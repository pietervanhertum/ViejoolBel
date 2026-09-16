"""Turns the stored plan into precise, timezone-aware ring jobs.

Rather than polling the clock once a second (campanella's approach), we register a
one-shot APScheduler job per ring for the current day, plus a daily re-plan just
after midnight and an on-demand :meth:`reload`. This is accurate, cheap, and does
not busy-wait.

A device with no real-time clock boots with a stale clock and only gets the right
time once NTP catches up — which, after transport, can be a whole day later. Two
safeguards keep the bell correct through that (see DESIGN.md §3.4/§4.1):

* Before the first plan we briefly wait for the clock to synchronise, so we plan
  against the right day (bounded, so an offline device still starts).
* A watchdog re-plans whenever the wall clock moves to another day or jumps, so a
  late NTP correction self-heals within a minute instead of leaving the day unplanned.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import Session

from .bell import BellController
from .db import record_event, session_scope
from .models import EV_CLOCK_UNSYNCED, EV_RING_MISSED, EventLog, RingLog, RingSource
from .schedule_service import PlannedRing, planned_rings_for

log = logging.getLogger(__name__)

# systemd-timesyncd touches this file once the clock is synchronised. Its parent
# directory only exists where timesyncd runs, so its absence means "not a
# timesync device" (dev laptops, CI, containers) and the startup wait is skipped.
_TIMESYNC_DIR = Path("/run/systemd/timesync")
_TIMESYNC_MARKER = _TIMESYNC_DIR / "synchronized"

# A scheduled ring may fire up to ``misfire_grace_time`` late; match a logged ring
# to a planned time within this window when deciding whether a past ring is a miss.
_RING_MATCH_TOLERANCE = dt.timedelta(seconds=120)


class BellScheduler:
    def __init__(
        self,
        controller: BellController,
        timezone: str,
        *,
        startup_sync_wait_seconds: float = 0.0,
        watchdog_seconds: float = 60.0,
    ) -> None:
        self._controller = controller
        self._tz = ZoneInfo(timezone)
        self._scheduler = BackgroundScheduler(timezone=self._tz)
        self._startup_sync_wait = startup_sync_wait_seconds
        self._watchdog_seconds = watchdog_seconds
        # The date the current plan was computed for, and the wall clock at the last
        # watchdog tick — used to detect day rollovers and clock jumps.
        self._planned_date: dt.date | None = None
        self._last_tick: dt.datetime | None = None

    def start(self) -> None:
        # Re-plan every day at 00:01 local time. A generous grace + coalesce means a
        # late wake-up (loaded Pi, clock jitter) never silently drops the re-plan —
        # the default grace is 1 s, which is far too tight for an unattended device.
        self._scheduler.add_job(
            self.reload,
            trigger="cron",
            hour=0,
            minute=1,
            id="daily-replan",
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
        )
        # Safety net against a stale-clock boot / missed re-plan (see module docstring).
        if self._watchdog_seconds > 0:
            self._scheduler.add_job(
                self._watchdog,
                trigger="interval",
                seconds=self._watchdog_seconds,
                id="replan-watchdog",
                replace_existing=True,
                misfire_grace_time=int(self._watchdog_seconds),
                coalesce=True,
            )
        self._wait_for_clock_sync()
        self._scheduler.start()
        self._last_tick = self.now()
        self.reload()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def is_alive(self) -> bool:
        return self._scheduler.running

    def now(self) -> dt.datetime:
        return dt.datetime.now(self._tz)

    def reload(self) -> list[PlannedRing]:
        """Recompute today's plan and (re)register ring jobs. Call after any
        config change so edits take effect immediately."""
        today = self.now().date()
        first_plan_for_date = self._planned_date != today
        for job in self._scheduler.get_jobs():
            if job.id and job.id.startswith("ring-"):
                job.remove()

        with session_scope() as s:
            plan = planned_rings_for(s, today)

        now = self.now()
        registered = 0
        skipped: list[PlannedRing] = []
        for pr in plan:
            run_at = dt.datetime.combine(today, pr.at, tzinfo=self._tz)
            if run_at <= now:
                skipped.append(pr)  # already past today; not replayed (see DESIGN.md §3.4)
                continue
            self._scheduler.add_job(
                self._fire,
                trigger="date",
                run_date=run_at,
                args=[pr],
                id=f"ring-{pr.event_id}",
                replace_existing=True,
                misfire_grace_time=30,
            )
            registered += 1
        # Record genuinely-missed rings, but only the first time we plan a given
        # date (a later reload from a config edit skips the same past rings, which
        # is normal, not a miss). Cross-checked against the ring log so a restart
        # after some bells already rang does not report them as missed.
        if first_plan_for_date and skipped:
            self._record_missed(today, skipped)
        self._planned_date = today
        log.info(
            "Planned %d ring(s) for %s (%d already past).",
            registered,
            today,
            len(skipped),
        )
        return plan

    def next_ring(self) -> dt.datetime | None:
        times = [
            job.next_run_time
            for job in self._scheduler.get_jobs()
            if job.id and job.id.startswith("ring-") and job.next_run_time
        ]
        return min(times) if times else None

    # --- robustness helpers ---------------------------------------------
    def _watchdog(self) -> None:
        """Re-plan when the wall clock moves to another day or jumps. Cheap, so it
        can run often; :meth:`reload` is idempotent."""
        now = self.now()
        reason = None
        if self._planned_date != now.date():
            reason = f"plan is for {self._planned_date}, today is {now.date()}"
        elif self._last_tick is not None:
            drift = abs((now - self._last_tick).total_seconds()) - self._watchdog_seconds
            if drift > max(2 * self._watchdog_seconds, 120):
                reason = f"clock jumped ~{drift:.0f}s"
        self._last_tick = now
        if reason:
            log.warning("Watchdog re-planning: %s.", reason)
            self.reload()

    def _wait_for_clock_sync(self) -> None:
        """Block (bounded) until the system clock is synchronised, so the first plan
        uses the right day. No-op where timesyncd is absent, so dev/CI never wait."""
        if self._startup_sync_wait <= 0 or not _TIMESYNC_DIR.exists():
            return
        if _TIMESYNC_MARKER.exists():
            return
        log.info("Waiting up to %.0fs for the clock to synchronise…", self._startup_sync_wait)
        deadline = time.monotonic() + self._startup_sync_wait
        while time.monotonic() < deadline:
            if _TIMESYNC_MARKER.exists():
                log.info("Clock synchronised; planning against the correct time.")
                return
            time.sleep(0.5)
        log.warning(
            "Clock still not synchronised after %.0fs; planning anyway.",
            self._startup_sync_wait,
        )
        with session_scope() as s:
            record_event(
                s,
                EV_CLOCK_UNSYNCED,
                f"Klok niet gesynchroniseerd na {self._startup_sync_wait:.0f}s bij start; "
                "rooster mogelijk op verkeerde tijd gepland. Overweeg een RTC-module.",
                level="warn",
            )

    def _record_missed(self, date: dt.date, skipped: list[PlannedRing]) -> None:
        with session_scope() as s:
            for pr in skipped:
                if self._scheduled_ring_logged(s, date, pr.at):
                    continue  # it actually rang; not a miss
                # The prefix (time + label + date) uniquely identifies the miss, so
                # matching on it dedupes across a restart without an ugly marker in
                # the user-visible text (labels never contain SQL LIKE wildcards).
                prefix = f"Gemiste bel {pr.at:%H:%M} '{pr.label}' op {date.isoformat()}"
                if self._miss_already_logged(s, prefix):
                    continue
                record_event(
                    s,
                    EV_RING_MISSED,
                    f"{prefix} — dienst was niet actief op dat tijdstip; niet ingehaald.",
                    level="warn",
                )

    def _miss_already_logged(self, s: Session, prefix: str) -> bool:
        return (
            s.scalar(
                select(EventLog.id)
                .where(EventLog.kind == EV_RING_MISSED, EventLog.detail.like(f"{prefix}%"))
                .limit(1)
            )
            is not None
        )

    def _scheduled_ring_logged(self, s: Session, date: dt.date, at: dt.time) -> bool:
        # RingLog.ts is naive UTC; convert the planned local time the same way.
        local = dt.datetime.combine(date, at, tzinfo=self._tz)
        utc_naive = local.astimezone(dt.UTC).replace(tzinfo=None)
        return (
            s.scalar(
                select(RingLog.id)
                .where(
                    RingLog.source == RingSource.SCHEDULED,
                    RingLog.ts >= utc_naive - _RING_MATCH_TOLERANCE,
                    RingLog.ts <= utc_naive + _RING_MATCH_TOLERANCE,
                )
                .limit(1)
            )
            is not None
        )

    def _fire(self, pr: PlannedRing) -> None:
        self._controller.ring(
            source=RingSource.SCHEDULED,
            sound_id=pr.sound_id,
            duration=pr.duration,
            use_audio=pr.use_audio,
            use_relay=pr.use_relay,
        )

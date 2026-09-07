"""Turns the stored plan into precise, timezone-aware ring jobs.

Rather than polling the clock once a second (campanella's approach), we register a
one-shot APScheduler job per ring for the current day, plus a daily re-plan just
after midnight and an on-demand :meth:`reload`. This is accurate, cheap, and does
not busy-wait.
"""

from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from .bell import BellController
from .db import session_scope
from .models import RingSource
from .schedule_service import PlannedRing, planned_rings_for

log = logging.getLogger(__name__)


class BellScheduler:
    def __init__(self, controller: BellController, timezone: str) -> None:
        self._controller = controller
        self._tz = ZoneInfo(timezone)
        self._scheduler = BackgroundScheduler(timezone=self._tz)

    def start(self) -> None:
        # Re-plan every day at 00:01 local time, and immediately.
        self._scheduler.add_job(
            self.reload,
            trigger="cron",
            hour=0,
            minute=1,
            id="daily-replan",
            replace_existing=True,
        )
        self._scheduler.start()
        self.reload()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def now(self) -> dt.datetime:
        return dt.datetime.now(self._tz)

    def reload(self) -> list[PlannedRing]:
        """Recompute today's plan and (re)register ring jobs. Call after any
        config change so edits take effect immediately."""
        today = self.now().date()
        for job in self._scheduler.get_jobs():
            if job.id and job.id.startswith("ring-"):
                job.remove()

        with session_scope() as s:
            plan = planned_rings_for(s, today)

        now = self.now()
        registered = 0
        for pr in plan:
            run_at = dt.datetime.combine(today, pr.at, tzinfo=self._tz)
            if run_at <= now:
                continue  # already past today; not replayed (see DESIGN.md §3.4)
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
        log.info(
            "Planned %d ring(s) for %s (%d already past).",
            registered,
            today,
            len(plan) - registered,
        )
        return plan

    def next_ring(self) -> dt.datetime | None:
        times = [
            job.next_run_time
            for job in self._scheduler.get_jobs()
            if job.id and job.id.startswith("ring-") and job.next_run_time
        ]
        return min(times) if times else None

    def _fire(self, pr: PlannedRing) -> None:
        self._controller.ring(
            source=RingSource.SCHEDULED,
            sound_id=pr.sound_id,
            duration=pr.duration,
            use_audio=pr.use_audio,
            use_relay=pr.use_relay,
        )

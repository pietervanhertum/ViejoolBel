"""Tests for the ring scheduler: past-ring skipping, missed-ring recording, and
the no-RTC safety net (day rollover / clock-jump re-planning). See DESIGN.md §3.4."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy import select

from viejoolbel.db import session_scope
from viejoolbel.models import (
    EV_RING_MISSED,
    BellEvent,
    DayType,
    EventLog,
    RingLog,
    RingSource,
)

TZ = ZoneInfo("Europe/Brussels")
# 2026-09-14 is a Monday, 2026-09-16 a Wednesday — both weekdays, so the seeded
# Mon–Fri default day-type applies.
MONDAY = dt.date(2026, 9, 14)
WEDNESDAY = dt.date(2026, 9, 16)


def _default_day_type_id() -> int:
    with session_scope() as s:
        return s.scalars(select(DayType)).first().id


def _add_event(hh: int, mm: int, label: str = "") -> None:
    with session_scope() as s:
        s.add(
            BellEvent(
                day_type_id=_default_day_type_id(),
                at=dt.time(hh, mm),
                duration=8,
                label=label,
            )
        )


def _at(date: dt.date, hh: int, mm: int) -> dt.datetime:
    return dt.datetime(date.year, date.month, date.day, hh, mm, tzinfo=TZ)


def _ring_job_ids(scheduler) -> list[str]:
    return [j.id for j in scheduler._scheduler.get_jobs() if j.id and j.id.startswith("ring-")]


def _miss_details() -> list[str]:
    with session_scope() as s:
        return list(
            s.scalars(select(EventLog.detail).where(EventLog.kind == EV_RING_MISSED))
        )


def _log_scheduled_ring(when_local: dt.datetime) -> None:
    with session_scope() as s:
        s.add(
            RingLog(
                ts=when_local.astimezone(dt.UTC).replace(tzinfo=None),
                source=RingSource.SCHEDULED,
                sound_name="Schoolbel",
                ok=True,
            )
        )


def test_reload_registers_future_and_skips_past(scheduler, initialized_db):
    _add_event(8, 40, "Ochtend")
    _add_event(10, 20, "Speeltijd")
    scheduler.now = lambda: _at(WEDNESDAY, 9, 0)

    plan = scheduler.reload()

    assert len(plan) == 2  # the plan lists everything
    assert len(_ring_job_ids(scheduler)) == 1  # but only 10:20 is registered to fire
    assert scheduler._planned_date == WEDNESDAY


def test_missed_past_ring_is_recorded_once(scheduler, initialized_db):
    _add_event(8, 40, "Ochtend")
    scheduler.now = lambda: _at(WEDNESDAY, 9, 0)

    scheduler.reload()
    details = _miss_details()
    assert len(details) == 1
    assert "08:40" in details[0]
    assert "Ochtend" in details[0]

    # A second reload on the same day (e.g. from a config edit) must not re-record it.
    scheduler.reload()
    assert len(_miss_details()) == 1

    # Even a restart after the miss (fresh process → planned_date reset) must not
    # re-record it: this is exactly the remediation of restarting the service.
    scheduler._planned_date = None
    scheduler.reload()
    assert len(_miss_details()) == 1


def test_past_ring_that_actually_rang_is_not_a_miss(scheduler, initialized_db):
    _add_event(8, 40, "Ochtend")
    _log_scheduled_ring(_at(WEDNESDAY, 8, 40))  # it fired on time
    scheduler.now = lambda: _at(WEDNESDAY, 9, 0)

    scheduler.reload()

    assert _miss_details() == []


def test_no_miss_recorded_when_nothing_is_past(scheduler, initialized_db):
    _add_event(10, 20, "Speeltijd")
    scheduler.now = lambda: _at(WEDNESDAY, 9, 0)

    scheduler.reload()

    assert _miss_details() == []
    assert len(_ring_job_ids(scheduler)) == 1


def test_watchdog_replans_when_clock_jumps_to_a_new_day(scheduler, initialized_db):
    """The reported failure: booted with a stale (Monday) clock, planned nothing
    useful, then NTP stepped the clock to Wednesday. The watchdog must re-plan."""
    _add_event(8, 40, "Ochtend")

    # First plan happens late Monday with a stale clock: 08:40 is already past.
    scheduler.now = lambda: _at(MONDAY, 23, 0)
    scheduler._last_tick = _at(MONDAY, 23, 0)
    scheduler.reload()
    assert scheduler._planned_date == MONDAY
    assert _ring_job_ids(scheduler) == []  # nothing left to fire Monday night

    # NTP steps the clock to Wednesday 08:00 — before the 08:40 bell.
    scheduler.now = lambda: _at(WEDNESDAY, 8, 0)
    scheduler._watchdog()

    assert scheduler._planned_date == WEDNESDAY
    assert len(_ring_job_ids(scheduler)) == 1  # 08:40 is now registered to fire


def test_watchdog_replans_on_large_same_day_clock_jump(scheduler, initialized_db):
    _add_event(10, 20, "Speeltijd")
    scheduler.now = lambda: _at(WEDNESDAY, 8, 0)
    scheduler.reload()
    scheduler._last_tick = _at(WEDNESDAY, 8, 0)

    calls: list[int] = []
    original = scheduler.reload
    scheduler.reload = lambda: (calls.append(1), original())[1]

    # Clock jumps forward an hour within the same day.
    scheduler.now = lambda: _at(WEDNESDAY, 9, 0)
    scheduler._watchdog()

    assert calls  # a jump larger than the tolerance triggers a re-plan


def test_watchdog_quiet_on_normal_tick(scheduler, initialized_db):
    _add_event(10, 20, "Speeltijd")
    scheduler.now = lambda: _at(WEDNESDAY, 8, 0)
    scheduler.reload()
    scheduler._last_tick = _at(WEDNESDAY, 8, 0)

    calls: list[int] = []
    original = scheduler.reload
    scheduler.reload = lambda: (calls.append(1), original())[1]

    # A normal tick one watchdog-interval later must not re-plan.
    scheduler.now = lambda: _at(WEDNESDAY, 8, 0) + dt.timedelta(seconds=scheduler._watchdog_seconds)
    scheduler._watchdog()

    assert calls == []

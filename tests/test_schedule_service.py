"""Tests for turning stored config into today's concrete plan (FR-1,3,13)."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from viejoolbel.db import session_scope, set_setting
from viejoolbel.models import BellEvent, CalendarRule, CalendarRuleKind, DayType
from viejoolbel.schedule_service import is_silenced_today, planned_rings_for


def _add_event(day_type_id: int, hh: int, mm: int) -> None:
    with session_scope() as s:
        s.add(BellEvent(day_type_id=day_type_id, at=dt.time(hh, mm), duration=8))


def _default_day_type_id() -> int:
    with session_scope() as s:
        return s.scalars(select(DayType)).first().id


def test_plan_lists_events_on_a_weekday(initialized_db):
    dtid = _default_day_type_id()
    _add_event(dtid, 8, 30)
    _add_event(dtid, 10, 15)
    monday = dt.date(2025, 9, 8)
    with session_scope() as s:
        plan = planned_rings_for(s, monday)
    assert [p.at for p in plan] == [dt.time(8, 30), dt.time(10, 15)]


def test_plan_empty_on_weekend(initialized_db):
    dtid = _default_day_type_id()
    _add_event(dtid, 8, 30)
    saturday = dt.date(2025, 9, 13)
    with session_scope() as s:
        assert planned_rings_for(s, saturday) == []


def test_plan_empty_on_closed_calendar_day(initialized_db):
    dtid = _default_day_type_id()
    _add_event(dtid, 8, 30)
    d = dt.date(2025, 9, 9)  # Tuesday
    with session_scope() as s:
        s.add(
            CalendarRule(
                start_date=d, end_date=d, kind=CalendarRuleKind.CLOSED, note="Studiedag"
            )
        )
    with session_scope() as s:
        assert planned_rings_for(s, d) == []


def test_silence_today_suppresses_plan(initialized_db):
    dtid = _default_day_type_id()
    _add_event(dtid, 8, 30)
    monday = dt.date(2025, 9, 8)
    with session_scope() as s:
        set_setting(s, "silence_date", monday.isoformat())
    with session_scope() as s:
        assert is_silenced_today(s, monday)
        assert planned_rings_for(s, monday) == []

"""Unit tests for the pure calendar resolution (FR-3, FR-4)."""

from __future__ import annotations

import datetime as dt

from viejoolbel.calendar import resolve_day
from viejoolbel.models import CalendarRule, CalendarRuleKind, WeekdayDefault


def _wd(weekday: int, kind: CalendarRuleKind, day_type_id: int | None) -> WeekdayDefault:
    return WeekdayDefault(weekday=weekday, kind=kind, day_type_id=day_type_id)


def _rule(id_, start, end, kind, day_type_id=None, note=""):
    r = CalendarRule(
        start_date=start, end_date=end, kind=kind, day_type_id=day_type_id, note=note
    )
    r.id = id_
    return r


DEFAULTS = {
    wd: _wd(
        wd,
        CalendarRuleKind.DAY_TYPE if wd < 5 else CalendarRuleKind.CLOSED,
        1 if wd < 5 else None,
    )
    for wd in range(7)
}


def test_weekday_default_rings_on_a_weekday():
    monday = dt.date(2025, 9, 8)  # a Monday
    res = resolve_day(monday, rules=[], weekday_defaults=DEFAULTS)
    assert res.rings and res.day_type_id == 1


def test_weekend_is_closed_by_default():
    saturday = dt.date(2025, 9, 13)
    res = resolve_day(saturday, rules=[], weekday_defaults=DEFAULTS)
    assert res.closed and not res.rings


def test_vacation_range_closes_a_weekday():
    d = dt.date(2025, 9, 9)  # Tuesday, normally rings
    rules = [
        _rule(1, dt.date(2025, 9, 8), dt.date(2025, 9, 12), CalendarRuleKind.CLOSED, note="Herfst")
    ]
    res = resolve_day(d, rules=rules, weekday_defaults=DEFAULTS)
    assert res.closed
    assert "Herfst" in res.reason


def test_single_date_override_beats_range():
    d = dt.date(2025, 9, 10)
    rules = [
        _rule(1, dt.date(2025, 9, 8), dt.date(2025, 9, 12), CalendarRuleKind.CLOSED),
        _rule(2, d, d, CalendarRuleKind.DAY_TYPE, day_type_id=7, note="Examen"),
    ]
    res = resolve_day(d, rules=rules, weekday_defaults=DEFAULTS)
    assert res.rings and res.day_type_id == 7


def test_shortest_range_wins_on_overlap():
    d = dt.date(2025, 9, 10)
    rules = [
        _rule(1, dt.date(2025, 9, 1), dt.date(2025, 9, 30), CalendarRuleKind.CLOSED),
        _rule(
            2, dt.date(2025, 9, 8), dt.date(2025, 9, 12), CalendarRuleKind.DAY_TYPE, day_type_id=3
        ),
    ]
    res = resolve_day(d, rules=rules, weekday_defaults=DEFAULTS)
    assert res.rings and res.day_type_id == 3


def test_no_rule_fails_safe_closed():
    d = dt.date(2025, 9, 8)
    res = resolve_day(d, rules=[], weekday_defaults={})
    assert res.closed

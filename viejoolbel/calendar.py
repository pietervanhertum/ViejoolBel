"""Calendar resolution: given a date, decide whether the school is closed or which
day-type applies (FR-3, FR-4).

This module is intentionally **pure**: it takes plain data structures, does no I/O,
and returns a :class:`DayResolution`. That makes the priority rules exhaustively
unit-testable without a database or a Raspberry Pi.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .models import CalendarRule, CalendarRuleKind, WeekdayDefault


@dataclass(frozen=True)
class DayResolution:
    closed: bool
    day_type_id: int | None
    reason: str  # human-readable explanation, shown in the UI

    @property
    def rings(self) -> bool:
        return not self.closed and self.day_type_id is not None


def resolve_day(
    date: dt.date,
    *,
    rules: list[CalendarRule],
    weekday_defaults: dict[int, WeekdayDefault],
) -> DayResolution:
    """Resolve *date* to a :class:`DayResolution`.

    Priority, highest first (FR-4):

    1. A single-date rule (``start_date == end_date == date``).
    2. A date-range rule that contains *date* (e.g. a vacation week). If several
       ranges match, the **shortest** (most specific) wins; ties break on the
       latest start date.
    3. The weekday default for ``date.weekday()``.
    4. Closed (fail safe: if nothing matches, do not ring).
    """
    single = [r for r in rules if r.start_date == r.end_date == date]
    if single:
        # Deterministic: last-created single-date rule wins.
        return _from_rule(max(single, key=lambda r: r.id or 0), "date override")

    ranges = [
        r
        for r in rules
        if r.start_date <= date <= r.end_date and r.start_date != r.end_date
    ]
    if ranges:
        best = min(ranges, key=lambda r: ((r.end_date - r.start_date).days, -(r.id or 0)))
        return _from_rule(best, "calendar range")

    wd = weekday_defaults.get(date.weekday())
    if wd is not None:
        if wd.kind is CalendarRuleKind.CLOSED:
            return DayResolution(True, None, "weekday closed")
        return DayResolution(False, wd.day_type_id, "weekday default")

    return DayResolution(True, None, "no rule (fail-safe closed)")


def _from_rule(rule: CalendarRule, reason: str) -> DayResolution:
    if rule.kind is CalendarRuleKind.CLOSED:
        note = f"{reason}: {rule.note}" if rule.note else reason
        return DayResolution(True, None, note)
    note = f"{reason}: {rule.note}" if rule.note else reason
    return DayResolution(False, rule.day_type_id, note)

"""Read-side helpers that turn stored config into today's concrete plan.

Kept separate from the scheduler so the "what should ring today" computation is
pure-ish (only DB reads) and directly unit-testable.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .calendar import DayResolution, resolve_day
from .db import get_setting
from .models import BellEvent, CalendarRule, DayType, WeekdayDefault


@dataclass(frozen=True)
class PlannedRing:
    at: dt.time
    event_id: int
    sound_id: int | None
    duration: int
    use_audio: bool
    use_relay: bool
    label: str


def _load_calendar(s: Session) -> tuple[list[CalendarRule], dict[int, WeekdayDefault]]:
    rules = list(s.scalars(select(CalendarRule)))
    weekday_defaults = {wd.weekday: wd for wd in s.scalars(select(WeekdayDefault))}
    return rules, weekday_defaults


def resolution_for(s: Session, date: dt.date) -> DayResolution:
    rules, weekday_defaults = _load_calendar(s)
    return resolve_day(date, rules=rules, weekday_defaults=weekday_defaults)


def is_silenced_today(s: Session, date: dt.date) -> bool:
    """FR-13: 'silence today' stores the ISO date it applies to."""
    return get_setting(s, "silence_date", "") == date.isoformat()


def planned_rings_for(s: Session, date: dt.date) -> list[PlannedRing]:
    """Concrete rings for *date*, honouring the calendar and 'silence today'.

    Returns an empty list when the day is closed or silenced.
    """
    if is_silenced_today(s, date):
        return []
    resolution = resolution_for(s, date)
    if not resolution.rings or resolution.day_type_id is None:
        return []
    day_type = s.get(DayType, resolution.day_type_id)
    if day_type is None:
        return []
    events = s.scalars(
        select(BellEvent).where(BellEvent.day_type_id == day_type.id).order_by(BellEvent.at)
    )
    return [
        PlannedRing(
            at=e.at,
            event_id=e.id,
            sound_id=e.sound_id,
            duration=e.duration,
            use_audio=e.use_audio,
            use_relay=e.use_relay,
            label=e.label,
        )
        for e in events
    ]

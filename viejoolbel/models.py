"""SQLAlchemy ORM models. See DESIGN.md §3.2 and SPEC.md §3 for semantics."""

from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Sound(Base):
    """An uploaded audio file usable by bell events and manual rings."""

    __tablename__ = "sounds"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    filename: Mapped[str] = mapped_column(String(255))  # stored under settings.sounds_dir
    default_duration: Mapped[int] = mapped_column(Integer, default=8)  # seconds
    # A distinct evacuation/alarm sound (FR-9); at most one is typically flagged.
    is_alarm: Mapped[bool] = mapped_column(Boolean, default=False)

    events: Mapped[list[BellEvent]] = relationship(back_populates="sound")


class DayType(Base):
    """A named timetable, e.g. 'Normal', 'Wednesday', 'Exam' (FR-2)."""

    __tablename__ = "day_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    events: Mapped[list[BellEvent]] = relationship(
        back_populates="day_type",
        cascade="all, delete-orphan",
        order_by="BellEvent.at",
    )


class BellEvent(Base):
    """A single ring within a day-type (FR-5)."""

    __tablename__ = "bell_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    day_type_id: Mapped[int] = mapped_column(ForeignKey("day_types.id", ondelete="CASCADE"))
    at: Mapped[dt.time] = mapped_column(Time)  # local wall-clock time
    sound_id: Mapped[int | None] = mapped_column(ForeignKey("sounds.id"))
    use_audio: Mapped[bool] = mapped_column(Boolean, default=True)
    use_relay: Mapped[bool] = mapped_column(Boolean, default=True)
    duration: Mapped[int] = mapped_column(Integer, default=8)  # seconds
    label: Mapped[str] = mapped_column(String(120), default="")

    day_type: Mapped[DayType] = relationship(back_populates="events")
    sound: Mapped[Sound | None] = relationship(back_populates="events")


class CalendarRuleKind(enum.StrEnum):
    CLOSED = "closed"  # nothing rings
    DAY_TYPE = "day_type"  # use a specific day-type


class CalendarRule(Base):
    """Maps concrete dates (or ranges) to a day-type or marks them closed (FR-3).

    Weekday defaults live in :class:`WeekdayDefault`; these rules override them.
    Priority (highest first): single-date rule > date-range rule (see calendar.py).
    """

    __tablename__ = "calendar_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    start_date: Mapped[dt.date] = mapped_column(Date)
    end_date: Mapped[dt.date] = mapped_column(Date)  # inclusive; == start for single day
    kind: Mapped[CalendarRuleKind] = mapped_column(Enum(CalendarRuleKind))
    day_type_id: Mapped[int | None] = mapped_column(ForeignKey("day_types.id"))
    note: Mapped[str] = mapped_column(String(200), default="")

    day_type: Mapped[DayType | None] = relationship()


class WeekdayDefault(Base):
    """Default day-type per weekday (0=Monday .. 6=Sunday) (FR-1, FR-4)."""

    __tablename__ = "weekday_defaults"

    weekday: Mapped[int] = mapped_column(Integer, primary_key=True)  # 0..6
    kind: Mapped[CalendarRuleKind] = mapped_column(
        Enum(CalendarRuleKind), default=CalendarRuleKind.CLOSED
    )
    day_type_id: Mapped[int | None] = mapped_column(ForeignKey("day_types.id"))

    day_type: Mapped[DayType | None] = relationship()


class RingSource(enum.StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    BUTTON = "button"
    TEST = "test"


class RingLog(Base):
    """Audit record of every ring (FR-24)."""

    __tablename__ = "ring_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stored as naive UTC for consistent comparisons across SQLite.
    ts: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.UTC).replace(tzinfo=None)
    )
    source: Mapped[RingSource] = mapped_column(Enum(RingSource))
    sound_name: Mapped[str] = mapped_column(String(120), default="")
    used_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    used_relay: Mapped[bool] = mapped_column(Boolean, default=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    detail: Mapped[str] = mapped_column(String(300), default="")


class Setting(Base):
    """Key/value application settings (FR-13 silence-today, auth, volume, …)."""

    __tablename__ = "settings"
    __table_args__ = (UniqueConstraint("key"),)

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), default="")


# Well-known event kinds for :class:`EventLog`. Kept as plain strings (not an
# Enum column) so new kinds can be added without a schema migration.
EV_HEALTH_FAULT = "health_fault"
EV_HEALTH_RECOVERED = "health_recovered"
EV_AP_FALLBACK = "ap_fallback"
EV_SERVICE_STARTED = "service_started"


class EventLog(Base):
    """Durable audit trail of operational events (health transitions, the offline
    safety-net opening the AP, …), so a post-mortem does not depend on journald
    surviving a reboot. Written by the health monitor; trimmed to a bounded size.
    """

    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stored as naive UTC for consistent comparisons across SQLite (like RingLog).
    ts: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.UTC).replace(tzinfo=None)
    )
    kind: Mapped[str] = mapped_column(String(40))
    level: Mapped[str] = mapped_column(String(10), default="info")  # ok/warn/error/info
    detail: Mapped[str] = mapped_column(String(500), default="")


# Schema version, bumped when models change; see db.migrate().
SCHEMA_VERSION = 1

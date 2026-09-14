"""Health evaluation: collect a set of checks into one report.

Kept mostly pure — it takes injected facts (system time, disk free, scheduler
liveness) and reads recent ring outcomes — so the severity logic is unit-testable
without hardware or real time (FR-24, NFR-2). See DESIGN.md §5.
"""

from __future__ import annotations

import datetime as dt
import enum
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import RingLog


class Level(enum.StrEnum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"

    @property
    def rank(self) -> int:
        return {"ok": 0, "warn": 1, "error": 2}[self.value]


@dataclass(frozen=True)
class Check:
    name: str
    level: Level
    detail: str

    @property
    def ok(self) -> bool:
        return self.level is Level.OK


@dataclass(frozen=True)
class HealthReport:
    generated_at: dt.datetime
    checks: list[Check] = field(default_factory=list)

    @property
    def level(self) -> Level:
        return max((c.level for c in self.checks), key=lambda lvl: lvl.rank, default=Level.OK)

    @property
    def ok(self) -> bool:
        return self.level is Level.OK

    @property
    def problems(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def as_dict(self) -> dict:
        return {
            "generated_at": self.generated_at.isoformat(),
            "level": self.level.value,
            "ok": self.ok,
            "checks": [
                {"name": c.name, "level": c.level.value, "ok": c.ok, "detail": c.detail}
                for c in self.checks
            ],
        }


def check_clock(now: dt.datetime, min_year: int) -> Check:
    if now.year < min_year:
        return Check(
            "clock",
            Level.ERROR,
            f"System clock reads {now.year}; it is not set. Bells will ring at the "
            "wrong time. Fit a DS3231 RTC or restore internet for NTP.",
        )
    return Check("clock", Level.OK, f"System time OK ({now:%Y-%m-%d %H:%M}).")


def check_disk(data_dir: Path, *, warn_mb: int = 200) -> Check:
    try:
        free_mb = shutil.disk_usage(data_dir).free // (1024 * 1024)
    except OSError as exc:
        return Check("disk", Level.ERROR, f"Cannot stat {data_dir}: {exc}")
    if free_mb < warn_mb:
        return Check("disk", Level.WARN, f"Low disk space: {free_mb} MB free.")
    return Check("disk", Level.OK, f"{free_mb} MB free.")


def check_scheduler(alive: bool) -> Check:
    if alive:
        return Check("scheduler", Level.OK, "Scheduler running.")
    return Check("scheduler", Level.ERROR, "Scheduler is not running.")


def check_hardware(hardware: object) -> Check:
    """Flag when the bell is running on the simulation driver on a real device.

    A silent fall-back to the mock driver (typically RPi.GPIO missing) makes every
    ring 'succeed' while nothing physically fires — the baffling case where the
    'Bel nu' button does nothing yet ``ffplay`` over SSH still makes sound. Surface
    it as an error so it is visible on the dashboard instead of hidden in the log.
    """
    reason = getattr(hardware, "fallback_reason", None)
    if reason:
        return Check("hardware", Level.ERROR, str(reason))
    return Check("hardware", Level.OK, f"Bell driver active ({type(hardware).__name__}).")


def check_recent_rings(s: Session, now: dt.datetime, *, window_hours: int = 24) -> Check:
    since = now.astimezone(dt.UTC).replace(tzinfo=None) - dt.timedelta(hours=window_hours)
    failures = list(
        s.scalars(select(RingLog).where(RingLog.ts >= since, RingLog.ok.is_(False)))
    )
    if failures:
        last = failures[-1]
        return Check(
            "rings",
            Level.ERROR,
            f"{len(failures)} failed ring(s) in {window_hours}h; last: {last.detail}",
        )
    return Check("rings", Level.OK, "No ring failures recently.")


def evaluate(
    s: Session,
    *,
    now: dt.datetime,
    data_dir: Path,
    scheduler_alive: bool,
    min_year: int,
    hardware: object | None = None,
) -> HealthReport:
    checks = [
        check_scheduler(scheduler_alive),
        check_clock(now, min_year),
        check_recent_rings(s, now),
        check_disk(data_dir),
    ]
    if hardware is not None:
        checks.append(check_hardware(hardware))
    return HealthReport(generated_at=now, checks=checks)

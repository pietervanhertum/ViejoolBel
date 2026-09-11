"""Database engine, session factory, seeding and a minimal migration runner."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    SCHEMA_VERSION,
    Base,
    CalendarRuleKind,
    DayType,
    EventLog,
    Setting,
    Sound,
    WeekdayDefault,
)

# Bundled starter sounds installed on first run so the bell works out of the box.
# (name, filename, default_duration_seconds, is_alarm)
DEFAULT_SOUNDS: list[tuple[str, str, int, bool]] = [
    ("Enkele bel", "enkele-bel.wav", 3, False),
    ("Dubbele bel", "dubbele-bel.wav", 4, False),
    ("Schoolbel", "schoolbel.wav", 4, False),
    ("Gong", "gong.wav", 4, False),
]
_ASSETS_SOUNDS_DIR = Path(__file__).parent / "assets" / "sounds"

_SESSION_FACTORY: sessionmaker[Session] | None = None


def init_engine(db_path: Path, *, echo: bool = False) -> sessionmaker[Session]:
    """Create the engine + tables and return a session factory.

    Uses ``check_same_thread=False`` because the scheduler and the web server run
    in different threads within the one service process.
    """
    global _SESSION_FACTORY
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=echo,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    _SESSION_FACTORY = sessionmaker(engine, expire_on_commit=False)
    with session_scope() as s:
        migrate(s)
        seed_defaults(s)
    return _SESSION_FACTORY


@contextmanager
def session_scope() -> Iterator[Session]:
    if _SESSION_FACTORY is None:
        raise RuntimeError("Database not initialised; call init_engine() first.")
    session = _SESSION_FACTORY()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_setting(s: Session, key: str, default: str = "") -> str:
    row = s.get(Setting, key)
    return row.value if row is not None else default


def set_setting(s: Session, key: str, value: str) -> None:
    row = s.get(Setting, key)
    if row is None:
        s.add(Setting(key=key, value=value))
    else:
        row.value = value


# Keep at most this many event-log rows so the table can never grow without bound
# on a device that runs for years.
_EVENT_LOG_MAX_ROWS = 1000


def record_event(
    s: Session, kind: str, detail: str = "", *, level: str = "info"
) -> EventLog:
    """Append an operational event to the durable :class:`EventLog` and trim the
    table to :data:`_EVENT_LOG_MAX_ROWS`. Never raises on trim failure."""
    event = EventLog(kind=kind, level=level, detail=detail[:500])
    s.add(event)
    s.flush()
    # Trim oldest rows beyond the cap (cheap: only runs the delete when over).
    total = s.scalar(select(func.count()).select_from(EventLog)) or 0
    if total > _EVENT_LOG_MAX_ROWS:
        cutoff = s.scalar(
            select(EventLog.id).order_by(EventLog.id.desc()).offset(_EVENT_LOG_MAX_ROWS)
        )
        if cutoff is not None:
            s.query(EventLog).filter(EventLog.id <= cutoff).delete(synchronize_session=False)
    return event


def migrate(s: Session) -> None:
    """Very small forward-only migration runner keyed on the ``schema_version``
    setting. New migrations append an ``if current < N`` block."""
    current = int(get_setting(s, "schema_version", "0") or "0")
    # (Future migrations go here, each bumping ``current``.)
    if current < SCHEMA_VERSION:
        set_setting(s, "schema_version", str(SCHEMA_VERSION))


def seed_defaults(s: Session) -> None:
    """Create sensible defaults on a fresh database so the UI is usable at once."""
    if s.scalar(select(DayType).limit(1)) is None:
        normal = DayType(name="Gewone dag", is_default=True)
        s.add(normal)
        s.flush()
        # Monday–Friday default to the "Gewone dag" day-type; weekends closed.
        for wd in range(7):
            kind = CalendarRuleKind.DAY_TYPE if wd < 5 else CalendarRuleKind.CLOSED
            s.add(
                WeekdayDefault(
                    weekday=wd,
                    kind=kind,
                    day_type_id=normal.id if wd < 5 else None,
                )
            )
    # First-run admin credentials (bcrypt hash set lazily by auth on first use).
    if get_setting(s, "admin_username", "") == "":
        set_setting(s, "admin_username", "admin")


def install_default_sounds(s: Session, sounds_dir: Path) -> int:
    """Install the bundled starter sounds **once**, adding only the ones missing.

    Guarded by a one-time ``default_sounds_seeded`` flag so it runs a single time —
    including on an upgrade of a database that predates this feature (that is why a
    device installed at 0.1.0 had no default sounds). It adds each default only if
    no sound with that name exists, so it never duplicates or overwrites the user's
    own uploads, and after seeding it will not re-add sounds the user later deletes.
    Returns the number of sounds installed.
    """
    if get_setting(s, "default_sounds_seeded", "") == "1":
        return 0
    existing = set(s.scalars(select(Sound.name)))
    sounds_dir.mkdir(parents=True, exist_ok=True)
    installed = 0
    for name, filename, duration, is_alarm in DEFAULT_SOUNDS:
        if name in existing:
            continue
        src = _ASSETS_SOUNDS_DIR / filename
        if not src.exists():
            continue
        shutil.copyfile(src, sounds_dir / filename)
        s.add(Sound(name=name, filename=filename, default_duration=duration, is_alarm=is_alarm))
        installed += 1
    set_setting(s, "default_sounds_seeded", "1")
    return installed

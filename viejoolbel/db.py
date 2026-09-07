"""Database engine, session factory, seeding and a minimal migration runner."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    SCHEMA_VERSION,
    Base,
    CalendarRuleKind,
    DayType,
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
        normal = DayType(name="Normal", is_default=True)
        s.add(normal)
        s.flush()
        # Monday–Friday default to the Normal day-type; weekends closed.
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
    """Copy the bundled starter sounds into *sounds_dir* and register them, once.

    No-op when any sound already exists, so it never overwrites the user's own
    uploads. Returns the number of sounds installed.
    """
    if s.scalar(select(Sound).limit(1)) is not None:
        return 0
    sounds_dir.mkdir(parents=True, exist_ok=True)
    installed = 0
    for name, filename, duration, is_alarm in DEFAULT_SOUNDS:
        src = _ASSETS_SOUNDS_DIR / filename
        if not src.exists():
            continue
        shutil.copyfile(src, sounds_dir / filename)
        s.add(Sound(name=name, filename=filename, default_duration=duration, is_alarm=is_alarm))
        installed += 1
    return installed

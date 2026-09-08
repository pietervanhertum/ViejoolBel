"""Configuration backup & restore (FR-18).

The backup is a portable JSON document that references sounds and day-types **by
name**, so it can be moved between devices. It contains the full schedule
configuration (day-types + bell events, the weekly layout, the calendar) and the
app settings (volume, notification URLs) — but **not** the audio files themselves
(they stay on the device) nor the password.

Restore is a full replace of the schedule configuration; existing sounds (their
audio files) are kept and matched by name. An event whose sound is not present on
this device becomes relay-only, and the restore report says how many.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import __version__
from .db import get_setting, set_setting
from .models import BellEvent, CalendarRule, CalendarRuleKind, DayType, Sound, WeekdayDefault

FORMAT = "viejoolbel-backup"

# Settings included in a backup (key -> default). The password is deliberately
# excluded; the timezone is exported for reference but set at install time.
_BACKUP_SETTING_KEYS = ("volume_db", "notify_webhook_url", "heartbeat_url")


@dataclass
class ImportReport:
    day_types: int = 0
    events: int = 0
    weekday_defaults: int = 0
    calendar_rules: int = 0
    events_missing_sound: int = 0
    missing_sounds: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": True,
            "day_types": self.day_types,
            "events": self.events,
            "weekday_defaults": self.weekday_defaults,
            "calendar_rules": self.calendar_rules,
            "events_missing_sound": self.events_missing_sound,
            "missing_sounds": sorted(set(self.missing_sounds)),
        }


def _name(mapping: dict[int, str], key: int | None) -> str | None:
    return mapping.get(key) if key is not None else None


def export_config(s: Session, *, timezone: str) -> dict:
    id_to_name = {d.id: d.name for d in s.scalars(select(DayType))}
    sound_name = {snd.id: snd.name for snd in s.scalars(select(Sound))}

    return {
        "format": FORMAT,
        "version": __version__,
        "exported_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "settings": {
            "timezone": timezone,
            **{k: get_setting(s, k, "") for k in _BACKUP_SETTING_KEYS},
        },
        "sounds": [
            {"name": snd.name, "is_alarm": snd.is_alarm, "default_duration": snd.default_duration}
            for snd in s.scalars(select(Sound))
        ],
        "day_types": [
            {
                "name": d.name,
                "is_default": d.is_default,
                "events": [
                    {
                        "at": e.at.strftime("%H:%M"),
                        "sound": _name(sound_name, e.sound_id),
                        "use_audio": e.use_audio,
                        "use_relay": e.use_relay,
                        "duration": e.duration,
                        "label": e.label,
                    }
                    for e in d.events
                ],
            }
            for d in s.scalars(select(DayType))
        ],
        "weekday_defaults": [
            {
                "weekday": wd.weekday,
                "kind": wd.kind.value,
                "day_type": _name(id_to_name, wd.day_type_id),
            }
            for wd in s.scalars(select(WeekdayDefault))
        ],
        "calendar_rules": [
            {
                "start_date": r.start_date.isoformat(),
                "end_date": r.end_date.isoformat(),
                "kind": r.kind.value,
                "day_type": _name(id_to_name, r.day_type_id),
                "note": r.note,
            }
            for r in s.scalars(select(CalendarRule))
        ],
    }


def _resolve_ref(entry: dict, name_to_id: dict[str, int]) -> tuple[CalendarRuleKind, int | None]:
    """Resolve a {kind, day_type: name} reference to (kind, day_type_id)."""
    dtid = name_to_id.get(str(entry.get("day_type")))
    if entry.get("kind") == "day_type" and dtid is not None:
        return CalendarRuleKind.DAY_TYPE, dtid
    return CalendarRuleKind.CLOSED, None


def _parse_time(value: str) -> dt.time:
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return dt.datetime.strptime(value, fmt).time()
        except (ValueError, TypeError):
            continue
    raise ValueError(f"Invalid time {value!r}")


def import_config(s: Session, data: object) -> ImportReport:
    """Validate and apply a backup document, replacing the schedule config.

    Raises :class:`ValueError` with a human-readable message on invalid input.
    """
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("Dit is geen geldig ViejoolBel-back-upbestand.")

    day_types = data.get("day_types", [])
    if not isinstance(day_types, list):
        raise ValueError("Ongeldig back-upbestand (day_types).")

    report = ImportReport()
    sound_ids = {snd.name: snd.id for snd in s.scalars(select(Sound))}

    # Replace schedule config (keep sounds/audio and the password). Order respects
    # references: rules & weekday defaults, then events, then day-types.
    s.execute(delete(CalendarRule))
    s.execute(delete(WeekdayDefault))
    s.execute(delete(BellEvent))
    s.execute(delete(DayType))
    s.flush()

    name_to_id: dict[str, int] = {}
    any_default = False
    for d in day_types:
        name = str(d.get("name", "")).strip()
        if not name:
            continue
        is_default = bool(d.get("is_default", False))
        any_default = any_default or is_default
        dt_row = DayType(name=name, is_default=is_default)
        s.add(dt_row)
        s.flush()
        name_to_id[name] = dt_row.id
        report.day_types += 1
        for e in d.get("events", []):
            try:
                at = _parse_time(str(e.get("at", "")))
            except ValueError as exc:
                raise ValueError(f"Ongeldige tijd in back-up: {e.get('at')!r}") from exc
            sound_name = e.get("sound")
            sound_id = sound_ids.get(sound_name) if sound_name else None
            if sound_name and sound_id is None:
                report.events_missing_sound += 1
                report.missing_sounds.append(str(sound_name))
            s.add(
                BellEvent(
                    day_type_id=dt_row.id,
                    at=at,
                    sound_id=sound_id,
                    use_audio=bool(e.get("use_audio", True)),
                    use_relay=bool(e.get("use_relay", True)),
                    duration=int(e.get("duration", 8)),
                    label=str(e.get("label", "")),
                )
            )
            report.events += 1

    # Ensure exactly one default day-type when any exist.
    if name_to_id and not any_default:
        first = s.scalars(select(DayType).order_by(DayType.id)).first()
        if first is not None:
            first.is_default = True

    for wd in data.get("weekday_defaults", []):
        try:
            weekday = int(wd.get("weekday"))
        except (TypeError, ValueError):
            continue
        if not 0 <= weekday <= 6:
            continue
        kind, dtid = _resolve_ref(wd, name_to_id)
        s.add(WeekdayDefault(weekday=weekday, kind=kind, day_type_id=dtid))
        report.weekday_defaults += 1

    for r in data.get("calendar_rules", []):
        try:
            start = dt.date.fromisoformat(str(r.get("start_date")))
            end = dt.date.fromisoformat(str(r.get("end_date")))
        except (TypeError, ValueError):
            continue
        if end < start:
            continue
        kind, dtid = _resolve_ref(r, name_to_id)
        s.add(
            CalendarRule(
                start_date=start, end_date=end, kind=kind, day_type_id=dtid,
                note=str(r.get("note", "")),
            )
        )
        report.calendar_rules += 1

    settings = data.get("settings", {})
    if isinstance(settings, dict):
        for key in _BACKUP_SETTING_KEYS:
            if key in settings and settings[key] is not None:
                set_setting(s, key, str(settings[key]))

    return report

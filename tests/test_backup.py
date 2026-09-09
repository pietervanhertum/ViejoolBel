"""Backup export/import (FR-18)."""

from __future__ import annotations

import datetime as dt
import io
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from viejoolbel.backup import export_config, import_config
from viejoolbel.db import get_setting, session_scope, set_setting
from viejoolbel.models import BellEvent, CalendarRule, CalendarRuleKind, DayType, Sound


def test_export_has_expected_shape(initialized_db):
    with session_scope() as s:
        data = export_config(s, timezone="Europe/Brussels")
    assert data["format"] == "viejoolbel-backup"
    assert {"day_types", "weekday_defaults", "calendar_rules", "settings", "sounds"} <= set(data)
    assert data["settings"]["timezone"] == "Europe/Brussels"


def test_roundtrip_restores_config(initialized_db):
    with session_scope() as s:
        snd = Sound(name="Startbel", filename="s.wav")
        s.add(snd)
        s.flush()
        dt_ = s.scalars(select(DayType)).first()
        s.add(BellEvent(day_type_id=dt_.id, at=dt.time(8, 30), sound_id=snd.id, label="Start"))
        s.add(
            CalendarRule(
                start_date=dt.date(2025, 10, 27),
                end_date=dt.date(2025, 10, 31),
                kind=CalendarRuleKind.CLOSED,
                note="Herfst",
            )
        )
        set_setting(s, "volume_db", "3")

    with session_scope() as s:
        data = export_config(s, timezone="Europe/Brussels")

    with session_scope() as s:
        report = import_config(s, data)
    assert report.events == 1 and report.calendar_rules == 1 and report.day_types >= 1

    with session_scope() as s:
        events = list(s.scalars(select(BellEvent)))
        assert len(events) == 1 and events[0].label == "Start"
        assert events[0].sound_id is not None  # resolved by name
        assert get_setting(s, "volume_db", "") == "3"
        rule = s.scalars(select(CalendarRule)).one()
        assert rule.note == "Herfst"


def test_import_missing_sound_becomes_relay_only(initialized_db):
    data = {
        "format": "viejoolbel-backup",
        "day_types": [
            {
                "name": "X",
                "is_default": True,
                "events": [{"at": "09:00", "sound": "Onbekend", "duration": 8, "label": "l"}],
            }
        ],
    }
    with session_scope() as s:
        report = import_config(s, data)
    assert report.events_missing_sound == 1 and "Onbekend" in report.missing_sounds
    with session_scope() as s:
        assert s.scalars(select(BellEvent)).one().sound_id is None


def test_import_rejects_non_backup(initialized_db):
    with session_scope() as s, pytest.raises(ValueError):
        import_config(s, {"foo": "bar"})


def test_import_rejects_bad_time(initialized_db):
    data = {
        "format": "viejoolbel-backup",
        "day_types": [{"name": "X", "events": [{"at": "25:99"}]}],
    }
    with session_scope() as s, pytest.raises(ValueError):
        import_config(s, data)


def test_restore_via_api(auth_client: TestClient):
    data = auth_client.get("/api/backup").json()
    blob = io.BytesIO(json.dumps(data).encode())
    resp = auth_client.post(
        "/api/restore", files={"file": ("b.json", blob, "application/json")}
    )
    assert resp.status_code == 200 and resp.json()["ok"] is True


def test_restore_rejects_garbage(auth_client: TestClient):
    resp = auth_client.post(
        "/api/restore", files={"file": ("b.json", io.BytesIO(b"not json"), "application/json")}
    )
    assert resp.status_code == 400


def test_backup_download_has_attachment_header(auth_client: TestClient):
    resp = auth_client.get("/api/backup")
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")

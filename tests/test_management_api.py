"""Tests for the schedule/calendar management API endpoints."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient


def _default_dt(client: TestClient) -> int:
    return client.get("/api/day-types").json()[0]["id"]


def _upload_sound(client: TestClient, name: str, blob: bytes = b"RIFFfake"):
    return client.post(
        "/api/sounds",
        data={"name": name},
        files={"file": ("s.wav", io.BytesIO(blob), "audio/wav")},
    )


def test_create_rename_and_delete_day_type(auth_client: TestClient):
    new_id = auth_client.post("/api/day-types", data={"name": "Woensdag"}).json()["id"]
    r = auth_client.post(f"/api/day-types/{new_id}/rename", data={"name": "Woe"})
    assert r.status_code == 200
    names = [d["name"] for d in auth_client.get("/api/day-types").json()]
    assert "Woe" in names
    assert auth_client.delete(f"/api/day-types/{new_id}").status_code == 200


def test_cannot_delete_default_day_type(auth_client: TestClient):
    default_id = _default_dt(auth_client)
    assert auth_client.delete(f"/api/day-types/{default_id}").status_code == 409


def test_set_default_moves_flag(auth_client: TestClient):
    new_id = auth_client.post("/api/day-types", data={"name": "Feestdag"}).json()["id"]
    assert auth_client.post(f"/api/day-types/{new_id}/default").status_code == 200
    dts = {d["id"]: d["is_default"] for d in auth_client.get("/api/day-types").json()}
    assert dts[new_id] is True
    assert sum(1 for v in dts.values() if v) == 1


def test_rename_conflict(auth_client: TestClient):
    auth_client.post("/api/day-types", data={"name": "A"})
    b_id = auth_client.post("/api/day-types", data={"name": "B"}).json()["id"]
    assert auth_client.post(f"/api/day-types/{b_id}/rename", data={"name": "A"}).status_code == 409


def test_edit_event(auth_client: TestClient):
    dtid = _default_dt(auth_client)
    eid = auth_client.post(
        f"/api/day-types/{dtid}/events", data={"at": "08:30", "label": "Start"}
    ).json()["id"]
    resp = auth_client.post(
        f"/api/events/{eid}",
        data={"at": "08:45", "label": "Later", "duration": 10, "use_audio": False},
    )
    assert resp.status_code == 200
    events = auth_client.get("/api/day-types").json()[0]["events"]
    e = next(e for e in events if e["id"] == eid)
    assert e["at"] == "08:45" and e["duration"] == 10 and e["use_audio"] is False


def test_weekday_defaults_roundtrip(auth_client: TestClient):
    dtid = _default_dt(auth_client)
    # Close Wednesday (index 2).
    assert auth_client.post(
        "/api/weekday-defaults", data={"weekday": 2, "kind": "closed"}
    ).status_code == 200
    rows = {r["weekday"]: r for r in auth_client.get("/api/weekday-defaults").json()}
    assert rows[2]["kind"] == "closed"
    # Assign a day-type to Saturday (index 5).
    assert auth_client.post(
        "/api/weekday-defaults", data={"weekday": 5, "kind": "day_type", "day_type_id": dtid}
    ).status_code == 200
    rows = {r["weekday"]: r for r in auth_client.get("/api/weekday-defaults").json()}
    assert rows[5]["kind"] == "day_type" and rows[5]["day_type_id"] == dtid


def test_weekday_default_requires_day_type(auth_client: TestClient):
    assert auth_client.post(
        "/api/weekday-defaults", data={"weekday": 1, "kind": "day_type"}
    ).status_code == 400


def test_calendar_list_and_delete(auth_client: TestClient):
    rid = auth_client.post(
        "/api/calendar",
        data={"start_date": "2025-10-27", "end_date": "2025-10-31", "kind": "closed",
              "note": "Herfst"},
    ).json()["id"]
    rules = auth_client.get("/api/calendar").json()
    assert any(r["id"] == rid and r["note"] == "Herfst" for r in rules)
    assert auth_client.delete(f"/api/calendar/{rid}").status_code == 200
    assert all(r["id"] != rid for r in auth_client.get("/api/calendar").json())


def test_calendar_month_view(auth_client: TestClient):
    body = auth_client.get("/api/calendar/month", params={"year": 2025, "month": 9}).json()
    assert body["year"] == 2025 and body["month"] == 9
    assert len(body["days"]) == 30
    assert {"date", "closed", "day_type_name", "ring_count"} <= set(body["days"][0])


def test_settings_roundtrip(auth_client: TestClient):
    assert auth_client.post("/api/settings", data={"volume_db": 3}).status_code == 200
    assert auth_client.get("/api/settings").json()["volume_db"] == 3


def test_settings_volume_range(auth_client: TestClient):
    assert auth_client.post("/api/settings", data={"volume_db": 999}).status_code == 400


def test_delete_sound_blocked_when_in_use(auth_client: TestClient):
    files = {"file": ("bel.wav", io.BytesIO(b"RIFFfake"), "audio/wav")}
    sid = auth_client.post("/api/sounds", data={"name": "Gebruikt"}, files=files).json()["id"]
    dtid = _default_dt(auth_client)
    auth_client.post(f"/api/day-types/{dtid}/events", data={"at": "09:00", "sound_id": sid})
    assert auth_client.delete(f"/api/sounds/{sid}").status_code == 409


def test_sound_audio_download(auth_client: TestClient):
    files = {"file": ("bel.wav", io.BytesIO(b"RIFFfake"), "audio/wav")}
    sid = auth_client.post("/api/sounds", data={"name": "Preview"}, files=files).json()["id"]
    resp = auth_client.get(f"/api/sounds/{sid}/audio")
    assert resp.status_code == 200 and resp.content == b"RIFFfake"


def test_uploaded_sounds_get_distinct_filenames(auth_client: TestClient, service):
    # Two different names must never share a file on disk (old hash%N could collide
    # and overwrite one sound's audio with another's).
    for name, blob in [("Bel A", b"AAAA"), ("Bel B", b"BBBB")]:
        _upload_sound(auth_client, name, blob)
    from sqlalchemy import select

    from viejoolbel.db import session_scope
    from viejoolbel.models import Sound

    with session_scope() as s:
        rows = {snd.name: snd.filename for snd in s.scalars(select(Sound))}
    assert rows["Bel A"] != rows["Bel B"]
    # And the bytes on disk are the ones uploaded (not overwritten).
    assert (service.settings.sounds_dir / rows["Bel A"]).read_bytes() == b"AAAA"
    assert (service.settings.sounds_dir / rows["Bel B"]).read_bytes() == b"BBBB"


def test_duplicate_name_rejected_without_touching_existing_file(auth_client: TestClient, service):
    _upload_sound(auth_client, "Uniek", b"ORIG")
    from sqlalchemy import select

    from viejoolbel.db import session_scope
    from viejoolbel.models import Sound

    with session_scope() as s:
        fname = s.scalar(select(Sound).where(Sound.name == "Uniek")).filename
    # A second upload with the same name is rejected...
    resp = _upload_sound(auth_client, "Uniek", b"NEW")
    assert resp.status_code == 409
    # ...and the original file is untouched (no overwrite, no orphan swap).
    assert (service.settings.sounds_dir / fname).read_bytes() == b"ORIG"

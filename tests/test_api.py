"""Integration tests exercising the full API over the mock hardware driver."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient


def test_status_requires_login(client: TestClient):
    assert client.get("/api/status").status_code == 401


def test_login_and_status(auth_client: TestClient):
    resp = auth_client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "time" in body and body["timezone"] == "Europe/Brussels"


def test_bad_login_rejected(client: TestClient):
    resp = client.post(
        "/login", data={"username": "admin", "password": "wrong"}, follow_redirects=False
    )
    assert resp.status_code == 401


def test_ring_now(auth_client: TestClient, service):
    resp = auth_client.post("/api/ring-now", data={"duration": 2, "use_audio": False})
    assert resp.status_code == 200 and resp.json()["ok"] is True
    assert len(service.hardware.rings) == 1


def test_ring_now_conflict_when_ringing(auth_client: TestClient, service):
    service.controller._lock.acquire()
    try:
        resp = auth_client.post("/api/ring-now", data={"duration": 1, "use_audio": False})
        assert resp.status_code == 409
    finally:
        service.controller._lock.release()


def test_self_test(auth_client: TestClient, service):
    assert auth_client.post("/api/self-test").status_code == 200
    assert service.hardware.self_tests == 1


def test_silence_today_toggles(auth_client: TestClient):
    assert auth_client.post("/api/silence-today", data={"on": True}).json()["silenced"] is True
    status = auth_client.get("/api/status").json()
    assert status["ring_count_today"] == 0


def test_sound_upload_and_delete(auth_client: TestClient):
    files = {"file": ("bel.wav", io.BytesIO(b"RIFFfake"), "audio/wav")}
    resp = auth_client.post("/api/sounds", data={"name": "Startbel"}, files=files)
    assert resp.status_code == 201
    sid = resp.json()["id"]
    assert any(s["name"] == "Startbel" for s in auth_client.get("/api/sounds").json())
    assert auth_client.delete(f"/api/sounds/{sid}").status_code == 200


def test_sound_upload_rejects_bad_type(auth_client: TestClient):
    files = {"file": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")}
    resp = auth_client.post("/api/sounds", data={"name": "x"}, files=files)
    assert resp.status_code == 400


def test_day_type_event_crud_and_plan(auth_client: TestClient):
    # Add an event to the default day-type and confirm it appears in day-types.
    dts = auth_client.get("/api/day-types").json()
    dtid = dts[0]["id"]
    resp = auth_client.post(
        f"/api/day-types/{dtid}/events",
        data={"at": "09:45", "duration": 6, "label": "Pauze"},
    )
    assert resp.status_code == 201
    eid = resp.json()["id"]
    dts = auth_client.get("/api/day-types").json()
    assert any(e["at"] == "09:45" for e in dts[0]["events"])
    assert auth_client.delete(f"/api/events/{eid}").status_code == 200


def test_add_event_rejects_bad_time(auth_client: TestClient):
    dtid = auth_client.get("/api/day-types").json()[0]["id"]
    resp = auth_client.post(f"/api/day-types/{dtid}/events", data={"at": "25:99"})
    assert resp.status_code == 400


def test_calendar_rule_closed_suppresses_today(auth_client: TestClient, service):
    today = service.scheduler.now().date().isoformat()
    # ensure something would otherwise ring today by adding an event
    dtid = auth_client.get("/api/day-types").json()[0]["id"]
    auth_client.post(f"/api/day-types/{dtid}/events", data={"at": "23:59", "label": "laat"})
    resp = auth_client.post(
        "/api/calendar",
        data={"start_date": today, "end_date": today, "kind": "closed", "note": "test"},
    )
    assert resp.status_code == 201
    assert auth_client.get("/api/status").json()["closed"] is True


def test_calendar_rule_rejects_reversed_range(auth_client: TestClient):
    resp = auth_client.post(
        "/api/calendar",
        data={"start_date": "2025-09-10", "end_date": "2025-09-01", "kind": "closed"},
    )
    assert resp.status_code == 400


def test_change_password_then_login(client: TestClient):
    client.post("/login", data={"username": "admin", "password": "changeme"})
    assert client.post("/api/password", data={"new_password": "s3cret!"}).status_code == 200
    client.post("/logout")
    ok = client.post(
        "/login", data={"username": "admin", "password": "s3cret!"}, follow_redirects=False
    )
    assert ok.status_code == 303


def test_change_password_rejects_short(auth_client: TestClient):
    assert auth_client.post("/api/password", data={"new_password": "abc"}).status_code == 400


def test_backup_returns_config(auth_client: TestClient):
    body = auth_client.get("/api/backup").json()
    assert "day_types" in body and body["day_types"]

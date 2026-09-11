"""Tests for the durable operational event log (post-mortem trail)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from viejoolbel.db import _EVENT_LOG_MAX_ROWS, record_event, session_scope
from viejoolbel.models import EV_HEALTH_FAULT, EventLog


def test_record_event_persists(initialized_db):
    with session_scope() as s:
        record_event(s, EV_HEALTH_FAULT, "scheduler: down", level="error")
    with session_scope() as s:
        rows = list(s.scalars(select(EventLog)))
    assert len(rows) == 1
    assert rows[0].kind == EV_HEALTH_FAULT
    assert rows[0].level == "error"
    assert rows[0].detail == "scheduler: down"


def test_record_event_trims_to_cap(initialized_db):
    with session_scope() as s:
        for i in range(_EVENT_LOG_MAX_ROWS + 25):
            record_event(s, "tick", f"n={i}")
    with session_scope() as s:
        total = s.scalar(select(func.count()).select_from(EventLog))
        # Newest survives, oldest trimmed.
        newest = s.scalar(select(EventLog).order_by(EventLog.id.desc()))
    assert total == _EVENT_LOG_MAX_ROWS
    assert newest.detail == f"n={_EVENT_LOG_MAX_ROWS + 24}"


def test_events_endpoint_newest_first(auth_client: TestClient):
    with session_scope() as s:
        record_event(s, "health_fault", "eerste", level="error")
        record_event(s, "health_recovered", "tweede", level="ok")
    body = auth_client.get("/api/events?limit=10").json()
    assert [e["detail"] for e in body["events"]] == ["tweede", "eerste"]
    assert body["events"][0]["kind"] == "health_recovered"


def test_events_endpoint_requires_login(client: TestClient):
    assert client.get("/api/events").status_code == 401

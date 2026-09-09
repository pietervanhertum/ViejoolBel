"""User-facing dates render in Dutch with 24-hour time (no English, no AM/PM)."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from viejoolbel.web.app import nl_date, nl_datetime


def test_nl_date_is_dutch():
    # 2026-09-09 is a Wednesday.
    assert nl_date(dt.date(2026, 9, 9)) == "woensdag 9 september 2026"


def test_nl_datetime_is_dutch_and_24h():
    # 17:30 must stay 24-hour, never "5:30 PM".
    assert nl_datetime(dt.datetime(2026, 9, 9, 17, 30)) == "woensdag 9 september 2026 — 17:30"
    # A morning time is zero-padded and unambiguous.
    assert nl_datetime(dt.datetime(2026, 1, 5, 8, 5)) == "maandag 5 januari 2026 — 08:05"


def test_dashboard_clock_is_dutch(auth_client: TestClient):
    resp = auth_client.get("/")
    assert resp.status_code == 200
    # The big clock shows a Dutch weekday name, never an English one.
    assert any(day in resp.text for day in
               ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"))
    for english in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"):
        assert english not in resp.text


def test_schedule_time_input_is_not_the_locale_picker(auth_client: TestClient):
    # The bell-time fields must not be a native <input type="time"> (whose picker
    # shows AM/PM in English-locale browsers); they are forced-24h text fields.
    dtid = auth_client.get("/api/day-types").json()[0]["id"]
    resp = auth_client.get(f"/roosters/{dtid}")
    assert resp.status_code == 200
    assert 'type="time"' not in resp.text
    assert 'class="time24"' in resp.text

"""Tests for onboarding access-point control (FR-19)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from viejoolbel import ap
from viejoolbel.config import Settings
from viejoolbel.db import session_scope, set_setting
from viejoolbel.monitor import HealthMonitor

_SCRIPT = Path("/opt/viejoolbel/current/deploy/ap_control.sh")


def _route_run(stdout: str):
    def run(*a, **k):
        return subprocess.CompletedProcess(a, 0, stdout=stdout, stderr="")
    return run


def test_network_online_reads_default_route(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ap.subprocess, "run", _route_run("default via 192.168.1.1\n"))
    assert ap.network_online() is True
    monkeypatch.setattr(ap.subprocess, "run", _route_run("192.168.4.0/24 dev wlan0\n"))
    assert ap.network_online() is False


def _monitor(settings: Settings) -> HealthMonitor:
    return HealthMonitor(settings, scheduler_is_alive=lambda: True)


def test_fallback_opens_ap_after_grace(
    initialized_db, settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    m = _monitor(settings)
    monkeypatch.setattr(ap, "network_online", lambda: False)
    monkeypatch.setattr(ap, "ap_is_active", lambda: False)
    raised = {"n": 0, "recovery": None}

    def fake_raise(_s, recovery_minutes=0):
        raised["n"] += 1
        raised["recovery"] = recovery_minutes
        return True, "ok"

    monkeypatch.setattr(ap, "raise_ap", fake_raise)

    m._check_network_fallback()          # arms the timer, does not act
    assert raised["n"] == 0
    m._offline_since = time.monotonic() - (settings.ap_fallback_minutes * 60 + 1)
    m._check_network_fallback()          # grace elapsed -> opens AP
    assert raised["n"] == 1
    # The self-heal reboot window is passed through to raise_ap.
    assert raised["recovery"] == settings.ap_fallback_recovery_minutes
    monkeypatch.setattr(ap, "ap_is_active", lambda: True)
    m._check_network_fallback()          # AP now up -> stands down (no loop)
    assert raised["n"] == 1


def test_fallback_resets_when_back_online(
    initialized_db, settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    def _no_raise(_s, *a, **k):
        raise AssertionError("should not open the AP")

    m = _monitor(settings)
    m._offline_since = time.monotonic() - 9999
    monkeypatch.setattr(ap, "network_online", lambda: True)
    monkeypatch.setattr(ap, "raise_ap", _no_raise)
    m._check_network_fallback()
    assert m._offline_since is None


def test_fallback_disabled_when_zero(
    initialized_db, settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    def _no_raise(_s, *a, **k):
        raise AssertionError("fallback disabled — must not open the AP")

    with session_scope() as s:
        set_setting(s, "ap_fallback_minutes", "0")
    m = _monitor(settings)
    m._offline_since = time.monotonic() - 9999
    monkeypatch.setattr(ap, "network_online", lambda: False)
    monkeypatch.setattr(ap, "ap_is_active", lambda: False)
    monkeypatch.setattr(ap, "raise_ap", _no_raise)
    m._check_network_fallback()  # must not raise the AP
    assert m._offline_since is None


def test_raise_ap_passes_recovery_minutes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ap, "available", lambda _s: True)
    seen = {}

    def run(cmd, *a, **k):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ap-raised reboot-in=10min", stderr="")

    monkeypatch.setattr(ap.subprocess, "run", run)
    ok, _msg = ap.raise_ap(_SCRIPT, 10)
    assert ok is True
    assert seen["cmd"] == ["sudo", str(_SCRIPT), "raise", "10"]

    # 0 (legacy) omits the minutes argument entirely.
    ap.raise_ap(_SCRIPT, 0)
    assert seen["cmd"] == ["sudo", str(_SCRIPT), "raise"]


def test_fallback_records_event_before_raising(
    initialized_db, settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    """The safety-net persists a durable event AND fires its alert before the AP
    takes over the radio (afterwards the device is offline)."""
    from viejoolbel.db import session_scope as _scope
    from viejoolbel.models import EV_AP_FALLBACK, EventLog
    from viejoolbel.notify import Notifier

    order: list[str] = []

    class T:
        def post(self, *a, **k):
            order.append("alert")
            return 200

        def get(self, *a, **k):
            return 200

    m = HealthMonitor(settings, scheduler_is_alive=lambda: True, notifier=Notifier(transport=T()))
    with session_scope() as s:
        set_setting(s, "notify_webhook_url", "https://ntfy.sh/test")
    monkeypatch.setattr(ap, "network_online", lambda: False)
    monkeypatch.setattr(ap, "ap_is_active", lambda: False)
    monkeypatch.setattr(ap, "raise_ap", lambda _s, r=0: order.append("raise") or (True, "ok"))

    m._offline_since = time.monotonic() - (settings.ap_fallback_minutes * 60 + 1)
    m._check_network_fallback()

    assert order == ["alert", "raise"]  # alert must go out while still online
    with _scope() as s:
        events = list(s.scalars(select(EventLog).where(EventLog.kind == EV_AP_FALLBACK)))
    assert len(events) == 1 and events[0].level == "warn"


def test_ap_fallback_endpoint_sets_recovery(auth_client: TestClient):
    resp = auth_client.post(
        "/api/ap/fallback", data={"minutes": "20", "recovery_minutes": "8"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fallback_minutes"] == 20 and body["recovery_minutes"] == 8
    # Reflected back in status.
    status = auth_client.get("/api/ap/status").json()
    assert status["fallback_minutes"] == 20 and status["recovery_minutes"] == 8


def test_ap_fallback_rejects_bad_recovery(auth_client: TestClient):
    resp = auth_client.post(
        "/api/ap/fallback", data={"minutes": "20", "recovery_minutes": "999"}
    )
    assert resp.status_code == 400


def test_status_unsupported(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ap, "available", lambda _s: False)
    d = ap.status(_SCRIPT)
    assert d["supported"] is False and d["ssid"] == ap.AP_SSID


def test_status_parses_helper_output(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ap, "available", lambda _s: True)
    out = "installed=yes\nenabled=enabled\nactive=active\nhostapd=running\n"
    monkeypatch.setattr(
        ap.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr=""),
    )
    d = ap.status(_SCRIPT)
    assert d["supported"] and d["installed"] and d["enabled"]
    assert d["active"] and d["hostapd_running"]


def test_set_enabled_ok(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ap, "available", lambda _s: True)
    monkeypatch.setattr(
        ap.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="enabled", stderr=""),
    )
    ok, _msg = ap.set_enabled(_SCRIPT, True)
    assert ok is True


def test_set_enabled_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ap, "available", lambda _s: True)
    monkeypatch.setattr(
        ap.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="", stderr="nope"),
    )
    ok, msg = ap.set_enabled(_SCRIPT, False)
    assert ok is False and "nope" in msg


def test_start_test_clamps_minutes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ap, "available", lambda _s: True)
    seen = {}

    def run(cmd, *a, **k):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="ap-test-started", stderr="")

    monkeypatch.setattr(ap.subprocess, "run", run)
    ok, _msg = ap.start_test(_SCRIPT, 999)
    assert ok is True
    assert seen["cmd"] == ["sudo", str(_SCRIPT), "start-test", "30"]


def test_ap_status_endpoint(auth_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ap, "status", lambda _s: {"supported": True, "enabled": True})
    body = auth_client.get("/api/ap/status").json()
    assert body["supported"] is True and body["enabled"] is True


def test_ap_enabled_endpoint(auth_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ap, "set_enabled", lambda _s, on: (True, "ok"))
    resp = auth_client.post("/api/ap/enabled", data={"enabled": "true"})
    assert resp.status_code == 200 and resp.json()["ok"] is True


def test_ap_test_endpoint(auth_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ap, "start_test", lambda _s, m: (True, "gestart"))
    resp = auth_client.post("/api/ap/test", data={"minutes": "5"})
    assert resp.status_code == 200 and resp.json()["ok"] is True


def test_ap_endpoints_require_login(client: TestClient):
    assert client.get("/api/ap/status").status_code == 401
    assert client.post("/api/ap/enabled", data={"enabled": "true"}).status_code == 401
    assert client.post("/api/ap/test", data={"minutes": "5"}).status_code == 401

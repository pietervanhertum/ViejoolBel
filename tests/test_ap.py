"""Tests for onboarding access-point control (FR-19)."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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
    raised = {"n": 0}

    def fake_raise(_s):
        raised["n"] += 1
        return True, "ok"

    monkeypatch.setattr(ap, "raise_ap", fake_raise)

    m._check_network_fallback()          # arms the timer, does not act
    assert raised["n"] == 0
    m._offline_since = time.monotonic() - (settings.ap_fallback_minutes * 60 + 1)
    m._check_network_fallback()          # grace elapsed -> opens AP
    assert raised["n"] == 1
    monkeypatch.setattr(ap, "ap_is_active", lambda: True)
    m._check_network_fallback()          # AP now up -> stands down (no loop)
    assert raised["n"] == 1


def test_fallback_resets_when_back_online(
    initialized_db, settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    def _no_raise(_s):
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
    def _no_raise(_s):
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

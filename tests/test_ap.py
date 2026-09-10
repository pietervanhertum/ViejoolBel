"""Tests for onboarding access-point control (FR-19)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from viejoolbel import ap

_SCRIPT = Path("/opt/viejoolbel/current/deploy/ap_control.sh")


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

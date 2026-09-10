"""Tests for WiFi scan/status/connect (FR-19)."""

from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from viejoolbel import wifi

_SCAN_OUTPUT = "\n".join(
    [
        "yes:72:WPA2:SchoolWiFi",
        "no:55:WPA2:Buren\\:Gastnet",  # SSID containing an escaped colon
        "no:40::OpenNet",  # open network (empty SECURITY)
        "no:90:WPA2:SchoolWiFi",  # weaker/stronger duplicate of the active one
        "no:30:WPA2:",  # hidden network (no SSID) — skipped
    ]
)


def _fake_run(output: str, returncode: int = 0):
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode, stdout=output, stderr="")

    return run


def test_split_terse_handles_escaped_colons():
    assert wifi._split_terse(r"yes:55:WPA2:Buren\:Gastnet") == [
        "yes",
        "55",
        "WPA2",
        "Buren:Gastnet",
    ]


def test_scan_parses_dedupes_and_orders(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wifi, "available", lambda: True)
    monkeypatch.setattr(wifi.subprocess, "run", _fake_run(_SCAN_OUTPUT))
    nets = wifi.scan()
    ssids = [n.ssid for n in nets]
    assert ssids == ["SchoolWiFi", "Buren:Gastnet", "OpenNet"]  # active first, then by signal
    active = next(n for n in nets if n.ssid == "SchoolWiFi")
    assert active.active is True and active.secure is True
    assert next(n for n in nets if n.ssid == "OpenNet").secure is False


def test_scan_empty_when_unsupported(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wifi, "available", lambda: False)
    assert wifi.scan() == []


def test_scan_falls_back_to_cache_when_rescan_refused(monkeypatch: pytest.MonkeyPatch):
    # NetworkManager rate-limits rescans; when "--rescan yes" is refused, scan()
    # must fall back to the cached list instead of returning nothing.
    monkeypatch.setattr(wifi, "available", lambda: True)
    calls: list[bool] = []

    def run(cmd, *args, **kwargs):
        rescan = "--rescan" in cmd
        calls.append(rescan)
        code = 1 if rescan else 0  # reject the rescan, allow the cached read
        return subprocess.CompletedProcess(cmd, code, stdout=_SCAN_OUTPUT, stderr="busy")

    monkeypatch.setattr(wifi.subprocess, "run", run)
    nets = wifi.scan()
    assert calls == [True, False]  # tried rescan first, then cached
    assert [n.ssid for n in nets] == ["SchoolWiFi", "Buren:Gastnet", "OpenNet"]


def test_current_ssid_returns_active(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wifi, "available", lambda: True)
    monkeypatch.setattr(wifi.subprocess, "run", _fake_run(_SCAN_OUTPUT))
    assert wifi.current_ssid() == "SchoolWiFi"


_SAVED_OUTPUT = "\n".join(
    [
        "SchoolWiFi:uuid-1:802-11-wireless:wlan0",  # active
        "Buren:uuid-2:802-11-wireless:",
        "Bekabeld:uuid-3:802-3-ethernet:eth0",  # not WiFi — skipped
        "viejoolbel-Gastnet:uuid-4:802-11-wireless:",  # ssid via prefix fallback
    ]
)


def _saved_run(cmd, *args, **kwargs):
    # `-g 802-11-wireless.ssid connection show <id>` → resolve SSID per profile
    if "-g" in cmd:
        ident = cmd[-1]
        ssid = {"uuid-1": "SchoolWiFi", "uuid-2": "Buren"}.get(ident, "")
        code = 0 if ssid else 1
        return subprocess.CompletedProcess(cmd, code, stdout=ssid, stderr="")
    return subprocess.CompletedProcess(cmd, 0, stdout=_SAVED_OUTPUT, stderr="")


def test_saved_networks_filters_and_resolves_ssid(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wifi, "available", lambda: True)
    monkeypatch.setattr(wifi.subprocess, "run", _saved_run)
    nets = wifi.saved_networks()
    # ethernet dropped; active first, then alphabetical; prefix fallback for uuid-4
    assert [n.ssid for n in nets] == ["SchoolWiFi", "Buren", "Gastnet"]
    assert next(n for n in nets if n.ssid == "SchoolWiFi").active is True
    # the raw connection name is kept as the handle used to forget it
    assert next(n for n in nets if n.ssid == "Gastnet").name == "viejoolbel-Gastnet"


def test_saved_networks_empty_when_unsupported(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wifi, "available", lambda: False)
    assert wifi.saved_networks() == []


def test_forget_requires_name(tmp_path):
    ok, msg = wifi.forget("  ", tmp_path / "forget_wifi.sh")
    assert ok is False


def test_forget_fails_gracefully_without_script(tmp_path):
    ok, msg = wifi.forget("SchoolWiFi", tmp_path / "missing.sh")
    assert ok is False and "script" in msg.lower()


def test_saved_endpoint(auth_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wifi, "available", lambda: True)
    monkeypatch.setattr(wifi.subprocess, "run", _saved_run)
    body = auth_client.get("/api/wifi/saved").json()
    assert body["supported"] is True
    assert body["networks"][0]["ssid"] == "SchoolWiFi"


def test_forget_endpoint_rejects_empty_name(auth_client: TestClient):
    assert auth_client.post("/api/wifi/forget", data={"name": " "}).status_code == 400


def test_forget_endpoint_reports_failure(auth_client: TestClient):
    resp = auth_client.post("/api/wifi/forget", data={"name": "SchoolWiFi"})
    assert resp.status_code == 502 and resp.json()["ok"] is False


def test_connect_requires_ssid(tmp_path):
    ok, msg = wifi.connect("  ", "pw", tmp_path / "set_wifi.sh")
    assert ok is False and "SSID" in msg


def test_connect_fails_gracefully_without_script(tmp_path):
    # No privileged helper on a dev/test machine → clear failure, no launch.
    ok, msg = wifi.connect("SchoolWiFi", "pw", tmp_path / "missing.sh")
    assert ok is False and "script" in msg.lower()


def test_scan_endpoint(auth_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wifi, "available", lambda: True)
    monkeypatch.setattr(wifi.subprocess, "run", _fake_run(_SCAN_OUTPUT))
    body = auth_client.get("/api/wifi/scan").json()
    assert body["supported"] is True
    assert body["networks"][0]["ssid"] == "SchoolWiFi"


def test_status_endpoint(auth_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(wifi, "available", lambda: False)
    body = auth_client.get("/api/wifi/status").json()
    assert body["supported"] is False and body["current_ssid"] is None


def test_connect_endpoint_rejects_empty_ssid(auth_client: TestClient):
    assert auth_client.post("/api/wifi/connect", data={"ssid": " "}).status_code == 400


def test_connect_endpoint_reports_failure(auth_client: TestClient):
    # Without the privileged script the endpoint reports a 502 + ok=False.
    resp = auth_client.post("/api/wifi/connect", data={"ssid": "SchoolWiFi", "password": "pw"})
    assert resp.status_code == 502
    assert resp.json()["ok"] is False


def test_wifi_endpoints_require_login(client: TestClient):
    assert client.get("/api/wifi/scan").status_code == 401
    assert client.post("/api/wifi/connect", data={"ssid": "x"}).status_code == 401
    assert client.get("/api/wifi/saved").status_code == 401
    assert client.post("/api/wifi/forget", data={"name": "x"}).status_code == 401

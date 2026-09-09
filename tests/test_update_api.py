"""Tests for the software-update endpoints (FR-22)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from viejoolbel import updater
from viejoolbel.updater import ReleaseInfo


def test_check_reports_newer(auth_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        updater, "check_latest", lambda repo, **k: ReleaseInfo("v9.9.9", "http://x", "notes")
    )
    body = auth_client.get("/api/update/check").json()
    assert body["available"] is True
    assert body["latest"] == "v9.9.9"


def test_check_reports_up_to_date(auth_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        updater, "check_latest", lambda repo, **k: ReleaseInfo("v0.0.1", "http://x", "")
    )
    body = auth_client.get("/api/update/check").json()
    assert body["available"] is False


def test_check_handles_unreachable(auth_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(updater, "check_latest", lambda repo, **k: None)
    body = auth_client.get("/api/update/check").json()
    assert body["available"] is False and body["error"]


def test_apply_rejects_invalid_tag(auth_client: TestClient):
    assert auth_client.post("/api/update/apply", data={"tag": "; rm -rf /"}).status_code == 400


def test_apply_fails_gracefully_without_script(auth_client: TestClient):
    # On a dev/test machine the privileged script is absent, so apply must report
    # a clear failure instead of launching anything.
    resp = auth_client.post("/api/update/apply", data={"tag": "v9.9.9"})
    assert resp.status_code == 409
    assert resp.json()["ok"] is False


def test_launch_update_validates_tag(tmp_path):
    ok, msg = updater.launch_update("nonsense tag", tmp_path / "apply.sh")
    assert ok is False and "Ongeldige" in msg


def test_read_log_returns_tail(tmp_path):
    log = tmp_path / "update.log"
    log.write_bytes(b"x" * 100 + b"TAIL")
    assert updater.read_log(log, max_bytes=8).endswith("TAIL")
    assert updater.read_log(tmp_path / "missing.log") == ""


def test_update_log_endpoint(auth_client: TestClient):
    body = auth_client.get("/api/update/log").json()
    assert "log" in body

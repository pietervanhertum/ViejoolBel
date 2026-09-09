"""Relay master-switch and default-sound behaviour."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

from viejoolbel.bell import BellController
from viejoolbel.db import get_setting, session_scope, set_setting
from viejoolbel.hardware.mock import MockHardware
from viejoolbel.models import RingSource


def test_disabled_relay_is_never_energised(controller: BellController, hardware: MockHardware):
    with session_scope() as s:
        set_setting(s, "relay_enabled", "0")
    controller.ring(
        source=RingSource.MANUAL, sound_id=None, duration=1, use_audio=False, use_relay=True
    )
    assert hardware.rings[-1].use_relay is False  # forced off despite use_relay=True


def test_enabled_relay_still_rings(controller: BellController, hardware: MockHardware):
    with session_scope() as s:
        set_setting(s, "relay_enabled", "1")
    controller.ring(
        source=RingSource.MANUAL, sound_id=None, duration=1, use_audio=False, use_relay=True
    )
    assert hardware.rings[-1].use_relay is True


def test_relay_setting_endpoint_and_ring(auth_client: TestClient, service):
    files = {"file": ("bel.wav", io.BytesIO(b"RIFFfake"), "audio/wav")}
    sid = auth_client.post("/api/sounds", data={"name": "S"}, files=files).json()["id"]
    assert auth_client.post("/api/settings/relay", data={"enabled": "false"}).status_code == 200
    auth_client.post(
        "/api/ring-now", data={"sound_id": sid, "use_audio": "true", "use_relay": "true"}
    )
    assert service.hardware.rings[-1].use_relay is False


def test_relay_hidden_in_ui_when_disabled(auth_client: TestClient):
    auth_client.post("/api/settings/relay", data={"enabled": "false"})
    body = auth_client.get("/").text
    assert 'name="use_relay"' not in body  # the relay checkbox is gone from Bel nu


def test_set_default_sound(auth_client: TestClient):
    files = {"file": ("bel.wav", io.BytesIO(b"RIFFfake"), "audio/wav")}
    sid = auth_client.post("/api/sounds", data={"name": "Startbel"}, files=files).json()["id"]
    assert auth_client.post(f"/api/sounds/{sid}/default").status_code == 200
    with session_scope() as s:
        assert get_setting(s, "default_sound_id", "") == str(sid)
    # Shown as default on the sounds page.
    assert "standaard" in auth_client.get("/geluiden").text


def test_set_default_sound_missing(auth_client: TestClient):
    assert auth_client.post("/api/sounds/9999/default").status_code == 404


def test_deleting_default_sound_clears_the_setting(auth_client: TestClient):
    files = {"file": ("bel.wav", io.BytesIO(b"RIFFfake"), "audio/wav")}
    sid = auth_client.post("/api/sounds", data={"name": "Tijdelijk"}, files=files).json()["id"]
    auth_client.post(f"/api/sounds/{sid}/default")
    assert auth_client.delete(f"/api/sounds/{sid}").status_code == 200
    with session_scope() as s:
        assert get_setting(s, "default_sound_id", "") == ""

"""Smoke tests for the management HTML pages (branding + rendering)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

PAGES = ["/", "/roosters", "/kalender", "/geluiden", "/instellingen"]


@pytest.mark.parametrize("path", PAGES)
def test_pages_redirect_when_logged_out(client: TestClient, path: str):
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


@pytest.mark.parametrize("path", PAGES)
def test_pages_render_when_logged_in(auth_client: TestClient, path: str):
    resp = auth_client.get(path)
    assert resp.status_code == 200
    # Consistent branding present on every page.
    assert "de Viejool" in resp.text


def test_rooster_detail_renders(auth_client: TestClient):
    dtid = auth_client.get("/api/day-types").json()[0]["id"]
    resp = auth_client.get(f"/roosters/{dtid}")
    assert resp.status_code == 200 and "Beltijden" in resp.text


def test_rooster_detail_404(auth_client: TestClient):
    assert auth_client.get("/roosters/9999").status_code == 404


def test_rooster_add_form_prefills_default_sound(auth_client: TestClient):
    sounds = auth_client.get("/api/sounds").json()
    assert sounds, "default sounds should be seeded"
    sid = sounds[0]["id"]
    assert auth_client.post(f"/api/sounds/{sid}/default").status_code == 200
    # A fresh day-type has no events, so the only sound <select> is the add form.
    new_id = auth_client.post("/api/day-types", data={"name": "PrefillDag"}).json()["id"]
    html = auth_client.get(f"/roosters/{new_id}").text
    assert f'value="{sid}" selected' in html


def test_rooster_relay_hidden_when_disabled(auth_client: TestClient):
    new_id = auth_client.post("/api/day-types", data={"name": "RelaisDag"}).json()["id"]
    auth_client.post("/api/settings/relay", data={"enabled": "true"})
    assert 'name="use_relay"' in auth_client.get(f"/roosters/{new_id}").text
    auth_client.post("/api/settings/relay", data={"enabled": "false"})
    assert 'name="use_relay"' not in auth_client.get(f"/roosters/{new_id}").text


def test_kalender_month_navigation(auth_client: TestClient):
    resp = auth_client.get("/kalender?year=2025&month=12")
    assert resp.status_code == 200 and "december 2025" in resp.text


def test_static_assets_are_cache_busted(auth_client: TestClient):
    # After an update the browser must fetch the new JS/CSS, so the URLs carry a
    # version query and the HTML itself is not cached (regression: a stale cached
    # app.js kept the old behaviour and made UI fixes look ineffective).
    from viejoolbel import __version__

    resp = auth_client.get("/")
    assert f"/static/app.js?v={__version__}" in resp.text
    assert f"/static/style.css?v={__version__}" in resp.text
    assert resp.headers.get("cache-control") == "no-cache"


def test_login_page_is_cache_busted(client: TestClient):
    from viejoolbel import __version__

    resp = client.get("/login")
    assert f"/static/app.js?v={__version__}" in resp.text

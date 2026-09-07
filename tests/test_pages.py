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


def test_kalender_month_navigation(auth_client: TestClient):
    resp = auth_client.get("/kalender?year=2025&month=12")
    assert resp.status_code == 200 and "december 2025" in resp.text

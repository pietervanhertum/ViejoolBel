"""End-to-end browser regression tests for UI-interaction bugs.

These require Playwright + a Chromium build; they are skipped automatically where
those are unavailable (e.g. the default CI image), so they never break the normal
suite. Run them locally with `pip install playwright` (Chromium already present in
the dev container) to guard against regressions of:

  * the AJAX forms navigating to the raw JSON API response (postForm), and
  * un-ticking a checkbox (audio/relais) being silently ignored.
"""

from __future__ import annotations

import glob
import socket
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from viejoolbel import db as db_module  # noqa: E402
from viejoolbel.config import Settings  # noqa: E402
from viejoolbel.service import Service  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _chromium_path() -> str | None:
    matches = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
    return matches[-1] if matches else None


@pytest.fixture
def live_server(tmp_path):
    port = _free_port()
    settings = Settings(
        data_dir=tmp_path / "data", hardware="mock", secret_key="x",
        host="127.0.0.1", port=port,
    )
    svc = Service(settings)
    svc.start()
    config = uvicorn.Config(svc.build_app(), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # we run off the main thread
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    else:  # pragma: no cover
        pytest.skip("server did not start")
    try:
        yield svc, f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        svc.stop()
        db_module._SESSION_FACTORY = None


def _launch(pw):
    exe = _chromium_path()
    try:
        return pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Chromium unavailable: {exc}")


def _login(page, base: str) -> None:
    page.goto(f"{base}/login")
    page.fill("input[name=username]", "admin")
    page.fill("input[name=password]", "changeme")
    page.click("button[type=submit]")
    page.wait_for_url(f"{base}/")


def test_ring_now_does_not_navigate_to_api(live_server):
    svc, base = live_server
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page()
        _login(page, base)
        page.click("form[action='/api/ring-now'] button[type=submit]")
        page.wait_for_timeout(800)
        # The page must stay on the dashboard, not show {"ok":...} JSON.
        assert page.url.rstrip("/") == base
        assert "\"ok\"" not in page.content()
        assert len(svc.hardware.rings) >= 1
        browser.close()


def test_unchecking_audio_takes_effect(live_server):
    svc, base = live_server
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page()
        _login(page, base)
        form = "form[action='/api/ring-now']"
        page.select_option(f"{form} select[name=sound_id]", index=1)  # a real sound
        page.uncheck(f"{form} input[name=use_audio]")
        page.click(f"{form} button[type=submit]")
        page.wait_for_timeout(800)
        assert svc.hardware.rings[-1].use_audio is False
        browser.close()

"""Tests that the monitor alerts only on health *transitions* and recovers."""

from __future__ import annotations

from viejoolbel.db import session_scope, set_setting
from viejoolbel.monitor import HealthMonitor
from viejoolbel.notify import Notifier


class RecordingTransport:
    def __init__(self):
        self.posts = []
        self.gets = []

    def post(self, url, payload, headers):
        self.posts.append((url, payload, headers))
        return 200

    def get(self, url):
        self.gets.append(url)
        return 200


def _monitor(settings, alive_holder, transport):
    return HealthMonitor(
        settings,
        scheduler_is_alive=lambda: alive_holder["alive"],
        notifier=Notifier(transport=transport),
    )


def test_alert_on_fault_then_recovery(initialized_db, settings):
    with session_scope() as s:
        set_setting(s, "notify_webhook_url", "https://ntfy.sh/test")
    alive = {"alive": True}
    t = RecordingTransport()
    mon = _monitor(settings, alive, t)

    # Healthy -> no alert.
    r1 = mon.evaluate_once()
    assert r1.ok and len(t.posts) == 0

    # Fault appears -> exactly one alert.
    alive["alive"] = False
    r2 = mon.evaluate_once()
    assert not r2.ok and len(t.posts) == 1

    # Still faulty -> no repeat alert.
    mon.evaluate_once()
    assert len(t.posts) == 1

    # Recovered -> one recovery alert.
    alive["alive"] = True
    mon.evaluate_once()
    assert len(t.posts) == 2


def test_no_alert_without_webhook(initialized_db, settings):
    alive = {"alive": False}
    t = RecordingTransport()
    mon = _monitor(settings, alive, t)
    mon.evaluate_once()
    assert t.posts == []


def test_last_report_is_stored(initialized_db, settings):
    alive = {"alive": True}
    mon = _monitor(settings, alive, RecordingTransport())
    mon.evaluate_once()
    assert mon.last_report is not None and mon.last_report.ok

"""Tests for the pure-ish health evaluation (fault reporting, NFR-2)."""

from __future__ import annotations

import datetime as dt

from viejoolbel import health
from viejoolbel.db import session_scope
from viejoolbel.hardware.mock import MockHardware
from viejoolbel.health import (
    Level,
    check_clock,
    check_hardware,
    check_scheduler,
    check_writable,
)
from viejoolbel.models import RingLog, RingSource

TZ = dt.UTC


def test_clock_error_when_year_implausible():
    c = check_clock(dt.datetime(1970, 1, 1, tzinfo=TZ), min_year=2024)
    assert c.level is Level.ERROR and "not set" in c.detail


def test_clock_ok_when_plausible():
    assert check_clock(dt.datetime(2025, 9, 1, tzinfo=TZ), min_year=2024).level is Level.OK


def test_scheduler_check():
    assert check_scheduler(True).level is Level.OK
    assert check_scheduler(False).level is Level.ERROR


def test_storage_check_ok_when_writable(tmp_path):
    assert check_writable(tmp_path).level is Level.OK


def test_storage_check_errors_when_not_writable(tmp_path):
    # A path that is not a writable directory (here a regular file) makes the
    # probe write fail exactly as a read-only mount would — and reliably so even
    # when the suite runs as root, which ignores plain permission bits.
    not_a_dir = tmp_path / "afile"
    not_a_dir.write_text("x")
    c = check_writable(not_a_dir)
    assert c.level is Level.ERROR
    assert "not writable" in c.detail


def test_hardware_check_ok_for_normal_driver():
    # A deliberately-chosen mock (dev/CI) is fine: no fallback_reason.
    assert check_hardware(MockHardware()).level is Level.OK


def test_hardware_check_errors_on_silent_fallback():
    hw = MockHardware(fallback_reason="RPi.GPIO missing; bell will not fire")
    c = check_hardware(hw)
    assert c.level is Level.ERROR
    assert "bell will not fire" in c.detail


def test_evaluate_flags_degraded_hardware(initialized_db, settings):
    now = dt.datetime(2025, 9, 1, 12, 0, tzinfo=TZ)
    hw = MockHardware(fallback_reason="GPIO driver unavailable")
    with session_scope() as s:
        report = health.evaluate(
            s,
            now=now,
            data_dir=settings.data_dir,
            scheduler_alive=True,
            min_year=2024,
            hardware=hw,
        )
    assert report.level is Level.ERROR
    assert any(c.name == "hardware" for c in report.problems)


def test_report_level_is_worst_check(initialized_db, settings):
    now = dt.datetime(2025, 9, 1, 12, 0, tzinfo=TZ)
    with session_scope() as s:
        report = health.evaluate(
            s,
            now=now,
            data_dir=settings.data_dir,
            scheduler_alive=False,  # forces ERROR
            min_year=2024,
        )
    assert report.level is Level.ERROR
    assert not report.ok
    assert any(c.name == "scheduler" for c in report.problems)


def test_recent_ring_failure_flags_error(initialized_db, settings):
    now = dt.datetime(2025, 9, 1, 12, 0, tzinfo=TZ)
    with session_scope() as s:
        s.add(
            RingLog(
                ts=now.replace(tzinfo=None),
                source=RingSource.SCHEDULED,
                ok=False,
                detail="amp offline",
            )
        )
    with session_scope() as s:
        report = health.evaluate(
            s, now=now, data_dir=settings.data_dir, scheduler_alive=True, min_year=2024
        )
    assert report.level is Level.ERROR
    assert any(c.name == "rings" and "amp offline" in c.detail for c in report.checks)


def test_healthy_report_is_ok(initialized_db, settings):
    now = dt.datetime(2025, 9, 1, 12, 0, tzinfo=TZ)
    with session_scope() as s:
        report = health.evaluate(
            s, now=now, data_dir=settings.data_dir, scheduler_alive=True, min_year=2024
        )
    assert report.ok and report.level is Level.OK

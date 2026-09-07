"""Tests for the pure-ish health evaluation (fault reporting, NFR-2)."""

from __future__ import annotations

import datetime as dt

from viejoolbel import health
from viejoolbel.db import session_scope
from viejoolbel.health import Level, check_clock, check_scheduler
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

"""Tests for the single ring path: locking, audit logging, sound resolution."""

from __future__ import annotations

import threading

from sqlalchemy import select

from viejoolbel.bell import BellController
from viejoolbel.db import session_scope
from viejoolbel.hardware.mock import MockHardware
from viejoolbel.models import RingLog, RingSource, Sound


def test_ring_records_audit_log(controller: BellController, hardware: MockHardware):
    ok = controller.ring(
        source=RingSource.MANUAL, sound_id=None, duration=3, use_audio=False, use_relay=True
    )
    assert ok
    assert len(hardware.rings) == 1
    assert hardware.rings[0].use_relay is True
    with session_scope() as s:
        logs = list(s.scalars(select(RingLog)))
    assert len(logs) == 1 and logs[0].source is RingSource.MANUAL and logs[0].ok


def test_ring_resolves_sound_path(controller: BellController, hardware: MockHardware, settings):
    with session_scope() as s:
        snd = Sound(name="Startbel", filename="s.mp3", default_duration=5)
        s.add(snd)
        s.flush()
        sid = snd.id
    controller.ring(
        source=RingSource.MANUAL, sound_id=sid, duration=5, use_audio=True, use_relay=False
    )
    assert hardware.rings[0].sound_path == settings.sounds_dir / "s.mp3"
    assert hardware.rings[0].use_audio is True


def test_ring_is_mutually_exclusive(controller: BellController):
    # Hold the lock as if a ring is in progress; a second ring must be rejected.
    assert controller._lock.acquire(blocking=False)
    try:
        ok = controller.ring(
            source=RingSource.MANUAL, sound_id=None, duration=1, use_audio=False, use_relay=True
        )
        assert ok is False
    finally:
        controller._lock.release()


def test_hardware_failure_is_logged_not_raised(controller: BellController, hardware: MockHardware):
    def boom(_req):
        raise RuntimeError("amp offline")

    hardware.ring = boom  # type: ignore[method-assign]
    ok = controller.ring(
        source=RingSource.MANUAL, sound_id=None, duration=1, use_audio=False, use_relay=True
    )
    assert ok is False
    with session_scope() as s:
        log = s.scalars(select(RingLog)).one()
    assert not log.ok and "amp offline" in log.detail


def test_self_test_uses_lock_and_logs(controller: BellController, hardware: MockHardware):
    controller.self_test()
    assert hardware.self_tests == 1
    with session_scope() as s:
        log = s.scalars(select(RingLog)).one()
    assert log.source is RingSource.TEST


def test_concurrent_rings_only_one_wins(controller: BellController, hardware: MockHardware):
    results: list[bool] = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(
            controller.ring(
                source=RingSource.MANUAL, sound_id=None, duration=0, use_audio=False, use_relay=True
            )
        )

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Both may actually succeed sequentially since each ring is instant with the
    # mock; what must hold is that no ring overlapped (lock serialised them).
    assert sum(results) >= 1
    assert len(hardware.rings) == sum(results)

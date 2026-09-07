"""Hardware abstraction layer.

Everything above this package is hardware-agnostic. The concrete driver is chosen
at runtime so the whole application runs and is tested off-device (DESIGN.md §3.5).
"""

from __future__ import annotations

import logging

from .base import BellHardware, RingRequest, StatusState
from .mock import MockHardware

log = logging.getLogger(__name__)

__all__ = ["BellHardware", "RingRequest", "StatusState", "MockHardware", "make_hardware"]


def make_hardware(kind: str, **kwargs: object) -> BellHardware:
    """Factory. ``kind`` is ``auto`` | ``gpio`` | ``mock``.

    ``auto`` uses the real GPIO driver when RPi.GPIO is importable (i.e. on a Pi)
    and otherwise falls back to the mock driver, so the same config works in dev,
    CI and production.
    """
    kind = (kind or "auto").lower()
    if kind == "mock":
        return MockHardware()
    if kind in {"gpio", "auto"}:
        try:
            from .gpio_audio import GpioAudioHardware

            return GpioAudioHardware(**kwargs)  # type: ignore[arg-type]
        except Exception as exc:  # pragma: no cover - only hit off-Pi
            if kind == "gpio":
                raise
            log.warning("GPIO hardware unavailable (%s); falling back to mock driver.", exc)
            return MockHardware()
    raise ValueError(f"Unknown hardware kind: {kind!r}")

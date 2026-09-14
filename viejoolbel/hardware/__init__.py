"""Hardware abstraction layer.

Everything above this package is hardware-agnostic. The concrete driver is chosen
at runtime so the whole application runs and is tested off-device (DESIGN.md §3.5).
"""

from __future__ import annotations

import logging

from .base import BellHardware, RingRequest, StatusState
from .mock import MockHardware

log = logging.getLogger(__name__)

__all__ = [
    "BellHardware",
    "RingRequest",
    "StatusState",
    "MockHardware",
    "make_hardware",
    "raspberry_pi_model",
]


def raspberry_pi_model() -> str | None:
    """Return the board model string if this looks like a Raspberry Pi, else None.

    Used to tell a legitimate dev/CI mock fall-back apart from a *device* that
    was supposed to drive real hardware but can't — on the latter a silent mock
    means the bell is dead while every ring still reports success.
    """
    for path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            with open(path, "rb") as f:  # noqa: PTH123 - /proc & /sys are not real paths
                text = f.read().decode("utf-8", "replace").replace("\x00", "").strip()
        except OSError:
            continue
        if "raspberry pi" in text.lower():
            return text
    return None


def make_hardware(kind: str, **kwargs: object) -> BellHardware:
    """Factory. ``kind`` is ``auto`` | ``gpio`` | ``mock``.

    ``auto`` uses the real GPIO driver when RPi.GPIO is importable (i.e. on a Pi)
    and otherwise falls back to the mock driver, so the same config works in dev,
    CI and production.

    Crucially, a fall-back *on a real Pi* is a misconfiguration, not a normal dev
    convenience: it leaves the bell and relay silently dead while the web UI and
    scheduler happily report every ring as successful. In that case we log an
    error and tag the mock with ``fallback_reason`` so the health check surfaces
    it, instead of pretending everything works.
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
            pi = raspberry_pi_model()
            if pi is not None:
                reason = (
                    f"GPIO driver unavailable on {pi}: {exc}. The bell and relay "
                    "will NOT fire even though rings report success. Install the Pi "
                    "extra (pip install '.[pi]', which pulls in RPi.GPIO) and restart "
                    "the service."
                )
                log.error("%s", reason)
                return MockHardware(fallback_reason=reason)
            log.warning(
                "GPIO hardware unavailable (%s); using the mock driver "
                "(expected when not running on a Raspberry Pi).",
                exc,
            )
            return MockHardware()
    raise ValueError(f"Unknown hardware kind: {kind!r}")

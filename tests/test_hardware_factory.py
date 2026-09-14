"""The hardware factory must make a mock fall-back on a real Pi *visible*.

Regression test for the confusing installation failure where the 'Bel nu' button
did nothing (and no scheduled/physical bell rang) while audio over SSH worked:
RPi.GPIO was not installed, so ``make_hardware("auto")`` silently swapped in the
simulation driver and every ring reported success.
"""

from __future__ import annotations

import pytest

from viejoolbel import hardware
from viejoolbel.hardware import make_hardware
from viejoolbel.hardware.mock import MockHardware

# The GPIO pin map the real driver needs; off a Pi it never gets past importing
# RPi.GPIO, but supplying them keeps the call well-formed.
PINS = {"relay_pin": 17, "amp_enable_pin": 27, "button_pin": 22, "led_pin": 23}


def test_explicit_mock_has_no_fallback_reason():
    hw = make_hardware("mock")
    assert isinstance(hw, MockHardware)
    assert hw.fallback_reason is None


def test_auto_off_pi_falls_back_silently(monkeypatch):
    # Off a Pi (no RPi.GPIO), the mock is expected and must NOT be flagged.
    monkeypatch.setattr(hardware, "raspberry_pi_model", lambda: None)
    hw = make_hardware("auto")
    assert isinstance(hw, MockHardware)
    assert hw.fallback_reason is None


def test_auto_on_pi_flags_the_fallback(monkeypatch):
    # On a Pi where the GPIO driver can't be built, the mock must carry a reason
    # so the health check turns it into a visible error instead of a silent dud.
    monkeypatch.setattr(hardware, "raspberry_pi_model", lambda: "Raspberry Pi 5 Model B")
    hw = make_hardware("auto")
    assert isinstance(hw, MockHardware)
    assert hw.fallback_reason is not None
    assert "Raspberry Pi 5" in hw.fallback_reason


def test_gpio_kind_raises_instead_of_falling_back(monkeypatch):
    # An explicit hardware="gpio" must fail loudly rather than degrade to mock,
    # even on a machine that looks like a Pi.
    monkeypatch.setattr(hardware, "raspberry_pi_model", lambda: "Raspberry Pi 5 Model B")
    with pytest.raises(ImportError):
        make_hardware("gpio", **PINS)

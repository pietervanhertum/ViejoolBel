"""Real Raspberry Pi driver: GPIO relay + amplifier-enable + status LED + button,
and audio playback through the default ALSA device.

Imported lazily by :func:`viejoolbel.hardware.make_hardware` so that importing the
package never requires ``RPi.GPIO`` on a development machine.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from .base import RingRequest, StatusState

log = logging.getLogger(__name__)


def build_play_cmd(sound_path: Path, duration: float, volume_db: int = 0) -> list[str]:
    """Build the ffplay command, applying the configured volume (in dB) when set.

    Kept as a pure function so the volume behaviour is unit-testable without audio
    hardware. ffplay handles mp3/wav/ogg and honours a hard timeout via ``-t``.
    """
    cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", "-t", str(duration)]
    if volume_db:
        cmd += ["-af", f"volume={volume_db}dB"]
    cmd.append(str(sound_path))
    return cmd


class GpioAudioHardware:
    """Concrete :class:`~viejoolbel.hardware.base.BellHardware` implementation."""

    def __init__(
        self,
        *,
        relay_pin: int,
        amp_enable_pin: int,
        button_pin: int,
        led_pin: int,
        amp_warmup_seconds: float = 1.0,
    ) -> None:
        import RPi.GPIO as GPIO  # imported here so dev machines never need it

        self._GPIO = GPIO
        self._relay_pin = relay_pin
        self._amp_enable_pin = amp_enable_pin
        self._button_pin = button_pin
        self._led_pin = led_pin
        self._amp_warmup = amp_warmup_seconds

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(relay_pin, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(amp_enable_pin, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(led_pin, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        self.set_status(StatusState.IDLE)

    def ring(self, request: RingRequest) -> None:
        GPIO = self._GPIO
        self.set_status(StatusState.RINGING)
        try:
            if request.use_relay:
                GPIO.output(self._relay_pin, GPIO.HIGH)
            if request.use_audio and request.sound_path is not None:
                GPIO.output(self._amp_enable_pin, GPIO.HIGH)
                time.sleep(self._amp_warmup)  # let the amplifier settle (anti-pop)
                self._play(request)
                GPIO.output(self._amp_enable_pin, GPIO.LOW)
            elif request.use_relay:
                time.sleep(request.duration)
        finally:
            GPIO.output(self._relay_pin, GPIO.LOW)
            GPIO.output(self._amp_enable_pin, GPIO.LOW)
            self.set_status(StatusState.IDLE)

    def _play(self, request: RingRequest) -> None:
        assert request.sound_path is not None
        cmd = build_play_cmd(request.sound_path, request.duration, request.volume_db)
        try:
            subprocess.run(cmd, check=True, timeout=request.duration + 5)
        except FileNotFoundError:
            log.error("ffplay not found; install ffmpeg. Falling back to aplay.")
            subprocess.run(
                ["aplay", str(request.sound_path)], check=False, timeout=request.duration + 5
            )
        except subprocess.TimeoutExpired:
            log.warning("Playback exceeded timeout and was terminated.")

    def set_status(self, state: StatusState) -> None:
        # Single LED: on while ringing/syncing, off when idle, blink handled by
        # a future PWM enhancement. Kept simple and robust here.
        on = state in {StatusState.RINGING, StatusState.SYNCING, StatusState.ERROR}
        self._GPIO.output(self._led_pin, self._GPIO.HIGH if on else self._GPIO.LOW)

    def read_button(self) -> bool:
        # Active-low with pull-up: pressed == 0.
        return self._GPIO.input(self._button_pin) == 0

    def self_test(self) -> None:
        self.ring(RingRequest(sound_path=None, duration=0.5, use_audio=False, use_relay=True))

    def cleanup(self) -> None:
        try:
            self._GPIO.cleanup()
        except Exception:  # pragma: no cover
            log.exception("GPIO cleanup failed")

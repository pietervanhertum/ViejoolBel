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


def build_play_pipeline(
    sound_path: Path, duration: float, volume_db: int = 0, device: str = ""
) -> tuple[list[str], list[str]]:
    """Build the ``(ffmpeg, aplay)`` pipeline that decodes *sound_path* and plays it
    through ALSA, applying the configured volume (in dB) when set.

    We deliberately use ``ffmpeg | aplay`` rather than ``ffplay``: ffplay plays via
    SDL, which on a headless service (no login session) often cannot open the audio
    device and then *silently* falls back to a dummy sink — it "succeeds" (exit 0)
    while producing no sound. ``aplay`` talks to ALSA directly and returns a real
    error when the device cannot be opened, so a genuine failure is recorded.

    ffmpeg decodes any format (wav/mp3/ogg) to raw PCM; ``aplay`` (via a ``plug``
    device) converts to whatever the card supports. Kept pure for unit testing.
    """
    af = ["-af", f"volume={volume_db}dB"] if volume_db else []
    decode = [
        "ffmpeg", "-nostdin", "-loglevel", "error",
        "-i", str(sound_path),
        *af,
        "-t", str(duration),
        "-f", "s16le", "-ar", "44100", "-ac", "2", "-",
    ]
    play = [
        "aplay", "-q", "-f", "S16_LE", "-r", "44100", "-c", "2",
        *(["-D", device] if device else []),
        "-",
    ]
    return decode, play


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
        audio_device: str = "",
    ) -> None:
        import RPi.GPIO as GPIO  # imported here so dev machines never need it

        self._GPIO = GPIO
        self._relay_pin = relay_pin
        self._amp_enable_pin = amp_enable_pin
        self._button_pin = button_pin
        self._led_pin = led_pin
        self._amp_warmup = amp_warmup_seconds
        self._audio_device = audio_device

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
        decode, play = build_play_pipeline(
            request.sound_path, request.duration, request.volume_db, self._audio_device
        )
        timeout = request.duration + 5
        try:
            decoder = subprocess.Popen(  # noqa: S603 - argv list, no shell
                decode, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
            )
            try:
                player = subprocess.run(  # noqa: S603 - argv list, no shell
                    play, stdin=decoder.stdout, capture_output=True, timeout=timeout
                )
            finally:
                if decoder.stdout is not None:
                    decoder.stdout.close()  # let ffmpeg get SIGPIPE if aplay stopped
                try:
                    decoder.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    decoder.kill()
        except FileNotFoundError as exc:
            # Missing ffmpeg or alsa-utils: surface it so the ring is logged failed.
            raise RuntimeError(f"audiogereedschap ontbreekt (ffmpeg/aplay): {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("audio afspelen duurde te lang en is afgebroken") from exc
        if player.returncode != 0:
            detail = (player.stderr or b"").decode("utf-8", "replace").strip()
            # aplay reports here when the device cannot be opened (wrong output,
            # busy, or no permission) — no more silent "success".
            raise RuntimeError(
                f"audio-uitvoer mislukt: {detail[:200] or f'aplay rc={player.returncode}'}"
            )

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

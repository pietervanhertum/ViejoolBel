"""Wires the pieces together into a runnable service and owns their lifecycle."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from .bell import BellController
from .config import Settings
from .db import get_setting, init_engine, install_default_sounds, session_scope
from .hardware import make_hardware
from .hardware.base import BellHardware
from .models import RingSource
from .monitor import HealthMonitor
from .scheduler import BellScheduler

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger(__name__)


class ButtonWatcher:
    """Polls the physical button in a background thread and rings on press,
    with simple debouncing (FR-12)."""

    def __init__(self, hardware: BellHardware, controller: BellController) -> None:
        self._hw = hardware
        self._controller = controller
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="button-watcher", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _default_sound_id(self) -> int | None:
        with session_scope() as s:
            raw = get_setting(s, "default_sound_id", "")
        try:
            return int(raw) if raw else None
        except ValueError:
            return None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if self._hw.read_button():
                    self._controller.ring(
                        source=RingSource.BUTTON,
                        sound_id=self._default_sound_id(),
                        duration=8,
                        use_audio=True,
                        use_relay=True,
                    )
                    time.sleep(1.0)  # debounce
            except Exception:  # never let the watcher thread die
                log.exception("Button watcher error")
            self._stop.wait(0.1)


class Service:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        settings.ensure_dirs()
        init_engine(settings.db_path)
        with session_scope() as s:
            install_default_sounds(s, settings.sounds_dir)
        self.hardware = make_hardware(
            settings.hardware,
            relay_pin=settings.gpio_relay_pin,
            amp_enable_pin=settings.gpio_amp_enable_pin,
            button_pin=settings.gpio_button_pin,
            led_pin=settings.gpio_led_pin,
            amp_warmup_seconds=settings.amp_warmup_seconds,
        )
        self.controller = BellController(self.hardware, settings)
        self.scheduler = BellScheduler(self.controller, settings.timezone)
        self.button = ButtonWatcher(self.hardware, self.controller)
        self.monitor = HealthMonitor(settings, scheduler_is_alive=self.scheduler.is_alive)

    def start(self) -> None:
        self.scheduler.start()
        self.button.start()
        self.monitor.start()
        log.info("ViejoolBel service started (hardware=%s).", type(self.hardware).__name__)

    def stop(self) -> None:
        self.monitor.stop()
        self.button.stop()
        self.scheduler.shutdown()
        self.hardware.cleanup()

    def build_app(self) -> FastAPI:
        from .web.app import create_app

        return create_app(self.controller, self.scheduler, self.settings, monitor=self.monitor)

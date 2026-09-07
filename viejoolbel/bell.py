"""The single ring path.

Every ring — scheduled, manual, physical button or self-test — goes through
:meth:`BellController.ring`, which holds a lock so rings can never overlap (FR-14)
and writes an audit record (FR-24).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from .config import Settings
from .db import get_setting, session_scope
from .hardware.base import BellHardware, RingRequest, StatusState
from .models import RingLog, RingSource, Sound

log = logging.getLogger(__name__)


class BellController:
    def __init__(self, hardware: BellHardware, settings: Settings) -> None:
        self._hw = hardware
        self._settings = settings
        self._lock = threading.Lock()

    @property
    def is_ringing(self) -> bool:
        return self._lock.locked()

    def ring(
        self,
        *,
        source: RingSource,
        sound_id: int | None,
        duration: int,
        use_audio: bool,
        use_relay: bool,
    ) -> bool:
        """Ring once. Returns False if a ring is already in progress (not queued).

        Resolving the sound file and writing the audit log happen here so all
        entry points share identical behaviour.
        """
        acquired = self._lock.acquire(blocking=False)
        if not acquired:
            log.warning("Ring requested from %s while already ringing; ignored.", source.value)
            return False
        try:
            sound_name, sound_path = self._resolve_sound(sound_id)
            request = RingRequest(
                sound_path=sound_path if use_audio else None,
                duration=float(duration),
                use_audio=use_audio and sound_path is not None,
                use_relay=use_relay,
                volume_db=self._volume_db(),
            )
            ok, detail = True, ""
            try:
                self._hw.ring(request)
            except Exception as exc:  # hardware failure must be recorded, not crash
                ok, detail = False, str(exc)[:300]
                self._hw.set_status(StatusState.ERROR)
                log.exception("Ring failed")
            self._log_ring(source, sound_name, request, ok, detail)
            return ok
        finally:
            self._lock.release()

    def self_test(self) -> None:
        with self._lock:
            self._hw.self_test()
            with session_scope() as s:
                s.add(
                    RingLog(
                        source=RingSource.TEST,
                        sound_name="(self-test)",
                        used_audio=True,
                        used_relay=True,
                        ok=True,
                    )
                )

    # --- helpers ---------------------------------------------------------
    def _resolve_sound(self, sound_id: int | None) -> tuple[str, Path | None]:
        if sound_id is None:
            return "(relay only)", None
        with session_scope() as s:
            sound = s.get(Sound, sound_id)
            if sound is None:
                return "(missing sound)", None
            return sound.name, self._settings.sounds_dir / sound.filename

    def _volume_db(self) -> int:
        with session_scope() as s:
            try:
                return int(get_setting(s, "volume_db", "0") or "0")
            except ValueError:
                return 0

    def _log_ring(
        self, source: RingSource, sound_name: str, request: RingRequest, ok: bool, detail: str
    ) -> None:
        with session_scope() as s:
            s.add(
                RingLog(
                    source=source,
                    sound_name=sound_name,
                    used_audio=request.use_audio,
                    used_relay=request.use_relay,
                    ok=ok,
                    detail=detail,
                )
            )

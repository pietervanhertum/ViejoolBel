"""Hardware protocol and shared value objects."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


class StatusState(enum.StrEnum):
    IDLE = "idle"  # green: everything OK, waiting
    RINGING = "ringing"  # blue: bell active
    ERROR = "error"  # red: something is wrong
    SYNCING = "syncing"  # yellow: time sync / update in progress


@dataclass(frozen=True)
class RingRequest:
    """A request to ring. ``sound_path`` is None for a relay-only ring."""

    sound_path: Path | None
    duration: float
    use_audio: bool
    use_relay: bool
    volume_db: int = 0


@runtime_checkable
class BellHardware(Protocol):
    """The contract every hardware driver implements (DESIGN.md §3.5).

    Implementations must be safe to call from a single controller thread. The
    higher layers serialise ring calls behind a lock, so drivers need not.
    """

    def ring(self, request: RingRequest) -> None:
        """Perform one ring: pulse the relay and/or play the sound, blocking for
        the duration. Must always leave outputs de-energised when it returns."""
        ...

    def set_status(self, state: StatusState) -> None:
        """Reflect *state* on the status LED (or no-op if none)."""
        ...

    def read_button(self) -> bool:
        """Return True if the physical ring button is currently pressed."""
        ...

    def self_test(self) -> None:
        """Briefly exercise audio and relay so an admin can verify wiring (FR-25)."""
        ...

    def cleanup(self) -> None:
        """Release GPIO / audio resources on shutdown."""
        ...

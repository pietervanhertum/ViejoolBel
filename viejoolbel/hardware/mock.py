"""In-memory hardware driver used in development, CI and all tests.

It records every interaction so tests can assert on them, and it never sleeps for
the real ring duration, keeping the suite fast.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .base import BellHardware, RingRequest, StatusState


@dataclass
class MockHardware(BellHardware):
    rings: list[RingRequest] = field(default_factory=list)
    statuses: list[StatusState] = field(default_factory=list)
    self_tests: int = 0
    cleaned_up: bool = False
    # Tests can toggle this to simulate the physical button being held.
    button_pressed: bool = False

    def ring(self, request: RingRequest) -> None:
        self.set_status(StatusState.RINGING)
        self.rings.append(request)
        self.set_status(StatusState.IDLE)

    def set_status(self, state: StatusState) -> None:
        self.statuses.append(state)

    def read_button(self) -> bool:
        return self.button_pressed

    def self_test(self) -> None:
        self.self_tests += 1

    def cleanup(self) -> None:
        self.cleaned_up = True

#!/usr/bin/env python3
"""Generate the bundled default bell sounds (viejoolbel/assets/sounds/*.wav).

These are simple, original synthesized tones so the system can ring something out
of the box with no uploads and no licensing concerns. Re-run to regenerate:

    python scripts/generate_default_sounds.py
"""

from __future__ import annotations

import math
import pathlib
import struct
import wave

RATE = 22050
OUT = pathlib.Path(__file__).resolve().parent.parent / "viejoolbel" / "assets" / "sounds"


def _write(name: str, samples: list[float]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    peak = max(1e-6, max(abs(s) for s in samples))
    scale = 0.89 / peak  # normalise with a little headroom

    def _pcm(s: float) -> bytes:
        return struct.pack("<h", int(max(-1.0, min(1.0, s * scale)) * 32767))

    frames = b"".join(_pcm(s) for s in samples)
    with wave.open(str(OUT / name), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(frames)
    print("wrote", OUT / name, f"({len(samples) / RATE:.1f}s)")


def _strike(freq: float, dur: float, decay: float = 6.0) -> list[float]:
    """One bell-like strike: fundamental + a few inharmonic partials, exp decay."""
    partials = [(1.0, 1.0), (2.76, 0.5), (5.40, 0.28), (8.93, 0.16)]  # bell-ish ratios
    n = int(dur * RATE)
    out = []
    for i in range(n):
        t = i / RATE
        env = math.exp(-decay * t)
        v = sum(a * math.sin(2 * math.pi * freq * r * t) for r, a in partials)
        out.append(env * v)
    return out


def _silence(dur: float) -> list[float]:
    return [0.0] * int(dur * RATE)


def _electric_bell(dur: float, tone: float = 1150.0, trill: float = 22.0) -> list[float]:
    """Old-school electric school bell: a buzzy tone gated by a fast clapper trill."""
    n = int(dur * RATE)
    out = []
    for i in range(n):
        t = i / RATE
        # square-ish tone (a couple of odd harmonics)
        core = (
            math.sin(2 * math.pi * tone * t)
            + 0.33 * math.sin(2 * math.pi * 3 * tone * t)
            + 0.2 * math.sin(2 * math.pi * 5 * tone * t)
        )
        gate = 0.5 * (1 + math.copysign(1.0, math.sin(2 * math.pi * trill * t)))  # on/off
        overall = min(1.0, t / 0.02) * min(1.0, (dur - t) / 0.05)  # tiny fade in/out
        out.append(core * gate * overall)
    return out


def main() -> None:
    _write("enkele-bel.wav", _strike(660.0, 2.0))
    _write("dubbele-bel.wav", _strike(660.0, 1.1) + _silence(0.15) + _strike(660.0, 1.6))
    _write("schoolbel.wav", _electric_bell(3.0))
    _write("gong.wav", _strike(196.0, 3.2, decay=3.2))


if __name__ == "__main__":
    main()

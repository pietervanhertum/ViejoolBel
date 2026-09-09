"""The configured volume must actually reach the audio player (regression)."""

from __future__ import annotations

from pathlib import Path

from viejoolbel.hardware.gpio_audio import build_play_cmd


def test_no_volume_filter_at_zero():
    cmd = build_play_cmd(Path("/tmp/x.wav"), 8, 0)
    assert "-af" not in cmd
    assert cmd[-1] == "/tmp/x.wav"
    assert "-t" in cmd and "8" in cmd


def test_positive_volume_applies_filter():
    cmd = build_play_cmd(Path("/tmp/x.wav"), 5, 6)
    assert "-af" in cmd
    assert "volume=6dB" in cmd


def test_negative_volume_applies_filter():
    cmd = build_play_cmd(Path("/tmp/x.wav"), 5, -12)
    assert "volume=-12dB" in cmd

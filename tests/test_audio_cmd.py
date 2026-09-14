"""Playback goes through ALSA (ffmpeg | aplay), not ffplay/SDL, and the configured
volume must actually reach the player (regression)."""

from __future__ import annotations

from pathlib import Path

from viejoolbel.hardware.gpio_audio import build_play_pipeline


def test_pipeline_uses_ffmpeg_and_aplay():
    decode, play = build_play_pipeline(Path("/tmp/x.wav"), 8, 0)
    assert decode[0] == "ffmpeg" and play[0] == "aplay"
    # ffmpeg reads the file and streams raw PCM; aplay reads that PCM from stdin.
    assert "/tmp/x.wav" in decode and decode[-1] == "-"
    assert play[-1] == "-"


def test_no_volume_filter_at_zero():
    decode, _play = build_play_pipeline(Path("/tmp/x.wav"), 8, 0)
    assert "-af" not in decode
    assert "-t" in decode and "8" in decode


def test_positive_volume_applies_filter():
    decode, _play = build_play_pipeline(Path("/tmp/x.wav"), 5, 6)
    assert "-af" in decode and "volume=6dB" in decode


def test_negative_volume_applies_filter():
    decode, _play = build_play_pipeline(Path("/tmp/x.wav"), 5, -12)
    assert "volume=-12dB" in decode


def test_device_is_passed_to_aplay_only_when_set():
    _d, play_default = build_play_pipeline(Path("/tmp/x.wav"), 5, 0, "")
    assert "-D" not in play_default
    _d, play_dev = build_play_pipeline(Path("/tmp/x.wav"), 5, 0, "plughw:CARD=Headphones")
    assert play_dev[play_dev.index("-D") + 1] == "plughw:CARD=Headphones"

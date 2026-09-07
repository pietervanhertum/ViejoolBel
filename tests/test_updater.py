"""Tests for update version comparison and API URL derivation (FR-22)."""

from __future__ import annotations

from viejoolbel.updater import _api_url, is_newer


def test_api_url_from_repo():
    assert (
        _api_url("https://github.com/pietervanhertum/ViejoolBel")
        == "https://api.github.com/repos/pietervanhertum/ViejoolBel/releases/latest"
    )


def test_is_newer_true():
    assert is_newer("v0.2.0", "0.1.0")
    assert is_newer("1.0.0", "0.9.9")


def test_is_newer_false_for_same_or_older():
    assert not is_newer("v0.1.0", "0.1.0")
    assert not is_newer("v0.1.0", "0.2.0")


def test_is_newer_fails_safe_on_garbage():
    assert not is_newer("banana", "0.1.0")
    assert not is_newer("v0.1.0", "not-a-version")

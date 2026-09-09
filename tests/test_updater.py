"""Tests for update version comparison and API URL derivation (FR-22)."""

from __future__ import annotations

from viejoolbel.updater import _api_url, is_newer


def test_check_latest_sends_bearer_token(monkeypatch):
    """On a private repo the API check must authenticate with the token."""
    import json as _json

    from viejoolbel import updater

    captured: dict = {}

    class _FakeResp:
        def read(self, *a):
            return _json.dumps({"tag_name": "v0.2.0", "html_url": "u", "body": "b"}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        captured["headers"] = dict(req.headers)
        return _FakeResp()

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    info = updater.check_latest("https://github.com/o/r", token="secret")
    assert info is not None and info.tag == "v0.2.0"
    assert captured["headers"].get("Authorization") == "Bearer secret"


def test_check_latest_falls_back_to_anonymous_on_bad_token(monkeypatch):
    """A stale/expired token yields 401 even on a public repo; the check must
    retry anonymously instead of failing (regression)."""
    import json as _json
    import urllib.error

    from viejoolbel import updater

    class _FakeResp:
        def read(self, *a):
            return _json.dumps({"tag_name": "v0.2.0", "html_url": "u", "body": ""}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        if "Authorization" in req.headers:
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
        return _FakeResp()

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    info = updater.check_latest("https://github.com/o/r", token="bad-token")
    assert info is not None and info.tag == "v0.2.0"


def test_current_version_prefers_installed_tag(tmp_path):
    from viejoolbel import __version__, updater

    assert updater.current_version(tmp_path) == __version__  # no file yet
    (tmp_path / "installed_version").write_text("v0.1.5\n")
    assert updater.current_version(tmp_path) == "v0.1.5"
    assert updater.current_version(None) == __version__


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
    # "not-a-version" has no digits at all -> unparseable -> not newer.
    assert not is_newer("v0.2.0", "not-a-version")


def test_is_newer_tolerates_stray_punctuation_in_tag():
    # Regression: a release tagged "v.0.1.1" must still be seen as newer than
    # 0.1.0 (previously parsed to an empty component and was treated as up-to-date).
    assert is_newer("v.0.1.1", "0.1.0")
    assert is_newer("release-0.2.0", "0.1.9")
    assert not is_newer("v.0.1.0", "0.1.0")


def test_is_valid_tag():
    from viejoolbel.updater import is_valid_tag

    assert is_valid_tag("v0.1.1")
    assert is_valid_tag("v.0.1.1")  # tolerated, argv-safe, has a digit
    assert is_valid_tag("0.1.2")
    assert not is_valid_tag("; rm -rf /")
    assert not is_valid_tag("main")  # no digit
    assert not is_valid_tag("")

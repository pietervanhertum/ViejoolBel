"""Tests for the webhook alert + heartbeat notifier using a fake transport."""

from __future__ import annotations

import json

from viejoolbel.notify import Notifier


class FakeTransport:
    def __init__(self, *, fail: bool = False, status: int = 200) -> None:
        self.fail = fail
        self.status = status
        self.posts: list[tuple[str, dict, dict]] = []
        self.gets: list[str] = []

    def post(self, url, payload, headers):
        if self.fail:
            raise ConnectionError("boom")
        self.posts.append((url, json.loads(payload), headers))
        return self.status

    def get(self, url):
        if self.fail:
            raise ConnectionError("boom")
        self.gets.append(url)
        return self.status


def test_alert_posts_json():
    t = FakeTransport()
    n = Notifier(transport=t)
    assert n.alert("https://ntfy.sh/x", level="error", title="T", message="M") is True
    url, body, headers = t.posts[0]
    assert url == "https://ntfy.sh/x"
    assert body["level"] == "error" and body["message"] == "M"
    assert headers["Priority"] == "urgent"


def test_alert_noop_without_url():
    t = FakeTransport()
    assert Notifier(transport=t).alert("", level="error", title="T", message="M") is False
    assert t.posts == []


def test_alert_returns_false_on_http_error():
    t = FakeTransport(status=500)
    assert Notifier(transport=t).alert("https://x", level="ok", title="T", message="M") is False


def test_alert_swallows_transport_error():
    t = FakeTransport(fail=True)
    assert Notifier(transport=t).alert("https://x", level="ok", title="T", message="M") is False


def test_heartbeat():
    t = FakeTransport()
    n = Notifier(transport=t)
    assert n.heartbeat("https://hc-ping.com/abc") is True
    assert t.gets == ["https://hc-ping.com/abc"]
    assert n.heartbeat("") is False

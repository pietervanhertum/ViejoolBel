"""Outbound fault alerting and heartbeat.

Two independent mechanisms (see docs and DESIGN.md §5):

* **Webhook alert** — when a fault appears (health transitions to WARN/ERROR) the
  device POSTs a short JSON message to a configured URL. This works with ntfy.sh,
  Discord, Slack, Home Assistant, or any custom endpoint, and requires the device
  to be online at that moment.

* **Heartbeat** — while healthy the device periodically pings a URL (e.g.
  healthchecks.io). If the pings stop, that external service alerts you. This is
  the only thing that can catch a device that is fully offline or powered down, so
  it complements the webhook rather than replacing it.

Both are best-effort: network errors are logged and swallowed, never raised into
the ring path.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Protocol

log = logging.getLogger(__name__)

_TIMEOUT = 8.0


class Transport(Protocol):
    def post(self, url: str, payload: bytes, headers: dict[str, str]) -> int: ...
    def get(self, url: str) -> int: ...


class UrllibTransport:
    def post(self, url: str, payload: bytes, headers: dict[str, str]) -> int:
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
            return int(resp.status)

    def get(self, url: str) -> int:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:  # noqa: S310
            return int(resp.status)


class Notifier:
    """Sends fault alerts and heartbeats via a pluggable transport (so tests can
    inject a fake and assert without real network)."""

    def __init__(self, transport: Transport | None = None) -> None:
        self._transport = transport or UrllibTransport()

    def alert(self, webhook_url: str, *, level: str, title: str, message: str) -> bool:
        if not webhook_url:
            return False
        body = json.dumps(
            {"title": title, "message": message, "level": level, "source": "viejoolbel"}
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            # ntfy.sh reads these headers; harmless for other endpoints.
            "Title": title,
            "Priority": "urgent" if level == "error" else "default",
        }
        try:
            status = self._transport.post(webhook_url, body, headers)
            if status >= 400:
                log.warning("Alert webhook returned HTTP %s", status)
                return False
            return True
        except Exception as exc:
            log.warning("Alert webhook failed: %s", exc)
            return False

    def heartbeat(self, url: str) -> bool:
        if not url:
            return False
        try:
            self._transport.get(url)
            return True
        except Exception as exc:
            log.warning("Heartbeat failed: %s", exc)
            return False

"""Minimal ``sd_notify`` client so the app can talk to the systemd watchdog
without pulling in a C dependency.

systemd sets ``NOTIFY_SOCKET`` in the environment when the unit uses
``Type=notify``/``WatchdogSec``. If it is absent (dev, tests, non-systemd) every
call is a no-op, so the same code runs everywhere.
"""

from __future__ import annotations

import logging
import os
import socket

log = logging.getLogger(__name__)


def _send(message: str) -> bool:
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return False
    # Abstract namespace sockets start with '@'.
    path = "\0" + addr[1:] if addr.startswith("@") else addr
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(path)
            sock.sendall(message.encode("utf-8"))
        return True
    except OSError as exc:  # pragma: no cover - depends on the host
        log.debug("sd_notify failed: %s", exc)
        return False


def ready() -> bool:
    """Tell systemd startup is complete (READY=1)."""
    return _send("READY=1")


def watchdog() -> bool:
    """Pet the systemd watchdog (WATCHDOG=1). Must be called well within
    ``WatchdogSec`` or systemd restarts the service."""
    return _send("WATCHDOG=1")


def status(text: str) -> bool:
    """Set the unit's human-readable status line (shown by ``systemctl status``)."""
    return _send(f"STATUS={text}")

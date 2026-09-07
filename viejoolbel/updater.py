"""Safe self-update (FR-22).

The strategy is deliberately conservative: never mutate the running install in
place. Instead fetch the newest tagged release into a *new* directory, run a health
check, then atomically flip the ``current`` symlink and restart. If the new version
is unhealthy, the symlink is flipped back — the device can never be bricked by an
update (NFR-3).

The heavy lifting (systemd restart, symlink flip) is done by a small privileged
helper script installed at ``deploy/apply_update.sh`` and invoked via a tightly
scoped sudoers rule; this module orchestrates and reports.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass

from . import __version__

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    url: str
    notes: str


def _api_url(repo: str) -> str:
    # https://github.com/owner/name -> https://api.github.com/repos/owner/name/releases/latest
    owner_name = repo.rstrip("/").removeprefix("https://github.com/")
    return f"https://api.github.com/repos/{owner_name}/releases/latest"


def check_latest(repo: str, *, timeout: float = 10.0) -> ReleaseInfo | None:
    """Query the repository's latest release. Returns None if none/unreachable."""
    try:
        req = urllib.request.Request(
            _api_url(repo), headers={"Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted host)
            data = json.load(resp)
    except Exception as exc:
        log.warning("Update check failed: %s", exc)
        return None
    tag = data.get("tag_name")
    if not tag:
        return None
    return ReleaseInfo(tag=tag, url=data.get("html_url", ""), notes=data.get("body", "") or "")


def current_version() -> str:
    return __version__


def is_newer(latest_tag: str, current: str | None = None) -> bool:
    """Compare ``vX.Y.Z`` style tags. Missing/odd tags are treated as not-newer
    to fail safe (we never auto-apply something we cannot reason about)."""
    cur = current or current_version()

    def parse(t: str) -> tuple[int, ...] | None:
        t = t.lstrip("vV").strip()
        parts = t.split(".")
        try:
            return tuple(int(p) for p in parts)
        except ValueError:
            return None

    a, b = parse(latest_tag), parse(cur)
    if a is None or b is None:
        return False
    return a > b

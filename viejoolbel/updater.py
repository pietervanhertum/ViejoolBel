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
import re
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__

log = logging.getLogger(__name__)

# Release tags we accept, e.g. "v0.2.0" or "0.2.0". Anything else is rejected
# before it can reach the shell command (defence in depth; the call is argv-based).
_TAG_RE = re.compile(r"^v?\d+(\.\d+){0,3}$")


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


def is_valid_tag(tag: str) -> bool:
    return bool(_TAG_RE.match(tag.strip()))


def launch_update(tag: str, script: Path) -> tuple[bool, str]:
    """Kick off the privileged updater for *tag* and return immediately.

    The apply script restarts the service (which kills this process), so it is
    launched **detached** in its own session; the web response returns before the
    restart happens. Returns ``(started, message)``. On a development machine —
    where the script or ``sudo`` is absent — it fails gracefully rather than
    raising, so the UI can show a clear message.
    """
    tag = tag.strip()
    if not is_valid_tag(tag):
        return False, f"Ongeldige versietag: {tag!r}"
    if shutil.which("sudo") is None:
        return False, "sudo niet beschikbaar (alleen op het geïnstalleerde toestel)."
    if not script.exists():
        return False, f"Updatescript niet gevonden op {script} (alleen op het toestel)."
    try:
        subprocess.Popen(  # noqa: S603 - argv list, tag validated above
            ["sudo", str(script), tag],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return False, f"Kon update niet starten: {exc}"
    return True, f"Update naar {tag} gestart. Het toestel herstart zo meteen."

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
from typing import IO

from . import __version__

log = logging.getLogger(__name__)

# A tag is accepted for `apply` if it contains a digit and only characters that are
# safe as a single argv element (defence in depth; the call is argv-based, not a
# shell). This is deliberately lenient — e.g. "v0.1.1", "0.1.1" and even a
# mistyped "v.0.1.1" all pass — because a strict pattern silently turned a typo'd
# release tag into "you're up to date". See _version_tuple() for comparison.
_TAG_SAFE_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


@dataclass(frozen=True)
class ReleaseInfo:
    tag: str
    url: str
    notes: str


def _api_url(repo: str) -> str:
    # https://github.com/owner/name -> https://api.github.com/repos/owner/name/releases/latest
    owner_name = repo.rstrip("/").removeprefix("https://github.com/")
    return f"https://api.github.com/repos/{owner_name}/releases/latest"


def check_latest(
    repo: str, *, token: str | None = None, timeout: float = 10.0
) -> ReleaseInfo | None:
    """Query the repository's latest release. Returns None if none/unreachable.

    Pass *token* (a GitHub PAT or fine-grained token) to reach a **private**
    repository's API; without it the API returns 404 for private repos. If a token
    is given but rejected (a stale/expired token returns HTTP 401 even for a public
    repo), we retry once anonymously, so a leftover bad token never blocks updates
    on a public repository.
    """
    token = (token or "").strip() or None
    info = _fetch_release(repo, token, timeout)
    if info is None and token is not None:
        info = _fetch_release(repo, None, timeout)
    return info


def _fetch_release(repo: str, token: str | None, timeout: float) -> ReleaseInfo | None:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(_api_url(repo), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted host)
            data = json.load(resp)
    except Exception as exc:
        log.warning("Update check failed (token=%s): %s", bool(token), exc)
        return None
    tag = data.get("tag_name")
    if not tag:
        return None
    return ReleaseInfo(tag=tag, url=data.get("html_url", ""), notes=data.get("body", "") or "")


def current_version(data_dir: Path | None = None) -> str:
    """The running version. Prefer the installed release tag (written by
    apply_update.sh) so it matches what was actually deployed, even when the code's
    ``__version__`` lags the release tag; fall back to ``__version__``."""
    if data_dir is not None:
        try:
            tag = (data_dir / "installed_version").read_text().strip()
            if tag:
                return tag
        except OSError:
            pass
    return __version__


def _version_tuple(text: str) -> tuple[int, ...] | None:
    """Extract a numeric version tuple from a tag, tolerant of prefixes and stray
    punctuation: "v0.1.1", "0.1.1", "v.0.1.1" and "release-0.1.1" all yield
    (0, 1, 1). Returns None only when there is no number at all."""
    nums = re.findall(r"\d+", text)
    if not nums:
        return None
    return tuple(int(n) for n in nums[:4])


def is_newer(latest_tag: str, current: str | None = None) -> bool:
    """True when *latest_tag* is a strictly newer version than *current* (or the
    running version). Unparseable input fails safe to not-newer."""
    a, b = _version_tuple(latest_tag), _version_tuple(current or current_version())
    if a is None or b is None:
        return False
    return a > b


def is_valid_tag(tag: str) -> bool:
    """Accept a tag for `apply`: at least one digit and only argv-safe characters."""
    tag = tag.strip()
    return bool(_TAG_SAFE_RE.match(tag)) and any(c.isdigit() for c in tag)


def launch_update(tag: str, script: Path, *, log_path: Path | None = None) -> tuple[bool, str]:
    """Kick off the privileged updater for *tag* and return immediately.

    The apply script restarts the service (which kills this process), so it is
    launched **detached** in its own session; the web response returns before the
    restart happens. Returns ``(started, message)``. On a development machine —
    where the script or ``sudo`` is absent — it fails gracefully rather than
    raising, so the UI can show a clear message.

    All output is appended to *log_path* (not discarded), so a failure that
    happens after this returns — a sudo denial, a failed clone, a failed health
    check — is still visible afterwards (in the UI's "updatelog" and the file).
    """
    tag = tag.strip()
    if not is_valid_tag(tag):
        return False, f"Ongeldige versietag: {tag!r}"
    if shutil.which("sudo") is None:
        return False, "sudo niet beschikbaar (alleen op het geïnstalleerde toestel)."
    if not script.exists():
        return False, f"Updatescript niet gevonden op {script} (alleen op het toestel)."

    out: int | IO[bytes] = subprocess.DEVNULL
    log_file: IO[bytes] | None = None
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(log_path, "ab")  # noqa: SIM115 - handed to the child process
            log_file.write(f"\n===== update -> {tag} @ {_now()} =====\n".encode())
            log_file.flush()
            out = log_file
        except OSError as exc:
            log.warning("Could not open update log %s: %s", log_path, exc)
    try:
        subprocess.Popen(  # noqa: S603 - argv list, tag validated above
            ["sudo", str(script), tag],
            start_new_session=True,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        return False, f"Kon update niet starten: {exc}"
    finally:
        if log_file is not None:
            log_file.close()
    return True, f"Update naar {tag} gestart. Het toestel herstart zo meteen."


def _now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


def read_log(log_path: Path, *, max_bytes: int = 8000) -> str:
    """Return the tail of the update log for display in the UI."""
    try:
        data = log_path.read_bytes()
    except OSError:
        return ""
    return data[-max_bytes:].decode("utf-8", "replace")

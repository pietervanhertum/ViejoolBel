"""Guards for the deployment unit + sudoers that make the update button work.

Regression: the systemd unit had NoNewPrivileges=true, which propagates to child
processes and blocks setuid binaries. The web app runs its privileged helpers via
sudo, so the update button failed with:
    sudo: The "no new privileges" flag is set, which prevents sudo from running as root.
"""

from __future__ import annotations

import re
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"


def _unit_text() -> str:
    return (DEPLOY / "systemd" / "viejoolbel.service").read_text()


def test_no_new_privileges_is_not_enabled():
    # sudo (setuid) must be able to escalate; NoNewPrivileges=true would break it.
    for line in _unit_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not re.match(r"NoNewPrivileges\s*=\s*(?:true|yes|1)\b", stripped, re.IGNORECASE), (
            "NoNewPrivileges must not be enabled: it blocks the sudo-based updater."
        )


def test_sudoers_still_scopes_the_updater():
    # Privilege is instead constrained by the exact-command sudoers allowlist.
    sudoers = (DEPLOY / "sudoers.d" / "viejoolbel").read_text()
    assert "apply_update.sh" in sudoers
    assert "NOPASSWD" in sudoers

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


def test_unit_exposes_etc_paths_for_the_updater():
    # apply_update.sh refreshes the unit + sudoers under /etc, which ProtectSystem
    # makes read-only unless carved out with ReadWritePaths.
    text = _unit_text()
    assert "ProtectSystem=full" in text  # /etc stays protected by default
    rw = next((ln for ln in text.splitlines() if ln.strip().startswith("ReadWritePaths=")), "")
    assert "/etc/systemd/system" in rw and "/etc/sudoers.d" in rw


def test_updater_refreshes_deployment_config():
    # A changed unit/sudoers must reach devices through the normal update, not only
    # via a manual install.sh re-run.
    script = (DEPLOY / "apply_update.sh").read_text()
    assert "install_deploy_config" in script
    assert "/etc/systemd/system/viejoolbel.service" in script
    assert "/etc/sudoers.d/viejoolbel" in script
    # The sudoers file must be validated before it replaces the live one.
    assert "visudo -cf" in script

"""Onboarding access-point control from the web UI (FR-19).

Lets an admin see and change whether the ``ViejoolBel-Setup`` onboarding access
point starts automatically when no known WiFi is available, and run a bounded
"test" that brings the AP up now. The privileged work is done by a scoped sudo
helper (``deploy/ap_control.sh``); this module orchestrates and parses. On a
machine without the helper/sudo it degrades gracefully.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_TIMEOUT = 20.0

# SSID/password of the onboarding AP (kept in sync with hostapd.conf), shown in
# the UI so an admin knows what to connect to.
AP_SSID = "ViejoolBel-Setup"
AP_PASSWORD = "belsetup2025"


def available(script: Path) -> bool:
    """True when the AP can be controlled here (sudo + helper present)."""
    return shutil.which("sudo") is not None and script.exists()


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(  # noqa: S603 - argv list (no shell); args fixed
            ["sudo", str(script), *args],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("AP control %s failed: %s", args, exc)
        return None


def status(script: Path) -> dict[str, object]:
    """Return the AP service state as a dict for the UI."""
    if not available(script):
        return {"supported": False, "ssid": AP_SSID, "password": AP_PASSWORD}
    proc = _run(script, "status")
    fields: dict[str, str] = {}
    if proc is not None and proc.returncode == 0:
        for line in proc.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                fields[k.strip()] = v.strip()
    return {
        "supported": True,
        "ssid": AP_SSID,
        "password": AP_PASSWORD,
        "installed": fields.get("installed") == "yes",
        "enabled": fields.get("enabled") == "enabled",
        "active": fields.get("active") == "active",
        "hostapd_running": fields.get("hostapd") == "running",
    }


def set_enabled(script: Path, on: bool) -> tuple[bool, str]:
    """Enable or disable the auto-start of the onboarding AP."""
    if not available(script):
        return False, "AP-beheer is op dit toestel niet beschikbaar."
    proc = _run(script, "enable" if on else "disable")
    if proc is None or proc.returncode != 0:
        detail = (proc.stderr.strip() if proc else "") or "onbekende fout"
        return False, f"Wijzigen van de AP-instelling mislukt: {detail}"
    return True, ("AP wordt automatisch gestart als er geen netwerk is."
                  if on else "Automatische AP is uitgeschakeld.")


def network_online() -> bool:
    """True when the device is on a real network (has a default route).

    In onboarding-AP mode wlan0 has 192.168.4.1 but no default route, so this
    correctly reports offline then — which is what the fallback watchdog wants."""
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, no shell
            ["ip", "route"], capture_output=True, text=True, timeout=5.0
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and any(
        line.startswith("default") for line in proc.stdout.splitlines()
    )


def ap_is_active() -> bool:
    """True when the onboarding AP (hostapd) is currently running."""
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, no shell
            ["pgrep", "-x", "hostapd"], capture_output=True, text=True, timeout=5.0
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def raise_ap(script: Path, recovery_minutes: int = 0) -> tuple[bool, str]:
    """Bring the onboarding AP up now — used by the offline safety-net.

    When *recovery_minutes* > 0 the helper also schedules a guaranteed reboot after
    that many minutes so the device retries its WiFi on its own (self-heal); the
    reboot is armed before the radio is touched, so recovery happens even if the AP
    fails to come up. 0 keeps the AP up until a manual reboot (legacy behaviour).
    """
    if not available(script):
        return False, "AP-beheer is niet beschikbaar."
    args = ["raise"]
    if recovery_minutes > 0:
        args.append(str(int(recovery_minutes)))
    proc = _run(script, *args)
    if proc is None or proc.returncode != 0:
        return False, "AP openen mislukt."
    return True, "AP geopend."


def start_test(script: Path, minutes: int = 5) -> tuple[bool, str]:
    """Bring the AP up now for a test; the device reboots after *minutes*."""
    if not available(script):
        return False, "AP-beheer is op dit toestel niet beschikbaar."
    minutes = min(30, max(1, minutes))
    proc = _run(script, "start-test", str(minutes))
    if proc is None or proc.returncode != 0:
        detail = (proc.stderr.strip() if proc else "") or "onbekende fout"
        return False, f"AP-test starten mislukt: {detail}"
    return True, (
        f"AP-test gestart. Verbind je telefoon met '{AP_SSID}' "
        f"(wachtwoord {AP_PASSWORD}) en surf naar http://192.168.4.1:8080. "
        f"Het toestel herstart automatisch na {minutes} minuten."
    )

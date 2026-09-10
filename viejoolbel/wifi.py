"""WiFi selection and login from the web UI (FR-19).

Lets an admin scan for nearby WiFi networks, see which one the device is on, and
join a network by entering its password — from the normal Instellingen page as
well as from the onboarding access-point portal.

As with the updater, the privileged work (joining a network, tearing the
onboarding AP down) is done by a tightly-scoped helper script
(``deploy/set_wifi.sh``) invoked via sudo; this module orchestrates, parses and
reports. On a development machine — where ``nmcli``/``sudo``/the script are absent
— every function degrades gracefully so the UI shows a clear message instead of
raising.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Joining a network can involve a DHCP round-trip; cap it so the request cannot
# hang forever if the credentials are wrong or the AP is out of range.
_CONNECT_TIMEOUT = 45.0
_SCAN_TIMEOUT = 15.0


@dataclass(frozen=True)
class Network:
    ssid: str
    signal: int  # 0..100
    secure: bool
    active: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "ssid": self.ssid,
            "signal": self.signal,
            "secure": self.secure,
            "active": self.active,
        }


def available() -> bool:
    """True when this machine can actually manage WiFi (has NetworkManager)."""
    return shutil.which("nmcli") is not None


def _split_terse(line: str) -> list[str]:
    """Split one line of ``nmcli -t`` output on unescaped colons.

    Terse mode separates fields with ``:`` and backslash-escapes any literal
    colon inside a value (an SSID may contain one), so a naive ``split(":")``
    would mangle such SSIDs.
    """
    fields: list[str] = []
    buf: list[str] = []
    it = iter(line)
    for ch in it:
        if ch == "\\":
            buf.append(next(it, ""))
        elif ch == ":":
            fields.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    fields.append("".join(buf))
    return fields


def scan() -> list[Network]:
    """Return nearby WiFi networks, strongest first, deduplicated by SSID.

    Returns an empty list when WiFi cannot be managed here or the scan fails,
    so callers never have to handle an exception.
    """
    if not available():
        return []
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, no shell
            ["nmcli", "-t", "-f", "ACTIVE,SIGNAL,SECURITY,SSID", "device", "wifi", "list"],
            capture_output=True,
            text=True,
            timeout=_SCAN_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("WiFi scan failed: %s", exc)
        return []
    if proc.returncode != 0:
        log.warning("WiFi scan returned %s: %s", proc.returncode, proc.stderr.strip())
        return []

    best: dict[str, Network] = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        # SECURITY may itself be empty or contain spaces (e.g. "WPA2 802.1X"); it
        # never contains a colon, so a 4-field split from the left is safe.
        active_s, signal_s, security, ssid = (_split_terse(line) + ["", "", "", ""])[:4]
        ssid = ssid.strip()
        if not ssid:  # hidden network — nothing to show or click
            continue
        try:
            signal = int(signal_s or "0")
        except ValueError:
            signal = 0
        secure = security.strip() not in ("", "--")
        active = active_s.strip().lower() in ("yes", "*")
        # Merge multiple sightings of the same SSID: keep the strongest signal,
        # and treat it as active/secure if ANY sighting says so (otherwise a
        # stronger non-active row would hide that we are connected to it).
        prev = best.get(ssid)
        if prev is None:
            best[ssid] = Network(ssid=ssid, signal=signal, secure=secure, active=active)
        else:
            best[ssid] = Network(
                ssid=ssid,
                signal=max(prev.signal, signal),
                secure=prev.secure or secure,
                active=prev.active or active,
            )
    return sorted(best.values(), key=lambda n: (not n.active, -n.signal, n.ssid.lower()))


def current_ssid() -> str | None:
    """SSID the device is currently associated with, or None if not on WiFi."""
    for net in scan():
        if net.active:
            return net.ssid
    return None


def connect(ssid: str, password: str, script: Path) -> tuple[bool, str]:
    """Join *ssid* using the privileged helper and return ``(ok, message)``.

    Fails gracefully (never raises) when run off a real device. Note that on a
    successful switch the device moves to the new network, so the browser making
    this request may lose contact before the response arrives — the UI warns
    about that.
    """
    ssid = ssid.strip()
    if not ssid:
        return False, "Geef een netwerknaam (SSID) op."
    if shutil.which("sudo") is None:
        return False, "sudo niet beschikbaar (alleen op het geïnstalleerde toestel)."
    if not script.exists():
        return False, f"WiFi-script niet gevonden op {script} (alleen op het toestel)."
    try:
        proc = subprocess.run(  # noqa: S603 - argv list (no shell); args validated
            ["sudo", str(script), ssid, password],
            capture_output=True,
            text=True,
            timeout=_CONNECT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        # A timeout usually means it IS switching networks (and took our route
        # with it), so report it as an in-progress switch rather than a failure.
        return (
            True,
            f"Verbinden met '{ssid}' gestart. Deze pagina is straks bereikbaar "
            "op het nieuwe netwerk.",
        )
    except OSError as exc:
        return False, f"Kon WiFi-verbinding niet starten: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip() or f"foutcode {proc.returncode}"
        return False, f"Verbinden met '{ssid}' mislukt: {detail}"
    return True, f"Verbonden met '{ssid}'. Het toestel is bereikbaar op viejoolbel.local."

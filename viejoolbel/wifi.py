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
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# Joining a network can involve a DHCP round-trip; cap it so the request cannot
# hang forever if the credentials are wrong or the AP is out of range.
_CONNECT_TIMEOUT = 45.0
# Cap for the individual nmcli scan/list calls.
_SCAN_TIMEOUT = 25.0
# How long to wait for a triggered rescan to populate before re-reading the list.
_RESCAN_SETTLE = 3.0

# Shown when sudo demands a password: the NOPASSWD rule for a helper is not (yet)
# on the device. This happens when a device updated to a release that added a new
# privileged helper but its sudoers rule has not been refreshed onto the system.
_SUDO_HINT = (
    "Onvoldoende rechten op het toestel (de sudo-regel ontbreekt nog). "
    "Werk het toestel bij naar de nieuwste versie, of voer op het toestel "
    "'sudo ./deploy/install.sh' opnieuw uit om de rechten te installeren."
)

# Shown when NetworkManager refuses an action because the polkit rule that grants
# the service account access is not (yet) installed on the device.
_POLKIT_HINT = (
    "Onvoldoende rechten om WiFi te beheren via NetworkManager. Werk het toestel "
    "bij naar de nieuwste versie, of voer op het toestel 'sudo ./deploy/install.sh' "
    "opnieuw uit; daarna staat de benodigde polkit-regel geïnstalleerd."
)


def _is_sudo_password_error(text: str) -> bool:
    """True when sudo failed because it wanted a password (no matching NOPASSWD
    rule) rather than because the command itself failed."""
    low = text.lower()
    return "a password is required" in low or "a terminal is required" in low


def _is_polkit_denied(text: str) -> bool:
    """True when NetworkManager refused an action for lack of authorisation
    (the polkit rule granting the service account is missing)."""
    low = text.lower()
    return (
        "not authorized" in low
        or "insufficient privileges" in low
        or "permission denied" in low
    )


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


def _trigger_rescan() -> None:
    """Ask NetworkManager to actively scan for networks (best effort).

    This is separate from listing on purpose: ``nmcli device wifi list
    --rescan yes`` is all-or-nothing — if NM refuses the rescan (it rate-limits
    how often one can run, e.g. right after connecting) the whole call fails and
    the caller is left with the stale cache, which often holds only the
    currently-connected AP. Triggering the rescan on its own and ignoring a
    "scanning not allowed" refusal lets us still read a fresh list afterwards."""
    try:
        subprocess.run(  # noqa: S603 - argv list, no shell
            ["nmcli", "device", "wifi", "rescan"],
            capture_output=True,
            text=True,
            timeout=_SCAN_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("WiFi rescan trigger failed (continuing with cache): %s", exc)


def _wifi_list() -> list[Network]:
    """Read NetworkManager's current WiFi list (no rescan) and parse it."""
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, no shell
            ["nmcli", "-t", "-f", "ACTIVE,SIGNAL,SECURITY,SSID", "device", "wifi", "list"],
            capture_output=True,
            text=True,
            timeout=_SCAN_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("WiFi list failed: %s", exc)
        return []
    if proc.returncode != 0:
        log.warning("WiFi list returned %s: %s", proc.returncode, proc.stderr.strip())
        return []
    return _parse_networks(proc.stdout)


def _parse_networks(stdout: str) -> list[Network]:
    best: dict[str, Network] = {}
    for line in stdout.splitlines():
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


def scan() -> list[Network]:
    """Return nearby WiFi networks, strongest first, deduplicated by SSID.

    Triggers a fresh scan so networks the device is not connected to also show
    up — nmcli's cached list often holds only the currently-associated AP. The
    rescan runs on its own (a refusal is ignored) and, because a scan takes a
    moment to complete, the list is read again after a short wait when the first
    read still shows one network or none.

    Returns an empty list when WiFi cannot be managed here or the scan fails,
    so callers never have to handle an exception.
    """
    if not available():
        return []
    _trigger_rescan()
    nets = _wifi_list()
    if len(nets) <= 1:
        # The scan was probably still running; give it a moment and re-read.
        time.sleep(_RESCAN_SETTLE)
        nets = _wifi_list() or nets
    return nets


def current_ssid() -> str | None:
    """SSID the device is currently associated with, or None if not on WiFi."""
    for net in scan():
        if net.active:
            return net.ssid
    return None


@dataclass(frozen=True)
class SavedNetwork:
    name: str  # NetworkManager connection id — the handle used to forget it
    ssid: str  # the WiFi SSID (for display)
    active: bool  # currently in use

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "ssid": self.ssid, "active": self.active}


def _connection_ssid(ident: str) -> str:
    """Look up the SSID stored in a saved connection profile (empty if none)."""
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, no shell
            ["nmcli", "-t", "-g", "802-11-wireless.ssid", "connection", "show", ident],
            capture_output=True,
            text=True,
            timeout=_SCAN_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def saved_networks() -> list[SavedNetwork]:
    """Return the WiFi networks stored on the device (NetworkManager profiles).

    These are the networks the device will join on its own — added here by
    connecting, or ahead of time by ``preseed_wifi.sh``. Returns an empty list
    when WiFi cannot be managed here or the query fails.
    """
    if not available():
        return []
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, no shell
            ["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show"],
            capture_output=True,
            text=True,
            timeout=_SCAN_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Listing saved networks failed: %s", exc)
        return []
    if proc.returncode != 0:
        log.warning("Listing saved networks returned %s: %s", proc.returncode, proc.stderr.strip())
        return []

    out: list[SavedNetwork] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        name, uuid, conn_type, device = (_split_terse(line) + ["", "", "", ""])[:4]
        if conn_type.strip() != "802-11-wireless":
            continue
        ssid = _connection_ssid(uuid) or name.removeprefix("viejoolbel-")
        out.append(
            SavedNetwork(
                name=name,
                ssid=ssid,
                active=device.strip() not in ("", "--"),
            )
        )
    return sorted(out, key=lambda n: (not n.active, n.ssid.lower()))


def _active_connection_names() -> set[str]:
    """Names of the currently-active NetworkManager connections."""
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, no shell
            ["nmcli", "-t", "-f", "NAME", "connection", "show", "--active"],
            capture_output=True,
            text=True,
            timeout=_SCAN_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if proc.returncode != 0:
        return set()
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def forget(name: str) -> tuple[bool, str]:
    """Delete a saved network profile by its connection *name*.

    Runs ``nmcli`` directly: the polkit rule installed with the app authorises
    the service account to modify NetworkManager connections, so no sudo helper
    is needed. Refuses to delete the connection the device is currently using —
    doing so would drop the device off the network and lose the very access
    path being used. Fails gracefully (never raises) when run off a real device.
    """
    name = name.strip()
    if not name:
        return False, "Geen netwerk opgegeven."
    if not available():
        return False, "WiFi-beheer is op dit toestel niet beschikbaar."
    if name in _active_connection_names():
        return False, (
            "Dit is het netwerk waarmee het toestel nu verbonden is. Verbind eerst "
            "met een ander netwerk voordat je dit vergeet, anders raakt het toestel "
            "offline."
        )
    try:
        proc = subprocess.run(  # noqa: S603 - argv list (no shell)
            ["nmcli", "connection", "delete", name],
            capture_output=True,
            text=True,
            timeout=_CONNECT_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Kon netwerk niet verwijderen: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip() or f"foutcode {proc.returncode}"
        if _is_polkit_denied(detail):
            return False, _POLKIT_HINT
        return False, f"Verwijderen van '{name}' mislukt: {detail}"
    return True, f"Netwerk '{name}' verwijderd."


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
        if _is_sudo_password_error(detail):
            return False, _SUDO_HINT
        return False, f"Verbinden met '{ssid}' mislukt: {detail}"
    return True, f"Verbonden met '{ssid}'. Het toestel is bereikbaar op viejoolbel.local."

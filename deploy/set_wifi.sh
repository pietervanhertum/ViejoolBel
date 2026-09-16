#!/usr/bin/env bash
#
# set_wifi.sh — join a WiFi network and tear down the onboarding AP (FR-19).
# Called (via scoped sudo) when the admin submits WiFi credentials in the web UI.
#
# Usage:  sudo set_wifi.sh "<SSID>" "<PASSWORD>"     (empty password = open network)
#
# Robust join:
#   * A stale/partial saved profile for the SSID (e.g. a netplan- or half-written
#     one missing key-mgmt) causes "802-11-wireless-security.key-mgmt: property is
#     missing" — so any existing profile for the target SSID is deleted first and a
#     fresh, complete one is created with the key management set explicitly.
#   * WPA2/WPA (wpa-psk) is tried first, then WPA3 (sae); open networks use no key.
#   * If the join fails, the previous connection is reactivated so the device never
#     strands itself off the network it is managed over.
#
set -euo pipefail
SSID="${1:?usage: set_wifi.sh SSID PASSWORD}"
PSK="${2-}"

# Stop the onboarding AP if it is running.
pkill hostapd 2>/dev/null || true
pkill dnsmasq 2>/dev/null || true

if ! command -v nmcli >/dev/null 2>&1; then
  # Fall back to wpa_supplicant on older images (no rollback available there).
  ip addr flush dev wlan0 || true
  wpa_passphrase "${SSID}" "${PSK}" >> /etc/wpa_supplicant/wpa_supplicant.conf
  systemctl restart wpa_supplicant
  dhclient wlan0 || true
  echo "[wifi] Attempted to join '${SSID}'."
  exit 0
fi

# If the onboarding AP left wlan0 unmanaged, hand it back to NetworkManager.
nmcli device set wlan0 managed yes >/dev/null 2>&1 || true

# Remember the WiFi connection currently in use, so we can roll back to it.
PREV="$(nmcli -t -f NAME,TYPE connection show --active 2>/dev/null \
        | awk -F: '$2=="802-11-wireless"{print $1; exit}')"

CON="viejoolbel-${SSID}"

# Delete every saved profile whose SSID matches the target (including a broken
# one missing key-mgmt, and our own leftover), so the join starts from a clean
# slate instead of reusing a bad profile.
while IFS=: read -r _name _type; do
  [[ "${_type}" == "802-11-wireless" ]] || continue
  s="$(nmcli -t -g 802-11-wireless.ssid connection show "${_name}" 2>/dev/null || true)"
  if [[ "${s}" == "${SSID}" || "${_name}" == "${CON}" ]]; then
    nmcli connection delete "${_name}" >/dev/null 2>&1 || true
  fi
done < <(nmcli -t -f NAME,TYPE connection show)

# Create a fresh, complete profile and bring it up. $1 = key-mgmt (wpa-psk|sae|none).
join() {
  nmcli connection delete "${CON}" >/dev/null 2>&1 || true
  if [[ "$1" == "none" ]]; then
    nmcli connection add type wifi con-name "${CON}" ifname wlan0 ssid "${SSID}" \
      connection.autoconnect yes >/dev/null 2>&1 || return 1
  else
    nmcli connection add type wifi con-name "${CON}" ifname wlan0 ssid "${SSID}" \
      wifi-sec.key-mgmt "$1" wifi-sec.psk "${PSK}" \
      connection.autoconnect yes >/dev/null 2>&1 || return 1
  fi
  local err
  if ! err="$(nmcli connection up "${CON}" 2>&1)"; then
    echo "[wifi] up (${1}) failed: ${err}" >&2
    return 1
  fi
  return 0
}

echo "[wifi] Joining '${SSID}' (previous: '${PREV:-none}')."
OK=0
if [[ -z "${PSK}" ]]; then
  join none && OK=1
else
  join wpa-psk && OK=1 || { echo "[wifi] Retrying as WPA3 (sae)..." >&2; join sae && OK=1; }
fi

if [[ "${OK}" == "1" ]]; then
  echo "[wifi] Connected to '${SSID}'."
  exit 0
fi

# The new network did not come up. Clean up the failed profile and roll back to
# the previous one if there was one, so the device stays reachable.
echo "[wifi] Could not join '${SSID}'." >&2
nmcli connection delete "${CON}" >/dev/null 2>&1 || true
if [[ -n "${PREV}" ]]; then
  echo "[wifi] Rolling back to '${PREV}'." >&2
  nmcli connection up "${PREV}" >/dev/null 2>&1 || true
fi
exit 1

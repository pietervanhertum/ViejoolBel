#!/usr/bin/env bash
#
# set_wifi.sh — join a WiFi network and tear down the onboarding AP (FR-19).
# Called (via scoped sudo) when the admin submits WiFi credentials in the web UI.
#
# Usage:  sudo set_wifi.sh "<SSID>" "<PASSWORD>"
#
# Safe switch with rollback: if the device is already on a WiFi network and the
# new one fails to come up, the previous connection is reactivated so the device
# never strands itself off the network it is managed over.
#
set -euo pipefail
SSID="${1:?usage: set_wifi.sh SSID PASSWORD}"
PSK="${2:?usage: set_wifi.sh SSID PASSWORD}"

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

# Remember the WiFi connection currently in use, so we can roll back to it.
PREV="$(nmcli -t -f NAME,TYPE connection show --active 2>/dev/null \
        | awk -F: '$2=="802-11-wireless"{print $1; exit}')"

echo "[wifi] Joining '${SSID}' (previous: '${PREV:-none}')."
if nmcli device wifi connect "${SSID}" password "${PSK}"; then
  echo "[wifi] Connected to '${SSID}'."
  exit 0
fi

# The new network did not come up. Roll back to the previous one if there was
# one, so the device stays reachable instead of being stranded.
echo "[wifi] Could not join '${SSID}'." >&2
if [[ -n "${PREV}" ]]; then
  echo "[wifi] Rolling back to '${PREV}'." >&2
  nmcli connection up "${PREV}" || true
fi
exit 1

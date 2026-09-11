#!/usr/bin/env bash
#
# preseed_wifi.sh — store a WiFi network on the device *before* it ships, so it
# joins that network automatically the moment it powers on at the school, with
# nobody having to touch the onboarding portal (FR-19, "zero-touch" install).
#
# Run this while you prepare the device at home/office — NOT at the school. The
# network does not have to be in range: NetworkManager keeps the saved profile
# and auto-connects whenever that SSID appears. Call it once per network, so you
# can preseed the school's WiFi *and* keep your own bench WiFi for testing; the
# device joins whichever is in range, preferring the higher priority.
#
# Usage:
#   sudo ./deploy/preseed_wifi.sh "<SSID>" ["<PASSWORD>"] [priority]
#
# Prefer to OMIT the password so the script prompts for it securely — then a
# password with special characters can never be mangled by the shell:
#   sudo ./deploy/preseed_wifi.sh "SchoolWiFi" "" 10   # prompts, priority 10
#   sudo ./deploy/preseed_wifi.sh "SchoolWiFi"         # prompts, priority 0
#
# If you DO pass the password inline, wrap it in SINGLE quotes. In an interactive
# bash shell a '!' inside DOUBLE quotes triggers history expansion *before* this
# script runs (bash: "!...: event not found"), and other characters ($, `) expand
# too. Single quotes disable all of that:
#   sudo ./deploy/preseed_wifi.sh "SchoolWiFi" '!SG_PersOn33L%3990?' 10
# (An inline password is also visible in `ps` and your shell history — another
# reason to prefer the prompt.)
#
# A higher priority number wins when two saved networks are both in range.
# Re-running for an SSID that already exists updates its password/priority.
#
set -euo pipefail

SSID="${1:?usage: preseed_wifi.sh SSID [PASSWORD] [priority]  (omit PASSWORD to be prompted securely)}"
PSK="${2-}"
PRIORITY="${3:-0}"

if [[ $EUID -ne 0 ]]; then
  echo "This must be run as root: sudo ./deploy/preseed_wifi.sh ..." >&2
  exit 1
fi

# Read the password interactively when it was not supplied (or given empty), so
# special characters bypass shell quoting entirely and it stays out of `ps`/history.
if [[ -z "${PSK}" ]]; then
  read -rsp "WiFi-wachtwoord voor '${SSID}': " PSK || true
  echo >&2
fi
if [[ -z "${PSK}" ]]; then
  echo "[preseed] Geen wachtwoord opgegeven; gestopt." >&2
  exit 1
fi
if (( ${#PSK} < 8 || ${#PSK} > 63 )); then
  echo "[preseed] Let op: een WPA-wachtwoord is 8–63 tekens (nu ${#PSK}). Ga toch door…" >&2
fi

# Prefer NetworkManager (default on Raspberry Pi OS Bookworm); it can hold many
# saved networks and auto-connects to whichever is in range.
if command -v nmcli >/dev/null 2>&1; then
  CON="viejoolbel-${SSID}"
  # Replace an existing profile for the same SSID so re-runs stay idempotent.
  if nmcli -g NAME connection show 2>/dev/null | grep -qxF "${CON}"; then
    echo "[preseed] Updating existing profile '${CON}'."
    nmcli connection delete "${CON}" >/dev/null 2>&1 || true
  fi
  nmcli connection add type wifi con-name "${CON}" ifname wlan0 ssid "${SSID}" \
    -- \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "${PSK}" \
    connection.autoconnect yes \
    connection.autoconnect-priority "${PRIORITY}"
  echo "[preseed] Saved '${SSID}' (priority ${PRIORITY}). The device will join it"
  echo "          automatically as soon as it is in range — no portal needed."
else
  # Fall back to wpa_supplicant on older images.
  CONF="/etc/wpa_supplicant/wpa_supplicant.conf"
  if grep -qF "ssid=\"${SSID}\"" "${CONF}" 2>/dev/null; then
    echo "[preseed] '${SSID}' already present in ${CONF}; leaving it as-is."
  else
    {
      echo ""
      echo "network={"
      wpa_passphrase "${SSID}" "${PSK}" | grep -vE '^\s*#' | sed '1d;$d'
      echo "    priority=${PRIORITY}"
      echo "}"
    } >> "${CONF}"
    echo "[preseed] Appended '${SSID}' (priority ${PRIORITY}) to ${CONF}."
  fi
fi

echo "[preseed] Currently saved WiFi networks:"
if command -v nmcli >/dev/null 2>&1; then
  nmcli -g NAME,TYPE connection show | awk -F: '$2=="802-11-wireless"{print "  - "$1}'
else
  grep -oE 'ssid="[^"]+"' "${CONF}" 2>/dev/null | sed 's/ssid=/  - /; s/"//g' || true
fi

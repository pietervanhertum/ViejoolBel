#!/usr/bin/env bash
#
# set_wifi.sh — join a WiFi network and tear down the onboarding AP (FR-19).
# Called (via scoped sudo) when the admin submits WiFi credentials in the web UI.
#
# Usage:  sudo set_wifi.sh "<SSID>" "<PASSWORD>"
#
set -euo pipefail
SSID="${1:?usage: set_wifi.sh SSID PASSWORD}"
PSK="${2:?usage: set_wifi.sh SSID PASSWORD}"

# Stop the onboarding AP if it is running.
pkill hostapd 2>/dev/null || true
pkill dnsmasq 2>/dev/null || true
ip addr flush dev wlan0 || true

# Prefer NetworkManager (default on Raspberry Pi OS Bookworm); fall back to
# wpa_supplicant on older images.
if command -v nmcli >/dev/null 2>&1; then
  nmcli device wifi connect "${SSID}" password "${PSK}"
else
  wpa_passphrase "${SSID}" "${PSK}" >> /etc/wpa_supplicant/wpa_supplicant.conf
  systemctl restart wpa_supplicant
  dhclient wlan0 || true
fi
echo "[wifi] Attempted to join '${SSID}'."

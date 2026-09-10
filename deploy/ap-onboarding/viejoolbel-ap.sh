#!/usr/bin/env bash
#
# viejoolbel-ap.sh — bring up the onboarding access point when, and only when, the
# device cannot join a known WiFi network (FR-19). Intended to run at boot via a
# small systemd unit (viejoolbel-ap.service, see docs/onboarding.md).
#
# It waits for a normal WiFi association; if none appears within the timeout it
# configures wlan0 as an AP (192.168.4.1) and starts hostapd + dnsmasq so an admin
# can connect to "ViejoolBel-Setup" and enter the school's WiFi credentials in the
# web UI. As soon as credentials are saved, set_wifi.sh tears the AP down again.
#
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ARG="${1:-45}"

has_link() { ip route | grep -q '^default'; }

# "now" forces the AP up immediately (used by the "Test AP" button); a number is
# how many seconds to wait for a normal WiFi connection before falling back to AP.
if [[ "${ARG}" == "now" ]]; then
  echo "[ap] Forcing onboarding access point up now."
else
  echo "[ap] Waiting up to ${ARG}s for an existing WiFi connection..."
  for _ in $(seq "${ARG}"); do
    if has_link; then
      echo "[ap] Network is up; onboarding AP not needed."
      exit 0
    fi
    sleep 1
  done
  echo "[ap] No network; starting onboarding access point."
fi

# Release wlan0 from NetworkManager so it does not fight the AP (runtime-only, so
# a reboot restores normal management). Fall back to stopping wpa_supplicant on
# non-NM images.
if command -v nmcli >/dev/null 2>&1; then
  nmcli device disconnect wlan0 >/dev/null 2>&1 || true
  nmcli device set wlan0 managed no >/dev/null 2>&1 || true
fi
systemctl stop wpa_supplicant 2>/dev/null || true
ip link set wlan0 down
ip addr flush dev wlan0
ip addr add 192.168.4.1/24 dev wlan0
ip link set wlan0 up

hostapd -B "${HERE}/hostapd.conf"
dnsmasq -C "${HERE}/dnsmasq.conf"
echo "[ap] AP 'ViejoolBel-Setup' is up at http://192.168.4.1:8080"

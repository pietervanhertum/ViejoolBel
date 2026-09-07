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
TIMEOUT="${1:-45}"

has_link() { ip route | grep -q '^default'; }

echo "[ap] Waiting up to ${TIMEOUT}s for an existing WiFi connection..."
for _ in $(seq "${TIMEOUT}"); do
  if has_link; then
    echo "[ap] Network is up; onboarding AP not needed."
    exit 0
  fi
  sleep 1
done

echo "[ap] No network; starting onboarding access point."
systemctl stop wpa_supplicant 2>/dev/null || true
ip link set wlan0 down
ip addr flush dev wlan0
ip addr add 192.168.4.1/24 dev wlan0
ip link set wlan0 up

hostapd -B "${HERE}/hostapd.conf"
dnsmasq -C "${HERE}/dnsmasq.conf"
echo "[ap] AP 'ViejoolBel-Setup' is up at http://192.168.4.1:8080"

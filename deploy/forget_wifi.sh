#!/usr/bin/env bash
#
# forget_wifi.sh — delete a saved WiFi network profile (FR-19). Called (via scoped
# sudo) when the admin removes a saved network in the web UI. Deleting a
# NetworkManager connection needs privilege, so this runs as root; it is limited
# to exactly this command by the sudoers rule.
#
# Usage:  sudo forget_wifi.sh "<connection-name-or-uuid>"
#
set -euo pipefail
ID="${1:?usage: forget_wifi.sh <connection-name-or-uuid>}"

if command -v nmcli >/dev/null 2>&1; then
  nmcli connection delete "${ID}"
else
  echo "[wifi] nmcli not available; cannot forget '${ID}'." >&2
  exit 1
fi
echo "[wifi] Removed saved network '${ID}'."

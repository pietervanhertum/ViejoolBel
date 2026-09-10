#!/usr/bin/env bash
#
# ap_control.sh — manage the onboarding access point from the web UI (FR-19).
# Called via scoped sudo. Subcommands:
#
#   status                 print installed/enabled/active/hostapd state (key=value)
#   enable                 install (if needed) and enable viejoolbel-ap.service
#   disable                disable viejoolbel-ap.service
#   start-test [minutes]   bring the AP up NOW for a test, and GUARANTEE recovery
#                          by scheduling an unconditional reboot after N minutes
#                          (default 5) — so a failed AP can never strand the device
#
set -euo pipefail

CUR="/opt/viejoolbel/current"
UNIT="viejoolbel-ap.service"
UNIT_SRC="${CUR}/deploy/ap-onboarding/${UNIT}"
AP_SH="${CUR}/deploy/ap-onboarding/viejoolbel-ap.sh"

install_unit() {
  [[ -f "${UNIT_SRC}" ]] || { echo "AP unit not found in release" >&2; return 1; }
  install -m 644 "${UNIT_SRC}" "/etc/systemd/system/${UNIT}"
  # The AP script runs its own hostapd/dnsmasq, so mask the packaged services.
  systemctl disable --now hostapd.service dnsmasq.service >/dev/null 2>&1 || true
  systemctl mask hostapd.service dnsmasq.service >/dev/null 2>&1 || true
  systemctl daemon-reload
}

cmd="${1:?usage: ap_control.sh status|enable|disable|start-test [minutes]}"
case "${cmd}" in
  status)
    installed=no; [[ -f "/etc/systemd/system/${UNIT}" ]] && installed=yes
    echo "installed=${installed}"
    echo "enabled=$(systemctl is-enabled "${UNIT}" 2>/dev/null || echo no)"
    echo "active=$(systemctl is-active "${UNIT}" 2>/dev/null || echo inactive)"
    echo "hostapd=$(pgrep -x hostapd >/dev/null 2>&1 && echo running || echo stopped)"
    ;;
  enable)
    install_unit
    systemctl enable "${UNIT}"
    echo "enabled"
    ;;
  disable)
    systemctl disable "${UNIT}" >/dev/null 2>&1 || true
    echo "disabled"
    ;;
  raise)
    # Bring the AP up now with no reboot (used by the offline safety-net).
    setsid "${AP_SH}" now >/dev/null 2>&1 &
    echo "ap-raised"
    ;;
  start-test)
    mins="${2:-5}"
    [[ "${mins}" =~ ^[0-9]+$ ]] && ((mins >= 1 && mins <= 30)) || mins=5
    # Schedule the guaranteed reboot FIRST, before touching the radio, so the
    # device always comes back even if the AP never comes up.
    if command -v systemd-run >/dev/null 2>&1 \
       && systemd-run --on-active="${mins}min" --unit=viejoolbel-ap-test-reboot \
            /sbin/reboot >/dev/null 2>&1; then
      :
    else
      setsid bash -c "sleep $((mins * 60)); /sbin/reboot" >/dev/null 2>&1 &
    fi
    # Force the AP up now (detached; it reconfigures wlan0, dropping WiFi).
    setsid "${AP_SH}" now >/dev/null 2>&1 &
    echo "ap-test-started reboot-in=${mins}min"
    ;;
  *)
    echo "unknown command: ${cmd}" >&2
    exit 2
    ;;
esac

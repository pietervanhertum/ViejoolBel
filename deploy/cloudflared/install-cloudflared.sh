#!/usr/bin/env bash
#
# Install cloudflared (the Cloudflare Tunnel connector) on Raspberry Pi OS /
# Debian, from Cloudflare's official apt repository so it receives security
# updates like any other package. Idempotent: safe to re-run.
#
# This is the tool that runs the `cloudflared tunnel ...` commands in
# docs/public-access.md, which expose the ViejoolBel web UI at a public HTTPS
# URL (e.g. https://bel.ottorosie.com) behind Cloudflare Access — WITHOUT
# port-forwarding or any change to the school's network (FR-21), exactly like
# Tailscale but with a custom domain and a real login in front.
#
# Usage:
#   sudo ./deploy/cloudflared/install-cloudflared.sh
#       -> installs the package only, then prints the next steps.
#
#   sudo ./deploy/cloudflared/install-cloudflared.sh --token <TUNNEL_TOKEN>
#       -> also installs + starts the connector as a systemd service using a
#          token from the Cloudflare Zero Trust dashboard (the "remotely-managed
#          tunnel" path, where ingress and Access are configured in the
#          dashboard). This is the simplest option for most people.
#
# For the locally-managed path (config.example.yml + viejoolbel-tunnel.service),
# leave off --token and follow docs/public-access.md.
#
set -euo pipefail

TOKEN=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --token)
      TOKEN="${2:-}"
      shift 2
      ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "This installer must be run as root: sudo $0" >&2
  exit 1
fi

echo "==> Installing cloudflared from Cloudflare's apt repository"
install -d -m 0755 /usr/share/keyrings
# Cloudflare's package signing key. curl -f so a proxy/error page never gets
# written as if it were a key.
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null

# `lsb_release -cs` is the Debian/RPi OS codename (bookworm, bullseye, ...).
CODENAME="$(. /etc/os-release 2>/dev/null && echo "${VERSION_CODENAME:-}")"
if [[ -z "${CODENAME}" ]] && command -v lsb_release >/dev/null 2>&1; then
  CODENAME="$(lsb_release -cs)"
fi
: "${CODENAME:=bookworm}"

echo \
  "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared ${CODENAME} main" \
  > /etc/apt/sources.list.d/cloudflared.list

apt-get update
apt-get install -y cloudflared

echo "==> Installed: $(cloudflared --version 2>/dev/null || echo 'cloudflared')"

if [[ -n "${TOKEN}" ]]; then
  echo "==> Installing the connector as a systemd service (remotely-managed tunnel)"
  # Creates and enables the cloudflared systemd service from the dashboard token.
  # Ingress + Cloudflare Access are managed in the Zero Trust dashboard.
  cloudflared service install "${TOKEN}"
  echo ""
  echo "==> Done. The tunnel is running as a service."
  echo "    Status: systemctl status cloudflared"
  echo "    Logs:   journalctl -u cloudflared -f"
  echo "    Make sure the tunnel's public hostname routes to http://localhost:8080"
  echo "    and that a Cloudflare Access policy protects it (docs/public-access.md)."
else
  cat <<'EOF'

==> cloudflared is installed. Next steps (see docs/public-access.md):

  Simplest (remotely-managed, recommended):
    1. In the Cloudflare Zero Trust dashboard, create a tunnel and copy its token.
    2. Re-run this script with:  sudo ./install-cloudflared.sh --token <TOKEN>
    3. In the dashboard, add a public hostname (e.g. bel.ottorosie.com) that
       points to http://localhost:8080, and add an Access application + policy.

  Locally-managed (gitops) alternative:
    1. cloudflared tunnel login
    2. cloudflared tunnel create viejoolbel
    3. cloudflared tunnel route dns viejoolbel bel.ottorosie.com
    4. Copy deploy/cloudflared/config.example.yml to /etc/cloudflared/config.yml
       and fill in the tunnel id + credentials path.
    5. Install deploy/cloudflared/viejoolbel-tunnel.service and enable it.

  Then enable the app-side Access gate (defence in depth): set
  VIEJOOLBEL_CF_ACCESS_TEAM_DOMAIN and VIEJOOLBEL_CF_ACCESS_AUD in
  /etc/viejoolbel/viejoolbel.env and reinstall with the [access] extra.
EOF
fi

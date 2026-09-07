#!/usr/bin/env bash
#
# ViejoolBel installer for Raspberry Pi OS (Bookworm/Bullseye) and Debian.
# Idempotent: safe to re-run. Creates a dedicated service user, a Python venv,
# a systemd unit, and installs the release under /opt/viejoolbel/releases with a
# "current" symlink that the updater flips atomically.
#
# Usage:  sudo ./deploy/install.sh
#
set -euo pipefail

APP_USER="viejoolbel"
OPT_DIR="/opt/viejoolbel"
RELEASES_DIR="${OPT_DIR}/releases"
DATA_DIR="/var/lib/viejoolbel"
ETC_DIR="/etc/viejoolbel"
VERSION="$(git -C "$(dirname "$0")/.." describe --tags --always 2>/dev/null || date +%Y%m%d%H%M%S)"
RELEASE_DIR="${RELEASES_DIR}/${VERSION}"

if [[ $EUID -ne 0 ]]; then
  echo "This installer must be run as root: sudo ./deploy/install.sh" >&2
  exit 1
fi

SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "==> Installing ViejoolBel ${VERSION} from ${SRC_DIR}"

echo "==> Installing OS dependencies"
apt-get update
apt-get install -y python3 python3-venv python3-pip ffmpeg alsa-utils git avahi-daemon

echo "==> Creating service user '${APP_USER}'"
if ! id -u "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --shell /usr/sbin/nologin "${APP_USER}"
fi
# GPIO/audio access on the Pi
usermod -aG gpio,audio "${APP_USER}" 2>/dev/null || true

echo "==> Laying out ${RELEASE_DIR}"
mkdir -p "${RELEASE_DIR}" "${DATA_DIR}" "${ETC_DIR}"
cp -a "${SRC_DIR}/." "${RELEASE_DIR}/"

echo "==> Creating virtualenv and installing the app"
python3 -m venv "${RELEASE_DIR}/.venv"
"${RELEASE_DIR}/.venv/bin/pip" install --upgrade pip wheel
# Install with the Pi extra so RPi.GPIO is pulled in on ARM.
"${RELEASE_DIR}/.venv/bin/pip" install "${RELEASE_DIR}[pi]" || "${RELEASE_DIR}/.venv/bin/pip" install "${RELEASE_DIR}"

echo "==> Pointing 'current' symlink at this release"
ln -sfn "${RELEASE_DIR}" "${OPT_DIR}/current"

echo "==> Generating environment file (secret key) if missing"
if [[ ! -f "${ETC_DIR}/viejoolbel.env" ]]; then
  SECRET="$(head -c 32 /dev/urandom | base64)"
  cat > "${ETC_DIR}/viejoolbel.env" <<EOF
VIEJOOLBEL_SECRET_KEY=${SECRET}
VIEJOOLBEL_TIMEZONE=Europe/Brussels
VIEJOOLBEL_PORT=8080
EOF
  chmod 640 "${ETC_DIR}/viejoolbel.env"
fi

echo "==> Setting ownership"
chown -R "${APP_USER}:${APP_USER}" "${OPT_DIR}" "${DATA_DIR}" "${ETC_DIR}"

echo "==> Installing sudoers rule for privileged actions"
install -m 440 "${SRC_DIR}/deploy/sudoers.d/viejoolbel" /etc/sudoers.d/viejoolbel

echo "==> Installing systemd unit"
install -m 644 "${SRC_DIR}/deploy/systemd/viejoolbel.service" /etc/systemd/system/viejoolbel.service
systemctl daemon-reload
systemctl enable viejoolbel.service
systemctl restart viejoolbel.service

echo ""
echo "==> Done. ViejoolBel is running."
echo "    Web UI:   http://$(hostname).local:8080   (login: admin / changeme)"
echo "    Logs:     journalctl -u viejoolbel -f"
echo "    Remote:   see docs/remote-support.md to enable Tailscale"
echo "    Offline:  see docs/onboarding.md for the WiFi access-point setup"

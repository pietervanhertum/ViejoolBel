#!/usr/bin/env bash
#
# apply_update.sh — atomic, self-rolling-back updater (FR-22, NFR-3).
#
# Fetches a release tag into a fresh directory, builds its venv, health-checks it,
# then flips the "current" symlink and restarts the service. If the new version
# fails its health check, the previous release is restored. The running install is
# never mutated in place, so a bad update can never brick the device.
#
# Usage:  sudo apply_update.sh <git-tag>
#
set -euo pipefail

TAG="${1:?usage: apply_update.sh <git-tag>}"
OPT_DIR="/opt/viejoolbel"
RELEASES_DIR="${OPT_DIR}/releases"
REPO="${VIEJOOLBEL_UPDATE_REPO:-https://github.com/pietervanhertum/ViejoolBel}"
NEW_DIR="${RELEASES_DIR}/${TAG}"
PREV_TARGET="$(readlink -f "${OPT_DIR}/current" || true)"

log() { echo "[apply_update] $*"; }

health_check() {
  # Import the app and boot the FastAPI app against mock hardware; exit non-zero
  # on any failure. Fast and hardware-free.
  VIEJOOLBEL_HARDWARE=mock VIEJOOLBEL_DATA_DIR="$(mktemp -d)" \
    "$1/.venv/bin/python" -c "from viejoolbel.service import Service; from viejoolbel.config import Settings; s=Service(Settings(hardware='mock')); s.build_app(); s.stop(); print('ok')"
}

log "Fetching ${TAG} from ${REPO}"
rm -rf "${NEW_DIR}"
git clone --depth 1 --branch "${TAG}" "${REPO}" "${NEW_DIR}"

log "Building virtualenv"
python3 -m venv "${NEW_DIR}/.venv"
"${NEW_DIR}/.venv/bin/pip" install --upgrade pip wheel >/dev/null
"${NEW_DIR}/.venv/bin/pip" install "${NEW_DIR}[pi]" >/dev/null 2>&1 || "${NEW_DIR}/.venv/bin/pip" install "${NEW_DIR}" >/dev/null

log "Running health check on the new release"
if ! health_check "${NEW_DIR}"; then
  log "Health check FAILED; leaving current release in place."
  rm -rf "${NEW_DIR}"
  exit 1
fi

log "Flipping 'current' symlink to ${NEW_DIR}"
ln -sfn "${NEW_DIR}" "${OPT_DIR}/current"
chown -R viejoolbel:viejoolbel "${NEW_DIR}"

log "Restarting service"
systemctl restart viejoolbel.service
sleep 3

if systemctl is-active --quiet viejoolbel.service; then
  log "Update to ${TAG} succeeded."
  exit 0
fi

log "Service failed to come up; rolling back."
if [[ -n "${PREV_TARGET}" ]]; then
  ln -sfn "${PREV_TARGET}" "${OPT_DIR}/current"
  systemctl restart viejoolbel.service
  log "Rolled back to ${PREV_TARGET}."
fi
exit 1

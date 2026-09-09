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
set -Eeuo pipefail

TAG="${1:?usage: apply_update.sh <git-tag>}"
OPT_DIR="/opt/viejoolbel"
RELEASES_DIR="${OPT_DIR}/releases"
ENV_FILE="/etc/viejoolbel/viejoolbel.env"
HERE="$(cd "$(dirname "$0")" && pwd)"

# Read VIEJOOLBEL_UPDATE_REPO and (for a private repo) VIEJOOLBEL_GITHUB_TOKEN
# from the env file *safely* — never source it (see lib_env.sh).
# shellcheck source=lib_env.sh
. "${HERE}/lib_env.sh"
VIEJOOLBEL_GITHUB_TOKEN="$(viejoolbel_read_env "${ENV_FILE}" VIEJOOLBEL_GITHUB_TOKEN)"

REPO="$(viejoolbel_read_env "${ENV_FILE}" VIEJOOLBEL_UPDATE_REPO)"
REPO="${REPO:-https://github.com/pietervanhertum/ViejoolBel}"
NEW_DIR="${RELEASES_DIR}/${TAG}"
PREV_TARGET="$(readlink -f "${OPT_DIR}/current" || true)"

# Log to stdout (captured to the update log by the caller) AND to journald, so a
# failure is visible both in the UI's "updatelog" and via `journalctl`.
log() { echo "[apply_update] $*"; logger -t viejoolbel-update -- "$*" 2>/dev/null || true; }

# On any unexpected error, say where it failed instead of dying silently.
trap 'log "FAILED at line ${LINENO} (exit $?). Current release left in place."' ERR

# Build the clone URL, injecting a token for a private repo when one is set.
clone_url() {
  if [[ -n "${VIEJOOLBEL_GITHUB_TOKEN:-}" && "${REPO}" == https://github.com/* ]]; then
    echo "https://x-access-token:${VIEJOOLBEL_GITHUB_TOKEN}@github.com/${REPO#https://github.com/}"
  else
    echo "${REPO}"
  fi
}

health_check() {
  # Import the app and boot the FastAPI app against mock hardware; exit non-zero
  # on any failure. Fast and hardware-free.
  VIEJOOLBEL_HARDWARE=mock VIEJOOLBEL_DATA_DIR="$(mktemp -d)" \
    "$1/.venv/bin/python" -c "from viejoolbel.service import Service; from viejoolbel.config import Settings; s=Service(Settings(hardware='mock')); s.build_app(); s.stop(); print('ok')"
}

# Re-install the systemd unit and sudoers rule from a release directory, so that
# deployment-config fixes (e.g. a changed unit) reach the device through the
# normal update instead of needing a manual install.sh re-run. Best-effort: a
# failure here is logged, never fatal, so an update is never blocked by it.
#   * The sudoers file is syntax-checked with visudo BEFORE it replaces the live
#     one — a malformed rule could otherwise lock out sudo entirely.
#   * Writes land in /etc, which the unit exposes to this root helper via
#     ReadWritePaths (ProtectSystem=full otherwise makes /etc read-only for the
#     service and its children).
install_deploy_config() {
  local src="$1"
  local unit_src="${src}/deploy/systemd/viejoolbel.service"
  local sudo_src="${src}/deploy/sudoers.d/viejoolbel"

  if [[ -f "${unit_src}" ]]; then
    if install -m 644 "${unit_src}" /etc/systemd/system/viejoolbel.service 2>/dev/null; then
      systemctl daemon-reload || true
      log "Refreshed systemd unit from ${src}."
    else
      log "WARN: could not write the systemd unit (left as-is)."
    fi
  fi

  if [[ -f "${sudo_src}" ]]; then
    if ! visudo -cf "${sudo_src}" >/dev/null 2>&1; then
      log "WARN: new sudoers rule failed validation; keeping the current one."
    elif install -m 440 "${sudo_src}" /etc/sudoers.d/viejoolbel 2>/dev/null; then
      log "Refreshed sudoers rule from ${src}."
    else
      log "WARN: could not write the sudoers rule (left as-is)."
    fi
  fi
}

log "Fetching ${TAG} from ${REPO}"
rm -rf "${NEW_DIR}"
git clone --depth 1 --branch "${TAG}" "$(clone_url)" "${NEW_DIR}"

log "Building virtualenv (this needs internet for pip)"
python3 -m venv "${NEW_DIR}/.venv"
"${NEW_DIR}/.venv/bin/pip" install --upgrade pip wheel
# Try the Pi extra (RPi.GPIO) first; fall back to the base install off-device.
"${NEW_DIR}/.venv/bin/pip" install "${NEW_DIR}[pi]" \
  || "${NEW_DIR}/.venv/bin/pip" install "${NEW_DIR}"

log "Running health check on the new release"
if ! health_check "${NEW_DIR}"; then
  log "Health check FAILED; leaving current release in place."
  rm -rf "${NEW_DIR}"
  exit 1
fi

log "Flipping 'current' symlink to ${NEW_DIR}"
ln -sfn "${NEW_DIR}" "${OPT_DIR}/current"
chown -R viejoolbel:viejoolbel "${NEW_DIR}"

# Record the installed tag so the app reports the deployed version (and the update
# check compares tag-to-tag), even when the code's __version__ lags the tag.
DATA_DIR="$(viejoolbel_read_env "${ENV_FILE}" VIEJOOLBEL_DATA_DIR)"
DATA_DIR="${DATA_DIR:-/var/lib/viejoolbel}"
mkdir -p "${DATA_DIR}"
printf '%s' "${TAG}" > "${DATA_DIR}/installed_version"
chown viejoolbel:viejoolbel "${DATA_DIR}/installed_version" 2>/dev/null || true

log "Refreshing deployment config (systemd unit + sudoers) from ${TAG}"
install_deploy_config "${NEW_DIR}"

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
  # Restore the previous release's unit/sudoers too, in case a changed unit is
  # what kept the new version from starting.
  install_deploy_config "${PREV_TARGET}"
  systemctl restart viejoolbel.service
  log "Rolled back to ${PREV_TARGET}."
fi
exit 1

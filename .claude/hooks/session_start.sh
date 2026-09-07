#!/usr/bin/env bash
# SessionStart hook: prepare a dev environment so tests and linters work in
# Claude Code (web) sessions. Idempotent and fast on warm caches.
set -euo pipefail
cd "$(dirname "$0")/../.."

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
pip install -q --upgrade pip >/dev/null 2>&1 || true
pip install -q -e ".[dev]" >/dev/null 2>&1 || true

echo "ViejoolBel dev env ready. Run: pytest -q | ruff check . | mypy viejoolbel"

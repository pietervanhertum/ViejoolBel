"""The updater must read the env file *safely*, never execute it.

Regression: apply_update.sh sourced /etc/viejoolbel/viejoolbel.env with bash, so a
token line that wasn't bash-sourceable (e.g. a space after '=') made bash try to
run the token as a command ("command not found") and aborted the whole update.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

DEPLOY = pathlib.Path(__file__).resolve().parent.parent / "deploy"
LIB = DEPLOY / "lib_env.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


def _read(env_file: pathlib.Path, key: str) -> str:
    script = f'set -Eeuo pipefail; . "{LIB}"; viejoolbel_read_env "{env_file}" "{key}"'
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    # No part of the file should ever be executed.
    assert "command not found" not in proc.stderr
    return proc.stdout


def test_reads_plain_value(tmp_path):
    env = tmp_path / "e.env"
    env.write_text("VIEJOOLBEL_GITHUB_TOKEN=github_pat_ABC123\n")
    assert _read(env, "VIEJOOLBEL_GITHUB_TOKEN") == "github_pat_ABC123"


def test_tolerates_space_after_equals(tmp_path):
    # This is the exact shape that broke the real device.
    env = tmp_path / "e.env"
    env.write_text("VIEJOOLBEL_GITHUB_TOKEN= github_pat_ABC123\n")
    assert _read(env, "VIEJOOLBEL_GITHUB_TOKEN") == "github_pat_ABC123"


def test_strips_quotes(tmp_path):
    env = tmp_path / "e.env"
    env.write_text('VIEJOOLBEL_UPDATE_REPO="https://github.com/x/y"\n')
    assert _read(env, "VIEJOOLBEL_UPDATE_REPO") == "https://github.com/x/y"


def test_missing_key_is_empty(tmp_path):
    env = tmp_path / "e.env"
    env.write_text("OTHER=1\n")
    assert _read(env, "VIEJOOLBEL_GITHUB_TOKEN") == ""


def test_last_assignment_wins(tmp_path):
    env = tmp_path / "e.env"
    env.write_text("VIEJOOLBEL_GITHUB_TOKEN=old\nVIEJOOLBEL_GITHUB_TOKEN=new\n")
    assert _read(env, "VIEJOOLBEL_GITHUB_TOKEN") == "new"


def test_apply_update_does_not_source_env_file():
    # Guard the specific regression: the script must not `. "${ENV_FILE}"`.
    text = (DEPLOY / "apply_update.sh").read_text()
    assert '. "${ENV_FILE}"' not in text
    assert "viejoolbel_read_env" in text

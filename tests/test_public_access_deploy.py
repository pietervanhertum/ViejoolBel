"""Guards for the Cloudflare Tunnel deploy files (docs/public-access.md)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CF = ROOT / "deploy" / "cloudflared"


def test_install_helper_is_executable_and_uses_the_official_repo():
    script = CF / "install-cloudflared.sh"
    assert os.access(script, os.X_OK), "install-cloudflared.sh must be executable"
    text = script.read_text()
    assert "pkg.cloudflare.com/cloudflared" in text  # official apt repo
    assert "apt-get install -y cloudflared" in text
    assert "cloudflared service install" in text  # token path


def test_tunnel_config_points_at_localhost():
    # The app's Access gate keys on loopback, so the tunnel MUST target localhost.
    text = (CF / "config.example.yml").read_text()
    assert "service: http://localhost:8080" in text
    assert "http_status:404" in text  # catch-all so nothing else reaches the app
    assert "no-autoupdate: true" in text


def test_tunnel_unit_is_self_healing():
    text = (CF / "viejoolbel-tunnel.service").read_text()
    assert "Restart=always" in text
    assert "tunnel run" in text
    assert "--config /etc/cloudflared/config.yml" in text


def test_installer_points_at_the_public_access_doc():
    assert "docs/public-access.md" in (ROOT / "deploy" / "install.sh").read_text()


def test_public_access_doc_exists():
    assert (ROOT / "docs" / "public-access.md").is_file()

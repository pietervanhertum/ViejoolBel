"""Tests for the Cloudflare Access gate (docs/public-access.md).

The pure request-classification helpers run everywhere. The JWT-verification and
end-to-end middleware tests need PyJWT + cryptography (the ``[access]`` extra) and
are skipped when it is not installed.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from viejoolbel import db as db_module
from viejoolbel.config import Settings
from viejoolbel.service import Service
from viejoolbel.web import cf_access

TEAM = "ottorosie.cloudflareaccess.com"
AUD = "test-aud-tag"
KID = "testkid"


# --------------------------------------------------------------------------
# Pure helpers (no crypto needed)
# --------------------------------------------------------------------------
def test_loopback_is_treated_as_tunnel():
    assert cf_access.looks_like_tunnel_request("127.0.0.1", Headers({}))
    assert cf_access.looks_like_tunnel_request("::1", Headers({}))


def test_lan_client_is_not_a_tunnel_request():
    assert not cf_access.looks_like_tunnel_request("192.168.1.50", Headers({}))
    assert not cf_access.looks_like_tunnel_request(None, Headers({}))


def test_cloudflare_headers_force_tunnel_classification():
    # A LAN client forging edge headers only opts into stricter checking; it can
    # never use them to bypass the gate.
    assert cf_access.looks_like_tunnel_request("192.168.1.50", Headers({"cf-ray": "abc"}))
    assert cf_access.looks_like_tunnel_request(
        "10.0.0.9", Headers({"cf-access-jwt-assertion": "x"})
    )


def test_extract_token_prefers_header_then_cookie():
    assert cf_access.extract_token(Headers({"cf-access-jwt-assertion": "H"}), {}) == "H"
    assert cf_access.extract_token(Headers({}), {"CF_Authorization": "C"}) == "C"
    assert cf_access.extract_token(Headers({}), {}) is None


# --------------------------------------------------------------------------
# JWT verification + middleware (needs the [access] extra)
# --------------------------------------------------------------------------
jwt = pytest.importorskip("jwt")
pytest.importorskip("cryptography")

from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def jwks(rsa_key) -> dict:
    """A JWKS document, as Cloudflare's /cdn-cgi/access/certs would return."""
    pub_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(rsa_key.public_key()))
    pub_jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return {"keys": [pub_jwk]}


def _mint(rsa_key, *, aud=AUD, iss=f"https://{TEAM}", ttl=300) -> str:
    now = dt.datetime.now(tz=dt.UTC)
    payload = {
        "aud": aud,
        "iss": iss,
        "email": "juf@ottorosie.com",
        "iat": now,
        "exp": now + dt.timedelta(seconds=ttl),
    }
    return jwt.encode(payload, rsa_key, algorithm="RS256", headers={"kid": KID})


def test_verifier_accepts_a_valid_token(rsa_key, jwks, monkeypatch):
    monkeypatch.setattr(cf_access.AccessVerifier, "_fetch_jwks", lambda self: jwks)
    v = cf_access.AccessVerifier(TEAM, AUD)
    claims = v.verify(_mint(rsa_key))
    assert claims["email"] == "juf@ottorosie.com"
    assert v.is_valid(_mint(rsa_key))


def test_verifier_rejects_bad_tokens(rsa_key, jwks, monkeypatch):
    monkeypatch.setattr(cf_access.AccessVerifier, "_fetch_jwks", lambda self: jwks)
    v = cf_access.AccessVerifier(TEAM, AUD)
    assert not v.is_valid(None)
    assert not v.is_valid("not-a-jwt")
    assert not v.is_valid(_mint(rsa_key, aud="someone-elses-app"))  # wrong audience
    assert not v.is_valid(_mint(rsa_key, iss="https://evil.example.com"))  # wrong issuer
    assert not v.is_valid(_mint(rsa_key, ttl=-10))  # expired
    # Signed by a different key than the published one.
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert not v.is_valid(_mint(other))


# ---- middleware end to end ----
def _client(monkeypatch, tmp_path, **extra) -> Iterator[TestClient]:
    settings = Settings(
        data_dir=tmp_path / "data",
        hardware="mock",
        secret_key="test-secret",
        startup_sync_wait_seconds=0,
        cf_access_team_domain=TEAM,
        cf_access_aud=AUD,
        **extra,
    )
    svc = Service(settings)
    app = svc.build_app()
    with TestClient(app) as c:
        yield c
    svc.stop()
    db_module._SESSION_FACTORY = None


@pytest.fixture
def access_client(monkeypatch, tmp_path, jwks) -> Iterator[TestClient]:
    monkeypatch.setattr(cf_access.AccessVerifier, "_fetch_jwks", lambda self: jwks)
    yield from _client(monkeypatch, tmp_path)


def test_tunnel_request_without_token_is_blocked(access_client):
    # /login needs no app auth, so a 403 here is the Access gate, not the app.
    resp = access_client.get("/login", headers={"cf-ray": "abc123"})
    assert resp.status_code == 403


def test_tunnel_request_with_valid_token_passes_gate(access_client, rsa_key):
    resp = access_client.get(
        "/login", headers={"cf-access-jwt-assertion": _mint(rsa_key)}
    )
    assert resp.status_code == 200


def test_lan_request_is_not_gated(access_client):
    # No loopback origin and no Cloudflare headers -> the gate stays out of the way
    # and the LAN keeps using the password login.
    resp = access_client.get("/login")
    assert resp.status_code == 200


def test_fail_closed_when_pyjwt_missing(monkeypatch, tmp_path):
    # Access configured but the verifier can't be built (extra not installed):
    # tunnel traffic is denied, LAN traffic still works.
    def _boom(*a, **k):
        raise ImportError("No module named 'jwt'")

    monkeypatch.setattr(cf_access.AccessVerifier, "__init__", _boom)
    gen = _client(monkeypatch, tmp_path)
    client = next(gen)
    try:
        assert client.get("/login", headers={"cf-ray": "x"}).status_code == 403
        assert client.get("/login").status_code == 200
    finally:
        with contextlib.suppress(StopIteration):
            next(gen)


def test_gate_is_absent_when_not_configured(tmp_path):
    # No cf_access_* settings -> no gate at all; a forged edge header does nothing.
    settings = Settings(
        data_dir=tmp_path / "data",
        hardware="mock",
        secret_key="test-secret",
        startup_sync_wait_seconds=0,
    )
    svc = Service(settings)
    with TestClient(svc.build_app()) as c:
        assert c.get("/login", headers={"cf-ray": "x"}).status_code == 200
    svc.stop()
    db_module._SESSION_FACTORY = None

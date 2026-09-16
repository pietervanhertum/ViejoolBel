"""Cloudflare Access JWT verification.

When ViejoolBel is exposed to the public internet through a Cloudflare Tunnel
(see docs/public-access.md), Cloudflare Access authenticates the visitor at the
edge and forwards a signed JWT to the origin in the ``Cf-Access-Jwt-Assertion``
header (and the ``CF_Authorization`` cookie). Verifying that JWT here means a
request cannot reach the app through the public hostname without having passed
Access first — even if the tunnel or a policy is later misconfigured. This is
defence in depth on top of the app's own password login.

The gate is deliberately narrow: it only applies to requests that arrived
through the tunnel (loopback origin, or carrying Cloudflare edge headers). Direct
access on the school LAN (``viejoolbel.local:8080``) is never gated by Access.

PyJWT (the ``[access]`` extra) is imported lazily so the base app still runs
without it; when Access is configured but PyJWT is missing, the caller denies
tunnel requests rather than letting them through.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# Loopback addresses. cloudflared connects to the app on localhost, so a loopback
# client is our signal that a request came in through the tunnel rather than off
# the LAN. IPv6 loopback and the IPv4-mapped form are included for completeness.
_LOOPBACK = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})

# How long to trust a fetched key set before refetching (Cloudflare rotates keys).
_JWKS_TTL_SECONDS = 3600.0


def looks_like_tunnel_request(client_host: str | None, headers: Any) -> bool:
    """True if the request appears to have arrived through the Cloudflare Tunnel.

    A loopback client is the authoritative signal (cloudflared proxies to
    ``http://localhost:8080``). The presence of Cloudflare edge headers is also
    treated as tunnel-origin so that a forged-but-invalid header fails closed
    (it forces JWT verification, which such a request cannot pass) rather than
    slipping past. Neither can be used by a LAN client to *bypass* the gate —
    only to opt themselves into stricter checking.
    """
    if client_host in _LOOPBACK:
        return True
    # ``headers`` is a Starlette Headers / mapping with case-insensitive lookup.
    with contextlib.suppress(TypeError):
        if "cf-access-jwt-assertion" in headers or "cf-ray" in headers:
            return True
    return False


def extract_token(headers: Any, cookies: Any) -> str | None:
    """Pull the Access JWT from the header or the ``CF_Authorization`` cookie."""
    token = None
    with contextlib.suppress(AttributeError):
        token = headers.get("cf-access-jwt-assertion")
    if not token:
        with contextlib.suppress(AttributeError):
            token = cookies.get("CF_Authorization")
    return token or None


class AccessVerifier:
    """Verifies Cloudflare Access JWTs against a team's rotating public keys.

    Importing this class requires PyJWT (the ``[access]`` extra); construction
    raises ``ImportError`` otherwise, which the app catches to enter fail-closed
    (deny tunnel traffic) mode.
    """

    def __init__(
        self,
        team_domain: str,
        aud: str,
        *,
        certs_url: str | None = None,
        _clock: Any = time.time,
    ) -> None:
        import jwt  # noqa: F401  (import-time dependency check; used in verify())

        self.issuer = f"https://{team_domain}"
        self.aud = aud
        self.certs_url = certs_url or f"{self.issuer}/cdn-cgi/access/certs"
        self._keys: dict[str, Any] = {}  # kid -> RSA public key object
        self._fetched_at = 0.0
        self._clock = _clock

    # -- key management ---------------------------------------------------
    def _fetch_jwks(self) -> dict[str, Any]:
        req = urllib.request.Request(self.certs_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (trusted host)
            return json.loads(resp.read().decode("utf-8"))

    def _load_keys(self, *, force: bool = False) -> None:
        fresh = (self._clock() - self._fetched_at) < _JWKS_TTL_SECONDS
        if self._keys and fresh and not force:
            return
        import jwt

        data = self._fetch_jwks()
        keys: dict[str, Any] = {}
        for jwk in data.get("keys", []):
            kid = jwk.get("kid")
            if not kid:
                continue
            keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        self._keys = keys
        self._fetched_at = self._clock()

    def _key_for(self, kid: str | None) -> Any:
        if kid and kid in self._keys:
            return self._keys[kid]
        # Unknown key id: keys may have rotated, so refetch once.
        self._load_keys(force=True)
        if kid and kid in self._keys:
            return self._keys[kid]
        raise KeyError(f"no Cloudflare Access signing key for kid={kid!r}")

    # -- verification -----------------------------------------------------
    def verify(self, token: str) -> dict[str, Any]:
        """Return the decoded claims, or raise if the token is not valid."""
        import jwt

        self._load_keys()
        header = jwt.get_unverified_header(token)
        key = self._key_for(header.get("kid"))
        return jwt.decode(
            token,
            key=key,
            algorithms=["RS256"],
            audience=self.aud,
            issuer=self.issuer,
        )

    def is_valid(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            self.verify(token)
            return True
        except Exception as exc:  # noqa: BLE001 - any failure means "not authorised"
            logger.warning("Cloudflare Access token rejected: %s", exc)
            return False

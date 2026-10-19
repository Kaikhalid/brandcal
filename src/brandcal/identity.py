"""Cloudflare Access identity: RS256 JWT verification and the email-to-role map (UI_SPEC 2.3, 2.4).

Verification needs the optional ``cryptography`` extra, imported only when it is used. Every
refusal is a short plain message; the token is never logged or echoed.
"""

from __future__ import annotations

import base64
import binascii
import json
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from brandcal.errors import BrandcalError, ErrorCode

LEEWAY_SECONDS = 60
MIN_KEY_BITS = 2048
_MAX_JWKS_BYTES = 1 << 20

JwksFetcher = Callable[[str], dict[str, Any]]


@dataclass(frozen=True)
class Principal:
    """A verified email and what it may do: "approver" (with its agent id) or "viewer"."""

    email: str
    role: str
    agent: str | None = None


def _unverified(reason: str) -> BrandcalError:
    return BrandcalError(
        ErrorCode.IDENTITY_UNVERIFIED,
        reason,
        "Sign in through Cloudflare Access, or ask the admin to check serve.identity.",
    )


def require_crypto() -> None:
    """Raise EXTRA_NOT_INSTALLED unless ``cryptography`` can be imported."""
    try:
        import cryptography.hazmat.primitives.asymmetric.rsa  # noqa: F401
    except ImportError:
        raise BrandcalError(
            ErrorCode.EXTRA_NOT_INSTALLED,
            "Access JWT verification needs the cryptography extra; install the crypto extra,"
            " or use --dev-unverified for a local, read-only session.",
            'Install it with: pip install "brandcal[crypto]"',
        ) from None


def fetch_jwks(url: str) -> dict[str, Any]:
    """Download and parse the team's signing keys."""
    if not url.startswith("https://"):
        raise ValueError("the JWKS URL must be https")
    with urllib.request.urlopen(url, timeout=10) as res:
        data = json.loads(res.read(_MAX_JWKS_BYTES))
    if not isinstance(data, dict):
        raise ValueError("the JWKS is not a JSON object")
    return data


def _b64(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        raise _unverified("The token is not a well-formed JWT.") from None


def _json_object(text: str) -> dict[str, Any]:
    try:
        data = json.loads(_b64(text))
    except ValueError:  # includes UnicodeDecodeError
        raise _unverified("The token is not a well-formed JWT.") from None
    if not isinstance(data, dict):
        raise _unverified("The token is not a well-formed JWT.")
    return data


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


class Verifier:
    """Verifies ``Cf-Access-Jwt-Assertion`` values for one team domain and audience."""

    def __init__(
        self,
        team_domain: str,
        audience: str,
        cache_minutes: float,
        fetch: JwksFetcher = fetch_jwks,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.issuer = f"https://{team_domain}"
        self.audience = audience
        self.url = f"{self.issuer}/cdn-cgi/access/certs"
        self._ttl = cache_minutes * 60
        self._fetch, self._clock = fetch, clock
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched_at: float | None = None
        self._lock = threading.Lock()

    def _load(self) -> None:
        try:
            data = self._fetch(self.url)
            keys = {str(k["kid"]): k for k in data["keys"] if isinstance(k, dict) and "kid" in k}
        except (OSError, ValueError, KeyError, TypeError):
            raise _unverified("The Access signing keys could not be loaded.") from None
        self._keys, self._fetched_at = keys, self._clock()

    def _key(self, kid: str) -> dict[str, Any]:
        """The JWK for ``kid``: from the cache, else one refetch, else a refusal."""
        with self._lock:
            fresh = self._fetched_at is not None and self._clock() - self._fetched_at < self._ttl
            fetched = False
            if not fresh:
                self._load()
                fetched = True
            if kid not in self._keys and not fetched:
                self._load()
            if kid not in self._keys:
                raise _unverified("The token was signed with an unknown key.")
            return self._keys[kid]

    def verify(self, token: str | None) -> str:
        """The email in a valid token; BrandcalError IDENTITY_UNVERIFIED otherwise."""
        if token is None or not token.strip():
            raise _unverified("No Access token came with this request.")
        parts = token.strip().split(".")
        if len(parts) != 3:
            raise _unverified("The token is not a well-formed JWT.")
        header, payload = _json_object(parts[0]), _json_object(parts[1])
        # Algorithm first, before any key is fetched or used: no "none", no HS256, nothing else.
        if header.get("alg") != "RS256":
            raise _unverified("The token does not use RS256.")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise _unverified("The token names no signing key.")
        require_crypto()
        key = self._public_key(self._key(kid))
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        try:
            key.verify(
                _b64(parts[2]),
                f"{parts[0]}.{parts[1]}".encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except InvalidSignature:
            raise _unverified("The token signature is not valid.") from None
        return self._email(payload)

    @staticmethod
    def _public_key(jwk: Mapping[str, Any]) -> Any:
        from cryptography.hazmat.primitives.asymmetric import rsa

        try:
            if jwk.get("kty") != "RSA":
                raise ValueError("not an RSA key")
            n = int.from_bytes(base64.urlsafe_b64decode(jwk["n"] + "=" * (-len(jwk["n"]) % 4)))
            e = int.from_bytes(base64.urlsafe_b64decode(jwk["e"] + "=" * (-len(jwk["e"]) % 4)))
            if n.bit_length() < MIN_KEY_BITS:
                raise ValueError("key too small")
            return rsa.RSAPublicNumbers(e, n).public_key()
        except (KeyError, TypeError, ValueError, binascii.Error):
            raise _unverified("The Access signing key is not usable.") from None

    def _email(self, claims: Mapping[str, Any]) -> str:
        """Check aud, iss, exp, nbf and return the email claim."""
        aud = claims.get("aud")
        if self.audience not in (
            [aud] if isinstance(aud, str) else aud if isinstance(aud, list) else []
        ):
            raise _unverified("The token is for a different application.")
        if claims.get("iss") != self.issuer:
            raise _unverified("The token was issued by a different team.")
        now = self._clock()
        exp, nbf = _number(claims.get("exp")), claims.get("nbf")
        if exp is None:
            raise _unverified("The token has no expiry.")
        if now > exp + LEEWAY_SECONDS:
            raise _unverified("The token has expired.")
        if nbf is not None and (_number(nbf) is None or now < float(nbf) - LEEWAY_SECONDS):
            raise _unverified("The token is not valid yet.")
        email = claims.get("email")
        if not isinstance(email, str) or not email.strip():
            raise _unverified("The token carries no email.")
        return email.strip()


def resolve(serve: Mapping[str, Any], email: str) -> Principal:
    """Map a verified email to an approver or viewer, case-insensitively (UI_SPEC 2.3)."""
    key = email.strip().lower()
    for listed, agent in (serve.get("approvers") or {}).items():
        if str(listed).strip().lower() == key:
            return Principal(key, "approver", str(agent))
    if key in {str(v).strip().lower() for v in serve.get("viewers") or []}:
        return Principal(key, "viewer")
    raise BrandcalError(
        ErrorCode.IDENTITY_UNMAPPED,
        "Your identity is verified, but it is not listed for this calendar.",
        "Ask the admin to add it to serve.approvers or serve.viewers.",
    )

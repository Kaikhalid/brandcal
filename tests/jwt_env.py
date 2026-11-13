"""Test helpers for Access JWTs: a local RSA key, an RS256 signer and a fake JWKS fetcher."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

TEAM = "example.cloudflareaccess.com"
AUD = "example-aud-tag"
RELAY_AUD = "example-relay-aud-tag"  # the connector's own Access app (U4 relay spec 3)
ISS = f"https://{TEAM}"
JWKS_URL = f"https://{TEAM}/cdn-cgi/access/certs"
APPROVER = "approver@example.com"
VIEWER = "viewer@example.com"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _int_b64(value: int) -> str:
    return b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def claims(**overrides: Any) -> dict[str, Any]:
    """Valid claims for APPROVER; pass a value to replace it, or None to drop the claim."""
    now = int(time.time())
    out: dict[str, Any] = {
        "aud": [AUD],
        "iss": ISS,
        "email": APPROVER,
        "iat": now,
        "nbf": now - 10,
        "exp": now + 3600,
    }
    out.update(overrides)
    return {k: v for k, v in out.items() if v is not None}


def service_claims(**overrides: Any) -> dict[str, Any]:
    """Claims shaped like an Access service-token JWT: a common_name, an empty sub, no email."""
    return claims(email=None, common_name="example-client-id.access", sub="", **overrides)


class Signer:
    """An RSA key that signs test tokens and publishes itself as a JWKS entry."""

    def __init__(self, kid: str = "key-1") -> None:
        self.kid = kid
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def jwks(self) -> dict[str, Any]:
        nums = self.key.public_key().public_numbers()
        jwk = {"kty": "RSA", "kid": self.kid, "n": _int_b64(nums.n), "e": _int_b64(nums.e)}
        return {"keys": [jwk]}

    def public_pem(self) -> bytes:
        return self.key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )

    def token(
        self, payload: dict[str, Any] | None = None, header: dict[str, Any] | None = None
    ) -> str:
        """An RS256 token; ``header`` replaces the default header (it is still signed with RSA)."""
        head = header if header is not None else {"alg": "RS256", "typ": "JWT", "kid": self.kid}
        body = claims() if payload is None else payload
        signing_input = f"{_part(head)}.{_part(body)}"
        sig = self.key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
        return f"{signing_input}.{b64(sig)}"

    def hs256_token(self, payload: dict[str, Any] | None = None) -> str:
        """The classic key-confusion forgery: HMAC with the public key bytes as the secret."""
        head = {"alg": "HS256", "typ": "JWT", "kid": self.kid}
        signing_input = f"{_part(head)}.{_part(claims() if payload is None else payload)}"
        mac = hmac.new(self.public_pem(), signing_input.encode(), hashlib.sha256).digest()
        return f"{signing_input}.{b64(mac)}"

    def unsigned_token(self, payload: dict[str, Any] | None = None) -> str:
        head = {"alg": "none", "typ": "JWT", "kid": self.kid}
        return f"{_part(head)}.{_part(claims() if payload is None else payload)}."


def _part(data: dict[str, Any]) -> str:
    return b64(json.dumps(data).encode())


class FakeJwks:
    """An injectable JWKS fetcher that records every call and never touches the network."""

    def __init__(self, *signers: Signer) -> None:
        self.keys: list[dict[str, Any]] = []
        self.publish(*signers)
        self.urls: list[str] = []

    def publish(self, *signers: Signer) -> None:
        self.keys = [k for s in signers for k in s.jwks()["keys"]]

    def __call__(self, url: str) -> dict[str, Any]:
        self.urls.append(url)
        return {"keys": list(self.keys)}

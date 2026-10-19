"""Access JWT verification (UI_SPEC 2.3, 2.4): every refusal, key rotation, mapping."""

from __future__ import annotations

import builtins
import time
from typing import Any

import pytest
from jwt_env import APPROVER, AUD, JWKS_URL, TEAM, VIEWER, FakeJwks, Signer, claims

from brandcal import identity
from brandcal.errors import BrandcalError, ErrorCode
from brandcal.identity import Verifier

SERVE: dict[str, Any] = {
    "approvers": {"Approver@Example.com": "approver-1"},
    "viewers": ["viewer@example.com"],
}


@pytest.fixture(scope="module")
def signer() -> Signer:
    return Signer("key-1")


class Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now


def make(fetch: FakeJwks, clock: Clock | None = None, minutes: int = 5) -> Verifier:
    return Verifier(TEAM, AUD, minutes, fetch=fetch, clock=clock or time.time)


def refused(
    verifier: Verifier, token: str | None, code: ErrorCode = ErrorCode.IDENTITY_UNVERIFIED
) -> str:
    with pytest.raises(BrandcalError) as err:
        verifier.verify(token)
    assert err.value.code == code
    assert err.value.message and err.value.next_step
    if token:
        assert token not in err.value.message  # never echo the token
        assert token not in err.value.next_step
    return err.value.message


def test_valid_token_returns_the_email_and_fetches_from_the_team_domain(signer: Signer) -> None:
    fetch = FakeJwks(signer)
    assert make(fetch).verify(signer.token()) == APPROVER
    assert fetch.urls == [JWKS_URL]


def test_aud_may_be_a_plain_string(signer: Signer) -> None:
    assert make(FakeJwks(signer)).verify(signer.token(claims(aud=AUD))) == APPROVER


def test_aud_list_with_other_audiences_is_accepted(signer: Signer) -> None:
    assert make(FakeJwks(signer)).verify(signer.token(claims(aud=["other", AUD]))) == APPROVER


def test_jwks_is_cached_for_the_configured_minutes(signer: Signer) -> None:
    fetch, clock = FakeJwks(signer), Clock()
    verifier = make(fetch, clock, minutes=5)
    token = signer.token(claims(exp=int(clock.now) + 3600))
    verifier.verify(token)
    clock.now += 4 * 60
    verifier.verify(token)
    assert len(fetch.urls) == 1
    clock.now += 2 * 60
    verifier.verify(token)
    assert len(fetch.urls) == 2


def test_leeway_is_sixty_seconds(signer: Signer) -> None:
    now = int(time.time())
    verifier = make(FakeJwks(signer))
    assert verifier.verify(signer.token(claims(exp=now - 30))) == APPROVER
    assert verifier.verify(signer.token(claims(nbf=now + 30))) == APPROVER
    refused(verifier, signer.token(claims(exp=now - 120)))
    refused(verifier, signer.token(claims(nbf=now + 120)))


@pytest.mark.parametrize("token", [None, "", "   "])
def test_no_token(signer: Signer, token: str | None) -> None:
    fetch = FakeJwks(signer)
    refused(make(fetch), token)
    assert fetch.urls == []


@pytest.mark.parametrize("token", ["abc", "a.b", "a.b.c.d", "!!!.@@@.###", "e30.e30."])
def test_malformed_token(signer: Signer, token: str) -> None:
    refused(make(FakeJwks(signer)), token)


def test_header_or_payload_that_is_not_a_json_object(signer: Signer) -> None:
    good = signer.token().split(".")
    # "W10" is [] and "bnVsbA" is null, both valid JSON but not objects.
    refused(make(FakeJwks(signer)), ".".join(["W10", good[1], good[2]]))
    refused(make(FakeJwks(signer)), ".".join([good[0], "bnVsbA", good[2]]))


def test_bad_signature(signer: Signer) -> None:
    other = Signer("key-1")  # same kid, different key
    refused(make(FakeJwks(signer)), other.token())


def test_tampered_payload(signer: Signer) -> None:
    head, _, sig = signer.token().split(".")
    forged = signer.token(claims(email="someone-else@example.com")).split(".")[1]
    refused(make(FakeJwks(signer)), f"{head}.{forged}.{sig}")


def test_expired(signer: Signer) -> None:
    refused(make(FakeJwks(signer)), signer.token(claims(exp=int(time.time()) - 3600)))


def test_exp_is_required(signer: Signer) -> None:
    refused(make(FakeJwks(signer)), signer.token(claims(exp=None)))


def test_not_yet_valid(signer: Signer) -> None:
    refused(make(FakeJwks(signer)), signer.token(claims(nbf=int(time.time()) + 3600)))


def test_wrong_audience(signer: Signer) -> None:
    refused(make(FakeJwks(signer)), signer.token(claims(aud=["someone-elses-app"])))
    refused(make(FakeJwks(signer)), signer.token(claims(aud=None)))


def test_wrong_issuer(signer: Signer) -> None:
    refused(make(FakeJwks(signer)), signer.token(claims(iss="https://evil.example.com")))
    refused(make(FakeJwks(signer)), signer.token(claims(iss=TEAM)))  # no https://


def test_missing_or_empty_email(signer: Signer) -> None:
    refused(make(FakeJwks(signer)), signer.token(claims(email=None)))
    refused(make(FakeJwks(signer)), signer.token(claims(email="")))
    refused(make(FakeJwks(signer)), signer.token(claims(email=42)))


def test_alg_none_is_refused_before_any_key_is_used(signer: Signer) -> None:
    fetch = FakeJwks(signer)
    refused(make(fetch), signer.unsigned_token())
    assert fetch.urls == []


def test_alg_hs256_with_the_public_key_as_secret_is_refused(signer: Signer) -> None:
    fetch = FakeJwks(signer)
    refused(make(fetch), signer.hs256_token())
    assert fetch.urls == []


@pytest.mark.parametrize("alg", ["RS512", "rs256", "ES256", "", None, 256])
def test_only_exactly_rs256_is_accepted(signer: Signer, alg: object) -> None:
    fetch = FakeJwks(signer)
    refused(make(fetch), signer.token(header={"alg": alg, "kid": signer.kid}))
    refused(make(fetch), signer.token(header={"kid": signer.kid}))
    assert fetch.urls == []


def test_missing_kid(signer: Signer) -> None:
    refused(make(FakeJwks(signer)), signer.token(header={"alg": "RS256"}))


def test_unknown_kid_refetches_once_then_refuses(signer: Signer) -> None:
    fetch = FakeJwks(signer)
    verifier = make(fetch)
    verifier.verify(signer.token())
    assert len(fetch.urls) == 1
    refused(verifier, Signer("rotated").token())
    assert len(fetch.urls) == 2  # exactly one refetch


def test_unknown_kid_on_a_cold_cache_fetches_only_once(signer: Signer) -> None:
    fetch = FakeJwks(signer)
    refused(make(fetch), Signer("rotated").token())
    assert len(fetch.urls) == 1


def test_key_rotation_is_picked_up_by_the_refetch(signer: Signer) -> None:
    fetch = FakeJwks(signer)
    verifier = make(fetch)
    verifier.verify(signer.token())
    new = Signer("key-2")
    fetch.publish(signer, new)
    assert verifier.verify(new.token()) == APPROVER
    assert len(fetch.urls) == 2


def test_fetch_failure_is_a_refusal_not_a_crash(signer: Signer) -> None:
    def broken(url: str) -> dict[str, Any]:
        raise OSError("network down")

    message = refused(Verifier(TEAM, AUD, 5, fetch=broken), signer.token())
    assert "signing keys" in message


@pytest.mark.parametrize(
    "keys", [[], [{"kid": "key-1", "kty": "EC"}], [{"kid": "key-1", "kty": "RSA"}]]
)
def test_unusable_jwks_entries_are_a_refusal(signer: Signer, keys: list[dict[str, Any]]) -> None:
    fetch = FakeJwks()
    fetch.keys = keys
    refused(make(fetch), signer.token())


def test_extra_missing_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    real = builtins.__import__

    def deny(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.split(".")[0] == "cryptography":
            raise ImportError("blocked for the test")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny)
    with pytest.raises(BrandcalError) as err:
        identity.require_crypto()
    assert err.value.code == ErrorCode.EXTRA_NOT_INSTALLED
    assert err.value.exit_code == 2
    assert "crypto extra" in err.value.message
    assert "--dev-unverified" in err.value.message


def test_approver_mapping_is_case_insensitive() -> None:
    who = identity.resolve(SERVE, "APPROVER@example.COM")
    assert (who.email, who.role, who.agent) == ("approver@example.com", "approver", "approver-1")


def test_viewer_mapping_is_read_only() -> None:
    who = identity.resolve(SERVE, "Viewer@Example.com")
    assert (who.role, who.agent) == ("viewer", None)


def test_verified_but_unlisted_is_unmapped() -> None:
    with pytest.raises(BrandcalError) as err:
        identity.resolve(SERVE, "stranger@example.com")
    assert err.value.code == ErrorCode.IDENTITY_UNMAPPED
    assert "serve.approvers" in err.value.next_step


def test_listed_as_both_means_approver() -> None:
    both = {"approvers": {APPROVER: "approver-1"}, "viewers": [APPROVER, VIEWER]}
    assert identity.resolve(both, APPROVER).role == "approver"

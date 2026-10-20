"""End to end, in process: fake Durable Object -> connector -> `serve.make_server` (spec 10)."""

from __future__ import annotations

import io
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import test_serve_api as base
from jwt_env import APPROVER, AUD, TEAM, FakeJwks, Signer, claims
from ui_env import add_post, make_home
from ws_env import ACCESS, HOST, SECRET, TZ, FakeDO, Reply, Running

from brandcal import relay, serve
from brandcal.config import load_config
from brandcal.identity import Verifier

signer = base.signer  # the module's key, reused as it is
ORIGIN = base.ORIGIN
HASH = "sha256-" + "A" * 43 + "="
INDEX = b"<!doctype html><title>Example Co</title><script>1</script>"


@dataclass
class Stack:
    home: Path
    do: FakeDO
    log: io.StringIO
    signer: Signer

    def call(
        self,
        method: str,
        path: str,
        *,
        jwt: str | None = "auto",
        origin: str | None = None,
        csrf: str | None = None,
        host: str = HOST,
        payload: dict[str, Any] | None = None,
    ) -> tuple[Reply, dict[str, str]]:
        headers = [("Host", host), ("Accept", "*/*")]
        if jwt is not None:
            token = self.signer.token(claims()) if jwt == "auto" else jwt
            headers.append(("Cf-Access-Jwt-Assertion", token))
        if origin:
            headers.append(("Origin", origin))
        if csrf:
            headers.append(("X-Brandcal-CSRF", csrf))
        body = b""
        if payload is not None:
            headers.append(("Content-Type", "application/json"))
            body = json.dumps(payload).encode()
        reply = self.do.fetch(method, path, headers, body)
        if host == HOST:
            assert reply.error is None, reply.error  # the answer arrived whole
        return reply, {k.lower(): v for k, v in reply.headers}

    def json(self, path: str) -> dict[str, Any]:
        reply, _ = self.call("GET", path)
        out: dict[str, Any] = json.loads(reply.body)
        return out


@pytest.fixture
def stack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signer: Signer) -> Iterator[Stack]:
    home = make_home(tmp_path / "home", monkeypatch)
    base.write_config(home)
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_bytes(INDEX)
    (static / "csp.json").write_text(
        json.dumps({"index.html": {"script": [HASH]}}), encoding="utf-8"
    )
    verifier = Verifier(TEAM, AUD, 5, fetch=FakeJwks(signer))
    server = serve.make_server(home, load_config(home), 0, verifier, static_root=static)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    do, log = FakeDO(), io.StringIO()
    settings = relay.Settings(do.url, HOST, int(server.server_address[1]), SECRET, ACCESS)
    running = Running(relay.Connector(settings, TZ, out=log))
    do.wait_ready()
    yield Stack(home, do, log, signer)
    running.stop()
    do.close()
    server.shutdown()
    server.server_close()


def test_pages_pass_through_with_their_csp(stack: Stack) -> None:
    reply, h = stack.call("GET", "/", jwt=None)
    assert reply.status == 200 and reply.body == INDEX
    assert h["content-type"] == "text/html; charset=utf-8"
    assert h["content-security-policy"] == f"default-src 'self'; script-src 'self' '{HASH}'"
    assert h["x-content-type-options"] == "nosniff" and h["referrer-policy"] == "no-referrer"
    assert h["cache-control"] == "no-store" and h["x-brandcal-exit"] == "0"
    mvp, h = stack.call("GET", "/mvp/", jwt=None)
    assert mvp.status == 200 and h["content-security-policy"] == "default-src 'self'"
    redirect, h = stack.call("GET", "/mvp", jwt=None)
    assert (redirect.status, h["location"]) == (308, "/mvp/")
    missing, h = stack.call("GET", "/nope.html", jwt=None)
    assert missing.status == 404 and h["x-brandcal-exit"] == "7"


def test_the_session_is_the_access_jwt_identity(stack: Stack) -> None:
    session = stack.json("/api/session")
    assert (session["identity"], session["role"], session["source"]) == (
        APPROVER,
        "approver",
        "access-jwt",
    )
    assert session["csrf"]


def test_a_missing_or_foreign_token_is_refused_by_brandcal_itself(stack: Stack) -> None:
    none, _ = stack.call("GET", "/api/session", jwt=None)
    other = stack.signer.token(claims(aud=["another-app-aud"]))
    foreign, _ = stack.call("GET", "/api/session", jwt=other)
    for reply in (none, foreign):
        assert reply.status == 401
        assert json.loads(reply.body)["error"]["code"] == "IDENTITY_UNVERIFIED"


def approve_body(stack: Stack, post_id: str) -> dict[str, Any]:
    post = stack.json(f"/api/posts/{post_id}")
    return {
        "version": post["content_version"],
        "hash": post["content_hash"],
        "window": post["window"],
    }


def test_an_approval_through_the_relay_is_recorded_as_the_console(stack: Stack) -> None:
    post = add_post(stack.home)
    csrf = stack.json("/api/session")["csrf"]
    reply, _ = stack.call(
        "POST",
        f"/api/posts/{post['id']}/approve",
        origin=ORIGIN,
        csrf=csrf,
        payload=approve_body(stack, post["id"]),
    )
    assert reply.status == 200, reply.body
    assert base.counts(stack.home)[1] == 1
    rows = base.approvals(stack.home, post["id"])
    assert rows[0]["channel"] == "console" and rows[0]["identity_source"] == "access-jwt"


def test_a_wrong_origin_is_bad_origin_and_changes_nothing(stack: Stack) -> None:
    post = add_post(stack.home)
    csrf = stack.json("/api/session")["csrf"]
    before = base.counts(stack.home)
    reply, h = stack.call(
        "POST",
        f"/api/posts/{post['id']}/approve",
        origin="https://evil.example.org",
        csrf=csrf,
        payload=approve_body(stack, post["id"]),
    )
    assert reply.status == 403 and h["x-brandcal-exit"] == "4"
    assert json.loads(reply.body)["error"]["code"] == "BAD_ORIGIN"
    assert base.counts(stack.home) == before


def test_a_wrong_host_never_reaches_brandcal(stack: Stack) -> None:
    post = add_post(stack.home)
    csrf = stack.json("/api/session")["csrf"]
    before = base.counts(stack.home)
    reply, _ = stack.call(
        "POST",
        f"/api/posts/{post['id']}/approve",
        host="evil.example.org",
        origin=ORIGIN,
        csrf=csrf,
        payload=approve_body(stack, post["id"]),
    )
    assert reply.error == "BAD_FRAME" and reply.status is None
    assert base.counts(stack.home) == before


def test_a_forged_email_header_and_cookie_change_nothing(stack: Stack) -> None:
    viewer = stack.signer.token(claims(email="viewer@example.com"))
    reply, _ = stack.call("GET", "/api/session", jwt=viewer)
    sent = [
        ("Host", HOST),
        ("Cf-Access-Jwt-Assertion", viewer),
        ("Cf-Access-Authenticated-User-Email", APPROVER),
        ("Cookie", "CF_Authorization=" + stack.signer.token(claims())),
    ]
    forged = stack.do.fetch("GET", "/api/session", sent)
    assert json.loads(forged.body)["identity"] == json.loads(reply.body)["identity"]
    assert json.loads(forged.body)["role"] == "viewer"


def test_the_log_holds_no_secret_and_no_jwt(stack: Stack) -> None:
    token = stack.signer.token(claims())
    csrf = stack.json("/api/session")["csrf"]
    post = add_post(stack.home)
    stack.call("POST", f"/api/posts/{post['id']}/approve", origin=ORIGIN, csrf=csrf, payload={})
    stack.call("GET", "/api/session", jwt=token)
    text = stack.log.getvalue()
    assert "outcome=ok" in text and "method=POST" in text
    for secret in (
        token,
        token.split(".")[1],
        csrf,
        SECRET.decode(),
        ACCESS[0],
        ACCESS[1],
        APPROVER,
    ):
        assert secret not in text

"""The JSON API behind `brandcal serve` (UI_SPEC 1.3, 1.5, 2.2, 2.5, 2.7, 3.3)."""

from __future__ import annotations

import builtins
import http.client
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from jwt_env import APPROVER, AUD, TEAM, VIEWER, FakeJwks, Signer, claims
from ui_env import CFG, NEW_WINDOW, add_post, cli_approve, make_home, open_home, run

from brandcal import actions, cli, serve
from brandcal.config import load_config
from brandcal.identity import Verifier

ORIGIN = "https://brandcal.example.com"
HOST = "brandcal.example.com"
SERVE: dict[str, Any] = {
    "port": 8700,
    "allowed_origins": [ORIGIN],
    "identity": {"team_domain": TEAM, "audience": AUD, "jwks_cache_minutes": 5},
    "approvers": {APPROVER: "approver-1"},
    "viewers": [VIEWER],
    "console_agent": "console",
}
WRITES = ["approve", "request-changes", "reschedule", "cancel", "edit", "submit", "note"]


@dataclass
class Resp:
    status: int
    headers: dict[str, str]
    raw: bytes

    @property
    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = json.loads(self.raw)
        return out

    @property
    def code(self) -> str:
        return str(self.body["error"]["code"])


class Client:
    def __init__(self, port: int, signer: Signer) -> None:
        self.port, self.signer = port, signer

    def token(self, email: str = APPROVER) -> str:
        return self.signer.token(claims(email=email))

    def call(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> Resp:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            res = conn.getresponse()
            out = Resp(res.status, {k.lower(): v for k, v in res.getheaders()}, res.read())
        finally:
            conn.close()
        # Every response, success or refusal, carries the hardening headers and no CORS.
        assert not [h for h in out.headers if h.startswith("access-control-")]
        assert out.headers["x-content-type-options"] == "nosniff"
        assert out.headers["referrer-policy"] == "no-referrer"
        assert out.headers["cache-control"] == "no-store"
        assert out.headers["content-security-policy"] == "default-src 'self'"
        return out

    def get(self, path: str, email: str = APPROVER, token: str | None = "auto") -> Resp:
        headers = {}
        if token is not None:
            headers["Cf-Access-Jwt-Assertion"] = self.token(email) if token == "auto" else token
        return self.call("GET", path, headers)

    def csrf(self, email: str = APPROVER) -> str:
        return str(self.get("/api/session", email).body["csrf"])

    def post(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        email: str = APPROVER,
        token: str | None = "auto",
        origin: str | None = ORIGIN,
        host: str = HOST,
        csrf: str | None = "auto",
        content_type: str = "application/json",
        raw: bytes | None = None,
    ) -> Resp:
        headers = {"Host": host, "Content-Type": content_type}
        if token is not None:
            headers["Cf-Access-Jwt-Assertion"] = self.token(email) if token == "auto" else token
        if origin is not None:
            headers["Origin"] = origin
        if csrf is not None:
            headers["X-Brandcal-CSRF"] = self.csrf(email) if csrf == "auto" else csrf
        body = raw if raw is not None else json.dumps(payload or {}).encode()
        return self.call("POST", path, headers, body)


@dataclass
class Env:
    home: Path
    client: Client
    jwks: FakeJwks


@pytest.fixture(scope="module")
def signer() -> Signer:
    return Signer("key-1")


def start(
    home: Path, signer: Signer, dev: bool = False
) -> tuple[ThreadingHTTPServer, Client, FakeJwks]:
    cfg = load_config(home)
    jwks = FakeJwks(signer)
    verifier = None if dev else Verifier(TEAM, AUD, 5, fetch=jwks)
    server = serve.make_server(home, cfg, 0, verifier, dev=dev)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, Client(server.server_address[1], signer), jwks


def write_config(home: Path, **changes: Any) -> None:
    cfg = {**CFG, "serve": SERVE, **changes}
    (home / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signer: Signer) -> Iterator[Env]:
    home = make_home(tmp_path / "home", monkeypatch)
    write_config(home)
    server, client, jwks = start(home, signer)
    yield Env(home, client, jwks)
    server.shutdown()
    server.server_close()


@pytest.fixture
def dev(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, signer: Signer) -> Iterator[Env]:
    home = make_home(tmp_path / "home", monkeypatch)
    write_config(home)
    server, client, jwks = start(home, signer, dev=True)
    yield Env(home, client, jwks)
    server.shutdown()
    server.server_close()


def seen(client: Client, post_id: str) -> dict[str, Any]:
    """What the UI holds after loading a post: version, hash and window."""
    post = client.get(f"/api/posts/{post_id}").body
    return {
        "version": post["content_version"],
        "hash": post["content_hash"],
        "window": post["window"],
    }


def counts(home: Path) -> tuple[int, int]:
    with open_home(home) as (conn, _):
        return (
            conn.execute("SELECT count(*) FROM events").fetchone()[0],
            conn.execute("SELECT count(*) FROM approvals").fetchone()[0],
        )


def approvals(home: Path, post_id: str) -> list[dict[str, Any]]:
    with open_home(home) as (conn, _):
        rows = conn.execute("SELECT * FROM approvals WHERE post_id = ? ORDER BY id", (post_id,))
        return [dict(r) for r in rows]


def event_detail(home: Path, post_id: str, action: str) -> dict[str, Any]:
    with open_home(home) as (conn, _):
        row = conn.execute(
            "SELECT detail FROM events WHERE post_id = ? AND action = ?", (post_id, action)
        ).fetchone()
        out: dict[str, Any] = json.loads(row["detail"])
        return out


# --- reads -------------------------------------------------------------------------------


def test_binds_to_loopback_only(env: Env, tmp_path: Path) -> None:
    server = serve.make_server(env.home, load_config(env.home), 0, None, dev=True)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


def test_session_names_the_verified_identity(env: Env) -> None:
    res = env.client.get("/api/session")
    assert res.status == 200
    assert res.body["ok"] is True
    assert (res.body["identity"], res.body["role"]) == (APPROVER, "approver")
    assert res.body["source"] == "access-jwt"
    assert res.body["csrf"]


def test_session_for_a_viewer(env: Env) -> None:
    body = env.client.get("/api/session", VIEWER).body
    assert (body["identity"], body["role"], body["source"]) == (VIEWER, "viewer", "access-jwt")


def test_schema_has_rules_and_config(env: Env) -> None:
    body = env.client.get("/api/schema").body
    assert "pending_approval" in body["states"]
    assert body["platforms"]["linkedin"]["chars_per_post"] == 3000
    assert body["timezone"] == "+03:00"
    assert body["claim_minutes"] == 30
    assert body["campaigns"] == [] and body["pillars"] == []
    assert body["transitions"]


def test_list_show_and_events(env: Env) -> None:
    post = add_post(env.home)
    listing = env.client.get("/api/posts?status=pending_approval&platform=linkedin").body
    assert [p["id"] for p in listing["posts"]] == [post["id"]]
    assert env.client.get("/api/posts?status=approved").body["posts"] == []
    shown = env.client.get(f"/api/posts/{post['id']}").body
    assert shown["parts"][0]["text"] == "Hello from Example Co"
    assert "approvals" in shown and "media" in shown
    events = env.client.get(f"/api/events?post={post['id']}&limit=5").body
    assert events["events"] and events["last_id"] == events["events"][-1]["id"]
    assert env.client.get(f"/api/events?since={events['last_id']}").body["events"] == []


def test_show_lists_the_buttons_with_their_refusals(env: Env) -> None:
    post = add_post(env.home)
    acts = env.client.get(f"/api/posts/{post['id']}").body["actions"]
    assert [a["id"] for a in acts] == ["approve", "request-changes", "edit", "cancel"]
    assert all(a["enabled"] and a["refusal"] is None for a in acts)
    viewer = env.client.get(f"/api/posts/{post['id']}", VIEWER).body["actions"]
    assert [a["id"] for a in viewer] == [a["id"] for a in acts]
    for a in viewer:
        assert a["enabled"] is False
        assert a["refusal"]["code"] == "ROLE_NOT_ALLOWED" and a["refusal"]["next"]


def test_missing_post_is_404_in_the_cli_shape(env: Env) -> None:
    res = env.client.get("/api/posts/nope")
    assert res.status == 404 and res.code == "NOT_FOUND"
    assert res.headers["x-brandcal-exit"] == "7"
    assert res.body["error"]["message"] and res.body["error"]["next"]


def test_bad_query_is_a_refusal(env: Env) -> None:
    res = env.client.get("/api/events?since=abc")
    assert res.status == 400 and res.code == "BAD_ARGS"
    res = env.client.get("/api/posts?from=yesterday")
    assert res.status == 422 and res.code == "BAD_TIME"
    assert res.headers["x-brandcal-exit"] == "3"


def test_non_api_paths_are_404(env: Env) -> None:
    for path in ("/", "/index.html", "/static/app.js", "/api", "/api/unknown"):
        res = env.client.get(path)
        assert res.status == 404 and res.code == "NOT_FOUND", path


def test_media_is_served_from_the_media_record(env: Env, tmp_path: Path) -> None:
    post = add_post(env.home)
    (env.home / "media").mkdir()
    (env.home / "media" / "pic.png").write_bytes(b"\x89PNG fake")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    with open_home(env.home) as (conn, _):
        part = conn.execute("SELECT id FROM parts WHERE post_id = ?", (post["id"],)).fetchone()[0]
        sql = (
            "INSERT INTO media (id, part_id, pos, kind, path, sha256, alt_text, bytes)"
            " VALUES (?, ?, ?, 'image', ?, ?, 'Alt text', 9)"
        )
        conn.execute(sql, ("m1", part, 1, "media/pic.png", "0" * 64))
        conn.execute(sql, ("m2", part, 2, "../secret.txt", "1" * 64))
        conn.commit()
    ok = env.client.get(f"/api/media/{post['id']}/1")
    assert ok.status == 200 and ok.raw == b"\x89PNG fake"
    assert ok.headers["content-type"] == "image/png"
    for n in ("2", "3", "x"):  # a path leaving the home, no such media, not a number
        res = env.client.get(f"/api/media/{post['id']}/{n}")
        assert res.status == 404 and res.code == "NOT_FOUND", n


# --- identity over HTTP --------------------------------------------------------------------


def test_no_token_is_401_on_reads(env: Env) -> None:
    res = env.client.get("/api/session", token=None)
    assert res.status == 401 and res.code == "IDENTITY_UNVERIFIED"
    assert res.headers["x-brandcal-exit"] == "4"
    assert env.client.get("/api/posts", token=None).status == 401


@pytest.mark.parametrize("which", ["garbage", "badsig", "expired", "aud", "iss", "alg", "email"])
def test_bad_token_is_401_and_never_echoed(env: Env, which: str) -> None:
    signer = env.client.signer
    bad = {
        "garbage": "not-a-jwt",
        "badsig": Signer("key-1").token(),
        "expired": signer.token(claims(exp=1)),
        "aud": signer.token(claims(aud=["other"])),
        "iss": signer.token(claims(iss="https://evil.example.com")),
        "alg": signer.unsigned_token(),
        "email": signer.token(claims(email=None)),
    }[which]
    res = env.client.get("/api/session", token=bad)
    assert res.status == 401 and res.code == "IDENTITY_UNVERIFIED"
    assert bad not in res.raw.decode()


def test_hs256_forgery_is_401(env: Env) -> None:
    res = env.client.get("/api/session", token=env.client.signer.hs256_token())
    assert res.status == 401 and res.code == "IDENTITY_UNVERIFIED"


def test_no_other_identity_source_is_accepted(env: Env) -> None:
    headers = {"X-Forwarded-Email": APPROVER, "Cf-Access-Authenticated-User-Email": APPROVER}
    headers["Cookie"] = f"CF_Authorization={env.client.token()}"
    assert env.client.call("GET", "/api/session", headers).status == 401


def test_unknown_kid_refetches_once(env: Env) -> None:
    env.client.get("/api/session")
    assert len(env.jwks.urls) == 1
    res = env.client.get("/api/session", token=Signer("rotated").token())
    assert res.status == 401
    assert len(env.jwks.urls) == 2


def test_verified_but_unlisted_is_403_unmapped(env: Env) -> None:
    res = env.client.get("/api/session", "stranger@example.com")
    assert res.status == 403 and res.code == "IDENTITY_UNMAPPED"
    assert "serve.approvers" in res.body["error"]["next"]
    assert env.client.get("/api/posts", "stranger@example.com").status == 403


def test_email_is_matched_case_insensitively(env: Env) -> None:
    assert env.client.get("/api/session", "Approver@EXAMPLE.com").body["role"] == "approver"


@pytest.mark.parametrize("method", ["OPTIONS", "PUT", "DELETE", "PATCH", "HEAD"])
def test_other_methods_are_405_without_cors(env: Env, method: str) -> None:
    headers = {"Origin": ORIGIN, "Access-Control-Request-Method": "POST"}
    res = env.client.call(method, "/api/session", headers)
    assert res.status == 405
    assert res.headers["allow"] == "GET, POST"


# --- write hardening -------------------------------------------------------------------------


def test_write_without_origin_is_refused(env: Env) -> None:
    post = add_post(env.home)
    before = counts(env.home)
    path = f"/api/posts/{post['id']}/approve"
    body = seen(env.client, post["id"])
    for origin in (None, "https://evil.example.com", ORIGIN + "/", "http://brandcal.example.com"):
        res = env.client.post(path, body, origin=origin)
        assert res.status == 403 and res.code == "BAD_ORIGIN", origin
    assert counts(env.home) == before


def test_write_with_wrong_host_is_refused(env: Env) -> None:
    post = add_post(env.home)
    body = seen(env.client, post["id"])
    for host in ("evil.example.com", "127.0.0.1:8700", "brandcal.example.com.evil.example.com"):
        res = env.client.post(f"/api/posts/{post['id']}/approve", body, host=host)
        assert res.status == 403 and res.code == "BAD_ORIGIN", host


def test_write_needs_the_csrf_token_bound_to_the_identity(env: Env) -> None:
    post = add_post(env.home)
    path = f"/api/posts/{post['id']}/approve"
    body = seen(env.client, post["id"])
    before = counts(env.home)
    mine, viewers = env.client.csrf(), env.client.csrf(VIEWER)
    assert mine != viewers
    for csrf in (None, "", "wrong", viewers, mine + "0"):
        res = env.client.post(path, body, csrf=csrf)
        assert res.status == 403 and res.code == "BAD_ORIGIN", csrf
    assert counts(env.home) == before


def test_csrf_token_changes_with_the_server_secret(
    env: Env, tmp_path: Path, signer: Signer
) -> None:
    other, client, _ = start(env.home, signer)
    try:
        assert client.csrf() != env.client.csrf()
    finally:
        other.shutdown()
        other.server_close()


def test_write_must_be_json(env: Env) -> None:
    post = add_post(env.home)
    path = f"/api/posts/{post['id']}/approve"
    body = seen(env.client, post["id"])
    for ctype in ("text/plain", "application/x-www-form-urlencoded", "application/jsonx", ""):
        res = env.client.post(path, body, content_type=ctype)
        assert res.status == 400 and res.code == "BAD_ARGS", ctype
    assert env.client.post(path, raw=b"[1]").code == "BAD_ARGS"
    assert env.client.post(path, raw=b"{not json").code == "BAD_ARGS"


def test_oversized_body_is_refused(env: Env) -> None:
    post = add_post(env.home)
    before = counts(env.home)
    big = b'{"note": "' + b"x" * (256 * 1024) + b'"}'
    res = env.client.post(f"/api/posts/{post['id']}/note", raw=big)
    assert res.status == 400 and res.code == "BAD_ARGS"
    assert "256" in res.body["error"]["message"]
    assert counts(env.home) == before


def test_missing_body_fields_are_bad_args(env: Env) -> None:
    post = add_post(env.home)
    path = f"/api/posts/{post['id']}/approve"
    for payload in ({}, {"version": "1", "hash": "a" * 8, "window": "w"}, {"version": True}):
        assert env.client.post(path, payload).code == "BAD_ARGS", payload


def test_unknown_write_path_is_404(env: Env) -> None:
    post = add_post(env.home)
    assert env.client.post(f"/api/posts/{post['id']}/begin").status == 404
    assert env.client.post("/api/session").status == 404


def test_write_without_a_token_is_401_before_anything_else(env: Env) -> None:
    post = add_post(env.home)
    res = env.client.post(f"/api/posts/{post['id']}/approve", token=None, csrf=None, origin=None)
    assert res.status == 401 and res.code == "IDENTITY_UNVERIFIED"


@pytest.mark.parametrize("endpoint", WRITES)
def test_viewer_cannot_write(env: Env, endpoint: str) -> None:
    post = add_post(env.home)
    before = counts(env.home)
    res = env.client.post(f"/api/posts/{post['id']}/{endpoint}", email=VIEWER)
    assert res.status == 403 and res.code == "ROLE_NOT_ALLOWED"
    assert res.body["error"]["next"]
    assert counts(env.home) == before


@pytest.mark.parametrize("endpoint", WRITES)
def test_unmapped_identity_cannot_write(env: Env, endpoint: str) -> None:
    post = add_post(env.home)
    path = f"/api/posts/{post['id']}/{endpoint}"
    res = env.client.post(path, email="stranger@example.com", csrf=None)
    assert res.status == 403 and res.code == "IDENTITY_UNMAPPED"


# --- write paths ---------------------------------------------------------------------------


def test_approve_records_the_console_decision(env: Env) -> None:
    post = add_post(env.home)
    body = seen(env.client, post["id"])
    res = env.client.post(
        f"/api/posts/{post['id']}/approve", body, content_type="application/json; charset=utf-8"
    )
    assert res.status == 200 and res.body["ok"] is True
    assert res.body["status"] == "approved"
    (row,) = approvals(env.home, post["id"])
    assert row["decision"] == "approve" and row["channel"] == "console"
    assert row["verified_identity"] == APPROVER and row["identity_source"] == "access-jwt"
    assert row["decided_by"] == "approver-1" and row["recorded_by"] == "console"
    assert (row["content_version"], row["content_hash"]) == (body["version"], body["hash"])
    assert row["source_message_id"] == "console-approve" and row["approver_words"] == "Approve"
    detail = event_detail(env.home, post["id"], "approve")
    assert detail["identity"] == APPROVER and detail["source"] == "access-jwt"
    assert detail["via"] == "console" and detail["channel"] == "console"
    with open_home(env.home) as (conn, _):
        assert actions.audit(conn, env.home)["ok"] is True  # no console_unverified flag


def test_request_changes_records_what_where_and_instruction(env: Env) -> None:
    post = add_post(env.home)
    body = {
        **seen(env.client, post["id"]),
        "what": "The headline",
        "where": "First line",
        "instruction": "Shorten it",
    }
    res = env.client.post(f"/api/posts/{post['id']}/request-changes", body)
    assert res.status == 200 and res.body["status"] == "changes_requested"
    (row,) = approvals(env.home, post["id"])
    assert row["decision"] == "request_changes" and row["channel"] == "console"
    assert row["verified_identity"] == APPROVER
    for text in ("The headline", "First line", "Shorten it"):
        assert text in row["changes_requested"]
    detail = event_detail(env.home, post["id"], "request-changes")
    assert detail["via"] == "console" and detail["identity"] == APPROVER


def test_request_changes_needs_all_three_fields(env: Env) -> None:
    post = add_post(env.home)
    before = counts(env.home)
    body = {**seen(env.client, post["id"]), "what": "The headline", "instruction": "Shorten it"}
    res = env.client.post(f"/api/posts/{post['id']}/request-changes", body)
    assert res.status == 422 and res.code == "REASON_REQUIRED"
    assert res.headers["x-brandcal-exit"] == "3"
    assert counts(env.home) == before


def test_reschedule_changes_only_the_time(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    post = add_post(env.home)
    cli_approve(capsys, env.home, post)
    body = {**seen(env.client, post["id"]), "new_window": NEW_WINDOW}
    res = env.client.post(f"/api/posts/{post['id']}/reschedule", body)
    assert res.status == 200 and res.body["status"] == "approved"
    row = approvals(env.home, post["id"])[-1]
    assert row["decision"] == "reschedule" and row["channel"] == "console"
    assert row["window"] == NEW_WINDOW and row["verified_identity"] == APPROVER
    detail = event_detail(env.home, post["id"], "reschedule")
    assert detail["via"] == "console" and detail["window"] == NEW_WINDOW
    assert env.client.get(f"/api/posts/{post['id']}").body["window"] == NEW_WINDOW


def test_cancel_records_the_console_decision(env: Env) -> None:
    post = add_post(env.home)
    body = {**seen(env.client, post["id"]), "kind": "version", "reason": "Not needed any more"}
    res = env.client.post(f"/api/posts/{post['id']}/cancel", body)
    assert res.status == 200 and res.body["status"] == "cancelled"
    (row,) = approvals(env.home, post["id"])
    assert row["decision"] == "cancel" and row["channel"] == "console"
    assert row["verified_identity"] == APPROVER and row["identity_source"] == "access-jwt"
    assert row["source_message_id"] == "console-cancel"
    detail = event_detail(env.home, post["id"], "cancel")
    assert detail["kind"] == "version" and detail["via"] == "console"
    assert env.client.get(f"/api/posts/{post['id']}").body["actions"] == []


def test_note_is_recorded_for_the_approver_agent(env: Env) -> None:
    post = add_post(env.home)
    res = env.client.post(f"/api/posts/{post['id']}/note", {"text": "Check the date"})
    assert res.status == 200
    assert "Check the date" in env.client.get(f"/api/posts/{post['id']}").body["notes"]


def test_a_refusal_from_the_action_keeps_its_status_mapping(env: Env) -> None:
    post = add_post(env.home)
    body = seen(env.client, post["id"])
    assert env.client.post(f"/api/posts/{post['id']}/approve", body).status == 200
    again = env.client.post(f"/api/posts/{post['id']}/approve", body)  # double submit
    assert again.status == 409 and again.code == "BAD_TRANSITION"
    assert env.client.post("/api/posts/nope/approve", body).status == 404


# --- stale views (3.3) -----------------------------------------------------------------------


def test_stale_version_is_refused_with_the_current_post(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    post = add_post(env.home)
    old = seen(env.client, post["id"])
    edit = ("part", "edit", post["id"], "1", "Hello again from Example Co")
    code, _ = run(capsys, env.home, *edit, "--as", "writer-1")
    assert code == 0
    before = counts(env.home)
    res = env.client.post(f"/api/posts/{post['id']}/approve", old)
    assert res.status == 409 and res.code == "STALE_APPROVAL"
    assert res.headers["x-brandcal-exit"] == "6"
    current = res.body["current"]
    assert current["content_version"] > old["version"]
    assert current["parts"][0]["text"] == "Hello again from Example Co"
    assert [a["id"] for a in current["actions"]][0] == "approve"
    assert counts(env.home) == before
    # The UI reloads and the new version goes through.
    assert (
        env.client.post(f"/api/posts/{post['id']}/approve", seen(env.client, post["id"])).status
        == 200
    )


def test_stale_window_is_refused_too(env: Env) -> None:
    post = add_post(env.home)
    body = {**seen(env.client, post["id"]), "window": NEW_WINDOW}
    res = env.client.post(f"/api/posts/{post['id']}/approve", body)
    assert res.status == 409 and res.code == "STALE_APPROVAL"
    assert approvals(env.home, post["id"]) == []


@pytest.mark.parametrize("endpoint", ["request-changes", "reschedule", "cancel"])
def test_every_decision_checks_version_hash_and_window(env: Env, endpoint: str) -> None:
    post = add_post(env.home)
    extra = {
        "request-changes": {"what": "a", "where": "b", "instruction": "c"},
        "reschedule": {"new_window": NEW_WINDOW},
        "cancel": {"kind": "idea", "reason": "r"},
    }[endpoint]
    for stale in ({"version": 99}, {"hash": "f" * 64}, {"window": NEW_WINDOW}):
        body = {**seen(env.client, post["id"]), **extra, **stale}
        res = env.client.post(f"/api/posts/{post['id']}/{endpoint}", body)
        # reschedule needs an approved post, so it is refused by state before it can be stale
        assert res.code == ("BAD_TRANSITION" if endpoint == "reschedule" else "STALE_APPROVAL")
    assert approvals(env.home, post["id"]) == []


# --- dev mode (2.5) --------------------------------------------------------------------------


def test_dev_session_is_unverified_and_read_only(dev: Env) -> None:
    body = dev.client.get("/api/session", token=None).body
    assert body["source"] == "dev-unverified" and body["identity"] is None
    assert body["role"] == "viewer" and body["csrf"] is None
    post = add_post(dev.home)
    shown = dev.client.get(f"/api/posts/{post['id']}", token=None).body
    assert all(a["enabled"] is False for a in shown["actions"])
    assert {a["refusal"]["code"] for a in shown["actions"]} == {"IDENTITY_UNVERIFIED"}
    assert dev.client.get("/api/schema", token=None).status == 200


def test_dev_mode_ignores_tokens_and_trusts_nothing(dev: Env) -> None:
    assert dev.client.get("/api/session").body["source"] == "dev-unverified"


@pytest.mark.parametrize("endpoint", WRITES)
def test_dev_mode_refuses_every_write(dev: Env, endpoint: str) -> None:
    post = add_post(dev.home)
    before = counts(dev.home)
    body = seen(dev.client, post["id"])
    for token in (None, "auto"):
        res = dev.client.post(f"/api/posts/{post['id']}/{endpoint}", body, token=token, csrf=None)
        assert res.status == 401 and res.code == "IDENTITY_UNVERIFIED"
    assert counts(dev.home) == before


# --- actions list (1.5) ------------------------------------------------------------------------


def post_with(status: str, **fields: Any) -> dict[str, Any]:
    return {"status": status, "content_hash": "a" * 64, "approvals": [], **fields}


def buttons(post: dict[str, Any], viewer: str | None = "approver") -> dict[str, dict[str, Any]]:
    return {a["id"]: a for a in actions.post_actions(post, CFG, viewer)}


def refusal(post: dict[str, Any], button: str) -> str | None:
    r = buttons(post)[button]["refusal"]
    return None if r is None else str(r["code"])


def test_pending_approval_buttons_and_hold() -> None:
    assert list(buttons(post_with("pending_approval"))) == [
        "approve",
        "request-changes",
        "edit",
        "cancel",
    ]
    held = post_with("pending_approval", hold_until="2999-01-01T00:00:00+00:00", hold_reason="x")
    assert refusal(held, "approve") == "ON_HOLD"
    assert buttons(held)["approve"]["enabled"] is False
    assert refusal(held, "edit") is None


def test_changes_requested_submit_needs_changed_content() -> None:
    asked = [{"decision": "request_changes", "content_hash": "a" * 64}]
    same = post_with("changes_requested", approvals=asked)
    assert list(buttons(same)) == ["edit", "submit", "cancel"]
    assert refusal(same, "submit") == "BAD_TRANSITION"
    changed = post_with("changes_requested", approvals=asked, content_hash="b" * 64)
    assert refusal(changed, "submit") is None


def test_approved_buttons_follow_the_claim_and_the_native_schedule() -> None:
    plain = post_with("approved")
    assert list(buttons(plain)) == ["reschedule", "edit", "cancel"]
    assert buttons(plain)["reschedule"]["label"] == "Change time"
    assert "approval" in buttons(plain)["edit"]["warning"]
    queued = post_with("approved", native_scheduled_at="2026-03-10T09:00:00+03:00")
    assert (refusal(queued, "edit"), refusal(queued, "cancel")) == (
        "EDIT_WHILE_SCHEDULED",
        "NATIVELY_SCHEDULED",
    )
    claimed = post_with("approved", claimed_by="manager-1")
    assert (refusal(claimed, "edit"), refusal(claimed, "cancel")) == (
        "EDIT_WHILE_CLAIMED",
        "CLAIMED",
    )
    assert refusal(claimed, "reschedule") is None


def test_missed_offers_approve_new_time() -> None:
    assert buttons(post_with("missed"))["reschedule"]["label"] == "Approve new time"


@pytest.mark.parametrize("status", ["published", "cancelled"])
def test_closed_posts_have_no_buttons(status: str) -> None:
    assert actions.post_actions(post_with(status), CFG, "approver") == []


def test_viewers_and_unverified_sessions_see_every_button_disabled() -> None:
    for viewer, code in (("viewer", "ROLE_NOT_ALLOWED"), (None, "IDENTITY_UNVERIFIED")):
        acts = actions.post_actions(post_with("pending_approval"), CFG, viewer)
        assert len(acts) == 4
        for a in acts:
            assert a["enabled"] is False and a["refusal"]["code"] == code and a["refusal"]["next"]


# --- the command (2.1, 2.4, 2.5) --------------------------------------------------------------


def serve_cli(
    capsys: pytest.CaptureFixture[str], home: Path, *argv: str
) -> tuple[int, dict[str, Any], str]:
    capsys.readouterr()
    code = cli.main(["--home", str(home), "serve", *argv])
    out = capsys.readouterr()
    return code, json.loads(out.out), out.err


@pytest.fixture
def no_listen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ThreadingHTTPServer, "serve_forever", lambda self, poll_interval=0.5: None)


def test_serve_is_in_the_command_table() -> None:
    assert cli.COMMANDS["serve"][1] == ["admin"]
    assert "--dev-unverified" in cli.COMMANDS["serve"][0]


def test_serve_without_a_serve_block_is_a_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = make_home(tmp_path / "home", monkeypatch)
    (home / "config.json").write_text(json.dumps({**CFG, "serve": None}), encoding="utf-8")
    code, out, _ = serve_cli(capsys, home, "--as", "admin-1", "--dev-unverified", "--port", "0")
    assert code == 2 and out["error"]["code"] == "BAD_ARGS"
    assert "serve" in out["error"]["message"]


def test_serve_is_admin_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = make_home(tmp_path / "home", monkeypatch)
    write_config(home)
    code, out, _ = serve_cli(capsys, home, "--as", "manager-1", "--dev-unverified")
    assert code == 4 and out["error"]["code"] == "ROLE_NOT_ALLOWED"
    code, out, _ = serve_cli(capsys, home, "--dev-unverified")
    assert code == 2 and out["error"]["code"] == "NO_AGENT"


def test_serve_needs_a_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = make_home(tmp_path / "home", monkeypatch)
    write_config(home, serve={**SERVE, "port": None})
    code, out, _ = serve_cli(capsys, home, "--as", "admin-1", "--dev-unverified")
    assert code == 2 and "port" in out["error"]["message"]


def test_verified_mode_needs_the_identity_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = make_home(tmp_path / "home", monkeypatch)
    write_config(home, serve={**SERVE, "identity": {"team_domain": TEAM}})
    code, out, _ = serve_cli(capsys, home, "--as", "admin-1", "--port", "0")
    assert code == 2 and out["error"]["code"] == "BAD_ARGS"
    assert "serve.identity" in out["error"]["message"]


def test_verified_mode_without_the_extra_does_not_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_listen: None,
) -> None:
    home = make_home(tmp_path / "home", monkeypatch)
    write_config(home)
    real = builtins.__import__

    def deny(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.split(".")[0] == "cryptography":
            raise ImportError("blocked for the test")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny)
    code, out, err = serve_cli(capsys, home, "--as", "admin-1", "--port", "0")
    assert code == 2 and out["error"]["code"] == "EXTRA_NOT_INSTALLED"
    assert (
        "crypto extra" in out["error"]["message"] and "--dev-unverified" in out["error"]["message"]
    )
    # Dev mode needs no extra.
    code, out, err = serve_cli(capsys, home, "--as", "admin-1", "--dev-unverified", "--port", "0")
    assert code == 0 and out["ok"] is True


def test_dev_mode_warns_on_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_listen: None,
) -> None:
    home = make_home(tmp_path / "home", monkeypatch)
    write_config(home)
    code, out, err = serve_cli(capsys, home, "--as", "admin-1", "--dev-unverified", "--port", "0")
    assert code == 0 and out["ok"] is True
    assert "UNVERIFIED" in err and "127.0.0.1" in err and "read-only" in err


def test_verified_start_names_the_address_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_listen: None,
) -> None:
    home = make_home(tmp_path / "home", monkeypatch)
    write_config(home)
    code, out, err = serve_cli(capsys, home, "--as", "admin-1", "--port", "0")
    assert code == 0 and "127.0.0.1" in err and "UNVERIFIED" not in err

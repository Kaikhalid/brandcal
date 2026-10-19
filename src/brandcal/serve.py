"""`brandcal serve`: the JSON API for the web UI (UI_SPEC 2).

Binds to 127.0.0.1 only. Every endpoint calls ``actions`` and returns the CLI's JSON; the
server adds only the HTTP frame: identity, origin and CSRF checks, status codes and headers.
Static files wait for U2 (non-/api paths are 404).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import secrets
import sqlite3
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from brandcal import actions, identity, posts
from brandcal.approvals import CONSOLE_SOURCE, Verified
from brandcal.config import display_tz
from brandcal.db import open_db
from brandcal.errors import BrandcalError, ErrorCode
from brandcal.identity import Verifier

HOST = "127.0.0.1"
BODY_LIMIT = 256 * 1024
DEV_SOURCE = "dev-unverified"
ALLOWED_METHODS = "GET, POST"
# Exit code -> HTTP status (UI_SPEC 1.3); IDENTITY_UNVERIFIED is 401.
STATUS = {2: 400, 3: 422, 4: 403, 5: 409, 6: 409, 7: 404, 8: 409}
_KIND_TYPE = {
    "image": "image/png",
    "gif": "image/gif",
    "video": "video/mp4",
    "pdf": "application/pdf",
}
Body = dict[str, Any]


@dataclass(frozen=True)
class Session:
    """Who is asking: a verified email with a role, or the unverified dev session."""

    email: str | None
    role: str  # "approver" or "viewer"
    agent: str | None
    source: str

    @property
    def viewer(self) -> str | None:
        """The role the action list is built for; None when nothing is verified."""
        return self.role if self.source == CONSOLE_SOURCE else None


class App:
    """Settings and per-process secrets shared by all requests."""

    def __init__(
        self, base: Path, cfg: Mapping[str, Any], verifier: Verifier | None, dev: bool
    ) -> None:
        if dev == (verifier is not None):
            raise ValueError("give a verifier, or dev=True, not both and not neither")
        block = cfg.get("serve")
        serve: dict[str, Any] = block if isinstance(block, dict) else {}
        self.base, self.cfg, self.serve = base, cfg, serve
        self.verifier, self.dev = verifier, dev
        self.origins: list[str] = [str(o) for o in serve.get("allowed_origins") or []]
        self.hosts = {urlsplit(o).netloc for o in self.origins}
        self._secret = secrets.token_bytes(32)

    def session(self, token: str | None) -> Session:
        if self.verifier is None:
            return Session(None, "viewer", None, DEV_SOURCE)
        who = identity.resolve(self.serve, self.verifier.verify(token))
        return Session(who.email, who.role, who.agent, CONSOLE_SOURCE)

    def csrf(self, session: Session) -> str | None:
        """A token bound to the identity; dev sessions cannot write, so they get none."""
        if session.email is None:
            return None
        msg = f"{session.email}|{session.source}".encode()
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()


class _Server(ThreadingHTTPServer):
    app: App
    daemon_threads = True


def _refusal(code: ErrorCode, message: str, next_step: str) -> BrandcalError:
    return BrandcalError(code, message, next_step)


def _not_found(what: str) -> BrandcalError:
    return _refusal(
        ErrorCode.NOT_FOUND, f"No such {what}.", "Check the address; see brandcal help."
    )


def _text(body: Body, key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise posts.bad_args(f"{key} is required.", f"Send {key} as non-empty text.")
    return value


def _optional(body: Body, key: str) -> str | None:
    value = body.get(key)
    return value if isinstance(value, str) else None


def _seen(body: Body) -> tuple[int, str, str]:
    """The version, hash and window the UI showed (UI_SPEC 3.3)."""
    version = body.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise posts.bad_args("version must be a whole number.", "Send the version you loaded.")
    return version, _text(body, "hash"), _text(body, "window")


Write = Callable[[sqlite3.Connection, Mapping[str, Any], actions.Identity, str, Body], Any]


def _approve(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], who: actions.Identity, pid: str, b: Body
) -> Any:
    version, hash_, window = _seen(b)
    return actions.approve(
        conn, cfg, who, pid, version, hash_, "console", "console-approve", "Approve",
        seen_window=window,
    )  # fmt: skip


def _request_changes(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], who: actions.Identity, pid: str, b: Body
) -> Any:
    version, hash_, window = _seen(b)
    return actions.request_changes(
        conn, cfg, who, pid, version, hash_, "console-request-changes", "Request changes",
        what=_optional(b, "what"), where=_optional(b, "where"),
        instruction=_optional(b, "instruction"), channel="console", seen_window=window,
    )  # fmt: skip


def _reschedule(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], who: actions.Identity, pid: str, b: Body
) -> Any:
    version, hash_, window = _seen(b)
    return actions.reschedule(
        conn, cfg, who, pid, version, hash_, _text(b, "new_window"), "console-reschedule",
        "Change time", channel="console", seen_window=window,
    )  # fmt: skip


def _cancel(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], who: actions.Identity, pid: str, b: Body
) -> Any:
    return actions.cancel(
        conn, cfg, who, pid, _text(b, "kind"), _text(b, "reason"), "console-cancel", "Cancel",
        channel="console", seen=_seen(b),
    )  # fmt: skip


def _edit(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], who: actions.Identity, pid: str, b: Body
) -> Any:
    fields = b.get("fields")
    if not isinstance(fields, dict) or not all(isinstance(v, str) for v in fields.values()):
        raise posts.bad_args("fields must be an object of text values.", 'Send {"fields": {...}}.')
    return actions.edit(conn, cfg, who, pid, [f"{k}={v}" for k, v in fields.items()])


def _submit(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], who: actions.Identity, pid: str, b: Body
) -> Any:
    return actions.submit(conn, cfg, who, pid)


def _note(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], who: actions.Identity, pid: str, b: Body
) -> Any:
    return actions.note(conn, cfg, who, pid, _text(b, "text"))


WRITES: dict[str, Write] = {
    "approve": _approve,
    "request-changes": _request_changes,
    "reschedule": _reschedule,
    "cancel": _cancel,
    "edit": _edit,
    "submit": _submit,
    "note": _note,
}


def _int_arg(query: Mapping[str, str], key: str) -> int | None:
    if key not in query:
        return None
    try:
        return int(query[key])
    except ValueError:
        raise posts.bad_args(f"{key} must be a whole number.", f"Pass ?{key}=N.") from None


class _Handler(BaseHTTPRequestHandler):
    server: _Server
    timeout = 30  # a stalled client must not hold a thread forever

    def log_message(self, format: str, *args: Any) -> None:
        """No access log: nothing from a request is written anywhere."""

    # -- frame ----------------------------------------------------------------------------

    def _send(self, status: int, payload: bytes, ctype: str, exit_code: int = 0) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Brandcal-Exit", str(exit_code))
        self.send_header("Content-Security-Policy", "default-src 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        if status == 405:
            self.send_header("Allow", ALLOWED_METHODS)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _json(self, status: int, body: Mapping[str, object], exit_code: int = 0) -> None:
        self._send(status, json.dumps(body).encode(), "application/json", exit_code)

    def _refuse(self, err: BrandcalError, extra: Body, status: int | None = None) -> None:
        if status is None:
            unverified = err.code == ErrorCode.IDENTITY_UNVERIFIED
            status = 401 if unverified else STATUS[err.exit_code]
        self._json(status, {**err.to_dict(), **extra}, err.exit_code)

    def _method_not_allowed(self) -> None:
        err = _refusal(
            ErrorCode.BAD_ARGS, f"{self.command} is not allowed.", f"Use {ALLOWED_METHODS}."
        )
        self._refuse(err, {}, 405)

    do_OPTIONS = do_PUT = do_DELETE = do_PATCH = do_HEAD = _method_not_allowed

    def do_GET(self) -> None:
        self._serve()

    def do_POST(self) -> None:
        self._serve()

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        app = self.server.app
        conn = open_db(app.base / "brand.db", display_tz(app.cfg))
        try:
            yield conn
        finally:
            conn.close()

    # -- request flow -----------------------------------------------------------------------

    def _serve(self) -> None:
        extra: Body = {}
        try:
            url = urlsplit(self.path)
            parts = [unquote(p) for p in url.path.split("/")[1:]]
            if parts[0] != "api" or len(parts) < 2:
                raise _not_found("page")
            body = self._read_body() if self.command == "POST" else b""
            session = self.server.app.session(self.headers.get("Cf-Access-Jwt-Assertion"))
            if self.command == "GET":
                self._get(parts[1:], url.query, session)
            else:
                self._post(parts[1:], session, body, extra)
        except BrandcalError as err:
            self._refuse(err, extra)

    def _read_body(self) -> bytes:
        length = self.headers.get("Content-Length", "")
        if not length.isdigit():
            raise posts.bad_args("A Content-Length header is required.", "Send a JSON body.")
        size = int(length)
        if size > BODY_LIMIT:
            self._drain(size)  # so the client can still read the refusal
            raise posts.bad_args(
                f"The body is over {BODY_LIMIT // 1024} KiB.", "Send a smaller request."
            )
        return self.rfile.read(size)

    def _drain(self, size: int) -> None:
        left = min(size, 4 * BODY_LIMIT)
        while left > 0 and (chunk := self.rfile.read(min(left, 65536))):
            left -= len(chunk)

    # -- reads ------------------------------------------------------------------------------

    def _get(self, parts: list[str], query: str, session: Session) -> None:
        app = self.server.app
        q = {k: v[0] for k, v in parse_qs(query).items()}
        out: dict[str, object]
        with self._db() as conn:
            if parts == ["session"]:
                out = {
                    "ok": True,
                    "identity": session.email,
                    "role": session.role,
                    "source": session.source,
                    "csrf": app.csrf(session),
                }
            elif parts == ["schema"]:
                out = actions.ui_schema(conn, app.cfg)
            elif parts == ["posts"]:
                out = actions.list_posts(
                    conn, app.cfg, app.base, q.get("status"), q.get("from"), q.get("to"),
                    q.get("platform"), q.get("closed", "") in ("1", "true"), False,
                )  # fmt: skip
            elif len(parts) == 2 and parts[0] == "posts":
                out = actions.post_detail(conn, app.cfg, parts[1], session.viewer)
            elif parts == ["events"]:
                limit = _int_arg(q, "limit") or actions.EVENTS_LIMIT
                out = actions.events(conn, _int_arg(q, "since"), q.get("post"), None, limit)
            elif len(parts) == 3 and parts[0] == "media":
                return self._media(conn, parts[1], parts[2])
            else:
                raise _not_found("endpoint")
        self._json(200, out)

    def _media(self, conn: sqlite3.Connection, post_id: str, number: str) -> None:
        """The N-th media file of a post, only from inside the data directory."""
        if not number.isdigit() or int(number) < 1:
            raise _not_found("media file")
        posts.load_post(conn, post_id)
        rows = conn.execute(
            "SELECT m.path, m.kind FROM media m JOIN parts p ON p.id = m.part_id"
            " WHERE p.post_id = ? ORDER BY p.pos, m.pos",
            (post_id,),
        ).fetchall()
        if int(number) > len(rows):
            raise _not_found("media file")
        base = self.server.app.base.resolve()
        path = (base / rows[int(number) - 1]["path"]).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise _not_found("media file")
        kind = rows[int(number) - 1]["kind"]
        guess = mimetypes.guess_type(path.name)[0]
        default = _KIND_TYPE[kind]
        same_family = guess is not None and guess.split("/")[0] == default.split("/")[0]
        ctype = guess if same_family and kind != "pdf" and guess else default
        self._send(200, path.read_bytes(), ctype)

    # -- writes -----------------------------------------------------------------------------

    def _post(self, parts: list[str], session: Session, raw: bytes, extra: Body) -> None:
        app = self.server.app
        if session.source != CONSOLE_SOURCE:
            raise _refusal(
                ErrorCode.IDENTITY_UNVERIFIED,
                "This session has no verified identity, so it cannot make changes.",
                "Sign in through Cloudflare Access; --dev-unverified is read-only.",
            )
        origin, host = self.headers.get("Origin"), self.headers.get("Host")
        if origin not in app.origins or host not in app.hosts:
            raise _refusal(
                ErrorCode.BAD_ORIGIN,
                "This request did not come from an allowed origin and host.",
                "Use the site's own address, or ask the admin to check serve.allowed_origins.",
            )
        sent, expected = self.headers.get("X-Brandcal-CSRF") or "", app.csrf(session) or ""
        if not hmac.compare_digest(sent.encode(), expected.encode()):
            raise _refusal(
                ErrorCode.BAD_ORIGIN,
                "The CSRF token is missing or wrong.",
                "Reload the page to get a new one (GET /api/session).",
            )
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise posts.bad_args("Writes must be application/json.", "Send a JSON body.")
        if session.role != "approver" or session.agent is None:
            raise _refusal(
                ErrorCode.ROLE_NOT_ALLOWED,
                "You have read-only access.",
                "Ask the admin to list you in serve.approvers.",
            )
        try:
            body = json.loads(raw)
        except ValueError:
            raise posts.bad_args("The body is not valid JSON.", "Send one JSON object.") from None
        if not isinstance(body, dict):
            raise posts.bad_args("The body must be one JSON object.", "Send one JSON object.")
        if len(parts) != 3 or parts[0] != "posts" or parts[2] not in WRITES:
            raise _not_found("endpoint")
        post_id = parts[1]
        who = actions.Identity(session.agent, Verified(str(session.email), session.source))
        with self._db() as conn:
            try:
                out = WRITES[parts[2]](conn, app.cfg, who, post_id, body)
            except BrandcalError as err:
                if err.code == ErrorCode.STALE_APPROVAL:
                    # UI_SPEC 3.3: the refusal carries the post as it is now.
                    extra["current"] = actions.post_detail(conn, app.cfg, post_id, session.viewer)
                raise
        self._json(200, out)


def make_server(
    base: Path, cfg: Mapping[str, Any], port: int, verifier: Verifier | None, *, dev: bool = False
) -> ThreadingHTTPServer:
    """A server bound to 127.0.0.1 (never anything else). ``verifier`` is None only in dev mode."""
    server = _Server((HOST, port), _Handler)
    try:
        server.app = App(base, cfg, verifier, dev)
    except ValueError:
        server.server_close()
        raise
    return server


def run(base: Path, cfg: Mapping[str, Any], port: int | None, dev: bool) -> dict[str, object]:
    """Check the config, then serve until interrupted."""
    serve = cfg.get("serve")
    if not isinstance(serve, dict):
        raise posts.bad_args(
            "config.json has no serve block.",
            "Add serve (port, allowed_origins, identity, approvers, viewers, console_agent);"
            " see docs/UI_SPEC.md 2.6.",
        )
    chosen = port if port is not None else serve.get("port")
    if not isinstance(chosen, int) or isinstance(chosen, bool) or not 0 <= chosen <= 65535:
        raise posts.bad_args("serve.port is required.", "Set serve.port or pass --port N.")
    verifier = None
    if not dev:
        ident = serve.get("identity")
        ident = ident if isinstance(ident, dict) else {}
        team, aud, minutes = (
            ident.get(k) for k in ("team_domain", "audience", "jwks_cache_minutes")
        )
        if not (isinstance(team, str) and team and isinstance(aud, str) and aud):
            raise posts.bad_args(
                "serve.identity needs team_domain and audience.", "Set them in config.json."
            )
        if not isinstance(minutes, int | float) or isinstance(minutes, bool) or minutes <= 0:
            raise posts.bad_args(
                "serve.identity.jwks_cache_minutes must be a number above 0.",
                "Set it in config.json.",
            )
        origins = serve.get("allowed_origins")
        if not isinstance(origins, list) or not all(isinstance(o, str) for o in origins):
            raise posts.bad_args(
                "serve.allowed_origins must be a list of origins.",
                'For example ["https://brandcal.example.com"].',
            )
        identity.require_crypto()
        verifier = Verifier(team, aud, minutes)
    server = make_server(base, cfg, chosen, verifier, dev=dev)
    if dev:
        print(
            "WARNING: --dev-unverified. No identity is checked: this session is UNVERIFIED and"
            " read-only, and every write is refused.",
            file=sys.stderr,
        )
    print(f"brandcal serve: listening on http://{HOST}:{server.server_address[1]}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return {"ok": True, "stopped": True}

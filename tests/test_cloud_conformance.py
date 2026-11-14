"""Conformance: the same API and CLI scenario against the Python core and the Cloudflare Worker.

Opt-in (needs Node and ``npm ci`` in cloud/): ``BRANDCAL_CLOUD_CONFORMANCE=1 pytest
tests/test_cloud_conformance.py``. One seeded home is copied twice: ``brandcal serve`` runs on
one copy, and the other is exported to a local D1 behind ``wrangler dev``. Every request goes to
both, and the answers must match after the times of day are masked. The CLI part runs the same
commands locally and in remote mode. At the end the two databases must hold the same rows, and the
Worker's copy must pass ``brandcal audit`` (hash chains, console identities).
"""

from __future__ import annotations

import contextlib
import http.client
import http.server
import io
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from conftest import PLATFORMS
from jwt_env import APPROVER, AUD, TEAM, VIEWER, FakeJwks, Signer, claims, service_claims
from ui_env import CFG, DATA

from brandcal import audit, cli, remote, serve
from brandcal.config import display_tz
from brandcal.db import open_db
from brandcal.identity import Verifier

pytestmark = pytest.mark.skipif(
    not os.environ.get("BRANDCAL_CLOUD_CONFORMANCE"),
    reason="set BRANDCAL_CLOUD_CONFORMANCE=1 (needs Node and npm ci in cloud/)",
)

ROOT = Path(__file__).resolve().parents[1]
CLOUD = ROOT / "cloud"
ORIGIN = "https://brandcal.example.com"
HOST = "brandcal.example.com"
CLIENT_ID = "example-client-id.access"
TIME_KEYS = {"at", "decided_at", "updated_at", "closed_at", "published_at", "claim_expires"}
HASH_KEYS = {"row_hash", "prev_hash"}
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}(?= )")
SERVE_CFG: dict[str, Any] = {
    **CFG["serve"],
    "allowed_origins": [ORIGIN],
    "identity": {"team_domain": TEAM, "audience": AUD, "jwks_cache_minutes": 5},
    "approvers": {APPROVER: "approver-1"},
    "viewers": [VIEWER],
}
FUTURE = "2099-01-01T09:00:00+03:00"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def cli_run(home: Path | None, *argv: str, stdin: str = "") -> tuple[int, dict[str, Any]]:
    out = io.StringIO()
    old = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out):
            code = cli.main(([] if home is None else ["--home", str(home)]) + list(argv))
    finally:
        sys.stdin = old
    return code, json.loads(out.getvalue())


def seed(home: Path) -> None:
    """Example Co posts in every state the console acts on."""
    home.mkdir(parents=True)
    cfg = {**CFG, "serve": SERVE_CFG, "campaigns": ["spring-launch"], "pillars": ["product"]}
    (home / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (home / "platforms.json").write_text(json.dumps(PLATFORMS), encoding="utf-8")
    assert cli_run(home, "init", "--as", "admin-1")[0] == 0

    def add(**extra: Any) -> dict[str, Any]:
        code, out = cli_run(home, "add", "--as", "writer-1", stdin=json.dumps({**DATA, **extra}))
        assert code == 0, out
        return out

    def card(cmd: str, post: dict[str, Any], *more: str) -> None:
        code, out = cli_run(
            home,
            cmd,
            post["id"],
            "--version",
            str(post["version"]),
            "--hash",
            post["hash"],
            "--msg",
            "m1",
            "--words",
            "Yes",
            "--as",
            "manager-1",
            *more,
        )
        assert code == 0, out

    w = "2026-03-1{d}T09:00:00+03:00/2026-03-1{d}T10:00:00+03:00"
    add(slug="one", window=w.format(d=1))  # p0001 pending
    card("approve", add(slug="two", window=w.format(d=2)), "--channel", "card")  # p0002 approved
    p3 = add(slug="three", window=w.format(d=3), first_comment="See [link]")
    card("request-changes", p3)  # p0003 changes_requested
    add(
        slug="four",
        post_type="thread",
        window=w.format(d=4),
        parts=[{"text": "One https://example.com/a"}, {"text": "Two"}],
    )
    add(slug="five", window=w.format(d=5), hold_until=FUTURE, hold_reason="legal")  # p0005 held
    add(slug="six", window=w.format(d=6), campaign="other")  # p0006 for cancel
    card("approve", add(slug="seven", window=w.format(d=7)), "--channel", "card")  # p0007


def export_sql(home: Path, out: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(CLOUD / "scripts" / "d1_export.py"),
            str(home),
            str(out),
            "--service-token",
            CLIENT_ID,
        ],
        check=True,
    )


class _Jwks(http.server.BaseHTTPRequestHandler):
    body = b""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *a: Any) -> None:
        pass


@dataclass
class Stack:
    signer: Signer
    py_port: int
    cf_port: int
    py_home: Path
    tmp: Path

    def token(self, email: str = APPROVER) -> str:
        return self.signer.token(claims(email=email))

    def service(self) -> str:
        return self.signer.token(service_claims())


@pytest.fixture(scope="module")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    tmp = tmp_path_factory.mktemp("cloud")
    saved = {
        k: os.environ.pop(k, None)
        for k in ("BRANDCAL_HOME", "BRANDCAL_AGENT", "BRANDCAL_TZ", remote.ENV_URL)
    }
    base = tmp / "seed"
    seed(base)
    py_home = tmp / "py"
    shutil.copytree(base, py_home)
    export_sql(base, tmp / "seed.sql")
    signer = Signer()
    _Jwks.body = json.dumps(signer.jwks()).encode()
    jwks = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Jwks)
    threading.Thread(target=jwks.serve_forever, daemon=True).start()
    cf_port = free_port()
    config = CLOUD / "wrangler.test.jsonc"
    config.write_text(
        json.dumps(
            {
                "name": "brandcal-test",
                "main": "src/index.ts",
                "compatibility_date": "2026-08-22",
                "assets": {
                    "directory": "../src/brandcal/web_next",
                    "binding": "ASSETS",
                    "run_worker_first": True,
                    "html_handling": "none",
                    "not_found_handling": "none",
                },
                "d1_databases": [
                    {
                        "binding": "DB",
                        "database_name": "brandcal-test",
                        "database_id": "00000000-0000-0000-0000-000000000001",
                    }
                ],
                "dev": {"host": HOST, "upstream_protocol": "https"},
                "vars": {
                    "ENVIRONMENT": "test",
                    "CSRF_SECRET": "test-csrf-secret-not-real",
                    "CERTS_URL": f"http://127.0.0.1:{jwks.server_address[1]}/certs",
                },
            }
        ),
        encoding="utf-8",
    )
    state = tmp / "state"
    env = {**os.environ, "CI": "1", "WRANGLER_SEND_METRICS": "false"}
    wrangler = ["npx", "wrangler"]
    subprocess.run(
        [
            *wrangler,
            "d1",
            "execute",
            "DB",
            "--local",
            "--persist-to",
            str(state),
            "-c",
            str(config),
            "--file",
            str(tmp / "seed.sql"),
        ],
        cwd=CLOUD,
        env=env,
        check=True,
        capture_output=True,
    )
    log = (tmp / "wrangler.log").open("w")
    proc = subprocess.Popen(
        [
            *wrangler,
            "dev",
            "-c",
            str(config),
            "--local",
            "--ip",
            "127.0.0.1",
            "--port",
            str(cf_port),
            "--persist-to",
            str(state),
        ],
        cwd=CLOUD,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    py_cfg = json.loads((py_home / "config.json").read_text(encoding="utf-8"))
    verifier = Verifier(TEAM, AUD, 5, fetch=FakeJwks(signer))
    py = serve.make_server(py_home, py_cfg, 0, verifier)
    threading.Thread(target=py.serve_forever, daemon=True).start()
    try:
        deadline = time.time() + 90
        while True:
            try:
                socket.create_connection(("127.0.0.1", cf_port), timeout=1).close()
                break
            except OSError:
                if time.time() > deadline or proc.poll() is not None:
                    raise RuntimeError((tmp / "wrangler.log").read_text()) from None
                time.sleep(0.5)
        time.sleep(1.0)
        yield Stack(signer, int(py.server_address[1]), cf_port, py_home, tmp)
    finally:
        py.shutdown()
        jwks.shutdown()
        proc.terminate()
        proc.wait(timeout=20)
        config.unlink(missing_ok=True)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def call(
    port: int, method: str, path: str, headers: dict[str, str], body: bytes | None = None
) -> tuple[int, str, dict[str, Any]]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.request(method, path, body=body, headers=headers)
        res = conn.getresponse()
        raw = res.read()
        return res.status, res.getheader("X-Brandcal-Exit") or "", json.loads(raw)
    finally:
        conn.close()


def mask(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in TIME_KEYS and isinstance(v, str):
                out[k] = "<time>"
            elif k in HASH_KEYS and isinstance(v, str):
                out[k] = "<hash>"
            elif k == "csrf" and isinstance(v, str):
                out[k] = "<csrf>"
            elif k == "notes" and isinstance(v, str):
                out[k] = STAMP.sub("<time>", v)
            else:
                out[k] = mask(v)
        return out
    if isinstance(value, list):
        return [mask(v) for v in value]
    return value


class Both:
    def __init__(self, s: Stack) -> None:
        self.s = s

    def get(
        self, path: str, email: str | None = APPROVER, token: str | None = None
    ) -> dict[str, Any]:
        h = {"Host": HOST}
        if token is not None:
            h["Cf-Access-Jwt-Assertion"] = token
        elif email is not None:
            h["Cf-Access-Jwt-Assertion"] = self.s.token(email)
        return self._both("GET", path, lambda port: h, None)

    def post(
        self,
        path: str,
        body: Any,
        email: str = APPROVER,
        *,
        csrf: bool = True,
        origin: str = ORIGIN,
        ctype: str = "application/json",
    ) -> dict[str, Any]:
        raw = json.dumps(body).encode()

        def headers(port: int) -> dict[str, str]:
            token = self.s.token(email)
            h = {
                "Host": HOST,
                "Origin": origin,
                "Content-Type": ctype,
                "Cf-Access-Jwt-Assertion": token,
            }
            if csrf:
                _, _, sess = call(
                    port, "GET", "/api/session", {"Host": HOST, "Cf-Access-Jwt-Assertion": token}
                )
                if sess.get("csrf"):
                    h["X-Brandcal-CSRF"] = sess["csrf"]
            return h

        return self._both("POST", path, headers, raw)

    def _both(self, method: str, path: str, headers: Any, body: bytes | None) -> dict[str, Any]:
        py = call(self.s.py_port, method, path, headers(self.s.py_port), body)
        cf = call(self.s.cf_port, method, path, headers(self.s.cf_port), body)
        what = f"{method} {path}"
        assert (cf[0], cf[1]) == (py[0], py[1]), f"{what}: {cf[:2]} != {py[:2]}\n{cf[2]}\n{py[2]}"
        worker, python = json.dumps(mask(cf[2]), indent=1), json.dumps(mask(py[2]), indent=1)
        assert mask(cf[2]) == mask(py[2]), f"{what}:\nworker={worker}\npython={python}"
        return py[2]


def seen(b: Both, pid: str) -> dict[str, Any]:
    d = b.get(f"/api/posts/{pid}")
    return {"version": d["content_version"], "hash": d["content_hash"][:8], "window": d["window"]}


def rows(db: Path) -> dict[str, list[dict[str, Any]]]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return {
            t: [dict(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY id")]  # noqa: S608
            for t in remote.SYNC_TABLES
        }
    finally:
        conn.close()


def worker_rows(s: Stack, folder: Path) -> tuple[dict[str, list[dict[str, Any]]], Path]:
    _, _, snap = call(
        s.cf_port,
        "GET",
        "/api/sync/snapshot",
        {"Host": HOST, "Cf-Access-Jwt-Assertion": s.service()},
    )
    assert snap["ok"] is True, snap
    folder.mkdir()
    remote.build_home(snap, folder)
    return rows(folder / "brand.db"), folder


def test_api_and_cli_conform(stack: Stack, tmp_path: Path) -> None:
    b = Both(stack)
    # Reads and identity.
    b.get("/api/session")
    b.get("/api/session", VIEWER)
    b.get("/api/session", None)
    b.get("/api/session", token="not.a.token")
    b.get("/api/session", "stranger@example.org")
    b.get("/api/schema")
    for q in (
        "",
        "?closed=1",
        "?status=approved",
        "?from=2026-03-12&to=2026-03-14",
        "?platform=linkedin",
        "?from=bad",
        "?status=",
    ):
        b.get(f"/api/posts{q}")
    for pid in ("p0001", "p0002", "p0003", "p0005", "p9999"):
        b.get(f"/api/posts/{pid}")
    b.get("/api/posts/p0001", VIEWER)
    b.get("/api/posts/p0002/versions")
    for q in ("", "?since=2&limit=3", "?post=p0002", "?limit=x", "?since=-1", "?post=p9999"):
        b.get(f"/api/events{q}")
    b.get("/api/nothing")
    b.get("/api/media/p0001/1")
    # Writes and refusals.
    b.post("/api/posts/p0001/approve", seen(b, "p0001"))
    b.post("/api/posts/p0001/approve", seen(b, "p0001"))
    b.post("/api/posts/p0005/approve", seen(b, "p0005"))
    b.post("/api/posts/p0004/approve", {**seen(b, "p0004"), "version": 9})
    b.post("/api/posts/p0004/approve", {**seen(b, "p0004"), "window": "x"})
    b.post("/api/posts/p0004/request-changes", {**seen(b, "p0004"), "what": "Tone"})
    b.post(
        "/api/posts/p0004/request-changes",
        {**seen(b, "p0004"), "what": "Tone", "where": "Part 1", "instruction": "Softer"},
    )
    b.post("/api/posts/p0003/submit", {})
    b.post(
        "/api/posts/p0003/edit", {"parts": {"1": "Better text"}, "fields": {"first_comment": ""}}
    )
    b.post("/api/posts/p0003/submit", {})
    b.post("/api/posts/p0003/submit", {})
    b.post("/api/posts/p0007/edit", {"fields": {"first_comment": "Read more", "title": "Seven"}})
    b.post(
        "/api/posts/p0002/reschedule",
        {**seen(b, "p0002"), "new_window": "2026-03-20T09:00:00+03:00/2026-03-20T11:00:00+03:00"},
    )
    b.post("/api/posts/p0002/reschedule", {**seen(b, "p0002"), "new_window": "bad"})
    b.post("/api/posts/p0006/cancel", {**seen(b, "p0006"), "kind": "idea"})
    b.post("/api/posts/p0006/cancel", {**seen(b, "p0006"), "kind": "idea", "reason": "Duplicate"})
    b.post("/api/posts/p0006/cancel", {**seen(b, "p0006"), "kind": "idea", "reason": "Again"})
    b.post("/api/posts/p0001/note", {"text": "Looks good"})
    b.post("/api/posts/p0001/edit", {"fields": {"colour": "red"}})
    b.post("/api/posts/p0001/edit", {})
    b.post(
        "/api/posts/p0001/edit",
        {"fields": {"window": "2026-03-21T09:00:00+03:00/2026-03-21T10:00:00+03:00"}},
    )
    b.post("/api/posts/p0004/edit", {"parts": {"3": "x"}})
    b.post("/api/posts/p0001/note", {"text": "x"}, csrf=False)
    b.post("/api/posts/p0001/note", {"text": "x"}, origin="https://evil.example.org")
    b.post("/api/posts/p0001/note", {"text": "x"}, VIEWER)
    b.post("/api/posts/p0001/note", {"text": "x"}, ctype="text/plain")
    b.post("/api/posts/p0001/frobnicate", {})
    for pid in ("p0001", "p0002", "p0003", "p0004", "p0006", "p0007"):
        b.get(f"/api/posts/{pid}")
        b.get(f"/api/posts/{pid}/versions")
    b.get("/api/events?limit=500")
    b.get("/api/posts?closed=1")

    # The CLI: the same commands locally (Python serve's home) and in remote mode (the Worker).
    def both_cli(*argv: str, stdin: str = "") -> dict[str, Any]:
        local = cli_run(stack.py_home, *argv, stdin=stdin)
        os.environ[remote.ENV_URL] = f"http://127.0.0.1:{stack.cf_port}"
        os.environ[remote.ENV_TEST_JWT] = stack.service()
        try:
            far = cli_run(None, *argv, stdin=stdin)
        finally:
            os.environ.pop(remote.ENV_URL)
            os.environ.pop(remote.ENV_TEST_JWT)
        assert far[0] == local[0], f"{argv}: exit {far[0]} != {local[0]}\n{far[1]}\n{local[1]}"
        assert mask(far[1]) == mask(local[1]), f"{argv}:\nremote={far[1]}\nlocal={local[1]}"
        return local[1]

    for argv in (
        ["list"],
        ["list", "--closed"],
        ["show", "p0001"],
        ["show", "p0007", "--log"],
        ["today"],
        ["events", "--since", "0"],
        ["next", "--as", "manager-1"],
    ):
        both_cli(*argv)
    added = both_cli("add", "--as", "writer-1", stdin=json.dumps({**DATA, "slug": "eight"}))
    both_cli("edit", added["id"], "title=Eight", "--as", "writer-1")
    fresh = both_cli("show", added["id"])
    both_cli(
        "approve",
        added["id"],
        "--version",
        str(fresh["content_version"]),
        "--hash",
        fresh["content_hash"][:8],
        "--channel",
        "card",
        "--msg",
        "m9",
        "--words",
        "Yes",
        "--as",
        "manager-1",
    )
    both_cli("note", added["id"], "Ready", "--as", "manager-1")
    both_cli(
        "published", "p0002", "https://www.linkedin.com/feed/update/example-1", "--as", "manager-1"
    )
    both_cli("sweep", "--as", "system")
    both_cli(
        "approve",
        "p0001",
        "--version",
        "1",
        "--hash",
        "deadbeef",
        "--channel",
        "card",
        "--msg",
        "m",
        "--words",
        "Yes",
        "--as",
        "manager-1",
    )
    both_cli("list", "--closed")

    # Same rows in both databases (times and event hashes masked); the Worker's copy audits clean.
    want = rows(stack.py_home / "brand.db")
    got, folder = worker_rows(stack, tmp_path / "worker")
    assert mask(got) == mask(want)
    conn = open_db(folder / "brand.db", display_tz(CFG))
    try:
        report = audit.audit(conn, folder)
    finally:
        conn.close()
    assert report["ok"] is True, report["flags"]
    assert report["checked"]["events"] == len(want["events"])


def test_static_files_conform(stack: Stack) -> None:
    """The built UI: same status, type and per-page Content-Security-Policy as brandcal serve."""
    for path in ("/", "/posts/", "/posts", "/needs-you/", "/manifest.webmanifest",
                 "/apple-touch-icon.png", "/csp.json", "/.well-known/x", "/nope.html",
                 "/%2e%2e/etc"):  # fmt: skip
        got = []
        for port in (stack.py_port, stack.cf_port):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            conn.request("GET", path, headers={"Host": HOST})
            res = conn.getresponse()
            body = res.read()
            got.append((res.status, res.getheader("Content-Type"),
                        res.getheader("Content-Security-Policy"), res.getheader("Location"),
                        len(body) if res.status == 200 else None))  # fmt: skip
            conn.close()
        assert got[1] == got[0], f"{path}: worker {got[1]} != python {got[0]}"

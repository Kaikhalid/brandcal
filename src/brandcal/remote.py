"""Remote mode: the CLI against brandcal on Cloudflare (D1_MIGRATION.md 5).

When ``BRANDCAL_REMOTE`` holds the site's address, every command runs here, with the full Python
core, on a fresh local copy of the calendar pulled from the Worker; the rows it changed are then
pushed back together with the generation the copy was taken at. If anyone wrote in between, the
push is refused and the command runs again on a new copy (up to three times). The Worker checks
what it is sent (only calendar tables, append-only events and approvals, unbroken hash chains,
no console decisions), so the output and exit code are those of the local command.

The Access service token comes from ``BRANDCAL_ACCESS_CLIENT_ID`` and
``BRANDCAL_ACCESS_CLIENT_SECRET``. It is only ever sent as request headers: never printed,
logged or written to a file.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from importlib import resources
from pathlib import Path
from typing import Any

from brandcal.config import display_tz
from brandcal.db import open_db
from brandcal.errors import EXIT_CODES, BrandcalError, ErrorCode

ENV_URL = "BRANDCAL_REMOTE"
ENV_ID = "BRANDCAL_ACCESS_CLIENT_ID"
ENV_SECRET = "BRANDCAL_ACCESS_CLIENT_SECRET"
ENV_TEST_JWT = "BRANDCAL_TEST_ACCESS_JWT"  # tests only, and only for an http://127.0.0.1 Worker
# Commands that read or write files on this machine have no remote meaning.
LOCAL_ONLY = frozenset(
    {"init", "migrate", "backup", "export", "archive", "serve", "relay", "media", "render"}
)
SYNC_TABLES = ("posts", "parts", "media", "approvals", "events")
FIXED_TABLES = ("agents", "platforms", "transitions", "archive_lock")
LOAD_ORDER = FIXED_TABLES + SYNC_TABLES
GENERATED = {"posts": ("window_start_utc", "window_end_utc")}
APPEND_ONLY = ("approvals", "events")
TRIES = 3
TIMEOUT = 30

Rows = dict[str, dict[Any, dict[str, Any]]]


def enabled() -> bool:
    return bool(os.environ.get(ENV_URL, "").strip())


def _fail(message: str, next_step: str = "") -> BrandcalError:
    return BrandcalError(ErrorCode.INTERNAL, message, next_step)


class Client:
    """GET and POST JSON to the Worker with the Access service-token headers."""

    def __init__(self) -> None:
        url = os.environ.get(ENV_URL, "").strip().rstrip("/")
        if not url.startswith("https://") and not url.startswith("http://127.0.0.1"):
            raise BrandcalError(
                ErrorCode.BAD_ARGS, f"{ENV_URL} must be an https:// address.", "Fix the setting."
            )
        cid, secret = os.environ.get(ENV_ID, ""), os.environ.get(ENV_SECRET, "")
        test_jwt = os.environ.get(ENV_TEST_JWT, "") if url.startswith("http://127.0.0.1") else ""
        if test_jwt:
            # Tests against a local Worker (no Access in front): send a signed test token.
            self.url = url
            self._headers = {"Cf-Access-Jwt-Assertion": test_jwt, "Accept": "application/json"}
            return
        if not cid or not secret:
            raise BrandcalError(
                ErrorCode.SECRET_UNAVAILABLE,
                "Remote mode needs the Access service token in the environment.",
                f"Set {ENV_ID} and {ENV_SECRET}.",
            )
        self.url = url
        self._headers = {
            "CF-Access-Client-Id": cid,
            "CF-Access-Client-Secret": secret,
            "Accept": "application/json",
            "User-Agent": "brandcal-remote",
        }

    def call(
        self, method: str, path: str, body: object | None = None
    ) -> tuple[int, dict[str, Any]]:
        data = None if body is None else json.dumps(body).encode()
        headers = dict(self._headers)
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as res:  # noqa: S310 (https checked)
                status, raw = res.status, res.read()
        except urllib.error.HTTPError as err:
            status, raw = err.code, err.read()
        except (urllib.error.URLError, OSError) as err:
            raise _fail(
                f"The remote calendar could not be reached ({type(err).__name__}).",
                "Check the network and BRANDCAL_REMOTE, then try again.",
            ) from None
        try:
            out = json.loads(raw)
        except ValueError:
            raise _fail(
                f"The remote calendar sent a non-JSON answer (HTTP {status}).",
                "Check that the service token is allowed by the Access application.",
            ) from None
        if not isinstance(out, dict):
            raise _fail(f"The remote calendar sent an unexpected answer (HTTP {status}).")
        return status, out


def _refusal(out: dict[str, Any]) -> BrandcalError:
    raw = out.get("error")
    err: dict[str, Any] = raw if isinstance(raw, dict) else {}
    code = str(err.get("code", "INTERNAL"))
    known = ErrorCode.__members__.get(code, ErrorCode.INTERNAL)
    return BrandcalError(known, str(err.get("message", "")), str(err.get("next", "")))


def snapshot(client: Client) -> dict[str, Any]:
    status, out = client.call("GET", "/api/sync/snapshot")
    if status != 200 or out.get("ok") is not True:
        raise _refusal(out)
    return out


def build_home(snap: dict[str, Any], folder: Path) -> Path:
    """A brandcal home in ``folder`` holding the snapshot: config.json and brand.db."""
    cfg = snap.get("config") or {}
    (folder / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    conn = open_db(folder / "brand.db", display_tz(cfg))
    try:
        schema = resources.files("brandcal").joinpath("schema.sql").read_text(encoding="utf-8")
        conn.executescript(schema)
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")]
        conn.execute("BEGIN")
        for name in names:
            conn.execute(f'DROP TRIGGER "{name}"')
        for table in FIXED_TABLES:
            conn.execute(f"DELETE FROM {table}")  # noqa: S608 (fixed names)
        tables = snap.get("tables") or {}
        for table in LOAD_ORDER:
            skip = GENERATED.get(table, ())
            for row in tables.get(table) or []:
                cols = [c for c in row if c not in skip]
                marks = ", ".join("?" for _ in cols)
                quoted = ", ".join(f'"{c}"' for c in cols)
                conn.execute(
                    f"INSERT INTO {table} ({quoted}) VALUES ({marks})",  # noqa: S608
                    [row[c] for c in cols],
                )
        conn.execute("COMMIT")
        conn.executescript(schema)  # recreates the triggers (CREATE ... IF NOT EXISTS)
    finally:
        conn.close()
    return folder


def read_rows(db: Path) -> Rows:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        out: Rows = {}
        for table in LOAD_ORDER:
            skip = GENERATED.get(table, ())
            rows = {}
            for r in conn.execute(f"SELECT * FROM {table}"):  # noqa: S608
                row = {k: r[k] for k in r.keys() if k not in skip}  # noqa: SIM118
                key = row.get("id", tuple(row.values()))
                rows[key] = row
            out[table] = rows
        return out
    finally:
        conn.close()


def diff(before: Rows, after: Rows) -> dict[str, dict[str, list[Any]]]:
    """The row changes of one command, in the shape POST /api/sync/apply takes."""
    for table in FIXED_TABLES:
        if before[table] != after[table]:
            raise BrandcalError(
                ErrorCode.ROLE_NOT_ALLOWED,
                f"Remote mode cannot change {table}.",
                "Agents, platforms and config change through the admin import.",
            )
    changes: dict[str, dict[str, list[Any]]] = {}
    for table in SYNC_TABLES:
        old, new = before[table], after[table]
        changed = [row for key, row in new.items() if old.get(key) != row]
        gone = [key for key in old if key not in new]
        if not changed and not gone:
            continue
        if table in APPEND_ONLY:
            if gone or any(key in old for key, row in new.items() if old.get(key) != row):
                raise BrandcalError(ErrorCode.APPEND_ONLY, f"{table} are append-only.")
            changes[table] = {"insert": sorted(changed, key=lambda r: r["id"])}
        else:
            changes[table] = {"upsert": changed, "delete": sorted(gone)}
    return changes


def pull(argv: Sequence[str]) -> int:
    """``brandcal pull --out PATH``: the remote calendar as a local brand.db, for reading."""
    try:
        if len(argv) != 2 or argv[0] != "--out":
            raise BrandcalError(ErrorCode.BAD_ARGS, "Usage: brandcal pull --out PATH", "")
        target = Path(argv[1])
        snap = snapshot(Client())
        with tempfile.TemporaryDirectory(prefix="brandcal-pull-") as tmp:
            build_home(snap, Path(tmp))
            part = target.with_name(target.name + ".part")
            shutil.copyfile(Path(tmp) / "brand.db", part)
            os.chmod(part, 0o600)
            os.replace(part, target)
        result: dict[str, object] = {"ok": True, "db": str(target), "gen": snap.get("gen")}
        code = 0
    except BrandcalError as err:
        result, code = err.to_dict(), err.exit_code
    print(json.dumps(result))
    return code


def main(argv: Sequence[str], local_main: Callable[[Sequence[str]], int]) -> int:
    """Run one CLI command in remote mode; prints exactly what the local command printed."""
    from brandcal.cli import build_parser  # local import: cli imports this module

    args_list = list(argv)
    if args_list[:1] == ["pull"]:
        return pull(args_list[1:])
    try:
        args = build_parser().parse_args(args_list)
        command = args.command or "help"
        if command in ("help", "schema"):
            return local_main(args_list)
        if args.home:
            raise BrandcalError(
                ErrorCode.BAD_ARGS, "--home cannot be used in remote mode.", f"Unset {ENV_URL}."
            )
        if command in LOCAL_ONLY:
            raise BrandcalError(
                ErrorCode.BAD_ARGS,
                f"'{command}' works on local files and is not available in remote mode.",
                "Backups are the Worker's daily snapshot and D1 Time Travel (D1_MIGRATION.md 6).",
            )
        client = Client()
    except BrandcalError as err:
        print(json.dumps(err.to_dict()))
        return err.exit_code
    stdin = sys.stdin.read() if command == "add" else ""
    saved_home = os.environ.get("BRANDCAL_HOME")
    try:
        for _ in range(TRIES):
            snap = snapshot(client)
            with tempfile.TemporaryDirectory(prefix="brandcal-remote-") as tmp:
                home = build_home(snap, Path(tmp))
                before = read_rows(home / "brand.db")
                os.environ["BRANDCAL_HOME"] = str(home)
                out = io.StringIO()
                old_stdin = sys.stdin
                sys.stdin = io.StringIO(stdin)
                try:
                    with contextlib.redirect_stdout(out):
                        code = local_main(args_list)
                finally:
                    sys.stdin = old_stdin
                changes = diff(before, read_rows(home / "brand.db"))
            if not changes:
                sys.stdout.write(out.getvalue())
                return code
            status, res = client.call(
                "POST", "/api/sync/apply", {"base_gen": snap.get("gen"), "changes": changes}
            )
            if status == 409 and (res.get("error") or {}).get("code") == "CONFLICT":
                continue
            if status != 200 or res.get("ok") is not True:
                raise _refusal(res)
            sys.stdout.write(out.getvalue())
            return code
        raise _fail("The remote calendar kept changing; nothing was saved.", "Try again.")
    except BrandcalError as err:
        print(json.dumps(err.to_dict()))
        return int(EXIT_CODES.get(err.code, 9))
    finally:
        if saved_home is None:
            os.environ.pop("BRANDCAL_HOME", None)
        else:
            os.environ["BRANDCAL_HOME"] = saved_home

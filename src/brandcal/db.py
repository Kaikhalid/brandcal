"""SQLite connection, schema set-up and error translation (SPEC 5.3)."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, tzinfo
from importlib import resources
from pathlib import Path

from brandcal.errors import BrandcalError, ErrorCode
from brandcal.events import row_hash
from brandcal.timefmt import format_time
from brandcal.transitions import TRANSITIONS

_TRIGGER_MESSAGE = re.compile(r"([A-Z][A-Z_]+): (.*)", re.DOTALL)


def open_db(path: Path, tz: tzinfo) -> sqlite3.Connection:
    """Open the database with the pragmas and SQL functions the schema relies on."""
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.create_function("bc_now", 0, lambda: format_time(datetime.now(tz)), deterministic=False)
    conn.create_function("bc_row_hash", 10, row_hash, deterministic=True)
    return conn


def init_db(
    conn: sqlite3.Connection, agents: list[dict[str, str]], platforms: dict[str, dict[str, object]]
) -> None:
    """Create the schema if needed, sync the transitions and add missing agents and platforms.

    The ``system`` agent is always present: triggers write events as ``system``.
    """
    schema = resources.files("brandcal").joinpath("schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    with transaction(conn):
        conn.execute("DELETE FROM transitions")
        conn.executemany(
            "INSERT INTO transitions (from_status, to_status, roles) VALUES (?, ?, ?)",
            [(f, t, ",".join(roles)) for f, t, roles in TRANSITIONS],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO agents (id, role) VALUES (?, ?)",
            [("system", "system")] + [(a["id"], a["role"]) for a in agents],
        )
        conn.executemany(
            "INSERT OR IGNORE INTO platforms (id, limits) VALUES (?, ?)",
            [(pid, json.dumps(limits, sort_keys=True)) for pid, limits in platforms.items()],
        )


def translate(exc: sqlite3.DatabaseError) -> BrandcalError:
    """Map a trigger's 'CODE: message' to that ErrorCode; anything else is BAD_ARGS."""
    text = str(exc)
    match = _TRIGGER_MESSAGE.fullmatch(text)
    if match and match[1] in ErrorCode.__members__:
        return BrandcalError(ErrorCode[match[1]], match[2])
    return BrandcalError(ErrorCode.BAD_ARGS, text)


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE ... COMMIT, rolling back and translating SQLite errors on failure."""
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException as exc:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        if isinstance(exc, sqlite3.DatabaseError):
            raise translate(exc) from exc
        raise

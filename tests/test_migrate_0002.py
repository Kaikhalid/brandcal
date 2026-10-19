"""Schema version mechanism and migration 0002 (UI_SPEC 3.2): the console approval channel."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

import pytest
from conftest import AGENTS, PLATFORMS, add_approval, make_post
from ui_env import UI_AGENTS

from brandcal.db import init_db, open_db
from brandcal.errors import BrandcalError
from brandcal.migrations import LATEST
from brandcal.transitions import TRANSITIONS

V1_APPROVALS = """
CREATE TABLE approvals (
  id INTEGER PRIMARY KEY,
  post_id TEXT NOT NULL REFERENCES posts(id),
  decision TEXT NOT NULL CHECK (decision IN ('approve','request_changes','cancel','reschedule')),
  content_version INTEGER NOT NULL, content_hash TEXT NOT NULL,
  window TEXT NOT NULL,
  decided_by  TEXT NOT NULL REFERENCES agents(id),
  channel     TEXT NOT NULL CHECK (channel IN ('card','writer-session','legacy')),
  relayed_by  TEXT NOT NULL REFERENCES agents(id),
  recorded_by TEXT NOT NULL REFERENCES agents(id),
  source_message_id TEXT NOT NULL,
  approver_words TEXT NOT NULL,
  changes_requested TEXT,
  decided_at TEXT NOT NULL,
  signature TEXT
);
CREATE TRIGGER approvals_no_update BEFORE UPDATE ON approvals
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY: approvals are append-only'); END;
CREATE TRIGGER approvals_no_delete BEFORE DELETE ON approvals
WHEN (SELECT active FROM archive_lock WHERE id = 1) IS NOT 1
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY: approvals can only be deleted by an archive run'); END;
CREATE TRIGGER approvals_roles BEFORE INSERT ON approvals
BEGIN
  SELECT RAISE(ABORT, 'ROLE_NOT_ALLOWED: decided_by must be an approver')
    WHERE NOT EXISTS (SELECT 1 FROM agents WHERE id = NEW.decided_by AND role = 'approver');
  SELECT RAISE(ABORT, 'ROLE_NOT_ALLOWED: relayed_by must be a manager or writer')
    WHERE NOT EXISTS (SELECT 1 FROM agents
                      WHERE id = NEW.relayed_by AND role IN ('manager','writer'));
  SELECT RAISE(ABORT, 'ROLE_NOT_ALLOWED: recorded_by must be a manager')
    WHERE NOT EXISTS (SELECT 1 FROM agents WHERE id = NEW.recorded_by AND role = 'manager');
END;
"""


def schema_sql() -> str:
    return resources.files("brandcal").joinpath("schema.sql").read_text(encoding="utf-8")


def build_v1(path: Path, tz: object) -> None:
    """A populated database as version 1 left it: old approvals table and trigger, no version."""
    conn = open_db(path, tz)  # type: ignore[arg-type]
    conn.executescript(schema_sql())
    for name in ("approvals_no_update", "approvals_no_delete", "approvals_roles"):
        conn.execute(f"DROP TRIGGER {name}")
    conn.execute("DROP TABLE approvals")
    conn.executescript(V1_APPROVALS)
    conn.execute("PRAGMA user_version = 0")
    conn.executemany(
        "INSERT INTO transitions (from_status, to_status, roles) VALUES (?, ?, ?)",
        [(f, t, ",".join(r)) for f, t, r in TRANSITIONS],
    )
    conn.executemany(
        "INSERT INTO agents (id, role) VALUES (?, ?)", [(a["id"], a["role"]) for a in AGENTS]
    )
    conn.execute("INSERT INTO agents (id, role) VALUES ('console', 'system')")
    conn.executemany(
        "INSERT INTO platforms (id, limits) VALUES (?, '{}')", [(p,) for p in PLATFORMS]
    )
    make_post(conn, id="p0001")
    add_approval(conn, "p0001", source_message_id="m1")
    conn.execute("UPDATE posts SET status = 'approved' WHERE id = 'p0001'")
    make_post(conn, id="p0002", slug="second")
    add_approval(conn, "p0002", decision="request_changes", changes_requested="Shorter")
    add_approval(conn, "p0002", channel="writer-session", relayed_by="writer-1", decision="cancel")
    conn.close()


def master(conn: sqlite3.Connection) -> list[tuple[str, str, str, str | None]]:
    rows = conn.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        " ORDER BY type, name"
    ).fetchall()
    return [tuple(r) for r in rows]  # type: ignore[misc]


def approvals_rows(conn: sqlite3.Connection) -> list[tuple[object, ...]]:
    cols = (
        "id, post_id, decision, content_version, content_hash, window, decided_by, channel,"
        " relayed_by, recorded_by, source_message_id, approver_words, changes_requested,"
        " decided_at, signature"
    )
    return [tuple(r) for r in conn.execute(f"SELECT {cols} FROM approvals ORDER BY id")]


def version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def test_fresh_init_lands_on_latest(tmp_path: Path, tz: object) -> None:
    conn = open_db(tmp_path / "brand.db", tz)  # type: ignore[arg-type]
    init_db(conn, UI_AGENTS, PLATFORMS)
    assert LATEST == 2 and version(conn) == LATEST
    init_db(conn, UI_AGENTS, PLATFORMS)  # safe to repeat
    assert version(conn) == LATEST
    conn.close()


def test_migration_keeps_rows_ids_and_triggers(tmp_path: Path, tz: object) -> None:
    path = tmp_path / "brand.db"
    build_v1(path, tz)
    before = sqlite3.connect(path)
    old_rows = approvals_rows(before)  # type: ignore[arg-type]
    old_triggers = {
        r[0] for r in before.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
    }
    assert before.execute("PRAGMA user_version").fetchone()[0] == 0 and len(old_rows) == 3
    before.close()

    conn = open_db(path, tz)  # type: ignore[arg-type]
    assert version(conn) == LATEST
    assert approvals_rows(conn) == old_rows
    assert [r[0] for r in conn.execute("SELECT id FROM approvals ORDER BY id")] == [1, 2, 3]
    new_triggers = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
    }
    assert new_triggers == old_triggers
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    row = conn.execute("SELECT verified_identity, identity_source FROM approvals WHERE id = 1")
    assert tuple(row.fetchone()) == (None, None)
    # The migrated database still enforces its rules and accepts a console approval.
    with pytest.raises(sqlite3.DatabaseError, match="APPEND_ONLY"):
        conn.execute("UPDATE approvals SET approver_words = 'x' WHERE id = 1")
    add_approval(
        conn, "p0001", channel="console", relayed_by="console", recorded_by="console",
        verified_identity="approver@example.com", identity_source="access-jwt",
    )  # fmt: skip
    conn.execute("UPDATE posts SET status = 'missed' WHERE id = 'p0001'")  # T-b still applies
    with pytest.raises(sqlite3.DatabaseError, match="STALE_APPROVAL"):
        conn.execute("UPDATE posts SET status = 'approved' WHERE id = 'p0002'")
    conn.close()
    again = open_db(path, tz)  # type: ignore[arg-type]
    assert version(again) == LATEST and len(approvals_rows(again)) == 4  # a second open is a no-op
    again.close()


def test_fresh_schema_equals_migrated_schema(tmp_path: Path, tz: object) -> None:
    build_v1(tmp_path / "old.db", tz)
    migrated = open_db(tmp_path / "old.db", tz)  # type: ignore[arg-type]
    fresh = open_db(tmp_path / "new.db", tz)  # type: ignore[arg-type]
    init_db(fresh, AGENTS, PLATFORMS)
    assert master(migrated) == master(fresh)
    migrated.close()
    fresh.close()


def test_empty_file_is_left_for_init(tmp_path: Path, tz: object) -> None:
    conn = open_db(tmp_path / "brand.db", tz)  # type: ignore[arg-type]
    assert version(conn) == 0
    conn.close()


def test_console_checks(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO agents (id, role) VALUES ('console', 'system')")
    make_post(conn)
    ok = {"channel": "console", "relayed_by": "console", "recorded_by": "console"}
    ident = {"verified_identity": "approver@example.com", "identity_source": "access-jwt"}
    add_approval(conn, "p0001", **ok, **ident)
    for bad in (
        {},  # no identity at all
        {"verified_identity": "approver@example.com"},  # no source
        {"verified_identity": "approver@example.com", "identity_source": "dev-unverified"},
        {"verified_identity": "", "identity_source": "access-jwt"},
    ):
        with pytest.raises(sqlite3.IntegrityError):
            add_approval(conn, "p0001", **ok, **bad)
    with pytest.raises(sqlite3.IntegrityError):  # the source is never dev-unverified, any channel
        add_approval(conn, "p0001", identity_source="dev-unverified")
    for who in ({"recorded_by": "manager-1"}, {"relayed_by": "writer-1"}):
        with pytest.raises(sqlite3.DatabaseError, match="ROLE_NOT_ALLOWED"):
            add_approval(conn, "p0001", **{**ok, **who}, **ident)
    with pytest.raises(sqlite3.DatabaseError, match="decided_by must be an approver"):
        add_approval(conn, "p0001", **ok, **ident, decided_by="manager-1")
    # Non-console channels keep the old rules: a system recorder is refused.
    with pytest.raises(sqlite3.DatabaseError, match="recorded_by must be a manager"):
        add_approval(conn, "p0001", recorded_by="console")


def test_unused_import_guard() -> None:
    assert BrandcalError  # keeps the import used if the tests above change

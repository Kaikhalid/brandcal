"""Schema versions, kept in PRAGMA user_version (UI_SPEC 3.2).

schema.sql is the source for a fresh database and ends by stamping LATEST. A database made
before versions existed has user_version 0 and an ``approvals`` table: it is version 1. An
empty file is left for ``init_db``. ``open_db`` calls ``migrate``, so every command sees the
latest schema. Each migration runs in one transaction; the object text below must stay equal
to schema.sql (tests/test_migrate_0002.py compares sqlite_master).
"""

from __future__ import annotations

import sqlite3

LATEST = 2

_APPROVALS = """CREATE TABLE IF NOT EXISTS approvals (
  id INTEGER PRIMARY KEY,
  post_id TEXT NOT NULL REFERENCES posts(id),
  decision TEXT NOT NULL CHECK (decision IN ('approve','request_changes','cancel','reschedule')),
  content_version INTEGER NOT NULL, content_hash TEXT NOT NULL,
  window TEXT NOT NULL,
  decided_by  TEXT NOT NULL REFERENCES agents(id),
  channel     TEXT NOT NULL CHECK (channel IN ('card','writer-session','legacy','console')),
  relayed_by  TEXT NOT NULL REFERENCES agents(id),
  recorded_by TEXT NOT NULL REFERENCES agents(id),
  source_message_id TEXT NOT NULL,
  approver_words TEXT NOT NULL,
  changes_requested TEXT,
  decided_at TEXT NOT NULL,
  signature TEXT,
  verified_identity TEXT,
  identity_source TEXT,
  CHECK (channel <> 'console' OR (length(verified_identity) > 0 AND identity_source IS NOT NULL)),
  CHECK (identity_source IS NULL OR identity_source = 'access-jwt')
)"""

_TRIGGERS = (
    """CREATE TRIGGER IF NOT EXISTS approvals_no_update
BEFORE UPDATE ON approvals
BEGIN
  SELECT RAISE(ABORT, 'APPEND_ONLY: approvals are append-only');
END""",
    """CREATE TRIGGER IF NOT EXISTS approvals_no_delete
BEFORE DELETE ON approvals
WHEN (SELECT active FROM archive_lock WHERE id = 1) IS NOT 1
BEGIN
  SELECT RAISE(ABORT, 'APPEND_ONLY: approvals can only be deleted by an archive run');
END""",
    """CREATE TRIGGER IF NOT EXISTS approvals_roles
BEFORE INSERT ON approvals
BEGIN
  SELECT RAISE(ABORT, 'ROLE_NOT_ALLOWED: decided_by must be an approver')
    WHERE NOT EXISTS (SELECT 1 FROM agents WHERE id = NEW.decided_by AND role = 'approver');
  SELECT RAISE(ABORT, 'ROLE_NOT_ALLOWED: relayed_by must be a manager or writer')
    WHERE NEW.channel <> 'console' AND NOT EXISTS (SELECT 1 FROM agents
                      WHERE id = NEW.relayed_by AND role IN ('manager','writer'));
  SELECT RAISE(ABORT, 'ROLE_NOT_ALLOWED: recorded_by must be a manager')
    WHERE NEW.channel <> 'console'
      AND NOT EXISTS (SELECT 1 FROM agents WHERE id = NEW.recorded_by AND role = 'manager');
  SELECT RAISE(ABORT, 'ROLE_NOT_ALLOWED: a console approval is relayed by the console agent')
    WHERE NEW.channel = 'console'
      AND NOT EXISTS (SELECT 1 FROM agents WHERE id = NEW.relayed_by AND role = 'system');
  SELECT RAISE(ABORT, 'ROLE_NOT_ALLOWED: a console approval is recorded by the console agent')
    WHERE NEW.channel = 'console'
      AND NOT EXISTS (SELECT 1 FROM agents WHERE id = NEW.recorded_by AND role = 'system');
END""",
)
_COLUMNS = (
    "id, post_id, decision, content_version, content_hash, window, decided_by, channel,"
    " relayed_by, recorded_by, source_message_id, approver_words, changes_requested,"
    " decided_at, signature"
)


def _0002_console_channel(conn: sqlite3.Connection) -> None:
    """Rebuild approvals: channel 'console', identity columns and the relaxed role trigger."""
    for name in ("approvals_no_update", "approvals_no_delete", "approvals_roles"):
        conn.execute(f"DROP TRIGGER {name}")
    # legacy_alter_table keeps the other triggers' bodies (which name approvals) untouched.
    conn.execute("PRAGMA legacy_alter_table = ON")
    conn.execute("ALTER TABLE approvals RENAME TO approvals_v1")
    conn.execute("PRAGMA legacy_alter_table = OFF")
    conn.execute(_APPROVALS)
    conn.execute(f"INSERT INTO approvals ({_COLUMNS}) SELECT {_COLUMNS} FROM approvals_v1")
    conn.execute("DROP TABLE approvals_v1")
    for trigger in _TRIGGERS:
        conn.execute(trigger)


MIGRATIONS = {2: _0002_console_channel}


def current_version(conn: sqlite3.Connection) -> int:
    """The schema version; 0 means no schema yet."""
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version:
        return version
    has = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'approvals'")
    return 1 if has.fetchone() else 0


def migrate(conn: sqlite3.Connection) -> None:
    """Apply every migration after the database's version; a fresh or current one is untouched."""
    if not 0 < current_version(conn) < LATEST:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        for target in range(current_version(conn) + 1, LATEST + 1):
            MIGRATIONS[target](conn)
            conn.execute(f"PRAGMA user_version = {target}")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

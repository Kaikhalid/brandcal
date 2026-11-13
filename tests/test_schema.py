"""Schema CHECKs and triggers (SPEC 5.3), exercised with raw SQL."""

from __future__ import annotations

import sqlite3
from datetime import tzinfo
from pathlib import Path

import pytest
from conftest import AGENTS, PLATFORMS, add_approval, approve_post, make_post

from brandcal.db import init_db, open_db, translate
from brandcal.errors import ErrorCode
from brandcal.events import append_event, last_hash, row_hash

CHECK = "CHECK constraint failed"
LATER = "2026-03-10T09:30:00+03:00"
NEW_WINDOW = "2026-03-11T09:00:00+03:00/2026-03-11T10:00:00+03:00"


@pytest.fixture
def approved(conn: sqlite3.Connection) -> str:
    pid = make_post(conn)
    approve_post(conn, pid)
    return pid


def code_of(info: pytest.ExceptionInfo[sqlite3.IntegrityError]) -> ErrorCode:
    return translate(info.value).code


def post_events(conn: sqlite3.Connection, pid: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM events WHERE chain = ? ORDER BY id", (f"post:{pid}",)
    ).fetchall()


# --- table CHECKs -----------------------------------------------------------------------


def test_status_outside_values_fails(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match=CHECK):
        make_post(conn, status="draft", legacy_id="L-1")


def test_window_without_offset_fails(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match=CHECK):
        make_post(conn, window="2026-03-10T09:00:00/2026-03-10T10:00:00")


def test_comment_without_delegation_fails(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match=CHECK):
        make_post(conn, post_type="comment", target_url="https://example.com/p/1")


def test_reshare_without_target_url_fails(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match=CHECK):
        make_post(conn, post_type="reshare")


@pytest.mark.parametrize(
    "overrides",
    [
        {"native_scheduled_at": LATER},
        {"claimed_by": "contrib-1", "claim_expires": LATER},
    ],
)
def test_schedule_or_claim_on_non_approved_fails(
    conn: sqlite3.Connection, overrides: dict[str, object]
) -> None:
    with pytest.raises(sqlite3.IntegrityError, match=CHECK):
        make_post(conn, **overrides)


def test_claim_without_expiry_fails(conn: sqlite3.Connection, approved: str) -> None:
    conn.execute(
        "UPDATE posts SET claimed_by = 'contrib-1', claim_expires = ? WHERE id = ?",
        (LATER, approved),
    )
    with pytest.raises(sqlite3.IntegrityError, match=CHECK):
        conn.execute("UPDATE posts SET claim_expires = NULL WHERE id = ?", (approved,))


def test_native_schedule_and_claim_together_fails(conn: sqlite3.Connection, approved: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match=CHECK):
        conn.execute(
            "UPDATE posts SET native_scheduled_at = ?, claimed_by = 'contrib-1',"
            " claim_expires = ? WHERE id = ?",
            (LATER, LATER, approved),
        )


def test_closed_at_on_missed_fails(conn: sqlite3.Connection, approved: str) -> None:
    with pytest.raises(sqlite3.IntegrityError, match=CHECK):
        conn.execute(
            "UPDATE posts SET status = 'missed', closed_at = ? WHERE id = ?", (LATER, approved)
        )


def test_cancel_kind_on_open_post_fails(conn: sqlite3.Connection) -> None:
    pid = make_post(conn)
    with pytest.raises(sqlite3.IntegrityError, match=CHECK):
        conn.execute("UPDATE posts SET cancel_kind = 'idea' WHERE id = ?", (pid,))


def test_cancelled_without_cancel_kind_fails(conn: sqlite3.Connection) -> None:
    pid = make_post(conn)
    with pytest.raises(sqlite3.IntegrityError, match=CHECK):
        conn.execute(
            "UPDATE posts SET status = 'cancelled', closed_at = ? WHERE id = ?", (LATER, pid)
        )


def test_null_window_only_for_legacy_published(conn: sqlite3.Connection) -> None:
    legacy: dict[str, object] = {
        "window": None,
        "status": "published",
        "legacy_id": "L-1",
        "closed_at": LATER,
    }
    make_post(conn, **legacy)
    with pytest.raises(sqlite3.IntegrityError, match=CHECK):
        make_post(conn, id="p0002", window=None)
    with pytest.raises(sqlite3.IntegrityError, match=CHECK):
        make_post(conn, id="p0003", **{**legacy, "legacy_id": "L-2", "status": "approved"})


# --- T-a, T-b, T-c, T-d -------------------------------------------------------------------


def test_insert_status_must_be_pending_unless_legacy(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError) as info:
        make_post(conn, status="approved")
    assert code_of(info) == ErrorCode.BAD_TRANSITION
    make_post(conn, status="published", legacy_id="L-1", closed_at=LATER)
    assert conn.execute("SELECT status FROM posts").fetchone()[0] == "published"


def test_status_change_must_be_in_transitions(conn: sqlite3.Connection) -> None:
    pid = make_post(conn)
    with pytest.raises(sqlite3.IntegrityError) as info:
        conn.execute("UPDATE posts SET status = 'missed' WHERE id = ?", (pid,))
    assert code_of(info) == ErrorCode.BAD_TRANSITION


def test_approved_needs_matching_approval(conn: sqlite3.Connection) -> None:
    pid = make_post(conn)
    sql = "UPDATE posts SET status = 'approved' WHERE id = ?"
    with pytest.raises(sqlite3.IntegrityError) as info:
        conn.execute(sql, (pid,))
    assert code_of(info) == ErrorCode.STALE_APPROVAL
    add_approval(conn, pid, content_hash="b" * 64)
    add_approval(conn, pid, content_version=2)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, (pid,))
    add_approval(conn, pid)
    conn.execute(sql, (pid,))
    assert conn.execute("SELECT status FROM posts").fetchone()[0] == "approved"


def test_published_needs_matching_approval(conn: sqlite3.Connection, approved: str) -> None:
    conn.execute("UPDATE posts SET content_hash = ? WHERE id = ?", ("c" * 64, approved))
    sql = (
        "UPDATE posts SET status = 'published', platform_url = 'https://example.com/p/1',"
        " closed_at = ? WHERE id = ?"
    )
    with pytest.raises(sqlite3.IntegrityError) as info:
        conn.execute(sql, (LATER, approved))
    assert code_of(info) == ErrorCode.STALE_APPROVAL
    add_approval(conn, approved)
    conn.execute(sql, (LATER, approved))
    assert conn.execute("SELECT status FROM posts").fetchone()[0] == "published"


# --- T-g, T-h, T-i ------------------------------------------------------------------------


def seed_rows(conn: sqlite3.Connection, pid: str) -> None:
    append_event(conn, at=LATER, actor="writer-1", action="add", chain=f"post:{pid}", post_id=pid)


@pytest.mark.parametrize(
    ("table", "assignment"),
    [("events", "reason = 'x'"), ("approvals", "approver_words = 'x'")],
)
def test_update_refused(
    conn: sqlite3.Connection, approved: str, table: str, assignment: str
) -> None:
    seed_rows(conn, approved)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(f"UPDATE {table} SET {assignment}")


@pytest.mark.parametrize("table", ["events", "approvals"])
def test_delete_needs_archive_lock(conn: sqlite3.Connection, approved: str, table: str) -> None:
    seed_rows(conn, approved)
    with pytest.raises(sqlite3.IntegrityError, match="archive"):
        conn.execute(f"DELETE FROM {table}")
    conn.execute("UPDATE archive_lock SET active = 1")
    conn.execute(f"DELETE FROM {table}")
    assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("field", ["decided_by", "recorded_by"])
def test_approval_roles_checked(conn: sqlite3.Connection, field: str) -> None:
    pid = make_post(conn)
    with pytest.raises(sqlite3.IntegrityError) as info:
        add_approval(conn, pid, **{field: "writer-1"})
    assert code_of(info) == ErrorCode.ROLE_NOT_ALLOWED


# --- T-e, T-f -----------------------------------------------------------------------------


def test_bc_now_uses_display_timezone(conn: sqlite3.Connection) -> None:
    assert conn.execute("SELECT bc_now()").fetchone()[0].endswith("+03:00")


@pytest.mark.parametrize("start", ["approved", "missed"])
def test_part_edit_requeues_and_logs(conn: sqlite3.Connection, approved: str, start: str) -> None:
    if start == "missed":
        conn.execute("UPDATE posts SET status = 'missed' WHERE id = ?", (approved,))
    seed_rows(conn, approved)
    prev = last_hash(conn, f"post:{approved}")
    ticks = iter(range(10, 60))
    # A clock that never repeats: the event's stored time must be the one that was hashed.
    conn.create_function("bc_now", 0, lambda: f"2026-03-10T09:00:{next(ticks)}+03:00")

    conn.execute("UPDATE parts SET text = 'Changed text' WHERE post_id = ?", (approved,))

    post = conn.execute("SELECT status, content_version FROM posts").fetchone()
    assert (post["status"], post["content_version"]) == ("pending_approval", 2)
    events = post_events(conn, approved)
    assert len(events) == 2
    ev = events[1]
    assert (ev["from_status"], ev["to_status"], ev["action"]) == (start, "pending_approval", "edit")
    assert ev["prev_hash"] == prev
    assert ev["row_hash"] == row_hash(
        prev,
        ev["at"],
        ev["actor"],
        ev["post_id"],
        ev["action"],
        ev["from_status"],
        ev["to_status"],
        ev["detail"],
        ev["reason"],
        ev["chain"],
    )


def test_part_edit_on_pending_bumps_version_only(conn: sqlite3.Connection) -> None:
    pid = make_post(conn)
    conn.execute("UPDATE parts SET text = 'Changed text' WHERE post_id = ?", (pid,))
    post = conn.execute("SELECT status, content_version FROM posts").fetchone()
    assert (post["status"], post["content_version"]) == ("pending_approval", 2)
    assert post_events(conn, pid) == []


def test_window_change_alone_does_not_bump(conn: sqlite3.Connection, approved: str) -> None:
    conn.execute('UPDATE posts SET "window" = ? WHERE id = ?', (NEW_WINDOW, approved))
    post = conn.execute("SELECT status, content_version FROM posts").fetchone()
    assert (post["status"], post["content_version"]) == ("approved", 1)
    assert post_events(conn, approved) == []


@pytest.mark.parametrize(
    ("assignment", "code"),
    [
        (f"native_scheduled_at = '{LATER}'", ErrorCode.EDIT_WHILE_SCHEDULED),
        (f"claimed_by = 'contrib-1', claim_expires = '{LATER}'", ErrorCode.EDIT_WHILE_CLAIMED),
    ],
)
def test_part_edit_refused_while_queued(
    conn: sqlite3.Connection, approved: str, assignment: str, code: ErrorCode
) -> None:
    conn.execute(f"UPDATE posts SET {assignment} WHERE id = ?", (approved,))
    with pytest.raises(sqlite3.IntegrityError) as info:
        conn.execute("UPDATE parts SET text = 'Changed text' WHERE post_id = ?", (approved,))
    assert code_of(info) == code
    post = conn.execute("SELECT status, content_version FROM posts").fetchone()
    assert (post["status"], post["content_version"]) == ("approved", 1)
    assert conn.execute("SELECT text FROM parts").fetchone()[0] == "Hello from Example Co"


def test_window_edit_refused_while_natively_scheduled(
    conn: sqlite3.Connection, approved: str
) -> None:
    conn.execute("UPDATE posts SET native_scheduled_at = ? WHERE id = ?", (LATER, approved))
    with pytest.raises(sqlite3.IntegrityError) as info:
        conn.execute('UPDATE posts SET "window" = ? WHERE id = ?', (NEW_WINDOW, approved))
    assert code_of(info) == ErrorCode.EDIT_WHILE_SCHEDULED


def test_plain_connection_cannot_edit_approved_part(
    conn: sqlite3.Connection, approved: str, tmp_path: Path
) -> None:
    plain = sqlite3.connect(tmp_path / "brand.db")
    try:
        with pytest.raises(sqlite3.OperationalError, match="no such function"):
            plain.execute("UPDATE parts SET text = 'Changed text'")
    finally:
        plain.close()


# --- init_db ------------------------------------------------------------------------------


def test_init_db_twice_is_harmless(conn: sqlite3.Connection) -> None:
    def snapshot() -> list[object]:
        return [
            conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("agents", "platforms", "transitions", "archive_lock", "sqlite_master")
        ]

    before = snapshot()
    init_db(conn, AGENTS, PLATFORMS)
    assert snapshot() == before
    assert before[:4] == [len(AGENTS), len(PLATFORMS), 12, 1]


# --- added by hand during review -----------------------------------------------------------


def test_append_only_code(conn: sqlite3.Connection) -> None:
    pid = make_post(conn)
    append_event(conn, at=LATER, actor="writer-1", action="add", chain=f"post:{pid}", post_id=pid)
    with pytest.raises(sqlite3.IntegrityError) as info:
        conn.execute("UPDATE events SET reason = 'x'")
    assert code_of(info) == ErrorCode.APPEND_ONLY
    with pytest.raises(sqlite3.IntegrityError) as info:
        conn.execute("DELETE FROM events")
    assert code_of(info) == ErrorCode.APPEND_ONLY


def test_first_comment_edit_on_approved_bumps_and_reverts(
    conn: sqlite3.Connection, approved: str
) -> None:
    before = conn.execute("SELECT content_version FROM posts").fetchone()[0]
    conn.execute("UPDATE posts SET first_comment = 'More at example.com' WHERE id = ?", (approved,))
    row = conn.execute("SELECT status, content_version FROM posts").fetchone()
    assert row["status"] == "pending_approval"
    assert row["content_version"] == before + 1


def test_missed_back_to_approved_needs_reschedule(conn: sqlite3.Connection, approved: str) -> None:
    conn.execute("UPDATE posts SET status = 'missed' WHERE id = ?", (approved,))
    # The old 'approve' decision is not enough to leave missed; a reschedule is.
    with pytest.raises(sqlite3.IntegrityError) as info:
        conn.execute("UPDATE posts SET status = 'approved' WHERE id = ?", (approved,))
    assert code_of(info) == ErrorCode.STALE_APPROVAL
    add_approval(conn, approved, decision="reschedule")
    conn.execute("UPDATE posts SET status = 'approved' WHERE id = ?", (approved,))
    assert conn.execute("SELECT status FROM posts").fetchone()[0] == "approved"


def test_system_agent_always_seeded(tmp_path: Path, tz: tzinfo) -> None:
    db = open_db(tmp_path / "other.db", tz)
    init_db(db, [], {})
    assert db.execute("SELECT role FROM agents WHERE id = 'system'").fetchone()[0] == "system"
    db.close()

"""Approver decisions: approve, request changes, reschedule, cancel, preview (SPEC 6.1, 7)."""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from conftest import AGENTS, PLATFORMS, WINDOW

from brandcal import approvals, posts
from brandcal.cli import main
from brandcal.errors import BrandcalError

CFG: dict[str, Any] = {"timezone": "+03:00", "agents": AGENTS}
NEW_WINDOW = "2026-03-11T14:00:00+03:00/2026-03-11T15:00:00+03:00"
DATA: dict[str, Any] = {
    "slug": "example-post",
    "title": "Example Co announcement",
    "platform": "linkedin",
    "post_type": "text",
    "window": WINDOW,
    "parts": [{"text": "Hello from Example Co"}],
}


def new_post(conn: sqlite3.Connection, who: str = "writer-1", **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = posts.add_post(conn, who, "writer", CFG, {**DATA, **extra})
    return out


def approve(conn: sqlite3.Connection, post: dict[str, Any], **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "version": post["version"],
        "hash_prefix": post["hash"],
        "channel": "card",
        "msg_id": "msg-1",
        "words": "Approved",
    }
    out: dict[str, Any] = approvals.approve(
        conn, "manager-1", "manager", CFG, post["id"], **{**args, **kw}
    )
    return out


def approved_post(conn: sqlite3.Connection) -> dict[str, Any]:
    post = new_post(conn)
    approve(conn, post)
    return post


def reschedule(conn: sqlite3.Connection, post: dict[str, Any], **kw: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "version": post["version"],
        "hash_prefix": post["hash"],
        "new_window": NEW_WINDOW,
        "msg_id": "msg-2",
        "words": "Move it",
    }
    out: dict[str, Any] = approvals.reschedule(
        conn, "manager-1", "manager", CFG, post["id"], **{**args, **kw}
    )
    return out


def cancel(
    conn: sqlite3.Connection, post_id: str, who: str = "manager-1", **kw: Any
) -> dict[str, Any]:
    role = "writer" if who.startswith("writer") else "manager"
    args: dict[str, Any] = {"kind": "plan", "reason": "Timing changed"}
    out: dict[str, Any] = approvals.cancel(conn, who, role, CFG, post_id, **{**args, **kw})
    return out


def row(conn: sqlite3.Connection, post_id: str) -> sqlite3.Row:
    r: sqlite3.Row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    return r


def fails(code: str, exit_code: int, fn: Any, *args: Any, **kw: Any) -> None:
    with pytest.raises(BrandcalError) as info:
        fn(*args, **kw)
    assert info.value.code.value == code
    assert info.value.exit_code == exit_code


def n_events(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])


# --- approve -----------------------------------------------------------------------------


def test_approve_records_row_and_status(conn: sqlite3.Connection) -> None:
    post = new_post(conn)
    out = approve(conn, post)
    assert out["ok"] is True and out["status"] == "approved" and out["id"] == post["id"]
    r = row(conn, post["id"])
    assert r["status"] == "approved"
    a = conn.execute("SELECT * FROM approvals").fetchone()
    assert (a["decision"], a["channel"], a["window"]) == ("approve", "card", WINDOW)
    assert (a["decided_by"], a["relayed_by"], a["recorded_by"]) == ("approver-1",) + (
        "manager-1",
    ) * 2
    assert a["content_version"] == r["content_version"] and a["content_hash"] == r["content_hash"]
    event = conn.execute("SELECT * FROM events WHERE action = 'approve'").fetchone()
    assert (event["from_status"], event["to_status"]) == ("pending_approval", "approved")


def test_approve_wrong_version_is_stale(conn: sqlite3.Connection) -> None:
    post = new_post(conn)
    fails("STALE_APPROVAL", 6, approve, conn, post, version=post["version"] + 1)
    assert row(conn, post["id"])["status"] == "pending_approval"


def test_approve_wrong_hash_prefix_is_stale(conn: sqlite3.Connection) -> None:
    post = new_post(conn)
    wrong = "0" * 8 if post["hash"] != "0" * 8 else "f" * 8
    fails("STALE_APPROVAL", 6, approve, conn, post, hash_prefix=wrong)
    full = row(conn, post["id"])["content_hash"]
    assert approve(conn, post, hash_prefix=full)["status"] == "approved"


def test_approve_hash_prefix_must_be_8_hex(conn: sqlite3.Connection) -> None:
    post = new_post(conn)
    fails("BAD_ARGS", 2, approve, conn, post, hash_prefix=post["hash"][:7])
    fails("BAD_ARGS", 2, approve, conn, post, hash_prefix="zzzzzzzz")


def test_approve_by_writer_not_allowed(conn: sqlite3.Connection) -> None:
    post = new_post(conn)
    fails(
        "ROLE_NOT_ALLOWED",
        4,
        approvals.approve,
        conn,
        "writer-1",
        "writer",
        CFG,
        post["id"],
        post["version"],
        post["hash"],
        "card",
        "m",
        "w",
    )
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


def test_approve_needs_pending_approval(conn: sqlite3.Connection) -> None:
    post = new_post(conn)
    approvals.request_changes(
        conn, "manager-1", "manager", CFG, post["id"], post["version"], post["hash"], "m", "Edit"
    )
    fails("BAD_TRANSITION", 5, approve, conn, post)


def test_approve_writer_session_needs_writer_relay(conn: sqlite3.Connection) -> None:
    post = new_post(conn)
    for relay in (None, "manager-1", "nobody"):
        fails("BAD_ARGS", 2, approve, conn, post, channel="writer-session", relayed_by=relay)
    approve(
        conn,
        post,
        channel="writer-session",
        relayed_by="writer-1",
        msg_id="sess-9",
        words="Yes, ship it",
    )
    a = conn.execute("SELECT * FROM approvals").fetchone()
    assert (a["channel"], a["source_message_id"], a["approver_words"]) == (
        "writer-session",
        "sess-9",
        "Yes, ship it",
    )
    assert (a["relayed_by"], a["recorded_by"], a["decided_by"]) == (
        "writer-1",
        "manager-1",
        "approver-1",
    )


def test_approve_bad_channel_and_missing_provenance(conn: sqlite3.Connection) -> None:
    post = new_post(conn)
    fails("BAD_ARGS", 2, approve, conn, post, channel="email")
    fails("BAD_ARGS", 2, approve, conn, post, words="")
    fails("BAD_ARGS", 2, approve, conn, post, msg_id="")
    fails("BAD_ARGS", 2, approve, conn, post, relayed_by="writer-1")


def test_approver_resolution(conn: sqlite3.Connection) -> None:
    post = new_post(conn)
    fails("BAD_ARGS", 2, approve, conn, post, approver="writer-1")
    solo = {**CFG, "agents": [a for a in AGENTS if a["role"] != "approver"]}
    with pytest.raises(BrandcalError) as info:
        approvals.approve(
            conn, "manager-1", "manager", solo, post["id"], 1, post["hash"], "card", "m", "w"
        )
    assert info.value.code.value == "BAD_ARGS"
    conn.execute("INSERT INTO agents (id, role) VALUES ('approver-2', 'approver')")
    two = {**CFG, "agents": [*AGENTS, {"id": "approver-2", "role": "approver"}]}
    with pytest.raises(BrandcalError) as info:
        approvals.approve(
            conn, "manager-1", "manager", two, post["id"], 1, post["hash"], "card", "m", "w"
        )
    assert info.value.code.value == "BAD_ARGS"
    approvals.approve(
        conn, "manager-1", "manager", two, post["id"], 1, post["hash"], "card", "m", "w",
        approver="approver-2",
    )  # fmt: skip
    assert conn.execute("SELECT decided_by FROM approvals").fetchone()[0] == "approver-2"


def test_edit_after_approval_makes_old_version_stale(conn: sqlite3.Connection) -> None:
    post = approved_post(conn)
    posts.part_edit(conn, "writer-1", "writer", CFG, post["id"], 1, "Changed text")
    r = row(conn, post["id"])
    assert r["status"] == "pending_approval" and r["content_version"] == post["version"] + 1
    fails("STALE_APPROVAL", 6, approve, conn, post)
    fresh = {"id": post["id"], "version": r["content_version"], "hash": r["content_hash"][:8]}
    assert approve(conn, fresh, msg_id="msg-3")["status"] == "approved"


def test_future_hold_blocks_approval(conn: sqlite3.Connection) -> None:
    post = new_post(conn, hold_until="2099-01-01T00:00:00+03:00", hold_reason="Embargo")
    fails("ON_HOLD", 3, approve, conn, post)
    assert row(conn, post["id"])["status"] == "pending_approval"
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


def test_approve_unknown_post(conn: sqlite3.Connection) -> None:
    fails("NOT_FOUND", 7, approve, conn, {"id": "p9999", "version": 1, "hash": "a" * 8})


# --- request changes ---------------------------------------------------------------------


def test_request_changes(conn: sqlite3.Connection) -> None:
    post = new_post(conn)
    out = approvals.request_changes(
        conn, "manager-1", "manager", CFG, post["id"], 1, post["hash"], "m-5", "Shorter, please"
    )
    assert out["status"] == "changes_requested"
    a = conn.execute("SELECT * FROM approvals").fetchone()
    assert (a["decision"], a["changes_requested"]) == ("request_changes", "Shorter, please")
    assert (a["approver_words"], a["source_message_id"]) == ("Shorter, please", "m-5")
    assert row(conn, post["id"])["status"] == "changes_requested"
    other = new_post(conn, slug="second")
    fails(
        "STALE_APPROVAL", 6, approvals.request_changes,
        conn, "manager-1", "manager", CFG, other["id"], 2, other["hash"], "m", "w",
    )  # fmt: skip
    fails(
        "ROLE_NOT_ALLOWED", 4, approvals.request_changes,
        conn, "writer-1", "writer", CFG, other["id"], 1, other["hash"], "m", "w",
    )  # fmt: skip


# --- reschedule --------------------------------------------------------------------------


def test_reschedule_approved_keeps_status(conn: sqlite3.Connection) -> None:
    post = approved_post(conn)
    out = reschedule(conn, post, new_window="2026-03-11T14:00:00Z/2026-03-11T15:00:00Z")
    assert out["status"] == "approved"
    assert out["window"] == "2026-03-11T17:00:00+03:00/2026-03-11T18:00:00+03:00"
    assert row(conn, post["id"])["window"] == out["window"]
    assert approvals.approved_window(conn, post["id"]) == out["window"]
    assert conn.execute("SELECT decision FROM approvals ORDER BY id DESC").fetchone()[0] == (
        "reschedule"
    )


def test_approved_window_follows_latest_decision(conn: sqlite3.Connection) -> None:
    post = new_post(conn)
    assert approvals.approved_window(conn, post["id"]) is None
    approve(conn, post)
    assert approvals.approved_window(conn, post["id"]) == WINDOW
    reschedule(conn, post)
    assert approvals.approved_window(conn, post["id"]) == NEW_WINDOW
    posts.part_edit(conn, "writer-1", "writer", CFG, post["id"], 1, "Changed text")
    assert approvals.approved_window(conn, post["id"]) is None


def test_reschedule_missed_becomes_approved(conn: sqlite3.Connection) -> None:
    post = approved_post(conn)
    conn.execute("UPDATE posts SET status = 'missed' WHERE id = ?", (post["id"],))
    out = reschedule(conn, post)
    assert (out["status"], out["window"]) == ("approved", NEW_WINDOW)
    assert row(conn, post["id"])["status"] == "approved"
    event = conn.execute("SELECT * FROM events WHERE action = 'reschedule'").fetchone()
    assert (event["from_status"], event["to_status"]) == ("missed", "approved")


def test_reschedule_checks(conn: sqlite3.Connection) -> None:
    post = approved_post(conn)
    fails("STALE_APPROVAL", 6, reschedule, conn, post, hash_prefix="0" * 8)
    fails("STALE_APPROVAL", 6, reschedule, conn, post, version=99)
    fails("BAD_WINDOW", 3, reschedule, conn, post, new_window="2026-03-11T14:00:00+03:00")
    pending = new_post(conn, slug="second")
    fails("BAD_TRANSITION", 5, reschedule, conn, pending)
    assert row(conn, post["id"])["window"] == WINDOW


def test_reschedule_while_natively_scheduled(conn: sqlite3.Connection) -> None:
    post = approved_post(conn)
    conn.execute(
        "UPDATE posts SET native_scheduled_at = ? WHERE id = ?",
        ("2026-03-10T09:30:00+03:00", post["id"]),
    )
    fails("EDIT_WHILE_SCHEDULED", 5, reschedule, conn, post)
    assert row(conn, post["id"])["window"] == WINDOW
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 1


# --- cancel ------------------------------------------------------------------------------


def test_cancel_needs_valid_kind(conn: sqlite3.Connection) -> None:
    post = new_post(conn)
    fails("BAD_ARGS", 2, cancel, conn, post["id"], kind="whim")
    fails("BAD_ARGS", 2, cancel, conn, post["id"], reason="")
    fails("BAD_ARGS", 2, cancel, conn, post["id"], msg_id="m")
    assert row(conn, post["id"])["status"] == "pending_approval"


def test_manager_cancel_sets_close_fields(conn: sqlite3.Connection) -> None:
    post = approved_post(conn)
    out = cancel(conn, post["id"], kind="idea", reason="Dropped topic")
    assert out["status"] == "cancelled"
    r = row(conn, post["id"])
    assert (r["cancel_kind"], r["status"]) == ("idea", "cancelled") and r["closed_at"]
    event = conn.execute("SELECT * FROM events WHERE action = 'cancel'").fetchone()
    assert (event["reason"], event["from_status"]) == ("Dropped topic", "approved")
    assert (
        conn.execute("SELECT COUNT(*) FROM approvals WHERE decision = 'cancel'").fetchone()[0] == 0
    )
    fails("POST_CLOSED", 5, cancel, conn, post["id"])


def test_cancel_with_approver_words_records_decision(conn: sqlite3.Connection) -> None:
    post = new_post(conn)
    cancel(conn, post["id"], msg_id="m-7", words="Drop it")
    a = conn.execute("SELECT * FROM approvals WHERE decision = 'cancel'").fetchone()
    assert (a["source_message_id"], a["approver_words"], a["decided_by"]) == (
        "m-7",
        "Drop it",
        "approver-1",
    )


def test_writer_cancel_rules(conn: sqlite3.Connection) -> None:
    own = new_post(conn)
    other = new_post(conn, who="writer-1", slug="other")
    conn.execute("UPDATE posts SET owner = 'manager-1' WHERE id = ?", (other["id"],))
    fails("ROLE_NOT_ALLOWED", 4, cancel, conn, other["id"], who="writer-1")
    fails("ROLE_NOT_ALLOWED", 4, cancel, conn, own["id"], who="writer-1", msg_id="m", words="w")
    assert cancel(conn, own["id"], who="writer-1")["status"] == "cancelled"
    changes = new_post(conn, slug="third")
    approvals.request_changes(
        conn, "manager-1", "manager", CFG, changes["id"], 1, changes["hash"], "m", "Edit"
    )
    assert cancel(conn, changes["id"], who="writer-1")["status"] == "cancelled"
    done = approved_post_with_slug(conn, "fourth")
    fails("ROLE_NOT_ALLOWED", 4, cancel, conn, done["id"], who="writer-1")
    fails("ROLE_NOT_ALLOWED", 4, approvals.cancel, conn, "approver-1", "approver", CFG,
          done["id"], "plan", "r")  # fmt: skip


def approved_post_with_slug(conn: sqlite3.Connection, slug: str) -> dict[str, Any]:
    post = new_post(conn, slug=slug)
    approve(conn, post)
    return post


def test_manager_cancel_refused_when_scheduled_or_claimed(conn: sqlite3.Connection) -> None:
    queued = approved_post(conn)
    conn.execute(
        "UPDATE posts SET native_scheduled_at = ? WHERE id = ?",
        ("2026-03-10T09:30:00+03:00", queued["id"]),
    )
    fails("NATIVELY_SCHEDULED", 5, cancel, conn, queued["id"])
    claimed = approved_post_with_slug(conn, "claimed")
    conn.execute(
        "UPDATE posts SET claimed_by = 'manager-1', claim_expires = ? WHERE id = ?",
        ("2026-03-10T09:45:00+03:00", claimed["id"]),
    )
    fails("CLAIMED", 8, cancel, conn, claimed["id"])
    assert row(conn, queued["id"])["status"] == "approved"
    assert row(conn, claimed["id"])["status"] == "approved"


def test_cancel_missed_clears_nothing_else(conn: sqlite3.Connection) -> None:
    post = approved_post(conn)
    conn.execute("UPDATE posts SET status = 'missed' WHERE id = ?", (post["id"],))
    assert cancel(conn, post["id"])["status"] == "cancelled"


# --- window_within -----------------------------------------------------------------------


def test_window_within() -> None:
    outer = "2026-03-10T09:00:00+03:00/2026-03-10T10:00:00+03:00"
    inside = approvals.window_within
    assert inside(outer, outer)
    assert inside("2026-03-10T09:15:00+03:00/2026-03-10T09:45:00+03:00", outer)
    assert inside("2026-03-10T09:00:00+03:00/2026-03-10T09:30:00+03:00", outer)
    assert not inside("2026-03-10T08:59:00+03:00/2026-03-10T09:30:00+03:00", outer)
    assert not inside("2026-03-10T09:30:00+03:00/2026-03-10T10:01:00+03:00", outer)
    assert not inside(outer, "2026-03-10T09:15:00+03:00/2026-03-10T09:45:00+03:00")


def test_window_within_across_offsets() -> None:
    outer = "2026-03-10T09:00:00+03:00/2026-03-10T10:00:00+03:00"
    same_instants = "2026-03-10T06:00:00+00:00/2026-03-10T07:00:00+00:00"
    assert approvals.window_within(same_instants, outer)
    assert approvals.window_within(outer, same_instants)
    assert approvals.window_within("2026-03-10T06:10:00Z/2026-03-10T06:50:00Z", outer)
    assert not approvals.window_within("2026-03-10T09:10:00Z/2026-03-10T09:50:00Z", outer)
    assert approvals.window_within(
        "2026-03-09T23:00:00-05:00/2026-03-09T23:30:00-05:00",
        "2026-03-10T03:30:00+00:00/2026-03-10T05:00:00+00:00",
    )


# --- preview -----------------------------------------------------------------------------


def test_preview_is_read_only(conn: sqlite3.Connection) -> None:
    post = new_post(conn, first_comment="Link in comments")
    before = n_events(conn)
    card = approvals.preview(conn, CFG, post["id"])
    assert n_events(conn) == before
    assert (card["platform"], card["post_type"], card["window"]) == ("linkedin", "text", WINDOW)
    assert (card["title"], card["first_comment"]) == ("Example Co announcement", "Link in comments")
    assert card["parts"][0]["text"] == "Hello from Example Co"
    assert (card["version"], card["hash"], card["kind"]) == (1, post["hash"], "card")
    assert [b["label"] for b in card["buttons"]] == ["Approve", "Request changes", "Cancel"]
    for button in card["buttons"]:
        assert (button["post"], button["version"], button["hash"]) == (
            post["id"],
            1,
            post["hash"],
        )
    fails("NOT_FOUND", 7, approvals.preview, conn, CFG, "p9999")


def test_preview_receipt_when_approver_confirmed(conn: sqlite3.Connection) -> None:
    out = posts.add_post(
        conn, "writer-1", "writer", CFG, DATA, approver_confirmed="sess-1", words="Final, go"
    )
    assert approvals.preview(conn, CFG, out["id"])["kind"] == "receipt"


# --- CLI round trip ----------------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "config.json").write_text(json.dumps(CFG), encoding="utf-8")
    (tmp_path / "platforms.json").write_text(json.dumps(PLATFORMS), encoding="utf-8")
    monkeypatch.setenv("BRANDCAL_HOME", str(tmp_path))
    monkeypatch.delenv("BRANDCAL_AGENT", raising=False)
    monkeypatch.delenv("BRANDCAL_TZ", raising=False)
    return tmp_path


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any]]:
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_cli_round_trip(
    home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run(capsys, "init", "--as", "admin-1")[0] == 0
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(DATA)))
    code, added = run(capsys, "add", "--as", "writer-1")
    assert code == 0
    pid, h = added["id"], added["hash"]

    code, card = run(capsys, "preview", pid)
    assert code == 0 and card["kind"] == "card" and card["hash"] == h

    common = [pid, "--version", "1", "--hash", h]
    code, out = run(capsys, "approve", *common, "--channel", "card", "--msg", "m1", "--words", "ok")
    assert (code, out["error"]["code"]) == (2, "NO_AGENT")
    code, out = run(
        capsys, "approve", *common, "--channel", "card", "--msg", "m1", "--words", "ok",
        "--as", "writer-1",
    )  # fmt: skip
    assert (code, out["error"]["code"]) == (4, "ROLE_NOT_ALLOWED")
    code, out = run(
        capsys, "approve", pid, "--version", "2", "--hash", h, "--channel", "card",
        "--msg", "m1", "--words", "ok", "--as", "manager-1",
    )  # fmt: skip
    assert (code, out["error"]["code"]) == (6, "STALE_APPROVAL")
    code, out = run(
        capsys, "approve", *common, "--channel", "card", "--msg", "m1", "--words", "ok",
        "--as", "manager-1",
    )  # fmt: skip
    assert (code, out["status"]) == (0, "approved")

    db = sqlite3.connect(home / "brand.db")
    assert db.execute("SELECT status FROM posts WHERE id = ?", (pid,)).fetchone()[0] == "approved"
    db.close()

    code, out = run(
        capsys, "reschedule", *common, "--window", NEW_WINDOW, "--msg", "m2", "--words", "later",
        "--as", "manager-1",
    )  # fmt: skip
    assert (code, out["window"]) == (0, NEW_WINDOW)
    code, out = run(
        capsys, "cancel", pid, "--kind", "plan", "--reason", "Timing", "--as", "manager-1"
    )
    assert (code, out["status"]) == (0, "cancelled")
    code, out = run(
        capsys, "cancel", pid, "--kind", "plan", "--reason", "Timing", "--as", "manager-1"
    )
    assert (code, out["error"]["code"]) == (5, "POST_CLOSED")


def test_cli_request_changes(
    home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    run(capsys, "init", "--as", "admin-1")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(DATA)))
    added = run(capsys, "add", "--as", "writer-1")[1]
    code, out = run(
        capsys, "request-changes", added["id"], "--version", "1", "--hash", added["hash"],
        "--msg", "m1", "--words", "Tighten it", "--as", "manager-1",
    )  # fmt: skip
    assert (code, out["status"]) == (0, "changes_requested")


def test_reschedule_while_claimed(conn: sqlite3.Connection) -> None:
    """Hand-added: a claimed post's window can't move under the publisher."""
    post = approved_post(conn)
    conn.execute(
        "UPDATE posts SET claimed_by = 'manager-1', claim_expires = ? WHERE id = ?",
        ("2026-03-10T10:00:00+03:00", post["id"]),
    )
    fails("EDIT_WHILE_CLAIMED", 5, reschedule, conn, post)
    assert row(conn, post["id"])["window"] == WINDOW

"""Add, edit, parts, notes, keywords, check and submit (SPEC 6.1, 8.1, 8.4)."""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from conftest import AGENTS, PLATFORMS, WINDOW, add_approval, approve_post, make_post

from brandcal import cli, content, posts
from brandcal.errors import BrandcalError

CFG: dict[str, Any] = {"timezone": "+03:00", "campaigns": ["Launch"], "pillars": ["Tips"]}
FUTURE = "2999-01-01T00:00:00+00:00"


@pytest.fixture(autouse=True)
def _no_tz_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRANDCAL_TZ", raising=False)


def data(**overrides: Any) -> dict[str, Any]:
    d: dict[str, Any] = {
        "slug": "example-post",
        "title": "Example Co launch",
        "platform": "linkedin",
        "post_type": "text",
        "window": WINDOW,
        "parts": [{"text": "Hello from Example Co"}],
    }
    d.update(overrides)
    return d


def add(conn: sqlite3.Connection, who: str = "writer-1", role: str = "writer", **kw: Any) -> Any:
    return posts.add_post(conn, who, role, CFG, data(**kw))


def fail(code: str, exit_code: int, fn: Any, *a: Any, **kw: Any) -> None:
    with pytest.raises(BrandcalError) as info:
        fn(*a, **kw)
    assert info.value.code.value == code
    assert info.value.exit_code == exit_code


def row(conn: sqlite3.Connection, pid: str) -> sqlite3.Row:
    r: sqlite3.Row = conn.execute("SELECT * FROM posts WHERE id = ?", (pid,)).fetchone()
    return r


def thread(conn: sqlite3.Connection) -> str:
    out = add(conn, post_type="thread", parts=[{"text": "one"}, {"text": "two"}, {"text": "three"}])
    return str(out["id"])


def texts(conn: sqlite3.Connection, pid: str) -> list[str]:
    rows = conn.execute("SELECT text FROM parts WHERE post_id = ? ORDER BY pos", (pid,))
    return [r[0] for r in rows]


# --- add ---------------------------------------------------------------------------------


def test_add_creates_pending_post(conn: sqlite3.Connection) -> None:
    out = add(conn)
    assert out["ok"] is True and out["id"] == "p0001" and out["status"] == "pending_approval"
    assert out["version"] == 1 and len(out["hash"]) == 8
    p = row(conn, "p0001")
    assert p["content_version"] == 1 and p["owner"] == "writer-1"
    assert p["content_hash"] == content.content_hash(conn, "p0001")
    assert out["hash"] == p["content_hash"][:8] and out["window"] == p["window"]
    events = conn.execute("SELECT action FROM events WHERE post_id = 'p0001'").fetchall()
    assert [e[0] for e in events] == ["add"]
    assert add(conn)["id"] == "p0002"


def test_add_normalises_window(conn: sqlite3.Connection) -> None:
    out = add(conn, window="2026-03-10T06:00:00Z/2026-03-10T07:00:00Z")
    assert out["window"] == WINDOW


def test_add_records_approver_confirmation(conn: sqlite3.Connection) -> None:
    out = posts.add_post(
        conn, "writer-1", "writer", CFG, data(), approver_confirmed="msg-9", words="Go ahead"
    )
    assert "msg-9" in out["next"]
    detail = json.loads(conn.execute("SELECT detail FROM events").fetchone()[0])
    assert detail["approver_confirmed"] == "msg-9" and detail["words"] == "Go ahead"
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


def test_add_stores_optional_fields(conn: sqlite3.Connection) -> None:
    add(conn, campaign="Launch", keywords=["a", "b"], notes="first note", series_id="s1")
    p = row(conn, "p0001")
    assert p["campaign"] == "Launch" and json.loads(p["keywords"]) == ["a", "b"]
    assert p["notes"] == "first note" and p["series_id"] == "s1"


def test_add_rejects_bad_input(conn: sqlite3.Connection) -> None:
    fail("BAD_ARGS", 2, add, conn, parts=[])
    fail("BAD_ARGS", 2, add, conn, bogus=1)
    fail("BAD_ARGS", 2, add, conn, platform="nowhere")
    fail("BAD_ARGS", 2, add, conn, post_type="reshare")
    assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0


def test_add_comment_needs_manager_and_delegation(conn: sqlite3.Connection) -> None:
    c = {"post_type": "comment", "target_url": "https://example.com/post"}
    fail("COMMENT_NOT_DELEGATED", 4, add, conn, "manager-1", "manager", **c)
    fail("ROLE_NOT_ALLOWED", 4, add, conn, "writer-1", "writer", **c)
    ok = add(
        conn,
        "manager-1",
        "manager",
        delegation_msg_id="m1",
        delegation_words="Please comment",
        **c,
    )
    assert ok["status"] == "pending_approval"


def test_add_roles(conn: sqlite3.Connection) -> None:
    fail("ROLE_NOT_ALLOWED", 4, add, conn, "contrib-1", "contributor")
    assert add(conn, "manager-1", "manager")["ok"] is True


def test_add_window_errors(conn: sqlite3.Connection) -> None:
    fail("TIME_OFFSET_REQUIRED", 3, add, conn, window="2026-03-10T09:00:00/2026-03-10T10:00:00")
    fail("BAD_WINDOW", 3, add, conn, window="2026-03-10T10:00:00+03:00/2026-03-10T09:00:00+03:00")


def test_add_text_limits(conn: sqlite3.Connection) -> None:
    long = "x" * 281
    fail("TOO_LONG", 3, add, conn, platform="x", parts=[{"text": long}])
    assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
    limits = {**PLATFORMS["x"], "premium": True, "premium_chars_per_post": 25000}
    limits["feed_preview_chars"] = 280
    conn.execute("UPDATE platforms SET limits = ? WHERE id = 'x'", (json.dumps(limits),))
    out = add(conn, platform="x", parts=[{"text": long}])
    assert out["ok"] is True and any("preview" in w for w in out["warnings"])


def test_urls_count_as_fixed_length(conn: sqlite3.Connection) -> None:
    url = "https://example.com/" + "a" * 300
    assert add(conn, platform="x", parts=[{"text": f"Read {url}"}])["ok"] is True


def test_add_image_without_images_is_warning(conn: sqlite3.Connection) -> None:
    out = add(conn, post_type="image")
    assert any("image" in w for w in out["warnings"])


def test_add_warnings(conn: sqlite3.Connection) -> None:
    out = add(conn, campaign="Other", pillar="Odd", parts=[{"text": "See [link] TBC"}])
    text = " ".join(out["warnings"])
    for word in ("campaign", "pillar", "placeholder", "past"):
        assert word in text
    add(conn)
    assert any("overlaps p0001" in w for w in add(conn)["warnings"] if "p0001" in w)


# --- edit --------------------------------------------------------------------------------


def test_edit_first_comment_bumps_version(conn: sqlite3.Connection) -> None:
    add(conn)
    before = row(conn, "p0001")["content_hash"]
    out = posts.edit_post(
        conn, "writer-1", "writer", CFG, "p0001", ["first_comment=More at example.com"]
    )
    assert out["version"] == 2
    p = row(conn, "p0001")
    assert p["first_comment"] == "More at example.com" and p["content_hash"] != before
    assert p["content_hash"] == content.content_hash(conn, "p0001")


def test_edit_uncovered_fields_keep_version(conn: sqlite3.Connection) -> None:
    add(conn)
    out = posts.edit_post(conn, "writer-1", "writer", CFG, "p0001", ["title=New title", "pillar="])
    assert out["version"] == 1 and row(conn, "p0001")["title"] == "New title"


def test_edit_window_and_clear(conn: sqlite3.Connection) -> None:
    add(conn, campaign="Launch")
    posts.edit_post(conn, "writer-1", "writer", CFG, "p0001", ["campaign="])
    assert row(conn, "p0001")["campaign"] is None
    posts.edit_post(
        conn,
        "writer-1",
        "writer",
        CFG,
        "p0001",
        ["window=2026-03-11T09:00:00Z/2026-03-11T10:00:00Z"],
    )
    assert row(conn, "p0001")["window"].startswith("2026-03-11T12:00:00+03:00")


def test_edit_bad_fields(conn: sqlite3.Connection) -> None:
    add(conn)
    for bad in (["status=approved"], ["title"], ["owner=x"]):
        fail("BAD_ARGS", 2, posts.edit_post, conn, "writer-1", "writer", CFG, "p0001", bad)
    fail("ROLE_NOT_ALLOWED", 4, posts.edit_post, conn, "contrib-1", "contributor", CFG, "p0001", [])


def test_edit_closed_post(conn: sqlite3.Connection) -> None:
    make_post(
        conn,
        status="published",
        legacy_id="old-1",
        window=None,
        platform_url="https://example.com/x",
        closed_at="2026-03-01T08:00:00+03:00",
    )
    fail("POST_CLOSED", 5, posts.edit_post, conn, "writer-1", "writer", CFG, "p0001", ["title=x"])
    fail("POST_CLOSED", 5, posts.part_edit, conn, "writer-1", "writer", CFG, "p0001", 1, "x")


def test_edit_approved_text_returns_to_pending(conn: sqlite3.Connection) -> None:
    add(conn)
    approve_post(conn, "p0001")
    old = row(conn, "p0001")["content_hash"]
    out = posts.part_edit(conn, "writer-1", "writer", CFG, "p0001", 1, "Changed text")
    assert out["status"] == "pending_approval"
    p = row(conn, "p0001")
    assert p["content_hash"] != old and p["content_version"] > 1


def test_not_found(conn: sqlite3.Connection) -> None:
    fail("NOT_FOUND", 7, posts.edit_post, conn, "writer-1", "writer", CFG, "p9999", ["title=x"])
    fail("NOT_FOUND", 7, posts.check_post, conn, CFG, "p9999")
    fail("NOT_FOUND", 7, posts.submit_post, conn, "writer-1", "writer", CFG, "p9999")
    fail("NOT_FOUND", 7, posts.add_note, conn, "writer-1", CFG, "p9999", "hi")
    fail("NOT_FOUND", 7, posts.set_keywords, conn, "writer-1", CFG, "p9999", ["a"])
    fail("NOT_FOUND", 7, posts.part_rm, conn, "writer-1", "writer", CFG, "p9999", 1)


# --- parts -------------------------------------------------------------------------------


def test_part_move_keeps_media_with_text(conn: sqlite3.Connection) -> None:
    pid = thread(conn)
    two = conn.execute("SELECT id FROM parts WHERE post_id = ? AND pos = 2", (pid,)).fetchone()[0]
    conn.execute(
        "INSERT INTO media (id, part_id, pos, kind, path, sha256, alt_text, bytes)"
        " VALUES ('m1', ?, 1, 'image', 'media/m1.png', ?, 'Alt', 5)",
        (two, "c" * 64),
    )
    content.refresh_hash(conn, pid)
    before = row(conn, pid)["content_hash"]
    posts.part_move(conn, "writer-1", "writer", CFG, pid, 2, 1)
    assert texts(conn, pid) == ["two", "one", "three"]
    attached = conn.execute(
        "SELECT p.text, p.pos FROM media m JOIN parts p ON p.id = m.part_id"
    ).fetchone()
    assert (attached[0], attached[1]) == ("two", 1)
    assert row(conn, pid)["content_hash"] != before
    assert row(conn, pid)["content_hash"] == content.content_hash(conn, pid)


def test_part_add_edit_rm_keep_positions_contiguous(conn: sqlite3.Connection) -> None:
    pid = thread(conn)
    posts.part_add(conn, "writer-1", "writer", CFG, pid, "new", 2)
    assert texts(conn, pid) == ["one", "new", "two", "three"]
    posts.part_add(conn, "writer-1", "writer", CFG, pid, "last")
    assert texts(conn, pid)[-1] == "last"
    posts.part_edit(conn, "writer-1", "writer", CFG, pid, 2, "newer")
    posts.part_rm(conn, "writer-1", "writer", CFG, pid, 1)
    assert texts(conn, pid) == ["newer", "two", "three", "last"]
    positions = [r[0] for r in conn.execute("SELECT pos FROM parts ORDER BY pos")]
    assert positions == [1, 2, 3, 4]
    fail("BAD_ARGS", 2, posts.part_edit, conn, "writer-1", "writer", CFG, pid, 9, "x")
    fail("BAD_ARGS", 2, posts.part_move, conn, "writer-1", "writer", CFG, pid, 1, 9)
    fail("BAD_ARGS", 2, posts.part_add, conn, "writer-1", "writer", CFG, pid, "x", 9)


def test_part_rm_refuses_part_with_media_or_last_part(conn: sqlite3.Connection) -> None:
    pid = add(conn)["id"]
    fail("BAD_ARGS", 2, posts.part_rm, conn, "writer-1", "writer", CFG, pid, 1)
    posts.part_add(conn, "writer-1", "writer", CFG, pid, "two")
    part = conn.execute("SELECT id FROM parts WHERE pos = 1").fetchone()[0]
    conn.execute(
        "INSERT INTO media (id, part_id, pos, kind, path, sha256, alt_text, bytes)"
        " VALUES ('m1', ?, 1, 'image', 'media/m1.png', ?, 'Alt', 5)",
        (part, "c" * 64),
    )
    fail("BAD_ARGS", 2, posts.part_rm, conn, "writer-1", "writer", CFG, pid, 1)


def test_media_add_refreshes_hash(conn: sqlite3.Connection, tmp_path: Path) -> None:
    pid = add(conn, post_type="image")["id"]
    src = tmp_path / "pic.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(16))
    before = row(conn, pid)["content_hash"]
    out = posts.media_add(
        conn, "writer-1", "writer", CFG, tmp_path, pid, 1, src, "An example picture"
    )
    assert out["version"] == 2 and row(conn, pid)["content_hash"] != before
    assert row(conn, pid)["content_hash"] == content.content_hash(conn, pid)
    assert posts.check_post(conn, CFG, pid)["ok"] is True
    fail(
        "ROLE_NOT_ALLOWED",
        4,
        posts.media_add,
        conn,
        "contrib-1",
        "contributor",
        CFG,
        tmp_path,
        pid,
        1,
        src,
        "Alt",
    )


# --- notes and keywords ------------------------------------------------------------------


def test_note_and_keywords_are_not_content(conn: sqlite3.Connection) -> None:
    add(conn)
    before = row(conn, "p0001")
    posts.add_note(conn, "contrib-1", CFG, "p0001", "first")
    posts.add_note(conn, "writer-1", CFG, "p0001", "second")
    posts.set_keywords(conn, "contrib-1", CFG, "p0001", ["alpha", "beta"])
    after = row(conn, "p0001")
    assert after["content_version"] == before["content_version"] == 1
    assert after["content_hash"] == before["content_hash"]
    lines = after["notes"].split("\n")
    assert len(lines) == 2 and lines[0].endswith("contrib-1: first")
    assert json.loads(after["keywords"]) == ["alpha", "beta"]


# --- check and submit --------------------------------------------------------------------


def test_check_is_read_only_and_flags_missing_images(conn: sqlite3.Connection) -> None:
    add(conn, post_type="image")
    events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    fail("MEDIA_INVALID", 3, posts.check_post, conn, CFG, "p0001")
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == events


def test_check_ok_returns_warnings(conn: sqlite3.Connection) -> None:
    add(conn)
    out = posts.check_post(conn, CFG, "p0001")
    assert out["ok"] is True and any("past" in w for w in out["warnings"])


def test_check_carousel_needs_pdf_and_thread_needs_parts(conn: sqlite3.Connection) -> None:
    add(conn, post_type="carousel")
    fail("MEDIA_INVALID", 3, posts.check_post, conn, CFG, "p0001")
    fail("INVALID_POST", 3, add, conn, post_type="thread")
    pid = thread(conn)
    posts.part_rm(conn, "writer-1", "writer", CFG, pid, 3)
    posts.part_rm(conn, "writer-1", "writer", CFG, pid, 2)
    fail("INVALID_POST", 3, posts.check_post, conn, CFG, pid)


def test_check_future_hold(conn: sqlite3.Connection) -> None:
    out = add(conn, hold_until=FUTURE, hold_reason="legal review")
    assert out["ok"] is True
    fail("ON_HOLD", 3, posts.check_post, conn, CFG, "p0001")
    posts.edit_post(conn, "writer-1", "writer", CFG, "p0001", ["hold_until="])
    assert posts.check_post(conn, CFG, "p0001")["ok"] is True


def test_submit_needs_content_change(conn: sqlite3.Connection) -> None:
    add(conn)
    add_approval(conn, "p0001", decision="request_changes", changes_requested="Shorter please")
    conn.execute("UPDATE posts SET status = 'changes_requested' WHERE id = 'p0001'")
    fail("BAD_TRANSITION", 5, posts.submit_post, conn, "writer-1", "writer", CFG, "p0001")
    assert row(conn, "p0001")["status"] == "changes_requested"
    posts.part_edit(conn, "writer-1", "writer", CFG, "p0001", 1, "Shorter text")
    out = posts.submit_post(conn, "writer-1", "writer", CFG, "p0001")
    assert out["status"] == "pending_approval"
    assert conn.execute("SELECT COUNT(*) FROM events WHERE action = 'submit'").fetchone()[0] == 1


def test_submit_from_wrong_state_or_role(conn: sqlite3.Connection) -> None:
    add(conn)
    fail("BAD_TRANSITION", 5, posts.submit_post, conn, "writer-1", "writer", CFG, "p0001")
    conn.execute("UPDATE posts SET status = 'changes_requested' WHERE id = 'p0001'")
    fail("ROLE_NOT_ALLOWED", 4, posts.submit_post, conn, "contrib-1", "contributor", CFG, "p0001")


# --- CLI ---------------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for var in ("BRANDCAL_HOME", "BRANDCAL_AGENT"):
        monkeypatch.delenv(var, raising=False)
    cfg = {"timezone": "+03:00", "agents": AGENTS, "campaigns": [], "pillars": []}
    (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (tmp_path / "platforms.json").write_text(json.dumps(PLATFORMS), encoding="utf-8")
    assert cli.main(["init", "--home", str(tmp_path), "--as", "admin-1"]) == 0
    return tmp_path


def run(
    capsys: pytest.CaptureFixture[str], home: Path, *argv: str, who: str = "writer-1"
) -> tuple[int, Any]:
    code = cli.main(["--home", str(home), "--as", who, *argv])
    return code, json.loads(capsys.readouterr().out)


def feed(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))


def test_cli_add_and_edit_flow(
    home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    feed(monkeypatch, data())
    code, out = run(capsys, home, "add")
    assert code == 0 and out["id"] == "p0001" and out["status"] == "pending_approval"
    code, out = run(capsys, home, "edit", "p0001", "first_comment=Link in comments")
    assert code == 0 and out["version"] == 2
    code, out = run(capsys, home, "part", "add", "p0001", "More text")
    assert code == 0
    code, out = run(capsys, home, "part", "move", "p0001", "2", "1")
    assert code == 0
    code, out = run(capsys, home, "note", "p0001", "a note", who="contrib-1")
    assert code == 0
    code, out = run(capsys, home, "keywords", "p0001", "a", "b", who="contrib-1")
    assert code == 0
    code, out = run(capsys, home, "check", "p0001", who="contrib-1")
    assert out["ok"] is False and out["error"]["code"] == "INVALID_POST"  # one-part text, two parts


def test_cli_window_without_offset(
    home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    feed(monkeypatch, data(window="2026-03-10T09:00:00/2026-03-10T10:00:00"))
    code, out = run(capsys, home, "add")
    assert code == 3 and out["error"]["code"] == "TIME_OFFSET_REQUIRED"


def test_cli_comment_flags_and_roles(
    home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    body = data(target_url="https://example.com/post")
    feed(monkeypatch, body)
    code, out = run(capsys, home, "add", "--type", "comment", who="manager-1")
    assert code == 4 and out["error"]["code"] == "COMMENT_NOT_DELEGATED"
    feed(monkeypatch, body)
    args = ["add", "--type", "comment", "--delegation-msg", "m1", "--delegation-words", "Do it"]
    code, out = run(capsys, home, *args, who="manager-1")
    assert code == 0 and out["id"] == "p0001"


def test_cli_unknown_id_and_bad_json(
    home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out = run(capsys, home, "check", "p0042")
    assert code == 7 and out["error"]["code"] == "NOT_FOUND"
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
    code, out = run(capsys, home, "add")
    assert code == 2 and out["error"]["code"] == "BAD_ARGS"


def test_cli_media_add(
    home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    feed(monkeypatch, data(post_type="image"))
    run(capsys, home, "add")
    pic = home / "pic.png"
    pic.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(16))
    code, out = run(capsys, home, "media", "add", "p0001", "1", str(pic), "--alt", "Example pic")
    assert code == 0 and out["version"] == 2
    code, out = run(capsys, home, "check", "p0001")
    assert code == 0

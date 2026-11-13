"""Hand-written: schedule, unschedule, begin, published and failed (SPEC 6, 7.3, 8.3)."""

from __future__ import annotations

import io
import json
import sqlite3
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from conftest import AGENTS, PLATFORMS, WINDOW

from brandcal import approvals, posts, publish
from brandcal.cli import main
from brandcal.errors import BrandcalError

CFG: dict[str, Any] = {"timezone": "+03:00", "agents": AGENTS}
TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 3, 10, 9, 30, tzinfo=TZ)  # inside WINDOW (09:00-10:00)
OTHER_WINDOW = "2026-03-11T14:00:00+03:00/2026-03-11T15:00:00+03:00"
URL = "https://example.com/posts/1"
DATA: dict[str, Any] = {
    "slug": "example-post",
    "title": "Example Co announcement",
    "platform": "linkedin",
    "post_type": "text",
    "window": WINDOW,
    "parts": [{"text": "Hello from Example Co"}],
}


def png_bytes() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


def approved(conn: sqlite3.Connection, home: Path, media: bool = False, **extra: Any) -> str:
    """Add a post (optionally with one image), approve it through approvals.approve."""
    post = posts.add_post(conn, "writer-1", "writer", CFG, {**DATA, **extra})
    if media:
        src = home.parent / "pic.png"
        src.write_bytes(png_bytes())
        posts.media_add(conn, "writer-1", "writer", CFG, home, post["id"], 1, src, "A pixel")
        post = posts.check_post(conn, CFG, post["id"])
    approvals.approve(
        conn, "manager-1", "manager", CFG, post["id"], post["version"], post["hash"], "card",
        "msg-1", "Approved",
    )  # fmt: skip
    return str(post["id"])


def begin(
    conn: sqlite3.Connection, home: Path, pid: str, who: str = "manager-1", **kw: Any
) -> dict[str, Any]:
    kw.setdefault("now", NOW)
    cfg = kw.pop("cfg", CFG)
    out: dict[str, Any] = publish.begin(conn, who, _role(who), cfg, home, pid, **kw)
    return out


def schedule(
    conn: sqlite3.Connection, home: Path, pid: str, at: str, now: datetime = NOW
) -> dict[str, Any]:
    out: dict[str, Any] = publish.schedule(conn, "manager-1", "manager", CFG, home, pid, at, now)
    return out


def published(conn: sqlite3.Connection, pid: str, url: str = URL, **kw: Any) -> dict[str, Any]:
    kw.setdefault("now", NOW + timedelta(minutes=5))
    out: dict[str, Any] = publish.published(conn, "manager-1", "manager", CFG, pid, url, **kw)
    return out


def _role(who: str) -> str:
    return "manager" if who == "manager-2" else next(a["role"] for a in AGENTS if a["id"] == who)


def fails(code: str, exit_code: int, fn: Any, *args: Any, **kw: Any) -> None:
    with pytest.raises(BrandcalError) as info:
        fn(*args, **kw)
    assert info.value.code.value == code
    assert info.value.exit_code == exit_code


def row(conn: sqlite3.Connection, pid: str) -> sqlite3.Row:
    r: sqlite3.Row = conn.execute("SELECT * FROM posts WHERE id = ?", (pid,)).fetchone()
    return r


def actions(conn: sqlite3.Connection, pid: str) -> list[str]:
    rows = conn.execute("SELECT action FROM events WHERE post_id = ? ORDER BY id", (pid,))
    return [r[0] for r in rows]


# --- window binding ----------------------------------------------------------------------


def test_begin_and_schedule_need_the_approved_window(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    posts.edit_post(conn, "manager-1", "manager", CFG, pid, [f"window={OTHER_WINDOW}"])
    fails(
        "WINDOW_NOT_APPROVED",
        6,
        begin,
        conn,
        home,
        pid,
        now=datetime(2026, 3, 11, 14, 30, tzinfo=TZ),
    )
    at = "2026-03-11T14:30:00+03:00"
    fails(
        "WINDOW_NOT_APPROVED",
        6,
        schedule,
        conn,
        home,
        pid,
        at,
        datetime(2026, 3, 11, 14, 0, tzinfo=TZ),
    )
    assert row(conn, pid)["claimed_by"] is None and row(conn, pid)["native_scheduled_at"] is None


def test_schedule_at_must_be_inside_the_window(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    fails("WINDOW_NOT_APPROVED", 6, schedule, conn, home, pid, "2026-03-10T11:00:00+03:00")
    fails("WINDOW_NOT_APPROVED", 6, schedule, conn, home, pid, "2026-03-10T10:00:00+03:00")
    fails("TIME_OFFSET_REQUIRED", 3, schedule, conn, home, pid, "2026-03-10T09:30:00")
    assert row(conn, pid)["native_scheduled_at"] is None


def test_begin_only_inside_the_window_now(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    fails(
        "WINDOW_NOT_APPROVED",
        6,
        begin,
        conn,
        home,
        pid,
        now=datetime(2026, 3, 10, 10, 0, tzinfo=TZ),
    )
    fails(
        "WINDOW_NOT_APPROVED",
        6,
        begin,
        conn,
        home,
        pid,
        now=datetime(2026, 3, 10, 8, 59, tzinfo=TZ),
    )
    assert begin(conn, home, pid, now=datetime(2026, 3, 10, 9, 0, tzinfo=TZ))["ok"] is True


def test_media_changed_on_disk_is_a_hash_mismatch(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home, media=True)
    path = home / conn.execute("SELECT path FROM media").fetchone()[0]
    path.chmod(0o644)
    path.write_bytes(png_bytes() + b"tampered")
    fails("HASH_MISMATCH", 6, begin, conn, home, pid)
    fails("HASH_MISMATCH", 6, schedule, conn, home, pid, "2026-03-10T09:45:00+03:00")
    assert row(conn, pid)["claimed_by"] is None


def test_begin_returns_media_with_absolute_paths(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home, media=True, first_comment="More at example.com")
    out = begin(conn, home, pid)
    media = out["parts"][0]["media"][0]
    assert Path(media["path"]).is_absolute() and Path(media["path"]).is_file()
    assert (media["alt_text"], media["kind"]) == ("A pixel", "image")
    assert (out["first_comment"], out["platform"]) == ("More at example.com", "linkedin")
    r = row(conn, pid)
    assert (out["hash"], out["version"]) == (r["content_hash"], r["content_version"])


def test_hold_blocks_schedule_and_begin(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    posts.edit_post(
        conn, "manager-1", "manager", CFG, pid, ["hold_until=2099-01-01T00:00:00+03:00"]
    )
    fails("ON_HOLD", 3, schedule, conn, home, pid, "2026-03-10T09:45:00+03:00")
    fails("ON_HOLD", 3, begin, conn, home, pid)


def test_begin_and_schedule_need_an_approved_post(conn: sqlite3.Connection, home: Path) -> None:
    post = posts.add_post(conn, "writer-1", "writer", CFG, DATA)
    fails("BAD_TRANSITION", 5, begin, conn, home, post["id"])
    fails("BAD_TRANSITION", 5, schedule, conn, home, post["id"], "2026-03-10T09:45:00+03:00")
    fails("NOT_FOUND", 7, begin, conn, home, "p9999")


@pytest.mark.parametrize("who", ["writer-1", "approver-1", "admin-1"])
def test_only_the_manager_publishes(conn: sqlite3.Connection, home: Path, who: str) -> None:
    pid = approved(conn, home)
    role = _role(who)
    at = "2026-03-10T09:45:00+03:00"
    fails("ROLE_NOT_ALLOWED", 4, publish.begin, conn, who, role, CFG, home, pid, now=NOW)
    fails("ROLE_NOT_ALLOWED", 4, publish.schedule, conn, who, role, CFG, home, pid, at, NOW)
    fails("ROLE_NOT_ALLOWED", 4, publish.unschedule, conn, who, role, CFG, pid)
    fails("ROLE_NOT_ALLOWED", 4, publish.published, conn, who, role, CFG, pid, URL)
    fails("ROLE_NOT_ALLOWED", 4, publish.failed, conn, who, role, CFG, pid, "x")


# --- schedule and unschedule -------------------------------------------------------------


def test_schedule_sets_the_time_and_is_idempotent(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    out = schedule(conn, home, pid, "2026-03-10T06:45:00Z")  # same instant, other offset
    assert out["ok"] is True and out["native_scheduled_at"] == "2026-03-10T09:45:00+03:00"
    assert row(conn, pid)["native_scheduled_at"] == "2026-03-10T09:45:00+03:00"
    assert actions(conn, pid)[-1] == "schedule"
    n = len(actions(conn, pid))
    again = schedule(conn, home, pid, "2026-03-10T09:45:00+03:00")
    assert again["ok"] is True and again["note"] == "already scheduled"
    assert len(actions(conn, pid)) == n


def test_schedule_refused_when_claimed(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    begin(conn, home, pid)
    fails("CLAIMED", 8, schedule, conn, home, pid, "2026-03-10T09:45:00+03:00")


def test_unschedule_clears_and_is_a_no_op_when_not_scheduled(
    conn: sqlite3.Connection, home: Path
) -> None:
    pid = approved(conn, home)
    out = publish.unschedule(conn, "manager-1", "manager", CFG, pid, NOW)
    assert out["ok"] is True and out["note"] == "not scheduled"
    assert "unschedule" not in actions(conn, pid)
    schedule(conn, home, pid, "2026-03-10T09:45:00+03:00")
    out = publish.unschedule(conn, "manager-1", "manager", CFG, pid, NOW)
    assert out["ok"] is True and "note" not in out
    assert row(conn, pid)["native_scheduled_at"] is None
    assert actions(conn, pid)[-1] == "unschedule"


# --- begin -------------------------------------------------------------------------------


def test_begin_refused_while_natively_scheduled(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    schedule(conn, home, pid, "2026-03-10T09:45:00+03:00")
    fails("NATIVELY_SCHEDULED", 5, begin, conn, home, pid)
    publish.unschedule(conn, "manager-1", "manager", CFG, pid, NOW)
    assert begin(conn, home, pid)["ok"] is True


def test_begin_twice_by_the_same_manager_is_idempotent(
    conn: sqlite3.Connection, home: Path
) -> None:
    pid = approved(conn, home, media=True)
    first = begin(conn, home, pid)
    n = len(actions(conn, pid))
    second = begin(conn, home, pid, now=NOW + timedelta(minutes=5))
    assert second == first
    assert row(conn, pid)["claim_expires"] == first["claim_expires"] == "2026-03-10T10:00:00+03:00"
    assert row(conn, pid)["claimed_by"] == "manager-1"
    assert len(actions(conn, pid)) == n


def test_begin_refused_when_someone_else_holds_the_claim(
    conn: sqlite3.Connection, home: Path
) -> None:
    conn.execute("INSERT INTO agents (id, role) VALUES ('manager-2', 'manager')")
    pid = approved(conn, home)
    begin(conn, home, pid)
    fails("CLAIMED", 8, begin, conn, home, pid, who="manager-2")


def test_claim_length_comes_from_the_config(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    out = begin(conn, home, pid, cfg={**CFG, "claim_minutes": 10})
    assert out["claim_expires"] == "2026-03-10T09:40:00+03:00"


def test_expired_claim_needs_a_live_check(conn: sqlite3.Connection, home: Path) -> None:
    cfg = {**CFG, "claim_minutes": 10}
    pid = approved(conn, home)
    begin(conn, home, pid, cfg=cfg)
    later = NOW + timedelta(minutes=15)
    fails("CHECK_LIVE_FIRST", 8, begin, conn, home, pid, cfg=cfg, now=later)
    assert begin(conn, home, pid, cfg=cfg, now=later, not_live=True)["ok"] is True
    detail = json.loads(
        conn.execute(
            "SELECT detail FROM events WHERE post_id = ? AND action = 'begin' ORDER BY id DESC",
            (pid,),
        ).fetchone()[0]
    )
    assert detail["not_live"] is True


# --- published and failed ----------------------------------------------------------------


def test_published_closes_the_post(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    begin(conn, home, pid)
    out = published(conn, pid)
    assert out["ok"] is True and out["status"] == "published"
    r = row(conn, pid)
    assert (r["status"], r["platform_url"]) == ("published", URL)
    assert r["closed_at"] == r["published_at"] == "2026-03-10T09:35:00+03:00"
    assert (r["native_scheduled_at"], r["claimed_by"], r["claim_expires"]) == (None,) * 3
    assert actions(conn, pid)[-1] == "published"


def test_published_twice_same_url_ok_other_url_conflicts(
    conn: sqlite3.Connection, home: Path
) -> None:
    pid = approved(conn, home)
    begin(conn, home, pid)
    published(conn, pid)
    n = len(actions(conn, pid))
    again = published(conn, pid)
    assert again["ok"] is True and again["note"] == "already published"
    assert len(actions(conn, pid)) == n
    fails("URL_CONFLICT", 8, published, conn, pid, "https://example.com/other")
    assert row(conn, pid)["platform_url"] == URL


def test_published_from_a_native_schedule(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    schedule(conn, home, pid, "2026-03-10T09:45:00+03:00")
    out = published(conn, pid, now=datetime(2026, 3, 10, 12, 0, tzinfo=TZ))  # after the window
    assert out["status"] == "published"
    assert row(conn, pid)["native_scheduled_at"] is None


def test_published_accepted_after_the_claim_expired(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    begin(conn, home, pid)
    assert published(conn, pid, now=NOW + timedelta(hours=2))["status"] == "published"


def test_published_needs_a_claim_or_a_schedule(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    fails("BAD_TRANSITION", 5, published, conn, pid)
    assert row(conn, pid)["status"] == "approved"


def test_published_by_another_manager_is_refused(conn: sqlite3.Connection, home: Path) -> None:
    conn.execute("INSERT INTO agents (id, role) VALUES ('manager-2', 'manager')")
    pid = approved(conn, home)
    begin(conn, home, pid)
    fails(
        "BAD_TRANSITION", 5, publish.published, conn, "manager-2", "manager", CFG, pid, URL, now=NOW
    )


def test_published_url_must_be_http(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    begin(conn, home, pid)
    for bad in ("ftp://example.com/x", "example.com/x", "https://", " "):
        fails("BAD_ARGS", 2, published, conn, pid, bad)
    assert row(conn, pid)["status"] == "approved"


def test_published_records_part_urls(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(
        conn,
        home,
        post_type="thread",
        parts=[{"text": "One from Example Co"}, {"text": "Two from Example Co"}],
    )
    begin(conn, home, pid)
    fails("BAD_ARGS", 2, published, conn, pid, part_urls={3: "https://example.com/p/3"})
    published(conn, pid, part_urls={1: "https://example.com/p/1", 2: "https://example.com/p/2"})
    urls = conn.execute("SELECT platform_url FROM parts WHERE post_id = ? ORDER BY pos", (pid,))
    assert [u[0] for u in urls] == ["https://example.com/p/1", "https://example.com/p/2"]


def test_failed_releases_the_claim(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    fails("BAD_TRANSITION", 5, publish.failed, conn, "manager-1", "manager", CFG, pid, "x", NOW)
    begin(conn, home, pid)
    out = publish.failed(conn, "manager-1", "manager", CFG, pid, "Login expired", NOW)
    assert out["ok"] is True and out["status"] == "approved"
    r = row(conn, pid)
    assert (r["status"], r["claimed_by"], r["claim_expires"]) == ("approved", None, None)
    event = conn.execute(
        "SELECT actor, reason, from_status, to_status FROM events"
        " WHERE post_id = ? AND action = 'publish_failed'",
        (pid,),
    ).fetchone()
    assert tuple(event) == ("manager-1", "Login expired", "approved", "approved")
    # A failed attempt is not an expired claim: the next begin goes straight through.
    assert begin(conn, home, pid)["ok"] is True


# --- CLI ---------------------------------------------------------------------------------


@pytest.fixture
def cli_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "config.json").write_text(json.dumps(CFG), encoding="utf-8")
    (tmp_path / "platforms.json").write_text(json.dumps(PLATFORMS), encoding="utf-8")
    monkeypatch.setenv("BRANDCAL_HOME", str(tmp_path))
    monkeypatch.delenv("BRANDCAL_AGENT", raising=False)
    monkeypatch.delenv("BRANDCAL_TZ", raising=False)
    return tmp_path


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any]]:
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_cli_publish_flow(
    cli_home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A window covering all of today (display timezone), so the real clock is inside it.
    if datetime.now(TZ).strftime("%H:%M") >= "23:58":
        pytest.skip("too close to local midnight for a real-clock window")
    day = datetime.now(TZ).strftime("%Y-%m-%d")
    window = f"{day}T00:00:00+03:00/{day}T23:59:58+03:00"
    run(capsys, "init", "--as", "admin-1")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({**DATA, "window": window})))
    added = run(capsys, "add", "--as", "writer-1")[1]
    pid = added["id"]
    code, out = run(capsys, "begin", pid, "--as", "manager-1")
    assert (code, out["error"]["code"]) == (5, "BAD_TRANSITION")
    run(
        capsys, "approve", pid, "--version", "1", "--hash", added["hash"], "--channel", "card",
        "--msg", "m1", "--words", "ok", "--as", "manager-1",
    )  # fmt: skip
    code, out = run(capsys, "begin", pid, "--as", "writer-1")
    assert (code, out["error"]["code"]) == (4, "ROLE_NOT_ALLOWED")

    at = f"{day}T12:00:00+03:00"
    assert run(capsys, "schedule", pid, "--at", at, "--as", "manager-1")[0] == 0
    code, out = run(capsys, "begin", pid, "--as", "manager-1")
    assert (code, out["error"]["code"]) == (5, "NATIVELY_SCHEDULED")
    assert run(capsys, "unschedule", pid, "--as", "manager-1")[0] == 0

    code, first = run(capsys, "begin", pid, "--as", "manager-1")
    assert code == 0 and first["parts"][0]["text"] == "Hello from Example Co"
    assert run(capsys, "begin", pid, "--as", "manager-1") == (0, first)
    code, out = run(capsys, "schedule", pid, "--at", at, "--as", "manager-1")
    assert (code, out["error"]["code"]) == (8, "CLAIMED")
    assert run(capsys, "failed", pid, "--reason", "Login expired", "--as", "manager-1")[0] == 0
    assert run(capsys, "begin", pid, "--not-live", "--as", "manager-1")[0] == 0

    code, out = run(capsys, "published", pid, URL, "--part", "1", URL, "--as", "manager-1")
    assert (code, out["status"]) == (0, "published")
    code, out = run(capsys, "published", pid, URL, "--as", "manager-1")
    assert (code, out["note"]) == (0, "already published")
    code, out = run(capsys, "published", pid, "https://example.com/x", "--as", "manager-1")
    assert (code, out["error"]["code"]) == (8, "URL_CONFLICT")
    code, out = run(capsys, "published", pid, URL, "--part", "x", URL, "--as", "manager-1")
    assert (code, out["error"]["code"]) == (2, "BAD_ARGS")

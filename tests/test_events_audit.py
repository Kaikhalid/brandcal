"""Hand-written: the read-only audit of hash chains, published posts and media (SPEC 7.3, 10.5)."""

from __future__ import annotations

import json
import sqlite3
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from conftest import AGENTS, add_approval, make_post

from brandcal import approvals, events, posts, publish
from brandcal.audit import audit
from brandcal.cli import main

CFG: dict[str, Any] = {"timezone": "+03:00", "agents": AGENTS}
NOW = datetime(2026, 3, 10, 9, 30, tzinfo=timezone(timedelta(hours=3)))
WINDOW = "2026-03-10T09:00:00+03:00/2026-03-10T10:00:00+03:00"
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


def approve(conn: sqlite3.Connection, pid: str) -> None:
    post = posts.check_post(conn, CFG, pid)
    approvals.approve(
        conn, "manager-1", "manager", CFG, pid, post["version"], post["hash"], "card", "m1", "OK"
    )


def lifecycle(conn: sqlite3.Connection, home: Path, media: bool = False) -> str:
    """add, submit, approve, edit after approval, approve again, begin, published."""
    pid = str(posts.add_post(conn, "writer-1", "writer", CFG, DATA)["id"])
    if media:
        src = home.parent / "pic.png"
        src.write_bytes(png_bytes())
        posts.media_add(conn, "writer-1", "writer", CFG, home, pid, 1, src, "A pixel")
    approve(conn, pid)
    posts.edit_post(conn, "writer-1", "writer", CFG, pid, ["first_comment=More at example.com"])
    approve(conn, pid)
    publish.begin(conn, "manager-1", "manager", CFG, home, pid, now=NOW)
    publish.published(conn, "manager-1", "manager", CFG, pid, "https://example.com/p/1", now=NOW)
    return pid


def kinds(report: dict[str, Any]) -> list[str]:
    return [f["kind"] for f in report["flags"]]


def drop(conn: sqlite3.Connection, *names: str) -> None:
    for name in names:
        conn.execute(f"DROP TRIGGER {name}")


def test_full_lifecycle_is_clean(conn: sqlite3.Connection, home: Path) -> None:
    pid = lifecycle(conn, home)
    report = audit(conn, home)
    assert report["ok"] is True
    assert report["flags"] == []
    assert report["checked"]["chains"] >= 1
    assert report["checked"]["published"] == 1
    rows = conn.execute("SELECT * FROM events WHERE chain = ? ORDER BY id", (f"post:{pid}",))
    prev = None
    count = 0
    for r in rows:
        assert r["prev_hash"] == prev
        prev = r["row_hash"]
        count += 1
    assert count >= 6
    assert report["checked"]["events"] == conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def test_tampered_detail_is_flagged(conn: sqlite3.Connection, home: Path) -> None:
    lifecycle(conn, home)
    target = conn.execute("SELECT id FROM events WHERE detail IS NOT NULL LIMIT 1").fetchone()[0]
    drop(conn, "events_no_update")
    conn.execute("UPDATE events SET detail = ? WHERE id = ?", (json.dumps({"x": 1}), target))
    report = audit(conn, home)
    assert report["ok"] is False
    assert [(f["kind"], f["event_id"]) for f in report["flags"]] == [("chain_tampered", target)]


def test_deleted_middle_event_is_a_gap(conn: sqlite3.Connection, home: Path) -> None:
    pid = lifecycle(conn, home)
    ids = [
        r[0] for r in conn.execute("SELECT id FROM events WHERE post_id = ? ORDER BY id", (pid,))
    ]
    conn.execute("UPDATE archive_lock SET active = 1")
    conn.execute("DELETE FROM events WHERE id = ?", (ids[2],))
    conn.execute("UPDATE archive_lock SET active = 0")
    report = audit(conn, home)
    assert [(f["kind"], f["event_id"]) for f in report["flags"]] == [("chain_gap", ids[3])]


def test_post_less_month_chains_verify(conn: sqlite3.Connection, home: Path) -> None:
    for month, n in (("2026-03", 2), ("2026-04", 1)):
        for _ in range(n):
            events.append_event(
                conn, at="2026-03-01T08:00:00+03:00", actor="system", action="sweep",
                chain=f"month:{month}",
            )  # fmt: skip
    report = audit(conn, home)
    assert report["ok"] is True
    assert report["checked"] == {
        "chains": 2,
        "events": 3,
        "published": 0,
        "media": 0,
        "archives": 0,
    }


def test_published_without_matching_approval_is_flagged(
    conn: sqlite3.Connection, home: Path
) -> None:
    make_post(
        conn,
        id="p0009",
        slug="legacy",
        legacy_id="L9",
        status="published",
        closed_at="2026-03-10T10:00:00+03:00",
    )
    add_approval(conn, "p0009", content_hash="b" * 64)
    report = audit(conn, home)
    assert ("published_unapproved", "p0009") in [(f["kind"], f["post"]) for f in report["flags"]]


def test_changed_and_missing_media(conn: sqlite3.Connection, home: Path) -> None:
    lifecycle(conn, home, media=True)
    path = conn.execute("SELECT path FROM media").fetchone()[0]
    assert audit(conn, home)["checked"]["media"] == 1
    (home / path).chmod(0o644)
    (home / path).write_bytes(b"changed")
    assert kinds(audit(conn, home)) == ["media_changed"]
    (home / path).unlink()
    assert kinds(audit(conn, home)) == ["media_missing"]


def test_content_changed_after_publish(conn: sqlite3.Connection, home: Path) -> None:
    pid = lifecycle(conn, home)
    drop(conn, *[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")])
    conn.execute("UPDATE parts SET text = 'Edited' WHERE post_id = ?", (pid,))
    assert kinds(audit(conn, home)) == ["content_changed"]


def snapshot(home: Path) -> tuple[bytes, int]:
    wal = home / "brand.db-wal"
    return (home / "brand.db").read_bytes(), wal.stat().st_size if wal.exists() else 0


def test_audit_is_read_only(conn: sqlite3.Connection, home: Path) -> None:
    lifecycle(conn, home)
    db = Path(conn.execute("PRAGMA database_list").fetchone()["file"])
    before = snapshot(db.parent)
    count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    audit(conn, home)
    assert not conn.in_transaction
    assert snapshot(db.parent) == before
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == count


def test_cli_audit_round_trip(conn: sqlite3.Connection, capsys: pytest.CaptureFixture[str]) -> None:
    base = Path(conn.execute("PRAGMA database_list").fetchone()["file"]).parent
    (base / "config.json").write_text(json.dumps(CFG), encoding="utf-8")
    lifecycle(conn, base)
    before = snapshot(base)
    assert main(["--home", str(base), "audit"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert snapshot(base) == before
    drop(conn, "events_no_update")
    conn.execute("UPDATE events SET reason = 'x' WHERE id = 1")
    assert main(["--home", str(base), "audit"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["flags"][0]["kind"] == "chain_tampered"

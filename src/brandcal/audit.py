"""Read-only audit: hash chains, published posts and media checksums (SPEC 7.3 point 6, 10.5)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from brandcal import content, media
from brandcal.events import row_hash

# Signed approvals are audited from T15.


def chain_flags(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], int, int]:
    flags: list[dict[str, Any]] = []
    chains = events = 0
    current: str | None = None
    expected_prev: str | None = None
    for r in conn.execute("SELECT * FROM events ORDER BY chain, id"):
        events += 1
        if r["chain"] != current:
            current, expected_prev = r["chain"], None
            chains += 1
        own = row_hash(
            r["prev_hash"], r["at"], r["actor"], r["post_id"], r["action"],
            r["from_status"], r["to_status"], r["detail"], r["reason"], r["chain"],
        )  # fmt: skip
        problem: tuple[str, str] | None = None
        if r["prev_hash"] != expected_prev:
            problem = ("chain_gap", "prev_hash does not match the previous row")
        elif r["row_hash"] != own:
            problem = ("chain_tampered", "row_hash does not match the row's fields")
        if problem:
            flags.append(
                {"kind": problem[0], "chain": current, "event_id": r["id"], "detail": problem[1]}
            )
        expected_prev = r["row_hash"]
    return flags, chains, events


def _published_flags(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], int]:
    flags: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT id, content_version, content_hash FROM posts WHERE status = 'published' ORDER BY id"
    ).fetchall()
    for p in rows:
        ok = conn.execute(
            "SELECT 1 FROM approvals WHERE post_id = ? AND content_version = ? AND content_hash = ?"
            " AND (decision IN ('approve', 'reschedule') OR channel = 'legacy') LIMIT 1",
            (p["id"], p["content_version"], p["content_hash"]),
        ).fetchone()
        if ok is None:
            detail = "no approval for the current version and hash"
            flags.append({"kind": "published_unapproved", "post": p["id"], "detail": detail})
        if content.content_hash(conn, p["id"]) != p["content_hash"]:
            detail = "content hash recomputed now differs from the stored hash"
            flags.append({"kind": "content_changed", "post": p["id"], "detail": detail})
    return flags, len(rows)


def _media_flags(conn: sqlite3.Connection, home: Path) -> tuple[list[dict[str, Any]], int]:
    flags: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT p.post_id, COUNT(*) AS n FROM media m JOIN parts p ON p.id = m.part_id"
        " GROUP BY p.post_id ORDER BY p.post_id"
    ).fetchall()
    for r in rows:
        for bad in media.verify_media(conn, home, r["post_id"]):
            kind = "media_missing" if bad["actual"] == "missing" else "media_changed"
            detail = f"{bad['path']}: file differs from the recorded checksum"
            flags.append({"kind": kind, "post": r["post_id"], "detail": detail})
    return flags, sum(r["n"] for r in rows)


def open_archive(path: Path) -> sqlite3.Connection:
    """An archive file opened read-only (SPEC 10.7); rows come back as sqlite3.Row."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _inside_flags(
    arc: sqlite3.Connection, home: Path, rel: str, detail: dict[str, Any]
) -> list[dict[str, Any]]:
    """Chains, manifest posts, chain tails and published media of one open archive file."""
    flags: list[dict[str, Any]] = [
        {**flag, "kind": "archive_chain", "file": rel} for flag in chain_flags(arc)[0]
    ]
    for item in detail["manifest"]:
        pid = item["post_id"]
        post = arc.execute("SELECT status FROM posts WHERE id = ?", (pid,)).fetchone()
        if post is None:
            msg = "manifest post is missing from the archive file"
            flags.append({"kind": "archive_post_missing", "file": rel, "post": pid, "detail": msg})
            continue
        last = arc.execute(
            "SELECT row_hash FROM events WHERE chain = ? ORDER BY id DESC LIMIT 1", (f"post:{pid}",)
        ).fetchone()
        if (last[0] if last else "") != item["last_row_hash"]:
            msg = "last event of the post's chain differs from the manifest"
            flags.append({"kind": "archive_chain_tail", "file": rel, "post": pid, "detail": msg})
        if post["status"] != "published":
            continue  # cancelled media sits in _trash and may be removed
        for m in arc.execute(
            "SELECT m.path, m.sha256 FROM media m JOIN parts p ON p.id = m.part_id"
            " WHERE p.post_id = ? ORDER BY m.id",
            (pid,),
        ):
            file = home / m["path"]
            if not file.is_file() or _sha256(file) != m["sha256"]:
                msg = f"{m['path']}: file is missing or differs from the recorded checksum"
                flags.append({"kind": "archive_media", "file": rel, "post": pid, "detail": msg})
    return flags


def _archive_flags(conn: sqlite3.Connection, home: Path) -> tuple[list[dict[str, Any]], int]:
    """Check every archive_written event against its file, read-only (SPEC 7.3 point 6, 10.5)."""
    flags: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT detail FROM events WHERE action = 'archive_written' ORDER BY id"
    ).fetchall()
    for row in rows:
        detail = json.loads(row["detail"])
        rel = str(detail.get("file"))
        path = home / rel
        if not path.is_file():
            msg = "archive file not found"
            flags.append({"kind": "archive_missing", "file": rel, "detail": msg})
            continue
        if detail.get("sha256") and _sha256(path) != detail["sha256"]:
            msg = "archive file differs from its archive_written checksum"
            flags.append({"kind": "archive_changed", "file": rel, "detail": msg})
        if "manifest" not in detail:
            continue
        try:
            arc = open_archive(path)
            try:
                flags += _inside_flags(arc, home, rel, detail)
            finally:
                arc.close()
        except sqlite3.DatabaseError as err:
            flags.append({"kind": "archive_chain", "file": rel, "detail": f"unreadable: {err}"})
    return flags, len(rows)


def audit(conn: sqlite3.Connection, home: Path) -> dict[str, Any]:
    """Check the whole database without writing anything; the caller reads ``ok`` and ``flags``."""
    chain_problems, chains, events = chain_flags(conn)
    published_flags, published = _published_flags(conn)
    media_flags, media_count = _media_flags(conn, home)
    archive_flags, archives = _archive_flags(conn, home)
    flags = chain_problems + published_flags + media_flags + archive_flags
    return {
        "ok": not flags,
        "flags": flags,
        "checked": {
            "chains": chains,
            "events": events,
            "published": published,
            "media": media_count,
            "archives": archives,
        },
    }

"""Read-only audit: hash chains, published posts and media checksums (SPEC 7.3 point 6, 10.5)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from brandcal import content, media
from brandcal.events import row_hash

# Archive file checksums, manifests and signed approvals are audited from T13 and T15.


def _chain_flags(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], int, int]:
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


def audit(conn: sqlite3.Connection, home: Path) -> dict[str, Any]:
    """Check the whole database without writing anything; the caller reads ``ok`` and ``flags``."""
    chain_flags, chains, events = _chain_flags(conn)
    published_flags, published = _published_flags(conn)
    media_flags, media_count = _media_flags(conn, home)
    flags = chain_flags + published_flags + media_flags
    return {
        "ok": not flags,
        "flags": flags,
        "checked": {
            "chains": chains,
            "events": events,
            "published": published,
            "media": media_count,
        },
    }

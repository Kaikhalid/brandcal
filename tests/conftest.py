"""Shared fixtures: a fresh database seeded with fake agents and platforms."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import timedelta, timezone, tzinfo
from pathlib import Path

import pytest

from brandcal.db import init_db, open_db

AGENTS: list[dict[str, str]] = [
    {"id": "writer-1", "role": "writer"},
    {"id": "manager-1", "role": "manager"},
    {"id": "approver-1", "role": "approver"},
    {"id": "contrib-1", "role": "contributor"},
    {"id": "admin-1", "role": "admin"},
    {"id": "system", "role": "system"},
]

PLATFORMS: dict[str, dict[str, object]] = {
    "linkedin": {"chars_per_post": 3000, "images_per_post": 9, "image_mb": 5},
    "x": {"premium": False, "chars_per_post": 280, "images_per_post": 4, "image_mb": 5},
}

WINDOW = "2026-03-10T09:00:00+03:00/2026-03-10T10:00:00+03:00"
STAMP = "2026-03-01T08:00:00+03:00"


@pytest.fixture
def tz() -> tzinfo:
    return timezone(timedelta(hours=3))


@pytest.fixture
def conn(tmp_path: Path, tz: tzinfo) -> Iterator[sqlite3.Connection]:
    db = open_db(tmp_path / "brand.db", tz)
    init_db(db, AGENTS, PLATFORMS)
    yield db
    db.close()


def make_post(conn: sqlite3.Connection, **overrides: object) -> str:
    """Insert a valid pending_approval post with one part; return its id."""
    row: dict[str, object] = {
        "id": "p0001",
        "slug": "example-post",
        "title": "Example Co announcement",
        "platform": "linkedin",
        "post_type": "text",
        "status": "pending_approval",
        "owner": "writer-1",
        "window": WINDOW,
        "content_hash": "a" * 64,
        "created_at": STAMP,
        "updated_at": STAMP,
    }
    row.update(overrides)
    cols = ", ".join(f'"{c}"' for c in row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO posts ({cols}) VALUES ({marks})", tuple(row.values()))
    conn.execute(
        "INSERT INTO parts (post_id, pos, text) VALUES (?, 1, ?)",
        (row["id"], "Hello from Example Co"),
    )
    # Adding the first part counted as a content edit; a new post starts at version 1.
    conn.execute("UPDATE posts SET content_version = 1 WHERE id = ?", (row["id"],))
    return str(row["id"])


def add_approval(conn: sqlite3.Connection, post_id: str, **overrides: object) -> None:
    """Insert an approvals row matching the post's current version and hash."""
    post = conn.execute(
        'SELECT content_version, content_hash, "window" FROM posts WHERE id = ?', (post_id,)
    ).fetchone()
    row: dict[str, object] = {
        "post_id": post_id,
        "decision": "approve",
        "content_version": post["content_version"],
        "content_hash": post["content_hash"],
        "window": post["window"],
        "decided_by": "approver-1",
        "channel": "card",
        "relayed_by": "manager-1",
        "recorded_by": "manager-1",
        "source_message_id": "msg-1",
        "approver_words": "Looks good",
        "decided_at": STAMP,
    }
    row.update(overrides)
    cols = ", ".join(f'"{c}"' for c in row)
    marks = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO approvals ({cols}) VALUES ({marks})", tuple(row.values()))


def approve_post(conn: sqlite3.Connection, post_id: str) -> None:
    """Record a matching approval and move the post to approved."""
    add_approval(conn, post_id)
    conn.execute("UPDATE posts SET status = 'approved' WHERE id = ?", (post_id,))

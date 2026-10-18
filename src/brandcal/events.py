"""Append-only event log with per-chain hashes (SPEC 5.3, 10.5).

Chains are ``post:<id>`` for post events and ``month:YYYY-MM`` (local month) for
post-less events. ``row_hash`` covers the previous hash and every field of the row,
so an edited or missing row breaks the chain. Verification lives in the audit (T10).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3


def row_hash(
    prev_hash: str | None,
    at: str,
    actor: str,
    post_id: str | None,
    action: str,
    from_status: str | None,
    to_status: str | None,
    detail: str | None,
    reason: str | None,
    chain: str,
) -> str:
    """SHA-256 (hex) of the canonical JSON array of the row's fields."""
    fields = [prev_hash, at, actor, post_id, action, from_status, to_status, detail, reason, chain]
    payload = json.dumps(fields, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def chain_for(post_id: str | None, month_key: str) -> str:
    """Chain name for an event: per post, or per local month for post-less events."""
    return f"post:{post_id}" if post_id else f"month:{month_key}"


def last_hash(conn: sqlite3.Connection, chain: str) -> str | None:
    row = conn.execute(
        "SELECT row_hash FROM events WHERE chain = ? ORDER BY id DESC LIMIT 1", (chain,)
    ).fetchone()
    return None if row is None else str(row[0])


def append_event(
    conn: sqlite3.Connection,
    *,
    at: str,
    actor: str,
    action: str,
    chain: str,
    post_id: str | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    detail: dict[str, object] | None = None,
    reason: str | None = None,
) -> int:
    """Insert one event at the end of its chain and return its id."""
    detail_text = None if detail is None else json.dumps(detail, sort_keys=True)
    prev = last_hash(conn, chain)
    h = row_hash(
        prev, at, actor, post_id, action, from_status, to_status, detail_text, reason, chain
    )
    cur = conn.execute(
        "INSERT INTO events (at, actor, post_id, action, from_status, to_status, detail, reason,"
        " chain, prev_hash, row_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (at, actor, post_id, action, from_status, to_status, detail_text, reason, chain, prev, h),
    )
    return int(cur.lastrowid or 0)

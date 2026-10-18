"""The sweep: mark missed posts, release expired claims, list overdue native queues (SPEC 6)."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from brandcal.approvals import CLEAR, log_event
from brandcal.db import transaction
from brandcal.posts import load_post
from brandcal.publish import stamp
from brandcal.timefmt import to_utc_text


def _ids(conn: sqlite3.Connection, where: str, when: str) -> list[str]:
    sql = f"SELECT id FROM posts WHERE status = 'approved' AND {where} ORDER BY id"
    return [r[0] for r in conn.execute(sql, (when,))]


def sweep(
    conn: sqlite3.Connection,
    cfg: Mapping[str, Any],
    now: datetime | None = None,
    agent: str | None = None,
) -> dict[str, Any]:
    """One transaction as ``system``; ``agent`` (who ran it) goes into each event's detail."""
    moment, at, month = stamp(cfg, now)
    when = to_utc_text(moment)
    run_by: dict[str, object] = {} if agent is None else {"run_by": agent}
    with transaction(conn):
        # Chosen before any claim is released: a post whose claim just ran out is not missed
        # in this run, so the next begin still has to check that it is not already live.
        plain = _ids(
            conn,
            "native_scheduled_at IS NULL AND claimed_by IS NULL AND window_end_utc <= ?",
            when,
        )
        expired = _ids(conn, "claimed_by IS NOT NULL AND datetime(claim_expires) <= ?", when)
        overdue = _ids(conn, "native_scheduled_at IS NOT NULL AND window_end_utc <= ?", when)
        for post_id in plain:
            post = load_post(conn, post_id)
            conn.execute(
                f"UPDATE posts SET status = 'missed', {CLEAR}, updated_at = ? WHERE id = ?",
                (at, post_id),
            )
            detail: dict[str, object] = {"window": post["window"]} | run_by
            log_event(conn, "system", "missed", post, at, month, detail)
        for post_id in expired:
            post = load_post(conn, post_id)
            conn.execute(
                "UPDATE posts SET claimed_by = NULL, claim_expires = NULL, updated_at = ?"
                " WHERE id = ?",
                (at, post_id),
            )
            detail = {"claimed_by": post["claimed_by"], "claim_expires": post["claim_expires"]}
            log_event(conn, "system", "claim_expired", post, at, month, detail | run_by)
    return {"ok": True, "missed": plain, "claims_released": expired, "overdue_native": overdue}

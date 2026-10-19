"""One function per UI action (UI_SPEC 1.2), shared by the CLI and, later, the web server.

Each function returns the CLI's JSON dict and raises the existing errors. Writes take an
``Identity``: the acting agent id and, for a human decision made in the console, the identity
the server verified. The role is always looked up in the config, never taken from the caller.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brandcal import approvals, archive, posts, reports
from brandcal import audit as audit_mod
from brandcal.approvals import Verified
from brandcal.errors import EXIT_CODES, BrandcalError, ErrorCode
from brandcal.transitions import CLOSED, STATES, TRANSITIONS

# Must match the posts.post_type CHECK in schema.sql (SPEC 5.3); test_cli_frame checks this.
POST_TYPES: tuple[str, ...] = (
    "text",
    "image",
    "carousel",
    "thread",
    "article",
    "reshare",
    "video",
    "comment",
)
TIME_FORMAT = "ISO 8601 with an explicit UTC offset, e.g. 2026-03-02T09:00:00+00:00"
EVENTS_LIMIT = 100


@dataclass(frozen=True)
class Identity:
    """Who acts: an agent id and, for console decisions, the verified human identity."""

    agent: str
    verified: Verified | None = None

    def role(self, cfg: Mapping[str, Any]) -> str:
        for agent in cfg.get("agents", []):
            if agent.get("id") == self.agent:
                return str(agent["role"])
        raise BrandcalError(
            ErrorCode.NO_AGENT, f"Unknown agent '{self.agent}'.", "Check config.json agents."
        )


# --- reads -------------------------------------------------------------------------------


def schema() -> dict[str, object]:
    return {
        "ok": True,
        "states": list(STATES),
        "closed_states": sorted(CLOSED),
        "transitions": [{"from": f, "to": t, "roles": list(r)} for f, t, r in TRANSITIONS],
        "post_types": list(POST_TYPES),
        "time_format": TIME_FORMAT,
        "exit_codes": {c.value: int(e) for c, e in EXIT_CODES.items()},
    }


def list_posts(
    conn: sqlite3.Connection,
    cfg: Mapping[str, Any],
    base: Path,
    status: str | None,
    date_from: str | None,
    date_to: str | None,
    platform: str | None,
    closed: bool,
    with_archive: bool,
) -> dict[str, object]:
    rows = reports.list_posts(
        conn, cfg, status, date_from, date_to, platform, closed, with_archive, base
    )
    return {"ok": True, "posts": rows}


def show(conn: sqlite3.Connection, post_id: str, log: bool = False) -> dict[str, object]:
    out: dict[str, object] = reports.show(conn, post_id, log)
    return out


def check(conn: sqlite3.Connection, cfg: Mapping[str, Any], post_id: str) -> dict[str, object]:
    out: dict[str, object] = posts.check_post(conn, cfg, post_id)
    return out


def today(conn: sqlite3.Connection, cfg: Mapping[str, Any], which: str) -> dict[str, object]:
    """``which`` is "today" or "tomorrow"."""
    return {"ok": True, "items": reports.day(conn, cfg, which)}


def audit(conn: sqlite3.Connection, base: Path) -> dict[str, object]:
    out: dict[str, object] = audit_mod.audit(conn, base)
    return out


def events(
    conn: sqlite3.Connection,
    since: int | None = None,
    post: str | None = None,
    actor: str | None = None,
    limit: int = EVENTS_LIMIT,
) -> dict[str, object]:
    """Live events after ``since``, ordered by id; pass ``last_id`` back as ``since`` (4.3)."""
    if since is not None and since < 0:
        raise posts.bad_args("--since must be 0 or more.", "Pass the last_id of the previous call.")
    if limit < 1:
        raise posts.bad_args("--limit must be 1 or more.", f"The default is {EVENTS_LIMIT}.")
    where: list[str] = ["id > ?"]
    params: list[int | str] = [since or 0]
    if post is not None:
        posts.load_post(conn, post)  # NOT_FOUND, or ARCHIVED with the archive show hint
        where.append("post_id = ?")
        params.append(post)
    if actor is not None:
        where.append("actor = ?")
        params.append(actor)
    cols = "id, at, actor, post_id, action, from_status, to_status, reason, detail"
    rows = conn.execute(
        f"SELECT {cols} FROM events WHERE {' AND '.join(where)} ORDER BY id LIMIT ?",
        (*params, limit),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        item["detail"] = None if r["detail"] is None else json.loads(r["detail"])
        items.append(item)
    last_id = items[-1]["id"] if items else (since or 0)
    return {
        "ok": True,
        "events": items,
        "last_id": last_id,
        "next": f"brandcal events --since {last_id}",
    }


def archive_list(base: Path, cfg: Mapping[str, Any], month: str) -> dict[str, object]:
    out: dict[str, object] = archive.list_month(base, cfg, month)
    return out


def archive_show(base: Path, month: str, post_id: str, log: bool = False) -> dict[str, object]:
    out: dict[str, object] = archive.show(base, month, post_id, log)
    return out


def archive_search(base: Path, month: str, text: str) -> dict[str, object]:
    out: dict[str, object] = archive.search(base, month, text)
    return out


def archive_stats(conn: sqlite3.Connection, month: str) -> dict[str, object]:
    out: dict[str, object] = archive.stats(conn, month)
    return out


# --- writes ------------------------------------------------------------------------------


def approve(
    conn: sqlite3.Connection,
    cfg: Mapping[str, Any],
    who: Identity,
    post_id: str,
    version: int,
    hash_prefix: str,
    channel: str,
    msg_id: str,
    words: str,
    relayed_by: str | None = None,
    approver: str | None = None,
) -> dict[str, object]:
    out: dict[str, object] = approvals.approve(
        conn, who.agent, who.role(cfg), cfg, post_id, version, hash_prefix, channel, msg_id,
        words, relayed_by, approver, verified=who.verified,
    )  # fmt: skip
    return out


def request_changes(
    conn: sqlite3.Connection,
    cfg: Mapping[str, Any],
    who: Identity,
    post_id: str,
    version: int,
    hash_prefix: str,
    msg_id: str,
    words: str,
    approver: str | None = None,
    *,
    what: str | None = None,
    where: str | None = None,
    instruction: str | None = None,
    channel: str = "card",
) -> dict[str, object]:
    out: dict[str, object] = approvals.request_changes(
        conn, who.agent, who.role(cfg), cfg, post_id, version, hash_prefix, msg_id, words,
        approver, what=what, where=where, instruction=instruction, channel=channel,
        verified=who.verified,
    )  # fmt: skip
    return out


def reschedule(
    conn: sqlite3.Connection,
    cfg: Mapping[str, Any],
    who: Identity,
    post_id: str,
    version: int,
    hash_prefix: str,
    window: str,
    msg_id: str,
    words: str,
    approver: str | None = None,
    *,
    channel: str = "card",
) -> dict[str, object]:
    out: dict[str, object] = approvals.reschedule(
        conn, who.agent, who.role(cfg), cfg, post_id, version, hash_prefix, window, msg_id,
        words, approver, channel=channel, verified=who.verified,
    )  # fmt: skip
    return out


def cancel(
    conn: sqlite3.Connection,
    cfg: Mapping[str, Any],
    who: Identity,
    post_id: str,
    kind: str,
    reason: str,
    msg_id: str | None = None,
    words: str | None = None,
    approver: str | None = None,
    *,
    channel: str = "card",
) -> dict[str, object]:
    out: dict[str, object] = approvals.cancel(
        conn, who.agent, who.role(cfg), cfg, post_id, kind, reason, msg_id, words, approver,
        channel=channel, verified=who.verified,
    )  # fmt: skip
    return out


def edit(
    conn: sqlite3.Connection,
    cfg: Mapping[str, Any],
    who: Identity,
    post_id: str,
    assignments: list[str],
) -> dict[str, object]:
    out: dict[str, object] = posts.edit_post(
        conn, who.agent, who.role(cfg), cfg, post_id, assignments
    )
    return out


def submit(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], who: Identity, post_id: str
) -> dict[str, object]:
    out: dict[str, object] = posts.submit_post(conn, who.agent, who.role(cfg), cfg, post_id)
    return out


def note(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], who: Identity, post_id: str, text: str
) -> dict[str, object]:
    who.role(cfg)  # the agent must exist
    out: dict[str, object] = posts.add_note(conn, who.agent, cfg, post_id, text)
    return out

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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from brandcal import approvals, archive, posts, reports
from brandcal import audit as audit_mod
from brandcal.approvals import Verified
from brandcal.config import display_tz
from brandcal.errors import EXIT_CODES, BrandcalError, ErrorCode
from brandcal.timefmt import parse_time
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


def ui_schema(conn: sqlite3.Connection, cfg: Mapping[str, Any]) -> dict[str, object]:
    """The rules plus the config the web UI needs (UI_SPEC 1.4)."""
    return {
        **schema(),
        "platforms": posts.platform_limits(conn),
        "timezone": cfg.get("timezone"),
        "claim_minutes": int(cfg.get("claim_minutes", 30)),
        "campaigns": list(cfg.get("campaigns", [])),
        "pillars": list(cfg.get("pillars", [])),
    }


_BUTTONS: dict[str, tuple[str, ...]] = {
    "pending_approval": ("approve", "request-changes", "edit", "cancel"),
    "changes_requested": ("edit", "submit", "cancel"),
    "approved": ("reschedule", "edit", "cancel"),
    "missed": ("reschedule", "edit", "cancel"),
}
_LABELS = {
    "approve": "Approve",
    "request-changes": "Request changes",
    "edit": "Edit",
    "cancel": "Cancel",
    "submit": "Submit for approval",
    "reschedule": "Change time",
}


def _blocked(button: str, post: Mapping[str, Any], cfg: Mapping[str, Any]) -> BrandcalError | None:
    """The refusal this button would produce on this post (UI_SPEC 1.5), or None."""
    pid = post.get("id", "this post")
    held = post.get("hold_until")
    if button == "approve" and held and parse_time(held, display_tz(cfg)) > datetime.now(UTC):
        return BrandcalError(
            ErrorCode.ON_HOLD,
            f"On hold until {held} ({post.get('hold_reason') or 'no reason'}).",
            "Clear the hold first: brandcal edit ID hold_until=",
        )
    if button == "submit":
        asked = [a for a in post.get("approvals", []) if a.get("decision") == "request_changes"]
        if asked and asked[-1].get("content_hash") == post.get("content_hash"):
            return BrandcalError(
                ErrorCode.BAD_TRANSITION,
                "The content has not changed since changes were requested.",
                "Edit the post first, then submit again.",
            )
    queued, claimed = post.get("native_scheduled_at"), post.get("claimed_by")
    if button == "edit" and queued:
        return BrandcalError(
            ErrorCode.EDIT_WHILE_SCHEDULED,
            f"{pid} is queued on the platform.",
            "Remove it from the platform's queue, then unschedule it.",
        )
    if button == "edit" and claimed:
        return BrandcalError(
            ErrorCode.EDIT_WHILE_CLAIMED,
            f"{pid} is claimed by {claimed}.",
            "Wait for the claim to end (published, failed or expired).",
        )
    if button == "cancel" and queued:
        return BrandcalError(
            ErrorCode.NATIVELY_SCHEDULED,
            f"{pid} is queued on the platform.",
            "Remove it from the platform's queue, then unschedule it.",
        )
    if button == "cancel" and claimed:
        return BrandcalError(
            ErrorCode.CLAIMED,
            f"{pid} is claimed by {claimed}.",
            "Wait for the claim to end (published, failed or expired).",
        )
    return None


def post_actions(
    post: Mapping[str, Any], cfg: Mapping[str, Any], viewer: str | None
) -> list[dict[str, object]]:
    """Buttons for a post (UI_SPEC 1.5). ``viewer`` is "approver", "viewer" or None (unverified).

    Every button with a transition is listed; one that is not allowed is disabled and carries the
    refusal it would produce. Closed posts have no buttons.
    """
    out: list[dict[str, object]] = []
    for button in _BUTTONS.get(str(post.get("status")), ()):
        label = _LABELS[button]
        if button == "reschedule" and post.get("status") == "missed":
            label = "Approve new time"
        if viewer is None:
            why: BrandcalError | None = BrandcalError(
                ErrorCode.IDENTITY_UNVERIFIED,
                "This session has no verified identity, so it is read-only.",
                "Sign in through Cloudflare Access.",
            )
        elif viewer != "approver":
            why = BrandcalError(
                ErrorCode.ROLE_NOT_ALLOWED,
                "You have read-only access.",
                "Ask the admin to list you in serve.approvers.",
            )
        else:
            why = _blocked(button, post, cfg)
        item: dict[str, object] = {
            "id": button,
            "label": label,
            "enabled": why is None,
            "refusal": None if why is None else why.to_dict()["error"],
        }
        if button == "edit" and post.get("status") == "approved":
            item["warning"] = "Editing returns the post to approval."
        out.append(item)
    return out


def post_detail(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], post_id: str, viewer: str | None
) -> dict[str, object]:
    """``show`` plus the buttons for this viewer."""
    out = show(conn, post_id)
    out["actions"] = post_actions(out, cfg, viewer)
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
    *,
    seen_window: str | None = None,
) -> dict[str, object]:
    out: dict[str, object] = approvals.approve(
        conn, who.agent, who.role(cfg), cfg, post_id, version, hash_prefix, channel, msg_id,
        words, relayed_by, approver, verified=who.verified, seen_window=seen_window,
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
    seen_window: str | None = None,
) -> dict[str, object]:
    out: dict[str, object] = approvals.request_changes(
        conn, who.agent, who.role(cfg), cfg, post_id, version, hash_prefix, msg_id, words,
        approver, what=what, where=where, instruction=instruction, channel=channel,
        verified=who.verified, seen_window=seen_window,
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
    seen_window: str | None = None,
) -> dict[str, object]:
    out: dict[str, object] = approvals.reschedule(
        conn, who.agent, who.role(cfg), cfg, post_id, version, hash_prefix, window, msg_id,
        words, approver, channel=channel, verified=who.verified, seen_window=seen_window,
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
    seen: tuple[int, str, str] | None = None,
) -> dict[str, object]:
    out: dict[str, object] = approvals.cancel(
        conn, who.agent, who.role(cfg), cfg, post_id, kind, reason, msg_id, words, approver,
        channel=channel, verified=who.verified, seen=seen,
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

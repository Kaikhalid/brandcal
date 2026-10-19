"""Recording the approver's decisions, bound to version, hash and window (SPEC 5.4, 6.1, 7)."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from brandcal import events, validate
from brandcal.config import display_tz
from brandcal.db import transaction
from brandcal.errors import BrandcalError, ErrorCode
from brandcal.posts import (
    bad_args,
    load_post,
    now_and_month,
    platform_limits,
    post_result,
    raise_first,
)
from brandcal.timefmt import normalise_window, parse_time
from brandcal.transitions import CLOSED, check_transition

CANCEL_KINDS = ("idea", "version", "plan")
_HEX = re.compile(r"[0-9a-f]{8,64}")
# Cleared in the same UPDATE as any status change (CHECK: only approved posts carry them).
CLEAR = "native_scheduled_at = NULL, claimed_by = NULL, claim_expires = NULL"


@dataclass(frozen=True)
class Verified:
    """A human identity checked by the server (UI_SPEC 2.3): the email and where it came from."""

    identity: str
    source: str


CONSOLE_SOURCE = "access-jwt"


def _console(role: str, cfg: Mapping[str, Any], verified: Verified | None, what: str) -> str:
    """Gate a console decision (UI_SPEC 3.1); return the console recorder agent's id."""
    if verified is None or verified.source != CONSOLE_SOURCE or not verified.identity.strip():
        raise BrandcalError(
            ErrorCode.IDENTITY_UNVERIFIED,
            f"A console decision ({what}) needs a verified identity; none was given.",
            "Console decisions are made in the web UI behind Cloudflare Access (brandcal serve);"
            " from the CLI use --channel card or writer-session.",
        )
    if role != "approver":
        raise BrandcalError(
            ErrorCode.ROLE_NOT_ALLOWED,
            f"Role {role} may not decide in the console.",
            "Sign in as an approver.",
        )
    serve = cfg.get("serve")
    agent = serve.get("console_agent") if isinstance(serve, Mapping) else None
    if agent not in _agents(cfg, "system"):
        raise bad_args(
            "serve.console_agent is not a configured agent with role system.",
            "Set serve.console_agent in config.json, then run: brandcal init",
        )
    return str(agent)


def _gate(
    role: str, cfg: Mapping[str, Any], channel: str, verified: Verified | None, what: str
) -> str | None:
    """The console recorder for channel console, else None after the manager-only check."""
    if channel == "console":
        return _console(role, cfg, verified, what)
    manager_only(role, what)
    return None


def _via(verified: Verified | None) -> dict[str, object]:
    """Event detail naming the verified identity of a console decision (UI_SPEC 4.3)."""
    if verified is None:
        return {}
    return {"identity": verified.identity, "source": verified.source, "via": "console"}


def manager_only(role: str, what: str) -> None:
    if role != "manager":
        raise BrandcalError(
            ErrorCode.ROLE_NOT_ALLOWED, f"Role {role} may not {what}.", "Ask the manager."
        )


def _need(name: str, value: str | None) -> str:
    if not value or not value.strip():
        raise bad_args(f"{name} is required.", "Give the approver's message id and exact words.")
    return value


def _agents(cfg: Mapping[str, Any], role: str) -> list[str]:
    return [str(a["id"]) for a in cfg.get("agents", []) if a.get("role") == role]


def _approver(cfg: Mapping[str, Any], given: str | None) -> str:
    """The agent who decided: the one named, or the only approver in the config."""
    known = _agents(cfg, "approver")
    if given is not None:
        if given not in known:
            raise bad_args(f"{given} is not an approver.", "Check config.json agents.")
        return given
    if len(known) != 1:
        raise bad_args(
            f"{len(known)} approvers are configured; cannot tell who decided.", "Pass --approver."
        )
    return known[0]


def _expect(post: sqlite3.Row, *statuses: str) -> None:
    if post["status"] not in statuses:
        raise BrandcalError(
            ErrorCode.BAD_TRANSITION,
            f"{post['id']} is {post['status']}; this needs {' or '.join(statuses)}.",
            "see the state machine in SPEC 6",
        )


def _bind(
    post: sqlite3.Row, version: int, hash_prefix: str, seen_window: str | None = None
) -> None:
    """The decision must name the post's current version and the start of its hash.

    The console also sends the window it showed (UI_SPEC 3.3): the window is not in the hash,
    so a different one counts as stale too.
    """
    prefix = hash_prefix.lower()
    if not _HEX.fullmatch(prefix):
        raise bad_args("The hash must be 8 or more hex characters.", "Copy it from the card.")
    if version != post["content_version"] or not post["content_hash"].startswith(prefix):
        raise BrandcalError(
            ErrorCode.STALE_APPROVAL,
            f"{post['id']} is now version {post['content_version']}"
            f" ({post['content_hash'][:8]}), not version {version} ({prefix[:8]}).",
            f"Send the approver the current version: brandcal preview {post['id']}",
        )
    if seen_window is not None and seen_window != post["window"]:
        raise BrandcalError(
            ErrorCode.STALE_APPROVAL,
            f"{post['id']} now has the window {post['window']}, not {seen_window}.",
            "Read the post again before deciding.",
        )


def _record(
    conn: sqlite3.Connection,
    post: sqlite3.Row,
    at: str,
    decision: str,
    *,
    window: str,
    decided_by: str,
    channel: str,
    relayed_by: str,
    recorded_by: str,
    msg_id: str,
    words: str,
    changes: str | None = None,
    verified: Verified | None = None,
) -> int:
    who = (verified.identity, verified.source) if verified else (None, None)
    cur = conn.execute(
        'INSERT INTO approvals (post_id, decision, content_version, content_hash, "window",'
        " decided_by, channel, relayed_by, recorded_by, source_message_id, approver_words,"
        " changes_requested, decided_at, verified_identity, identity_source)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (post["id"], decision, post["content_version"], post["content_hash"], window)
        + (decided_by, channel, relayed_by, recorded_by, msg_id, words, changes, at)
        + who,
    )
    return int(cur.lastrowid or 0)


def log_event(
    conn: sqlite3.Connection,
    actor_id: str,
    action: str,
    post: sqlite3.Row,
    at: str,
    month: str,
    detail: dict[str, object],
    reason: str | None = None,
) -> None:
    status = conn.execute("SELECT status FROM posts WHERE id = ?", (post["id"],)).fetchone()[0]
    events.append_event(
        conn,
        at=at,
        actor=actor_id,
        action=action,
        chain=events.chain_for(post["id"], month),
        post_id=post["id"],
        from_status=post["status"],
        to_status=status,
        detail=detail,
        reason=reason,
    )


# --- decisions ---------------------------------------------------------------------------


def approve(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    post_id: str,
    version: int,
    hash_prefix: str,
    channel: str,
    msg_id: str,
    words: str,
    relayed_by: str | None = None,
    approver: str | None = None,
    *,
    verified: Verified | None = None,
    seen_window: str | None = None,
) -> Any:
    console = _gate(role, cfg, channel, verified, "record an approval")
    if console is not None:
        if relayed_by is not None:
            raise bad_args("A console approval has no --relayed-by.", "Drop --relayed-by.")
        relay = console
    elif channel == "card":
        if relayed_by not in (None, actor_id):
            raise bad_args("A card approval is relayed by the manager.", "Drop --relayed-by.")
        relay = actor_id
    elif channel == "writer-session":
        if relayed_by is None or relayed_by not in _agents(cfg, "writer"):
            raise bad_args("A writer-session approval needs --relayed-by with a writer.")
        relay = relayed_by
    else:
        raise bad_args(f"Unknown channel {channel!r}.", "Use card or writer-session.")
    _need("msg", msg_id)
    _need("words", words)
    decided_by = actor_id if console is not None else _approver(cfg, approver)
    with transaction(conn):
        post = load_post(conn, post_id)
        _expect(post, "pending_approval")
        _bind(post, version, hash_prefix, seen_window)
        errors, warnings = validate.validate(conn, post_id, platform_limits(conn), cfg, "check")
        raise_first(errors)
        at, month = now_and_month(cfg)
        approval = _record(
            conn,
            post,
            at,
            "approve",
            window=post["window"],
            decided_by=decided_by,
            channel=channel,
            relayed_by=relay,
            recorded_by=console or actor_id,
            msg_id=msg_id,
            words=words,
            verified=verified if console else None,
        )
        conn.execute(
            f"UPDATE posts SET status = 'approved', {CLEAR}, updated_at = ? WHERE id = ?",
            (at, post_id),
        )
        detail: dict[str, object] = {"approval": approval, "channel": channel, "msg": msg_id}
        detail.update(_via(verified if console else None))
        log_event(conn, actor_id, "approve", post, at, month, detail)
        next_step = (
            "send the approver a receipt: exact text, window, fingerprint, 'reply stop to pull it'"
            if channel == "writer-session"
            else f"publish inside the window: brandcal begin {post_id}"
        )
        return post_result(conn, post_id, next_step, warnings)


def request_changes(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
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
    verified: Verified | None = None,
    seen_window: str | None = None,
) -> Any:
    console = _gate(role, cfg, channel, verified, "record a request for changes")
    if channel not in ("card", "console"):
        raise bad_args(f"Unknown channel {channel!r}.", "Use card or console.")
    _need("msg", msg_id)
    _need("words", words)
    changes = _reason(channel, words, what, where, instruction)
    decided_by = actor_id if console is not None else _approver(cfg, approver)
    with transaction(conn):
        post = load_post(conn, post_id)
        _expect(post, "pending_approval")
        _bind(post, version, hash_prefix, seen_window)
        at, month = now_and_month(cfg)
        approval = _record(
            conn,
            post,
            at,
            "request_changes",
            window=post["window"],
            decided_by=decided_by,
            channel=channel,
            relayed_by=console or actor_id,
            recorded_by=console or actor_id,
            msg_id=msg_id,
            words=words,
            changes=changes,
            verified=verified if console else None,
        )
        conn.execute(
            f"UPDATE posts SET status = 'changes_requested', {CLEAR}, updated_at = ? WHERE id = ?",
            (at, post_id),
        )
        detail: dict[str, object] = {"approval": approval, **_via(verified if console else None)}
        log_event(conn, actor_id, "request-changes", post, at, month, detail)
        return post_result(conn, post_id, "writer: edit the post, then brandcal submit", [])


def reschedule(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    post_id: str,
    version: int,
    hash_prefix: str,
    new_window: str,
    msg_id: str,
    words: str,
    approver: str | None = None,
    *,
    channel: str = "card",
    verified: Verified | None = None,
    seen_window: str | None = None,
) -> Any:
    """Time-only decision: the new window becomes the approved one; a missed post is approved."""
    console = _gate(role, cfg, channel, verified, "record a time change")
    _need("msg", msg_id)
    _need("words", words)
    window = normalise_window(new_window, display_tz(cfg))
    decided_by = actor_id if console is not None else _approver(cfg, approver)
    with transaction(conn):
        post = load_post(conn, post_id)
        _expect(post, "approved", "missed")
        _bind(post, version, hash_prefix, seen_window)
        at, month = now_and_month(cfg)
        approval = _record(
            conn,
            post,
            at,
            "reschedule",
            window=window,
            decided_by=decided_by,
            channel=channel,
            relayed_by=console or actor_id,
            recorded_by=console or actor_id,
            msg_id=msg_id,
            words=words,
            verified=verified if console else None,
        )
        # An approved post keeps its status (and any claim or queue entry); a missed one is
        # approved again, which clears them.
        change = f"status = 'approved', {CLEAR}," if post["status"] == "missed" else ""
        conn.execute(
            f'UPDATE posts SET "window" = ?, {change} updated_at = ? WHERE id = ?',
            (window, at, post_id),
        )
        detail: dict[str, object] = {"approval": approval, "window": window}
        detail.update(_via(verified if console else None))
        log_event(conn, actor_id, "reschedule", post, at, month, detail)
        return post_result(
            conn, post_id, f"publish inside the new window: brandcal begin {post_id}", []
        )


def cancel(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    post_id: str,
    kind: str,
    reason: str,
    msg_id: str | None = None,
    words: str | None = None,
    approver: str | None = None,
    *,
    channel: str = "card",
    verified: Verified | None = None,
    seen: tuple[int, str, str] | None = None,
) -> Any:
    """``seen`` is the (version, hash, window) the console showed; it is checked as for approve."""
    if kind not in CANCEL_KINDS:
        raise bad_args(f"Unknown cancel kind {kind!r}.", f"Use one of: {' '.join(CANCEL_KINDS)}")
    _need("reason", reason)
    console = _console(role, cfg, verified, "cancel") if channel == "console" else None
    if console is None and role not in ("manager", "writer"):
        raise BrandcalError(ErrorCode.ROLE_NOT_ALLOWED, f"Role {role} may not cancel posts.")
    decided_by = None
    if msg_id or words or console:
        if console is None:
            manager_only(role, "record the approver's cancel decision")
        _need("msg", msg_id)
        _need("words", words)
        decided_by = actor_id if console else _approver(cfg, approver)
    with transaction(conn):
        post = load_post(conn, post_id)
        if post["status"] in CLOSED:
            raise BrandcalError(
                ErrorCode.POST_CLOSED, f"{post_id} is {post['status']} and cannot be changed."
            )
        if seen is not None:
            _bind(post, seen[0], seen[1], seen[2])
        # Transition roles name who records a decision; a console decision is the approver's
        # own, recorded for them, so it is checked as the manager's (UI_SPEC 3.5).
        check_transition(post["status"], "cancelled", "manager" if console else role)
        if role == "writer" and post["owner"] != actor_id:
            raise BrandcalError(
                ErrorCode.ROLE_NOT_ALLOWED,
                f"{post_id} belongs to {post['owner']}; a writer cancels only own posts.",
                "Ask the manager.",
            )
        if post["native_scheduled_at"]:
            raise BrandcalError(
                ErrorCode.NATIVELY_SCHEDULED,
                f"{post_id} is queued on the platform.",
                f"Remove it from the platform's queue, then: brandcal unschedule {post_id}",
            )
        if post["claimed_by"]:
            raise BrandcalError(
                ErrorCode.CLAIMED,
                f"{post_id} is claimed by {post['claimed_by']}.",
                "Wait for the claim to end (published, failed or expired).",
            )
        at, month = now_and_month(cfg)
        detail: dict[str, object] = {"kind": kind, **_via(verified if console else None)}
        if decided_by is not None:
            detail["approval"] = _record(
                conn,
                post,
                at,
                "cancel",
                window=post["window"],
                decided_by=decided_by,
                channel=channel,
                relayed_by=console or actor_id,
                recorded_by=console or actor_id,
                msg_id=str(msg_id),
                words=str(words),
                verified=verified if console else None,
            )
        conn.execute(
            f"UPDATE posts SET status = 'cancelled', cancel_kind = ?, closed_at = ?, {CLEAR},"
            " updated_at = ? WHERE id = ?",
            (kind, at, at, post_id),
        )
        log_event(conn, actor_id, "cancel", post, at, month, detail, reason)
        return post_result(conn, post_id, "", [])


def _reason(
    channel: str, words: str, what: str | None, where: str | None, instruction: str | None
) -> str:
    """The text stored in changes_requested: JSON what/where/instruction (UI_SPEC 4.2) or words."""
    given = {"what": what, "where": where, "instruction": instruction}
    if channel != "console" and not any(given.values()):
        return words
    if not all(v and v.strip() for v in given.values()):
        raise BrandcalError(
            ErrorCode.REASON_REQUIRED,
            "Request changes needs what, where and instruction, all non-empty.",
            "Give --what (what is wrong), --where (where it is) and --instruction (what to do).",
        )
    return json.dumps({k: str(v).strip() for k, v in given.items()}, sort_keys=True)


def console_unverified(conn: sqlite3.Connection, post_id: str) -> bool:
    """True if the approval the post stands on is a console one without a verified identity."""
    row = conn.execute(
        "SELECT a.channel, a.verified_identity, a.identity_source FROM approvals a"
        " JOIN posts p ON p.id = a.post_id WHERE a.post_id = ?"
        " AND a.decision IN ('approve', 'reschedule') AND a.content_version = p.content_version"
        " AND a.content_hash = p.content_hash ORDER BY a.id DESC LIMIT 1",
        (post_id,),
    ).fetchone()
    return bool(
        row
        and row["channel"] == "console"
        and (not row["verified_identity"] or row["identity_source"] != CONSOLE_SOURCE)
    )


# --- window binding ----------------------------------------------------------------------


def approved_window(conn: sqlite3.Connection, post_id: str) -> str | None:
    """Window of the latest approve or reschedule decision for the current version and hash."""
    row = conn.execute(
        'SELECT a."window" FROM approvals a JOIN posts p ON p.id = a.post_id'
        " WHERE a.post_id = ? AND a.decision IN ('approve', 'reschedule')"
        " AND a.content_version = p.content_version AND a.content_hash = p.content_hash"
        " ORDER BY a.id DESC LIMIT 1",
        (post_id,),
    ).fetchone()
    return None if row is None else str(row[0])


def _span(window: str) -> tuple[datetime, datetime]:
    parts = window.split("/")
    if len(parts) != 2:
        raise BrandcalError(ErrorCode.BAD_WINDOW, f"Window must be START/END: {window!r}.")
    return parse_time(parts[0], UTC), parse_time(parts[1], UTC)


def window_within(inner: str, outer: str) -> bool:
    """True if the inner window starts no earlier and ends no later than the outer (as instants)."""
    (i_start, i_end), (o_start, o_end) = _span(inner), _span(outer)
    return o_start <= i_start and i_end <= o_end


# --- preview -----------------------------------------------------------------------------


def preview(conn: sqlite3.Connection, cfg: Mapping[str, Any], post_id: str) -> dict[str, Any]:
    """Card data for the approver. Read-only."""
    post = load_post(conn, post_id)
    parts = [
        {
            "pos": p["pos"],
            "text": p["text"],
            "media": [
                m[0]
                for m in conn.execute(
                    "SELECT alt_text FROM media WHERE part_id = ? ORDER BY pos", (p["id"],)
                )
            ],
        }
        for p in conn.execute(
            "SELECT id, pos, text FROM parts WHERE post_id = ? ORDER BY pos", (post_id,)
        ).fetchall()
    ]
    added = conn.execute(
        "SELECT detail FROM events WHERE post_id = ? AND action = 'add' ORDER BY id DESC LIMIT 1",
        (post_id,),
    ).fetchone()
    confirmed = bool(added and added[0] and json.loads(added[0]).get("approver_confirmed"))
    h8 = post["content_hash"][:8]
    return {
        "ok": True,
        "id": post_id,
        "kind": "receipt" if confirmed else "card",
        "platform": post["platform"],
        "post_type": post["post_type"],
        "window": post["window"],
        "title": post["title"],
        "parts": parts,
        "first_comment": post["first_comment"],
        "version": post["content_version"],
        "hash": h8,
        "buttons": [
            {"label": label, "post": post_id, "version": post["content_version"], "hash": h8}
            for label in ("Approve", "Request changes", "Cancel")
        ],
    }

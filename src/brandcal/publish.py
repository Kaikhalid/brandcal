"""Publishing: schedule, unschedule, begin, published and failed (SPEC 6, 7.3, 8.3)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from brandcal import approvals, content, media, validate
from brandcal.approvals import CLEAR, log_event, manager_only
from brandcal.config import display_tz
from brandcal.db import transaction
from brandcal.errors import BrandcalError, ErrorCode
from brandcal.posts import bad_args, load_post, platform_limits, raise_first
from brandcal.timefmt import format_time, month_key, normalise_time, parse_time, to_utc_text


def stamp(cfg: Mapping[str, Any], now: datetime | None) -> tuple[datetime, str, str]:
    """The moment to act at (default: now), its text and its month key, in the display zone."""
    tz = display_tz(cfg)
    moment = now.astimezone(tz) if now else datetime.now(tz)
    return moment, format_time(moment), month_key(moment, tz)


def _need_approved(post: sqlite3.Row) -> None:
    if post["status"] != "approved":
        raise BrandcalError(
            ErrorCode.BAD_TRANSITION,
            f"{post['id']} is {post['status']}; this needs approved.",
            "see the state machine in SPEC 6",
        )


def _recheck(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], home: Path, post: sqlite3.Row
) -> None:
    """Approved, window inside the approved one, content and files unchanged, still valid."""
    pid = post["id"]
    _need_approved(post)
    approved = approvals.approved_window(conn, pid)
    if approved is None or not approvals.window_within(post["window"], approved):
        raise BrandcalError(
            ErrorCode.WINDOW_NOT_APPROVED,
            f"The window of {pid} is not inside the window the approver agreed to"
            f" ({approved or 'none recorded'}).",
            f"Ask the approver for a new time: brandcal reschedule {pid}",
        )
    if content.content_hash(conn, pid) != post["content_hash"] or media.verify_media(
        conn, home, pid
    ):
        raise BrandcalError(
            ErrorCode.HASH_MISMATCH,
            f"The text or media of {pid} no longer match the approved fingerprint.",
            "Do not publish; tell the approver and send a fresh card.",
        )
    errors, _ = validate.validate(conn, pid, platform_limits(conn), cfg, "check")
    raise_first(errors)


def _in_window(post: sqlite3.Row, moment: datetime) -> bool:
    """True from the window's start up to, not including, its end."""
    return bool(post["window_start_utc"] <= to_utc_text(moment) < post["window_end_utc"])


def _content(conn: sqlite3.Connection, home: Path, post: sqlite3.Row) -> dict[str, Any]:
    parts = [
        {
            "pos": p["pos"],
            "text": p["text"],
            "media": [
                {
                    "path": str((home / m["path"]).absolute()),
                    "alt_text": m["alt_text"],
                    "kind": m["kind"],
                }
                for m in conn.execute(
                    "SELECT path, alt_text, kind FROM media WHERE part_id = ? ORDER BY pos",
                    (p["id"],),
                )
            ],
        }
        for p in conn.execute(
            "SELECT id, pos, text FROM parts WHERE post_id = ? ORDER BY pos", (post["id"],)
        ).fetchall()
    ]
    return {
        "ok": True,
        "id": post["id"],
        "version": post["content_version"],
        "hash": post["content_hash"],
        "claim_expires": post["claim_expires"],
        "parts": parts,
        "first_comment": post["first_comment"],
        "platform": post["platform"],
    }


# --- native schedule ---------------------------------------------------------------------


def schedule(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    home: Path,
    post_id: str,
    at: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    manager_only(role, "schedule posts")
    when = parse_time(at, display_tz(cfg))
    when_text = normalise_time(at, display_tz(cfg))
    _, stamp_at, month = stamp(cfg, now)
    with transaction(conn):
        post = load_post(conn, post_id)
        if post["claimed_by"]:
            raise BrandcalError(
                ErrorCode.CLAIMED,
                f"{post_id} is claimed by {post['claimed_by']}.",
                "Wait for the claim to end (published, failed or expired).",
            )
        _recheck(conn, cfg, home, post)
        if not _in_window(post, when):
            raise BrandcalError(
                ErrorCode.WINDOW_NOT_APPROVED,
                f"{when_text} is outside the window {post['window']}.",
                "Pick a time inside the approved window.",
            )
        out: dict[str, Any] = {"ok": True, "id": post_id, "native_scheduled_at": when_text}
        if post["native_scheduled_at"] == when_text:
            return out | {"note": "already scheduled"}
        conn.execute(
            "UPDATE posts SET native_scheduled_at = ?, updated_at = ? WHERE id = ?",
            (when_text, stamp_at, post_id),
        )
        log_event(conn, actor_id, "schedule", post, stamp_at, month, {"at": when_text})
        return out | {"next": "queue it on the platform, then record: brandcal published"}


def unschedule(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    post_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    manager_only(role, "unschedule posts")
    _, stamp_at, month = stamp(cfg, now)
    with transaction(conn):
        post = load_post(conn, post_id)
        out: dict[str, Any] = {"ok": True, "id": post_id}
        if post["native_scheduled_at"] is None:
            return out | {"note": "not scheduled"}
        conn.execute(
            "UPDATE posts SET native_scheduled_at = NULL, updated_at = ? WHERE id = ?",
            (stamp_at, post_id),
        )
        log_event(
            conn,
            actor_id,
            "unschedule",
            post,
            stamp_at,
            month,
            {"was": post["native_scheduled_at"]},
        )
        return out


# --- claim -------------------------------------------------------------------------------


def begin(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    home: Path,
    post_id: str,
    not_live: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    manager_only(role, "begin publishing")
    moment, stamp_at, month = stamp(cfg, now)
    with transaction(conn):
        post = load_post(conn, post_id)
        _need_approved(post)
        if post["native_scheduled_at"]:
            raise BrandcalError(
                ErrorCode.NATIVELY_SCHEDULED,
                f"{post_id} is queued on the platform.",
                f"Remove it from the platform's queue, then: brandcal unschedule {post_id}",
            )
        held = post["claimed_by"] is not None
        if held and parse_time(post["claim_expires"], display_tz(cfg)) > moment:
            if post["claimed_by"] != actor_id:
                raise BrandcalError(
                    ErrorCode.CLAIMED,
                    f"{post_id} is claimed by {post['claimed_by']} until {post['claim_expires']}.",
                    "Wait for the claim to end (published, failed or expired).",
                )
            _recheck(conn, cfg, home, post)  # the same claim again: files may have changed
            return _content(conn, home, post)
        last = conn.execute(
            "SELECT action FROM events WHERE post_id = ?"
            " AND action IN ('begin', 'claim_expired', 'publish_failed') ORDER BY id DESC LIMIT 1",
            (post_id,),
        ).fetchone()
        # A claim that ran out (released by sweep, or still in place) may have gone live.
        if (held or (last and last[0] == "claim_expired")) and not not_live:
            raise BrandcalError(
                ErrorCode.CHECK_LIVE_FIRST,
                f"The last claim on {post_id} ran out; it may already be live.",
                f"Check the platform. If it is not live: brandcal begin {post_id} --not-live",
            )
        _recheck(conn, cfg, home, post)
        if not _in_window(post, moment):
            raise BrandcalError(
                ErrorCode.WINDOW_NOT_APPROVED,
                f"It is outside the window {post['window']}.",
                "Wait for the window, or ask the approver for a new time.",
            )
        expires = format_time(moment + timedelta(minutes=int(cfg.get("claim_minutes", 30))))
        conn.execute(
            "UPDATE posts SET claimed_by = ?, claim_expires = ?, updated_at = ? WHERE id = ?",
            (actor_id, expires, stamp_at, post_id),
        )
        detail = {"claim_expires": expires, "not_live": not_live}
        log_event(conn, actor_id, "begin", post, stamp_at, month, detail)
        return _content(conn, home, load_post(conn, post_id))


# --- outcome -----------------------------------------------------------------------------


def _http_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise bad_args(f"Not an http(s) URL: {url!r}.", "Give the link to the live post.")
    return url.strip()


def _expired_claim_of(conn: sqlite3.Connection, post_id: str, actor_id: str) -> bool:
    """True if the post's last claim event is this manager's claim released by sweep.

    SPEC 6: ``published`` is still accepted after a claim expires, even once sweep has
    released it, because the post may have gone out just after the claim ran out.
    """
    row = conn.execute(
        "SELECT action, detail FROM events WHERE post_id = ?"
        " AND action IN ('begin', 'claim_expired', 'publish_failed') ORDER BY id DESC LIMIT 1",
        (post_id,),
    ).fetchone()
    if row is None or row["action"] != "claim_expired" or not row["detail"]:
        return False
    return bool(json.loads(row["detail"]).get("claimed_by") == actor_id)


def published(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    post_id: str,
    url: str,
    part_urls: dict[int, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    manager_only(role, "record a publication")
    url = _http_url(url)
    part_urls = {pos: _http_url(u) for pos, u in (part_urls or {}).items()}
    _, stamp_at, month = stamp(cfg, now)
    with transaction(conn):
        post = load_post(conn, post_id)
        if post["status"] == "published":
            if post["platform_url"] != url:
                raise BrandcalError(
                    ErrorCode.URL_CONFLICT,
                    f"{post_id} is already published at {post['platform_url']}.",
                    "Check which link is right; a published post is never changed.",
                )
            return {"ok": True, "id": post_id, "status": "published", "note": "already published"}
        _need_approved(post)
        if (
            not post["native_scheduled_at"]
            and post["claimed_by"] != actor_id
            and not _expired_claim_of(conn, post_id, actor_id)
        ):
            raise BrandcalError(
                ErrorCode.BAD_TRANSITION,
                f"{post_id} is neither claimed by {actor_id} nor queued on the platform.",
                f"Run: brandcal begin {post_id} (or schedule it) before recording it",
            )
        for pos, part_url in part_urls.items():
            done = conn.execute(
                "UPDATE parts SET platform_url = ? WHERE post_id = ? AND pos = ?",
                (part_url, post_id, pos),
            )
            if done.rowcount != 1:
                raise bad_args(f"{post_id} has no part {pos}.")
        conn.execute(
            "UPDATE posts SET status = 'published', platform_url = ?, published_at = ?,"
            f" closed_at = ?, {CLEAR}, updated_at = ? WHERE id = ?",
            (url, stamp_at, stamp_at, stamp_at, post_id),
        )
        detail: dict[str, object] = {"url": url, "parts": len(part_urls)}
        log_event(conn, actor_id, "published", post, stamp_at, month, detail)
        return {"ok": True, "id": post_id, "status": "published", "url": url}


def failed(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    post_id: str,
    reason: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    manager_only(role, "record a failed attempt")
    if not reason.strip():
        raise bad_args("A reason is required.", "Say what went wrong: --reason TEXT")
    _, stamp_at, month = stamp(cfg, now)
    with transaction(conn):
        post = load_post(conn, post_id)
        if post["claimed_by"] is None:
            raise BrandcalError(
                ErrorCode.BAD_TRANSITION,
                f"{post_id} has no claim to release.",
                f"Run: brandcal begin {post_id}",
            )
        conn.execute(
            "UPDATE posts SET claimed_by = NULL, claim_expires = NULL, updated_at = ? WHERE id = ?",
            (stamp_at, post_id),
        )
        detail: dict[str, object] = {"claimed_by": post["claimed_by"]}
        log_event(conn, actor_id, "publish_failed", post, stamp_at, month, detail, reason)
        next_step = f"retry: brandcal begin {post_id}"
        return {"ok": True, "id": post_id, "status": "approved", "next": next_step}

"""Command logic for adding, editing and submitting posts (SPEC 6.1, 8.1, 8.4)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from brandcal import content, events, media, validate
from brandcal.config import display_tz
from brandcal.db import transaction
from brandcal.errors import BrandcalError, ErrorCode
from brandcal.timefmt import format_time, month_key, normalise_time, normalise_window
from brandcal.transitions import CLOSED, check_transition

WRITE_ROLES = ("writer", "manager")
EDITABLE = [
    "title",
    "slug",
    "window",
    "first_comment",
    "target_url",
    "post_type",
    "campaign",
    "pillar",
    "series_id",
    "series_pos",
    "source_doc",
    "hold_until",
    "hold_reason",
]
_ADD_KEYS = [
    "slug",
    "title",
    "platform",
    "post_type",
    "window",
    "parts",
    "first_comment",
    "target_url",
    "campaign",
    "pillar",
    "keywords",
    "series_id",
    "series_pos",
    "source_doc",
    "hold_until",
    "hold_reason",
    "notes",
    "delegation_msg_id",
    "delegation_words",
]
_TMP = 1000  # parts are renumbered through pos + _TMP so UNIQUE (post_id, pos) never clashes


def bad_args(message: str, next_step: str = "") -> BrandcalError:
    return BrandcalError(ErrorCode.BAD_ARGS, message, next_step)


def _require_role(role: str) -> None:
    if role not in WRITE_ROLES:
        raise BrandcalError(
            ErrorCode.ROLE_NOT_ALLOWED,
            f"Role {role} may not change posts.",
            "Ask a writer or manager.",
        )


def now_and_month(cfg: Mapping[str, Any]) -> tuple[str, str]:
    """Current local time text and its month key."""
    tz = display_tz(cfg)
    now = datetime.now(tz)
    return format_time(now), month_key(now, tz)


def archived_posts(conn: sqlite3.Connection) -> dict[str, str]:
    """Post id -> month for every post named in an archive_written manifest (SPEC 10.5)."""
    rows = conn.execute(
        "SELECT json_extract(m.value, '$.post_id'), json_extract(e.detail, '$.month')"
        " FROM events e, json_each(e.detail, '$.manifest') m WHERE e.action = 'archive_written'"
        " ORDER BY e.id"
    )
    return {str(r[0]): str(r[1]) for r in rows if r[0] is not None}


def load_post(conn: sqlite3.Connection, post_id: str) -> sqlite3.Row:
    post: sqlite3.Row | None = conn.execute(
        "SELECT * FROM posts WHERE id = ?", (post_id,)
    ).fetchone()
    if post is None:
        month = archived_posts(conn).get(post_id)
        if month is not None:
            raise BrandcalError(
                ErrorCode.ARCHIVED,
                f"{post_id} was archived in {month}.",
                f"brandcal archive show {post_id} --month {month}",
            )
        raise BrandcalError(ErrorCode.NOT_FOUND, f"No such post: {post_id}.", "Run: brandcal list")
    return post


def _load_open(conn: sqlite3.Connection, post_id: str) -> sqlite3.Row:
    post = load_post(conn, post_id)
    if post["status"] in CLOSED:
        raise BrandcalError(
            ErrorCode.POST_CLOSED, f"{post_id} is {post['status']} and cannot be changed."
        )
    return post


def platform_limits(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute("SELECT id, limits FROM platforms").fetchall()
    return {r["id"]: json.loads(r["limits"]) for r in rows}


def raise_first(errors: list[BrandcalError]) -> None:
    if errors:
        first = errors[0]
        if len(errors) > 1:
            message = " ".join(e.message for e in errors)
            raise BrandcalError(first.code, message, first.next_step)
        raise first


def post_result(conn: sqlite3.Connection, post_id: str, next_step: str, warnings: list[str]) -> Any:
    p = load_post(conn, post_id)
    return {
        "ok": True,
        "id": post_id,
        "status": p["status"],
        "version": p["content_version"],
        "hash": p["content_hash"][:8],
        "window": p["window"],
        "next": next_step,
        "warnings": warnings,
    }


def _event(
    conn: sqlite3.Connection,
    cfg: Mapping[str, Any],
    actor_id: str,
    action: str,
    post_id: str,
    from_status: str | None,
    detail: dict[str, object] | None = None,
) -> None:
    at, month = now_and_month(cfg)
    to_status = load_post(conn, post_id)["status"]
    events.append_event(
        conn,
        at=at,
        actor=actor_id,
        action=action,
        chain=events.chain_for(post_id, month),
        post_id=post_id,
        from_status=from_status,
        to_status=to_status,
        detail=detail,
    )


def _touch(conn: sqlite3.Connection, cfg: Mapping[str, Any], post_id: str) -> None:
    conn.execute("UPDATE posts SET updated_at = ? WHERE id = ?", (now_and_month(cfg)[0], post_id))


# --- add ---------------------------------------------------------------------------------


def next_post_id(conn: sqlite3.Connection) -> str:
    """The next free post id (SPEC 5.5): one more than the live posts and every archive manifest."""
    n = conn.execute(
        "SELECT COALESCE(MAX(CAST(substr(id, 2) AS INTEGER)), 0) FROM posts WHERE id GLOB 'p[0-9]*'"
    ).fetchone()[0]
    for post_id in archived_posts(conn):
        if post_id[1:].isdigit():
            n = max(n, int(post_id[1:]))
    return f"p{n + 1:04d}"


def add_post(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    data: Mapping[str, Any],
    approver_confirmed: str | None = None,
    words: str | None = None,
) -> Any:
    _require_role(role)
    unknown = sorted(set(data) - set(_ADD_KEYS))
    if unknown:
        raise bad_args(
            f"Unknown field(s): {', '.join(unknown)}.", f"Allowed: {' '.join(_ADD_KEYS)}"
        )
    for key in ("slug", "title", "platform", "post_type", "window", "parts"):
        if not data.get(key):
            raise bad_args(f"Missing field: {key}.")
    parts = data["parts"]
    if not isinstance(parts, list) or not all(
        isinstance(p, dict) and isinstance(p.get("text"), str) and p["text"] for p in parts
    ):
        raise bad_args('parts must be a list of {"text": "..."} objects.')
    ptype = data["post_type"]
    if ptype == "comment":
        if role != "manager":
            raise BrandcalError(ErrorCode.ROLE_NOT_ALLOWED, "Only the manager adds comments.")
        if not data.get("delegation_msg_id") or not data.get("delegation_words"):
            raise BrandcalError(
                ErrorCode.COMMENT_NOT_DELEGATED,
                "A comment needs a recorded delegation.",
                "Give delegation_msg_id and delegation_words.",
            )
    if ptype in ("comment", "reshare") and not data.get("target_url"):
        raise bad_args(f"A {ptype} needs a target_url.")
    tz = display_tz(cfg)
    window = normalise_window(str(data["window"]), tz)
    hold_until = normalise_time(str(data["hold_until"]), tz) if data.get("hold_until") else None
    keywords = data.get("keywords") or []
    if not isinstance(keywords, list):
        raise bad_args("keywords must be a list.")
    now = now_and_month(cfg)[0]
    with transaction(conn):
        post_id = next_post_id(conn)
        conn.execute(
            'INSERT INTO posts (id, slug, title, platform, post_type, owner, "window", series_id,'
            " series_pos, campaign, pillar, keywords, first_comment, target_url,"
            " delegation_msg_id, delegation_words, hold_until, hold_reason, source_doc, notes,"
            " content_hash, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (post_id, data["slug"], data["title"], data["platform"], ptype, actor_id, window)
            + (data.get("series_id"), data.get("series_pos"), data.get("campaign"))
            + (data.get("pillar"), json.dumps(keywords), data.get("first_comment"))
            + (data.get("target_url"), data.get("delegation_msg_id"))
            + (data.get("delegation_words"), hold_until, data.get("hold_reason"))
            + (data.get("source_doc"), data.get("notes"), "0" * 64, now, now),
        )
        conn.executemany(
            "INSERT INTO parts (post_id, pos, text) VALUES (?, ?, ?)",
            [(post_id, i, p["text"]) for i, p in enumerate(parts, 1)],
        )
        conn.execute("UPDATE posts SET content_version = 1 WHERE id = ?", (post_id,))
        content.refresh_hash(conn, post_id)
        errors, warnings = validate.validate(conn, post_id, platform_limits(conn), cfg, "add")
        raise_first(errors)
        detail: dict[str, object] = {}
        if approver_confirmed:
            detail = {"approver_confirmed": approver_confirmed, "words": words}
        _event(conn, cfg, actor_id, "add", post_id, None, detail or None)
        result = post_result(
            conn, post_id, f"manager: send a card (brandcal preview {post_id})", []
        )
    if approver_confirmed:
        result["next"] = (
            f"manager: approver confirmed in {approver_confirmed}; record it with"
            f" brandcal approve {post_id}"
        )
    result["warnings"] = warnings
    return result


# --- edit and parts ----------------------------------------------------------------------


def _mutate(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    post_id: str,
    action: str,
    detail: dict[str, object],
    change: Callable[[], None],
) -> Any:
    """Run a content change in one transaction: change, rehash, event."""
    _require_role(role)
    with transaction(conn):
        before = _load_open(conn, post_id)["status"]
        change()
        _touch(conn, cfg, post_id)
        content.refresh_hash(conn, post_id)
        _event(conn, cfg, actor_id, action, post_id, before, detail)
        return post_result(
            conn, post_id, "manager: send a card (brandcal preview " + post_id + ")", []
        )


def edit_post(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    post_id: str,
    assignments: Sequence[str],
) -> Any:
    _require_role(role)
    values: dict[str, object] = {}
    tz = display_tz(cfg)
    for item in assignments:
        field, sep, raw = item.partition("=")
        if not sep or field not in EDITABLE:
            raise bad_args(f"Cannot edit {item!r}.", f"Use field=value with: {' '.join(EDITABLE)}")
        value: object = raw or None
        if value is not None:
            if field == "window":
                value = normalise_window(raw, tz)
            elif field == "hold_until":
                value = normalise_time(raw, tz)
            elif field == "series_pos":
                if not raw.isdigit():
                    raise bad_args("series_pos must be a whole number.")
                value = int(raw)
        values[field] = value

    def change() -> None:
        for field, value in values.items():
            conn.execute(f'UPDATE posts SET "{field}" = ? WHERE id = ?', (value, post_id))

    return _mutate(conn, actor_id, role, cfg, post_id, "edit", {"fields": sorted(values)}, change)


def _part_ids(conn: sqlite3.Connection, post_id: str) -> list[int]:
    rows = conn.execute("SELECT id FROM parts WHERE post_id = ? ORDER BY pos", (post_id,))
    return [int(r[0]) for r in rows]


def _renumber(conn: sqlite3.Connection, post_id: str, ids: list[int]) -> None:
    """Give the parts positions 1..n in the order of ids (media follow their part's id)."""
    conn.execute("UPDATE parts SET pos = pos + ? WHERE post_id = ?", (_TMP, post_id))
    for pos, part_id in enumerate(ids, 1):
        conn.execute("UPDATE parts SET pos = ? WHERE id = ?", (pos, part_id))


def _check_pos(ids: list[int], pos: int, *, extra: int = 0) -> None:
    if not 1 <= pos <= len(ids) + extra:
        raise bad_args(f"Position {pos} is out of range 1..{len(ids) + extra}.")


def part_add(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    post_id: str,
    text: str,
    pos: int | None = None,
) -> Any:
    def change() -> None:
        ids = _part_ids(conn, post_id)
        at = len(ids) + 1 if pos is None else pos
        _check_pos(ids, at, extra=1)
        conn.execute("UPDATE parts SET pos = pos + ? WHERE post_id = ?", (_TMP, post_id))
        new = conn.execute(
            "INSERT INTO parts (post_id, pos, text) VALUES (?, ?, ?)", (post_id, _TMP * 10, text)
        ).lastrowid
        ids.insert(at - 1, int(new or 0))
        _renumber(conn, post_id, ids)

    return _mutate(conn, actor_id, role, cfg, post_id, "part_add", {"pos": pos}, change)


def part_edit(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    post_id: str,
    pos: int,
    text: str,
) -> Any:
    def change() -> None:
        _check_pos(_part_ids(conn, post_id), pos)
        conn.execute(
            "UPDATE parts SET text = ? WHERE post_id = ? AND pos = ?", (text, post_id, pos)
        )

    return _mutate(conn, actor_id, role, cfg, post_id, "part_edit", {"pos": pos}, change)


def part_move(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    post_id: str,
    src: int,
    dst: int,
) -> Any:
    def change() -> None:
        ids = _part_ids(conn, post_id)
        _check_pos(ids, src)
        _check_pos(ids, dst)
        ids.insert(dst - 1, ids.pop(src - 1))
        _renumber(conn, post_id, ids)

    return _mutate(
        conn, actor_id, role, cfg, post_id, "part_move", {"from": src, "to": dst}, change
    )


def part_rm(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    post_id: str,
    pos: int,
) -> Any:
    def change() -> None:
        ids = _part_ids(conn, post_id)
        _check_pos(ids, pos)
        if len(ids) == 1:
            raise bad_args("A post needs at least one part.")
        gone = ids.pop(pos - 1)
        if conn.execute("SELECT 1 FROM media WHERE part_id = ?", (gone,)).fetchone():
            raise bad_args(f"Part {pos} has media and cannot be removed.")
        conn.execute("DELETE FROM parts WHERE id = ?", (gone,))
        _renumber(conn, post_id, ids)

    return _mutate(conn, actor_id, role, cfg, post_id, "part_rm", {"pos": pos}, change)


def media_add(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    home: Path,
    post_id: str,
    part_pos: int,
    src: Path,
    alt_text: str,
    credit: str | None = None,
    source_url: str | None = None,
    licence: str | None = None,
) -> Any:
    """Add a media file, then rehash in a second short transaction (SPEC 9)."""
    _require_role(role)
    post = _load_open(conn, post_id)
    row = media.add_media(
        conn,
        home,
        post_id,
        part_pos,
        src,
        alt_text,
        platform_limits(conn).get(post["platform"], {}),
        credit,
        source_url,
        licence,
    )
    with transaction(conn):
        content.refresh_hash(conn, post_id)
        _touch(conn, cfg, post_id)
        _event(conn, cfg, actor_id, "media_add", post_id, post["status"], {"media": row["id"]})
        return post_result(conn, post_id, f"brandcal check {post_id}", [])


# --- notes and keywords ------------------------------------------------------------------


def add_note(
    conn: sqlite3.Connection,
    actor_id: str,
    cfg: Mapping[str, Any],
    post_id: str,
    text: str,
) -> Any:
    at = now_and_month(cfg)[0]
    with transaction(conn):
        status = load_post(conn, post_id)["status"]
        conn.execute(
            "UPDATE posts SET notes = CASE WHEN notes IS NULL THEN ? ELSE notes || char(10) || ?"
            " END, updated_at = ? WHERE id = ?",
            (line := f"{at} {actor_id}: {text}", line, at, post_id),
        )
        _event(conn, cfg, actor_id, "note", post_id, status)
        return post_result(conn, post_id, "", [])


def set_keywords(
    conn: sqlite3.Connection,
    actor_id: str,
    cfg: Mapping[str, Any],
    post_id: str,
    words: Sequence[str],
) -> Any:
    with transaction(conn):
        status = load_post(conn, post_id)["status"]
        conn.execute(
            "UPDATE posts SET keywords = ? WHERE id = ?", (json.dumps(list(words)), post_id)
        )
        _touch(conn, cfg, post_id)
        _event(conn, cfg, actor_id, "keywords", post_id, status, {"keywords": list(words)})
        return post_result(conn, post_id, "", [])


# --- check and submit --------------------------------------------------------------------


def check_post(conn: sqlite3.Connection, cfg: Mapping[str, Any], post_id: str) -> Any:
    """Validate at the strict stage. Read-only."""
    load_post(conn, post_id)
    errors, warnings = validate.validate(conn, post_id, platform_limits(conn), cfg, "check")
    raise_first(errors)
    return post_result(
        conn, post_id, "ready for approval" if not warnings else "review warnings", warnings
    )


def submit_post(
    conn: sqlite3.Connection,
    actor_id: str,
    role: str,
    cfg: Mapping[str, Any],
    post_id: str,
) -> Any:
    with transaction(conn):
        post = load_post(conn, post_id)
        check_transition(post["status"], "pending_approval", role)
        last = conn.execute(
            "SELECT content_hash FROM approvals WHERE post_id = ? AND decision = 'request_changes'"
            " ORDER BY id DESC LIMIT 1",
            (post_id,),
        ).fetchone()
        if last is not None and last[0] == post["content_hash"]:
            raise BrandcalError(
                ErrorCode.BAD_TRANSITION,
                "The content has not changed since changes were requested.",
                "Edit the post first, then submit again.",
            )
        errors, warnings = validate.validate(conn, post_id, platform_limits(conn), cfg, "check")
        raise_first(errors)
        conn.execute("UPDATE posts SET status = 'pending_approval' WHERE id = ?", (post_id,))
        _touch(conn, cfg, post_id)
        _event(conn, cfg, actor_id, "submit", post_id, post["status"])
        out = post_result(conn, post_id, f"manager: send a card (brandcal preview {post_id})", [])
    out["warnings"] = warnings
    return out

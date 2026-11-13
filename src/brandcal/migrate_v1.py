"""Migration from a v1 JSON calendar (SPEC 12).

``plan`` is pure; ``migrate`` applies the plan in one transaction (or just reports it).
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Collection, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from brandcal import content, events, posts, timefmt
from brandcal.config import display_tz
from brandcal.db import transaction
from brandcal.errors import BrandcalError, ErrorCode

STATUSES = ("idea", "draft", "approved", "posted", "skipped")
NOT_IMPORTED_FILE = "migrate_not_imported.json"
NEXT_STEP = "run brandcal check ID for each pending_approval post"
_KNOWN = frozenset(
    {
        "id",
        "platform",
        "status",
        "date",
        "window",
        "title",
        "body",
        "first_comment",
        "assets",
        "approved_on",
        "posted_at",
        "url",
        "posted_url",
        "notes",
    }
)
_STR_FIELDS = (
    "date",
    "window",
    "title",
    "body",
    "first_comment",
    "approved_on",
    "posted_at",
    "notes",
)
_WINDOW = re.compile(r"(\d{2}:\d{2})-(\d{2}:\d{2})")
_LOCAL_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
_MARKER = re.compile(r"^(\d+)/(?=\s|$)", re.MULTILINE)


def _bad(message: str) -> BrandcalError:
    return BrandcalError(ErrorCode.BAD_ARGS, message)


def _as_str(raw: Mapping[str, Any], key: str, ident: str) -> str:
    value = raw.get(key, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise _bad(f"Item {ident}: {key} must be a string.")
    return value


def _url_from_v1(raw: Mapping[str, Any], ident: str) -> tuple[str, str | None, str | None]:
    """Return (mapped url, raw url if the key was present, raw posted_url if present)."""
    has_url = "url" in raw
    has_posted = "posted_url" in raw
    url = _as_str(raw, "url", ident) if has_url else ""
    posted = _as_str(raw, "posted_url", ident) if has_posted else ""
    left, right = url.strip(), posted.strip()
    if left and right and left != right:
        raise _bad(f"Item {ident}: url and posted_url both set and differ.")
    return left or right, (url if has_url else None), (posted if has_posted else None)


def _unknown(raw: Mapping[str, Any], ident: str) -> dict[str, Any]:
    extra = {k: raw[k] for k in raw if k not in _KNOWN}
    if not extra:
        return {}
    try:
        json.dumps(extra, ensure_ascii=False)
    except (TypeError, ValueError) as err:
        raise _bad(f"Item {ident}: cannot preserve unknown fields: {err}.") from None
    return extra


def _raw_items(data: object) -> list[object]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return list(data["items"])
    raise _bad('The v1 file must be a JSON array, or a JSON object with an "items" list.')


def _items(data: object) -> list[dict[str, Any]]:
    """Check the shape of the file and return its items with every known field present."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n, raw in enumerate(_raw_items(data), 1):
        if not isinstance(raw, dict):
            raise _bad(f"Item {n} is not an object.")
        item: dict[str, Any] = {}
        for key in ("id", "platform", "status"):
            if not isinstance(raw.get(key), str) or not raw[key]:
                raise _bad(f"Item {n}: {key} must be a non-empty string.")
            item[key] = raw[key]
        ident = item["id"]
        for key in _STR_FIELDS:
            item[key] = _as_str(raw, key, ident)
        assets = raw.get("assets") or []
        if not isinstance(assets, list) or not all(isinstance(a, str) for a in assets):
            raise _bad(f"Item {ident}: assets must be a list of strings.")
        item["assets"] = assets
        mapped, raw_url, raw_posted = _url_from_v1(raw, ident)
        item["url"] = mapped
        item["_raw_url"] = raw_url
        item["_raw_posted_url"] = raw_posted
        item["_unknown"] = _unknown(raw, ident)
        if item["status"] not in STATUSES:
            raise _bad(f"Item {ident}: unknown status {item['status']!r}.")
        if ident in seen:
            raise _bad(f"Item id {ident!r} appears twice.")
        seen.add(ident)
        items.append(item)
    return items


def _first_agent(cfg: Mapping[str, Any], role: str) -> str:
    ids = sorted(str(a["id"]) for a in cfg.get("agents", []) if a.get("role") == role)
    if not ids:
        raise _bad(f"The config has no {role} agent; the migration needs one.")
    return ids[0]


def _local(text: str, tz: Any) -> str:
    """Format a naive local ISO date or date-time in tz."""
    try:
        return timefmt.format_time(datetime.fromisoformat(text).replace(tzinfo=tz))
    except ValueError:
        raise BrandcalError(ErrorCode.BAD_TIME, f"Cannot parse time: {text!r}.") from None


def _posted_at(text: str, tz: Any) -> str:
    stripped = text.strip()
    if _LOCAL_TIME.fullmatch(stripped):
        return _local(stripped, tz)
    if "T" not in stripped:
        return _local(f"{timefmt.parse_date(stripped).isoformat()}T00:00", tz)
    return timefmt.normalise_time(stripped, tz)


def _window(date: str, window: str, tz: Any) -> str | None:
    if not date.strip() or not window.strip():
        return None
    m = _WINDOW.fullmatch(window.strip())
    if m is None:
        raise BrandcalError(
            ErrorCode.BAD_WINDOW, f"Cannot parse window: {window!r}.", "Use HH:MM-HH:MM."
        )
    day = timefmt.parse_date(date).isoformat()
    return timefmt.normalise_window(
        f"{_local(f'{day}T{m[1]}', tz)}/{_local(f'{day}T{m[2]}', tz)}", tz
    )


def split_parts(body: str, title: str) -> list[str]:
    """Split a thread body on line-start ``1/``, ``2/`` ... markers; an empty body stays empty."""
    marks: list[re.Match[str]] = []
    for m in _MARKER.finditer(body):
        if int(m[1]) == len(marks) + 1:
            marks.append(m)
    if not marks:
        return [body.strip() or body]
    pieces = [
        body[m.end() : (marks[i + 1].start() if i + 1 < len(marks) else len(body))]
        for i, m in enumerate(marks)
    ]
    intro = body[: marks[0].start()].strip()
    if intro:
        pieces[0] = f"{intro}\n\n{pieces[0].strip()}"
    parts = [p.strip() for p in pieces if p.strip()]
    return parts or [title]


def _slug(title: str, legacy_id: str) -> str:
    for text in (title, legacy_id):
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
        if slug:
            return slug
    return "post"


def _extras(item: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "v1_status": item["status"],
        "date": item["date"],
        "window": item["window"],
        "body": item["body"],
        "first_comment": item["first_comment"],
        "assets": item["assets"],
        "approved_on": item["approved_on"],
        "posted_at": item["posted_at"],
    }
    if item["_raw_url"] is not None:
        payload["url"] = item["_raw_url"]
    if item["_raw_posted_url"] is not None:
        payload["posted_url"] = item["_raw_posted_url"]
    if item["_unknown"]:
        payload["unknown"] = item["_unknown"]
    return payload


def _not_imported(item: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "legacy_id": item["id"],
        "status": item["status"],
        "reason": reason,
        "platform": item["platform"],
        "title": item["title"],
        "body": item["body"],
        "date": item["date"],
        "window": item["window"],
        "assets": item["assets"],
        "notes": item["notes"],
        "first_comment": item["first_comment"],
    }


def _plan_item(
    item: dict[str, Any],
    cfg: Mapping[str, Any],
    tz: Any,
    *,
    keep_approved: bool = False,
    approved_words: str | None = None,
) -> dict[str, Any] | str:
    """The post to insert for one item, or the reason it is not imported."""
    status = item["status"]
    window = _window(item["date"], item["window"], tz)
    published = None
    posted_at_fallback = False
    if status == "posted":
        if item["posted_at"].strip():
            published = _posted_at(item["posted_at"], tz)
        elif item["date"].strip():
            published = _posted_at(item["date"], tz)
            posted_at_fallback = True
        else:
            return "needs posted_at or date"
    parts = split_parts(item["body"], item["title"])
    docs = [a for a in item["assets"] if a.lower().endswith(".md")]
    post: dict[str, Any] = {
        "legacy_id": item["id"],
        "status": (
            "published"
            if status == "posted"
            else "cancelled"
            if status == "skipped"
            else "approved"
            if status == "approved" and keep_approved
            else "pending_approval"
        ),
        "v1_status": status,
        "slug": _slug(item["title"], item["id"]),
        "title": item["title"],
        "platform": item["platform"],
        "post_type": "thread" if len(parts) > 1 else "text",
        "window": window,
        "parts": parts,
        "source_doc": docs[0] if docs else None,
        "notes": item["notes"] or None,
        "first_comment": item["first_comment"] or None,
        "assets": [a for a in item["assets"] if not a.lower().endswith(".md")],
        "md_assets": docs,
        "published": published,
        "posted_at_fallback": posted_at_fallback,
        "url": item["url"].strip() or None,
        "approval": None,
        "extras": _extras(item),
    }
    keep = status == "approved" and keep_approved
    if published is not None or keep:
        approver, manager = _first_agent(cfg, "approver"), _first_agent(cfg, "manager")
        decided_at = published
        if item["approved_on"].strip():
            on = timefmt.parse_date(item["approved_on"]).isoformat()
            decided_at = _local(f"{on}T00:00", tz)
        elif decided_at is None:
            decided_at = (
                _local(f"{timefmt.parse_date(item['date']).isoformat()}T00:00", tz)
                if item["date"].strip()
                else None
            )
        if keep and approved_words:
            words = approved_words
        elif keep:
            words = "legacy import, already approved in v1"
            if item["approved_on"].strip():
                words += f" (approved on {timefmt.parse_date(item['approved_on']).isoformat()})"
        else:
            words = "legacy import, unverified"
            if item["approved_on"].strip():
                words += f" (approved on {timefmt.parse_date(item['approved_on']).isoformat()})"
        if decided_at is None:
            return "needs a decision time"
        post["approval"] = {
            "decided_by": approver,
            "relayed_by": manager,
            "recorded_by": manager,
            "source_message_id": f"legacy:{item['id']}",
            "approver_words": words,
            "decided_at": decided_at,
        }
    return post


def plan(
    data: object,
    cfg: Mapping[str, Any],
    existing_legacy_ids: Collection[str],
    *,
    keep_approved: bool = False,
    approved_words: str | None = None,
) -> dict[str, Any]:
    """What a migration would do, with no database access. Ids are filled in by ``migrate``."""
    tz = display_tz(cfg)
    imported: list[dict[str, Any]] = []
    not_imported: list[dict[str, Any]] = []
    already: list[str] = []
    missing_url: list[dict[str, Any]] = []
    missing_posted_at: list[dict[str, Any]] = []
    needs_window: list[dict[str, Any]] = []
    unknown_fields: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    new_posts: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for item in _items(data):
        lid = item["id"]
        if lid in existing_legacy_ids:
            already.append(lid)
            continue
        try:
            result = _plan_item(
                item, cfg, tz, keep_approved=keep_approved, approved_words=approved_words
            )
        except BrandcalError as err:
            raise BrandcalError(err.code, f"Item {lid}: {err.message}", err.next_step) from None
        if isinstance(result, str):
            not_imported.append({"legacy_id": lid, "status": item["status"], "reason": result})
            details.append(_not_imported(item, result))
            continue
        new_posts.append(result)
        imported.append({"legacy_id": lid, "id": None, "status": result["status"]})
        if result["v1_status"] == "posted" and result["url"] is None:
            missing_url.append({"id": None, "legacy_id": lid})
        if result["posted_at_fallback"]:
            missing_posted_at.append(
                {"id": None, "legacy_id": lid, "published_at": result["published"]}
            )
        if result["status"] == "pending_approval" and result["window"] is None:
            needs_window.append({"id": None, "legacy_id": lid})
        if result["extras"].get("unknown"):
            unknown_fields.append(
                {"id": None, "legacy_id": lid, "keys": sorted(result["extras"]["unknown"])}
            )
        if result["assets"]:
            assets.append({"id": None, "legacy_id": lid, "paths": result["assets"]})
    return {
        "imported": imported,
        "not_imported": not_imported,
        "already_imported": already,
        "missing_url": missing_url,
        "missing_posted_at": missing_posted_at,
        "needs_window": needs_window,
        "unknown_fields": unknown_fields,
        "assets_to_add": assets,
        "_posts": new_posts,
        "_details": details,
    }


def _insert(conn: sqlite3.Connection, post: dict[str, Any], owner: str, now: str, who: str) -> str:
    post_id = posts.next_post_id(conn)
    status = post["status"]
    # Insert approved rows as pending_approval first: adding parts would otherwise fire
    # the content-bump trigger and drop them back to pending_approval.
    insert_status = "pending_approval" if status == "approved" else status
    closed = status in ("published", "cancelled")
    extras = json.dumps(post["extras"], ensure_ascii=False, separators=(",", ":"))
    conn.execute(
        'INSERT INTO posts (id, slug, title, platform, post_type, status, owner, "window",'
        " source_doc, notes, content_hash, legacy_id, platform_url, published_at, cancel_kind,"
        " first_comment, extras, created_at, updated_at, closed_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (post_id, post["slug"], post["title"], post["platform"], post["post_type"], insert_status)
        + (owner, post["window"], post["source_doc"], post["notes"], "0" * 64, post["legacy_id"])
        + (post["url"], post["published"], "plan" if status == "cancelled" else None)
        + (post["first_comment"], extras)
        + (now, now, (post["published"] or now) if closed else None),
    )
    conn.executemany(
        "INSERT INTO parts (post_id, pos, text) VALUES (?, ?, ?)",
        [(post_id, i, text) for i, text in enumerate(post["parts"], 1)],
    )
    # Inserting parts counted as content edits; an imported post starts at version 1.
    conn.execute("UPDATE posts SET content_version = 1 WHERE id = ?", (post_id,))
    digest = content.refresh_hash(conn, post_id)
    approval = post["approval"]
    if approval is not None:
        conn.execute(
            "INSERT INTO approvals (post_id, decision, content_version, content_hash, window,"
            " decided_by, channel, relayed_by, recorded_by, source_message_id, approver_words,"
            " decided_at) VALUES (?, 'approve', 1, ?, ?, ?, 'legacy', ?, ?, ?, ?, ?)",
            (post_id, digest, post["window"] or "", approval["decided_by"])
            + (approval["relayed_by"], approval["recorded_by"], approval["source_message_id"])
            + (approval["approver_words"], approval["decided_at"]),
        )
    if status == "approved":
        conn.execute(
            "UPDATE posts SET status = 'approved', updated_at = ? WHERE id = ?",
            (now, post_id),
        )
    events.append_event(
        conn,
        at=now,
        actor=who,
        action="migrate",
        chain=events.chain_for(post_id, ""),
        post_id=post_id,
        to_status=status,
        detail={"legacy_id": post["legacy_id"], "v1_status": post["v1_status"]},
    )
    return post_id


def _fill_ids(report: dict[str, Any], ids: Mapping[str, str]) -> None:
    for key in (
        "imported",
        "missing_url",
        "missing_posted_at",
        "needs_window",
        "unknown_fields",
        "assets_to_add",
    ):
        for entry in report[key]:
            entry["id"] = ids[entry["legacy_id"]]


def migrate(
    conn: sqlite3.Connection,
    cfg: Mapping[str, Any],
    home: Path,
    data: object,
    actor: str,
    *,
    dry_run: bool,
    out: Path | None = None,
    owner: str | None = None,
    now: str | None = None,
    keep_approved: bool = False,
    approved_words: str | None = None,
) -> dict[str, Any]:
    """Import (or, with dry_run, only report) a v1 calendar; see SPEC 12."""
    if approved_words and not keep_approved:
        raise _bad("--legacy-approved-words requires --legacy-approved.")
    existing = {
        r[0] for r in conn.execute("SELECT legacy_id FROM posts WHERE legacy_id IS NOT NULL")
    }
    report = plan(data, cfg, existing, keep_approved=keep_approved, approved_words=approved_words)
    new_posts: list[dict[str, Any]] = report.pop("_posts")
    details: list[dict[str, Any]] = report.pop("_details")
    if new_posts:
        known = {str(a["id"]) for a in cfg.get("agents", [])}
        if owner is not None and owner not in known:
            raise _bad(f"Unknown owner '{owner}'.")
        owner = owner or _first_agent(cfg, "writer")
        platforms = {r[0] for r in conn.execute("SELECT id FROM platforms")}
        for post in new_posts:
            if post["platform"] not in platforms:
                raise _bad(f"Item {post['legacy_id']}: unknown platform '{post['platform']}'.")
    report.update(ok=True, dry_run=dry_run, out=None, next=NEXT_STEP)
    if dry_run:
        first = int(posts.next_post_id(conn)[1:])
        _fill_ids(report, {p["legacy_id"]: f"p{first + i:04d}" for i, p in enumerate(new_posts)})
        return report
    stamp = now or timefmt.format_time(datetime.now(display_tz(cfg)))
    ids: dict[str, str] = {}
    with transaction(conn):
        for post in new_posts:
            ids[post["legacy_id"]] = _insert(conn, post, str(owner), stamp, actor)
    _fill_ids(report, ids)
    target = out if out is not None else home / NOT_IMPORTED_FILE
    target.write_text(
        json.dumps({"not_imported": details}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report["out"] = str(target)
    return report

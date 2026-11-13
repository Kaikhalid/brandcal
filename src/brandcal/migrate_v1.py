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
_STR_FIELDS = (
    "date",
    "window",
    "title",
    "body",
    "approved_on",
    "posted_at",
    "url",
    "notes",
)
_WINDOW = re.compile(r"(\d{2}:\d{2})-(\d{2}:\d{2})")
_LOCAL_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
_MARKER = re.compile(r"^(\d+)/(?=\s|$)", re.MULTILINE)


def _bad(message: str) -> BrandcalError:
    return BrandcalError(ErrorCode.BAD_ARGS, message)


def _items(data: object) -> list[dict[str, Any]]:
    """Check the shape of the file and return its items with every field present."""
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise _bad('The v1 file must be a JSON object with an "items" list.')
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for n, raw in enumerate(data["items"], 1):
        if not isinstance(raw, dict):
            raise _bad(f"Item {n} is not an object.")
        item: dict[str, Any] = {}
        for key in ("id", "platform", "status"):
            if not isinstance(raw.get(key), str) or not raw[key]:
                raise _bad(f"Item {n}: {key} must be a non-empty string.")
            item[key] = raw[key]
        for key in _STR_FIELDS:
            value = raw.get(key, "")
            if value is None:
                value = ""
            if not isinstance(value, str):
                raise _bad(f"Item {item['id']}: {key} must be a string.")
            item[key] = value
        assets = raw.get("assets") or []
        if not isinstance(assets, list) or not all(isinstance(a, str) for a in assets):
            raise _bad(f"Item {item['id']}: assets must be a list of strings.")
        item["assets"] = assets
        if item["status"] not in STATUSES:
            raise _bad(f"Item {item['id']}: unknown status {item['status']!r}.")
        if item["id"] in seen:
            raise _bad(f"Item id {item['id']!r} appears twice.")
        seen.add(item["id"])
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
    """Split a thread body on line-start ``1/``, ``2/`` ... markers; empty body gives the title."""
    marks: list[re.Match[str]] = []
    for m in _MARKER.finditer(body):
        if int(m[1]) == len(marks) + 1:
            marks.append(m)
    if not marks:
        return [body.strip() or title]
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
    }


def _plan_item(item: dict[str, Any], cfg: Mapping[str, Any], tz: Any) -> dict[str, Any] | str:
    """The post to insert for one item, or the reason it is not imported."""
    status = item["status"]
    if status in ("idea", "draft"):
        return str(status)
    window = _window(item["date"], item["window"], tz)
    published = None
    if status == "posted":
        if not item["posted_at"].strip():
            return "needs posted_at"
        published = _posted_at(item["posted_at"], tz)
    elif window is None:
        return "needs a date and window"
    parts = split_parts(item["body"], item["title"])
    docs = [a for a in item["assets"] if a.lower().endswith(".md")]
    notes = item["notes"]
    if len(docs) > 1:
        notes = (notes + "\n" if notes else "") + "Other source docs: " + ", ".join(docs[1:])
    post: dict[str, Any] = {
        "legacy_id": item["id"],
        "status": {"posted": "published", "approved": "pending_approval"}.get(status, "cancelled"),
        "v1_status": status,
        "slug": _slug(item["title"], item["id"]),
        "title": item["title"],
        "platform": item["platform"],
        "post_type": "thread" if len(parts) > 1 else "text",
        "window": window,
        "parts": parts,
        "source_doc": docs[0] if docs else None,
        "notes": notes or None,
        "assets": [a for a in item["assets"] if not a.lower().endswith(".md")],
        "published": published,
        "url": item["url"].strip() or None,
        "approval": None,
    }
    if published is not None:
        approver, manager = _first_agent(cfg, "approver"), _first_agent(cfg, "manager")
        words = "legacy import, unverified"
        decided_at = published
        if item["approved_on"].strip():
            on = timefmt.parse_date(item["approved_on"]).isoformat()
            words += f" (approved on {on})"
            decided_at = _local(f"{on}T00:00", tz)
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
    data: object, cfg: Mapping[str, Any], existing_legacy_ids: Collection[str]
) -> dict[str, Any]:
    """What a migration would do, with no database access. Ids are filled in by ``migrate``."""
    tz = display_tz(cfg)
    imported: list[dict[str, Any]] = []
    not_imported: list[dict[str, Any]] = []
    already: list[str] = []
    missing_url: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    new_posts: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for item in _items(data):
        lid = item["id"]
        if lid in existing_legacy_ids:
            already.append(lid)
            continue
        try:
            result = _plan_item(item, cfg, tz)
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
        if result["assets"]:
            assets.append({"id": None, "legacy_id": lid, "paths": result["assets"]})
    return {
        "imported": imported,
        "not_imported": not_imported,
        "already_imported": already,
        "missing_url": missing_url,
        "assets_to_add": assets,
        "_posts": new_posts,
        "_details": details,
    }


def _insert(conn: sqlite3.Connection, post: dict[str, Any], owner: str, now: str, who: str) -> str:
    post_id = posts.next_post_id(conn)
    status = post["status"]
    closed = status in ("published", "cancelled")
    conn.execute(
        'INSERT INTO posts (id, slug, title, platform, post_type, status, owner, "window",'
        " source_doc, notes, content_hash, legacy_id, platform_url, published_at, cancel_kind,"
        " created_at, updated_at, closed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (post_id, post["slug"], post["title"], post["platform"], post["post_type"], status)
        + (owner, post["window"], post["source_doc"], post["notes"], "0" * 64, post["legacy_id"])
        + (post["url"], post["published"], "plan" if status == "cancelled" else None)
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
    for key in ("imported", "missing_url", "assets_to_add"):
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
) -> dict[str, Any]:
    """Import (or, with dry_run, only report) a v1 calendar; see SPEC 12."""
    existing = {
        r[0] for r in conn.execute("SELECT legacy_id FROM posts WHERE legacy_id IS NOT NULL")
    }
    report = plan(data, cfg, existing)
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

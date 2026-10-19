"""Read-only views: next, today, list, show, weekly report and week page (SPEC 8.1, 8.5)."""

from __future__ import annotations

import html
import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta, tzinfo
from importlib import resources
from pathlib import Path
from string import Template
from typing import Any

from brandcal import audit, posts, timefmt
from brandcal import config as cfgmod
from brandcal.errors import BrandcalError, ErrorCode
from brandcal.transitions import CLOSED

LIMIT = 10
STALE_DAYS = 14
SOON = timedelta(hours=24)


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)


def _utc(text: str | None) -> datetime | None:
    """A SQLite ``datetime()`` text ("YYYY-MM-DD HH:MM:SS", UTC) as an aware datetime."""
    return None if text is None else datetime.fromisoformat(text).replace(tzinfo=UTC)


def short_row(post: sqlite3.Row) -> dict[str, Any]:
    return {k: post[k] for k in ("id", "status", "platform", "title", "window")}


def _start(post: sqlite3.Row) -> datetime:
    start = _utc(post["window_start_utc"])
    assert start is not None  # only legacy published posts lack a window
    return start


def _structured_reason(conn: sqlite3.Connection, post_id: str) -> dict[str, str] | None:
    """The what/where/instruction of the latest request for changes, if it has them (4.2)."""
    row = conn.execute(
        "SELECT changes_requested FROM approvals WHERE post_id = ? AND decision = 'request_changes'"
        " ORDER BY id DESC LIMIT 1",
        (post_id,),
    ).fetchone()
    try:
        data = json.loads(row[0]) if row and row[0] else None
    except ValueError:
        return None
    keys = ("what", "where", "instruction")
    if isinstance(data, dict) and all(isinstance(data.get(k), str) for k in keys):
        return {k: str(data[k]) for k in keys}
    return None


def next_for(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], agent: str, now: datetime | None = None
) -> list[dict[str, Any]]:
    role = next((str(a["role"]) for a in cfg.get("agents", []) if a.get("id") == agent), None)
    if role is None:
        raise BrandcalError(ErrorCode.NO_AGENT, f"Unknown agent '{agent}'.", "Check --as NAME.")
    at = _now(now)
    items: list[tuple[datetime, dict[str, Any]]] = []
    for p in conn.execute(
        "SELECT * FROM posts WHERE status NOT IN ('published', 'cancelled')"
        " ORDER BY window_start_utc, id"
    ):
        pid, status, start = p["id"], p["status"], _start(p)
        row = short_row(p)
        if role == "writer" and status == "changes_requested" and p["owner"] == agent:
            row["next"] = f"brandcal edit {pid} ... then brandcal submit {pid}"
            reason = _structured_reason(conn, pid)
            if reason is not None:
                row["reason"] = reason
        elif role == "approver" and status == "pending_approval":
            row["next"] = f"brandcal preview {pid}"
        elif role != "manager":
            continue
        elif status == "approved" and start <= at + SOON:
            if p["native_scheduled_at"]:
                row["next"] = f"confirm it went live, then brandcal published {pid} URL"
            else:
                row["next"] = f"brandcal begin {pid}"
        elif status == "missed":
            end = _utc(p["window_end_utc"])
            assert end is not None
            if end < at - timedelta(days=STALE_DAYS):
                row["stale"] = True
            row["next"] = f"brandcal reschedule {pid} ... or brandcal cancel {pid} ..."
        elif status == "pending_approval" and start <= at + SOON:
            row["next"] = "chase the approver"
        else:
            continue
        items.append((start, row))
    return [row for _, row in items[:LIMIT]]


def _local_day(post: sqlite3.Row, cfg: Mapping[str, Any]) -> date:
    return timefmt.local_date(_start(post), cfg_tz(cfg))


def cfg_tz(cfg: Mapping[str, Any]) -> tzinfo:
    return cfgmod.display_tz(cfg)


def _dated(conn: sqlite3.Connection, where: str = "1") -> list[sqlite3.Row]:
    sql = f"SELECT * FROM posts WHERE window IS NOT NULL AND {where} ORDER BY window_start_utc, id"  # noqa: S608
    return conn.execute(sql).fetchall()


def day(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], which: str, now: datetime | None = None
) -> list[dict[str, Any]]:
    target = timefmt.local_date(_now(now), cfg_tz(cfg)) + timedelta(days=int(which == "tomorrow"))
    return [short_row(p) for p in _dated(conn) if _local_day(p, cfg) == target]


def list_posts(
    conn: sqlite3.Connection,
    cfg: Mapping[str, Any],
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    platform: str | None = None,
    closed: bool = False,
    with_archive: bool = False,
    home: Path | None = None,
) -> list[dict[str, Any]]:
    lo = None if date_from is None else timefmt.parse_date(date_from)
    hi = None if date_to is None else timefmt.parse_date(date_to)

    def keep(p: sqlite3.Row, archived: bool) -> bool:
        if status is not None and p["status"] != status:
            return False
        if status is None and not closed and not archived and p["status"] in CLOSED:
            return False
        if platform is not None and p["platform"] != platform:
            return False
        if lo is not None or hi is not None:
            if p["window"] is None:
                return False
            d = _local_day(p, cfg)
            if (lo is not None and d < lo) or (hi is not None and d > hi):
                return False
        return True

    query = "SELECT * FROM posts ORDER BY window_start_utc, id"
    found = [
        ((p["window_start_utc"] or "", p["id"]), short_row(p))
        for p in conn.execute(query)
        if keep(p, False)
    ]
    if with_archive:
        if home is None:
            raise BrandcalError(
                ErrorCode.HOME_NOT_CONFIGURED, "The archive needs the data directory."
            )
        from brandcal import archive  # imported here: archive itself uses this module

        for month, arc in archive.overlapping(home, lo, hi):
            found += [
                (
                    (p["window_start_utc"] or "", p["id"]),
                    {**short_row(p), "archived": True, "month": month},
                )
                for p in arc.execute(query)
                if keep(p, True)
            ]
        found.sort(key=lambda item: item[0])
    return [row for _, row in found]


def show(conn: sqlite3.Connection, post_id: str, log: bool = False) -> dict[str, Any]:
    post = dict(posts.load_post(conn, post_id))
    post["parts"] = [
        dict(r)
        for r in conn.execute(
            "SELECT pos, text FROM parts WHERE post_id = ? ORDER BY pos", (post_id,)
        )
    ]
    post["media"] = [
        dict(r)
        for r in conn.execute(
            "SELECT m.path, m.kind, m.alt_text, m.sha256 FROM media m"
            " JOIN parts p ON p.id = m.part_id WHERE p.post_id = ? ORDER BY p.pos, m.pos",
            (post_id,),
        )
    ]
    post["approvals"] = [
        {k: v for k, v in dict(r).items() if k != "signature"}
        for r in conn.execute("SELECT * FROM approvals WHERE post_id = ? ORDER BY id", (post_id,))
    ]
    if log:
        events = []
        for r in conn.execute(
            "SELECT id, at, actor, action, from_status, to_status, reason, detail FROM events"
            " WHERE post_id = ? ORDER BY id",
            (post_id,),
        ):
            e = dict(r)
            e["detail"] = None if r["detail"] is None else json.loads(r["detail"])
            events.append(e)
        post["events"] = events
    return {"ok": True, **post}


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def weekly(
    conn: sqlite3.Connection,
    cfg: Mapping[str, Any],
    home: Path,
    end: date | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    tz = cfg_tz(cfg)
    at = _now(now)
    last = end if end is not None else timefmt.local_date(at, tz)
    first = last - timedelta(days=6)
    lo = datetime(first.year, first.month, first.day, tzinfo=tz)
    hi = datetime(last.year, last.month, last.day, tzinfo=tz) + timedelta(days=1)

    def inside(text: str | None) -> bool:
        return text is not None and lo <= _at(text) < hi

    def acted(action: str) -> list[sqlite3.Row]:
        return [
            r
            for r in conn.execute("SELECT * FROM events WHERE action = ? ORDER BY id", (action,))
            if inside(r["at"])
        ]

    def row_for(pid: str) -> dict[str, Any]:
        return short_row(posts.load_post(conn, pid))

    everything = conn.execute("SELECT * FROM posts ORDER BY window_start_utc, id").fetchall()
    published = [
        {**short_row(p), "platform_url": p["platform_url"]}
        for p in everything
        if p["status"] == "published" and inside(p["published_at"] or p["closed_at"])
    ]
    missed_ids = dict.fromkeys(str(e["post_id"]) for e in acted("missed"))
    waiting = []
    for p in everything:
        if p["status"] != "pending_approval":
            continue
        since = conn.execute(
            "SELECT at FROM events WHERE post_id = ? AND action IN ('add', 'submit')"
            " ORDER BY id DESC LIMIT 1",
            (p["id"],),
        ).fetchone()
        hours = None if since is None else round((at - _at(since[0])).total_seconds() / 3600, 1)
        waiting.append({**short_row(p), "hours_waiting": hours})
    today = timefmt.local_date(at, tz)
    horizon = today + timedelta(days=7)
    return {
        "ok": True,
        "from": first.isoformat(),
        "to": last.isoformat(),
        "published": published,
        "missed": [row_for(pid) for pid in missed_ids],
        "failed": [
            {"id": e["post_id"], "at": e["at"], "actor": e["actor"], "reason": e["reason"]}
            for e in acted("publish_failed")
        ],
        "cancelled": [
            {**short_row(p), "cancel_kind": p["cancel_kind"]}
            for p in everything
            if p["status"] == "cancelled" and inside(p["closed_at"])
        ],
        "waiting_for_approver": waiting,
        "next_7_days": [
            short_row(p)
            for p in _dated(conn, "status NOT IN ('published', 'cancelled')")
            if today <= _local_day(p, cfg) < horizon
        ],
        "published_without_url": [
            short_row(p) for p in everything if p["status"] == "published" and not p["platform_url"]
        ],
        "flags": audit.audit(conn, home)["flags"],
        "approvals": [
            {
                k: r[k]
                for k in (
                    "post_id",
                    "decision",
                    "decided_at",
                    "channel",
                    "source_message_id",
                    "approver_words",
                    "relayed_by",
                    "recorded_by",
                    "decided_by",
                )  # fmt: skip
            }
            for r in conn.execute("SELECT * FROM approvals ORDER BY id")
            if inside(r["decided_at"])
        ],
    }


def render_week(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], now: datetime | None = None
) -> str:
    tz = cfg_tz(cfg)
    today = timefmt.local_date(_now(now), tz)
    sections = []
    for offset in range(7):
        d = today + timedelta(days=offset)
        items = []
        for p in _dated(conn):
            if _local_day(p, cfg) != d:
                continue
            when = timefmt.parse_window(p["window"], tz)[0].astimezone(tz).strftime("%H:%M")
            parts = (when, p["platform"], p["title"], p["status"])
            items.append("<li>" + " &middot; ".join(html.escape(str(x)) for x in parts) + "</li>")
        body = "".join(items) or "<li>Nothing scheduled</li>"
        sections.append(f"<section><h2>{html.escape(d.isoformat())}</h2><ul>{body}</ul></section>")
    text = (resources.files("brandcal") / "templates" / "week.html").read_text(encoding="utf-8")
    return Template(text).substitute(
        days="\n".join(sections), range=f"{today} to {today + timedelta(days=6)}"
    )

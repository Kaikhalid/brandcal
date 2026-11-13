#!/usr/bin/env python3
# ruff: noqa: E501  (the demo posts are long lines of fake prose; the layout is kept by fmt: skip)
"""Build a clearly fake demo home for the web UI and its screenshots (UI_SPEC 7).

Everything is invented: Example Co, example.com, writer-1, manager-1 and approver@example.com.
The week is fixed by the date you pass in and every event is stamped from a fixed clock, so
the data never depends on the wall clock.

Usage: python scripts/make_demo_home.py HOME WEEK_START   (WEEK_START is a Monday, YYYY-MM-DD)
"""

from __future__ import annotations

import json
import struct
import sys
import tempfile
import zlib
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from brandcal import actions, approvals, cli, posts, publish, sweep
from brandcal.approvals import Verified
from brandcal.config import display_tz, load_config
from brandcal.db import open_db
from brandcal.timefmt import format_time, month_key

TZ = timezone(timedelta(hours=1))
TEAM = "example.cloudflareaccess.com"
AUDIENCE = "example-aud-tag"
APPROVER_EMAIL = "approver@example.com"
CONFIG: dict[str, Any] = {
    "timezone": "+01:00",
    "campaigns": ["spring-launch", "hiring"],
    "pillars": ["product", "culture"],
    "agents": [
        {"id": "writer-1", "role": "writer"},
        {"id": "manager-1", "role": "manager"},
        {"id": "approver-1", "role": "approver"},
        {"id": "admin-1", "role": "admin"},
        {"id": "system", "role": "system"},
        {"id": "console", "role": "system"},
    ],
    "serve": {
        "port": 8765,
        "allowed_origins": ["http://127.0.0.1:8765"],
        "identity": {"team_domain": TEAM, "audience": AUDIENCE, "jwks_cache_minutes": 5},
        "approvers": {APPROVER_EMAIL: "approver-1"},
        "viewers": ["viewer@example.com"],
        "console_agent": "console",
    },
}
PLATFORMS: dict[str, dict[str, object]] = {
    "linkedin": {"chars_per_post": 3000, "images_per_post": 9, "image_mb": 5},
    "x": {"chars_per_post": 280, "images_per_post": 4, "image_mb": 5},
    "instagram": {"chars_per_post": 2200, "images_per_post": 10, "image_mb": 8},
    "youtube": {"chars_per_post": 5000, "image_mb": 5},
    "bluesky": {"chars_per_post": 300, "images_per_post": 4, "image_mb": 1},
}
ALT = "Example Co team around a table with laptops, planning the spring launch"


def _png(width: int = 960, height: int = 540) -> bytes:
    """A small flat illustration (no real photograph): sky, hills and a sun."""
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            if (x - 740) ** 2 + (y - 150) ** 2 < 70**2:
                px = (250, 204, 21)
            elif y > 330 + 40 * ((x // 120) % 2) - (x % 120) // 6:
                px = (34, 120 + y // 12, 90)
            else:
                px = (96 + y // 8, 150 + y // 10, 235 - y // 12)
            rows += bytes(px)

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body)
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


class Demo:
    """Drives the library with a fixed clock; every call is a real brandcal action."""

    def __init__(self, home: Path, monday: date) -> None:
        self.home, self.monday = home, monday
        self.cfg = load_config(home)
        self.conn = open_db(home / "brand.db", display_tz(self.cfg))
        self.now = datetime.combine(monday - timedelta(days=3), time(9, 0), TZ)
        self.approver = actions.Identity("approver-1", Verified(APPROVER_EMAIL, "access-jwt"))
        self.ids: dict[str, str] = {}
        tz = display_tz(self.cfg)

        def fixed(_cfg: object) -> tuple[str, str]:
            return format_time(self.now), month_key(self.now, tz)

        # Events and decisions take their time from this clock, not the wall clock.
        posts.now_and_month = fixed  # type: ignore[assignment]
        approvals.now_and_month = fixed  # type: ignore[assignment,attr-defined]

    def tick(self, minutes: int = 17) -> None:
        self.now += timedelta(minutes=minutes)

    def window(self, day: int, start: int, hours: int = 1) -> str:
        first = datetime.combine(self.monday + timedelta(days=day), time(start), TZ)
        return f"{format_time(first)}/{format_time(first + timedelta(hours=hours))}"

    def add(self, key: str, day: int, start: int, platform: str, kind: str, **extra: Any) -> str:
        who, role = ("manager-1", "manager") if kind == "comment" else ("writer-1", "writer")
        data = {
            "slug": key,
            "platform": platform,
            "post_type": kind,
            "window": self.window(day, start),
            "campaign": "spring-launch",
            "pillar": "product",
            **extra,
        }
        self.tick()
        out = posts.add_post(self.conn, who, role, self.cfg, data)
        self.ids[key] = str(out["id"])
        return self.ids[key]

    def seen(self, key: str) -> tuple[int, str, str]:
        row = posts.load_post(self.conn, self.ids[key])
        return int(row["content_version"]), str(row["content_hash"]), str(row["window"])

    def approve(self, key: str) -> None:
        version, digest, window = self.seen(key)
        self.tick()
        actions.approve(
            self.conn, self.cfg, self.approver, self.ids[key], version, digest[:8], "console",
            f"demo-{key}", "Approve", seen_window=window,
        )  # fmt: skip

    def ask_changes(self, key: str) -> None:
        version, digest, window = self.seen(key)
        self.tick()
        actions.request_changes(
            self.conn, self.cfg, self.approver, self.ids[key], version, digest[:8],
            f"demo-{key}", "Request changes", what="The opening line is too long.",
            where="Part 1, first sentence", instruction="Shorten it to one clear claim.",
            channel="console", seen_window=window,
        )  # fmt: skip

    def manager(self, call: Callable[..., Any], *args: Any, **kw: Any) -> None:
        self.tick()
        call(self.conn, "manager-1", "manager", self.cfg, *args, **kw)


def build(home: Path, week_start: date) -> None:
    """Create the home at ``home`` with posts in all six states in the week of ``week_start``."""
    if week_start.weekday() != 0:
        raise ValueError("WEEK_START must be a Monday")
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(json.dumps(CONFIG, indent=2), encoding="utf-8")
    (home / "platforms.json").write_text(json.dumps(PLATFORMS, indent=2), encoding="utf-8")
    if cli.main(["--home", str(home), "init", "--as", "admin-1"]) != 0:
        raise RuntimeError("init failed")
    d = Demo(home, week_start)
    cfg, conn = d.cfg, d.conn
    try:
        # Monday: published.
        d.add("hiring-update", 0, 9, "linkedin", "text", title="We are hiring a designer",
              campaign="hiring", pillar="culture",
              parts=[{"text": "Example Co is hiring a product designer.\nRemote friendly, based in any time zone."}])  # fmt: skip
        d.approve("hiring-update")
        d.tick()
        publish.begin(conn, "manager-1", "manager", cfg, home, d.ids["hiring-update"],
                      now=datetime.combine(week_start, time(9, 10), TZ))  # fmt: skip
        publish.published(conn, "manager-1", "manager", cfg, d.ids["hiring-update"],
                          "https://example.com/posts/hiring-update",
                          now=datetime.combine(week_start, time(9, 14), TZ))  # fmt: skip
        # Tuesday morning: approved, then missed by the sweep.
        d.add("newsletter-nudge", 1, 8, "linkedin", "text", title="Newsletter reminder",
              parts=[{"text": "The spring newsletter goes out this week. Subscribe at example.com."}])  # fmt: skip
        d.approve("newsletter-nudge")
        d.now = datetime.combine(week_start + timedelta(days=1), time(12, 0), TZ)
        sweep.sweep(conn, cfg, now=d.now)
        # Tuesday: an image waiting for approval, with alt text and two versions.
        d.add("team-photo", 1, 10, "instagram", "image", title="Planning day at Example Co",
              parts=[{"text": "Planning day at Example Co. Big things coming this spring."}])  # fmt: skip
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "planning-day.png"
            src.write_bytes(_png())
            d.tick()
            posts.media_add(conn, "writer-1", "writer", cfg, home, d.ids["team-photo"], 1, src,
                            ALT, "Example Co", "https://example.com/team", "CC0")  # fmt: skip
        d.tick()
        posts.part_edit(conn, "writer-1", "writer", cfg, d.ids["team-photo"], 1,
                        "Planning day at Example Co. Big things are coming this spring.")  # fmt: skip
        # Tuesday afternoon: a thread, approved and queued in the platform's own scheduler.
        d.add("launch-thread", 1, 14, "x", "thread", title="Spring launch thread",
              parts=[{"text": "Spring launch: three things we shipped this month. A thread."},
                     {"text": "1/ Shared calendars now show every time in your own time zone."},
                     {"text": "2/ Approvals record exactly what was agreed. Read more: example.com/launch"}])  # fmt: skip
        d.approve("launch-thread")
        d.manager(publish.schedule, home, d.ids["launch-thread"],
                  d.window(1, 14).split("/")[0], now=d.now)  # fmt: skip
        # Wednesday: an article waiting, and a post that needs changes.
        d.add("launch-article", 2, 9, "linkedin", "article", title="How we plan a launch",
              parts=[{"text": "Planning a launch starts with a calendar everyone can read."}])  # fmt: skip
        d.add("teaser", 2, 15, "x", "text", title="Launch teaser",
              parts=[{"text": "Something new is landing on Thursday. Here is a first look at what the whole Example Co team has been building for the past few months, with a lot of care."}])  # fmt: skip
        d.ask_changes("teaser")
        # Thursday: a video, and a reshare claimed for publishing.
        d.add("demo-video", 3, 11, "youtube", "video", title="Product walkthrough",
              parts=[{"text": "A two minute walkthrough of the spring release."}])  # fmt: skip
        d.add("partner-reshare", 3, 16, "linkedin", "reshare", title="Partner announcement",
              target_url="https://example.org/news/partner-launch",
              parts=[{"text": "Congratulations to our partners at Example Org on their launch."}])  # fmt: skip
        d.approve("partner-reshare")
        d.manager(publish.begin, home, d.ids["partner-reshare"],
                  now=datetime.combine(week_start + timedelta(days=3), time(16, 5), TZ))  # fmt: skip
        # Friday: a delegated comment, and a carousel that was cancelled.
        d.add("thread-reply", 4, 10, "linkedin", "comment", title="Reply to partner thread",
              target_url="https://example.org/news/partner-thread",
              delegation_msg_id="demo-delegation-1", delegation_words="Yes, reply for us",
              parts=[{"text": "Thanks for the kind words. We are excited to build this together."}])  # fmt: skip
        d.add("old-carousel", 4, 13, "instagram", "carousel", title="Feature carousel",
              parts=[{"text": "Five features in five slides."}])  # fmt: skip
        version, digest, window = d.seen("old-carousel")
        d.tick()
        actions.cancel(conn, cfg, d.approver, d.ids["old-carousel"], "idea",
                       "Replaced by the launch thread", "demo-cancel", "Cancel",
                       channel="console", seen=(version, digest, window))  # fmt: skip
        # Saturday: a short post from the bluesky account.
        d.add("weekend-note", 5, 10, "bluesky", "text", title="Weekend note",
              parts=[{"text": "Quiet weekend at Example Co. See you Monday."}])  # fmt: skip
    finally:
        conn.close()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    build(Path(argv[0]), date.fromisoformat(argv[1]))
    print(f"demo home written to {argv[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

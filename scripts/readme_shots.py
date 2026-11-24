#!/usr/bin/env python3
# ruff: noqa: E501  (the showcase posts are long lines of fake prose)
"""Rebuild the README screenshots from a clearly fake Example Co showcase calendar.

Everything shown is invented (Example Co, example.com, approver@example.com). The data is
built with scripts/make_demo_home.py plus a few more weeks of posts, served by
`brandcal serve` in-process behind a local, test-only Access signer, and captured with
Playwright at 2x with the browser clock pinned, so the shots never depend on the wall clock.

Needs: pip install -e ".[dev,crypto,ui-test]", python -m playwright install chromium.
Usage: python scripts/readme_shots.py [OUT_DIR]   (default build/readme-shots, git-ignored)
Then: python scripts/readme_hero.py to compose docs/img/ from those raw shots.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from jwt_env import AUD, TEAM, FakeJwks, Signer, claims  # noqa: E402

from brandcal import publish, serve  # noqa: E402
from brandcal.config import load_config  # noqa: E402
from brandcal.identity import Verifier  # noqa: E402

WEEK = date(2026, 3, 2)  # a Monday; the month view is March 2026
CLOCK = "2026-03-03T12:40:00+01:00"  # the browser's "now": Tuesday lunchtime
DESKTOP = {"width": 1440, "height": 900}
PHONE = {"width": 390, "height": 844}


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# (key, day from WEEK, hour, platform, kind, title, text, state) for the rest of March.
MORE: list[tuple[str, int, int, str, str, str, str, str]] = [
    (
        "office-hours",
        2,
        12,
        "linkedin",
        "text",
        "Office hours, live",
        "Join the Example Co team for open office hours this Wednesday.",
        "approved",
    ),
    (
        "tip-week-1",
        4,
        8,
        "x",
        "text",
        "Tip of the week",
        "Tip: write the approval window into the brief, not the chat.",
        "scheduled",
    ),
    (
        "weekend-reel",
        6,
        11,
        "instagram",
        "video",
        "Behind the scenes reel",
        "Sixty seconds behind the scenes of the spring launch.",
        "pending",
    ),
    (
        "customer-story",
        7,
        9,
        "linkedin",
        "article",
        "Customer story: Example Org",
        "How Example Org plans a quarter of posts in one afternoon.",
        "approved",
    ),
    (
        "launch-recap",
        8,
        14,
        "x",
        "thread",
        "Launch week recap",
        "Launch week, in five posts. A thread.",
        "pending",
    ),
    (
        "team-spotlight",
        9,
        10,
        "instagram",
        "carousel",
        "Team spotlight",
        "Meet the people behind the spring release.",
        "pending",
    ),
    (
        "webinar-invite",
        10,
        16,
        "linkedin",
        "text",
        "Webinar invite",
        "Planning a launch with a small team: a free 30 minute webinar.",
        "scheduled",
    ),
    (
        "tip-week-2",
        11,
        8,
        "x",
        "text",
        "Tip of the week",
        "Tip: one owner approves, everyone else drafts.",
        "scheduled",
    ),
    (
        "bluesky-hello",
        12,
        10,
        "bluesky",
        "text",
        "Hello, Bluesky",
        "Example Co is now on Bluesky. Say hello.",
        "pending",
    ),
    (
        "product-update",
        14,
        9,
        "linkedin",
        "text",
        "March product update",
        "What shipped in March, in plain words.",
        "pending",
    ),
    (
        "faq-video",
        16,
        11,
        "youtube",
        "video",
        "Five questions, answered",
        "The five questions we hear most, answered in four minutes.",
        "pending",
    ),
    (
        "tip-week-3",
        18,
        8,
        "x",
        "text",
        "Tip of the week",
        "Tip: keep every time with its offset, and nobody misses a slot.",
        "approved",
    ),
    (
        "community-call",
        21,
        17,
        "linkedin",
        "text",
        "Community call",
        "Our first community call is on Thursday. Bring questions.",
        "pending",
    ),
    (
        "spring-sale",
        22,
        12,
        "instagram",
        "image",
        "Spring offer",
        "A spring offer for teams of every size.",
        "pending",
    ),
    (
        "tip-week-4",
        25,
        8,
        "x",
        "text",
        "Tip of the week",
        "Tip: the audit log is the answer to who approved what.",
        "pending",
    ),
    (
        "month-wrap",
        26,
        15,
        "linkedin",
        "text",
        "March in review",
        "Thank you for a busy March. Here is what is next.",
        "pending",
    ),
]


def build_home(home: Path) -> None:
    demo = load("make_demo_home")
    demo.CONFIG["serve"]["console_approvals"] = True  # the seeded approvals need it
    demo.build(home, WEEK)
    d = demo.Demo(home, WEEK)
    d.now = datetime.combine(WEEK + timedelta(days=1), time(12, 5), demo.TZ)

    def tick(minutes: int = 0) -> None:  # keep every extra event before the browser's "now"
        d.now += timedelta(seconds=15)

    d.tick = tick
    try:
        for key, day, hour, platform, kind, title, text, state in MORE:
            parts = [{"text": text}]
            if kind == "thread":
                parts += [{"text": "1/ Every post was approved by a person, version by version."}]
            extra: dict[str, Any] = {"title": title, "parts": parts}
            d.add(key, day, hour, platform, kind, **extra)
            if state in ("approved", "scheduled"):
                d.approve(key)
            if state == "scheduled":
                d.manager(
                    publish.schedule, home, d.ids[key], d.window(day, hour).split("/")[0], now=d.now
                )
    finally:
        d.conn.close()


CURSOR = (
    "(() => { const c = document.createElement('div'); c.id = 'demo-cursor';"
    " Object.assign(c.style, {position: 'fixed', left: '0px', top: '0px', width: '22px',"
    " height: '22px', borderRadius: '50%', background: 'rgba(0,0,0,.28)',"
    " border: '2px solid #fff', boxShadow: '0 1px 4px rgba(0,0,0,.35)', zIndex: 99999,"
    " pointerEvents: 'none', transition: 'none'}); document.body.appendChild(c); })()"
)


def approve_flow(browser: Any, url: str, token: str, out: Path) -> None:
    """Frames of approving one post from the week view, for docs/img/approve-flow.webp."""
    ctx = browser.new_context(
        viewport=DESKTOP, device_scale_factor=1, color_scheme="light",
        reduced_motion="reduce", timezone_id="Africa/Lagos",
        extra_http_headers={"Cf-Access-Jwt-Assertion": token},
    )  # fmt: skip
    page = ctx.new_page()
    page.clock.set_fixed_time(datetime.fromisoformat(CLOCK))
    page.goto(f"{url}/?view=week&date={WEEK.isoformat()}")
    page.get_by_role("heading", level=1).wait_for(timeout=10_000)
    page.locator('[aria-busy="true"]').first.wait_for(state="detached", timeout=10_000)
    page.evaluate(CURSOR)
    frames = out / "approve-flow"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir()
    n = 0

    def frame(hold_ms: int) -> None:
        nonlocal n
        page.wait_for_timeout(150)
        page.screenshot(path=str(frames / f"{n:03d}-{hold_ms}.png"))
        n += 1

    def glide(target: Any, steps: int = 8) -> None:
        box = target.bounding_box()
        assert box
        x1, y1 = box["x"] + min(box["width"] / 2, 60), box["y"] + min(box["height"] / 2, 18)
        x0, y0 = page.evaluate(
            "(() => { const c = document.getElementById('demo-cursor');"
            " return [parseFloat(c.style.left), parseFloat(c.style.top)]; })()"
        )
        for i in range(1, steps + 1):
            x, y = x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps
            page.evaluate(
                "([x, y]) => { const c = document.getElementById('demo-cursor');"
                " c.style.left = (x - 11) + 'px'; c.style.top = (y - 11) + 'px'; }",
                [x + 11, y + 11],
            )
            frame(60)
        page.mouse.move(x1, y1)

    page.evaluate(
        "() => { const c = document.getElementById('demo-cursor');"
        " c.style.left = '640px'; c.style.top = '600px'; }"
    )
    frame(1200)
    card = page.locator("[data-post-id]", has_text="How we plan a launch").first
    glide(card)
    frame(400)
    card.click()
    page.locator("aside[data-post-panel] pre").first.wait_for(timeout=10_000)
    frame(1400)
    approve = page.locator('aside[data-post-panel] [data-action-button="approve"]')
    glide(approve)
    approve.click()
    dialog = page.locator('[data-action-dialog="approve"]')
    dialog.wait_for(timeout=10_000)
    frame(1600)
    submit = dialog.locator("button[type=submit]")
    glide(submit)
    submit.click()
    page.locator("[data-notice]", has_text="done").wait_for(timeout=10_000)
    page.locator('[aria-busy="true"]').first.wait_for(state="detached", timeout=10_000)
    frame(2600)
    ctx.close()


def main(argv: list[str]) -> int:
    out = Path(argv[0]) if argv else ROOT / "build" / "readme-shots"
    out.mkdir(parents=True, exist_ok=True)
    home = Path(tempfile.mkdtemp()) / "home"
    build_home(home)
    signer = Signer()
    server = serve.make_server(
        home, load_config(home), 0, Verifier(TEAM, AUD, 5, fetch=FakeJwks(signer))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    server.app.origins, server.app.hosts = [url], {url.split("//")[1]}  # type: ignore[attr-defined]
    token = signer.token(claims())
    day = WEEK.isoformat()
    shots: list[tuple[str, str, dict[str, int], str | None]] = [
        ("calendar-week", f"/?view=week&date={day}", DESKTOP, None),
        ("calendar-month", f"/?view=month&date={day}", DESKTOP, None),
        ("needs-you", "/needs-you/", DESKTOP, None),
        ("posts", "/posts/", DESKTOP, None),
        ("activity", "/activity/", DESKTOP, None),
        ("channels", f"/channels/?date={day}", DESKTOP, None),
        ("post-panel", f"/?view=week&date={day}", DESKTOP, "Spring launch thread"),
        ("post-panel-pending", f"/?view=week&date={day}", DESKTOP, "Planning day at Example Co"),
        ("mobile-week", f"/?view=week&date={day}", PHONE, None),
        ("mobile-needs-you", "/needs-you/", PHONE, None),
    ]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for scheme in ("light", "dark"):
                for name, path, size, panel in shots:
                    ctx = browser.new_context(
                        viewport=size, device_scale_factor=2, color_scheme=scheme,
                        reduced_motion="reduce", timezone_id="Africa/Lagos",
                        extra_http_headers={"Cf-Access-Jwt-Assertion": token},
                    )  # fmt: skip
                    page = ctx.new_page()
                    page.clock.set_fixed_time(datetime.fromisoformat(CLOCK))
                    page.goto(url + path)
                    page.get_by_role("heading", level=1).wait_for(timeout=10_000)
                    page.locator('[aria-busy="true"]').first.wait_for(
                        state="detached", timeout=10_000
                    )
                    if panel:
                        page.locator("[data-post-id]", has_text=panel).first.click()
                        page.locator("aside[data-post-panel] pre").first.wait_for(timeout=10_000)
                    page.wait_for_timeout(500)
                    page.screenshot(path=str(out / f"{name}-{scheme}.png"))
                    ctx.close()
            approve_flow(browser, url, token, out)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print(f"shots written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

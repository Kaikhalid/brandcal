# ruff: noqa: F811
# (the fixtures come from test_next_home.py by name, the usual pytest way to share them)
"""The read views of the new UI (N2): Calendar, Needs you, Posts, Channels, Activity and the panel.

Same fixtures and helpers as test_next_home.py (the demo home pinned to the week of WEEK, a
verified approver, a --dev-unverified viewer). Each view loads in light and dark at 1440x900 with
zero console errors and zero CSP violations, writes build/ui-shots/next-<view>-<theme>.png and an
advisory axe report. The behaviour tests check URL state, focus, inert, the diff and the grid.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import pytest

expect = pytest.importorskip("playwright.sync_api").expect
pytest.importorskip("cryptography")

from test_next_home import (  # noqa: E402, F401  (fixtures are used by name)
    PHONE,
    SCHEMES,
    axe_report,
    browser,
    dev_site,
    home,
    idle,
    open_page,
    shot,
    site,
    until,
)
from test_screens import WEEK  # noqa: E402

DATE = WEEK.isoformat()
TUESDAY = (WEEK + timedelta(days=1)).isoformat()
LAPTOP = {"width": 1024, "height": 768}

# name -> (path, query, a selector that only exists once the data is drawn)
VIEWS = {
    "calendar-week": ("/", f"?view=week&date={DATE}", "[data-post-id]"),
    "calendar-month": ("/", f"?view=month&date={DATE}", "[data-post-id]"),
    "needs-you": ("/needs-you/", "", "[data-post-id]"),
    "posts": ("/posts/", "", "tr[data-post-id]"),
    "channels": ("/channels/", f"?date={DATE}", "[data-platform]"),
    "activity": ("/activity/", "", "[data-event-id]"),
}


def post_id(page: Any, title: str) -> str:
    found: str = page.evaluate(
        "async t => (await (await fetch('/api/posts?closed=1')).json()).posts"
        ".find(p => p.title === t).id",
        title,
    )
    return found


def wait_drawn(page: Any, selector: str) -> None:
    page.locator(selector).first.wait_for(timeout=10_000)
    idle(page)


def load(
    browser: Any, site: tuple[str, str], view: str, scheme: str, size: dict[str, int] | None = None
) -> tuple[Any, list[str]]:
    path, query, ready = VIEWS[view]
    page, problems = open_page(
        browser, site, path, scheme, query=query, **({"size": size} if size else {})
    )
    wait_drawn(page, ready)
    return page, problems


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("view", list(VIEWS))
def test_view_loads_clean_in_both_themes(
    browser: Any, site: tuple[str, str], view: str, scheme: str
) -> None:
    page, problems = load(browser, site, view, scheme)
    try:
        page.wait_for_timeout(200)
        shot(page, f"next-{view}-{scheme}")
        axe_report(page, f"next-{view}-{scheme}")
        assert page.evaluate("window.__csp") == []
        assert not problems, problems
        assert page.locator("h1").count() == 1
    finally:
        page.context.close()


@pytest.mark.parametrize("scheme", SCHEMES)
def test_panel_loads_clean_in_both_themes(browser: Any, site: tuple[str, str], scheme: str) -> None:
    page, _ = open_page(browser, site, "/", scheme, query=f"?view=week&date={DATE}")
    try:
        pid = post_id(page, "Spring launch thread")
    finally:
        page.context.close()
    page, problems = open_page(
        browser, site, "/", scheme, query=f"?view=week&date={DATE}&post={pid}"
    )
    try:
        wait_drawn(page, "aside[data-post-panel] pre")
        page.wait_for_timeout(200)
        shot(page, f"next-panel-{scheme}")
        axe_report(page, f"next-panel-{scheme}")
        assert page.evaluate("window.__csp") == []
        assert not problems, problems
        panel = page.get_by_role("complementary", name="Spring launch thread")
        assert panel.is_visible()
        text = panel.inner_text()
        for needle in ("Part 1 of 3", "/ 280 characters", "Agent equivalents (CLI)", "Audit trail"):
            assert needle in text, needle
    finally:
        page.context.close()


def test_the_week_places_a_post_in_its_days_stack_in_time_order(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = load(browser, site, "calendar-week", "light")
    try:
        pid = post_id(page, "Planning day at Example Co")  # Tuesday, 10:00 to 11:00
        card = page.locator(f'button[data-post-id="{pid}"]')
        assert card.get_attribute("data-day") == TUESDAY
        assert card.get_attribute("data-start") == "10:00"
        stack = page.locator(f'section[data-day="{TUESDAY}"]')
        assert stack.locator(f'button[data-post-id="{pid}"]').count() == 1
        # No hour axis: the card sits at the top of its stack, ordered by start time.
        starts = stack.locator("button[data-post-id]").evaluate_all(
            "els => els.map(e => [e.dataset.start, e.getBoundingClientRect().top])"
        )
        assert [s for s, _ in starts] == sorted(s for s, _ in starts), starts
        assert [y for _, y in starts] == sorted(y for _, y in starts), starts
        assert "10:00" in card.inner_text()
        # The tooltip carries the whole window with the zone offset (S10).
        assert re.search(r"10:00 to 11:00 \([+-]\d\d:\d\d\)", card.get_attribute("title") or "")
        heading = page.get_by_role("heading", level=1).inner_text()
        assert "9 – 15 March 2026" in heading
    finally:
        page.context.close()


def test_the_month_view_shows_posts_and_the_week_navigates(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = load(browser, site, "calendar-month", "light")
    try:
        assert "March 2026" in page.get_by_role("heading", level=1).inner_text()
        assert page.locator("[data-post-id]").count() >= 8
        page.get_by_role("button", name="Next month").click()
        page.wait_for_url(re.compile("date=2026-04-01"))
        page.get_by_role("button", name="Week", exact=True).click()
        page.wait_for_url(re.compile("view=week"))
        page.go_back()
        page.wait_for_url(re.compile("view=month"))
    finally:
        page.context.close()


def test_a_platform_checkbox_in_the_filters_popover_sets_the_url(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = load(browser, site, "calendar-week", "light")
    try:
        page.locator("[data-filters-toggle]").click()
        box = page.locator('[data-filter="platform:linkedin"]')
        before = page.locator("[data-post-id]").count()
        assert not box.is_checked()
        box.click()  # the URL is the state, so the box ticks a moment after the click
        page.wait_for_url(re.compile("platform=linkedin"))
        expect(box).to_be_checked()
        expect(page.locator("[data-post-id]")).not_to_have_count(before)
        platforms = page.locator("[data-post-id] [data-platform]").evaluate_all(
            "els => [...new Set(els.map(e => e.dataset.platform))]"
        )
        assert platforms == ["linkedin"], platforms
        assert page.locator("[data-post-id]").count() < before
        box.click()
        expect(box).not_to_be_checked()
        assert "platform=" not in page.url
        page.get_by_label("Search by slug").fill("launch-thread")
        page.wait_for_url(re.compile("q=launch-thread"))
        expect(page.locator("[data-post-id]")).to_have_count(1)
    finally:
        page.context.close()


def test_the_panel_takes_focus_makes_the_page_inert_and_gives_focus_back(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = load(browser, site, "calendar-week", "light", LAPTOP)
    try:
        pid = post_id(page, "Spring launch thread")
        opener = page.locator(f'button[data-post-id="{pid}"]')
        opener.click()
        page.wait_for_url(re.compile(f"post={pid}"))
        until(page, "document.querySelector('aside')?.contains(document.activeElement)")
        assert page.evaluate("document.getElementById('shell-body').inert") is True
        expect(page.get_by_role("complementary", name="Spring launch thread")).to_be_visible()
        page.keyboard.press("Escape")
        page.locator("aside").wait_for(state="detached")
        assert "post=" not in page.url
        assert page.evaluate("document.getElementById('shell-body').inert") is False
        assert page.evaluate("document.activeElement.dataset.postId") == pid
    finally:
        page.context.close()


def test_from_1200px_the_panel_sits_beside_the_content(browser: Any, site: tuple[str, str]) -> None:
    page, _ = load(browser, site, "calendar-week", "light")
    try:
        pid = post_id(page, "Spring launch thread")
        page.locator(f'button[data-post-id="{pid}"]').click()
        until(page, "document.querySelector('aside')?.contains(document.activeElement)")
        assert page.evaluate("document.getElementById('shell-body').inert") is False
        main = page.get_by_role("main").bounding_box()
        panel = page.locator("aside").bounding_box()
        assert main and panel and main["x"] + main["width"] <= panel["x"] + 1
        page.get_by_role("button", name="Close panel").click()
        page.locator("aside").wait_for(state="detached")
        # The calendar swaps bands for columns as the panel leaves, so the opener is new.
        until(page, f"document.activeElement?.dataset.postId === '{pid}'")
    finally:
        page.context.close()


def test_a_directly_loaded_panel_returns_focus_to_the_main_heading(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = open_page(browser, site, "/posts/", "light")
    try:
        pid = post_id(page, "Spring launch thread")
        page.goto(f"{site[0]}/posts/?post={pid}")
        page.locator("aside h2").wait_for()
        page.keyboard.press("Escape")
        page.locator("aside").wait_for(state="detached")
        assert page.evaluate("document.activeElement.tagName") == "H1"
    finally:
        page.context.close()


def test_the_panel_diffs_two_versions_with_signs_and_shows_media(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = load(browser, site, "calendar-week", "light")
    try:
        pid = post_id(page, "Planning day at Example Co")
        page.locator(f'button[data-post-id="{pid}"]').click()
        # History, Compare and the CLI lines are disclosures, closed on open.
        page.locator("aside").get_by_role("button", name="Compare versions").click()
        page.locator("aside").get_by_role("button", name="Agent equivalents (CLI)").click()
        diff = page.locator("aside [data-diff]")
        diff.wait_for()
        added = diff.locator("[data-sign=add]")
        removed = diff.locator("[data-sign=del]")
        assert added.count() >= 1 and removed.count() >= 1
        assert added.first.inner_text().startswith("+ ")
        assert removed.first.inner_text().startswith("- ")
        image = page.locator("aside figure img")
        assert image.get_attribute("alt", timeout=5_000)
        assert "Alt text:" in page.locator("aside figure figcaption").inner_text()
        page.get_by_role("button", name=re.compile("^Fingerprint")).click()
        said = page.locator("aside [role=status]").filter(has_text=re.compile("Copied|copy"))
        expect(said).to_have_count(1)
        wanted = page.evaluate(
            "async id => { const p = await (await fetch('/api/posts/' + id)).json();"
            " return [...p.actions, p.note].filter(Boolean).map(a => [a.id, a.cli]); }",
            pid,
        )
        assert len(wanted) >= 3
        for action, cli in wanted:  # each action: a button (N3) and its exact CLI line
            assert page.locator(f'aside [data-cli-for="{action}"] code').inner_text() == cli
            assert page.locator(f'aside [data-action-button="{action}"]').count() == 1
    finally:
        page.context.close()


def test_needs_you_lists_the_posts_the_badge_counts(browser: Any, site: tuple[str, str]) -> None:
    page, _ = load(browser, site, "needs-you", "light")
    try:
        sections = page.locator("main section[data-status]")
        assert sections.count() == 3
        rows = page.locator("main li button[data-post-id]").count()
        expected = page.evaluate(
            "async () => { const s = await (await fetch('/api/schema')).json(); let n = 0;"
            " for (const x of s.needs_you) n += (await (await fetch('/api/posts?status=' + x))"
            ".json()).posts.length; return n; }"
        )
        assert rows == expected
        badge = page.get_by_role("navigation", name="Primary").get_by_role(
            "link", name=re.compile("^Needs you")
        )
        assert str(expected) in badge.inner_text()
        assert "Awaiting you" in sections.first.inner_text()
    finally:
        page.context.close()


def test_a_viewer_is_told_a_post_awaits_approval_not_awaiting_you(
    browser: Any, dev_site: tuple[str, str]
) -> None:
    page, _ = open_page(browser, dev_site, "/needs-you/", "light")
    try:
        chip = page.locator("main span[data-status=pending_approval]").first
        chip.wait_for()
        assert chip.inner_text().strip() == "Awaiting approval"
        assert chip.get_attribute("title") == "pending_approval"
    finally:
        page.context.close()


def test_posts_sort_by_window_and_rows_open_the_panel(browser: Any, site: tuple[str, str]) -> None:
    page, _ = load(browser, site, "posts", "light")
    try:
        first = page.locator("tbody tr").first.get_attribute("data-post-id")
        page.get_by_role("button", name=re.compile("^Window")).click()
        page.wait_for_url(re.compile("sort=-window"))
        expect(page.locator("tbody tr").first).not_to_have_attribute("data-post-id", first or "")
        assert page.locator("th[aria-sort=descending]").count() == 1
        assert page.locator("tbody tr").count() >= 8  # open posts only until "closed" is asked
        page.locator("tbody tr button").first.click()
        page.locator("aside h2").wait_for()
    finally:
        page.context.close()


def test_channels_show_limits_and_counts(browser: Any, site: tuple[str, str]) -> None:
    page, _ = load(browser, site, "channels", "light")
    try:
        cards = page.locator("main section[data-platform]")
        assert cards.count() == 5
        x = page.locator('main section[data-platform="x"]')
        assert "280" in x.inner_text()
        linkedin = page.locator('main section[data-platform="linkedin"]')
        assert "https://example.com/posts/hiring-update" in linkedin.inner_text()
        assert linkedin.locator("[data-status=published]").count() == 1
    finally:
        page.context.close()


def test_activity_shows_who_and_how_and_checks_for_new(browser: Any, site: tuple[str, str]) -> None:
    page, _ = load(browser, site, "activity", "light")
    try:
        rows = page.locator("li[data-event-id]")
        ids = rows.evaluate_all("els => els.map(e => Number(e.dataset.eventId))")
        assert ids == sorted(ids, reverse=True)  # newest first
        older = page.get_by_role("button", name="Load older")
        if older.count():
            older.click()
            assert page.locator("li[data-event-id]").count() > len(ids)
        page.get_by_role("button", name="Check for new").click()
        page.get_by_role("status").filter(has_text="Nothing new").wait_for()
        page.locator("#activity-post").select_option(label="Spring launch thread")
        page.wait_for_url(re.compile("for="))
        until(
            page,
            "document.querySelectorAll('li[data-event-id]').length > 0"
            " && document.querySelectorAll('li[data-event-id]').length < 50",
        )
        assert "console (verified)" in page.locator("main").inner_text()
    finally:
        page.context.close()


@pytest.mark.parametrize("view", ["calendar-week", "calendar-month", "posts", "needs-you"])
@pytest.mark.parametrize("size", [LAPTOP, PHONE], ids=["1024", "390"])
def test_the_views_fit_small_screens(
    browser: Any, site: tuple[str, str], view: str, size: dict[str, int]
) -> None:
    page, problems = load(browser, site, view, "light", size)
    try:
        page.wait_for_timeout(200)
        shot(page, f"next-{view}-{size['width']}")
        assert not problems, problems
        if view.startswith("calendar") and size is PHONE:
            assert page.locator("h3[aria-current=date], section[data-day] h3").count() >= 1
            # Day bands, not columns: the region holds sections, never the seven stacks.
            assert page.locator("[aria-label='Week calendar'] [data-week-stacks]").count() == 0
        # No page-wide sideways scroll; only the grid or table scrolls itself.
        offenders = page.evaluate(
            "[...document.querySelectorAll('body *')].filter(e => !e.closest('[role=region]')"
            " && e.getBoundingClientRect().right > window.innerWidth + 1).slice(0, 5)"
            ".map(e => e.tagName + '.' + String(e.className).slice(0, 60))"
        )
        assert offenders == [], offenders
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    finally:
        page.context.close()


def test_the_panel_hides_a_same_day_window_that_repeats_when(
    browser: Any, site: tuple[str, str]
) -> None:
    # U4: a same-day Window read exactly like "When"; the row now shows only for a window that
    # ends on a later local day (core keeps windows on one display-zone date, so only a window
    # stored before a timezone change can do that).
    page, _ = open_page(browser, site, "/", "light", query=f"?view=week&date={DATE}")
    try:
        pid = post_id(page, "Planning day at Example Co")  # Tuesday, 10:00 to 11:00
    finally:
        page.context.close()
    page, problems = open_page(
        browser, site, "/", "light", query=f"?view=week&date={DATE}&post={pid}"
    )
    try:
        wait_drawn(page, "aside[data-post-panel] pre")
        when = page.locator("aside[data-post-panel] dt:text-is('When') + dd")
        assert re.fullmatch(r"Tue \d{1,2} [A-Z][a-z]{2}, 10:00 to 11:00", when.inner_text().strip())
        assert page.locator("aside[data-post-panel] dt:text-is('Window')").count() == 0
        assert not problems, problems
    finally:
        page.context.close()


def test_phone_day_headings_are_as_wide_as_the_cards(browser: Any, site: tuple[str, str]) -> None:
    # U4: at 390 px the sticky day heading stuck out 8 px on each side of the cards under it.
    page, problems = load(browser, site, "calendar-week", "light", PHONE)
    try:
        pairs = page.evaluate(
            "[...document.querySelectorAll('section[data-day]')].map(s => {"
            " const h = s.querySelector('h3'), c = s.querySelector('button[data-post-id]');"
            " if (!h || !c) return null;"
            " const a = h.getBoundingClientRect(), b = c.getBoundingClientRect();"
            " return [a.left, a.right, b.left, b.right] }).filter(Boolean)"
        )
        assert pairs, "no day with a card"
        for hl, hr, cl, cr in pairs:
            assert abs(hl - cl) <= 0.5 and abs(hr - cr) <= 0.5, (hl, hr, cl, cr)
        assert not problems, problems
    finally:
        page.context.close()

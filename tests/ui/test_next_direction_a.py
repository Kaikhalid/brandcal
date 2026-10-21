# ruff: noqa: F811, E501
# (the fixtures come from test_next_writes.py / test_next_home.py by name; E501 is for the
# JavaScript snippets that run inside the page)
"""Gates for direction A, "Quiet command bar (week stacks)": the week as seven time-ordered stacks
with no hour axis, a month whose rows size to their content, and the calendar high on the screen.
The foundation's gates (test_next_foundation.py) stay green underneath. Same demo home and fixtures.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import pytest
from axe_helper import axe_available

expect = pytest.importorskip("playwright.sync_api").expect
pytest.importorskip("cryptography")

from test_next_foundation import DESKTOP, WEEK_QUERY, collapse, week  # noqa: E402
from test_next_home import (  # noqa: E402, F401  (fixtures are used by name)
    PHONE,
    SCHEMES,
    axe_report,
    browser,
    new_page,
    open_page,
)
from test_next_views import LAPTOP, load, wait_drawn  # noqa: E402
from test_next_writes import dev_site, home, site  # noqa: E402, F401

pytestmark = pytest.mark.skipif(not axe_available(), reason="web/node_modules/axe-core is missing")

STACKS = "[aria-label='Week calendar'] [data-week-stacks] section[data-day]"

STACK_JS = """() => {
  const box = (el) => { const b = el.getBoundingClientRect(); return {x: b.x, y: b.y, w: b.width, h: b.height, b: b.bottom}; };
  const region = document.querySelector('[aria-label="Week calendar"]');
  const stacks = [...region.querySelectorAll('[data-week-stacks] section[data-day]')];
  const heads = [...region.querySelectorAll('[data-day-header]')];
  const cards = [...region.querySelectorAll('button[data-post-id]')].map((c) => ({
    id: c.dataset.postId, ...box(c), clipped: c.scrollHeight > c.clientHeight + 1 || c.scrollWidth > c.clientWidth + 1,
    time: c.querySelector('[data-card-time]')?.textContent, platform: !!c.querySelector('[data-platform]'),
    status: !!c.querySelector('[data-status]'), title: !!c.querySelector('[data-card-title]'),
    over: c.getBoundingClientRect().right > c.closest('section').getBoundingClientRect().right + 0.5,
  }));
  return {
    stacks: stacks.map(box), heads: heads.map((h) => ({...box(h), sticky: getComputedStyle(h).position})),
    cards, region: box(region), scroll: [region.scrollWidth, region.clientWidth], h: innerHeight,
    hourLabels: [...region.querySelectorAll('*')].filter((e) => !e.children.length && /^\\d\\d:00$/.test(e.textContent.trim()) && !e.closest('button')).length,
    emptyText: [...region.querySelectorAll('section[data-day]')].filter((s) => !s.querySelector('button[data-post-id]')).map((s) => s.textContent.includes('Nothing planned')),
  };
}"""


# -- the week as seven stacks ---------------------------------------------------------------


def test_the_week_is_seven_equal_stacks_with_sticky_headers_and_no_hour_axis(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        found = page.evaluate(STACK_JS)
        assert len(found["stacks"]) == 7 and len(found["heads"]) == 7, found["stacks"]
        widths = [s["w"] for s in found["stacks"]]
        assert max(widths) - min(widths) <= 1, widths
        assert min(widths) >= 140, widths  # 1440 open: about 150 px each
        assert {round(s["y"]) for s in found["stacks"]} == {round(found["stacks"][0]["y"])}
        assert all(h["sticky"] == "sticky" for h in found["heads"]), found["heads"]
        assert found["hourLabels"] == 0, "an hour axis is still drawn"
        assert page.locator(".hour-grid").count() == 0
        assert found["scroll"][0] <= found["scroll"][1], found["scroll"]
        # A header is a weekday and a date; the week has Monday first.
        names = page.locator("[data-day-header] [data-weekday]").all_inner_texts()
        assert names == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], names
    finally:
        page.context.close()


def test_today_is_marked_by_a_numeral_a_word_a_tint_and_the_current_date(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = new_page(browser, site, "light", DESKTOP)
    page.clock.install(time=dt.datetime.fromisoformat("2026-03-10T10:30:00+01:00"))
    try:
        page.goto(f"{site[0]}/{WEEK_QUERY}")
        wait_drawn(page, "[data-post-id]")
        head = page.locator("[data-day-header='2026-03-10']")
        assert "Today" in head.inner_text() and head.locator(".bg-pill").count() == 1
        section = page.locator("section[data-day='2026-03-10']")
        assert section.get_attribute("aria-current") == "date"
        assert page.locator("section[aria-current=date]").count() == 1
        # Today's header and stack share one tint, apart from the other days.
        tones = page.evaluate(
            "() => ['2026-03-10', '2026-03-11'].map((d) => [document.querySelector(`[data-day-header=\"${d}\"]`), document.querySelector(`section[data-day=\"${d}\"]`)]"
            ".map((e) => getComputedStyle(e).backgroundColor))"
        )
        assert tones[0][0] == tones[0][1] and tones[1][0] == tones[1][1], tones
        assert tones[0][0] != tones[1][0], tones
    finally:
        page.context.close()


@pytest.mark.parametrize("size", [DESKTOP, LAPTOP], ids=["1440x900", "1024x768"])
def test_every_card_prints_time_platform_title_and_status_and_fits_its_stack(
    browser: Any, site: tuple[str, str], size: dict[str, int]
) -> None:
    page = week(browser, site, size=size)
    try:
        found = page.evaluate(STACK_JS)
        assert len(found["stacks"]) == 7, found["stacks"]
        cards = found["cards"]
        assert len(cards) >= 8, cards
        for card in cards:
            assert re.fullmatch(r"\d\d:\d\d", card["time"] or ""), card
            assert card["platform"] and card["status"] and card["title"], card
            assert not card["clipped"] and not card["over"], card
            assert 72 <= card["h"] <= 190, card  # about 96 px a card, more where the words wrap
        # Nothing inside a card reaches past it (a chip or a long word used to spill at 1024).
        spill = page.evaluate(
            "() => [...document.querySelectorAll('[data-week-stacks] button[data-post-id] *')].filter((e) => {"
            " const c = e.closest('button').getBoundingClientRect(), b = e.getBoundingClientRect();"
            " return b.width > 0 && (b.right > c.right + 0.5 || b.left < c.left - 0.5); })"
            ".map((e) => e.textContent.trim().slice(0, 30))"
        )
        assert spill == [], spill
    finally:
        page.context.close()


def test_a_day_without_posts_says_so_quietly(browser: Any, site: tuple[str, str]) -> None:
    page = week(browser, site)
    try:
        empty = page.evaluate(STACK_JS)["emptyText"]
        assert empty, "the demo week should have a quiet day"
        assert all(empty), empty
    finally:
        page.context.close()


@pytest.mark.parametrize(
    ("size", "card_limit", "head_limit"),
    [(DESKTOP, 0.17, 0.14), (LAPTOP, 0.20, 0.14)],
    ids=["1440x900", "1024x768"],
)
def test_the_first_card_and_the_day_headers_start_high(
    browser: Any, site: tuple[str, str], size: dict[str, int], card_limit: float, head_limit: float
) -> None:
    page = week(browser, site, size=size)
    try:
        found = page.evaluate(STACK_JS)
        height = found["h"]
        assert found["heads"][0]["y"] / height <= head_limit, found["heads"][0]
        first = min(c["y"] for c in found["cards"])
        assert first / height <= card_limit, (first, height)
        # The whole week is in view without a sideways scroll, and every stack reaches the foot.
        assert found["scroll"][0] <= found["scroll"][1]
        assert all(s["b"] >= found["region"]["b"] - 12 for s in found["stacks"]), found["stacks"]
    finally:
        page.context.close()


def test_the_rail_widens_the_columns(browser: Any, site: tuple[str, str]) -> None:
    page = week(browser, site)
    try:
        open_width = page.evaluate(STACK_JS)["stacks"][0]["w"]
        collapse(page)
        page.wait_for_timeout(200)
        found = page.evaluate(STACK_JS)
        assert len(found["stacks"]) == 7
        assert found["stacks"][0]["w"] >= open_width + 20, (open_width, found["stacks"][0])
        assert found["stacks"][0]["w"] >= 170, found["stacks"][0]
        assert page.evaluate("document.documentElement.scrollHeight <= innerHeight")
    finally:
        page.context.close()


def test_a_card_opens_the_panel_and_the_week_keeps_its_stacks_only_when_there_is_room(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        page.locator(f"{STACKS} button[data-post-id]").first.click()
        page.locator("aside[data-post-panel]").wait_for(timeout=5_000)
        page.wait_for_timeout(300)
        # (the sidebar is open here: the box is about 656 px, under the stacks threshold)
        assert page.locator("[data-week-stacks]").count() == 0, "bands expected beside the panel"
        current = page.locator("button[aria-current=true][data-post-id]")
        expect(current).to_have_count(1)
    finally:
        page.context.close()


def test_the_week_keeps_seven_stacks_beside_the_panel_with_the_sidebar_collapsed(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        collapse(page)
        page.locator(f"{STACKS} button[data-post-id]").first.click()
        page.locator("aside[data-post-panel]").wait_for(timeout=5_000)
        page.wait_for_timeout(450)
        found = page.evaluate(STACK_JS)
        assert len(found["stacks"]) == 7, (
            "stacks expected beside the panel when the rail is collapsed"
        )
        assert min(s["w"] for s in found["stacks"]) >= 110, [s["w"] for s in found["stacks"]]
        assert found["scroll"][0] <= found["scroll"][1], found["scroll"]
        assert not any(c["over"] for c in found["cards"]), "a card passes its well"
        assert not any(c["clipped"] for c in found["cards"]), "a card clips its content"
        chips = page.evaluate(CARD_JS)  # the narrowest wells (about 100 px of card): still one line
        assert all(c["chipH"] < 36 for c in chips if len(c["label"]) <= 14), chips
        current = page.locator("button[aria-current=true][data-post-id]")
        expect(current).to_have_count(1)
    finally:
        page.context.close()


# -- card detail by well width (R-A 3, 4, 5) -------------------------------------------------

CARD_JS = """() => [...document.querySelectorAll('[aria-label="Week calendar"] button[data-post-id]')].map((c) => {
  const vis = (el) => !!el && getComputedStyle(el).display !== 'none' && el.getBoundingClientRect().width > 0;
  const chip = c.querySelector('[data-status]');
  const icon = chip.querySelector('svg');
  const end = c.querySelector('[data-card-end]');
  return { w: c.getBoundingClientRect().width, chipH: chip.getBoundingClientRect().height, icon: vis(icon), label: chip.textContent,
    end: vis(end) ? end.textContent.trim() : null, time: c.querySelector('[data-card-time]').textContent,
    hyphens: getComputedStyle(c.querySelector('[data-card-title]')).hyphens,
    badges: [...c.querySelectorAll('[data-badge]')].map((b) => ({ id: b.dataset.badge, visible: b.innerText.trim() })) };
})"""


def test_a_wide_card_prints_its_window_and_names_its_badges(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        cards = page.evaluate(CARD_JS)
        assert cards and all(c["w"] >= 128 for c in cards), [c["w"] for c in cards]
        for c in cards:
            assert re.fullmatch(r"–\d\d:\d\d", c["end"] or ""), c
            assert c["time"] and "–" not in c["time"], c  # the start time stays on its own
            assert c["hyphens"] == "manual", c  # no automatic hyphenation
        badges = [b for c in cards for b in c["badges"]]
        assert badges, "the demo week has a card with a badge"
        assert all(b["visible"] for b in badges), badges  # never an icon alone at this width
    finally:
        page.context.close()


def test_a_narrow_card_keeps_one_line_chips_and_no_window(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site, size=LAPTOP)  # 1024: the rail collapses by itself
    try:
        cards = page.evaluate(CARD_JS)
        assert cards and all(c["w"] < 128 for c in cards), [c["w"] for c in cards]
        for c in cards:
            assert c["end"] is None, c  # "09:00" alone below 8 rem
            assert not c["icon"], c  # the chip keeps its word and drops its icon
            if len(c["label"]) <= 14:  # one line ("Awaiting you" no longer wraps); a long label may
                assert c["chipH"] < 36, c
            assert c["hyphens"] == "manual", c
    finally:
        page.context.close()


# -- the month ------------------------------------------------------------------------------

MONTH_JS = """() => {
  const region = document.querySelector('[aria-label="Month calendar"]');
  const cells = [...region.querySelectorAll('[role=group][data-day]')];
  const rows = new Map();
  for (const c of cells) { const b = c.getBoundingClientRect(); const k = Math.round(b.top); const p = rows.get(k) || {h: 0, posts: 0}; rows.set(k, {h: Math.max(p.h, b.height), posts: p.posts + c.querySelectorAll('button[data-post-id]').length}); }
  const titles = [...region.querySelectorAll('[data-card-title]')].map((t) => ({ text: t.textContent, wraps: t.scrollHeight > t.clientHeight + 1, cut: t.scrollWidth > t.clientWidth + 1, truncated: getComputedStyle(t).textOverflow === 'ellipsis' }));
  return { rows: [...rows.values()], titles, scroll: [region.scrollWidth, region.clientWidth], page: document.documentElement.scrollWidth, w: innerWidth,
    stacks: document.querySelectorAll('[data-week-stacks]').length };
}"""


def test_month_rows_size_to_content_and_titles_wrap_instead_of_truncating(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = load(browser, site, "calendar-month", "light", DESKTOP)
    try:
        found = page.evaluate(MONTH_JS)
        rows = found["rows"]
        assert len(rows) >= 5, rows
        empty = [r["h"] for r in rows if r["posts"] == 0]
        busy = [r["h"] for r in rows if r["posts"] > 0]
        assert empty and busy, rows
        assert max(empty) <= 100, empty  # an empty week is a quiet row, not 128
        assert min(empty) <= 70, empty  # an empty week that is not selected is 64 px (R-A 6)
        assert rows[0]["h"] > 0, rows  # the first row stays on screen
        assert max(busy) > max(empty), rows  # a busy week is taller
        assert found["titles"], "no cards in the month"
        assert not any(t["truncated"] for t in found["titles"]), found["titles"]
        assert not any(t["cut"] for t in found["titles"]), found["titles"]
        assert found["scroll"][0] <= found["scroll"][1] and found["page"] <= found["w"], found
    finally:
        page.context.close()


def test_the_month_uses_bands_below_880_px_and_never_scrolls_sideways(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = load(browser, site, "calendar-month", "light", PHONE)
    try:
        found = page.evaluate(MONTH_JS)
        assert found["page"] <= found["w"], found
        assert found["scroll"][0] <= found["scroll"][1], found
    finally:
        page.context.close()


# -- axe, both themes -----------------------------------------------------------------------


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("view", ["calendar-week", "calendar-month"])
def test_axe_finds_nothing_on_the_stacks_and_the_month_rows(
    browser: Any, site: tuple[str, str], view: str, scheme: str
) -> None:
    page, _ = load(browser, site, view, scheme, DESKTOP)
    try:
        page.wait_for_timeout(300)
        axe_report(page, f"direction-a-{view}-{scheme}")
    finally:
        page.context.close()


@pytest.mark.parametrize("scheme", SCHEMES)
def test_axe_finds_nothing_on_the_stacks_with_the_rail_collapsed(
    browser: Any, site: tuple[str, str], scheme: str
) -> None:
    page = week(browser, site, scheme)
    try:
        collapse(page)
        axe_report(page, f"direction-a-rail-{scheme}")
    finally:
        page.context.close()


def test_the_stacks_reflow_at_320_without_sideways_scroll(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = open_page(
        browser, site, "/", "light", size={"width": 320, "height": 640}, query=WEEK_QUERY
    )
    try:
        wait_drawn(page, "[data-post-id]")
        assert page.evaluate("document.documentElement.scrollWidth") <= 320
        assert page.locator("[data-week-stacks]").count() == 0
    finally:
        page.context.close()

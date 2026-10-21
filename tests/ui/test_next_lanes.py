# ruff: noqa: F811, E501
# (the fixtures come from test_next_writes.py / test_next_home.py by name; E501 is for the
# JavaScript snippets that run inside the page)
"""Gates for direction C, "Channel lanes": the week is a row per platform and a column per day,
the whole week is visible without scrolling, the lane label is the channel filter, and the month
and narrow widths fall back to a content-sized grid and a day list. Built on the shared
foundation, whose gates (test_next_foundation.py) stay green.
"""

from __future__ import annotations

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
    open_page,
)
from test_next_views import LAPTOP, wait_drawn  # noqa: E402
from test_next_writes import dev_site, home, new_post, site  # noqa: E402, F401

pytestmark = pytest.mark.skipif(not axe_available(), reason="web/node_modules/axe-core is missing")

LANES_JS = """() => {
  const grid = document.querySelector('[data-lane-grid]');
  const rows = [...grid.querySelectorAll('[role=row][data-lane]')];
  const head = grid.querySelector('[role=columnheader][data-day]').getBoundingClientRect();
  const box = grid.getBoundingClientRect();
  const last = rows[rows.length - 1].getBoundingClientRect();
  const days = [...grid.querySelectorAll('[role=columnheader][data-day]')].map((d) => d.getBoundingClientRect().width);
  return { lanes: rows.length, days: days.length, dayWidth: days[0], top: box.top / innerHeight, header: head.top / innerHeight,
    bottom: last.bottom, innerHeight, scrolls: grid.scrollHeight > grid.clientHeight + 1, sideways: grid.scrollWidth > grid.clientWidth + 1,
    pageScrolls: document.documentElement.scrollHeight > innerHeight, pageSideways: document.documentElement.scrollWidth > innerWidth };
}"""


@pytest.mark.parametrize(
    ("size", "fits"), [(DESKTOP, True), (LAPTOP, False)], ids=["1440x900", "1024x768"]
)
def test_the_week_has_a_lane_per_platform_and_at_1440_the_whole_week_needs_no_scrolling(
    browser: Any, site: tuple[str, str], size: dict[str, int], fits: bool
) -> None:
    page = week(browser, site, size=size)
    try:
        found = page.evaluate(LANES_JS)
        assert found["days"] == 7 and found["lanes"] >= 5, found
        assert found["top"] <= 0.14, found  # the grid starts high (the foundation's budget)
        if fits:  # at 1024 x 768 the lanes may scroll inside their own region (the page never does)
            assert found["bottom"] <= found["innerHeight"], found  # every lane is on screen
            assert not found["scrolls"], found
        assert not found["sideways"], found
        assert not found["pageScrolls"] and not found["pageSideways"], found
        assert found["dayWidth"] >= 100, found  # narrow, but readable
        for lane in page.locator("[role=row][data-lane]").all():
            assert lane.locator("[data-lane-toggle]").count() == 1
    finally:
        page.context.close()


def test_lane_labels_are_toggle_buttons_in_the_tab_order_and_work_from_the_keyboard(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        label = page.locator('[data-lane-toggle="linkedin"]')
        # The name starts with the visible label's words (WCAG 2.5.3) and says what the press does.
        named = page.get_by_role("button", name=re.compile(r"^Show only LinkedIn \d+ posts?$"))
        expect(named).to_have_count(1)
        label.focus()
        page.keyboard.press("Enter")
        page.wait_for_url(re.compile("platform=linkedin"))
        expect(label).to_have_attribute("aria-pressed", "true")
        # The channel half is gone from the popover (the lanes are it); Status and the rest stay.
        page.locator("[data-filters-toggle]").click()
        popup = page.locator("[data-slot=popover-content][data-open]")
        popup.wait_for(timeout=5_000)
        assert popup.get_by_text("Platform", exact=True).count() == 0
        assert popup.locator('[data-filter="status:pending_approval"]').count() == 1
        # The Filters button does not count the channel: the lane chip does.
        expect(page.locator("[data-filters-toggle]")).not_to_contain_text("(")
    finally:
        page.context.close()


def test_a_gap_in_a_lane_is_a_quiet_dash_and_a_post_is_a_card_in_its_cell(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        cells = page.locator("[data-lane] [role=cell][data-day]")
        assert cells.count() >= 5 * 7
        empty = cells.filter(has_not=page.locator("button[data-post-id]"))
        assert empty.count() >= 1
        assert empty.first.locator("[aria-hidden=true]").count() == 1
        filled = cells.filter(has=page.locator("button[data-post-id]"))
        assert filled.count() >= 1
        # A card prints time, title and the status word (icon and word, never colour alone).
        card = filled.first.locator("button[data-post-id]").first
        assert re.search(r"\d\d:\d\d", card.inner_text())
        assert card.locator("[data-status]").count() == 1
    finally:
        page.context.close()


def test_more_than_two_posts_in_a_cell_fold_into_a_plus_n_more_list(
    browser: Any, site: tuple[str, str], home: Any
) -> None:
    ids = [new_post(home, f"lane-more-{n}", f"Lane crowd {n}") for n in range(1, 4)]
    page, problems = open_page(
        browser, site, "/", "light", size=DESKTOP, query="?view=week&date=2027-03-01"
    )
    try:
        wait_drawn(page, "[data-lane-grid] [data-post-id]")
        cell = page.locator('[data-lane="linkedin"] [role=cell][data-day="2027-03-02"]')
        assert cell.locator("> button[data-post-id]").count() == 2
        more = cell.locator("[data-more-cell]")
        expect(more).to_have_text(re.compile(r"\+1 more"))
        assert 24 <= more.bounding_box()["height"] <= 48  # type: ignore[index]  # target size
        more.focus()
        page.keyboard.press("Enter")
        popup = page.locator("[data-slot=popover-content][data-open]")
        popup.wait_for(timeout=5_000)
        listed = popup.locator("button[data-post-id]")
        assert listed.count() == 1
        assert listed.get_attribute("data-post-id") in ids
        axe_report(page, "next-lanes-more")
        page.keyboard.press("Escape")
        popup.wait_for(state="detached", timeout=5_000)
        expect(more).to_be_focused()
        more.click()
        popup.wait_for(timeout=5_000)
        listed.click()
        page.wait_for_url(re.compile("post=p"))
        page.locator("aside[data-post-panel]").wait_for(timeout=10_000)
        assert not problems, problems
    finally:
        page.context.close()


def test_the_collapsed_sidebar_gives_the_lanes_more_room_and_nothing_overflows(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        open_width = page.evaluate(LANES_JS)["dayWidth"]
        collapse(page)
        found = page.evaluate(LANES_JS)
        assert found["dayWidth"] > open_width + 10, (open_width, found)
        assert found["bottom"] <= found["innerHeight"] and not found["pageSideways"], found
        # Still reachable: a lane label takes keyboard focus beside the rail.
        page.locator('[data-lane-toggle="linkedin"]').focus()
        assert page.evaluate("document.activeElement.dataset.laneToggle") == "linkedin"
    finally:
        page.context.close()


def test_below_880_px_of_calendar_the_week_is_a_day_list_with_the_channel_on_each_card(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = open_page(browser, site, "/", "light", size=PHONE, query=WEEK_QUERY)
    try:
        wait_drawn(page, "[data-post-id]")
        assert page.locator("[data-lane-grid]").count() == 0
        first = page.locator("button[data-post-id]").first
        assert first.locator("[data-platform]").inner_text().strip() != ""
        # With no lanes the popover keeps the channel half.
        page.locator("[data-filters-toggle]").click()
        page.locator("[data-slot=popover-content][data-open]").wait_for(timeout=5_000)
        assert page.locator('[data-filter="platform:linkedin"]').count() == 1
    finally:
        page.context.close()


def test_the_month_is_a_content_sized_grid_whose_weeks_grow_with_their_posts(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = open_page(
        browser, site, "/", "light", size=DESKTOP, query=WEEK_QUERY.replace("week", "month")
    )
    try:
        wait_drawn(page, "[data-post-id]")
        assert page.locator("[data-lane-grid]").count() == 0
        found = page.evaluate(
            "() => { const r = document.querySelector('[aria-label=\"Month calendar\"]');"
            " const cells = [...r.querySelectorAll('[role=group][data-day]')].map((c) => c.getBoundingClientRect().height);"
            " return { sideways: r.scrollWidth > r.clientWidth + 1, min: Math.min(...cells), max: Math.max(...cells), n: cells.length }; }"
        )
        assert not found["sideways"], found
        assert found["min"] < 130 <= found["max"] or found["max"] > found["min"], found
        assert found["n"] % 7 == 0, found
    finally:
        page.context.close()


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("soloed", [False, True], ids=["all", "solo"])
def test_the_lanes_pass_axe_in_both_themes(
    browser: Any, site: tuple[str, str], scheme: str, soloed: bool
) -> None:
    query = WEEK_QUERY + ("&platform=linkedin" if soloed else "")
    page, problems = open_page(browser, site, "/", scheme, size=DESKTOP, query=query)
    try:
        wait_drawn(page, "[data-lane-grid] [data-post-id]")
        page.wait_for_timeout(300)
        axe_report(page, f"next-lanes-{scheme}-{'solo' if soloed else 'all'}")
        assert page.evaluate("window.__csp") == []
        assert not problems, problems
    finally:
        page.context.close()


@pytest.mark.parametrize("scheme", SCHEMES)
def test_the_lanes_pass_axe_with_the_rail_collapsed(
    browser: Any, site: tuple[str, str], scheme: str
) -> None:
    page = week(browser, site, scheme)
    try:
        collapse(page)
        axe_report(page, f"next-lanes-rail-{scheme}")
    finally:
        page.context.close()

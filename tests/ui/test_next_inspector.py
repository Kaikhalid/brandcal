# ruff: noqa: F811, E501
# (the fixtures come from test_next_writes.py / test_next_home.py by name; E501 is for the
# JavaScript snippets that run inside the page)
"""Gates for direction B, the inspector rail: day bands on the calendar and a permanent right-hand
rail that is the Needs you queue, becomes the post detail with its actions on top, and moves on to
the next item after a decision. Same demo home and fixtures as test_next_foundation.py.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from axe_helper import axe_available

expect = pytest.importorskip("playwright.sync_api").expect
pytest.importorskip("cryptography")

from test_next_foundation import DESKTOP, collapse, week  # noqa: E402
from test_next_home import (  # noqa: E402, F401  (fixtures are used by name)
    PHONE,
    SCHEMES,
    axe_report,
    browser,
    open_page,
)
from test_next_views import LAPTOP, post_id, wait_drawn  # noqa: E402
from test_next_writes import (  # noqa: E402, F401
    DATE,
    api,
    confirm,
    dev_site,
    done,
    home,
    open_dialog,
    site,
)

pytestmark = pytest.mark.skipif(not axe_available(), reason="web/node_modules/axe-core is missing")

RAIL = "[data-inspector-rail]"
BANDS = "[aria-label='Week calendar'] > section[data-day]"


def rail_ready(page: Any) -> None:
    page.locator(f"{RAIL} [data-queue-row]").first.wait_for(timeout=10_000)


def row(page: Any, title: str) -> Any:
    return page.locator("[data-queue-row]", has_text=title)


# -- the queue and the bands -----------------------------------------------------------------


def test_the_rail_is_the_needs_you_queue_most_urgent_first(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        rail_ready(page)
        rail = page.locator(RAIL)
        assert rail.get_attribute("data-inspector-rail") == "queue"
        box = rail.bounding_box()
        assert box and 410 <= box["width"] <= 420, box  # 26 rem at 1440 px
        assert rail.locator("h2").inner_text().startswith("Needs you")
        order = page.evaluate(
            f'() => [...document.querySelectorAll("{RAIL} section[data-status]")].map((s) => s.dataset.status)'
        )
        rank = ["missed", "changes_requested", "pending_approval"]
        assert order == sorted(order, key=lambda s: rank.index(s) if s in rank else 9), order
        total = int(re.sub(r"\D", "", rail.locator("[data-queue-count]").inner_text()))
        assert total == rail.locator("[data-queue-row]").count() > 0
        # The chip in the bar is gone (the rail is it) and the sidebar badge agrees with the rail.
        assert page.locator("header [data-needs-you-chip]").count() == 0
        assert page.locator("header [data-rail-button]").count() == 0
    finally:
        page.context.close()


@pytest.mark.parametrize("size", [DESKTOP, LAPTOP], ids=["1440x900", "1024x768"])
def test_the_week_is_seven_day_bands_and_the_first_band_is_fully_in_view(
    browser: Any, site: tuple[str, str], size: dict[str, int]
) -> None:
    page = week(browser, site, size=size)
    try:
        assert page.locator(BANDS).count() == 7
        found = page.evaluate(
            """() => {
              const grid = document.querySelector('[aria-label="Week calendar"]');
              const first = grid.querySelector('section[data-day]').getBoundingClientRect();
              return { top: grid.getBoundingClientRect().top / innerHeight, firstBottom: first.bottom, height: innerHeight,
                       wide: grid.scrollWidth <= grid.clientWidth, page: document.documentElement.scrollWidth <= innerWidth };
            }"""
        )
        assert found["top"] <= 0.14, found
        assert found["firstBottom"] <= found["height"], found
        assert found["wide"] and found["page"], found
        # Empty days are a quiet line, not a tall well.
        quiet = page.locator(BANDS, has_text="Nothing planned.").first
        if quiet.count():
            box = quiet.bounding_box()
            assert box and box["height"] <= 64, box
    finally:
        page.context.close()


def test_a_queue_row_turns_the_rail_into_the_post_with_its_actions_in_view(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        rail_ready(page)
        row(page, "How we plan a launch").first.click()
        detail = page.locator(f"{RAIL}[data-post-panel]")
        detail.wait_for(timeout=10_000)
        assert detail.get_attribute("data-inspector-rail") == "detail"
        pid = post_id(page, "How we plan a launch")
        assert f"post={pid}" in page.url
        back = detail.locator("[data-rail-back]")
        expect(back).to_have_accessible_name(re.compile(r"^Back to Needs you \d+ waiting$"))
        page.locator("[data-panel-actions] button").first.wait_for(timeout=10_000)
        found = page.evaluate(
            "() => { const b = document.querySelector('[data-panel-actions]').getBoundingClientRect();"
            " return { top: b.top, bottom: b.bottom, height: innerHeight }; }"
        )
        assert found["top"] >= 0 and found["bottom"] <= found["height"], found
        # The calendar card of the same post is the selected one (ink outline via aria-current).
        card = page.locator(f"[aria-label='Week calendar'] button[data-post-id='{pid}']")
        expect(card).to_have_attribute("aria-current", "true")
        # Back returns to the queue and puts focus on the row that was open.
        back.click()
        rail_ready(page)
        assert "post=" not in page.url
        assert page.locator(RAIL).get_attribute("data-inspector-rail") == "queue"
        expect(row(page, "How we plan a launch").first).to_be_focused()
    finally:
        page.context.close()


def test_j_and_k_walk_the_queue_and_typing_is_left_alone(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        rail_ready(page)
        rows = page.locator("[data-queue-row]")
        assert rows.count() >= 2
        page.locator("main").focus()
        page.keyboard.press("j")
        expect(rows.nth(0)).to_be_focused()
        page.keyboard.press("j")
        expect(rows.nth(1)).to_be_focused()
        page.keyboard.press("k")
        expect(rows.nth(0)).to_be_focused()
        page.keyboard.press("Enter")
        page.locator(f"{RAIL}[data-post-panel]").wait_for(timeout=10_000)
        # A search box swallows the keys.
        page.locator("[data-rail-back]").click()
        page.locator("[data-filters-toggle]").click()
        search = page.locator(
            "[data-slot=popover-content] input[type=search], [data-slot=popover-content] input[type=text]"
        ).first
        if search.count():
            search.focus()
            page.keyboard.press("j")
            expect(search).to_be_focused()
    finally:
        page.context.close()


def test_a_decision_moves_the_rail_on_to_the_next_item(browser: Any, site: tuple[str, str]) -> None:
    page = week(browser, site)
    try:
        rail_ready(page)
        before = page.locator("[data-queue-row]").count()
        assert before > 1
        titles = [
            t.split("\n")[-1].strip() for t in page.locator("[data-queue-row]").all_inner_texts()
        ]
        index = titles.index("How we plan a launch")
        # The next row of the queue, or the one before when it was the last.
        expected = titles[index + 1] if index + 1 < len(titles) else titles[index - 1]
        row(page, "How we plan a launch").first.click()
        page.locator(f"{RAIL}[data-post-panel]").wait_for(timeout=10_000)
        page.locator("[data-panel-actions] [data-action-button='approve']").wait_for(timeout=10_000)
        dialog = open_dialog(page, "approve")
        confirm(dialog)
        done(page, dialog, "Approve: done. How we plan a launch is now Approved")
        # The panel now shows another post of the queue (or the queue itself when it was the last).
        expect(page.locator("#panel-title")).to_have_text(expected)
        expect(page.locator("#panel-title")).to_be_focused()
        assert page.locator(RAIL).get_attribute("data-inspector-rail") == "detail"
        decided = post_id(page, "How we plan a launch")
        assert api(site, f"/api/posts/{decided}")["status"] == "approved"
    finally:
        page.context.close()


# -- below 1180 px the rail is a sheet ---------------------------------------------------------


def test_below_1180_the_toolbar_button_opens_the_queue_as_a_sheet(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site, size=LAPTOP)
    try:
        assert page.locator(RAIL).count() == 0
        button = page.locator("header [data-rail-button]")
        assert button.count() == 1
        assert re.search(r"Needs you", button.inner_text())
        button.click()
        sheet = page.locator(f"{RAIL}[data-inspector-rail='queue']")
        sheet.wait_for(timeout=5_000)
        expect(page.locator("#rail-title")).to_be_focused()
        assert page.evaluate("document.getElementById('shell-body').inert === true")
        axe_report(page, "inspector-sheet-1024")
        page.keyboard.press("Escape")
        expect(sheet).to_have_count(0)
        expect(button).to_be_focused()
        assert page.evaluate("document.getElementById('shell-body').inert === false")
    finally:
        page.context.close()


def test_the_phone_keeps_the_day_list_with_a_sticky_heading_and_the_sheet_button(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site, size=PHONE)
    try:
        assert page.locator(RAIL).count() == 0
        assert page.locator("header [data-rail-button]").count() == 1
        heading = page.locator(f"{BANDS} h3").first
        position = heading.evaluate("el => getComputedStyle(el).position")
        assert position == "sticky", position
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        first = page.evaluate(
            "document.querySelector('[aria-label=\"Week calendar\"] h3').getBoundingClientRect().top / innerHeight"
        )
        assert first <= 0.2, first
    finally:
        page.context.close()


# -- the collapsed sidebar with the rail --------------------------------------------------------


@pytest.mark.parametrize("scheme", SCHEMES)
def test_with_the_sidebar_collapsed_the_rail_and_the_bands_fit_the_screen(
    browser: Any, site: tuple[str, str], scheme: str
) -> None:
    page = week(browser, site, scheme)
    try:
        rail_ready(page)
        collapse(page)
        found = page.evaluate(
            """() => {
              const r = document.querySelector('[data-inspector-rail]').getBoundingClientRect();
              const g = document.querySelector('[aria-label="Week calendar"]');
              return { railRight: r.right, railWidth: r.width, view: innerWidth, grid: g.getBoundingClientRect().width,
                       overflow: document.documentElement.scrollWidth - innerWidth, bands: g.scrollWidth <= g.clientWidth };
            }"""
        )
        assert abs(found["railRight"] - found["view"]) <= 1, found
        assert 410 <= found["railWidth"] <= 420, found
        assert found["overflow"] <= 0 and found["bands"], found
        assert found["grid"] > 800, found  # the freed sidebar width goes to the calendar
    finally:
        page.context.close()


# -- axe, both themes ----------------------------------------------------------------------------


@pytest.mark.parametrize("scheme", SCHEMES)
def test_axe_clean_for_the_queue_and_the_detail_state(
    browser: Any, site: tuple[str, str], scheme: str
) -> None:
    page = week(browser, site, scheme)
    try:
        rail_ready(page)
        axe_report(page, f"inspector-queue-{scheme}")
        page.locator("[data-queue-row]").first.click()  # the decision test above approved one post
        page.locator(f"{RAIL}[data-post-panel] [data-action-button]").first.wait_for(timeout=10_000)
        axe_report(page, f"inspector-detail-{scheme}")
        page.locator("[data-rail-back]").click()
        collapse(page)
        axe_report(page, f"inspector-collapsed-{scheme}")
    finally:
        page.context.close()


@pytest.mark.parametrize("scheme", SCHEMES)
def test_axe_clean_for_the_month(browser: Any, site: tuple[str, str], scheme: str) -> None:
    page, _ = open_page(browser, site, "/", scheme, size=DESKTOP, query=f"?view=month&date={DATE}")
    try:
        wait_drawn(page, "[data-post-id]")
        collapse(page)  # 1376 px of content: the month grid
        assert page.locator("[aria-label='Month calendar'] [role=group]").count() >= 28
        axe_report(page, f"inspector-month-{scheme}")
    finally:
        page.context.close()

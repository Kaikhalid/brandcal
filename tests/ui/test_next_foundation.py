# ruff: noqa: F811, E501
# (the fixtures come from test_next_writes.py / test_next_home.py by name; E501 is for the
# JavaScript snippets that run inside the page)
"""Gates for the shared UI foundation (S1): the collapsed rail, one top bar, a calendar that
starts high on the screen, the Filters popover and strip, the Needs you chip, the panel's pinned
actions and the container-width switch. Same demo home and fixtures as test_next_a11y.py. Each
direction (A, B, C) is built on this layer and keeps these gates green.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from axe_helper import axe_available

expect = pytest.importorskip("playwright.sync_api").expect
pytest.importorskip("cryptography")

from test_next_a11y import PANEL, open_panel  # noqa: E402
from test_next_home import (  # noqa: E402, F401  (fixtures are used by name)
    PHONE,
    SCHEMES,
    axe_report,
    browser,
    open_page,
)
from test_next_views import LAPTOP, load, wait_drawn  # noqa: E402
from test_next_writes import DATE, dev_site, home, site  # noqa: E402, F401

pytestmark = pytest.mark.skipif(not axe_available(), reason="web/node_modules/axe-core is missing")

DESKTOP = {"width": 1440, "height": 900}
WEEK_QUERY = f"?view=week&date={DATE}"
RAIL_LABELS = ("Calendar", "Needs you", "Posts", "Channels", "Activity", "Settings")


def week(
    browser: Any, site: tuple[str, str], scheme: str = "light", size: dict[str, int] | None = None
) -> Any:
    page, _ = open_page(browser, site, "/", scheme, size=size or DESKTOP, query=WEEK_QUERY)
    wait_drawn(page, "[data-post-id]")
    return page


def collapse(page: Any) -> None:
    page.keyboard.press("[")
    page.wait_for_selector("[data-slot='sidebar'][data-state='collapsed']")
    page.mouse.move(700, 450)
    page.wait_for_timeout(450)  # the rail animates its width (300 ms)


# -- the collapsed rail ----------------------------------------------------------------------

RAIL_JS = """() => {
  const box = (el) => { const b = el.getBoundingClientRect(); return {l: b.left, t: b.top, r: b.right, b: b.bottom, w: b.width}; };
  const container = document.querySelector("[data-slot='sidebar-container']");
  const rail = box(container);
  const links = [...document.querySelectorAll("nav[aria-label=Primary] a")].map((a) => {
    const link = box(a), icon = box(a.querySelector('svg')), label = box(a.querySelector(':scope > span'));
    return { text: a.textContent.trim(), name: a.getAttribute('aria-label'), link, icon, labelWidth: label.w };
  });
  const footer = [...document.querySelectorAll("[data-sidebar='footer'] button")]
    .filter((b) => b.getClientRects().length).map((b) => ({ name: b.getAttribute('aria-label'), ...box(b) }));
  return { rail, links, footer, scrollWidth: container.scrollWidth, clientWidth: container.clientWidth,
    inner: (() => { const i = document.querySelector("[data-slot='sidebar-inner']"); return [i.scrollWidth, i.clientWidth]; })() };
}"""


@pytest.mark.parametrize("scheme", SCHEMES)
def test_the_collapsed_rail_keeps_every_icon_inside_its_link_and_hides_the_label(
    browser: Any, site: tuple[str, str], scheme: str
) -> None:
    page = week(browser, site, scheme)
    try:
        collapse(page)
        found = page.evaluate(RAIL_JS)
        assert 63 <= found["rail"]["w"] <= 65, found["rail"]
        assert len(found["links"]) == len(RAIL_LABELS)
        for link, label in zip(found["links"], RAIL_LABELS, strict=True):
            a, i = link["link"], link["icon"]
            assert a["w"] >= 40 and a["l"] >= 0 and a["r"] <= found["rail"]["r"] + 0.5, link
            # The icon lies inside its link (it used to sit at x -2 to -18, off screen).
            assert i["l"] >= a["l"] - 0.5 and i["r"] <= a["r"] + 0.5, link
            assert i["t"] >= a["t"] - 0.5 and i["b"] <= a["b"] + 0.5, link
            # The label is visually hidden, not removed: one pixel at most.
            assert link["labelWidth"] <= 1, link
            assert link["text"].startswith(label), link
        assert found["scrollWidth"] <= found["clientWidth"], found
        assert found["inner"][0] <= found["inner"][1], found
        # Footer controls (avatar, theme menu) are whole and inside the rail.
        assert len(found["footer"]) >= 2, found["footer"]
        for control in found["footer"]:
            assert control["l"] >= 0 and control["r"] <= found["rail"]["r"] + 0.5, control
        # The accessible name is still the label, plus the count when there is one.
        nav = page.get_by_role("navigation", name="Primary")
        for label in RAIL_LABELS:
            link = nav.get_by_role("link", name=re.compile(f"^{label}( \\d+ waiting)?$"))
            assert link.count() == 1, label
    finally:
        page.context.close()


def test_the_rail_shows_the_waiting_count_as_a_dot_and_tooltips_the_name(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        collapse(page)
        needs = page.get_by_role("navigation", name="Primary").get_by_role(
            "link", name=re.compile("^Needs you")
        )
        assert re.search(
            r"\d+ waiting",
            needs.get_attribute("aria-label") or needs.evaluate("el => el.textContent"),
        )
        dot = needs.locator("span.bg-destructive")
        assert dot.is_visible(), "no count dot in the rail"
        needs.focus()  # reached by keyboard: the tooltip shows on focus as well as on hover
        page.locator("[data-slot='tooltip-content'][data-open]").wait_for(timeout=3_000)
        assert "Needs you" in page.locator("[data-slot='tooltip-content'][data-open]").inner_text()
    finally:
        page.context.close()


def test_the_rail_has_a_theme_menu_that_sets_system_light_and_dark(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        collapse(page)
        button = page.get_by_role("button", name=re.compile("^Theme"))
        button.click()
        for name in ("System", "Light", "Dark"):
            expect(page.get_by_role("menuitemradio", name=name)).to_be_visible()
        page.get_by_role("menuitemradio", name="Dark").click()
        assert page.evaluate("document.documentElement.classList.contains('dark')")
        page.keyboard.press("Escape")
        expect(page.get_by_role("button", name="Theme: Dark")).to_be_focused()
    finally:
        page.context.close()


def test_the_rail_choice_is_remembered_and_a_mid_width_window_starts_as_the_rail(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site, size=LAPTOP)  # 1024: no saved choice, so the rail
    try:
        expect(page.locator("[data-slot='sidebar']")).to_have_attribute("data-state", "collapsed")
        assert page.evaluate("localStorage.getItem('brandcal-sidebar')") is None
        page.keyboard.press("[")
        page.wait_for_selector("[data-slot='sidebar'][data-state='expanded']")
        page.reload()
        # A saved choice wins over the auto-rail.
        page.wait_for_selector("[data-slot='sidebar'][data-state='expanded']")
    finally:
        page.context.close()
    page = week(browser, site)  # 1440 starts open
    try:
        expect(page.locator("[data-slot='sidebar']")).to_have_attribute("data-state", "expanded")
    finally:
        page.context.close()


# -- one top bar, calendar first ------------------------------------------------------------


def test_the_calendar_has_one_bar_with_the_title_in_it_and_the_page_does_not_scroll(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        assert page.locator("header").count() == 1
        assert page.locator("h1").count() == 1
        assert page.locator("header h1").count() == 1
        assert "9 – 15 March 2026" in page.locator("h1").inner_text()
        assert page.locator("header").get_by_role("button", name="Toggle navigation").count() == 1
        for name in ("Previous week", "Next week", "Today", "Week", "Month"):
            found = page.locator("header").get_by_role("button", name=name, exact=True)
            assert found.count() == 1, name
        assert page.locator("header [data-needs-you-chip]").count() == 1
        assert page.locator("header [data-filters-toggle]").count() == 1
        assert page.evaluate("document.documentElement.scrollHeight <= innerHeight")
        assert page.locator("main").get_by_role("region", name="Week calendar").count() == 1
    finally:
        page.context.close()


GRID_TOP_JS = """() => {
  const grid = document.querySelector('[aria-label="Week calendar"]') || document.querySelector('[aria-label="Month calendar"]');
  const first = grid.querySelector('h3, [data-day]');
  return { grid: grid.getBoundingClientRect().top / innerHeight, first: first.getBoundingClientRect().top / innerHeight };
}"""


@pytest.mark.parametrize(
    ("size", "limit"),
    [(DESKTOP, 0.14), (LAPTOP, 0.14), (PHONE, 0.2)],
    ids=["1440x900", "1024x768", "390x844"],
)
def test_the_calendar_starts_high_on_the_screen(
    browser: Any, site: tuple[str, str], size: dict[str, int], limit: float
) -> None:
    page = week(browser, site, size=size)
    try:
        top = page.evaluate(GRID_TOP_JS)
        assert top["grid"] <= limit, top
    finally:
        page.context.close()


def test_the_strip_says_the_zone_offset_and_the_counts(browser: Any, site: tuple[str, str]) -> None:
    page = week(browser, site)
    try:
        strip = page.locator("[data-filter-strip]")
        text = strip.inner_text()
        assert re.search(r"[+-]\d\d:\d\d", text), text
        assert re.search(r"\d+ posts?", text) and "published" in text, text
        box = strip.bounding_box()
        assert box and 30 <= box["height"] <= 40, box
    finally:
        page.context.close()


# -- the Filters popover and the strip ------------------------------------------------------


def test_the_filters_popover_opens_by_keyboard_closes_on_esc_and_returns_focus(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        trigger = page.locator("[data-filters-toggle]")
        expect(trigger).to_have_attribute("aria-expanded", "false")
        trigger.focus()
        page.keyboard.press("Enter")
        popup = page.locator("[data-slot=popover-content][data-open]")
        popup.wait_for(timeout=5_000)
        expect(trigger).to_have_attribute("aria-expanded", "true")
        assert page.get_by_role("dialog", name="Filters").count() == 1
        assert popup.evaluate("el => el.contains(document.activeElement)"), "focus did not enter"
        page.keyboard.press("Escape")
        page.locator("[data-slot=popover-content]").wait_for(state="detached", timeout=5_000)
        expect(trigger).to_be_focused()
        expect(trigger).to_have_attribute("aria-expanded", "false")
    finally:
        page.context.close()


def test_esc_in_the_popover_closes_only_the_popover_when_the_panel_is_open(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = open_panel(browser, site, "light")
    try:
        page.locator("[data-filters-toggle]").click()
        page.locator("[data-slot=popover-content][data-open]").wait_for(timeout=5_000)
        page.keyboard.press("Escape")
        page.locator("[data-slot=popover-content]").wait_for(state="detached", timeout=5_000)
        assert page.locator(PANEL).count() == 1, "Esc closed the panel as well"
        assert "post=" in page.url
    finally:
        page.context.close()


def test_active_filters_show_as_chips_with_a_clear_button_and_live_in_the_url(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        strip = page.locator("[data-filter-strip]")
        assert strip.locator("[data-filter-chip]").count() == 0
        assert strip.get_by_role("button", name="Clear filters").count() == 0
        # C: the channel is chosen on the lane label, so the popover has no Platform half.
        page.locator('[data-lane-toggle="linkedin"]').click()
        page.wait_for_url(re.compile("platform=linkedin"))
        page.locator("[data-filters-toggle]").click()
        assert page.locator('[data-filter="platform:linkedin"]').count() == 0
        # The URL is the state, so a box ticks a moment after the click: click, then expect.
        page.locator('[data-filter="status:pending_approval"]').click()
        page.wait_for_url(re.compile("status=pending_approval"))
        assert "status=pending_approval" in page.url
        page.keyboard.press("Escape")
        page.locator("[data-slot=popover-content]").wait_for(state="detached", timeout=5_000)
        chips = strip.locator("[data-filter-chip]")
        expect(chips).to_have_count(2)
        # The lane chip is the channel; Filters (n) and the live count are the other half.
        expect(page.locator("[data-filters-toggle]")).to_contain_text("(1)")
        assert "1 filter applied" in strip.locator("[role=status]").inner_text()
        # One chip removes one filter.
        strip.get_by_role("button", name="Remove filter: LinkedIn").click()
        expect(chips).to_have_count(1)
        assert "platform=" not in page.url and "status=pending_approval" in page.url
        # Clear removes the rest.
        strip.get_by_role("button", name="Clear filters").click()
        expect(chips).to_have_count(0)
        assert "status=" not in page.url
        expect(page.locator("[data-filters-toggle]")).not_to_contain_text("(")
    finally:
        page.context.close()


def test_a_filtered_url_opens_with_the_chips_already_on(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = open_page(
        browser, site, "/", "light", size=DESKTOP, query=f"{WEEK_QUERY}&platform=linkedin"
    )
    try:
        wait_drawn(page, "[data-post-id]")
        expect(page.locator("[data-filter-chip='platform:linkedin']")).to_have_count(1)
    finally:
        page.context.close()


# -- Needs you ------------------------------------------------------------------------------


def test_the_needs_you_chip_toggles_the_three_statuses_and_aria_pressed(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        wanted = page.evaluate(
            "async () => { const s = await (await fetch('/api/schema')).json();"
            " return s.needs_you.filter((x) => s.states.includes(x)); }"
        )
        assert len(wanted) == 3, wanted
        chip = page.locator("[data-needs-you-chip]")
        expect(chip).to_have_attribute("aria-pressed", "false")
        assert re.search(r"Needs you\s*\d+", chip.inner_text()) or "waiting" in chip.inner_text()
        chip.click()
        expect(chip).to_have_attribute("aria-pressed", "true")
        page.wait_for_url(re.compile("status="))
        match = re.search(r"status=([^&]+)", page.url)
        assert match, page.url
        applied = set(match.group(1).replace("%2C", ",").split(","))
        assert applied == set(wanted), applied
        statuses = page.locator("[data-post-id] [data-status]").evaluate_all(
            "els => [...new Set(els.map((e) => e.dataset.status))]"
        )
        assert set(statuses) <= set(wanted), statuses
        chip.click()
        expect(chip).to_have_attribute("aria-pressed", "false")
        assert "status=" not in page.url
    finally:
        page.context.close()


# -- the panel ------------------------------------------------------------------------------


PANEL_ACTIONS_JS = """() => {
  const bar = document.querySelector('[data-panel-actions]').getBoundingClientRect();
  const button = document.querySelector('[data-panel-actions] button:not([disabled])').getBoundingClientRect();
  const panel = document.querySelector('aside[data-post-panel]');
  return { barTop: bar.top, barBottom: bar.bottom, button: [button.top, button.bottom], inView: bar.top >= 0 && bar.bottom <= innerHeight,
    scrolls: panel.scrollHeight > panel.clientHeight, height: innerHeight };
}"""


@pytest.mark.parametrize("size", [DESKTOP, LAPTOP], ids=["1440x900", "1024x768"])
def test_the_panel_actions_are_in_view_on_open_and_stay_there_while_scrolling(
    browser: Any, site: tuple[str, str], size: dict[str, int]
) -> None:
    page, _ = open_panel(browser, site, "light", size)
    try:
        opening = page.evaluate(PANEL_ACTIONS_JS)
        assert opening["inView"], opening
        # Actions come before History, Compare and the audit trail in the DOM, and those are disclosures.
        order = page.evaluate(
            "() => { const t = [...document.querySelectorAll('aside[data-post-panel] h3 button, aside[data-post-panel] [data-panel-actions]')];"
            " return t.map((e) => e.hasAttribute('data-panel-actions') ? 'actions' : e.textContent.trim()); }"
        )
        assert order[0] == "actions", order
        for title in ("Version history", "Compare versions", "Audit trail"):
            button = page.locator(PANEL).get_by_role("button", name=title)
            expect(button).to_have_attribute("aria-expanded", "false")
        page.locator(PANEL).evaluate("el => { el.scrollTop = el.scrollHeight }")
        page.wait_for_timeout(150)
        after = page.evaluate(PANEL_ACTIONS_JS)
        assert after["inView"], after
        assert after["barTop"] <= 1, after  # pinned to the top of the panel's scroller
    finally:
        page.context.close()


def test_a_disclosure_opens_and_closes_by_keyboard(browser: Any, site: tuple[str, str]) -> None:
    page, _ = open_panel(browser, site, "light")
    try:
        button = page.locator(PANEL).get_by_role("button", name="Audit trail")
        button.focus()
        page.keyboard.press("Enter")
        expect(button).to_have_attribute("aria-expanded", "true")
        assert page.locator(PANEL).get_by_role("list").filter(has_text="by ").count() >= 1
        page.keyboard.press("Space")
        expect(button).to_have_attribute("aria-expanded", "false")
    finally:
        page.context.close()


# -- container width, not viewport ----------------------------------------------------------


def test_opening_the_panel_at_1440_switches_to_day_bands_with_no_sideways_scroll(
    browser: Any, site: tuple[str, str]
) -> None:
    page = week(browser, site)
    try:
        columns = page.locator("[aria-label='Week calendar'][data-lane-grid]")
        assert columns.count() == 1, "lanes expected"
        pid = page.evaluate(
            "async () => (await (await fetch('/api/posts?closed=1')).json()).posts.find((p) => p.title === 'Spring launch thread').id"
        )
        page.locator(f"button[data-post-id='{pid}']").first.click()
        page.locator(PANEL).wait_for(timeout=5_000)
        page.wait_for_timeout(300)
        assert columns.count() == 0, "bands expected"
        found = page.evaluate(
            "() => { const r = document.querySelector('[aria-label=\"Week calendar\"]');"
            " return { region: [r.scrollWidth, r.clientWidth], page: document.documentElement.scrollWidth, w: innerWidth }; }"
        )
        assert found["region"][0] <= found["region"][1] and found["page"] <= found["w"], found
        page.get_by_role("button", name="Close panel").click()
        page.locator(PANEL).wait_for(state="detached")
        page.wait_for_timeout(300)
        assert page.locator("[aria-label='Week calendar'][data-lane-grid]").count() == 1
    finally:
        page.context.close()


@pytest.mark.parametrize("view", ["calendar-week", "calendar-month"])
def test_nothing_scrolls_sideways_at_320_with_the_bar_and_the_popover(
    browser: Any, site: tuple[str, str], view: str
) -> None:
    page, _ = load(browser, site, view, "light", size={"width": 320, "height": 640})
    try:
        scroll = "document.documentElement.scrollWidth"
        assert page.evaluate(scroll) <= 320
        wide = page.evaluate(
            "[...document.querySelectorAll('*')].filter((el) => ['auto','scroll'].includes(getComputedStyle(el).overflowX)"
            " && el.scrollWidth > el.clientWidth + 1 && el.getClientRects().length).map((el) => el.getAttribute('aria-label') || el.tagName)"
        )
        assert wide == [], wide
        page.locator("[data-filters-toggle]").click()
        page.locator("[data-slot=popover-content][data-open]").wait_for(timeout=5_000)
        page.wait_for_timeout(250)
        assert page.evaluate(scroll) <= 320
        box = page.locator("[data-slot=popover-content]").bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= 320.5, box
    finally:
        page.context.close()


# -- axe with the new surfaces --------------------------------------------------------------


@pytest.mark.parametrize("scheme", SCHEMES)
def test_axe_finds_nothing_with_the_filters_popover_open(
    browser: Any, site: tuple[str, str], scheme: str
) -> None:
    page = week(browser, site, scheme)
    try:
        page.locator("[data-filters-toggle]").click()
        page.locator("[data-slot=popover-content][data-open]").wait_for(timeout=5_000)
        page.wait_for_timeout(300)
        axe_report(page, f"foundation-filters-{scheme}")
    finally:
        page.context.close()


@pytest.mark.parametrize("scheme", SCHEMES)
def test_axe_finds_nothing_with_filters_applied_and_the_needs_you_chip_pressed(
    browser: Any, site: tuple[str, str], scheme: str
) -> None:
    page = week(browser, site, scheme)
    try:
        page.locator("[data-needs-you-chip]").click()
        page.wait_for_url(re.compile("status="))
        page.wait_for_timeout(300)
        axe_report(page, f"foundation-chip-{scheme}")
    finally:
        page.context.close()


@pytest.mark.parametrize("scheme", SCHEMES)
def test_axe_finds_nothing_with_the_rail_theme_menu_open(
    browser: Any, site: tuple[str, str], scheme: str
) -> None:
    page = week(browser, site, scheme)
    try:
        collapse(page)
        page.get_by_role("button", name=re.compile("^Theme")).click()
        page.get_by_role("menuitemradio", name="Light").wait_for(timeout=5_000)
        page.wait_for_timeout(300)
        axe_report(page, f"foundation-theme-menu-{scheme}")
    finally:
        page.context.close()

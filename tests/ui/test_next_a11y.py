# ruff: noqa: F811, E501
# (the fixtures come from test_next_writes.py / test_next_home.py by name; E501 is for the
# JavaScript snippets that run inside the page)
"""Accessibility gates for the new UI (N4): WCAG 2.2 AA as failing assertions.

axe (wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa) must find nothing on every route in both themes,
with the panel closed and open, the collapsed rail, the month view and the phone sheet; the four N3
dialogs are checked by test_next_writes.py through the same blocking helper. The rest of the
file is what axe cannot see: the real rendered contrast, a keyboard walk, focus in and out of the
panel and dialogs, reflow, text spacing, zoom, reduced motion and transparency, target size, the
now line and the notice timer. Same demo home and fixtures as test_next_writes.py.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import pytest
from axe_helper import axe_available

expect = pytest.importorskip("playwright.sync_api").expect
pytest.importorskip("cryptography")

from test_next_home import (  # noqa: E402, F401  (fixtures are used by name)
    PHONE,
    ROUTES,
    SCHEMES,
    axe_report,
    browser,
    idle,
    new_page,
    open_page,
    shot,
)
from test_next_views import TUESDAY, VIEWS, load, post_id, wait_drawn  # noqa: E402
from test_next_writes import (  # noqa: E402, F401
    DATE,
    button,
    dev_site,
    home,
    new_post,
    open_dialog,
    open_post,
    site,
)

pytestmark = pytest.mark.skipif(not axe_available(), reason="web/node_modules/axe-core is missing")

PANEL = "aside[data-post-panel]"
# The week grid is the one two-dimensional scroller; the Posts table is a data table, which WCAG
# 1.4.10 exempts (the page itself never scrolls sideways).
ALLOWED_SCROLL = {"Week calendar", "Posts"}
SPRING = "Spring launch thread"


# -- in-page helpers (all run with page.evaluate, which the page's CSP allows) ----------------

COLOUR_JS = """
const cv = document.createElement('canvas'); cv.width = cv.height = 1;
const cx = cv.getContext('2d', { willReadFrequently: true });
const rgba = (css) => {
  cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = css; cx.fillRect(0, 0, 1, 1);
  const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255];
};
const over = (fg, bg) => [0, 1, 2].map((i) => fg[i] * fg[3] + bg[i] * (1 - fg[3]));
const lum = (c) => {
  const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
};
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
// The opaque colour behind an element's content: every ancestor background, composited in order
// over the body's canvas (glass is a translucent fill over the canvas; the wash is checked in
// scripts/ui_contrast.py).
const backdrop = (el) => {
  const chain = []; for (let e = el; e; e = e.parentElement) chain.push(e);
  let base = rgba(getComputedStyle(document.body).backgroundColor).slice(0, 3);
  for (const e of chain.reverse()) {
    const c = rgba(getComputedStyle(e).backgroundColor);
    if (c[3] > 0) base = over(c, base);
  }
  return base;
};
const visible = (el) => {
  const r = el.getBoundingClientRect();
  if (r.width <= 2 || r.height <= 2) return false;
  for (let e = el; e; e = e.parentElement) {
    const s = getComputedStyle(e);
    if (s.visibility === 'hidden' || s.display === 'none' || Number(s.opacity) < 0.99) return false;
  }
  return true;
};
"""

CONTRAST_JS = (
    "() => {"
    + COLOUR_JS
    + """
  const out = [];
  const label = (el) => (el.getAttribute('data-post-id') || el.className.toString().slice(0, 40));
  for (const el of document.body.querySelectorAll('*')) {
    if (!visible(el)) continue;
    const s = getComputedStyle(el);
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (own) {
      const bg = backdrop(el);
      const fg = over(rgba(s.color), bg);
      const r = ratio(fg, bg);
      if (r < 4.5) out.push(['text', el.textContent.trim().slice(0, 30), r.toFixed(2)]);
    }
    if (el instanceof SVGSVGElement) {
      const bg = backdrop(el.parentElement);
      const r = ratio(over(rgba(s.stroke === 'none' ? s.color : s.stroke), bg), bg);
      if (r < 3) out.push(['icon', label(el.parentElement), r.toFixed(2)]);
    }
    if ((el.hasAttribute('data-status') || el.hasAttribute('data-platform'))
        && parseFloat(s.borderTopWidth) > 0 && s.borderTopStyle !== 'none') {
      const bg = backdrop(el.parentElement);
      const r = ratio(over(rgba(s.borderTopColor), bg), bg);
      if (r < 3) out.push(['chip border', label(el), r.toFixed(2)]);
    }
  }
  return out;
}"""
)

DESCRIBE_JS = (
    "() => {"
    + COLOUR_JS
    + """
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  window.__n = window.__n || 0; el.__k = el.__k || ++window.__n;
  const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
  const bg = backdrop(el.parentElement || el);
  let ring = 0;
  if (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) >= 1) {
    ring = ratio(over(rgba(s.outlineColor), bg), bg);
  }
  for (const m of s.boxShadow.matchAll(/(rgba?\\([^)]*\\))((?:\\s+-?[\\d.]+px){2,4})/g)) {
    const spread = Number((m[2].trim().split(/\\s+/)[3] || '0px').replace('px', ''));
    if (spread >= 2) ring = Math.max(ring, ratio(over(rgba(m[1]), bg), bg));
  }
  const tiny = r.width <= 2 || r.height <= 2;
  // Covered only if every sample point of the box that is on screen is hit by something else:
  // a control partly scrolled out of its container is not "entirely hidden" (2.4.11).
  const points = [[0.5, 0.5], [0.1, 0.1], [0.9, 0.1], [0.1, 0.9], [0.9, 0.9]]
    .map(([x, y]) => [r.left + r.width * x, r.top + r.height * y])
    .filter(([x, y]) => x >= 0 && y >= 0 && x < innerWidth && y < innerHeight);
  const hit = (p) => { const t = document.elementFromPoint(p[0], p[1]);
    return t && (el === t || el.contains(t) || t.contains(el)); };
  const covered = !tiny && !points.some(hit);
  const inView = r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
  const region = el.matches('a[href="#main"]') ? -1
    : el.closest("[data-slot='sidebar-container'], [data-slot='sidebar']") ? 0
    : el.closest('header') ? 1 : el.closest('main') ? 2
    : el.closest('aside[data-post-panel]') ? 3 : 9;
  return { key: el.__k, name: (el.getAttribute('aria-label') || el.textContent || el.tagName)
    .trim().slice(0, 30), ring, tiny, covered, inView, region, top: r.top, left: r.left };
}"""
)

TABBABLE_JS = (
    "() => {"
    + COLOUR_JS
    + """
  window.__n = window.__n || 0;
  const q = 'a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select,'
    + ' textarea, [tabindex]:not([tabindex="-1"])';
  return [...document.querySelectorAll(q)]
    .filter((el) => el.tabIndex >= 0 && el.getClientRects().length && !el.closest('[inert], [hidden]')
      && getComputedStyle(el).visibility !== 'hidden')
    .map((el) => { el.__k = el.__k || ++window.__n; return el.__k; });
}"""
)

TARGETS_JS = (
    "() => {"
    + COLOUR_JS
    + """
  const q = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button],'
    + ' [role=radio], [role=checkbox], [tabindex="0"]';
  const all = [...document.querySelectorAll(q)].filter((el) => visible(el) && !el.closest('[inert]'));
  const rects = all.map((el) => {
    const label = el.labels && el.labels[0];
    const r = (label && visible(label) ? label : el).getBoundingClientRect();
    return { el, r };
  });
  const out = [];
  for (const { el, r } of rects) {
    if (r.width >= 24 && r.height >= 24) continue;
    if (el.matches('p a, li a, td a') && el.closest('p, li, td')?.textContent.trim() !== el.textContent.trim()) continue;
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    const clash = rects.some((o) => {
      if (o.el === el) return false;
      const dx = Math.max(o.r.left - cx, 0, cx - o.r.right);
      const dy = Math.max(o.r.top - cy, 0, cy - o.r.bottom);
      return Math.hypot(dx, dy) < 12;
    });
    if (clash) out.push([el.tagName.toLowerCase(), (el.getAttribute('aria-label') || el.textContent).trim().slice(0, 30), Math.round(r.width), Math.round(r.height)]);
  }
  return out;
}"""
)

TEXT_SPACING_CSS = (
    "*{line-height:1.5 !important;letter-spacing:0.12em !important;word-spacing:0.16em !important}"
    "p{margin-bottom:2em !important}"
)
SPACING_JS = (
    "(css) => { const s = new CSSStyleSheet(); s.replaceSync(css);"
    " document.adoptedStyleSheets = [...document.adoptedStyleSheets, s]; }"
)
CLIPPED_JS = """() => [...document.querySelectorAll(
  'h1, h2, h3, button, [data-status], [data-platform], label, th')]
  .filter((el) => { const r = el.getBoundingClientRect();
    return r.width > 2 && r.height > 2 && !el.closest('[aria-hidden=true], [inert]'); })
  .filter((el) => el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1)
  .map((el) => (el.getAttribute('aria-label') || el.textContent).trim().slice(0, 40))"""
SCROLLERS_JS = """() => ({
  page: document.documentElement.scrollWidth,
  wide: [...document.querySelectorAll('*')].filter((el) => {
    const s = getComputedStyle(el);
    return ['auto', 'scroll'].includes(s.overflowX) && el.scrollWidth > el.clientWidth + 1
      && el.getClientRects().length;
  }).map((el) => el.getAttribute('aria-label') || el.tagName.toLowerCase()),
})"""


def thread_id(page: Any) -> str:
    return post_id(page, SPRING)


def open_panel(
    browser: Any, site: tuple[str, str], scheme: str, size: dict[str, int] | None = None
) -> tuple[Any, list[str]]:
    page, _ = open_page(browser, site, "/", scheme, query=f"?view=week&date={DATE}")
    pid = thread_id(page)
    page.context.close()
    page, problems = open_page(
        browser,
        site,
        "/",
        scheme,
        **({"size": size} if size else {}),
        query=f"?view=week&date={DATE}&post={pid}",
    )
    wait_drawn(page, f"{PANEL} pre")
    page.wait_for_timeout(300)
    return page, problems


# -- a. axe: zero violations, light and dark -------------------------------------------------


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("view", [*VIEWS, "settings"])
def test_axe_finds_nothing_on_every_route(
    browser: Any, site: tuple[str, str], view: str, scheme: str
) -> None:
    if view == "settings":
        page, _ = open_page(browser, site, "/settings/", scheme)
    else:
        page, _ = load(browser, site, view, scheme)
    try:
        axe_report(page, f"next-a11y-{view}-{scheme}")
    finally:
        page.context.close()


@pytest.mark.parametrize("scheme", SCHEMES)
def test_axe_finds_nothing_with_the_panel_open(
    browser: Any, site: tuple[str, str], scheme: str
) -> None:
    page, _ = open_panel(browser, site, scheme)
    try:
        axe_report(page, f"next-a11y-panel-{scheme}")
    finally:
        page.context.close()


@pytest.mark.parametrize("scheme", SCHEMES)
def test_axe_finds_nothing_on_the_collapsed_rail(
    browser: Any, site: tuple[str, str], scheme: str
) -> None:
    page, _ = load(browser, site, "calendar-week", scheme)
    try:
        page.keyboard.press("[")
        page.wait_for_selector("[data-slot='sidebar'][data-state='collapsed']")
        page.mouse.move(700, 450)
        page.wait_for_timeout(350)
        axe_report(page, f"next-a11y-rail-{scheme}")
    finally:
        page.context.close()


@pytest.mark.parametrize("scheme", SCHEMES)
def test_axe_finds_nothing_in_the_phone_sheet(
    browser: Any, site: tuple[str, str], scheme: str
) -> None:
    page, _ = open_page(browser, site, "/", scheme, size=PHONE)
    try:
        page.get_by_role("button", name="Toggle navigation").click()
        page.get_by_role("dialog").wait_for(timeout=5_000)
        page.wait_for_timeout(350)
        axe_report(page, f"next-a11y-phone-sheet-{scheme}")
    finally:
        page.context.close()


@pytest.mark.parametrize("scheme", SCHEMES)
def test_axe_finds_nothing_at_390_with_the_filters_open(
    browser: Any, site: tuple[str, str], scheme: str
) -> None:
    page, _ = load(browser, site, "calendar-week", scheme, size=PHONE)
    try:
        toggle = page.locator("[data-filters-toggle]")
        expect(toggle).to_have_attribute("aria-expanded", "false")
        toggle.click()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        axe_report(page, f"next-a11y-filters-{scheme}")
    finally:
        page.context.close()


# -- rendered contrast (what axe marks "needs review") ---------------------------------------


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("panel", [False, True], ids=["blocks", "panel"])
def test_rendered_contrast_of_text_icons_and_chips(
    browser: Any, site: tuple[str, str], scheme: str, panel: bool
) -> None:
    if panel:
        page, _ = open_panel(browser, site, scheme)
    else:
        page, _ = load(browser, site, "calendar-week", scheme)
    try:
        assert page.evaluate(CONTRAST_JS) == []
    finally:
        page.context.close()


def test_every_platform_has_its_own_block_colour_in_both_themes(
    browser: Any, site: tuple[str, str]
) -> None:
    for scheme in SCHEMES:
        page, _ = load(browser, site, "calendar-week", scheme)
        try:
            seen = page.evaluate(
                "() => Object.fromEntries([...document.querySelectorAll('button[data-post-id]')]"
                ".map((b) => [b.querySelector('[data-platform]').dataset.platform,"
                " [getComputedStyle(b).backgroundColor, ['Top', 'Right', 'Bottom', 'Left']"
                ".map((s) => getComputedStyle(b)['border' + s + 'Width']).join(' ')]]))"
            )
        finally:
            page.context.close()
        assert len(seen) >= 3, seen
        fills = [fill for fill, _ in seen.values()]
        assert len(set(fills)) == len(fills), seen  # the pastel fill alone tells platforms apart
        # No accent stripe on any edge: the fill, the printed name and a faint inner hairline.
        assert all(borders == "0px 0px 0px 0px" for _, borders in seen.values()), seen


# -- b. the keyboard walk --------------------------------------------------------------------


def walk(page: Any) -> list[dict[str, Any]]:
    """Tab from the skip link through every focusable element, then Shift+Tab all the way back."""
    page.evaluate("window.scrollTo(0, 0)")
    page.evaluate("document.querySelector('a[href=\"#main\"]').focus()")
    seen = [page.evaluate(DESCRIBE_JS)]
    assert seen[0] and seen[0]["name"] == "Skip to main content", seen[0]
    for _ in range(250):
        page.keyboard.press("Tab")
        info = page.evaluate(DESCRIBE_JS)
        if info is None or info["key"] == seen[0]["key"]:
            break
        seen.append(info)
    else:
        raise AssertionError("Tab never leaves the page: a keyboard trap")
    back = []
    for _ in range(len(seen) - 1):
        page.keyboard.press("Shift+Tab")
        back.append(page.evaluate(DESCRIBE_JS)["key"])
    # Tab ended on the wrap (or the skip link again), so the first Shift+Tab lands on the last.
    assert back == [s["key"] for s in reversed(seen[1:])], "Shift+Tab does not retrace Tab"
    return seen


def check_walk(page: Any) -> None:
    expected = set(page.evaluate(TABBABLE_JS))
    seen = walk(page)
    keys = {s["key"] for s in seen}
    assert expected <= keys, f"{len(expected - keys)} focusable element(s) were never reached"
    regions = [s["region"] for s in seen]
    assert regions == sorted(regions), f"focus order does not follow the layout: {regions}"
    for s in seen:
        if not s["tiny"]:
            assert s["ring"] >= 3, f"no 3:1 focus indicator on {s['name']!r} ({s['ring']:.2f})"
        assert s["inView"], f"{s['name']!r} is off screen when focused"
        assert not s["covered"], f"{s['name']!r} is hidden behind something when focused (2.4.11)"


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("view", [*VIEWS, "settings"])
def test_keyboard_walk_on_every_route(
    browser: Any, site: tuple[str, str], view: str, scheme: str
) -> None:
    if view == "settings":
        page, _ = open_page(browser, site, "/settings/", scheme)
    else:
        page, _ = load(browser, site, view, scheme)
    try:
        check_walk(page)
    finally:
        page.context.close()


def test_keyboard_walk_with_the_panel_beside_the_page(browser: Any, site: tuple[str, str]) -> None:
    page, _ = open_panel(browser, site, "light")
    try:
        check_walk(page)
        assert page.evaluate(
            "[...document.querySelectorAll('[data-post-panel] *')].some((e) => e.tabIndex >= 0)"
        )
    finally:
        page.context.close()


def test_the_panel_takes_focus_traps_it_while_modal_and_returns_it(
    browser: Any, site: tuple[str, str]
) -> None:
    size = {"width": 1024, "height": 768}
    page, _ = load(browser, site, "calendar-week", "light", size=size)
    try:
        block = page.locator(f"button[data-post-id]:has-text('{SPRING}')").first
        pid = block.get_attribute("data-post-id")
        block.focus()
        page.keyboard.press("Enter")
        wait_drawn(page, f"{PANEL} pre")
        page.wait_for_timeout(300)
        assert page.evaluate("document.activeElement.id") == "panel-title"
        # Programmatic focus on the heading (tabindex=-1) draws no ring: it is not a control.
        assert page.evaluate("getComputedStyle(document.activeElement).outlineStyle") == "none"
        # Modal below 1200 px: Tab never reaches the page behind. Leaving the document (focus on
        # the body, i.e. the browser's own controls) is the normal wrap, not a trap.
        inside = (
            f"['BODY', 'HTML'].includes(document.activeElement.tagName)"
            f" || document.activeElement.closest('{PANEL}') !== null"
        )
        for key in ("Tab", "Shift+Tab"):
            for _ in range(40):
                page.keyboard.press(key)
                assert page.evaluate(inside), (
                    key,
                    page.evaluate("document.activeElement.outerHTML.slice(0, 160)"),
                )
        page.keyboard.press("Escape")
        expect(page.locator(PANEL)).to_have_count(0)
        assert page.evaluate("document.activeElement.dataset.postId") == pid
    finally:
        page.context.close()


@pytest.mark.parametrize("action", ["approve", "request-changes", "cancel", "edit"])
def test_every_dialog_takes_focus_traps_it_and_returns_it(
    browser: Any, site: tuple[str, str], home: Any, action: str
) -> None:
    pid = new_post(home, f"a11y-{action}", f"Access check {action}")
    page, _ = open_post(browser, site, pid)
    try:
        dialog = open_dialog(page, action)
        page.wait_for_timeout(250)
        assert dialog.evaluate("(el) => el.contains(document.activeElement)")
        for key in ("Tab", "Shift+Tab"):
            for _ in range(25):
                page.keyboard.press(key)
                page.wait_for_timeout(30)  # focus guards hand focus back asynchronously
                assert dialog.evaluate("(el) => el.contains(document.activeElement)"), key
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        expect(button(page, action)).to_be_focused()
    finally:
        page.context.close()


# -- c. reflow, text spacing, zoom, motion, transparency, target size ------------------------


@pytest.mark.parametrize("path", list(ROUTES))
def test_reflow_at_320_has_no_two_dimensional_scroll_but_the_week_grid(
    browser: Any, site: tuple[str, str], path: str
) -> None:
    page, _ = open_page(
        browser, site, path, "light", size={"width": 320, "height": 640}, query=f"?date={DATE}"
    )
    try:
        found = page.evaluate(SCROLLERS_JS)
        assert found["page"] <= 320, found
        assert set(found["wide"]) <= ALLOWED_SCROLL, found
    finally:
        page.context.close()


@pytest.mark.parametrize("view", ["calendar-week", "calendar-month", "posts", "needs-you"])
def test_reflow_at_320_for_the_data_views(browser: Any, site: tuple[str, str], view: str) -> None:
    page, _ = load(browser, site, view, "light", size={"width": 320, "height": 640})
    try:
        found = page.evaluate(SCROLLERS_JS)
        assert found["page"] <= 320, found
        assert set(found["wide"]) <= ALLOWED_SCROLL, found
    finally:
        page.context.close()


@pytest.mark.parametrize("view", [*VIEWS, "settings"])
def test_text_spacing_clips_nothing(browser: Any, site: tuple[str, str], view: str) -> None:
    if view == "settings":
        page, _ = open_page(browser, site, "/settings/", "light")
    else:
        page, _ = load(browser, site, view, "light")
    try:
        page.evaluate(SPACING_JS, TEXT_SPACING_CSS)
        page.wait_for_timeout(150)
        assert page.evaluate(CLIPPED_JS) == []
    finally:
        page.context.close()


def test_text_spacing_clips_nothing_in_the_panel(browser: Any, site: tuple[str, str]) -> None:
    page, _ = open_panel(browser, site, "light")
    try:
        page.evaluate(SPACING_JS, TEXT_SPACING_CSS)
        page.wait_for_timeout(150)
        assert page.evaluate(CLIPPED_JS) == []
    finally:
        page.context.close()


@pytest.mark.parametrize("path", list(ROUTES))
def test_200_percent_zoom_keeps_every_route_usable(
    browser: Any, site: tuple[str, str], path: str
) -> None:
    # 200% at 1280x800 is a 640x400 CSS pixel viewport.
    page, _ = open_page(browser, site, path, "light", size={"width": 640, "height": 400})
    try:
        found = page.evaluate(SCROLLERS_JS)
        assert found["page"] <= 640, found
        assert set(found["wide"]) <= ALLOWED_SCROLL, found
        assert page.get_by_role("heading", level=1).is_visible()
        page.get_by_role("button", name="Toggle navigation").click()
        assert page.get_by_role("link", name=re.compile("^Settings")).first.is_visible()
    finally:
        page.context.close()


def test_reduced_motion_removes_every_transition_on_the_panel_and_dialogs(
    browser: Any, site: tuple[str, str], home: Any
) -> None:
    longest = (
        "(root) => Math.max(0, ...[root, ...root.querySelectorAll('*')].flatMap((e) =>"
        " [getComputedStyle(e).transitionDuration, getComputedStyle(e).animationDuration]"
        ".flatMap((v) => v.split(',').map((x) => parseFloat(x) * (x.includes('ms') ? 0.001 : 1)))))"
    )
    pid = new_post(home, "a11y-motion", "Motion check")
    page, _ = open_post(browser, site, pid)  # new_page sets reduced_motion="reduce"
    try:
        assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
        assert page.locator(PANEL).evaluate(longest) <= 0.001
        for action in ("approve", "request-changes", "cancel", "edit"):
            dialog = open_dialog(page, action)
            assert dialog.evaluate(longest) <= 0.001, action
            overlay = page.locator("[data-slot$='overlay']")
            if overlay.count():
                assert overlay.first.evaluate(longest) <= 0.001, action
            page.wait_for_timeout(250)  # focus must be in the dialog, or Escape closes the panel
            page.keyboard.press("Escape")
            expect(dialog).to_have_count(0)
    finally:
        page.context.close()


@pytest.mark.parametrize("scheme", SCHEMES)
def test_reduced_transparency_makes_the_shell_and_panel_solid(
    browser: Any, site: tuple[str, str], scheme: str
) -> None:
    page, _ = open_panel(browser, site, scheme)
    try:
        cdp = page.context.new_cdp_session(page)
        cdp.send(
            "Emulation.setEmulatedMedia",
            {"features": [{"name": "prefers-reduced-transparency", "value": "reduce"}]},
        )
        assert page.evaluate("matchMedia('(prefers-reduced-transparency: reduce)').matches")
        page.wait_for_timeout(300)
        for selector in ("header", PANEL, "[data-slot='sidebar-container'] > div"):
            style = page.locator(selector).first.evaluate(
                "(e) => { const s = getComputedStyle(e);"
                " return [s.backdropFilter, s.backgroundColor]; }"
            )
            assert style[0] == "none", (selector, style)
            assert not style[1].startswith(("rgba", "color(")) or style[1].endswith(", 1)"), style
        solid = page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--glass-solid').trim()"
        )
        assert re.fullmatch(r"#[0-9a-f]{6}", solid)
    finally:
        page.context.close()


@pytest.mark.parametrize("size", [{"width": 1440, "height": 900}, PHONE], ids=["desktop", "phone"])
@pytest.mark.parametrize("view", [*VIEWS, "settings"])
def test_every_target_is_24_px_or_has_the_spacing_exception(
    browser: Any, site: tuple[str, str], view: str, size: dict[str, int]
) -> None:
    if view == "settings":
        page, _ = open_page(browser, site, "/settings/", "light", size=size)
    else:
        page, _ = load(browser, site, view, "light", size=size)
    try:
        assert page.evaluate(TARGETS_JS) == []
    finally:
        page.context.close()


# -- the now line and the notice -------------------------------------------------------------


def test_the_now_line_sits_on_the_right_day_and_hour_and_is_hidden_from_assistive_tech(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = new_clock_page(browser, site, dt.datetime.fromisoformat(f"{TUESDAY}T10:30:00+01:00"))
    try:
        page.goto(f"{site[0]}/?view=week&date={DATE}")
        wait_drawn(page, "[data-post-id]")
        line = page.locator("[data-now]")
        expect(line).to_have_count(1)
        assert line.get_attribute("aria-hidden") == "true"
        assert line.get_attribute("data-now") == "10:30"
        day = page.locator(f"section[data-day='{TUESDAY}']")
        assert day.locator("[data-now]").count() == 1  # on Tuesday, not on another day
        assert page.locator("[data-now]").count() == 1
        label = day.locator(".sr-only", has_text="Now: 10:30")  # visually hidden, still read
        expect(label).to_have_count(1)
        # The rule sits inside the stack, after every card that starts before 10:30 and before
        # every card that starts after it.
        order = page.evaluate(
            "(() => { const l = document.querySelector('[data-now]'); const y = l.getBoundingClientRect().top;"
            " return [...l.closest('section').querySelectorAll('button[data-post-id]')]"
            ".map((b) => [b.dataset.start, b.getBoundingClientRect().top < y]); })()"
        )
        assert order, "no cards on the day with the rule"
        for start, above in order:
            assert above == (start <= "10:30"), order
    finally:
        page.context.close()


def new_clock_page(browser: Any, site: tuple[str, str], when: dt.datetime) -> tuple[Any, list[str]]:
    page, problems = new_page(browser, site, "light")
    page.clock.install(time=when)
    return page, problems


def test_the_notice_lasts_8_s_pauses_on_hover_and_focus_and_never_covers_the_focus(
    browser: Any, site: tuple[str, str], home: Any
) -> None:
    pid = new_post(home, "a11y-notice", "Notice check")
    page, _ = new_clock_page(browser, site, dt.datetime.now(dt.UTC))
    try:
        page.set_viewport_size({"width": 1024, "height": 768})
        page.goto(f"{site[0]}/?view=week&date={DATE}&post={pid}")
        page.locator(f"{PANEL} [data-action-button]").first.wait_for(timeout=10_000)
        card = page.locator("[data-notice-host] > div")

        def send_note(text: str) -> None:
            dialog = open_dialog(page, "note")
            dialog.get_by_label("Note (required)").fill(text)
            dialog.locator("button[type=submit]").click()
            expect(dialog).to_have_count(0)
            expect(card).to_have_attribute("data-open", "true")

        send_note("First note.")
        page.clock.fast_forward(7_000)
        expect(card).to_have_attribute("data-open", "true")  # still there at 7 s
        page.clock.fast_forward(1_500)
        expect(card).to_have_attribute("data-open", "false")  # gone after 8 s

        send_note("Second note.")
        card.hover()
        page.clock.fast_forward(30_000)
        expect(card).to_have_attribute("data-open", "true")  # hovering pauses the clock
        page.mouse.move(5, 400)
        page.clock.fast_forward(8_500)
        expect(card).to_have_attribute("data-open", "false")

        send_note("Third note.")
        dismiss = page.get_by_role("button", name="Dismiss notice")
        dismiss.focus()
        page.clock.fast_forward(30_000)
        expect(card).to_have_attribute("data-open", "true")  # focus inside pauses it too
        page.keyboard.press("Tab")  # leaves the card; the clock restarts
        page.clock.fast_forward(8_500)
        expect(card).to_have_attribute("data-open", "false")

        # A visible notice never covers the control that has focus (WCAG 2.4.11).
        send_note("Fourth note.")
        notice = card.bounding_box()
        assert notice
        for _ in range(30):
            page.keyboard.press("Tab")
            box = page.evaluate(
                "(() => { const r = document.activeElement.getBoundingClientRect();"
                " return [r.left, r.top, r.right, r.bottom]; })()"
            )
            if page.evaluate(
                "document.activeElement.closest('[data-notice-host]') !== null"
                " || ['BODY', 'HTML'].includes(document.activeElement.tagName)"
            ):
                continue  # the card itself, or focus has left the document (the browser's wrap)
            overlap = not (
                box[2] <= notice["x"]
                or box[0] >= notice["x"] + notice["width"]
                or box[3] <= notice["y"]
                or box[1] >= notice["y"] + notice["height"]
            )
            assert not overlap, (box, notice)
    finally:
        page.context.close()


# -- the sidebar --------------------------------------------------------------------------------


@pytest.mark.parametrize("scheme", SCHEMES)
def test_every_sidebar_label_stays_on_one_line_and_hints_show_only_on_hover_or_focus(
    browser: Any, site: tuple[str, str], scheme: str
) -> None:
    page, _ = load(browser, site, "calendar-week", scheme)
    try:
        nav = page.get_by_role("navigation", name="Primary")
        heights = nav.locator("a > span:first-of-type").evaluate_all(
            "(els) => els.map((e) => e.getBoundingClientRect().height)"
        )
        assert heights and max(heights) < 24, heights  # one line of 14 px text each
        hints = nav.locator("kbd[data-slot='kbd-group']")
        opacity = "(e) => getComputedStyle(e).opacity"
        assert [h.evaluate(opacity) for h in hints.all()] == ["0"] * hints.count()
        posts = nav.get_by_role("link", name=re.compile("^Posts"))
        posts.hover()
        page.wait_for_timeout(100)
        assert posts.locator("kbd[data-slot='kbd-group']").evaluate(opacity) == "1", "hover"
        page.mouse.move(700, 450)
        posts.focus()
        page.wait_for_timeout(100)
        assert posts.locator("kbd[data-slot='kbd-group']").evaluate(opacity) == "1", "focus"
    finally:
        page.context.close()


def test_the_needs_you_count_follows_the_mvp_rule_for_a_viewer_too(
    browser: Any, dev_site: tuple[str, str]
) -> None:
    """--dev-unverified is a viewer; the count is the same statuses the MVP strip counts
    (schema.needs_you that the schema also lists as states), whatever the role."""
    page, _ = open_page(browser, dev_site, "/needs-you/", "light")
    try:
        wait_drawn(page, "main li button[data-post-id]")
        rows = page.locator("main li button[data-post-id]").count()
        link = page.get_by_role("navigation", name="Primary").get_by_role(
            "link", name=re.compile("^Needs you")
        )
        assert f"{rows} waiting" in link.inner_text().replace("\n", " ")
        idle(page)
    finally:
        page.context.close()


def test_the_mvp_loads_in_dev_unverified_mode_without_a_null_error(
    browser: Any, dev_site: tuple[str, str]
) -> None:
    page, problems = new_page(browser, dev_site, "light")
    page.goto(f"{dev_site[0]}/mvp/")  # no date in the URL: "today" needs the schema's zone
    page.wait_for_selector("[data-ready]", timeout=10_000)
    shot(page, "mvp-dev-unverified")
    try:
        assert not [p for p in problems if "timezone" in p or "null" in p], problems
        assert page.locator("#banner").is_visible()
    finally:
        page.context.close()

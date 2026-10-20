"""The new UI shell (N1) under the CSP: every route, the rail, the phone sheet and the dev banner.

Needs Playwright and chromium (see test_screens.py). Each route loads in light and dark with zero
console errors, zero page errors and zero `securitypolicyviolation` events; shots go to
build/ui-shots/next-<route>-<theme>.png. The axe runs are advisory: they write
build/ui-shots/axe-next-*.json and fail on any violation (test_next_a11y.py holds the rest of
the accessibility gates).
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from axe_helper import axe_available, run_axe

sync_api = pytest.importorskip("playwright.sync_api")
pytest.importorskip("cryptography")

from jwt_env import AUD, TEAM, FakeJwks, Signer, claims  # noqa: E402
from test_screens import SHOTS, SIZE, WEEK, load_demo  # noqa: E402

from brandcal import serve  # noqa: E402
from brandcal.config import load_config  # noqa: E402
from brandcal.identity import Verifier  # noqa: E402

SCHEMES = ["light", "dark"]
ROUTES = {
    "/": "calendar",
    "/needs-you/": "needs-you",
    "/posts/": "posts",
    "/channels/": "channels",
    "/activity/": "activity",
    "/settings/": "settings",
}
PHONE = {"width": 390, "height": 844}
WATCH_CSP = (
    "window.__csp = [];"
    "document.addEventListener('securitypolicyviolation',"
    " e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));"
)
IDLE = "document.querySelectorAll('[aria-busy=\"true\"]').length === 0"


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    path = tmp_path_factory.mktemp("demo-next") / "home"
    load_demo().build(path, WEEK)
    yield path


@pytest.fixture(scope="module")
def site(home: Any) -> Iterator[tuple[str, str]]:
    signer = Signer()
    verifier = Verifier(TEAM, AUD, 5, fetch=FakeJwks(signer))
    server = serve.make_server(home, load_config(home), 0, verifier)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", signer.token(claims())
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def dev_site(home: Any) -> Iterator[tuple[str, str]]:
    """The same data served with --dev-unverified: no identity, read-only."""
    server = serve.make_server(home, load_config(home), 0, None, dev=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", ""
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


def new_page(
    browser: Any, site: tuple[str, str], scheme: str, size: dict[str, int] = SIZE
) -> tuple[Any, list[str]]:
    url, token = site
    context = browser.new_context(
        viewport=size,
        color_scheme=scheme,
        reduced_motion="reduce",
        extra_http_headers={"Cf-Access-Jwt-Assertion": token} if token else {},
    )
    context.add_init_script(WATCH_CSP)
    problems: list[str] = []
    page = context.new_page()
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    # Chromium's console line for a failed request has no URL; name the request as well.
    page.on(
        "response",
        lambda r: (
            problems.append(f"{r.status} {r.request.method} {r.url}") if r.status >= 400 else None
        ),
    )
    return page, problems


def idle(page: Any) -> None:
    """Wait until nothing on the page is busy. A locator wait, not wait_for_function: Playwright
    compiles that predicate with eval, which the page's CSP refuses."""
    page.locator('[aria-busy="true"]').first.wait_for(state="detached", timeout=10_000)


def until(page: Any, expression: str, timeout_ms: int = 10_000) -> None:
    """Poll a JavaScript expression with page.evaluate (which the CSP does not block)."""
    for _ in range(timeout_ms // 50):
        if page.evaluate(expression):
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"timed out waiting for: {expression}")


def open_page(
    browser: Any,
    site: tuple[str, str],
    path: str,
    scheme: str,
    size: dict[str, int] = SIZE,
    query: str = "",
) -> tuple[Any, list[str]]:
    """The page at ``path`` once it has loaded, with every console error and page error."""
    page, problems = new_page(browser, site, scheme, size)
    page.goto(f"{site[0]}{path}{query}")
    if path.startswith("/mvp/"):
        page.wait_for_selector("[data-ready]", timeout=10_000)
        page.wait_for_selector(".card", timeout=10_000)
    else:
        page.get_by_role("heading", level=1).wait_for(timeout=10_000)
        idle(page)
        assert page.evaluate("document.documentElement.classList.contains('dark')") == (
            scheme == "dark"
        )
    page.wait_for_timeout(300)  # let late errors and violations arrive
    return page, problems


def shot(page: Any, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=False)


def axe_report(page: Any, name: str) -> list[str]:
    """Blocking: write build/ui-shots/axe-<name>.json and fail on any violation (the MVP tests in
    test_screens.py keep their own advisory helper). "Needs review" items are only reported."""
    found = run_axe(page)
    SHOTS.mkdir(parents=True, exist_ok=True)
    (SHOTS / f"axe-{name}.json").write_text(json.dumps(found, indent=2) + "\n", encoding="utf-8")
    ids = [f"{v['id']} x{v['count']} {v['targets']}" for v in found["violations"]]
    assert not ids, f"axe ({name}): {'; '.join(ids)}"
    return ids


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("path", [*ROUTES, "/mvp/"])
def test_page_loads_with_no_console_errors_or_csp_violations(
    browser: Any, site: tuple[str, str], path: str, scheme: str
) -> None:
    query = f"?view=week&date={WEEK.isoformat()}" if path == "/mvp/" else ""
    page, problems = open_page(browser, site, path, scheme, query=query)
    shot(page, f"{'mvp-home' if path == '/mvp/' else 'next-' + ROUTES[path]}-{scheme}")
    violations = page.evaluate("window.__csp")
    page.context.close()
    assert not problems, problems
    assert violations == []


@pytest.mark.parametrize("path", list(ROUTES))
def test_every_route_has_a_title_a_heading_and_the_landmarks(
    browser: Any, site: tuple[str, str], path: str
) -> None:
    page, problems = open_page(browser, site, path, "light")
    try:
        title = page.title()
        assert title.endswith(" · brandcal"), title
        assert page.locator("h1").count() == 1
        for landmark in ("banner", "navigation", "main"):
            assert page.get_by_role(landmark).count() == 1, landmark
        assert page.evaluate("document.documentElement.lang") == "en-GB"
        assert not problems
    finally:
        page.context.close()


def test_the_sidebar_lists_every_page_marks_the_current_one_and_shows_the_identity(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = open_page(browser, site, "/posts/", "light")
    try:
        nav = page.get_by_role("navigation", name="Primary")
        for name in ("Calendar", "Needs you", "Posts", "Channels", "Activity", "Settings"):
            assert nav.get_by_role("link", name=re.compile(f"^{name}")).count() == 1, name
        current = nav.locator("[aria-current='page']")
        assert current.count() == 1 and current.inner_text().startswith("Posts")
        footer = page.locator("[data-sidebar='footer']")
        assert "access-jwt" in footer.inner_text()
        assert footer.get_by_role("radio", name="Dark").is_visible()
        assert page.locator("[data-dev-banner]").count() == 0
    finally:
        page.context.close()


def test_the_needs_you_badge_counts_the_posts_that_need_the_viewer(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = open_page(browser, site, "/", "light")
    try:
        expected = page.evaluate(
            "async () => { const schema = await (await fetch('/api/schema')).json();"
            " let n = 0; for (const s of schema.needs_you) {"
            " n += (await (await fetch('/api/posts?status=' + s)).json()).posts.length; }"
            " return n; }"
        )
        link = page.get_by_role("navigation", name="Primary").get_by_role(
            "link", name=re.compile("^Needs you")
        )
        if expected:
            assert link.inner_text().split("\n")[1].strip().startswith(str(expected))
        else:
            assert "waiting" not in link.inner_text()
    finally:
        page.context.close()


def test_post_id_comes_from_the_query_not_a_route(browser: Any, site: tuple[str, str]) -> None:
    page, problems = open_page(browser, site, "/posts/", "light")
    try:
        pid = page.evaluate(
            "async () => (await (await fetch('/api/posts?closed=1')).json()).posts"
            ".find(p => p.title === 'Spring launch thread').id"
        )
        page.goto(f"{site[0]}/posts/?post={pid}")
        panel = page.get_by_role("complementary", name="Spring launch thread")
        panel.wait_for(timeout=10_000)
        assert panel.is_visible()
        assert not problems
    finally:
        page.context.close()


def test_the_settings_page_shows_the_theme_session_and_rules(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = open_page(browser, site, "/settings/", "light")
    try:
        main = page.get_by_role("main")
        assert main.get_by_text("Source: access-jwt").is_visible()
        assert main.get_by_text("Signed in as").is_visible()
        for label in ("Awaiting you", "Scheduled", "Published", "Missed", "Cancelled"):
            assert main.locator("[data-status]", has_text=label).count() >= 1, label
        assert main.locator("[data-platform]").count() >= 1
        main.get_by_role("radio", name="Dark").click()
        assert page.evaluate("document.documentElement.classList.contains('dark')")
        main.get_by_role("radio", name="Light").click()
        assert not page.evaluate("document.documentElement.classList.contains('dark')")
        assert page.evaluate("localStorage.length") == 1  # only the theme
    finally:
        page.context.close()


def test_g_chords_go_to_pages_and_never_fire_while_typing(
    browser: Any, site: tuple[str, str]
) -> None:
    page, problems = open_page(browser, site, "/", "light")
    try:
        for keys, path in (("gn", "/needs-you/"), ("gp", "/posts/"), ("gs", "/settings/")):
            page.keyboard.press(keys[0])
            page.keyboard.press(keys[1])
            page.wait_for_url(f"**{path}")
        # Typing in a field must not navigate: add a field, focus it and type a chord.
        page.evaluate("document.body.insertAdjacentHTML('beforeend', '<input id=t aria-label=t>')")
        page.focus("#t")
        page.keyboard.type("gc")
        page.wait_for_timeout(200)
        assert page.url.endswith("/settings/")
        # Switching them off in Settings stops the chords too.
        page.evaluate("document.getElementById('t').remove()")
        page.get_by_role("checkbox", name="Single-key shortcuts").uncheck()
        page.locator("body").click(position={"x": 700, "y": 5})
        page.keyboard.press("g")
        page.keyboard.press("c")
        page.wait_for_timeout(200)
        assert page.url.endswith("/settings/")
        assert not problems
    finally:
        page.context.close()


@pytest.mark.parametrize("scheme", SCHEMES)
def test_the_rail_collapses_remembers_itself_and_keeps_names_and_tooltips(
    browser: Any, site: tuple[str, str], scheme: str
) -> None:
    page, problems = open_page(browser, site, "/", scheme)
    try:
        trigger = page.get_by_role("button", name="Toggle navigation")
        assert trigger.get_attribute("aria-expanded") == "true"
        page.keyboard.press("[")
        page.wait_for_selector("[data-slot='sidebar'][data-state='collapsed']")
        assert trigger.get_attribute("aria-expanded") == "false"
        assert page.evaluate("localStorage.getItem('brandcal-sidebar')") == "collapsed"
        page.mouse.move(700, 450)
        page.wait_for_timeout(350)  # the rail animates its width
        shot(page, f"next-calendar-rail-{scheme}")
        # Icon-only items still have a name, and a target of at least 40 px.
        link = page.get_by_role("navigation", name="Primary").get_by_role("link", name="Posts")
        box = link.bounding_box()
        assert box and box["width"] >= 40 and box["height"] >= 40
        # The avatar is a focusable button with the identity in its name.
        # Reached by keyboard (Tab), so the tooltip shows on focus as well as on hover.
        for _ in range(30):
            page.keyboard.press("Tab")
            if page.evaluate(
                "(document.activeElement.getAttribute('aria-label') || '')"
                ".startsWith('Signed in as')"
            ):
                break
        else:
            raise AssertionError("the avatar button is not in the tab order")
        tip = page.locator("[data-slot='tooltip-content'][data-open]")
        tip.wait_for(timeout=3_000)
        assert "access-jwt" in tip.inner_text()
        # A reload keeps the rail collapsed; ctrl+B opens it again.
        page.reload()
        page.wait_for_selector("[data-slot='sidebar'][data-state='collapsed']")
        page.keyboard.press("Control+b")
        page.wait_for_selector("[data-slot='sidebar'][data-state='expanded']")
        assert not problems
    finally:
        page.context.close()


def test_on_a_phone_the_sidebar_is_a_sheet_with_focus_trapped_and_returned(
    browser: Any, site: tuple[str, str]
) -> None:
    page, problems = open_page(browser, site, "/", "light", size=PHONE)
    try:
        assert page.locator("[data-slot='sidebar-container']").count() == 0
        trigger = page.get_by_role("button", name="Toggle navigation")
        trigger.focus()
        trigger.click()
        dialog = page.get_by_role("dialog")
        dialog.wait_for(timeout=5_000)
        page.wait_for_timeout(350)
        shot(page, "next-calendar-mobile-sheet-light")
        for _ in range(12):  # the trap keeps focus inside the sheet
            page.keyboard.press("Tab")
            page.wait_for_timeout(60)  # focus guards hand focus back asynchronously
            assert dialog.evaluate("el => el.contains(document.activeElement)")
        if axe_available():
            axe_report(page, "next-calendar-mobile-sheet-light")
        for _ in range(3):  # an open tooltip takes the first Escape (WCAG 1.4.13)
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            if not dialog.is_visible():
                break
        dialog.wait_for(state="hidden", timeout=5_000)
        assert page.evaluate("document.activeElement.getAttribute('aria-label')") == (
            "Toggle navigation"
        )
        # Choosing a page closes the sheet.
        trigger.click()
        dialog.get_by_role("link", name=re.compile("^Settings")).click()
        page.wait_for_url("**/settings/")
        dialog.wait_for(state="hidden", timeout=5_000)
        assert not problems
    finally:
        page.context.close()


@pytest.mark.parametrize("path", list(ROUTES))
def test_no_horizontal_scroll_at_320_px(browser: Any, site: tuple[str, str], path: str) -> None:
    page, _ = open_page(browser, site, path, "light", size={"width": 320, "height": 800})
    try:
        assert page.evaluate("document.documentElement.scrollWidth") <= 320
    finally:
        page.context.close()


def test_a_focused_control_is_never_hidden_behind_the_sticky_bar(
    browser: Any, site: tuple[str, str]
) -> None:
    page, _ = open_page(browser, site, "/settings/", "light", size={"width": 1440, "height": 420})
    try:
        hidden = page.evaluate(
            """() => {
              const out = [];
              for (const el of document.querySelectorAll('main a[href], main button, main input')) {
                el.focus();
                const r = el.getBoundingClientRect();
                const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
                if (!top || !(el === top || el.contains(top) || top.contains(el))) {
                  out.push(el.outerHTML.slice(0, 80));
                }
              }
              return out;
            }"""
        )
        assert hidden == []
    finally:
        page.context.close()


def test_session_errors_show_the_code_the_message_and_the_next_step(
    browser: Any, site: tuple[str, str]
) -> None:
    url, _ = site  # no identity header: the server refuses /api/session
    context = browser.new_context(viewport=SIZE)
    page = context.new_page()
    try:
        page.goto(f"{url}/")
        alert = page.get_by_role("alert").filter(has_text="What to do:")  # not the route announcer
        alert.first.wait_for(timeout=10_000)
        text = alert.first.inner_text()
        assert any(code in text for code in ("IDENTITY_UNVERIFIED", "IDENTITY_UNMAPPED")), text
        assert page.locator("[data-error-code]").first.is_visible()
    finally:
        context.close()


@pytest.mark.parametrize("scheme", SCHEMES)
def test_the_dev_server_shows_a_permanent_red_read_only_banner(
    browser: Any, dev_site: tuple[str, str], scheme: str
) -> None:
    page, problems = open_page(browser, dev_site, "/", scheme)
    try:
        banner = page.locator("[data-dev-banner]")
        banner.wait_for(timeout=10_000)
        assert banner.get_attribute("role") == "status"
        text = banner.inner_text()
        assert "unverified and read-only" in text and "IDENTITY_UNVERIFIED" in text
        assert banner.get_by_role("button").count() == 0  # never dismissible
        # The sidebar and the sticky bar start below the banner, so nothing is covered.
        banner_box = banner.bounding_box()
        assert banner_box
        bar_top = page.get_by_role("banner").bounding_box()
        assert bar_top and bar_top["y"] >= banner_box["y"] + banner_box["height"] - 1
        footer = page.locator("[data-sidebar='footer']").inner_text()
        assert "dev-unverified" in footer
        shot(page, f"next-dev-banner-{scheme}")
        if axe_available():
            axe_report(page, f"next-dev-banner-{scheme}")
        assert not problems
    finally:
        page.context.close()


@pytest.mark.skipif(not axe_available(), reason="web/node_modules/axe-core is not installed")
@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("path", list(ROUTES))
def test_axe_report_for_each_route(
    browser: Any, site: tuple[str, str], path: str, scheme: str
) -> None:
    """Writes the findings to build/ui-shots/ and fails on any violation."""
    page, _ = open_page(browser, site, path, scheme)
    ids = axe_report(page, f"next-{ROUTES[path]}-{scheme}")
    page.context.close()
    print(f"axe {ROUTES[path]} {scheme}: {', '.join(ids) or 'no violations'}")

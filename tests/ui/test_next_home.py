"""The new UI at `/` and the MVP at `/mvp/` load cleanly under the CSP (N0).

Needs Playwright and chromium (see test_screens.py). Zero console errors, zero page errors and
zero `securitypolicyviolation` events, in light and dark. Shots go to build/ui-shots/. The axe
run is advisory: it reports violations but does not fail the build yet.
"""

from __future__ import annotations

import json
import threading
import warnings
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
WATCH_CSP = (
    "window.__csp = [];"
    "document.addEventListener('securitypolicyviolation',"
    " e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));"
)


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, str]]:
    home = tmp_path_factory.mktemp("demo-next") / "home"
    load_demo().build(home, WEEK)
    signer = Signer()
    verifier = Verifier(TEAM, AUD, 5, fetch=FakeJwks(signer))
    server = serve.make_server(home, load_config(home), 0, verifier)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", signer.token(claims())
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


def open_page(browser: Any, site: tuple[str, str], path: str, scheme: str) -> tuple[Any, list[str]]:
    """The page at ``path`` in the colour scheme, with every console error and page error."""
    url, token = site
    context = browser.new_context(
        viewport=SIZE,
        color_scheme=scheme,
        reduced_motion="reduce",
        extra_http_headers={"Cf-Access-Jwt-Assertion": token},
    )
    context.add_init_script(WATCH_CSP)
    problems: list[str] = []
    page = context.new_page()
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    # The MVP shows the demo week only when asked for it; the demo data is pinned to WEEK.
    page.goto(f"{url}{path}" if path == "/" else f"{url}{path}?view=week&date={WEEK.isoformat()}")
    if path == "/":
        page.wait_for_selector("[data-status]", timeout=10_000)
        page.get_by_text("Signed in as").wait_for(timeout=10_000)
        assert page.evaluate("document.documentElement.classList.contains('dark')") == (
            scheme == "dark"
        )
    else:
        page.wait_for_selector("[data-ready]", timeout=10_000)
        page.wait_for_selector(".card", timeout=10_000)
    page.wait_for_timeout(300)  # let late errors and violations arrive
    return page, problems


@pytest.mark.parametrize("scheme", SCHEMES)
@pytest.mark.parametrize("path", ["/", "/mvp/"])
def test_page_loads_with_no_console_errors_or_csp_violations(
    browser: Any, site: tuple[str, str], path: str, scheme: str
) -> None:
    page, problems = open_page(browser, site, path, scheme)
    name = "next-home" if path == "/" else "mvp-home"
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{name}-{scheme}.png"), full_page=True)
    violations = page.evaluate("window.__csp")
    page.context.close()
    assert not problems, problems
    assert violations == []


def test_the_home_page_shows_the_session_status_chips_and_platforms(
    browser: Any, site: tuple[str, str]
) -> None:
    page, problems = open_page(browser, site, "/", "light")
    try:
        assert page.get_by_role("heading", name="brandcal", level=1).is_visible()
        for label in ("Draft", "Awaiting you", "Scheduled", "Published", "Failed"):
            assert page.locator("[data-status]", has_text=label).count() == 1, label
        for name in ("LinkedIn", "X", "Instagram", "YouTube", "Bluesky"):
            assert page.locator("[data-platform]", has_text=name).count() == 1, name
        assert page.get_by_role("button", name="Review posts").is_visible()
        assert page.get_by_text("Source: access-jwt").is_visible()
        assert not problems
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
        alert = page.get_by_role("alert").filter(has_text="Next:")  # not Next's route announcer
        alert.wait_for(timeout=10_000)
        text = alert.inner_text()
        assert "Failed" in text and "Next:" in text
        assert any(code in text for code in ("IDENTITY_UNVERIFIED", "IDENTITY_UNMAPPED"))
    finally:
        context.close()


@pytest.mark.skipif(not axe_available(), reason="web/node_modules/axe-core is not installed")
@pytest.mark.parametrize("scheme", SCHEMES)
def test_axe_report_for_the_home_page(browser: Any, site: tuple[str, str], scheme: str) -> None:
    """Advisory: writes the findings to build/ui-shots/ and warns; it does not fail yet."""
    page, _ = open_page(browser, site, "/", scheme)
    found = run_axe(page)
    page.context.close()
    SHOTS.mkdir(parents=True, exist_ok=True)
    (SHOTS / f"axe-next-home-{scheme}.json").write_text(
        json.dumps(found, indent=2) + "\n", encoding="utf-8"
    )
    if found["violations"]:
        ids = ", ".join(f"{v['id']} x{v['count']}" for v in found["violations"])
        warnings.warn(f"axe ({scheme}): {ids}", stacklevel=1)
    assert isinstance(found["violations"], list)

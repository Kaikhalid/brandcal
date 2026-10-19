"""Screenshots of the read-only views against the fake demo home (UI_SPEC 7).

Advisory: needs Playwright and its chromium (`pip install -e ".[dev,crypto,ui-test]"`, then
`python -m playwright install chromium`). Shots go to build/ui-shots/ (git-ignored).
"""

from __future__ import annotations

import importlib.util
import threading
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
pytest.importorskip("cryptography")

from jwt_env import AUD, TEAM, FakeJwks, Signer, claims  # noqa: E402

from brandcal import serve  # noqa: E402
from brandcal.config import load_config  # noqa: E402
from brandcal.identity import Verifier  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "build" / "ui-shots"
WEEK = date(2026, 3, 9)  # a Monday; the demo and the views are pinned to it
SIZE = {"width": 1440, "height": 900}
PANEL_POST = "launch-thread"


def load_demo() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "make_demo_home", ROOT / "scripts/make_demo_home.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    home = tmp_path_factory.mktemp("demo") / "home"
    load_demo().build(home, WEEK)
    signer = Signer()
    verifier = Verifier(TEAM, AUD, 5, fetch=FakeJwks(signer))
    server = serve.make_server(home, load_config(home), 0, verifier)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    server.app.origins, server.app.hosts = [origin], {origin.split("//")[1]}  # type: ignore[attr-defined]
    serve_token = signer.token(claims())
    yield f"http://127.0.0.1:{server.server_address[1]}|{serve_token}"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def browser_page(base_url: str) -> Iterator[tuple[Any, str]]:
    url, token = base_url.split("|")
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport=SIZE,
            extra_http_headers={"Cf-Access-Jwt-Assertion": token},
            reduced_motion="reduce",
        )
        yield context, url
        browser.close()


def open_view(context: Any, url: str, query: str, theme: str) -> tuple[Any, list[str]]:
    """A page on the given view in the given theme, plus the console errors it collected."""
    problems: list[str] = []
    page = context.new_page()
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    page.add_init_script(
        "window.__csp = [];"
        "document.addEventListener('securitypolicyviolation',"
        " e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));"
    )
    page.goto(f"{url}/?{query}")
    try:
        page.wait_for_selector("[data-ready]", timeout=10_000)
        page.wait_for_selector(".card", timeout=10_000)
    except sync_api.TimeoutError:
        pytest.fail(
            f"no cards; console: {problems}; refusal: {page.locator('#error').inner_text()}"
        )
    page.get_by_role("radio", name=theme.capitalize()).click()
    assert page.evaluate("document.documentElement.dataset.theme") == theme
    assert page.evaluate("localStorage.getItem('brandcal-theme')") == theme
    page.wait_for_timeout(350)  # let the theme transition settle
    return page, problems


def finish(page: Any, problems: list[str], name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / name))
    assert not problems, problems
    assert page.evaluate("window.__csp") == []
    page.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_week_view(browser_page: tuple[Any, str], theme: str) -> None:
    page, problems = open_view(*browser_page, f"view=week&date={WEEK.isoformat()}", theme)
    assert page.locator(".card").count() >= 10
    statuses = {c.get_attribute("data-status") for c in page.locator("#calendar .card").all()}
    assert {"pending_approval", "changes_requested", "approved", "missed", "published"} <= statuses
    assert page.locator("#needs .need-item").count() >= 3
    finish(page, problems, f"week-{theme}.png")


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_month_view(browser_page: tuple[Any, str], theme: str) -> None:
    page, problems = open_view(*browser_page, f"view=month&date={WEEK.isoformat()}", theme)
    assert page.locator("#calendar .day").count() >= 28
    finish(page, problems, f"month-{theme}.png")


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_panel_open(browser_page: tuple[Any, str], theme: str) -> None:
    page, problems = open_view(*browser_page, f"view=week&date={WEEK.isoformat()}", theme)
    page.locator("#calendar .card", has_text="Spring launch thread").click()
    page.wait_for_selector("#panel[data-open='true'] .count")
    assert page.locator("#panel .cli").count() >= 1
    assert "/ 280" in page.locator("#panel").inner_text()
    page.wait_for_timeout(400)
    finish(page, problems, f"panel-{theme}.png")


def test_escape_closes_the_panel_and_returns_focus(browser_page: tuple[Any, str]) -> None:
    page, problems = open_view(*browser_page, f"view=week&date={WEEK.isoformat()}", "light")
    card = page.locator("#calendar .card", has_text="Planning day at Example Co")
    card.focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("#panel[data-open='true']")
    assert "Example Co team around a table" in page.locator("#panel").inner_text()
    page.keyboard.press("Escape")
    page.wait_for_selector("#panel[data-open='false']", state="attached")
    assert card.evaluate("el => el === document.activeElement")
    assert not problems
    page.close()


def test_refusals_and_disabled_buttons_show_code_and_next(browser_page: tuple[Any, str]) -> None:
    page, problems = open_view(*browser_page, f"view=week&date={WEEK.isoformat()}", "light")
    page.locator("#calendar .card", has_text="Partner announcement").click()
    page.wait_for_selector("#panel[data-open='true'] .action")
    text = page.locator("#panel").inner_text()
    assert "EDIT_WHILE_CLAIMED" in text and "What to do:" in text
    # A claim disables Edit and Cancel; the core still allows a time change and a note.
    enabled = page.locator("#panel button.action:not([disabled])").all_inner_texts()
    assert sorted(enabled) == ["Add a note", "Change time"]
    assert not problems
    page.close()


def open_action(context: Any, url: str, action: str) -> tuple[Any, list[str]]:
    """The panel of a pending post with the confirm dialog of one action open."""
    page, problems = open_view(context, url, f"view=week&date={WEEK.isoformat()}", "light")
    page.locator("#calendar .card[data-status='pending_approval']").last.click()
    page.wait_for_selector(f"#panel[data-open='true'] [data-action='{action}']:not([disabled])")
    page.locator(f"#panel [data-action='{action}']").click()
    page.wait_for_selector("dialog[open]")
    return page, problems


def test_approve_confirm_dialog(browser_page: tuple[Any, str]) -> None:
    page, problems = open_action(*browser_page, "approve")
    text = page.locator("dialog[open]").inner_text()
    assert "brandcal approve" in text and "fingerprint" in text
    page.keyboard.press("Escape")  # cancels, and the panel stays open
    assert page.locator("dialog[open]").count() == 0
    assert page.locator("#panel[data-open='true']").count() == 1
    assert page.evaluate("document.activeElement.dataset.action") == "approve"
    page.locator("#panel [data-action='approve']").click()
    page.wait_for_selector("dialog[open]")
    page.wait_for_timeout(100)
    finish(page, problems, "approve-confirm-light.png")


def test_request_changes_form(browser_page: tuple[Any, str]) -> None:
    page, problems = open_action(*browser_page, "request-changes")
    assert page.locator("dialog[open] textarea[required]").count() == 3
    finish(page, problems, "request-changes-light.png")


def test_confirmed_approve_records_and_the_panel_updates(browser_page: tuple[Any, str]) -> None:
    page, problems = open_action(*browser_page, "approve")
    page.locator("dialog[open] button[type=submit]").click()
    page.wait_for_selector("dialog[open]", state="detached")
    page.wait_for_selector("#panel .status[data-status='approved']")
    assert "Approved" in page.locator("#panel").inner_text()
    assert "Approve: done" in page.locator("#notice").inner_text()
    assert not problems
    page.close()

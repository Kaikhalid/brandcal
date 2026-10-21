# ruff: noqa: F811
# (the fixtures come from test_next_home.py by name, the usual pytest way to share them)
"""The write actions of the new UI (N3): confirm dialogs, notices, refusals and stale views.

Same helpers as test_next_home.py, but these tests write, so the module builds its own demo home
and serves it twice: to a verified approver (full writes) and with --dev-unverified (read-only).
Every send is checked against the API afterwards: the post, and an event with via console and the
verified identity in GET /api/events. Shots go to build/ui-shots/next-<name>-<theme>.png; the axe
runs are advisory (build/ui-shots/axe-next-*.json plus a warning).
"""

from __future__ import annotations

import json
import re
import threading
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from axe_helper import axe_available

expect = pytest.importorskip("playwright.sync_api").expect
pytest.importorskip("cryptography")

from jwt_env import APPROVER, AUD, TEAM, FakeJwks, Signer, claims  # noqa: E402
from test_next_home import (  # noqa: E402, F401  (fixtures are used by name)
    SCHEMES,
    axe_report,
    browser,
    open_page,
    shot,
)
from test_screens import WEEK, load_demo  # noqa: E402

from brandcal import posts, serve  # noqa: E402
from brandcal.config import display_tz, load_config  # noqa: E402
from brandcal.db import open_db  # noqa: E402
from brandcal.identity import Verifier  # noqa: E402

DATE = WEEK.isoformat()
WRITER = "writer-1"
FUTURE = "2027-03-02T09:00:00+01:00/2027-03-02T10:00:00+01:00"


@pytest.fixture(scope="module")
def home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("demo-writes") / "home"
    load_demo().build(path, WEEK)
    return path


@pytest.fixture(scope="module")
def site(home: Path) -> Iterator[tuple[str, str]]:
    signer = Signer()
    verifier = Verifier(TEAM, AUD, 5, fetch=FakeJwks(signer))
    server = serve.make_server(home, load_config(home), 0, verifier)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    # The browser sends Origin and Host of the test server, not the configured port.
    server.app.origins, server.app.hosts = [origin], {origin.split("//")[1]}  # type: ignore[attr-defined]
    yield origin, signer.token(claims())
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def dev_site(home: Path) -> Iterator[tuple[str, str]]:
    server = serve.make_server(home, load_config(home), 0, None, dev=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", ""
    server.shutdown()
    server.server_close()


# -- helpers ---------------------------------------------------------------------------------


def api(site: tuple[str, str], path: str) -> Any:
    headers = {"Cf-Access-Jwt-Assertion": site[1]} if site[1] else {}
    with urllib.request.urlopen(urllib.request.Request(site[0] + path, headers=headers)) as res:
        return json.load(res)


def pid_for(site: tuple[str, str], title: str) -> str:
    found = [p["id"] for p in api(site, "/api/posts?closed=1")["posts"] if p["title"] == title]
    assert len(found) == 1, (title, found)
    return str(found[0])


def new_post(home: Path, slug: str, title: str) -> str:
    """A pending post made by the writer through the core, like the CLI would."""
    cfg = load_config(home)
    conn = open_db(home / "brand.db", display_tz(cfg))
    try:
        out = posts.add_post(
            conn,
            WRITER,
            "writer",
            cfg,
            {
                "slug": slug,
                "platform": "linkedin",
                "post_type": "text",
                "window": FUTURE,
                "title": title,
                "parts": [{"text": f"{title}. Example Co will say more soon."}],
            },
        )
        return str(out["id"])
    finally:
        conn.close()


def writer_edits(home: Path, post: str, text: str) -> None:
    """The writer changes part 1 through the core, as `brandcal part edit` would."""
    cfg = load_config(home)
    conn = open_db(home / "brand.db", display_tz(cfg))
    try:
        posts.part_edit(conn, WRITER, "writer", cfg, post, 1, text)
    finally:
        conn.close()


def console_events(site: tuple[str, str], pid: str) -> list[dict[str, Any]]:
    events = api(site, f"/api/events?post={pid}")["events"]
    return [
        e
        for e in events
        if isinstance(e["detail"], dict)
        and e["detail"].get("via") == "console"
        and e["detail"].get("identity") == APPROVER
    ]


def open_post(
    browser: Any, site: tuple[str, str], pid: str, scheme: str = "light"
) -> tuple[Any, list[str]]:
    page, problems = open_page(
        browser, site, "/", scheme, query=f"?view=week&date={DATE}&post={pid}"
    )
    page.locator("aside[data-post-panel] ul [data-action-button]").first.wait_for(timeout=10_000)
    return page, problems


def button(page: Any, action: str) -> Any:
    return page.locator(f'aside[data-post-panel] [data-action-button="{action}"]')


def open_dialog(page: Any, action: str) -> Any:
    button(page, action).click()
    dialog = page.locator(f'[data-action-dialog="{action}"]')
    dialog.wait_for(timeout=10_000)
    return dialog


def active(page: Any) -> str:
    """The focused element, described by name, id or text."""
    found: str = page.evaluate(
        "(() => { const e = document.activeElement;"
        " return e.name || e.dataset.actionButton || e.id || e.textContent.trim(); })()"
    )
    return found


def focused(page: Any, expected: str) -> None:
    """The dialog takes focus as it opens; poll for it rather than race it."""
    for _ in range(40):
        if active(page) == expected:
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"focus is on {active(page)!r}, expected {expected!r}")


def confirm(dialog: Any) -> None:
    dialog.locator("button[type=submit]").click()


def done(page: Any, dialog: Any, text: str) -> None:
    """The dialog closed, and the notice (a polite live region) says what happened."""
    expect(dialog).to_have_count(0)
    notice = page.locator("[data-notice]")
    expect(notice).to_have_attribute("role", "status")
    expect(notice).to_have_attribute("aria-live", "polite")
    expect(notice).to_contain_text(text)


def recorded(site: tuple[str, str], pid: str, before: int) -> None:
    """One more event with via console and the verified identity."""
    assert len(console_events(site, pid)) == before + 1


def clean(page: Any, problems: list[str], refused: str = "") -> None:
    """No CSP violation and no console error, except the browser's own line for a refusal the
    test provoked on purpose (``refused`` is that HTTP status)."""
    assert page.evaluate("window.__csp") == []
    left = [p for p in problems if not (refused and refused in p)]
    assert not left, left
    page.context.close()


def axe_if_available(page: Any, name: str) -> None:
    if axe_available():
        axe_report(page, name)


# -- dialogs: focus, CLI line, shots and axe -------------------------------------------------


@pytest.mark.parametrize("scheme", SCHEMES)
def test_dialogs_open_with_the_right_focus_and_say_what_they_do(
    browser: Any, site: tuple[str, str], home: Path, scheme: str
) -> None:
    pid = new_post(home, f"dialogs-{scheme}", f"Dialog check {scheme}")
    page, problems = open_post(browser, site, pid, scheme)
    # name -> (the focus on opening, words the dialog must show, the file in build/ui-shots)
    cases = {
        "approve": ("Go back", "brandcal approve", "approve-dialog"),
        "request-changes": ("what", "All three fields are required.", "request-changes"),
        "cancel": ("kind", "cannot be undone", "cancel-dialog"),
    }
    for action, (focus, words, name) in cases.items():
        dialog = open_dialog(page, action)
        text = dialog.inner_text()
        focused(page, focus)
        assert words in text
        assert "Agent equivalent (CLI)" in text
        assert "This console action records channel console with your verified identity." in text
        assert dialog.locator("code[data-cli]").inner_text().startswith("brandcal")
        page.wait_for_timeout(150)
        shot(page, f"next-{name}-{scheme}")
        axe_if_available(page, f"next-dialog-{action}-{scheme}")
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
        expect(button(page, action)).to_be_focused()
        assert page.locator("aside[data-post-panel]").count() == 1  # Esc closed only the dialog
    # The cancel dialog is an alert dialog, with the failed tone, an icon and the word.
    open_dialog(page, "cancel")
    expect(page.get_by_role("alertdialog")).to_have_count(1)
    expect(page.get_by_role("button", name="Cancel post")).to_be_visible()
    page.keyboard.press("Escape")
    # The edit dialog: a field per part, the server's warning first, "Move to…".
    planning = pid_for(site, "Planning day at Example Co")
    page.goto(f"{site[0]}/?view=week&date={DATE}&post={planning}")
    button(page, "edit").wait_for(timeout=10_000)
    dialog = open_dialog(page, "edit")
    focused(page, "part-1")
    says = dialog.locator("[data-slot$=description]").inner_text()
    edit = next(a for a in api(site, f"/api/posts/{planning}")["actions"] if a["id"] == "edit")
    assert says.startswith(edit["warning"])
    assert dialog.get_by_text("Move to…").count() == 1
    assert dialog.get_by_label(re.compile("Alt text, file 1")).count() == 1
    page.wait_for_timeout(150)
    shot(page, f"next-edit-dialog-{scheme}")
    axe_if_available(page, f"next-dialog-edit-{scheme}")
    page.keyboard.press("Escape")
    clean(page, problems)


def test_focus_is_trapped_in_the_dialog(browser: Any, site: tuple[str, str], home: Path) -> None:
    page, problems = open_post(browser, site, new_post(home, "trap", "Trap check"))
    dialog = open_dialog(page, "request-changes")
    for _ in range(12):
        page.keyboard.press("Tab")
        page.wait_for_timeout(50)  # a focus guard hands focus straight back inside
        assert page.evaluate("!!document.activeElement.closest('[role=dialog]')")
    dialog.get_by_role("button", name="Go back").click()
    expect(dialog).to_have_count(0)
    expect(button(page, "request-changes")).to_be_focused()
    clean(page, problems)


def test_the_cli_line_has_a_copy_button_that_says_copied(
    browser: Any, site: tuple[str, str], home: Path
) -> None:
    page, problems = open_post(browser, site, new_post(home, "copy", "Copy check"))
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.locator("aside[data-post-panel]").get_by_role(
        "button", name="Agent equivalents (CLI)"
    ).click()
    row = page.locator('aside[data-post-panel] li[data-cli-for="approve"]')
    row.get_by_role("button", name="Copy the Approve command").click()
    expect(row.locator("[role=status]")).to_have_text("Copied")
    assert page.evaluate("navigator.clipboard.readText()").startswith("brandcal approve")
    clean(page, problems)


# -- the seven writes ------------------------------------------------------------------------


def test_approve_sends_and_the_panel_moves_on(browser: Any, site: tuple[str, str]) -> None:
    pid = pid_for(site, "How we plan a launch")
    before = len(console_events(site, pid))
    page, problems = open_post(browser, site, pid)
    dialog = open_dialog(page, "approve")
    focused(page, "Go back")
    assert "Approve version 1 (fingerprint" in dialog.inner_text()
    confirm(dialog)
    done(page, dialog, "Approve: done. How we plan a launch is now Approved, version 1.")
    recorded(site, pid, before)
    assert api(site, f"/api/posts/{pid}")["status"] == "approved"
    # The panel was reloaded: no Approve button, and the focus is on the heading that remains.
    expect(button(page, "approve")).to_have_count(0)
    expect(page.locator("#panel-title")).to_be_focused()
    expect(page.locator("aside[data-post-panel]")).to_contain_text("console (verified:")
    shot(page, "next-notice-light")
    clean(page, problems)


def test_the_notice_in_the_dark_theme(browser: Any, site: tuple[str, str], home: Path) -> None:
    pid = new_post(home, "notice-dark", "Notice dark")
    page, problems = open_post(browser, site, pid, "dark")
    dialog = open_dialog(page, "note")
    dialog.get_by_label("Note (required)").fill("Checked the wording with the team.")
    confirm(dialog)
    done(page, dialog, "Add a note: done. Notice dark is now")
    page.wait_for_timeout(200)
    shot(page, "next-notice-dark")
    page.get_by_role("button", name="Dismiss notice").click()
    expect(page.get_by_role("button", name="Dismiss notice")).to_have_count(0)
    clean(page, problems)


def test_request_changes_needs_all_three_fields_and_then_sends(
    browser: Any, site: tuple[str, str]
) -> None:
    pid = pid_for(site, "Product walkthrough")
    before = len(console_events(site, pid))
    page, problems = open_post(browser, site, pid)
    sent: list[str] = []
    page.on("request", lambda r: sent.append(r.url) if r.method == "POST" else None)
    dialog = open_dialog(page, "request-changes")
    assert dialog.locator("textarea[required]").count() == 3
    dialog.get_by_label("What is wrong").fill("The length is wrong.")
    dialog.get_by_label("Where it is").fill("Part 1")
    confirm(dialog)  # the third field is empty: nothing is sent
    page.wait_for_timeout(300)
    assert sent == []
    expect(dialog).to_have_count(1)
    assert len(console_events(site, pid)) == before
    dialog.get_by_label("What the writer should do").fill("Say it in one sentence.")
    confirm(dialog)
    done(page, dialog, "Request changes: done. Product walkthrough is now Changes requested")
    recorded(site, pid, before)
    assert api(site, f"/api/posts/{pid}")["status"] == "changes_requested"
    clean(page, problems)


def test_reschedule_moves_the_window_through_move_to(browser: Any, site: tuple[str, str]) -> None:
    pid = pid_for(site, "Newsletter reminder")
    before = len(console_events(site, pid))
    page, problems = open_post(browser, site, pid)
    assert button(page, "reschedule").inner_text() == "Approve new time"
    dialog = open_dialog(page, "reschedule")
    expect(dialog.get_by_label("Day")).to_be_focused()  # the first field
    raw = dialog.get_by_label(re.compile("^New window"))
    sent = dialog.locator("[data-window-sent]")
    # The window text drives the day and times ...
    raw.fill("2027-03-04T10:00:00+01:00/2027-03-04T11:00:00+01:00")
    expect(dialog.get_by_label("Day")).to_have_value("2027-03-04")
    expect(dialog.get_by_label("Start")).to_have_value("10:00")
    # ... and they drive the text, which is printed before anything is sent.
    dialog.get_by_label("Day").fill("2027-03-05")
    dialog.get_by_label("Start").fill("13:30")
    dialog.get_by_label("End").fill("14:30")
    want = "2027-03-05T13:30:00+01:00/2027-03-05T14:30:00+01:00"
    expect(raw).to_have_value(want)
    expect(sent).to_have_text(want)
    confirm(dialog)
    done(page, dialog, "Approve new time: done. Newsletter reminder is now Approved")
    recorded(site, pid, before)
    assert api(site, f"/api/posts/{pid}")["window"] == want
    clean(page, problems)


def test_cancel_closes_the_post(browser: Any, site: tuple[str, str]) -> None:
    pid = pid_for(site, "Weekend note")
    before = len(console_events(site, pid))
    page, problems = open_post(browser, site, pid)
    dialog = open_dialog(page, "cancel")
    focused(page, "kind")
    dialog.get_by_label("What is cancelled").select_option("idea")
    dialog.get_by_label("Reason").fill("Not needed this week.")
    confirm(dialog)
    done(page, dialog, "Cancel: done. Weekend note is now Cancelled")
    recorded(site, pid, before)
    assert api(site, f"/api/posts/{pid}")["status"] == "cancelled"
    expect(page.locator("aside[data-post-panel]")).to_contain_text(
        "This post is closed, so there is nothing to do."
    )
    expect(page.locator("#panel-title")).to_be_focused()
    clean(page, problems)


def test_edit_sends_only_what_changed(browser: Any, site: tuple[str, str]) -> None:
    pid = pid_for(site, "Planning day at Example Co")
    before_version = api(site, f"/api/posts/{pid}")["content_version"]
    before = len(console_events(site, pid))
    page, problems = open_post(browser, site, pid)
    bodies: list[str] = []
    page.on(
        "request",
        lambda r: bodies.append(r.post_data or "") if r.method == "POST" else None,
    )
    dialog = open_dialog(page, "edit")
    dialog.get_by_label("Text (required)").fill(
        "Planning day at Example Co. A short and clear line."
    )
    confirm(dialog)
    done(page, dialog, "Edit: done. Planning day at Example Co is now")
    recorded(site, pid, before)
    post = api(site, f"/api/posts/{pid}")
    assert post["content_version"] == before_version + 1
    assert [json.loads(b) for b in bodies] == [
        {
            "fields": {},
            "parts": {"1": "Planning day at Example Co. A short and clear line."},
            "alt_texts": {},
        }
    ]
    expect(page.locator("#panel-title")).to_be_visible()
    expect(button(page, "edit")).to_be_focused()
    clean(page, problems)


def test_submit_sends_a_post_whose_content_changed(
    browser: Any, site: tuple[str, str], home: Path
) -> None:
    pid = pid_for(site, "Launch teaser")
    before = len(console_events(site, pid))
    writer_edits(home, pid, "Something new is landing on Thursday.")
    page, problems = open_post(browser, site, pid)
    dialog = open_dialog(page, "submit")
    focused(page, "Go back")
    confirm(dialog)
    done(page, dialog, "Submit for approval: done. Launch teaser is now")
    recorded(site, pid, before)
    assert api(site, f"/api/posts/{pid}")["status"] == "pending_approval"
    clean(page, problems)


def test_note_adds_a_note(browser: Any, site: tuple[str, str]) -> None:
    pid = pid_for(site, "Reply to partner thread")
    before = len(console_events(site, pid))
    page, problems = open_post(browser, site, pid)
    dialog = open_dialog(page, "note")
    focused(page, "text")
    confirm(dialog)  # empty: not sent
    page.wait_for_timeout(200)
    expect(dialog).to_have_count(1)
    dialog.get_by_label("Note (required)").fill("Waiting for the partner to confirm.")
    confirm(dialog)
    done(page, dialog, "Add a note: done. Reply to partner thread is now")
    recorded(site, pid, before)
    expect(button(page, "note")).to_be_focused()
    clean(page, problems)


# -- refusals --------------------------------------------------------------------------------


def test_a_refused_write_keeps_the_dialog_open_with_the_servers_words(
    browser: Any, site: tuple[str, str], home: Path
) -> None:
    pid = new_post(home, "refused", "Refused check")
    page, problems = open_post(browser, site, pid)
    before = len(api(site, f"/api/events?post={pid}")["events"])
    dialog = open_dialog(page, "request-changes")
    # Blank is not empty to the browser; the server decides, and its words are shown as they are.
    for label in ("What is wrong", "Where it is", "What the writer should do"):
        dialog.get_by_label(label).fill("   ")
    confirm(dialog)
    alert = dialog.locator("[data-error-code]")
    alert.wait_for(timeout=10_000)
    assert alert.get_attribute("role") == "alert"
    assert alert.get_attribute("data-error-code") == "REASON_REQUIRED"
    assert "What to do:" in alert.inner_text()
    expect(dialog.locator("button[type=submit]")).to_be_enabled()
    expect(dialog.locator("button[type=submit]")).not_to_have_attribute("aria-busy", "true")
    assert dialog.count() == 1
    assert len(api(site, f"/api/events?post={pid}")["events"]) == before
    clean(page, problems, "422")


def test_disabled_actions_stay_visible_with_their_refusal(
    browser: Any, site: tuple[str, str]
) -> None:
    pid = pid_for(site, "Partner announcement")
    page, problems = open_post(browser, site, pid)
    page.locator("aside[data-post-panel]").get_by_role(
        "button", name="Agent equivalents (CLI)"
    ).click()
    for action in ("edit", "cancel"):
        b = button(page, action)
        assert b.is_disabled()
        assert b.get_attribute("aria-disabled") == "true"
        text = page.locator(f'aside[data-post-panel] li[data-action-note="{action}"]').inner_text()
        assert "EDIT_WHILE_CLAIMED" in text or "CLAIMED" in text
        assert "What to do:" in text
        cli = page.locator(f'aside[data-post-panel] li[data-cli-for="{action}"]')
        assert "Agent equivalent (CLI)" in cli.inner_text()
    assert button(page, "note").is_enabled()
    clean(page, problems)


def test_a_closed_post_has_nothing_to_do(browser: Any, site: tuple[str, str]) -> None:
    page, problems = open_page(
        browser,
        site,
        "/",
        "light",
        query=f"?view=week&date={DATE}&post={pid_for(site, 'Feature carousel')}",
    )
    expect(page.locator("aside[data-post-panel]")).to_contain_text(
        "This post is closed, so there is nothing to do."
    )
    assert page.locator("aside[data-post-panel] [data-action-button]").count() == 0
    clean(page, problems)


@pytest.mark.parametrize("scheme", SCHEMES)
def test_stale_approval_shows_the_banner_and_records_nothing(
    browser: Any, site: tuple[str, str], home: Path, scheme: str
) -> None:
    pid = new_post(home, f"stale-{scheme}", f"Stale check {scheme}")
    before = len(api(site, f"/api/events?post={pid}")["events"])
    page, problems = open_post(browser, site, pid, scheme)
    dialog = open_dialog(page, "approve")
    # The writer changes the post between opening the dialog and pressing the button.
    writer_edits(home, pid, "A different text, so version 2.")
    events_after_edit = len(api(site, f"/api/events?post={pid}")["events"])
    assert events_after_edit > before
    confirm(dialog)
    expect(dialog).to_have_count(0)
    banner = page.locator("[data-stale-banner]")
    expect(banner).to_have_attribute("role", "alert")
    expect(banner).to_have_text(
        "This post changed (version 1 to 2). Read it again before deciding. Nothing was recorded."
    )
    # Nothing was recorded, the panel shows version 2 and Approve is available again.
    assert len(api(site, f"/api/events?post={pid}")["events"]) == events_after_edit
    assert api(site, f"/api/posts/{pid}")["status"] == "pending_approval"
    assert console_events(site, pid) == []
    expect(page.locator("[data-notice]")).to_have_text("")
    expect(button(page, "approve")).to_be_focused()
    expect(button(page, "approve")).to_be_enabled()
    page.wait_for_timeout(200)
    shot(page, f"next-stale-{scheme}")
    clean(page, problems, "409")


def test_the_dev_unverified_server_refuses_every_write(
    browser: Any, dev_site: tuple[str, str]
) -> None:
    pid = pid_for(dev_site, "Product walkthrough")
    page, problems = open_post(browser, dev_site, pid)
    buttons = page.locator("aside[data-post-panel] [data-action-button]")
    assert buttons.count() >= 4
    for i in range(buttons.count()):
        assert buttons.nth(i).is_disabled()
        assert buttons.nth(i).get_attribute("aria-disabled") == "true"
    rows = page.locator("aside[data-post-panel] li[data-action-note]")
    assert rows.count() == buttons.count()
    for i in range(rows.count()):
        assert "IDENTITY_UNVERIFIED" in rows.nth(i).inner_text()
        assert "What to do:" in rows.nth(i).inner_text()
    assert page.locator("[data-dev-banner]").is_visible()
    # A write attempted anyway is refused by the server, not by the page.
    got = page.evaluate(
        "async (id) => { const r = await fetch('/api/posts/' + id + '/note', {method: 'POST',"
        " headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: 'x'})});"
        " return [r.status, (await r.json()).error.code]; }",
        pid,
    )
    assert got == [401, "IDENTITY_UNVERIFIED"]
    assert page.evaluate("window.__csp") == []
    page.context.close()
    assert [p for p in problems if "401" not in p] == []

"""Write endpoints of `brandcal serve` (UI_SPEC 1.2, 3.3, 4.1, 4.2) and data moved into the API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import test_serve_api as base
from jwt_env import APPROVER, VIEWER
from test_media import png_bytes
from ui_env import CFG, NEW_WINDOW, add_post, cli_approve, open_home, run

from brandcal import actions, posts

env, dev, signer = base.env, base.dev, base.signer  # the module's fixtures, reused as they are
Env = base.Env
WRITES = base.WRITES
seen, counts, approvals, event_detail = base.seen, base.counts, base.approvals, base.event_detail
CHANGES = {"what": "The headline", "where": "First line", "instruction": "Shorten it"}


def path(post: dict[str, Any], endpoint: str) -> str:
    return f"/api/posts/{post['id']}/{endpoint}"


def event_row(home: Path, post_id: str, action: str) -> dict[str, Any]:
    with open_home(home) as (conn, _):
        row = conn.execute(
            "SELECT actor, detail FROM events WHERE post_id = ? AND action = ? ORDER BY id DESC",
            (post_id, action),
        ).fetchone()
        return {"actor": row["actor"], "detail": json.loads(row["detail"] or "{}")}


def assert_console_event(home: Path, post_id: str, action: str) -> None:
    row = event_row(home, post_id, action)
    assert row["actor"] == "approver-1"
    detail = row["detail"]
    assert (detail["identity"], detail["source"], detail["via"]) == (
        APPROVER,
        "access-jwt",
        "console",
    )


# --- happy paths: every write leaves an event with identity, source and via ----------------


def test_approve_event(env: Env) -> None:
    post = add_post(env.home)
    assert env.client.post(path(post, "approve"), seen(env.client, post["id"])).status == 200
    assert_console_event(env.home, post["id"], "approve")


def test_request_changes_event(env: Env) -> None:
    post = add_post(env.home)
    body = {**seen(env.client, post["id"]), **CHANGES}
    assert env.client.post(path(post, "request-changes"), body).status == 200
    assert_console_event(env.home, post["id"], "request-changes")


def test_reschedule_event(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    post = add_post(env.home)
    cli_approve(capsys, env.home, post)
    body = {**seen(env.client, post["id"]), "new_window": NEW_WINDOW}
    assert env.client.post(path(post, "reschedule"), body).status == 200
    assert_console_event(env.home, post["id"], "reschedule")


def test_cancel_event(env: Env) -> None:
    post = add_post(env.home)
    body = {**seen(env.client, post["id"]), "kind": "idea", "reason": "Not needed"}
    assert env.client.post(path(post, "cancel"), body).status == 200
    assert_console_event(env.home, post["id"], "cancel")


def test_note_event(env: Env) -> None:
    post = add_post(env.home)
    assert env.client.post(path(post, "note"), {"text": "Check the date"}).status == 200
    assert_console_event(env.home, post["id"], "note")


def test_edit_makes_a_new_version_and_never_approves(
    env: Env, capsys: pytest.CaptureFixture[str]
) -> None:
    post = add_post(env.home)
    cli_approve(capsys, env.home, post)
    before = approvals(env.home, post["id"])
    body = {"fields": {"first_comment": "Link in the comments"}, "parts": {"1": "Hello again"}}
    res = env.client.post(path(post, "edit"), body)
    assert res.status == 200 and res.body["status"] == "pending_approval"
    assert res.body["version"] == post["version"] + 1
    assert approvals(env.home, post["id"]) == before  # an edit never approves
    shown = env.client.get(f"/api/posts/{post['id']}").body
    assert shown["parts"][0]["text"] == "Hello again"
    assert shown["first_comment"] == "Link in the comments"
    assert_console_event(env.home, post["id"], "edit")


def test_edit_changes_alt_text_and_the_window(env: Env) -> None:
    post = add_post(env.home)
    src = env.home / "pic.png"
    src.write_bytes(png_bytes())
    with open_home(env.home) as (conn, cfg):
        posts.media_add(conn, "writer-1", "writer", cfg, env.home, post["id"], 1, src, "Old alt")
    body = {"fields": {"window": NEW_WINDOW}, "alt_texts": {"1": "A team around a table"}}
    assert env.client.post(path(post, "edit"), body).status == 200
    shown = env.client.get(f"/api/posts/{post['id']}").body
    assert shown["media"][0]["alt_text"] == "A team around a table"
    assert shown["window"] == NEW_WINDOW


def test_edit_refuses_bad_input(env: Env) -> None:
    post = add_post(env.home)
    before = counts(env.home)
    for body in (
        {},
        {"fields": {"status": "approved"}},
        {"parts": {"9": "x"}},
        {"parts": {"a": "x"}},
    ):
        res = env.client.post(path(post, "edit"), body)
        assert res.status == 400 and res.code == "BAD_ARGS", body
    assert counts(env.home) == before


def test_submit_after_changes_were_requested(env: Env) -> None:
    post = add_post(env.home)
    asked = {**seen(env.client, post["id"]), **CHANGES}
    assert env.client.post(path(post, "request-changes"), asked).status == 200
    unchanged = env.client.post(path(post, "submit"))
    assert unchanged.status == 409 and unchanged.code == "BAD_TRANSITION"
    assert env.client.post(path(post, "edit"), {"parts": {"1": "Shorter"}}).status == 200
    res = env.client.post(path(post, "submit"))
    assert res.status == 200 and res.body["status"] == "pending_approval"
    assert_console_event(env.home, post["id"], "submit")


# --- refusals ------------------------------------------------------------------------------


@pytest.mark.parametrize("endpoint", WRITES)
def test_viewer_is_refused_and_nothing_is_written(env: Env, endpoint: str) -> None:
    post = add_post(env.home)
    before = counts(env.home)
    res = env.client.post(path(post, endpoint), seen(env.client, post["id"]), email=VIEWER)
    assert res.status == 403 and res.code == "ROLE_NOT_ALLOWED"
    assert counts(env.home) == before


@pytest.mark.parametrize("endpoint", WRITES)
def test_unverified_and_dev_sessions_are_refused(dev: Env, endpoint: str) -> None:
    post = add_post(dev.home)
    before = counts(dev.home)
    res = dev.client.post(path(post, endpoint), {"text": "x"}, token=None, csrf=None)
    assert res.status == 401 and res.code == "IDENTITY_UNVERIFIED"
    assert counts(dev.home) == before


@pytest.mark.parametrize("endpoint", WRITES)
def test_origin_and_csrf_are_checked_on_every_write(env: Env, endpoint: str) -> None:
    post = add_post(env.home)
    before = counts(env.home)
    for kwargs in ({"origin": "https://evil.example.org"}, {"origin": None}, {"csrf": "wrong"}):
        res = env.client.post(path(post, endpoint), {"text": "x"}, **kwargs)
        assert res.status == 403 and res.code == "BAD_ORIGIN", kwargs
    assert counts(env.home) == before


@pytest.mark.parametrize("missing", ["what", "where", "instruction"])
@pytest.mark.parametrize("blank", [None, "", "   "])
def test_request_changes_needs_each_field(env: Env, missing: str, blank: str | None) -> None:
    post = add_post(env.home)
    body = {**seen(env.client, post["id"]), **CHANGES}
    if blank is None:
        del body[missing]
    else:
        body[missing] = blank
    res = env.client.post(path(post, "request-changes"), body)
    assert res.status == 422 and res.code == "REASON_REQUIRED"
    assert approvals(env.home, post["id"]) == []


@pytest.mark.parametrize("reason", [None, "", "  "])
def test_cancel_needs_a_reason(env: Env, reason: str | None) -> None:
    post = add_post(env.home)
    body = {**seen(env.client, post["id"]), "kind": "idea"}
    if reason is not None:
        body["reason"] = reason
    res = env.client.post(path(post, "cancel"), body)
    assert res.status == 422 and res.code == "REASON_REQUIRED"
    assert approvals(env.home, post["id"]) == []


@pytest.mark.parametrize("stale", [{"version": 9}, {"hash": "f" * 8}, {"window": NEW_WINDOW}])
def test_stale_approve_changes_nothing_and_returns_the_current_post(
    env: Env, stale: dict[str, Any]
) -> None:
    post = add_post(env.home)
    before = counts(env.home)
    res = env.client.post(path(post, "approve"), {**seen(env.client, post["id"]), **stale})
    assert res.status == 409 and res.code == "STALE_APPROVAL"
    assert res.body["current"]["id"] == post["id"]
    assert res.body["current"]["actions"][0]["cli"]
    assert counts(env.home) == before


def test_wrong_state_is_refused(env: Env) -> None:
    post = add_post(env.home)
    assert env.client.post(path(post, "submit")).code == "BAD_TRANSITION"
    body = {**seen(env.client, post["id"]), "new_window": NEW_WINDOW}
    assert env.client.post(path(post, "reschedule"), body).code == "BAD_TRANSITION"
    closed = {**seen(env.client, post["id"]), "kind": "idea", "reason": "r"}
    assert env.client.post(path(post, "cancel"), closed).status == 200
    assert env.client.post(path(post, "edit"), {"parts": {"1": "x"}}).code == "POST_CLOSED"


@pytest.mark.parametrize(
    "argv",
    [("edit", "{id}", "title=Changed"), ("submit", "{id}"), ("note", "{id}", "Hello")],
)
def test_the_cli_still_refuses_the_approver(
    env: Env, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...]
) -> None:
    post = add_post(env.home)
    before = counts(env.home)
    code, out = run(
        capsys, env.home, *[a.format(id=post["id"]) for a in argv], "--as", "approver-1"
    )
    assert code == 4 and out["error"]["code"] == "ROLE_NOT_ALLOWED"
    assert counts(env.home) == before


def test_actions_refuse_an_approver_without_a_verified_identity(env: Env) -> None:
    post = add_post(env.home)
    with open_home(env.home) as (conn, cfg):
        who = actions.Identity("approver-1")
        for call in (
            lambda: actions.edit(conn, cfg, who, post["id"], ["title=x"]),
            lambda: actions.submit(conn, cfg, who, post["id"]),
            lambda: actions.note(conn, cfg, who, post["id"], "hi"),
        ):
            with pytest.raises(Exception) as info:
                call()
            assert info.value.code.value == "ROLE_NOT_ALLOWED"  # type: ignore[attr-defined]


# --- rules and command lines come from the API ---------------------------------------------


def test_schema_names_the_needs_you_statuses(env: Env) -> None:
    body = env.client.get("/api/schema").body
    assert body["needs_you"] == ["pending_approval", "changes_requested", "missed"]
    roles = {(t["from"], t["to"]): t["roles"] for t in body["transitions"]}
    for pair in (("pending_approval", "approved"), ("changes_requested", "pending_approval")):
        assert "approver" in roles[pair]


def test_every_action_carries_its_command_line(env: Env) -> None:
    post = add_post(env.home)
    shown = env.client.get(f"/api/posts/{post['id']}").body
    lines = {a["id"]: a["cli"] for a in shown["actions"]}
    prefix = f"brandcal approve {post['id']} --version 1 --hash {shown['content_hash'][:8]}"
    assert lines["approve"].startswith(prefix)
    assert (
        "--what <what>" in lines["request-changes"]
        and "--where <where>" in lines["request-changes"]
    )
    assert "<reason>" in lines["cancel"] and f"cancel {post['id']}" in lines["cancel"]
    assert lines["edit"].startswith(f"brandcal edit {post['id']}")
    assert all(line.startswith("brandcal ") for line in lines.values())


def test_closed_and_unverified_views_still_carry_command_lines() -> None:
    post = {"id": "p0001", "status": "approved", "content_version": 2, "window": NEW_WINDOW}
    post["content_hash"] = "ab" * 32
    for viewer in ("viewer", None):
        shown = {a["id"]: a for a in actions.post_actions(post, CFG, viewer)}
        assert shown["reschedule"]["cli"].startswith("brandcal reschedule p0001 --version 2")
        assert "--hash abababab" in shown["reschedule"]["cli"]
        assert shown["reschedule"]["enabled"] is False


def test_versions_keep_the_text_of_every_version(env: Env) -> None:
    post = add_post(env.home, first_comment="First thoughts")
    body = {"parts": {"1": "Second text"}, "fields": {"first_comment": "Second thoughts"}}
    assert env.client.post(path(post, "edit"), body).status == 200
    assert env.client.post(path(post, "edit"), {"parts": {"1": "Third text"}}).status == 200
    res = env.client.get(path(post, "versions"))
    assert res.status == 200
    versions = res.body["versions"]
    assert [v["version"] for v in versions] == [1, 2, 3]
    assert [v["parts"] for v in versions] == [
        ["Hello from Example Co"],
        ["Second text"],
        ["Third text"],
    ]
    assert [v["first_comment"] for v in versions] == [
        "First thoughts",
        "Second thoughts",
        "Second thoughts",
    ]
    assert versions[0]["editor"] == "writer-1" and versions[1]["editor"] == APPROVER
    assert all(v["hash"] and v["at"] for v in versions)
    shown = env.client.get(f"/api/posts/{post['id']}").body
    assert versions[-1]["hash"] == shown["content_hash"]


def test_versions_of_a_new_post_and_of_a_missing_one(env: Env) -> None:
    post = add_post(env.home)
    (only,) = env.client.get(path(post, "versions")).body["versions"]
    assert only["version"] == 1 and only["parts"] == ["Hello from Example Co"]
    assert env.client.get("/api/posts/nope/versions").status == 404

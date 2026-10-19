"""The CLI and actions.py give identical JSON and events for each mapped UI action (UI_SPEC 1.2)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from ui_env import NEW_WINDOW, add_post, make_home, open_home, run

from brandcal import actions
from brandcal.actions import Identity

TIMES = {"at", "updated_at", "created_at", "closed_at", "decided_at", "row_hash", "prev_hash"}
MANAGER, WRITER = Identity("manager-1"), Identity("writer-1")
Conn = Any
Setup = Callable[[Path, pytest.CaptureFixture[str], dict[str, Any]], None]


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in TIMES}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def event_log(home: Path) -> list[Any]:
    with open_home(home) as (conn, _):
        rows = conn.execute(
            "SELECT actor, post_id, action, from_status, to_status, detail, reason FROM events"
            " ORDER BY id"
        )
        return [tuple(r) for r in rows]


def approve_cli(home: Path, capsys: pytest.CaptureFixture[str], post: dict[str, Any]) -> None:
    args = ["approve", post["id"], "--version", "1", "--hash", post["hash"], "--channel", "card"]
    assert run(capsys, home, *args, "--msg", "m", "--words", "Yes", "--as", "manager-1")[0] == 0


def request_cli(home: Path, capsys: pytest.CaptureFixture[str], post: dict[str, Any]) -> None:
    args = ["request-changes", post["id"], "--version", "1", "--hash", post["hash"]]
    assert run(capsys, home, *args, "--msg", "m", "--words", "No", "--as", "manager-1")[0] == 0


def changes_made(home: Path, capsys: pytest.CaptureFixture[str], post: dict[str, Any]) -> None:
    request_cli(home, capsys, post)
    args = ["part", "edit", post["id"], "1", "Reworded text", "--as", "writer-1"]
    assert run(capsys, home, *args)[0] == 0


def nothing(home: Path, capsys: pytest.CaptureFixture[str], post: dict[str, Any]) -> None:
    return None


# name, setup, CLI argv (given the post), action call (given conn, cfg, home, post)
CASES: list[tuple[str, Setup, Callable[[dict[str, Any]], list[str]], Callable[..., Any]]] = [
    ("schema", nothing, lambda p: ["schema"], lambda c, g, h, p: actions.schema()),
    ("list", nothing, lambda p: ["list", "--status", "pending_approval"],
     lambda c, g, h, p: actions.list_posts(
         c, g, h, "pending_approval", None, None, None, False, False)),
    ("show", nothing, lambda p: ["show", p["id"], "--log"],
     lambda c, g, h, p: actions.show(c, p["id"], True)),
    ("check", nothing, lambda p: ["check", p["id"]],
     lambda c, g, h, p: actions.check(c, g, p["id"])),
    ("events", nothing, lambda p: ["events", "--post", p["id"]],
     lambda c, g, h, p: actions.events(c, None, p["id"], None, 100)),
    ("today", nothing, lambda p: ["today"], lambda c, g, h, p: actions.today(c, g, "today")),
    ("tomorrow", nothing, lambda p: ["tomorrow"],
     lambda c, g, h, p: actions.today(c, g, "tomorrow")),
    ("audit", nothing, lambda p: ["audit"], lambda c, g, h, p: actions.audit(c, h)),
    ("approve", nothing,
     lambda p: ["approve", p["id"], "--version", "1", "--hash", p["hash"], "--channel", "card",
                "--msg", "m", "--words", "Yes", "--as", "manager-1"],
     lambda c, g, h, p: actions.approve(c, g, MANAGER, p["id"], 1, p["hash"], "card", "m", "Yes")),
    ("request_changes", nothing,
     lambda p: ["request-changes", p["id"], "--version", "1", "--hash", p["hash"], "--msg", "m",
                "--words", "No", "--what", "a", "--where", "b", "--instruction", "c",
                "--as", "manager-1"],
     lambda c, g, h, p: actions.request_changes(
         c, g, MANAGER, p["id"], 1, p["hash"], "m", "No", what="a", where="b", instruction="c")),
    ("reschedule", approve_cli,
     lambda p: ["reschedule", p["id"], "--version", "1", "--hash", p["hash"],
                "--window", NEW_WINDOW, "--msg", "m", "--words", "Ok", "--as", "manager-1"],
     lambda c, g, h, p: actions.reschedule(
         c, g, MANAGER, p["id"], 1, p["hash"], NEW_WINDOW, "m", "Ok")),
    ("cancel", nothing,
     lambda p: ["cancel", p["id"], "--kind", "idea", "--reason", "No", "--as", "manager-1"],
     lambda c, g, h, p: actions.cancel(c, g, MANAGER, p["id"], "idea", "No")),
    ("edit", nothing,
     lambda p: ["edit", p["id"], "title=Changed title", "--as", "writer-1"],
     lambda c, g, h, p: actions.edit(c, g, WRITER, p["id"], ["title=Changed title"])),
    ("submit", changes_made,
     lambda p: ["submit", p["id"], "--as", "writer-1"],
     lambda c, g, h, p: actions.submit(c, g, WRITER, p["id"])),
    ("note", nothing,
     lambda p: ["note", p["id"], "remember this", "--as", "writer-1"],
     lambda c, g, h, p: actions.note(c, g, WRITER, p["id"], "remember this")),
]  # fmt: skip


@pytest.mark.parametrize(("name", "setup", "argv", "call"), CASES, ids=[c[0] for c in CASES])
def test_cli_and_action_agree(
    name: str,
    setup: Setup,
    argv: Callable[[dict[str, Any]], list[str]],
    call: Callable[..., Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    homes = [make_home(tmp_path / "cli", monkeypatch), make_home(tmp_path / "act", monkeypatch)]
    posts = [add_post(h) for h in homes]
    for h, p in zip(homes, posts, strict=True):
        setup(h, capsys, p)
    code, cli_out = run(capsys, homes[0], *argv(posts[0]))
    with open_home(homes[1]) as (conn, cfg):
        act_out = call(conn, cfg, homes[1], posts[1])
    assert code == 0 and cli_out["ok"]
    assert scrub(cli_out) == scrub(act_out)
    assert scrub(event_log(homes[0])) == scrub(event_log(homes[1]))


def test_actions_raise_the_cli_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = make_home(tmp_path / "h", monkeypatch)
    post = add_post(home)
    code, out = run(capsys, home, "show", "p9999")
    assert code == 7 and out["error"]["code"] == "NOT_FOUND"
    from brandcal.errors import BrandcalError

    with open_home(home) as (conn, cfg), pytest.raises(BrandcalError) as err:
        actions.show(conn, "p9999", False)
    assert err.value.to_dict() == out
    with open_home(home) as (conn, cfg), pytest.raises(BrandcalError) as err:
        actions.approve(
            conn, cfg, Identity("nobody"), post["id"], 1, post["hash"], "card", "m", "w"
        )
    assert err.value.code.value == "NO_AGENT"

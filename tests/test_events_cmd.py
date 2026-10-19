"""brandcal events: read-only, ordered by id, resumable with --since (UI_SPEC 4.3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from ui_env import add_post, cli_approve, make_home, open_home, run

from brandcal import posts


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return make_home(tmp_path / "home", monkeypatch)


def test_events_since_returns_each_event_once(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    post = add_post(home)
    code, first = run(capsys, home, "events", "--as", "writer-1")
    assert code == 0 and first["ok"] and [e["action"] for e in first["events"]] == ["add"]
    assert first["last_id"] == first["events"][-1]["id"] and "--since" in first["next"]
    event = first["events"][0]
    assert event["actor"] == "writer-1" and event["post_id"] == post["id"]
    assert isinstance(event["detail"], dict) or event["detail"] is None
    cli_approve(capsys, home, post)
    code, second = run(capsys, home, "events", "--since", str(first["last_id"]))
    assert [e["action"] for e in second["events"]] == ["approve"]
    assert second["last_id"] > first["last_id"]
    code, empty = run(capsys, home, "events", "--since", str(second["last_id"]))
    assert code == 0 and empty["events"] == [] and empty["last_id"] == second["last_id"]


def test_events_filters_limit_and_order(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    one = add_post(home)
    two = add_post(home, slug="second")
    cli_approve(capsys, home, one)
    _, out = run(capsys, home, "events")
    ids = [e["id"] for e in out["events"]]
    assert ids == sorted(ids) and len(ids) == 3
    _, out = run(capsys, home, "events", "--post", two["id"])
    assert [e["post_id"] for e in out["events"]] == [two["id"]]
    _, out = run(capsys, home, "events", "--actor", "manager-1")
    assert [e["action"] for e in out["events"]] == ["approve"]
    _, out = run(capsys, home, "events", "--limit", "2")
    assert len(out["events"]) == 2 and out["last_id"] == ids[1]  # resume from the second
    _, rest = run(capsys, home, "events", "--limit", "2", "--since", str(out["last_id"]))
    assert [e["id"] for e in rest["events"]] == ids[2:]


def test_events_is_read_only_for_every_role(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    add_post(home)
    for agent in ("writer-1", "manager-1", "approver-1", "admin-1"):
        code, out = run(capsys, home, "events", "--as", agent)
        assert code == 0 and out["ok"]
    with open_home(home) as (conn, _):
        assert (
            conn.execute("SELECT count(*) FROM events WHERE action = 'events'").fetchone()[0] == 0
        )


def test_events_errors(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    add_post(home)
    code, out = run(capsys, home, "events", "--post", "p9999")
    assert code == 7 and out["error"]["code"] == "NOT_FOUND"
    for bad in (("--limit", "0"), ("--limit", "-1"), ("--since", "-3")):
        code, out = run(capsys, home, "events", *bad)
        assert code == 2 and out["error"]["code"] == "BAD_ARGS"
    code, out = run(capsys, home, "events", "--since", "x")
    assert code == 2 and out["error"]["code"] == "BAD_ARGS"


def test_events_for_an_archived_post_says_archived(
    home: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(posts, "archived_posts", lambda conn: {"p0777": "2026-02"})
    code, out = run(capsys, home, "events", "--post", "p0777")
    assert code == 7 and out["error"]["code"] == "ARCHIVED"
    assert "archive show p0777 --month 2026-02" in out["error"]["next"]


def test_help_events(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    code, out = run(capsys, home, "help", "events")
    assert code == 0 and "--since" in out["arguments"] and out["roles"] == ["all"]

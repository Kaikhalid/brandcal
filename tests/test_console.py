"""Console approvals, structured change requests and the new error codes (UI_SPEC 2.3, 3, 4.2)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from ui_env import NEW_WINDOW, VERIFIED, add_post, make_home, open_home, run

from brandcal import actions, audit
from brandcal.actions import Identity
from brandcal.approvals import Verified
from brandcal.errors import EXIT_CODES, BrandcalError, ErrorCode, ExitCode

APPROVER = Identity("approver-1", Verified(VERIFIED["identity"], VERIFIED["source"]))
THREE = {"what": "Headline overstates", "where": "Part 1", "instruction": "Say up to 20%"}


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return make_home(tmp_path / "home", monkeypatch)


def console_approve(home: Path, post: dict[str, Any], who: Identity = APPROVER) -> dict[str, Any]:
    with open_home(home) as (conn, cfg):
        return actions.approve(
            conn, cfg, who, post["id"], post["version"], post["hash"], "console",
            "console-approve", "Approve",
        )  # fmt: skip


def code_of(err: pytest.ExceptionInfo[BrandcalError]) -> ErrorCode:
    return err.value.code


def test_console_approval_is_recorded_with_identity(home: Path) -> None:
    post = add_post(home)
    out = console_approve(home, post)
    assert out["ok"] and out["status"] == "approved" and "begin" in out["next"]
    with open_home(home) as (conn, cfg):
        a = conn.execute("SELECT * FROM approvals").fetchone()
        assert (a["channel"], a["decided_by"], a["recorded_by"], a["relayed_by"]) == (
            "console", "approver-1", "console", "console",
        )  # fmt: skip
        assert (a["verified_identity"], a["identity_source"]) == (
            "approver@example.com",
            "access-jwt",
        )
        assert (a["source_message_id"], a["approver_words"]) == ("console-approve", "Approve")
        ev = conn.execute("SELECT actor, detail FROM events WHERE action = 'approve'").fetchone()
        assert ev["actor"] == "approver-1"
        detail = json.loads(ev["detail"])
        assert detail["identity"] == "approver@example.com" and detail["via"] == "console"
        assert detail["source"] == "access-jwt"
        assert audit.audit(conn, home)["ok"]


def test_console_approval_without_identity_is_refused(home: Path) -> None:
    post = add_post(home)
    for who in (
        Identity("approver-1"),
        Identity("approver-1", Verified("approver@example.com", "dev-unverified")),
    ):
        with pytest.raises(BrandcalError) as err:
            console_approve(home, post, who)
        assert code_of(err) is ErrorCode.IDENTITY_UNVERIFIED and err.value.exit_code == 4
    with open_home(home) as (conn, _):
        assert conn.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0


def test_console_needs_an_approver_and_a_console_agent(home: Path) -> None:
    post = add_post(home)
    with pytest.raises(BrandcalError) as err:
        console_approve(home, post, Identity("manager-1", APPROVER.verified))
    assert code_of(err) is ErrorCode.ROLE_NOT_ALLOWED
    with open_home(home) as (conn, cfg):
        cfg["serve"] = {}
        with pytest.raises(BrandcalError) as err:
            actions.approve(conn, cfg, APPROVER, "p0001", 1, post["hash"], "console", "b", "w")
        assert code_of(err) is ErrorCode.BAD_ARGS and "console_agent" in err.value.next_step


def test_cli_cannot_record_console(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    post = add_post(home)
    base = [
        "approve",
        post["id"],
        "--version",
        "1",
        "--hash",
        post["hash"],
        "--msg",
        "m",
        "--words",
        "w",
    ]
    for agent in ("manager-1", "approver-1"):
        code, out = run(capsys, home, *base, "--channel", "console", "--as", agent)
        assert code == 4 and out["error"]["code"] == "IDENTITY_UNVERIFIED"
        assert "web UI" in out["error"]["next"]
    code, out = run(capsys, home, *base, "--channel", "card", "--as", "approver-1")
    assert code == 4 and out["error"]["code"] == "ROLE_NOT_ALLOWED"


def test_begin_refuses_console_approval_without_identity(home: Path) -> None:
    post = add_post(home)
    with open_home(home) as (conn, cfg):
        conn.execute("PRAGMA ignore_check_constraints = ON")  # simulate a damaged row
        conn.execute(
            'INSERT INTO approvals (post_id, decision, content_version, content_hash, "window",'
            " decided_by, channel, relayed_by, recorded_by, source_message_id, approver_words,"
            " decided_at) SELECT id, 'approve', content_version, content_hash, \"window\","
            " 'approver-1', 'console', 'console', 'console', 'b', 'w', '2026-03-01T08:00:00+03:00'"
            " FROM posts"
        )
        conn.execute("UPDATE posts SET status = 'approved'")
        conn.execute("PRAGMA ignore_check_constraints = OFF")
        assert any(f["kind"] == "console_unverified" for f in audit.audit(conn, home)["flags"])
        from brandcal import publish

        with pytest.raises(BrandcalError) as err:
            publish.begin(conn, "manager-1", "manager", cfg, home, post["id"])
        assert code_of(err) is ErrorCode.IDENTITY_UNVERIFIED


def test_begin_accepts_verified_console_approval(home: Path) -> None:
    post = add_post(home)
    console_approve(home, post)
    with open_home(home) as (conn, cfg):
        from brandcal import publish

        inside = datetime(2026, 3, 10, 9, 30, tzinfo=timezone(timedelta(hours=3)))
        out = publish.begin(conn, "manager-1", "manager", cfg, home, post["id"], True, inside)
        assert out["ok"]


def test_request_changes_reason_is_required_for_console(home: Path) -> None:
    post = add_post(home)
    with open_home(home) as (conn, cfg):

        def call(**kw: Any) -> dict[str, Any]:
            return actions.request_changes(
                conn, cfg, APPROVER, post["id"], 1, post["hash"], "console-request-changes",
                "Request changes", channel="console", **kw,
            )  # fmt: skip

        for missing in ({}, {**THREE, "where": " "}, {**THREE, "instruction": None}):
            with pytest.raises(BrandcalError) as err:
                call(**missing)
            assert code_of(err) is ErrorCode.REASON_REQUIRED and err.value.exit_code == 3
        assert conn.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0
        assert call(**THREE)["status"] == "changes_requested"
        row = conn.execute("SELECT * FROM approvals").fetchone()
        assert json.loads(row["changes_requested"]) == THREE and row["channel"] == "console"


def test_cli_request_changes_structured_reason(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    post = add_post(home)
    base = ["request-changes", post["id"], "--version", "1", "--hash", post["hash"]]
    base += ["--msg", "m", "--words", "see below", "--as", "manager-1"]
    code, out = run(capsys, home, *base, "--what", "Too long")  # partial: all three or none
    assert code == 3 and out["error"]["code"] == "REASON_REQUIRED"
    code, out = run(capsys, home, *base, "--what", "w", "--where", "p1", "--instruction", "cut")
    assert code == 0 and out["status"] == "changes_requested"
    code, out = run(capsys, home, "next", "--as", "writer-1")
    item = out["items"][0]
    assert item["reason"] == {"what": "w", "where": "p1", "instruction": "cut"}


def test_legacy_request_changes_unchanged(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    post = add_post(home)
    args = ["request-changes", post["id"], "--version", "1", "--hash", post["hash"]]
    code, out = run(capsys, home, *args, "--msg", "m", "--words", "Shorter", "--as", "manager-1")
    assert code == 0
    with open_home(home) as (conn, _):
        assert conn.execute("SELECT changes_requested FROM approvals").fetchone()[0] == "Shorter"
    _, out = run(capsys, home, "next", "--as", "writer-1")
    assert "reason" not in out["items"][0]


def test_console_reschedule_and_cancel(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    post = add_post(home)
    console_approve(home, post)
    with open_home(home) as (conn, cfg):
        out = actions.reschedule(
            conn, cfg, APPROVER, post["id"], 1, post["hash"], NEW_WINDOW, "console-reschedule",
            "Change time", channel="console",
        )  # fmt: skip
        assert out["window"] == NEW_WINDOW
        out = actions.cancel(
            conn, cfg, APPROVER, post["id"], "plan", "Not needed", "console-cancel", "Cancel",
            channel="console",
        )  # fmt: skip
        assert out["status"] == "cancelled"
        rows = conn.execute(
            "SELECT decision, channel, decided_by FROM approvals ORDER BY id"
        ).fetchall()
        assert [tuple(r) for r in rows] == [("approve", "console", "approver-1")] + [
            ("reschedule", "console", "approver-1"),
            ("cancel", "console", "approver-1"),
        ]
        with pytest.raises(BrandcalError) as err:
            actions.cancel(
                conn,
                cfg,
                Identity("approver-1"),
                post["id"],
                "plan",
                "x",
                "b",
                "w",
                channel="console",
            )
        assert code_of(err) is ErrorCode.IDENTITY_UNVERIFIED


def test_approver_still_refused_by_other_actions(home: Path) -> None:
    post = add_post(home)
    with open_home(home) as (conn, cfg):
        conn.execute("UPDATE posts SET status = 'changes_requested'")  # so submit is a real move
        for call in (
            lambda: actions.edit(conn, cfg, APPROVER, post["id"], ["title=X"]),
            lambda: actions.submit(conn, cfg, APPROVER, post["id"]),
        ):
            with pytest.raises(BrandcalError) as err:
                call()
            assert code_of(err) is ErrorCode.ROLE_NOT_ALLOWED


@pytest.mark.parametrize(
    ("code", "exit_code"),
    [
        (ErrorCode.IDENTITY_UNVERIFIED, ExitCode.NOT_ALLOWED),
        (ErrorCode.IDENTITY_UNMAPPED, ExitCode.NOT_ALLOWED),
        (ErrorCode.BAD_ORIGIN, ExitCode.NOT_ALLOWED),
        (ErrorCode.REASON_REQUIRED, ExitCode.VALIDATION),
        (ErrorCode.EXTRA_NOT_INSTALLED, ExitCode.USAGE),
    ],
)
def test_new_error_codes(code: ErrorCode, exit_code: ExitCode) -> None:
    assert code.value == code.name and EXIT_CODES[code] is exit_code
    err = BrandcalError(code, "m", "n")
    assert err.exit_code == int(exit_code) and err.to_dict()["error"]["code"] == code.value
    assert f"`{code.value}`" in Path("docs/ERRORS.md").read_text(encoding="utf-8")

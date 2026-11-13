"""Hand-written: next, today, tomorrow, list, show, report weekly, render week (SPEC 8.1, 8.5)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from conftest import AGENTS, PLATFORMS, WINDOW, add_approval, approve_post
from conftest import make_post as _make_post

from brandcal import events, reports
from brandcal.cli import main
from brandcal.db import init_db, open_db
from brandcal.errors import BrandcalError

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 3, 10, 9, 30, tzinfo=TZ)  # inside WINDOW (09:00-10:00)
AGENTS2 = [*AGENTS, {"id": "writer-2", "role": "writer"}]
CFG: dict[str, Any] = {"timezone": "+03:00", "agents": AGENTS2}


def make_post(conn: sqlite3.Connection, **overrides: object) -> str:
    """Like conftest.make_post, but may seed any state (posts are inserted pending, then moved)."""
    late_keys = ("status", "platform_url", "closed_at", "published_at", "cancel_kind")
    late = {k: overrides.pop(k) for k in late_keys if k in overrides}
    pid = _make_post(conn, **overrides)
    status = late.pop("status", "pending_approval")
    if status in ("approved", "missed", "published"):
        approve_post(conn, pid)
    if status != "pending_approval" and status != "approved":
        late["status"] = status
    if late:
        sets = ", ".join(f'"{k}" = ?' for k in late)
        conn.execute(f"UPDATE posts SET {sets} WHERE id = ?", (*late.values(), pid))
    return pid


def win(day: str, hour: int = 9, off: str = "+03:00") -> str:
    return f"{day}T{hour:02d}:00:00{off}/{day}T{hour:02d}:45:00{off}"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    (path / "config.json").write_text(json.dumps(CFG), encoding="utf-8")
    db = open_db(path / "brand.db", TZ)
    init_db(db, AGENTS2, PLATFORMS)
    db.close()
    return path


@pytest.fixture
def db(home: Path) -> Any:
    conn = open_db(home / "brand.db", TZ)
    yield conn
    conn.close()


def run(home: Path, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any]]:
    code = main(["--home", str(home), *argv])
    out: dict[str, Any] = json.loads(capsys.readouterr().out)
    return code, out


def event(conn: sqlite3.Connection, pid: str, action: str, at: str, **kw: Any) -> None:
    events.append_event(
        conn, at=at, actor="manager-1", action=action, chain=f"post:{pid}", post_id=pid, **kw
    )


def test_next_writer_shows_own_changes_requested(db: sqlite3.Connection) -> None:
    make_post(db, id="p0001", status="changes_requested")
    make_post(db, id="p0002", status="changes_requested", owner="writer-2")
    rows = reports.next_for(db, CFG, "writer-1", NOW)
    assert [r["id"] for r in rows] == ["p0001"]
    assert rows[0]["next"] == "brandcal edit p0001 ... then brandcal submit p0001"
    assert "text" not in rows[0]


def test_next_manager_stale_and_due(db: sqlite3.Connection) -> None:
    make_post(db, id="p0001", status="approved")
    make_post(db, id="p0002", status="missed", window=win("2026-02-01"))
    make_post(db, id="p0003", status="missed", window=win("2026-03-05"))
    rows = {r["id"]: r for r in reports.next_for(db, CFG, "manager-1", NOW)}
    assert rows["p0001"]["next"] == "brandcal begin p0001"
    assert rows["p0002"]["stale"] is True
    assert "stale" not in rows["p0003"]
    assert rows["p0003"]["next"].startswith("brandcal reschedule p0003")
    assert [r["id"] for r in reports.next_for(db, CFG, "manager-1", NOW)][0] == "p0002"


def test_next_manager_scheduled_and_chase(db: sqlite3.Connection) -> None:
    make_post(db, id="p0001", status="approved")
    db.execute("UPDATE posts SET native_scheduled_at = '2026-03-10T09:00:00+03:00'")
    make_post(db, id="p0002", window=win("2026-03-10", 20))
    make_post(db, id="p0003", window=win("2026-03-20"))
    rows = {r["id"]: r for r in reports.next_for(db, CFG, "manager-1", NOW)}
    assert "brandcal published p0001 URL" in rows["p0001"]["next"]
    assert "approver" in rows["p0002"]["next"]
    assert "p0003" not in rows


def test_next_approver_and_unknown(db: sqlite3.Connection) -> None:
    make_post(db)
    assert reports.next_for(db, CFG, "approver-1", NOW)[0]["next"] == "brandcal preview p0001"
    with pytest.raises(BrandcalError) as info:
        reports.next_for(db, CFG, "nobody", NOW)
    assert (info.value.code.value, info.value.exit_code) == ("NO_AGENT", 2)


def test_next_unknown_via_cli(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(home, capsys, "next", "--as", "nobody")
    assert code == 2 and out["error"]["code"] == "NO_AGENT"


@pytest.mark.parametrize("off", ["+03:00", "-05:00"])
def test_today_honours_offset(tmp_path: Path, off: str) -> None:
    tz = timezone(timedelta(hours=int(off[:3])))
    conn = open_db(tmp_path / "brand.db", tz)
    init_db(conn, AGENTS, PLATFORMS)
    start = f"2026-03-19T23:30:00{off}/2026-03-19T23:45:00{off}"
    make_post(conn, id="p0001", window=start)
    make_post(conn, id="p0002", window=win("2026-03-20", 1, off))
    cfg = {"timezone": off, "agents": AGENTS}
    now = datetime(2026, 3, 19, 12, tzinfo=tz)
    assert [r["id"] for r in reports.day(conn, cfg, "today", now)] == ["p0001"]
    assert [r["id"] for r in reports.day(conn, cfg, "tomorrow", now)] == ["p0002"]
    conn.close()


def test_list_filters(
    home: Path, db: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    make_post(db, id="p0001")
    make_post(db, id="p0002", platform="x", window=win("2026-03-11"))
    make_post(
        db, id="p0003", status="published", platform_url="https://example.com/p",
        closed_at="2026-03-10T10:00:00+03:00", window=win("2026-03-12"),
    )  # fmt: skip
    db.commit()
    ids = lambda out: [r["id"] for r in out["posts"]]  # noqa: E731
    assert ids(run(home, capsys, "list")[1]) == ["p0001", "p0002"]
    assert ids(run(home, capsys, "list", "--closed")[1]) == ["p0001", "p0002", "p0003"]
    assert ids(run(home, capsys, "list", "--platform", "x")[1]) == ["p0002"]
    assert ids(run(home, capsys, "list", "--from", "2026-03-11")[1]) == ["p0002"]
    assert ids(run(home, capsys, "list", "--to", "2026-03-10")[1]) == ["p0001"]
    assert ids(run(home, capsys, "list", "--status", "pending_approval")[1]) == ["p0001", "p0002"]
    code, out = run(home, capsys, "list", "--from", "nope")
    assert code == 3 and out["error"]["code"] == "BAD_TIME"


def test_show_and_log(
    home: Path, db: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    make_post(db)
    add_approval(db, "p0001")
    event(db, "p0001", "add", "2026-03-01T08:00:00+03:00", detail={"k": 1})
    event(db, "p0001", "submit", "2026-03-01T09:00:00+03:00", reason="r")
    db.commit()
    code, out = run(home, capsys, "show", "p0001")
    assert code == 0 and "events" not in out
    assert out["parts"] == [{"pos": 1, "text": "Hello from Example Co"}]
    assert out["approvals"][0]["approver_words"] == "Looks good"
    assert "signature" not in out["approvals"][0]
    _, out = run(home, capsys, "show", "p0001", "--log")
    assert [e["action"] for e in out["events"]] == ["add", "submit"]
    assert out["events"][0]["detail"] == {"k": 1}
    code, out = run(home, capsys, "show", "p9999")
    assert code == 7 and out["error"]["code"] == "NOT_FOUND"


def test_weekly(home: Path, db: sqlite3.Connection) -> None:
    make_post(
        db, id="p0001", status="published", platform_url="https://example.com/p1",
        published_at="2026-03-09T09:30:00+03:00", closed_at="2026-03-09T09:30:00+03:00",
        window=win("2026-03-09"),
    )  # fmt: skip
    make_post(db, id="p0002")
    make_post(
        db, id="p0003", status="cancelled", cancel_kind="plan",
        closed_at="2026-03-08T12:00:00+03:00", window=win("2026-03-12"),
    )  # fmt: skip
    make_post(db, id="p0004", window=win("2026-03-11"))
    event(db, "p0002", "publish_failed", "2026-03-10T09:10:00+03:00", reason="login failed")
    event(db, "p0004", "add", "2026-03-10T05:30:00+03:00")
    add_approval(db, "p0001", decided_at="2026-03-05T08:00:00+03:00")
    add_approval(db, "p0004", decided_at="2026-03-02T08:00:00+03:00")
    rep = reports.weekly(db, CFG, home, now=NOW)
    assert rep["published"][0]["platform_url"] == "https://example.com/p1"
    assert rep["failed"] == [
        {
            "id": "p0002",
            "at": "2026-03-10T09:10:00+03:00",
            "actor": "manager-1",
            "reason": "login failed",
        }  # fmt: skip
    ]
    assert [r["id"] for r in rep["cancelled"]] == ["p0003"]
    waiting = {r["id"]: r for r in rep["waiting_for_approver"]}
    assert waiting["p0004"]["hours_waiting"] == 4.0
    assert "p0004" in [r["id"] for r in rep["next_7_days"]]
    assert rep["published_without_url"] == []
    assert isinstance(rep["flags"], list)
    (appr,) = rep["approvals"]
    assert {k: appr[k] for k in ("channel", "source_message_id", "approver_words")} == {
        "channel": "card", "source_message_id": "msg-1", "approver_words": "Looks good",
    }  # fmt: skip
    assert (appr["relayed_by"], appr["recorded_by"], appr["decided_by"]) == (
        "manager-1", "manager-1", "approver-1",
    )  # fmt: skip


def test_weekly_cli_manager_only(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(home, capsys, "report", "weekly", "--as", "writer-1")
    assert code == 4 and out["error"]["code"] == "ROLE_NOT_ALLOWED"
    code, out = run(home, capsys, "report", "weekly", "--as", "manager-1", "--end", "2026-03-10")
    assert code == 0 and out["ok"] is True
    code, out = run(home, capsys, "report", "weekly", "--as", "manager-1", "--end", "bad")
    assert code == 3


def test_render_week_escapes(home: Path, db: sqlite3.Connection, capsys: Any) -> None:
    make_post(db, title="Hi <b>there</b>")
    page = reports.render_week(db, CFG, NOW)
    assert "&lt;b&gt;there&lt;/b&gt;" in page and "<b>" not in page
    assert "<script" not in page and "http" not in page
    db.commit()
    code, out = run(home, capsys, "render", "week", "--as", "manager-1")
    assert code == 0 and out["ok"] is True and "<html" in out["html"]
    target = home / "week.html"
    code, out = run(home, capsys, "render", "week", "--as", "manager-1", "--out", str(target))
    assert code == 0 and "<html" in target.read_text(encoding="utf-8")


def test_reads_leave_db_unchanged(home: Path, db: sqlite3.Connection, capsys: Any) -> None:
    make_post(db)
    event(db, "p0001", "add", "2026-03-01T08:00:00+03:00")
    db.commit()
    db.close()
    path = home / "brand.db"
    before = path.read_bytes()
    commands = [
        ["next", "--as", "manager-1"], ["today"], ["tomorrow"], ["list", "--closed"],
        ["show", "p0001", "--log"], ["report", "weekly", "--as", "manager-1"],
        ["render", "week", "--as", "manager-1"],
    ]  # fmt: skip
    for argv in commands:
        assert run(home, capsys, *argv)[0] == 0
    assert path.read_bytes() == before
    check = sqlite3.connect(path)
    assert check.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    check.close()
    assert WINDOW  # fixture constant stays referenced


def test_render_week_shows_times_in_the_display_timezone(db: sqlite3.Connection) -> None:
    """Hand-added: a window stored in another offset is shown in the display timezone."""
    day = NOW.date().isoformat()
    make_post(db, window=win(day, hour=1, off="-05:00"))  # 01:00-05:00 is 09:00+03:00
    page = reports.render_week(db, CFG, NOW)
    assert "09:00" in page and "01:00" not in page

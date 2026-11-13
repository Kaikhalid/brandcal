"""Hand-written: the sweep marks missed posts and releases expired claims (SPEC 6, 8.3, 11)."""

from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import PLATFORMS
from test_publish import CFG, DATA, NOW, TZ, approved, begin, fails, published, row, run, schedule

from brandcal import posts, sweep

AFTER = datetime(2026, 3, 10, 11, 0, tzinfo=TZ)  # the window (09:00-10:00) has ended
SHORT = {**CFG, "claim_minutes": 10}


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


@pytest.fixture
def cli_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "config.json").write_text(json.dumps(CFG), encoding="utf-8")
    (tmp_path / "platforms.json").write_text(json.dumps(PLATFORMS), encoding="utf-8")
    monkeypatch.setenv("BRANDCAL_HOME", str(tmp_path))
    monkeypatch.delenv("BRANDCAL_AGENT", raising=False)
    monkeypatch.delenv("BRANDCAL_TZ", raising=False)
    return tmp_path


def run_sweep(conn: sqlite3.Connection, now: datetime = AFTER, **kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = sweep.sweep(conn, CFG, now, **kw)
    return out


def n_events(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])


def test_plain_approved_past_window_is_missed(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    out = run_sweep(conn)
    assert out == {"ok": True, "missed": [pid], "claims_released": [], "overdue_native": []}
    assert row(conn, pid)["status"] == "missed"
    event = conn.execute(
        "SELECT actor, from_status, to_status FROM events WHERE post_id = ? AND action = 'missed'",
        (pid,),
    ).fetchone()
    assert tuple(event) == ("system", "approved", "missed")


def test_window_still_open_is_left_alone(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    out = run_sweep(conn, NOW)
    assert out["missed"] == [] and row(conn, pid)["status"] == "approved"
    assert run_sweep(conn, datetime(2026, 3, 10, 10, 0, tzinfo=TZ))["missed"] == [pid]


def test_natively_scheduled_past_window_is_listed_not_missed(
    conn: sqlite3.Connection, home: Path
) -> None:
    pid = approved(conn, home)
    schedule(conn, home, pid, "2026-03-10T09:45:00+03:00")
    n = n_events(conn)
    out = run_sweep(conn)
    assert (out["missed"], out["overdue_native"]) == ([], [pid])
    assert row(conn, pid)["status"] == "approved" and n_events(conn) == n
    assert run_sweep(conn, NOW)["overdue_native"] == []  # window not over yet


def test_live_claim_past_window_is_untouched(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    begin(conn, home, pid, now=datetime(2026, 3, 10, 9, 55, tzinfo=TZ))  # claim until 10:25
    n = n_events(conn)
    out = run_sweep(conn, datetime(2026, 3, 10, 10, 10, tzinfo=TZ))
    assert (out["missed"], out["claims_released"], out["overdue_native"]) == ([], [], [])
    r = row(conn, pid)
    assert (r["status"], r["claimed_by"]) == ("approved", "manager-1") and n_events(conn) == n


def test_expired_claim_is_released_and_needs_a_live_check(
    conn: sqlite3.Connection, home: Path
) -> None:
    pid = approved(conn, home)
    begin(conn, home, pid, cfg=SHORT)  # claim until 09:40
    out = run_sweep(conn, datetime(2026, 3, 10, 9, 45, tzinfo=TZ))
    assert (out["claims_released"], out["missed"]) == ([pid], [])
    r = row(conn, pid)
    assert (r["status"], r["claimed_by"], r["claim_expires"]) == ("approved", None, None)
    event = conn.execute(
        "SELECT actor, from_status, to_status FROM events WHERE post_id = ? AND action = ?",
        (pid, "claim_expired"),
    ).fetchone()
    assert tuple(event) == ("system", "approved", "approved")
    n = n_events(conn)
    assert run_sweep(conn, datetime(2026, 3, 10, 9, 46, tzinfo=TZ))["claims_released"] == []
    assert n_events(conn) == n
    later = datetime(2026, 3, 10, 9, 46, tzinfo=TZ)
    fails("CHECK_LIVE_FIRST", 8, begin, conn, home, pid, now=later)
    assert begin(conn, home, pid, now=later, not_live=True)["ok"] is True


def test_expired_claim_after_the_window_is_missed_on_the_next_run(
    conn: sqlite3.Connection, home: Path
) -> None:
    pid = approved(conn, home)
    begin(conn, home, pid, now=datetime(2026, 3, 10, 9, 55, tzinfo=TZ))  # claim until 10:25
    first = run_sweep(conn, datetime(2026, 3, 10, 10, 30, tzinfo=TZ))
    assert (first["claims_released"], first["missed"]) == ([pid], [])
    assert row(conn, pid)["status"] == "approved"
    assert run_sweep(conn, datetime(2026, 3, 10, 10, 31, tzinfo=TZ))["missed"] == [pid]


def test_published_and_pending_posts_are_untouched(conn: sqlite3.Connection, home: Path) -> None:
    done = approved(conn, home)
    begin(conn, home, done)
    published(conn, done)
    pending = posts.add_post(conn, "writer-1", "writer", CFG, DATA)["id"]
    n = n_events(conn)
    out = run_sweep(conn)
    assert (out["missed"], out["claims_released"], out["overdue_native"]) == ([], [], [])
    assert (row(conn, done)["status"], row(conn, pending)["status"]) == (
        "published",
        "pending_approval",
    )
    assert n_events(conn) == n


def test_second_run_changes_nothing(conn: sqlite3.Connection, home: Path) -> None:
    plain = approved(conn, home)
    claimed = approved(conn, home)
    begin(conn, home, claimed, now=datetime(2026, 3, 10, 9, 55, tzinfo=TZ))  # claim until 10:25
    queued = approved(conn, home)
    schedule(conn, home, queued, "2026-03-10T09:45:00+03:00")
    now = datetime(2026, 3, 10, 10, 10, tzinfo=TZ)
    first = run_sweep(conn, now)
    assert (first["missed"], first["claims_released"], first["overdue_native"]) == (
        [plain],
        [],
        [queued],
    )
    n = n_events(conn)
    second = run_sweep(conn, now)
    assert (second["missed"], second["claims_released"]) == ([], [])
    assert second["overdue_native"] == [queued] and n_events(conn) == n
    assert row(conn, claimed)["claimed_by"] == "manager-1"


def test_sweep_records_who_ran_it(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    run_sweep(conn, agent="writer-1")
    detail = json.loads(
        conn.execute(
            "SELECT detail FROM events WHERE post_id = ? AND action = 'missed'", (pid,)
        ).fetchone()[0]
    )
    assert detail["run_by"] == "writer-1"
    other = approved(conn, home, slug="no-agent")
    run_sweep(conn)
    detail = json.loads(
        conn.execute(
            "SELECT detail FROM events WHERE post_id = ? AND action = 'missed'", (other,)
        ).fetchone()[0]
    )
    assert "run_by" not in detail


def test_sweep_is_one_transaction(conn: sqlite3.Connection, home: Path) -> None:
    pid = approved(conn, home)
    conn.execute(
        "CREATE TRIGGER boom BEFORE INSERT ON events WHEN NEW.action = 'missed'"
        " BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY: boom'); END"
    )
    fails("APPEND_ONLY", 5, sweep.sweep, conn, CFG, AFTER)
    assert row(conn, pid)["status"] == "approved"
    assert not conn.in_transaction


def test_cli_sweep(
    cli_home: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run(capsys, "init", "--as", "admin-1")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(DATA)))  # window is long past
    added = run(capsys, "add", "--as", "writer-1")[1]
    pid = added["id"]
    run(
        capsys, "approve", pid, "--version", "1", "--hash", added["hash"], "--channel", "card",
        "--msg", "m1", "--words", "ok", "--as", "manager-1",
    )  # fmt: skip
    code, out = run(capsys, "sweep")  # no agent needed
    assert (code, out["missed"]) == (0, [pid])
    assert run(capsys, "sweep", "--as", "writer-1") == (
        0,
        {"ok": True, "missed": [], "claims_released": [], "overdue_native": []},
    )
    code, out = run(capsys, "sweep", "--as", "nobody")
    assert (code, out["error"]["code"]) == (2, "NO_AGENT")


def test_published_accepted_after_sweep_released_the_claim(
    conn: sqlite3.Connection, home: Path
) -> None:
    """Hand-added (SPEC 6): the post may have gone out just after its claim ran out."""
    pid = approved(conn, home)
    begin(conn, home, pid, cfg=SHORT)  # claim until 09:40
    run_sweep(conn, datetime(2026, 3, 10, 9, 45, tzinfo=TZ))
    out = published(conn, pid, now=datetime(2026, 3, 10, 9, 50, tzinfo=TZ))
    assert out["status"] == "published"
    assert row(conn, pid)["status"] == "published"

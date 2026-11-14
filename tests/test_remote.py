"""Remote mode without a network: snapshot round-trip, diffs and refusals (D1_MIGRATION.md 5)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from ui_env import add_post, cli_approve, make_home

from brandcal import cli, remote
from brandcal.errors import BrandcalError, ErrorCode


def snapshot_of(home: Path) -> dict[str, object]:
    conn = sqlite3.connect(home / "brand.db")
    conn.row_factory = sqlite3.Row
    tables = {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in remote.LOAD_ORDER}
    conn.close()
    cfg = json.loads((home / "config.json").read_text(encoding="utf-8"))
    return {"ok": True, "gen": 4, "config": cfg, "tables": tables}


def test_build_home_round_trips_rows_and_keeps_triggers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = make_home(tmp_path / "home", monkeypatch)
    cli_approve(capsys, home, add_post(home))
    copy = tmp_path / "copy"
    copy.mkdir()
    remote.build_home(snapshot_of(home), copy)
    assert remote.read_rows(copy / "brand.db") == remote.read_rows(home / "brand.db")
    conn = sqlite3.connect(copy / "brand.db")
    triggers = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger'").fetchone()
    conn.close()
    assert triggers[0] > 20


def test_diff_lists_upserts_and_appends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = make_home(tmp_path / "home", monkeypatch)
    post = add_post(home)
    before = remote.read_rows(home / "brand.db")
    cli_approve(capsys, home, post)
    changes = remote.diff(before, remote.read_rows(home / "brand.db"))
    assert set(changes) == {"posts", "approvals", "events"}
    assert changes["posts"]["upsert"][0]["status"] == "approved"
    assert "window_start_utc" not in changes["posts"]["upsert"][0]
    assert [e["action"] for e in changes["events"]["insert"]] == ["approve"]


def test_diff_refuses_fixed_tables_and_rewrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = make_home(tmp_path / "home", monkeypatch)
    add_post(home)
    before = remote.read_rows(home / "brand.db")
    after = remote.read_rows(home / "brand.db")
    after["agents"]["x"] = {"id": "x", "role": "admin"}
    with pytest.raises(BrandcalError) as err:
        remote.diff(before, after)
    assert err.value.code == ErrorCode.ROLE_NOT_ALLOWED
    after = remote.read_rows(home / "brand.db")
    first = next(iter(after["events"]))
    after["events"][first] = {**after["events"][first], "reason": "changed"}
    with pytest.raises(BrandcalError) as err:
        remote.diff(before, after)
    assert err.value.code == ErrorCode.APPEND_ONLY


def test_remote_mode_needs_the_token_and_refuses_local_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(remote.ENV_URL, "https://brandcal.example.com")
    monkeypatch.delenv(remote.ENV_ID, raising=False)
    monkeypatch.delenv(remote.ENV_SECRET, raising=False)
    assert cli.main(["list"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "SECRET_UNAVAILABLE"
    assert cli.main(["backup", "--as", "admin-1"]) == 2
    assert "not available in remote mode" in capsys.readouterr().out
    assert cli.main(["--home", "/tmp/x", "list"]) == 2
    assert "--home" in capsys.readouterr().out
    monkeypatch.setenv(remote.ENV_URL, "http://brandcal.example.com")
    monkeypatch.setenv(remote.ENV_ID, "id")
    monkeypatch.setenv(remote.ENV_SECRET, "secret")
    assert cli.main(["list"]) == 2
    assert "https" in capsys.readouterr().out

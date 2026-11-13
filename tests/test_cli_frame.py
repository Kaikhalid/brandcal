from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from brandcal import cli

AGENTS = [
    {"id": "writer-1", "role": "writer"},
    {"id": "manager-1", "role": "manager"},
    {"id": "admin-1", "role": "admin"},
]


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for var in ("BRANDCAL_HOME", "BRANDCAL_AGENT", "BRANDCAL_TZ"):
        monkeypatch.delenv(var, raising=False)
    cfg = {"timezone": "-05:00", "agents": AGENTS}
    (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return tmp_path


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, Any]:
    code = cli.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_unknown_command(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(capsys, "frobnicate")
    assert code == 2
    assert out["ok"] is False and out["error"]["code"] == "BAD_ARGS"


def test_bad_option(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(capsys, "schema", "--nope")
    assert code == 2
    assert out["error"]["code"] == "BAD_ARGS"


def test_help_lists_approve(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(capsys, "help")
    assert code == 0
    assert {"name": "approve", "roles": ["manager"]} in out["commands"]


def test_help_command_shows_errors(capsys: pytest.CaptureFixture[str]) -> None:
    _, out = run(capsys, "help", "add")
    assert "TOO_LONG" in out["errors"] and out["roles"] == ["writer", "manager"]
    code, out = run(capsys, "help", "nope")
    assert code == 2 and out["error"]["code"] == "BAD_ARGS"


def test_schema(capsys: pytest.CaptureFixture[str]) -> None:
    _, out = run(capsys, "schema")
    assert len(out["states"]) == 6
    assert len(out["transitions"]) == 12
    assert out["exit_codes"]["TIME_OFFSET_REQUIRED"] == 3
    assert "published" in out["closed_states"]


def test_init(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    code, out = run(capsys, "--home", str(home), "init", "--as", "admin-1")
    assert code == 0 and out["ok"] is True
    assert (home / "brand.db").exists()
    code, _ = run(capsys, "--home", str(home), "--as", "admin-1", "init")
    assert code == 0


def test_init_needs_agent(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    code, out = run(capsys, "--home", str(home), "init")
    assert code == 2 and out["error"]["code"] == "NO_AGENT"
    code, out = run(capsys, "--home", str(home), "init", "--as", "ghost")
    assert code == 2 and out["error"]["code"] == "NO_AGENT"


def test_init_agent_from_env(
    capsys: pytest.CaptureFixture[str], home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRANDCAL_AGENT", "admin-1")
    code, _ = run(capsys, "--home", str(home), "init")
    assert code == 0


def test_init_role_not_allowed(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    code, out = run(capsys, "--home", str(home), "init", "--as", "writer-1")
    assert code == 4 and out["error"]["code"] == "ROLE_NOT_ALLOWED"
    assert not (home / "brand.db").exists()


def test_home_not_configured(capsys: pytest.CaptureFixture[str], home: Path) -> None:
    code, out = run(capsys, "init", "--as", "admin-1")
    assert code == 2 and out["error"]["code"] == "HOME_NOT_CONFIGURED"


def test_pretty(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["schema", "--pretty"]) == 0
    text = capsys.readouterr().out
    assert text.count("\n") > 5
    assert json.loads(text)["ok"] is True


def test_post_types_match_schema(conn) -> None:  # type: ignore[no-untyped-def]
    from brandcal.cli import POST_TYPES

    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'posts'").fetchone()[0]
    for t in POST_TYPES:
        assert f"'{t}'" in sql
    assert sql.count("'comment'") >= 1 and len(POST_TYPES) == 8

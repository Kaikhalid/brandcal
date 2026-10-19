"""Shared helpers for the UI action-layer tests: a CLI home with a console recorder agent."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from conftest import AGENTS, PLATFORMS, WINDOW

from brandcal import cli, posts
from brandcal.config import display_tz, load_config
from brandcal.db import open_db

UI_AGENTS: list[dict[str, str]] = AGENTS + [{"id": "console", "role": "system"}]
CFG: dict[str, Any] = {
    "timezone": "+03:00",
    "agents": UI_AGENTS,
    "serve": {"console_agent": "console"},
}
DATA: dict[str, Any] = {
    "slug": "example-post",
    "title": "Example Co announcement",
    "platform": "linkedin",
    "post_type": "text",
    "window": WINDOW,
    "parts": [{"text": "Hello from Example Co"}],
}
NEW_WINDOW = "2026-03-11T14:00:00+03:00/2026-03-11T15:00:00+03:00"
VERIFIED = {"identity": "approver@example.com", "source": "access-jwt"}


def make_home(path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for var in ("BRANDCAL_HOME", "BRANDCAL_AGENT", "BRANDCAL_TZ"):
        monkeypatch.delenv(var, raising=False)
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text(json.dumps(CFG), encoding="utf-8")
    (path / "platforms.json").write_text(json.dumps(PLATFORMS), encoding="utf-8")
    assert cli.main(["--home", str(path), "init", "--as", "admin-1"]) == 0
    return path


@contextmanager
def open_home(home: Path) -> Iterator[tuple[sqlite3.Connection, dict[str, Any]]]:
    cfg = load_config(home)
    conn = open_db(home / "brand.db", display_tz(cfg))
    try:
        yield conn, cfg
    finally:
        conn.close()


def add_post(home: Path, **extra: Any) -> dict[str, Any]:
    with open_home(home) as (conn, cfg):
        out: dict[str, Any] = posts.add_post(conn, "writer-1", "writer", cfg, {**DATA, **extra})
        return out


def run(capsys: pytest.CaptureFixture[str], home: Path, *argv: str) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    code = cli.main(["--home", str(home), *argv])
    out: dict[str, Any] = json.loads(capsys.readouterr().out)
    return code, out


def cli_approve(
    capsys: pytest.CaptureFixture[str], home: Path, post: dict[str, Any]
) -> dict[str, Any]:
    args = ["approve", post["id"], "--version", str(post["version"]), "--hash", post["hash"]]
    code, out = run(
        capsys,
        home,
        *args,
        "--channel",
        "card",
        "--msg",
        "m1",
        "--words",
        "Yes",
        "--as",
        "manager-1",
    )
    assert code == 0, out
    return out

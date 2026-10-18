"""Tests for scripts/privacy_scan.py.

Sample "bad" strings are assembled at runtime so this file itself stays clean.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "privacy_scan.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("privacy_scan", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ps = _load()
AT = "@"


def reasons(text: str, deny: list[str] | None = None, names: bool = True) -> list[str]:
    return [r for _, r in ps.scan_text(text, ps.compile_denylist(deny or []), names)]


def test_clean_text_passes() -> None:
    text = (
        "Example Co posts at 2026-03-02T09:00:00+01:00/2026-03-02T10:00:00+01:00.\n"
        f"Contact hello{AT}example.com or team{AT}example.org. Version 0.0.1.\n"
        "See https://github.com/example/brandcal and 2026-03-02T09:00:00-05:00.\n"
    )
    assert reasons(text) == []


@pytest.mark.parametrize(
    "text, expected",
    [
        ("ref " + "ab12" * 10, "hex"),
        ("https://demo-site" + ".vercel" + ".app/page", "vercel-app"),
        ("mail someone" + AT + "corp.test", "email"),
        ("call +44 20 " + "7946 0958", "phone"),
        ("call (555) 010-" + "4477", "phone"),
    ],
)
def test_detects(text: str, expected: str) -> None:
    assert any(expected in r for r in reasons(text)), reasons(text)


def test_denylist_whole_word_case_insensitive() -> None:
    deny = ["Zorblax", "acme-secret.test"]
    assert reasons("hello ZORBLAX here", deny)
    assert reasons("see acme-secret.test now", deny)
    assert not reasons("Zorblaxian is a different word", deny)
    assert not reasons("hello ZORBLAX here", deny, names=False)


def test_case_clash() -> None:
    assert ps.case_clashes([Path("docs/A.md"), Path("docs/a.md")])
    assert ps.case_clashes([Path("Docs/x.md"), Path("docs/y.md")])
    assert not ps.case_clashes([Path("docs/a.md"), Path("docs/b.md")])


def test_cli_on_dirty_tree(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text("Copyright (c) 2026 Zorblax\n")
    (tmp_path / "ok.txt").write_text("nothing to see\n")
    deny = tmp_path.parent / f"{tmp_path.name}_deny.txt"
    deny.write_text("# private terms\nZorblax\n")
    env = {"BRANDCAL_DENYLIST": str(deny), "PATH": ""}
    run = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True, env=env
    )
    assert run.returncode == 0, run.stdout  # LICENSE is exempt from the denylist
    (tmp_path / "notes.md").write_text("met zorblax today\n")
    run = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True, env=env
    )
    assert run.returncode == 1
    assert "notes.md:1: denylisted term" in run.stdout

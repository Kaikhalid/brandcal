"""Hand-written: the README quick start runs exactly as written."""

from __future__ import annotations

import io
import json
import re
import shlex
import shutil
import sys
from pathlib import Path

import pytest

from brandcal import cli

ROOT = Path(__file__).resolve().parent.parent
BLOCK = re.compile(r"<!-- quickstart -->\s*```sh\n(.*?)```\s*<!-- /quickstart -->", re.DOTALL)


def test_quickstart_runs_as_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    match = BLOCK.search((ROOT / "README.md").read_text(encoding="utf-8"))
    assert match, "quick start block not found"
    monkeypatch.delenv("BRANDCAL_TZ", raising=False)
    monkeypatch.delenv("BRANDCAL_AGENT", raising=False)
    monkeypatch.chdir(ROOT)
    home = tmp_path / "home"
    home.mkdir()
    ran = 0
    for line in match[1].splitlines():
        if not line.strip():
            continue
        words = shlex.split(line)
        if line.startswith("export BRANDCAL_HOME="):
            monkeypatch.setenv("BRANDCAL_HOME", str(home))
        elif words[0] == "cp" and words[-1] == "$BRANDCAL_HOME/":
            for src in words[1:-1]:
                shutil.copy(ROOT / src, home)
        elif words[0] == "brandcal":
            args = words[1:]
            if "<" in args:
                i = args.index("<")
                text = (ROOT / args[i + 1]).read_text(encoding="utf-8")
                monkeypatch.setattr(sys, "stdin", io.StringIO(text))
                args = args[:i]
            capsys.readouterr()
            assert cli.main(args) == 0, line
            out = json.loads(capsys.readouterr().out)
            assert out["ok"] is True, line
            ran += 1
        else:
            pytest.fail(f"unexpected quick start line: {line}")
    assert ran >= 5

"""Hand-written: docs/ERRORS.md is generated from errors.py and stays in step with it."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from brandcal.errors import EXIT_CODES, ErrorCode

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "ERRORS.md"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "gen_errors_md", ROOT / "scripts/gen_errors_md.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load()


def test_committed_file_matches_the_generator() -> None:
    expected = gen.render((ROOT / "src" / "brandcal" / "errors.py").read_text(encoding="utf-8"))
    assert DOC.read_text(encoding="utf-8") == expected


def test_every_code_appears_once_with_its_exit_code() -> None:
    rows = [line for line in DOC.read_text(encoding="utf-8").splitlines() if line.startswith("| ")]
    cells = [[c.strip() for c in line.strip("|").split("|")] for line in rows[1:]]
    by_code = {c[1].strip("`"): c for c in cells}
    assert len(cells) == len(by_code) == len(ErrorCode)
    for code in ErrorCode:
        assert by_code[code.value][0] == str(int(EXIT_CODES[code]))
        assert by_code[code.value][2]
    exits = [int(c[0]) for c in cells]
    assert exits == sorted(exits)


def test_check_flag(tmp_path: Path) -> None:
    assert gen.main(["--check"]) == 0
    copy = tmp_path / "ERRORS.md"
    copy.write_text(DOC.read_text(encoding="utf-8"), encoding="utf-8")
    assert gen.main(["--check", "--file", str(copy)]) == 0
    copy.write_text(copy.read_text(encoding="utf-8") + "edited\n", encoding="utf-8")
    assert gen.main(["--check", "--file", str(copy)]) == 1
    assert gen.main(["--file", str(copy)]) == 0
    assert gen.main(["--check", "--file", str(copy)]) == 0

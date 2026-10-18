import subprocess
import sys

import brandcal
from brandcal import cli
from brandcal.errors import EXIT_CODES, ErrorCode, ExitCode, exit_code_for


def test_version() -> None:
    assert brandcal.__version__ == "0.0.1"


def test_cli_version(capsys) -> None:  # type: ignore[no-untyped-def]
    try:
        cli.main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    assert "brandcal 0.0.1" in capsys.readouterr().out


def test_cli_version_subprocess() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "brandcal", "--version"], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "brandcal 0.0.1"


def test_cli_help_exits_zero(capsys) -> None:  # type: ignore[no-untyped-def]
    assert cli.main(["help"]) == 0
    assert "Planned commands" in capsys.readouterr().out
    assert cli.main([]) == 0


def test_error_codes_unique() -> None:
    names = [c.name for c in ErrorCode]
    values = [c.value for c in ErrorCode]
    assert len(names) == len(set(names))
    assert len(values) == len(set(values))
    assert all(c.name == c.value for c in ErrorCode)


def test_named_error_codes_present_and_mapped() -> None:
    required = {
        "TIME_OFFSET_REQUIRED",
        "WINDOW_NOT_APPROVED",
        "NATIVELY_SCHEDULED",
        "CHECK_LIVE_FIRST",
        "NO_FRESH_BACKUP",
        "COMMENT_NOT_DELEGATED",
    }
    assert required <= {c.name for c in ErrorCode}
    for code in ErrorCode:
        assert code in EXIT_CODES
        assert exit_code_for(code) not in (ExitCode.OK, 1)

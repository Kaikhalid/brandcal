from __future__ import annotations

from pathlib import Path

import pytest

from brandcal.config import display_tz, home, load_config
from brandcal.errors import BrandcalError, ErrorCode


def test_env_tz_beats_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRANDCAL_TZ", "+03:00")
    tz = display_tz({"timezone": "-05:00"})
    assert tz.utcoffset(None).total_seconds() == 3 * 3600  # type: ignore[union-attr]


def test_config_tz_used_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRANDCAL_TZ", raising=False)
    tz = display_tz({"timezone": "-05:00"})
    assert tz.utcoffset(None).total_seconds() == -5 * 3600  # type: ignore[union-attr]


def test_no_tz_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRANDCAL_TZ", raising=False)
    with pytest.raises(BrandcalError) as exc:
        display_tz({})
    assert exc.value.code == ErrorCode.TZ_NOT_CONFIGURED
    assert exc.value.exit_code == 2


def test_home_requires_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRANDCAL_HOME", raising=False)
    with pytest.raises(BrandcalError) as exc:
        home()
    assert exc.value.code == ErrorCode.HOME_NOT_CONFIGURED


def test_home_explicit_beats_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BRANDCAL_HOME", str(tmp_path / "env"))
    assert home(str(tmp_path / "arg")) == tmp_path / "arg"
    assert home() == tmp_path / "env"


def test_load_config(tmp_path: Path) -> None:
    assert load_config(tmp_path) == {}
    (tmp_path / "config.json").write_text('{"timezone": "Europe/London"}')
    assert load_config(tmp_path) == {"timezone": "Europe/London"}


@pytest.mark.parametrize("text", ["{not json", "[1, 2]"])
def test_bad_config(tmp_path: Path, text: str) -> None:
    (tmp_path / "config.json").write_text(text)
    with pytest.raises(BrandcalError) as exc:
        load_config(tmp_path)
    assert exc.value.code == ErrorCode.BAD_ARGS

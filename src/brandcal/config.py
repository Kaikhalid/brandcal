"""Configuration lookup (SPEC 4, 13). No setting depends on the machine."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import tzinfo
from pathlib import Path
from typing import Any

from brandcal.errors import BrandcalError, ErrorCode
from brandcal.timefmt import resolve_tz


def home(explicit: str | None = None) -> Path:
    """The data directory: explicit value, else BRANDCAL_HOME. There is no default."""
    value = explicit or os.environ.get("BRANDCAL_HOME")
    if not value:
        raise BrandcalError(
            ErrorCode.HOME_NOT_CONFIGURED,
            "No data directory is configured.",
            "Set BRANDCAL_HOME or pass --home PATH.",
        )
    return Path(value)


def load_config(home: Path) -> dict[str, Any]:
    """Load home/config.json, or {} if it does not exist."""
    path = home / "config.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as err:
        raise BrandcalError(ErrorCode.BAD_ARGS, f"Cannot read {path.name}: {err}.") from None
    if not isinstance(data, dict):
        raise BrandcalError(ErrorCode.BAD_ARGS, f"{path.name} must contain a JSON object.")
    return data


def display_tz(cfg: Mapping[str, Any]) -> tzinfo:
    """BRANDCAL_TZ wins over config "timezone"; neither is TZ_NOT_CONFIGURED."""
    value = os.environ.get("BRANDCAL_TZ") or cfg.get("timezone") or ""
    if not isinstance(value, str):
        raise BrandcalError(ErrorCode.BAD_ARGS, '"timezone" must be a string.')
    return resolve_tz(value)

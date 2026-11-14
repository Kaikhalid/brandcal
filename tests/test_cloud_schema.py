"""cloud/schema.sql is generated from src/brandcal/schema.sql and must be current."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cloud_schema_is_current() -> None:
    script = ROOT / "cloud" / "scripts" / "make_schema.py"
    done = subprocess.run([sys.executable, str(script), "--check"], check=False)
    assert done.returncode == 0, "Run: python cloud/scripts/make_schema.py"

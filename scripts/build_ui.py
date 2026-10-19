#!/usr/bin/env python3
"""Build the web UI into src/brandcal/web_next/ (the `make ui` equivalent).

Runs `npm ci` in web/ only if web/node_modules is missing, then `npm run build`, which is
`next build` followed by web/scripts/postbuild.mjs (copy to web_next/ and write csp.json).
Commit the result: pip users never need Node. Needs Node 20 and npm.

Usage: python scripts/build_ui.py
Exit status: 0 on success, otherwise the failing step's status (127 if npm is missing).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def run(npm: str, *args: str) -> int:
    print(f"build_ui: npm --prefix web {' '.join(args)}", flush=True)
    return subprocess.run([npm, "--prefix", str(WEB), *args], check=False).returncode


def main() -> int:
    npm = shutil.which("npm")
    if npm is None:
        print("build_ui: npm not found; install Node 20 (see docs/UI_STYLE.md)", file=sys.stderr)
        return 127
    if not (WEB / "node_modules").is_dir():
        code = run(npm, "ci")
        if code:
            return code
    code = run(npm, "run", "build")
    if code == 0:
        print("build_ui: done; commit src/brandcal/web_next/")
    return code


if __name__ == "__main__":
    sys.exit(main())

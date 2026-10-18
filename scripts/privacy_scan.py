#!/usr/bin/env python3
"""Fail if the repository contains private or personal data.

Checks every tracked or untracked-but-not-ignored text file for:

* 40-character hexadecimal strings (e.g. commit hashes or tokens);
* Vercel deployment URLs (the vercel dot app domain);
* email addresses outside ``example.com`` / ``example.org``;
* phone-number-like strings;
* any term from an optional denylist file named by ``BRANDCAL_DENYLIST``
  (one term per line, ``#`` comments allowed; matched as whole words,
  case-insensitively). The denylist must live outside the repository.
  ``LICENSE`` is exempt from the denylist check (it carries the copyright line).

It also fails if two paths differ only by letter case.

Usage: python scripts/privacy_scan.py [ROOT]
Exit status: 0 if clean, 1 if any finding.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

HEX40 = re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{40}(?![0-9A-Fa-f])")
VERCEL = re.compile(r"\.vercel\.app", re.IGNORECASE)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org"}
PHONE_PATTERNS = (
    # International: +CC then 2-4 further groups of digits.
    re.compile(r"(?<![\w+])\+\d{1,3}[ .-]?\(?\d{1,4}\)?(?:[ .-]?\d{2,4}){2,4}(?!\d)"),
    # North-American style: 3-3-4 digit groups, optionally with brackets.
    re.compile(r"(?<![\w-])\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?![\w-])"),
    # Local numbers with a leading 0 and space-separated digit groups.
    re.compile(r"(?<![\w.:-])0\d{2,4}[ ]\d{3}[ ]\d{3,4}(?![\w-])"),
)
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "node_modules",
    "build",
    "dist",
}
DENYLIST_EXEMPT = {"LICENSE"}


def list_files(root: Path) -> list[Path]:
    """Files git would commit (tracked + untracked, not ignored); walk if not a repo."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
        rels = sorted({p for p in out.decode("utf-8").split("\0") if p})
        return [Path(p) for p in rels if (root / p).is_file()]
    except (OSError, subprocess.CalledProcessError):
        found: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info")
            ]
            for name in filenames:
                found.append((Path(dirpath) / name).relative_to(root))
        return sorted(found)


def load_denylist(path: str | None) -> list[str]:
    if not path:
        return []
    terms: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        term = line.split("#", 1)[0].strip()
        if term:
            terms.append(term)
    return terms


def compile_denylist(terms: Iterable[str]) -> list[tuple[str, re.Pattern[str]]]:
    return [(t, re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)", re.IGNORECASE)) for t in terms]


def scan_text(
    text: str, denylist: list[tuple[str, re.Pattern[str]]], check_names: bool = True
) -> Iterator[tuple[int, str]]:
    """Yield (line number, reason) for each finding in ``text``."""
    for lineno, line in enumerate(text.splitlines(), start=1):
        if HEX40.search(line):
            yield lineno, "40-character hex string"
        if VERCEL.search(line):
            yield lineno, "vercel-app URL"
        for m in EMAIL.finditer(line):
            if m.group(1).lower() not in ALLOWED_EMAIL_DOMAINS:
                yield lineno, f"email address ({m.group(0)})"
        if any(p.search(line) for p in PHONE_PATTERNS):
            yield lineno, "phone-number-like string"
        if check_names:
            for term, pattern in denylist:
                if pattern.search(line):
                    yield lineno, f"denylisted term ({term})"


def case_clashes(paths: Iterable[Path]) -> list[list[str]]:
    seen: dict[str, set[str]] = {}
    for p in paths:
        parts = p.as_posix().split("/")
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            seen.setdefault(prefix.lower(), set()).add(prefix)
    return [sorted(v) for v in seen.values() if len(v) > 1]


def scan(root: Path, denylist_path: str | None) -> list[str]:
    denylist = compile_denylist(load_denylist(denylist_path))
    files = list_files(root)
    findings: list[str] = []
    for rel in files:
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable; not scanned
        check_names = rel.as_posix() not in DENYLIST_EXEMPT
        for lineno, reason in scan_text(text, denylist, check_names):
            findings.append(f"{rel.as_posix()}:{lineno}: {reason}")
        for _, pattern in denylist if check_names else []:
            if pattern.search(rel.as_posix()):
                findings.append(f"{rel.as_posix()}: denylisted term in path")
    for clash in case_clashes(files):
        findings.append(f"case clash: {', '.join(clash)}")
    return findings


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]) if args else Path(__file__).resolve().parent.parent
    findings = scan(root, os.environ.get("BRANDCAL_DENYLIST"))
    for f in findings:
        print(f)
    if findings:
        print(f"privacy scan: {len(findings)} finding(s)", file=sys.stderr)
        return 1
    print("privacy scan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())

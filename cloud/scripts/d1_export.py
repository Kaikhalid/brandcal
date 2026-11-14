#!/usr/bin/env python3
"""Write SQL that loads a brandcal home (brand.db + config.json) into an empty D1 database.

Usage: python cloud/scripts/d1_export.py HOME OUT.sql [--service-token CLIENT_ID] ...

The output starts with cloud/schema.sql, then every row of every table (generated columns
left out, D1 computes them), then the config in meta. The relay block of the config is dropped
(it names files on the old machine). ``--service-token`` lists Access service-token client ids
that may use /api/sync (a client id is not a secret, but keep the output file private: it holds
the whole calendar). Run it on a copy of the home; it only reads.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORDER = (
    "agents",
    "platforms",
    "transitions",
    "archive_lock",
    "posts",
    "parts",
    "media",
    "approvals",
    "events",
)
GENERATED = {"posts": ("window_start_utc", "window_end_utc")}
REPLACE = {"agents", "platforms", "transitions", "archive_lock"}


def literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, bytes):
        return f"X'{value.hex()}'"
    return "'" + str(value).replace("'", "''") + "'"


def export(home: Path, service_tokens: list[str]) -> str:
    conn = sqlite3.connect(f"file:{home / 'brand.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out = [(ROOT / "cloud" / "schema.sql").read_text(encoding="utf-8")]
    try:
        for table in ORDER:
            skip = GENERATED.get(table, ())
            verb = "INSERT OR REPLACE" if table in REPLACE else "INSERT"
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid"):  # noqa: S608
                cols = [c for c in row.keys() if c not in skip]  # noqa: SIM118
                names = ", ".join(f'"{c}"' for c in cols)
                values = ", ".join(literal(row[c]) for c in cols)
                out.append(f"{verb} INTO {table} ({names}) VALUES ({values});")
    finally:
        conn.close()
    cfg = json.loads((home / "config.json").read_text(encoding="utf-8"))
    cfg.pop("relay", None)
    serve = cfg.setdefault("serve", {})
    serve.pop("port", None)
    if service_tokens:
        serve["service_tokens"] = service_tokens
    out.append(f"INSERT OR REPLACE INTO meta (k, v) VALUES ('config', {literal(json.dumps(cfg))});")
    out.append("INSERT OR REPLACE INTO meta (k, v) VALUES ('gen', '1');")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("home", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--service-token", action="append", default=[])
    a = ap.parse_args()
    a.out.write_text(export(a.home, a.service_token), encoding="utf-8")
    a.out.chmod(0o600)


if __name__ == "__main__":
    main()

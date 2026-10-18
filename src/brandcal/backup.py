"""Export, backup and restore test (SPEC 10.6). Files live under the data directory."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from brandcal import audit, events
from brandcal.config import display_tz
from brandcal.db import open_db, transaction
from brandcal.errors import BrandcalError, ErrorCode
from brandcal.publish import stamp

_TABLES: dict[str, str] = {
    "agents": "id",
    "platforms": "id",
    "posts": "id",
    "parts": "id",
    "media": "id",
    "approvals": "id",
    "events": "id",
    "transitions": "from_status, to_status",
}
_DEFAULT_KEEP = {"db": 14, "json": 30}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _rel(path: Path, home: Path) -> str:
    return path.relative_to(home).as_posix()


def _no_backup(message: str) -> BrandcalError:
    return BrandcalError(ErrorCode.NO_FRESH_BACKUP, message, "Run: brandcal backup")


def integrity_problems(path: Path) -> list[str]:
    """PRAGMA integrity_check on a database file; an empty list means ok."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = [str(r[0]) for r in conn.execute("PRAGMA integrity_check")]
        finally:
            conn.close()
    except sqlite3.DatabaseError as err:
        return [str(err)]
    return [] if rows == ["ok"] else rows


def copy_db(conn: sqlite3.Connection, dest: Path) -> None:
    """Copy the live DB with the backup API and verify the copy; never writes to the live DB."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    out = sqlite3.connect(dest)
    try:
        conn.backup(out)
        out.execute("PRAGMA journal_mode = DELETE")  # one self-contained file
    except BaseException:
        out.close()
        dest.unlink(missing_ok=True)
        raise
    out.close()
    problems = integrity_problems(dest)
    if problems:
        for leftover in (dest, Path(f"{dest}-wal"), Path(f"{dest}-shm")):
            leftover.unlink(missing_ok=True)
        raise _no_backup("The database copy failed its integrity check: " + "; ".join(problems[:3]))


def _keep(cfg: Mapping[str, Any], key: str) -> int:
    raw = cfg.get("backup_keep") or {}
    value = raw.get(key, _DEFAULT_KEEP[key]) if isinstance(raw, dict) else _DEFAULT_KEEP[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise BrandcalError(ErrorCode.BAD_ARGS, f'"backup_keep" {key} must be a whole number >= 1.')
    return value


def _prune(folder: Path, pattern: str, keep: int, home: Path) -> list[str]:
    files = sorted(folder.glob(pattern), key=lambda p: p.name)
    old = files[:-keep]
    for path in old:
        path.unlink()
    return [_rel(p, home) for p in old]


def _mirror(src: Path, dest: Path) -> None:
    """Copy files missing from dest (immutable, content-named files)."""
    for file in sorted(src.rglob("*")) if src.is_dir() else []:
        target = dest / file.relative_to(src)
        if file.is_file() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)


def _written_hash(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute(
        "SELECT json_extract(detail, '$.sha256') FROM events WHERE action = 'archive_written'"
        " AND json_extract(detail, '$.file') = ? ORDER BY id DESC LIMIT 1",
        (f"archive/{name}",),
    ).fetchone()
    return None if row is None or row[0] is None else str(row[0])


def _check_archives(conn: sqlite3.Connection, home: Path) -> tuple[list[str], list[dict[str, str]]]:
    copied: list[str] = []
    flags: list[dict[str, str]] = []
    src_dir, dest_dir = home / "archive", home / "backups" / "archive"
    for src in sorted(src_dir.glob("*.sqlite")):
        rel = _rel(src, home)
        actual = _sha256(src)
        expected = _written_hash(conn, src.name) or actual
        if actual != expected:
            detail = "archive file differs from its archive_written checksum"
            flags.append({"kind": "archive_changed", "file": rel, "detail": detail})
            continue
        copy = dest_dir / src.name
        if copy.exists() and _sha256(copy) == expected:
            continue
        if copy.exists():
            detail = "backup copy had a different checksum and was replaced"
            flags.append({"kind": "archive_copy_mismatch", "file": rel, "detail": detail})
            copy.unlink()
        else:
            copied.append(rel)
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, copy)
        copy.chmod(0o444)
    _mirror(src_dir / "media", dest_dir / "media")
    return copied, flags


def backup(
    conn: sqlite3.Connection,
    cfg: Mapping[str, Any],
    home: Path,
    actor: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Checked database copy, its event, media and archive copies, then retention."""
    moment, at, month = stamp(cfg, now)
    dest = home / "backups" / "db" / f"brand-{moment:%Y%m%dT%H%M%S}.sqlite"
    copy_db(conn, dest)
    digest = _sha256(dest)
    detail: dict[str, object] = {
        "file": _rel(dest, home),
        "sha256": digest,
        "local_date": moment.date().isoformat(),
        "integrity": "ok",
    }
    with transaction(conn):
        events.append_event(
            conn, at=at, actor=actor, action="backup_checked",
            chain=events.chain_for(None, month), detail=detail,
        )  # fmt: skip
    _mirror(home / "media", home / "backups" / "media")
    copied, flags = _check_archives(conn, home)
    removed = _prune(dest.parent, "brand-*.sqlite", _keep(cfg, "db"), home)
    return {
        "ok": True, "file": detail["file"], "sha256": digest,
        "archive_copied": copied, "flags": flags, "removed": removed,
    }  # fmt: skip


def export(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], home: Path, now: datetime | None = None
) -> dict[str, Any]:
    """Write every table as JSON from one read snapshot; records no event."""
    moment, at, _ = stamp(cfg, now)
    data: dict[str, Any] = {"exported_at": at}
    conn.execute("BEGIN")
    try:
        for table, order in _TABLES.items():
            cur = conn.execute(f"SELECT * FROM {table} ORDER BY {order}")
            names = [d[0] for d in cur.description]
            data[table] = [dict(zip(names, row, strict=True)) for row in cur.fetchall()]
    finally:
        conn.execute("COMMIT")
    dest = home / "backups" / "json" / f"export-{moment:%Y%m%dT%H%M%S}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(dest)
    _prune(dest.parent, "export-*.json", _keep(cfg, "json"), home)
    return {"ok": True, "file": _rel(dest, home), "counts": {t: len(data[t]) for t in _TABLES}}


def fresh_backup(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], home: Path, now: datetime | None = None
) -> dict[str, Any] | None:
    """Today's (local) passing backup whose file still has the recorded checksum, else None."""
    moment, _, _ = stamp(cfg, now)
    today = moment.date().isoformat()
    rows = conn.execute(
        "SELECT at, detail FROM events WHERE action = 'backup_checked'"
        " AND json_extract(detail, '$.local_date') = ? ORDER BY id DESC",
        (today,),
    ).fetchall()
    for row in rows:
        detail = json.loads(row["detail"])
        path = home / str(detail["file"])
        if path.is_file() and _sha256(path) == detail["sha256"]:
            return {
                "file": detail["file"],
                "sha256": detail["sha256"],
                "local_date": today,
                "at": row["at"],
            }
    return None


def _restored_checks(temp: Path, cfg: Mapping[str, Any], problems: list[str]) -> dict[str, Any]:
    conn = open_db(temp / "brand.db", display_tz(cfg))
    try:
        archives = sorted((temp / "archive").glob("*.sqlite"))
        for file in archives:
            problems += [f"{file.name}: {p}" for p in integrity_problems(file)]
            expected = _written_hash(conn, file.name)
            if expected is not None and _sha256(file) != expected:
                problems.append(f"{file.name}: checksum differs from its archive_written event")
        report = audit.audit(conn, temp)
    finally:
        conn.close()
    problems += [f"{f['kind']} ({f.get('detail', '')})" for f in report["flags"]]
    return {"checked": report["checked"], "archives": len(archives)}


def restore_test(home: Path, cfg: Mapping[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Rebuild the latest backup, media and archives in a temp dir and audit it there."""
    stamp(cfg, now)  # validates the timezone like the other functions
    backups = sorted((home / "backups" / "db").glob("brand-*.sqlite"), key=lambda p: p.name)
    if not backups:
        raise _no_backup("There is no database backup to restore.")
    latest = backups[-1]
    problems: list[str] = []
    result: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="brandcal-restore-") as tmp:
        temp = Path(tmp)
        shutil.copy2(latest, temp / "brand.db")
        for name in ("media", "archive"):
            if (home / "backups" / name).is_dir():
                shutil.copytree(home / "backups" / name, temp / name)
        problems += [f"database: {p}" for p in integrity_problems(temp / "brand.db")]
        if not problems:
            try:
                result = _restored_checks(temp, cfg, problems)
            except sqlite3.DatabaseError as err:
                problems.append(f"database: {err}")
    if problems:
        raise _no_backup(f"Restore test of {latest.name} failed: " + "; ".join(problems[:10]))
    return {
        "ok": True,
        "backup": latest.name,
        "audit": {"checked": result["checked"]},
        "archives": result["archives"],
    }

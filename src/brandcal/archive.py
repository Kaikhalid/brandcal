"""Monthly archive: the atomic run, its resume rules and read-only access (SPEC 10, 8.1)."""

from __future__ import annotations

import calendar
import json
import os
import re
import shutil
import sqlite3
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from importlib import resources
from pathlib import Path
from typing import Any

from brandcal import audit, events, reports
from brandcal.backup import _sha256, fresh_backup
from brandcal.config import display_tz
from brandcal.db import transaction
from brandcal.errors import BrandcalError, ErrorCode
from brandcal.publish import stamp
from brandcal.timefmt import month_key, month_start

_MONTH = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])")
_MONTH_FILE = re.compile(r"(\d{4}-(?:0[1-9]|1[0-2]))\.sqlite")
_MOVED = ("posts", "parts", "media", "approvals", "events")  # in insert order; deleted in reverse
_REFERENCE = ("agents", "platforms", "transitions")  # copied whole, never deleted
_IDS = "(SELECT value FROM json_each(:ids))"
# Tables are written as main.<table> so they never mean the attached archive file.
_WHERE = {
    "posts": f"id IN {_IDS}",
    "parts": f"post_id IN {_IDS}",
    "media": f"part_id IN (SELECT id FROM main.parts WHERE post_id IN {_IDS})",
    "approvals": f"post_id IN {_IDS}",
    "events": f"post_id IN {_IDS} OR chain = :chain",
}
_STAY = "month already archived"


def _kill_point(name: str) -> None:
    """Does nothing; tests replace it to stop a run at "tmp_written", "renamed" or "deleted"."""


@dataclass
class _Ctx:
    conn: sqlite3.Connection
    home: Path
    actor: str
    at: str
    tz: tzinfo
    cutoff: datetime


def _bad_args(message: str, next_step: str = "") -> BrandcalError:
    return BrandcalError(ErrorCode.BAD_ARGS, message, next_step)


def _check_month(month: str) -> str:
    if not _MONTH.fullmatch(month):
        raise _bad_args(f"Month must be YYYY-MM, not {month!r}.", "Use e.g. --month 2026-03")
    return month


def _verify_failed(message: str) -> BrandcalError:
    return BrandcalError(ErrorCode.HASH_MISMATCH, message, "Nothing was lost. Run: brandcal audit")


# --- selection ------------------------------------------------------------------------------


def _params(month: str, ids: list[str]) -> dict[str, str]:
    return {"ids": json.dumps(ids), "chain": f"month:{month}"}


def _eligible(conn: sqlite3.Connection, tz: tzinfo, cutoff: datetime) -> dict[str, list[str]]:
    """Closed posts that ended before the cutoff, by the local month of closed_at (SPEC 10.1)."""
    out: dict[str, list[str]] = {}
    rows = conn.execute(
        "SELECT id, closed_at FROM posts WHERE status IN ('published', 'cancelled')"
        " AND closed_at IS NOT NULL ORDER BY id"
    )
    for r in rows:
        closed = datetime.fromisoformat(r[1])
        if closed.tzinfo is None:
            closed = closed.replace(tzinfo=tz)
        if closed < cutoff:
            out.setdefault(month_key(closed, tz), []).append(r[0])
    return out


def _chain_months(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT substr(chain, 7) FROM events"
        " WHERE chain GLOB 'month:[0-9][0-9][0-9][0-9]-[0-9][0-9]'"
    )
    return {r[0] for r in rows}


def _written_months(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT json_extract(detail, '$.month') FROM events"
        " WHERE action = 'archive_written'"
    )
    return {r[0] for r in rows if r[0]}


def _written(conn: sqlite3.Connection, month: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT detail FROM events WHERE action = 'archive_written'"
        " AND json_extract(detail, '$.file') = ? ORDER BY id DESC LIMIT 1",
        (f"archive/{month}.sqlite",),
    ).fetchone()
    detail: dict[str, Any] | None = None if row is None else json.loads(row[0])
    return detail


def _live_counts(conn: sqlite3.Connection, month: str, ids: list[str]) -> dict[str, int]:
    params = _params(month, ids)
    return {
        t: int(
            conn.execute(f"SELECT COUNT(*) FROM main.{t} WHERE {_WHERE[t]}", params).fetchone()[0]
        )
        for t in _MOVED
    }


def _file_counts(arc: sqlite3.Connection) -> dict[str, int]:
    return {t: int(arc.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) for t in _MOVED}


def _tail(conn: sqlite3.Connection, post_id: str) -> str:
    row = conn.execute(
        "SELECT row_hash FROM events WHERE chain = ? ORDER BY id DESC LIMIT 1", (f"post:{post_id}",)
    ).fetchone()
    return "" if row is None else str(row[0])


# --- the archive file -------------------------------------------------------------------------


def _create(tmp: Path) -> None:
    """The live schema without triggers, journal mode DELETE, plus the manifest table."""
    schema = resources.files("brandcal").joinpath("schema.sql").read_text(encoding="utf-8")
    arc = sqlite3.connect(tmp)
    try:
        arc.executescript(schema)
        for (name,) in arc.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall():
            arc.execute(f'DROP TRIGGER "{name}"')
        arc.execute("PRAGMA journal_mode = DELETE")
        arc.execute(
            "CREATE TABLE manifest (post_id TEXT PRIMARY KEY, last_row_hash TEXT NOT NULL,"
            " status TEXT NOT NULL, closed_at TEXT NOT NULL)"
        )
        arc.commit()
    finally:
        arc.close()


def _columns(conn: sqlite3.Connection, table: str) -> str:
    """Column list for copying: generated columns (hidden 2 or 3) are recomputed, not copied."""
    rows = conn.execute(f"PRAGMA main.table_xinfo({table})").fetchall()
    return ", ".join(f'"{r[1]}"' for r in rows if r[6] not in (2, 3))


def _media_plan(
    conn: sqlite3.Connection, month: str, ids: list[str]
) -> list[tuple[str, str, str, str]]:
    """(media id, live path, archive path, sha256); cancelled media goes to _trash (SPEC 9)."""
    plan = []
    rows = conn.execute(
        "SELECT m.id, m.path, m.sha256, po.status FROM main.media m"
        " JOIN main.parts p ON p.id = m.part_id JOIN main.posts po ON po.id = p.post_id"
        " WHERE po.id IN (SELECT value FROM json_each(?)) ORDER BY m.id",
        (json.dumps(ids),),
    ).fetchall()
    for r in rows:
        rest = str(r[1]).removeprefix("media/")
        if ".." in Path(rest).parts or Path(rest).is_absolute():
            raise BrandcalError(ErrorCode.MEDIA_INVALID, f"Unsafe media path: {r[1]}.")
        trash = "_trash/" if r[3] == "cancelled" else ""
        plan.append((r[0], r[1], f"archive/media/{month}/{trash}{rest}", r[2]))
    return plan


def _copy_media(home: Path, plan: list[tuple[str, str, str, str]]) -> None:
    """Copy each file to its archive path and verify the checksum; a verified copy is kept."""
    for _, old, new, digest in plan:
        src, dst = home / old, home / new
        if dst.is_file() and _sha256(dst) == digest:
            continue
        if not src.is_file() or _sha256(src) != digest:
            raise BrandcalError(
                ErrorCode.MEDIA_INVALID,
                f"{old} is missing or differs from its recorded checksum.",
                "Restore the file from backups/media, then run archive again.",
            )
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.unlink(missing_ok=True)
        shutil.copy2(src, dst)
        if _sha256(dst) != digest:
            dst.unlink()
            raise BrandcalError(ErrorCode.MEDIA_INVALID, f"The copy of {old} failed its checksum.")


def _copy_rows(
    conn: sqlite3.Connection,
    tmp: Path,
    month: str,
    ids: list[str],
    plan: list[tuple[str, str, str, str]],
) -> None:
    """ATTACH the new file and copy the selection in one transaction (SPEC 10.3 step 1)."""
    params = _params(month, ids)
    conn.execute("ATTACH DATABASE ? AS arc", (str(tmp),))
    try:
        conn.execute("BEGIN")
        try:
            for table in (*_REFERENCE, *_MOVED):
                cols = _columns(conn, table)
                where = f" WHERE {_WHERE[table]}" if table in _WHERE else ""
                conn.execute(
                    f"INSERT INTO arc.{table} ({cols}) SELECT {cols} FROM main.{table}{where}",
                    params,
                )
            conn.executemany(
                "UPDATE arc.media SET path = ? WHERE id = ?",
                [(new, mid) for mid, _, new, _ in plan],
            )
            conn.execute(
                "INSERT INTO arc.manifest (post_id, last_row_hash, status, closed_at)"
                " SELECT p.id, COALESCE((SELECT e.row_hash FROM main.events e"
                " WHERE e.chain = 'post:' || p.id ORDER BY e.id DESC LIMIT 1), ''),"
                " p.status, p.closed_at FROM main.posts p WHERE p.id IN " + _IDS + " ORDER BY p.id",
                params,
            )
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.execute("DETACH DATABASE arc")


def _mismatches(
    conn: sqlite3.Connection, arc: sqlite3.Connection, month: str, ids: list[str]
) -> list[str]:
    """Where the archive file differs from the live selection: counts, ids and chain tails."""
    want, have = _live_counts(conn, month, ids), _file_counts(arc)
    out = [f"{t}: {have[t]} rows in the file, {want[t]} live" for t in _MOVED if have[t] != want[t]]
    if [r[0] for r in arc.execute("SELECT id FROM posts ORDER BY id")] != sorted(ids):
        out.append("the file holds different posts")
    manifest = {r[0]: r[1] for r in arc.execute("SELECT post_id, last_row_hash FROM manifest")}
    if set(manifest) != set(ids):
        out.append("the manifest lists different posts")
    for pid in ids:
        if manifest.get(pid) != _tail(conn, pid) or _tail(arc, pid) != _tail(conn, pid):
            out.append(f"{pid}: last row_hash differs from the live chain")
    return out


def _problems(conn: sqlite3.Connection, path: Path, month: str, ids: list[str]) -> list[str]:
    """Everything SPEC 10.3 step 2 checks: live selection, hash chains, foreign keys."""
    try:
        arc = audit.open_archive(path)
        try:
            out = _mismatches(conn, arc, month, ids)
            out += [f"{f['kind']} in {f['chain']}" for f in audit.chain_flags(arc)[0]]
            out += [
                f"foreign key problem in {r[0]}" for r in arc.execute("PRAGMA foreign_key_check")
            ]
        finally:
            arc.close()
    except sqlite3.DatabaseError as err:
        return [f"cannot read the file: {err}"]
    return out


def _detail(arc: sqlite3.Connection, month: str, digest: str) -> dict[str, Any]:
    """The archive_written detail, read from the verified file (SPEC 10.3 step 3, 10.5)."""
    by_platform: dict[str, dict[str, int]] = {}
    urls = []
    for p in arc.execute("SELECT platform, status, platform_url FROM posts ORDER BY id"):
        seen = by_platform.setdefault(p["platform"], {})
        seen[p["status"]] = seen.get(p["status"], 0) + 1
        if p["status"] == "published" and p["platform_url"]:
            urls.append(p["platform_url"])
    failed = arc.execute("SELECT COUNT(*) FROM events WHERE action = 'publish_failed'").fetchone()[
        0
    ]
    return {
        "file": f"archive/{month}.sqlite",
        "sha256": digest,
        "month": month,
        "counts": _file_counts(arc),
        "summary": {"by_platform_status": by_platform, "urls": urls, "failed_attempts": failed},
        "manifest": [
            dict(r)
            for r in arc.execute(
                "SELECT post_id, last_row_hash, status, closed_at FROM manifest ORDER BY post_id"
            )
        ],
    }


# --- the run ------------------------------------------------------------------------------------


def _commit(c: _Ctx, month: str, ids: list[str], final: Path) -> dict[str, Any]:
    """Step 3: delete the moved rows and write archive_written in one transaction."""
    arc = audit.open_archive(final)
    try:
        detail = _detail(arc, month, _sha256(final))
        with transaction(c.conn):
            live = _eligible(c.conn, c.tz, c.cutoff).get(month, [])
            problems = _mismatches(c.conn, arc, month, live)
            if problems:
                raise _verify_failed("The live rows changed during the run: " + "; ".join(problems))
            params = _params(month, live)
            c.conn.execute("UPDATE archive_lock SET active = 1 WHERE id = 1")
            for table in reversed(_MOVED):
                c.conn.execute(f"DELETE FROM main.{table} WHERE {_WHERE[table]}", params)
            events.append_event(
                c.conn, at=c.at, actor=c.actor, action="archive_written", chain="archive",
                detail=detail,
            )  # fmt: skip
            c.conn.execute("UPDATE archive_lock SET active = 0 WHERE id = 1")
    finally:
        arc.close()
    left = c.conn.execute("PRAGMA foreign_key_check").fetchall()
    if left:
        raise _verify_failed(f"Foreign keys are broken after archiving {month}.")
    _kill_point("deleted")
    return detail


def _finish(c: _Ctx, month: str, detail: dict[str, Any], fresh: bool) -> None:
    """Step 4, safe to repeat: live media folders, VACUUM, read-only file, backup copy."""
    removed = False
    for item in detail.get("manifest", []):
        pid = str(item["post_id"])
        folder = c.home / "media" / pid
        if Path(pid).name == pid and folder.is_dir():
            shutil.rmtree(folder)
            removed = True
    if fresh or removed:
        c.conn.execute("VACUUM")
    final = c.home / "archive" / f"{month}.sqlite"
    final.chmod(0o444)
    copy = c.home / "backups" / "archive" / final.name
    if not (copy.is_file() and _sha256(copy) == detail["sha256"]):
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.unlink(missing_ok=True)
        shutil.copy2(final, copy)
    copy.chmod(0o444)


def _archive(c: _Ctx, month: str, ids: list[str]) -> dict[str, Any]:
    final = c.home / "archive" / f"{month}.sqlite"
    tmp = final.with_name(final.name + ".tmp")
    tmp.unlink(missing_ok=True)  # a leftover temp file means the month starts again
    resumed = False
    if final.exists():
        if _problems(c.conn, final, month, ids):
            os.replace(final, final.with_name(final.name + ".stale"))
        else:
            resumed = True  # rows already in a verified file are never copied twice
    counts = _live_counts(c.conn, month, ids)
    if not resumed and not counts["posts"] and not counts["events"]:
        return {"month": month, "action": "nothing", "posts": [], "counts": counts}
    plan = _media_plan(c.conn, month, ids)
    if resumed:
        _copy_media(c.home, plan)
    else:
        final.parent.mkdir(parents=True, exist_ok=True)
        try:
            _create(tmp)
            _copy_media(c.home, plan)
            _copy_rows(c.conn, tmp, month, ids, plan)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        _kill_point("tmp_written")
        problems = _problems(c.conn, tmp, month, ids)
        if problems:
            tmp.unlink(missing_ok=True)
            raise _verify_failed(f"The new {month} archive file failed its checks: {problems[:5]}")
        os.replace(tmp, final)
        _kill_point("renamed")
    detail = _commit(c, month, ids, final)
    _finish(c, month, detail, True)
    return {
        "month": month,
        "action": "resumed" if resumed else "archived",
        "posts": ids,
        "counts": detail["counts"],
    }


def _month(c: _Ctx, month: str, ids: list[str], dry_run: bool) -> tuple[dict[str, Any], list[str]]:
    """One month's entry for the result and the post ids that stay live because it is done."""
    detail = _written(c.conn, month)
    if detail is not None:
        entry: dict[str, Any] = {"month": month, "action": "already_archived", "posts": []}
        if not dry_run:
            path = c.home / str(detail["file"])
            if not path.is_file():
                entry["action"] = "archive_missing"
            elif _sha256(path) != detail["sha256"]:
                entry["action"] = "archive_changed"
            else:
                _finish(c, month, detail, False)
        return entry, ids
    if dry_run:
        counts = _live_counts(c.conn, month, ids)
        action = "would_archive" if counts["posts"] or counts["events"] else "nothing"
        return {"month": month, "action": action, "posts": ids, "counts": counts}, []
    return _archive(c, month, ids), []


def _preconditions(
    conn: sqlite3.Connection, cfg: Mapping[str, Any], home: Path, now: datetime | None
) -> None:
    if fresh_backup(conn, cfg, home, now) is None:
        raise BrandcalError(
            ErrorCode.NO_FRESH_BACKUP,
            "No backup taken today has passed its integrity check.",
            "Run: brandcal backup",
        )
    claimed = [r[0] for r in conn.execute("SELECT id FROM posts WHERE claimed_by IS NOT NULL")]
    if claimed:
        raise BrandcalError(
            ErrorCode.CLAIMED,
            f"Claimed for publishing: {', '.join(sorted(claimed))}.",
            "Finish them with brandcal published or failed, then run archive again.",
        )


def run(
    conn: sqlite3.Connection,
    cfg: Mapping[str, Any],
    home: Path,
    actor: str,
    month: str | None = None,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Archive one month, or every closed month before the current one (SPEC 10.3, 10.4)."""
    moment, at, current = stamp(cfg, now)
    if month is not None:
        _check_month(month)
        if month >= current:
            raise _bad_args(
                f"{month} is not before the current month ({current}).",
                "Only months that have ended can be archived.",
            )
    if not dry_run:
        _preconditions(conn, cfg, home, now)
    tz = display_tz(cfg)
    c = _Ctx(conn, home, actor, at, tz, month_start(moment, tz))
    eligible = _eligible(conn, tz, c.cutoff)
    if month is not None:
        months = [month]
    else:
        known = _chain_months(conn) | _written_months(conn)
        months = sorted(set(eligible) | {m for m in known if m < current})
    entries: list[dict[str, Any]] = []
    left_live: list[dict[str, str]] = []
    for m in months:
        entry, stay = _month(c, m, eligible.get(m, []), dry_run)
        entries.append(entry)
        left_live += [{"id": pid, "month": m, "reason": _STAY} for pid in stay]
    return {"ok": True, "dry_run": dry_run, "months": entries, "left_live": left_live}


# --- reading (SPEC 10.7) --------------------------------------------------------------------------


def open_readonly(home: Path, month: str) -> sqlite3.Connection:
    """The month's archive file, read-only; a missing file is NOT_FOUND."""
    path = home / "archive" / f"{_check_month(month)}.sqlite"
    if not path.is_file():
        raise BrandcalError(
            ErrorCode.NOT_FOUND,
            f"There is no archive file for {month}.",
            "Run: brandcal list --with-archive",
        )
    return audit.open_archive(path)


def overlapping(
    home: Path, lo: date | None, hi: date | None
) -> Iterator[tuple[str, sqlite3.Connection]]:
    """Open each archive file whose month overlaps lo..hi (all files without dates)."""
    for path in sorted((home / "archive").glob("*.sqlite")):
        m = _MONTH_FILE.fullmatch(path.name)
        if m is None:
            continue
        year, mon = int(m[1][:4]), int(m[1][5:])
        first, last = date(year, mon, 1), date(year, mon, calendar.monthrange(year, mon)[1])
        if (lo is not None and last < lo) or (hi is not None and first > hi):
            continue
        arc = audit.open_archive(path)
        try:
            yield m[1], arc
        finally:
            arc.close()


def list_month(home: Path, cfg: Mapping[str, Any], month: str) -> dict[str, Any]:
    arc = open_readonly(home, month)
    try:
        rows = reports.list_posts(arc, cfg, closed=True)
    finally:
        arc.close()
    return {"ok": True, "month": month, "posts": rows}


def show(home: Path, month: str, post_id: str, log: bool = False) -> dict[str, Any]:
    arc = open_readonly(home, month)
    try:
        out = reports.show(arc, post_id, log)
    except BrandcalError as err:
        if err.code is not ErrorCode.NOT_FOUND:
            raise
        raise BrandcalError(
            ErrorCode.NOT_FOUND,
            f"{post_id} is not in the {month} archive.",
            f"brandcal archive list --month {month}",
        ) from None
    finally:
        arc.close()
    return {**out, "archived": True, "month": month}


def search(home: Path, month: str, text: str) -> dict[str, Any]:
    """Posts whose title or any part's text contains text, ignoring case."""
    if not text.strip():
        raise _bad_args("Search text is empty.", "Give a word or phrase to look for.")
    needle = text.casefold()
    arc = open_readonly(home, month)
    try:
        rows = []
        for p in arc.execute("SELECT * FROM posts ORDER BY window_start_utc, id"):
            texts = [p["title"]] + [
                r[0] for r in arc.execute("SELECT text FROM parts WHERE post_id = ?", (p["id"],))
            ]
            if any(needle in t.casefold() for t in texts):
                rows.append(reports.short_row(p))
    finally:
        arc.close()
    return {"ok": True, "month": month, "posts": rows}


def stats(conn: sqlite3.Connection, month: str) -> dict[str, Any]:
    """Monthly totals from the archive_written summary; the file is not opened."""
    detail = _written(conn, _check_month(month))
    if detail is None:
        raise BrandcalError(
            ErrorCode.NOT_FOUND, f"{month} has not been archived.", "Run: brandcal archive run"
        )
    counts = detail.get("counts", {})
    return {
        "ok": True,
        "month": month,
        "file": detail["file"],
        "sha256": detail.get("sha256"),
        "posts": counts.get("posts", 0),
        "counts": counts,
        "summary": detail.get("summary", {}),
    }

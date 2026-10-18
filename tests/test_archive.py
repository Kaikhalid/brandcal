"""Hand-written: monthly archive run, resume, audit anchors and archive reads (SPEC 10, 7.3)."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import stat
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from conftest import AGENTS, PLATFORMS, approve_post, make_post

from brandcal import archive, audit, backup, config, content, events, posts
from brandcal.cli import main
from brandcal.db import init_db, open_db
from brandcal.errors import BrandcalError, ErrorCode
from brandcal.timefmt import resolve_tz

TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 11, 1, 3, 0, 0, tzinfo=TZ)
MOVED = ("posts", "parts", "media", "approvals", "events")
CLAIM_END = "2026-11-01T04:00:00+03:00"


class Killed(Exception):
    pass


def make_home(base: Path, tz_text: str = "+03:00") -> Path:
    base.mkdir(parents=True)
    (base / "config.json").write_text(
        json.dumps({"timezone": tz_text, "agents": AGENTS}), encoding="utf-8"
    )
    conn = open_db(base / "brand.db", resolve_tz(tz_text))
    init_db(conn, AGENTS, PLATFORMS)
    conn.close()
    return base


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return make_home(tmp_path / "home")


@pytest.fixture
def db(home: Path) -> Iterator[sqlite3.Connection]:
    conn = open_db(home / "brand.db", TZ)
    yield conn
    conn.close()


def win(day: str) -> str:
    return f"{day}T09:00:00+03:00/{day}T09:45:00+03:00"


def seed(
    conn: sqlite3.Connection,
    home: Path,
    pid: str,
    status: str = "published",
    closed: str | None = "2026-10-15T12:00:00+03:00",
    *,
    media: bool = True,
    failed: bool = False,
) -> str:
    """A post in any state with a media file under media/<post>/ and a few events."""
    make_post(
        conn,
        id=pid,
        slug=pid,
        title=f"Example Co launch {pid}",
        window=win((closed or "2026-10-25")[:10]),
    )
    if media:
        part_id = conn.execute("SELECT id FROM parts WHERE post_id = ?", (pid,)).fetchone()[0]
        data = f"fake image {pid}".encode()
        digest = hashlib.sha256(data).hexdigest()
        rel = f"media/{pid}/1-1-{digest[:8]}.png"
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_bytes(data)
        conn.execute(
            "INSERT INTO media (id, part_id, pos, kind, path, sha256, alt_text, bytes)"
            " VALUES (?, ?, 1, 'image', ?, ?, 'Example Co photo', ?)",
            (f"m-{pid}", part_id, rel, digest, len(data)),
        )
    content.refresh_hash(conn, pid)
    if status in ("approved", "missed", "published"):
        approve_post(conn, pid)
    late: dict[str, object] = {}
    if status == "published":
        late = {"platform_url": f"https://example.com/{pid}", "published_at": closed}
    if status in ("published", "cancelled"):
        late |= {"closed_at": closed}
    if status == "cancelled":
        late["cancel_kind"] = "idea"
    if status in ("missed", "published", "cancelled"):
        late["status"] = status
    if late:
        sets = ", ".join(f'"{k}" = ?' for k in late)
        conn.execute(f"UPDATE posts SET {sets} WHERE id = ?", (*late.values(), pid))
    at = closed or "2026-10-25T09:00:00+03:00"
    chain = f"post:{pid}"
    events.append_event(
        conn, at=at, actor="writer-1", action="add", chain=chain, post_id=pid,
        to_status="pending_approval",
    )  # fmt: skip
    if failed:
        events.append_event(
            conn, at=at, actor="manager-1", action="publish_failed", chain=chain, post_id=pid,
            reason="platform error",
        )  # fmt: skip
    if status != "pending_approval":
        events.append_event(
            conn, at=at, actor="manager-1", action=status, chain=chain, post_id=pid,
            from_status="approved", to_status=status,
        )  # fmt: skip
    return pid


def scene(conn: sqlite3.Connection, home: Path) -> None:
    """Two October posts that move, an open missed post and one closed in November."""
    seed(conn, home, "p0001", failed=True)
    seed(conn, home, "p0002", "cancelled", "2026-10-20T12:00:00+03:00")
    seed(conn, home, "p0003", "missed", None)
    seed(conn, home, "p0004", closed="2026-11-01T01:00:00+03:00")
    events.append_event(
        conn, at="2026-10-20T10:00:00+03:00", actor="system", action="sweep", chain="month:2026-10"
    )


def ready(conn: sqlite3.Connection, home: Path) -> None:
    scene(conn, home)
    backup.backup(conn, config.load_config(home), home, "admin-1", now=NOW - timedelta(hours=1))


def go(
    conn: sqlite3.Connection,
    home: Path,
    month: str | None = "2026-10",
    now: datetime = NOW,
    dry_run: bool = False,
) -> dict[str, Any]:
    cfg = config.load_config(home)
    return archive.run(conn, cfg, home, "admin-1", month=month, dry_run=dry_run, now=now)


def cli(home: Path, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any]]:
    code = main(["--home", str(home), *argv])
    out: dict[str, Any] = json.loads(capsys.readouterr().out)
    return code, out


def code_of(exc: pytest.ExceptionInfo[BrandcalError]) -> ErrorCode:
    return exc.value.code


def kill_at(monkeypatch: pytest.MonkeyPatch, point: str) -> None:
    def fake(name: str) -> None:
        if name == point:
            raise Killed(name)

    monkeypatch.setattr(archive, "_kill_point", fake)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ids(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT id FROM posts ORDER BY id")]


def written(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT detail FROM events WHERE action = 'archive_written' ORDER BY id")
    return [json.loads(r[0]) for r in rows]


def arc_counts(arc: sqlite3.Connection) -> dict[str, int]:
    return {t: arc.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in MOVED}  # noqa: S608


def live_counts(conn: sqlite3.Connection, pids: list[str], month: str) -> dict[str, int]:
    marks = ",".join("?" for _ in pids)
    sub = f"SELECT id FROM parts WHERE post_id IN ({marks})"
    queries = {
        "posts": (f"SELECT COUNT(*) FROM posts WHERE id IN ({marks})", pids),
        "parts": (f"SELECT COUNT(*) FROM parts WHERE post_id IN ({marks})", pids),
        "media": (f"SELECT COUNT(*) FROM media WHERE part_id IN ({sub})", pids),
        "approvals": (f"SELECT COUNT(*) FROM approvals WHERE post_id IN ({marks})", pids),
        "events": (
            f"SELECT COUNT(*) FROM events WHERE post_id IN ({marks}) OR chain = ?",
            [*pids, f"month:{month}"],
        ),
    }
    return {t: conn.execute(q, args).fetchone()[0] for t, (q, args) in queries.items()}


# --- preconditions and selection ----------------------------------------------------------


def test_run_needs_a_fresh_backup_and_no_claim(
    home: Path, db: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    seed(db, home, "p0001")
    code, out = cli(home, capsys, "archive", "run", "--as", "admin-1")
    assert code == 5 and out["error"]["code"] == "NO_FRESH_BACKUP"
    assert not (home / "archive").exists()
    assert cli(home, capsys, "backup", "--as", "admin-1")[0] == 0
    seed(db, home, "p0002", "approved", None)
    db.execute(
        "UPDATE posts SET claimed_by = 'manager-1', claim_expires = ? WHERE id = 'p0002'",
        (CLAIM_END,),
    )
    code, out = cli(home, capsys, "archive", "run", "--as", "admin-1")
    assert code == 8 and out["error"]["code"] == "CLAIMED"
    assert ids(db) == ["p0001", "p0002"] and not (home / "archive").exists()


def test_run_roles_and_month_arguments(
    home: Path, db: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = cli(home, capsys, "archive", "run", "--as", "writer-1")
    assert code == 4 and out["error"]["code"] == "ROLE_NOT_ALLOWED"
    code, out = cli(home, capsys, "archive", "run")
    assert code == 2 and out["error"]["code"] == "NO_AGENT"
    for month in ("2026-11", "2026-12", "2026-13", "nov"):
        with pytest.raises(BrandcalError) as exc:
            go(db, home, month)
        assert code_of(exc) is ErrorCode.BAD_ARGS


@pytest.mark.parametrize(
    ("tz_text", "inside", "outside"),
    [
        ("+03:00", "2026-10-31T23:30:00+03:00", "2026-11-01T01:00:00+03:00"),
        ("-05:00", "2026-10-31T22:00:00-05:00", "2026-11-01T00:30:00-05:00"),
        ("+03:00", "2026-10-31T20:30:00+00:00", "2026-10-31T22:30:00+00:00"),
    ],
)
def test_only_closed_posts_before_the_local_month_start_move(
    tmp_path: Path, tz_text: str, inside: str, outside: str
) -> None:
    tz = resolve_tz(tz_text)
    home = make_home(tmp_path / "h", tz_text)
    conn = open_db(home / "brand.db", tz)
    seed(conn, home, "p0001", closed=inside)
    seed(conn, home, "p0002", closed=outside)
    seed(conn, home, "p0003", "missed", None)
    cfg = config.load_config(home)
    now = datetime(2026, 11, 1, 3, 0, tzinfo=tz)
    backup.backup(conn, cfg, home, "admin-1", now=now - timedelta(hours=1))
    out = archive.run(conn, cfg, home, "admin-1", now=now)
    assert ids(conn) == ["p0002", "p0003"]  # the missed post and the November one stay
    assert [m["month"] for m in out["months"]] == ["2026-10"]
    assert [p.name for p in (home / "archive").glob("*.sqlite")] == ["2026-10.sqlite"]
    arc = archive.open_readonly(home, "2026-10")
    assert [r[0] for r in arc.execute("SELECT id FROM posts")] == ["p0001"]
    conn.close()


def test_without_month_every_earlier_month_with_posts_or_events(
    home: Path, db: sqlite3.Connection
) -> None:
    ready(db, home)
    seed(db, home, "p0005", closed="2026-09-10T12:00:00+03:00")
    events.append_event(
        db, at="2026-08-05T10:00:00+03:00", actor="system", action="sweep", chain="month:2026-08"
    )
    out = go(db, home, None)
    assert [m["month"] for m in out["months"]] == ["2026-08", "2026-09", "2026-10"]
    assert sorted(p.name for p in (home / "archive").glob("*.sqlite")) == [
        "2026-08.sqlite", "2026-09.sqlite", "2026-10.sqlite",
    ]  # fmt: skip
    assert ids(db) == ["p0003", "p0004"]
    assert [d["month"] for d in written(db)] == ["2026-08", "2026-09", "2026-10"]
    left = db.execute(
        "SELECT COUNT(*) FROM events WHERE chain LIKE 'month:%' AND chain <> 'month:2026-11'"
    )
    assert left.fetchone()[0] == 0


def test_dry_run_reports_and_writes_nothing(home: Path, db: sqlite3.Connection) -> None:
    scene(db, home)  # no backup and no claim check: a dry run skips both
    before = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    out = go(db, home, dry_run=True)
    (month,) = out["months"]
    assert month["month"] == "2026-10" and month["posts"] == ["p0001", "p0002"]
    assert month["counts"] == live_counts(db, ["p0001", "p0002"], "2026-10")
    assert not (home / "archive").exists() and not (home / "backups").exists()
    assert ids(db) == ["p0001", "p0002", "p0003", "p0004"]
    assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == before


# --- the run --------------------------------------------------------------------------------


def test_counts_checksums_foreign_keys_and_media(
    home: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready(db, home)
    expected = live_counts(db, ["p0001", "p0002"], "2026-10")
    assert all(n > 0 for n in expected.values())
    seen: dict[str, bool] = {}

    def spy(name: str) -> None:
        if name == "renamed":
            seen["folder"] = (home / "media" / "p0001").is_dir()

    monkeypatch.setattr(archive, "_kill_point", spy)
    go(db, home)
    assert seen == {"folder": True}  # live media is only removed after the commit
    arc = archive.open_readonly(home, "2026-10")
    assert arc_counts(arc) == expected
    (detail,) = written(db)
    assert detail["counts"] == expected and detail["month"] == "2026-10"
    assert detail["file"] == "archive/2026-10.sqlite"
    assert detail["sha256"] == sha(home / "archive" / "2026-10.sqlite")
    assert arc.execute("PRAGMA foreign_key_check").fetchall() == []
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    for table in ("agents", "platforms", "transitions"):
        count = f"SELECT COUNT(*) FROM {table}"  # noqa: S608
        assert arc.execute(count).fetchone()[0] == db.execute(count).fetchone()[0]
    paths = {r["id"]: r["path"] for r in arc.execute("SELECT id, path FROM media")}
    assert paths["m-p0001"].startswith("archive/media/2026-10/p0001/")
    assert paths["m-p0002"].startswith("archive/media/2026-10/_trash/p0002/")
    for row in arc.execute("SELECT path, sha256 FROM media"):
        assert sha(home / row["path"]) == row["sha256"]
    assert not (home / "media" / "p0001").exists() and not (home / "media" / "p0002").exists()
    assert (home / "media" / "p0003").is_dir() and (home / "media" / "p0004").is_dir()
    assert db.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 2
    assert ids(db) == ["p0003", "p0004"]


def test_summary_and_manifest_in_the_event(home: Path, db: sqlite3.Connection) -> None:
    ready(db, home)
    go(db, home)
    (detail,) = written(db)
    assert detail["summary"] == {
        "by_platform_status": {"linkedin": {"cancelled": 1, "published": 1}},
        "urls": ["https://example.com/p0001"],
        "failed_attempts": 1,
    }
    arc = archive.open_readonly(home, "2026-10")
    for item in detail["manifest"]:
        last = arc.execute(
            "SELECT row_hash FROM events WHERE chain = ? ORDER BY id DESC LIMIT 1",
            (f"post:{item['post_id']}",),
        ).fetchone()[0]
        assert item["last_row_hash"] == last
    assert [(m["post_id"], m["status"]) for m in detail["manifest"]] == [
        ("p0001", "published"), ("p0002", "cancelled"),
    ]  # fmt: skip
    assert arc.execute("SELECT COUNT(*) FROM manifest").fetchone()[0] == 2
    # the event sits on its own chain and stays in the live database
    row = db.execute("SELECT chain, post_id, actor FROM events WHERE action = 'archive_written'")
    assert tuple(row.fetchone()) == ("archive", None, "admin-1")
    assert db.execute("SELECT COUNT(*) FROM archive_lock WHERE active = 1").fetchone()[0] == 0


def snapshot(home: Path) -> dict[str, Any]:
    conn = open_db(home / "brand.db", TZ)
    try:
        details = written(conn)
        live = ids(conn)
        folders = sorted(p.name for p in (home / "media").glob("*"))
    finally:
        conn.close()
    (detail,) = [d for d in details if d["month"] == "2026-10"]
    path = home / "archive" / "2026-10.sqlite"
    arc = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = {t: arc.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in MOVED}  # noqa: S608
        post_ids = [r[0] for r in arc.execute("SELECT id FROM posts ORDER BY id")]
        hashes = sorted(r[0] for r in arc.execute("SELECT row_hash FROM events"))
    finally:
        arc.close()
    copy = home / "backups" / "archive" / "2026-10.sqlite"
    assert sha(path) == detail["sha256"] == sha(copy)
    assert stat.S_IMODE(path.stat().st_mode) == 0o444 == stat.S_IMODE(copy.stat().st_mode)
    media = sorted(
        p.relative_to(home).as_posix() for p in (home / "archive" / "media").rglob("*.png")
    )
    assert not list((home / "archive").glob("*.tmp")) and not list(
        (home / "archive").glob("*.stale")
    )
    return {
        "live": live, "folders": folders, "rows": rows, "post_ids": post_ids, "hashes": hashes,
        "counts": detail["counts"], "manifest": detail["manifest"], "media": media,
    }  # fmt: skip


@pytest.mark.parametrize("point", ["tmp_written", "renamed", "deleted"])
def test_killed_run_resumes_to_the_same_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, point: str
) -> None:
    states = []
    for name in ("clean", "killed"):
        home = make_home(tmp_path / name)
        conn = open_db(home / "brand.db", TZ)
        ready(conn, home)
        if name == "killed":
            with monkeypatch.context() as m:
                kill_at(m, point)
                with pytest.raises(Killed):
                    go(conn, home)
            if point == "tmp_written":
                assert (home / "archive" / "2026-10.sqlite.tmp").exists()
            if point == "renamed":
                assert not written(conn)
            if point == "deleted":
                assert len(written(conn)) == 1 and (home / "media" / "p0001").exists()
        out = go(conn, home)
        assert out["months"][0]["action"] in ("archived", "resumed", "already_archived")
        assert len(written(conn)) == 1  # exactly one archive_written for the month
        conn.close()
        states.append(snapshot(home))
    assert states[0] == states[1]
    assert states[0]["live"] == ["p0003", "p0004"] and states[0]["folders"] == ["p0003", "p0004"]
    assert states[0]["rows"]["posts"] == 2  # no duplicates


def test_second_run_does_nothing(home: Path, db: sqlite3.Connection) -> None:
    ready(db, home)
    assert go(db, home)["months"][0]["action"] == "archived"
    path = home / "archive" / "2026-10.sqlite"
    first = path.read_bytes()
    n = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    for month in ("2026-10", None):
        out = go(db, home, month)
        assert [m["action"] for m in out["months"]] == ["already_archived"]
    assert path.read_bytes() == first
    assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == n
    assert len(written(db)) == 1


def test_eligible_post_in_an_archived_month_stays_live(home: Path, db: sqlite3.Connection) -> None:
    ready(db, home)
    go(db, home)
    first = (home / "archive" / "2026-10.sqlite").read_bytes()
    seed(db, home, "p0005", closed="2026-10-28T12:00:00+03:00")
    out = go(db, home, None)
    assert out["left_live"] == [
        {"id": "p0005", "month": "2026-10", "reason": "month already archived"}
    ]
    assert "p0005" in ids(db) and len(written(db)) == 1
    assert (home / "archive" / "2026-10.sqlite").read_bytes() == first


def test_month_file_that_no_longer_matches_is_set_aside(
    home: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready(db, home)
    with monkeypatch.context() as m:
        kill_at(m, "renamed")
        with pytest.raises(Killed):
            go(db, home)
    seed(db, home, "p0005", closed="2026-10-28T12:00:00+03:00")  # arrived after the file was made
    go(db, home)
    assert (home / "archive" / "2026-10.sqlite.stale").exists()
    arc = archive.open_readonly(home, "2026-10")
    assert [r[0] for r in arc.execute("SELECT id FROM posts ORDER BY id")] == [
        "p0001", "p0002", "p0005",
    ]  # fmt: skip
    assert ids(db) == ["p0003", "p0004"] and len(written(db)) == 1


def test_matching_month_file_is_not_copied_twice(
    home: Path, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready(db, home)
    with monkeypatch.context() as m:
        kill_at(m, "renamed")
        with pytest.raises(Killed):
            go(db, home)
    path = home / "archive" / "2026-10.sqlite"
    first = path.read_bytes()
    go(db, home)
    assert path.read_bytes() == first and not path.with_name(path.name + ".stale").exists()


def test_changed_live_media_stops_the_run(home: Path, db: sqlite3.Connection) -> None:
    ready(db, home)
    (next((home / "media" / "p0001").iterdir())).write_bytes(b"not the original")
    with pytest.raises(BrandcalError) as exc:
        go(db, home)
    assert code_of(exc) is ErrorCode.MEDIA_INVALID
    assert ids(db) == ["p0001", "p0002", "p0003", "p0004"]
    assert not list((home / "archive").glob("*.sqlite*"))


# --- audit anchors ---------------------------------------------------------------------------


def make_writable(path: Path) -> None:
    path.chmod(0o644)


def kinds(report: dict[str, Any]) -> set[str]:
    return {f["kind"] for f in report["flags"]}


def test_audit_is_clean_after_a_run(home: Path, db: sqlite3.Connection) -> None:
    ready(db, home)
    go(db, home)
    report = audit.audit(db, home)
    assert report["ok"] and report["checked"]["archives"] == 1


def test_audit_flags_a_post_missing_from_the_archive_file(
    home: Path, db: sqlite3.Connection
) -> None:
    ready(db, home)
    go(db, home)
    path = home / "archive" / "2026-10.sqlite"
    make_writable(path)
    arc = sqlite3.connect(path)
    arc.execute("DELETE FROM posts WHERE id = 'p0001'")
    arc.commit()
    arc.close()
    report = audit.audit(db, home)
    flags = [f for f in report["flags"] if f["kind"] == "archive_post_missing"]
    assert [f["post"] for f in flags] == ["p0001"] and flags[0]["file"] == "archive/2026-10.sqlite"
    assert "archive_changed" in kinds(report)


def test_audit_flags_a_deleted_last_event(home: Path, db: sqlite3.Connection) -> None:
    ready(db, home)
    go(db, home)
    path = home / "archive" / "2026-10.sqlite"
    make_writable(path)
    arc = sqlite3.connect(path)
    arc.execute(
        "DELETE FROM events WHERE id = (SELECT MAX(id) FROM events WHERE chain = 'post:p0002')"
    )
    arc.commit()
    arc.close()
    report = audit.audit(db, home)
    tails = [f for f in report["flags"] if f["kind"] == "archive_chain_tail"]
    assert [f["post"] for f in tails] == ["p0002"]
    assert "archive_chain" not in kinds(report)  # the chain inside the file still links up


def test_audit_flags_a_broken_chain_inside_the_file(home: Path, db: sqlite3.Connection) -> None:
    ready(db, home)
    go(db, home)
    path = home / "archive" / "2026-10.sqlite"
    make_writable(path)
    arc = sqlite3.connect(path)
    arc.execute("UPDATE events SET reason = 'edited' WHERE chain = 'post:p0001' AND action = 'add'")
    arc.commit()
    arc.close()
    assert {"archive_chain", "archive_changed"} <= kinds(audit.audit(db, home))


def test_audit_flags_missing_file_and_published_media_but_not_trash(
    home: Path, db: sqlite3.Connection
) -> None:
    ready(db, home)
    go(db, home)
    base = home / "archive" / "media" / "2026-10"
    next((base / "_trash" / "p0002").iterdir()).unlink()
    assert audit.audit(db, home)["ok"]  # the audit expects trash to be removable
    next((base / "p0001").iterdir()).write_bytes(b"changed")
    report = audit.audit(db, home)
    assert kinds(report) == {"archive_media"}
    next((base / "p0001").iterdir()).unlink()
    assert kinds(audit.audit(db, home)) == {"archive_media"}
    (home / "archive" / "2026-10.sqlite").unlink()
    assert kinds(audit.audit(db, home)) == {"archive_missing"}


# --- the archive file and reading it -----------------------------------------------------------


def test_archive_file_is_read_only_without_triggers(home: Path, db: sqlite3.Connection) -> None:
    ready(db, home)
    go(db, home)
    path = home / "archive" / "2026-10.sqlite"
    assert stat.S_IMODE(path.stat().st_mode) == 0o444
    copy = home / "backups" / "archive" / "2026-10.sqlite"
    assert stat.S_IMODE(copy.stat().st_mode) == 0o444 and sha(copy) == sha(path)
    arc = archive.open_readonly(home, "2026-10")
    assert (
        arc.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger'").fetchone()[0] == 0
    )
    with pytest.raises(sqlite3.OperationalError):
        arc.execute("DELETE FROM posts")
    arc.close()
    with pytest.raises(BrandcalError) as exc:
        archive.open_readonly(home, "2026-09")
    assert code_of(exc) is ErrorCode.NOT_FOUND


def test_archived_ids_are_never_reused_and_say_archived(
    home: Path,
    db: sqlite3.Connection,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for n in (1, 2, 3):
        seed(db, home, f"p000{n}")
    backup.backup(db, config.load_config(home), home, "admin-1", now=NOW - timedelta(hours=1))
    go(db, home)
    assert ids(db) == [] and posts.next_post_id(db) == "p0004"
    payload = {
        "slug": "example-post", "title": "Example Co next", "platform": "linkedin",
        "post_type": "text", "window": win("2026-12-01"), "parts": [{"text": "Hello"}],
    }  # fmt: skip
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    code, out = cli(home, capsys, "add", "--as", "writer-1")
    assert code == 0 and out["id"] == "p0004"
    code, out = cli(home, capsys, "show", "p0001")
    assert code == 7 and out["error"]["code"] == "ARCHIVED"
    assert "archive show p0001 --month 2026-10" in out["error"]["next"]
    code, out = cli(home, capsys, "edit", "p0002", "title=Changed", "--as", "writer-1")
    assert code == 7 and out["error"]["code"] == "ARCHIVED"
    code, out = cli(home, capsys, "show", "p0099")
    assert code == 7 and out["error"]["code"] == "NOT_FOUND"


def test_list_with_archive_and_archive_reads(
    home: Path, db: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    ready(db, home)
    go(db, home)
    code, out = cli(home, capsys, "list", "--closed")
    assert [p["id"] for p in out["posts"]] == ["p0003", "p0004"]
    code, out = cli(home, capsys, "list", "--with-archive")
    rows = {p["id"]: p for p in out["posts"]}
    assert code == 0 and sorted(rows) == ["p0001", "p0002", "p0003"]
    assert rows["p0001"]["archived"] is True and rows["p0001"]["month"] == "2026-10"
    assert "archived" not in rows["p0003"]
    _, out = cli(home, capsys, "list", "--with-archive", "--status", "published")
    assert [p["id"] for p in out["posts"]] == ["p0001", "p0004"]  # archived, then live
    _, out = cli(home, capsys, "list", "--with-archive", "--status", "cancelled")
    assert [(p["id"], p["archived"]) for p in out["posts"]] == [("p0002", True)]
    _, out = cli(home, capsys, "list", "--with-archive", "--platform", "x")
    assert out["posts"] == []
    _, out = cli(
        home, capsys, "list", "--with-archive", "--from", "2026-10-16", "--to", "2026-10-31"
    )
    assert [p["id"] for p in out["posts"]] == ["p0002", "p0003"]
    _, out = cli(home, capsys, "list", "--with-archive", "--from", "2026-11-01")
    assert [p["id"] for p in out["posts"]] == []

    _, out = cli(home, capsys, "archive", "list", "--month", "2026-10")
    assert [p["id"] for p in out["posts"]] == ["p0001", "p0002"] and "window" in out["posts"][0]
    code, out = cli(home, capsys, "archive", "show", "p0001", "--month", "2026-10", "--log")
    assert code == 0 and out["id"] == "p0001" and out["parts"][0]["text"].startswith("Hello")
    assert out["media"][0]["path"].startswith("archive/media/2026-10/p0001/")
    assert [e["action"] for e in out["events"]] == ["add", "publish_failed", "published"]
    code, out = cli(home, capsys, "archive", "show", "p0003", "--month", "2026-10")
    assert code == 7 and out["error"]["code"] == "NOT_FOUND"
    _, out = cli(home, capsys, "archive", "search", "LAUNCH P0002", "--month", "2026-10")
    assert [p["id"] for p in out["posts"]] == ["p0002"]
    _, out = cli(home, capsys, "archive", "search", "hello from EXAMPLE", "--month", "2026-10")
    assert [p["id"] for p in out["posts"]] == ["p0001", "p0002"]
    (home / "archive" / "2026-10.sqlite").unlink()  # stats come from the event, not the file
    code, out = cli(home, capsys, "archive", "stats", "--month", "2026-10")
    assert code == 0 and out["posts"] == 2 and out["summary"]["failed_attempts"] == 1
    assert out["counts"]["events"] > 0 and out["sha256"] == written(db)[0]["sha256"]
    code, out = cli(home, capsys, "archive", "list", "--month", "2026-10")
    assert code == 7 and out["error"]["code"] == "NOT_FOUND"
    code, out = cli(home, capsys, "archive", "stats", "--month", "2026-09")
    assert code == 7 and out["error"]["code"] == "NOT_FOUND"


def test_restore_test_and_audit_after_a_run(
    home: Path, db: sqlite3.Connection, capsys: pytest.CaptureFixture[str]
) -> None:
    ready(db, home)
    go(db, home)
    code, out = cli(home, capsys, "backup", "restore-test", "--as", "admin-1")
    assert code == 0 and out["ok"]
    cfg = config.load_config(home)
    backup.backup(db, cfg, home, "admin-1", now=NOW + timedelta(minutes=1))  # now holds the event
    code, out = cli(home, capsys, "backup", "restore-test", "--as", "admin-1")
    assert code == 0 and out["archives"] == 1
    report = audit.audit(db, home)
    assert report["ok"], report["flags"]
    code, out = cli(home, capsys, "audit")
    assert code == 0 and out["ok"] and out["checked"]["archives"] == 1

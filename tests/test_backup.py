"""Hand-written: export, backup, archive file copies, retention and restore-test (SPEC 10.6)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from conftest import AGENTS, PLATFORMS, make_post

from brandcal import backup, events
from brandcal.cli import main
from brandcal.db import init_db, open_db
from brandcal.errors import BrandcalError, ErrorCode

TZ = timezone(timedelta(hours=3))
CFG: dict[str, Any] = {"timezone": "+03:00", "agents": AGENTS}
CFG_W: dict[str, Any] = {**CFG, "timezone": "-05:00"}
NOW = datetime(2026, 3, 10, 9, 30, 15, tzinfo=TZ)
STAMP = "2026-03-10T09:30:15+03:00"


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    (path / "config.json").write_text(json.dumps(CFG), encoding="utf-8")
    db = open_db(path / "brand.db", TZ)
    init_db(db, AGENTS, PLATFORMS)
    db.close()
    return path


@pytest.fixture
def db(home: Path) -> Iterator[sqlite3.Connection]:
    conn = open_db(home / "brand.db", TZ)
    yield conn
    conn.close()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def backup_events(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM events WHERE action = 'backup_checked'").fetchall()


def make_archive(home: Path, month: str = "2026-02") -> Path:
    path = home / "archive" / f"{month}.sqlite"
    path.parent.mkdir(exist_ok=True)
    arc = sqlite3.connect(path)
    arc.execute("CREATE TABLE t (x TEXT)")
    arc.execute("INSERT INTO t VALUES ('Example Co')")
    arc.commit()
    arc.close()
    return path


def written(conn: sqlite3.Connection, name: str, digest: str) -> None:
    events.append_event(
        conn, at=STAMP, actor="system", action="archive_written", chain="month:2026-03",
        detail={"file": f"archive/{name}", "sha256": digest},
    )  # fmt: skip


def codes(exc: pytest.ExceptionInfo[BrandcalError]) -> ErrorCode:
    return exc.value.code


def test_copy_includes_wal_but_not_uncommitted(
    db: sqlite3.Connection, home: Path, tmp_path: Path
) -> None:
    make_post(db)
    other = open_db(home / "brand.db", TZ)
    other.execute("BEGIN IMMEDIATE")
    make_post(other, id="p0002", slug="second-post")
    dest = tmp_path / "copy.sqlite"
    backup.copy_db(db, dest)
    other.execute("ROLLBACK")
    other.close()
    copy = sqlite3.connect(dest)
    ids = [r[0] for r in copy.execute("SELECT id FROM posts ORDER BY id")]
    copy.close()
    assert ids == ["p0001"]
    assert backup.integrity_problems(dest) == []


def test_backup_event_and_fresh_backup(db: sqlite3.Connection, home: Path) -> None:
    make_post(db)
    out = backup.backup(db, CFG, home, "admin-1", NOW)
    assert out["ok"] is True
    assert out["file"] == "backups/db/brand-20260310T093015.sqlite"
    copy = home / out["file"]
    assert out["sha256"] == sha(copy)
    assert backup.integrity_problems(copy) == []
    (ev,) = backup_events(db)
    assert (ev["actor"], ev["post_id"], ev["chain"]) == ("admin-1", None, "month:2026-03")
    assert json.loads(ev["detail"]) == {
        "file": out["file"], "sha256": out["sha256"], "local_date": "2026-03-10", "integrity": "ok",
    }  # fmt: skip
    found = backup.fresh_backup(db, CFG, home, NOW + timedelta(hours=1))
    assert found is not None and found["file"] == out["file"]
    assert backup.fresh_backup(db, CFG, home, NOW + timedelta(days=1)) is None
    copy.write_bytes(copy.read_bytes() + b"x")
    assert backup.fresh_backup(db, CFG, home, NOW) is None


def test_local_date_uses_configured_offset(db: sqlite3.Connection, home: Path) -> None:
    late = datetime(2026, 3, 10, 23, 30, tzinfo=timezone(timedelta(hours=-5)))
    out = backup.backup(db, CFG_W, home, "admin-1", late)
    assert out["file"] == "backups/db/brand-20260310T233000.sqlite"
    assert json.loads(backup_events(db)[0]["detail"])["local_date"] == "2026-03-10"
    assert backup.fresh_backup(db, CFG_W, home, late) is not None
    assert backup.fresh_backup(db, CFG, home, late) is None  # +03:00 is already 2026-03-11


def test_integrity_failure_leaves_nothing(
    db: sqlite3.Connection, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backup, "integrity_problems", lambda path: ["row 1 missing"])
    with pytest.raises(BrandcalError) as exc:
        backup.backup(db, CFG, home, "admin-1", NOW)
    assert codes(exc) is ErrorCode.NO_FRESH_BACKUP
    assert backup_events(db) == []
    assert list((home / "backups" / "db").iterdir()) == []


def test_archive_missing_copy_is_made_read_only(db: sqlite3.Connection, home: Path) -> None:
    src = make_archive(home)
    written(db, "2026-02.sqlite", sha(src))
    (home / "archive" / "2026-03.sqlite.tmp").write_bytes(b"partial")
    media = home / "archive" / "media" / "2026-02"
    media.mkdir(parents=True)
    (media / "a.png").write_bytes(b"png")
    out = backup.backup(db, CFG, home, "admin-1", NOW)
    copy = home / "backups" / "archive" / "2026-02.sqlite"
    assert out["archive_copied"] == ["archive/2026-02.sqlite"]
    assert out["flags"] == []
    assert sha(copy) == sha(src)
    assert copy.stat().st_mode & 0o777 == 0o444
    assert (home / "backups" / "archive" / "media" / "2026-02" / "a.png").read_bytes() == b"png"
    assert not (home / "backups" / "archive" / "2026-03.sqlite.tmp").exists()
    again = backup.backup(db, CFG, home, "admin-1", NOW + timedelta(minutes=1))
    assert again["archive_copied"] == [] and again["flags"] == []


def test_archive_copy_with_wrong_checksum_is_replaced(db: sqlite3.Connection, home: Path) -> None:
    src = make_archive(home)
    written(db, "2026-02.sqlite", sha(src))
    bad = home / "backups" / "archive" / "2026-02.sqlite"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"damaged")
    bad.chmod(0o444)
    out = backup.backup(db, CFG, home, "admin-1", NOW)
    assert [f["kind"] for f in out["flags"]] == ["archive_copy_mismatch"]
    assert sha(bad) == sha(src)


def test_changed_source_archive_is_flagged_and_not_copied(
    db: sqlite3.Connection, home: Path
) -> None:
    src = make_archive(home)
    written(db, "2026-02.sqlite", "0" * 64)
    out = backup.backup(db, CFG, home, "admin-1", NOW)
    assert [(f["kind"], f["file"]) for f in out["flags"]] == [
        ("archive_changed", "archive/2026-02.sqlite")
    ]
    assert out["archive_copied"] == []
    assert src.exists() and not (home / "backups" / "archive" / "2026-02.sqlite").exists()


def test_retention_defaults(db: sqlite3.Connection, home: Path) -> None:
    folder = home / "backups" / "db"
    folder.mkdir(parents=True)
    for i in range(20):
        (folder / f"brand-2026010{i % 10}T0000{i:02d}.sqlite").write_bytes(b"old")
    (folder / "notes.txt").write_text("keep me", encoding="utf-8")
    (folder / "brand-readme.txt").write_text("keep me", encoding="utf-8")
    out = backup.backup(db, CFG, home, "admin-1", NOW)
    assert len(list(folder.glob("brand-*.sqlite"))) == 14
    assert (home / out["file"]).exists() and len(out["removed"]) == 7
    assert (folder / "notes.txt").exists() and (folder / "brand-readme.txt").exists()

    jfolder = home / "backups" / "json"
    jfolder.mkdir(parents=True)
    for i in range(35):
        (jfolder / f"export-20260101T0000{i:02d}.json").write_text("{}", encoding="utf-8")
    (jfolder / "other.json").write_text("{}", encoding="utf-8")
    backup.export(db, CFG, home, NOW)
    assert len(list(jfolder.glob("export-*.json"))) == 30
    assert (jfolder / "other.json").exists()


def test_retention_override(db: sqlite3.Connection, home: Path) -> None:
    cfg = {**CFG_W, "backup_keep": {"db": 2}}
    for minute in range(4):
        backup.backup(db, cfg, home, "admin-1", NOW + timedelta(minutes=minute))
    names = sorted(p.name for p in (home / "backups" / "db").iterdir())
    assert names == ["brand-20260310T013215.sqlite", "brand-20260310T013315.sqlite"]
    for minute in range(3):
        backup.export(
            db, {**cfg, "backup_keep": {"json": 1}}, home, NOW + timedelta(minutes=minute)
        )
    assert len(list((home / "backups" / "json").iterdir())) == 1


def test_export_has_every_table_and_leaves_db_untouched(db: sqlite3.Connection, home: Path) -> None:
    make_post(db)
    before = (home / "brand.db").read_bytes()
    out = backup.export(db, CFG, home, NOW)
    assert (home / "brand.db").read_bytes() == before
    assert out["file"] == "backups/json/export-20260310T093015.json"
    data = json.loads((home / out["file"]).read_text(encoding="utf-8"))
    tables = [
        "agents",
        "platforms",
        "posts",
        "parts",
        "media",
        "approvals",
        "events",
        "transitions",
    ]
    assert data["exported_at"] == STAMP
    for table in tables:
        assert len(data[table]) == out["counts"][table]
    assert [p["id"] for p in data["posts"]] == ["p0001"]
    assert data["parts"][0]["text"] == "Hello from Example Co"
    assert {a["id"] for a in data["agents"]} >= {"writer-1", "admin-1"}
    assert out["counts"]["events"] == db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert backup_events(db) == []


def test_restore_test_clean(db: sqlite3.Connection, home: Path) -> None:
    pid = make_post(db)
    media_file = home / "media" / "ab" / "img.png"
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"fake image")
    db.execute(
        "INSERT INTO media (id, part_id, pos, kind, path, sha256, alt_text, bytes)"
        " VALUES ('m1', (SELECT id FROM parts WHERE post_id = ?), 1, 'image', ?, ?, 'Alt', 10)",
        (pid, "media/ab/img.png", sha(media_file)),
    )
    src = make_archive(home)
    written(db, "2026-02.sqlite", sha(src))
    backup.backup(db, CFG, home, "admin-1", NOW)
    before = sorted(str(p) for p in home.rglob("*"))
    out = backup.restore_test(home, CFG, NOW)
    assert out["ok"] is True and out["archives"] == 1
    assert out["backup"] == "brand-20260310T093015.sqlite"
    assert out["audit"]["checked"]["media"] == 1
    assert sorted(str(p) for p in home.rglob("*")) == before


def test_restore_test_detects_missing_media_copy(db: sqlite3.Connection, home: Path) -> None:
    pid = make_post(db)
    f = home / "media" / "img.png"
    f.parent.mkdir()
    f.write_bytes(b"fake image")
    db.execute(
        "INSERT INTO media (id, part_id, pos, kind, path, sha256, alt_text, bytes)"
        " VALUES ('m1', (SELECT id FROM parts WHERE post_id = ?), 1, 'image', ?, ?, 'Alt', 10)",
        (pid, "media/img.png", sha(f)),
    )
    backup.backup(db, CFG, home, "admin-1", NOW)
    (home / "backups" / "media" / "img.png").unlink()
    with pytest.raises(BrandcalError) as exc:
        backup.restore_test(home, CFG, NOW)
    assert codes(exc) is ErrorCode.NO_FRESH_BACKUP and "media_missing" in exc.value.message


def test_restore_test_detects_archive_hash_mismatch(db: sqlite3.Connection, home: Path) -> None:
    src = make_archive(home)
    written(db, "2026-02.sqlite", sha(src))
    backup.backup(db, CFG, home, "admin-1", NOW)
    copy = home / "backups" / "archive" / "2026-02.sqlite"
    copy.chmod(0o644)
    other = sqlite3.connect(copy)
    other.execute("INSERT INTO t VALUES ('changed')")
    other.commit()
    other.close()
    with pytest.raises(BrandcalError) as exc:
        backup.restore_test(home, CFG, NOW)
    assert codes(exc) is ErrorCode.NO_FRESH_BACKUP and "2026-02.sqlite" in exc.value.message


def run(home: Path, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any]]:
    code = main(["--home", str(home), *argv])
    out: dict[str, Any] = json.loads(capsys.readouterr().out)
    return code, out


def test_cli_roles(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for argv in (["export"], ["backup"], ["backup", "restore-test"]):
        code, out = run(home, capsys, *argv, "--as", "writer-1")
        assert code == 4 and out["error"]["code"] == "ROLE_NOT_ALLOWED"
    assert not (home / "backups").exists()


def test_cli_backup_export_and_restore_test(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(home, capsys, "backup", "--as", "admin-1")
    assert code == 0 and out["ok"] is True and out["file"].startswith("backups/db/brand-")
    code, out = run(home, capsys, "export", "--as", "admin-1")
    assert code == 0 and out["counts"]["agents"] >= 1
    code, out = run(home, capsys, "backup", "restore-test", "--as", "admin-1")
    assert code == 0 and out["ok"] is True


def test_cli_restore_test_fails_on_corrupt_backup(
    home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make = open_db(home / "brand.db", TZ)
    for i in range(30):
        make_post(make, id=f"p{i:04d}", slug=f"post-{i}")
    make.close()
    assert run(home, capsys, "backup", "--as", "admin-1")[0] == 0
    (latest,) = (home / "backups" / "db").glob("brand-*.sqlite")
    data = bytearray(latest.read_bytes())
    data[len(data) // 4 : 3 * len(data) // 4] = b"\xff" * (len(data) // 2)
    latest.write_bytes(bytes(data))
    code, out = run(home, capsys, "backup", "restore-test", "--as", "admin-1")
    assert code == 5 and out["error"]["code"] == "NO_FRESH_BACKUP"


def test_cli_restore_test_without_backup(home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(home, capsys, "backup", "restore-test", "--as", "admin-1")
    assert code == 5 and out["error"]["code"] == "NO_FRESH_BACKUP"
    assert not (home / "backups").exists()

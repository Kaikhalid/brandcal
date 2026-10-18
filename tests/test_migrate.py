"""Hand-written: migration from a v1 JSON calendar (SPEC 12)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from brandcal import audit, cli
from brandcal.config import display_tz, load_config
from brandcal.db import open_db

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "v1_calendar.example.json"
AGENTS = [
    {"id": "writer-1", "role": "writer"},
    {"id": "manager-1", "role": "manager"},
    {"id": "approver-1", "role": "approver"},
    {"id": "admin-1", "role": "admin"},
    {"id": "system", "role": "system"},
]
PLATFORMS = {
    "linkedin": {"chars_per_post": 3000, "images_per_post": 9, "image_mb": 5},
    "x": {"premium": False, "chars_per_post": 280, "images_per_post": 4, "image_mb": 5},
}


def setup_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tz: str = "+03:00") -> Path:
    monkeypatch.delenv("BRANDCAL_TZ", raising=False)
    monkeypatch.delenv("BRANDCAL_AGENT", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    cfg = {"timezone": tz, "agents": AGENTS, "platforms_file": "platforms.json"}
    (home / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (home / "platforms.json").write_text(json.dumps(PLATFORMS), encoding="utf-8")
    monkeypatch.setenv("BRANDCAL_HOME", str(home))
    assert cli.main(["init", "--as", "admin-1"]) == 0
    return home


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    code = cli.main(list(args))
    out: dict[str, Any] = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    return code, out


def v1_file(tmp_path: Path, *items: dict[str, Any]) -> Path:
    path = tmp_path / "v1.json"
    path.write_text(json.dumps({"items": list(items)}), encoding="utf-8")
    return path


def item(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "v1-1",
        "platform": "linkedin",
        "status": "posted",
        "date": "2026-02-02",
        "window": "09:00-10:00",
        "title": "Example Co update",
        "body": "Hello from Example Co.",
        "assets": [],
        "approved_on": "",
        "posted_at": "2026-02-02T09:12:00+03:00",
        "url": "https://example.com/p/1",
        "notes": "",
    }
    base.update(fields)
    return base


def migrate_cli(
    capsys: pytest.CaptureFixture[str], path: Path, *extra: str
) -> tuple[int, dict[str, Any]]:
    return run(capsys, "migrate", str(path), "--as", "admin-1", *extra)


def db_of(home: Path) -> sqlite3.Connection:
    cfg = load_config(home)
    return open_db(home / "brand.db", display_tz(cfg))


def test_dry_run_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = setup_home(tmp_path, monkeypatch)
    before = (home / "brand.db").read_bytes()
    code, out = migrate_cli(capsys, EXAMPLE, "--dry-run")
    assert code == 0 and out["ok"] is True and out["dry_run"] is True
    assert [i["id"] for i in out["imported"]] == [f"p000{n}" for n in range(1, 7)]
    assert out["out"] is None
    assert (home / "brand.db").read_bytes() == before
    assert not (home / "migrate_not_imported.json").exists()
    conn = db_of(home)
    assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
    conn.close()


def test_example_import_maps_every_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = setup_home(tmp_path, monkeypatch)
    code, out = migrate_cli(capsys, EXAMPLE)
    assert code == 0 and out["dry_run"] is False
    assert out["out"] == str(home / "migrate_not_imported.json")
    assert out["next"] == "run brandcal check ID for each pending_approval post"
    conn = db_of(home)
    rows = {r["legacy_id"]: r for r in conn.execute("SELECT * FROM posts")}
    ex1 = rows["ex-001"]
    assert ex1["status"] == "published" and ex1["id"] == "p0001"
    assert ex1["published_at"] == ex1["closed_at"] == "2026-02-02T09:12:00+03:00"
    assert ex1["window"] == "2026-02-02T09:00:00+03:00/2026-02-02T10:00:00+03:00"
    assert ex1["platform_url"] == "https://example.com/posts/ex-001"
    assert ex1["source_doc"] == "drafts/example-launch.md"
    assert rows["ex-002"]["window"] is None and rows["ex-003"]["platform_url"] is None
    app = conn.execute("SELECT * FROM approvals WHERE post_id = 'p0001'").fetchone()
    assert (app["decision"], app["channel"]) == ("approve", "legacy")
    assert app["source_message_id"] == "legacy:ex-001"
    assert app["approver_words"] == "legacy import, unverified (approved on 2026-01-30)"
    assert app["decided_at"] == "2026-01-30T00:00:00+03:00"
    assert (app["decided_by"], app["relayed_by"], app["recorded_by"]) == (
        "approver-1",
        "manager-1",
        "manager-1",
    )
    no_date = conn.execute("SELECT * FROM approvals WHERE post_id = 'p0003'").fetchone()
    assert no_date["window"] == "" and no_date["decided_at"] == "2026-02-05T00:00:00+03:00"
    assert no_date["approver_words"] == "legacy import, unverified"
    ev = conn.execute("SELECT * FROM events WHERE chain = 'post:p0001'").fetchall()
    assert [(e["action"], e["actor"], e["to_status"]) for e in ev] == [
        ("migrate", "admin-1", "published")
    ]
    assert json.loads(ev[0]["detail"]) == {"legacy_id": "ex-001", "v1_status": "posted"}
    report = audit.audit(conn, home)
    assert report["ok"] is True, report["flags"]
    conn.close()


def test_approved_skipped_and_not_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = setup_home(tmp_path, monkeypatch)
    _, out = migrate_cli(capsys, EXAMPLE)
    conn = db_of(home)
    ex4 = conn.execute("SELECT * FROM posts WHERE legacy_id = 'ex-004'").fetchone()
    assert ex4["status"] == "pending_approval" and ex4["content_version"] == 1
    assert ex4["window"] == "2026-03-12T08:00:00+03:00/2026-03-12T09:00:00+03:00"
    assert ex4["source_doc"] == "drafts/example-customer-story.md"
    assert (
        conn.execute("SELECT COUNT(*) FROM approvals WHERE post_id = ?", (ex4["id"],)).fetchone()[0]
        == 0
    )
    ex8 = conn.execute("SELECT * FROM posts WHERE legacy_id = 'ex-008'").fetchone()
    assert (ex8["status"], ex8["cancel_kind"]) == ("cancelled", "plan")
    assert ex8["closed_at"] is not None
    conn.close()
    assert {n["legacy_id"]: n["reason"] for n in out["not_imported"]} == {
        "ex-006": "idea",
        "ex-007": "draft",
    }
    saved = json.loads((home / "migrate_not_imported.json").read_text(encoding="utf-8"))
    by_id = {n["legacy_id"]: n for n in saved["not_imported"]}
    assert by_id["ex-007"]["title"] == "Example draft: event recap"
    assert by_id["ex-007"]["body"] == "Draft text for a fake event recap."
    assert by_id["ex-007"]["assets"] == ["drafts/example-event-recap.md"]
    assert by_id["ex-006"]["notes"] == "Rough idea only."


def test_approved_without_window_is_not_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup_home(tmp_path, monkeypatch)
    path = v1_file(
        tmp_path,
        item(id="a", status="approved", window=""),
        item(id="b", status="skipped", date=""),
    )
    _, out = migrate_cli(capsys, path)
    assert out["imported"] == []
    assert {n["reason"] for n in out["not_imported"]} == {"needs a date and window"}


def test_thread_is_split_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = setup_home(tmp_path, monkeypatch)
    body = "Intro line\n1/ First\n\n2/ Second\nmore\n\n3/ Third"
    path = v1_file(tmp_path, item(status="approved", platform="x", body=body))
    migrate_cli(capsys, path)
    conn = db_of(home)
    post = conn.execute("SELECT * FROM posts").fetchone()
    assert post["post_type"] == "thread"
    parts = conn.execute("SELECT pos, text FROM parts ORDER BY pos").fetchall()
    assert [(p["pos"], p["text"]) for p in parts] == [
        (1, "Intro line\n\nFirst"),
        (2, "Second\nmore"),
        (3, "Third"),
    ]
    conn.close()


def test_empty_body_uses_title_and_single_marker_is_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = setup_home(tmp_path, monkeypatch)
    path = v1_file(
        tmp_path,
        item(id="a", body="", title="Only a title"),
        item(id="b", body="1/ Just one", title="Other"),
    )
    migrate_cli(capsys, path)
    conn = db_of(home)
    rows = conn.execute(
        "SELECT p.legacy_id, p.post_type, p.slug, t.text FROM posts p JOIN parts t"
        " ON t.post_id = p.id ORDER BY p.id"
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("a", "text", "only-a-title", "Only a title"),
        ("b", "text", "other", "Just one"),
    ]
    conn.close()


@pytest.mark.parametrize(
    ("tz", "expected"),
    [
        (
            "+03:00",
            ["2026-02-02T09:12:00+03:00", "2026-02-03T08:30:00+03:00", "2026-02-04T00:00:00+03:00"],
        ),
        (
            "-05:00",
            ["2026-02-02T01:12:00-05:00", "2026-02-03T08:30:00-05:00", "2026-02-04T00:00:00-05:00"],
        ),
    ],
)
def test_posted_at_formats_are_normalised(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tz: str,
    expected: list[str],
) -> None:
    home = setup_home(tmp_path, monkeypatch, tz)
    stamps = ["2026-02-02T09:12:00+03:00", "2026-02-03T08:30", "2026-02-04"]
    path = v1_file(tmp_path, *(item(id=f"i{n}", posted_at=s) for n, s in enumerate(stamps)))
    code, _ = migrate_cli(capsys, path)
    assert code == 0
    conn = db_of(home)
    got = [r[0] for r in conn.execute("SELECT published_at FROM posts ORDER BY id")]
    assert got == expected
    conn.close()


def test_missing_url_and_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = setup_home(tmp_path, monkeypatch)
    path = v1_file(
        tmp_path,
        item(id="n1", url="", assets=["images/a.jpg", "drafts/a.md", "drafts/b.MD", "c.png"]),
    )
    _, out = migrate_cli(capsys, path)
    assert out["missing_url"] == [{"id": "p0001", "legacy_id": "n1"}]
    assert out["assets_to_add"] == [
        {"id": "p0001", "legacy_id": "n1", "paths": ["images/a.jpg", "c.png"]}
    ]
    conn = db_of(home)
    post = conn.execute("SELECT * FROM posts").fetchone()
    assert post["source_doc"] == "drafts/a.md" and "drafts/b.MD" in post["notes"]
    assert conn.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 0
    conn.close()


def test_rerun_skips_and_ids_continue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = setup_home(tmp_path, monkeypatch)
    _, first = migrate_cli(capsys, EXAMPLE)
    legacy = [i["legacy_id"] for i in first["imported"]]
    code, again = migrate_cli(capsys, EXAMPLE)
    assert code == 0 and again["imported"] == []
    assert sorted(again["already_imported"]) == sorted(legacy)
    conn = db_of(home)
    assert conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == len(legacy)
    conn.close()
    post = {
        "slug": "later",
        "title": "Later",
        "platform": "linkedin",
        "post_type": "text",
        "window": "2030-03-04T09:00:00+00:00/2030-03-04T10:00:00+00:00",
        "parts": [{"text": "Hi"}],
    }
    added = home / "post.json"
    added.write_text(json.dumps(post), encoding="utf-8")
    with added.open(encoding="utf-8") as fh:
        monkeypatch.setattr("sys.stdin", fh)
        _, res = run(capsys, "add", "--as", "writer-1")
    assert res["id"] == "p0007"
    path = v1_file(tmp_path, item(id="new-1"))
    _, third = migrate_cli(capsys, path)
    assert third["imported"] == [{"legacy_id": "new-1", "id": "p0008", "status": "published"}]


def test_writer_cannot_migrate_admin_can(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup_home(tmp_path, monkeypatch)
    code, out = run(capsys, "migrate", str(EXAMPLE), "--as", "writer-1")
    assert code == 4 and out["error"]["code"] == "ROLE_NOT_ALLOWED"
    code, out = run(capsys, "migrate", str(EXAMPLE), "--as", "admin-1")
    assert code == 0 and out["ok"] is True


def test_bad_input_is_bad_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup_home(tmp_path, monkeypatch)
    broken = tmp_path / "broken.json"
    broken.write_text("{nope", encoding="utf-8")
    bad_inputs = [
        broken,
        v1_file(tmp_path, item(status="maybe")),
        v1_file(tmp_path, item(title=5)),
        v1_file(tmp_path, {k: v for k, v in item().items() if k != "status"}),
        v1_file(tmp_path, item(assets="a.jpg")),
    ]
    for path in bad_inputs:
        code, out = migrate_cli(capsys, path)
        assert code == 2 and out["error"]["code"] == "BAD_ARGS", path


def test_owner_option_and_missing_agents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = setup_home(tmp_path, monkeypatch)
    path = v1_file(tmp_path, item())
    code, out = migrate_cli(capsys, path, "--owner", "ghost")
    assert code == 2 and out["error"]["code"] == "BAD_ARGS"
    code, _ = migrate_cli(capsys, path, "--owner", "manager-1", "--out", str(tmp_path / "o.json"))
    assert code == 0 and (tmp_path / "o.json").is_file()
    conn = db_of(home)
    assert conn.execute("SELECT owner FROM posts").fetchone()[0] == "manager-1"
    conn.close()

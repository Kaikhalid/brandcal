from __future__ import annotations

import hashlib
import sqlite3
import struct
import sys
import zlib
from pathlib import Path

import pytest
from conftest import approve_post, make_post

from brandcal.errors import BrandcalError, ErrorCode
from brandcal.media import add_media, sniff_kind, verify_media

LIMITS = {"image_mb": 5, "images_per_post": 4}


def png_bytes(w: int = 3, h: int = 2) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def png(tmp_path: Path) -> Path:
    p = tmp_path / "src" / "pic.png"
    p.parent.mkdir()
    p.write_bytes(png_bytes())
    return p


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture
def post(conn: sqlite3.Connection) -> str:
    return make_post(conn)


def add(
    conn: sqlite3.Connection, home: Path, src: Path, alt: str = "A pixel", **kw: object
) -> dict:  # type: ignore[type-arg]
    limits = kw.pop("limits", LIMITS)
    return add_media(conn, home, "p0001", 1, src, alt, limits, **kw)  # type: ignore[arg-type]


def test_html_renamed_jpg_rejected(tmp_path: Path) -> None:
    fake = tmp_path / "x.jpg"
    fake.write_text("<html><body>hi</body></html>")
    with pytest.raises(BrandcalError) as err:
        sniff_kind(fake)
    assert err.value.code == ErrorCode.MEDIA_INVALID


def test_extension_must_match_kind(png: Path) -> None:
    wrong = png.with_name("pic.pdf")
    wrong.write_bytes(png.read_bytes())
    with pytest.raises(BrandcalError):
        sniff_kind(wrong)
    assert sniff_kind(png) == "image"


def test_png_accepted_with_dimensions(
    conn: sqlite3.Connection, home: Path, post: str, png: Path
) -> None:
    row = add(conn, home, png, credit="Example Co")
    assert (row["width"], row["height"], row["kind"]) == (3, 2, "image")
    assert row["id"] == "p0001-1-1" and row["credit"] == "Example Co"
    assert row["bytes"] == png.stat().st_size


def test_empty_alt_rejected(conn: sqlite3.Connection, home: Path, post: str, png: Path) -> None:
    with pytest.raises(BrandcalError) as err:
        add(conn, home, png, alt="  ")
    assert err.value.code == ErrorCode.MEDIA_INVALID


def test_oversize_rejected(conn: sqlite3.Connection, home: Path, post: str, png: Path) -> None:
    with pytest.raises(BrandcalError) as err:
        add(conn, home, png, limits={"image_mb": 0.00001, "images_per_post": 4})
    assert err.value.code == ErrorCode.MEDIA_INVALID
    assert not (home / "media").exists()


def test_fifth_image_rejected(conn: sqlite3.Connection, home: Path, post: str, png: Path) -> None:
    for _ in range(4):
        add(conn, home, png)
    with pytest.raises(BrandcalError) as err:
        add(conn, home, png)
    assert err.value.code == ErrorCode.MEDIA_INVALID
    assert conn.execute("SELECT COUNT(*) FROM media").fetchone()[0] == 4


def test_stored_copy_readonly_and_hash(
    conn: sqlite3.Connection, home: Path, post: str, png: Path
) -> None:
    row = add(conn, home, png)
    stored = home / row["path"]
    assert stored.stat().st_mode & 0o777 == 0o444
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == row["sha256"]
    assert stored.name == f"1-1-{row['sha256'][:8]}.png"
    assert verify_media(conn, home, "p0001") == []


def test_verify_reports_change(conn: sqlite3.Connection, home: Path, post: str, png: Path) -> None:
    row = add(conn, home, png)
    stored = home / row["path"]
    stored.chmod(0o644)
    stored.write_bytes(b"changed")
    bad = verify_media(conn, home, "p0001")
    assert [b["path"] for b in bad] == [row["path"]]
    assert bad[0]["expected"] == row["sha256"] and bad[0]["actual"] != row["sha256"]


def test_media_on_approved_post_resets_to_pending(
    conn: sqlite3.Connection, home: Path, post: str, png: Path
) -> None:
    approve_post(conn, post)
    add(conn, home, png)
    status = conn.execute("SELECT status FROM posts WHERE id = ?", (post,)).fetchone()[0]
    assert status == "pending_approval"


def test_works_without_pillow(
    conn: sqlite3.Connection,
    home: Path,
    post: str,
    png: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "PIL", None)
    monkeypatch.setitem(sys.modules, "PIL.Image", None)
    row = add(conn, home, png)
    assert (row["width"], row["height"]) == (3, 2)


# --- added by hand during review -----------------------------------------------------------


def test_media_on_natively_scheduled_post_refused(
    conn: sqlite3.Connection, home: Path, post: str, png: Path
) -> None:
    approve_post(conn, post)
    conn.execute(
        "UPDATE posts SET native_scheduled_at = '2026-03-02T09:30:00+03:00' WHERE id = ?", (post,)
    )
    with pytest.raises(BrandcalError) as info:
        add(conn, home, png)
    assert info.value.code == ErrorCode.EDIT_WHILE_SCHEDULED
    assert not list((home / "media").rglob("*.png"))  # copied file removed again
    assert conn.execute("SELECT status FROM posts").fetchone()[0] == "approved"


@pytest.mark.parametrize(
    ("name", "head", "kind"),
    [
        ("a.jpg", b"\xff\xd8\xff\xe0" + b"\0" * 12, "image"),
        ("a.webp", b"RIFF\0\0\0\0WEBPVP8 ", "image"),
        ("a.gif", b"GIF89a" + b"\0" * 10, "gif"),
        ("a.pdf", b"%PDF-1.7\n" + b"\0" * 7, "pdf"),
        ("a.mp4", b"\0\0\0\x18ftypmp42" + b"\0" * 4, "video"),
    ],
)
def test_sniff_other_kinds(tmp_path: Path, name: str, head: bytes, kind: str) -> None:
    path = tmp_path / name
    path.write_bytes(head)
    assert sniff_kind(path) == kind

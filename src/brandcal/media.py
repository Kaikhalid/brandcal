"""Media files: content checks, copy-in, checksums and verification (SPEC 9)."""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import sqlite3
import struct
import subprocess
from pathlib import Path
from typing import Any

from brandcal.db import transaction
from brandcal.errors import BrandcalError, ErrorCode

_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "image": (".jpg", ".jpeg", ".png", ".webp"),
    "gif": (".gif",),
    "pdf": (".pdf",),
    "video": (".mp4", ".mov"),
}


def _invalid(message: str, next_step: str = "") -> BrandcalError:
    return BrandcalError(ErrorCode.MEDIA_INVALID, message, next_step)


def sniff_kind(path: Path) -> str:
    """Kind from the file's magic bytes; the extension must agree. Else MEDIA_INVALID."""
    with path.open("rb") as fh:
        head = fh.read(16)
    if head.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")) or (
        head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    ):
        kind = "image"
    elif head.startswith((b"GIF87a", b"GIF89a")):
        kind = "gif"
    elif head.startswith(b"%PDF-"):
        kind = "pdf"
    elif head[4:8] == b"ftyp":
        kind = "video"
    else:
        raise _invalid(f"{path.name}: contents are not a supported media type")
    if path.suffix.lower() not in _EXTENSIONS[kind]:
        raise _invalid(f"{path.name}: extension does not match its {kind} contents")
    return kind


def _pillow_size(path: Path) -> tuple[int, int] | None:
    try:
        image: Any = importlib.import_module("PIL.Image")
        with image.open(path) as im:
            return int(im.width), int(im.height)
    except Exception:  # Pillow missing or unable to read the file: fall back to headers
        return None


def _header_size(path: Path) -> tuple[int, int] | None:
    with path.open("rb") as fh:
        head = fh.read(26)
    if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
        w, h = struct.unpack(">II", head[16:24])
        return w, h
    if head.startswith((b"GIF87a", b"GIF89a")) and len(head) >= 10:
        w, h = struct.unpack("<HH", head[6:10])
        return w, h
    return None


def _ffprobe(path: Path) -> tuple[int | None, int | None, float | None]:
    exe = shutil.which("ffprobe")
    if exe is None:
        return None, None, None
    cmd = [exe, "-v", "error", "-select_streams", "v:0", "-show_entries"]
    cmd += ["stream=width,height:format=duration", "-of", "json", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True).stdout
        data = json.loads(out)
        stream = (data.get("streams") or [{}])[0]
        duration = data.get("format", {}).get("duration")
        return stream.get("width"), stream.get("height"), float(duration) if duration else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, None, None


def add_media(
    conn: sqlite3.Connection,
    home: Path,
    post_id: str,
    part_pos: int,
    src: Path,
    alt_text: str,
    limits: dict[str, Any],
    credit: str | None = None,
    source_url: str | None = None,
    licence: str | None = None,
) -> dict[str, Any]:
    """Check, copy in (read-only) and record one media file; return the media row."""
    if not alt_text.strip():
        raise _invalid("Alt text is required.", "Pass --alt with a description.")
    kind = sniff_kind(src)
    size = src.stat().st_size
    if kind == "image" and size > float(limits.get("image_mb", float("inf"))) * 1024 * 1024:
        raise _invalid(f"{src.name} is larger than {limits['image_mb']} MB")
    part = conn.execute(
        "SELECT id FROM parts WHERE post_id = ? AND pos = ?", (post_id, part_pos)
    ).fetchone()
    if part is None:
        raise BrandcalError(ErrorCode.BAD_ARGS, f"{post_id} has no part {part_pos}.")
    width = height = None
    duration: float | None = None
    if kind == "video":
        width, height, duration = _ffprobe(src)
    else:
        size_wh = _pillow_size(src) or _header_size(src)
        width, height = size_wh if size_wh else (None, None)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    dest: Path | None = None
    try:
        with transaction(conn):
            row = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(MAX(pos), 0) AS last, "
                "COALESCE(SUM(kind IN ('image','gif')), 0) AS imgs FROM media WHERE part_id = ?",
                (part["id"],),
            ).fetchone()
            if kind in ("image", "gif") and row["imgs"] >= int(
                limits.get("images_per_post", 1 << 30)
            ):
                raise _invalid(f"Part {part_pos} already has {row['imgs']} images (the limit)")
            n = row["last"] + 1
            rel = f"media/{post_id}/{part_pos}-{n}-{sha[:8]}{src.suffix.lower()}"
            media_id = f"{post_id}-{part_pos}-{n}"
            dest = home / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            dest.chmod(0o444)
            conn.execute(
                "INSERT INTO media (id, part_id, pos, kind, path, sha256, alt_text, bytes, width,"
                " height, duration_s, source_url, credit, licence)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (media_id, part["id"], n, kind, rel, sha, alt_text, size, width, height)
                + (duration, source_url, credit, licence),
            )
    except BaseException:
        if dest is not None and dest.exists():
            dest.chmod(0o644)
            dest.unlink()
        raise
    return dict(conn.execute("SELECT * FROM media WHERE id = ?", (media_id,)).fetchone())


def verify_media(conn: sqlite3.Connection, home: Path, post_id: str) -> list[dict[str, str]]:
    """Media whose file hash differs from the record: dicts of path, expected, actual."""
    rows = conn.execute(
        "SELECT m.path, m.sha256 FROM media m JOIN parts p ON p.id = m.part_id"
        " WHERE p.post_id = ? ORDER BY m.id",
        (post_id,),
    ).fetchall()
    bad: list[dict[str, str]] = []
    for r in rows:
        file = home / r["path"]
        actual = hashlib.sha256(file.read_bytes()).hexdigest() if file.is_file() else "missing"
        if actual != r["sha256"]:
            bad.append({"path": r["path"], "expected": r["sha256"], "actual": actual})
    return bad

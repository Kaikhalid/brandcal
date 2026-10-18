"""Post validation (SPEC 8.4): hard errors and softer warnings, without changing anything."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from brandcal.config import display_tz
from brandcal.errors import BrandcalError, ErrorCode
from brandcal.timefmt import parse_time, to_utc_text

_URL = re.compile(r"https?://\S+")
_PLACEHOLDER = re.compile(r"\bTBC\b|\[link\]", re.IGNORECASE)
_DEFAULT_URL_CHARS = 23
# Media kinds a post type needs at least one of.
_NEEDS: dict[str, tuple[str, ...]] = {
    "image": ("image", "gif"),
    "carousel": ("pdf",),
    "video": ("video",),
}


def text_length(text: str, url_chars: int) -> int:
    """Length with every URL counted as url_chars."""
    return len(_URL.sub(lambda _: "x" * url_chars, text))


def validate(
    conn: sqlite3.Connection,
    post_id: str,
    limits_by_platform: Mapping[str, Mapping[str, Any]],
    cfg: Mapping[str, Any],
    stage: str,
) -> tuple[list[BrandcalError], list[str]]:
    """Return (errors, warnings). stage is "add" or "check"; "check" is the strict one."""
    post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    parts = conn.execute(
        "SELECT id, pos, text FROM parts WHERE post_id = ? ORDER BY pos", (post_id,)
    ).fetchall()
    kinds = [
        r[0]
        for r in conn.execute(
            "SELECT m.kind FROM media m JOIN parts p ON p.id = m.part_id WHERE p.post_id = ?",
            (post_id,),
        )
    ]
    limits = limits_by_platform.get(post["platform"], {})
    errors: list[BrandcalError] = []
    warnings: list[str] = []
    ptype = post["post_type"]

    def bad(code: ErrorCode, message: str, next_step: str = "") -> None:
        errors.append(BrandcalError(code, message, next_step))

    # Text length per part.
    premium = limits.get("premium") is True
    limit = limits.get("premium_chars_per_post" if premium else "chars_per_post")
    if premium and limit is None:
        limit = limits.get("chars_per_post")
    preview = limits.get("feed_preview_chars")
    url_chars = int(limits.get("url_chars", _DEFAULT_URL_CHARS))
    for part in parts:
        n = text_length(part["text"], url_chars)
        if limit is not None and n > int(limit):
            bad(
                ErrorCode.TOO_LONG,
                f"Part {part['pos']} is {n} characters; the limit is {limit}.",
                "Shorten the text or split it into a thread.",
            )
        elif premium and preview is not None and n > int(preview):
            warnings.append(
                f"Part {part['pos']} is {n} characters, over the {preview}-character feed preview."
            )

    # Structure per post type.
    if ptype == "thread" and len(parts) < 2:
        bad(
            ErrorCode.INVALID_POST,
            "A thread needs 2 or more parts.",
            "Add parts: brandcal part add",
        )
    elif ptype != "thread" and len(parts) != 1:
        bad(ErrorCode.INVALID_POST, f"A {ptype} post has exactly 1 part, not {len(parts)}.")
    if ptype in ("reshare", "comment") and not post["target_url"]:
        bad(ErrorCode.INVALID_POST, f"A {ptype} needs a target_url.")
    if ptype == "article":
        if not post["title"].strip():
            bad(ErrorCode.INVALID_POST, "An article needs a title.")
        if not any(p["text"].strip() for p in parts):
            bad(ErrorCode.INVALID_POST, "An article needs a non-empty body.")
    needed = _NEEDS.get(ptype)
    if needed is not None:
        count = sum(k in needed for k in kinds)
        if count == 0:
            what = " or ".join(needed)
            message = f"A {ptype} post needs at least one {what} file."
            if stage == "check":
                bad(ErrorCode.MEDIA_INVALID, message, "Attach it: brandcal media add")
            else:
                warnings.append(message)
        max_images = limits.get("images_per_post")
        if ptype == "image" and max_images is not None and count > int(max_images):
            bad(ErrorCode.MEDIA_INVALID, f"{count} images; the limit is {max_images}.")

    # Links.
    target = post["target_url"]
    if target:
        url = urlparse(target)
        if _PLACEHOLDER.search(target):
            warnings.append("target_url is a placeholder.")
        elif url.scheme not in ("http", "https") or not url.netloc:
            bad(ErrorCode.INVALID_POST, f"target_url is not a well-formed link: {target!r}.")
    fields = [p["text"] for p in parts] + [post["first_comment"] or ""]
    if any(_PLACEHOLDER.search(t) for t in fields):
        warnings.append("Text contains a placeholder link (TBC or [link]).")

    # Campaign and pillar: warnings only, and only when the config lists any.
    for field, key in (("campaign", "campaigns"), ("pillar", "pillars")):
        allowed = cfg.get(key) or []
        if post[field] and allowed and post[field] not in allowed:
            warnings.append(f"{field} {post[field]!r} is not in the configured {key}.")

    # Window.
    if post["window"]:
        if post["window_end_utc"] < to_utc_text(datetime.now(UTC)):
            warnings.append("The window is in the past.")
        for other in conn.execute(
            "SELECT id FROM posts WHERE platform = ? AND id <> ? AND window IS NOT NULL"
            " AND status NOT IN ('published', 'cancelled')"
            " AND window_start_utc < ? AND window_end_utc > ? ORDER BY id",
            (post["platform"], post_id, post["window_end_utc"], post["window_start_utc"]),
        ):
            warnings.append(f"The window overlaps {other[0]} on {post['platform']}.")

    # Holds.
    if post["hold_until"]:
        until = parse_time(post["hold_until"], display_tz(cfg))
        if until > datetime.now(UTC):
            reason = post["hold_reason"] or "no reason given"
            message = f"On hold until {post['hold_until']} ({reason})."
            if stage == "check":
                bad(ErrorCode.ON_HOLD, message, "Clear the hold: brandcal edit ID hold_until=")
            else:
                warnings.append(message)
    return errors, warnings

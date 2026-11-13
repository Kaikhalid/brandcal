"""Content hash: the canonical form of a post and its SHA-256 fingerprint (SPEC 5.4)."""

from __future__ import annotations

import hashlib
import json
import sqlite3


def _q(value: object) -> str:
    """JSON string form, so newlines in text can't imitate the line structure."""
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


def canonical_form(conn: sqlite3.Connection, post_id: str) -> str:
    """The text that is hashed: covered fields only, parts and media in position order."""
    post = conn.execute(
        "SELECT platform, post_type, target_url, first_comment FROM posts WHERE id = ?",
        (post_id,),
    ).fetchone()
    lines = [
        "v1",
        f"platform={post['platform']}",
        f"post_type={post['post_type']}",
        f"target_url={_q(post['target_url'])}",
        f"first_comment={_q(post['first_comment'])}",
    ]
    for part in conn.execute(
        "SELECT id, pos, text FROM parts WHERE post_id = ? ORDER BY pos", (post_id,)
    ).fetchall():
        lines += [f"part={part['pos']}", f"text={_q(part['text'])}"]
        for m in conn.execute(
            "SELECT pos, sha256, alt_text FROM media WHERE part_id = ? ORDER BY pos", (part["id"],)
        ).fetchall():
            lines.append(f"media={m['pos']}:{m['sha256']}:{_q(m['alt_text'])}")
    return "\n".join(lines)


def content_hash(conn: sqlite3.Connection, post_id: str) -> str:
    return hashlib.sha256(canonical_form(conn, post_id).encode("utf-8")).hexdigest()


def refresh_hash(conn: sqlite3.Connection, post_id: str) -> str:
    """Recompute the hash and store it on the post. Call inside the editing transaction."""
    h = content_hash(conn, post_id)
    conn.execute("UPDATE posts SET content_hash = ? WHERE id = ?", (h, post_id))
    return h

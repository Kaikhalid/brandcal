"""Content hash: canonical form (SPEC 5.4) and what does and does not change it."""

from __future__ import annotations

import hashlib
import sqlite3

from conftest import make_post

from brandcal import content


def add_part(conn: sqlite3.Connection, post_id: str, pos: int, text: str) -> int:
    cur = conn.execute(
        "INSERT INTO parts (post_id, pos, text) VALUES (?, ?, ?)", (post_id, pos, text)
    )
    return int(cur.lastrowid or 0)


def add_media(conn: sqlite3.Connection, part_id: int, alt: str, sha: str = "b" * 64) -> None:
    conn.execute(
        "INSERT INTO media (id, part_id, pos, kind, path, sha256, alt_text, bytes)"
        " VALUES (?, ?, 1, 'image', ?, ?, ?, 10)",
        (f"m-{part_id}", part_id, f"media/{part_id}.png", sha, alt),
    )


def test_canonical_form_vector(conn: sqlite3.Connection) -> None:
    pid = make_post(conn, first_comment="First!", target_url="https://example.com/a")
    first = conn.execute("SELECT id FROM parts WHERE post_id = ?", (pid,)).fetchone()["id"]
    add_media(conn, first, "A logo")
    add_part(conn, pid, 2, "Second, part")
    expected = "\n".join(
        [
            "v1",
            "platform=linkedin",
            "post_type=text",
            'target_url="https://example.com/a"',
            'first_comment="First!"',
            "part=1",
            'text="Hello from Example Co"',
            f'media=1:{"b" * 64}:"A logo"',
            "part=2",
            'text="Second, part"',
        ]
    )
    assert content.canonical_form(conn, pid) == expected
    assert content.content_hash(conn, pid) == hashlib.sha256(expected.encode()).hexdigest()


def test_empty_optional_fields_are_empty(conn: sqlite3.Connection) -> None:
    pid = make_post(conn)
    lines = content.canonical_form(conn, pid).split("\n")
    assert lines[3:5] == ['target_url=""', 'first_comment=""']


def test_same_content_same_hash(conn: sqlite3.Connection) -> None:
    pid = make_post(conn)
    assert content.content_hash(conn, pid) == content.content_hash(conn, pid)


def test_refresh_hash_writes_and_returns(conn: sqlite3.Connection) -> None:
    pid = make_post(conn)
    h = content.refresh_hash(conn, pid)
    stored = conn.execute("SELECT content_hash FROM posts WHERE id = ?", (pid,)).fetchone()[0]
    assert stored == h == content.content_hash(conn, pid)


def test_covered_changes_alter_hash(conn: sqlite3.Connection) -> None:
    pid = make_post(conn)
    base = content.content_hash(conn, pid)
    seen = {base}

    conn.execute("UPDATE parts SET text = 'Hello, from Example Co' WHERE post_id = ?", (pid,))
    seen.add(content.content_hash(conn, pid))
    conn.execute("UPDATE posts SET first_comment = 'More at example.com' WHERE id = ?", (pid,))
    seen.add(content.content_hash(conn, pid))
    assert len(seen) == 3


def test_alt_text_changes_hash(conn: sqlite3.Connection) -> None:
    pid = make_post(conn)
    part = conn.execute("SELECT id FROM parts WHERE post_id = ?", (pid,)).fetchone()["id"]
    add_media(conn, part, "Old alt")
    before = content.content_hash(conn, pid)
    conn.execute("UPDATE media SET alt_text = 'New alt' WHERE part_id = ?", (part,))
    assert content.content_hash(conn, pid) != before


def test_part_order_changes_hash(conn: sqlite3.Connection) -> None:
    pid = make_post(conn)
    add_part(conn, pid, 2, "Second")
    before = content.content_hash(conn, pid)
    conn.execute("UPDATE parts SET pos = pos + 10 WHERE post_id = ?", (pid,))
    conn.execute("UPDATE parts SET pos = 3 - (pos - 10) WHERE post_id = ?", (pid,))
    assert content.content_hash(conn, pid) != before


def test_uncovered_fields_do_not_change_hash(conn: sqlite3.Connection) -> None:
    pid = make_post(conn)
    before = content.content_hash(conn, pid)
    conn.execute(
        "UPDATE posts SET title = 'Other', slug = 'other', notes = 'a note',"
        " campaign = 'x', window = '2026-03-11T09:00:00+03:00/2026-03-11T10:00:00+03:00'"
        " WHERE id = ?",
        (pid,),
    )
    assert content.content_hash(conn, pid) == before


def test_newline_in_text_cannot_imitate_parts(conn: sqlite3.Connection) -> None:
    """Hand-added: one part containing 'part=2' must not hash like two parts."""
    one = make_post(conn, id="p0101")
    conn.execute("UPDATE parts SET text = ? WHERE post_id = ?", ("x\npart=2\ntext=y", one))
    two = make_post(conn, id="p0102")
    conn.execute("UPDATE parts SET text = 'x' WHERE post_id = ?", (two,))
    add_part(conn, two, 2, "y")
    assert content.content_hash(conn, one) != content.content_hash(conn, two)

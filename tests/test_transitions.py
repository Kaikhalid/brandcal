"""The state machine (SPEC 6.1) in Python and in the transitions table."""

from __future__ import annotations

import sqlite3
from itertools import product

import pytest
from conftest import make_post

from brandcal.db import translate
from brandcal.errors import BrandcalError, ErrorCode
from brandcal.transitions import CLOSED, STATES, TRANSITIONS, check_transition

ROLES = ("manager", "writer", "approver", "contributor", "admin", "system")
LISTED = {(f, t): roles for f, t, roles in TRANSITIONS}
PAIRS = list(product(STATES, STATES))
LISTED_PAIRS = [p for p in PAIRS if p in LISTED]
UNLISTED_PAIRS = [p for p in PAIRS if p not in LISTED]


def test_spec_lists_twelve_changes() -> None:
    assert len(PAIRS) == 36
    assert len(TRANSITIONS) == 12
    assert len(LISTED) == 12
    assert all(f != t for f, t in LISTED)


@pytest.mark.parametrize(("src", "dst"), LISTED_PAIRS)
def test_listed_pair_allows_its_roles_only(src: str, dst: str) -> None:
    for role in ROLES:
        if role in LISTED[(src, dst)]:
            check_transition(src, dst, role)
        else:
            with pytest.raises(BrandcalError) as info:
                check_transition(src, dst, role)
            assert info.value.code == ErrorCode.ROLE_NOT_ALLOWED


@pytest.mark.parametrize(("src", "dst"), LISTED_PAIRS)
def test_listed_pair_refuses_contributor_with_exit_4(src: str, dst: str) -> None:
    with pytest.raises(BrandcalError) as info:
        check_transition(src, dst, "contributor")
    assert info.value.code == ErrorCode.ROLE_NOT_ALLOWED
    assert info.value.exit_code == 4


@pytest.mark.parametrize(("src", "dst"), UNLISTED_PAIRS)
def test_unlisted_pair_is_bad_transition_with_exit_5(src: str, dst: str) -> None:
    for role in ROLES:
        with pytest.raises(BrandcalError) as info:
            check_transition(src, dst, role)
        assert info.value.code == ErrorCode.BAD_TRANSITION
        assert info.value.exit_code == 5


@pytest.mark.parametrize("closed", sorted(CLOSED))
def test_nothing_leaves_a_closed_state(closed: str) -> None:
    assert not [t for t in TRANSITIONS if t[0] == closed]
    for dst, role in product(STATES, ROLES):
        with pytest.raises(BrandcalError) as info:
            check_transition(closed, dst, role)
        assert info.value.code == ErrorCode.BAD_TRANSITION


def test_table_matches_transitions(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT from_status, to_status, roles FROM transitions").fetchall()
    assert {tuple(r) for r in rows} == {(f, t, ",".join(r)) for f, t, r in TRANSITIONS}


def test_status_trigger_refuses_unlisted_change(conn: sqlite3.Connection) -> None:
    pid = make_post(conn)
    with pytest.raises(sqlite3.IntegrityError) as info:
        conn.execute(
            "UPDATE posts SET status = 'published', platform_url = 'https://example.com/p/1',"
            " closed_at = '2026-03-10T09:30:00+03:00' WHERE id = ?",
            (pid,),
        )
    assert translate(info.value).code == ErrorCode.BAD_TRANSITION
    assert conn.execute("SELECT status FROM posts").fetchone()[0] == "pending_approval"

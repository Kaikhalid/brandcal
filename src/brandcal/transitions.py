"""The state machine of SPEC 6 and 6.1: allowed status changes and who may make them."""

from __future__ import annotations

from brandcal.errors import BrandcalError, ErrorCode

STATES: tuple[str, ...] = (
    "pending_approval",
    "changes_requested",
    "approved",
    "missed",
    "published",
    "cancelled",
)

CLOSED: frozenset[str] = frozenset({"published", "cancelled"})

# (from, to, roles). "system" covers the automatic changes (content-edit trigger, sweep).
# The "writer (own posts)" ownership rule is checked by the CLI, not here. "approver" is listed
# for the changes the web UI performs; the CLI refuses that role on every command (UI_SPEC 3.5).
TRANSITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("pending_approval", "approved", ("manager", "approver")),
    ("pending_approval", "changes_requested", ("manager", "approver")),
    ("changes_requested", "pending_approval", ("writer", "manager", "approver")),
    ("approved", "pending_approval", ("system",)),
    ("missed", "pending_approval", ("system",)),
    ("approved", "published", ("manager",)),
    ("approved", "missed", ("system",)),
    ("missed", "approved", ("manager", "approver")),
    ("pending_approval", "cancelled", ("manager", "writer", "approver")),
    ("changes_requested", "cancelled", ("manager", "writer", "approver")),
    ("approved", "cancelled", ("manager", "approver")),
    ("missed", "cancelled", ("manager", "approver")),
)

# Statuses that wait for a person (UI_SPEC 5.1): the "needs you" strip.
NEEDS_YOU: tuple[str, ...] = ("pending_approval", "changes_requested", "missed")

_ROLES: dict[tuple[str, str], tuple[str, ...]] = {(f, t): roles for f, t, roles in TRANSITIONS}


def check_transition(from_status: str, to_status: str, role: str) -> None:
    """Raise BAD_TRANSITION for an unlisted pair, ROLE_NOT_ALLOWED for an unlisted role."""
    roles = _ROLES.get((from_status, to_status))
    if roles is None:
        raise BrandcalError(
            ErrorCode.BAD_TRANSITION,
            f"{from_status} -> {to_status} is not an allowed status change",
            "see the state machine in SPEC 6",
        )
    if role not in roles:
        raise BrandcalError(
            ErrorCode.ROLE_NOT_ALLOWED,
            f"role {role} may not change {from_status} -> {to_status}",
            f"ask one of: {', '.join(roles)}",
        )

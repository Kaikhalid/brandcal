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
# The "writer (own posts)" ownership rule is checked by the CLI, not here.
TRANSITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("pending_approval", "approved", ("manager",)),
    ("pending_approval", "changes_requested", ("manager",)),
    ("changes_requested", "pending_approval", ("writer", "manager")),
    ("approved", "pending_approval", ("system",)),
    ("missed", "pending_approval", ("system",)),
    ("approved", "published", ("manager",)),
    ("approved", "missed", ("system",)),
    ("missed", "approved", ("manager",)),
    ("pending_approval", "cancelled", ("manager", "writer")),
    ("changes_requested", "cancelled", ("manager", "writer")),
    ("approved", "cancelled", ("manager",)),
    ("missed", "cancelled", ("manager",)),
)

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

"""Stable error codes and the process exit codes they map to.

This is a stub. Every error the CLI reports carries one of these codes in its
JSON output, and the process exits with the matching exit code. Codes are
stable identifiers: never rename or reuse one once released.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class ExitCode(IntEnum):
    """Process exit codes. Several error codes may share one exit code."""

    OK = 0
    USAGE = 2
    VALIDATION = 3
    NOT_ALLOWED = 4
    BAD_STATE = 5
    APPROVAL_MISMATCH = 6
    NOT_FOUND = 7
    CONFLICT = 8


class ErrorCode(StrEnum):
    """Machine-readable error codes. The value always equals the name."""

    TIME_OFFSET_REQUIRED = "TIME_OFFSET_REQUIRED"
    """A timestamp was given without an explicit UTC offset."""

    WINDOW_NOT_APPROVED = "WINDOW_NOT_APPROVED"
    """The post's time window is not inside the window the approver agreed to."""

    NATIVELY_SCHEDULED = "NATIVELY_SCHEDULED"
    """The post is queued in the platform's own scheduler; unschedule it first."""

    CHECK_LIVE_FIRST = "CHECK_LIVE_FIRST"
    """A previous claim expired; confirm the post is not already live first."""

    NO_FRESH_BACKUP = "NO_FRESH_BACKUP"
    """No verified backup exists for the required period."""

    COMMENT_NOT_DELEGATED = "COMMENT_NOT_DELEGATED"
    """Agents never post comments unless a human has delegated that exact comment."""


EXIT_CODES: dict[ErrorCode, ExitCode] = {
    ErrorCode.TIME_OFFSET_REQUIRED: ExitCode.VALIDATION,
    ErrorCode.COMMENT_NOT_DELEGATED: ExitCode.NOT_ALLOWED,
    ErrorCode.NATIVELY_SCHEDULED: ExitCode.BAD_STATE,
    ErrorCode.NO_FRESH_BACKUP: ExitCode.BAD_STATE,
    ErrorCode.WINDOW_NOT_APPROVED: ExitCode.APPROVAL_MISMATCH,
    ErrorCode.CHECK_LIVE_FIRST: ExitCode.CONFLICT,
}
"""Exit code for each error code. TODO: add the remaining codes as commands land."""


def exit_code_for(code: ErrorCode) -> int:
    """Return the process exit code for an error code."""
    return int(EXIT_CODES[code])

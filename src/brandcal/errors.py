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

    BAD_ARGS = "BAD_ARGS"
    """The command line could not be understood."""

    TZ_NOT_CONFIGURED = "TZ_NOT_CONFIGURED"
    """No display timezone is configured (config.json "timezone" or BRANDCAL_TZ)."""

    HOME_NOT_CONFIGURED = "HOME_NOT_CONFIGURED"
    """No data directory is configured (BRANDCAL_HOME or --home)."""

    BAD_TIME = "BAD_TIME"
    """A date or time could not be parsed."""

    BAD_WINDOW = "BAD_WINDOW"
    """A time window is not a valid ISO 8601 interval within one local date."""

    ROLE_NOT_ALLOWED = "ROLE_NOT_ALLOWED"
    """The acting agent's role may not do this."""

    BAD_TRANSITION = "BAD_TRANSITION"
    """This status change is not in the state machine (SPEC 6.1)."""

    EDIT_WHILE_SCHEDULED = "EDIT_WHILE_SCHEDULED"
    """Content or window edits are refused while the post is natively scheduled."""

    EDIT_WHILE_CLAIMED = "EDIT_WHILE_CLAIMED"
    """Edits are refused while the post is claimed for publishing."""

    STALE_APPROVAL = "STALE_APPROVAL"
    """No approval matches the post's current content version and hash."""

    APPEND_ONLY = "APPEND_ONLY"
    """Events and approvals are never changed, and deleted only by an archive run."""

    NO_AGENT = "NO_AGENT"
    """No acting agent given (--as or BRANDCAL_AGENT), or the agent is unknown."""

    MEDIA_INVALID = "MEDIA_INVALID"
    """A media file failed its checks (type, size, alt text, count)."""

    TOO_LONG = "TOO_LONG"
    """A part's text is over the platform's character limit."""

    ON_HOLD = "ON_HOLD"
    """The post has a hold that has not been cleared."""

    NOT_FOUND = "NOT_FOUND"
    """No such post in the live calendar."""

    POST_CLOSED = "POST_CLOSED"
    """The post is published or cancelled and can no longer be changed."""

    INVALID_POST = "INVALID_POST"
    """The post's structure breaks a rule (part count, target URL, article title or body)."""


EXIT_CODES: dict[ErrorCode, ExitCode] = {
    ErrorCode.TIME_OFFSET_REQUIRED: ExitCode.VALIDATION,
    ErrorCode.COMMENT_NOT_DELEGATED: ExitCode.NOT_ALLOWED,
    ErrorCode.NATIVELY_SCHEDULED: ExitCode.BAD_STATE,
    ErrorCode.NO_FRESH_BACKUP: ExitCode.BAD_STATE,
    ErrorCode.WINDOW_NOT_APPROVED: ExitCode.APPROVAL_MISMATCH,
    ErrorCode.CHECK_LIVE_FIRST: ExitCode.CONFLICT,
    ErrorCode.BAD_ARGS: ExitCode.USAGE,
    ErrorCode.TZ_NOT_CONFIGURED: ExitCode.USAGE,
    ErrorCode.HOME_NOT_CONFIGURED: ExitCode.USAGE,
    ErrorCode.BAD_TIME: ExitCode.VALIDATION,
    ErrorCode.BAD_WINDOW: ExitCode.VALIDATION,
    ErrorCode.ROLE_NOT_ALLOWED: ExitCode.NOT_ALLOWED,
    ErrorCode.BAD_TRANSITION: ExitCode.BAD_STATE,
    ErrorCode.EDIT_WHILE_SCHEDULED: ExitCode.BAD_STATE,
    ErrorCode.EDIT_WHILE_CLAIMED: ExitCode.BAD_STATE,
    ErrorCode.STALE_APPROVAL: ExitCode.APPROVAL_MISMATCH,
    ErrorCode.APPEND_ONLY: ExitCode.BAD_STATE,
    ErrorCode.NO_AGENT: ExitCode.USAGE,
    ErrorCode.MEDIA_INVALID: ExitCode.VALIDATION,
    ErrorCode.TOO_LONG: ExitCode.VALIDATION,
    ErrorCode.ON_HOLD: ExitCode.VALIDATION,
    ErrorCode.NOT_FOUND: ExitCode.NOT_FOUND,
    ErrorCode.POST_CLOSED: ExitCode.BAD_STATE,
    ErrorCode.INVALID_POST: ExitCode.VALIDATION,
}
"""Exit code for each error code. TODO: add the remaining codes as commands land."""


def exit_code_for(code: ErrorCode) -> int:
    """Return the process exit code for an error code."""
    return int(EXIT_CODES[code])


class BrandcalError(Exception):
    """An expected failure with a stable code, a message and a suggested next step."""

    def __init__(self, code: ErrorCode, message: str, next_step: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.next_step = next_step

    @property
    def exit_code(self) -> int:
        return exit_code_for(self.code)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": False,
            "error": {"code": self.code.value, "message": self.message, "next": self.next_step},
        }

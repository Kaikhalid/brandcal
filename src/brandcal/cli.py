"""Command-line entry point (stub)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from brandcal import __version__

PLANNED_COMMANDS: tuple[tuple[str, str], ...] = (
    ("help [CMD]", "List commands, or show one command's arguments and rules"),
    ("schema", "Print states, transitions, roles and time format as JSON"),
    ("add", "Add a near-final post (always starts at pending_approval)"),
    ("edit ID field=value", "Change a post; content edits require re-approval"),
    ("submit ID", "Send a post back for approval after requested changes"),
    ("approve / request-changes / reschedule ID", "Record a human approver's decision"),
    ("list / show / today / next", "Read the calendar"),
    ("schedule / unschedule ID", "Record or remove a native platform schedule"),
    ("begin ID", "Claim an approved post for publishing"),
    ("published ID URL / failed ID", "Close out or release a claim"),
    ("cancel ID", "Cancel an open post with a reason"),
    ("sweep", "Mark missed posts and release expired claims"),
    ("audit", "Verify the event hash chain and integrity"),
    ("backup / export", "Verified database backup and JSON export"),
    ("archive run", "Monthly archive of closed posts"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brandcal",
        description="Human-approved social content calendar for AI agents (early development).",
    )
    parser.add_argument("--version", action="version", version=f"brandcal {__version__}")
    sub = parser.add_subparsers(dest="command")
    help_p = sub.add_parser("help", help="show available and planned commands")
    help_p.add_argument("topic", nargs="?", help="command to describe (not yet implemented)")
    return parser


def _print_help() -> None:
    print(f"brandcal {__version__} - early development, not yet usable.")
    print("Planned commands:")
    width = max(len(name) for name, _ in PLANNED_COMMANDS)
    for name, summary in PLANNED_COMMANDS:
        print(f"  {name.ljust(width)}  {summary}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in (None, "help"):
        _print_help()
        return 0
    parser.error(f"unknown command: {args.command}")
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

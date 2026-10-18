"""Command-line entry point: argparse frame, JSON output and the help/schema/init commands."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

from brandcal import __version__
from brandcal import config as cfgmod
from brandcal.db import init_db, open_db
from brandcal.errors import EXIT_CODES, BrandcalError, ErrorCode
from brandcal.transitions import CLOSED, STATES, TRANSITIONS

# Must match the posts.post_type CHECK in schema.sql (SPEC 5.3); test_cli_frame checks this.
POST_TYPES: tuple[str, ...] = (
    "text",
    "image",
    "carousel",
    "thread",
    "article",
    "reshare",
    "video",
    "comment",
)
TIME_FORMAT = "ISO 8601 with an explicit UTC offset, e.g. 2026-03-02T09:00:00+00:00"

# name -> (arguments, roles, error codes). Static; extended as commands land (SPEC 8.1).
_W = ["writer", "manager"]
_ALL = ["all"]
_E_ID = ["NOT_FOUND", "ARCHIVED"]
COMMANDS: dict[str, tuple[str, list[str], list[str]]] = {
    "help": ("[CMD]", _ALL, ["BAD_ARGS"]),
    "schema": ("", _ALL, []),
    "next": ("--as NAME", _ALL, ["NO_AGENT"]),
    "today": ("", _ALL, []),
    "tomorrow": ("", _ALL, []),
    "list": (
        "[--status S] [--from D] [--to D] [--platform P] [--closed]",
        _ALL,
        ["BAD_TIME"],
    ),
    "show": ("ID [--log]", _ALL, _E_ID),
    "add": (
        "(JSON on stdin) [--approver-confirmed MSG --words TEXT]",
        _W,
        ["BAD_ARGS", "NO_AGENT", "ROLE_NOT_ALLOWED", "TOO_LONG", "TIME_OFFSET_REQUIRED"]
        + ["BAD_WINDOW", "BAD_TIME", "MEDIA_INVALID", "COMMENT_NOT_DELEGATED", "ON_HOLD"],
    ),
    "edit": (
        "ID field=value ...",
        _W,
        _E_ID + ["EDIT_WHILE_SCHEDULED", "EDIT_WHILE_CLAIMED", "ROLE_NOT_ALLOWED", "BAD_ARGS"],
    ),
    "part": ("add|edit|move|rm ID ...", _W, _E_ID + ["EDIT_WHILE_SCHEDULED", "BAD_ARGS"]),
    "media": (
        "add ID PART FILE --alt TEXT [--credit --source --licence]",
        _W,
        _E_ID + ["MEDIA_INVALID", "EDIT_WHILE_SCHEDULED", "EDIT_WHILE_CLAIMED"],
    ),
    "note": ("ID TEXT", _ALL, _E_ID),
    "keywords": ("ID WORD ...", _ALL, _E_ID),
    "check": ("ID", _ALL, _E_ID),
    "submit": ("ID", _W, _E_ID + ["BAD_TRANSITION", "ROLE_NOT_ALLOWED"]),
    "preview": ("ID", ["manager"], _E_ID),
    "approve": ("ID ...", ["manager"], _E_ID + ["BAD_TRANSITION", "ROLE_NOT_ALLOWED"]),
    "request-changes": ("ID ...", ["manager"], _E_ID + ["BAD_TRANSITION", "ROLE_NOT_ALLOWED"]),
    "reschedule": ("ID ...", ["manager"], _E_ID + ["BAD_WINDOW", "BAD_TIME"]),
    "cancel": (
        "ID --kind idea|version|plan --reason TEXT",
        ["manager", "writer"],
        _E_ID + ["BAD_TRANSITION", "ROLE_NOT_ALLOWED"],
    ),
    "schedule": ("ID --at TIME", ["manager"], _E_ID + ["WINDOW_NOT_APPROVED", "BAD_TIME"]),
    "unschedule": ("ID", ["manager"], _E_ID),
    "begin": (
        "ID [--not-live]",
        ["manager"],
        _E_ID
        + ["CLAIMED", "CHECK_LIVE_FIRST", "STALE_APPROVAL", "HASH_MISMATCH", "ON_HOLD"]
        + ["WINDOW_NOT_APPROVED", "NATIVELY_SCHEDULED"],
    ),
    "published": ("ID URL [--part N URL ...]", ["manager"], _E_ID + ["URL_CONFLICT"]),
    "failed": ("ID --reason TEXT", ["manager"], _E_ID + ["BAD_TRANSITION"]),
    "sweep": ("", ["system", "any"], []),
    "audit": ("", _ALL, []),
    "report": ("weekly [--end DATE]", ["manager"], ["BAD_TIME"]),
    "render": ("week", ["manager"], []),
    "export": ("", ["admin", "system"], []),
    "backup": ("[restore-test]", ["admin", "system"], ["NO_FRESH_BACKUP"]),
    "archive": (
        "run [--month YYYY-MM] [--dry-run] | list|show|search|stats --month YYYY-MM",
        ["admin", "system", "all (read)"],
        ["NO_FRESH_BACKUP", "BAD_ARGS"],
    ),
    "init": ("", ["admin"], ["NO_AGENT", "ROLE_NOT_ALLOWED", "HOME_NOT_CONFIGURED"]),
    "migrate": ("FILE [--dry-run]", ["admin"], ["BAD_ARGS", "ROLE_NOT_ALLOWED"]),
}


class _Parser(argparse.ArgumentParser):
    """Reports usage errors as BAD_ARGS instead of printing argparse text."""

    def error(self, message: str) -> NoReturn:
        raise BrandcalError(ErrorCode.BAD_ARGS, message, "Run: brandcal help")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="brandcal", add_help=False)
    parser.add_argument("--version", action="version", version=f"brandcal {__version__}")
    # Global options work before or after the command; the subparser copy only sets a value
    # when given, so it never overwrites one given before the command.
    for p, dflt in ((parser, None), (common := _Parser(add_help=False), argparse.SUPPRESS)):
        p.add_argument("--home", metavar="PATH", default=dflt)
        p.add_argument("--as", dest="agent", metavar="NAME", default=dflt)
        p.add_argument("--pretty", action="store_true", default=dflt or False)
    sub = parser.add_subparsers(dest="command", parser_class=_Parser)
    help_p = sub.add_parser("help", parents=[common], add_help=False)
    help_p.add_argument("topic", nargs="?")
    sub.add_parser("schema", parents=[common], add_help=False)
    sub.add_parser("init", parents=[common], add_help=False)
    return parser


def actor(args: argparse.Namespace, cfg: dict[str, Any]) -> tuple[str, str]:
    """The acting (agent id, role) from --as or BRANDCAL_AGENT. Writes call this; reads don't."""
    name = args.agent or os.environ.get("BRANDCAL_AGENT")
    if not name:
        raise BrandcalError(
            ErrorCode.NO_AGENT, "No acting agent given.", "Pass --as NAME or set BRANDCAL_AGENT."
        )
    for agent in cfg.get("agents", []):
        if agent.get("id") == name:
            return name, str(agent["role"])
    raise BrandcalError(ErrorCode.NO_AGENT, f"Unknown agent '{name}'.", "Check config.json agents.")


def cmd_help(args: argparse.Namespace) -> dict[str, object]:
    if args.topic is None:
        return {"ok": True, "commands": [{"name": n, "roles": v[1]} for n, v in COMMANDS.items()]}
    if args.topic not in COMMANDS:
        raise BrandcalError(
            ErrorCode.BAD_ARGS, f"Unknown command '{args.topic}'.", "Run: brandcal help"
        )
    arguments, roles, errors = COMMANDS[args.topic]
    return {
        "ok": True,
        "command": args.topic,
        "arguments": arguments,
        "roles": roles,
        "errors": errors,
    }


def cmd_schema(args: argparse.Namespace) -> dict[str, object]:
    return {
        "ok": True,
        "states": list(STATES),
        "closed_states": sorted(CLOSED),
        "transitions": [{"from": f, "to": t, "roles": list(r)} for f, t, r in TRANSITIONS],
        "post_types": list(POST_TYPES),
        "time_format": TIME_FORMAT,
        "exit_codes": {c.value: int(e) for c, e in EXIT_CODES.items()},
    }


def cmd_init(args: argparse.Namespace) -> dict[str, object]:
    base = cfgmod.home(args.home)
    cfg = cfgmod.load_config(base)
    _, role = actor(args, cfg)
    if role != "admin":
        raise BrandcalError(ErrorCode.ROLE_NOT_ALLOWED, "Only an admin may run init.")
    platforms: dict[str, dict[str, object]] = {}
    pfile = base / str(cfg.get("platforms_file", "platforms.json"))
    if pfile.is_file():
        try:
            platforms = json.loads(pfile.read_text(encoding="utf-8"))
        except ValueError as err:
            raise BrandcalError(ErrorCode.BAD_ARGS, f"Cannot read {pfile.name}: {err}.") from None
    conn = open_db(Path(base) / "brand.db", cfgmod.display_tz(cfg))
    try:
        init_db(conn, cfg.get("agents", []), platforms)
    finally:
        conn.close()
    return {"ok": True, "db": "brand.db"}


COMMAND_FUNCS = {"help": cmd_help, "schema": cmd_schema, "init": cmd_init}


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.command is None:
            args.command, args.topic = "help", None
        result = COMMAND_FUNCS[args.command](args)
    except BrandcalError as err:
        result, code = err.to_dict(), err.exit_code
        pretty = "--pretty" in (argv if argv is not None else sys.argv[1:])
    else:
        code, pretty = 0, args.pretty
    print(json.dumps(result, indent=2 if pretty else None))
    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

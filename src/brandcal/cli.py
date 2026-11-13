"""Command-line entry point: argparse frame, JSON output and the help/schema/init commands."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from brandcal import (
    __version__,
    actions,
    approvals,
    archive,
    backup,
    migrate_v1,
    posts,
    publish,
    relay,
    reports,
    serve,
    sweep,
    timefmt,
)
from brandcal import config as cfgmod
from brandcal.actions import POST_TYPES, TIME_FORMAT, Identity  # noqa: F401
from brandcal.db import init_db, open_db
from brandcal.errors import BrandcalError, ErrorCode

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
        "[--status S] [--from D] [--to D] [--platform P] [--closed] [--with-archive]",
        _ALL,
        ["BAD_TIME"],
    ),
    "show": ("ID [--log]", _ALL, _E_ID),
    "events": (
        "[--since ID] [--post ID] [--actor NAME] [--limit N]",
        _ALL,
        ["BAD_ARGS", "NOT_FOUND", "ARCHIVED"],
    ),
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
    "approve": (
        "ID --version N --hash H --channel card|writer-session --msg MSG --words TEXT"
        " [--relayed-by NAME] [--approver NAME]",
        ["manager"],
        _E_ID
        + ["BAD_TRANSITION", "ROLE_NOT_ALLOWED", "STALE_APPROVAL", "ON_HOLD", "BAD_ARGS"]
        + ["IDENTITY_UNVERIFIED"],
    ),
    "request-changes": (
        "ID --version N --hash H --msg MSG --words TEXT [--approver NAME]"
        " [--what TEXT --where TEXT --instruction TEXT]",
        ["manager"],
        _E_ID
        + ["BAD_TRANSITION", "ROLE_NOT_ALLOWED", "STALE_APPROVAL", "BAD_ARGS", "REASON_REQUIRED"],
    ),
    "reschedule": (
        "ID --version N --hash H --window W --msg MSG --words TEXT [--approver NAME]",
        ["manager"],
        _E_ID
        + ["BAD_WINDOW", "BAD_TIME", "STALE_APPROVAL", "EDIT_WHILE_SCHEDULED"]
        + ["BAD_TRANSITION", "ROLE_NOT_ALLOWED", "BAD_ARGS"],
    ),
    "cancel": (
        "ID --kind idea|version|plan --reason TEXT [--msg MSG --words TEXT] [--approver NAME]",
        ["manager", "writer"],
        _E_ID + ["POST_CLOSED", "NATIVELY_SCHEDULED", "CLAIMED", "ROLE_NOT_ALLOWED", "BAD_ARGS"],
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
        ["NO_FRESH_BACKUP", "CLAIMED", "BAD_ARGS", "ROLE_NOT_ALLOWED", "NOT_FOUND"],
    ),
    "init": ("", ["admin"], ["NO_AGENT", "ROLE_NOT_ALLOWED", "HOME_NOT_CONFIGURED"]),
    "serve": (
        "[--port N] [--dev-unverified]",
        ["admin"],
        ["BAD_ARGS", "NO_AGENT", "ROLE_NOT_ALLOWED", "EXTRA_NOT_INSTALLED"],
    ),
    "relay": (
        "[--local-dev]",
        ["admin"],
        ["BAD_ARGS", "NO_AGENT", "ROLE_NOT_ALLOWED", "SECRET_UNAVAILABLE", "CONNECTOR_REFUSED"]
        + ["CONNECTOR_REPLACED", "PROTOCOL_MISMATCH"],
    ),
    "migrate": (
        "FILE [--dry-run] [--out FILE] [--owner NAME]",
        ["admin"],
        ["BAD_ARGS", "ROLE_NOT_ALLOWED"],
    ),
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
    add_p = sub.add_parser("add", parents=[common], add_help=False)
    add_p.add_argument("--approver-confirmed", metavar="MSG")
    add_p.add_argument("--words")
    add_p.add_argument("--type", dest="post_type")
    add_p.add_argument("--delegation-msg")
    add_p.add_argument("--delegation-words")
    edit_p = sub.add_parser("edit", parents=[common], add_help=False)
    edit_p.add_argument("id")
    edit_p.add_argument("assignments", nargs="+", metavar="field=value")
    part_p = sub.add_parser("part", parents=[common], add_help=False)
    part_sub = part_p.add_subparsers(dest="part_cmd", parser_class=_Parser, required=True)
    for name, extra in (("add", ["text"]), ("edit", ["pos", "text"])):
        p = part_sub.add_parser(name, parents=[common], add_help=False)
        for arg in ["id", *extra]:
            p.add_argument(arg, type=int if arg == "pos" else str)
        if name == "add":
            p.add_argument("--pos", type=int)
    for name, extra in (("move", ["from_pos", "to_pos"]), ("rm", ["pos"])):
        p = part_sub.add_parser(name, parents=[common], add_help=False)
        p.add_argument("id")
        for arg in extra:
            p.add_argument(arg, type=int)
    media_p = sub.add_parser("media", parents=[common], add_help=False)
    media_sub = media_p.add_subparsers(dest="media_cmd", parser_class=_Parser, required=True)
    madd = media_sub.add_parser("add", parents=[common], add_help=False)
    madd.add_argument("id")
    madd.add_argument("part", type=int)
    madd.add_argument("file")
    madd.add_argument("--alt", required=True)
    madd.add_argument("--credit")
    madd.add_argument("--source")
    madd.add_argument("--licence")
    note_p = sub.add_parser("note", parents=[common], add_help=False)
    note_p.add_argument("id")
    note_p.add_argument("text")
    kw_p = sub.add_parser("keywords", parents=[common], add_help=False)
    kw_p.add_argument("id")
    kw_p.add_argument("words", nargs="*")
    for name in ("check", "submit", "preview"):
        sub.add_parser(name, parents=[common], add_help=False).add_argument("id")
    for name, extra in (
        ("approve", ["channel", "msg", "words"]),
        ("request-changes", ["msg", "words"]),
        ("reschedule", ["window", "msg", "words"]),
    ):
        p = sub.add_parser(name, parents=[common], add_help=False)
        p.add_argument("id")
        p.add_argument("--version", type=int, required=True)
        p.add_argument("--hash", required=True)
        for arg in extra:
            p.add_argument(f"--{arg}", required=True)
        p.add_argument("--approver")
        if name == "approve":
            p.add_argument("--relayed-by")
        if name == "request-changes":
            for field in ("what", "where", "instruction"):
                p.add_argument(f"--{field}")
    cancel_p = sub.add_parser("cancel", parents=[common], add_help=False)
    cancel_p.add_argument("id")
    cancel_p.add_argument("--kind", required=True)
    cancel_p.add_argument("--reason", required=True)
    cancel_p.add_argument("--msg")
    cancel_p.add_argument("--words")
    cancel_p.add_argument("--approver")
    sched_p = sub.add_parser("schedule", parents=[common], add_help=False)
    sched_p.add_argument("id")
    sched_p.add_argument("--at", required=True)
    sub.add_parser("unschedule", parents=[common], add_help=False).add_argument("id")
    begin_p = sub.add_parser("begin", parents=[common], add_help=False)
    begin_p.add_argument("id")
    begin_p.add_argument("--not-live", action="store_true")
    pub_p = sub.add_parser("published", parents=[common], add_help=False)
    pub_p.add_argument("id")
    pub_p.add_argument("url")
    pub_p.add_argument("--part", nargs=2, action="append", metavar=("N", "URL"), default=[])
    failed_p = sub.add_parser("failed", parents=[common], add_help=False)
    failed_p.add_argument("id")
    failed_p.add_argument("--reason", required=True)
    sub.add_parser("sweep", parents=[common], add_help=False)
    sub.add_parser("audit", parents=[common], add_help=False)
    for name in ("next", "today", "tomorrow"):
        sub.add_parser(name, parents=[common], add_help=False)
    list_p = sub.add_parser("list", parents=[common], add_help=False)
    list_p.add_argument("--status")
    list_p.add_argument("--from", dest="date_from")
    list_p.add_argument("--to", dest="date_to")
    list_p.add_argument("--platform")
    list_p.add_argument("--closed", action="store_true")
    list_p.add_argument("--with-archive", action="store_true")
    show_p = sub.add_parser("show", parents=[common], add_help=False)
    show_p.add_argument("id")
    show_p.add_argument("--log", action="store_true")
    events_p = sub.add_parser("events", parents=[common], add_help=False)
    events_p.add_argument("--since", type=int)
    events_p.add_argument("--post")
    events_p.add_argument("--actor")
    events_p.add_argument("--limit", type=int, default=actions.EVENTS_LIMIT)
    report_p = sub.add_parser("report", parents=[common], add_help=False)
    report_sub = report_p.add_subparsers(dest="report_cmd", parser_class=_Parser, required=True)
    report_sub.add_parser("weekly", parents=[common], add_help=False).add_argument("--end")
    render_p = sub.add_parser("render", parents=[common], add_help=False)
    render_sub = render_p.add_subparsers(dest="render_cmd", parser_class=_Parser, required=True)
    render_sub.add_parser("week", parents=[common], add_help=False).add_argument("--out")
    sub.add_parser("export", parents=[common], add_help=False)
    backup_p = sub.add_parser("backup", parents=[common], add_help=False)
    backup_sub = backup_p.add_subparsers(dest="backup_cmd", parser_class=_Parser)
    backup_sub.add_parser("restore-test", parents=[common], add_help=False)
    archive_p = sub.add_parser("archive", parents=[common], add_help=False)
    archive_sub = archive_p.add_subparsers(dest="archive_cmd", parser_class=_Parser, required=True)
    run_p = archive_sub.add_parser("run", parents=[common], add_help=False)
    run_p.add_argument("--month")
    run_p.add_argument("--dry-run", action="store_true")
    for name in ("list", "show", "search", "stats"):
        read_p = archive_sub.add_parser(name, parents=[common], add_help=False)
        if name == "show":
            read_p.add_argument("id")
            read_p.add_argument("--log", action="store_true")
        if name == "search":
            read_p.add_argument("text")
        read_p.add_argument("--month", required=True)
    serve_p = sub.add_parser("serve", parents=[common], add_help=False)
    serve_p.add_argument("--port", type=int)
    serve_p.add_argument("--dev-unverified", action="store_true")
    relay_p = sub.add_parser("relay", parents=[common], add_help=False)
    relay_p.add_argument("--local-dev", action="store_true")
    migrate_p = sub.add_parser("migrate", parents=[common], add_help=False)
    migrate_p.add_argument("file")
    migrate_p.add_argument("--dry-run", action="store_true")
    migrate_p.add_argument("--out")
    migrate_p.add_argument("--owner")
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
    return actions.schema()


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


@contextmanager
def _session(args: argparse.Namespace, write: bool = True) -> Iterator[_Session]:
    """Open home/brand.db with the display timezone; writes also resolve the acting agent."""
    base = cfgmod.home(args.home)
    cfg = cfgmod.load_config(base)
    who, role = actor(args, cfg) if write else ("", "")
    if not (base / "brand.db").is_file():
        raise BrandcalError(ErrorCode.BAD_ARGS, "No brand.db here.", "Run: brandcal init")
    conn = open_db(base / "brand.db", cfgmod.display_tz(cfg))
    try:
        yield _Session(conn, base, cfg, who, role)
    finally:
        conn.close()


@dataclass
class _Session:
    conn: sqlite3.Connection
    base: Path
    cfg: dict[str, Any]
    who: str
    role: str


def cmd_add(args: argparse.Namespace) -> dict[str, object]:
    try:
        data = json.loads(sys.stdin.read())
    except ValueError as err:
        raise BrandcalError(ErrorCode.BAD_ARGS, f"stdin is not valid JSON: {err}.") from None
    if not isinstance(data, dict):
        raise BrandcalError(ErrorCode.BAD_ARGS, "stdin must be one JSON object.")
    for key, value in (
        ("post_type", args.post_type),
        ("delegation_msg_id", args.delegation_msg),
        ("delegation_words", args.delegation_words),
    ):
        if value:
            data[key] = value
    with _session(args) as s:
        out: dict[str, object] = posts.add_post(
            s.conn, s.who, s.role, s.cfg, data, args.approver_confirmed, args.words
        )
        return out


def cmd_edit(args: argparse.Namespace) -> dict[str, object]:
    with _session(args) as s:
        return actions.edit(s.conn, s.cfg, Identity(s.who), args.id, args.assignments)


def cmd_part(args: argparse.Namespace) -> dict[str, object]:
    with _session(args) as s:
        c, w, r, g = s.conn, s.who, s.role, s.cfg
        out: dict[str, object]
        if args.part_cmd == "add":
            out = posts.part_add(c, w, r, g, args.id, args.text, args.pos)
        elif args.part_cmd == "edit":
            out = posts.part_edit(c, w, r, g, args.id, args.pos, args.text)
        elif args.part_cmd == "move":
            out = posts.part_move(c, w, r, g, args.id, args.from_pos, args.to_pos)
        else:
            out = posts.part_rm(c, w, r, g, args.id, args.pos)
        return out


def cmd_media(args: argparse.Namespace) -> dict[str, object]:
    with _session(args) as s:
        out: dict[str, object] = posts.media_add(
            s.conn,
            s.who,
            s.role,
            s.cfg,
            s.base,
            args.id,
            args.part,
            Path(args.file),
            args.alt,
            args.credit,
            args.source,
            args.licence,
        )
        return out


def cmd_note(args: argparse.Namespace) -> dict[str, object]:
    with _session(args) as s:
        return actions.note(s.conn, s.cfg, Identity(s.who), args.id, args.text)


def cmd_keywords(args: argparse.Namespace) -> dict[str, object]:
    with _session(args) as s:
        out: dict[str, object] = posts.set_keywords(s.conn, s.who, s.cfg, args.id, args.words)
        return out


def cmd_check(args: argparse.Namespace) -> dict[str, object]:
    with _session(args, write=False) as s:
        return actions.check(s.conn, s.cfg, args.id)


def cmd_submit(args: argparse.Namespace) -> dict[str, object]:
    with _session(args) as s:
        return actions.submit(s.conn, s.cfg, Identity(s.who), args.id)


def cmd_preview(args: argparse.Namespace) -> dict[str, object]:
    with _session(args, write=False) as s:
        out: dict[str, object] = approvals.preview(s.conn, s.cfg, args.id)
        return out


def cmd_approve(args: argparse.Namespace) -> dict[str, object]:
    # No verified identity here, so channel console is refused (IDENTITY_UNVERIFIED).
    with _session(args) as s:
        return actions.approve(
            s.conn, s.cfg, Identity(s.who), args.id, args.version, args.hash, args.channel,
            args.msg, args.words, args.relayed_by, args.approver,
        )  # fmt: skip


def cmd_request_changes(args: argparse.Namespace) -> dict[str, object]:
    with _session(args) as s:
        return actions.request_changes(
            s.conn, s.cfg, Identity(s.who), args.id, args.version, args.hash, args.msg, args.words,
            args.approver, what=args.what, where=args.where, instruction=args.instruction,
        )  # fmt: skip


def cmd_reschedule(args: argparse.Namespace) -> dict[str, object]:
    with _session(args) as s:
        return actions.reschedule(
            s.conn, s.cfg, Identity(s.who), args.id, args.version, args.hash, args.window,
            args.msg, args.words, args.approver,
        )  # fmt: skip


def cmd_cancel(args: argparse.Namespace) -> dict[str, object]:
    with _session(args) as s:
        return actions.cancel(
            s.conn, s.cfg, Identity(s.who), args.id, args.kind, args.reason, args.msg, args.words,
            args.approver,
        )  # fmt: skip


def cmd_schedule(args: argparse.Namespace) -> dict[str, object]:
    with _session(args) as s:
        out: dict[str, object] = publish.schedule(
            s.conn, s.who, s.role, s.cfg, s.base, args.id, args.at
        )
        return out


def cmd_unschedule(args: argparse.Namespace) -> dict[str, object]:
    with _session(args) as s:
        out: dict[str, object] = publish.unschedule(s.conn, s.who, s.role, s.cfg, args.id)
        return out


def cmd_begin(args: argparse.Namespace) -> dict[str, object]:
    with _session(args) as s:
        out: dict[str, object] = publish.begin(
            s.conn, s.who, s.role, s.cfg, s.base, args.id, args.not_live
        )
        return out


def cmd_published(args: argparse.Namespace) -> dict[str, object]:
    part_urls: dict[int, str] = {}
    for number, url in args.part:
        if not number.isdigit():
            raise BrandcalError(ErrorCode.BAD_ARGS, f"--part needs a part number, not {number!r}.")
        part_urls[int(number)] = url
    with _session(args) as s:
        out: dict[str, object] = publish.published(
            s.conn, s.who, s.role, s.cfg, args.id, args.url, part_urls
        )
        return out


def cmd_failed(args: argparse.Namespace) -> dict[str, object]:
    with _session(args) as s:
        out: dict[str, object] = publish.failed(s.conn, s.who, s.role, s.cfg, args.id, args.reason)
        return out


def cmd_sweep(args: argparse.Namespace) -> dict[str, object]:
    """Any agent may run it; the agent is optional and, when given, is recorded."""
    named = bool(args.agent or os.environ.get("BRANDCAL_AGENT"))
    with _session(args, write=named) as s:
        out: dict[str, object] = sweep.sweep(s.conn, s.cfg, agent=s.who or None)
        return out


def cmd_audit(args: argparse.Namespace) -> dict[str, object]:
    """Read-only; exits 0 even with flags, the caller reads ok and flags."""
    with _session(args, write=False) as s:
        return actions.audit(s.conn, s.base)


def cmd_next(args: argparse.Namespace) -> dict[str, object]:
    """The agent comes from --as only, so a manager can look up another agent's list."""
    with _session(args, write=False) as s:
        if not args.agent:
            raise BrandcalError(ErrorCode.NO_AGENT, "No agent given.", "Pass --as NAME.")
        return {"ok": True, "items": reports.next_for(s.conn, s.cfg, args.agent)}


def cmd_today(args: argparse.Namespace) -> dict[str, object]:
    with _session(args, write=False) as s:
        return actions.today(s.conn, s.cfg, args.command)


def cmd_list(args: argparse.Namespace) -> dict[str, object]:
    with _session(args, write=False) as s:
        return actions.list_posts(
            s.conn, s.cfg, s.base, args.status, args.date_from, args.date_to, args.platform,
            args.closed, args.with_archive,
        )  # fmt: skip


def cmd_show(args: argparse.Namespace) -> dict[str, object]:
    with _session(args, write=False) as s:
        return actions.show(s.conn, args.id, args.log)


def cmd_events(args: argparse.Namespace) -> dict[str, object]:
    with _session(args, write=False) as s:
        return actions.events(s.conn, args.since, args.post, args.actor, args.limit)


def _manager_only(args: argparse.Namespace, cfg: dict[str, Any]) -> None:
    if actor(args, cfg)[1] != "manager":
        raise BrandcalError(ErrorCode.ROLE_NOT_ALLOWED, "Only a manager may run this command.")


def cmd_report(args: argparse.Namespace) -> dict[str, object]:
    with _session(args, write=False) as s:
        _manager_only(args, s.cfg)
        end = None if args.end is None else timefmt.parse_date(args.end)
        out: dict[str, object] = reports.weekly(s.conn, s.cfg, s.base, end)
        return out


def cmd_render(args: argparse.Namespace) -> dict[str, object]:
    with _session(args, write=False) as s:
        _manager_only(args, s.cfg)
        page = reports.render_week(s.conn, s.cfg)
    if args.out:
        Path(args.out).write_text(page, encoding="utf-8")
        return {"ok": True, "out": args.out}
    return {"ok": True, "html": page}


def _admin_or_system(role: str) -> None:
    if role not in ("admin", "system"):
        raise BrandcalError(ErrorCode.ROLE_NOT_ALLOWED, "Only an admin or system may run this.")


def cmd_export(args: argparse.Namespace) -> dict[str, object]:
    with _session(args) as s:
        _admin_or_system(s.role)
        out: dict[str, object] = backup.export(s.conn, s.cfg, s.base)
        return out


def cmd_backup(args: argparse.Namespace) -> dict[str, object]:
    if args.backup_cmd == "restore-test":
        # Never opens the live database: only home and config are needed.
        base = cfgmod.home(args.home)
        cfg = cfgmod.load_config(base)
        _admin_or_system(actor(args, cfg)[1])
        out: dict[str, object] = backup.restore_test(base, cfg)
        return out
    with _session(args) as s:
        _admin_or_system(s.role)
        out = backup.backup(s.conn, s.cfg, s.base, s.who)
        return out


def cmd_archive(args: argparse.Namespace) -> dict[str, object]:
    with _session(args, write=args.archive_cmd == "run") as s:
        out: dict[str, object]
        if args.archive_cmd == "run":
            _admin_or_system(s.role)
            out = archive.run(s.conn, s.cfg, s.base, s.who, args.month, args.dry_run)
        elif args.archive_cmd == "list":
            out = actions.archive_list(s.base, s.cfg, args.month)
        elif args.archive_cmd == "show":
            out = actions.archive_show(s.base, args.month, args.id, args.log)
        elif args.archive_cmd == "search":
            out = actions.archive_search(s.base, args.month, args.text)
        else:
            out = actions.archive_stats(s.conn, args.month)
        return out


def cmd_serve(args: argparse.Namespace) -> dict[str, object]:
    """Serve the web UI's JSON API on 127.0.0.1 (UI_SPEC 2.1); runs until interrupted."""
    base = cfgmod.home(args.home)
    cfg = cfgmod.load_config(base)
    if actor(args, cfg)[1] != "admin":
        raise BrandcalError(ErrorCode.ROLE_NOT_ALLOWED, "Only an admin may run serve.")
    cfgmod.display_tz(cfg)
    if not (base / "brand.db").is_file():
        raise BrandcalError(ErrorCode.BAD_ARGS, "No brand.db here.", "Run: brandcal init")
    return serve.run(base, cfg, args.port, args.dev_unverified)


def cmd_relay(args: argparse.Namespace) -> dict[str, object]:
    """Connect to the Worker relay and replay its requests to `serve`; runs until SIGTERM."""
    base = cfgmod.home(args.home)
    cfg = cfgmod.load_config(base)
    if actor(args, cfg)[1] != "admin":
        raise BrandcalError(ErrorCode.ROLE_NOT_ALLOWED, "Only an admin may run relay.")
    cfgmod.display_tz(cfg)
    return relay.run(base, cfg, args.local_dev)


def cmd_migrate(args: argparse.Namespace) -> dict[str, object]:
    with _session(args) as s:
        if s.role != "admin":
            raise BrandcalError(ErrorCode.ROLE_NOT_ALLOWED, "Only an admin may run migrate.")
        try:
            data = json.loads(Path(args.file).read_text(encoding="utf-8"))
        except (ValueError, OSError) as err:
            raise BrandcalError(ErrorCode.BAD_ARGS, f"Cannot read {args.file}: {err}.") from None
        out: dict[str, object] = migrate_v1.migrate(
            s.conn,
            s.cfg,
            s.base,
            data,
            s.who,
            dry_run=args.dry_run,
            out=Path(args.out) if args.out else None,
            owner=args.owner,
        )
        return out


COMMAND_FUNCS = {
    "serve": cmd_serve,
    "relay": cmd_relay,
    "archive": cmd_archive,
    "migrate": cmd_migrate,
    "export": cmd_export,
    "backup": cmd_backup,
    "next": cmd_next,
    "today": cmd_today,
    "tomorrow": cmd_today,
    "list": cmd_list,
    "show": cmd_show,
    "events": cmd_events,
    "report": cmd_report,
    "render": cmd_render,
    "help": cmd_help,
    "schema": cmd_schema,
    "init": cmd_init,
    "add": cmd_add,
    "edit": cmd_edit,
    "part": cmd_part,
    "media": cmd_media,
    "note": cmd_note,
    "keywords": cmd_keywords,
    "check": cmd_check,
    "submit": cmd_submit,
    "preview": cmd_preview,
    "approve": cmd_approve,
    "request-changes": cmd_request_changes,
    "reschedule": cmd_reschedule,
    "cancel": cmd_cancel,
    "schedule": cmd_schedule,
    "unschedule": cmd_unschedule,
    "begin": cmd_begin,
    "published": cmd_published,
    "failed": cmd_failed,
    "sweep": cmd_sweep,
    "audit": cmd_audit,
}


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

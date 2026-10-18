# brandcal

A generic, open-source command-line tool and SQLite library for AI agents that manage a
**human-approved** social media content calendar.

> **Status:** early development (v0.x). The core commands work and are tested, but
> interfaces, schema and error codes may still change until v1.0.

## What it is

brandcal keeps a content calendar in a single SQLite file and gives AI agents a small,
strict CLI to work with it. Agents draft, schedule and publish posts; a human approves every
single post before it can go out. Every change is recorded in an append-only, hash-chained
event log, so you can always see who did what and when.

It is deliberately generic: no platform credentials, no posting bots, no built-in brand.
You bring your own agents and your own publishing workflow.

## Roles

| Role | Who | Can |
|---|---|---|
| `writer` | AI agent | Add and edit posts, resubmit after requested changes |
| `manager` | AI agent | Relay the approver's decisions, schedule, claim and record publication |
| `approver` | **Human** | Approve, request changes, reschedule or cancel. Only a human approves. |

## The 6-state model

Every post is in exactly one of six states. `published` and `cancelled` are closed and are
never reopened.

```mermaid
stateDiagram-v2
  [*] --> pending_approval : writer adds a post
  pending_approval --> approved : approver approves this version and window
  pending_approval --> changes_requested : approver requests changes
  changes_requested --> pending_approval : writer edits and resubmits
  approved --> pending_approval : content edited (automatic)
  approved --> published : manager publishes and records the URL
  approved --> missed : window ended unpublished
  missed --> approved : approver agrees a new window
  missed --> pending_approval : content edited (automatic)
  pending_approval --> cancelled
  changes_requested --> cancelled
  approved --> cancelled
  missed --> cancelled : approver cancels
  published --> [*]
  cancelled --> [*]
```

| State | Meaning |
|---|---|
| `pending_approval` | Near-final post waiting for the human approver |
| `changes_requested` | The approver asked for changes |
| `approved` | The approver approved this exact content (by hash) and time window |
| `missed` | The approved window ended without the post going out |
| `published` | Live, with its URL recorded (closed) |
| `cancelled` | Dropped, with a reason (closed) |

Being queued in a platform's native scheduler, or being claimed by an agent for publishing,
are **fields on an approved post**, not separate states.

## Design principles

- **A human approves every post.** Approval is per post, bound to a content hash and to a
  time window. Any content edit sends the post back to `pending_approval`; publishing or
  scheduling outside the approved window is refused (`WINDOW_NOT_APPROVED`).
- **Agents never comment.** Comments and replies are not delegated to agents
  (`COMMENT_NOT_DELEGATED`).
- **Explicit time offsets.** Every time is ISO 8601 with an explicit UTC offset, such as
  `2026-03-02T09:00:00+01:00`. A time without an offset is rejected
  (`TIME_OFFSET_REQUIRED`). The display timezone is configurable; there is no hidden default.
- **Append-only audit.** Every change writes an event; events form a hash chain that
  `brandcal audit` can verify.
- **Safe housekeeping.** Monthly archive of closed posts and verified backups
  (`NO_FRESH_BACKUP` blocks the archive if there is no checked backup).
- **Machine-friendly.** One-line JSON output and stable error codes with documented exit codes.

## Commands

| Command | Purpose |
|---|---|
| `brandcal help [CMD]` | List commands, or describe one (arguments, roles, errors) |
| `brandcal schema` | States, transitions, roles and time format as JSON |
| `brandcal init` | Create `brand.db` from the schema and seed agents and platforms from config |
| `brandcal add` / `edit` / `part` / `media add` / `submit` | Write and revise posts |
| `brandcal note` / `keywords` / `check` | Notes, keywords and validation (not content) |
| `brandcal preview` | Card data for the manager to show the approver |
| `brandcal approve` / `request-changes` / `reschedule` | Record the human approver's decision |
| `brandcal cancel` | Cancel an open post with a kind and a reason |
| `brandcal schedule` / `unschedule` | Record a native platform schedule |
| `brandcal begin` / `published` / `failed` | Claim, publish and close out a post |
| `brandcal list` / `show` / `today` / `tomorrow` / `next` | Read the calendar |
| `brandcal report weekly` / `render week` | Weekly JSON report and weekly HTML page |
| `brandcal sweep` | Mark missed posts, release expired claims |
| `brandcal audit` | Verify hash chains, approvals of published posts and media checksums |
| `brandcal export` / `backup` / `backup restore-test` | JSON export, checked database copies and a restore test |
| `brandcal migrate FILE [--dry-run]` | Import a v1 JSON calendar |

Every command prints one line of JSON. Every write needs `--as NAME` (or `BRANDCAL_AGENT`).
Error codes and exit codes are listed in [docs/ERRORS.md](docs/ERRORS.md); the full
specification is [docs/SPEC.md](docs/SPEC.md).

## Quick start

This runs against the fake data in [examples/](examples/), in a throwaway data directory.
A test (`tests/test_readme.py`) runs these exact commands, so they stay correct.

<!-- quickstart -->
```sh
export BRANDCAL_HOME="$(mktemp -d)"
cp examples/config.json examples/platforms.json "$BRANDCAL_HOME/"
brandcal init --as admin-1
brandcal add --as writer-1 < examples/posts/example-launch.json
brandcal list
brandcal show p0001
brandcal check p0001
brandcal next --as approver-1
brandcal preview p0001 --as manager-1
brandcal audit
brandcal backup --as admin-1
brandcal migrate examples/v1_calendar.example.json --dry-run --as admin-1
```
<!-- /quickstart -->

`preview` returns the version and hash the approver sees. Once the human approver has
agreed, the manager records it with the same version and hash, for example
`brandcal approve p0001 --version 1 --hash <hash> --channel card --msg msg-001 --words "Approved" --as manager-1`.
The post can then be scheduled or published inside its approved window.

## Install and development

Requires Python 3.11 or newer. brandcal uses only the standard library at runtime
(including `sqlite3`).

```sh
git clone https://github.com/Kaikhalid/brandcal.git
cd brandcal
git switch work
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

brandcal --version
brandcal help
```

Set `BRANDCAL_HOME` to your data directory and give it a `config.json` (see
[examples/config.json](examples/config.json) and SPEC 13). There is no default timezone:
set `"timezone"` in the config or `BRANDCAL_TZ`.

Checks (run all of them before committing):

```sh
ruff check .
ruff format --check .
mypy src
pytest
python scripts/privacy_scan.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and, for AI agents, [AGENTS.md](AGENTS.md).
The generic specification is [docs/SPEC.md](docs/SPEC.md). Example data is in
[examples/](examples/).

## Licence

MIT. See [LICENSE](LICENSE).

# brandcal on Cloudflare: Workers + D1

Status: built and conformance-tested; staging first, production switchover by runbook. Hosts and
ids below are placeholders (`brandcal.example.com`, `example.cloudflareaccess.com`). Real values
live only in the private deployment config and the operator's runbook, never in this repository.

## 1. Why

Until now `brandcal serve` ran on one machine and a Worker relayed browser requests to it
([DEPLOY_RELAY.md](docs/DEPLOY_RELAY.md)). If that machine sleeps, restarts or loses its link, the
web UI is down, and the calendar's only copy lives on its disk. The goal: nothing depends on a
single machine, it stays within Cloudflare's free tier, and the Python core stays the reference.

## 2. Architecture

```
browser ──▶ Access (people: passkey or email code) ──▶ Worker "brandcal" ──▶ D1 "brandcal"
agents  ──▶ Access (service token)                ──▶    │  static assets: src/brandcal/web_next
                                                          └─ cron: daily JSON snapshot to KV
```

- One Worker (`cloud/`) serves the built Next.js UI from Workers static assets and the same JSON
  API as `brandcal serve` (UI_SPEC 1.3) from D1. Same paths, bodies, status codes, `X-Brandcal-Exit`
  header, per-page Content-Security-Policy and hardening headers.
- `cloud/src/model.ts` is a port of the console's part of the Python core: list, detail, versions,
  events, schema, and the seven console writes (approve, request changes, change time, cancel,
  edit, submit, note), with validation, the content hash, the event hash chain and the content-bump
  rule that the SQLite triggers enforce locally.
- Agents keep the full Python core. In remote mode (section 5) the CLI runs every command on a
  fresh local copy and pushes only the row changes back.
- No media files live in the cloud yet: the media endpoint answers 404. The calendar has none
  today; R2 can be added later (it needs a payment method on the account).
- The relay, the box connector and the Durable Object are retired after the switchover.

## 3. Data mapping

`cloud/schema.sql` is generated from `src/brandcal/schema.sql` by `cloud/scripts/make_schema.py`
(`tests/test_cloud_schema.py` fails if it is stale). Every table, column, generated column, CHECK
and foreign key is the same, with two D1 differences:

| Python (SQLite) | D1 |
|---|---|
| Triggers that call `bc_now()` and `bc_row_hash()` (content bump) and the status triggers | Left out: D1 cannot register SQL functions. The Worker port and the Python core enforce them in code; the Worker re-checks pushes (section 5). |
| `window GLOB '<51-char pattern>'` | Same rule split in two GLOBs (D1 refuses patterns over 50 bytes). |
| none | `meta` table: `gen` (write generation) and `config` (the `config.json` the server needs). |

Append-only and role triggers on events and approvals are kept. Rows are copied verbatim, so
content hashes and event hashes carry over and `brandcal audit` still verifies the chains.

Every write is optimistic: a batch (one D1 transaction) starts with
`UPDATE meta SET v = seen + 1 WHERE k = 'gen'`, and a trigger aborts the batch if another write
moved the generation first. The writer reloads and tries again (three times).

## 4. Identity and approval semantics

- Cloudflare Access gates the hostname. The Worker verifies `Cf-Access-Jwt-Assertion` again, as
  `brandcal serve` does: RS256 only, the team's published keys, the exact audience, issuer, expiry
  and not-before (60 s leeway).
- People: the email maps to `serve.approvers` (approver with its agent id) or `serve.viewers`.
  A console decision by the verified approver counts as the approver's sign-off only when
  `serve.console_approvals` is JSON `true` (UI_SPEC 2.6), recorded with channel `console`,
  `verified_identity` and `identity_source = access-jwt`.
- Writes need an allowed `Origin` and `Host` and a CSRF token: an HMAC of the identity under the
  Worker secret `CSRF_SECRET`.
- Service tokens (no email, a `common_name`) reach only `/api/sync/*`, and only if the client id
  is listed in `serve.service_tokens`. People never reach the sync endpoints.

## 5. CLI remote mode

```
export BRANDCAL_REMOTE=https://brandcal.example.com
export BRANDCAL_ACCESS_CLIENT_ID=...      # Access service token, environment only
export BRANDCAL_ACCESS_CLIENT_SECRET=...  # never printed, logged or written to a file
brandcal list
brandcal published <ID> <URL> --as manager-1
brandcal pull --out /tmp/brand.db         # a read-only local copy (for scripts and backups)
```

1. `GET /api/sync/snapshot` returns every table, the config and the generation.
2. The CLI builds a temporary home (schema, rows, triggers) and runs the command with the normal
   Python code, so output, exit codes and every rule are exactly the local ones.
3. It diffs the five calendar tables and sends `POST /api/sync/apply {base_gen, changes}`.
4. The Worker refuses: other tables, updates or deletes of events and approvals, ids that do not
   follow the last one, events that do not continue their hash chain (it recomputes each
   `row_hash`), post deletes, and any approval with channel `console` or a verified identity
   (only the Worker records those, for the person Access verified).
5. A stale generation answers 409 and the CLI reruns the command on a fresh copy.

Not available remotely (they work on local files): `init`, `migrate`, `backup`, `export`,
`archive`, `media`, `render`, `serve`, `relay`.

## 6. Backup and restore

- D1 Time Travel: point-in-time restore for the last 7 days (free plan), no setup.
- The Worker's daily cron writes a JSON snapshot to KV (`snapshot/YYYY-MM-DD.json`, kept 35 days).
- Agents can keep an off-Cloudflare copy with `brandcal pull --out <file>` in the nightly routine.
- Restore: Time Travel `wrangler d1 time-travel restore`, or rebuild a home from a snapshot and
  re-import it with `cloud/scripts/d1_export.py`.

## 7. Import

```
python cloud/scripts/make_schema.py                         # only if schema.sql changed
python cloud/scripts/d1_export.py COPY_OF_HOME seed.sql --service-token CLIENT_ID
wrangler d1 execute <db> --remote --file seed.sql           # into an empty database
```

Run the export on a copy of the home (it only reads). It drops the `relay` block from the config.

## 8. Deploy and switchover (outline)

1. Create the D1 database and KV namespace, put `CSRF_SECRET`, deploy the Worker on a staging
   host behind its own Access application, import a copy, and compare it with the source.
2. Freeze writes, take a final copy, import it into the production database, deploy the Worker
   on the production host (replacing the relay's custom domain), point the agents at remote mode.
3. Rollback: put the relay's custom domain back on the old Worker and restart `serve` and the
   connector on the original home, which stays untouched until the new setup has run for a week.

The exact runbook with real names and timings is private to the operator.

## 9. Tests

- `tests/test_cloud_conformance.py` (opt-in, `BRANDCAL_CLOUD_CONFORMANCE=1`, needs Node): one
  seeded home, two copies; every API request goes to `brandcal serve` and to the Worker under
  `wrangler dev` with a local D1, and the answers must match with times of day masked. The same
  CLI commands run locally and in remote mode. Afterwards both databases must hold the same rows
  and the Worker's copy must pass `brandcal audit`. Static files must match too.
- `tests/test_remote.py` and `tests/test_cloud_schema.py` run in the normal suite.
- CI job `cloud` runs the TypeScript check and the conformance suite.

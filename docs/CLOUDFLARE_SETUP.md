# Self-hosting brandcal on Cloudflare (Workers + D1 + Access)

This guide takes you from a fresh Cloudflare account to a working hosted brandcal calendar: the
web UI served from Workers static assets, the API backed by D1, daily JSON backups to KV,
Cloudflare Access in front of everything, and the Python CLI connected in remote mode.

All hostnames, emails and ids in this guide are placeholders:

- `brandcal.example.com`: your calendar hostname
- `your-team.cloudflareaccess.com`: your Cloudflare Zero Trust team domain
- `you@example.com`: the human owner's email address
- `00000000-0000-0000-0000-000000000000`: placeholder for Cloudflare database, KV, Access and token ids

Never commit your real values to Git. Keep them in `cloud/wrangler.local.jsonc` (git-ignored),
Wrangler secrets and your private environment.

For architecture background and D1 schema details, see [D1_MIGRATION.md](../D1_MIGRATION.md).

## 1. Prerequisites

- A Cloudflare account (the free tier is enough for Workers, D1, KV and Access for a small team).
- A domain whose DNS is managed by Cloudflare (for example `example.com`).
- Zero Trust enabled in the Cloudflare dashboard (this gives you `your-team.cloudflareaccess.com`).
- Python 3.11 or newer.
- Node.js 22 or newer for Wrangler and the Worker tooling (and Node 20 only if you rebuild the
  Next.js front end yourself).

Log in to Wrangler once before running the commands below:

```sh
npx --prefix cloud wrangler login
```

## 2. Clone the repository and check the web UI build

Clone brandcal, install the Python CLI in a virtual environment and install the Cloud Worker
tooling:

```sh
git clone https://github.com/Kaikhalid/brandcal.git
cd brandcal
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
npm --prefix cloud ci
```

The built Next.js static export is already committed under `src/brandcal/web_next/`, so a fresh
checkout is ready to deploy without building the front end.

If you edit files in `web/` or want to rebuild the static export yourself, use Node 20 and run:

```sh
python scripts/build_ui.py
```

This runs `npm ci` (if needed) and `npm run build` inside `web/`, then copies the static output
and its per-page Content Security Policy hashes (`csp.json`) into `src/brandcal/web_next/`.

## 3. Create the D1 database

Create a new D1 database named `brandcal`:

```sh
npx --prefix cloud wrangler d1 create brandcal
```

Copy the `database_id` UUID from the command output. You will put it into your private Wrangler
config in step 5.

Note on schema and migrations: brandcal does not use D1 migration folders. The full D1 schema
lives in `cloud/schema.sql` (generated from `src/brandcal/schema.sql` by
`cloud/scripts/make_schema.py`). In step 9, `cloud/scripts/d1_export.py` prepends
`cloud/schema.sql` to your initial config and seed rows so one `wrangler d1 execute` command
creates all tables, triggers and starting data together.

If you ever want to apply the empty schema by itself first, you can run:

```sh
npx --prefix cloud wrangler d1 execute brandcal --remote --file cloud/schema.sql --config cloud/wrangler.local.jsonc
```

## 4. Create the KV namespace for daily backups

The Worker includes a daily cron (`30 0 * * *`, 00:30 UTC) that writes a full JSON snapshot of
the calendar to a KV namespace bound as `BACKUPS` under the key `snapshot/YYYY-MM-DD.json`, kept
for 35 days.

Create the namespace:

```sh
npx --prefix cloud wrangler kv namespace create BACKUPS
```

Copy the namespace `id` from the output. You will put it into your private Wrangler config in
step 5.

If you skip creating `BACKUPS` and omit `kv_namespaces` from your local config, the Worker still
runs (it skips the KV write when `env.BACKUPS` is absent), and D1 Time Travel still provides
7-day point-in-time recovery. Setting up `BACKUPS` is strongly recommended so you have 35 days of
plain JSON snapshots.

## 5. Create a private Wrangler config

Copy the committed template `cloud/wrangler.jsonc` to `cloud/wrangler.local.jsonc`:

```sh
cp cloud/wrangler.jsonc cloud/wrangler.local.jsonc
```

`cloud/.gitignore` already ignores `wrangler.*.jsonc` (while keeping `wrangler.jsonc` tracked),
so `cloud/wrangler.local.jsonc` will not be committed. Real ids, account-specific hostnames and
custom domains never belong in the committed `cloud/wrangler.jsonc`, which stays generic with
placeholders so forks and contributors never leak private infrastructure details.

Edit `cloud/wrangler.local.jsonc` and replace the three placeholders with your own values:

```jsonc
{
  "$schema": "node_modules/wrangler/config-schema.json",
  "name": "brandcal",
  "main": "src/index.ts",
  "compatibility_date": "2026-08-22",
  "workers_dev": false,
  "preview_urls": false,
  "routes": [{ "pattern": "brandcal.example.com", "custom_domain": true }],
  "assets": {
    "directory": "../src/brandcal/web_next",
    "binding": "ASSETS",
    "run_worker_first": true,
    "html_handling": "none",
    "not_found_handling": "none"
  },
  "d1_databases": [
    {
      "binding": "DB",
      "database_name": "brandcal",
      "database_id": "00000000-0000-0000-0000-000000000000"
    }
  ],
  "kv_namespaces": [
    {
      "binding": "BACKUPS",
      "id": "00000000-0000-0000-0000-000000000000"
    }
  ],
  "triggers": { "crons": ["30 0 * * *"] },
  "observability": { "logs": { "enabled": true, "invocation_logs": false } }
}
```

Keep `"workers_dev": false` and `"preview_urls": false` so the Worker is reachable only on your
Access-protected custom domain.

## 6. Set Worker secrets

The Worker reads one secret in production (defined in `cloud/src/index.ts`):

| Secret name | Purpose |
|---|---|
| `CSRF_SECRET` | Random secret key used to sign per-user HMAC-SHA256 CSRF tokens (`X-Brandcal-CSRF`) for browser writes. |

There are no other production secrets in Wrangler:

- `CERTS_URL` and `ENVIRONMENT` in `cloud/src/index.ts` are test-only hooks (honoured only when
  `ENVIRONMENT` is `"test"`). Do not set them in production.
- Cloudflare Access settings (`team_domain`, `audience`, `approvers`, `viewers`,
  `service_tokens`) are not secrets; they live in `config.json` and are stored in D1's `meta`
  table in step 9.

Generate a random 32-byte hex value and store it as `CSRF_SECRET` (you can run this after the
first deploy, or right before deploying):

```sh
python3 -c 'import secrets; print(secrets.token_hex(32))' | \
  npx --prefix cloud wrangler secret put CSRF_SECRET --config cloud/wrangler.local.jsonc
```

## 7. Deploy the Worker and attach the custom domain

Deploy from the repository root:

```sh
npx --prefix cloud wrangler deploy --config cloud/wrangler.local.jsonc
```

Because `routes` sets `"custom_domain": true`, Cloudflare automatically creates the DNS record
and TLS certificate for `brandcal.example.com`. Until you configure Cloudflare Access in step 8
and seed D1 in step 9, API requests return `401 IDENTITY_UNVERIFIED` or an error, which is
expected.

## 8. Configure Cloudflare Access

Cloudflare Access gates `brandcal.example.com`, and the Worker independently verifies every
`Cf-Access-Jwt-Assertion` JWT on every API call (RS256, team public keys, exact `aud`, `iss`,
`exp` and `nbf`).

### 8a. Create the Access application

In the Cloudflare Zero Trust dashboard:

1. Go to **Access > Applications > Add an application > Self-hosted**.
2. Set the application name (for example `brandcal`) and domain to `brandcal.example.com`.
3. Choose a session duration that suits daily use (for example **1 month** if you approve posts
   from your phone).
4. Save the application and copy its **Application Audience (AUD) Tag**. Note your team domain
   (`your-team.cloudflareaccess.com`) from **Settings > Custom Pages** or **Access** overview.

### 8b. Add a policy for the human owner (and any viewers)

Inside the `brandcal` application, add an **Allow** policy for people:

- **Action**: Allow
- **Include**: Emails: `you@example.com` (add any read-only viewers here too)
- **Authentication**: One-time PIN by email, a passkey, or an identity provider you already use
  in Zero Trust.

### 8c. Create a service token for bots and the CLI

1. Go to **Access > Service Auth > Service Tokens > Create Service Token**.
2. Name it after the assistant or machine using it (for example `brandcal-bot-1`) and choose a
   token duration.
3. Copy both values immediately (Cloudflare shows the secret only once):
   - **Client ID** (looks like `00000000-0000-0000-0000-000000000000.access`)
   - **Client Secret**
4. Back in the `brandcal` Access application, add a second policy:
   - **Action**: Service Auth
   - **Include**: Service Token: select `brandcal-bot-1`

The Client ID is not a secret and goes into `serve.service_tokens` in step 9. Keep the Client
Secret private (in your bot's secret store or a git-ignored `.env`).

## 9. Seed configuration and a first test post

Create a temporary local directory outside the repository to build the initial database and
configuration:

```sh
export BRANDCAL_HOME="$(mktemp -d)"
cp examples/config.serve.example.json "$BRANDCAL_HOME/config.json"
cp examples/platforms.json "$BRANDCAL_HOME/platforms.json"
```

Edit `$BRANDCAL_HOME/config.json`:

1. Set `"timezone"` to your IANA timezone (for example `"Europe/London"`). brandcal never
   guesses a timezone.
2. Adjust `"agents"` if you want different agent ids. Keep an approver agent (`"approver-1"`),
   `"system"` and `"console"` (role `"system"`).
3. In `"serve"`:
   - Set `"allowed_origins"` to `["https://brandcal.example.com"]`.
   - Set `"identity.team_domain"` to `"your-team.cloudflareaccess.com"` (bare host, no
     `https://` and no trailing slash).
   - Set `"identity.audience"` to your Access application's AUD tag.
   - Map your human email in `"approvers"`, for example `{"you@example.com": "approver-1"}`.
   - List any read-only emails in `"viewers"` (or leave `[]`).
   - Set `"console_approvals": true` **only if you want clicking Approve in the web UI to count
     as your binding human approval**. It defaults to `false`; while `false`, console approvals
     are refused.
   - Put your Access service-token Client ID in `"service_tokens"`.
4. Edit `$BRANDCAL_HOME/platforms.json` to match the channels and character limits you use.

Initialise the temporary database and add one test post (using obviously fake data first so you
can verify the whole flow):

```sh
brandcal init --as admin-1
brandcal add --as writer-1 < examples/posts/example-launch.json
brandcal audit
```

Export the local home (schema, rows and config) into a single SQL file and load it into your
empty remote D1 database:

```sh
python cloud/scripts/d1_export.py "$BRANDCAL_HOME" /tmp/brandcal-seed.sql \
  --service-token 00000000-0000-0000-0000-000000000000.access
npx --prefix cloud wrangler d1 execute brandcal --remote \
  --file /tmp/brandcal-seed.sql --config cloud/wrangler.local.jsonc
rm -f /tmp/brandcal-seed.sql
```

Notes:

- `d1_export.py` sets file mode `0600` on the SQL file, strips any `relay` block and `serve.port`,
  and writes `config.json` into `meta` (`k = 'config'`) with `gen = 1`.
- Passing `--service-token` replaces `serve.service_tokens` in the exported config (repeat the
  flag for multiple tokens). Omit `--service-token` if you already edited `serve.service_tokens`
  directly in `config.json`.
- Always delete `/tmp/brandcal-seed.sql` and your temporary `$BRANDCAL_HOME` once imported,
  because they hold your calendar data.

### Updating configuration later without wiping posts

To change `config.json` later (for example to add a viewer, flip `console_approvals` or rotate a
service token), update only the `config` row in `meta` and increment `gen` so any concurrent
sync detects the change. Keep the SQL in a temporary `0600` file, run it, and delete it:

```sh
python3 - <<'PY' > /tmp/update-cfg.sql
import json, pathlib
cfg = json.loads(pathlib.Path("/path/to/updated-config.json").read_text(encoding="utf-8"))
cfg.pop("relay", None)
cfg.get("serve", {}).pop("port", None)
escaped = json.dumps(cfg).replace("'", "''")
print(f"UPDATE meta SET v = '{escaped}' WHERE k = 'config';")
print("UPDATE meta SET v = CAST(CAST(v AS INTEGER) + 1 AS TEXT) WHERE k = 'gen';")
PY
chmod 600 /tmp/update-cfg.sql
npx --prefix cloud wrangler d1 execute brandcal --remote \
  --file /tmp/update-cfg.sql --config cloud/wrangler.local.jsonc
rm -f /tmp/update-cfg.sql
```

## 10. Connect the CLI in remote mode and verify

Unset `BRANDCAL_HOME` (so the CLI does not confuse local and remote modes) and export the remote
variables:

```sh
unset BRANDCAL_HOME
export BRANDCAL_REMOTE=https://brandcal.example.com
export BRANDCAL_ACCESS_CLIENT_ID=00000000-0000-0000-0000-000000000000.access
export BRANDCAL_ACCESS_CLIENT_SECRET=replace-with-your-access-client-secret
```

Run one read command and one small write command:

```sh
brandcal list
brandcal note p0001 "Remote smoke check" --as manager-1
brandcal audit
```

Both commands should return one line of JSON with `"ok": true`.

Next, open `https://brandcal.example.com` in a browser, sign in through Cloudflare Access as
`you@example.com`, and confirm your test post appears on the calendar with the note you just
added.

For connecting AI assistants (Grok Bot, Claude Code, Cursor or other agents) to this deployment,
see [docs/BOT_INTEGRATION.md](BOT_INTEGRATION.md).

## 11. Backups, restore, upgrades and token rotation

### Backups

Three layers protect your data:

1. **D1 Time Travel**: automatic 7-day point-in-time recovery on Cloudflare's free plan.
2. **Daily KV snapshots**: the Worker's `30 0 * * *` cron writes `snapshot/YYYY-MM-DD.json` to
   the `BACKUPS` KV namespace and retains each snapshot for 35 days.
3. **Off-Cloudflare local copy**: pull a read-only SQLite copy from any machine with the service
   token:

   ```sh
   brandcal pull --out /path/to/backups/brand-2026-03-02.db
   ```

List or fetch a KV snapshot with Wrangler:

```sh
npx --prefix cloud wrangler kv key list --binding BACKUPS --config cloud/wrangler.local.jsonc
npx --prefix cloud wrangler kv key get snapshot/2026-03-02.json \
  --binding BACKUPS --config cloud/wrangler.local.jsonc > /tmp/snapshot.json
```

### Restore

- **Within 7 days (fastest)**: use D1 Time Travel to restore the database in place:

  ```sh
  npx --prefix cloud wrangler d1 time-travel info brandcal \
    --timestamp 2026-03-02T09:00:00Z --config cloud/wrangler.local.jsonc
  npx --prefix cloud wrangler d1 time-travel restore brandcal \
    --timestamp 2026-03-02T09:00:00Z --config cloud/wrangler.local.jsonc
  ```

- **Older than 7 days (from a KV snapshot)**: rebuild a local home from the JSON snapshot using
  `brandcal.remote.build_home`, verify it with `brandcal audit`, then export it into a fresh D1
  database with `cloud/scripts/d1_export.py` and point `cloud/wrangler.local.jsonc` at the new
  database id:

  ```sh
  python3 - <<'PY'
  import json, pathlib
  from brandcal.remote import build_home
  snap = json.loads(pathlib.Path("/tmp/snapshot.json").read_text(encoding="utf-8"))
  out = pathlib.Path("/tmp/restored-home")
  out.mkdir(parents=True, exist_ok=True)
  build_home(snap, out)
  PY
  BRANDCAL_HOME=/tmp/restored-home brandcal audit
  ```

### Upgrading to a new release

```sh
git fetch --tags
git checkout v0.2.0
npm --prefix cloud ci
npx --prefix cloud wrangler deploy --config cloud/wrangler.local.jsonc
```

Check `CHANGELOG.md` before upgrading to see whether the release changes `cloud/schema.sql`. If
you also upgrade the Python CLI used by bots, install the matching tag (see
[docs/BOT_INTEGRATION.md](BOT_INTEGRATION.md)).

### Rotating a service token

Zero-downtime rotation:

1. Create a new service token in Cloudflare Zero Trust and add it to the `brandcal` Access
   application's Service Auth policy.
2. Add the new Client ID to `serve.service_tokens` in `meta.config` (keeping the old Client ID
   for now) using the config update snippet in step 9.
3. Update `BRANDCAL_ACCESS_CLIENT_ID` and `BRANDCAL_ACCESS_CLIENT_SECRET` on your bot or machine
   and verify `brandcal list` succeeds.
4. Remove the old Client ID from `serve.service_tokens` in `meta.config`.
5. Revoke and delete the old service token in Cloudflare Zero Trust.

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `401 IDENTITY_UNVERIFIED` ("No Access token came with this request") | Request bypassed Access, or the Access application does not cover `brandcal.example.com`. | Confirm the Access application hostname matches your custom domain and `"workers_dev": false` is set. |
| `401 IDENTITY_UNVERIFIED` ("different application" or "different team") | `serve.identity.audience` or `serve.identity.team_domain` in `meta.config` does not match Access. | Copy the exact AUD tag and bare team domain (`your-team.cloudflareaccess.com`, no `https://`) into `meta.config`. |
| `401 IDENTITY_UNVERIFIED` ("The token carries no email") on CLI | Service token Client ID is missing from `serve.service_tokens`. | Add the Client ID (`...access`) to `serve.service_tokens` in `meta.config`. |
| CLI prints `The remote calendar sent a non-JSON answer (HTTP 302)` or `HTTP 403` | Cloudflare Access redirected the CLI to the human login page instead of letting the service token through. | Add a **Service Auth** (not Allow) policy for the service token on the Access application, and double-check both `BRANDCAL_ACCESS_CLIENT_ID` and `BRANDCAL_ACCESS_CLIENT_SECRET`. |
| `403 IDENTITY_UNMAPPED` in browser | Access verified your email, but it is not listed in `serve.approvers` or `serve.viewers`. | Add `you@example.com` to `serve.approvers` (mapped to `"approver-1"`) or `serve.viewers` in `meta.config`. |
| `403 ROLE_NOT_ALLOWED` on browser Approve | Either you are listed as a viewer (not an approver), or `serve.console_approvals` is `false`. | Check `serve.approvers` and set `"console_approvals": true` if you intend console clicks to count as approvals. |
| `403 ROLE_NOT_ALLOWED` ("Sync is for the agents' service token only" / "Service tokens may only use /api/sync") | A human browser hit `/api/sync/*`, or a service token hit a console API route. | Keep browsers on `/` and `/api/posts`, and keep bots on the CLI (which uses `/api/sync/*`). |
| `403 BAD_ORIGIN` or CSRF error on browser write | `serve.allowed_origins` does not match `https://brandcal.example.com`, or `CSRF_SECRET` was changed or not set. | Verify `serve.allowed_origins`, set `CSRF_SECRET` via `wrangler secret put`, then reload the page so the browser fetches a fresh `/api/session`. |
| `409 CONFLICT` | Another write landed while the CLI or browser was preparing its change. | The CLI and Worker retry up to three times automatically; if it still fails, rerun the command. |
| `409 STALE_APPROVAL` | The post's content or window changed after you loaded it. | Reload the post, review the new version and hash, and decide again. |
| `500 INTERNAL` or D1 `no such table: meta` | D1 database was created but never seeded, or `database_id` in `cloud/wrangler.local.jsonc` points at an empty database. | Run step 9 (`d1_export.py` and `wrangler d1 execute --remote`) against the right database id. |
| `BAD_ARGS` ("cannot be used in remote mode") | Command operates on local files (`init`, `migrate`, `backup`, `export`, `archive`, `serve`, `relay`, `media`, `render`) or `--home` was passed with `BRANDCAL_REMOTE` set. | Run local-only commands without `BRANDCAL_REMOTE`, or use `brandcal pull --out FILE` for a local read-only copy. |

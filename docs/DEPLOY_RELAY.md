# Deploying the web UI through the Cloudflare Worker relay

This is the generic recipe for running `brandcal serve` behind a Cloudflare Worker relay instead
of a Cloudflare Tunnel. Every host, email and id below is a placeholder: `brandcal.example.com`
is the browser host, `brandcal-relay.example.com` the connector host,
`example.cloudflareaccess.com` your Zero Trust team domain, `AUD_TAG` the Access application's
AUD tag and `<store-id>` the private secret store. Never commit the real values; keep them in
`BRANDCAL_HOME/config.json` and in a private wrangler config outside the repository.

The connector itself (`brandcal relay`, its config block, exit codes and log format) is described
in [RELAY_CONNECTOR.md](RELAY_CONNECTOR.md). The tunnel recipe it replaces is
[DEPLOY_UI.md](DEPLOY_UI.md); the brandcal side of Access (`serve` block, approvers, the JWT
check) is the same, so read that first.

## 1. What the relay is and why

`cloudflared` needs outbound port 7844 for both its QUIC and HTTP/2 transports. Where only
outbound 443 is open, a tunnel cannot connect. The relay replaces the tunnel with a Worker and
one Durable Object:

```
browser ──https──▶ Access (browser host) ──▶ Worker ──▶ Durable Object "relay"
                                                              ▲
                     Access service token (connector host)    ║ one WebSocket over 443, outbound
                                                              ║
                                          brandcal relay ─────╝ ──http──▶ 127.0.0.1:8787 brandcal serve
```

- `brandcal relay` dials out and keeps one WebSocket open. The Worker sends each browser request
  down it; the connector replays it against `brandcal serve` on `127.0.0.1` and streams the
  answer back.
- Cloudflare Access stays in front of the browser host. The Worker only checks that a
  `Cf-Access-Jwt-Assertion` header is present and shaped like a JWT; **`brandcal serve` verifies
  it**, exactly as behind the tunnel. That check is the one that counts: brandcal accepts a token
  only if its `aud` is exactly the browser app's AUD tag and it carries an email, so a token for
  the connector's own Access app, or a service-token JWT, is refused with `IDENTITY_UNVERIFIED`.
- Only allow-listed headers cross in either direction (RELAY_CONNECTOR.md, "What crosses").
  Cookies, `Authorization`, `Cf-Access-Authenticated-User-Email` and client addresses never reach
  brandcal.
- Everything fits the Workers Free plan and the Zero Trust Free plan for one or two users.
- Every Worker deploy disconnects the socket. The connector reconnects within seconds; requests in
  flight fail cleanly (a dropped write says so, and is never retried).

## 2. Hosts and Access applications

| Host | Used by | Access | The Worker accepts |
|---|---|---|---|
| `brandcal.example.com` | browsers | the existing app from DEPLOY_UI.md (OTP, approvers only) | GET and POST, except `/_relay/*`; `/_relay/health` is answered by the Worker |
| `brandcal-relay.example.com` | the connector only | a **new** app with one *Service Auth* policy for one service token | only `GET /_relay/connect` with `Upgrade: websocket`; anything else is 404 |

- The connector cannot do an OTP sign-in, and an exemption on the browser host would weaken it,
  so it gets its own host. The Worker routes by host (`PUBLIC_HOST`, `RELAY_HOST`), so a request
  never crosses between the two roles.
- The connector is authenticated twice: Access checks the service token at the edge, then the
  Durable Object sends a 32-byte nonce and expects
  `HMAC-SHA256(RELAY_SECRET, nonce || "brandcal-relay.v1")` within 10 s. The secret never crosses
  the wire. A wrong answer closes the socket with 4003 and the connector exits 4.
- `workers_dev` and `preview_urls` are `false`, so no `*.workers.dev` or preview URL reaches the
  Worker around Access.
- In Cloudflare, check that Rocket Loader, Email Obfuscation and other HTML-rewriting features are
  off for the browser host: they break brandcal's hash-based CSP.

## 3. Secrets and where they live

| Secret | Where | Read by |
|---|---|---|
| `RELAY_SECRET` (32 random bytes, `python -c "import secrets; print(secrets.token_urlsafe(32))"`) | Worker secret `RELAY_SECRET`; on the box `/cursor/stores/<store-id>/secrets/brandcal_relay_secret` | Worker; connector at start-up |
| Access service token (`{"client_id": "...", "client_secret": "..."}`) | `/cursor/stores/<store-id>/secrets/brandcal_relay_access.json` | connector at start-up |
| Cloudflare API token (section 5) | `/cursor/stores/<store-id>/secrets/cloudflare_api_token`, only between issue and revocation | `wrangler`, for one deploy |

- Generate the relay secret into a file and pipe it into `wrangler secret put`; never type it on
  a command line, echo it or log it.
- The connector reads both of its files once at start-up and keeps them in memory. A missing or
  unreadable file stops it with `SECRET_UNAVAILABLE` (exit 2), naming the path only.
- **Isolation caveat.** Keep secrets out of the repository and out of shared work trees, but do
  not assume a per-agent store isolates them. A store that is a shared mount (for example a FUSE
  mount with `allow_other`, files that cannot be `chmod`-ed, synced to a remote backend) is no more
  private than any other file readable by the same user on the host. The owner must accept that
  risk explicitly before cutover. Mitigations: the API token exists for one deploy only, the
  service token is scoped to one Access app, `RELAY_SECRET` lets a holder pose as the connector but
  not sign in as an approver, and all three can be rotated in minutes.

## 4. The `relay` config block and the private wrangler config

brandcal side, in `BRANDCAL_HOME/config.json` next to `serve`:

```json
"relay": {
  "url": "wss://brandcal-relay.example.com/_relay/connect",
  "public_host": "brandcal.example.com",
  "secret_file": "/cursor/stores/<store-id>/secrets/brandcal_relay_secret",
  "access_token_file": "/cursor/stores/<store-id>/secrets/brandcal_relay_access.json",
  "max_response_mb": 32
}
```

`public_host` must be the host of one of `serve.allowed_origins`. Set `timezone` (or
`BRANDCAL_TZ`) as usual: log lines carry that offset, for example `+03:00`.

Worker side: `relay/wrangler.jsonc` in the repository holds placeholders only and no
`account_id`. Keep the real one **outside** the repository, with `main` pointing at the work
tree's `relay/src/index.ts`:

```jsonc
{
  "name": "brandcal-relay",
  "main": "/path/to/brandcal/relay/src/index.ts",
  "compatibility_date": "2026-08-22",
  "workers_dev": false,
  "preview_urls": false,
  "routes": [
    { "pattern": "brandcal.example.com", "custom_domain": true },
    { "pattern": "brandcal-relay.example.com", "custom_domain": true }
  ],
  "durable_objects": { "bindings": [{ "name": "RELAY", "class_name": "Relay" }] },
  "migrations": [{ "tag": "v1", "new_sqlite_classes": ["Relay"] }],
  "vars": {
    "PUBLIC_HOST": "brandcal.example.com",
    "RELAY_HOST": "brandcal-relay.example.com",
    "DISPLAY_UTC_OFFSET": "+03:00"
  },
  "observability": { "logs": { "enabled": true, "invocation_logs": false } }
}
```

- `DISPLAY_UTC_OFFSET` has no default in the repository. Missing or malformed, every request gets
  500 `RELAY_MISCONFIGURED` (the Worker fails closed).
- Keep `invocation_logs` off: invocation logs record request headers, which would include the
  JWT. Only the Worker's own one-line-per-request logs are kept, and they never hold header
  values, bodies, tokens, secrets, emails or client addresses.
- The account id comes from `CLOUDFLARE_ACCOUNT_ID` in the deploy command's environment, never
  from a committed file.

Run `brandcal serve` and `brandcal relay` side by side under one small restart loop outside the
repository. It must **not** restart the connector after exit 2 (config or secrets), 4
(credentials refused) or 8 (replaced by a newer connector).

## 5. Every deploy needs a fresh Cloudflare API token

No long-lived Cloudflare token is kept. Every Worker deploy, redeploy or `wrangler secret put`
uses a new, scoped token, issued by the owner for that one job.

**Create it:** Cloudflare dashboard, My Profile, API Tokens, Create Token, Custom token.

- Routine redeploy:
  - Account, Workers Scripts: Edit
  - Zone, Workers Routes: Edit, restricted to the brandcal zone only
- Cutover only, in addition:
  - Zone, DNS: Edit (same zone)
  - Account, Access: Apps and Policies: Edit
  - Account, Access: Service Tokens: Edit
- TTL ending within 24 hours. Optionally restrict it to the host's egress IP.
- Nothing beyond these permissions.

**Store it** in `/cursor/stores/<store-id>/secrets/cloudflare_api_token`.

**Use it** only as `CLOUDFLARE_API_TOKEN` in the environment of the one deploy command, read from
the file at that moment, never echoed, logged or put on a command line:

```sh
CLOUDFLARE_API_TOKEN="$(cat /cursor/stores/<store-id>/secrets/cloudflare_api_token)" \
CLOUDFLARE_ACCOUNT_ID="<account-id>" \
  npx --prefix relay wrangler deploy --config /path/outside/the/repo/wrangler.jsonc
```

**Revoke it** after the deploy is verified: the owner (or a session given that right) revokes the
token in the dashboard and deletes the file. The run log records only "token used, revoked at
<time with offset>".

## 6. Cutover and rollback

Nothing here runs automatically; each step needs the owner's go-ahead.

1. Pre-checks: `brandcal serve` runs from the intended home (demo data until a separate decision
   allows real data behind the GUI); the relay tests and a local `wrangler dev` run pass.
2. Zero Trust: create the service token (one year, expiry alert on) and save it to the store;
   create the connector Access app for `brandcal-relay.example.com` with one Service Auth policy
   for that token. Leave the browser app untouched.
3. Generate `RELAY_SECRET` into the store.
4. Deploy with only the connector custom domain, then
   `npx --prefix relay wrangler secret put RELAY_SECRET --config ... < <secret file>`, and start
   `brandcal relay`.
5. Check: the connector host without the token gets 401 or 403 from Access, and the connector
   logs `connected ready`.
6. Outage window: a custom domain cannot be created over an existing CNAME. Record the browser
   host's tunnel CNAME, delete it, and redeploy with both custom domains. The connector
   reconnects within seconds.
7. Live checks: signed out, the browser host redirects to the team login; signed in,
   `/api/session` shows the approver with source `access-jwt`; `/_relay/health` shows
   `connected:true`; stopping `brandcal relay` shows the offline page; stopping `brandcal serve`
   shows 502 "brandcal serve is not running"; Workers Logs hold no JWT or email.
8. Leave the old tunnel dormant. Revoke the API token and delete its file (section 5).

**Rollback:** remove the browser host's custom domain and recreate the recorded CNAME. If the
tunnel could never connect from this host, that means "site closed, data safe". Removing the
custom domain alone is the emergency stop. The Access apps stay either way.

## 7. The `RELAY_*` error codes

These belong to the Worker, not the CLI (CLI codes are in [ERRORS.md](ERRORS.md)). Pages get a
self-contained HTML page; `/api/*` gets brandcal's error shape
`{"ok":false,"error":{"code":"...","message":"...","next":"..."}}` with no `X-Brandcal-Exit`.

| HTTP | Code | Meaning |
|---|---|---|
| 400 | `RELAY_BAD_REQUEST` | A WebSocket upgrade on the browser host |
| 401 | `RELAY_UNAUTHENTICATED` | No `Cf-Access-Jwt-Assertion`, more than one, or not shaped like a JWT |
| 404 | `RELAY_NOT_FOUND` | Unknown host, a reserved `/_relay/` path, or anything but the connect path on the connector host |
| 405 | `RELAY_METHOD_NOT_ALLOWED` | A method other than GET or POST (`Allow: GET, POST`) |
| 413 | `RELAY_REQUEST_TOO_LARGE` | A request body over 1 MiB (or one that would not fit a 1 MiB frame) |
| 500 | `RELAY_MISCONFIGURED` | `DISPLAY_UTC_OFFSET` is missing or malformed |
| 502 | `RELAY_UPSTREAM_DOWN` | `brandcal serve is not running` (the connector could not reach it within 2 s) |
| 502 | `RELAY_TOO_LARGE` | The response passed the 32 MiB cap before its head was sent (after that, the stream is aborted) |
| 502 | `RELAY_BAD_FRAME` | The connector refused the request (for example a wrong Host) or sent a malformed frame |
| 502 | `RELAY_DROPPED` | The socket dropped mid-request. For a POST: "Your change may or may not have been saved: reload to check before trying again." |
| 503 | `RELAY_OFFLINE` | No connector, or its last pong is older than 90 s (`Retry-After: 30`) |
| 503 | `RELAY_BUSY` | 16 requests already in flight |
| 504 | `RELAY_TIMEOUT` | No response head within 30 s, a 30 s gap between chunks, or brandcal took longer than 25 s |

`GET /_relay/health` (behind Access) returns
`{"ok":true,"connected":true,"connected_since":"2026-10-24T09:15:02+03:00","last_pong_age_s":12,"agent":"brandcal-relay/x.y","in_flight":0}`,
or 503 with `connected:false` when the connector is away.

## 8. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Every request 500 `RELAY_MISCONFIGURED` | `DISPLAY_UTC_OFFSET` missing from the private config, or not `±HH:MM` |
| Connector exits 4 at once | Access refused the service token (401/403), or `RELAY_SECRET` differs between the Worker and the file (close 4003). Re-put the secret or fix the token file |
| Connector exits 8 | Another `brandcal relay` took over. Run only one; the restart loop must not restart after 8 |
| Connector exits 2 with `SECRET_UNAVAILABLE` | The store is not mounted or the path in `relay` is wrong |
| Offline page although the connector logs `connected ready` | The connector reached a different Worker or host; check `relay.url` and `RELAY_HOST` |
| 502 "brandcal serve is not running" | `brandcal serve` is down, or `serve.port` differs from where it listens |
| 401 `IDENTITY_UNVERIFIED` from brandcal behind a signed-in session | `serve.identity.audience` is not exactly the browser app's AUD tag (see DEPLOY_UI.md) |
| 403 `BAD_ORIGIN` on writes | `serve.allowed_origins` and `relay.public_host` do not name the browser host |
| Pages load without styles or scripts | An HTML-rewriting zone feature (Rocket Loader, Email Obfuscation) is on for the host |
| A deploy and then brief 503s | Expected: a deploy closes the socket; the connector reconnects within its backoff |

## Local test with `wrangler dev`

With fake secrets only, on demo data:

```sh
# a fake secret in a scratch file, and .dev.vars next to a local wrangler config:
#   RELAY_SECRET=<the same fake value>
#   vars: PUBLIC_HOST=brandcal.example.com, RELAY_HOST=127.0.0.1:8788, DISPLAY_UTC_OFFSET=+03:00
BRANDCAL_HOME=/tmp/demo brandcal serve --as admin-1 --dev-unverified
npx --prefix relay wrangler dev --config /tmp/wrangler.dev.jsonc --ip 127.0.0.1 --port 8788 --local
BRANDCAL_HOME=/tmp/demo brandcal relay --as admin-1 --local-dev   # relay.url ws://127.0.0.1:8788/_relay/connect
curl -H 'Host: brandcal.example.com' -H 'Cf-Access-Jwt-Assertion: e30.e30.e30' http://127.0.0.1:8788/
```

`--local-dev` allows `ws://127.0.0.1:PORT` and makes the access token file optional; `wrangler
dev` has no Access in front of it.

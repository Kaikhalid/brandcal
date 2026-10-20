# brandcal web UI specification (v0.2)

Status: proposal for owner review. Companion to [SPEC.md](SPEC.md); where this document
changes a SPEC rule it says so (section 3.5). Nothing here is implemented yet. All names,
addresses and hosts below are fake (`Example Co`, `example.com`, `approver@example.com`,
`brandcal.example.com`).

---

## 1. Paradigm

### 1.1 Principles

brandcal is a tool for agents that a human can also use. The UI is a second front end to the
same core, like the CLI.

- **No logic of its own.** Every UI action calls the same core function as a CLI command.
  The browser never decides whether something is allowed; the server returns what the core
  returned.
- **Every action shows its CLI equivalent.** Each button has a "copy command" line, for
  example `brandcal approve p0001 --version 3 --hash 3b9e21d0 --channel console ...`.
- **Every refusal is the CLI's refusal.** The UI shows the error `code`, the `message` in
  plain words and the `next` instruction verbatim (SPEC 8.2, [ERRORS.md](ERRORS.md)). The UI
  adds no text of its own to an error.
- **Nothing hard-coded.** Platforms, limits, post types, statuses, transitions, timezone and
  roles come from the database and config (1.4). A new platform in `platforms.json` appears
  in the UI after `brandcal init`, with no UI release.
- **No honour system for decisions.** Every write needs a verified identity (2.3). Dev mode
  (2.5) is the only exception and can never decide.
- **No ambiguity about the next step.** Which buttons appear in which state is derived from
  the transition table (1.5), by the server, in one place.

### 1.2 Action map

"New" means the command or function does not exist yet and is built in U1. Existing CLI
handlers are moved into a shared action layer, `brandcal/actions.py` (to be confirmed in U1
after reading `cli.py`), and the CLI calls it too, so both front ends share one code path.

| UI action | CLI command | Core function | Roles (UI) | New? |
|---|---|---|---|---|
| Load rules | `brandcal schema` | `actions.schema` | any viewer | extended |
| Week / month / list | `brandcal list --from D --to D` | `actions.list_posts` | any viewer | no |
| "Needs you" strip | `brandcal list --status S` (three calls) | `actions.list_posts` | any viewer | no |
| Open a post | `brandcal show ID --log` | `actions.show` | any viewer | no |
| Check a post | `brandcal check ID` | `actions.check` | any viewer | no |
| Audit trail / what changed | `brandcal events [--since ID] [--post ID]` | `actions.events` | any viewer | **yes** |
| Today / tomorrow | `brandcal today` / `tomorrow` | `actions.today` | any viewer | no |
| Integrity badge | `brandcal audit` | `actions.audit` | any viewer | no |
| Archive month view | `brandcal archive list/show --month M` | `actions.archive_*` | any viewer | no |
| Approve | `brandcal approve ID ... --channel console` | `actions.approve` | approver | channel new |
| Request changes | `brandcal request-changes ID ... --what --where --instruction` | `actions.request_changes` | approver | flags new |
| Change time only | `brandcal reschedule ID --window W ...` | `actions.reschedule` | approver | channel new |
| Cancel | `brandcal cancel ID --kind K --reason R` | `actions.cancel` | approver | channel new |
| Edit text | `brandcal edit ID field=value ...` | `actions.edit` | approver (UI only); writer, manager (CLI only) | actor rule new |
| Submit after requested changes | `brandcal submit ID` | `actions.submit` | approver (UI only); writer, manager (CLI only) | actor rule new |
| Add a note | `brandcal note ID "..."` | `actions.note` | approver (UI only); writer, manager (CLI only) | actor rule new |
| Serve the UI | `brandcal serve` | `serve.main` | admin | **yes** |

Not in the UI: `begin`, `published`, `failed`, `schedule`, `unschedule`, `add`, media upload,
`sweep`, backup, export, archive run, migrate. Those stay with agents and the admin. The UI
shows their results (live URL, claim, native schedule) read-only.

**Which surface each role uses (decision 8).** One surface per role, so there is never a
choice to make:

| Role | Surface | Writes |
|---|---|---|
| approver (a human) | UI only, with a verified Access identity | approve, request changes, change time, cancel, edit, submit, note |
| viewer (a human) | UI only, with a verified Access identity | none (read-only) |
| writer, manager, admin, system (agents) | CLI only, `--as NAME` | as SPEC 6.1 and 8.1; the UI never acts for them |

The CLI keeps refusing the approver role on every command (`ROLE_NOT_ALLOWED`). The UI
never accepts `--as`-style names; dev mode (2.5) is read-only. The asymmetry is deliberate:
the human edits in the UI, agents edit through the CLI, and both reach the same
`actions.edit`, the same version rules and the same events.

### 1.3 Refusals

Every non-2xx response has the CLI's error body (`{"ok":false,"error":{"code","message","next"}}`).
The UI renders it in a fixed panel: code in monospace, message, then "What to do:" and `next`.
It never reduces a refusal to "something went wrong". HTTP status follows the exit code
(2 and 3: 400 and 422, 4: 403, or 401 for `IDENTITY_UNVERIFIED`, 5, 6 and 8: 409, 7: 404). The
exact exit code is in the `X-Brandcal-Exit` header.

### 1.4 Where rules come from

| Needed by the UI | Served by | Source |
|---|---|---|
| States, transitions, roles per transition | `GET /api/schema` | `transitions` table |
| Platforms and character limits | `GET /api/schema` | `platforms` table, from `platforms.json` |
| Post types | `GET /api/schema` | the `post_type` list in the database schema |
| Timezone, claim minutes, campaigns, pillars | `GET /api/schema` | `config.json` |
| Who I am, my role, allowed actions | `GET /api/session` | verified identity (2.3) |
| Per-post allowed actions and disabled reasons | `GET /api/posts/ID` (`actions`) | transitions plus post fields (1.5) |

Icons and colours are the only presentation data the UI ships, keyed by id, with a fallback
for any id it does not know (5.2).

### 1.5 Buttons by state

The server builds `actions` for each post from the transition table, the viewer's role and
the post's fields (claim, native schedule, hold). The client renders exactly that list. A
button that is not allowed is shown **disabled with the refusal it would produce** (code and
`next`), never silently hidden, except where no transition exists at all.

| State | Buttons shown | Notes |
|---|---|---|
| `pending_approval` | Approve, Request changes, Edit, Cancel | Approve refused with `ON_HOLD` while a hold is set |
| `changes_requested` | Edit, Submit for approval, Cancel | Submit is enabled once the content has changed since the request |
| `approved` | Change time, Edit, Cancel | Edit and Cancel disabled with `EDIT_WHILE_SCHEDULED`, `NATIVELY_SCHEDULED`, `EDIT_WHILE_CLAIMED` or `CLAIMED` when the fields say so; Edit warns it returns the post to approval |
| `missed` | Approve new time, Edit, Cancel | "Approve new time" is the time-only `reschedule` |
| `published`, `cancelled` | none | closed; read-only (`POST_CLOSED`) |

---

## 2. Architecture

### 2.1 Server

`brandcal serve` (new command, admin) starts a stdlib `http.server` (threaded) that:

- binds to **127.0.0.1 only**; there is no option to bind elsewhere;
- serves a JSON API under `/api/` and static files shipped inside the package: `/` is the
  Next.js static export committed in `src/brandcal/web_next/`, and the first vanilla-JS views
  (CSS, an SVG sprite) stay at `/mvp/` under `brandcal/web/`;
- needs **no npm and no new runtime dependency** at run time: Node builds the export, and only
  maintainers run that build (`python scripts/build_ui.py`), so pip users never need Node;
- opens the database per request, using the same action layer as the CLI, so triggers, hash
  chains and the audit apply unchanged;
- refuses to start without `BRANDCAL_HOME`, a configured timezone and a `serve` config block
  (2.6), with the usual exit 2 codes.

Intended exposure is a Cloudflare Tunnel (`cloudflared`) to `127.0.0.1:PORT`, protected by
Cloudflare Access. brandcal is never directly reachable from the internet.

### 2.2 Endpoints

All responses are JSON in the CLI shape; every request is authenticated (2.3).

| Method and path | Action |
|---|---|
| `GET /api/session` | identity, role, source (`access-jwt` or `dev-unverified`), CSRF token |
| `GET /api/schema` | rules and config for the UI (1.4) |
| `GET /api/posts?from=&to=&status=&platform=&closed=` | list |
| `GET /api/posts/ID` | post, parts, media, approvals, `actions` |
| `GET /api/events?since=&post=&limit=` | audit events |
| `GET /api/media/ID/N` | media file (checked path, no traversal, content type from the media record) |
| `POST /api/posts/ID/approve` / `request-changes` / `reschedule` / `cancel` / `edit` / `submit` / `note` | write actions |

Write bodies are JSON and always carry `version`, `hash` and `window` as the UI saw them (3.3).
Extra fields: `request-changes` `what`, `where`, `instruction`; `reschedule` `new_window` (its
`window` is the one the UI saw); `cancel` `kind`, `reason`; `edit` `fields` (an object of text
values); `note` `text`. The server supplies the button id and label recorded with a decision (for
example `console-approve`, "Approve"). `STALE_APPROVAL` responses carry `current`, the post as
`GET /api/posts/ID` would return it. Unknown methods (including `OPTIONS`) get 405 with
`Allow: GET, POST`. The CSRF token is the HMAC of the identity under a per-process secret, so it
changes when the server restarts. Every JSON response carries `X-Brandcal-Exit`. Config is read
once at start; restart to apply changes.

### 2.3 Identity

Reads and writes both need a verified identity. There is one way to get it (decision 5):

- **Access JWT.** Read `Cf-Access-Jwt-Assertion`. Check the signature
   against the team's JWKS (`https://TEAM_DOMAIN/cdn-cgi/access/certs`, cached, refreshed on
   an unknown `kid`), then `aud` equals the configured audience, `iss` equals
   `https://TEAM_DOMAIN`, `exp` and `nbf` hold (60 s leeway), `alg` is `RS256` only (never
   `none` or `HS256`). The identity is the `email` claim. No other header, cookie or proxy mode is accepted.

The email is then looked up in `serve.approvers` (email to approver agent id) or
`serve.viewers` (read-only). An email in neither list: `IDENTITY_UNMAPPED`. No header or a
bad token: `IDENTITY_UNVERIFIED`. Nothing is inferred from the request body, cookies or
client-supplied names.

**Proposed new codes** (U1 adds them to `errors.py` and regenerates ERRORS.md):

| Exit | Code | Meaning |
|---|---|---|
| 4 | `IDENTITY_UNVERIFIED` | No valid verified identity on this request (no or bad token, or any write in dev mode). `next`: sign in through Cloudflare Access, or ask the admin to check `serve.identity`. |
| 4 | `IDENTITY_UNMAPPED` | The identity is verified but not listed as an approver or viewer. `next`: ask the admin to add it to `serve.approvers`. |
| 4 | `BAD_ORIGIN` | A write came from an origin or host that is not allowed (2.7). |
| 3 | `REASON_REQUIRED` | Request changes needs `what`, `where` and `instruction` (4.2). |
| 2 | `EXTRA_NOT_INSTALLED` | An optional extra this feature needs (2.4) is not installed. Raised by `serve` (U1b). |

### 2.4 JWT signature check

RS256 verification uses the optional `cryptography` extra, which SPEC 7.5 already names
(decision 1). There is no stdlib RS256 fallback. Without the extra, `serve` refuses to start
in verified mode with `EXTRA_NOT_INSTALLED` (exit 2) and an explained message: "Access JWT
verification needs the cryptography extra; install the crypto extra, or use --dev-unverified
for a local, read-only session". U1 adds the optional extra
`crypto = ["cryptography"]` to `pyproject.toml` (T15 reuses it). No required dependency is added. `--dev-unverified` needs no
extra.

### 2.5 Local dev mode

`brandcal serve --dev-unverified` skips identity checks for **reads only**. It is for local
development of the views.

- Printed warning at start; a permanent red "UNVERIFIED (dev)" banner in every view.
- `GET /api/session` reports source `dev-unverified`.
- Every event and edit it causes records `"identity_source":"dev-unverified"`.
- Every write (approve, request changes, change time, cancel, edit, submit, note) returns
  `IDENTITY_UNVERIFIED`. A human decision with no verified human is the exact failure this
  tool exists to prevent, and agents write through the CLI (1.2), so there is no exception.
  Write paths are tested with locally signed test JWTs instead.
- It requires the flag every time; no config key enables it.

### 2.6 Config keys

New `serve` block in `config.json` (no machine-dependent defaults, SPEC 13; `--port` may
override `serve.port`):

| Key | Meaning |
|---|---|
| `serve.port` | Port on 127.0.0.1; required |
| `serve.allowed_origins` | List of exact origins, for example `["https://brandcal.example.com"]`; required for writes |
| `serve.identity.team_domain` | For example `example.cloudflareaccess.com` |
| `serve.identity.audience` | The Access application AUD tag |
| `serve.identity.jwks_cache_minutes` | JWKS cache lifetime |
| `serve.approvers` | `{"approver@example.com": "approver-1"}`; the agent must have role `approver` |
| `serve.viewers` | List of emails with read-only access |
| `serve.console_agent` | Id of the recorder agent for console decisions (role `system`, seeded by `init`) |

### 2.7 HTTP hardening

- JSON only: writes need `Content-Type: application/json`; other types get `BAD_ARGS`.
- **No CORS**: the server never sends `Access-Control-*` headers.
- Writes need an `Origin` header exactly in `serve.allowed_origins`, and a `Host` header from
  the same set (guards against DNS rebinding). Otherwise `BAD_ORIGIN`.
- A CSRF token from `GET /api/session`, bound to the identity and sent as `X-Brandcal-CSRF`;
  a missing or wrong token is `BAD_ORIGIN`.
- `Content-Security-Policy: default-src 'self'`; inline scripts and styles are allowed only by
  the per-page `sha256` hashes the build writes to `csp.json` (`script-src 'self' 'sha256-...'`),
  never `'unsafe-inline'` or `'unsafe-eval'`; the MVP at `/mvp/` has no inline script at all.
  Also `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and
  `Cache-Control: no-store` on API responses.
- All user text is inserted with `textContent`, never as HTML.
- Request body limit 256 KiB; no directory listing; static files from an allow-list.

### 2.8 Tunnel and Access setup (generic)

1. Run `brandcal serve` as a service under a dedicated user, with `BRANDCAL_HOME` set.
2. Create a Cloudflare Tunnel with an ingress rule from `brandcal.example.com` to
   `http://127.0.0.1:PORT`.
3. Create an Access application for `brandcal.example.com`; policy: allow only the approver
   and viewer emails, require your identity provider's MFA, and set the session duration to
   24 hours for approvers (decision 6; a Cloudflare setting, not brandcal's). Copy the AUD tag and the team
   domain into `serve.identity`.
4. Add `https://brandcal.example.com` to `serve.allowed_origins`.
5. Check: open the site signed in (session shows your email), and call the tunnel URL with no
   Access cookie (must be blocked by Access; if it ever reaches brandcal, brandcal answers
   `IDENTITY_UNVERIFIED`).

---

## 3. Approvals from the console

### 3.1 The new channel

SPEC 7.1 has two channels, `card` and `writer-session`. A third, **`console`**, is a decision
made by the verified approver in the UI. Each such approval records:

- `decided_by`: the approver agent mapped from the verified email;
- the **verified identity** (email) and its **source** (`access-jwt`);
- `source_message_id`: the button id (for example `console-approve`), `approver_words`: the
  button label, plus the structured reason for request-changes (4.2);
- `content_version`, `content_hash` and `window` exactly as sent by the UI;
- `recorded_by` and `relayed_by`: the console recorder agent (`serve.console_agent`).

### 3.2 Schema change (migration for U1)

`approvals.channel` is `CHECK (channel IN ('card','writer-session','legacy'))`. U1 adds
migration `0002` (SQLite needs a table rebuild to change a CHECK; the migration must keep
rows, ids and the triggers, and be tested on a populated database). There was no migration
framework, so U1a adds `brandcal/migrations.py`: the version lives in `PRAGMA user_version`
(a database without one that has an `approvals` table is version 1), `open_db` applies pending
migrations, and `schema.sql` stays the source for fresh databases and stamps the latest version:

- channel CHECK becomes `('card','writer-session','legacy','console')`;
- new columns `verified_identity TEXT` and `identity_source TEXT`, both required when
  channel is `console`, and CHECKed to `access-jwt` (never
  `dev-unverified`);
- the existing triggers that require `recorded_by` and `relayed_by` to be a manager or writer
  are relaxed **only for channel `console`**: both must have role `system`, and `decided_by`
  must still have role `approver`. A trigger cannot read `config.json`, so that both are the
  *configured* `serve.console_agent` is enforced in code (`approvals.py`), not by the trigger;
- `audit` gains a check: every console approval has a verified identity and source
  (`console_unverified`); an `approve` decision on a published post matching its hash is the
  existing `published_unapproved` and `content_changed` check.

### 3.3 Stale views

The UI carries `version`, `hash` and `window` from the moment the post was loaded. The server
passes them to the same check as CLI `approve`. A mismatch is refused with `STALE_APPROVAL`
(exit 6) and the response also includes the current post, so the UI shows "This post changed
(v2 to v3). Read it again before deciding", reloads the card and re-enables the buttons for
the new version. Nothing is recorded. A window difference counts as stale too, because the
window is not in the hash but is bound to the approval (SPEC 5.4). Double submits are
harmless: the second attempt hits `BAD_TRANSITION` or the idempotent path.

### 3.4 Trust model delta (SPEC 7.3)

| SPEC 7.3 rule | Change for `console` |
|---|---|
| 1. Decisions come from outside the tool | Still true: the human acts in a browser behind Access; the server does not originate decisions |
| 2. Only the manager records decisions | **Amended:** the server records a console decision, acting on a verified human, through the `console` recorder agent. The manager never relays a console decision and cannot create one (the channel needs a verified identity) |
| 3. Relayed approvals produce a receipt | **Not needed for console**: no one relays, and the approver saw the exact text, fingerprint and window on screen when they pressed the button. The on-screen confirmation (with fingerprint and window) and the audit event replace the receipt |
| 4. Version and hash bind; window binds time | Unchanged |
| 5. `begin` re-checks | Unchanged; also refuses a console approval that lacks a verified identity (`IDENTITY_UNVERIFIED`, decision 7) |
| 6. `audit` | Extended as in 3.2 |
| 7. Manager compares live accounts | Unchanged |

New risk: a compromised Access session can approve. Mitigations are Access MFA, short Access
a 24-hour Access session, and the identity recorded on every approval. Console approvals are
not signed: the Access identity is the proof, and signing stays with T15 (decision 4).

### 3.5 Conflicts with existing SPEC rules, resolved

| Existing rule | Resolution |
|---|---|
| "Only the manager records decisions" (SPEC 7.3.2, 7.4) | Kept for `card` and `writer-session`. For `console` the server records on a verified human's behalf (3.4). Update SPEC 7.3 by cross-reference only |
| The approver role has no commands (AGENTS.md) | The CLI still has none: `approver` stays `ROLE_NOT_ALLOWED` on every CLI command. The approver's actions exist only through `serve` with a verified identity, using the same core functions. Role lists in `transitions` gain `approver` for the rows the UI can perform (deferred to U3: U1a leaves the table alone, and a console cancel is checked against the manager row because the transition roles name who records a decision) |
| Self-declared `--as NAME` | Unchanged for the CLI. The UI never uses it; dev mode is read-only (2.5) |
| System role never approves (SPEC 6.1) | The `console` agent has role `system` but only records; the deciding actor is the approver and the trigger enforces it (3.2) |
| Edits belong to writer and manager | Agents still edit through the CLI only. Only the human approver edits in the UI (4.1, decision 3); the CLI `edit` still refuses the approver role |
| Cards and buttons are sent by the manager | Console buttons need no card; the card flow remains for chat channels |

---

## 4. Human edits and requests

### 4.1 Editing

Only the verified approver can edit in the UI (agents edit through the CLI, 1.2): text, first comment, target URL,
alt text and window from the post panel, through `actions.edit`.

- A content edit makes a **new version** under the existing rules: status returns to
  `pending_approval` (automatic trigger), refused while the post is natively scheduled or
  claimed (`EDIT_WHILE_SCHEDULED`, `EDIT_WHILE_CLAIMED`).
- **Warning before saving**, when the post is `approved` or `missed`: "Saving creates version
  N+1 and withdraws the approval. You will need to approve again." When it is
  `pending_approval` or `changes_requested`: "Saving creates version N+1." The warning text is
  generated from the status and version, not typed in the UI.
- An edit never approves. The human reads the new version and presses Approve as a separate,
  deliberate step with the new hash.
- Changes to window, title, notes and keywords do not change the hash (SPEC 5.4); the UI says
  "no new approval needed" for those.
- Media upload is not in the UI (U3 scope); alt text edits are.

### 4.2 Request changes

Requires three non-empty fields, stored as JSON in `approvals.changes_requested`:

| Field | Meaning | Example |
|---|---|---|
| `what` | What is wrong | "The headline overstates the result" |
| `where` | Where it is (part number, field or media position) | "Part 1, sentence 2" |
| `instruction` | What the writer should do | "Say 'up to 20%' and cite the report" |

Missing or blank: `REASON_REQUIRED`. `brandcal request-changes` gains `--what`, `--where` and
`--instruction`, required for channel `console` and optional for older channels. `next` for the
writer then prints these fields verbatim.

### 4.3 Audit and discovery by agents

Every UI action is an event in the audit log with `actor` = the verified approver agent and
`detail` = `{"identity":"approver@example.com","source":"access-jwt","via":"console"}`
(dev mode: source `dev-unverified`). Nothing bypasses the hash chain.

Agents learn about human changes in two ways:

1. `brandcal next --as NAME` already lists `changes_requested` posts; it now includes the
   structured reason.
2. New read-only command **`brandcal events [--since EVENT_ID] [--post ID] [--actor NAME]
   [--limit N]`** (all roles; default limit 100; ordered by id). Output: `{"ok":true,
   "events":[...],"last_id":N,"next":"..."}`. An agent stores `last_id` and passes it as
   `--since` next time, so it sees every human edit, approval, request and cancellation exactly
   once. Archived events are not included (`ARCHIVED` hint as for `show`).

---

## 5. Views

### 5.1 Layout

- **Needs you** strip, always at the top: three counts and lists for `pending_approval`,
  `changes_requested` and `missed`, from `list --status`. Clicking one opens the post panel.
  The strip is collapsible: a button with `aria-expanded` toggles it, the choice is kept in
  `localStorage` (`brandcal-needs`), and collapsed it is one compact row of the three counts.
- **Today** is marked by a ring and a visible "Today" label in week and month views, never by
  colour alone.
- **Panel layout**: from 1200 px wide the open panel sits beside the grid (the grid shrinks;
  `main` gets right padding equal to the panel width); below that it overlays the page with a
  dimmed scrim, and a click on the scrim or Esc closes it. Focus moves into the panel on open
  and returns to the card on close.
- **Week** (default) and **Month** views over `list --from --to`. Posts are placed by window
  start in the configured timezone and show the window ("09:00 to 10:00", offset shown on
  hover). No timezone is assumed in the browser: all times are rendered from the server's
  strings with the configured zone.
- **Filters**: status (multi), platform, post type, campaign, pillar, "include closed",
  search by slug. Filter state is in the URL, so a view can be shared.
- A closed or archived month is read via the archive commands and marked "archive".

### 5.2 Icons and colours

- **Platform icon** and **post-type icon** (text, image, carousel, thread, article, reshare,
  video, comment) are looked up by id in the shipped SVG sprite. Unknown ids get a generic
  icon, and the id is always also shown as text (icons never carry meaning alone). Platform
  glyphs are neutral shapes or initials, not brand logos.
- **Status** has a label, a shape and a colour (never colour alone):

| State | Shape | Colour token |
|---|---|---|
| `pending_approval` | clock | `--st-pending` |
| `changes_requested` | pencil | `--st-changes` |
| `approved` | tick | `--st-approved` |
| `missed` | warning | `--st-missed` |
| `published` | globe | `--st-published` |
| `cancelled` | cross | `--st-cancelled` |

Post cards also show small badges for "natively scheduled", "claimed", "on hold" and an
unverified-dev flag, all from post fields.

**Licensing of the shipped icons.** `src/brandcal/web/icons.svg` is a hand-drawn outline set
made for this project on a 24 px grid (1.5 px stroke, `currentColor`, round caps). It copies no
third-party artwork and is released under the project's MIT licence. Platform glyphs are
generic metaphors (briefcase, bolt, camera, play, cloud, hexagon), never a platform's logo or
trade dress, so no trademark licence is needed; the platform id is always printed beside the
glyph. Any icon added later must be drawn in-house or come from a set whose licence permits
redistribution, with its licence file added next to the sprite.

### 5.3 Post detail panel

- Exact text of each part, as stored, in a preformatted block (nothing trimmed).
- Per platform and part: `N / limit` characters, with the limit from `/api/schema`; over
  limit shows `TOO_LONG` in red text with the label, not colour alone.
- Media preview with the **alt text** shown beneath and a warning if empty.
- First comment, target URL, window, campaign, pillar, notes.
- **Version history**: each version with its hash, editor and time; select two for a text diff
  (client-side, display only). Versions are rebuilt from the snapshots stored in the events,
  so there is no migration `0003`.
- **Fingerprint**: the first 8 characters of the hash, click to copy the full hash.
- Live URL(s) when published; claim and native schedule fields when set.
- **Audit trail** from `events` for that post, with the actor, the verified identity and
  source, and decision words. Console approvals are tagged "console (verified)".
- Action buttons per 1.5, each with its `brandcal ...` line labelled "Agent equivalent (CLI)".
  The confirm dialog repeats the label and adds: "This console action records channel console
  with your verified identity." The note button comes from the API under its own `note` key,
  beside `actions`, because a note is not a state transition.
- An unexpected server error is `INTERNAL`, exit code 9 (ERRORS.md, SPEC 8.2).

---

## 6. Visual design

Minimal glassmorphism, used for **structure only**:

- Translucent (`backdrop-filter: blur(24px)`, about 72% fill) for the floating layer only: the
  top bar and the side panel. Dialogs and cards are solid.
- **Text, icons, borders of status badges and status colours are solid**, always drawn on a
  panel whose effective background stays above the contrast limit.
- WCAG 2.2 AA: 4.5:1 for text, 3:1 for icons and focus rings; visible focus; keyboard
  operable; no information by colour alone; targets at least 24 px.
- `@media (prefers-reduced-transparency: reduce)` and browsers without `backdrop-filter`:
  panels become opaque `--panel-solid`. `@media (prefers-reduced-motion: reduce)` removes
  transitions and animations. `prefers-color-scheme: dark` has its own checked token set.

Light tokens (solid colours, checked at least 4.5:1 on `--bg` and `--panel-solid`):

| Token | Value | Use |
|---|---|---|
| `--bg` | `#F4F6FA` | page |
| `--panel-glass` | `rgba(255,255,255,0.72)` | translucent panel |
| `--panel-solid` | `#FFFFFF` | fallback panel |
| `--ink` / `--ink-muted` | `#0F172A` / `#475569` | text |
| `--accent` | `#1D4ED8` | links, focus |
| `--st-pending` | `#92400E` | amber |
| `--st-changes` | `#B91C1C` | red |
| `--st-approved` | `#166534` | green |
| `--st-missed` | `#6B21A8` | purple |
| `--st-published` | `#1E40AF` | blue |
| `--st-cancelled` | `#475569` | grey |

U2 includes a computed-contrast test over every token pair, so the table is verified, not
assumed. Font: `"Inter"` if installed, then the system stack (CI installs `fonts-inter`); no
web fonts, no external requests of any kind. Text sizes are `rem` (root 87.5%), no px sizes.
Entrance animation is a 250 ms fade with 4 px lift and 2 px blur; reduced motion fades only.

---

## 7. Testing

- **API tests (pytest, no browser):** start the server on an ephemeral port in a thread with
  a temporary home and fake data. Cover: every endpoint, the action table (UI action gives the
  same result and events as the CLI command), every refusal code and its `next`, JWT checks
  against locally generated RSA keys (good, wrong `aud`, wrong `iss`, expired, `alg=none`,
  unknown `kid`, bad signature), `IDENTITY_UNMAPPED`, Origin, Host, CSRF and content-type
  checks, no CORS headers, dev mode read-only, `STALE_APPROVAL` on an outdated view,
  the console migration on a populated database, and `audit` on console approvals.
- **Playwright screenshot tests:** pages are rendered against clearly fake demo data (Example
  Co, `example.com`) generated by a script into a temporary home, with the server using a
  stubbed test identity (no dev banner). Views: Needs you, week, month, post panel for each state, a
  refusal, a stale-view reload, reduced-transparency and dark variants. Baselines are compared
  with a small pixel tolerance and uploaded as CI artefacts.
- **Playwright is a development and CI-only dependency (approved, decision 2)**, added as `pyproject.toml` optional group `ui-test`). CI installs it with
  `pip install -e ".[dev,ui-test]"` then `playwright install --with-deps chromium`, in a
  separate job. The API tests run in the main pytest job and block merges. The screenshot job
  is advisory until U4 lands, then it blocks merges too (decision 2). Nothing is
  downloaded at runtime by brandcal.
- **Privacy scan stays in CI** and covers `docs/`, `src/brandcal/web/` and the screenshot
  baselines' source data (no real names, emails, domains or media).
- The standard five checks (AGENTS.md) run before every commit.

---

## 8. Build plan

Four tasks, each small enough for one session. Tests are written first.

### U1. Action layer and JSON API

U1 is split in two sessions. **U1a (core)** is items 1 to 4, 7 and 10: `src/brandcal/actions.py`
(new), `migrations.py` (new), `cli.py`, `approvals.py`, `publish.py`, `audit.py`, `reports.py`,
`errors.py`, `schema.sql`, `docs/ERRORS.md` (regenerated), `tests/test_actions.py`,
`tests/test_migrate_0002.py`, `tests/test_events_cmd.py`, `tests/test_console.py`. Console
decisions are driven through `actions` with a verified `Identity`; the CLI cannot record
them. **U1b (serve and identity)** is items 5, 6, 8 and 9: `src/brandcal/serve.py` (new),
`src/brandcal/identity.py` (new; U4 only reviews it against a real Access application),
`tests/test_serve_api.py`, `tests/test_identity.py`; it adds the optional `seen_window` /
`seen` checks to the decisions in `approvals.py` and `actions.py` (3.3) and `actions.post_actions`
(1.5); it also raises `IDENTITY_UNMAPPED`, `BAD_ORIGIN` and
`EXTRA_NOT_INSTALLED`, which U1a only defines.

1. CLI handlers move to `actions.py` with no behaviour change; the existing suite passes.
2. `brandcal events` exists with `--since`, `--post`, `--actor`, `--limit`, and `help events`.
3. `request-changes` accepts `--what/--where/--instruction`; `REASON_REQUIRED` is enforced for
   channel `console`.
4. Migration `0002` as in 3.2, tested on a populated database; triggers for `console`; `audit`
   check added.
5. `brandcal serve` binds to 127.0.0.1, serves the read endpoints and `GET /api/schema`
   (platforms, post types, transitions, timezone) from the database and config.
6. Write endpoints call the actions and return the CLI JSON; HTTP status follows 1.3.
7. New error codes are in `errors.py` and ERRORS.md.
8. `GET /api/posts/ID` returns `actions` per 1.5 with disabled reasons.
9. Identity: Access JWT verification per 2.3 and 2.4 (`EXTRA_NOT_INSTALLED` at start when
   the extra is missing), `IDENTITY_UNVERIFIED` and `IDENTITY_UNMAPPED`, and read-only
   `--dev-unverified` per 2.5. Every write without a verified identity is refused, tested per
   endpoint with locally signed test JWTs.
10. `begin` refuses a console approval without a verified identity with `IDENTITY_UNVERIFIED`.

### U2. Read-only views

Files: `src/brandcal/web/` (`index.html`, `app.js`, `app.css`, `icons.svg`), package-data
setting in `pyproject.toml`, `tests/test_web_static.py`.

1. Needs-you strip, week view, month view, list and filters, from the API only.
2. Post panel per 5.3, including character counts against limits and media with alt text.
3. Icons by id with a fallback; status label, shape and colour.
4. Times shown in the configured timezone with the window; nothing hard-coded for platform or
   status.
5. Glass styles with the reduced-transparency and reduced-motion fallbacks; contrast test over
   all token pairs.
6. No external requests; CSP passes with no inline script.

### U3. Edit, approve, request changes, cancel

Files: `src/brandcal/web/app.js`, `app.css`, `src/brandcal/serve.py`, `tests/test_serve_writes.py`.

1. Buttons come only from the `actions` array; disabled buttons show code and `next`.
2. Approve, Change time and Cancel send version, hash and window; the CLI line is shown for
   each.
3. Request changes form with the three required fields.
4. Edit form with the warning from 4.1; the edit does not approve.
5. `STALE_APPROVAL` reloads the post and shows the banner; nothing is recorded.
6. Every action leaves an event with the identity, source and `via: console`.
7. Dev mode is shown unverified everywhere and cannot decide.

### U4. Identity, tunnel docs and screenshots

Files: `src/brandcal/identity.py` (new), `src/brandcal/serve.py`, `docs/DEPLOY_UI.md` (new, 2.8),
`pyproject.toml` (only with the owner's approval), `tests/test_identity.py`, `tests/ui/`,
`scripts/make_demo_home.py`, CI workflow.

1. Access JWT verification (from U1) reviewed against a real Access application on a test
   account; JWKS refresh on an unknown `kid`.
2. `IDENTITY_UNVERIFIED` and `IDENTITY_UNMAPPED` on every UI path.
3. Origin, Host, CSRF and content-type checks per 2.7.
4. Console approvals refuse any identity source other than `access-jwt`.
5. `DEPLOY_UI.md` holds the generic tunnel and Access steps (fake hosts only).
6. Playwright tests and demo-data script per section 7; the screenshot job becomes blocking.
7. Privacy scan and the five standard checks pass.

---

## 9. Decisions (19 Oct 2026)

1. **JWT verification** uses the optional `cryptography` extra. Without it, `serve` refuses to
   start in verified mode with an explained `EXTRA_NOT_INSTALLED`. No stdlib RS256.
2. **Playwright** is a CI-only dev dependency. The API tests block merges; the screenshot job
   is advisory until U4, then it blocks.
3. **Only the approver edits in the UI.** Agents keep editing through the CLI (1.2, 4.1).
4. **Console approvals are not signed.** The Access identity is the proof; signing stays
   with T15.
5. **Access JWT only.** There is no trusted-header mode.
6. **Session length** is a Cloudflare setting; the docs recommend 24 hours for approvers.
7. **`begin`** on a console approval without a verified identity raises
   `IDENTITY_UNVERIFIED`, not `STALE_APPROVAL`.
8. **The CLI keeps refusing the approver role**; each role uses one surface (1.2).

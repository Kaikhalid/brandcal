// The console's reads and writes, ported from actions.py, approvals.py, posts.py, reports.py and
// validate.py. Only what the web UI calls is here: agents keep using the Python core, which reaches
// D1 through the sync endpoints (sync.ts). Each function names its Python original.

import {
  BrandcalError, CLOSED, EXIT, NEEDS_YOU, POST_TYPES, STATES, TIME_FORMAT, TRANSITIONS, type MediaRow,
  type PartRow, type PostRow, type Tz, badArgs, canonicalForm, checkTransition, normaliseTime,
  normaliseWindow, nowText, parseDate, parseTime, pyDumps, pyRepr, resolveTz, rowHash, sha256Hex,
  sqliteUtc, toLocal, localDate, utcText,
} from "./core";
import { CONSOLE_SOURCE } from "./auth";
import { Batch, type Cfg, META_SQL, type Row, parseCfg, readAll } from "./store";

export const EVENTS_LIMIT = 100;
const CLEAR = "native_scheduled_at = NULL, claimed_by = NULL, claim_expires = NULL";
const HEX = /^[0-9a-f]{8,64}$/;
const CANCEL_KINDS = ["idea", "version", "plan"];
const EDITABLE = [
  "title", "slug", "window", "first_comment", "target_url", "post_type", "campaign", "pillar",
  "series_id", "series_pos", "source_doc", "hold_until", "hold_reason",
];
const BUMP_FIELDS = new Set(["first_comment", "target_url", "post_type"]);
const QUEUE_FIELDS = new Set(["first_comment", "target_url", "post_type", "window"]);

export interface Verified { identity: string; source: string }
export interface Who { agent: string; verified: Verified | null }

export const tzOf = (cfg: Cfg): Tz => resolveTz(cfg.timezone ?? "");
const serveOf = (cfg: Cfg) => (cfg.serve && typeof cfg.serve === "object" ? cfg.serve : {}) as Record<string, unknown>;
const agentsOf = (cfg: Cfg) => (Array.isArray(cfg.agents) ? cfg.agents : []) as { id: string; role: string }[];

export function roleOf(cfg: Cfg, agent: string): string {
  const found = agentsOf(cfg).find((a) => a.id === agent);
  if (!found) throw new BrandcalError("NO_AGENT", `Unknown agent '${agent}'.`, "Check config.json agents.");
  return String(found.role);
}

export const consoleApprovalsEnabled = (cfg: Cfg) => serveOf(cfg).console_approvals === true;

// --- loading ------------------------------------------------------------------------------

const ARCHIVED_SQL =
  "SELECT json_extract(m.value, '$.post_id') AS pid, json_extract(e.detail, '$.month') AS month" +
  " FROM events e, json_each(e.detail, '$.manifest') m WHERE e.action = 'archive_written' ORDER BY e.id";

function notFound(postId: string, archived: Row[]): BrandcalError {
  let month: string | null = null;
  for (const r of archived) if (r.pid !== null && String(r.pid) === postId) month = String(r.month);
  if (month !== null) {
    return new BrandcalError(
      "ARCHIVED", `${postId} was archived in ${month}.`, `brandcal archive show ${postId} --month ${month}`,
    );
  }
  return new BrandcalError("NOT_FOUND", `No such post: ${postId}.`, "Run: brandcal list");
}

/** Everything one post's read or write needs, read in one consistent batch. */
export interface State {
  db: D1Database;
  gen: number;
  cfg: Cfg;
  tz: Tz;
  /** The NOT_FOUND or ARCHIVED refusal when the post does not exist; see present(). */
  missing: BrandcalError | null;
  post: PostRow;
  parts: PartRow[];
  media: MediaRow[];
  approvals: Row[];
  limits: Record<string, Record<string, unknown>>;
  others: Row[];
  nextApproval: number;
  nextEvent: number;
  lastHash: string | null;
}

export async function loadState(db: D1Database, postId: string): Promise<State> {
  const p = (sql: string, ...args: unknown[]) => db.prepare(sql).bind(...args);
  const [meta, post, parts, media, approvals, maxA, maxE, last, platforms, others, archived] =
    await readAll(db, [
      db.prepare(META_SQL),
      p("SELECT * FROM posts WHERE id = ?", postId),
      p("SELECT * FROM parts WHERE post_id = ? ORDER BY pos", postId),
      p("SELECT m.* FROM media m JOIN parts p ON p.id = m.part_id WHERE p.post_id = ? ORDER BY p.pos, m.pos", postId),
      p("SELECT * FROM approvals WHERE post_id = ? ORDER BY id", postId),
      db.prepare("SELECT COALESCE(MAX(id), 0) AS n FROM approvals"),
      db.prepare("SELECT COALESCE(MAX(id), 0) AS n FROM events"),
      p("SELECT row_hash FROM events WHERE chain = ? ORDER BY id DESC LIMIT 1", `post:${postId}`),
      db.prepare("SELECT id, limits FROM platforms"),
      p("SELECT id, platform, window_start_utc, window_end_utc FROM posts WHERE id <> ? AND window IS NOT NULL" +
        " AND status NOT IN ('published', 'cancelled') ORDER BY id", postId),
      db.prepare(ARCHIVED_SQL),
    ]);
  const { gen, cfg } = parseCfg(meta!);
  const tz = tzOf(cfg);
  const missing = post![0] ? null : notFound(postId, archived!);
  const limits: Record<string, Record<string, unknown>> = {};
  for (const r of platforms!) limits[String(r.id)] = JSON.parse(String(r.limits)) as Record<string, unknown>;
  return {
    db, gen, cfg, tz, missing, post: { ...(post![0] ?? { id: postId }) } as PostRow, parts: parts! as PartRow[], media: media! as MediaRow[],
    approvals: approvals!, limits, others: others!, nextApproval: Number(maxA![0]!.n) + 1,
    nextEvent: Number(maxE![0]!.n) + 1, lastHash: last![0] ? String(last![0].row_hash) : null,
  };
}

/** posts.load_post: raise at the point where Python loads the post. */
export function present(s: State): State {
  if (s.missing) throw s.missing;
  return s;
}

// --- shared pieces --------------------------------------------------------------------------

function postResult(s: State, next: string, warnings: string[]) {
  return {
    ok: true, id: s.post.id, status: s.post.status, version: s.post.content_version,
    hash: String(s.post.content_hash).slice(0, 8), window: s.post.window, next, warnings,
  };
}

function contentSnapshot(s: State) {
  return {
    version: s.post.content_version,
    hash: s.post.content_hash,
    parts: [...s.parts].sort((a, b) => a.pos - b.pos).map((p) => p.text),
    first_comment: s.post.first_comment ?? null,
    target_url: s.post.target_url ?? null,
    alt_texts: s.media.map((m) => m.alt_text),
  };
}

async function appendEvent(
  s: State, b: Batch, e: { at: string; actor: string; action: string; from: string | null; to: string | null; detail: unknown; reason?: string | null },
): Promise<void> {
  const detail = e.detail === null || e.detail === undefined ? null : pyDumps(e.detail);
  const chain = `post:${s.post.id}`;
  const reason = e.reason ?? null;
  const h = await rowHash(s.lastHash, e.at, e.actor, s.post.id, e.action, e.from, e.to, detail, reason, chain);
  b.add(
    "INSERT INTO events (id, at, actor, post_id, action, from_status, to_status, detail, reason, chain, prev_hash, row_hash)" +
      " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
    s.nextEvent, e.at, e.actor, s.post.id, e.action, e.from, e.to, detail, reason, chain, s.lastHash, h,
  );
  s.nextEvent += 1;
  s.lastHash = h;
}

function record(
  s: State, b: Batch, at: string, decision: string,
  o: { window: string; decidedBy: string; channel: string; relayedBy: string; recordedBy: string; msg: string; words: string; changes?: string | null; verified: Verified | null },
): number {
  const id = s.nextApproval++;
  b.add(
    'INSERT INTO approvals (id, post_id, decision, content_version, content_hash, "window", decided_by, channel,' +
      " relayed_by, recorded_by, source_message_id, approver_words, changes_requested, decided_at," +
      " verified_identity, identity_source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    id, s.post.id, decision, s.post.content_version, s.post.content_hash, o.window, o.decidedBy, o.channel,
    o.relayedBy, o.recordedBy, o.msg, o.words, o.changes ?? null, at,
    o.verified?.identity ?? null, o.verified?.source ?? null,
  );
  return id;
}

const via = (v: Verified | null) => (v ? { identity: v.identity, source: v.source, via: "console" } : {});

function need(name: string, value: string | null | undefined): string {
  if (!value || !value.trim()) throw badArgs(`${name} is required.`, "Give the approver's message id and exact words.");
  return value;
}

/** approvals._console: gate a console decision; the console recorder agent's id. */
function consoleGate(role: string, cfg: Cfg, verified: Verified | null, what: string): string {
  if (!verified || verified.source !== CONSOLE_SOURCE || !verified.identity.trim()) {
    throw new BrandcalError(
      "IDENTITY_UNVERIFIED", `A console decision (${what}) needs a verified identity; none was given.`,
      "Console decisions are made in the web UI behind Cloudflare Access (brandcal serve);" +
        " from the CLI use --channel card or writer-session.",
    );
  }
  if (role !== "approver") {
    throw new BrandcalError("ROLE_NOT_ALLOWED", `Role ${role} may not decide in the console.`, "Sign in as an approver.");
  }
  if (!consoleApprovalsEnabled(cfg)) {
    throw new BrandcalError(
      "CONSOLE_DISABLED", `A console decision (${what}) is disabled until serve.console_approvals is true.`,
      "Set serve.console_approvals to true in config.json (see docs/UI_SPEC.md).",
    );
  }
  const agent = serveOf(cfg).console_agent;
  if (!agentsOf(cfg).some((a) => a.role === "system" && a.id === agent)) {
    throw badArgs(
      "serve.console_agent is not a configured agent with role system.",
      "Set serve.console_agent in config.json, then run: brandcal init",
    );
  }
  return String(agent);
}

function expect(post: PostRow, ...statuses: string[]): void {
  if (!statuses.includes(String(post.status))) {
    throw new BrandcalError(
      "BAD_TRANSITION", `${post.id} is ${String(post.status)}; this needs ${statuses.join(" or ")}.`,
      "see the state machine in SPEC 6",
    );
  }
}

/** approvals._bind. */
function bind(post: PostRow, version: number, hashPrefix: string, seenWindow: string | null): void {
  const prefix = hashPrefix.toLowerCase();
  if (!HEX.test(prefix)) throw badArgs("The hash must be 8 or more hex characters.", "Copy it from the card.");
  const hash = String(post.content_hash);
  if (version !== post.content_version || !hash.startsWith(prefix)) {
    throw new BrandcalError(
      "STALE_APPROVAL",
      `${post.id} is now version ${String(post.content_version)} (${hash.slice(0, 8)}), not version ${version} (${prefix.slice(0, 8)}).`,
      `Send the approver the current version: brandcal preview ${post.id}`,
    );
  }
  if (seenWindow !== null && seenWindow !== post.window) {
    throw new BrandcalError(
      "STALE_APPROVAL", `${post.id} now has the window ${String(post.window)}, not ${seenWindow}.`,
      "Read the post again before deciding.",
    );
  }
}

function raiseFirst(errors: BrandcalError[]): void {
  if (errors.length === 0) return;
  const first = errors[0]!;
  if (errors.length > 1) throw new BrandcalError(first.code, errors.map((e) => e.message).join(" "), first.next);
  throw first;
}

// --- validate.py ----------------------------------------------------------------------------

const URL_RE = /https?:\/\/\S+/g;
const PLACEHOLDER = /\bTBC\b|\[link\]/i;
const NEEDS: Record<string, string[]> = { image: ["image", "gif"], carousel: ["pdf"], video: ["video"] };
const cp = (t: string) => [...t].length;

export function validate(s: State, stage: "add" | "check"): [BrandcalError[], string[]] {
  const post = s.post;
  const parts = [...s.parts].sort((a, b) => a.pos - b.pos);
  const kinds = s.media.map((m) => m.kind);
  const limits = s.limits[String(post.platform)] ?? {};
  const errors: BrandcalError[] = [];
  const warnings: string[] = [];
  const ptype = String(post.post_type);
  const bad = (code: string, message: string, next = "") => errors.push(new BrandcalError(code, message, next));
  const premium = limits.premium === true;
  let limit = limits[premium ? "premium_chars_per_post" : "chars_per_post"];
  if (premium && (limit === undefined || limit === null)) limit = limits.chars_per_post;
  const preview = limits.feed_preview_chars;
  const urlChars = Number(limits.url_chars ?? 23);
  for (const part of parts) {
    const n = cp(part.text.replace(URL_RE, () => "x".repeat(urlChars)));
    if (limit !== undefined && limit !== null && n > Number(limit)) {
      bad("TOO_LONG", `Part ${part.pos} is ${n} characters; the limit is ${String(limit)}.`,
        "Shorten the text or split it into a thread.");
    } else if (premium && preview !== undefined && preview !== null && n > Number(preview)) {
      warnings.push(`Part ${part.pos} is ${n} characters, over the ${String(preview)}-character feed preview.`);
    }
  }
  if (ptype === "thread" && parts.length < 2) {
    bad("INVALID_POST", "A thread needs 2 or more parts.", "Add parts: brandcal part add");
  } else if (ptype !== "thread" && parts.length !== 1) {
    bad("INVALID_POST", `A ${ptype} post has exactly 1 part, not ${parts.length}.`);
  }
  if ((ptype === "reshare" || ptype === "comment") && !post.target_url) bad("INVALID_POST", `A ${ptype} needs a target_url.`);
  if (ptype === "article") {
    if (!String(post.title).trim()) bad("INVALID_POST", "An article needs a title.");
    if (!parts.some((p) => p.text.trim())) bad("INVALID_POST", "An article needs a non-empty body.");
  }
  const needed = NEEDS[ptype];
  if (needed) {
    const count = kinds.filter((k) => needed.includes(k)).length;
    if (count === 0) {
      const message = `A ${ptype} post needs at least one ${needed.join(" or ")} file.`;
      if (stage === "check") bad("MEDIA_INVALID", message, "Attach it: brandcal media add");
      else warnings.push(message);
    }
    const max = limits.images_per_post;
    if (ptype === "image" && max !== undefined && max !== null && count > Number(max)) {
      bad("MEDIA_INVALID", `${count} images; the limit is ${String(max)}.`);
    }
  }
  const target = post.target_url ? String(post.target_url) : "";
  if (target) {
    const m = /^([A-Za-z][A-Za-z0-9+.-]*):(?:\/\/([^/?#]*))?/.exec(target);
    if (PLACEHOLDER.test(target)) warnings.push("target_url is a placeholder.");
    else if (!m || !["http", "https"].includes(m[1]!.toLowerCase()) || !m[2]) {
      bad("INVALID_POST", `target_url is not a well-formed link: ${pyRepr(target)}.`);
    }
  }
  const fields = [...parts.map((p) => p.text), post.first_comment ? String(post.first_comment) : ""];
  if (fields.some((t) => PLACEHOLDER.test(t))) warnings.push("Text contains a placeholder link (TBC or [link]).");
  for (const [field, key] of [["campaign", "campaigns"], ["pillar", "pillars"]] as const) {
    const allowed = Array.isArray(s.cfg[key]) ? (s.cfg[key] as unknown[]) : [];
    const value = post[field];
    if (value && allowed.length && !allowed.includes(value)) {
      warnings.push(`${field} ${pyRepr(String(value))} is not in the configured ${key}.`);
    }
  }
  if (post.window) {
    const start = String(post.window_start_utc);
    const end = String(post.window_end_utc);
    if (end < utcText(Date.now())) warnings.push("The window is in the past.");
    for (const o of s.others) {
      if (o.platform === post.platform && String(o.window_start_utc) < end && String(o.window_end_utc) > start) {
        warnings.push(`The window overlaps ${String(o.id)} on ${String(post.platform)}.`);
      }
    }
  }
  if (post.hold_until) {
    if (parseTime(String(post.hold_until)) > Date.now()) {
      const message = `On hold until ${String(post.hold_until)} (${post.hold_reason ? String(post.hold_reason) : "no reason given"}).`;
      if (stage === "check") bad("ON_HOLD", message, "Clear the hold: brandcal edit ID hold_until=");
      else warnings.push(message);
    }
  }
  return [errors, warnings];
}

// --- reads (actions.py, reports.py) ---------------------------------------------------------

export function schema() {
  return {
    ok: true,
    states: [...STATES],
    closed_states: [...CLOSED].sort(),
    transitions: TRANSITIONS.map(([f, t, r]) => ({ from: f, to: t, roles: r })),
    post_types: POST_TYPES,
    time_format: TIME_FORMAT,
    exit_codes: EXIT,
  };
}

export async function uiSchema(db: D1Database) {
  const [meta, platforms] = await readAll(db, [db.prepare(META_SQL), db.prepare("SELECT id, limits FROM platforms")]);
  const { cfg } = parseCfg(meta!);
  const limits: Record<string, unknown> = {};
  for (const r of platforms!) limits[String(r.id)] = JSON.parse(String(r.limits));
  return {
    ...schema(), platforms: limits, timezone: cfg.timezone ?? null, needs_you: NEEDS_YOU,
    claim_minutes: Math.trunc(Number(cfg.claim_minutes ?? 30)),
    campaigns: Array.isArray(cfg.campaigns) ? cfg.campaigns : [],
    pillars: Array.isArray(cfg.pillars) ? cfg.pillars : [],
  };
}

const shortRow = (p: Row) => ({ id: p.id, status: p.status, platform: p.platform, title: p.title, window: p.window });

function localDay(p: Row, tz: Tz): string {
  return localDate(toLocal(sqliteUtc(String(p.window_start_utc)), tz));
}

/** reports.list_posts (no archive). */
export async function listPosts(db: D1Database, q: Record<string, string>) {
  const [meta, rows] = await readAll(db, [db.prepare(META_SQL), db.prepare("SELECT * FROM posts ORDER BY window_start_utc, id")]);
  const { cfg } = parseCfg(meta!);
  const tz = tzOf(cfg);
  const lo = q.from === undefined ? null : parseDate(q.from);
  const hi = q.to === undefined ? null : parseDate(q.to);
  const closed = q.closed === "1" || q.closed === "true";
  const keep = (p: Row) => {
    if (q.status !== undefined && p.status !== q.status) return false;
    if (q.status === undefined && !closed && CLOSED.has(String(p.status))) return false;
    if (q.platform !== undefined && p.platform !== q.platform) return false;
    if (lo !== null || hi !== null) {
      if (p.window === null) return false;
      const d = localDay(p, tz);
      if ((lo !== null && d < lo) || (hi !== null && d > hi)) return false;
    }
    return true;
  };
  return { ok: true, posts: rows!.filter(keep).map(shortRow) };
}

/** reports.show. */
function show(s: State): Record<string, unknown> {
  return {
    ok: true,
    ...s.post,
    parts: [...s.parts].sort((a, b) => a.pos - b.pos).map((p) => ({ pos: p.pos, text: p.text })),
    media: s.media.map((m) => ({ path: m.path, kind: m.kind, alt_text: m.alt_text, sha256: m.sha256 })),
    approvals: s.approvals.map((a) => {
      const { signature: _sig, ...rest } = a;
      return rest;
    }),
  };
}

const BUTTONS: Record<string, string[]> = {
  pending_approval: ["approve", "request-changes", "edit", "cancel"],
  changes_requested: ["edit", "submit", "cancel"],
  approved: ["reschedule", "edit", "cancel"],
  missed: ["reschedule", "edit", "cancel"],
};
const LABELS: Record<string, string> = {
  approve: "Approve", "request-changes": "Request changes", edit: "Edit", cancel: "Cancel",
  submit: "Submit for approval", reschedule: "Change time",
};

function cliLine(button: string, post: Record<string, unknown>): string {
  const pid = String(post.id ?? "<post>");
  const seen = `${pid} --version ${String(post.content_version)} --hash ${String(post.content_hash).slice(0, 8)}`;
  const card = "--msg <message-id> --words <approver-words> --approver <approver> --as <manager>";
  const lines: Record<string, string> = {
    approve: `brandcal approve ${seen} --channel card ${card}`,
    "request-changes": `brandcal request-changes ${seen} ${card} --what <what> --where <where> --instruction <instruction>`,
    reschedule: `brandcal reschedule ${seen} --window <new-window> ${card}`,
    cancel: `brandcal cancel ${pid} --kind <idea|version|plan> --reason <reason> --as <manager>`,
    edit: `brandcal edit ${pid} <field>=<value> --as <writer>`,
    submit: `brandcal submit ${pid} --as <writer>`,
    note: `brandcal note ${pid} <text> --as <writer>`,
  };
  return lines[button]!;
}

function blocked(button: string, post: Record<string, unknown>): BrandcalError | null {
  const pid = String(post.id ?? "this post");
  const held = post.hold_until ? String(post.hold_until) : null;
  if (button === "approve" && held && parseTime(held) > Date.now()) {
    return new BrandcalError(
      "ON_HOLD", `On hold until ${held} (${post.hold_reason ? String(post.hold_reason) : "no reason"}).`,
      "Clear the hold first: brandcal edit ID hold_until=",
    );
  }
  if (button === "submit") {
    const asked = (post.approvals as Row[]).filter((a) => a.decision === "request_changes");
    if (asked.length && asked[asked.length - 1]!.content_hash === post.content_hash) {
      return new BrandcalError(
        "BAD_TRANSITION", "The content has not changed since changes were requested.",
        "Edit the post first, then submit again.",
      );
    }
  }
  const queued = post.native_scheduled_at;
  const claimed = post.claimed_by;
  const fromQueue = "Remove it from the platform's queue, then unschedule it.";
  const wait = "Wait for the claim to end (published, failed or expired).";
  if (button === "edit" && queued) return new BrandcalError("EDIT_WHILE_SCHEDULED", `${pid} is queued on the platform.`, fromQueue);
  if (button === "edit" && claimed) return new BrandcalError("EDIT_WHILE_CLAIMED", `${pid} is claimed by ${String(claimed)}.`, wait);
  if (button === "cancel" && queued) return new BrandcalError("NATIVELY_SCHEDULED", `${pid} is queued on the platform.`, fromQueue);
  if (button === "cancel" && claimed) return new BrandcalError("CLAIMED", `${pid} is claimed by ${String(claimed)}.`, wait);
  return null;
}

function item(button: string, post: Record<string, unknown>, cfg: Cfg, viewer: string | null) {
  let label = button === "note" ? "Add a note" : LABELS[button]!;
  if (button === "reschedule" && post.status === "missed") label = "Approve new time";
  let why: BrandcalError | null;
  if (viewer === null) {
    why = new BrandcalError(
      "IDENTITY_UNVERIFIED", "This session has no verified identity, so it is read-only.",
      "Sign in through Cloudflare Access.",
    );
  } else if (viewer !== "approver") {
    why = new BrandcalError("ROLE_NOT_ALLOWED", "You have read-only access.", "Ask the admin to list you in serve.approvers.");
  } else if (["approve", "request-changes", "reschedule", "cancel"].includes(button) && !consoleApprovalsEnabled(cfg)) {
    why = new BrandcalError(
      "CONSOLE_DISABLED", `A console decision (${button}) is disabled until serve.console_approvals is true.`,
      "Set serve.console_approvals to true in config.json (see docs/UI_SPEC.md).",
    );
  } else {
    why = blocked(button, post);
  }
  const out: Record<string, unknown> = {
    id: button, label, cli: cliLine(button, post), enabled: why === null,
    refusal: why === null ? null : why.toDict().error,
  };
  if (button === "edit") {
    const fresh = `Saving creates version ${Math.trunc(Number(post.content_version ?? 0)) + 1}`;
    out.warning = post.status === "approved" || post.status === "missed"
      ? `${fresh} and withdraws the approval. You will need to approve again.`
      : `${fresh}.`;
  }
  return out;
}

export function detailOf(s: State, viewer: string | null) {
  const out = show(s);
  out.actions = (BUTTONS[String(out.status)] ?? []).map((b) => item(b, out, s.cfg, viewer));
  out.note = CLOSED.has(String(out.status)) ? null : item("note", out, s.cfg, viewer);
  return out;
}

export async function postDetail(db: D1Database, postId: string, viewer: string | null) {
  return detailOf(present(await loadState(db, postId)), viewer);
}

export async function versions(db: D1Database, postId: string) {
  const s = present(await loadState(db, postId));
  const { results } = await db
    .prepare("SELECT at, actor, detail FROM events WHERE post_id = ? AND detail IS NOT NULL ORDER BY id")
    .bind(postId).all<Row>();
  const found = new Map<number, Record<string, unknown>>();
  for (const row of results) {
    const detail = JSON.parse(String(row.detail)) as unknown;
    const snap = detail && typeof detail === "object" && !Array.isArray(detail)
      ? (detail as Record<string, unknown>).snapshot : undefined;
    if (snap && typeof snap === "object" && !Array.isArray(snap)) {
      const d = detail as Record<string, unknown>;
      found.set(Math.trunc(Number((snap as Row).version)), {
        ...(snap as Row), editor: d.identity || row.actor, at: row.at,
      });
    }
  }
  const now = contentSnapshot(s);
  const live = Math.trunc(Number(now.version));
  if (!found.has(live) || found.get(live)!.hash !== now.hash) found.set(live, { ...now, editor: null, at: null });
  return { ok: true, id: postId, versions: [...found.keys()].sort((a, b) => a - b).map((k) => found.get(k)) };
}

export async function events(db: D1Database, since: number | null, post: string | null, limit: number) {
  if (since !== null && since < 0) throw badArgs("--since must be 0 or more.", "Pass the last_id of the previous call.");
  if (limit < 1) throw badArgs("--limit must be 1 or more.", `The default is ${EVENTS_LIMIT}.`);
  const where = ["id > ?"];
  const params: unknown[] = [since ?? 0];
  if (post !== null) {
    present(await loadState(db, post));
    where.push("post_id = ?");
    params.push(post);
  }
  const { results } = await db
    .prepare(`SELECT id, at, actor, post_id, action, from_status, to_status, reason, detail FROM events WHERE ${where.join(" AND ")} ORDER BY id LIMIT ?`)
    .bind(...params, limit).all<Row>();
  const items: Row[] = results.map((r) => ({ ...r, detail: r.detail === null ? null : JSON.parse(String(r.detail)) as unknown }));
  const lastId = items.length ? items[items.length - 1]!.id : (since ?? 0);
  return { ok: true, events: items, last_id: lastId, next: `brandcal events --since ${String(lastId)}` };
}

// --- writes (approvals.py, posts.py) ---------------------------------------------------------

export interface Seen { version: number; hash: string; window: string }

async function logEvent(s: State, b: Batch, actor: string, action: string, from: string, at: string, detail: unknown, reason: string | null = null) {
  await appendEvent(s, b, { at, actor, action, from, to: String(s.post.status), detail, reason });
}

function decidedState(s: State) {
  return { at: nowText(s.tz).at };
}

export async function approve(db: D1Database, who: Who, postId: string, seen: Seen) {
  const s = await loadState(db, postId);
  const role = roleOf(s.cfg, who.agent);
  const recorder = consoleGate(role, s.cfg, who.verified, "record an approval");
  const msg = need("msg", "console-approve");
  const words = need("words", "Approve");
  present(s);
  const before = String(s.post.status);
  expect(s.post, "pending_approval");
  bind(s.post, seen.version, seen.hash, seen.window);
  const [errors, warnings] = validate(s, "check");
  raiseFirst(errors);
  const { at } = decidedState(s);
  const b = new Batch(db, s.gen);
  const approval = record(s, b, at, "approve", {
    window: String(s.post.window), decidedBy: who.agent, channel: "console", relayedBy: recorder,
    recordedBy: recorder, msg, words, verified: who.verified,
  });
  b.add(`UPDATE posts SET status = 'approved', ${CLEAR}, updated_at = ? WHERE id = ?`, at, postId);
  Object.assign(s.post, { status: "approved", native_scheduled_at: null, claimed_by: null, claim_expires: null, updated_at: at });
  await logEvent(s, b, who.agent, "approve", before, at, { approval, channel: "console", msg, ...via(who.verified) });
  await b.commit();
  return postResult(s, `publish inside the window: brandcal begin ${postId}`, warnings);
}

export async function requestChanges(db: D1Database, who: Who, postId: string, seen: Seen, what: string | null, where: string | null, instruction: string | null) {
  const s = await loadState(db, postId);
  const role = roleOf(s.cfg, who.agent);
  const recorder = consoleGate(role, s.cfg, who.verified, "record a request for changes");
  const msg = need("msg", "console-request-changes");
  const words = need("words", "Request changes");
  const given = { what, where, instruction };
  if (!Object.values(given).every((v) => v && v.trim())) {
    throw new BrandcalError(
      "REASON_REQUIRED", "Request changes needs what, where and instruction, all non-empty.",
      "Give --what (what is wrong), --where (where it is) and --instruction (what to do).",
    );
  }
  const changes = pyDumps({ what: what!.trim(), where: where!.trim(), instruction: instruction!.trim() });
  present(s);
  const before = String(s.post.status);
  expect(s.post, "pending_approval");
  bind(s.post, seen.version, seen.hash, seen.window);
  const { at } = decidedState(s);
  const b = new Batch(db, s.gen);
  const approval = record(s, b, at, "request_changes", {
    window: String(s.post.window), decidedBy: who.agent, channel: "console", relayedBy: recorder,
    recordedBy: recorder, msg, words, changes, verified: who.verified,
  });
  b.add(`UPDATE posts SET status = 'changes_requested', ${CLEAR}, updated_at = ? WHERE id = ?`, at, postId);
  Object.assign(s.post, { status: "changes_requested", native_scheduled_at: null, claimed_by: null, claim_expires: null, updated_at: at });
  await logEvent(s, b, who.agent, "request-changes", before, at, { approval, ...via(who.verified) });
  await b.commit();
  return postResult(s, "writer: edit the post, then brandcal submit", []);
}

function queueGuard(post: PostRow): void {
  if (post.native_scheduled_at !== null && post.native_scheduled_at !== undefined) {
    throw new BrandcalError("EDIT_WHILE_SCHEDULED", "post is natively scheduled; unschedule it first");
  }
  if (post.claimed_by !== null && post.claimed_by !== undefined) {
    throw new BrandcalError("EDIT_WHILE_CLAIMED", "post is claimed for publishing");
  }
}

export async function reschedule(db: D1Database, who: Who, postId: string, seen: Seen, newWindow: string) {
  const s = await loadState(db, postId);
  const role = roleOf(s.cfg, who.agent);
  const recorder = consoleGate(role, s.cfg, who.verified, "record a time change");
  const msg = need("msg", "console-reschedule");
  const words = need("words", "Change time");
  const window = normaliseWindow(newWindow, s.tz);
  present(s);
  const before = String(s.post.status);
  expect(s.post, "approved", "missed");
  bind(s.post, seen.version, seen.hash, seen.window);
  if (window !== s.post.window) queueGuard(s.post);
  const { at } = decidedState(s);
  const b = new Batch(db, s.gen);
  const approval = record(s, b, at, "reschedule", {
    window, decidedBy: who.agent, channel: "console", relayedBy: recorder, recordedBy: recorder,
    msg, words, verified: who.verified,
  });
  const missed = before === "missed";
  b.add(`UPDATE posts SET "window" = ?, ${missed ? `status = 'approved', ${CLEAR},` : ""} updated_at = ? WHERE id = ?`, window, at, postId);
  Object.assign(s.post, { window, updated_at: at });
  if (missed) Object.assign(s.post, { status: "approved", native_scheduled_at: null, claimed_by: null, claim_expires: null });
  await logEvent(s, b, who.agent, "reschedule", before, at, { approval, window, ...via(who.verified) });
  await b.commit();
  return postResult(s, `publish inside the new window: brandcal begin ${postId}`, []);
}

export async function cancel(db: D1Database, who: Who, postId: string, kind: string, reason: string, seen: Seen) {
  const s = await loadState(db, postId);
  const role = roleOf(s.cfg, who.agent);
  if (!CANCEL_KINDS.includes(kind)) {
    throw badArgs(`Unknown cancel kind ${pyRepr(kind)}.`, `Use one of: ${CANCEL_KINDS.join(" ")}`);
  }
  const recorder = consoleGate(role, s.cfg, who.verified, "cancel");
  if (!reason.trim()) throw new BrandcalError("REASON_REQUIRED", "A cancel needs a reason.", "Say why the post is cancelled.");
  const msg = need("msg", "console-cancel");
  const words = need("words", "Cancel");
  present(s);
  const before = String(s.post.status);
  if (CLOSED.has(before)) throw new BrandcalError("POST_CLOSED", `${postId} is ${before} and cannot be changed.`);
  bind(s.post, seen.version, seen.hash, seen.window);
  checkTransition(before, "cancelled", role);
  if (s.post.native_scheduled_at) {
    throw new BrandcalError("NATIVELY_SCHEDULED", `${postId} is queued on the platform.`,
      `Remove it from the platform's queue, then: brandcal unschedule ${postId}`);
  }
  if (s.post.claimed_by) {
    throw new BrandcalError("CLAIMED", `${postId} is claimed by ${String(s.post.claimed_by)}.`,
      "Wait for the claim to end (published, failed or expired).");
  }
  const { at } = decidedState(s);
  const b = new Batch(db, s.gen);
  const detail: Record<string, unknown> = { kind, ...via(who.verified) };
  detail.approval = record(s, b, at, "cancel", {
    window: String(s.post.window), decidedBy: who.agent, channel: "console", relayedBy: recorder,
    recordedBy: recorder, msg, words, verified: who.verified,
  });
  b.add(`UPDATE posts SET status = 'cancelled', cancel_kind = ?, closed_at = ?, ${CLEAR}, updated_at = ? WHERE id = ?`, kind, at, at, postId);
  Object.assign(s.post, { status: "cancelled", cancel_kind: kind, closed_at: at, native_scheduled_at: null, claimed_by: null, claim_expires: null, updated_at: at });
  await logEvent(s, b, who.agent, "cancel", before, at, detail, reason);
  await b.commit();
  return postResult(s, "", []);
}

/** actions._console_via: the approver writes only with a verified console identity. */
function consoleVia(role: string, verified: Verified | null): Record<string, unknown> | null {
  if (role !== "approver") return null;
  if (!verified) {
    throw new BrandcalError("ROLE_NOT_ALLOWED", "Role approver may not change posts from the command line.",
      "Use the web console, or ask a writer or manager.");
  }
  if (verified.source !== CONSOLE_SOURCE || !verified.identity.trim()) {
    throw new BrandcalError("IDENTITY_UNVERIFIED", "Changes from the console need a verified identity; none was given.",
      "Sign in through Cloudflare Access.");
  }
  return via(verified);
}

function requireRole(role: string, v: Record<string, unknown> | null): void {
  if (!["writer", "manager"].includes(role) && !(role === "approver" && v !== null)) {
    throw new BrandcalError("ROLE_NOT_ALLOWED", `Role ${role} may not change posts.`, "Ask a writer or manager.");
  }
}

/** posts.edit_post through posts._mutate, with the schema's queue and content-bump triggers. */
export async function edit(db: D1Database, who: Who, postId: string, fields: [string, string][], parts: Map<number, string>, alts: Map<number, string>) {
  const s = await loadState(db, postId);
  const role = roleOf(s.cfg, who.agent);
  const v = consoleVia(role, who.verified);
  requireRole(role, v);
  const values = new Map<string, string | number | null>();
  for (const [field, raw] of fields) {
    const itemText = `${field}=${raw}`;
    if (!EDITABLE.includes(field)) throw badArgs(`Cannot edit ${pyRepr(itemText)}.`, `Use field=value with: ${EDITABLE.join(" ")}`);
    let value: string | number | null = raw || null;
    if (value !== null) {
      if (field === "window") value = normaliseWindow(raw, s.tz);
      else if (field === "hold_until") value = normaliseTime(raw, s.tz);
      else if (field === "series_pos") {
        if (!/^\d+$/.test(raw)) throw badArgs("series_pos must be a whole number.");
        value = Number(raw);
      }
    }
    values.set(field, value);
  }
  present(s);
  const before = String(s.post.status);
  if (CLOSED.has(before)) throw new BrandcalError("POST_CLOSED", `${postId} is ${before} and cannot be changed.`);
  const oldVersion = Number(s.post.content_version);
  const b = new Batch(db, s.gen);
  let bumped = false;
  const bump = async () => {
    if (bumped) return;
    bumped = true;
    const status = String(s.post.status);
    if (status === "approved" || status === "missed") {
      await appendEvent(s, b, {
        at: nowText(s.tz).at, actor: "system", action: "edit", from: status, to: "pending_approval",
        detail: null, reason: "content edited",
      });
      s.post.status = "pending_approval";
    }
  };
  for (const [field, value] of values) {
    const old = s.post[field] ?? null;
    if (QUEUE_FIELDS.has(field) && old !== value) queueGuard(s.post);
    if ((field === "title" || field === "slug") && value === null) {
      throw badArgs(`NOT NULL constraint failed: posts.${field}`);
    }
    b.add(`UPDATE posts SET "${field}" = ? WHERE id = ?`, value, postId);
    s.post[field] = value;
    if (BUMP_FIELDS.has(field) && old !== value) await bump();
  }
  const sorted = [...s.parts].sort((a, b2) => a.pos - b2.pos);
  for (const [pos, text] of parts) {
    if (!(pos >= 1 && pos <= sorted.length)) throw badArgs(`Position ${pos} is out of range 1..${sorted.length}.`);
    if (!text.trim()) throw badArgs(`Part ${pos} cannot be empty.`, "Write the text of the part.");
    const part = sorted[pos - 1]!;
    if (part.text !== text) {
      queueGuard(s.post);
      b.add("UPDATE parts SET text = ? WHERE id = ?", text, part.id);
      part.text = text;
      await bump();
    }
  }
  for (const [n, alt] of alts) {
    if (!(n >= 1 && n <= s.media.length)) throw badArgs(`There is no media file ${n}.`, `Use 1..${s.media.length}.`);
    if (!alt.trim()) throw badArgs("Alt text cannot be empty.", "Describe the media file.");
    queueGuard(s.post);
    const m = s.media[n - 1]!;
    b.add("UPDATE media SET alt_text = ? WHERE id = ?", alt, m.id);
    m.alt_text = alt;
    await bump();
  }
  const at = nowText(s.tz).at;
  s.post.updated_at = at;
  s.post.content_hash = await sha256Hex(canonicalForm(s.post, s.parts, s.media));
  const detail: Record<string, unknown> = { fields: [...values.keys()].sort() };
  if (parts.size) detail.parts = [...parts.keys()].sort((x, y) => x - y);
  if (alts.size) detail.alt_texts = [...alts.keys()].sort((x, y) => x - y);
  Object.assign(detail, v ?? {});
  if (bumped) {
    s.post.content_version = oldVersion + 1;
    detail.snapshot = contentSnapshot(s);
  }
  b.add("UPDATE posts SET updated_at = ?, content_hash = ?, content_version = ?, status = ? WHERE id = ?",
    at, s.post.content_hash, s.post.content_version, s.post.status, postId);
  await appendEvent(s, b, { at, actor: who.agent, action: "edit", from: before, to: String(s.post.status), detail });
  await b.commit();
  return postResult(s, `manager: send a card (brandcal preview ${postId})`, []);
}

export async function submit(db: D1Database, who: Who, postId: string) {
  const s = await loadState(db, postId);
  const role = roleOf(s.cfg, who.agent);
  const v = consoleVia(role, who.verified);
  requireRole(role, v);
  present(s);
  const before = String(s.post.status);
  checkTransition(before, "pending_approval", role);
  const asked = s.approvals.filter((a) => a.decision === "request_changes");
  if (asked.length && asked[asked.length - 1]!.content_hash === s.post.content_hash) {
    throw new BrandcalError("BAD_TRANSITION", "The content has not changed since changes were requested.",
      "Edit the post first, then submit again.");
  }
  const [errors, warnings] = validate(s, "check");
  raiseFirst(errors);
  const at = nowText(s.tz).at;
  const b = new Batch(db, s.gen);
  b.add("UPDATE posts SET status = 'pending_approval', updated_at = ? WHERE id = ?", at, postId);
  Object.assign(s.post, { status: "pending_approval", updated_at: at });
  await logEvent(s, b, who.agent, "submit", before, at, v);
  await b.commit();
  return postResult(s, `manager: send a card (brandcal preview ${postId})`, warnings);
}

export async function note(db: D1Database, who: Who, postId: string, text: string) {
  const s = await loadState(db, postId);
  const role = roleOf(s.cfg, who.agent);
  const v = consoleVia(role, who.verified);
  present(s);
  const at = nowText(s.tz).at;
  const status = String(s.post.status);
  const line = `${at} ${who.agent}: ${text}`;
  const b = new Batch(db, s.gen);
  b.add("UPDATE posts SET notes = CASE WHEN notes IS NULL THEN ? ELSE notes || char(10) || ? END, updated_at = ? WHERE id = ?",
    line, line, at, postId);
  s.post.notes = s.post.notes === null || s.post.notes === undefined ? line : `${String(s.post.notes)}\n${line}`;
  s.post.updated_at = at;
  await logEvent(s, b, who.agent, "note", status, at, v);
  await b.commit();
  return postResult(s, "", []);
}

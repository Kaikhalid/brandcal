// The agents' path to D1 (D1_MIGRATION.md 5). The Python CLI in remote mode pulls a snapshot, runs
// the command with the full Python core on a local copy, and pushes the row changes back with the
// generation it started from. The Worker re-checks what it can before applying: only the five
// calendar tables change, events and approvals are append-only, every new event continues its
// hash chain, and no pushed approval may claim the console channel or a verified identity (only
// the Worker records those, for the person Access verified).

import { BrandcalError, badArgs, rowHash } from "./core";
import { Batch, Conflict, type Row, META_SQL, parseCfg, readAll } from "./store";

export const TABLES = ["agents", "platforms", "transitions", "archive_lock", "posts", "parts", "media", "approvals", "events"];
const COLS: Record<string, string[]> = {
  posts: [
    "id", "slug", "title", "platform", "post_type", "status", "owner", "window", "series_id", "series_pos",
    "campaign", "pillar", "keywords", "first_comment", "target_url", "delegation_msg_id", "delegation_words",
    "hold_until", "hold_reason", "source_doc", "content_version", "content_hash", "native_scheduled_at",
    "claimed_by", "claim_expires", "platform_post_id", "platform_url", "published_at", "cancel_kind", "notes",
    "legacy_id", "extras", "created_at", "updated_at", "closed_at",
  ],
  parts: ["id", "post_id", "pos", "text", "platform_post_id", "platform_url"],
  media: [
    "id", "part_id", "pos", "kind", "path", "sha256", "alt_text", "bytes", "width", "height", "duration_s",
    "source_url", "credit", "licence",
  ],
  approvals: [
    "id", "post_id", "decision", "content_version", "content_hash", "window", "decided_by", "channel",
    "relayed_by", "recorded_by", "source_message_id", "approver_words", "changes_requested", "decided_at",
    "signature", "verified_identity", "identity_source",
  ],
  events: ["id", "at", "actor", "post_id", "action", "from_status", "to_status", "detail", "reason", "chain", "prev_hash", "row_hash"],
};
const KEYS: Record<string, string> = { posts: "id", parts: "id", media: "id", approvals: "id", events: "id" };
const SHIFT = 1_000_000;

export async function snapshot(db: D1Database): Promise<Record<string, unknown>> {
  const results = await readAll(db, [db.prepare(META_SQL), ...TABLES.map((t) => db.prepare(`SELECT * FROM ${t}`))]);
  const { gen, cfg } = parseCfg(results[0]!);
  const tables: Record<string, Row[]> = {};
  TABLES.forEach((t, i) => (tables[t] = results[i + 1]!));
  return { ok: true, gen, config: cfg, tables };
}

interface Change { upsert?: Row[]; delete?: (string | number)[]; insert?: Row[] }

const q = (c: string) => `"${c}"`;

function checkRow(table: string, row: unknown): Row {
  if (!row || typeof row !== "object" || Array.isArray(row)) throw badArgs(`A ${table} row must be an object.`);
  const cols = COLS[table]!;
  for (const k of Object.keys(row)) if (!cols.includes(k)) throw badArgs(`Unknown column ${table}.${k}.`);
  if (!(KEYS[table]! in row)) throw badArgs(`A ${table} row needs its ${KEYS[table]}.`);
  return row as Row;
}

function upsertSql(table: string, row: Row): [string, unknown[]] {
  const cols = Object.keys(row);
  const key = KEYS[table]!;
  const sets = cols.filter((c) => c !== key).map((c) => `${q(c)} = excluded.${q(c)}`);
  const sql = `INSERT INTO ${table} (${cols.map(q).join(", ")}) VALUES (${cols.map(() => "?").join(", ")})` +
    (sets.length ? ` ON CONFLICT(${key}) DO UPDATE SET ${sets.join(", ")}` : ` ON CONFLICT(${key}) DO NOTHING`);
  return [sql, cols.map((c) => row[c])];
}

export async function apply(db: D1Database, body: unknown): Promise<{ ok: true; gen: number; applied: Record<string, number> }> {
  if (!body || typeof body !== "object") throw badArgs("The body must be one JSON object.");
  const { base_gen: baseGen, changes } = body as { base_gen?: unknown; changes?: unknown };
  if (typeof baseGen !== "number" || !Number.isInteger(baseGen)) throw badArgs("base_gen must be a whole number.");
  if (!changes || typeof changes !== "object") throw badArgs("changes must be an object.");
  const ch = changes as Record<string, Change>;
  for (const t of Object.keys(ch)) {
    if (!(t in COLS)) {
      throw new BrandcalError("ROLE_NOT_ALLOWED", `Remote mode cannot change ${t}.`,
        "Change agents, platforms and config with the admin import (D1_MIGRATION.md 7).");
    }
  }
  const [meta, maxA, maxE] = await readAll(db, [
    db.prepare(META_SQL),
    db.prepare("SELECT COALESCE(MAX(id), 0) AS n FROM approvals"),
    db.prepare("SELECT COALESCE(MAX(id), 0) AS n FROM events"),
  ]);
  const { gen } = parseCfg(meta!);
  if (gen !== baseGen) throw new Conflict("stale base_gen");
  const b = new Batch(db, gen);
  const applied: Record<string, number> = {};
  // Append-only tables: inserts only, above the current maximum id.
  for (const t of ["approvals", "events"]) {
    const c = ch[t];
    if (!c) continue;
    if (c.upsert?.length || c.delete?.length) {
      throw new BrandcalError("APPEND_ONLY", `${t} are append-only; remote mode can only add them.`);
    }
  }
  const newApprovals = (ch.approvals?.insert ?? []).map((r) => checkRow("approvals", r)).sort((a, b2) => Number(a.id) - Number(b2.id));
  let expectA = Number(maxA![0]!.n) + 1;
  for (const a of newApprovals) {
    if (Number(a.id) !== expectA++) throw new BrandcalError("APPEND_ONLY", "Pushed approvals must follow the last approval id.");
    if (a.channel === "console" || a.verified_identity !== null && a.verified_identity !== undefined || a.identity_source) {
      throw new BrandcalError("ROLE_NOT_ALLOWED", "Only the web console records console decisions.",
        "Use --channel card or writer-session from the CLI.");
    }
  }
  const newEvents = (ch.events?.insert ?? []).map((r) => checkRow("events", r)).sort((a, b2) => Number(a.id) - Number(b2.id));
  let expectE = Number(maxE![0]!.n) + 1;
  const chains = [...new Set(newEvents.map((e) => String(e.chain)))];
  const lasts = new Map<string, string | null>();
  if (chains.length) {
    const rows = await readAll(db, chains.map((c) =>
      db.prepare("SELECT row_hash FROM events WHERE chain = ? ORDER BY id DESC LIMIT 1").bind(c)));
    chains.forEach((c, i) => lasts.set(c, rows[i]![0] ? String(rows[i]![0]!.row_hash) : null));
  }
  for (const e of newEvents) {
    if (Number(e.id) !== expectE++) throw new BrandcalError("APPEND_ONLY", "Pushed events must follow the last event id.");
    const chain = String(e.chain);
    const prev = lasts.get(chain) ?? null;
    const s = (k: string) => (e[k] === null || e[k] === undefined ? null : String(e[k]));
    const want = await rowHash(prev, String(e.at), String(e.actor), s("post_id"), String(e.action), s("from_status"),
      s("to_status"), s("detail"), s("reason"), chain);
    if ((e.prev_hash ?? null) !== prev || e.row_hash !== want) {
      throw new BrandcalError("HASH_MISMATCH", `Event ${String(e.id)} does not continue the ${chain} hash chain.`,
        "Pull again and rerun the command.");
    }
    lasts.set(chain, want);
  }
  // Deletes (part removal): media first, then parts. Posts are never deleted remotely.
  if (ch.posts?.delete?.length) {
    throw new BrandcalError("ROLE_NOT_ALLOWED", "Remote mode does not delete posts.", "Archive runs stay an admin task.");
  }
  for (const t of ["media", "parts"]) {
    for (const id of ch[t]?.delete ?? []) b.add(`DELETE FROM ${t} WHERE id = ?`, id);
    applied[`${t}_deleted`] = ch[t]?.delete?.length ?? 0;
  }
  // Positions are UNIQUE per post (parts) and per part (media): park moved rows first.
  for (const t of ["parts", "media"]) {
    const ids = (ch[t]?.upsert ?? []).map((r) => checkRow(t, r).id);
    if (ids.length) b.add(`UPDATE ${t} SET pos = pos + ${SHIFT} WHERE id IN (${ids.map(() => "?").join(", ")})`, ...ids);
  }
  for (const t of ["posts", "parts", "media"]) {
    const rows = (ch[t]?.upsert ?? []).map((r) => checkRow(t, r));
    for (const r of rows) {
      const [sql, params] = upsertSql(t, r);
      b.add(sql, ...params);
    }
    applied[t] = rows.length;
  }
  for (const [t, rows] of [["approvals", newApprovals], ["events", newEvents]] as const) {
    for (const r of rows) {
      const cols = Object.keys(r);
      b.add(`INSERT INTO ${t} (${cols.map(q).join(", ")}) VALUES (${cols.map(() => "?").join(", ")})`, ...cols.map((c) => r[c]));
    }
    applied[t] = rows.length;
  }
  const next = await b.commit();
  return { ok: true, gen: next, applied };
}


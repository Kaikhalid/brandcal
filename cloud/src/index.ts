// brandcal on Cloudflare (D1_MIGRATION.md): the built web UI from Workers static assets and the
// JSON API of `brandcal serve` from D1. Same frame as serve.py: identity from the Access JWT,
// origin and CSRF checks on writes, the CLI's JSON and exit code, and no detail on a fault.

import { CONSOLE_SOURCE, SERVICE_SOURCE, type Session, csrf, resolve, sameText, verify } from "./auth";
import { BrandcalError, badArgs } from "./core";
import cspPages from "../../src/brandcal/web_next/csp.json";
import * as model from "./model";
import { Conflict, META_SQL, parseCfg, retrying } from "./store";
import { apply, snapshot } from "./sync";

export interface Env {
  DB: D1Database;
  ASSETS: Fetcher;
  BACKUPS?: KVNamespace;
  /** A secret (wrangler secret put); the CSRF tokens are HMACs under it. */
  CSRF_SECRET: string;
  /** Tests only: where to fetch the Access keys from, honoured only when ENVIRONMENT is "test". */
  CERTS_URL?: string;
  ENVIRONMENT?: string;
}

const BODY_LIMIT = 256 * 1024;
const SYNC_LIMIT = 4 * 1024 * 1024;
const DEFAULT_CSP = "default-src 'self'";
const STATUS: Record<number, number> = { 2: 400, 3: 422, 4: 403, 5: 409, 6: 409, 7: 404, 8: 409, 9: 500 };
const HASH = /^sha256-[A-Za-z0-9+/_-]+={0,2}$/;
const ESCAPED = /%(?:2e|2f|5c|00)/i;

function cspFor(page: string): string {
  const hashes = (cspPages as Record<string, Record<string, string[]>>)[page];
  if (!hashes) return DEFAULT_CSP;
  const d = (k: string) => (hashes[k] ?? []).filter((v) => HASH.test(v)).map((v) => `'${v}'`);
  const parts = [DEFAULT_CSP];
  if (d("script").length) parts.push(`script-src 'self' ${d("script").join(" ")}`);
  const styles = [...d("style"), ...d("style_attr")];
  if (styles.length) parts.push(`style-src 'self'${d("style_attr").length ? " 'unsafe-hashes'" : ""} ${styles.join(" ")}`);
  return parts.join("; ");
}

function headers(ctype: string, exit = 0, csp = DEFAULT_CSP): Headers {
  return new Headers({
    "Content-Type": ctype, "X-Brandcal-Exit": String(exit), "Content-Security-Policy": csp,
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
  });
}

function json(status: number, body: unknown, exit = 0): Response {
  return new Response(JSON.stringify(body), { status, headers: headers("application/json", exit) });
}

function refuse(err: BrandcalError, extra: Record<string, unknown> = {}, status?: number): Response {
  const s = status ?? (err.code === "IDENTITY_UNVERIFIED" ? 401 : STATUS[err.exit] ?? 500);
  return json(s, { ...err.toDict(), ...extra }, err.exit);
}

const notFound = (what: string) => new BrandcalError("NOT_FOUND", `No such ${what}.`, "Check the address; see brandcal help.");

async function readBody(request: Request, limit: number): Promise<string> {
  const length = request.headers.get("Content-Length");
  if (length !== null && !/^\d+$/.test(length)) throw badArgs("A Content-Length header is required.", "Send a JSON body.");
  const text = await request.text();
  if (new TextEncoder().encode(text).length > limit) {
    throw badArgs(`The body is over ${Math.floor(limit / 1024)} KiB.`, "Send a smaller request.");
  }
  return text;
}

/** serve._static: a file of the Next.js build, never csp.json, dotfiles or odd paths. */
async function serveStatic(request: Request, env: Env, path: string): Promise<Response> {
  if (!path.startsWith("/") || path.includes("\\") || ESCAPED.test(path)) throw notFound("page");
  let decoded: string;
  try {
    decoded = decodeURIComponent(path);
  } catch {
    throw notFound("page");
  }
  if ([...decoded].some((c) => c.charCodeAt(0) < 0x20 || c === "\x7f")) throw notFound("page");
  const segs = decoded.split("/").slice(1);
  const inner = segs[segs.length - 1] === "" ? segs.slice(0, -1) : segs;
  if (inner.some((p) => !p || p.startsWith(".")) || decoded === "/csp.json") throw notFound("page");
  const asset = (p: string) => env.ASSETS.fetch(new Request(new URL(p, request.url), { method: "GET" }));
  const res = await asset(path.endsWith("/") ? `${path}index.html` : path);
  if (res.status === 404 && !path.endsWith("/") && inner.length && (await asset(`${path}/index.html`)).ok) {
    const search = new URL(request.url).search;
    const h = headers("text/plain; charset=utf-8");
    h.set("Location", `${path}/${search}`);
    return new Response(null, { status: 308, headers: h });
  }
  if (!res.ok) throw notFound("page");
  const ctype = res.headers.get("Content-Type") ?? "application/octet-stream";
  let csp = DEFAULT_CSP;
  if (ctype.startsWith("text/html")) {
    const page = decoded.endsWith("/") ? `${decoded.slice(1)}index.html` : decoded.slice(1);
    csp = cspFor(page);
  }
  return new Response(res.body, { status: 200, headers: headers(ctype, 0, csp) });
}

async function session(request: Request, env: Env, serve: Record<string, unknown>): Promise<Session> {
  const identity = (serve.identity ?? {}) as Record<string, unknown>;
  const certs = env.ENVIRONMENT === "test" ? env.CERTS_URL : undefined;
  const claims = await verify(request.headers.get("Cf-Access-Jwt-Assertion"), identity, undefined, certs);
  return resolve(serve, claims);
}

function query(url: URL): Record<string, string> {
  const q: Record<string, string> = {};
  for (const [k, v] of url.searchParams) if (v !== "" && !(k in q)) q[k] = v;
  return q;
}

function intArg(q: Record<string, string>, key: string): number | null {
  if (!(key in q)) return null;
  if (!/^\s*[+-]?\d+\s*$/.test(q[key]!)) throw badArgs(`${key} must be a whole number.`, `Pass ?${key}=N.`);
  return Number(q[key]!.trim());
}

function text(body: Record<string, unknown>, key: string): string {
  const v = body[key];
  if (typeof v !== "string" || !v.trim()) throw badArgs(`${key} is required.`, `Send ${key} as non-empty text.`);
  return v;
}
const optional = (body: Record<string, unknown>, key: string) => (typeof body[key] === "string" ? (body[key] as string) : null);

function seen(body: Record<string, unknown>): model.Seen {
  const v = body.version;
  if (typeof v !== "number" || !Number.isInteger(v)) throw badArgs("version must be a whole number.", "Send the version you loaded.");
  return { version: v, hash: text(body, "hash"), window: text(body, "window") };
}

function numbered(body: Record<string, unknown>, key: string): Map<number, string> {
  const value = body[key] ?? {};
  const ok = value !== null && typeof value === "object" && !Array.isArray(value) &&
    Object.entries(value).every(([k, v]) => /^\d+$/.test(k) && typeof v === "string");
  if (!ok) throw badArgs(`${key} must map positions to text.`, `Send {"${key}": {"1": "..."}}.`);
  return new Map(Object.entries(value as Record<string, string>).map(([k, v]) => [Number(k), v]));
}

type Write = (db: D1Database, who: model.Who, pid: string, b: Record<string, unknown>) => Promise<unknown>;
const WRITES: Record<string, Write> = {
  approve: (db, who, pid, b) => model.approve(db, who, pid, seen(b)),
  "request-changes": (db, who, pid, b) => {
    const s = seen(b);
    return model.requestChanges(db, who, pid, s, optional(b, "what"), optional(b, "where"), optional(b, "instruction"));
  },
  reschedule: (db, who, pid, b) => {
    const s = seen(b);
    return model.reschedule(db, who, pid, s, text(b, "new_window"));
  },
  cancel: (db, who, pid, b) => model.cancel(db, who, pid, text(b, "kind"), optional(b, "reason") ?? "", seen(b)),
  edit: (db, who, pid, b) => {
    const fields = b.fields ?? {};
    if (!fields || typeof fields !== "object" || Array.isArray(fields) || !Object.values(fields).every((v) => typeof v === "string")) {
      throw badArgs("fields must be an object of text values.", 'Send {"fields": {...}}.');
    }
    const parts = numbered(b, "parts");
    const alts = numbered(b, "alt_texts");
    const entries = Object.entries(fields as Record<string, string>);
    if (!entries.length && !parts.size && !alts.size) throw badArgs("There is nothing to change.", "Send fields, parts or alt_texts.");
    return model.edit(db, who, pid, entries, parts, alts);
  },
  submit: (db, who, pid) => model.submit(db, who, pid),
  note: (db, who, pid, b) => model.note(db, who, pid, text(b, "text")),
};

async function api(request: Request, env: Env, url: URL, parts: string[], extra: Record<string, unknown>): Promise<Response> {
  const body = request.method === "POST"
    ? await readBody(request, parts[0] === "sync" ? SYNC_LIMIT : BODY_LIMIT) : "";
  const meta = await env.DB.prepare(META_SQL).all<Record<string, unknown>>();
  const { cfg } = parseCfg(meta.results);
  const serve = (cfg.serve ?? {}) as Record<string, unknown>;
  const who = await session(request, env, serve);
  // The agents' sync endpoints take a service token only; people never reach them.
  if (parts[0] === "sync") {
    if (who.source !== SERVICE_SOURCE) throw new BrandcalError("ROLE_NOT_ALLOWED", "Sync is for the agents' service token only.");
    if (request.method === "GET" && parts.length === 2 && parts[1] === "snapshot") return json(200, await snapshot(env.DB));
    if (request.method === "POST" && parts.length === 2 && parts[1] === "apply") {
      let data: unknown;
      try {
        data = JSON.parse(body);
      } catch {
        throw badArgs("The body is not valid JSON.", "Send one JSON object.");
      }
      return json(200, await apply(env.DB, data));
    }
    throw notFound("endpoint");
  }
  if (who.source !== CONSOLE_SOURCE) throw new BrandcalError("ROLE_NOT_ALLOWED", "Service tokens may only use /api/sync.");
  const viewer = who.role;
  if (request.method === "GET") {
    const q = query(url);
    let out: unknown;
    if (parts.length === 1 && parts[0] === "session") {
      out = { ok: true, identity: who.email, role: who.role, source: who.source, csrf: await csrf(env.CSRF_SECRET, who) };
    } else if (parts.length === 1 && parts[0] === "schema") out = await model.uiSchema(env.DB);
    else if (parts.length === 1 && parts[0] === "posts") out = await model.listPosts(env.DB, q);
    else if (parts.length === 2 && parts[0] === "posts") out = await model.postDetail(env.DB, parts[1]!, viewer);
    else if (parts.length === 3 && parts[0] === "posts" && parts[2] === "versions") out = await model.versions(env.DB, parts[1]!);
    else if (parts.length === 1 && parts[0] === "events") {
      out = await model.events(env.DB, intArg(q, "since"), q.post ?? null, intArg(q, "limit") || model.EVENTS_LIMIT);
    } else if (parts.length === 3 && parts[0] === "media") {
      // No media files live in the cloud yet (D1_MIGRATION.md 2); every media request is 404.
      if (!/^\d+$/.test(parts[2]!) || Number(parts[2]) < 1) throw notFound("media file");
      model.present(await model.loadState(env.DB, parts[1]!));
      throw notFound("media file");
    } else throw notFound("endpoint");
    return json(200, out);
  }
  // Writes (serve._post).
  const origins = Array.isArray(serve.allowed_origins) ? serve.allowed_origins.map(String) : [];
  const hosts = new Set(origins.map((o) => { try { return new URL(o).host; } catch { return ""; } }));
  const origin = request.headers.get("Origin");
  const host = request.headers.get("Host") ?? url.host;
  if (origin === null || !origins.includes(origin) || !hosts.has(host)) {
    throw new BrandcalError("BAD_ORIGIN", "This request did not come from an allowed origin and host.",
      "Use the site's own address, or ask the admin to check serve.allowed_origins.");
  }
  const expected = (await csrf(env.CSRF_SECRET, who)) ?? "";
  if (!sameText(request.headers.get("X-Brandcal-CSRF") ?? "", expected)) {
    throw new BrandcalError("BAD_ORIGIN", "The CSRF token is missing or wrong.", "Reload the page to get a new one (GET /api/session).");
  }
  const ctype = (request.headers.get("Content-Type") ?? "").split(";")[0]!.trim().toLowerCase();
  if (ctype !== "application/json") throw badArgs("Writes must be application/json.", "Send a JSON body.");
  if (who.role !== "approver" || who.agent === null) {
    throw new BrandcalError("ROLE_NOT_ALLOWED", "You have read-only access.", "Ask the admin to list you in serve.approvers.");
  }
  let data: unknown;
  try {
    data = JSON.parse(body);
  } catch {
    throw badArgs("The body is not valid JSON.", "Send one JSON object.");
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) throw badArgs("The body must be one JSON object.", "Send one JSON object.");
  if (parts.length !== 3 || parts[0] !== "posts" || !(parts[2]! in WRITES)) throw notFound("endpoint");
  const pid = parts[1]!;
  const identity: model.Who = { agent: who.agent, verified: { identity: String(who.email), source: who.source } };
  try {
    const out = await retrying(() => WRITES[parts[2]!]!(env.DB, identity, pid, data as Record<string, unknown>));
    return json(200, out);
  } catch (err) {
    if (err instanceof BrandcalError && err.code === "STALE_APPROVAL") {
      extra.current = await model.postDetail(env.DB, pid, viewer);
    }
    throw err;
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const extra: Record<string, unknown> = {};
    try {
      const url = new URL(request.url);
      if (request.method !== "GET" && request.method !== "POST") {
        const r = refuse(badArgs(`${request.method} is not allowed.`, "Use GET, POST."), {}, 405);
        r.headers.set("Allow", "GET, POST");
        return r;
      }
      const path = url.pathname;
      const parts = path.split("/").slice(1).map((p) => { try { return decodeURIComponent(p); } catch { return p; } });
      if (request.method === "GET" && parts[0] !== "api") return await serveStatic(request, env, path);
      if (parts.length < 2 || parts[0] !== "api") throw notFound("page");
      return await api(request, env, url, parts.slice(1), extra);
    } catch (err) {
      if (err instanceof Conflict) {
        return json(409, { ok: false, error: { code: "CONFLICT", message: "The calendar changed since your snapshot.", next: "Pull again and retry." } }, 8);
      }
      if (err instanceof BrandcalError) return refuse(err, extra);
      console.error("internal fault", err instanceof Error ? err.name : "unknown");
      const fault = new BrandcalError("INTERNAL", "The server hit an unexpected fault and could not answer this request.",
        "Try again; if it keeps happening, tell the admin to check the server's log.");
      return json(500, fault.toDict(), fault.exit);
    }
  },

  /** Daily backup (D1_MIGRATION.md 6): a JSON snapshot in KV, kept 35 days; D1 Time Travel covers 7. */
  async scheduled(_event: ScheduledController, env: Env): Promise<void> {
    if (!env.BACKUPS) return;
    const snap = await snapshot(env.DB);
    const day = new Date().toISOString().slice(0, 10);
    await env.BACKUPS.put(`snapshot/${day}.json`, JSON.stringify(snap), { expirationTtl: 35 * 86400 });
  },
};

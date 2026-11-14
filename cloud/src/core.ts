// Shared pieces of the Python core (src/brandcal), ported for the Worker: error codes, the state
// machine, time text, Python-identical JSON and the SHA-256 fingerprints. Python is the reference;
// test/core.test.ts checks these against values the Python code produced.

export const EXIT: Record<string, number> = {
  TIME_OFFSET_REQUIRED: 3, COMMENT_NOT_DELEGATED: 4, NATIVELY_SCHEDULED: 5, NO_FRESH_BACKUP: 5,
  WINDOW_NOT_APPROVED: 6, CHECK_LIVE_FIRST: 8, BAD_ARGS: 2, TZ_NOT_CONFIGURED: 2,
  HOME_NOT_CONFIGURED: 2, BAD_TIME: 3, BAD_WINDOW: 3, ROLE_NOT_ALLOWED: 4, BAD_TRANSITION: 5,
  EDIT_WHILE_SCHEDULED: 5, EDIT_WHILE_CLAIMED: 5, STALE_APPROVAL: 6, APPEND_ONLY: 5, NO_AGENT: 2,
  MEDIA_INVALID: 3, TOO_LONG: 3, ON_HOLD: 3, NOT_FOUND: 7, POST_CLOSED: 5, INVALID_POST: 3,
  HASH_MISMATCH: 6, CLAIMED: 8, URL_CONFLICT: 8, ARCHIVED: 7, IDENTITY_UNVERIFIED: 4,
  IDENTITY_UNMAPPED: 4, BAD_ORIGIN: 4, REASON_REQUIRED: 3, EXTRA_NOT_INSTALLED: 2,
  SECRET_UNAVAILABLE: 2, CONNECTOR_REFUSED: 4, CONNECTOR_REPLACED: 8, PROTOCOL_MISMATCH: 2,
  CONSOLE_DISABLED: 4, INTERNAL: 9,
};

export class BrandcalError extends Error {
  constructor(public code: string, message: string, public next = "") {
    super(message);
  }
  get exit(): number {
    return EXIT[this.code] ?? 9;
  }
  toDict(): { ok: false; error: { code: string; message: string; next: string } } {
    return { ok: false, error: { code: this.code, message: this.message, next: this.next } };
  }
}

export const badArgs = (message: string, next = "") => new BrandcalError("BAD_ARGS", message, next);

export const STATES = [
  "pending_approval", "changes_requested", "approved", "missed", "published", "cancelled",
] as const;
export const CLOSED = new Set(["published", "cancelled"]);
export const NEEDS_YOU = ["pending_approval", "changes_requested", "missed"];
export const POST_TYPES = [
  "text", "image", "carousel", "thread", "article", "reshare", "video", "comment",
];
export const TIME_FORMAT = "ISO 8601 with an explicit UTC offset, e.g. 2026-03-02T09:00:00+00:00";
export const TRANSITIONS: [string, string, string[]][] = [
  ["pending_approval", "approved", ["manager", "approver"]],
  ["pending_approval", "changes_requested", ["manager", "approver"]],
  ["changes_requested", "pending_approval", ["writer", "manager", "approver"]],
  ["approved", "pending_approval", ["system"]],
  ["missed", "pending_approval", ["system"]],
  ["approved", "published", ["manager"]],
  ["approved", "missed", ["system"]],
  ["missed", "approved", ["manager", "approver"]],
  ["pending_approval", "cancelled", ["manager", "writer", "approver"]],
  ["changes_requested", "cancelled", ["manager", "writer", "approver"]],
  ["approved", "cancelled", ["manager", "approver"]],
  ["missed", "cancelled", ["manager", "approver"]],
];

export function checkTransition(from: string, to: string, role: string): void {
  const row = TRANSITIONS.find(([f, t]) => f === from && t === to);
  if (!row) {
    throw new BrandcalError(
      "BAD_TRANSITION", `${from} -> ${to} is not an allowed status change`,
      "see the state machine in SPEC 6",
    );
  }
  if (!row[2].includes(role)) {
    throw new BrandcalError(
      "ROLE_NOT_ALLOWED", `role ${role} may not change ${from} -> ${to}`,
      `ask one of: ${row[2].join(", ")}`,
    );
  }
}

// --- time (timefmt.py) ----------------------------------------------------------------------

/** A display timezone: a fixed offset in minutes, or an IANA name. */
export type Tz = { fixed: number } | { iana: string };

const OFFSET = /^([+-])(\d{2}):(\d{2})$/;
const TIME = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}(?::\d{2})?)(Z|[+-]\d{2}:\d{2})?$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function offsetMinutes(value: string): number | null {
  if (value === "Z") return 0;
  const m = OFFSET.exec(value);
  if (!m || Number(m[2]) > 23 || Number(m[3]) > 59) return null;
  const mins = Number(m[2]) * 60 + Number(m[3]);
  return m[1] === "-" ? -mins : mins;
}

export function resolveTz(value: unknown): Tz {
  if (typeof value !== "string") throw badArgs('"timezone" must be a string.');
  const v = value.trim();
  if (!v) {
    throw new BrandcalError(
      "TZ_NOT_CONFIGURED", "No display timezone is configured.",
      'Set "timezone" in config.json or BRANDCAL_TZ.',
    );
  }
  const fixed = offsetMinutes(v);
  if (fixed !== null) return { fixed };
  try {
    new Intl.DateTimeFormat("en-GB", { timeZone: v });
  } catch {
    throw badArgs(
      `Unknown timezone: ${pyRepr(v)}.`,
      "Use an IANA name such as Europe/London or an offset such as +03:00.",
    );
  }
  return { iana: v };
}

/** The tz's UTC offset in minutes at the instant ``ms``. */
export function tzOffset(tz: Tz, ms: number): number {
  if ("fixed" in tz) return tz.fixed;
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: tz.iana, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).formatToParts(new Date(ms));
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value);
  const local = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"),
    get("second"));
  return Math.round((local - Math.floor(ms / 1000) * 1000) / 60000);
}

const pad = (n: number, w = 2) => String(n).padStart(w, "0");

/** An instant with its local fields in a tz (seconds resolution). */
export interface Local { ms: number; offset: number; y: number; mo: number; d: number; h: number; mi: number; s: number }

export function toLocal(ms: number, tz: Tz): Local {
  const sec = Math.floor(ms / 1000) * 1000;
  const offset = tzOffset(tz, sec);
  const t = new Date(sec + offset * 60000);
  return {
    ms: sec, offset, y: t.getUTCFullYear(), mo: t.getUTCMonth() + 1, d: t.getUTCDate(),
    h: t.getUTCHours(), mi: t.getUTCMinutes(), s: t.getUTCSeconds(),
  };
}

function offsetText(mins: number): string {
  const sign = mins < 0 ? "-" : "+";
  const a = Math.abs(mins);
  return `${sign}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
}

/** YYYY-MM-DDTHH:MM:SS+HH:MM (never "Z"), like timefmt.format_time. */
export function formatLocal(l: Local): string {
  return `${l.y}-${pad(l.mo)}-${pad(l.d)}T${pad(l.h)}:${pad(l.mi)}:${pad(l.s)}${offsetText(l.offset)}`;
}

export const localDate = (l: Local) => `${l.y}-${pad(l.mo)}-${pad(l.d)}`;

export function nowText(tz: Tz, ms = Date.now()): { at: string; month: string } {
  const l = toLocal(ms, tz);
  return { at: formatLocal(l), month: `${l.y}-${pad(l.mo)}` };
}

function validCalendar(date: string, time: string): boolean {
  const [y, mo, d] = date.split("-").map(Number) as [number, number, number];
  const [h, mi, s = 0] = time.split(":").map(Number) as [number, number, number?];
  if (mo < 1 || mo > 12 || d < 1 || h > 23 || mi > 59 || (s ?? 0) > 59) return false;
  const days = new Date(Date.UTC(y, mo, 0)).getUTCDate();
  return d <= days && y >= 1;
}

/** Parse a time that carries an offset; the instant in ms. */
export function parseTime(text: string): number {
  const m = TIME.exec(text.trim());
  if (!m) {
    throw new BrandcalError(
      "BAD_TIME", `Cannot parse time: ${pyRepr(text)}.`, "Use YYYY-MM-DDTHH:MM:SS+HH:MM.",
    );
  }
  if (m[3] === undefined) {
    throw new BrandcalError(
      "TIME_OFFSET_REQUIRED", `Time has no UTC offset: ${pyRepr(text)}.`,
      "Add an offset such as +03:00 or Z.",
    );
  }
  const off = offsetMinutes(m[3]);
  if (off === null || !validCalendar(m[1]!, m[2]!)) {
    throw new BrandcalError("BAD_TIME", `Cannot parse time: ${pyRepr(text)}.`);
  }
  const [y, mo, d] = m[1]!.split("-").map(Number) as [number, number, number];
  const [h, mi, s = 0] = m[2]!.split(":").map(Number) as [number, number, number?];
  return Date.UTC(y, mo - 1, d, h, mi, s ?? 0) - off * 60000;
}

export function normaliseTime(text: string, tz: Tz): string {
  return formatLocal(toLocal(parseTime(text), tz));
}

export function normaliseWindow(text: string, tz: Tz): string {
  const parts = text.split("/");
  if (parts.length !== 2) {
    throw new BrandcalError("BAD_WINDOW", `Window must be START/END: ${pyRepr(text)}.`, "Use START/END.");
  }
  const start = toLocal(parseTime(parts[0]!), tz);
  const end = toLocal(parseTime(parts[1]!), tz);
  if (end.ms <= start.ms) throw new BrandcalError("BAD_WINDOW", "Window end must be after its start.");
  if (localDate(start) !== localDate(end)) {
    throw new BrandcalError(
      "BAD_WINDOW", "Window must fall within one local date in the display timezone.",
    );
  }
  return `${formatLocal(start)}/${formatLocal(end)}`;
}

export function parseDate(text: string): string {
  const t = text.trim();
  if (DATE.test(t) && validCalendar(t, "00:00")) return t;
  throw new BrandcalError("BAD_TIME", `Cannot parse date: ${pyRepr(text)}.`, "Use YYYY-MM-DD.");
}

/** SQLite datetime() text ("YYYY-MM-DD HH:MM:SS", UTC) to ms. */
export const sqliteUtc = (text: string) => Date.parse(`${text.replace(" ", "T")}Z`);

export function utcText(ms: number): string {
  const t = new Date(Math.floor(ms / 1000) * 1000);
  return `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())} ${pad(t.getUTCHours())}:${pad(t.getUTCMinutes())}:${pad(t.getUTCSeconds())}`;
}

// --- Python-identical text ------------------------------------------------------------------

/** repr() of a str, as Python prints it in messages (simple cases: quotes and backslashes). */
export function pyRepr(s: string): string {
  const q = s.includes("'") && !s.includes('"') ? '"' : "'";
  let out = "";
  for (const ch of s) {
    const c = ch.codePointAt(0)!;
    if (ch === "\\") out += "\\\\";
    else if (ch === q) out += `\\${q}`;
    else if (ch === "\n") out += "\\n";
    else if (ch === "\r") out += "\\r";
    else if (ch === "\t") out += "\\t";
    else if (c < 0x20 || c === 0x7f) out += `\\x${c.toString(16).padStart(2, "0")}`;
    else out += ch;
  }
  return q + out + q;
}

type Json = null | boolean | number | string | Json[] | { [k: string]: Json };

/** json.dumps(value, sort_keys=True) with Python's defaults (", ", ": ", ensure_ascii). */
export function pyDumps(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("non-finite number");
    return Number.isInteger(value) ? String(value) : JSON.stringify(value);
  }
  if (typeof value === "string") {
    return JSON.stringify(value).replace(/[^\x20-\x7e]/g, (c) =>
      `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);
  }
  if (Array.isArray(value)) return `[${value.map(pyDumps).join(", ")}]`;
  const obj = value as Record<string, Json>;
  const keys = Object.keys(obj).filter((k) => obj[k] !== undefined).sort();
  return `{${keys.map((k) => `${pyDumps(k)}: ${pyDumps(obj[k])}`).join(", ")}}`;
}

/** json.dumps(value, ensure_ascii=False, separators=(",", ":")) for a flat list. */
export const compactDumps = (value: (string | null)[]) => JSON.stringify(value);

export async function sha256Hex(text: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** events.row_hash: SHA-256 of the canonical JSON array of the row's fields. */
export function rowHash(
  prev: string | null, at: string, actor: string, postId: string | null, action: string,
  from: string | null, to: string | null, detail: string | null, reason: string | null,
  chain: string,
): Promise<string> {
  return sha256Hex(compactDumps([prev, at, actor, postId, action, from, to, detail, reason, chain]));
}

/** content._q: the JSON string form of a value ("" for null). */
const q = (v: unknown) => JSON.stringify(v === null || v === undefined ? "" : String(v));

export interface PostRow { [k: string]: unknown; id: string }
export interface PartRow { id: number; post_id: string; pos: number; text: string; [k: string]: unknown }
export interface MediaRow { id: string; part_id: number; pos: number; kind: string; sha256: string; alt_text: string; [k: string]: unknown }

/** content.canonical_form. */
export function canonicalForm(post: PostRow, parts: PartRow[], media: MediaRow[]): string {
  const lines = [
    "v1",
    `platform=${String(post.platform)}`,
    `post_type=${String(post.post_type)}`,
    `target_url=${q(post.target_url)}`,
    `first_comment=${q(post.first_comment)}`,
  ];
  for (const part of [...parts].sort((a, b) => a.pos - b.pos)) {
    lines.push(`part=${part.pos}`, `text=${q(part.text)}`);
    for (const m of media.filter((x) => x.part_id === part.id).sort((a, b) => a.pos - b.pos)) {
      lines.push(`media=${m.pos}:${m.sha256}:${q(m.alt_text)}`);
    }
  }
  return lines.join("\n");
}

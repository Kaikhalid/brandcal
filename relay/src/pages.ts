// Everything the Worker and the Durable Object say themselves: the time format, the log line, and
// the self-contained error pages (HTML for browsers, brandcal's JSON error shape for /api/*).

export const OFFLINE_TEXT =
  "The calendar server is not connected right now. Nothing has been lost: approvals and edits already made are saved.";
export const OFFLINE_NEXT =
  "Try again in a few minutes; if this lasts, the box or `brandcal relay` is down.";
export const DROPPED_WRITE =
  "The connection to the calendar dropped. Your change may or may not have been saved: reload to check before trying again.";
export const DROPPED_READ = "The connection to the calendar dropped. Reload the page to try again.";

// -- time: the offset comes from configuration; the repo has no timezone default ----------------

const OFFSET = /^([+-])(0\d|1\d|2[0-3]):([0-5]\d)$/;

/** Minutes east of UTC for "+03:00"-style text, or null if it is missing or malformed. */
export function parseOffset(text: string | undefined): number | null {
  const m = typeof text === "string" ? OFFSET.exec(text) : null;
  if (!m) return null;
  const minutes = Number(m[2]) * 60 + Number(m[3]);
  return m[1] === "-" ? -minutes : minutes;
}

/** ISO 8601 with the configured offset, never "Z": 2026-10-24T09:15:02+03:00. */
export function formatTime(epochMs: number, offset: string): string {
  const minutes = parseOffset(offset);
  if (minutes === null) throw new Error("formatTime needs a validated offset");
  const local = new Date(epochMs + minutes * 60_000).toISOString();
  return `${local.slice(0, 19)}${offset}`;
}

export interface LogFields {
  stream: number | string;
  method: string;
  path: string;
  status: number;
  ms: number;
  bytes: number;
  outcome: string;
}

/** One line per event. Never a header value, body, query string, JWT, secret, cookie, email or IP. */
export function logEvent(offset: string, f: LogFields): void {
  const path = f.path.split("?", 1)[0]!.slice(0, 200);
  console.log(
    `${formatTime(Date.now(), offset)} stream=${f.stream} method=${f.method} path=${path}` +
      ` status=${f.status} ms=${f.ms} bytes=${f.bytes} outcome=${f.outcome}`,
  );
}

/** A line for connection events (connect, disconnect): the same prefix, then plain fields. */
export function logConnection(offset: string, text: string): void {
  console.log(`${formatTime(Date.now(), offset)} ${text}`);
}

// -- pages -------------------------------------------------------------------------------------

const STYLE =
  "body{margin:0;padding:2rem 1rem;font:16px/1.5 system-ui,sans-serif;color:#1a1a1a;background:#fafafa}" +
  "main{max-width:34rem;margin:0 auto}h1{font-size:1.4rem;margin:0 0 1rem}p{margin:0 0 .75rem}" +
  ".code{color:#555;font-size:.85rem}";

let styleHash: Promise<string> | undefined;

/** base64 SHA-256 of the one inline style, for the Content-Security-Policy. */
export function hashOfStyle(): Promise<string> {
  styleHash ??= crypto.subtle
    .digest("SHA-256", new TextEncoder().encode(STYLE))
    .then((d) => btoa(String.fromCharCode(...new Uint8Array(d))));
  return styleHash;
}

export interface Problem {
  status: number;
  code: string;
  title: string;
  message: string;
  next: string;
  /** An extra line shown on the page and appended to the JSON message, such as "Last connected…". */
  detail?: string;
  headers?: Record<string, string>;
}

const escapeHtml = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export const isApi = (path: string) => path.startsWith("/api/");

/** A self-made response: JSON for /api/*, otherwise a page with no script, font or image. */
export async function problem(path: string, p: Problem): Promise<Response> {
  const headers = new Headers(p.headers);
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("Cache-Control", "no-store");
  headers.set("Referrer-Policy", "no-referrer");
  headers.set(
    "Content-Security-Policy",
    `default-src 'none'; style-src 'sha256-${await hashOfStyle()}'`,
  );
  if (isApi(path)) {
    headers.set("Content-Type", "application/json; charset=utf-8");
    const message = p.detail ? `${p.message} ${p.detail}` : p.message;
    const body = { ok: false, error: { code: p.code, message, next: p.next } };
    return new Response(JSON.stringify(body), { status: p.status, headers });
  }
  headers.set("Content-Type", "text/html; charset=utf-8");
  const detail = p.detail ? `<p>${escapeHtml(p.detail)}</p>` : "";
  const html =
    `<!doctype html><html lang="en-GB"><head><meta charset="utf-8">` +
    `<meta name="viewport" content="width=device-width,initial-scale=1">` +
    `<title>${escapeHtml(p.title)}</title><style>${STYLE}</style></head><body><main>` +
    `<h1>${escapeHtml(p.title)}</h1><p>${escapeHtml(`${p.message} ${p.next}`)}</p>${detail}` +
    `<p class="code">${escapeHtml(p.code)}</p></main></body></html>`;
  return new Response(html, { status: p.status, headers });
}

export const PROBLEMS = {
  misconfigured: {
    status: 500,
    code: "RELAY_MISCONFIGURED",
    title: "brandcal relay is not set up",
    message: "The relay has no valid display time offset, so it refuses every request.",
    next: "Set DISPLAY_UTC_OFFSET in the Worker configuration, for example +03:00, and deploy again.",
  },
  notFound: {
    status: 404,
    code: "RELAY_NOT_FOUND",
    title: "Not found",
    message: "There is nothing at this address.",
    next: "Check the address.",
  },
  badRequest: {
    status: 400,
    code: "RELAY_BAD_REQUEST",
    title: "Bad request",
    message: "The relay does not accept this kind of request.",
    next: "Use an ordinary GET or POST request.",
  },
  method: {
    status: 405,
    code: "RELAY_METHOD_NOT_ALLOWED",
    title: "Method not allowed",
    message: "Only GET and POST are allowed.",
    next: "Use GET or POST.",
    headers: { Allow: "GET, POST" },
  },
  unauthenticated: {
    status: 401,
    code: "RELAY_UNAUTHENTICATED",
    title: "Sign in again",
    message: "The request does not carry a valid Cloudflare Access sign-in.",
    next: "Sign in again, then reload the page.",
  },
  requestTooLarge: {
    status: 413,
    code: "RELAY_REQUEST_TOO_LARGE",
    title: "Request too large",
    message: "The request is larger than the relay accepts (1 MiB).",
    next: "Send less data.",
  },
  offline: {
    status: 503,
    code: "RELAY_OFFLINE",
    title: "brandcal is offline",
    message: OFFLINE_TEXT,
    next: OFFLINE_NEXT,
    headers: { "Retry-After": "30" },
  },
  busy: {
    status: 503,
    code: "RELAY_BUSY",
    title: "brandcal is busy",
    message: "The relay already has 16 requests in flight.",
    next: "Try again in a few seconds.",
    headers: { "Retry-After": "5" },
  },
  upstreamDown: {
    status: 502,
    code: "RELAY_UPSTREAM_DOWN",
    title: "brandcal serve is not running",
    message: "brandcal serve is not running.",
    next: "Start `brandcal serve` on the box, then reload.",
  },
  timeout: {
    status: 504,
    code: "RELAY_TIMEOUT",
    title: "The calendar took too long",
    message: "The calendar server did not answer in time.",
    next: "Reload to try again. If a change was in progress, check it before repeating it.",
  },
  tooLarge: {
    status: 502,
    code: "RELAY_TOO_LARGE",
    title: "The response is too large",
    message: "The calendar's answer is larger than the relay passes on (32 MiB).",
    next: "Ask for something smaller.",
  },
  badFrame: {
    status: 502,
    code: "RELAY_BAD_FRAME",
    title: "The relay got a bad answer",
    message: "The connector sent something the relay could not use.",
    next: "Reload to try again. If this repeats, restart `brandcal relay`.",
  },
  droppedWrite: {
    status: 502,
    code: "RELAY_DROPPED",
    title: "The connection dropped",
    message: DROPPED_WRITE,
    next: "Reload the page and check before trying again.",
  },
  droppedRead: {
    status: 502,
    code: "RELAY_DROPPED",
    title: "The connection dropped",
    message: DROPPED_READ,
    next: "Reload the page.",
  },
} satisfies Record<string, Problem>;

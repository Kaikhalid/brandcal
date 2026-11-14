// Cloudflare Access identity (identity.py, serve.App.session and csrf), ported for the Worker.
// Access already gates the hostname; this is the second check, as in brandcal serve: the
// Cf-Access-Jwt-Assertion is verified (RS256, team keys, exact audience, issuer, expiry) and the
// email is mapped to approver or viewer. A service-token JWT (no email, a common_name) maps to the
// agents' sync access only when its client id is listed in serve.service_tokens.

import { BrandcalError } from "./core";

export const CONSOLE_SOURCE = "access-jwt";
export const SERVICE_SOURCE = "service-token";
const LEEWAY = 60;
const MIN_KEY_BITS = 2048;

export interface Session {
  email: string | null;
  role: "approver" | "viewer" | "service";
  agent: string | null;
  source: string;
}

export type Serve = Record<string, unknown>;

const unverified = (reason: string) => new BrandcalError(
  "IDENTITY_UNVERIFIED", reason,
  "Sign in through Cloudflare Access, or ask the admin to check serve.identity.",
);

function b64url(text: string): Uint8Array {
  const norm = text.replace(/-/g, "+").replace(/_/g, "/");
  let bin: string;
  try {
    bin = atob(norm + "=".repeat((4 - (norm.length % 4)) % 4));
  } catch {
    throw unverified("The token is not a well-formed JWT.");
  }
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

function jsonPart(text: string): Record<string, unknown> {
  try {
    const data: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(b64url(text)));
    if (data && typeof data === "object" && !Array.isArray(data)) return data as Record<string, unknown>;
  } catch (e) {
    if (e instanceof BrandcalError) throw e;
  }
  throw unverified("The token is not a well-formed JWT.");
}

type Jwk = { kid: string; kty?: string; n?: string; e?: string };
interface KeyCache { url: string; at: number; keys: Map<string, Jwk> }
let cache: KeyCache | null = null;

/** Fetch the team's keys (test hook: ``fetcher``). */
export type Fetcher = (url: string) => Promise<unknown>;
const defaultFetch: Fetcher = async (url) => {
  const res = await fetch(url, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`status ${res.status}`);
  return res.json();
};

async function loadKeys(url: string, fetcher: Fetcher): Promise<Map<string, Jwk>> {
  try {
    const data = (await fetcher(url)) as { keys?: unknown };
    const keys = new Map<string, Jwk>();
    for (const k of Array.isArray(data.keys) ? data.keys : []) {
      if (k && typeof k === "object" && typeof (k as Jwk).kid === "string") keys.set((k as Jwk).kid, k as Jwk);
    }
    return keys;
  } catch {
    throw unverified("The Access signing keys could not be loaded.");
  }
}

async function keyFor(url: string, kid: string, ttlMs: number, fetcher: Fetcher): Promise<Jwk> {
  const now = Date.now();
  let fetched = false;
  if (!cache || cache.url !== url || now - cache.at >= ttlMs) {
    cache = { url, at: now, keys: await loadKeys(url, fetcher) };
    fetched = true;
  }
  if (!cache.keys.has(kid) && !fetched) cache = { url, at: now, keys: await loadKeys(url, fetcher) };
  const key = cache.keys.get(kid);
  if (!key) throw unverified("The token was signed with an unknown key.");
  return key;
}

export function resetKeyCache(): void {
  cache = null;
}

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);

export interface Claims { email: string | null; commonName: string | null }

/** Verify a token; the email (people) or common_name (service tokens) it carries. */
export async function verify(
  token: string | null, identity: Record<string, unknown>, fetcher: Fetcher = defaultFetch,
  certsUrl?: string,
): Promise<Claims> {
  if (token === null || !token.trim()) throw unverified("No Access token came with this request.");
  const parts = token.trim().split(".");
  if (parts.length !== 3) throw unverified("The token is not a well-formed JWT.");
  const header = jsonPart(parts[0]!);
  const payload = jsonPart(parts[1]!);
  if (header.alg !== "RS256") throw unverified("The token does not use RS256.");
  const kid = header.kid;
  if (typeof kid !== "string" || !kid) throw unverified("The token names no signing key.");
  const team = String(identity.team_domain ?? "");
  const audience = String(identity.audience ?? "");
  if (!team || !audience) throw unverified("serve.identity is not configured.");
  const issuer = `https://${team}`;
  const url = certsUrl ?? `${issuer}/cdn-cgi/access/certs`;
  const ttl = Number(identity.jwks_cache_minutes ?? 60) * 60000;
  const jwk = await keyFor(url, kid, ttl, fetcher);
  let key: CryptoKey;
  try {
    if (jwk.kty !== "RSA" || !jwk.n || !jwk.e) throw new Error("not RSA");
    if (b64url(jwk.n).length * 8 < MIN_KEY_BITS) throw new Error("small");
    key = await crypto.subtle.importKey(
      "jwk", { kty: "RSA", n: jwk.n, e: jwk.e, alg: "RS256", ext: true },
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"],
    );
  } catch {
    throw unverified("The Access signing key is not usable.");
  }
  const ok = await crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5", key, b64url(parts[2]!), new TextEncoder().encode(`${parts[0]}.${parts[1]}`),
  );
  if (!ok) throw unverified("The token signature is not valid.");
  const aud = payload.aud;
  const audOk = aud === audience || (Array.isArray(aud) && aud.length === 1 && aud[0] === audience);
  if (!audOk) throw unverified("The token is for a different application.");
  if (payload.iss !== issuer) throw unverified("The token was issued by a different team.");
  const now = Date.now() / 1000;
  const exp = num(payload.exp);
  if (exp === null) throw unverified("The token has no expiry.");
  if (now > exp + LEEWAY) throw unverified("The token has expired.");
  if (payload.nbf !== undefined && payload.nbf !== null) {
    const nbf = num(payload.nbf);
    if (nbf === null || now < nbf - LEEWAY) throw unverified("The token is not valid yet.");
  }
  const email = typeof payload.email === "string" && payload.email.trim() ? payload.email.trim() : null;
  const cn = typeof payload.common_name === "string" && payload.common_name.trim()
    ? payload.common_name.trim() : null;
  if (!email && !cn) throw unverified("The token carries no email.");
  return { email, commonName: email ? null : cn };
}

/** identity.resolve plus service tokens. */
export function resolve(serve: Serve, claims: Claims): Session {
  if (claims.email) {
    const key = claims.email.trim().toLowerCase();
    const approvers = (serve.approvers ?? {}) as Record<string, unknown>;
    for (const [listed, agent] of Object.entries(approvers)) {
      if (listed.trim().toLowerCase() === key) {
        return { email: key, role: "approver", agent: String(agent), source: CONSOLE_SOURCE };
      }
    }
    const viewers = Array.isArray(serve.viewers) ? serve.viewers : [];
    if (viewers.some((v) => String(v).trim().toLowerCase() === key)) {
      return { email: key, role: "viewer", agent: null, source: CONSOLE_SOURCE };
    }
    throw new BrandcalError(
      "IDENTITY_UNMAPPED", "Your identity is verified, but it is not listed for this calendar.",
      "Ask the admin to add it to serve.approvers or serve.viewers.",
    );
  }
  const tokens = Array.isArray(serve.service_tokens) ? serve.service_tokens.map(String) : [];
  if (claims.commonName && tokens.includes(claims.commonName)) {
    return { email: null, role: "service", agent: null, source: SERVICE_SOURCE };
  }
  throw unverified("The token carries no email.");
}

async function hmacHex(secret: string, msg: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(msg));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** A token bound to the identity; only people get one. */
export async function csrf(secret: string, session: Session): Promise<string | null> {
  if (session.email === null) return null;
  return hmacHex(secret, `${session.email}|${session.source}`);
}

export function sameText(a: string, b: string): boolean {
  const x = new TextEncoder().encode(a);
  const y = new TextEncoder().encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

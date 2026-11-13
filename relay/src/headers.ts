// The two header allow-lists (spec 6). Anything not named here is dropped, in both directions.

import type { HeaderPairs } from "./protocol";

// Cookie, Authorization, Cf-Access-Authenticated-User-Email, Cf-Connecting-IP, Forwarded,
// X-Forwarded-* and every hop-by-hop header are absent on purpose: brandcal trusts only the JWT.
const FORWARDED: ReadonlyArray<readonly [string, string]> = [
  ["cf-access-jwt-assertion", "Cf-Access-Jwt-Assertion"],
  ["origin", "Origin"],
  ["content-type", "Content-Type"],
  ["accept", "Accept"],
  ["x-brandcal-csrf", "X-Brandcal-CSRF"],
];

export const RESPONSE_HEADERS: ReadonlySet<string> = new Set([
  "content-type",
  "content-length",
  "content-security-policy",
  "x-content-type-options",
  "referrer-policy",
  "cache-control",
  "location",
  "allow",
  "x-brandcal-exit",
]);

/** Host (the configured public host, never the client's) first, then the allow-listed headers. */
export function requestHeaders(from: Headers, publicHost: string): HeaderPairs {
  const out: HeaderPairs = [["Host", publicHost]];
  for (const [lower, canonical] of FORWARDED) {
    const value = from.get(lower);
    if (value !== null) out.push([canonical, value]);
  }
  return out;
}

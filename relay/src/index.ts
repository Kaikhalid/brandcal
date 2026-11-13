// The Worker: routes by Host (spec 3 and 6), checks the request, and hands it to the Durable Object.
// The Worker does not verify the JWT signature (spec 3b); brandcal serve does.

import { requestHeaders } from "./headers";
import { PROBLEMS, type Problem, formatTime, logEvent, parseOffset, problem } from "./pages";
import { MAX_FRAME } from "./protocol";

export { Relay } from "./relay_do";

type Env = Cloudflare.Env;

const MAX_BODY = MAX_FRAME; // 1 MiB; brandcal enforces its own, smaller, limit
const MAX_JWT = 16 * 1024;
const JWT_SHAPE = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;
const isUpgrade = (r: Request) => r.headers.get("Upgrade")?.toLowerCase() === "websocket";

/** Read the body up to the limit; null if it is larger. */
async function readBody(request: Request): Promise<Uint8Array | null> {
  const declared = request.headers.get("Content-Length");
  if (declared !== null && Number(declared) > MAX_BODY) return null;
  if (!request.body) return new Uint8Array();
  const reader = request.body.getReader();
  const parts: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.length;
    if (size > MAX_BODY) {
      await reader.cancel();
      return null;
    }
    parts.push(value);
  }
  const body = new Uint8Array(size);
  let at = 0;
  for (const part of parts) {
    body.set(part, at);
    at += part.length;
  }
  return body;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const began = Date.now();
    const url = new URL(request.url);
    const offset = env.DISPLAY_UTC_OFFSET;
    const refuse = async (p: Problem, outcome: string) => {
      if (offset !== undefined && parseOffset(offset) !== null) {
        logEvent(offset, {
          stream: "-",
          method: request.method,
          path: url.pathname,
          status: p.status,
          ms: Date.now() - began,
          bytes: 0,
          outcome,
        });
      }
      return problem(url.pathname, p);
    };

    // Fail closed: without a valid offset no timestamp can be written, so nothing is served.
    if (parseOffset(offset) === null) return refuse(PROBLEMS.misconfigured, "misconfigured");

    const host = url.host.toLowerCase();
    const stub = env.RELAY.getByName("relay");

    if (host === env.RELAY_HOST.toLowerCase()) {
      const connect =
        request.method === "GET" && url.pathname === "/_relay/connect" && isUpgrade(request);
      return connect ? stub.fetch(request) : refuse(PROBLEMS.notFound, "not_found");
    }
    if (host !== env.PUBLIC_HOST.toLowerCase()) return refuse(PROBLEMS.notFound, "unknown_host");

    // The browser host.
    if (request.method !== "GET" && request.method !== "POST") {
      return refuse(PROBLEMS.method, "method_not_allowed");
    }
    const health = url.pathname === "/_relay/health";
    if (url.pathname.startsWith("/_relay/") && !health) return refuse(PROBLEMS.notFound, "not_found");
    if (isUpgrade(request)) return refuse(PROBLEMS.badRequest, "upgrade_refused");

    const jwt = request.headers.get("Cf-Access-Jwt-Assertion");
    if (jwt === null || jwt.length > MAX_JWT || !JWT_SHAPE.test(jwt)) {
      return refuse(PROBLEMS.unauthenticated, "no_jwt");
    }

    if (health) {
      const s = await stub.status();
      const body = {
        ok: true,
        connected: s.connected,
        connected_since: s.connectedSince === null ? null : formatTime(s.connectedSince, offset!),
        last_pong_age_s: s.lastPongAgeS,
        agent: s.agent,
        in_flight: s.inFlight,
      };
      return new Response(JSON.stringify(body), {
        status: s.connected ? 200 : 503,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Cache-Control": "no-store",
          "X-Content-Type-Options": "nosniff",
          "Referrer-Policy": "no-referrer",
        },
      });
    }

    const body = await readBody(request);
    if (body === null) return refuse(PROBLEMS.requestTooLarge, "request_too_large");

    // Only the allow-listed headers travel on; Host is the configured public host.
    const forwarded = new Headers();
    for (const [name, value] of requestHeaders(request.headers, env.PUBLIC_HOST)) {
      if (name !== "Host") forwarded.set(name, value);
    }
    const inner = new Request(`https://${env.PUBLIC_HOST}${url.pathname}${url.search}`, {
      method: request.method,
      headers: forwarded,
      redirect: "manual", // a 308 from brandcal goes to the browser; the Worker must not follow it
      body: request.method === "POST" ? body : undefined,
    });
    return stub.fetch(inner);
  },
} satisfies ExportedHandler<Env>;

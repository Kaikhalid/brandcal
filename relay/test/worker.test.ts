import { SELF, env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import worker from "../src/index";
import { T, decodeReq } from "../src/protocol";
import { COOKIE, Fake, JWT, PUBLIC, RELAY, SPOOFED_EMAIL, browser, logs, useHarness, utf8 } from "./support";

useHarness();

const get = (path: string, init: RequestInit = {}, host = PUBLIC) => browser(path, init, host);

async function sha256b64(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", utf8(text));
  return btoa(String.fromCharCode(...new Uint8Array(digest)));
}

describe("host routing", () => {
  it("answers 404 on an unknown host", async () => {
    const res = await get("/", {}, "other.example.com");
    expect(res.status).toBe(404);
  });

  it("serves the connector path on the relay host only", async () => {
    const fake = await Fake.open(RELAY);
    expect(fake.ws).toBeTruthy();
  });

  it("404s everything but GET /_relay/connect with Upgrade on the relay host", async () => {
    for (const [path, init] of [
      ["/", {}],
      ["/_relay/connect", {}],
      ["/_relay/connect", { method: "POST" }],
      ["/_relay/health", {}],
      ["/api/session", {}],
    ] as Array<[string, RequestInit]>) {
      const res = await get(path, init, RELAY);
      expect(res.status, `${init.method ?? "GET"} ${path}`).toBe(404);
    }
  });

  it("never serves /_relay/connect on the browser host", async () => {
    for (const init of [{}, { headers: { Upgrade: "websocket" } }]) {
      const res = await get("/_relay/connect", init);
      expect(res.status).toBe(404);
    }
  });

  it("404s any other /_relay/ path on the browser host without forwarding it", async () => {
    const fake = await Fake.ready();
    for (const path of ["/_relay/other", "/_relay/", "/_relay/health/x", "/_relay/connect/"]) {
      expect((await get(path)).status, path).toBe(404);
    }
    expect(await fake.quiet()).toBe(true);
  });

  it("answers 400 to a WebSocket upgrade on the browser host", async () => {
    const res = await get("/ws", { headers: { Upgrade: "websocket" } });
    expect(res.status).toBe(400);
  });
});

describe("browser host request checks", () => {
  it("allows only GET and POST (405 with Allow)", async () => {
    for (const method of ["PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]) {
      const res = await get("/api/session", { method });
      expect(res.status, method).toBe(405);
      expect(res.headers.get("Allow")).toBe("GET, POST");
    }
  });

  it("refuses a missing Cf-Access-Jwt-Assertion with 401 HTML and does not forward", async () => {
    const fake = await Fake.ready();
    const empty = await get("/", { headers: { "Cf-Access-Jwt-Assertion": "" } });
    const missing = await SELF.fetch(`https://${PUBLIC}/`);
    expect(empty.status).toBe(401);
    expect(missing.status).toBe(401);
    expect(missing.headers.get("Content-Type")).toContain("text/html");
    expect(await fake.quiet()).toBe(true);
  });

  it("answers /api/ refusals with brandcal's JSON error shape and no X-Brandcal-Exit", async () => {
    const res = await get("/api/session", { headers: { "Cf-Access-Jwt-Assertion": "not-a-jwt" } });
    expect(res.status).toBe(401);
    expect(res.headers.get("X-Brandcal-Exit")).toBeNull();
    expect(res.headers.get("Content-Type")).toContain("application/json");
    const body = (await res.json()) as { ok: boolean; error: Record<string, string> };
    expect(body.ok).toBe(false);
    expect(Object.keys(body.error).sort()).toEqual(["code", "message", "next"]);
    expect(body.error.code).toBe("RELAY_UNAUTHENTICATED");
  });

  it.each([
    ["two segments", "aaa.bbb"],
    ["four segments", "a.b.c.d"],
    ["an empty segment", "a..c"],
    ["characters outside base64url", "a+b.c/d.e=f"],
    ["a comma-joined duplicate", `${JWT}, ${JWT}`],
    ["a segment over the size limit", `a.${"b".repeat(16 * 1024)}.c`],
  ])("refuses a JWT header with %s", async (_name, value) => {
    const res = await get("/api/session", { headers: { "Cf-Access-Jwt-Assertion": value } });
    expect(res.status).toBe(401);
  });

  it("accepts a JWT header of exactly 16 KiB", async () => {
    const pad = 16 * 1024 - 4;
    const res = await get("/api/session", {
      headers: { "Cf-Access-Jwt-Assertion": `a.${"b".repeat(pad)}.c` },
    });
    expect(res.status).toBe(503); // past the check: the connector is simply not there
  });

  it("answers 413 for a body over 1 MiB before the Durable Object", async () => {
    const fake = await Fake.ready();
    const big = new Uint8Array(1024 * 1024 + 1);
    const res = await get("/api/x", { method: "POST", body: big });
    expect(res.status).toBe(413);
    const json = (await res.json()) as { error: { code: string } };
    expect(json.error.code).toBe("RELAY_REQUEST_TOO_LARGE");
    expect(await fake.quiet()).toBe(true);
  });

  it("answers 413 when the encoded REQ frame would pass 1 MiB", async () => {
    const fake = await Fake.ready();
    const res = await get("/api/x", { method: "POST", body: new Uint8Array(1024 * 1024) });
    expect(res.status).toBe(413);
    expect(await fake.quiet()).toBe(true);
  });
});

describe("request header allow-list", () => {
  it("forwards only the allow-listed headers, with Host set to the public host", async () => {
    const fake = await Fake.ready();
    const pending = get("/api/posts?x=1", {
      method: "POST",
      body: '{"a":1}',
      headers: {
        Origin: `https://${PUBLIC}`,
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-Brandcal-CSRF": "csrf-token-fake",
        Cookie: COOKIE,
        Authorization: "Bearer fake",
        "Cf-Access-Authenticated-User-Email": SPOOFED_EMAIL,
        "Cf-Connecting-IP": "203.0.113.9",
        "X-Forwarded-For": "203.0.113.9",
        Forwarded: "for=203.0.113.9",
        "X-Custom": "nope",
      },
    });
    const frame = await fake.nextOf(T.REQ);
    const req = decodeReq(frame.payload);
    expect(req.m).toBe("POST");
    expect(req.p).toBe("/api/posts?x=1");
    expect(new TextDecoder().decode(req.body)).toBe('{"a":1}');
    const names = req.h.map(([k]) => k.toLowerCase()).sort();
    expect(names).toEqual(
      ["accept", "cf-access-jwt-assertion", "content-type", "host", "origin", "x-brandcal-csrf"].sort(),
    );
    const byName = Object.fromEntries(req.h.map(([k, v]) => [k.toLowerCase(), v]));
    expect(byName["host"]).toBe(env.PUBLIC_HOST);
    expect(byName["cf-access-jwt-assertion"]).toBe(JWT);
    expect(JSON.stringify(req.h)).not.toContain(SPOOFED_EMAIL);
    expect(JSON.stringify(req.h)).not.toContain("fake-cookie-value");
    fake.respond(frame.stream, 200, [["Content-Type", "text/plain"]], [utf8("ok")]);
    expect((await pending).status).toBe(200);
  });

  it("never copies Host from the client", async () => {
    const fake = await Fake.ready();
    const pending = get("/", { headers: { Host: "evil.example.com" } });
    const frame = await fake.nextOf(T.REQ);
    const hosts = decodeReq(frame.payload).h.filter(([k]) => k.toLowerCase() === "host");
    expect(hosts).toEqual([[expect.any(String), env.PUBLIC_HOST]]);
    fake.respond(frame.stream, 204, []);
    await pending;
  });
});

describe("response header allow-list", () => {
  it("keeps only the allow-listed headers and passes the status through", async () => {
    const fake = await Fake.ready();
    const pending = get("/mvp", { redirect: "manual" });
    const frame = await fake.nextOf(T.REQ);
    fake.respond(
      frame.stream,
      308,
      [
        ["Location", "/mvp/"],
        ["Content-Type", "text/html; charset=utf-8"],
        ["Content-Security-Policy", "default-src 'self'"],
        ["X-Content-Type-Options", "nosniff"],
        ["Referrer-Policy", "no-referrer"],
        ["Cache-Control", "no-store"],
        ["Allow", "GET, POST"],
        ["X-Brandcal-Exit", "0"],
        ["Set-Cookie", "session=fake-value"],
        ["Server", "fake-server"],
        ["X-Powered-By", "fake"],
        ["Access-Control-Allow-Origin", "*"],
        ["Transfer-Encoding", "chunked"],
      ],
      [],
    );
    const res = await pending;
    expect(res.status).toBe(308);
    expect(res.headers.get("Location")).toBe("/mvp/");
    expect(res.headers.get("Content-Security-Policy")).toBe("default-src 'self'");
    expect(res.headers.get("X-Brandcal-Exit")).toBe("0");
    expect(res.headers.get("Allow")).toBe("GET, POST");
    for (const dropped of ["Set-Cookie", "Server", "X-Powered-By", "Access-Control-Allow-Origin"]) {
      expect(res.headers.get(dropped), dropped).toBeNull();
    }
  });
});

describe("DISPLAY_UTC_OFFSET", () => {
  it.each([[undefined], [""], ["Z"], ["+0300"], ["+3"], ["+03:60"], ["+24:00"], ["UTC+3"], [" +03:00"]])(
    "fails closed with 500 RELAY_MISCONFIGURED for %j",
    async (offset) => {
      for (const [host, path] of [
        [PUBLIC, "/api/session"],
        [PUBLIC, "/"],
        [PUBLIC, "/_relay/health"],
        [RELAY, "/_relay/connect"],
        ["other.example.com", "/"],
      ]) {
        const req = new Request(`https://${host}${path}`, {
          headers: { "Cf-Access-Jwt-Assertion": JWT, Upgrade: "websocket" },
        });
        const res = await worker.fetch(req, { ...env, DISPLAY_UTC_OFFSET: offset });
        expect(res.status, `${host}${path}`).toBe(500);
        if (path?.startsWith("/api/")) {
          const body = (await res.json()) as { error: { code: string } };
          expect(body.error.code).toBe("RELAY_MISCONFIGURED");
        } else {
          expect(await res.text()).toContain("RELAY_MISCONFIGURED");
        }
      }
    },
  );

  it("accepts a valid offset", async () => {
    const req = new Request(`https://${PUBLIC}/`, { headers: { "Cf-Access-Jwt-Assertion": JWT } });
    const res = await worker.fetch(req, { ...env, DISPLAY_UTC_OFFSET: "-05:30" });
    expect(res.status).toBe(503);
  });
});

describe("self-made pages", () => {
  it("carry a CSP with the hash of their one inline style, plus the other hardening headers", async () => {
    const res = await get("/", { headers: { "Cf-Access-Jwt-Assertion": "bad" } });
    const html = await res.text();
    const style = /<style>([\s\S]*?)<\/style>/.exec(html);
    expect(style).not.toBeNull();
    expect(html.match(/<style/g)?.length).toBe(1);
    expect(html).not.toMatch(/<script|<img|<link|style="/i);
    const hash = await sha256b64(style![1]!);
    expect(res.headers.get("Content-Security-Policy")).toBe(
      `default-src 'none'; style-src 'sha256-${hash}'`,
    );
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    expect(res.headers.get("Referrer-Policy")).toBe("no-referrer");
  });

  it("are the same for every kind of page", async () => {
    const pages = [
      await get("/", { method: "PUT" }),
      await get("/", { headers: { "Cf-Access-Jwt-Assertion": "bad" } }),
      await get("/"), // offline
      await get("/_relay/nope"),
    ];
    const csps = new Set(pages.map((p) => p.headers.get("Content-Security-Policy")));
    expect(csps.size).toBe(1);
    for (const p of pages) {
      expect(p.headers.get("X-Content-Type-Options")).toBe("nosniff");
      expect(p.headers.get("Cache-Control")).toBe("no-store");
      expect(p.headers.get("Referrer-Policy")).toBe("no-referrer");
    }
  });
});

describe("logging", () => {
  it("never writes the JWT, the secret, a cookie, an email or an IP address", async () => {
    const fake = await Fake.ready();
    await get("/api/x", { method: "PUT" });
    await get("/api/y", { headers: { "Cf-Access-Jwt-Assertion": "bad" } });
    const pending = get("/secret-path?token=query-value-fake", {
      headers: {
        Cookie: COOKIE,
        "Cf-Access-Authenticated-User-Email": SPOOFED_EMAIL,
        "Cf-Connecting-IP": "203.0.113.9",
      },
    });
    const frame = await fake.nextOf(T.REQ);
    fake.respond(frame.stream, 200, [["Content-Type", "text/plain"]], [utf8("secret-body-text")]);
    await (await pending).text();
    await get("/_relay/health");
    fake.drop();
    await fake.waitClosed().catch(() => undefined);
    const all = logs.join("\n");
    expect(logs.length).toBeGreaterThan(3);
    for (const forbidden of [
      JWT,
      JWT.split(".")[1]!,
      "test-relay-secret-not-real",
      "fake-cookie-value",
      SPOOFED_EMAIL,
      "203.0.113.9",
      "query-value-fake",
      "secret-body-text",
      "csrf-token-fake",
    ]) {
      expect(all, forbidden).not.toContain(forbidden);
    }
    expect(all).toContain("/secret-path");
    expect(all).not.toMatch(/\d{4}-\d\d-\d\dT[\d:]+(Z|\+00:00)/);
    expect(all).toMatch(/\d{4}-\d\d-\d\dT[\d:]+\+03:00 /);
  });
});

import { SELF, runInDurableObject } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { MAX_FRAME, T, decodeJson, decodeReq, encode, encodeJson, encodeResHead } from "../src/protocol";
import config from "../wrangler.jsonc?raw";
import {
  Fake,
  PUBLIC,
  RELAY,
  browser,
  logs,
  setLastSeen,
  setLimits,
  stub,
  useHarness,
  utf8,
} from "./support";

useHarness();

const MESSAGE =
  "The connection to the calendar dropped. Your change may or may not have been saved: reload to check before trying again.";

type ApiError = { ok: boolean; error: { code: string; message: string; next: string } };

describe("connector handshake", () => {
  it("answers HELLO with a 32-byte CHALLENGE, then READY after a good PROOF", async () => {
    const fake = await Fake.open();
    fake.hello();
    expect((await fake.nextOf(T.CHALLENGE)).payload.length).toBe(32);
    fake.ws.close(1000);
  });

  it("selects the subprotocol brandcal-relay.v1 and refuses a client that does not offer it", async () => {
    const res = await SELF.fetch(`https://${RELAY}/_relay/connect`, {
      headers: { Upgrade: "websocket", "Sec-WebSocket-Protocol": "brandcal-relay.v1" },
    });
    expect(res.status).toBe(101);
    expect(res.headers.get("Sec-WebSocket-Protocol")).toBe("brandcal-relay.v1");
    res.webSocket?.accept();
    res.webSocket?.close(1000);
    const bare = await SELF.fetch(`https://${RELAY}/_relay/connect`, {
      headers: { Upgrade: "websocket" },
    });
    expect(bare.status).toBe(400);
    const other = await SELF.fetch(`https://${RELAY}/_relay/connect`, {
      headers: { Upgrade: "websocket", "Sec-WebSocket-Protocol": "other.v1" },
    });
    expect(other.status).toBe(400);
  });

  it("sends READY with the version and stream limit, and trims the secret", async () => {
    const fake = await Fake.open();
    fake.hello();
    const nonce = (await fake.nextOf(T.CHALLENGE)).payload;
    const { proof } = await import("../src/protocol");
    fake.send(encode(T.PROOF, 0, await proof(utf8("test-relay-secret-not-real"), nonce)));
    const ready = await fake.nextOf(T.READY);
    expect(decodeJson(ready.payload)).toEqual({ v: 1, max_streams: 16 });
  });

  it("closes 4003 on a wrong PROOF", async () => {
    const fake = await Fake.open();
    fake.hello();
    await fake.nextOf(T.CHALLENGE);
    fake.send(encode(T.PROOF, 0, new Uint8Array(32)));
    expect((await fake.waitClosed()).code).toBe(4003);
  });

  it("closes 4003 for a proof made with another secret", async () => {
    const fake = await Fake.open();
    fake.hello();
    const nonce = (await fake.nextOf(T.CHALLENGE)).payload;
    const { proof } = await import("../src/protocol");
    fake.send(encode(T.PROOF, 0, await proof(utf8("another-secret"), nonce)));
    expect((await fake.waitClosed()).code).toBe(4003);
  });

  it("uses a fresh nonce each time", async () => {
    const a = await Fake.open();
    const b = await Fake.open();
    a.hello();
    b.hello();
    const na = (await a.nextOf(T.CHALLENGE)).payload;
    const nb = (await b.nextOf(T.CHALLENGE)).payload;
    expect(Array.from(na)).not.toEqual(Array.from(nb));
  });

  it("closes 4003 when authentication takes longer than the limit", async () => {
    await setLimits({ authMs: 40 });
    const fake = await Fake.open();
    await new Promise((r) => setTimeout(r, 120));
    fake.hello();
    expect((await fake.waitClosed()).code).toBe(4003);
  });

  it("closes a connector that never speaks once anything else happens (no timers)", async () => {
    await setLimits({ authMs: 40 });
    const idle = await Fake.open();
    await new Promise((r) => setTimeout(r, 120));
    await browser("/"); // any request sweeps sockets past the handshake limit
    expect((await idle.waitClosed()).code).toBe(4003);
  });

  it("closes 4002 for a protocol version other than 1", async () => {
    const fake = await Fake.open();
    fake.hello("brandcal-relay/9", 2);
    expect((await fake.waitClosed()).code).toBe(4002);
  });

  it.each([
    ["a frame shorter than its head", new Uint8Array([0, 0])],
    ["an unknown frame type", new Uint8Array([0x7f, 0, 0, 0, 1])],
    ["PROOF before HELLO", encode(T.PROOF, 0, new Uint8Array(32))],
    ["a stream frame before the handshake", encode(T.RES_END, 5)],
    ["a HELLO that is not JSON", encode(T.HELLO, 0, utf8("nope"))],
    ["a HELLO with a non-text agent", encodeJson(T.HELLO, 0, { v: 1, agent: 7 })],
  ])("closes 4004 for %s", async (_name, bytes) => {
    const fake = await Fake.open();
    fake.send(bytes);
    expect((await fake.waitClosed()).code).toBe(4004);
  });

  it("closes 4004 for a frame the connector may not send after READY", async () => {
    const fake = await Fake.ready();
    fake.send(encode(T.CANCEL, 3));
    expect((await fake.waitClosed()).code).toBe(4004);
  });

  it("closes 4004 for text other than ping", async () => {
    const fake = await Fake.ready();
    fake.ws.send("hello");
    expect((await fake.waitClosed()).code).toBe(4004);
  });

  it("closes 4004 for a frame over 1 MiB", async () => {
    const fake = await Fake.ready();
    fake.send(new Uint8Array(MAX_FRAME + 1));
    expect((await fake.waitClosed()).code).toBe(4004);
  });
});

describe("one connector, newest wins", () => {
  it("closes the old connector with 4001 and serves through the new one", async () => {
    const a = await Fake.ready();
    const b = await Fake.ready();
    expect((await a.waitClosed()).code).toBe(4001);
    const pending = browser("/x");
    const req = await b.nextOf(T.REQ);
    b.respond(req.stream, 200, [["Content-Type", "text/plain"]], [utf8("via b")]);
    expect(await (await pending).text()).toBe("via b");
  });

  it("answers 502 RELAY_DROPPED to a stream in flight on the replaced socket", async () => {
    const a = await Fake.ready();
    const pending = browser("/api/slow");
    await a.nextOf(T.REQ);
    await Fake.ready();
    const res = await pending;
    expect(res.status).toBe(502);
    expect(((await res.json()) as ApiError).error.code).toBe("RELAY_DROPPED");
  });

  it("does not let a connector that fails authentication replace the good one", async () => {
    const good = await Fake.ready();
    const bad = await Fake.open();
    bad.hello();
    await bad.nextOf(T.CHALLENGE);
    bad.send(encode(T.PROOF, 0, new Uint8Array(32)));
    expect((await bad.waitClosed()).code).toBe(4003);
    expect(good.closed).toBeNull();
    const pending = browser("/y");
    const req = await good.nextOf(T.REQ);
    good.respond(req.stream, 204, []);
    expect((await pending).status).toBe(204);
  });
});

describe("offline", () => {
  it("answers pages with 503, Retry-After and the spec text when nothing is connected", async () => {
    const res = await browser("/");
    expect(res.status).toBe(503);
    expect(res.headers.get("Retry-After")).toBe("30");
    const html = await res.text();
    expect(html).toContain("brandcal is offline");
    expect(html).toContain(
      "The calendar server is not connected right now. Nothing has been lost: approvals and edits already made are saved. Try again in a few minutes; if this lasts, the box or `brandcal relay` is down.",
    );
  });

  it("shows when the connector was last connected, from last_seen, with the configured offset", async () => {
    await setLastSeen(Date.now() - 5 * 60_000 - 5_000);
    const html = await (await browser("/")).text();
    expect(html).toMatch(/Last connected 5 minutes ago \(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+03:00\)/);
    expect(html).not.toMatch(/\dZ\b|\+00:00/);
  });

  it("says so when no connector has ever been seen", async () => {
    expect(await (await browser("/")).text()).toContain("No connection has been seen yet.");
  });

  it("answers /api/ with brandcal's error shape and no X-Brandcal-Exit", async () => {
    const res = await browser("/api/session");
    expect(res.status).toBe(503);
    expect(res.headers.get("Retry-After")).toBe("30");
    expect(res.headers.get("X-Brandcal-Exit")).toBeNull();
    const body = (await res.json()) as ApiError;
    expect(body.ok).toBe(false);
    expect(body.error.code).toBe("RELAY_OFFLINE");
    expect(body.error.message).toContain("not connected right now");
    expect(body.error.next).toContain("brandcal relay");
  });

  it("counts a connector whose last pong is older than the limit as offline at once", async () => {
    const fake = await Fake.ready();
    await setLimits({ staleMs: 20 });
    await new Promise((r) => setTimeout(r, 80));
    const res = await browser("/api/session");
    expect(res.status).toBe(503);
    expect(await fake.quiet()).toBe(true);
  });

  it("records last_seen on connect and on disconnect", async () => {
    const before = Date.now();
    const fake = await Fake.ready();
    fake.ws.close(1000);
    await new Promise((r) => setTimeout(r, 100));
    const html = await (await browser("/")).text();
    expect(html).toMatch(/Last connected (less than a minute|0 minutes|1 minute) ago/);
    expect(Date.now() - before).toBeLessThan(10_000);
  });
});

describe("forwarding", () => {
  it("streams a response head and body back and logs one line per stream", async () => {
    const fake = await Fake.ready();
    const pending = browser("/page?q=private-query");
    const req = await fake.nextOf(T.REQ);
    fake.respond(req.stream, 200, [["Content-Type", "text/html"]], [utf8("hel"), utf8("lo")]);
    const res = await pending;
    expect(await res.text()).toBe("hello");
    await new Promise((r) => setTimeout(r, 20));
    const line = logs.find((l) => l.includes("path=/page"));
    expect(line).toMatch(/^\d{4}-\d\d-\d\dT[\d:]+\+03:00 stream=\d+ method=GET path=\/page status=200 ms=\d+ bytes=5 outcome=ok$/);
    expect(line).not.toContain("private-query");
  });

  it("streams a 5 MB body without waiting for the end", async () => {
    const fake = await Fake.ready();
    const pending = browser("/big");
    const req = await fake.nextOf(T.REQ);
    const chunk = new Uint8Array(256 * 1024).fill(0x61);
    const total = 20 * chunk.length; // 5 MiB
    fake.send(encodeResHead(req.stream, 200, [["Content-Type", "application/octet-stream"]], total));
    const res = await pending;
    expect(res.status).toBe(200);
    const reader = res.body!.getReader();
    fake.send(encode(T.RES_BODY, req.stream, chunk));
    const first = await reader.read(); // arrives before RES_END is sent
    expect(first.value![0]).toBe(0x61);
    let got = first.value!.length;
    for (let i = 1; i < 20; i++) fake.send(encode(T.RES_BODY, req.stream, chunk));
    fake.send(encode(T.RES_END, req.stream));
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      got += value.length;
    }
    expect(got).toBe(total);
  });

  it("answers 502 RELAY_TOO_LARGE when RES_HEAD announces more than the cap", async () => {
    await setLimits({ maxResponse: 1000 });
    const fake = await Fake.ready();
    const pending = browser("/api/huge");
    const req = await fake.nextOf(T.REQ);
    fake.send(encodeResHead(req.stream, 200, [], 5000));
    const res = await pending;
    expect(res.status).toBe(502);
    expect(((await res.json()) as ApiError).error.code).toBe("RELAY_TOO_LARGE");
    expect((await fake.nextOf(T.CANCEL)).stream).toBe(req.stream);
  });

  it("aborts the stream when the body passes the cap", async () => {
    await setLimits({ maxResponse: 1000 });
    const fake = await Fake.ready();
    const pending = browser("/chunked");
    const req = await fake.nextOf(T.REQ);
    fake.send(encodeResHead(req.stream, 200, [["Content-Type", "text/plain"]], null));
    const res = await pending;
    fake.send(encode(T.RES_BODY, req.stream, new Uint8Array(600)));
    fake.send(encode(T.RES_BODY, req.stream, new Uint8Array(600)));
    await expect(res.arrayBuffer()).rejects.toThrow();
    expect((await fake.nextOf(T.CANCEL)).stream).toBe(req.stream);
  });

  it.each([
    ["UPSTREAM_DOWN", 502, "RELAY_UPSTREAM_DOWN", "brandcal serve is not running"],
    ["UPSTREAM_TIMEOUT", 504, "RELAY_TIMEOUT", ""],
    ["TOO_LARGE", 502, "RELAY_TOO_LARGE", ""],
    ["BAD_FRAME", 502, "RELAY_BAD_FRAME", ""],
  ])("maps RES_ERR %s to %i %s before the head", async (code, status, relayCode, text) => {
    const fake = await Fake.ready();
    const pending = browser("/api/err");
    const req = await fake.nextOf(T.REQ);
    fake.send(encodeJson(T.RES_ERR, req.stream, { code }));
    const res = await pending;
    expect(res.status).toBe(status);
    const body = (await res.json()) as ApiError;
    expect(body.error.code).toBe(relayCode);
    expect(body.error.message).toContain(text);
  });

  it("aborts the stream on RES_ERR after the head was sent", async () => {
    const fake = await Fake.ready();
    const pending = browser("/late");
    const req = await fake.nextOf(T.REQ);
    fake.send(encodeResHead(req.stream, 200, [], null));
    const res = await pending;
    fake.send(encodeJson(T.RES_ERR, req.stream, { code: "UPSTREAM_TIMEOUT" }));
    await expect(res.text()).rejects.toThrow();
  });

  it("aborts the stream when the body is shorter than the announced length", async () => {
    const fake = await Fake.ready();
    const pending = browser("/short");
    const req = await fake.nextOf(T.REQ);
    fake.send(encodeResHead(req.stream, 200, [], 10));
    const res = await pending;
    fake.send(encode(T.RES_BODY, req.stream, new Uint8Array(3)));
    fake.send(encode(T.RES_END, req.stream));
    await expect(res.arrayBuffer()).rejects.toThrow();
  });

  // Called on the Durable Object itself, so the test cancels the very body the DO made.
  it("sends CANCEL when the browser stops reading a response", async () => {
    const fake = await Fake.ready();
    const request = new Request(`https://${PUBLIC}/stream`, { headers: { Accept: "text/plain" } });
    const outcome = runInDurableObject(stub(), async (relay) => {
      const res = await relay.fetch(request);
      await res.body!.cancel();
      return res.status;
    });
    const req = await fake.nextOf(T.REQ);
    fake.send(encodeResHead(req.stream, 200, [["Content-Type", "text/plain"]], null));
    fake.send(encode(T.RES_BODY, req.stream, utf8("part")));
    expect(await outcome).toBe(200);
    expect((await fake.nextOf(T.CANCEL)).stream).toBe(req.stream);
    await new Promise((r) => setTimeout(r, 20));
    expect(logs.some((l) => l.includes("outcome=cancelled"))).toBe(true);
    const health = (await (await browser("/_relay/health")).json()) as { in_flight: number };
    expect(health.in_flight).toBe(0);
  });


  it("ignores late frames for a stream it no longer knows", async () => {
    const fake = await Fake.ready();
    fake.send(encode(T.RES_BODY, 999, utf8("late")));
    fake.send(encode(T.RES_END, 999));
    const pending = browser("/after");
    const req = await fake.nextOf(T.REQ);
    fake.respond(req.stream, 204, []);
    expect((await pending).status).toBe(204);
  });

  it("gives each stream its own id", async () => {
    const fake = await Fake.ready();
    const a = browser("/a");
    const b = browser("/b");
    const first = await fake.nextOf(T.REQ);
    const second = await fake.nextOf(T.REQ);
    expect(first.stream).not.toBe(second.stream);
    expect(first.stream).toBeGreaterThan(0);
    const [ra, rb] = decodeReq(first.payload).p === "/a" ? [first, second] : [second, first];
    fake.respond(rb.stream, 200, [], [utf8("b")]);
    fake.respond(ra.stream, 200, [], [utf8("a")]);
    expect(await (await a).text()).toBe("a");
    expect(await (await b).text()).toBe("b");
  });

  it("answers 503 RELAY_BUSY past 16 streams in flight", async () => {
    const fake = await Fake.ready();
    const first = Array.from({ length: 16 }, (_, i) => browser(`/api/s${i}`));
    const reqs = [];
    for (let i = 0; i < 16; i++) reqs.push(await fake.nextOf(T.REQ));
    const res = await browser("/api/seventeen");
    expect(res.status).toBe(503);
    expect(((await res.json()) as ApiError).error.code).toBe("RELAY_BUSY");
    for (const r of reqs) fake.respond(r.stream, 204, []);
    for (const p of first) expect((await p).status).toBe(204);
    const again = browser("/api/after");
    fake.respond((await fake.nextOf(T.REQ)).stream, 204, []);
    expect((await again).status).toBe(204);
  });
});

describe("timeouts and dropped writes", () => {
  it("answers 504 RELAY_TIMEOUT when RES_HEAD does not come, and cancels the stream", async () => {
    await setLimits({ headMs: 80 });
    const fake = await Fake.ready();
    const pending = browser("/api/hang");
    const req = await fake.nextOf(T.REQ);
    const res = await pending;
    expect(res.status).toBe(504);
    expect(((await res.json()) as ApiError).error.code).toBe("RELAY_TIMEOUT");
    expect((await fake.nextOf(T.CANCEL)).stream).toBe(req.stream);
  });

  it("aborts the stream when a gap between body chunks is too long", async () => {
    await setLimits({ headMs: 80 });
    const fake = await Fake.ready();
    const pending = browser("/gap");
    const req = await fake.nextOf(T.REQ);
    fake.send(encodeResHead(req.stream, 200, [["Content-Type", "text/plain"]], null));
    const res = await pending;
    fake.send(encode(T.RES_BODY, req.stream, utf8("one")));
    await expect(res.text()).rejects.toThrow();
    expect((await fake.nextOf(T.CANCEL)).stream).toBe(req.stream);
  });

  it("answers 502 RELAY_DROPPED with the spec message when the socket drops after a POST", async () => {
    const fake = await Fake.ready();
    const pending = browser("/api/posts/p1/approve", { method: "POST", body: "{}" });
    await fake.nextOf(T.REQ);
    fake.ws.close(1011, "gone");
    const res = await pending;
    expect(res.status).toBe(502);
    const body = (await res.json()) as ApiError;
    expect(body.error.code).toBe("RELAY_DROPPED");
    expect(body.error.message).toBe(MESSAGE);
    expect(res.headers.get("X-Brandcal-Exit")).toBeNull();
  });

  it("shows the same message on a dropped page POST", async () => {
    const fake = await Fake.ready();
    const pending = browser("/form", { method: "POST", body: "a=1" });
    await fake.nextOf(T.REQ);
    fake.ws.close(1001);
    const res = await pending;
    expect(res.status).toBe(502);
    expect(await res.text()).toContain(MESSAGE);
  });

  it("aborts a response already started when the socket drops", async () => {
    const fake = await Fake.ready();
    const pending = browser("/dropping");
    const req = await fake.nextOf(T.REQ);
    fake.send(encodeResHead(req.stream, 200, [], null));
    const res = await pending;
    fake.ws.close(1001);
    await expect(res.text()).rejects.toThrow();
  });
});

describe("health", () => {
  it("reports the connector with +03:00 timestamps", async () => {
    await Fake.ready("brandcal-relay/1.2.3");
    const res = await browser("/_relay/health");
    expect(res.status).toBe(200);
    const text = await res.text();
    expect(text).not.toMatch(/\dZ"|\+00:00/);
    const body = JSON.parse(text) as Record<string, unknown>;
    expect(Object.keys(body)).toEqual([
      "ok",
      "connected",
      "connected_since",
      "last_pong_age_s",
      "agent",
      "in_flight",
    ]);
    expect(body.ok).toBe(true);
    expect(body.connected).toBe(true);
    expect(body.connected_since).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+03:00$/);
    expect(body.agent).toBe("brandcal-relay/1.2.3");
    expect(body.in_flight).toBe(0);
    expect(typeof body.last_pong_age_s).toBe("number");
    expect(res.headers.get("Content-Type")).toContain("application/json");
    expect(res.headers.get("Cache-Control")).toBe("no-store");
  });

  it("counts streams in flight", async () => {
    const fake = await Fake.ready();
    const pending = browser("/x");
    const req = await fake.nextOf(T.REQ);
    const body = (await (await browser("/_relay/health")).json()) as { in_flight: number };
    expect(body.in_flight).toBe(1);
    fake.respond(req.stream, 204, []);
    await pending;
  });

  it("answers 503 with connected:false when nothing is connected", async () => {
    const res = await browser("/_relay/health");
    expect(res.status).toBe(503);
    const body = (await res.json()) as Record<string, unknown>;
    expect(body.connected).toBe(false);
    expect(body.connected_since).toBeNull();
    expect(body.agent).toBeNull();
    expect(body.in_flight).toBe(0);
  });

  it("never includes the secret, an email or an address", async () => {
    await Fake.ready();
    const text = await (await browser("/_relay/health")).text();
    expect(text).not.toContain("test-relay-secret-not-real");
    expect(text).not.toMatch(/@|\d+\.\d+\.\d+\.\d+/);
  });
});

describe("wrangler.jsonc", () => {
  const cfg = JSON.parse(config) as Record<string, any>;

  it("turns invocation logs off and keeps the custom log lines", () => {
    expect(cfg.observability.logs.enabled).toBe(true);
    expect(cfg.observability.logs.invocation_logs).toBe(false);
  });

  it("closes workers.dev and preview URLs", () => {
    expect(cfg.workers_dev).toBe(false);
    expect(cfg.preview_urls).toBe(false);
  });

  it("holds no account id, no timezone default and no secret", () => {
    expect(cfg).not.toHaveProperty("account_id");
    expect(cfg.vars).not.toHaveProperty("DISPLAY_UTC_OFFSET");
    expect(cfg.vars).not.toHaveProperty("RELAY_SECRET");
    expect(config).not.toContain("account_id");
    expect(config).not.toContain("DISPLAY_UTC_OFFSET");
  });

  it("uses placeholder hosts, custom domains and a SQLite Durable Object", () => {
    expect(cfg.name).toBe("brandcal-relay");
    expect(cfg.main).toBe("src/index.ts");
    expect(cfg.vars.PUBLIC_HOST).toBe(PUBLIC);
    expect(cfg.vars.RELAY_HOST).toBe(RELAY);
    expect(cfg.routes).toEqual([
      { pattern: PUBLIC, custom_domain: true },
      { pattern: RELAY, custom_domain: true },
    ]);
    expect(cfg.durable_objects.bindings).toEqual([{ name: "RELAY", class_name: "Relay" }]);
    expect(cfg.migrations[0].new_sqlite_classes).toEqual(["Relay"]);
    expect(cfg.compatibility_date).toMatch(/^\d{4}-\d\d-\d\d$/);
  });
});

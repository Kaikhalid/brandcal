import { SELF, env, reset, runInDurableObject } from "cloudflare:test";
import { afterEach, beforeEach, vi } from "vitest";
import { type Frame, T, decode, encode, encodeJson, encodeResHead, proof } from "../src/protocol";
import type { Limits } from "../src/relay_do";

export const PUBLIC = "brandcal.example.com";
export const RELAY = "brandcal-relay.example.com";
export const SECRET = "test-relay-secret-not-real";
// Three base64url segments, obviously fake. Never appears in any log line (asserted).
export const JWT = "eyJhbGciOiJub25lIn0.eyJmYWtlIjoidGVzdC1ub3QtcmVhbCJ9.ZmFrZS1zaWduYXR1cmU";
export const SPOOFED_EMAIL = "spoofed.person@example.com";
export const COOKIE = "CF_Authorization=fake-cookie-value-not-real";

export const logs: string[] = [];
const open: Fake[] = [];

/** Capture console.log (the Worker's only output) and reset the Durable Object between tests. */
export function useHarness(): void {
  beforeEach(() => {
    logs.length = 0;
    vi.spyOn(console, "log").mockImplementation((line: unknown) => {
      logs.push(String(line));
    });
  });
  afterEach(async () => {
    for (const f of open.splice(0)) f.drop();
    vi.restoreAllMocks();
    await reset();
  });
}

export function stub() {
  return env.RELAY.getByName("relay");
}

/** Change the Durable Object's limits so a test runs in milliseconds, not seconds. */
export async function setLimits(limits: Partial<Limits>): Promise<void> {
  await runInDurableObject(stub(), (relay) => {
    Object.assign(relay.limits, limits);
  });
}

export async function setLastSeen(ms: number): Promise<void> {
  await runInDurableObject(stub(), async (_relay, state) => {
    await state.storage.put("last_seen", ms);
  });
}

export function browser(path: string, init: RequestInit = {}, host = PUBLIC): Promise<Response> {
  const headers = new Headers(init.headers);
  if (!headers.has("Cf-Access-Jwt-Assertion")) headers.set("Cf-Access-Jwt-Assertion", JWT);
  return SELF.fetch(`https://${host}${path}`, { ...init, headers });
}

/** A fake connector: a WebSocket client from the test that speaks protocol v1. */
export class Fake {
  private queue: Frame[] = [];
  private waiting: Array<() => void> = [];
  closed: { code: number; reason: string } | null = null;

  private constructor(readonly ws: WebSocket) {
    ws.binaryType = "arraybuffer"; // workerd defaults to "blob"
    ws.addEventListener("message", (e) => {
      if (typeof e.data === "string") return;
      this.queue.push(decode(e.data as ArrayBuffer));
      this.wake();
    });
    ws.addEventListener("close", (e) => {
      this.closed = { code: e.code, reason: e.reason };
      this.wake();
    });
  }

  static async open(host = RELAY, protocol: string | null = "brandcal-relay.v1"): Promise<Fake> {
    const headers: Record<string, string> = { Upgrade: "websocket" };
    if (protocol) headers["Sec-WebSocket-Protocol"] = protocol;
    const res = await SELF.fetch(`https://${host}/_relay/connect`, { headers });
    if (res.status !== 101 || !res.webSocket) throw new Error(`upgrade refused: ${res.status}`);
    res.webSocket.accept();
    const fake = new Fake(res.webSocket);
    open.push(fake);
    return fake;
  }

  /** Connect and complete the handshake; resolves once the Durable Object says READY. */
  static async ready(agent = "brandcal-relay/0.0.0-test"): Promise<Fake> {
    const fake = await Fake.open();
    await fake.handshake(agent);
    return fake;
  }

  private wake(): void {
    for (const w of this.waiting.splice(0)) w();
  }

  private async until<R>(pick: () => R | undefined, ms: number, what: string): Promise<R> {
    const end = Date.now() + ms;
    for (;;) {
      const got = pick();
      if (got !== undefined) return got;
      const left = end - Date.now();
      if (left <= 0) throw new Error(`timed out waiting for ${what}`);
      await new Promise<void>((resolve) => {
        this.waiting.push(resolve);
        setTimeout(resolve, left);
      });
    }
  }

  send(bytes: Uint8Array): void {
    this.ws.send(bytes);
  }

  next(ms = 2000): Promise<Frame> {
    return this.until(() => this.queue.shift(), ms, "a frame");
  }

  async nextOf(kind: number, ms = 2000): Promise<Frame> {
    const frame = await this.next(ms);
    if (frame.kind !== kind) throw new Error(`expected frame ${kind}, got ${frame.kind}`);
    return frame;
  }

  waitClosed(ms = 2000): Promise<{ code: number; reason: string }> {
    return this.until(() => this.closed ?? undefined, ms, "a close");
  }

  /** Assert that nothing more arrives within `ms`. */
  async quiet(ms = 50): Promise<boolean> {
    await new Promise((resolve) => setTimeout(resolve, ms));
    return this.queue.length === 0;
  }

  hello(agent = "brandcal-relay/0.0.0-test", v = 1): void {
    this.send(encodeJson(T.HELLO, 0, { v, agent }));
  }

  async handshake(agent = "brandcal-relay/0.0.0-test", secret = SECRET): Promise<void> {
    this.hello(agent);
    const nonce = (await this.nextOf(T.CHALLENGE)).payload;
    this.send(encode(T.PROOF, 0, await proof(new TextEncoder().encode(secret), nonce)));
    await this.nextOf(T.READY);
  }

  /** Answer a stream the way the real connector would. */
  respond(
    stream: number,
    status: number,
    headers: Array<[string, string]>,
    chunks: Uint8Array[] = [],
  ): void {
    const length = chunks.reduce((n, c) => n + c.length, 0);
    this.send(encodeResHead(stream, status, headers, length));
    for (const chunk of chunks) this.send(encode(T.RES_BODY, stream, chunk));
    this.send(encode(T.RES_END, stream));
  }

  drop(): void {
    try {
      this.ws.close(1000, "test over");
    } catch {
      // already closed
    }
  }
}

export const utf8 = (s: string) => new TextEncoder().encode(s);

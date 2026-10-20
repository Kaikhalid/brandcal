// The Durable Object "Relay": one instance, holding the connector's WebSocket (Hibernation API
// only: no ws.accept(), no alarms, no idle timers) and the browser requests in flight on it.
//
// Per-socket state lives in the socket's attachment so it survives hibernation. Streams are in
// memory only, which is safe because a Durable Object is not evicted while a request is in flight.
// The few timers below each belong to one request in flight and are cleared when it ends.

import { DurableObject } from "cloudflare:workers";
import { RESPONSE_HEADERS, requestHeaders } from "./headers";
import {
  PROBLEMS,
  type Problem,
  formatTime,
  logConnection,
  logEvent,
  problem,
} from "./pages";
import {
  FrameError,
  type Frame,
  SUBPROTOCOL,
  T,
  decode,
  decodeJson,
  decodeResHead,
  encode,
  encodeJson,
  encodeReq,
  proof,
} from "./protocol";

type Env = Cloudflare.Env;

export interface Limits {
  maxStreams: number;
  /** Waiting for RES_HEAD, or the gap between body chunks. */
  headMs: number;
  /** WebSocket handshake plus authentication. */
  authMs: number;
  /** A last pong older than this counts as offline. */
  staleMs: number;
  /** Total response bytes. */
  maxResponse: number;
}

export const DEFAULT_LIMITS: Limits = {
  maxStreams: 16,
  headMs: 30_000,
  authMs: 10_000,
  staleMs: 90_000,
  maxResponse: 32 * 1024 * 1024,
};

interface Attachment {
  id: string;
  /** When the socket was accepted. */
  at: number;
  helloed: boolean;
  /** base64 nonce sent in the CHALLENGE. */
  nonce: string | null;
  authed: boolean;
  /** When it authenticated. */
  since: number | null;
  agent: string | null;
}

interface Stream {
  id: number;
  socket: string;
  ws: WebSocket;
  method: string;
  path: string;
  began: number;
  sent: number;
  status: number;
  length: number | null;
  /** Set until the response head has been delivered; resolves the browser's fetch. */
  head: ((response: Response | Promise<Response>) => void) | null;
  /** Feeds the response body the browser is reading. */
  sink: ReadableStreamDefaultController<Uint8Array> | null;
  timer: ReturnType<typeof setTimeout> | null;
  done: boolean;
}

export interface Status {
  connected: boolean;
  connectedSince: number | null;
  lastPongAgeS: number | null;
  agent: string | null;
  inFlight: number;
}

const RES_ERR_PROBLEMS: Record<string, Problem> = {
  UPSTREAM_DOWN: PROBLEMS.upstreamDown,
  UPSTREAM_TIMEOUT: PROBLEMS.timeout,
  TOO_LARGE: PROBLEMS.tooLarge,
  BAD_FRAME: PROBLEMS.badFrame,
};
const NO_BODY = new Set([204, 205, 304]);
const OPEN = 1;

const base64 = (b: Uint8Array) => btoa(String.fromCharCode(...b));
const unbase64 = (s: string) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

export class Relay extends DurableObject<Env> {
  /** Public so that tests can shorten them; production keeps the defaults. */
  limits: Limits = { ...DEFAULT_LIMITS };
  private streams = new Map<number, Stream>();
  private nextId = 1;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    // The runtime answers the connector's text "ping" without waking us and records the time.
    ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair("ping", "pong"));
  }

  private get offset(): string {
    return this.env.DISPLAY_UTC_OFFSET as string; // the Worker has already validated it
  }

  // -- entry points ----------------------------------------------------------------------------

  override async fetch(request: Request): Promise<Response> {
    this.sweep();
    if (request.headers.get("Upgrade")?.toLowerCase() === "websocket") return this.accept(request);
    return this.proxy(request);
  }

  /** For the health endpoint, called by the Worker. */
  async status(): Promise<Status> {
    this.sweep();
    const link = this.online();
    return {
      connected: link !== null,
      connectedSince: link?.att.since ?? null,
      lastPongAgeS: link ? Math.floor((Date.now() - this.lastPong(link.ws, link.att)) / 1000) : null,
      agent: link?.att.agent ?? null,
      inFlight: this.streams.size,
    };
  }

  // -- the connector's socket --------------------------------------------------------------------

  private accept(request: Request): Response | Promise<Response> {
    const offered = (request.headers.get("Sec-WebSocket-Protocol") ?? "")
      .split(",")
      .map((p) => p.trim());
    if (!offered.includes(SUBPROTOCOL)) return problem("/_relay/connect", PROBLEMS.badRequest);
    const { 0: client, 1: server } = new WebSocketPair();
    this.ctx.acceptWebSocket(server, ["connector"]);
    const att: Attachment = {
      id: crypto.randomUUID(),
      at: Date.now(),
      helloed: false,
      nonce: null,
      authed: false,
      since: null,
      agent: null,
    };
    server.serializeAttachment(att);
    return new Response(null, {
      status: 101,
      webSocket: client,
      headers: { "Sec-WebSocket-Protocol": SUBPROTOCOL },
    });
  }

  private attachment(ws: WebSocket): Attachment | null {
    return (ws.deserializeAttachment() as Attachment | null) ?? null;
  }

  private close(ws: WebSocket, code: number, reason: string): void {
    const att = this.attachment(ws);
    try {
      ws.close(code, reason);
    } catch {
      // already closing
    }
    if (att) this.dropStreams(att.id);
  }

  /** Sockets past the handshake limit that never authenticated. Enforced here, not on a timer. */
  private sweep(): void {
    const now = Date.now();
    for (const ws of this.ctx.getWebSockets("connector")) {
      const att = this.attachment(ws);
      if (att && !att.authed && now - att.at > this.limits.authMs) {
        this.close(ws, 4003, "authentication timed out");
      }
    }
  }

  private lastPong(ws: WebSocket, att: Attachment): number {
    const pong = this.ctx.getWebSocketAutoResponseTimestamp(ws)?.getTime() ?? 0;
    return Math.max(pong, att.since ?? 0);
  }

  /** The newest authenticated socket, or null if it is gone or its last pong is too old. */
  private online(): { ws: WebSocket; att: Attachment } | null {
    let best: { ws: WebSocket; att: Attachment } | null = null;
    for (const ws of this.ctx.getWebSockets("connector")) {
      const att = this.attachment(ws);
      if (ws.readyState !== OPEN || !att?.authed) continue;
      if (!best || (att.since ?? 0) > (best.att.since ?? 0)) best = { ws, att };
    }
    if (best && Date.now() - this.lastPong(best.ws, best.att) > this.limits.staleMs) return null;
    return best;
  }

  override async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer): Promise<void> {
    if (message === "ping") return; // normally answered by the runtime without reaching us
    const att = this.attachment(ws);
    if (!att || typeof message === "string") return this.close(ws, 4004, "malformed frame");
    this.sweep();
    if (!att.authed && Date.now() - att.at > this.limits.authMs) {
      return this.close(ws, 4003, "authentication timed out");
    }
    let frame: Frame;
    try {
      frame = decode(message);
    } catch (err) {
      if (!(err instanceof FrameError)) throw err;
      return this.close(ws, 4004, "malformed frame");
    }
    if (att.authed) return this.onFrame(ws, att, frame);
    return this.handshake(ws, att, frame);
  }

  override async webSocketClose(ws: WebSocket, code: number): Promise<void> {
    await this.gone(ws, code);
    try {
      ws.close(code >= 1000 && ![1005, 1006, 1015].includes(code) ? code : 1000, "closing");
    } catch {
      // already closed
    }
  }

  override async webSocketError(ws: WebSocket): Promise<void> {
    await this.gone(ws, 1006);
  }

  private async gone(ws: WebSocket, code: number): Promise<void> {
    const att = this.attachment(ws);
    if (!att) return;
    this.dropStreams(att.id);
    if (!att.authed) return;
    logConnection(this.offset, `disconnect close=${code}`);
    const other = this.ctx
      .getWebSockets("connector")
      .some((o) => o.readyState === OPEN && this.attachment(o)?.id !== att.id && this.attachment(o)?.authed);
    if (!other) await this.ctx.storage.put("last_seen", Date.now());
  }

  private async handshake(ws: WebSocket, att: Attachment, frame: Frame): Promise<void> {
    if (!att.helloed) {
      if (frame.kind !== T.HELLO) return this.close(ws, 4004, "HELLO must come first");
      let hello: Record<string, unknown>;
      try {
        hello = decodeJson(frame.payload);
      } catch {
        return this.close(ws, 4004, "malformed HELLO");
      }
      if (hello.v !== 1) return this.close(ws, 4002, "protocol version");
      if (typeof hello.agent !== "string") return this.close(ws, 4004, "malformed HELLO");
      const nonce = crypto.getRandomValues(new Uint8Array(32));
      att.helloed = true;
      att.nonce = base64(nonce);
      att.agent = hello.agent.replace(/[^\x20-\x7e]/g, "?").slice(0, 64);
      ws.serializeAttachment(att);
      ws.send(encode(T.CHALLENGE, 0, nonce));
      return;
    }
    if (frame.kind !== T.PROOF || att.nonce === null) return this.close(ws, 4004, "PROOF expected");
    const secret = new TextEncoder().encode((this.env.RELAY_SECRET ?? "").trim());
    const expected = await proof(secret, unbase64(att.nonce));
    const ok = secret.length > 0 && crypto.subtle.timingSafeEqual(expected, frame.payload);
    if (!ok) {
      logConnection(this.offset, "auth-failed close=4003");
      return this.close(ws, 4003, "authentication failed");
    }
    const now = Date.now();
    const fresh = this.attachment(ws);
    if (!fresh || fresh.authed) return;
    for (const other of this.ctx.getWebSockets("connector")) {
      const o = this.attachment(other);
      if (o && o.id !== att.id && o.authed) this.close(other, 4001, "replaced by a newer connector");
    }
    att.authed = true;
    att.since = now;
    ws.serializeAttachment(att);
    await this.ctx.storage.put("last_seen", now);
    ws.send(encodeJson(T.READY, 0, { v: 1, max_streams: this.limits.maxStreams }));
    logConnection(this.offset, `connect agent=${att.agent}`);
  }

  // -- frames from the connector -----------------------------------------------------------------

  private onFrame(ws: WebSocket, att: Attachment, frame: Frame): void {
    switch (frame.kind) {
      case T.RES_HEAD:
      case T.RES_BODY:
      case T.RES_END:
      case T.RES_ERR: {
        const s = this.streams.get(frame.stream);
        if (s && s.socket === att.id) this.onResponse(s, frame);
        return; // a frame for a stream that already ended is ignored
      }
      default:
        this.close(ws, 4004, "unexpected frame");
    }
  }

  private onResponse(s: Stream, frame: Frame): void {
    if (frame.kind === T.RES_ERR) return this.onError(s, frame);
    if (frame.kind === T.RES_HEAD) return this.onHead(s, frame);
    if (s.head) return this.bad(s); // a body or an end before the head
    if (frame.kind === T.RES_BODY) {
      if (!s.sink) return; // 204, 205 and 304 have no body
      s.sent += frame.payload.length;
      if (s.sent > this.limits.maxResponse) return this.abort(s, "too_large", true);
      if (frame.payload.length > 0) this.push(s, (c) => c.enqueue(frame.payload.slice()));
      return this.arm(s);
    }
    // RES_END
    if (s.length !== null && s.sent !== s.length) return this.abort(s, "short_body", false);
    this.push(s, (c) => c.close());
    this.finish(s, "ok");
  }

  private onHead(s: Stream, frame: Frame): void {
    if (!s.head) return this.bad(s); // a second head
    let head;
    try {
      head = decodeResHead(frame.payload);
    } catch {
      return this.bad(s);
    }
    if (head.bl !== null && head.bl > this.limits.maxResponse) {
      return this.fail(s, PROBLEMS.tooLarge, "too_large", true);
    }
    const headers = new Headers();
    try {
      for (const [name, value] of head.h) {
        if (RESPONSE_HEADERS.has(name.toLowerCase())) headers.append(name, value);
      }
    } catch {
      return this.bad(s);
    }
    s.status = head.s;
    s.length = head.bl;
    let body: ReadableStream<Uint8Array> | null = null;
    if (!NO_BODY.has(head.s)) {
      // Chunks are passed on as they arrive; nothing is held beyond what the browser has not yet
      // read. cancel() runs when the browser goes away, and the connector is then told to stop.
      body = new ReadableStream<Uint8Array>({
        start: (controller) => {
          s.sink = controller;
        },
        cancel: () => this.cancel(s),
      });
    }
    const deliver = s.head;
    s.head = null;
    deliver(new Response(body, { status: head.s, headers }));
    this.arm(s);
  }

  private onError(s: Stream, frame: Frame): void {
    let code = "";
    try {
      code = String(decodeJson(frame.payload).code);
    } catch {
      return this.bad(s);
    }
    const known = RES_ERR_PROBLEMS[code];
    if (!known) return this.bad(s);
    this.fail(s, known, code.toLowerCase(), false);
  }

  // -- one browser request -----------------------------------------------------------------------

  private async offline(path: string): Promise<Response> {
    const seen = await this.ctx.storage.get<number>("last_seen");
    let detail = "No connection has been seen yet.";
    if (seen !== undefined) {
      const minutes = Math.floor((Date.now() - seen) / 60_000);
      const ago =
        minutes < 1 ? "less than a minute" : minutes === 1 ? "1 minute" : `${minutes} minutes`;
      detail = `Last connected ${ago} ago (${formatTime(seen, this.offset)}).`;
    }
    return problem(path, { ...PROBLEMS.offline, detail });
  }

  private async proxy(request: Request): Promise<Response> {
    const began = Date.now();
    const url = new URL(request.url);
    const path = url.pathname + url.search;
    const done = (p: Problem, outcome: string) => {
      logEvent(this.offset, {
        stream: "-",
        method: request.method,
        path,
        status: p.status,
        ms: Date.now() - began,
        bytes: 0,
        outcome,
      });
      return problem(path, p);
    };

    const link = this.online();
    if (!link) {
      logEvent(this.offset, {
        stream: "-",
        method: request.method,
        path,
        status: 503,
        ms: Date.now() - began,
        bytes: 0,
        outcome: "offline",
      });
      return this.offline(path);
    }
    if (this.streams.size >= this.limits.maxStreams) return done(PROBLEMS.busy, "busy");

    const body = new Uint8Array(await request.arrayBuffer());
    const id = this.nextId;
    this.nextId = id >= 0xffffffff ? 1 : id + 1;
    let frame: Uint8Array;
    try {
      const headers = requestHeaders(request.headers, this.env.PUBLIC_HOST);
      frame = encodeReq(id, request.method, path, headers, body);
    } catch (err) {
      if (!(err instanceof FrameError)) throw err; // the only way to fail is a frame over 1 MiB
      return done(PROBLEMS.requestTooLarge, "request_too_large");
    }

    const reply = new Promise<Response>((resolve) => {
      const s: Stream = {
        id,
        socket: link.att.id,
        ws: link.ws,
        method: request.method,
        path,
        began,
        sent: 0,
        status: 0,
        length: null,
        head: resolve,
        sink: null,
        timer: null,
        done: false,
      };
      this.streams.set(id, s);
      request.signal.addEventListener("abort", () => this.cancel(s));
      this.arm(s);
      try {
        link.ws.send(frame);
      } catch {
        this.dropped(s);
      }
    });
    return reply;
  }

  // -- ending a stream ---------------------------------------------------------------------------

  private arm(s: Stream): void {
    if (s.timer) clearTimeout(s.timer);
    s.timer = setTimeout(() => {
      s.timer = null;
      if (s.head) this.fail(s, PROBLEMS.timeout, "timeout", true);
      else this.abort(s, "timeout", true);
    }, this.limits.headMs);
  }

  /** Use the body controller. It throws once the browser has cancelled, which is fine. */
  private push(s: Stream, use: (c: ReadableStreamDefaultController<Uint8Array>) => void): void {
    if (!s.sink) return;
    try {
      use(s.sink);
    } catch {
      // the browser already went away
    }
  }

  private sendCancel(s: Stream): void {
    try {
      s.ws.send(encode(T.CANCEL, s.id));
    } catch {
      // the socket is gone anyway
    }
  }

  private finish(s: Stream, outcome: string): void {
    if (s.done) return;
    s.done = true;
    if (s.timer) clearTimeout(s.timer);
    this.streams.delete(s.id);
    logEvent(this.offset, {
      stream: s.id,
      method: s.method,
      path: s.path,
      status: s.status,
      ms: Date.now() - s.began,
      bytes: s.sent,
      outcome,
    });
  }

  /** End a stream with an error: a page if the head is not out yet, else abort the body. */
  private fail(s: Stream, p: Problem, outcome: string, cancel: boolean): void {
    if (s.done) return;
    if (cancel) this.sendCancel(s);
    const deliver = s.head;
    if (deliver) {
      s.head = null;
      s.status = p.status;
      deliver(problem(s.path, p));
    } else {
      this.push(s, (c) => c.error(new Error(outcome)));
    }
    this.finish(s, outcome);
  }

  private abort(s: Stream, outcome: string, cancel: boolean): void {
    this.fail(s, PROBLEMS.badFrame, outcome, cancel);
  }

  private bad(s: Stream): void {
    this.fail(s, PROBLEMS.badFrame, "bad_frame", true);
  }

  /** The browser went away: tell the connector to drop the upstream connection. */
  private cancel(s: Stream): void {
    if (s.done) return;
    this.sendCancel(s);
    s.head = null;
    this.finish(s, "cancelled");
  }

  private dropped(s: Stream): void {
    this.fail(s, s.method === "POST" ? PROBLEMS.droppedWrite : PROBLEMS.droppedRead, "dropped", false);
  }

  private dropStreams(socket: string): void {
    for (const s of [...this.streams.values()]) if (s.socket === socket) this.dropped(s);
  }
}

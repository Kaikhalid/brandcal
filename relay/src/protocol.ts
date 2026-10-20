// Frame format of brandcal-relay.v1. Mirrors src/brandcal/relay.py; the shared golden vectors in
// tests/data/relay_frames.json keep the two in step.
//
// Every frame is one binary WebSocket message: type:u8 | stream:u32be | payload.

export const T = {
  HELLO: 0x00,
  CHALLENGE: 0x01,
  PROOF: 0x02,
  READY: 0x03,
  REQ: 0x10,
  CANCEL: 0x11,
  RES_HEAD: 0x20,
  RES_BODY: 0x21,
  RES_END: 0x22,
  RES_ERR: 0x23,
} as const;

const CONNECTION_FRAMES: readonly number[] = [T.HELLO, T.CHALLENGE, T.PROOF, T.READY]; // stream 0
const STREAM_FRAMES: readonly number[] = [T.REQ, T.CANCEL, T.RES_HEAD, T.RES_BODY, T.RES_END, T.RES_ERR];

export const MAX_FRAME = 1024 * 1024;
export const CHUNK = 256 * 1024;
export const HEAD_SIZE = 5;
export const SUBPROTOCOL = "brandcal-relay.v1";
const LABEL = new TextEncoder().encode(SUBPROTOCOL);

export class FrameError extends Error {}

export interface Frame {
  kind: number;
  stream: number;
  payload: Uint8Array;
}

export type HeaderPairs = Array<[string, string]>;

export interface ReqFrame {
  m: string;
  p: string;
  h: HeaderPairs;
  body: Uint8Array;
}

export interface ResHead {
  s: number;
  h: HeaderPairs;
  bl: number | null;
}

const enc = new TextEncoder();
const dec = new TextDecoder("utf-8", { fatal: true, ignoreBOM: false });

export function encode(kind: number, stream: number, payload: Uint8Array = new Uint8Array()): Uint8Array {
  const out = new Uint8Array(HEAD_SIZE + payload.length);
  if (out.length > MAX_FRAME) throw new FrameError("a frame is over 1 MiB");
  new DataView(out.buffer).setUint8(0, kind);
  new DataView(out.buffer).setUint32(1, stream);
  out.set(payload, HEAD_SIZE);
  return out;
}

export function decode(data: ArrayBuffer | Uint8Array): Frame {
  const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
  if (bytes.length < HEAD_SIZE) throw new FrameError("a frame is shorter than its 5-byte head");
  if (bytes.length > MAX_FRAME) throw new FrameError("a frame is over 1 MiB");
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const kind = view.getUint8(0);
  const stream = view.getUint32(1);
  const payload = bytes.subarray(HEAD_SIZE);
  if (CONNECTION_FRAMES.includes(kind)) {
    if (stream !== 0) throw new FrameError("a connection frame has a stream id");
  } else if (STREAM_FRAMES.includes(kind)) {
    if (stream === 0) throw new FrameError("a stream frame has stream id 0");
  } else {
    throw new FrameError(`unknown frame type ${kind}`);
  }
  if ((kind === T.CHALLENGE || kind === T.PROOF) && payload.length !== 32) {
    throw new FrameError("a nonce or proof is not 32 bytes");
  }
  if ((kind === T.CANCEL || kind === T.RES_END) && payload.length !== 0) {
    throw new FrameError("this frame type carries no payload");
  }
  return { kind, stream, payload };
}

export function decodeJson(payload: Uint8Array): Record<string, unknown> {
  let data: unknown;
  try {
    data = JSON.parse(dec.decode(payload));
  } catch {
    throw new FrameError("the payload is not UTF-8 JSON");
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    throw new FrameError("the payload is not a JSON object");
  }
  return data as Record<string, unknown>;
}

export function encodeJson(kind: number, stream: number, data: object): Uint8Array {
  return encode(kind, stream, enc.encode(JSON.stringify(data)));
}

export function encodeReq(
  stream: number,
  method: string,
  path: string,
  headers: HeaderPairs,
  body: Uint8Array = new Uint8Array(),
): Uint8Array {
  const meta = enc.encode(JSON.stringify({ m: method, p: path, h: headers, bl: body.length }));
  const payload = new Uint8Array(4 + meta.length + body.length);
  new DataView(payload.buffer).setUint32(0, meta.length);
  payload.set(meta, 4);
  payload.set(body, 4 + meta.length);
  return encode(T.REQ, stream, payload);
}

function pairs(value: unknown, what: string): HeaderPairs {
  if (!Array.isArray(value)) throw new FrameError(`${what} needs h`);
  return value.map((pair) => {
    const ok =
      Array.isArray(pair) && pair.length === 2 && pair.every((x) => typeof x === "string");
    if (!ok) throw new FrameError("a header is not a [name, value] pair");
    return [pair[0] as string, pair[1] as string];
  });
}

export function decodeReq(payload: Uint8Array): ReqFrame {
  if (payload.length < 4) throw new FrameError("a request has no JSON length");
  const size = new DataView(payload.buffer, payload.byteOffset, payload.byteLength).getUint32(0);
  if (size > payload.length - 4) throw new FrameError("the request JSON runs past the frame");
  const meta = decodeJson(payload.subarray(4, 4 + size));
  const body = payload.subarray(4 + size);
  const { m, p, bl } = meta;
  if (typeof m !== "string" || typeof p !== "string") throw new FrameError("a request needs m and p");
  const h = pairs(meta.h, "a request");
  if (bl !== body.length) throw new FrameError("bl does not match the body length");
  return { m, p, h, body };
}

export function encodeResHead(stream: number, status: number, headers: HeaderPairs, length: number | null): Uint8Array {
  return encodeJson(T.RES_HEAD, stream, { s: status, h: headers, bl: length });
}

export function decodeResHead(payload: Uint8Array): ResHead {
  const meta = decodeJson(payload);
  const { s, bl } = meta;
  if (typeof s !== "number" || !Number.isInteger(s) || s < 200 || s > 599) {
    throw new FrameError("s is not a status code");
  }
  const h = pairs(meta.h, "a response head");
  if (bl !== null && (typeof bl !== "number" || !Number.isInteger(bl) || bl < 0)) {
    throw new FrameError("bl is not a length or null");
  }
  return { s, h, bl };
}

/** HMAC-SHA256(secret, nonce || "brandcal-relay.v1"): the secret itself never crosses the wire. */
export async function proof(secret: Uint8Array, nonce: Uint8Array): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey("raw", secret, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const data = new Uint8Array(nonce.length + LABEL.length);
  data.set(nonce);
  data.set(LABEL, nonce.length);
  return new Uint8Array(await crypto.subtle.sign("HMAC", key, data));
}

export function toHex(bytes: Uint8Array): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function fromHex(hex: string): Uint8Array {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = Number.parseInt(hex.slice(2 * i, 2 * i + 2), 16);
  return out;
}

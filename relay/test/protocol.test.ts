import { describe, expect, it } from "vitest";
import vectors from "../../tests/data/relay_frames.json";
import {
  FrameError,
  MAX_FRAME,
  T,
  decode,
  decodeJson,
  decodeReq,
  decodeResHead,
  encode,
  encodeJson,
  encodeReq,
  encodeResHead,
  fromHex,
  proof,
  toHex,
} from "../src/protocol";

const text = new TextDecoder();
const kinds = T as Record<string, number>;

describe("golden vectors (shared with the Python connector)", () => {
  it("uses the same frame size limit", () => {
    expect(MAX_FRAME).toBe(vectors.max_frame);
  });

  for (const v of vectors.valid) {
    it(`decodes and re-encodes ${v.name}`, () => {
      const bytes = fromHex(v.hex);
      const frame = decode(bytes);
      expect(frame.kind).toBe(kinds[v.type]);
      expect(frame.stream).toBe(v.stream);
      if ("payload_hex" in v) {
        expect(toHex(frame.payload)).toBe(v.payload_hex);
        expect(toHex(encode(frame.kind, frame.stream, frame.payload))).toBe(v.hex);
      } else if ("json" in v && v.json) {
        expect(decodeJson(frame.payload)).toEqual(v.json);
        if (frame.kind === T.RES_HEAD) {
          const head = decodeResHead(frame.payload);
          expect(toHex(encodeResHead(frame.stream, head.s, head.h, head.bl))).toBe(v.hex);
        } else {
          expect(toHex(encodeJson(frame.kind, frame.stream, v.json))).toBe(v.hex);
        }
      } else {
        const req = decodeReq(frame.payload);
        expect(req.m).toBe(v.req.m);
        expect(req.p).toBe(v.req.p);
        expect(req.h).toEqual(v.req.h);
        expect(toHex(req.body)).toBe(v.req.body_hex);
        const again = encodeReq(frame.stream, req.m, req.p, req.h, req.body);
        expect(toHex(again)).toBe(v.hex);
      }
    });
  }

  for (const v of vectors.malformed) {
    it(`refuses ${v.name}: ${v.reason}`, () => {
      const bytes = fromHex(v.hex);
      if (v.where === "frame") {
        expect(() => decode(bytes)).toThrow(FrameError);
      } else {
        const frame = decode(bytes);
        expect(() => decodeReq(frame.payload)).toThrow(FrameError);
      }
    });
  }

  it("computes the HMAC proof the connector computes", async () => {
    const p = vectors.proof;
    const secret = new TextEncoder().encode(p.secret);
    const mac = await proof(secret, fromHex(p.nonce_hex));
    expect(toHex(mac)).toBe(p.hmac_hex);
  });

  it("uses the label from the vectors", () => {
    expect(vectors.proof.label).toBe("brandcal-relay.v1");
  });
});

describe("frame limits", () => {
  it("refuses to encode or decode a frame over 1 MiB", () => {
    expect(() => encode(T.RES_BODY, 1, new Uint8Array(MAX_FRAME - 4))).toThrow(FrameError);
    expect(encode(T.RES_BODY, 1, new Uint8Array(MAX_FRAME - 5)).length).toBe(MAX_FRAME);
    expect(() => decode(new Uint8Array(MAX_FRAME + 1))).toThrow(FrameError);
  });

  it("refuses a REQ whose encoded frame would pass 1 MiB", () => {
    const small = encodeReq(1, "POST", "/x", [["Host", "h"]], new Uint8Array(10));
    expect(small.length).toBeLessThan(MAX_FRAME);
    expect(() =>
      encodeReq(1, "POST", "/x", [["Host", "h"]], new Uint8Array(MAX_FRAME)),
    ).toThrow(FrameError);
  });

  it("round-trips a non-ASCII path and header as UTF-8", () => {
    const bytes = encodeReq(3, "GET", "/caf%C3%A9", [["Accept", "text/é"]], new Uint8Array());
    const req = decodeReq(decode(bytes).payload);
    expect(req.h).toEqual([["Accept", "text/é"]]);
    expect(text.decode(bytes)).toContain("caf");
  });
});

describe("RES_HEAD", () => {
  const head = (obj: unknown) => new TextEncoder().encode(JSON.stringify(obj));

  it("accepts a null length", () => {
    expect(decodeResHead(head({ s: 308, h: [["Location", "/mvp/"]], bl: null })).bl).toBeNull();
  });

  it.each([
    ["status below 200", { s: 100, h: [], bl: 0 }],
    ["status above 599", { s: 600, h: [], bl: 0 }],
    ["status not an integer", { s: "200", h: [], bl: 0 }],
    ["header not a pair", { s: 200, h: [["a"]], bl: 0 }],
    ["header not text", { s: 200, h: [["a", 1]], bl: 0 }],
    ["negative length", { s: 200, h: [], bl: -1 }],
    ["fractional length", { s: 200, h: [], bl: 1.5 }],
    ["missing headers", { s: 200, bl: 0 }],
  ])("refuses %s", (_name, obj) => {
    expect(() => decodeResHead(head(obj))).toThrow(FrameError);
  });
});

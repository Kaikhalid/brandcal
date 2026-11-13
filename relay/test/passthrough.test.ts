import { evictDurableObject } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { T, decodeJson, encode, proof } from "../src/protocol";
import { Fake, SECRET, browser, stub, useHarness, utf8 } from "./support";

useHarness();

describe("redirects", () => {
  it("passes a 308 from brandcal to the browser instead of following it", async () => {
    const fake = await Fake.ready();
    const pending = browser("/mvp", { redirect: "manual" });
    const req = await fake.nextOf(T.REQ);
    fake.respond(req.stream, 308, [["Location", "/mvp/"]]);
    const res = await pending;
    expect(res.status).toBe(308);
    expect(res.headers.get("Location")).toBe("/mvp/");
    expect(await fake.quiet()).toBe(true); // no second request was made
  });
});

describe("hibernation", () => {
  it("keeps an authenticated connector across eviction of the Durable Object", async () => {
    const fake = await Fake.ready("brandcal-relay/1.2.3");
    await evictDurableObject(stub());
    const health = (await (await browser("/_relay/health")).json()) as Record<string, unknown>;
    expect(health.connected).toBe(true);
    expect(health.agent).toBe("brandcal-relay/1.2.3");
    const pending = browser("/after-sleep");
    const req = await fake.nextOf(T.REQ);
    fake.respond(req.stream, 200, [["Content-Type", "text/plain"]], [utf8("awake")]);
    expect(await (await pending).text()).toBe("awake");
  });

  it("finishes a handshake that was interrupted by eviction", async () => {
    const fake = await Fake.open();
    fake.hello();
    const nonce = (await fake.nextOf(T.CHALLENGE)).payload;
    await evictDurableObject(stub());
    fake.send(encode(T.PROOF, 0, await proof(utf8(SECRET), nonce)));
    expect(decodeJson((await fake.nextOf(T.READY)).payload).v).toBe(1);
  });

  it("keeps the stream id counter across eviction", async () => {
    const fake = await Fake.ready();
    const first = browser("/first");
    const req1 = await fake.nextOf(T.REQ);
    expect(req1.stream).toBe(1);
    fake.respond(req1.stream, 200, [], [utf8("first")]);
    expect(await (await first).text()).toBe("first");
    await evictDurableObject(stub());
    const second = browser("/second");
    const req2 = await fake.nextOf(T.REQ);
    expect(req2.stream).toBe(2);
    fake.respond(req2.stream, 200, [], [utf8("second")]);
    expect(await (await second).text()).toBe("second");
  });
});

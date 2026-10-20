# brandcal relay (Cloudflare Worker)

The Worker and Durable Object for the U4 relay. The box cannot reach a Cloudflare tunnel edge, so
`brandcal relay` (the connector, `src/brandcal/relay.py`) dials out over port 443 and keeps one
WebSocket open to the Durable Object. The Worker takes each browser request, sends it down that
socket, and streams the answer back. Cloudflare Access stays in front of the browser host, and
`brandcal serve` still verifies the Access JWT itself; the Worker only checks that the header is
present and shaped like a JWT.

| File | What it holds |
|---|---|
| `src/index.ts` | Host routing, request checks, header allow-list |
| `src/relay_do.ts` | Durable Object `Relay`: connector socket, handshake, streams |
| `src/protocol.ts` | Frame encode and decode (protocol v1, mirrors the Python module) |
| `src/headers.ts`, `src/pages.ts` | Header allow-lists; self-made pages, time format and log line |
| `wrangler.jsonc` | Placeholder hosts only. The real config lives outside the repo |

## Test

From the repository root:

```sh
npm --prefix relay ci
npm --prefix relay run typecheck
npm --prefix relay test
```

The tests run in Miniflare through `@cloudflare/vitest-pool-workers`, with a fake connector that
speaks the protocol. They share `tests/data/relay_frames.json` with the Python tests, so the two
implementations cannot drift. The display offset (`DISPLAY_UTC_OFFSET`) and the secret are supplied
by `vitest.config.ts`; the repo has no timezone default and holds no real secret.

Nothing here talks to Cloudflare. Deploying, secrets and the cutover are described in
`docs/DEPLOY_RELAY.md`, including the fresh API token needed for every deploy.

## Configuration

- `PUBLIC_HOST` and `RELAY_HOST`: the browser host and the connector host (vars).
- `DISPLAY_UTC_OFFSET`: for example `+03:00`, set in the private deployment config. If it is
  missing or malformed, every request gets 500 `RELAY_MISCONFIGURED`.
- `RELAY_SECRET`: a secret, set with `wrangler secret put`. It is never in a file in the repo.

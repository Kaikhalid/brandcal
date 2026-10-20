# `brandcal relay`: the connector for the Worker relay

`brandcal relay` dials out to the Cloudflare Worker relay over one WebSocket on port 443 and
replays each browser request against `brandcal serve` on `127.0.0.1`. It is for hosts that
cannot reach a Cloudflare Tunnel edge. Every host, path and id below is a placeholder:
`brandcal.example.com` is the UI host, `brandcal-relay.example.com` the connector host.

It speaks protocol `brandcal-relay.v1`. The frame format is pinned by the golden vectors in
`tests/data/relay_frames.json`; the Worker's tests read the same file.

## The `relay` block

Add it to `BRANDCAL_HOME/config.json`, next to `serve`:

```json
"relay": {
  "url": "wss://brandcal-relay.example.com/_relay/connect",
  "public_host": "brandcal.example.com",
  "secret_file": "/cursor/stores/<store-id>/secrets/brandcal_relay_secret",
  "access_token_file": "/cursor/stores/<store-id>/secrets/brandcal_relay_access.json",
  "max_response_mb": 32
}
```

- `url` must be `wss://`. The one exception is `ws://127.0.0.1:PORT/...` together with
  `--local-dev` (for `wrangler dev`). Anything else is `BAD_ARGS`, exit 2.
- `public_host` must equal the host (with the port, if any) of one of `serve.allowed_origins`.
  The connector writes it as the `Host` header, and refuses (`BAD_FRAME`) any request whose
  `Host` differs, so `brandcal serve`'s Host, Origin and CSRF checks work unchanged.
- `serve.port` is where requests are replayed; the host is always `127.0.0.1` and cannot be
  configured.
- `max_response_mb` (default 32) caps one response; past it the request ends with `TOO_LARGE`.

## Secret files

Both files are read **once**, at start-up, and kept in memory only. Replace a file and restart
the connector to pick it up. There is no mode check, because the secret store cannot be
`chmod`-ed.

- `secret_file`: the shared relay secret, as text. Surrounding whitespace is ignored.
- `access_token_file`: the Cloudflare Access service token, as JSON:

  ```json
  {"client_id": "<id>.access", "client_secret": "<secret>"}
  ```

  They are sent as the `CF-Access-Client-Id` and `CF-Access-Client-Secret` headers on the
  upgrade request. With `--local-dev` on `ws://127.0.0.1`, the file (and the key) may be left
  out: `wrangler dev` has no Access. The relay secret is still required.

A missing, unreadable or empty file, or a malformed token file, stops the connector with
`SECRET_UNAVAILABLE` (exit 2). The message names the path and never the contents.

## What crosses

Request headers replayed: `Cf-Access-Jwt-Assertion`, `Origin`, `Content-Type`, `Accept`,
`X-Brandcal-CSRF`, plus `Host` (see above). `Content-Length` is recomputed. Everything else is
dropped: cookies, `Authorization`, `Cf-Access-Authenticated-User-Email`, client addresses,
`X-Forwarded-*`, hop-by-hop headers. Only `GET` and `POST` are replayed, and a path must start
with `/` and hold no control character, space or non-ASCII character.

Response headers kept: `Content-Type`, `Content-Length`, `Content-Security-Policy`,
`X-Content-Type-Options`, `Referrer-Policy`, `Cache-Control`, `Location`, `Allow`,
`X-Brandcal-Exit`. Bodies stream back in chunks of at most 256 KiB.

A request that cannot be answered ends with `RES_ERR`: `UPSTREAM_DOWN` (no connection to
`serve` within 2 s, or it dropped), `UPSTREAM_TIMEOUT` (no complete answer within 25 s),
`TOO_LARGE`, or `BAD_FRAME`.

## Running and exit codes

```sh
BRANDCAL_HOME=/srv/brandcal brandcal relay --as admin-1
```

It needs the `admin` role, like `serve`, and runs until stopped. Human logs go to stderr; one
JSON line goes to stdout on exit.

| Exit | Cause | Code |
|---|---|---|
| 0 | SIGTERM or SIGINT (closes the socket with 1000) | none (`{"ok": true, "stopped": true}`) |
| 2 | bad config; missing secret file; close 4002 | `BAD_ARGS`, `SECRET_UNAVAILABLE`, `PROTOCOL_MISMATCH` |
| 4 | HTTP 401 or 403 on the upgrade, or close 4003 | `CONNECTOR_REFUSED` |
| 8 | close 4001: a newer connector replaced this one | `CONNECTOR_REPLACED` |

Any other disconnect reconnects with exponential backoff and full jitter: a random delay up to
1 s, doubling to 60 s, reset after 5 minutes connected. A supervisor script must not restart
the connector after exit 2, 4 or 8. Liveness: a protocol ping every 20 s, the text `ping` every
60 s, and a reconnect after 45 s without any frame.

## Log format

One line per event, on stderr, with the time in ISO 8601 with the display offset from
`timezone` in `config.json` or `BRANDCAL_TZ` (for example `+03:00`):

```
2026-10-24T09:15:02+03:00 connected ready
2026-10-24T09:15:07+03:00 stream=7 method=GET path=/api/session status=200 ms=12 bytes=168 outcome=ok
2026-10-24T09:16:40+03:00 disconnect close=1012 backoff=0.37s
```

The query string is never logged, nor any header value, body, token, secret, cookie, email or
client address.

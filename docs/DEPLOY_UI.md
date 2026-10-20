# Deploying the web UI behind Cloudflare Tunnel and Access

This is the generic recipe from UI_SPEC 2.8. Every host, email and id below is a placeholder:
`brandcal.example.com` is your UI hostname, `example.cloudflareaccess.com` your Zero Trust team
domain, `approver@example.com` the approver, `TUNNEL_ID` and `AUD_TAG` the values Cloudflare
gives you. Never commit the real ones; keep them in `BRANDCAL_HOME/config.json` only.

`brandcal serve` binds to 127.0.0.1 and is never reachable from the internet directly. The
only way in is the tunnel, and Access sits in front of the tunnel. brandcal still checks the
Access JWT itself on every request (UI_SPEC 2.3), so a request that somehow bypasses Access is
refused with `IDENTITY_UNVERIFIED`.

## 1. Before you start

- A Cloudflare zone for the hostname (here `example.com`), with DNS on Cloudflare.
- Zero Trust enabled on the account, with a team name (this gives the team domain
  `example.cloudflareaccess.com`). The dashboard asks you to pick a plan the first time; that
  choice is yours, brandcal needs nothing beyond Access for a few users.
- brandcal with the crypto extra: `pip install "brandcal[crypto]"`. Without it, verified mode
  refuses to start with `EXTRA_NOT_INSTALLED`.

## 2. Configure brandcal

Add a `serve` block to `BRANDCAL_HOME/config.json` (UI_SPEC 2.6):

```json
"serve": {
  "port": 8787,
  "allowed_origins": ["https://brandcal.example.com"],
  "identity": {
    "team_domain": "example.cloudflareaccess.com",
    "audience": "AUD_TAG",
    "jwks_cache_minutes": 60
  },
  "approvers": {"approver@example.com": "approver-1"},
  "viewers": ["viewer@example.com"],
  "console_agent": "console"
}
```

- `team_domain` is the bare host, with no `https://` and no trailing slash; brandcal builds
  the issuer `https://example.cloudflareaccess.com` and the key URL
  `https://example.cloudflareaccess.com/cdn-cgi/access/certs` from it.
- `audience` is the AUD tag of the Access application (step 4). Fill it in, then restart.
  brandcal accepts a token only if its `aud` is exactly this tag: a string, or a list holding
  that one entry. A token for any other application, or for this one plus others, is refused
  with `IDENTITY_UNVERIFIED`.
- `approver-1` must be an agent with role `approver`; `console` an agent with role `system`.
- Emails are matched case-insensitively.

Run it as a service under a dedicated user, with `BRANDCAL_HOME` set:

```sh
BRANDCAL_HOME=/srv/brandcal brandcal serve
# brandcal serve: listening on http://127.0.0.1:8787
```

Config is read once at start; restart after every change.

## 3. Create the tunnel

Use a remotely managed tunnel (configured in Cloudflare, run with a token):

1. Zero Trust, Networks, Tunnels: create a tunnel of type Cloudflared, for example
   `brandcal`. Cloudflare shows a tunnel token. Save it to a file readable only by the
   service user (`chmod 600`) and never paste it anywhere else.
2. Public hostname (ingress): `brandcal.example.com` to service `http://127.0.0.1:8787`.
   Leave the catch-all rule as `http_status:404`, so no other hostname reaches anything.
3. The dashboard adds a proxied DNS record `brandcal` CNAME `TUNNEL_ID.cfargotunnel.com`. If
   you configure it by API, add that one record yourself; touch no other record.
4. Install `cloudflared` from Cloudflare's official release and run it:

   ```sh
   cloudflared tunnel run --token-file /etc/brandcal/tunnel_token
   ```

   `--token-file` keeps the token out of the process list. Run it as a service next to
   `brandcal serve`.

## 4. Protect it with Access

1. Zero Trust, Access, Applications: add a self-hosted application for
   `brandcal.example.com` (the whole host, every path).
2. Session duration: 24 hours (decision 6; a Cloudflare setting, not brandcal's).
3. Identity: your identity provider with MFA, or One-time PIN (codes sent by email) if you
   have none. Turn off instant auth to other providers you do not want here.
4. Policy: action Allow, include only the approver and viewer emails
   (`approver@example.com`, `viewer@example.com`). No "Everyone", no email domains.
5. Copy the application's **AUD tag** into `serve.identity.audience` and the team domain into
   `serve.identity.team_domain`, then restart `brandcal serve`.

## 5. Check it

```sh
# Not signed in: Access answers, brandcal is never reached.
curl -sI https://brandcal.example.com/
# HTTP/2 302, location: https://example.cloudflareaccess.com/cdn-cgi/access/login/...

# On the server, without a token: refused by brandcal itself.
curl -s http://127.0.0.1:8787/api/session
# {"ok": false, "error": {"code": "IDENTITY_UNVERIFIED", ...}}   (HTTP 401)

# A forged token is refused too.
curl -s -H 'Cf-Access-Jwt-Assertion: e30.e30.e30' http://127.0.0.1:8787/api/session
# IDENTITY_UNVERIFIED
```

Then open `https://brandcal.example.com/` in a browser, sign in through Access and open
`https://brandcal.example.com/api/session`: it shows your email, your role (`approver` or
`viewer`) and source `access-jwt`. The UI shows no red "UNVERIFIED (dev)" banner, and an
approver sees Approve on posts that are waiting. An email that passed Access but is in neither
`serve.approvers` nor `serve.viewers` gets `IDENTITY_UNMAPPED`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `serve` exits with `BAD_ARGS` "serve.identity.team_domain must be a bare host name" | `team_domain` has `https://`, `http://` or a slash; set the host alone, e.g. `myteam.cloudflareaccess.com` |
| Every request `IDENTITY_UNVERIFIED`, "signing keys could not be loaded" | `team_domain` is the wrong host, or the server cannot reach it |
| "The token is for a different application" | `audience` is not this application's AUD tag |
| "The token was issued by a different team" | `team_domain` is another team's |
| Writes get `BAD_ORIGIN` | `https://brandcal.example.com` missing from `serve.allowed_origins` |
| Cloudflare error 1033 | `cloudflared` is not running or not connected |
| 502 from the tunnel | `brandcal serve` is not running on the configured port |

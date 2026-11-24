# Changelog

All notable changes to brandcal are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - Unreleased

### Added
- Cloudflare Worker + D1 backend (`cloud/`) serving the Next.js static UI from Workers static
  assets and the full console JSON API from D1, with optimistic locking (`meta.gen`), Access JWT
  verification, per-page CSP hashes and a daily JSON backup cron to the `BACKUPS` KV namespace
  (#53).
- CLI remote mode (`BRANDCAL_REMOTE`, `BRANDCAL_ACCESS_CLIENT_ID`,
  `BRANDCAL_ACCESS_CLIENT_SECRET`): runs commands through the full Python core on a pulled
  snapshot and pushes verified row diffs back via `/api/sync/apply`, plus `brandcal pull --out`
  for read-only local copies (#53).
- Conformance test suite (`tests/test_cloud_conformance.py`) verifying API and CLI parity
  between `brandcal serve` (SQLite) and the Cloudflare Worker (local D1) (#53).
- From-zero Cloudflare self-hosting guide (`docs/CLOUDFLARE_SETUP.md`), AI assistant integration
  guide (`docs/BOT_INTEGRATION.md`), root `.env.example`, `examples/config.serve.example.json`,
  and draft release notes (`docs/release-notes/v0.2.0.md`).
- `BACKUPS` KV binding placeholder in `cloud/wrangler.jsonc`.
- Documentation clarifying that `posts.extras` is a frozen one-time snapshot from v1 import and
  must never be preferred over v2 columns.
- Web UI screenshots (Example Co demo data) in `docs/img/`, plus GitHub issue and pull request
  templates.

### Changed
- Rewrote `README.md` to lead with Cloudflare Workers + D1 self-hosting, remote AI assistant
  usage and local SQLite quick start, with a plain Status section.
- Updated `SECURITY.md` to list `0.2.x` as the supported release series.
- Updated package classifier in `pyproject.toml` from Pre-Alpha to Alpha.

### Fixed
- `brandcal next` and weekly report sorting no longer crash on imported or idea posts that have
  no time slot (`window IS NULL`); unscheduled posts sort last (#54).

### Deprecated
- Single-machine Cloudflare Tunnel (`docs/DEPLOY_UI.md`) and Worker relay (`docs/DEPLOY_RELAY.md`,
  `docs/RELAY_CONNECTOR.md`, `relay/`) hosting paths are marked as historical reference, replaced
  by the Cloudflare Worker + D1 setup in `docs/CLOUDFLARE_SETUP.md`.

## [0.1.4] - 2026-11-14

### Changed
- Relay connector reconnects after 60 s without an app-level reply (text pong or binary frame),
  sending a text ping every 20 s so half-open links are detected reliably (#51).

### Added
- Optional `BRANDCAL_RELAY_HEARTBEAT` file touched on app-level replies for external watchdogs
  (#51).

## [0.1.3] - 2026-11-14

### Changed
- Updated app icon artwork with full-bleed opaque iOS icons, 192/512 icons, maskable 512 icon
  and favicon (#49).

### Added
- `make_icons.py` helper to rebuild icons from source artwork (#49).

## [0.1.2] - 2026-11-14

### Added
- `brandcal migrate` accepts the bare JSON array v1 calendar format and maps `posted_url` to
  `platform_url` (#45).
- `brandcal migrate --legacy-approved` imports already-approved v1 rows with a recorded legacy
  approval (#46).
- App icons, web manifest (`.webmanifest` served as `application/manifest+json`) and passkey
  sign-in notes for phone approvers (#47).

## [0.1.1] - 2026-11-13

### Security
- Upgraded `next` and `eslint-config-next` from 16.4.0 to 16.4.6 to address known advisories,
  and rebuilt the committed static export (#43).

## [0.1.0] - 2026-11-13

### Added
- Initial public release of brandcal with Example Co test data.
- Python CLI implementing the 6-state content calendar model, per-post approvals bound to content
  hash and time window, explicit UTC offsets, append-only hash-chained audit log, backups,
  archiving and v1 migration.
- Next.js static web UI (`brandcal serve`) behind Cloudflare Access, with `serve.console_approvals`
  off by default.
- Cloudflare Worker + Durable Object relay (`relay/` and `brandcal relay`) for hosts restricted
  to outbound port 443.

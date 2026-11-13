# Examples

All data here is obviously fake (**Example Co**, `example.com`).

- `config.json` and `platforms.json`: a minimal data-directory configuration (SPEC 13),
  used by the README quick start.
- `posts/example-launch.json`: one post to pipe into `brandcal add`.
- `v1_calendar.example.json`: a calendar in the generic v1 JSON format that
  `brandcal migrate` imports (SPEC 12), as a JSON object with an `items` list. It covers
  posted items with the three `posted_at` formats and a missing URL, approved but unposted
  items, an idea, a draft, a skipped item, thread bodies with `1/` markers and `.md` and
  image assets. A bare JSON array is also accepted. Ideas and drafts are imported as
  `pending_approval` (SPEC 12).
- `sample_calendar.json`: an illustration of v2 calendar data (ISO 8601 times with explicit
  offsets, windows as ISO intervals, different states). Illustrative only.

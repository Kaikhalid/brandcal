# Direction A: quiet command bar (week stacks)

Built on the shared foundation (FOUNDATION.md), branch `ui-dir-a`. The calm, calendar-first baseline.
The foundation already gave one 64 px toolbar, the 32 px strip, the Filters popover, the Needs you chip,
the container-width hook, pinned panel actions and the fixed collapsed rail. This branch replaces the
week and month bodies and finishes the direction around them.

## Concept

The week is seven time-ordered stacks, one well per day, with no hour axis. Eleven posts a week and
one-hour windows never needed 24 hours of vertical space; they needed to be read in order. Each post is
a card (time and platform, title, status chip) and the whole week is on screen at once. The month uses the
same wells and cards, in rows that size to what they hold. Everything else (toolbar, strip, filters,
panel) is the foundation, unchanged.

## Layout per breakpoint

Measured on Example Co demo data (`measure.json` beside the screenshots). "Header" is the top of the
sticky day-header row; "first card" is the top of the first post card, as a share of viewport height.

| Viewport | Layout | Header | First card |
|---|---|---|---|
| 1440×900, sidebar open | 7 stacks, about 153 px wells | 11.3% (102 px) | 16.7% (150 px) |
| 1440×900, rail | 7 stacks, about 190 px wells | 11.3% | 16.7% |
| 1440×900, panel open | day bands beside the 30 rem panel (box under 880 px), no sideways scroll | 10.7% | 17.3% |
| 1024×768, rail (automatic) | 7 stacks, about 122 px wells, titles up to 3 lines | 13.3% | 19.5% |
| 1024×768, sidebar opened by hand | day bands, cards flow in two columns | 12.5% | 20.3% |
| 390×844 | day bands, one column | 17.1% | 24.2% |

The brief's targets (first card at or below 17% at 1440×900 and 20% at 1024×768, header at or below 14%) are
met. With the sidebar opened by hand at 1024 the card row sits at 20.3%, a hair over the 20% figure, because
that box is 720 px and is a band layout; the header is at 12.5%. Under 880 px the calendar is bands by rule
(foundation S4), so seven columns at 1024 need the automatic rail.

- **Week stacks** (box of 880 px and up). One CSS grid of two rows: seven header cells (sticky, 48 px,
  `aria-hidden`, the sections carry the day name) over seven wells (`section[data-day]`, labelled with the
  day, `aria-current="date"` for today). The wells stretch to the foot of the calendar, so the week reads as
  seven columns even when a day is quiet.
- **Today**: black numeral circle, the word "Today" (it drops to screen-reader-only text when the column
  is narrower than 140 px), a `--muted` tint across header and well, and the thin "now" rule placed between the
  posts before and after the current minute (`aria-hidden`; a visually hidden "Now: 10:30" keeps the reading order).
- **Card**: platform pastel fill and printed platform name (no icon), time, post-type icon (hidden in a narrow
  well; the type stays as screen-reader text), title clamped to two lines, `StatusChip`, compact badges. The
  tooltip carries the title and the whole window with the zone offset (`Tue 10 Mar 2026, 10:00 to 11:00 (+01:00)`;
  the owner's `+03:00` once the zone is configured). No edge stripe anywhere.
- **Month**: wells for the days, rows sized to content (empty week 96 px, a busy week grows), titles wrap,
  the same cards, "+n more" after three. Days outside the month are outlined, not filled.
- **Day bands** (the phone, a wide box under 880 px): each day's cards flow in
  `repeat(auto-fill, minmax(16rem, 1fr))`, so a box of 700 px gets two columns instead of one 700 px-wide card.
- **Rail, toolbar, strip, filters, Needs you chip, panel**: the foundation, untouched.

## What changed (files)

- `web/components/calendar-view.tsx`: `WeekGrid` and `Block` and the lane-overlap code (`place`) are gone.
  New `WeekStacks`, `StackCard`, `NowRule`, `windowTip`; `MonthGrid` rebuilt on the same cards; the day
  bands flow in columns; `Card` lost its `compact` mode.
- `web/components/platform-swatch.tsx`: `PlatformMark` takes `bare` (name only).
- `web/app/globals.css`: the `.hour-grid` rule is removed.
- `docs/UI_STYLE.md`: the "Week stacks, no hour axis" paragraph in the layout section.
- Tests: `tests/ui/test_next_direction_a.py` (new, 18 tests); `test_next_views.py`, `test_next_foundation.py` and
  `test_next_a11y.py` updated where they asserted an hour grid or the now line's hour position.

## The collapsed sidebar

Fixed by the foundation (label `sr-only` in the rail, gap 0, count outside the badge with a dot, tooltips,
footer with avatar and theme menu, 300 ms `--ease-out`, saved state, auto-rail at 768 to 1179 px). This
branch keeps it working with the new body: collapsing at 1440 widens the stacks from about 153 to about 190 px
(`test_the_rail_widens_the_columns`), and axe is clean on the stacks with the rail collapsed, both themes. The
foundation's rail geometry test stays green.

## Trade-offs and risks

- **No time axis**: gaps between posts no longer show how far apart they are in the day; the order and the
  printed time carry it. Two posts at the same minute stack one after the other, never side by side.
- **Narrow wells at 1024**: about 98 px of card text. A long word is hyphenated (`hyphens: auto`, `lang="en-GB"`),
  titles go to three lines, status chips like "Awaiting you" wrap to two lines. Past that the title is clamped (the
  tooltip and the panel hold the whole text).
- **The panel turns the week into bands** (it must, at 1440 with the sidebar open the box is about 650 px). The
  selection keeps its 2 px ink outline and focus returns to the card on close (`settleFocus`).
- **Month, leading weeks**: the empty weeks before the first post stay (96 px each), so on a month that has data
  only in one week the first card is well below the fold. Real months fill the rows. Scrolling to today's week
  on load would fix it and was left out to keep the first row visible, as the brief asks.
- **Sticky headers are `aria-hidden`**: they repeat what each section's label says; today is announced through
  `aria-current="date"` on the section.

## Iteration notes

First shots, then fixes:

1. At 1024 with the rail, "Published", "Cancelled" and "Partner announcement" spilled past the card edge. The
   card now uses `wrap-anywhere`, hyphenation, 8 px padding and a smaller chip right padding in a narrow well, the
   gaps and well padding tighten by 2 px under 60 rem, and a test asserts nothing inside a card passes its edge at
   1440 and 1024.
2. Row 1 wrapped unevenly ("YouTube" pushed the type icon to a second line). The generic megaphone icon is gone
   from the platform name in stacks and the type icon hides in a narrow well, so every card starts with one clean
   line.
3. With the sidebar open at 1024 the bands were one 700 px-wide card per row, mostly empty. They now flow in
   columns of at least 16 rem.
4. Today was never visible in the demo (its week is in March), so a clock-pinned shot and test cover the numeral,
   the word, the tint and the now rule.

## Screenshots

`/workspace/brandcal_ui_shots/dirs/a/` (script `shots/a/test_shots.py`; no console errors), each in `light` and
`dark`: `week-1440-<theme>`, `week-1440-<theme>-collapsed`, `week-1024-<theme>` (sidebar opened by hand),
`week-1024-<theme>-collapsed`, `month-1440-<theme>`, `month-1440-<theme>-collapsed`, `month-1024-<theme>`,
`month-1024-<theme>-collapsed`, `week-today-1440-<theme>`, `week-390-<theme>`, `month-390-<theme>`,
`sheet-390-<theme>`, `panel-1440-<theme>`, `panel-1024-<theme>`, `panel-390-<theme>`, `approve-1440-<theme>`,
`filters-1440-<theme>`, `filters-1024-<theme>`, `needs-you-chip-1440-<theme>`, `rail-closeup-<theme>`, and
`measure.json`.

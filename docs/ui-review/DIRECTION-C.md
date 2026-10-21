# Direction C: Channel lanes

Built on the shared foundation (FOUNDATION.md) on branch `ui-dir-c`. EVALUATION.md section 8 "C" is the spec.

## Concept

The week is a map of channels: **a row per platform, a column per day**. A gap in a channel's cadence is a
blank cell, so "is LinkedIn covered on Thursday?" is answered by looking, not by reading. The lane label is
also the platform filter, so the Platform half of the Filters popover is gone while the lanes are on screen.
Planning and coverage come first; filtering is the second job of the same control.

## Layout per breakpoint

Widths are the calendar box (the shell column minus gutters), not the window, so an open panel is handled.

| Where | What you get |
|---|---|
| 1440 × 900, sidebar open (box 1136 px) | Lane label 120 px, seven days of about 143 px. Five lanes, the grid starts at 96 px (10.7%) and ends at 884 px (the last lane at 876), so the whole week is on screen and nothing scrolls. Lanes stretch to share the spare height. Cards print time, type icon, title (2 lines) and the status chip. |
| 1440 × 900, rail (box 1328 px) | Days of about 170 px; the type word returns beside the icon (from 1300 px of shell width). |
| 1024 × 768, rail (automatic; box 912 px) | Label column 96 px (no dot), days of about 114 px. Grid starts at 96 px (12.5%). Five lanes need about 830 px (the grid has 656), so the grid scrolls inside its own region (sticky day header); the page never scrolls. |
| Box under 880 px (sidebar opened at 1024, panel open at 1440, 768) | The day list, with the channel printed on every card. The Platform half of Filters is back in the popover here. |
| 390 × 844 | The day list (unchanged). |
| Month | A content-sized grid: weeks take the height their posts need (`min-h-24`), titles wrap to two lines, the platform is printed on each card. No fixed rows, no sideways scroll above 880 px; the day list below. |

**Lane label** (`data-lane-toggle`): a button with `aria-pressed`, the platform name and its post count. Name: "Show
only LinkedIn 5 posts" (the visible words are contained in it: WCAG 2.5.3). Pressing it filters the calendar to
that channel; pressing others adds them. The unselected lanes fold to a 48 px row with "Hidden: press the channel
name to add it", so they stay one press away. The strip then reads `+01:00 · 5 posts · … · Showing: [LinkedIn ×]
Show all`; the chips reuse `data-filter-chip="platform:x"`. The URL is the state (`?platform=linkedin`).

**Cells**: lane wells are `rounded-inner` (20 px) with hairline day separators; today's column is tinted and its
header carries the ink circle plus the word "Today" from 1100 px (read by assistive technology at any width). Cards are the
platform pastel with `rounded-control`; more than two in a cell shows `+n more`, a 24 px-plus popover list. An empty cell is one
quiet dash (`aria-hidden`), because gaps are the signal.

**Semantics**: the region "Week calendar" holds `role=table` with column headers (days), row headers (lane
labels) and cells. Tab order is lane by lane: label, then that lane's cards left to right.

## What changed (files)

| File | Change |
|---|---|
| `web/components/lane-grid.tsx` (new) | `LaneGrid`, `LaneLabel`, `MoreCell` (popover list), `LaneShowing` (the strip's "Showing" chips). |
| `web/components/calendar-bits.tsx` (new) | `Entry`, `DayNumber` (now with `word="wide"`), `PostCard` (the lane, month and popover card). |
| `web/components/calendar-view.tsx` | Rewritten: the hour grid, `Block`, `place()` and the now line are gone. Lanes in the week when the box is 880 px or more; `MonthGrid` content-sized; `DayList` unchanged in idea. Posts are filtered in two steps (everything but the channel, then the channel) so every lane can count its own posts. `hideFilters` and `FilterStrip hide` pass `platform` only while lanes show. |
| `web/components/filters-popover.tsx` | `Filters (n)` no longer counts a half the page replaces. |
| `web/app/globals.css` | `.hour-grid` removed (nothing uses it). |
| `tests/ui/test_next_lanes.py` (new) | 14 tests: layout at 1440 and 1024, lane toggle by keyboard, gaps and cards, collapsed rail, day list, month, `+n more`, axe in both themes (all, solo, rail collapsed, popover). |
| `tests/ui/test_next_views.py`, `test_next_foundation.py`, `test_next_a11y.py` | Updated for lanes (lane cell not hour offset; lane toggle not the platform checkbox; no now line, so today's header is asserted instead; `ALLOWED_SCROLL` is now just the Posts table). |

No API, dependency or `lib/` change. The built `src/brandcal/web_next/` is regenerated.

## The collapsed sidebar

Fixed by the foundation (FOUNDATION.md, "The sidebar fix"): `sr-only` label, no gap, count dot, tooltips, footer
theme menu, 300 ms width motion, persisted state. C keeps it working: `test_the_collapsed_sidebar_gives_the_lanes_more_room_and_nothing_overflows`
collapses the rail and checks that day columns grow (143 to 170 px), the lanes still fit, the page does not scroll sideways, and a lane label
takes focus beside the rail. The foundation's rail geometry, tooltip and axe tests are unchanged and green.

## Trade-offs and risks

- **1024 × 768 scrolls inside the grid.** The five lanes want about 830 px at 114 px-wide days (status chips wrap to two lines). The header stays
  sticky and the first four lanes are visible. Options if this matters: fewer default lanes (hide a channel with no posts in the
  week), or a denser card at narrow widths.
- **No hour axis.** The cards show the start time only; the full window with its offset is the card's `title`. The now line is gone (the
  today column replaces it).
- **Lanes grow with the platform list.** Each platform in the schema is a row; ten channels would scroll at any size.
- **A busy channel-day** shows two cards and `+n more`.
- **Channel filter and the popover split by width.** At 880 px or less the Platform checkboxes return to the popover, so a filter set in
  one layout shows as a chip in the other.
- The demo zone is `+01:00`; the strip prints whatever offset the schema carries (`+03:00` in the configured site).
- `line-clamp-2` on card titles: the whole title is in the card's `title` and in the panel.

## Iteration notes

First screenshot pass (light 1440 and 1024) found, and the second pass fixed:

1. Lane names truncated at 1024 ("Linke…"): the dot is hidden under 1100 px and padding tightened.
2. Type word cut ("comme…") at 143 px days: shown only from 1300 px of shell width, otherwise icon plus a screen-reader word.
3. Status chips overflowing 101 px cards at 1024: card, cell and chip padding reduced at narrow widths; titles break anywhere
   rather than overflow.
4. Dead space under the lanes at 1440: the grid fills the box and the lanes share the spare height (not when a channel is soloed).
5. "Channel" header caption sat higher than the day labels: centred.
6. Axe `label-content-name-mismatch` on the lane buttons (an `aria-label` that did not hold the visible words): the name now comes from
   the content with a screen-reader "Show only".
7. Folded lanes said "2 posts hidden" beside "2 posts": now "Hidden: press the channel name to add it".

## Screenshots

`/workspace/brandcal_ui_shots/dirs/c/` (script `/workspace/dev/brandcal_dirs/shots/c/test_shots.py`; `measure.json` holds the geometry).
Names are `<view>-<width>-<theme>[-collapsed].png`.

- Week: `week-1440-{light,dark}`, `week-1440-{light,dark}-collapsed`, `week-1024-{light,dark}` (sidebar opened by hand: day list), `week-1024-{light,dark}-collapsed` (lanes), `week-390-{light,dark}`
- Soloed channel: `lanes-solo-{1440,1024}-{light,dark}`
- Month: `month-{1440,1024}-{light,dark}`, `month-{1440,1024}-{light,dark}-collapsed`, `month-390-{light,dark}`
- Panel: `panel-{1440,1024,390}-{light,dark}`; approve dialog: `approve-1440-{light,dark}`
- Filters popover: `filters-open-{1440,1024}-{light,dark}`; Needs you pressed: `needs-you-1440-{light,dark}`
- Phone sheet: `sheet-390-{light,dark}`; rail close-up: `rail-closeup-{light,dark}`

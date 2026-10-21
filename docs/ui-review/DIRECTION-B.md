# Direction B: Inspector rail (day bands and the Needs you queue)

Built on the shared foundation (FOUNDATION.md) from EVALUATION.md section 8, "B. Inspector rail".
Approval workflow first: spot what needs Kai, open it, decide, and land on the next one without
leaving the calendar.

## Concept

The calendar is seven **day bands**; beside it sits a **persistent right-hand rail**. By default the
rail is the Needs you queue (Missed, Changes requested, Awaiting you, most urgent first). Picking a
post, from the queue or from a card, turns the rail into that post's detail with the actions on top.
Deciding (approve, request changes, cancel) moves the rail on to the next item of the queue, so a
run of approvals is a run of clicks in one place. Back returns to the queue.

## Layout per breakpoint

| Viewport | Layout |
|---|---|
| 1440 and up | Sidebar 256 px (or 64 px rail), calendar bands about 720 px, rail 26 rem (416 px) beside it. Collapsing the sidebar gives the calendar about 912 px and the month a real grid. |
| 1180 to 1439 | Same, with a 22 rem rail. |
| 768 to 1179 | No rail column. The toolbar has an amber **Needs you N** button; it opens the queue as a sheet over the calendar (`?queue=1`, modal, Esc closes, focus returns to the button). A post opened from the sheet goes Back to the sheet. A post opened from a card is the existing panel sheet with a Close button. |
| under 768 | Day list (the same `DayBands` component, stacked, sticky day headings) and the same Needs you button and sheet. The sidebar is the existing sheet. |

The toolbar is the foundation's (title, range nav, Filters, Week/Month, theme toggle) without the
Needs you chip: at 1180 and up the rail is the chip, below it the button takes its place.

## What changed (files)

New:
- `web/components/day-bands.tsx`: `DayBands` (the week at every width and the phone list), `BandCard`, `DayNumber`.
  88 px label column (weekday, 24 px light numeral, the black circle and "Today" for today, a "Now 10:30"
  marker in today's label), cards in `flex-wrap` (168 px minimum, 320 px maximum), an empty day is one short line
  ("Nothing planned."). The band stacks under 34 rem of its own width (container query).
- `web/components/inspector-rail.tsx`: `QueueRail` (queue state, `j`/`k`, "All clear." state with the CLI hint),
  `RailButton` (below 1180 px), `useRail`, `railFrame` (the frame both rail states share).
- `web/components/needs-queue.tsx`: one shared read of the queue (provider in the shell, reloads after every write).
- `tests/ui/test_next_inspector.py`: the direction's gates (below).
- `docs/ui-review/DIRECTION-B.md`.

Changed:
- `web/components/post-panel.tsx`: on the calendar the panel is the rail's detail state (`rail`, `beside`
  props): Back to Needs you instead of Close, rail frame, and **advance after a decision** (the queue is
  snapshotted before the write, the move happens once the notice has been said and the dialog has closed).
  `Host` decides between detail, queue and nothing, and keeps the page behind inert whenever a sheet is open.
- `web/components/calendar-view.tsx`: week is always `DayBands`; month is a grid from 840 px of box width,
  otherwise bands; month cards use `StatusChip iconOnly`; the Needs you button replaces the chip below 1180 px.
- `web/components/calendar-toolbar.tsx`: additive `needsYou` prop (undefined keeps the chip).
- `web/components/status-chip.tsx`: additive `iconOnly` (icon in its fill, word kept for readers and the tooltip).
- `web/components/post-bits.tsx`: `focusPostLater(id, scope)`, `rememberOpener`.
- `web/components/app-shell.tsx`: `NeedsQueueProvider`.
- `web/lib/needs-you.ts`: `byUrgency`, `queuePosts`, `afterDecision`.
- Tests updated for the new design: `test_next_a11y.py` (card colour test scoped to `main`, now-marker, notice),
  `test_next_foundation.py` (rail instead of chip, bands with the panel open), `test_next_views.py`
  (cards scoped to `main`, Back instead of Close), `test_next_writes.py` (approve and cancel advance).
- `src/brandcal/web_next/`: rebuilt.

## The collapsed sidebar

The foundation's fix is unchanged and its test is green: the label is `sr-only` in the rail, gap 0, the
count is a dot with the sr text outside it, every item has a tooltip and is keyboard reachable, the footer
holds the avatar and a theme menu, width motion is 300 ms ease-out, and the state is persisted. With the
rail on the right, collapsing the left sidebar hands its 192 px to the calendar (bands about 912 px, the
month becomes a grid); a new test checks the rail stays 416 px wide at the right edge and nothing scrolls
sideways, in both themes.

## Trade-offs and risks

- **Below 1180 px there is no persistent queue.** It is one tap away (button with the count) but not always on.
- **Bands hide the time axis.** Overlap and gaps are read from the order and the times on the cards, not
  from position. The now line became a "Now 10:30" marker in today's label.
- **Month cells show the status as an icon** in its fill (the word is the tooltip and the reader text), because a
  120 px cell cannot hold "Changes requested". Week bands and the rail always print the word.
- **Advancing is a deliberate surprise.** After a decision the panel shows a different post. It says so in the
  notice ("Approve: done. X is now Approved") and focus lands on the new heading. It only advances when the
  decided post was in the queue; a post opened from a card that is not in the queue stays put.
- The queue is read once per write (3 requests), the same cost as the sidebar badge.
- `j`/`k` respect typing and the single-key shortcuts switch (WCAG 2.1.4).
- Unused CSS (`.hour-grid`, `--hour`) is left in `globals.css` for the other directions that may still use it.

## Iteration notes

First pass to second, after looking at the screenshots:
1. An empty day was 82 px tall because the label column stacked weekday over numeral; empty days now put them
   side by side (60 px).
2. The rail's detail state lost its bottom padding (`p-4` overrode `pb-32` in `cn`), so the last disclosure sat
   under the notice card; fixed, and the notice test caught it.
3. The rail had no edge in light mode; added a hairline on its left.
4. The queue left the rail empty below its rows; added a quiet `j` / `k` hint (desktop only).
5. Platform names, the offset and the status stay printed on every card; nothing is carried by colour or an edge stripe.

## Screenshots

`/workspace/brandcal_ui_shots/dirs/b/` (script `shots/b/test_shots.py`; `measure.json` has the geometry). Names are
`<view>-<width>-<theme>[-collapsed].png`:

- `week-1440-{light,dark}`, `week-1440-{light,dark}-collapsed`, `week-1024-{light,dark}`, `week-1024-{light,dark}-collapsed`
- `month-1440-{light,dark}`, `month-1440-{light,dark}-collapsed`, `month-1024-{light,dark}`, `month-1024-{light,dark}-collapsed`
- `week-390-{light,dark}`, `month-390-{light,dark}`, `sheet-390-{light,dark}` (sidebar sheet)
- `panel-1440-{light,dark}` (rail detail), `panel-1024-{light,dark}`, `panel-390-{light,dark}`
- `approve-1440-{light,dark}` (approve dialog over the rail)
- `queue-sheet-1024-{light,dark}`, `queue-sheet-390-{light,dark}`
- `filters-open-1440-{light,dark}`, `filters-open-1024-{light,dark}`
- `rail-closeup-{light,dark}` (collapsed sidebar, crop 0 to 80 px)

Geometry at 1440×900 (sidebar open): grid top 96 px (10.7%), first day band at 104 px, rail 416 px wide, page does not scroll.
At 1024×768 (auto rail): grid top 96 px (12.5%). At 390×844: first day heading 152 px (18.0%).

## Tests

`tests/ui/test_next_inspector.py`: queue order and count; seven bands, first band in view, no sideways scroll, quiet empty day
(1440 and 1024); queue row to detail with actions in view, selected card and Back with focus; `j`/`k`; approve advances;
sheet below 1180 (button, focus, inert, Esc); phone day list; collapsed sidebar with the rail (both themes); axe in both
themes for queue, detail, collapsed and month; axe for the 1024 sheet.

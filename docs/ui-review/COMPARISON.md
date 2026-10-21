# UI directions compared: A, B, C

Task CMP. Review only; no code changed. Evidence: the three direction docs, the `measure.json` beside each set of
screenshots, 27 screenshots read from `/workspace/brandcal_ui_shots/dirs/{a,b,c}/`, and spot checks of the code in
the A worktree. Nothing was built or run for this review. Lens: Kai's taste (calendar is the hero, filters
secondary, balanced and minimal, shadcn, no coloured edge stripes, a collapsed sidebar that works, times carry an
offset) over the EVALUATION.md use-case model (section 4) and shared requirements S1 to S11 (section 7).

## 1. Summary and recommendation

**Recommendation: build on Direction A (quiet command bar, week stacks).** It is the only direction where the whole
week is on screen, with no scroll, at every default size (1440 open, 1440 collapsed, 1024 auto-rail, 390), it keeps
the calendar as the hero with the foundation's 64 px bar and 32 px strip above it, and it is the calmest and most
consistent between week and month. Its weaknesses are small and fixable: opening a post turns the week into a
long list, the 1024 wells are tight, and the cards carry no offset. B has the best approval flow (a persistent
Needs you queue that advances after each decision) but pays for it by squeezing the calendar to 720 px, so Sunday
is below the fold at 1440 and the month is not a month. C is the most striking at 1440 and answers "is LinkedIn
covered on Thursday?" at a glance, but at the default 1024 it scrolls inside its own grid and truncates titles.

**Borrow from the others:**
- From B: the "next in the queue after a decision" behaviour (`afterDecision` in `web/lib/needs-you.ts`, the queue
  snapshot in `post-panel.tsx`) and the `StatusChip iconOnly` variant for narrow cells.
- From C: the lane label as a platform filter, with the strip's "Showing: [LinkedIn ×] Show all" line, as a later
  optional third view (Week / Lanes / Month); and the `role=table` semantics with row and column headers.

## 2. Scoring (1 to 5, higher is better)

| | A | B | C |
|---|---|---|---|
| Balance and composition | 4 | 3 | 4 |
| Use-case fit | 4 | 4 | 3 |
| Visual quality | 4 | 3 | 4 |
| Accessibility (WCAG 2.2 AA) | 4 | 4 | 4 |
| Responsiveness | 4 | 3 | 3 |
| **Total (of 25)** | **20** | **17** | **18** |

All three share the same foundation bar, strip, filters popover, rail and panel actions, so the differences sit in
the week and month bodies and in how the panel is handled.

### Evidence per score

**Balance and composition**
- A, 4: `a/week-1440-light.png` shows seven equal wells under one calm bar; grid top 96 px (10.7%), first card at
  16.7% (`a/measure.json`). It loses a point because the wells run to the foot, so about 55% of each well is empty
  with 11 posts (the cards end near y=540 of 884).
- B, 3: `b/week-1440-light.png` is three columns (sidebar 256, calendar 720, rail 416; `b/measure.json`
  `grid.w` 720, `rail.w` 416). The calendar is about half the screen, Saturday is cut at the foot and Sunday is
  not visible. Several bands are half empty on the right (Mon, Sat).
- C, 4: `c/week-1440-light.png` fills the box exactly (`lastLaneBottom` 876 of 900, `gridScrolls` false), with no
  dead space. It loses a point for the field of about 24 dashes in empty cells, which is busier than "minimal".

**Use-case fit**
- A, 4: all 7 days, today marked (ink numeral, "Today", tint, now rule: `a/week-today-1440-light.png`), amber
  Needs you chip in the bar. Opening a post gives bands and loses the week (`a/panel-1440-light.png`).
- B, 4: the best on "spot it, decide it, land on the next". `b/panel-1440-light.png` shows the queue by
  urgency, then the detail with Approve first in the rail, and the calendar behind it does not reflow. It is weaker on
  "scan the week": `b/month-1440-light.png` (title "Mar 2026") is the week's bands again, not a month, because the
  box is 720 px (month grid needs 840 px); only the collapsed sidebar gives a grid (`month-1440-light-collapsed`).
  Below 1180 px the queue is a button and a sheet (`b/queue-sheet-1024-light.png`), not always on.
- C, 3: strongest for coverage and planning. Weaker on the rest: opening a post drops to a day list of 656 px
  wide cards (`c/panel-1440-light.png`), the default 1024 view scrolls inside the grid
  (`c/week-1024-light-collapsed.png`, `gridScrolls` true, Bluesky lane below the fold), and splitting the platform
  filter between the lane label and the popover by width is a mode change Kai would have to learn
  (`c/lanes-solo-1440-light.png`).

**Visual quality**
- A, 4: consistent pastel cards with printed platform name, clean today treatment, good dark mode
  (`a/week-1440-dark.png`). Blemishes: a lone icon pill with no label under some status chips (Thu "Partner
  announcement" in `a/week-1440-light.png`), and hyphenation at 1024 ("part-ner", "announce-ment" in
  `a/week-1024-light-collapsed.png`).
- B, 3: lovely 24 px light numerals and a well-set rail, good dark mode (`b/week-1440-dark.png`). But the same
  megaphone icon is repeated on every card (11 times), cards are wide and flat with large blank right halves,
  and the clipped last band looks unfinished.
- C, 4: the most distinctive and ordered at 1440 (`c/week-1440-light.png`, dark `c/week-1440-dark.png`). The month
  is a hairline grid (`c/month-1440-light.png`) that does not match the week's rounded wells, and 1024 has ellipsis
  titles ("announceme…", "Example…").

**Accessibility (WCAG 2.2 AA)**
- All three rely on the same foundation (focus return, `sr-only` rail labels, 24 px floor, axe in both themes) and each
  doc reports axe clean on its own states. No direction uses coloured edge stripes; status is a printed word plus icon.
- A, 4: 18 new tests (`test_next_direction_a.py`), a test that nothing passes a card edge at 1440 and 1024,
  `aria-current="date"`, `aria-hidden` sticky headers with labelled sections. Risk: about 98 px of text in 1024 wells.
- B, 4: the most careful interaction work: inert page behind sheets, Esc and focus return, `j`/`k` that respect
  the single-key switch (2.1.4), focus lands on the new heading with a notice after advancing. Risk: month cells show
  status as an icon with the word only in the tooltip and reader text.
- C, 4: the richest semantics (`role=table`, row and column headers, lane buttons with `aria-pressed`, 2.5.3 fixed
  after axe flagged it). Risk: an inner scroll region and ellipsis-truncated titles at 1024.

**Responsiveness**

| Viewport | A | B | C |
|---|---|---|---|
| 1440 open | 7 stacks, no scroll, first card 16.7% | bands, Sun below fold, first band 11.6% | 5 lanes, no scroll, first card 18.0% |
| 1440 collapsed | stacks widen 153 to 181 px (`a/week-1440-light-collapsed.png`) | bands to 912 px, still 5 of 7 days | days widen 143 to 170 px |
| 1024 default (auto-rail) | 7 stacks, no scroll, first card 19.5% | bands, Sat and Sun below fold | lanes scroll, first card 20.8% |
| 390 | day list, first card 24.2% | day list, 22.7% (page height 1587 in `measure.json`) | day list, 24.2% |
| Panel open | bands (week lost) | rail, calendar unchanged | day list (week lost) |

- A, 4: the only one with the whole week visible at every default. Loses a point for the panel turning the week
  into bands, and for the month's empty leading weeks (first card at 43.8% at 1440, 51.3% at 1024 collapsed).
- B, 3: best panel behaviour, worst week fit. At 390 `pageScrollHeight` is 1587 against 844 in A and C, so the page
  itself scrolls (S3 asks for one inner scroller). Worth checking in the browser before relying on it.
- C, 3: best at 1440, weakest at the default 1024, and loses the lanes when the panel opens.

### Caveats on the shots
- The Needs you count differs between shots (A 8, B 7, C 7 in light; C dark 8). The strip says 5 awaiting, which
  with 1 missed and 1 changes requested gives 7. This looks like demo data state between runs, not a direction defect.
- The panel shots are not like for like: A and C open a natively scheduled post (no Approve), B opens an awaiting
  post (Approve visible). The approve dialogs are the same shared component in all three.
- `measure.json` `firstPostShare` is only a card position, not the whole screen. B's 11.6% is the first band, not the
  first card in a column.

## 3. Per direction

### A. Quiet command bar (week stacks)
**Strengths**
- Whole week at every default, 10.7% grid top and 16.7% first card at 1440, 19.5% at 1024 (targets 17% and 20% met).
- The calmest week: seven wells, time-ordered cards, today treatment with ink numeral and now rule.
- Week and month use the same wells and cards, so the product reads as one thing.
- Collapsed rail widens the stacks (153 to 181 px) and has a test (`test_the_rail_widens_the_columns`).
- Smallest change footprint: `calendar-view.tsx`, `platform-swatch.tsx`, one test file.

**Weaknesses**
- Opening a post at 1440 with the sidebar open turns the week into bands (box 656 px): `a/panel-1440-light.png`.
- 1024 wells hold about 98 px of text: hyphenated words and two-line status chips (`a/week-1024-light-collapsed.png`).
- About 55% of each well is empty at the foot (`a/week-1440-light.png`).
- No hour axis, and the card shows the start time only; the window and offset are in the tooltip.
- Unlabelled icon pill under some status chips.

**Open issues (its doc)**
- No time axis: gaps between posts no longer show distance; same-minute posts stack.
- Narrow wells at 1024: hyphenation, three-line titles, two-line chips.
- The panel turns the week into bands.
- Month leading weeks: empty weeks stay at 96 px, so the first card is well below the fold on a month with data in one
  week; scrolling to today's week was left out.
- Sticky headers are `aria-hidden` (today is announced through `aria-current`).
- With the sidebar opened by hand at 1024 the first card sits at 20.3%, a hair over the 20% target.

### B. Inspector rail (day bands and the Needs you queue)
**Strengths**
- The best approval workflow: queue by urgency (Missed, Changes requested, Awaiting you), Approve first in the
  rail, advance to the next after a decision, `j`/`k`, "All clear." state.
- The calendar does not move when a post opens (`b/panel-1440-light.png`).
- Phone list is the most compact (cards 102 px against 141 px in A and C).
- Strong interaction accessibility and tests (`test_next_inspector.py`).

**Weaknesses**
- The calendar is only 720 px at 1440 with the sidebar open; Sunday is not visible (`b/week-1440-light.png`).
- The month at 1440 with the sidebar open is the week's bands (`b/month-1440-light.png`).
- At 1024 the queue is a button and a sheet, and the week needs scrolling to reach Saturday.
- Repeated generic megaphone on every card; half-empty bands.
- The rail takes 29% of the screen permanently, which works against "filters and secondary things must not take
  over"; the calendar is no longer the hero.
- Largest change footprint (new `day-bands.tsx`, `inspector-rail.tsx`, `needs-queue.tsx`, changes to the panel and
  four test files).

**Open issues (its doc)**
- Below 1180 px there is no persistent queue.
- Bands hide the time axis; the now line became a "Now 10:30" marker.
- Month cells show status as an icon, not a word.
- Advancing after a decision is a deliberate surprise (announced in the notice; only when the post was in the queue).
- The queue is read once per write (three requests).
- Unused CSS (`.hour-grid`, `--hour`) left in `globals.css`.

### C. Channel lanes
**Strengths**
- The best 1440 composition and the only one that shows coverage and cadence gaps (`c/week-1440-light.png`).
- Lane label doubles as the platform filter, with a clear "Showing" strip line (`c/lanes-solo-1440-light.png`).
- Best semantics (`role=table`) and a thoughtful `+n more` popover.
- Collapsed rail widens the days (143 to 170 px).

**Weaknesses**
- Default 1024 scrolls inside the grid and truncates titles with ellipsis (`c/week-1024-light-collapsed.png`).
- Panel open drops to a day list with 656 px wide cards (`c/panel-1440-light.png`).
- The filter is split by width: lanes above 880 px, popover below.
- Month is a hairline grid unlike the week's wells (`c/month-1440-light.png`), with the platform printed on every
  card.
- The lane model grows with the platform list (ten channels would scroll at any size).
- Card shows only the type icon plus start time; the platform name is carried by the lane.

**Open issues (its doc)**
- 1024 scrolls inside the grid (options: hide empty channels, a denser card).
- No hour axis, no now line (the today column replaces it).
- Lanes grow with the platform list.
- A busy channel-day shows two cards and `+n more`.
- Channel filter and popover split by width.
- The demo zone is `+01:00`; the strip prints whatever offset the schema carries.
- `line-clamp-2` on titles (full title in the card `title` and the panel).

## 4. Refinements for A (at most six, by value)

Each is small enough for a ~45-minute build run. Test risk is given so the run can plan the test edits first.

1. **Keep the week visible when a post is open.** Problem: `a/panel-1440-light.png` (week becomes bands, 2.5 days
   on screen). Change: lower the stacks threshold from 880 px to about 840 px in `calendar-view.tsx` (the
   `useElementWidth` check), so a collapsed sidebar plus the 30 rem panel keeps seven stacks (box about 848 px, wells
   about 120 px, the same as the shipped 1024 case). With the sidebar open the box is 656 px, so bands remain there.
   Test risk: tests that assert bands beside the panel at 1440 (`test_next_foundation.py`,
   `test_next_direction_a.py`) need their precondition checked, since they may open the panel with the sidebar open.
2. **Print the offset where the decision is made.** Problem: the approve dialog says "to be published Tue 2 Mar,
   09:00 to 10:00" and the panel's When row says "Wed 11 Mar, 09:00 to 10:00", both with no offset
   (`a/approve-1440-light.png`, `a/panel-1440-light.png`); only the strip and the card tooltip carry it. Change: append
   the offset from `zoneOffset(schema.timezone, …)` in `post-actions.tsx:292` and `post-panel.tsx:391`. Test risk:
   low (no test in `tests/ui` asserts the dialog sentence; the only match is a comment at `test_next_views.py:397`).
3. **Stop the two-line status chips and hyphenation at 1024.** Problem: `a/week-1024-light-collapsed.png`
   ("Awaiting you" on two lines, "part-ner", "announce-ment"). Change: in a well under about 130 px, hide the chip's
   leading icon (word stays) and drop `hyphens: auto` in favour of `text-wrap: balance` on the title, in
   `StackCard` in `calendar-view.tsx` and the `StatusChip` class passed at line 104. Test risk: the no-overflow test
   should stay green, since this only frees width.
4. **Label or remove the orphan icon pill.** Problem: a lone hand or checklist pill under the chip on Thu "Partner
   announcement" and Tue "Spring launch thread" (`a/week-1440-light.png`), with no visible meaning. Change: render
   `PostBadges` compact (`calendar-view.tsx:105`) only when a badge has text at that width, or show the text
   ("Natively scheduled") from 140 px up and keep the icon with `sr-only` text below. Test risk: low; check any test
   that counts card children.
5. **Show the window on the card, width permitting.** Problem: with no hour axis the end time lives only in the tooltip.
   Change: in the card's time row print "09:00–10:00" when the well is at least 140 px (the same container-query rule
   that shows the word "Today"), keeping "09:00" alone below that. Test risk: medium; tests that match the card text
   `09:00` exactly may need `startswith`.
6. **Trim the empty leading weeks in month.** Problem: `a/month-1440-light.png` (first card at 43.8%, two empty
   weeks above the data). Change: render a week that has no posts and is not the selected week at 64 px instead of 96 px
   (`MonthGrid`, `min-h-24`). Test risk: low to medium; the doc says the 96 px row was a brief figure, so keep the
   first row visible and keep the test that asserts the grid has no sideways scroll.

Not for the 45-minute run (note for later): adopt B's advance-to-next-in-queue after a decision, and C's lane view as a
third toggle.

## 5. Screenshot index for Kai's morning review

1. `/workspace/brandcal_ui_shots/dirs/a/week-today-1440-light.png`: the recommended direction at its best (today
   column, now rule, amber Needs you chip, all seven days).
2. `/workspace/brandcal_ui_shots/dirs/c/week-1440-light.png`: the strongest alternative, the channel matrix.
3. `/workspace/brandcal_ui_shots/dirs/b/panel-1440-light.png`: B's rail with Approve first and the calendar still
   in place; the reason to borrow its queue behaviour.
4. `/workspace/brandcal_ui_shots/dirs/a/panel-1440-light.png`: A's main weakness (the week becoming bands when a
   post opens), and what refinement 1 addresses.

Also useful: `a/week-1024-light-collapsed.png` (the default laptop state), `c/week-1024-light-collapsed.png`
(where lanes scroll), `b/month-1440-light.png` (a month that is not a month).

## Report

**Recommendation.** Build on Direction A: it alone shows the whole week without scrolling at every default size and
keeps the calendar as the hero. Borrow B's advance-after-decision queue behaviour and C's lane-as-filter idea later.

**Totals.** A 20, B 17, C 18 (of 25).

**Refinements for A.**
1. Keep seven stacks when the panel is open (lower the 880 px threshold to about 840 px).
2. Print the offset in the approve dialog and the panel's When row (`post-actions.tsx:292`, `post-panel.tsx:391`).
3. Stop two-line status chips and hyphenation in 1024 wells.
4. Label or remove the orphan icon pill on cards.
5. Show the start and end time on the card when the well is at least 140 px.
6. Shorten empty leading weeks in the month view.

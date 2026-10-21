# brandcal web UI: evaluation and layout directions (E1)

Analysis and concepts only; no app code changed. Branch `ui-review`, from `ui`. Lens: `docs/UI_STYLE.md`,
the make-interfaces-feel-better rules, the apple-design HIG pages (sidebars, split-views, toolbars,
popovers, layout, typography, color, dark-mode, motion, focus-and-selection) and the WCAG 2.2 AA floor.
Owner's view, in one line: the calendar is the product, yet it starts halfway down the screen, and the
left menu breaks when collapsed. Both are true and both are cheap to fix. Demo data is Example Co.

Screenshots: `/workspace/brandcal_ui_shots/dirs/current/` (made by
`/workspace/dev/brandcal_dirs/shots/current/test_shots.py`; geometry in `measure.json` beside them).
The demo home runs on `+01:00`; the zone is read from `schema.timezone`, never hard-coded. Wireframes
below show the owner's `+03:00`.

## 1. Measurements (current UI, light and dark identical)

`y` is the top of the week grid's day-header row; the "first row" is the 08:00 hour line under it.

| Viewport | Sidebar | Grid starts (y, share of height) | Calendar visible below it | Days visible |
|---|---|---|---|---|
| 1440 x 900 | open | 420 px, **46.7%** (first row 53%) | 423 px = 2.9 of 24 hours | 7 |
| 1440 x 900 | rail | 420 px, 46.7% | same | 7 |
| 1440 x 900, post open | open | 512 px, **56.9%** | 331 px = 2.3 hours | 4.5 (grid scrolls sideways) |
| 1024 x 768 | open | 468 px, **60.9%** (first row 68%) | 243 px = 1.7 hours | 4 |
| 1024 x 768 | rail | 420 px, 54.7% | 291 px | 6 |
| 768 x 1024 | open | 648 px, 63.3% | | 3 |
| 390 x 844 (day list) | sheet | first day heading 500 px, **59.2%**; first card 560 px, 66.4% | | 1 day per screen |
| Month 1440 x 900 | open | 420 px; first post 760 px, 84% (two leading weeks are empty) | | 7 |

What the 420 px at 1440 is made of: shell bar 64 + top padding 56 + title and three 48 px figures 78 +
nav/view toolbar 40 + filter pills 84 (two rows) + three gaps of 32 to 34. So filters are the biggest
single block (20%), but the cause is **five stacked bands**, each reasonable alone. At 1024 the pills
wrap to three rows (132 px), with a post open to four rows (about 176 px, 20%).

Sidebar geometry is right in both states (gap 256 or 64 px, main shifts, no page scroll); the break is
inside the rail (section 3).

## 2. Problems, ranked by impact

| # | Problem | Evidence | Where |
|---|---|---|---|
| 1 | **Chrome before calendar.** Bar, title with figures, nav/view row, filter pills and 32 px gaps push the grid to 47% (1440), 61% (1024), 59% (390). At 1440 x 900 three posts are fully readable above the fold and three more are cut off. | `week-1440-light-expanded.png`, `week-1024-light-expanded.png`, `week-390-light.png` | `calendar-view.tsx:501-567`, `app-shell.tsx:59-62,68`, `filters-bar.tsx:188-243` |
| 2 | **Wrong calendar metaphor.** A 24-hour axis at 144 px per hour (`--hour: 9rem`) inside a 42 rem nested scroller shows about 3 hours; 11 posts a week, one-hour windows, no drag, so the time axis does no work. Columns are `minmax(9rem,1fr)` in a 66 rem box: below about 1130 px of content only 4 to 6 days show, with sideways scroll. Two vertical scrollers (page and grid) fight. | `week-1024-light-expanded.png` (Fri cut off), `panel-1440-light.png` | `globals.css` `.hour-grid`, `calendar-view.tsx:43,233,242,244` |
| 3 | **Collapsed sidebar broken**: icons pushed off the left edge, label fragments ("Cale", "Needs", "Pos") clipped in the 40 px rail, theme controls gone. | `week-1440-light-collapsed.png`, `week-1440-dark-collapsed.png` | `app-sidebar.tsx:43` with `ui/sidebar.tsx:481` (section 3) |
| 4 | **The core loop is long.** Spot (Needs you is another page; "Awaiting approval 5" on the calendar is a dead number) then open then decide. In the panel, **Actions is the last section**, below Version history, Compare and Audit trail, so Approve is a long scroll away. | `needs-you-1440-light.png`, `panel-1440-light.png` | `post-panel.tsx:402-410`, `calendar-view.tsx:512-522` |
| 5 | **Filters over management.** 11 always-visible toggle pills (5 platforms, 6 statuses) plus "More filters" hold prime space for an occasional job. There is no "needs me" shortcut (it is three statuses to tick). Once folded, no summary says a filter is on. | `week-1440-light-expanded.png` | `filters-bar.tsx:160-245` |
| 6 | **The panel starves the calendar.** At 1440 a 30 rem panel leaves 704 px: grid scrolls sideways, filters wrap to four rows. Below 1200 px it is a modal overlay. | `panel-1440-light.png`, `panel-1024-light.png` | `post-panel.tsx:527-528` |
| 7 | **Month view wastes height.** 128 px empty week rows, truncated titles ("We are hirin..."), sideways scroll under about 1250 px (`min-w-[70rem]`). | `month-1440-light-expanded.png` | `calendar-view.tsx:332,353` |
| 8 | **Decorative chrome.** Three 48 px figures outweigh the calendar title; a 64 px glass bar holds two buttons; the theme control appears three times (footer switcher, bar toggle, Settings). | `week-1440-light-expanded.png` | `app-shell.tsx:59`, `calendar-view.tsx:512` |
| 9 | **Type below the contract.** Blocks, chips and badges use `text-xs` (12 px) where UI_STYLE 4 says 13 px minimum. Sidebar motion is 200 ms `ease-linear` where UI_STYLE 7 says `--ease-out` and 300 ms for panels. Kbd hints (`g c`) show on touch sheets. | `sheet-390-light.png` | `calendar-view.tsx:128-138,164-170`, `ui/sidebar.tsx:224`, `app-sidebar.tsx:59` |

Kept (do not regress): tokens and contrast gates, status chips with icon and word, no edge stripes,
URL-held state, `g`-chords and `[`, focus return from panel and dialogs, the phone day list, the
now marker, reduced-motion and reduced-transparency paths, axe and keyboard gates.

Guidance behind the directions (files under `apple-design/references/hig/`):
`popovers.md` Best practices ("a calendar event popover makes it easy to change the date or time of an
event"; popovers hold a few related tasks, one at a time); `toolbars.md` Item groupings (sidebar toggle and
title at the leading edge, at most three groups, one primary action); `sidebars.md` Desktop (hide and
reveal on resize; no critical actions at the bottom); `layout.md` Visual hierarchy (most important content
near the top and leading side, progressive disclosure) and Adaptability (follow available space);
`split-views.md` (persistently highlight the selection); `motion.md` (avoid motion on frequent
interactions, never the only cue). Polish rules: 0.96 press, concentric radii, 40 px hit areas,
named transition properties.

Tension to resolve in favour of WCAG, not HIG: HIG toolbars prefer borderless symbols; WCAG 1.4.11 needs
a 3:1 boundary on controls, so circular buttons stay outlined. HIG typography says avoid light weights;
keep weight 300 for the 24 px title and large numerals only, 400 for everything small.

## 3. The collapsed sidebar bug

Probe (`test_rail_probe.py`, collapsed at 1440): every link is 40 px wide at x 12; the icon sits at
**x -2 to -18** (off-screen); the label is `display: block`, 36 to 69 px wide, centred over it.

**Cause.** `app-sidebar.tsx:43` renders `<span className="whitespace-nowrap">{item.label}</span>` with no
collapsed rule, while `ui/sidebar.tsx:481` makes the collapsed button `size-10! justify-center p-0!
overflow-hidden` with `gap-3`. Icon (20) + gap (12) + label (36 to 69) is wider than 40 px, so centred
overflow clips both ends: the icon leaves on the left, the label stays. Stock shadcn relies on
`[&>span:last-child]:truncate` (same line), but here the last child is the Kbd group, so nothing collapses
the label; N4-10 added `whitespace-nowrap`, which made it worse. Axe passes (clipped content is still in
the DOM) and no test measures geometry, so it shipped.

**Fix every direction must include.**
1. `app-sidebar.tsx:43`: `group-data-[collapsible=icon]:sr-only` on the label. Not `hidden`: the link's
   accessible name must survive.
2. `ui/sidebar.tsx:481`: add `group-data-[collapsible=icon]:gap-0` so the lone icon is centred.
3. Collapsed count: the `Badge` is hidden in the rail, taking its `sr-only " waiting"` with it. Put the
   `sr-only` "N waiting" outside the badge; keep the visible dot, or a 20 px numeric pill (ink on
   `--muted-fill`).
4. Footer in the rail: avatar button plus a theme menu button (Base UI Menu radio group: System, Light,
   Dark) so the switcher is never lost.
5. Auto-rail: with no saved flag and a viewport of 768 to 1179 px, start collapsed (HIG sidebars:
   "automatically hiding and revealing a sidebar when its container window resizes"). The open sidebar at
   768 px leaves 512 px of content. A saved choice always wins.
6. Sidebar width motion: `duration-300 ease-out` (tokens), not 200 ms linear.
7. Test (new, blocking): in the collapsed rail every nav link's icon box lies inside its link box, the
   label's rendered width is at most 1 px, the link's accessible name still equals the label (plus
   "N waiting"), and `scrollWidth <= clientWidth` for the rail; both themes; axe still clean.

## 4. Use-case model

Kai (approver/admin) plans and manages a social calendar. Agents add and edit posts through the CLI; Kai
decides.

| Job | Frequency | Needs |
|---|---|---|
| Scan this week (or month): what goes out, when, where | Every visit, many times a day | All 7 days at once, each post's title, time, platform, status; today marked |
| Spot what needs me: awaiting approval, changes requested, missed or failed | Every visit | A count and a one-click route; the urgent state visibly heavier than the calm ones |
| Open a post and decide: approve, request changes, move, edit, cancel | Daily, in bursts of several | Full text beside the calendar; **the actions without scrolling**; next item after each decision |
| Move in time: previous, next, today, week or month | Constantly | One compact control group, keyboard friendly |
| Filter by channel or status | Occasional | One click away, URL-held, a visible trace when active |
| Find a post by slug, jump to a page | Rare | A command bar (`/` or Cmd/Ctrl+K), the existing `g` chords |

Visible without scrolling at 1440 x 900 and 1024 x 768: the whole week; the range and nav; the Needs you
count; an active-filter trace; the open post's actions. Behind one click: the filter set, version history,
compare, audit trail, other pages, theme choice. **Budget (the new gate):** the first calendar row starts
at or above 14% of the viewport height at 1440 x 900 and 1024 x 768 (now 47% and 61%), and at 390 x 844 the
first day heading is at or above 20% (now 59%).

## 5. Candidate layouts (six)

All six: left sidebar kept (fixed, rail below it), shell bar merged with the page toolbar, filters demoted,
status always chip (icon + word), no leading-edge stripes, `+03:00` shown in the context strip and in each
block's `title`.

### C1. Quiet command bar (calendar first)
One 64 px toolbar replaces bar, title, nav row and filters row; a 32 px strip carries counts and active
filters. Filters live in one popover; Needs you is an amber chip-button that applies the three statuses.
The calendar fills the viewport as the only scroller.
```
+---------+--------------------------------------------------------------+
| b       | = 9-15 March 2026  < Today >   [! Needs you 7][Filters][Wk|Mo] (o)|  64
| Schedule| +03:00 . 11 posts . 5 awaiting you . 1 published     Filtered: x |  32
| Calendar+-------+-------+-------+-------+-------+-------+-------+
| Needs 7 | Mon 9 | Tue 10| Wed 11| Thu 12| Fri 13| Sat 14| Sun 15|
| Posts   | [card]| [card]| [card]|       | [card]| [card]|       |
| ...     | [card]| [card]|       |       | [card]|       |       |
+---------+-------+-------+-------+-------+-------+-------+-------+
```
390: row 1 `[=] 9-15 Mar [!7][filter] [theme]`, row 2 `< Today >  [Wk|Mo]`; day list from about 18%.
Strengths: smallest change, lowest risk, fixes problems 1, 2, 5, 8. Risks: calendar alone does not shorten
the spot-and-decide loop (problem 4).

### C2. Calendar + inspector rail
A permanent right rail (26 rem): by default the **Needs you queue** (Missed, Changes requested, Awaiting
you, in that order); picking a post (from the queue or the calendar) turns the rail into the post detail
with actions on top; Back returns to the queue. The week becomes seven day bands.
```
+------+------------------------------------------+------------------+
| side | = 9-15 March 2026 < Today > [Filters][Wk|Mo] | NEEDS YOU      7  |
|      | +03:00 . 11 posts . 5 awaiting you       | Missed (1)        |
|      +--+---------------------------------------+  Newsletter rem.. |
|      |Mo| [Hiring][ ][ ]                         | Changes req. (1)  |
|      |Tu| [Newsletter][Planning][Launch teaser]  |  Launch teaser    |
|      |We| [How we plan][ ]                       | Awaiting you (5)  |
|      |Th| nothing planned                        |  Planning day..   |
|      |Fr| [Reply][Feature]                       |  How we plan..    |
+------+--+---------------------------------------+------------------+
 selected: rail = < Needs you | title, chips | [Approve][Changes][Move...] | text, media, details
```
390: no rail; Needs you is a toolbar chip opening the sheet; detail is the existing sheet.
Strengths: shortest decide loop, always-on answer to "what needs me", split-view pattern (HIG split-views:
"persistently highlight the current selection"). Risks: 26 rem rail plus open sidebar leaves 768 px, so
bands (not columns) are mandatory; 1024 needs the rail as an overlay.

### C3. Agenda + month map (split)
Left 24 rem agenda (day groups, sticky day headings, status switch All / Needs you); right a month map with
per-day dots and the selected day's cards.
```
+------+-------------------+--------------------------------------+
| side | AGENDA [All|Needs]| March 2026 < >   [Filters]           |
|      | Mon 9             | Mo Tu We Th Fr Sa Su                 |
|      |  09:00 hiring     | .  .  .  .  .  .  1                  |
|      | Tue 10            | 2  3  4  5  6  7  8                  |
|      |  08:00 newsletter | 9: 1 10: 3 11: 2 ...                 |
+------+-------------------+--------------------------------------+
```
390: the agenda alone, with the map behind a `Map` toggle.
Strengths: scan and plan in one screen, good for long ranges. Risks: two lists to keep in sync, week-level
glance is weaker than a week grid, most new code.

### C4. Desk (today and needs-you first)
A 136 px "desk" band under the toolbar: Today (this day's posts), Needs you (three tiles, each a button),
Next up (next three scheduled); then the week stacks as the hero below.
```
+------+----------------------------------------------------------+
| side | = 9-15 March 2026 < Today > [Filters][Wk|Mo]              |
|      | +--TODAY Tue 10----+--NEEDS YOU-------+--NEXT UP-------+ |
|      | | 08:00 Newsletter | Missed 1         | 10:00 Planning | |
|      | | 10:00 Planning   | Changes req. 1   | 11:00 Product  | |
|      | +------------------+ Awaiting you 5   +----------------+ |
|      | Mon 9 | Tue 10 | Wed 11 | ... week stacks                |
+------+----------------------------------------------------------+
```
390: the Needs you tiles become one row above the day list; Today and Next up fold into the list.
Strengths: answer-first, replaces the dead figures with live, actionable ones. Risks: costs 136 px of
height (grid at about 28%), duplicates the queue, reads as a dashboard.

### C5. Planner board (status kanban)
Columns Draft, Awaiting you, Changes requested, Scheduled, Published; cards ordered by date; week as a
range filter.
```
+------+----------------------------------------------------------+
| side | Draft 3 | Awaiting you 5 | Changes 1 | Scheduled 4 | Pub 1 |
|      | [card]  | [card]         | [card]    | [card]      |[card] |
+------+----------------------------------------------------------+
```
390: one column at a time with a status switcher.
Strengths: best for pipeline management. Risks: loses the calendar mental model (the main feature), the
natural interaction is drag (needs WCAG 2.5.7 alternatives), weakest for "what goes out Thursday".

### C6. Channel lanes (week by platform)
Rows are platforms, columns are days: the filter becomes the structure. Gaps in a channel's cadence show at
a glance; clicking a lane label solos that channel. Whole week fits without scrolling.
```
+------+--------+------+------+------+------+------+------+------+
| side |        | Mon 9| Tue10| Wed11| Thu12| Fri13| Sat14| Sun15|
|      | LinkedIn| [c] | [c]  | [c]  |      | [c]  |      |      |
|      | X       |      | [c]  | [c]  |      |      |      |      |
|      | Instagram|     | [c]  |      |      | [c]  |      |      |
|      | YouTube |      |      |      | [c]  |      |      |      |
|      | Bluesky |      |      |      |      |      | [c]  |      |
+------+--------+------+------+------+------+------+------+------+
```
390: lanes collapse to the day list grouped by day with the channel on each card (unchanged data model).
Strengths: the most planning-literate view of a multi-channel calendar, most distinctive, no filter row
needed for channels. Risks: a busy channel-day stacks cards, month needs another form, lanes grow with the
platform list.

## 6. Scoring (1 to 5; build risk: 5 = lowest)

| Concept | Balance | Use-case fit | Visual potential | Accessibility | Responsiveness | Build risk | Total |
|---|---|---|---|---|---|---|---|
| C1 Quiet command bar | 4 | 4 | 3 | 5 | 5 | 5 | **26** |
| C2 Inspector rail | 5 | 5 | 4 | 4 | 3 | 3 | **24** |
| C3 Agenda + map | 3 | 4 | 3 | 4 | 4 | 3 | 21 |
| C4 Desk | 3 | 4 | 4 | 4 | 4 | 4 | 23 |
| C5 Planner board | 3 | 3 | 4 | 3 | 3 | 2 | 18 |
| C6 Channel lanes | 4 | 4 | 5 | 4 | 3 | 3 | **23** |

**Pick: A = C1, B = C2, C = C6, optional D = C4.** They differ in what organises the screen: the toolbar
(A), the decision queue (B), the channel (C), today (D). C3 and C5 are dropped (duplicate lists; wrong
metaphor). A is also the foundation the others sit on, so it ships first as the shared layer in section 7.
If only one direction can ship, ship B on A's foundation.

## 7. Shared requirements (every direction)

S1. Fix the collapsed sidebar (section 3). Keep the left sidebar paradigm (256 px open, 64 px rail, sheet
below 768 px), shadcn components (add `popover`, `dropdown-menu`, `toggle-group` as local files on the
installed `@base-ui/react`; **no new dependency**), and the System/Light/Dark switcher (footer, Settings,
rail menu; the bar's quick toggle stays).
S2. **One top bar**: `AppShell`'s glass bar becomes the page toolbar through a slot (a `ToolbarSlot`
portal target in `app-shell.tsx`); no separate title row, no `pt-14` above content on `/`. Landmarks stay
one banner, one nav, one main; `h1` is the range label with the sr-only "Calendar: ".
S3. **One scroller.** The calendar region is `h-[calc(100svh-var(--shell-top)-bar-strip)]`, scrolls
inside itself with sticky day headers; the page does not scroll on `/`. Bottom `scroll-padding` keeps the
notice card clear (WCAG 2.4.11). Name stays `Week calendar` / `Month calendar`.
S4. **Container-width layout, not viewport.** A `useElementWidth` ResizeObserver hook on the calendar box:
at least 880 px gives day columns, below gives day bands (the current `DayList`, widened). The panel
opening therefore never causes sideways scroll. No sideways scroll anywhere on `/` at 320 px.
S5. **Filters in one popover** (Base UI Popover, non-modal, Esc closes and returns focus): Platform
(checkbox list with `PlatformDot`), Status (checkbox list, chips), Post type, Campaign, Pillar, Search by
slug, "Include published and cancelled". Trigger shows `Filters (n)`, `aria-expanded`, keeps
`data-filters-toggle`. When any filter is active, a 32 px strip shows removable chips plus "Clear
filters" (`aria-live` polite count). Still URL state (`lib/url-state.ts`), so a filtered view is shareable.
S6. **Needs you, live**: an amber chip-button (`bg-st-awaiting text-st-awaiting-ink`, clock icon, count)
in the toolbar; `aria-pressed`, toggles the three needs-you statuses in the URL. It is the only coloured
control in the bar. The three dead figures go; counts become one strip line (`tabular-nums`, 13 px).
S7. **Panel: actions first.** The Actions block leaves the foot of `post-panel.tsx` and is pinned
(`sticky`) so Approve, Request changes and "Move..." are always in view; History, Compare and Audit
stay below, collapsed by default (disclosure, `aria-expanded`). Focus, return-focus and inert rules from
N4 are untouched.
S8. **Type and space.** 4 px base. Bar 64, strip 32, gutters 24 (16 below 640), gaps 8/16. Title 24 px
weight 300 (18 px below 640); labels, strip, chips 13 px; card title 14 px weight 500; times `tabular-nums`.
Nothing under 13 px. Radii concentric (UI_STYLE 5): calendar card 28, day wells `rounded-inner` 20 with
8 px padding, post cards `rounded-control` 12 inside 8 px well padding (12 + 8 = 20). Wells are separated by
8 px gaps and soft shadow, not borders. Controls 40 px, 24 px floor.
S9. **Motion** (tokens only, never `transition: all`): popover 150 ms opacity and `scale 0.96 to 1` with
the trigger as transform origin, exit 100 ms; sidebar width 300 ms ease-out; press 0.96. Nothing animates
on week change, selection or `j/k` (high-frequency). Reduced motion keeps every cue (colour, icon, label).
S10. Times: `+03:00` offset in the strip, every block `title` carries the full window with offset; zone
from `schema.timezone`. No leading-edge coloured stripes: pastel fill, printed platform name, status chip.
S11. **CI stays green**: pytest including `tests/ui` with axe, vitest, ruff, mypy, web lint and typecheck, the section 9 gates; `python scripts/build_ui.py` re-run and the
committed `src/brandcal/web_next/` plus `csp.json` match a second build byte for byte.

## 8. Build briefs

Build order: shared layer first (S1 to S11 on one branch off `ui`), then A, B, C, (D) each on its own branch
off the shared layer, so each can be judged by screenshots. Widths below are content widths with the
sidebar open (256 px) or railed (64 px).

### A. Quiet command bar (week stacks)
| Aspect | Spec |
|---|---|
| Grid | 1440 open: 1184 px content, 7 columns of about 150 px. 1440 railed: 1376 px, about 180 px. 1024: auto-rail, 960 px, about 125 px. 768: rail, 704 px, bands (below 880). 390: day list. |
| Toolbar (64 px) | Leading: `[Toggle navigation]` (40), title (24 px, 300). Then `[<] [Today] [>]`. Trailing: Needs you chip, `Filters (n)`, `Week / Month` segmented (black pill = selected), theme toggle. Below 1100 px content the chip and Filters become 40 px icon buttons with a count dot and sr text; below 640 two rows (row 2: nav + segmented). |
| Strip (32 px) | `+03:00 . 11 posts . 5 awaiting you . 1 published`, then filter chips. |
| Week body | `WeekStacks`: seven `rounded-inner` wells, header 48 px sticky (`Mon` label + date numeral, today in the black circle plus a `Today` word, well tinted `--muted-fill`). Cards in time order, no hour axis: row 1 time + platform name (13 px), row 2 title (2 lines, 14 px), row 3 `StatusChip` (28 px). About 96 px a card. A thin "now" rule is inserted in today's stack at the right time (`aria-hidden`, sr-only `Now: 09:41`). Empty day: a quiet `Nothing planned`. |
| Month | Rows size to content (`min-h-24`), leading empty weeks kept but at 96 px; titles wrap to 2 lines; same cards; no sideways scroll above 880 px, bands below. |
| Needs you | Toolbar chip, sidebar badge, existing page unchanged. |
| Rail | Section 3 fix; icon pills 40 px, active = black circle, count dot, footer avatar + theme menu. |
| Panel | 30 rem sticky at 1200 px and up (container logic gives bands when it opens), actions pinned at the foot, secondary sections collapsed. Modal overlay below 1200 px as now. |
| Targets | First card at or below 17% of height at 1440 x 900 (about 152 px), 20% at 1024 x 768, grid header at 14% or less. |

### B. Inspector rail (day bands + queue)
| Aspect | Spec |
|---|---|
| Grid | 1440 open: 256 sidebar, 416 px rail (26 rem), so about **744 px of calendar as bands** (1184 - 416 - 24 gutter). 1440 railed: about 896 px (columns allowed, bands stay the default). 1180 to 1439: rail 22 rem. Below 1180: the rail becomes the overlay sheet, opened from a toolbar button with the count. 390: day list as now. |
| Toolbar | As A without the Needs you chip (the rail is it); the rail header carries the count. |
| Calendar body | `DayBands`: 7 rows, 88 px label column (`Mon`, numeral 24 px light, Today word), cards flow in `flex-wrap`, min 168 px, grow to fill; empty day is a 40 px line. This is the same component as the phone list, only wider. |
| Rail, queue state | Header `Needs you` + count; sections Missed, Changes requested, Awaiting you (status chip as the section label); rows: platform dot + name, title, `Wed 11 . 09:00`. Keyboard: `j`/`k` move, Enter opens. Empty: `All clear.` with the CLI hint line. |
| Rail, detail state | `< Needs you (6)` back button, title, chips, **actions row on top** (Approve as the one black pill, Request changes outlined, `Move...` and `More` menu), then text, media, details; history/compare/audit as disclosures. After a decision the rail advances to the next queue item (current test behaviour kept). |
| Calendar link | Selected card takes the 2 px ink outline (existing `aria-current`); queue row and card stay in sync via `?post=`. |
| Rail (nav) | Section 3 fix; with the right rail open and the sidebar open at 1440 the sidebar stays open (bands need only about 600 px). |
| Targets | Grid header at 12 to 14%; the first day band fully visible at 1440 x 900 and 1024 x 768; Approve visible with no scroll on open. |

### C. Channel lanes
| Aspect | Spec |
|---|---|
| Grid | `grid-cols-[7.5rem_repeat(7,minmax(0,1fr))]`. 1440 open: 120 px label + 7 x about 145 px; lanes `min-h-[6.5rem]`, auto-grow, 5 lanes plus a 48 px header fit in about 570 px with no scroll. 1440 railed: about 180 px days. 1024 railed: about 120 px days (cards drop the type row). Below 880 px of container: day list with the channel printed on each card (as today). 390: same. |
| Toolbar and strip | As A, but the platform half of Filters is gone: each lane label is a button (`aria-pressed`, "Show only LinkedIn"); the strip shows `Showing: LinkedIn x` plus `Show all`. Filters popover keeps Status and the rest. |
| Cells | `rounded-inner` lane wells with hairline day separators; card = pastel fill (`rounded-control`), row 1 `09:00 . LinkedIn`, row 2 title (2 lines), row 3 `StatusChip` compact (24 px; "Awaiting you" fits 129 px). More than two cards in a cell: `+n more` opens a popover list (WCAG 2.5.8 targets 24 px). Empty lane row shows a single quiet dash per cell: gaps are the signal. |
| Month | Falls back to A's month grid. |
| Needs you | As A (chip in the bar, sidebar badge). |
| Rail | Section 3 fix. |
| Panel | As A. |
| Targets | The whole week visible at 1440 x 900 with no scroll; grid header at 12% or less. |

### D (optional). Desk
| Aspect | Spec |
|---|---|
| Grid | Under the A toolbar and strip: a 136 px, three-column desk band (Today 5 fr, Needs you 4 fr, Next up 3 fr; wells `rounded-inner`), then A's week stacks filling the rest. At 1024 the band is two columns (Next up drops); at 390 it is one `Needs you` row of three tiles above the day list. |
| Needs you | Three tiles (Missed, Changes requested, Awaiting you), each a button that sets the filter and focuses the first match; they replace the toolbar chip. Zero state: `All clear` on one line (band shrinks to 56 px). |
| Targets | Grid header at 28% or less at 1440 x 900 (below that, drop the band for a toolbar chip). Build only if A to C land inside budget. |

## 9. Tests

**Change.** `tests/ui/test_next_views.py:157,172` (platform pill and "More filters": open the Filters popover
first; in C use the lane buttons); `test_next_a11y.py:318` (`[data-filters-toggle]` kept on the trigger);
`:631` the now-line test (the marker sits in today's stack, `aria-hidden`, sr text kept); `:54`
`ALLOWED_SCROLL` (tighten once nothing scrolls sideways); keyboard-walk order tests (`:408,:421`) for the
new bar order. Unchanged on purpose: `Toggle navigation`, `Week calendar`, `Month calendar`, `Primary` nav
names, the footer `radio` theme names.

**Add (blocking).** (1) Collapsed-rail geometry (section 3). (2) Calendar-first gate: grid top divided by
`innerHeight` at 1440 x 900 and 1024 x 768 is at most 14%, at 390 x 844 the first day heading at most 20%.
(3) Container switch: opening the panel at 1440 gives bands with `scrollWidth <= clientWidth`. (4) Filters
popover: opens by keyboard, Esc closes and returns focus, active chips appear, Clear removes them, URL
carries state. (5) Needs-you chip toggles the three statuses and `aria-pressed`. (6) Panel actions visible
without scrolling on open at both desktop sizes. (7) axe in both themes for: popover open, rail collapsed,
panel open, B's rail in both states, C's lanes. (8) Rendered contrast on the new cards. Keep reflow at
320, text spacing, 200% zoom, reduced motion and transparency, target size, `test_ui_contrast.py`. Update
`UI_STYLE.md` (layout section, 13 px floor) in the build run.

## 10. Screenshots for each built direction

To `/workspace/brandcal_ui_shots/dirs/<a|b|c|d>/`, same script shape as `current/test_shots.py`, both
themes where marked (L/D): `week-1440-{L,D}-{expanded,collapsed}`, `week-1024-L-{expanded,collapsed}`,
`week-768-L`, `week-390-{L,D}`, `sheet-390-L`, `month-1440-L`, `month-390-L`, `panel-1440-{L,D}`,
`panel-1024-L`, `panel-390-L`, `needs-you-1440-L`, `filters-open-1440-L`, `filters-open-390-L`,
`filtered-1440-L`, `rail-closeup-L` and `rail-closeup-D` (crop 0 to 80 px wide), B only `rail-queue-1440-L`
and `rail-detail-1440-L`, C only `lanes-solo-1440-L`; plus `measure.json` from the same geometry probe
(grid top share per viewport) so the section 1 table can be redone for each.

## 11. Risks

Hour-axis removal changes the now-line semantics and the block tests (planned). Popover and menu parts
come from `@base-ui/react`; they position with runtime inline style, which the page CSP allows (script-set
styles are not hashed, only HTML attributes), but check `window.__csp` stays empty. Container-width
switching needs a ResizeObserver: render the first paint as bands (the safe layout) and upgrade after
mount to avoid a flash. Auto-rail needs the saved flag read after hydration (already so). B's keyboard
`j/k` must respect `isTyping` and the single-key shortcut switch (WCAG 2.1.4).

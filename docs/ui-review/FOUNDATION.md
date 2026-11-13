# Shared foundation (S1)

What every direction (A, B, C) builds on. It covers EVALUATION.md section 3 (the collapsed rail) and
section 7 S1–S11, with direction A's quiet command bar, strip and filters popover as the shell. The
week and month bodies are still the old ones; the directions replace them.

## What the shared layer provides

All under `web/components/` unless stated.

| Piece | Use it like this |
|---|---|
| `toolbar.tsx` | `ToolbarSlot` is rendered once, by the shell's glass header. A page renders `<ToolbarPortal>` and its controls land in the bar, in DOM order (which is Tab order). No CSS `order`. |
| `ToolbarTitle` | `label` (sr-only lead-in, "Calendar: "), `short` (shown under 800 px of content width, the full text stays for readers), `children` (the full title). It is the page's one `h1`. |
| `ToolbarSpacer` | Pushes everything after it to the trailing edge. |
| `calendar-toolbar.tsx` | `CalendarToolbar({ view, date, inRange, step, today, onView, hideFilters })` is the whole bar: title, `RangeNav`, spacer, `NeedsYouChip`, `FiltersPopover`, `ViewSwitch`. Directions reuse it and pass `hideFilters` for what they replace. `RangeNav` and `ViewSwitch` are exported on their own. |
| `filters-popover.tsx` | `FiltersPopover({ hide })`, `FilterStrip({ summary, hide })`, `NeedsYouChip`, `useFilterState()`. `hide` is `("platform" \| "status")[]`; C passes `["platform"]` because its lanes replace that half. Every choice is URL state. |
| `FilterStrip` | The 32 px line under the bar. `summary` is the page's text (offset, counts). Active filters show as removable chips, plus "Clear filters" and a polite live count. |
| `useFilterState()` | `{ schema, role, filters, set, toggle, clear, activeCount }`. `toggle` reads the address, so two quick clicks both count. |
| `use-element-width.ts` | `useElementWidth() → [ref, width \| null]`. The calendar uses 880 px: at least 880 gives day columns, below gives day bands. First paint is bands. Measure the box, not the window, so the open panel is handled. |
| `disclosure.tsx` | `Disclosure({ title, defaultOpen, className })`. An `h3 > button` with `aria-expanded`/`aria-controls`; the content stays in the DOM, `hidden` while closed. |
| `post-actions.tsx` | `Actions` renders the pinned `[data-panel-actions]` bar (`li[data-action][data-enabled]`, buttons carry `data-action-button`). Notes go in `li[data-action-note]`; CLI blocks are `li[data-cli-for]` inside a closed "Agent equivalents (CLI)" disclosure. |
| `post-panel.tsx` | Actions come straight after the chips. History, Compare and Audit are disclosures. Esc is ignored while a popover or menu is open, so Esc closes only the topmost layer. |
| `post-bits.tsx` | `focusPostLater(id)` and `settleFocus()` return focus to a post button that does not exist yet (the calendar swaps bands for columns as the panel closes). A body that remounts its post buttons should call `settleFocus()` after the swap. |
| `theme-menu.tsx` | The rail footer's System/Light/Dark menu (the header still has the full `ThemeToggle`). |
| `ui/popover.tsx`, `ui/dropdown-menu.tsx`, `ui/toggle-group.tsx` | Local shadcn-style files on the installed `@base-ui/react`. No new dependencies. |
| `lib/time.ts` | `zoneOffset(zone, at)` gives "+03:00" from an offset or an IANA zone; `rangeLabelShort(view, date)` gives "9 – 15 Mar". |

Container queries on the shell column (`@container`): controls go icon-only under 1100 px
(`@max-[1100px]:`), the title shortens under 800 px (`@max-[800px]:`). Use these, not window media
queries, so an open panel narrows the bar correctly.

One scroller on `/`: the column is `100svh − --shell-top` tall and `main` is a flex column. The
calendar region fills what is left and scrolls inside itself, so the page never scrolls.

## The sidebar fix

- The label is `sr-only` in the rail (it was clipped, not hidden), and the gap is 0.
- The waiting count's screen-reader text sits outside the badge; the badge is `aria-hidden`, and the rail shows a count dot.
- Every rail item has a tooltip; all are keyboard reachable.
- The rail footer holds the avatar and a theme menu (the theme switch was unreachable there).
- Width motion is 300 ms on `--ease-out`, and reduced motion removes it.
- The state is persisted. With nothing saved, 768–1179 px opens as a rail by itself; a saved choice always wins.

## Measurements (Example Co data, +03:00)

Top of the calendar grid, as a share of the viewport height. "Before" is EVALUATION.md section 1.

| Viewport | Before | After |
|---|---|---|
| 1440×900, sidebar open | 420 px, 46.7% | 96 px, 10.7% (first post card at 305 px, 33.9%; page does not scroll) |
| 1440×900, panel open | — | 96 px, 10.7% (bar 64 px, one row) |
| 1024×768, rail (automatic) | 54.7% | 96 px, 12.5% |
| 1024×768, sidebar opened by hand | 60.9% | 144 px, 18.8% (the bar wraps to two rows at 768 px of content) |
| 390×844 | first day heading at 500 px, 59.2% | 144 px, 17.1% (bar 112 px in two rows, strip 32 px) |

Sidebar width: 256 px open, 64 px as a rail.

## Test hooks

`[data-toolbar-slot]`, `[data-filters-toggle]`, `[data-filter-strip]`, `[data-filter="platform:x"]`,
`[data-filter="status:x"]`, `[data-filter-chip]`, `[data-needs-you-chip]` (`aria-pressed`),
`[data-panel-actions]`, `[data-action-note]`, `[data-cli-for]`. Tests: `tests/ui/test_next_foundation.py`.

## Notes for A, B and C

- A's panel spec says actions at the foot; the foundation pins them at the top (`sticky top-0` in `Actions`, a one-class change).
- The week and month bodies are placeholders. Month still has leading empty weeks and truncated titles.
- Screenshots: `/workspace/brandcal_ui_shots/dirs/base/` (script `shots/base/test_shots.py`; `measure.json` has the geometry).

# brandcal web UI: style tokens and rules

Soft minimalism with frosted glass. A neutral off-white canvas, near-black ink and no colour in
the chrome. Colour only carries meaning: soft pastels per platform, a chip colour per status,
strong colour only for data. One high-contrast black pill marks the active or primary state
(it inverts in dark mode). This file is the style contract for the Next.js UI in `web/`; the
tokens live in `web/app/globals.css` and are checked by `scripts/ui_contrast.py`.

The stricter rule wins when sources disagree: WCAG 2.2 AA is the floor, then the polish rules.

## 1. Principles

- **Quiet type, loud numbers.** Light or regular headings, small grey labels (still 4.5:1),
  big light tabular figures. Hierarchy comes from size, not weight.
- **Soft shadows, not borders, on cards.** Controls keep a 3:1 boundary.
- **Glass only on the shell, sidebar and floating panels.** Never on content.
- **Status is a chip with an icon and a word**: Draft, Awaiting you, Scheduled, Published,
  Failed. Never colour alone.
- **Thin outline Lucide icons**, 1.5 px stroke beside regular text, `currentColor` only.
- Generous space. British English in all copy.

## 2. Colour tokens

Hex only, so the contrast script can parse them. Dark is its own checked set, not an inversion.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--canvas` | `#f5f5f3` | `#0e0e10` | page |
| `--surface` | `#ffffff` | `#19191c` | cards, popovers |
| `--muted-fill` | `#eeeeeb` | `#232327` | quiet fills (shadcn `muted`) |
| `--ink` | `#111113` | `#f2f2f0` | text |
| `--label` | `#5e5e66` | `#a3a3ab` | small grey labels |
| `--hairline` | `#e3e3de` | `#2a2a2e` | grid lines, dividers (decorative) |
| `--control-boundary` | `#85858d` | `#6f6f78` | inputs, switches, outlined buttons |
| `--glass` / `--glass-solid` | `#ffffffb8` / `#fbfbfa` | `#19191cb8` / `#1d1d20` | 72% fill / fallback |
| `--pill-bg` / `--pill-fg` | `#111113` / `#fafaf9` | `#f2f2f0` / `#111113` | the black pill |
| `--focus-ring` | `#111113` | `#f2f2f0` | 2 px ring, 2 px offset |
| `--destructive` | `#b3261e` | `#ff8a80` | errors, destructive text |

shadcn variables (`--background`, `--card`, `--primary`, `--ring`, `--input`, `--sidebar-*` and
the rest) are aliases of these tokens, so shadcn components follow the theme. `--input` is the control
boundary, which is why an input keeps 3:1 without extra work.

### Platform pastels

One pastel per platform id. The ink is the readable colour on it. The name is always printed.

| Platform | Pastel | Light bg / ink | Dark bg / ink |
|---|---|---|---|
| `linkedin` | sky | `#c9e1fa` / `#0f3f6b` | `#1b3a5c` / `#cfe4fa` |
| `x` | lilac | `#ddd3f8` / `#36246b` | `#3a2f63` / `#e2d9fb` |
| `instagram` | rose | `#f7cfe6` / `#6e1a55` | `#5a2147` / `#fbd3ea` |
| `youtube` | butter | `#f7e5a0` / `#5a4600` | `#4a3d12` / `#f5e6a3` |
| `bluesky` | mint | `#c4ebd6` / `#0f5236` | `#17443a` / `#c6f0da` |

Each platform also has an **edge**, a slightly stronger colour of the same hue, used for the small
dot on the platform pill, filter and badge. A post block (week, month, day list) has no coloured
stripe on any side: its pastel fill carries the platform, the name and icon are printed inside,
and a 1 px inner hairline of the edge at 25% (`inset-ring-pf-<id>-edge/25`) plus the card
shadow keeps adjacent and overlapping blocks of one platform apart in both themes. The selected
block takes the 2 px ink outline; focus takes the focus ring. Rose is deliberately pink, not salmon, so an Instagram block is never mistaken
for a Failed chip. Status stays a separate chip (icon and word); colour is never the only cue.

| Platform | Light edge | Dark edge |
|---|---|---|
| `linkedin` | `#2f78c4` | `#5aa2e8` |
| `x` | `#7b5bd6` | `#9a82ee` |
| `instagram` | `#c23a95` | `#e268b4` |
| `youtube` | `#8f6a00` | `#d9aa2a` |
| `bluesky` | `#1a7f4f` | `#4cc088` |

Tokens: `--pf-<id>-bg`, `--pf-<id>-ink` and `--pf-<id>-edge`; Tailwind: `bg-pf-<id>
text-pf-<id>-ink bg-pf-<id>-edge` (dot) and `inset-ring-pf-<id>-edge/25` (block hairline). In code use `platformBlock()` and `PlatformDot`.

### Backdrop and banner

`--wash-a` (`#e4e2f1` / `#1a1a2b`) and `--wash-b` (`#dfeaee` / `#102226`) are two faint radial
washes, fixed to the viewport behind the shell, so the sidebar glass has something to frost.
Content cards, the week grid, blocks and dialogs stay solid. `--banner-bg` / `--banner-fg`
(`#b3261e` / `#ffffff` light, `#8c1d18` / `#fff1ef` dark) colour the permanent dev-unverified
banner: a deep warning red in both themes, never the salmon of `--destructive` in dark.

### Status chips

| Status | Icon | Light bg / ink | Dark bg / ink |
|---|---|---|---|
| Draft | pencil | `#e7e7e3` / `#46464d` | `#2b2b2f` / `#d0d0d6` |
| Awaiting you | clock | `#ffddb8` / `#6b3500` | `#4a3213` / `#ffd9a6` |
| Scheduled | calendar-clock | `#dce6fa` / `#1e3f8f` | `#223560` / `#c4d4fa` |
| Published | circle-check | `#166a3f` / `#ffffff` | `#5bd58d` / `#04301a` |
| Failed | triangle-alert | `#f9d6d2` / `#8a1c16` | `#55231f` / `#ffc8c2` |

Published is the only solid fill, so it cannot be mistaken for the ink pill (which is
monochrome) or for any pastel. Tokens: `--st-<name>-bg` and `--st-<name>-ink`.

## 3. Contrast (computed)

Run `python scripts/ui_contrast.py` for every pair (120 rows). `tests/test_ui_contrast.py` fails
the build below 4.5:1 for text and 3:1 for control boundaries, focus rings, the pill's state cue
and status chip icons. Glass text is checked on the translucent fill flattened over the canvas,
the card and each pastel. Values below are light / dark and come from that script.

| Pair | Light | Dark | Minimum |
|---|---|---|---|
| ink on canvas / surface | 17.28 / 18.86 | 17.20 / 15.65 | 4.5 |
| label on canvas / surface / muted | 5.89 / 6.42 / 5.53 | 7.70 / 7.00 / 6.25 | 4.5 |
| destructive on canvas | 5.99 | 8.45 | 4.5 |
| black pill text on pill | 18.06 | 16.83 | 4.5 |
| platform ink on pastel (lowest of five) | 7.10 | 8.50 | 4.5 |
| platform edge on its pastel (lowest of five) | 3.40 | 3.85 | 3 |
| ink / label on wash-a and wash-b (lowest) | 14.77 / 5.03 | 14.65 / 6.56 | 4.5 |
| dev banner text and icon | 6.54 | 8.28 | 4.5 / 3 |
| status chip text (lowest of five) | 6.63 | 7.86 | 4.5 |
| status chip icon (lowest of five) | 6.63 | 7.86 | 3 |
| control boundary on canvas / surface | 3.35 / 3.66 | 3.88 / 3.53 | 3 |
| focus ring on canvas / surface | 17.28 / 18.86 | 17.20 / 15.65 | 3 |
| black pill against canvas | 17.28 | 17.20 | 3 |
| glass label, worst backdrop | 5.86 | 6.25 | 4.5 |
| glass ink, worst backdrop | 17.21 | 13.97 | 4.5 |

The script checks the tokens. `tests/ui/test_next_a11y.py` also computes the contrast of what is
actually rendered (text 4.5:1, icons 3:1, chip borders 3:1, glass composited over the canvas) on
the week blocks and on the panel over glass, in both themes.

Rules the numbers back up: never use `--hairline` as the only boundary of a control; never put
`--label` on a pastel (use that pastel's ink); never set text below 4.5:1 because it is "large"
(WCAG counts only 24 px, or 18.66 px bold, as large).

## 4. Type

Geist Sans and Geist Mono from the `geist` package (bundled by `next/font/local`, so builds
work offline and there are no external font requests). Headings are weight 300, body 400.
Body text is at least 14 px; small labels are 13 px (`0.8125rem`), never smaller. Figures use
`.figure` (3 rem, light, tabular). `text-wrap: balance` on headings, `pretty` on paragraphs and
list items. Antialiased smoothing is set once on `<html>`.

## 5. Radii (concentric rule)

Outer radius = inner radius + the padding between them.

| Token | Value | Use |
|---|---|---|
| `--radius-card` (`rounded-card`) | 28 px | cards; inner 20 + 8 px padding |
| `--radius-inner` (`rounded-inner`) | 20 px | tiles inside a card; control 12 + 8 px |
| `--radius-control` (`rounded-control`) | 12 px | inputs, small tiles |
| `rounded-full` | pill | buttons, chips, circular icon buttons |

Above 24 px of padding, treat the layers as separate surfaces and pick radii independently.

## 6. Spacing

A 4 px base (Tailwind's `--spacing`). Use 4, 8, 12, 16, 24, 32, 48, 64, 96. Page gutters 24,
section gaps 56, card padding 8 outside and 20 inside. Controls are at least 40 px square
(24 px is the WCAG 2.5.8 floor, never go under it); extend small targets with a pseudo-element
and never let two hit areas overlap.

### Layout (the calendar is the hero)

- **One bar.** The shell's glass bar (64 px, two rows on a phone) is also the page toolbar: the
  page puts its title, navigation and controls into it through `ToolbarPortal`
  (`components/toolbar.tsx`). No second title row, no padding above the content on `/`.
- **One strip.** Under the bar, a 32 px strip carries the zone offset (`+03:00`, from
  `schema.timezone`), the counts and the removable chips of the active filters.
- **One scroller.** On `/` the shell column is one screen tall and the calendar fills what is left;
  it scrolls inside itself with sticky day headings, and the page does not scroll. Bottom
  `scroll-padding` keeps a focused control clear of the notice card.
- **Container width, not viewport.** The calendar reads the width of its own box
  (`useElementWidth`): from 880 px seven day columns, below that day bands. The post panel opening
  beside it therefore never causes sideways scroll. The bar's controls collapse to icon buttons by
  the width of the content column (a container query at 1100 px).
- **Gutters** 24 px (16 below 640), gaps 8 and 16. Gaps between wells are 8 px and a soft shadow,
  not borders.
- **Week stacks, no hour axis.** The week is seven `rounded-inner` wells inside the calendar card
  (8 px padding, 6 px when the calendar box is under 60 rem). Each well has a 48 px sticky header
  (weekday, date numeral, the black circle and the word "Today" for today, tinted `--muted`) and its
  posts as cards in time order: row 1 time and platform name, row 2 title (two lines, three in a
  very narrow well), row 3 the status chip. A thin ink "now" rule sits in today's stack at the
  right place; an empty day says "Nothing planned". The month uses the same wells and cards in rows
  that size to their content (at least 96 px). Day bands (a box under 880 px) flow their cards in
  as many columns of at least 16 rem as fit.

## 7. Motion

| Token | Value | Use |
|---|---|---|
| `--dur-fast` | 100 ms | hover colour |
| `--dur-base` | 150 ms | press, small exits |
| `--dur-slow` | 300 ms | icon cross-fades, panels |
| `--ease-out` | `cubic-bezier(0.2, 0, 0.2, 1)` | everything |

- Use CSS transitions for interactive state (they retarget when interrupted); keyframes only for
  one-off staged entrances. Exits are shorter and softer than entrances.
- **Never `transition: all`.** Name the properties (`transition-[scale,background-color]`).
- Press is `scale(0.96)`, never lower than 0.95. `.press` and the Button do this.
- Icon swaps keep both icons in the DOM and cross-fade: scale 0.25 to 1, opacity 0 to 1, blur
  4 px to 0 (`blur-none`, not `blur-0`, in Tailwind 4).
- No custom animation on high-frequency interactions. Motion is never the only cue.
- `prefers-reduced-motion: reduce` cuts transitions and animations to 0.01 ms and drops the
  press scale; colour, icon and label cues stay.
- `will-change` only for transform, opacity or filter, and only after seeing a stutter.

## 8. Glass

`.glass` is the 72% fill (`--glass`) with `blur(24px) saturate(1.4)` and the floating shadow.

- Allowed on: the shell bar, the sidebar, floating panels. Not on cards, tables or any content.
- Text on glass uses `--ink` or `--label` only, and passes 4.5:1 over every backdrop that can
  scroll beneath it (section 3).
- `prefers-reduced-transparency: reduce`, and browsers without `backdrop-filter`, switch to the
  solid `--glass-solid` and drop the blur. Both fallbacks are also contrast-checked.

## 9. Component rules

- **Black pill.** The primary action and the active item (current nav item, selected segment)
  use `bg-pill text-pill-foreground`, fully rounded. There is at most one primary pill per view.
  It inverts in dark mode through the same tokens. Inactive pills are outlined with
  `--control-boundary`.
- **Status chips.** `StatusChip` always renders an icon (`aria-hidden`) and the word. 28 px
  tall, 13 px text, fully rounded. A failed state in prose also uses the Failed chip.
- **Platform swatches.** A pastel tile with the platform name in its own ink. Never a brand logo.
- **Cards.** `.card-surface`: solid `--surface`, 28 px radius, soft shadow, no border. Nested
  tiles use 20 px with 8 px padding.
- **Circular icon buttons.** 40 px, `rounded-full`, 1.5 px outline icon, a 3:1 boundary, an
  `aria-label`, press scale 0.96.
- **Sidebar.** Glass on `--sidebar`, 1 px `--hairline` divider, the current item is a black pill.
  256 px open, a 64 px rail (icons centred in 40 px links, labels `sr-only` so the name survives,
  the waiting count as a dot with its "N waiting" text outside the badge, a theme menu beside the
  avatar), a sheet below 768 px. Width moves 300 ms with `--ease-out`. With no saved choice a
  768 to 1179 px window starts as the rail; a saved choice always wins.
- **Popover.** Base UI Popover, non-modal, `card-surface` with the floating shadow; opacity and
  scale 0.96 to 1 from the trigger, 150 ms in and 100 ms out; Esc closes and returns focus.
- **Needs you chip.** The one coloured control in the bar: `bg-st-awaiting text-st-awaiting-ink`,
  clock icon and count, `aria-pressed`; pressed adds a 2 px ink ring.
- **Floating panel.** Glass, `rounded-card`, the floating shadow, focus moves in and returns to
  the trigger on close; scrolled content never hides a focused control (`scroll-padding-top`).
- **Focus.** `:focus-visible` is a 2 px ring in `--focus-ring` with a 2 px offset, never
  semi-transparent.

## 10. Building the UI

The committed build lives in `src/brandcal/web_next/`, so pip users never need Node.

```sh
python scripts/build_ui.py   # npm ci only if web/node_modules is missing, then npm run build
```

`npm run build` is `next build` and then `web/scripts/postbuild.mjs`, which cleans and refills
`src/brandcal/web_next/` from `web/out/` and writes `csp.json`: for each HTML page, the sha256
of every inline script, inline style and `style=""` value. The build id is fixed in
`next.config.ts`, so a second build is byte-identical; CI rebuilds and fails on any difference.
Use Node 20.

`brandcal serve` serves the UI at `/` and the first vanilla views at `/mvp/`. For a page from
`web_next` it sends `default-src 'self'; script-src 'self' 'sha256-...'; style-src 'self'
'sha256-...'` built from that page's `csp.json` entry (loaded once at start), adding
`'unsafe-hashes'` only if the page has `style=""` attributes. `'unsafe-inline'` and
`'unsafe-eval'` are never sent. Do not inject `<style>` or `<script>` elements at runtime, and
avoid `style` props in components: the hashes cover only what is in the built HTML.

## 11. Checks

- `python scripts/ui_contrast.py` and `tests/test_ui_contrast.py`: the contrast gate.
- `tests/ui/test_next_home.py`: `/` and `/mvp/` in light and dark with zero console errors and
  zero CSP violations; screenshots in `build/ui-shots/`.
- axe-core (`wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa`) is a failing assertion on
  every route in both themes, with the panel closed and open, the collapsed rail, the phone sheet
  and each write dialog. Reports go to `build/ui-shots/axe-next-*.json`.
- `tests/ui/test_next_a11y.py` (blocking in CI as `ui-next`): rendered contrast, the keyboard walk
  (visible 3:1 focus indicator, not hidden, layout order, no trap, Shift+Tab back), focus into and
  back out of the panel and dialogs, reflow at 320 px, text spacing (1.4.12), 200% zoom, reduced
  motion and transparency, target size, the now line and the notice timer.
- Not covered by automation: drag alternatives, screen-reader output, real devices.
- The design and accessibility review that led to these gates is in [UI_REVIEW_N4.md](UI_REVIEW_N4.md).

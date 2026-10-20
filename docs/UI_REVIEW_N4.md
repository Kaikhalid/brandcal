# Design and accessibility review of the web UI (N4)

Scope: every route (`/`, `/?view=month`, `/needs-you/`, `/posts/`, `/channels/`, `/activity/`,
`/settings/`), the post panel and the write dialogs, in light and dark, at 1440, 1024, 390 and
320 px. Checklist: the make-interfaces-feel-better rules, the Apple HIG pages on layout, sidebars,
materials, typography, colour, dark mode, motion, focus, modality, disclosure and writing, and
WCAG 2.2 Level AA (the stricter rule wins). Demo data only (Example Co).

Severity: **High** is a WCAG 2.2 AA failure or broken behaviour; **Medium** is a clear rule
violation a user would notice; **Low** is taste. The gates that now keep these fixed are in
`tests/ui/test_next_a11y.py` (blocking in CI as `ui-next`) and are described in
[UI_STYLE.md](UI_STYLE.md) section 11.

| Id | View | Finding | Skill and rule | Severity | Fix | Fixed |
|---|---|---|---|---|---|---|
| N4-01 | Panel | Opening a post leaves Tab able to reach the skip link: the page behind the modal panel (below 1200 px) is inert, but the skip link sat outside the inert region | WCAG 2.4.3, modality: a modal contains focus | High | The skip link moved inside the inert shell body | yes |
| N4-02 | Panel, notice | The notice card covers the last rows of the panel and of the page when they are scrolled to the end, so a focused control can sit under it | WCAG 2.4.11 Focus Not Obscured | High | `pb-32` on the panel and `main`, `scroll-padding-bottom` on `html` | yes |
| N4-03 | Panel | The stale-approval banner is sticky and covers the first rows (version history) | HIG layout: nothing covers content | High | The banner is in the panel flow above the content | yes |
| N4-04 | Week, month, panel | Text spacing (1.4.12) clips week blocks and chips: fixed heights, `overflow-hidden`, `whitespace-nowrap` on chips and badges | WCAG 1.4.12 | High | Blocks use `min-height`; chips, platform badges and post badges wrap and have `min-h` | yes |
| N4-05 | All | Dev banner text on the salmon `--destructive` in dark did not read as a warning | HIG colour and dark mode: keep the meaning in both themes | Medium | New `--banner-bg` / `--banner-fg`: a deep red in both themes, 6.54:1 light and 8.28:1 dark (icon 3:1) | yes |
| N4-06 | Calendar | Posts are only faintly coloured by platform; sky and lilac were close and blush read like the Failed chip | make-interfaces-feel-better: colour carries meaning; WCAG 1.4.1 | Medium | Five distinct pastels (rose for Instagram) plus a stronger 4 px left edge and a dot, as tokens; text 4.5:1 in place | yes |
| N4-07 | Month, Posts, Needs you, filters | The platform colour was missing outside the week view | Consistency | Medium | `PlatformDot` in the badge and filter pills; `platformBlock` on cards | yes |
| N4-08 | Shell | The sidebar glass is invisible over a flat canvas | HIG materials: a material needs something behind it | Medium | Two faint fixed washes behind the shell; content stays solid; solid under reduced transparency; glass text re-checked (5.86:1 label, 13.97:1 ink at worst) | yes |
| N4-09 | Sidebar | A Kbd hint on every row is visual noise | make-interfaces-feel-better: restraint; HIG sidebars | Medium | Hints show on hover and focus of the row and in the collapsed rail's tooltip; the full list stays in Settings | yes |
| N4-10 | Sidebar | "Needs you" wraps to two lines with a two-digit count | HIG sidebars: labels stay on one line | Medium | `whitespace-nowrap` on labels, hints take no extra space until shown | yes |
| N4-11 | Panel | A heavy pill-shaped focus ring on the heading when the panel opens | make-interfaces-feel-better: focus looks like the control | Medium | A 1 px square outline for the heading (not a control); every control keeps the 2 px ring | yes |
| N4-12 | Calendar, 390 px | Two rows of filter pills push the calendar far down | HIG disclosure controls; layout on small screens | Medium | Below 640 px one "Filters (n)" disclosure with `aria-expanded` and the active count | yes |
| N4-13 | Shell | Viewer in dev-unverified mode: the Needs you count and the MVP strip | Consistency | Medium | Checked: both use `needs_you` statuses the schema also lists as states, whatever the role; a test pins it for a viewer | yes |
| N4-14 | `/mvp/` | `Cannot read properties of null (reading 'timezone')` in dev-unverified mode (and with no date in the URL): today was computed before the schema loaded | Broken behaviour | High | The date is filled in after the schema loads | yes |
| N4-15 | Calendar | The now line was untested (the fixture week never holds today) | Test gap | Medium | Test with Playwright's clock: right day and hour, `aria-hidden`, a visually hidden "Now: HH:MM" | yes |
| N4-16 | Notice | The 8 s timer, the pause on hover and focus and the never-covers-focus rule were not tested | Test gap | Medium | Test with Playwright's clock | yes |
| N4-17 | All | axe "needs review" on contrast (week blocks, panel over glass) was never confirmed | WCAG 1.4.3, 1.4.11 | Medium | Computed in-page contrast of every text node, icon and chip border, both themes | yes |
| N4-18 | All | The axe helpers in the new-UI tests only warned | Gate | Medium | They fail on any violation | yes |
| N4-19 | Posts, 320 px | The table scrolls sideways inside its own region | WCAG 1.4.10 (data tables are exempt) | Low | Kept; named in the test as the one exception besides the week grid | no |
| N4-20 | Docs | UI_SPEC 2.1 and 2.7 still described `/` as the vanilla MVP and "no inline script" | Docs match the build | Medium | Updated to the committed export, `/mvp/` and per-page hashes | yes |

## Checked and found fine

Light and dark themes are separate checked token sets; type is at least 13 px with tabular
figures; radii are concentric; motion uses named properties and honours reduced motion;
status is always an icon and a word; targets are at least 24 px or have the spacing exception;
heading order, landmarks, titles and `lang` are right on every route.

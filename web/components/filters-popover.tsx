"use client"

import { Clock, SlidersHorizontal, X } from "lucide-react"
import * as React from "react"

import { useAppData } from "@/components/app-data"
import { fieldClass, names, pillClass, Select } from "@/components/filters-bar"
import { PlatformDot, platformLabel } from "@/components/platform-swatch"
import { StatusChip, statusLabel } from "@/components/status-chip"
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "@/components/ui/popover"
import { needsStatuses } from "@/lib/needs-you"
import { FILTER_KEYS, moreCount, parseFilters, useUrlState } from "@/lib/url-state"
import { cn } from "@/lib/utils"

/** A part of the popover a direction may leave out (the channel lanes replace the platform half). */
export type FilterGroup = "platform" | "status"

const CLEAR = Object.fromEntries(FILTER_KEYS.map((key) => [key, null]))

/** The filters as URL state, plus the verbs the toolbar, popover and strip share. */
export function useFilterState() {
  const { schema, session } = useAppData()
  const { params, set } = useUrlState()
  const filters = parseFilters(params)
  const role = session.state === "ok" ? session.data.role : null
  const toggle = (key: "status" | "platform", id: string) => {
    // Read the address, not the last render: two quick clicks must both count.
    const now = parseFilters(new URLSearchParams(window.location.search))[key]
    set({ [key]: (now.includes(id) ? now.filter((x) => x !== id) : [...now, id]).join(",") })
  }
  const activeCount = filters.platform.length + filters.status.length + moreCount(filters)
  return {
    schema: schema.state === "ok" ? schema.data : null,
    role,
    filters,
    set,
    toggle,
    clear: () => set(CLEAR),
    activeCount,
  }
}

const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x))

function Group({ legend, children }: { legend: string; children: React.ReactNode }) {
  return (
    <fieldset className="flex min-w-0 flex-col gap-1">
      <legend className="mb-1 text-[0.8125rem] text-label">{legend}</legend>
      {children}
    </fieldset>
  )
}

const rowClass = "flex min-h-10 items-center gap-3 rounded-control px-2 text-sm hover:bg-muted"
const boxClass = "size-5 shrink-0 accent-[var(--pill-bg)]"

/** A checkbox whose state lives in the URL. The URL reaches React a moment after the click, so the
 *  box ticks at once on its own and is brought back in line (a chip removed, Back pressed) by the
 *  effect; a controlled box would flicker back to unticked first. */
function UrlCheckbox({
  checked,
  onToggle,
  ...rest
}: { checked: boolean; onToggle: (on: boolean) => void } & Omit<
  React.ComponentProps<"input">,
  "checked" | "onChange" | "type"
>) {
  const ref = React.useRef<HTMLInputElement>(null)
  React.useEffect(() => {
    if (ref.current) ref.current.checked = checked
  }, [checked])
  return (
    <input
      {...rest}
      ref={ref}
      type="checkbox"
      defaultChecked={checked}
      onChange={(e) => onToggle(e.target.checked)}
      className={boxClass}
    />
  )
}

function PopoverBody({ hide }: { hide: FilterGroup[] }) {
  const { schema, filters, set, toggle } = useFilterState()
  const id = React.useId()
  if (!schema) return null
  const closed = filters.closed ?? true
  // Two columns from 640 px: Platform beside Status, then the four fields in pairs.
  return (
    <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
      {!hide.includes("platform") && (
        <Group legend="Platform">
          {Object.keys(schema.platforms).map((p) => (
            <label key={p} className={rowClass}>
              <UrlCheckbox
                data-filter={`platform:${p}`}
                checked={filters.platform.includes(p)}
                onToggle={() => toggle("platform", p)}
              />
              <PlatformDot platform={p} />
              {platformLabel(p)}
            </label>
          ))}
        </Group>
      )}
      {!hide.includes("status") && (
        <Group legend="Status">
          {schema.states.map((s) => (
            <label key={s} className={rowClass}>
              <UrlCheckbox
                data-filter={`status:${s}`}
                checked={filters.status.includes(s)}
                onToggle={() => toggle("status", s)}
              />
              <StatusChip status={s} className="min-h-6 py-0.5" />
            </label>
          ))}
        </Group>
      )}
      <Select label="Post type" value={filters.type} options={schema.post_types} onChange={(v) => set({ type: v })} />
      <Select label="Campaign" value={filters.campaign} options={names(schema.campaigns)} onChange={(v) => set({ campaign: v })} />
      <Select label="Pillar" value={filters.pillar} options={names(schema.pillars)} onChange={(v) => set({ pillar: v })} />
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${id}-q`} className="text-sm text-label">
          Search by slug
        </label>
        <input
          id={`${id}-q`}
          type="search"
          value={filters.q}
          onChange={(e) => set({ q: e.target.value }, "replace")}
          className={fieldClass}
          spellCheck={false}
        />
      </div>
      <label className={cn(rowClass, "sm:col-span-2")}>
        <UrlCheckbox checked={closed} onToggle={(on) => set({ closed: on ? "1" : "0" })} />
        Include published and cancelled posts
      </label>
    </div>
  )
}

/** The one Filters control: a non-modal popover. Esc closes it and returns focus to the button;
 *  every choice is URL state, so a filtered view can be shared. Below 1100 px of content width
 *  (a container query on the shell) the button is an icon with a count dot. */
export function FiltersPopover({ hide = [] }: { hide?: FilterGroup[] }) {
  const { schema, filters, activeCount: all } = useFilterState()
  if (!schema) return null
  // A half the page replaces (the lanes) is counted by that page, not here.
  const activeCount =
    all - (hide.includes("platform") ? filters.platform.length : 0) - (hide.includes("status") ? filters.status.length : 0)
  return (
    <Popover>
      <PopoverTrigger
        data-filters-toggle
        className={cn(
          pillClass(activeCount > 0),
          "relative h-10 gap-2 @max-[1100px]:w-10 @max-[1100px]:justify-center @max-[1100px]:px-0"
        )}
      >
        <SlidersHorizontal aria-hidden="true" strokeWidth={1.5} className="size-4" />
        <span className="@max-[1100px]:sr-only">Filters</span>
        {activeCount > 0 && (
          <>
            <span className="tabular-nums @max-[1100px]:sr-only">({activeCount})</span>
            <span
              aria-hidden="true"
              className="absolute top-1.5 right-1.5 hidden size-2.5 rounded-full bg-pill-foreground @max-[1100px]:block"
            />
          </>
        )}
      </PopoverTrigger>
      <PopoverContent align="end" className="flex w-[34rem] flex-col gap-4">
        <PopoverTitle>Filters</PopoverTitle>
        <PopoverBody hide={hide} />
      </PopoverContent>
    </Popover>
  )
}

/** The amber "Needs you" chip-button: one press applies the statuses the schema lists as needing
 *  the viewer (the same rule as the sidebar badge); pressing again removes them. The only coloured
 *  control in the bar. */
export function NeedsYouChip() {
  const { needsYou } = useAppData()
  const { schema, filters, set } = useFilterState()
  if (!schema) return null
  const target = needsStatuses(schema)
  const on = target.length > 0 && sameSet(filters.status, target)
  const count = needsYou.state === "ok" ? needsYou.data : null
  return (
    <button
      type="button"
      aria-pressed={on}
      data-needs-you-chip
      onClick={() => set({ status: on ? null : target.join(",") })}
      className="press inline-flex h-10 items-center gap-2 rounded-full bg-st-awaiting px-4 text-sm whitespace-nowrap text-st-awaiting-ink hover:brightness-[0.97] aria-pressed:ring-2 aria-pressed:ring-ink @max-[1100px]:px-3"
    >
      <Clock aria-hidden="true" strokeWidth={1.5} className="size-4 shrink-0" />
      <span className="@max-[1100px]:sr-only">Needs you</span>
      {count !== null && count > 0 && (
        <span className="tabular-nums">
          {count}
          <span className="sr-only"> waiting</span>
        </span>
      )}
    </button>
  )
}

type Chip = { key: string; label: string; remove: () => void }

function chipsFor(f: ReturnType<typeof useFilterState>, hide: FilterGroup[]): Chip[] {
  const { filters, set, toggle, role } = f
  const out: Chip[] = []
  if (!hide.includes("platform")) {
    for (const p of filters.platform) out.push({ key: `platform:${p}`, label: platformLabel(p), remove: () => toggle("platform", p) })
  }
  if (!hide.includes("status")) {
    for (const s of filters.status) out.push({ key: `status:${s}`, label: statusLabel(s, role), remove: () => toggle("status", s) })
  }
  if (filters.type) out.push({ key: "type", label: `Type: ${filters.type}`, remove: () => set({ type: null }) })
  if (filters.campaign) out.push({ key: "campaign", label: `Campaign: ${filters.campaign}`, remove: () => set({ campaign: null }) })
  if (filters.pillar) out.push({ key: "pillar", label: `Pillar: ${filters.pillar}`, remove: () => set({ pillar: null }) })
  if (filters.q) out.push({ key: "q", label: `Slug: ${filters.q}`, remove: () => set({ q: null }) })
  if (filters.closed !== null) {
    out.push({
      key: "closed",
      label: filters.closed ? "With published and cancelled" : "Without published and cancelled",
      remove: () => set({ closed: null }),
    })
  }
  return out
}

/** The 32 px context strip under the bar: a summary line (zone offset, counts) the page supplies,
 *  then a removable chip per active filter, "Clear filters" and a polite live count. */
export function FilterStrip({
  summary,
  hide = [],
}: {
  summary: React.ReactNode
  hide?: FilterGroup[]
}) {
  const state = useFilterState()
  const chips = chipsFor(state, hide)
  return (
    <div
      data-filter-strip
      className="flex min-h-8 shrink-0 flex-wrap items-center gap-x-3 gap-y-1 px-4 py-1 text-[0.8125rem] text-label md:px-6"
    >
      <p className="tabular-nums">{summary}</p>
      {chips.length > 0 && (
        <>
          <span aria-hidden="true" className="h-4 w-px bg-hairline" />
          <ul aria-label="Active filters" className="flex flex-wrap items-center gap-2">
            {chips.map((chip) => (
              <li key={chip.key}>
                <button
                  type="button"
                  data-filter-chip={chip.key}
                  onClick={chip.remove}
                  aria-label={`Remove filter: ${chip.label}`}
                  className="press inline-flex h-6 items-center gap-1 rounded-full bg-muted pr-1.5 pl-2.5 text-[0.8125rem] text-ink hover:bg-accent"
                >
                  {chip.label}
                  <X aria-hidden="true" strokeWidth={1.5} className="size-3.5" />
                </button>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={state.clear}
            className="min-h-6 rounded-control px-1 text-[0.8125rem] underline underline-offset-4 hover:text-ink"
          >
            Clear filters
          </button>
        </>
      )}
      <span role="status" aria-live="polite" className="sr-only">
        {chips.length ? `${chips.length} ${chips.length === 1 ? "filter" : "filters"} applied` : ""}
      </span>
    </div>
  )
}

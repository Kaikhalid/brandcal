"use client"

import { SlidersHorizontal } from "lucide-react"
import * as React from "react"

import { useAppData } from "@/components/app-data"
import { platformLabel } from "@/components/platform-swatch"
import { statusLabel } from "@/components/status-chip"
import type { Schema } from "@/lib/api"
import { FILTER_KEYS, moreCount, parseFilters, useUrlState, type Filters } from "@/lib/url-state"
import { cn } from "@/lib/utils"

export const pillClass = (active: boolean) =>
  cn(
    "press inline-flex h-9 items-center rounded-full border px-4 text-sm whitespace-nowrap",
    active
      ? "border-transparent bg-pill text-pill-foreground"
      : "border-control bg-surface text-ink hover:bg-muted"
  )

const fieldClass =
  "h-10 w-full rounded-control border border-control bg-surface px-3 text-sm text-ink"

const names = (items: unknown[]) => items.map((item) => String(item))

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: string[]
  onChange: (value: string) => void
}) {
  const id = React.useId()
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm text-label">
        {label}
      </label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={fieldClass}>
        <option value="">Any</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </div>
  )
}

function MoreFilters({
  schema,
  filters,
  closedByDefault,
  set,
}: {
  schema: Schema
  filters: Filters
  closedByDefault: boolean
  set: (patch: Record<string, string | null>, mode?: "push" | "replace") => void
}) {
  const [open, setOpen] = React.useState(false)
  const box = React.useRef<HTMLDivElement>(null)
  const button = React.useRef<HTMLButtonElement>(null)
  const count = moreCount(filters)
  const id = React.useId()

  React.useEffect(() => {
    if (!open) return
    const away = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("pointerdown", away)
    return () => document.removeEventListener("pointerdown", away)
  }, [open])

  const closed = filters.closed ?? closedByDefault
  return (
    <div
      ref={box}
      className="relative"
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.stopPropagation()
          setOpen(false)
          button.current?.focus()
        }
      }}
    >
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
        className={cn(pillClass(count > 0), "gap-2")}
      >
        <SlidersHorizontal aria-hidden="true" strokeWidth={1.5} className="size-4" />
        More filters{count > 0 && <span className="tabular-nums"> ({count})</span>}
      </button>
      {open && (
        <div
          id={id}
          role="group"
          aria-label="More filters"
          className="card-surface absolute top-full left-0 z-30 mt-2 flex w-80 max-w-[calc(100vw-3rem)] flex-col gap-4 p-5 shadow-float"
        >
          <Select
            label="Post type"
            value={filters.type}
            options={schema.post_types}
            onChange={(v) => set({ type: v })}
          />
          <Select
            label="Campaign"
            value={filters.campaign}
            options={names(schema.campaigns)}
            onChange={(v) => set({ campaign: v })}
          />
          <Select
            label="Pillar"
            value={filters.pillar}
            options={names(schema.pillars)}
            onChange={(v) => set({ pillar: v })}
          />
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
          <label className="flex min-h-6 items-center gap-3 text-sm">
            <input
              type="checkbox"
              checked={closed}
              onChange={(e) => set({ closed: e.target.checked ? "1" : "0" })}
              className="size-5 accent-[var(--pill-bg)]"
            />
            Include published and cancelled posts
          </label>
        </div>
      )}
    </div>
  )
}

/** Multi-select pills for platforms and statuses, plus the rest behind "More filters". All of it
 *  is URL state, so a filtered view can be shared. */
export function FiltersBar({ closedByDefault }: { closedByDefault: boolean }) {
  const { schema, session } = useAppData()
  const { params, set } = useUrlState()
  const filters = parseFilters(params)
  const role = session.state === "ok" ? session.data.role : null
  if (schema.state !== "ok") return null

  const toggle = (key: "status" | "platform", id: string) => {
    const now = filters[key]
    set({ [key]: (now.includes(id) ? now.filter((x) => x !== id) : [...now, id]).join(",") })
  }
  const active = FILTER_KEYS.some((key) => params.get(key))
  const groups = [
    { key: "platform", label: "Platform", ids: Object.keys(schema.data.platforms), text: platformLabel },
    {
      key: "status",
      label: "Status",
      ids: schema.data.states,
      text: (id: string) => statusLabel(id, role),
    },
  ] as const

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
      {groups.map(({ key, label, ids, text }) => (
        <div key={key} role="group" aria-label={label} className="flex flex-wrap items-center gap-2">
          {ids.map((id) => {
            const on = filters[key].includes(id)
            return (
              <button
                key={id}
                type="button"
                aria-pressed={on}
                data-filter={`${key}:${id}`}
                onClick={() => toggle(key, id)}
                className={pillClass(on)}
              >
                {text(id)}
              </button>
            )
          })}
        </div>
      ))}
      <MoreFilters
        schema={schema.data}
        filters={filters}
        closedByDefault={closedByDefault}
        set={set}
      />
      {active && (
        <button
          type="button"
          onClick={() => set(Object.fromEntries(FILTER_KEYS.map((key) => [key, null])))}
          className="min-h-6 rounded-control px-2 text-sm text-label underline underline-offset-4 hover:text-ink"
        >
          Clear filters
        </button>
      )}
    </div>
  )
}

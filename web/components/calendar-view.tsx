"use client"

import { CalendarDays } from "lucide-react"
import * as React from "react"

import { useAppData } from "@/components/app-data"
import { CalendarToolbar } from "@/components/calendar-toolbar"
import { DayBands, DayNumber, type Entry, type Open } from "@/components/day-bands"
import { EmptyState } from "@/components/empty-state"
import { ErrorPanel } from "@/components/error-panel"
import { FilterStrip } from "@/components/filters-popover"
import { RailButton, useRail } from "@/components/inspector-rail"
import { PlatformMark, platformBlock } from "@/components/platform-swatch"
import { settleFocus, useOpenPost } from "@/components/post-bits"
import { StatusChip, statusLabel } from "@/components/status-chip"
import { Skeleton } from "@/components/ui/skeleton"
import { usePostItems } from "@/components/use-post-items"
import { useElementWidth } from "@/components/use-element-width"
import { ViewGate } from "@/components/view-gate"
import type { Schema } from "@/lib/api"
import {
  DAYS,
  addDays,
  dayLabel,
  isDateKey,
  localParts,
  monthStart,
  parseDate,
  rangeFor,
  spanOf,
  todayKey,
  zoneOffset,
  type View,
} from "@/lib/time"
import { FILTER_KEYS, applyFilters, parseFilters, useUrlState } from "@/lib/url-state"
import { cn } from "@/lib/utils"

const MONTH_COLUMNS_MIN = 840 // px of calendar box: from here the month is a grid, below it day bands

/** The time now in the configured zone, refreshed each minute (a clock, not a poll of the API). */
function useNow(zone: string | null) {
  const [now, setNow] = React.useState<string | null>(null)
  React.useEffect(() => {
    const tick = () => setNow(new Date().toISOString())
    tick()
    const timer = window.setInterval(tick, 60_000)
    return () => window.clearInterval(timer)
  }, [])
  return now === null ? null : localParts(now, zone)
}

type Common = { entry: Entry; open: Open; current: boolean }

/** A post in a month cell: time and status icon, the platform, then the title in two lines. */
function MonthCard({ entry: { item, span }, open, current }: Common) {
  const { row } = item
  return (
    <button
      type="button"
      data-post-id={row.id}
      data-day={span.day}
      data-start={span.from}
      aria-current={current ? "true" : undefined}
      title={row.window ?? undefined}
      onClick={(e) => open(row.id, e.currentTarget)}
      className={cn(
        "press flex w-full min-w-0 flex-col items-start gap-1 rounded-control p-2 text-left shadow-card",
        "hover:brightness-[0.97] aria-[current=true]:outline-2 aria-[current=true]:outline-ink",
        platformBlock(row.platform)
      )}
    >
      <span className="flex w-full items-center justify-between gap-1">
        <span className="text-[0.8125rem] tabular-nums">{span.from}</span>
        <StatusChip status={row.status} iconOnly />
      </span>
      <PlatformMark platform={row.platform} className="max-w-full" />
      <span className="line-clamp-2 text-sm leading-snug font-medium break-words">{row.title}</span>
    </button>
  )
}

function MonthGrid({
  days,
  month,
  byDay,
  today,
  open,
  post,
}: {
  days: string[]
  month: number
  byDay: Map<string, Entry[]>
  today: string
  open: Open
  post: string | null
}) {
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set())
  return (
    <div
      role="region"
      aria-label="Month calendar"
      tabIndex={0}
      className="card-surface relative h-full scroll-pb-32 overflow-y-auto"
    >
      <div>
        <div className="sticky top-0 z-10 grid grid-cols-7 border-b border-hairline bg-surface">
          {[...DAYS.slice(1), DAYS[0]].map((d) => (
            <div key={d} className="px-3 py-2 text-sm text-label">
              {d}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7">
          {days.map((day) => {
            const mine = byDay.get(day) ?? []
            const all = expanded.has(day)
            const shown = all ? mine : mine.slice(0, 2)
            return (
              <div
                key={day}
                role="group"
                aria-label={dayLabel(day)}
                aria-current={day === today ? "date" : undefined}
                data-day={day}
                className={cn(
                  "flex min-h-24 min-w-0 flex-col gap-1.5 border-t border-l border-hairline p-2 nth-[7n+1]:border-l-0",
                  parseDate(day)[1] !== month && "bg-canvas"
                )}
              >
                <DayNumber day={day} today={day === today} light={parseDate(day)[1] !== month} />
                {shown.map((entry) => (
                  <MonthCard
                    key={entry.item.row.id}
                    entry={entry}
                    open={open}
                    current={post === entry.item.row.id}
                  />
                ))}
                {mine.length > 2 && (
                  <button
                    type="button"
                    aria-expanded={all}
                    onClick={() => {
                      const next = new Set(expanded)
                      if (all) next.delete(day)
                      else next.add(day)
                      setExpanded(next)
                    }}
                    className="press min-h-6 self-start rounded-full px-2 text-sm text-label underline underline-offset-4 hover:text-ink"
                  >
                    {all ? "Show fewer" : `+${mine.length - 2} more`}
                  </button>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function CalendarSkeleton() {
  return (
    <div role="status" aria-busy="true" aria-label="Loading the calendar" className="flex flex-col gap-2">
      {Array.from({ length: 4 }, (_, i) => (
        <div key={i} className="flex gap-3 rounded-inner bg-surface p-2 shadow-card">
          <Skeleton className="h-16 w-20" />
          <Skeleton className="h-16 flex-1 rounded-control" />
        </div>
      ))}
    </div>
  )
}

function CalendarBody({ schema }: { schema: Schema }) {
  const { params, set } = useUrlState()
  const zone = schema.timezone
  const view: View = params.get("view") === "month" ? "month" : "week"
  const today = todayKey(zone)
  const dateParam = params.get("date")
  const date = isDateKey(dateParam) ? dateParam : today
  const [from, to] = rangeFor(view, date)
  const items = usePostItems(from, to)
  const open = useOpenPost()
  const now = useNow(zone)
  const { beside } = useRail()
  // The week is always day bands (the inspector rail takes the width a column grid would want).
  // The month is a grid when its box is wide enough to read; the width of the calendar box itself,
  // so the rail opening beside it never causes sideways scroll. Bands are the first paint.
  const [box, width] = useElementWidth<HTMLDivElement>()
  const monthGrid = view === "month" && width !== null && width >= MONTH_COLUMNS_MIN
  // The layout switched (the box widened or narrowed): give focus to the post that opened it, if one waits.
  React.useEffect(() => {
    settleFocus()
  }, [monthGrid])
  const { session } = useAppData()
  const role = session.state === "ok" ? session.data.role : null
  const post = params.get("post")

  const days = React.useMemo(() => {
    const out: string[] = []
    for (let d = from; d <= to; d = addDays(d, 1)) out.push(d)
    return out
  }, [from, to])

  const visible = React.useMemo(() => {
    if (items.state !== "ok") return []
    return applyFilters(items.data, parseFilters(params), schema, true).filter(
      ({ row }) => row.window
    )
  }, [items, params, schema])

  const byDay = React.useMemo(() => {
    const map = new Map<string, Entry[]>()
    for (const item of visible) {
      const span = spanOf(item.row.window ?? "", zone)
      map.set(span.day, [...(map.get(span.day) ?? []), { item, span }])
    }
    for (const list of map.values()) list.sort((a, b) => a.span.startMin - b.span.startMin)
    return map
  }, [visible, zone])

  const step = (n: number) =>
    set({ view, date: view === "week" ? addDays(date, 7 * n) : monthStart(date, n) })
  const unit = view === "week" ? "week" : "month"
  const inRange = today >= from && today <= to
  const month = parseDate(date)[1]

  const offset = zoneOffset(zone)
  const count = visible.length
  const awaiting = visible.filter(({ row }) => row.status === "pending_approval").length
  const published = visible.filter(({ row }) => row.status === "published").length
  const label = view === "week" ? "Week calendar" : "Month calendar"

  return (
    <>
      <CalendarToolbar
        view={view}
        date={date}
        inRange={inRange}
        step={step}
        today={() => set({ date: today })}
        onView={(next) => set({ view: next, date })}
        // The rail is the Needs you queue; below 1180 px, where it is a sheet, a button opens it.
        needsYou={beside ? null : <RailButton />}
      />
      <FilterStrip
        summary={
          <>
            <span title={zone ?? undefined}>
              <span className="sr-only">Times in </span>
              {offset ?? "the zone each post carries"}
            </span>
            {` · ${count} ${count === 1 ? "post" : "posts"} · ${awaiting} ${statusLabel("pending_approval", role).toLowerCase()} · ${published} published`}
          </>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4 md:px-6">
        <div ref={box} className="h-full">
          {items.state === "loading" ? (
            <CalendarSkeleton />
          ) : items.state === "error" ? (
            <ErrorPanel error={items.refusal} />
          ) : visible.length === 0 ? (
            <EmptyState
              icon={CalendarDays}
              line={`No posts in this ${unit}${FILTER_KEYS.some((key) => params.get(key)) ? " with these filters" : ""}. Agents add posts through the CLI.`}
              command="brandcal add --as NAME ..."
            />
          ) : monthGrid ? (
            <MonthGrid
              days={days}
              month={month}
              byDay={byDay}
              today={today}
              open={open}
              post={post}
            />
          ) : (
            <DayBands
              days={days}
              byDay={byDay}
              today={today}
              now={inRange ? now : null}
              open={open}
              post={post}
              quietDays={view === "week"}
              label={label}
              zone={zone}
            />
          )}
        </div>
      </div>
    </>
  )
}

export function CalendarView() {
  return (
    <ViewGate label="Loading the calendar" rows={2}>
      {(schema) => <CalendarBody schema={schema} />}
    </ViewGate>
  )
}

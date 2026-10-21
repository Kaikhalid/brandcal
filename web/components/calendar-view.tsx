"use client"

import { CalendarDays } from "lucide-react"
import * as React from "react"

import { useAppData } from "@/components/app-data"
import { CalendarToolbar } from "@/components/calendar-toolbar"
import { DayNumber, PostCard, type Entry, type Open } from "@/components/calendar-bits"
import { EmptyState } from "@/components/empty-state"
import { ErrorPanel } from "@/components/error-panel"
import { FilterStrip, useFilterState } from "@/components/filters-popover"
import { LaneGrid, LaneShowing } from "@/components/lane-grid"
import { PlatformMark, platformBlock } from "@/components/platform-swatch"
import { PostBadges, settleFocus, useOpenPost } from "@/components/post-bits"
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
  dowOf,
  isDateKey,
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

const LANES_MIN = 880 // px of calendar box: from here the week is lanes, below it day bands

/** A post as a card: the day list on a small screen. */
function Card({ entry: { item, span }, open, current }: { entry: Entry; open: Open; current: boolean }) {
  const { row, detail } = item
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
        "press flex w-full flex-col items-start gap-1.5 rounded-control p-4 text-left shadow-card",
        "hover:brightness-[0.97] aria-[current=true]:outline-2 aria-[current=true]:outline-ink",
        platformBlock(row.platform)
      )}
    >
      <span className="flex w-full min-w-0 items-baseline gap-2">
        <span className="shrink-0 text-[0.8125rem] tabular-nums">{span.from}</span>
        <span className="min-w-0 text-base font-medium">{row.title}</span>
      </span>
      <span className="text-[0.8125rem] tabular-nums">
        {span.text} · {detail.post_type}
      </span>
      <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <PlatformMark platform={row.platform} />
      </span>
      <StatusChip status={row.status} className="min-h-6 gap-1 px-2 text-[0.8125rem]" />
      <PostBadges post={detail} />
    </button>
  )
}

/** The month as a plain grid. Weeks take the height their posts need (no fixed rows), and a day with
 *  more than three posts folds the rest behind "+n more". */
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
      className="card-surface relative max-h-full scroll-pb-32 overflow-y-auto"
    >
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
          const shown = all ? mine : mine.slice(0, 3)
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
                <PostCard
                  key={entry.item.row.id}
                  entry={entry}
                  open={open}
                  current={post === entry.item.row.id}
                  showPlatform
                />
              ))}
              {mine.length > 3 && (
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
                  {all ? "Show fewer" : `+${mine.length - 3} more`}
                </button>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** Below 880px the week (and the month) becomes a list of days, each with a sticky heading and the
 *  channel printed on every card. */
function DayList({
  days,
  byDay,
  today,
  open,
  post,
  quietDays,
  label,
}: {
  days: string[]
  byDay: Map<string, Entry[]>
  today: string
  open: Open
  post: string | null
  quietDays: boolean
  label: string
}) {
  return (
    <div
      role="region"
      aria-label={label}
      tabIndex={0}
      className="flex h-full scroll-pb-32 flex-col gap-6 overflow-y-auto"
    >
      {days
        .filter((d) => quietDays || (byDay.get(d) ?? []).length)
        .map((day) => {
          const mine = byDay.get(day) ?? []
          return (
            <section key={day} aria-label={dayLabel(day)} data-day={day} className="flex flex-col gap-3">
              <h3
                aria-current={day === today ? "date" : undefined}
                className="sticky top-0 z-10 flex items-center gap-3 rounded-control bg-canvas px-4 py-2 text-base font-normal"
              >
                <span className="text-label">{DAYS[dowOf(day)]}</span>
                <DayNumber day={day} today={day === today} />
              </h3>
              {mine.length ? (
                mine.map((entry) => (
                  <Card
                    key={entry.item.row.id}
                    entry={entry}
                    open={open}
                    current={post === entry.item.row.id}
                  />
                ))
              ) : (
                <p className="text-sm text-label">Nothing planned.</p>
              )}
            </section>
          )
        })}
    </div>
  )
}

function CalendarSkeleton() {
  return (
    <div role="status" aria-busy="true" aria-label="Loading the calendar" className="card-surface p-4">
      <div className="flex flex-col gap-3">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-24 w-full rounded-inner" />
        ))}
      </div>
    </div>
  )
}

function CalendarBody({ schema }: { schema: Schema }) {
  const { params, set } = useUrlState()
  const filterState = useFilterState()
  const zone = schema.timezone
  const view: View = params.get("view") === "month" ? "month" : "week"
  const today = todayKey(zone)
  const dateParam = params.get("date")
  const date = isDateKey(dateParam) ? dateParam : today
  const [from, to] = rangeFor(view, date)
  const items = usePostItems(from, to)
  const open = useOpenPost()
  // Lanes need room: the width of the calendar box itself, so the panel opening beside it
  // switches to day bands instead of scrolling sideways. Bands are the first paint (the safe layout).
  const [box, width] = useElementWidth<HTMLDivElement>()
  const columns = width !== null && width >= LANES_MIN
  const lanes = columns && view === "week"
  // The layout switched (the panel closed): give focus to the post that opened it, if one waits.
  React.useEffect(() => {
    settleFocus()
  }, [columns])
  const { session } = useAppData()
  const role = session.state === "ok" ? session.data.role : null
  const post = params.get("post")

  const days = React.useMemo(() => {
    const out: string[] = []
    for (let d = from; d <= to; d = addDays(d, 1)) out.push(d)
    return out
  }, [from, to])

  // Every filter but the channel: the lanes print their own counts, so they need the channels
  // the filter would hide as well.
  const pool = React.useMemo<Entry[]>(() => {
    if (items.state !== "ok") return []
    const rest = { ...parseFilters(params), platform: [] }
    return applyFilters(items.data, rest, schema, true)
      .filter(({ row }) => row.window)
      .map((item) => ({ item, span: spanOf(item.row.window ?? "", zone) }))
  }, [items, params, schema, zone])

  const selected = filterState.filters.platform
  const entries = React.useMemo(
    () => (selected.length ? pool.filter((e) => selected.includes(e.item.row.platform)) : pool),
    [pool, selected]
  )

  const byDay = React.useMemo(() => {
    const map = new Map<string, Entry[]>()
    for (const entry of entries) map.set(entry.span.day, [...(map.get(entry.span.day) ?? []), entry])
    for (const list of map.values()) list.sort((a, b) => a.span.startMin - b.span.startMin)
    return map
  }, [entries])

  // One lane per platform the schema lists, then any other a post carries.
  const platforms = React.useMemo(() => {
    const known = Object.keys(schema.platforms)
    const extra = [...new Set(pool.map((e) => e.item.row.platform))].filter((p) => !known.includes(p))
    return [...known, ...extra]
  }, [schema, pool])

  const step = (n: number) =>
    set({ view, date: view === "week" ? addDays(date, 7 * n) : monthStart(date, n) })
  const unit = view === "week" ? "week" : "month"
  const inRange = today >= from && today <= to
  const month = parseDate(date)[1]

  const offset = zoneOffset(zone)
  const count = entries.length
  const awaiting = entries.filter(({ item }) => item.row.status === "pending_approval").length
  const published = entries.filter(({ item }) => item.row.status === "published").length
  const label = view === "week" ? "Week calendar" : "Month calendar"
  const hide = lanes ? (["platform"] as const) : []

  return (
    <>
      <CalendarToolbar
        view={view}
        date={date}
        inRange={inRange}
        step={step}
        today={() => set({ date: today })}
        onView={(next) => set({ view: next, date })}
        hideFilters={[...hide]}
      />
      <FilterStrip
        hide={[...hide]}
        summary={
          <>
            <span title={zone ?? undefined}>
              <span className="sr-only">Times in </span>
              {offset ?? "the zone each post carries"}
            </span>
            {` · ${count} ${count === 1 ? "post" : "posts"} · ${awaiting} ${statusLabel("pending_approval", role).toLowerCase()} · ${published} published`}
            {lanes && (
              <LaneShowing
                selected={selected}
                remove={(p) => filterState.toggle("platform", p)}
                clear={() => set({ platform: null })}
              />
            )}
          </>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4 md:px-6">
        <div ref={box} className="h-full">
          {items.state === "loading" ? (
            <CalendarSkeleton />
          ) : items.state === "error" ? (
            <ErrorPanel error={items.refusal} />
          ) : (lanes ? pool : entries).length === 0 ? (
            <EmptyState
              icon={CalendarDays}
              line={`No posts in this ${unit}${FILTER_KEYS.some((key) => params.get(key)) ? " with these filters" : ""}. Agents add posts through the CLI.`}
              command="brandcal add --as NAME ..."
            />
          ) : lanes ? (
            <LaneGrid
              days={days}
              entries={pool}
              platforms={platforms}
              selected={selected}
              today={today}
              open={open}
              post={post}
              zone={zone}
              toggle={(p) => filterState.toggle("platform", p)}
            />
          ) : !columns || view === "week" ? (
            <DayList
              days={days}
              byDay={byDay}
              today={today}
              open={open}
              post={post}
              quietDays={view === "week"}
              label={label}
            />
          ) : (
            <MonthGrid
              days={days}
              month={month}
              byDay={byDay}
              today={today}
              open={open}
              post={post}
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

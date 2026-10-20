"use client"

import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react"
import * as React from "react"

import { EmptyState } from "@/components/empty-state"
import { ErrorPanel } from "@/components/error-panel"
import { FiltersBar, pillClass } from "@/components/filters-bar"
import { PlatformMark, platformBlock } from "@/components/platform-swatch"
import { PostBadges, TypeIcon, useOpenPost } from "@/components/post-bits"
import { StatusChip } from "@/components/status-chip"
import { Skeleton } from "@/components/ui/skeleton"
import { usePostItems } from "@/components/use-post-items"
import { useMedia } from "@/components/use-media"
import { Figure, ViewGate } from "@/components/view-gate"
import type { Schema } from "@/lib/api"
import {
  DAYS,
  addDays,
  clock,
  dayLabel,
  dowOf,
  isDateKey,
  localParts,
  monthStart,
  parseDate,
  rangeFor,
  rangeLabel,
  spanOf,
  todayKey,
  type Span,
  type View,
} from "@/lib/time"
import {
  FILTER_KEYS,
  applyFilters,
  parseFilters,
  useUrlState,
  type PostItem,
} from "@/lib/url-state"
import { cn } from "@/lib/utils"

const HOUR_REM = 9 // the height of an hour row; keep in step with --hour in globals.css
const MIN_BLOCK = 60 // minutes: a shorter window is drawn this tall so its text stays readable

type Entry = { item: PostItem; span: Span }
type Placed = Entry & { lane: number; lanes: number }

/** Posts that overlap in time share the day column side by side, one lane each. */
function place(entries: Entry[]): Placed[] {
  const sorted = [...entries].sort(
    (a, b) => a.span.startMin - b.span.startMin || a.span.endMin - b.span.endMin
  )
  const out: Placed[] = []
  let cluster: Placed[] = []
  let laneEnds: number[] = []
  let clusterEnd = 0
  const flush = () => {
    for (const p of cluster) p.lanes = laneEnds.length
    out.push(...cluster)
    cluster = []
    laneEnds = []
  }
  for (const e of sorted) {
    if (cluster.length && e.span.startMin >= clusterEnd) flush()
    const end = Math.max(e.span.endMin, e.span.startMin + MIN_BLOCK)
    let lane = laneEnds.findIndex((x) => x <= e.span.startMin)
    if (lane < 0) {
      lane = laneEnds.length
      laneEnds.push(end)
    } else {
      laneEnds[lane] = end
    }
    cluster.push({ ...e, lane, lanes: 0 })
    clusterEnd = Math.max(clusterEnd, end)
  }
  flush()
  return out
}

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

type Common = { entry: Entry; open: ReturnType<typeof useOpenPost>; current: boolean }

/** A post as a soft pastel block in the week grid. */
function Block({
  entry: { item, span },
  lane,
  lanes,
  open,
  current,
}: Common & { lane: number; lanes: number }) {
  const { row, detail } = item
  const end = Math.max(span.endMin, span.startMin + MIN_BLOCK)
  return (
    <button
      type="button"
      data-post-id={row.id}
      data-start={span.from}
      data-day={span.day}
      aria-current={current ? "true" : undefined}
      title={row.window ?? undefined}
      onClick={(e) => open(row.id, e.currentTarget)}
      style={{
        top: `calc(var(--hour) * ${span.startMin / 60})`,
        // A minimum, not a fixed height: wider text spacing grows the block instead of clipping it.
        minHeight: `calc(var(--hour) * ${(end - span.startMin) / 60} - 4px)`,
        left: `calc(${(lane / lanes) * 100}% + 2px)`,
        width: `calc(${100 / lanes}% - 4px)`,
      }}
      className={cn(
        "press absolute flex flex-col items-start gap-1 rounded-control p-2.5 text-left shadow-card hover:z-[6] focus-visible:z-[6]",
        "hover:brightness-[0.97] aria-[current=true]:outline-2 aria-[current=true]:outline-ink",
        platformBlock(row.platform)
      )}
    >
      <span className="text-sm leading-snug font-medium break-words">{row.title}</span>
      <span className="text-xs tabular-nums" title={row.window ?? undefined}>
        {span.text}
      </span>
      <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <PlatformMark platform={row.platform} />
        <span className="inline-flex items-center gap-1 text-xs">
          <TypeIcon type={detail.post_type} className="size-3.5" />
          {detail.post_type}
        </span>
      </span>
      <StatusChip status={row.status} className="min-h-6 gap-1 px-2 text-xs" />
      <PostBadges post={detail} />
    </button>
  )
}

/** A post as a card: the day list on a small screen, and the expanded "+N more" of the month. */
function Card({ entry: { item, span }, open, current, compact }: Common & { compact?: boolean }) {
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
        "press flex w-full flex-col items-start gap-1.5 rounded-control text-left shadow-card",
        "hover:brightness-[0.97] aria-[current=true]:outline-2 aria-[current=true]:outline-ink",
        compact ? "p-2" : "p-4",
        platformBlock(row.platform)
      )}
    >
      <span className="flex w-full min-w-0 items-baseline gap-2">
        <span className="shrink-0 text-xs tabular-nums">{span.from}</span>
        <span className={cn("min-w-0 font-medium", compact ? "truncate text-sm" : "text-base")}>
          {row.title}
        </span>
      </span>
      {!compact && (
        <span className="text-xs tabular-nums">
          {span.text} · {detail.post_type}
        </span>
      )}
      <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
        <PlatformMark platform={row.platform} />
        {compact && (
          <>
            <TypeIcon type={detail.post_type} className="size-3.5" />
            <span className="sr-only">{detail.post_type}</span>
          </>
        )}
      </span>
      <StatusChip status={row.status} className="min-h-6 gap-1 px-2 text-xs" />
      {!compact && <PostBadges post={detail} />}
    </button>
  )
}

function DayNumber({ day, today, light }: { day: string; today: boolean; light?: boolean }) {
  const n = parseDate(day)[2]
  return (
    <span className="inline-flex items-center gap-2">
      <span
        className={cn(
          "inline-flex size-8 items-center justify-center rounded-full text-lg tabular-nums",
          today ? "bg-pill text-pill-foreground" : light && "text-label"
        )}
      >
        {n}
      </span>
      {today && <span className="text-sm">Today</span>}
    </span>
  )
}

function WeekGrid({
  days,
  byDay,
  today,
  now,
  zone,
  open,
  post,
}: {
  days: string[]
  byDay: Map<string, Entry[]>
  today: string
  now: ReturnType<typeof useNow>
  zone: string | null
  open: ReturnType<typeof useOpenPost>
  post: string | null
}) {
  const scroller = React.useRef<HTMLDivElement>(null)
  const first = days.flatMap((d) => byDay.get(d) ?? []).map((e) => e.span.startMin)
  const firstHour = first.length ? Math.floor(Math.min(...first) / 60) : 8
  React.useEffect(() => {
    const box = scroller.current
    if (!box) return
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize)
    box.scrollTop = Math.max(0, firstHour * HOUR_REM * rem - 8)
  }, [firstHour, days])

  const template = "grid-cols-[3.5rem_repeat(7,minmax(9rem,1fr))]"
  const nowMin = now ? now.h * 60 + now.mi : 0
  const nowDay = now ? `${now.y}-${String(now.mo).padStart(2, "0")}-${String(now.d).padStart(2, "0")}` : ""
  return (
    <div
      ref={scroller}
      role="region"
      aria-label="Week calendar"
      tabIndex={0}
      className="card-surface relative max-h-[42rem] overflow-auto"
    >
      <div className="min-w-[66rem]">
        <div className={cn("sticky top-0 z-10 grid border-b border-hairline bg-surface", template)}>
          <div />
          {days.map((day) => (
            <div
              key={day}
              aria-current={day === today ? "date" : undefined}
              className="flex items-center gap-2 border-l border-hairline px-3 py-3"
            >
              <span className="w-9 text-sm text-label">{DAYS[dowOf(day)]}</span>
              <DayNumber day={day} today={day === today} />
            </div>
          ))}
        </div>
        <div className={cn("grid", template)}>
          <div className="hour-grid relative" aria-hidden="true">
            {Array.from({ length: 24 }, (_, h) => (
              <span
                key={h}
                className="absolute right-2 -translate-y-1/2 text-xs text-label tabular-nums"
                style={{ top: `calc(var(--hour) * ${h})`, display: h === 0 ? "none" : undefined }}
              >
                {String(h).padStart(2, "0")}:00
              </span>
            ))}
          </div>
          {days.map((day) => (
            <section
              key={day}
              aria-label={dayLabel(day)}
              data-day={day}
              className="hour-grid relative border-l border-hairline"
            >
              {place(byDay.get(day) ?? []).map((p) => (
                <Block
                  key={p.item.row.id}
                  entry={p}
                  lane={p.lane}
                  lanes={p.lanes}
                  open={open}
                  current={post === p.item.row.id}
                />
              ))}
              {now && day === nowDay && (
                <>
                  <span className="sr-only">Now: {clock(now)}</span>
                  <div
                    aria-hidden="true"
                    data-now={clock(now)}
                    className="pointer-events-none absolute inset-x-0 z-[5] h-px bg-ink"
                    style={{ top: `calc(var(--hour) * ${nowMin / 60})` }}
                  >
                    <span className="absolute -top-1 -left-1 size-2 rounded-full bg-ink" />
                  </div>
                </>
              )}
            </section>
          ))}
        </div>
      </div>
      <span className="sr-only">Times are shown in {zone ?? "the time each post carries"}.</span>
    </div>
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
  open: ReturnType<typeof useOpenPost>
  post: string | null
}) {
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set())
  return (
    <div
      role="region"
      aria-label="Month calendar"
      tabIndex={0}
      className="card-surface relative overflow-x-auto"
    >
      <div className="min-w-[70rem]">
      <div className="grid grid-cols-7 border-b border-hairline">
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
                "flex min-h-32 min-w-0 flex-col gap-1.5 border-t border-l border-hairline p-2 first:border-l-0 nth-[7n+1]:border-l-0",
                parseDate(day)[1] !== month && "bg-canvas"
              )}
            >
              <DayNumber day={day} today={day === today} light={parseDate(day)[1] !== month} />
              {shown.map((entry) => (
                <Card
                  key={entry.item.row.id}
                  entry={entry}
                  open={open}
                  current={post === entry.item.row.id}
                  compact
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
    </div>
  )
}

/** Below 768px the grid becomes a list of days, each with a sticky heading. */
function DayList({
  days,
  byDay,
  today,
  open,
  post,
  quietDays,
}: {
  days: string[]
  byDay: Map<string, Entry[]>
  today: string
  open: ReturnType<typeof useOpenPost>
  post: string | null
  quietDays: boolean
}) {
  return (
    <div className="flex flex-col gap-6">
      {days
        .filter((d) => quietDays || (byDay.get(d) ?? []).length)
        .map((day) => {
          const mine = byDay.get(day) ?? []
          return (
            <section key={day} aria-label={dayLabel(day)} data-day={day} className="flex flex-col gap-3">
              <h3
                aria-current={day === today ? "date" : undefined}
                className="sticky top-[calc(var(--shell-top)+4rem)] z-10 flex items-center gap-3 rounded-control bg-canvas px-4 py-2 text-base font-normal"
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
      <div className="grid grid-cols-7 gap-3">
        {Array.from({ length: 7 }, (_, i) => (
          <div key={i} className="flex flex-col gap-3">
            <Skeleton className="h-8 w-16" />
            <Skeleton className="h-24 w-full rounded-control" />
            {i % 2 === 0 && <Skeleton className="h-24 w-full rounded-control" />}
          </div>
        ))}
      </div>
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
  const wide = useMedia("(min-width: 768px)")
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

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-wrap items-end justify-between gap-x-10 gap-y-6">
        <div>
          <h1 className="text-4xl tracking-tight">
            <span className="sr-only">Calendar: </span>
            {rangeLabel(view, date)}
          </h1>
          <p className="mt-2 text-sm text-label">
            Times in {zone ?? "the zone each post carries"}
          </p>
        </div>
        <div className="flex flex-wrap gap-x-10 gap-y-4">
          <Figure value={visible.length} label={view === "week" ? "This week" : "This month"} />
          <Figure
            value={visible.filter(({ row }) => row.status === "pending_approval").length}
            label="Awaiting approval"
          />
          <Figure
            value={visible.filter(({ row }) => row.status === "published").length}
            label="Published"
          />
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          aria-label={`Previous ${unit}`}
          onClick={() => step(-1)}
          className="press inline-flex size-10 items-center justify-center rounded-full border border-control bg-surface hover:bg-muted"
        >
          <ChevronLeft aria-hidden="true" strokeWidth={1.5} className="size-5" />
        </button>
        <button
          type="button"
          onClick={() => set({ date: today })}
          className={cn(pillClass(inRange), "h-10")}
        >
          Today
        </button>
        <button
          type="button"
          aria-label={`Next ${unit}`}
          onClick={() => step(1)}
          className="press inline-flex size-10 items-center justify-center rounded-full border border-control bg-surface hover:bg-muted"
        >
          <ChevronRight aria-hidden="true" strokeWidth={1.5} className="size-5" />
        </button>
        <div role="group" aria-label="View" className="ml-auto flex rounded-full bg-muted p-1">
          {(["week", "month"] as const).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={view === v}
              onClick={() => set({ view: v, date })}
              className={cn(
                "press h-9 rounded-full px-5 text-sm",
                view === v ? "bg-pill text-pill-foreground" : "text-ink hover:bg-accent"
              )}
            >
              {v === "week" ? "Week" : "Month"}
            </button>
          ))}
        </div>
      </div>

      <FiltersBar closedByDefault />

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
      ) : !wide ? (
        <DayList
          days={days}
          byDay={byDay}
          today={today}
          open={open}
          post={post}
          quietDays={view === "week"}
        />
      ) : view === "week" ? (
        <WeekGrid
          days={days}
          byDay={byDay}
          today={today}
          now={inRange ? now : null}
          zone={zone}
          open={open}
          post={post}
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
  )
}

export function CalendarView() {
  return (
    <ViewGate label="Loading the calendar" rows={2}>
      {(schema) => <CalendarBody schema={schema} />}
    </ViewGate>
  )
}

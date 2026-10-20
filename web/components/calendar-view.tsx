"use client"

import { CalendarDays } from "lucide-react"
import * as React from "react"

import { useAppData } from "@/components/app-data"
import { CalendarToolbar } from "@/components/calendar-toolbar"
import { EmptyState } from "@/components/empty-state"
import { ErrorPanel } from "@/components/error-panel"
import { FilterStrip } from "@/components/filters-popover"
import { PlatformMark, platformBlock } from "@/components/platform-swatch"
import { PostBadges, TypeIcon, settleFocus, useOpenPost } from "@/components/post-bits"
import { StatusChip, statusLabel } from "@/components/status-chip"
import { Skeleton } from "@/components/ui/skeleton"
import { usePostItems } from "@/components/use-post-items"
import { useElementWidth } from "@/components/use-element-width"
import { ViewGate } from "@/components/view-gate"
import type { Schema } from "@/lib/api"
import {
  DAYS,
  addDays,
  clock,
  dateKey,
  dayLabel,
  dowOf,
  isDateKey,
  localParts,
  monthStart,
  parseDate,
  rangeFor,
  spanOf,
  todayKey,
  windowLabel,
  zoneOffset,
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

const COLUMNS_MIN = 880 // px of calendar box: from here seven day columns, below it day bands

type Entry = { item: PostItem; span: Span }

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

/** The tooltip of a post: its title and the whole window with the zone offset ("+03:00"). */
function windowTip(title: string, window: string | null, zone: string | null) {
  if (!window) return title
  const offset = zoneOffset(zone, new Date(window.split("/")[0]))
  return `${title}\n${windowLabel(window, zone)}${offset ? ` (${offset})` : ""}`
}

/** A post in a day stack or a month cell: time and platform, the title (two lines), the status. */
function StackCard({ entry: { item, span }, open, current, zone }: Common & { zone: string | null }) {
  const { row, detail } = item
  return (
    <button
      type="button"
      data-post-id={row.id}
      data-day={span.day}
      data-start={span.from}
      aria-current={current ? "true" : undefined}
      title={windowTip(row.title, row.window, zone)}
      onClick={(e) => open(row.id, e.currentTarget)}
      className={cn(
        "press flex w-full min-w-0 flex-col items-start gap-1.5 rounded-control p-2.5 text-left shadow-card @max-[8rem]:p-2",
        "hover:brightness-[0.97] aria-[current=true]:outline-2 aria-[current=true]:outline-ink",
        platformBlock(row.platform)
      )}
    >
      <span className="flex w-full min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-[0.8125rem] leading-snug">
        <span data-card-time className="font-medium tabular-nums">
          {span.from}
        </span>
        <PlatformMark platform={row.platform} bare />
        <TypeIcon type={detail.post_type} className="ml-auto size-3.5 @max-[10rem]:hidden" />
        <span className="sr-only">{detail.post_type}</span>
      </span>
      <span
        data-card-title
        className="line-clamp-2 min-w-0 text-sm leading-snug font-medium hyphens-auto wrap-anywhere @max-[8rem]:line-clamp-3"
      >
        {row.title}
      </span>
      <StatusChip status={row.status} className="min-h-7 gap-1 pr-2.5 pl-2 text-[0.8125rem]" />
      <PostBadges post={detail} compact />
    </button>
  )
}

/** A post as a full-width card in the day bands (the phone and any calendar box under 880 px). */
function Card({ entry: { item, span }, open, current }: Common) {
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
      <PlatformMark platform={row.platform} />
      <StatusChip status={row.status} className="min-h-6 gap-1 px-2 text-[0.8125rem]" />
      <PostBadges post={detail} />
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

/** The well of a day: tinted for today, a quiet canvas well for the others. */
const wellTone = (today: boolean) => (today ? "bg-muted" : "bg-canvas")

/** The thin "now" rule inside today's stack, between the posts before and after this minute. */
function NowRule({ now }: { now: NonNullable<ReturnType<typeof useNow>> }) {
  return (
    <>
      <span className="sr-only">Now: {clock(now)}</span>
      <div
        aria-hidden="true"
        data-now={clock(now)}
        className="pointer-events-none relative h-0.5 shrink-0 rounded-full bg-ink"
      >
        <span className="absolute -top-[3px] -left-1 size-2 rounded-full bg-ink" />
      </div>
    </>
  )
}

/** The week as seven time-ordered stacks: no hour axis, each post a card in its day's well. */
function WeekStacks({
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
  const nowMin = now ? now.h * 60 + now.mi : 0
  const nowDay = now ? dateKey(now) : ""
  return (
    <div
      role="region"
      aria-label="Week calendar"
      tabIndex={0}
      className="card-surface @container relative flex h-full scroll-pb-32 flex-col overflow-y-auto"
    >
      {/* One grid: the header cells (row 1) stick to the top while the stacks (row 2) scroll.
          Under 60 rem of calendar the gaps and well padding tighten by 2 px so a card keeps its width. */}
      <div
        data-week-stacks
        className="grid min-h-full flex-1 grid-cols-7 grid-rows-[auto_1fr] gap-x-2 px-2 pt-1.5 pb-2 @max-[60rem]:gap-x-1.5 @max-[60rem]:px-1.5"
      >
        {days.map((day) => (
          <div
            key={`head-${day}`}
            data-day-header={day}
            aria-hidden="true"
            className={cn("@container sticky top-0 z-10 rounded-t-inner", wellTone(day === today))}
          >
            <div className="flex h-12 items-center gap-2 px-3">
              <span data-weekday className="w-8 text-sm text-label">
                {DAYS[dowOf(day)]}
              </span>
              <span
                className={cn(
                  "inline-flex size-8 shrink-0 items-center justify-center rounded-full text-lg tabular-nums",
                  day === today && "bg-pill text-pill-foreground"
                )}
              >
                {parseDate(day)[2]}
              </span>
              {day === today && <span className="text-sm @max-[8.75rem]:hidden">Today</span>}
            </div>
          </div>
        ))}
        {days.map((day) => {
          const mine = byDay.get(day) ?? []
          const isToday = day === today
          // Today's rule goes before the first post that starts after this minute (or at the end).
          const next = mine.findIndex((e) => e.span.startMin > nowMin)
          const rule = now && day === nowDay ? (next === -1 ? mine.length : next) : -1
          return (
            <section
              key={day}
              aria-label={dayLabel(day)}
              aria-current={isToday ? "date" : undefined}
              data-day={day}
              className={cn(
                "@container flex min-w-0 flex-col gap-2 rounded-b-inner px-2 pb-2 @max-[60rem]:px-1.5",
                wellTone(isToday)
              )}
            >
              {mine.map((entry, i) => (
                <React.Fragment key={entry.item.row.id}>
                  {now && rule === i && <NowRule now={now} />}
                  <StackCard
                    entry={entry}
                    open={open}
                    current={post === entry.item.row.id}
                    zone={zone}
                  />
                </React.Fragment>
              ))}
              {now && rule === mine.length && <NowRule now={now} />}
              {mine.length === 0 && (
                <p className="px-1 py-2 text-[0.8125rem] text-label">Nothing planned</p>
              )}
            </section>
          )
        })}
      </div>
      <span className="sr-only">Times are shown in {zone ?? "the time each post carries"}.</span>
    </div>
  )
}

/** The month: the same wells and cards as the week, a row per week sized to what it holds
 *  (at least 96 px), so an empty week is a quiet line and a busy one grows. */
function MonthGrid({
  days,
  month,
  byDay,
  today,
  zone,
  open,
  post,
}: {
  days: string[]
  month: number
  byDay: Map<string, Entry[]>
  today: string
  zone: string | null
  open: ReturnType<typeof useOpenPost>
  post: string | null
}) {
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set())
  return (
    <div
      role="region"
      aria-label="Month calendar"
      tabIndex={0}
      className="card-surface relative h-full scroll-pb-32 overflow-y-auto px-2 pb-2"
    >
      <div className="sticky top-0 z-10 grid grid-cols-7 gap-x-2 bg-surface pt-1.5">
        {[...DAYS.slice(1), DAYS[0]].map((d) => (
          <div key={d} className="px-3 py-2 text-sm text-label">
            {d}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-2">
        {days.map((day) => {
          const mine = byDay.get(day) ?? []
          const all = expanded.has(day)
          const shown = all ? mine : mine.slice(0, 3)
          const outside = parseDate(day)[1] !== month
          return (
            <div
              key={day}
              role="group"
              aria-label={dayLabel(day)}
              aria-current={day === today ? "date" : undefined}
              data-day={day}
              className={cn(
                "@container flex min-h-24 min-w-0 flex-col gap-2 rounded-inner p-2",
                outside ? "inset-ring inset-ring-hairline" : wellTone(day === today)
              )}
            >
              <DayNumber day={day} today={day === today} light={outside} />
              {shown.map((entry) => (
                <StackCard
                  key={entry.item.row.id}
                  entry={entry}
                  open={open}
                  current={post === entry.item.row.id}
                  zone={zone}
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

/** Below 768px the grid becomes a list of days, each with a sticky heading. */
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
  open: ReturnType<typeof useOpenPost>
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
                // Cards flow in as many columns as the box allows: one on a phone, two or three
                // when a wide box (the sidebar open, the panel open) is still under 880 px.
                <div className="grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-3">
                  {mine.map((entry) => (
                    <Card
                      key={entry.item.row.id}
                      entry={entry}
                      open={open}
                      current={post === entry.item.row.id}
                    />
                  ))}
                </div>
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
  // Columns need room: the width of the calendar box itself, so the panel opening beside it
  // switches to day bands instead of scrolling sideways. Bands are the first paint (the safe layout).
  const [box, width] = useElementWidth<HTMLDivElement>()
  const columns = width !== null && width >= COLUMNS_MIN
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
          ) : !columns ? (
            <DayList
              days={days}
              byDay={byDay}
              today={today}
              open={open}
              post={post}
              quietDays={view === "week"}
              label={label}
            />
          ) : view === "week" ? (
            <WeekStacks
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
              zone={zone}
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

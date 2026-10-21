"use client"

import { PlatformMark, platformBlock } from "@/components/platform-swatch"
import { PostBadges, type useOpenPost } from "@/components/post-bits"
import { StatusChip } from "@/components/status-chip"
import { DAYS, clock, dayLabel, dowOf, parseDate, type Span } from "@/lib/time"
import type { PostItem } from "@/lib/url-state"
import { cn } from "@/lib/utils"

export type Entry = { item: PostItem; span: Span }
export type Open = ReturnType<typeof useOpenPost>

/** The numeral of a day: the black circle when it is today. */
export function DayNumber({ day, today, light }: { day: string; today: boolean; light?: boolean }) {
  const n = parseDate(day)[2]
  return (
    <span
      className={cn(
        "inline-flex size-8 items-center justify-center rounded-full text-lg tabular-nums",
        today ? "bg-pill text-pill-foreground" : light && "text-label"
      )}
    >
      {n}
    </span>
  )
}

/** A post as a card in a day band: time and platform, the title, then the status. The window with its
 *  offset is the tooltip; the fill is the platform's pastel, never an edge stripe. */
function BandCard({
  entry: { item, span },
  open,
  current,
}: {
  entry: Entry
  open: Open
  current: boolean
}) {
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
        // 168 px at least, grown to share the band, but never a slab: one post stays card-sized.
        "press flex min-w-0 flex-[1_1_10.5rem] flex-col items-start gap-1.5 rounded-control p-3 text-left shadow-card",
        "max-w-80 hover:brightness-[0.97] aria-[current=true]:outline-2 aria-[current=true]:outline-ink @max-[34rem]:max-w-none @max-[34rem]:basis-full",
        platformBlock(row.platform)
      )}
    >
      <span className="flex w-full min-w-0 items-center justify-between gap-2">
        <span className="shrink-0 text-[0.8125rem] tabular-nums">
          {span.from}
          <span className="sr-only"> to {span.to}</span>
        </span>
        <PlatformMark platform={row.platform} className="min-w-0" />
      </span>
      <span className="line-clamp-3 text-sm leading-snug font-medium break-words">{row.title}</span>
      <span className="flex flex-wrap items-center gap-1.5">
        <StatusChip status={row.status} className="min-h-6 gap-1 px-2 text-[0.8125rem]" />
        <PostBadges post={detail} compact />
      </span>
      <span className="sr-only">{detail.post_type}</span>
    </button>
  )
}

/** Days as bands: one row per day with the day on the left and its posts flowing beside it. The same
 *  component serves the week at any width and the phone list (the band stacks under 34 rem of its
 *  own width, with a sticky heading). */
export function DayBands({
  days,
  byDay,
  today,
  now,
  open,
  post,
  quietDays,
  label,
  zone,
}: {
  days: string[]
  byDay: Map<string, Entry[]>
  today: string
  /** The time now, when today is in range: shown in today's label as a marker. */
  now: { h: number; mi: number; y: number; mo: number; d: number } | null
  open: Open
  post: string | null
  quietDays: boolean
  label: string
  zone: string | null
}) {
  const nowDay = now ? `${now.y}-${String(now.mo).padStart(2, "0")}-${String(now.d).padStart(2, "0")}` : ""
  return (
    <div
      role="region"
      aria-label={label}
      tabIndex={0}
      className="@container flex h-full scroll-pb-32 flex-col gap-2 overflow-y-auto"
    >
      {days
        .filter((d) => quietDays || (byDay.get(d) ?? []).length)
        .map((day) => {
          const mine = byDay.get(day) ?? []
          const isToday = day === today
          return (
            <section
              key={day}
              aria-label={dayLabel(day)}
              data-day={day}
              className={cn(
                "grid shrink-0 grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 gap-y-2 rounded-inner p-2 shadow-card @max-[34rem]:grid-cols-1",
                isToday ? "bg-muted" : "bg-surface"
              )}
            >
              <h3
                aria-current={isToday ? "date" : undefined}
                className={cn(
                  "flex px-2 py-1 text-base font-normal @max-[34rem]:sticky @max-[34rem]:top-0 @max-[34rem]:z-10",
                  "@max-[34rem]:flex-row @max-[34rem]:items-center @max-[34rem]:gap-3 @max-[34rem]:py-0",
                  // An empty day is one line: the weekday and the numeral side by side.
                  mine.length ? "flex-col items-start gap-0.5" : "flex-wrap items-center gap-x-2"
                )}
              >
                <span className="text-sm text-label">{DAYS[dowOf(day)]}</span>
                <span className="inline-flex items-center gap-2">
                  <span
                    className={cn(
                      "inline-flex size-9 items-center justify-center rounded-full text-2xl font-light tabular-nums @max-[34rem]:size-8 @max-[34rem]:text-lg @max-[34rem]:font-normal",
                      isToday && "bg-pill text-pill-foreground"
                    )}
                  >
                    {parseDate(day)[2]}
                  </span>
                  {isToday && <span className="text-sm">Today</span>}
                </span>
                {now && day === nowDay && (
                  <>
                    <span className="sr-only">Now: {clock(now)}</span>
                    <span aria-hidden="true" data-now={clock(now)} className="text-[0.8125rem] text-label tabular-nums">
                      Now {clock(now)}
                    </span>
                  </>
                )}
              </h3>
              {mine.length ? (
                <div className="flex min-w-0 flex-wrap content-start gap-2">
                  {mine.map((entry) => (
                    <BandCard key={entry.item.row.id} entry={entry} open={open} current={post === entry.item.row.id} />
                  ))}
                </div>
              ) : (
                <p className="flex min-h-10 items-center px-2 text-sm text-label @max-[34rem]:min-h-0">Nothing planned.</p>
              )}
            </section>
          )
        })}
      <span className="sr-only">Times are shown in {zone ?? "the time each post carries"}.</span>
    </div>
  )
}

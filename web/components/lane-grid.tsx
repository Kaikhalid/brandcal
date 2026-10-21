"use client"

import { X } from "lucide-react"
import * as React from "react"

import { DayNumber, PostCard, type Entry, type Open } from "@/components/calendar-bits"
import { PlatformDot, platformLabel } from "@/components/platform-swatch"
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "@/components/ui/popover"
import { DAYS, dayLabel, dowOf } from "@/lib/time"
import { cn } from "@/lib/utils"

const SHOWN = 2 // cards a cell shows before "+n more"

// A narrow label column under 1100 px of content, a roomier one above. The container is the shell
// column (an open panel narrows it), so these are container queries, not window ones.
const TEMPLATE = "grid-cols-[6rem_repeat(7,minmax(0,1fr))] @min-[1100px]:grid-cols-[7.5rem_repeat(7,minmax(0,1fr))]"

const posts = (n: number) => `${n} ${n === 1 ? "post" : "posts"}`

/** The lane's label is the channel filter: pressed means this channel is shown (the others fold). */
function LaneLabel({
  platform,
  count,
  pressed,
  onToggle,
}: {
  platform: string
  count: number
  pressed: boolean
  onToggle: () => void
}) {
  const label = platformLabel(platform)
  return (
    <button
      type="button"
      data-lane-toggle={platform}
      aria-pressed={pressed}
      title={`Show only ${label}`}
      onClick={onToggle}
      className="press group flex min-h-10 w-full min-w-0 flex-col items-start justify-center gap-0.5 rounded-control px-2 py-2 text-left hover:bg-surface aria-pressed:bg-pill aria-pressed:text-pill-foreground aria-pressed:hover:bg-pill @min-[1100px]:px-2.5"
    >
      <span className="flex min-w-0 max-w-full items-center gap-2 text-sm font-medium">
        <PlatformDot
          platform={platform}
          className="hidden group-aria-pressed:ring-1 group-aria-pressed:ring-pill-foreground @min-[1100px]:inline-block"
        />
        <span className="sr-only">Show only </span>
        <span className="min-w-0 truncate">{label}</span>
      </span>
      <span className="text-[0.8125rem] tabular-nums text-label group-aria-pressed:text-pill-foreground">
        {posts(count)}
      </span>
    </button>
  )
}

/** More than two posts in a cell: the rest are one press away, in a small list. */
function MoreCell({
  platform,
  day,
  entries,
  open,
  post,
}: {
  platform: string
  day: string
  entries: Entry[]
  open: Open
  post: string | null
}) {
  const [shown, setShown] = React.useState(false)
  const trigger = React.useRef<HTMLButtonElement>(null)
  return (
    <Popover open={shown} onOpenChange={setShown}>
      <PopoverTrigger
        ref={trigger}
        data-more-cell
        className="press inline-flex min-h-6 items-center self-start rounded-full px-2 text-[0.8125rem] text-label underline underline-offset-4 hover:text-ink"
      >
        +{entries.length} more
        <span className="sr-only">
          {" "}
          {platformLabel(platform)} {entries.length === 1 ? "post" : "posts"} on {dayLabel(day)}
        </span>
      </PopoverTrigger>
      <PopoverContent align="start" className="flex w-72 flex-col gap-2 p-3">
        <PopoverTitle className="px-1 text-sm">
          {platformLabel(platform)} · {dayLabel(day)}
        </PopoverTitle>
        <ul className="flex flex-col gap-2">
          {entries.map((entry) => (
            <li key={entry.item.row.id}>
              <PostCard
                entry={entry}
                current={post === entry.item.row.id}
                from={trigger}
                open={(id, from) => {
                  setShown(false)
                  open(id, from)
                }}
              />
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  )
}

/** The chip pair the strip shows while channels are filtered: what is on, one press to remove it,
 *  and "Show all". Plain buttons, so it sits inside the strip's summary line. */
export function LaneShowing({
  selected,
  remove,
  clear,
}: {
  selected: string[]
  remove: (platform: string) => void
  clear: () => void
}) {
  if (selected.length === 0) return null
  return (
    <>
      {" · Showing: "}
      <span className="inline-flex flex-wrap items-center gap-1.5 align-middle">
        {selected.map((p) => (
          <button
            key={p}
            type="button"
            data-filter-chip={`platform:${p}`}
            aria-label={`Remove filter: ${platformLabel(p)}`}
            onClick={() => remove(p)}
            className="press inline-flex h-6 items-center gap-1 rounded-full bg-muted pr-1.5 pl-2.5 text-[0.8125rem] text-ink hover:bg-accent"
          >
            {platformLabel(p)}
            <X aria-hidden="true" strokeWidth={1.5} className="size-3.5" />
          </button>
        ))}
        <button
          type="button"
          data-show-all-lanes
          onClick={clear}
          className="min-h-6 rounded-control px-1 text-[0.8125rem] underline underline-offset-4 hover:text-ink"
        >
          Show all
        </button>
      </span>
    </>
  )
}

/** The week by channel: a row per platform, a column per day. The label of each lane filters the
 *  calendar to that channel; the others fold to a one-line row so they stay one press away. A gap in
 *  a lane (a dash) is the signal this layout exists for. Posts arrive unfiltered by channel so every
 *  lane can print its own count. */
export function LaneGrid({
  days,
  entries,
  platforms,
  selected,
  today,
  open,
  post,
  zone,
  toggle,
}: {
  days: string[]
  entries: Entry[]
  platforms: string[]
  selected: string[]
  today: string
  open: Open
  post: string | null
  zone: string | null
  toggle: (platform: string) => void
}) {
  const cells = React.useMemo(() => {
    const map = new Map<string, Entry[]>()
    for (const entry of entries) {
      const key = `${entry.item.row.platform}|${entry.span.day}`
      map.set(key, [...(map.get(key) ?? []), entry])
    }
    return map
  }, [entries])
  const total = (p: string) => entries.filter((e) => e.item.row.platform === p).length

  return (
    <div
      role="region"
      aria-label="Week calendar"
      tabIndex={0}
      data-lane-grid
      className="card-surface relative h-full scroll-pb-32 overflow-y-auto p-2 pt-0"
    >
      <div
        role="table"
        aria-label="Posts by channel and day"
        className="flex min-h-full min-w-0 flex-col gap-2"
      >
        <div role="row" className={cn("sticky top-0 z-10 grid bg-surface pt-1", TEMPLATE)}>
          <div role="columnheader" className="flex items-center px-2.5 text-[0.8125rem] text-label">
            Channel
          </div>
          {days.map((day) => (
            <div
              key={day}
              role="columnheader"
              data-day={day}
              aria-current={day === today ? "date" : undefined}
              className="flex min-h-12 min-w-0 items-center gap-1.5 px-2 @min-[1100px]:gap-2 @min-[1100px]:px-3"
            >
              <span className="text-sm text-label">{DAYS[dowOf(day)]}</span>
              <DayNumber day={day} today={day === today} word="wide" />
            </div>
          ))}
        </div>
        {platforms.map((platform) => {
          const on = selected.includes(platform)
          const folded = selected.length > 0 && !on
          const count = total(platform)
          return (
            <div
              key={platform}
              role="row"
              data-lane={platform}
              data-folded={folded ? "" : undefined}
              className={cn("grid rounded-inner bg-muted/60", selected.length === 0 && "flex-1", TEMPLATE)}
            >
              <div role="rowheader" className="p-1.5">
                <LaneLabel platform={platform} count={count} pressed={on} onToggle={() => toggle(platform)} />
              </div>
              {folded ? (
                <div
                  role="cell"
                  className="col-span-7 flex items-center px-3 text-[0.8125rem] text-label"
                >
                  {count === 0 ? "No posts this week" : "Hidden: press the channel name to add it"}
                </div>
              ) : (
                days.map((day) => {
                  const mine = cells.get(`${platform}|${day}`) ?? []
                  const more = mine.length > SHOWN ? mine.slice(SHOWN) : []
                  return (
                    <div
                      key={day}
                      role="cell"
                      data-day={day}
                      className={cn(
                        "flex min-h-24 min-w-0 flex-col gap-1.5 border-l border-hairline p-1 @min-[1100px]:min-h-[6.5rem] @min-[1100px]:p-1.5",
                        day === today && "bg-surface/70"
                      )}
                    >
                      {mine.length === 0 && (
                        <span aria-hidden="true" className="m-auto h-px w-4 bg-label/40" />
                      )}
                      {mine.slice(0, more.length ? SHOWN : mine.length).map((entry) => (
                        <PostCard
                          key={entry.item.row.id}
                          entry={entry}
                          open={open}
                          current={post === entry.item.row.id}
                        />
                      ))}
                      {more.length > 0 && (
                        <MoreCell platform={platform} day={day} entries={more} open={open} post={post} />
                      )}
                    </div>
                  )
                })
              )}
            </div>
          )
        })}
      </div>
      <span className="sr-only">Times are shown in {zone ?? "the time each post carries"}.</span>
    </div>
  )
}

"use client"

import type * as React from "react"

import { PlatformMark, platformBlock, platformLabel } from "@/components/platform-swatch"
import { PostBadges, TypeIcon, type useOpenPost } from "@/components/post-bits"
import { StatusChip } from "@/components/status-chip"
import { parseDate, type Span } from "@/lib/time"
import type { PostItem } from "@/lib/url-state"
import { cn } from "@/lib/utils"

export type Entry = { item: PostItem; span: Span }
export type Open = ReturnType<typeof useOpenPost>

/** The day number; today's is the ink circle. `word` decides when the word "Today" is drawn: always
 *  (day list, month), or only where there is room (the lane headers, which print it from 1100 px). */
export function DayNumber({
  day,
  today,
  light,
  word = "always",
}: {
  day: string
  today: boolean
  light?: boolean
  word?: "always" | "wide"
}) {
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
      {today && (
        <span className={cn("text-sm", word === "wide" && "sr-only @min-[1100px]:not-sr-only")}>
          Today
        </span>
      )}
    </span>
  )
}

/** A post as a pastel card in a lane cell, in the month grid and in the "+n more" list. Row 1 is the
 *  time and the type, row 2 the title (two lines), then the status chip. In a lane the platform is the
 *  row's label, so the card prints it for assistive technology only; elsewhere it is printed. */
export function PostCard({
  entry: { item, span },
  open,
  current,
  showPlatform,
  from,
}: {
  entry: Entry
  open: Open
  current: boolean
  showPlatform?: boolean
  /** The element that gets focus back when the panel closes (a card in a popover is gone by then). */
  from?: React.RefObject<HTMLElement | null>
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
      onClick={(e) => open(row.id, from?.current ?? e.currentTarget)}
      className={cn(
        "press flex w-full min-w-0 flex-col items-start gap-1 rounded-control p-1.5 text-left shadow-card @min-[1100px]:p-2",
        "hover:brightness-[0.97] aria-[current=true]:outline-2 aria-[current=true]:outline-ink",
        platformBlock(row.platform)
      )}
    >
      <span className="flex w-full min-w-0 items-center gap-1.5 text-[0.8125rem] tabular-nums">
        {span.from}
        <TypeIcon type={detail.post_type} className="size-3.5" />
        <span className="min-w-0 truncate @max-[1300px]:sr-only">{detail.post_type}</span>
      </span>
      {showPlatform ? (
        <PlatformMark platform={row.platform} className="max-w-full" />
      ) : (
        <span data-platform={row.platform} className="sr-only">
          {platformLabel(row.platform)}
        </span>
      )}
      <span className="line-clamp-2 text-sm leading-snug font-medium [overflow-wrap:anywhere]">{row.title}</span>
      <StatusChip status={row.status} className="min-h-6 gap-1 px-1.5 py-0.5 @min-[1100px]:px-2" />
      <PostBadges post={detail} compact />
    </button>
  )
}

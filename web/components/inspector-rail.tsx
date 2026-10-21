"use client"

import { Clock, Inbox, X } from "lucide-react"
import { usePathname } from "next/navigation"
import * as React from "react"

import { useAppData } from "@/components/app-data"
import { ErrorPanel } from "@/components/error-panel"
import { useNeedsQueue } from "@/components/needs-queue"
import { PlatformDot, platformLabel } from "@/components/platform-swatch"
import { rememberOpener, useOpenPost } from "@/components/post-bits"
import { isTyping, useShortcuts } from "@/components/shortcuts"
import { StatusChip } from "@/components/status-chip"
import { Skeleton } from "@/components/ui/skeleton"
import { useMedia } from "@/components/use-media"
import type { PostRow, Schema } from "@/lib/api"
import { isCurrent } from "@/lib/nav"
import { dayLabel, spanOf } from "@/lib/time"
import { useUrlState } from "@/lib/url-state"
import { cn } from "@/lib/utils"

/** From this viewport width the rail sits beside the calendar; below it the rail is a sheet. */
export const RAIL_MIN = 1180

/** Where the post panel and the queue go: on the calendar the rail is a permanent column from 1180 px. */
export function useRail() {
  const onCalendar = isCurrent("/", usePathname())
  const wide = useMedia(`(min-width: ${RAIL_MIN}px)`)
  const wider = useMedia("(min-width: 1200px)")
  return { onCalendar, beside: onCalendar ? wide : wider }
}

/** The frame both rail states share: a column beside the calendar (22 rem, 26 rem from 1440 px),
 *  or a sheet over it. `scroll-pb-32` keeps a focused control clear of the notice card (2.4.11). */
export const railFrame = (beside: boolean) =>
  cn(
    "glass scroll-pb-32 overflow-y-auto overscroll-contain",
    beside
      ? "sticky top-(--shell-top) z-10 h-[calc(100svh-var(--shell-top))] w-[22rem] shrink-0 self-start border-l border-hairline min-[1440px]:w-[26rem]"
      : "fixed top-(--shell-top) right-0 bottom-0 z-40 w-[min(34rem,100vw)]"
  )

function time(row: PostRow, schema: Schema) {
  const span = row.window ? spanOf(row.window, schema.timezone) : null
  return span ? `${dayLabel(span.day)} · ${span.from}` : null
}

function Row({ row, schema, current }: { row: PostRow; schema: Schema; current: boolean }) {
  const open = useOpenPost()
  return (
    <li>
      <button
        type="button"
        data-queue-row
        data-post-id={row.id}
        aria-current={current ? "true" : undefined}
        title={row.window ?? undefined}
        onClick={(e) => open(row.id, e.currentTarget)}
        className="press flex min-h-14 w-full flex-col items-start gap-1 rounded-control px-3 py-2.5 text-left hover:bg-muted aria-[current=true]:bg-muted aria-[current=true]:outline-2 aria-[current=true]:outline-ink"
      >
        <span className="flex w-full items-center gap-2 text-[0.8125rem] text-label">
          <PlatformDot platform={row.platform} />
          <span className="min-w-0 truncate">{platformLabel(row.platform)}</span>
          <span className="ml-auto shrink-0 tabular-nums">{time(row, schema)}</span>
        </span>
        <span className="line-clamp-2 text-sm leading-snug font-medium">{row.title}</span>
      </button>
    </li>
  )
}

/** `j` and `k` walk the queue rows (Enter, a button's own key, opens one). Never while typing, and
 *  never when single-key shortcuts are off (WCAG 2.1.4). */
function useQueueKeys(root: React.RefObject<HTMLElement | null>) {
  const { enabled } = useShortcuts()
  React.useEffect(() => {
    if (!enabled) return
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return
      if (e.key !== "j" && e.key !== "k") return
      const rows = [...(root.current?.querySelectorAll<HTMLElement>("[data-queue-row]") ?? [])]
      if (!rows.length) return
      const at = rows.indexOf(document.activeElement as HTMLElement)
      const next = e.key === "j" ? (at < 0 ? 0 : Math.min(at + 1, rows.length - 1)) : Math.max(at - 1, 0)
      e.preventDefault()
      rows[next]?.focus()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [enabled, root])
}

/** The queue state of the rail: Needs you, most urgent first. */
export function QueueRail({ beside }: { beside: boolean }) {
  const { schema } = useAppData()
  const { state, groups, total } = useNeedsQueue()
  const { params, set } = useUrlState()
  const current = params.get("post")
  const root = React.useRef<HTMLElement>(null)
  const heading = React.useRef<HTMLHeadingElement>(null)
  useQueueKeys(root)

  const close = React.useCallback(() => {
    set({ queue: null })
    // The page behind is inert while the sheet is open; lift that so focus can go back to the button.
    const behind = document.getElementById("shell-body")
    if (behind) behind.inert = false
    document.querySelector<HTMLElement>("[data-rail-button]")?.focus()
  }, [set])

  // The sheet takes focus when it opens; Esc closes it unless a popover or menu is open above it.
  React.useEffect(() => {
    if (!beside) heading.current?.focus({ preventScroll: true })
  }, [beside])
  React.useEffect(() => {
    if (beside) return
    const onKey = (e: KeyboardEvent) => {
      const floating = document.querySelector(
        "[data-slot='popover-content'][data-open], [data-slot='dropdown-menu-content'][data-open]"
      )
      if (e.key === "Escape" && !e.defaultPrevented && !floating) close()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [beside, close])

  return (
    <aside
      ref={root}
      aria-labelledby="rail-title"
      data-inspector-rail="queue"
      className={railFrame(beside)}
    >
      <div className="flex flex-col gap-6 p-4 pb-32">
        <div className="flex items-center justify-between gap-3 pt-1 pl-1">
          <h2
            id="rail-title"
            ref={heading}
            tabIndex={-1}
            className="flex items-baseline gap-3 text-2xl leading-tight font-light tracking-tight outline-none"
          >
            Needs you
            {total !== null && (
              <span data-queue-count className="text-lg text-label tabular-nums">
                {total}
                <span className="sr-only"> waiting</span>
              </span>
            )}
          </h2>
          {!beside && (
            <button
              type="button"
              onClick={close}
              aria-label="Close Needs you"
              className="press inline-flex size-10 shrink-0 items-center justify-center rounded-full border border-control bg-surface hover:bg-muted"
            >
              <X aria-hidden="true" strokeWidth={1.5} className="size-5" />
            </button>
          )}
        </div>
        {state.state === "loading" || schema.state !== "ok" ? (
          <div role="status" aria-busy="true" aria-label="Loading what needs you" className="flex flex-col gap-3">
            <Skeleton className="h-5 w-1/2" />
            <Skeleton className="h-14 w-full rounded-control" />
            <Skeleton className="h-14 w-full rounded-control" />
          </div>
        ) : state.state === "error" ? (
          <ErrorPanel error={state.refusal} />
        ) : total === 0 ? (
          <div className="flex flex-col items-start gap-2 rounded-inner bg-muted p-4 text-sm">
            <Inbox aria-hidden="true" strokeWidth={1.5} className="size-5 text-label" />
            <p className="text-base font-medium">All clear.</p>
            <p className="text-label">Nothing is waiting for you. Agents submit posts through the CLI:</p>
            <code className="font-mono text-[0.8125rem] break-all">brandcal submit POST_ID --as NAME</code>
          </div>
        ) : (
          groups
            .filter((g) => g.posts.length)
            .map(({ status, posts }) => (
              <section
                key={status}
                data-status={status}
                aria-labelledby={`queue-${status}`}
                className="flex flex-col gap-1"
              >
                <h3 id={`queue-${status}`} className="flex items-center gap-2 pl-1 text-sm font-normal">
                  <StatusChip status={status} />
                  <span className="text-label tabular-nums">
                    {posts.length}
                    <span className="sr-only"> {posts.length === 1 ? "post" : "posts"}</span>
                  </span>
                </h3>
                <ul className="flex flex-col">
                  {posts.map((row) => (
                    <Row key={row.id} row={row} schema={schema.data} current={current === row.id} />
                  ))}
                </ul>
              </section>
            ))
        )}
        {beside && total ? (
          <p className="pl-1 text-[0.8125rem] text-label">
            Press <kbd className="font-mono">j</kbd> or <kbd className="font-mono">k</kbd> to move through the queue,
            Enter to open a post.
          </p>
        ) : null}
      </div>
    </aside>
  )
}

/** The toolbar's Needs you button below 1180 px, where the rail is a sheet: the amber chip with
 *  the count; it opens the queue (`?queue=1`). */
export function RailButton() {
  const { total } = useNeedsQueue()
  const { params, set } = useUrlState()
  const on = params.get("queue") === "1"
  return (
    <button
      type="button"
      data-rail-button
      aria-expanded={on}
      onClick={(e) => {
        rememberOpener(e.currentTarget)
        set({ queue: on ? null : "1", post: null })
      }}
      className="press inline-flex h-10 items-center gap-2 rounded-full bg-st-awaiting px-4 text-sm whitespace-nowrap text-st-awaiting-ink hover:brightness-[0.97] aria-expanded:ring-2 aria-expanded:ring-ink @max-[1100px]:px-3"
    >
      <Clock aria-hidden="true" strokeWidth={1.5} className="size-4 shrink-0" />
      <span className="@max-[1100px]:sr-only">Needs you</span>
      {total !== null && total > 0 && (
        <span className="tabular-nums">
          {total}
          <span className="sr-only"> waiting</span>
        </span>
      )}
    </button>
  )
}

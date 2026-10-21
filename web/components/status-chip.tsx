"use client"

import {
  CalendarClock,
  Check,
  CircleDashed,
  Clock,
  Globe,
  Pencil,
  TriangleAlert,
  X,
  type LucideIcon,
} from "lucide-react"

import { useAppData } from "@/components/app-data"
import { cn } from "@/lib/utils"

// Status is always an icon and a word, never colour alone (docs/UI_STYLE.md). Chips are keyed by
// the server's status ids (GET /api/schema `states`); the five style names of UI_STYLE section 2
// (draft, awaiting, scheduled, published, failed) are accepted too. An id this file does not
// know still gets a chip: a neutral one that prints the id in words.
type Look = { label: string; Icon: LucideIcon; tone: string }

const DRAFT = "bg-st-draft text-st-draft-ink"
const AWAITING = "bg-st-awaiting text-st-awaiting-ink"
const SCHEDULED = "bg-st-scheduled text-st-scheduled-ink"
// A solid fill, so Published is clearly distinct from the ink pill and every pastel.
const PUBLISHED = "bg-st-published text-st-published-ink"
const FAILED = "bg-st-failed text-st-failed-ink"

const draft: Look = { label: "Draft", Icon: Pencil, tone: DRAFT }
const awaiting: Look = { label: "Awaiting you", Icon: Clock, tone: AWAITING }
const scheduled: Look = { label: "Scheduled", Icon: CalendarClock, tone: SCHEDULED }
const published: Look = { label: "Published", Icon: Globe, tone: PUBLISHED }
const failed: Look = { label: "Failed", Icon: TriangleAlert, tone: FAILED }

const STATUS: Record<string, Look> = {
  draft,
  awaiting,
  scheduled,
  published,
  failed,
  pending_approval: awaiting,
  changes_requested: { label: "Changes requested", Icon: Pencil, tone: DRAFT },
  // UI_SPEC 5.2 shapes: clock, pencil, check, triangle-alert, globe, x.
  approved: { ...scheduled, Icon: Check },
  missed: { label: "Missed", Icon: TriangleAlert, tone: FAILED },
  cancelled: { label: "Cancelled", Icon: X, tone: DRAFT },
}

/** "some_status" -> "Some status" for an id with no entry above. */
function humanise(id: string): string {
  const words = id.replace(/[_-]+/g, " ").trim()
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Unknown"
}

function lookFor(status: string): Look {
  return STATUS[status] ?? { label: humanise(status), Icon: CircleDashed, tone: DRAFT }
}

/** The word a chip prints for a status id. A post awaiting approval says "Awaiting you" only to
 *  the approver, who is the one who must act; everyone else reads "Awaiting approval". */
export function statusLabel(status: string, role?: string | null): string {
  if (status === "pending_approval" && role !== "approver") return "Awaiting approval"
  return lookFor(status).label
}

/** The five styles of UI_STYLE, for galleries. */
export const STATUS_STYLES = ["draft", "awaiting", "scheduled", "published", "failed"] as const

function StatusChip({
  status,
  className,
  iconOnly,
}: {
  status: string
  className?: string
  /** For a cell too narrow for the word (the month map): the icon in its fill, the word kept for
   *  readers and in the tooltip. */
  iconOnly?: boolean
}) {
  const { session } = useAppData()
  const { Icon, tone } = lookFor(status)
  const label = statusLabel(status, session.state === "ok" ? session.data.role : null)
  if (iconOnly) {
    return (
      <span
        data-status={status}
        title={label}
        className={cn("inline-flex size-6 shrink-0 items-center justify-center rounded-full", tone, className)}
      >
        <Icon aria-hidden="true" strokeWidth={1.5} className="size-4" />
        <span className="sr-only">{label}</span>
      </span>
    )
  }
  return (
    <span
      data-status={status}
      title={status}
      className={cn(
        // min-h, not h, and no nowrap: wider text spacing wraps the word instead of spilling out.
        "inline-flex min-h-7 max-w-full items-center gap-1.5 rounded-full py-1 pr-3 pl-2.5 text-[0.8125rem] leading-tight",
        tone,
        className
      )}
    >
      <Icon aria-hidden="true" strokeWidth={1.5} className="size-4 shrink-0" />
      {label}
    </span>
  )
}

export { StatusChip }

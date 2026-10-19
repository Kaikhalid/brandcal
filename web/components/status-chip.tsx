import { CalendarClock, CircleCheck, Clock, Pencil, TriangleAlert } from "lucide-react"

import { cn } from "@/lib/utils"

// Status is always an icon and a word, never colour alone (docs/UI_STYLE.md).
const STATUS = {
  draft: { label: "Draft", Icon: Pencil, tone: "bg-st-draft text-st-draft-ink" },
  awaiting: { label: "Awaiting you", Icon: Clock, tone: "bg-st-awaiting text-st-awaiting-ink" },
  scheduled: {
    label: "Scheduled",
    Icon: CalendarClock,
    tone: "bg-st-scheduled text-st-scheduled-ink",
  },
  // A solid fill, so Published is clearly distinct from the ink pill and every pastel.
  published: {
    label: "Published",
    Icon: CircleCheck,
    tone: "bg-st-published text-st-published-ink",
  },
  failed: { label: "Failed", Icon: TriangleAlert, tone: "bg-st-failed text-st-failed-ink" },
} as const

export type Status = keyof typeof STATUS
export const STATUSES = Object.keys(STATUS) as Status[]

function StatusChip({ status, className }: { status: Status; className?: string }) {
  const { label, Icon, tone } = STATUS[status]
  return (
    <span
      data-status={status}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-full pr-3 pl-2.5 text-[0.8125rem] leading-none",
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

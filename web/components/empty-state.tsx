import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

// Nothing to show yet: an icon, one line, and the agent command that would create the data.
// Data comes from agents through the CLI (UI_SPEC 1.2), so this is where the UI points them.
function EmptyState({
  icon: Icon,
  line,
  command,
  className,
}: {
  icon: LucideIcon
  line: string
  command: string
  className?: string
}) {
  return (
    <div className={cn("card-surface flex flex-col items-center gap-4 px-6 py-16 text-center", className)}>
      <span className="flex size-12 items-center justify-center rounded-full bg-muted text-ink">
        <Icon aria-hidden="true" strokeWidth={1.5} className="size-6" />
      </span>
      <p className="max-w-prose">{line}</p>
      <code className="max-w-full rounded-control bg-muted px-3 py-2 font-mono text-[0.8125rem] break-words">
        {command}
      </code>
    </div>
  )
}

export { EmptyState }

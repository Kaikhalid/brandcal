import { TriangleAlert } from "lucide-react"

import type { ErrorBody } from "@/lib/api"
import { cn } from "@/lib/utils"

// A refusal, in the CLI's words and nothing else (UI_SPEC 1.3): the code in monospace, the
// message, then "What to do:" and `next`, verbatim. `blocking` errors are announced at once
// (role="alert"); a non-blocking one, such as a disabled button's reason, is plain text.
function ErrorPanel({
  error,
  blocking = true,
  className,
}: {
  error: ErrorBody
  blocking?: boolean
  className?: string
}) {
  return (
    <div
      role={blocking ? "alert" : undefined}
      data-error-code={error.code}
      className={cn("card-surface flex gap-4 p-5", className)}
    >
      <TriangleAlert
        aria-hidden="true"
        strokeWidth={1.5}
        className="mt-0.5 size-5 shrink-0 text-destructive"
      />
      <div className="min-w-0">
        <p className="font-mono text-sm break-words text-destructive">{error.code}</p>
        <p className="mt-1">{error.message}</p>
        <p className="mt-2 text-sm text-label">
          <strong className="font-medium text-ink">What to do:</strong> {error.next}
        </p>
      </div>
    </div>
  )
}

export { ErrorPanel }

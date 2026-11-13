import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

// Page loads show the shape of what is coming (never a spinner). aria-busy tells assistive
// technology the region is still filling in; the label says what for.
function LoadingState({
  label = "Loading",
  rows = 3,
  className,
}: {
  label?: string
  rows?: number
  className?: string
}) {
  return (
    <div
      aria-busy="true"
      role="status"
      aria-label={label}
      className={cn("flex flex-col gap-3", className)}
    >
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="card-surface flex items-center gap-4 p-5">
          <Skeleton className="size-10 shrink-0 rounded-full" />
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <Skeleton className="h-4 w-2/5" />
            <Skeleton className="h-4 w-4/5" />
          </div>
          <Skeleton className="hidden h-7 w-24 rounded-full sm:block" />
        </div>
      ))}
    </div>
  )
}

export { LoadingState }

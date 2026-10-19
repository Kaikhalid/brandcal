"use client"

import { UserRound } from "lucide-react"

import { useAppData } from "@/components/app-data"
import { ThemeSwitcher } from "@/components/theme-switcher"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

function initialOf(identity: string | null): string | null {
  const first = identity?.trim().charAt(0)
  return first ? first.toUpperCase() : null
}

function Avatar({ initial }: { initial: string | null }) {
  return (
    <span
      aria-hidden="true"
      className="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted text-sm text-ink"
    >
      {initial ?? <UserRound strokeWidth={1.5} className="size-5" />}
    </span>
  )
}

// Who the server thinks is asking (GET /api/session): identity, role and where the identity came
// from. In the rail it is an avatar with a tooltip; the theme switcher sits under it.
function IdentityFooter() {
  const { session } = useAppData()

  if (session.state === "loading") {
    return (
      <div aria-busy="true" className="flex items-center gap-3 p-1">
        <Skeleton className="size-10 shrink-0 rounded-full" />
        <div className="flex flex-1 flex-col gap-2 group-data-[collapsible=icon]:hidden">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      </div>
    )
  }

  const ok = session.state === "ok"
  const who = ok ? (session.data.identity ?? "Unverified") : "Not signed in"
  const detail = ok ? `${session.data.role} · ${session.data.source}` : session.refusal.code
  const summary = `${who}, ${detail}`

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3 p-1 group-data-[collapsible=icon]:hidden">
        <Avatar initial={ok ? initialOf(session.data.identity) : null} />
        <div className="min-w-0">
          <p className="truncate text-sm" title={who}>
            {who}
          </p>
          <p className="truncate text-[0.8125rem] text-label">{detail}</p>
        </div>
      </div>
      <div className="hidden justify-center group-data-[collapsible=icon]:flex">
        <Tooltip>
          <TooltipTrigger
            aria-label={`Signed in as ${summary}`}
            className="rounded-full"
            render={<button type="button" />}
          >
            <Avatar initial={ok ? initialOf(session.data.identity) : null} />
          </TooltipTrigger>
          <TooltipContent side="right">{summary}</TooltipContent>
        </Tooltip>
      </div>
      <ThemeSwitcher compact className="group-data-[collapsible=icon]:hidden" />
    </div>
  )
}

export { IdentityFooter }

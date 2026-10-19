"use client"

import { Activity, CalendarDays, FileText, Inbox, Share2, type LucideIcon } from "lucide-react"
import { useSearchParams } from "next/navigation"
import * as React from "react"

import { useAppData } from "@/components/app-data"
import { EmptyState } from "@/components/empty-state"
import { ErrorPanel } from "@/components/error-panel"
import { LoadingState } from "@/components/loading-state"

/** The open post lives in the address (`?post=ID`), so a view can be shared. No dynamic routes. */
export function usePostParam(): string | null {
  return useSearchParams().get("post")
}

function SelectedPost() {
  const post = usePostParam()
  if (!post) return null
  return (
    <p className="text-sm text-label">
      Selected post: <code className="font-mono text-ink">{post}</code>
    </p>
  )
}

export function PageHeading({ title, description }: { title: string; description: string }) {
  return (
    <div>
      <h1 className="text-4xl tracking-tight">{title}</h1>
      <p className="mt-3 max-w-prose text-label">{description}</p>
    </div>
  )
}

type View = { title: string; description: string; icon: LucideIcon; line: string; command: string }

// The copy of each stubbed route. The pages are server components (they set the document title),
// so they pass a key, not an icon component, across the client boundary.
export const VIEWS = {
  calendar: {
    title: "Calendar",
    description: "Every post in its publishing window, by week and by month.",
    icon: CalendarDays,
    line: "The calendar fills as agents add posts. It is not built yet; this page is the shell.",
    command: "brandcal add --as NAME ...",
  },
  "needs-you": {
    title: "Needs you",
    description: "Posts waiting for your decision: approvals, requested changes and missed windows.",
    icon: Inbox,
    line: "Nothing is waiting for you here yet. The list arrives with the read views.",
    command: "brandcal add --as NAME ...",
  },
  posts: {
    title: "Posts",
    description: "Every post, with its status, platform and window.",
    icon: FileText,
    line: "No posts are shown yet. The list arrives with the read views.",
    command: "brandcal add --as NAME ...",
  },
  channels: {
    title: "Channels",
    description: "The platforms posts can go to, and their limits.",
    icon: Share2,
    line: "Channels come from platforms.json. The channel view arrives with the read views.",
    command: "brandcal init",
  },
  activity: {
    title: "Activity",
    description: "What changed, who did it and when, from the audit trail.",
    icon: Activity,
    line: "No activity is shown yet. The audit trail arrives with the read views.",
    command: "brandcal events --since 0",
  },
} satisfies Record<string, View>

// Every N1 route is a stub: heading, one line, then a loading placeholder while the session and
// rules load, the server's own refusal if they cannot, or the empty state with the agent command
// that creates data. The read views arrive in N2.
function RoutePage({ view }: { view: keyof typeof VIEWS }) {
  const { title, description, icon, line, command } = VIEWS[view]
  const { session, schema } = useAppData()
  const refusal =
    session.state === "error" ? session.refusal : schema.state === "error" ? schema.refusal : null
  const loading = session.state === "loading" || schema.state === "loading"

  return (
    <div className="flex flex-col gap-10">
      <PageHeading title={title} description={description} />
      <React.Suspense fallback={null}>
        <SelectedPost />
      </React.Suspense>
      {refusal ? (
        <ErrorPanel error={refusal} />
      ) : loading ? (
        <LoadingState label={`Loading ${title.toLowerCase()}`} />
      ) : (
        <EmptyState icon={icon} line={line} command={command} />
      )}
    </div>
  )
}

export { RoutePage }

"use client"

import { Inbox } from "lucide-react"
import * as React from "react"

import { useAppData, type Loadable } from "@/components/app-data"
import { EmptyState } from "@/components/empty-state"
import { ErrorPanel } from "@/components/error-panel"
import { LoadingState } from "@/components/loading-state"
import { PlatformBadge } from "@/components/platform-swatch"
import { useOpenPost } from "@/components/post-bits"
import { PageHeading } from "@/components/route-page"
import { StatusChip } from "@/components/status-chip"
import { Figure, ViewGate } from "@/components/view-gate"
import type { Schema } from "@/lib/api"
import { loadNeedsYou, type NeedsGroup } from "@/lib/needs-you"
import { dayLabel, spanOf } from "@/lib/time"
import { useUrlState } from "@/lib/url-state"

// The agent command that would put a post into each state; the empty state shows it.
const HOW: Record<string, string> = {
  pending_approval: "brandcal submit POST_ID --as NAME",
  changes_requested: "brandcal request-changes POST_ID --as NAME ...",
  missed: "brandcal sweep --as NAME",
}

function Sections({ schema, groups }: { schema: Schema; groups: NeedsGroup[] }) {
  const open = useOpenPost()
  const { params } = useUrlState()
  const current = params.get("post")
  return (
    <div className="flex flex-col gap-8">
      {groups.map(({ status, posts }) => (
        <section
          key={status}
          data-status={status}
          aria-labelledby={`needs-${status}`}
          className="flex flex-col gap-4"
        >
          <div className="flex items-end justify-between gap-4">
            <h2 id={`needs-${status}`} className="flex items-center gap-3 text-2xl tracking-tight">
              <StatusChip status={status} />
            </h2>
            <Figure value={posts.length} label={posts.length === 1 ? "post" : "posts"} />
          </div>
          {posts.length === 0 ? (
            <EmptyState
              icon={Inbox}
              line="Nothing here."
              command={HOW[status] ?? `brandcal list --status ${status}`}
              className="py-10"
            />
          ) : (
            <ul className="card-surface divide-y divide-hairline overflow-hidden">
              {posts.map((p) => {
                const span = p.window ? spanOf(p.window, schema.timezone) : null
                return (
                  <li key={p.id}>
                    <button
                      type="button"
                      data-post-id={p.id}
                      aria-current={current === p.id ? "true" : undefined}
                      title={p.window ?? undefined}
                      onClick={(e) => open(p.id, e.currentTarget)}
                      className="press flex min-h-14 w-full flex-wrap items-center gap-x-4 gap-y-2 px-5 py-4 text-left hover:bg-muted aria-[current=true]:bg-muted"
                    >
                      <PlatformBadge platform={p.platform} />
                      <span className="min-w-0 flex-1 basis-48">{p.title}</span>
                      {span && (
                        <span className="text-sm text-label tabular-nums">
                          {dayLabel(span.day)}, {span.from}
                        </span>
                      )}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      ))}
    </div>
  )
}

function Loaded({ schema }: { schema: Schema }) {
  const [state, setState] = React.useState<Loadable<NeedsGroup[]>>({ state: "loading" })
  const { epoch } = useAppData()
  React.useEffect(() => {
    let live = true
    loadNeedsYou(schema).then((r) => {
      if (live) setState(r.ok ? { state: "ok", data: r.groups } : { state: "error", refusal: r.refusal })
    })
    return () => {
      live = false
    }
  }, [schema, epoch])
  if (state.state === "loading") return <LoadingState label="Loading what needs you" rows={3} />
  if (state.state === "error") return <ErrorPanel error={state.refusal} />
  return <Sections schema={schema} groups={state.data} />
}

export function NeedsYouView() {
  return (
    <div className="flex flex-col gap-10">
      <PageHeading
        title="Needs you"
        description="Posts waiting for your decision: approvals, requested changes and missed windows."
      />
      <ViewGate label="Loading what needs you" rows={3}>
        {(schema) => <Loaded schema={schema} />}
      </ViewGate>
    </div>
  )
}

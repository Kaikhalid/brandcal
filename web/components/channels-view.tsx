"use client"

import { Share2 } from "lucide-react"
import * as React from "react"

import { useAppData, type Loadable } from "@/components/app-data"
import { EmptyState } from "@/components/empty-state"
import { ErrorPanel } from "@/components/error-panel"
import { LoadingState } from "@/components/loading-state"
import { PlatformBadge, platformTone } from "@/components/platform-swatch"
import { words } from "@/components/post-bits"
import { PageHeading } from "@/components/route-page"
import { StatusChip } from "@/components/status-chip"
import { ViewGate } from "@/components/view-gate"
import { getPost, getPosts, type PostRow, type Schema } from "@/lib/api"
import { addDays, fullTime, isDateKey, monthStart, spanOf, todayKey } from "@/lib/time"
import { useUrlState } from "@/lib/url-state"
import { cn } from "@/lib/utils"

type Live = { id: string; title: string; urls: string[]; at: string }
type Data = { rows: PostRow[]; live: Live[] }

const LIVE_PER_CHANNEL = 3

async function load(schema: Schema): Promise<Loadable<Data>> {
  const list = await getPosts({ closed: true })
  if (!list.ok) return { state: "error", refusal: list.refusal }
  const rows = list.data.posts
  // The latest published posts of each channel, for their live URLs.
  const latest = Object.keys(schema.platforms).flatMap((platform) =>
    rows
      .filter((r) => r.platform === platform && r.status === "published")
      .sort((a, b) => (b.window ?? "").localeCompare(a.window ?? ""))
      .slice(0, LIVE_PER_CHANNEL)
  )
  const details = await Promise.all(latest.map((r) => getPost(r.id)))
  const live: Live[] = []
  for (const [i, d] of details.entries()) {
    if (!d.ok) return { state: "error", refusal: d.refusal }
    const urls = [d.data.platform_url, ...d.data.parts.map((p) => p.platform_url)].filter(
      (u): u is string => Boolean(u)
    )
    if (urls.length) {
      live.push({ id: latest[i].id, title: latest[i].title, urls: [...new Set(urls)], at: d.data.published_at ?? "" })
    }
  }
  return { state: "ok", data: { rows, live } }
}

function Card({ schema, id, limits, data, month }: {
  schema: Schema
  id: string
  limits: Record<string, unknown>
  data: Data
  month: [string, string]
}) {
  const mine = data.rows.filter((r) => {
    if (r.platform !== id || !r.window) return false
    const day = spanOf(r.window, schema.timezone).day
    return day >= month[0] && day <= month[1]
  })
  const counts = schema.states
    .map((status) => ({ status, n: mine.filter((r) => r.status === status).length }))
    .filter((c) => c.n > 0)
  const urls = data.live.filter((l) => data.rows.find((r) => r.id === l.id)?.platform === id)
  return (
    <section aria-labelledby={`ch-${id}`} data-platform={id} className="card-surface overflow-hidden">
      <div className={cn("flex items-center justify-between gap-3 px-6 py-5", platformTone(id))}>
        <h2 id={`ch-${id}`} className="text-xl tracking-tight">
          <PlatformBadge platform={id} className="bg-transparent px-0 text-base" />
        </h2>
        <code className="rounded-control bg-surface/60 px-2 py-1 font-mono text-xs">{id}</code>
      </div>
      <div className="flex flex-col gap-6 p-6">
        <div>
          <h3 className="mb-2 text-sm font-normal text-label">Limits</h3>
          {Object.keys(limits).length ? (
            <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm">
              {Object.entries(limits).map(([key, value]) => (
                <React.Fragment key={key}>
                  <dt>{words(key)}</dt>
                  <dd className="tabular-nums">{String(value)}</dd>
                </React.Fragment>
              ))}
            </dl>
          ) : (
            <p className="text-sm text-label">No limits are set for this channel.</p>
          )}
        </div>
        <div>
          <h3 className="mb-2 text-sm font-normal text-label">This month</h3>
          {counts.length ? (
            <ul className="flex flex-wrap gap-2">
              {counts.map(({ status, n }) => (
                <li key={status} className="flex items-center gap-2">
                  <StatusChip status={status} />
                  <span className="text-xl font-light tabular-nums">{n}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-label">No posts this month.</p>
          )}
        </div>
        {urls.length > 0 && (
          <div>
            <h3 className="mb-2 text-sm font-normal text-label">Latest live</h3>
            <ul className="flex flex-col gap-2 text-sm">
              {urls.flatMap((l) =>
                l.urls.map((u) => (
                  <li key={`${l.id}-${u}`} className="min-w-0">
                    <span className="block">{l.title}</span>
                    <a
                      href={u}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="break-all underline underline-offset-4"
                    >
                      {u}
                      <span className="sr-only"> (opens in a new tab)</span>
                    </a>
                    {l.at && (
                      <span className="block text-xs text-label">
                        {fullTime(l.at, schema.timezone)}
                      </span>
                    )}
                  </li>
                ))
              )}
            </ul>
          </div>
        )}
      </div>
    </section>
  )
}

function Loaded({ schema }: { schema: Schema }) {
  const [state, setState] = React.useState<Loadable<Data>>({ state: "loading" })
  const { params } = useUrlState()
  const { epoch } = useAppData()
  React.useEffect(() => {
    let live = true
    load(schema).then((r) => live && setState(r))
    return () => {
      live = false
    }
  }, [schema, epoch])
  const ids = Object.keys(schema.platforms)
  if (ids.length === 0) {
    return (
      <EmptyState
        icon={Share2}
        line="No channels are configured. Channels come from platforms.json."
        command="brandcal init"
      />
    )
  }
  if (state.state === "loading") return <LoadingState label="Loading channels" rows={3} />
  if (state.state === "error") return <ErrorPanel error={state.refusal} />
  // The current month, or the month of ?date= so a view can be pinned and shared.
  const date = isDateKey(params.get("date")) ? params.get("date")! : todayKey(schema.timezone)
  const bounds: [string, string] = [monthStart(date), addDays(monthStart(date, 1), -1)]
  return (
    <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
      {ids.map((id) => (
        <Card key={id} schema={schema} id={id} limits={schema.platforms[id]} data={state.data} month={bounds} />
      ))}
    </div>
  )
}

export function ChannelsView() {
  return (
    <div className="flex flex-col gap-10">
      <PageHeading
        title="Channels"
        description="The platforms posts can go to, their limits and what is planned this month."
      />
      <ViewGate label="Loading channels" rows={3}>
        {(schema) => <Loaded schema={schema} />}
      </ViewGate>
    </div>
  )
}

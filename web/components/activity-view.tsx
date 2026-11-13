"use client"

import { Activity } from "lucide-react"
import * as React from "react"

import { useAppData } from "@/components/app-data"
import { EmptyState } from "@/components/empty-state"
import { ErrorPanel } from "@/components/error-panel"
import { LoadingState } from "@/components/loading-state"
import { words, useOpenPost } from "@/components/post-bits"
import { PageHeading } from "@/components/route-page"
import { ViewGate } from "@/components/view-gate"
import { getEvents, getPosts, type BrandcalRefusal, type EventRow, type PostRow, type Schema } from "@/lib/api"
import { fullTime } from "@/lib/time"
import { useUrlState } from "@/lib/url-state"

const PAGE = 500 // events per request while reading the log
const SHOWN = 50 // rows shown at first, and added by each "Load older"

/** Who decided and through what: the verified identity the server recorded, in words. */
export function sourceOf(detail: unknown): { identity: string | null; source: string } {
  const d = typeof detail === "object" && detail !== null ? (detail as Record<string, unknown>) : {}
  const identity = typeof d.identity === "string" ? d.identity : null
  if (d.via === "console") return { identity, source: "console (verified)" }
  if (d.source === "dev-unverified") return { identity, source: "dev (unverified)" }
  if (typeof d.source === "string") return { identity, source: d.source }
  return { identity, source: "CLI" }
}

type LogState = { events: EventRow[]; lastId: number }

/** Read the log forward from `since` (the API pages in id order) until it is exhausted. */
async function readLog(
  post: string,
  since: number
): Promise<{ ok: true; events: EventRow[]; lastId: number } | { ok: false; refusal: BrandcalRefusal }> {
  const events: EventRow[] = []
  let lastId = since
  for (;;) {
    const page = await getEvents({ since: lastId, post: post || undefined, limit: PAGE })
    if (!page.ok) return { ok: false, refusal: page.refusal }
    events.push(...page.data.events)
    lastId = page.data.last_id
    if (page.data.events.length < PAGE) return { ok: true, events, lastId }
  }
}

function Log({ schema, posts }: { schema: Schema; posts: PostRow[] }) {
  const { params, set } = useUrlState()
  const open = useOpenPost()
  const post = params.get("for") ?? ""
  const { epoch } = useAppData()
  // What was read is kept with the post filter it belongs to; another filter reads as loading.
  const [read, setRead] = React.useState<{ post: string; log?: LogState; error?: BrandcalRefusal } | null>(null)
  const [shown, setShown] = React.useState(SHOWN)
  const [checking, setChecking] = React.useState(false)
  const [note, setNote] = React.useState("")
  const current = read?.post === post ? read : null
  const log = current?.log
  const error = current?.error

  React.useEffect(() => {
    let live = true
    readLog(post, 0).then((r) => {
      if (!live) return
      setShown(SHOWN)
      setRead(r.ok ? { post, log: { events: r.events, lastId: r.lastId } } : { post, error: r.refusal })
    })
    return () => {
      live = false
    }
  }, [post, epoch])

  async function checkForNew() {
    if (!log) return
    setChecking(true)
    const r = await readLog(post, log.lastId)
    setChecking(false)
    if (!r.ok) return setRead({ post, error: r.refusal })
    setRead({ post, log: { events: [...log.events, ...r.events], lastId: r.lastId } })
    setNote(r.events.length ? `${r.events.length} new` : "Nothing new")
  }

  if (error) return <ErrorPanel error={error} />
  if (!log) return <LoadingState label="Loading activity" rows={6} />

  const newest = [...log.events].reverse()
  const rows = newest.slice(0, shown)
  const titles = new Map(posts.map((p) => [p.id, p.title]))
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="activity-post" className="text-sm text-label">
            Post
          </label>
          <select
            id="activity-post"
            value={post}
            onChange={(e) => set({ for: e.target.value })}
            className="h-10 min-w-56 rounded-control border border-control bg-surface px-3 text-sm"
          >
            <option value="">All posts</option>
            {posts.map((p) => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          onClick={checkForNew}
          disabled={checking}
          className="press h-10 rounded-full border border-control bg-surface px-5 text-sm hover:bg-muted"
        >
          Check for new
        </button>
        <span role="status" className="text-sm text-label">
          {checking ? "Checking" : note}
        </span>
      </div>

      {rows.length === 0 ? (
        <EmptyState
          icon={Activity}
          line="No activity yet. Every change an agent or a person makes is recorded here."
          command="brandcal events --since 0"
        />
      ) : (
        <ol className="card-surface divide-y divide-hairline overflow-hidden">
          {rows.map((e) => {
            const { identity, source } = sourceOf(e.detail)
            return (
              <li
                key={e.id}
                data-event-id={e.id}
                className="grid gap-x-6 gap-y-1 px-5 py-4 md:grid-cols-[11rem_1fr_auto]"
              >
                <span className="text-sm text-label tabular-nums">{fullTime(e.at, schema.timezone)}</span>
                <span className="min-w-0">
                  <span className="font-medium">{words(e.action)}</span>
                  {e.from_status && e.to_status && e.from_status !== e.to_status && (
                    <span className="text-label">
                      {" "}
                      · {words(e.from_status)} to {words(e.to_status)}
                    </span>
                  )}
                  <span className="block text-sm text-label">
                    {e.actor}
                    {identity ? `, ${identity}` : ""} · {source}
                  </span>
                  {e.reason && <span className="block text-sm">{e.reason}</span>}
                </span>
                {e.post_id && (
                  <button
                    type="button"
                    data-post-id={e.post_id}
                    onClick={(ev) => open(e.post_id!, ev.currentTarget)}
                    className="press -mx-2 min-h-8 self-start rounded-control px-2 text-left text-sm underline underline-offset-4 hover:bg-muted"
                  >
                    {titles.get(e.post_id) ?? e.post_id}
                  </button>
                )}
              </li>
            )
          })}
        </ol>
      )}
      {shown < newest.length && (
        <button
          type="button"
          onClick={() => setShown(shown + SHOWN)}
          className="press h-10 self-start rounded-full border border-control bg-surface px-5 text-sm hover:bg-muted"
        >
          Load older
        </button>
      )}
    </div>
  )
}

function Loaded({ schema }: { schema: Schema }) {
  const [posts, setPosts] = React.useState<PostRow[] | null>(null)
  React.useEffect(() => {
    let live = true
    getPosts({ closed: true }).then((r) => live && setPosts(r.ok ? r.data.posts : []))
    return () => {
      live = false
    }
  }, [])
  if (posts === null) return <LoadingState label="Loading activity" rows={6} />
  return <Log schema={schema} posts={posts} />
}

export function ActivityView() {
  return (
    <div className="flex flex-col gap-10">
      <PageHeading
        title="Activity"
        description="What changed, who did it and when, from the audit trail. Newest first."
      />
      <ViewGate label="Loading activity" rows={6}>
        {(schema) => <Loaded schema={schema} />}
      </ViewGate>
    </div>
  )
}

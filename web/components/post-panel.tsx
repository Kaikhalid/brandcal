"use client"

import { ChevronLeft, Copy, TriangleAlert, X } from "lucide-react"
import * as React from "react"
import { Suspense } from "react"
import { flushSync } from "react-dom"

import { useAppData, type Loadable } from "@/components/app-data"
import { Disclosure } from "@/components/disclosure"
import { ErrorPanel } from "@/components/error-panel"
import { QueueRail, railFrame, useRail } from "@/components/inspector-rail"
import { useNeedsQueue } from "@/components/needs-queue"
import { useNotice } from "@/components/notice"
import { PlatformBadge } from "@/components/platform-swatch"
import { Actions, type ActionsHost } from "@/components/post-actions"
import { PostBadges, TypeTag, focusPostLater, takeOpener, words } from "@/components/post-bits"
import { StatusChip } from "@/components/status-chip"
import { Skeleton } from "@/components/ui/skeleton"
import {
  getEvents,
  getPost,
  getVersions,
  mediaUrl,
  type EventRow,
  type PostAction,
  type PostDetail,
  type Schema,
  type Version,
} from "@/lib/api"
import { diffLines } from "@/lib/diff"
import { afterDecision } from "@/lib/needs-you"
import { dayLabel, fullTime, spanOf, windowLabel, windowSpansDays } from "@/lib/time"
import { useUrlState } from "@/lib/url-state"
import { cn } from "@/lib/utils"

type Data = { post: PostDetail; events: EventRow[]; versions: Version[] }

async function fetchPanel(id: string): Promise<Loadable<Data>> {
  const [post, ev, vs] = await Promise.all([getPost(id), getEvents({ post: id }), getVersions(id)])
  const failed = [post, ev, vs].find((r) => !r.ok)
  if (failed && !failed.ok) return { state: "error", refusal: failed.refusal }
  if (post.ok && ev.ok && vs.ok) {
    return { state: "ok", data: { post: post.data, events: ev.data.events, versions: vs.data.versions } }
  }
  return { state: "loading" }
}

function usePanelData(id: string): { state: Loadable<Data>; reload: () => Promise<Loadable<Data>> } {
  // The answer is kept with the post it belongs to; another post reads as loading.
  const [answer, setAnswer] = React.useState<{ id: string; state: Loadable<Data> } | null>(null)
  React.useEffect(() => {
    let live = true
    fetchPanel(id).then((state) => live && setAnswer({ id, state }))
    return () => {
      live = false
    }
  }, [id])
  // After a write: read the post again. The old answer stays on screen until the new one is in.
  const reload = React.useCallback(async () => {
    const state = await fetchPanel(id)
    // Drawn before this returns, so the caller can look for the button it wants to focus.
    flushSync(() => setAnswer({ id, state }))
    return state
  }, [id])
  return { state: answer?.id === id ? answer.state : { state: "loading" }, reload }
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const id = React.useId()
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <h3 id={id} className="text-sm font-normal text-label">
        {title}
      </h3>
      {children}
    </section>
  )
}

function Rows({ rows }: { rows: [string, React.ReactNode][] }) {
  const shown = rows.filter(([, v]) => v !== null && v !== undefined && v !== "" && v !== false)
  return (
    <dl className="grid grid-cols-[7rem_1fr] gap-x-4 gap-y-2 text-sm">
      {shown.map(([label, value]) => (
        <React.Fragment key={label}>
          <dt className="text-label">{label}</dt>
          <dd className="min-w-0 break-words">{value}</dd>
        </React.Fragment>
      ))}
    </dl>
  )
}

const link = (url: string) =>
  /^https?:/.test(url) ? (
    <a href={url} target="_blank" rel="noopener noreferrer" className="break-all underline underline-offset-4">
      {url}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  ) : (
    url
  )

function Fingerprint({ hash }: { hash: string }) {
  const [said, setSaid] = React.useState("")
  async function copy() {
    try {
      await navigator.clipboard.writeText(hash)
      setSaid("Copied the full hash")
    } catch {
      setSaid("Could not copy; select the hash and copy it by hand")
    }
  }
  return (
    <span className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={copy}
        title={hash}
        aria-label={`Fingerprint ${hash.slice(0, 8)}. Copy the full hash`}
        className="press inline-flex min-h-8 items-center gap-2 rounded-control border border-control px-2.5 font-mono text-[0.8125rem] hover:bg-muted"
      >
        {hash.slice(0, 8)}
        <Copy aria-hidden="true" strokeWidth={1.5} className="size-4" />
      </button>
      <span role="status" className="text-[0.8125rem] text-label">
        {said}
      </span>
    </span>
  )
}

function Text({ post, schema }: { post: PostDetail; schema: Schema }) {
  const limit = schema.platforms[post.platform]?.chars_per_post
  const max = typeof limit === "number" ? limit : null
  return post.parts.map((part) => {
    const n = [...part.text].length
    const over = max !== null && n > max
    return (
      <Section key={part.pos} title={post.parts.length > 1 ? `Part ${part.pos} of ${post.parts.length}` : "Text"}>
        <pre className="rounded-control bg-muted p-3 font-sans text-sm leading-relaxed whitespace-pre-wrap">
          {part.text}
        </pre>
        <p className="text-[0.8125rem] text-label tabular-nums">
          {max !== null ? `${n} / ${max} characters` : `${n} characters`}
          {over && (
            <span className="ml-2 inline-flex items-center gap-1 font-medium text-destructive">
              <TriangleAlert aria-hidden="true" strokeWidth={1.5} className="size-4" />
              TOO_LONG: {n - max} over
            </span>
          )}
        </p>
      </Section>
    )
  })
}

function Media({ post }: { post: PostDetail }) {
  if (!post.media.length) return null
  return (
    <Section title="Media">
      {post.media.map((m, i) => {
        const src = mediaUrl(post.id, i + 1)
        const alt = (m.alt_text ?? "").trim()
        return (
          <figure key={src} className="flex flex-col gap-2">
            {m.kind === "image" || m.kind === "gif" ? (
              // eslint-disable-next-line @next/next/no-img-element -- a same-origin API file, not a static asset
              <img src={src} alt={alt} loading="lazy" className="w-full rounded-control bg-muted" />
            ) : (
              <a href={src} className="underline underline-offset-4">
                {words(m.kind)} file {i + 1}
              </a>
            )}
            <figcaption className="text-sm">
              {alt ? (
                <>
                  <strong className="font-medium">Alt text:</strong> {alt}
                </>
              ) : (
                <span className="inline-flex items-center gap-1.5 font-medium text-destructive">
                  <TriangleAlert aria-hidden="true" strokeWidth={1.5} className="size-4" />
                  No alt text. Add it before approval.
                </span>
              )}
            </figcaption>
          </figure>
        )
      })}
    </Section>
  )
}

function Details({ post, zone }: { post: PostDetail; zone: string | null }) {
  const live = [...new Set([post.platform_url, ...post.parts.map((p) => p.platform_url)].filter(Boolean))] as string[]
  const t = (iso: string | null) => (iso ? fullTime(iso, zone) : null)
  return (
    <Section title="Details">
      <Rows
        rows={[
          ["Channel", <PlatformBadge key="c" platform={post.platform} />],
          ["Published", t(post.published_at)],
          [
            "Live URL",
            live.length ? (
              <span key="l" className="flex flex-col gap-1">
                {live.map((u) => (
                  <span key={u}>{link(u)}</span>
                ))}
              </span>
            ) : null,
          ],
          ["First comment", post.first_comment],
          ["Target URL", post.target_url && link(post.target_url)],
          ["Campaign", post.campaign],
          ["Pillar", post.pillar],
          ["Owner", post.owner],
          ["Notes", post.notes],
          ["Claimed", post.claimed_by && `${post.claimed_by} until ${t(post.claim_expires)}`],
          ["Queued on platform", t(post.native_scheduled_at)],
          [
            "On hold until",
            post.hold_until && `${t(post.hold_until)}${post.hold_reason ? ` (${post.hold_reason})` : ""}`,
          ],
          ["Closed", t(post.closed_at)],
        ]}
      />
    </Section>
  )
}

function formatChanges(raw: string): string {
  try {
    const c = JSON.parse(raw) as Record<string, string>
    return `What: ${c.what}. Where: ${c.where}. Instruction: ${c.instruction}.`
  } catch {
    return raw
  }
}

function History({ data, zone }: { data: Data; zone: string | null }) {
  const { post, events } = data
  const changes = events.filter(
    (e) => e.action === "add" || e.action === "edit" || e.action === "media_add" || e.action.startsWith("part")
  )
  return (
    <Disclosure title="Version history">
      <p className="text-sm">
        Now version {post.content_version}, fingerprint{" "}
        <code className="font-mono">{post.content_hash.slice(0, 8)}</code>
      </p>
      <ul className="flex flex-col gap-2 text-sm">
        {changes.map((e) => (
          <li key={e.id}>
            {words(e.action)} by {e.actor}
            <span className="block text-[0.8125rem] text-label tabular-nums">{fullTime(e.at, zone)}</span>
          </li>
        ))}
      </ul>
      {post.approvals.length > 0 && (
        <>
          <h4 className="text-sm font-normal text-label">Decisions</h4>
          <ul className="flex flex-col gap-3 text-sm">
            {post.approvals.map((a) => (
              <li key={a.id}>
                <strong className="font-medium">{words(a.decision)}</strong> on version {a.content_version},
                fingerprint <code className="font-mono">{a.content_hash.slice(0, 8)}</code>
                <span className="block text-[0.8125rem] text-label tabular-nums">
                  {a.decided_by} via{" "}
                  {a.channel === "console" ? `console (verified: ${a.verified_identity})` : a.channel},{" "}
                  {fullTime(a.decided_at, zone)}
                </span>
                {a.approver_words && <span className="block">&ldquo;{a.approver_words}&rdquo;</span>}
                {a.changes_requested && (
                  <span className="block text-label">{formatChanges(a.changes_requested)}</span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </Disclosure>
  )
}

const flat =(v: Version) => [
  ...v.parts.flatMap((t, i) => [`Part ${i + 1}:`, ...t.split("\n")]),
  `First comment: ${v.first_comment ?? ""}`,
  `Target URL: ${v.target_url ?? ""}`,
  ...v.alt_texts.map((t, i) => `Alt text ${i + 1}: ${t}`),
]

function Compare({ versions }: { versions: Version[] }) {
  const [from, setFrom] = React.useState(String(versions[versions.length - 2]?.version ?? ""))
  const [to, setTo] = React.useState(String(versions[versions.length - 1]?.version ?? ""))
  const select = "h-10 rounded-control border border-control bg-surface px-3 text-sm"
  if (versions.length < 2) {
    return (
      <Disclosure title="Compare versions">
        <p className="text-sm text-label">Only one version exists, so there is nothing to compare.</p>
      </Disclosure>
    )
  }
  const find = (n: string) => versions.find((v) => String(v.version) === n) ?? versions[0]
  const lines = diffLines(flat(find(from)), flat(find(to)))
  const options = versions.map((v) => (
    <option key={v.version} value={v.version}>
      Version {v.version}
    </option>
  ))
  return (
    <Disclosure title="Compare versions">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <select aria-label="Compare from" value={from} onChange={(e) => setFrom(e.target.value)} className={select}>
          {options}
        </select>
        <span className="text-label">to</span>
        <select aria-label="Compare to" value={to} onChange={(e) => setTo(e.target.value)} className={select}>
          {options}
        </select>
      </div>
      <pre aria-live="polite" data-diff className="overflow-x-auto rounded-control bg-muted py-2 font-mono text-[0.8125rem] leading-relaxed">
        {lines.map((l, i) => (
          <span
            key={i}
            data-sign={l.sign === " " ? "same" : l.sign === "+" ? "add" : "del"}
            className={cn(
              "block px-3 whitespace-pre-wrap",
              l.sign === "+" && "bg-pf-bluesky text-pf-bluesky-ink",
              l.sign === "-" && "bg-pf-instagram text-pf-instagram-ink"
            )}
          >
            {l.sign === " " ? "  " : `${l.sign} `}
            {l.text}
          </span>
        ))}
      </pre>
    </Disclosure>
  )
}

function identityTag(detail: unknown): string | null {
  const d = typeof detail === "object" && detail !== null ? (detail as Record<string, unknown>) : null
  if (!d) return null
  if (d.via === "console") return `console (verified: ${String(d.identity)})`
  if (d.source === "dev-unverified") return "dev (unverified)"
  return null
}

function Audit({ events, zone }: { events: EventRow[]; zone: string | null }) {
  return (
    <Disclosure title="Audit trail">
      <ol className="flex flex-col gap-3 text-sm">
        {events.map((e) => {
          const tag = identityTag(e.detail)
          return (
            <li key={e.id}>
              <strong className="font-medium">{words(e.action)}</strong> by {e.actor}
              {e.from_status && e.to_status && e.from_status !== e.to_status
                ? `: ${words(e.from_status)} to ${words(e.to_status)}`
                : ""}
              <span className="block text-[0.8125rem] text-label tabular-nums">
                {fullTime(e.at, zone)}
                {tag ? `, ${tag}` : ""}
              </span>
              {e.reason && <span className="block">{e.reason}</span>}
            </li>
          )
        })}
      </ol>
    </Disclosure>
  )
}

function Body({ data, schema, host }: { data: Data; schema: Schema; host: ActionsHost }) {
  const { post } = data
  const zone = schema.timezone
  const w = post.window ? spanOf(post.window, zone) : null
  return (
    <div className="flex flex-col gap-7">
      <div className="flex flex-wrap items-center gap-2">
        <StatusChip status={post.status} />
        <PlatformBadge platform={post.platform} />
        <TypeTag type={post.post_type} />
        <PostBadges post={post} />
      </div>
      {/* Actions first: pinned under the status, so Approve is in view on open and stays there. */}
      <Actions post={post} schema={schema} host={host} />
      <Rows
        rows={[
          ["Post", <code key="p" className="font-mono">{post.id}</code>],
          ["Slug", <code key="s" className="font-mono">{post.slug}</code>],
          ["When", w && `${dayLabel(w.day)}, ${w.text}`],
          [
            "Window",
            // A same-day window reads exactly like "When"; show the row only when it adds an end day.
            post.window && windowSpansDays(post.window, zone) && (
              <span key="w" title={post.window} className="tabular-nums">
                {windowLabel(post.window, zone)}
              </span>
            ),
          ],
          ["Version", String(post.content_version)],
          ["Fingerprint", <Fingerprint key="f" hash={post.content_hash} />],
        ]}
      />
      <Text post={post} schema={schema} />
      <Media post={post} />
      <Details post={post} zone={zone} />
      <History data={data} zone={zone} />
      <Compare versions={data.versions} />
      <Audit events={data.events} zone={zone} />
    </div>
  )
}

// A decision takes the post out of your hands, so on the calendar's rail the next in the queue opens.
const DECISIONS: PostAction["id"][] = ["approve", "request-changes", "cancel"]

/** `rail`: on the calendar, where this is the inspector rail's detail state. `beside`: a column, not a sheet. */
function Panel({ id, rail, beside }: { id: string; rail: boolean; beside: boolean }) {
  const { schema, refresh } = useAppData()
  const { params, set } = useUrlState()
  const notify = useNotice()
  const queue = useNeedsQueue()
  const queued = React.useRef(queue.posts)
  React.useEffect(() => {
    queued.current = queue.posts
  }, [queue.posts])
  // A sheet opened from the queue goes back to it; one opened from the calendar just closes.
  const back = rail && (beside || params.get("queue") === "1")
  const { state, reload } = usePanelData(id)
  const heading = React.useRef<HTMLHeadingElement>(null)
  const root = React.useRef<HTMLElement>(null)
  const title = state.state === "ok" ? state.data.post.title : "Post"
  const version = state.state === "ok" ? state.data.post.content_version : 0
  const [banner, setBanner] = React.useState<string | null>(null)

  // After a write the panel waits for two things before it says and focuses anything: the reload
  // has been drawn, and the dialog has finished closing (the page behind a modal is inert, so
  // focus cannot land earlier).
  const latest = React.useRef({ title, version })
  React.useEffect(() => {
    latest.current = { title, version }
  }, [title, version])
  const gate = React.useRef({
    pending: null as PostAction["id"] | null,
    notice: null as string | null,
    reloading: false,
    closed: true,
    // Where the rail goes after a decision: a post id, null for all clear, undefined to stay.
    advance: undefined as string | null | undefined,
  })
  const settle = React.useCallback(() => {
    const g = gate.current
    if (g.reloading || !g.closed) return
    if (g.notice) notify(g.notice)
    g.notice = null
    if (g.advance !== undefined) {
      const next = g.advance
      g.advance = undefined
      g.pending = null
      takeOpener()
      // The panel of the next post mounts and takes focus on its heading; all clear focuses the queue's.
      set({ post: next }, "replace")
      if (next === null) window.setTimeout(() => document.getElementById("rail-title")?.focus(), 80)
      return
    }
    if (g.pending) {
      // The same action, or the panel heading when it no longer exists or is disabled.
      const same = root.current?.querySelector<HTMLElement>(`[data-action-button="${g.pending}"]:not([disabled])`)
      ;(same ?? heading.current)?.focus()
    }
    g.pending = null
  }, [notify, set])

  const host = React.useMemo<ActionsHost>(
    () => ({
      opened: () => {
        gate.current.closed = false
      },
      closed: (actionId) => {
        gate.current.closed = true
        gate.current.pending ??= actionId
        settle()
      },
      written: async (actionId, label, result) => {
        const g = gate.current
        g.pending = actionId
        g.reloading = true
        setBanner(null)
        // Taken before the write is read back: the queue as it stood when the decision was made.
        if (rail && DECISIONS.includes(actionId)) g.advance = afterDecision(queued.current, id)
        const fresh = await reload()
        const post = fresh.state === "ok" ? fresh.data.post : null
        const status = String(result.status ?? post?.status ?? "")
        g.notice = `${label}: done. ${latest.current.title} is now ${words(status)}, version ${result.version ?? post?.content_version}.`
        g.reloading = false
        refresh()
        settle()
      },
      stale: async (actionId, current) => {
        const g = gate.current
        g.pending = actionId
        g.reloading = true
        setBanner(
          `This post changed (version ${latest.current.version} to ${current?.content_version ?? "a newer version"}). Read it again before deciding. Nothing was recorded.`
        )
        await reload()
        g.reloading = false
        refresh()
        settle()
      },
    }),
    [reload, refresh, settle, rail, id]
  )

  // Focus moves into the panel when it opens or switches post.
  React.useEffect(() => {
    heading.current?.focus({ preventScroll: true })
  }, [id])

  const close = React.useCallback(() => {
    set({ post: null })
    // The page behind may still be inert; focus cannot land on it until that is lifted.
    const behind = document.getElementById("shell-body")
    if (behind) behind.inert = false
    const opener = takeOpener()
    if (opener && document.contains(opener)) {
      opener.focus({ preventScroll: true })
    } else if (back) {
      // The queue row that opened it is redrawn as the queue returns: focus it once it is there.
      focusPostLater(id, "[data-inspector-rail]")
    } else if (document.querySelector(`button[data-post-id="${id}"]`)) {
      // The calendar re-lays itself out when the panel closes; focus the post once it has.
      focusPostLater(id)
    } else {
      const heading = document.querySelector<HTMLElement>("h1")
      if (heading) {
        if (!heading.hasAttribute("tabindex")) heading.tabIndex = -1
        heading.focus({ preventScroll: true })
      }
    }
  }, [set, id, back])

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Esc inside a confirm dialog closes only the dialog, never the panel behind it.
      const inDialog = e.target instanceof Element && e.target.closest('[role="dialog"], [role="alertdialog"]')
      // Nor while a popover or menu (Filters, theme) is open: Esc closes that first.
      const floating = document.querySelector("[data-slot='popover-content'][data-open], [data-slot='dropdown-menu-content'][data-open]")
      if (e.key === "Escape" && !e.defaultPrevented && !inDialog && !floating) close()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [close])

  return (
    <aside
      ref={root}
      aria-labelledby="panel-title"
      data-post-panel={id}
      data-inspector-rail={rail ? "detail" : undefined}
      className={cn(
        rail
          ? railFrame(beside)
          : cn(
              // scroll-pb keeps a focused control clear of the notice card at the bottom right (WCAG 2.4.11).
              "glass scroll-pb-32 fixed top-(--shell-top) right-0 bottom-0 z-40 w-[min(34rem,100vw)] overflow-y-auto overscroll-contain",
              "min-[1200px]:sticky min-[1200px]:z-10 min-[1200px]:h-[calc(100svh-var(--shell-top))] min-[1200px]:w-[30rem] min-[1200px]:shrink-0 min-[1200px]:self-start"
            )
      )}
    >
      {/* pb-32: the last rows can scroll clear of the notice card at the bottom right (2.4.11). */}
      <div className={cn("flex flex-col gap-7", rail ? "p-4" : "p-6", "pb-32")}>
        {back && (
          <button
            type="button"
            data-rail-back
            onClick={close}
            className="press -mb-3 inline-flex h-10 items-center gap-1 self-start rounded-full border border-control bg-surface pr-4 pl-2 text-sm hover:bg-muted"
          >
            <ChevronLeft aria-hidden="true" strokeWidth={1.5} className="size-5" />
            <span className="sr-only">Back to </span>
            Needs you
            {queue.total ? (
              <span className="ml-1 text-label tabular-nums">
                {queue.total}
                <span className="sr-only"> waiting</span>
              </span>
            ) : null}
          </button>
        )}
        <div className="flex items-start justify-between gap-3">
          <h2
            id="panel-title"
            ref={heading}
            tabIndex={-1}
            // Focus lands here when the panel opens (tabindex=-1, never in the Tab order). It is
            // not a control, so it shows no ring: Chromium counts focus on a deep link as
            // :focus-visible, and any ring around a short title reads as a button. Keyboard focus
            // on every control keeps the global ring.
            className={cn(
              "leading-tight tracking-tight outline-none focus:outline-none focus-visible:outline-none",
              rail ? "px-1 text-2xl font-light" : "text-2xl"
            )}
          >
            {title}
          </h2>
          {!back && (
            <button
              type="button"
              onClick={close}
              aria-label="Close panel"
              className="press inline-flex size-10 shrink-0 items-center justify-center rounded-full border border-control bg-surface hover:bg-muted"
            >
              <X aria-hidden="true" strokeWidth={1.5} className="size-5" />
            </button>
          )}
        </div>
        {banner && (
          <div
            role="alert"
            data-stale-banner
            className="flex gap-3 rounded-inner bg-st-awaiting p-4 text-sm text-st-awaiting-ink"
          >
            <TriangleAlert aria-hidden="true" strokeWidth={1.5} className="mt-0.5 size-5 shrink-0" />
            <p>{banner}</p>
          </div>
        )}
        {state.state === "loading" || schema.state !== "ok" ? (
          <div role="status" aria-busy="true" aria-label="Loading the post" className="flex flex-col gap-4">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="h-24 w-full rounded-control" />
            <Skeleton className="h-6 w-1/2" />
          </div>
        ) : state.state === "error" ? (
          <ErrorPanel error={state.refusal} />
        ) : (
          <Body data={state.data} schema={schema.data} host={host} />
        )}
      </div>
    </aside>
  )
}

function Host() {
  const { params } = useUrlState()
  const id = params.get("post")
  const { onCalendar: rail, beside } = useRail()
  const sheet = rail && !beside && params.get("queue") === "1"

  // As a sheet (the panel below 1200 px, the calendar's queue below 1180 px) everything behind is
  // inert. As a column beside the content, the content stays usable.
  React.useEffect(() => {
    const body = document.getElementById("shell-body")
    if (!body) return
    body.inert = (Boolean(id) || sheet) && !beside
    return () => {
      body.inert = false
    }
  }, [id, sheet, beside])

  // On the calendar the rail is always there from 1180 px: the queue, or the open post.
  // Keyed by post: another post starts with a clean banner and no pending focus.
  if (id) return <Panel key={id} id={id} rail={rail} beside={beside} />
  if (rail && (beside || sheet)) return <QueueRail beside={beside} />
  return null
}

/** The side panel of the open post (`?post=ID`), shown from any view. */
export function PostPanel() {
  return (
    <Suspense fallback={null}>
      <Host />
    </Suspense>
  )
}

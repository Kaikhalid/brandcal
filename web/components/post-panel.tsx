"use client"

import { Check, Copy, TriangleAlert, X } from "lucide-react"
import * as React from "react"
import { Suspense } from "react"

import { useAppData, type Loadable } from "@/components/app-data"
import { ErrorPanel } from "@/components/error-panel"
import { PlatformBadge } from "@/components/platform-swatch"
import { PostBadges, TypeTag, takeOpener, words } from "@/components/post-bits"
import { StatusChip } from "@/components/status-chip"
import { Skeleton } from "@/components/ui/skeleton"
import { useMedia } from "@/components/use-media"
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
import { dayLabel, fullTime, spanOf } from "@/lib/time"
import { useUrlState } from "@/lib/url-state"
import { cn } from "@/lib/utils"

type Data = { post: PostDetail; events: EventRow[]; versions: Version[] }

function usePanelData(id: string): Loadable<Data> {
  // The answer is kept with the post it belongs to; another post reads as loading.
  const [answer, setAnswer] = React.useState<{ id: string; state: Loadable<Data> } | null>(null)
  React.useEffect(() => {
    let live = true
    Promise.all([getPost(id), getEvents({ post: id }), getVersions(id)]).then(([post, ev, vs]) => {
      if (!live) return
      const failed = [post, ev, vs].find((r) => !r.ok)
      const state: Loadable<Data> =
        failed && !failed.ok
          ? { state: "error", refusal: failed.refusal }
          : post.ok && ev.ok && vs.ok
            ? { state: "ok", data: { post: post.data, events: ev.data.events, versions: vs.data.versions } }
            : { state: "loading" }
      setAnswer({ id, state })
    })
    return () => {
      live = false
    }
  }, [id])
  return answer?.id === id ? answer.state : { state: "loading" }
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
        className="press inline-flex min-h-8 items-center gap-2 rounded-control border border-control px-2.5 font-mono text-xs hover:bg-muted"
      >
        {hash.slice(0, 8)}
        <Copy aria-hidden="true" strokeWidth={1.5} className="size-4" />
      </button>
      <span role="status" className="text-xs text-label">
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
        <p className="text-xs text-label tabular-nums">
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
    <Section title="Version history">
      <p className="text-sm">
        Now version {post.content_version}, fingerprint{" "}
        <code className="font-mono">{post.content_hash.slice(0, 8)}</code>
      </p>
      <ul className="flex flex-col gap-2 text-sm">
        {changes.map((e) => (
          <li key={e.id}>
            {words(e.action)} by {e.actor}
            <span className="block text-xs text-label tabular-nums">{fullTime(e.at, zone)}</span>
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
                <span className="block text-xs text-label tabular-nums">
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
    </Section>
  )
}

const flat = (v: Version) => [
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
      <Section title="Compare versions">
        <p className="text-sm text-label">Only one version exists, so there is nothing to compare.</p>
      </Section>
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
    <Section title="Compare versions">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <select aria-label="Compare from" value={from} onChange={(e) => setFrom(e.target.value)} className={select}>
          {options}
        </select>
        <span className="text-label">to</span>
        <select aria-label="Compare to" value={to} onChange={(e) => setTo(e.target.value)} className={select}>
          {options}
        </select>
      </div>
      <pre aria-live="polite" data-diff className="overflow-x-auto rounded-control bg-muted py-2 font-mono text-xs leading-relaxed">
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
    </Section>
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
    <Section title="Audit trail">
      <ol className="flex flex-col gap-3 text-sm">
        {events.map((e) => {
          const tag = identityTag(e.detail)
          return (
            <li key={e.id}>
              <strong className="font-medium">{words(e.action)}</strong> by {e.actor}
              {e.from_status && e.to_status && e.from_status !== e.to_status
                ? `: ${words(e.from_status)} to ${words(e.to_status)}`
                : ""}
              <span className="block text-xs text-label tabular-nums">
                {fullTime(e.at, zone)}
                {tag ? `, ${tag}` : ""}
              </span>
              {e.reason && <span className="block">{e.reason}</span>}
            </li>
          )
        })}
      </ol>
    </Section>
  )
}

function Actions({ post }: { post: PostDetail }) {
  const all = [...post.actions, post.note].filter((a): a is PostAction => a !== null)
  return (
    <Section title="Actions">
      {all.length === 0 ? (
        <p className="text-sm text-label">This post is closed, so there is nothing to do.</p>
      ) : (
        <ul className="flex flex-col gap-4">
          {all.map((a) => (
            <li key={a.id} data-action={a.id} data-enabled={a.enabled} className="flex flex-col gap-2 rounded-control bg-muted p-3 text-sm">
              <span className="flex items-center gap-2 font-medium">
                {a.enabled ? (
                  <Check aria-hidden="true" strokeWidth={1.5} className="size-4" />
                ) : (
                  <X aria-hidden="true" strokeWidth={1.5} className="size-4" />
                )}
                {a.label}
                <span className="font-normal text-label">{a.enabled ? "Possible now" : "Not possible now"}</span>
              </span>
              {a.warning && a.id === "edit" && <p className="text-label">{a.warning}</p>}
              {a.refusal && <ErrorPanel error={a.refusal} blocking={false} className="shadow-none" />}
              <p className="text-xs text-label">Agent equivalent (CLI)</p>
              <code className="rounded-control bg-surface px-2 py-1.5 font-mono text-xs break-words">{a.cli}</code>
            </li>
          ))}
        </ul>
      )}
    </Section>
  )
}

function Body({ data, schema }: { data: Data; schema: Schema }) {
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
      <Rows
        rows={[
          ["Post", <code key="p" className="font-mono">{post.id}</code>],
          ["Slug", <code key="s" className="font-mono">{post.slug}</code>],
          ["When", w && `${dayLabel(w.day)}, ${w.text}`],
          ["Window", post.window && <code key="w" className="font-mono break-all">{post.window}</code>],
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
      <Actions post={post} />
    </div>
  )
}

function Panel({ id }: { id: string }) {
  const { schema } = useAppData()
  const { set } = useUrlState()
  const state = usePanelData(id)
  const heading = React.useRef<HTMLHeadingElement>(null)
  const title = state.state === "ok" ? state.data.post.title : "Post"

  // Focus moves into the panel when it opens or switches post.
  React.useEffect(() => {
    heading.current?.focus({ preventScroll: true })
  }, [id])

  const close = React.useCallback(() => {
    set({ post: null })
    // The page behind may still be inert; focus cannot land on it until that is lifted.
    const behind = document.getElementById("shell-body")
    if (behind) behind.inert = false
    const back = takeOpener()
    const target =
      back && document.contains(back) ? back : document.querySelector<HTMLElement>("main h1")
    if (target) {
      if (!target.hasAttribute("tabindex") && target.tagName === "H1") target.tabIndex = -1
      target.focus({ preventScroll: true })
    }
  }, [set])

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) close()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [close])

  return (
    <aside
      aria-labelledby="panel-title"
      data-post-panel={id}
      className={cn(
        "glass fixed top-(--shell-top) right-0 bottom-0 z-40 w-[min(34rem,100vw)] overflow-y-auto overscroll-contain",
        "min-[1200px]:sticky min-[1200px]:z-10 min-[1200px]:h-[calc(100svh-var(--shell-top))] min-[1200px]:w-[30rem] min-[1200px]:shrink-0 min-[1200px]:self-start"
      )}
    >
      <div className="flex flex-col gap-7 p-6">
        <div className="flex items-start justify-between gap-3">
          <h2
            id="panel-title"
            ref={heading}
            tabIndex={-1}
            className="rounded-control text-2xl leading-tight tracking-tight"
          >
            {title}
          </h2>
          <button
            type="button"
            onClick={close}
            aria-label="Close panel"
            className="press inline-flex size-10 shrink-0 items-center justify-center rounded-full border border-control bg-surface hover:bg-muted"
          >
            <X aria-hidden="true" strokeWidth={1.5} className="size-5" />
          </button>
        </div>
        {state.state === "loading" || schema.state !== "ok" ? (
          <div role="status" aria-busy="true" aria-label="Loading the post" className="flex flex-col gap-4">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="h-24 w-full rounded-control" />
            <Skeleton className="h-6 w-1/2" />
          </div>
        ) : state.state === "error" ? (
          <ErrorPanel error={state.refusal} />
        ) : (
          <Body data={state.data} schema={schema.data} />
        )}
      </div>
    </aside>
  )
}

function Host() {
  const { params } = useUrlState()
  const id = params.get("post")
  const beside = useMedia("(min-width: 1200px)")

  // Below 1200px the panel overlays, so everything behind it is inert. From 1200px it sits beside
  // the content, which stays usable.
  React.useEffect(() => {
    const body = document.getElementById("shell-body")
    if (!body) return
    body.inert = Boolean(id) && !beside
    return () => {
      body.inert = false
    }
  }, [id, beside])

  return id ? <Panel id={id} /> : null
}

/** The side panel of the open post (`?post=ID`), shown from any view. */
export function PostPanel() {
  return (
    <Suspense fallback={null}>
      <Host />
    </Suspense>
  )
}

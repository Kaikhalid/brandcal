"use client"

import { ArrowDown, ArrowUp, FileText } from "lucide-react"
import * as React from "react"

import { EmptyState } from "@/components/empty-state"
import { ErrorPanel } from "@/components/error-panel"
import { FiltersBar } from "@/components/filters-bar"
import { LoadingState } from "@/components/loading-state"
import { PlatformBadge } from "@/components/platform-swatch"
import { TypeTag, useOpenPost } from "@/components/post-bits"
import { PageHeading } from "@/components/route-page"
import { StatusChip } from "@/components/status-chip"
import { usePostItems } from "@/components/use-post-items"
import { ViewGate } from "@/components/view-gate"
import type { Schema } from "@/lib/api"
import { fullTime } from "@/lib/time"
import { FILTER_KEYS, applyFilters, parseFilters, useUrlState } from "@/lib/url-state"

const startOf = (window: string | null) => (window ? Date.parse(window.split("/")[0]) : 0)

function Table({ schema }: { schema: Schema }) {
  const { params, set } = useUrlState()
  const items = usePostItems()
  const open = useOpenPost()
  const desc = params.get("sort") === "-window"
  const current = params.get("post")

  const rows = React.useMemo(() => {
    if (items.state !== "ok") return []
    const kept = applyFilters(items.data, parseFilters(params), schema, false)
    return kept.sort((a, b) => (startOf(a.row.window) - startOf(b.row.window)) * (desc ? -1 : 1))
  }, [items, params, schema, desc])

  if (items.state === "loading") return <LoadingState label="Loading posts" rows={5} />
  if (items.state === "error") return <ErrorPanel error={items.refusal} />
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={FileText}
        line={
          FILTER_KEYS.some((key) => params.get(key))
            ? "No posts match these filters."
            : "No posts yet. Agents add posts through the CLI."
        }
        command="brandcal add --as NAME ..."
      />
    )
  }
  const SortIcon = desc ? ArrowDown : ArrowUp
  const head = "px-5 py-3 text-left text-sm font-normal text-label"
  return (
    <div
      role="region"
      aria-label="Posts"
      tabIndex={0}
      className="card-surface relative overflow-x-auto"
    >
      <table className="w-full min-w-[56rem] border-collapse">
        <caption className="sr-only">
          {rows.length} posts, sorted by window, {desc ? "latest" : "earliest"} first
        </caption>
        <thead>
          <tr className="border-b border-hairline">
            <th scope="col" className={head}>
              Title
            </th>
            <th scope="col" className={head}>
              Platform
            </th>
            <th scope="col" className={head}>
              Type
            </th>
            <th scope="col" className={head}>
              Status
            </th>
            <th scope="col" className={head} aria-sort={desc ? "descending" : "ascending"}>
              <button
                type="button"
                onClick={() => set({ sort: desc ? null : "-window" })}
                className="press -mx-2 inline-flex min-h-8 items-center gap-1.5 rounded-control px-2 hover:bg-muted hover:text-ink"
              >
                Window
                <SortIcon aria-hidden="true" strokeWidth={1.5} className="size-4" />
                <span className="sr-only">
                  , sorted {desc ? "latest" : "earliest"} first. Activate to reverse.
                </span>
              </button>
            </th>
            <th scope="col" className={`${head} text-right`}>
              Version
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ row, detail }) => (
            <tr
              key={row.id}
              data-post-id={row.id}
              data-current={current === row.id}
              className="border-b border-hairline last:border-b-0 data-[current=true]:bg-muted"
            >
              <th scope="row" className="max-w-80 px-5 py-3 text-left font-normal">
                <button
                  type="button"
                  title={row.window ?? undefined}
                  aria-current={current === row.id ? "true" : undefined}
                  onClick={(e) => open(row.id, e.currentTarget)}
                  className="press -mx-2 flex min-h-10 flex-col rounded-control px-2 text-left hover:bg-muted"
                >
                  <span>{row.title}</span>
                  <span className="font-mono text-xs text-label">{detail.slug}</span>
                </button>
              </th>
              <td className="px-5 py-3">
                <PlatformBadge platform={row.platform} />
              </td>
              <td className="px-5 py-3">
                <TypeTag type={detail.post_type} />
              </td>
              <td className="px-5 py-3">
                <StatusChip status={row.status} />
              </td>
              <td
                className="px-5 py-3 text-sm whitespace-nowrap tabular-nums"
                title={row.window ?? undefined}
              >
                {row.window ? windowText(row.window, schema.timezone) : "No window"}
              </td>
              <td className="px-5 py-3 text-right tabular-nums">v{detail.content_version}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function windowText(window: string, zone: string | null): string {
  const [start, end] = window.split("/")
  return `${fullTime(start, zone)} to ${fullTime(end ?? start, zone).slice(-5)}`
}

export function PostsView() {
  return (
    <div className="flex flex-col gap-8">
      <PageHeading
        title="Posts"
        description="Every post, with its status, platform and window."
      />
      <ViewGate label="Loading posts" rows={5}>
        {(schema) => (
          <>
            <FiltersBar closedByDefault={false} />
            <Table schema={schema} />
          </>
        )}
      </ViewGate>
    </div>
  )
}

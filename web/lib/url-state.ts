"use client"

import { useSearchParams } from "next/navigation"
import * as React from "react"

import type { PostDetail, PostRow, Schema } from "@/lib/api"

// The state of a view lives in the address, so it can be shared and back/forward work. Next
// listens to history.pushState / replaceState and re-renders useSearchParams (single-page-apps
// guide), so there is no router round trip: this is a static export with nothing to fetch.
export function useUrlState() {
  const params = useSearchParams()
  const set = React.useCallback((patch: Record<string, string | null>, mode: "push" | "replace" = "push") => {
    const next = new URLSearchParams(window.location.search)
    for (const [key, value] of Object.entries(patch)) {
      if (value === null || value === "") next.delete(key)
      else next.set(key, value)
    }
    const text = next.toString()
    const url = `${window.location.pathname}${text ? `?${text}` : ""}`
    if (mode === "push") window.history.pushState(null, "", url)
    else window.history.replaceState(null, "", url)
  }, [])
  return { params, set }
}

/** The filters both the Calendar and Posts share. `closed` is null when the URL does not say. */
export type Filters = {
  status: string[]
  platform: string[]
  type: string
  campaign: string
  pillar: string
  closed: boolean | null
  q: string
}

const list = (text: string | null) => (text ?? "").split(",").filter(Boolean)

export function parseFilters(params: URLSearchParams): Filters {
  const closed = params.get("closed")
  return {
    status: list(params.get("status")),
    platform: list(params.get("platform")),
    type: params.get("type") ?? "",
    campaign: params.get("campaign") ?? "",
    pillar: params.get("pillar") ?? "",
    closed: closed === "1" ? true : closed === "0" ? false : null,
    q: params.get("q") ?? "",
  }
}

export const FILTER_KEYS = ["status", "platform", "type", "campaign", "pillar", "closed", "q"]

/** How many of the filters hidden behind "More filters" are set. */
export function moreCount(f: Filters): number {
  return [f.type, f.campaign, f.pillar, f.q].filter(Boolean).length + (f.closed === null ? 0 : 1)
}

export type PostItem = { row: PostRow; detail: PostDetail }

/** Apply the filters. `closedByDefault`: whether posts in a closed state show when the URL says
 *  nothing (the Calendar shows what went out; the Posts list hides it until asked). Picking a
 *  closed status as a filter shows it either way. */
export function applyFilters(
  items: PostItem[],
  f: Filters,
  schema: Schema,
  closedByDefault: boolean
): PostItem[] {
  const closedOn = f.closed ?? closedByDefault
  const slug = f.q.trim().toLowerCase()
  return items.filter(({ row, detail }) => {
    if (f.status.length && !f.status.includes(row.status)) return false
    if (!f.status.length && !closedOn && schema.closed_states.includes(row.status)) return false
    if (f.platform.length && !f.platform.includes(row.platform)) return false
    if (f.type && detail.post_type !== f.type) return false
    if (f.campaign && detail.campaign !== f.campaign) return false
    if (f.pillar && detail.pillar !== f.pillar) return false
    if (slug && !`${detail.slug} ${row.id}`.toLowerCase().includes(slug)) return false
    return true
  })
}

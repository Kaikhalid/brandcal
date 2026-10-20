"use client"

import * as React from "react"

import { useAppData, type Loadable } from "@/components/app-data"
import { getPost, getPosts } from "@/lib/api"
import type { PostItem } from "@/lib/url-state"

/** The posts in a date range (all of them when none is given), each with its full detail: the
 *  list rows carry no type, campaign or badges, and the MVP fetched the detail of every post too.
 *  Closed posts are always fetched; the views decide whether to show them. */
export function usePostItems(from?: string, to?: string): Loadable<PostItem[]> {
  // The answer is kept with the range it belongs to; another range reads as loading.
  const key = `${from ?? ""}/${to ?? ""}`
  const { epoch } = useAppData()
  const [answer, setAnswer] = React.useState<{ key: string; state: Loadable<PostItem[]> } | null>(null)

  React.useEffect(() => {
    let live = true
    async function load() {
      const list = await getPosts({ from, to, closed: true })
      if (!list.ok) return { state: "error", refusal: list.refusal } as const
      const details = await Promise.all(list.data.posts.map((row) => getPost(row.id)))
      const items: PostItem[] = []
      for (const [i, detail] of details.entries()) {
        if (!detail.ok) return { state: "error", refusal: detail.refusal } as const
        items.push({ row: list.data.posts[i], detail: detail.data })
      }
      return { state: "ok", data: items } as const
    }
    load().then((state) => live && setAnswer({ key, state }))
    return () => {
      live = false
    }
    // A write bumps epoch: read again, and keep showing the old answer until the new one is in.
  }, [from, to, key, epoch])

  return answer?.key === key ? answer.state : { state: "loading" }
}

"use client"

import * as React from "react"

import { useAppData, type Loadable } from "@/components/app-data"
import { byUrgency, loadNeedsYou, needsTotal, queuePosts, type NeedsGroup } from "@/lib/needs-you"

// The Needs you queue, read once for the whole shell: the inspector rail lists it, the post
// detail in the rail counts it and advances along it, and the toolbar button shows its size. It
// reads again after every write (epoch), like the sidebar badge, which uses the same rule.
const QueueContext = React.createContext<Loadable<NeedsGroup[]>>({ state: "loading" })

export function NeedsQueueProvider({ children }: { children: React.ReactNode }) {
  const { schema, epoch } = useAppData()
  const rules = schema.state === "ok" ? schema.data : null
  const [state, setState] = React.useState<Loadable<NeedsGroup[]>>({ state: "loading" })
  React.useEffect(() => {
    if (!rules) return
    let live = true
    loadNeedsYou(rules).then((r) => {
      if (live) setState(r.ok ? { state: "ok", data: byUrgency(r.groups) } : { state: "error", refusal: r.refusal })
    })
    return () => {
      live = false
    }
  }, [rules, epoch])
  return <QueueContext.Provider value={state}>{children}</QueueContext.Provider>
}

export function useNeedsQueue() {
  const state = React.useContext(QueueContext)
  const groups = state.state === "ok" ? state.data : []
  return {
    state,
    groups,
    posts: queuePosts(groups),
    total: state.state === "ok" ? needsTotal(groups) : null,
  }
}

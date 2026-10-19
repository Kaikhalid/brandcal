"use client"

import * as React from "react"

import {
  getPosts,
  getSchema,
  getSession,
  type BrandcalRefusal,
  type Schema,
  type Session,
} from "@/lib/api"

// What every page shares: who is asking (GET /api/session), the rules (GET /api/schema) and how
// many posts need the viewer. All of it is read from the server on load; nothing is kept in the
// browser, so an agent reading the API sees exactly what the person sees.
export type Loadable<T> =
  | { state: "loading" }
  | { state: "ok"; data: T }
  | { state: "error"; refusal: BrandcalRefusal }

type AppData = {
  session: Loadable<Session>
  schema: Loadable<Schema>
  /** Posts in the statuses that need the viewer (schema.needs_you), as the MVP strip counts them. */
  needsYou: Loadable<number>
}

const LOADING: AppData = {
  session: { state: "loading" },
  schema: { state: "loading" },
  needsYou: { state: "loading" },
}

const AppDataContext = React.createContext<AppData>(LOADING)

export const useAppData = () => React.useContext(AppDataContext)

async function loadNeedsYou(schema: Schema): Promise<Loadable<number>> {
  const wanted = schema.needs_you.filter((s) => schema.states.includes(s))
  const lists = await Promise.all(wanted.map((status) => getPosts({ status })))
  let count = 0
  for (const list of lists) {
    if (!list.ok) return { state: "error", refusal: list.refusal }
    count += list.data.posts.length
  }
  return { state: "ok", data: count }
}

function AppDataProvider({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<AppData>(LOADING)

  React.useEffect(() => {
    let live = true
    const patch = (next: Partial<AppData>) => live && setData((prev) => ({ ...prev, ...next }))
    getSession().then((r) =>
      patch({ session: r.ok ? { state: "ok", data: r.data } : { state: "error", refusal: r.refusal } })
    )
    getSchema().then(async (r) => {
      if (!r.ok) return patch({ schema: { state: "error", refusal: r.refusal }, needsYou: { state: "error", refusal: r.refusal } })
      patch({ schema: { state: "ok", data: r.data } })
      patch({ needsYou: await loadNeedsYou(r.data) })
    })
    return () => {
      live = false
    }
  }, [])

  return <AppDataContext.Provider value={data}>{children}</AppDataContext.Provider>
}

export { AppDataProvider }

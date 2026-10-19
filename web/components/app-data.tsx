"use client"

import * as React from "react"

import {
  getSchema,
  getSession,
  type BrandcalRefusal,
  type Schema,
  type Session,
} from "@/lib/api"
import { loadNeedsYou, needsTotal } from "@/lib/needs-you"

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

async function loadNeedsCount(schema: Schema): Promise<Loadable<number>> {
  const result = await loadNeedsYou(schema)
  return result.ok
    ? { state: "ok", data: needsTotal(result.groups) }
    : { state: "error", refusal: result.refusal }
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
      patch({ needsYou: await loadNeedsCount(r.data) })
    })
    return () => {
      live = false
    }
  }, [])

  return <AppDataContext.Provider value={data}>{children}</AppDataContext.Provider>
}

export { AppDataProvider }

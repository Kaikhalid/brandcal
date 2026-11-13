"use client"

import * as React from "react"

import { useAppData } from "@/components/app-data"
import { ErrorPanel } from "@/components/error-panel"
import { LoadingState } from "@/components/loading-state"
import type { BrandcalRefusal, Schema, Session } from "@/lib/api"

/** Holds a view back until the session and the rules (schema) are known. Their refusal, if any,
 *  is shown verbatim; until then, skeletons in the shape of the page. */
export function ViewGate({
  label,
  rows,
  children,
}: {
  label: string
  rows?: number
  children: (schema: Schema, session: Session) => React.ReactNode
}) {
  const { session, schema } = useAppData()
  const refusal =
    session.state === "error" ? session.refusal : schema.state === "error" ? schema.refusal : null
  if (refusal) return <ErrorPanel error={refusal} />
  if (session.state !== "ok" || schema.state !== "ok") return <LoadingState label={label} rows={rows} />
  return <>{children(schema.data, session.data)}</>
}

/** A big, light, tabular figure with a small grey label. */
export function Figure({ value, label }: { value: React.ReactNode; label: string }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="figure">{value}</span>
      <span className="text-sm text-label">{label}</span>
    </div>
  )
}

/** The refusal of a data load, or null. */
export function refusalOf(...states: { state: string; refusal?: BrandcalRefusal }[]) {
  return states.find((s) => s.state === "error")?.refusal ?? null
}

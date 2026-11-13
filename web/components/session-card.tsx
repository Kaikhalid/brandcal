"use client"

import { useAppData } from "@/components/app-data"
import { ErrorPanel } from "@/components/error-panel"
import { LoadingState } from "@/components/loading-state"

// GET /api/session as the shared app data shows it: who is signed in, with what role, and from
// where the identity came (a Cloudflare Access JWT, or the read-only development session).
function SessionCard() {
  const { session } = useAppData()

  if (session.state === "loading") return <LoadingState label="Checking who is signed in" rows={1} />
  if (session.state === "error") return <ErrorPanel error={session.refusal} />

  const { identity, role, source } = session.data
  return (
    <div className="card-surface p-2">
      <div className="rounded-inner bg-canvas p-5">
        <p className="text-sm text-label">Signed in as</p>
        <p className="figure mt-2 capitalize">{role}</p>
        <p className="mt-3 text-sm">
          {identity ?? "No verified identity (read-only development session)"}
        </p>
        <p className="mt-1 text-sm text-label">Source: {source}</p>
      </div>
    </div>
  )
}

export { SessionCard }

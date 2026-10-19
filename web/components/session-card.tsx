"use client"

import { useEffect, useState } from "react"

import { StatusChip } from "@/components/status-chip"

type Refusal = { code: string; message: string; next: string }
type State =
  | { kind: "loading" }
  | { kind: "ok"; identity: string | null; role: string; source: string }
  | { kind: "error"; error: Refusal }

const UNREACHABLE: Refusal = {
  code: "NETWORK_ERROR",
  message: "The page could not reach the brandcal server.",
  next: "Check that brandcal serve is running, then reload this page.",
}

// GET /api/session: who the server thinks is asking, or its refusal in the CLI's shape.
async function loadSession(signal: AbortSignal): Promise<State> {
  try {
    const res = await fetch("/api/session", { credentials: "same-origin", signal })
    const body: unknown = await res.json()
    const data = (body ?? {}) as Record<string, unknown>
    if (data.ok === true && typeof data.role === "string") {
      return {
        kind: "ok",
        identity: typeof data.identity === "string" ? data.identity : null,
        role: data.role,
        source: String(data.source ?? ""),
      }
    }
    const error = (data.error ?? {}) as Partial<Refusal>
    return {
      kind: "error",
      error: {
        code: error.code ?? "UNEXPECTED_ANSWER",
        message: error.message ?? "The server answered, but not with a session.",
        next: error.next ?? "Reload the page; if it persists, ask the admin to check the server.",
      },
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err
    return { kind: "error", error: UNREACHABLE }
  }
}

function SessionCard() {
  const [state, setState] = useState<State>({ kind: "loading" })

  useEffect(() => {
    const controller = new AbortController()
    loadSession(controller.signal).then(setState, () => undefined)
    return () => controller.abort()
  }, [])

  return (
    <div className="card-surface p-2">
      <div className="rounded-inner bg-canvas p-5" aria-live="polite">
        {state.kind === "loading" && <p className="text-label">Checking who is signed in…</p>}
        {state.kind === "ok" && (
          <>
            <p className="text-sm text-label">Signed in as</p>
            <p className="figure mt-2 capitalize">{state.role}</p>
            <p className="mt-3 text-sm">
              {state.identity ?? "No verified identity (read-only development session)"}
            </p>
            <p className="mt-1 text-sm text-label">Source: {state.source}</p>
          </>
        )}
        {state.kind === "error" && (
          <div role="alert">
            <StatusChip status="failed" />
            <p className="mt-3 font-mono text-sm">{state.error.code}</p>
            <p className="mt-1">{state.error.message}</p>
            <p className="mt-1 text-sm text-label">Next: {state.error.next}</p>
          </div>
        )}
      </div>
    </div>
  )
}

export { SessionCard }

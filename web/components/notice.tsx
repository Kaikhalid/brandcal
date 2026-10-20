"use client"

import { Check, X } from "lucide-react"
import * as React from "react"

import { cn } from "@/lib/utils"

// A notice is one short sentence after a write ("Approve: done. ..."). No library: one polite live
// region, mounted once in the shell and always present (a live region only announces text that
// changes inside an element that already exists). The card stays until it is dismissed, replaced
// or 8 seconds pass; hovering it or focusing inside it pauses the clock.
const SHOWN_MS = 8000

type Notify = (text: string) => void

const NoticeContext = React.createContext<Notify>(() => undefined)

export const useNotice = () => React.useContext(NoticeContext)

function NoticeProvider({ children }: { children: React.ReactNode }) {
  // `n` makes the same sentence twice in a row a new notice, so its clock restarts.
  const [notice, setNotice] = React.useState<{ n: number; text: string } | null>(null)
  const [paused, setPaused] = React.useState(false)
  const notify = React.useCallback<Notify>((text) => setNotice((prev) => ({ n: (prev?.n ?? 0) + 1, text })), [])

  React.useEffect(() => {
    if (!notice || paused) return
    const timer = window.setTimeout(() => setNotice(null), SHOWN_MS)
    return () => window.clearTimeout(timer)
  }, [notice, paused])

  return (
    <NoticeContext.Provider value={notify}>
      {children}
      <div
        className="pointer-events-none fixed right-6 bottom-6 z-[70] flex max-w-[min(26rem,calc(100vw-3rem))] justify-end"
        data-notice-host
      >
        <div
          onMouseEnter={() => setPaused(true)}
          onMouseLeave={() => setPaused(false)}
          onFocus={() => setPaused(true)}
          onBlur={() => setPaused(false)}
          data-open={notice ? "true" : "false"}
          // Closed, the card is clipped (sr-only), not display:none, so the live region stays in the
          // accessibility tree and its next text is announced.
          className={cn(
            "flex items-start gap-3 rounded-inner bg-surface p-4 text-sm shadow-float",
            notice
              ? "pointer-events-auto transition-[opacity,translate] duration-(--dur-base) ease-(--ease-out) starting:translate-y-2 starting:opacity-0"
              : "sr-only"
          )}
        >
          <Check aria-hidden="true" strokeWidth={1.5} className="mt-0.5 size-5 shrink-0" />
          {/* Always mounted; the text is what changes. */}
          <p role="status" aria-live="polite" data-notice className="min-w-0 flex-1 break-words">
            {notice?.text}
          </p>
          <button
            type="button"
            onClick={() => setNotice(null)}
            hidden={!notice}
            aria-label="Dismiss notice"
            className="press -m-1 inline-flex size-10 shrink-0 items-center justify-center rounded-full hover:bg-muted"
          >
            <X aria-hidden="true" strokeWidth={1.5} className="size-5" />
          </button>
        </div>
      </div>
    </NoticeContext.Provider>
  )
}

export { NoticeProvider }

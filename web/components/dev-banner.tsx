"use client"

import { ShieldAlert } from "lucide-react"
import * as React from "react"

import { useAppData } from "@/components/app-data"

// `brandcal serve --dev-unverified` has no verified identity, so it can never write (UI_SPEC
// 2.5). The red banner is permanent: no close button, no storage. Its height is published as
// --shell-top so the fixed sidebar and the sticky shell bar start below it.
function DevBanner() {
  const { session } = useAppData()
  const unverified = session.state === "ok" && session.data.source === "dev-unverified"
  const ref = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    const el = ref.current
    if (!unverified || !el) return
    const root = document.documentElement
    const publish = () => root.style.setProperty("--shell-top", `${el.offsetHeight}px`)
    publish()
    const observer = new ResizeObserver(publish)
    observer.observe(el)
    return () => {
      observer.disconnect()
      root.style.removeProperty("--shell-top")
    }
  }, [unverified])

  if (!unverified) return null
  return (
    <div
      ref={ref}
      role="status"
      data-dev-banner
      className="sticky top-0 z-50 flex items-center justify-center gap-3 bg-banner px-4 py-2 text-center text-sm text-banner-foreground"
    >
      <ShieldAlert aria-hidden="true" strokeWidth={1.5} className="size-5 shrink-0" />
      <p>
        This session is unverified and read-only; every write returns{" "}
        <code className="font-mono">IDENTITY_UNVERIFIED</code>.
      </p>
    </div>
  )
}

export { DevBanner }

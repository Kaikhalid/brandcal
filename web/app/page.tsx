import { ArrowRight } from "lucide-react"

import { PlatformSwatch, PLATFORMS } from "@/components/platform-swatch"
import { SessionCard } from "@/components/session-card"
import { StatusChip, STATUSES } from "@/components/status-chip"
import { ThemeToggle } from "@/components/theme-toggle"
import { Button } from "@/components/ui/button"

// Foundations only (N0): the tokens, the chips and the session call, end to end under the CSP.
// The shell (N1), read views (N2) and writes (N3) come later.
export default function Page() {
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-14 px-6 py-16">
      <header className="flex items-start justify-between gap-6">
        <div>
          <h1 className="text-5xl tracking-tight">brandcal</h1>
          <p className="mt-3 text-label">Foundations preview. Views come next.</p>
        </div>
        <ThemeToggle />
      </header>

      <section aria-labelledby="who" className="flex flex-col gap-4">
        <h2 id="who" className="text-xl">
          Session
        </h2>
        <SessionCard />
      </section>

      <section aria-labelledby="status" className="flex flex-col gap-4">
        <h2 id="status" className="text-xl">
          Status
        </h2>
        <ul className="flex flex-wrap gap-3">
          {STATUSES.map((s) => (
            <li key={s}>
              <StatusChip status={s} />
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="platforms" className="flex flex-col gap-4">
        <h2 id="platforms" className="text-xl">
          Platforms
        </h2>
        <ul className="flex flex-wrap gap-3">
          {PLATFORMS.map((p) => (
            <li key={p}>
              <PlatformSwatch platform={p} />
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="primary" className="flex flex-col gap-4">
        <h2 id="primary" className="text-xl">
          Primary action
        </h2>
        <div>
          <Button className="h-10 rounded-full pr-4 pl-5 text-sm" type="button">
            Review posts
            <ArrowRight aria-hidden="true" strokeWidth={1.5} className="size-4" />
          </Button>
        </div>
      </section>
    </main>
  )
}

import type { Metadata } from "next"
import { Suspense } from "react"

import { NeedsYouView } from "@/components/needs-you-view"

export const metadata: Metadata = { title: "Needs you" }

export default function Page() {
  return (
    <Suspense fallback={null}>
      <NeedsYouView />
    </Suspense>
  )
}

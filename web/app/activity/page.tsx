import type { Metadata } from "next"
import { Suspense } from "react"

import { ActivityView } from "@/components/activity-view"

export const metadata: Metadata = { title: "Activity" }

export default function Page() {
  return (
    <Suspense fallback={null}>
      <ActivityView />
    </Suspense>
  )
}

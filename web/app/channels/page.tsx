import type { Metadata } from "next"
import { Suspense } from "react"

import { ChannelsView } from "@/components/channels-view"

export const metadata: Metadata = { title: "Channels" }

export default function Page() {
  return (
    <Suspense fallback={null}>
      <ChannelsView />
    </Suspense>
  )
}

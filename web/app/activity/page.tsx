import type { Metadata } from "next"

import { RoutePage } from "@/components/route-page"

export const metadata: Metadata = { title: "Activity" }

export default function Page() {
  return <RoutePage view="activity" />
}

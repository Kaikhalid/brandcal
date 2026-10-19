import type { Metadata } from "next"

import { RoutePage } from "@/components/route-page"

export const metadata: Metadata = { title: "Channels" }

export default function Page() {
  return <RoutePage view="channels" />
}

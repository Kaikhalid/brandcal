import type { Metadata } from "next"

import { RoutePage } from "@/components/route-page"

export const metadata: Metadata = { title: "Needs you" }

export default function Page() {
  return <RoutePage view="needs-you" />
}

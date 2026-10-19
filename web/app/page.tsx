import type { Metadata } from "next"

import { RoutePage } from "@/components/route-page"

// A layout's title template does not apply to the page of its own segment, so spell it out.
export const metadata: Metadata = { title: { absolute: "Calendar · brandcal" } }

// `/` renders the Calendar itself (no redirect). The week and month views arrive in N2.
export default function Page() {
  return <RoutePage view="calendar" />
}

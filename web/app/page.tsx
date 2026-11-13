import type { Metadata } from "next"
import { Suspense } from "react"

import { CalendarView } from "@/components/calendar-view"

// A layout's title template does not apply to the page of its own segment, so spell it out.
export const metadata: Metadata = { title: { absolute: "Calendar · brandcal" } }

// `/` renders the Calendar itself (no redirect). Its state is in the address (?view=, ?date=, ...).
export default function Page() {
  return (
    <Suspense fallback={null}>
      <CalendarView />
    </Suspense>
  )
}

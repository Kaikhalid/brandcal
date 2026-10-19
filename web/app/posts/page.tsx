import type { Metadata } from "next"

import { RoutePage } from "@/components/route-page"

export const metadata: Metadata = { title: "Posts" }

// The open post is the ?post= query, read on the client; there are no dynamic routes.
export default function Page() {
  return <RoutePage view="posts" />
}

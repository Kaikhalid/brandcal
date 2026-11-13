import type { Metadata } from "next"
import { Suspense } from "react"

import { PostsView } from "@/components/posts-view"

export const metadata: Metadata = { title: "Posts" }

export default function Page() {
  return (
    <Suspense fallback={null}>
      <PostsView />
    </Suspense>
  )
}

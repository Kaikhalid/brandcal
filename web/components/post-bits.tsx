"use client"

import {
  CirclePause,
  FileText,
  GalleryHorizontal,
  Hand,
  Image as ImageIcon,
  ListChecks,
  MessageCircle,
  MessagesSquare,
  Newspaper,
  Repeat2,
  Shapes,
  Type,
  Video,
  type LucideIcon,
} from "lucide-react"
import * as React from "react"

import type { PostDetail } from "@/lib/api"
import { useUrlState } from "@/lib/url-state"
import { cn } from "@/lib/utils"

// Post types get generic outline metaphors, never brand logos. The id is always printed; an id
// this table does not know gets a generic icon.
const TYPE_ICON: Record<string, LucideIcon> = {
  text: Type,
  image: ImageIcon,
  video: Video,
  thread: MessagesSquare,
  article: Newspaper,
  carousel: GalleryHorizontal,
  reshare: Repeat2,
  comment: MessageCircle,
  document: FileText,
}

export function TypeIcon({ type, className }: { type: string; className?: string }) {
  const Icon = Object.hasOwn(TYPE_ICON, type) ? TYPE_ICON[type] : Shapes
  return <Icon aria-hidden="true" strokeWidth={1.5} className={cn("size-4 shrink-0", className)} />
}

export function TypeTag({ type }: { type: string }) {
  return (
    <span data-type={type} className="inline-flex items-center gap-1.5 text-[0.8125rem] text-label">
      <TypeIcon type={type} />
      {type}
    </span>
  )
}

/** What is going on with a post beyond its status: queued on the platform, claimed, on hold. */
export function postBadges(post: PostDetail): { id: string; Icon: LucideIcon; text: string }[] {
  const out = []
  if (post.native_scheduled_at) out.push({ id: "queued", Icon: ListChecks, text: "Natively scheduled" })
  if (post.claimed_by) out.push({ id: "claimed", Icon: Hand, text: `Claimed by ${post.claimed_by}` })
  if (post.hold_until) out.push({ id: "hold", Icon: CirclePause, text: "On hold" })
  return out
}

export function PostBadges({ post, compact }: { post: PostDetail; compact?: boolean }) {
  return postBadges(post).map(({ id, Icon, text }) => (
    <span
      key={id}
      data-badge={id}
      title={text}
      className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs leading-5 text-ink"
    >
      <Icon aria-hidden="true" strokeWidth={1.5} className="size-3.5 shrink-0" />
      {compact ? <span className="sr-only">{text}</span> : text}
    </span>
  ))
}

// The element that opened the panel, so Esc and the close button can hand focus back to it.
let opener: HTMLElement | null = null

export const takeOpener = () => {
  const el = opener
  opener = null
  return el
}

/** Open a post in the side panel (`?post=ID`) from any view; `from` gets focus back on close. */
export function useOpenPost() {
  const { set } = useUrlState()
  return React.useCallback(
    (id: string, from: HTMLElement) => {
      opener = from
      set({ post: id })
    },
    [set]
  )
}

/** "changes_requested" -> "Changes requested". */
export const words = (id: string) => {
  const text = id.replaceAll("_", " ").replaceAll("-", " ")
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** The wording of a count: "1 post", "3 posts". */
export const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

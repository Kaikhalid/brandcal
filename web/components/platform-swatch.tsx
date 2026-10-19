import { Globe, Megaphone } from "lucide-react"

import { cn } from "@/lib/utils"

// One pastel per platform id (examples/platforms.json uses the same ids). The name is always
// printed: the colour never carries the meaning alone, and there is never a brand logo.
const PLATFORM = {
  linkedin: { label: "LinkedIn", tone: "bg-pf-linkedin text-pf-linkedin-ink" },
  x: { label: "X", tone: "bg-pf-x text-pf-x-ink" },
  instagram: { label: "Instagram", tone: "bg-pf-instagram text-pf-instagram-ink" },
  youtube: { label: "YouTube", tone: "bg-pf-youtube text-pf-youtube-ink" },
  bluesky: { label: "Bluesky", tone: "bg-pf-bluesky text-pf-bluesky-ink" },
} as const

export type Platform = keyof typeof PLATFORM
export const PLATFORMS = Object.keys(PLATFORM) as Platform[]

const isKnown = (id: string): id is Platform => Object.hasOwn(PLATFORM, id)

// A platform added in platforms.json shows up with a neutral fill and its id as the name.
const UNKNOWN_TONE = "bg-muted text-ink"

export const platformLabel = (id: string) => (isKnown(id) ? PLATFORM[id].label : id)

/** A small pill: pastel, icon, name. */
function PlatformBadge({ platform, className }: { platform: string; className?: string }) {
  const known = isKnown(platform)
  const Icon = known ? Megaphone : Globe
  return (
    <span
      data-platform={platform}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-full pr-3 pl-2.5 text-[0.8125rem] leading-none whitespace-nowrap",
        known ? PLATFORM[platform].tone : UNKNOWN_TONE,
        className
      )}
    >
      <Icon aria-hidden="true" strokeWidth={1.5} className="size-4 shrink-0" />
      {platformLabel(platform)}
    </span>
  )
}

/** A larger tile for galleries and cards. */
function PlatformSwatch({ platform, className }: { platform: string; className?: string }) {
  return (
    <span
      data-platform={platform}
      className={cn(
        "inline-flex h-16 min-w-28 items-end rounded-inner px-4 py-3 text-sm",
        isKnown(platform) ? PLATFORM[platform].tone : UNKNOWN_TONE,
        className
      )}
    >
      {platformLabel(platform)}
    </span>
  )
}

export { PlatformBadge, PlatformSwatch }

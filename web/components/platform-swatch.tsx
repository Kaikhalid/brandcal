import { Globe, Megaphone } from "lucide-react"

import { cn } from "@/lib/utils"

// One pastel per platform id (examples/platforms.json uses the same ids). The name is always
// printed: the colour never carries the meaning alone, and there is never a brand logo.
// `edge` is the slightly stronger colour of the small dots; `hairline` is the same hue, faint,
// as a 1 px inner ring that keeps adjacent blocks of one platform apart (no stripe on any side).
const PLATFORM = {
  linkedin: {
    label: "LinkedIn",
    tone: "bg-pf-linkedin text-pf-linkedin-ink",
    hairline: "inset-ring-pf-linkedin-edge/25",
    dot: "bg-pf-linkedin-edge",
  },
  x: {
    label: "X",
    tone: "bg-pf-x text-pf-x-ink",
    hairline: "inset-ring-pf-x-edge/25",
    dot: "bg-pf-x-edge",
  },
  instagram: {
    label: "Instagram",
    tone: "bg-pf-instagram text-pf-instagram-ink",
    hairline: "inset-ring-pf-instagram-edge/25",
    dot: "bg-pf-instagram-edge",
  },
  youtube: {
    label: "YouTube",
    tone: "bg-pf-youtube text-pf-youtube-ink",
    hairline: "inset-ring-pf-youtube-edge/25",
    dot: "bg-pf-youtube-edge",
  },
  bluesky: {
    label: "Bluesky",
    tone: "bg-pf-bluesky text-pf-bluesky-ink",
    hairline: "inset-ring-pf-bluesky-edge/25",
    dot: "bg-pf-bluesky-edge",
  },
} as const

export type Platform = keyof typeof PLATFORM
export const PLATFORMS = Object.keys(PLATFORM) as Platform[]

const isKnown = (id: string): id is Platform => Object.hasOwn(PLATFORM, id)

// A platform added in platforms.json shows up with a neutral fill and its id as the name.
const UNKNOWN_TONE = "bg-muted text-ink"

export const platformLabel = (id: string) => (isKnown(id) ? PLATFORM[id].label : id)

/** The pastel fill and its readable ink for a platform id (neutral for an unknown one). */
export const platformTone = (id: string) => (isKnown(id) ? PLATFORM[id].tone : UNKNOWN_TONE)

/**
 * The pastel block of a post: fill and ink carry the platform (its name and icon are printed
 * inside), a faint same-hue 1 px inner hairline separates neighbours. Neutral for an unknown id.
 */
export const platformBlock = (id: string) =>
  cn(
    "inset-ring",
    isKnown(id) ? `${PLATFORM[id].tone} ${PLATFORM[id].hairline}` : "bg-muted text-ink inset-ring-hairline"
  )

/** A small round swatch in the platform's edge colour. Decorative: the name is always printed. */
function PlatformDot({ platform, className }: { platform: string; className?: string }) {
  return (
    <span
      aria-hidden="true"
      data-platform-dot={platform}
      className={cn(
        "inline-block size-2.5 shrink-0 rounded-full",
        isKnown(platform) ? PLATFORM[platform].dot : "bg-control",
        className
      )}
    />
  )
}

/** Icon and name with no fill, for text that already sits on the platform's pastel. */
function PlatformMark({
  platform,
  className,
  bare,
}: {
  platform: string
  className?: string
  /** The name alone, for a tight card (the icon is generic and adds no meaning). */
  bare?: boolean
}) {
  const Icon = isKnown(platform) ? Megaphone : Globe
  return (
    <span data-platform={platform} className={cn("inline-flex items-center gap-1.5 text-[0.8125rem]", className)}>
      {!bare && <Icon aria-hidden="true" strokeWidth={1.5} className="size-4 shrink-0" />}
      {platformLabel(platform)}
    </span>
  )
}

/** A small pill: pastel, icon, name. */
function PlatformBadge({ platform, className }: { platform: string; className?: string }) {
  return (
    <span
      data-platform={platform}
      className={cn(
        "inline-flex min-h-7 max-w-full items-center gap-2 rounded-full px-3 py-1 text-[0.8125rem] leading-tight",
        platformTone(platform),
        className
      )}
    >
      <PlatformDot platform={platform} />
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

export { PlatformBadge, PlatformDot, PlatformMark, PlatformSwatch }

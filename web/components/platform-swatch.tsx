import { cn } from "@/lib/utils"

// One pastel per platform id (examples/platforms.json and the sprite use the same ids).
// The name is always printed: the colour never carries the meaning alone.
const PLATFORM = {
  linkedin: { label: "LinkedIn", tone: "bg-pf-linkedin text-pf-linkedin-ink" },
  x: { label: "X", tone: "bg-pf-x text-pf-x-ink" },
  instagram: { label: "Instagram", tone: "bg-pf-instagram text-pf-instagram-ink" },
  youtube: { label: "YouTube", tone: "bg-pf-youtube text-pf-youtube-ink" },
  bluesky: { label: "Bluesky", tone: "bg-pf-bluesky text-pf-bluesky-ink" },
} as const

export type Platform = keyof typeof PLATFORM
export const PLATFORMS = Object.keys(PLATFORM) as Platform[]

function PlatformSwatch({ platform, className }: { platform: Platform; className?: string }) {
  const { label, tone } = PLATFORM[platform]
  return (
    <span
      data-platform={platform}
      className={cn(
        "inline-flex h-16 min-w-28 items-end rounded-inner px-4 py-3 text-sm",
        tone,
        className
      )}
    >
      {label}
    </span>
  )
}

export { PlatformSwatch }

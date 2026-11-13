import {
  Activity,
  CalendarDays,
  FileText,
  Inbox,
  Settings,
  Share2,
  type LucideIcon,
} from "lucide-react"

export type NavItem = {
  href: string
  label: string
  icon: LucideIcon
  /** The second key of the `g` chord (g then this key goes to the page). */
  key: string
}

// Routes are static pages (trailingSlash). The open post is the ?post= query, never a route.
export const NAV_SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: "Schedule",
    items: [
      { href: "/", label: "Calendar", icon: CalendarDays, key: "c" },
      { href: "/needs-you/", label: "Needs you", icon: Inbox, key: "n" },
      { href: "/posts/", label: "Posts", icon: FileText, key: "p" },
    ],
  },
  {
    title: "Workspace",
    items: [
      { href: "/channels/", label: "Channels", icon: Share2, key: "h" },
      { href: "/activity/", label: "Activity", icon: Activity, key: "a" },
      { href: "/settings/", label: "Settings", icon: Settings, key: "s" },
    ],
  },
]

export const NAV_ITEMS: NavItem[] = NAV_SECTIONS.flatMap((section) => section.items)

/** Is `href` the page at `pathname`? Both are compared without a trailing slash. */
export function isCurrent(href: string, pathname: string): boolean {
  const trim = (p: string) => (p.length > 1 ? p.replace(/\/+$/, "") : p)
  return trim(href) === trim(pathname)
}

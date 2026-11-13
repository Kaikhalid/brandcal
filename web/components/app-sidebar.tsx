"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

import { useAppData } from "@/components/app-data"
import { IdentityFooter } from "@/components/identity-footer"
import { Badge } from "@/components/ui/badge"
import { Kbd, KbdGroup } from "@/components/ui/kbd"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"
import { isCurrent, NAV_SECTIONS, type NavItem } from "@/lib/nav"
import { cn } from "@/lib/utils"

function NavLink({ item, count }: { item: NavItem; count: number | null }) {
  const pathname = usePathname()
  const { setOpenMobile } = useSidebar()
  const active = isCurrent(item.href, pathname)
  const Icon = item.icon
  const waiting = count !== null && count > 0

  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        isActive={active}
        tooltip={`${item.label}${waiting ? ` (${count})` : ""} · g then ${item.key}`}
        aria-current={active ? "page" : undefined}
        // No prefetch: Next probes each page with HEAD, which the server refuses (UI_SPEC 2.2).
        render={<Link href={item.href} prefetch={false} onClick={() => setOpenMobile(false)} />}
      >
        <Icon aria-hidden="true" strokeWidth={1.5} />
        {/* sr-only, not hidden, in the rail: the link keeps its name (EVALUATION 3). */}
        <span className="whitespace-nowrap group-data-[collapsible=icon]:sr-only">{item.label}</span>
        {waiting && (
          <>
            <Badge
              variant="secondary"
              aria-hidden="true"
              className="ml-auto tabular-nums group-data-[collapsible=icon]:hidden"
            >
              {count}
            </Badge>
            {/* Outside the badge, so the count is still read when the badge is hidden in the rail. */}
            <span className="sr-only">{` ${count} waiting`}</span>
            <span
              aria-hidden="true"
              className="absolute top-1.5 right-1.5 hidden size-3 rounded-full border-2 border-surface bg-destructive group-data-[collapsible=icon]:block"
            />
          </>
        )}
        <KbdGroup
          aria-hidden="true"
          // Shown only for the row under the pointer or the keyboard (and in the collapsed rail's
          // tooltip); the full list lives in Settings. Opacity, not display, so rows never reflow.
          className={cn(
            "opacity-0 group-focus-within/menu-item:opacity-100 group-hover/menu-item:opacity-100 group-data-[collapsible=icon]:hidden",
            !waiting && "ml-auto"
          )}
        >
          <Kbd>g</Kbd>
          <Kbd>{item.key}</Kbd>
        </KbdGroup>
      </SidebarMenuButton>
    </SidebarMenuItem>
  )
}

function AppSidebar() {
  const { needsYou } = useAppData()
  const count = needsYou.state === "ok" ? needsYou.data : null

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="p-3">
        <div className="flex h-10 items-center gap-3 px-1">
          <span
            aria-hidden="true"
            className="flex size-8 shrink-0 items-center justify-center rounded-full bg-pill text-pill-foreground"
          >
            b
          </span>
          <span className="text-lg font-light tracking-tight group-data-[collapsible=icon]:hidden">
            brandcal
          </span>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <nav aria-label="Primary" className="flex flex-col">
          {NAV_SECTIONS.map((section) => (
            <SidebarGroup key={section.title} className="px-3 py-2">
              <SidebarGroupLabel>{section.title}</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu className="gap-1">
                  {section.items.map((item) => (
                    <NavLink
                      key={item.href}
                      item={item}
                      count={item.href === "/needs-you/" ? count : null}
                    />
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          ))}
        </nav>
      </SidebarContent>
      <SidebarFooter className="border-t border-sidebar-border p-3">
        <IdentityFooter />
      </SidebarFooter>
    </Sidebar>
  )
}

export { AppSidebar }

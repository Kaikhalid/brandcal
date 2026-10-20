"use client"

import { PanelLeft } from "lucide-react"
import { usePathname } from "next/navigation"

import { AppDataProvider } from "@/components/app-data"
import { AppSidebar } from "@/components/app-sidebar"
import { DevBanner } from "@/components/dev-banner"
import { NoticeProvider } from "@/components/notice"
import { PostPanel } from "@/components/post-panel"
import { Shortcuts } from "@/components/shortcuts"
import { ThemeToggle } from "@/components/theme-toggle"
import { SidebarProvider, useSidebar } from "@/components/ui/sidebar"
import { TooltipProvider } from "@/components/ui/tooltip"
import { isCurrent } from "@/lib/nav"
import { cn } from "@/lib/utils"

// A circular icon button: toggles the rail on desktop, opens the navigation sheet on a phone.
function ShellTrigger() {
  const { isMobile, open, openMobile, toggleSidebar } = useSidebar()
  return (
    <button
      type="button"
      onClick={toggleSidebar}
      aria-label="Toggle navigation"
      aria-expanded={isMobile ? openMobile : open}
      title="Toggle navigation ([)"
      className="press inline-flex size-10 shrink-0 items-center justify-center rounded-full border border-control bg-surface text-ink hover:bg-muted"
    >
      <PanelLeft aria-hidden="true" strokeWidth={1.5} className="size-5" />
    </button>
  )
}

// The shell: skip link, dev banner, glass sidebar (a sheet on a phone), a frosted bar that sticks
// to the top of the content, and <main>. Landmarks: one banner (the bar), one nav, one main.
function AppShell({ children }: { children: React.ReactNode }) {
  // The calendar and the posts table need the width; the rest read better narrow.
  const pathname = usePathname()
  const wide = isCurrent("/", pathname) || isCurrent("/posts/", pathname)
  return (
    <AppDataProvider>
      <NoticeProvider>
      <TooltipProvider delay={300}>
        <DevBanner />
        <SidebarProvider>
          <Shortcuts />
          {/* Inert while the post panel overlays the page (below 1200px); see post-panel.tsx. The
              skip link lives inside it so a modal panel cannot be left by Tab. */}
          <div id="shell-body" className="contents">
            <a
              href="#main"
              className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[60] focus:rounded-full focus:bg-pill focus:px-5 focus:py-3 focus:text-sm focus:text-pill-foreground"
            >
              Skip to main content
            </a>
            <AppSidebar />
            <div className="flex min-w-0 flex-1 flex-col">
              <header className="glass sticky top-(--shell-top) z-20 flex h-16 items-center justify-between gap-3 px-4 md:px-6">
                <ShellTrigger />
                <ThemeToggle />
              </header>
              <main
                id="main"
                tabIndex={-1}
                className={cn(
                  // pb-32 leaves room to scroll the last controls clear of the notice card.
                  "mx-auto w-full flex-1 px-6 pt-10 pb-32 outline-none md:pt-14",
                  wide ? "max-w-[88rem]" : "max-w-5xl"
                )}
              >
                {children}
              </main>
            </div>
          </div>
          <PostPanel />
        </SidebarProvider>
      </TooltipProvider>
      </NoticeProvider>
    </AppDataProvider>
  )
}

export { AppShell }

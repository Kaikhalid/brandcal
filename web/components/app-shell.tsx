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
import { ToolbarProvider, ToolbarSlot } from "@/components/toolbar"
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

// The shell: skip link, dev banner, glass sidebar (a sheet on a phone), one glass bar that is also
// the page toolbar (see toolbar.tsx), and <main>. Landmarks: one banner (the bar), one nav, one
// main. On the calendar the column is exactly one screen tall and <main> is a flex column, so the
// calendar is the only scroller; every other page scrolls as a page.
function AppShell({ children }: { children: React.ReactNode }) {
  // The calendar and the posts table need the width; the rest read better narrow.
  const pathname = usePathname()
  const fill = isCurrent("/", pathname)
  const wide = fill || isCurrent("/posts/", pathname)
  return (
    <AppDataProvider>
      <NoticeProvider>
      <TooltipProvider delay={300}>
        <DevBanner />
        <SidebarProvider>
          <Shortcuts />
          <ToolbarProvider>
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
            {/* @container: the bar's controls collapse to icons by the width of this column. */}
            <div
              className={cn(
                "@container flex min-w-0 flex-1 flex-col",
                fill && "h-[calc(100svh-var(--shell-top))] overflow-hidden"
              )}
            >
              <header className="glass sticky top-(--shell-top) z-20 flex min-h-16 shrink-0 flex-wrap items-center gap-x-2 gap-y-2 px-4 py-3 md:px-6">
                <ShellTrigger />
                <ToolbarSlot />
                <ThemeToggle className="ml-auto" />
              </header>
              <main
                id="main"
                tabIndex={-1}
                className={cn(
                  "w-full outline-none",
                  fill
                    ? "flex min-h-0 flex-1 flex-col"
                    : cn(
                        // pb-32 leaves room to scroll the last controls clear of the notice card.
                        "mx-auto flex-1 px-6 pt-10 pb-32 md:pt-14",
                        wide ? "max-w-[88rem]" : "max-w-5xl"
                      )
                )}
              >
                {children}
              </main>
            </div>
          </div>
          <PostPanel />
          </ToolbarProvider>
        </SidebarProvider>
      </TooltipProvider>
      </NoticeProvider>
    </AppDataProvider>
  )
}

export { AppShell }

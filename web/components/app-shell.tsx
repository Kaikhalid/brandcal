"use client"

import { PanelLeft } from "lucide-react"

import { AppDataProvider } from "@/components/app-data"
import { AppSidebar } from "@/components/app-sidebar"
import { DevBanner } from "@/components/dev-banner"
import { Shortcuts } from "@/components/shortcuts"
import { ThemeToggle } from "@/components/theme-toggle"
import { SidebarProvider, useSidebar } from "@/components/ui/sidebar"
import { TooltipProvider } from "@/components/ui/tooltip"

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
  return (
    <AppDataProvider>
      <TooltipProvider delay={300}>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-[60] focus:rounded-full focus:bg-pill focus:px-5 focus:py-3 focus:text-sm focus:text-pill-foreground"
        >
          Skip to main content
        </a>
        <DevBanner />
        <SidebarProvider>
          <Shortcuts />
          <AppSidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <header className="glass sticky top-(--shell-top) z-20 flex h-16 items-center justify-between gap-3 px-4 md:px-6">
              <ShellTrigger />
              <ThemeToggle />
            </header>
            <main
              id="main"
              tabIndex={-1}
              className="mx-auto w-full max-w-5xl flex-1 px-6 py-10 outline-none md:py-14"
            >
              {children}
            </main>
          </div>
        </SidebarProvider>
      </TooltipProvider>
    </AppDataProvider>
  )
}

export { AppShell }

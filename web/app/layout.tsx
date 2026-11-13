import type { Metadata } from "next"
import { GeistMono } from "geist/font/mono"
import { GeistSans } from "geist/font/sans"

import "./globals.css"
import { AppShell } from "@/components/app-shell"
import { ShortcutsProvider } from "@/components/shortcuts"
import { ThemeProvider } from "@/components/theme-provider"
import { cn } from "@/lib/utils"

export const metadata: Metadata = {
  title: { default: "brandcal", template: "%s · brandcal" },
  description: "The brand content calendar: what is planned, what needs you, what went out.",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="en-GB"
      suppressHydrationWarning
      className={cn("antialiased", GeistSans.variable, GeistMono.variable, "font-sans")}
    >
      <body>
        <ShortcutsProvider>
          <ThemeProvider>
            <AppShell>{children}</AppShell>
          </ThemeProvider>
        </ShortcutsProvider>
      </body>
    </html>
  )
}

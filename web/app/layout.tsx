import type { Metadata, Viewport } from "next"
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
  applicationName: "brandcal",
  icons: {
    icon: [{ url: "/icon-192.png", sizes: "192x192", type: "image/png" }],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
  appleWebApp: { capable: true, title: "brandcal", statusBarStyle: "default" },
}

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#F6F4F0" },
    { media: "(prefers-color-scheme: dark)", color: "#121316" },
  ],
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
      <head>
        {/* The site sits behind Cloudflare Access: the manifest fetch must carry the session cookie. */}
        <link rel="manifest" href="/manifest.webmanifest" crossOrigin="use-credentials" />
      </head>
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

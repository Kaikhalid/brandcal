"use client"

import * as React from "react"
import { ThemeProvider as NextThemesProvider, useTheme } from "next-themes"

import { isTyping, useShortcuts } from "@/components/shortcuts"

function ThemeProvider({
  children,
  ...props
}: React.ComponentProps<typeof NextThemesProvider>) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      // No disableTransitionOnChange: it injects a <style> element at runtime, which the
      // page's Content-Security-Policy (hashes only, no 'unsafe-inline') would block.
      {...props}
    >
      <ThemeHotkey />
      {children}
    </NextThemesProvider>
  )
}

// "d" flips the theme; like the other single-key shortcuts it can be switched off in Settings.
function ThemeHotkey() {
  const { resolvedTheme, setTheme } = useTheme()
  const { enabled } = useShortcuts()

  React.useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!enabled || event.defaultPrevented || event.repeat) {
        return
      }

      if (event.metaKey || event.ctrlKey || event.altKey) {
        return
      }

      if (event.key.toLowerCase() !== "d") {
        return
      }

      if (isTyping(event.target)) {
        return
      }

      setTheme(resolvedTheme === "dark" ? "light" : "dark")
    }

    window.addEventListener("keydown", onKeyDown)

    return () => {
      window.removeEventListener("keydown", onKeyDown)
    }
  }, [enabled, resolvedTheme, setTheme])

  return null
}

export { ThemeProvider }

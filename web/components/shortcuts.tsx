"use client"

import { useRouter } from "next/navigation"
import * as React from "react"

import { useSidebar } from "@/components/ui/sidebar"
import { NAV_ITEMS } from "@/lib/nav"

// Single-key shortcuts can be switched off (WCAG 2.1.4): the switch lives in Settings. It is
// deliberately in memory only, because the UI keeps nothing in the browser but the theme and
// the sidebar flag (so an agent and a person always see the same state).
const ShortcutsContext = React.createContext<{
  enabled: boolean
  setEnabled: (on: boolean) => void
}>({ enabled: true, setEnabled: () => undefined })

export const useShortcuts = () => React.useContext(ShortcutsContext)

function ShortcutsProvider({ children }: { children: React.ReactNode }) {
  const [enabled, setEnabled] = React.useState(true)
  const value = React.useMemo(() => ({ enabled, setEnabled }), [enabled])
  return <ShortcutsContext.Provider value={value}>{children}</ShortcutsContext.Provider>
}

/** Shortcuts never fire while the person is typing, or while a control that uses keys has focus. */
export function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return (
    target.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) ||
    target.getAttribute("role") === "textbox"
  )
}

const CHORD_MS = 1500

// g then c/n/p/h/a/s goes to a page; [ and Cmd/Ctrl+B toggle the rail (or the mobile sheet).
function Shortcuts() {
  const router = useRouter()
  const { toggleSidebar } = useSidebar()
  const { enabled } = useShortcuts()
  const chord = React.useRef<number | null>(null)

  React.useEffect(() => {
    const clear = () => {
      if (chord.current !== null) window.clearTimeout(chord.current)
      chord.current = null
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.defaultPrevented || event.repeat || event.isComposing || isTyping(event.target)) return

      if ((event.metaKey || event.ctrlKey) && !event.altKey && event.key.toLowerCase() === "b") {
        event.preventDefault()
        toggleSidebar()
        return
      }
      if (!enabled || event.metaKey || event.ctrlKey || event.altKey) return

      if (chord.current !== null) {
        clear()
        const target = NAV_ITEMS.find((item) => item.key === event.key.toLowerCase())
        if (target) {
          event.preventDefault()
          router.push(target.href)
        }
        return
      }
      if (event.key === "g") {
        chord.current = window.setTimeout(clear, CHORD_MS)
      } else if (event.key === "[") {
        event.preventDefault()
        toggleSidebar()
      }
    }

    window.addEventListener("keydown", onKeyDown)
    return () => {
      window.removeEventListener("keydown", onKeyDown)
      clear()
    }
  }, [enabled, router, toggleSidebar])

  return null
}

export { Shortcuts, ShortcutsProvider }

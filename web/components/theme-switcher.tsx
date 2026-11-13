"use client"

import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react"
import { useTheme } from "next-themes"
import * as React from "react"

import { cn } from "@/lib/utils"

const OPTIONS: { value: string; label: string; Icon: LucideIcon }[] = [
  { value: "system", label: "System", Icon: Monitor },
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
]

// System / Light / Dark as segmented pills; the selected one is the black pill. A radio group, so
// the arrow keys move between the options and the state is exposed without colour.
function ThemeSwitcher({ className, compact = false }: { className?: string; compact?: boolean }) {
  const { theme, setTheme } = useTheme()
  // next-themes only knows the stored theme after hydration; until then nothing is selected.
  const mounted = React.useSyncExternalStore(
    () => () => undefined,
    () => true,
    () => false
  )
  const current = mounted ? theme : undefined
  const refs = React.useRef<(HTMLButtonElement | null)[]>([])

  function onKeyDown(event: React.KeyboardEvent, index: number) {
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0
    if (!step) return
    event.preventDefault()
    const next = (index + step + OPTIONS.length) % OPTIONS.length
    setTheme(OPTIONS[next].value)
    refs.current[next]?.focus()
  }

  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className={cn("inline-flex items-center gap-1 rounded-full border border-control p-0.5", className)}
    >
      {OPTIONS.map(({ value, label, Icon }, index) => {
        const selected = current === value
        return (
          <button
            key={value}
            ref={(el) => {
              refs.current[index] = el
            }}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected || (!current && value === "system") ? 0 : -1}
            onClick={() => setTheme(value)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={cn(
              "press inline-flex h-9 min-w-9 items-center justify-center gap-1.5 rounded-full px-3 text-[0.8125rem]",
              selected ? "bg-pill text-pill-foreground" : "text-ink hover:bg-muted"
            )}
          >
            <Icon aria-hidden="true" strokeWidth={1.5} className="size-4 shrink-0" />
            <span className={cn(compact && "sr-only")}>{label}</span>
          </button>
        )
      })}
    </div>
  )
}

export { ThemeSwitcher }

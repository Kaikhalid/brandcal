"use client"

import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react"
import { useTheme } from "next-themes"
import * as React from "react"

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

const OPTIONS: { value: string; label: string; Icon: LucideIcon }[] = [
  { value: "system", label: "System", Icon: Monitor },
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
]

// The theme switcher for the collapsed rail, where three segments do not fit: one 40 px button
// that opens a System / Light / Dark radio menu. The expanded footer and Settings keep the
// ThemeSwitcher; the bar keeps its quick toggle.
function ThemeMenu() {
  const { theme, setTheme } = useTheme()
  const mounted = React.useSyncExternalStore(
    () => () => undefined,
    () => true,
    () => false
  )
  const current = (mounted ? theme : undefined) ?? "system"
  const Icon = OPTIONS.find((o) => o.value === current)?.Icon ?? Monitor
  return (
    <DropdownMenu>
      <Tooltip>
        <TooltipTrigger
          render={
            <DropdownMenuTrigger
              aria-label={`Theme: ${OPTIONS.find((o) => o.value === current)?.label ?? "System"}`}
              className="press inline-flex size-10 items-center justify-center rounded-full border border-control bg-surface text-ink hover:bg-muted"
            />
          }
        >
          <Icon aria-hidden="true" strokeWidth={1.5} className="size-5" />
        </TooltipTrigger>
        <TooltipContent side="right">Theme</TooltipContent>
      </Tooltip>
      <DropdownMenuContent side="right" align="end" sideOffset={12}>
        <DropdownMenuRadioGroup value={current} onValueChange={(value) => setTheme(String(value))}>
          {OPTIONS.map(({ value, label, Icon: Option }) => (
            <DropdownMenuRadioItem key={value} value={value}>
              <Option aria-hidden="true" strokeWidth={1.5} />
              {label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export { ThemeMenu }

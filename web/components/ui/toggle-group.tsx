"use client"

import { Toggle as TogglePrimitive } from "@base-ui/react/toggle"
import { ToggleGroup as ToggleGroupPrimitive } from "@base-ui/react/toggle-group"
import { cn } from "cn"

// A segmented control: the pressed segment is the one black pill (UI_STYLE 2).
function ToggleGroup({ className, ...props }: ToggleGroupPrimitive.Props) {
  return (
    <ToggleGroupPrimitive
      data-slot="toggle-group"
      className={cn("inline-flex items-center rounded-full bg-muted p-1", className)}
      {...props}
    />
  )
}

function ToggleGroupItem({ className, ...props }: TogglePrimitive.Props) {
  return (
    <TogglePrimitive
      data-slot="toggle-group-item"
      className={cn(
        "press inline-flex h-8 items-center justify-center rounded-full px-3.5 text-sm text-ink hover:bg-accent aria-pressed:bg-pill aria-pressed:text-pill-foreground aria-pressed:hover:bg-pill",
        className
      )}
      {...props}
    />
  )
}

export { ToggleGroup, ToggleGroupItem }

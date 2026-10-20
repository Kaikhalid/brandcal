"use client"

import { Popover as PopoverPrimitive } from "@base-ui/react/popover"
import { cn } from "cn"

function Popover({ ...props }: PopoverPrimitive.Root.Props) {
  return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

function PopoverTrigger({ ...props }: PopoverPrimitive.Trigger.Props) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}

// Opacity and scale 0.96 to 1 from the trigger (150 ms in, 100 ms out), tokens only; the
// reduced-motion rule in globals.css shortens both to nothing.
function PopoverContent({
  className,
  align = "end",
  alignOffset = 0,
  side = "bottom",
  sideOffset = 8,
  children,
  ...props
}: PopoverPrimitive.Popup.Props &
  Pick<PopoverPrimitive.Positioner.Props, "align" | "alignOffset" | "side" | "sideOffset">) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Positioner
        align={align}
        alignOffset={alignOffset}
        side={side}
        sideOffset={sideOffset}
        className="isolate z-50"
      >
        <PopoverPrimitive.Popup
          data-slot="popover-content"
          className={cn(
            "card-surface z-50 max-h-(--available-height) w-80 max-w-[calc(100vw-1.5rem)] origin-(--transform-origin) overflow-y-auto overscroll-contain p-5 text-ink shadow-float outline-none",
            "data-open:animate-in data-open:fade-in-0 data-open:zoom-in-[0.96] data-open:duration-150 data-open:ease-(--ease-out)",
            "data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-[0.96] data-closed:duration-100",
            className
          )}
          {...props}
        >
          {children}
        </PopoverPrimitive.Popup>
      </PopoverPrimitive.Positioner>
    </PopoverPrimitive.Portal>
  )
}

function PopoverTitle({ className, ...props }: PopoverPrimitive.Title.Props) {
  return (
    <PopoverPrimitive.Title
      data-slot="popover-title"
      className={cn("text-base font-normal", className)}
      {...props}
    />
  )
}

export { Popover, PopoverTrigger, PopoverContent, PopoverTitle }

"use client"

import * as React from "react"
import { createPortal } from "react-dom"

import { cn } from "@/lib/utils"

// One top bar. AppShell owns the banner (the glass bar); a page puts its own controls into it
// through <ToolbarPortal>, so there is no second row of page chrome under the bar. The slot is
// `display: contents`: the page's items sit in the bar's own flex row (wrapping to a second row
// on a phone) and keep the DOM order they are written in, which is also the Tab order.
const SlotContext = React.createContext<{
  slot: HTMLElement | null
  setSlot: (element: HTMLElement | null) => void
}>({ slot: null, setSlot: () => undefined })

function ToolbarProvider({ children }: { children: React.ReactNode }) {
  const [slot, setSlot] = React.useState<HTMLElement | null>(null)
  const value = React.useMemo(() => ({ slot, setSlot }), [slot])
  return <SlotContext.Provider value={value}>{children}</SlotContext.Provider>
}

/** The portal target, rendered once by the shell's bar. */
function ToolbarSlot() {
  const { setSlot } = React.useContext(SlotContext)
  return <div ref={setSlot} data-toolbar-slot className="contents" />
}

/** Page controls for the shell's bar. Renders nothing until the bar has mounted its slot. */
function ToolbarPortal({ children }: { children: React.ReactNode }) {
  const { slot } = React.useContext(SlotContext)
  return slot ? createPortal(children, slot) : null
}

/** The page title in the bar: the one h1, 24 px light (18 px below 640). `label` is the visually
 *  hidden lead-in ("Calendar: ") that names the page for a screen reader. */
function ToolbarTitle({
  label,
  short,
  children,
  className,
}: {
  label?: string
  /** A shorter title for a narrow bar, shown instead of `children` when the content column is under
   *  800 px (a container query; the full title stays for readers). */
  short?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <h1
      className={cn(
        "min-w-0 shrink text-lg leading-tight font-light tracking-tight sm:text-2xl",
        className
      )}
    >
      {label && <span className="sr-only">{label}</span>}
      {short ? (
        <>
          <span aria-hidden="true" className="hidden @max-[800px]:inline">
            {short}
          </span>
          <span className="@max-[800px]:sr-only">{children}</span>
        </>
      ) : (
        children
      )}
    </h1>
  )
}

/** Pushes the controls after it to the trailing edge of the bar. */
function ToolbarSpacer() {
  return <div aria-hidden="true" className="min-w-0 flex-1" />
}

export { ToolbarPortal, ToolbarProvider, ToolbarSlot, ToolbarSpacer, ToolbarTitle }

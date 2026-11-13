"use client"

import { ChevronDown } from "lucide-react"
import * as React from "react"

import { cn } from "@/lib/utils"

/** A heading whose button shows or hides its content (`aria-expanded`), closed by default. The
 *  content stays in the DOM, hidden, so `aria-controls` always points at something and a form or
 *  a selection inside it keeps its state. Used for the secondary sections of the post panel. */
export function Disclosure({
  title,
  children,
  defaultOpen = false,
  className,
}: {
  title: string
  children: React.ReactNode
  defaultOpen?: boolean
  className?: string
}) {
  const [open, setOpen] = React.useState(defaultOpen)
  const id = React.useId()
  return (
    <section className={cn("-mx-2 flex flex-col gap-1", className)}>
      <h3 className="text-sm font-normal">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen(!open)}
          className="press flex min-h-10 w-full items-center justify-between gap-2 rounded-control px-2 text-left text-sm text-label hover:bg-muted hover:text-ink"
        >
          {title}
          <ChevronDown
            aria-hidden="true"
            strokeWidth={1.5}
            className={cn("size-4 shrink-0 transition-transform duration-150", open && "rotate-180")}
          />
        </button>
      </h3>
      <div id={id} hidden={!open} className="flex flex-col gap-3 px-2 pb-2">
        {children}
      </div>
    </section>
  )
}

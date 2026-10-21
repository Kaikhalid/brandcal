"use client"

import { ChevronLeft, ChevronRight } from "lucide-react"
import type * as React from "react"

import { FiltersPopover, NeedsYouChip, type FilterGroup } from "@/components/filters-popover"
import { pillClass } from "@/components/filters-bar"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { ToolbarPortal, ToolbarSpacer, ToolbarTitle } from "@/components/toolbar"
import { rangeLabel, rangeLabelShort, type View } from "@/lib/time"
import { cn } from "@/lib/utils"

const roundButton =
  "press inline-flex size-10 shrink-0 items-center justify-center rounded-full border border-control bg-surface hover:bg-muted"

/** Previous, Today, Next. "Today" is the black pill while today is inside the range on show. */
export function RangeNav({
  unit,
  inRange,
  step,
  today,
}: {
  unit: string
  inRange: boolean
  step: (n: number) => void
  today: () => void
}) {
  return (
    <div className="flex items-center gap-2">
      <button type="button" aria-label={`Previous ${unit}`} onClick={() => step(-1)} className={roundButton}>
        <ChevronLeft aria-hidden="true" strokeWidth={1.5} className="size-5" />
      </button>
      <button type="button" onClick={today} className={cn(pillClass(inRange), "h-10")}>
        Today
      </button>
      <button type="button" aria-label={`Next ${unit}`} onClick={() => step(1)} className={roundButton}>
        <ChevronRight aria-hidden="true" strokeWidth={1.5} className="size-5" />
      </button>
    </div>
  )
}

/** Week / Month as a segmented control (the pressed segment is the black pill). */
export function ViewSwitch({ view, onChange }: { view: View; onChange: (view: View) => void }) {
  return (
    <ToggleGroup
      aria-label="View"
      value={[view]}
      onValueChange={(value) => {
        const next = value[0]
        if (next === "week" || next === "month") onChange(next)
      }}
    >
      <ToggleGroupItem value="week">Week</ToggleGroupItem>
      <ToggleGroupItem value="month">Month</ToggleGroupItem>
    </ToggleGroup>
  )
}

/** The calendar's controls for the shell's bar, in Tab order: title, range navigation, then at the
 *  trailing edge the Needs you chip, Filters and the view switch (the bar adds the theme toggle).
 *  A direction replaces pieces by composing the exports above instead of this wrapper. */
export function CalendarToolbar({
  view,
  date,
  inRange,
  step,
  today,
  onView,
  hideFilters,
  needsYou,
}: {
  view: View
  date: string
  inRange: boolean
  step: (n: number) => void
  today: () => void
  onView: (view: View) => void
  hideFilters?: FilterGroup[]
  /** What takes the Needs you chip's place (direction B: the rail's button); `null` for nothing. */
  needsYou?: React.ReactNode
}) {
  return (
    <ToolbarPortal>
      <ToolbarTitle label="Calendar: " short={rangeLabelShort(view, date)}>
        {rangeLabel(view, date)}
      </ToolbarTitle>
      <RangeNav unit={view} inRange={inRange} step={step} today={today} />
      <ToolbarSpacer />
      {needsYou === undefined ? <NeedsYouChip /> : needsYou}
      <FiltersPopover hide={hideFilters} />
      <ViewSwitch view={view} onChange={onView} />
    </ToolbarPortal>
  )
}

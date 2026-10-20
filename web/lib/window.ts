// A "START/END" window (both ends carry an explicit offset) to and from the three native inputs of
// "Move to…": a day, a start time and an end time, read and written in the configured zone
// (GET /api/schema `timezone`), never the browser's. The text the server gets is always the
// string built here or typed by hand, and the dialog prints it before anything is sent.

import { addDays, clock, dateKey, localParts, parseDate } from "@/lib/time"

const pad = (n: number) => String(n).padStart(2, "0")
const OWN_OFFSET = /(Z|[+-]\d{2}:?\d{2})$/

export type WindowParts = {
  day: string
  from: string
  to: string
  /** Whole days between the start day and the end day (0 for a window inside one day). */
  span: number
}

const dayNumber = (key: string) => {
  const [y, m, d] = parseDate(key)
  return Date.UTC(y, m - 1, d) / 86_400_000
}

/** The parts of a window text, or null when it cannot be read as two instants. */
export function windowParts(window: string, zone: string | null): WindowParts | null {
  const [a, b] = window.split("/")
  if (!a || !b || Number.isNaN(Date.parse(a)) || Number.isNaN(Date.parse(b))) return null
  const start = localParts(a, zone)
  const end = localParts(b, zone)
  return {
    day: dateKey(start),
    from: clock(start),
    to: clock(end),
    span: dayNumber(dateKey(end)) - dayNumber(dateKey(start)),
  }
}

/** Minutes the zone is ahead of UTC at the instant `ms`. */
function offsetAt(ms: number, zone: string): number {
  const t = localParts(new Date(ms).toISOString(), zone)
  return (Date.UTC(t.y, t.mo - 1, t.d, t.h, t.mi) - Math.floor(ms / 60_000) * 60_000) / 60_000
}

/** "2026-03-10T09:00:00+01:00" for that wall-clock time in `zone` (an IANA name, an offset or "Z"). */
function zonedIso(day: string, time: string, zone: string): string {
  const [y, m, d] = parseDate(day)
  const [h, mi] = time.split(":").map(Number)
  const wall = Date.UTC(y, m - 1, d, h, mi)
  // The offset at the wall time as if it were UTC, then again at the instant that gives (DST edges).
  const first = offsetAt(wall, zone)
  const offset = offsetAt(wall - first * 60_000, zone)
  const sign = offset < 0 ? "-" : "+"
  const abs = Math.abs(offset)
  return `${day}T${time}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`
}

/** The window text for a day, a start and an end. `current` supplies the offset when the server
 *  names no zone. */
export function buildWindow(parts: WindowParts, zone: string | null, current: string): string {
  const own = OWN_OFFSET.exec(current.split("/")[0] ?? "")?.[1] ?? "Z"
  const where = zone ?? own
  return `${zonedIso(parts.day, parts.from, where)}/${zonedIso(addDays(parts.day, parts.span), parts.to, where)}`
}

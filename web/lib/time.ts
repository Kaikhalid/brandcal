// Times are always shown in the configured zone (GET /api/schema `timezone`), computed from the
// server's own ISO strings. The browser's zone is never read (it is only used for "now" as an
// instant, which has no zone).

const OFFSET = /^([+-])(\d{2}):?(\d{2})$/
const SUFFIX = /(Z|[+-]\d{2}:?\d{2})$/

export const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
export const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
]

const pad = (n: number) => String(n).padStart(2, "0")

export type Local = { y: number; mo: number; d: number; h: number; mi: number }

function offsetMinutes(zone: string): number | null {
  const text = zone === "Z" ? "+00:00" : zone
  const m = OFFSET.exec(text)
  return m ? (m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3])) : null
}

/** The wall-clock parts of an instant in `zone` (an offset, "Z" or an IANA name). With no zone,
 *  the offset the string itself carries; with neither, UTC. */
export function localParts(iso: string, zone: string | null): Local {
  const ms = Date.parse(iso)
  const own = SUFFIX.exec(iso)?.[1]
  const shift = offsetMinutes(zone ?? own ?? "Z")
  if (shift !== null || zone === null) {
    const t = new Date(ms + (shift ?? 0) * 60000)
    return {
      y: t.getUTCFullYear(),
      mo: t.getUTCMonth() + 1,
      d: t.getUTCDate(),
      h: t.getUTCHours(),
      mi: t.getUTCMinutes(),
    }
  }
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: zone,
      hourCycle: "h23",
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "numeric",
    })
      .formatToParts(ms)
      .map((p) => [p.type, p.value])
  )
  return {
    y: Number(parts.year),
    mo: Number(parts.month),
    d: Number(parts.day),
    h: Number(parts.hour),
    mi: Number(parts.minute),
  }
}

export const clock = (t: Local) => `${pad(t.h)}:${pad(t.mi)}`
export const dateKey = (t: Local) => `${t.y}-${pad(t.mo)}-${pad(t.d)}`
export const parseDate = (key: string): [number, number, number] => {
  const [y, m, d] = key.split("-").map(Number)
  return [y, m, d]
}
export const isDateKey = (text: string | null): text is string => /^\d{4}-\d{2}-\d{2}$/.test(text ?? "")

export function dowOf(key: string): number {
  const [y, m, d] = parseDate(key)
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay()
}

export function addDays(key: string, n: number): string {
  const [y, m, d] = parseDate(key)
  const t = new Date(Date.UTC(y, m - 1, d + n))
  return `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())}`
}

export const weekStart = (key: string) => addDays(key, -((dowOf(key) + 6) % 7))

export function monthStart(key: string, months = 0): string {
  const [y, m] = parseDate(key)
  const t = new Date(Date.UTC(y, m - 1 + months, 1))
  return `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-01`
}

/** Today's date in the configured zone. */
export const todayKey = (zone: string | null) => dateKey(localParts(new Date().toISOString(), zone))

export function dayLabel(key: string): string {
  const [, m, d] = parseDate(key)
  return `${DAYS[dowOf(key)]} ${d} ${MONTHS[m - 1].slice(0, 3)}`
}

export type View = "week" | "month"

/** The visible range, inclusive: a week, or the weeks that cover a month. */
export function rangeFor(view: View, date: string): [string, string] {
  if (view === "week") {
    const from = weekStart(date)
    return [from, addDays(from, 6)]
  }
  const [y, m] = parseDate(date)
  const first = `${y}-${pad(m)}-01`
  const last = `${y}-${pad(m)}-${pad(new Date(Date.UTC(y, m, 0)).getUTCDate())}`
  return [weekStart(first), addDays(weekStart(last), 6)]
}

/** "9 – 15 March 2026", "30 Mar – 5 Apr 2026", "March 2026". */
export function rangeLabel(view: View, date: string): string {
  const [y, m] = parseDate(date)
  if (view === "month") return `${MONTHS[m - 1]} ${y}`
  const [from, to] = rangeFor("week", date)
  const [, fm, fd] = parseDate(from)
  const [ty, tm, td] = parseDate(to)
  return fm === tm
    ? `${fd} – ${td} ${MONTHS[tm - 1]} ${ty}`
    : `${fd} ${MONTHS[fm - 1].slice(0, 3)} – ${td} ${MONTHS[tm - 1].slice(0, 3)} ${ty}`
}

export type Span = {
  day: string
  from: string
  to: string
  text: string
  /** Minutes from midnight of `day`; `endMin` is clipped to the end of that day. */
  startMin: number
  endMin: number
}

/** A "START/END" window in the configured zone. */
export function spanOf(window: string, zone: string | null): Span {
  const [a, b] = window.split("/")
  const start = localParts(a, zone)
  const end = localParts(b ?? a, zone)
  const startMin = start.h * 60 + start.mi
  const sameDay = dateKey(start) === dateKey(end)
  return {
    day: dateKey(start),
    from: clock(start),
    to: clock(end),
    text: `${clock(start)} to ${clock(end)}`,
    startMin,
    endMin: sameDay ? Math.max(end.h * 60 + end.mi, startMin) : 1440,
  }
}

/** "Tue 10 Mar 2026, 09:00" */
export function fullTime(iso: string, zone: string | null): string {
  const t = localParts(iso, zone)
  return `${dayLabel(dateKey(t))} ${t.y}, ${clock(t)}`
}

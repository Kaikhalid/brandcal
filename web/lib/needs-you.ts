import { getPosts, type BrandcalRefusal, type PostRow, type Schema } from "@/lib/api"

// The one rule for "needs you" (the MVP strip, SPEC 12): the posts in the statuses the schema
// lists in `needs_you` that it also knows as states. The sidebar badge and the Needs you page
// both call this, so they can never disagree.
export function needsStatuses(schema: Schema): string[] {
  return schema.needs_you.filter((s) => schema.states.includes(s))
}

export type NeedsGroup = { status: string; posts: PostRow[] }

export async function loadNeedsYou(
  schema: Schema
): Promise<{ ok: true; groups: NeedsGroup[] } | { ok: false; refusal: BrandcalRefusal }> {
  const statuses = needsStatuses(schema)
  const lists = await Promise.all(statuses.map((status) => getPosts({ status })))
  const groups: NeedsGroup[] = []
  for (const [i, list] of lists.entries()) {
    if (!list.ok) return { ok: false, refusal: list.refusal }
    groups.push({ status: statuses[i], posts: list.data.posts })
  }
  return { ok: true, groups }
}

export const needsTotal = (groups: NeedsGroup[]) => groups.reduce((n, g) => n + g.posts.length, 0)

// The queue reads most urgent first: what slipped, what was sent back, what waits for a decision.
const URGENCY = ["missed", "changes_requested", "pending_approval"]
const rank = (status: string) => {
  const at = URGENCY.indexOf(status)
  return at < 0 ? URGENCY.length : at
}

/** The groups most urgent first; a status this list does not know keeps its place at the end. */
export const byUrgency = (groups: NeedsGroup[]): NeedsGroup[] =>
  [...groups].sort((a, b) => rank(a.status) - rank(b.status))

export const queuePosts = (groups: NeedsGroup[]): PostRow[] => groups.flatMap((g) => g.posts)

/** The post to show once `id` has been decided: the one after it in the queue, else the one before
 *  it, else null (all clear). Undefined when `id` is not in the queue at all, so nothing advances. */
export function afterDecision(queue: PostRow[], id: string): string | null | undefined {
  const at = queue.findIndex((p) => p.id === id)
  if (at < 0) return undefined
  return queue[at + 1]?.id ?? queue[at - 1]?.id ?? null
}

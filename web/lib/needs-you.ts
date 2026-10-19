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

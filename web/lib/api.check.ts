/* eslint-disable @typescript-eslint/no-unused-vars */
// Compile-time checks only (no test runner): `npm run typecheck` fails if the client's contract
// drifts. Nothing imports this file and it has no runtime effect.
import {
  approve,
  getEvents,
  getPost,
  getPosts,
  getSchema,
  getSession,
  mediaUrl,
  requestChanges,
  type ApiResult,
  type BrandcalRefusal,
  type PostDetail,
  type WriteResult,
} from "./api"

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2 ? true : false
const assert = <T extends true>(_?: T) => undefined

// Every non-2xx is a typed refusal with these exact fields.
assert<Equal<keyof BrandcalRefusal, "code" | "message" | "next" | "status" | "exit" | "origin" | "current">>(true)

// Calls resolve to ApiResult and never throw: the failure arm is always a BrandcalRefusal.
async function contract() {
  const refusal = (r: ApiResult<unknown>) => (r.ok ? null : r.refusal)
  assert<Equal<ReturnType<typeof refusal>, BrandcalRefusal | null>>(true)

  const session = await getSession()
  if (session.ok) assert<Equal<typeof session.data.role, "approver" | "viewer">>(true)
  const schema = await getSchema()
  if (schema.ok) assert<Equal<typeof schema.data.needs_you, string[]>>(true)
  const list = await getPosts({ status: "pending_approval", closed: true })
  if (list.ok) assert<Equal<typeof list.data.posts[number]["window"], string | null>>(true)
  const detail = await getPost("p0001")
  if (detail.ok) assert<Equal<typeof detail.data, PostDetail>>(true)
  await getEvents({ since: 0, post: "p0001", limit: 10 })
  const written = await requestChanges("p0001", { version: 1, hash: "abc", window: "w", what: "x" })
  if (written.ok) assert<Equal<typeof written.data, WriteResult>>(true)
  await approve("p0001", { version: 1, hash: "abc", window: "w" })
  assert<Equal<ReturnType<typeof mediaUrl>, string>>(true)
}

export type { contract }

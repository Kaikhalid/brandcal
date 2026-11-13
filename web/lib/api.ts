// Typed client for the brandcal JSON API (docs/UI_SPEC.md 2.2). The shapes mirror the server
// (src/brandcal/serve.py, actions.py, reports.py, schema.sql) field for field.
//
// Rules this file keeps:
// - Same origin, JSON, cookies as the browser sends them. Writes carry the CSRF token from
//   GET /api/session in X-Brandcal-CSRF, exactly like the MVP (src/brandcal/web/app.js).
// - Nothing throws. Every call resolves to ApiResult: the data, or a BrandcalRefusal in the
//   CLI's shape (code, message, next) plus the HTTP status and the X-Brandcal-Exit code.
// - No storage of any kind. The CSRF token lives in module memory only.

// -- errors --------------------------------------------------------------------------------

/** The CLI's error body, verbatim: `{"ok": false, "error": {code, message, next}}`. */
export interface ErrorBody {
  code: string
  message: string
  next: string
}

/** A refusal. `origin` tells the UI whether the server said it or the browser could not. */
export interface BrandcalRefusal extends ErrorBody {
  /** HTTP status; 0 when no answer came back. */
  status: number
  /** X-Brandcal-Exit (the CLI's exit code, SPEC 8.2); null when there was no such header. */
  exit: number | null
  origin: "server" | "client"
  /** STALE_APPROVAL carries the post as GET /api/posts/ID would return it now (UI_SPEC 3.3). */
  current?: PostDetail
}

export type ApiResult<T> = { ok: true; data: T } | { ok: false; refusal: BrandcalRefusal }

// -- reads ---------------------------------------------------------------------------------

export type SessionSource = "access-jwt" | "dev-unverified"

/** GET /api/session */
export interface Session {
  ok: true
  /** The verified email; null in dev-unverified mode. */
  identity: string | null
  role: "approver" | "viewer"
  source: SessionSource
  /** Null when the session cannot write (dev mode). */
  csrf: string | null
}

export interface Transition {
  from: string
  to: string
  roles: string[]
}

/** GET /api/schema (actions.ui_schema). Platform limits are whatever platforms.json holds. */
export interface Schema {
  ok: true
  states: string[]
  closed_states: string[]
  transitions: Transition[]
  post_types: string[]
  time_format: string
  exit_codes: Record<string, number>
  platforms: Record<string, Record<string, unknown>>
  timezone: string | null
  needs_you: string[]
  claim_minutes: number
  campaigns: unknown[]
  pillars: unknown[]
}

/** One row of GET /api/posts (reports.short_row). */
export interface PostRow {
  id: string
  status: string
  platform: string
  title: string
  window: string | null
}

export interface PostList {
  ok: true
  posts: PostRow[]
}

export interface PostFilters {
  /** Inclusive local dates, YYYY-MM-DD. */
  from?: string
  to?: string
  status?: string
  platform?: string
  /** Include published and cancelled posts. */
  closed?: boolean
}

export interface Part {
  pos: number
  text: string
  /** Where this part went live (a thread has one per part); absent before publishing. */
  platform_url?: string | null
}

/** One snapshot of a post's content (GET /api/posts/ID/versions, actions.versions). */
export interface Version {
  version: number
  hash: string
  parts: string[]
  first_comment: string | null
  target_url: string | null
  alt_texts: string[]
  /** Who made it and when; null for the live version of a post that predates snapshots. */
  editor: string | null
  at: string | null
}

export interface VersionList {
  ok: true
  id: string
  versions: Version[]
}

export type MediaKind = "image" | "video" | "pdf" | "gif"

export interface Media {
  path: string
  kind: MediaKind
  alt_text: string
  sha256: string
}

/** An approvals row without its signature. */
export interface Approval {
  id: number
  post_id: string
  decision: "approve" | "request_changes" | "cancel" | "reschedule"
  content_version: number
  content_hash: string
  window: string
  decided_by: string
  channel: "card" | "writer-session" | "legacy" | "console"
  relayed_by: string
  recorded_by: string
  source_message_id: string
  approver_words: string
  /** JSON text: {what, where, instruction} for a structured request for changes. */
  changes_requested: string | null
  decided_at: string
  verified_identity: string | null
  identity_source: string | null
}

/** One button of a post (actions.post_actions). A disabled one carries the refusal it gives. */
export interface PostAction {
  id: "approve" | "request-changes" | "reschedule" | "cancel" | "edit" | "submit" | "note"
  label: string
  /** The `brandcal` command that does the same, with <placeholders>. */
  cli: string
  enabled: boolean
  refusal: ErrorBody | null
  /** Only on `edit`. */
  warning?: string
}

/** GET /api/posts/ID: the posts row, its parts, media, approvals and the viewer's buttons. */
export interface PostDetail {
  ok: true
  id: string
  slug: string
  title: string
  platform: string
  post_type: string
  status: string
  owner: string
  window: string | null
  window_start_utc: string | null
  window_end_utc: string | null
  series_id: string | null
  series_pos: number | null
  campaign: string | null
  pillar: string | null
  /** JSON text, e.g. '["a","b"]'. */
  keywords: string
  first_comment: string | null
  target_url: string | null
  delegation_msg_id: string | null
  delegation_words: string | null
  hold_until: string | null
  hold_reason: string | null
  source_doc: string | null
  content_version: number
  content_hash: string
  native_scheduled_at: string | null
  claimed_by: string | null
  claim_expires: string | null
  platform_post_id: string | null
  platform_url: string | null
  published_at: string | null
  cancel_kind: "idea" | "version" | "plan" | null
  notes: string | null
  legacy_id: string | null
  created_at: string
  updated_at: string
  closed_at: string | null
  parts: Part[]
  media: Media[]
  approvals: Approval[]
  actions: PostAction[]
  /** The "Add a note" button; null on a closed post. */
  note: PostAction | null
}

export interface EventRow {
  id: number
  at: string
  actor: string
  post_id: string | null
  action: string
  from_status: string | null
  to_status: string | null
  reason: string | null
  /** Parsed JSON detail, or null. */
  detail: unknown
}

export interface EventList {
  ok: true
  events: EventRow[]
  last_id: number
  /** The CLI line that continues from last_id. */
  next: string
}

export interface EventFilters {
  /** Only events after this id. */
  since?: number
  post?: string
  limit?: number
}

// -- writes --------------------------------------------------------------------------------

/** What the UI saw when it showed the post (UI_SPEC 3.3); the server refuses a stale one. */
export interface Seen {
  version: number
  hash: string
  window: string
}

export interface RequestChangesBody extends Seen {
  what?: string
  where?: string
  instruction?: string
}

export interface RescheduleBody extends Seen {
  new_window: string
}

export interface CancelBody extends Seen {
  kind: "idea" | "version" | "plan"
  reason?: string
}

export interface EditBody {
  /** Post fields as text values, e.g. {title: "..."}. */
  fields?: Record<string, string>
  /** Part position ("1", "2", ...) to new text. */
  parts?: Record<string, string>
  /** Part position to alt text. */
  alt_texts?: Record<string, string>
}

export interface NoteBody {
  text: string
}

/** The answer of a write (posts.post_result for decisions; other writes add or omit fields). */
export interface WriteResult {
  ok: true
  id?: string
  status?: string
  version?: number
  hash?: string
  window?: string | null
  next?: string
  warnings?: string[]
  [key: string]: unknown
}

// -- plumbing ------------------------------------------------------------------------------

const CSRF_HEADER = "X-Brandcal-CSRF"
const EXIT_HEADER = "X-Brandcal-Exit"

let csrfToken: string | null = null

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function clientRefusal(code: string, message: string, next: string): BrandcalRefusal {
  return { code, message, next, status: 0, exit: null, origin: "client" }
}

/** The browser got no answer at all (server down, tunnel closed, offline). Labelled client-side. */
export const NETWORK_REFUSAL = clientRefusal(
  "NETWORK_ERROR",
  "The browser could not reach the brandcal server.",
  "Check that brandcal serve is running and that you are online, then reload this page."
)

function toRefusal(body: unknown, status: number, exit: number | null): BrandcalRefusal {
  const error = isRecord(body) && isRecord(body.error) ? body.error : null
  const text = (key: string): string | null =>
    error && typeof error[key] === "string" ? (error[key] as string) : null
  const refusal: BrandcalRefusal = {
    code: text("code") ?? `HTTP_${status}`,
    message: text("message") ?? "The server answered, but not in the expected form.",
    next: text("next") ?? "Reload the page; if it keeps happening, ask the admin to check the server.",
    status,
    exit,
    origin: "server",
  }
  if (isRecord(body) && isRecord(body.current)) refusal.current = body.current as unknown as PostDetail
  return refusal
}

async function request<T>(path: string, init: RequestInit = {}): Promise<ApiResult<T>> {
  let res: Response
  try {
    res = await fetch(path, { credentials: "same-origin", ...init })
  } catch {
    return { ok: false, refusal: NETWORK_REFUSAL }
  }
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    body = null
  }
  const header = res.headers.get(EXIT_HEADER)
  const exit = header !== null && /^\d+$/.test(header) ? Number(header) : null
  if (res.ok && isRecord(body) && body.ok !== false) return { ok: true, data: body as T }
  return { ok: false, refusal: toRefusal(body, res.status, exit) }
}

function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === false || value === "") continue
    search.set(key, value === true ? "1" : String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ""
}

const postPath = (id: string) => `/api/posts/${encodeURIComponent(id)}`

// -- reads ---------------------------------------------------------------------------------

/** GET /api/session. Also remembers the CSRF token for the writes. */
export async function getSession(): Promise<ApiResult<Session>> {
  const result = await request<Session>("/api/session")
  if (result.ok) csrfToken = result.data.csrf
  return result
}

export function getSchema(): Promise<ApiResult<Schema>> {
  return request<Schema>("/api/schema")
}

export function getPosts(filters: PostFilters = {}): Promise<ApiResult<PostList>> {
  return request<PostList>(`/api/posts${query({ ...filters })}`)
}

export function getPost(id: string): Promise<ApiResult<PostDetail>> {
  return request<PostDetail>(postPath(id))
}

export function getVersions(id: string): Promise<ApiResult<VersionList>> {
  return request<VersionList>(`${postPath(id)}/versions`)
}

export function getEvents(filters: EventFilters = {}): Promise<ApiResult<EventList>> {
  return request<EventList>(`/api/events${query({ ...filters })}`)
}

/** The address of the N-th media file of a post (1-based, in part then media order). */
export function mediaUrl(postId: string, n: number): string {
  return `/api/media/${encodeURIComponent(postId)}/${n}`
}

// -- writes (approver with a verified identity only; the server decides) -------------------

async function write<B extends object>(
  id: string,
  action: PostAction["id"],
  body: B
): Promise<ApiResult<WriteResult>> {
  if (csrfToken === null) {
    const session = await getSession()
    if (!session.ok) return session
  }
  return request<WriteResult>(`${postPath(id)}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", [CSRF_HEADER]: csrfToken ?? "" },
    body: JSON.stringify(body),
  })
}

export const approve = (id: string, seen: Seen) => write(id, "approve", seen)
export const requestChanges = (id: string, body: RequestChangesBody) =>
  write(id, "request-changes", body)
export const reschedule = (id: string, body: RescheduleBody) => write(id, "reschedule", body)
export const cancel = (id: string, body: CancelBody) => write(id, "cancel", body)
export const edit = (id: string, body: EditBody) => write(id, "edit", body)
export const submit = (id: string) => write(id, "submit", {})
export const note = (id: string, body: NoteBody) => write(id, "note", body)

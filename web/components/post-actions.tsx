"use client"

import { Ban, Check, Copy, LoaderCircle } from "lucide-react"
import * as React from "react"

import { Disclosure } from "@/components/disclosure"
import { ErrorPanel } from "@/components/error-panel"
import { words } from "@/components/post-bits"
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import * as api from "@/lib/api"
import type {
  ApiResult,
  BrandcalRefusal,
  CancelBody,
  PostAction,
  PostDetail,
  Schema,
  Seen,
  WriteResult,
} from "@/lib/api"
import { dayLabel, spanOf, zoneOffset } from "@/lib/time"
import { buildWindow, windowParts, type WindowParts } from "@/lib/window"
import { cn } from "@/lib/utils"

// The write actions of the post panel (UI_SPEC 1.5, 3.3, 4.1, 4.2). Each button comes from the
// server's `actions` list (and `note`), in its order, with its label; the browser decides nothing
// about what is allowed. A disabled button stays visible and disabled with the server's refusal
// under it. Every action opens a confirm dialog that says what will happen, built field for field
// like the MVP's formFor (src/brandcal/web/app.js). Validation here is only "not empty"; the
// server decides everything else and its refusal is shown verbatim with ErrorPanel.
//
// There is no drag-and-drop anywhere in this UI: moving a post in time is the "Move to…" fields
// (a day and two times, or the window text), so WCAG 2.5.7 (dragging movements) has nothing to
// offer an alternative to.

/** What the panel does around a dialog: focus, the reload, the banner and the notice. */
export type ActionsHost = {
  /** A dialog opened (page behind it is inert until it has closed). */
  opened: () => void
  /** A dialog finished closing without a write: give focus back to the action that opened it. */
  closed: (id: PostAction["id"]) => void
  /** The write was accepted: reload, then say so and focus the same action. */
  written: (id: PostAction["id"], label: string, result: WriteResult) => Promise<void>
  /** STALE_APPROVAL: reload, show the banner and focus the same action; nothing was recorded. */
  stale: (id: PostAction["id"], current: PostDetail | undefined) => Promise<void>
}

const KINDS: [CancelBody["kind"], string][] = [
  ["idea", "The idea is dropped"],
  ["version", "This version is dropped"],
  ["plan", "The plan is dropped"],
]

const CONSOLE_LINE = "This console action records channel console with your verified identity."

const control = "w-full rounded-control border border-control bg-surface px-3 text-sm"
const pill =
  "press inline-flex min-h-11 items-center justify-center gap-2 rounded-full px-5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-60"
const outlined = "border border-control bg-surface text-ink hover:bg-muted"
const solid = "bg-pill text-pill-foreground hover:opacity-90"

// -- the command line an agent would use -----------------------------------------------------

function CliBlock({ cli, label }: { cli: string; label: string }) {
  const [said, setSaid] = React.useState("")
  async function copy() {
    try {
      await navigator.clipboard.writeText(cli)
      setSaid("Copied")
    } catch {
      setSaid("Could not copy; select the command and copy it by hand")
    }
  }
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-[0.8125rem] text-label">Agent equivalent (CLI)</p>
      <div className="flex items-start gap-2">
        <code
          data-cli
          className="min-w-0 flex-1 rounded-control bg-muted px-3 py-2 font-mono text-[0.8125rem] leading-relaxed break-words"
        >
          {cli}
        </code>
        <button
          type="button"
          onClick={copy}
          aria-label={`Copy the ${label} command`}
          className="press relative inline-flex size-10 shrink-0 items-center justify-center rounded-full border border-control bg-surface hover:bg-muted"
        >
          <Copy
            aria-hidden="true"
            strokeWidth={1.5}
            className={cn(
              "absolute size-4 transition-[opacity,scale,filter] duration-(--dur-slow) ease-(--ease-out)",
              said === "Copied" ? "scale-[0.25] opacity-0 blur-[4px]" : "scale-100 opacity-100 blur-none"
            )}
          />
          <Check
            aria-hidden="true"
            strokeWidth={1.5}
            className={cn(
              "absolute size-4 transition-[opacity,scale,filter] duration-(--dur-slow) ease-(--ease-out)",
              said === "Copied" ? "scale-100 opacity-100 blur-none" : "scale-[0.25] opacity-0 blur-[4px]"
            )}
          />
        </button>
      </div>
      <span role="status" className="min-h-4 text-[0.8125rem] text-label">
        {said}
      </span>
    </div>
  )
}

// -- fields ----------------------------------------------------------------------------------

function Required({ on }: { on?: boolean }) {
  return on ? <span className="font-normal text-label">(required)</span> : null
}

type FieldProps = {
  label: string
  name: string
  required?: boolean
  hint?: string
  defaultValue?: string
}

function TextArea({ label, name, required, hint, defaultValue = "", rows = 3 }: FieldProps & { rows?: number }) {
  const id = React.useId()
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id} className="flex-wrap gap-x-1.5 leading-snug">
        {label} <Required on={required} />
      </Label>
      <Textarea
        id={id}
        name={name}
        rows={rows}
        required={required}
        defaultValue={defaultValue}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className="min-h-20 rounded-control border-control bg-surface px-3 py-2 text-sm dark:bg-surface"
      />
      {hint && (
        <p id={`${id}-hint`} className="text-[0.8125rem] text-label">
          {hint}
        </p>
      )}
    </div>
  )
}

function Line({ label, name, required, hint, defaultValue = "" }: FieldProps) {
  const id = React.useId()
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id} className="flex-wrap gap-x-1.5 leading-snug">
        {label} <Required on={required} />
      </Label>
      <input
        id={id}
        name={name}
        type="text"
        required={required}
        defaultValue={defaultValue}
        spellCheck={false}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className={cn(control, "h-10")}
      />
      {hint && (
        <p id={`${id}-hint`} className="text-[0.8125rem] text-label">
          {hint}
        </p>
      )}
    </div>
  )
}

/** "Move to…": a day and two times in the configured zone, and the window text they make. Either
 *  one updates the other; what is sent is always the text, which is printed before confirming. */
function MoveTo({
  name,
  rawLabel,
  post,
  schema,
  hint,
}: {
  name: string
  rawLabel: string
  post: PostDetail
  schema: Schema
  hint?: string
}) {
  const zone = schema.timezone
  const [raw, setRaw] = React.useState(post.window ?? "")
  const id = React.useId()
  const parts = windowParts(raw, zone)
  const move = (change: Partial<WindowParts>) => {
    if (!parts) return
    const next = { ...parts, ...change }
    if (next.day && next.from && next.to) setRaw(buildWindow(next, zone, raw))
  }
  const unreadable = parts === null
  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-3 text-sm font-medium">Move to…</legend>
      <div className="grid grid-cols-1 gap-3 min-[480px]:grid-cols-3">
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${id}-day`}>Day</Label>
          <input
            id={`${id}-day`}
            type="date"
            value={parts?.day ?? ""}
            disabled={unreadable}
            onChange={(e) => move({ day: e.target.value })}
            className={cn(control, "h-10")}
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${id}-from`}>Start</Label>
          <input
            id={`${id}-from`}
            type="time"
            value={parts?.from ?? ""}
            disabled={unreadable}
            onChange={(e) => move({ from: e.target.value })}
            className={cn(control, "h-10")}
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor={`${id}-to`}>End</Label>
          <input
            id={`${id}-to`}
            type="time"
            value={parts?.to ?? ""}
            disabled={unreadable}
            onChange={(e) => move({ to: e.target.value })}
            className={cn(control, "h-10")}
          />
        </div>
      </div>
      <p className="text-[0.8125rem] text-label">
        {zone ? `Day and times are in ${zone}.` : "Day and times use the offset of the current window."}
      </p>
      <div className="flex flex-col gap-2">
        <Label htmlFor={`${id}-raw`} className="flex-wrap gap-x-1.5 leading-snug">
          {rawLabel} <Required on />
        </Label>
        <input
          id={`${id}-raw`}
          name={name}
          type="text"
          required
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          spellCheck={false}
          aria-describedby={`${id}-hint`}
          className={cn(control, "h-10 font-mono text-[0.8125rem]")}
        />
        <p id={`${id}-hint`} className="text-[0.8125rem] text-label">
          {[schema.time_format, hint].filter(Boolean).join(". ")}
        </p>
      </div>
      <p className="text-sm">
        The window that will be sent:{" "}
        <code data-window-sent className="font-mono text-[0.8125rem] break-all">
          {raw}
        </code>
      </p>
    </fieldset>
  )
}

// -- what each action asks for, says and sends (the MVP's formFor) -----------------------------

const short = (post: PostDetail) =>
  `version ${post.content_version} (fingerprint ${post.content_hash.slice(0, 8)}) of "${post.title}"`

function saysFor(a: PostAction, post: PostDetail, schema: Schema): string {
  switch (a.id) {
    case "approve": {
      const when = post.window ? spanOf(post.window, schema.timezone) : null
      const offset = post.window
        ? zoneOffset(schema.timezone, new Date(post.window.split("/")[0]))
        : null
      return `Approve ${short(post)}${when ? `, to be published ${dayLabel(when.day)}, ${when.text}${offset ? ` (${offset})` : ""}` : ""}. The post can then be published inside that window.`
    }
    case "request-changes":
      return `Send ${short(post)} back to the writer. All three fields are required.`
    case "reschedule":
      return `Change only the time of ${short(post)}. The text stays as approved.`
    case "cancel":
      return `Cancel "${post.title}". This closes the post and cannot be undone.`
    case "submit":
      return `Submit ${short(post)} for approval again.`
    case "note":
      return `Add a note to "${post.title}". It does not change the content.`
    case "edit": {
      const first = post.parts[0]?.text ?? ""
      return `${a.warning ?? ""} Saving never approves; you approve the new version as a separate step. (First text starts: "${first.slice(0, 40)}")`.trim()
    }
  }
}

function Fields({ a, post, schema }: { a: PostAction; post: PostDetail; schema: Schema }) {
  switch (a.id) {
    case "approve":
    case "submit":
      return null
    case "request-changes":
      return (
        <>
          <TextArea label="What is wrong" name="what" required />
          <TextArea label="Where it is" name="where" required />
          <TextArea label="What the writer should do" name="instruction" required />
        </>
      )
    case "reschedule":
      return <MoveTo name="new_window" rawLabel="New window" post={post} schema={schema} />
    case "cancel":
      return <CancelFields />
    case "note":
      return <TextArea label="Note" name="text" required />
    case "edit":
      return (
        <>
          {post.parts.map((p) => (
            <TextArea
              key={p.pos}
              label={post.parts.length > 1 ? `Text, part ${p.pos}` : "Text"}
              name={`part-${p.pos}`}
              required
              rows={5}
              defaultValue={p.text}
            />
          ))}
          <TextArea label="First comment" name="first_comment" rows={2} defaultValue={post.first_comment ?? ""} />
          <Line label="Target URL" name="target_url" defaultValue={post.target_url ?? ""} />
          {post.media.map((m, i) => (
            <Line key={i} label={`Alt text, file ${i + 1}`} name={`alt-${i + 1}`} required defaultValue={m.alt_text ?? ""} />
          ))}
          <MoveTo
            name="window"
            rawLabel="Window"
            post={post}
            schema={schema}
            hint="Changing only the window needs no new approval"
          />
        </>
      )
  }
}

function CancelFields() {
  const id = React.useId()
  return (
    <>
      <div className="flex flex-col gap-2">
        <Label htmlFor={id}>What is cancelled</Label>
        <select id={id} name="kind" className={cn(control, "h-10")}>
          {KINDS.map(([value, text]) => (
            <option key={value} value={value}>
              {words(value)}: {text}
            </option>
          ))}
        </select>
      </div>
      <TextArea label="Reason" name="reason" required />
    </>
  )
}

type Values = Record<string, string>

/** The request each action sends, exactly as the MVP's body(): an edit sends only what changed. */
function send(a: PostAction, post: PostDetail, f: Values): Promise<ApiResult<WriteResult>> {
  const seen: Seen = { version: post.content_version, hash: post.content_hash, window: post.window ?? "" }
  switch (a.id) {
    case "approve":
      return api.approve(post.id, seen)
    case "request-changes":
      return api.requestChanges(post.id, { ...seen, what: f.what, where: f.where, instruction: f.instruction })
    case "reschedule":
      return api.reschedule(post.id, { ...seen, new_window: f.new_window })
    case "cancel":
      return api.cancel(post.id, { ...seen, kind: f.kind as CancelBody["kind"], reason: f.reason })
    case "submit":
      return api.submit(post.id)
    case "note":
      return api.note(post.id, { text: f.text })
    case "edit": {
      const fields: Record<string, string> = {}
      for (const key of ["first_comment", "target_url", "window"] as const) {
        if (f[key] !== (post[key] ?? "")) fields[key] = f[key]
      }
      const parts: Record<string, string> = {}
      for (const p of post.parts) if (f[`part-${p.pos}`] !== p.text) parts[p.pos] = f[`part-${p.pos}`]
      const alt_texts: Record<string, string> = {}
      post.media.forEach((m, i) => {
        if (f[`alt-${i + 1}`] !== (m.alt_text ?? "")) alt_texts[i + 1] = f[`alt-${i + 1}`]
      })
      return api.edit(post.id, { fields, parts, alt_texts })
    }
  }
}

/** The named fields of a form, as typed (a textarea's value keeps plain line feeds). */
function valuesOf(form: HTMLFormElement): Values {
  const out: Values = {}
  for (const el of Array.from(form.elements)) {
    if ((el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) && el.name) {
      out[el.name] = el.value
    }
  }
  return out
}

// -- the confirm dialog ----------------------------------------------------------------------

type DialogProps = {
  action: PostAction
  post: PostDetail
  schema: Schema
  open: boolean
  onOpenChange: (open: boolean) => void
  onComplete: (open: boolean) => void
  onSent: (result: WriteResult) => void
  onStale: (current: PostDetail | undefined) => void
}

function ActionDialog({ action: a, post, schema, open, onOpenChange, onComplete, onSent, onStale }: DialogProps) {
  const [busy, setBusy] = React.useState(false)
  const [refusal, setRefusal] = React.useState<BrandcalRefusal | null>(null)
  const form = React.useRef<HTMLFormElement>(null)
  const back = React.useRef<HTMLButtonElement>(null)
  const danger = a.id === "cancel"
  const confirm = a.id === "approve" ? `Approve version ${post.content_version}` : danger ? "Cancel post" : a.label

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setRefusal(null)
    const result = await send(a, post, valuesOf(e.currentTarget))
    if (result.ok) return onSent(result.data)
    if (result.refusal.code === "STALE_APPROVAL") return onStale(result.refusal.current)
    setRefusal(result.refusal)
    setBusy(false)
  }

  // A decision with no fields opens on "Go back", so a stray Enter never approves.
  const initialFocus = () =>
    form.current?.querySelector<HTMLElement>("textarea:not([disabled]), input:not([disabled]), select") ?? back.current

  const body = (
    <form ref={form} onSubmit={submit} className="flex flex-col gap-6">
      <Fields a={a} post={post} schema={schema} />
      <CliBlock cli={a.cli} label={a.label} />
      <p className="text-sm text-label">{CONSOLE_LINE}</p>
      {refusal && <ErrorPanel error={refusal} className="shadow-none bg-muted" />}
      <div className="flex flex-wrap justify-end gap-3">
        <button
          ref={back}
          type="button"
          onClick={() => !busy && onOpenChange(false)}
          className={cn(pill, outlined)}
        >
          Go back
        </button>
        <button
          type="submit"
          disabled={busy}
          aria-busy={busy || undefined}
          className={cn(pill, danger ? "bg-st-failed text-st-failed-ink hover:opacity-90" : solid)}
        >
          {busy ? (
            <LoaderCircle aria-hidden="true" strokeWidth={1.5} className="size-4 animate-spin" />
          ) : danger ? (
            <Ban aria-hidden="true" strokeWidth={1.5} className="size-4" />
          ) : null}
          {confirm}
        </button>
      </div>
    </form>
  )

  const change = (next: boolean) => {
    if (!busy || next) onOpenChange(next)
  }
  const heading = "text-2xl leading-tight font-light tracking-tight"
  const says = "text-sm leading-relaxed text-label"
  return danger ? (
    <AlertDialog open={open} onOpenChange={change} onOpenChangeComplete={onComplete}>
      <AlertDialogContent initialFocus={initialFocus} finalFocus={false} data-action-dialog={a.id}>
        <div className="flex flex-col gap-3">
          <AlertDialogTitle className={heading}>{a.label}</AlertDialogTitle>
          <AlertDialogDescription className={says}>{saysFor(a, post, schema)}</AlertDialogDescription>
        </div>
        {body}
      </AlertDialogContent>
    </AlertDialog>
  ) : (
    <Dialog open={open} onOpenChange={change} onOpenChangeComplete={onComplete} disablePointerDismissal>
      <DialogContent
        initialFocus={initialFocus}
        finalFocus={false}
        showCloseButton={false}
        data-action-dialog={a.id}
      >
        <div className="flex flex-col gap-3">
          <DialogTitle className={heading}>{a.label}</DialogTitle>
          <DialogDescription className={says}>{saysFor(a, post, schema)}</DialogDescription>
        </div>
        {body}
      </DialogContent>
    </Dialog>
  )
}

// -- the buttons -----------------------------------------------------------------------------

/** One button per action the server listed (then the note), with what stops it and its CLI line. */
export function Actions({ post, schema, host }: { post: PostDetail; schema: Schema; host: ActionsHost }) {
  const all = [...post.actions, post.note].filter((a): a is PostAction => a !== null)
  // The dialog is built from the post as it was when the button was pressed: the version, hash and
  // window the person is deciding on (UI_SPEC 3.3), whatever is reloaded behind it.
  const [dialog, setDialog] = React.useState<{ n: number; action: PostAction; post: PostDetail } | null>(null)
  const [open, setOpen] = React.useState(false)

  if (all.length === 0 && !dialog) {
    return <p className="text-sm text-label">This post is closed, so there is nothing to do.</p>
  }

  function start(action: PostAction) {
    setDialog((prev) => ({ n: (prev?.n ?? 0) + 1, action, post }))
    setOpen(true)
    host.opened()
  }

  const notes = all.filter((a) => (a.warning && a.id === "edit") || a.refusal)

  // Three parts, in this order: the buttons (pinned: sticky to the top of the panel's scroller, so
  // Approve and the others are always in view), what stops or warns about an action, and the CLI
  // lines behind a disclosure. The panel places them; they are siblings of its other sections.
  return (
    <>
      <div
        role="group"
        aria-label="Actions"
        data-panel-actions
        className="sticky top-0 z-10 -mx-6 bg-glass-solid px-6 py-3 shadow-card"
      >
        <ul className="flex flex-wrap gap-2">
          {all.map((a) => (
            <li key={a.id} data-action={a.id} data-enabled={a.enabled}>
              <button
                type="button"
                data-action-button={a.id}
                disabled={!a.enabled}
                aria-disabled={a.enabled ? undefined : "true"}
                onClick={() => start(a)}
                className={cn(pill, "min-h-10 px-4", a.id === "approve" && a.enabled ? solid : outlined)}
              >
                {a.label}
              </button>
            </li>
          ))}
        </ul>
      </div>
      {notes.length > 0 && (
        <ul className="flex flex-col gap-3 text-sm">
          {notes.map((a) => (
            <li key={a.id} data-action-note={a.id} className="flex flex-col gap-2">
              {a.warning && a.id === "edit" && <p className="text-label">{a.warning}</p>}
              {a.refusal && (
                <ErrorPanel error={a.refusal} blocking={false} className="bg-muted shadow-none" />
              )}
            </li>
          ))}
        </ul>
      )}
      <Disclosure title="Agent equivalents (CLI)">
        <ul className="flex flex-col gap-4">
          {all.map((a) => (
            <li key={a.id} data-cli-for={a.id}>
              <CliBlock cli={a.cli} label={a.label} />
            </li>
          ))}
        </ul>
      </Disclosure>
      {dialog && (
        <ActionDialog
          key={dialog.n}
          action={dialog.action}
          post={dialog.post}
          schema={schema}
          open={open}
          onOpenChange={setOpen}
          onComplete={(isOpen) => {
            if (isOpen) return
            setDialog(null)
            host.closed(dialog.action.id)
          }}
          onSent={(result) => {
            setOpen(false)
            void host.written(dialog.action.id, dialog.action.label, result)
          }}
          onStale={(current) => {
            setOpen(false)
            void host.stale(dialog.action.id, current)
          }}
        />
      )}
    </>
  )
}

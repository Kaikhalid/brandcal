"use client"

import { useAppData } from "@/components/app-data"
import { ErrorPanel } from "@/components/error-panel"
import { LoadingState } from "@/components/loading-state"
import { PlatformBadge } from "@/components/platform-swatch"
import { PageHeading } from "@/components/route-page"
import { SessionCard } from "@/components/session-card"
import { useShortcuts } from "@/components/shortcuts"
import { StatusChip } from "@/components/status-chip"
import { ThemeSwitcher } from "@/components/theme-switcher"
import { Kbd, KbdGroup } from "@/components/ui/kbd"
import { NAV_ITEMS } from "@/lib/nav"

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-4">
      <h2 id={id} className="text-xl">
        {title}
      </h2>
      {children}
    </section>
  )
}

function Row({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2 py-4 sm:flex-row sm:gap-6">
      <dt className="w-44 shrink-0 text-sm text-label">{term}</dt>
      <dd className="min-w-0 text-sm">{children}</dd>
    </div>
  )
}

function Shortcut({ keys, label }: { keys: React.ReactNode; label: string }) {
  return (
    <li className="flex items-center justify-between gap-4 py-2 text-sm">
      <span>{label}</span>
      <KbdGroup>{keys}</KbdGroup>
    </li>
  )
}

function SchemaSummary() {
  const { schema } = useAppData()
  if (schema.state === "loading") return <LoadingState label="Loading the rules" rows={2} />
  if (schema.state === "error") return <ErrorPanel error={schema.refusal} />
  const s = schema.data
  return (
    <dl className="card-surface divide-y divide-hairline px-6">
      <Row term="Timezone">{s.timezone ?? "Not set"}</Row>
      <Row term="Platforms">
        <ul className="flex flex-wrap gap-2">
          {Object.keys(s.platforms).map((id) => (
            <li key={id}>
              <PlatformBadge platform={id} />
            </li>
          ))}
        </ul>
      </Row>
      <Row term="Statuses">
        <ul className="flex flex-wrap gap-2">
          {s.states.map((id) => (
            <li key={id}>
              <StatusChip status={id} />
            </li>
          ))}
        </ul>
      </Row>
      <Row term="Needs you">
        <ul className="flex flex-wrap gap-2">
          {s.needs_you.map((id) => (
            <li key={id}>
              <StatusChip status={id} />
            </li>
          ))}
        </ul>
      </Row>
      <Row term="Post types">{s.post_types.join(", ")}</Row>
    </dl>
  )
}

function SettingsView() {
  const { enabled, setEnabled } = useShortcuts()
  return (
    <div className="flex flex-col gap-14">
      <PageHeading
        title="Settings"
        description="Appearance, keyboard shortcuts, your session and the rules the server enforces."
      />

      <Section id="appearance" title="Appearance">
        <div>
          <ThemeSwitcher />
        </div>
      </Section>

      <Section id="shortcuts" title="Keyboard shortcuts">
        <label className="flex w-fit items-center gap-3 py-2 text-sm">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
            className="size-6 accent-pill"
          />
          Single-key shortcuts
        </label>
        <p className="max-w-prose text-sm text-label">
          Turn these off if they clash with assistive technology. They never fire while you type in a
          field. Press <Kbd>g</Kbd> and then the second key.
        </p>
        <ul className="card-surface divide-y divide-hairline px-6">
          {NAV_ITEMS.map((item) => (
            <Shortcut
              key={item.href}
              label={`Go to ${item.label}`}
              keys={
                <>
                  <Kbd>g</Kbd>
                  <Kbd>{item.key}</Kbd>
                </>
              }
            />
          ))}
          <Shortcut label="Switch theme" keys={<Kbd>d</Kbd>} />
          <Shortcut label="Collapse or expand the sidebar" keys={<Kbd>[</Kbd>} />
          <Shortcut
            label="Collapse or expand the sidebar (always on)"
            keys={
              <>
                <Kbd>Ctrl</Kbd>
                <Kbd>B</Kbd>
              </>
            }
          />
        </ul>
      </Section>

      <Section id="session" title="Session">
        <SessionCard />
      </Section>

      <Section id="rules" title="Rules from the server">
        <SchemaSummary />
      </Section>
    </div>
  )
}

export { SettingsView }

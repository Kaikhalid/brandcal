# Olympus - Specification

**Version:** 1.0   **Date:** 2026-11-14   **Status:** Approved - Phases 1 to 9, and the unsigned local build in Phase 11 (2026-11-14). Phase 10 and signing are not approved.
**Supersedes:** nothing
**Blockers go to:** the final report

The user named the product "Olympus" on 2026-11-14.

## 0. North Star

- **Achievement:** A marketing lead installs one macOS app, pastes one Gemini API key, and gets a team of role-specific agents. The agents research, propose, write and illustrate posts into a brandcal calendar. The human approves each post in the app.
- **Value:** A small organisation gains the output of a marketing team without hiring one or learning agent tooling. brandcal's approval guarantees stay intact, so nothing is approved without a human decision.
- **Evidence of success:**
  1. On a Mac with no developer tools, the signed app opens, accepts a key, and shows a calendar within 4 onboarding screens.
  2. One brief typed by the user produces at least one post in state `pending_approval`, with text and one image, with no terminal use.
  3. `brandcal audit` on the app's calendar passes, and every approval row traces to a human click in the app.
  4. Changing the model for one role in Settings changes the model id sent on that role's next request, with no restart.
  5. A new role added as a data file appears in the Team view and can run, with no code change.
- **Looks like success but isn't:**
  1. Agents produce posts in a private store that brandcal never sees.
  2. A post reaches `approved` without a human click.
  3. The app works only when launched from a developer checkout with Python and Node installed.
  4. All roles call the same model, and the per-role setting changes a label only.
  5. The demo works with the developer's key, and a new user's free-tier key fails with an unexplained error.

## 1. Operator Charter


**C1. Words used in this spec.**
- *User:* the person who asked for the change. Only the user can approve this spec, change a locked item, or make a user-only decision.
- *North Star:* section 0 of this spec. It states what the change must achieve, for whom, and how anyone can tell.
- *Locked items:* the North Star, the Outcomes, the invariants, the locked decisions and the no-go list.
- *Claims:* statements about the current code. Each has a tag: *observed* (the author read it at the cited path:line), *inferred* (concluded from other facts) or *unverified* (not checked). A Claim may be wrong.
- *Suggestions:* anchors, code sketches, suggested commands and search recipes. They are starting points.
- *Outcome:* the observable result that must be true when a phase ends.
- *Touch set:* the files and symbols named under "Where" in the work items. The list is expected, not exclusive.
- *No-go list:* what must not be touched.
- *Blocker:* one of B1–B5 in C8.
- *Assumption:* a choice you made without asking, because it kept the three-question test (C7) at "yes".
- *Deviation Log:* your list of every place where the live code or your work differed from this spec. Keep it in a file named `[this spec's file name]-log.md` next to this spec.

**C2. Check the approval first.** Read the Status line at the top of this spec before you do anything else. Build only if it starts with "Approved". Build only the scope it names (end-to-end, or one named phase). If it says anything else, or there is no Status line, change nothing. Tell whoever started you that the spec needs the user's approval, and stop.

**C3. Your role.** You are the operator. You own the code. This spec was written by someone who studied the system, and the code may have changed since. Your job is to achieve the North Star. It is not to copy the spec. Build what is needed, in the way that fits the live code.

**C4. Priority when two things disagree.**
1. Locked items. Never change them. They describe what the change must achieve, even where the code behaves differently today.
2. The live code. If it differs from a Claim, follow the code.
3. Suggestions. Change them freely.
4. Anything this spec leaves open is your decision.

**C5. Verification pass.** Do this before you edit anything, even if you wrote this spec yourself in this session. The code may have changed, and re-reading it finds differences that memory misses.
1. Read the repository's instruction files (for example CLAUDE.md, AGENTS.md, README, the contributing guide) and follow them.
2. Run the search recipes in the "How to re-check" column of the Claims table, if the spec has one.
3. Check each Claim, and each file named in the work items, against the live code.
4. Run the test suite with the command the spec gives. If the spec gives none, use the project's usual test command. Record how many tests pass and fail, and name every failure that already exists. If there is no test suite, record that.
5. Start the Deviation Log with every difference you found.
6. Change your plan to match what is actually in the code.

**C6. Phase loop.** Work through the phases in dependency order (each phase lists what it depends on). For each phase:
1. Re-read the files you are about to edit.
2. Make the changes.
3. Write the tests from the phase's test contract.
4. Run the acceptance checks.
5. Run the full test suite. Every test that passed in the baseline must still pass, except tests that C10 allows you to update. Every new test must pass. Log any other difference and explain it.

A phase is done when its Outcome is observably true and all its acceptance checks pass. Start a phase only when every phase it depends on is done.

**C7. The three-question test.** Use it whenever the live code differs from the spec, and whenever you want to do something the spec does not say. Ask:
1. Does the change keep the North Star, this phase's Outcome and every locked decision true?
2. Does it stay outside the no-go list? Does it stay inside the touch set? A file outside the touch set is allowed only if it must change because of your change (such as a caller of a function you changed).
3. Can this phase's rollback step still undo it?

If all three answers are "yes", continue and log it. Do not ask anyone. Log it as type A if the difference is cosmetic (a rename, a moved line, different formatting). Log it as type B if you used a different mechanism with the same intent, or added something the spec did not foresee.

If any answer is "no", go to C8.

**C8. Resolve a "no" before you stop.** Try these steps in order.
1. Check whether the North Star, a locked decision or the Context already answers the question.
2. Check how this codebase already solves a similar problem.
3. Choose the most reversible option for which all three answers in C7 are "yes". Log it as an Assumption and continue.

If no such option exists, find the matching Blocker. A "no" to question 1 is B1. A "no" to question 2 is B2. A "no" to question 3 is B3. B4 and B5 apply whenever they describe the situation, even if all three answers are "yes". These five are the only Blockers:
- **B1:** the work cannot achieve a locked item by any means available to you.
- **B2:** the work would cross the no-go list. It would also be B2 if it changed something outside the touch set that the work does not require (for example other services, secrets, billing or production data).
- **B3:** the work needs an action that cannot be undone, and the spec does not describe it. Examples: deleting data, force-pushing, running a migration with no rollback, deploying.
- **B4:** the work needs a change to a security or permission boundary that the spec does not describe.
- **B5:** the work needs a decision from the user-only list.

Nothing else is a reason to stop. These are your decisions: naming, structure, where helpers go, style, wording of messages, test-framework details, and a check that was written wrongly.

**C9. Handling a Blocker.**
1. Stop only the work the Blocker affects, and the phases that depend on it.
2. Finish all the other work.
3. Write a Blocker report with these parts: what you were doing; what you found; which Blocker it is (B1–B5); the options you see; the option you would choose; what you did not do; what you finished meanwhile.
4. Send the report to the party named in "Blockers go to". By default, put it in the final report. Do not wait for a reply.
5. If no work can continue, stop and report.

**C10. When a check fails.**
1. Find out which is wrong: the code, the check, or the environment.
2. Trace the failure from the symptom to the first step where actual behaviour differs from expected (input, processing, storage, output). Fix it at that step, not at the symptom.
3. If the check was wrong, correct it so that it still verifies the Outcome. Log the change.

You must not do any of these:
- weaken, skip or delete a check to get a pass
- hard-code an expected value
- suppress an error to hide it
- write code you believe is wrong because a sketch showed it

You may update an existing test in two cases only. First, the test checks behaviour that this spec deliberately changes. Second, the test must follow a rename or a move, and its assertions stay the same. Log every such change with the reason. You must not edit any other existing test.

**C11. Working rules.**
- Read a file before you edit it.
- Change only what the work item needs. Do not refactor nearby code.
- Do not commit, push or deploy unless the spec says to.
- Restart a service only when the change cannot load without it.
- Never write secret values (keys, tokens, passwords) into code, logs or reports.
- For a bulk or mechanical edit: list every place to change with a command, and apply the rule. Then run the exit check the spec gives, such as "a search for X finds nothing outside Y".
- If you find an existing bug or failing test that blocks nothing: fix it only if the fix takes fewer than 10 lines and is in a file you are already editing. Log the fix. Otherwise log it as a follow-up.

**C12. Finish.**
1. Check the North Star's "Evidence of success" against the real system wherever you can (for example a request, a command-line call or a query).
2. Give a verdict: Achieved, Partly achieved, or Not achieved. Add the evidence.
3. Write the final report in the format below. Attach the Deviation Log and any Blocker reports.
4. Report failures plainly. Never describe a failing run as passing.

Each Deviation Log entry has these parts: type (A, B or Assumption); where; what the spec said; what you found; what you did; why all three answers in C7 were "yes".

```
Implementation complete.

North Star: [Achieved | Partly achieved | Not achieved] - [evidence]

Phases delivered:
  ✅ Phase 1: [title] - [acceptance checks passed / total]
  ...

Tests: baseline [x passed, y failed]; final [x passed, y failed]; new [n]
  (existing failures, unchanged: [list])

Deviations: [n] type A, [n] type B, [n] Assumptions   (full log attached)
Blockers: [none | list, with reports attached]
Follow-ups: [list]

Files changed:
  [path] - [one line]

Removed: [mechanisms, symbols, fields]
Added:   [mechanisms, symbols, fields]
Invariants confirmed: [list]
```


## 2. Context

### 2.1 Problem and evidence

brandcal is a Python command-line tool and SQLite library. Agents draft and schedule posts in one `brand.db` file. A human approver must approve each post. It has no agent team, no desktop app, and no model integration.

The user wants a self-contained macOS Electron app. In it, a team of marketing agents uses brandcal as its shared calendar. The user must be a non-technical person who can obtain an API key.

**Feasibility verdict: feasible, with four conditions.**

1. The bot code must be written for this app. CopilotKit/OpenBot cannot be embedded (see 2.2).
2. brandcal must ship inside the app as a bundled executable. brandcal has zero runtime dependencies, which keeps this practical.
3. Signing and notarisation need a Mac and a paid Apple Developer ID. A Linux cloud session can build and test, and cannot sign.
4. The "ego browser" tool was not readable from the planning session. It is an adapter behind an interface, built last.

### 2.2 Design rationale

This change only adds a new product in a new repository. It removes and weakens nothing in brandcal. brandcal's role checks, database triggers and hash chain stay the only path to the calendar.

**Why not build on CopilotKit/OpenBot.** Its application code is MIT. It needs Docker Compose, PostgreSQL and Bun. It depends on a component named CopilotKit Intelligence under a separate licence. Its desktop app uses Tauri, not Electron. A self-contained Electron app cannot contain those parts. Olympus borrows four ideas from it and no code: a roster of named bots, one workspace surface per bot, approval gates on writes, and a typed event stream from agent to interface.

**Why not the other "OpenBot" projects.** `nightly-labs/openbot` is excluded by the user: its licence forbids commercial use. `meetopenbot/openbot` is MIT but small, and documents no Gemini support.

**Why a TypeScript agent library, not a platform.** The app needs a tool-calling loop, per-role model choice and streaming. A library gives those with no server. The two candidates are the Vercel AI SDK with its Google provider, and Google's ADK for TypeScript. Both are Apache-2.0. Phase 1 picks one by test (decision D1).

**Why a new repository, not a branch.** brandcal is Python with a strict one-issue-one-change rule. Olympus is TypeScript with its own release cycle and signing. A branch would mix two toolchains and two sets of contributor rules. Olympus pins a released brandcal version instead.

**Why fewer roles first.** The user listed more than 8 functions. Each role adds cost per run and a failure point. Roles are data files (decision L9), so v1 ships 7 and more are added without code.

**Why search grounding before a browser.** Gemini's Google Search grounding and URL context cover trend, market and competitor reading with no browser session, login or captcha. A late-majority user must not manage a browser agent on day one. The browser sits behind an interface for the cases grounding cannot reach.

**Invariant:** Before and after this build, a post reaches `approved` only after a human decision, and every calendar change is made by a `brandcal` command.

### 2.3 Environment

- **Olympus repository:** new, created by the user (U1). This spec lives in the brandcal repository at `specs/olympus-spec.md` until the user moves it.
- **brandcal repository:** `Kaikhalid/brandcal`. Licence MIT. Python 3.11 or later. Zero runtime dependencies.
- **brandcal tests:** `python3 -m pytest` from the brandcal root.
- **Olympus runtime:** Node 22, Electron, React, TypeScript, Vite, Tailwind 4.
- **Olympus tests (to be created in Phase 2):** `npm test` runs unit tests. `npm run e2e` runs Playwright against the Electron app. On Linux, run e2e under `xvfb-run`.
- **Terms:**
  - *Sidecar:* the brandcal executable bundled inside the app.
  - *Olympus home:* the directory given to brandcal as `BRANDCAL_HOME`. It sits inside the app's user-data directory.
  - *Role:* one agent definition (see L9).
  - *Model slot:* a named setting that maps to one Gemini model id. The slots are `reasoning`, `writing`, `fast`, `image`.
  - *Run:* one execution of one role for one task, with a budget and a result.
  - *Brief:* a goal typed by the human that starts one or more runs.
  - *Brand profile:* the organisation's voice, audiences, content pillars, platforms and competitors, entered by the human.
  - *app.db:* Olympus's own SQLite file for runs, ideas, research notes and settings. It is never `brand.db`.

### 2.4 Claims

| # | Claim | Tag | How to re-check |
|---|---|---|---|
| K1 | brandcal prints one line of JSON per command, with `ok`, and on errors `error.code` and `error.next`. Exit codes are 0 and 2 to 9. | observed (brandcal `AGENTS.md`, `docs/ERRORS.md`) | Run `brandcal help` and one failing command. |
| K2 | brandcal has zero runtime dependencies and one console script `brandcal = brandcal.cli:main`. | observed (`pyproject.toml`) | Read `[project]` in `pyproject.toml`. |
| K3 | brandcal needs `BRANDCAL_HOME` or `--home`. It has no default. The home holds `brand.db` and `config.json`. | inferred (sub-agent read of `src/brandcal/config.py`) | `grep -n BRANDCAL_HOME src/brandcal/*.py` |
| K4 | Agents are declared in `config.json` as `agents: [{id, role}]`. `--as NAME` or `BRANDCAL_AGENT` selects one. Identity is self-declared. | inferred (sub-agent read of `cli.py`) | `grep -n "BRANDCAL_AGENT" src/brandcal/cli.py` |
| K5 | The approvals table allows channels `card`, `writer-session`, `legacy` and `console` only. `console` needs a verified identity. | observed (`src/brandcal/schema.sql`, the `channel` CHECK) | `grep -n "channel" src/brandcal/schema.sql` |
| K6 | The CLI refuses the `approver` role on every command. A manager records a card approval with `source_message_id` and `approver_words`. | inferred (sub-agent read of `transitions.py`, `approvals.py`) | `brandcal help approve` |
| K7 | brandcal has no MCP server and no HTTP API usable by agents. `brandcal serve` binds to 127.0.0.1. | inferred | `grep -rn "127.0.0.1" src/brandcal/serve.py` |
| K8 | The brandcal web UI uses Next.js 16, React 19, Tailwind 4 and `@base-ui/react`. | observed (`web/package.json`) | Read `web/package.json`. |
| K9 | CopilotKit/OpenBot is MIT, needs Docker and PostgreSQL, depends on separately licensed CopilotKit Intelligence, and ships a Tauri desktop app. | inferred (sub-agent read of its README and LICENSE on 2026-11-14) | Read the repository README and LICENSE. |
| K10 | The current Gemini JavaScript package is `@google/genai`. The key travels in the `x-goog-api-key` header to `generativelanguage.googleapis.com`. | unverified (search snippets; Google's documentation site was unreachable) | Read Google's Gemini API libraries page. |
| K11 | Gemini image generation is not available on the free tier. | unverified | Read Google's Gemini API pricing page. |
| K12 | Gemini model ids change often. No id in this spec is confirmed. | observed (conflicting ids across sources) | Call the API's model list endpoint with a real key. |
| K13 | `vercel-labs/ui` is the "UI SDK": headless behaviour packages under `@ui-sdk/*`, Apache-2.0, in beta, with an agent skill. | inferred (sub-agent read of the repository page) | Read the repository README. |
| K14 | `emilkowalski/skills` is MIT and contains guidance skills for coding agents. `sonner` and `vaul` are MIT. | inferred | Read each repository's LICENSE. |
| K15 | The "ego browser" skill exists only on the user's computer. Its interface is unknown. | unverified | The user supplies the skill text (U4). |
| K16 | Electron `safeStorage` encrypts with a key held in the macOS Keychain. | unverified (Electron's documentation site was unreachable) | Read Electron's `safeStorage` API page. |

## 3. Decisions

### 3.1 Locked decisions

- **L1. Separate repository.** Olympus's code lives in its own repository. It pins one released brandcal version. Reason: two toolchains and two rule sets. Rules out: Olympus code inside the brandcal repository.
- **L2. Self-contained macOS app.** The installed app runs with no Python, Node, Docker, database server or account other than the Gemini key. v1 ships for Apple silicon. Rules out: any required background service.
- **L3. No OpenBot code.** Olympus copies no code from any project named OpenBot. `nightly-labs/openbot` must not be read, used or referenced as a dependency. Reason: licence and architecture (2.2).
- **L4. brandcal is the only door to the calendar.** Every calendar read and write is a `brandcal` command run by the main process. Olympus must not open `brand.db`, its media files or its archives directly. Reason: brandcal's triggers, hash chain and audit depend on it.
- **L5. Humans decide.** Approve, request changes, reschedule and cancel happen only after a human click in the app. No agent tool exposes these four actions. The record of each decision names the click event. Rules out: auto-approval, including a "trusted" mode.
- **L6. One key, one provider, per-role models.** All model calls use one Gemini API key. Each role names a model slot. Settings maps each slot to a model id. A change applies to the next request with no restart.
- **L7. No hard-coded model ids in role files or call sites.** Default ids live in one file, `models.defaults.json`. The app validates them against the API's model list at onboarding. Reason: K12.
- **L8. The key never leaves the main process.** The key is stored only through Electron `safeStorage`. It must not appear in the renderer, in logs, in `app.db`, in `brand.db`, in crash reports or in agent prompts.
- **L9. Roles are data.** A role is one file with: id, display name, brandcal role, model slot, system prompt, tool list, and a default budget. A new role that uses existing tools needs no code change.
- **L10. v1 roster is 7 roles.** Strategist, Trend Scout, Competitor Monitor, Idea Generator, Copywriter, Designer, Editor. A separate non-model identity, Desk, records human decisions with brandcal role `manager`.
- **L11. Renderer isolation.** `contextIsolation` is on, `nodeIntegration` is off, and the sandbox is on. The renderer reaches the main process only through one typed, allow-listed IPC module. Remote content is never loaded in the app window.
- **L12. Every run is bounded.** Each run has a token budget, a step limit of 20 tool calls, and a cancel control. A monthly spend cap stops new runs when reached. The app shows estimated spend.
- **L13. Onboarding has at most 4 screens.** Welcome, key, brand profile, first brief. The key screen tests the key and states in plain words what works and what does not.
- **L14. No posting to social platforms in v1.** The human posts, then marks the post published in the app. Reason: platform terms and credential risk.
- **L15. One browser interface.** Any browser automation goes through one `BrowserTool` interface with one implementation per adapter. v1 research uses Gemini search grounding and URL context.
- **L16. Agent tools enforce the brandcal role.** A role's tool list is filtered by its brandcal role. A writer role cannot call a manager command even if its file lists it.
- **L17. Dependency licences.** Every shipped dependency is MIT, Apache-2.0, BSD or ISC. Rules out: AGPL, SSPL, BSL, "enterprise" directories and non-commercial licences.
- **L18. Fake data only.** Fixtures, screenshots and examples use `Example Co` and `example.com`. Every time carries an explicit UTC offset. Reason: brandcal's data rules.
- **L19. Approvals use the `card` channel.** Desk records each human decision on brandcal's existing `card` channel. The click event id is the `source_message_id`. Reason: the user chose it, and it needs no brandcal change.
- **L20. One human, one Mac, one local calendar.** v1 has one Olympus home on one Mac and one human user with many agents. Rules out: remote mode, sharing and accounts in v1.
- **L21. The interface follows brandcal's web UI.** Olympus reuses the structure, components, tokens and style rules of brandcal's `web/` directory and `docs/UI_STYLE.md`. Reason: the user chose it. Rules out: a new visual language.
- **L22. The browser adapter is after v1.** Phase 10 is not built in v1. The `BrowserTool` interface is not created until then.
- **L23. Distribution waits for proof of concept.** v1 ends with an unsigned build that runs on the user's Mac. Signing and notarisation are not built until the user supplies them.

### 3.2 Delegated to the operator

- **D1. Agent library.** Choose the Vercel AI SDK (`ai` with `@ai-sdk/google`) or Google ADK for TypeScript. Criteria, in order: runs inside the Electron main process with no server; one role can call a text model and another an image model with one key; calls go direct to Google with no gateway; streaming and tool calls work; licence meets L17. If both pass, choose the AI SDK.
- **D2. Build tooling.** Choose electron-vite or Electron Forge, and the packager. Criterion: produces a notarised `.dmg` containing the sidecar.
- **D3. Sidecar packaging.** Choose PyInstaller or an embedded standalone Python. Criterion: the packaged app runs `brandcal help` on a Mac with no Python, and passes notarisation.
- **D4. Interface components.** Copy components from brandcal's `web/` where one fits (L21). For a missing component, build it with Tailwind 4 and `@base-ui/react` in the same style. `@ui-sdk/*` packages must not be used in v1. `sonner` may be used for notices.
- **D5.** Test frameworks, the SQLite library for `app.db`, file layout, naming, wording of messages.

### 3.3 User-only decisions

- **U1.** Creating the Olympus repository, its owner and its visibility.
- **U3.** Apple Developer ID enrolment, and where signing credentials are kept.
- **U4.** The ego browser skill text, supplied after v1.
- **U5.** The default monthly spend cap.
- **U7.** Any change to brandcal itself.

## 4. Target design

All sketches are Suggestions. Adapt them to local conventions.

**Processes.** One Electron main process and one renderer window. The main process starts the sidecar once per command.

**Main-process modules.**

| Module | Job | Must not |
|---|---|---|
| `CalendarService` | Runs `brandcal` commands with `BRANDCAL_HOME` and `--as`. Parses the JSON line and exit code into a typed result. | Open `brand.db`. Retry a write blindly. |
| `KeyVault` | Stores and returns the key through `safeStorage`. | Return the key over IPC. |
| `ModelRouter` | Maps a role's model slot to a model id and a client call. | Hold ids outside `models.defaults.json` and Settings. |
| `RoleRegistry` | Loads and validates role files. Applies L16. | Execute anything. |
| `AgentRuntime` | Runs one role as a tool loop with budget, step limit and cancel. Emits typed events. | Call approve, request-changes, reschedule or cancel. |
| `Toolbox` | Calendar tools, research tools, image tool, notes tool, `BrowserTool`. | Reach the network except through `ModelRouter` and `BrowserTool`. |
| `RunStore` | Persists runs, events, ideas, research notes and spend in `app.db`. | Store the key or post content that belongs in brandcal. |
| `Desk` | Turns a human click into the matching `brandcal` manager command. | Act without a click event id. |
| `ipc` | The allow-listed typed bridge. | Expose a generic "run command" channel. |

**Flow of one brief.**

1. The human types a brief. The Strategist reads the brand profile and the calendar, and proposes tasks.
2. Trend Scout and Competitor Monitor write research notes to `app.db`, with source links.
3. Idea Generator turns notes into idea cards. The human keeps or discards each idea.
4. Copywriter creates the post with `brandcal add` and `part`.
5. Designer generates an image and attaches it with `brandcal media add`.
6. Editor runs `brandcal check`, fixes what it reports, then runs `brandcal submit`.
7. The post is `pending_approval`. The Inbox shows the preview card from `brandcal preview`.
8. The human clicks a decision. `Desk` records it. The post is scheduled.
9. The human posts it, then clicks "Mark published".

**Role to brandcal role and model slot.**

| Role | brandcal role | Model slot | Tools |
|---|---|---|---|
| Strategist | writer | reasoning | calendar read, notes, propose tasks |
| Trend Scout | writer | fast | search grounding, URL context, notes |
| Competitor Monitor | writer | fast | search grounding, URL context, notes, `BrowserTool` |
| Idea Generator | writer | writing | notes, ideas |
| Copywriter | writer | writing | calendar read, `add`, `edit`, `part` |
| Designer | writer | image | image generate, `media add` |
| Editor | writer | reasoning | `check`, `edit`, `submit` |
| Desk (no model) | manager | none | `preview`, `approve`, `request-changes`, `reschedule`, `cancel`, `schedule`, `published` |

**Screens.** Calendar (week and month). Inbox (decisions waiting for the human). Team (each role, its status, its last run, its model slot). Ideas. Research. Post detail. Settings (key, models, brand profile, spend).

**Interface rule for late-majority users.** Each screen has one primary action. No screen shows a model id, a token count or a JSON error unless the user opens "Details".

## 5. Phases

### Phase 1 - Proving spikes

**Outcome:** Three written decisions (D1, D2 with D3, D4) exist, each backed by a script that ran. No product code exists.
**Contribution to the North Star:** Removes the three unknowns that could make the app impossible to ship.
**Depends on:** U1.

#### 1.1 Work items
- **Agent library spike.** Intent: prove D1. Where: `spikes/agent/`. Change: with each candidate, run two roles with two model slots, one tool call, and one image generation, direct to Google.
- **Sidecar spike.** Intent: prove D2 and D3. Where: `spikes/sidecar/`. Change: package an empty Electron app containing brandcal. On a Mac, run `brandcal help` from the packaged app. Notarise it if U3 is done.
- **Interface spike.** Intent: prove D4. Where: `spikes/ui/`. Change: render one calendar week in an Electron renderer with the chosen component set.
- **Claims check.** Intent: settle K10, K11, K12 and K16. Change: read the official pages and record the result in `docs/decisions.md`.

#### 1.2 Acceptance checks
- [ ] `docs/decisions.md` records D1 to D4 with the evidence - check: read the file.
- [ ] The agent spike prints two different model ids from two roles - check: run it with a real key.
- [ ] The packaged spike app prints brandcal's help JSON with system Python removed from `PATH` - check: run on a Mac.

#### 1.3 Test contract
| Outcome tested | Source of the expected value | Kind | Wrong implementation it catches |
|---|---|---|---|
| Two roles use two models | The model ids in the spike's config, compared with ids in the request log | wiring | One client reused for all roles |
| Sidecar runs without Python | Help output from a developer checkout of the same brandcal version | preservation | Sidecar that calls system Python |

#### 1.4 Rollback
Delete the `spikes/` directory and `docs/decisions.md`.

#### 1.5 Blocker risks
B5 if U3 is not done: notarisation is then deferred to Phase 11 and logged. B1 if neither library passes D1.

### Phase 2 - App shell and security boundary

**Outcome:** `npm run dev` opens a window with empty navigation for all seven screens. The renderer cannot reach Node or the network.
**Contribution to the North Star:** The secure frame every later phase builds in.
**Depends on:** Phase 1.

#### 2.1 Work items
- **Scaffold.** Intent: a typed Electron, Vite, React project with lint, type-check, unit and e2e commands and CI. Where: repository root.
- **IPC bridge.** Intent: L11. Where: `src/main/ipc`, `src/preload`. Change: one allow-list of named channels with typed payloads and input validation.
- **Navigation shell.** Intent: the seven screens exist as empty routes.
- **Agent rules.** Intent: an `AGENTS.md` that carries L4, L5, L8, L17 and L18 for coding agents.

#### 2.2 Acceptance checks
- [ ] The app starts and shows seven navigation entries - check: `npm run e2e`.
- [ ] `window.require` and `window.process` are undefined in the renderer - check: an e2e test evaluates both.
- [ ] A request to an unknown IPC channel is refused - check: unit test.
- [ ] A licence check fails the build on a disallowed licence - check: add a fake AGPL package in a test fixture.

#### 2.3 Test contract
| Outcome tested | Source of the expected value | Kind | Wrong implementation it catches |
|---|---|---|---|
| Renderer has no Node access | L11 | rejection | `nodeIntegration` left on |
| Unknown or malformed IPC is refused | L11 | rejection | A generic pass-through channel |
| Disallowed licence fails CI | L17 | rejection | A check that only prints |

#### 2.4 Rollback
Revert the phase's commits.

#### 2.5 Blocker risks
None expected.

### Phase 3 - Calendar bridge

**Outcome:** On first launch the app creates a Olympus home with `brandcal init`. The Calendar screen lists posts read through the sidecar.
**Contribution to the North Star:** Makes brandcal the app's calendar, under L4.
**Depends on:** Phase 2.

#### 3.1 Work items
- **Sidecar build step.** Intent: the pinned brandcal version is built into the app resources by one script.
- **`CalendarService`.** Intent: one typed function per brandcal command in the Section 4 role table. Change: map exit codes 2 to 9 to typed errors that keep `error.code` and `error.next`.
- **Home setup.** Intent: create `config.json` with the timezone the user confirms, the 7 roles and Desk. Change: never guess a timezone silently.
- **Calendar screen.** Intent: week and month views from `list`, and post detail from `show`.

#### 3.2 Acceptance checks
- [ ] A post added with the sidecar from a terminal appears in the app after refresh - check: run `brandcal add` against the Olympus home.
- [ ] `brandcal audit` on the Olympus home reports ok after first launch - check: run it.
- [ ] No Olympus source file opens `brand.db` - check: `grep -rn "brand.db" src/` finds only the path passed to brandcal.

#### 3.3 Test contract
| Outcome tested | Source of the expected value | Kind | Wrong implementation it catches |
|---|---|---|---|
| Each brandcal exit code maps to its typed error | brandcal `docs/ERRORS.md` | invariant | Treating every non-zero exit as one error |
| The calendar shows what brandcal holds | Posts created by direct sidecar calls in the test | wiring | A cached or mocked list |
| A writer identity cannot run a manager command | brandcal's own refusal (exit 4) | rejection | `--as` hard-coded to the manager |
| Times keep their offsets end to end | The offset in the input | preservation | Conversion to local time on the way |

#### 3.4 Rollback
Revert the phase's commits. Delete the test Olympus home.

#### 3.5 Blocker risks
B2 if a needed read exists only by opening `brand.db`. B5 if the fix needs a brandcal change (U7).

### Phase 4 - Key onboarding and model router

**Outcome:** A new user completes the 4 onboarding screens. The key is stored. Settings shows four model slots with validated ids.
**Contribution to the North Star:** Evidence items 1 and 4.
**Depends on:** Phase 2.

#### 4.1 Work items
- **`KeyVault`.** Intent: L8.
- **`ModelRouter`.** Intent: L6 and L7. Change: read slots from Settings on every request.
- **Key test.** Intent: L13. Change: call the model list, then one cheap text call and one image call. Report each result in plain words. If image generation is refused, say so and keep the rest working.
- **Onboarding and Settings screens.** Intent: L13. Change: the brand profile form has at most 6 fields.

#### 4.2 Acceptance checks
- [ ] A wrong key shows a plain-language message and stores nothing - check: e2e with a fake key against a stub server.
- [ ] The key is absent from `app.db`, logs and the renderer - check: search all three for the test key string.
- [ ] Changing the `writing` slot changes the model id on the next request - check: stub server records the id.
- [ ] A real key completes onboarding - check: manual run with a real key.

#### 4.3 Test contract
| Outcome tested | Source of the expected value | Kind | Wrong implementation it catches |
|---|---|---|---|
| The slot setting drives the request | The id written to Settings by the test | wiring | An id cached at start-up |
| The key never crosses IPC | L8 | rejection | A "get key" channel |
| An unknown model id is refused at save time | The stub's model list | rejection | Saving any string |
| A text-only key leaves text roles usable | A stub that refuses image calls | preservation | One failed capability blocks onboarding |

#### 4.4 Rollback
Revert the phase's commits. Remove the stored test key.

#### 4.5 Blocker risks
B4 if the key must be exposed outside the main process for any feature.

### Phase 5 - Agent runtime with Copywriter and Editor

**Outcome:** From a one-line brief, the Copywriter creates a post and the Editor submits it. The post is `pending_approval` in brandcal.
**Contribution to the North Star:** Evidence item 2, text part. Evidence item 5.
**Depends on:** Phases 3 and 4.

#### 5.1 Work items
- **`RoleRegistry`.** Intent: L9 and L16. Change: validate each role file against a schema. Reject unknown tools.
- **`AgentRuntime`.** Intent: L12. Change: tool loop, budget, 20-step limit, cancel, typed event stream to the renderer.
- **Calendar tools.** Intent: wrap `CalendarService` functions as agent tools. Change: return brandcal's `error.next` to the model so it can correct itself.
- **`RunStore`.** Intent: persist runs, events and spend.
- **Role files.** Intent: Copywriter and Editor, with the brand profile injected.
- **Brief box.** Intent: one input on the Calendar screen that starts a run and shows progress in plain words.

#### 5.2 Acceptance checks
- [ ] A brief yields a post with status `pending_approval` - check: `brandcal show` on the Olympus home.
- [ ] A role file that lists `approve` fails to load - check: unit test.
- [ ] A run stops at its budget and reports why - check: stub model that never finishes.
- [ ] A role added as a new file appears in the registry with no code change - check: add a fixture role.

#### 5.3 Test contract
| Outcome tested | Source of the expected value | Kind | Wrong implementation it catches |
|---|---|---|---|
| The post exists in brandcal, not only in `app.db` | `brandcal show` output | wiring | Drafts kept in a private store |
| No tool reaches the four human decisions | L5 | rejection | A generic "run brandcal" tool |
| Budget and step limit stop a run | L12 | rejection | A limit that only logs |
| Cancel leaves no half-written post | brandcal state before the run | invariant | Cancel between `add` and `part` leaving junk unreported |
| Each role sends its own slot's model id | Settings values in the test | wiring | One model for all roles |

#### 5.4 Rollback
Revert the phase's commits. Posts created in test homes are deleted with the homes.

#### 5.5 Blocker risks
B4 if a tool needs a brandcal role above the one in the role table.

### Phase 6 - Approval Inbox

**Outcome:** The Inbox lists posts awaiting a decision. A human click approves, requests changes, reschedules or cancels. The decision is recorded by Desk through brandcal.
**Contribution to the North Star:** Evidence item 3.
**Depends on:** Phase 5.

#### 6.1 Work items
- **`Desk`.** Intent: L5. Change: each decision needs a click event id created in the main process from a real input event.
- **Inbox and post detail.** Intent: show the `brandcal preview` card, the content hash and the window. One primary action per card.
- **Changes loop.** Intent: "Request changes" with a note re-runs Copywriter and Editor on that post.
- **Mark published.**

#### 6.2 Acceptance checks
- [ ] After a click, the approvals row holds the click event id - check: `brandcal audit` and `brandcal show`.
- [ ] Editing an approved post returns it to `pending_approval` - check: edit through the app, then `brandcal show`.
- [ ] An IPC decision call with no matching click event is refused - check: unit test.

#### 6.3 Test contract
| Outcome tested | Source of the expected value | Kind | Wrong implementation it catches |
|---|---|---|---|
| No approval without a click | L5 | rejection | Renderer code or an agent calling the decision channel directly |
| The approval binds to the shown hash | The hash from `brandcal preview` | invariant | Approving whatever version is latest |
| A stale card is refused | brandcal exit code 6 after an edit | rejection | Swallowing the mismatch and retrying |

#### 6.4 Rollback
Revert the phase's commits.

#### 6.5 Blocker risks
B5 if the `card` channel cannot carry the click event id without a brandcal change (U7).

### Phase 7 - Research and ideas

**Outcome:** Strategist, Trend Scout, Competitor Monitor and Idea Generator run. The Research and Ideas screens show their output with source links. A kept idea starts a Copywriter run.
**Contribution to the North Star:** The "team" in the Achievement.
**Depends on:** Phase 5.

#### 7.1 Work items
- **Research tools.** Intent: search grounding and URL context through `ModelRouter`. Change: store every source link with its note.
- **Notes and ideas stores.**
- **Four role files.**
- **Strategist task proposal.** Intent: propose runs for the other roles. The human starts them in v1.
- **Research and Ideas screens.**

#### 7.2 Acceptance checks
- [ ] Each research note has at least one source link that opens - check: e2e against a stub, then one manual real run.
- [ ] Keeping an idea creates a post draft - check: `brandcal list`.
- [ ] Competitor names come from the brand profile only - check: change the profile, then compare the next run's queries.

#### 7.3 Test contract
| Outcome tested | Source of the expected value | Kind | Wrong implementation it catches |
|---|---|---|---|
| Notes carry real sources | Links returned by the stub's grounding data | wiring | Links invented by the model |
| The brand profile drives research | Profile values set by the test | wiring | Hard-coded example competitors |
| Discarded ideas create nothing in brandcal | Post count before and after | preservation | Eager post creation |

#### 7.4 Rollback
Revert the phase's commits.

#### 7.5 Blocker risks
None expected.

### Phase 8 - Designer and media

**Outcome:** The Designer generates an image for a post and attaches it through `brandcal media add`. The preview card shows it.
**Contribution to the North Star:** Evidence item 2, image part.
**Depends on:** Phases 5 and 6.

#### 8.1 Work items
- **Image tool.** Intent: generate through the `image` slot. Change: write the file to a staging directory, then hand it to brandcal.
- **Designer role file.** Change: every image gets alt text and a credit that states it is AI-generated.
- **Media in post detail.** Change: display through an IPC channel, not a file URL.
- **Graceful absence.** Intent: with a text-only key, the Designer is shown as unavailable with a plain reason.

#### 8.2 Acceptance checks
- [ ] A post has one media item with alt text - check: `brandcal show`.
- [ ] `brandcal check` passes on that post - check: run it.
- [ ] With image calls refused, the text pipeline still reaches `pending_approval` - check: stub.

#### 8.3 Test contract
| Outcome tested | Source of the expected value | Kind | Wrong implementation it catches |
|---|---|---|---|
| The media file is stored by brandcal | SHA-256 computed by the test over the generated file | wiring | A path saved in `app.db` only |
| Image failure does not block text | L13 | preservation | The whole run failing |
| Media must not be edited after attach | The content hash before and after viewing | invariant | Re-encoding on display |

#### 8.4 Rollback
Revert the phase's commits.

#### 8.5 Blocker risks
B1 if K11 is true and the user's key cannot generate images. This is reported, and the phase still ships the graceful absence.

### Phase 9 - Team view, schedules and spend

**Outcome:** The Team screen shows each role's state and last run. The human can set a role to run on a schedule. The monthly cap stops new runs.
**Contribution to the North Star:** Makes the agents a standing team, within L12.
**Depends on:** Phase 7.

#### 9.1 Work items
- **Team screen.**
- **Scheduler.** Intent: recurring runs while the app is open. Change: every routine starts with `brandcal sweep`, run as the system identity.
- **Spend tracking and cap.** Intent: L12 and U5.
- **Routines.** Intent: nightly `backup` and `export` of the Olympus home.

#### 9.2 Acceptance checks
- [ ] A scheduled role runs at its time and records a run - check: e2e with a fake clock.
- [ ] At the cap, a new run is refused with a plain message - check: set the cap to zero.
- [ ] A backup file exists after the nightly routine - check: list the backup directory.

#### 9.3 Test contract
| Outcome tested | Source of the expected value | Kind | Wrong implementation it catches |
|---|---|---|---|
| The cap blocks runs | The cap value set by the test | rejection | A warning with no stop |
| Scheduled runs still cannot decide | L5 | rejection | A scheduler path that bypasses Desk |
| Spend equals the sum of recorded usage | Usage figures from the stub | invariant | A fixed estimate per run |

#### 9.4 Rollback
Revert the phase's commits.

#### 9.5 Blocker risks
B5 until U5 is chosen. The operator may ship with the cap required at onboarding instead.

### Phase 10 - Browser adapter

**Outcome:** `BrowserTool` has one working adapter. Competitor Monitor can read a page that grounding cannot reach.
**Contribution to the North Star:** The user's stated wish for browser-driven agents, behind L15.
**Depends on:** Phase 7 and U4. Not approved for v1 (L22).

#### 10.1 Work items
- **`BrowserTool` interface.** Intent: `open`, `read`, `screenshot`, `close`. Read-only in v1.
- **Adapter.** Intent: implement against the ego browser as described in the text the user supplies.
- **Guard.** Intent: the adapter refuses form submission, login and any site not allowed in Settings.

#### 10.2 Acceptance checks
- [ ] Competitor Monitor returns text from a local test page through the adapter - check: e2e with a local server.
- [ ] A navigation to a site outside the allow-list is refused - check: unit test.

#### 10.3 Test contract
| Outcome tested | Source of the expected value | Kind | Wrong implementation it catches |
|---|---|---|---|
| Page text reaches the note | Content of the local test page | wiring | Falling back to search silently |
| Off-list sites are refused | The allow-list set by the test | rejection | A check on the first URL only, missed on redirect |

#### 10.4 Rollback
Revert the phase's commits. Roles lose the `BrowserTool` entry.

#### 10.5 Blocker risks
B5 until U4 is done. B4 if the adapter needs logged-in sessions.

### Phase 11 - Packaging and hardening

**Outcome:** A signed, notarised `.dmg` installs on a clean Mac and meets all five Evidence items.
**Contribution to the North Star:** Evidence item 1, and the final check of all others.
**Depends on:** all earlier phases in scope, and U3.

#### 11.1 Work items
- **Unsigned local build.** Intent: one command builds an unsigned app that runs on the user's Mac (L23).
- **Signing and notarisation (not approved, L23).** Intent: hardened runtime, the sidecar signed, the `.dmg` stapled. Must run on a Mac.
- **Clean-machine test.** Intent: a macOS user account with no developer tools.
- **Late-majority pass.** Intent: every error has a plain message and one next step. No screen shows raw JSON by default.
- **Documentation.** Intent: a README, a "get your key" guide with screenshots, and the licence notices file.
- **Full re-check.** Intent: run every earlier acceptance check.

#### 11.2 Acceptance checks
- [ ] `spctl --assess` accepts the installed app - check: run on a Mac.
- [ ] All five Evidence items hold on the clean account - check: follow the README only.
- [ ] `brandcal audit` passes after a full brief-to-published cycle - check: run it.
- [ ] The licence notices file lists every shipped dependency - check: compare with the lockfile.

#### 11.3 Test contract
| Outcome tested | Source of the expected value | Kind | Wrong implementation it catches |
|---|---|---|---|
| The packaged app needs no developer tools | A `PATH` with no Python or Node | preservation | A sidecar that works only in development |
| The full cycle keeps the audit chain valid | `brandcal audit` | invariant | Any direct database write |
| The key survives a restart and stays out of files | A search of the user-data directory for the test key | invariant | A plaintext fallback when `safeStorage` is unavailable |

#### 11.4 Rollback
Remove the release artefact. Code changes revert by commit.

#### 11.5 Blocker risks
B5 until U3 is done. B3: publishing a release is not undoable, so the operator builds the artefact and does not publish it.

## 6. Cross-phase invariants

1. Every calendar change is a `brandcal` command (L4).
2. No path approves, requests changes, reschedules or cancels without a human click (L5).
3. The key exists only in `safeStorage` and main-process memory (L8).
4. `brandcal audit` passes on every Olympus home the tests create.
5. All tests pass with no network access, using stubs. Real-key checks are manual and labelled.
6. No model id appears outside `models.defaults.json`, Settings and test fixtures (L7).

## 7. Non-goals and no-go list

**Non-goals for v1:** posting to social platforms; Windows or Linux builds; Intel Mac builds; multi-user accounts; models from providers other than Google; analytics on post performance; video generation; a mobile app.

**No-go list:**
- The brandcal repository. Any change there is U7.
- `brand.db`, its media and its archives, except through `brandcal`.
- Any code from a project named OpenBot. `nightly-labs/openbot` in any form.
- brandcal's `main` branch.
- Real personal data, real posts and real credentials in the repository.
- Publishing a release, or deploying anything.

## 8. Build plan with sub-agents

This section tells the orchestrator how to staff the phases. It does not change the Charter.

**Principle.** The expensive model writes and reviews. Cheap models build. Each sub-agent gets one work item, this spec's path, the files in scope, the check that proves it done, and the no-go list.

| Phase | Builder model | Reviewer | Parallel lanes |
|---|---|---|---|
| 1 Spikes | Sonnet-class for the agent and sidecar spikes; Haiku-class for the interface spike and the claims check | Orchestrator reads `docs/decisions.md` only | 4 |
| 2 Shell | Haiku-class for scaffold and screens; Sonnet-class for the IPC bridge | Orchestrator reviews the IPC diff | 2 |
| 3 Calendar bridge | Haiku-class | Sonnet-class reviews error mapping | 2: service, screen |
| 4 Key and router | Sonnet-class for `KeyVault`; Haiku-class for the rest | Orchestrator reviews `KeyVault` | 2 |
| 5 Runtime | Sonnet-class for `AgentRuntime` and L16; Haiku-class for role files, tools and the brief box | Orchestrator reviews the runtime diff | 3 |
| 6 Inbox | Sonnet-class for `Desk`; Haiku-class for screens | Orchestrator reviews `Desk` | 2 |
| 7 Research | Haiku-class | Sonnet-class spot check | 3 |
| 8 Designer | Haiku-class | Sonnet-class spot check | 1 |
| 9 Team and spend | Haiku-class | Sonnet-class spot check | 2 |
| 10 Browser | Sonnet-class | Orchestrator reviews the guard | 1 |
| 11 Packaging | Sonnet-class, on the user's Mac | Orchestrator reviews the final report | 1 |

**Rules for frugal runs.**
1. One sub-agent must not edit a file that another lane in the same phase edits. Lanes are split by directory.
2. A sub-agent returns a report of at most 300 words, plus test output. The orchestrator does not read its transcript.
3. The orchestrator reviews diffs only for the modules that hold a locked boundary: `ipc`, `KeyVault`, `AgentRuntime`, `Desk`, and the browser guard.
4. Phases 4 and 3 may run at the same time. Phases 7 and 6 may run at the same time. No other phases overlap.
5. If a Haiku-class builder fails the same acceptance check twice, the work item moves to a Sonnet-class builder. It does not get a third attempt.

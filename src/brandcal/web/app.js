"use strict";
// brandcal read-only views. All data comes from the JSON API; user text is only ever set with
// textContent. The server decides buttons, limits and refusals; this file only draws them.
(() => {
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const SVG_NS = "http://www.w3.org/2000/svg";
  const OFFSET = /^([+-])(\d{2}):?(\d{2})$/;
  const KINDS = [["idea", "The idea is dropped"], ["version", "This version is dropped"], ["plan", "The plan is dropped"]];

  const root = document.documentElement;
  const $ = (id) => document.getElementById(id);
  const state = { view: "week", date: "", platform: "", type: "", status: new Set(), post: "", schema: null, session: null, posts: [], needs: {}, details: new Map() };
  const seen = new Set();
  let loadSeq = 0;
  let panelSeq = 0;
  const NEEDS_KEY = "brandcal-needs";
  let opener = null;

  // ---- small helpers -------------------------------------------------------------------

  function el(tag, props = {}, ...kids) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key === "data") Object.assign(node.dataset, value);
      else node.setAttribute(key, value === true ? "" : value);
    }
    node.append(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
    return node;
  }

  function icon(kind, id) {
    const name = document.getElementById(`${kind}-${id}`) ? `${kind}-${id}` : `${kind}-generic`;
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "icon");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const use = document.createElementNS(SVG_NS, "use");
    use.setAttribute("href", `#${name}`);
    svg.append(use);
    return svg;
  }

  const words = (id) => {
    const text = String(id).replaceAll("_", " ");
    return text.charAt(0).toUpperCase() + text.slice(1);
  };
  const pad = (n) => String(n).padStart(2, "0");

  class ApiError extends Error {
    constructor(error, status, body = null) {
      super(error.message);
      this.error = error;
      this.status = status;
      this.body = body;
    }
  }

  // Writes carry the CSRF token the server bound to this identity (UI_SPEC 2.7).
  const postJson = (path, payload) => getJson(path, { method: "POST", headers: { "Content-Type": "application/json", "X-Brandcal-CSRF": state.session.csrf || "" }, body: JSON.stringify(payload) });

  async function getJson(path, init = {}) {
    let res;
    try {
      res = await fetch(path, { credentials: "same-origin", ...init });
    } catch {
      throw new ApiError({ code: "NO_REPLY", message: "The server did not answer.", next: "Check that brandcal serve is running, then reload." }, 0);
    }
    let body = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    if (!res.ok || !body || body.ok === false) {
      const error = body && body.error ? body.error : { code: `HTTP_${res.status}`, message: "The reply was not in the expected form.", next: "Reload; if it persists, tell the admin." };
      throw new ApiError(error, res.status, body);
    }
    return body;
  }

  // ---- time: always in the configured zone, from the server's strings --------------------

  function local(iso) {
    const ms = Date.parse(iso);
    const zone = state.schema.timezone === "Z" ? "+00:00" : state.schema.timezone;
    const m = OFFSET.exec(zone);
    if (m) {
      const shift = (m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3])) * 60000;
      const t = new Date(ms + shift);
      return { y: t.getUTCFullYear(), mo: t.getUTCMonth() + 1, d: t.getUTCDate(), time: `${pad(t.getUTCHours())}:${pad(t.getUTCMinutes())}` };
    }
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: zone, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric", hour: "numeric", minute: "numeric" }).formatToParts(ms).map((p) => [p.type, p.value]));
    return { y: Number(parts.year), mo: Number(parts.month), d: Number(parts.day), time: `${parts.hour}:${parts.minute}` };
  }

  const dateKey = (t) => `${t.y}-${pad(t.mo)}-${pad(t.d)}`;
  const parseDate = (key) => key.split("-").map(Number);
  const dowOf = (key) => { const [y, m, d] = parseDate(key); return new Date(Date.UTC(y, m - 1, d)).getUTCDay(); };
  function addDays(key, n) {
    const [y, m, d] = parseDate(key);
    const t = new Date(Date.UTC(y, m - 1, d + n));
    return `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())}`;
  }
  const weekStart = (key) => addDays(key, -((dowOf(key) + 6) % 7));
  const today = () => dateKey(local(new Date().toISOString()));
  const dayLabel = (key) => { const [, m, d] = parseDate(key); return `${DAYS[dowOf(key)]} ${d} ${MONTHS[m - 1].slice(0, 3)}`; };

  function span(win) {
    const [a, b] = win.split("/");
    const start = local(a);
    return { day: dateKey(start), from: start.time, to: local(b).time, text: `${start.time} to ${local(b).time}` };
  }

  function range() {
    if (state.view === "week") {
      const from = weekStart(state.date);
      return [from, addDays(from, 6)];
    }
    const [y, m] = parseDate(state.date);
    const last = `${y}-${pad(m)}-${pad(new Date(Date.UTC(y, m, 0)).getUTCDate())}`;
    return [weekStart(`${y}-${pad(m)}-01`), addDays(weekStart(last), 6)];
  }

  function rangeLabel() {
    const [y, m] = parseDate(state.date);
    if (state.view === "month") return `${MONTHS[m - 1]} ${y}`;
    const [from, to] = range();
    const [, fm, fd] = parseDate(from);
    const [ty, tm, td] = parseDate(to);
    return fm === tm ? `${fd} to ${td} ${MONTHS[tm - 1]} ${ty}` : `${fd} ${MONTHS[fm - 1].slice(0, 3)} to ${td} ${MONTHS[tm - 1].slice(0, 3)} ${ty}`;
  }

  // ---- url state ---------------------------------------------------------------------

  function readUrl() {
    const q = new URLSearchParams(location.search);
    state.view = q.get("view") === "month" ? "month" : "week";
    // No date in the URL: "today" needs the schema's zone, so start() fills it in once loaded.
    state.date = /^\d{4}-\d{2}-\d{2}$/.test(q.get("date") || "") ? q.get("date") : "";
    state.platform = q.get("platform") || "";
    state.type = q.get("type") || "";
    state.status = new Set((q.get("status") || "").split(",").filter(Boolean));
    state.post = q.get("post") || "";
  }

  function writeUrl() {
    const q = new URLSearchParams({ view: state.view, date: state.date });
    if (state.platform) q.set("platform", state.platform);
    if (state.type) q.set("type", state.type);
    if (state.status.size) q.set("status", [...state.status].join(","));
    if (state.post) q.set("post", state.post);
    history.replaceState(null, "", `?${q}`);
  }

  // ---- errors --------------------------------------------------------------------------

  function showError(err) {
    const box = $("error");
    if (!(err instanceof ApiError)) console.error(err);
    const e = err instanceof ApiError ? err.error : { code: "BROWSER_ERROR", message: "The page could not show this data.", next: "Reload the page." };
    box.replaceChildren(
      el("div", { class: "code mono", text: e.code }),
      el("p", { text: e.message || "No reason was given." }),
      el("p", {}, el("strong", { text: "What to do: " }), e.next || "Reload the page."),
    );
    box.hidden = false;
  }

  const hideError = () => { $("error").hidden = true; };

  // ---- pieces --------------------------------------------------------------------------

  const statusChip = (id) => el("span", { class: "status", data: { status: id } }, icon("status", id), words(id));
  const platformTag = (id) => el("span", { class: "tag" }, icon("platform", id), id);
  const typeTag = (id) => el("span", { class: "tag" }, icon("type", id), id);

  function badges(post) {
    const out = [];
    if (post.native_scheduled_at) out.push(el("span", { class: "badge" }, icon("ui", "queue"), "Natively scheduled"));
    if (post.claimed_by) out.push(el("span", { class: "badge" }, icon("ui", "claimed"), `Claimed by ${post.claimed_by}`));
    if (post.hold_until) out.push(el("span", { class: "badge" }, icon("ui", "hold"), "On hold"));
    return out;
  }

  function card(post, detail, compact) {
    const w = span(post.window);
    const kind = detail ? detail.post_type : "";
    const button = el("button", { type: "button", class: compact ? "card compact rise" : "card rise", data: { status: post.status, id: post.id }, title: post.window.replace("/", " to ") });
    if (state.post === post.id) button.setAttribute("aria-current", "true");
    if (compact) {
      button.append(icon("status", post.status), el("span", { class: "when num", text: w.from }), el("span", { class: "title", text: post.title, title: post.title }));
      button.setAttribute("aria-label", `${post.title}, ${words(post.status)}, ${post.platform}, ${kind}, ${w.text}`);
    } else {
      button.append(
        statusChip(post.status),
        el("span", { class: "when num", text: w.text }),
        el("span", { class: "title", text: post.title }),
        el("span", { class: "row" }, platformTag(post.platform), kind && typeTag(kind), detail && badges(detail)),
      );
    }
    button.addEventListener("click", () => openPost(post.id, button));
    return button;
  }

  // ---- views ---------------------------------------------------------------------------

  function visible() {
    return state.posts.filter((p) => {
      const kind = state.details.get(p.id)?.post_type;
      return (!state.platform || p.platform === state.platform) && (!state.type || kind === state.type) && (!state.status.size || state.status.has(p.status));
    });
  }

  const needs = () => state.schema.needs_you.filter((s) => state.schema.states.includes(s));

  function renderNeeds() {
    const box = $("needs");
    box.replaceChildren();
    $("needs-counts").replaceChildren(...needs().map((id) => el("span", { class: "cnt", data: { status: id } }, icon("status", id), words(id), el("span", { class: "num", text: String((state.needs[id] || []).length) }))));
    needs().forEach((id) => {
      const list = state.needs[id] || [];
      const ul = el("ul", {});
      for (const p of list) {
        const w = span(p.window);
        const item = el("button", { type: "button", class: "need-item", data: { id: p.id }, title: p.window.replace("/", " to ") }, icon("platform", p.platform), el("span", { class: "title", text: p.title }), el("span", { class: "when num", text: `${dayLabel(w.day)}, ${w.from}` }));
        if (state.post === p.id) item.setAttribute("aria-current", "true");
        item.addEventListener("click", () => openPost(p.id, item));
        ul.append(el("li", {}, item));
      }
      box.append(el("section", { class: "need rise", data: { status: id, chunk: 0 }, "aria-label": words(id) }, el("h3", {}, icon("status", id), words(id), el("span", { class: "num", text: String(list.length) })), list.length ? ul : el("p", { class: "none", text: "Nothing here." })));
    });
  }

  function renderWeek(posts) {
    const [from] = range();
    const box = $("calendar");
    box.replaceChildren();
    const grid = el("div", { class: "week" });
    for (let i = 0; i < 7; i++) {
      const key = addDays(from, i);
      const mine = posts.filter((p) => span(p.window).day === key);
      const head = el("h3", { class: "day-head" }, DAYS[dowOf(key)], el("span", { class: "num", text: String(parseDate(key)[2]) }));
      if (key === today()) {
        head.setAttribute("aria-current", "date");
        head.append(el("span", { class: "today-tag", text: "Today" }));
      }
      const col = el("section", { class: "col rise", data: { chunk: 1 + Math.floor(i / 2) }, "aria-label": dayLabel(key) }, head, ...mine.map((p) => card(p, state.details.get(p.id), false)));
      if (!mine.length) col.append(el("p", { class: "none", text: "Nothing planned." }));
      grid.append(col);
    }
    box.append(grid);
  }

  function renderMonth(posts) {
    const [from, to] = range();
    const [, month] = parseDate(state.date);
    const grid = el("div", { class: "month" });
    DAYS.slice(1).concat(DAYS[0]).forEach((d) => grid.append(el("div", { class: "dow", text: d })));
    for (let key = from, n = 0; key <= to; key = addDays(key, 1), n++) {
      const mine = posts.filter((p) => span(p.window).day === key);
      const cell = el("div", { class: "day rise", role: "group", "aria-label": dayLabel(key), data: { chunk: Math.floor(n / 7), outside: String(parseDate(key)[1] !== month) } }, el("div", { class: "day-top" }, el("span", { class: "num", text: String(parseDate(key)[2]) })));
      if (key === today()) {
        cell.setAttribute("aria-current", "date");
        cell.firstChild.append(el("span", { class: "today-tag", text: "Today" }));
      }
      mine.slice(0, 3).forEach((p) => cell.append(card(p, state.details.get(p.id), true)));
      if (mine.length > 3) {
        const more = el("button", { type: "button", class: "more", text: `+${mine.length - 3} more` });
        more.addEventListener("click", () => { state.view = "week"; state.date = key; syncControls(); load(); });
        cell.append(more);
      }
      grid.append(cell);
    }
    $("calendar").replaceChildren(grid);
  }

  function render() {
    $("range").textContent = rangeLabel();
    const first = !seen.has(state.view);
    const box = [$("needs"), $("calendar")];
    renderNeeds();
    const posts = visible();
    if (state.view === "week") renderWeek(posts);
    else renderMonth(posts);
    // Stagger only the first time a view is drawn; updates and navigation appear instantly.
    box.forEach((b) => b.classList.toggle("enter", first));
    if (first) {
      document.querySelectorAll(".rise").forEach((n) => n.style.setProperty("--d", `${Number(n.dataset.chunk || 0) * 100}ms`));
      window.setTimeout(() => box.forEach((b) => b.classList.remove("enter")), 1600);
    }
    seen.add(state.view);
  }

  async function load() {
    const mine = ++loadSeq;
    writeUrl();
    try {
      const [from, to] = range();
      const wanted = needs();
      const [list, ...needLists] = await Promise.all([getJson(`/api/posts?${new URLSearchParams({ from, to, closed: "1" })}`), ...wanted.map((s) => getJson(`/api/posts?status=${s}`))]);
      const details = new Map();
      await Promise.all(list.posts.map(async (p) => details.set(p.id, await getJson(`/api/posts/${encodeURIComponent(p.id)}`))));
      if (mine !== loadSeq) return;
      state.posts = list.posts;
      state.details = details;
      state.needs = Object.fromEntries(wanted.map((s, i) => [s, needLists[i].posts]));
      hideError();
      render();
    } catch (err) {
      if (mine === loadSeq) showError(err);
    }
    if (!root.dataset.ready) requestAnimationFrame(() => requestAnimationFrame(() => { root.dataset.ready = "1"; }));
  }

  // ---- side panel ----------------------------------------------------------------------

  function section(title, ...kids) {
    return el("section", { class: "sec" }, title && el("h3", { text: title }), ...kids);
  }

  function dl(rows) {
    const list = el("dl", {});
    for (const [label, value] of rows) {
      if (value === null || value === undefined || value === "") continue;
      list.append(el("dt", { text: label }), el("dd", {}, value));
    }
    return list;
  }

  const full = (iso) => { const t = local(iso); return `${dayLabel(dateKey(t))} ${t.y}, ${t.time}`; };

  function textParts(post) {
    const limits = (state.schema.platforms[post.platform] || {}).chars_per_post;
    return post.parts.map((part) => {
      const n = [...part.text].length;
      const over = limits && n > limits;
      return section(post.parts.length > 1 ? `Part ${part.pos} of ${post.parts.length}` : "Text", el("pre", { class: "text", text: part.text }), el("p", { class: "count num" }, limits ? `${n} / ${limits} characters` : `${n} characters`, over && el("span", { class: "over", text: `TOO_LONG: ${n - limits} over` })));
    });
  }

  function mediaBlock(post) {
    if (!post.media.length) return null;
    return section("Media", ...post.media.map((m, i) => {
      const src = `/api/media/${encodeURIComponent(post.id)}/${i + 1}`;
      const alt = (m.alt_text || "").trim();
      const shown = m.kind === "image" || m.kind === "gif" ? el("img", { src, alt, loading: "lazy" }) : el("a", { href: src, text: `${words(m.kind)} file ${i + 1}` });
      return el("figure", {}, shown, el("figcaption", {}, alt ? el("span", {}, el("strong", { text: "Alt text: " }), alt) : el("span", { class: "warn", text: "No alt text. Add it before approval." })));
    }));
  }

  function link(value) {
    return /^https?:/.test(value) ? el("a", { href: value, rel: "noopener noreferrer", target: "_blank", text: value }) : value;
  }

  function details(post) {
    const live = [post.platform_url, ...post.parts.map((p) => p.platform_url)].filter(Boolean);
    return section("Details", dl([
      ["First comment", post.first_comment],
      ["Target URL", post.target_url && link(post.target_url)],
      ["Campaign", post.campaign],
      ["Pillar", post.pillar],
      ["Owner", post.owner],
      ["Notes", post.notes],
      ["Live URL", live.length ? el("span", {}, ...[...new Set(live)].map((u) => el("div", {}, link(u)))) : null],
      ["Claimed", post.claimed_by && `${post.claimed_by} until ${full(post.claim_expires)}`],
      ["Queued on platform", post.native_scheduled_at && full(post.native_scheduled_at)],
      ["On hold until", post.hold_until && `${full(post.hold_until)}${post.hold_reason ? ` (${post.hold_reason})` : ""}`],
      ["Closed", post.closed_at && full(post.closed_at)],
    ]));
  }

  function identityTag(detail) {
    if (!detail) return null;
    if (detail.via === "console") return `console (verified: ${detail.identity})`;
    if (detail.source === "dev-unverified") return "dev (unverified)";
    return null;
  }

  function versionHistory(post, events) {
    const changes = events.filter((e) => e.action === "add" || e.action === "edit" || e.action === "media_add" || e.action.startsWith("part"));
    const decided = post.approvals.map((a) => el("li", {}, el("span", {}, el("strong", { text: `${words(a.decision)} ` }), `on version ${a.content_version}, fingerprint `, el("code", { text: a.content_hash.slice(0, 8) })), el("span", { class: "muted num", text: `${a.decided_by} via ${a.channel === "console" ? `console (verified: ${a.verified_identity})` : a.channel}, ${full(a.decided_at)}` }), a.approver_words && el("span", { text: `"${a.approver_words}"` }), a.changes_requested && el("span", { class: "muted", text: formatChanges(a.changes_requested) })));
    return section("Version history", el("p", { class: "num" }, `Now version ${post.content_version}, fingerprint `, el("code", { text: post.content_hash.slice(0, 8) })), el("ul", { class: "list" }, ...changes.map((e) => el("li", {}, el("span", { text: `${words(e.action)} by ${e.actor}` }), el("span", { class: "muted num", text: full(e.at) })))), decided.length ? el("h3", { text: "Decisions" }) : null, decided.length ? el("ul", { class: "list" }, ...decided) : null);
  }

  function formatChanges(raw) {
    try {
      const c = JSON.parse(raw);
      return `What: ${c.what}. Where: ${c.where}. Instruction: ${c.instruction}.`;
    } catch {
      return String(raw);
    }
  }

  function audit(events) {
    return section("Audit trail", el("ol", { class: "list" }, ...events.map((e) => {
      const tag = identityTag(e.detail);
      return el("li", {}, el("span", {}, el("strong", { text: words(e.action) }), ` by ${e.actor}`, e.from_status && e.to_status && e.from_status !== e.to_status ? `: ${words(e.from_status)} to ${words(e.to_status)}` : ""), el("span", { class: "muted num", text: `${full(e.at)}${tag ? `, ${tag}` : ""}` }), e.reason && el("span", { text: e.reason }));
    })));
  }

  // ---- write actions: every one goes through a confirm dialog ---------------------------------

  const field = (label, control, hint) => el("label", { class: "field" }, el("span", { text: label }), control, hint && el("small", { class: "muted", text: hint }));
  const seenBy = (post) => ({ version: post.content_version, hash: post.content_hash, window: post.window });
  const short = (post) => `version ${post.content_version} (fingerprint ${post.content_hash.slice(0, 8)}) of "${post.title}"`;

  // What each action asks for, what it will do, and the request it sends.
  function formFor(a, post) {
    const when = span(post.window).text;
    const text = (name, value = "") => el("textarea", { name, rows: 3, required: true }, value);
    switch (a.id) {
      case "approve":
        return { fields: [], says: `Approve ${short(post)}, to be published ${dayLabel(span(post.window).day)}, ${when}. The post can then be published inside that window.`, body: () => ({ ...seenBy(post) }) };
      case "request-changes":
        return { fields: [field("What is wrong", text("what")), field("Where it is", text("where")), field("What the writer should do", text("instruction"))], says: `Send ${short(post)} back to the writer. All three fields are required.`, body: (f) => ({ ...seenBy(post), what: f.what, where: f.where, instruction: f.instruction }) };
      case "reschedule":
        return { fields: [field("New window", el("input", { name: "new_window", type: "text", required: true, value: post.window, spellcheck: "false" }), state.schema.time_format)], says: `Change only the time of ${short(post)}. The text stays as approved.`, body: (f) => ({ ...seenBy(post), new_window: f.new_window }) };
      case "cancel":
        return { fields: [field("What is cancelled", el("select", { name: "kind" }, ...KINDS.map(([v, t]) => el("option", { value: v, text: `${words(v)}: ${t}` })))), field("Reason", text("reason"))], says: `Cancel "${post.title}". This closes the post and cannot be undone.`, danger: true, body: (f) => ({ ...seenBy(post), kind: f.kind, reason: f.reason }) };
      case "submit":
        return { fields: [], says: `Submit ${short(post)} for approval again.`, body: () => ({}) };
      case "note":
        return { fields: [field("Note", text("text"))], says: `Add a note to "${post.title}". It does not change the content.`, body: (f) => ({ text: f.text }) };
      default: {
        const first = (post.parts[0] || {}).text || "";
        return {
          fields: [
            ...post.parts.map((p) => field(post.parts.length > 1 ? `Text, part ${p.pos}` : "Text", el("textarea", { name: `part-${p.pos}`, rows: 5, required: true }, p.text))),
            field("First comment", el("textarea", { name: "first_comment", rows: 2 }, post.first_comment || "")),
            field("Target URL", el("input", { name: "target_url", type: "text", value: post.target_url || "", spellcheck: "false" })),
            ...post.media.map((m, i) => field(`Alt text, file ${i + 1}`, el("input", { name: `alt-${i + 1}`, type: "text", required: true, value: m.alt_text || "" }))),
            field("Window", el("input", { name: "window", type: "text", required: true, value: post.window, spellcheck: "false" }), "Changing only the window needs no new approval."),
          ],
          says: `${a.warning} Saving never approves; you approve the new version as a separate step. (First text starts: "${first.slice(0, 40)}")`,
          body: (f) => {
            const fields = {};
            for (const k of ["first_comment", "target_url", "window"]) if (f[k] !== (post[k] || "")) fields[k] = f[k];
            const parts = {};
            post.parts.forEach((p) => { if (f[`part-${p.pos}`] !== p.text) parts[p.pos] = f[`part-${p.pos}`]; });
            const alt_texts = {};
            post.media.forEach((m, i) => { if (f[`alt-${i + 1}`] !== (m.alt_text || "")) alt_texts[i + 1] = f[`alt-${i + 1}`]; });
            return { fields, parts, alt_texts };
          },
        };
      }
    }
  }

  function confirmDialog(a, post, opener) {
    const spec = formFor(a, post);
    const errorBox = el("div", { class: "refusal", role: "alert", hidden: true });
    const go = el("button", { type: "submit", class: spec.danger ? "btn primary danger" : "btn primary", text: a.id === "approve" ? `Approve version ${post.content_version}` : a.label });
    const back = el("button", { type: "button", class: "btn", text: "Go back" });
    const form = el("form", { method: "dialog", class: "form" }, el("h2", { id: "confirm-title", text: a.label }), el("p", { class: "says", text: spec.says }), ...spec.fields, el("p", { class: "muted", text: "Agent equivalent (CLI)" }), el("code", { class: "cli", text: a.cli }), el("p", { class: "muted", text: "This console action records channel console with your verified identity." }), errorBox, el("div", { class: "row end" }, back, go));
    const dlg = el("dialog", { class: "confirm", "aria-labelledby": "confirm-title" }, form);
    const close = () => { dlg.close(); dlg.remove(); };
    back.addEventListener("click", close);
    dlg.addEventListener("cancel", () => window.setTimeout(() => dlg.remove(), 0));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!form.reportValidity()) return;
      go.disabled = true;
      go.setAttribute("aria-busy", "true");
      const values = Object.fromEntries(new FormData(form).entries());
      try {
        const res = await postJson(`/api/posts/${encodeURIComponent(post.id)}/${a.id}`, spec.body(values));
        close();
        $("notice").textContent = `${a.label}: done. ${post.title} is now ${words(res.status)}, version ${res.version}.`;
        await Promise.all([openPost(post.id, opener, { refocus: a.id }), load()]);
      } catch (err) {
        go.disabled = false;
        go.removeAttribute("aria-busy");
        if (err instanceof ApiError && err.error.code === "STALE_APPROVAL") {
          const now = err.body && err.body.current ? err.body.current.content_version : "a newer version";
          close();
          await openPost(post.id, opener, { banner: `This post changed (version ${post.content_version} to ${now}). Read it again before deciding. Nothing was recorded.` });
          await load();
          return;
        }
        const e2 = err instanceof ApiError ? err.error : { code: "BROWSER_ERROR", message: "The page could not send this.", next: "Reload the page." };
        errorBox.replaceChildren(el("div", { class: "code mono", text: e2.code }), el("p", { text: e2.message }), el("p", {}, el("strong", { text: "What to do: " }), e2.next || "Reload the page."));
        errorBox.hidden = false;
      }
    });
    document.body.append(dlg);
    dlg.showModal();
    // A decision with no fields opens on "Go back", so a stray Enter never approves (U3 review M3).
    (dlg.querySelector("textarea, input, select") || back).focus();
  }

  function actionRows(post) {
    const all = [...post.actions, post.note].filter(Boolean);
    const rows = all.map((a) => {
      const button = el("button", { type: "button", class: "btn action", data: { action: a.id }, disabled: !a.enabled, "aria-disabled": a.enabled ? null : "true", text: a.label });
      button.addEventListener("click", () => confirmDialog(a, post, button));
      return el("div", { class: "action-row" },
        button,
        a.warning && a.id === "edit" && el("p", { class: "muted", text: a.warning }),
        a.refusal && el("p", { class: "reason" }, el("span", { class: "code mono", text: a.refusal.code }), ` ${a.refusal.message} `, el("strong", { text: "What to do: " }), a.refusal.next),
        el("p", { class: "muted", text: "Agent equivalent (CLI)" }),
        el("code", { class: "cli", text: a.cli }));
    });
    return section("Actions", ...(rows.length ? rows : [el("p", { class: "muted", text: "This post is closed, so there is nothing to do." })]));
  }

  // ---- text diff between two versions (line based, no library) -------------------------------

  const flat = (v) => [...v.parts.flatMap((t, i) => [`Part ${i + 1}:`, ...t.split("\n")]), `First comment: ${v.first_comment || ""}`, `Target URL: ${v.target_url || ""}`, ...v.alt_texts.map((t, i) => `Alt text ${i + 1}: ${t}`)];

  function diffLines(a, b) {
    const n = a.length, m = b.length;
    const t = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) t[i][j] = a[i] === b[j] ? t[i + 1][j + 1] + 1 : Math.max(t[i + 1][j], t[i][j + 1]);
    const out = [];
    let i = 0, j = 0;
    while (i < n && j < m) {
      if (a[i] === b[j]) { out.push([" ", a[i]]); i++; j++; } else if (t[i + 1][j] >= t[i][j + 1]) out.push(["-", a[i++]]); else out.push(["+", b[j++]]);
    }
    while (i < n) out.push(["-", a[i++]]);
    while (j < m) out.push(["+", b[j++]]);
    return out;
  }

  function versionDiff(versions) {
    if (versions.length < 2) return null;
    const pick = (label, value) => el("select", { "aria-label": label }, ...versions.map((v) => el("option", { value: v.version, text: `Version ${v.version}` })), null);
    const from = pick("Compare from", 0), to = pick("Compare to", 0);
    from.value = versions[versions.length - 2].version;
    to.value = versions[versions.length - 1].version;
    const out = el("pre", { class: "diff", "aria-live": "polite" });
    const draw = () => {
      const find = (s) => versions.find((v) => String(v.version) === s.value);
      out.replaceChildren(...diffLines(flat(find(from)), flat(find(to))).map(([sign, line]) => el("span", { class: `diff-line ${sign === "+" ? "add" : sign === "-" ? "del" : "same"}`, text: `${sign} ${line}\n` })));
    };
    from.addEventListener("change", draw);
    to.addEventListener("change", draw);
    draw();
    return section("Compare versions", el("div", { class: "row" }, from, el("span", { class: "muted", text: "to" }), to), out);
  }

  async function copy(text, status) {
    try {
      await navigator.clipboard.writeText(text);
      status.textContent = "Copied the full hash";
    } catch {
      status.textContent = "Could not copy; the full hash is in the page source";
    }
    window.setTimeout(() => { status.textContent = ""; }, 2500);
  }

  function renderPanel(post, events, versions, banner) {
    const panel = $("panel");
    const close = el("button", { type: "button", class: "icon-btn", "aria-label": "Close panel" }, icon("ui", "close"));
    close.addEventListener("click", closePanel);
    const status = el("span", { class: "muted", role: "status" });
    const fp = el("button", { type: "button", class: "fp", "aria-label": `Fingerprint ${post.content_hash.slice(0, 8)}. Copy the full hash` }, el("code", { text: post.content_hash.slice(0, 8) }), icon("ui", "copy"));
    fp.addEventListener("click", () => copy(post.content_hash, status));
    const w = span(post.window);
    const blocks = [
      banner && el("p", { class: "refusal stale", role: "alert", text: banner }),
      el("section", { class: "sec head", data: { status: post.status } }, el("h2", { id: "panel-title", text: post.title }), close, el("div", { class: "row" }, statusChip(post.status), platformTag(post.platform), typeTag(post.post_type), ...badges(post))),
      section(null, dl([["Post", el("code", { text: post.id })], ["When", `${dayLabel(w.day)}, ${w.text}`], ["Window", el("code", { text: post.window })], ["Version", String(post.content_version)], ["Fingerprint", el("span", { class: "row" }, fp, status)]])),
      ...textParts(post), mediaBlock(post), details(post), versionHistory(post, events), versionDiff(versions), audit(events), actionRows(post),
    ];
    panel.replaceChildren(...blocks.filter(Boolean));
    panel.scrollTop = 0;
  }

  async function openPost(id, from, opts = {}) {
    const mine = ++panelSeq;
    opener = from || null;
    try {
      const path = `/api/posts/${encodeURIComponent(id)}`;
      const [post, ev, vs] = await Promise.all([getJson(path), getJson(`/api/events?post=${encodeURIComponent(id)}`), getJson(`${path}/versions`)]);
      if (mine !== panelSeq) return;
      state.post = id;
      renderPanel(post, ev.events, vs.versions, opts.banner);
      const panel = $("panel");
      // Sit below the floating toolbar so its controls (theme, filters) stay reachable.
      panel.style.setProperty("top", `${Math.round(document.querySelector(".bar").getBoundingClientRect().bottom + 12)}px`);
      panel.inert = false;
      panel.setAttribute("aria-hidden", "false");
      panel.dataset.open = "true";
      markCurrent();
      writeUrl();
      hideError();
      (panel.querySelector(`[data-action="${opts.refocus}"]:not([disabled])`) || panel.querySelector(".icon-btn")).focus({ preventScroll: true });
    } catch (err) {
      if (mine === panelSeq) showError(err);
    }
  }

  function markCurrent() {
    document.querySelectorAll("[data-id]").forEach((n) => (n.dataset.id === state.post ? n.setAttribute("aria-current", "true") : n.removeAttribute("aria-current")));
  }

  function closePanel() {
    const panel = $("panel");
    if (panel.dataset.open !== "true") return;
    panelSeq++;
    panel.dataset.open = "false";
    panel.setAttribute("aria-hidden", "true");
    panel.inert = true;
    state.post = "";
    markCurrent();
    writeUrl();
    const back = opener && document.contains(opener) ? opener : null;
    (back || $("main")).focus({ preventScroll: true });
    opener = null;
  }

  // ---- controls ------------------------------------------------------------------------

  function buildFilters() {
    const box = $("filters");
    const select = (label, key, values) => {
      const node = el("select", { id: `f-${key}` }, el("option", { value: "", text: `All ${label.toLowerCase()}s` }), ...values.map((v) => el("option", { value: v, text: v })));
      node.value = state[key];
      node.addEventListener("change", () => { state[key] = node.value; load(); });
      return el("label", {}, label, node);
    };
    const chips = state.schema.states.map((id) => {
      const chip = el("button", { type: "button", class: "chip", "aria-pressed": String(state.status.has(id)), data: { status: id }, style: null }, icon("status", id), words(id));
      chip.style.setProperty("--chip-ink", "var(--st)");
      chip.addEventListener("click", () => {
        if (state.status.has(id)) state.status.delete(id);
        else state.status.add(id);
        chip.setAttribute("aria-pressed", String(state.status.has(id)));
        load();
      });
      return chip;
    });
    box.replaceChildren(select("Platform", "platform", Object.keys(state.schema.platforms)), select("Type", "type", state.schema.post_types), el("div", { class: "group", role: "group", "aria-label": "Status" }, ...chips));
  }

  function syncControls() {
    document.querySelector(`input[name="view"][value="${state.view}"]`).checked = true;
  }

  function wire() {
    document.querySelectorAll('input[name="view"]').forEach((r) => r.addEventListener("change", () => { state.view = r.value; load(); }));
    const theme = window.brandcalTheme;
    const current = document.querySelector(`input[name="theme"][value="${theme.preference()}"]`);
    current.checked = true;
    document.querySelectorAll('input[name="theme"]').forEach((r) => r.addEventListener("change", () => theme.set(r.value)));
    const step = (n) => {
      if (state.view === "week") state.date = addDays(state.date, 7 * n);
      else { const [y, m] = parseDate(state.date); const t = new Date(Date.UTC(y, m - 1 + n, 1)); state.date = `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-01`; }
      load();
    };
    $("prev").addEventListener("click", () => step(-1));
    $("next").addEventListener("click", () => step(1));
    $("today").addEventListener("click", () => { state.date = today(); load(); });
    $("scrim").addEventListener("click", closePanel);
    const toggle = $("needs-toggle");
    const collapse = (on) => {
      toggle.setAttribute("aria-expanded", String(!on));
      $("needs").hidden = on;
    };
    try { collapse(localStorage.getItem(NEEDS_KEY) === "collapsed"); } catch (err) { collapse(false); }
    toggle.addEventListener("click", () => {
      const on = toggle.getAttribute("aria-expanded") === "true";
      collapse(on);
      try { localStorage.setItem(NEEDS_KEY, on ? "collapsed" : "open"); } catch (err) { /* not remembered */ }
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !document.querySelector("dialog[open]")) closePanel(); });
  }

  async function loadSprite() {
    const res = await fetch("/mvp/icons.svg", { credentials: "same-origin" });
    const doc = new DOMParser().parseFromString(await res.text(), "image/svg+xml");
    const sprite = document.importNode(doc.documentElement, true);
    sprite.setAttribute("class", "sr");
    document.body.prepend(sprite);
  }

  async function start() {
    readUrl();
    wire();
    try {
      await loadSprite();
      const [session, schema] = await Promise.all([getJson("/api/session"), getJson("/api/schema")]);
      state.session = session;
      state.schema = schema;
      if (!state.date) state.date = today();
      if (session.source === "dev-unverified") {
        const banner = $("banner");
        banner.textContent = "UNVERIFIED (dev): no identity is checked and every change is refused.";
        banner.hidden = false;
      } else {
        $("who").textContent = `${session.identity} (${session.role})`;
      }
      syncControls();
      buildFilters();
      await load();
      if (state.post) openPost(state.post, null);
    } catch (err) {
      showError(err);
      root.dataset.ready = "1";
    }
  }

  start();
})();

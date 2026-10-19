"use strict";
// brandcal read-only views. All data comes from the JSON API; user text is only ever set with
// textContent. The server decides buttons, limits and refusals; this file only draws them.
(() => {
  const NEEDS = ["pending_approval", "changes_requested", "missed"];
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const SVG_NS = "http://www.w3.org/2000/svg";
  const OFFSET = /^([+-])(\d{2}):?(\d{2})$/;
  // The equivalent CLI line for each button id (the CLI cannot record console decisions).
  const CLI = {
    approve: (p) => `brandcal approve ${p.id} --version ${p.content_version} --hash ${p.content_hash.slice(0, 8)} --channel card --msg MSG_ID --words "APPROVER'S WORDS" --approver NAME --as NAME`,
    "request-changes": (p) => `brandcal request-changes ${p.id} --version ${p.content_version} --hash ${p.content_hash.slice(0, 8)} --msg MSG_ID --words "APPROVER'S WORDS" --what "..." --where "..." --instruction "..." --approver NAME --as NAME`,
    reschedule: (p) => `brandcal reschedule ${p.id} --version ${p.content_version} --hash ${p.content_hash.slice(0, 8)} --window "${p.window}" --msg MSG_ID --words "APPROVER'S WORDS" --approver NAME --as NAME`,
    cancel: (p) => `brandcal cancel ${p.id} --kind idea --reason "WHY" --as NAME`,
    edit: (p) => `brandcal edit ${p.id} FIELD=VALUE --as NAME`,
    submit: (p) => `brandcal submit ${p.id} --as NAME`,
  };

  const root = document.documentElement;
  const $ = (id) => document.getElementById(id);
  const state = { view: "week", date: "", platform: "", type: "", status: new Set(), post: "", schema: null, session: null, posts: [], needs: {}, details: new Map() };
  const seen = new Set();
  let loadSeq = 0;
  let panelSeq = 0;
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
    constructor(error, status) {
      super(error.message);
      this.error = error;
      this.status = status;
    }
  }

  async function getJson(path) {
    let res;
    try {
      res = await fetch(path, { credentials: "same-origin" });
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
      throw new ApiError(error, res.status);
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
    state.date = /^\d{4}-\d{2}-\d{2}$/.test(q.get("date") || "") ? q.get("date") : today();
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
      button.append(icon("status", post.status), el("span", { class: "when num", text: w.from }), el("span", { class: "title", text: post.title }));
      button.setAttribute("aria-label", `${post.title}, ${words(post.status)}, ${post.platform}, ${kind}, ${w.text}`);
    } else {
      button.append(
        el("span", { class: "row between" }, statusChip(post.status), el("span", { class: "when num", text: w.text })),
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

  function renderNeeds() {
    const box = $("needs");
    box.replaceChildren();
    NEEDS.filter((s) => state.schema.states.includes(s)).forEach((id, i) => {
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
      if (key === today()) head.setAttribute("aria-current", "date");
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
      const cell = el("div", { class: "day rise", role: "group", "aria-label": dayLabel(key), data: { chunk: Math.floor(n / 7), outside: String(parseDate(key)[1] !== month) } }, el("span", { class: "num", text: String(parseDate(key)[2]) }));
      if (key === today()) cell.setAttribute("aria-current", "date");
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
      const wanted = NEEDS.filter((s) => state.schema.states.includes(s));
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

  function actionRows(post) {
    const rows = post.actions.map((a) => {
      const line = (CLI[a.id] || (() => `brandcal help ${a.id}`))(post);
      return el("div", { class: "action-row" },
        el("button", { type: "button", class: "action", disabled: true, "aria-disabled": "true", text: a.label }),
        a.warning && el("p", { class: "muted", text: a.warning }),
        a.refusal ? el("p", { class: "reason" }, el("span", { class: "code mono", text: a.refusal.code }), ` ${a.refusal.message} `, el("strong", { text: "What to do: " }), a.refusal.next) : el("p", { class: "muted", text: "You may do this, but this version of the console is read-only." }),
        el("p", { class: "muted", text: "Equivalent command:" }),
        el("code", { class: "cli", text: line }));
    });
    return section("Actions", ...(rows.length ? rows : [el("p", { class: "muted", text: "This post is closed, so there is nothing to do." })]));
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

  function renderPanel(post, events) {
    const panel = $("panel");
    const close = el("button", { type: "button", class: "icon-btn", "aria-label": "Close panel" }, icon("ui", "close"));
    close.addEventListener("click", closePanel);
    const status = el("span", { class: "muted", role: "status" });
    const fp = el("button", { type: "button", class: "fp", "aria-label": `Fingerprint ${post.content_hash.slice(0, 8)}. Copy the full hash` }, el("code", { text: post.content_hash.slice(0, 8) }), icon("ui", "copy"));
    fp.addEventListener("click", () => copy(post.content_hash, status));
    const w = span(post.window);
    const blocks = [
      el("section", { class: "sec head", data: { status: post.status } }, el("h2", { id: "panel-title", text: post.title }), close, el("div", { class: "row" }, statusChip(post.status), platformTag(post.platform), typeTag(post.post_type), ...badges(post))),
      section(null, dl([["Post", el("code", { text: post.id })], ["When", `${dayLabel(w.day)}, ${w.text}`], ["Window", el("code", { text: post.window })], ["Version", String(post.content_version)], ["Fingerprint", el("span", { class: "row" }, fp, status)]])),
      ...textParts(post), mediaBlock(post), details(post), versionHistory(post, events), audit(events), actionRows(post),
    ];
    panel.replaceChildren(...blocks.filter(Boolean));
    panel.scrollTop = 0;
  }

  async function openPost(id, from) {
    const mine = ++panelSeq;
    opener = from || null;
    try {
      const [post, ev] = await Promise.all([getJson(`/api/posts/${encodeURIComponent(id)}`), getJson(`/api/events?post=${encodeURIComponent(id)}`)]);
      if (mine !== panelSeq) return;
      state.post = id;
      renderPanel(post, ev.events);
      const panel = $("panel");
      // Sit below the floating toolbar so its controls (theme, filters) stay reachable.
      panel.style.setProperty("top", `${Math.round(document.querySelector(".bar").getBoundingClientRect().bottom + 12)}px`);
      panel.inert = false;
      panel.setAttribute("aria-hidden", "false");
      panel.dataset.open = "true";
      markCurrent();
      writeUrl();
      hideError();
      panel.querySelector(".icon-btn").focus({ preventScroll: true });
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
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePanel(); });
  }

  async function loadSprite() {
    const res = await fetch("/icons.svg", { credentials: "same-origin" });
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

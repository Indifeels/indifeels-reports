/* Indifeels Project Board: admin-only kanban.
   Tables: board_tasks, board_comments, board_attachments (+ private storage bucket board-attachments). */
window.BoardPanel = (() => {
  const COLS = [
    { id: "backlog", name: "Backlog" },
    { id: "todo", name: "To Do" },
    { id: "progress", name: "In Progress" },
    { id: "done", name: "Done" },
    { id: "stuck", name: "Roadblocks" }
  ];
  const PRI = {
    risk: "Most risky",
    none: "No priority",
    low: "Fix, not urgent",
    med: "Fix, a bit urgent",
    urgent: "Very urgent, today",
    done: "Completed"
  };
  const BUCKET = "board-attachments";
  const MAX_FILE = 10 * 1024 * 1024;
  const ALLOWED = [
    "image/png", "image/jpeg", "image/webp", "image/gif", "image/heic", "application/pdf", "text/plain", "text/csv",
    "application/msword", "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
  ];
  const SELECT = "id,title,col,pri,prev,pos,source,created_at,due_date,board_comments(count),board_attachments(count)";
  const REFRESH_MS = 60 * 60 * 1000;

  let sb, me, root, tasks = [], dragging = false, pending = false, timer, lastLoad = 0, lanes = {}, dlg = null, justDragged = 0;

  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const uid = () => (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36);
  const byId = (id) => tasks.find((t) => t.id === id);
  const myName = () => (me && (me.display_name || me.username)) || "Admin";
  const say = (msg, err) => { const s = root && root.querySelector(".bp-status"); if (s) { s.textContent = msg || ""; s.className = "bp-status" + (err ? " err" : ""); } };
  const stampText = () => "Last refreshed " + new Date().toLocaleString("en-AU", { timeZone: "Australia/Melbourne", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  const when = (iso) => new Date(iso).toLocaleString("en-AU", { timeZone: "Australia/Melbourne", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  const plural = (n, w) => n + " " + w + (n === 1 ? "" : "s");
  const sizeText = (n) => n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
  const norm = (r) => ({ ...r, n_comments: r.board_comments?.[0]?.count ?? 0, n_files: r.board_attachments?.[0]?.count ?? 0 });

  /* ---------- dates (Melbourne calendar day) ---------- */
  const todayMel = () => new Date().toLocaleDateString("en-CA", { timeZone: "Australia/Melbourne" });
  const dayNum = (iso) => { const [y, m, d] = iso.split("-").map(Number); return Date.UTC(y, m - 1, d) / 86400000; };
  const daysUntil = (iso) => dayNum(iso) - dayNum(todayMel());
  const addDays = (n) => new Date((dayNum(todayMel()) + n) * 86400000).toISOString().slice(0, 10);
  const fmtDate = (iso) => {
    const [y, m, d] = iso.split("-").map(Number);
    const sameYear = String(y) === todayMel().slice(0, 4);
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-AU", { timeZone: "UTC", day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }) });
  };
  const isOverdue = (t) => !!t.due_date && t.col !== "done" && daysUntil(t.due_date) < 0;
  function dueChip(t) {
    if (!t.due_date) return null;
    if (t.col === "done") return { text: "Due " + fmtDate(t.due_date), cls: "muted" };
    const d = daysUntil(t.due_date);
    if (d < 0) return { text: "Overdue " + (-d) + "d", cls: "late" };
    if (d === 0) return { text: "Due today", cls: "today" };
    if (d === 1) return { text: "Due tomorrow", cls: "soon" };
    return { text: "Due " + fmtDate(t.due_date), cls: "" };
  }

  /* ---------- data ---------- */
  async function load() {
    const { data, error } = await sb.from("board_tasks").select(SELECT).order("pos");
    if (error) { say("Couldn't load the board: " + error.message, true); return; }
    tasks = (data || []).map(norm);
    lastLoad = Date.now();
    const st = root.querySelector(".bp-stamp"); if (st) st.textContent = stampText();
    say("");
    if (dlg) {
      const nt = byId(dlg.t.id);
      if (!nt) closeDetail(); else { dlg.t = nt; paintMeta(); }
    }
    if (dragging) { pending = true; return; }
    render();
  }
  async function put(id, patch) {
    const t = byId(id); if (t) Object.assign(t, patch);
    const { error } = await sb.from("board_tasks").update(patch).eq("id", id);
    if (error) { say("Couldn't save that change: " + error.message, true); await load(); }
  }
  async function add(colId, title) {
    const pos = tasks.filter((t) => t.col === colId).reduce((m, t) => Math.max(m, t.pos || 0), 0) + 1000;
    const row = { title, col: colId, pri: colId === "done" ? "done" : "none", pos, source: "manual" };
    const { data, error } = await sb.from("board_tasks").insert(row).select(SELECT).single();
    if (error) { say("Couldn't add the task: " + error.message, true); return; }
    tasks.push(norm(data)); render();
  }
  async function del(id) {
    const { data: files } = await sb.from("board_attachments").select("path").eq("task_id", id);
    tasks = tasks.filter((t) => t.id !== id);
    if (dlg && dlg.t.id === id) closeDetail();
    render();
    const { error } = await sb.from("board_tasks").delete().eq("id", id);
    if (error) { say("Couldn't delete the task: " + error.message, true); await load(); return; }
    if (files && files.length) { try { await sb.storage.from(BUCKET).remove(files.map((f) => f.path)); } catch (_) {} }
  }
  function setPriority(t, k) {
    const patch = { pri: k };
    if (k === "done") { if (t.pri !== "done") patch.prev = t.pri || "none"; patch.col = "done"; }
    else if (t.col === "done") patch.col = "todo";
    return put(t.id, patch);
  }
  function moveTo(t, colId) {
    if (t.col === colId) return Promise.resolve();
    const pos = tasks.filter((x) => x.col === colId).reduce((m, x) => Math.max(m, x.pos || 0), 0) + 1000;
    const patch = { col: colId, pos };
    if (colId === "done" && t.pri !== "done") { patch.prev = t.pri || "none"; patch.pri = "done"; }
    else if (t.col === "done" && colId !== "done") patch.pri = (t.prev && t.prev !== "done") ? t.prev : "none";
    return put(t.id, patch);
  }

  /* ---------- board ---------- */
  function build() {
    root.innerHTML = "";
    const shell = el("div", "bp");
    const head = el("div", "bp-head");
    head.append(el("h2", "", "Indifeels Project Board"));
    const meta = el("div", "bp-meta");
    const late = el("span", "bp-late"); late.hidden = true;
    meta.append(late, el("span", "bp-stamp", "Loading…"));
    const btn = el("button", "bp-btn", "Refresh"); btn.type = "button"; btn.addEventListener("click", load);
    meta.append(btn); head.append(meta);
    shell.append(head, el("div", "bp-status"));
    const alerts = el("div", "bp-alerts"); alerts.hidden = true;
    alerts.append(el("span", "", "Get a phone alert each morning when a task is overdue."));
    const on = el("button", "bp-btn", "Turn on phone alerts"); on.type = "button";
    on.addEventListener("click", () => { document.getElementById("m-push")?.click(); [2000, 6000, 15000].forEach((ms) => setTimeout(pushHint, ms)); });
    alerts.append(on);
    shell.append(alerts);
    const legend = el("div", "bp-legend");
    Object.entries(PRI).forEach(([k, label]) => legend.append(el("span", "p-" + k, label)));
    shell.append(legend);
    const board = el("div", "bp-board");
    lanes = {};
    COLS.forEach((c) => {
      const lane = el("section", "bp-lane"); lane.dataset.col = c.id;
      const h = el("h3"); h.append(el("span", "", c.name)); const count = el("span", "bp-count", "0"); h.append(count);
      const cards = el("div", "bp-cards");
      const form = el("form", "bp-add");
      const input = el("input"); input.placeholder = "+ Add task"; input.maxLength = 200; input.autocomplete = "off"; input.setAttribute("aria-label", "Add task to " + c.name);
      const go = el("button", "", "Add"); go.type = "submit";
      form.append(input, go);
      form.addEventListener("submit", (e) => { e.preventDefault(); const v = input.value.trim(); if (!v) return; input.value = ""; add(c.id, v); input.focus(); });
      lane.append(h, cards, form); board.append(lane);
      lanes[c.id] = { lane, cards, count };
    });
    shell.append(board); root.append(shell);
  }

  async function pushHint() {
    const box = root && root.querySelector(".bp-alerts"); if (!box) return;
    try {
      if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window) || Notification.permission === "denied") { box.hidden = true; return; }
      const reg = await navigator.serviceWorker.ready;
      box.hidden = !!(await reg.pushManager.getSubscription());
    } catch (_) { box.hidden = true; }
  }

  function render() {
    COLS.forEach((c) => {
      const L = lanes[c.id];
      const list = tasks.filter((t) => t.col === c.id).sort((a, b) => (a.pos || 0) - (b.pos || 0));
      L.count.textContent = String(list.length);
      L.cards.replaceChildren();
      if (!list.length) L.cards.append(el("div", "bp-empty", "Nothing here yet. Add a task below or drag one in."));
      list.forEach((t) => L.cards.append(card(t)));
    });
    const n = tasks.filter(isOverdue).length;
    const late = root.querySelector(".bp-late");
    late.hidden = !n; late.textContent = n ? n + " overdue" : "";
  }

  function card(t) {
    const pri = PRI[t.pri] ? t.pri : "none";
    const d = el("div", "bp-card p-" + pri + (isOverdue(t) ? " is-late" : "")); d.dataset.id = t.id;
    d.tabIndex = 0; d.setAttribute("role", "button"); d.setAttribute("aria-label", "Open task: " + (t.title || ""));
    const grip = el("div", "bp-grip", "⋮⋮"); grip.setAttribute("aria-hidden", "true");
    const dot = el("button", "bp-pri"); dot.type = "button"; dot.title = "Change priority: " + PRI[pri]; dot.setAttribute("aria-label", "Change priority, now " + PRI[pri]);
    dot.addEventListener("click", (e) => { e.stopPropagation(); menu(dot, t); });
    const main = el("div", "bp-main");
    main.append(el("div", "bp-title", t.title || ""));
    const chips = el("div", "bp-chips");
    const due = dueChip(t);
    if (due) chips.append(el("span", "bp-chip " + due.cls, due.text));
    if (t.n_comments) chips.append(el("span", "bp-chip", plural(t.n_comments, "comment")));
    if (t.n_files) chips.append(el("span", "bp-chip", plural(t.n_files, "file")));
    if (chips.children.length) main.append(chips);
    const x = el("button", "bp-x", "✕"); x.type = "button"; x.title = "Delete task"; x.setAttribute("aria-label", "Delete task");
    let timeout = null;
    x.addEventListener("click", (e) => {
      e.stopPropagation();
      if (x.classList.contains("arm")) { clearTimeout(timeout); del(t.id); }
      else { x.classList.add("arm"); x.textContent = "Delete?"; timeout = setTimeout(() => { x.classList.remove("arm"); x.textContent = "✕"; }, 2500); }
    });
    d.append(grip, dot, main, x);
    d.addEventListener("click", (e) => {
      if (e.target.closest("button") || e.target.closest(".bp-grip")) return;
      if (Date.now() - justDragged < 400) return;
      openDetail(byId(t.id) || t);
    });
    d.addEventListener("keydown", (e) => { if (e.target === d && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openDetail(byId(t.id) || t); } });
    d.addEventListener("pointerdown", (e) => startDrag(e, d, t));
    return d;
  }

  /* ---------- drag and drop (mouse; on touch, drag from the handle) ---------- */
  function startDrag(e, node, t) {
    if (e.button !== undefined && e.button !== 0) return;
    if (e.target.closest("button")) return;
    if (e.pointerType === "touch" && !e.target.closest(".bp-grip")) return;
    const sx = e.clientX, sy = e.clientY;
    let started = false, ghost = null, ph = null, offX = 0, offY = 0;
    const rect = node.getBoundingClientRect();
    const move = (ev) => {
      if (!started) {
        if (Math.hypot(ev.clientX - sx, ev.clientY - sy) < 6) return;
        started = true; dragging = true;
        offX = sx - rect.left; offY = sy - rect.top;
        ghost = node.cloneNode(true); ghost.classList.add("bp-ghost"); ghost.style.width = rect.width + "px";
        document.body.appendChild(ghost);
        ph = el("div", "bp-placeholder"); ph.style.height = rect.height + "px";
        node.after(ph); node.classList.add("bp-gone");
      }
      ev.preventDefault();
      ghost.style.left = (ev.clientX - offX) + "px"; ghost.style.top = (ev.clientY - offY) + "px";
      const lane = [...root.querySelectorAll(".bp-lane")].find((l) => { const r = l.getBoundingClientRect(); return ev.clientX >= r.left && ev.clientX <= r.right && ev.clientY >= r.top && ev.clientY <= r.bottom; });
      root.querySelectorAll(".bp-lane").forEach((l) => l.classList.toggle("over", l === lane));
      if (!lane) return;
      const box = lane.querySelector(".bp-cards");
      let before = null;
      for (const o of box.querySelectorAll(".bp-card:not(.bp-gone)")) { const r = o.getBoundingClientRect(); if (ev.clientY < r.top + r.height / 2) { before = o; break; } }
      if (before) box.insertBefore(ph, before); else box.appendChild(ph);
    };
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", up);
      if (!started) return;
      justDragged = Date.now();
      const lane = ph.closest(".bp-lane"), colId = lane.dataset.col;
      const ids = [...lane.querySelectorAll(".bp-cards > .bp-card:not(.bp-gone), .bp-cards > .bp-placeholder")].map((n) => n.classList.contains("bp-placeholder") ? t.id : n.dataset.id);
      ghost.remove(); ph.remove(); node.classList.remove("bp-gone");
      root.querySelectorAll(".bp-lane").forEach((l) => l.classList.remove("over"));
      dragging = false;
      commitMove(t, colId, ids);
      pending = false; render(); paintMeta();
    };
    document.addEventListener("pointermove", move, { passive: false });
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", up);
  }

  function commitMove(t, colId, ids) {
    ids.forEach((id, i) => {
      const cur = byId(id); if (!cur) return;
      const patch = {}, pos = (i + 1) * 1000;
      if (cur.pos !== pos) patch.pos = pos;
      if (id === t.id && cur.col !== colId) {
        patch.col = colId;
        if (colId === "done" && cur.pri !== "done") { patch.prev = cur.pri || "none"; patch.pri = "done"; }
        else if (cur.col === "done" && colId !== "done") { patch.pri = (cur.prev && cur.prev !== "done") ? cur.prev : "none"; }
      }
      if (Object.keys(patch).length) put(id, patch);
    });
  }

  /* ---------- quick priority menu ---------- */
  function closeMenus() { document.querySelectorAll(".bp-menu").forEach((m) => m.remove()); }
  function menu(anchor, t) {
    closeMenus();
    const m = el("div", "bp-menu");
    const r = anchor.getBoundingClientRect();
    m.style.left = Math.max(8, Math.min(r.left + scrollX, document.documentElement.clientWidth - 230)) + "px";
    m.style.top = (r.bottom + scrollY + 4) + "px";
    Object.entries(PRI).forEach(([k, label]) => {
      const b = el("button"); b.type = "button";
      b.append(el("i", "bp-dot p-" + k), document.createTextNode(label));
      b.addEventListener("click", () => { m.remove(); setPriority(t, k).then(() => { render(); paintMeta(); }); });
      m.append(b);
    });
    document.body.append(m);
    m.querySelector("button").focus();
    setTimeout(() => document.addEventListener("click", closeMenus, { once: true }), 0);
  }

  /* ---------- task detail: title, column, priority, due date, comments, files ---------- */
  function field(label, forId) { const w = el("div", "bpd-field"); const l = el(forId ? "label" : "span", "bpd-label", label); if (forId) l.htmlFor = forId; w.append(l); return w; }

  function openDetail(t) {
    closeDetail();
    closeMenus();
    const prevFocus = document.activeElement;
    const ov = el("div", "bp-overlay");
    const box = el("div", "bp-dialog"); box.setAttribute("role", "dialog"); box.setAttribute("aria-modal", "true"); box.setAttribute("aria-label", "Task details"); box.tabIndex = -1;
    ov.append(box);

    const top = el("div", "bpd-top");
    const title = el("input", "bpd-title"); title.id = "bpd-title"; title.maxLength = 300; title.value = t.title || ""; title.setAttribute("aria-label", "Task title");
    const commitTitle = () => { if (!dlg) return; const v = title.value.trim(); if (!v) { title.value = dlg.t.title || ""; return; } if (v !== dlg.t.title) put(dlg.t.id, { title: v.slice(0, 300) }).then(render); };
    title.addEventListener("blur", commitTitle);
    title.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); title.blur(); } });
    const close = el("button", "bpd-close", "✕"); close.type = "button"; close.setAttribute("aria-label", "Close"); close.addEventListener("click", closeDetail);
    top.append(title, close);

    const grid = el("div", "bpd-grid");
    const fCol = field("Column", "bpd-col");
    const sel = el("select"); sel.id = "bpd-col";
    COLS.forEach((c) => { const o = el("option", "", c.name); o.value = c.id; sel.append(o); });
    sel.addEventListener("change", () => { moveTo(dlg.t, sel.value).then(() => { render(); paintMeta(); }); });
    fCol.append(sel);

    const fDue = field("Due date", "bpd-due");
    const dateRow = el("div", "bpd-daterow");
    const date = el("input"); date.type = "date"; date.id = "bpd-due";
    date.addEventListener("change", () => { setDue(date.value || null); });
    dateRow.append(date);
    const quick = el("div", "bpd-quick");
    [["Today", () => todayMel()], ["Tomorrow", () => addDays(1)], ["Next week", () => addDays(7)], ["Clear", () => null]].forEach(([label, fn]) => {
      const b = el("button", "bpd-q", label); b.type = "button"; b.addEventListener("click", () => setDue(fn())); quick.append(b);
    });
    fDue.append(dateRow, quick);
    grid.append(fCol, fDue);

    const fPri = field("Priority");
    const pills = el("div", "bpd-pills"); pills.setAttribute("role", "group"); pills.setAttribute("aria-label", "Priority");
    Object.entries(PRI).forEach(([k, label]) => {
      const b = el("button", "bpd-pill p-" + k, label); b.type = "button"; b.dataset.pri = k;
      b.addEventListener("click", () => { setPriority(dlg.t, k).then(() => { render(); paintMeta(); }); });
      pills.append(b);
    });
    fPri.append(pills);

    const cSec = el("section", "bpd-sec");
    const cHead = el("h3", "", "Comments");
    const cList = el("div", "bpd-list");
    const cForm = el("form", "bpd-composer");
    const cText = el("textarea"); cText.id = "bpd-comment"; cText.rows = 2; cText.maxLength = 2000; cText.placeholder = "Write a comment. Enter to post, Shift+Enter for a new line."; cText.setAttribute("aria-label", "New comment");
    const cBtn = el("button", "bpd-primary", "Post"); cBtn.type = "submit";
    cForm.append(cText, cBtn);
    cText.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); cForm.requestSubmit(); } });
    cSec.append(cHead, cList, cForm);

    const aSec = el("section", "bpd-sec");
    const aHead = el("h3", "", "Attachments");
    const aList = el("div", "bpd-list");
    const aRow = el("div", "bpd-uprow");
    const file = el("input"); file.type = "file"; file.multiple = true; file.accept = ALLOWED.join(","); file.hidden = true; file.id = "bpd-file";
    const aBtn = el("button", "bpd-q", "Add file"); aBtn.type = "button"; aBtn.addEventListener("click", () => file.click());
    const aNote = el("span", "bpd-note", "Images, PDF, Word, Excel, PowerPoint, text or CSV. Up to 10 MB each.");
    aRow.append(aBtn, aNote, file);
    aSec.append(aHead, aList, aRow);

    const foot = el("div", "bpd-foot");
    const msg = el("span", "bpd-msg"); msg.setAttribute("role", "status");
    const delBtn = el("button", "bpd-del", "Delete task"); delBtn.type = "button";
    let delTimer = null;
    delBtn.addEventListener("click", () => {
      if (delBtn.classList.contains("arm")) { clearTimeout(delTimer); del(dlg.t.id); }
      else { delBtn.classList.add("arm"); delBtn.textContent = "Tap again to delete"; delTimer = setTimeout(() => { delBtn.classList.remove("arm"); delBtn.textContent = "Delete task"; }, 3000); }
    });
    foot.append(msg, delBtn);

    box.append(top, grid, fPri, cSec, aSec, foot);
    document.body.append(ov);
    document.body.style.overflow = "hidden";

    dlg = { t, ov, box, title, sel, date, pills, cHead, cList, cText, cBtn, aHead, aList, file, msg, prevFocus, comments: [], files: [] };
    ov.addEventListener("mousedown", (e) => { if (e.target === ov) closeDetail(); });
    box.addEventListener("keydown", trapKeys);
    cForm.addEventListener("submit", (e) => { e.preventDefault(); postComment(); });
    file.addEventListener("change", () => { const fs = [...file.files]; file.value = ""; uploadFiles(fs); });
    paintMeta();
    box.focus();
    loadComments();
    loadFiles();
  }

  function note(text, err) { if (dlg) { dlg.msg.textContent = text || ""; dlg.msg.className = "bpd-msg" + (err ? " err" : ""); } }

  function paintMeta() {
    if (!dlg) return;
    const t = dlg.t;
    if (document.activeElement !== dlg.title) dlg.title.value = t.title || "";
    dlg.sel.value = t.col;
    if (document.activeElement !== dlg.date) dlg.date.value = t.due_date || "";
    dlg.pills.querySelectorAll(".bpd-pill").forEach((b) => { const on = b.dataset.pri === t.pri; b.classList.toggle("on", on); b.setAttribute("aria-pressed", String(on)); });
  }

  async function setDue(iso) {
    if (!dlg) return;
    const t = dlg.t;
    await put(t.id, { due_date: iso });
    render(); paintMeta();
  }

  function closeDetail() {
    if (!dlg) return;
    const d = dlg; dlg = null;
    const v = d.title.value.trim();
    if (v && v !== d.t.title && byId(d.t.id)) { put(d.t.id, { title: v.slice(0, 300) }).then(render); }
    d.ov.remove();
    document.body.style.overflow = "";
    try { d.prevFocus && d.prevFocus.isConnected && d.prevFocus.focus(); } catch (_) {}
  }

  function trapKeys(e) {
    if (e.key === "Escape") { e.stopPropagation(); closeDetail(); return; }
    if (e.key !== "Tab" || !dlg) return;
    const items = [...dlg.box.querySelectorAll("button, input:not([hidden]), select, textarea, a[href]")].filter((n) => !n.disabled && n.offsetParent !== null);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === dlg.box)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  /* comments */
  async function loadComments() {
    const d = dlg; if (!d) return;
    const { data, error } = await sb.from("board_comments").select("id,body,author_name,author_id,created_at").eq("task_id", d.t.id).order("created_at");
    if (dlg !== d) return;
    if (error) { note("Couldn't load comments: " + error.message, true); return; }
    d.comments = data || [];
    syncCount("n_comments", d.comments.length);
    paintComments();
  }
  function paintComments() {
    const d = dlg; if (!d) return;
    d.cHead.textContent = "Comments (" + d.comments.length + ")";
    d.cList.replaceChildren();
    if (!d.comments.length) d.cList.append(el("p", "bpd-empty", "No comments yet."));
    d.comments.forEach((c) => {
      const row = el("div", "bpd-item");
      const meta = el("div", "bpd-meta");
      meta.append(el("b", "", c.author_name || "Unknown"), el("span", "", when(c.created_at)));
      const x = el("button", "bpd-x", "✕"); x.type = "button"; x.setAttribute("aria-label", "Delete comment");
      let tm = null;
      x.addEventListener("click", async () => {
        if (!x.classList.contains("arm")) { x.classList.add("arm"); x.textContent = "Delete?"; tm = setTimeout(() => { x.classList.remove("arm"); x.textContent = "✕"; }, 2500); return; }
        clearTimeout(tm);
        const { error } = await sb.from("board_comments").delete().eq("id", c.id);
        if (error) { note("Couldn't delete the comment: " + error.message, true); return; }
        if (dlg !== d) return;
        d.comments = d.comments.filter((z) => z.id !== c.id); syncCount("n_comments", d.comments.length); paintComments();
      });
      meta.append(x);
      row.append(meta, el("div", "bpd-body", c.body));
      d.cList.append(row);
    });
    d.cList.scrollTop = d.cList.scrollHeight;
  }
  async function postComment() {
    const d = dlg; if (!d) return;
    const body = d.cText.value.trim(); if (!body) return;
    d.cBtn.disabled = true;
    const { data, error } = await sb.from("board_comments").insert({ task_id: d.t.id, body, author_name: myName().slice(0, 80) }).select("id,body,author_name,author_id,created_at").single();
    d.cBtn.disabled = false;
    if (error) { note("Couldn't post the comment: " + error.message, true); return; }
    note("");
    d.cText.value = "";
    if (dlg !== d) return;
    d.comments.push(data); syncCount("n_comments", d.comments.length); paintComments(); d.cText.focus();
  }
  function syncCount(key, n) { if (dlg && dlg.t[key] !== n) { dlg.t[key] = n; if (!dragging) render(); } }

  /* attachments */
  async function loadFiles() {
    const d = dlg; if (!d) return;
    const { data, error } = await sb.from("board_attachments").select("id,path,name,size,mime,uploaded_by,created_at").eq("task_id", d.t.id).order("created_at");
    if (dlg !== d) return;
    if (error) { note("Couldn't load attachments: " + error.message, true); return; }
    d.files = data || [];
    d.urls = {};
    if (d.files.length) {
      const { data: signed } = await sb.storage.from(BUCKET).createSignedUrls(d.files.map((f) => f.path), 3600);
      (signed || []).forEach((s) => { if (s && s.path && s.signedUrl) d.urls[s.path] = s.signedUrl; });
    }
    if (dlg !== d) return;
    syncCount("n_files", d.files.length);
    paintFiles();
  }
  function paintFiles() {
    const d = dlg; if (!d) return;
    d.aHead.textContent = "Attachments (" + d.files.length + ")";
    d.aList.replaceChildren();
    if (!d.files.length) d.aList.append(el("p", "bpd-empty", "No files yet."));
    d.files.forEach((f) => {
      const row = el("div", "bpd-item bpd-file");
      const url = d.urls && d.urls[f.path];
      if (url && (f.mime || "").startsWith("image/") && f.mime !== "image/heic") {
        const img = el("img", "bpd-thumb"); img.src = url; img.alt = ""; img.loading = "lazy"; row.append(img);
      }
      const info = el("div", "bpd-fileinfo");
      let nameEl;
      if (url) { nameEl = el("a", "bpd-name", f.name); nameEl.href = url; nameEl.target = "_blank"; nameEl.rel = "noopener noreferrer"; }
      else nameEl = el("span", "bpd-name", f.name);
      info.append(nameEl, el("span", "bpd-sub", [f.size != null ? sizeText(f.size) : "", f.uploaded_by, when(f.created_at)].filter(Boolean).join(" · ")));
      const x = el("button", "bpd-x", "✕"); x.type = "button"; x.setAttribute("aria-label", "Delete file " + f.name);
      let tm = null;
      x.addEventListener("click", async () => {
        if (!x.classList.contains("arm")) { x.classList.add("arm"); x.textContent = "Delete?"; tm = setTimeout(() => { x.classList.remove("arm"); x.textContent = "✕"; }, 2500); return; }
        clearTimeout(tm);
        const { error } = await sb.from("board_attachments").delete().eq("id", f.id);
        if (error) { note("Couldn't delete the file: " + error.message, true); return; }
        try { await sb.storage.from(BUCKET).remove([f.path]); } catch (_) {}
        if (dlg !== d) return;
        d.files = d.files.filter((z) => z.id !== f.id); syncCount("n_files", d.files.length); paintFiles();
      });
      row.append(info, x);
      d.aList.append(row);
    });
  }
  async function uploadFiles(files) {
    const d = dlg; if (!d || !files.length) return;
    for (const f of files) {
      if (dlg !== d) return;
      if (f.size > MAX_FILE) { note(f.name + " is over 10 MB.", true); continue; }
      if (!ALLOWED.includes(f.type)) { note(f.name + ": this file type isn't supported.", true); continue; }
      note("Uploading " + f.name + "…");
      const safe = f.name.replace(/[^\w.\-]+/g, "_").slice(-80) || "file";
      const path = d.t.id + "/" + uid() + "-" + safe;
      const up = await sb.storage.from(BUCKET).upload(path, f, { contentType: f.type, upsert: false });
      if (up.error) { note(f.name + ": " + up.error.message, true); continue; }
      const ins = await sb.from("board_attachments").insert({ task_id: d.t.id, path, name: f.name.slice(0, 200), size: f.size, mime: f.type, uploaded_by: myName().slice(0, 80) }).select("id").single();
      if (ins.error) { try { await sb.storage.from(BUCKET).remove([path]); } catch (_) {} note(f.name + ": " + ins.error.message, true); continue; }
      note("");
    }
    if (dlg === d) await loadFiles();
  }

  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenus(); });
  window.addEventListener("popstate", closeDetail);

  /* ---------- home tile ---------- */
  async function stats(client) {
    const { data, error } = await client.from("board_tasks").select("col,pri,due_date");
    if (error) throw new Error(error.message);
    const rows = data || [], today = todayMel();
    const overdue = rows.filter((x) => x.col !== "done" && x.due_date && x.due_date < today).length;
    return {
      warn: overdue > 0,
      stats: [
        [String(rows.filter((x) => x.col === "todo").length), "To do"],
        [String(rows.filter((x) => x.pri === "urgent" && x.col !== "done").length), "Urgent"],
        [String(overdue), "Overdue"],
        [String(rows.filter((x) => x.col === "stuck").length), "Roadblocks"]
      ]
    };
  }

  async function open(client, mount, profile) {
    sb = client; me = profile || null; root = mount; dragging = false; pending = false;
    closeDetail();
    clearInterval(timer);
    build();
    pushHint();
    await load();
    timer = setInterval(() => { if (!root.hidden && !dlg && Date.now() - lastLoad >= REFRESH_MS - 1000) load(); }, 60 * 1000);
  }
  return { open, stats };
})();

/* Indifeels Project Board: admin-only kanban stored in Supabase public.board_tasks. */
window.BoardPanel = (() => {
  const COLS = [
    { id: "backlog", name: "Backlog" },
    { id: "todo", name: "To Do" },
    { id: "stuck", name: "Roadblocks" },
    { id: "done", name: "Done" }
  ];
  const PRI = {
    risk: "Most risky",
    none: "No priority",
    low: "Fix, not urgent",
    med: "Fix, a bit urgent",
    urgent: "Very urgent, today",
    done: "Completed"
  };
  const REFRESH_MS = 60 * 60 * 1000;
  let sb, root, shell, tasks = [], dragging = false, editing = false, pending = false, timer, lastLoad = 0, lanes = {};

  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const stampText = () => "Last refreshed " + new Date().toLocaleString("en-AU", { timeZone: "Australia/Melbourne", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  const byId = (id) => tasks.find((t) => t.id === id);
  const say = (msg, err) => { const s = root.querySelector(".bp-status"); if (s) { s.textContent = msg || ""; s.className = "bp-status" + (err ? " err" : ""); } };

  async function load() {
    const { data, error } = await sb.from("board_tasks").select("id,title,col,pri,prev,pos,source,created_at").order("pos");
    if (error) { say("Couldn't load the board: " + error.message, true); return; }
    tasks = data || [];
    lastLoad = Date.now();
    const st = root.querySelector(".bp-stamp"); if (st) st.textContent = stampText();
    say("");
    if (dragging || editing) { pending = true; return; }
    render();
  }
  function flush() { if (pending && !dragging && !editing) { pending = false; render(); } }

  async function put(id, patch) {
    const t = byId(id); if (t) Object.assign(t, patch);
    const { error } = await sb.from("board_tasks").update(patch).eq("id", id);
    if (error) { say("Couldn't save that change: " + error.message, true); await load(); }
  }
  async function add(colId, title) {
    const inCol = tasks.filter((t) => t.col === colId);
    const pos = inCol.reduce((m, t) => Math.max(m, t.pos || 0), 0) + 1000;
    const row = { title, col: colId, pri: colId === "done" ? "done" : "none", pos, source: "manual" };
    const { data, error } = await sb.from("board_tasks").insert(row).select("id,title,col,pri,prev,pos,source,created_at").single();
    if (error) { say("Couldn't add the task: " + error.message, true); return; }
    tasks.push(data); render();
  }
  async function del(id) {
    tasks = tasks.filter((t) => t.id !== id); render();
    const { error } = await sb.from("board_tasks").delete().eq("id", id);
    if (error) { say("Couldn't delete the task: " + error.message, true); await load(); }
  }

  function build() {
    root.innerHTML = "";
    shell = el("div", "bp");
    const head = el("div", "bp-head");
    head.append(el("h2", "", "Indifeels Project Board"));
    const meta = el("div", "bp-meta");
    meta.append(el("span", "bp-stamp", "Loading…"));
    const btn = el("button", "bp-btn", "Refresh"); btn.type = "button"; btn.addEventListener("click", load);
    meta.append(btn); head.append(meta);
    shell.append(head, el("div", "bp-status"));
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

  function render() {
    COLS.forEach((c) => {
      const L = lanes[c.id];
      const list = tasks.filter((t) => t.col === c.id).sort((a, b) => (a.pos || 0) - (b.pos || 0));
      L.count.textContent = String(list.length);
      L.cards.replaceChildren();
      if (!list.length) L.cards.append(el("div", "bp-empty", "Nothing here yet. Add a task below or drag one in."));
      list.forEach((t) => L.cards.append(card(t)));
    });
  }

  function card(t) {
    const pri = PRI[t.pri] ? t.pri : "none";
    const d = el("div", "bp-card p-" + pri); d.dataset.id = t.id;
    const grip = el("div", "bp-grip", "⋮⋮"); grip.setAttribute("aria-hidden", "true");
    const dot = el("button", "bp-pri"); dot.type = "button"; dot.title = "Change priority: " + PRI[pri]; dot.setAttribute("aria-label", "Change priority, now " + PRI[pri]);
    dot.addEventListener("click", (e) => { e.stopPropagation(); menu(dot, t); });
    const title = el("div", "bp-title", t.title || ""); title.title = "Double-click to edit";
    title.addEventListener("dblclick", () => { editing = true; title.contentEditable = "true"; title.focus(); getSelection().selectAllChildren(title); });
    title.addEventListener("blur", () => {
      if (title.contentEditable !== "true") return;
      title.contentEditable = "false"; editing = false;
      const v = title.textContent.trim();
      if (v && v !== t.title) put(t.id, { title: v.slice(0, 300) }); else title.textContent = t.title || "";
      flush();
    });
    title.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); title.blur(); } });
    const x = el("button", "bp-x", "✕"); x.type = "button"; x.title = "Delete task"; x.setAttribute("aria-label", "Delete task");
    let timeout = null;
    x.addEventListener("click", (e) => {
      e.stopPropagation();
      if (x.classList.contains("arm")) { clearTimeout(timeout); del(t.id); }
      else { x.classList.add("arm"); x.textContent = "Delete?"; timeout = setTimeout(() => { x.classList.remove("arm"); x.textContent = "✕"; }, 2500); }
    });
    d.append(grip, dot, title, x);
    d.addEventListener("pointerdown", (e) => startDrag(e, d, t));
    return d;
  }

  function startDrag(e, node, t) {
    if (e.button !== undefined && e.button !== 0) return;
    if (e.target.closest("button") || node.querySelector(".bp-title").isContentEditable) return;
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
      const lane = ph.closest(".bp-lane"), colId = lane.dataset.col;
      const ids = [...lane.querySelectorAll(".bp-cards > .bp-card:not(.bp-gone), .bp-cards > .bp-placeholder")].map((n) => n.classList.contains("bp-placeholder") ? t.id : n.dataset.id);
      ghost.remove(); ph.remove(); node.classList.remove("bp-gone");
      root.querySelectorAll(".bp-lane").forEach((l) => l.classList.remove("over"));
      dragging = false;
      commitMove(t, colId, ids);
      pending = false; render();
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

  function closeMenus() { document.querySelectorAll(".bp-menu").forEach((m) => m.remove()); }
  function menu(anchor, t) {
    closeMenus();
    const m = el("div", "bp-menu");
    const r = anchor.getBoundingClientRect();
    m.style.left = Math.max(8, Math.min(r.left + scrollX, document.documentElement.clientWidth - 230)) + "px";
    m.style.top = (r.bottom + scrollY + 4) + "px";
    Object.entries(PRI).forEach(([k, label]) => {
      const b = el("button"); b.type = "button";
      const dot = el("i", "bp-dot p-" + k); b.append(dot, document.createTextNode(label));
      b.addEventListener("click", () => {
        const patch = { pri: k };
        if (k === "done") { if (t.pri !== "done") patch.prev = t.pri || "none"; patch.col = "done"; }
        else if (t.col === "done") patch.col = "todo";
        put(t.id, patch).then(render); m.remove();
      });
      m.append(b);
    });
    document.body.append(m);
    m.querySelector("button").focus();
    setTimeout(() => document.addEventListener("click", closeMenus, { once: true }), 0);
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenus(); });

  /* Counts for the home tile. */
  async function stats(client) {
    const { data, error } = await client.from("board_tasks").select("col,pri");
    if (error) throw new Error(error.message);
    const rows = data || [];
    return [
      [String(rows.filter((x) => x.col === "todo").length), "To do"],
      [String(rows.filter((x) => x.pri === "urgent" && x.col !== "done").length), "Urgent"],
      [String(rows.filter((x) => x.col === "stuck").length), "Roadblocks"]
    ];
  }

  async function open(client, mount) {
    sb = client; root = mount; dragging = false; editing = false; pending = false;
    clearInterval(timer);
    build();
    await load();
    timer = setInterval(() => { if (!root.hidden && Date.now() - lastLoad >= REFRESH_MS - 1000) load(); }, 60 * 1000);
  }
  return { open, stats };
})();

/* Indifeels Reports web app */
(function () {
  "use strict";
  const CFG = window.APP_CONFIG;
  const sb = window.supabase.createClient(CFG.url, CFG.key, { auth: { persistSession: true, autoRefreshToken: true } });
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const toEmail = (u) => `${u.trim().toLowerCase()}@${CFG.domain}`;
  let me = null, reports = [], keys = {};

  // ---------- theme ----------
  const root = document.documentElement;
  const curTheme = () => root.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const themeLabel = () => ($("#m-theme").textContent = curTheme() === "dark" ? "Light mode" : "Dark mode");
  try { const t = localStorage.getItem("ir-theme"); if (t) root.setAttribute("data-theme", t); } catch (_) {}
  themeLabel();
  $("#m-theme").addEventListener("click", () => {
    const n = curTheme() === "dark" ? "light" : "dark"; root.setAttribute("data-theme", n);
    try { localStorage.setItem("ir-theme", n); } catch (_) {}
    themeLabel(); closeMenu();
  });

  // ---------- helpers ----------
  function toast(msg) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2600); }
  function showErr(id, msg) { const e = $(id); e.textContent = msg; e.hidden = !msg; }
  function busy(btn, on, label) { btn.disabled = on; if (label) { btn.dataset.l = btn.dataset.l || btn.textContent; btn.textContent = on ? label : btn.dataset.l; } }
  $$(".eye:not(.gen)").forEach((b) => b.addEventListener("click", () => { const i = document.getElementById(b.dataset.for); const s = i.type === "password"; i.type = s ? "text" : "password"; b.textContent = s ? "Hide" : "Show"; }));
  function genPassword() { const a = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"; const r = crypto.getRandomValues(new Uint32Array(10)); return "Indi-" + Array.from(r, (x) => a[x % a.length]).join(""); }

  // ---------- views ----------
  const VIEWS = ["login", "reset", "shell"];
  const PAGES = ["home", "report", "password", "admin"];
  function view(v) { VIEWS.forEach((x) => ($("#v-" + x).hidden = x !== v)); }
  function page(p, title) {
    PAGES.forEach((x) => ($("#v-" + x).hidden = x !== p));
    $("#b-back").hidden = p === "home";
    $("#bar-text").textContent = title || "Indifeels Reports";
    if (p !== "report") { $("#rep-frame").hidden = true; $("#rep-frame").srcdoc = ""; }
    window.scrollTo(0, 0);
    closeMenu();
  }
  $("#b-back").addEventListener("click", () => go("home"));
  $("#to-reset").addEventListener("click", () => { $("#r-user").value = $("#l-user").value; view("reset"); });
  $("#to-login").addEventListener("click", () => view("login"));

  // menu
  function closeMenu() { $("#menu").hidden = true; $("#b-menu").setAttribute("aria-expanded", "false"); }
  $("#b-menu").addEventListener("click", (e) => { e.stopPropagation(); const m = $("#menu"); m.hidden = !m.hidden; $("#b-menu").setAttribute("aria-expanded", String(!m.hidden)); });
  document.addEventListener("click", (e) => { if (!e.target.closest(".menu-wrap")) closeMenu(); });
  $$("#menu [data-go]").forEach((b) => b.addEventListener("click", () => go(b.dataset.go)));
  $("#m-out").addEventListener("click", async () => { await sb.auth.signOut(); location.hash = ""; start(); });

  // install prompt (Android / desktop Chrome)
  let deferred = null;
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferred = e; $("#m-install").hidden = false; });
  $("#m-install").addEventListener("click", async () => { closeMenu(); if (!deferred) return; deferred.prompt(); await deferred.userChoice; deferred = null; $("#m-install").hidden = true; });

  // ---------- auth ----------
  $("#f-login").addEventListener("submit", async (e) => {
    e.preventDefault(); showErr("#l-err", "");
    const u = $("#l-user").value.trim(), p = $("#l-pass").value;
    if (!u || !p) return showErr("#l-err", "Enter your username and password.");
    const btn = $("#l-btn"); busy(btn, true, "Signing in…");
    const { error } = await sb.auth.signInWithPassword({ email: toEmail(u), password: p });
    busy(btn, false, "Signing in…");
    if (error) return showErr("#l-err", /invalid/i.test(error.message) ? "That username and password don't match. Check them, or request a password reset." : /banned/i.test(error.message) ? "This account is switched off. Contact your admin." : error.message);
    $("#l-pass").value = "";
    start();
  });

  $("#f-reset").addEventListener("submit", async (e) => {
    e.preventDefault(); showErr("#r-err", ""); $("#r-ok").hidden = true;
    const u = $("#r-user").value.trim();
    if (!u) return showErr("#r-err", "Enter your username.");
    const btn = $("#r-btn"); busy(btn, true, "Sending…");
    try {
      const res = await fetch(`${CFG.url}/functions/v1/request-reset`, { method: "POST", headers: { "Content-Type": "application/json", apikey: CFG.key, Authorization: `Bearer ${CFG.key}` }, body: JSON.stringify({ username: u, note: $("#r-note").value }) });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.error || "The request didn't go through. Try again in a minute.");
      $("#r-ok").hidden = false; $("#r-note").value = "";
    } catch (err) { showErr("#r-err", err.message); }
    busy(btn, false);
  });

  $("#f-pw").addEventListener("submit", async (e) => {
    e.preventDefault(); showErr("#p-err", ""); $("#p-ok").hidden = true;
    const a = $("#p-new").value, b = $("#p-new2").value;
    if (a.length < 8) return showErr("#p-err", "Use at least 8 characters.");
    if (a !== b) return showErr("#p-err", "The two passwords don't match.");
    const btn = $("#p-btn"); busy(btn, true, "Saving…");
    const { error } = await sb.auth.updateUser({ password: a });
    busy(btn, false);
    if (error) return showErr("#p-err", error.message);
    $("#p-new").value = $("#p-new2").value = ""; $("#p-ok").hidden = false;
  });

  // ---------- crypto ----------
  const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  async function decryptFile(path, keyB64) {
    const res = await fetch(`${path}?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error("not-published");
    const buf = new Uint8Array(await res.arrayBuffer());
    const key = await crypto.subtle.importKey("raw", b64(keyB64), "AES-GCM", false, ["decrypt"]);
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: buf.slice(0, 12) }, key, buf.slice(12));
    const stream = new Blob([plain]).stream().pipeThrough(new DecompressionStream("gzip"));
    return await new Response(stream).text();
  }

  // ---------- home ----------
  async function loadReports() {
    const [{ data: reps, error: e1 }, { data: ks, error: e2 }] = await Promise.all([
      sb.from("reports").select("id,title,description,sort").order("sort"),
      sb.from("report_keys").select("report_id,key_b64"),
    ]);
    if (e1 || e2) throw new Error((e1 || e2).message);
    reports = reps || []; keys = Object.fromEntries((ks || []).map((k) => [k.report_id, k.key_b64]));
  }
  // Fixed look per report, so each tile always looks the same.
  const I = {
    mega: '<path d="M3 11v2a1 1 0 0 0 1 1h2l5 4V6L6 10H4a1 1 0 0 0-1 1z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/>',
    trend: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    box: '<path d="M12 3 3 7.5v9L12 21l9-4.5v-9z"/><path d="M3 7.5 12 12l9-4.5M12 12v9"/>',
    alert: '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>',
    dollar: '<circle cx="12" cy="12" r="9"/><path d="M15 9.5c-.5-1-1.6-1.5-3-1.5-1.7 0-3 .8-3 2s1.3 1.7 3 2 3 .9 3 2.1-1.3 1.9-3 1.9c-1.4 0-2.5-.5-3-1.5M12 6.5v11"/>',
    msg: '<path d="M4 5h16v11H9l-5 4z"/>',
    bag: '<path d="M5 8h14l-1 12H6z"/><path d="M9 8a3 3 0 0 1 6 0"/>',
    bars: '<path d="M5 20V12M10 20V7M15 20v-5M20 20V4"/>',
    tag: '<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8.5" r="1.5"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    chart: '<path d="M4 20V4M4 20h16"/><path d="M8 16l4-5 3 3 5-6"/>',
  };
  const svg = (k, cls = "") => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${I[k] || I.chart}</svg>`;
  const LOOK = {
    daily: { c: "blue", icon: "mega", stat: ["dollar", "msg", "bag", "bars"], line: ["blue", "purple", "green", "blue"] },
    monthly: { c: "green", icon: "trend", stat: [null, null, null, null], line: ["green", "blue", "orange", "green"] },
    stock: { c: "orange", icon: "box", stat: ["box", "box", "tag"], line: [] },
  };
  const SPARE = ["purple", "teal", "rose"];
  function look(id) {
    if (LOOK[id]) return LOOK[id];
    let h = 0; for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return { c: SPARE[h % SPARE.length], icon: "chart", stat: [], line: [] };
  }
  function spark(vals, color) {
    const v = (vals || []).map(Number).filter((x) => isFinite(x));
    if (v.length < 2) return "";
    const lo = Math.min(...v), hi = Math.max(...v), rg = hi - lo || 1;
    const pts = v.map((x, i) => `${(i / (v.length - 1) * 100).toFixed(1)},${(23 - (x - lo) / rg * 20).toFixed(1)}`).join(" ");
    return `<svg class="sp" viewBox="0 0 100 26" preserveAspectRatio="none" aria-hidden="true"><polyline style="--lc:var(--${color})" points="${pts}"/></svg>`;
  }
  // Refresh health: explicit failure from r/status.json, or no successful refresh within the expected window.
  const MAX_AGE_H = { daily: 26, monthly: 26, stock: 10 };
  let status = {};
  async function loadStatus() {
    try { const res = await fetch(`r/status.json?t=${Date.now()}`, { cache: "no-store" }); status = res.ok ? await res.json() : {}; } catch (_) { status = {}; }
  }
  const fmtTime = (iso) => new Date(iso).toLocaleString("en-AU", { timeZone: "Australia/Sydney", weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  function health(id) {
    const s = status[id]; if (!s) return null;
    if (s.ok === false) return { title: "Last refresh failed", text: `${s.reason || "The refresh didn't finish."}${s.last_ok ? ` Showing data from ${fmtTime(s.last_ok)}.` : ""}` };
    const age = s.last_ok ? (Date.now() - new Date(s.last_ok).getTime()) / 36e5 : Infinity;
    if (age > (MAX_AGE_H[id] || 26)) return { title: "Refresh overdue", text: `No successful refresh since ${s.last_ok ? fmtTime(s.last_ok) : "it was set up"}. Check the scheduled task.` };
    return null;
  }
  function tileHTML(r, meta) {
    const L = look(r.id), hl = health(r.id);
    const alertBox = hl ? `<div class="alert">${svg("alert")}<div><b>${esc(hl.title)}</b>${esc(hl.text)}</div></div>` : "";
    const st = (meta?.stats || []).slice(0, 4);
    const stats = st.map((s, i) => `<div class="st" style="--sc:var(--${L.line[i] || L.c})">${L.stat[i] ? svg(L.stat[i], "si") : ""}<b>${esc(s[0])}</b><span>${esc(s[1])}</span>${spark(meta?.spark?.[i], L.line[i] || L.c)}</div>`).join("");
    const sig = meta?.signal ? `<p class="sig"><span class="pl">${esc(meta.signal.label)}</span>${esc(meta.signal.reason)}</p>` : "";
    const upd = meta?.updated ? `Updated ${esc(meta.updated)}` : "Waiting for the next update";
    const warn = meta?.warn ? `<span class="wn">${svg("alert")}${esc(meta.warn)}</span>` : "";
    return `<button class="tile t-${L.c}${hl ? " alerted" : ""}" type="button" data-id="${esc(r.id)}">
      <div class="th"><span class="ic">${svg(hl ? "alert" : L.icon)}</span><h3>${esc(r.title)}</h3><span class="open" aria-hidden="true">Open <span class="ar">&rsaquo;</span></span><p class="ds">${esc(r.description || "")}</p></div>
      ${alertBox}${stats ? `<div class="sts n${st.length}">${stats}</div>` : ""}${sig}<div class="ft"><span class="u">${svg("clock")}${upd}</span>${warn}</div></button>`;
  }
  async function renderHome() {
    const box = $("#tiles");
    $("#hello").textContent = me.display_name ? `Hi ${me.display_name.split(" ")[0]}, here are your reports` : "Your reports";
    await loadStatus();
    box.innerHTML = reports.map((r) => tileHTML(r, null)).join("");
    $("#no-reports").hidden = reports.length > 0;
    box.querySelectorAll(".tile").forEach((t) => t.addEventListener("click", () => openReport(t.dataset.id)));
    await Promise.all(reports.map(async (r) => {
      if (!keys[r.id]) return;
      try {
        const meta = JSON.parse(await decryptFile(`r/${r.id}.meta.bin`, keys[r.id]));
        const el = box.querySelector(`.tile[data-id="${CSS.escape(r.id)}"]`);
        if (el) { el.outerHTML = tileHTML(r, meta); box.querySelector(`.tile[data-id="${CSS.escape(r.id)}"]`).addEventListener("click", () => openReport(r.id)); }
      } catch (_) { /* no published summary yet */ }
    }));
  }

  // ---------- report viewer ----------
  async function openReport(id) {
    const r = reports.find((x) => x.id === id); if (!r) return go("home");
    if (location.hash !== "#" + id) history.pushState(null, "", "#" + id);
    page("report", r.title);
    const st = $("#rep-status"), fr = $("#rep-frame");
    st.hidden = false; st.textContent = "Opening report…"; fr.hidden = true;
    try {
      let html = await decryptFile(`r/${id}.bin`, keys[id]);
      html = html.replace(/<a href="\.\/"[^>]*>[^<]*All reports<\/a>/, ""); // hub-only back link
      fr.srcdoc = html; fr.hidden = false; st.hidden = true;
    } catch (e) {
      st.textContent = e.message === "not-published" ? "This report hasn't been published yet. It appears after tonight's 10 pm update." : "This report couldn't be opened. Pull down to refresh, or sign out and back in.";
    }
  }

  // ---------- admin ----------
  async function adminCall(body) {
    const { data, error } = await sb.functions.invoke("admin", { body });
    if (error) {
      let msg = error.message; try { const j = await error.context.json(); msg = j.error || msg; } catch (_) {}
      throw new Error(msg);
    }
    return data;
  }
  let adminData = null;
  async function renderAdmin() {
    $("#users").innerHTML = '<p class="empty">Loading users…</p>';
    try { adminData = await adminCall({ action: "list" }); } catch (e) { $("#users").innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
    const reps = adminData.reports || [];
    $("#a-reports").innerHTML = reps.map((r) => `<label class="chk"><input type="checkbox" value="${esc(r.id)}"> ${esc(r.title)}</label>`).join("");
    const grants = {}; (adminData.grants || []).forEach((g) => (grants[g.user_id] = grants[g.user_id] || new Set()).add(g.report_id));
    $("#users").innerHTML = (adminData.users || []).map((u) => {
      const g = grants[u.id] || new Set();
      const checks = u.is_admin ? '<p class="uh meta">Admins see every report.</p>' :
        `<div class="checks">${reps.map((r) => `<label class="chk"><input type="checkbox" data-uid="${u.id}" value="${esc(r.id)}" ${g.has(r.id) ? "checked" : ""}> ${esc(r.title)}</label>`).join("")}</div>`;
      const self = u.id === me.id;
      return `<div class="card user" data-uid="${u.id}">
        <div class="uh"><div><b>${esc(u.display_name || u.username)}</b>${u.is_admin ? '<span class="tag">Admin</span>' : ""}${u.disabled ? '<span class="tag off">Switched off</span>' : ""}
          <div class="meta">Username: ${esc(u.username)}${u.email ? " &nbsp;Email: " + esc(u.email) : ""}</div></div>
          <div class="uact">${self ? "" : `<button class="btn sm" data-act="toggle" type="button">${u.disabled ? "Switch on" : "Switch off"}</button><button class="btn sm danger" data-act="delete" type="button">Delete</button>`}</div></div>
        ${checks}
        <div class="setpw"><input type="text" placeholder="New password for ${esc(u.username)}" aria-label="New password for ${esc(u.username)}" autocomplete="off"><button class="btn sm" data-act="gen" type="button">Generate</button><button class="btn sm" data-act="setpw" type="button">Set password</button></div>
      </div>`;
    }).join("") || '<p class="empty">No users yet.</p>';

    $$("#users input[type=checkbox][data-uid]").forEach((c) => c.addEventListener("change", async () => {
      const uid = c.dataset.uid;
      const sel = $$(`#users input[type=checkbox][data-uid="${uid}"]`).filter((x) => x.checked).map((x) => x.value);
      try { await adminCall({ action: "update", id: uid, reports: sel }); toast("Report access saved"); } catch (e) { c.checked = !c.checked; toast(e.message); }
    }));
    $$("#users .user").forEach((card) => {
      const uid = card.dataset.uid; const u = adminData.users.find((x) => x.id === uid);
      card.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", async () => {
        const inp = card.querySelector(".setpw input");
        try {
          if (b.dataset.act === "gen") { inp.value = genPassword(); return; }
          if (b.dataset.act === "setpw") {
            if (inp.value.length < 8) return toast("Use at least 8 characters");
            await adminCall({ action: "set_password", id: uid, password: inp.value });
            toast(`Password set for ${u.username}. Share it with them.`); return;
          }
          if (b.dataset.act === "toggle") { await adminCall({ action: "update", id: uid, disabled: !u.disabled }); toast(u.disabled ? "Account switched on" : "Account switched off"); return renderAdmin(); }
          if (b.dataset.act === "delete") {
            if (b.dataset.confirm !== "1") { b.dataset.confirm = "1"; b.textContent = "Tap again to delete"; setTimeout(() => { b.dataset.confirm = ""; b.textContent = "Delete"; }, 4000); return; }
            await adminCall({ action: "delete", id: uid }); toast("User deleted"); return renderAdmin();
          }
        } catch (e) { toast(e.message); }
      }));
    });
    renderResets();
  }
  function renderResets() {
    const rs = adminData?.resets || [];
    const open = rs.filter((r) => !r.handled_at);
    const badge = $("#reset-count"); badge.textContent = open.length; badge.hidden = !open.length;
    $("#resets").innerHTML = rs.length ? rs.map((r) => `<div class="card user"><div class="uh"><div><b>${esc(r.username)}</b>${r.handled_at ? '<span class="tag">Done</span>' : '<span class="tag off">Waiting</span>'}
      <div class="meta">${new Date(r.created_at).toLocaleString("en-AU", { timeZone: "Australia/Sydney" })}${r.note ? " &nbsp;" + esc(r.note) : ""}</div></div>
      ${r.handled_at ? "" : `<div class="uact"><button class="btn sm" type="button" data-rid="${r.id}">Mark done</button></div>`}</div></div>`).join("")
      : '<p class="empty">No password reset requests.</p>';
    $$("#resets [data-rid]").forEach((b) => b.addEventListener("click", async () => { try { await adminCall({ action: "reset_handled", id: Number(b.dataset.rid) }); toast("Marked as done"); renderAdmin(); } catch (e) { toast(e.message); } }));
  }
  $("#t-users").addEventListener("click", () => { $("#t-users").setAttribute("aria-selected", "true"); $("#t-resets").setAttribute("aria-selected", "false"); $("#p-users").hidden = false; $("#p-resets").hidden = true; });
  $("#t-resets").addEventListener("click", () => { $("#t-resets").setAttribute("aria-selected", "true"); $("#t-users").setAttribute("aria-selected", "false"); $("#p-users").hidden = true; $("#p-resets").hidden = false; });
  $("#a-gen").addEventListener("click", () => ($("#a-pass").value = genPassword()));
  $("#f-add").addEventListener("submit", async (e) => {
    e.preventDefault(); showErr("#a-err", ""); $("#a-ok").hidden = true;
    const body = { action: "create", username: $("#a-user").value.trim().toLowerCase(), display_name: $("#a-name").value.trim(), email: $("#a-email").value.trim(), password: $("#a-pass").value, is_admin: $("#a-admin").checked, reports: $$("#a-reports input:checked").map((x) => x.value) };
    if (!/^[a-z0-9._-]{3,32}$/.test(body.username)) return showErr("#a-err", "Username: 3 to 32 characters, lowercase letters, numbers, dot, dash or underscore.");
    if (body.password.length < 8) return showErr("#a-err", "First password must be at least 8 characters.");
    const btn = $("#a-btn"); busy(btn, true, "Adding…");
    try {
      await adminCall(body);
      const ok = $("#a-ok"); ok.textContent = `Added ${body.username}. Share this with them: username ${body.username}, password ${body.password}. They can change it after signing in.`; ok.hidden = false;
      $("#f-add").reset(); renderAdmin();
    } catch (err) { showErr("#a-err", err.message); }
    busy(btn, false);
  });

  // ---------- routing ----------
  function go(p) {
    if (p === "home") { if (location.hash) history.pushState(null, "", location.pathname); page("home"); renderHome(); }
    else if (p === "password") { page("password", "Change password"); }
    else if (p === "admin" && me?.is_admin) { page("admin", "Admin"); renderAdmin(); }
  }
  window.addEventListener("popstate", () => { const id = location.hash.slice(1); if (id && reports.some((r) => r.id === id)) openReport(id); else { page("home"); renderHome(); } });

  async function start() {
    const { data: { session } } = await sb.auth.getSession();
    if (!session) { view("login"); return; }
    const { data: prof, error } = await sb.from("profiles").select("id,username,display_name,is_admin,disabled").eq("id", session.user.id).single();
    if (error || !prof || prof.disabled) { await sb.auth.signOut(); view("login"); showErr("#l-err", prof?.disabled ? "This account is switched off. Contact your admin." : ""); return; }
    me = prof;
    $("#me-name").textContent = `Signed in as ${prof.username}`;
    $("#me-initial").textContent = (prof.display_name || prof.username)[0].toUpperCase();
    $("#m-admin").hidden = !prof.is_admin;
    view("shell");
    try { await loadReports(); } catch (e) { toast(e.message); }
    const id = location.hash.slice(1);
    if (id && reports.some((r) => r.id === id)) openReport(id); else { page("home"); renderHome(); }
  }
  sb.auth.onAuthStateChange((ev) => { if (ev === "SIGNED_OUT") view("login"); });
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  start();
})();

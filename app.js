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
  const PAGES = ["home", "report", "stock", "attribution", "password", "admin"];
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
    "order-attribution": { c: "teal", icon: "tag", stat: ["tag", "clock", "dollar"], line: ["teal", "purple", "green"] },
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
      if (r.id === "order-attribution") {
        try {
          await loadAttribution();
          const meta = attributionStats();
          const el = box.querySelector(`.tile[data-id="${CSS.escape(r.id)}"]`);
          if (el) { el.outerHTML = tileHTML(r, meta); box.querySelector(`.tile[data-id="${CSS.escape(r.id)}"]`).addEventListener("click", () => openReport(r.id)); }
        } catch (_) {}
        return;
      }
      if (!keys[r.id]) return;
      try {
        const meta = JSON.parse(await decryptFile(`r/${r.id}.meta.bin`, keys[r.id]));
        if (r.id === "stock") { try { await loadMoves(); Object.assign(meta, stockStats()); } catch (_) {} }
        const el = box.querySelector(`.tile[data-id="${CSS.escape(r.id)}"]`);
        if (el) { el.outerHTML = tileHTML(r, meta); box.querySelector(`.tile[data-id="${CSS.escape(r.id)}"]`).addEventListener("click", () => openReport(r.id)); }
      } catch (_) { /* no published summary yet */ }
    }));
  }

  // ---------- stock move tick list ----------
  let SM = { moves: [], now: {}, ticks: {} };
  async function loadMoves() {
    const log = JSON.parse(await decryptFile("r/stock_moves.bin", keys.stock));
    const { data, error } = await sb.from("stock_ticks").select("*");
    if (error) throw new Error(error.message);
    SM = { moves: log.moves || [], fixes: log.fixes || [], now: log.now || {}, ticks: Object.fromEntries((data || []).map((t) => [t.move_id, t])) };
    return SM;
  }
  const smPending = () => SM.moves.filter((m) => !SM.ticks[m.id]?.finalised_at).sort((a, b) => b.moved_at.localeCompare(a.moved_at));
  const smDone = () => SM.moves.filter((m) => SM.ticks[m.id]?.finalised_at).sort((a, b) => SM.ticks[b.id].finalised_at.localeCompare(SM.ticks[a.id].finalised_at)).slice(0, 40);
  const smSold = (m) => (SM.now[m.item]?.shop ?? m.shop_after) < 0;
  function stockStats() {
    const p = smPending(), t = p.filter((m) => SM.ticks[m.id]?.ticked).length, sold = p.filter(smSold).length;
    return { stats: [[String(p.length - t), "to move and tick"], [String(t), "ticked, not finalised"], [String(sold), "sold before moved"]],
      warn: sold ? `${sold} sold before they were moved` : "" };
  }
  function smRow(m, done) {
    const tk = SM.ticks[m.id] || {}, now = SM.now[m.item] || { shop: m.shop_after, backup: m.backup_after }, sold = now.shop < 0;
    const thumb = m.img ? `<img src="${esc(m.img + (m.img.includes("?") ? "&" : "?") + "width=160")}" alt="" loading="lazy" width="64" height="80">` : `<span class="ph"></span>`;
    const who = done ? `Finalised by ${esc(tk.finalised_by_name || "—")}, ${fmtTime(tk.finalised_at)}` : tk.ticked ? `Ticked by ${esc(tk.ticked_by_name || "—")}, ${fmtTime(tk.ticked_at)}` : `Moved in Shopify ${fmtTime(m.moved_at)}`;
    return `<label class="sm-row${tk.ticked ? " on" : ""}${sold ? " sold" : ""}">
      <input type="checkbox" data-mid="${esc(m.id)}" ${tk.ticked ? "checked" : ""} ${done ? "disabled" : ""} aria-label="Moved to shop: ${esc(m.product)} ${esc(m.variant)}">
      ${thumb}
      <span class="sm-main"><b>${esc(m.product)}</b><span class="vp">${esc(m.variant || "One size")}</span><span class="sub">${esc(m.sku)}</span>
        <span class="sub">${who}</span>${sold ? `<span class="sm-flag">${svg("alert")}Sold before it was moved. Shop location is ${now.shop}.</span>` : ""}</span>
      <span class="sm-q"><span><b class="${now.shop < 0 ? "neg" : ""}">${now.shop}</b>Shop</span><span><b>${now.backup}</b>Backup</span></span></label>`;
  }
  function renderStock() {
    const p = smPending(), d = smDone(), st = stockStats();
    $("#sm-sum").innerHTML = st.stats.map((s) => `<div class="st"><b>${esc(s[0])}</b><span>${esc(s[1])}</span></div>`).join("");
    $("#sm-list").innerHTML = p.map((m) => smRow(m, false)).join("");
    $("#sm-status").hidden = p.length > 0; $("#sm-status").textContent = "Nothing to move right now. New moves appear here after each order.";
    $("#sm-done-wrap").hidden = !d.length; $("#sm-done").innerHTML = d.map((m) => smRow(m, true)).join("");
    const fx = (SM.fixes || []).slice().sort((a, b) => b.at.localeCompare(a.at));
    $("#sm-fix-wrap").hidden = !fx.length; $("#sm-fix-sum").textContent = `Website stock numbers corrected (${fx.length})`;
    $("#sm-fix").innerHTML = fx.slice(0, 100).map((f) => `<div class="sm-fx"><span class="sm-main"><b>${esc(f.product)}</b><span class="vp">${esc(f.variant || "One size")}</span><span class="sub">${esc(f.sku)} · ${fmtTime(f.at)}</span><span class="sub">${esc(f.why)}</span></span><span class="sm-ch"><s>ST ${esc(f.was)}</s><b>ST ${esc(f.now)}</b></span></div>`).join("");
    const t = p.filter((m) => SM.ticks[m.id]?.ticked).length;
    $("#sm-bar").hidden = !p.length; $("#sm-count").textContent = `${t} of ${p.length} ticked`; $("#sm-final").disabled = !t;
    $("#sm-final").textContent = "Stock finalised"; delete $("#sm-final").dataset.confirm;
    $$("#sm-list input[data-mid]").forEach((c) => c.addEventListener("change", async () => {
      c.disabled = true;
      const { error } = await sb.rpc("tick_stock_move", { mid: c.dataset.mid, on_: c.checked });
      if (error) { toast(error.message); c.checked = !c.checked; c.disabled = false; return; }
      SM.ticks[c.dataset.mid] = { ...(SM.ticks[c.dataset.mid] || {}), ticked: c.checked, ticked_by_name: me.display_name || me.username, ticked_at: new Date().toISOString() };
      renderStock();
    }));
  }
  $("#sm-final").addEventListener("click", async () => {
    const b = $("#sm-final");
    if (b.dataset.confirm !== "1") { b.dataset.confirm = "1"; b.textContent = "Tap again to confirm"; setTimeout(() => { if (b.dataset.confirm === "1") { delete b.dataset.confirm; b.textContent = "Stock finalised"; } }, 4000); return; }
    b.disabled = true; b.textContent = "Saving…";
    const { data, error } = await sb.rpc("finalise_stock_moves");
    if (error) { toast(error.message); renderStock(); return; }
    toast(`${data} move${data === 1 ? "" : "s"} finalised`);
    try { await loadMoves(); } catch (_) {}
    renderStock();
  });
  $("#sm-report").addEventListener("click", () => openReport("stock", true));
  async function openStock(r) {
    page("stock", r.title);
    $("#sm-list").innerHTML = ""; $("#sm-sum").innerHTML = ""; $("#sm-bar").hidden = true; $("#sm-done-wrap").hidden = true;
    const st = $("#sm-status"); st.hidden = false; st.textContent = "Loading…";
    try { await loadMoves(); renderStock(); }
    catch (e) { st.textContent = e.message === "not-published" ? "No moves have been logged yet." : "The move list couldn't be loaded. Pull down to refresh."; }
  }


  // ---------- order attribution ----------
  const ORDER_SOURCES = ["Google Online Orders - WEB","Google CALLS MEL - SALE","Google Direction MEL - Store Visit","FB Online Orders - WEB","FB CALLS MEL - SALE","FB/IG PAGE MSGS MEL - SALE","FB WHATSAPP MSGS MEL - SALE","Organic Orders","Repeat Customer","Word of Mouth","Marketplace MEL","Marketplace SYD","Marketplace BRN","AI","Direct order","Invalid","Unknown Online","Unknown Offline"];
  let OA = { rows: [], channel: null };
  const oaPending = () => OA.rows.filter((r) => !r.order_source || r.sync_status !== "synced");
  const oaDone = () => OA.rows.filter((r) => r.order_source && r.sync_status === "synced").slice(0, 40);
  const oaMoney = (v, c = "AUD") => new Intl.NumberFormat("en-AU", { style: "currency", currency: c, maximumFractionDigits: 2 }).format(Number(v || 0));

  async function loadAttribution() {
    const { data, error } = await sb.from("order_attribution_queue")
      .select("order_id,legacy_id,order_name,created_at,customer_name,total,currency,shopify_source,products,order_source,sync_status,sync_error,updated_at")
      .order("created_at", { ascending: false }).limit(150);
    if (error) throw new Error(error.message);
    OA.rows = data || [];
    return OA.rows;
  }
  function attributionStats() {
    const p = oaPending(), syncing = p.filter((r) => r.sync_status === "syncing").length;
    const value = p.reduce((a, r) => a + Number(r.total || 0), 0);
    const newest = OA.rows[0]?.updated_at || OA.rows[0]?.created_at;
    return {
      stats: [[String(p.length), "orders need a source"], [String(syncing), "syncing now"], [oaMoney(value), "pending order value"]],
      warn: p.length ? `${p.length} order${p.length === 1 ? "" : "s"} need attribution` : "",
      updated: newest ? fmtTime(newest) : "",
    };
  }
  function oaProducts(r) {
    const a = Array.isArray(r.products) ? r.products : [];
    return a.length ? a.map((p) => `${esc(p.title || "Item")}${Number(p.quantity || 1) > 1 ? ` × ${Number(p.quantity)}` : ""}`).join(" · ") : "Order details";
  }
  function oaRow(r) {
    const syncing = r.sync_status === "syncing", failed = r.sync_status === "error";
    const opts = ['<option value="">Choose source…</option>'].concat(ORDER_SOURCES.map((x) => `<option value="${esc(x)}" ${r.order_source === x ? "selected" : ""}>${esc(x)}</option>`)).join("");
    const stat = syncing ? '<span class="oa-state syncing">Syncing…</span>' : failed ? '<span class="oa-state error">Sync failed</span>' : r.order_source ? '<span class="oa-state done">Synced</span>' : '<span class="oa-state pending">Pending</span>';
    const retry = failed && r.order_source ? `<button class="btn sm oa-retry" type="button" data-order="${esc(r.order_id)}" data-source="${esc(r.order_source)}">Retry</button>` : "";
    return `<div class="oa-row ${failed ? "has-error" : ""}" data-order="${esc(r.order_id)}">
      <div class="oa-top">
        <a class="oa-order" href="https://admin.shopify.com/store/bvdxj3-r8/orders/${esc(r.legacy_id)}" target="_blank" rel="noopener">${esc(r.order_name)}</a>
        <b class="oa-total">${oaMoney(r.total, r.currency)}</b>
        ${stat}
      </div>
      <div class="oa-meta">${esc((r.shopify_source || "Shopify").toUpperCase())} · ${fmtTime(r.created_at)}${r.customer_name ? " · " + esc(r.customer_name) : ""}</div>
      <div class="oa-products">${oaProducts(r)}</div>
      <div class="oa-actions">
        <select class="oa-source" data-order="${esc(r.order_id)}" aria-label="Order source for ${esc(r.order_name)}" ${syncing ? "disabled" : ""}>${opts}</select>
        ${retry}
      </div>
      ${failed ? `<div class="oa-error">${esc(r.sync_error || "Shopify did not accept the update. Retry or choose another source.")}</div>` : ""}
    </div>`;
  }
  function renderAttribution() {
    const p = oaPending(), d = oaDone(), value = p.reduce((a, r) => a + Number(r.total || 0), 0);
    $("#oa-sum").innerHTML = [
      [p.length, "pending orders"],
      [p.filter((r) => r.sync_status === "syncing").length, "syncing"],
      [oaMoney(value), "pending value"],
    ].map((x) => `<div class="st"><b>${esc(x[0])}</b><span>${esc(x[1])}</span></div>`).join("");
    $("#oa-pending").innerHTML = p.map(oaRow).join("");
    $("#oa-status").hidden = p.length > 0;
    $("#oa-status").textContent = "All current orders are attributed.";
    $("#oa-done-wrap").hidden = !d.length;
    $("#oa-done").innerHTML = d.map(oaRow).join("");
    $(".oa-source").forEach((sel) => sel.addEventListener("change", () => { if (sel.value) syncAttribution(sel.dataset.order, sel.value); }));
    $(".oa-retry").forEach((b) => b.addEventListener("click", () => syncAttribution(b.dataset.order, b.dataset.source)));
  }
  async function syncAttribution(orderId, source) {
    const row = OA.rows.find((r) => r.order_id === orderId);
    if (!row || !source) return;
    row.order_source = source; row.sync_status = "syncing"; row.sync_error = null; renderAttribution();
    try {
      const { data, error } = await sb.functions.invoke("order-attribution", { body: { action: "update", order_id: orderId, source } });
      if (error) {
        let msg = error.message; try { const j = await error.context.json(); msg = j.error || msg; } catch (_) {}
        throw new Error(msg);
      }
      if (data?.error) throw new Error(data.error);
      toast(`${row.order_name} syncing to Shopify`);
    } catch (e) {
      row.sync_status = "error"; row.sync_error = e.message; renderAttribution(); toast(e.message);
    }
  }
  async function openAttribution(r) {
    page("attribution", r.title);
    $("#oa-pending").innerHTML = ""; $("#oa-sum").innerHTML = ""; $("#oa-done-wrap").hidden = true;
    const st = $("#oa-status"); st.hidden = false; st.textContent = "Loading…";
    try { await loadAttribution(); renderAttribution(); } catch (e) { st.textContent = "The order queue couldn't be loaded. Pull down to refresh."; }
    updateOrderNotifyButton();
  }
  function updateOrderNotifyButton() {
    const b = $("#oa-notify"); if (!b) return;
    if (!("Notification" in window)) { b.hidden = true; return; }
    b.hidden = false;
    b.disabled = Notification.permission === "granted";
    b.textContent = Notification.permission === "granted" ? "Notifications on" : Notification.permission === "denied" ? "Notifications blocked" : "Enable notifications";
  }
  async function enableOrderNotifications() {
    if (!("Notification" in window)) return toast("Notifications aren't supported on this device.");
    const p = await Notification.requestPermission();
    updateOrderNotifyButton();
    toast(p === "granted" ? "New-order notifications enabled" : "Notification permission wasn't enabled");
  }
  $("#oa-notify").addEventListener("click", enableOrderNotifications);
  async function notifyNewOrder(r) {
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    const items = Array.isArray(r.products) ? r.products : [];
    const body = `${items[0]?.title || "New Shopify order"} · ${oaMoney(r.total, r.currency)}`;
    const data = { url: location.origin + location.pathname + "#order-attribution" };
    try {
      if ("serviceWorker" in navigator) {
        const reg = await navigator.serviceWorker.ready;
        await reg.showNotification(`New order ${r.order_name}`, { body, icon: "icons/icon-192.png", badge: "icons/icon-192.png", tag: "order-" + r.legacy_id, data });
      } else new Notification(`New order ${r.order_name}`, { body });
    } catch (_) {}
  }
  function startAttributionRealtime() {
    if (OA.channel || !reports.some((r) => r.id === "order-attribution")) return;
    OA.channel = sb.channel("order-attribution-live")
      .on("postgres_changes", { event: "*", schema: "public", table: "order_attribution_queue" }, async (payload) => {
        if (payload.eventType === "INSERT" && payload.new) notifyNewOrder(payload.new);
        try { await loadAttribution(); } catch (_) { return; }
        if (!$("#v-attribution").hidden) renderAttribution();
        if (!$("#v-home").hidden) renderHome();
      }).subscribe();
  }

  // ---------- report viewer ----------
  async function openReport(id, full) {
    const r = reports.find((x) => x.id === id); if (!r) return go("home");
    if (location.hash !== "#" + id) history.pushState(null, "", "#" + id);
    if (id === "stock" && !full) return openStock(r);
    if (id === "order-attribution") return openAttribution(r);
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
    startAttributionRealtime(); updateOrderNotifyButton();
    const id = location.hash.slice(1);
    if (id && reports.some((r) => r.id === id)) openReport(id); else { page("home"); renderHome(); }
  }
  sb.auth.onAuthStateChange((ev) => { if (ev === "SIGNED_OUT") view("login"); });
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  start();
})();

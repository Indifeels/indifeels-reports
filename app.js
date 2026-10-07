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

  $("#dashboard-theme").addEventListener("click", () => $("#m-theme").click());

  // ---------- helpers ----------
  function toast(msg) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2600); }
  function showErr(id, msg) { const e = $(id); e.textContent = msg; e.hidden = !msg; }
  function busy(btn, on, label) { btn.disabled = on; if (label) { btn.dataset.l = btn.dataset.l || btn.textContent; btn.textContent = on ? label : btn.dataset.l; } }
  $$(".eye:not(.gen)").forEach((b) => b.addEventListener("click", () => { const i = document.getElementById(b.dataset.for); const s = i.type === "password"; i.type = s ? "text" : "password"; b.textContent = s ? "Hide" : "Show"; }));
  function genPassword() { const a = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"; const r = crypto.getRandomValues(new Uint32Array(10)); return "Indi-" + Array.from(r, (x) => a[x % a.length]).join(""); }

  // ---------- views ----------
  const VIEWS = ["login", "reset", "shell"];
  const PAGES = ["home", "report", "stock", "attribution", "password", "admin", "schedule"];
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

  // ---------- phone push notifications ----------
  const b64urlBytes = (s) => {
    const p = "=".repeat((4 - s.length % 4) % 4);
    const b = atob((s + p).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(b, (x) => x.charCodeAt(0));
  };
  async function phonePushState() {
    const b = $("#m-push"); if (!b) return;
    if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) {
      b.textContent = "Phone notifications unavailable"; b.disabled = true; return;
    }
    if (Notification.permission === "denied") {
      b.textContent = "Phone notifications blocked"; b.disabled = true; return;
    }
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      b.textContent = sub ? "Phone notifications on" : "Enable phone notifications";
      b.disabled = !!sub;
    } catch (_) {
      b.textContent = "Enable phone notifications"; b.disabled = false;
    }
  }
  async function enablePhonePush() {
    if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) {
      return toast("Phone push notifications aren't supported on this device.");
    }
    let p = Notification.permission;
    if (p !== "granted") p = await Notification.requestPermission();
    if (p !== "granted") { await phonePushState(); return toast("Phone notifications weren't enabled."); }
    try {
      const reg = await navigator.serviceWorker.ready;
      let sub = await reg.pushManager.getSubscription();
      if (!sub) {
        const kr = await fetch(`${CFG.url}/functions/v1/report-phone-push?action=public-key`, { cache:"no-store" });
        if (!kr.ok) throw new Error("Could not get push key.");
        const { publicKey } = await kr.json();
        sub = await reg.pushManager.subscribe({ userVisibleOnly:true, applicationServerKey:b64urlBytes(publicKey) });
      }
      const j = sub.toJSON();
      const { error } = await sb.from("push_subscriptions").upsert({
        user_id: me.id,
        endpoint: sub.endpoint,
        p256dh: j.keys?.p256dh || "",
        auth_key: j.keys?.auth || "",
        origin: location.origin,
        enabled: true,
        updated_at: new Date().toISOString()
      }, { onConflict:"endpoint" });
      if (error) throw error;
      toast("Phone report notifications enabled");
    } catch (e) {
      toast(e?.message || "Could not enable phone notifications.");
    }
    await phonePushState();
  }
  $("#m-push")?.addEventListener("click", enablePhonePush);

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
      sb.from("reports").select("id,title,description,sort,category_id,admin_only").order("sort"),
      sb.from("report_keys").select("report_id,key_b64"),
    ]);
    if (e1 || e2) throw new Error((e1 || e2).message);
    reports = (reps || []).filter(r=>!r.admin_only || me?.is_admin);
    const {data: cats,error: ce} = await sb.from("report_categories").select("*").order("sort");
    if(ce) throw new Error(ce.message);
    if(cats?.length) HOME_GROUPS=cats.map(c=>({id:c.id,name:c.title,color:c.color,ids:reports.filter(r=>r.category_id===c.id).map(r=>r.id)}));
    keys = Object.fromEntries((ks || []).map((k) => [k.report_id, k.key_b64]));
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
    eye: '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="2.5"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
  };
  const svg = (k, cls = "") => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${I[k] || I.chart}</svg>`;
  const LOOK = {
    "schedule-panel": { c: "purple", icon: "clock", stat: [], line: [] },
    daily: { c: "purple", icon: "mega", stat: ["dollar", "msg", "bag", "bars"], line: ["purple", "purple", "green", "purple"] },
    monthly: { c: "green", icon: "trend", stat: [null, null, null, null], line: ["green", "purple", "orange", "green"] },
    stock: { c: "orange", icon: "box", stat: ["box", "box", "tag"], line: [] },
    "order-attribution": { c: "teal", icon: "tag", stat: ["tag", "clock", "dollar"], line: ["teal", "purple", "green"] },
    "product-visibility": { c: "purple", icon: "eye", stat: ["eye", "tag", "alert"], line: ["purple", "teal", "rose"] },
    restock: { c: "orange", icon: "box", stat: ["box", "alert", "tag"], line: [] },
    footwear: { c: "rose", icon: "search", stat: ["search", "bars", "trend"], line: ["rose", "purple", "green"] },
    "google-tracked": { c: "purple", icon: "chart", stat: ["dollar", "bag", "trend", "tag"], line: ["purple", "purple", "green", "teal"] },
    "call-tracking": { c: "teal", icon: "chart", stat: ["msg", "tag", "alert"], line: ["teal", "green", "rose"] },
    "order-source": { c: "teal", icon: "bars", stat: ["dollar", "bag", "trend", "tag"], line: ["purple", "purple", "green", "teal"] },
    "tech-availability": { c: "teal", icon: "alert", stat: ["bars", "alert", "alert"], line: ["teal", "orange", "rose"] },
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
  let status = {}, scheduleStatus = {}, scheduleControl = {};
  async function loadStatus() {
    try { const res = await fetch(`r/status.json?t=${Date.now()}`, { cache: "no-store" }); status = res.ok ? await res.json() : {}; } catch (_) { status = {}; }
  }
  const fmtTime = (iso) => new Date(iso).toLocaleString("en-AU", { timeZone: "Australia/Sydney", weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
  function health(id) {
    const run = scheduleStatus[id], control = scheduleControl[id];
    if (run?.status === "failed") return {title:"Last refresh failed",text:run.detail || "Open Schedule Panel for details."};
    if (control && !control.runner) return {title:"Refresh not connected",text:control.runner_note || "This report has no automatic data refresh runner."};
    if (control && (!control.enabled || run)) return null;
    const s = status[id]; if (!s) return null;
    if (s.ok === false) return { title: "Last refresh failed", text: `${s.reason || "The refresh didn't finish."}${s.last_ok ? ` Showing data from ${fmtTime(s.last_ok)}.` : ""}` };
    const age = s.last_ok ? (Date.now() - new Date(s.last_ok).getTime()) / 36e5 : Infinity;
    if (age > (MAX_AGE_H[id] || 26)) return { title: "Refresh overdue", text: `No successful refresh since ${s.last_ok ? fmtTime(s.last_ok) : "it was set up"}. Check the scheduled task.` };
    return null;
  }
  let HOME_GROUPS = [
    {name:"Sales Analysis",color:"#568F8C",ids:["order-source","order-attribution","call-tracking"]},
    {name:"Facebook",color:"#986D7E",ids:["facebook-tracked","daily","monthly"]},
    {name:"Google",color:"#AD915A",ids:["google-tracked","google-non-tracked"]},
    {name:"Stock Management",color:"#708C74",ids:["stock","product-visibility","restock"]},
    {name:"SEO",color:"#927CA2",ids:["footwear"]},
    {name:"Admin Panel",color:"#838099",ids:["schedule-panel","tech-availability"]}
  ];
  const HOME_TITLES = {daily:"Facebook Non-tracked",monthly:"Facebook Monthly Profitability",stock:"Stock Movement & Negative Stock",footwear:"SEO Rankings","google-tracked":"Google Tracked"};
  const homeMeta = {}, homePeriods = {};
  function homePending(id) {
    if (id === "order-attribution" && homeMeta[id]) return oaPending().length;
    if (id === "stock" && homeMeta[id]) return smPending().length;
    const v=homeMeta[id]?.actions_pending;
    return Number.isFinite(Number(v)) && v != null ? Number(v) : null;
  }
  function homeWarning(id) { return !!(health(id) || homeMeta[id]?.warn || homeMeta[id]?.health === "bad"); }
  function homeUpdated(id,meta) {
    const iso=status[id]?.last_ok || (scheduleStatus[id]?.status === "succeeded" ? scheduleStatus[id]?.finished_at : null);
    if (iso && !isNaN(Date.parse(iso))) return new Date(iso).toLocaleString("en-AU",{timeZone:"Australia/Melbourne",day:"2-digit",month:"short",year:"numeric",hour:"numeric",minute:"2-digit"});
    return meta?.updated || "Not available";
  }
  function compactKpiLabel(label) {
    const clean=String(label).replace(/(?:,?\s*)(yesterday|today(?: so far)?|last \d+ days|this month)/ig,"").trim();
    const names={"orders need review":"Review","syncing now":"Syncing","pending order value":"Value","overall ROAS":"ROAS","Google Ads":"Google Ads","GMB":"GMB","ad spend":"Spend","net profit":"Profit","cost per message":"Cost/msg","to move and tick":"To move","ticked, not finalised":"Ticked","sold before moved":"Sold","Reports managed":"Reports"};
    return names[clean] || clean.replace(/^./,x=>x.toUpperCase());
  }
  function publishedPeriods(id,html) {
    const doc=new DOMParser().parseFromString(html,"text/html"),out={};
    const text=el=>el?.textContent.replace(/\s+/g," ").trim() || "—";
    const fromKpis=nodes=>Array.from(nodes).slice(0,4).map(el=>{const v=el.querySelector("b,.v");return [text(v),text(el.querySelector(".l") || el.querySelector("span:not(.chg):not(.ar):not(.dl)"))];});
    if(id==="order-source"){
      const match=html.match(/^const M=(.+);$/m);
      if(match){const model=JSON.parse(match[1]).model;for(const [key,label] of [["y","Yesterday"],["d7","7 days"],["d15","15 days"],["d30","30 days"]]){const a=model[key]?.all,paid=model[key]?.paid;if(a)out[key]={label,stats:[[oaMoney(paid?.spend || 0),"Spend"],[oaMoney(a.revenue || 0),"Revenue"],[a.roas==null?"—":Number(a.roas).toFixed(2)+"×","ROAS"],[oaMoney(a.profit || 0),"Profit"]]};}}
    } else if(id==="google-tracked"){
      const total=Array.from(doc.querySelectorAll("tr.total")).find(el=>text(el.querySelector("th"))==="All tracked campaigns");
      if(total)for(const [key,cls,label] of [["y","t","Yesterday"],["d7","w","7 days"],["d15","x","15 days"],["d30","m","30 days"],["life","l","Lifetime"]]){const cells=total.querySelectorAll("td.c"+cls);if(cells.length===4)out[key]={label,stats:Array.from(cells).map((el,i)=>{const copy=el.cloneNode(true);copy.querySelectorAll(".ar,.chg").forEach(x=>x.remove());return [text(copy),["Spend","Revenue","ROAS","Profit"][i]];})};}
    } else if(id==="call-tracking"){
      for(const [key,pub,label] of [["y","yesterday","Yesterday"],["d7","last_7","7 days"],["d15","last_15","15 days"],["d30","last_30","30 days"],["life","lifetime","Lifetime"]]){const node=doc.querySelector(`[data-p="${pub}"] .kpis`);if(node){const cards=Array.from(node.querySelectorAll(".kpi"));const total=cards[0],google=cards.find(x=>text(x.querySelector(".l"))==="Google Ads Paid"),website=cards.find(x=>text(x.querySelector(".l"))==="Website");out[key]={label,stats:[[text(total?.querySelector(".v")),"Calls"],[text(google?.querySelector(".v")),"Google Ads"],[text(website?.querySelector(".v")),"Website"]]};}}
    } else {
      if(id==="daily"){
        const total=Array.from(doc.querySelectorAll("tr.total")).find(el=>text(el.querySelector("th"))==="All non-tracked campaigns");
        if(total)for(const [key,cls,label] of [["y","t","Yesterday"],["d7","w","7 days"],["d15","x","15 days"],["d30","m","30 days"],["life","l","Lifetime"]]){const cells=total.querySelectorAll("td.c"+cls);if(cells.length===3)out[key]={label,stats:Array.from(cells).map((el,i)=>{const copy=el.cloneNode(true);copy.querySelectorAll(".ar").forEach(x=>x.remove());return [text(copy),["Spend","Messages","Cost/msg"][i]];})};}
      }
      for(const node of doc.querySelectorAll(".kpi")){const heading=text(node.querySelector("h2")),key=/yesterday/i.test(heading)?"y":/7 days/i.test(heading)?"d7":/15 days/i.test(heading)?"d15":/30 days/i.test(heading)?"d30":/lifetime/i.test(heading)?"life":null;if(key && !out[key]){const cells=node.querySelectorAll(".kv:not(.sv) > div");if(cells.length)out[key]={label:heading,stats:fromKpis(cells)};}}
    }
    return out;
  }
  function tileHTML(r,meta) {
    const L=look(r.id), hl=health(r.id), sr=scheduleStatus[r.id];
    const failed=sr?.status === "failed" || (!sr && status[r.id]?.ok === false);
    const pending=homePending(r.id);
    const label=sr?.status === "in_progress" ? "In progress" : sr?.status === "queued" ? "Queued" : failed ? "Refresh failed" : scheduleControl[r.id]?.enabled === false ? "Paused" : pending ? `${pending} pending` : homeWarning(r.id) ? "Review" : meta ? "Up to date" : "No data";
    const tone=failed ? "failed" : homeWarning(r.id) || pending ? "warning" : meta ? "good" : "unknown";
    const selected=homePeriods[r.id] || (meta?.periods?.y ? "y" : "summary");
    const period=meta?.periods?.[selected];
    const unavailable=selected!=="summary" && !period;
    const st=(unavailable ? (meta?.stats || []).map(x=>["—",x[1]]) : period?.stats || meta?.stats || []).slice(0,4);
    const stats=st.map(x=>{const raw=String(x[0]),suffix=raw.match(/\s*(\([^)]*\))$/),value=suffix?raw.slice(0,suffix.index):raw;const numeric=Number(value.replace(/[^0-9.-]/g,""));const displayed=/\$/.test(value)&&Number.isFinite(numeric)?new Intl.NumberFormat("en-AU",{style:"currency",currency:"AUD",maximumFractionDigits:0,notation:Math.abs(numeric)>=10000?"compact":"standard"}).format(/−/.test(value)?-numeric:numeric):value;return `<div class="report-kpi"><span title="${esc(x[1])}">${esc(compactKpiLabel(x[1]))}</span><strong title="${esc(value)}">${esc(displayed)}</strong>${suffix?`<small>${esc(suffix[1])}</small>`:""}</div>`;}).join("");
    const periodLabel=st.some(x=>/yesterday/i.test(x[1])) ? "Yesterday" : st.some(x=>/today/i.test(x[1])) ? "Today so far" : r.id === "monthly" ? "This month" : "Summary";
    const timeReport=["order-source","google-tracked","daily","monthly","call-tracking","order-attribution"].includes(r.id);
    const options=timeReport ? [["summary","Summary"],["y","Yesterday"],["d7","7 days"],["d15","15 days"],["d30","30 days"],["life","Lifetime"]] : [["summary","Summary"]];
    const choices=options.map(([key,label])=>`<option value="${key}" ${selected===key?"selected":""}>${key==="summary"?"Summary":label}</option>`).join("");
    return `<article class="report-card" data-id="${esc(r.id)}" style="--report-accent:var(--category-accent,var(--${L.c}))"><div class="report-heading"><span class="report-icon">${svg(L.icon)}</span><h3>${esc(HOME_TITLES[r.id] || r.title)}</h3></div><p class="report-updated">Last updated · ${esc(homeUpdated(r.id,meta))}</p><div class="report-kpis">${stats || '<span class="report-unavailable">Summary not available yet</span>'}</div><div class="report-bottom"><span class="report-status ${tone}" title="${esc(hl?.text || meta?.warn || label)}">${homeWarning(r.id)?svg("alert"):"<i></i>"}${esc(label)}</span><select class="report-period" aria-label="Summary period for ${esc(r.title)}">${choices}</select><button type="button" class="report-open" data-open="${esc(r.id)}">Open Report <span aria-hidden="true">›</span></button></div>${unavailable?`<p class="report-issue">This period is not available in the published data yet.</p>`:hl?`<p class="report-issue">${esc(hl.text)}</p>`:""}</article>`;
  }
  function fitHomeTitles() {
    document.querySelectorAll(".report-heading h3").forEach(el=>{let size=16;el.style.fontSize=size+"px";while(el.scrollWidth>el.clientWidth && size>10){size-=.5;el.style.fontSize=size+"px";}});
  }
  window.addEventListener("resize",fitHomeTitles);
  function paintHomeCards() {
    const box=$("#tiles");
    box.querySelectorAll(".report-card").forEach(el=>{const r=reports.find(x=>x.id===el.dataset.id);if(r) el.outerHTML=tileHTML(r,homeMeta[r.id]);});
    fitHomeTitles();
    box.querySelectorAll(".report-open").forEach(b=>b.addEventListener("click",()=>openReport(b.dataset.open)));
    box.querySelectorAll(".report-period").forEach(select=>select.addEventListener("change",()=>{homePeriods[select.closest(".report-card").dataset.id]=select.value;paintHomeCards();}));
    box.querySelectorAll(".report-category").forEach(el=>{
      const ids=JSON.parse(el.dataset.ids), counts=ids.map(homePending), known=counts.filter(x=>x!=null);
      el.querySelector('[data-count="actions"]').textContent=known.length ? known.reduce((a,b)=>a+b,0)+(known.length<ids.length?"+":"") : "—";
      const warnings=ids.filter(homeWarning).length;
      el.querySelector('[data-count="warnings"]').textContent=String(warnings);
      el.classList.toggle("has-warning",warnings>0);
    });
  }
  function updateHomeClock() {
    if(!me)return;
    const now=new Date(),hour=Number(new Intl.DateTimeFormat("en-AU",{timeZone:"Australia/Melbourne",hour:"numeric",hourCycle:"h23"}).format(now));
    const greeting=hour<12?"Good morning":hour<17?"Good afternoon":"Good evening";
    $("#hello").textContent=`${greeting}${me.display_name?", "+me.display_name.split(" ")[0]:""}`;
    const clock=zone=>new Intl.DateTimeFormat("en-AU",{timeZone:zone,hour:"numeric",minute:"2-digit"}).format(now);
    const date=new Intl.DateTimeFormat("en-AU",{timeZone:"Australia/Melbourne",weekday:"short",day:"numeric",month:"short"}).format(now);
    $("#home-sub").innerHTML=`<span class="home-date">${esc(date)}</span><span class="home-clocks"><span>🇦🇺 Melbourne <b>${esc(clock("Australia/Melbourne"))}</b></span><span>🇮🇳 New Delhi <b>${esc(clock("Asia/Kolkata"))}</b></span></span>`;
  }
  setInterval(updateHomeClock,60000);
  function syncHomeExpand(){const groups=Array.from(document.querySelectorAll("#tiles .report-category"));$("#home-expand").textContent=groups.length && groups.every(x=>x.open)?"Collapse All":"Expand All";$("#home-expand").disabled=!groups.length;}
  $("#home-expand").addEventListener("click",()=>{const groups=Array.from(document.querySelectorAll("#tiles .report-category")),open=!groups.every(x=>x.open);groups.forEach(x=>{x.open=open;try{localStorage.setItem("ir-category-"+x.dataset.group,open?"open":"closed");}catch(_){}});syncHomeExpand();});
  let weatherChecked=0;
  async function loadHomeWeather(){
    if(Date.now()-weatherChecked<1800000)return;weatherChecked=Date.now();
    try{const response=await fetch("https://api.met.no/weatherapi/locationforecast/2.0/compact?lat=-37.81&lon=144.96",{signal:AbortSignal.timeout(7000)});if(!response.ok)return;
      const data=await response.json(),series=data.properties?.timeseries || [],now=Date.now(),entry=series.reduce((best,x)=>Math.abs(Date.parse(x.time)-now)<Math.abs(Date.parse(best.time)-now)?x:best,series[0]);
      const temp=entry?.data?.instant?.details?.air_temperature,code=entry?.data?.next_1_hours?.summary?.symbol_code || "",label=code.replace(/_(day|night|polartwilight)$/,""),icon=/thunder/.test(code)?"⛈️":/snow/.test(code)?"🌨️":/rain|sleet/.test(code)?"🌧️":/fog/.test(code)?"🌫️":/partly|fair/.test(code)?"⛅":/cloud/.test(code)?"☁️":/clearsky/.test(code)?(/night/.test(code)?"🌙":"☀️"):"🌤️";
      if(Number.isFinite(temp)){const el=$("#home-weather");el.innerHTML=`<small class="weather-city">Melbourne</small><span>${icon} ${Math.round(temp)}°C</span><small class="weather-credit">Weather source</small>`;el.title=`Melbourne forecast · ${label} · Weather data: MET Norway`;el.href="https://www.met.no/en";el.hidden=false;}
    }catch(_){}
  }
  async function renderHome() {
    const box=$("#tiles");
    updateHomeClock();
    loadHomeWeather();
    await loadStatus();
    try { const [rr,cc]=await Promise.all([sb.from("report_refresh_runs").select("report_id,status,scheduled_at,finished_at,detail").order("scheduled_at",{ascending:false}),sb.from("report_refresh_control").select("report_id,enabled,runner,runner_note")]);scheduleStatus={};(rr.data||[]).forEach(x=>{if(!scheduleStatus[x.report_id])scheduleStatus[x.report_id]=x;});scheduleControl=Object.fromEntries((cc.data||[]).map(x=>[x.report_id,x])); } catch(_) {}
    const knownIds=HOME_GROUPS.flatMap(g=>g.ids);
    const extras=reports.filter(r=>!knownIds.includes(r.id));
    box.innerHTML=HOME_GROUPS.map((g,i)=>{
      const rows=g.ids.map(id=>reports.find(r=>r.id===id)).filter(Boolean).concat(i===5?extras:[]);
      if(!rows.length)return "";
      const upcoming=i===1?[{title:"Facebook Tracked"}]:i===2?[{title:"Google Non-tracked"}]:[];
      let expanded=false;try{expanded=localStorage.getItem("ir-category-"+i)==="open";}catch(_){}
      return `<details class="report-category" data-group="${i}" data-ids='${JSON.stringify(rows.map(r=>r.id))}' style="--category-accent:${g.color}" ${expanded?"open":""}><summary><h3>${i+1}. ${esc(g.name)}</h3><div class="category-counts"><span>Reports<strong>${rows.length+upcoming.length}</strong></span><span>Actions pending<strong data-count="actions">—</strong></span><span>Warnings<strong data-count="warnings">0</strong></span></div><span class="category-chevron" aria-hidden="true">⌄</span></summary><div class="category-reports">${rows.map(r=>tileHTML(r,homeMeta[r.id])).join("")}${upcoming.map(r=>`<article class="report-upcoming"><strong>${r.title}</strong><span>Upcoming</span></article>`).join("")}</div></details>`;
    }).join("");
    box.querySelectorAll(".report-category").forEach(el=>el.addEventListener("toggle",()=>{try{localStorage.setItem("ir-category-"+el.dataset.group,el.open?"open":"closed");}catch(_){}syncHomeExpand();}));
    syncHomeExpand();
    $("#home-report-count").textContent=`${reports.length} reports · ${box.querySelectorAll(".report-category").length} categories`;
    $("#no-reports").hidden=reports.length>0;paintHomeCards();
    await Promise.all(reports.map(async r=>{
      try {
        let meta;
        if(r.id==="order-attribution"){await loadAttribution();meta=attributionStats();}
        else if(r.id==="footwear")meta=seoMeta(await loadSeoRankingsData());
        else if(r.id==="tech-availability")meta=techMeta(await loadTechAvailability());
        else if(r.id==="report-access"){const data=await adminCall({action:"list"});meta={stats:[[String(data.users?.length || 0),"People"],[String(data.users?.filter(x=>x.is_admin && !x.disabled).length || 0),"Admins"],[String(data.reports?.length || 0),"Reports"]]};}
        else if(r.id==="schedule-panel")meta={stats:[[String(Object.keys(scheduleControl).length),"Reports managed"],[String(Object.values(scheduleControl).filter(x=>x.enabled).length),"Enabled"],[String(Object.values(scheduleStatus).filter(x=>x.status==="failed").length),"Failed"]]};
        else if(keys[r.id]){meta=JSON.parse(await decryptFile(`r/${r.id}.meta.bin`,keys[r.id]));if(r.id==="stock"){await loadMoves();Object.assign(meta,stockStats());}}
        if(meta){
          if(r.id==="order-attribution"){
            meta.periods={};const today=new Date().toLocaleDateString("en-CA",{timeZone:"Australia/Melbourne"});
            for(const [key,days,label] of [["y",1,"Yesterday"],["d7",7,"7 days"],["d15",15,"15 days"],["d30",30,"30 days"]]){const end=new Date(today+"T00:00:00Z"),start=new Date(end.getTime()-days*86400000).toISOString().slice(0,10);const rows=OA.rows.filter(x=>{const date=new Date(x.created_at).toLocaleDateString("en-CA",{timeZone:"Australia/Melbourne"});return date>=start && date<today;}),pending=rows.filter(x=>x.attribution_auto || !x.order_source || x.sync_status!=="synced");meta.periods[key]={label,stats:[[String(rows.length),"Orders"],[String(rows.length-pending.length),"Confirmed"],[String(pending.length),"Review"]]};}
          } else if(keys[r.id] && ["order-source","google-tracked","daily","monthly","call-tracking"].includes(r.id)){
            try{meta.periods={...publishedPeriods(r.id,await decryptFile(`r/${r.id}.bin`,keys[r.id])),...meta.periods};}catch(_){}
          }
          homeMeta[r.id]=meta;
        }
      }catch(_){}paintHomeCards();
    }));
  }

  // ---------- stock move tick list ----------
  let SM = { moves: [], now: {}, ticks: {} };
  async function loadMoves() {
    const log = JSON.parse(await decryptFile("r/stock_moves.bin", keys.stock));
    const { data, error } = await sb.from("stock_ticks").select("*");
    if (error) throw new Error(error.message);
    SM = { moves: log.moves || [], fixes: log.fixes || [], neg: log.negatives || [], now: log.now || {}, ticks: Object.fromEntries((data || []).map((t) => [t.move_id, t])) };
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
  function negRow(n) {
    const thumb = n.img ? `<img src="${esc(n.img + (n.img.includes("?") ? "&" : "?") + "width=160")}" alt="" loading="lazy" width="64" height="80">` : `<span class="ph"></span>`;
    return `<div class="sm-row ng">${thumb}<span class="sm-main"><b>${esc(n.product)}</b><span class="vp">${esc(n.variant || "One size")}</span><span class="sub">${esc(n.sku)}</span></span>
      <span class="sm-q"><span><b class="${n.shop < 0 ? "neg" : ""}">${n.shop}</b>Shop</span><span><b class="${n.backup < 0 ? "neg" : ""}">${n.backup}</b>Backup</span></span></div>`;
  }
  function renderStock() {
    const p = smPending(), d = smDone(), st = stockStats();
    $("#sm-sum").innerHTML = st.stats.map((s) => `<div class="st"><b>${esc(s[0])}</b><span>${esc(s[1])}</span></div>`).join("");
    $("#sm-list").innerHTML = p.map((m) => smRow(m, false)).join("");
    $("#sm-status").hidden = p.length > 0; $("#sm-status").textContent = "Nothing to move right now. New moves appear here after each order.";
    const ng = SM.neg || [];
    $("#sm-neg-wrap").hidden = !ng.length; $("#sm-neg-sum").textContent = `Negative stock (${ng.length})`; $("#sm-neg").innerHTML = ng.map(negRow).join("");
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
    $("#sm-list").innerHTML = ""; $("#sm-sum").innerHTML = ""; $("#sm-bar").hidden = true; $("#sm-done-wrap").hidden = true; $("#sm-neg-wrap").hidden = true;
    const st = $("#sm-status"); st.hidden = false; st.textContent = "Loading…";
    try { await loadMoves(); renderStock(); }
    catch (e) { st.textContent = e.message === "not-published" ? "No moves have been logged yet." : "The move list couldn't be loaded. Pull down to refresh."; }
  }


  // ---------- order attribution ----------
  const ORDER_SOURCES = ["Google Online Orders - WEB","Google CALLS MEL - SALE","Google Direction MEL - Store Visit","FB Online Orders - WEB","FB CALLS MEL - SALE","FB/IG PAGE MSGS MEL - SALE","FB WHATSAPP MSGS MEL - SALE","Organic Orders","Repeat Customer","Word of Mouth","Marketplace MEL","Marketplace SYD","Marketplace BRN","AI","Direct order","Invalid","Unknown Online","Unknown Offline"];
  let OA = { rows: [], catalog: [], channel: null };
  const oaPending = () => OA.rows.filter((r) => r.attribution_auto === true || !r.order_source || r.sync_status !== "synced");
  const oaDone = () => OA.rows.filter((r) => r.order_source && r.sync_status === "synced" && r.attribution_auto !== true).slice(0, 40);
  const oaPaidPlatform = (source) => source === "Google Online Orders - WEB" ? "Google" : source === "FB Online Orders - WEB" ? "Facebook" : "";
  const oaMoney = (v, c = "AUD") => new Intl.NumberFormat("en-AU", { style: "currency", currency: c, maximumFractionDigits: 2 }).format(Number(v || 0));
  const oaCampaignValue = (x) => x ? `${x.platform} — ${x.campaign_name}` : "";
  const oaCampaigns = () => {
    const m = new Map();
    OA.catalog.forEach((x) => {
      const k = `${x.platform}|${x.campaign_id}`;
      const old = m.get(k);
      if (!old || String(x.last_seen_date || "") > String(old.last_seen_date || "")) m.set(k, x);
    });
    return Array.from(m.values()).sort((a, b) => {
      const ae = /active|enabled/i.test(a.campaign_status || "") ? 0 : 1;
      const be = /active|enabled/i.test(b.campaign_status || "") ? 0 : 1;
      return ae - be || a.platform.localeCompare(b.platform) || a.campaign_name.localeCompare(b.campaign_name);
    });
  };
  const oaFindCampaign = (value) => oaCampaigns().find((x) => oaCampaignValue(x) === String(value || "").trim()) || null;
  const oaAdsets = (campaign) => {
    if (!campaign) return [];
    const m = new Map();
    OA.catalog
      .filter((x) => x.platform === campaign.platform && x.campaign_id === campaign.campaign_id && x.adset_id && x.adset_name)
      .forEach((x) => {
        const old = m.get(x.adset_id);
        if (!old || String(x.last_seen_date || "") > String(old.last_seen_date || "")) m.set(x.adset_id, x);
      });
    return Array.from(m.values()).sort((a, b) => {
      const ae = /active|enabled/i.test(a.adset_status || "") ? 0 : 1;
      const be = /active|enabled/i.test(b.adset_status || "") ? 0 : 1;
      return ae - be || a.adset_name.localeCompare(b.adset_name);
    });
  };
  const oaFindAdset = (campaign, value) => oaAdsets(campaign).find((x) => x.adset_name === String(value || "").trim()) || null;

  async function loadAttribution() {
    const [q, c] = await Promise.all([
      sb.from("order_attribution_queue")
        .select("order_id,legacy_id,order_name,created_at,customer_name,contact_email,contact_phone,total,currency,shopify_source,products,order_source,campaign_platform,campaign_id,campaign_name,adset_id,adset_name,sync_status,sync_error,attribution_auto,journey_ready,journey_checked_at,journey,attribution_note,updated_at")
        .order("created_at", { ascending: false }).limit(150),
      sb.from("ad_attribution_catalog")
        .select("option_key,platform,campaign_id,campaign_name,campaign_status,adset_id,adset_name,adset_status,last_seen_date,refreshed_at")
        .order("platform").order("campaign_name"),
    ]);
    if (q.error) throw new Error(q.error.message);
    if (c.error) throw new Error(c.error.message);
    OA.rows = q.data || [];
    OA.catalog = c.data || [];
    return OA.rows;
  }
  function attributionStats() {
    const p = oaPending(), syncing = p.filter((r) => r.sync_status === "syncing").length;
    const value = p.reduce((a, r) => a + Number(r.total || 0), 0);
    const newest = OA.rows[0]?.updated_at || OA.rows[0]?.created_at;
    return {
      stats: [[String(p.length), "orders need review"], [String(syncing), "syncing now"], [oaMoney(value), "pending order value"]],
      warn: p.length ? `${p.length} order${p.length === 1 ? "" : "s"} need attribution review` : "",
      updated: newest ? fmtTime(newest) : "",
    };
  }
  function oaProducts(r) {
    const a = Array.isArray(r.products) ? r.products : [];
    return a.length ? a.map((p) => `${esc(p.title || "Item")}${Number(p.quantity || 1) > 1 ? ` × ${Number(p.quantity)}` : ""}`).join(" · ") : "Order details";
  }
  function oaCampaignOptions() {
    return oaCampaigns().map((x) => {
      const status = x.campaign_status ? ` — ${x.campaign_status}` : "";
      return `<option value="${esc(oaCampaignValue(x))}" label="${esc(x.platform + status)}"></option>`;
    }).join("");
  }
  function oaAdsetOptions(campaign) {
    return oaAdsets(campaign).map((x) => {
      const status = x.adset_status ? ` — ${x.adset_status}` : "";
      return `<option value="${esc(x.adset_name)}" label="${esc((campaign.platform === "Google" ? "Google ad group" : "Facebook ad set") + status)}"></option>`;
    }).join("");
  }
  function oaStoredCampaign(r) {
    if (!r.campaign_platform || !r.campaign_id || !r.campaign_name) return null;
    return { platform:r.campaign_platform, campaign_id:r.campaign_id, campaign_name:r.campaign_name };
  }
  function oaJourneySuggestion(r) {
    const j = r.journey && typeof r.journey === "object" ? r.journey : {};
    const norm = (v) => String(v || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
    const all = [];
    const seen = new Set();
    [j.first_visit, ...(Array.isArray(j.moments) ? j.moments : []), j.last_visit].filter(Boolean).forEach((v) => {
      const k = v.id || [v.occurred_at, v.source, v.landing_page, JSON.stringify(v.utm || {})].join("|");
      if (!seen.has(k)) { seen.add(k); all.push(v); }
    });
    all.sort((a,b) => String(a.occurred_at || "").localeCompare(String(b.occurred_at || "")));

    const platformOf = (v) => {
      const u=v?.utm||{};
      const h=[v?.source,v?.source_description,v?.referrer_url,u.source,u.medium,u.campaign,u.content].filter(Boolean).join(" ").toLowerCase();
      if (/facebook|instagram|meta|m\.facebook|l\.instagram/.test(h)) return "Facebook";
      if (/google/.test(h)) return "Google";
      return null;
    };
    const organic = (v) => {
      const u=v?.utm||{};
      const h=[v?.source,v?.source_description,v?.referrer_url,u.source,u.medium,u.campaign,u.content].filter(Boolean).join(" ").toLowerCase();
      const m=String(u.medium||"").toLowerCase();
      if (/sag[_ ]organic|organic/.test(h)) return true;
      if (platformOf(v)==="Google" && ["","organic","product_sync"].includes(m) && !/cpc|ppc|paid|ads|adwords/.test(h)) return true;
      if (platformOf(v)==="Facebook" && (!u.source && !u.medium && !u.campaign && !u.term && !u.content || ["social","organic","referral"].includes(m))) return true;
      return false;
    };
    const paid = (v) => {
      const u=v?.utm||{};
      const p=platformOf(v);
      if (!u || !p || organic(v)) return false;
      const h=[u.source,u.medium,u.campaign,u.term,u.content,v?.source_description].filter(Boolean).join(" ").toLowerCase();
      if (/cpc|ppc|paid|tracked|non tracked|non-tracked|sales|campaign/.test(h)) return true;
      if (p==="Facebook" && (u.campaign||u.term||u.content) && !["social","organic","referral"].includes(String(u.medium||"").toLowerCase())) return true;
      if (p==="Google" && !["","organic","product_sync"].includes(String(u.medium||"").toLowerCase())) return true;
      return false;
    };

    const paidVisits=all.filter(paid);
    const visit=paidVisits.length ? paidVisits[paidVisits.length-1] : all.find(organic) || all[0] || {};
    const utm=visit.utm||{};
    const platform=platformOf(visit);
    const isOrganic=!paidVisits.length && organic(visit);
    let source=isOrganic ? "Organic Orders" : platform==="Facebook" ? "FB Online Orders - WEB" : platform==="Google" ? "Google Online Orders - WEB" : null;
    let campaign=null, adset=null;

    if (!isOrganic && platform) {
      const cats=oaCampaigns().filter((x)=>x.platform===platform);
      const rawCampaign=platform==="Facebook" ? String(utm.medium||utm.campaign||"") : String(utm.campaign||utm.medium||"");
      if (rawCampaign) {
        const exact=cats.filter((x)=>norm(x.campaign_name)===norm(rawCampaign));
        const ids=new Set(exact.map((x)=>x.campaign_id));
        if(ids.size===1 && exact.length) {
          const x=exact[0];
          campaign={platform:x.platform,campaign_id:x.campaign_id,campaign_name:x.campaign_name};
        }
      }
      if (!campaign && rawCampaign) {
        const n=norm(rawCampaign);
        const hits=n.length>=10 ? cats.filter((x)=>{const c=norm(x.campaign_name);return c.length>=10&&(c.startsWith(n)||n.startsWith(c));}) : [];
        const ids=new Set(hits.map((x)=>x.campaign_id));
        if(ids.size===1 && hits.length) {
          const x=hits[0];
          campaign={platform:x.platform,campaign_id:x.campaign_id,campaign_name:x.campaign_name};
        }
      }
      if (!campaign && rawCampaign) campaign={platform,campaign_id:"",campaign_name:rawCampaign,journey_derived:true};

      if (campaign) {
        const sets=campaign.campaign_id ? oaAdsets(campaign) : [];
        if (utm.term) {
          const hit=sets.find((x)=>String(x.adset_id||"")===String(utm.term));
          if(hit) adset=hit;
        }
        const rawAdset=platform==="Facebook" ? String(utm.campaign||"") : "";
        if (!adset && rawAdset) {
          const exact=sets.filter((x)=>norm(x.adset_name)===norm(rawAdset));
          if(exact.length===1) adset=exact[0];
        }
        if(!adset && rawAdset) adset={adset_id:String(utm.term||""),adset_name:rawAdset,journey_derived:true};
      }
    }
    return { source, platform, campaign, adset, utm, visit };
  }
  function oaJourneyPlace(v) {
    if (!v) return "";
    const raw = v.landing_page || v.referrer_url || "";
    if (!raw) return "";
    try {
      const u = new URL(raw);
      return u.pathname && u.pathname !== "/" ? u.pathname : u.hostname;
    } catch (_) { return raw; }
  }
  function oaJourneyHTML(r) {
    if (!r.journey_ready) {
      const checked = r.journey_checked_at ? ` Last checked ${fmtTime(r.journey_checked_at)}.` : "";
      return `<div class="oa-journey waiting"><b>Shopify attribution is still processing.</b><span>We re-check automatically every 15 minutes.${esc(checked)}</span></div>`;
    }
    const j = r.journey && typeof r.journey === "object" ? r.journey : {};
    const first = j.first_visit || null, last = j.last_visit || null;
    const suggest = oaJourneySuggestion(r);
    const firstText = first ? (first.source_description || first.source || "First session available") : "No first-session detail";
    const lastText = last ? (last.source_description || last.source || "Conversion session available") : "No conversion-session detail";
    const firstPlace = oaJourneyPlace(first), lastPlace = oaJourneyPlace(last);
    const utm = suggest.utm || {};
    const utmLine = [utm.source, utm.medium, utm.campaign].filter(Boolean).join(" · ");
    const suggestion = suggest.source && !r.order_source
      ? `<div class="oa-journey-suggest">Suggested source: <b>${esc(suggest.source)}</b>${suggest.campaign ? ` · ${esc(suggest.campaign.campaign_name)}` : ""}</div>`
      : "";
    const note = r.attribution_note
      ? `<div class="oa-journey-note"><b>Note:</b> ${esc(r.attribution_note)}</div>`
      : "";
    return `<div class="oa-journey">
      <div><b>First session:</b> ${esc(firstText)}${firstPlace ? " · " + esc(firstPlace) : ""}</div>
      <div><b>Converted after:</b> ${esc(lastText)}${lastPlace ? " · " + esc(lastPlace) : ""}</div>
      ${utmLine ? `<div class="oa-journey-utm"><b>UTM:</b> ${esc(utmLine)}</div>` : ""}
      ${suggestion}
      ${note}
    </div>`;
  }

  function oaRow(r) {
    const syncing = r.sync_status === "syncing", failed = r.sync_status === "error";
    const suggest = oaJourneySuggestion(r);
    const selectedSource = r.order_source || suggest.source || "";
    const opts = ['<option value="">Choose source…</option>'].concat(ORDER_SOURCES.map((x) => `<option value="${esc(x)}" ${selectedSource === x ? "selected" : ""}>${esc(x)}</option>`)).join("");
    const stat = syncing ? '<span class="oa-state syncing">Syncing…</span>' : failed ? '<span class="oa-state error">Sync failed</span>' : r.attribution_auto === true ? '<span class="oa-state pending">Auto-detected · confirm</span>' : r.order_source ? '<span class="oa-state done">Confirmed</span>' : '<span class="oa-state pending">Pending</span>';
    const saveText = syncing ? "Saving…" : failed ? "Retry Shopify" : r.attribution_auto === true ? "Confirm attribution" : "Save attribution";
    const campaign = oaStoredCampaign(r) || suggest.campaign;
    const campaignValue = campaign ? `${campaign.platform} — ${campaign.campaign_name}` : "";
    const cid = `oa-campaign-${r.legacy_id}`, aid = `oa-adset-${r.legacy_id}`;
    const adHint = campaign?.platform === "Google" ? "Search Google ad group…" : campaign?.platform === "Facebook" ? "Search Facebook ad set…" : "Choose campaign first…";
    const suggestedAdset = r.adset_name || suggest.adset?.adset_name || "";
    return `<div class="oa-row ${failed ? "has-error" : ""}" data-order="${esc(r.order_id)}">
      <div class="oa-top">
        <a class="oa-order" href="https://admin.shopify.com/store/bvdxj3-r8/orders/${esc(r.legacy_id)}" target="_blank" rel="noopener">${esc(r.order_name)}</a>
        <b class="oa-total">${oaMoney(r.total, r.currency)}</b>
        ${stat}
      </div>
      <div class="oa-meta">${esc((r.shopify_source || "Shopify").toUpperCase())} · ${fmtTime(r.created_at)}${r.customer_name ? " · " + esc(r.customer_name) : ""}</div>
      <div class="oa-products">${oaProducts(r)}</div>
      ${oaJourneyHTML(r)}
      <div class="oa-fields">
        <label class="oa-field"><span>Phone <em>customer order</em></span><input class="oa-phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="04xx xxx xxx" value="${esc(r.contact_phone || "")}" ${syncing ? "disabled" : ""}></label>
        <label class="oa-field"><span>Email <em>customer order</em></span><input class="oa-email" type="email" inputmode="email" autocomplete="email" placeholder="customer@example.com" value="${esc(r.contact_email || "")}" ${syncing ? "disabled" : ""}></label>
      </div>
      <div class="oa-fields oa-ad-fields">
        <label class="oa-field"><span>Campaign <em>search Facebook + Google</em></span>
          <input class="oa-campaign" type="search" list="${cid}" autocomplete="off" placeholder="Search campaign…" value="${esc(campaignValue)}" ${syncing ? "disabled" : ""}>
          <datalist id="${cid}" class="oa-campaign-list">${oaCampaignOptions()}</datalist>
        </label>
        <label class="oa-field"><span>Ad set / ad group <em>optional</em></span>
          <input class="oa-adset" type="search" list="${aid}" autocomplete="off" placeholder="${esc(adHint)}" value="${esc(suggestedAdset)}" ${syncing ? "disabled" : ""}>
          <datalist id="${aid}" class="oa-adset-list">${oaAdsetOptions(campaign)}</datalist>
        </label>
      </div>
      <div class="oa-actions">
        <select class="oa-source" aria-label="Order source for ${esc(r.order_name)}" ${syncing ? "disabled" : ""}>${opts}</select>
        <button class="btn sm oa-resync" type="button" data-order="${esc(r.order_id)}" ${syncing ? "disabled" : ""}>Re-sync details</button>
        <button class="btn oa-save" type="button" data-order="${esc(r.order_id)}" ${syncing ? "disabled" : ""}>${saveText}</button>
      </div>
      ${failed ? `<div class="oa-error">${esc(r.sync_error || "Shopify did not accept the update. Check the details and retry.")}</div>` : ""}
    </div>`;
  }
  function oaRefreshAdsetList(card) {
    const campaignInput = card.querySelector(".oa-campaign");
    const adsetInput = card.querySelector(".oa-adset");
    const list = card.querySelector(".oa-adset-list");
    const campaign = oaFindCampaign(campaignInput.value);
    list.innerHTML = oaAdsetOptions(campaign);
    adsetInput.placeholder = campaign ? (campaign.platform === "Google" ? "Search Google ad group…" : "Search Facebook ad set…") : "Choose campaign first…";
    if (!campaign || (adsetInput.value && !oaFindAdset(campaign, adsetInput.value))) adsetInput.value = "";
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
    $$(".oa-campaign").forEach((input) => {
      input.addEventListener("change", () => oaRefreshAdsetList(input.closest(".oa-row")));
      input.addEventListener("input", () => {
        if (oaFindCampaign(input.value)) oaRefreshAdsetList(input.closest(".oa-row"));
      });
    });
    $$(".oa-resync").forEach((btn) => btn.addEventListener("click", () => refreshAttributionJourney(btn.dataset.order, btn)));
    $$(".oa-save").forEach((btn) => btn.addEventListener("click", () => {
      const card = btn.closest(".oa-row");
      const source = card.querySelector(".oa-source").value;
      const emailEl = card.querySelector(".oa-email");
      const email = emailEl.value.trim();
      const phone = card.querySelector(".oa-phone").value.trim();
      const campaignEl = card.querySelector(".oa-campaign");
      const adsetEl = card.querySelector(".oa-adset");
      const campaignText = campaignEl.value.trim();
      const row = OA.rows.find((x) => x.order_id === btn.dataset.order);
      const suggested = row ? oaJourneySuggestion(row) : {};
      if (!source) return toast("Choose an order source first");
      if (email && !emailEl.checkValidity()) return toast("Enter a valid email address or leave it blank");
      const expectedPlatform = oaPaidPlatform(source);
      let campaign = null, adset = null;
      if (expectedPlatform) {
        campaign = campaignText ? oaFindCampaign(campaignText) : null;
        if (!campaign && suggested.campaign && suggested.campaign.platform === expectedPlatform && campaignText === oaCampaignValue(suggested.campaign)) campaign = suggested.campaign;
        if (campaignText && !campaign) return toast("Choose the campaign from the list or use the Shopify-suggested campaign");
        if (campaign && campaign.platform !== expectedPlatform) return toast(`Choose a ${expectedPlatform} campaign for this source`);
        const adsetText = adsetEl.value.trim();
        adset = adsetText && campaign ? oaFindAdset(campaign, adsetText) : null;
        if (!adset && suggested.adset && adsetText === suggested.adset.adset_name) adset = suggested.adset;
        if (adsetText && !campaign) return toast("Choose the campaign before the ad set/ad group");
        if (adsetText && !adset) return toast(campaign?.platform === "Google" ? "Choose the Google ad group from the list or use the Shopify-suggested value" : "Choose the Facebook ad set from the list or use the Shopify-suggested value");
      }
      syncAttribution(btn.dataset.order, source, email, phone, campaign, adset);
    }));
  }
  async function refreshAttributionJourney(orderId, btn) {
    if (!orderId || !btn) return;
    busy(btn, true, "Checking…");
    try {
      const { data, error } = await sb.functions.invoke("order-attribution", { body: { action:"refresh", order_id:orderId } });
      if (error) {
        let msg = error.message; try { const j = await error.context.json(); msg = j.error || msg; } catch (_) {}
        throw new Error(msg);
      }
      if (data?.error) throw new Error(data.error);
      toast("Shopify session details are being re-checked");
      const reload = async () => {
        try { await loadAttribution(); if (!$("#v-attribution").hidden) renderAttribution(); } catch (_) {}
      };
      setTimeout(reload, 9000);
      setTimeout(reload, 25000);
      setTimeout(reload, 55000);
    } catch (e) {
      toast(e?.message || "Could not start the Shopify detail refresh");
      busy(btn, false);
    }
  }

  async function syncAttribution(orderId, source, email = "", phone = "", campaign = null, adset = null) {
    const row = OA.rows.find((r) => r.order_id === orderId);
    if (!row || !source) return;
    row.order_source = source;
    if (email) row.contact_email = email;
    if (phone) row.contact_phone = phone;
    row.campaign_platform = campaign?.platform || null;
    row.campaign_id = campaign?.campaign_id || null;
    row.campaign_name = campaign?.campaign_name || null;
    row.adset_id = adset?.adset_id || null;
    row.adset_name = adset?.adset_name || null;
    row.sync_status = "syncing"; row.sync_error = null; renderAttribution();
    try {
      const { data, error } = await sb.functions.invoke("order-attribution", { body: {
        action: "update",
        order_id: orderId,
        source,
        email,
        phone,
        campaign_platform: campaign?.platform || "",
        campaign_id: campaign?.campaign_id || "",
        campaign_name: campaign?.campaign_name || "",
        adset_id: adset?.adset_id || "",
        adset_name: adset?.adset_name || "",
        journey_derived: Boolean(campaign?.journey_derived || adset?.journey_derived),
      } });
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
    try {
      await loadAttribution();
      renderAttribution();
      if (!OA.catalog.length) toast("Campaign list is refreshing; source attribution still works.");
    } catch (e) { st.textContent = "The order queue couldn't be loaded. Pull down to refresh."; }
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
    await enablePhonePush();
    updateOrderNotifyButton();
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

  // ---------- unified SEO rankings ----------
  let SEO_CACHE = null;
  const seoEsc = esc;
  const seoNum = (v) => v == null ? "—" : Number(v).toLocaleString("en-AU");
  const seoPos = (v) => v == null || !Number.isFinite(Number(v)) ? "—" : Number(v).toFixed(1);
  const seoDate = (v) => v ? new Date(v + "T00:00:00").toLocaleDateString("en-AU", { day:"numeric", month:"short", year:"numeric" }) : "—";
  const seoNorm = (v) => String(v || "").toLowerCase().replace(/[^a-z0-9]+/g, "");

  async function loadSeoRankingsData(force) {
    if (SEO_CACHE && !force) return SEO_CACHE;
    const a = await Promise.all([
      sb.from("seo_rank_categories").select("*").order("sort"),
      sb.from("seo_rank_products").select("*").order("title"),
      sb.from("seo_rank_snapshots").select("*").order("snapshot_date")
    ]);
    const e = a[0].error || a[1].error || a[2].error;
    if (e) throw new Error(e.message);
    SEO_CACHE = { categories:a[0].data||[], products:a[1].data||[], snapshots:a[2].data||[] };
    return SEO_CACHE;
  }

  function seoProductHistory(d, p) {
    return (d.snapshots || []).filter(function(s) {
      return s.category_id === p.category_id && s.handle === p.handle;
    }).slice().sort(function(x, y) { return String(x.snapshot_date).localeCompare(String(y.snapshot_date)); });
  }
  function seoBaselineSnapshot(d, p, cat) {
    const h = seoProductHistory(d, p);
    if (!h.length) return null;
    return h.find(function(x) { return x.snapshot_date === cat.baseline_date; }) ||
      h.find(function(x) { return String(x.snapshot_date) >= String(cat.baseline_date || ""); }) || h[0];
  }
  function seoLatestSnapshot(d, p) {
    const h = seoProductHistory(d, p);
    return h.length ? h[h.length - 1] : null;
  }
  function seoKeywordRank(snapshot, keyword) {
    if (!snapshot || !keyword) return null;
    const k = seoNorm(keyword);
    const qs = Array.isArray(snapshot.top_queries) ? snapshot.top_queries : [];
    const same = qs.filter(function(q) { return seoNorm(q.q) === k && Number(q.impressions || 0) > 0 && q.position != null; });
    if (same.length) {
      const den = same.reduce(function(a, q) { return a + Number(q.impressions || 0); }, 0);
      if (den > 0) return same.reduce(function(a, q) { return a + Number(q.position || 0) * Number(q.impressions || 0); }, 0) / den;
    }
    if (seoNorm(snapshot.top_query) === k && snapshot.top_query_position != null) return Number(snapshot.top_query_position);
    return null;
  }
  function seoDays(a, b) {
    if (!a || !b) return null;
    return Math.floor((new Date(b + "T00:00:00") - new Date(a + "T00:00:00")) / 86400000);
  }
  function seoPhase(cat) {
    const n = seoDays(cat.baseline_date, cat.gsc_settled_through);
    if (n == null) return { code:"unknown", label:"Tracking", note:"Waiting for settled GSC dates." };
    if (n < 0) return { code:"waiting", label:"Too early to judge", note:"GSC is settled only through " + seoDate(cat.gsc_settled_through) + ", before the SEO baseline of " + seoDate(cat.baseline_date) + "." };
    if (n < 7) return { code:"early", label:"Early signal", note:"Only " + (n + 1) + " day" + (n ? "s" : "") + " of post-SEO GSC data are settled." };
    if (n < 28) return { code:"forming", label:"Trend forming", note:(n + 1) + " days of post-SEO GSC data are settled; the 28-day window is still mixing old and new SEO." };
    return { code:"mature", label:"Comparable", note:"A full post-SEO 28-day window is available." };
  }
  function seoDelta(v, b) {
    if (v == null || b == null) return null;
    return Number(v) - Number(b);
  }
  function seoSigned(v, digits) {
    if (v == null || !Number.isFinite(Number(v))) return "—";
    const n = Number(v), d = digits == null ? 0 : digits;
    return (n > 0 ? "+" : "") + n.toFixed(d);
  }
  function seoRankDelta(base, current) {
    if (base == null || current == null) return null;
    return Number(base) - Number(current);
  }
  function seoStatus(p, cat, base, current, baseRank, currentRank) {
    const phase = seoPhase(cat);
    if (!p.published) return { code:"off", label:"Not live", reason:"This product is not currently live, so SEO movement is not actionable." };
    if (p.current_indexed === false) return { code:"bad", label:"Not indexed", reason:"Google reports this live URL as not indexed. Ranking improvement cannot happen until indexing is fixed." };
    if (!current) return { code:"nodata", label:"No GSC data", reason:"No Search Console snapshot has been recorded for this product yet." };

    const bi = base ? Number(base.impressions || 0) : null;
    const ci = Number(current.impressions || 0);
    const bc = base ? Number(base.clicks || 0) : null;
    const cc = Number(current.clicks || 0);
    const rd = seoRankDelta(baseRank, currentRank);

    if (phase.code === "waiting") {
      return { code:"wait", label:"Awaiting post-SEO data", reason:phase.note };
    }
    if (baseRank == null && currentRank != null) {
      return { code:"new", label:"New keyword visibility", reason:"The selected keyword now appears around #" + seoPos(currentRank) + ", but there is no same-keyword baseline to calculate a rank gain yet." };
    }
    if (baseRank == null && currentRank == null) {
      if ((bi || 0) === 0 && ci > 0) return { code:"new", label:"Visibility started", reason:"The product went from no recorded impressions to " + seoNum(ci) + " impressions, but the selected keyword has no comparable rank yet." };
      return { code:"nodata", label:"No comparable keyword rank", reason:"The selected target keyword was not measured in both the baseline and latest snapshot." };
    }
    if (rd != null && rd >= 2) {
      return { code:"good", label:"SEO improving", reason:"Target keyword improved " + seoPos(rd) + " ranks (#" + seoPos(baseRank) + " → #" + seoPos(currentRank) + "); impressions " + seoSigned(seoDelta(ci, bi), 0) + ", clicks " + seoSigned(seoDelta(cc, bc), 0) + "." };
    }
    if (rd != null && rd <= -2) {
      return { code:"bad", label:"Ranking down", reason:"Target keyword dropped " + seoPos(Math.abs(rd)) + " ranks (#" + seoPos(baseRank) + " → #" + seoPos(currentRank) + "); impressions " + seoSigned(seoDelta(ci, bi), 0) + ", clicks " + seoSigned(seoDelta(cc, bc), 0) + "." };
    }
    if (ci > (bi || 0) || cc > (bc || 0)) {
      return { code:"good", label:"Visibility improving", reason:"Rank is broadly stable, while impressions/clicks increased (" + seoNum(bi || 0) + " → " + seoNum(ci) + " impressions; " + seoNum(bc || 0) + " → " + seoNum(cc) + " clicks)." };
    }
    if (ci < (bi || 0) || cc < (bc || 0)) {
      return { code:"warn", label:"Visibility softer", reason:"Rank is broadly stable, but search visibility is lower than the baseline window." };
    }
    return { code:"flat", label:"No clear change", reason:"The selected keyword rank and search visibility are essentially unchanged so far." };
  }

  function seoCategorySummary(d, cat) {
    const ps = (d.products || []).filter(function(p) { return p.category_id === cat.id; });
    const live = ps.filter(function(p) { return p.published; });
    let baseImp=0, currImp=0, baseClicks=0, currClicks=0, comparableRanks=[], currentRanks=[];
    live.forEach(function(p) {
      const b=seoBaselineSnapshot(d,p,cat), c=seoLatestSnapshot(d,p);
      if (b) { baseImp += Number(b.impressions||0); baseClicks += Number(b.clicks||0); }
      if (c) { currImp += Number(c.impressions||0); currClicks += Number(c.clicks||0); }
      const br=seoKeywordRank(b,p.target_keyword), cr=seoKeywordRank(c,p.target_keyword);
      if (cr != null) currentRanks.push(cr);
      if (br != null && cr != null) comparableRanks.push([br,cr]);
    });
    const median=function(arr){
      if(!arr.length) return null;
      const x=arr.slice().sort(function(a,b){return a-b;});
      const m=Math.floor(x.length/2);
      return x.length%2?x[m]:(x[m-1]+x[m])/2;
    };
    const baseMedian=median(comparableRanks.map(function(x){return x[0];}));
    const currMedianComparable=median(comparableRanks.map(function(x){return x[1];}));
    const currMedian=median(currentRanks);
    return {
      products:ps.length, live:live.length,
      baseImp:baseImp, currImp:currImp, baseClicks:baseClicks, currClicks:currClicks,
      baseMedian:baseMedian, currMedianComparable:currMedianComparable, currMedian:currMedian,
      comparableRankProducts:comparableRanks.length,
      indexed:live.filter(function(p){return p.current_indexed===true;}).length,
      notIndexed:live.filter(function(p){return p.current_indexed===false;}).length,
      notChecked:live.filter(function(p){return p.current_indexed==null;}).length
    };
  }

  function seoMeta(d) {
    const cats=d.categories||[];
    const stats=[];
    cats.forEach(function(cat) {
      const s=seoCategorySummary(d,cat);
      stats.push([seoNum(s.currImp), cat.title + " impressions"]);
      stats.push([seoNum(s.currClicks), cat.title + " clicks"]);
    });
    const phases=cats.map(seoPhase);
    const waiting=phases.some(function(x){return x.code==="waiting";});
    const notIndexed=(d.products||[]).filter(function(p){return p.published && p.current_indexed===false;}).length;
    const latest=(cats.map(function(c){return c.refreshed_at;}).filter(Boolean).sort().slice(-1)[0]);
    const through=cats.map(function(c){return c.gsc_settled_through;}).filter(Boolean).sort().slice(-1)[0];
    return {
      updated: latest ? fmtTime(latest) : "",
      stats: stats.slice(0,4),
      warn: notIndexed ? notIndexed + " live page" + (notIndexed===1?" is":"s are") + " not indexed" : "",
      signal: waiting ? { code:"hold", label:"TOO EARLY TO JUDGE", reason:"GSC is settled through " + seoDate(through) + "; the SEO baselines are newer." }
        : { code:"hold", label:"SEO IMPACT TRACKING", reason:"Compare each category and product against its saved SEO baseline." }
    };
  }

  function seoHistoryHTML(d, p, cat) {
    const h=seoProductHistory(d,p).slice(-12);
    if(!h.length) return '<div class="nohist">No historical snapshots yet.</div>';
    let rows="";
    h.forEach(function(x){
      const r=seoKeywordRank(x,p.target_keyword);
      rows += '<tr><td>' + seoDate(x.snapshot_date) + '</td><td>' + seoNum(x.impressions) + '</td><td>' + seoNum(x.clicks) + '</td><td>' + (r==null?'—':'#'+seoPos(r)) + '</td><td>' + (x.top_query?seoEsc(x.top_query) + (x.top_query_position!=null?' <span class="rank">#'+seoPos(x.top_query_position)+'</span>':''):'—') + '</td></tr>';
    });
    return '<div class="history"><div class="histnote">Each row is a trailing 28-day GSC snapshot. Selected keyword: <b>' + seoEsc(p.target_keyword||"—") + '</b>.</div><table><thead><tr><th>Snapshot</th><th>Impressions</th><th>Clicks</th><th>Selected keyword rank</th><th>Top query</th></tr></thead><tbody>' + rows + '</tbody></table></div>';
  }

  function seoProductRow(d, p, cat, uid) {
    const b=seoBaselineSnapshot(d,p,cat), c=seoLatestSnapshot(d,p);
    const br=seoKeywordRank(b,p.target_keyword), cr=seoKeywordRank(c,p.target_keyword);
    const rd=seoRankDelta(br,cr);
    const status=seoStatus(p,cat,b,c,br,cr);
    const img=p.image_url ? '<img src="' + seoEsc(p.image_url + (p.image_url.indexOf("?")>=0?"&":"?") + "width=120") + '" alt="" loading="lazy">' : '<span class="ph">No image</span>';
    const live=p.published ? '<span class="badge live">Live</span>' : '<span class="badge off">' + seoEsc(p.shopify_status||"Not live") + '</span>';
    const idx=p.current_indexed===true ? '<span class="badge indexed">Indexed</span>' :
      (p.current_indexed===false ? '<span class="badge notindexed">Not indexed</span>' : '<span class="badge unchecked" title="Google index status has not been checked for this URL yet">Not checked</span>');
    const beforeRank=br==null?'—':'#'+seoPos(br);
    const currentRank=cr==null?'—':'#'+seoPos(cr);
    let move='—', moveClass='neutral';
    if(rd!=null){ move=(rd>0?'▲ +':rd<0?'▼ ':'• ')+seoPos(Math.abs(rd))+' ranks'; moveClass=rd>=2?'good':rd<=-2?'bad':'neutral'; }
    const bi=b?Number(b.impressions||0):0, ci=c?Number(c.impressions||0):0, bc=b?Number(b.clicks||0):0, cc=c?Number(c.clicks||0):0;
    const top=c&&c.top_query ? seoEsc(c.top_query) + (c.top_query_position!=null?' <span class="rank">#'+seoPos(c.top_query_position)+'</span>':'') : '—';
    return '<tr class="product-row">' +
      '<td class="prodcell"><div class="prodwrap"><span class="thumb">'+img+'</span><span><a href="'+seoEsc(p.url)+'" target="_blank" rel="noopener">'+seoEsc(p.title)+'</a><small>Top query: '+top+'</small></span></div></td>' +
      '<td>'+live+'</td>' +
      '<td>'+idx+'</td>' +
      '<td class="keyword"><b>'+seoEsc(p.target_keyword||"—")+'</b><small>Chosen SEO keyword</small></td>' +
      '<td class="metric"><b>'+beforeRank+'</b><small>'+seoDate(b&&b.snapshot_date)+'</small><span>'+seoNum(bi)+' imp · '+seoNum(bc)+' clk</span></td>' +
      '<td class="metric"><b>'+currentRank+'</b><small>'+seoDate(c&&c.snapshot_date)+'</small><span>'+seoNum(ci)+' imp · '+seoNum(cc)+' clk</span></td>' +
      '<td><span class="move '+moveClass+'">'+move+'</span><small>'+seoSigned(ci-bi,0)+' imp · '+seoSigned(cc-bc,0)+' clk</small></td>' +
      '<td class="verdict"><span class="badge v-'+status.code+'">'+seoEsc(status.label)+'</span><small>'+seoEsc(status.reason)+'</small></td>' +
      '<td><button class="histbtn" type="button" data-target="'+seoEsc(uid)+'">History</button></td>' +
      '</tr>' +
      '<tr class="history-row" id="'+seoEsc(uid)+'" hidden><td colspan="9">'+seoHistoryHTML(d,p,cat)+'</td></tr>';
  }

  function seoCategoryHTML(d, cat, index) {
    const s=seoCategorySummary(d,cat), phase=seoPhase(cat);
    const ps=(d.products||[]).filter(function(p){return p.category_id===cat.id;}).slice().sort(function(a,b){
      const ca=seoLatestSnapshot(d,a), cb=seoLatestSnapshot(d,b);
      return Number(cb&&cb.impressions||0)-Number(ca&&ca.impressions||0) || String(a.title).localeCompare(String(b.title));
    });
    const impDelta=s.currImp-s.baseImp, clickDelta=s.currClicks-s.baseClicks;
    const rankDelta=seoRankDelta(s.baseMedian,s.currMedianComparable);
    const rankText=s.comparableRankProducts ? ('#'+seoPos(s.currMedianComparable)) : (s.currMedian!=null?'#'+seoPos(s.currMedian):'—');
    const rankSub=s.comparableRankProducts ? ('vs #'+seoPos(s.baseMedian)+' · '+(rankDelta==null?'—':seoSigned(rankDelta,1)+' ranks')) : 'No same-keyword baseline yet';
    let rows="";
    ps.forEach(function(p,i){ rows+=seoProductRow(d,p,cat,'seo-h-'+index+'-'+i); });
    return '<details class="catbox cat-'+seoEsc(cat.id)+'" open>' +
      '<summary><div><span class="catdot"></span><b>'+seoEsc(cat.title)+'</b><small>'+s.live+' live / '+s.products+' tracked · SEO baseline '+seoDate(cat.baseline_date)+'</small></div><span class="phase '+seoEsc(phase.code)+'">'+seoEsc(phase.label)+'</span></summary>' +
      '<div class="catbody">' +
        '<div class="phase-note">'+seoEsc(phase.note)+'</div>' +
        '<div class="catstats">' +
          '<div class="stat"><span>Impressions · 28d</span><b>'+seoNum(s.currImp)+'</b><small>Before '+seoNum(s.baseImp)+' · <strong class="'+(impDelta>0?'pos':impDelta<0?'neg':'flat')+'">'+seoSigned(impDelta,0)+'</strong></small></div>' +
          '<div class="stat"><span>Clicks · 28d</span><b>'+seoNum(s.currClicks)+'</b><small>Before '+seoNum(s.baseClicks)+' · <strong class="'+(clickDelta>0?'pos':clickDelta<0?'neg':'flat')+'">'+seoSigned(clickDelta,0)+'</strong></small></div>' +
          '<div class="stat"><span>Selected keyword rank</span><b>'+rankText+'</b><small>'+rankSub+'</small></div>' +
          '<div class="stat"><span>Google index status</span><b>'+s.indexed+' indexed</b><small>'+s.notIndexed+' not indexed · '+s.notChecked+' not checked</small></div>' +
        '</div>' +
        '<div class="legend"><span><i class="lg good"></i>Improving</span><span><i class="lg bad"></i>Declining / not indexed</span><span><i class="lg wait"></i>Too early / needs data</span><span><i class="lg flat"></i>Stable</span></div>' +
        '<div class="tablewrap"><table class="prodtable"><thead><tr><th>Product</th><th>Live</th><th>Google index</th><th>Selected keyword</th><th>Before SEO</th><th>Latest</th><th>Change</th><th>SEO verdict</th><th></th></tr></thead><tbody>'+rows+'</tbody></table></div>' +
      '</div></details>';
  }

  function seoReportHTML(d) {
    const cats=d.categories||[];
    const through=cats.map(function(c){return c.gsc_settled_through;}).filter(Boolean).sort().slice(-1)[0];
    let sections="";
    cats.forEach(function(cat,i){ sections+=seoCategoryHTML(d,cat,i); });
    const css=':root{color-scheme:dark;--bg:#090d12;--panel:#111821;--panel2:#161f2a;--line:#293645;--text:#f6f7f9;--muted:#97a3af;--green:#52d68a;--red:#ff727c;--amber:#f2c35b;--purple:#b794f6;--rose:#f090b8;--soft:#1d2834}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top left,#181323 0,#090d12 38%);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif;padding:16px}.wrap{max-width:1500px;margin:auto}h1{font-size:26px;margin:0 0 4px}.intro{color:var(--muted);font-size:12px;line-height:1.5;margin-bottom:14px}.explain{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0 14px}.explain div{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:10px}.explain b{display:block;font-size:11px;margin-bottom:3px}.explain span{font-size:10px;color:var(--muted);line-height:1.4}.catbox{background:var(--panel);border:1px solid var(--line);border-radius:16px;margin:12px 0;overflow:hidden}.catbox summary{list-style:none;cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:10px;padding:14px 16px;background:linear-gradient(90deg,#171e28,#111821)}.catbox summary::-webkit-details-marker{display:none}.catbox summary>div{display:flex;align-items:center;gap:9px;flex-wrap:wrap}.catbox summary b{font-size:17px}.catbox summary small{color:var(--muted);font-size:10px}.catdot{width:10px;height:10px;border-radius:50%;display:inline-block;background:var(--purple);box-shadow:0 0 14px rgba(183,148,246,.55)}.cat-bangles .catdot{background:var(--rose);box-shadow:0 0 14px rgba(240,144,184,.5)}.phase{font-size:9px;text-transform:uppercase;letter-spacing:.08em;font-weight:800;border-radius:999px;padding:6px 8px;background:#2b2533;color:#d7b8ff}.phase.waiting,.phase.early{background:#362d18;color:#ffd978}.phase.forming{background:#28243a;color:#cbb7ff}.phase.mature{background:#163126;color:#7ce5aa}.catbody{padding:12px}.phase-note{font-size:11px;color:#ddc87f;background:#2b2517;border:1px solid #4b3d19;border-radius:10px;padding:9px 10px;margin-bottom:10px}.catstats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.stat{background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:10px}.stat>span{display:block;font-size:9px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}.stat>b{display:block;font-size:19px;margin:4px 0}.stat small{font-size:9px;color:var(--muted)}.pos{color:var(--green)}.neg{color:var(--red)}.flat{color:var(--muted)}.legend{display:flex;gap:12px;flex-wrap:wrap;margin:11px 1px 8px;color:var(--muted);font-size:9px}.legend span{display:flex;align-items:center;gap:4px}.lg{width:7px;height:7px;border-radius:50%;display:inline-block}.lg.good{background:var(--green)}.lg.bad{background:var(--red)}.lg.wait{background:var(--amber)}.lg.flat{background:#82909d}.tablewrap{overflow:auto;border:1px solid var(--line);border-radius:12px}.prodtable{border-collapse:collapse;width:100%;min-width:1250px;background:#0d141c}.prodtable th{position:sticky;top:0;background:#18212b;color:#aebac5;font-size:9px;text-transform:uppercase;letter-spacing:.05em;text-align:left;padding:9px;border-bottom:1px solid var(--line);z-index:2}.prodtable td{padding:9px;border-top:1px solid #1e2a36;vertical-align:top;font-size:10px}.product-row:hover{background:#111c27}.prodwrap{display:flex;gap:8px;min-width:235px}.thumb{width:48px;height:58px;border-radius:8px;overflow:hidden;background:#1b2530;flex:0 0 auto;display:flex;align-items:center;justify-content:center}.thumb img{width:100%;height:100%;object-fit:cover}.ph{font-size:8px;color:var(--muted)}.prodwrap a{color:#fff;text-decoration:none;font-weight:750;font-size:11px;line-height:1.25}.prodwrap small,.keyword small,.metric small,.metric span,.verdict small,td>small{display:block;color:var(--muted);font-size:8px;line-height:1.35;margin-top:3px}.rank{color:#ddd;font-weight:800}.badge{display:inline-block;border-radius:999px;padding:4px 6px;font-size:8px;font-weight:800;white-space:nowrap}.badge.live{background:#183226;color:#77e4aa}.badge.off{background:#252d35;color:#a9b2bb}.badge.indexed{background:#1b3027;color:#75dfa8}.badge.notindexed,.badge.v-bad{background:#3a1e24;color:#ff9097}.badge.unchecked{background:#2d2b24;color:#d8c991}.badge.v-good,.badge.v-new{background:#163426;color:#76e4a8}.badge.v-wait,.badge.v-warn{background:#3a3018;color:#f3d276}.badge.v-flat,.badge.v-nodata,.badge.v-off{background:#252f39;color:#b9c2ca}.keyword{min-width:150px}.metric{min-width:105px}.metric b{font-size:14px}.move{display:inline-block;font-weight:850;font-size:10px}.move.good{color:var(--green)}.move.bad{color:var(--red)}.move.neutral{color:#c5ced7}.verdict{min-width:240px}.histbtn{border:1px solid #544568;background:#211a2c;color:#d9c4ff;border-radius:8px;padding:6px 8px;font-size:9px;font-weight:750}.history-row td{background:#0a1017;padding:0!important}.history{padding:10px 12px 12px}.histnote{font-size:9px;color:var(--muted);margin-bottom:7px}.history table{border-collapse:collapse;width:100%;min-width:700px}.history th,.history td{position:static!important;background:transparent!important;padding:6px!important;font-size:9px!important;border-top:1px solid #1c2834!important}.nohist{padding:10px;color:var(--muted);font-size:9px}.foot{color:var(--muted);font-size:9px;line-height:1.5;margin:14px 2px}.foot b{color:#cbd3da}@media(max-width:760px){body{padding:10px}.explain{grid-template-columns:1fr}.catstats{grid-template-columns:1fr 1fr}.catbox summary{align-items:flex-start}.catbox summary>div{display:grid;grid-template-columns:auto 1fr}.catbox summary small{grid-column:2}.phase{flex:0 0 auto}.prodtable{min-width:1180px}}';
    const js='document.querySelectorAll(".histbtn").forEach(function(b){b.addEventListener("click",function(){var r=document.getElementById(b.dataset.target);if(!r)return;r.hidden=!r.hidden;b.textContent=r.hidden?"History":"Hide";});});';
    return '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+css+'</style></head><body><div class="wrap">' +
      '<h1>SEO Rankings</h1>' +
      '<div class="intro">Purpose: measure whether the SEO work is improving Google visibility and ranking for each product. GSC data is settled through <b>'+seoDate(through)+'</b>. We compare each category against its own saved SEO baseline.</div>' +
      '<div class="explain"><div><b>Selected keyword rank</b><span>The 28-day average Google position for the exact keyword chosen for that product. Lower is better: #3 is better than #10.</span></div><div><b>Before SEO vs Latest</b><span>Uses saved dated GSC snapshots, not the old baseline fields. Rank movement is only shown when the same selected keyword exists in both snapshots.</span></div><div><b>Index status</b><span>Indexed = Google has confirmed the URL. Not indexed = action needed. Not checked = we do not yet have a Google index check for that URL.</span></div></div>' +
      sections +
      '<div class="foot"><b>Reading the report:</b> Impressions and clicks are trailing 28-day GSC values. Rank is the selected target keyword position, not the vague average across every query. “Too early to judge” means GSC has not yet settled data after the SEO baseline, so the report will not pretend a movement was caused by the new SEO.</div>' +
      '</div><script>'+js+'<\/script></body></html>';
  }

  async function openSeoRankings(r) {
    page("report", r.title);
    const st=$("#rep-status"), fr=$("#rep-frame");
    st.hidden=false; st.textContent="Loading SEO rankings…"; fr.hidden=true;
    try { fr.srcdoc=seoReportHTML(await loadSeoRankingsData(true)); fr.hidden=false; st.hidden=true; }
    catch(e){ st.textContent="The SEO Rankings report couldn't be loaded. Pull down to refresh."; }
  }



  // ---------- tech availability ----------
  async function loadTechAvailability() {
    const { data, error } = await sb.from("tech_availability")
      .select("id,name,usage_pct,usage_label,status,impact,detail,checked_at,source,status_url,auto_detected,sort")
      .order("sort");
    if (error) throw new Error(error.message);
    return data || [];
  }
  async function loadVoiceCostSummary() {
    const { data, error } = await sb.rpc("voice_cost_summary");
    if (error) return null;
    return Array.isArray(data) ? (data[0] || null) : data;
  }
  function techMeta(rows) {
    const healthy = rows.filter((x) => x.status === "operational").length;
    const issues = rows.filter((x) => x.status === "degraded" || x.status === "outage").length;
    const impacting = rows.filter((x) => x.impact).length;
    const pending = (x) => x.source === "pending-setup";
    const unknown = rows.filter((x) => x.status === "unknown" && !pending(x)).length;
    const latest = rows.map((x) => x.checked_at).filter(Boolean).sort().at(-1);
    const stale = !latest || (Date.now() - new Date(latest).getTime()) > 25 * 60 * 1000;
    const bad = impacting > 0 || unknown > 0 || stale;
    const first = rows.find((x) => x.impact);
    const reason = impacting ? `${first?.name || "A service"} is currently affecting IndiFeels.`
      : stale ? "The infrastructure monitor has not checked in within 25 minutes."
      : unknown ? `${unknown} service${unknown === 1 ? "" : "s"} could not be verified.`
      : "No monitored infrastructure outage is affecting IndiFeels.";
    return {
      stats: [[`${healthy}/${rows.length}`, "systems operational"], [String(issues), "current issues"], [String(impacting), "impacting IndiFeels"]],
      updated: latest ? fmtTime(latest) : "not checked yet",
      warn: stale ? "Monitoring heartbeat overdue" : unknown ? `${unknown} service${unknown === 1 ? "" : "s"} could not be verified` : "",
      signal: { label: bad ? "Attention" : "All clear", reason },
      health: bad ? "bad" : "good",
      health_text: impacting ? `${impacting} service${impacting === 1 ? "" : "s"} currently impacting reports or operations.` : reason
    };
  }
  function techReportHTML(rows, voiceCost) {
    const healthy = rows.filter((x) => x.status === "operational").length;
    const issues = rows.filter((x) => x.status === "degraded" || x.status === "outage").length;
    const impacting = rows.filter((x) => x.impact).length;
    const pending = (x) => x.source === "pending-setup";
    const unknown = rows.filter((x) => x.status === "unknown" && !pending(x)).length;
    const latest = rows.map((x) => x.checked_at).filter(Boolean).sort().at(-1);
    const label = (s, r) => r && r.source === "pending-setup" ? "Setup pending" : s === "operational" ? "Operational" : s === "degraded" ? "Degraded" : s === "outage" ? "Outage" : "Unknown";
    const pct = (x) => x == null || !isFinite(Number(x)) ? null : Math.max(0, Math.min(100, Number(x)));
    const vc = voiceCost || {};
    const money = (v) => "$" + Number(v || 0).toFixed(Number(v || 0) < 1 ? 3 : 2);
    const mins = (v) => Number(v || 0).toFixed(Number(v || 0) < 10 ? 1 : 0);
    const avgCall = Number(vc.avg_duration_sec || 0);
    const voiceCostHTML = `<section class="voicecost">
      <div class="vchead"><div><h2>OpenAI Voice Assistant Cost</h2><p>Live usage + backend reasoning · USD</p></div><span class="vcstate">Tracking</span></div>
      <div class="vcgrid">
        <div><b>${mins(vc.today_minutes)} min</b><span>Today voice time</span></div>
        <div><b>${money(vc.today_cost_usd)}</b><span>Today cost</span></div>
        <div><b>${Number(vc.conversations_today || 0)}</b><span>Today conversations</span></div>
        <div><b>${mins(vc.month_minutes)} min</b><span>This month voice time</span></div>
        <div><b>${money(vc.month_cost_usd)}</b><span>This month cost</span></div>
        <div><b>${money(vc.month_forecast_usd)}</b><span>Month forecast</span></div>
        <div><b>${Number(vc.conversations_month || 0)}</b><span>Month conversations</span></div>
        <div><b>${avgCall.toFixed(0)} sec</b><span>Average call</span></div>
      </div>
      <p class="vcnote">Voice uses GPT-Live session duration; backend GPT-6 Luna token cost is included. Current GPT-Live rate assumption: US$0.05/min.</p>
    </section>`;
    const cards = rows.map((r) => {
      const p = pct(r.usage_pct);
      const usage = p == null
        ? `<div class="usage na"><b>N/A</b><span>${esc(r.usage_label || "Not exposed")}</span></div>`
        : `<div class="usage"><div class="uv"><b>${p.toFixed(p < 10 ? 1 : 0)}%</b><span>${esc(r.usage_label || "")}</span></div><div class="bar"><i style="width:${p}%"></i></div></div>`;
      const link = r.status_url ? `<a href="${esc(r.status_url)}" target="_blank" rel="noopener">Official status ↗</a>` : "";
      const auto = r.auto_detected ? '<span class="auto">Auto-detected</span>' : "";
      return `<article class="svc ${esc(r.status)}">
        <div class="top"><div><h2>${esc(r.name)} ${auto}</h2><div class="meta">Checked ${esc(fmtTime(r.checked_at))} · ${esc(r.source || "monitor")}</div></div><span class="status ${esc(r.source === "pending-setup" ? "pending" : r.status)}">${label(r.status, r)}</span></div>
        <div class="grid"><div><span class="k">Usage %</span>${usage}</div><div><span class="k">Impact</span><span class="impact ${r.impact ? "yes" : "no"}">${r.impact ? "Yes" : "No"}</span></div></div>
        <div class="detail"><span class="k">Detail</span><p>${esc(r.detail || "No detail available.")}</p>${link}</div>
      </article>`;
    }).join("");
    return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark"><style>
      :root{font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;color-scheme:light dark}
      *{box-sizing:border-box}body{margin:0;background:#f5f6f8;color:#17191d}.wrap{max-width:1120px;margin:auto;padding:24px 18px 56px}
      h1{font-size:30px;margin:0 0 6px}.sub{color:#666;margin:0 0 20px}.sum{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:0 0 18px}
      .sum div,.svc{background:#fff;border:1px solid #e2e5ea;border-radius:14px}.sum div{padding:14px}.sum b{display:block;font-size:25px}.sum span,.meta,.k,.usage span{color:#6b7078;font-size:12px}
      .list{display:grid;gap:12px}.svc{padding:16px;border-left:5px solid #7b8088}.svc.operational{border-left-color:#22863a}.svc.degraded{border-left-color:#bf8700}.svc.outage{border-left-color:#cf222e}
      .top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.top h2{font-size:18px;margin:0 0 4px}.status,.impact,.auto{display:inline-flex;align-items:center;border-radius:999px;padding:5px 9px;font-size:12px;font-weight:700;white-space:nowrap}
      .status.operational,.impact.no{background:#dafbe1;color:#116329}.status.degraded{background:#fff8c5;color:#7d4e00}.status.outage,.impact.yes{background:#ffebe9;color:#a40e26}.status.unknown{background:#eaeef2;color:#57606a}.status.pending{background:#ddf4ff;color:#0550ae}
      .auto{background:#ddf4ff;color:#0969da;padding:3px 7px;font-size:10px;vertical-align:2px}.grid{display:grid;grid-template-columns:2fr 1fr;gap:16px;margin-top:14px}.k{display:block;text-transform:uppercase;letter-spacing:.06em;font-weight:700;margin-bottom:6px}
      .uv{display:flex;justify-content:space-between;gap:10px;align-items:baseline}.usage b{font-size:20px}.usage.na{display:flex;gap:10px;align-items:baseline}.bar{height:7px;background:#eaeef2;border-radius:99px;overflow:hidden;margin-top:6px}.bar i{display:block;height:100%;background:#57606a;border-radius:99px}
      .detail{margin-top:14px;padding-top:13px;border-top:1px solid #eaeef2}.detail p{margin:0 0 8px;line-height:1.45}.detail a{font-size:12px;text-decoration:none}.foot{margin-top:18px;color:#6b7078;font-size:12px;line-height:1.5}
      .voicecost{background:#fff;border:1px solid #e2e5ea;border-radius:14px;padding:16px;margin:0 0 18px}.vchead{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:12px}.vchead h2{font-size:18px;margin:0 0 3px}.vchead p,.vcnote{margin:0;color:#6b7078;font-size:12px;line-height:1.45}.vcstate{display:inline-flex;border-radius:999px;padding:5px 9px;background:#dafbe1;color:#116329;font-size:12px;font-weight:700}.vcgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:9px}.vcgrid div{background:#f7f8fa;border:1px solid #eaeef2;border-radius:11px;padding:11px}.vcgrid b{display:block;font-size:18px}.vcgrid span{display:block;color:#6b7078;font-size:11px;margin-top:3px}.vcnote{margin-top:10px}
      @media(max-width:650px){.wrap{padding:16px 12px 40px}h1{font-size:25px}.sum{grid-template-columns:1fr 1fr}.grid{grid-template-columns:1fr}.vcgrid{grid-template-columns:1fr 1fr}.top{align-items:center}}
      @media(prefers-color-scheme:dark){body{background:#111316;color:#f3f4f6}.sum div,.svc{background:#191c20;border-color:#30343a}.sub,.sum span,.meta,.k,.usage span,.foot{color:#aab0b8}.detail{border-color:#30343a}.bar{background:#30343a}.status.operational,.impact.no{background:#183b24;color:#75d68c}.status.degraded{background:#453b13;color:#f2cf65}.status.outage,.impact.yes{background:#4b1e24;color:#ff9a9f}.status.unknown{background:#30343a;color:#c5cad1}.status.pending{background:#12304a;color:#79c0ff}.auto{background:#17344d;color:#7cc5ff}.voicecost{background:#191c20;border-color:#30343a}.vchead p,.vcnote,.vcgrid span{color:#aab0b8}.vcgrid div{background:#15171a;border-color:#30343a}.vcstate{background:#183b24;color:#75d68c}}
    </style></head><body><div class="wrap">
      <h1>Tech Availability Report</h1>
      <p class="sub">Infrastructure health for IndiFeels reporting · automatically checked every 10 minutes${latest ? " · latest " + esc(fmtTime(latest)) : ""}</p>
      <div class="sum"><div><b>${rows.length}</b><span>Monitored systems</span></div><div><b>${healthy}</b><span>Operational</span></div><div><b>${issues}</b><span>Issues</span></div><div><b>${impacting}</b><span>Impacting IndiFeels</span></div></div>\n      ${voiceCostHTML}
      <div class="list">${cards}</div>
      <div class="foot"><b>Usage %:</b> quota/capacity consumed where the provider exposes a reliable measurable limit. “N/A” means the provider does not expose a trustworthy percentage to this monitor — it does not mean 0%.<br><b>Automatic additions:</b> new production integrations detected in the repository are added as “Auto-detected / Unknown” until a health and usage probe is configured.${unknown ? " " + unknown + " service(s) currently need verification." : ""}</div>
    </div></body></html>`;
  }
  async function openTechAvailability(r) {
    page("report", r.title);
    const st=$("#rep-status"), fr=$("#rep-frame");
    st.hidden=false; st.textContent="Checking infrastructure…"; fr.hidden=true;
    try {
      const [rows, voiceCost] = await Promise.all([loadTechAvailability(), loadVoiceCostSummary()]);
      fr.srcdoc=techReportHTML(rows, voiceCost); fr.hidden=false; st.hidden=true;
    }
    catch(e){ st.textContent="The Tech Availability Report couldn't be loaded. Pull down to refresh."; }
  }

  // ---------- report viewer ----------
  async function openReport(id, full) {
    const r = reports.find((x) => x.id === id); if (!r) return go("home");
    if (location.hash !== "#" + id) history.pushState(null, "", "#" + id);
    if (id === "report-access") { if(me?.is_admin) return go("admin"); return go("home"); }
    if (id === "schedule-panel") return openSchedulePanel();
    if (id === "stock" && !full) return openStock(r);
    if (id === "order-attribution") return openAttribution(r);
    if (id === "footwear") return openSeoRankings(r);
    if (id === "tech-availability") return openTechAvailability(r);
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


  // Surface report-frame JavaScript failures instead of silently showing an empty shell.
  window.addEventListener("message", (event) => {
    const fr = $("#rep-frame");
    if (!fr || event.source !== fr.contentWindow) return;
    const d = event.data || {};
    if (d.report !== "order-source") return;
    if (d.type === "report-render-error") {
      const st = $("#rep-status");
      st.textContent = "Order Source render error: " + (d.message || "unknown") + (d.line ? " (line " + d.line + ")" : "");
      st.hidden = false;
      console.error("Order Source render error", d);
    } else if (d.type === "report-render-stage" && d.stage === "render-complete") {
      $("#rep-status").hidden = true;
    }
  });

  // ---------- restock report ----------
  const RS_KEY = "ir-restock-state";
  window.addEventListener("message", async (event) => {
    const fr = $("#rep-frame");
    if (!fr || event.source !== fr.contentWindow) return;
    const d = event.data || {};
    if (d.type !== "restock") return;
    const reply = (o) => { try { fr.contentWindow?.postMessage(o, "*"); } catch (_) {} };
    if (d.action === "theme") {
      try { if (d.theme === "dark" || d.theme === "light") localStorage.setItem("ir-restock-theme", d.theme); } catch (_) {}
    } else if (d.action === "ready") {
      let th = "dark"; try { th = localStorage.getItem("ir-restock-theme") === "light" ? "light" : "dark"; } catch (_) {}
      reply({ type: "restock-theme", theme: th });
      try { const s = JSON.parse(localStorage.getItem(RS_KEY) || "null"); if (s) reply({ type: "restock-state", state: s }); } catch (_) {}
    } else if (d.action === "save") {
      try { localStorage.setItem(RS_KEY, JSON.stringify(d.state || {})); } catch (_) {}
    } else if (d.action === "export") {
      const rows = Array.isArray(d.rows) ? d.rows.slice(0, 5000) : [];
      const csv = "\ufeff" + rows.map((r) => r.map((c) => '"' + String(c).replace(/"/g, '""') + '"').join(",")).join("\r\n");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
      a.download = String(d.filename || "restock.csv").replace(/[^\w.-]/g, "_");
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      toast("Excel file downloaded");
    } else if (d.action === "clear") {
      try {
        const { data, error } = await sb.functions.invoke("restock-confirm", { body: { action: "clear", items: d.items, asof: d.asof } });
        if (error || !data?.ok) {
          let msg = data?.error || error?.message || "Couldn't save the removal.";
          try { const j = await error.context.json(); msg = j.error || msg; } catch (_) {}
          reply({ type: "restock-clear-result", req: d.req, ok: false, error: msg });
          return;
        }
        reply({ type: "restock-clear-result", req: d.req, ok: true });
      } catch (err) {
        reply({ type: "restock-clear-result", req: d.req, ok: false, error: err?.message || "Couldn't save the removal." });
      }
    } else if (d.action === "confirm") {
      try {
        const { data, error } = await sb.functions.invoke("restock-confirm", { body: { items: d.items, asof: d.asof } });
        if (error || !data?.ok) {
          let msg = data?.error || error?.message || "Couldn't confirm.";
          try { const j = await error.context.json(); msg = j.error || msg; } catch (_) {}
          reply({ type: "restock-confirm-result", req: d.req, ok: false, error: msg });
          return;
        }
        reply({ type: "restock-confirm-result", req: d.req, ok: true, sheet: !!data.sheet,
          message: (data.sheet ? "Added to the supplier sheet: " : "Confirmed: ") + data.count + " item" + (data.count === 1 ? "" : "s") + " · " + data.units + " units" });
        toast("Confirmed");
      } catch (err) {
        reply({ type: "restock-confirm-result", req: d.req, ok: false, error: err?.message || "Couldn't confirm." });
      }
    }
  });

  // ---------- product visibility fixes ----------
  window.addEventListener("message", async (event) => {
    const fr = $("#rep-frame");
    if (!fr || event.source !== fr.contentWindow) return;
    const d = event.data || {};
    if (d.type !== "product-visibility-fix") return;
    const action = String(d.action || "");
    const productId = d.product_id ? String(d.product_id) : null;
    if (!["fix-one", "fix-all", "ignore", "delete"].includes(action)) return;

    const send = (payload) => {
      try { fr.contentWindow?.postMessage({ type: "product-visibility-fix-result", ...payload }, "*"); } catch (_) {}
    };

    try {
      const { data, error } = await sb.functions.invoke("product-visibility-fix", {
        body: { action, product_id: productId },
      });
      if (error) {
        let msg = error.message || "Could not start the fix.";
        try { const j = await error.context.json(); msg = j.error || msg; } catch (_) {}
        send({ ok: false, error: msg });
        toast(msg);
        return;
      }
      if (!data?.ok) {
        const msg = data?.error || "Could not start the fix.";
        send({ ok: false, error: msg });
        toast(msg);
        return;
      }
      const msg = action === "fix-all"
        ? "Fix All started. Shopify will be updated and this report will refresh automatically."
        : action === "delete"
          ? "Delete started. The product will be permanently removed from Shopify and this report will refresh automatically."
          : action === "ignore"
            ? "Ignore started. The product will be archived in Shopify and removed from this report."
            : "Fix started. Shopify will be updated and this report will refresh automatically.";
      send({ ok: true, message: msg, action, product_id: productId });
      toast(action === "fix-all" ? "Fix All started" : action === "delete" ? "Delete started" : action === "ignore" ? "Product archived" : "Fix started");

      // The authenticated endpoint queues the GitHub/Shopify job. Refresh the report after it has had time to rebuild.
      setTimeout(() => { if (location.hash === "#product-visibility") openReport("product-visibility"); }, 12000);
      setTimeout(() => { if (location.hash === "#product-visibility") openReport("product-visibility"); }, 26000);
    } catch (err) {
      const msg = err?.message || "Could not start the fix.";
      send({ ok: false, error: msg });
      toast(msg);
    }
  });

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
    if(!me?.is_admin) return go("home");
    $("#users").innerHTML = '<p class="empty">Loading users…</p>';
    try { adminData = await adminCall({ action: "list" }); } catch (e) { $("#users").innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
    const reps = adminData.reports || [];
    const categories = adminData.categories || [];
    function accessGroups(uid,grants,groupGrants) {
      return categories.map(c=>{const rows=reps.filter(r=>r.category_id===c.id),eligible=rows.filter(r=>!r.admin_only),all=groupGrants.has(c.id),count=all?eligible.length:eligible.filter(r=>grants.has(r.id)).length;
        return `<details class="access-category" style="--access-accent:${esc(c.color)}"><summary><input type="checkbox" data-category="${esc(c.id)}" aria-label="Grant entire ${esc(c.title)} category" ${all?"checked":""} ${eligible.length?"":"disabled"}><strong>${c.sort}. ${esc(c.title)}</strong><span data-access-count>${count}/${eligible.length} reports</span><span class="access-chevron" aria-hidden="true">⌄</span></summary><p class="access-help">Category access includes future reports. Admin-only reports remain restricted.</p>${rows.map(r=>`<label class="access-row"><input type="checkbox" data-report="${esc(r.id)}" ${r.admin_only?"disabled":all?"checked disabled":grants.has(r.id)?"checked":""}> <span>${esc(HOME_TITLES[r.id] || r.title)}</span>${r.admin_only?'<small>Admin only</small>':all?'<small data-inherited>Category access</small>':""}</label>`).join("")}</details>`;
      }).join("");
    }
    $("#a-reports").innerHTML = reps.filter(r=>!r.admin_only).map((r) => `<label class="chk"><input type="checkbox" value="${esc(r.id)}"> ${esc(r.title)}</label>`).join("");
    const grants = {}; (adminData.grants || []).forEach((g) => (grants[g.user_id] = grants[g.user_id] || new Set()).add(g.report_id));
    $("#users").innerHTML = (adminData.users || []).map((u) => {
      const g = grants[u.id] || new Set();
      const cg=new Set((adminData.category_grants || []).filter(x=>x.user_id===u.id).map(x=>x.category_id));
      const checks = u.is_admin ? '<p class="uh meta">Admins have access to every report, including Report Access.</p>' : `<div class="access-groups">${accessGroups(u.id,g,cg)}</div><button class="btn primary sm" data-act="save" type="button">Save access</button>`;
      const self = u.id === me.id;
      return `<details class="card user access-person" data-uid="${u.id}"><summary>${esc(u.display_name || u.username)} <span>${u.is_admin?"Admin":"Member"}</span></summary>
        <div class="uh"><div><b>${esc(u.display_name || u.username)}</b>${u.is_admin ? '<span class="tag">Admin</span>' : ""}${u.disabled ? '<span class="tag off">Switched off</span>' : ""}
          <div class="meta">Username: ${esc(u.username)}${u.email ? " &nbsp;Email: " + esc(u.email) : ""}</div></div>
          <div class="uact">${self ? "" : `<button class="btn sm" data-act="toggle" type="button">${u.disabled ? "Switch on" : "Switch off"}</button><button class="btn sm danger" data-act="delete" type="button">Delete</button>`}</div></div>
        ${self?'<p class="meta">Your admin account</p>':`<button class="btn sm role-button" data-act="role" type="button">${u.is_admin?"Remove admin":"Make admin"}</button>`}
        ${checks}
        <div class="setpw"><input type="text" placeholder="New password for ${esc(u.username)}" aria-label="New password for ${esc(u.username)}" autocomplete="off"><button class="btn sm" data-act="gen" type="button">Generate</button><button class="btn sm" data-act="setpw" type="button">Set password</button></div>
      </details>`;
    }).join("") || '<p class="empty">No users yet.</p>';

    function syncAccess(group) {
      const c=group.querySelector("[data-category]"),eligible=Array.from(group.querySelectorAll("[data-report]")).filter(r=>!reps.find(x=>x.id===r.dataset.report)?.admin_only),count=eligible.filter(r=>r.checked).length;
      c.indeterminate=!c.checked && count>0;
      group.querySelector("[data-access-count]").textContent=`${count}/${eligible.length} reports`;
    }
    $$("#users .access-category").forEach(group=>{
      const c=group.querySelector("[data-category]");
      c.addEventListener("click",e=>e.stopPropagation());
      c.addEventListener("keydown",e=>e.stopPropagation());
      c.addEventListener("change",()=>{
        group.querySelectorAll("[data-report]").forEach(r=>{if(!reps.find(x=>x.id===r.dataset.report)?.admin_only){
          if(c.checked)r.dataset.individual=r.checked?"1":"0";
          r.disabled=c.checked;r.checked=c.checked || r.dataset.individual==="1";
          const label=r.closest("label");label.querySelector("[data-inherited]")?.remove();
          if(c.checked)label.insertAdjacentHTML("beforeend",'<small data-inherited>Category access</small>');
        }});syncAccess(group);
      });
      group.querySelectorAll("[data-report]").forEach(r=>{r.dataset.individual=grants[group.closest(".user").dataset.uid]?.has(r.dataset.report)?"1":"0";r.addEventListener("change",()=>{r.dataset.individual=r.checked?"1":"0";syncAccess(group);});});syncAccess(group);
    });
    $$("#users .user").forEach((card) => {
      const uid = card.dataset.uid; const u = adminData.users.find((x) => x.id === uid);
      card.querySelectorAll("[data-act]").forEach((b) => b.addEventListener("click", async () => {
        const inp = card.querySelector(".setpw input");
        try {
          if (b.dataset.act === "save") {
            b.disabled=true;
            try {await adminCall({action:"update",id:uid,reports:Array.from(card.querySelectorAll("[data-report]:checked:not(:disabled)")).map(x=>x.dataset.report),category_ids:Array.from(card.querySelectorAll("[data-category]:checked")).map(x=>x.dataset.category)});toast("Report access saved");} finally {b.disabled=false;} return;
          }
          if (b.dataset.act === "role") {await adminCall({action:"update",id:uid,is_admin:!u.is_admin});toast(u.is_admin?"Admin access removed":"Admin access granted");return renderAdmin();}
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

  async function openSchedulePanel() {
    page("schedule", "Schedule Panel");
    if (location.hash !== "#schedule-panel") history.pushState(null,"","#schedule-panel");
    await window.SchedulePanel.open(sb, $("#v-schedule"), reports, !!me?.is_admin);
  }
  // ---------- routing ----------
  function go(p) {
    if (p === "home") { if (location.hash) history.pushState(null, "", location.pathname); page("home"); renderHome(); }
    else if (p === "schedule") { openSchedulePanel(); }
    else if (p === "password") { page("password", "Change password"); }
    else if (p === "admin" && me?.is_admin) { page("admin", "Report Access"); renderAdmin(); }
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
    startAttributionRealtime(); updateOrderNotifyButton(); phonePushState();
    const id = location.hash.slice(1);
    if (id && reports.some((r) => r.id === id)) openReport(id); else { page("home"); renderHome(); }
  }
  sb.auth.onAuthStateChange((ev) => { if (ev === "SIGNED_OUT") view("login"); });
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  start();
})();


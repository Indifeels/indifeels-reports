// Caches the app shell so it opens fast; report files always come fresh from the network.
const CACHE = "ir-shell-v82-push-reconnect";
const SHELL = ["./", "index.html", "app.css?v=31-logo", "app.js?v=74-push-reconnect", "schedule-panel.css?v=4", "schedule-panel.js?v=4", "board-panel.css?v=9", "board-panel.js?v=7", "report-charcoal.css?v=1", "config.js", "vendor/supabase.js", "manifest.webmanifest", "icons/icon-192.png", "icons/favicon-48.png", "icons/badge-96.png", "favicon.ico"];
self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.includes("/r/")) return;
  e.respondWith(fetch(e.request, { cache: "no-cache" }).then((res) => { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return res; }).catch(() => caches.match(e.request)));
});

self.addEventListener("notificationclick", (e) => {
  const n = e.notification, d = n.data || {};
  n.close();
  if (e.action === "ignore") return;                       // just dismiss this reminder
  if (e.action === "mute") {                                // never remind about this task again
    if (d.muteUrl) e.waitUntil(fetch(d.muteUrl, { method: "POST", mode: "no-cors" }).catch(() => {}));
    return;
  }
  const url = d.url || "./#order-attribution";               // tapping the notification or "Open" opens the card
  e.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then((ws) => {
    for (const w of ws) { if ("focus" in w) { w.navigate(url); return w.focus(); } }
    return clients.openWindow ? clients.openWindow(url) : null;
  }));
});


self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) {
    try { d = { body: e.data ? e.data.text() : "" }; } catch (_) {}
  }
  const title = d.title || "IndiFeels Reports";
  const opts = {
    body: d.body || "New report data is available.",
    icon: "icons/icon-192.png",
    badge: "icons/badge-96.png",
    tag: d.tag || "indifeels-report-refresh",
    renotify: !!d.stage,
    data: { url: d.url || "./", muteUrl: d.muteUrl || "" }
  };
  if (d.stage) {                                            // task reminder from the Project Board
    opts.image = d.image;
    opts.requireInteraction = !!d.requireInteraction;
    opts.vibrate = d.stage === "overdue" ? [300, 120, 300, 120, 300] : [200, 100, 200];
    opts.actions = [{ action: "ignore", title: "Ignore" }, { action: "mute", title: "Never remind" }, { action: "open", title: "Open" }];
  }
  e.waitUntil(self.registration.showNotification(title, opts));
});


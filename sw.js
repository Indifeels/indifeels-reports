// Caches the app shell so it opens fast; report files always come fresh from the network.
const CACHE = "ir-shell-v41-traffic-filters";
const SHELL = ["./", "index.html", "app.css?v=30-traffic-filters", "app.js?v=43-traffic-filters", "schedule-panel.css?v=3", "schedule-panel.js?v=3", "report-charcoal.css?v=1", "config.js", "vendor/supabase.js", "manifest.webmanifest", "icons/icon-192.png"];
self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.includes("/r/")) return;
  e.respondWith(fetch(e.request, { cache: "no-cache" }).then((res) => { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return res; }).catch(() => caches.match(e.request)));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = e.notification?.data?.url || "./#order-attribution";
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
    badge: "icons/icon-192.png",
    tag: d.tag || "indifeels-report-refresh",
    renotify: false,
    data: { url: d.url || "./" }
  };
  e.waitUntil(self.registration.showNotification(title, opts));
});


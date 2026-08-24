/* Journal service worker.
   Network-first for the app HTML so a fresh deploy shows up on the next load
   (falling back to cache only when offline); cache-first for static assets.
   Auto-updates: the new worker skips waiting and claims clients immediately.
   Only active when served over http(s); ignored on file://. */
const CACHE = "journal-v1";
const ASSETS = ["./", "./index.html", "./journal.html", "./manifest.webmanifest",
  "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).catch(() => {}));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function isDocument(request, url) {
  return request.mode === "navigate" || request.destination === "document" ||
    url.pathname.endsWith("/") || url.pathname.endsWith(".html");
}

self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;

  if (isDocument(e.request, url)) {
    e.respondWith(
      fetch(e.request).then(res => {
        if (res && res.status === 200) { const clone = res.clone(); caches.open(CACHE).then(c => c.put(e.request, clone)); }
        return res;
      }).catch(() => caches.match(e.request).then(hit => hit || caches.match("./journal.html") || caches.match("./")))
    );
    return;
  }

  e.respondWith(
    caches.match(e.request).then(hit => hit || fetch(e.request).then(res => {
      if (res && res.status === 200) { const clone = res.clone(); caches.open(CACHE).then(c => c.put(e.request, clone)); }
      return res;
    }).catch(() => caches.match("./journal.html")))
  );
});

/* Pocket service worker — cache-first, precaches the app shell for full offline use.
   Bump CACHE on every deploy so clients pick up the new version. */
const CACHE = "pocket-v3";
const ASSETS = [
  "./",
  "./index.html",
  "./manifest.webmanifest",
  "./icon-192.png",
  "./icon-512.png",
  "./icon-512-maskable.png",
  "./apple-touch-icon.png"
];

// Precache the shell on install.
self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)));
  // Note: we do NOT skipWaiting() here — the new worker waits so the page can
  // show its "New version available" prompt and skip on the user's tap.
});

// Drop old caches once the new worker takes control.
self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// The page tells us to activate immediately when the user taps "refresh".
self.addEventListener("message", event => {
  if (event.data && event.data.type === "SKIP_WAITING") self.skipWaiting();
});

// Cache-first for GET requests; fall back to the network and cache what we fetch.
// Navigations fall back to the cached shell so the app opens fully offline.
self.addEventListener("fetch", event => {
  const req = event.request;
  if (req.method !== "GET") return;

  event.respondWith(
    caches.match(req).then(cached => {
      if (cached) return cached;
      return fetch(req)
        .then(res => {
          if (res && res.ok && new URL(req.url).origin === self.location.origin) {
            const copy = res.clone();
            caches.open(CACHE).then(cache => cache.put(req, copy)).catch(() => {});
          }
          return res;
        })
        .catch(() => req.mode === "navigate" ? caches.match("./index.html") : undefined);
    })
  );
});

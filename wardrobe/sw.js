/* Wardrobe service worker.
   Network-first for the app HTML so a fresh deploy shows up on the next load
   (falling back to cache only when offline); cache-first for static assets.
   Auto-updates: the new worker skips waiting and claims clients immediately, so
   users always converge on the latest version without a manual cache clear.
   Only active when served over http(s); ignored on file://. */
const CACHE = "wardrobe-v29";
const ASSETS = ["./", "./index.html", "./wardrobe.html", "./manifest.webmanifest",
  "./icon-192.png", "./icon-512.png", "./apple-touch-icon.png"];

self.addEventListener("install", e => {
  self.skipWaiting();                                   // take over as soon as the new worker is ready
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).catch(() => {}));
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))  // purge older caches
      .then(() => self.clients.claim())
  );
});

// Is this request for an HTML document (a navigation, or the app shell)?
function isDocument(request, url) {
  return request.mode === "navigate" || request.destination === "document" ||
    url.pathname.endsWith("/") || url.pathname.endsWith(".html");
}

self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  if (url.hostname.indexOf("open-meteo.com") !== -1) return;  // never cache the weather API

  if (isDocument(e.request, url)) {
    // network-first: always try the network so deploys appear immediately; cache as a fallback
    e.respondWith(
      fetch(e.request).then(res => {
        if (res && res.status === 200 && url.origin === location.origin) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      }).catch(() => caches.match(e.request).then(hit => hit || caches.match("./wardrobe.html") || caches.match("./")))
    );
    return;
  }

  // cache-first for everything else (icons, manifest) — these are versioned/rarely change
  e.respondWith(
    caches.match(e.request).then(hit => hit || fetch(e.request).then(res => {
      if (res && res.status === 200 && url.origin === location.origin) {
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
      }
      return res;
    }).catch(() => caches.match("./wardrobe.html")))
  );
});

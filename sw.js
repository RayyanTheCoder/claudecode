/* Wardrobe service worker — cache-first app shell for offline use.
   Only active when the app is served over http(s); ignored on file://. */
const CACHE = "wardrobe-v10";
const ASSETS = ["./", "./index.html", "./wardrobe.html", "./manifest.webmanifest",
  "./icon-192.png", "./icon-512.png", "./apple-touch-icon.png"];

// Install but DO NOT skipWaiting — the new worker parks in "waiting" so the page
// can show an update prompt. It activates only when the page posts SKIP_WAITING.
self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
});
self.addEventListener("message", e => { if (e.data === "SKIP_WAITING") self.skipWaiting(); });

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  // never cache the weather API — let it hit the network and fail gracefully offline
  if (url.hostname.indexOf("open-meteo.com") !== -1) return;
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

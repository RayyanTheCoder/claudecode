/* MetaStrip service worker — offline app shell + lazy runtime caching for the
   ffmpeg core. Bump CACHE when shipping new assets. */
const CACHE = 'metastrip-v1';

/* Small shell cached on install so the app opens instantly and works offline.
   The 32 MB ffmpeg core is intentionally NOT precached — it is cached on first
   use (runtime) so the app opens in well under a second. */
const SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './vendor/util/ffmpeg-util.js',
  './vendor/ffmpeg/ffmpeg.js',
  './vendor/ffmpeg/814.ffmpeg.js',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './icons/icon-maskable-512.png',
  './icons/apple-touch-icon.png',
  './icons/favicon-32.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // never touch third-party requests

  // Cache-first, then network with runtime caching. The heavy ffmpeg core/wasm
  // gets cached the first time it is fetched, enabling fully offline use after.
  event.respondWith(
    caches.match(req).then((hit) => {
      if (hit) return hit;
      return fetch(req).then((res) => {
        if (res && res.ok && res.type === 'basic') {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      }).catch(() => hit); // offline and uncached → let the request fail naturally
    })
  );
});

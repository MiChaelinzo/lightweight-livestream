// Offline shell. Loaded as a module worker (see registerOffline in js/app.js).
import {
  CACHE_NAME, SHELL_FILES, isCacheable, staleCacheNames, strategyFor,
} from "./js/sw-logic.js";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_FILES))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(staleCacheNames(names).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

async function remember(request, response) {
  if (isCacheable(response)) {
    const cache = await caches.open(CACHE_NAME);
    await cache.put(request, response.clone());
  }
  return response;
}

async function networkFirst(request) {
  try {
    return await remember(request, await fetch(request));
  } catch (err) {
    const cached = await caches.match(request);
    if (cached) return cached;
    throw err;
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  return cached || remember(request, await fetch(request));
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const strategy = strategyFor({
    url: request.url, method: request.method, origin: self.location.origin, mode: request.mode,
  });
  if (strategy === "network-only") return;
  event.respondWith(strategy === "network-first" ? networkFirst(request) : cacheFirst(request));
});

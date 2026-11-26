// Pure cache rules for sw.js. No browser APIs here so node can test them.

// Bump when any cached .js or .css file changes so old caches are dropped on
// activate. The suffix is a content fingerprint; web/test/sw-logic.test.js
// fails and prints the new value when it is out of date.
export const CACHE_NAME = "lightstream-shell-v1-facf26a3";

// Same-origin files cached on install. presets.json is cached too (offline
// fallback) but is always tried on the network first.
export const SHELL_FILES = [
  "/",
  "/style.css",
  "/presets.json",
  "/js/app.js",
  "/js/hero3d.js",
  "/js/geometry.js",
  "/js/capture-demo.js",
  "/js/presets-logic.js",
  "/js/sw-logic.js",
  "/companion/",
  "/companion/companion.css",
  "/companion/companion.js",
  "/companion/companion-logic.js",
];

// Images in /img are deliberately not precached (about 85 KB, below the fold, lazy
// loaded). They are cache-first at runtime once seen, which keeps the install small.
export const PRESETS_PATH = "/presets.json";

// Returns "network-first", "cache-first" or "network-only" (do not touch).
export function strategyFor({ url, method, origin, mode }) {
  if (method !== "GET") return "network-only";
  const parsed = new URL(url);
  if (parsed.origin !== origin) return "network-only";
  if (parsed.pathname === PRESETS_PATH) return "network-first";
  if (mode === "navigate") return "network-first";
  return "cache-first";
}

// Cache names owned by this app but not the current one.
export function staleCacheNames(names) {
  return names.filter((n) => n.startsWith("lightstream-shell-") && n !== CACHE_NAME);
}

// Only successful, same-origin ("basic") responses are worth storing.
export function isCacheable(response) {
  return Boolean(response) && response.ok && response.type === "basic";
}

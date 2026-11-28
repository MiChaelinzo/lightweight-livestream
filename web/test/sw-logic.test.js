import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import {
  CACHE_NAME, SHELL_FILES, isCacheable, staleCacheNames, strategyFor,
} from "../js/sw-logic.js";

const WEB = fileURLToPath(new URL("..", import.meta.url));
const ORIGIN = "https://example.test";

test("presets.json and page navigations are network-first", () => {
  assert.equal(strategyFor({ url: ORIGIN + "/presets.json", method: "GET", origin: ORIGIN, mode: "cors" }), "network-first");
  assert.equal(strategyFor({ url: ORIGIN + "/", method: "GET", origin: ORIGIN, mode: "navigate" }), "network-first");
});

test("same-origin static assets are cache-first", () => {
  assert.equal(strategyFor({ url: ORIGIN + "/style.css", method: "GET", origin: ORIGIN, mode: "no-cors" }), "cache-first");
  assert.equal(strategyFor({ url: ORIGIN + "/js/app.js", method: "GET", origin: ORIGIN, mode: "cors" }), "cache-first");
  assert.equal(strategyFor({ url: ORIGIN + "/manifest.webmanifest", method: "GET", origin: ORIGIN, mode: "cors" }), "cache-first");
  assert.equal(strategyFor({ url: ORIGIN + "/icons/icon-192.png", method: "GET", origin: ORIGIN, mode: "no-cors" }), "cache-first");
});

test("cross-origin and non-GET requests are never touched", () => {
  assert.equal(strategyFor({ url: "https://api.twitch.tv/helix/streams", method: "GET", origin: ORIGIN, mode: "cors" }), "network-only");
  assert.equal(strategyFor({ url: ORIGIN + "/x", method: "POST", origin: ORIGIN, mode: "cors" }), "network-only");
});

test("only old lightstream caches are marked stale", () => {
  const names = [CACHE_NAME, "lightstream-shell-v0", "other-app-cache"];
  assert.deepEqual(staleCacheNames(names), ["lightstream-shell-v0"]);
});

test("isCacheable accepts ok basic responses only", () => {
  assert.equal(isCacheable({ ok: true, type: "basic" }), true);
  assert.equal(isCacheable({ ok: false, type: "basic" }), false);
  assert.equal(isCacheable({ ok: true, type: "opaque" }), false);
  assert.equal(isCacheable(undefined), false);
});

test("every shell file exists in web/", () => {
  for (const path of SHELL_FILES) {
    const rel = path === "/" ? "index.html" : path.endsWith("/") ? path.slice(1) + "index.html" : path.slice(1);
    assert.ok(existsSync(join(WEB, rel)), "missing " + path);
  }
  assert.ok(existsSync(join(WEB, "sw.js")));
});

test("CACHE_NAME fingerprint matches every offline shell byte", () => {
  const hash = createHash("sha256");
  for (const path of [...SHELL_FILES].sort()) {
    const rel = path === "/" ? "index.html" : path.endsWith("/") ? path.slice(1) + "index.html" : path.slice(1);
    let bytes = readFileSync(join(WEB, rel));
    if (path === "/js/sw-logic.js") {
      const text = bytes.toString("utf8").split("\n")
        .filter((line) => !line.startsWith("export const CACHE_NAME")).join("\n");
      bytes = Buffer.from(text, "utf8");
    }
    hash.update(path + "\n");
    hash.update(bytes);
  }
  const want = hash.digest("hex").slice(0, 8);
  assert.equal(CACHE_NAME, "lightstream-shell-v2-" + want,
    "offline shell changed: set CACHE_NAME to lightstream-shell-v2-" + want);
});

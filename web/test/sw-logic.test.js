import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
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

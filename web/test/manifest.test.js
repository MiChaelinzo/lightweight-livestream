import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { SHELL_FILES } from "../js/sw-logic.js";

const WEB = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFileSync(join(WEB, path), "utf8");
const manifest = JSON.parse(read("manifest.webmanifest"));

function pngDimensions(path) {
  const data = readFileSync(path);
  assert.deepEqual(data.subarray(0, 8), Buffer.from("89504e470d0a1a0a", "hex"));
  return [data.readUInt32BE(16), data.readUInt32BE(20)];
}

test("manifest identifies an installable companion rather than a broadcaster", () => {
  assert.equal(manifest.id, "/");
  assert.equal(manifest.start_url, "/");
  assert.equal(manifest.scope, "/");
  assert.equal(manifest.display, "standalone");
  assert.match(manifest.name, /Companion/);
  assert.match(manifest.description, /does not broadcast from a phone/i);
  assert.equal(manifest.prefer_related_applications, false);
  assert.equal(manifest.related_applications, undefined);
});

test("manifest icons exist at their declared PNG sizes and include maskable art", () => {
  assert.ok(manifest.icons.length >= 3);
  for (const icon of manifest.icons) {
    const path = join(WEB, icon.src.slice(1));
    assert.ok(existsSync(path), icon.src);
    assert.equal(icon.type, "image/png");
    const declared = icon.sizes.split("x").map(Number);
    assert.deepEqual(pngDimensions(path), declared, icon.src);
  }
  assert.ok(manifest.icons.some((icon) => icon.purpose === "maskable"));
  assert.ok(manifest.icons.some((icon) => icon.sizes === "192x192"));
  assert.ok(manifest.icons.some((icon) => icon.sizes === "512x512"));
});

test("manifest shortcuts and screenshots reference real same-origin files", () => {
  for (const shortcut of manifest.shortcuts) {
    assert.ok(shortcut.url.startsWith("/"));
    const relative = shortcut.url.endsWith("/")
      ? shortcut.url.slice(1) + "index.html" : shortcut.url.slice(1);
    assert.ok(existsSync(join(WEB, relative)), shortcut.url);
  }
  for (const screenshot of manifest.screenshots) {
    assert.ok(existsSync(join(WEB, screenshot.src.slice(1))), screenshot.src);
    assert.equal(screenshot.form_factor, "wide");
  }
});

test("install page gives Android and iOS steps with an explicit capability boundary", () => {
  const html = read("install/index.html");
  assert.match(html, /Android: Chrome/);
  assert.match(html, /Install app/);
  assert.match(html, /iPhone or iPad: Safari/);
  assert.match(html, /Add to Home Screen/);
  assert.match(html, /companion, not a mobile broadcaster/i);
  assert.match(html, /does not ship an APK, AAB, or IPA/i);
  assert.match(html, /desktop app's phone-remote link is separate/i);
});

test("offline shell includes install metadata, icons, and both installable pages", () => {
  for (const path of [
    "/", "/install/", "/companion/", "/manifest.webmanifest",
    "/icons/icon-192.png", "/icons/icon-512.png", "/icons/maskable-512.png",
    "/js/register-sw.js", "/js/install.js",
  ]) {
    assert.ok(SHELL_FILES.includes(path), path);
  }
});

test("web companion keeps its no-dependency architecture", () => {
  const pkg = JSON.parse(read("package.json"));
  assert.equal(pkg.type, "module");
  assert.equal(pkg.dependencies, undefined);
  assert.equal(pkg.devDependencies, undefined);
});

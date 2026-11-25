// Static accessibility and security checks that parse the HTML and CSS.
// They do not replace a browser audit (not run here, UNVERIFIED).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const WEB = fileURLToPath(new URL("..", import.meta.url));
const read = (p) => readFileSync(join(WEB, p), "utf8");
const PAGES = { "index.html": read("index.html"), "companion/index.html": read("companion/index.html") };

function ids(html) {
  return [...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]);
}

test("pages declare lang, viewport, title, one h1 and a main landmark", () => {
  for (const [name, html] of Object.entries(PAGES)) {
    assert.match(html, /<html lang="[a-z]{2}/, name);
    assert.match(html, /<meta name="viewport" content="width=device-width/, name);
    assert.match(html, /<title>[^<]+<\/title>/, name);
    assert.equal((html.match(/<h1[\s>]/g) || []).length, 1, name + " h1 count");
    assert.match(html, /<main[\s>]/, name);
  }
});

test("ids are unique and in-page links and aria references resolve", () => {
  for (const [name, html] of Object.entries(PAGES)) {
    const all = ids(html);
    assert.equal(new Set(all).size, all.length, name + " duplicate ids");
    for (const m of html.matchAll(/href="#([^"]+)"/g)) assert.ok(all.includes(m[1]), name + " #" + m[1]);
    for (const m of html.matchAll(/aria-labelledby="([^"]+)"/g)) assert.ok(all.includes(m[1]), name + " labelledby " + m[1]);
  }
});

test("skip link is first in the body and targets main", () => {
  const html = PAGES["index.html"];
  assert.match(html, /<body>\s*<a class="skip" href="#main">/);
  assert.match(html, /<main id="main">/);
});

test("form controls have a label and buttons have text", () => {
  const html = PAGES["index.html"];
  for (const m of html.matchAll(/<label>([\s\S]*?)<\/label>/g)) {
    assert.match(m[1], /<(select|input)\b/, "label without control");
  }
  const controls = (html.match(/<(select|input)\b/g) || []).length;
  const labelled = (html.match(/<label>[^<]*<(select|input)\b/g) || []).length;
  assert.equal(controls, labelled);
  for (const m of html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)) assert.ok(m[1].trim().length > 0);
});

test("images and svg have text alternatives, nav has a name", () => {
  const html = PAGES["index.html"];
  assert.equal((html.match(/<img\b(?![^>]*\balt=)/g) || []).length, 0);
  for (const m of html.matchAll(/<img\b[^>]*>/g)) {
    for (const attr of ["alt", "width", "height", 'loading="lazy"', 'decoding="async"']) {
      assert.ok(m[0].includes(attr), "img missing " + attr + ": " + m[0]);
    }
  }
  assert.match(html, /<canvas id="hero-canvas" aria-hidden="true">/);
  for (const m of html.matchAll(/<svg\b([^>]*)>/g)) assert.match(m[1], /role="img"[^>]*aria-label="[^"]+"|aria-label="[^"]+"[^>]*role="img"/);
  for (const m of html.matchAll(/<nav\b([^>]*)>/g)) assert.match(m[1], /aria-label=/);
});

test("no inline scripts, inline styles or event handler attributes (strict CSP)", () => {
  for (const [name, html] of Object.entries(PAGES)) {
    assert.equal((html.match(/<script\b(?![^>]*\bsrc=)/g) || []).length, 0, name + " inline script");
    assert.equal((html.match(/<style\b/g) || []).length, 0, name + " style tag");
    assert.equal((html.match(/\sstyle="/g) || []).length, 0, name + " style attr");
    assert.equal((html.match(/\son[a-z]+="/g) || []).length, 0, name + " handler attr");
  }
});

test("vercel.json CSP forbids unsafe-inline and keeps companion hosts path-scoped", () => {
  const config = JSON.parse(read("vercel.json"));
  const csps = config.headers.flatMap((h) => h.headers).filter((h) => h.key === "Content-Security-Policy");
  assert.ok(csps.length >= 2);
  for (const csp of csps) {
    assert.doesNotMatch(csp.value, /unsafe-(inline|eval)/);
    assert.match(csp.value, /default-src 'self'/);
  }
  const root = config.headers.find((h) => h.source.startsWith("/((?!companion)"));
  assert.doesNotMatch(JSON.stringify(root), /twitch/);
  const sw = config.headers.find((h) => h.source === "/sw.js");
  assert.ok(sw.headers.some((h) => h.key === "Cache-Control" && h.value === "no-cache"));
});

test("companion renders chat with textContent only", () => {
  const js = read("companion/companion.js");
  assert.doesNotMatch(js, /innerHTML|outerHTML|insertAdjacentHTML|document\.write/);
});

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}
function vars(block) {
  return Object.fromEntries([...block.matchAll(/--([a-z]+):\s*(#[0-9a-fA-F]{6})/g)].map((m) => [m[1], m[2]]));
}

test("text colors meet WCAG AA (4.5:1) in dark and light schemes", () => {
  const css = read("style.css");
  const dark = vars(css.match(/:root\s*\{([^}]*)\}/)[1]);
  const light = { ...dark, ...vars(css.match(/prefers-color-scheme: light\)\s*\{\s*:root\s*\{([^}]*)\}/)[1]) };
  for (const [scheme, v] of [["dark", dark], ["light", light]]) {
    for (const fg of ["text", "muted", "cyan"]) {
      for (const bg of ["bg", "panel"]) {
        assert.ok(contrast(v[fg], v[bg]) >= 4.5, `${scheme} ${fg} on ${bg} = ${contrast(v[fg], v[bg]).toFixed(2)}`);
      }
    }
  }
  assert.ok(contrast("#04101a", dark.cyan) >= 4.5, "dark button text on cyan");
  assert.ok(contrast("#ffffff", light.cyan) >= 4.5 && contrast("#ffffff", light.violet) >= 4.5, "light button text");
});

test("css keeps focus ring, reduced motion and 44px touch targets", () => {
  const css = read("style.css");
  assert.match(css, /:focus-visible/);
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(css, /button, \.button \{[^}]*min-height: 44px/);
  assert.match(css, /select, input \{[^}]*min-height: 44px/);
});

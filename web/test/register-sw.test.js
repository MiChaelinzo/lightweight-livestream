import { test } from "node:test";
import assert from "node:assert/strict";
import { registerOffline } from "../js/register-sw.js";

test("service worker registers at the root as a module", async () => {
  const calls = [];
  const registration = { scope: "/" };
  const serviceWorker = {
    register: async (...args) => {
      calls.push(args);
      return registration;
    },
  };
  assert.equal(await registerOffline({ serviceWorker, protocol: "https:" }), registration);
  assert.deepEqual(calls, [["/sw.js", { type: "module" }]]);
});

test("local files and unavailable service workers remain nonfatal", async () => {
  let called = false;
  const serviceWorker = { register: async () => { called = true; } };
  assert.equal(await registerOffline({ serviceWorker, protocol: "file:" }), null);
  assert.equal(called, false);
  assert.equal(await registerOffline({ serviceWorker: null, protocol: "https:" }), null);
});

test("registration failure is reported but does not reject page startup", async () => {
  const original = console.warn;
  const warnings = [];
  console.warn = (...parts) => warnings.push(parts.join(" "));
  try {
    const result = await registerOffline({
      serviceWorker: { register: async () => { throw new Error("offline"); } },
      protocol: "https:",
    });
    assert.equal(result, null);
  } finally {
    console.warn = original;
  }
  assert.match(warnings.join("\n"), /Offline mode unavailable: offline/);
});

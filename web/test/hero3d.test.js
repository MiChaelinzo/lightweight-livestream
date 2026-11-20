import { test } from "node:test";
import assert from "node:assert/strict";
import { chooseMode, isLowEnd } from "../js/hero3d.js";

test("chooseMode picks off, still or animate", () => {
  assert.equal(chooseMode({ hasWebGL: false, reducedMotion: false, lowEnd: false }), "off");
  assert.equal(chooseMode({ hasWebGL: true, reducedMotion: true, lowEnd: false }), "still");
  assert.equal(chooseMode({ hasWebGL: true, reducedMotion: false, lowEnd: true }), "still");
  assert.equal(chooseMode({ hasWebGL: true, reducedMotion: false, lowEnd: false }), "animate");
});

test("isLowEnd uses cores and memory when reported", () => {
  assert.equal(isLowEnd({ hardwareConcurrency: 2 }), true);
  assert.equal(isLowEnd({ hardwareConcurrency: 8, deviceMemory: 2 }), true);
  assert.equal(isLowEnd({ hardwareConcurrency: 8, deviceMemory: 8 }), false);
  assert.equal(isLowEnd({}), false);
});

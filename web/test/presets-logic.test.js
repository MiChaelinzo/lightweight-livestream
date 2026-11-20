import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  PC_CLASSES,
  describeCommand,
  gbPerHour,
  recommendPreset,
  requiredUploadMbps,
  streamKbps,
} from "../js/presets-logic.js";

const data = JSON.parse(
  readFileSync(new URL("../presets.json", import.meta.url), "utf8")
);
const byName = Object.fromEntries(data.presets.map((p) => [p.name, p]));

test("presets.json has the expected shape", () => {
  assert.ok(byName[data.default], "default preset exists");
  for (const p of data.presets) {
    for (const key of ["width", "height", "fps", "video_kbps", "audio_kbps"]) {
      assert.ok(Number.isInteger(p[key]) && p[key] > 0, p.name + "." + key);
    }
    assert.equal(typeof p.description, "string");
    assert.equal(typeof p.x264_preset, "string");
  }
});

test("bandwidth maths", () => {
  const light = byName.light;
  assert.equal(streamKbps(light), 1096);
  assert.ok(Math.abs(requiredUploadMbps(light) - 1.644) < 1e-9);
  assert.ok(Math.abs(gbPerHour(light) - 0.4932) < 1e-9);
});

test("recommendation respects upload and PC class", () => {
  assert.equal(recommendPreset(data.presets, 50, "strong").name, "720p60");
  assert.equal(recommendPreset(data.presets, 50, "average").name, "balanced");
  assert.equal(recommendPreset(data.presets, 50, "old").name, "light");
  assert.equal(recommendPreset(data.presets, 2, "strong").name, "light");
});

test("recommendation falls back to the lowest preset", () => {
  assert.equal(recommendPreset(data.presets, 0.1, "strong").name, "potato");
});

test("every preset is recommendable with enough upload on a strong PC", () => {
  for (const p of data.presets) {
    const best = recommendPreset(data.presets, requiredUploadMbps(p), "strong");
    assert.ok(streamKbps(best) >= streamKbps(p), p.name);
  }
});

test("invalid input is rejected", () => {
  assert.throws(() => recommendPreset(data.presets, 5, "nope"));
  assert.throws(() => recommendPreset(data.presets, NaN, "old"));
  assert.throws(() => recommendPreset(data.presets, -1, "old"));
  assert.throws(() => recommendPreset([], 5, "old"));
  assert.ok(Object.keys(PC_CLASSES).length >= 3);
});

test("command text", () => {
  assert.equal(describeCommand(byName.light), "lightstream start --platform twitch --preset light");
});

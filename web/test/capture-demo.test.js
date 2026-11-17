import test from "node:test";
import assert from "node:assert/strict";
import { extensionForMime, pickMimeType } from "../js/capture-demo.js";

test("extensionForMime follows the recorder container", () => {
  assert.equal(extensionForMime("video/mp4;codecs=avc1"), "mp4");
  assert.equal(extensionForMime("video/webm;codecs=vp9,opus"), "webm");
  assert.equal(extensionForMime(""), "webm");
});

test("pickMimeType returns the first supported candidate or empty", () => {
  assert.equal(pickMimeType((t) => t === "video/mp4"), "video/mp4");
  assert.equal(pickMimeType(() => false), "");
});

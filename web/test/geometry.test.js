import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildIcosahedron, buildRing, multiply, rotationY, translation,
} from "../js/geometry.js";

test("icosahedron has 20 faces and 30 unique edges on the unit sphere", () => {
  const { triangles, edges } = buildIcosahedron();
  assert.equal(triangles.length, 20 * 3 * 6);
  assert.equal(edges.length, 30 * 2 * 3);
  for (let i = 0; i < triangles.length; i += 6) {
    const len = Math.hypot(triangles[i], triangles[i + 1], triangles[i + 2]);
    assert.ok(Math.abs(len - 1) < 1e-6);
  }
});

test("ring has two points per segment", () => {
  assert.equal(buildRing(10, 2).length, 10 * 2 * 3);
});

test("matrix multiply: identity-like composition", () => {
  const m = multiply(translation(1, 2, 3), rotationY(0));
  assert.deepEqual(Array.from(m.slice(12, 15)), [1, 2, 3]);
});

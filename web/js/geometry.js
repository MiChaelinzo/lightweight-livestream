// Pure geometry and matrix helpers for the hero scene. No DOM, no WebGL.

const GOLDEN = (1 + Math.sqrt(5)) / 2;

const ICO_VERTS = [
  [-1, GOLDEN, 0], [1, GOLDEN, 0], [-1, -GOLDEN, 0], [1, -GOLDEN, 0],
  [0, -1, GOLDEN], [0, 1, GOLDEN], [0, -1, -GOLDEN], [0, 1, -GOLDEN],
  [GOLDEN, 0, -1], [GOLDEN, 0, 1], [-GOLDEN, 0, -1], [-GOLDEN, 0, 1],
];

const ICO_FACES = [
  [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
  [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
  [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
  [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1],
];

export function normalize(v) {
  const len = Math.hypot(v[0], v[1], v[2]);
  return [v[0] / len, v[1] / len, v[2] / len];
}

// Unit icosahedron, flat shaded: three vertices and one normal per face.
// Returns interleaved [x,y,z,nx,ny,nz] floats and a deduplicated edge list.
export function buildIcosahedron() {
  const verts = ICO_VERTS.map(normalize);
  const triangles = [];
  const edgeKeys = new Set();
  const edges = [];
  for (const [a, b, c] of ICO_FACES) {
    const va = verts[a], vb = verts[b], vc = verts[c];
    const n = normalize([
      va[0] + vb[0] + vc[0], va[1] + vb[1] + vc[1], va[2] + vb[2] + vc[2],
    ]);
    for (const v of [va, vb, vc]) triangles.push(...v, ...n);
    for (const [i, j] of [[a, b], [b, c], [c, a]]) {
      const key = Math.min(i, j) + "-" + Math.max(i, j);
      if (edgeKeys.has(key)) continue;
      edgeKeys.add(key);
      edges.push(...verts[i], ...verts[j]);
    }
  }
  return { triangles: new Float32Array(triangles), edges: new Float32Array(edges) };
}

// Ring of line segments in the XZ plane.
export function buildRing(segments, radius) {
  const out = [];
  for (let i = 0; i < segments; i++) {
    const a0 = (i / segments) * Math.PI * 2;
    const a1 = ((i + 1) / segments) * Math.PI * 2;
    out.push(Math.cos(a0) * radius, 0, Math.sin(a0) * radius);
    out.push(Math.cos(a1) * radius, 0, Math.sin(a1) * radius);
  }
  return new Float32Array(out);
}

// Column-major 4x4 matrices (WebGL layout).
export function perspective(fovY, aspect, near, far) {
  const f = 1 / Math.tan(fovY / 2);
  const nf = 1 / (near - far);
  return new Float32Array([
    f / aspect, 0, 0, 0,
    0, f, 0, 0,
    0, 0, (far + near) * nf, -1,
    0, 0, 2 * far * near * nf, 0,
  ]);
}

export function rotationY(a) {
  const c = Math.cos(a), s = Math.sin(a);
  return new Float32Array([c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1]);
}

export function rotationX(a) {
  const c = Math.cos(a), s = Math.sin(a);
  return new Float32Array([1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1]);
}

export function translation(x, y, z) {
  return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]);
}

export function multiply(a, b) {
  const out = new Float32Array(16);
  for (let col = 0; col < 4; col++) {
    for (let row = 0; row < 4; row++) {
      let sum = 0;
      for (let k = 0; k < 4; k++) sum += a[k * 4 + row] * b[col * 4 + k];
      out[col * 4 + row] = sum;
    }
  }
  return out;
}

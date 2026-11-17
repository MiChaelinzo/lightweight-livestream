// Dependency-free raw WebGL hero: a shaded icosahedron with neon edges and an
// orbiting ring. Falls back to the CSS gradient when WebGL is missing, and
// draws one still frame on weak devices or when reduced motion is requested.

import {
  buildIcosahedron, buildRing, multiply, perspective,
  rotationX, rotationY, translation,
} from "./geometry.js";

const LOW_END_MAX_CORES = 2;
const LOW_END_MAX_MEMORY_GB = 2;
const FOV_Y = Math.PI / 4;
const NEAR = 0.1;
const FAR = 50;
const CAMERA_DISTANCE = 4.2;
const RING_SEGMENTS = 96;
const RING_RADIUS = 1.9;
const SPIN_Y = 0.35;
const SPIN_X = 0.18;
const RING_TILT = 0.5;
const STILL_FRAME_TIME = 2.2;
const MAX_PIXEL_RATIO = 2;

export function isLowEnd(nav) {
  const cores = nav.hardwareConcurrency;
  const memory = nav.deviceMemory;
  return (
    (typeof cores === "number" && cores <= LOW_END_MAX_CORES) ||
    (typeof memory === "number" && memory <= LOW_END_MAX_MEMORY_GB)
  );
}

// "animate" runs the loop, "still" draws one frame, "off" shows the CSS fallback.
export function chooseMode({ hasWebGL, reducedMotion, lowEnd }) {
  if (!hasWebGL) return "off";
  return reducedMotion || lowEnd ? "still" : "animate";
}

const FACE_VERT = `
attribute vec3 position;
attribute vec3 normal;
uniform mat4 model;
uniform mat4 viewProj;
varying vec3 vNormal;
varying vec3 vView;
void main() {
  vec4 world = model * vec4(position, 1.0);
  vNormal = mat3(model) * normal;
  vView = normalize(vec3(0.0, 0.0, ${CAMERA_DISTANCE.toFixed(1)}) - world.xyz);
  gl_Position = viewProj * world;
}`;

const FACE_FRAG = `
precision mediump float;
uniform float time;
varying vec3 vNormal;
varying vec3 vView;
void main() {
  vec3 n = normalize(vNormal);
  float rim = pow(1.0 - max(dot(n, normalize(vView)), 0.0), 2.0);
  float key = max(dot(n, normalize(vec3(0.4, 0.8, 0.6))), 0.0);
  float pulse = 0.5 + 0.5 * sin(time * 1.4);
  vec3 base = vec3(0.04, 0.06, 0.14) + key * vec3(0.05, 0.12, 0.22);
  vec3 glow = mix(vec3(0.1, 0.8, 1.0), vec3(0.8, 0.2, 1.0), pulse) * rim;
  gl_FragColor = vec4(base + glow, 1.0);
}`;

const LINE_VERT = `
attribute vec3 position;
uniform mat4 model;
uniform mat4 viewProj;
void main() { gl_Position = viewProj * model * vec4(position, 1.0); }`;

const LINE_FRAG = `
precision mediump float;
uniform vec3 color;
void main() { gl_FragColor = vec4(color, 1.0); }`;

function compile(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error("Shader compile failed: " + gl.getShaderInfoLog(shader));
  }
  return shader;
}

function link(gl, vertSrc, fragSrc) {
  const program = gl.createProgram();
  gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, vertSrc));
  gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, fragSrc));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error("Program link failed: " + gl.getProgramInfoLog(program));
  }
  return program;
}

function uploadBuffer(gl, data) {
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
  return buffer;
}

function createScene(gl) {
  const facesProgram = link(gl, FACE_VERT, FACE_FRAG);
  const linesProgram = link(gl, LINE_VERT, LINE_FRAG);
  const ico = buildIcosahedron();
  const ring = buildRing(RING_SEGMENTS, RING_RADIUS);
  const buffers = {
    faces: uploadBuffer(gl, ico.triangles),
    edges: uploadBuffer(gl, ico.edges),
    ring: uploadBuffer(gl, ring),
  };
  const counts = {
    faces: ico.triangles.length / 6,
    edges: ico.edges.length / 3,
    ring: ring.length / 3,
  };
  const FLOAT_BYTES = 4;
  const FACE_STRIDE = 6 * FLOAT_BYTES;

  function drawFaces(model, viewProj, time) {
    gl.useProgram(facesProgram);
    const pos = gl.getAttribLocation(facesProgram, "position");
    const nor = gl.getAttribLocation(facesProgram, "normal");
    gl.bindBuffer(gl.ARRAY_BUFFER, buffers.faces);
    gl.enableVertexAttribArray(pos);
    gl.enableVertexAttribArray(nor);
    gl.vertexAttribPointer(pos, 3, gl.FLOAT, false, FACE_STRIDE, 0);
    gl.vertexAttribPointer(nor, 3, gl.FLOAT, false, FACE_STRIDE, 3 * FLOAT_BYTES);
    gl.uniformMatrix4fv(gl.getUniformLocation(facesProgram, "model"), false, model);
    gl.uniformMatrix4fv(gl.getUniformLocation(facesProgram, "viewProj"), false, viewProj);
    gl.uniform1f(gl.getUniformLocation(facesProgram, "time"), time);
    gl.drawArrays(gl.TRIANGLES, 0, counts.faces);
    gl.disableVertexAttribArray(nor);
  }

  function drawLines(buffer, count, model, viewProj, color) {
    gl.useProgram(linesProgram);
    const pos = gl.getAttribLocation(linesProgram, "position");
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.enableVertexAttribArray(pos);
    gl.vertexAttribPointer(pos, 3, gl.FLOAT, false, 0, 0);
    gl.uniformMatrix4fv(gl.getUniformLocation(linesProgram, "model"), false, model);
    gl.uniformMatrix4fv(gl.getUniformLocation(linesProgram, "viewProj"), false, viewProj);
    gl.uniform3fv(gl.getUniformLocation(linesProgram, "color"), color);
    gl.drawArrays(gl.LINES, 0, count);
  }

  return function render(width, height, time) {
    gl.viewport(0, 0, width, height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.DEPTH_TEST);
    const proj = perspective(FOV_Y, width / height, NEAR, FAR);
    const view = translation(0, 0, -CAMERA_DISTANCE);
    const viewProj = multiply(proj, view);
    const model = multiply(rotationY(time * SPIN_Y), rotationX(time * SPIN_X));
    const ringModel = multiply(rotationX(RING_TILT), rotationY(-time * SPIN_Y * 2));
    drawFaces(model, viewProj, time);
    drawLines(buffers.edges, counts.edges, model, viewProj, [0.2, 0.9, 1.0]);
    drawLines(buffers.ring, counts.ring, ringModel, viewProj, [0.85, 0.3, 1.0]);
  };
}

// Returns { mode, stop }. onFallback() is called when the CSS fallback should show.
export function startHero(canvas, env = {}) {
  const nav = env.navigator || navigator;
  const reducedMotion = Boolean(
    (env.matchMedia || window.matchMedia)("(prefers-reduced-motion: reduce)").matches
  );
  const gl = canvas.getContext("webgl", { antialias: true, alpha: true });
  const mode = chooseMode({ hasWebGL: Boolean(gl), reducedMotion, lowEnd: isLowEnd(nav) });
  if (mode === "off") return { mode, stop() {} };

  let render;
  try {
    render = createScene(gl);
  } catch (err) {
    console.warn("3D hero disabled:", err.message);
    return { mode: "off", stop() {} };
  }

  const pixelRatio = Math.min(
    window.devicePixelRatio || 1,
    isLowEnd(nav) ? 1 : MAX_PIXEL_RATIO
  );
  function resize() {
    const w = Math.max(1, Math.floor(canvas.clientWidth * pixelRatio));
    const h = Math.max(1, Math.floor(canvas.clientHeight * pixelRatio));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
  }

  if (mode === "still") {
    resize();
    render(canvas.width, canvas.height, STILL_FRAME_TIME);
    window.addEventListener("resize", () => {
      resize();
      render(canvas.width, canvas.height, STILL_FRAME_TIME);
    });
    return { mode, stop() {} };
  }

  let frameId = 0;
  let visible = true;
  const startedAt = performance.now();
  function frame(now) {
    resize();
    render(canvas.width, canvas.height, (now - startedAt) / 1000);
    frameId = requestAnimationFrame(frame);
  }
  function setRunning(shouldRun) {
    if (shouldRun && !frameId) frameId = requestAnimationFrame(frame);
    if (!shouldRun && frameId) {
      cancelAnimationFrame(frameId);
      frameId = 0;
    }
  }
  const observer = new IntersectionObserver((entries) => {
    visible = entries[0].isIntersecting;
    setRunning(visible && !document.hidden);
  });
  observer.observe(canvas);
  const onVisibility = () => setRunning(visible && !document.hidden);
  document.addEventListener("visibilitychange", onVisibility);
  setRunning(true);

  return {
    mode,
    stop() {
      setRunning(false);
      observer.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
    },
  };
}

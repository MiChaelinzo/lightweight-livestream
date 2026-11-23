import { startHero } from "./hero3d.js";
import { setupCaptureDemo } from "./capture-demo.js";
import {
  PC_CLASSES, describeCommand, gbPerHour, recommendPreset,
  requiredUploadMbps, streamKbps,
} from "./presets-logic.js";

const $ = (id) => document.getElementById(id);
const DEFAULT_UPLOAD_MBPS = 5;

function initHero() {
  const canvas = $("hero-canvas");
  try {
    const hero = startHero(canvas, {
      onFallback: () => document.body.classList.add("no-3d"),
    });
    if (hero.mode === "off") document.body.classList.add("no-3d");
  } catch (err) {
    console.warn("3D hero disabled:", err.message);
    document.body.classList.add("no-3d");
  }
}

function renderResult(preset, presets, uploadMbps, pcClass) {
  const rec = recommendPreset(presets, uploadMbps, pcClass);
  const lines = [
    "Recommended: " + rec.name + " (" + rec.width + "x" + rec.height + " at " + rec.fps + " fps)",
    rec.description,
    "Needs about " + requiredUploadMbps(rec).toFixed(1) + " Mbps upload and uses about " +
      gbPerHour(rec).toFixed(2) + " GB per hour (" + streamKbps(rec) + " kbps total).",
    "Command: " + describeCommand(rec),
  ];
  if (preset && preset.name !== rec.name) {
    lines.push("You picked " + preset.name + ", which may not suit this upload speed or PC.");
  }
  $("result").textContent = lines.join("\n");
}

async function initPicker() {
  const select = $("preset");
  const upload = $("upload");
  const pc = $("pc");
  const result = $("result");
  let data;
  try {
    const response = await fetch("presets.json");
    if (!response.ok) throw new Error("HTTP " + response.status);
    data = await response.json();
  } catch (err) {
    result.textContent = "Could not load presets (" + err.message + "). See the README table instead.";
    return;
  }
  for (const [key, cls] of Object.entries(PC_CLASSES)) {
    pc.add(new Option(cls.label, key));
  }
  for (const p of data.presets) select.add(new Option(p.name, p.name));
  select.value = data.default;
  upload.value = String(DEFAULT_UPLOAD_MBPS);

  function update() {
    const uploadMbps = Number(upload.value);
    if (!Number.isFinite(uploadMbps) || uploadMbps <= 0) {
      result.textContent = "Enter your upload speed in Mbps (a number above 0).";
      return;
    }
    const chosen = data.presets.find((p) => p.name === select.value);
    renderResult(chosen, data.presets, uploadMbps, pc.value);
  }
  for (const el of [select, upload, pc]) el.addEventListener("input", update);
  update();
}

// Offline shell. Optional: any failure leaves the site working online.
function registerOffline() {
  if (!("serviceWorker" in navigator) || location.protocol === "file:") return;
  navigator.serviceWorker.register("/sw.js", { type: "module" }).catch((err) => {
    console.warn("Offline mode unavailable:", err.message);
  });
}

initHero();
initPicker();
registerOffline();
setupCaptureDemo({
  startButton: $("capture-start"),
  stopButton: $("capture-stop"),
  status: $("capture-status"),
  preview: $("capture-preview"),
  download: $("capture-download"),
});

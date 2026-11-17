// Pure helpers for the preset picker. No DOM, no network, easy to test.
// Preset numbers come from presets.json, generated from the Python presets.

export const UPLOAD_HEADROOM = 1.5;
const KBPS_PER_MBPS = 1000;
const BITS_PER_BYTE = 8;
const SECONDS_PER_HOUR = 3600;
const BYTES_PER_GB = 1e9;

// Highest video bitrate each PC class is expected to encode comfortably.
export const PC_CLASSES = {
  old: { label: "Old or weak PC", maxVideoKbps: 1000 },
  average: { label: "Average PC", maxVideoKbps: 2500 },
  strong: { label: "Strong PC or hardware encoder", maxVideoKbps: Infinity },
};

export function streamKbps(preset) {
  return preset.video_kbps + preset.audio_kbps;
}

export function requiredUploadMbps(preset) {
  return (streamKbps(preset) * UPLOAD_HEADROOM) / KBPS_PER_MBPS;
}

export function gbPerHour(preset) {
  const bytesPerSecond = (streamKbps(preset) * KBPS_PER_MBPS) / BITS_PER_BYTE;
  return (bytesPerSecond * SECONDS_PER_HOUR) / BYTES_PER_GB;
}

// Returns the best preset the upload speed and PC class allow. Falls back to
// the lowest-bitrate preset so there is always an answer.
export function recommendPreset(presets, uploadMbps, pcClass) {
  const cls = PC_CLASSES[pcClass];
  if (!cls) throw new Error("Unknown PC class: " + pcClass);
  if (!Array.isArray(presets) || presets.length === 0) {
    throw new Error("No presets available");
  }
  if (!Number.isFinite(uploadMbps) || uploadMbps <= 0) {
    throw new Error("Upload speed must be a positive number");
  }
  const byBitrate = [...presets].sort(
    (a, b) => streamKbps(a) - streamKbps(b) || a.fps - b.fps
  );
  const fitting = byBitrate.filter(
    (p) => p.video_kbps <= cls.maxVideoKbps && requiredUploadMbps(p) <= uploadMbps
  );
  return fitting.length > 0 ? fitting[fitting.length - 1] : byBitrate[0];
}

export function describeCommand(preset) {
  return "lightstream start twitch " + preset.name;
}

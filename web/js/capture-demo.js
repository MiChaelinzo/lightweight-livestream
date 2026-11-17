// Local screen recording demo. Records to a file on this computer only.
// Browsers cannot send RTMP, so this cannot go live on Twitch or YouTube.

const MIME_CANDIDATES = [
  "video/webm;codecs=vp9,opus",
  "video/webm;codecs=vp8,opus",
  "video/webm",
  "video/mp4",
];

export function pickMimeType(isTypeSupported) {
  return MIME_CANDIDATES.find((type) => isTypeSupported(type)) || "";
}

export function isCaptureSupported(env = globalThis) {
  return Boolean(
    env.navigator && env.navigator.mediaDevices &&
    typeof env.navigator.mediaDevices.getDisplayMedia === "function" &&
    typeof env.MediaRecorder === "function"
  );
}

export function setupCaptureDemo({ startButton, stopButton, status, preview, download }) {
  if (!isCaptureSupported()) {
    startButton.disabled = true;
    status.textContent =
      "Screen recording is not available in this browser. The desktop app does not need it.";
    return;
  }

  let recorder = null;
  let stream = null;
  let objectUrl = null;

  function setIdle(message) {
    startButton.disabled = false;
    stopButton.disabled = true;
    status.textContent = message;
  }

  async function start() {
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
    } catch (err) {
      setIdle("Recording was not started: " + err.message);
      return;
    }
    const mimeType = pickMimeType((t) => MediaRecorder.isTypeSupported(t));
    const chunks = [];
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    recorder.addEventListener("dataavailable", (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    });
    recorder.addEventListener("stop", () => {
      stream.getTracks().forEach((t) => t.stop());
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      const blob = new Blob(chunks, { type: recorder.mimeType || "video/webm" });
      objectUrl = URL.createObjectURL(blob);
      preview.src = objectUrl;
      preview.hidden = false;
      download.href = objectUrl;
      download.download = "lightstream-demo.webm";
      download.hidden = false;
      setIdle("Done. The recording stays on this computer. Nothing was uploaded or streamed.");
    });
    stream.getVideoTracks()[0].addEventListener("ended", () => {
      if (recorder && recorder.state !== "inactive") recorder.stop();
    });
    recorder.start();
    startButton.disabled = true;
    stopButton.disabled = false;
    download.hidden = true;
    status.textContent = "Recording locally. Press Stop when you are done.";
  }

  function stop() {
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }

  startButton.addEventListener("click", start);
  stopButton.addEventListener("click", stop);
  setIdle("Ready. Nothing is recorded until you press Start and pick a screen.");
}

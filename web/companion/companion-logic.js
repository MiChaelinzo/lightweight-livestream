// Pure companion logic. No DOM, no network, no clock access: everything is injected.

export const MAX_CHAT_LINES = 8;
export const MAX_MESSAGE_CHARS = 200;
const CHANNEL_PATTERN = /^[a-z0-9_]{3,25}$/;

export function formatTimer(totalSeconds) {
  const safe = Number.isFinite(totalSeconds) ? Math.max(0, Math.floor(totalSeconds)) : 0;
  const pad = (n) => String(n).padStart(2, "0");
  return pad(Math.floor(safe / 3600)) + ":" + pad(Math.floor((safe % 3600) / 60)) + ":" + pad(safe % 60);
}

export function goalPercent(current, target) {
  if (!(target > 0) || !Number.isFinite(current)) return 0;
  return Math.min(100, Math.max(0, Math.round((current / target) * 100)));
}

function toPositiveInt(value, fallback) {
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

/**
 * Settings come from the URL. Credentials (clientId, token) are read from the
 * fragment only, because fragments are never sent to a server. Query strings
 * are ignored for credentials on purpose.
 */
export function parseCompanionParams(search, hash) {
  const query = new URLSearchParams(String(search || "").replace(/^\?/, ""));
  const fragment = new URLSearchParams(String(hash || "").replace(/^#/, ""));
  const channel = (fragment.get("channel") || query.get("channel") || "").trim().toLowerCase();
  return {
    channel: CHANNEL_PATTERN.test(channel) ? channel : "",
    clientId: (fragment.get("clientId") || "").trim(),
    token: (fragment.get("token") || "").trim(),
    goalTarget: toPositiveInt(fragment.get("goal") || query.get("goal"), 100),
    goalLabel: (fragment.get("goalLabel") || query.get("goalLabel") || "Follower goal").slice(0, 40),
    demo: !channel || (fragment.get("demo") || query.get("demo")) === "1",
  };
}

/** Remove control characters and cap length. Callers must still use textContent. */
export function sanitizeChatText(text) {
  // eslint-disable-next-line no-control-regex
  const clean = String(text == null ? "" : text).replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim();
  return clean.length > MAX_MESSAGE_CHARS ? clean.slice(0, MAX_MESSAGE_CHARS - 1) + "\u2026" : clean;
}

/** Parse one Twitch IRC line. Returns {user, text} for chat messages, otherwise null. */
export function parseTwitchChatLine(line) {
  const match = /^(?:@\S+ )?:([^!\s]+)![^ ]+ PRIVMSG #\S+ :(.*)$/.exec(String(line).replace(/\r?\n$/, ""));
  if (!match) return null;
  const text = sanitizeChatText(match[2]);
  return text ? { user: sanitizeChatText(match[1]).slice(0, 25), text } : null;
}

export function addChatMessage(messages, message, limit = MAX_CHAT_LINES) {
  return messages.concat([message]).slice(-limit);
}

export function formatViewerCount(count) {
  if (!Number.isFinite(count) || count < 0) return "--";
  return count >= 10000 ? (count / 1000).toFixed(1).replace(/\.0$/, "") + "k" : String(Math.floor(count));
}

/** Deterministic offline sample data so demo mode is reproducible and testable. */
export function demoSnapshot(elapsedSeconds) {
  const step = Math.floor(Math.max(0, elapsedSeconds) / 5);
  const lines = [
    { user: "demo_viewer", text: "Demo mode: no credentials were given." },
    { user: "night_owl", text: "The overlay captures cleanly in a browser source scene." },
    { user: "old_laptop", text: "Streaming from an Intel HD laptop." },
    { user: "tentacle_fan", text: "Something is watching the stream." },
  ];
  return {
    viewers: 12 + (step % 7) * 3,
    followers: 40 + step,
    message: lines[step % lines.length],
  };
}

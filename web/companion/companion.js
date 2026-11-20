import {
  addChatMessage, demoSnapshot, formatTimer, formatViewerCount, goalPercent,
  parseCompanionParams, parseTwitchChatLine,
} from "./companion-logic.js";

const $ = (id) => document.getElementById(id);
const params = parseCompanionParams(location.search, location.hash);
const startedAt = Date.now();
let messages = [];
let followers = 0;

function renderChat() {
  const list = $("chat");
  list.replaceChildren();
  for (const msg of messages) {
    const row = document.createElement("li");
    const user = document.createElement("strong");
    user.textContent = msg.user + ": ";
    const text = document.createElement("span");
    text.textContent = msg.text;
    row.append(user, text);
    list.append(row);
  }
}

function renderGoal() {
  const pct = goalPercent(followers, params.goalTarget);
  $("goal-label").textContent = params.goalLabel + " " + followers + "/" + params.goalTarget;
  const bar = $("goal-bar");
  bar.value = pct;
  bar.textContent = pct + "%";
}

function setStatus(text) {
  $("status").textContent = text;
}

function pushMessage(msg) {
  messages = addChatMessage(messages, msg);
  renderChat();
}

function tickTimer() {
  $("timer").textContent = formatTimer((Date.now() - startedAt) / 1000);
}

function startDemo() {
  setStatus("Demo mode (offline sample data)");
  const update = () => {
    const snap = demoSnapshot((Date.now() - startedAt) / 1000);
    $("viewers").textContent = formatViewerCount(snap.viewers);
    followers = snap.followers;
    renderGoal();
    pushMessage(snap.message);
  };
  update();
  setInterval(update, 5000);
}

function startTwitchChat() {
  const socket = new WebSocket("wss://irc-ws.chat.twitch.tv:443");
  socket.addEventListener("open", () => {
    socket.send("NICK justinfan" + (10000 + Math.floor(Math.random() * 80000)));
    socket.send("JOIN #" + params.channel);
  });
  socket.addEventListener("message", (event) => {
    for (const line of String(event.data).split("\r\n")) {
      if (line.startsWith("PING")) socket.send("PONG :tmi.twitch.tv");
      const msg = parseTwitchChatLine(line);
      if (msg) pushMessage(msg);
    }
  });
  socket.addEventListener("close", () => setStatus("Chat disconnected. Reload to reconnect."));
  socket.addEventListener("error", () => setStatus("Chat connection failed."));
}

async function pollTwitchStats() {
  const headers = { "Client-Id": params.clientId, Authorization: "Bearer " + params.token };
  try {
    const res = await fetch("https://api.twitch.tv/helix/streams?user_login=" + encodeURIComponent(params.channel), { headers });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const body = await res.json();
    const stream = body.data && body.data[0];
    $("viewers").textContent = stream ? formatViewerCount(stream.viewer_count) : "offline";
  } catch (err) {
    setStatus("Viewer count unavailable: " + err.message);
  }
}

function start() {
  tickTimer();
  setInterval(tickTimer, 1000);
  renderGoal();
  if (params.demo) return startDemo();
  setStatus("Connecting to " + params.channel);
  startTwitchChat();
  if (params.clientId && params.token) {
    pollTwitchStats();
    setInterval(pollTwitchStats, 30000);
  } else {
    $("viewers").textContent = "--";
  }
}

start();

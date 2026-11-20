import { test } from "node:test";
import assert from "node:assert/strict";
import {
  addChatMessage, demoSnapshot, formatTimer, formatViewerCount, goalPercent,
  parseCompanionParams, parseTwitchChatLine, sanitizeChatText,
} from "../companion/companion-logic.js";

test("formatTimer pads and clamps", () => {
  assert.equal(formatTimer(0), "00:00:00");
  assert.equal(formatTimer(3725.9), "01:02:05");
  assert.equal(formatTimer(-5), "00:00:00");
  assert.equal(formatTimer(NaN), "00:00:00");
});

test("goalPercent clamps and handles bad targets", () => {
  assert.equal(goalPercent(50, 200), 25);
  assert.equal(goalPercent(500, 200), 100);
  assert.equal(goalPercent(5, 0), 0);
  assert.equal(goalPercent(-4, 10), 0);
});

test("credentials are read from the fragment only", () => {
  const p = parseCompanionParams("?channel=Some_Chan&clientId=leak&token=leak", "#clientId=abc&token=xyz&goal=50");
  assert.equal(p.channel, "some_chan");
  assert.equal(p.clientId, "abc");
  assert.equal(p.token, "xyz");
  assert.equal(p.goalTarget, 50);
  assert.equal(p.demo, false);
  const q = parseCompanionParams("?clientId=leak&token=leak", "");
  assert.equal(q.clientId, "");
  assert.equal(q.token, "");
});

test("no or invalid channel means demo mode", () => {
  assert.equal(parseCompanionParams("", "").demo, true);
  assert.equal(parseCompanionParams("", "#channel=a b").channel, "");
  assert.equal(parseCompanionParams("", "#channel=valid_name&demo=1").demo, true);
  assert.equal(parseCompanionParams("", "#goal=-3").goalTarget, 100);
});

test("sanitizeChatText strips control characters and caps length", () => {
  assert.equal(sanitizeChatText("hi\u0000\u0007 there\n"), "hi there");
  assert.equal(sanitizeChatText("<img src=x onerror=alert(1)>"), "<img src=x onerror=alert(1)>");
  assert.equal(sanitizeChatText("a".repeat(500)).length, 200);
  assert.equal(sanitizeChatText(null), "");
});

test("parseTwitchChatLine reads PRIVMSG and ignores the rest", () => {
  const line = "@badge-info= :viewer!viewer@viewer.tmi.twitch.tv PRIVMSG #chan :hello world\r\n";
  assert.deepEqual(parseTwitchChatLine(line), { user: "viewer", text: "hello world" });
  assert.equal(parseTwitchChatLine(":tmi.twitch.tv 001 justinfan1 :Welcome"), null);
  assert.equal(parseTwitchChatLine("PING :tmi.twitch.tv"), null);
});

test("addChatMessage keeps only the newest lines without mutating", () => {
  const start = [{ user: "a", text: "1" }, { user: "b", text: "2" }];
  const next = addChatMessage(start, { user: "c", text: "3" }, 2);
  assert.deepEqual(next.map((m) => m.user), ["b", "c"]);
  assert.equal(start.length, 2);
});

test("formatViewerCount and demoSnapshot are deterministic", () => {
  assert.equal(formatViewerCount(842), "842");
  assert.equal(formatViewerCount(12500), "12.5k");
  assert.equal(formatViewerCount(-1), "--");
  assert.deepEqual(demoSnapshot(12), demoSnapshot(14));
  assert.notDeepEqual(demoSnapshot(0), demoSnapshot(5));
});

import { readFileSync } from "node:fs";

test("vercel CSP allows exactly the hosts the companion uses", () => {
  const config = JSON.parse(readFileSync(new URL("../vercel.json", import.meta.url), "utf8"));
  const csp = config.headers[0].headers.find((h) => h.key === "Content-Security-Policy").value;
  const connect = csp.split(";").map((d) => d.trim()).find((d) => d.startsWith("connect-src"));
  assert.match(connect, /wss:\/\/irc-ws\.chat\.twitch\.tv/);
  assert.match(connect, /https:\/\/api\.twitch\.tv/);
  assert.doesNotMatch(connect, /\*/);
});

test("companion page and showcase carry no inline script or style and state mockups", () => {
  const companion = readFileSync(new URL("../companion/index.html", import.meta.url), "utf8");
  const index = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  for (const html of [companion, index]) {
    assert.doesNotMatch(html, /\sstyle=/);
    assert.doesNotMatch(html, /<script(?![^>]*src=)/);
  }
  assert.match(index, /not real screen captures/);
});

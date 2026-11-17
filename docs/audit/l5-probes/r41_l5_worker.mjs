// AUDIT-R41-L5 Worker probe (r41_l5_worker.mjs) — agent & queue lane.
// Mock KV, same harness shape as tests/bh_worker_poll_guard.mjs.
// Focus: panel_url claim guard parity with Flask (_check_panel_claim),
// and body-token auth parity with Flask (_agent_auth).
// FIX LANE Fix-D (R41): W02/W03 now assert the fixed behavior (were
// OBSERVE cells in the audit); W13 flipped to assert the heartbeat
// lands on the snapshot (R41-L5-P2-3 fixed) — BH-03(c) style, disclosed.
// Usage: node docs/audit/l5-probes/r41_l5_worker.mjs (exit = FAIL count)
// Import uses a relative path into the same tree's cloudflare/src/index.js.
import worker from "../../../cloudflare/src/index.js";

class MockKV {
  constructor() { this.store = new Map(); }
  async get(key, type) {
    const v = this.store.get(key);
    if (v === undefined) return null;
    if (type === "json") return JSON.parse(v);
    return v;
  }
  async put(key, value) { this.store.set(key, value); }
  async delete(key) { this.store.delete(key); }
  async list({ prefix }) {
    const keys = [...this.store.keys()].filter((k) => k.startsWith(prefix));
    return { keys: keys.map((name) => ({ name })) };
  }
}

const kv = new MockKV();
const env = { PANEL_KV: kv, ADMIN_PASSWORD: "admin-pass-123" };
const BASE = "https://panel-a.example.com";

const RESULTS = [];
function cell(name, cond, detail = "") {
  RESULTS.push([name, !!cond]);
  console.log((cond ? "PASS " : "FAIL ") + name + (detail ? " | " + detail : ""));
}

async function req(method, path, { body, headers = {}, rawBody } = {}) {
  const h = { ...headers };
  let b;
  if (rawBody !== undefined) { b = rawBody; h["Content-Type"] = "application/json"; }
  else if (body !== undefined) { b = JSON.stringify(body); h["Content-Type"] = "application/json"; }
  const r = await worker.fetch(
    new Request(BASE + path, { method, headers: h, body: b }), env, {});
  const text = await r.text();
  let j = null;
  try { j = JSON.parse(text); } catch { /* non-json */ }
  return { status: r.status, json: j, text, headers: r.headers };
}

async function loginAsAdmin(ip) {
  const r = await req("POST", "/api/login", {
    body: { password: "admin-pass-123" },
    headers: { "CF-Connecting-IP": ip },
  });
  const cookie = r.headers.get("Set-Cookie") || "";
  const m = cookie.match(/panel_session=([^;]+)/);
  return m ? `panel_session=${m[1]}` : "";
}

async function poll(token, bodyExtra = {}, headersExtra = {}) {
  const headers = { ...headersExtra };
  if (token) headers.Authorization = "Bearer " + token;
  return req("POST", "/api/agent/poll", {
    body: { node_name: "wk1", ...bodyExtra },
    headers,
  });
}

async function report(token, bodyExtra = {}) {
  return req("POST", "/api/agent/report", {
    body: { node_name: "wk1", ...bodyExtra },
    headers: token ? { Authorization: "Bearer " + token } : {},
  });
}

async function main() {
  const adminCookie = await loginAsAdmin("10.9.0.1");
  cell("W00 admin session obtained", adminCookie.length > 0);

  // Register wk1 bound to panel-a (the URL this Worker answers on).
  let r = await req("POST", "/api/nodes", {
    body: { name: "wk1", panel_url: "https://panel-a.example.com" },
    headers: { Cookie: adminCookie },
  });
  cell("W01 register node bound to panel-a", r.status === 201 && !!r.json?.token, `${r.status}`);
  const token = r.json?.token;

  // --- panel_url claim guard: Flask 403s a mismatched claim (F13). ---
  r = await poll(token, { panel_url: "https://panel-B.example.com" });
  cell("W02 poll with mismatched panel_url claim -> 403 (Flask F13 parity, R41-L5-P2-1 fixed)",
    r.status === 403, `${r.status} ${JSON.stringify(r.json)}`);

  // --- body-token auth: Flask accepts body.node_token (F09-F14 used it). ---
  r = await req("POST", "/api/agent/poll", {
    body: { node_name: "wk1", node_token: token, panel_url: "https://panel-a.example.com" },
  });
  cell("W03 poll with body token only, no header -> 200 (Flask parity, R41-L5-P2-2 fixed)",
    r.status === 200, `${r.status} ${JSON.stringify(r.json)}`);

  // Control: matching claim + header token.
  r = await poll(token, { panel_url: "https://panel-a.example.com" });
  cell("W04 poll matching claim + header token 200",
    r.status === 200 && Array.isArray(r.json?.commands), `${r.status}`);

  // --- dispatch/report lifecycle parity ---
  r = await req("POST", "/api/cmd", {
    body: { node: "wk1", action: "get_status", params: {} },
    headers: { Cookie: adminCookie },
  });
  const cmd1 = r.json?.cmd_id;
  cell("W05 enqueue get_status 202", r.status === 202 && !!cmd1, `${r.status}`);
  r = await poll(token, { panel_url: "https://panel-a.example.com" });
  cell("W06 poll delivers queued cmd once",
    r.status === 200 && r.json.commands.length === 1 && r.json.commands[0].id === cmd1,
    JSON.stringify(r.json?.commands));
  r = await poll(token, { panel_url: "https://panel-a.example.com" });
  cell("W07 second poll: sent cmd NOT re-dispatched",
    r.status === 200 && r.json.commands.length === 0, JSON.stringify(r.json?.commands));
  r = await report(token, { id: cmd1, ok: true, result: { openvpn: { running: false } } });
  cell("W08 report sent cmd 200 done",
    r.status === 200 && r.json?.status === "done", `${r.status} ${JSON.stringify(r.json)}`);
  r = await report(token, { id: cmd1, ok: true, result: {} });
  cell("W09 duplicate report 409",
    r.status === 409, `${r.status} ${JSON.stringify(r.json)}`);
  r = await req("POST", "/api/cmd", {
    body: { node: "wk1", action: "test_sk5", params: {} },
    headers: { Cookie: adminCookie },
  });
  const cmd2 = r.json?.cmd_id;
  r = await report(token, { id: cmd2, ok: true, result: {} });
  cell("W10 report for queued (never sent) cmd 409",
    r.status === 409, `${r.status} ${JSON.stringify(r.json)}`);
  r = await report(token, { id: "no-such-id", ok: true });
  cell("W11 report unknown id 404", r.status === 404, `${r.status}`);

  // --- /api/cmd whitelist enforcement parity (Flask F05) ---
  r = await req("POST", "/api/cmd", {
    body: { node: "wk1", action: "rm_rf", params: {} },
    headers: { Cookie: adminCookie },
  });
  cell("W12 unknown action via /api/cmd 400 + allowed list of 13",
    r.status === 400 && Array.isArray(r.json?.allowed) && r.json.allowed.length === 13,
    `${r.status} ${JSON.stringify(r.json)}`);

  // --- poll heartbeat: the agent sends status every poll; Flask stores
  // it on the node snapshot (F46). Worker handleAgentPoll only bumps
  // last_seen — the heartbeat status is discarded until a get_status
  // report lands. Use a FRESH node (wk2) that has only ever polled,
  // so no get_status snapshot can mask the result. ---
  r = await req("POST", "/api/nodes", {
    body: { name: "wk2", panel_url: "https://panel-a.example.com" },
    headers: { Cookie: adminCookie },
  });
  const token2 = r.json?.token;
  cell("W13a register fresh node wk2", r.status === 201 && !!token2, `${r.status}`);
  r = await req("POST", "/api/agent/poll", {
    body: { node_name: "wk2", panel_url: "https://panel-a.example.com",
            status: { version: "0.1.0", hostname: "poll-host",
                      openvpn_running: true, sk5_enabled: true } },
    headers: { Authorization: "Bearer " + token2 },
  });
  cell("W13b wk2 poll with heartbeat status 200",
    r.status === 200, `${r.status}`);
  r = await req("GET", "/api/nodes", { headers: { Cookie: adminCookie } });
  const wk2 = (r.json?.nodes || []).find((n) => n.name === "wk2") || {};
  // R41-L5-P2-3 FIXED (probe expectation flipped from the audit's OBSERVE
  // cell, BH-03(c) style — disclosed here, not silently rewritten):
  // the poll heartbeat now lands on the node snapshot like Flask F46,
  // so a poll-only node shows openvpn/sk5_enabled/status_age_s.
  cell("W13 poll-only node shows heartbeat status (R41-L5-P2-3 fixed)",
    wk2.openvpn !== null && wk2.openvpn.running === true
    && wk2.sk5_enabled === true && wk2.status_age_s !== null
    && wk2.last_seen !== null,
    JSON.stringify(wk2));

  const fails = RESULTS.filter(([, ok]) => !ok).length;
  console.log(`\n${RESULTS.length - fails}/${RESULTS.length} passed, ${fails} FAILED`);
  process.exit(fails);
}

main();

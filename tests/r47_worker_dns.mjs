// R47 Worker-face LIVE-R47-1: the Worker status must report the DNS the
// server actually pushes, not the hardcoded 1.1.1.1. The agent's
// get_status snapshot now carries the pushed DNS (core server_dns,
// read from server.conf); the Worker must (a) keep it through
// snapshotFromResult, (b) prefer it over servercfg in mergeServerCfg,
// (c) store the create_server result's dns in servercfg. Cells:
//   D1  get_status report with openvpn.dns 8.8.8.8 -> GET /api/status
//       openvpn.dns == 8.8.8.8. FAILS on 1.0.3 (snapshot drops dns,
//       merge falls back to FIXED_DNS).
//   D2  report without dns + servercfg dns 9.9.9.9 -> status 9.9.9.9
//       (servercfg fallback; control, passes on 1.0.3 too).
//   D3  report with non-string dns (123) -> status 9.9.9.9, no crash
//       (control).
//   D4  no servercfg + report without dns -> status 1.1.1.1 (control).
//   D5  create_server report with result.dns 8.8.8.8 -> servercfg dns
//       8.8.8.8. FAILS on 1.0.3 (hardcoded FIXED_DNS).
//   D6  create_server report without result.dns (old agent) ->
//       servercfg dns 1.1.1.1 (control).
//   D7  create_server report with result.dns 123 -> servercfg dns
//       1.1.1.1 (control).
//   D8  snapshot dns 8.8.8.8 beats servercfg dns 9.9.9.9 -> status
//       8.8.8.8. FAILS on 1.0.3 (merge overwrote with cfg).
//   D9  GET /api/nodes shows the same dns (list path uses
//       mergeServerCfg too). FAILS on 1.0.3.
// Usage: node tests/r47_worker_dns.mjs (exit = FAIL count)
import worker from "../cloudflare/src/index.js";

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

const env = {
  PANEL_KV: new MockKV(),
  ADMIN_PASSWORD: "admin123",
  // No AGENT_BUNDLE_ORIGIN on purpose: GET /api/nodes resolves the
  // origin bundle hash unconditionally, and a configured origin
  // would make this mock-KV probe do a real network fetch (it hangs
  // when sandbox egress stalls). Nothing under test needs the bundle.
};
const BASE = "https://panel-a.example.com";
const RESULTS = [];
const FAILURES = [];
function cell(name, ok, detail = "") {
  RESULTS.push([name, !!ok]);
  console.log((ok ? "PASS " : "FAIL ") + name + (detail ? " | " + detail : ""));
  if (!ok) FAILURES.push(name);
}
// Setup lines are printed, not counted: the corpus counts the 9 D cells.
function note(name, ok, detail = "") {
  console.log((ok ? "PASS " : "FAIL ") + name + (detail ? " | " + detail : ""));
}
async function req(method, path, { body, headers = {} } = {}) {
  const h = { ...headers };
  let b;
  if (body !== undefined) { b = JSON.stringify(body); h["Content-Type"] = "application/json"; }
  const r = await worker.fetch(new Request(BASE + path, { method, headers: h, body: b }), env, {});
  const text = await r.text();
  let j = null;
  try { j = JSON.parse(text); } catch { /* non-JSON body */ }
  return { status: r.status, text, j };
}
async function login() {
  const r = await req("POST", "/api/login", { body: { password: "admin123" } });
  const keys = [...env.PANEL_KV.store.keys()].filter((k) => k.startsWith("session:"));
  const sid = keys.length ? keys[0].slice("session:".length) : "";
  return sid ? `panel_session=${sid}` : "";
}
async function kvJson(key) { return env.PANEL_KV.get(key, "json"); }
async function kvPutJson(key, v) { await env.PANEL_KV.put(key, JSON.stringify(v)); }

// Enqueue a command and deliver it via agent poll, returning its id.
async function deliver(action, params, auth, bearer) {
  const c = await req("POST", "/api/cmd", { body: { node: "lightsail", action, params }, headers: auth });
  if (c.status !== 202 || !c.j || !c.j.cmd_id) throw new Error(`enqueue ${action} failed: ${c.status} ${c.text}`);
  const pol = await req("POST", "/api/agent/poll", { body: {}, headers: bearer });
  if (pol.status !== 200 || !Array.isArray(pol.j.commands) || !pol.j.commands.some((x) => x.id === c.j.cmd_id)) {
    throw new Error(`poll did not deliver ${action}: ${pol.status} ${pol.text}`);
  }
  return c.j.cmd_id;
}
async function report(cmdId, result, bearer, ok = true) {
  const r = await req("POST", "/api/agent/report", { body: { cmd_id: cmdId, ok, result }, headers: bearer });
  if (r.status !== 200) throw new Error(`report ${cmdId} failed: ${r.status} ${r.text}`);
  return r;
}
function statusResult(openvpn) {
  return {
    openvpn: { running: true, unit_active: true, pid: 1234, clients: [], ...(openvpn || {}) },
    users: [],
    sk5: { enabled: false },
    egress_ip: null,
    health: null,
  };
}
async function statusDns(auth) {
  const s = await req("GET", "/api/status", { headers: auth });
  if (s.status !== 200) throw new Error(`GET /api/status failed: ${s.status} ${s.text}`);
  return s.j && s.j.openvpn ? s.j.openvpn.dns : undefined;
}

const cookie = await login();
note("setup: login 200", !!cookie);
const auth = { Cookie: cookie };
const reg = await req("POST", "/api/nodes", { body: { name: "lightsail", panel_url: "" }, headers: auth });
note("setup: register lightsail 201", reg.status === 201, `status=${reg.status}`);
const nodeToken = reg.j && reg.j.token ? reg.j.token : "";
const bearer = { Authorization: `Bearer ${nodeToken}` };

// D1: snapshot dns reaches /api/status.
let id = await deliver("get_status", {}, auth, bearer);
await report(id, statusResult({ dns: "8.8.8.8" }), bearer);
let dns = await statusDns(auth);
cell("D1 status dns follows snapshot 8.8.8.8", dns === "8.8.8.8", `dns=${dns}`);

// D2/D3: no snapshot dns -> servercfg fallback; non-string dns ignored.
await kvPutJson("servercfg:lightsail", { proto: "udp", port: 1194, subnet: "10.8.0.0/24", dns: "9.9.9.9" });
id = await deliver("get_status", {}, auth, bearer);
await report(id, statusResult({}), bearer);
dns = await statusDns(auth);
cell("D2 no snapshot dns falls back to servercfg 9.9.9.9", dns === "9.9.9.9", `dns=${dns}`);
id = await deliver("get_status", {}, auth, bearer);
await report(id, statusResult({ dns: 123 }), bearer);
dns = await statusDns(auth);
cell("D3 non-string snapshot dns falls back to servercfg", dns === "9.9.9.9", `dns=${dns}`);

// D4: neither snapshot nor servercfg -> FIXED_DNS.
await env.PANEL_KV.delete("servercfg:lightsail");
id = await deliver("get_status", {}, auth, bearer);
await report(id, statusResult({}), bearer);
dns = await statusDns(auth);
cell("D4 no snapshot dns, no servercfg -> 1.1.1.1", dns === "1.1.1.1", `dns=${dns}`);

// D5/D6/D7: create_server completion stores the result dns in servercfg.
id = await deliver("create_server", { proto: "udp", port: 1194 }, auth, bearer);
await report(id, { proto: "udp", port: 1194, conf: "/etc/openvpn/server/server.conf", server_files: [], dns: "8.8.8.8" }, bearer);
let cfg = await kvJson("servercfg:lightsail");
cell("D5 create_server result dns stored in servercfg", cfg && cfg.dns === "8.8.8.8", `dns=${cfg && cfg.dns}`);
id = await deliver("create_server", { proto: "udp", port: 1194 }, auth, bearer);
await report(id, { proto: "udp", port: 1194, conf: "/etc/openvpn/server/server.conf", server_files: [] }, bearer);
cfg = await kvJson("servercfg:lightsail");
cell("D6 create_server without result dns -> 1.1.1.1", cfg && cfg.dns === "1.1.1.1", `dns=${cfg && cfg.dns}`);
id = await deliver("create_server", { proto: "udp", port: 1194 }, auth, bearer);
await report(id, { proto: "udp", port: 1194, conf: "/etc/openvpn/server/server.conf", server_files: [], dns: 123 }, bearer);
cfg = await kvJson("servercfg:lightsail");
cell("D7 create_server non-string result dns -> 1.1.1.1", cfg && cfg.dns === "1.1.1.1", `dns=${cfg && cfg.dns}`);

// D8: snapshot dns beats servercfg dns.
await kvPutJson("servercfg:lightsail", { proto: "udp", port: 1194, subnet: "10.8.0.0/24", dns: "9.9.9.9" });
id = await deliver("get_status", {}, auth, bearer);
await report(id, statusResult({ dns: "8.8.8.8" }), bearer);
dns = await statusDns(auth);
cell("D8 snapshot dns 8.8.8.8 beats servercfg 9.9.9.9", dns === "8.8.8.8", `dns=${dns}`);

// D9: /api/nodes list shows the same dns.
const nodes = await req("GET", "/api/nodes", { headers: auth });
const nodeDns = nodes.j && Array.isArray(nodes.j.nodes) && nodes.j.nodes[0] && nodes.j.nodes[0].openvpn
  ? nodes.j.nodes[0].openvpn.dns
  : undefined;
cell("D9 /api/nodes openvpn.dns 8.8.8.8", nodeDns === "8.8.8.8", `dns=${nodeDns}`);

const pass = RESULTS.length - FAILURES.length;
console.log(`\nTOTAL ${RESULTS.length} PASS ${pass} FAIL ${FAILURES.length}`);
if (FAILURES.length) { console.log("FAILURES: " + FAILURES.join(", ")); process.exit(1); }

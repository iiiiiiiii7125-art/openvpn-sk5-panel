// R47-L7 Worker CA-pin family -- the R46 Fix-AH headline (agent pins the
// panel CA, fresh-CA nodes flagged cert_pin_stale with UI badge + re-pin
// path) is Flask-only. This probe asserts the FIXED contract on the
// Worker and FAILS on the 1.0.3 tree (new-finding cells, not defect pins):
//   C1  GET /api/agent/panel-ca must NOT be a bare 404 "未知接口": the
//       installer (agent/install-agent.sh) treats 404 as "pre-fix panel"
//       and falls back to pinning the presented LEAF. In Worker mode the
//       leaf is a Cloudflare edge cert that rotates, so the fallback is
//       a time-bomb (same mechanism as LIVE-R45-3). Fixed behavior: a
//       distinctive Worker-mode status (409/501) the installer can tell
//       apart from "pre-fix panel", so it fails loudly instead of
//       leaf-pinning.
//   C2  GET /api/nodes must carry a cert_pin_stale key (null = unknown
//       is honest; ABSENT means the frontend badge can never fire).
//   C3  GET /api/status (compat) must carry cert_pin_stale too (Flask
//       app.py:1001 emits it; the Worker cachedStatus does not).
//   C4  control: agent_code_outdated DOES work in Worker mode (the
//       staleness machinery exists for code, but not for pins) -- this
//       cell PASSES on the current tree and pins the asymmetry.
// Origin fetch is stubbed via globalThis.fetch.
// Usage: node tests/r47_l7_worker_capin.mjs (exit = FAIL count)
import worker from "../cloudflare/src/index.js";
import { createHash } from "node:crypto";

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

const BUNDLE_BYTES = Buffer.from("fake-agent-bundle-bytes");
const ORIGIN_HASH = createHash("sha256").update(BUNDLE_BYTES).digest("hex");
globalThis.fetch = async (url) => {
  const u = String(url);
  if (u.endsWith("/api/agent/bundle.sha256")) {
    return new Response(`${ORIGIN_HASH}  ovpn-agent-bundle.tar.gz\n`, { status: 200 });
  }
  if (u.endsWith("/api/agent/bundle")) return new Response(BUNDLE_BYTES, { status: 200 });
  return new Response("not found", { status: 404 });
};

const env = {
  PANEL_KV: new MockKV(),
  ADMIN_PASSWORD: "admin123",
  AGENT_BUNDLE_ORIGIN: "https://origin.example:8443",
};
const BASE = "https://panel-a.example.com";
const RESULTS = [];
const FAILURES = [];
function cell(name, ok, detail = "") {
  RESULTS.push([name, !!ok]);
  console.log((ok ? "PASS " : "FAIL ") + name + (detail ? " | " + detail : ""));
  if (!ok) FAILURES.push(name);
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
  const setCookie = r.status === 200 ? "panel_session=ok" : "";
  // The mock KV stores the real session id; read it back for the cookie.
  const keys = [...env.PANEL_KV.store.keys()].filter((k) => k.startsWith("session:"));
  const sid = keys.length ? keys[0].slice("session:".length) : "";
  return sid ? `panel_session=${sid}` : setCookie;
}

const cookie = await login();
cell("setup: login 200", !!cookie);
const auth = { Cookie: cookie };

// Register a node, then let its heartbeat go stale (old last_seen).
const reg = await req("POST", "/api/nodes", { body: { name: "lightsail", panel_url: "" }, headers: auth });
cell("setup: register lightsail 201", reg.status === 201, `status=${reg.status}`);
const nodeToken = reg.j && reg.j.token ? reg.j.token : "";
// Heartbeat via poll (R45-LIVE-2: the bundle hash rides the poll
// heartbeat, body.status.bundle_sha256), then we rewind last_seen 2
// hours to simulate a bricked agent.
const OLD_HASH = "0".repeat(64);
const hb = await req("POST", "/api/agent/poll", {
  body: { status: { bundle_sha256: OLD_HASH, openvpn_running: true, sk5_enabled: false } },
  headers: { Authorization: `Bearer ${nodeToken}` },
});
cell("setup: heartbeat accepted", hb.status === 200, `status=${hb.status}`);
// Rewind the node's last_seen + snapshot time 2h (bricked-agent shape).
const snapKey = "status:lightsail";
const snap = await env.PANEL_KV.get(snapKey, "json");
if (snap) {
  snap.at = Date.now() - 2 * 3600 * 1000;
  await env.PANEL_KV.put(snapKey, JSON.stringify(snap));
}
const nodeRec = await env.PANEL_KV.get("node:lightsail", "json");
if (nodeRec) {
  nodeRec.last_seen = new Date(Date.now() - 2 * 3600 * 1000).toISOString();
  await env.PANEL_KV.put("node:lightsail", JSON.stringify(nodeRec));
}

// C1: the panel-ca endpoint must be distinguishable from "pre-fix panel".
const ca = await req("GET", "/api/agent/panel-ca");
cell(
  "C1 panel-ca is not a bare 404 (Worker-mode distinctive status)",
  ca.status !== 404,
  `status=${ca.status} body=${ca.text.slice(0, 80)}`,
);

// C2: /api/nodes carries cert_pin_stale (null = unknown is honest).
const nodes = await req("GET", "/api/nodes", { headers: auth });
const n0 = nodes.j && Array.isArray(nodes.j.nodes) ? nodes.j.nodes[0] : null;
cell(
  "C2 /api/nodes carries cert_pin_stale key",
  !!n0 && Object.prototype.hasOwnProperty.call(n0, "cert_pin_stale"),
  `keys=${n0 ? Object.keys(n0).join(",") : "no-node"}`,
);

// C3: /api/status carries cert_pin_stale (Flask app.py:1001 emits it).
const st = await req("GET", "/api/status?node=lightsail", { headers: auth });
cell(
  "C3 /api/status carries cert_pin_stale key",
  !!st.j && Object.prototype.hasOwnProperty.call(st.j, "cert_pin_stale"),
  `keys=${st.j ? Object.keys(st.j).join(",") : "no-status"}`,
);

// C4 (control, passes now): code-outdated staleness DOES work in Worker
// mode -- the asymmetry this family is about (pins, unlike code, have
// no signal at all).
cell(
  "C4 control: agent_code_outdated is true for the old hash",
  !!n0 && n0.agent_code_outdated === true,
  `agent_code_outdated=${n0 ? n0.agent_code_outdated : "no-node"}`,
);

const pass = RESULTS.filter(([, ok]) => ok).length;
console.log(`TOTAL ${RESULTS.length} PASS ${pass} FAIL ${FAILURES.length}`);
process.exit(FAILURES.length ? 1 : 0);

// R47 integration probe: Worker side of the 15-action whitelist (D04).
// Fix-BC added renew_server_cert + repair_pki as agent actions, but the
// Worker ACTIONS stayed at 13 and had no compat routes for them, so in
// Worker mode POST /api/cmd 400'd both actions and the panel's renew /
// repair buttons 404'd. Asserts the FIXED behavior: FAILS on the pre-fix
// merged tree, PASSES once the Worker carries 15 actions + both compat
// routes. Usage: node tests/r47_int_worker_renew_repair.mjs
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
  const keys = [...env.PANEL_KV.store.keys()].filter((k) => k.startsWith("session:"));
  const sid = keys.length ? keys[0].slice("session:".length) : "";
  return sid ? `panel_session=${sid}` : "";
}

const cookie = await login();
cell("setup: login 200", !!cookie);
const auth = { Cookie: cookie };
const reg = await req("POST", "/api/nodes", { body: { name: "lightsail", panel_url: "" }, headers: auth });
cell("setup: register lightsail 201", reg.status === 201, `status=${reg.status}`);
const nodeToken = reg.j && reg.j.token ? reg.j.token : "";
const bearer = { Authorization: `Bearer ${nodeToken}` };

for (const action of ["renew_server_cert", "repair_pki"]) {
  const r = await req("POST", "/api/cmd", { body: { node: "lightsail", action, params: {} }, headers: auth });
  cell(`W1 /api/cmd ${action} -> 202`, r.status === 202, `status=${r.status} body=${r.text.slice(0, 80)}`);
}
const bogus = await req("POST", "/api/cmd", { body: { node: "lightsail", action: "bogus_action", params: {} }, headers: auth });
cell("W2 /api/cmd bogus_action -> 400", bogus.status === 400, `status=${bogus.status}`);

const ren = await req("POST", "/api/openvpn/renew-server-cert?node=lightsail", { body: {}, headers: auth });
cell("W3 compat POST /api/openvpn/renew-server-cert -> 202", ren.status === 202, `status=${ren.status} body=${ren.text.slice(0, 80)}`);
const rep = await req("POST", "/api/openvpn/pki/repair?node=lightsail", { body: {}, headers: auth });
cell("W4 compat POST /api/openvpn/pki/repair -> 202", rep.status === 202, `status=${rep.status} body=${rep.text.slice(0, 80)}`);

const pol = await req("POST", "/api/agent/poll", { body: {}, headers: bearer });
const got = Array.isArray(pol.j.commands) ? pol.j.commands.map((c) => c.action).sort() : [];
cell("W5 poll delivers renew_server_cert + repair_pki",
  pol.status === 200 && got.includes("renew_server_cert") && got.includes("repair_pki"),
  `status=${pol.status} actions=${got.join(",")}`);

const pass = RESULTS.filter(([, ok]) => ok).length;
console.log(`TOTAL ${RESULTS.length} PASS ${pass} FAIL ${FAILURES.length}`);
process.exit(FAILURES.length ? 1 : 0);

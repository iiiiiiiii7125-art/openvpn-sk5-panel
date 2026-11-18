// R47 integration fixup: Worker compat-route username validation
// (R47-L3-3). Flask core validate_username ([A-Za-z0-9_-]{1,32},
// reserved server/openvpn-ca/ca) 400s bad names before enqueueing;
// the Worker used to 202 them and only fail at the agent. Cells
// assert the FIXED behavior (Flask parity): FAIL = finding present.
// Usage: node tests/r47_int_worker_username.mjs (exit = FAIL count)
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

function makeEnv() {
  return {
    PANEL_KV: new MockKV(),
    ADMIN_PASSWORD: "admin-pass-123",
    AGENT_BUNDLE_ORIGIN: "https://origin.example:8443",
  };
}
const env = makeEnv();
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
  try { j = JSON.parse(text); } catch { /* non-json */ }
  return { status: r.status, json: j, text, headers: r.headers };
}

async function main() {
  const lr = await req("POST", "/api/login", {
    body: { password: "admin-pass-123" }, headers: { "CF-Connecting-IP": "10.9.0.1" },
  });
  const m = (lr.headers.get("Set-Cookie") || "").match(/panel_session=([^;]+)/);
  const auth = m ? { Cookie: `panel_session=${m[1]}` } : {};
  cell("W00 admin session obtained", !!m, `${lr.status}`);

  const rr = await req("POST", "/api/nodes", {
    body: { name: "n1", panel_url: "https://panel-a.example.com" }, headers: auth,
  });
  cell("W00b register n1", rr.status === 201, `${rr.status}`);

  // Create-face pattern cells (Flask parity: 400 before enqueueing).
  let r = await req("POST", "/api/openvpn/users", { body: { name: "bad/name" }, headers: auth });
  cell("U1 create_user bad/name -> 400", r.status === 400, `${r.status}`);
  r = await req("POST", "/api/openvpn/users", { body: { name: "" }, headers: auth });
  cell("U2 create_user empty name -> 400", r.status === 400, `${r.status}`);
  r = await req("POST", "/api/openvpn/users", { body: { name: "x".repeat(40) }, headers: auth });
  cell("U3 create_user 40-char name -> 400", r.status === 400, `${r.status}`);
  r = await req("POST", "/api/openvpn/users", { body: { name: "server" }, headers: auth });
  cell("U4 create_user reserved 'server' -> 400", r.status === 400, `${r.status}`);
  r = await req("POST", "/api/openvpn/users", { body: { name: "OpenVPN-CA" }, headers: auth });
  cell("U5 create_user reserved 'OpenVPN-CA' -> 400", r.status === 400, `${r.status}`);
  r = await req("POST", "/api/openvpn/users", { body: { name: "ca" }, headers: auth });
  cell("U6 create_user reserved 'ca' -> 400", r.status === 400, `${r.status}`);
  r = await req("POST", "/api/openvpn/users", { body: {}, headers: auth });
  cell("U7 create_user missing name -> 400", r.status === 400, `${r.status}`);
  r = await req("POST", "/api/openvpn/users", { body: { name: 123 }, headers: auth });
  cell("U8 create_user int name -> 400", r.status === 400, `${r.status}`);
  r = await req("POST", "/api/openvpn/users", { body: { name: "alice" }, headers: auth });
  cell("U9 create_user alice -> 202 queued", r.status === 202 && r.json?.queued === true, `${r.status}`);
  r = await req("POST", "/api/openvpn/users", { body: { name: "a-1_b".padEnd(32, "x") }, headers: auth });
  cell("U10 create_user 32-char name -> 202 queued", r.status === 202 && r.json?.queued === true, `${r.status}`);

  // Revoke-face pattern cells (name comes from the URL path).
  r = await req("DELETE", "/api/openvpn/users/a%20b", { headers: auth });
  cell("R1 revoke 'a b' -> 400", r.status === 400, `${r.status}`);
  r = await req("DELETE", "/api/openvpn/users/bad%2Fname", { headers: auth });
  cell("R2 revoke 'bad/name' -> 400", r.status === 400, `${r.status}`);
  r = await req("DELETE", "/api/openvpn/users/server", { headers: auth });
  cell("R3 revoke reserved 'server' -> 400", r.status === 400, `${r.status}`);
  r = await req("DELETE", "/api/openvpn/users/alice", { headers: auth });
  cell("R4 revoke alice -> 202 queued", r.status === 202 && r.json?.queued === true, `${r.status}`);

  const pass = RESULTS.filter(([_, ok]) => ok).length;
  console.log(`TOTAL ${RESULTS.length} PASS ${pass} FAIL ${FAILURES.length}`);
  process.exit(FAILURES.length);
}

main();

// R19 Worker probe (r19_worker_ovpn_download.mjs) — R19-P2-2:
// Worker .ovpn 下载不查吊销／过期：Flask 三条下载路径对 revoked／expired
// 一律 403（R13-P2-3，AW）；Worker 专用下载路径只认回执存在即 200，
// 回执无 TTL、吊销不删回执，吊销后 .ovpn 永久可下。
// 本探针断言修复后行为（PASS = 正确）：revoked／expired → 403，valid → 200，
// 无回执 → 404。Usage: node tests/r19_worker_ovpn_download.mjs
// Import 用相对路径，指向同树 cloudflare/src/index.js，不依赖 /tmp 副本。
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

const kv = new MockKV();
const env = { PANEL_KV: kv, ADMIN_PASSWORD: "admin-pass-123" };
const BASE = "https://panel.example.com";

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

async function poll(token, node = "wk1") {
  return req("POST", "/api/agent/poll", {
    body: { node_name: node },
    headers: { Authorization: "Bearer " + token },
  });
}

async function reportDone(token, cmdId, result) {
  return req("POST", "/api/agent/report", {
    body: { cmd_id: cmdId, ok: true, result },
    headers: { Authorization: "Bearer " + token },
  });
}

async function setUserStatus(adminCookie, token, name, status) {
  const gs = await req("POST", "/api/cmd", {
    body: { node: "wk1", action: "get_status", params: {} },
    headers: { Cookie: adminCookie },
  });
  const id = gs.json?.cmd_id;
  await poll(token);
  await reportDone(token, id, { users: [{ name, status }] });
}

async function main() {
  const adminCookie = await loginAsAdmin("10.9.0.1");
  cell("DL-00 admin session obtained", adminCookie.length > 0);
  const reg = await req("POST", "/api/nodes", {
    body: { name: "wk1", panel_url: "" }, headers: { Cookie: adminCookie },
  });
  const token = reg.json?.token;
  cell("DL-00b register node 201", reg.status === 201 && !!token, `${reg.status}`);

  // 建 alice，agent 回执带 .ovpn → 回执落盘
  const cu = await req("POST", "/api/openvpn/users", {
    body: { name: "alice" }, headers: { Cookie: adminCookie },
  });
  const idCu = cu.json?.cmd_id;
  await poll(token);
  const rep = await reportDone(token, idCu, { ovpn: "client\nproto udp\n" });
  cell("DL-01 create_user receipt stored", rep.status === 200, `${rep.status}`);

  // valid（无快照用户状态）→ 200
  const d0 = await req("GET", "/api/openvpn/users/alice/ovpn", { headers: { Cookie: adminCookie } });
  cell("DL-02 download valid user: 200", d0.status === 200, `${d0.status}`);

  // revoked → 403
  await setUserStatus(adminCookie, token, "alice", "revoked");
  const d1 = await req("GET", "/api/openvpn/users/alice/ovpn", { headers: { Cookie: adminCookie } });
  cell("DL-03 download revoked user: 403", d1.status === 403, `${d1.status}`);

  // expired → 403
  await setUserStatus(adminCookie, token, "alice", "expired");
  const d2 = await req("GET", "/api/openvpn/users/alice/ovpn", { headers: { Cookie: adminCookie } });
  cell("DL-04 download expired user: 403", d2.status === 403, `${d2.status}`);

  // valid 回来 → 200
  await setUserStatus(adminCookie, token, "alice", "valid");
  const d3 = await req("GET", "/api/openvpn/users/alice/ovpn", { headers: { Cookie: adminCookie } });
  cell("DL-05 download valid again: 200", d3.status === 200, `${d3.status}`);

  // 无回执用户 → 404
  const d4 = await req("GET", "/api/openvpn/users/nobody/ovpn", { headers: { Cookie: adminCookie } });
  cell("DL-06 download unknown user: 404", d4.status === 404, `${d4.status}`);

  const fails = RESULTS.filter(([, ok]) => !ok).length;
  console.log(`\nTOTAL ${RESULTS.length} cells, FAIL ${fails}: ${RESULTS.filter(([, ok]) => !ok).map(([n]) => n).join(", ")}`);
  process.exit(fails);
}

main().catch((e) => { console.error(e); process.exit(99); });

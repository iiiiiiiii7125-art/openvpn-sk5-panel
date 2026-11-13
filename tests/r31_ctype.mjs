// AUDIT-R31 content-type probe (auditor-written, landed in tree by
// the R31-P2-1 fix lane): valid JSON body sent with a NON-JSON
// Content-Type. Flask _json_body requires request.is_json
// (application/json) and 400s otherwise; the Worker request.json()
// used to parse regardless of Content-Type.
// BH-03(c): after the R31-P2-1 fix this probe asserts the FIXED
// behavior — both faces 400 on non-JSON Content-Type (the Worker
// envelope guard); C3 (application/json; charset) stays 202 on both
// faces. The Flask counterpart is tests/r31_ctype.py.
// Usage: node tests/r31_ctype.mjs. Exit code = number of FAILs.
import worker from "../cloudflare/src/index.js";

class MockKV {
  constructor() { this.store = new Map(); }
  async get(key, type) {
    const v = this.store.get(key);
    if (v === undefined) return null;
    if (type === "json") return JSON.parse(v);
    return v;
  }
  async put(key, value, opts = {}) { this.store.set(key, value); }
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

async function req(method, path, { rawBody, contentType, headers = {} } = {}) {
  const h = { ...headers };
  if (contentType !== null) h["Content-Type"] = contentType;
  const r = await worker.fetch(new Request(BASE + path, { method, headers: h, body: rawBody }), env, {});
  const text = await r.text();
  let j = null;
  try { j = JSON.parse(text); } catch { /* non-json */ }
  return { status: r.status, json: j, text };
}

async function main() {
  const r = await worker.fetch(new Request(BASE + "/api/login", { method: "POST", headers: { "Content-Type": "application/json", "CF-Connecting-IP": "10.9.0.1" }, body: JSON.stringify({ password: "admin-pass-123" }) }), env, {});
  const ck = (r.headers.get("Set-Cookie") || "").match(/panel_session=([^;]+)/);
  const H = { Cookie: ck ? `panel_session=${ck[1]}` : "" };
  let t = await req("POST", "/api/nodes", { rawBody: JSON.stringify({ name: "n1", panel_url: "https://n1.example:8443" }), contentType: "application/json", headers: H });
  cell("W0 register node 201", t.status === 201, String(t.status));
  t = await req("POST", "/api/sk5", { rawBody: JSON.stringify({ host: "proxy.example", port: 1001, username: "u", password: "p", enabled: false }), contentType: "application/json", headers: H });
  cell("W0 sk5 save 202", t.status === 202, String(t.status));

  // C1: toggle, valid JSON, Content-Type text/plain.
  // BH-03(c): fixed, Worker 400s like Flask.
  t = await req("POST", "/api/sk5/fail-open", { rawBody: '{"fail_open": true}', contentType: "text/plain", headers: H });
  console.log(`C1 toggle text/plain: worker ${t.status} (Flask: 400, not application/json)`);
  cell("C1 toggle text/plain -> 400", t.status === 400);
  // C2: toggle, valid JSON, NO Content-Type header at all.
  // BH-03(c): fixed, Worker 400s like Flask.
  t = await req("POST", "/api/sk5/fail-open", { rawBody: '{"fail_open": false}', contentType: null, headers: H });
  console.log(`C2 toggle no content-type: worker ${t.status} (Flask: 400)`);
  cell("C2 toggle no Content-Type -> 400", t.status === 400);
  // C3: toggle, valid JSON, application/json; charset suffix.
  t = await req("POST", "/api/sk5/fail-open", { rawBody: '{"fail_open": true}', contentType: "application/json; charset=utf-8", headers: H });
  console.log(`C3 toggle json;charset: worker ${t.status} (Flask: 202)`);
  cell("C3 toggle application/json;charset -> Worker 202 (agreement)", t.status === 202);
  // C4: login with text/plain valid JSON — BH-03(c): fixed, Worker
  // 400s like Flask (the login guard already 400s on a null body).
  t = await req("POST", "/api/login", { rawBody: '{"password": "admin-pass-123"}', contentType: "text/plain", headers: { "CF-Connecting-IP": "10.9.0.9" } });
  console.log(`C4 login text/plain correct pw: worker ${t.status} (Flask: 400)`);
  cell("C4 login text/plain -> 400", t.status === 400);
  // C5: save route, text/plain valid JSON — BH-03(c): fixed, 400.
  t = await req("POST", "/api/sk5", { rawBody: '{"host":"proxy.example","port":1001,"username":"u","password":"p","enabled":false}', contentType: "text/plain", headers: H });
  console.log(`C5 save text/plain: worker ${t.status} (Flask: 400)`);
  cell("C5 save text/plain -> 400", t.status === 400);

  const fails = RESULTS.filter(([, ok]) => !ok).length;
  console.log(`R31 content-type (worker): ${RESULTS.length - fails}/${RESULTS.length}`);
  process.exit(fails);
}

main();

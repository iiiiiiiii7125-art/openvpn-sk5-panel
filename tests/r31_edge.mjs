// AUDIT-R31 edge probe (auditor-written, landed in tree by the
// R31-P2-1 fix lane): token-scanner edge shapes against the Worker
// toggle + save routes. Sends RAW bodies; JSON.stringify would
// collapse 1.0 -> "1" and hide the shapes.
// BH-03(c): after the R31-P2-1 fix this probe asserts the FIXED
// behavior — malformed / non-object bodies 400 on both faces (the
// Worker envelope guard), like Flask; E1-E11, E19, E20 are agreement
// cells and are unchanged. The Flask counterpart is
// tests/r31_edge.py.
// Usage: node tests/r31_edge.mjs (from the tree root).
// Exit code = number of FAILs.
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

async function req(method, path, { rawBody, headers = {} } = {}) {
  const h = { ...headers, "Content-Type": "application/json" };
  const r = await worker.fetch(new Request(BASE + path, { method, headers: h, body: rawBody }), env, {});
  const text = await r.text();
  let j = null;
  try { j = JSON.parse(text); } catch { /* non-json */ }
  return { status: r.status, json: j, text };
}

async function main() {
  const r0 = await req("POST", "/api/login", { rawBody: JSON.stringify({ password: "admin-pass-123" }), headers: { "CF-Connecting-IP": "10.9.0.1" } });
  const m = (r0.text.match(/panel_session=([^;"]+)/) || [])[1];
  // login sets cookie via Set-Cookie header; re-fetch headers properly:
  const H = { Cookie: "" };
  {
    const r = await worker.fetch(new Request(BASE + "/api/login", { method: "POST", headers: { "Content-Type": "application/json", "CF-Connecting-IP": "10.9.0.1" }, body: JSON.stringify({ password: "admin-pass-123" }) }), env, {});
    const ck = (r.headers.get("Set-Cookie") || "").match(/panel_session=([^;]+)/);
    H.Cookie = ck ? `panel_session=${ck[1]}` : "";
  }
  let r = await req("POST", "/api/nodes", { rawBody: JSON.stringify({ name: "n1", panel_url: "https://n1.example:8443" }), headers: H });
  cell("W0 register node 201", r.status === 201, String(r.status));
  r = await req("POST", "/api/sk5", { rawBody: JSON.stringify({ host: "proxy.example", port: 1001, username: "u", password: "p", enabled: false }), headers: H });
  cell("W0 sk5 save 202", r.status === 202, String(r.status));

  async function toggleRaw(path, raw) {
    const t = await req("POST", path, { rawBody: raw, headers: H });
    let params = null;
    if (t.json && t.json.cmd_id) {
      const rec = await kv.get(`cmd:${t.json.cmd_id}`, "json");
      params = rec ? rec.params : null;
    }
    return { status: t.status, params };
  }
  async function saveRaw(raw) {
    const t = await req("POST", "/api/sk5", { rawBody: raw, headers: H });
    let params = null;
    if (t.json && t.json.cmd_id) {
      const rec = await kv.get(`cmd:${t.json.cmd_id}`, "json");
      params = rec ? rec.params : null;
    }
    return { status: t.status, params };
  }

  // E1: duplicate keys, float first then int — JSON.parse last-wins 1.
  let t = await toggleRaw("/api/sk5/fail-open", '{"fail_open": 1.0, "fail_open": 1}');
  console.log(`E1 dup 1.0,1: worker ${t.status} params=${JSON.stringify(t.params)} (Flask: 202 True)`);
  cell("E1 dup float-then-int -> 202 True", t.status === 202 && t.params && t.params.fail_open === true);
  // E2: duplicate keys, int first then float — JSON.parse last-wins 1.0.
  t = await toggleRaw("/api/sk5/fail-open", '{"fail_open": 1, "fail_open": 1.0}');
  console.log(`E2 dup 1,1.0: worker ${t.status} (Flask: 400)`);
  cell("E2 dup int-then-float -> 400", t.status === 400);
  // E3: the key spelled inside an earlier string value must not count.
  t = await toggleRaw("/api/sk5/fail-open", '{"note": "say \\"fail_open\\": 1.0 ok", "fail_open": true}');
  console.log(`E3 key-in-string: worker ${t.status} params=${JSON.stringify(t.params)} (Flask: 202 True)`);
  cell("E3 key inside string value -> 202 True", t.status === 202 && t.params && t.params.fail_open === true);
  // E4: the key inside a nested object must not count.
  t = await toggleRaw("/api/sk5/fail-open", '{"cfg": {"fail_open": 1.0}, "fail_open": true}');
  console.log(`E4 key-in-nested-object: worker ${t.status} params=${JSON.stringify(t.params)} (Flask: 202 True)`);
  cell("E4 key inside nested object -> 202 True", t.status === 202 && t.params && t.params.fail_open === true);
  // E5: unicode-escaped key decodes to fail_open; value 1.0 is float.
  t = await toggleRaw("/api/sk5/fail-open", '{"fail_\\u006fpen": 1.0}');
  console.log(`E5 unicode-escaped key 1.0: worker ${t.status} (Flask: 400)`);
  cell("E5 unicode-escaped key with 1.0 -> 400", t.status === 400);
  // E6: pretty-printed body, 1.0 across newlines.
  t = await toggleRaw("/api/sk5/fail-open", '{\n  "fail_open": 1.0\n}');
  console.log(`E6 pretty 1.0: worker ${t.status} (Flask: 400)`);
  cell("E6 pretty-printed 1.0 -> 400", t.status === 400);
  // E7: save port duplicate float-then-int -> last-wins 1001.
  let s = await saveRaw('{"host":"proxy.example","port":1001.0,"port":1001,"username":"u","password":"p","enabled":false}');
  console.log(`E7 save port dup 1001.0,1001: worker ${s.status} params=${JSON.stringify(s.params)} (Flask: 202)`);
  cell("E7 save port dup float-then-int -> 202", s.status === 202 && s.params && s.params.port === 1001);
  // E8: save port duplicate int-then-float -> last-wins 1001.0.
  s = await saveRaw('{"host":"proxy.example","port":1001,"port":1001.0,"username":"u","password":"p","enabled":false}');
  console.log(`E8 save port dup 1001,1001.0: worker ${s.status} (Flask: 400)`);
  cell("E8 save port dup int-then-float -> 400", s.status === 400);
  // E9: string value full of braces/commas before the real key.
  t = await toggleRaw("/api/sk5/fail-open", '{"username": "a,b}c{d", "fail_open": true}');
  console.log(`E9 braces-in-string: worker ${t.status} params=${JSON.stringify(t.params)} (Flask: 202 True)`);
  cell("E9 braces/commas inside string -> 202 True", t.status === 202 && t.params && t.params.fail_open === true);
  // E10: key inside a nested array of objects must not count.
  t = await toggleRaw("/api/sk5/fail-open", '{"arr": [1, {"fail_open": 1.0}], "fail_open": true}');
  console.log(`E10 key-in-nested-array: worker ${t.status} params=${JSON.stringify(t.params)} (Flask: 202 True)`);
  cell("E10 key inside nested array -> 202 True", t.status === 202 && t.params && t.params.fail_open === true);
  // E11: negative zero token "-0" is a plain int literal; value 0 -> False.
  t = await toggleRaw("/api/sk5/fail-open", '{"fail_open": -0}');
  console.log(`E11 fail_open -0: worker ${t.status} params=${JSON.stringify(t.params)} (Flask: 202 False)`);
  cell("E11 -0 token -> 202 False", t.status === 202 && t.params && t.params.fail_open === false);
  // E12: leading-zero token "01" is invalid JSON. BH-03(c): after the
  // R31-P2-1 fix the Worker envelope guard 400s here, like Flask.
  t = await toggleRaw("/api/sk5/fail-open", '{"fail_open": 01}');
  console.log(`E12 fail_open 01 (invalid JSON): worker ${t.status} (Flask: 400)`);
  cell("E12 invalid JSON -> 400", t.status === 400);
  // E13: array body — BH-03(c): fixed, Worker 400s like Flask.
  t = await toggleRaw("/api/sk5/fail-open", '[1, 2]');
  console.log(`E13 array body: worker ${t.status} (Flask: 400)`);
  cell("E13 array body -> 400", t.status === 400);
  // E14: string body — BH-03(c): fixed, Worker 400s like Flask.
  t = await toggleRaw("/api/sk5/fail-open", '"hello"');
  console.log(`E14 string body: worker ${t.status} (Flask: 400)`);
  cell("E14 string body -> 400", t.status === 400);
  // E15: empty body — BH-03(c): fixed, Worker 400s like Flask.
  t = await toggleRaw("/api/sk5/fail-open", '');
  console.log(`E15 empty body: worker ${t.status} (Flask: 400)`);
  cell("E15 empty body -> 400", t.status === 400);
  // E16: JSON null body — BH-03(c): fixed, Worker 400s like Flask.
  t = await toggleRaw("/api/sk5/fail-open", 'null');
  console.log(`E16 null body: worker ${t.status} (Flask: 400)`);
  cell("E16 null body -> 400", t.status === 400);
  // E17: create_server with invalid JSON — BH-03(c): fixed, 400.
  async function rawPost(path, raw) {
    const t = await req("POST", path, { rawBody: raw, headers: H });
    let params = null;
    if (t.json && t.json.cmd_id) {
      const rec = await kv.get(`cmd:${t.json.cmd_id}`, "json");
      params = rec ? rec.params : null;
    }
    return { status: t.status, params };
  }
  let u = await rawPost("/api/openvpn/server", '{"port": 01}');
  console.log(`E17 create_server invalid JSON: worker ${u.status} (Flask: 400)`);
  cell("E17 create_server invalid JSON -> 400", u.status === 400);
  // E18: create_user with non-JSON body — BH-03(c): fixed, 400.
  u = await rawPost("/api/openvpn/users", 'not json');
  console.log(`E18 create_user non-JSON: worker ${u.status} (Flask: 400)`);
  cell("E18 create_user non-JSON -> 400", u.status === 400);
  // E19: bare-action stop with garbage body — Flask ignores the body
  // entirely on this route, so both faces execute: agreement control.
  u = await rawPost("/api/openvpn/stop", 'garbage');
  console.log(`E19 stop garbage body: worker ${u.status} (Flask: 202, body ignored)`);
  cell("E19 stop garbage body -> Worker 202 (agreement, body ignored)", u.status === 202);
  // E20: bare-action sk5/enable with array body — agreement control.
  u = await rawPost("/api/sk5/enable", '[1]');
  console.log(`E20 sk5/enable array body: worker ${u.status} (Flask: 202, body ignored)`);
  cell("E20 sk5/enable array body -> Worker 202 (agreement, body ignored)", u.status === 202);

  const fails = RESULTS.filter(([, ok]) => !ok).length;
  console.log(`R31 edge (worker): ${RESULTS.length - fails}/${RESULTS.length}`);
  process.exit(fails);
}

main();

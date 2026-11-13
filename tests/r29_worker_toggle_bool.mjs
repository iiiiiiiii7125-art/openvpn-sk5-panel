// AUDIT-R29 Worker toggle-bool probe (r29_worker_toggle_bool.mjs) —
// cross-face behavioral consistency: POST /api/sk5/fail-open and
// /api/sk5/udp-over-tcp with non-boolean inputs. Flask rejects
// non-bool with 400 (_strict_bool/_toggle_value, R12-P2-1) and
// accepts 0/1; the Worker toggle used to read typeof with a terminal
// `: false` fallback plus an `enabled` fallback key (R29-P2-1).
// BH-03(c): after the R29-P2-1 fix this probe asserts the FIXED
// behavior — both faces agree (non-bool/non-0-1 -> 400, 1 -> true,
// missing key -> false, {enabled:true} on fail-open -> false, on
// udp-over-tcp -> true via the R12-P2-2 adjudicated fallback).
// T9 (added by the fix lane) pins that adjudicated fallback so a
// later round cannot "fix" it away. The Flask counterpart is
// tests/r29_flask_toggle_bool.py.
// T10–T13 (R30-P2-1 fix): JSON integer-floats. JSON.stringify(1.0)
// collapses to "1", so these cells send RAW bodies — after
// JSON.parse, 1.0 and 1 are the same number, but Flask rejects 1.0
// (isinstance float) while the Worker used to accept it
// (Number.isInteger(1.0) is true). The fixed Worker validates the
// raw token: `1`/`0` pass; `1.0`, `1e0` 400, like Flask.
// Usage: node tests/r29_worker_toggle_bool.mjs
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

async function req(method, path, { body, rawBody, headers = {} } = {}) {
  const h = { ...headers };
  let b;
  if (rawBody !== undefined) { b = rawBody; h["Content-Type"] = "application/json"; }
  else if (body !== undefined) { b = JSON.stringify(body); h["Content-Type"] = "application/json"; }
  const r = await worker.fetch(new Request(BASE + path, { method, headers: h, body: b }), env, {});
  const text = await r.text();
  let j = null;
  try { j = JSON.parse(text); } catch { /* non-json */ }
  return { status: r.status, json: j, text, headers: r.headers };
}

async function main() {
  const cookie = await (async () => {
    const r = await req("POST", "/api/login", {
      body: { password: "admin-pass-123" },
      headers: { "CF-Connecting-IP": "10.9.0.1" },
    });
    const m = (r.headers.get("Set-Cookie") || "").match(/panel_session=([^;]+)/);
    return m ? `panel_session=${m[1]}` : "";
  })();
  const H = { Cookie: cookie };
  // register node + save a stored sk5cfg so the toggle has host/port
  let r = await req("POST", "/api/nodes", { body: { name: "n1", panel_url: "https://n1.example:8443" }, headers: H });
  cell("W0 register node 201", r.status === 201, String(r.status));
  r = await req("POST", "/api/sk5", {
    body: { host: "proxy.example", port: 1001, username: "u", password: "p", enabled: false },
    headers: H,
  });
  cell("W0 sk5 save 202", r.status === 202, String(r.status));
  const cmdId = r.json && r.json.cmd_id;

  async function toggle(path, body) {
    const t = await req("POST", path, { body, headers: H });
    let params = null;
    if (t.json && t.json.cmd_id) {
      const rec = await kv.get(`cmd:${t.json.cmd_id}`, "json");
      params = rec ? rec.params : null;
    }
    return { status: t.status, params, body: t.json };
  }

  // T1: string "true" -> Flask 400; fixed Worker must 400 too.
  let t = await toggle("/api/sk5/fail-open", { fail_open: "true" });
  console.log(`T1 fail-open "true": worker status=${t.status} params=${JSON.stringify(t.params)} (Flask: 400)`);
  cell("T1 string true -> 400", t.status === 400);
  // T2: int 1 -> Flask True (200/202); fixed Worker must apply True.
  t = await toggle("/api/sk5/fail-open", { fail_open: 1 });
  console.log(`T2 fail-open 1: worker status=${t.status} params=${JSON.stringify(t.params)} (Flask: applied True)`);
  cell("T2 int 1 -> 202 True", t.status === 202 && t.params && t.params.fail_open === true);
  // T3: enabled fallback key -> Flask False (default, no fallback on
  // fail-open). Fixed Worker must NOT read `enabled` on this route.
  t = await toggle("/api/sk5/fail-open", { enabled: true });
  console.log(`T3 fail-open {enabled:true}: worker status=${t.status} params=${JSON.stringify(t.params)} (Flask: applied False)`);
  cell("T3 enabled-key -> 202 False (no fallback on fail-open)", t.status === 202 && t.params && t.params.fail_open === false);
  // T4: control, real bool false -> both False
  t = await toggle("/api/sk5/fail-open", { fail_open: false });
  console.log(`T4 fail-open false: worker status=${t.status} params=${JSON.stringify(t.params)} (Flask: applied False)`);
  cell("T4 bool false agrees (Worker False)", t.status === 202 && t.params && t.params.fail_open === false);
  // T5: udp-over-tcp string "true" -> Flask 400; fixed Worker must 400 too.
  t = await toggle("/api/sk5/udp-over-tcp", { udp_over_tcp: "true" });
  console.log(`T5 uot "true": worker status=${t.status} params=${JSON.stringify(t.params)} (Flask: 400)`);
  cell("T5 string true -> 400", t.status === 400);
  // T6: udp-over-tcp int 1 -> Flask True; fixed Worker must apply True.
  t = await toggle("/api/sk5/udp-over-tcp", { udp_over_tcp: 1 });
  console.log(`T6 uot 1: worker status=${t.status} params=${JSON.stringify(t.params)} (Flask: applied True)`);
  cell("T6 int 1 -> 202 True", t.status === 202 && t.params && t.params.udp_over_tcp === true);
  // T7: empty body -> both False (Flask default)
  t = await toggle("/api/sk5/fail-open", {});
  console.log(`T7 fail-open {}: worker status=${t.status} params=${JSON.stringify(t.params)} (Flask: applied False)`);
  cell("T7 empty body agrees (Worker False)", t.status === 202 && t.params && t.params.fail_open === false);
  // T8: string "false" -> Flask 400; fixed Worker must 400 too.
  t = await toggle("/api/sk5/fail-open", { fail_open: "false" });
  console.log(`T8 fail-open "false": worker status=${t.status} params=${JSON.stringify(t.params)} (Flask: 400)`);
  cell("T8 string false -> 400", t.status === 400);
  // T9 (fix-lane addition): udp-over-tcp {enabled:true} -> Flask 202
  // True via the R12-P2-2 adjudicated `enabled` fallback; the fixed
  // Worker must keep that fallback on THIS route only.
  t = await toggle("/api/sk5/udp-over-tcp", { enabled: true });
  console.log(`T9 uot {enabled:true}: worker status=${t.status} params=${JSON.stringify(t.params)} (Flask: applied True via adjudicated fallback)`);
  cell("T9 uot enabled-key -> 202 True (adjudicated fallback kept)", t.status === 202 && t.params && t.params.udp_over_tcp === true);

  // T10–T13 (R30-P2-1 fix): raw bodies — JSON.stringify would
  // collapse 1.0 to "1", so the literal must travel as raw text.
  async function toggleRaw(path, raw) {
    const r = await req("POST", path, { rawBody: raw, headers: H });
    return { status: r.status, json: r.json };
  }
  // T10: fail_open 1.0 -> Flask 400; fixed Worker must 400 too.
  t = await toggleRaw("/api/sk5/fail-open", '{"fail_open": 1.0}');
  console.log(`T10 fail-open 1.0: worker status=${t.status} (Flask: 400)`);
  cell("T10 fail-open 1.0 -> 400 (raw token, not plain int)", t.status === 400);
  // T11: udp-over-tcp 1.0 -> Flask 400; fixed Worker must 400 too.
  t = await toggleRaw("/api/sk5/udp-over-tcp", '{"udp_over_tcp": 1.0}');
  console.log(`T11 uot 1.0: worker status=${t.status} (Flask: 400)`);
  cell("T11 uot 1.0 -> 400 (raw token, not plain int)", t.status === 400);
  // T12: save-route port 1001.0 -> Flask 400; fixed Worker must 400 too.
  t = await req("POST", "/api/sk5", {
    rawBody: '{"host":"proxy.example","port":1001.0,"username":"u","password":"p","enabled":false}',
    headers: H,
  });
  console.log(`T12 save port 1001.0: worker status=${t.status} (Flask: 400)`);
  cell("T12 save port 1001.0 -> 400 (raw token, not plain int)", t.status === 400);
  // T13: fail_open 1e0 -> Flask parses 1e0 as float 1.0 -> 400; the
  // fixed Worker must 400 too (exponent is not a plain-int token).
  t = await toggleRaw("/api/sk5/fail-open", '{"fail_open": 1e0}');
  console.log(`T13 fail-open 1e0: worker status=${t.status} (Flask: 400)`);
  cell("T13 fail-open 1e0 -> 400 (exponent is not a plain-int token)", t.status === 400);

  const fails = RESULTS.filter(([, ok]) => !ok).length;
  console.log(`R29 worker-toggle-bool: ${RESULTS.length - fails}/${RESULTS.length} fixed-behavior cells pass, ${fails} failed`);
  process.exit(fails);
}
main();

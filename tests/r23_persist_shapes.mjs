// R23 Worker probe (r23_persist_shapes.mjs) — persisted-state shape matrix,
// Worker / KV face: every KV record x shape (missing / empty / corrupt /
// non-object / array) x reader. PASS = loud fail / honest degrade /
// repair; FAIL = silent data loss or silent misreport.
//
// W1 is the headline: loginfail:<ip> as a JSON ARRAY. recordLoginFailure
// does `rec.failures = [...]` on the array, then kvPutJson stringifies it
// — JSON.stringify drops extra props on arrays — so the failure count is
// silently discarded on every write-back and the IP can NEVER be locked
// out. Same hand-edit precondition class as R18/R19 (filed P2 there).
// W2 (string record) was updated by the BR fix: the old loud-500
// expectation pinned the defective behavior — a non-object record now
// resets to an empty counter (+ warn) and the failure is counted
// normally. W3 (failures-as-string) still throws inside
// recordLoginFailure and surfaces as a loud 500 via the top-level
// catch — fail-closed, recorded (Flask parity, R23 §2.8 matrix).
// Usage: node tests/r23_persist_shapes.mjs (relative import, same tree).
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

async function wrongLogin(ip) {
  return req("POST", "/api/login", {
    body: { password: "wrong-password" },
    headers: { "CF-Connecting-IP": ip },
  });
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

const IP1 = "203.0.113.11"; // loginfail = [] (array)
const IP2 = "203.0.113.12"; // loginfail = "x" (string)
const IP3 = "203.0.113.13"; // loginfail = {failures: "abc"}
const IP4 = "203.0.113.14"; // loginfail = normal object (control)

// Seed the shapes directly in KV (hand-edit simulation).
await kv.put("loginfail:" + IP1, JSON.stringify([]));
await kv.put("loginfail:" + IP2, JSON.stringify("x"));
await kv.put("loginfail:" + IP3, JSON.stringify({ failures: "abc", locked_until: 0 }));
await kv.put("loginfail:" + IP4, JSON.stringify({ failures: [], locked_until: 0 }));

// W1: array record — 6 wrong logins; a working lockout returns 429 by #5/#6.
const w1 = [];
for (let i = 0; i < 6; i++) w1.push((await wrongLogin(IP1)).status);
cell("W1-loginfail-array-locks-out",
  w1.includes(429),
  "6 wrong logins -> " + JSON.stringify(w1) + " (no 429 = lockout silently defeated)");

// W2: string record — BR fix changed this cell's expectation (same
// legitimate family as BN's Q5 update / BH-03(c)): the old 500 pinned
// the DEFECTIVE behavior (TypeError on a non-object record). The fix
// resets a non-object loginfail record to an empty counter (+ warn),
// so the wrong login is counted normally: 401 here, 429 by the 6th.
// Field-level damage (W3, failures as string) is unchanged: loud 500.
const w2 = await wrongLogin(IP2);
const w2rec = await kv.get("loginfail:" + IP2, "json");
cell("W2-loginfail-string-reset-and-counted",
  w2.status === 401 && w2rec && !Array.isArray(w2rec)
  && Array.isArray(w2rec.failures) && w2rec.failures.length === 1,
  "wrong login -> " + w2.status + " record=" + JSON.stringify(w2rec));

// W3: failures-as-string — same expectation (loud 500, fail-closed).
const w3 = await wrongLogin(IP3);
cell("W3-loginfail-failures-string-loud-not-bypass",
  w3.status === 500,
  "wrong login -> " + w3.status);

// W4: control — normal object record locks out on schedule.
const w4 = [];
for (let i = 0; i < 6; i++) w4.push((await wrongLogin(IP4)).status);
cell("W4-loginfail-object-control-locks-out",
  w4[4] === 429 || w4[5] === 429,
  "6 wrong logins -> " + JSON.stringify(w4));

// W5: node record non-object -> listNodes skips it, /api/nodes 200.
await kv.put("node:wk1", JSON.stringify({
  name: "wk1", token_hash: "aa", panel_url: "", created_at: "2026-01-01T00:00:00Z",
}));
await kv.put("node:bad", JSON.stringify("not-an-object"));
const admin = await loginAsAdmin("203.0.113.20");
const w5 = await req("GET", "/api/nodes", { headers: { Cookie: admin } });
cell("W5-node-record-string-skipped",
  w5.status === 200 && Array.isArray(w5.json?.nodes)
  && w5.json.nodes.length === 1 && w5.json.nodes[0].name === "wk1",
  "/api/nodes -> " + w5.status + " nodes=" + JSON.stringify(w5.json?.nodes));

// W6: status snapshot non-object -> compat /api/status 200, no crash.
await kv.put("status:wk1", JSON.stringify("not-an-object"));
const w6 = await req("GET", "/api/status?node=wk1", { headers: { Cookie: admin } });
cell("W6-status-snapshot-string-200",
  w6.status === 200,
  "/api/status -> " + w6.status);

// W7: session record non-object -> requireAdmin 401, no crash.
const w7 = await req("GET", "/api/nodes",
  { headers: { Cookie: "panel_session=deadbeef-deadbeef-deadbeef-deadbeef" } });
await kv.put("session:deadbeef-deadbeef-deadbeef-deadbeef", JSON.stringify("x"));
const w7b = await req("GET", "/api/nodes",
  { headers: { Cookie: "panel_session=deadbeef-deadbeef-deadbeef-deadbeef" } });
cell("W7-session-record-string-401",
  w7.status === 401 && w7b.status === 401,
  "missing -> " + w7.status + ", string -> " + w7b.status);

// W8: sk5cfg non-object -> compat toggle must 400 honestly ("save full
// config first"): stored.host is undefined on a string record.
await kv.put("sk5cfg:wk1", JSON.stringify("not-an-object"));
const w8 = await req("POST", "/api/sk5/fail-open",
  { body: { node: "wk1", fail_open: true }, headers: { Cookie: admin } });
cell("W8-sk5cfg-string-toggle-400",
  w8.status === 400,
  "/api/sk5/fail_open -> " + w8.status + " " + JSON.stringify(w8.json));

// W9: servercfg non-object -> sk5 save UDP guard reads .proto safely.
await kv.put("servercfg:wk1", JSON.stringify("not-an-object"));
const w9 = await req("POST", "/api/sk5",
  { body: { node: "wk1", host: "proxy.example", port: 1080 },
    headers: { Cookie: admin } });
cell("W9-servercfg-string-no-crash",
  w9.status === 400 || w9.status === 202,
  "/api/sk5 save -> " + w9.status + " " + JSON.stringify(w9.json));

const fails = RESULTS.filter(([, ok]) => !ok).length;
console.log(`R23 worker: ${RESULTS.length - fails}/${RESULTS.length} PASS`);
process.exit(fails);

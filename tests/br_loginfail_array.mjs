// BR probe (br_loginfail_array.mjs) — R23-P2-4 fix verification:
// loginfail:<ip> as a JSON ARRAY (or other non-object) must NOT silently
// defeat the login lockout. Pre-fix: recordLoginFailure hung a `failures`
// property on the array, JSON.stringify dropped it on write-back, the
// failure count reset to 0 every time — 6 wrong logins -> [401 x6], no 429.
// Post-fix: kvLoginFailRecord normalizes any non-object/array record to a
// fresh {failures: [], locked_until: 0} (+ console.warn with key + typeof,
// never record content) at BOTH read points (loginLockedUntil and
// recordLoginFailure); null/undefined is the normal first-failure state.
// Field-level damage (failures not an array) is deliberately NOT normalized
// here — Flask parity is loud 500 (R23 §2.8 matrix), see B8.
// Usage: node tests/br_loginfail_array.mjs (relative import, same tree).
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
async function rightLogin(ip) {
  return req("POST", "/api/login", {
    body: { password: "admin-pass-123" },
    headers: { "CF-Connecting-IP": ip },
  });
}
async function sixWrong(ip) {
  const out = [];
  for (let i = 0; i < 6; i++) out.push((await wrongLogin(ip)).status);
  return out;
}
const EXPECT_6 = JSON.stringify([401, 401, 401, 401, 401, 429]);

// B1: headline — empty array record locks out on schedule.
await kv.put("loginfail:203.0.113.11", JSON.stringify([]));
const b1 = await sixWrong("203.0.113.11");
cell("B1-loginfail-array-locks-out",
  JSON.stringify(b1) === EXPECT_6,
  "6 wrong logins -> " + JSON.stringify(b1) + " (pre-fix: [401 x6], no 429)");

// B2: non-empty array record — same reset, same lockout.
await kv.put("loginfail:203.0.113.12", JSON.stringify(["junk", 123]));
const b2 = await sixWrong("203.0.113.12");
cell("B2-loginfail-nonempty-array-locks-out",
  JSON.stringify(b2) === EXPECT_6,
  "6 wrong logins -> " + JSON.stringify(b2));

// B3: string record — reset to a real object, lockout works, and the
// repaired KV record is a plain object with a live lock (not a string).
await kv.put("loginfail:203.0.113.13", JSON.stringify("x"));
const b3 = await sixWrong("203.0.113.13");
const b3rec = await kv.get("loginfail:203.0.113.13", "json");
cell("B3-loginfail-string-locks-out-and-repairs",
  JSON.stringify(b3) === EXPECT_6
  && b3rec && !Array.isArray(b3rec) && typeof b3rec === "object"
  && Array.isArray(b3rec.failures) && b3rec.locked_until > Date.now(),
  "6 wrong logins -> " + JSON.stringify(b3)
  + " record=" + JSON.stringify(b3rec));

// B4: missing record (normal first-failure path) — control.
const b4 = await sixWrong("203.0.113.14");
cell("B4-loginfail-missing-control-locks-out",
  JSON.stringify(b4) === EXPECT_6,
  "6 wrong logins -> " + JSON.stringify(b4));

// B5: well-formed object record — control.
await kv.put("loginfail:203.0.113.15", JSON.stringify({ failures: [], locked_until: 0 }));
const b5 = await sixWrong("203.0.113.15");
cell("B5-loginfail-object-control-locks-out",
  JSON.stringify(b5) === EXPECT_6,
  "6 wrong logins -> " + JSON.stringify(b5));

// B6: lock lasts 15 minutes — the 429 carries Retry-After ~900 and the
// stored locked_until is ~900s in the future.
await kv.put("loginfail:203.0.113.16", JSON.stringify([]));
await sixWrong("203.0.113.16");
const b6r = await wrongLogin("203.0.113.16");
const b6rec = await kv.get("loginfail:203.0.113.16", "json");
const retryAfter = Number(b6r.headers.get("Retry-After"));
const lockMsLeft = b6rec.locked_until - Date.now();
cell("B6-lock-is-15-minutes",
  b6r.status === 429 && retryAfter >= 895 && retryAfter <= 900
  && lockMsLeft >= 890000 && lockMsLeft <= 900000,
  "429 Retry-After=" + retryAfter + " locked_until-now=" + lockMsLeft + "ms");

// B7: pre-seeded 2 failures inside the window are preserved — 3 more
// wrong logins reach 5 and lock on the 4th attempt of this run.
const now = Date.now();
await kv.put("loginfail:203.0.113.17", JSON.stringify({
  failures: [now - 60000, now - 30000], locked_until: 0,
}));
const b7 = [];
for (let i = 0; i < 4; i++) b7.push((await wrongLogin("203.0.113.17")).status);
cell("B7-preseeded-failures-count-toward-lock",
  JSON.stringify(b7) === JSON.stringify([401, 401, 401, 429]),
  "4 wrong logins -> " + JSON.stringify(b7));

// B8: field-level damage (failures as string) is NOT normalized — Flask
// parity is loud 500 (R23 §2.8 matrix); must not 200/401-pretend-normal.
await kv.put("loginfail:203.0.113.18", JSON.stringify({ failures: "abc", locked_until: 0 }));
const b8 = await wrongLogin("203.0.113.18");
cell("B8-failures-string-loud-not-bypass",
  b8.status === 500,
  "wrong login -> " + b8.status);

// B9: an already-locked record blocks both right and wrong passwords.
await kv.put("loginfail:203.0.113.19", JSON.stringify({ failures: [], locked_until: Date.now() + 900000 }));
const b9right = await rightLogin("203.0.113.19");
const b9wrong = await wrongLogin("203.0.113.19");
cell("B9-locked-record-blocks-both",
  b9right.status === 429 && b9wrong.status === 429,
  "right -> " + b9right.status + ", wrong -> " + b9wrong.status);

// B10: successful login clears the loginfail key (existing behavior).
await kv.put("loginfail:203.0.113.20", JSON.stringify({ failures: [Date.now() - 1000], locked_until: 0 }));
const b10 = await rightLogin("203.0.113.20");
const b10gone = await kv.get("loginfail:203.0.113.20", "json");
cell("B10-success-clears-loginfail",
  b10.status === 200 && b10gone === null,
  "right login -> " + b10.status + ", record after=" + JSON.stringify(b10gone));

// B11: object missing locked_until only — missing field is filled, the
// 2 seeded failures are kept (not wiped by a whole-record rebuild).
await kv.put("loginfail:203.0.113.21", JSON.stringify({ failures: [Date.now() - 60000, Date.now() - 30000] }));
const b11 = [];
for (let i = 0; i < 4; i++) b11.push((await wrongLogin("203.0.113.21")).status);
cell("B11-missing-field-filled-failures-kept",
  JSON.stringify(b11) === JSON.stringify([401, 401, 401, 429]),
  "4 wrong logins -> " + JSON.stringify(b11));

const fails = RESULTS.filter(([, ok]) => !ok).length;
console.log(`BR loginfail: ${RESULTS.length - fails}/${RESULTS.length} PASS`);
process.exit(fails);

// R27 probe (r27_worker_dangling_queue.mjs) -- Worker queue/sent lists
// had no TTL while cmd records expire after 7 days (CMD_TTL_S).
// A queued/sent command whose record expired was a DANGLING id: the
// sweep only iterates live cmd:* records, so it could never see it;
// the next poll silently dropped it (dispatch loop `if (!cmd) continue`
// + conditional clear / stillSent rebuild) with no failed marking,
// no audit row, and no console.warn -- the operator's cmd_get 404s
// ("命令不存在") with no way to tell "expired" from "never existed".
// Flask side has no equivalent: agent_queue.json never expires
// (BN/BQ cover corruption, not expiry).
//
// FIXED (R27-P2-2): (a) the poll's dispatch / timeout loops console.warn
// naming a dangling id when they meet one; (b) every queue:/sent:
// write carries the same expirationTtl: CMD_TTL_S, so a node's whole
// queue state lives and dies together (each poll rewrites and refreshes
// the TTL; live nodes unaffected).
//
// Cells:
//   Q1 queued cmd whose record expired: poll dispatches nothing,
//      queue drops the id.
//   Q2 FLIPPED per BH-03(c): a console.warn names the dangling id.
//   Q3 cmd_get 404s after the drop.
//   Q4 sent cmd whose record expired: next poll drops the sent copy,
//      no requeue, no failed marking -- but a warn names the id
//      (FLIPPED per BH-03(c): the old "no warn" pinned the defect).
//   Q5 FLIPPED per BH-03(c): the queue:/sent: writes now carry
//      expirationTtl while cmd: writes carry CMD_TTL_S (the old
//      "no expirationTtl" pinned the asymmetry). The match regex is
//      dot-all non-greedy so multi-line calls (the poll's conditional
//      clear) are inspected in full -- the old [^)]* regex truncated
//      at the first ")" and never saw that call's options.
// Run: node tests/r27_worker_dangling_queue.mjs
// Exit code = FAIL count.
import worker from "../cloudflare/src/index.js";
import { readFileSync } from "node:fs";

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

async function main() {
  const warnings = [];
  const origWarn = console.warn;
  console.warn = (...a) => { warnings.push(a.join(" ")); origWarn(...a); };

  let r = await req("POST", "/api/login", {
    body: { password: "admin-pass-123" },
    headers: { "CF-Connecting-IP": "10.9.0.1" },
  });
  const m = (r.headers.get("Set-Cookie") || "").match(/panel_session=([^;]+)/);
  const adminCookie = m ? `panel_session=${m[1]}` : "";
  r = await req("POST", "/api/nodes", {
    body: { name: "wk1", panel_url: "" }, headers: { Cookie: adminCookie },
  });
  const token = r.json?.token;

  // --- Q1/Q2/Q3: dangling queued id
  r = await req("POST", "/api/cmd", {
    body: { node: "wk1", action: "get_status", params: {} },
    headers: { Cookie: adminCookie },
  });
  const cmdId1 = r.json?.cmd_id;
  // Simulate the 7-day CMD_TTL_S expiry: the record is gone, the
  // queue list (no TTL) still holds the id.
  await kv.delete(`cmd:${cmdId1}`);
  warnings.length = 0;
  r = await req("POST", "/api/agent/poll", {
    body: { node_name: "wk1" },
    headers: { Authorization: "Bearer " + token },
  });
  const queueAfter = await kv.get("queue:wk1", "json");
  cell("Q1 expired queued cmd: poll dispatches nothing, queue id "
       + "dropped (warn covered by Q2)",
    r.status === 200 && (r.json?.commands || []).length === 0
    && Array.isArray(queueAfter) && !queueAfter.includes(cmdId1),
    `status=${r.status} cmds=${(r.json?.commands || []).length} queue=${JSON.stringify(queueAfter)}`);
  cell("Q2 warn: a console.warn names the dangling id",
    warnings.some((w) => w.includes(cmdId1)),
    `warnings=${JSON.stringify(warnings)}`);
  r = await req("GET", `/api/cmd/${cmdId1}`, { headers: { Cookie: adminCookie } });
  cell("Q3 cmd_get 404s after the silent drop",
    r.status === 404, String(r.status));

  // --- Q4: dangling sent entry
  r = await req("POST", "/api/cmd", {
    body: { node: "wk1", action: "get_status", params: {} },
    headers: { Cookie: adminCookie },
  });
  const cmdId2 = r.json?.cmd_id;
  r = await req("POST", "/api/agent/poll", {
    body: { node_name: "wk1" },
    headers: { Authorization: "Bearer " + token },
  });
  const sentBefore = await kv.get("sent:wk1", "json");
  const dispatched = (r.json?.commands || []).some((x) => x.id === cmdId2)
    && Array.isArray(sentBefore) && sentBefore.some((e) => e.id === cmdId2);
  await kv.delete(`cmd:${cmdId2}`); // record TTLs; sent copy (no TTL) stays
  warnings.length = 0;
  r = await req("POST", "/api/agent/poll", {
    body: { node_name: "wk1" },
    headers: { Authorization: "Bearer " + token },
  });
  const sentAfter = await kv.get("sent:wk1", "json");
  cell("Q4 expired sent cmd: next poll drops the sent copy, "
       + "no requeue, no failed marking -- but a warn names the id",
    dispatched && r.status === 200
    && Array.isArray(sentAfter) && !sentAfter.some((e) => e.id === cmdId2)
    && warnings.some((w) => w.includes(cmdId2)),
    `dispatched=${dispatched} sentAfter=${JSON.stringify(sentAfter)} warnings=${JSON.stringify(warnings)}`);

  // --- Q5: the TTL asymmetry is closed, by source. The regex is
  // dot-all non-greedy so multi-line kvPutJson calls are matched in
  // full (the poll's conditional clear spans 5 lines).
  const src = readFileSync(new URL("../cloudflare/src/index.js", import.meta.url), "utf-8");
  const queuePuts = [...src.matchAll(/kvPutJson\(\s*env,\s*`queue:\$\{[^}]+\}`[\s\S]*?\);/g)]
    .map((x) => x[0]);
  const sentPuts = [...src.matchAll(/kvPutJson\(\s*env,\s*`sent:\$\{[^}]+\}`[\s\S]*?\);/g)]
    .map((x) => x[0]);
  const cmdPuts = [...src.matchAll(/kvPutJson\(\s*env,\s*`cmd:\$\{[^}]+\}`[\s\S]*?\);/g)]
    .map((x) => x[0]);
  cell("Q5 queue:/sent: writes carry expirationTtl, same as cmd: writes",
    queuePuts.length > 0 && queuePuts.every((s) => s.includes("expirationTtl"))
    && sentPuts.length > 0 && sentPuts.every((s) => s.includes("expirationTtl"))
    && cmdPuts.length > 0 && cmdPuts.every((s) => s.includes("expirationTtl")),
    `queue puts=${queuePuts.length} sent puts=${sentPuts.length} cmd puts=${cmdPuts.length}`);

  console.warn = origWarn;
  const fails = RESULTS.filter(([, ok]) => !ok).length;
  console.log(`r27_worker_dangling_queue: ${RESULTS.length - fails}/${RESULTS.length} PASS`);
  process.exit(fails);
}

main();

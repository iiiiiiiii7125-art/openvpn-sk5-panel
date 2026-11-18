// R47 integration check: does any Worker status-read path re-queue a sent
// command the way Flask's GET /api/cmd/<id> did before Fix-BB (R47-L5-1)?
//
// Flask pre-BB: GET /api/cmd/<id> ran _requeue_stale_sent, so the UI's own
// waitCmd polling (every 2s) flipped a still-executing slow command
// sent -> queued at 120s, its late report 409'd, and after 3 retries the
// panel called it abandoned while the agent had run it.
// Worker: handleGetCmd (GET /api/cmd/:id) also runs _sweepWorkerCmds --
// but the sweep only timeout-handles sent records NOT referenced by the
// sent:<node> copy (orphan healing, R18-P2-2); normally-delivered commands
// are in the copy and must be skipped. This probe proves that behaviorally:
//   G1  aged sent install_prereqs (non-safe) WITH sent-copy entry:
//       3x GET must leave it sent (retries untouched).
//   G2  same for get_status (safe action): 3x GET must leave it sent.
//   G3  late report for the aged install_prereqs must be accepted (200,
//       status done), not 409.
//   G4  ORPHAN (sent record, sent-copy entry missing): aged get_status
//       must stay sent after GET -- the read path heals the copy, it
//       does not judge the timeout. FAILS on 1.0.3 (GET re-queued it).
//   G5  ORPHAN: aged install_prereqs must stay sent after GET (not
//       failed by the read). FAILS on 1.0.3 (GET failed it).
//   G6  The poll path still owns the sweep: the next agent poll must
//       timeout-handle the restored orphans (safe -> requeued, non-safe
//       -> failed), proving the sweep moved to poll, not away.
// Aging is by direct KV edit (sent_at = now - 130s); no real waiting.
// Usage: node tests/r47_int_worker_getcmd_sweep.mjs (exit = FAIL count)
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
async function kvJson(key) { return env.PANEL_KV.get(key, "json"); }
async function kvPutJson(key, v) { await env.PANEL_KV.put(key, JSON.stringify(v)); }
async function ageCmd(id, ms = 130000) {
  const cmd = await kvJson(`cmd:${id}`);
  cmd.sent_at = Date.now() - ms;
  await kvPutJson(`cmd:${id}`, cmd);
  const sent = (await kvJson("sent:lightsail")) || [];
  for (const e of sent) if (e.id === id) e.sent_at = Date.now() - ms;
  await kvPutJson("sent:lightsail", sent);
}
async function orphanCmd(id, ms = 130000) {
  const cmd = await kvJson(`cmd:${id}`);
  cmd.sent_at = Date.now() - ms;
  await kvPutJson(`cmd:${id}`, cmd);
  const sent = (await kvJson("sent:lightsail")) || [];
  await kvPutJson("sent:lightsail", sent.filter((e) => e.id !== id));
}

const cookie = await login();
cell("setup: login 200", !!cookie);
const auth = { Cookie: cookie };
const reg = await req("POST", "/api/nodes", { body: { name: "lightsail", panel_url: "" }, headers: auth });
cell("setup: register lightsail 201", reg.status === 201, `status=${reg.status}`);
const nodeToken = reg.j && reg.j.token ? reg.j.token : "";
const bearer = { Authorization: `Bearer ${nodeToken}` };

// Enqueue one slow non-safe + one safe command, deliver via agent poll.
const c1 = await req("POST", "/api/cmd", { body: { node: "lightsail", action: "install_prereqs", params: {} }, headers: auth });
const c2 = await req("POST", "/api/cmd", { body: { node: "lightsail", action: "get_status", params: {} }, headers: auth });
cell("setup: enqueue install_prereqs + get_status", c1.status === 202 && c2.status === 202,
  `c1=${c1.status} c2=${c2.status}`);
const idSlow = c1.j.cmd_id;
const idSafe = c2.j.cmd_id;
const pol = await req("POST", "/api/agent/poll", { body: {}, headers: bearer });
cell("setup: poll delivers both", pol.status === 200 && Array.isArray(pol.j.commands) && pol.j.commands.length === 2,
  `status=${pol.status} n=${pol.j && pol.j.commands ? pol.j.commands.length : "?"}`);
const sentCopy = (await kvJson("sent:lightsail")) || [];
cell("setup: sent copy holds both ids", sentCopy.some((e) => e.id === idSlow) && sentCopy.some((e) => e.id === idSafe),
  `sent=${JSON.stringify(sentCopy.map((e) => e.id))}`);

// Simulate 130 s of execution (no real wait).
await ageCmd(idSlow);
await ageCmd(idSafe);

// G1: UI polling must not re-queue the still-executing non-safe command.
let g1ok = true;
let g1detail = "";
for (let i = 0; i < 3; i++) {
  const g = await req("GET", `/api/cmd/${idSlow}`, { headers: auth });
  const cur = await kvJson(`cmd:${idSlow}`);
  if (g.j.status !== "sent" || cur.status !== "sent" || (cur.retries || 0) !== 0) {
    g1ok = false;
    g1detail = `poll#${i + 1}: GET status=${g.j.status} record=${cur.status} retries=${cur.retries}`;
    break;
  }
  g1detail = `3x GET: status=sent retries=${cur.retries || 0}`;
}
cell("G1 GET x3 leaves aged sent install_prereqs sent (no re-queue)", g1ok, g1detail);

// G2: same for the safe action.
let g2ok = true;
let g2detail = "";
for (let i = 0; i < 3; i++) {
  const g = await req("GET", `/api/cmd/${idSafe}`, { headers: auth });
  const cur = await kvJson(`cmd:${idSafe}`);
  if (g.j.status !== "sent" || cur.status !== "sent" || (cur.retries || 0) !== 0) {
    g2ok = false;
    g2detail = `poll#${i + 1}: GET status=${g.j.status} record=${cur.status} retries=${cur.retries}`;
    break;
  }
  g2detail = `3x GET: status=sent retries=${cur.retries || 0}`;
}
cell("G2 GET x3 leaves aged sent get_status sent (no re-queue)", g2ok, g2detail);

// G3: the late report for the aged slow command must be accepted.
const rep = await req("POST", "/api/agent/report", {
  body: { cmd_id: idSlow, ok: true, result: { installed: true } },
  headers: bearer,
});
const after = await kvJson(`cmd:${idSlow}`);
cell("G3 late report for aged sent command accepted (200, done)", rep.status === 200 && after.status === "done",
  `report=${rep.status} record=${after.status} body=${rep.text.slice(0, 80)}`);

// G4/G5: orphan boundary -- sent record with NO sent-copy entry.
const c3 = await req("POST", "/api/cmd", { body: { node: "lightsail", action: "get_status", params: {} }, headers: auth });
const c4 = await req("POST", "/api/cmd", { body: { node: "lightsail", action: "install_prereqs", params: {} }, headers: auth });
const idOrphanSafe = c3.j.cmd_id;
const idOrphanSlow = c4.j.cmd_id;
const pol2 = await req("POST", "/api/agent/poll", { body: {}, headers: bearer });
// The first get_status (idSafe, aged 130 s, still in the sent copy) is
// timeout-handled by THIS poll's own timeout loop: safe action ->
// re-queued and re-delivered in the same poll. That is the poll path
// owning the sweep (designed), so expect 3 deliveries here.
const delivered2 = Array.isArray(pol2.j.commands) ? pol2.j.commands.map((c) => c.id) : [];
cell("setup: poll delivers orphan pair (+ aged safe re-delivery)", pol2.status === 200
  && delivered2.includes(idOrphanSafe) && delivered2.includes(idOrphanSlow) && delivered2.includes(idSafe),
  `status=${pol2.status} n=${delivered2.length}`);
await orphanCmd(idOrphanSafe);
await orphanCmd(idOrphanSlow);
// G4: orphan safe action -- GET must NOT re-queue it; it heals the copy.
const g4 = await req("GET", `/api/cmd/${idOrphanSafe}`, { headers: auth });
const cur4 = await kvJson(`cmd:${idOrphanSafe}`);
const sentAfter4 = (await kvJson("sent:lightsail")) || [];
cell("G4 GET leaves aged orphan get_status sent (heals copy, no re-queue)",
  g4.j.status === "sent" && cur4.status === "sent" && (cur4.retries || 0) === 0
  && sentAfter4.some((e) => e.id === idOrphanSafe),
  `GET status=${g4.j.status} record=${cur4.status} retries=${cur4.retries} copy-restored=${sentAfter4.some((e) => e.id === idOrphanSafe)}`);
// G5: orphan non-safe action -- GET must NOT fail it.
const g5 = await req("GET", `/api/cmd/${idOrphanSlow}`, { headers: auth });
const cur5 = await kvJson(`cmd:${idOrphanSlow}`);
const sentAfter5 = (await kvJson("sent:lightsail")) || [];
cell("G5 GET leaves aged orphan install_prereqs sent (no false failed)",
  g5.j.status === "sent" && cur5.status === "sent"
  && sentAfter5.some((e) => e.id === idOrphanSlow),
  `GET status=${g5.j.status} record=${cur5.status} copy-restored=${sentAfter5.some((e) => e.id === idOrphanSlow)}`);
// G6: the next agent poll -- alive, asking for work -- timeout-handles
// the restored orphans: safe -> requeued (+re-delivered), non-safe ->
// failed. The sweep lives on the poll path.
const pol3 = await req("POST", "/api/agent/poll", { body: {}, headers: bearer });
const cur6safe = await kvJson(`cmd:${idOrphanSafe}`);
const cur6slow = await kvJson(`cmd:${idOrphanSlow}`);
const delivered3 = Array.isArray(pol3.j.commands) ? pol3.j.commands.map((c) => c.id) : [];
cell("G6 next poll timeout-handles restored orphans (safe requeued, non-safe failed)",
  pol3.status === 200 && cur6safe.status === "sent" && delivered3.includes(idOrphanSafe)
  && cur6slow.status === "failed",
  `poll=${pol3.status} safe=${cur6safe.status} redelivered=${delivered3.includes(idOrphanSafe)} slow=${cur6slow.status}`);

const pass = RESULTS.filter(([, ok]) => ok).length;
console.log(`TOTAL ${RESULTS.length} PASS ${pass} FAIL ${FAILURES.length}`);
process.exit(FAILURES.length ? 1 : 0);

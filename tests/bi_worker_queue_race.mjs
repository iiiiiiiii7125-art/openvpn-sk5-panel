// BI Worker probe (bi_worker_queue_race.mjs) — R18-P2-1 修复后行为：
// poll 窗口内入队的命令不得丢失（条件式清空＋孤儿回收）。
// 与 R18 复现探针不同：本探针断言修复后行为（PASS = 正确），R18 的
// r18_worker_queue_race.mjs 断言缺陷复现（修复后 RACE-02/05 翻红属预期）。
// Usage: node tests/bi_worker_queue_race.mjs  (exit code = FAIL count)
// Import 用相对路径，指向同树 cloudflare/src/index.js，不依赖 /tmp 副本。
import worker from "../cloudflare/src/index.js";

class MockKV {
  constructor() {
    this.store = new Map();
    this.intercept = null; // async hook: runs once on next get("queue:wk1")
  }
  async get(key, type) {
    const v = this.store.get(key); // 先快照：hook 跑完后仍返回旧值
    if (this.intercept && key === "queue:wk1") {
      const fn = this.intercept;
      this.intercept = null;
      await fn();
    }
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

async function enqueue(adminCookie, node, action, params = {}) {
  const r = await req("POST", "/api/cmd", {
    body: { node, action, params },
    headers: { Cookie: adminCookie },
  });
  return r.json?.cmd_id;
}

async function getCmd(adminCookie, id) {
  const r = await req("GET", `/api/cmd/${id}`, { headers: { Cookie: adminCookie } });
  return r.json;
}

async function main() {
  const adminCookie = await loginAsAdmin("10.9.0.1");
  cell("BI-RACE-00 admin session obtained", adminCookie.length > 0);
  let r = await req("POST", "/api/nodes", {
    body: { name: "wk1", panel_url: "" }, headers: { Cookie: adminCookie },
  });
  const token = r.json?.token;
  cell("BI-RACE-00b register node 201", r.status === 201 && !!token, `${r.status}`);

  // A 先入队；B 在 poll 读队列之后、清队列之前入队（确定性交错）。
  // 修复后 B 不得丢失：同轮 poll 经孤儿回收下发，或下一轮 poll 下发。
  const idA = await enqueue(adminCookie, "wk1", "get_status");
  cell("BI-RACE-01 enqueue A queued", !!idA, `${idA}`);
  let idB = null;
  kv.intercept = async () => {
    idB = await enqueue(adminCookie, "wk1", "get_status");
  };
  const p1 = await poll(token);
  const gotP1 = (p1.json?.commands || []).map((c) => c.id);
  cell("BI-RACE-02 poll 1 dispatches A", gotP1.includes(idA),
    `dispatched=${JSON.stringify(gotP1)}`);
  cell("BI-RACE-03 B was enqueued during poll", !!idB, `${idB}`);

  // B 在 poll 1 或之后 3 轮内必须被下发（不丢失）；记录不得卡 queued。
  const seen = new Set(gotP1);
  for (let i = 0; i < 3 && !seen.has(idB); i++) {
    const p = await poll(token);
    for (const c of p.json?.commands || []) seen.add(c.id);
  }
  cell("BI-RACE-04 B dispatched within poll 1 + 3 later polls (NOT lost)",
    seen.has(idB), seen.has(idB) ? "B dispatched" : "B stuck");
  const cmdB = await getCmd(adminCookie, idB);
  cell("BI-RACE-05 B record reached sent (not stuck queued)",
    cmdB?.status === "sent", `status=${cmdB?.status}`);
  const queueNow = await kv.get("queue:wk1", "json");
  cell("BI-RACE-06 queue array no longer references dispatched B",
    Array.isArray(queueNow) && !queueNow.includes(idB),
    `queue=${JSON.stringify(queueNow)}`);

  // 对照：poll 完成后再入队 C，下一轮 poll 正常取到。
  const idC = await enqueue(adminCookie, "wk1", "get_status");
  const pC = await poll(token);
  cell("BI-RACE-07 control: enqueue after poll dispatches normally",
    (pC.json?.commands || []).some((c) => c.id === idC), `${idC}`);

  // 孤儿回收：直接种一个孤儿——D 入队后把队列数组清空（模拟丢失的 id），
  // 下一轮 poll 的 sweep 必须把它捞回来并下发。
  const idD = await enqueue(adminCookie, "wk1", "get_status");
  await kv.put("queue:wk1", JSON.stringify([]));
  const pD = await poll(token);
  cell("BI-RACE-08 orphan queued cmd re-enqueued and dispatched by next poll",
    (pD.json?.commands || []).some((c) => c.id === idD), `${idD}`);
  const cmdD = await getCmd(adminCookie, idD);
  cell("BI-RACE-08b orphan D record reached sent",
    cmdD?.status === "sent", `status=${cmdD?.status}`);

  // 孤儿 sent 恢复：E 下发后把 sent 副本清空（记录仍 sent、未超时），
  // 下一轮 poll 必须把 sent 副本恢复，且不得重复下发 E。
  const idE = await enqueue(adminCookie, "wk1", "get_status");
  await poll(token); // dispatch E -> sent
  await kv.put("sent:wk1", JSON.stringify([]));
  const pE = await poll(token);
  const sentAfter = await kv.get("sent:wk1", "json");
  cell("BI-RACE-09 orphan sent copy restored by next poll",
    Array.isArray(sentAfter) && sentAfter.some((e) => e.id === idE),
    `sent=${JSON.stringify(sentAfter)}`);
  cell("BI-RACE-09b orphan sent cmd NOT redispatched while unexpired",
    !(pE.json?.commands || []).some((c) => c.id === idE));
  const cmdE = await getCmd(adminCookie, idE);
  cell("BI-RACE-09c orphan sent record still sent (not failed)",
    cmdE?.status === "sent", `status=${cmdE?.status}`);

  // 孤儿 sent＋数值型过期 sent_at（SAFE 动作）：sweep 走超时路径重投＋重发。
  const idF = await enqueue(adminCookie, "wk1", "get_status");
  await poll(token); // dispatch F -> sent
  const stale = Date.now() - 130000;
  await kv.put("sent:wk1", JSON.stringify([]));
  const recF = await kv.get("cmd:" + idF, "json");
  recF.sent_at = stale;
  await kv.put("cmd:" + idF, JSON.stringify(recF));
  const pF = await poll(token);
  const cmdF = await getCmd(adminCookie, idF);
  cell("BI-RACE-10 orphan sent with numeric stale sent_at (safe): requeued+redispatched, retries=1",
    cmdF?.status === "sent" && cmdF?.retries === 1 &&
    (pF.json?.commands || []).some((c) => c.id === idF),
    `status=${cmdF?.status} retries=${cmdF?.retries}`);

  const fails = RESULTS.filter(([, ok]) => !ok).length;
  console.log(`\nTOTAL ${RESULTS.length} cells, FAIL ${fails}: ${RESULTS.filter(([, ok]) => !ok).map(([n]) => n).join(", ")}`);
  process.exit(fails);
}

main().catch((e) => { console.error(e); process.exit(99); });

// R18 Worker probe (r18_worker_queue_race.mjs) — Worker 面 queue:<name> 的
// read-modify-write 竞态：handleAgentPoll 读队列→处理→末尾无条件写 []，
// enqueueCommand 读队列→push→写回；两者无锁、无 CAS、无版本号。
// 若下发（enqueue）的写落在 poll 的清队列写之前，该命令 id 永久丢失：
// cmd 记录仍为 queued，但没有任何队列数组再引用它，之后任意多轮 poll
// 都取不到它，也无任何孤儿回收路径（_requeue 只处理 sent 态）。
// Usage: node tests/r18_worker_queue_race.mjs  (exit code = FAIL count)
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
  cell("RACE-00 admin session obtained", adminCookie.length > 0);
  let r = await req("POST", "/api/nodes", {
    body: { name: "wk1", panel_url: "" }, headers: { Cookie: adminCookie },
  });
  const token = r.json?.token;
  cell("RACE-00b register node 201", r.status === 201 && !!token, `${r.status}`);

  // A 先入队；B 在 poll 读队列之后、清队列之前入队（确定性交错）。
  const idA = await enqueue(adminCookie, "wk1", "get_status");
  cell("RACE-01 enqueue A queued", !!idA, `${idA}`);
  let idB = null;
  kv.intercept = async () => {
    idB = await enqueue(adminCookie, "wk1", "get_status");
  };
  const p1 = await poll(token);
  const gotA = (p1.json?.commands || []).map((c) => c.id);
  cell("RACE-02 poll dispatches A only", gotA.includes(idA) && !gotA.includes(idB),
    `dispatched=${JSON.stringify(gotA)}`);
  cell("RACE-03 B was enqueued during poll", !!idB, `${idB}`);

  // B 此后是否还能被取到：再 poll 三轮。
  let bSeen = false;
  for (let i = 0; i < 3; i++) {
    const p = await poll(token);
    if ((p.json?.commands || []).some((c) => c.id === idB)) bSeen = true;
  }
  cell("RACE-04 B never dispatched in 3 later polls (LOST)", !bSeen,
    bSeen ? "B dispatched (not lost)" : "B stuck");
  const cmdB = await getCmd(adminCookie, idB);
  cell("RACE-05 B record still queued forever", cmdB?.status === "queued",
    `status=${cmdB?.status}`);
  const queueNow = await kv.get("queue:wk1", "json");
  cell("RACE-06 queue array does not reference B", Array.isArray(queueNow) && !queueNow.includes(idB),
    `queue=${JSON.stringify(queueNow)}`);

  // 对照：poll 完成后再入队 C，下一轮 poll 正常取到（证明是时序竞态而非必现 bug）。
  const idC = await enqueue(adminCookie, "wk1", "get_status");
  const pC = await poll(token);
  cell("RACE-07 control: enqueue after poll dispatches normally",
    (pC.json?.commands || []).some((c) => c.id === idC), `${idC}`);

  const fails = RESULTS.filter(([, ok]) => !ok).length;
  console.log(`\nTOTAL ${RESULTS.length} cells, FAIL ${fails}: ${RESULTS.filter(([, ok]) => !ok).map(([n]) => n).join(", ")}`);
  process.exit(fails);
}

main().catch((e) => { console.error(e); process.exit(99); });

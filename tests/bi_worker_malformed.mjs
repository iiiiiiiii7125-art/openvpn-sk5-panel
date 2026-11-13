// BI Worker probe (bi_worker_malformed.mjs) — R18-P2-2 修复后行为：
// Worker 面畸形 sweep：缺 status／未知 status／非对象／sent_at 非数值／
// 缺 node 的记录必须落 failed＋隔离（不再滞留至 7 天 TTL）；数值型过期
// sent_at 的超时路径保持工作；吊销也能救畸形记录。
// 与 R18 复现探针不同：本探针断言修复后行为（PASS = 正确），R18 的
// r18_worker_malformed.mjs 断言缺陷复现（修复后 M-01/02/03/06 翻红属预期）。
// Usage: node tests/bi_worker_malformed.mjs  (exit code = FAIL count)
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

async function req(method, path, { body, headers = {} } = {}) {
  const r = await worker.fetch(
    new Request(BASE + path, {
      method,
      headers: { ...headers, "Content-Type": "application/json" },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }), env, {});
  const text = await r.text();
  let j = null;
  try { j = JSON.parse(text); } catch { /* non-json */ }
  return { status: r.status, json: j, text, headers: r.headers };
}

const login = await req("POST", "/api/login", {
  body: { password: "admin-pass-123" },
  headers: { "CF-Connecting-IP": "10.9.0.1" },
});
const cookie = "panel_session=" + (login.headers.get("Set-Cookie") || "").match(/panel_session=([^;]+)/)?.[1];
const reg = await req("POST", "/api/nodes", {
  body: { name: "wk1", panel_url: "" }, headers: { Cookie: cookie },
});
const token = reg.json?.token;
cell("BI-M-00 setup: node registered, token issued", !!token);

async function enqueue(node, action, params = {}) {
  const r = await req("POST", "/api/cmd", {
    body: { node, action, params }, headers: { Cookie: cookie },
  });
  return r.json?.cmd_id;
}
async function poll(node = "wk1") {
  return req("POST", "/api/agent/poll", {
    body: { node_name: node }, headers: { Authorization: "Bearer " + token },
  });
}
const getCmd = (id) => kv.get("cmd:" + id, "json");
const getCmdApi = (id) => req("GET", "/api/cmd/" + id, { headers: { Cookie: cookie } });

// M-01: 缺 status 的记录 —— poll 后标 failed＋隔离，不下发
const id1 = await enqueue("wk1", "get_status");
const rec1 = await getCmd(id1);
delete rec1.status;
await kv.put("cmd:" + id1, JSON.stringify(rec1));
const p1 = await poll();
const after1 = await getCmd(id1);
cell("BI-M-01 missing-status: poll does NOT dispatch it",
  !(p1.json?.commands || []).some((x) => x.id === id1));
cell("BI-M-01 missing-status: marked failed after poll (swept)",
  after1 && after1.status === "failed" && /隔离/.test(after1.error || ""),
  `status=${after1?.status} error=${after1?.error}`);

// M-02: 未知 status —— poll 后标 failed；report 仍 409；getCmd 见 failed
const id2 = await enqueue("wk1", "get_status");
const rec2 = await getCmd(id2);
rec2.status = "bogus";
await kv.put("cmd:" + id2, JSON.stringify(rec2));
const p2 = await poll();
const rep2 = await req("POST", "/api/agent/report", {
  body: { node_name: "wk1", cmd_id: id2, ok: true, result: {} },
  headers: { Authorization: "Bearer " + token },
});
const after2 = await getCmd(id2);
cell("BI-M-02 bogus-status: poll does NOT dispatch it",
  !(p2.json?.commands || []).some((x) => x.id === id2));
cell("BI-M-02 bogus-status: report rejected 409", rep2.status === 409,
  "status=" + rep2.status);
cell("BI-M-02 bogus-status: marked failed after poll+report (swept)",
  after2 && after2.status === "failed", `status=${after2?.status}`);

// M-03: sent_at 非数值（非幂等动作）—— 超时路径触发，首超时即标 failed
const id3 = await enqueue("wk1", "create_user", { name: "u3" });
await poll(); // dispatch -> sent
const sent3 = await kv.get("sent:wk1", "json");
const rec3 = await getCmd(id3);
sent3[0].sent_at = "abc";
rec3.sent_at = "abc";
await kv.put("sent:wk1", JSON.stringify(sent3));
await kv.put("cmd:" + id3, JSON.stringify(rec3));
const p3 = await poll();
const after3 = await getCmd(id3);
cell("BI-M-03 non-numeric sent_at (non-safe): marked failed after poll (NaN treated as expired)",
  after3 && after3.status === "failed", `status=${after3?.status}`);
cell("BI-M-03 non-numeric sent_at (non-safe): NOT redispatched",
  !(p3.json?.commands || []).some((x) => x.id === id3));

// M-03b: sent_at 非数值（SAFE 动作）—— 超时路径触发，重投＋重发，retries=1
const id3b = await enqueue("wk1", "get_status");
await poll(); // dispatch -> sent
const sent3b = await kv.get("sent:wk1", "json");
const rec3b = await getCmd(id3b);
sent3b.find((e) => e.id === id3b).sent_at = "abc";
rec3b.sent_at = "abc";
await kv.put("sent:wk1", JSON.stringify(sent3b));
await kv.put("cmd:" + id3b, JSON.stringify(rec3b));
const p3b = await poll();
const after3b = await getCmd(id3b);
cell("BI-M-03b non-numeric sent_at (safe): requeued+redispatched, retries=1",
  after3b && after3b.status === "sent" && after3b.retries === 1 &&
  (p3b.json?.commands || []).some((x) => x.id === id3b),
  `status=${after3b?.status} retries=${after3b?.retries}`);

// M-04 对照：数值型过期 sent_at（SAFE 动作）—— 同轮 poll 重投＋重发
const id4 = await enqueue("wk1", "get_status");
await poll(); // dispatch -> sent
const sent4 = await kv.get("sent:wk1", "json");
const stale = Date.now() - 130000;
sent4.find((e) => e.id === id4).sent_at = stale;
const rec4 = await getCmd(id4);
rec4.sent_at = stale;
await kv.put("sent:wk1", JSON.stringify(sent4));
await kv.put("cmd:" + id4, JSON.stringify(rec4));
const p4 = await poll();
const after4 = await getCmd(id4);
cell("BI-M-04 control numeric stale sent_at (safe): requeued+redispatched, retries=1",
  after4 && after4.status === "sent" && after4.retries === 1 &&
  (p4.json?.commands || []).some((x) => x.id === id4),
  `status=${after4?.status} retries=${after4?.retries}`);

// M-05 对照：数值型过期 sent_at（非幂等动作）—— 首超时即标 failed
const id5 = await enqueue("wk1", "create_user", { name: "u5" });
await poll(); // dispatch -> sent
const sent5 = await kv.get("sent:wk1", "json");
sent5.find((e) => e.id === id5).sent_at = stale;
const rec5 = await getCmd(id5);
rec5.sent_at = stale;
await kv.put("sent:wk1", JSON.stringify(sent5));
await kv.put("cmd:" + id5, JSON.stringify(rec5));
await poll();
const after5 = await getCmd(id5);
cell("BI-M-05 control numeric stale sent_at (non-safe): failed at first timeout",
  after5 && after5.status === "failed",
  `status=${after5?.status}`);

// M-06: 非对象记录 —— poll 200 不崩，记录被隔离为 failed 对象
const id6 = await enqueue("wk1", "get_status");
await kv.put("cmd:" + id6, JSON.stringify("hello"));
const p6 = await poll();
const after6 = await getCmd(id6);
cell("BI-M-06 non-object record: poll stays 200 (no crash)",
  p6.status === 200, "status=" + p6.status);
cell("BI-M-06 non-object record: isolated as failed object after poll",
  after6 && typeof after6 === "object" && after6.status === "failed",
  `value=${JSON.stringify(after6)}`);

// M-07: 缺 node 的记录 —— poll 后标 failed（不归属任何节点，不滞留）
const id7 = await enqueue("wk1", "get_status");
const rec7 = await getCmd(id7);
delete rec7.node;
await kv.put("cmd:" + id7, JSON.stringify(rec7));
await poll();
const after7 = await getCmd(id7);
cell("BI-M-07 missing-node: marked failed after poll (swept)",
  after7 && after7.status === "failed", `status=${after7?.status}`);

// M-08: cmd_get 读路径先扫 —— 缺 status 的记录经 GET 即见 failed
const id8 = await enqueue("wk1", "get_status");
const rec8 = await getCmd(id8);
delete rec8.status;
await kv.put("cmd:" + id8, JSON.stringify(rec8));
const gc8 = await getCmdApi(id8);
cell("BI-M-08 cmd_get path sweeps: missing-status record reads as failed",
  gc8.json && gc8.json.status === "failed", `status=${gc8.json?.status}`);

// M-09: timeout_hint 数值化 —— 数值型过期 sent_at 的 sent 记录有 hint
const id9 = await enqueue("wk1", "get_status");
await poll(); // dispatch -> sent
const sent9 = await kv.get("sent:wk1", "json");
sent9.find((e) => e.id === id9).sent_at = stale;
const rec9 = await getCmd(id9);
rec9.sent_at = stale;
await kv.put("sent:wk1", JSON.stringify(sent9));
await kv.put("cmd:" + id9, JSON.stringify(rec9));
const gc9 = await getCmdApi(id9);
cell("BI-M-09 getCmd timeout_hint present for stale numeric sent_at",
  gc9.json && "timeout_hint" in gc9.json, `hint=${!!(gc9.json && gc9.json.timeout_hint)}`);

// M-10: 吊销能救畸形记录 —— 新节点 wk2 上造一条 bogus 记录再吊销，须见 failed
const reg2 = await req("POST", "/api/nodes", {
  body: { name: "wk2", panel_url: "" }, headers: { Cookie: cookie },
});
cell("BI-M-10 setup: second node wk2 registered", reg2.status === 201, `${reg2.status}`);
const id10 = await enqueue("wk2", "get_status");
const rec10 = await getCmd(id10);
rec10.status = "bogus";
await kv.put("cmd:" + id10, JSON.stringify(rec10));
const rev = await req("DELETE", "/api/nodes/wk2", { headers: { Cookie: cookie } });
const after10 = await getCmd(id10);
cell("BI-M-10 revoke saves malformed record: bogus -> failed on revoke",
  rev.status === 200 && after10 && after10.status === "failed",
  `revoke=${rev.status} status=${after10?.status}`);

const fails = RESULTS.filter(([, ok]) => !ok).length;
console.log(`TOTAL ${RESULTS.length} PASS ${RESULTS.length - fails} FAIL ${fails}`);
process.exit(fails ? 1 : 0);

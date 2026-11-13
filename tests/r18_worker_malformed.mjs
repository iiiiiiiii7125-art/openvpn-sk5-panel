// R18 Worker probe (r18_worker_malformed.mjs) — Worker 面无 malformed sweep：
// Flask 面 _fail_malformed_cmds 在 6 处读路径上把畸形命令标 failed＋审计
// （R12-P1-1／R13-P2-1／R14-P2-1）；Worker 面没有任何等价物——index.js
// 里 "failed" 写点只有三处：吊销（:518）、重投超限（:607）、非幂等超时
// （:620）。手改 KV 造出的畸形记录（缺 status／未知 status／非对象／
// sent_at 非数值）在任何 API 路径上都得不到 failed 标记与审计，只在
// CMD_TTL_S（7 天）到期后随记录删除而消失。
// Usage: node tests/r18_worker_malformed.mjs  (exit code = FAIL count)
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
cell("M-00 setup: node registered, token issued", !!token);

async function enqueue(action, params = {}) {
  const r = await req("POST", "/api/cmd", {
    body: { node: "wk1", action, params }, headers: { Cookie: cookie },
  });
  return r.json?.cmd_id;
}
async function poll() {
  return req("POST", "/api/agent/poll", {
    body: { node_name: "wk1" }, headers: { Authorization: "Bearer " + token },
  });
}
const getCmd = (id) => kv.get("cmd:" + id, "json");

// M-01: 缺 status 的记录 —— poll 不下发、也不标 failed、不审计
const id1 = await enqueue("get_status");
const rec1 = await getCmd(id1);
delete rec1.status;
await kv.put("cmd:" + id1, JSON.stringify(rec1));
const p1 = await poll();
const after1 = await getCmd(id1);
cell("M-01 missing-status: poll does NOT dispatch it",
  !(p1.json?.commands || []).some((x) => x.id === id1));
cell("M-01 missing-status: still NOT failed after poll cycle (no sweep)",
  after1 && !("status" in after1));

// M-02: 未知 status —— poll 跳过、report 409、仍不标 failed
const id2 = await enqueue("get_status");
const rec2 = await getCmd(id2);
rec2.status = "bogus";
await kv.put("cmd:" + id2, JSON.stringify(rec2));
const p2 = await poll();
const rep2 = await req("POST", "/api/agent/report", {
  body: { node_name: "wk1", cmd_id: id2, ok: true, result: {} },
  headers: { Authorization: "Bearer " + token },
});
const after2 = await getCmd(id2);
cell("M-02 bogus-status: poll does NOT dispatch it",
  !(p2.json?.commands || []).some((x) => x.id === id2));
cell("M-02 bogus-status: report rejected 409", rep2.status === 409,
  "status=" + rep2.status);
cell("M-02 bogus-status: still 'bogus' after poll+report (no sweep)",
  after2 && after2.status === "bogus");

// M-03: sent_at 非数值 —— 超时重投永不触发，sent 态卡住
const id3 = await enqueue("create_user", { name: "u3" });
await poll(); // dispatch -> sent
const sent3 = await kv.get("sent:wk1", "json");
const rec3 = await getCmd(id3);
sent3[0].sent_at = "abc";
rec3.sent_at = "abc";
await kv.put("sent:wk1", JSON.stringify(sent3));
await kv.put("cmd:" + id3, JSON.stringify(rec3));
const p3 = await poll();
const after3 = await getCmd(id3);
const gc3 = await req("GET", "/api/cmd/" + id3, { headers: { Cookie: cookie } });
cell("M-03 non-numeric sent_at: still sent after poll (NaN never times out)",
  after3 && after3.status === "sent");
cell("M-03 non-numeric sent_at: retries still 0 (requeue never ran)",
  after3 && (after3.retries || 0) === 0);
cell("M-03 non-numeric sent_at: getCmd timeout_hint also missing (NaN)",
  gc3.json && !("timeout_hint" in gc3.json));

// M-04 对照：数值型过期 sent_at（SAFE 动作）—— 同轮 poll 重投＋重发
const id4 = await enqueue("get_status");
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
cell("M-04 control numeric stale sent_at (safe): requeued+redispatched, retries=1",
  after4 && after4.status === "sent" && after4.retries === 1 &&
  (p4.json?.commands || []).some((x) => x.id === id4),
  "status=" + after4?.status + " retries=" + after4?.retries);

// M-05 对照：数值型过期 sent_at（非幂等动作）—— 首超时即标 failed
const id5 = await enqueue("create_user", { name: "u5" });
await poll(); // dispatch -> sent
const sent5 = await kv.get("sent:wk1", "json");
sent5.find((e) => e.id === id5).sent_at = stale;
const rec5 = await getCmd(id5);
rec5.sent_at = stale;
await kv.put("sent:wk1", JSON.stringify(sent5));
await kv.put("cmd:" + id5, JSON.stringify(rec5));
await poll();
const after5 = await getCmd(id5);
cell("M-05 control numeric stale sent_at (non-safe): failed at first timeout",
  after5 && after5.status === "failed",
  "status=" + after5?.status);

// M-06: 非对象记录 —— poll 不崩（200），记录原样滞留
const id6 = await enqueue("get_status");
await kv.put("cmd:" + id6, JSON.stringify("hello"));
const p6 = await poll();
const after6 = await getCmd(id6);
cell("M-06 non-object record: poll stays 200 (no crash)",
  p6.status === 200, "status=" + p6.status);
cell("M-06 non-object record: still 'hello' after poll (no sweep)",
  after6 === "hello", "value=" + JSON.stringify(after6));

const fails = RESULTS.filter(([, ok]) => !ok).length;
console.log(`TOTAL ${RESULTS.length} PASS ${RESULTS.length - fails} FAIL ${fails}`);
process.exit(fails ? 1 : 0);

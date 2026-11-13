// R19 Worker probe (r19_worker_nonlist_container.mjs) — R19-P2-1:
// queue:<name> / sent:<name> 容器值非数组时，Worker 读路径与写路径不得 500。
// Flask 面已由 BA（R14-P2-1）修完（非列表按空处理＋审计）；Worker 面从未审过
// 该形状：poll／enqueue 在非列表容器值上抛 TypeError → 500，节点卡死至
// 手工修 KV（sweep 自身先抛，无法自愈）。
// 本探针断言修复后行为（PASS = 正确）：非数组容器按 [] 处理，命令照常
// 下发或诚实失败，绝不 500。Usage: node tests/r19_worker_nonlist_container.mjs
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
  return r;
}

async function getCmd(adminCookie, id) {
  const r = await req("GET", `/api/cmd/${id}`, { headers: { Cookie: adminCookie } });
  return r.json;
}

async function freshNode(adminCookie, name) {
  const r = await req("POST", "/api/nodes", {
    body: { name, panel_url: "" }, headers: { Cookie: adminCookie },
  });
  return r.json?.token;
}

async function main() {
  const adminCookie = await loginAsAdmin("10.9.0.1");
  cell("NL-00 admin session obtained", adminCookie.length > 0);

  // NL-01: poll，queue 为字符串，且有孤儿 queued 记录 → 不得 500，命令应下发
  {
    const token = await freshNode(adminCookie, "nl1");
    const e = await enqueue(adminCookie, "nl1", "get_status");
    const id = e.json?.cmd_id;
    await kv.put("queue:nl1", JSON.stringify("not-a-list"));
    const p = await poll(token, "nl1");
    const dispatched = (p.json?.commands || []).some((c) => c.id === id);
    cell("NL-01 poll queue=string + orphan queued: 200 and dispatched", p.status === 200 && dispatched,
      `${p.status} dispatched=${dispatched}`);
  }
  // NL-02: poll，queue 为字符串，无孤儿 → 200 空下发
  {
    const token = await freshNode(adminCookie, "nl2");
    await kv.put("queue:nl2", JSON.stringify("not-a-list"));
    const p = await poll(token, "nl2");
    cell("NL-02 poll queue=string, no orphan: 200", p.status === 200 && Array.isArray(p.json?.commands),
      `${p.status}`);
  }
  // NL-03: poll，queue 为对象 → 200
  {
    const token = await freshNode(adminCookie, "nl3");
    const e = await enqueue(adminCookie, "nl3", "get_status");
    const id = e.json?.cmd_id;
    await kv.put("queue:nl3", JSON.stringify({ a: 1 }));
    const p = await poll(token, "nl3");
    const dispatched = (p.json?.commands || []).some((c) => c.id === id);
    cell("NL-03 poll queue=object + orphan: 200 and dispatched", p.status === 200 && dispatched,
      `${p.status} dispatched=${dispatched}`);
  }
  // NL-04: poll，sent 为字符串 → 200
  {
    const token = await freshNode(adminCookie, "nl4");
    await enqueue(adminCookie, "nl4", "get_status");
    await kv.put("sent:nl4", JSON.stringify("not-a-list"));
    const p = await poll(token, "nl4");
    cell("NL-04 poll sent=string: 200", p.status === 200 && Array.isArray(p.json?.commands),
      `${p.status}`);
  }
  // NL-05: poll，sent 为对象 → 200
  {
    const token = await freshNode(adminCookie, "nl5");
    await enqueue(adminCookie, "nl5", "get_status");
    await kv.put("sent:nl5", JSON.stringify({ a: 1 }));
    const p = await poll(token, "nl5");
    cell("NL-05 poll sent=object: 200", p.status === 200 && Array.isArray(p.json?.commands),
      `${p.status}`);
  }
  // NL-06: enqueue 时 queue 为字符串 → 202，命令入队且下一轮可下发
  {
    const token = await freshNode(adminCookie, "nl6");
    await kv.put("queue:nl6", JSON.stringify("not-a-list"));
    const e = await enqueue(adminCookie, "nl6", "get_status");
    const id = e.json?.cmd_id;
    const p = await poll(token, "nl6");
    const dispatched = (p.json?.commands || []).some((c) => c.id === id);
    cell("NL-06 enqueue on queue=string: 202 and later dispatched",
      e.status === 202 && !!id && p.status === 200 && dispatched,
      `enqueue=${e.status} poll=${p.status} dispatched=${dispatched}`);
  }
  // NL-07: report，queue 为字符串＋孤儿 → 不得 500（200 或 409）
  {
    const token = await freshNode(adminCookie, "nl7");
    const e = await enqueue(adminCookie, "nl7", "get_status");
    const id = e.json?.cmd_id;
    await kv.put("queue:nl7", JSON.stringify("not-a-list"));
    const r = await req("POST", "/api/agent/report", {
      body: { cmd_id: id, ok: true, result: {} },
      headers: { Authorization: "Bearer " + token },
    });
    cell("NL-07 report queue=string + orphan: not 500", r.status !== 500, `${r.status}`);
  }
  // NL-08: revoke，queue 为字符串＋孤儿 → 200，节点消失
  {
    const token = await freshNode(adminCookie, "nl8");
    await enqueue(adminCookie, "nl8", "get_status");
    await kv.put("queue:nl8", JSON.stringify("not-a-list"));
    const r = await req("DELETE", "/api/nodes/nl8", { headers: { Cookie: adminCookie } });
    const gone = await kv.get("node:nl8", "json");
    cell("NL-08 revoke queue=string + orphan: 200 and node gone",
      r.status === 200 && gone === null, `${r.status} gone=${gone === null}`);
  }
  // NL-09: cmd_get，queue 为字符串＋孤儿 → 200
  {
    const token = await freshNode(adminCookie, "nl9");
    const e = await enqueue(adminCookie, "nl9", "get_status");
    const id = e.json?.cmd_id;
    await kv.put("queue:nl9", JSON.stringify("not-a-list"));
    const g = await req("GET", `/api/cmd/${id}`, { headers: { Cookie: adminCookie } });
    cell("NL-09 cmd_get queue=string + orphan: 200", g.status === 200, `${g.status}`);
  }
  // NL-10 对照：正常列表 queue，poll 下发一次
  {
    const token = await freshNode(adminCookie, "nl10");
    const e = await enqueue(adminCookie, "nl10", "get_status");
    const id = e.json?.cmd_id;
    const p = await poll(token, "nl10");
    const dispatched = (p.json?.commands || []).some((c) => c.id === id);
    cell("NL-10 control normal list queue: 200 and dispatched once",
      p.status === 200 && dispatched, `${p.status} dispatched=${dispatched}`);
  }
  // NL-11 对照：非对象 cmd 记录，poll 200（sweep 隔离，BI 已修）
  {
    const token = await freshNode(adminCookie, "nl11");
    await kv.put("queue:nl11", JSON.stringify(["bad1"]));
    await kv.put("cmd:bad1", JSON.stringify("not-a-dict"));
    const p = await poll(token, "nl11");
    cell("NL-11 control non-object cmd record: 200", p.status === 200, `${p.status}`);
  }

  const fails = RESULTS.filter(([, ok]) => !ok).length;
  console.log(`\nTOTAL ${RESULTS.length} cells, FAIL ${fails}: ${RESULTS.filter(([, ok]) => !ok).map(([n]) => n).join(", ")}`);
  process.exit(fails);
}

main().catch((e) => { console.error(e); process.exit(99); });

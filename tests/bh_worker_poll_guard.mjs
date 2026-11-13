// BH Worker probe (bh_worker_poll_guard.mjs) — R17-P1-1 Worker 面修复验证。
// Mock KV 全路由：poll 只下发 queued 命令；report 只接受 sent 态回执。
// Usage: node tests/bh_worker_poll_guard.mjs  (exit code = FAIL count)
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
  return r.json?.cmd_id;
}

async function main() {
  const adminCookie = await loginAsAdmin("10.9.0.1");
  cell("BH-00 admin session obtained", adminCookie.length > 0, "");
  let r = await req("POST", "/api/nodes", {
    body: { name: "wk1", panel_url: "" }, headers: { Cookie: adminCookie },
  });
  cell("BH-00b register node 201", r.status === 201 && !!r.json?.token,
    `${r.status}`);
  const token = r.json?.token;

  // ---------- (a) failed 标记的命令不下发（W5-01 翻转） ----------
  const failedId = await enqueue(adminCookie, "wk1", "get_status");
  const cmdRec = await kv.get(`cmd:${failedId}`, "json");
  cmdRec.status = "failed";
  cmdRec.error = "队列条目损坏（status 缺失），已隔离，不再下发";
  await kv.put(`cmd:${failedId}`, JSON.stringify(cmdRec));
  r = await poll(token);
  cell("BH-01 (a) poll does NOT dispatch failed cmd",
    !(r.json?.commands || []).some((x) => x.id === failedId),
    JSON.stringify(r.json?.commands || []));
  const failedAfter = await kv.get(`cmd:${failedId}`, "json");
  cell("BH-01b failed cmd stays failed after poll",
    failedAfter?.status === "failed", JSON.stringify(failedAfter?.status));

  // ---------- (b) 已 sent 的命令，陈旧／并发 poll 重读不重复下发（W5-05 翻转） ----------
  const dupId = await enqueue(adminCookie, "wk1", "get_status");
  r = await poll(token);
  const first = (r.json?.commands || []).some((x) => x.id === dupId);
  cell("BH-02a first poll dispatches the queued cmd", first,
    JSON.stringify(r.json?.commands || []));
  // 模拟陈旧 KV 读／并发第二轮 poll：队列里仍有该 id
  const q2 = (await kv.get("queue:wk1", "json")) || [];
  q2.push(dupId);
  await kv.put("queue:wk1", JSON.stringify(q2));
  r = await poll(token);
  cell("BH-02 (b) stale second poll does NOT re-dispatch sent cmd",
    !(r.json?.commands || []).some((x) => x.id === dupId),
    JSON.stringify(r.json?.commands || []));

  // ---------- (c) report 先行对 queued 命令回执 → 409 拒收，命令仍 queued（W5-06 翻转） ----------
  const preId = await enqueue(adminCookie, "wk1", "init_pki",
    { force: true, confirm: true });
  r = await req("POST", "/api/agent/report", {
    body: { cmd_id: preId, ok: false, error: "stale agent report" },
    headers: { Authorization: "Bearer " + token },
  });
  cell("BH-03a report on still-queued cmd is 409 (not accepted)",
    r.status === 409, `${r.status} ${JSON.stringify(r.json)?.slice(0, 100)}`);
  const preRec = await kv.get(`cmd:${preId}`, "json");
  cell("BH-03b queued cmd stays queued after stale report",
    preRec?.status === "queued", JSON.stringify(preRec?.status));
  r = await poll(token);
  // 修正口径：409 拒收后命令仍是 queued——下一轮 poll 下发它是
  // 正常行为（诚实地 queued→sent），不是 R17 的 bug。R17 的 bug 是
  // “已 failed 仍下发”，即面板信 failed、agent 却执行；现在两者
  // 一致：要么 queued→下发，要么 failed→不下发。本格断言：下发后
  // 状态为 sent（未被悄悄丢弃、也未以 failed 态下发）。
  const dispatchedAsQueued = (r.json?.commands || []).some((x) => x.id === preId);
  const preAfter = await kv.get(`cmd:${preId}`, "json");
  cell("BH-03 (c) after 409 the still-queued init_pki is dispatched as queued (sent)",
    dispatchedAsQueued && preAfter?.status === "sent",
    JSON.stringify(r.json?.commands || []) + " status=" + preAfter?.status);

  // ---------- (d) 正常 queued 命令下发一次且翻 sent、记 sent 副本 ----------
  const okId = await enqueue(adminCookie, "wk1", "get_status");
  r = await poll(token);
  cell("BH-04 (d) normal queued cmd dispatched exactly once",
    (r.json?.commands || []).filter((x) => x.id === okId).length === 1,
    JSON.stringify(r.json?.commands || []));
  const okRec = await kv.get(`cmd:${okId}`, "json");
  cell("BH-04b dispatched cmd flipped to sent",
    okRec?.status === "sent" && typeof okRec?.sent_at === "number",
    JSON.stringify(okRec?.status));
  const sentCopy = (await kv.get("sent:wk1", "json")) || [];
  cell("BH-04c sent copy recorded",
    sentCopy.some((e) => e.id === okId), JSON.stringify(sentCopy));

  // ---------- (e) 超时 sent 的回队／标失败规则仍工作 ----------
  const now = Date.now();
  async function seedSent(id, action, sentAt) {
    await kv.put(`cmd:${id}`, JSON.stringify({
      id, node: "wk1", action, params: {}, status: "sent",
      sent_at: sentAt, created_at: now, retries: 0,
    }));
    const sent = (await kv.get("sent:wk1", "json")) || [];
    sent.push({ id, action, sent_at: sentAt });
    await kv.put("sent:wk1", JSON.stringify(sent));
  }
  await seedSent("sent-ok", "get_status", now - 130000);
  await seedSent("sent-bad", "create_user", now - 130000);
  r = await poll(token);
  const got = (r.json?.commands || []).map((x) => x.id);
  cell("BH-05 (e) timed-out idempotent get_status requeued+dispatched",
    got.includes("sent-ok"), JSON.stringify(got));
  cell("BH-05b timed-out non-idempotent create_user NOT dispatched",
    !got.includes("sent-bad"), JSON.stringify(got));
  const badRec = await kv.get("cmd:sent-bad", "json");
  cell("BH-05c non-idempotent timed-out cmd marked failed",
    badRec?.status === "failed", JSON.stringify(badRec?.status));

  // ---------- (f) 正常回执 sent→done/failed 仍工作；重复回执 409 且不翻 ----------
  const repId = await enqueue(adminCookie, "wk1", "get_status");
  await poll(token); // flips sent
  r = await req("POST", "/api/agent/report", {
    body: { cmd_id: repId, ok: true, result: { openvpn: { running: false } } },
    headers: { Authorization: "Bearer " + token },
  });
  cell("BH-06 (f) normal report sent->done 200",
    r.status === 200 && r.json?.status === "done",
    `${r.status} ${JSON.stringify(r.json)?.slice(0, 80)}`);
  r = await req("POST", "/api/agent/report", {
    body: { cmd_id: repId, ok: false, error: "duplicate report" },
    headers: { Authorization: "Bearer " + token },
  });
  cell("BH-06b duplicate report on done cmd is 409",
    r.status === 409, `${r.status} ${JSON.stringify(r.json)?.slice(0, 80)}`);
  const repRec = await kv.get(`cmd:${repId}`, "json");
  cell("BH-06c done cmd stays done after duplicate report",
    repRec?.status === "done", JSON.stringify(repRec?.status));
  const failId = await enqueue(adminCookie, "wk1", "create_user",
    { name: "u1" });
  await poll(token);
  r = await req("POST", "/api/agent/report", {
    body: { cmd_id: failId, ok: false, error: "boom" },
    headers: { Authorization: "Bearer " + token },
  });
  cell("BH-06d normal report sent->failed 200",
    r.status === 200 && r.json?.status === "failed",
    `${r.status} ${JSON.stringify(r.json)?.slice(0, 80)}`);

  // ---------- 额外：状态缺失的手改条目不下发 ----------
  const ghostId = await enqueue(adminCookie, "wk1", "get_status");
  const ghostRec = await kv.get(`cmd:${ghostId}`, "json");
  delete ghostRec.status;
  await kv.put(`cmd:${ghostId}`, JSON.stringify(ghostRec));
  r = await poll(token);
  cell("BH-07 status-missing hand-edited cmd NOT dispatched",
    !(r.json?.commands || []).some((x) => x.id === ghostId),
    JSON.stringify(r.json?.commands || []));

  const fails = RESULTS.filter(([, ok]) => !ok).map(([n]) => n);
  console.log(`\nTOTAL ${RESULTS.length} cells, FAIL ${fails.length}: ${JSON.stringify(fails)}`);
  process.exit(fails.length);
}

main().catch((e) => { console.error(e); process.exit(99); });

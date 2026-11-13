// AUDIT-R17 Worker probe (r17_worker.mjs) — mock KV, own enumeration.
// Drives cloudflare/src/index.js default.fetch with an in-memory KV.
// Usage: node tests/r17_worker.mjs
// Cells W1..W6x; exit code = FAIL count.
import worker from "../cloudflare/src/index.js";

const TREE = process.env.R17_TREE || "/tmp/r17/ptree";

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

async function loginAsAdmin(ip) {
  const r = await req("POST", "/api/login", {
    body: { password: "admin-pass-123" },
    headers: { "CF-Connecting-IP": ip },
  });
  const cookie = r.headers.get("Set-Cookie") || "";
  const m = cookie.match(/panel_session=([^;]+)/);
  return m ? `panel_session=${m[1]}` : "";
}

async function main() {
  // ---------- W1 login / lockout ----------
  let r = await req("GET", "/api/nodes");
  cell("W1-01 nodes unauth 401", r.status === 401, String(r.status));
  r = await req("POST", "/api/login", { rawBody: "not json", headers: { "CF-Connecting-IP": "10.1.0.1" } });
  cell("W1-02 login non-JSON body 400 (R13-P2-4)", r.status === 400, String(r.status));
  cell("W1-03 non-JSON body does NOT record failure",
    (await kv.get("loginfail:10.1.0.1", "json")) === null, "");
  r = await req("POST", "/api/login", { body: [1, 2], headers: { "CF-Connecting-IP": "10.1.0.2" } });
  cell("W1-04 login array body 400", r.status === 400, String(r.status));
  cell("W1-05 array body does NOT record failure",
    (await kv.get("loginfail:10.1.0.2", "json")) === null, "");
  r = await req("POST", "/api/login", { body: {}, headers: { "CF-Connecting-IP": "10.1.0.3" } });
  cell("W1-06 login missing password 401 + records", r.status === 401 &&
    (await kv.get("loginfail:10.1.0.3", "json")) !== null, String(r.status));
  for (let i = 0; i < 5; i++) {
    r = await req("POST", "/api/login", { body: { password: "wrong" }, headers: { "CF-Connecting-IP": "10.1.0.4" } });
  }
  cell("W1-07 5 wrong logins -> 5th 401", r.status === 401, String(r.status));
  r = await req("POST", "/api/login", { body: { password: "wrong" }, headers: { "CF-Connecting-IP": "10.1.0.4" } });
  cell("W1-08 6th wrong login 429 + Retry-After",
    r.status === 429 && r.headers.get("Retry-After") !== null,
    `${r.status} ${r.headers.get("Retry-After")}`);
  r = await req("POST", "/api/login", { body: { password: "admin-pass-123" }, headers: { "CF-Connecting-IP": "10.1.0.5" } });
  cell("W1-09 correct login 200", r.status === 200, String(r.status));
  const sc = r.headers.get("Set-Cookie") || "";
  cell("W1-10 session cookie HttpOnly", sc.includes("HttpOnly"), sc.slice(0, 80));
  const adminCookie = await loginAsAdmin("10.1.0.6");
  cell("W1-11 admin session cookie obtained", adminCookie.length > 0, "");

  // ---------- W2 nodes ----------
  r = await req("POST", "/api/nodes", {
    body: { name: "wk1", panel_url: "" }, headers: { Cookie: adminCookie },
  });
  cell("W2-01 register node 201 + token once",
    r.status === 201 && !!r.json?.token, `${r.status} ${JSON.stringify(r.json)?.slice(0, 80)}`);
  const token = r.json?.token;
  r = await req("GET", "/api/nodes", { headers: { Cookie: adminCookie } });
  cell("W2-02 node list has no token", !JSON.stringify(r.json).includes(token), "");
  // nameless KV record must not kill listNodes (R12-P2-3)
  await kv.put("node:", JSON.stringify({ created_at: 1 }));
  r = await req("GET", "/api/nodes", { headers: { Cookie: adminCookie } });
  cell("W2-03 listNodes with nameless record 200 (not 500)",
    r.status === 200 && Array.isArray(r.json?.nodes), `${r.status}`);
  await kv.delete("node:");
  r = await req("POST", "/api/nodes", {
    body: { name: "bad name!", panel_url: "" }, headers: { Cookie: adminCookie },
  });
  cell("W2-04 register bad name 400", r.status === 400, String(r.status));
  r = await req("POST", "/api/nodes", {
    body: { name: "wk1", panel_url: "" }, headers: { Cookie: adminCookie },
  });
  cell("W2-05 duplicate node 409", r.status === 409, String(r.status));

  // ---------- W3 cmd enqueue validation ----------
  r = await req("POST", "/api/cmd", {
    body: { node: "wk1", action: "get_status", params: [] },
    headers: { Cookie: adminCookie },
  });
  cell("W3-01 cmd list params 400", r.status === 400, String(r.status));
  r = await req("POST", "/api/cmd", {
    body: { node: "wk1", action: "rm_rf", params: {} },
    headers: { Cookie: adminCookie },
  });
  cell("W3-02 cmd unknown action 400", r.status === 400, String(r.status));
  r = await req("POST", "/api/cmd", {
    body: { node: "ghost", action: "get_status", params: {} },
    headers: { Cookie: adminCookie },
  });
  cell("W3-03 cmd ghost node 404", r.status === 404, String(r.status));
  r = await req("POST", "/api/cmd", {
    body: { node: "wk1", action: "get_status", params: {} },
    headers: { Cookie: adminCookie },
  });
  cell("W3-04 enqueue get_status 202", r.status === 202 && !!r.json?.cmd_id,
    `${r.status} ${JSON.stringify(r.json)?.slice(0, 80)}`);
  const cmdId = r.json?.cmd_id;
  r = await req("POST", "/api/agent/poll", {
    body: { node_name: "wk1" },
    headers: { Authorization: "Bearer " + token },
  });
  cell("W3-05 agent poll gets the command",
    r.status === 200 && (r.json?.commands || []).some((x) => x.id === cmdId),
    `${r.status} ${JSON.stringify(r.json)?.slice(0, 120)}`);
  r = await req("POST", "/api/agent/report", {
    body: { cmd_id: cmdId, ok: true, result: { openvpn: { running: false } } },
    headers: { Authorization: "Bearer " + token },
  });
  cell("W3-06 agent report 200", r.status === 200, String(r.status));
  r = await req("GET", `/api/cmd/${cmdId}`, { headers: { Cookie: adminCookie } });
  cell("W3-07 cmd done after report", r.json?.status === "done",
    JSON.stringify(r.json)?.slice(0, 120));
  r = await req("POST", "/api/agent/poll", {
    body: { node_name: "wk1" },
    headers: { Authorization: "Bearer bad" },
  });
  cell("W3-08 poll bad token 401", r.status === 401, String(r.status));
  r = await req("POST", "/api/agent/poll", {
    body: { node_name: "other" },
    headers: { Authorization: "Bearer " + token },
  });
  cell("W3-09 poll token/name mismatch 401", r.status === 401, String(r.status));

  // ---------- W4 change-password ----------
  r = await req("POST", "/api/change-password", {
    body: { old_password: "x", new_password: "y" },
  });
  cell("W4-01 change-password unauth 401", r.status === 401, String(r.status));
  r = await req("POST", "/api/change-password", {
    body: { old_password: "admin-pass-123", new_password: "newpass123456" },
    headers: { Cookie: adminCookie },
  });
  cell("W4-02 change-password authed 501 (R11-P2-1)", r.status === 501,
    `${r.status} ${JSON.stringify(r.json)?.slice(0, 100)}`);

  // ---------- W5 poll dispatch guard (Worker face of R17-P1-1) ----------
  r = await req("POST", "/api/cmd", {
    body: { node: "wk1", action: "get_status", params: {} },
    headers: { Cookie: adminCookie },
  });
  const failedId = r.json?.cmd_id;
  const cmdRec = await kv.get(`cmd:${failedId}`, "json");
  cmdRec.status = "failed";
  cmdRec.error = "队列条目损坏（status 缺失），已隔离，不再下发";
  await kv.put(`cmd:${failedId}`, JSON.stringify(cmdRec));
  r = await req("POST", "/api/agent/poll", {
    body: { node_name: "wk1" },
    headers: { Authorization: "Bearer " + token },
  });
  cell("W5-01 Worker poll does NOT dispatch failed cmd",
    !(r.json?.commands || []).some((x) => x.id === failedId),
    JSON.stringify(r.json?.commands || []));
  // sent-timeout: idempotent requeued, non-idempotent failed
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
  r = await req("POST", "/api/agent/poll", {
    body: { node_name: "wk1" },
    headers: { Authorization: "Bearer " + token },
  });
  const got = (r.json?.commands || []).map((x) => x.id);
  cell("W5-02 sent-timeout idempotent get_status requeued", got.includes("sent-ok"),
    JSON.stringify(got));
  cell("W5-03 sent-timeout non-idempotent create_user NOT requeued",
    !got.includes("sent-bad"), JSON.stringify(got));
  const badRec = await kv.get("cmd:sent-bad", "json");
  cell("W5-04 non-idempotent timed-out cmd marked failed",
    badRec?.status === "failed", JSON.stringify(badRec)?.slice(0, 120));

  // ---------- W5-05/06: same unconditional-push defect, other reachability ----------
  // W5-05: stale/concurrent poll re-reading the queue while the record is
  // already sent -> the same command is dispatched a second time.
  r = await req("POST", "/api/cmd", {
    body: { node: "wk1", action: "get_status", params: {} },
    headers: { Cookie: adminCookie },
  });
  const dupId = r.json?.cmd_id;
  r = await req("POST", "/api/agent/poll", {
    body: { node_name: "wk1" },
    headers: { Authorization: "Bearer " + token },
  });
  const first = (r.json?.commands || []).some((x) => x.id === dupId);
  // simulate a stale KV read / concurrent second poll: queue still has the id
  const q2 = (await kv.get("queue:wk1", "json")) || [];
  q2.push(dupId);
  await kv.put("queue:wk1", JSON.stringify(q2));
  r = await req("POST", "/api/agent/poll", {
    body: { node_name: "wk1" },
    headers: { Authorization: "Bearer " + token },
  });
  cell("W5-05 OBSERVED: stale second poll re-dispatches already-sent cmd",
    first && (r.json?.commands || []).some((x) => x.id === dupId),
    JSON.stringify(r.json?.commands || []));
  // W5-06: report-before-poll -- report handler has no status guard
  // (index.js:684 applies done/failed to any status), so a queued cmd
  // reported failed keeps its queue entry and is dispatched next poll.
  r = await req("POST", "/api/cmd", {
    body: { node: "wk1", action: "init_pki", params: { force: true, confirm: true } },
    headers: { Cookie: adminCookie },
  });
  const preId = r.json?.cmd_id;
  r = await req("POST", "/api/agent/report", {
    body: { cmd_id: preId, ok: false, error: "stale agent report" },
    headers: { Authorization: "Bearer " + token },
  });
  cell("W5-06a report on a still-queued cmd accepted (no status guard)",
    r.status === 200 && r.json?.status === "failed",
    `${r.status} ${JSON.stringify(r.json)?.slice(0, 100)}`);
  r = await req("POST", "/api/agent/poll", {
    body: { node_name: "wk1" },
    headers: { Authorization: "Bearer " + token },
  });
  cell("W5-06b OBSERVED: poll dispatches the report-failed init_pki",
    (r.json?.commands || []).some((x) => x.id === preId),
    JSON.stringify(r.json?.commands || []));

  // ---------- W6 bundle proxy without origin ----------
  r = await req("GET", "/install-agent.sh");
  cell("W6-01 bundle proxy without AGENT_BUNDLE_ORIGIN 503", r.status === 503,
    String(r.status));

  const fails = RESULTS.filter(([, ok]) => !ok).map(([n]) => n);
  console.log(`\nTOTAL ${RESULTS.length} cells, FAIL ${fails.length}: ${JSON.stringify(fails)}`);
  process.exit(fails.length);
}

main().catch((e) => { console.error(e); process.exit(99); });

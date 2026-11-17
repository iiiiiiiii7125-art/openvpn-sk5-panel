// R43-J4 Worker/agent journey probe — Worker face (mock KV).
// Mirrors tests/r43_j4_journey.py in one continuous flow: register ->
// poll (claim guard, body token, heartbeat) -> dispatch all 13 actions
// -> report -> public-ip -> rotate token -> login lockout.
// Complements (does not duplicate) the L5/L6/F4 probes, which already
// cover claim/body-token/heartbeat-age/malformed-sent_at in isolation.
// Usage: node tests/r43_j4_journey.mjs (exit = FAIL count)
// Import uses a relative path into the same tree's cloudflare/src/index.js.
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
const BASE = "https://panel-a.example.com";
const ACTIONS_13 = ["install_prereqs", "init_pki", "create_server",
  "start_openvpn", "stop_openvpn", "restart_openvpn",
  "create_user", "revoke_user", "set_sk5", "test_sk5",
  "enable_sk5", "disable_sk5", "get_status"];

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
  const adminCookie = await loginAsAdmin("10.9.0.1");
  cell("WJ0 admin session obtained", adminCookie.length > 0);

  // --- J1: register node ---
  let r = await req("POST", "/api/nodes", {
    body: { name: "wj1", panel_url: "https://panel-a.example.com" },
    headers: { Cookie: adminCookie },
  });
  const token = r.json?.token;
  cell("WJ1 register node 201 + token shown once",
    r.status === 201 && typeof token === "string" && token.length > 20, `${r.status}`);
  r = await req("GET", "/api/nodes", { headers: { Cookie: adminCookie } });
  cell("WJ1b token NOT in node list (single disclosure)",
    !(r.text || "").includes(token), "token leaked");

  const poll = (tok, extra = {}, headersExtra = {}) => {
    const headers = { ...headersExtra };
    if (tok) headers.Authorization = "Bearer " + tok;
    return req("POST", "/api/agent/poll", {
      body: { node_name: "wj1", ...extra }, headers,
    });
  };

  // --- J2-J5: poll auth + claim guard + body token ---
  r = await poll("bad-token");
  cell("WJ2 poll with wrong token -> 401", r.status === 401, `${r.status}`);
  r = await poll(token, { panel_url: "https://panel-a.example.com" });
  cell("WJ3 poll header token + matching claim -> 200, no commands",
    r.status === 200 && Array.isArray(r.json?.commands) && r.json.commands.length === 0,
    `${r.status}`);
  r = await poll(token, { panel_url: "https://panel-B.example.com" });
  cell("WJ4 poll mismatched panel_url claim -> 403 (Fix-D L5-P2-1)",
    r.status === 403, `${r.status}`);
  r = await req("POST", "/api/agent/poll", {
    body: { node_name: "wj1", node_token: token, panel_url: "https://panel-a.example.com" },
  });
  cell("WJ5 poll body token only -> 200 (Fix-D L5-P2-2)",
    r.status === 200, `${r.status}`);

  // --- J6: heartbeat stores status but never stamps at (Fix-K) ---
  r = await poll(token, {
    panel_url: "https://panel-a.example.com",
    status: { version: "0.1.0", hostname: "wj-host", openvpn_running: true, sk5_enabled: true },
  });
  cell("WJ6 heartbeat poll 200", r.status === 200, `${r.status}`);
  r = await req("GET", "/api/nodes", { headers: { Cookie: adminCookie } });
  const wj1a = (r.json?.nodes || []).find((n) => n.name === "wj1") || {};
  cell("WJ6b heartbeat visible, age null until get_status",
    wj1a.openvpn?.running === true && wj1a.sk5_enabled === true
    && wj1a.status_age_s === null && wj1a.last_seen !== null,
    JSON.stringify(wj1a));

  // --- J7: dispatch get_status, poll delivers once ---
  r = await req("POST", "/api/cmd", {
    body: { node: "wj1", action: "get_status", params: {} },
    headers: { Cookie: adminCookie },
  });
  const cmd1 = r.json?.cmd_id;
  cell("WJ7 enqueue get_status 202", r.status === 202 && !!cmd1, `${r.status}`);
  r = await poll(token, { panel_url: "https://panel-a.example.com" });
  cell("WJ7b poll delivers the queued cmd once",
    r.status === 200 && r.json.commands.length === 1 && r.json.commands[0].id === cmd1,
    JSON.stringify(r.json?.commands));
  r = await poll(token, { panel_url: "https://panel-a.example.com" });
  cell("WJ7c second poll: sent cmd NOT re-dispatched",
    r.status === 200 && r.json.commands.length === 0, `${r.status}`);

  // --- J8: report get_status stamps at ---
  r = await req("POST", "/api/agent/report", {
    body: { node_name: "wj1", id: cmd1, ok: true,
            result: { openvpn: { running: true, online_users: 2 },
                      sk5: { enabled: false }, egress_ip: "203.0.113.55" } },
    headers: { Authorization: "Bearer " + token },
  });
  cell("WJ8 report get_status done 200",
    r.status === 200 && r.json?.status === "done", `${r.status} ${JSON.stringify(r.json)}`);
  r = await req("GET", "/api/nodes", { headers: { Cookie: adminCookie } });
  const wj1b = (r.json?.nodes || []).find((n) => n.name === "wj1") || {};
  cell("WJ8b snapshot at stamped, age ~0, egress visible",
    typeof wj1b.status_age_s === "number" && wj1b.status_age_s < 5
    && wj1b.egress_ip === "203.0.113.55",
    JSON.stringify(wj1b));

  // --- J9: all 13 actions enqueue ---
  const bad = [];
  for (const a of ACTIONS_13) {
    r = await req("POST", "/api/cmd", {
      body: { node: "wj1", action: a, params: {} },
      headers: { Cookie: adminCookie },
    });
    if (r.status !== 202) bad.push([a, r.status]);
  }
  cell("WJ9 all 13 whitelist actions enqueue (202)", bad.length === 0, JSON.stringify(bad));

  // --- J10: invalid action rejected + allowed list of 13 ---
  r = await req("POST", "/api/cmd", {
    body: { node: "wj1", action: "rm_rf", params: {} },
    headers: { Cookie: adminCookie },
  });
  cell("WJ10 invalid action -> 400 + allowed list of 13",
    r.status === 400 && Array.isArray(r.json?.allowed) && r.json.allowed.length === 13,
    `${r.status}`);

  // --- J11: report for a queued (never sent) cmd -> 409 ---
  r = await req("POST", "/api/cmd", {
    body: { node: "wj1", action: "test_sk5", params: {} },
    headers: { Cookie: adminCookie },
  });
  const qid = r.json?.cmd_id;
  r = await req("POST", "/api/agent/report", {
    body: { node_name: "wj1", id: qid, ok: true, result: {} },
    headers: { Authorization: "Bearer " + token },
  });
  cell("WJ11 report for queued (not sent) cmd -> 409", r.status === 409, `${r.status}`);

  // --- J12: malformed sent_at -> failed, not requeued (Fix-D L6-P2-2) ---
  r = await req("POST", "/api/cmd", {
    body: { node: "wj1", action: "get_status", params: {} },
    headers: { Cookie: adminCookie },
  });
  const mid = r.json?.cmd_id;
  await poll(token, { panel_url: "https://panel-a.example.com" }); // sends it
  // Corrupt BOTH the sent copy and the cmd record: the poll timeout
  // handler prefers the sent copy's sent_at (sentAtOverride), so
  // corrupting the record alone leaves a valid override behind.
  // (Same method as tests/bi_worker_malformed.mjs M-03b.)
  const sentList = await kv.get("sent:wj1", "json");
  const sentEntry = (sentList || []).find((e) => e.id === mid);
  if (sentEntry) sentEntry.sent_at = "not-a-date";
  await kv.put("sent:wj1", JSON.stringify(sentList));
  const cmdRec = await kv.get(`cmd:${mid}`, "json");
  cmdRec.sent_at = "not-a-date";
  await kv.put(`cmd:${mid}`, JSON.stringify(cmdRec));
  r = await poll(token, { panel_url: "https://panel-a.example.com" });
  const delivered = (r.json?.commands || []).map((c) => c.id);
  const after = await kv.get(`cmd:${mid}`, "json");
  cell("WJ12 malformed sent_at -> failed, not re-dispatched",
    !delivered.includes(mid) && after?.status === "failed",
    `delivered=${JSON.stringify(delivered)} status=${after?.status}`);

  // --- J13: public-ip named node ---
  r = await req("GET", "/api/openvpn/public-ip?node=wj1", { headers: { Cookie: adminCookie } });
  cell("WJ13 public-ip named node returns snapshot egress (Fix-D L6-P2-1)",
    r.status === 200 && r.json?.ip === "203.0.113.55",
    `${r.status} ${JSON.stringify(r.json)}`);

  // --- J14: token rotation ---
  r = await req("POST", "/api/nodes/wj1/rotate", { headers: { Cookie: adminCookie } });
  const newToken = r.json?.token;
  cell("WJ14 rotate returns new token",
    r.status === 200 && newToken && newToken !== token, `${r.status}`);
  r = await poll(token, { panel_url: "https://panel-a.example.com" });
  cell("WJ14b old token poll -> 401", r.status === 401, `${r.status}`);
  r = await poll(newToken, { panel_url: "https://panel-a.example.com" });
  cell("WJ14c new token poll -> 200", r.status === 200, `${r.status}`);

  // --- J15: login lockout parity (5x401 -> 429 + Retry-After 900) ---
  const statuses = [];
  for (let i = 0; i < 6; i++) {
    r = await req("POST", "/api/login", {
      body: { password: "wrong-password" },
      headers: { "CF-Connecting-IP": "10.9.0.9" },
    });
    statuses.push(r.status);
  }
  r = await req("POST", "/api/login", {
    body: { password: "wrong-password" },
    headers: { "CF-Connecting-IP": "10.9.0.9" },
  });
  const ra = r.headers.get("Retry-After");
  cell("WJ15 lockout 5x401 then 429 + Retry-After 900",
    statuses.filter((s) => s === 401).length === 5 && r.status === 429 && ra === "900",
    `statuses=${JSON.stringify(statuses)} retry_after=${ra}`);
  r = await req("POST", "/api/login", {
    body: { password: "admin-pass-123" },
    headers: { "CF-Connecting-IP": "10.9.0.9" },
  });
  cell("WJ15b correct password while locked -> 429", r.status === 429, `${r.status}`);

  // --- J16: change-password is an honest 501 in Worker mode ---
  r = await req("POST", "/api/change-password", {
    body: { old_password: "x", new_password: "y12345678901" },
    headers: { Cookie: adminCookie },
  });
  cell("WJ16 change-password -> honest 501 (R11-P2-1)",
    r.status === 501, `${r.status}`);

  const fails = RESULTS.filter(([, ok]) => !ok).length;
  console.log(`\n${RESULTS.length - fails}/${RESULTS.length} passed, ${fails} FAILED`);
  process.exit(fails);
}

main();

// AUDIT-R41-L6 Worker parity probe (r41_l6_worker_parity.mjs) — independent derivation.
// Drives cloudflare/src/index.js default.fetch with a fresh in-memory MockKV.
// Covers the route-parity gaps the historical probes never exercised:
//   public-ip / audit / path-form multi-node ovpn (Flask-only routes),
//   /nodes/<name>/install template equality vs the frontend builder,
//   change-password 501, login lockout incl. malformed-body non-counting,
//   safe-action + unparseable sent_at (server-mode.md R13-P2-1 claim),
//   bundle-proxy 503s, 72-byte-prefix login divergence (Worker side).
// Usage: node tests/r41_l6_worker_parity.mjs ; exit code = FAIL count.
// FIX LANE Fix-D (R41): L6-02/L6-03 flipped to assert the fixed
// public-ip behavior (R41-L6-P2-1 fixed) — BH-03(c) style, disclosed;
// L6-15/L6-16 already asserted the fixed sent_at contract in the audit.
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
    return { keys: keys.map((name) => ({ name })), list_complete: true };
  }
}

const kv = new MockKV();
const BASE = "https://panel.example.com";
let ENV = null; // set in main(); worker.fetch(request, env, ctx) needs env.
const RESULTS = [];
function cell(name, cond, detail = "") {
  RESULTS.push([name, !!cond]);
  console.log((cond ? "PASS " : "FAIL ") + name + (detail ? " | " + detail : ""));
}

async function req(method, path, { body, rawBody, headers = {}, contentType } = {}) {
  const h = { ...headers };
  let b;
  if (rawBody !== undefined) { b = rawBody; h["Content-Type"] = contentType || "application/json"; }
  else if (body !== undefined) { b = JSON.stringify(body); h["Content-Type"] = "application/json"; }
  const r = await worker.fetch(new Request(BASE + path, { method, headers: h, body: b }), ENV);
  let j = null;
  try { j = await r.json(); } catch { /* non-JSON */ }
  return { status: r.status, headers: r.headers, json: j, text: j === null ? await r.text().catch(() => "") : "" };
}

// Frontend buildInstallCommand replica (panel/templates/index.html:830-833 + shellQuote :818-820).
function shellQuote(s) {
  return "'" + String(s).replace(/'/g, "'\\''") + "'";
}
function buildInstallCommand(panelUrl, token, nodeName) {
  const base = String(panelUrl || BASE).replace(/\/$/, "");
  let cmd = "curl -ksSL " + shellQuote(base + "/install-agent.sh") + " -o /tmp/install-agent.sh && "
    + "curl -ksSL " + shellQuote(base + "/install-agent.sh.sha256") + " -o /tmp/install-agent.sh.sha256 && "
    + "cd /tmp && sha256sum -c install-agent.sh.sha256 && "
    + "bash /tmp/install-agent.sh --panel-url " + shellQuote(base) + " --token " + shellQuote(token);
  if (nodeName) cmd += " --node-name " + shellQuote(nodeName);
  return cmd;
}

async function main() {
  const env = { PANEL_KV: kv, ADMIN_PASSWORD: "admin-pass-123" };
  ENV = env;

  // --- login (control) ---
  let r = await req("POST", "/api/login", { body: { password: "admin-pass-123" }, headers: { "CF-Connecting-IP": "10.0.0.1" } });
  cell("L6-00 login 200 + session cookie", r.status === 200 && /panel_session=/.test(r.headers.get("set-cookie") || ""), `${r.status}`);
  const cookie = (r.headers.get("set-cookie") || "").split(";")[0];
  const admin = { Cookie: cookie };

  // --- register node (control) ---
  r = await req("POST", "/api/nodes", { body: { name: "wk1", panel_url: BASE }, headers: admin });
  cell("L6-01 register node 201", r.status === 201 && !!r.json?.token, `${r.status}`);
  const token = r.json?.token;
  const auth = { Authorization: "Bearer " + token };

  // --- W-R41-01: GET /api/openvpn/public-ip (R41-L6-P2-1 FIXED —
  // expectation flipped from the audit's gap-asserting cell, BH-03(c)
  // style, disclosed): named-node case returns the snapshot egress IP;
  // with no snapshot yet the endpoint honestly 502s (the Worker cannot
  // probe the transit host's own egress IP — Flask docstring, same).
  r = await req("GET", "/api/openvpn/public-ip", { headers: admin });
  cell("L6-02 public-ip, single node, no snapshot yet: honest 502 (never a LAN/edge IP)", r.status === 502 && /尚未上报出口 IP/.test(r.json?.error || ""), `${r.status} ${JSON.stringify(r.json)}`);
  // Named-node case: Flask R11-P1-1 returns the snapshot egress IP; Worker has the same snapshot.
  await kv.put("status:wk1", JSON.stringify({ at: Date.now(), openvpn: { running: true }, egress: { ip: "203.0.113.7" }, sk5: {}, users: [] }));
  r = await req("GET", "/api/openvpn/public-ip?node=wk1", { headers: admin });
  cell("L6-03 public-ip ?node=wk1 with snapshot egress IP: 200 ip (Flask R11-P1-1 parity)", r.status === 200 && r.json?.ip === "203.0.113.7", `${r.status} ${JSON.stringify(r.json)}`);

  // --- W-R41-02: GET /api/audit (Flask has it; Worker must 404) ---
  r = await req("GET", "/api/audit?limit=100", { headers: admin });
  cell("L6-04 audit: Worker 404 (Flask: 200 rows)", r.status === 404, `${r.status} ${JSON.stringify(r.json)}`);

  // --- W-R41-03: path-form multi-node ovpn (Flask has it; Worker must 404) ---
  r = await req("GET", "/api/nodes/wk1/users/alice/ovpn", { headers: admin });
  cell("L6-05 path-form node ovpn: Worker 404 (Flask: 200/403/404)", r.status === 404, `${r.status}`);
  // Control: compat form works once an .ovpn is reported.
  r = await req("POST", "/api/cmd", { body: { node: "wk1", action: "create_user", params: { name: "alice" } }, headers: admin });
  const cmdId = r.json?.cmd_id;
  r = await req("POST", "/api/agent/poll", { body: { node_name: "wk1" }, headers: auth });
  r = await req("POST", "/api/agent/report", { body: { cmd_id: cmdId, ok: true, result: { ovpn: "client\nremote 1.2.3.4 1194\n" } }, headers: auth });
  cell("L6-06 control: create_user report done", r.status === 200 && r.json?.status === "done", `${r.status} ${JSON.stringify(r.json)}`);
  r = await req("GET", "/api/openvpn/users/alice/ovpn?node=wk1", { headers: admin });
  cell("L6-07 control: compat ovpn download 200", r.status === 200, `${r.status}`);

  // --- W-R41-04: /nodes/<name>/install template == frontend builder ---
  r = await req("POST", "/api/nodes/wk1/install", { body: {}, headers: admin });
  const expected = buildInstallCommand(BASE, "<NODE_TOKEN>", "wk1");
  cell("L6-08 install template 200 + byte-identical to frontend buildInstallCommand",
    r.status === 200 && r.json?.command_template === expected,
    `${r.status} match=${r.json?.command_template === expected}`);

  // --- W-R41-05: change-password 501 (known honest divergence) ---
  r = await req("POST", "/api/change-password", { body: { old_password: "x", new_password: "y12345678901" }, headers: admin });
  cell("L6-09 change-password 501 + wrangler guidance", r.status === 501 && /wrangler secret put ADMIN_PASSWORD/.test(r.json?.error || ""), `${r.status}`);

  // --- W-R41-06: login lockout (fresh IP 10.0.0.2) ---
  const ip2 = { "CF-Connecting-IP": "10.0.0.2" };
  const seq = [];
  for (let i = 0; i < 5; i++) {
    r = await req("POST", "/api/login", { body: { password: "wrong" }, headers: ip2 });
    seq.push(r.status);
  }
  cell("L6-10 lockout: 5 wrong -> 401 x5", seq.every((s) => s === 401), JSON.stringify(seq));
  r = await req("POST", "/api/login", { body: { password: "wrong" }, headers: ip2 });
  cell("L6-11 lockout: 6th wrong -> 429 + Retry-After", r.status === 429 && !!r.headers.get("retry-after"), `${r.status} retry-after=${r.headers.get("retry-after")}`);
  r = await req("POST", "/api/login", { body: { password: "admin-pass-123" }, headers: ip2 });
  cell("L6-12 lockout: correct pw while locked -> 429", r.status === 429, `${r.status}`);
  r = await req("POST", "/api/login", { body: { password: "admin-pass-123" }, headers: { "CF-Connecting-IP": "10.0.0.3" } });
  cell("L6-13 lockout: other IP unaffected -> 200", r.status === 200, `${r.status}`);
  // Malformed body must not count as a failed login (fresh IP 10.0.0.4).
  const ip4 = { "CF-Connecting-IP": "10.0.0.4" };
  for (let i = 0; i < 5; i++) {
    await req("POST", "/api/login", { rawBody: "not json{", headers: ip4 });
  }
  r = await req("POST", "/api/login", { body: { password: "wrong" }, headers: ip4 });
  cell("L6-14 malformed bodies do not count: 5 malformed + 1 wrong -> 401 (not 429)", r.status === 401, `${r.status}`);

  // --- W-R41-07/08: safe action + unparseable / missing sent_at ---
  async function safeSentCase(label, sentAtValue) {
    const rr = await req("POST", "/api/cmd", { body: { node: "wk1", action: "get_status", params: {} }, headers: admin });
    const id = rr.json?.cmd_id;
    await req("POST", "/api/agent/poll", { body: { node_name: "wk1" }, headers: auth });
    const sentArr = JSON.parse((await kv.get("sent:wk1")) || "[]");
    const rec = JSON.parse((await kv.get("cmd:" + id)) || "{}");
    const e = sentArr.find((x) => x.id === id);
    if (e) e.sent_at = sentAtValue;
    rec.sent_at = sentAtValue;
    await kv.put("sent:wk1", JSON.stringify(sentArr));
    await kv.put("cmd:" + id, JSON.stringify(rec));
    const p = await req("POST", "/api/agent/poll", { body: { node_name: "wk1" }, headers: auth });
    const after = JSON.parse((await kv.get("cmd:" + id)) || "{}");
    const redispatched = (p.json?.commands || []).some((x) => x.id === id);
    return { id, after, redispatched, label };
  }
  let c = await safeSentCase("abc", "abc");
  // Contract under test: Flask R13-P2-1 (panel/app.py:746-747) marks a sent
  // command with unparseable sent_at failed immediately, never requeued;
  // server-mode.md claims the Worker does the same. Assert that contract.
  cell("L6-15 safe get_status + sent_at='abc': failed immediately, never requeued (Flask R13-P2-1 / server-mode.md)",
    c.after.status === "failed" && (c.after.retries || 0) === 0 && !c.redispatched,
    `status=${c.after.status} retries=${c.after.retries} redispatched=${c.redispatched}`);
  c = await safeSentCase("null", null);
  cell("L6-16 safe get_status + sent_at=null: failed immediately, never requeued",
    c.after.status === "failed" && (c.after.retries || 0) === 0 && !c.redispatched,
    `status=${c.after.status} retries=${c.after.retries} redispatched=${c.redispatched}`);

  // --- W-R41-09: bundle proxy without origin -> 503 on all four endpoints ---
  const bundlePaths = ["/install-agent.sh", "/install-agent.sh.sha256", "/api/agent/bundle", "/api/agent/bundle.sha256"];
  let all503 = true;
  for (const p of bundlePaths) {
    r = await req("GET", p, {});
    if (r.status !== 503) all503 = false;
    console.log(`    bundle ${p} -> ${r.status}`);
  }
  cell("L6-17 bundle proxy without AGENT_BUNDLE_ORIGIN: all four 503", all503, "");

  // --- W-R41-10: 72-byte-prefix login divergence (Worker side) ---
  const env72 = { PANEL_KV: new MockKV(), ADMIN_PASSWORD: "A".repeat(72) + "suffix-ONE" };
  const req72 = async (pw) => {
    const rr = await worker.fetch(new Request(BASE + "/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json", "CF-Connecting-IP": "10.0.0.9" },
      body: JSON.stringify({ password: pw }),
    }), env72);
    return rr.status;
  };
  const s1 = await req72("A".repeat(72) + "suffix-ONE");
  const s2 = await req72("A".repeat(72) + "suffix-TWO");
  cell("L6-18 72-byte prefix: exact password 200, same-72-prefix different suffix 401 (Flask live, bcrypt 5.0.0: full 79B string 401, 72B prefix 200 -- disjoint acceptance, report O-R41-L6-2)",
    s1 === 200 && s2 === 401, `exact=${s1} collision=${s2}`);

  const fails = RESULTS.filter(([, ok]) => !ok).map(([n]) => n);
  console.log(`\nTOTAL ${RESULTS.length} cells, FAIL ${fails.length}: ${JSON.stringify(fails)}`);
  process.exit(fails.length);
}

main().catch((e) => { console.error(e); process.exit(99); });

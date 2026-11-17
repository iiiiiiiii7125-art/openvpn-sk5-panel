// AUDIT-R42-F4 age-semantics probe (Worker face, mock KV).
// Question: what does status `at` / age_s measure on the Worker?
// Flask stamps `at` ONLY on get_status results (R11-P1-1: heartbeat
// never stamps at); a poll-only node has age null / stale true.
// FIX LANE Fix-K (R42-F4-1): the DIVERGENCE cells below are flipped
// BH-03(c) style — disclosed here, not silently rewritten. Before the
// fix they asserted the divergent behavior (poll/report stamped `at`,
// age measured time-since-poll); after the fix they assert the
// Flask-matching behavior: age stays null / stale true until the first
// get_status report lands, non-get_status reports never touch the
// snapshot, and an enable_sk5 report neither refreshes age nor
// overwrites egress. tests/r42_f4_age_flask.py asserts the Flask half
// (unchanged — Flask is the reference).
// Usage: node tests/r42_f4_age.mjs (exit = FAIL count)
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
const RESULTS = [];
function cell(name, cond, detail = "") {
  RESULTS.push([name, !!cond]);
  console.log((cond ? "PASS " : "FAIL ") + name + (detail ? " | " + detail : ""));
}
async function req(method, path, { body, headers = {} } = {}) {
  const h = { ...headers };
  let b;
  if (body !== undefined) { b = JSON.stringify(body); h["Content-Type"] = "application/json"; }
  const r = await worker.fetch(new Request(BASE + path, { method, headers: h, body: b }), env, {});
  const text = await r.text();
  let j = null;
  try { j = JSON.parse(text); } catch { /* non-json */ }
  return { status: r.status, json: j, text, headers: r.headers };
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const lr = await req("POST", "/api/login", {
    body: { password: "admin-pass-123" },
    headers: { "CF-Connecting-IP": "10.9.0.1" },
  });
  const m = (lr.headers.get("Set-Cookie") || "").match(/panel_session=([^;]+)/);
  const adminCookie = m ? `panel_session=${m[1]}` : "";
  cell("A00 admin session obtained", adminCookie.length > 0);

  const rr = await req("POST", "/api/nodes", {
    body: { name: "wk1", panel_url: "https://panel-a.example.com" },
    headers: { Cookie: adminCookie },
  });
  const token = rr.json?.token;
  cell("A01 register node", rr.status === 201 && !!token, `${rr.status}`);

  const hb = {
    version: "1.0", hostname: "h1",
    openvpn_running: true, sk5_enabled: false,
  };
  async function poll(extra = {}) {
    return req("POST", "/api/agent/poll", {
      body: { node_name: "wk1", panel_url: "https://panel-a.example.com", status: hb, ...extra },
      headers: { Authorization: "Bearer " + token },
    });
  }
  async function status() {
    const r = await req("GET", "/api/status?node=wk1", { headers: { Cookie: adminCookie } });
    return r.json;
  }

  // A1: poll-only node — heartbeat lands (L5-P2-3 holds) but age stays
  // null / stale true until a get_status report lands (R42-F4-1 fixed).
  let r = await poll();
  cell("A1 poll with heartbeat 200", r.status === 200, `${r.status}`);
  let st = await status();
  cell("A1 poll-only node shows heartbeat values",
    st?.openvpn?.running === true && st?.sk5?.enabled === false,
    JSON.stringify(st));
  cell("A1 FIXED: poll-only node age_s null, stale true (Flask-matching)",
    st?.age_s === null && st?.stale === true,
    `age_s=${st?.age_s} stale=${st?.stale} note=${st?.note}`);

  // A2: no poll for 1.2 s — age stays null (nothing was ever measured).
  await sleep(1200);
  st = await status();
  cell("A2 after 1.2s idle, age_s still null and stale",
    st?.age_s === null && st?.stale === true,
    `age_s=${st?.age_s} stale=${st?.stale}`);

  // A2b: a second poll does NOT stamp at (age stays null).
  r = await poll();
  st = await status();
  cell("A2b second poll does not stamp at, age_s still null",
    st?.age_s === null, `age_s=${st?.age_s}`);

  // A3: a create_user report (result carries NO status sections) must
  // NOT refresh at (R42-F4-1 fixed).
  r = await req("POST", "/api/cmd", {
    body: { node: "wk1", action: "create_user", params: { name: "u1" } },
    headers: { Cookie: adminCookie },
  });
  const cmd1 = r.json?.cmd_id;
  cell("A3 enqueue create_user 202", r.status === 202 && !!cmd1, `${r.status}`);
  r = await poll();
  cell("A3 poll dispatches create_user",
    r.json?.commands?.length === 1 && r.json.commands[0].id === cmd1,
    JSON.stringify(r.json?.commands));
  await sleep(1100);
  r = await req("POST", "/api/agent/report", {
    body: { node_name: "wk1", panel_url: "https://panel-a.example.com",
            id: cmd1, ok: true,
            result: { ovpn: "-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----" } },
    headers: { Authorization: "Bearer " + token },
  });
  cell("A3 report create_user 200 done", r.status === 200 && r.json?.status === "done", `${r.status}`);
  st = await status();
  cell("A3 FIXED: non-status report does not refresh at (age_s still null)",
    st?.age_s === null, `age_s=${st?.age_s}`);

  // A4: even a FAILED report with an empty-object result must NOT refresh at.
  r = await req("POST", "/api/cmd", {
    body: { node: "wk1", action: "revoke_user", params: { name: "u1" } },
    headers: { Cookie: adminCookie },
  });
  const cmd2 = r.json?.cmd_id;
  r = await poll();
  await sleep(1100);
  r = await req("POST", "/api/agent/report", {
    body: { node_name: "wk1", panel_url: "https://panel-a.example.com",
            id: cmd2, ok: false, result: {}, error: "boom" },
    headers: { Authorization: "Bearer " + token },
  });
  cell("A4 report failed revoke_user 200 failed", r.status === 200 && r.json?.status === "failed", `${r.status}`);
  st = await status();
  cell("A4 FIXED: failed empty-object report does not refresh at (age_s still null)",
    st?.age_s === null, `age_s=${st?.age_s}`);

  // A5 control: a real get_status report refreshes at AND carries full sections (both faces agree).
  r = await req("POST", "/api/cmd", {
    body: { node: "wk1", action: "get_status", params: {} },
    headers: { Cookie: adminCookie },
  });
  const cmd3 = r.json?.cmd_id;
  r = await poll();
  r = await req("POST", "/api/agent/report", {
    body: { node_name: "wk1", panel_url: "https://panel-a.example.com",
            id: cmd3, ok: true,
            result: { openvpn: { running: true, clients: [], unit_active: true, pid: 123, error: null },
                      egress_ip: "203.0.113.9", sk5: { enabled: false }, users: [] } },
    headers: { Authorization: "Bearer " + token },
  });
  cell("A5 report get_status 200 done", r.status === 200 && r.json?.status === "done", `${r.status}`);
  st = await status();
  cell("A5 control: get_status report gives age_s==0 AND full sections",
    st?.age_s === 0 && st?.openvpn?.running === true && st?.egress?.ip === "203.0.113.9",
    `age_s=${st?.age_s} egress=${JSON.stringify(st?.egress)}`);

  // A6: an enable_sk5 report carries a FLAT sk5-manager result (what
  // enable() really returns: enabled/policy_routing_active/egress_ip at
  // top level, no `sk5` object). After the fix the report must NOT touch
  // the snapshot at all: `at` stays unstamped (age null / stale true),
  // the `sk5` section keeps its honest heartbeat value (enabled false),
  // and egress is NOT overwritten with the enable result's probe IP
  // (no get_status ever ran).
  r = await req("POST", "/api/nodes", {
    body: { name: "wk2", panel_url: "https://panel-a.example.com" },
    headers: { Cookie: adminCookie },
  });
  const token2 = r.json?.token;
  cell("A6 register wk2", r.status === 201 && !!token2, `${r.status}`);
  async function poll2(extra = {}) {
    return req("POST", "/api/agent/poll", {
      body: { node_name: "wk2", panel_url: "https://panel-a.example.com", status: hb, ...extra },
      headers: { Authorization: "Bearer " + token2 },
    });
  }
  async function status2() {
    const r2 = await req("GET", "/api/status?node=wk2", { headers: { Cookie: adminCookie } });
    return r2.json;
  }
  r = await poll2();
  cell("A6 poll wk2 heartbeat 200", r.status === 200, `${r.status}`);
  r = await req("POST", "/api/cmd", {
    body: { node: "wk2", action: "enable_sk5", params: {} },
    headers: { Cookie: adminCookie },
  });
  const cmd6 = r.json?.cmd_id;
  r = await poll2();
  cell("A6 poll dispatches enable_sk5",
    r.json?.commands?.length === 1 && r.json.commands[0].id === cmd6,
    JSON.stringify(r.json?.commands));
  await sleep(1100);
  r = await req("POST", "/api/agent/report", {
    body: { node_name: "wk2", panel_url: "https://panel-a.example.com",
            id: cmd6, ok: true,
            result: { enabled: true, policy_routing_active: true,
                      egress_ip: "203.0.113.55", singbox_running: true,
                      vpn_net: "10.8.0.0/24", config_error: null,
                      singbox_config: "/etc/openvpn-sk5-panel/sing-box.json",
                      policy_script: "/etc/openvpn-sk5-panel/policy-routing.sh",
                      last_health: null } },
    headers: { Authorization: "Bearer " + token2 },
  });
  cell("A6 report enable_sk5 200 done", r.status === 200 && r.json?.status === "done", `${r.status}`);
  const st2 = await status2();
  cell("A6 FIXED: enable report does not claim fresh age (age null, stale true, sk5 keeps honest heartbeat value enabled false)",
    st2?.age_s === null && st2?.stale === true && st2?.sk5?.enabled === false,
    `age_s=${st2?.age_s} stale=${st2?.stale} sk5=${JSON.stringify(st2?.sk5)}`);
  cell("A6 FIXED: enable report does not overwrite snapshot egress (no get_status ever ran)",
    st2?.egress?.ip === null,
    `egress=${JSON.stringify(st2?.egress)}`);

  const failed = RESULTS.filter(([, ok]) => !ok).length;
  console.log(`\nTOTAL ${RESULTS.length} cells, FAIL ${failed}: ${RESULTS.filter(([, ok]) => !ok).map(([n]) => n)}`);
  process.exit(failed ? 1 : 0);
}
main();

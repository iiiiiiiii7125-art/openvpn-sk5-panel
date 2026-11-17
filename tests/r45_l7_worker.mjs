#!/usr/bin/env node
// R45-L7 Worker-face probe (mock KV), adopted by Fix-AB.
// Questions:
//  (a) Does POST /api/openvpn/server forward a user-typed server_ip?
//      R45-L7-2 FIX: yes -- it is queued with the create_server cmd,
//      recorded in servercfg on done, and re-sent with create_user
//      (W03/W13/W16); non-string / invalid values 400 (W15).
//  (a2) Does /api/status surface ovpn.remote_ip / remote_warning the
//      way Flask _remote_status_payload does? R45-L7-1 FIX: yes --
//      from the snapshot egress IP (W06/W07/W14 public+private).
//  (b) 13-action whitelist on the Worker face (re-census).
//  (c) Concurrent polls with the same token: is a queued command
//      delivered exactly once? (20 raced pairs.)
// Usage: node tests/r45_l7_worker.mjs (exit = FAIL count)
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

const ACTIONS13 = [
  "install_prereqs", "init_pki", "create_server", "start_openvpn",
  "stop_openvpn", "restart_openvpn", "create_user", "revoke_user",
  "set_sk5", "test_sk5", "enable_sk5", "disable_sk5", "get_status",
];

async function main() {
  const lr = await req("POST", "/api/login", {
    body: { password: "admin-pass-123" },
    headers: { "CF-Connecting-IP": "10.9.0.1" },
  });
  const m = (lr.headers.get("Set-Cookie") || "").match(/panel_session=([^;]+)/);
  const adminCookie = m ? `panel_session=${m[1]}` : "";
  cell("W00 admin session obtained", adminCookie.length > 0);
  const adminH = { Cookie: adminCookie };

  const reg = await req("POST", "/api/nodes", {
    body: { name: "n1", panel_url: "https://panel-a.example.com:8443" },
    headers: adminH,
  });
  cell("W01 register n1 -> 201", reg.status === 201, reg.status);
  const token = reg.json && reg.json.token;

  // (a1) server_ip drop: save with an explicit domain remote.
  const srv = await req("POST", "/api/openvpn/server", {
    body: { port: 1194, proto: "udp", server_ip: "vpn.example.com" },
    headers: adminH,
  });
  cell("W02 save server with server_ip -> 202", srv.status === 202, srv.status);
  const cmdId = srv.json && srv.json.cmd_id;
  const cmd = await req("GET", `/api/cmd/${cmdId}`, { headers: adminH });
  const params = (cmd.json && cmd.json.params) || {};
  // R45-L7-2 FIX (BH-03(c) flip, disclosed): the audit cell pinned the
  // defect (server_ip dropped). The Worker now forwards server_ip with
  // the create_server command, so the cell asserts the fixed behavior.
  cell(
    "W03 FIXED server_ip forwarded in queued params",
    params.server_ip === "vpn.example.com",
    "params=" + JSON.stringify(params),
  );

  // (a2) status surface: agent reports get_status with an egress IP.
  const poll = await req("POST", "/api/agent/poll", {
    body: { node_token: token, panel_url: "https://panel-a.example.com:8443" },
  });
  const got = (poll.json && poll.json.commands) || [];
  cell("W04 poll takes the create_server cmd", got.length === 1 && got[0].id === cmdId, JSON.stringify(got.map((c) => c.action)));
  // NOTE: the create_server cmd is completed by the W05 report below
  // (which carries cmd_id: cmdId, ok: true) -- that is what records
  // servercfg (incl. server_ip) for the W13/W16 cells.
  const rep = await req("POST", "/api/agent/report", {
    body: {
      node_token: token, cmd_id: cmdId, ok: true,
      panel_url: "https://panel-a.example.com:8443",
      result: {
        openvpn: { running: true, unit_active: true, pid: 123, clients: [], online_users: 0, error: null },
        egress_ip: "203.0.113.7",
        sk5: { enabled: false },
        users: [],
      },
    },
  });
  cell("W05 get_status report -> 200 done", rep.status === 200 && rep.json && rep.json.status === "done", rep.status);
  // W05 reported a get_status RESULT against the create_server cmd, so
  // the snapshot was not written (only get_status reports stamp it).
  // Enqueue a real get_status cmd and report it to land the snapshot.
  const gsq = await req("POST", "/api/cmd", {
    body: { node: "n1", action: "get_status", params: {} },
    headers: adminH,
  });
  const gsId = gsq.json && gsq.json.cmd_id;
  const gpoll = await req("POST", "/api/agent/poll", {
    body: { node_token: token, panel_url: "https://panel-a.example.com:8443" },
  });
  const ggot = (gpoll.json && gpoll.json.commands) || [];
  cell("W05b poll takes the get_status cmd", ggot.some((c) => c.id === gsId), JSON.stringify(ggot.map((c) => c.action)));
  const grep = await req("POST", "/api/agent/report", {
    body: {
      node_token: token, cmd_id: gsId, ok: true,
      panel_url: "https://panel-a.example.com:8443",
      result: {
        openvpn: { running: true, unit_active: true, pid: 123, clients: [], online_users: 0, error: null },
        egress_ip: "203.0.113.7",
        sk5: { enabled: false },
        users: [],
      },
    },
  });
  cell("W05c get_status report -> 200 done", grep.status === 200 && grep.json && grep.json.status === "done", grep.status);
  const st = await req("GET", "/api/status", { headers: adminH });
  const ovpn = (st.json && st.json.openvpn) || {};
  // R45-L7-1 FIX (BH-03(c) flip, disclosed): the audit cells pinned the
  // defect (no remote_ip / remote_warning on the Worker face). The
  // Worker now surfaces both from the snapshot egress IP, mirroring
  // Flask _remote_status_payload -- 203.0.113.7 is private per Python
  // ipaddress (TEST-NET-3), so the warning must fire, same as Flask F08.
  cell(
    "W06 FIXED status HAS ovpn.remote_ip",
    ovpn.remote_ip === "203.0.113.7",
    "remote_ip=" + ovpn.remote_ip,
  );
  cell(
    "W07 FIXED status HAS ovpn.remote_warning",
    typeof ovpn.remote_warning === "string" && ovpn.remote_warning.includes("203.0.113.7"),
    "remote_warning=" + ovpn.remote_warning,
  );
  cell(
    "W07b FIXED remote_is_private true for 203.0.113.7",
    ovpn.remote_is_private === true,
    "remote_is_private=" + ovpn.remote_is_private,
  );
  const pub = await req("GET", "/api/openvpn/public-ip", { headers: adminH });
  cell("W08 control: public-ip returns snapshot egress IP", pub.status === 200 && pub.json && pub.json.ip === "203.0.113.7", pub.status + " " + JSON.stringify(pub.json));

  // R45-L7-2 FIX: create_user carries the stored server_ip (from the
  // create_server save, W04b) so the agent writes it into .ovpn remote.
  const cu = await req("POST", "/api/openvpn/users", {
    body: { name: "alice" },
    headers: adminH,
  });
  cell("W13 create_user alice -> 202", cu.status === 202, cu.status);
  const cuId = cu.json && cu.json.cmd_id;
  const cuCmd = await req("GET", `/api/cmd/${cuId}`, { headers: adminH });
  const cuParams = (cuCmd.json && cuCmd.json.params) || {};
  cell(
    "W13b create_user params carry server_ip from servercfg",
    cuParams.name === "alice" && cuParams.server_ip === "vpn.example.com",
    "params=" + JSON.stringify(cuParams),
  );

  // (b) 13-action whitelist via /api/cmd.
  let ok13 = 0;
  for (const a of ACTIONS13) {
    const r = await req("POST", "/api/cmd", {
      body: { node: "n1", action: a, params: {} },
      headers: adminH,
    });
    if (r.status === 202) ok13++;
    else console.log("  action " + a + " -> " + r.status);
  }
  cell("W09 all 13 actions -> 202", ok13 === 13, ok13 + "/13");
  for (const bad of ["start", "stop", "exec", "shell"]) {
    const r = await req("POST", "/api/cmd", {
      body: { node: "n1", action: bad, params: {} },
      headers: adminH,
    });
    cell(`W10 invalid action "${bad}" -> 400`, r.status === 400, r.status);
  }
  const arr = await req("POST", "/api/cmd", {
    body: { node: "n1", action: "get_status", params: [] },
    headers: adminH,
  });
  cell("W11 params array -> 400", arr.status === 400, arr.status);

  // R45-L7-1 FIX: public vs private egress branches, via fresh
  // get_status reports (same shape as W05b/W05c).
  async function reportEgress(ip) {
    const q = await req("POST", "/api/cmd", {
      body: { node: "n1", action: "get_status", params: {} },
      headers: adminH,
    });
    const id = q.json && q.json.cmd_id;
    const p = await req("POST", "/api/agent/poll", {
      body: { node_token: token, panel_url: "https://panel-a.example.com:8443" },
    });
    const cmds = (p.json && p.json.commands) || [];
    if (!cmds.some((c) => c.id === id)) return null;
    const r = await req("POST", "/api/agent/report", {
      body: {
        node_token: token, cmd_id: id,
        panel_url: "https://panel-a.example.com:8443",
        ok: true,
        result: {
          openvpn: { running: true, unit_active: true, pid: 123, clients: [], online_users: 0, error: null },
          egress_ip: ip,
          sk5: { enabled: false },
          users: [],
        },
      },
    });
    if (r.status !== 200) return null;
    const s = await req("GET", "/api/status", { headers: adminH });
    return (s.json && s.json.openvpn) || {};
  }
  const pubOvpn = await reportEgress("1.2.3.4");
  cell("W14a public egress 1.2.3.4 -> remote_ip, no warning", pubOvpn && pubOvpn.remote_ip === "1.2.3.4" && pubOvpn.remote_warning === null && pubOvpn.remote_is_private === false, JSON.stringify(pubOvpn));
  const privOvpn = await reportEgress("192.168.1.1");
  cell("W14b private egress 192.168.1.1 -> remote_ip + warning", privOvpn && privOvpn.remote_ip === "192.168.1.1" && typeof privOvpn.remote_warning === "string" && privOvpn.remote_warning.includes("192.168.1.1") && privOvpn.remote_is_private === true, JSON.stringify(privOvpn));

  // R45-L7-2 FIX: server_ip validation at enqueue (Flask messages).
  const badType = await req("POST", "/api/openvpn/server", {
    body: { port: 1194, proto: "udp", server_ip: 123 },
    headers: adminH,
  });
  cell("W15a server_ip 123 -> 400 strict-str", badType.status === 400 && (badType.json && badType.json.error || "").includes("server_ip 须为字符串，收到 int"), badType.status + " " + JSON.stringify(badType.json));
  const badVal = await req("POST", "/api/openvpn/server", {
    body: { port: 1194, proto: "udp", server_ip: "bad ip" },
    headers: adminH,
  });
  cell("W15b server_ip 'bad ip' -> 400 invalid", badVal.status === 400 && (badVal.json && badVal.json.error || "").includes("server_ip 不合法"), badVal.status + " " + JSON.stringify(badVal.json));
  const clearSave = await req("POST", "/api/openvpn/server", {
    body: { port: 1194, proto: "udp", server_ip: "" },
    headers: adminH,
  });
  cell("W15c server_ip '' (clear) -> 202", clearSave.status === 202, clearSave.status);
  // R45-L7-2 FIX: clear path -- report the clear-save done, then a
  // create_user must NOT carry server_ip.
  const clearId = clearSave.json && clearSave.json.cmd_id;
  const cpoll = await req("POST", "/api/agent/poll", {
    body: { node_token: token, panel_url: "https://panel-a.example.com:8443" },
  });
  const ccmds = (cpoll.json && cpoll.json.commands) || [];
  cell("W16a poll takes the clear-save cmd", ccmds.some((c) => c.id === clearId), JSON.stringify(ccmds.map((c) => c.id)));
  const crep = await req("POST", "/api/agent/report", {
    body: {
      node_token: token, cmd_id: clearId,
      panel_url: "https://panel-a.example.com:8443",
      ok: true,
      result: { proto: "udp", port: 1194 },
    },
  });
  cell("W16b clear-save report -> 200 done", crep.status === 200 && crep.json && crep.json.status === "done", crep.status);
  const cu2 = await req("POST", "/api/openvpn/users", {
    body: { name: "bob" },
    headers: adminH,
  });
  const cu2Id = cu2.json && cu2.json.cmd_id;
  const cu2Cmd = await req("GET", `/api/cmd/${cu2Id}`, { headers: adminH });
  const cu2Params = (cu2Cmd.json && cu2Cmd.json.params) || {};
  cell(
    "W16c create_user bob after clear carries no server_ip",
    cu2Params.name === "bob" && !("server_ip" in cu2Params),
    "params=" + JSON.stringify(cu2Params),
  );

  // (c) Raced polls: enqueue one cmd, fire two polls concurrently.
  let dups = 0;
  let rounds = 0;
  for (let i = 0; i < 20; i++) {
    const enq = await req("POST", "/api/cmd", {
      body: { node: "n1", action: "create_user", params: { name: `race${i}` } },
      headers: adminH,
    });
    const id = enq.json && enq.json.cmd_id;
    const [p1, p2] = await Promise.all([
      req("POST", "/api/agent/poll", { body: { node_token: token, panel_url: "https://panel-a.example.com:8443" } }),
      req("POST", "/api/agent/poll", { body: { node_token: token, panel_url: "https://panel-a.example.com:8443" } }),
    ]);
    const ids = [...((p1.json && p1.json.commands) || []), ...((p2.json && p2.json.commands) || [])].map((c) => c.id);
    const n = ids.filter((x) => x === id).length;
    rounds++;
    if (n > 1) dups++;
    // drain: report the cmd done so the next round starts clean
    if (n >= 1) {
      await req("POST", "/api/agent/report", {
        body: { node_token: token, cmd_id: id, ok: true, panel_url: "https://panel-a.example.com:8443", result: { name: `race${i}`, ovpn: "x" } },
      });
    }
  }
  cell("W12 raced polls deliver each cmd exactly once (20 rounds)", dups === 0, `dup-rounds=${dups}/${rounds} (0 dups = no duplicate observed in this interleaving)`);

  const fails = RESULTS.filter(([, ok]) => !ok).length;
  console.log(`TOTAL ${RESULTS.length} cells, FAIL ${fails}: [${RESULTS.filter(([, ok]) => !ok).map(([n]) => n).join(", ")}]`);
  process.exit(fails);
}

main();

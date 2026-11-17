// R46-L7 cross-face contract v2 -- Worker half (new fields).
// Mirror of tests/r46_l7_contract.py (Flask). The R44-L4 Worker probe
// (tests/r44_l4_worker.mjs) is the baseline census (re-run on e7f18ff:
// 79/79). The R45 Fix-AD Worker probe covered the basic staleness
// matrix (old/current/none/origin-down); this probe adds the contract
// angles: malformed + non-string + empty hashes, get_status merge
// survival, poll-only age semantics, and the distribution endpoints
// with an origin configured (bundle + sha256 + install script + the
// install template's --force shape).
// Origin fetch is stubbed via globalThis.fetch.
// Usage: node tests/r46_l7_contract.mjs (exit = FAIL count)
import worker from "../cloudflare/src/index.js";
import { createHash } from "node:crypto";

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

const BUNDLE_BYTES = Buffer.from("fake-agent-bundle-bytes");
// The origin's bundle.sha256 MUST be the sha256 of the bundle it serves:
// handleAgentBundle verifies the bundle against it and fail-closes (502)
// on mismatch. So the "current" hash is derived from the stub bytes.
const ORIGIN_HASH = createHash("sha256").update(BUNDLE_BYTES).digest("hex");
const OLD_HASH = "0".repeat(64);
let originMode = "ok"; // ok | down | badsha
globalThis.fetch = async (url) => {
  const u = String(url);
  if (originMode === "down") throw new Error("origin down");
  if (u.endsWith("/api/agent/bundle.sha256")) {
    if (originMode === "badsha") return new Response("not-a-hash\n", { status: 200 });
    if (originMode === "mismatch") return new Response(`${"c".repeat(64)}  ovpn-agent-bundle.tar.gz\n`, { status: 200 });
    return new Response(`${ORIGIN_HASH}  ovpn-agent-bundle.tar.gz\n`, { status: 200 });
  }
  if (u.endsWith("/api/agent/bundle")) {
    return new Response(BUNDLE_BYTES, { status: 200 });
  }
  if (u.endsWith("/install-agent.sh")) {
    return new Response("#!/bin/bash\necho agent-install-stub\n", { status: 200 });
  }
  if (u.endsWith("/install-agent.sh.sha256")) {
    return new Response(`${"b".repeat(64)}  install-agent.sh\n`, { status: 200 });
  }
  return new Response("not found", { status: 404 });
};

function makeEnv() {
  return {
    PANEL_KV: new MockKV(),
    ADMIN_PASSWORD: "admin-pass-123",
    AGENT_BUNDLE_ORIGIN: "https://origin.example:8443",
  };
}
const env = makeEnv();
const BASE = "https://panel-a.example.com";
const RESULTS = [];
const FAILURES = [];
function cell(name, ok, detail = "") {
  RESULTS.push([name, !!ok]);
  console.log((ok ? "PASS " : "FAIL ") + name + (detail ? " | " + detail : ""));
  if (!ok) FAILURES.push(name);
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

async function main() {
  const lr = await req("POST", "/api/login", {
    body: { password: "admin-pass-123" }, headers: { "CF-Connecting-IP": "10.9.0.1" },
  });
  const m = (lr.headers.get("Set-Cookie") || "").match(/panel_session=([^;]+)/);
  const auth = m ? { Cookie: `panel_session=${m[1]}` } : {};
  cell("D00 admin session obtained", !!m, `${lr.status}`);

  const rr = await req("POST", "/api/nodes", {
    body: { name: "n1", panel_url: "https://panel-a.example.com" }, headers: auth,
  });
  const token = rr.json?.token;
  cell("D00b register n1", rr.status === 201 && !!token, `${rr.status}`);

  const HB = { version: "1.0", hostname: "h1", openvpn_running: true, sk5_enabled: false };
  async function poll(tok, status) {
    return req("POST", "/api/agent/poll", {
      body: { node_name: "n1", panel_url: "https://panel-a.example.com", status },
      headers: { Authorization: "Bearer " + tok },
    });
  }
  async function status(name = "n1") {
    const r = await req("GET", `/api/status?node=${name}`, { headers: auth });
    return r.json;
  }
  async function nodeEntry(name = "n1") {
    const nl = await req("GET", "/api/nodes", { headers: auth });
    return (nl.json?.nodes || []).find((n) => n.name === name) || {};
  }

  // D01: origin hash -> outdated False, on both reads.
  let pr = await poll(token, { ...HB, bundle_sha256: ORIGIN_HASH });
  cell("D01 origin hash poll 200", pr.status === 200, `${pr.status}`);
  let st = await status();
  cell("D01 /api/status origin hash -> outdated False",
    st?.agent_bundle_sha256 === ORIGIN_HASH && st?.agent_code_outdated === false,
    JSON.stringify({ i: st?.agent_bundle_sha256, o: st?.agent_code_outdated }));
  let e = await nodeEntry();
  cell("D01b /api/nodes same values",
    e?.agent_bundle_sha256 === ORIGIN_HASH && e?.agent_code_outdated === false,
    JSON.stringify({ i: e?.agent_bundle_sha256, o: e?.agent_code_outdated }));

  // D02: old valid hash -> outdated True.
  await poll(token, { ...HB, bundle_sha256: OLD_HASH });
  st = await status();
  cell("D02 old valid hash -> outdated True",
    st?.agent_bundle_sha256 === OLD_HASH && st?.agent_code_outdated === true,
    JSON.stringify({ o: st?.agent_code_outdated }));

  // D03: malformed string -> installed kept, outdated True (must agree
  // with Flask C03; a split is a finding).
  await poll(token, { ...HB, bundle_sha256: "garbage-not-hex" });
  st = await status();
  cell("D03 malformed string hash -> installed kept, outdated True",
    st?.agent_bundle_sha256 === "garbage-not-hex" && st?.agent_code_outdated === true,
    JSON.stringify({ i: st?.agent_bundle_sha256, o: st?.agent_code_outdated }));

  // D04/D05/D06: non-string / empty / absent -> unknown.
  await poll(token, { ...HB, bundle_sha256: 123 });
  st = await status();
  cell("D04 int hash -> installed null, outdated null",
    st?.agent_bundle_sha256 === null && st?.agent_code_outdated === null,
    JSON.stringify({ i: st?.agent_bundle_sha256, o: st?.agent_code_outdated }));
  // D04b: null hash after a valid hash -> the agent's "unknown" (the
  // realistic case: the agent sends bundle_sha256: null whenever its
  // bundle.sha256 record is missing or malformed). Flask C04b clears
  // to unknown; the Worker must agree.
  await poll(token, { ...HB, bundle_sha256: ORIGIN_HASH });
  await poll(token, { ...HB, bundle_sha256: null });
  st = await status();
  cell("D04b null hash after valid hash -> installed null, outdated null",
    st?.agent_bundle_sha256 === null && st?.agent_code_outdated === null,
    JSON.stringify({ i: st?.agent_bundle_sha256, o: st?.agent_code_outdated }));
  await poll(token, { ...HB, bundle_sha256: "" });
  st = await status();
  cell("D05 empty-string hash -> installed null, outdated null",
    st?.agent_bundle_sha256 === null && st?.agent_code_outdated === null,
    JSON.stringify({ i: st?.agent_bundle_sha256, o: st?.agent_code_outdated }));
  await poll(token, { ...HB });
  st = await status();
  cell("D06 no hash -> installed null, outdated null",
    st?.agent_bundle_sha256 === null && st?.agent_code_outdated === null,
    JSON.stringify({ i: st?.agent_bundle_sha256, o: st?.agent_code_outdated }));

  // D07: get_status report after a heartbeat must NOT clobber the hash.
  await poll(token, { ...HB, bundle_sha256: ORIGIN_HASH });
  const cr = await req("POST", "/api/cmd", {
    body: { node: "n1", action: "get_status" }, headers: auth,
  });
  const cmdId = cr.json?.cmd_id || "";
  cell("D07a enqueue get_status 202", cr.status === 202 && !!cmdId, `${cr.status}`);
  await poll(token, { ...HB, bundle_sha256: ORIGIN_HASH });
  const rp = await req("POST", "/api/agent/report", {
    body: {
      node_token: token, cmd_id: cmdId, ok: true,
      result: { openvpn: { running: true }, users: [], sk5: { enabled: false }, egress_ip: null, health: null },
    },
  });
  cell("D07b report ok 200", rp.status === 200, `${rp.status}`);
  st = await status();
  e = await nodeEntry();
  cell("D07 get_status report keeps bundle hash (merge survival)",
    st?.agent_bundle_sha256 === ORIGIN_HASH && st?.agent_code_outdated === false
    && e?.agent_bundle_sha256 === ORIGIN_HASH,
    JSON.stringify({ s: st?.agent_bundle_sha256, e: e?.agent_bundle_sha256 }));
  cell("D07c get_status report stamps at (age_s small, stale false)",
    st?.age_s !== null && st?.age_s !== undefined && st?.age_s < 60 && st?.stale === false,
    `age_s=${st?.age_s} stale=${st?.stale}`);

  // D08: poll-only node -> bundle fields present, age unknown.
  const rr2 = await req("POST", "/api/nodes", {
    body: { name: "n2", panel_url: "https://panel-a.example.com" }, headers: auth,
  });
  const token2 = rr2.json?.token;
  await req("POST", "/api/agent/poll", {
    body: { node_name: "n2", panel_url: "https://panel-a.example.com", status: { ...HB, bundle_sha256: ORIGIN_HASH } },
    headers: { Authorization: "Bearer " + token2 },
  });
  const st2 = await status("n2");
  cell("D08 poll-only node: bundle fields present, age_s null, stale true",
    st2?.agent_bundle_sha256 === ORIGIN_HASH && st2?.agent_code_outdated === false
    && st2?.age_s === null && st2?.stale === true,
    `age_s=${st2?.age_s} stale=${st2?.stale}`);

  // D09: distribution endpoints with an origin configured.
  let r = await req("GET", "/api/agent/bundle.sha256", { headers: auth });
  cell("D09 bundle.sha256 with origin -> 200, origin hash",
    r.status === 200 && r.text.startsWith(ORIGIN_HASH), `${r.status} ${r.text.slice(0, 70)}`);
  r = await req("GET", "/api/agent/bundle", { headers: auth });
  cell("D09b bundle with origin -> 200 bytes",
    r.status === 200 && r.text.length > 0, `${r.status} ${r.text.length}`);
  r = await req("GET", "/install-agent.sh", { headers: auth });
  cell("D09c install-agent.sh with origin -> 200",
    r.status === 200 && r.text.includes("agent-install-stub"), `${r.status}`);
  r = await req("GET", "/install-agent.sh.sha256", { headers: auth });
  cell("D09d install-agent.sh.sha256 with origin -> 200, 64-hex",
    r.status === 200 && /^[0-9a-f]{64}/.test(r.text.trim()), `${r.status} ${r.text.slice(0, 20)}`);
  // D09e: bundle bytes whose hash does NOT match the origin's sha256 ->
  // 502 fail-closed (handleAgentBundle verifies before serving). Fresh
  // env so no cached origin hash masks the mismatch.
  originMode = "mismatch";
  const env3 = makeEnv();
  const lr3 = await worker.fetch(new Request(BASE + "/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json", "CF-Connecting-IP": "10.9.0.1" },
    body: JSON.stringify({ password: "admin-pass-123" }),
  }), env3, {});
  const m3 = (lr3.headers.get("Set-Cookie") || "").match(/panel_session=([^;]+)/);
  const auth3 = m3 ? { Cookie: `panel_session=${m3[1]}` } : {};
  const br3 = await worker.fetch(new Request(BASE + "/api/agent/bundle", {
    method: "GET", headers: { Cookie: auth3.Cookie },
  }), env3, {});
  cell("D09e bundle/sha256 mismatch -> 502 (fail-closed verification)",
    br3.status === 502, `${br3.status} ${(await br3.text()).slice(0, 80)}`);
  originMode = "ok";

  // D10: install template is the fresh-install command: no --force.
  // The update path is the frontend's buildUpdateCommand (Flask C09b),
  // not this template -- assert the fact so a future --force addition
  // here is a deliberate decision, not an accident.
  r = await req("POST", "/api/nodes/n1/install", { body: {}, headers: auth });
  const tpl = r.json?.command_template || "";
  cell("D10 install template has --token and no --force",
    r.status === 200 && tpl.includes("--token") && !tpl.includes("--force"),
    `${r.status} ${tpl.slice(0, 120)}`);

  // D11: origin returns a malformed sha -> outdated unknown, never a lie.
  originMode = "badsha";
  const env2 = makeEnv();
  const lr2 = await worker.fetch(new Request(BASE + "/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json", "CF-Connecting-IP": "10.9.0.1" },
    body: JSON.stringify({ password: "admin-pass-123" }),
  }), env2, {});
  const m2 = (lr2.headers.get("Set-Cookie") || "").match(/panel_session=([^;]+)/);
  const auth2 = m2 ? { Cookie: `panel_session=${m2[1]}` } : {};
  const rr3 = await worker.fetch(new Request(BASE + "/api/nodes", {
    method: "POST",
    headers: { "Content-Type": "application/json", Cookie: auth2.Cookie },
    body: JSON.stringify({ name: "n3", panel_url: "https://panel-a.example.com" }),
  }), env2, {});
  const token3 = (await rr3.json())?.token;
  await worker.fetch(new Request(BASE + "/api/agent/poll", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token3 },
    body: JSON.stringify({
      node_name: "n3", panel_url: "https://panel-a.example.com",
      status: { ...HB, bundle_sha256: OLD_HASH },
    }),
  }), env2, {});
  const st3r = await worker.fetch(new Request(BASE + "/api/status?node=n3", {
    method: "GET", headers: { Cookie: auth2.Cookie },
  }), env2, {});
  const st3 = await st3r.json();
  cell("D11 origin bad sha -> outdated null (unknown), installed kept",
    st3?.agent_code_outdated === null && st3?.agent_bundle_sha256 === OLD_HASH,
    JSON.stringify({ o: st3?.agent_code_outdated, i: st3?.agent_bundle_sha256 }));

  const fails = FAILURES.length;
  console.log(`\nTOTAL: PASS=${RESULTS.length - fails} FAIL=${fails} ${JSON.stringify(FAILURES)}`);
  process.exit(fails);
}

main().catch((e) => { console.error("probe crashed:", e); process.exit(2); });

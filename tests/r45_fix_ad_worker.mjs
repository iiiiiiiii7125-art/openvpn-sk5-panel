// R45-LIVE-2 agent-delivery probe -- Worker half (r45_fix_ad.py is
// the Flask half, r45_fix_ad_install.sh is the installer half).
// The Worker passes the agent's bundle_sha256 heartbeat key through
// to the snapshot and computes agent_code_outdated against the origin
// bundle hash (KV-cached 1h): True = stale, False = current,
// None = unknown (no hash reported, or origin unreachable -- never a
// lie). Origin fetch is stubbed via globalThis.fetch.
// Usage: node tests/r45_fix_ad_worker.mjs (exit = FAIL count)
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

const ORIGIN_HASH = "a".repeat(64);
const OLD_HASH = "0".repeat(64);
let originReachable = true;
globalThis.fetch = async (url) => {
  if (!originReachable) throw new Error("origin down");
  if (String(url).endsWith("/api/agent/bundle.sha256")) {
    return new Response(`${ORIGIN_HASH}  ovpn-agent-bundle.tar.gz\n`, { status: 200 });
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

async function main() {
  const lr = await req("POST", "/api/login", {
    body: { password: "admin-pass-123" },
    headers: { "CF-Connecting-IP": "10.9.0.1" },
  });
  const m = (lr.headers.get("Set-Cookie") || "").match(/panel_session=([^;]+)/);
  const adminCookie = m ? `panel_session=${m[1]}` : "";
  cell("W00 admin session obtained", adminCookie.length > 0);

  const rr = await req("POST", "/api/nodes", {
    body: { name: "wk-ad", panel_url: "https://panel-a.example.com" },
    headers: { Cookie: adminCookie },
  });
  const token = rr.json?.token;
  cell("W01 register wk-ad", rr.status === 201 && !!token, `${rr.status}`);

  const HB = { version: "1.0", hostname: "h1", openvpn_running: true, sk5_enabled: false };
  async function poll(name, tok, status) {
    return req("POST", "/api/agent/poll", {
      body: { node_name: name, panel_url: "https://panel-a.example.com", status },
      headers: { Authorization: "Bearer " + tok },
    });
  }
  async function status(name) {
    const r = await req("GET", `/api/status?node=${name}`, { headers: { Cookie: adminCookie } });
    return r.json;
  }

  // W02: old hash -> outdated True.
  let pr = await poll("wk-ad", token, { ...HB, bundle_sha256: OLD_HASH });
  cell("W02 poll with old hash 200", pr.status === 200, `${pr.status}`);
  let st = await status("wk-ad");
  cell("W02 /api/status outdated True for old hash",
    st?.agent_code_outdated === true && st?.agent_bundle_sha256 === OLD_HASH,
    JSON.stringify(st?.agent_code_outdated));

  // W03: current (origin) hash -> outdated False.
  pr = await poll("wk-ad", token, { ...HB, bundle_sha256: ORIGIN_HASH });
  cell("W03 poll with origin hash 200", pr.status === 200, `${pr.status}`);
  st = await status("wk-ad");
  cell("W03 /api/status outdated False for origin hash",
    st?.agent_code_outdated === false && st?.agent_bundle_sha256 === ORIGIN_HASH,
    JSON.stringify(st?.agent_code_outdated));

  // W04: fresh node, no hash reported -> unknown (None), never a lie.
  const rr2 = await req("POST", "/api/nodes", {
    body: { name: "wk-ad2", panel_url: "https://panel-a.example.com" },
    headers: { Cookie: adminCookie },
  });
  const token2 = rr2.json?.token;
  cell("W04 register wk-ad2", rr2.status === 201 && !!token2, `${rr2.status}`);
  pr = await poll("wk-ad2", token2, { ...HB });
  cell("W04 poll without hash 200", pr.status === 200, `${pr.status}`);
  st = await status("wk-ad2");
  cell("W04 /api/status unknown: installed null, outdated null",
    st?.agent_bundle_sha256 === null && st?.agent_code_outdated === null,
    JSON.stringify({ i: st?.agent_bundle_sha256, o: st?.agent_code_outdated }));

  // W05: nodes list carries the same flags.
  const nl = await req("GET", "/api/nodes", { headers: { Cookie: adminCookie } });
  const e1 = (nl.json?.nodes || []).find((n) => n.name === "wk-ad");
  const e2 = (nl.json?.nodes || []).find((n) => n.name === "wk-ad2");
  cell("W05 /api/nodes wk-ad outdated False",
    e1?.agent_code_outdated === false && e1?.agent_bundle_sha256 === ORIGIN_HASH,
    JSON.stringify(e1?.agent_code_outdated));
  cell("W05b /api/nodes wk-ad2 unknown",
    e2?.agent_bundle_sha256 === null && e2?.agent_code_outdated === null,
    JSON.stringify({ i: e2?.agent_bundle_sha256, o: e2?.agent_code_outdated }));

  // W06: origin unreachable -> unknown, not a stale verdict. Fresh
  // env (fresh KV: no cached origin hash) + fetch throwing.
  const env2 = makeEnv();
  originReachable = false;
  const lr2 = await (async () => {
    const r = await worker.fetch(new Request(BASE + "/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json", "CF-Connecting-IP": "10.9.0.1" },
      body: JSON.stringify({ password: "admin-pass-123" }),
    }), env2, {});
    return r;
  })();
  const m2 = (lr2.headers.get("Set-Cookie") || "").match(/panel_session=([^;]+)/);
  const cookie2 = m2 ? `panel_session=${m2[1]}` : "";
  const rr3 = await worker.fetch(new Request(BASE + "/api/nodes", {
    method: "POST",
    headers: { "Content-Type": "application/json", Cookie: cookie2 },
    body: JSON.stringify({ name: "wk-ad3", panel_url: "https://panel-a.example.com" }),
  }), env2, {});
  const token3 = (await rr3.json())?.token;
  const pr3 = await worker.fetch(new Request(BASE + "/api/agent/poll", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + token3 },
    body: JSON.stringify({
      node_name: "wk-ad3", panel_url: "https://panel-a.example.com",
      status: { ...HB, bundle_sha256: OLD_HASH },
    }),
  }), env2, {});
  const st3r = await worker.fetch(new Request(BASE + "/api/status?node=wk-ad3", {
    method: "GET", headers: { Cookie: cookie2 },
  }), env2, {});
  const st3 = await st3r.json();
  cell("W06 origin down: outdated null (unknown), installed kept",
    pr3.status === 200 && st3?.agent_code_outdated === null
    && st3?.agent_bundle_sha256 === OLD_HASH,
    JSON.stringify({ o: st3?.agent_code_outdated, i: st3?.agent_bundle_sha256 }));

  const fails = RESULTS.filter(([, ok]) => !ok).length;
  console.log("----");
  console.log(`checks=${RESULTS.length} failures=${fails}`);
  process.exit(fails ? 1 : 0);
}

main().catch((e) => { console.error("probe crashed:", e); process.exit(2); });

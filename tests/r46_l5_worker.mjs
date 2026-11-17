// R46-L5 state-machine v2 probe -- Worker half: bundle_sha256 states x
// Worker cachedStatus / handleListNodes, incl. the KV-cached origin hash.
//
// Headline: originBundleSha256 caches the origin bundle hash in KV for
// 1h. After the panel ships a new bundle, the Worker keeps comparing
// against the OLD hash for up to an hour: a current agent reads stale,
// a stale agent reads current. W07 cells PINNED that defective behavior
// (finding R46-L5-1) -- they passed when the defect reproduced.
// BH-03(c) FLIP (Fix-AF, R46): originBundleSha256 now re-fetches whenever
// the origin is reachable and the KV cache is only a fallback when the
// fetch fails, so W07a/b/c assert the FIXED behavior (fresh cache no
// longer overrides a reachable origin). W08 (expired cache heals) is
// unchanged.
// Origin fetch is stubbed via globalThis.fetch (mutable origin hash).
// Usage: node tests/r46_l5_worker.mjs (exit = FAIL count)
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

const CUR_HASH = "a".repeat(64);   // what the origin serves right now
const OLD_HASH = "0".repeat(64);   // a previous bundle
let originHash = CUR_HASH;
let originReachable = true;
globalThis.fetch = async (url) => {
  if (!originReachable) throw new Error("origin down");
  if (String(url).endsWith("/api/agent/bundle.sha256")) {
    return new Response(`${originHash}  ovpn-agent-bundle.tar.gz\n`, { status: 200 });
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
const BASE = "https://panel-a.example.com";
const RESULTS = [];
function cell(name, cond, detail = "") {
  RESULTS.push([name, !!cond]);
  console.log((cond ? "PASS " : "FAIL ") + name + (detail ? " | " + detail : ""));
}
async function req(env, method, path, { body, headers = {} } = {}) {
  const h = { ...headers };
  let b;
  if (body !== undefined) { b = JSON.stringify(body); h["Content-Type"] = "application/json"; }
  const r = await worker.fetch(new Request(BASE + path, { method, headers: h, body: b }), env, {});
  const text = await r.text();
  let j = null;
  try { j = JSON.parse(text); } catch { /* non-json */ }
  return { status: r.status, json: j, text, headers: r.headers };
}
async function login(env) {
  const lr = await req(env, "POST", "/api/login", {
    body: { password: "admin-pass-123" },
    headers: { "CF-Connecting-IP": "10.9.0.1" },
  });
  const m = (lr.headers.get("Set-Cookie") || "").match(/panel_session=([^;]+)/);
  return m ? `panel_session=${m[1]}` : "";
}
const HB = { version: "1.0", hostname: "h1", openvpn_running: true, sk5_enabled: false };

async function main() {
  const env = makeEnv();
  const adminCookie = await login(env);
  cell("W00 admin session obtained", adminCookie.length > 0);

  async function register(name) {
    const rr = await req(env, "POST", "/api/nodes", {
      body: { name, panel_url: "https://panel-a.example.com" },
      headers: { Cookie: adminCookie },
    });
    return rr.json?.token;
  }
  async function poll(name, tok, status) {
    return req(env, "POST", "/api/agent/poll", {
      body: { node_name: name, panel_url: "https://panel-a.example.com", status },
      headers: { Authorization: "Bearer " + tok },
    });
  }
  async function status(name) {
    const r = await req(env, "GET", `/api/status?node=${name}`, { headers: { Cookie: adminCookie } });
    return r.json;
  }
  async function nodesList() {
    const r = await req(env, "GET", "/api/nodes", { headers: { Cookie: adminCookie } });
    return r.json?.nodes || [];
  }

  const token = await register("wk-l5");
  cell("W01 register wk-l5", !!token);

  // W02: current (origin) hash -> False.
  let pr = await poll("wk-l5", token, { ...HB, bundle_sha256: CUR_HASH });
  cell("W02 poll current hash 200", pr.status === 200, `${pr.status}`);
  let st = await status("wk-l5");
  cell("W02 origin hash: outdated False",
    st?.agent_code_outdated === false && st?.agent_bundle_sha256 === CUR_HASH,
    JSON.stringify(st?.agent_code_outdated));

  // W03: old hash -> True.
  pr = await poll("wk-l5", token, { ...HB, bundle_sha256: OLD_HASH });
  st = await status("wk-l5");
  cell("W03 old hash: outdated True",
    st?.agent_code_outdated === true && st?.agent_bundle_sha256 === OLD_HASH,
    JSON.stringify(st?.agent_code_outdated));

  // W04: malformed string -> True (same as Flask: any non-empty string
  // is treated as a comparable hash).
  pr = await poll("wk-l5", token, { ...HB, bundle_sha256: "xyz" });
  st = await status("wk-l5");
  cell("W04 malformed 'xyz': installed kept, outdated True",
    st?.agent_code_outdated === true && st?.agent_bundle_sha256 === "xyz",
    JSON.stringify(st));

  // W05: number -> BH-03(c) flip (Fix-AF, R46-L7-1): the key is present
  // but not a string, so null is written into the snapshot (Flask
  // _touch_node merge semantics) and the verdict goes unknown -- the
  // previous string hash must NOT persist. The audit cell pinned the
  // defective freeze ("previous string hash persists (merge keeps)").
  pr = await poll("wk-l5", token, { ...HB, bundle_sha256: 123 });
  st = await status("wk-l5");
  cell("W05 number hash: installed null, outdated null (unknown, not frozen)",
    st?.agent_bundle_sha256 === null && st?.agent_code_outdated === null,
    JSON.stringify(st));

  // W06: get_status report preserves the hash (merge, not replace).
  const cr = await req(env, "POST", "/api/cmd", {
    body: { node: "wk-l5", action: "get_status", params: {} },
    headers: { Cookie: adminCookie },
  });
  const cmdId = cr.json?.cmd_id;
  cell("W06 enqueue get_status", cr.status === 202 && !!cmdId, `${cr.status}`);
  pr = await poll("wk-l5", token, { ...HB, bundle_sha256: CUR_HASH });
  const dispatched = (pr.json?.commands || []).some((c) => c.id === cmdId);
  cell("W06 poll dispatches get_status", dispatched, JSON.stringify(pr.json?.commands));
  const rr = await req(env, "POST", "/api/agent/report", {
    body: { node_name: "wk-l5", panel_url: "https://panel-a.example.com",
            cmd_id: cmdId, ok: true,
            result: { openvpn: { running: true, clients: [] }, users: [],
                      sk5: { enabled: false }, egress_ip: null } },
    headers: { Authorization: "Bearer " + token },
  });
  cell("W06 report get_status 200", rr.status === 200, `${rr.status}`);
  st = await status("wk-l5");
  cell("W06 get_status report keeps hash + stamps age",
    st?.agent_bundle_sha256 === CUR_HASH && st?.agent_code_outdated === false
    && st?.age_s !== null && st?.age_s <= 60, JSON.stringify(st));

  // W07: KV-cache staleness, both directions. Seed the cache with the
  // OLD hash (fresh), origin now serves CUR. BH-03(c) flip (Fix-AF):
  // a reachable origin is re-fetched, so the fresh cache no longer
  // overrides it -- current agent reads fresh, stale agent reads stale.
  await env.PANEL_KV.put("origin_bundle_sha256",
    JSON.stringify({ hash: OLD_HASH, at: Date.now() }));
  pr = await poll("wk-l5", token, { ...HB, bundle_sha256: CUR_HASH });
  st = await status("wk-l5");
  cell("W07a fresh OLD cache + reachable origin + current agent: outdated False",
    st?.agent_code_outdated === false && st?.agent_bundle_sha256 === CUR_HASH,
    JSON.stringify(st?.agent_code_outdated));
  pr = await poll("wk-l5", token, { ...HB, bundle_sha256: OLD_HASH });
  st = await status("wk-l5");
  cell("W07b fresh OLD cache + reachable origin + stale agent: outdated True",
    st?.agent_code_outdated === true && st?.agent_bundle_sha256 === OLD_HASH,
    JSON.stringify(st?.agent_code_outdated));
  let nl = await nodesList();
  let e = nl.find((n) => n.name === "wk-l5");
  cell("W07c handleListNodes agrees (stale agent outdated True)",
    e?.agent_code_outdated === true, JSON.stringify(e?.agent_code_outdated));

  // W08: expire the cache -> Worker re-fetches the origin and heals.
  await env.PANEL_KV.put("origin_bundle_sha256",
    JSON.stringify({ hash: OLD_HASH, at: Date.now() - 2 * 3600 * 1000 }));
  st = await status("wk-l5");
  cell("W08a expired cache + stale agent: outdated True again (healed)",
    st?.agent_code_outdated === true && st?.agent_bundle_sha256 === OLD_HASH,
    JSON.stringify(st?.agent_code_outdated));
  pr = await poll("wk-l5", token, { ...HB, bundle_sha256: CUR_HASH });
  st = await status("wk-l5");
  cell("W08b expired cache + current agent: outdated False (healed)",
    st?.agent_code_outdated === false && st?.agent_bundle_sha256 === CUR_HASH,
    JSON.stringify(st?.agent_code_outdated));

  // W09: origin down + no cache -> unknown, never a lie.
  const env2 = makeEnv();
  originReachable = false;
  const cookie2 = await login(env2);
  const token2 = await (async () => {
    const r = await req(env2, "POST", "/api/nodes", {
      body: { name: "wk-l5b", panel_url: "https://panel-a.example.com" },
      headers: { Cookie: cookie2 },
    });
    return r.json?.token;
  })();
  pr = await req(env2, "POST", "/api/agent/poll", {
    body: { node_name: "wk-l5b", panel_url: "https://panel-a.example.com",
            status: { ...HB, bundle_sha256: OLD_HASH } },
    headers: { Authorization: "Bearer " + token2 },
  });
  const st2 = await (async () => {
    const r = await req(env2, "GET", "/api/status?node=wk-l5b", { headers: { Cookie: cookie2 } });
    return r.json;
  })();
  cell("W09 origin down, no cache: outdated null, installed kept",
    pr.status === 200 && st2?.agent_code_outdated === null
    && st2?.agent_bundle_sha256 === OLD_HASH,
    JSON.stringify({ o: st2?.agent_code_outdated, i: st2?.agent_bundle_sha256 }));
  originReachable = true;

  const fails = RESULTS.filter(([, ok]) => !ok).length;
  console.log("----");
  console.log(`checks=${RESULTS.length} failures=${fails}`);
  process.exit(fails ? 1 : 0);
}

main().catch((e) => { console.error("probe crashed:", e); process.exit(2); });

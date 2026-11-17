// R46 Fix-AF own probe: bundle_sha256 edge behavior the AD probes never
// exercise (adopted from the R46-L6 audit probe tests/r46_l6_nonstring.mjs).
// (a) Worker heartbeat with a NON-STRING bundle_sha256: fixed by R46-L7-1
// (write null into the snapshot when the key is present but not a string,
// Flask _touch_node merge semantics) -- the verdict must go UNKNOWN,
// not freeze at its last value.
// (b) Worker origin hash is KV-cached 1h (originBundleSha256): fixed by
// R46-L5-1 (re-fetch whenever the origin is reachable; the cache is only
// a fallback when the fetch fails) -- after the origin bundle changes,
// a poll with the NEW hash must compare against the NEW origin hash.
// BH-03(c) FLIP (Fix-AF, R46): cells A1/A2/A3 PINNED the defective freeze
// behavior in the audit probe (they passed when the defect reproduced);
// here they assert the FIXED behavior. B1 already asserted the fixed
// behavior in the audit probe. A0/A4/B2 are controls, unchanged.
// Usage: node tests/r46_fix_af_worker.mjs (exit = FAIL count). Mock KV +
// stubbed fetch, same harness shape as tests/r45_fix_ad_worker.mjs.
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

const OLD_HASH = "0".repeat(64);
const NEW_HASH = "a".repeat(64);
let originHash = OLD_HASH;
globalThis.fetch = async (url) => {
  if (String(url).endsWith("/api/agent/bundle.sha256")) {
    return new Response(`${originHash}  ovpn-agent-bundle.tar.gz\n`, { status: 200 });
  }
  return new Response("not found", { status: 404 });
};
const env = {
  PANEL_KV: new MockKV(),
  ADMIN_PASSWORD: "admin-pass-123",
  AGENT_BUNDLE_ORIGIN: "https://origin.example:8443",
};
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

const lr = await req("POST", "/api/login", {
  body: { password: "admin-pass-123" },
  headers: { "CF-Connecting-IP": "10.9.0.1" },
});
const m = (lr.headers.get("Set-Cookie") || "").match(/panel_session=([^;]+)/);
const cookie = m ? `panel_session=${m[1]}` : "";
const rr = await req("POST", "/api/nodes", {
  body: { name: "wk-ns", panel_url: "https://panel-a.example.com" },
  headers: { Cookie: cookie },
});
const token = rr.json?.token;
const HB = { version: "1.0", hostname: "h1", openvpn_running: true, sk5_enabled: false };
async function poll(status) {
  return req("POST", "/api/agent/poll", {
    body: { node_name: "wk-ns", panel_url: "https://panel-a.example.com", status },
    headers: { Authorization: "Bearer " + token },
  });
}
async function status() {
  return (await req("GET", "/api/status?node=wk-ns", { headers: { Cookie: cookie } })).json;
}

// (a) new string hash vs OLD origin -> outdated True.
await poll({ ...HB, bundle_sha256: NEW_HASH });
let st = await status();
cell("A0 new string hash -> outdated True",
  st?.agent_code_outdated === true && st?.agent_bundle_sha256 === NEW_HASH,
  JSON.stringify({ o: st?.agent_code_outdated, i: st?.agent_bundle_sha256 }));
// Non-string hash (number) -> BH-03(c) flip (Fix-AF): the snapshot hash
// must clear to unknown, not freeze at the previous value.
// R46-L7-1 fix: key present but not a string writes null into the snapshot.
await poll({ ...HB, bundle_sha256: 12345 });
st = await status();
cell("A1 non-string hash: installed null (unknown, not frozen)",
  st?.agent_bundle_sha256 === null,
  JSON.stringify({ i: st?.agent_bundle_sha256 }));
cell("A2 non-string hash: outdated null (unknown, not frozen True)",
  st?.agent_code_outdated === null,
  JSON.stringify({ o: st?.agent_code_outdated }));
// Null hash: same clearing (typeof null !== "string").
await poll({ ...HB, bundle_sha256: null });
st = await status();
cell("A3 null hash: installed null (unknown, not frozen)",
  st?.agent_bundle_sha256 === null,
  JSON.stringify({ i: st?.agent_bundle_sha256 }));
// String old hash (== origin) moves the verdict to False (control: string
// polls still update the snapshot, only non-strings freeze it).
await poll({ ...HB, bundle_sha256: OLD_HASH });
st = await status();
cell("A4 string old hash moves the verdict to False (control)",
  st?.agent_bundle_sha256 === OLD_HASH && st?.agent_code_outdated === false,
  JSON.stringify({ o: st?.agent_code_outdated, i: st?.agent_bundle_sha256 }));

// (b) origin bundle changes (panel upgrade) but KV still caches OLD_HASH
// (cached 1h ago in this same env by the earlier originBundleSha256 call).
originHash = NEW_HASH;
await poll({ ...HB, bundle_sha256: NEW_HASH });
st = await status();
// Correct verdict would be False (installed == new origin). The cached
// origin hash is OLD_HASH, so installed NEW_HASH != cached OLD_HASH.
cell("B1 new agent vs upgraded origin: outdated False expected",
  st?.agent_code_outdated === false,
  JSON.stringify({ o: st?.agent_code_outdated }));
cell("B2 new agent vs upgraded origin: installed kept",
  st?.agent_bundle_sha256 === NEW_HASH,
  JSON.stringify({ i: st?.agent_bundle_sha256 }));

const fails = RESULTS.filter(([, ok]) => !ok).length;
console.log("----");
console.log(`checks=${RESULTS.length} failures=${fails}`);
process.exit(fails ? 1 : 0);

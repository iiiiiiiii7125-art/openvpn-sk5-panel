// R47-BD probe 5: SK5 host-shape validation on the Worker face
// (R47-L6-3 + R47-L3-5) -- fixed behavior. POST /api/sk5 must 400 a
// malformed host at save time instead of queueing it (202) for the
// agent to reject later. Same harness as the R47-L3 Worker probe
// (MockKV, admin session, node n1).
// Usage: node tests/r47_bd_worker_host.mjs (exit = FAIL count)
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
  cell("W00 admin session obtained", !!m, `${lr.status}`);

  const rr = await req("POST", "/api/nodes", {
    body: { name: "n1", panel_url: "https://panel-a.example.com" }, headers: auth,
  });
  cell("W00b register n1", rr.status === 201, `${rr.status}`);

  const save = (host) => req("POST", "/api/sk5", {
    body: { host, port: 1001, username: "u", password: "p", enabled: false },
    headers: auth,
  });

  let r = await save("exa mple.com");
  cell("W1 sk5 save 'exa mple.com' -> 400", r.status === 400, `${r.status} ${r.text.slice(0, 80)}`);
  r = await save("not a host!!!");
  cell("W2 sk5 save 'not a host!!!' -> 400", r.status === 400, `${r.status}`);
  r = await save("proxy.iproyal.net:1080");
  cell("W3 sk5 save 'proxy.iproyal.net:1080' (host:port typo) -> 400", r.status === 400, `${r.status}`);
  r = await save("proxy.example.com");
  cell("W4 sk5 save 'proxy.example.com' -> 202", r.status === 202, `${r.status}`);
  r = await save("::1");
  cell("W5 sk5 save '::1' (IPv6 literal) -> 202", r.status === 202, `${r.status}`);
  r = await save("127.0.0.1");
  cell("W6 sk5 save '127.0.0.1' -> 202", r.status === 202, `${r.status}`);

  console.log(`TOTAL ${RESULTS.length} cells, ${FAILURES.length} FAIL`);
  process.exit(FAILURES.length);
}
main();

// R22 Worker probe (r22_time_bounds.mjs) — time & order boundary audit,
// Worker face. Mirrors the Flask cells of tests/r22_time_bounds.py.
// Usage: node tests/r22_time_bounds.mjs
// Import uses a relative path, pointing at the live tree's index.js.
// Cells W-T1..W-T8; exit code = FAIL count.
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

async function freshNode(adminCookie, name) {
  const r = await req("POST", "/api/nodes", {
    body: { name, panel_url: "" }, headers: { Cookie: adminCookie },
  });
  return r.json?.token;
}

async function enqueue(adminCookie, node, action, params = {}) {
  return req("POST", "/api/cmd", {
    body: { node, action, params },
    headers: { Cookie: adminCookie },
  });
}

async function poll(token, node) {
  return req("POST", "/api/agent/poll", {
    body: { node_name: node },
    headers: { Authorization: "Bearer " + token },
  });
}

async function getCmdRecord(id) {
  return kv.get(`cmd:${id}`, "json");
}


async function ageSent(node, id, ageMs) {
  // Age BOTH the sent-list copy and the cmd record, keeping them
  // consistent (as dispatch writes them). The poll timeout loop reads
  // the COPY's sent_at (_handleSentTimeout override); the sweep reads
  // the RECORD's sent_at for orphans. Ageing only the record ages
  // nothing on the poll path -- that was the probe's first-version bug.
  const sent = (await kv.get(`sent:${node}`, "json")) || [];
  for (const e of sent) if (e && e.id === id) e.sent_at = Date.now() - ageMs;
  await kv.put(`sent:${node}`, JSON.stringify(sent));
  const rec = await getCmdRecord(id);
  if (rec) {
    rec.sent_at = Date.now() - ageMs;
    await kv.put(`cmd:${id}`, JSON.stringify(rec));
  }
  return rec;
}

async function main() {
  const adminCookie = await loginAsAdmin("10.9.0.1");

  // ---------- W-T1: lockout count boundary (5 fails -> lock) ----------
  {
    const ip = "10.9.0.11";
    for (let i = 0; i < 4; i++) {
      const r = await req("POST", "/api/login", {
        body: { password: "wrong" },
        headers: { "CF-Connecting-IP": ip },
      });
      if (r.status !== 401) cell("W-T1a 4 wrong logins -> 401", false, `${r.status}`);
    }
    cell("W-T1a 4 wrong logins -> 401, no lock yet", true);
    const r5 = await req("POST", "/api/login", {
      body: { password: "wrong" },
      headers: { "CF-Connecting-IP": ip },
    });
    cell("W-T1b 5th wrong login -> 401 and lock set", r5.status === 401, `${r5.status}`);
    const r6 = await req("POST", "/api/login", {
      body: { password: "wrong" },
      headers: { "CF-Connecting-IP": ip },
    });
    cell("W-T1c 6th login while locked -> 429 + Retry-After",
      r6.status === 429 && r6.headers.get("Retry-After") !== null
      && Number(r6.headers.get("Retry-After")) >= 1
      && (r6.json?.retry_after_s ?? 0) >= 1,
      `${r6.status} Retry-After=${r6.headers.get("Retry-After")}`);
  }

  // ---------- W-T2: window edge (failure exactly 300s old is pruned) ----------
  {
    const ip = "10.9.0.12";
    const now = Date.now();
    await kv.put(`loginfail:${ip}`, JSON.stringify({
      failures: [now - 300000, now - 300000, now - 300000, now - 300000, now - 300000],
      locked_until: 0,
    }));
    const r = await req("POST", "/api/login", {
      body: { password: "wrong" },
      headers: { "CF-Connecting-IP": ip },
    });
    const rec = await kv.get(`loginfail:${ip}`, "json");
    cell("W-T2a 5 failures exactly 300s old -> pruned, no lock",
      r.status === 401 && !(rec?.locked_until > Date.now()), `${r.status}`);
    await kv.put(`loginfail:${ip}`, JSON.stringify({
      failures: [now - 299000, now - 299000, now - 299000, now - 299000, now - 299000],
      locked_until: 0,
    }));
    const r2 = await req("POST", "/api/login", {
      body: { password: "wrong" },
      headers: { "CF-Connecting-IP": ip },
    });
    const rec2 = await kv.get(`loginfail:${ip}`, "json");
    cell("W-T2b 5 failures 299s old -> counted, lock set",
      r2.status === 401 && rec2?.locked_until > Date.now(), `${r2.status}`);
  }

  // ---------- W-T3: sent timeout + retries boundary (Worker) ----------
  {
    const token = await freshNode(adminCookie, "wt3");
    const e = await enqueue(adminCookie, "wt3", "get_status");
    const id = e.json?.cmd_id;
    // dispatch once so the record is sent
    await poll(token, "wt3");
    let rec = await getCmdRecord(id);
    // 119990ms ago -> NOT timed out (10ms margin; exact <= operator code-verified)
    rec.sent_at = Date.now() - 119990;
    await kv.put(`cmd:${id}`, JSON.stringify(rec));
    const p1 = await poll(token, "wt3");
    rec = await getCmdRecord(id);
    cell("W-T3a sent 119990ms ago -> still sent",
      rec.status === "sent" && (p1.json?.commands || []).length === 0,
      `status=${rec.status}`);
    // 120010ms ago -> requeued, retries 1
    await ageSent("wt3", id, 120010);
    rec = await getCmdRecord(id);
    rec.status = "sent";
    await kv.put(`cmd:${id}`, JSON.stringify(rec));
    // queue must not already hold the id; poll requeues it, then dispatches it
    const p2 = await poll(token, "wt3");
    rec = await getCmdRecord(id);
    cell("W-T3b sent 120010ms ago -> requeued then re-dispatched, retries 1",
      rec.status === "sent" && rec.retries === 1
      && (p2.json?.commands || []).some((c) => c.id === id),
      `status=${rec.status} retries=${rec.retries}`);
    // retries=3 + stale -> failed
    rec.retries = 3;
    rec.status = "sent";
    await kv.put(`cmd:${id}`, JSON.stringify(rec));
    await ageSent("wt3", id, 120010);
    await poll(token, "wt3");
    rec = await getCmdRecord(id);
    cell("W-T3c retries=3 + stale -> failed, '已重投 3 次'",
      rec.status === "failed" && (rec.error || "").includes("已重投 3 次"),
      `status=${rec.status}`);
    // non-safe action: stale -> failed immediately, no requeue
    const e2 = await enqueue(adminCookie, "wt3", "create_user", { username: "u1" });
    const id2 = e2.json?.cmd_id;
    await poll(token, "wt3");
    let rec2 = await getCmdRecord(id2);
    rec2.status = "sent";
    rec2.retries = 0;
    await kv.put(`cmd:${id2}`, JSON.stringify(rec2));
    await ageSent("wt3", id2, 120010);
    await poll(token, "wt3");
    rec2 = await getCmdRecord(id2);
    cell("W-T3d non-safe create_user + stale -> failed immediately (Worker-only rule)",
      rec2.status === "failed", `status=${rec2.status}`);
  }

  // ---------- W-T8: FIFO dispatch order + requeue to tail ----------
  {
    const token = await freshNode(adminCookie, "wt8");
    const ids = [];
    for (let i = 0; i < 3; i++) {
      const e = await enqueue(adminCookie, "wt8", "get_status");
      ids.push(e.json?.cmd_id);
    }
    const p = await poll(token, "wt8");
    const got = (p.json?.commands || []).map((c) => c.id);
    cell("W-T8a 3 enqueued commands dispatch in FIFO order",
      JSON.stringify(got) === JSON.stringify(ids), `got=${got}`);
    cell("W-T8b poll_interval_s is 5", p.json?.poll_interval_s === 5,
      `poll_interval_s=${p.json?.poll_interval_s}`);
    // requeue-to-tail: A sent+stale, B queued -> poll returns [B, A]
    const ea = await enqueue(adminCookie, "wt8", "get_status");
    const a = ea.json?.cmd_id;
    await poll(token, "wt8"); // A dispatched -> sent
    const eb = await enqueue(adminCookie, "wt8", "get_status");
    const b = eb.json?.cmd_id;
    let recA = await getCmdRecord(a);
    recA.status = "sent";
    await kv.put(`cmd:${a}`, JSON.stringify(recA));
    await ageSent("wt8", a, 120010);
    const p2 = await poll(token, "wt8");
    const got2 = (p2.json?.commands || []).map((c) => c.id);
    cell("W-T8c stale sent A requeues to tail behind B",
      JSON.stringify(got2) === JSON.stringify([b, a]), `got=${got2}`);
  }

  const fails = RESULTS.filter(([, ok]) => !ok).length;
  console.log(`\nTOTAL ${RESULTS.length} cells, FAIL ${fails}: ${RESULTS.filter(([, ok]) => !ok).map(([n]) => n).join(", ")}`);
  process.exit(fails);
}

main().catch((e) => { console.error(e); process.exit(99); });

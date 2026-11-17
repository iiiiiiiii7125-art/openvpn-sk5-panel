// R42-F5 DOM probe — panel frontend family census, behavioral cells.
//
// Runs the actual <script> from panel/templates/index.html in a fake DOM
// (node:vm) with the REAL api()/apiWait() and a stubbed fetch, so the
// cells exercise the shipped code paths, not a re-implementation:
//
//   F5-A  401 path discards the server's error body: wrong password must
//         surface "密码错误", not the generic "未登录".
//   F5-B  same for change-password: wrong old password must surface
//         "旧密码错误".
//   F5-C  L2-P2-2 family, SK5 leg: typed-but-unsaved SK5 edits must
//         survive a manual refresh (refreshAll -> loadSk5 unconditional
//         refill); currently reverted to the server value.
//   F5-D  empty port field: save must be rejected client-side; currently
//         the P01 confirm shows "NaN" and the request goes out with
//         port null (server then defaults it to 1194/443).
//   F5-G  (R42-Fix-J) registration warning: the server's d.warning must
//         reach nodeMsg; the stub POST /api/nodes returns one (the
//         server half is proven by the Flask probe G2).
//   F5-E  regression: port/proto dirty guards (Fix-E) still hold.
//   F5-F  regression/clearance: subnet/dns inputs are disabled, so the
//         loadStatus refill cannot clobber typing there.
//
// Cells assert the DESIRED behavior; a FAIL is a finding (L6 convention).
// Usage: node tests/r42_f5_frontend.mjs [path-to-tree]
// Exit 0 = all checks pass.
"use strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const TREE = process.argv[2] || path.resolve(__dirname, "..");
const HTML = fs.readFileSync(path.join(TREE, "panel/templates/index.html"), "utf8");
const m = HTML.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.error("FAIL: no <script> block found"); process.exit(1); }
const SCRIPT = m[1];

let failures = 0;
function check(name, cond, detail) {
  console.log((cond ? "PASS" : "FAIL") + " " + name + (cond ? "" : " :: " + detail));
  if (!cond) failures++;
}

/* ---------- fake DOM (same shape as the Fix-E harness) ---------- */
function makeElement(tag) {
  const el = {
    tagName: (tag || "div").toUpperCase(),
    children: [],
    style: {},
    dataset: {},
    className: "",
    innerHTML: "",
    textContent: "",
    value: "",
    checked: false,
    disabled: false,
    _listeners: {},
    onclick: null,
    onsubmit: null,
    onchange: null,
    addEventListener(type, fn) {
      (this._listeners[type] = this._listeners[type] || []).push(fn);
    },
    appendChild(c) { this.children.push(c); return c; },
    removeChild(c) {
      const i = this.children.indexOf(c);
      if (i !== -1) this.children.splice(i, 1);
      return c;
    },
    prepend(c) { this.children.unshift(c); return c; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    select() {},
    focus() {},
    click() { if (typeof this.onclick === "function") return this.onclick(); },
    scrollIntoView() {},
  };
  return el;
}

const STATUS_A = {
  openvpn: { running: true, port: 1194, proto: "udp", subnet: "10.8.0.0/24", dns: "1.1.1.1", online_users: 0, remote_ip: "1.2.3.4" },
  egress: { ip: "5.6.7.8", via_sk5: false },
  sk5: { enabled: false },
};
const SK5_A = { sk5: { host: "proxy.example.net", port: 1001, username: "u1", enabled: false, fail_open: false, udp_over_tcp: false } };

function makeHarness() {
  const byId = new Map();
  const created = [];
  const store = new Map();
  const confirms = [];
  const requests = []; // {path, method, body(parsed or null)}

  function resp(status, data) {
    return {
      status,
      ok: status >= 200 && status < 300,
      json: async () => JSON.parse(JSON.stringify(data)),
    };
  }

  async function stubFetch(url, opts) {
    const method = (opts && opts.method) || "GET";
    const path = String(url).split("?")[0];
    let body = null;
    try { body = opts && opts.body ? JSON.parse(opts.body) : null; } catch (e) { body = null; }
    requests.push({ path, method, body });
    if (path === "/api/me") return resp(200, { admin: false });
    if (path === "/api/login") return resp(401, { ok: false, error: "密码错误" });
    if (path === "/api/change-password") return resp(401, { ok: false, error: "旧密码错误" });
    if (path === "/api/status") return resp(200, JSON.parse(JSON.stringify(STATUS_A)));
    if (path === "/api/sk5" && method === "GET") return resp(200, JSON.parse(JSON.stringify(SK5_A)));
    if (path === "/api/sk5" && method === "POST") return resp(200, { ok: true, sk5: {} });
    if (path === "/api/openvpn/users") return resp(200, { users: [] });
    if (path === "/api/nodes" && method === "POST") return resp(201, { ok: true, node: { name: "ghost1", panel_url: "http://10.99.99.99:8443" }, token: "tok-once", warning: "面板地址 http://10.99.99.99:8443 不在面板证书 SAN 中，agent 以 HTTPS 连接时无法验证证书" });
    if (path === "/api/nodes") return resp(200, { nodes: [] });
    if (path === "/api/openvpn/server") return resp(200, { ok: true, server: {} });
    return resp(200, { ok: true });
  }

  const documentStub = {
    _activeElement: null,
    get activeElement() { return this._activeElement; },
    set activeElement(v) { this._activeElement = v; },
    getElementById(id) {
      if (!byId.has(id)) {
        const el = makeElement("div");
        el.id = id;
        byId.set(id, el);
      }
      return byId.get(id);
    },
    createElement(tag) {
      const el = makeElement(tag);
      created.push(el);
      return el;
    },
    createTextNode(text) { return { textContent: text }; },
    querySelectorAll() { return []; },
    execCommand() { return true; },
    body: makeElement("body"),
  };

  const ctx = vm.createContext({
    console,
    document: documentStub,
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, v),
      removeItem: (k) => store.delete(k),
    },
    location: { origin: "https://panel.example:8443" },
    navigator: { clipboard: { writeText: async () => {} } },
    fetch: stubFetch,
    setInterval: () => 0,
    setTimeout: (fn) => 0,
    confirm: (msg) => { confirms.push(msg); return true; },
    TextEncoder,
    Blob: function () {},
    URL: { createObjectURL: () => "blob:x", revokeObjectURL: () => {} },
  });
  vm.runInContext(SCRIPT, ctx, { filename: "index.html<script>" });

  function fire(el, type) {
    (el._listeners[type] || []).forEach((fn) => fn.call(el, { target: el }));
  }
  function el(id) { return documentStub.getElementById(id); }
  async function flush(n) {
    for (let i = 0; i < (n || 5); i++) await new Promise((r) => setImmediate(r));
  }
  return { ctx, el, created, confirms, requests, fire, flush };
}

(async () => {
  /* ---------- F5-A: wrong-password 401 must say 密码错误 ---------- */
  {
    const h = makeHarness();
    h.el("password").value = "wrongpass";
    await h.el("loginBtn").onclick();
    check("F5-A login 401 surfaces the server message",
      h.el("loginMsg").textContent.includes("密码错误"),
      "loginMsg=" + JSON.stringify(h.el("loginMsg").textContent));
  }

  /* ---------- F5-B: change-password 401 must say 旧密码错误 ---------- */
  {
    const h = makeHarness();
    h.el("oldPw").value = "OldPass123456";
    h.el("newPw").value = "NewPass123456";
    h.el("confirmPw").value = "NewPass123456";
    await h.el("changePwForm").onsubmit({ preventDefault() {} });
    check("F5-B change-password 401 surfaces the server message",
      h.el("changePwMsg").textContent.includes("旧密码错误"),
      "changePwMsg=" + JSON.stringify(h.el("changePwMsg").textContent));
  }

  /* ---------- F5-C: SK5 edits must survive a manual refresh ---------- */
  {
    const h = makeHarness();
    await h.ctx.refreshAll();
    await h.flush();
    check("F5-C0 refresh fills SK5 form from server",
      h.el("sk5Host").value === "proxy.example.net",
      "sk5Host=" + h.el("sk5Host").value);
    h.el("sk5Host").value = "proxy2.example.net";
    h.el("sk5Port").value = "2002";
    await h.el("refreshBtn").onclick();
    await h.flush(8);
    check("F5-C1 typed SK5 host survives manual refresh",
      h.el("sk5Host").value === "proxy2.example.net",
      "sk5Host=" + h.el("sk5Host").value);
    check("F5-C2 typed SK5 port survives manual refresh",
      String(h.el("sk5Port").value) === "2002",
      "sk5Port=" + h.el("sk5Port").value);
  }

  /* ---------- F5-D: empty port field must not confirm "NaN" ---------- */
  {
    const h = makeHarness();
    await h.ctx.loadStatus();
    h.el("port").value = "";
    await h.el("saveServerBtn").onclick();
    await h.flush();
    check("F5-D1 confirm never shows NaN for an empty port",
      !h.confirms.some((c) => c.includes("NaN")),
      "confirms=" + JSON.stringify(h.confirms));
    const save = h.requests.find((r) => r.path === "/api/openvpn/server" && r.method === "POST");
    check("F5-D2 no request goes out with an empty/invalid port",
      !save || (Number.isInteger(save.body && save.body.port) && save.body.port >= 1 && save.body.port <= 65535),
      "save=" + JSON.stringify(save && save.body));
  }

  /* ---------- F5-G (R42-Fix-J): registration warning is surfaced ---------- */
  {
    const h = makeHarness();
    h.el("newNodeName").value = "ghost1";
    h.el("newNodeUrl").value = "";
    await h.el("registerNodeBtn").onclick();
    await h.flush();
    check("F5-G node registration warning is shown in nodeMsg",
      h.el("nodeMsg").textContent.includes("无法验证"),
      "nodeMsg=" + JSON.stringify(h.el("nodeMsg").textContent));
  }

  /* ---------- F5-E: regression, port/proto dirty guards hold ---------- */
  {
    const h = makeHarness();
    await h.ctx.loadStatus();
    h.el("port").value = "1195";
    h.fire(h.el("port"), "input");
    h.el("proto").value = "tcp";
    h.fire(h.el("proto"), "change");
    await h.ctx.loadStatus();
    check("F5-E typed port/proto survive a tick (Fix-E guard holds)",
      String(h.el("port").value) === "1195" && h.el("proto").value === "tcp",
      "port=" + h.el("port").value + " proto=" + h.el("proto").value);
  }

  /* ---------- F5-F: subnet/dns are disabled inputs (no clobber risk) ---------- */
  {
    const subnetTag = HTML.match(/<input[^>]*id="subnet"[^>]*>/)[0];
    const dnsTag = HTML.match(/<input[^>]*id="dns"[^>]*>/)[0];
    check("F5-F1 subnet input is disabled (user cannot type)",
      /\bdisabled\b/.test(subnetTag), subnetTag);
    check("F5-F2 dns input is disabled (user cannot type)",
      /\bdisabled\b/.test(dnsTag), dnsTag);
    const saveBlock = SCRIPT.slice(SCRIPT.indexOf('saveServerBtn").onclick'));
    const bodyLit = saveBlock.match(/var body = \{[\s\S]*?\};/)[0];
    check("F5-F3 saveServer body carries only port/proto/server_ip",
      !/subnet|dns/.test(bodyLit),
      "save body=" + bodyLit);
  }

  console.log(failures === 0 ? "ALL PASS" : failures + " FAILURES");
  process.exit(failures === 0 ? 0 : 1);
})().catch((e) => { console.error("FAIL harness error:", e); process.exit(1); });

// R41 Fix-E verification — DOM-level probe for the real shipped index.html script.
//
// Runs the actual <script> from panel/templates/index.html in a fake DOM
// (node:vm) and drives the real loadStatus / loadNodes / save-handler code:
//   E1  P2-1: "复制安装命令" makes no /install request; clipboard text is the
//             local buildInstallCommand() output (byte-identical to the
//             Worker template per L6-08).
//   E2  P2-2: typed port/proto survive a loadStatus tick while blurred.
//   E3  P2-2: typed port/proto survive a loadStatus tick while focused.
//   E4  P2-2: with no edits, loadStatus still refreshes port/proto.
//   E5  P2-2: save after typing triggers the P01 confirm with the NEW
//             values, sends them, and clears dirty so refresh resumes.
//   E6  P2-2: save with unchanged values triggers no confirm.
//   E7  comment: header comment no longer lists /install as a Flask route,
//             notes it as Worker-only, and lists change-password.
//
// Usage: node tests/r41_fix_e_dom.mjs [path-to-tree]
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

/* ---------- fake DOM ---------- */
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
    _listeners: {},
    onclick: null,
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
  };
  return el;
}

function makeHarness(statusPayload) {
  const byId = new Map();
  const created = [];
  const store = new Map();
  const apiCalls = [];
  const clipboard = [];
  const confirms = [];
  const apiWaitCalls = [];
  let currentStatus = statusPayload;

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
    navigator: {
      clipboard: {
        writeText: async (t) => { clipboard.push(t); },
      },
    },
    fetch: async () => ({ json: async () => ({ admin: false }) }),
    setInterval: () => 0,
    setTimeout: (fn) => 0,
    confirm: (msg) => { confirms.push(msg); return true; },
  });
  ctx.__document = documentStub;
  vm.runInContext(SCRIPT, ctx, { filename: "index.html<script>" });

  // Stub the network layer after eval: the script's own api()/apiWait()
  // resolve through the context global, so replacing them intercepts
  // every call loadStatus/loadNodes/save make.
  ctx.api = async (p, method, body) => {
    apiCalls.push({ path: p, method: method || "GET", body });
    // Emulate Flask: POST /api/nodes/<name>/install does not exist
    // (404 -> api() throws "响应不是 JSON", the frontend falls back).
    if (/^\/api\/nodes\/[^/]+\/install$/.test(p)) throw new Error("HTTP 404");
    if (p === "/api/status") return JSON.parse(JSON.stringify(currentStatus));
    if (p === "/api/nodes") {
      return { nodes: [{ name: "node1", panel_url: "https://panel.example:8443", online: true, egress_ip: "5.6.7.8", sk5_enabled: false }] };
    }
    if (p === "/api/openvpn/public-ip") return { ip: "1.2.3.4" };
    return { ok: true };
  };
  ctx.apiWait = async (p, method, body) => {
    apiWaitCalls.push({ path: p, method, body });
    return { ok: true, server: {} };
  };

  function fire(el, type) {
    (el._listeners[type] || []).forEach((fn) => fn.call(el, { target: el }));
  }
  function el(id) { return documentStub.getElementById(id); }
  return {
    ctx, el, created, apiCalls, clipboard, confirms, apiWaitCalls,
    fire,
    setStatus(p) { currentStatus = p; },
    async tick() { await ctx.loadStatus(); },
  };
}

const STATUS_A = {
  openvpn: { running: true, port: 1194, proto: "udp", subnet: "10.8.0.0/24", dns: "1.1.1.1", online_users: 0, remote_ip: "1.2.3.4" },
  egress: { ip: "5.6.7.8", via_sk5: false },
  sk5: { enabled: false },
};

(async () => {
  /* ---------- E1: P2-1 copy button ---------- */
  {
    const h = makeHarness(STATUS_A);
    await h.ctx.loadNodes();
    const btn = h.created.find(
      (e) => e.tagName === "BUTTON" && e.textContent === "复制安装命令" && typeof e.onclick === "function"
    );
    check("E1a copy button exists", !!btn, "no button with that label/onclick");
    if (btn) {
      btn.onclick();
      await new Promise((r) => setImmediate(r));
      const installCalls = h.apiCalls.filter((c) => c.path.includes("/install"));
      check("E1b no /install request on click", installCalls.length === 0,
        "api calls: " + JSON.stringify(h.apiCalls));
      check("E1c one clipboard write", h.clipboard.length === 1, "writes=" + h.clipboard.length);
      const expected = h.ctx.buildInstallCommand("https://panel.example:8443", "<NODE_TOKEN>", "node1");
      check("E1d clipboard == buildInstallCommand()", h.clipboard[0] === expected,
        "got: " + h.clipboard[0]);
      const t = h.clipboard[0] || "";
      check("E1e template shape (curl + sha256 + panel-url + token + node-name)",
        t.includes("curl -ksSL 'https://panel.example:8443/install-agent.sh'") &&
        t.includes("sha256sum -c install-agent.sh.sha256") &&
        t.includes("--panel-url 'https://panel.example:8443'") &&
        t.includes("--token '<NODE_TOKEN>'") &&
        t.includes("--node-name 'node1'"),
        "got: " + t);
    }
  }

  /* ---------- E2/E3/E5: P2-2 dirty guards ---------- */
  {
    const h = makeHarness(STATUS_A);
    await h.tick();
    check("E2a initial refresh fills port/proto", h.el("port").value === 1194 && h.el("proto").value === "udp",
      "port=" + h.el("port").value + " proto=" + h.el("proto").value);
    // User types a new port/proto, then blurs (E2: blurred case).
    h.el("port").value = "1195";
    h.fire(h.el("port"), "input");
    h.el("proto").value = "tcp";
    h.fire(h.el("proto"), "change");
    h.ctx.document.activeElement = h.el("serverIp"); // blurred away from port/proto
    await h.tick();
    check("E2b typed values survive tick while blurred",
      String(h.el("port").value) === "1195" && h.el("proto").value === "tcp",
      "port=" + h.el("port").value + " proto=" + h.el("proto").value);
    check("E2c server truth still tracked separately",
      h.ctx.lastServerPort === 1194 && h.ctx.lastServerProto === "udp",
      "lastServerPort=" + h.ctx.lastServerPort);
    // E3: same, while focused in the port field.
    h.el("port").value = "1196";
    h.fire(h.el("port"), "input");
    h.ctx.document.activeElement = h.el("port");
    await h.tick();
    check("E3 typed value survives tick while focused", String(h.el("port").value) === "1196",
      "port=" + h.el("port").value);
    // E5: save with the typed values -> P01 confirm fires with the NEW
    // values, body carries them, dirty clears, refresh resumes.
    h.el("port").value = "1195";
    h.fire(h.el("port"), "input");
    h.el("proto").value = "tcp";
    h.fire(h.el("proto"), "change");
    await h.tick(); // one more tick: values must still be 1195/tcp
    check("E5a values still typed before save",
      String(h.el("port").value) === "1195" && h.el("proto").value === "tcp",
      "port=" + h.el("port").value + " proto=" + h.el("proto").value);
    await h.el("saveServerBtn").onclick();
    check("E5b P01 confirm fired once with new values",
      h.confirms.length === 1 && h.confirms[0].includes("1195") && h.confirms[0].includes("TCP"),
      "confirms=" + JSON.stringify(h.confirms));
    const save = h.apiWaitCalls.find((c) => c.path === "/api/openvpn/server");
    check("E5c save body carries typed port/proto + allow_port_change",
      !!save && save.body.port === 1195 && save.body.proto === "tcp" && save.body.allow_port_change === true,
      "save=" + JSON.stringify(save));
    // After save, server now reports 1195/tcp; refresh must follow it.
    h.setStatus({
      openvpn: { running: true, port: 1195, proto: "tcp", subnet: "10.8.0.0/24", dns: "1.1.1.1", online_users: 0, remote_ip: "1.2.3.4" },
      egress: { ip: "5.6.7.8", via_sk5: false },
      sk5: { enabled: false },
    });
    await h.tick();
    check("E5d post-save tick follows server values", String(h.el("port").value) === "1195" && h.el("proto").value === "tcp",
      "port=" + h.el("port").value + " proto=" + h.el("proto").value);
    // And an external change afterwards is picked up (dirty cleared).
    h.setStatus({
      openvpn: { running: true, port: 1194, proto: "udp", subnet: "10.8.0.0/24", dns: "1.1.1.1", online_users: 0, remote_ip: "1.2.3.4" },
      egress: { ip: "5.6.7.8", via_sk5: false },
      sk5: { enabled: false },
    });
    await h.tick();
    check("E5e dirty cleared: external change is picked up again",
      String(h.el("port").value) === "1194" && h.el("proto").value === "udp",
      "port=" + h.el("port").value + " proto=" + h.el("proto").value);
  }

  /* ---------- E4: no-dirty refresh still works ---------- */
  {
    const h = makeHarness(STATUS_A);
    await h.tick();
    check("E4a refresh fills server values when untouched",
      h.el("port").value === 1194 && h.el("proto").value === "udp",
      "port=" + h.el("port").value);
    h.setStatus({
      openvpn: { running: true, port: 1195, proto: "tcp", subnet: "10.8.0.0/24", dns: "1.1.1.1", online_users: 0, remote_ip: "1.2.3.4" },
      egress: { ip: "5.6.7.8", via_sk5: false },
      sk5: { enabled: false },
    });
    await h.tick();
    check("E4b server-side change is picked up when untouched",
      String(h.el("port").value) === "1195" && h.el("proto").value === "tcp",
      "port=" + h.el("port").value + " proto=" + h.el("proto").value);
  }

  /* ---------- E6: unchanged save triggers no confirm ---------- */
  {
    const h = makeHarness(STATUS_A);
    await h.tick();
    await h.el("saveServerBtn").onclick();
    check("E6a no confirm for unchanged values", h.confirms.length === 0,
      "confirms=" + JSON.stringify(h.confirms));
    const save = h.apiWaitCalls.find((c) => c.path === "/api/openvpn/server");
    check("E6b unchanged save sends no allow_port_change",
      !!save && !("allow_port_change" in save.body),
      "save=" + JSON.stringify(save));
  }

  /* ---------- E7: header comment ---------- */
  {
    const comment = HTML.match(/\/\* 接口与 panel\/app\.py[\s\S]*?\*\//)[0];
    const listPart = comment.split("注意：")[0];
    check("E7a comment no longer lists /install as a Flask route",
      !listPart.includes("/install"), "list still mentions /install");
    check("E7b comment notes /install is Worker-only",
      comment.includes("仅 Cloudflare Worker 实现") && comment.includes("buildInstallCommand()"),
      "note missing");
    check("E7c comment lists change-password (called at :1044, was missing)",
      listPart.includes("POST /api/change-password"), "change-password absent");
    check("E7d no quoted \"/install\" path literal left in the script",
      !/\"\/install\"/.test(SCRIPT),
      "a quoted /install literal remains");
  }

  console.log(failures === 0 ? "ALL PASS" : failures + " FAILURES");
  process.exit(failures === 0 ? 0 : 1);
})().catch((e) => { console.error("FAIL harness error:", e); process.exit(1); });

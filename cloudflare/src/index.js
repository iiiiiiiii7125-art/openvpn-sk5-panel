// OpenVPN + SK5 面板 — Cloudflare Worker（控制面）
// 无依赖，ES Module。前端复用 panel/templates/index.html（Workers Static Assets）。
//
// 控制面模型（与 FLMX 同款思路：面板管注册/下发/回执，agent 在中转机上拉命令）：
//   面板 -> KV 队列 -> agent 每 5 秒 POST /api/agent/poll 拉命令
//   agent -> POST /api/agent/report 回结果 -> KV -> 面板 GET /api/cmd/:id 查询
//
// KV 键（全部在 PANEL_KV 命名空间）：
//   node:<name>            节点注册记录 {name, token_hash, panel_url, created_at, last_seen}
//                          token 明文只在注册/轮换时返回一次，KV 里只存 SHA-256 哈希。
//   queue:<name>           该节点待执行命令队列（JSON 数组，先进先出）
//   sent:<name>            已下发未回执的命令 [{id, action, sent_at}]（P1-6：120 秒超时处理）
//   cmd:<id>               单条命令记录 {id, node, action, params, status, result, error, ...}
//                          status: queued | sent | done | failed；7 天后过期（expirationTtl）。
//   status:<name>          节点最近一次状态快照（agent 上报 get_status 结果后写入）
//   servercfg:<name>       节点最近一次建服务成功的配置 {proto, port, subnet, dns}
//                          （快照补 proto/port/subnet/dns 用，见 P1-5）
//   sk5cfg:<name>          节点最近一次保存的 SK5 全量配置（含密码，见安全说明）
//                          （fail-open / UoT 开关下发前先读它补齐 host+port，见 P0-2；
//                           密码框留空时用它保留旧密码，见 P0-4 Worker 侧）
//   sk5test:<name>         节点最近一次 test_sk5 的原始结果 {tcp_ok, udp_ok, host, port, ...}
//                          （1-25：UDP 服务 + 同地址 UDP 测试失败时保存 SK5 即硬拒）
//   ovpn:<name>:<user>     最近一次 create_user 上报的 .ovpn 文本（含私钥，见 README 安全说明）
//   session:<id>           管理员会话 {created_at, expires_at}，24 小时有效
//   loginfail:<ip>         登录失败计数 {failures:[ms], locked_until: ms}（P1-3，与 Flask 同口径）
//
// agent 动作白名单（与 agent/agent.py 的 ACTIONS 及 Flask 面板 AGENT_ACTIONS
// 逐字一致，共 13 个，非法动作一律 400；agent 不认 "start"/"stop"，
// 只能用 "start_openvpn"/"stop_openvpn"，写错 agent 会直接拒收）。
//   install_prereqs, init_pki, create_server, start_openvpn, stop_openvpn,
//   restart_openvpn, create_user, revoke_user, set_sk5, test_sk5,
//   enable_sk5, disable_sk5, get_status
//
// 兼容层（本文件后半部分）：panel/templates/index.html 是单节点 UI，直接调
// /api/status、/api/openvpn/*、/api/sk5/*。在 Cloudflare 模式下这些路由由 Worker
// 翻译成命令队列 + KV 状态缓存。语义（P0-1 修复后）：
//   POST 类下发命令，返回 202 {ok:true, cmd_id, queued:true}——202 只表示
//   “已排队”，不是成功；前端须按 cmd_id 轮询 GET /api/cmd/:id，等到
//   done/failed 才报成功/失败，绝不凭 202 报成功。
//   GET 类返回节点最近上报的快照（带 stale / age_s），不保证实时。
//   单节点时不用选节点；多节点须用 ?node= 或 X-Node 指定。
//
// set_sk5 语义（P0-2/P1-15 修正）：agent 的 action_set_sk5 已是部分合并
//   （host/port 均可缺，缺失即保留存量）；sk5_manager.set_sk5 同款。
//   Worker 的 fail-open / udp-over-tcp 路由下发前仍先读 sk5cfg:<node>
//   补齐全量字段再发 set_sk5（纵深防御）；无已存配置时明确 400，
//   绝不发缺字段的命令。
//
// 命令 sent 态（P1-6）：poll 取走后命令记 sent 并留 sent:<node> 副本。
//   下次 poll 时超过 120 秒未回执的：幂等/只读动作（get_status、test_sk5、
//   enable_sk5、disable_sk5、start/stop/restart_openvpn）自动回队重发；
//   非幂等动作（create_user、revoke_user、init_pki、create_server、set_sk5、
//   install_prereqs）标 failed，由管理员确认 agent 状态后手动重发，
//   不自动重发避免重复执行。
//
// 队列写一致性（R18-P2-1／P2-2）：poll 的清空是条件式（只清本轮实际取走
//   的 id，窗口内新入队的 id 保留）；poll／report／revoke／cmd_get 的读
//   路径先跑 `_sweepWorkerCmds`——畸形记录标 failed＋隔离、孤儿 queued
//   记录重新入队、孤儿 sent 记录按超时规则处理。enqueueCommand 本身仍是
//   读→push→写回：它与 poll 的清空写交错时最多让已取走的 id 在队列数组
//   里短暂复活一轮（记录已是 sent／done／failed，下发守卫会跳过、下轮
//   条件式清空会摘掉），不丢命令；丢命令的方向只在 poll 的清空写，已修。

const ACTIONS = new Set([
  "install_prereqs",
  "init_pki",
  "create_server",
  "start_openvpn",
  "stop_openvpn",
  "restart_openvpn",
  "create_user",
  "revoke_user",
  "set_sk5",
  "test_sk5",
  "enable_sk5",
  "disable_sk5",
  "get_status",
]);

const SESSION_TTL_S = 24 * 3600;
const CMD_TTL_S = 7 * 24 * 3600;
const POLL_INTERVAL_S = 5;
const NAME_RE = /^[A-Za-z0-9_-]{1,32}$/;

// 登录限流（P1-3：与 Flask panel/app.py 逐字同口径——
// 同一 IP 5 分钟内 5 次失败即锁 15 分钟，锁期内 429 + Retry-After）。
const LOGIN_MAX_FAILURES = 5;
const LOGIN_WINDOW_SECONDS = 300;
const LOGIN_LOCK_SECONDS = 900;
// 命令已下发未回执的超时（P1-6，与 Flask 的 120 秒 timeout_hint 同值）。
const SENT_TIMEOUT_MS = 120000;
// sent 态重投上限（R3-P1-1：与 Flask SENT_MAX_RETRIES=3 同值；超过即标 failed，
// 死 agent 的命令不再无限循环。非幂等动作首超时即标 failed，不走重投）。
const SENT_MAX_RETRIES = 3;
// 超时未回执时可安全自动重入队的动作（幂等/只读）；其余动作标失败手动重发。
const SAFE_RETRY_ACTIONS = new Set([
  "get_status",
  "test_sk5",
  "enable_sk5",
  "disable_sk5",
  "start_openvpn",
  "stop_openvpn",
  "restart_openvpn",
]);
// 与 core 固定值一致（panel/app.py FIXED_SUBNET / FIXED_DNS）：
// 隧道子网与推送 DNS 不可改，Worker 快照直接用这两个常量补齐。
const FIXED_SUBNET = "10.8.0.0/24";
const FIXED_DNS = "1.1.1.1";

// ---------- 小工具 ----------

function json(data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function err(message, status = 400) {
  return json({ ok: false, error: message }, status);
}

async function readJson(request) {
  // R31-P2-1: envelope guard (Flask _json_body parity). A body only
  // counts as a JSON object when Content-Type is application/json
  // (a `; charset=...` suffix is allowed; compared case-insensitively,
  // like Flask's mimetype) AND the parsed value is a plain object.
  // Anything else — wrong Content-Type, malformed JSON, scalar, null,
  // array — returns null here, and every caller 400s with
  // "请求体须为 JSON 对象". Never silently proceed with {}.
  if (!isJsonContentType(request)) return null;
  try {
    const body = await request.json();
    return body && typeof body === "object" && !Array.isArray(body) ? body : null;
  } catch {
    return null;
  }
}

// R31-P2-1: Content-Type must be application/json for a JSON body.
// Flask _json_body requires request.is_json; Workers' request.json()
// parses regardless of Content-Type, so the check lives here.
function isJsonContentType(request) {
  const ct = request.headers.get("content-type");
  if (typeof ct !== "string") return false;
  return ct.split(";")[0].trim().toLowerCase() === "application/json";
}

// R30-P2-1: plain-integer token scanner for one JSON object text.
// JSON.parse erases the 1.0 vs 1 distinction (both become the number
// 1), while Flask's `type(x) is int` / `isinstance(x, int)` rejects
// 1.0. Integer client fields are therefore validated against the RAW
// request text: the token for the field must be a plain integer
// literal. Returns a Map of top-level key -> raw value token (last
// occurrence wins, matching JSON.parse), or null if the text is not
// a single well-formed JSON object. Nested values are skipped whole
// (strings honor escapes, brackets nest), so a key spelled inside a
// nested string or value can never be mistaken for a top-level member.
function topLevelTokens(raw) {
  let i = 0;
  const n = raw.length;
  const isWs = (c) => c === " " || c === "\t" || c === "\n" || c === "\r";
  const skipWs = () => { while (i < n && isWs(raw[i])) i++; };
  // Index just past the closing quote of the string starting at `s`,
  // or -1 if unterminated.
  const stringEnd = (s) => {
    let j = s + 1;
    while (j < n) {
      if (raw[j] === "\\") { j += 2; continue; }
      if (raw[j] === '"') return j + 1;
      j++;
    }
    return -1;
  };
  // Index just past the JSON value starting at `s`, or -1.
  const valueEnd = (s) => {
    const ch = raw[s];
    if (ch === '"') return stringEnd(s);
    if (ch === "{" || ch === "[") {
      const open = ch;
      const close = ch === "{" ? "}" : "]";
      let depth = 0;
      let j = s;
      while (j < n) {
        const c = raw[j];
        if (c === '"') { j = stringEnd(j); if (j < 0) return -1; continue; }
        if (c === open) depth++;
        else if (c === close) { depth--; if (depth === 0) return j + 1; }
        j++;
      }
      return -1;
    }
    let j = s;
    while (j < n && raw[j] !== "," && raw[j] !== "}") j++;
    return j;
  };
  skipWs();
  if (raw[i] !== "{") return null;
  i++;
  const out = new Map();
  skipWs();
  if (raw[i] === "}") return out;
  for (;;) {
    skipWs();
    if (raw[i] !== '"') return null;
    const keyEnd = stringEnd(i);
    if (keyEnd < 0) return null;
    let key;
    try { key = JSON.parse(raw.slice(i, keyEnd)); } catch { return null; }
    i = keyEnd;
    skipWs();
    if (raw[i] !== ":") return null;
    i++;
    skipWs();
    const valueStart = i;
    const end = valueEnd(i);
    if (end < 0) return null;
    out.set(key, raw.slice(valueStart, end).trim());
    i = end;
    skipWs();
    if (raw[i] === ",") { i++; continue; }
    if (raw[i] === "}") return out;
    return null;
  }
}

// The only JSON integer literals Python parses as int: an optional
// minus followed by 0 or a non-zero digit run. No fraction, no
// exponent, no leading zeros (those are invalid JSON anyway, so
// JSON.parse already rejects them). `1.0`, `1.00`, `1e0`, `1.5` all
// fail this test, exactly like Flask's `type(x) is int`.
const INT_TOKEN_RE = /^-?(0|[1-9][0-9]*)$/;

// R30-P2-1: read the raw request text together with the parsed body.
// Integer fields are checked against the raw token (see
// topLevelTokens). Malformed JSON keeps the old readJson behavior
// (body null, and the callers 400 as before).
// R31-P2-1: the same envelope guard as readJson applies — wrong
// Content-Type, malformed JSON, scalar, null, or array body yields
// { body: null, tokens: null }.
async function readJsonRaw(request) {
  if (!isJsonContentType(request)) return { body: null, tokens: null };
  let raw = null;
  try {
    raw = await request.text();
  } catch {
    return { body: null, tokens: null };
  }
  let body = null;
  try {
    const v = JSON.parse(raw);
    if (v && typeof v === "object" && !Array.isArray(v)) body = v;
  } catch {
    return { body: null, tokens: null };
  }
  return { body, tokens: body ? topLevelTokens(raw) : null };
}

function nowMs() {
  return Date.now();
}

function randomHex(nBytes) {
  const buf = new Uint8Array(nBytes);
  crypto.getRandomValues(buf);
  return [...buf].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function sha256Hex(text) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text),
  );
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function sha256HexBuf(buf) {
  const digest = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// 定时安全的字符串比较：先各自 SHA-256，再按字节比对，避免直接 == 泄露长度/前缀。
async function safeEqual(a, b) {
  const ha = await sha256Hex(a);
  const hb = await sha256Hex(b);
  if (ha.length !== hb.length) return false;
  let diff = 0;
  for (let i = 0; i < ha.length; i++) diff |= ha.charCodeAt(i) ^ hb.charCodeAt(i);
  return diff === 0;
}

function getCookie(request, name) {
  const cookie = request.headers.get("Cookie") || "";
  for (const part of cookie.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (k === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

function sessionCookieHeader(request, sessionId) {
  const secure = new URL(request.url).protocol === "https:";
  return (
    `panel_session=${encodeURIComponent(sessionId)}; HttpOnly; Path=/; ` +
    `Max-Age=${SESSION_TTL_S}; SameSite=Lax${secure ? "; Secure" : ""}`
  );
}

function clearSessionCookieHeader() {
  return "panel_session=; HttpOnly; Path=/; Max-Age=0; SameSite=Lax";
}

// 客户端 IP：Workers 上取 CF-Connecting-IP（无该头时记 unknown）。
function clientIp(request) {
  return request.headers.get("CF-Connecting-IP") || "unknown";
}

// ---------- KV 读写 ----------

async function kvGetJson(env, key) {
  return env.PANEL_KV.get(key, "json");
}

async function kvPutJson(env, key, value, opts = {}) {
  await env.PANEL_KV.put(key, JSON.stringify(value), opts);
}

// R19-P2-1：queue:/sent: 容器值归一化。手改 KV 可能把容器写成字符串／
// 对象等非数组值；`|| []` 只防 null/undefined，不防非数组真值——直接
// 当数组用（push/filter/map/spread）会抛 TypeError → 500，节点命令
// 通道卡死，且 sweep 自身先抛、无法自愈。非数组一律按 [] 处理（Flask
// BA 同款），并 console.warn 记容器形状（只记键与 typeof，不写内容；
// 容器里只有命令 id）。滞留的 queued 记录由 sweep 的孤儿回收重新入队。
function kvArray(value, key) {
  if (Array.isArray(value)) return value;
  if (value === null || value === undefined) return [];
  console.warn(`kv container ${key} is not an array (${typeof value}); treating as empty`);
  return [];
}

async function listNodes(env) {
  const listed = await env.PANEL_KV.list({ prefix: "node:" });
  const nodes = [];
  for (const entry of listed.keys || []) {
    const rec = await kvGetJson(env, entry.name);
    // R12-P2-3：手改 KV 可能留下无名脏记录（注册入口只写 NAME_RE
    // 校验过的名，见 handleRegisterNode）——跳过并记日志，绝不让
    // 一条脏记录在 sort 里抛 TypeError、灭全部兼容路由与 agent 鉴权。
    if (rec && (typeof rec.name !== "string" || !rec.name)) {
      console.warn(`listNodes: skip nameless node record ${entry.name}`);
      continue;
    }
    if (rec) nodes.push(rec);
  }
  nodes.sort((a, b) => a.name.localeCompare(b.name));
  return nodes;
}

// ---------- 会话 / 节点鉴权 ----------

async function requireAdmin(request, env) {
  const sessionId = getCookie(request, "panel_session");
  if (!sessionId) return null;
  const sess = await kvGetJson(env, `session:${sessionId}`);
  if (!sess || !sess.expires_at || sess.expires_at <= nowMs()) {
    if (sess) await env.PANEL_KV.delete(`session:${sessionId}`);
    return null;
  }
  return sess;
}

async function authenticateNode(request, env, bodyToken = null) {
  // R41-L5-P2-2: Flask _agent_auth 同款——接受 Authorization: Bearer
  // <token> 或 body.node_token；两者都在且不一致 -> 401（防 token
  // 混用冒领）。bodyToken 由调用方从已读出的 body 里取（body 流只能
  // 读一次，authenticateNode 自己不读）。
  const auth = request.headers.get("Authorization") || "";
  const m = auth.match(/^Bearer\s+(.+)$/);
  const headerToken = m ? m[1].trim() || null : null;
  const bodyTok =
    bodyToken != null && String(bodyToken) !== "" ? String(bodyToken) : null;
  if (headerToken && bodyTok && headerToken !== bodyTok) return null;
  const token = headerToken || bodyTok;
  if (!token) return null;
  const tokenHash = await sha256Hex(token);
  const nodes = await listNodes(env);
  for (const node of nodes) {
    if (node.token_hash && node.token_hash === tokenHash) return node;
  }
  return null;
}

// R41-L5-P2-1: FLMX 认领守卫（Flask _check_panel_claim 同款）：节点
// 注册时绑定的 panel_url 与 agent 配置里的 panel_url 必须逐字相等
// （仅去尾斜杠），否则拒绝认领——防别的面板拿一个有效 token 就把
// 节点接管走。agent 未上报 panel_url（旧版 agent）时放行，但 poll
// 响应里带 panel_url_unverified 提示升级 agent。
function checkPanelClaim(node, body) {
  const stored = (node.panel_url || "").replace(/\/+$/, "");
  const claimed =
    body && body.panel_url != null ? String(body.panel_url).replace(/\/+$/, "") : "";
  if (stored && claimed && claimed !== stored) {
    return {
      ok: false,
      error: `panel_url 不匹配：节点注册于 ${stored}，agent 配置为 ${claimed}，拒绝认领`,
    };
  }
  if (stored && !claimed) return { ok: true, status: "unverified" };
  return { ok: true, status: "ok" };
}

// 节点解析（兼容层用）：body.node > ?node= > X-Node 指定（R12-P2-5：
// 与 Flask _resolve_compat_node 同款优先级；ghost 一律 404，绝不
// 静默落到唯一节点上执行）；未指定时：恰好 1 个节点则用它，
// 0 个报未注册，多个报须指定。body 由调用方先读出后传入（body 流
// 只能读一次，resolveNode 自己不再读）。
async function resolveNode(request, env, body = null) {
  const url = new URL(request.url);
  // 与 Flask 同款：falsy（空串／0／false）即视为未指定，往后回落；
  // 其余值一律 String() 后 trim 再查（数字 123 即 "123"，查无即 404）。
  const bodyNode =
    body && typeof body === "object" && !Array.isArray(body) && body.node
      ? String(body.node).trim()
      : "";
  const name =
    bodyNode || url.searchParams.get("node") || request.headers.get("X-Node") || "";
  const nodes = await listNodes(env);
  if (name) {
    const node = nodes.find((n) => n.name === name);
    if (!node) return { error: err(`节点不存在：${name}`, 404) };
    return { node };
  }
  if (nodes.length === 0) return { error: err("未注册节点，先 POST /api/nodes 注册", 400) };
  if (nodes.length > 1) {
    return {
      error: json(
        {
          ok: false,
          error: "多节点须指定 node 参数",
          nodes: nodes.map((n) => n.name),
        },
        400,
      ),
    };
  }
  return { node: nodes[0] };
}

// 下发一条命令：写 cmd:<id> + 追加到 queue:<node>，返回命令记录。
async function enqueueCommand(env, nodeName, action, params) {
  const id = crypto.randomUUID();
  const cmd = {
    id,
    node: nodeName,
    action,
    params: params || {},
    status: "queued",
    result: null,
    error: null,
    retries: 0,
    created_at: nowMs(),
    sent_at: null,
    finished_at: null,
  };
  await kvPutJson(env, `cmd:${id}`, cmd, { expirationTtl: CMD_TTL_S });
  const queue = kvArray(await kvGetJson(env, `queue:${nodeName}`), `queue:${nodeName}`);
  queue.push(id);
  // R27-P2-2: queue: shares the cmd: TTL (7 days) so the list and its
  // records live and die together -- a queue list that outlives its
  // records is what leaves dangling ids. Every poll rewrites the
  // list and refreshes the TTL, so live nodes are unaffected.
  await kvPutJson(env, `queue:${nodeName}`, queue, { expirationTtl: CMD_TTL_S });
  return cmd;
}

// 把 agent 上报的 get_status 原始结果归一化成 Flask /api/status 同形快照：
//   agent 给的是扁平 egress_ip（字符串），不是 egress 对象；
//   online_users 是 Flask 现算的（clients 列表长度），agent 只给 clients 列表；
//   proto/port/subnet/dns 不在 agent 结果里，由读快照时按 servercfg 补（见 cachedStatus）。
// 密码字段绝不写入快照。
// R42-F4-1：归一化结果本身不打 at —— at 只由 get_status 回执在
// handleAgentReport 里落戳（Flask R11-P1-1：心跳不打 at）。旧版在
// 这里落戳，导致任何命令回执都刷新快照年龄。
function snapshotFromResult(result) {
  if (!result || typeof result !== "object") return null;
  const snap = {};
  if (result.openvpn && typeof result.openvpn === "object") {
    const ov = result.openvpn;
    snap.openvpn = {
      running: !!ov.running,
      unit_active: ov.unit_active !== undefined ? ov.unit_active : null,
      pid: ov.pid !== undefined ? ov.pid : null,
      clients: Array.isArray(ov.clients) ? ov.clients : [],
      online_users: Array.isArray(ov.clients)
        ? ov.clients.length
        : ov.online_users || 0,
      error: ov.error !== undefined ? ov.error : null,
    };
  }
  if (typeof result.egress_ip === "string" && result.egress_ip) {
    snap.egress = { ip: result.egress_ip };
  } else if (result.egress && typeof result.egress === "object") {
    snap.egress = result.egress;
  }
  if (result.sk5 && typeof result.sk5 === "object") {
    const { password, ...safe } = result.sk5;
    snap.sk5 = safe;
  }
  if (Array.isArray(result.users)) snap.users = result.users;
  return snap;
}

// R45-L7-1: Flask _remote_status_payload 同款的 remote 判定
// （core ip_is_private: is_private / loopback / link-local / reserved /
// multicast 任一即真；不可解析即真——调用方报警告）。Worker 没有
// Python ipaddress，用手工范围表镜像它；100.64/10 在本版 Python
// (3.12) 的 is_private 里是 False，这里同样不算内网。
function parseIpv6(s) {
  if (typeof s !== "string" || !s.includes(":")) return null;
  // 带点的尾段（::ffff:1.2.3.4）只许出现在地址末尾。
  if (s.includes(".") && !/:[^:]*\.[^:]*$/.test(s)) return null;
  const dbl = s.split("::");
  if (dbl.length > 2) return null;
  const parsePart = (part) => {
    if (!part) return [];
    const out = [];
    for (const g of part.split(":")) {
      if (g.includes(".")) {
        const m = g.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
        if (!m) return null;
        const o = m.slice(1).map(Number);
        if (o.some((n) => n > 255)) return null;
        out.push((o[0] << 8) | o[1], (o[2] << 8) | o[3]);
      } else {
        if (!/^[0-9a-fA-F]{1,4}$/.test(g)) return null;
        out.push(parseInt(g, 16));
      }
    }
    return out;
  };
  if (dbl.length === 1) {
    const groups = parsePart(dbl[0]);
    return groups && groups.length === 8 ? groups : null;
  }
  const left = parsePart(dbl[0]);
  const right = parsePart(dbl[1]);
  if (!left || !right || left.length + right.length > 7) return null;
  return [...left, ...new Array(8 - left.length - right.length).fill(0), ...right];
}

function isPrivateIp(ip) {
  if (typeof ip !== "string" || !ip.trim()) return true;
  const s = ip.trim();
  const v4 = s.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (v4) {
    const o = v4.slice(1).map(Number);
    if (o.some((n) => n > 255)) return true;
    const [a, b, c] = o;
    if (a === 0 || a === 10 || a === 127) return true;
    if (a === 169 && b === 254) return true; // link-local
    if (a === 172 && b >= 16 && b <= 31) return true;
    if (a === 192 && b === 0) return true; // 192.0.0.0/24 IETF assignments
    if (a === 192 && b === 2) return true; // TEST-NET-1
    if (a === 192 && b === 168) return true;
    if (a === 198 && (b === 18 || b === 19)) return true; // 198.18/15 benchmarking
    if (a === 198 && b === 51 && c === 100) return true; // TEST-NET-2
    if (a === 203 && b === 0 && c === 113) return true; // TEST-NET-3
    if (a >= 224 && a <= 239) return true; // multicast
    if (a >= 240) return true; // reserved incl. 255.255.255.255
    return false;
  }
  if (!s.includes(":")) return true; // 不是 IP 字面量：Flask 同款报警告
  const g = parseIpv6(s);
  if (!g) return true;
  // IPv4-mapped ::ffff:a.b.c.d：Python 3.12 按内层 v4 判定。
  if (g.slice(0, 5).every((x) => x === 0) && g[5] === 0xffff) {
    return isPrivateIp(`${(g[6] >> 8) & 0xff}.${g[6] & 0xff}.${(g[7] >> 8) & 0xff}.${g[7] & 0xff}`);
  }
  if (g.every((x) => x === 0)) return true; // ::
  if (g[0] === 1 && g.slice(1).every((x) => x === 0)) return true; // ::1
  if ((g[0] & 0xffc0) === 0xfe80) return true; // fe80::/10 link-local
  if ((g[0] & 0xfe00) === 0xfc00) return true; // fc00::/7 unique-local
  if ((g[0] & 0xff00) === 0xff00) return true; // ff00::/8 multicast
  if (g[0] === 0x2001 && g[1] === 0x0db8) return true; // 2001:db8::/32 documentation
  if (g[0] === 0x0100 && g[1] === 0 && g[2] === 0 && g[3] === 0) return true; // 100::/64
  return false;
}

// Flask _remote_warning 同款文案（panel/app.py:1248）：内网地址即警告，
// 公网地址回 null（键仍在，与 Flask 形状一致）。
function remoteWarning(ip) {
  if (typeof ip !== "string" || !ip) return null;
  if (!isPrivateIp(ip)) return null;
  return `当前 .ovpn 的 remote 为内网地址 ${ip}，站外客户端连不上：请在上方填公网 IP/域名，或点“自动探测公网 IP”`;
}

function isIpLiteral(value) {
  const v4 = value.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (v4 && v4.slice(1).every((n) => Number(n) <= 255)) return true;
  if (value.includes(":") && parseIpv6(value)) return true;
  return false;
}

// Flask _valid_server_ip 同款：IP 字面量或主机名，不含空白与 shell 元字符。
function isValidServerIp(value) {
  if (/[\s"';&|<>$`\\]/.test(value)) return false;
  if (isIpLiteral(value)) return true;
  return /^[A-Za-z0-9._:-]{1,253}$/.test(value) && !value.includes("..");
}

// 读快照时把建服务配置合并进 openvpn 段（Flask 是现算这四个字段的）。
async function mergeServerCfg(env, nodeName, openvpn) {
  const cfg = await kvGetJson(env, `servercfg:${nodeName}`);
  const ovpn = { ...(openvpn || { running: false }) };
  if (cfg) {
    ovpn.proto = cfg.proto || null;
    ovpn.port = cfg.port !== undefined ? cfg.port : null;
    ovpn.subnet = cfg.subnet || FIXED_SUBNET;
    ovpn.dns = cfg.dns || FIXED_DNS;
  }
  return ovpn;
}

// R41-L5-P2-3: 从快照派生 openvpn/sk5 段（Flask _remote_status_payload
// 同款）：全量对象优先；心跳形快照只有扁平键（openvpn_running /
// sk5_enabled，见 handleAgentPoll 的心跳合并）时从扁平键派生；
// 都没有时回 null。sk5Full 标记 sk5 是否来自全量对象——心跳形时
// policy_routing_active 未测，via_sk5 须保持 null、不编造。
function deriveSnapshotSections(snap) {
  const s = snap && typeof snap === "object" && !Array.isArray(snap) ? snap : {};
  const ovpn =
    s.openvpn && typeof s.openvpn === "object"
      ? s.openvpn
      : typeof s.openvpn_running === "boolean"
        ? { running: s.openvpn_running }
        : null;
  const sk5Obj = s.sk5 && typeof s.sk5 === "object" ? s.sk5 : null;
  const sk5Full = !!sk5Obj && Object.keys(sk5Obj).length > 0;
  const sk5 = sk5Full
    ? sk5Obj
    : typeof s.sk5_enabled === "boolean"
      ? { enabled: s.sk5_enabled }
      : {};
  const sk5Enabled = "enabled" in sk5 ? !!sk5.enabled : null;
  return { ovpn, sk5, sk5Full, sk5Enabled };
}

// ---------- 控制面：登录 / 节点注册 ----------

// 登录限流（P1-3，与 Flask 同口径）：同一 IP 5 分钟内 5 次失败即锁 15 分钟。

// R23-P2-4：loginfail:<ip> 记录归一化。手改 KV 可能把记录写成数组／
// 字符串等非对象值；recordLoginFailure 直接在记录上挂 failures 属性，
// JSON.stringify 序列化数组时丢弃额外属性——失败计数每次写回都被丢
// 掉，该 IP 永不锁定（6 次错密全 401 无 429）。读回的记录先过此守卫：
// null/undefined 是正常初态（首次失败），静默按空记录计；非对象／
// 数组一律重置为 {failures: [], locked_until: 0} 并 console.warn 记
// 键与 typeof，不写记录内容（与 BJ 的 kvArray 同族）；对象缺字段
// 时只补缺的字段，已有失败计数保留。字段级损坏（failures 非数组）
// 不在此归一化——Flask 同款为 loud 500（R23 §2.8 矩阵），Worker
// 保持同款响亮失败，见 br_loginfail_array.mjs 的 B8 格。
function kvLoginFailRecord(value, key) {
  if (value === null || value === undefined) {
    return { failures: [], locked_until: 0 };
  }
  if (typeof value !== "object" || Array.isArray(value)) {
    console.warn(`loginfail record ${key} is not an object (${Array.isArray(value) ? "array" : typeof value}); resetting to empty`);
    return { failures: [], locked_until: 0 };
  }
  if (value.failures === undefined) value.failures = [];
  if (value.locked_until === undefined) value.locked_until = 0;
  return value;
}

async function loginLockedUntil(env, ip) {
  const rec = kvLoginFailRecord(await kvGetJson(env, `loginfail:${ip}`), `loginfail:${ip}`);
  if (!rec.locked_until) return 0;
  return rec.locked_until > nowMs() ? rec.locked_until : 0;
}

async function recordLoginFailure(env, ip) {
  const now = nowMs();
  const rec = kvLoginFailRecord(await kvGetJson(env, `loginfail:${ip}`), `loginfail:${ip}`);
  const windowStart = now - LOGIN_WINDOW_SECONDS * 1000;
  rec.failures = (rec.failures || []).filter((t) => t > windowStart);
  rec.failures.push(now);
  if (rec.failures.length >= LOGIN_MAX_FAILURES) {
    rec.locked_until = now + LOGIN_LOCK_SECONDS * 1000;
    rec.failures = [];
  }
  await kvPutJson(env, `loginfail:${ip}`, rec, {
    expirationTtl: LOGIN_LOCK_SECONDS + LOGIN_WINDOW_SECONDS,
  });
}

async function handleLogin(request, env) {
  const body = await readJson(request);
  // R13-P2-4：畸形请求体不是一次失败登录——与 Flask `_json_body`
  // 同款：非 JSON／非对象体先回 400 且不记限流。readJson 对非 JSON
  // 与 JSON 标量回 null，但数组的 typeof 也是 "object"，须另判。
  if (!body || Array.isArray(body)) {
    return err("请求体须为 JSON 对象", 400);
  }
  const password = typeof body.password === "string" ? body.password : "";
  const secret = env.ADMIN_PASSWORD || "";
  if (!secret) return err("服务端未设置 ADMIN_PASSWORD（wrangler secret put ADMIN_PASSWORD）", 500);
  const ip = clientIp(request);
  const lockedUntil = await loginLockedUntil(env, ip);
  if (lockedUntil) {
    const retry = Math.ceil((lockedUntil - nowMs()) / 1000);
    return json(
      { ok: false, error: `登录失败过多，已锁定，请 ${retry} 秒后再试`, retry_after_s: retry },
      429,
      { "Retry-After": String(retry) },
    );
  }
  if (!password || !(await safeEqual(password, secret))) {
    await recordLoginFailure(env, ip);
    return err("密码错误", 401);
  }
  await env.PANEL_KV.delete(`loginfail:${ip}`);
  const sessionId = randomHex(32);
  await kvPutJson(
    env,
    `session:${sessionId}`,
    { created_at: nowMs(), expires_at: nowMs() + SESSION_TTL_S * 1000 },
    { expirationTtl: SESSION_TTL_S },
  );
  return json(
    { ok: true, admin: true },
    200,
    { "Set-Cookie": sessionCookieHeader(request, sessionId) },
  );
}

async function handleLogout(request, env) {
  const sessionId = getCookie(request, "panel_session");
  if (sessionId) await env.PANEL_KV.delete(`session:${sessionId}`);
  return json(
    { ok: true },
    200,
    { "Set-Cookie": clearSessionCookieHeader() },
  );
}

// agent 安装命令（与 Flask 面板 buildInstallCommand 同一口径，
// R2-BUG-11/12 同族修）：默认自签面板上 plain curl 连脚本都下不下来，
// 故 -k 下脚本；.sha256 必须取到且 sha256sum -c 通过才执行，校验失败
// 即停，不许 warn 后继续跑未验脚本；且必须带 --node-name <注册名>，
// 否则 agent 默认用 hostname 注册，poll 恒 401。
// .sha256 文件须为 `sha256sum -c` 可读的 "<hash>  install-agent.sh" 格式。
function shellQuote(s) {
  return "'" + String(s).replace(/'/g, "'\\''") + "'";
}
function installCommand(panelUrl, token, nodeName) {
  const base = String(panelUrl || "").replace(/\/$/, "");
  let cmd =
    `curl -ksSL ${shellQuote(base + "/install-agent.sh")} -o /tmp/install-agent.sh && ` +
    `curl -ksSL ${shellQuote(base + "/install-agent.sh.sha256")} -o /tmp/install-agent.sh.sha256 && ` +
    `cd /tmp && sha256sum -c install-agent.sh.sha256 && ` +
    `bash /tmp/install-agent.sh --panel-url ${shellQuote(base)} --token ${shellQuote(token)}`;
  if (nodeName) cmd += " --node-name " + shellQuote(nodeName);
  return cmd;
}

async function handleListNodes(request, env) {
  const nodes = await listNodes(env);
  // R45-LIVE-2: 源站当前 bundle 哈希只取一次，供全表 agent 代码
  // 过期标记复用（取不到时各节点的 outdated 即未知，不谎报）。
  const currentHash = await originBundleSha256(env);
  const out = [];
  for (const n of nodes) {
    const snap = await kvGetJson(env, `status:${n.name}`);
    // R41-L5-P2-3：心跳形快照的扁平键也参与派生（全量对象优先）。
    const { ovpn: ovpnRaw, sk5Enabled } = deriveSnapshotSections(snap);
    const installedHash =
      (snap && typeof snap.bundle_sha256 === "string" && snap.bundle_sha256) || null;
    const ovpn = ovpnRaw ? await mergeServerCfg(env, n.name, ovpnRaw) : null;
    out.push({
      name: n.name,
      panel_url: n.panel_url || null,
      created_at: n.created_at,
      last_seen: n.last_seen || null,
      openvpn: ovpn,
      online_users: ovpn ? ovpn.online_users || 0 : null,
      egress_ip: snap && snap.egress ? snap.egress.ip || null : null,
      sk5_enabled: sk5Enabled,
      agent_bundle_sha256: installedHash,
      agent_code_outdated: installedHash
        ? (currentHash ? installedHash !== currentHash : null)
        : null,
      status_age_s:
        snap && snap.at ? Math.floor((nowMs() - snap.at) / 1000) : null,
    });
  }
  return json({ ok: true, nodes: out });
}

async function handleRegisterNode(request, env) {
  const body = await readJson(request);
  if (!body) return err("请求体须为 JSON", 400);
  const name = typeof body.name === "string" ? body.name.trim() : "";
  if (!NAME_RE.test(name)) {
    return err("节点名非法：只允许字母/数字/_/-，1–32 字符", 400);
  }
  const panelUrl = typeof body.panel_url === "string" ? body.panel_url.trim() : "";
  if (panelUrl && !/^https?:\/\/.+/.test(panelUrl)) {
    return err("panel_url 须以 http:// 或 https:// 开头", 400);
  }
  if (await kvGetJson(env, `node:${name}`)) {
    return err(`节点已存在：${name}`, 409);
  }
  // token 明文只返回一次：调用方（装机脚本）须当场记下，KV 里只存哈希。
  const token = `${randomHex(16)}-${randomHex(16)}`;
  const finalPanelUrl = panelUrl || new URL(request.url).origin;
  await kvPutJson(env, `node:${name}`, {
    name,
    token_hash: await sha256Hex(token),
    panel_url: finalPanelUrl,
    created_at: nowMs(),
    last_seen: null,
  });
  await kvPutJson(env, `queue:${name}`, [], { expirationTtl: CMD_TTL_S });
  return json(
    {
      ok: true,
      node: { name, panel_url: finalPanelUrl },
      token,
      install_command: installCommand(finalPanelUrl, token, name),
      note: "token 与安装命令只返回这一次，请当场记下；丢失只能轮换，不可找回",
    },
    201,
  );
}

// P1-4：吊销节点。旧 token 立即作废（节点记录删除，poll 即 401）；
// 排队中与已下发未回执的命令一律标失败——节点已死，这些命令不可能再完成。
async function handleRevokeNode(request, env, name) {
  if (!NAME_RE.test(name)) return err("节点名非法", 400);
  if (!(await kvGetJson(env, `node:${name}`))) {
    return err(`节点不存在：${name}`, 404);
  }
  const queue0 = kvArray(await kvGetJson(env, `queue:${name}`), `queue:${name}`);
  const sent0 = kvArray(await kvGetJson(env, `sent:${name}`), `sent:${name}`);
  // R18-P2-2：先 sweep——畸形记录先落 failed（revoke 的只标 queued/sent
  // 循环救不了它们，记录会滞留至 TTL）；孤儿 queued 记录重新入队后
  // 同样被下面的循环标失败，不再漏网。调用方以返回值为准。
  const { queue, sent } = await _sweepWorkerCmds(env, name, queue0, sent0);
  const now = nowMs();
  for (const id of [...queue, ...sent.map((e) => e.id)]) {
    const cmd = await kvGetJson(env, `cmd:${id}`);
    if (!cmd || (cmd.status !== "queued" && cmd.status !== "sent")) continue;
    cmd.status = "failed";
    cmd.error = "节点已吊销";
    cmd.finished_at = now;
    await kvPutJson(env, `cmd:${id}`, cmd, { expirationTtl: CMD_TTL_S });
  }
  await env.PANEL_KV.delete(`node:${name}`);
  await env.PANEL_KV.delete(`queue:${name}`);
  await env.PANEL_KV.delete(`sent:${name}`);
  await env.PANEL_KV.delete(`status:${name}`);
  return json({ ok: true, node: name });
}

// P1-4：轮换节点 token。旧 token 立即作废（哈希已换，旧 token poll 即 401）；
// 排队中的命令保留——新 token 的 agent 重装后仍会取走执行。
async function handleRotateNode(request, env, name) {
  if (!NAME_RE.test(name)) return err("节点名非法", 400);
  const rec = await kvGetJson(env, `node:${name}`);
  if (!rec) return err(`节点不存在：${name}`, 404);
  const token = `${randomHex(16)}-${randomHex(16)}`;
  rec.token_hash = await sha256Hex(token);
  await kvPutJson(env, `node:${name}`, rec);
  const panelUrl = rec.panel_url || new URL(request.url).origin;
  return json(
    {
      ok: true,
      node: { name },
      token,
      install_command: installCommand(panelUrl, token, name),
      note: "新 token 与安装命令只返回这一次；旧 token 立即失效，须重跑安装命令",
    },
    200,
  );
}

// FLMX §1-10：一键安装命令入口。完整命令含 token，只在注册/轮换时返回一次；
// 此处返回模板（<NODE_TOKEN> 占位），供已记下 token 的管理员粘贴使用。
async function handleNodeInstall(request, env, name) {
  if (!NAME_RE.test(name)) return err("节点名非法", 400);
  const rec = await kvGetJson(env, `node:${name}`);
  if (!rec) return err(`节点不存在：${name}`, 404);
  const panelUrl = rec.panel_url || new URL(request.url).origin;
  return json({
    ok: true,
    node: name,
    panel_url: panelUrl,
    command_template: installCommand(panelUrl, "<NODE_TOKEN>", name),
    note: "把 <NODE_TOKEN> 换成注册/轮换时记下的 token 再粘贴执行；"
      + "安装命令须 -k 下脚本并校验 install-agent.sh.sha256，校验失败即停"
      + "（bundle 下发仍是 sha256 fail-closed）",
  });
}

// ---------- 控制面：agent 拉命令 / 回结果 ----------

// ---------- Worker 面命令 sweep 与孤儿回收（R18-P2-1 / R18-P2-2） ----------

// 合法命令状态（四态之外即畸形）。
const CMD_STATUSES = new Set(["queued", "sent", "done", "failed"]);

// sent_at 数值化：数值／数字串正常转；非数值（手改 KV 塞 "abc" 之类）
// 按 0 计——已超时方向（fail-closed），绝不因 NaN 比较恒假而永不超时
//（R18-P2-2 的 S4 缺口：`now - "abc"` 是 NaN，`NaN > 120000` 恒假）。
function toMs(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

// 把一条畸形命令记录标 failed＋隔离。原因只写判定谓词，绝不写记录内容
//（cmd params 可能含 SK5 密码、result 可能含 .ovpn 私钥）。
// Worker 侧无审计存储，原因进记录 error 字段＋console.warn（与 Flask
// `_fail_malformed_cmds` 的审计行同款作用）。能保留的身份字段尽量保留
//（id／node／action），其余一律置空，避免畸形值继续参与状态机。
async function _failMalformedCmd(env, id, orig, reason) {
  const isObj = orig && typeof orig === "object" && !Array.isArray(orig);
  console.warn(`sweep: malformed cmd ${id} (${reason}) -> failed`);
  await kvPutJson(
    env,
    `cmd:${id}`,
    {
      id,
      node: isObj && typeof orig.node === "string" ? orig.node : null,
      action: isObj && typeof orig.action === "string" ? orig.action : "unknown",
      params: {},
      status: "failed",
      result: null,
      error: `命令记录畸形，已隔离：${reason}`,
      retries: isObj && typeof orig.retries === "number" ? orig.retries : 0,
      created_at: isObj && typeof orig.created_at === "number" ? orig.created_at : nowMs(),
      sent_at: null,
      finished_at: nowMs(),
    },
    { expirationTtl: CMD_TTL_S },
  );
}

// R41-L6-P2-2: sent_at 须为可用时间戳（数值或数字串，且 > 0）。
// 缺失／null／非数值／布尔／<= 0 一律不可解析——Flask R13-P2-1
// 把这类 sent 命令直接标 failed，不走超时重投。
function usableSentAt(value) {
  if (typeof value === "number") return Number.isFinite(value) && value > 0;
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value);
    return Number.isFinite(n) && n > 0;
  }
  return false;
}

// sent 态超时处理（poll 的超时循环与 sweep 共用）：返回 "requeued"／
// "failed"／null（未超时）。调用方负责：requeued → 把 id 推回 queue；
// failed → 不再跟踪。sentAtOverride 为 sent 副本里的 sent_at（poll 循环
// 用它；sweep 无副本时传空，用记录自身的 sent_at）。
async function _handleSentTimeout(env, cmd, now, sentAtOverride) {
  // R41-L6-P2-2 (Flask R13-P2-1)：sent_at 缺失／不可解析的 sent 命令
  // 直接标 failed，绝不重发——不分动作是否幂等。旧行为把非数值经
  // toMs() 映射为 0（已超时方向），安全动作会被重投并重新下发，最多
  // 3 次无意义重执行。
  const rawSentAt = sentAtOverride ?? cmd.sent_at;
  if (!usableSentAt(rawSentAt)) {
    cmd.status = "failed";
    cmd.error = "sent_at 缺失／不可解析，命令已隔离标失败，不再下发（R13-P2-1）";
    cmd.finished_at = now;
    await kvPutJson(env, `cmd:${cmd.id}`, cmd, { expirationTtl: CMD_TTL_S });
    return "failed";
  }
  const sentAt = Number(rawSentAt);
  if (now - sentAt <= SENT_TIMEOUT_MS) return null;
  if (SAFE_RETRY_ACTIONS.has(cmd.action)) {
    const retries = (typeof cmd.retries === "number" ? cmd.retries : 0) + 1;
    cmd.retries = retries;
    if (retries > SENT_MAX_RETRIES) {
      cmd.status = "failed";
      cmd.error = `agent 超过 120 秒未回执，已重投 ${SENT_MAX_RETRIES} 次，放弃`;
      cmd.finished_at = now;
      await kvPutJson(env, `cmd:${cmd.id}`, cmd, { expirationTtl: CMD_TTL_S });
      return "failed";
    }
    cmd.status = "queued";
    cmd.sent_at = null;
    cmd.requeued_at = now;
    await kvPutJson(env, `cmd:${cmd.id}`, cmd, { expirationTtl: CMD_TTL_S });
    return "requeued";
  }
  cmd.status = "failed";
  cmd.error =
    "agent 超过 120 秒未回执（可能已死或离线）：未自动重发，"
    + "请确认 agent 状态后手动重新下发";
  cmd.finished_at = now;
  await kvPutJson(env, `cmd:${cmd.id}`, cmd, { expirationTtl: CMD_TTL_S });
  return "failed";
}

// Worker 面畸形 sweep＋孤儿回收（Flask `_fail_malformed_cmds` 同款，
// R18-P2-2）：在 poll／report／revoke／cmd_get 的读路径先扫，保证任何
// 记录都能经合法事件到达终态，不靠 7 天 TTL 删除“解决”。
//   - 非对象／缺 status／未知 status／缺 node 的记录 → 标 failed＋隔离；
//   - queued 但队列数组不引用的孤儿记录 → 重新入队（R18-P2-1 的自愈层；
//     即使队列写仍有残留竞态窗口，下一轮 poll 的 sweep 也会再捞回来）；
//   - sent 但 sent 副本不引用的记录 → 按超时规则处理（未超时恢复副本，
//     已超时走重投／标失败）；
//   - 其余记录不动。返回 { queue, sent }（可能已补孤儿），调用方以返回值为准。
// 队列写回用“重读＋并集”（不直接写回传入数组），避免 sweep 自己的写
// 覆盖 poll 窗口内新入队的 id；无改动时不写回（不与并发写争用）。
// list() 不可用时（如旧 harness 的 MockKV）静默退化为不扫——调用方
// 行为与修复前一致，绝不因此 500。
async function _sweepWorkerCmds(env, nodeName, queue, sent) {
  // 未传数组时（如 report／revoke／cmd_get 路径）先读 KV——绝不能默认
  // 空数组：空数组会让 sweep 把全部记录都当成孤儿（已验证的实测教训：
  // cmd_get 的 sweep 曾因此把未超时的 sent 记录也走超时处理）。
  let queueArr = Array.isArray(queue)
    ? queue
    : kvArray(await kvGetJson(env, `queue:${nodeName}`), `queue:${nodeName}`);
  let sentArr = Array.isArray(sent)
    ? sent
    : kvArray(await kvGetJson(env, `sent:${nodeName}`), `sent:${nodeName}`);
  if (!env.PANEL_KV || typeof env.PANEL_KV.list !== "function") {
    return { queue: queueArr, sent: sentArr };
  }
  const queueIds = new Set(queueArr);
  const sentIds = new Set(sentArr.map((e) => e && e.id).filter(Boolean));
  let queueChanged = false;
  let sentChanged = false;
  const now = nowMs();
  let cursor;
  for (;;) {
    const page = await env.PANEL_KV.list({ prefix: "cmd:", ...(cursor ? { cursor } : {}) });
    for (const entry of page.keys || []) {
      const id = entry.name.slice("cmd:".length);
      const cmd = await kvGetJson(env, entry.name);
      if (cmd === null || cmd === undefined) continue; // 已删／TTL 到期
      if (typeof cmd !== "object" || Array.isArray(cmd)) {
        await _failMalformedCmd(env, id, null, "记录不是 JSON 对象");
        continue;
      }
      if (typeof cmd.node !== "string" || !cmd.node) {
        await _failMalformedCmd(env, id, cmd, "缺 node");
        continue;
      }
      if (cmd.node !== nodeName) continue; // 别节点记录由其自身 poll 扫
      if (typeof cmd.status !== "string" || !CMD_STATUSES.has(cmd.status)) {
        await _failMalformedCmd(
          env,
          id,
          cmd,
          typeof cmd.status === "string" ? `未知 status：${cmd.status}` : "缺 status",
        );
        continue;
      }
      if (cmd.status === "queued" && !queueIds.has(id)) {
        console.warn(`sweep: orphan queued cmd ${id} re-enqueued`);
        queueArr.push(id);
        queueIds.add(id);
        queueChanged = true;
      } else if (cmd.status === "sent" && !sentIds.has(id)) {
        const outcome = await _handleSentTimeout(env, cmd, now);
        if (outcome === "requeued") {
          queueArr.push(cmd.id);
          queueIds.add(cmd.id);
          queueChanged = true;
        } else if (outcome === null) {
          sentArr.push({ id: cmd.id, action: cmd.action, sent_at: toMs(cmd.sent_at) });
          sentIds.add(cmd.id);
          sentChanged = true;
        }
        // outcome === "failed"：记录已标失败，不再跟踪。
      }
    }
    if (page.list_complete === false && page.cursor) {
      cursor = page.cursor;
      continue;
    }
    break;
  }
  if (queueChanged) {
    const fresh = kvArray(await kvGetJson(env, `queue:${nodeName}`), `queue:${nodeName}`);
    const merged = [...fresh];
    for (const id of queueArr) if (!merged.includes(id)) merged.push(id);
    await kvPutJson(env, `queue:${nodeName}`, merged, { expirationTtl: CMD_TTL_S });
  }
  if (sentChanged) {
    const fresh = kvArray(await kvGetJson(env, `sent:${nodeName}`), `sent:${nodeName}`);
    const merged = [...fresh];
    const mergedIds = new Set(merged.map((e) => e && e.id).filter(Boolean));
    for (const e of sentArr) {
      if (e && e.id && !mergedIds.has(e.id)) {
        merged.push(e);
        mergedIds.add(e.id);
      }
    }
    await kvPutJson(env, `sent:${nodeName}`, merged, { expirationTtl: CMD_TTL_S });
  }
  return { queue: queueArr, sent: sentArr };
}

async function handleAgentPoll(request, env) {
  // Body 只读一次，后面鉴权（body token）、认领守卫、node_name
  // 校验、心跳落快照共用——body 流只能消费一次。空 body／非 JSON
  // 按 {} 处理（旧版 agent 无 body 时按旧行为放行到鉴权）。
  let body = {};
  try {
    const parsed = await request.json();
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) body = parsed;
  } catch {
    // 空 body / 非 JSON：无认领、无 token、无心跳，按旧行为放行。
  }
  const node = await authenticateNode(request, env, body.node_token ?? null);
  if (!node) return err("节点 token 无效（须传 Authorization: Bearer <node_token> 或 body.node_token）", 401);
  // R3-P2-12：与 Flask _agent_auth 同口径——body 认领的 node_name 与
  // token 归属不符即 401（配错 --node-name 要 loud 失败，不许静默按
  // token 归属下发）。无 node_name 字段的旧版 agent 按旧行为放行。
  const claimedName = typeof body.node_name === "string" ? body.node_name : "";
  if (claimedName && claimedName !== node.name) {
    return err("token 与节点名不匹配", 401);
  }
  // R41-L5-P2-1：panel_url 认领守卫（Flask _check_panel_claim 同款）。
  const claim = checkPanelClaim(node, body);
  if (!claim.ok) return err(claim.error, 403);
  // R41-L5-P2-3：poll 心跳状态落快照（Flask agent_poll/_touch_node
  // 同款）：心跳键合并写，绝不覆盖全量 openvpn/sk5/egress/users
  // 对象；R42-F4-1：心跳不打 at（Flask R11-P1-1 同款）——at 只由
  // get_status 回执落戳，否则 age_s 量的是“距上次 poll”而非
  // “距上次实测”，poll-only 节点永远显示新鲜。
  if (body.status && typeof body.status === "object" && !Array.isArray(body.status)) {
    const prev = (await kvGetJson(env, `status:${node.name}`)) || {};
    const hb = {};
    if (typeof body.status.version === "string") hb.version = body.status.version;
    if (typeof body.status.hostname === "string") hb.hostname = body.status.hostname;
    if (typeof body.status.openvpn_running === "boolean") hb.openvpn_running = body.status.openvpn_running;
    if (typeof body.status.sk5_enabled === "boolean") hb.sk5_enabled = body.status.sk5_enabled;
    // R45-LIVE-2: agent 上报的安装包哈希随心跳进快照（panel 比对
    // 当前包后给出 agent_code_outdated；未上报即未知，不谎报）。
    // R46-L7-1: 心跳带了 bundle_sha256 键但不是字符串时写 null 进
    // 快照（Flask _touch_node 合并语义同款）——旧哈希不许残留，
    // 否则过期标记永远冻结在旧结论上；键不存在时不碰快照。
    if (typeof body.status.bundle_sha256 === "string") {
      hb.bundle_sha256 = body.status.bundle_sha256;
    } else if ("bundle_sha256" in body.status) {
      hb.bundle_sha256 = null;
    }
    await kvPutJson(env, `status:${node.name}`, { ...prev, ...hb });
  }
  const now = nowMs();
  let queue = kvArray(await kvGetJson(env, `queue:${node.name}`), `queue:${node.name}`);
  let sent = kvArray(await kvGetJson(env, `sent:${node.name}`), `sent:${node.name}`);

  // R18-P2-2：先 sweep（畸形隔离＋孤儿回收），再处理超时／下发。
  // sweep 可能补回队列／sent 副本，调用方以返回值为准。
  ({ queue, sent } = await _sweepWorkerCmds(env, node.name, queue, sent));

  // P1-6：先处理超时未回执的 sent 命令。安全动作自动回队（本次 poll 即重发），
  // 非幂等动作标失败（不自动重发，避免重复建用户/清 CA），管理员手动重发。
  // R3-P1-1：重投有上限（与 Flask SENT_MAX_RETRIES=3 同值）：超时重投时
  // retries +1，超过 3 次即标 failed 并清理 sent 副本，死 agent 的命令
  // 不再无限循环。
  const stillSent = [];
  for (const entry of sent) {
    const cmd = await kvGetJson(env, `cmd:${entry.id}`);
    if (!cmd) {
      // R27-P2-2: dangling sent id -- the cmd: record expired (7-day
      // CMD_TTL_S) while the sent: list still holds it. The entry is
      // dropped below (stillSent omits it); warn so the loss is
      // visible in logs instead of evaporating silently. Worker has
      // no audit store; console.warn is the only honest signal.
      console.warn(`worker poll: dangling sent command id ${entry.id} (cmd record expired or deleted)`);
      continue;
    }
    if (typeof cmd !== "object" || cmd.status !== "sent") continue;
    const outcome = await _handleSentTimeout(env, cmd, now, entry.sent_at);
    if (outcome === "requeued") {
      queue.push(cmd.id);
    } else if (outcome === null) {
      stillSent.push(entry);
    }
    // outcome === "failed"：不再跟踪。
  }
  sent = stillSent;

  // 下发队列里的命令：取走即记 sent（留 sent:<node> 副本供超时处理）。
  // R17-P1-1：下发列表只认 status === "queued"。队列数组里的 id 只是
  // “候选”，sweep／回执／超时已把记录标为 failed/done/sent 的，
  // 必须同步失去下发资格——否则已隔离的 init_pki 仍会被 agent 执行、
  // CA 被重建，而面板显示 failed（双重谎报）。状态缺失的手改条目
  // 同样跳过（不认状态即不下发）。
  const commands = [];
  const takenIds = new Set(queue); // 本轮实际取走的 id（含超时回队重发的）
  for (const id of queue) {
    const cmd = await kvGetJson(env, `cmd:${id}`);
    if (!cmd) {
      // R27-P2-2: dangling queued id -- the cmd: record expired (7-day
      // CMD_TTL_S) while the queue: list still holds it. The conditional
      // clear below drops the id; warn so the loss is visible in logs
      // instead of evaporating silently.
      console.warn(`worker poll: dangling queued command id ${id} (cmd record expired or deleted)`);
      continue;
    }
    if (cmd.status !== "queued") continue;
    cmd.status = "sent";
    cmd.sent_at = now;
    await kvPutJson(env, `cmd:${id}`, cmd, { expirationTtl: CMD_TTL_S });
    sent.push({ id: cmd.id, action: cmd.action, sent_at: now });
    commands.push({ id: cmd.id, action: cmd.action, params: cmd.params || {} });
  }
  // R18-P2-1：条件式清空——只清本次实际取走的 id。无条件写 [] 会丢命令：
  // enqueue 的读→push→写回若落在 poll 的清空写之前，该 id 永久丢失、
  // 记录卡 queued（旧行为）。重读当前队列再 filter：poll 窗口内新入队
  // 的 id 不在 takenIds 里，自然保留；已取走的 id 即使被并发 enqueue
  // 的写回短暂复活，也只是状态已 sent／done／failed 的旧 id，下一轮
  // poll 的守卫会跳过、条件式清空会摘掉，不会重复下发。
  const currentQueue = kvArray(await kvGetJson(env, `queue:${node.name}`), `queue:${node.name}`);
  await kvPutJson(
    env,
    `queue:${node.name}`,
    currentQueue.filter((id) => !takenIds.has(id)),
    { expirationTtl: CMD_TTL_S },
  );
  // sent 副本去重（并发 poll 可能重复记同一 id；超时循环按 id 去重处理，
  // 副本里不留重复条目）。
  const dedupedSent = [];
  const seenSentIds = new Set();
  for (const e of sent) {
    if (!e || !e.id || seenSentIds.has(e.id)) continue;
    seenSentIds.add(e.id);
    dedupedSent.push(e);
  }
  await kvPutJson(env, `sent:${node.name}`, dedupedSent, { expirationTtl: CMD_TTL_S });
  const rec = await kvGetJson(env, `node:${node.name}`);
  if (rec) {
    rec.last_seen = nowMs();
    await kvPutJson(env, `node:${node.name}`, rec);
  }
  const out = { ok: true, node: node.name, commands, poll_interval_s: POLL_INTERVAL_S };
  // R41-L5-P2-1：旧版 agent 未上报 panel_url 时放行，但提示升级
  //（Flask agent_poll 同款 panel_url_unverified）。
  if (claim.status === "unverified") out.panel_url_unverified = true;
  return json(out);
}

async function handleAgentReport(request, env) {
  // R41-L5-P2-2：body 先读出再鉴权（Flask _agent_auth 同款：body
  // token 也是有效凭证）。readJson 对非 JSON 体回 null，鉴权随后
  // 只认 header——与旧行为一致（header 有效＋坏 body 仍走下面的 400）。
  const body = await readJson(request);
  const node = await authenticateNode(request, env, body ? body.node_token ?? null : null);
  if (!node) return err("节点 token 无效（须传 Authorization: Bearer <node_token> 或 body.node_token）", 401);
  if (!body) return err("请求体须为 JSON", 400);
  // R41-L5-P2-1：panel_url 认领守卫（Flask agent_report 同款）。
  const claim = checkPanelClaim(node, body);
  if (!claim.ok) return err(claim.error, 403);

  // agent 发 id，Flask 面板侧用 cmd_id：两个都接受（任一有值即按命令
  // 回执处理；都没有才是纯心跳）。只认 cmd_id 时 agent 的回执会被
  // 当成心跳丢掉，命令永远停在 sent 态。
  const cmdId = body.cmd_id || body.id;
  // 纯心跳：无命令 id，只有状态快照时只更新快照与 last_seen。
  if (!cmdId) {
    if (body.status_snapshot) {
      // R42-F4-1：纯心跳回执按 Flask agent_report 同款合并写（不打
      // at、不丢弃旧快照的其它键）；旧版整存替换且带 at，等同一次
      // get_status 回执。
      const snap = snapshotFromResult(body.status_snapshot);
      if (snap) {
        const prev = (await kvGetJson(env, `status:${node.name}`)) || {};
        await kvPutJson(env, `status:${node.name}`, { ...prev, ...snap });
      }
    }
    const rec = await kvGetJson(env, `node:${node.name}`);
    if (rec) {
      rec.last_seen = nowMs();
      await kvPutJson(env, `node:${node.name}`, rec);
    }
    return json({ ok: true, heartbeat: true });
  }

  // R18-P2-2：先 sweep——畸形记录先落 failed（随后按 failed 走 409，
  // 而不是以畸形原态回 409 后继续滞留）；孤儿 queued 记录重新入队。
  await _sweepWorkerCmds(env, node.name, null, null);
  const cmd = await kvGetJson(env, `cmd:${cmdId}`);
  if (!cmd) return err(`命令不存在：${cmdId}`, 404);
  if (typeof cmd !== "object" || Array.isArray(cmd)) {
    // sweep 已隔离过一次仍读到非对象（并发写回）：再隔离一次后 409。
    await _failMalformedCmd(env, cmdId, null, "记录不是 JSON 对象");
    return err(`命令记录畸形，已隔离：${cmdId}`, 409);
  }
  if (cmd.node !== node.name) return err("该命令不属于本节点", 403);
  // R17-P1-1：只接受 sent 态命令的回执。queued/done/failed 命令的回执
  // 是陈旧 agent 的回执——不翻状态（否则 queued 命令先被报 failed、
  // 队列条目仍在，下一轮 poll 照常下发）。选 409（状态冲突，loud 失败）：
  // agent 的 report 失败只记一条 warning、无重试风暴（agent.py run_once
  // 捕获 _post_json 异常即记日志继续），重复回执也不会把已 done/failed
  // 的记录再翻一遍。Worker 侧无审计存储，409 正文即诚实信号。
  if (cmd.status !== "sent") {
    return err(`命令不在 sent 态（当前 ${cmd.status}），回执已忽略`, 409);
  }
  cmd.status = body.ok === true ? "done" : "failed";
  cmd.result = body.result !== undefined ? body.result : null;
  cmd.error = body.ok === true ? null : typeof body.error === "string" ? body.error : "agent 执行失败";
  cmd.finished_at = nowMs();
  await kvPutJson(env, `cmd:${cmd.id}`, cmd, { expirationTtl: CMD_TTL_S });
  // 回执到达即从 sent 副本里摘掉（不再参与超时重发/标失败）。
  const sent = kvArray(await kvGetJson(env, `sent:${node.name}`), `sent:${node.name}`);
  const kept = sent.filter((e) => e.id !== cmd.id);
  if (kept.length !== sent.length) {
    await kvPutJson(env, `sent:${node.name}`, kept, { expirationTtl: CMD_TTL_S });
  }

  // R42-F4-1（Flask R11-P1-1 同款）：快照只由 get_status 的成功回执
  // 更新并打 at；其它动作的回执不碰快照——enable_sk5 等回执是扁平
  // sk5-manager 结果（无 sk5 对象），旧版照单合并会刷新 age、覆盖
  // egress，却不更新 sk5 段，面板显示“新鲜”数据说 SK5 仍关。
  if (cmd.action === "get_status" && cmd.status === "done") {
    const snap = snapshotFromResult(body.result);
    if (snap) {
      const prev = (await kvGetJson(env, `status:${node.name}`)) || {};
      await kvPutJson(env, `status:${node.name}`, { ...prev, ...snap, at: nowMs() });
    }
  }
  // 建服务成功：记下 proto/port，供快照补 proto/port/subnet/dns（P1-5）。
  // R45-L7-2：同时记下对外地址，供建用户时补发给 agent（server_ip 键
  // 在场即设定/清空，缺键即保持旧值；非字符串一律不存——/api/cmd 直发
  // 的命令不经 validateCreateServer，脏值绝不能进 servercfg）。
  if (cmd.action === "create_server" && cmd.status === "done") {
    const params = cmd.params || {};
    const prev = (await kvGetJson(env, `servercfg:${node.name}`)) || {};
    await kvPutJson(env, `servercfg:${node.name}`, {
      proto: params.proto || "udp",
      port: params.port !== undefined ? params.port : 1194,
      subnet: FIXED_SUBNET,
      dns: FIXED_DNS,
      server_ip:
        typeof params.server_ip === "string"
          ? params.server_ip || null
          : prev.server_ip || null,
    });
  }
  // SK5 测试成功：记下原始结果，供 1-25 保存守卫用（同地址 UDP 失败即硬拒）。
  if (cmd.action === "test_sk5" && cmd.status === "done" && body.result) {
    await kvPutJson(env, `sk5test:${node.name}`, {
      at: nowMs(),
      ...(typeof body.result === "object" ? body.result : {}),
    });
  }
  // create_user 成功且带 .ovpn 文本时，存一份供面板下载（.ovpn 含私钥，见 README 安全说明）。
  if (cmd.action === "create_user" && cmd.status === "done") {
    const user = cmd.params && cmd.params.name;
    const ovpn = body.result && typeof body.result.ovpn === "string" ? body.result.ovpn : null;
    if (user && ovpn) {
      await kvPutJson(env, `ovpn:${node.name}:${user}`, { ovpn, at: nowMs() });
    }
  }
  const rec = await kvGetJson(env, `node:${node.name}`);
  if (rec) {
    rec.last_seen = nowMs();
    await kvPutJson(env, `node:${node.name}`, rec);
  }
  return json({ ok: true, cmd_id: cmd.id, status: cmd.status });
}

// ---------- 控制面：管理员下发命令 / 查结果 ----------

async function handleCreateCmd(request, env) {
  const body = await readJson(request);
  if (!body) return err("请求体须为 JSON", 400);
  const nodeName = typeof body.node === "string" ? body.node.trim() : "";
  const action = typeof body.action === "string" ? body.action.trim() : "";
  if (!nodeName) return err("须指定 node", 400);
  if (!ACTIONS.has(action)) {
    return json(
      { ok: false, error: `非法 action：${action}`, allowed: [...ACTIONS].sort() },
      400,
    );
  }
  if (!(await kvGetJson(env, `node:${nodeName}`))) {
    return err(`节点不存在：${nodeName}`, 404);
  }
  // R12-P2-4：typeof [] === "object"，数组须显式拦（Flask 同款 400）；
  // 其余非对象标量沿旧例回落 {}（agent 侧 _as_* 再验）。
  if (Array.isArray(body.params)) {
    return err("params 须为 JSON 对象", 400);
  }
  const params = body.params && typeof body.params === "object" ? body.params : {};
  const cmd = await enqueueCommand(env, nodeName, action, params);
  return json(
    // R6-P2-7: file-header contract promises 202 {ok:true, cmd_id,
    // queued:true}; the compat enqueue route already returns queued:true.
    { ok: true, cmd_id: cmd.id, node: nodeName, action, status: "queued", queued: true },
    202,
  );
}

// 查命令结果时把 params 里的密码脱敏（Flask 侧 cmd_get 同款 _redact_dict）。
function redactParams(params) {
  if (!params || typeof params !== "object") return params;
  const out = { ...params };
  if ("password" in out) out.password = out.password ? "••••••••" : "";
  return out;
}

async function handleGetCmd(request, env, id) {
  let cmd = await kvGetJson(env, `cmd:${id}`);
  if (!cmd) return err(`命令不存在：${id}`, 404);
  // R18-P2-2：先 sweep——畸形记录先落 failed 再返回（而不是原样返回
  // 畸形态）；非对象记录直接隔离后返回 failed 视图。
  if (typeof cmd !== "object" || Array.isArray(cmd)) {
    await _failMalformedCmd(env, id, null, "记录不是 JSON 对象");
    cmd = await kvGetJson(env, `cmd:${id}`);
  } else if (typeof cmd.node === "string" && cmd.node) {
    await _sweepWorkerCmds(env, cmd.node, null, null);
    cmd = await kvGetJson(env, `cmd:${id}`);
    if (!cmd) return err(`命令不存在：${id}`, 404);
  }
  const out = { ok: true, ...cmd, params: redactParams(cmd.params) };
  // sent_at 数值化：非数值按 0 计（已超时方向）；R18-P2-2 的 S4 缺口
  // 在此同样会因 NaN 比较恒假而丢 hint，数值化后不再丢。
  const sentAt = toMs(cmd.sent_at);
  if (cmd.status === "sent" && sentAt > 0 && nowMs() - sentAt > SENT_TIMEOUT_MS) {
    out.timeout_hint = "已下发超过 120 秒未回执：agent 可能已死或离线，可重新下发";
  }
  return json(out);
}

// ---------- 兼容层：单节点 UI（panel/templates/index.html）调的旧接口 ----------
// 语义：POST 类 = 下发命令进队列，返回 202 {ok:true, cmd_id, queued:true}；
// 202 只表示“已排队”，前端须按 cmd_id 轮询 GET /api/cmd/:id 等真实结果，
// 绝不凭 202 报成功（P0-1）。
// GET 类 = 读 KV 里的最近上报快照，带 stale / age_s，不保证实时。
// 多节点时须 ?node= 或 X-Node 指定节点；单节点自动用唯一节点。

async function cachedStatus(env, nodeName) {
  const snap = (await kvGetJson(env, `status:${nodeName}`)) || null;
  const ageS = snap && snap.at ? Math.floor((nowMs() - snap.at) / 1000) : null;
  // R41-L5-P2-3：心跳形快照的扁平键也参与派生（全量对象优先）。
  const { ovpn: ovpnRaw, sk5, sk5Full } = deriveSnapshotSections(snap);
  const ovpn = await mergeServerCfg(env, nodeName, ovpnRaw);
  // R45-L7-1: remote_ip / remote_warning 取快照原始出口 IP（Flask
  // _remote_status_payload 同款）——下面的 via_sk5 分支会把 egress.ip
  // 置 null（策略缺失时），所以先取原始值；快照无出口 IP 时两键缺席。
  const rawEgressIp =
    (snap && snap.egress && typeof snap.egress.ip === "string" && snap.egress.ip) ||
    (snap && typeof snap.egress_ip === "string" && snap.egress_ip) ||
    null;
  if (rawEgressIp) {
    ovpn.remote_ip = rawEgressIp;
    ovpn.remote_is_private = isPrivateIp(rawEgressIp);
    ovpn.remote_warning = remoteWarning(rawEgressIp);
  }
  const egress = (snap && snap.egress) || {};
  // R45-LIVE-2: agent 代码过期标记。installedHash 取心跳上报的
  // bundle_sha256（未上报即未知）；currentHash 只在有上报值时才取
  // （取不到即未知，绝不谎报）。
  const installedHash =
    (snap && typeof snap.bundle_sha256 === "string" && snap.bundle_sha256) || null;
  const currentHash = installedHash ? await originBundleSha256(env) : null;
  const agentCodeOutdated = installedHash
    ? (currentHash ? installedHash !== currentHash : null)
    : null;
  // R7-P1-1: via_sk5 的唯一判据是实测的 policy_routing_active，与 Flask
  // status() 同款。agent 的 get_status() 在 enabled 时恒写 egress_ip
  // 探针值，只看 sk5.enabled 会在策略路由缺失时谎称流量经 SK5
  //（R6-P1-1 同款谎言换控制面）。快照里缺该字段时按缺失处理（不撒谎）。
  if (sk5Full && sk5.enabled && sk5.policy_routing_active) {
    // 策略在位：复用探针 IP；探针取不到时 ip=null 但 via_sk5 仍为 true
    //（流量进链后黑洞，kill-switch 工作态，case D）。
    egress.via_sk5 = true;
    egress.ip = egress.ip || null;
  } else if (sk5Full && sk5.enabled) {
    // 策略缺失：流量根本不走链，绝不复用探针 IP。
    egress.via_sk5 = false;
    egress.ip = null;
    egress.error = "SK5 已启用但策略路由未生效，出口未经过 SK5";
  } else if (sk5Full) {
    // SK5 未启用：快照里的 ip 即直连探针 IP，via_sk5 恒为 false。
    egress.via_sk5 = false;
    egress.ip = egress.ip || null;
  } else if (snap && (typeof snap.sk5_enabled === "boolean" || typeof snap.openvpn_running === "boolean")) {
    // R41-L5-P2-3：心跳形快照——policy 状态未测，via_sk5 保持 null、
    // 不编造（Flask _remote_status_payload 同款；sk5Full 为假时上面
    // 三支都不应落，全量缺失即未知）。
    egress.via_sk5 = null;
    egress.ip = egress.ip || null;
  } else {
    // 无快照／无 sk5 信息：沿旧行为，via_sk5 为 false。
    egress.via_sk5 = false;
    egress.ip = egress.ip || null;
  }
  return {
    ok: true,
    node: nodeName,
    openvpn: ovpn,
    egress,
    sk5,
    users: (snap && snap.users) || [],
    stale: ageS === null || ageS > 60,
    age_s: ageS,
    agent_bundle_sha256: installedHash,
    agent_code_outdated: agentCodeOutdated,
    note:
      ageS === null
        ? "节点尚未上报状态：agent 首次 poll 后执行一次 get_status 即可"
        : undefined,
  };
}

// R41-L6-P2-1: GET /api/openvpn/public-ip（Flask ovpn_public_ip 同款）。
// 指名节点时读该节点的已存快照出口 IP（快照无出口 IP 时诚实 502，
// 绝不拿本机 IP 冒充）；未指名时按 resolveNode 的单节点回落。Worker
// 无法探测中转机本机的出口 IP（边缘节点的出口不是中转机的出口），
// 所以没有“本机探测”分支——Flask 的 docstring 同款结论（“Cloudflare
// 模式无此端点”指的是本机探测，不是整条路由）。
async function handlePublicIp(request, env) {
  const { node, error } = await resolveNode(request, env);
  if (error) return error;
  const snap = (await kvGetJson(env, `status:${node.name}`)) || {};
  const egress = snap.egress && typeof snap.egress === "object" ? snap.egress : {};
  const ip =
    (typeof egress.ip === "string" && egress.ip) ||
    (typeof snap.egress_ip === "string" && snap.egress_ip) ||
    null;
  if (!ip) {
    return json(
      { ok: false, error: "节点尚未上报出口 IP：先让 agent 上报一次 get_status" },
      502,
    );
  }
  return json({ ok: true, ip });
}

async function handleCompatStatus(request, env) {
  const { node, error } = await resolveNode(request, env);
  if (error) return error;
  return json(await cachedStatus(env, node.name));
}

async function handleCompatEnqueue(request, env, action, paramsOf, needsBody = false, validate = null) {
  const body = await readJson(request);
  // R31-P2-1: body-reading actions (create_server/create_user) refuse
  // a malformed / non-object / wrong-content-type body with 400, like
  // Flask _json_body — the guard runs before any default or enqueue.
  // Bare actions (start/stop/restart/test/enable/disable/revoke)
  // ignore the body on both faces, so they keep the old `|| {}` and
  // are deliberately NOT gated (gating them would break E19/E20).
  if (needsBody && !body) return err("请求体须为 JSON 对象", 400);
  const b = body || {};
  const { node, error } = await resolveNode(request, env, b);
  if (error) return error;
  // R44-L4-F1/F2: the compat-enqueue layer used to validate only
  // node/action/params-shape and never the action's own field
  // semantics, so a bad proto/port/name got a misleading 202 and
  // only failed at the agent. Validate before enqueueing, with
  // Flask's messages and the same acceptance (Flask _valid_port
  // takes true ints only; proto is case-insensitive on both faces).
  if (validate) {
    const verr = validate(b);
    if (verr) return err(verr, 400);
  }
  const params = paramsOf ? await paramsOf(b, node) : {};
  const cmd = await enqueueCommand(env, node.name, action, params);
  return json(
    { ok: true, cmd_id: cmd.id, node: node.name, action, status: "queued", queued: true },
    202,
  );
}

// R7-P2-9 / Y2: 重建 CA 兼容转发。破坏性意图先验（与 Flask
// /api/openvpn/init-pki 同款顺序）：缺 force/confirm 一律 400，
// 不走到节点判定；入队 init_pki {force:true, confirm:true}。
// 登录保护与鉴权同其他 compat 路由（路由表在 requireAdmin 之后）。
// R44-L4-F1/F2: pre-enqueue field validation for the compat routes
// (see handleCompatEnqueue). Type names mirror Flask's
// _strict_str message (type(value).__name__): a JSON 123 is "int",
// true is "bool", null is "NoneType".
function pyTypeName(v) {
  if (v === null) return "NoneType";
  if (Array.isArray(v)) return "list";
  if (typeof v === "number") return Number.isInteger(v) ? "int" : "float";
  if (typeof v === "boolean") return "bool";
  if (typeof v === "string") return "str";
  return "dict";
}

function validateCreateServer(b) {
  if (b.proto !== undefined && b.proto !== null) {
    if (typeof b.proto !== "string" || !["udp", "tcp"].includes(b.proto.toLowerCase())) {
      return "proto 只能为 udp 或 tcp";
    }
  }
  if (b.port !== undefined && b.port !== null) {
    if (!Number.isInteger(b.port) || b.port < 1 || b.port > 65535) {
      return "port 须为 1-65535 的整数";
    }
  }
  // R45-L7-2: server_ip 随命令转发，入队前先验（Flask _strict_str +
  // _valid_server_ip 同款：缺键即保持旧值，空串即清除，非空须合法）。
  if (b.server_ip !== undefined && b.server_ip !== null) {
    if (typeof b.server_ip !== "string") {
      return `server_ip 须为字符串，收到 ${pyTypeName(b.server_ip)}`;
    }
    if (b.server_ip.trim() && !isValidServerIp(b.server_ip.trim())) {
      return "server_ip 不合法：须为 IP 或主机名";
    }
  }
  return null;
}

function validateCreateUser(b) {
  if (b.name !== undefined && b.name !== null && typeof b.name !== "string") {
    return `用户名须为字符串，收到 ${pyTypeName(b.name)}`;
  }
  return null;
}

async function handleCompatInitPki(request, env) {
  const body = await readJson(request);
  if (!body) return err("请求体须为 JSON", 400);
  if (body.force !== true) {
    return err("重建 CA 须显式传 force=true：将销毁现有 CA，全部已签发用户证书立即失效", 400);
  }
  if (body.confirm !== true) {
    return err("重建 CA 须并传 confirm=true 二次确认：全部已签发用户证书将失效，须重建用户并重新下载 .ovpn", 400);
  }
  const { node, error } = await resolveNode(request, env, body);
  if (error) return error;
  const cmd = await enqueueCommand(env, node.name, "init_pki", { force: true, confirm: true });
  return json(
    { ok: true, cmd_id: cmd.id, node: node.name, action: "init_pki", status: "queued", queued: true },
    202,
  );
}

async function handleCompatUsers(request, env) {
  const { node, error } = await resolveNode(request, env);
  if (error) return error;
  const snap = (await kvGetJson(env, `status:${node.name}`)) || {};
  return json({ ok: true, node: node.name, users: snap.users || [] });
}

async function handleCompatSk5Get(request, env) {
  const { node, error } = await resolveNode(request, env);
  if (error) return error;
  const snap = (await kvGetJson(env, `status:${node.name}`)) || {};
  // 快照里不含密码（snapshotFromResult 已剔除），前端密码框留空即不覆盖。
  return json({ ok: true, node: node.name, sk5: snap.sk5 || {} });
}

async function handleCompatOvpnDownload(request, env, name) {
  const { node, error } = await resolveNode(request, env);
  if (error) return error;
  const rec = await kvGetJson(env, `ovpn:${node.name}:${name}`);
  if (!rec || !rec.ovpn) {
    return err(`该用户 .ovpn 尚未生成/上报：先建用户，等 agent 回执后再下载`, 404);
  }
  // R19-P2-2：下载前查快照 users 守卫（Flask _download_block_reason 同款，
  // R13-P2-3）：快照里该用户 revoked／expired 一律 403，文案与 Flask 面
  // 同义（"用户 <名> <原因>"）。无快照／快照无该用户条目时放行——与
  // Flask _snapshot_users 回空 dict 时放行同款（快照滞后 caveat：吊销
  // 后、下次 get_status 上报前仍可下载；证书已进 CRL，握手会拒，下载
  // 本身不授予接入）。
  const snap = (await kvGetJson(env, `status:${node.name}`)) || {};
  const users = Array.isArray(snap.users) ? snap.users : [];
  const entry = users.find((u) => u && typeof u === "object" && u.name === name);
  const status = entry && typeof entry.status === "string" ? entry.status : null;
  if (status === "revoked") {
    return err(`用户 ${name} 已被吊销，.ovpn 不可下载（证书已进 CRL）`, 403);
  }
  if (status === "expired") {
    return err(`用户 ${name} 证书已过期，.ovpn 不可下载`, 403);
  }
  return new Response(rec.ovpn, {
    status: 200,
    headers: {
      "Content-Type": "application/x-openvpn-profile",
      "Content-Disposition": `attachment; filename="${name}.ovpn"`,
    },
  });
}

// POST /api/sk5（全量保存）：set_sk5 是全量覆盖（P1-15），
// agent 强制要求 host+port，缺一律 400，不下发必败命令。
// 密码框留空 = 不覆盖已存密码（P0-4 Worker 侧）；1-25 守卫见内联注释。
async function handleCompatSk5Save(request, env) {
  const { body, tokens } = await readJsonRaw(request);
  // R31-P2-1: envelope guard (Flask _json_body parity). A null body
  // used to fall through to the host check and 400 "host 不能为空";
  // the verdict is unchanged (still 400), only the message unifies to
  // the envelope wording. A valid JSON body with a non-JSON
  // Content-Type now 400s here instead of executing (C5).
  if (!body) return err("请求体须为 JSON 对象", 400);
  const b = body;
  const { node, error } = await resolveNode(request, env, b);
  if (error) return error;
  const host = typeof b.host === "string" ? b.host.trim() : "";
  const port = b.port;
  if (!host) return err("host 不能为空", 400);
  // R30-P2-1: the port token must be a plain integer literal.
  // Number.isInteger(1001.0) is true in JS, but Flask's
  // `type(value) is int` rejects 1001.0 — check the raw token.
  const portToken = tokens ? tokens.get("port") ?? null : null;
  if (
    typeof port !== "number" ||
    portToken === null ||
    !INT_TOKEN_RE.test(portToken) ||
    port < 1 ||
    port > 65535
  ) {
    return err("port 须为 1-65535 的整数", 400);
  }
  const stored = (await kvGetJson(env, `sk5cfg:${node.name}`)) || {};
  // 1-25：服务是 UDP 模式，且同一地址的 SK5 最近一次 UDP 测试明确失败——
  // 保存即硬拒并明示，不许“保存成功、UDP 默默不通”。未测过的不拦（前端会提示先测）。
  const serverCfg = await kvGetJson(env, `servercfg:${node.name}`);
  if (serverCfg && serverCfg.proto === "udp") {
    const lastTest = await kvGetJson(env, `sk5test:${node.name}`);
    if (
      lastTest &&
      lastTest.udp_ok === false &&
      lastTest.host === host &&
      Number(lastTest.port) === Number(port)
    ) {
      return err(
        "该 SK5 的 UDP 测试失败过（UDP ASSOCIATE 不通），而服务是 UDP 模式："
        + "请切 TCP 443 或换支持 UDP 的 SK5",
        400,
      );
    }
  }
  let password = typeof b.password === "string" ? b.password : "";
  if (!password && stored.password) password = stored.password;
  const params = {
    host,
    port,
    username: typeof b.username === "string" ? b.username : stored.username || "",
    password,
    enabled: typeof b.enabled === "boolean" ? b.enabled : !!stored.enabled,
    fail_open: typeof b.fail_open === "boolean" ? b.fail_open : !!stored.fail_open,
    udp_over_tcp:
      typeof b.udp_over_tcp === "boolean" ? b.udp_over_tcp : !!stored.udp_over_tcp,
  };
  await kvPutJson(env, `sk5cfg:${node.name}`, params);
  const cmd = await enqueueCommand(env, node.name, "set_sk5", params);
  return json(
    { ok: true, cmd_id: cmd.id, node: node.name, action: "set_sk5", status: "queued", queued: true },
    202,
  );
}

// fail-open / udp-over-tcp 开关（P0-2）：set_sk5 是全量覆盖，单字段必被 agent 拒收。
// 下发前先读 sk5cfg:<node> 补齐 host/port/username/password/enabled，
// 无已存配置时明确 400，绝不发缺字段的命令。
// R29-P2-1：开关输入须严格规整（Flask _coerce_bool 同口径，R12-P2-1）。
// 在键时只接受真布尔或 0/1 整数，其余一律 400——旧代码用 typeof 回落＋
// 终端 `: false`，字符串 "true"／1 会静默入队 false（与 Flask 面反向）。
// 缺键时：fail-open 只读本键，默认 False；udp-over-tcp 回落 `enabled`
// 键（R12-P2-2 已裁定，与 Flask _toggle_value 同款），两者都缺才默认 False。
// R30-P2-1: `token` is the raw source token for the field. After
// JSON.parse, 1.0 and 1 are the same number, but Flask rejects 1.0
// (isinstance float) — so a bare Number.isInteger check is not the
// same口径. A number value passes only when its token is a plain
// integer literal; `1.0`, `1.00`, `1e0`, `1.5` all 400.
function coerceToggleBool(value, key, token) {
  if (typeof value === "boolean") return { value, error: null };
  if (
    typeof value === "number" &&
    token !== null &&
    INT_TOKEN_RE.test(token) &&
    (value === 0 || value === 1)
  ) {
    return { value: value === 1, error: null };
  }
  const got = token !== null ? token : typeof value;
  return { value: null, error: `${key} 须为 JSON 布尔值（true/false）或 0/1，收到 ${got}` };
}

async function handleCompatSk5Toggle(request, env, key) {
  const { body, tokens } = await readJsonRaw(request);
  // R31-P2-1: envelope guard (Flask _json_body parity). A null body
  // used to fall through to `{}` and silently enqueue the default
  // (fail_open=false) with 202; now it 400s before any default or
  // enqueue, like Flask.
  if (!body) return err("请求体须为 JSON 对象", 400);
  const b = body;
  const { node, error } = await resolveNode(request, env, b);
  if (error) return error;
  const stored = await kvGetJson(env, `sk5cfg:${node.name}`);
  if (!stored || !stored.host || !stored.port) {
    return err("先在 SK5 配置页保存完整 SK5 配置（host/port），再改这个开关", 400);
  }
  const tokenOf = (k) => (tokens ? tokens.get(k) ?? null : null);
  let value;
  if (key in b) {
    const c = coerceToggleBool(b[key], key, tokenOf(key));
    if (c.error) return err(c.error, 400);
    value = c.value;
  } else if (key === "udp_over_tcp" && "enabled" in b) {
    // R12-P2-2 adjudicated: udp-over-tcp falls back to `enabled`
    // (Flask _toggle_value parity). fail-open has NO such fallback.
    // The fallback value goes through the same strict token check.
    const c = coerceToggleBool(b.enabled, "enabled", tokenOf("enabled"));
    if (c.error) return err(c.error, 400);
    value = c.value;
  } else {
    value = false;
  }
  const params = { ...stored, [key]: value };
  await kvPutJson(env, `sk5cfg:${node.name}`, params);
  const cmd = await enqueueCommand(env, node.name, "set_sk5", params);
  return json(
    { ok: true, cmd_id: cmd.id, node: node.name, action: "set_sk5", status: "queued", queued: true },
    202,
  );
}

// ---------- agent 安装包代理（P0-3） ----------
// Worker 本身不含 agent/ 代码，安装包须由源站面板提供：
//   AGENT_BUNDLE_ORIGIN = 服务器模式面板的地址，例如 https://panel.example.com:8443
//   （须能从 Cloudflare 网络访问到；源站是 Flask 面板，
//    提供 /install-agent.sh、/install-agent.sh.sha256、
//    /api/agent/bundle、/api/agent/bundle.sha256）。
// 未配置时返回 503 并明示，不返回 404 误导；bundle 下发前必验 sha256，
// 与源站 bundle.sha256 不符即 502 拒绝下发（fail-closed）。
function bundleOrigin(env) {
  const origin = (env.AGENT_BUNDLE_ORIGIN || "").trim().replace(/\/$/, "");
  return origin || null;
}

function originNotConfigured() {
  return err(
    "未配置 AGENT_BUNDLE_ORIGIN：Cloudflare 模式的 agent 安装包须由源站面板提供，"
    + "wrangler secret put AGENT_BUNDLE_ORIGIN（服务器模式面板地址，如 https://panel.example.com:8443）",
    503,
  );
}

async function fetchFromOrigin(origin, path) {
  let res;
  try {
    res = await fetch(`${origin}${path}`);
  } catch (e) {
    return { ok: false, status: 502, error: `源站 ${origin} 不可达：${e.message || e}` };
  }
  return { ok: res.ok, status: res.status, res };
}

async function handleAgentBundleSha256(request, env) {
  const origin = bundleOrigin(env);
  if (!origin) return originNotConfigured();
  const got = await fetchFromOrigin(origin, "/api/agent/bundle.sha256");
  if (!got.ok) {
    return err(
      `源站未提供 bundle.sha256（HTTP ${got.status}）：拒绝下发未经校验的安装包`,
      502,
    );
  }
  const text = (await got.res.text()).trim();
  const hash = text.split(/\s+/)[0] || "";
  if (!/^[0-9a-f]{64}$/.test(hash)) {
    return err("源站 bundle.sha256 不是 64 位十六进制哈希", 502);
  }
  return new Response(`${text}\n`, {
    status: 200,
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}

async function handleAgentBundle(request, env) {
  const origin = bundleOrigin(env);
  if (!origin) return originNotConfigured();
  const sum = await fetchFromOrigin(origin, "/api/agent/bundle.sha256");
  if (!sum.ok) {
    return err(
      `源站未提供 bundle.sha256（HTTP ${sum.status}）：拒绝下发未经校验的安装包`,
      502,
    );
  }
  const sumText = (await sum.res.text()).trim();
  const want = sumText.split(/\s+/)[0] || "";
  if (!/^[0-9a-f]{64}$/.test(want)) {
    return err("源站 bundle.sha256 不是 64 位十六进制哈希", 502);
  }
  const got = await fetchFromOrigin(origin, "/api/agent/bundle");
  if (!got.ok) {
    return err(`源站 bundle 下载失败（HTTP ${got.status}）`, 502);
  }
  const buf = await got.res.arrayBuffer();
  const actual = await sha256HexBuf(buf);
  if (actual !== want) {
    return err("安装包 sha256 与源站 bundle.sha256 不符：拒绝下发", 502);
  }
  return new Response(buf, {
    status: 200,
    headers: {
      "Content-Type": "application/gzip",
      "Content-Disposition": 'attachment; filename="ovpn-agent-bundle.tar.gz"',
    },
  });
}

// R45-LIVE-2: 源站当前 bundle 哈希（供 agent_code_outdated 比对）。
// R46-L5-1: 源站能连通时每次都重新取；KV 缓存（1 小时）只是源站
// 取不到时的回退，不许用缓存的新鲜度代替源站的现值——否则升级后
// 一小时内新 agent 判过期、旧 agent 判新鲜。源站未配置或取不到时
// 回 null——outdated 即未知，绝不谎报过期。安装包下发仍走
// handleAgentBundle 的逐次校验，不复用此缓存。
async function originBundleSha256(env) {
  const cached = await kvGetJson(env, "origin_bundle_sha256");
  const cachedFresh =
    cached && typeof cached.hash === "string" && typeof cached.at === "number"
    && nowMs() - cached.at < 3600 * 1000 ? cached.hash : null;
  const origin = bundleOrigin(env);
  if (!origin) return cachedFresh;
  const got = await fetchFromOrigin(origin, "/api/agent/bundle.sha256");
  if (!got.ok) return cachedFresh;
  const text = (await got.res.text()).trim();
  const hash = text.split(/\s+/)[0] || "";
  if (!/^[0-9a-f]{64}$/.test(hash)) return null;
  await kvPutJson(env, "origin_bundle_sha256", { hash, at: nowMs() }, { expirationTtl: 3600 });
  return hash;
}

async function handleInstallAgentScript(request, env, shaOnly) {
  const origin = bundleOrigin(env);
  if (!origin) return originNotConfigured();
  const path = shaOnly ? "/install-agent.sh.sha256" : "/install-agent.sh";
  const got = await fetchFromOrigin(origin, path);
  if (!got.ok) {
    return err(`源站未提供 ${path}（HTTP ${got.status}）`, 502);
  }
  const text = await got.res.text();
  if (shaOnly) {
    const hash = text.trim().split(/\s+/)[0] || "";
    if (!/^[0-9a-f]{64}$/.test(hash)) {
      return err("源站 install-agent.sh.sha256 不是 64 位十六进制哈希", 502);
    }
  }
  return new Response(text, {
    status: 200,
    headers: {
      "Content-Type": shaOnly
        ? "text/plain; charset=utf-8"
        : "text/x-shellscript; charset=utf-8",
    },
  });
}

// ---------- 路由 ----------

// 路由分发本体（fetch 包装见文件尾：兜底 500）。
async function handleFetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;

    // agent 安装脚本：无鉴权公开下发（脚本本身不含任何凭据），
    // 经 AGENT_BUNDLE_ORIGIN 源站代理；未配置时 503 明示。
    if (method === "GET" && path === "/install-agent.sh") {
      return handleInstallAgentScript(request, env, false);
    }
    if (method === "GET" && path === "/install-agent.sh.sha256") {
      return handleInstallAgentScript(request, env, true);
    }

    // 静态前端：GET / 及其他静态路径直接交给 Static Assets（panel/templates/index.html 原文件）。
    if (method === "GET" && (path === "/" || !path.startsWith("/api/"))) {
      if (env.ASSETS && typeof env.ASSETS.fetch === "function") {
        return env.ASSETS.fetch(request);
      }
      return err("未配置 Static Assets（wrangler.toml [assets]）", 503);
    }

    // 登录（唯一不需会话的管理接口）。
    if (method === "POST" && path === "/api/login") return handleLogin(request, env);

    // agent 接口：Bearer 节点 token 鉴权，不走管理员会话。
    if (path === "/api/agent/poll" && method === "POST") return handleAgentPoll(request, env);
    if (path === "/api/agent/report" && method === "POST") return handleAgentReport(request, env);
    // agent 安装包：无鉴权公开下发（包里只有代码），经源站代理 + sha256 验后才下发。
    if (path === "/api/agent/bundle" && method === "GET") return handleAgentBundle(request, env);
    if (path === "/api/agent/bundle.sha256" && method === "GET") return handleAgentBundleSha256(request, env);
    if (path.startsWith("/api/agent/")) return err("未知 agent 接口", 404);

    // 其余 /api/* 一律须管理员会话。
    const admin = await requireAdmin(request, env);
    if (!admin) return err("未登录", 401);

    if (method === "POST" && path === "/api/logout") return handleLogout(request, env);
    if (method === "GET" && path === "/api/me") return json({ ok: true, admin: true });
    // 改密：Cloudflare 模式不支持面板内改密（R11-P2-1）。
    // 管理员密码是 Cloudflare secret（env.ADMIN_PASSWORD），面板无处可写；
    // 恒回 501 并明示线下出路，绝不回含混的“未知接口”404。
    // 前端 api() 原样显示 data.error，不用另改前端。
    if (method === "POST" && path === "/api/change-password") {
      return err(
        "Cloudflare 模式不支持面板内改密：管理员密码是 Cloudflare secret，请用 `wrangler secret put ADMIN_PASSWORD` 修改后重新部署",
        501,
      );
    }
    if (method === "GET" && path === "/api/nodes") return handleListNodes(request, env);
    if (method === "POST" && path === "/api/nodes") return handleRegisterNode(request, env);
    const nodeActionMatch = path.match(/^\/api\/nodes\/([A-Za-z0-9_-]+)\/(rotate|install)$/);
    if (method === "POST" && nodeActionMatch) {
      if (nodeActionMatch[2] === "rotate") return handleRotateNode(request, env, nodeActionMatch[1]);
      return handleNodeInstall(request, env, nodeActionMatch[1]);
    }
    const nodeMatch = path.match(/^\/api\/nodes\/([A-Za-z0-9_-]+)$/);
    if (method === "DELETE" && nodeMatch) return handleRevokeNode(request, env, nodeMatch[1]);
    if (method === "POST" && path === "/api/cmd") return handleCreateCmd(request, env);
    const cmdMatch = path.match(/^\/api\/cmd\/([A-Za-z0-9-]+)$/);
    if (method === "GET" && cmdMatch) return handleGetCmd(request, env, cmdMatch[1]);

    // 兼容层：单节点 UI 的旧接口（见文件头说明）。
    if (method === "GET" && path === "/api/status") return handleCompatStatus(request, env);
    if (method === "GET" && path === "/api/openvpn/public-ip") return handlePublicIp(request, env);
    if (method === "POST" && path === "/api/openvpn/server") {
      return handleCompatEnqueue(request, env, "create_server", (b) => {
        const p = {
          port: b.port,
          proto: b.proto,
        };
        // R45-L7-2: 对外地址随命令发给 agent（README 观察-1 的补发方案）；
        // 键在场即设定/清空（空串=清除已存值），缺键即保持旧值。
        if (typeof b.server_ip === "string") p.server_ip = b.server_ip.trim();
        return p;
      }, true, validateCreateServer);
    }
    if (method === "POST" && path === "/api/openvpn/start") {
      return handleCompatEnqueue(request, env, "start_openvpn", () => ({}));
    }
    if (method === "POST" && path === "/api/openvpn/stop") {
      return handleCompatEnqueue(request, env, "stop_openvpn", () => ({}));
    }
    if (method === "POST" && path === "/api/openvpn/restart") {
      return handleCompatEnqueue(request, env, "restart_openvpn", () => ({}));
    }
    if (method === "POST" && path === "/api/openvpn/init-pki") {
      return handleCompatInitPki(request, env);
    }
    if (method === "GET" && path === "/api/openvpn/users") return handleCompatUsers(request, env);
    if (method === "POST" && path === "/api/openvpn/users") {
      return handleCompatEnqueue(request, env, "create_user", async (b, node) => {
        const p = { name: b.name };
        // R45-L7-2：建服务时存下的对外地址随建用户命令补发给 agent，
        // agent 的 action_create_user 原样把它写进 .ovpn remote（core
        // create_user 的 server_ip 参数）；未存过即不传，agent 自行探测。
        const cfg = await kvGetJson(env, `servercfg:${node.name}`);
        if (cfg && typeof cfg.server_ip === "string" && cfg.server_ip) {
          p.server_ip = cfg.server_ip;
        }
        return p;
      }, true, validateCreateUser);
    }
    const revokeMatch = path.match(/^\/api\/openvpn\/users\/([^/]+)$/);
    if (method === "DELETE" && revokeMatch) {
      return handleCompatEnqueue(request, env, "revoke_user", () => ({
        name: decodeURIComponent(revokeMatch[1]),
      }));
    }
    const ovpnMatch = path.match(/^\/api\/openvpn\/users\/([^/]+)\/ovpn$/);
    if (method === "GET" && ovpnMatch) {
      return handleCompatOvpnDownload(request, env, decodeURIComponent(ovpnMatch[1]));
    }
    if (method === "GET" && path === "/api/sk5") return handleCompatSk5Get(request, env);
    if (method === "POST" && path === "/api/sk5") {
      return handleCompatSk5Save(request, env);
    }
    if (method === "POST" && path === "/api/sk5/test") {
      return handleCompatEnqueue(request, env, "test_sk5", () => ({}));
    }
    if (method === "POST" && path === "/api/sk5/enable") {
      return handleCompatEnqueue(request, env, "enable_sk5", () => ({}));
    }
    if (method === "POST" && path === "/api/sk5/disable") {
      return handleCompatEnqueue(request, env, "disable_sk5", () => ({}));
    }
    if (method === "POST" && path === "/api/sk5/fail-open") {
      return handleCompatSk5Toggle(request, env, "fail_open");
    }
    if (method === "POST" && path === "/api/sk5/udp-over-tcp") {
      return handleCompatSk5Toggle(request, env, "udp_over_tcp");
    }

    if (path.startsWith("/api/")) return err("未知接口", 404);
    return err("未找到", 404);
}

export default {
  // R12-P2-3：兜底——任何未捕获异常都回 500 JSON，永不裸抛（生产上
  // 即无响应；listNodes 之类已逐项加固，此处是最后一道防线）。
  async fetch(request, env, ctx) {
    try {
      return await handleFetch(request, env, ctx);
    } catch (e) {
      console.error("worker unhandled error:", e);
      return err("内部错误", 500);
    }
  },
};

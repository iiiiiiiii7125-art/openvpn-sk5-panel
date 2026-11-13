# OpenVPN + SK5 面板 — Cloudflare 部署

> **未验（P0-1）：Cloudflare 模式从未在真实部署上验证。** `wrangler deploy --dry-run` 通过不等于部署可用；`wrangler.toml` 里的 KV id 仍为占位符。

控制面跑在 Cloudflare Workers 上，执行面是中转机上的 agent（agent 路另行实现）。
面板只管节点注册、命令下发、结果回执；真正装 OpenVPN、切 SK5 的活都在 agent 那头做。

```
浏览器 -> Workers 面板 (ovpn-sk5-panel) -> KV 队列
                                              |
中转机 agent 每 5 秒 POST /api/agent/poll 拉命令 -> 执行 -> POST /api/agent/report 回结果
```

## 文件

| 文件 | 说明 |
|---|---|
| `wrangler.toml` | Workers 配置：`name = "ovpn-sk5-panel"`，`compatibility_date = "2026-01-01"`，KV 绑定 `PANEL_KV`，前端为 Static Assets（`../panel/templates`，即 `panel/templates/index.html` 原文件，不复制） |
| `src/index.js` | Worker 本体，无依赖，ES Module：控制面路由 + 单节点 UI 兼容层 |
| `server-mode.md` | 服务器部署与 Cloudflare 部署的对照表 |

## 部署步骤

```bash
cd cloudflare
npm install -g wrangler        # 或 npx wrangler，下同
wrangler login

# 1. 建 KV 命名空间（生产 + 预览各一个）
wrangler kv namespace create PANEL_KV
wrangler kv namespace create PANEL_KV --preview
# 把两条命令输出的 id / preview_id 填进 wrangler.toml 对应位置
# （填之前 wrangler deploy 会报错，这是故意的：不许把假 id 提交上去）

# 2. 设管理员密码（只进 secret，不进文件、不进 git）
wrangler secret put ADMIN_PASSWORD

# 2b. （Cloudflare 模式要给中转机装 agent 才需要）设安装包源站：
# 服务器模式面板的地址，例如 https://panel.example.com:8443
wrangler secret put AGENT_BUNDLE_ORIGIN

# 3. 部署
wrangler deploy
# 成功后得到 https://ovpn-sk5-panel.<你的子域名>.workers.dev
```

## 验证

```bash
PANEL=https://ovpn-sk5-panel.<你的子域名>.workers.dev

# 未登录一律 401
curl -s -o /dev/null -w "%{http_code}\n" $PANEL/api/nodes
# -> 401

# 登录（拿到 HttpOnly 会话 cookie，存 cookie.txt）
curl -s -c cookie.txt -X POST $PANEL/api/login \
  -H 'Content-Type: application/json' \
  -d '{"password":"你设的密码"}'
# -> {"ok":true,"admin":true}

# 登录后应为 200
curl -s -b cookie.txt $PANEL/api/nodes
# -> {"ok":true,"nodes":[]}

# 注册节点：token 只返回一次，当场记下，交给中转机 agent 用
curl -s -b cookie.txt -X POST $PANEL/api/nodes \
  -H 'Content-Type: application/json' \
  -d '{"name":"hk-transit","panel_url":""}'
# -> {"ok":true,"node":{"name":"hk-transit",...},"token":"..."}

# 下发命令并查结果（agent 每 5 秒 poll 一次）
curl -s -b cookie.txt -X POST $PANEL/api/cmd \
  -H 'Content-Type: application/json' \
  -d '{"node":"hk-transit","action":"get_status","params":{}}'
# -> {"ok":true,"cmd_id":"...","status":"queued"}（202）
curl -s -b cookie.txt $PANEL/api/cmd/<cmd_id>
# -> status: queued -> sent -> done/failed，done 时带 result
```

## 验活注意：Workers 版本按 POP 慢速传播

2026-11-10 教训：部署 API 显示 100% 不等于各 POP 都生效——当时本机出口（ORD/EWR）近 40 分钟仍回旧版，另一出口（ATL）已是新版。

所以判定“部署生效”之前不要只看 `wrangler deploy` 的成功回显，必须换第二出口多点核：

1. 在本机 `curl $PANEL/api/nodes` 应为 401（未登录），且响应里可加版本标识核对（见下）。
2. 换一个出口再测一次（手机流量、另一台 VPS、或 Simular Box 的 shell 里 curl），两边都拿到新版行为才算生效。
3. 若一边新一边旧，等传播完成再测，不要反复重部署——重部署不会加速 POP 滚动。

建议每次发版先在 Worker 里确认新旧行为可区分（例如 `GET /api/me` 未登录返回的错误文案或节点列表字段有变化），再按上面两步核。

## 接口契约（agent 路按此实现）

### agent → 面板

- `POST /api/agent/poll`，头 `Authorization: Bearer <node_token>`，空 body。
  返回 `{ok:true, node, commands:[{id, action, params}], poll_interval_s:5}`。
  命令交出即记 `sent` 态（`sent:<节点>` 留副本）；agent 须执行并回执。
  下次 poll 时超过 120 秒未回执的：幂等/只读动作（`get_status`、`test_sk5`、
  `enable_sk5`、`disable_sk5`、`start/stop/restart_openvpn`）自动回队重发；
  非幂等动作（`create_user`、`revoke_user`、`init_pki`、`create_server`、
  `set_sk5`、`install_prereqs`）标 `failed`，由管理员确认 agent 状态后手动重发，
  不自动重发避免重复执行。`GET /api/cmd/:id` 可见状态与 `timeout_hint`。
- `POST /api/agent/report`，Bearer 鉴权，body `{cmd_id, ok, result?, error?}`。
  无 `cmd_id` 时视为纯心跳：body 可带 `status_snapshot`，只更新状态快照与 `last_seen`。
  `cmd_id` 与 `id` 两个字段都接受（agent 发哪个都认）。

### 面板 → agent（动作白名单，共 13 个，非法一律 400）

`install_prereqs, init_pki, create_server, start_openvpn, stop_openvpn, restart_openvpn, create_user,`
`revoke_user, set_sk5, test_sk5, enable_sk5, disable_sk5, get_status`

### get_status 快照形状（agent 的 `result` 按此返回，面板据此渲染）

agent 的 `action_get_status` 返回扁平形（见 `agent/agent.py`）：

```json
{
  "openvpn": {"running": true, "unit_active": true, "pid": 1234, "clients": [{"name": "alice"}], "error": null},
  "users": [{"name": "alice", "status": "valid", "online": true}],
  "sk5": {"enabled": true, "host": "proxy.iproyal.net", "port": 1001, "fail_open": false, "udp_over_tcp": false, "singbox_running": true, "policy_routing_active": true},
  // 端口待确认：示例写 1001 只是默认值；若商家给的是 9000 请填 9000 并回报
  //（1001/9000 哪个是 SOCKS5 口尚未确认）。
  "egress_ip": "1.2.3.4"
}
```

Worker 收到后归一化成面板 `/api/status` 的形状（与 Flask 一致）：`egress_ip` →
`egress.ip`（`via_sk5` 唯一判据是实测的 `policy_routing_active`：策略在位才复用
探针 IP，策略缺失时 `via_sk5=false`、`ip=null` 并给出错误文案；与 Flask 同款），
`online_users` = `clients` 列表长度，
`proto/port/subnet/dns` 按最近一次建服务成功的配置补（`servercfg:<节点>`，
子网/DNS 是 core 固定值 `10.8.0.0/24` / `1.1.1.1`）。

- `set_sk5` 是**部分合并**：agent 的 `action_set_sk5`
  （`agent/agent.py`）只改传来的字段，缺失字段保留已存值，host/port
  均可缺；`sk5_manager.set_sk5` 同款语义（密码缺失/空串保留已有密码，只
  有显式非空密码才覆盖，清密码须传 `clear_password=true`，见
  `docs/security.md`）。面板“故障回直连 / UDP over TCP”两个开关走
  `handleCompatSk5Toggle`：下发前仍先读 `sk5cfg:<节点>` 把开关并进已存全
  量配置再发 `set_sk5`（纵深防御）；无已存配置时明确 400，绝不发缺字段
  的命令。
- 保存 SK5 时密码框留空 = 不覆盖已存密码（Worker 读 `sk5cfg` 补旧密码再下发）；
  绝不把空串发给 agent 覆盖掉已存密码。
- `create_user` 成功时 `result` 须带 `ovpn`（完整 `.ovpn` 文本），面板存入 KV 供下载；
  `test_sk5` 的 `result` 是原始测试结果
  `{tcp_ok, udp_ok, egress_ip, latency_ms, udp_mode, udp_note, host, port}`，
  TCP 与 UDP 分开报，不许把 TCP 通冒充 UDP 通。前端收到后归一化成
  `{tcp:{ok,latency_ms,egress_ip}, udp:{ok,mode,note}}` 再分开展示。

### KV 键（`PANEL_KV`）

| 前缀 | 内容 |
|---|---|
| `node:<name>` | 节点记录。token 只存 SHA-256 哈希，明文不落 KV |
| `queue:<name>` | 待执行命令 id 队列（FIFO） |
| `sent:<name>` | 已下发未回执的命令 `[{id, action, sent_at}]`（120 秒超时处理用） |
| `cmd:<id>` | 命令记录，7 天过期（`expirationTtl`）。`params` 可能含 SK5 密码，见安全说明 |
| `status:<name>` | 最近状态快照（密码字段已剔除） |
| `servercfg:<name>` | 最近一次建服务成功的配置 `{proto, port, subnet, dns}`（快照补字段用） |
| `sk5cfg:<name>` | 最近一次保存的 SK5 全量配置（含密码；开关下发与密码保留用） |
| `sk5test:<name>` | 最近一次 `test_sk5` 的原始结果（UDP 保存守卫用） |
| `ovpn:<name>:<user>` | `.ovpn` 文本 |
| `session:<id>` | 管理员会话，24 小时过期 |
| `loginfail:<ip>` | 登录失败计数 `{failures, locked_until}`（限流用） |

## 单节点 UI 兼容层

`panel/templates/index.html` 直接调 `/api/status`、`/api/openvpn/*`、`/api/sk5/*`，
另有“节点”页调 `/api/nodes`、`/api/cmd/:id`。在 Cloudflare 模式下 Worker 把
旧接口翻译成命令队列 + KV 状态缓存：

- POST 类（建服务、启停、新建/吊销用户、保存/测试/启用/停用 SK5）：下发命令，返回 **202**
  `{ok:true, cmd_id, queued:true}`。**202 只表示“已排队”，不是成功。**
  前端按 `cmd_id` 轮询 `GET /api/cmd/:id`（每 2 秒，最多 120 秒），等到
  `done` 才报成功、`failed` 报 agent 的错误、超时报“已下发超过 120 秒未回执”。
  建用户成功后前端用回执里的 `ovpn` 文本直接下载（Flask 直连模式则用返回的
  `ovpn_url`）；SK5 测试只有拿到 `test` 结果才显示“测试完成”，空结果一律报
  “测试未返回结果”，绝不假报。
- GET 类（`/api/status`、用户列表、SK5 配置）：读节点最近上报的快照，带 `stale` / `age_s`
  （超过 60 秒未上报即 `stale:true`，前端会注明“状态为缓存快照”）；节点尚未上报过时给空状态 + 提示。
- `.ovpn` 下载：读 `ovpn:<节点>:<用户>`，未生成时 404 并提示等 agent 回执。
- 节点选择：单节点自动用唯一节点；多节点时前端“节点”页有下拉框选当前节点，
  兼容接口自动带 `?node=<名>`，也可手动用 `X-Node` 头指定；不指定时 400 并返回节点名列表。
- 节点页（`/api/nodes`）：注册节点（token 与安装命令只返回一次）、节点列表
  （在线/离线按 `last_seen` 30 秒内判定、出口 IP、SK5 状态）、轮换 token、
  吊销节点、复制安装命令；命令记录（本浏览器 localStorage 存最近 30 条，
  可按 `cmd_id` 重查状态）。

## agent 安装包（Cloudflare 模式）

Worker 本身不含 agent/ 代码，安装包须由源站面板提供。部署前设置：

```bash
wrangler secret put AGENT_BUNDLE_ORIGIN
# 填服务器模式面板的地址，例如 https://panel.example.com:8443
# （须能从 Cloudflare 网络访问到；源站是 Flask 面板，提供
#  /install-agent.sh、/install-agent.sh.sha256、
#  /api/agent/bundle、/api/agent/bundle.sha256）
```

Worker 收到 `GET /install-agent.sh`、`/install-agent.sh.sha256`、
`/api/agent/bundle`、`/api/agent/bundle.sha256` 时代理到源站；其中 bundle
下发前必拿源站的 `bundle.sha256` 验包，哈希不符即 502 拒绝下发
（fail-closed）。未配置 `AGENT_BUNDLE_ORIGIN` 时这四个接口返回 503 并明示，
不返回 404 误导。注册/轮换节点时返回的安装命令是 fail-closed 形：
先取 `install-agent.sh`，再取 `.sha256`——`.sha256` 必须取到且 `sha256sum -c`
通过才执行，缺失或验不过即停（fail-closed）；bundle 下发仍是 sha256 fail-closed。

## 服务器部署模式

同一套前端 + `panel/app.py`（Flask）直接跑在服务器上，不经过 Cloudflare。
设 `PANEL_MODE=server`，agent 的 `poll` / `report` 地址改指服务器面板
（例如 `https://<服务器 IP>:8443/api/agent/poll`），命令动作白名单与上面完全一致。
两种模式的对照见 `server-mode.md`。

`panel/app.py` 已实现 `/api/agent/poll`、`/api/agent/report`、`/api/nodes`、
`/api/cmd` 这组 agent 侧接口（命令队列存 `agent_queue.json`（0600）+
SQLite `nodes` 表，与 KV 键一一对应），服务器模式可直接接远程 agent；
同时保留单机直连接口（直接调本机 `core/`、`egress/`），两种用法共存。
`set_sk5` 在 Flask 侧同样是部分合并（`panel/app.py` → `sk5_manager.set_sk5`，缺字段保留已存值），与 Worker 一致。

## 与 FLMX 的对齐（用户 2026-11-12 07:54 令）

入站的安装部署方式、面板 UI、含安全在内，全部参考 FLMX 来做：

- **安装部署**：面板为控制面、agent 装在中转机上执行安装部署——面板只下发命令，
  OpenVPN / sing-box / SK5 的安装与控制都在 agent 侧完成，不由 Worker 直接操作目标机器。
- **面板 UI**：Cloudflare 与服务器两种模式共用同一份前端（`panel/templates/index.html`），
  与 FLMX 同款思路：一个面板、两种托管，界面与操作路径一致。
- **安全**：管理员会话（HttpOnly cookie）+ 节点 token（Bearer，KV 只存哈希）双层鉴权，
  密码只进 `wrangler secret` / 服务端本地文件，不进代码与配置；管理接口未登录一律 401。

## 安全说明

- `ADMIN_PASSWORD` 只放 `wrangler secret`，绝不写进 `wrangler.toml`、代码或 git。
- 登录限流与 Flask 同口径：同一 IP（`CF-Connecting-IP`）5 分钟内 5 次失败即锁
  15 分钟，锁期内 429 + `Retry-After`；成功登录即清零。
- 节点 token 只在注册/轮换时返回一次；轮换用 `POST /api/nodes/<名>/rotate`
  （旧 token 立即作废），吊销用 `DELETE /api/nodes/<名>`（旧 token 立即作废，
  排队/已下发的命令一律标失败）。token 泄露后任何人可冒充该节点拉命令、伪造回执。
- 命令记录 `cmd:<id>` 的 `params` 可能含 SK5 密码，KV 里明文存放、7 天过期；
  `.ovpn` 文本含用户私钥，同样明文存 KV。这是个人自用面板的取舍，不是 E2E 加密方案，
  不要把这套面板的 KV 命名空间共享给他人。`GET /api/cmd/:id` 返回时 `params`
  里的密码已脱敏（Flask 侧同款）。
- 管理员会话 cookie 为 HttpOnly、`SameSite=Lax`，https 下自动加 `Secure`；
  `wrangler dev` 的 http 本地调试下不加 `Secure`，生产不受影响。
- 密码比对用 SHA-256 哈希后按字节比对，不直接 `==`，避免时序泄露。

## 未解决的风险

- 本路只在沙箱里做了 `node --check` 与带 mock KV 的全路由测试（56 格去重后；58 次执行，W7/W8 的畸形体与 lockout 探针 L1 的 4 体重合 2 体），
  覆盖登录限流、节点轮换/吊销、快照归一化、sent 超时重发/标失败、
  bundle 代理验签、UDP 保存守卫、畸形容器归一化（queue/sent 非数组按空
  处理，R19-P2-1）、畸形命令 sweep 与孤儿回收（R18-P2-2）、.ovpn 下载
  吊销／过期守卫（快照里 revoked／expired 一律 403，R19-P2-2），
  **没有跑过真实 `wrangler deploy`**（沙箱未装 wrangler、无 Cloudflare 账号登录态），
  部署与 POP 传播须在有账号的机器上按上面步骤实测。
- Cloudflare 模式的 agent 安装依赖 `AGENT_BUNDLE_ORIGIN` 源站面板：
  源站须提供 `/install-agent.sh(.sha256)` 与 `/api/agent/bundle(.sha256)`；
  源站不可达或不提供时安装走不通（503/502 明示）。
- `sk5cfg:<节点>` 与 `cmd:<id>` 的 `params` 里含 SK5 明文密码（KV 7 天过期），
  与命令记录同款取舍，见安全说明。

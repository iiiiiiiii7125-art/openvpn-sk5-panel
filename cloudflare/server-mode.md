# 服务器部署 vs Cloudflare 部署 — 对照表

同一套产品，两种托管方式。前端是同一份 `panel/templates/index.html`，
agent 是同一套（动作白名单、poll/report 契约完全一致），变的只是控制面跑在哪、
数据存在哪。

| 维度 | Cloudflare 模式 | 服务器模式 |
|---|---|---|
| 控制面跑在哪 | Cloudflare Workers（`ovpn-sk5-panel`），全球 POP 就近接入 | 中转机本机或另一台服务器上的 Flask（`panel/app.py`），`PANEL_MODE=server` |
| 前端 | Workers Static Assets 直出 `panel/templates/index.html` 原文件 | Flask `GET /` 渲染同一文件 |
| 面板地址 | `https://ovpn-sk5-panel.<子域名>.workers.dev` | `https://<服务器 IP>:8443`（自签证书；agent 须用 `--ca-cert` 或安装时 TOFU 钉死面板证书，见 README） |
| agent 的 poll/report 地址 | `https://ovpn-sk5-panel.<子域名>.workers.dev/api/agent/*` | `https://<服务器 IP>:8443/api/agent/*` |
| 命令队列 / 结果存储 | Cloudflare KV（`PANEL_KV`，键见 README） | 本地 `agent_queue.json`（0600）+ SQLite `nodes` 表，与 KV 键一一对应 |
| 管理员密码 | `wrangler secret put ADMIN_PASSWORD` | 首次启动生成的随机密码（`panel/app.py` 逻辑，写 `/etc/openvpn-sk5-panel/admin.pass`，600） |
| 节点注册 | `POST /api/nodes`，token 只返回一次，附 fail-closed 安装命令 | 同接口（Flask 版，`panel/app.py` 已实现） |
| 节点轮换 / 吊销 | `POST /api/nodes/<名>/rotate`、`DELETE /api/nodes/<名>`（旧 token 立即作废） | 同接口（Flask 版，`panel/app.py` 已实现） |
| 安装命令入口 | `POST /api/nodes/<名>/install`，返回 fail-closed 命令模板 | 仅 Worker 有该接口；Flask 侧由前端 `buildInstallCommand` 就地拼装（见下） |
| 动作白名单 | 13 个（见 README），非法 400 | 相同 13 个 |
| `set_sk5` 语义 | 部分合并（agent 缺字段保留已存值，host/port 可缺；Worker 开关路由下发前先读 sk5cfg 补齐再发，无已存配置时 400） | 相同 |
| `get_status` 快照形状 | `{openvpn, egress, sk5, users}`（Worker 归一化后，与 Flask 一致） | 相同 |
| 命令 sent 态 | 超时 120 秒：幂等动作自动回队重发，非幂等标失败手动重发（`sent_at` 缺失／不可解析时直接标 `failed`，不重发，R13-P2-1） | **两端分歧（不相同）**：Worker 仅 7 个幂等动作可重投，非幂等首超时即标 `failed`；Flask `_requeue_stale_sent` 不分动作全重投（含 `create_user`／`init_pki`，R5 已查证、定性非 bug）。上限两端一致，均为 `SENT_MAX_RETRIES = 3`。 |
| 登录限流 | 同 IP 5 分钟 5 次失败锁 15 分钟，429 + Retry-After | 相同 |
| 多节点 | 支持（前端“节点”页下拉选当前节点；`body.node` / `?node=` / `X-Node` 指定，优先级 body.node > `?node=` > `X-Node`，与 Flask 一致） | 相同（前端共用） |
| 离线可用性 | 面板本身不依赖任何一台中转机在线；某节点离线只影响该节点 | 面板跑在哪台机，哪台机关机面板就没了 |
| 延迟 | 多一跳 Workers + KV，命令下发到执行最多约 5 秒（poll 间隔） | 本机直连，命令立即执行；远程 agent 同样 5 秒 poll 间隔 |
| 版本传播 | Workers 按 POP 慢速滚动：部署 API 100% ≠ 各 POP 生效，须换第二出口多点核（2026-11-10 教训，见 README） | 改完重启服务即生效，无传播问题 |
| 成本 | Workers 免费额度内一般够用（KV 读写量小） | 服务器本身的成本，无额外费用 |
| 安全边界 | SK5 密码 / `.ovpn` 私钥明文存 KV（7 天过期）；token 哈希存储 | 同样明文存本地盘；面板端口须防火墙只放行可信 IP 或套 HTTPS 反代 |

## 怎么选

- 只要一个中转机、图省事：**服务器模式**——装完即用，无 Cloudflare 账号、无传播等待。
- 多台中转机、或面板不能跟着某一台机走：**Cloudflare 模式**——控制面常驻云端，
  各机 agent 只管每 5 秒来拉命令；某台机挂了不影响面板和其他节点。
- 两者可以混用：Cloudflare 做控制面，服务器上的 Flask 只跑 agent 侧执行，
  但不要两边同时对同一节点下发命令（队列各管各的，会打架）。
- Cloudflare 模式装 agent 须配 `AGENT_BUNDLE_ORIGIN`（见 README“agent 安装包”一节）：
  Worker 把安装包请求代理到服务器模式面板，验 sha256 后才下发；不配则安装接口 503。

## 现状

- Cloudflare 模式：Worker 已按本目录实现（`src/index.js`），待真实 `wrangler deploy` 验证。
- 服务器模式：`panel/app.py` 已实现 `/api/agent/poll`、`/api/agent/report`、
  `/api/nodes`、`/api/cmd`（命令队列
  `agent_queue.json` + SQLite `nodes` 表），服务器面板可直接接远程 agent；
  安装命令由前端 `buildInstallCommand` 就地拼装（Flask 侧无
  `POST /api/nodes/<名>/install` 接口，该接口仅 Worker 有）；
  单机直连接口（直接调本机 `core/`、`egress/`）同时保留，两种用法共存。

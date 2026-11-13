# 全量审计 R1 — openvpn-sk5-panel

> 审计人：独立审计路（未参与任何建设路）。日期：2026-11-12。
> 审计对象：`~/workspace/openvpn-sk5-panel/` 全部文件（38 个文件，8089 行）。
> 方法：全量枚举 → 接口对账 → 链路实证（Flask test-client / node + mock KV / 假 PKI·假 SK5 跑公开函数）→ 安全专项 → 安装与文档对账。测试一律在 `/tmp/audit-copy` 副本上跑，未动项目原文件、未动 `/etc`、未动任何真机。
> 证据等级：每条 finding 标注 `实证`（测试脚本跑出）或 `代码确认`（通读代码 + 静态核对，未能在沙箱跑出，多因缺二进制）；`代码确认`项已在文中写明未复现的原因。

## 一句话裁决

**不能交付。先修 5 条 P0，再修 P1 才能进入真机验证；Cloudflare 模式在 P0 修完前不具备"面板可用"的宣称条件。**

| 严重度 | 数量 | 说明 |
|---|---|---|
| P0 阻断 | 5 | 交付前必须修 |
| P1 必须修 | 15 | 修完才能进真机验证 / 发版 |
| P2 建议 | 13 | 同批修最好，至少登记进门禁 |
| 合计 | 33 | |

## 审计范围与实证结果总览

| 文件 | 行数 | 审计方式 | 结果 |
|---|---|---|---|
| panel/app.py | 1272 | 全文通读 + Flask test-client 全路由 | 见 P0-4/P0-5、P1-1/P1-6/P1-7、P2-1/P2-5/P2-7 |
| panel/templates/index.html | 728 | 全文通读 + 每个 API 调用逐一对账 | 见 P0-1、P1-2、P1-5 |
| cloudflare/src/index.js | 612 | 全文通读 + node + mock KV 全路由 | 见 P0-1/P0-2/P0-3、P1-3/P1-4/P1-5 |
| agent/agent.py | 750 | 全文通读 + execute_command 实测 + --once 实测 | 见 P0-2、P1-6/P1-10/P1-13、P2-2/P2-3/P2-9 |
| core/openvpn_manager.py | 637 | 全文通读 + 假 PKI 实测 | 见 P1-10/P1-11/P1-13、P2-15 |
| core/easyrsa.sh | 112 | 全文通读 | 无单独 finding（见 P1-10 证据说明） |
| egress/sk5_manager.py | 684 | 全文通读 + 假 SK5 实测 | 见 P0-4、P1-1/P1-8、P2-12 |
| egress/policy-routing.sh | 176 | 全文通读 | 见 P1-9 |
| egress/test-egress.sh | 121 | 通读 | 见已证伪 R-1 |
| install.sh | 580 | 全文通读 | 见 P1-9/P1-11、P2-6/P2-7/P2-8 |
| agent/install-agent.sh | 175 | 通读 | 见 P0-3、P2-13 |
| verify.sh / verify-integration.sh | 559 / 199 | 通读 + 结构核对 | 无单独 finding（见 P2-8） |
| systemd/*.service、wrangler.toml、模板 ×3、README ×6、docs ×3 | — | 逐项对账 | 见 P1-9/P1-14/P1-15、P2-6/P2-12/P2-13 |
| panel/data/secret.key | 32 字节 | 实测比对 | 见 P0-5 |

实证测试（均在 `/tmp/audit-tests/`，副本 `/tmp/audit-copy`）：

| 测试 | 结果 |
|---|---|
| `bash -n` 全部 7 个 shell 脚本 | 全过 |
| `python3 -m py_compile` 全部 4 个 Python 文件 | 全过 |
| `node --check cloudflare/src/index.js` | 过 |
| sing-box 模板占位符替换后 JSON 校验 | 过（outbounds `bought-sk5/direct/block`，final `bought-sk5`） |
| Flask test-client 全路由（38 项） | 38/39；唯一"失败"是我方延迟断言写法问题，改用静默 SOCKS 重测后证实（见 P1-1：单次探针 10.0s，`/api/status` 20.0s） |
| Worker + mock KV 全路由（21 项） | 21/21 |
| agent/core 公开函数（14 项） | 11/14；其余 3 项逐一复核见"已证伪 / 已修正"节（F14 换精确断言后成立；curl argv 泄露被证伪；UoT 文件权限按 umask 重述） |
| 枚举：TODO/FIXME/XXX/NotImplemented | 零命中 |
| 枚举：`shell=True` | 零命中；subprocess 全用列表参数 |
| 枚举：空函数 / `pass` 占位 | 零命中；全部 `pass` 皆为合法的异常吞掉（清理类） |

---

## P0 阻断（5 条）

### P0-1 — Cloudflare 模式：前端把 202 排队当成功报，建用户无下载、SK5 测试空结果却显示"测试完成"

- 文件：`cloudflare/src/index.js:442-446, 465-473, 575-581`；`panel/templates/index.html:465-471, 658-668, 690-712`
- 复现（Worker + mock KV，实证）：
  - `POST /api/openvpn/users {"name":"alice"}` → `202 {"ok":true,"cmd_id":"…","status":"queued","queued":true}`，响应里**没有 `ovpn_url`**。前端 `index.html:666` 只在 `d.ovpn_url` 存在时才给下载链接，Cloudflare 模式下建完用户无任何下载入口（须等 agent 回执后再从用户列表点下载）。
  - `POST /api/sk5/test` → `202`，响应里**没有 `test` 字段**。前端 `index.html:696` 取 `d.test || {}` 得 `{}`，TCP/UDP 两格显示"—"，`testResult` 显示 `{}`，随后 `index.html:712` 仍 `showMsg("sk5Msg", "测试完成", true)`——**用户看到"测试完成"，实际什么都没测**。
  - 根因：前端 `api()`（`index.html:471`）只认 `!res.ok || data.ok === false` 为失败；202 是 2xx 且 `ok:true`，一律当成功。Worker 兼容层所有 POST 类接口都返回 202，Flask 全部返回 200/201——两套面板同一前端，成功语义不一致，前端未区分。
- 影响：Cloudflare 面板上每一次写操作（建服务、启停、建用户、保存/测试/启用 SK5）都会在命令尚未执行、甚至尚未下发时就向用户报成功；测试功能在 Cloudflare 模式下是假的。

### P0-2 — Worker 的 fail-open / udp-over-tcp 兼容路由必败：单字段 set_sk5，agent 强制要求 host+port

- 文件：`cloudflare/src/index.js:591-599`；`agent/agent.py:546-548`；`cloudflare/README.md:115-117`
- 复现（实证，两端闭环）：
  - Worker 侧：`POST /api/sk5/fail-open {"fail_open":true}` → 202 入队，KV 里存下的命令参数实测为 `{"fail_open":true}`（无 host、无 port）。
  - agent 侧：对该命令调 `execute_command`，实测返回 `(False, None, "ValueError: missing required param: host")`。`udp_over_tcp` 路由同理。
  - README 称"set_sk5 按部分合并语义：agent 只改传来的字段"——**假的**。`action_set_sk5` 首行就是 `_need_params(params, "host", "port")`，且 `sk5_manager.set_sk5` 是全量覆盖、无合并逻辑。
- 影响：面板上"故障回直连""UDP over TCP"两个开关在 Cloudflare 模式下点下去必失败，且失败只出现在 agent 回执里，前端早已报成功（与 P0-1 叠加，用户无从发现）。

### P0-3 — Cloudflare 模式无法安装 agent：Worker 没有 /api/agent/bundle 与 /install-agent.sh

- 文件：`cloudflare/src/index.js:508-612`（路由表无此二路由）；`agent/install-agent.sh:99-124`
- 复现（实证）：Worker mock KV 下 `GET /api/agent/bundle` → 404；`GET /install-agent.sh` → 404（即使配了 Static Assets 也 404，因为 `agent/` 不在 `wrangler.toml [assets] directory = "../panel/templates"` 内）。
- 影响：README 部署方式二给出的装机命令 `curl -fsSL https://<面板>/install-agent.sh | bash -s -- --panel-url … --token …` 在 Cloudflare 模式下第一步就 404；`install-agent.sh` 还要先取 `$PANEL_URL/api/agent/bundle.sha256` 做 fail-closed 校验，同样 404。**Cloudflare 模式没有可走的 agent 安装路径**，"面板放 Cloudflare、中转机只装 agent"的部署方式二目前不可落地。

### P0-4 — SK5 密码会被保存操作清空（Flask 与 Worker 两路都中招）

- 文件：`panel/app.py:799-807`；`panel/templates/index.html:675-682`；`egress/sk5_manager.py:478-494`；`cloudflare/src/index.js:575-581`
- 复现（Flask test-client，实证）：
  - `POST /api/sk5 {host, port, username:"u1", password:"SECRET123", enabled:false}` → 200；`GET /api/sk5` → `has_password: true`。
  - 再 `POST /api/sk5 {host, port, username:"u1", password:"", enabled:false}`（模拟前端密码框留空）→ 200；`GET /api/sk5` → **`has_password: false`**。密码已被空串覆盖。
  - 前端 `sk5Body()` 恒发 `password` 字段（未重填即空串）；Flask `sk5_save` 无条件传给 `set_sk5` 存空密码；`set_sk5` 无"空即保留"逻辑。Worker 兼容层注释称"前端密码框留空即不覆盖"，但两端代码都没实现；Worker 实测：保存空密码原样进队发给 agent。
  - 二次伤害：`_render_singbox_config` 遇空密码会把 `password` 键整个删掉（按"无认证商家"处理），于是带认证的 SK5 在"只改个开关"的保存后变成无认证拨号，失败时只报认证错，不报"密码丢了"。
- 影响：用户在面板上改一次 fail-open 开关或启停一次 SK5，就会悄悄丢掉 SK5 密码，出口链随即断掉，且无任何提示指向密码丢失。

### P0-5 — panel/data/secret.key（32 字节随机）随项目树发货，全部署共用同一 Flask 会话密钥

- 文件：`panel/data/secret.key`（0600，32 字节）；`panel/app.py:76-89`；`install.sh:261-270`
- 复现（实证）：`panel/app.py` 的 `_load_or_create_secret()` 是"存在即读、缺失才生成"；`install.sh` 用 `cp -a "$SCRIPT_DIR/panel"` 把整个 panel 目录（含 `data/secret.key`）拷到 `/opt/openvpn-sk5-panel/`。实测：Flask 进程的 `app.secret_key` 与发货文件字节逐字节相同（sha256 前 16 位 `484fec07e813e9b9`）。
- 影响：任何拿到这份项目树的人都能伪造任意部署的 Flask 会话 cookie（`{"admin": true}`），**无需管理员密码直接进面板**。这违反了 `docs/flmx-reference.md` 1-5 条"禁止写死默认值"与 `docs/security.md` 的"代码里没有任何默认口令/密钥"口径。修法：`install.sh` 安装时删除发货的 `secret.key` 并重生成（或面板首次启动时若检测到该文件与发货哈希相同即强制轮换），且把 `panel/data/secret.key` 从仓库/发布包中移除。

---

## P1 必须修（15 条）

### P1-1 — /api/status 在 SK5 静默时耗时 20 秒（两个 10 秒 egress 探针串行）

- 文件：`panel/app.py:583-599`；`egress/sk5_manager.py:541-556, 561-563`
- 复现（实证）：起一个只接受 TCP 永不回包的静默 SOCKS5（127.0.0.1:11080），`current_egress_ip()` 单次耗时 **10.0s**；`GET /api/status` 耗时 **20.0s**。根因：`sk5_get_status()` 在 enabled 时内部调一次 `current_egress_ip()`，`status()` 又单独调一次——每次状态轮询做两次串行探针。前端每 15 秒轮询一次，SK5 一静默请求就排队堆积、状态页卡死。
- 影响：SK5 故障时正是用户最需要看状态的时候，状态接口本身先 20 秒超时。

### P1-2 — 前端完全没有节点/agent 界面：远程 agent 只能靠 curl

- 文件：`panel/templates/index.html`（全文无 `/api/nodes`、`/api/cmd` 调用，无节点选择器）；`panel/app.py:934-1080`（后端接口齐全）
- 复现（代码确认）：前端只调本地直连接口（`/api/status`、`/api/openvpn/*`、`/api/sk5*`），Flask 的节点注册/命令下发/结果查询接口存在但前端一个都不调。Cloudflare 模式 `cloudflare/README.md:143-144,187` 自认"多节点下拉 UI 是后续项"、"单节点下完整可用"——但即便单节点，节点注册、命令排队状态、agent 在线状态在 UI 里也全无入口。
- 影响：这个面板的核心卖点是"面板直接操作远程中转机"，UI 层却只能管本机；远程模式的管理操作没有图形入口。

### P1-3 — Worker 登录无任何限流（Flask 有同 IP 5 分钟 5 次锁 15 分钟 + 429）

- 文件：`cloudflare/src/index.js:239-258`（`handleLogin` 无计数、无锁定）；`panel/app.py:232-273`
- 复现（实证）：Worker mock KV 下连续 10 次错误密码登录，全部返回 401，**一次 429 都没有**。
- 影响：Cloudflare 面板的管理密码可被无限在线爆破（KV 免费额度内几乎无成本）。

### P1-4 — Worker 无节点吊销/轮换接口（Flask 有 DELETE /api/nodes/\<name\>、POST …/rotate）

- 文件：`cloudflare/src/index.js:508-612`（路由表无此二路由）；`panel/app.py:988-1031`
- 复现（实证）：`DELETE /api/nodes/node1` → 404；`POST /api/nodes/node1/rotate` → 404。README 给出的"轮换办法"是手工删 KV 里的 `node:<name>`（`cloudflare/README.md:173-174`）。
- 影响：节点 token 泄露后无法在面板内吊销或轮换，只能手工改 KV；与 Flask 侧"旧 token 立即作废"的能力不对等。

### P1-5 — Worker 快照形状错位：出口 IP、在线用户、协议/端口恒为空

- 文件：`cloudflare/src/index.js:221-232`（`snapshotFromResult`）；`agent/agent.py:582-589`（`action_get_status`）
- 复现（实证）：模拟 agent 上报标准 `get_status` 结果 `{openvpn:{running, clients:[…]}, users:[…], sk5:{…}, egress_ip:"1.2.3.4"}` 后，`GET /api/status` 返回 `egress: {}`（`snapshotFromResult` 要的是 `result.egress` 对象，agent 给的是扁平 `egress_ip`），`openvpn.online_users` 缺失（`server_status` 只有 `clients` 列表，`online_users` 是 Flask 现算的），`GET /api/nodes` 的 `egress_ip: null`。且 `openvpn` 快照里无 `proto/port/subnet/dns`（Flask 才补这四个字段），前端在 Cloudflare 模式下协议/端口/子网/DNS 四格恒为"—"，在线用户恒为"0 人"。
- 影响：Cloudflare 面板状态页核心数字（当前出口 IP 是不是 SK5 的 IP）永远空白，验收判据本身看不见。

### P1-6 — 命令"sent"态无重投：agent 取走后死掉，命令永久卡住

- 文件：`panel/app.py:1128-1155`（poll 出队后即清队列）；`cloudflare/src/index.js:321-346`（同款）；`agent/agent.py:686-699`（report 失败只记日志）
- 复现（Flask test-client，实证）：下发 `create_user` → poll 一次取走命令 → 第二次 poll 返回空；若此时 agent 崩溃、report 丢失，命令在 `sent` 态永久停留，两端只给"已下发超过 120 秒未回执，可重新下发"的提示。非幂等命令（`create_user`、`init_pki`）人工重发有重复执行副作用；`nodes_revoke` 只把 `queued` 命令标失败，`sent` 的不管。
- 影响：一次 agent 崩溃或网络抖动就能让一条管理命令无声丢失，面板显示"已下发"、实际没执行。

### P1-7 — 无管理员改密接口、无首次登录强制改密

- 文件：`panel/app.py`（全文无 change-password 路由；实测 `POST /api/change-password` → 404）；`install.sh:560-563` 自认"面板没有改密接口，请妥善保存"
- 影响：初始随机密码一旦泄露（日志、截图、转发），无法在面板内轮换，只能进 SQLite 手工改哈希；与 `docs/flmx-reference.md` 第 3 条（FLMX 对照）不符。

### P1-8 — check_health() 从未被任何部署件调用：fail-open 是死开关

- 文件：`egress/sk5_manager.py:602-630`；`panel/README.md:80,85`；`egress/README.md:87,125-126`；`systemd/`（无 timer 单元）；`install.sh`（无定时器/启动钩子）
- 复现（代码确认）：全仓 grep，`check_health` 的调用方只有 CLI 入口与 README。`panel/README.md` 自认"面板暂未轮询"，`egress/README.md` 称"供定时器轮询"但没有任何 timer 单元、cron、启动钩子存在。
- 影响：默认断网保护（kill-switch）靠"table 100 留在原地"惯性成立；但 `fail_open=true` 时没有任何东西会去执行 fail-over，用户开 fail-open 得到的仍是永久黑洞——面板上的开关承诺了一个不存在的行为。

### P1-9 — 策略路由无开机持久化；install.sh 重跑会覆盖已渲染的 SK5 配置

- 文件：`egress/policy-routing.sh`（`ip rule` 只写运行时状态）；`install.sh:351-384`；`systemd/openvpn-sk5-singbox.service`（无 ExecStartPost）
- 复现（代码确认）：
  - `ip rule from 10.8.0.0/24 lookup 100` 是运行时状态，重启后消失；没有任何单元、钩子、timer 在开机时重挂。重启后 `sk5.json` 仍 `enabled=true`，面板仍显示"SK5 已启用"，但 VPN 用户流量已走主表直连——**静默 fail-open，与断网保护承诺相反**。前端虽有 `policy_routing_active` 一格显示"未生效"，但无告警、无自动修复。
  - `install.sh` 每次重跑都用 `cat > "$CONFIG_DIR/sing-box.json"` 无条件写入直连模式配置（无"已存在则保留"守卫）。SK5 已启用时重跑安装，磁盘上的 sing-box 配置被换成直连版；当前运行的 sing-box 进程尚持旧配置，重启/重装后即按直连版加载，`sk5.json` 仍称 enabled——同款静默降级。
- 影响：一次重启或一次重装就能让"已启用 SK5"变成"直连出口"，面板不报错。

### P1-10 — agent 的 create_server 不幂等：第二次"建服务"必失败

- 文件：`agent/agent.py:490-499`；`core/openvpn_manager.py:151-183`；`core/easyrsa.sh:66-80`
- 复现（代码确认；沙箱无 easy-rsa，未能在真机复现）：`action_create_server` 每次都无条件调 `build_server_cert()`，后者调 `easyrsa.sh build-server` → `easyrsa gen-req server`。Easy-RSA 在 `pki/private/server.key` 已存在时拒绝重建（须先删 req/key）。`install.sh:395-404` 自己处理了这种"中断残留"（无 server.crt 时删 stale req/key），但 agent 路没做。面板"建服务"点第二次（例如改个端口）即报 easyrsa 错。
- 影响：agent 模式下改协议/端口的唯一入口是坏的；且 `build_server_cert` 每次重跑 `gen-dh`（2048 位，数分钟），即使能跑也极慢。

### P1-11 — 入口段端口无占用检查（FLMX P01 铁律未落地）

- 文件：`panel/app.py:629-655`；`agent/agent.py:490-499`；`core/openvpn_manager.py:395-427`；`docs/flmx-reference.md:1-24`
- 复现（代码确认）：全仓无 `ss`/`lsof`/bind 探测。`POST /api/openvpn/server` 只校验端口范围，不查本节点占用。1194/443 已被别的服务占时，配置照常渲染，失败只在 `systemctl start openvpn-server@server` 时才以通用错误爆出。`docs/flmx-reference.md` 1-24 明确映射"建服务时查本节点占用并避开"，且用户有"入口段端口创建时严密审查现有占用并避开、创建后永不换口"的在册口径——代码里零实现。
- 影响：端口冲突要到启动失败才发现，且报错不指明冲突方。

### P1-12 — UoT 探针把 SK5 密码写进 /tmp 明文文件，无显式 chmod

- 文件：`egress/sk5_manager.py:440-481`（`_udp_probe_via_uot_singbox`）
- 复现（实证）：用假 sing-box 顶住 18080 端口，调 `_udp_probe_via_uot_singbox`，探针进行中 `/tmp/openvpn-sk5-uot-probe/sing-box.json` 实测存在且内容含 SK5 明文密码，模式 `0660`（本沙箱 umask 007；标准 Debian umask 022 下同款代码产生 `0644`，即任意本地用户可读）。文件路径固定可预测，目录同样无显式 chmod；`finally` 只删文件不删目录。
- 影响：每次 UoT 测试期间，SK5 密码以明文躺在 `/tmp` 固定路径，权限取决于进程 umask。另：该临时路径固定，多并发探针会互踩同一文件（P2-11）。

### P1-13 — core 的 systemctl 调用无超时、无 FileNotFoundError 保护：无 systemctl 二进制的主机上启停/状态直接崩溃，直接模式回退不可达

- 文件：`core/openvpn_manager.py:471-476, 500-504`
- 复现（实证）：把 `PATH` 剥到只剩空目录后跑 `server_status()`，实测抛 `FileNotFoundError: [Errno 2] No such file or directory: 'systemctl'`——尽管函数 docstring 承诺"Never raises for a stopped/missing daemon"。`start_server()` 同理抛 `FileNotFoundError`，而不是按文档"systemd 不可用时直接 `openvpn --daemon` 启动"。`server_status` 与 `_systemctl` 的 `subprocess.run` 都没传 `timeout`，systemctl 一挂住，`/api/status` 也跟着挂住（egress 的 `_singbox_running` 有 `timeout=10` 且捕 `OSError`，core 没有）。
- 影响：无 systemd 的容器/精简主机上，OpenVPN 的启停查三路全崩；文档承诺的直接模式回退在该环境下是死代码。

### P1-14 — cloudflare/server-mode.md 与代码严重不符（已过时到会误导部署）

- 文件：`cloudflare/server-mode.md`
- 复现（文档对代码）：
  - 称"panel/app.py 目前是单机直连版，尚未实现 /api/agent/poll、/api/agent/report、/api/nodes、/api/cmd"——**四者都已实现**（`panel/app.py:1079-1245`）。
  - 称"命令队列 / 结果存储：本地 SQLite / JSON（待补）"——已实现（`agent_queue.json` + SQLite `nodes` 表）。
  - 称"set_sk5 语义：部分合并（只改传来的字段）"（服务器模式列）——Flask 侧是全量覆盖（见 P0-4），且 agent 强制 host+port（见 P0-2）。
- 影响：按此文档部署会以为服务器面板接不了远程 agent、以为 set_sk5 可以单字段改——两个结论都是错的。

### P1-15 — cloudflare/README.md 的"set_sk5 部分合并语义"是假宣称

- 文件：`cloudflare/README.md:115-117`；`agent/agent.py:546-548`
- 复现：README 称"set_sk5 按部分合并语义：agent 只改传来的字段，未传的字段保持原值。面板'故障回直连 / UDP over TCP'两个开关就是单独发 set_sk5 {fail_open} / set_sk5 {udp_over_tcp} 实现的。"——agent 代码首行即 `_need_params(params, "host", "port")`，单字段调用必被拒（P0-2 已实证）。文档的中心契约断言与实现相反。
- 影响：照文档实现的任何客户端（包括本项目自己的 Worker）都会踩 P0-2。

---

## P2 建议（13 条）

### P2-1 — 登录限流是进程内内存，且无 ProxyFix：反代后 remote_addr 全是代理 IP，全局误锁

- 文件：`panel/app.py:232-273`（`_LOGIN_ATTEMPTS` 内存 dict，`request.remote_addr`）；`docs/security.md` 自认"重启后清零"
- 影响：面板重启即清零（重启窗口内可再试 5 次）；面板挂反代/CF 后所有登录来自同一 IP，一人触发锁定即锁全部人。修法：计数进 SQLite + `ProxyFix`（或只信可信代理的 `X-Forwarded-For`）。

### P2-2 — agent 已装 sing-box 时不校验版本（只跑 version，不比对）

- 文件：`agent/agent.py:407-414`；对比 `agent/agent.py:416-427`（tun2socks 会比对 `TUN2SOCKS_VERSION`）、`install.sh:223-231`（会比对 `SINGBOX_VERSION`）
- 复现（代码段分析，实证）：`_install_singbox` 的 early-return 块只 `_run([singbox, "version"])` 后直接返回，全块不出现 `SINGBOX_VERSION`。节点上已有 sing-box 1.8.0 时 agent 照单全收，`sing-box check` 到启用时才报 1.11 字段错，定位困难。

### P2-3 — agent --once 轮询失败仍返回 0

- 文件：`agent/agent.py:735-746`
- 复现（实证）：`--config` 指一个 panel_url 为 `https://127.0.0.1:1` 的配置跑 `--once`，日志 "poll failed: … Connection refused"，进程退出码 **0**。`run_once()` 返回 -1，但 `main` 丢弃了返回值。
- 影响：`--once` 不能用于健康检查/冒烟脚本（失败也报成功）。

### P2-4 — bundle 确定性不完全：只排了文件名序，未排目录序

- 文件：`panel/app.py:1225-1247`（`_build_agent_bundle`）
- 复现（代码确认；实测两次打包字节一致）：`os.walk` 的 `dirnames` 只过滤 `__pycache__` 未排序，tar 条目顺序依赖文件系统 readdir 顺序。本沙箱两次打包字节相同（同一文件系统短时间内稳定），但换一台机器/一次目录变动就可能让 `/api/agent/bundle.sha256` 与实际下载的包对不上，fail-closed 误杀正常安装。

### P2-5 — 管理员密码哈希是加盐 SHA-256 而非 bcrypt

- 文件：`panel/app.py:157-168`（`_hash_password`）；`docs/security.md` 已记为"与 FLMX 的待对齐项"
- 影响：DB 泄露后 SHA-256 可高速离线爆破；bcrypt/argon2 是既定对齐目标。

### P2-6 — OVPN_DNS 环境变量被静默忽略

- 文件：`install.sh:41,128`（只读入与打印）；`core/server.conf.template:22`（`push "dhcp-option DNS 1.1.1.1"` 写死）；`core/openvpn_manager.py:395-427`（`render_server_conf` 无 DNS 参数）
- 复现（代码确认）：`OVPN_DNS=8.8.8.8 bash install.sh` 后 server.conf 里仍是 1.1.1.1。README 只对 `OVPN_SUBNET` 诚实标注了"core 固定值，改了也只影响 NAT 规则"，`OVPN_DNS` 无此标注。

### P2-7 — install.sh 写 panel.env 的 PANEL_ADMIN_PASSWORD_FILE，但 app.py 从不读它

- 文件：`install.sh:333-345`；`panel/app.py:72-73`（`ADMIN_PASS_PATH` 硬编码 `/etc/openvpn-sk5-panel/admin.pass`）
- 影响：目前两者恰好同值所以能工作；一旦有人改 panel.env，面板照旧写死路径，安装健康门禁读到的密码文件与面板实际写的不一致，安装在最后一步自杀。死变量应删或接线。

### P2-8 — install.sh / verify.sh 健康门禁登录时把管理员密码放进 curl -d argv（ps 可见）

- 文件：`install.sh:544`；`verify.sh:196`
- 复现（实证）：对一个只接受不回包的本地端口跑同款 `curl -d '{"password": "TOPSECRET-ADMIN-PW"}'`，进行中读 `/proc/<pid>/cmdline`，密码明文完整在列。curl 只 scrub `-u/--proxy-user` 类凭据参数，`-d` 的 body 不 scrub。
- 影响：安装/自检的数秒窗口内，本机任意用户 `ps` 即可看到管理员初始密码（该密码同时还打印在安装总结里，窗口与安装过程重合）。

### P2-9 — init_pki force=true 可经远程命令触发，无二次确认

- 文件：`agent/agent.py:483-488`（`action_init_pki` 直接传 `force`）；`panel/app.py:101-113`（白名单放行）
- 影响：一条 `/api/cmd`（`init_pki {force:true}`）就能清空 CA、作废全部已发用户证书；管理员误点或会话被盗即全灭。应要求显式确认字段或禁掉远程 force。

### P2-10 — .ovpn 下载接口不校验用户状态：已吊销用户仍可下载

- 文件：`panel/app.py:1079-1100`（`ovpn_users_download` 只调 `_rebuild_user_ovpn`，不查 `list_users` 状态）
- 影响：低。被吊销证书的 .ovpn 下载回去也连不上（CRL 会拦），但 UI 上"吊销"后仍可下载旧凭证，易生困惑。

### P2-11 — UoT 探针用固定 /tmp 路径，多并发探针互踩；_expected_sha256 首个 manifest 无条目时直接 raise

- 文件：`egress/sk5_manager.py:448-451`（`tmpdir = /tmp/openvpn-sk5-uot-probe` 固定）；`agent/agent.py:376-394`（manifest 循环内 `raise`，不试下一个名字）
- 影响：低。两次 `test_sk5` 并发会覆写同一临时配置；上游 `checksums.txt` 存在但缺条目时本应试 `SHA256SUMS.txt`，现直接拒绝安装。

### P2-12 — 两处文档已过时（好消息方向，但仍须改）

- `docs/security.md` 残留风险 #1 称"install_prereqs 的 sing-box SHA-256 校验目前是可选参数：不给只告警、不阻断"——**已不成立**：`agent/agent.py:361-394` 的 `_expected_sha256` 是 fail-closed（无 manifest 且无 override 即 raise），集成路已修，文档未同步。
- 根 `README.md` 称"待补：面板尚未提供 /api/agent/bundle.sha256 端点"——**已不成立**：端点已补（`panel/app.py:1249-1258`），README 未同步。按旧文档部署会误以为远程装 agent 被阻塞。

### P2-13 — docs/flmx-reference.md 多项映射未落地或已过时

- 0-2：称节点 token"改放原始 token（或自定义 X-Node-Token 头）"，实际 agent 仍用 `Authorization: Bearer`（`agent/agent.py:209-213`）。Bearer 本身没问题，表须更新。
- 1-10：`POST /api/nodes/{id}/install` 返回可粘贴装机命令——未实现。
- 1-13：`install-agent.sh` 本身应先验 `.sha256` 再执行（FLMX 同款）——未实现；目前是 `curl | bash` 无校验（TLS 是唯一保护）。
- 1-25：`Proto=udp` 时 SK5 须支持 UDP Associate 否则表单直接拒绝——未实现；TCP-only SK5 + UDP 1194 的组合可保存成功，UDP 默默不通。
- 1-4 / 1-17：已有部署须显式 `--force` + 备份旧 config、`reset-failed` 后判活——`install-agent.sh` 无 `--force`、无 `reset-failed`（有 `is-active` 判活，`install-agent.sh:168`）。

---

## 已确认的非问题（审计员逐项核实，可直接采信）

- 无 `TODO/FIXME/XXX/NotImplemented`；无空函数；全部 `pass` 皆为合法的异常吞掉。
- 无 `shell=True`；subprocess 全用列表参数；agent params 白名单 13 个动作 + 禁用键（`command/shell/cmd/exec/script/argv`）分派前拒绝（实测：`bogus_action` 与 `{"shell": "id"}` 均被拒）。
- 节点 token 两端只存 SHA-256（Flask SQLite / Worker KV）；注册/轮换/吊销实测生效（旧 token 轮换后 poll 401、吊销后 poll 401）。
- SK5 密码 0600 存放（`sk5.json`、`sing-box.json`）；审计日志脱敏（实测 audit 日志里无 `SECRET123`）；`agent_queue.json` 0600。
- agent 强制 HTTPS + 拒 https→http 降级重定向（`_NoDowngradeRedirectHandler`）；`panel_url` 认领守卫实测生效（Flask poll 错 panel_url → 403）。
- `.ovpn` 下载经 `validate_username` 校验；`node_user_ovpn` 只是字典查找，无路径穿越。
- `install.sh` / `install-agent.sh` 的 sha256 校验是真 fail-closed（无 manifest 且无 override 即停）；`install.sh` 有 `/root/flmx-panel` 目标断言；`verify.sh` 对沙箱缺二进制诚实记 FAIL/SKIP。
- `server.conf.template` 与 `sing-box.json.template` 渲染后 JSON/配置合法（模板校验通过）；`policy-routing.sh` 的"只按源地址匹配、拒绝 from-all 规则"守卫逻辑正确。

## 已证伪 / 已修正的候选问题（审计过程中推翻，不立案）

- **"SK5 密码经 curl --proxy-user 泄露到 ps"——证伪。** 原以为 `_curl_via_sk5`（`egress/sk5_manager.py:268-277`）与 `test-egress.sh` 把密码放进 curl argv 即泄露。实测：对静默 SOCKS 跑同款 curl，`/proc/<pid>/cmdline` 里 `--proxy-user` 后是空白——**curl 自行 scrub 了该参数**。改为 P2-8（`curl -d` 的管理员密码是真泄露，curl 不 scrub body）。
- **"sk5_set_enabled 未 import"——误报。** 集成路已澄清：现文件正确调用已 import 的 `sk5_enable_fn` / `sk5_disable_fn`。
- **"Flask 的 bundle.sha256 端点缺失"——已修。** 主控在审计前已补（`panel/app.py:1249-1258`）；实测两次打包字节一致、哈希与包体相符。残留 P2-4（目录序未排）与 P2-12（README 未同步）。

## 审计未覆盖 / 须真机验证的部分（诚实列明，不冒充结论）

- 未在真机跑过 openvpn/sing-box 端到端：沙箱无这两个二进制；UDP 数据面验证只能上测试机（沙箱 UDP sendto 一律 EPERM）。
- Cloudflare 未真实 `wrangler deploy`（无登录态、KV id 是占位符）；Workers 版本按 POP 慢速传播，验活须换第二出口多点核（2026-11-10 教训）。
- P1-10 的 easyrsa 重建拒绝行为未在真机复现（沙箱无 easy-rsa），以 Easy-RSA 行为 + `install.sh` 的同款 stale 清理逻辑为据。
- 真机验证报告 `docs/live-verify.md` 尚在进行中（S0–S4 待填）；其 §1 已实测：**Simular Box 不能当中转机**（无公网 IP、无入站、无直连路由），原定 Box 作中转机的拓扑已不可行，验证路已 pivot 到 Lightsail 作中转机。本审计的结论不受该 pivot 影响。
- `check_health` 的 fail-open 语义、`create_server` 二次调用、`install.sh` 重跑覆盖配置三项，建议在真机上复核（沙箱只能证代码路径）。

## 修完后的复审口径

按第一前提，修复后的再审计必须全量全局（doc/index.md＋doc/guide/ 13 篇功能全链验为骨架、代码面全量分路为辅，换推导方法独立复算），不许只审修复 diff。本报告的 33 条 finding 逐条复验时，P0-1/P0-2/P0-3 须在真实 `wrangler deploy` 的 Worker 上复验（mock KV 不算数），P0-4/P1-1/P1-8/P1-9/P1-10/P1-13 须在 Lightsail 真机上复验。

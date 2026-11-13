# OpenVPN 接 SK5 落地 · 真机复跑验证报告（第十四轮 R14）

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（BJ＋BK＋BL＋BM 四路修复后的最新树——本轮第一次验证 R19 的 2 条、R20 的 2 条与 R13-BUG-1 的 BM 修复）。
> 验证人：真机复跑验证路（第十四轮）。日期：2026-11-12。
> **结论：R19 与 R20 的真机格全过，S0–S4 与 headline 精选全过；新 bug 1 个（R14-BUG-1，高——自愈重建的死 tun1 挡住 sing-box 重启，链路永久停在黑洞态）。**
> 前情：第十三轮见 [live-verify-R13.md](live-verify-R13.md)（R18 的 2 条真机格全过、S0–S4 与 headline 精选全过；新 bug 1 个高——R13-BUG-1，sing-box 死亡静默回直连）；AUDIT-R19（224 行，差集 2 条全 P2 Worker 面，BJ 已修并主控核验）、AUDIT-R20（287 行，差集 2 条全 P2，BK＋BL 已修并主控核验）；AUDIT-R21 在本轮打包后完工（318 行，差集 1 条 P2：R21-P2-1 队列文件整文件损坏静默丢命令，BN 路已修并主控核验）、AUDIT-R22 在跑——**本轮打包树早于 BN 修复，R21-P2-1 的真机格属 live-15；本轮只验代码真机行为，不写审计结论**。

## 0. 树版本（本次装机所用）

| 文件 | mtime (UTC) | sha256（前 12 位） | 说明 |
|---|---|---|---|
| install.sh | 2026-11-12 16:46:54 | 3f050f037e7a | AZ 路（未动） |
| panel/app.py | 2026-11-12 18:38:12 | 204de1136cc5 | BG 路：poll 循环顶 `status != "queued": continue`＋report 非 sent 回 409（2754 行） |
| core/openvpn_manager.py | 2026-11-12 17:20:57 | 3b5d7dfe9ea1 | BB 路（未动） |
| agent/agent.py | 2026-11-12 19:50:12 | f303af828555 | BL 路：心跳 `isinstance(parsed, dict)` 检查 |
| cloudflare/src/index.js | 2026-11-12 19:25:36 | 089bb32da319 | BJ 路：`kvArray` 归一化＋下载快照守卫 |
| egress/policy-routing.sh | 2026-11-12 20:06:09 | 423a98bd022e | BM 路：table 100 兜底黑洞＋自检 |
| egress/sk5_manager.py | 2026-11-12 20:03:26 | 7727486677a2 | BK 路 `_validate_stored`＋BM 路 `_repair_policy` 自愈 |
| panel/templates/index.html | 2026-11-12 15:21:57 | 4f7dc697451c | AR 路（未动） |
| verify.sh | 2026-11-12 14:45:28 | 7867f557c6bb | 主控（未动） |
| verify-integration.sh | 2026-11-12 18:14:53 | 6ef6ba2db8b1 | BE 路：§7 两层同一格（常量值＋字典绑定） |
| egress/test-egress.sh | 2026-11-12 08:40:51 | d6db69ec0a6e | X 路（未动） |

树稳定检查：最新产品改动为 egress/policy-routing.sh（20:06:09 UTC），打包执行时刻 20:21:16 UTC，**稳定 15 分 07 秒**（满 15 分钟门；live-11 差 12 秒的教训未重犯）。其间只有 AUDIT-R21 的报告文件与本报告在写、产品文件无变动；`__pycache__` 为探针 import 产物、打包时剔除（安装子集不含 tests/）。打包时源码树 `panel/data/` 为空（`ls` 空）；毒 panel.db＋agent_queue.json 由 AE 的真实代码毒快照（`~/workspace/ae-tests/poison/`）注入打包副本，**源码树本身未被毒化**。

**打包（20:21:16 UTC）**：传包走 scp（R4–R13 同款）。`ovpn-r14.tar.gz`：41 条目，198,295 字节，sha256 `116a5a890d2b333e7725f24b51c574a11b4588e4fa839bf0473f002a2889e9fb`（机上核对一致）；install.sh sha256 `3f050f037e7a4eba992716aff5d8f54ed746c2769c6fd224d55da696d3d468de`。清单与 R13 逐项一致（41/41 diff 空）。包内毒物核对：`panel/data/panel.db` 含 admin 行 1 条（哈希 `$2b$12$tceqe…`，表 `admin`）、`panel/data/agent_queue.json` 含 3 条 init_pki force+confirm（action 均为 init_pki）——与 R8 §6.2 的毒形一致。

## 1. 地面真值（Lightsail 现状，测试前实测，20:12 UTC）

- 机上是**第十三轮收尾态**：安装 #1＋headline-9 默认重跑后状态。openvpn-server 单元 inactive（但 openvpn 进程 PID 902628 仍在、监听 443——live-13 §8 面板 restart 直接拉起的进程，非 systemd 单元在管，属既往收尾态）；panel PID 897099（8443）、sing-box MainPID 908457、agent active、dante 127.0.0.1:11080 active；SK5 禁用；节点 lightsail 已注册；用户 alice/bob 有效；ufw 启用；CA 序列 `0E665BBEC1ED87EB41AC89B8F2AB615D040745A4`。
- 第十三轮残留全部在位，**重装前必须清除**：`/root/r13/` 测试产物在位；`/root/ovpn-r13.tar.gz`（毒包，证据，**勿删**）、`/root/ovpn-r12.tar.gz`、`/root/ovpn-r11.tar.gz`、`/root/ovpn-r10.tar.gz`、`/root/ovpn-r9.tar.gz`、`/root/ovpn-r8.tar.gz`、`/root/ovpn-r7.tar.gz`、`/root/ovpn-r7b.tar.gz`、`/root/ovpn-r2.tar.gz` 在位；`/opt/openvpn-sk5-panel/` 为第十三轮装树；`/etc/openvpn-sk5-panel/` 含 admin.pass（0600）；`/etc/openvpn/server/server.conf` 为 `port 443 / proto tcp / server 10.8.0.0 255.255.255.0`。
- netns `vpntest` 仍在（live-13 收尾遗留）；TCP 客户端 PID 903751 仍连（live-13 终态）。
- FLMX 相关进程同机在跑（paneld、flmx-int2 paneld、flmx_agent、sing-box 1.14.4），**一律不碰**；`/root/flmx-panel` 不动。

## 2. 清场（全新重装前，20:14 UTC）

- 先杀 live-13 遗留 TCP 客户端（精确 PID 903751，`kill`＋`kill -9` 确认消失）、删 netns `vpntest`（`ip netns list` 空）。
- 四服务已停（openvpn 进程 902628 精确 PID 杀、panel/singbox/agent 全部 inactive，dante 保留，active）；无残留客户端进程。
- FORWARD 链删 tun0 产品规则、NAT POSTROUTING 的 `-s 10.8.0.0/24 -o ens5 MASQUERADE` 1 条；其余 ts-forward/DOCKER-USER/DOCKER-FORWARD/ufw 段不动。
- 状态已 wipe：`/root/openvpn-sk5-panel`、`/opt/openvpn-sk5-panel`、`/opt/ovpn-agent`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/ovpn-agent` 全删；sing-box 与 tun2socks 二进制已删（`find` 空，逼安装器走下载路径，复验版本校验）；`/root/r13/`、全部证据 tarball 保留未动。
- 清场后核对：无 tun0/tun1、无 1194/443/8443 监听、`/opt/openvpn-sk5-panel` 与 `/etc/openvpn-sk5-panel` 不存在。
- S0 安装已于 20:21 UTC 后台启动（`nohup bash install.sh`，日志 `/root/r14/install.log`，安装器 PID 920359）。

## 3. S0 基线：毒包安装 + 建服务 + 建用户 —— 通过（一次成功；AN 新行在位）

### 3.0 第一次安装（毒包，全新安装，UDP 1194 默认）—— 通过

- install.log：**0 个 ERROR**；sing-box 1.11.15 下载 `sha256 OK`、自报 `sing-box version 1.11.15`；tun2socks 2.7.0 下载 `sha256 OK`；完成横幅已印。
- **毒物未入住（AN 新行为）**：日志有新行 `[install] panel/ installed (panel/data/ excluded: …)`（1 条）；旧 `discarded shipped runtime file` 行 **0 条**；初始密码已生成并写入 `/etc/openvpn-sk5-panel/admin.pass`（0600）。
- 装后核对：`/opt/openvpn-sk5-panel/panel/data/` 仅含 panel.db，**agent_queue.json 文件不存在**（毒队列从未拷入）；panel.db 的 admin 行哈希为 `$2b$12$1vF6lXLXNJWi2ru…`，与毒哈希 `$2b$12$tceqe…` 不同——全新 admin 行；nodes 0、audit_log 1 行（全新库）、login_attempts 0 行。
- 服务：openvpn-server@server active（UDP 1194，PID 921073）、panel PID 921197、sing-box active，agent inactive（属预期，由 S0-agent 安装）；CA 序列 `49682873442675F2BBB31E5C5E990FD9278C8FC4`（notBefore 2026-11-12 20:21:50，记下供 agent 轮询后对比）。
- ufw 回归格（AN 的 R8-BUG-2 反面）：机上 ufw 在位——安装后 `ufw status` 仍 4015 行；iptables-persistent 未装（ufw 机跳过，属预期）。

### 3.1 S0 后半段：建服务确认＋建用户 —— 通过

- 面板登录 200；`/api/status` 200：openvpn running（UDP 1194，PID 921073），online_users 0，SK5 未启用，`singbox_running: true`，sk5 块 `policy_routing_active: false`。
- 默认 `.ovpn` remote 为 **16.146.199.68 1194**（IPv4 公网）。
- 用户：alice、bob 创建均 200；`GET /api/openvpn/users` 只列 alice、bob，alice 序列号 `7B4D5FC04FBF7466196F1069D45611E6`、bob `8FFCC11B2922A6B58AC4D75D0016E789`。
- **观察（不立案）**：`/api/status` 的直接出口探测返回 IPv6 地址 `2600:1f13:14d:a300:7913:f273:997e:c8b8`（本机有 IPv6，探测走了 v6）；live-9 同格为 IPv4 16.146.199.68、live-10/live-11/live-12/live-13 同款 IPv6。数据面实测（S1/S2）仍以 IPv4 出口为准，面板 `egress.ip` 的 v4/v6 取值未作断言。

## 4. S0-agent：节点注册 + agent 安装 + 命令链 —— 通过（第二毒物 agent 侧终验通过）

- 注册：`POST /api/nodes {"name":"lightsail","panel_url":"https://172.26.15.152:8443"}` → 201，token 只存 `/root/r14/token.txt`（未写报告）。中途一次取 token 路径走偏：`json.load` 被 panel.py 的 `201 ` 状态前缀绊住——改 sed 按首个 `{` 截取后取全 token（长 43），测试侧流程问题，非产品问题。
- 安装命令（面板两步走命令，按 agent/README 记载的流程执行；token 由文件读入）：`curl -ksSL https://172.26.15.152:8443/install-agent.sh`＋`install-agent.sh.sha256` 校验 `install-agent.sh: OK`＋`bash /tmp/install-agent.sh --panel-url … --token … --node-name 'lightsail'` → **EXIT=0**。bundle sha256 OK、`/etc/ovpn-agent/config.json` 0600、`ovpn-agent is ACTIVE (node=lightsail)`。
- poll：`GET /api/nodes` 的 `last_seen` 为 2026-11-12T20:25:09+00:00（新鲜），心跳合并 `last_status`（hostname/version/openvpn_running/sk5_enabled）；agent 日志 0 条 401/403、无 poll failed、无 init_pki。
- **毒 init_pki 未执行**：agent 上线并轮询后，CA 序列仍为 `49682873442675F2BBB31E5C5E990FD9278C8FC4`（与安装时一致）；面板 `agent_queue.json` 现为 `{"queue": {"lightsail": []}, "cmds": {仅 1 条合法 get_status}, "ovpn": {}}`——init_pki 0 条。
- 命令链：`POST /api/cmd {"node":"lightsail","action":"get_status"}` → **202**（cmd_id 0d1b536a…）；约 1 秒后 `GET /api/cmd/<id>` → **done**，error null；result 含 openvpn running=true pid 921073（与面板一致）、sk5 enabled=false。

## 5. S1 直连态（UDP 1194）—— 通过（首次即通，零手工 FORWARD）

- 客户端（alice，netns vpntest，`--float`）：改 remote 为 LAN IP 172.26.15.152（R7 同款，公网 IP 发夹在 netns 内受限，非产品问题），**首次即通**，`Initialization Sequence Completed`（20:25:59），tun0 10.8.0.2/24，redirect-gateway 路由就位（0.0.0.0/1＋128.0.0.0/1 via 10.8.0.1 dev tun0）。PID 923112。
- 数据面（direct）：`curl ifconfig.me`（HTTP 与 HTTPS，--resolve 绕 MagicDNS）→ **16.146.199.68**；NTP UDP：216.239.35.4 回 **48 字节** 14.4ms、162.159.200.1 回 **48 字节** 6.1ms。UDP 数据面通过。
- **BUG-9 第十五次复验——修好（UDP 模式）**：部署态原始日志（逗号 v2，13 段）为 `CLIENT_LIST,alice,10.200.0.2:46840,10.8.0.2,,6746,11032,2026-11-12 20:25:59,1794515159,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users` = **1**；`clients`=[{name: alice, real_address: 10.200.0.2:46840, virtual_address: 10.8.0.2, bytes_received: "6746", bytes_sent: "11032", connected_since: "2026-11-12 20:25:59"}]——逐字段一致；`/api/openvpn/users` 的 alice `online: true`、bob `online: false`（本节实测）。

## 6. S2 落地态（SK5 开）—— 通过（TCP+UDP 均走 SK5，双日志为证）

- 启用：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → 200（`policy_routing_active: true`）；`/api/sk5/test` → 200（tcp_ok，84.6ms；udp_ok，`mode: native`，native UDP ASSOCIATE + DNS to 1.1.1.1:53——非 TCP 承载冒充）。
- 路由（策略路由表 100）：`ip rule`（`from 10.8.0.0/24 lookup 100`）；表 100 `default via 10.9.0.1 dev tun1` **＋ `blackhole default metric 200`（BM 层 1 在真机上在位）**；`ip route get 1.1.1.1 from 10.8.0.1` → `dev tun1 table 100`；tun1 UP、mtu 1400。
- 数据面（dante 本地测试 SK5，出口仍为本机 IP 16.146.199.68——属测试 SK5 的已知性质）：隧道内 curl ifconfig.me（HTTP 与 HTTPS，--resolve 绕 MagicDNS）→ **16.146.199.68**；NTP UDP：216.239.35.4 回 **48 字节** 26.7ms、162.159.200.1 回 **48 字节** 22.2ms（比直连态慢，符合 SK5 路径）。
- 双日志为证：sing-box 日志（20:27:54–55）明文记录 `outbound/socks[bought-sk5]: outbound connection to 34.160.111.145:80`、`:443`，以及 `outbound packet connection to 216.239.35.4:123` 与 `162.159.200.1:123`（inbound/tun[tun-in] 收到）——**TCP 与 UDP 均真实走了 SK5 出站**；dante 日志同窗口有 `tcp/connect` 与 `udp/udpassociate`。

## 7. S3 断网保护（杀 dante）—— 通过（数据面全断、无直连回落、自动恢复、隧道不断）

- 杀 dante（`systemctl stop danted`，inactive）：客户端 TCP `curl --resolve … http://ifconfig.me` → **exit 56**（Recv failure），HTTPS → exit 35（SSL connect error，同样失败）；NTP UDP 到 216.239.35.4 → **TimeoutError**；**无直连回落**（curl 不是成功、是失败——fail-closed 成立）。隧道未断（同一客户端 PID 923112，tun0 仍在，`Initialization Sequence Completed` 仅 1 次）。
- 面板 `/api/status`：kill 期间 **egress.ip = null**（`{'error': None, 'ip': None, 'latency_ms': None, 'via_sk5': True}` 形状同 live-9/live-10/live-11/live-12/live-13），诚实报空。
- 恢复（`systemctl start danted`，active）：客户端 TCP 立即回 **16.146.199.68**，NTP 回 **48 字节** 24.3ms。隧道全程未断：同一 PID 923112，client.log 里 `Initialization Sequence Completed` 仅出现 1 次、SIGUSR1 0 行——无重连、无重拨。
- 口径注记（设计，非缺陷）：kill 期间 `dig @1.1.1.1` 仍有回包——sing-box 路由规则 `protocol dns / port 53 → direct`（见 `/etc/openvpn-sk5-panel/sing-box.json`），DNS 默认走直连、不经 SK5，是文档已定设计；断网保护覆盖的是 TCP/UDP 数据面，DNS 不在黑洞范围内。
- **本节只覆盖 SK5 死亡（dante 死）情形。sing-box 本体死亡情形见 §9 BM 真机格——本轮首次以修复后代码实测。**

## 8. S4 TCP 备模式（443）—— 通过（BUG-14 修好，S1/S2 各重跑一次）

- **BUG-14 修好**：`POST /api/openvpn/server {"proto":"tcp","port":443,"allow_port_change":true}` → **HTTP 200**。`POST /api/openvpn/restart` → 200（新 pid 924218）。TCP 443 监听，UDP 1194 监听消失，`/api/status` 为 proto=tcp port=443 running=true；新下载的 alice.ovpn 为 `proto tcp / remote 16.146.199.68 443`（默认 remote 仍是 IPv4 公网）。SK5 保持开启态。
- **TCP 首连 120s 超时跟进——未复现（5 次全部 1 秒内）**：5 次全新 TCP 首连全部 **0.2 秒** `TCP connection established`＋`Initialization Sequence Completed`。R7 的 120s 超时单次事件本轮未再出现（第七轮未复现）。切 TCP 前已按 live-9/live-10/live-11/live-12/live-13 教训先杀旧 UDP 客户端（PID 923112，tun0 消失确认）。
- S2-TCP（SK5 开）：新 TCP 客户端连上（20:29:02，tun0 10.8.0.2/24，PID 924500）；curl → 16.146.199.68；NTP → 48 字节 42.5ms/17.8ms；sing-box 日志 20:29:07 有 `outbound/socks[bought-sk5]: outbound connection to 34.160.111.145:80` 与 `outbound packet connection to 216.239.35.4:123`／`162.159.200.1:123`，dante 日志同窗口有 `tcp/accept` 与 `udp/udpassociate`——TCP+SK5 链路在 TCP 模式下同样成立。
- BUG-9（TCP 模式）：原始日志 `CLIENT_LIST,alice,10.200.0.2:40614,10.8.0.2,,4618,4429,2026-11-12 20:29:02,1794515342,UNDEF,5,0,AES-256-GCM`；面板 `/api/status` 的 `online_users`=**1**，`openvpn.detail.clients`=[{name: alice, real_address: 10.200.0.2:40614, virtual_address: 10.8.0.2, bytes_received: "4618", bytes_sent: "4429", connected_since: "2026-11-12 20:29:02"}]——逐字段一致。**BUG-9 第十六次复验在 UDP 与 TCP 两种模式下均修好**。

## 9. R19＋R20 的真机格 —— 通过（R19 机上 mock-KV 格；R20 存量形状＋心跳真机格）

### 9.0 环境与分层说明（先写清，不冒充）

- Worker 面无真实部署（P0-1/2/3 仍卡登录＋KV 占位），本节 R19 格全部是**机上 mock-KV 格**：探针在测试机上跑、mock KV 在内存里模拟 `queue:/sent:/cmd:` 三类键，Worker 代码走真实 `cloudflare/src/index.js` 全路由（BJ 版，sha256 `089bb32da319…`，与 §0 打包树一致，机上核对一致）。不是真实 Worker 部署，不冒充。
- 机上 node：v18.20.4（live-13 装的测试侧工具，不动产品）。node 18 两个坑：① `.js` 默认按 CommonJS 加载，`package.json {"type":"module"}` 须放在 index.js 向上能找到的位置（本轮初次放 tests/ 下不生效——node 从 index.js 向上找，移到 probes/ 根后解决，测试侧问题）；② 须加 `--experimental-global-webcrypto`（沙箱 node v24 自带全局 crypto，故沙箱跑不触发）。
- R20 格走真机上已安装的 egress/agent 代码（`/root/r14/ptree-machine`，sk5_manager.py sha256 `7727486677a2` 与已安装的 `/opt/ovpn-agent/egress/sk5_manager.py` 一致）。

### 9.1 R19 的 2 条（机上 mock-KV 格）—— 通过（12/12＋8/8）

- 非列表容器探针 `tests/r19_worker_nonlist_container.mjs`：**12 格全过，FAIL 0**（NL-01–NL-09 全部转绿；NL-10/NL-11 对照绿）。
- 下载探针 `tests/r19_worker_ovpn_download.mjs`：**8 格全过，FAIL 0**（DL-03 revoked、DL-04 expired 均 403；DL-02 无快照放行、DL-06 未知用户 404）。
- **R19-P2-1／P2-2 在机上 mock-KV 格上成立。**

### 9.2 R18 回归（机上 mock-KV 格＋Flask 对照）—— 通过

- BI 竞态探针 **15/15**、BI 畸形探针 **18/18**、BH 回归探针 **20/20**。
- R18 复现探针按预期翻转：竞态 **7/9**（2 红恰为 RACE-02 下发 A＋B、RACE-05 B 已 sent）；畸形 **9/13**（4 红恰为 M-01/02/03/06 均已落 failed，M-06  detail 为 `命令记录畸形，已隔离：记录不是 JSON 对象`）。
- Flask 面 BG 探针 **22/22**（打包树副本＋fixture CA/server，nobody 身份跑；探针文件 600 拒读，`chmod a+r` 后通过，测试侧问题，同 live-13）。

### 9.3 R20 的 2 条（真机）—— 通过

- R20 探针 `tests/r20_input_shapes.py`（机上 ptree-machine）：S1/S2 按预期翻转——`"port": true` 与 `1194.5` 均被 `_validate_stored` 诚实拒（`bad stored /tmp/…/sk5.json: port must be an integer 1-65535, got bool True`／`got float 1194.5`），不再渲染出 server_port 1／1194；S3–S5 控制格绿；S6 按预期翻转——列表形 sk5.json 下真实 `heartbeat_status()` 返回 `HB-OK {… 'openvpn_running': True, 'sk5_enabled': False}`，不再抛 AttributeError；S7 观察格绿。
- BK 新探针 `tests/bk_stored_shapes.py`：**8/8**（数字串 port 拒、两开关字符串拒、0/1 归一化、get_status 降级 config_error、current_egress_ip 回 None、port 0／70000 拒）。
- **真机活文件格**：把线上 `/etc/openvpn-sk5-panel/sk5.json` 的 port 临时改成 `true` 后，`/api/status` 仍 200，`sk5.config_error` 为 `bad stored /etc/openvpn-sk5-panel/sk5.json: port must be an integer 1-65535, got bool True`——不 500；恢复原文件后复查：enabled true、policy_routing_active true、config_error None，表 100 双路由在位。
- **观察（不立案）**：恢复后紧接着的一次 `/api/status` 仍显示旧 config_error 与 enabled false——查清为面板 `_cached_sk5_status()` 的 10 秒状态缓存（panel/app.py:1376，`_SK5_STATUS_CACHE_TTL = 10.0`，注释写明设计），下一查询即恢复正确值，非产品问题。

## 10. BM 的真机格 —— 层 1 通过（黑洞兜底成立）；层 2 失效，新 bug 1 个（R14-BUG-1，高）

### 10.1 杀 sing-box：流量黑洞、不回直连 —— 通过（R13-BUG-1 的泄漏签名消失）

- 链路启用态（SK5 开、TCP 443、TCP 客户端 PID 924500 在连）下 `systemctl stop openvpn-sk5-singbox`（inactive 确认）：**客户端 curl 立即 exit 28（超时），NTP UDP TimeoutError**——流量被黑洞，未改走直连。`ip route show table 100` 只剩 `blackhole default metric 200`（tun1 路由随 tun1 消失被内核删除）；tun1 不存在。
- 面板诚实：`/api/status` 的 `last_health` 为 `{"healthy": false, "action": "blackholed_kill_switch", "detail": "sing-box not running"}`（health.json 同款）；`sk5.singbox_running: false`。**R13-BUG-1 的泄漏签名（curl 回 16.146.199.68 exit 0）在修复后代码上未复现。**

### 10.2 新 bug：R14-BUG-1（高）——自愈重建的死 tun1 挡住 sing-box 重启，链路永久停在黑洞态

- **现象**：杀 sing-box 后约 20 秒内，健康检查的 `_repair_policy()` 重跑 policy-routing.sh enable——`ensure_tun1` 把 tun1 重新建了出来（死设备，`NO-CARRIER … state DOWN`），并重装了 `default via 10.9.0.1 dev tun1 linkdown` 路由。随后 `systemctl start openvpn-sk5-singbox` 立即 FATAL：`start inbound/tun[tun-in]: configure tun interface: file exists`（sing-box[926908]，20:34:53）；systemd `Restart=on-failure` 连试 5 次全撞同一错，`NRestarts=5` 触 StartLimitBurst 上限，单元落 `failed`（20:35:09），不再尝试。
- **影响**：链路永久停在黑洞态——流量安全（无泄漏，curl 持续 exit 28）、面板诚实报 `blackholed_kill_switch`，但**无自愈**：sing-box 再也起不来，直到人工 `ip link del tun1` ＋ `reset-failed` ＋重起。BM 宣称的“重启／健康检查时自动重装策略”第二层，在 sing-box 死亡这一正主场景下不成立——修好的是“死后不泄漏”，没修好“死后能回来”。
- **根因（代码面）**：`ensure_tun1`（policy-routing.sh:119-131）无条件建设备——sing-box 活着时它建设备是兜底；sing-box 死后健康检查调用它，等于抢在 sing-box 前面把设备占住。sing-box 的 tun inbound 建设备时不接受已存在的同名设备（`file exists` 即 FATAL，无 adopt 逻辑）。修复方向（供修复路）：自愈重装时**不得重建 tun1 设备**（只重装黑洞与 rule；tun1 路由等 sing-box 自己重建设备后再由下一档健康检查补），或重装前先删 `linkdown` 的死 tun1；二选一，须在真机上验“杀 sing-box → 黑洞 → systemd 自动重起成功 → 60 秒档内恢复走 SK5”全程无人干预。
- **诊断证实（人工恢复，全程实测）**：`reset-failed`＋`ip link del tun1`＋`systemctl start` 后 sing-box 立即干净启动（MainPID 927318，`sing-box started`，tun1 UP LOWER_UP）；随后健康检查 20:36:11 自动重装 tun1 路由，health 翻 `{"healthy": true, "action": "policy_repaired", "detail": "tcp_ok=True udp_ok=True egress=16.146.199.68; policy was missing, auto-repaired by this check"}`；客户端 curl 回 16.146.199.68 exit 0、NTP 48 字节 24.7ms；表 100 双路由在位；**同一 TCP 客户端 PID 924500 全程未断**（`Initialization Sequence Completed` 仅 1 次、SIGUSR1 0 行）——自愈的后半段（设备在位时补路由）本身是好的，坏的只是重建设备这一步。
- **定级**：高（非 P0：无泄漏、面板诚实上报、kill-switch 承诺成立；但 sing-box 一死即需人工干预才能恢复，断网保护的自愈承诺不成立，且 systemd 重试耗尽后彻底停摆）。
- **复现命令**：链路启用态 → `systemctl stop openvpn-sk5-singbox` → 等 60 秒健康检查档 → `systemctl start openvpn-sk5-singbox` → FATAL `file exists`，5 次后单元 failed。

## 11. headline 回归精选 —— 通过（6 项全过）

### 11.1 headline-1 首启一次 200 —— 通过（首启一次 200；10 次交替全一次 200，delta 恰 10）

- **首启（全新安装后第一次启用）**：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功，§6）。**R6-BUG-1 真机回归通过**。
- **10 次交替**（从禁用态起，奇数步全表单启用、偶数步单字段禁用，均为真实翻转）：10 步全部 **200**（一次成功），逐格 Started 计数各 **+1**（136→137→138→139→119→120→121→122→123→124）。计数口径：journalctl 里 `Started openvpn-sk5-singbox.service` 行数（live-8/9/10/11/12/13 同口径；`systemctl show NRestarts` 恒 0，不用它）。
- **计数口径注记（测试侧，非产品问题）**：第 4 步到第 5 步之间绝对计数从 139 掉到 119——journal 已 474.6M，journald vacuum 掉了 20 条最旧记录，绝对值首尾相减失效。改用窗口计数复核：20:37:20–20:41:40 窗口内 `Started` 行共 **11 条**＝setup 禁用 1 次＋10 次交替 10 次（并发那 1 次是窗口外第 12 条，20:41:40），与逐格 +1 一致，10 次交替 delta 恰 10 成立。

### 11.2 headline-3 并发启用 delta 恰 1 —— 通过（双 200，delta 恰 1）

- 从禁用态起，两路 `POST /api/sk5 {"host","port","enabled":true}` 同时发出 → **双 200**，Started 124→125（**delta 恰 1**，相邻两次读数之间无 vacuum），终态 enabled=true、policy=true、via=true、ip=16.146.199.68。AH 的 `_SK5_MUTATE_LOCK` 在真机并发路径上成立。**R7-BUG-3 真机终验通过**。

### 11.3 headline-5 policy-missing 诚实＋零重起修复 —— 通过（手动删策略，面板重开零重起修复）

- **诚实**：手动删表 100 的 tun1 路由后（本格为隔离面板路径、事先停了健康检查定时器——否则 60 秒档内定时器自愈会抢在面板重开前面，测试侧控制，事后已恢复定时器），面板 `/api/status`：`via_sk5=false`、`egress.ip=None`、`policy_routing_active=false`（enabled 仍 true），未谎称经 SK5、未谎称黑洞。
- **零重起修复**：全表单重开（`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}`）→ 200，收据 **`repaired: true`、`repair_detail: ["policy routing re-applied"]`**，Started 125→125（delta=0，**零重起补策略**）；恢复后 rule 100＋table 100 均在位，`policy_routing_active=true`、curl 回 16.146.199.68。UDP 客户端 PID 924500 全程未断（TCP 客户端）。
- 注记：本格删的是 tun1 路由（非 live-12 的手动删策略、非 live-13 的 sing-box 死亡衍生），修复路径与收据与 live-12/live-13 一致。

### 11.4 headline-6 verify.sh 双态 —— 通过（开态 18/0/4、关态 23/0/0）

- **开态**（SK5 开）：`bash verify.sh` → **PASS=18 FAIL=0 SKIP=4，VERIFY: ALL GREEN**（与 R5–R13 开态 18/0/4 一致；4 个 SKIP 为开态下跳过的 toggle 格，属设计）。
- **关态**（面板关 SK5 后 25 秒再跑）：`bash verify.sh` → **PASS=23 FAIL=0 SKIP=0，VERIFY: ALL GREEN**。R5-BUG-1 的关态天花板（22/1）继续不存在。关态跑完后 SK5 为禁用（verify.sh 的 enable 探针自带清理禁用；跑完紧接着的一次查询曾显示 enabled 真——又是 10 秒状态缓存，下一查询即为禁用，见 §9.3 观察）。

### 11.5 headline-7 前端真渲染 —— 通过（真渲染：0 项低于 4.5，最薄 4.92；零 JS 异常）

- 真机 headless Chromium 渲染（1440x900，`render/dashboard.png` 126,805 字节＋`render-contrast.json`）：标题 “OpenVPN + SK5 面板”、h1 “概览”；可见文本元素 **166 项，0 项低于 4.5**，最薄 **4.92**（“当前 .ovpn 的 remote 为公网地址 16.146.199.68，站外”，绿字白底）；30 项低于 7.0（目标值，非门禁底线；live-10/11/12/13 同款分布）。
- 控制台事件 4 条：3 条 verbose 级 DOM 建议（密码字段不在 form 内等）＋1 条 favicon.ico 404（缺 favicon 资产）；**零 JS 异常**（无 Uncaught／exception 条目）。favicon 404 与 live-10/11/12/13 同款，记观察、不立案。

### 11.6 headline-9 毒树默认重跑行级比对 —— 通过

- 毒树（`/root/r14/`，含毒 panel.db＋毒 agent_queue.json）默认重跑 `bash install.sh`（无任何 flag，日志 `/root/r14/install-rerun.log`，AN 新行 1 条、ERROR 0、完成横幅已印）。
- 行级比对（重跑前快照 `/root/r14/h9-before.json`）：admin 行**完全一致**（哈希仍为全新 `$2b$12$1vF6lXLXNJWi2ru…`，非毒 `$2b$12$tceqe…`）；login_attempts **一致**（0 行）；nodes **一致**（1 行 lightsail，name＋url 一致）；audit 35→36 行，**前 35 行完全一致**，新增 1 行仅为重跑后本轮登录（admin login ok，ip=127.0.0.1，合法）；server PID 不变（924218，服务未重起）；`agent_queue.json` 的 cmds 仍仅 1 条合法 get_status id，**毒的 3 条 init_pki 未入住**。
- **R8-BUG-1（毒树重跑销毁线上 panel.db）本轮终验通过。**

## 12. 结论与机器终态

- **格汇总**：§3 S0 通过｜§4 S0-agent 通过｜§5 S1（UDP）通过｜§6 S2（SK5 开）通过｜§7 S3（杀 dante）通过｜§8 S4（TCP 443）通过｜§9 R19 两条（机上 mock-KV 格 12/12＋8/8；R18 回归 15/15＋18/18＋20/20，复现翻转 7/9＋9/13，BG 22/22）与 R20 两条（R20 探针 S1/S2/S6 按预期翻转、BK 探针 8/8、活文件格 config_error 降级不 500）通过｜§10 BM 层 1 通过（杀 sing-box 黑洞、不回直连）、层 2 失效 **新 bug 1 个：R14-BUG-1（高，§10.2）**｜§11 headline-1/3/5/6/7/9 全部通过。**结论：R19、R20 的真机格全过；回归全过；新 bug 1 个高。** BJ 的 `kvArray` 归一化与下载守卫、BK 的 `_validate_stored`、BL 的心跳守卫在真机上成立；BM 的兜底黑洞成立（R13-BUG-1 的泄漏签名未复现），但自愈重建的死 tun1 挡住 sing-box 重启、链路永久停在黑洞态——本轮判**不能按“全部通过”收尾**，须修完 R14-BUG-1 再由下一轮复验。
- **R19-P2-1／P2-2 闭环（机上 mock-KV 格）**：非列表容器探针 12/12、下载探针 8/8。**Worker 面真实部署仍未验**（无真实 Worker 部署；P0-1/2/3 仍卡登录＋KV 占位，需用户决断，已问七次未复）。
- **回归**：S0 全新安装（毒包）、S0-agent（节点注册＋agent 安装＋命令链）、S1/S2/S3/S4（UDP 1194＋TCP 443 双模、SK5 TCP＋UDP 双栈、dante 死全断无回落且自动恢复、策略路由）与 headline-1/3/5/6/7/9 全部通过；U-5 致败格与 D13 并发安装不重复（live-10 已验，结论沿用）。**打包树（20:21:16 UTC）早于 BN 修复**——AUDIT-R21（04:30 CST 完工，差集 1 条 P2：R21-P2-1 队列文件整文件损坏静默丢命令，BN 路 04:34 已完工并主控核验）与 AUDIT-R22（04:34 派出）均在本轮打包之后，R21-P2-1 的真机格属 live-15，不在本轮；本轮机上探针亦为 R21 探针修净前的副本（r20 S6 同步缺 egress 的注记不影响本轮格子，S6 只用 agent/＋core/）。
- **诚实未验**：arm64 安装格；Worker 面真实部署（R19-BJ、R20-BK/BL、BM 均只到机上 mock-KV／沙箱探针／真机 egress 格）；Cloudflare 真实部署（P0-1/2/3，仍卡登录＋KV 占位，需用户决断，已问七次未复）；IPRoyal 1001 vs 9000 哪个是 SOCKS5 端口（面板默认 1001，待用户填真实 SK5 后核）。
- **机器终态**（2026-11-12 20:47 UTC）：TCP 443 模式；openvpn-server@server PID 924218、panel 8443（PID 921197）、sing-box MainPID 932023、ovpn-agent active、dante active；SK5 禁用（verify.sh 关态清理所致，表 100 为空）；用户 alice/bob 有效；CA `49682873442675F2BBB31E5C5E990FD9278C8FC4`；节点 lightsail 在线；ufw 4015 行；TCP 客户端 PID 924500 仍连在 netns vpntest（tun0 10.8.0.2，`Initialization Sequence Completed` 仅 1 次）。证据在 `/root/r14/`；打包 tarball `/root/ovpn-r14.tar.gz`（sha256 `116a5a890d2b333e7725f24b51c574a11b4588e4fa839bf0473f002a2889e9fb`）。
- **证据清单**（`/root/r14/`）：`install.log`／`install-rerun.log`（两次安装全日志）、`h9-before.json`（毒树重跑前快照）、`verify-open.log`／`verify-closed.log`（verify.sh 双态）、`token.txt`（节点 token，勿外传）、`probes/`（R19/R18/BI/BH/BG 探针＋BJ 版 index.js＋package.json，机上 mock-KV 用）、`ptree-machine/`（R20/BK 探针机上运行树）、`bg/`（BG 探针 22 格机上运行环境）、`fixtures/`（fixture CA/server）、`panel.py`／`netns.sh`／`tcp5-r14.sh`／`cdp-r14.py`／`alt10-r14.sh`（测试工具与日志）、`client-udp.log`／`client-tcp.log`／`client-tcp-try{1..5}.log`（客户端全日志）、`alice.ovpn`／`alice-tcp.ovpn`（完整配置文件，8612／8611 字节）、`render/dashboard.png`＋`render-contrast.json`（前端真渲染）。FLMX 同机进程（paneld、flmx-panel）全程未碰；证据 tarball `/root/ovpn-r7.tar.gz`～`/root/ovpn-r14.tar.gz` 均在位。

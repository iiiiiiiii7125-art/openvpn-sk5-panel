# OpenVPN 接 SK5 落地 · 真机复跑验证报告（第十三轮 R13）

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（BA/BB/BC/BD/BE/BG/BH/BI 修复后的最新树——本轮第一次验证 R18 的 2 条修复）。
> 验证人：真机复跑验证路（第十三轮）。日期：2026-11-12。
> **结论：R18 的 2 条真机格全过，S0–S4 与 headline 精选全过；新 bug 1 个（R13-BUG-1，高——sing-box 死亡静默回直连，断网保护承诺不成立）。**
> 前情：第十二轮见 [live-verify-R12.md](live-verify-R12.md)（全部通过、零新 bug；R16 的 1 条与 R17 的 1 条真机全过、S0–S4 与 headline 精选全过）；AUDIT-R18（261 行）判不能交付、差集 2 条（全 P2，双面 Worker），修复路 BI 已完工并主控核验；AUDIT-R19 与本轮并行在跑，03:23 CST 完工（224 行，判不能交付、差集 2 条全 P2 Worker 面；修复 BJ 路 03:28 完工并主控核验）；AUDIT-R20 亦与本轮并行，03:49 CST 完工（287 行，判不能交付、差集 2 条全 P2：R20-P2-1 存量 sk5.json port bool／float 被 int() 洗白进 sing-box 配置、R20-P2-2 agent 心跳读列表形 sk5.json 抛 AttributeError；修复 BK＋BL 两路 03:50 并行派出）——**本轮打包树（19:21:50 UTC）早于 BJ 与 BK/BL 修复，R19 与 R20 的真机格属 live-14，不在本轮**。

## 0. 树版本（本次装机所用）

| 文件 | mtime (UTC) | sha256（前 12 位） | 说明 |
|---|---|---|---|
| install.sh | 2026-11-12 16:46:54 | 3f050f037e7a | AZ 路（未动） |
| panel/app.py | 2026-11-12 18:38:12 | 204de1136cc5 | BG 路：poll 循环顶 `status != "queued": continue`＋report 非 sent 回 409（2754 行） |
| core/openvpn_manager.py | 2026-11-12 17:20:57 | 3b5d7dfe9ea1 | BB 路（未动） |
| agent/agent.py | 2026-11-12 16:46:20 | 7f999298df5b | AX 路（未动） |
| cloudflare/src/index.js | 2026-11-12 19:06:24 | 9b85049f4f64 | **BI 路：条件式清空＋`_sweepWorkerCmds`＋`toMs` 数值化（1234→1444 行）** |
| egress/policy-routing.sh | 2026-11-12 12:13:01 | 103a121bbdfe | AG 路（未动） |
| egress/sk5_manager.py | 2026-11-12 12:37:13 | 02de9d8a4908 | AJ 路（未动） |
| panel/templates/index.html | 2026-11-12 15:21:57 | 4f7dc697451c | AR 路（未动） |
| verify.sh | 2026-11-12 14:45:28 | 7867f557c6bb | 主控（未动） |
| verify-integration.sh | 2026-11-12 18:14:53 | 6ef6ba2db8b1 | BE 路：§7 两层同一格（常量值＋字典绑定） |
| egress/test-egress.sh | 2026-11-12 08:40:51 | d6db69ec0a6e | X 路（未动） |
| README.md | 2026-11-12 17:56:09 | 6154ecabe046 | BD 路（未动） |
| panel/README.md | 2026-11-12 17:54:19 | d565d49be62f | BD 路（未动） |
| docs/security.md | 2026-11-12 17:54:57 | 523e689f2736 | BD 路（未动） |
| cloudflare/server-mode.md | 2026-11-12 17:54:19 | 9dfad606bb9b | BD 路（未动） |
| cloudflare/README.md | 2026-11-12 17:54:19 | 7393d2b57e53 | BD 路（未动） |
| core/README.md | 2026-11-12 17:54:14 | c042e4b3d2fc | BD 路（未动） |
| docs/flmx-reference.md | 2026-11-12 17:55:47 | cc994f423a9b | BD 路（未动） |

树稳定检查：最新产品改动为 cloudflare/src/index.js（19:06:24 UTC），打包执行时刻 19:21:50 UTC，**稳定 15 分 26 秒**（满 15 分钟门；live-11 差 12 秒的教训未重犯）。其间只有 AUDIT-R19 的报告文件与本报告在写、产品文件无变动；`__pycache__` 为探针 import 产物、打包时剔除（安装子集不含 tests/）。打包时源码树 `panel/data/` 为空（`ls` 空）；毒 panel.db＋agent_queue.json 由 AE 的真实代码毒快照（`~/workspace/ae-tests/poison/`）注入打包副本，**源码树本身未被毒化**。

**打包（19:21:50 UTC）**：传包走 scp（R4–R12 同款）。`ovpn-r13.tar.gz`：41 条目，195,275 字节，sha256 `0c5e119483d89f97747fa7e49840e6fbf9dde462e4638a3ba5b325acf335d75b`（机上核对一致）；install.sh sha256 `3f050f037e7a4eba992716aff5d8f54ed746c2769c6fd224d55da696d3d468de`。清单与 R12 逐项一致（41/41 diff 空）。包内毒物核对：`panel/data/panel.db` 含 admin 行 1 条（哈希 `$2b$12$tceqe…`，表 `admin`）、`panel/data/agent_queue.json` 含 3 条 init_pki force+confirm（action 均为 init_pki）——与 R8 §6.2 的毒形一致。

## 1. 地面真值（Lightsail 现状，测试前实测，19:21 UTC）

- 机上是**第十二轮收尾态**：安装 #1＋headline-9 默认重跑后状态。五服务全部 active（openvpn PID 886611 TCP 443、panel PID 882013 8443、sing-box、agent、dante 127.0.0.1:11080）；SK5 禁用；节点 lightsail 已注册、last_seen 新鲜；用户 alice/bob 有效；ufw 启用、4015 行；CA 序列 `1736E0DA…`。
- 第十二轮残留全部在位，**重装前必须清除**：`/root/r12/` 测试产物在位；`/root/ovpn-r12.tar.gz`（毒包，证据，**勿删**）、`/root/ovpn-r11.tar.gz`、`/root/ovpn-r10.tar.gz`、`/root/ovpn-r9.tar.gz`、`/root/ovpn-r8.tar.gz`、`/root/ovpn-r7.tar.gz`、`/root/ovpn-r7b.tar.gz`、`/root/ovpn-r2.tar.gz` 在位；`/opt/openvpn-sk5-panel/` 为第十二轮装树；`/etc/openvpn-sk5-panel/` 含 admin.pass（0600）；`/etc/openvpn/server/server.conf` 为 `port 443 / proto tcp / server 10.8.0.0 255.255.255.0`。
- netns `vpntest` 仍在（live-12 收尾遗留）；TCP 客户端 PID 886958 仍连（live-12 终态）。
- FLMX 相关进程同机在跑（paneld、flmx-int2 paneld、flmx_agent、sing-box 1.14.4），**一律不碰**；`/root/flmx-panel` 不动。
- 注记：sing-box MainPID 现为 894019，live-12 收尾记为 891426——其间有一次重起（verify.sh 关态清理或健康检查定时器所致，属测试收尾／定时器行为，非产品异常；重装后以新 PID 为准）。

## 2. 清场（全新重装前，19:22 UTC）

- 先杀 live-12 遗留 TCP 客户端（精确 PID 886958，`kill`＋`kill -9` 确认消失）、删 netns `vpntest`（`ip netns list` 空）。
- 四服务已停（openvpn/panel/singbox/agent 全部 inactive，dante 保留，active）；无残留客户端进程。
- FORWARD 链删 tun0 产品规则 2 条（`-s/-d 10.8.0.0/24` 形状）、NAT POSTROUTING 的 `-s 10.8.0.0/24 -o ens5 MASQUERADE` 1 条；其余 ts-forward/DOCKER-USER/DOCKER-FORWARD/ufw 段不动。
- 状态已 wipe：`/root/openvpn-sk5-panel`、`/opt/openvpn-sk5-panel`、`/opt/ovpn-agent`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/ovpn-agent` 全删；sing-box 与 tun2socks 二进制已删（`find /usr/local/bin /usr/bin /opt -name "sing-box*" -o -name "tun2socks*"` 空，逼安装器走下载路径，复验版本校验）；`/root/r12/`、全部证据 tarball 保留未动。
- 清场后核对：无 tun0/tun1、无 1194/443/8443 监听、`/opt/openvpn-sk5-panel` 与 `/etc/openvpn-sk5-panel` 不存在。
- S0 安装已于 19:22 UTC 后台启动（`nohup bash install.sh`，日志 `/root/r13/install.log`，安装器 PID 895951）。

## 3. S0 基线：毒包安装 + 建服务 + 建用户 —— 通过（一次成功；AN 新行在位）

### 3.0 第一次安装（毒包，全新安装，UDP 1194 默认）—— 通过

- install.log：**0 个 ERROR**；sing-box 1.11.15 下载 `sha256 OK`、自报 `sing-box version 1.11.15`；tun2socks 2.7.0 下载 `sha256 OK`（`tun2socks-linux-amd64.zip: OK`，双锚核验）；完成横幅已印。
- **毒物未入住（AN 新行为）**：日志有新行 `[install] panel/ installed (panel/data/ excluded: …)`（1 条）；旧 `discarded shipped runtime file` 行 **0 条**；初始密码已生成并写入 `/etc/openvpn-sk5-panel/admin.pass`（0600）。
- 装后核对：`/opt/openvpn-sk5-panel/panel/data/` 仅含 panel.db，**agent_queue.json 文件不存在**（毒队列从未拷入）；panel.db 的 admin 行哈希为 `$2b$12$2ECgKfC7Y2caq…`，与毒哈希 `$2b$12$tceqe…` 不同——全新 admin 行；nodes 0、audit 1 行（全新库）。
- 五单元：openvpn/panel/singbox active，agent inactive（属预期，由 S0-agent 安装），sing-box 在跑；CA 序列 `0E665BBEC1ED87EB41AC89B8F2AB615D040745A4`（notBefore 2026-11-12 19:23:03，记下供 agent 轮询后对比）。
- ufw 回归格（AN 的 R8-BUG-2 反面）：机上 ufw 在位（`ufw status` 4015 行）——安装后 ufw 仍在，`ufw status` 仍 4015 行；iptables-persistent 未装（ufw 机跳过，属预期）。

### 3.1 S0 后半段：建服务确认＋建用户 —— 通过

- 面板登录 200；`/api/status` 200：openvpn running（UDP 1194，PID 896976），online_users 0，SK5 未启用，`singbox_running: true`，sk5 块 `policy_routing_active: false`。
- 默认 `.ovpn` remote 为 **16.146.199.68 1194**（IPv4 公网）。
- 用户：alice、bob 创建均 200；`GET /api/openvpn/users` 只列 alice、bob，alice 序列号 `ED090C923F8D0F42C6B2F2A4DB0B5706`、bob `950E7FA5C9B4BBC915F66395B2EC5F03`；`.ovpn` 下载 8612 字节（curl 直取完整文件，避开 panel.py 4000 字符截断坑），`proto udp / remote 16.146.199.68 1194`，含 2 个 CERTIFICATE 块。
- **观察（不立案）**：`/api/status` 的直接出口探测返回 IPv6 地址 `2600:1f13:14d:a300:7913:f273:997e:c8b8`（本机有 IPv6，探测走了 v6）；live-9 同格为 IPv4 16.146.199.68、live-10/live-11/live-12 同款 IPv6。数据面实测（S1/S2）仍以 IPv4 出口为准，面板 `egress.ip` 的 v4/v6 取值未作断言。

## 4. S0-agent：节点注册 + agent 安装 + 命令链 —— 通过（第二毒物 agent 侧终验通过）

- 注册：`POST /api/nodes {"name":"lightsail","panel_url":"https://172.26.15.152:8443"}` → 201，token 只存 `/root/r13/token.txt`（未写报告）。中途一次取 token 路径走偏：首 POST 已 201，`json.load` 被 panel.py 的 `201 ` 状态前缀绊住、`||` 回退又 POST 一次得 409“节点已存在”——删节点重注册、按首个 `{` 截取后取全 token（长 43），测试侧流程问题，非产品问题。
- 安装命令（面板两步走命令，按 agent/README 记载的流程执行；token 由文件读入）：`curl -ksSL https://172.26.15.152:8443/install-agent.sh`＋`install-agent.sh.sha256` 校验 `install-agent.sh: OK`＋`bash /tmp/install-agent.sh --panel-url … --token … --node-name 'lightsail'` → **EXIT=0**。bundle sha256 OK、`/etc/ovpn-agent/config.json` 0600、`ovpn-agent is ACTIVE (node=lightsail)`。
- poll：`GET /api/nodes` 的 `last_seen` 为 2026-11-12T19:26:53+00:00（新鲜），心跳合并 `last_status`（hostname/version/openvpn_running/sk5_enabled）；agent 日志 0 条 401/403、无 poll failed、无 init_pki。
- **毒 init_pki 未执行**：agent 上线并轮询后，CA 序列仍为 `0E665BBEC1ED87EB41AC89B8F2AB615D040745A4`（与安装时一致）；面板 `agent_queue.json` 现为 `{"queue": {"lightsail": []}, "cmds": {}, "ovpn": {}}`——init_pki 0 条。
- 命令链：`POST /api/cmd {"node":"lightsail","action":"get_status"}` → **202**（cmd_id 2a869d5b…）；约 1 秒后 `GET /api/cmd/<id>` → **done**，error null；result 含 openvpn running=true pid 896976（与面板一致）、sk5 enabled=false。

## 5. S1 直连态（UDP 1194）—— 通过（首次即通，零手工 FORWARD）

- 客户端（alice，netns vpntest，`--float`）：改 remote 为 LAN IP 172.26.15.152（R7 同款，公网 IP 发夹在 netns 内受限，非产品问题），**首次即通**，`Initialization Sequence Completed`（19:29:51），tun0 10.8.0.2/24，redirect-gateway 路由就位。PID 900005。
- 数据面（direct）：`curl ifconfig.me`（HTTP 与 HTTPS，--resolve 绕 MagicDNS）→ **16.146.199.68**；`dig @1.1.1.1 ifconfig.me` → 34.160.111.145 有回包；NTP UDP：216.239.35.4 回 **48 字节** 14.5ms、162.159.200.1 回 **48 字节** 6.0ms。UDP 数据面通过。
- **BUG-9 第十三次复验——修好（UDP 模式）**：部署态原始日志（逗号 v2，13 段）为 `CLIENT_LIST,alice,10.200.0.2:41407,10.8.0.2,,6355,13048,2026-11-12 19:29:51,1794511791,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users` = **1**；`clients`=[{name: alice, real_address: 10.200.0.2:41407, virtual_address: 10.8.0.2, bytes_received: "6355", bytes_sent: "13048", connected_since: "2026-11-12 19:29:51"}]——逐字段一致；`/api/openvpn/users` 的 alice `online: true`、bob `online: false`（本节实测）。
- 测试侧注记：一次 tssh 会话在 `sleep 65`（等状态文件刷）时断开（Broken pipe，exec 60 秒级上限），状态日志检查改分两次跑；断开未影响客户端与隧道。

## 6. S2 落地态（SK5 开）—— 通过（TCP+UDP 均走 SK5，双日志为证）

- 启用：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → 200（`policy_routing_active: true`）；`/api/sk5/test` → 200（tcp_ok，90.4ms；udp_ok，`mode: native`，native UDP ASSOCIATE + DNS to 1.1.1.1:53——非 TCP 承载冒充）。
- 路由（策略路由表 100）：`ip rule`（`from 10.8.0.0/24 lookup 100`）；表 100 `default via 10.9.0.1 dev tun1`；`ip route get 1.1.1.1 from 10.8.0.1` → `dev tun1 table 100`；tun1 UP、mtu 1400。
- 数据面（dante 本地测试 SK5，出口仍为本机 IP 16.146.199.68——属测试 SK5 的已知性质）：隧道内 curl ifconfig.me（HTTP 与 HTTPS，--resolve 绕 MagicDNS）→ **16.146.199.68**；NTP UDP：216.239.35.4 回 **48 字节** 35.5ms、162.159.200.1 回 **48 字节** 26.7ms（比直连态慢，符合 SK5 路径）。
- 双日志为证：sing-box 日志（19:32:24）明文记录 `outbound/socks[bought-sk5]: outbound connection to 34.160.111.145:80`、`:443`，以及 `outbound packet connection to 216.239.35.4:123` 与 `162.159.200.1:123`（inbound/tun[tun-in] 收到）——**TCP 与 UDP 均真实走了 SK5 出站**。

## 7. S3 断网保护（杀 dante）—— 通过（数据面全断、无直连回落、自动恢复、隧道不断）

- 杀 dante（`systemctl stop danted`，inactive）：客户端 TCP `curl --resolve … http://ifconfig.me` → **exit 56**（Recv failure），HTTPS → exit 35（SSL connect error，同样失败）；NTP UDP 到 216.239.35.4 → **TimeoutError**；**无直连回落**（curl 不是成功、是失败——fail-closed 成立）。隧道未断（同一客户端 PID 900005，tun0 仍在，`Initialization Sequence Completed` 仅 1 次）。
- 面板 `/api/status`：kill 期间 **egress.ip = null**（`{'error': None, 'ip': None, 'latency_ms': None, 'via_sk5': True}` 形状同 live-9/live-10/live-11/live-12），诚实报空。
- 恢复（`systemctl start danted`，active）：客户端 TCP 立即回 **16.146.199.68**，NTP 回 **48 字节** 45.7ms。隧道全程未断：同一 PID 900005，client.log 里 `Initialization Sequence Completed` 仅出现 1 次、SIGUSR1 0 行——无重连、无重拨。
- 口径注记（设计，非缺陷）：kill 期间 `dig @1.1.1.1` 仍有回包——sing-box 路由规则 `protocol dns / port 53 → direct`（见 `/etc/openvpn-sk5-panel/sing-box.json`），DNS 默认走直连、不经 SK5，是文档已定设计；断网保护覆盖的是 TCP/UDP 数据面，DNS 不在黑洞范围内。
- **本节只覆盖 SK5 死亡（dante 死）情形。sing-box 本体死亡情形见 §11 R13-BUG-1——本轮首次实测，断网保护在此情形下不成立。**

## 8. S4 TCP 备模式（443）—— 通过（BUG-14 修好，S1/S2 各重跑一次）

- **BUG-14 修好**：`POST /api/openvpn/server {"proto":"tcp","port":443,"allow_port_change":true}` → **HTTP 200**。`POST /api/openvpn/restart` → 200（新 pid 902628）。TCP 443 监听，UDP 1194 监听消失，`/api/status` 为 proto=tcp port=443 running=true；新下载的 alice.ovpn 为 `proto tcp / remote 16.146.199.68 443`（默认 remote 仍是 IPv4 公网）。SK5 保持开启态。
- **TCP 首连 120s 超时跟进——未复现（5 次全部 1 秒内）**：5 次全新 TCP 首连全部 **1 秒内** `TCP connection established`＋`Initialization Sequence Completed`（实测各约 0.2 秒，轮询粒度 0.25 秒）。R7 的 120s 超时单次事件本轮未再出现（第六轮未复现）。切 TCP 前已按 live-9/live-10/live-11/live-12 教训先杀旧 UDP 客户端（PID 900005，tun0 消失确认）。中途一次测试侧失误：tcp5.sh 的 sed 仍写 `1194`、未匹配 TCP 文件的 `443`，首轮 5 次全撞公网 IP 发夹超时（10 秒等满、0 次完成）——改 sed 为 `443`→LAN IP 后重跑，5 次全通；测试侧流程问题，非产品问题。
- S2-TCP（SK5 开）：新 TCP 客户端连上（19:37:56，tun0 10.8.0.2/24，PID 903751）；curl → 16.146.199.68；NTP → 48 字节 28.7ms/19.9ms；dante 日志同窗口有 `udp/udpassociate`——TCP+SK5 链路在 TCP 模式下同样成立。
- BUG-9（TCP 模式）：原始日志 `CLIENT_LIST,alice,10.200.0.2:59428,10.8.0.2,,4507,4388,2026-11-12 19:37:56,1794512276,UNDEF,5,0,AES-256-GCM`；面板 `/api/status` 的 `online_users`=**1**，`openvpn.detail.clients`=[{name: alice, real_address: 10.200.0.2:59428, virtual_address: 10.8.0.2, bytes_received: "4507", bytes_sent: "4388", connected_since: "2026-11-12 19:37:56"}]——逐字段一致。**BUG-9 第十四次复验在 UDP 与 TCP 两种模式下均修好**。

## 9. R18 两条的机上 mock-KV 格 —— 通过（BI 修复成立；真实 Worker 部署仍未验）

### 9.0 环境与分层说明（先写清，不冒充）

- Worker 面无真实部署（P0-1/2/3 仍卡登录＋KV 占位），本节全部格子是**机上 mock-KV 格**：探针在测试机上跑、mock KV 在内存里模拟 `queue:/sent:/cmd:` 三类键，Worker 代码走真实 `cloudflare/src/index.js` 全路由。不是真实 Worker 部署，不冒充。
- 机上 node：本机原无 node，为跑探针经 apt 装 nodejs **18.20.4**（测试侧工具，不动产品）。node 18 有两个坑，均已定位并写明：① `.js` 默认按 CommonJS 加载、Worker 文件是 ESM（`export default`），探针目录补 `package.json {"type":"module"}` 后解决；② node 18 无全局 `crypto`（Worker 的 `sha256Hex` 要 `crypto.subtle`），须加 `--experimental-global-webcrypto`（沙箱 node 为 v24.22.1，自带全局 crypto，故沙箱跑不触发）。
- **被测文件版本（关键）**：探针用的 index.js 取自 `/tmp/r19/ptree/cloudflare/src/index.js`，sha256 `9b85049f4f64…`（BI 版，与 §0 打包树一致，机上核对一致）。活树当时的 index.js 已被并行在跑的 BJ 路改到 19:25:36（R19 修复，`Array.isArray` 归一化），不是本轮被测版本——本轮不用它，只用哈希核对过的 BI 版。BJ 的改动不进本轮打包树（打包 19:21:50 UTC，早于 BJ），R19 的 2 条真机格属 live-14。

### 9.1 BI 修复探针（机上 mock-KV）—— 通过（15/15＋18/18）

- 竞态探针 `tests/bi_worker_queue_race.mjs`：**15 格全过，FAIL 0**（poll 窗口内入队不丢失——B 在 poll 1 经孤儿回收即下发；孤儿 queued／sent 均被回收；缺 status／bogus／非对象／缺 node 均落 failed；sent_at "abc" 非幂等首超时即 failed；SAFE 重投 retries=1；吊销救畸形记录；cmd_get 读路径即见 failed）。
- 畸形探针 `tests/bi_worker_malformed.mjs`：**18 格全过，PASS 18 FAIL 0**（末格 BI-M-10：revoke 救畸形记录，bogus → failed，revoke=200）。
- **BI 的两条在机上 mock-KV 格上成立。**

### 9.2 R18 复现探针按预期翻转 —— 通过（7/9＋9/13，翻转格逐项核对）

- 竞态复现 `tests/r18_worker_queue_race.mjs`：**7/9**，2 个 FAIL 恰为预期翻转格——RACE-02：poll 下发了 A 与 B（`dispatched=["0a35b42e…","8091aa97…"]`，B 在 poll 1 即被下发而非丢失）；RACE-05：B 记录 `status=sent`（未卡 queued）。其余 7 格绿。
- 畸形复现 `tests/r18_worker_malformed.mjs`：**9/13**，4 个 FAIL 恰为预期翻转格——M-01（缺 status 已标 failed）、M-02（"bogus" 已标 failed）、M-03（sent_at 非数值已标 failed，NaN 缺口关闭）、M-06（非对象记录已标 failed，error="命令记录畸形，已隔离：记录不是 JSON 对象"）。对照格 M-04/M-05（数值型 sent_at 超时路径）仍绿。
- **R18-P2-1／P2-2 的复现探针在修复后按预期翻转，无超范围红格。**

### 9.3 BH 回归探针（机上 mock-KV）—— 通过（20/20）

- `tests/bh_worker_poll_guard.mjs`：**20 格全过，FAIL 0**（failed 命令不下发、陈旧 poll 不重下发、queued 回执 409、正常下发一次翻 sent、超时回队／标失败、重复回执 409）。

### 9.4 Flask 面同族对照（机上）—— 通过（22/22，竞态缺口是 Worker 面独有）

- `tests/r18_bg.py`（BG 探针，Flask 面 poll／report 守卫）：**22 格全过，FAIL 0**。运行环境：被测树取打包树副本（`/tmp/r13-bg/ptree`，panel/app.py sha256 `204de1136cc5`＝BG 版）；系统 python3.11＋flask 3.1.3／bcrypt；fixture CA／server 目录自沙箱 `/tmp/r17/fixture-*` 原样拷上机；nobody 身份跑（探针文件权限曾 600 拒读，`chmod a+r` 后通过，测试侧问题）。
- Flask 面在并发 poll 下无命令丢失（`_QUEUE_LOCK` 覆盖 load→save 全程，单进程）——**R18-P2-1 的竞态缺口是 Worker 面独有，Flask 面本就安全**，与 R18 §3 的定性一致。

## 10. headline 回归精选 —— 通过（6 项全过）

### 10.1 headline-1 首启一次 200 —— 通过（首启一次 200；10 次交替全一次 200，delta 恰 10）

- **首启（全新安装后第一次启用）**：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功，§6）。**R6-BUG-1 真机回归通过**。
- **10 次交替**（从禁用态起，奇数步全表单启用、偶数步单字段禁用，均为真实翻转）：10 步全部 **200**（一次成功），Started 111→121（**delta 恰 10**，每步一次重起），终态禁用。计数口径：journalctl 里 `Started openvpn-sk5-singbox.service` 行数（live-8/9/10/11/12 同口径；`systemctl show NRestarts` 恒 0，不用它）。

### 10.2 headline-3 并发启用 delta 恰 1 —— 通过（双 200，delta 恰 1）

- 从禁用态起，两路 `POST /api/sk5 {"host","port","enabled":true}` 同时发出 → **双 200**，Started 121→122（**delta 恰 1**），终态 enabled=true、policy=true、via=true、ip=16.146.199.68。AH 的 `_SK5_MUTATE_LOCK` 在真机并发路径上成立。**R7-BUG-3 真机终验通过**。

### 10.3 headline-5 policy-missing 诚实＋零重起修复 —— 通过（sing-box 死后衍生的 policy-missing 态同样修复）

- **诚实**：sing-box 死后重启、table 100 为空（§11 过程），面板 `/api/status`：`via_sk5=false`、`egress.ip=None`、error=**“SK5 已启用但策略路由未生效，出口未经过 SK5”**、`policy_routing_active=false`（enabled 仍 true）；60 秒健康检查写 health.json：`{"healthy": false, "action": "policy_missing", "detail": "policy routing not applied; policy routing is not applied, VPN traffic egresses direct (not blackholed) until the chain is repaired (re-enable via the panel)", "checked_at": "2026-11-12T19:34:03Z"}`——诚实报缺策略、直言流量走直连，未谎称经 SK5、未谎称黑洞。
- **零重起修复**：全表单重开（`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}`）→ 200，收据 **`repaired: true`、`repair_detail: ["policy routing re-applied"]`**，Started 110→110（delta=0，**零重起补策略**）、MainPID 901406 不变；恢复后 rule 100＋table 100 均在位，`policy_routing_active=true`、curl 回 16.146.199.68。UDP 客户端 PID 900005 全程未断。
- 注记：本次 policy-missing 由 sing-box 死亡衍生（非 live-12 的手动删策略），修复路径与收据与 live-12 一致。修复只补策略，不解决 §11 的根因（sing-box 再死仍会静默回直连）。

### 10.4 headline-6 verify.sh 双态 —— 通过（开态 18/0/4、关态 23/0/0）

- **开态**（SK5 开）：`bash verify.sh` → **PASS=18 FAIL=0 SKIP=4，VERIFY: ALL GREEN**（与 R5–R12 开态 18/0/4 一致；4 个 SKIP 为开态下跳过的 toggle 格，属设计）。
- **关态**（面板关 SK5 后 25 秒再跑）：`bash verify.sh` → **PASS=23 FAIL=0 SKIP=0，VERIFY: ALL GREEN**。R5-BUG-1 的关态天花板（22/1）继续不存在。关态跑完后 SK5 为禁用（verify.sh 的 enable 探针自带清理禁用）。

### 10.5 headline-7 前端真渲染 —— 通过（真渲染：0 项低于 4.5，最薄 4.92；零 JS 异常）

- 真机 headless Chromium 渲染（1440x900，`render/dashboard.png` 122,284 字节＋`render-contrast.json`）：标题 “OpenVPN + SK5 面板”、h1 “概览”；可见文本元素 **156 项，0 项低于 4.5**，最薄 **4.92**（“当前 .ovpn 的 remote 为公网地址 16.146.199.68，站外”，绿字白底）；27 项低于 7.0（目标值，非门禁底线；live-10/11/12 同款分布）。
- 控制台事件 4 条：3 条 verbose 级 DOM 建议（密码字段不在 form 内等）＋1 条 favicon.ico 404（缺 favicon 资产）；**零 JS 异常**（无 Uncaught／exception 条目）。favicon 404 与 live-10/11/12 同款，记观察、不立案。

### 10.6 headline-9 毒树默认重跑行级比对 —— 通过

- 毒树（`/root/r13/install-src/openvpn-sk5-panel`，含毒 panel.db＋毒 agent_queue.json）默认重跑 `bash install.sh`（无任何 flag，日志 `/root/r13/install-rerun.log`，AN 新行 1 条、ERROR 0、完成横幅已印）。
- 行级比对（重跑前快照 `/root/r13/h9-before.json`）：admin 行**完全一致**（哈希仍为全新 `$2b$12$2ECgKfC7Y2caq…`，非毒 `$2b$12$tceqe…`）；login_attempts **一致**（0 行）；nodes **一致**（1 行 lightsail）；audit 37→38 行，**前 37 行完全一致**，新增 1 行仅为重跑后本轮登录（admin login ok，合法）；server PID 不变（902628，服务未重起）；`agent_queue.json` 的 cmds 仍仅 1 条合法 get_status id，**毒的 3 条 init_pki 未入住**。
- **R8-BUG-1（毒树重跑销毁线上 panel.db）本轮终验通过。**

## 11. 新 bug：R13-BUG-1（高）——sing-box 死亡静默回直连，断网保护承诺不成立

### 11.1 现象（两次独立复现，数字实测）

- 链路启用态（SK5 开、table 100 在位、流量走 SK5）下 `systemctl stop openvpn-sk5-singbox`（inactive 确认）：**客户端 curl 立即回 16.146.199.68（exit 0），NTP UDP 回 48 字节**——流量悄悄改走直连，未断网、未黑洞。
- 第二次独立复现（stop 后 2 秒再查）：sing-box inactive、tun1 不存在、**table 100 为空**、主表 `default via 172.26.0.1 dev ens5`，curl 仍回 16.146.199.68 exit 0。
- sing-box 重启后（`systemctl start`，active，MainPID 901406）：table 100 **仍为空**、`policy_routing_active: false`（enabled 仍 true）、curl 仍走直连——**无自愈**，链路永久静默直连，直到人工重开才修复（§10.3）。

### 11.2 机制（内核行为，与文档模型相反）

- table 100 的唯一路由是 `default via 10.9.0.1 dev tun1`——**设备绑定路由**。sing-box 一死，tun1 消失，内核**删除**该路由（不是把它留成死路由）；table 100 变空表；`from 10.8.0.0/24 lookup 100` 命中后查无路由，**落回主表**走 ens5 直连。空表不丢包、只落回——文档的模型（“路由死了→无路可走→丢包”）在内核行为上是错的。
- 代码面自认：`check_health()` 把“策略缺失”与“黑洞”分两档——策略在位＋链死才 `blackholed_kill_switch`；策略缺失则 `policy_missing`，detail 直言 “VPN traffic egresses direct (not blackholed)”（sk5_manager.py:978-981、:1036-1041）。即代码知道策略缺失＝直连，但**没有任何路径在 sing-box 死亡时补黑洞或重装策略**——健康检查只上报、不修复（fail_open=false 时无动作）；systemd 的 `Restart=on-failure`（RestartSec=3）只复活 sing-box 本体，不重装 table 100 路由。
- 修复方向（供修复路）：enable 时在 table 100 里再装一条与设备无关的兜底黑洞路由（如 `blackhole default metric 200`），tun1 路由在时优先走它，tun1 一死即落黑洞而非落回主表；或 sing-box 重启／健康检查发现策略缺失时自动重装策略（不止于上报）。

### 11.3 影响与定性

- **承诺对照**：README.md:156 与 egress/README.md:117 均写 “sing-box 或 SK5 一死，VPN 用户流量无路可走、直接丢包 —— **绝不会悄悄改走直连暴露真实出口 IP**”；sk5_manager.py:81 注释与 disable() docstring 同款断言。实测 sing-box 死亡情形与承诺相反。
- **影响**：断网保护是本产品的 headline 安全特性（默认 fail-closed）；买 SK5 的目的正是隐藏中转机真实出口 IP。sing-box 崩溃／被杀后，用户流量在无任何告警的情况下改走直连暴露真实 IP，且重启后永久保持直连（只报 `policy_routing_active: false` 与 health.json 的 policy_missing，不阻断流量）。面板诚实上报（非谎报），但流量本身静默回落——安全承诺不成立。
- **为什么前 12 轮没抓到**：S3 历轮只杀 dante（SK5 死）——此时 tun1＋table 100 完好，流量确实黑洞；sing-box 本体死亡情形从未真机跑过。本轮 S3 误杀 sing-box 才撞见（测试侧走偏，产品侧真 bug）。
- **定级**：高（非 P0：面板诚实上报 policy_missing、非谎报；dante 死仍正确黑洞；触发需 sing-box 崩溃／被杀，属低频事件；但安全承诺失效＋静默暴露＋无自愈，超 P2）。
- **复现命令**：链路启用态 → `systemctl stop openvpn-sk5-singbox` → `ip route show table 100`（空）→ netns 内 `curl --resolve ifconfig.me:80:… http://ifconfig.me` 回 16.146.199.68 exit 0（应为失败）。

## 12. 结论与机器终态

- **格汇总**：§3 S0 通过｜§4 S0-agent 通过｜§5 S1（UDP）通过｜§6 S2（SK5 开）通过｜§7 S3（杀 dante）通过｜§8 S4（TCP 443）通过｜§9 R18 两条（BI 修，机上 mock-KV 格 15/15＋18/18；复现探针按预期翻转 7/9＋9/13；BH 20/20；Flask 对照 BG 22/22）通过｜§10 headline-1/3/5/6/7/9 全部通过。**新 bug 1 个：R13-BUG-1（高，§11）。**
- **结论：R18 的 2 条真机格全过；回归全过；新 bug 1 个高。** BI 的 Worker 队列竞态修复与畸形 sweep 修复在机上 mock-KV 格上成立，Flask 面同族对照 22/22 证明竞态缺口 Worker 面独有。但 S3 误杀 sing-box 撞见 R13-BUG-1——断网保护承诺在 sing-box 死亡情形下不成立（静默回直连、无自愈），与 README 的“绝不会悄悄改走直连”相反；本轮判**不能按“全部通过”收尾**，须修完 R13-BUG-1 再由下一轮复验。
- **R18-P2-1／P2-2 闭环（机上 mock-KV 格）**：BI 竞态探针 15/15、畸形探针 18/18；R18 复现探针按预期翻转（竞态 7/9，RACE-02 下发 A＋B、RACE-05 B 已 sent；畸形 9/13，M-01/02/03/06 均已落 failed）；BH 回归 20/20；Flask 面 BG 22/22。**Worker 面真实部署仍未验**（无真实 Worker 部署；P0-1/2/3 仍卡登录＋KV 占位，需用户决断，已问六次未复）。
- **回归**：S0 全新安装（毒包）、S0-agent（节点注册＋agent 安装＋命令链）、S1/S2/S3/S4（UDP 1194＋TCP 443 双模、SK5 TCP＋UDP 双栈、dante 死全断无回落且自动恢复、策略路由）与 headline-1/3/5/6/7/9 全部通过；U-5 致败格与 D13 并发安装不重复（live-10 已验，结论沿用）。R19 与 R20 的真机格属 live-14（打包树早于 BJ 与 BK/BL 修复）。
- **诚实未验**：arm64 安装格；Worker 面真实部署（R18-BI、R19-BJ、R20-BK/BL 均只到机上 mock-KV／沙箱探针）；Cloudflare 真实部署（P0-1/2/3，仍卡登录＋KV 占位，需用户决断，已问六次未复）；IPRoyal 1001 vs 9000 哪个是 SOCKS5 端口（面板默认 1001，待用户填真实 SK5 后核）。
- **机器终态**（2026-11-12 19:47 UTC）：TCP 443 模式；openvpn-server PID 902628、panel 8443（PID 897099）、sing-box MainPID 908457（毒树重跑后重起）、ovpn-agent active、dante active；SK5 禁用（verify.sh 关态清理所致）；用户 alice/bob 有效；CA `0E665BBEC1ED87EB41AC89B8F2AB615D040745A4`；节点 lightsail 在线；ufw 4015 行；TCP 客户端 PID 903751 仍连在 netns vpntest（tun0 10.8.0.2）。证据在 `/root/r13/`；打包 tarball `/root/ovpn-r13.tar.gz`（sha256 `0c5e119483d89f97747fa7e49840e6fbf9dde462e4638a3ba5b325acf335d75b`）。
- **证据清单**（`/root/r13/`）：`install.log`／`install-rerun.log`（两次安装全日志）、`h9-before.json`（毒树重跑前快照）、`verify-open.log`／`verify-closed.log`（verify.sh 双态）、`token.txt`（节点 token，勿外传）、`probes/`（BI/BH/R18 五套 .mjs 探针＋BI 版 index.js＋package.json，机上 mock-KV 用）、`/tmp/r13-bg/`（BG 探针 22 格机上运行环境：打包树副本 ptree＋fixture CA/server＋r18_bg.py）、`panel.py`／`netns.sh`／`tcp-tries.sh`／`tcp5.sh`／`cdp.py`／`alt10.sh`／`alt10.log`（测试工具与日志）、`client-udp.log`／`client-tcp.log`／`client-tcp-try{1..5}.log`（客户端全日志）、`alice.ovpn`／`alice-tcp.ovpn`（完整配置文件，8612／8611 字节）、`render/dashboard.png`＋`render-contrast.json`（前端真渲染）。FLMX 同机进程（paneld、flmx-panel）全程未碰；证据 tarball `/root/ovpn-r7.tar.gz`～`/root/ovpn-r13.tar.gz` 均在位。

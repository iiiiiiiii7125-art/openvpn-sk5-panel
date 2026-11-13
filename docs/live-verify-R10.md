# OpenVPN 接 SK5 落地 · 真机复跑验证报告（第十轮 R10）

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（AW/AX/AY/AZ 修复后的最新树——本轮第一次验证 R13 的 7 条修复）。
> 验证人：真机复跑验证路（第十轮）。日期：2026-11-12。
> **结论：全部通过，新 bug 0 条。** S0–S4、R13 七条真机格、headline-1～9 全过；R13 的 7 条在真机上全部关闭，历史问题无一复发。未验：Cloudflare 真实部署（P0-1/2/3）、SK5 真实 IPRoyal 端口（1001 vs 9000）。
> 前情：第九轮见 [live-verify-R9.md](live-verify-R9.md)（全部通过、零新 bug；R8-BUG-1/R8-BUG-2 真机验收通过）；AUDIT-R13（341 行）判不能交付、差集 7 条（全 P2），修复路 AW/AX/AY/AZ 已完工并主控核验；AUDIT-R14 与本轮并行在跑。

## 0. 树版本（本次装机所用）

| 文件 | mtime (UTC) | sha256（前 12 位） | 说明 |
|---|---|---|---|
| install.sh | 2026-11-12 16:46:54 | 3f050f037e7a | AZ 路：OVPN_SUBNET 非默认值直接 die（R13-P2-6 选 a，1082 行） |
| panel/app.py | 2026-11-12 16:47:08 | aebd74920f81 | AW 路：sent_at 可解析性校验标 failed＋三下载路径统一 403（2694 行） |
| core/openvpn_manager.py | 2026-11-12 16:46:20 | 02b7431297e6 | AX 路：port 默认值合并改 `port is None` 显式判定（1542 行） |
| agent/agent.py | 2026-11-12 16:46:20 | 7f999298df5b | AX 路：`_as_int` 先拒 bool／float（922 行） |
| cloudflare/src/index.js | 2026-11-12 16:45:26 | e40fe4d7d8d0 | AY 路：畸形登录体 400 不记限流（1221 行） |
| egress/policy-routing.sh | 2026-11-12 12:13:01 | 103a121bbdfe | AG 路（未动） |
| egress/README.md | 2026-11-12 12:16:15 | 63f38f69d7fc | AG 路（未动） |
| egress/sk5_manager.py | 2026-11-12 12:37:13 | 02de9d8a4908 | AJ 路（未动） |
| panel/templates/index.html | 2026-11-12 15:21:57 | 4f7dc697451c | AR 路（未动） |
| verify.sh | 2026-11-12 14:45:28 | 7867f557c6bb | 主控（未动） |
| verify-integration.sh | 2026-11-12 09:35:55 | 7e040ea3ee4a | AD（未动） |
| egress/test-egress.sh | 2026-11-12 08:40:51 | d6db69ec0a6e | X 路（未动） |
| README.md | 2026-11-12 16:46:57 | 33f530b9fa71 | AZ 路：:66 OVPN_SUBNET 诚实后果 |
| panel/README.md | 2026-11-12 16:46:57 | 2c9c5e6e43e7 | AZ 路：:57-58 同族补行 |
| docs/security.md | 2026-11-12 16:47:16 | da5277cb0438 | AW 路：:12 补 sent_at 可解析前提 |
| cloudflare/server-mode.md | 2026-11-12 16:50:36 | 245e0d448b54 | AW 路：:21 补 sent_at 可解析前提 |
| docs/flmx-reference.md | 2026-11-12 16:47:28 | ee8ded22f7ed | AZ 路：9 行钉位删／改未抄（待定） |

树稳定检查：17:06:00 核查时最新产品改动为 cloudflare/server-mode.md（16:50:36），**稳定 15 分 24 秒，门过**（其间只有 AUDIT-R14 的报告文件在写，产品文件无变动；`__pycache__` 17:00:22 为探针 import 产物、打包时剔除）。打包时源码树 `panel/data/` 为空（`ls` 空）；毒 panel.db＋agent_queue.json 由 AE 的真实代码毒快照（`~/workspace/ae-tests/poison/`）注入打包副本，**源码树本身未被毒化**。

**打包（17:06 UTC）**：传包走 scp（R4–R9 同款）。`ovpn-r10.tar.gz`：41 条目，191,347 字节，sha256 `f23eba068b34ee9ca45a637544fb7afaa829202fe3751ca1e90bc3f8527ad37c`（机上核对一致）；install.sh sha256 `3f050f037e7a4eba992716aff5d8f54ed746c2769c6fd224d55da696d3d468de`。包内毒物核对：`panel/data/panel.db` 含 admin 行 1 条、`panel/data/agent_queue.json` 含 3 条 init_pki force+confirm（action 均为 init_pki）——与 R8 §6.2 的毒形一致。

## 1. 地面真值（Lightsail 现状，测试前实测，17:01 UTC）

- 机上是**第九轮收尾态**：安装 #3＋headline-9 默认重跑后状态。五服务全部 active（openvpn PID 802368 UDP 1194、panel PID 802504 8443、sing-box、agent、dante 127.0.0.1:11080）；SK5 禁用，online_users 0；节点 lightsail 已注册、agent 正常轮询；用户 alice、bob 均 valid；ufw 启用中，`ufw status` 4015 行（2000 条原规则＋既存＋1194/8443）；CA 序列 `2261BCCC…`；admin 哈希 `$2b$12$ydqZ…`。
- 第九轮残留全部在位，**重装前必须清除**：
  - `/root/r9/` 测试产物在位（52 个文件，panel.py、netns-setup.sh、probe.sh、cdp-r9.py、install/install2/install3 等）；
  - `/root/ovpn-r9.tar.gz`（毒包，证据，**勿删**）、`/root/ovpn-r8.tar.gz`、`/root/ovpn-r7.tar.gz`、`/root/ovpn-r7b.tar.gz`、`/root/ovpn-r2.tar.gz` 在位；
  - `/opt/openvpn-sk5-panel/` 为第九轮装树；`/etc/openvpn-sk5-panel/` 含 admin.pass（0600）；`/etc/openvpn/server/server.conf` 为 `port 1194 / proto udp / server 10.8.0.0 255.255.255.0`。
- netns 已空（第九轮收尾已删 `vpntest`）；无残留客户端进程。
- FLMX 相关进程同机在跑（paneld、flmx-int2 paneld、flmx_agent、sing-box 1.14.4），**一律不碰**；`/root/flmx-panel` 不动。

## 2. 清场（全新重装前，17:06–17:07 UTC）

- 四服务已停（openvpn/singbox/panel/agent 全部 inactive，dante 保留，active）；无残留客户端进程、无 netns。
- FORWARD 链删 tun0 产品规则 2 条（`-s/-d 10.8.0.0/24` 形状）、NAT POSTROUTING 的 `-s 10.8.0.0/24 -o ens5 MASQUERADE` 1 条；其余 ts-forward/DOCKER-USER/DOCKER-FORWARD/ufw 段不动。
- 状态已 wipe：`/root/openvpn-sk5-panel`、`/opt/openvpn-sk5-panel`、`/opt/ovpn-agent`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/ovpn-agent` 全删；sing-box 与 tun2socks 二进制已删（逼安装器走下载路径，复验版本校验）；`/root/r9/`、全部证据 tarball 保留未动。
- 清场后核对：无 tun0/tun1、无 1194/443/8443 监听、`/opt/openvpn-sk5-panel` 与 `/etc/openvpn-sk5-panel` 不存在。
- S0 安装已于 17:07 UTC 后台启动（`nohup bash install.sh`，日志 `/root/r10/install.log`，安装器 PID 830501）。

## 3. S0 基线：毒包安装 + 建服务 + 建用户 —— 通过（一次成功；R7-BUG-2＋第二毒物终验通过，AN 新行在位）

### 3.0 第一次安装（毒包，全新安装，UDP 1194 默认）—— 通过

- install.log：**0 个 ERROR**；sing-box 1.11.15 下载 `sha256 OK`、自报 `sing-box version 1.11.15`；tun2socks 2.7.0 下载 `sha256 OK`——两次版本校验均一次通过。
- **毒物未入住（AN 新行为）**：日志有新行 `[install] panel/ installed (panel/data/ excluded: …)`（1 条）；旧 `discarded shipped runtime file` 行 **0 条**；**完成横幅已印**；初始密码已生成并写入 `/etc/openvpn-sk5-panel/admin.pass`（0600）。
- 装后核对：`/opt/openvpn-sk5-panel/panel/data/` 仅含 panel.db，**agent_queue.json 文件不存在**（毒队列从未拷入）；panel.db 的 admin 行哈希为 `$2b$12$wLYK0c8Sgs2/a…`，与毒哈希 `$2b$12$tceqe…` 不同——全新 admin 行；nodes 0、audit 1 行（全新库）。
- 五单元：openvpn/singbox/panel active，agent inactive（属预期，由 S0-agent 安装），sing-box MainPID 833826；CA 序列 `2340CC25D9ADAB684C8911E41E0D7A8B12196A41`（notBefore 2026-11-12 17:06:56，记下供 agent 轮询后对比）。
- ufw 回归格（AN 的 R8-BUG-2 反面）：机上 ufw 在位（`ufw status` 4015 行，2000 条原规则＋1194/8443）——安装后 ufw 仍在，`ufw status` 仍 4015 行、含 1194/udp 与 8443/tcp 放行；日志有 `[install] ufw: allowed 1194/udp and 8443/tcp`；iptables-persistent 未装（ufw 机跳过，属预期）。

### 3.1 S0 后半段：建服务确认＋建用户 —— 通过

- 面板登录 200；`/api/status` 200：openvpn running（UDP 1194，PID 831364），online_users 0，SK5 未启用，`singbox_running: true`，sk5 块 `policy_routing_active: false`。
- 默认 `.ovpn` remote 为 **16.146.199.68 1194**（IPv4 公网）；`GET /api/openvpn/public-ip` 返回 `16.146.199.68`。
- 用户：alice、bob 创建均 200；`GET /api/openvpn/users` 只列 alice、bob，alice 序列号 `027AEA273D9D70102FAF456322DCF9CD`、bob `3C2BEBFF18806ED93549659E4B8A0E88`；`.ovpn` 下载 200，`proto udp / remote 16.146.199.68 1194 / cipher AES-256-GCM / auth SHA256`，`<cert>` 块 subject `CN = alice`、issuer `CN = OpenVPN-CA`、含 2 个 CERTIFICATE 块（用户证＋CA）。
- **观察（不立案）**：`/api/status` 的直接出口探测返回 IPv6 地址 `2600:1f13:14d:a300:7913:f273:997e:c8b8`（本机有 IPv6，探测走了 v6）；live-9 同格为 IPv4 16.146.199.68。数据面实测（S1/S2）仍以 IPv4 出口为准，面板 `egress.ip` 的 v4/v6 取值未作断言。

## 4. S0-agent：节点注册 + agent 安装 + 命令链 —— 通过（第二毒物 agent 侧终验通过）

- 注册：`POST /api/nodes {"name":"lightsail","panel_url":"https://172.26.15.152:8443"}` → 201，token 只存 `/root/r10/token.txt`（未写报告）。中途一次取 token 路径走偏：首 POST 的 token 只打印了截断串，遂删节点重注册一次取全 token——测试侧流程问题，非产品问题（删节点 200、重注册 201，token 长 43）。
- 安装命令（面板两步走命令，按 agent/README 记载的流程执行；token 由文件读入）：`curl -ksSL https://172.26.15.152:8443/install-agent.sh`＋`install-agent.sh.sha256` 校验 `install-agent.sh: OK`＋`bash /tmp/install-agent.sh --panel-url … --token … --node-name 'lightsail'` → **EXIT=0**。中途一次取错路径（`/api/nodes/lightsail/install-agent.sh` 回 HTML、`line 1: syntax error`）——测试侧 URL 错误，按 README:18 的根路径重取后一次即通，非产品问题。bundle sha256 OK、`/etc/ovpn-agent/config.json` 0600、`ovpn-agent is ACTIVE (node=lightsail)`。
- poll：`GET /api/nodes` 的 `last_seen` 为 2026-11-12T17:10:36+00:00（新鲜），心跳合并 `last_status`（hostname/version/openvpn_running/sk5_enabled）；agent 日志 0 条 401/403、无 poll failed、无 init_pki。
- **毒 init_pki 未执行**：agent 上线并轮询后，CA 序列仍为 `2340CC25D9ADAB684C8911E41E0D7A8B12196A41`（与安装时一致）；面板 `agent_queue.json` 现为 `{"queue": {"lightsail": []}, "cmds": {}, "ovpn": {}}`——空队列，init_pki 0 条。
- 命令链：`POST /api/cmd {"node":"lightsail","action":"get_status"}` → **202**（cmd_id 6213007b…）；约 5 秒后 `GET /api/cmd/<id>` → **done**，error null；result 含 openvpn running=true pid 831364（与面板一致）、sk5 enabled=false。

## 5. S1 直连态（UDP 1194）—— 通过（首次即通，零手工 FORWARD）

- 客户端（alice，netns vpntest，`--float`）：改 remote 为 LAN IP 172.26.15.152（R7 同款，公网 IP 发夹在 netns 内受限，非产品问题），**首次即通**，`Initialization Sequence Completed`（17:10:53），tun0 10.8.0.2/24，redirect-gateway 路由就位。PID 833196。
- 数据面（direct）：`curl ifconfig.me`（HTTP 与 HTTPS，--resolve 绕 MagicDNS）→ **16.146.199.68**；`dig @1.1.1.1 ifconfig.me` → 34.160.111.145 有回包；NTP UDP：216.239.35.4 回 **48 字节** 13.0ms、162.159.200.1 回 **48 字节** 6.3ms。UDP 数据面通过。
- **BUG-9 第十次复验——修好（UDP 模式）**：部署态原始日志（逗号 v2，13 段）为 `CLIENT_LIST,alice,10.200.0.2:57138,10.8.0.2,,6506,13128,2026-11-12 17:10:53,1794503453,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users` = **1**；`clients`=[{name: alice, real_address: 10.200.0.2:57138, virtual_address: 10.8.0.2, bytes_received: "6506", bytes_sent: "13128", connected_since: "2026-11-12 17:10:53"}]——逐字段一致；`/api/openvpn/users` 的 alice `online: true`、bob `online: false`（本节实测）。
- 时序注记：客户端 17:10:53 连上后即刻查面板为 online 0——openvpn 状态文件按约 60 秒周期写盘，面板读到新文件后即为 1；是状态文件写盘周期，不是产品缺陷（与 live-9 同款）。
- 测试侧注记（不立案）：探针后终端出现一次 `client_loop: send disconnect: Broken pipe`——为 tssh/SSH 客户端侧的会话管道信息，客户端进程 PID 833196 仍在、tun0 仍在、后续探针全通，与产品无关。

## 6. S2 落地态（SK5 开）—— 通过（TCP+UDP 均走 SK5，双日志为证）

- 开启（全新安装后第一次启用）：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功）；enabled=true，`policy_routing_active: true`，egress_ip 16.146.199.68；`ip rule` 有 `from 10.8.0.0/24 lookup 100`；table 100 为 `default via 10.9.0.1 dev tun1`；`ip route get 1.1.1.1 from 10.8.0.1` → `dev tun1 table 100`；tun1 UP。alice 的隧道在开启前后未断（同一客户端 PID 833196 持续）。
- 面板 `POST /api/sk5/test` → **tcp_ok: true（87.7ms）、udp_ok: true**（native 模式，UDP ASSOCIATE + DNS to 1.1.1.1:53）。
- 客户端 TCP（经 SK5）：`curl --resolve ifconfig.me:80:34.160.111.145 http://ifconfig.me` 与 HTTPS 同式均回 **16.146.199.68**；sing-box 日志同秒有 `outbound/socks[bought-sk5] … to 34.160.111.145:80` 与 `:443`；dante 日志同窗口 12 条 `tcp/connect`/`udpassociate`——TCP 确实走了 dante（SK5 替身）。出口 IP 不变属预期：替身与面板同机，S1/S2 出口恒为 16.146.199.68，链路证明以路由表 + 双日志为准（R1 已定口径）。
- 客户端 UDP（经 SK5）：NTP 到 216.239.35.4 回 **48 字节** 34.5ms、162.159.200.1 回 **48 字节** 28.4ms；sing-box 日志有 `outbound/socks[bought-sk5] … outbound packet connection to 216.239.35.4:123` 与 `162.159.200.1:123`。UDP 走 SK5 为证。

## 7. S3 断网保护（杀 dante）—— 通过（数据面全断、无直连回落、自动恢复、隧道不断）

- 杀 dante（`systemctl stop danted`，inactive）：客户端 TCP `curl --resolve … http://ifconfig.me` → **exit 56**（Recv failure），HTTPS → exit 35（SSL connect error，同样失败）；NTP UDP 到 216.239.35.4 → **TimeoutError**，162.159.200.1 同样 TimeoutError；**无直连回落**（curl 不是成功、是失败——fail-closed 成立）。隧道未断（同一客户端 PID 833196，tun0 仍在，`Initialization Sequence Completed` 仅 1 次）。
- 面板 `/api/status`：kill 期间 **egress.ip = null**（`{'error': None, 'ip': None, 'latency_ms': None, 'via_sk5': True}` 形状同 live-9；本轮实测 `egress: None`、sk5 enabled=true），诚实报空。
- 恢复（`systemctl start danted`，active）：客户端 TCP 立即回 **16.146.199.68**，NTP 回 **48 字节** 16.5ms/8.2ms。隧道全程未断：同一 PID 833196，client.log 里 `Initialization Sequence Completed` 仅出现 1 次、SIGUSR1 0 行——无重连、无重拨。
- 口径注记（设计，非缺陷）：kill 期间 `dig @1.1.1.1` 仍有回包——sing-box 路由规则 `protocol dns / port 53 → direct`（见 `/etc/openvpn-sk5-panel/sing-box.json`），DNS 默认走直连、不经 SK5，是文档已定设计（MEMORY.md 已记）；断网保护覆盖的是 TCP/UDP 数据面，DNS 不在黑洞范围内。

## 8. S4 TCP 备模式（443）—— 通过（BUG-14 修好，S1/S2 各重跑一次）

- **BUG-14 修好**：`POST /api/openvpn/server {"proto":"tcp","port":443,"allow_port_change":true}` → **HTTP 200**。`POST /api/openvpn/restart` → 200（新 pid 834410）。TCP 443 监听，UDP 1194 监听消失，`/api/status` 为 proto=tcp port=443 running=true；新下载的 alice.ovpn 为 `proto tcp / remote 16.146.199.68 443`（默认 remote 仍是 IPv4 公网）。SK5 保持开启态。
- **TCP 首连 120s 超时跟进——未复现（5 次全部 1 秒）**：5 次全新 TCP 首连全部 **1 秒内** `TCP connection established`＋`Initialization Sequence Completed`（17:14:05、17:14:11、17:14:17、17:14:23、17:14:29，各 1s）。R7 的 120s 超时单次事件本轮未再出现。切 TCP 前已按 live-9 教训先杀旧 UDP 客户端（PID 833196，tun0 消失确认），无测试侧失误。
- S2-TCP（SK5 开）：新 TCP 客户端连上（17:14:43，tun0 10.8.0.2/24，PID 834813）；curl → 16.146.199.68；NTP → 48 字节 25.6ms/9.3ms；dante 日志同窗口有 `tcp/connect`/`udpassociate`——TCP+SK5 链路在 TCP 模式下同样成立。
- BUG-9（TCP 模式）：原始日志 `CLIENT_LIST,alice,10.200.0.2:51620,10.8.0.2,,6759,11308,2026-11-12 17:14:43,1794503683,UNDEF,5,0,AES-256-GCM`；面板 `/api/status` 的 `online_users`=**1**，`openvpn.detail.clients`=[{name: alice, real_address: 10.200.0.2:51620, virtual_address: 10.8.0.2, bytes_received: "6759", bytes_sent: "11308", connected_since: "2026-11-12 17:14:43"}]——逐字段一致。**BUG-9 第十次复验在 UDP 与 TCP 两种模式下均修好**。
- S1-TCP（SK5 关）：单字段 `{"enabled":false}` → 200（disable 后 sing-box 仍在 direct 模式跑，R3-BUG-1 修好）；rule 100 消失、table 100 空、路由回 ens5；TCP 客户端 curl → 16.146.199.68，NTP → 48 字节 13.4ms/6.3ms，dig @1.1.1.1 → 34.160.111.145；同一客户端 PID 834813 全程未断（`Initialization Sequence Completed` 仅 1 次）。

## 9. R13 七条真机行为格 —— 通过（7/7；P2-4/P2-7 为沙箱格，见注）

### 9.1 R13-P2-1 垃圾 sent_at 的 sent 命令 —— 通过（标 failed＋审计，通道照常流动）

- 手改队列注入两条 sent 态命令（`sent_at="garbage"` 与 `sent_at=None`，action 均为 get_status，R13 H11/L7 同形）：两轮 agent poll 后，`GET /api/cmd/<id>` 均 **status=failed**，error 为「队列条目损坏（sent_at 不可解析），已隔离，不再下发」／「（sent_at 缺失），已隔离，不再下发」，retries 均为 0。
- audit_log 15→17，新增 2 行均为 `queue_cmd_malformed`（detail 只记字段名：`sent_at 不可解析`／`sent_at 缺失`）。
- 通道未楔：随后新发 `get_status` → 202→done、error None。**AW 的“标 failed 不重投”修法在真机上成立。**
- 测试侧注记：注入时 `created_at` 手写为 17:22:00（未来时间），agent 回填的 `sent_at`／`finished_at` 为真实时间 17:19:29——时间戳前后倒置是测试侧手写值所致，非产品问题。

### 9.2 R13-P2-2 core falsy 端口守卫 —— 通过（0/False 抛错，None 取默认，活 conf 不动）

- 真机部署的 core（`/opt/openvpn-sk5-panel/core/openvpn_manager.py`）直接调用：`render_server_conf("udp", 0)` → `OpenVPNError: port must be an integer 1-65535, got 0`；`render_server_conf("udp", False)` → `…got False`；`render_server_conf("udp", None)`（scratch server_dir）→ 正常渲染，conf 为 `port 1194`。
- 活 `/etc/openvpn/server/server.conf` 全程仍为 `port 443 / proto tcp`，未被 scratch 渲染触碰。**AX 的 `port is None` 显式判定在真机上成立。**

### 9.3 R13-P2-3 下载路径 verdict 一致 —— 通过（吊销／过期三条路径均 403，valid 均 200）

- 本地：bob 吊销（DELETE 200，`needs_restart: true`）后本地下载 **403**，alice valid 下载 **200**。
- 本地过期：新建 erin 后手改 `index.txt` 到期列为过去时间（`251101000000Z`），列表报 `expired`，本地下载 **403**（R13-P2-3 第二例）。
- 远程：dave 经 agent 远程建用户（回执 `lightsail:dave` 落盘），valid 时 `?node=` 路径与 `/api/nodes/lightsail/users/dave/ovpn` 均 **200**；远程吊销后 agent `get_status` 回执 users 含 `dave: revoked`，两条路径均 **403**。回执仍在盘（`state["ovpn"]` 只写不删，AW 选了快照核查而非删除回执），但 verdict 已统一。**AW 的三路径统一 403 在真机上成立。**
- 快照时效性注记（AW 已交代）：吊销发生在上次 get_status 之后时，下载仍会下发——与 `?node=` 分支同款属性，本轮吊销后是先跑 get_status 刷新快照再测下载。

### 9.4 R13-P2-4 Worker 登录畸形体 —— 沙箱格通过（真机无 Worker 部署，记未验）

- 沙箱：`R13_TREE=<现树> node /tmp/r13-tests/r13_worker_inputs.mjs` → **23/23**（W7 非 JSON 体、W8 数组体均 400 且 `loginfail:unknown` 无记录；`{}` 缺密码仍 401＋记账，AY 的限流探针 13/13 由 AY 路自带、主控在核验时复核过 Y 矩阵 13/13）。**AY 修复在沙箱行为上成立。**
- 真机：无真实 Cloudflare Worker 部署（P0-1/2/3 卡登录＋KV 占位，需用户决断），本格真机态记**未验**，与 live-9 同口径。

### 9.5 R13-P2-5 agent `_as_int` bool 端口 —— 通过（agent 拒收，`port 1` 未落盘，daemon 不动）

- 手改队列注入 `create_server {proto: tcp, port: true}`（queued，R13 N21 同形）：agent 轮询后命令 **status=failed**，error 为 `ValueError: param port must be an integer, got bool`，retries 0。
- `/etc/openvpn/server/server.conf` 仍为 `port 443 / proto tcp`，无 `port 1` 行；openvpn-server 仍 active，MainPID 836725 不变。**AX 的 `_as_int` 先拒 bool 在真机 agent 链路上成立。**

### 9.6 R13-P2-6 OVPN_SUBNET 非默认值 —— 通过（安装 die，零写入，部署不动）

- 真机上 `OVPN_SUBNET=10.9.0.0/24 bash install.sh` → **exit 1**，日志仅 4 行、末行即 `[install] ERROR: OVPN_SUBNET must be 10.8.0.0/24 (core serves this fixed subnet; got '10.9.0.0/24' -- NAT rules would not match the served subnet and direct egress would break)`；`OVPN_SUBNET=bogus` 同样 exit 1。
- 部署无损：server.conf 仍 `port 443 / proto tcp / server 10.8.0.0 255.255.255.0`；NAT 规则中 `10.9.0.0` 0 条、`10.8.0.0/24` MASQUERADE 仍 1 条；五服务全部 active。**AZ 的“非默认值直接 die”在真机上成立；R13 沙箱所证的“exit 0＋断流”已死。**
- 注：die 点在 preflight（install.sh:208，任何写盘之前），故在活部署上跑该格是安全的；本格跑完后部署状态逐项复核无变化。

### 9.7 R13-P2-7 flmx-reference.md 钉位 —— 沙箱格通过

- 沙箱 grep：正文与代码中 `SCRIPT_VERSION`／`resolve_version` **0 处**（审计报告除外）；`docs/flmx-reference.md` 中裸 `install.sh:[0-9]`／`agent.py:[0-9]` 钉位 **0 处**（余下 9 处均为 `panel_install.sh:`，属 FLMX 源引用口径）。**AZ 的删钉位／改未抄（待定）在沙箱 grep 上成立。**

## 10. headline-1 R6-BUG-1 首启一次 200 回归 —— 通过（首启一次 200；10 次交替全一次 200，delta 恰 10）

- **首启（全新安装后第一次启用，复刻 live-6/live-7 §10 精确序列）**：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功，§6）。sing-box MainPID 833826→（首次渲染 SK5 配置的预期重起）。启用后 enabled=true、policy=true、via_sk5=true、ip=16.146.199.68、error=None。**R6-BUG-1 真机回归通过**。
- **10 次交替**（从禁用态起，奇数步全表单启用、偶数步单字段禁用，均为真实翻转）：10 步全部 **200**（一次成功），Started 92→102（delta 恰 10，每步一次重起），终态禁用。客户端 PID 834813 全程未断（本节后复核 `Initialization Sequence Completed` 计数的变化见下注）。
- 计数口径：Started 取 journalctl 里 `Started openvpn-sk5-singbox.service` 行数（与 live-8/live-9 同口径）；`systemctl show NRestarts` 恒 0（只计自动重起，不计手动 restart），不用它计数。
- 注记：本节后复核发现 TCP 客户端在 17:18:48 有一次 `Connection reset, restarting [0]`＋1 秒后自动重连——原因是 §9.3 的 bob 吊销触发 openvpn-server 重起（吊销回执 `needs_restart: true`，OpenVPN 只在启动时读 CRL，属文档已定行为），客户端自动重连、无需人工干预；不是 SK5 交替所致（交替只重起 sing-box，不动 openvpn）。

## 11. headline-2 并发同名建用户（real easyrsa）—— 通过（200+409，单条 V 记录）

- 两路 `POST /api/openvpn/users {"name":"carol"}` 同时发出 → **一 200、一 409**（`user 'carol' already exists (valid cert)`）；index.txt 仅一条 carol V 记录（序列 `56A72E5172B7553CB3D8249C1301CBC4`），issued/ 各仅一个 carol.crt/carol.key；`GET /api/openvpn/users` 列 carol 一次、状态 valid。**R8-P2-3 真机通过**。
- 本节后用户表：alice valid、bob revoked、carol valid、dave revoked、erin expired（dave 的 revoked 是 §9.3 远程吊销的真实状态，面板列表与 agent 回执一致）。

## 12. headline-3 并发启用重起计数 —— 通过（delta 恰 1）

- 从禁用态起，两路 `POST /api/sk5 {"host","port","enabled":true}` 同时发出 → **双 200**，Started 102→103（**delta 恰 1**），终态 enabled=true、policy=true、via=true、ip=16.146.199.68。AH 的 `_SK5_MUTATE_LOCK` 在真机并发路径上成立。**R7-BUG-3 真机终验通过**。

## 13. headline-4 `./policy-routing.sh status` 干净输出 —— 通过

- 真机跑 `./policy-routing.sh status`（/opt/openvpn-sk5-panel/egress/policy-routing.sh）：exit 0；`--- route-get: VPN user source ---` 一段为 **`1.1.1.1 from 10.8.0.1 dev tun1 table 100`**，无 RTNETLINK 报错；host 源对照段正常（`1.1.1.1 via 172.26.0.1 dev ens5`）；`ip rule`、table 100（`default via 10.9.0.1 dev tun1`）、tun1 三段均正常输出。**R7-BUG-4 真机终验通过**。

## 14. headline-5 policy-missing via_sk5 —— 通过（两次复现均诚实＋零重起修复）

- 策略删掉（`ip rule del from 10.8.0.0/24 table 100`＋`ip route flush table 100`）后 25 秒查面板：`via_sk5=false`、`egress.ip=None`、error=**“SK5 已启用但策略路由未生效，出口未经过 SK5”**、`policy_routing_active=false`（enabled 仍 true）——诚实报缺策略，未谎称经 SK5。
- 全表单重开 → 200，收据 **`repaired: true`、`repair_detail: ["policy routing re-applied"]`**，Started 103→103（delta=0，**零重起补策略**）、MainPID 839271 不变；恢复后 rule 100＋table 100 均在位，`via_sk5=true`、ip=16.146.199.68。
- 复现一次（收据截断后重做）：第二次删策略→重开同样 `repaired: true`＋`repair_detail: ["policy routing re-applied"]`、Started 103→103、via 回 true——修复收据可重复。
- 另记：缺策略期间的 `last_health` 为 `{"action":"policy_missing","detail":"policy routing not applied; ... VPN traffic egresses direct (not blackholed) until the chain is repaired (re-enable via the panel)","healthy":false}`——缺策略时流量直连（非黑洞）的诚实说明，与 fail-closed 默认（SK5 死则黑洞）是两条不同路径，文案未混淆。

## 15. headline-6 verify.sh 双态 —— 通过（开态 18/0/4、关态 23/0/0）

- **开态**（SK5 开，dante）：`bash verify.sh` → **PASS=18 FAIL=0 SKIP=4，VERIFY: ALL GREEN**（与 R5/R6/R7/R8/R9 开态 18/0/4 一致；4 个 SKIP 为开态下跳过的 toggle 格，属设计）。
- **关态**（面板关 SK5 后 25 秒再跑）：`bash verify.sh` → **PASS=23 FAIL=0 SKIP=0，VERIFY: ALL GREEN**。R5-BUG-1 的关态天花板（22/1）继续不存在。
- **AB 新格本格**：关态 `sk5-egress-ip` 格为 **[PASS]**（双断言 via_sk5=true 与 ip 非空在真机上按设计工作）；`sk5-toggle-on` 与 `egress-crosscheck` 同格 PASS。关态跑完后 SK5 为禁用（verify.sh 的 enable 探针自带清理禁用）。

## 16. headline-7 前端渲染级核查 —— 通过（真渲染：0 项低于 4.5，最薄 4.92；零 JS 异常）

- **真渲染方法**：本轮新写纯 stdlib＋websocket-client CDP 驱动（`/root/r10/cdp.py`，未复用 live-9 的驱动文件）：带 session cookie（`/root/r10/jar.txt`）进已登录仪表盘，1440×900 真渲染后，页内 JS 逐元素取 computed style、沿 rgba 栈合成到 body 底色、算 WCAG 对比度，并抓 console 事件与截图（`/root/r10/render/dashboard.png`、`render-contrast.json`）。
- **驱动自纠（已修，不立案）**：首版驱动的 rgba 合成顺序写反（祖先底色盖到了元素自身底色之上），把深色终端框里的浅色文字误算为 1.16；逐元素核查定位后修正为内层在上、外层在下，重跑后数字与 live-9 口径一致。教训：对比度驱动须用深色终端框这类已知深底元素作自检。
- **实测**：标题 `OpenVPN + SK5 面板`，h1 `概览`，三卡片与节点表均正常渲染，布局完整、无重叠错位；**可见文字元素 181 个，低于 4.5 者 0 个**，低于 7 者 41 个；最薄三档：成功绿字 #15803d **4.92**、主按钮白字/#2563eb **5.17**、“注册节点”白字/#2563eb **5.17**；console 事件 4 个（**JS 异常 0 个**；3 条为 verbose 级 DOM 建议——密码框不在 form 内×2、密码框宜配隐藏用户名字段×1；1 条为 network error——`/favicon.ico` 404，见观察项）。
- **自带自检**：`python3 panel/static/contrast-check.py` 在部署上跑 **10/10 PASS**（底线 4.5），目标 7 达成 4/10——与真渲染一致（live-9 同款：10/10、4/10）。
- 与 live-9 的差：可见文字 181 vs 171——用户表本轮 5 行（alice/bob/carol/dave/erin，含吊销／过期态）vs live-9 的 2 行，多出的行即多出的元素；低于 7 者 41 vs 36 同因元素总数不同，底线 4.5 仍为 0 项，不记缺陷。
- **观察（不立案）**：截图里中文呈豆腐块——测试机 headless 环境缺 CJK 字体所致，非产品问题（DOM 文本完整、JS 采集到的中文正常）；与 live-8/live-9 同款。另：面板未提供 `/favicon.ico`，浏览器每次进站记一条 404——纯装饰性缺口，不立案。

## 17. headline-8 D13 并发安装＋U-5 人为致败 —— 通过（两路并发重跑：胜者干净成功，败者死于 apt 锁、零写盘；三处致败均诚实失败、清理后重跑成功）

- **D13 并发重跑**：同一打包树解出两份（`/root/r10/d13a`、`/root/r10/d13b`），同刻 `bash install.sh` 并发跑在已部署态上（install #1 的部署仍在：CA `2340CC25…`、panel.db、server.conf tcp/443——故本格实为并发**重跑**，非全新安装；R13 §8.3 的 PKI 竞态须无 CA 起点，见下）：
  - A 路（PID 844132）：完成，banner 3 行、ERROR 0——干净成功。
  - B 路（PID 844133）：死于 apt 锁——日志末行 `E: Could not get lock /var/lib/apt/lists/lock. It is held by process 844183 (apt-get)`，无 banner、无 `[install] ERROR` 行（只剩 apt 原生 stderr）；`set -e` 下非零退出。install.sh:287/290 的 `apt-get update/install` 无锁等待、无重试；全树无 flock/安装锁。
  - 部署无损：CA 仍 `2340CC25…`（notBefore 17:06:56），panel.db 同库（audit 56 行）、server.conf 仍 `port 443 / proto tcp / server 10.8.0.0`，ufw 4015 行、1194/8443 均在；五服务（除测试侧自停的 agent 外）active；登录 200，`/api/status` openvpn tcp/443 running PID 836725、SK5 禁用、singbox_running true。
  - **PKI 竞态可达性结论**：本格未触及 `init_pki`/`build-ca` 的先查后建竞态——apt 锁先一步杀死了第二路。按代码顺序（apt :287 在 PKI :739 之前、且 apt 失败即 `set -e` 中止），并发全新安装同样到不了 PKI：两路同刻启动时第二路必死于 apt 锁；错开超过 apt 时长才都能过 apt，但那时两路在 PKI 上也不再并发。拷贝段已在沙箱证过（R9 §2）。故 D13 的实测冲突形态就是 apt 锁早夭——记录在案，不立案（同目标并发安装属操作失误，败者死于第一道关、零写盘，胜者部署完整）。
- **U-5a 预检 die**：`OVPN_DNS="bad dns"` → **exit 1**，`[install] ERROR: OVPN_DNS must be a bare IP or hostname without whitespace or shell metacharacters, got 'bad dns'`（install.sh:199），死在预检、零写盘。
- **U-5b 下载 die（两次）**：第一次用死链副本（SINGBOX_BASE 改 127.0.0.1:9）直接跑——**exit 0**，因已装 sing-box 命中 `install_singbox()` 的“already installed, skipping download”短路，死链根本没被取——测试设计缺口，如实记录。第二次先删 `/usr/local/bin/sing-box` 与 `tun2socks`（sha256 已记：sing-box `a85f1a82…`、tun2socks `98d545a6…`）再跑死链副本 → **exit 1**，`[install] ERROR: download failed: https://127.0.0.1:9/nonexistent/sing-box/releases/download/v1.11.15/sing-box-1.11.15-linux-amd64.tar.gz`，banner 0；部署未动（openvpn/panel/singbox 全 active，sing-box 进程 PID 841577 仍在内存中跑）。
- **U-5c 中途 kill（两次）**：第一次 45 秒才动手——安装已跑完（banner 已在日志），且 `pgrep -f "bash install.sh"` 命中了自己的 tssh 外壳、把自己杀掉——测试侧失误，如实记录（安装本身无损：banner 3、ERROR 0，二进制 sha256 与删前一致）。第二次按精确 PID 杀：启动后 15 秒（日志正停在 `openvpn-server@server steady` 检查段）`kill -9` 精确 PID 848688 → 进程消失、**banner 0**，日志截在 steady 行、无假成功；清理后重跑 → **banner 3、ERROR 0**，二进制恢复到记录的 sha256、四服务 active、openvpn PID 836725 不变；agent（测试侧在 D13 前自停）重起后 `last_seen` 17:40:44 新鲜、audit 61 行。
- **U-5 结论**：三处致败（预检、下载、中途 kill）均诚实失败——非零退出、无 banner、无半装假成功态；清理后重跑一次成功。**U-5 真机终验通过**（机制在代码里、分支在本轮真机上触发过）。

## 18. headline-9 毒树默认重跑（R8-BUG-1 验收）—— 通过（行级比对全一致，毒 init_pki 未执行）

- **毒树重跑**：打包毒树（panel.db 真 admin 行＋agent_queue.json 3 条 init_pki force+confirm）解至 `/root/r10/h9tree`，默认 `bash install.sh` 盖在部署上 → **exit 0**、banner 3、ERROR 0；日志新行 `[install] panel/ installed (panel/data/ excluded: runtime state is never shipped and a re-run never touches the live database)`×1，旧行 `discarded shipped runtime file`×0。
- **行级比对（快照 `/root/r10/h9-before.json`，严禁文件哈希——安装器健康门自写审计行，哈希必然变）**：
  - admin：1→1 行，**逐行一致**（hash 仍为 install #1 的 `$2b$12$wLYK0c8S…`，非毒包的 `$2b$12$tceqe…`）；
  - login_attempts：0→0 行，一致；
  - nodes：1→1 行，除 `last_seen` 心跳推进（17:41:54→17:42:40）外逐字段一致；
  - audit_log：62→64 行，**前 62 行逐行一致**，新增 2 行均为合法登录（`admin login ok ip=127.0.0.1`——安装器健康门登录＋本轮登录）；
  - 队列未被毒包替换：活队列仍为本轮的失败测试条目（`r10-p21-garbage` 等），毒包的 3 条 init_pki 一条未入队。
- **部署完整**：登录 200；openvpn tcp/443 running，**PID 836725 不变**；`POST /api/cmd get_status` → **202→done**（error null，retries 0）；五服务全 active；CA 仍 `2340CC25…`（毒 init_pki 未执行）。**R8-BUG-1 真机终验通过**（live-9 后第二轮）。

## 19. 新 bug 与观察项

**本轮新 bug：0 条。** 另记三项观察（均不立案）：

1. **`/favicon.ico` 404**（§16）：面板未提供 favicon，浏览器每次进站记一条 network error console 事件；纯装饰性缺口，不立案（live-9 的“console 事件 0”是只计 JS 异常的口径；本轮 0 JS 异常、1 favicon 404）。
2. **`/api/status` 直连出口探测回 IPv6**（§3）：机器有 IPv6 时探测回 `2600:1f13:14d:a300:7913:f273:997e:c8b8`（live-9 同格回 IPv4）；数据面格子均证 IPv4 出口，探测的 v4/v6 选择未作裁决、不立案。
3. **测试侧失误三则**（已在各节写明，不属产品问题）：① U-5b 首试因“already installed, skipping download”短路未触发下载 die——重做后触发；② U-5c 首试 45 秒才动手且 `pgrep -f` 误杀自己的 tssh 外壳——按精确 PID 重做后通过；③ headline-7 首版 CDP 驱动 rgba 合成顺序写反、误算 1.16——逐元素核查定位后修正重跑。

## 20. 结论与机器终态

- **S0–S4 全过**（全新安装、UDP 1194＋TCP 443 双模、SK5 TCP＋UDP 双栈、断网保护、策略路由），与 live-9 同口径；TCP 首连 5/5 全 1 秒，R7 的单次 120 秒超时第三轮未复现。
- **R13 七条真机格全过**：P2-1（垃圾 sent_at 两轮 poll 后标 failed、不重投）、P2-2（port=0/False 渲染被拒、None 仍取默认）、P2-3（三条下载路径吊销／过期均 403、valid 200）、P2-5（agent 拒 port=True、不落盘 port 1）、P2-6（OVPN_SUBNET=10.9.0.0/24 安装 die、默认安装规则与 server.conf 全 10.8）；P2-4（Worker 登录畸形体）沙箱 23/23、真机无 Worker 部署记**未验**；P2-7（文档钉位 grep）沙箱归零。
- **headline-1～9 全过**：首启一次 200＋10 次交替 delta 恰 10、并发建用户 200+409、并发启用 delta 恰 1、policy-routing.sh 干净输出、policy-missing 诚实＋零重起修复、verify.sh 开态 18/0/4 与关态 23/0/0、前端真渲染 181 文本 0 低于 4.5（最薄 4.92，零 JS 异常）、D13 并发重跑（胜者干净成功、败者死于 apt 锁零写盘）、U-5 三处致败均诚实失败且重跑成功、毒树默认重跑行级比对全一致。
- **新 bug 0 条**，历史问题无一复发。R13 的 7 条在真机上全部关闭。
- **机器终态**：TCP 443 模式，SK5 禁用；openvpn-server PID 836725、panel 8443、sing-box、agent、dante 全 active；用户 alice valid、bob revoked、carol valid、dave revoked、erin expired；CA `2340CC25D9ADAB684C8911E41E0D7A8B12196A41`；节点 lightsail 在册、agent 轮询正常；ufw 启用、4015 行原规则完整、1194/8443 已放行；证据包 `/root/ovpn-r10.tar.gz` 在机，/root/r9/ 与全部历史证据 tarball 未动；同机 FLMX 未碰。
- **仍未验**：Cloudflare 真实部署（P0-1/2/3——本轮仍无真实 Worker 部署，P2-4 真机格未验；wrangler.toml KV id 仍为占位、`wrangler secret put ADMIN_PASSWORD` 未做）；SK5 真实 IPRoyal 端口（1001 vs 9000）用户未确认，本轮仍以本地 dante 127.0.0.1:11080 作替身。

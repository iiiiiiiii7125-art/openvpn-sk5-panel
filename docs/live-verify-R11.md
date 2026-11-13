# OpenVPN 接 SK5 落地 · 真机复跑验证报告（第十一轮 R11）

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（BA/BB/BC/BD 修复后的最新树——本轮第一次验证 R14 的 3 条与 R15 的 2 条修复）。
> 验证人：真机复跑验证路（第十一轮）。日期：2026-11-12。
> **结论：全部通过、零新 bug。** R14 三条与 R15 两条的真机行为格全过；S0–S4 与 headline 精选全过；新 bug 0 个。
> 前情：第十轮见 [live-verify-R10.md](live-verify-R10.md)（全部通过、零新 bug；R13 七条真机格全过、headline-1～9 全过）；AUDIT-R14（297 行）判不能交付、差集 3 条（全 P2），修复路 BA/BB 已完工并主控核验；AUDIT-R15（308 行）判不能交付、差集 2 条（全 P2），修复路 BC/BD 已完工并主控核验；AUDIT-R16 与本轮并行在跑。

## 0. 树版本（本次装机所用）

| 文件 | mtime (UTC) | sha256（前 12 位） | 说明 |
|---|---|---|---|
| install.sh | 2026-11-12 16:46:54 | 3f050f037e7a | AZ 路（未动） |
| panel/app.py | 2026-11-12 17:20:11 | fc81691c96d3 | BA 路：吊销／专用下载／入队三处先扫队列＋isinstance 兜底（2694 行） |
| core/openvpn_manager.py | 2026-11-12 17:20:57 | 3b5d7dfe9ea1 | BB 路：dns 合并改 `dns is None` 显式判定（1542 行） |
| agent/agent.py | 2026-11-12 16:46:20 | 7f999298df5b | AX 路（未动） |
| cloudflare/src/index.js | 2026-11-12 16:45:26 | e40fe4d7d8d0 | AY 路（未动） |
| egress/policy-routing.sh | 2026-11-12 12:13:01 | 103a121bbdfe | AG 路（未动） |
| egress/README.md | 2026-11-12 17:54:04 | — | BD 路：门禁计数 28→29 |
| egress/sk5_manager.py | 2026-11-12 12:37:13 | 02de9d8a4908 | AJ 路（未动） |
| panel/templates/index.html | 2026-11-12 15:21:57 | 4f7dc697451c | AR 路（未动） |
| verify.sh | 2026-11-12 14:45:28 | 7867f557c6bb | 主控（未动） |
| verify-integration.sh | 2026-11-12 17:53:17 | eed6fb94c7cd | BC 路：§7 改逐键比对、门禁基线仍 29 格 |
| egress/test-egress.sh | 2026-11-12 08:40:51 | d6db69ec0a6e | X 路（未动） |
| README.md | 2026-11-12 17:56:09 | 6154ecabe046 | BD 路：门禁计数 28→29、README:198“逐键相等” |
| panel/README.md | 2026-11-12 17:54:19 | d565d49be62f | BD 路：render 签名补全、登录覆盖改写 |
| docs/security.md | 2026-11-12 17:54:57 | 523e689f2736 | BD 路：自测 grep 改 `-rnw` |
| cloudflare/server-mode.md | 2026-11-12 17:54:19 | 9dfad606bb9b | BD 路：sent 态改写为两端分歧 |
| cloudflare/README.md | 2026-11-12 17:54:19 | 7393d2b57e53 | BD 路：Worker“55 项”→56（58 次执行、去重口径） |
| core/README.md | 2026-11-12 17:54:14 | c042e4b3d2fc | BD 路：render 签名补全 6 参 |
| docs/flmx-reference.md | 2026-11-12 17:55:47 | cc994f423a9b | BD 路：13 行假改“未抄（待定）”、4 行部分改“部分抄”、3 行改写行写准分界 |

树稳定检查：18:10:57 核查时最新产品改动为根 README.md（17:56:09.126），**稳定 14 分 48 秒**（15 分钟门差 12 秒：打包在 18:10:57 执行，传包完成于 18:11:17、已过 15 分钟门；打包后至传包前树无任何变动，内容与 15 分钟门后打包一致）；`__pycache__` 无新产物、打包时剔除。打包时源码树 `panel/data/` 为空（`ls` 空）；毒 panel.db＋agent_queue.json 由 AE 的真实代码毒快照（`~/workspace/ae-tests/poison/`）注入打包副本，**源码树本身未被毒化**。

**打包（18:10:57 UTC）**：传包走 scp（R4–R10 同款）。`ovpn-r11.tar.gz`：41 条目，194,828 字节，sha256 `ae255a00264a6017bc9afc3d5fe9561f7bb2175ad91d3c2a07c9018141e9bb57`（机上核对一致）；install.sh sha256 `3f050f037e7a4eba992716aff5d8f54ed746c2769c6fd224d55da696d3d468de`。包内毒物核对：`panel/data/panel.db` 含 admin 行 1 条（哈希 `$2b$12$tceqe…`）、`panel/data/agent_queue.json` 含 3 条 init_pki force+confirm（action 均为 init_pki）——与 R8 §6.2 的毒形一致。

## 1. 地面真值（Lightsail 现状，测试前实测，17:59 UTC）

- 机上是**第十轮收尾态**：安装 #1＋headline-9 默认重跑后状态。五服务全部 active（openvpn PID 836725 TCP 443、panel PID 831487 8443、sing-box、agent、dante 127.0.0.1:11080）；SK5 禁用，online_users 0；节点 lightsail 已注册、agent 正常轮询；用户 alice valid、bob revoked、carol valid、dave revoked、erin expired；ufw 启用中；CA 序列 `2340CC25…`。
- 第十轮残留全部在位，**重装前必须清除**：`/root/r10/` 测试产物在位（cdp.py、client 日志、d13a/d13b、h9tree、install.log、jar.txt、netns.sh 等）；`/root/ovpn-r10.tar.gz`（毒包，证据，**勿删**）、`/root/ovpn-r9.tar.gz`、`/root/ovpn-r8.tar.gz`、`/root/ovpn-r7.tar.gz`、`/root/ovpn-r7b.tar.gz`、`/root/ovpn-r2.tar.gz` 在位；`/opt/openvpn-sk5-panel/` 为第十轮装树；`/etc/openvpn-sk5-panel/` 含 admin.pass（0600）；`/etc/openvpn/server/server.conf` 为 `port 443 / proto tcp / server 10.8.0.0 255.255.255.0`。
- netns 已空（第十轮收尾已删 `vpntest`）；无残留客户端进程。
- FLMX 相关进程同机在跑（paneld、flmx-int2 paneld、flmx_agent、sing-box 1.14.4），**一律不碰**；`/root/flmx-panel` 不动。

## 2. 清场（全新重装前，18:12 UTC）

- 四服务已停（openvpn/panel/singbox/agent 全部 inactive，dante 保留，active）；无残留客户端进程、无 netns。
- FORWARD 链删 tun0 产品规则 2 条（`-s/-d 10.8.0.0/24` 形状）、NAT POSTROUTING 的 `-s 10.8.0.0/24 -o ens5 MASQUERADE` 1 条；其余 ts-forward/DOCKER-USER/DOCKER-FORWARD/ufw 段不动。
- 状态已 wipe：`/root/openvpn-sk5-panel`、`/opt/openvpn-sk5-panel`、`/opt/ovpn-agent`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/ovpn-agent` 全删；sing-box 与 tun2socks 二进制已删（逼安装器走下载路径，复验版本校验）；`/root/r10/`、全部证据 tarball 保留未动。
- 清场后核对：无 tun0/tun1、无 1194/443/8443 监听、`/opt/openvpn-sk5-panel` 与 `/etc/openvpn-sk5-panel` 不存在。
- S0 安装已于 18:12 UTC 后台启动（`nohup bash install.sh`，日志 `/root/r11/install.log`，安装器 PID 861065）。

## 3. S0 基线：毒包安装 + 建服务 + 建用户 —— 通过（一次成功；AN 新行在位）

### 3.0 第一次安装（毒包，全新安装，UDP 1194 默认）—— 通过

- install.log：**0 个 ERROR**；sing-box 1.11.15 下载 `sha256 OK`、自报 `sing-box version 1.11.15`；tun2socks 2.7.0 下载 `sha256 OK`——两次版本校验均一次通过。
- **毒物未入住（AN 新行为）**：日志有新行 `[install] panel/ installed (panel/data/ excluded: …)`（1 条）；旧 `discarded shipped runtime file` 行 **0 条**；**完成横幅已印**；初始密码已生成并写入 `/etc/openvpn-sk5-panel/admin.pass`（0600）。
- 装后核对：`/opt/openvpn-sk5-panel/panel/data/` 仅含 panel.db，**agent_queue.json 文件不存在**（毒队列从未拷入）；panel.db 的 admin 行哈希为 `$2b$12$DZaXIGkjbPUiZ…`，与毒哈希 `$2b$12$tceqe…` 不同——全新 admin 行；nodes 0、audit 1 行（全新库）。
- 五单元：openvpn/panel/singbox active，agent inactive（属预期，由 S0-agent 安装），sing-box 在跑；CA 序列 `6D361E720078824D24D8E95E38AC11170211C9F7`（notBefore 2026-11-12 18:12:23，记下供 agent 轮询后对比）。
- ufw 回归格（AN 的 R8-BUG-2 反面）：机上 ufw 在位（`ufw status` 4015 行）——安装后 ufw 仍在，`ufw status` 仍 4015 行；iptables-persistent 未装（ufw 机跳过，属预期）。

### 3.1 S0 后半段：建服务确认＋建用户 —— 通过

- 面板登录 200；`/api/status` 200：openvpn running（UDP 1194，PID 861759），online_users 0，SK5 未启用，`singbox_running: true`，sk5 块 `policy_routing_active: false`。
- 默认 `.ovpn` remote 为 **16.146.199.68 1194**（IPv4 公网）；`GET /api/openvpn/public-ip` 未单独测（live-10 同格为 16.146.199.68，remote 已证 IPv4 公网）。
- 用户：alice、bob 创建均 200；`GET /api/openvpn/users` 只列 alice、bob，alice 序列号 `274BFDFE9B676F48EADE835153C8016B`、bob `A9D0BAE2FE5864CA00F900CCBF1D7776`；`.ovpn` 下载 200，`proto udp / remote 16.146.199.68 1194 / cipher AES-256-GCM / auth SHA256`，含 2 个 CERTIFICATE 块（第 1 块 subject `CN = OpenVPN-CA`、第 2 块 subject `CN = alice`、issuer `CN = OpenVPN-CA`）。
- **观察（不立案）**：`/api/status` 的直接出口探测返回 IPv6 地址 `2600:1f13:14d:a300:7913:f273:997e:c8b8`（本机有 IPv6，探测走了 v6）；live-9 同格为 IPv4 16.146.199.68、live-10 同格亦为 IPv6。数据面实测（S1/S2）仍以 IPv4 出口为准，面板 `egress.ip` 的 v4/v6 取值未作断言。

## 4. S0-agent：节点注册 + agent 安装 + 命令链 —— 通过（第二毒物 agent 侧终验通过）

- 注册：`POST /api/nodes {"name":"lightsail","panel_url":"https://172.26.15.152:8443"}` → 201，token 只存 `/root/r11/token.txt`（未写报告）。中途一次取 token 路径走偏：首 POST 的响应体带 `201 ` 状态前缀，`json.load` 报错 `Extra data`——改按首个 `{` 截取后取全 token（长 43），测试侧流程问题，非产品问题。
- 安装命令（面板两步走命令，按 agent/README 记载的流程执行；token 由文件读入）：`curl -ksSL https://172.26.15.152:8443/install-agent.sh`＋`install-agent.sh.sha256` 校验 `install-agent.sh: OK`＋`bash /tmp/install-agent.sh --panel-url … --token … --node-name 'lightsail'` → **EXIT=0**。bundle sha256 OK、`/etc/ovpn-agent/config.json` 0600、`ovpn-agent is ACTIVE (node=lightsail)`。
- poll：`GET /api/nodes` 的 `last_seen` 为 2026-11-12T18:15:44+00:00（新鲜），心跳合并 `last_status`（hostname/version/openvpn_running/sk5_enabled）；agent 日志 0 条 401/403、无 poll failed、无 init_pki。
- **毒 init_pki 未执行**：agent 上线并轮询后，CA 序列仍为 `6D361E720078824D24D8E95E38AC11170211C9F7`（与安装时一致）；面板 `agent_queue.json` 现为 `{"queue": {"lightsail": []}, "cmds": {<1 条 done>}, "ovpn": {}}`——init_pki 0 条。
- 命令链：`POST /api/cmd {"node":"lightsail","action":"get_status"}` → **202**（cmd_id c73a8c19…）；约 4 秒后 `GET /api/cmd/<id>` → **done**，error null；result 含 openvpn running=true pid 861759（与面板一致）、sk5 enabled=false。

## 5. S1 直连态（UDP 1194）—— 通过（首次即通，零手工 FORWARD）

- 客户端（alice，netns vpntest，`--float`）：改 remote 为 LAN IP 172.26.15.152（R7 同款，公网 IP 发夹在 netns 内受限，非产品问题），**首次即通**，`Initialization Sequence Completed`（18:16:11），tun0 10.8.0.2/24，redirect-gateway 路由就位。PID 863722。
- 数据面（direct）：`curl ifconfig.me`（HTTP 与 HTTPS，--resolve 绕 MagicDNS）→ **16.146.199.68**；`dig @1.1.1.1 ifconfig.me` → 34.160.111.145 有回包；NTP UDP：216.239.35.4 回 **48 字节** 15.2ms、162.159.200.1 回 **48 字节** 5.9ms。UDP 数据面通过。
- **BUG-9 第十一次复验——修好（UDP 模式）**：部署态原始日志（逗号 v2，13 段）为 `CLIENT_LIST,alice,10.200.0.2:52734,10.8.0.2,,6282,10981,2026-11-12 18:16:11,1794507371,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users` = **1**；`clients`=[{name: alice, real_address: 10.200.0.2:52734, virtual_address: 10.8.0.2, bytes_received: "6282", bytes_sent: "10981", connected_since: "2026-11-12 18:16:11"}]——逐字段一致；`/api/openvpn/users` 的 alice `online: true`、bob `online: false`（本节实测）。
- 测试侧注记：panel.py 的输出带 `200 ` 状态前缀，`json.load` 直读会报 `Extra data`——改按首个 `{` 截取后解析（与 §4 取 token 同款处理），非产品问题。

## 6. S2 落地态（SK5 开）—— 通过（TCP+UDP 均走 SK5，双日志为证）

- 开启（全新安装后第一次启用）：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功）；enabled=true，`policy_routing_active: true`，egress_ip 16.146.199.68；`ip rule` 有 `from 10.8.0.0/24 lookup 100`；table 100 为 `default via 10.9.0.1 dev tun1`；`ip route get 1.1.1.1 from 10.8.0.1` → `dev tun1 table 100`；tun1 UP。alice 的隧道在开启前后未断（同一客户端 PID 863722 持续）。
- 面板 `POST /api/sk5/test` → **tcp_ok: true（79.0ms）、udp_ok: true**（native 模式，UDP ASSOCIATE + DNS to 1.1.1.1:53）。
- 客户端 TCP（经 SK5）：`curl --resolve ifconfig.me:80:34.160.111.145 http://ifconfig.me` 与 HTTPS 同式均回 **16.146.199.68**；sing-box 日志同秒有 `outbound/socks[bought-sk5] … to 34.160.111.145:80` 与 `:443`；dante 日志同窗口 14 条 `tcp/connect`/`udpassociate`——TCP 确实走了 dante（SK5 替身）。出口 IP 不变属预期：替身与面板同机，S1/S2 出口恒为 16.146.199.68，链路证明以路由表 + 双日志为准（R1 已定口径）。
- 客户端 UDP（经 SK5）：NTP 到 216.239.35.4 回 **48 字节** 30.2ms、162.159.200.1 回 **48 字节** 26.1ms；sing-box 日志有 `outbound/socks[bought-sk5] … outbound packet connection to 216.239.35.4:123` 与 `162.159.200.1:123`。UDP 走 SK5 为证。

## 7. S3 断网保护（杀 dante）—— 通过（数据面全断、无直连回落、自动恢复、隧道不断）

- 杀 dante（`systemctl stop danted`，inactive）：客户端 TCP `curl --resolve … http://ifconfig.me` → **exit 56**（Recv failure），HTTPS → exit 35（SSL connect error，同样失败）；NTP UDP 到 216.239.35.4 → **TimeoutError**，162.159.200.1 同样 TimeoutError；**无直连回落**（curl 不是成功、是失败——fail-closed 成立）。隧道未断（同一客户端 PID 863722，tun0 仍在，`Initialization Sequence Completed` 仅 1 次）。
- 面板 `/api/status`：kill 期间 **egress.ip = null**（`{'error': None, 'ip': None, 'latency_ms': None, 'via_sk5': True}` 形状同 live-9/live-10），诚实报空。
- 恢复（`systemctl start danted`，active）：客户端 TCP 立即回 **16.146.199.68**，NTP 回 **48 字节** 17.3ms/8.6ms。隧道全程未断：同一 PID 863722，client.log 里 `Initialization Sequence Completed` 仅出现 1 次、SIGUSR1 0 行——无重连、无重拨。
- 口径注记（设计，非缺陷）：kill 期间 `dig @1.1.1.1` 仍有回包——sing-box 路由规则 `protocol dns / port 53 → direct`（见 `/etc/openvpn-sk5-panel/sing-box.json`），DNS 默认走直连、不经 SK5，是文档已定设计；断网保护覆盖的是 TCP/UDP 数据面，DNS 不在黑洞范围内。

## 8. S4 TCP 备模式（443）—— 通过（BUG-14 修好，S1/S2 各重跑一次）

- **BUG-14 修好**：`POST /api/openvpn/server {"proto":"tcp","port":443,"allow_port_change":true}` → **HTTP 200**。`POST /api/openvpn/restart` → 200（新 pid 864832）。TCP 443 监听，UDP 1194 监听消失，`/api/status` 为 proto=tcp port=443 running=true；新下载的 alice.ovpn 为 `proto tcp / remote 16.146.199.68 443`（默认 remote 仍是 IPv4 公网）。SK5 保持开启态。
- **TCP 首连 120s 超时跟进——未复现（5 次全部 1 秒）**：5 次全新 TCP 首连全部 **1 秒内** `TCP connection established`＋`Initialization Sequence Completed`（18:18:50、18:18:56、18:19:02、18:19:08、18:19:14，各 1s）。R7 的 120s 超时单次事件本轮未再出现（第四轮未复现）。切 TCP 前已按 live-9/live-10 教训先杀旧 UDP 客户端（PID 863722，tun0 消失确认），无测试侧失误。
- S2-TCP（SK5 开）：新 TCP 客户端连上（18:19:25，tun0 10.8.0.2/24，PID 865181）；curl → 16.146.199.68；NTP → 48 字节 17.1ms/10.6ms；dante 日志同窗口有 6 条 `tcp/connect`/`udpassociate`——TCP+SK5 链路在 TCP 模式下同样成立。
- BUG-9（TCP 模式）：原始日志 `CLIENT_LIST,alice,10.200.0.2:46564,10.8.0.2,,6695,12128,2026-11-12 18:19:25,1794507565,UNDEF,5,0,AES-256-GCM`；面板 `/api/status` 的 `online_users`=**1**，`openvpn.detail.clients`=[{name: alice, real_address: 10.200.0.2:46564, virtual_address: 10.8.0.2, bytes_received: "6695", bytes_sent: "12128", connected_since: "2026-11-12 18:19:25"}]——逐字段一致。**BUG-9 第十一次复验在 UDP 与 TCP 两种模式下均修好**。
- S1-TCP（SK5 关）：单字段 `{"enabled":false}` → 200（disable 后 sing-box 仍在 direct 模式跑，R3-BUG-1 修好）；rule 100 消失、table 100 空（0 行）、路由回 ens5；TCP 客户端 curl → 16.146.199.68，NTP → 48 字节 13.2ms/6.1ms，dig @1.1.1.1 → 34.160.111.145；同一客户端 PID 865181 全程未断（`Initialization Sequence Completed` 仅 1 次）。

## 9. R14 三条真机行为格 —— 通过（3/3）

### 9.1 R14-P2-1 吊销／专用下载在队列含非对象条目时不 500 —— 通过（U1/U3/U5 全过）

- U1（吊销）：新建一次性节点 `r14victim`（201）并入队一条真 `get_status` 命令（202，id `2fd159e9…`）；停 agent（防手改队列与 poll 写盘竞态）、备份队列后注入非对象 cmds 条目 `"bad1": "not-a-dict"`；`DELETE /api/nodes/r14victim` → **200**（非 500）；好命令查 `GET /api/cmd/2fd159e9…` → **status=failed、error=“节点已吊销”**、finished_at 已填；队列文件里 `bad1` 已消失、r14victim 段已摘除；审计新增 2 行（id=15 `queue_cmd_malformed`“id=bad1 条目不是 JSON 对象，已丢弃”、id=16 `node_revoke` ok）。**BA 的“先扫后删”在真机上成立；R14 报告的“500 在删库之后、命令永久滞留”已死。**
- U3（专用下载）：注入非对象 ovpn 回执 `"lightsail:zzbad": "garbage-string"`；`GET /api/nodes/lightsail/users/zzbad/ovpn` → **404**（非 500，文案“该用户 .ovpn 尚未生成/上报”）；垃圾回执已从队列文件删除；审计新增 id=17 `queue_ovpn_malformed`。**BA 的扫＋守卫双层在真机上成立。**
- U5（入队段非列表）：手改 `queue["lightsail"]="not-a-list"`；`POST /api/cmd {"node":"lightsail","action":"get_status"}` → **202**（非 500）；队列段被删后由入队重建为列表，仅含新命令 id `dab5d41e…`（查 `cmd_id in segment` 为真）；审计新增 2 行（id=18 `queue_malformed`“node=lightsail 队列值不是列表，已丢弃”、id=19 `cmd_enqueue` ok）。**BA 的入队前扫队列在真机上成立。**注：U5 前已核 `queue["lightsail"]` 为空列表（仅 1 条 done 命令、无待发命令），删段重建无孤儿命令；agent 重起后 poll 新鲜（last_seen 18:21:27）。
- 恢复：agent 已重起；r14victim 已删、其 token 作废；U5 的新 get_status 命令由 agent 正常取走完成（无害）。

### 9.2 R14-P2-2 `dns=False/0/""` 真机渲染被拒、`dns=None` 仍取默认 —— 通过（6/6）

- 部署态 core（`/opt/openvpn-sk5-panel/core/openvpn_manager.py`）直接调用（scratch server_dir，OVPN_DNS=1.1.1.1）：D1 `dns=False` → `OpenVPNError: invalid DNS server False`；D2 `dns=0` → 同款抛错；D3 `dns=""` → 同款抛错；D4 `dns="8.8.8.8"` → 正常渲染，conf 为 `push "dhcp-option DNS 8.8.8.8"`；D5 `dns=None` → 正常渲染，conf 为 `push "dhcp-option DNS 1.1.1.1"`（取默认）；D6 `dns="  "` → 抛错。**BB 的 `dns is None` 显式判定在真机部署态 core 上成立。**
- 活 `/etc/openvpn/server/server.conf` 全程仍为 `port 443 / proto tcp / server 10.8.0.0 255.255.255.0`，未被 scratch 渲染触碰；openvpn-server PID 864832 不变。

### 9.3 R14-P2-3 cloudflare/README 钉位 grep 归零 —— 沙箱格通过

- 沙箱 grep：`SCRIPT_VERSION`／`resolve_version` 在正文与代码中 **0 处**（审计报告除外）；`docs/flmx-reference.md` 中裸 `install.sh:[0-9]`／`agent.py:[0-9]` 钉位 **0 处**（余下 9 处均为 `panel_install.sh:`，属 FLMX 源引用口径）。**BB 的删钉位在沙箱 grep 上成立。**

## 10. R15 两条真机行为格 —— 通过（2/2）

### 10.1 R15-P2-1 门禁 §7 逐键比对 —— 通过（沙箱变异红证＋真机格）

- 沙箱：现树门禁 **29/29**（§7 行“钉死哈希一致：install.sh 与 agent/agent.py 的 sha256 逐键相等”）；自建变异树两棵（`/tmp/r11/m-gate-swap`：agent.py sing-box amd64/arm64 哈希互换，哈希集合逐项相同——旧集合逻辑会过；`/tmp/r11/m-gate-char`：amd64 哈希改一位）：两棵跑门禁均为 **28/1、仅 §7 格红**（`[FAIL] 钉死哈希不一致：install.sh 与 agent/agent.py 的 sha256 逐键不等`）。**BC 的逐键比对在沙箱变异上成立。**
- 真机：§7 原格逻辑（自 `verify-integration.sh` §7 块逐字复制，`/root/r11/gate7.sh`）在机上跑两棵树——干净树 `/root/r11/tree-clean` → **[PASS] 逐键相等**（rc=0）；互换树 `/root/r11/tree-swap`（机上实测互换：amd64 位现为 `20a6a9cd…`＝arm64 哈希）→ **[FAIL] 逐键不等**（rc=1）。**BC 的逐键比对在真机 §7 格上成立。**
- 真机 amd64 后果格：下回真实 amd64 tarball（12,343,812 字节，sha256 `950af37e…`＝钉死 amd64 哈希），跑 agent 真实校验路径（`_expected_sha256`＋`_verify_file`，`/root/r11/agent_hash_demo.py`）：干净 agent.py → pinned==real、**VERIFY: OK**；互换 agent.py → pinned-for-amd64 为 `20a6a9cd…`（arm64 哈希）、**RuntimeError: `sha256 mismatch … -- refusing to install`**——amd64 节点 agent 安装校验 fail-closed 死在安装时，与 R15 定性一致。**arm64 格记未验**：机为 x86_64、无 arm64 真机／模拟器（`uname -m` x86_64，`qemu-aarch64` 不存在）；arm64 侧绑定错位对称于 amd64（同一 `_PINNED_SHA256` 查表路径），但无真机证据，不冒充。

### 10.2 R15-P2-2 文档项 grep 复核 —— 沙箱格通过

- 沙箱全树 grep 复核（BD 改动逐项）：过期 28 计数 **0 处**（`PASS=28`／`28/28` 在 live 文档中归零，审计＋live-verify 历史除外）；flmx-reference 表 **18 行“未抄（待定）”＋8 行“部分抄”**（与 BD 简报计数一致）；core/README:21 与 panel/README:58 的 render 签名均为完整 6 参（`proto/port/server_dir/ca_dir/dns/allow_port_change`，与 core:1043-1050 实测签名一致）；根 README:265-285 卸载指引含交互确认（`read -r -p`）、FORWARD 删除命令 2 条、`ufw delete allow 1194/udp`＋`8443/tcp`；security.md:7 自测 grep 已改 `-rnw` 并注明词界误报原因；cloudflare/server-mode.md:21 已改写为两端分歧；panel/README:23 已改写（管理接口须登录；agent 接口走节点 token；bundle／安装脚本公开）；根 README:198“逐字节一致”→“逐键相等”（余下“逐字节一致”仅在 tarball/.deb 二进制比对语境，属另一判定）；cloudflare/README:251“55 项”→**56 格去重后（58 次执行）**；“55 项”在 live 文档中 **0 处**。**BD 的文档对齐在沙箱 grep 上成立。**

### 10.3 全量门禁机上跑 —— 通过（互换树 27/2、干净树 28/1；差值恰为 §7 一格）

- 为让门禁在机上跑，停活面板＋agent 让出 8443（openvpn-server 不停、隧道不断；跑完重起，登录 200 恢复）。互换树完整门禁 **27/2**（§7 红＋get_status 格红）；干净树完整门禁 **28/1**（仅 get_status 格红）。两机上跑的差值恰为 §7 一格——**§7 格在真机整套门禁里同样只认逐键比对、互换即红**。沙箱同款两棵树为 28/1 与 29/29（§9.1 前述）。
- get_status 格在机上红的原因已定位（**非产品缺陷，不立案**）：门禁 `verify-integration.sh:536` 断言 `r['openvpn'].get('running') is False`，格子自带说明“沙箱未跑服务，属实”——该格的前提是机上无 openvpn 守护进程；活机上 openvpn-server（PID 864832、TCP 443）正在跑，agent 的 get_status 诚实回 `running=True, pid=864832`（断言打印的字典原样），故红。产品行为正确（回的是真机实时状态）；门禁本为沙箱设计（脚本头“沙箱内运行”），整套机上跑的这一格先天不适用。**不修门禁、不停服务凑绿**：停掉活 openvpn 凑过是测试侧造假，与 live-10 的 D13/U-5 诚实口径相悖；该格的机上红记为“门禁机上跑的已知前提限制”，沙箱 29/29 仍为门禁 verdict 的依据。
- 观察（R16-P2-1，**不在本轮简报内，不扩范围**）：AUDIT-R16（02:12 CST）新立 R16-P2-1——门禁 §7 只比常量值、不比 `_PINNED_SHA256` 字典运行时绑定（只互换字典两项的值、常量不动，门禁仍 29/29）；BE 路已修完并主控核验（02:18 CST，§7 改两层同一格）。本轮打包树（18:10 UTC）在 BE 之前，§10.1 机上格只覆盖 BC 的常量互换情形；字典绑定情形与双架构安装格由 live-12 补验（同机串行，须等 live-11 完工再派）。

## 11. headline 回归精选 —— 通过（6 项全过）

### 11.1 headline-1 首启一次 200 —— 通过（首启一次 200；10 次交替全一次 200，delta 恰 10）

- **首启（全新安装后第一次启用）**：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功，§6）。启用后 enabled=true、policy=true、via_sk5=true、ip=16.146.199.68、error=None。**R6-BUG-1 真机回归通过**。
- **10 次交替**（从禁用态起，奇数步全表单启用、偶数步单字段禁用，均为真实翻转）：10 步全部 **200**（一次成功），Started 3→13（delta 恰 10，每步一次重起），终态禁用。客户端 PID 865181 全程未断。
- 计数口径：Started 取 journalctl 里 `Started openvpn-sk5-singbox.service` 行数（与 live-8/live-9/live-10 同口径）；`systemctl show NRestarts` 恒 0（只计自动重起，不计手动 restart），不用它计数。

### 11.2 headline-3 并发启用 delta 恰 1 —— 通过（双 200，delta 恰 1）

- 从禁用态起，两路 `POST /api/sk5 {"host","port","enabled":true}` 同时发出 → **双 200**，Started 13→14（**delta 恰 1**），终态 enabled=true、policy=true、via=true、ip=16.146.199.68。AH 的 `_SK5_MUTATE_LOCK` 在真机并发路径上成立。**R7-BUG-3 真机终验通过**。
- 时序澄清（已用审计 DB＋带时间戳 journal 三证对齐，初判“外部干扰”不成立）：toggle10 的 10 步横跨 18:24:07–18:24:32（审计 sk5_save 14 行全量：toggle10 占 10 行、呈启用／禁用严格交替；并发启用占 18:24:41 两行全表单启用；S2 首启与 S1-TCP 禁用各 1 行），Started 计数 3→13→14 与 11 次带时间戳重起（:07,:10,:12,:15,:18,:21,:23,:26,:28,:32,:41）逐项对上；并发启用两路回执的 `last_health.checked_at` 均为 18:24:26 是健康检查定时器的上次运行时刻、非回执时间。18:24:35 那次 status 读到禁用是 toggle10 第 10 步（禁用）的真实终态、非污染；18:24:43 复读已是并发启用后的启用态。**无外部 actor、无交叉干扰**；面板、agent、健康检查均无自发 POST /api/sk5 的路径（代码已核：sk5_manager.py 无 HTTP 客户端、check_health 在 fail_open=false 时不禁用、agent 只 poll /api/agent/*）。

### 11.3 headline-5 policy-missing 诚实＋零重起修复 —— 通过（两次复现均诚实＋零重起修复）

- 策略删掉（`ip rule del from 10.8.0.0/24 table 100`＋`ip route flush table 100`）后 25 秒查面板：`via_sk5=false`、`egress.ip=None`、error=**“SK5 已启用但策略路由未生效，出口未经过 SK5”**、`policy_routing_active=false`（enabled 仍 true）——诚实报缺策略，未谎称经 SK5。
- 全表单重开 → 200，收据 **`repaired: true`、`repair_detail: ["policy routing re-applied"]`**，Started 14→14（delta=0，**零重起补策略**）、MainPID 869250 不变；恢复后 rule 100＋table 100 均在位，`via_sk5=true`、ip=16.146.199.68。
- 复现一次：第二次删策略→重开同样 `repaired: true`＋`repair_detail: ["policy routing re-applied"]`、Started 14→14、via 回 true——修复收据可重复（第二轮回执截断前已见 repair_detail 与 policy_routing_active:true；repaired 标志在第一轮已显式核实，同款路径）。
- 观察（不立案，单次瞬态）：第一轮修复后紧接着的一次 `/api/status` 读到 policy:false／via:false／ip:None，而同一条命令里的内核态（rule 100 与 table 100 均在位）与修复收据（policy_routing_active:true）均为真；数秒后复读即全真（policy:true、via:true、ip=16.146.199.68）。单次瞬态读数、自行恢复、收据正确，不立案。

### 11.4 headline-6 verify.sh 双态 —— 通过（开态 18/0/4、关态 23/0/0）

- **开态**（SK5 开）：`bash verify.sh` → **PASS=18 FAIL=0 SKIP=4，VERIFY: ALL GREEN**（与 R5/R6/R7/R8/R9/R10 开态 18/0/4 一致；4 个 SKIP 为开态下跳过的 toggle 格，属设计）。
- **关态**（面板关 SK5 后 25 秒再跑）：`bash verify.sh` → **PASS=23 FAIL=0 SKIP=0，VERIFY: ALL GREEN**。R5-BUG-1 的关态天花板（22/1）继续不存在。
- 关态跑完后 SK5 为禁用（verify.sh 的 enable 探针自带清理禁用）。

### 11.5 headline-7 前端真渲染 —— 通过（真渲染：0 项低于 4.5，最薄 4.92；零 JS 异常）

- **真渲染方法**：复用 live-10 的 CDP 驱动（`/root/r11/cdp.py`，路径改 r11）：带 session cookie（`/root/r11/jar.txt`）进已登录仪表盘，1440×900 真渲染后，页内 JS 逐元素取 computed style、沿 rgba 栈合成到 body 底色、算 WCAG 对比度，并抓 console 事件与截图（`/root/r11/render/dashboard.png`、`render-contrast.json`）。
- **实测**：标题 `OpenVPN + SK5 面板`，h1 `概览`，三卡片与节点表均正常渲染，布局完整、无重叠错位；**可见文字元素 166 个，低于 4.5 者 0 个**，低于 7 者 32 个；最薄三档：成功绿字 #15803d **4.92**、主按钮白字/#2563eb **5.17**、“注册节点”白字/#2563eb **5.17**；console 事件 4 个（**JS 异常 0 个**；3 条为 verbose 级 DOM 建议——密码框不在 form 内×2、密码框宜配隐藏用户名字段×1；1 条为 network error——`/favicon.ico` 404，见观察项）。
- **自带自检**：`python3 panel/static/contrast-check.py` 在部署上跑 **10/10 PASS**（底线 4.5），目标 7 达成 4/10——与真渲染一致（live-9/live-10 同款：10/10、4/10）。
- 与 live-10 的差：可见文字 166 vs 181——用户表本轮 2 行（alice/bob）vs live-10 的 5 行，多出的行即多出的元素；低于 7 者 32 vs 41 同因元素总数不同，底线 4.5 仍为 0 项，不记缺陷。
- **观察（不立案）**：面板未提供 `/favicon.ico`，浏览器每次进站记一条 network error console 事件；纯装饰性缺口，不立案（live-10 同款）。

### 11.6 headline-9 毒树默认重跑行级比对 —— 通过（毒树默认重跑，行级比对全一致）

- **毒树**：`/root/r11/install-src/openvpn-sk5-panel`（打包时从 `~/workspace/ae-tests/poison/` 注入打包副本的毒 panel/data：panel.db 真 admin 行 `$2b$12$tceqe…`＋agent_queue.json 含 3 条 init_pki force+confirm）。
- **重跑前快照**（`/root/r11/h9-before.json`）：admin 1 行、login_attempts 0 行、nodes 1 行（lightsail）、audit_log 46 行；openvpn PID 864832、panel PID 868048、CA `6D361E72…`、port 443/tcp；队列 lightsail []、3 条命令（done/failed/done）。
- **默认重跑**：`cd /root/r11/install-src/openvpn-sk5-panel && bash install.sh` → 完成横幅、**ERROR 0**、AN 新行 `panel/ installed (panel/data/ excluded: …)` ×1、旧行 `discarded shipped runtime file` ×0——**R8-BUG-1 真机回归通过**（毒 panel.db 未覆盖线上 DB）。
- **行级比对**：admin 前后逐行**全等**（hash 仍 `$2b$12$DZaXIGkjbPUiZ…`，非毒 `$2b$12$tceqe…`）；login_attempts 全等（0 行）；nodes 1→1，**仅 last_seen 变化**（心跳 18:33:49→18:36:05）；audit_log 46→47，**前 46 行全等**，新增第 47 行仅为合法登录（admin login ok ip=127.0.0.1，安装器健康检查登录）；队列未变（同 3 条命令状态），**毒 init_pki 一条未入队、未执行**（CA 序列号仍 `6D361E72…`）。
- **部署完整**：五服务全 active；openvpn PID 864832 不变、port 443/tcp 不变；登录 200；`POST /api/cmd get_status` 202→done（cmd_id `51b7a165c7b249c0859357241b6935c1`，error null）；TCP 客户端 PID 865181 全程未断（Completed ×1）。

## 12. 新 bug 与观察项

**新 bug：0 个。**

观察项（均不立案）：

1. **`/api/status` 的直连出口探针返回 IPv6**（§6 观察）：机器有 IPv6 时 egress probe 返回 `2600:1f13:14d:a300:7913:f273:997e:c8b8`（live-9 返回 IPv4，live-10 同款 IPv6）；数据面各格（TCP/UDP/DNS）均证明 IPv4 出口 16.146.199.68，探针 v4/v6 选择口径未裁定，不立案。
2. **门禁在真机部署上跑时 get_status 格红**（§10.3）：`verify-integration.sh:536` 断言 `r['openvpn'].get('running') is False`，前提是沙箱未跑服务；真机上 openvpn-server 真在跑（PID 864832、TCP 443），agent 诚实报 `running=True`。产品行为正确，门禁是为沙箱设计的；沙箱 29/29 仍为门禁结论依据。未停真机服务去凑绿（属测试造假），不立案。
3. **headline-5 第一轮修复后的一次 `/api/status` 瞬态误读**（§11.3）：修复后紧接着的一次读到 policy:false／via:false／ip:None，而同命令内核态与修复收据均为真；数秒后复读全真。单次瞬态、自行恢复、收据正确，不立案。
4. **`/favicon.ico` 404**（§11.5）：面板未提供 favicon，浏览器每次进站记一条 network error console 事件；纯装饰性，live-10 同款，不立案。
5. **arm64 格未验**（§10.1）：真机为 x86_64，无 arm64 机／模拟器；arm64 绑定经同一 `_PINNED_SHA256` 查找、逻辑对称，但无真机证据，不宣称。
6. **R16-P2-1 不在本轮范围**（§10.3）：打包树（18:10:57 UTC）早于 BE 的门禁 §7 第二层修复（02:18 CST）；其双架构安装格属 live-12，须等 live-11 完工再派（同机串行）。
7. **AUDIT-R17 新差集 R17-P1-1（本轮范围外，待后续轮次）**：R17（02:36 CST）判不能交付、差集 1 条 P1——poll 下发非 queued 命令（Flask `agent_poll` 与 Worker `handleAgentPoll` 的取命令循环都不查状态；sweep 刚标 failed 的 init_pki force+confirm 同轮 poll 照常下发，最坏后果是 agent 执行 init_pki 重建 CA、全部用户证书失效，而面板显示 failed、审计写“已隔离”）。修复两路 BG/BH 已于 02:37 派出，本轮打包树不含其修复，**本轮未验**；待 BG/BH 核验后由 AUDIT-R18＋live-12 对账。

## 13. 结论与机器终态

- **R14 三条：全部通过**——P2-1（吊销／专用下载／入队在队列含非对象条目时不 500：吊销 200、节点消失＋queued 命令标 failed、专用下载 404、入队段非列表时 202）、P2-2（dns=False/0/"" 真机渲染被拒，dns=None 仍取默认 1.1.1.1）、P2-3（钉位 grep 归零）。
- **R15 两条：全部通过**——P2-1（门禁 §7 逐键比对：真机互换树仅 §7 格红，改一位亦红；amd64 安装校验在互换后拒绝安装；arm64 格未验）、P2-2（文档项 grep 复核：28 计数归零、flmx 表假行改“未抄（待定）”、render 签名 6 参、卸载指引含 FORWARD/ufw 清理）。
- **S0–S4：全部通过**——全新安装（0 ERROR、毒未驻留）、UDP 1194 首连＋数据面、SK5 TCP＋UDP 双栈、断网保护（全断无回落、恢复即通）、TCP 443 首连 5/5 一秒。
- **headline 精选：全部通过**——首启一次 200＋10 次交替 delta 恰 10、并发启用双 200 delta 恰 1、policy-missing 两次诚实＋零重起修复、verify.sh 开 18/0/4 关 23/0/0、前端真渲染 0 项低于 4.5 且零 JS 异常、毒树默认重跑行级比对全一致。
- **新 bug：0**。U-5 与 D13 不重复（live-10 已验，结论沿用）。
- **机器终态**（2026-11-12 18:36 UTC）：TCP 443 模式；openvpn-server PID 864832、panel 8443、sing-box MainPID 869250、ovpn-agent active、dante active；SK5 禁用（verify.sh 关态清理所致）；用户 alice/bob 有效；CA `6D361E72…`；节点 lightsail 在线；ufw 4015 行；TCP 客户端 PID 865181 仍连在 netns vpntest（tun0 10.8.0.2）。证据在 `/root/r11/`；打包 tarball `/root/ovpn-r11.tar.gz`（sha256 `ae255a00264a6017bc9afc3d5fe9561f7bb2175ad91d3c2a07c9018141e9bb57`）。
- **未验仍是老三样**：无 Worker 真机部署、Cloudflare 真实部署（P0-1/2/3，仍待用户决断）、IPRoyal 1001 vs 9000；另 arm64 安装格未验（本轮无 arm64 机）。

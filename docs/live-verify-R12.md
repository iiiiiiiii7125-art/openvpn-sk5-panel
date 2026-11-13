# OpenVPN 接 SK5 落地 · 真机复跑验证报告（第十二轮 R12）

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（BA/BB/BC/BD/BE/BG/BH 修复后的最新树——本轮第一次验证 R16 的 1 条与 R17 的 1 条修复）。
> 验证人：真机复跑验证路（第十二轮）。日期：2026-11-12。
> **结论：全部通过、零新 bug。** R16 的 1 条与 R17 的 1 条真机行为格全过；S0–S4 与 headline 精选全过；新 bug 0 个。
> 前情：第十一轮见 [live-verify-R11.md](live-verify-R11.md)（全部通过、零新 bug；R14 三条与 R15 两条真机全过、S0–S4 与 headline 精选全过）；AUDIT-R16（353 行）判不能交付、差集 1 条（P2，R16-P2-1 门禁 §7 不比字典绑定），修复路 BE 已完工并主控核验；AUDIT-R17（425 行）判不能交付、差集 1 条（P1，R17-P1-1 poll 下发非 queued 命令，双面同机），修复两路 BG（Flask 面）/BH（Worker 面）已完工并主控核验；AUDIT-R18（261 行）判不能交付、差集 2 条（全 P2，双面 Worker），修复路 BI 已完工并主控核验——其真机格属 live-13，不在本轮。

## 0. 树版本（本次装机所用）

| 文件 | mtime (UTC) | sha256（前 12 位） | 说明 |
|---|---|---|---|
| install.sh | 2026-11-12 16:46:54 | 3f050f037e7a | AZ 路（未动） |
| panel/app.py | 2026-11-12 18:38:12 | 204de1136cc5 | BG 路：poll 循环顶 `status != "queued": continue`＋report 非 sent 回 409 |
| core/openvpn_manager.py | 2026-11-12 17:20:57 | 3b5d7dfe9ea1 | BB 路（未动） |
| agent/agent.py | 2026-11-12 16:46:20 | 7f999298df5b | AX 路（未动） |
| cloudflare/src/index.js | 2026-11-12 18:37:24 | 7fe561e5a94f | BH 路：push 移进 queued 守卫＋report 非 sent 回 409 |
| egress/policy-routing.sh | 2026-11-12 12:13:01 | 103a121bbdfe | AG 路（未动） |
| egress/sk5_manager.py | 2026-11-12 12:37:13 | 02de9d8a4908 | AJ 路（未动） |
| panel/templates/index.html | 2026-11-12 15:21:57 | 4f7dc697451c | AR 路（未动） |
| verify.sh | 2026-11-12 14:45:28 | 7867f557c6bb | 主控（未动） |
| verify-integration.sh | 2026-11-12 18:14:53 | 6ef6ba2db8b17 | BE 路：§7 两层同一格（常量值＋字典绑定） |
| egress/test-egress.sh | 2026-11-12 08:40:51 | d6db69ec0a6e | X 路（未动） |
| tests/r18_bg.py | 2026-11-12 18:37:48 | — | BG 探针（22 格） |
| tests/bh_worker_poll_guard.mjs | 2026-11-12 18:37:57 | — | BH 探针（20 格） |

树稳定检查：最新产品改动为 panel/app.py（18:38:12 UTC），打包执行时刻计满 15 分钟（门 18:53:12 UTC）；其间只有 AUDIT-R18 的报告文件（docs/audit/AUDIT-R18.md）与本报告在写、产品文件无变动（live-10 同款口径）；`__pycache__` 为探针 import 产物、打包时剔除。打包时源码树 `panel/data/` 为空（`ls` 空）；毒 panel.db＋agent_queue.json 由 AE 的真实代码毒快照（`~/workspace/ae-tests/poison/`）注入打包副本，**源码树本身未被毒化**。

**打包（18:53:28 UTC）**：传包走 scp（R4–R11 同款）。`ovpn-r12.tar.gz`：41 条目，194,845 字节，sha256 `6dde7a4be6c28f51870e8d4f3996e66b3e29b01243598a97f356bb556c204d56`（机上核对一致）；install.sh sha256 `3f050f037e7a4eba992716aff5d8f54ed746c2769c6fd224d55da696d3d468de`。包内毒物核对：`panel/data/panel.db` 含 admin 行 1 条（哈希 `$2b$12$tceqe…`）、`panel/data/agent_queue.json` 含 3 条 init_pki force+confirm（action 均为 init_pki）——与 R8 §6.2 的毒形一致。另记：打包执行前 1 分钟（18:51:57 UTC）树内新落 `tests/r18_worker_queue_race.mjs`（探针资产，非产品文件、不在安装子集内，不影响打包内容；产品文件稳定时钟仍以 panel/app.py 18:38:12 UTC 计，打包时稳定 15 分 16 秒）。

**沙箱预验（打包前，§7 两层逻辑逐字提取，`/tmp/r12/gate7.sh`）**：干净树 **[PASS] 逐键相等**；字典 sing-box 两项互换（常量不动）→ **[FAIL] 逐键不等**；字典 tun2socks 两项互换 → **[FAIL]**；常量 sing-box 两项互换 → **[FAIL]**。BE 的第二层在沙箱四格上成立。注：整套 `verify-integration.sh` 未在沙箱重跑——与并行在跑的 AUDIT-R18 共用固定 `/tmp/ovpn-int-test` 与 8443，两路同跑会互删测试目录（本轮第一跑即因此 SKIP/401 串）；沙箱门禁 29/29 以主控 02:40 核验为准（BG/BH 完工后亲手跑过）。

## 1. 地面真值（Lightsail 现状，测试前实测，18:41–18:43 UTC）

- 机上是**第十一轮收尾态**：安装 #1＋headline-9 默认重跑后状态。五服务全部 active（openvpn PID 864832 TCP 443、panel PID 868048 8443、sing-box、agent、dante 127.0.0.1:11080）；SK5 禁用；节点 lightsail 已注册、last_seen 新鲜（18:43:30）；用户 alice/bob 有效；ufw 启用、4015 行；CA 序列 `6D361E72…`（notBefore 2026-11-12 18:12:23）；admin 哈希 `$2b$12$DZaXI…`（live-11 新建、非毒 `$2b$12$tceqe…`）；audit_log 50 行；队列 lightsail []、仅 1 条 done 命令（get_status）。
- 第十一轮残留全部在位，**重装前必须清除**：`/root/r11/` 测试产物在位（cdp.py、client 日志、d13a/d13b、h9tree、install.log、jar.txt、netns.sh 等）；`/root/ovpn-r11.tar.gz`（毒包，证据，**勿删**）、`/root/ovpn-r10.tar.gz`、`/root/ovpn-r9.tar.gz`、`/root/ovpn-r8.tar.gz`、`/root/ovpn-r7.tar.gz`、`/root/ovpn-r7b.tar.gz`、`/root/ovpn-r2.tar.gz` 在位；`/opt/openvpn-sk5-panel/` 为第十一轮装树；`/etc/openvpn-sk5-panel/` 含 admin.pass（0600）；`/etc/openvpn/server/server.conf` 为 `port 443 / proto tcp / server 10.8.0.0 255.255.255.0`。
- netns `vpntest` 仍在（live-11 收尾遗留）；TCP 客户端 PID 865181 仍连（live-11 终态）。
- FLMX 同机在跑（paneld PID 2193899、flmx_agent 多进程、sing-box 1.14.4、docker flmx-panel-frontend/backend Up 24h），**一律不碰**；`/root/flmx-panel` 不动。

## 2. 清场（全新重装前，18:53 UTC）

- 先杀 live-11 遗留 TCP 客户端（精确 PID 865181，`kill`＋`kill -9` 确认消失）、删 netns `vpntest`。
- 四服务已停（openvpn/panel/singbox/agent 全部 inactive，dante 保留，active）；无残留客户端进程。
- FORWARD 链 tun0 产品规则 0 条残留、NAT POSTROUTING 的 `-s 10.8.0.0/24 -o ens5 MASQUERADE` 已删；其余 ts-forward/DOCKER-USER/DOCKER-FORWARD/ufw 段不动。
- 状态已 wipe：`/root/openvpn-sk5-panel`、`/opt/openvpn-sk5-panel`、`/opt/ovpn-agent`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/ovpn-agent` 全删；sing-box 与 tun2socks 二进制已删（逼安装器走下载路径，复验版本校验）；`/root/r11/`、全部证据 tarball 保留未动。
- 清场后核对：无 tun0/tun1、无 1194/443/8443 监听、`/opt/openvpn-sk5-panel` 与 `/etc/openvpn-sk5-panel` 不存在。
- S0 安装已于 18:53 UTC 后台启动（`nohup bash install.sh`，日志 `/root/r12/install.log`，安装器 PID 881031）。

## 3. S0 基线：毒包安装 + 建服务 + 建用户 —— 通过（首次安装死在转发门、重跑一次通过；AN 新行在位）

### 3.0 第一次安装（毒包，全新安装，UDP 1194 默认）—— 转发门 transient 失败后重跑通过

- install.log 前段全绿：sing-box 1.11.15 下载 `sha256 OK`、tun2socks 2.7.0 下载 `sha256 OK`；pip 依赖已满足（flask 3.1.3、bcrypt 5.0.0）；五单元 steady（openvpn/panel/singbox 均 active、restarts=0）；面板 health gate 通过（login + /api/status 200）。
- **首次安装死在最后一步**：`[install] ERROR: health gate: route lookup for VPN source 10.8.0.1 does not resolve via ens5 (1.1.1.1 from 10.8.0.1 via 172.26.0.1 dev ens5 uid 0 cache)`——全日志仅 1 个 ERROR，无完成横幅，安装器退出。**但打印出的路由值本身含 `dev ens5`**：机上逐字复现同一谓词（`printf '%s' "$FWD_ROUTE" | grep -q "dev $WAN_IF"`，WAN_IF=ens5）为 GREP_MATCH；把 die 信息里的精确多行字符串（含 `\n    cache `）拿来复测亦为 EXACT_STRING_MATCH。安装时那次失败的机制无法从现有证据重建（打印值含匹配串、谓词现时必过）——**记为 transient，不立案**（无机制、无复现；见下重跑）。
- **重跑（同一毒树默认重跑，见 §11.6）一次通过**：`bash install.sh` → **ERROR 0**、完成横幅已印；`forwarding gate passed (FORWARD rules present; VPN source routes via ens5: 1.1.1.1 from 10.8.0.1 via 172.26.0.1 dev ens5 uid 0 cache)`——与首次死掉时打印的路由值逐字相同；openvpn PID 881847、panel PID 882013 均未变（重跑未重起守护进程）。AZ 先例（health-gate 瞬态失败、串行重跑通过）同款处置。
- **毒物未入住（AN 新行为）**：重跑日志有新行 `[install] panel/ installed (panel/data/ excluded: …)`（1 条）；旧 `discarded shipped runtime file` 行 **0 条**；装后 `/opt/openvpn-sk5-panel/panel/data/` 仅含 panel.db，**agent_queue.json 文件不存在**（毒队列从未拷入）；panel.db 的 admin 行哈希为 `$2b$12$66jKa…`，与毒哈希 `$2b$12$tceqe…` 不同——全新 admin 行；nodes 0、audit 1 行（安装器 health-gate 登录）、login_attempts 0 行。
- 五单元：openvpn/panel/singbox active，agent inactive（属预期，由 S0-agent 安装）；CA 序列 `1736E0DAA91FA4208CD9D31791975507D1054882`（新 CA，记下供 agent 轮询后对比）。
- ufw 回归格（AN 的 R8-BUG-2 反面）：安装器日志 `ufw is installed -- skipping iptables-persistent`，apt 后 `ufw still installed`；机上 ufw 在位（`ufw status` 4015 行）；iptables-persistent 未装（ufw 机跳过，属预期）。

### 3.1 S0 后半段：建服务确认＋建用户 —— 通过

- 面板登录 200；`/api/status` 200：openvpn running（UDP 1194，PID 881847），online_users 0，SK5 未启用，`singbox_running: true`，sk5 块 `policy_routing_active: false`。
- 默认 `.ovpn` remote 为 **16.146.199.68 1194**（IPv4 公网）。
- 用户：alice、bob 创建均 200；`GET /api/openvpn/users` 只列 alice、bob，alice 序列号 `3BF75551935780809EFAFCA2DB8B15DA`、bob `A0815598D01849E09F24521782049C2B`；`.ovpn` 下载 200，`proto udp / remote 16.146.199.68 1194`。测试侧注记：首建用错字段名 `username` 得 400（端点读 `name`），改 `name` 后 200，非产品问题。
- **观察（不立案）**：`/api/status` 的直接出口探测返回 IPv6 地址 `2600:1f13:14d:a300:7913:f273:997e:c8b8`（本机有 IPv6，探测走了 v6）；live-9 同格为 IPv4 16.146.199.68、live-10/live-11 同款 IPv6。数据面实测（S1/S2）仍以 IPv4 出口为准，面板 `egress.ip` 的 v4/v6 取值未作断言。

## 4. S0-agent：节点注册 + agent 安装 + 命令链 —— 通过（第二毒物 agent 侧终验通过）

- 注册：`POST /api/nodes {"name":"lightsail","panel_url":"https://172.26.15.152:8443"}` → 201，token 只存 `/root/r12/token.txt`（未写报告）。中途一次 tssh 隧道瞬断（proxy closed during CONNECT），重发即通，测试侧通道问题，非产品问题。
- 安装命令（面板两步走命令，按 agent/README 记载的流程执行；token 由文件读入）：`curl -ksSL https://172.26.15.152:8443/install-agent.sh`＋`install-agent.sh.sha256` 校验 `install-agent.sh: OK`＋`bash /tmp/install-agent.sh --panel-url … --token … --node-name 'lightsail'` → **EXIT=0**。bundle sha256 OK、`/etc/ovpn-agent/config.json` 0600、`ovpn-agent is ACTIVE (node=lightsail)`。
- poll：`GET /api/nodes` 的 `last_seen` 为 2026-11-12T19:01:14+00:00（新鲜），心跳合并 `last_status`（hostname/version/openvpn_running/sk5_enabled）；agent 日志 0 条 401/403、无 poll failed、无 init_pki。
- **毒 init_pki 未执行**：agent 上线并轮询后，CA 序列仍为 `1736E0DAA91FA4208CD9D31791975507D1054882`（与安装时一致）；面板 `agent_queue.json` 现为 `{"queue": {"lightsail": []}, "cmds": {}, "ovpn": {}}`——init_pki 0 条。
- 命令链：`POST /api/cmd {"node":"lightsail","action":"get_status"}` → **202**（cmd_id cae2b81a…）；约 3 秒后 `GET /api/cmd/<id>` → **done**，error null；result 含 openvpn running=true pid 881847（与面板一致）、sk5 enabled=false。

## 5. S1 直连态（UDP 1194）—— 通过（首次即通，零手工 FORWARD）

- 客户端（alice，netns vpntest，`--float`）：改 remote 为 LAN IP 172.26.15.152（R7 同款，公网 IP 发夹在 netns 内受限，非产品问题），**首次即通**，`Initialization Sequence Completed`（19:02:31），tun0 10.8.0.2/24，redirect-gateway 路由就位。PID 885675。测试侧注记：首次启动因 panel.py 的 4000 字符截断打印导致 .ovpn 截断（`Endtag </cert> missing`）而死——改 curl 直取完整 .ovpn（8608 字节、2 个 CERTIFICATE 块）后即通，非产品问题。
- 数据面（direct）：`curl ifconfig.me`（HTTP 与 HTTPS，--resolve 绕 MagicDNS）→ **16.146.199.68**；`dig @1.1.1.1 ifconfig.me` → 34.160.111.145 有回包；NTP UDP：216.239.35.4 回 **48 字节** 12.7ms、162.159.200.1 回 **48 字节** 6.1ms。UDP 数据面通过。
- **BUG-9 第十二次复验——修好（UDP 模式）**：部署态原始日志（逗号 v2，13 段）为 `CLIENT_LIST,alice,10.200.0.2:60315,10.8.0.2,,6242,11016,2026-11-12 19:02:31,1794510151,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users` = **1**；`clients`=[{name: alice, real_address: 10.200.0.2:60315, virtual_address: 10.8.0.2, bytes_received: "6242", bytes_sent: "11016", connected_since: "2026-11-12 19:02:31"}]——逐字段一致；`/api/openvpn/users` 的 alice `online: true`、bob `online: false`（本节实测）。时序注记：连接后 18 秒（19:02:49）首次查面板为 online_users 0——状态文件约 60 秒一刷（19:02:51 写盘），复查即为 1；刷新间隔所致，非产品问题。

## 6. S2 落地态（SK5 开）—— 通过（TCP+UDP 均走 SK5，双日志为证）

- 开启（全新安装后第一次启用）：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功）；enabled=true，`policy_routing_active: true`，egress_ip 16.146.199.68；`ip rule` 有 `from 10.8.0.0/24 lookup 100`；table 100 为 `default via 10.9.0.1 dev tun1`；`ip route get 1.1.1.1 from 10.8.0.1` → `dev tun1 table 100`；tun1 UP。alice 的隧道在开启前后未断（同一客户端 PID 885675 持续）。
- 面板 `POST /api/sk5/test` → **tcp_ok: true（95.8ms）、udp_ok: true**（native 模式，UDP ASSOCIATE + DNS to 1.1.1.1:53）。
- 客户端 TCP（经 SK5）：`curl --resolve ifconfig.me:80:34.160.111.145 http://ifconfig.me` 与 HTTPS 同式均回 **16.146.199.68**；sing-box 日志同秒有 `outbound/socks[bought-sk5] … to 34.160.111.145:80` 与 `:443`；dante 日志（syslog）同窗口有 `tcp/connect … 34.160.111.145.443`——TCP 确实走了 dante（SK5 替身）。出口 IP 不变属预期：替身与面板同机，S1/S2 出口恒为 16.146.199.68，链路证明以路由表 + 双日志为准（R1 已定口径）。
- 客户端 UDP（经 SK5）：NTP 到 216.239.35.4 回 **48 字节** 32.6ms、162.159.200.1 回 **48 字节** 28.9ms；sing-box 日志有 `outbound/socks[bought-sk5] … outbound packet connection to 216.239.35.4:123` 与 `162.159.200.1:123`；dante 日志同窗口有 `udp/udpassociate`。UDP 走 SK5 为证。

## 7. S3 断网保护（杀 dante）—— 通过（数据面全断、无直连回落、自动恢复、隧道不断）

- 杀 dante（`systemctl stop danted`，inactive）：客户端 TCP `curl --resolve … http://ifconfig.me` → **exit 56**（Recv failure），HTTPS → exit 35（SSL connect error，同样失败）；NTP UDP 到 216.239.35.4 → **TimeoutError**，162.159.200.1 同样 TimeoutError；**无直连回落**（curl 不是成功、是失败——fail-closed 成立）。隧道未断（同一客户端 PID 885675，tun0 仍在，`Initialization Sequence Completed` 仅 1 次）。
- 面板 `/api/status`：kill 期间 **egress.ip = null**（`{'error': None, 'ip': None, 'latency_ms': None, 'via_sk5': True}` 形状同 live-9/live-10/live-11），诚实报空。
- 恢复（`systemctl start danted`，active）：客户端 TCP 立即回 **16.146.199.68**，NTP 回 **48 字节** 17.3ms/9.4ms。隧道全程未断：同一 PID 885675，client.log 里 `Initialization Sequence Completed` 仅出现 1 次、SIGUSR1 0 行——无重连、无重拨。
- 口径注记（设计，非缺陷）：kill 期间 `dig @1.1.1.1` 仍有回包——sing-box 路由规则 `protocol dns / port 53 → direct`（见 `/etc/openvpn-sk5-panel/sing-box.json`），DNS 默认走直连、不经 SK5，是文档已定设计；断网保护覆盖的是 TCP/UDP 数据面，DNS 不在黑洞范围内。

## 8. S4 TCP 备模式（443）—— 通过（BUG-14 修好，S1/S2 各重跑一次）

- **BUG-14 修好**：`POST /api/openvpn/server {"proto":"tcp","port":443,"allow_port_change":true}` → **HTTP 200**。`POST /api/openvpn/restart` → 200（新 pid 886611）。TCP 443 监听，UDP 1194 监听消失，`/api/status` 为 proto=tcp port=443 running=true；新下载的 alice.ovpn 为 `proto tcp / remote 16.146.199.68 443`（默认 remote 仍是 IPv4 公网）。SK5 保持开启态。
- **TCP 首连 120s 超时跟进——未复现（5 次全部 1 秒）**：5 次全新 TCP 首连全部 **1 秒内** `TCP connection established`＋`Initialization Sequence Completed`（19:04:28、19:04:34、19:04:40、19:04:46、19:04:52，各 1s）。R7 的 120s 超时单次事件本轮未再出现（第五轮未复现）。切 TCP 前已按 live-9/live-10/live-11 教训先杀旧 UDP 客户端（PID 885675，tun0 消失确认），无测试侧失误。
- S2-TCP（SK5 开）：新 TCP 客户端连上（19:05:04，tun0 10.8.0.2/24，PID 886958）；curl → 16.146.199.68；NTP → 48 字节 28.7ms/10.0ms；dante 日志同窗口有 `tcp/connect`/`udpassociate`——TCP+SK5 链路在 TCP 模式下同样成立。
- BUG-9（TCP 模式）：原始日志 `CLIENT_LIST,alice,10.200.0.2:57732,10.8.0.2,,6543,11940,2026-11-12 19:05:04,1794510304,UNDEF,5,0,AES-256-GCM`；面板 `/api/status` 的 `online_users`=**1**，`openvpn.detail.clients`=[{name: alice, real_address: 10.200.0.2:57732, virtual_address: 10.8.0.2, bytes_received: "6543", bytes_sent: "11940", connected_since: "2026-11-12 19:05:04"}]——逐字段一致。**BUG-9 第十二次复验在 UDP 与 TCP 两种模式下均修好**。
- S1-TCP（SK5 关）：单字段 `{"enabled":false}` → 200（disable 后 sing-box 仍在 direct 模式跑，R3-BUG-1 修好）；rule 100 消失、table 100 空（0 行）、路由回 ens5；TCP 客户端 curl → 16.146.199.68，NTP → 48 字节 12.9ms/6.2ms，dig @1.1.1.1 → 34.160.111.145；同一客户端 PID 886958 全程未断（`Initialization Sequence Completed` 仅 1 次）。

## 9. R16-P2-1 双架构安装格 —— 通过（字典绑定情形，amd64 双二进制）

### 9.1 门禁 §7 两层在真机上 —— 通过（干净树 PASS、两棵字典互换树仅 §7 格红）

- §7 原格逻辑（自现树 `verify-integration.sh` §7 块逐字复制，`/root/r12/gate7.sh`，含 BE 第二层）在机上跑三棵树（均自本轮打包树解出）：干净树 `/root/r12/tree-clean` → **[PASS] 逐键相等**（rc=0）；字典互换树 `/root/r12/tree-dict-sb`（`_PINNED_SHA256` 里 sing-box 两项值互换、常量逐字不动）→ **[FAIL] 逐键不等**（rc=1）；字典互换树 `/root/r12/tree-dict-t2`（tun2socks 两项值互换、常量逐字不动）→ **[FAIL] 逐键不等**（rc=1）。**BE 的第二层（字典绑定校验）在真机 §7 格上成立；R16-P2-1 的盲区已关。**
- 运行时绑定直测：`/root/r12/tree-dict-sb` 的 `_pinned_sha256("sing-box","amd64")` 返回 `20a6a9cd…`（arm64 哈希），干净树返回 `950af37e…`——与 R16 报告的后果一致。

### 9.2 amd64 后果格：字典互换后安装校验 fail-closed —— 通过（sing-box＋tun2socks 双二进制）

- sing-box（真实 tarball `/root/r11/sing-box-1.11.15-linux-amd64.tar.gz`，12,343,812 字节，sha256 `950af37e…`＝钉死 amd64 哈希；agent 真实校验路径 `_expected_sha256`＋`_verify_file`，`/root/r12/agent_hash_demo.py`）：干净 agent.py → pinned==real、**VERIFY: OK**；字典互换 agent.py → pinned-for-amd64 为 `20a6a9cd…`（arm64 哈希）、**RuntimeError: `sha256 mismatch … -- refusing to install`**——amd64 节点 agent 安装校验 fail-closed 死在安装时，与 R16 定性一致。
- tun2socks（真实 zip 新下载自 release URL，`tun2socks-linux-amd64.zip`，4,595,237 字节，sha256 `a612baa2…`＝钉死 amd64 哈希；同款 `_expected_sha256`＋`_verify_file` 路径）：干净 agent → pinned==real、**VERIFY: OK**；字典互换 agent → pinned-for-amd64 为 `3931476c…`（arm64 哈希）、**RuntimeError: `tun2socks-linux-amd64.zip sha256 mismatch … -- refusing to install`**——fail-closed。
- **arm64 格记未验**：机为 x86_64、无 arm64 真机／模拟器（`uname -m` x86_64，`qemu-aarch64` 不存在）；arm64 侧绑定错位对称于 amd64（同一 `_PINNED_SHA256` 查表路径），但无真机证据，不冒充。
- 观察（R16 §2.3 已记、不立案）：install.sh 的两处 case 映射互换（m-bc6）不在 §7 宣称的 invariant 内，门禁覆盖边界；下载路径的绑定由本节真实下载＋校验覆盖。

## 10. R17-P1-1 真机格（Flask 面）—— 通过（(a)(b)(c) 全过；Worker 面未验）

- 手段（live-11 §9.1 U1 同款）：停 ovpn-agent 防 poll 写竞态；备份队列到 `/root/r12/queue-before.json`；手工注入 failed 态 init_pki（force+confirm，id `c-r17fail`，error 为 sweep 同款「队列条目损坏（缺少 status），已隔离，不再下发」）并补一条 `queue_cmd_malformed` 审计行（模拟 sweep 隔离）；随后以 curl 扮 agent（Bearer 节点 token＋`panel_url` 认领）直接读 poll 响应——不靠推断。
- **(a) failed 态 init_pki 不下发**：poll-1 响应 `commands` 仅含正常 get_status（`5077132d…`），**不含 c-r17fail**；查态：c-r17fail 仍 **failed**、sent_at null、error 原文在位；真 agent 重启后跑 3 轮 poll（last_seen 19:09:51 新鲜）：CA 序列号前后一致 `1736E0DAA91FA4208CD9D31791975507D1054882`（与 S0 新装 CA 同值），agent 日志 `init_pki` 出现 **0 次**——最坏后果（重建 CA、用户证书全死）未发生。BG 修后行为（循环顶 `status != "queued": continue`）在真机上成立。
- **(c) 正常命令下发一次且翻 sent、第二轮不重复**：poll-1 后 get_status `5077132d…` 为 **sent**、sent_at 19:09:08；poll-2 响应 `commands: []`——无重复下发。
- **时序**：注入 19:07:00 → 入队 get_status 19:08:59（202）→ poll-1 19:09:08（commands 仅 get_status，翻 sent）→ poll-2（commands []）→ 入队 cmd2（202）→ report 409 → poll-3 19:09:26（commands 含 cmd2，翻 sent）。
- 真 agent 重启后跑 3 轮 poll（last_seen 19:09:51 新鲜），CA 序列号不变、日志 init_pki 0 次；随后队列恢复注入前备份（19:10:02）。
- **(b) queued 命令先报 failed 应 409 拒收、随后 poll 合法下发**：新入队 get_status `671ab64e…`（queued）；未 poll 即以 agent 身份 `POST /api/agent/report {id, ok:false}` → **HTTP 409** `{"error":"命令未下发（status=queued），回执不予接受"}`；查态仍 **queued**、sent_at null、error null；poll-3 响应含该 id，查态翻 **sent**、sent_at 19:09:26——按 BG 修后行为验（report 拒收非 sent 回执＋409 审计），不按旧断言。
- 收尾：队列已恢复注入前备份（`queue: {"lightsail": []}`），agent 重启 active、last_seen 19:10:02 新鲜、CA 序列号仍 `1736E0DA…`。**Worker 面记未验**：无真实 Worker 部署，BH 的同款修复只在沙箱探针 20/20（主控核验），不在本轮真机格内。

## 11. headline 回归精选 —— 通过（6 项全过）

### 11.1 headline-1 首启一次 200 —— 通过（首启一次 200；10 次交替全一次 200，delta 恰 10）

- **首启（全新安装后第一次启用）**：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功，§6）。**R6-BUG-1 真机回归通过**。
- **10 次交替**（从禁用态起，奇数步全表单启用、偶数步单字段禁用，均为真实翻转）：10 步全部 **200**（一次成功），Started 86→96（**delta 恰 10**，每步一次重起），终态禁用。计数口径：journalctl 里 `Started openvpn-sk5-singbox.service` 行数（live-8/9/10/11 同口径；`systemctl show NRestarts` 恒 0，不用它）。

### 11.2 headline-3 并发启用 delta 恰 1 —— 通过（双 200，delta 恰 1）

- 从禁用态起，两路 `POST /api/sk5 {"host","port","enabled":true}` 同时发出 → **双 200**（线程并发重跑取证），Started 100→101（**delta 恰 1**），终态 enabled=true、policy=true、via=true、ip=16.146.199.68。AH 的 `_SK5_MUTATE_LOCK` 在真机并发路径上成立。**R7-BUG-3 真机终验通过**。
- 时序澄清（第一轮并发取证时 shell 后台重定向未留码、且 19:12:11 同秒出现两行 Started，曾疑 delta 为 2）：已隔离重跑——先单步禁用读数（Started 99→100，禁用本身重起一次），再并发启用读数（100→101，delta 恰 1）；19:12:11 的两行 Started 分别是禁用的重起与并发对的唯一一次重起同秒落地。
- 审计三证：并发对的两行 `sk5_save`（19:11:41 ×2、19:12:12 ×2）各只对应一行 Started（19:11:40、19:12:11 之一）；禁用步的 `sk5_save` 为 toggle-only（19:11:15、19:12:11）各对应一行 Started。**无外部 actor、无交叉干扰**；面板、agent、健康检查均无自发 POST /api/sk5 的路径（live-11 已核）。

### 11.3 headline-5 policy-missing 诚实＋零重起修复 —— 通过（两次复现均诚实＋零重起修复）

- 策略删掉（`ip rule del from 10.8.0.0/24 table 100`＋`ip route flush table 100`）后 25 秒查面板：`via_sk5=false`、`egress.ip=None`、error=**“SK5 已启用但策略路由未生效，出口未经过 SK5”**、`policy_routing_active=false`（enabled 仍 true）——诚实报缺策略，未谎称经 SK5。
- 全表单重开 → 200，收据 **`repaired: true`、`repair_detail: ["policy routing re-applied"]`**，Started 101→101（delta=0，**零重起补策略**）、MainPID 891426 不变；恢复后 rule 100＋table 100 均在位，`via_sk5=true`、ip=16.146.199.68。
- 复现一次：第二次删策略→重开同样 `repaired: true`＋`repair_detail: ["policy routing re-applied"]`、Started 101→101、MainPID 891426 不变——修复收据可重复。TCP 客户端 PID 886958 两轮全程未断。

### 11.4 headline-6 verify.sh 双态 —— 通过（开态 18/0/4、关态 23/0/0）

- **开态**（SK5 开）：`bash verify.sh` → **PASS=18 FAIL=0 SKIP=4，VERIFY: ALL GREEN**（与 R5–R11 开态 18/0/4 一致；4 个 SKIP 为开态下跳过的 toggle 格，属设计）。
- **关态**（面板关 SK5 后 25 秒再跑）：`bash verify.sh` → **PASS=23 FAIL=0 SKIP=0，VERIFY: ALL GREEN**。R5-BUG-1 的关态天花板（22/1）继续不存在。关态跑完后 SK5 为禁用（verify.sh 的 enable 探针自带清理禁用）。

### 11.5 headline-7 前端真渲染 —— 通过（真渲染：0 项低于 4.5，最薄 4.92；零 JS 异常）

- **真渲染方法**：复用 live-10 的 CDP 驱动（`/root/r12/cdp.py`，路径改 r12）：带 session cookie（`/root/r12/jar.txt`）进已登录仪表盘，1440×900 真渲染后，页内 JS 逐元素取 computed style、沿 rgba 栈合成到 body 底色、算 WCAG 对比度，并抓 console 事件与截图（`/root/r12/render/dashboard.png`、`render-contrast.json`）。
- **结果**：低于 4.5 的元素 **0 项**（`below45: []`），最薄 4.92（“当前 .ovpn 的 remote 为公网地址…”绿字 rgb(21,128,61) on rgba(252,253,254)，ratio 4.92）；低于 7 的 32 项（目标 7 未全达，同 live-9/10/11 口径）；console 事件 4 条——3 条浏览器 verbose 建议（密码字段不在 form 内、无 username 字段）＋1 条 favicon.ico 404，**零 JS 异常**（无 Uncaught/exception）。
- **自带自检**：`python3 panel/static/contrast-check.py` 在部署上跑 **10/10 PASS**（底线 4.5），目标 7 达成 4/10——与真渲染一致（live-9/live-10/live-11 同款：10/10、4/10）。

### 11.6 headline-9 毒树默认重跑行级比对 —— 通过（见 §3.0）

- 毒树默认重跑行级比对已在 §3.0 完成：admin 行字节一致、login_attempts 0 行、nodes 0 行、audit 仅新增重跑自身的合法登录行、CA 序列不变、conf 不变、agent_queue.json 仍缺席。**R8-BUG-1 真机终验通过**。

## 12. 新 bug 与观察项

- **新 bug：0 个。** 本轮无新立案。
- **观察 1（S0 首次安装死在转发健康门，未立案）**：首次安装 sole ERROR 为 `health gate: route lookup for VPN source 10.8.0.1 does not resolve via ens5`，无完成横幅；同一毒树重跑一次即通过，路由值字节一致。打印值本身含 `dev ens5`、谓词机上重放 GREP_MATCH、die 信息原文重放 EXACT_STRING_MATCH——属瞬态、机制未重建（AZ 同款先例，串行重跑通过）。重放证据：谓词 `ip route get 1.1.1.1 from 10.8.0.1 | grep -q "dev ens5"` 机上返回匹配；die 信息多行原文逐字节比对一致。不立案，记入本节备查。
- **观察 2（状态文件刷新间隔）**：OpenVPN 状态文件约 60 秒一刷；客户端连上后 18 秒查面板 online_users 仍为 0，复查即为 1。面板读数滞后于连接事件约一分钟以内，属刷新间隔所致，非产品问题。
- **观察 3（R16 §2.3，已记不立案）**：install.sh 的两处 case 映射互换（m-bc6）不在门禁 §7 宣称的 invariant 内；下载路径的绑定由 §9.2 真实下载＋校验覆盖。
- **观察 4（console 杂项）**：CDP 抓到 favicon.ico 404 一条＋密码字段不在 form 内的浏览器建议三条；无 JS 异常，不影响使用，不立案。
- **测试侧注记**：panel.py 的 4000 字符截断打印曾把 .ovpn 截断致客户端 `Endtag </cert> missing` 而死——改 curl 直取完整 .ovpn（8608 字节）后即通；工具侧问题，非产品问题。

## 13. 结论与机器终态

- **格汇总**：§3 S0 通过｜§4 S0-agent 通过｜§5 S1（UDP）通过｜§6 S2（SK5 开）通过｜§7 S3（断网保护）通过｜§8 S4（TCP 443）通过｜§9 R16-P2-1 通过（arm64 未验）｜§10 R17-P1-1 通过（Worker 未验）｜§11.1 首启＋10 交替通过｜§11.2 并发启用通过｜§11.3 policy-missing 两次通过｜§11.4 verify.sh 双态通过｜§11.5 前端真渲染通过｜§11.6 毒树重跑通过。**14 格通过、0 格失败、新 bug 0 个。**
- **结论：全部通过、零新 bug。** R16 的 1 条（字典绑定情形）与 R17 的 1 条（Flask 面队列守卫）真机行为格全过；S0–S4 与 headline 精选全过；新 bug 0 个。
- **R16-P2-1 闭环**：门禁 §7 两层在真机上——干净树 PASS、sing-box 字典互换树与 tun2socks 字典互换树仅 §7 格红；amd64 后果格双二进制——干净 agent 对真实 tarball VERIFY OK、字典互换 agent 均 RuntimeError `sha256 mismatch … refusing to install`（fail-closed）；arm64 格记未验（x86_64 机、无 qemu-aarch64）。
- **R17-P1-1 闭环（Flask 面）**：failed 态 init_pki（force+confirm）poll 不下发（CA 序列号前后一致 `1736E0DA…`、agent 日志 init_pki 0 次）；queued 命令先报 failed 遭 409 拒收、仍 queued、随后 poll 合法下发并翻 sent；正常命令下发一次翻 sent、第二轮 poll 不重复下发。Worker 面记未验（无真实 Worker 部署；BH 沙箱探针 20/20 已由主控核验）。**R18 的两条（BI 修）真机格属 live-13，不在本轮。**
- **回归**：S0 全新安装（毒包）、S0-agent（节点注册＋agent 安装＋命令链）、S1/S2/S3/S4（UDP 1194＋TCP 443 双模、SK5 TCP＋UDP 双栈、断网保护全断无回落且自动恢复、策略路由）与 headline-1/3/5/6/7/9 全部通过；U-5 致败格与 D13 并发安装不重复（live-10 已验，结论沿用）。
- **诚实未验**：arm64 安装格；Worker 面（R17-BH、R18-BI）；Cloudflare 真实部署（P0-1/2/3，仍卡登录＋KV 占位，需用户决断，已问五次未复）；IPRoyal 1001 vs 9000 哪个是 SOCKS5 端口（面板默认 1001，待用户填真实 SK5 后核）。
- **机器终态**（2026-11-12 19:13 UTC）：TCP 443 模式；openvpn-server PID 886611、panel 8443（PID 882013）、sing-box MainPID 891426、ovpn-agent active（last_seen 19:10:02 新鲜）、dante active；SK5 禁用（verify.sh 关态清理所致）；用户 alice/bob 有效；CA `1736E0DA…`；节点 lightsail 在线；ufw 4015 行；TCP 客户端 PID 886958 仍连在 netns vpntest（tun0 10.8.0.2）。证据在 `/root/r12/`；打包 tarball `/root/ovpn-r12.tar.gz`（sha256 `6dde7a4be6c28f51870e8d4f3996e66b3e29b01243598a97f356bb556c204d56`）。
- **证据清单**（`/root/r12/`）：`install.log`／`install-rerun.log`（两次安装全日志）、`h9-before.json`（毒树重跑前快照）、`queue-before.json`（§10 注入前队列备份，已恢复）、`gate7.sh`（§7 两层原格）、`agent_hash_demo.py`（amd64 后果格演示）、`panel.py`／`probe.sh`／`tcp-tries.sh`／`netns.sh`／`cdp.py`（测试工具）、`client-udp.log`／`client-tcp.log`／`client-tcp-try{1..5}.log`（客户端全日志）、`alice.ovpn`／`alice-tcp.ovpn`（完整配置文件，8608／8607 字节）、`render/dashboard.png`＋`render-contrast.json`（前端真渲染）、`tree-clean`／`tree-dict-sb`／`tree-dict-t2`（§9 三棵树）、`tun2socks-linux-amd64.zip`（4,595,237 字节，真实 release 包）。FLMX 同机进程（paneld、flmx-panel）全程未碰；证据 tarball `/root/ovpn-r7.tar.gz`～`/root/ovpn-r11.tar.gz` 均在位。

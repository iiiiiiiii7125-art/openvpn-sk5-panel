# OpenVPN 接 SK5 落地 · 真机复跑验证报告（第十七轮 R17）

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（BT 修复后的最新树——本轮第一次验证 R24-P2-1 的修复）。
> 验证人：真机复跑验证路（第十七轮）。日期：2026-11-12。
> **结论：全部通过，零新 bug。**——BT 真机格全过（§9：慢启动大声失败、楔死态一次 enable 恢复、健康检查删占位、三轮自动重启竞态、linkdown 拒认），S0–S4 全过，headline 六项全过（§10）。R24-P2-1 在真机上关闭。
> 前情：第十六轮见 [live-verify-R16.md](live-verify-R16.md)（全部通过、零新 bug；BP／BQ／BR／BS 四路修复的真机格全过、S0–S4 与 headline 精选全过）；AUDIT-R24（244 行，不能交付，差集 1 条 P2：R24-P2-1，enable 路径占位符写出的 linkdown 路由骗过 `_policy_active()`，链路永久卡死；修复 BT 路沙箱级已完工并主控核验）、AUDIT-R25 在跑——**本轮只验代码真机行为，不写审计结论**。

## 0. 树版本（本次装机所用）

| 文件 | mtime (UTC) | sha256（前 12 位） | 说明 |
|---|---|---|---|
| install.sh | 2026-11-12 16:46:54 | 3f050f037e7a | AZ 路（未动） |
| panel/app.py | 2026-11-12 21:59:34 | 40868bbfd8b9 | BQ 路（未动） |
| core/openvpn_manager.py | 2026-11-12 17:20:57 | 3b5d7dfe9ea1 | BB 路（未动） |
| agent/agent.py | 2026-11-12 19:50:12 | f303af828555 | BL 路（未动） |
| cloudflare/src/index.js | 2026-11-12 21:58:59 | f43180976393 | BR 路（未动） |
| egress/policy-routing.sh | 2026-11-12 22:36:25 | fbfb29a49164 | BT 路：`ensure_tun1`／`tun_exists` 删除，全树零 `tuntap add`；自检 grep 加 `grep -v linkdown` |
| egress/sk5_manager.py | 2026-11-12 22:35:55 | e209084f0915 | BT 路：`enable()` 等 LIVE tun1、5 秒超时大声失败；`_policy_active()` 拒 linkdown 行；`_tun1_dead_placeholder()`／`_remove_dead_tun1_placeholder()` 三重判死清死占位；`_apply_policy()` 默认动词改为 `repair` |
| panel/templates/index.html | 2026-11-12 15:21:57 | 4f7dc697451c | AR 路（未动） |
| verify.sh | 2026-11-12 14:45:28 | 7867f557c6bb | 主控（未动） |
| verify-integration.sh | 2026-11-12 22:36:32 | 2d110ff4ffec | BT 路：门禁桩同步（stub `ip link show` 报 live tun1、测试替身补 `repair` 分支） |
| egress/test-egress.sh | 2026-11-12 08:40:51 | d6db69ec0a6e | X 路（未动） |

树稳定检查：最新产品改动为 verify-integration.sh（22:36:32 UTC），打包执行时刻 23:37:58 UTC，**稳定 61 分 26 秒**（满 15 分钟门；live-11 差 12 秒的教训未重犯）。其间只有 AUDIT-R25 的报告文件与本报告在写、产品文件无变动；`__pycache__` 为探针 import 产物、打包时剔除（安装子集不含 tests/、docs/、cloudflare/）。打包时源码树 `panel/data/` 为空（`ls` 空）；毒 panel.db＋agent_queue.json 由 AE 的真实代码毒快照（`~/workspace/ae-tests/poison/`）注入打包副本，**源码树本身未被毒化**。

**打包（23:37:58 UTC）**：传包走 scp（R4–R16 同款）。`ovpn-r17.tar.gz`：41 条目，208,775 字节，sha256 `3ac83532ce015742b6803b603fd412508948ad23e09541b974ce8ac32c140543`（机上核对一致）；install.sh sha256 `3f050f037e7a4eba992716aff5d8f54ed746c2769c6fd224d55da696d3d468de`。清单与 R16 逐项一致（41/41 diff 空；首版 40 条因 rsync `--exclude 'tests'` 误排 `core/tests`，次版 42 条因多出 `.gitignore`，均已纠正重打）。包内毒物核对：`panel/data/panel.db` 含 admin 行 1 条（哈希 `$2b$12$tceqe…`，表 `admin`）、`panel/data/agent_queue.json` 含 3 条 init_pki force+confirm（action 均为 init_pki，1 sent＋2 queued）——与 R8 §6.2 的毒形一致。

## 1. 地面真值（Lightsail 现状，测试前实测，23:36 UTC）

- 机上是**第十六轮收尾态**：安装 #1＋headline-9 默认重跑后状态。五服务全部 active（openvpn-server PID 510 TCP 443、panel PID 511 8443、sing-box MainPID 26708、agent PID 516、dante PID 568）；SK5 禁用（verify.sh 关态清理所致，表 100 为空）；节点 lightsail 已注册；用户 alice/bob 有效，另有 verify-* 测试用户 4 个（verify.sh 的 user-ovpn 检查残留，2 valid、2 revoked，脚本只建不删，live-16 §14 已记）；ufw 启用、4015 行；CA 序列 `47503898D915C8FAA90FC789AEB36A6D65892C93`。
- 第十六轮残留全部在位，**重装前必须清除**：`/root/r16/` 测试产物在位；`/root/ovpn-r16.tar.gz`（毒包，证据，**勿删**）、`/root/ovpn-r15.tar.gz`、`/root/ovpn-r14.tar.gz`、`/root/ovpn-r13.tar.gz`、`/root/ovpn-r12.tar.gz`、`/root/ovpn-r11.tar.gz`、`/root/ovpn-r10.tar.gz`、`/root/ovpn-r9.tar.gz`、`/root/ovpn-r8.tar.gz`、`/root/ovpn-r7.tar.gz`、`/root/ovpn-r7b.tar.gz`、`/root/ovpn-r2.tar.gz` 在位；`/opt/openvpn-sk5-panel/` 为第十六轮装树；`/etc/openvpn-sk5-panel/` 含 admin.pass（0600）；`/etc/openvpn/server/server.conf` 为 `port 443 / proto tcp / server 10.8.0.0 255.255.255.0`。
- netns `vpntest` 仍在（live-16 收尾遗留）；TCP 客户端 PID 17332 仍连（live-16 终态）。
- FLMX 相关进程同机在跑（paneld、flmx-int2 paneld、flmx_agent、sing-box 1.14.4），**一律不碰**；`/root/flmx-panel` 不动。另有另一聊的节点连接日志审计工作残留（`/root/scratch-nodeconnlog/` 的 paneld／flmx_agent），**一律不碰**。

## 2. 清场（全新重装前，23:38 UTC）

- 先杀 live-16 遗留 TCP 客户端（精确 PID 17332，`kill`＋`kill -9` 确认消失）、删 netns `vpntest`（`ip netns list` 空）。
- 四服务已停（openvpn-server@server／panel／singbox／agent 全部 inactive，dante 保留，active）；无残留客户端进程（剩余 sing-box 进程为 FLMX 的 1.14.4，PID 26913，未碰）。
- FORWARD 链删 tun0 产品规则 2 条（`-d 10.8.0.0/24 -i ens5 -o tun0` conntrack 形＋`-s 10.8.0.0/24 -i tun0 -o ens5`）、NAT POSTROUTING 的 `-s 10.8.0.0/24 -o ens5 MASQUERADE` 1 条（删后两处计数均为 0）；其余 ts-forward/DOCKER-USER/DOCKER-FORWARD/ufw 段不动。
- 状态已 wipe：`/root/openvpn-sk5-panel`、`/opt/openvpn-sk5-panel`、`/opt/ovpn-agent`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/ovpn-agent` 全删；sing-box 与 tun2socks 二进制已删（`/usr/local/bin/sing-box`、`/usr/local/bin/tun2socks`，`find` 除 flmx 外为空，逼安装器走下载路径，复验版本校验）；`/root/r16/`、全部证据 tarball 保留未动。
- 清场后核对：无 tun0/tun1、无 1194/443/8443 监听、`/opt/openvpn-sk5-panel` 与 `/etc/openvpn-sk5-panel` 不存在。
- S0 安装已于 23:38:50 UTC 后台启动（`nohup bash install.sh`，日志 `/root/r17/install.log`，安装器 PID 29011）。

## 3. S0 基线：毒包安装 + 建服务 + 建用户 —— 通过（一次成功；AN 新行在位）

### 3.0 第一次安装（毒包，全新安装，UDP 1194 默认）—— 通过

- install.log：**0 个 ERROR**；sing-box 1.11.15 安装 `sing-box version 1.11.15`、tun2socks 2.7.0 下载 `tun2socks-linux-amd64.zip: OK`；完成横幅已印。
- **毒物未入住（AN 新行为）**：日志有新行 `[install] panel/ installed (panel/data/ excluded: …)`（1 条）；旧 `discarded shipped runtime file` 行 **0 条**；初始密码已生成并写入 `/etc/openvpn-sk5-panel/admin.pass`（0600，值不写入报告）。
- 装后核对：`/opt/openvpn-sk5-panel/panel/data/` 仅含 panel.db，**agent_queue.json 文件不存在**（毒队列从未拷入）；panel.db 的 admin 行哈希为 `$2b$12$AM3Qnw8v…`，与毒哈希 `$2b$12$tceqe…` 不同——全新 admin 行；nodes 0、audit_log 1 行（全新库）、login_attempts 0 行。
- 服务：openvpn-server@server active（UDP 1194，PID 29892）、panel active、sing-box active，agent inactive（属预期，由 S0-agent 安装）；CA 序列 `234EC8C2C63681296D1B5507F674348C32A138F0`（notBefore 2026-11-12 23:38:55，记下供 agent 轮询后对比）。
- ufw 回归格（AN 的 R8-BUG-2 反面）：机上 ufw 在位——安装后 `ufw status` 仍 4015 行；iptables-persistent 未装（`dpkg -l` 为 rc 残留配置，ufw 机跳过，属预期）。

### 3.1 S0 后半段：建服务确认＋建用户 —— 通过

- 面板登录 200；`/api/status` 200：openvpn running（UDP 1194，PID 29892），online_users 0，SK5 未启用，`singbox_running: true`，sk5 块 `policy_routing_active: false`。
- 默认 `.ovpn` remote 为 **16.146.199.68 1194**（IPv4 公网）。
- 用户：alice、bob 创建均 200；`GET /api/openvpn/users` 只列 alice、bob，alice 序列号 `2D39235E…`、bob `65E4D628…`。
- **观察（不立案）**：`/api/status` 的直接出口探测返回 IPv6 地址 `2600:1f13:14d:a300:7913:f273:997e:c8b8`（本机有 IPv6，探测走了 v6）；live-9 同格为 IPv4 16.146.199.68、live-10/live-11/live-12/live-13/live-14/live-15/live-16 同款 IPv6。数据面实测（S1/S2）仍以 IPv4 出口为准，面板 `egress.ip` 的 v4/v6 取值未作断言。

## 4. S0-agent：节点注册 + agent 安装 + 命令链 —— 通过（第二毒物 agent 侧终验通过）

- 注册：`POST /api/nodes {"name":"lightsail","panel_url":"https://172.26.15.152:8443"}` → 201，token 只存 `/root/r17/token.txt`（0600，未写报告）；随后 rotate 一次取新 token（长 43）再安装，测试侧流程，非产品问题。
- 安装命令（面板两步走命令，按 agent/README 记载的流程执行；token 由文件读入）：`curl -ksSL https://172.26.15.152:8443/install-agent.sh`＋`install-agent.sh.sha256` 校验 `install-agent.sh: OK`＋`bash /tmp/install-agent.sh --panel-url … --token … --node-name 'lightsail'` → **EXIT=0**。bundle sha256 OK、`/etc/ovpn-agent/config.json` 0600、`ovpn-agent is ACTIVE (node=lightsail)`。
- poll：`GET /api/nodes` 的 `last_seen` 为 2026-11-12T23:41:46+00:00（新鲜），心跳合并 `last_status`（hostname/version/openvpn_running/sk5_enabled）；agent 日志 0 条 401/403、无 poll failed、无 init_pki。
- **毒 init_pki 未执行**：agent 上线并轮询后，CA 序列仍为 `234EC8C2C63681296D1B5507F674348C32A138F0`（与安装时一致）；面板 `agent_queue.json` 现为 `{"queue": {"lightsail": []}, "cmds": {}, "ovpn": {}}`——init_pki 0 条。
- 命令链：`POST /api/cmd {"node":"lightsail","action":"get_status"}` → **202**（cmd_id 74cb65ad…）；约 3 秒后 `GET /api/cmd/<id>` → **done**，error null；result 含 openvpn running=true pid 29892（与面板一致）、sk5 enabled=false。

## 5. S1 直连态（UDP 1194）—— 通过（首次即通，零手工 FORWARD）

- 客户端（alice，netns vpntest，`--float`）：改 remote 为 LAN IP 172.26.15.152（R7 同款，公网 IP 发夹在 netns 内受限，非产品问题）。**测试侧失误（已修正，不立案）**：首轮直接在新建 netns 里起客户端，未跑 veth 建网脚本（`/root/r16/netns.sh`：veth-host 10.200.0.1/30 ↔ veth-cli 10.200.0.2/30＋默认路由＋FORWARD 规则），报 `Network is unreachable` 循环重起；杀掉失败客户端（精确 PID 31491）＋跑通建网脚本后重连，**首次即通**，`Initialization Sequence Completed`（23:43:10），tun0 10.8.0.2/24，redirect-gateway 路由就位（0.0.0.0/1＋128.0.0.0/1 via 10.8.0.1 dev tun0）。PID 31856。
- 数据面（direct）：`curl ifconfig.me`（HTTP 与 HTTPS，--resolve 绕 MagicDNS）→ **16.146.199.68**；NTP UDP：216.239.35.4 回 **48 字节** 13.8ms、162.159.200.1 回 **48 字节** 5.9ms。UDP 数据面通过。
- **BUG-9 第十九次复验——修好（UDP 模式）**：部署态原始日志（逗号 v2，13 段）为 `CLIENT_LIST,alice,10.200.0.2:55603,10.8.0.2,,6250,10989,2026-11-12 23:43:10,1794526990,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `openvpn.online_users` = **1**；`openvpn.detail.clients`=[{name: alice, real_address: 10.200.0.2:55603, virtual_address: 10.8.0.2, bytes_received: "6250", bytes_sent: "10989", connected_since: "2026-11-12 23:43:10"}]——逐字段一致；`/api/openvpn/users` 的 alice `online: true`、bob `online: false`（本节实测）。注：中途一次 tssh 代理断开（client_loop Broken pipe，测试侧通道问题），重连后复查，客户端仍在、状态文件已刷新，数字为重查实测值。

## 6. S2 落地态（SK5 开）—— 通过（TCP+UDP 均走 SK5，双日志为证）

- 启用：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → 200（`/api/status` 核 `policy_routing_active: true`、enabled: true）；`/api/sk5/test` → 200（tcp_ok，81.4ms；udp_ok，`mode: native`，native UDP ASSOCIATE + DNS to 1.1.1.1:53——非 TCP 承载冒充）。
- 路由（策略路由表 100）：`ip rule`（`from 10.8.0.0/24 lookup 100`）；表 100 `default via 10.9.0.1 dev tun1` **＋ `blackhole default metric 200`（BM 层 1 在真机上在位）**；`ip route get 1.1.1.1 from 10.8.0.1` → `dev tun1 table 100`；tun1 UP、LOWER_UP。
- 数据面（dante 本地测试 SK5，出口仍为本机 IP 16.146.199.68——属测试 SK5 的已知性质）：隧道内 curl ifconfig.me（HTTP 与 HTTPS，--resolve 绕 MagicDNS）→ **16.146.199.68**；NTP UDP：216.239.35.4 回 **48 字节** 25.2ms、162.159.200.1 回 **48 字节** 18.4ms（比直连态慢，符合 SK5 路径）。
- 双日志为证：sing-box 日志（23:44:58）明文记录 `outbound/socks[bought-sk5]: outbound connection to 34.160.111.145:80`、`:443`，以及 `outbound packet connection to 216.239.35.4:123` 与 `162.159.200.1:123`——**TCP 与 UDP 均真实走了 SK5 出站**；dante 日志同窗口有 11 行 `tcp/connect` 与 `udp/udpassociate`。

## 7. S3 断网保护（杀 dante）—— 通过（数据面全断、无直连回落、自动恢复、隧道不断）

- 杀 dante（`systemctl stop danted`，inactive）：客户端 TCP `curl --resolve … http://ifconfig.me` → **exit 56**（Recv failure），HTTPS → exit 35（SSL connect error，同样失败）；NTP UDP 到 216.239.35.4 → **TimeoutError**；**无直连回落**（curl 不是成功、是失败——fail-closed 成立）。隧道未断（同一客户端 PID 31856，tun0 仍在，`Initialization Sequence Completed` 仅 1 次）。
- 面板 `/api/status`：kill 期间 **egress.ip = null**（`{'error': None, 'ip': None, 'latency_ms': None, 'via_sk5': True}` 形状同 live-9/live-10/live-11/live-12/live-13/live-14/live-15/live-16），诚实报空。
- 恢复（`systemctl start danted`，active）：客户端 TCP 立即回 **16.146.199.68**，NTP 回 **48 字节**。隧道全程未断：同一 PID 31856，client.log 里 `Initialization Sequence Completed` 仅出现 1 次、SIGUSR1 0 行——无重连、无重拨。
- 口径注记（设计，非缺陷）：kill 期间 `dig @1.1.1.1` 仍有回包——sing-box 路由规则 `protocol dns / port 53 → direct`（见 `/etc/openvpn-sk5-panel/sing-box.json`），DNS 默认走直连、不经 SK5，是文档已定设计；断网保护覆盖的是 TCP/UDP 数据面，DNS 不在黑洞范围内。
- **本节只覆盖 SK5 死亡（dante 死）情形。sing-box 本体死亡情形见 §9 BT 真机格。**

## 8. S4 TCP 备模式（443）—— 通过（BUG-14 修好，S1/S2 各重跑一次）

- **BUG-14 修好**：`POST /api/openvpn/server {"proto":"tcp","port":443,"allow_port_change":true}` → **HTTP 200**。`POST /api/openvpn/restart` → 200（新 pid 32827）。TCP 443 监听，UDP 1194 监听消失，`/api/status` 为 proto=tcp port=443 running=true；新下载的 bob.ovpn 为 `proto tcp / remote 16.146.199.68 443`（默认 remote 仍是 IPv4 公网）。SK5 保持开启态。
- **TCP 首连 120s 超时跟进——未复现（5 次全部 0.11 秒）**：首版计时脚本用 `bc`（机上未装，live-15 同款坑）导致计时空白，5 次均已连上；改用 python 单调钟重跑，5 次全新 TCP 首连全部 **0.11 秒** `TCP connection established`＋`Initialization Sequence Completed`。R7 的 120s 超时单次事件本轮未再出现（第九轮未复现）。切 TCP 前已按 live-9/live-10/live-11/live-12/live-13/live-14/live-15/live-16 教训先杀旧 UDP 客户端（PID 31856，tun0 消失确认）。
- S2-TCP（SK5 开）：新 TCP 客户端连上（23:46:31，tun0 10.8.0.2/24，PID 33350）；curl → 16.146.199.68；NTP → 48 字节；sing-box 日志与 dante 日志同窗口有 SK5 出站记录——TCP+SK5 链路在 TCP 模式下同样成立。
- BUG-9（TCP 模式）：原始日志 `CLIENT_LIST,bob,10.200.0.2:43264,10.8.0.2,,4708,4454,2026-11-12 23:46:31,1794527191,UNDEF,10,0,AES-256-GCM`；面板 `/api/status` 的 `openvpn.online_users`=**1**，`openvpn.detail.clients`=[{name: bob, real_address: 10.200.0.2:43264, virtual_address: 10.8.0.2, bytes_received: "4708", bytes_sent: "4454", connected_since: "2026-11-12 23:46:31"}]——逐字段一致；`/api/openvpn/users` 的 alice `online: false`、bob `online: true`。**BUG-9 第十九次复验在 UDP 与 TCP 两种模式下均修好**。注：刚连上时面板 clients 为空，系 OpenVPN 状态文件约 60 秒刷新滞后（live-9 起的已知观察），65 秒后复查即一致。

## 9. BT 真机格 —— 通过（慢启动大声失败、楔死态一次 enable 恢复、健康检查删占位、三轮自动重启竞态全过、linkdown 拒认）

### 9.0 慢启动采样（a）—— 通过（5.24 秒大声失败、无占位、无策略改动、enabled 仍 False；随后正常 enable 即成）

- 前置：面板关 SK5（enabled=false、策略已清、sing-box 直连模式 MainPID 34397、表 100 空、无 rule）；测试侧在 sing-box 单元上加临时 drop-in（`/etc/systemd/system/openvpn-sk5-singbox.service.d/slow.conf`：`ExecStart=/bin/sh -c 'sleep 8; exec /usr/local/bin/sing-box run …'`），`daemon-reload` 后生效——`systemctl restart` 对 Type=simple 只等主进程 fork 即返，wrapper 睡 8 秒才 exec 真 sing-box，tun1 在 8 秒后才出现。
- `POST /api/sk5/enable` → **500**（耗时 5.24 秒），error 全文：`sing-box did not create a live tun1 within 5 s (no placeholder was created; check that sing-box is running and its tun inbound is configured -- see sing-box.log); enable aborted, no policy state changed`——与 BT 代码文案逐字一致。
- 失败瞬间核对：**无 tun1 设备**、无 vpn rule、表 100 空、sk5.json `enabled: false`——不建占位符、不改任何策略状态、enabled 保持 False。单元 ActiveState=active（wrapper 进程 MainPID 34523 在睡）。
- 约 8 秒后 tun1 自行出现 LIVE（UP,LOWER_UP，同一 MainPID 34523——exec 替换了 shell）；删 drop-in＋`daemon-reload` 后再 `POST /api/sk5/enable` → **200**（0.84 秒），enabled=true、policy=true、singbox=true。链路恢复后 TCP 客户端（PID 33350）curl 回 16.146.199.68，表 100 live 路由＋黑洞，NRestarts=0。

### 9.1 预制 K3 楔死态＋linkdown 拒认（d）＋一次 enable 恢复（b）—— 通过

- 预制（健康检查定时器先停，防 repair 档抢跑）：停 sing-box 单元（tun1 随 fd 关闭消失，rule＋黑洞仍在）；手工建占位 `ip tuntap add dev tun1 mode tun`＋`ip link set tun1 up`（`NO-CARRIER,POINTOPOINT,MULTICAST,NOARP,UP state DOWN`——死占位三重判死形）；`ip addr add 10.9.0.1/30 dev tun1` 后 `ip route add table 100 default via 10.9.0.1 dev tun1` 才成功（**测试侧教训**：裸占位无地址时 `via 10.9.0.1` 报 `Nexthop has invalid gateway`——网关须 on-link；旧 enable 路径的占位同样带地址，补地址后复现的内核态与 R24 探针一致）。表 100：`default via 10.9.0.1 dev tun1 linkdown`＋`blackhole default metric 200`；`ip route get 1.1.1.1 from 10.8.0.1` → `dev tun1`（linkdown 遮住黑洞）；sk5.json enabled=true。
- **（d）linkdown 拒认**：`GET /api/status` → `policy_routing_active: false`、`singbox_running: false`、`egress: {'error': 'SK5 已启用但策略路由未生效，出口未经过 SK5', 'ip': None, 'via_sk5': False}`——linkdown 路由不再骗过谓词，`via_sk5` 不撒谎。（`last_health` 仍为 23:49:40 的旧值，系定时器已停、无新档，非产品问题。）
- **（b）一次 enable 恢复**：`POST /api/sk5/enable` → **200**（0.91 秒），result `repaired: true`、`repair_detail: ["sing-box restarted"]`；占位被删、新 tun1 LIVE（UP,LOWER_UP，mtu 1400），表 100 live 路由＋黑洞、无 linkdown；sing-box MainPID 35242、NRestarts=0、`file exists`／`FATAL` 0 行；面板 enabled=true、policy=true、singbox=true。TCP 客户端 PID 33350 仍连，curl 回 16.146.199.68。

### 9.2 健康检查删占位（repair 路径）—— 通过（占位＋linkdown 路由均被删、报 kill-switch、下一档补路由）

- 再预制同一楔死态（停 sing-box、建占位＋linkdown 路由＋黑洞，23:50:51），直接触发健康检查单元（`systemctl start openvpn-sk5-healthcheck.service`，与定时器档同一代码路径，确定性触发）：服务 Result=success；**占位 tun1 被删**（`ip link show tun1` 无设备）、linkdown 路由被删，表 100 只剩黑洞；`last_health` 报 **`blackholed_kill_switch`**（23:51:01Z），detail：`sing-box not running; policy routing is not applied, VPN traffic is held by the fallback blackhole route in table 100 (not egressing direct); auto-repair: policy re-applied by health check (blackhole + rule in place; tun1 route waits for sing-box)`——含黑洞兜底、无「did not stick」。
- 手动重起 sing-box（MainPID 35606，干净启动，`file exists`／`FATAL` 0 行；定时器已恢复 active）：下一档（23:52:02Z）翻 **`policy_repaired`**（tcp_ok/udp_ok，egress=16.146.199.68），表 100 live 路由＋黑洞，curl 回 16.146.199.68，客户端 PID 33350 全程未断（`Initialization Sequence Completed` 仅 1 次）。

### 9.3 systemd 自动重启与 pre-clean 竞态（c）—— 通过（三轮全过，无楔死、无 StartLimitBurst、客户端全程未断）

- 第一轮（SIGKILL，23:52:48）：杀 MainPID 35606，8 秒内 systemd 自动重起（新 PID 36199，**NRestarts=1**，未触 StartLimitBurst 上限），tun1 LIVE；下一档（23:53:03Z）翻 **`policy_repaired`**（journal 明文：`policy was missing, auto-repaired by this check`），表 100 live 路由＋黑洞，curl 回 16.146.199.68。
- 第二轮（SIGKILL，23:54:21）：杀 MainPID 36199，8 秒内自动重起（新 PID 36808，**NRestarts=2**），tun1 LIVE；下一档（23:55:04Z）再翻 **`policy_repaired`**，curl 回 16.146.199.68。
- 第三轮（SIGTERM，23:55:52）：杀 MainPID 36808——sing-box 优雅退出 0，单元 inactive、**NRestarts 仍为 2（无自动重起，符合 SIGTERM 干净退出语义）**，tun1 消失且**无占位残留**，表 100 黑洞-only；随后两档（23:56:04Z、23:57:05Z）均报 `blackholed_kill_switch`（黑洞兜底文案），客户端 curl exit 28（流量被丢、无直连）；手动重起干净成功（新 PID 37972，`file exists`／`FATAL` 0 行），下一档（23:58:05Z）翻 **`policy_repaired`**，curl 回 16.146.199.68。
- 三轮全程：同一 TCP 客户端 PID 33350 存活，`Initialization Sequence Completed` 仅 1 次；单元从未落 failed；`file exists`／`FATAL` 全程 0 行。
- **R24-P2-1 在真机上关闭。**

## 10. headline 回归精选 —— 通过（六项全过；verify.sh 双态首轮即全绿）

### 10.1 headline-1 首启一次 200 —— 通过（首启一次 200；10 次交替全一次 200，delta 恰 10）

- **首启（全新安装后第一次启用）**：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功，§6）。**R6-BUG-1 真机回归通过**。
- **10 次交替**（脚本 `/root/r17/alt10-r17.sh`，从禁用态起，奇数步全表单启用、偶数步单字段禁用，均为真实翻转）：基线 Started 210 → setup disable 211 → 10 步逐格 212→213→214→215→216→217→218→219→220→221，**每步 +1，delta 恰 10**，10 步全部 200 一次成功。注：禁用步亦 +1——disable 同样重起 sing-box（重渲染直连模式配置），与 live-15/live-16 的逐格 +1 一致；`_start_singbox()` 的 `reset-failed` 使 11 次连续重起未触 StartLimitBurst。
- TCP 客户端 PID 33350 全程未断（`Initialization Sequence Completed` 仅 1 次）。

### 10.2 headline-3 并发启用 delta 恰 1 —— 通过（双 200，delta 恰 1）

- 从禁用态起（10.1 步 10 结束态），两路全表单启用同时发出 → **双 200**，Started 221→222（**delta 恰 1**），终态 enabled=true、policy=true、via=true、ip=16.146.199.68。AH 的 `_SK5_MUTATE_LOCK` 在真机并发路径上成立。**R7-BUG-3 真机终验通过**。
- TCP 客户端 PID 33350 全程未断。

### 10.3 headline-5 policy-missing 诚实＋零重起修复 —— 通过（手动删策略，面板重开零重起修复）

- **时序控制**：停定时器后确认 inactive，且上一档健康检查（00:03:09Z）已完成在删路由之前——无 live-16 接管轮的撞车失误；本轮一次跑出。
- **诚实**：定时器 inactive，手动删表 100 的 tun1 路由（表 100 只剩黑洞），13 秒后面板 `/api/status`：`via_sk5=false`、`egress.ip=None`、`policy_routing_active=false`（enabled 仍 true），未谎称经 SK5、未谎称黑洞。
- **零重起修复**：全表单重开 → 200，收据 **`repaired: true`、`repair_detail: ["policy routing re-applied"]`**，Started 222→222（delta=0，**零重起补策略**）；恢复后 rule＋table 100 均在位，`policy_routing_active=true`、curl 回 16.146.199.68。TCP 客户端 PID 33350 全程未断；事后定时器已恢复 active。

### 10.4 headline-6 verify.sh 双态 —— 通过（开态 18/0/4、关态 23/0/0，双态首轮即全绿）

- **开态**（SK5 开）：**PASS=18 FAIL=0 SKIP=4**，`VERIFY: ALL GREEN`。`direct-forwarding` 通过（FORWARD 规则在位；本轮无真实重启，AN 的 live-only 规则丢失限制未触发）。
- **关态**（面板关 SK5 后 25 秒再跑）：**PASS=23 FAIL=0 SKIP=0**，`VERIFY: ALL GREEN`。
- 两次输出均已落盘存档（机上 `/root/r17/r17-verify-open.txt`、`r17-verify-closed.txt`；live-16 接管轮“四次输出未落盘”的教训已补）。关态跑完后 SK5 为禁用（verify.sh 的 enable 探针自带清理禁用）。
- 测试侧残留：两次 verify.sh 的 user-ovpn 检查各留 1 个 verify-* 用户（verify-1794528280 valid、verify-1794528317 revoked，脚本只建不删，面板行为本身正常）。

### 10.5 headline-7 前端真渲染 —— 通过（真渲染：0 项低于 4.5，最薄 4.92；零 JS 异常）

- 真机 headless Chromium 渲染（1440x900，`render/dashboard.png`＋`render-contrast.json`，脚本为 cdp-r16.py 的 r17 路径版 cdp-r17.py）：标题 “OpenVPN + SK5 面板”、h1 “概览”；可见文本元素 **166 项，0 项低于 4.5**，最薄 **4.92**（“当前 .ovpn 的 remote 为公网地址 16.146.199.68，站外”，绿字白底）；32 项低于 7.0（目标值，非门禁底线；live-16 为 32 项）。注：元素数 166（live-16 为 166）系本轮渲染时 SK5 处于禁用态、面板少一组启用态文案，门禁项 0 低于 4.5 不变。
- 控制台事件 4 条：3 条 verbose 级 DOM 建议（密码字段不在 form 内等）＋1 条 favicon.ico 404（缺 favicon 资产）；**零 JS 异常**（无 Uncaught／exception 条目）。favicon 404 与 live-10–16 同款，记观察、不立案。

### 10.6 headline-9 毒树默认重跑行级比对 —— 通过

- 毒树（`/root/r17/install-src/openvpn-sk5-panel/`，含毒 panel.db＋毒 agent_queue.json）默认重跑 `bash install.sh`（无任何 flag，日志 `/root/r17/install-rerun.log`，AN 新行 1 条、ERROR 0、完成横幅已印；nohup 后台跑，中途一次 tssh 代理断开未断重跑进程，重连后复查已完成）。
- 行级比对（重跑前快照 `/root/r17/h9-before.json`）：admin 行**完全一致**（哈希仍为全新 `$2b$12$AM3Qnw8v…`，非毒 `$2b$12$tceqe…`）；login_attempts **一致**（0 行）；nodes **一致**（1 行 lightsail，name＋url 一致）；audit 39→40 行，**前 39 行完全一致**，新增 1 行仅为安装器自身的 panel 健康门登录（00:07:15，ip=127.0.0.1，install.sh:984 的 `/api/login` 自检，合法）；server PID 不变（32827，服务未重起）；`agent_queue.json` 的 cmds 仍仅 1 条合法 get_status（done），**毒的 3 条 init_pki 未入住**。
- **R8-BUG-1（毒树重跑销毁线上 panel.db）本轮终验通过。**附带：重跑日志明文 AN 限制（ufw 机 NAT／FORWARD 规则 live-only、不 survive 重启，须重跑 install.sh 补）与 FORWARD 规则已在位。

## 11. 结论与机器终态

**结论：全部通过，零新 bug。** BT 真机格全过（§9：慢启动大声失败、楔死态一次 enable 恢复、健康检查删占位、三轮自动重启竞态、linkdown 拒认），S0–S4 全过，headline 六项全过（§10）。R24-P2-1 在真机上关闭。AUDIT-R25 的差集不属本轮。

**机器终态（2026-11-13 00:08 UTC）**：TCP 443 模式（openvpn PID 32827，UDP 1194 已无监听）；面板 8443（PID 30016）；sing-box active（MainPID 42758，NRestarts=0）；agent active（PID 31133）；dante active（PID 32749）；健康检查定时器 active。SK5 **禁用**（关态 verify 清理后状态）；表 100 空、无 vpn rule。TCP 客户端 PID 33350 仍连接在 netns `vpntest` 里（`Initialization Sequence Completed` 全程仅 1 次，直连态 curl 回 16.146.199.68）。用户 alice／bob 有效，另有 2 个 verify-* 测试用户（1 valid、1 revoked，verify.sh 只建不删）。CA `234EC8C2C63681296D1B5507F674348C32A138F0`（与安装时一致，毒 init_pki 从未执行）。节点 lightsail 在线。ufw 4015 行。FLMX 同机进程未碰。证据在 `/root/r17/`（install.log、install-rerun.log、h9-before.json、alt10-r17.sh、netns.sh、cdp-r17.py、render/、client-tcp.log、token.txt 0600、r17-verify-open.txt、r17-verify-closed.txt）；证据 tarball `/root/ovpn-r17.tar.gz`（3ac83532…）在位，r7–r16 tarball 未动。

**证据清单（机上 `/root/r17/`）**：install.log（S0 首装）、install-rerun.log（headline-9 重跑）、h9-before.json（重跑前快照）、alt10-r17.sh（headline-1/3 脚本）、netns.sh（客户端 netns 建网）、cdp-r17.py（前端渲染脚本）、render/dashboard.png＋render-contrast.json、client-tcp.log（TCP 客户端全程日志，PID 33350）、client.log（UDP 客户端，已死）、tcp1–5.log＋tcpR1–5.log（S4 计时）、token.txt（0600）、r17-verify-open.txt＋r17-verify-closed.txt（verify.sh 两次输出）。证据 tarball `/root/ovpn-r17.tar.gz`（sha256 3ac83532…）在位，r7–r16 tarball 未动。

**未验**：Cloudflare Worker 真机部署（P0-1/2/3，仍待用户决断）；arm64 安装校验（本机 x86_64，无 arm64 机）。

**本轮方法注记**：测试侧失误均已当场修正并在各节注明（S1 首轮未跑 veth 建网脚本、S4 首版计时脚本缺 `bc`、headline-9 中途 tssh 代理断开），修正后的数字均为重测实测值；任何一次「通过」均以重测通过为准，不以失误轮次的数字充数。verify.sh 两次输出均已落盘存档。

## 12. 观察（不立案）

1. **5 秒窗口与慢启动活锁（O-R25-2 的 live-17 采样）**：BT (a) 实测——人工 8 秒延迟启动时 enable 在 5.24 秒大声失败；延迟撤除、daemon 暖启动后 enable 0.84 秒成功。本机（512MB Lightsail）暖启动充足（0.84 秒），未见系统性不足。边界如实记下：若某机 sing-box 恒慢于 5 秒（持续过载或极慢磁盘），每次 enable 均会失败、永不收敛——这是 5 秒硬截止的设计取舍，非本轮缺陷；是否升级立案由 AUDIT-R25/R26 的裁定权定。
2. **DNS 直连是设计**（§7 已记）：杀 dante 全断期间 `dig @1.1.1.1` 仍通——sing-box 规则 `protocol dns / port 53 → direct`，DNS 默认走直连出口，不进杀开关覆盖面；TCP/UDP 数据面全断无回落，杀开关本身成立。
3. **verify.sh 留 verify-* 用户**（§10.4 已记）：两次运行各留 1 个用户（1 valid、1 revoked），脚本只建不删；面板行为本身正常，属测试残留，已在终态点名。
4. **面板客户端列表约 60 秒刷新滞后**（§8 已记）：OpenVPN 状态文件刷新周期所致，新连接后须等一档才出现在面板列表；live-9 以来已知，非缺陷。
5. **本轮两次 tssh 代理断开**（§5 中段、§10.6 中段）均为测试侧通道抖动，重连后进程与数据均在，未影响任何一格的结论。

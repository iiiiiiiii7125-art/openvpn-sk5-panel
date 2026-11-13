# OpenVPN 接 SK5 落地 · 真机复跑验证报告（第十五轮 R15）

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（BN＋BO 两路修复后的最新树——本轮第一次验证 R21-P2-1 的 BN 修复与 R14-BUG-1 的 BO 修复）。
> 验证人：真机复跑验证路（第十五轮）。日期：2026-11-12。
> **结论：新 bug 1 个（R15-BUG-1，P2）**——sing-box 死期间健康检查报 `policy_missing` 而非 `blackholed_kill_switch` 且称 repair「did not stick」（§10）。其余全部通过：BN 真机格、BO 真机格（R14-BUG-1 两层均已修复）、S0–S4、headline 六项。打包树：BN＋BO 修复后当前树（panel/app.py 含隔离审计行、policy-routing.sh 含 repair 动词＋tun1_live、sk5_manager.py 含 _repair_policy 调 repair）；打包 21:17:20 UTC，稳定 15 分 18 秒。
> 前情：第十四轮见 [live-verify-R14.md](live-verify-R14.md)（R19 与 R20 的真机格全过、S0–S4 与 headline 精选全过；新 bug 1 个高——R14-BUG-1，自愈重建的死 tun1 挡住 sing-box 重启）；AUDIT-R21（318 行，差集 1 条 P2：R21-P2-1 队列文件整文件损坏静默丢命令，BN 路已修并主控核验）、AUDIT-R22（231 行，差集 1 条高即 R14-BUG-1，BO 路已修并主控核验）——**本轮打包树含 BN＋BO 两路修复，R21-P2-1 与 BO 的真机格均属本轮**。

## 0. 树版本（本次装机所用）

| 文件 | mtime (UTC) | sha256（前 12 位） | 说明 |
|---|---|---|---|
| install.sh | 2026-11-12 16:46:54 | 3f050f037e7a | AZ 路（未动） |
| panel/app.py | 2026-11-12 20:32:41 | 6aa2e97da251 | BN 路：`_quarantine_corrupt_queue` 隔离审计行＋`_queue_loss_counts`（2790 行） |
| core/openvpn_manager.py | 2026-11-12 17:20:57 | 3b5d7dfe9ea1 | BB 路（未动） |
| agent/agent.py | 2026-11-12 19:50:12 | f303af828555 | BL 路：心跳 `isinstance(parsed, dict)` 检查 |
| cloudflare/src/index.js | 2026-11-12 19:25:36 | 089bb32da319 | BJ 路：`kvArray` 归一化＋下载快照守卫 |
| egress/policy-routing.sh | 2026-11-12 21:02:02 | 59846a39a9d8 | BO 路：`repair` 动词＋`tun1_live()`（489 行） |
| egress/sk5_manager.py | 2026-11-12 21:01:56 | e95e238ad44e | BK 路 `_validate_stored`＋BO 路 `_repair_policy` 调 `repair`（1291 行） |
| panel/templates/index.html | 2026-11-12 15:21:57 | 4f7dc697451c | AR 路（未动） |
| verify.sh | 2026-11-12 14:45:28 | 7867f557c6bb | 主控（未动） |
| verify-integration.sh | 2026-11-12 18:14:53 | 6ef6ba2db8b1 | BE 路：§7 两层同一格（常量值＋字典绑定） |
| egress/test-egress.sh | 2026-11-12 08:40:51 | d6db69ec0a6e | X 路（未动） |
| README.md | 2026-11-12 17:56:09 | 6154ecabe046 | BD 路（未动） |
| panel/README.md | 2026-11-12 17:54:19 | d565d49be62f | BD 路（未动） |
| docs/security.md | 2026-11-12 17:54:57 | 523e689f2736 | BD 路（未动） |
| cloudflare/server-mode.md | 2026-11-12 17:54:19 | 9dfad606bb9b | BD 路（未动） |
| cloudflare/README.md | 2026-11-12 19:28:49 | 47489de2f9a4 | BJ 路：Worker 行为覆盖表补三行 |
| core/README.md | 2026-11-12 17:54:14 | c042e4b3d2fc | BD 路（未动） |
| docs/flmx-reference.md | 2026-11-12 17:55:47 | cc994f423a9b | BD 路（未动） |

树稳定检查：最新产品改动为 egress/policy-routing.sh（21:02:02 UTC），打包执行时刻 21:17:20 UTC，**稳定 15 分 18 秒**（满 15 分钟门；live-11 差 12 秒的教训未重犯）。其间只有 AUDIT-R22 的报告文件与本报告在写、产品文件无变动；`__pycache__` 为探针 import 产物、打包时剔除（安装子集不含 tests/）。打包时源码树 `panel/data/` 为空（`ls` 空）；毒 panel.db＋agent_queue.json 由 AE 的真实代码毒快照（`~/workspace/ae-tests/poison/`）注入打包副本，**源码树本身未被毒化**。

**打包（21:17:20 UTC）**：传包走 scp（R4–R14 同款）。`ovpn-r15.tar.gz`：41 条目，202,247 字节，sha256 `ff99a5df9596e2222783e8d9e6d9b140a4d5cc9cee362318fefd9105d0f1aef7`（机上核对一致）；install.sh sha256 `3f050f037e7a4eba992716aff5d8f54ed746c2769c6fd224d55da696d3d468de`。清单与 R14 逐项一致（41/41 diff 空）。包内毒物核对：`panel/data/panel.db` 含 admin 行 1 条（哈希 `$2b$12$tceqe…`，表 `admin`）、`panel/data/agent_queue.json` 含 3 条 init_pki force+confirm（action 均为 init_pki）——与 R8 §6.2 的毒形一致。

**注记（测试侧污染清理）**：打包前发现源码树 `panel/data/panel.db` 在位（mtime 20:55:11 UTC，1 admin 行、0 节点、7 audit 行、1 登录行）——系 R22 审计路探针未隔离数据目录所致的测试污染（同日 20:55 宿主 `/etc/openvpn-sk5-panel/` 亦出现两枚泄露测试凭据，BO 路已通报、主控已删），非产品代码。已删该文件恢复 `panel/data/` 为空；AN 的安装器排除逻辑（install.sh:474-519，panel/data/ 永不拷入）亦在，打包副本仍只含 AE 毒物。

## 1. 地面真值（Lightsail 现状，测试前实测，21:05 UTC）

- 机上是**第十四轮收尾态**：安装 #1＋headline-9 默认重跑后状态。五服务全部 active（openvpn-server PID 924218 TCP 443、panel PID 921197 8443、sing-box MainPID 932023、agent、dante 127.0.0.1:11080）；SK5 禁用（verify.sh 关态清理所致，表 100 为空）；节点 lightsail 已注册；用户 alice/bob 有效；ufw 启用、4015 行；CA 序列 `49682873442675F2BBB31E5C5E990FD9278C8FC4`。
- 第十四轮残留全部在位，**重装前必须清除**：`/root/r14/` 测试产物在位；`/root/ovpn-r14.tar.gz`（毒包，证据，**勿删**）、`/root/ovpn-r13.tar.gz`、`/root/ovpn-r12.tar.gz`、`/root/ovpn-r11.tar.gz`、`/root/ovpn-r10.tar.gz`、`/root/ovpn-r9.tar.gz`、`/root/ovpn-r8.tar.gz`、`/root/ovpn-r7.tar.gz`、`/root/ovpn-r7b.tar.gz`、`/root/ovpn-r2.tar.gz` 在位；`/opt/openvpn-sk5-panel/` 为第十四轮装树；`/etc/openvpn-sk5-panel/` 含 admin.pass（0600）；`/etc/openvpn/server/server.conf` 为 `port 443 / proto tcp / server 10.8.0.0 255.255.255.0`。
- netns `vpntest` 仍在（live-14 收尾遗留）；TCP 客户端 PID 924500 仍连（live-14 终态）。
- FLMX 相关进程同机在跑（paneld、flmx-int2 paneld、flmx_agent、sing-box 1.14.4），**一律不碰**；`/root/flmx-panel` 不动。

## 2. 清场（全新重装前，21:06–21:10 UTC）

- 先杀 live-14 遗留 TCP 客户端（精确 PID 924500，`kill`＋`kill -9` 确认消失）、删 netns `vpntest`（`ip netns list` 空）。
- 四服务已停（openvpn/panel/singbox/agent 全部 inactive，dante 保留，active）；无残留客户端进程（剩余 sing-box 进程均为 FLMX 的 1.14.4，未碰）。
- FORWARD 链删 tun0 产品规则 2 条（`-s/-d 10.8.0.0/24` 形状）、NAT POSTROUTING 的 `-s 10.8.0.0/24 -o ens5 MASQUERADE` 1 条；其余 ts-forward/DOCKER-USER/DOCKER-FORWARD/ufw 段不动。
- 状态已 wipe：`/root/openvpn-sk5-panel`、`/opt/openvpn-sk5-panel`、`/opt/ovpn-agent`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/ovpn-agent` 全删；sing-box 与 tun2socks 二进制已删（`find /usr/local/bin /usr/bin /opt -name "sing-box*" -o -name "tun2socks*"` 除 flmx 外为空，逼安装器走下载路径，复验版本校验）；`/root/r14/`、全部证据 tarball 保留未动。
- 清场后核对：无 tun0/tun1、无 1194/443/8443 监听、`/opt/openvpn-sk5-panel` 与 `/etc/openvpn-sk5-panel` 不存在。
- S0 安装已于 21:17 UTC 后台启动（`nohup bash install.sh`，日志 `/root/r15/install.log`，安装器 PID 943746）。

## 3. S0 基线：毒包安装 + 建服务 + 建用户 —— 通过（一次成功；AN 新行在位）

### 3.0 第一次安装（毒包，全新安装，UDP 1194 默认）—— 通过

- install.log：**0 个 ERROR**；sing-box 1.11.15 下载 `sha256 OK`、自报 `sing-box version 1.11.15`；tun2socks 2.7.0 下载 `sha256 OK`（`tun2socks-linux-amd64.zip: OK`，双锚核验）；完成横幅已印。
- **毒物未入住（AN 新行为）**：日志有新行 `[install] panel/ installed (panel/data/ excluded: …)`（1 条）；旧 `discarded shipped runtime file` 行 **0 条**；初始密码已生成并写入 `/etc/openvpn-sk5-panel/admin.pass`（0600）。
- 装后核对：`/opt/openvpn-sk5-panel/panel/data/` 仅含 panel.db，**agent_queue.json 文件不存在**（毒队列从未拷入）；panel.db 的 admin 行哈希为 `$2b$12$dXjQcxz/vnTHL…`，与毒哈希 `$2b$12$tceqe…` 不同——全新 admin 行；nodes 0、audit 1 行（全新库）。
- 三单元：openvpn/panel/singbox active，agent inactive（属预期，由 S0-agent 安装），sing-box 在跑；CA 序列 `42C40269B3B3382896B37B63EEF4F2EEC326B8B1`（记下供 agent 轮询后对比）。
- ufw 回归格（AN 的 R8-BUG-2 反面）：机上 ufw 在位（`ufw status` 4015 行）——安装后 ufw 仍在，`ufw status` 仍 4015 行；iptables-persistent 未装（ufw 机跳过，属预期）。

### 3.1 S0 后半段：建服务确认＋建用户 —— 通过

- 面板登录 200；`/api/status` 200：openvpn running（UDP 1194，PID 944489），online_users 0，SK5 未启用，`singbox_running: true`，sk5 块 `policy_routing_active: false`。
- 默认 `.ovpn` remote 为 **16.146.199.68 1194**（IPv4 公网）。
- 用户：alice、bob 创建均 200；`GET /api/openvpn/users` 只列 alice、bob，alice 序列号 `68DB2A40DE570A98`、bob `764BD5AE9F191DAC`；`.ovpn` 下载 8612 字节（curl 直取完整文件，避开 panel.py 4000 字符截断坑），`proto udp / remote 16.146.199.68 1194`，含 2 个 CERTIFICATE 块。
- **观察（不立案）**：`/api/status` 的直接出口探测返回 IPv6 地址 `2600:1f13:14d:a300:7913:f273:997e:c8b8`（本机有 IPv6，探测走了 v6）；live-9 同格为 IPv4 16.146.199.68、live-10/live-11/live-12/live-13/live-14 同款 IPv6。数据面实测（S1/S2）仍以 IPv4 出口为准，面板 `egress.ip` 的 v4/v6 取值未作断言。

## 4. S0-agent：节点注册 + agent 安装 + 命令链 —— 通过（第二毒物 agent 侧终验通过）

- 注册：`POST /api/nodes {"name":"lightsail","panel_url":"https://172.26.15.152:8443"}` → 201，token 只存 `/root/r15/token.txt`（未写报告）。
- 安装命令（面板两步走命令，按 agent/README 记载的流程执行；token 由文件读入）：`curl -ksSL https://172.26.15.152:8443/install-agent.sh`＋`install-agent.sh.sha256` 校验 `install-agent.sh: OK`＋`bash /tmp/install-agent.sh --panel-url … --token … --node-name 'lightsail'` → **EXIT=0**。bundle sha256 OK、`/etc/ovpn-agent/config.json` 0600、`ovpn-agent is ACTIVE (node=lightsail)`。
- poll：`GET /api/nodes` 的 `last_seen` 为 2026-11-12T21:24:30+00:00（新鲜），心跳合并 `last_status`（hostname/version/openvpn_running/sk5_enabled）；agent 日志 0 条 401/403、无 poll failed、无 init_pki。
- **毒 init_pki 未执行**：agent 上线并轮询后，CA 序列仍为 `42C40269B3B3382896B37B63EEF4F2EEC326B8B1`（与安装时一致）；面板 `agent_queue.json` 现为 `{"queue": {"lightsail": []}, "cmds": {}, "ovpn": {}}`——init_pki 0 条。
- 命令链：`POST /api/cmd {"node":"lightsail","action":"get_status"}` → **202**（cmd_id 7f8b257d…）；约 11 秒后 `GET /api/cmd/<id>` → **done**，error null；result 含 openvpn running=true、sk5 enabled=false。

## 5. S1 直连态（UDP 1194）—— 通过（首次即通，零手工 FORWARD）

- 客户端（alice，netns vpntest，`--float`）：改 remote 为 LAN IP 172.26.15.152（R7 同款，公网 IP 发夹在 netns 内受限，非产品问题），**首次即通**，`Initialization Sequence Completed`，tun0 10.8.0.2/24，redirect-gateway 路由就位。PID 947163。
- 数据面（direct）：`curl ifconfig.me`（HTTP 与 HTTPS，--resolve 绕 MagicDNS）→ **16.146.199.68**；`dig @1.1.1.1 ifconfig.me` → 34.160.111.145 有回包；NTP UDP：216.239.35.4 回 **48 字节** 12.6ms、162.159.200.1 回 **48 字节** 5.9ms。UDP 数据面通过。
- **BUG-9 第十七次复验——修好（UDP 模式）**：部署态原始日志（逗号 v2，13 段）为 `CLIENT_LIST,alice,10.200.0.2:40546,10.8.0.2,,6306,12804,2026-11-12 21:25:26,1794518726,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users` = **1**；`clients`=[{name: alice, real_address: 10.200.0.2:40546, virtual_address: 10.8.0.2, bytes_received: "6306", bytes_sent: "12804", connected_since: "2026-11-12 21:25:26"}]——逐字段一致；`/api/openvpn/users` 的 alice `online: true`、bob `online: false`（本节实测）。

## 6. S2 落地态（SK5 开）—— 通过（BM 黑洞在位）

- `POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → 200，`policy_routing_active: true`；`POST /api/sk5/test` → 200，tcp_ok（81.9ms）、udp_ok（native）。
- 表 100（BM 层 1 实测在位）：`default via 10.9.0.1 dev tun1`＋`blackhole default metric 200`；`ip rule` 有 `from 10.8.0.0/24 lookup 100`；`ip route get 1.1.1.1 from 10.8.0.1` → `dev tun1 table 100`；tun1 `UP,LOWER_UP`。
- 数据面（SK5 启用态）：curl（HTTP+HTTPS，--resolve）→ **16.146.199.68**；**netns 内 NTP**：216.239.35.4 回 **48 字节** 35.1ms、162.159.200.1 回 **48 字节** 31.1ms（比直连 12.6/5.9ms 慢，符合 SK5 路径）。
- 双日志为证：TCP——sing-box `outbound/socks[bought-sk5]: outbound connection to 34.160.111.145:80` 与 `:443`；UDP——sing-box `outbound/socks[bought-sk5]: outbound packet connection to 216.239.35.4:123` 与 `162.159.200.1:123`（21:30:31）；dante 同窗口有 `udp/udpassociate` 会话（21:30:31/34）。
- **测试侧纠错（已修正，不立案）**：首轮 NTP 在宿主上跑（未进 netns），回包走宿主直连、与隧道无关——我当场发现后改在 netns 内重跑，上述 48 字节回包均为 netns 内实测；sing-box 日志里 NTP 目的地址仅在重跑后出现，与修正一致。

## 7. S3 断网保护（杀 dante）—— 通过（数据面全断、无直连回落、链路自恢复、隧道不断）

- 杀 dante（精确 PID 924034，SIGTERM；`systemctl show` 事后确认 danted 单元无 Restart= 指令，SIGTERM 属 clean deactivation、NRestarts=0）：客户端 TCP `curl --resolve … http://ifconfig.me` → **exit 56**（Recv failure），HTTPS → exit 35（SSL connect error，同样失败）；netns 内 NTP UDP 到 216.239.35.4 → **TimeoutError**；**无直连回落**（curl 不是成功、是失败——fail-closed 成立）。隧道未断（同一客户端 PID 947163，tun0 仍在，`Initialization Sequence Completed` 仅 1 次）。
- 面板 `/api/status`：kill 期间 **egress.ip = null**（`{'error': None, 'ip': None, 'latency_ms': None, 'via_sk5': True}` 形状同 live-9/live-10/live-11/live-12/live-13/live-14），诚实报空。
- 恢复（`systemctl start danted`，active）：客户端 TCP 立即回 **16.146.199.68**，NTP 回 **48 字节**。隧道全程未断：同一 PID 947163，client.log 里 `Initialization Sequence Completed` 仅出现 1 次、SIGUSR1 0 行——无重连、无重拨。
- 口径注记（设计，非缺陷）：dante 单元本身无 Restart=——所谓「自动恢复」指 dante 复活后链路无需人工重启用即恢复（sing-box 自动重连、客户端不断），不是 dante 自重启；live-14 报告 §7 同样是手动 `systemctl start danted` 后恢复，本轮与之口径一致。kill 期间 `dig @1.1.1.1` 仍有回包——sing-box 路由规则 `protocol dns / port 53 → direct`（见 `/etc/openvpn-sk5-panel/sing-box.json`），DNS 默认走直连、不经 SK5，是文档已定设计；断网保护覆盖的是 TCP/UDP 数据面，DNS 不在黑洞范围内。
- **本节只覆盖 SK5 死亡（dante 死）情形。sing-box 本体死亡情形见 §10 BO 真机格——本轮重点。**

## 8. S4 TCP 备模式（443）—— 通过（R7 的 120s 超时第七轮未复现）

- 切模式：`POST /api/openvpn/server {"proto":"tcp","port":443,"allow_port_change":true}` → 200；server.conf 已改 `port 443 / proto tcp`，但**服务未自动重启**（PID 仍 944489，UDP 1194 仍在监听，TCP 443 无监听，journal 无重启记录）——API 回执自带注记「改配置后需重启服务才生效」，属已定口径（面板只写配置、不重启）；手工 `systemctl restart openvpn-server@server` 后 TCP 443 监听（PID 950968）、UDP 1194 消失。
- 5 次首连（bob，TCP，逐次杀掉重连，Python 计时到 `Initialization Sequence Completed`）：**0.12s、0.11s、0.11s、0.11s、0.11s**——全 ≤1 秒。R7 的单次 120s 超时连续第七轮未复现。首轮用 `bc` 计时失败（机上无 bc），已改 Python 重测，数字为重测实测值。
- 数据面（TCP 模式＋SK5 启用态）：curl → **16.146.199.68**；netns 内 NTP 回 **48 字节**。持久 TCP 客户端 PID 951484（供 §10 BO 格用同一客户端）。
- **BUG-9 第十七次复验——修好（TCP 模式）**：部署态原始日志（逗号 v2，13 段）为 `CLIENT_LIST,bob,10.200.0.2:35074,10.8.0.2,,4636,4453,2026-11-12 21:36:36,1794519396,UNDEF,10,0,AES-256-GCM`；面板 `/api/status` 的 `online_users` = **1**；`clients`=[{name: bob, real_address: 10.200.0.2:35074, virtual_address: 10.8.0.2, bytes_received: "4636", bytes_sent: "4453", connected_since: "2026-11-12 21:36:36"}]——逐字段一致；`/api/openvpn/users` 的 bob `online: true`、alice `online: false`（本节实测）。

## 9. R21-P2-1 真机格（BN）—— 通过

- 损坏前快照：audit_log 10 行、`queue_corrupt_quarantined` 0 行、无 `.corrupt` 文件；队列含已完成的 get_status 命令 1 条（已备份 `/root/r15/queue-before-bn.json`，sha256 `c896ba71…`）。
- 损坏（21:38:02 UTC，整文件写垃圾 `THIS IS NOT JSON {{{ garbage-corrupt-queue-r15`，46 字节，sha256 `20abd4f0…`）：agent 下一轮 poll 仍 200——节点 `last_seen` 21:38:28（损坏后仍新鲜），agent 日志 0 条 poll failed/401/403；**命令不下发**（隔离后队列为空，损坏期间无新命令入队、无 dispatch）。
- 隔离审计行：audit_log 10→**11 行**，新增恰 1 行（id 11）：action=`queue_corrupt_quarantined`、result=`failed`、detail 含备份路径 `/opt/openvpn-sk5-panel/panel/data/agent_queue.json.corrupt.20261112T213803342415`＋损坏原因 `Expecting value: line 1 column 1 (char 0)`＋丢失计数 `queued=不可知 sent=不可知 .ovpn 回执=不可知`（「不可知」而非编 0，BN 的诚实口径）；journal 同步有 WARNING（路径＋解析错误，无文件内容）。
- `.corrupt` 备份**字节一致**：备份 sha256 `20abd4f075413719e45a834599fddca18193297fd2a0906a50b67df838763bc3`，与写入的垃圾文件 sha256 逐字节相同。
- 恢复：从备份拷回队列（sha256 回到 `c896ba71…`）；新下发 get_status → 202，8 秒内 done（done 命令 2 条）——链路正常。

## 10. BO 真机格（杀 sing-box → 黑洞 → 自动重起 → 自愈）—— 通过（R14-BUG-1 的两层均已修复；中间态命名偏差 1 条，见 R15-BUG-1）

**前置（21:38:54）**：TCP 443 模式、SK5 启用态；sing-box PID 948011、NRestarts=0、active；表 100 有 tun1 路由＋黑洞；TCP 客户端 PID 951484 在线；curl 经 SK5 回 16.146.199.68。

**第一杀（SIGTERM，精确 PID 948011，21:38:58）——BM 层 1 成立**：tun1 立即消失（`Device "tun1" does not exist`）；表 100 只剩 `blackhole default metric 200`；`ip route get 1.1.1.1 from 10.8.0.1` → `RTNETLINK answers: Invalid argument`（黑洞）；客户端 curl exit **28**（超时）、NTP **TimeoutError**——绝无直连回落；R13-BUG-1 泄漏签名未复现。TCP 客户端 951484 全程在线。
- SIGTERM 属 clean 退出（`Deactivated successfully`、Result=success）：systemd 按 Restart=on-failure 不重启，39 秒后仍 inactive、NRestarts=0——**这是 systemd 的正确行为，不是产品问题**；自动重起路径见第二杀（SIGKILL）。
- 健康检查 21:39:39（杀后 41 秒）：`policy_missing`，healthy=False，detail 明确写「sing-box not running; policy routing is not applied, VPN traffic is held by the fallback blackhole route in table 100 (not egressing direct)」——流量状态诚实；`policy_routing_active: false`、`singbox_running: false`。**但 action 不是 live-14 的 `blackholed_kill_switch`，且 detail 称「policy script exited 0 but the policy still did not stick」——见 R15-BUG-1（P2）。**

**手动重起（模拟重起结果）**：`systemctl start openvpn-sk5-singbox` → active、新 PID 953116、NRestarts=0，tun1 `UP,LOWER_UP`，journal **0 条** `file exists`/FATAL——R14-BUG-1 的 `file exists` 碰撞未复现（repair 动词未重建死 tun1，表 100 在 sing-box 死期间保持黑洞-only，无占位设备可撞）。
- 下一档健康检查 21:41:40（重起后 57 秒）：action **`policy_repaired`**、healthy=True、`tcp_ok=True udp_ok=True egress=16.146.199.68`、detail「policy was missing, auto-repaired by this check」；表 100 恢复 tun1 路由＋黑洞；curl 回 16.146.199.68；TCP 客户端 951484 在线、`Initialization Sequence Completed` 仅 1 次。

**第二杀（SIGKILL，精确 PID 953116，21:41:51）——systemd 自动重起实测**：单元 `Restart=on-failure, RestartSec=3, StartLimitBurst=5/120s`；8 秒后 sing-box **自动** active、新 PID 953569、**NRestarts=1**，tun1 `UP,LOWER_UP`，journal **0 条** `file exists`/FATAL——未触 StartLimitBurst、未落 failed。
- 下一档健康检查 21:42:41：再次 **`policy_repaired`**、healthy=True、tcp/udp ok、egress 16.146.199.68；表 100 tun1 路由＋黑洞；curl 回 16.146.199.68；netns 内 NTP 回 **48 字节**；TCP 客户端 951484 在线、完成序列仅 1 次；sing-box NRestarts 仍 1。

**结论**：R14-BUG-1 的两层均已修复——层 1（黑洞兜底）与层 2（自愈不撞 `file exists`、不触 StartLimitBurst）均在真机上复现通过，且是同一 TCP 客户端全程不断的两次完整循环（SIGTERM＋手动重起、SIGKILL＋自动重起）。

### R15-BUG-1（P2）：sing-box 死期间健康检查报 `policy_missing` 而非 `blackholed_kill_switch`，且称 repair「did not stick」

- **复现**：上述第一杀后 41 秒的健康检查（21:39:39）：action=`policy_missing`，detail 含「auto-repair: policy script exited 0 but the policy still did not stick (re-enable via the panel if this persists)」。
- **机制**：`check_health`（sk5_manager.py:1140-1160）先 `_repair_policy()`；repair 动词按 BO 设计只装黑洞＋rule、不装 tun1 路由（设备不活）；随后代码用 `_policy_active()`（:903，要求 tun1 路由在位）复验——sing-box 死时 tun1 路由不可能存在，复验必失败 → `repaired=False`、note 写「did not stick」→ 落 `policy_missing`（:1218）。
- **与承诺不符**：同一函数 docstring（:1113-1121）写明「a repaired chain is re-verdicted by the probe (healthy -> `policy_repaired`, still dead -> `blackholed_kill_switch`). Only a failed repair lands `policy_missing`」。live-14 实测也是 `blackholed_kill_switch`（当时 repair 走 enable 动词、重建了死 tun1＋路由，`_policy_active()` 为真、探针失败才落 kill-switch）。BO 改了 repair 语义却未同步改 verdict 逻辑/docstring——repair 脚本 exit 0 且做了它设计上该做的全部事（黑洞＋rule 在位），却被判「失败」。
- **定级 P2（非安全）**：流量安全属性未破——detail 明确写清流量被黑洞兜住、未走直连，`policy_routing_active: false` 亦诚实；「re-enable via the panel if this persists」指引亦可操作（重启用会重启 sing-box、恢复链路）。损害在标签与措辞：`policy_missing` 与真正危险态（无黑洞、流量直连）共用同一 action 名，仅靠 detail 文本区分；「did not stick」误述一次按设计成功的 repair。修法建议：repair 成功（脚本 exit 0 且黑洞＋rule 在位）但链仍死（sing-box 不在）时按 docstring 落 `blackholed_kill_switch`；或把 `_policy_active()` 的复验改为「repair 动词的自检口径」（黑洞＋rule 在位即算 repair 成功），并同步 docstring。

## 11. headline 回归精选 —— 通过（6 项全过；另有 1 个瞬态未立案）

### 11.1 headline-1 首启一次 200 —— 通过（首启一次 200；10 次交替全一次 200，delta 恰 10）

- **首启（全新安装后第一次启用）**：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功，§6）。**R6-BUG-1 真机回归通过**。
- **10 次交替**（从禁用态起，奇数步全表单启用、偶数步单字段禁用，均为真实翻转）：10 步全部 **200**（一次成功），逐格 Started 计数各 **+1**（134→135→136→137→138→139→140→141→142→143→144）。计数口径：journalctl 里 `Started openvpn-sk5-singbox.service` 行数（live-8/9/10/11/12/13/14 同口径）；本轮绝对计数未遇 vacuum（逐格 +1 全程单调），delta 恰 10 成立。注：禁用步亦 +1——disable 同样重起 sing-box（重渲染直连模式配置），与 live-14 的逐格 +1 一致。
- TCP 客户端 PID 951484 全程未断。

### 11.2 headline-3 并发启用 delta 恰 1 —— 通过（双 200，delta 恰 1）

- 从禁用态起，两路 `POST /api/sk5 {"host","port","enabled":true}` 同时发出 → **双 200**，Started 145→146（**delta 恰 1**），终态 enabled=true、policy=true、via=true、ip=16.146.199.68。AH 的 `_SK5_MUTATE_LOCK` 在真机并发路径上成立。**R7-BUG-3 真机终验通过**。
- **测试侧纠错（已修正，不立案）**：首轮并发因第二个后台命令丢了 `cd /root/r15`、panel.py 未找到，只有一路真正发出——我当场发现（conc2.json 内容为 traceback）后重做，双 200＋delta 恰 1 为重做实测值。

### 11.3 headline-5 policy-missing 诚实＋零重起修复 —— 通过（手动删策略，面板重开零重起修复）

- **诚实**：手动删表 100 的 tun1 路由后（本格为隔离面板路径、事先停了健康检查定时器——否则 60 秒档内定时器自愈会抢在面板重开前面，测试侧控制，事后已恢复定时器），面板 `/api/status`：`via_sk5=false`、`egress.ip=None`、`policy_routing_active=false`（enabled 仍 true），未谎称经 SK5、未谎称黑洞。注：删路由后 2 秒内的一次查询仍显示旧值——面板 `_SK5_STATUS_CACHE_TTL` 10 秒缓存（live-14 同款观察），12 秒后复查即为上述诚实值。
- **零重起修复**：全表单重开（`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}`）→ 200，收据 **`repaired: true`、`repair_detail: ["policy routing re-applied"]`**，Started 146→146（delta=0，**零重起补策略**）；恢复后 rule 100＋table 100 均在位，`policy_routing_active=true`、curl 回 16.146.199.68。TCP 客户端 PID 951484 全程未断。

### 11.4 headline-6 verify.sh 双态 —— 通过（开态 18/0/4、关态 23/0/0）

- **开态**（SK5 开）：`bash verify.sh` → **PASS=18 FAIL=0 SKIP=4，VERIFY: ALL GREEN**（与 R5–R14 开态 18/0/4 一致；4 个 SKIP 为开态下跳过的 toggle 格，属设计）。
- **关态**（面板关 SK5 后 25 秒再跑）：首轮 **PASS=22 FAIL=1 SKIP=0**——唯一 FAIL 为 `egress-crosscheck`（`egress/test-egress.sh` 在链启用态下失败；`internet_ok` 为真故未走 SKIP 分支）。**瞬态，未立案**：test-egress.out 随 verify.sh 清理已删、失败小节无法定位；同一链路态下手动重跑 test-egress.sh → **PASS=5 FAIL=0 SKIP=2、EXIT=0**，同树串行重跑关态 verify.sh → **PASS=23 FAIL=0 SKIP=0，VERIFY: ALL GREEN**（live-12 的 S0 转发门瞬态先例：同树串行重跑通过即不立案）。R5-BUG-1 的关态天花板（22/1）继续不存在。关态跑完后 SK5 为禁用（verify.sh 的 enable 探针自带清理禁用；跑完紧接着的一次查询曾显示 enabled 真——又是 10 秒状态缓存，12 秒后复查即为禁用，见 live-14 §11.4 同款）。

### 11.5 headline-7 前端真渲染 —— 通过（真渲染：0 项低于 4.5，最薄 4.92；零 JS 异常）

- 真机 headless Chromium 渲染（1440x900，`render/dashboard.png` 126,800 字节＋`render-contrast.json`，脚本为 cdp-r14.py 的 r15 路径版 cdp-r15.py）：标题 “OpenVPN + SK5 面板”、h1 “概览”；可见文本元素 **171 项，0 项低于 4.5**，最薄 **4.92**（“当前 .ovpn 的 remote 为公网地址 16.146.199.68，站外”，绿字白底）；35 项低于 7.0（目标值，非门禁底线；live-10/11/12/13/14 同款分布）。
- 控制台事件 4 条：3 条 verbose 级 DOM 建议（密码字段不在 form 内等）＋1 条 favicon.ico 404（缺 favicon 资产）；**零 JS 异常**（无 Uncaught／exception 条目）。favicon 404 与 live-10/11/12/13/14 同款，记观察、不立案。

### 11.6 headline-9 毒树默认重跑行级比对 —— 通过

- 毒树（`/root/r15/install-src/`，含毒 panel.db＋毒 agent_queue.json）默认重跑 `bash install.sh`（无任何 flag，日志 `/root/r15/install-rerun.log`，AN 新行 1 条、ERROR 0、完成横幅已印；重跑期间 tssh 会话曾断开一次，重连确认重跑已完成）。
- 行级比对（重跑前快照 `/root/r15/h9-before.json`）：admin 行**完全一致**（哈希仍为全新 `$2b$12$dXjQcxz/vnTHL…`，非毒 `$2b$12$tceqe…`）；login_attempts **一致**（0 行）；nodes **一致**（1 行 lightsail，name＋url 一致）；audit 48→49 行，**前 48 行完全一致**，新增 1 行仅为重跑后本轮登录（admin login ok，合法）；server PID 不变（950968，服务未重起）；`agent_queue.json` 的 cmds 仍仅 2 条合法 get_status id，**毒的 3 条 init_pki 未入住**；BN 的 `.corrupt` 备份仍在。
- **R8-BUG-1（毒树重跑销毁线上 panel.db）本轮终验通过。**

## 12. 结论与机器终态

**结论：新 bug 1 个（R15-BUG-1，P2）**——sing-box 死期间健康检查报 `policy_missing` 而非 `blackholed_kill_switch` 且称 repair「did not stick」（§10）。其余全部通过：BN 真机格、BO 真机格（两层、两次完整循环）、S0–S4、headline 六项。R14-BUG-1 已在真机上关闭（§10 两次循环实证）。

**机器终态（2026-11-12 21:56 UTC）**：TCP 443 模式（openvpn PID 950968，UDP 1194 已无监听）；面板 8443（PID 944620）；sing-box active（MainPID 960518，NRestarts=0）；agent active；dante active。SK5 **禁用**（关态 verify 清理后状态）；表 100 空。TCP 客户端 PID 951484 仍连接在 netns `vpntest` 里（`Initialization Sequence Completed` 全程仅 1 次）。用户 alice/bob 有效。CA `42C40269B3B3382896B37B63EEF4F2EEC326B8B1`（与安装时一致，毒 init_pki 从未执行）。节点 lightsail 在线。ufw 4015 行。FLMX 同机进程未碰。证据在 `/root/r15/`（install.log、install-rerun.log、verify-open/closed/closed2.log、h9-before.json、queue-before-bn.json、render/、client-*.log、token.txt 0600）；证据 tarball `/root/ovpn-r15.tar.gz`（ff99a5df…）在位，r7–r14 tarball 未动。

**未验**：R15-BUG-1 的修复后复验（属下一轮）；Cloudflare Worker 真机部署（P0-1/2/3，仍待用户决断）；arm64 安装校验（本机 x86_64，无 arm64 机）。

**本轮方法注记**：全部数字均为机上实测值；测试侧失误均已当场修正并在各节注明（S2 首轮 NTP 跑在宿主、11.2 首轮并发丢 `cd`、S4 首轮 `bc` 缺失、11.4 关态首轮瞬态红），修正后的数字均为重测实测值；任何一次「通过」均以重测通过为准，不以失误轮次的数字充数。

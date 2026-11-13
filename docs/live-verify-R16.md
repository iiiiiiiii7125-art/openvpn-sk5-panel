# OpenVPN 接 SK5 落地 · 真机复跑验证报告（第十六轮 R16）

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（BP＋BQ＋BR＋BS 四路修复后的最新树——本轮第一次验证 R23 的 4 条与 R15-BUG-1 的修复）。
> 验证人：真机复跑验证路（第十六轮）。日期：2026-11-12。
> **结论：全部通过，零新 bug。**——BP／BQ／BR／BS 四路修复的真机格全过（§9–§12），S0–S4 全过，headline 六项全过（§13；headline-6 开/关态首轮各 1 红，均系 AN 已接受的限制——BP 真实重启后 live-only 的 FORWARD／NAT 规则未恢复，毒树默认重跑补上后重测全绿，见 §13.4）。
> 前情：第十五轮见 [live-verify-R15.md](live-verify-R15.md)（BN 与 BO 的真机格全过、S0–S4 与 headline 精选全过；新 bug 1 个 P2——R15-BUG-1，sing-box 死期间健康检查报 `policy_missing` 而非 `blackholed_kill_switch`）；AUDIT-R23（304 行，差集 4 条全 P2：P2-1 boot 时 `do_restore` 仍走全 `enable`、P2-2 `do_restore` 把 sk5.json 损坏当“未配置”、P2-3 队列文件不可读静默丢命令、P2-4 Worker `loginfail:<ip>` 数组形锁账丢失，BP／BQ／BR／BS 四路已修并主控核验）、AUDIT-R24 已完工（244 行，不能交付，差集 1 条 P2：R24-P2-1，enable 占位符写出的 linkdown 路由骗过 `_policy_active()`；修复 BT 路沙箱级已完工，真机格属 live-17，不属本轮）——**本轮只验代码真机行为，不写审计结论**。

## 0. 树版本（本次装机所用）

| 文件 | mtime (UTC) | sha256（前 12 位） | 说明 |
|---|---|---|---|
| install.sh | 2026-11-12 16:46:54 | 3f050f037e7a | AZ 路（未动） |
| panel/app.py | 2026-11-12 21:59:34 | 40868bbfd8b9 | BQ 路：`_load_queue` OSError 分支拆开＋不可读隔离（2790 行） |
| core/openvpn_manager.py | 2026-11-12 17:20:57 | 3b5d7dfe9ea1 | BB 路（未动） |
| agent/agent.py | 2026-11-12 19:50:12 | f303af828555 | BL 路：心跳 `isinstance(parsed, dict)` 检查 |
| cloudflare/src/index.js | 2026-11-12 21:58:59 | f43180976393 | BR 路：`kvLoginFailRecord` 归一化 |
| egress/policy-routing.sh | 2026-11-12 22:01:20 | f2750422a912 | BP 路：`do_restore` 走 repair 语义＋`read_stored_enabled()` |
| egress/sk5_manager.py | 2026-11-12 22:01:00 | d7bfa06db651 | BS 路：`_repair_holding()` verdict 契约 |
| panel/templates/index.html | 2026-11-12 15:21:57 | 4f7dc697451c | AR 路（未动） |
| verify.sh | 2026-11-12 14:45:28 | 7867f557c6bb | 主控（未动） |
| verify-integration.sh | 2026-11-12 18:14:53 | 6ef6ba2db8b1 | BE 路：§7 两层同一格（常量值＋字典绑定） |
| egress/test-egress.sh | 2026-11-12 08:40:51 | d6db69ec0a6e | X 路（未动） |

树稳定检查：最新产品改动为 egress/policy-routing.sh（22:01:20 UTC），打包执行时刻 22:16:27 UTC，**稳定 15 分 07 秒**（满 15 分钟门；live-11 差 12 秒的教训未重犯）。其间只有 AUDIT-R24 的报告文件与本报告在写、产品文件无变动；`__pycache__` 为探针 import 产物、打包时剔除（安装子集不含 tests/）。打包时源码树 `panel/data/` 为空（`ls` 空）；毒 panel.db＋agent_queue.json 由 AE 的真实代码毒快照（`~/workspace/ae-tests/poison/`）注入打包副本，**源码树本身未被毒化**。

**打包（22:16:27 UTC）**：传包走 scp（R4–R15 同款）。`ovpn-r16.tar.gz`：41 条目，204,498 字节，sha256 `2e624c0700a2f7a9b224165aaf16f6edb2b8bd3f2db8eea027c0b88e25e85eff`（机上核对一致）；install.sh sha256 `3f050f037e7a4eba992716aff5d8f54ed746c2769c6fd224d55da696d3d468de`。清单与 R15 逐项一致（41/41 diff 空）。包内毒物核对：`panel/data/panel.db` 含 admin 行 1 条（哈希 `$2b$12$tceqe…`，表 `admin`）、`panel/data/agent_queue.json` 含 3 条 init_pki force+confirm（action 均为 init_pki）——与 R8 §6.2 的毒形一致。注：首次 scp 因缺 `StrictHostKeyChecking=accept-new`＋`UserKnownHostsFile` 报错 Host key verification failed，改按 tssh.sh 同款参数重传成功，测试侧问题。

## 1. 地面真值（Lightsail 现状，测试前实测，22:11 UTC）

- 机上是**第十五轮收尾态**：安装 #1＋headline-9 默认重跑后状态。五服务全部 active（openvpn-server PID 950968 TCP 443、panel PID 944620 8443、sing-box MainPID 960518、agent PID 946718、dante 127.0.0.1:11080）；SK5 禁用（verify.sh 关态清理所致，表 100 为空）；节点 lightsail 已注册；用户 alice/bob 有效；ufw 启用、4015 行；CA 序列 `42C40269B3B3382896B37B63EEF4F2EEC326B8B1`。
- 第十五轮残留全部在位，**重装前必须清除**：`/root/r15/` 测试产物在位；`/root/ovpn-r15.tar.gz`（毒包，证据，**勿删**）、`/root/ovpn-r14.tar.gz`、`/root/ovpn-r13.tar.gz`、`/root/ovpn-r12.tar.gz`、`/root/ovpn-r11.tar.gz`、`/root/ovpn-r10.tar.gz`、`/root/ovpn-r9.tar.gz`、`/root/ovpn-r8.tar.gz`、`/root/ovpn-r7.tar.gz`、`/root/ovpn-r7b.tar.gz`、`/root/ovpn-r2.tar.gz` 在位；`/opt/openvpn-sk5-panel/` 为第十五轮装树；`/etc/openvpn-sk5-panel/` 含 admin.pass（0600）；`/etc/openvpn/server/server.conf` 为 `port 443 / proto tcp / server 10.8.0.0 255.255.255.0`。
- netns `vpntest` 仍在（live-15 收尾遗留）；TCP 客户端 PID 951484 仍连（live-15 终态）。
- FLMX 相关进程同机在跑（paneld、flmx-int2 paneld、flmx_agent、sing-box 1.14.4，PID 53637），**一律不碰**；`/root/flmx-panel` 不动。

## 2. 清场（全新重装前，22:11 UTC）

- 先杀 live-15 遗留 TCP 客户端（精确 PID 951484，`kill`＋`kill -9` 确认消失）、删 netns `vpntest`（`ip netns list` 空）；另杀残留 `/tmp/udp-echo2.py`（精确 PID 333604，测试侧遗留）。
- 四服务已停（openvpn-server@server／panel／singbox／agent 全部 inactive，dante 保留，active）；无残留客户端进程（剩余 sing-box 进程为 FLMX 的 1.14.4，未碰）。
- FORWARD 链删 tun0 产品规则 2 条（`-d 10.8.0.0/24 -i ens5 -o tun0` conntrack 形＋`-s 10.8.0.0/24 -i tun0 -o ens5`）、NAT POSTROUTING 的 `-s 10.8.0.0/24 -o ens5 MASQUERADE` 1 条；其余 ts-forward/DOCKER-USER/DOCKER-FORWARD/ufw 段不动。
- 状态已 wipe：`/root/openvpn-sk5-panel`、`/opt/openvpn-sk5-panel`、`/opt/ovpn-agent`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/ovpn-agent` 全删；sing-box 与 tun2socks 二进制已删（`find` 除 flmx_agent 外为空，逼安装器走下载路径，复验版本校验）；`/root/r15/`、全部证据 tarball 保留未动。
- 清场后核对：无 tun0/tun1、无 1194/443/8443 监听、`/opt/openvpn-sk5-panel` 与 `/etc/openvpn-sk5-panel` 不存在。
- S0 安装已于 22:16 UTC 后台启动（`nohup bash install.sh`，日志 `/root/r16/install.log`，安装器 PID 968860）。

## 3. S0 基线：毒包安装 + 建服务 + 建用户 —— 通过（一次成功；AN 新行在位）

### 3.0 第一次安装（毒包，全新安装，UDP 1194 默认）—— 通过

- install.log：**0 个 ERROR**；sing-box 1.11.15 安装 `sing-box version 1.11.15`、tun2socks 2.7.0 下载 `tun2socks-linux-amd64.zip: OK`；完成横幅已印。
- **毒物未入住（AN 新行为）**：日志有新行 `[install] panel/ installed (panel/data/ excluded: …)`（1 条）；旧 `discarded shipped runtime file` 行 **0 条**；初始密码已生成并写入 `/etc/openvpn-sk5-panel/admin.pass`（0600）。
- 装后核对：`/opt/openvpn-sk5-panel/panel/data/` 仅含 panel.db，**agent_queue.json 文件不存在**（毒队列从未拷入）；panel.db 的 admin 行哈希为 `$2b$12$sjDFuLVVm74j3…`，与毒哈希 `$2b$12$tceqe…` 不同——全新 admin 行；nodes 0、audit_log 1 行（全新库）、login_attempts 0 行。
- 服务：openvpn-server@server active（UDP 1194，PID 969499）、panel PID 944620、sing-box active，agent inactive（属预期，由 S0-agent 安装）；CA 序列 `47503898D915C8FAA90FC789AEB36A6D65892C93`（notBefore 2026-11-12 22:16:58，记下供 agent 轮询后对比）。
- ufw 回归格（AN 的 R8-BUG-2 反面）：机上 ufw 在位——安装后 `ufw status` 仍 4015 行；iptables-persistent 未装（ufw 机跳过，属预期）。

### 3.1 S0 后半段：建服务确认＋建用户 —— 通过

- 面板登录 200；`/api/status` 200：openvpn running（UDP 1194，PID 969499），online_users 0，SK5 未启用，`singbox_running: true`，sk5 块 `policy_routing_active: false`。
- 默认 `.ovpn` remote 为 **16.146.199.68 1194**（IPv4 公网）。
- 用户：alice、bob 创建均 200；`GET /api/openvpn/users` 只列 alice、bob，alice 序列号 `847FBE63…`、bob `80CB707A…`。注：首轮 chain 里 bob 的 POST 实际已成功（409 是我第二次重复提交所致，测试侧问题，非产品问题）。
- **观察（不立案）**：`/api/status` 的直接出口探测返回 IPv6 地址 `2600:1f13:14d:a300:7913:f273:997e:c8b8`（本机有 IPv6，探测走了 v6）；live-9 同格为 IPv4 16.146.199.68、live-10/live-11/live-12/live-13/live-14/live-15 同款 IPv6。数据面实测（S1/S2）仍以 IPv4 出口为准，面板 `egress.ip` 的 v4/v6 取值未作断言。

## 4. S0-agent：节点注册 + agent 安装 + 命令链 —— 通过（第二毒物 agent 侧终验通过）

- 注册：`POST /api/nodes {"name":"lightsail","panel_url":"https://172.26.15.152:8443"}` → 201，token 只存 `/root/r16/token.txt`（未写报告）。中途两次取 token 路径走偏：首次注册回执的 token 在顶层字段（我按 `node.token` 取，KeyError）；又多注册一个 lightsail2 看字段形——随后 DELETE 删掉，并用 `/api/nodes/lightsail/rotate` 重新取 token（长 43），测试侧流程问题，非产品问题。
- 安装命令（面板两步走命令，按 agent/README 记载的流程执行；token 由文件读入）：`curl -ksSL https://172.26.15.152:8443/install-agent.sh`＋`install-agent.sh.sha256` 校验 `install-agent.sh: OK`＋`bash /tmp/install-agent.sh --panel-url … --token … --node-name 'lightsail'` → **EXIT=0**。bundle sha256 OK、`/etc/ovpn-agent/config.json` 0600、`ovpn-agent is ACTIVE (node=lightsail)`。
- poll：`GET /api/nodes` 的 `last_seen` 为 2026-11-12T22:20:40+00:00（新鲜），心跳合并 `last_status`（hostname/version/openvpn_running/sk5_enabled）；agent 日志 0 条 401/403、无 poll failed、无 init_pki。
- **毒 init_pki 未执行**：agent 上线并轮询后，CA 序列仍为 `47503898D915C8FAA90FC789AEB36A6D65892C93`（与安装时一致）；面板 `agent_queue.json` 现为 `{"queue": {"lightsail": []}, "cmds": {}, "ovpn": {}}`——init_pki 0 条。
- 命令链：`POST /api/cmd {"node":"lightsail","action":"get_status"}` → **202**（cmd_id c89db4ba…）；约 8 秒后 `GET /api/cmd/<id>` → **done**，error null；result 含 openvpn running=true pid 969499（与面板一致）、sk5 enabled=false。

## 5. S1 直连态（UDP 1194）—— 通过（首次即通，零手工 FORWARD）

- 客户端（alice，netns vpntest，`--float`）：改 remote 为 LAN IP 172.26.15.152（R7 同款，公网 IP 发夹在 netns 内受限，非产品问题），**首次即通**，`Initialization Sequence Completed`（22:21:12），tun0 10.8.0.2/24，redirect-gateway 路由就位（0.0.0.0/1＋128.0.0.0/1 via 10.8.0.1 dev tun0）。PID 971734。
- 数据面（direct）：`curl ifconfig.me`（HTTP 与 HTTPS，--resolve 绕 MagicDNS）→ **16.146.199.68**；NTP UDP：216.239.35.4 回 **48 字节** 11.9ms、162.159.200.1 回 **48 字节** 6.0ms。UDP 数据面通过。
- **BUG-9 第十八次复验——修好（UDP 模式）**：部署态原始日志（逗号 v2，13 段）为 `CLIENT_LIST,alice,10.200.0.2:48828,10.8.0.2,,3563,3548,2026-11-12 22:21:12,1794522072,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `openvpn.online_users` = **1**；`openvpn.detail.clients`=[{name: alice, real_address: 10.200.0.2:48828, virtual_address: 10.8.0.2, bytes_received: "3563", bytes_sent: "3548", connected_since: "2026-11-12 22:21:12"}]——逐字段一致；`/api/openvpn/users` 的 alice `online: true`、bob `online: false`（本节实测）。注：首轮我按顶层键取 `online_users` 得 None，实为嵌套在 `openvpn.online_users` 下，测试侧取键错误，非产品问题。

## 6. S2 落地态（SK5 开）—— 通过（TCP+UDP 均走 SK5，双日志为证）

- 启用：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → 200（`/api/status` 核 `policy_routing_active: true`、enabled: true）；`/api/sk5/test` → 200（tcp_ok，89.6ms；udp_ok，`mode: native`，native UDP ASSOCIATE + DNS to 1.1.1.1:53——非 TCP 承载冒充）。
- 路由（策略路由表 100）：`ip rule`（`from 10.8.0.0/24 lookup 100`）；表 100 `default via 10.9.0.1 dev tun1` **＋ `blackhole default metric 200`（BM 层 1 在真机上在位）**；`ip route get 1.1.1.1 from 10.8.0.1` → `dev tun1 table 100`；tun1 UP、LOWER_UP。
- 数据面（dante 本地测试 SK5，出口仍为本机 IP 16.146.199.68——属测试 SK5 的已知性质）：隧道内 curl ifconfig.me（HTTP 与 HTTPS，--resolve 绕 MagicDNS）→ **16.146.199.68**；NTP UDP：216.239.35.4 回 **48 字节** 32.3ms、162.159.200.1 回 **48 字节** 27.9ms（比直连态慢，符合 SK5 路径）。
- 双日志为证：sing-box 日志（22:21:58）明文记录 `outbound/socks[bought-sk5]: outbound connection to 34.160.111.145:80`、`:443`，以及 `outbound packet connection to 216.239.35.4:123` 与 `162.159.200.1:123`——**TCP 与 UDP 均真实走了 SK5 出站**；dante 日志同窗口有 `tcp/connect` 与 `udp/udpassociate`。注：首轮 grep 用 `--since "22:23"`（当时才 22:22，未来窗口）得 0 行，测试侧时间错误，重查 22:21:50–22:22:10 窗口后得证。

## 7. S3 断网保护（杀 dante）—— 通过（数据面全断、无直连回落、自动恢复、隧道不断）

- 杀 dante（`systemctl stop danted`，inactive；MainPID 曾为 950509）：客户端 TCP `curl --resolve … http://ifconfig.me` → **exit 56**（Recv failure），HTTPS → exit 35（SSL connect error，同样失败）；NTP UDP 到 216.239.35.4 → **TimeoutError**；**无直连回落**（curl 不是成功、是失败——fail-closed 成立）。隧道未断（同一客户端 PID 971734，tun0 仍在，`Initialization Sequence Completed` 仅 1 次）。
- 面板 `/api/status`：kill 期间 **egress.ip = null**（`{'error': None, 'ip': None, 'latency_ms': None, 'via_sk5': True}` 形状同 live-9/live-10/live-11/live-12/live-13/live-14/live-15），诚实报空。
- 恢复（`systemctl start danted`，active）：客户端 TCP 立即回 **16.146.199.68**，NTP 回 **48 字节**。隧道全程未断：同一 PID 971734，client.log 里 `Initialization Sequence Completed` 仅出现 1 次、SIGUSR1 0 行——无重连、无重拨。
- 口径注记（设计，非缺陷）：kill 期间 `dig @1.1.1.1` 仍有回包——sing-box 路由规则 `protocol dns / port 53 → direct`（见 `/etc/openvpn-sk5-panel/sing-box.json`），DNS 默认走直连、不经 SK5，是文档已定设计；断网保护覆盖的是 TCP/UDP 数据面，DNS 不在黑洞范围内。
- **本节只覆盖 SK5 死亡（dante 死）情形。sing-box 本体死亡情形见 §12 BS 真机格。**

## 8. S4 TCP 备模式（443）—— 通过（BUG-14 修好，S1/S2 各重跑一次）

- **BUG-14 修好**：`POST /api/openvpn/server {"proto":"tcp","port":443,"allow_port_change":true}` → **HTTP 200**。`POST /api/openvpn/restart` → 200（新 pid 972598）。TCP 443 监听，UDP 1194 监听消失，`/api/status` 为 proto=tcp port=443 running=true；新下载的 bob.ovpn 为 `proto tcp / remote 16.146.199.68 443`（默认 remote 仍是 IPv4 公网）。SK5 保持开启态。
- **TCP 首连 120s 超时跟进——未复现（5 次全部 0.2 秒）**：5 次全新 TCP 首连全部 **0.2 秒** `TCP connection established`＋`Initialization Sequence Completed`。R7 的 120s 超时单次事件本轮未再出现（第八轮未复现）。切 TCP 前已按 live-9/live-10/live-11/live-12/live-13/live-14/live-15 教训先杀旧 UDP 客户端（PID 971734，tun0 消失确认）。
- S2-TCP（SK5 开）：新 TCP 客户端连上（22:23:29，tun0 10.8.0.2/24，PID 972923）；curl → 16.146.199.68；NTP → 48 字节；sing-box 日志与 dante 日志同窗口有 SK5 出站记录——TCP+SK5 链路在 TCP 模式下同样成立。
- BUG-9（TCP 模式）：原始日志 `CLIENT_LIST,bob,10.200.0.2:60120,10.8.0.2,,4545,4387,2026-11-12 22:23:29,1794522209,UNDEF,5,0,AES-256-GCM`；面板 `/api/status` 的 `openvpn.online_users`=**1**，`openvpn.detail.clients`=[{name: bob, real_address: 10.200.0.2:60120, virtual_address: 10.8.0.2, bytes_received: "4545", bytes_sent: "4387", connected_since: "2026-11-12 22:23:29"}]——逐字段一致。**BUG-9 第十八次复验在 UDP 与 TCP 两种模式下均修好**。注：刚连上时面板 clients 为空，系 OpenVPN 状态文件约 60 秒刷新滞后（live-9 起的已知观察），65 秒后复查即一致。

## 9. BP 真机格（真实重启）—— 通过（三格全过：好态自动恢复、损坏态大声失败、缺失态静默直连）

### 9.1 好态重启（链路启用态，22:33:17 UTC）—— 通过

- 重启前快照：sk5.json 正常（enabled=true，sha256 `a097a24d…`，与备份一致）；表 100 为 rule＋tun1 路由＋黑洞；单元含 `Wants=network-online.target openvpn-sk5-singbox.service`（无 Requires=）、`After=` 同款、`ExecStart=/opt/openvpn-sk5-panel/egress/policy-routing.sh restore`；四单元（policy/singbox/healthcheck.timer/danted）均为 enabled。
- 重启耗时约 1.5 分钟（22:33:17→22:35:01 up 1 min）。restore 单元 **ExecMainStatus=0**；journal 明文：`[policy-routing] repair mode: not creating tun1 (sing-box owns it)`、`table 100: blackhole default metric 200 (fallback kill-switch)`、`added rule: from 10.8.0.0/24 lookup 100`、`table 100: default via 10.9.0.1 dev tun1`、`enabled: 10.8.0.0/24 -> table 100 -> tun1 -> SK5`——**restore 全程未建占位 tun1**，tun1 路由只在设备活时装（R23-P2-1 的竞态已消除）。
- 启动后首档健康检查（22:34:39Z，重启后约 56 秒）：healthy，action=`none`（无需修复——restore 已装全），tcp_ok/udp_ok，egress=16.146.199.68；表 100 rule＋tun1＋黑洞齐全、tun1 UP,LOWER_UP。**无需人工干预，链路自动恢复走 SK5**（首档即 healthy，比简报要求的「档内翻 policy_repaired」更优——repair 档只在 restore 留黑洞-only 时才出现）。
- 新 TCP 客户端（旧客户端随重启死亡，属预期——进程无法跨重启）首次即通，curl → 16.146.199.68，NTP 48 字节；sing-box 日志 `file exists`/`FATAL` 0 行。

### 9.2 损坏态重启（sk5.json 损坏，22:35:42 UTC）—— 通过

- 损坏：sk5.json 改写为 `{invalid json garbage`（sha256 `77615fcd…`）；重启。
- restore 单元 **ExecMainStatus=1、Failed with result 'exit-code'**；journal 大声点名：`[policy-routing] ERROR: stored SK5 config /etc/openvpn-sk5-panel/sk5.json is damaged (invalid JSON (Expecting property name enclosed in double quotes: line 1 column 2 (char 1))); fix or remove it by hand -- refusing to change policy state`——文件＋原因＋手工修建议齐全，**且在动任何策略状态之前死**（rule 0 条、表 100 不存在、FORWARD tun0 规则 0 条）。
- sk5.json 字节不变（重启后 sha256 仍为 `77615fcd…`，损坏内容原样在位，未被静默「修好」或覆盖）。
- 面板诚实：`/api/status` 的 sk5 块 `config_error: 'cannot parse /etc/openvpn-sk5-panel/sk5.json: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)'`，enabled=false、policy_routing_active=false。
- **无静默直连**：新 TCP 客户端能连上隧道（Initialization Sequence Completed ×1），但数据面全死——curl exit 28、NTP TimeoutError。机理：restore 死前未装 FORWARD/NAT，客户端流量既无 SK5 路径也无直连 NAT（FORWARD tun0 0 条、MASQUERADE 0 条）——流量被丢、不是静默直连。R23-P2-2 的「静默降级直连」已消除（且本轮实测比旧口径更严：连直连都不通）。
- 恢复：从 `/root/r16/sk5-good.json` 拷回好文件（sha256 回到 `a097a24d…`），`POST /api/sk5 {"enabled":true}` → 200；rule＋tun1＋黑洞回位，curl 回 16.146.199.68、NTP 48 字节，config_error=None。

### 9.3 缺失态重启对照（sk5.json 删除，22:38:34 UTC）—— 通过

- 删除 sk5.json 后重启：restore 单元 **ExecMainStatus=0**，journal 仅一行 `[policy-routing] no stored SK5 config, leaving main table alone`——静默直连（无失败、无报错）；rule 0 条、表 100 不存在、FORWARD tun0 规则 0 条、sk5.json 仍不存在；面板 sk5 块 enabled=false、policy_routing_active=false、config_error=None。**缺失与损坏泾渭分明**（缺失静默、损坏大声）。
- 恢复：拷回好文件并 `POST /api/sk5 {"enabled":true}` → 200，rule＋tun1＋黑洞回位，sk5 enabled=true、policy_routing_active=true、config_error=None。
- **R23-P2-1 与 R23-P2-2 在真机上关闭。**

## 10. BQ 真机格（队列不可读）—— 通过（ELOOP 触发同分支；chmod 000 前置条件在 root 面板上不可达成，见注记）

- **注记（环境前提，非产品问题）**：机上面板以 `User=root` 运行，root 绕过文件 mode 位——`chmod 000` 后面板仍能正常读队列（22:25:58 设 000 后下一档 poll 照常重写队列、audit 仍 17 行、隔离 0 行），EACCES 前置条件在本机上无法由 mode 位产生。BQ 的修法分支是 `open()` 抛 OSError（非 ENOENT）即隔离，与错误号无关；故用自指符号链接（`agent_queue.json -> agent_queue.json`）触发同分支的 `[Errno 40] Too many levels of symbolic links`，诚实记录触发方式。
- 损坏（22:26:33，ELOOP）：agent 下一轮 poll 仍 200——节点 `last_seen` 22:26:49（损坏后仍新鲜）；**命令不下发**（隔离后队列为空，损坏期间无新命令入队、无 dispatch）。
- 隔离审计行：audit_log 17→**18 行**，新增恰 1 行（id 18）：action=`queue_corrupt_quarantined`、result=`failed`、detail 含备份路径 `/opt/openvpn-sk5-panel/panel/data/agent_queue.json.corrupt.20261112T222634453205`＋损坏原因 `queue file unreadable: [Errno 40] Too many levels of symbolic links: '…/agent_queue.json'`＋丢失计数 `queued=不可知 sent=不可知 .ovpn 回执=不可知`（「不可知」而非编 0，BQ 的诚实口径）；journal 同步有 WARNING（路径＋错误，无文件内容）。
- `.corrupt` 备份在位：隔离动作是 `os.replace` 改名，备份即被改名的自指符号链接本身（与 BQ 设计一致：原文件被保全、可手工恢复）；新鲜空队列文件已由 `_save_queue` 写回（53 字节）。
- 恢复：从事前备份拷回队列（sha256 回到 `ab55703a…`，3113 字节、0600）；新下发 get_status → 202，8 秒内 done——链路正常。

## 11. BR 真机格（机上 mock-KV 格）—— 通过（11/11）

- 机上 node v18.20.4（live-13/live-14 同款坑）：探针在测试机上跑、mock KV 在内存里模拟 `loginfail:<ip>` 键，Worker 代码走真实 `cloudflare/src/index.js`（BR 版，sha256 `f43180976393…`，与 §0 打包树一致，机上核对一致），`package.json {"type":"module"}`＋`--experimental-global-webcrypto`。不是真实 Worker 部署，不冒充。
- BR 探针 `tests/br_loginfail_array.mjs`：**11 格全过，FAIL 0**（数组空／非空、字符串、缺失、对象对照均 6 次后 429；锁 15 分钟，Retry-After 900；预置 2 次失败计入锁定；已锁记录双向 429；成功登录清 key；缺字段补全且计数保留；字段级损坏仍 loud 500）。
- **R23-P2-4 在机上 mock-KV 格上成立。**

## 12. BS 真机格（杀 sing-box → kill-switch 命名）—— 通过（两轮循环，命名与恢复均正）

- 第一轮（SIGTERM，22:27:53）：sing-box inactive、tun1 消失、表 100 只剩 `blackhole default metric 200`；客户端 curl exit 28、NTP TimeoutError——流量被黑洞兜住、绝无直连。
- 命名：健康检查档（22:28:25Z）报 **`blackholed_kill_switch`**（不再是 `policy_missing`）；detail 全文：`sing-box not running; policy routing is not applied, VPN traffic is held by the fallback blackhole route in table 100 (not egressing direct); auto-repair: policy re-applied by health check (blackhole + rule in place; tun1 route waits for sing-box)`——含黑洞兜底、**无「did not stick」**（R15-BUG-1 的文案已修净）；`policy_routing_active: false`、`singbox_running: false` 均诚实。
- 手动重起：干净启动（新 PID 975110，NRestarts=0，tun1 UP,LOWER_UP，`file exists`/`FATAL` 0 行）；下一档（22:29:26Z）翻 **`policy_repaired`**（tcp_ok/udp_ok，egress=16.146.199.68）；curl 回 16.146.199.68、表 100 tun1＋黑洞齐全。
- 第二轮（SIGKILL，22:31）：systemd **8 秒内自动重起**（新 PID 975992，**NRestarts=1**，未触 StartLimitBurst 上限）；tun1 UP,LOWER_UP，`file exists`/`FATAL` 0 行；下一档（22:32:28Z）再翻 **`policy_repaired`**，curl 回 16.146.199.68。
- 隧道全程未断：同一 TCP 客户端 PID 972923 存活，client-tcp.log 里 `Initialization Sequence Completed` 仅 1 次（两轮均未重连）。
- **R15-BUG-1 在真机上关闭。**

## 13. headline 回归精选 —— 通过（6 项全过；另有接管注记与 1 个已接受限制的确定性红格，见 13.0／13.4）

### 13.0 接管注记（原 lane 中断，22:44:25 UTC）

- 原 lane 于 22:44:25 UTC 中断死亡，无完工回执；报告 §0–§12 已写完，§13／§14 为接管补写。接管先重核地面真值（23:10–23:12 UTC）：五服务全 active、表 100 rule＋tun1＋黑洞齐全、SK5 启用、CA `47503898D915C8FAA90FC789AEB36A6D65892C93` 与安装时一致——与 §12 状态一致，§9–§12 的数字沿用（接管未重跑 BP／BQ／BR／BS 格）。
- 原 lane 中断前在 22:43:32–22:44:18 发出 13 次 toggle-only `POST /api/sk5`（audit id 43–55），journal 里同窗口 `Started openvpn-sk5-singbox.service` 共 12 行——与“setup disable＋10 交替＋并发双启用（delta 1）”的 13 发／12 次重起吻合，但逐格 Started 读数从未落盘，**无法采信为 headline-1／2 的实测值**。接管按同口径从已知态完整重跑 11.1／11.2（见下），以下数字均为接管重测值。另：新 TCP 客户端为接管所建（PID 17332，bob-tcp-lan.ovpn；§8 的旧客户端随 BP 重启死亡属预期，§9.1 已记）。

### 13.1 headline-1 首启一次 200 —— 通过（首启一次 200；10 次交替全一次 200，delta 恰 10）

- **首启（全新安装后第一次启用）**：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功，§6）。**R6-BUG-1 真机回归通过**。
- **10 次交替**（接管重跑，脚本 `/root/r16/alt10-r16.sh`，从禁用态起，奇数步全表单启用、偶数步单字段禁用，均为真实翻转）：基线 Started 177 → setup disable 178 → 10 步逐格 179→180→181→182→183→184→185→186→187→188，**每步 +1，delta 恰 10**，10 步全部 200 一次成功（全程约 250 秒，每步含 2 秒等待 Started 落盘）。注：禁用步亦 +1——disable 同样重起 sing-box（重渲染直连模式配置），与 live-15 的逐格 +1 一致。
- TCP 客户端 PID 17332 全程未断（`Initialization Sequence Completed` 仅 1 次）。

### 13.2 headline-3 并发启用 delta 恰 1 —— 通过（双 200，delta 恰 1）

- 从禁用态起（11.1 步 10 结束态），两路全表单启用同时发出 → **双 200**，Started 188→189（**delta 恰 1**），终态 enabled=true、policy=true、via=true、ip=16.146.199.68。AH 的 `_SK5_MUTATE_LOCK` 在真机并发路径上成立。**R7-BUG-3 真机终验通过**。
- TCP 客户端 PID 17332 全程未断。

### 13.3 headline-5 policy-missing 诚实＋零重起修复 —— 通过（手动删策略，面板重开零重起修复）

- **首轮测试侧失误（已修正，不立案）**：停定时器的命令与定时器下一触发（23:23:10Z）撞车——删路由后 3 秒健康检查即跑并报 `policy_repaired`（“policy was missing, auto-repaired by this check”），面板仍显示 policy=true。该轮反证健康检查自愈速度（删路由后 3 秒内补回），但未跑出“诚实缺失值”；遂确认定时器 inactive 且 23:24:00 后零触发后重跑。
- **诚实（重跑）**：定时器 inactive，手动删表 100 的 tun1 路由（表 100 只剩黑洞），13 秒后面板 `/api/status`：`via_sk5=false`、`egress.ip=None`、`policy_routing_active=false`（enabled 仍 true），未谎称经 SK5、未谎称黑洞。注：`last_health` 仍为 23:23:10 的 `policy_repaired`（上次健康检查结果，非本次状态）。
- **零重起修复**：全表单重开 → 200，收据 **`repaired: true`、`repair_detail: ["policy routing re-applied"]`**，Started 189→189（delta=0，**零重起补策略**）；恢复后 rule＋table 100 均在位，`policy_routing_active=true`、curl 回 16.146.199.68。TCP 客户端 PID 17332 全程未断；事后定时器已恢复 active。

### 13.4 headline-6 verify.sh 双态 —— 通过（首轮各 1 红系已接受限制，毒树重跑补规则后重测全绿）

- **开态首轮**（SK5 开）：**PASS=17 FAIL=1 SKIP=4**——唯一 FAIL 为 `direct-forwarding`（`FORWARD accept tun0 10.8.0.0/24 -> ens5 missing`）。定因（非新 bug）：全新安装时 install.log:30–32 已加 NAT MASQUERADE 与两条 FORWARD 规则、:55 转发门通过；BP §9 的三次真实重启后规则全失（NAT POSTROUTING 无 10.8.0.0/24 项、FORWARD 无 tun0→ens5 项），机上 uptime 49 分钟佐证重启——正是 AN 已接受的限制（install.log:6 明文＋README:71：ufw 机上 NAT／FORWARD 规则 live-only、不 survive 重启，须重跑 install.sh 补）。SK5 数据面不受影响（tun0↔tun1 规则由 policy-routing enable 所加、在位；客户端 curl／NTP 全程正常）。
- **关态首轮**（面板关 SK5 后 25 秒再跑）：**PASS=22 FAIL=1 SKIP=0**——同一 FAIL、同一原因（确定性，非瞬态）。
- **补救与重测**：headline-9 的毒树默认重跑（§13.6）按文档口径补回全部三条规则（install-rerun.log:25–27）；随后重跑开态 **PASS=18 FAIL=0 SKIP=4**、关态 **PASS=23 FAIL=0 SKIP=0**，**双态 ALL GREEN**。关态跑完后 SK5 为禁用（verify.sh 的 enable 探针自带清理禁用）。

### 13.5 headline-7 前端真渲染 —— 通过（真渲染：0 项低于 4.5，最薄 4.92；零 JS 异常）

- 真机 headless Chromium 渲染（1440x900，`render/dashboard.png`＋`render-contrast.json`，脚本为 cdp-r14.py 的 r16 路径版 cdp-r16.py）：标题 “OpenVPN + SK5 面板”、h1 “概览”；可见文本元素 **166 项，0 项低于 4.5**，最薄 **4.92**（“当前 .ovpn 的 remote 为公网地址 16.146.199.68，站外”，绿字白底）；32 项低于 7.0（目标值，非门禁底线；live-15 为 35 项）。注：元素数 166（live-15 为 171）系本轮渲染时 SK5 处于禁用态、面板少一组启用态文案，门禁项 0 低于 4.5 不变。
- 控制台事件 4 条：3 条 verbose 级 DOM 建议（密码字段不在 form 内等）＋1 条 favicon.ico 404（缺 favicon 资产）；**零 JS 异常**（无 Uncaught／exception 条目）。favicon 404 与 live-10–15 同款，记观察、不立案。

### 13.6 headline-9 毒树默认重跑行级比对 —— 通过

- 毒树（`/root/r16/install-src/openvpn-sk5-panel/`，含毒 panel.db＋毒 agent_queue.json）默认重跑 `bash install.sh`（无任何 flag，日志 `/root/r16/install-rerun.log`，AN 新行 1 条、ERROR 0、完成横幅已印；nohup 后台跑，未断会话）。
- 行级比对（重跑前快照 `/root/r16/h9-before.json`）：admin 行**完全一致**（哈希仍为全新 `$2b$12$sjDFuLVVm74j3…`，非毒 `$2b$12$tceqe…`）；login_attempts **一致**（0 行）；nodes **一致**（1 行 lightsail，name＋url 一致）；audit 80→81 行，**前 80 行完全一致**，新增 1 行仅为重跑后本轮登录（admin login ok，合法）；server PID 不变（510，服务未重起）；`agent_queue.json` 的 cmds 仍仅 3 条合法 get_status（done），**毒的 3 条 init_pki 未入住**；BN 的 `.corrupt` 备份仍在。
- **R8-BUG-1（毒树重跑销毁线上 panel.db）本轮终验通过。**附带：重跑补回 §13.4 的三条 NAT／FORWARD 规则（install-rerun.log:25–27）。

## 14. 结论与机器终态

**结论：全部通过，零新 bug。** BP／BQ／BR／BS 四路修复的真机格全过（§9–§12：BP 真实重启三格、BQ 隔离审计行、BR mock-KV 11/11、BS 两轮 kill-switch 命名与恢复），S0–S4 全过，headline 六项全过（§13）。R23 的 4 条与 R15-BUG-1 在真机上关闭。AUDIT-R24 的差集 1 条（R24-P2-1）不属本轮，其修复 BT 路的真机格属 live-17。

**机器终态（2026-11-12 23:33 UTC）**：TCP 443 模式（openvpn PID 510，UDP 1194 已无监听）；面板 8443（PID 511）；sing-box active（MainPID 26708，NRestarts=0）；agent active（PID 516）；dante active（PID 568）。SK5 **禁用**（关态 verify 清理后状态）；表 100 空。TCP 客户端 PID 17332 仍连接在 netns `vpntest` 里（`Initialization Sequence Completed` 全程仅 1 次，直连态 curl 回 16.146.199.68）。用户 alice／bob 有效。CA `47503898D915C8FAA90FC789AEB36A6D65892C93`（与安装时一致，毒 init_pki 从未执行）。节点 lightsail 在线。ufw 4015 行。FLMX 同机进程未碰。证据在 `/root/r16/`（install.log、install-rerun.log、h9-before.json、alt10-r16.sh、cdp-r16.py、render/、client-tcp16.log、token.txt 0600）；证据 tarball `/root/ovpn-r16.tar.gz`（2e624c07…）在位，r7–r15 tarball 未动。

**未验**：R24-P2-1 的修复后复验（属 live-17）；Cloudflare Worker 真机部署（P0-1/2/3，仍待用户决断）；arm64 安装校验（本机 x86_64，无 arm64 机）。

**本轮方法注记**：§0–§12 为原 lane 实测（接管只核了地面真值一致性，未重跑 BP／BQ／BR／BS 格）；§13 为接管重测值（11.1／11.2 全程重跑；11.3 首轮测试侧失误后重跑；11.4 开/关态各跑两轮——首轮确定性红＋补救后重测绿；11.5／11.6 各跑一次）。verify.sh 的四次输出未落盘存档，数字以 §13.4 所记为准。测试侧残留：verify.sh 的 user-ovpn 检查留下 4 个 verify-* 用户（2 valid、2 revoked），其脚本只建不删，面板行为本身正常。测试侧失误均已当场修正并在各节注明，修正后的数字均为重测实测值；任何一次「通过」均以重测通过为准，不以失误轮次的数字充数。

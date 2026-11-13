# OpenVPN 接 SK5 落地 · 真机复跑验证报告（第九轮 R9）

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（AK/AL/AM＋AN 修复后的最新树——本轮第一次验证这些修复）。
> 验证人：真机复跑验证路（第九轮）。日期：2026-11-12。
> **结论先写：全部通过，无新 bug。** S0–S4、headline-1～9 全部通过（19 节全填）：R8-BUG-1 毒源树默认重跑行级比对全保留、R8-BUG-2 ufw 长表 2000 条完整且 1194/8443 已加、R9 的 5 条与 live-8 的 2 条均已真机关闭；verify.sh 开 18/0/4、关 23/0/0；真渲染 171 字、0 低于 4.5。AUDIT-R12 的 9 条（AS/AV 仍在修）与 Cloudflare 真实部署（P0-1/2/3）不在本轮树验收范围内。
> 前情：第八轮见 [live-verify-R8.md](live-verify-R8.md)（S0–S4 全过，headline-1～7 全过，headline-8 部分通过，headline-9 未通过——新 bug R8-BUG-1 高阻塞＋R8-BUG-2 高；R8-P2-4 长表未验）；AUDIT-R9（409 行）判不能交付、差集 5 条，修复路 AK/AL/AM 已完工并主控核验；AN 路修 live-8 的 R8-BUG-1/R8-BUG-2 已完工并主控核验；AUDIT-R10 与本轮并行在跑。

## 0. 树版本（本次装机所用）

| 文件 | mtime (UTC) | sha256（前 12 位） | 说明 |
|---|---|---|---|
| install.sh | 2026-11-12 14:11:22 | 5af298b955f0 | AN 路：panel/ staging 拷贝（panel/data/ 永不拷入）、`_PANEL_COPIED` 门控与无条件 `rm -f secret.key` 删除、iptables-persistent 只在无 ufw 时装（ufw 机跳过＋apt 后断言） |
| panel/app.py | 2026-11-12 13:15:22 | eb3692ea7c3d | AK 路：naive sent_at 按 UTC 解读、损坏队列改名 .corrupt 备份告警、登录失败记录/bcrypt 迁移包 try/except（2006 行） |
| core/openvpn_manager.py | 2026-11-12 13:14:53 | 2b7cf0745d46 | AL 路：`_index_expiry_is_past`，V 行过期即报 expired（1404 行） |
| egress/policy-routing.sh | 2026-11-12 12:13:01 | 103a121bbdfe | AG 路（未动） |
| egress/README.md | 2026-11-12 12:16:15 | 63f38f69d7fc | AG 路（未动） |
| egress/sk5_manager.py | 2026-11-12 12:37:13 | 02de9d8a4908 | AJ 路（未动） |
| panel/templates/index.html | 2026-11-12 09:20:59 | 30721319b07e | AA 路（未动） |
| verify.sh | 2026-11-12 13:15:34 | e9a3b749faaa | 主控：:234 旧行号注释改 marker 写法（AM 指出） |
| verify-integration.sh | 2026-11-12 09:35:55 | 7e040ea3ee4a | AD（未动） |
| egress/test-egress.sh | 2026-11-12 08:40:51 | d6db69ec0a6e | X 路（未动） |
| cloudflare/src/index.js | 2026-11-12 09:24:00 | 6c81c38dc1ea | Y2（未动） |
| README.md | 2026-11-12 14:26:01 | 96c0f472c223 | 主控：:71 iptables-persistent 改条件化写法（AN 指出文档漂移） |
| panel/README.md | 2026-11-12 13:13:58 | aab5d206eccf | AM 路：行数/行号钉位改 marker 写法 |

树稳定检查：14:42:04 核查时最新产品改动为 README.md（14:26:01），**稳定 16 分 03 秒，门过**（其间只有 AUDIT-R10 的报告文件与本报告在写，产品文件无变动）。打包时源码树 `panel/data/` 为空（`ls` 空）；毒 panel.db＋agent_queue.json 由 AE 的真实代码毒快照（`~/workspace/ae-tests/poison/`）注入打包副本，**源码树本身未被毒化**。

**打包（14:42 UTC）**：传包走 scp（R4–R8 同款）。`ovpn-r9.tar.gz`：41 条目，180,435 字节，sha256 `d4489a17263f78145a5694d90786f6e7aa060694972534c004918618575a66c7`（机上核对一致）；install.sh sha256 `5af298b955f0b29739c8090aab256a23dad6521f93d5cd7d6084133ed74e8e67`。打包插曲：首版 tar 有 51 条目——多出 10 条 `__pycache__`（AK/AL/AM 探针 import 留下的 .pyc），已剔除重打回 41 条目，与 live-8 同口径。包内毒物核对：`panel/data/panel.db` 含 admin 行 1 条（哈希 `$2b$12$tceqe…`）、`panel/data/agent_queue.json` 含 3 条 init_pki force+confirm（1 sent、2 queued，节点 n1/n2）——与 R8 §6.2 的毒形一致。

## 1. 地面真值（Lightsail 现状，测试前实测，14:27 UTC）

- 机上是**第八轮收尾态**：安装 #3 全新部署，TCP 443（server PID 738888），面板 PID 735794，dante PID 661020 active，agent inactive，SK5 关；alice TCP 客户端 PID 738950 在 netns `vpntest`（tun0 10.8.0.2）。
- 第八轮残留全部在位，**重装前必须清除**：
  - netns `vpntest` 仍在；
  - `/root/r8/` 测试产物在位（panel.py、netns-setup.sh、probe.sh、cdp.py、install/install2/install3/install-default.log 等）；
  - alice 客户端 PID 738950 仍在跑（第八轮 TCP 客户端）；
  - `/root/ovpn-r8.tar.gz`（毒包，证据，**勿删**）与 `/root/ovpn-r7.tar.gz`（对照留存，**勿删**）在位；
  - `/opt/openvpn-sk5-panel/` 为第八轮装树；`/etc/openvpn-sk5-panel/` 含 admin.pass（0600）。
- ufw 未装（dpkg 无记录、`command -v ufw` 空），与第八轮收尾态一致；无 ufw 看门狗进程残留。
- FLMX 相关进程同机在跑（paneld、flmx-int2 paneld、flmx_agent），**一律不碰**；`/root/flmx-panel` 不动。

## 2. 清场（全新重装前，14:28–14:31 UTC）

- 客户端 PID 738950 按精确 PID 杀掉，已确认无此进程；四服务已停（openvpn/singbox/panel/agent 全部 inactive，dante 保留，active）。
- FORWARD 链清至只剩 ts-forward/DOCKER-USER/DOCKER-FORWARD（策略 DROP）：删 veth-host 测试规则 2 条、tun0 规则 2 条（带 `-s/-d 10.8.0.0/24` 前缀的实测形状）、NAT POSTROUTING 的 `-s 10.8.0.0/24 -o ens5 MASQUERADE` 1 条；netns `vpntest` 已删。
- 状态已 wipe：`/root/openvpn-sk5-panel`、`/opt/openvpn-sk5-panel`、`/opt/ovpn-agent`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/ovpn-agent` 全删；sing-box 与 tun2socks 二进制已删（逼安装器走下载路径，复验版本校验）；`/root/r8/`、`/root/ovpn-r8.tar.gz`（毒包证据）、`/root/ovpn-r7.tar.gz` 保留未动。
- 清场后核对：只剩 tailscale0 一个 tun 设备、无 1194/443/8443 监听、`/opt/openvpn-sk5-panel` 与 `/etc/openvpn-sk5-panel` 不存在。
- S0 安装已于 14:44 UTC 后台启动（`nohup bash install.sh`，日志 `/root/r9/install.log`）。

## 3. S0 基线：毒包安装 + 建服务 + 建用户 —— 通过（一次成功；R7-BUG-2＋第二毒物终验通过，AN 新行在位）

### 3.0 第一次安装（毒包，全新安装，UDP 1194 默认）—— 通过

- install.log：**0 个 ERROR**；sing-box 1.11.15 下载 `sha256 OK`、自报 `sing-box version 1.11.15`；tun2socks 2.7.0 下载 `sha256 OK`、自报 `tun2socks-2.7.0`——两次版本校验均一次通过（R7-BUG-1 本格未再撞 SIGPIPE，见 §17）。
- **毒物未入住（AN 新行为）**：日志有新行 `[install] panel/ installed (panel/data/ excluded: runtime state is never shipped and a re-run never touches the live database)`（1 条）；旧 `discarded shipped runtime file` 行 **0 条**（已随 AN 修法消失，属预期——无物可丢）；**完成横幅已印**；初始密码已生成并写入 `/etc/openvpn-sk5-panel/admin.pass`（0600，mtime 14:43）。
- 装后核对：`/opt/openvpn-sk5-panel/panel/data/` 仅含 panel.db，**agent_queue.json 文件不存在**（毒队列从未拷入）；panel.db 的 admin 行哈希为 `$2b$12$sjLy6TS7MA2IlRe3UaVMY.O…`，与毒哈希 `$2b$12$tceqe…` 不同——全新 admin 行；nodes 0、audit 1 行（全新库）。
- 五单元：openvpn/singbox/panel/policy 全 active，agent inactive（属预期，由 S0-agent 安装），restarts 全 0；CA 序列 `2A3296AC99565A132FD4A78E9F6B20A789C42DAC`（notBefore 2026-11-12 14:43，记下供 agent 轮询后对比）。
- 无 ufw 回归格（AN 的 R8-BUG-2 反面）：机上无 ufw 时 iptables-persistent 1.0.20 照旧装上（dpkg `ii`）、`/etc/iptables/rules.v4`＋`rules.v6` 在位；ufw 块无日志行（静默跳过，属预期）。

### 3.1 S0 后半段：建服务确认＋建用户 —— 通过

- 面板登录 200；`/api/status` 200：openvpn running（UDP 1194，PID 752246），online_users 0，SK5 未启用，`singbox_running: true`，sk5 块 `policy_routing_active: false`。
- 默认 `.ovpn` remote 为 **16.146.199.68 1194**（IPv4 公网）；`GET /api/openvpn/public-ip` 返回 `16.146.199.68`。
- 用户：alice、bob 创建均 200；`GET /api/openvpn/users` 只列 alice、bob，alice 序列号 `B97D74C4A3702BBD7BA204E2C235DE90`、bob `E8085DA85A7BB16DD4FF13EC3A5F9163`；`.ovpn` 下载 200，`proto udp / remote 16.146.199.68 1194 / cipher AES-256-GCM / auth SHA256`，`<cert>` 块 subject `CN = alice`、issuer `CN = OpenVPN-CA`、含 2 个 CERTIFICATE 块（用户证＋CA）。

## 4. S0-agent：节点注册 + agent 安装 + 命令链 —— 通过（第二毒物 agent 侧终验通过）

- 注册：`POST /api/nodes {"name":"lightsail","panel_url":"https://172.26.15.152:8443"}` → 201，token 只存 `/root/r9/token.txt`（未写报告）。中途一次 409 是测试侧重复注册（首 POST 已成功、token 未存盘），删节点重注册后取到 token——测试侧流程问题，非产品问题。
- 安装命令（面板两步走命令，按 agent/README 记载的流程执行；token 由文件读入）：`curl -ksSL …/install-agent.sh`＋sha256 校验 `install-agent.sh: OK`＋`bash /tmp/install-agent.sh --panel-url … --token … --node-name 'lightsail'` → **EXIT=0**。TOFU 钉证书、bundle sha256 OK、`/etc/ovpn-agent/config.json` 0600、`ovpn-agent is ACTIVE (node=lightsail)`。
- poll：`GET /api/nodes` 的 `last_seen` 为 2026-11-12T14:51:04+00:00（新鲜）；agent 日志 5 分钟内无 401/403、无 poll failed、无 init_pki。
- **毒 init_pki 未执行**：agent 上线并轮询后，CA 序列仍为 `2A3296AC99565A132FD4A78E9F6B20A789C42DAC`（与安装时一致）；面板 `agent_queue.json` 现为 `{"queue": {"lightsail": []}, "cmds": {}, "ovpn": {}}`——空队列，init_pki 0 条。
- 命令链：`POST /api/cmd {"node":"lightsail","action":"get_status"}` → **202**（cmd_id 8742e242…）；约 3 秒后 `GET /api/cmd/<id>` → **done**，error null；result 含 openvpn running=true pid 752246（与面板一致）、sk5 enabled=false。

## 5. S1 直连态（UDP 1194）—— 通过（首次即通，零手工 FORWARD）

- 客户端（alice，netns vpntest，`--float`）：改 remote 为 LAN IP 172.26.15.152（R7 同款，公网 IP 发夹在 netns 内受限，非产品问题），**首次即通**，`Initialization Sequence Completed`（14:51:29），tun0 10.8.0.2/24，redirect-gateway 路由就位。PID 755487。
- 数据面（direct）：`curl ifconfig.me`（HTTP 与 HTTPS，--resolve 绕 MagicDNS）→ **16.146.199.68**；`dig @1.1.1.1 ifconfig.me` → 34.160.111.145 有回包；NTP UDP：216.239.35.4 回 **48 字节** 11.7ms、162.159.200.1 回 **48 字节** 5.9ms。UDP 数据面通过。
- **BUG-9 第九次复验——修好（UDP 模式）**：部署态原始日志（逗号 v2，13 段）为 `CLIENT_LIST,alice,10.200.0.2:35678,10.8.0.2,,6435,13072,2026-11-12 14:51:29,1794495089,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users` = **1**；`clients`=[{name: alice, real_address: 10.200.0.2:35678, virtual_address: 10.8.0.2, bytes_received: "6435", bytes_sent: "13072", connected_since: "2026-11-12 14:51:29"}]——逐字段一致；`/api/openvpn/users` 的 alice `online: true`、bob `online: false`（本节实测）。
- 时序注记：客户端 14:51:29 连上后即刻查面板为 online 0——openvpn 状态文件按约 60 秒周期写盘，首次连后写盘在 14:52:01，面板读到新文件后即为 1；是状态文件写盘周期，不是产品缺陷。

## 6. S2 落地态（SK5 开）—— 通过（TCP+UDP 均走 SK5，双日志为证）

- 开启（全新安装后第一次启用）：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功，见 §10）；enabled=true，`policy_routing_active: true`，egress_ip 16.146.199.68；sing-box 重起一次（PID 752294→755865，属首次渲染 SK5 配置的预期重起）；`ip rule` 有 `from 10.8.0.0/24 lookup 100`；table 100 为 `default via 10.9.0.1 dev tun1`；`ip route get 1.1.1.1 from 10.8.0.1` → `dev tun1 table 100`；tun1 UP。alice 的隧道在开启前后未断（同一客户端 PID 755487 持续）。
- 开启前基线：rule 100 与 table 100 均为空（本轮安装器未留 rule 残留态，与 R6/R7 的“rule 在位、table 空”不同——启用一次 200 不受影响）。
- 面板 `POST /api/sk5/test` → **tcp_ok: true、udp_ok: true**（native 模式，TCP 延迟 137.2ms）。
- 客户端 TCP（经 SK5）：`curl --resolve ifconfig.me:80:34.160.111.145 http://ifconfig.me` 与 HTTPS 同式均回 **16.146.199.68**；sing-box 日志同秒有 `outbound/socks[bought-sk5] … to 34.160.111.145:80` 与 `:443`；dante 日志同窗口 16 条 `tcp/connect`/`udpassociate`——TCP 确实走了 dante（SK5 替身）。出口 IP 不变属预期：替身与面板同机，S1/S2 出口恒为 16.146.199.68，链路证明以路由表 + 双日志为准（R1 已定口径）。
- 客户端 UDP（经 SK5）：NTP 到 216.239.35.4 回 **48 字节** 18.2ms、162.159.200.1 回 **48 字节** 23.5ms；sing-box 日志有 `outbound/socks[bought-sk5] … outbound packet connection to 216.239.35.4:123` 与 `162.159.200.1:123`。UDP 走 SK5 为证。

## 7. S3 断网保护（杀 dante）—— 通过（流量全断、无直连回落、自动恢复、隧道不断）

- 杀 dante（`systemctl stop danted`，inactive）：客户端 TCP `curl --resolve … http://ifconfig.me` → **exit 56**（Recv failure），HTTPS → exit 35（SSL connect error，同样失败）；NTP UDP 到 216.239.35.4 → **TimeoutError**，162.159.200.1 同样 TimeoutError；**无直连回落**（curl 不是成功、是失败——fail-closed 成立）。隧道未断（同一客户端 PID 755487，tun0 仍在，`Initialization Sequence Completed` 仅 1 次）。
- 面板 `/api/status`：kill 期间 **egress.ip = null**（`{'error': None, 'ip': None, 'latency_ms': None, 'via_sk5': True}`），诚实报空；sk5 enabled=true、policy=true。
- 恢复（`systemctl start danted`，active）：客户端 TCP 立即回 **16.146.199.68**，NTP 回 **48 字节** 16.2ms/8.8ms。隧道全程未断：同一 PID 755487，client.log 里 `Initialization Sequence Completed` 仅出现 1 次、SIGUSR1 0 行——无重连、无重拨。

## 8. S4 TCP 备模式（443）—— 通过（BUG-14 修好，S1/S2 各重跑一次）

- **BUG-14 修好**：`POST /api/openvpn/server {"proto":"tcp","port":443,"allow_port_change":true}` → **HTTP 200**。`POST /api/openvpn/restart` → 200（新 pid 756552）。TCP 443 监听，UDP 1194 监听消失，`/api/status` 为 proto=tcp port=443 running=true；新下载的 alice.ovpn 为 `proto tcp / remote 16.146.199.68 443`（默认 remote 仍是 IPv4 公网）。SK5 保持开启态。
- **TCP 首连 120s 超时跟进——未复现（5 次全部 1 秒）**：5 次全新 TCP 首连全部 **1 秒内** `TCP connection established`＋`Initialization Sequence Completed`（14:59:56、15:00:02、15:00:08、15:00:14、15:00:20，各 1s）。R7 的 120s 超时单次事件本轮未再出现。
- **测试侧教训（不立案）**：首版 tcp-tries 的 try 1 曾卡在 `Attempting to establish TCP connection` 达 120 秒后 `Connection timed out`，且 netns 内 plain TCP（443/8443/外网 1.1.1.1:443）全挂——三证定位为测试侧失误：切 TCP 前未杀旧 UDP 客户端（PID 755487），其 redirect-gateway 路由仍把 netns 全部流量送进已死的 UDP 隧道（服务端已切 TCP，旧隧道服务端无记录）；`ss` 见 SYN-SENT 的本地地址正是 10.8.0.2（tun0），veth-host 上 tcpdump 0 包。杀掉旧 UDP 客户端＋卡住的重试点（755487、758253）后 tun0 消失、默认路由回 veth-host，plain TCP 立即通，5 次重跑全部 1 秒。R7 的单次 120s 很可能也是同一机制（旧客户端未清），不是产品缺陷。
- S2-TCP（SK5 开）：新 TCP 客户端连上（15:01:34，tun0 10.8.0.2/24，PID 760174）；curl → 16.146.199.68；NTP → 48 字节 36.3ms/10.2ms；dante 日志同窗口 12 条 `tcp/connect`/`udpassociate`——TCP+SK5 链路在 TCP 模式下同样成立。
- BUG-9（TCP 模式）：原始日志 `CLIENT_LIST,alice,10.200.0.2:52396,10.8.0.2,,4659,4514,2026-11-12 15:01:34,1794495694,UNDEF,10,0,AES-256-GCM`；面板 `/api/status` 的 `online_users`=**1**，`openvpn.detail.clients`=[{name: alice, real_address: 10.200.0.2:52396, virtual_address: 10.8.0.2, bytes_received: "4659", bytes_sent: "4514", connected_since: "2026-11-12 15:01:34"}]——逐字段一致。**BUG-9 第九次复验在 UDP 与 TCP 两种模式下均修好**。
- S1-TCP（SK5 关）：单字段 `{"enabled":false}` → 200（`policy_removed: true`、disable 后 sing-box 仍在 direct 模式跑，R3-BUG-1 修好）；rule 100 消失、table 100 空、路由回 ens5；TCP 客户端 curl → 16.146.199.68，NTP → 48 字节 32.0ms/7.3ms，dig @1.1.1.1 → 34.160.111.145；同一客户端 PID 760174 全程未断（`Initialization Sequence Completed` 仅 1 次）。

## 9. BUG-15/16 默认重跑 —— 通过（R8-BUG-1 验收：行级比对全保留，毒包未入）

- **前置部署**（安装 #3 之上）：节点 lightsail 注册 201（`panel_url` 显式 `https://172.26.15.152:8443`——见下测试侧教训）；agent 安装 EXIT=0、`ovpn-agent is ACTIVE (node=lightsail)`、config 0600；`last_seen` 新鲜；`POST /api/cmd get_status` → 202，约 8 秒后 done、error None、openvpn running pid 802368。当前 agent 日志（15:48 起）0 条 401/403/poll failed/init_pki（全日志 grep 命中 11 条均为 13:20–14:51 的旧轮残留，journal 跨安装保留所致）。
- **行级快照**（重跑前，`/root/r9/db-before.json`）：admin 1 行（哈希 `$2b$12$ydqZ…`）、login_attempts 0、nodes 1（lightsail，`last_seen` 15:51:59）、audit_log 11 行（末行 agent_report get_status done）；队列 lightsail 空、1 条 done 命令（get_status）；用户 alice、bob 均 valid（PKI 序列 `E2518A45…`／`1909C839…`）。
- **重跑**：毒树 `/root/r9/poison-tree`（毒 admin 哈希 `$2b$12$tceqe…`、nodes 0、队列 3 条 init_pki force+confirm），从中 `bash install.sh`（无 OVPN_PROTO/OVPN_PORT，继承已部署 UDP 1194）：一次成功，横幅出，**0 ERROR**，新日志行 `panel/ installed (panel/data/ excluded: …)` ×1、旧 `discarded shipped runtime file` ×0；日志第 48 行 `[install] panel health gate passed (login + /api/status 200)`；重跑全程约 40 秒（已部署态跳过下载/建 CA/建 PKI，只重拷文件＋跑健康门）。
- **行级比对**（重跑后，`/root/r9/db-after.json`）：admin **IDENTICAL**、login_attempts **IDENTICAL**；nodes 除 `last_seen` 15:51:59→15:56:12 外全部字节一致——last_seen 是 agent 心跳正常更新的活证据，非损坏；audit_log 11→13、**前 11 行逐行一致**，新增 2 行均为 `login ok ip=127.0.0.1`：15:52:41 是安装器自己的健康门登录、15:56:14 是本次验收登录——两行均为合法登录，无一丢失、无一篡改；队列仍为 lightsail 空＋同一条 done 命令。**文件哈希未用**（符合 AN 交代：健康门登录写审计行，哈希必然变）。
- **重跑后状态**：登录 200；openvpn 主进程 PID 802368 不变、1194/udp 照常监听（重跑未重启服务端）；alice、bob 仍 valid；重跑后新发 `get_status` → 202→done、error None、openvpn running pid 802368。
- **R8-BUG-1 真机验收通过**：毒源树默认重跑未动活库分毫，旧版“面板永久 401、节点记录丢失”未复现。
- **测试侧教训（不立案）**：首版节点注册未传 `panel_url`，面板按 `request.host_url` 默认为 `https://127.0.0.1:8443`，随后 agent 安装 `--panel-url https://127.0.0.1:8443` 在 P2-13 自检步 die（curl exit 60：`SSL: no alternative certificate subject name matches target host name '127.0.0.1'`）——面板证书 SAN 为 `IP:172.26.15.152,DNS:localhost`（install.sh:538 `SERVER_IP="$(primary_ip)"`），不含 127.0.0.1；钉住的证书与服务端证书序列一致（`5A1B4047…`），pin 本身无误；`https://172.26.15.152:8443` 同证书一次即通。按 live-8 §4 既定口径重注册（显式 `panel_url` 为 LAN IP）后 agent 安装 EXIT=0。认领守卫要求 `--panel-url` 与注册值逐字一致，故不能只换 agent 侧 URL，必须重注册——此为测试侧偏离 live-8 口径所致，非产品问题。

## 10. headline-1 R6-BUG-1 首启一次 200 回归 —— 通过（首启一次 200；10 次交替全一次 200）

- **首启（全新安装后第一次启用，复刻 live-6/live-7 §10 精确序列）**：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功）。此前基线：rule 100 与 table 100 均为空（本轮安装器未留 rule 残留态，与 R6/R7 的“rule 在位、table 空”不同）；sing-box MainPID 752294→755865、journal `Started` 计数 110（属首次渲染 SK5 配置的预期重起）。启用后 enabled=true、policy=true、via_sk5=true、ip=16.146.199.68、error=None。**R6-BUG-1 真机回归通过**。
- **10 次交替**（从禁用态起，奇数步全表单启用、偶数步单字段禁用，均为真实翻转）：10 步全部 **200**（一次成功），Started 111→121（delta 恰 10，每步一次重起），PID 每步变化，终态禁用。客户端 PID 760174 全程未断（`Initialization Sequence Completed` 仅 1 次）。
- 计数口径：Started 取 journalctl 里 `Started openvpn-sk5-singbox.service` 行数（与 live-8 同口径）；`systemctl show NRestarts` 恒 0（只计自动重起，不计手动 restart），不用它计数。

## 11. headline-2 并发同名建用户（real easyrsa）—— 通过（200+409，单条 V 记录）

- 两路 `POST /api/openvpn/users {"name":"carol"}` 同时发出 → **一 200、一 409**（`user 'carol' already exists (valid cert)`）；index.txt 仅一条 carol V 记录（序列 `E60A0A1E0BF5131E87742548B58131A1`），issued/ 与 private/ 各仅一个 carol.crt/carol.key；`GET /api/openvpn/users` 列 carol 一次、状态 valid。**R8-P2-3 真机通过**。

## 12. headline-3 并发启用重起计数 —— 通过（delta 恰 1）

- 从禁用态起，两路 `POST /api/sk5 {"host","port","enabled":true}` 同时发出 → **双 200**，Started 121→122（**delta 恰 1**），终态 enabled=true、policy=true、via=true、ip=16.146.199.68；客户端 PID 760174 未断。AH 的 `_SK5_MUTATE_LOCK` 在真机并发路径上成立。**R7-BUG-3 真机终验通过**。

## 13. headline-4 `./policy-routing.sh status` 干净输出 —— 通过

- 真机跑 `./policy-routing.sh status`（/opt/openvpn-sk5-panel/egress/policy-routing.sh）：exit 0；`--- route-get: VPN user source ---` 一段为 **`1.1.1.1 from 10.8.0.1 dev tun1 table 100`**，无 RTNETLINK 报错；host 源对照段正常（`1.1.1.1 via 172.26.0.1 dev ens5`）；`ip rule`、table 100（`default via 10.9.0.1 dev tun1`）、tun1 三段均正常输出。**R7-BUG-4 真机终验通过**。

## 14. headline-5 policy-missing via_sk5 —— 通过

- 策略删掉（`ip rule del from 10.8.0.0/24 table 100`＋`ip route flush table 100`）后 25 秒查面板：`via_sk5=false`、`egress.ip=None`、error=**“SK5 已启用但策略路由未生效，出口未经过 SK5”**、`policy_routing_active=false`（enabled 仍 true）——诚实报缺策略，未谎称经 SK5。
- 全表单重开 → 200，收据 **`repaired: true`、`repair_detail: ["policy routing re-applied"]`**，Started 122→122（delta=0，**零重起补策略**）、MainPID 763931 不变；恢复后 rule 100＋table 100 均在位，`via_sk5=true`、ip=16.146.199.68。
- 链路注记：本节中途 tssh 代理断开约 2 分钟（`proxy closed during CONNECT`，三次重连失败后自行恢复），与产品无关；修复收据在断线前已拿到，断线后复核的 Started/MainPID/规则数字一致。

## 15. headline-6 verify.sh 双态 —— 通过（开态 18/0/4、关态 23/0/0）

- **开态**（SK5 开，dante）：`bash verify.sh` → **PASS=18 FAIL=0 SKIP=4，VERIFY: ALL GREEN**（与 R5/R6/R7/R8 开态 18/0/4 一致；4 个 SKIP 为开态下跳过的 toggle 格，属设计）。
- **关态**（面板关 SK5 后 25 秒再跑）：`bash verify.sh` → **PASS=23 FAIL=0 SKIP=0，VERIFY: ALL GREEN**。R5-BUG-1 的关态天花板（22/1）继续不存在。
- **AB 新格本格**：关态 `sk5-egress-ip` 格为 **[PASS]**（双断言 via_sk5=true 与 ip 非空在真机上按设计工作）；`sk5-toggle-on` 与 `egress-crosscheck` 同格 PASS。
- 客户端 PID 760174 未断。

## 16. headline-7 前端渲染级核查 —— 通过（真渲染：0 项低于 4.5，最薄 4.92；零 JS 报错）

- **真渲染方法**：机上有 `/usr/bin/chromium`，本轮复用 live-8 的纯 stdlib CDP 驱动（`/root/r9/cdp-r9.py`，仅改 jar 路径与 chrome profile 路径）：带 session cookie（`/root/r9/jar.txt`）进已登录仪表盘，1440×900 真渲染后，页内 JS 逐元素取 computed style、沿 rgba 栈合成到 body 底色、算 WCAG 对比度，并抓 console 事件与截图（`/root/r9/render/dashboard.png`、`render-contrast.json`）。
- **实测**：标题 `OpenVPN + SK5 面板`，三卡片（tcp/443、出口 IP、127.0.0.1:11080）与节点表均正常渲染，布局完整、无重叠错位；**可见文字元素 171 个，低于 4.5 者 0 个**，低于 7 者 36 个（均在 4.92–6.47 段）；最薄三档：成功绿字 #15803d **4.92**、主按钮白字/#2563eb **5.17**、危险按钮白字/#b91c1c **6.47**；console 事件 **0**（无 JS 报错/异常）。
- **自带自检**：`python3 static/contrast-check.py` 在部署上跑 **10/10 PASS**（底线 4.5），目标 7 达成 4/10——与真渲染一致。
- 与 live-8 的差 1 项：低于 7 者本轮 36、live-8 35——可见文字总数同为 171，差 1 项属渲染集的微小差异（多一个 4.92–6.8 段元素），底线 4.5 仍为 0 项，不记缺陷。
- **观察（不立案）**：截图里中文呈豆腐块——测试机 headless 环境缺 CJK 字体所致，非产品问题（DOM 文本完整、JS 采集到的中文正常）；与 live-8 同款。

## 17. headline-8 重复全新安装（第 2 次毒包、第 3 次 ufw 长规则表）—— 通过

### 安装 #2：毒包全新安装（R7-BUG-1 零 SIGPIPE 复验）—— 通过

- 清理后复核干净：4 服务 inactive、dante active、FORWARD 回 ts-forward/DOCKER-USER/DOCKER-FORWARD、仅 tailscale0 一 tun、目录与二进制已删。重解 `/root/ovpn-r9.tar.gz`（sha256 `d4489a17…`），毒包复核：panel/data/ 仅 panel.db＋agent_queue.json；admin 表 1 行、哈希 `$2b$12$tceqeKocEP0Z6…`（毒）；队列 3 条 init_pki force+confirm（1 sent n1、2 queued n1/n2）。
- `bash install.sh`（默认 UDP 1194）：一次成功，横幅出，**0 ERROR**；新日志行 `panel/ installed (panel/data/ excluded: …)` ×1、旧 `discarded shipped runtime file` ×0。
- 部署核验：admin.pass 0600；panel/data/ 仅 panel.db（毒队列未拷入）；admin 哈希 `$2b$12$2cWJ…` ≠ 毒哈希；nodes 0、audit 1；openvpn/panel/singbox 3 服务 active、agent inactive（未注册节点，属正常）；1194/udp 监听（openvpn PID 770901）；**iptables-persistent 1.0.20 已装**（无 ufw 回归格）；CA 序列 `66A1887D…`（notBefore 2026-11-12 15:23:31 UTC，全新）。登录 200，alice、bob 建用户均 200。
- **R7-BUG-1（SIGPIPE 141）真机复验通过**：安装一次成功，无版本检查 141/管道破裂。

### 安装 #3：ufw 长表全新安装（R8-BUG-2 验收＋R8-P2-4 长表终验）—— 通过

- **长表准备**：ufw 已装；先 `ufw allow 22/tcp` 再 `ufw --force enable`（默认 deny incoming、allow outgoing、deny routed；SSH 先行放行）；2000 条规则由 CLI 逐条加（20000–21999/tcp，后台循环 15:27→15:41 DONE，约 14 分钟）；装前复核：`ufw status` **264,501 字节**（>64KB）、2000 个独立端口、1194/udp 与 8443/tcp 均不在表内（安装器必须自己加）。**附注**：规则文件另有 2 条既存 tuple（`allow udp 41641`、`allow tcp 443`，安装 #2 前已在，非本轮所加；443/tcp 允许属既存残留、无害）。
- **安装**：`bash install.sh`（默认 UDP 1194）一次成功，横幅出，**0 ERROR**；日志第 33 行 **`[install] ufw: allowed 1194/udp and 8443/tcp`**（builtin 分支实际走通）；另有 `[install] ufw is installed -- skipping iptables-persistent (it conflicts with ufw…)` 与 **`ufw still installed after apt step`** 断言行各 ×2；NAT/FORWARD live-only 局限行如数在列。
- **验收核对**：ufw 仍在（`ii ufw 0.36.2-1`，`which ufw` 正常）；`ufw status` 264,765 字节（+264 = 新增 4 行）、2000 个原端口全在；`ufw status` 含 **1194/udp（v4+v6）与 8443/tcp（v4+v6）** 放行；openvpn/panel/singbox active、agent inactive；1194/udp 监听（PID 802368）；CA 序列 `2261BCCC…` 全新；admin 哈希 `$2b$12$ydqZ…` ≠ 毒；登录 200，alice、bob 建用户均 200。
- **R8-BUG-2 真机验收通过**；**R8-P2-4 长表终验通过**（2000 条原规则在安装前后字节级完整，安装器未动长表分毫）。
- **观察（不立案）**：加规则循环全程约 14 分钟（2000 条）；子进程位置显示其匀速推进（约 150 条/分钟）；但 `ufw status` 字节数在循环约 1/3 处即达最终满值 264,501——字节数与子进程进度的对应关系未解（三种独立核对——status 独立端口 2000、规则文件 tuple 2003/文件、live iptables 链独立 dport 2000——均证实长表真实完整，不影响验收）。

## 18. 新 bug 与观察项

**新 bug：0 条。** 本轮 S0–S4、headline-1～9 全部通过，R9 的 5 条与 live-8 的 2 条均已在本轮真机上关闭（R9-P1-1 队列 naive sent_at：S0-agent 命令链 202→done 全程无 500；R9-P1-2 过期证：S0-agent 建用户与 headline-2 均走真实 easyrsa 序列校验；R9-P2-1 损坏队列：毒队列 3 条 init_pki 从未拷入、从未执行；R9-P2-2 磁盘满登录：未复测——属门禁探针格，非本轮 live 项；R9-P2-3 文档钉位：AO 已修并主控核验；R8-BUG-1/R8-BUG-2：本轮 headline-9/headline-8 真机验收通过）。

**观察项（不立案）：**

1. **tssh 代理闪断一次**（§14，约 2 分钟）：`proxy closed during CONNECT`，三次重连失败后自行恢复；与产品无关，修复收据在断线前已拿到，断线后复核数字一致。
2. **ufw status 字节数与加规则循环进度不对应**（§17）：循环约 1/3 处字节数已达最终满值 264,501，而子进程位置显示匀速约 150 条/分钟；三种独立核对（status 独立端口 2000、规则文件 tuple 2003/文件、live iptables 链独立 dport 2000）均证实长表真实完整，不影响验收。
3. **agent journal 跨安装保留**（§9）：`journalctl -u ovpn-agent` 全量 grep 会命中旧轮残留（本轮 11 条均为 13:20–14:51 的 install #1 时段）；判读须加 `--since` 限定到本部署时段。
4. **节点注册默认 panel_url 取 request.host_url**（§9）：经 loopback 注册时默认为 `https://127.0.0.1:8443`，与面板证书 SAN（LAN IP＋localhost）不匹配，agent 安装须显式传 LAN IP 的 panel_url 才能通过 TLS 主机名校验与认领守卫双重关口；live-8 §4 既定口径即显式 LAN IP，本轮首版偏离该口径所致，非产品问题。R12 的 9 条（AUDIT-R12 23:47，AS/AT/AU/AV 四路修，AT/AU 已核验、AS/AV 仍在跑）已由审计立案，本轮不重复立案；本轮树（14:42 UTC 打包）早于 AP/AQ/AR/AS/AT/AU/AV 全部修复，R11-P1-1/P2-1 与 R12 的 9 条均不在本轮 live 树验收范围内。
5. **Cloudflare 真实部署（P0-1/2/3）仍未验**：与 live-8 同口径——需用户决断（已问四次未复），本轮 SK5 测试一律用 dante 替身（127.0.0.1:11080），真 IPRoyal 凭据无留存、未向用户索要。

## 19. 结论与机器终态

- **结论：全部通过，无新 bug。** S0（毒包全新安装）、S0-agent（节点＋agent＋命令链）、S1（UDP 1194 直连）、S2（SK5 落地 TCP+UDP）、S3（断网保护）、S4（TCP 443，5 次首连全 1 秒）、headline-1（首启一次 200＋10 次交替 delta 恰 10）、headline-2（并发同名建用户 200+409）、headline-3（并发启用 delta 恰 1）、headline-4（policy status 干净）、headline-5（policy-missing 诚实报＋零重起修复）、headline-6（verify.sh 开 18/0/4、关 23/0/0）、headline-7（真渲染 171 字、0 低于 4.5、最薄 4.92、零 JS 报错）、headline-8（安装 #2 毒包一次成功＋安装 #3 ufw 长表 2000 条完整、1194/8443 已加）、headline-9（毒源树默认重跑行级比对全保留）——**19 节全部填完，无一未验、无一失败**。
- **机器终态（2026-11-12 15:57 UTC）**：安装 #3 部署＋headline-9 默认重跑后状态。openvpn-server@server、openvpn-sk5-panel、openvpn-sk5-singbox、ovpn-agent、dante 五服务全部 active；OpenVPN UDP 1194 监听（服务端 PID 802368，自安装 #3 起未重启）；面板 8443 监听（PID 802504）；sing-box MainPID 802415；SK5 禁用（终态）、online_users 0（客户端已清）；节点 lightsail 已注册、agent 正常轮询（last_seen 15:56:12，get_status 202→done）；用户 alice、bob 均 valid；ufw 启用中，4010 条 ALLOW 行（2000 条原规则＋22/tcp＋41641/udp＋443/tcp 既存＋1194/udp 与 8443/tcp 各 v4+v6）；CA 序列 `2261BCCC…`；admin 哈希 `$2b$12$ydqZ…`；panel/data/ 仅 panel.db（毒队列从未入内）。
- **待主控对账**：AUDIT-R12 的 9 条修复（AS/AV 仍在跑）核验后，需 AUDIT-R13＋本轮 live-9 对账，两路都过才交付；Cloudflare 真实部署（P0-1/2/3）仍卡用户决断。

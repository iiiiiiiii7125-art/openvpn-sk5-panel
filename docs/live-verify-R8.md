# OpenVPN 接 SK5 落地 · 真机复跑验证报告（第八轮 R8）

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（AE/AG/AH/AJ 修复后的最新树——本轮第一次验证这些修复）。
> 验证人：真机复跑验证路（第八轮）。日期：2026-11-12。
> **结论先写：S0–S4 全过，headline-1～8 除 R8-P2-4 未验外全过；headline-9 默认重跑未通过——新 bug R8-BUG-1（高，阻塞：毒源树重跑销毁线上 panel.db，面板永久无法登录）；另新 bug R8-BUG-2（高：全新安装静默卸载已装 ufw、2005 条规则全毁，致 R8-P2-4 测试不可达）。R8 的 8 条修复除 R8-P2-4 未验外 live 可验项全过。**
> 前情：第七轮见 [live-verify-R7.md](live-verify-R7.md)（S0–S4 全过，BUG-9 第八次复验双模式修好，新发现 R7-BUG-1/2 高阻塞＋R7-BUG-3/4 低）；AUDIT-R8（414 行）判不能交付、差集 8 条，修复路 AE/AG/AH/AJ 已完工并主控核验；R9 与本轮并行在跑。

## 0. 树版本（本次装机所用）

| 文件 | mtime (UTC) | sha256（前 12 位） | 说明 |
|---|---|---|---|
| install.sh | 2026-11-12 12:20:28 | c324575a3906 | AE 路：版本校验先存变量再 grep、ufw 内建匹配、装树后 `_PANEL_COPIED` 门控清 panel.db＋agent_queue.json |
| panel/app.py | 2026-11-12 12:20:44 | a28bca4c8d49 | AH 路：`_SK5_MUTATE_LOCK` 覆盖五路改动 |
| core/openvpn_manager.py | 2026-11-12 12:22:18 | cccc306d034e | AH 路：PKI 目录 flock、悬空 V 记录删行 |
| egress/policy-routing.sh | 2026-11-12 12:13:01 | 103a121bbdfe | AG 路：删 occupant 死分支、do_status 源 10.8.0.1 |
| egress/README.md | 2026-11-12 12:16:15 | 63f38f69d7cc | AG 路：M4 节按内核真实语义重写 |
| egress/sk5_manager.py | 2026-11-12 12:37:13 | 02de9d8a4908 | AJ 路：`_atomic_write_json` 唯一 tmp 名，四处写盘全改走它 |
| panel/templates/index.html | 2026-11-12 09:20:59 | 30721319b07e | AA 路（未动） |
| verify.sh | 2026-11-12 09:38:04 | 1af3bfdd5c19 | AD2＋AB（未动） |
| verify-integration.sh | 2026-11-12 09:35:55 | 7e040ea3ee4a | AD（未动） |
| egress/test-egress.sh | 2026-11-12 08:40:51 | d6db69ec0a6e | X 路（未动） |
| cloudflare/src/index.js | 2026-11-12 09:24:00 | 6c81c38dc1ea | Y2（未动） |
| README.md | 2026-11-12 09:24:04 | a348e494bc35 | Z 路（未动） |

树稳定检查：12:53:03 核查时最新改动为 egress/sk5_manager.py（12:37:13），**稳定 15 分 47 秒，门过**。打包时源码树 `panel/data/` 为空（AE 已清）；毒 panel.db＋agent_queue.json 由 AE 的真实代码毒快照（`~/workspace/ae-tests/poison/`）注入打包副本，**源码树本身未被毒化**。

**打包（12:53:03 UTC）**：传包走 scp（R4/R5/R6/R7 同款）。`ovpn-r8.tar.gz`：41 条目，176,553 字节，sha256 `dcba52223cdb702bbd8e7d10f9715132af68f0c598b86af30b0c02bfec96ceb9`（机上核对后补）；install.sh sha256 `c324575a3906a1d448551696df672e008c60718d3e6c06165e093d84237c7261`。包内毒物核对：`panel/data/panel.db` 含 admin 行 1 条、`panel/data/agent_queue.json` 含 3 条 init_pki force+confirm（1 sent、2 queued，节点 n1/n2）——与 R8 §6.2 的毒形一致。

## 1. 地面真值（Lightsail 现状，测试前实测，12:40 UTC）

- 机上是**第七轮收尾态**：六服务全 active（openvpn-server@server PID 606308、openvpn-sk5-singbox PID 616685、openvpn-sk5-panel PID 597449、openvpn-sk5-policy、ovpn-agent、danted），TCP 443 部署，SK5 开（dante 替身 127.0.0.1:11080），监听 443/tcp、11080、8443。
- 第七轮残留全部在位，**重装前必须清除**：
  - netns `vpntest` 仍在；
  - `/root/r7/` 测试产物在位（panel.py、netns-setup.sh、probe.sh、toggle10.sh、storm2.sh、conc-enable.sh、install/install2/install3/install-default.log、verify-on/off.log、token.txt 0600、alice*.ovpn、client-udp/tcp.log）；
  - alice 客户端 PID 606388 仍在跑（第七轮 TCP 客户端）；
  - `/root/ovpn-r7.tar.gz`（毒包，171,323 字节，证据，**勿删**）与 `/root/ovpn-r7b.tar.gz`（干净包，169,186 字节）在位；
  - `/opt/openvpn-sk5-panel/` 为第七轮装树；`/etc/openvpn-sk5-panel/` 含 admin.pass（0600）。
- FLMX 相关进程同机在跑（paneld、flzx-panel、flmx-int2 paneld），**一律不碰**；`/root/flmx-panel` 不动。

## 2. 清场（全新重装前，12:53 UTC）

- 客户端 PID 606388（第七轮 TCP 客户端）按精确 PID 杀掉，已确认无此进程；四服务已停（openvpn/singbox/panel/agent 全部 inactive，dante 保留，active）。
- 绕行已清：FORWARD 链清至只剩 ts-forward/DOCKER-USER/DOCKER-FORWARD（策略 DROP）。注意：本轮安装器规则实形带 `-s/-d 10.8.0.0/24` 前缀（`iptables -S` 实测），清场脚本初版按无前缀形状删、漏了三条（两条 tun0＋一条 tun1→tun0），已按实测形状补删、复核链干净；另删 veth-host 两条测试规则；netns `vpntest` 已删。
- 状态已 wipe：`/root/openvpn-sk5-panel`、`/opt/openvpn-sk5-panel`、`/opt/ovpn-agent`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/ovpn-agent` 全删；sing-box 与 tun2socks 二进制已删（逼安装器走下载路径，复验版本校验）；`/root/r7/`、`/root/ovpn-r7.tar.gz`（毒包证据）、`/root/ovpn-r7b.tar.gz` 保留未动。
- 清场后核对：只剩 tailscale0 一个 tun 设备、无 1194/443/8443 监听、`/opt/openvpn-sk5-panel` 与 `/etc/openvpn-sk5-panel` 不存在。
- S0 安装已于 12:54 UTC 后台启动（`nohup bash install.sh`，PID 653481，日志 `/root/r8/install.log`）。

## 3. S0 基线：毒包安装 + 建服务 + 建用户 —— 通过（一次成功；R7-BUG-2＋第二毒物终验通过）

### 3.0 第一次安装（毒包，全新安装，UDP 1194 默认）—— 通过

- install.log：**0 个 ERROR**；sing-box 1.11.15 下载 `sha256 OK`、自报 `sing-box version 1.11.15`；tun2socks 2.7.0 下载 `sha256 OK`、自报 `tun2socks-2.7.0`——两次版本校验均一次通过（R7-BUG-1 本格未再撞 SIGPIPE，见 §17）。
- **毒物丢弃实证**：日志有两条 `[install] discarded shipped runtime file panel/data/panel.db (runtime state must never ship)` 与 `panel/data/agent_queue.json` 同款；**完成横幅已印**；初始密码已生成并写入 `/etc/openvpn-sk5-panel/admin.pass`（0600，mtime 12:54）。
- 装后核对：`/opt/openvpn-sk5-panel/panel/data/panel.db` 的 admin 行哈希为 `$2b$12$zX.30aDzeNAumaPkO99pZ.S…`，与毒哈希 `$2b$12$tceqeKocEP0Z6KowAfCcrue…` 不同——全新 admin 行，毒行已被丢弃；nodes 0、audit 1 行（全新库）；**agent_queue.json 文件不存在**（毒队列已删、面板尚未建新队列），init_pki 命令 0 条。
- 五单元：openvpn/singbox/panel/policy 全 active，agent inactive（属预期，由 S0-agent 安装），restarts 全 0；CA 序列 `50455F26A2C3EE73AB167EF60C95B7383F606C45`（notBefore 2026-11-12 12:54，记下供 agent 轮询后对比）。

### 3.1 S0 后半段：建服务确认＋建用户 —— 通过

- 面板登录 200；`/api/status` 200：openvpn running（UDP 1194，PID 654195），online_users 0，SK5 未启用，`singbox_running: true`，sk5 块 `policy_routing_active: false`。
- 默认 `.ovpn` remote 为 **16.146.199.68 1194**（IPv4 公网，R3-BUG-5 修好）；`GET /api/openvpn/public-ip` 返回 `16.146.199.68`。
- 用户：alice、bob 创建均 200；`GET /api/openvpn/users` 只列 alice、bob，alice 序列号 `AA0832F618F8D3AF34A557EEB6E80FC0`、bob `4B8F5854987CD6FD660C4FEAE15FA094`；`.ovpn` 下载 200，`proto udp / remote 16.146.199.68 1194 / cipher AES-256-GCM / auth SHA256`，`<cert>` 块 subject `CN = alice`、issuer `CN = OpenVPN-CA`、CA 序列与安装时一致（`50455F26…`）。

## 4. S0-agent：节点注册 + agent 安装 + 命令链 —— 通过（第二毒物 agent 侧终验通过）

- 注册：`POST /api/nodes {"name":"lightsail","panel_url":"https://172.26.15.152:8443"}` → 201，token 只存 `/root/r8/node-reg.json`（未写报告）。
- 安装命令（面板两步走命令逐字执行，token 由文件读入）：`curl -ksSL …/install-agent.sh`＋sha256 校验＋`bash /tmp/install-agent.sh --panel-url … --token … --node-name 'lightsail'` → **EXIT=0**。中途一次失败是测试侧脚本 bug：node-reg.json 存的是 `201 {json}`（panel.py 打印的状态码前缀），token 解析抛 JSONDecodeError——已修解析（取首个 `{` 后 JSON），重跑 EXIT=0，非产品问题。TOFU 钉证书、bundle sha256 OK、`/etc/ovpn-agent/config.json` 0600、`ovpn-agent is ACTIVE (node=lightsail)`。
- poll：`GET /api/nodes` 的 `last_seen` 为 2026-11-12T12:59:50+00:00（新鲜）；agent 日志 5 分钟内无 401/403、无 poll failed、无 init_pki。
- **毒 init_pki 未执行**：agent 上线并轮询后，CA 序列仍为 `50455F26A2C3EE73AB167EF60C95B7383F606C45`（与安装时一致）；面板 `agent_queue.json` 现为 `{"queue": {"lightsail": []}, "cmds": {}, "ovpn": {}}`——空队列，init_pki 0 条。
- 命令链：`POST /api/cmd {"node":"lightsail","action":"get_status"}` → **202**（cmd_id 96ea421d…）；约 3 秒后 `GET /api/cmd/<id>` → **done**，error null；result 含 openvpn running=true pid 654195（与面板一致）、sk5 enabled=false、users=[alice、bob]（序列号与 §3.1 一致）。

## 5. S1 直连态（UDP 1194）—— 通过（首次即通，零手工 FORWARD）

- 客户端（alice，netns vpntest，`--float`）：先用默认 remote 公网 IP 16.146.199.68 连——22 秒未完成（无 `Initialization Sequence Completed`、无 tun0），属 R7 已记的机内 netns 发往公网 IP 发夹限制，非产品问题；按精确 PID 杀掉后改 remote 为 LAN IP 172.26.15.152（R7 同款），**首次即通**，`Initialization Sequence Completed`（13:00:55），tun0 10.8.0.2/24，redirect-gateway 路由就位。PID 656949。
- 数据面（direct）：`curl ifconfig.me`（HTTP 与 HTTPS，--resolve 绕 MagicDNS）→ **16.146.199.68**；`dig @1.1.1.1 ifconfig.me` → 34.160.111.145 有回包；NTP UDP：216.239.35.4 回 **48 字节** 12.8ms、162.159.200.1 回 **48 字节** 7.1ms。UDP 数据面通过。
- **BUG-9 第九次复验——修好（UDP 模式）**：部署态原始日志（逗号 v2，13 段）为 `CLIENT_LIST,alice,10.200.0.2:48945,10.8.0.2,,6695,11056,2026-11-12 13:00:55,1794488455,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users` = **1**；`clients`=[{name: alice, real_address: 10.200.0.2:48945, virtual_address: 10.8.0.2, bytes_received: "6695", bytes_sent: "11056", connected_since: "2026-11-12 13:00:55"}]——逐字段一致；`/api/openvpn/users` 的 alice `online: true`、bob `online: false`（本节实测）。

## 6. S2 落地态（SK5 开）—— 通过（TCP+UDP 均走 SK5，双日志为证）

- 开启（全新安装后第一次启用）：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功，见 §10）；enabled=true，`policy_routing_active: true`，egress_ip 16.146.199.68；sing-box 重起一次（PID 654261→657522，Started 134→135，属首次渲染 SK5 配置的预期重起）；`ip rule` 有 `from 10.8.0.0/24 lookup 100`；table 100 为 `default via 10.9.0.1 dev tun1`；`ip route get 1.1.1.1 from 10.8.0.1` → `dev tun1 table 100`；tun1 UP。alice 的隧道在开启前后未断（同一客户端 PID 656949 持续）。
- 开启前基线：rule 100 已在位、table 100 为空（与 R6/R7 同款安装器残留态）——本次首次启用一次 200，AC 的幂等 add（规则在位即跳过）按设计工作（见 §10）。
- 面板 `POST /api/sk5/test` → **tcp_ok: true、udp_ok: true**（native 模式，TCP 延迟 110.8ms）。
- 客户端 TCP（经 SK5）：`curl --resolve ifconfig.me:80:34.160.111.145 http://ifconfig.me` 与 HTTPS 同式均回 **16.146.199.68**；sing-box 日志同秒有 `outbound/socks[bought-sk5] … to 34.160.111.145:80` 与 `:443`；dante 日志同窗口 16 条 `tcp/connect`/`udpassociate`——TCP 确实走了 dante（SK5 替身）。出口 IP 不变属预期：替身与面板同机，S1/S2 出口恒为 16.146.199.68，链路证明以路由表 + 双日志为准（R1 已定口径）。
- 客户端 UDP（经 SK5）：NTP 到 216.239.35.4 回 **48 字节** 19.5ms、162.159.200.1 回 **48 字节** 12.8ms；sing-box 日志有 `outbound/socks[bought-sk5] … outbound packet connection to 216.239.35.4:123` 与 `162.159.200.1:123`。UDP 走 SK5 为证。

## 7. S3 断网保护（杀 dante）—— 通过（流量全断、无直连回落、自动恢复、隧道不断）

- 杀 dante（`systemctl stop danted`，inactive）：客户端 TCP `curl --resolve … http://ifconfig.me` → **exit 56**（Recv failure），HTTPS → exit 35（SSL connect error，同样失败）；NTP UDP 到 216.239.35.4 → **TimeoutError**，162.159.200.1 同样 TimeoutError；**无直连回落**（curl 不是成功、是失败——fail-closed 成立）。隧道未断（同一客户端 PID 656949，tun0 仍在，`Initialization Sequence Completed` 仅 1 次）。
- 面板 `/api/status`：kill 期间 **egress.ip = null**（`{'error': None, 'ip': None, 'latency_ms': None, 'via_sk5': True}`），诚实报空；sk5 enabled=true、policy=true。
- 恢复（`systemctl start danted`，active）：客户端 TCP 立即回 **16.146.199.68**，NTP 回 **48 字节** 15.1ms/9.4ms。隧道全程未断：同一 PID 656949，client.log 里 `Initialization Sequence Completed` 仅出现 1 次、SIGUSR1 0 行——无重连、无重拨。

## 8. S4 TCP 备模式（443）—— 通过（BUG-14 修好，S1/S2 各重跑一次）

- **BUG-14 修好**：`POST /api/openvpn/server {"proto":"tcp","port":443,"allow_port_change":true}` → **HTTP 200**。`POST /api/openvpn/restart` → 200（新 pid 662165）。TCP 443 监听，UDP 1194 监听消失，`/api/status` 为 proto=tcp port=443 running=true；新下载的 alice.ovpn 为 `proto tcp / remote 16.146.199.68 443`（默认 remote 仍是 IPv4 公网）。SK5 保持开启态。
- **TCP 首连 120s 超时跟进（headline-8）——未复现**：5 次全新 TCP 首连全部 **1 秒内** `TCP connection established`＋`Initialization Sequence Completed`（13:12:32/38/44/50/56，各 1s）。R7 的 120s 超时单次事件本轮未再出现——支持 R7 的“测试侧 veth 路径上一次 SYN 丢失”假说，产品侧无动作。
- S2-TCP（SK5 开）：新 TCP 客户端连上（13:15:13，tun0 10.8.0.2/24，PID 663209）；curl → 16.146.199.68；NTP → 48 字节 18.6ms/10.9ms；dante 日志同窗口有 `tcp/connect`/`udpassociate`——TCP+SK5 链路在 TCP 模式下同样成立。旧 UDP 客户端 PID 656949 按精确 PID 杀掉（服务端已切 TCP，其重连无意义）。
- BUG-9（TCP 模式）：原始日志 `CLIENT_LIST,alice,10.200.0.2:48288,10.8.0.2,,3624,3657,2026-11-12 13:15:13,1794489313,UNDEF,5,0,AES-256-GCM`；面板 `/api/status` 的 `online_users`=**1**，`openvpn.detail.clients`=[{name: alice, real_address: 10.200.0.2:48288, virtual_address: 10.8.0.2, bytes_received: "3624", bytes_sent: "3657", connected_since: "2026-11-12 13:15:13"}]——逐字段一致。**BUG-9 第九次复验在 UDP 与 TCP 两种模式下均修好**。
- S1-TCP（SK5 关）：单字段 `{"enabled":false}` → 200（`policy_removed: true`、disable 后 sing-box 仍在 direct 模式跑，R3-BUG-1 修好）；rule 100 消失、table 100 空、路由回 ens5；TCP 客户端 curl → 16.146.199.68，NTP → 48 字节 15.5ms/7.2ms，dig @1.1.1.1 → 34.160.111.145；同一客户端 PID 663209 全程未断（`Initialization Sequence Completed` 仅 1 次）。

## 9. BUG-15/16 默认重跑 —— **未通过（新 bug R8-BUG-1，高，阻塞；见 §18）**

- `bash install.sh`（无 OVPN_PROTO/OVPN_PORT，从 `/root/openvpn-sk5-panel` 即毒包解压树重跑）：继承行正确——`inheriting deployed entry port from /etc/openvpn/server/server.conf (proto=tcp port=443; explicit OVPN_PROTO/OVPN_PORT still wins)`；server.conf 仍为 `port 443 / proto tcp`；七服务（openvpn/singbox/panel/policy/healthcheck.timer/agent/dante）全 active；客户端 PID 663209 全程未断（`Initialization Sequence Completed` 仅 1 次）；`/api/status` proto=tcp port=443 running=true online=1——**隧道与部署本身未受损**。
- 但安装器在登录门处 **`die`**：`[install] ERROR: panel login check failed (HTTP 401) -- password file and panel DB disagree`（install-default.log:46），**完成横幅未印（0 次）**——本次默认重跑未完成。
- **事后态（已定位到行，见 §18 R8-BUG-1）**：面板进程 PID 654325 自 12:54 起未重启；`/opt/openvpn-sk5-panel/panel/data/panel.db` 是重跑中新生成的文件（mtime 13:23），admin 行 **0 条**、nodes **0 条**、audit 仅 8 条（重跑后新写）；admin.pass 仍是 12:54 的旧文件。后果：**面板永久无法登录**——`POST /api/login` 401（“密码错误”，我亲手复核）；节点记录丢失（`GET /api/nodes` 为空）；agent 自 13:20:39 起每 60 秒 poll 401（`panel HTTP 401 on /api/agent/poll`，backoff 已顶满，至今未恢复）；修复须重启面板重建 admin（新密码进 admin.pass，节点/审计历史丢失——该恢复路径未跑，机器保持现状供修复路取证）。
- 与 R7 的差别：R7 默认重跑通过，因其源树是干净包 r7b（panel/data 已排除）；本轮重跑源树是毒包解压树（panel/data 在位）——触发条件正是 AE 守卫的误伤面。

## 10. headline-1 R6-BUG-1 首启一次 200 回归 —— 通过（首启一次 200；10 次交替全一次 200）

- **首启（全新安装后第一次启用，复刻 live-6/live-7 §10 精确序列）**：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功）。此前基线：rule 100 已在位、table 100 为空（与 R6/R7 同款安装器残留态）；sing-box MainPID 654261、Started=134。启用后 enabled=true、policy=true、via_sk5=true、ip=16.146.199.68、error=None；sing-box 重起一次（PID 654261→657522，Started 134→135，属首次渲染 SK5 配置的预期重起）。**R6-BUG-1 真机回归通过**。
- **10 次交替**（从启用态起，奇数步单字段禁用、偶数步全表单启用，均为真实翻转）：10 步全部 **200**（一次成功），Started 135→145（delta 恰 10，每步一次重起），PID 每步变化，终态启用。客户端 PID 656949 全程未断（`Initialization Sequence Completed` 仅 1 次）。

## 11. headline-2 并发同名建用户（real easyrsa）—— R8-P2-3 裁决：通过（200+409，单条 V 记录）

- 两路 `POST /api/openvpn/users {"name":"carol"}` 同时发出 → **一 200、一 409**（`user 'carol' already exists (valid cert)`）；index.txt 仅一条 carol V 记录（序列 `7A3CD004733E8CD76A5D8E0A6EAC8720`），issued/ 与 private/ 各仅一个 carol.crt/carol.key；`GET /api/openvpn/users` 列 carol 一次、状态 valid。**R8-P2-3 真机通过**。
- **real easyrsa 语义裁决（R8 的 fake-easyrsa caveat 在此结案）**：把 live PKI 拷到 /tmp，在副本上用真实 easyrsa 3.1.0 再跑一次 `build-client-full carol nopass`——**拒绝**：`Request file already exists. Aborting build to avoid overwriting this file.`（在已有的 req 文件处中止，未到签发）；副本 index.txt 仍仅 1 条 carol V 记录；live PKI 未动（仍 1 条）、CA 序列不变。即：real easyrsa 遇预存 key 是拒绝、不是覆盖——R8 担心的“无锁时双 V 幽灵序列”在真机上本就不可达（无锁最坏是第二路 500，不是幽灵序列）；AH 的锁把结局收成干净的 200+409。

## 12. headline-3 并发启用重起计数 —— R7-BUG-3 终验：通过（delta 恰 1）

- 从禁用态起，两路 `POST /api/sk5 {"host","port","enabled":true}` 同时发出 → **双 200**，Started 146→147（**delta 恰 1**），终态 enabled=true、policy=true、via=true、ip=16.146.199.68；客户端 PID 656949 未断。AH 的 `_SK5_MUTATE_LOCK` 在真机并发路径上成立。**R7-BUG-3 真机终验通过**（R7 轮次 delta 2，本轮 delta 1）。

## 13. headline-4 `./policy-routing.sh status` 干净输出 —— R7-BUG-4 终验：通过

- 真机跑 `./policy-routing.sh status`（/opt/openvpn-sk5-panel/egress/policy-routing.sh）：exit 0；`--- route-get: VPN user source ---` 一段为 **`1.1.1.1 from 10.8.0.1 dev tun1 table 100`**，无 RTNETLINK 报错；host 源对照段正常（`1.1.1.1 via 172.26.0.1 dev ens5`）；`ip rule`、table 100（`default via 10.9.0.1 dev tun1`）、tun1 三段均正常输出。**R7-BUG-4 真机终验通过**。

## 14. headline-5 policy-missing via_sk5 —— 通过（live-7 未重跑格，本轮显式重跑）

- 策略删掉（`ip rule del from 10.8.0.0/24 table 100`＋`ip route flush table 100`）后 25 秒查面板：`via_sk5=false`、`egress.ip=None`、error=**“SK5 已启用但策略路由未生效，出口未经过 SK5”**、`policy_routing_active=false`（enabled 仍 true）——诚实报缺策略，未谎称经 SK5。
- 全表单重开 → 200，收据 **`repaired: true`、`repair_detail: ["policy routing re-applied"]`**，Started delta=0（**零重起补策略**）、MainPID 不变；恢复后 rule 100＋table 100 均在位，`via_sk5=true`、ip=16.146.199.68。为抓完整收据该循环做了两次，两次数字一致。

## 15. headline-6 verify.sh 双态 —— 通过（开态 18/0/4、关态 23/0/0）

- **开态**（SK5 开，dante，13:17 UTC）：`bash verify.sh` → **PASS=18 FAIL=0 SKIP=4，VERIFY: ALL GREEN**（与 R5/R6/R7 开态 18/0/4 一致；4 个 SKIP 为开态下跳过的 toggle 格，属设计）。
- **关态**（面板关 SK5 后 25 秒再跑，13:18 UTC）：`bash verify.sh` → **PASS=23 FAIL=0 SKIP=0，VERIFY: ALL GREEN**。R5-BUG-1 的关态天花板（22/1）继续不存在。
- **AB 新格本格**：关态 `sk5-egress-ip` 格为 **[PASS]**（双断言 via_sk5=true 与 ip 非空在真机上按设计工作）；`sk5-toggle-on` 与 `egress-crosscheck` 同格 PASS。
- 关态跑完即刻查面板显示 enabled=true——是 10 秒状态缓存的旧快照（R7-P2-12 同款）或 cleanup 尚在途中；10 秒后再查终态 enabled=false、policy=false、via=false——verify.sh 自身把链重开又清回关态（sk5-enable-endpoint 格末尾 cleanup disable），终态正确；客户端 PID 663209 未断。

## 16. headline-7 前端渲染级核查（首轮）—— 通过（真渲染：0 项低于 4.5，最薄 4.92；零 JS 报错）

- **真渲染方法**：机上有 `/usr/bin/chromium`，本轮用纯 stdlib CDP 驱动（无 node，故手写 WebSocket 客户端，`/root/r8/cdp.py`）：带 session cookie（`/root/r8/jar.txt`）进已登录仪表盘，1440×900 真渲染后，页内 JS 逐元素取 computed style、沿 rgba 栈合成到 body 底色、算 WCAG 对比度，并抓 console 事件与截图（`/root/r8/render/dashboard.png`、`render-contrast.json`）。
- **实测**：标题 `OpenVPN + SK5 面板`，顶栏“玻璃适中 · 对比度 ≥ 4.5”，三卡片（tcp/443、出口 IP、127.0.0.1:11080）与节点表均正常渲染，布局完整、无重叠错位；**可见文字元素 171 个，低于 4.5 者 0 个**，低于 7 者 35 个（均在 4.92–6.8 段）；最薄三档：成功绿字 #15803d **4.92**、主按钮白字/#2563eb **5.17**、危险按钮白字/#b91c1c **6.47**；console 事件 **0**（无 JS 报错/异常）。
- **自带自检**：`python3 static/contrast-check.py` 在部署上跑 **10/10 PASS**（底线 4.5），目标 7 达成 4/10——与真渲染一致。
- **扩展对子（自检 10 对之外）**：warn 徽标 #92400e/#fef3c7 6.37、idle #374151/#e5e7eb 8.33、info #1e40af/#dbeafe 7.15、禁用输入 #4b5563/#f3f4f6 6.87、导航 #4b5563/侧栏 7.42、最差渐变点（蓝 10% 渐变中心叠玻璃）正文 13.93——**全过**。`--ink-3 #6b7280` 仅定义、页内无实际使用（最薄 4.59 的格不存在于渲染中）。
- **托盘兜底**：全部文字都在玻璃容器内（侧栏/顶栏白 70%、卡片白 72%＋blur），底色为 #f6f7fb＋三道 ≤10% 透明度的径向渐变（非图片壁纸）；即使 backdrop-filter 不生效，白 70–72% 叠近白底仍得近白有效底色，文字不直接落在渐变上。
- **观察（不立案）**：① 禁用态主按钮 `opacity: .55`，白字有效对比度 2.63——禁用控件属 WCAG 豁免项，且是刻意的“灰掉”示能，不记缺陷；② 截图里中文呈豆腐块——测试机 headless 环境缺 CJK 字体所致，非产品问题（DOM 文本完整、JS 采集到的中文正常）；③ placeholder 无显式颜色（浏览器默认灰），非必填文本，不计。

## 17. headline-8 重复全新安装（第 2 次毒包、第 3 次 ufw 长规则表）—— R7-BUG-1 / R8-P2-4 终验

- **安装 #2（毒包，全新，UDP 1194 默认）**：先清 #1 后的部署（TCP 客户端 663209 按精确 PID 杀；服务停；`/root/openvpn-sk5-panel /opt/openvpn-sk5-panel /opt/ovpn-agent /etc/openvpn-sk5-panel /etc/openvpn/server /etc/ovpn-agent` 删；sing-box/tun2socks 二进制删以强制下载路径）；从 tarball 重新解压（sha256 仍 `dcba5222…`，毒文件在位，install.sh sha256 仍 `c324575a…`）。结果：**PASS**——0 ERROR、横幅出、两条 `discarded shipped runtime file`、版本校验一次过（sing-box 1.11.15、tun2socks 2.7.0）、admin.pass 新生成（13:28，0600）、新 admin 哈希 `$2b$12$MlpjMDo8xgXx6BVNyDwKrOa`（与 #1、`$2b$12$tceq…` 毒哈希均不同）、nodes 0、三服务 active。**R7-BUG-1 终验：三次全新安装（#1、#2、#3）版本校验全部一次过、零 SIGPIPE 死亡**（另 §9 默认重跑亦经过版本校验段，无 141）。
- **安装 #3（ufw 长规则表，全新）**：ufw 0.36.2（Debian 12，apt 装）。先 `ufw allow 22/tcp 41641/udp 8443/tcp 1194/udp 443/tcp` 再 `--force enable`（SSH 全程未断）；旧看门狗（900 秒后 `ufw --force disable`）在批量加规则前已杀——防止它在中途关防火墙使安装器测到 inactive。**造表教训**：直接编辑 `/etc/ufw/user.rules` 插 2000 条再 `ufw reload` 不行——iptables 链确实多了 2006 条规则，但 reload 后文件被重写回 6 行，`ufw status` 仍只出 765 字节／15 行（`ufw status` 读的是 ufw 自己的规则库，不是 iptables）；要造真长表只能走 CLI 逐条加。CLI 批量循环（20000–21999/tcp，2000 条，约 15 分钟，每次加规则重写全表、越往后越慢）完成：`ufw status` 264,765 字节／4,015 行（每条端口占 v4+v6 两行），远超 64KB 管道缓冲。安装前特意删掉 1194/udp 与 8443/tcp 两条放行（`ufw status` 计数归 0），使安装器必须自己补加、测试才作数；看门狗重挂 15 分钟。
- **安装 #3 结果：安装本身 PASS，但 ufw 测试未能执行——新 bug R8-BUG-2（高，见 §18）**：0 ERROR、横幅出、两条 `discarded shipped`、admin.pass 新生成（13:51）、三服务 active；但安装器 apt 步骤（install.sh:217-218）装 `iptables-persistent`，Debian 下该包与 ufw 冲突——apt 在 install3.log:8 把 ufw 0.36.2-1 **卸载**了（`Removing ufw (0.36.2-1) ...`），2005 条规则随之销毁；随后 ufw 块（install.sh:725-731）因 `command -v ufw` 失败而静默跳过，日志无 `ufw: allowed` 行，装后 `ufw status` → `command not found`。**R8-P2-4 的长表 live 测试因此未能执行**（前提“安装到 ufw 块时 ufw 仍在”不可达），记为**未验**，非通过、非失败。

## 18. 新 bug 与观察项

### R8-BUG-1（高，阻塞）默认重跑从含 panel/data 的源树运行会销毁线上 panel.db，面板永久无法登录

- 现象：§9 默认重跑死在登录门（HTTP 401、无完成横幅）；事后面板 `POST /api/login` 恒 401，`GET /api/nodes` 为空，agent 每 60 秒 poll 401；panel.db 为重跑中新生成的空库（admin 0 行、nodes 0 行）。
- 机制（日志＋DB 转储＋进程状态三证）：
  1. 重跑源树 `/root/openvpn-sk5-panel` 是毒包解压树，`panel/data/panel.db` 与 `agent_queue.json` 在位；install.sh 装树 `cp -a panel/` 把毒 panel.db **覆盖**了线上活库（/opt 下的 panel.db 被毒库替换）；
  2. 随后 AE 的 `_PANEL_COPIED` 门控（install.sh:422-430）因“源树有该文件”而把 /opt 下的 panel.db 与 agent_queue.json **删掉**——门控只分得清“源树有没有文件”，分不清“/opt 下的是随包带入的还是线上活数据”；拷贝已先把活库覆盖，删除等于销毁活库；
  3. 面板进程（PID 654325，自 12:54 未重启）下一次按路径开库时建出全新空库（表结构在、admin 0 行）；`_ensure_admin_password()` 只在启动时跑，不补 admin 行——此后每次登录查无 admin 即 401；节点/审计/队列随旧库一起丢失；agent 因节点记录消失而 poll 401。
  4. 佐证：install-default.log 两条 `discarded shipped runtime file`；panel.db mtime 13:23、admin 0 行；admin.pass 仍是 12:54 旧文件（面板未重建密码）；journal 仅 1 条 Started（面板从未重启）；agent 首个 401 在 13:20:39（重跑中拷贝＋删除发生的时刻）。
- 定性：AE 守卫对**全新安装**正确（§3.0 已证毒物丢弃、新 admin 生成），对**重装/原地升级**是误伤——重装时源树带运行态文件即触发活库销毁。触发须源树含 panel/data 文件：干净交付树（AE 已清空源码树 panel/data）不触发；但 R7-BUG-2 已警示“下轮打包若忘排除即重蹈”，且用户可能从任意含 panel/data 的目录重跑 install.sh——升级路径上的活库无保护是产品缺口，不是测试失误。修法方向（供修复路）：装树时**根本不拷贝 panel/data/**（与 docs/、`__pycache__` 同类排除；面板 import 时自建 DATA_DIR，AE 已核实），门控随之不再需要；或重装前备份线上 panel.db、拷贝后若源树带文件则恢复备份。二选一，验收：从毒包解压树默认重跑须出横幅、登录成功、节点/审计/用户全在、agent poll 正常。
- 附带：R7 轮次 BUG-15/16 的“原地升级路径打通”结论在本轮毒源树条件下不成立——升级路径的活库保护缺失，须以修复后重跑为准。

### R8-BUG-2（高）全新安装静默卸载用户已装的 ufw，防火墙规则全毁；R8-P2-4 的长表 live 测试因此不可达

- 现象：安装 #3 前 ufw 0.36.2 启用、2005 条规则、`ufw status` 264,765 字节；安装后 ufw 已卸载（dpkg 状态 `rc`）、`ufw status` → `command not found`、内核 ufw 规则 0 条、日志无 `ufw: allowed` 行；安装本身 0 ERROR、横幅出、admin.pass 新生成。
- 机制（日志＋源码＋dpkg 三证）：install.sh:217-218 硬依赖 `apt-get install -y -qq --no-install-recommends openvpn easy-rsa iptables-persistent curl jq python3 python3-pip …`；Debian 下 iptables-persistent 与 ufw 冲突，apt 在 install3.log:8（apt 步骤首条）即 `Removing ufw (0.36.2-1) ...`，随后装 netfilter-persistent/iptables-persistent；ufw 块（install.sh:725-731）以 `command -v ufw` 为门，ufw 已无，静默跳过。安装器自己的 1194/8443 放行也因此从未执行——只是此刻无防火墙，端口天然开放。
- 定性：全新安装在用户机器上**无声拆掉已有防火墙并销毁其全部规则**（本轮 2005 条），日志里除 apt 输出的一行外无任何警告；是产品缺陷，不是测试失误。附带后果：AE 的 R8-P2-4 修复（builtin 匹配，install.sh:726-728）在实践中是死代码——只要机器装了 ufw，依赖步骤必先卸掉它，ufw 块永远到不了长表判断。修法方向（供修复路）：iptables-persistent 不应无条件硬装——检测到 ufw 时跳过该包并走 ufw 放行（或警告＋中止，由用户定夺）；验收：ufw 启用＋长表下全新安装，装后 ufw 仍在、原规则全在、`ufw status` 含 1194/8443 放行、R8-P2-4 的 builtin 分支实际走通。**R8-P2-4 live 测试本轮记未验**（前提不可达），待 R8-BUG-2 修复后重跑。
- 注：本轮前 ufw 未装（§2），故 R1–R7 从未触及此冲突；机器现态与轮前一致（无防火墙，INPUT ACCEPT＋ts-input），无需恢复动作。/etc/ufw 配置文件残留（dpkg `rc` 态）与 `*.20261112_133428` 备份是 ufw 自身文件，轮后未动。

### 观察项（不立案）

- **R3-OBS-1 未复发**：本轮面板 journal 里 401 除本次 R8-BUG-1 的登录/agent poll 401 外无其他；R8-BUG-1 的 401 是产品故障所致，不计入 OBS。
- **verify.sh 的 verify-* 用户残留**：关态/开态跑完后 panel 留 `verify-1794489382`（valid）与 `verify-1794489417`（revoked）两个测试用户——门禁自带行为，历轮皆有，不立案。
- **TCP 客户端首次 connect 120 秒超时**：§8 已记——本轮 5 次首连全部 1 秒成功，R7 单次事件未复现，产品侧无动作。
- **沙箱门禁未在本轮跑**：verify-integration.sh 是沙箱门禁，机上按设计 SKIP；主控已在沙箱重跑 28/28（AE/AG/AH/AJ 核验），本轮不重复。
- **R9 已完工（并行，2026-11-12 21:12，409 行）**：判不能交付、差集 5 条（P1 2、P2 3），R8 的 8 条全关；修复路 AK/AL/AM 已完工并主控核验；本轮 live-8 的新 bug（R8-BUG-1）供 R10 对账（主控侧信息，非本轮审计结论）。

## 19. 结论与机器终态

###  verdicts

| 格 | 结论 |
|---|---|
| S0 毒包安装＋建服务＋建用户 | 通过（一次成功；R7-BUG-2＋第二毒物终验） |
| S0-agent 节点＋agent＋命令链 | 通过（第二毒物 agent 侧终验） |
| S1 直连态 UDP 1194 | 通过 |
| S2 落地态 SK5 开 | 通过（TCP+UDP 均走 SK5） |
| S3 断网保护 | 通过 |
| S4 TCP 443 备模式 | 通过（5 次 TCP 首连全 1 秒，R7 单次 120s 超时未复现） |
| headline-1 首启一次 200＋10 次交替 | 通过 |
| headline-2 并发同名建用户（real easyrsa） | 通过（200+409，单条 V；real easyrsa 拒写已存 req） |
| headline-3 并发启用重起 delta 恰 1 | 通过 |
| headline-4 policy-routing.sh status | 通过 |
| headline-5 policy-missing via_sk5 | 通过（live-7 未重跑格，本轮显式重跑） |
| headline-6 verify.sh 双态 | 通过（开态 18/0/4、关态 23/0/0） |
| headline-7 前端渲染级核查 | 通过（0 项低于 4.5，最薄 4.92；零 JS 报错） |
| headline-8 重复全新安装 | **部分通过**：#2 毒包全新安装通过；#3 安装本身通过、R7-BUG-1 零 SIGPIPE（三装全一次过）；但 R8-P2-4 长表测试**未验**——安装器先卸了 ufw（R8-BUG-2） |
| headline-9 默认重跑（BUG-15/16 回归） | **未通过——新 bug R8-BUG-1（高，阻塞）**：死于登录门、无横幅、面板永久无法登录、节点记录丢失 |

**本轮新 bug 2 条**：R8-BUG-1（高，阻塞；默认重跑从含 panel/data 的源树运行销毁线上 panel.db）与 R8-BUG-2（高；全新安装静默卸载已装 ufw、规则全毁，致 R8-P2-4 测试不可达）。R8 的 8 条修复终验：R7-BUG-1（零 SIGPIPE 三装）、R7-BUG-2（毒包两件全丢弃）、R7-BUG-3（delta 恰 1）、R7-BUG-4（status 源段干净）、R8-P2-1/2（门禁＋文档，沙箱侧）、R8-P2-3（200+409 单 V）——除 R8-P2-4 未验外，其余 live 可验项全部通过。

### 机器终态（2026-11-12 14:03 UTC）

- 部署：安装 #3 全新部署，TCP 443（server PID 738888，`port 443 / proto tcp`），admin.pass 生成于 13:51（0600）；面板可登录；online=1（alice，10.8.0.2，TCP 客户端 PID 738950 在 netns vpntest，流量 6812/12145 字节，直连数据面 HTTP/HTTPS/DNS/NTP 全通）。
- SK5：**关**（enabled=false，policy=false，via_sk5=false）。原因：三次全新安装清空了面板 DB，IPRoyal 凭据只存在旧库里，机上与工作区均无留存（已全盘 grep，含 bash_history 与 /root/r7，无凭据）；本轮 S2/S4 已证 SK5 链本身可用，终态缺的是凭据重填——主控侧决定是否重填（**不在本轮补：凭据不入记忆、不在聊天里要**）。
- 服务：openvpn-server@server / sing-box / panel / policy / healthcheck.timer 全 active；ovpn-agent inactive（#3 后未重注册节点）；dante 测试替身进程不在（#2/#3 清场后未重起；SK5 关态下无关）。
- 防火墙：ufw 已卸载（dpkg `rc` 态，/etc/ufw 配置残留），内核 ufw 规则 0 条——与本轮开始前一致（轮前即未装 ufw），INPUT ACCEPT＋ts-input；长表 2005 条规则已随 ufw 卸载销毁。
- tarball：`/root/ovpn-r8.tar.gz` sha256 `dcba52223cdb702bbd8e7d10f9715132af68f0c598b86af30b0c02bfec96ceb9`（毒包证据，勿删）；`/root/ovpn-r7.tar.gz` sha256 `53de47fecfbc33ddfa61a715a8d2f812c7a66f5a77693027bc812346cde6453b`（对照留存，勿删）。日志与工具全在 `/root/r8/`（install/install2/install3/install-default/verify-on/verify-off/agent-install/tcp-tries/client-final.log，panel.py、netns-setup.sh、probe.sh、cdp.py、render/dashboard.png）。
- 遗留：§9 的 R8-BUG-1 破坏态已被 #2/#3 全新安装覆盖（机器现为全新部署，非 §9 破坏态）；R8-BUG-1/R8-BUG-2 待修复路修、AUDIT-R10 对账后重验（R8-BUG-1 验收：毒包解压树默认重跑须出横幅、登录成功、节点/审计/用户全在；R8-BUG-2 验收：ufw 启用＋长表下全新安装，ufw 仍在、原规则全在、1194/8443 放行补加）。

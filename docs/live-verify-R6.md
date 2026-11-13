# OpenVPN 接 SK5 落地 · 真机复跑验证报告（第六轮 R6）

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（U/V/W/X 修复后的最新树——本轮第一次验证 U/V/W/X）。
> 验证人：真机复跑验证路（第六轮）。日期：2026-11-12。
> **结论先写：S0–S4 全过；BUG-9 第七次复验 UDP/TCP 双模式修好；BUG-15/16 默认重跑通过；headline-1 (a)(b)(c) 全过、(d) 发现 R6-BUG-2；headline-2 全过（开态 18/0/4、关态 23/0/0，R5-BUG-1 真机终验通过）；headline-3 全过。新 bug 2 条：R6-BUG-1（首次启用 500，一次性竞态、复现未果）与 R6-BUG-2（门禁 python argv，中）。阻塞：R6-BUG-1 1 条待主控裁定（首启失败需重试）；R6-BUG-2 为门禁项。**
> 前情：第一轮见 [live-verify.md](live-verify.md)（S0–S4 全过，9 个 bug，4 阻塞）；第二轮见 [live-verify-R2.md](live-verify-R2.md)（S0–S4 全过，新发现 7 个 bug，3 阻塞）；第三轮见 [live-verify-R3.md](live-verify-R3.md)（S0–S4 全过，BUG-9 第四次复验修好，新发现 6 项）；第四轮见 [live-verify-R4.md](live-verify-R4.md)（S0–S4 全过，新发现 4 项：R4-BUG-1 限流钉死＋静默直连、R4-BUG-2 自拷 abort、R4-BUG-3/4 门禁 bug）；第五轮见 [live-verify-R5.md](live-verify-R5.md)（S0–S4 全过，headline-1/2/4/5/6 通过，headline-3 未全绿——唯一新发现 R5-BUG-1 门禁，X 路已修）。

## 0. 树版本（本次装机所用）

| 文件 | mtime (UTC) | 说明 |
|---|---|---|
| install.sh | 2026-11-12 05:59:49 | R 路（未动） |
| panel/app.py | 2026-11-12 08:07:29 | U 路：status 以 policy_routing_active 为判据、set_sk5 短路、fail-over 区分 |
| panel/templates/index.html | 2026-11-12 02:49:17 | L 路（未动） |
| egress/sk5_manager.py | 2026-11-12 08:07:40 | U 路：check_health 三全要求、fail-open 区分 failover_failed |
| verify.sh | 2026-11-12 07:29:19 | T 路＋主控双机制检查（未动） |
| verify-integration.sh | 2026-11-12 08:14:24 | 主控：§4c 格 B 改写为真实翻转（U 路 P2-2 后门禁冲突修） |
| core/openvpn_manager.py | 2026-11-12 06:01:40 | S 路（未动） |
| egress/test-egress.sh | 2026-11-12 08:40:51 | X 路：§6 loopback 端点只验活性、差值断言 SKIP |
| cloudflare/src/index.js | 2026-11-12 08:05:38 | W 路：handleCreateCmd 回 queued:true |
| README.md | 2026-11-12 08:06:36 | V 路：门禁数 27、route-get 源 10.8.0.1、文档去假宣称 |

树稳定检查：08:47:41 核查时最新改动为 egress/test-egress.sh（08:40:51），须满 15 分钟稳定（08:55:51 UTC）后打包传机。**08:56:29 复核：安装相关文件自 08:40:51 后无改动，稳定 15 分 38 秒，门过**。注：并行在跑的 AUDIT-R7 此时正在写 `docs/audit/AUDIT-R7.md`，docs/ 不在安装拷贝清单内，故本次打包**只含安装子集**（agent core egress panel systemd install.sh verify.sh verify-integration.sh README.md），不含 docs/ 与 `__pycache__`。

**打包（08:56:29 UTC）**：传包走 scp（R4/R5 同款）。`ovpn-r6.tar.gz`：48 条目，279,742 字节，sha256 `76686359993dc1c022948272d600c38020de932aea0cd7556b69410b4dc9f253`（机上核对一致）；install.sh sha256 `977054c388c938928368d10a59b1c0c210bff53fd621cefc88fc45ffbd2313b8`（与 R5 相同，install.sh 本轮未动）。

## 1. 地面真值（Lightsail 现状，测试前实测，08:47 UTC）

- 机上是**第五轮收尾态**（与 R5 §15.2 逐项一致）：六服务全 active（openvpn-server@server PID 509468、openvpn-sk5-singbox PID 507341、openvpn-sk5-panel PID 488562、openvpn-sk5-policy、ovpn-agent PID 490170、danted PID 491573），TCP 443 部署，SK5 开（dante 替身），监听 443/tcp、11080、8443。
- 第五轮残留全部在位，**重装前必须清除**：
  - netns `vpntest` 仍在（第五轮残留）；
  - `/root/r5/` 测试产物在位（alice2-tcp-lan.ovpn、client 日志）＋ `/root/r5-cleanup.sh` ＋ `/root/ovpn-r5.tar.gz`；
  - alice 客户端 PID 509525 仍在跑（第五轮 TCP 客户端，新证书）；
  - `/opt/openvpn-sk5-panel/` 为第五轮装树（含 agent/ 与 systemd/）。
- FLMX 相关进程同机在跑（sing-box PID 53637、2054953、2755416，`/etc/flmx_agent/kernels/singbox/`），**一律不碰**；`/root/flmx-panel` 不动。

## 2. 清场（全新重装前，08:57 UTC）

- 客户端 PID 509525（第五轮 TCP 客户端）按精确 PID 杀掉，已确认无此进程；四服务已停（openvpn/singbox/panel/agent 全部 inactive，dante 保留，active）。
- 绕行已清：FORWARD 链清至只剩 ts-forward/DOCKER-USER/DOCKER-FORWARD（策略 DROP，删掉安装器自加的两条 tun0 规则与 policy-routing 的两条 tun0↔tun1 规则——注：清场脚本的 `--line-numbers` 循环只删掉了前两条，tun0↔tun1 两条须用完整规则描述显式 `-D` 才删掉，已核对链内零产品规则）；系统信任库无 ovpn 证书（R3 已清，本轮复核无残留）；无 systemd drop-in 残留；netns `vpntest` 已删。
- 状态已 wipe：`/root/openvpn-sk5-panel`、`/opt/openvpn-sk5-panel`、`/opt/ovpn-agent`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/ovpn-agent` 全删；sing-box 与 tun2socks 二进制已删（逼安装器走下载路径，复验 BUG-2）；`/root/r5/`、`/root/r5-cleanup.sh`、`/root/ovpn-r5.tar.gz` 已清。
- 新树已就位：`/root/openvpn-sk5-panel/`（R6 包解压），install.sh sha256 与打包值一致（`977054c3…`）。
- 清场后核对：只剩 tailscale0 一个 tun 设备、无 1194/443/8443 监听、`/opt/openvpn-sk5-panel` 与 `/etc/openvpn-sk5-panel` 不存在。

## 3. S0 基线：安装 + 建服务 + 建用户 —— 通过（默认路径，全程零绕行）

- `bash install.sh`（UDP 1194 默认）：**完成横幅已印、日志 0 个 ERROR**（EXIT=0 的判定与 R3/R4/R5 同口径：横幅 + 无 ERROR；nohup 后台跑故 `$?` 未直接捕获），无环境变量绕行、无手工规则、无手工信任库。apt + pip + PKI 全新生成；sing-box 1.11.15 与 tun2socks 2.7.0 因二进制已删而走下载，**均 `sha256 OK`**（BUG-2 下载路径本轮再次真机通过）。
- 五单元全 active：openvpn-server@server（PID 520389，UDP 1194 监听，tun0 UP）、openvpn-sk5-singbox（PID 520454，tun1 UP，10.9.0.1/30，direct 模式）、openvpn-sk5-panel（PID 520520，8443 监听）、openvpn-sk5-policy、openvpn-sk5-healthcheck.timer；restarts 全 0（BUG-3 修好）。
- **BUG-10 真机修好**：`/opt/openvpn-sk5-panel/agent/` 在位（agent.py、install-agent.sh、ovpn-agent.service）；**R3-BUG-3 真机修好**：`/opt/openvpn-sk5-panel/systemd/` 在位，5 个单元文件齐全。
- 面板登录 200；`/api/status` 200：openvpn running（UDP 1194，pid 520389，status_log `/var/log/openvpn/openvpn-status.log`），online_users 0（无客户端时正确），egress IPv6 直连，SK5 未启用，`singbox_running: true`，sk5 块 `policy_routing_active: false`（SK5 关时旗标为 false；`ip rule` 仍有 rule 100 在位但 table 100 为空——R2 已记的旗标语义，关态无实际影响）。顶层 `remote_ip` 为 `16.146.199.68`、`remote_warning` 为 null——R4 §3 的顶层 null 缺口本轮未现。
- **R3-BUG-5 真机修好**：默认 `.ovpn` remote 为 **`16.146.199.68 1194`（IPv4 公网）**；`GET /api/openvpn/public-ip` 返回 `16.146.199.68`。安装日志亦印 `public IP detected: 16.146.199.68`。
- 用户：alice、bob 创建均 200；`GET /api/openvpn/users` 只列 alice、bob（无 CA 条目，BUG-4 修好），各带 DER 序列号（alice `75290A3E1902B80A67C9EA8E2F6DA69B`、bob `F7F0BFBE4A14D969EBA69A59192587C1`）；`.ovpn` 下载 200（8612 字节），`proto udp / cipher AES-256-GCM / auth SHA256`，客户端证书 subject `CN = alice`、issuer `CN = OpenVPN-CA`（BUG-7 修好；注：直接对 .ovpn 跑 openssl 读到的是首个内嵌块即 CA 证书，须取 `<cert>` 块核对才是用户证书）。

## 4. S0-agent：节点注册 + agent 安装 + 命令链 —— 通过（BUG-11/12 默认路径修好）

- 注册：`POST /api/nodes {"name":"lightsail","panel_url":"https://172.26.15.152:8443"}` → 201，token 43 字符（一次性返回，未写报告；只存 `/root/r6/token.txt` 0600）。
- 安装命令（按前端 `buildInstallCommand` 拼出的两步走命令逐字执行，token 由文件读入、命令本体未改动）：`curl -ksSL 'https://172.26.15.152:8443/install-agent.sh' -o /tmp/install-agent.sh && curl -ksSL 'https://172.26.15.152:8443/install-agent.sh.sha256' -o /tmp/install-agent.sh.sha256 && cd /tmp && sha256sum -c install-agent.sh.sha256 && bash /tmp/install-agent.sh --panel-url 'https://172.26.15.152:8443' --token '…' --node-name 'lightsail'` → **EXIT=0**。`install-agent.sh: OK`；TOFU 自动把面板自签证书钉到 `/etc/ovpn-agent/panel-ca.pem`；bundle 下载后 sha256 OK；`/etc/ovpn-agent/config.json` 0600；`ovpn-agent is ACTIVE (node=lightsail)`。**全程零手工信任库、零手工拷文件**——BUG-11 与 BUG-12 默认路径均修好。
- poll：`GET /api/nodes` 的 `last_seen` 为 2026-11-12T09:00:31+00:00（查时约 09:00:39，新鲜）；agent 日志 5 分钟内无 401/403、无 poll failed。
- 命令链：`POST /api/cmd {"node":"lightsail","action":"get_status"}` → **202**（cmd_id 0361aa00…，queued）；约 3 秒后 `GET /api/cmd/<id>` → **done**，error null；result 含 openvpn running=true pid 520389（与面板一致）、sk5 enabled=false、users alice/bob。

## 5. S1 直连态（UDP 1194）—— 通过（首次即通，零手工 FORWARD）

- 客户端（alice，netns vpntest，`--float`，remote 改为 LAN IP 172.26.15.152——机内 netns 发往公网 IP 会经 ens5 出网关发夹回不来，属云环境限制；出厂默认 remote 已在 §3 验为公网 IPv4）：**首次即通**，`Initialization Sequence Completed`（09:01:17），tun0 10.8.0.2/24，redirect-gateway 路由就位。安装器自带的 FORWARD 规则之外未加任何手工规则（测试侧 netns 自身的 veth 转发规则除外）。
- 数据面（direct）：`curl ifconfig.me`（HTTP 与 HTTPS，--resolve 绕 MagicDNS）→ **16.146.199.68**；`dig @1.1.1.1 ifconfig.me` → 34.160.111.145 有回包；NTP UDP：216.239.35.4 回 **48 字节** 12.4ms、162.159.200.1 回 **48 字节** 6.0ms。UDP 数据面通过。
- **BUG-9 第七次复验——修好（UDP 模式）**：部署态原始日志（逗号 v2，13 段）为 `CLIENT_LIST,alice,10.200.0.2:59921,10.8.0.2,,6354,13093,2026-11-12 09:01:17,1794474077,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users` = **1**；`clients`=[{name: alice, real_address: 10.200.0.2:59921, virtual_address: 10.8.0.2, bytes_received: "6354", bytes_sent: "13093", connected_since: "2026-11-12 09:01:17"}]——逐字段一致；`/api/openvpn/users` 的 alice `online: true`、bob `online: false`。
- 测试侧小事故（非产品）：`panel.py api` 的输出是 `200 {...}` 一行，我直接喂 `json.load` 报 Extra data；改 `sed "s/^200 //"` 后正常。数据面结论不受影响。

## 6. S2 落地态（SK5 开）—— 通过（TCP+UDP 均走 SK5，双日志为证）

- 开启（首次尝试）：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **500**，`{"error":"policy-routing.sh enable failed: RTNETLINK answers: File exists","ok":false}`——见 **R6-BUG-1**（§13）。盘上 `sk5.json` 仍为 `enabled: false`（Q 的先成功后写盘守住了盘状态）；但 sing-box 已被该次调用渲染成 SK5 配置并重起（新 PID 522770），策略路由未应用——daemon 与盘短暂分裂（见 §13）。
- 开启（原样重发同一请求）：→ **200**，enabled=true，`policy_routing_active: true`，egress_ip 16.146.199.68；sing-box active（重起后 PID 523551）；`ip rule` 有 `from 10.8.0.0/24 lookup 100`；table 100 为 `default via 10.9.0.1 dev tun1`；`ip route get 1.1.1.1 from 10.8.0.1` → `dev tun1 table 100`；tun1 UP。alice 的隧道在两次开启尝试前后未断（同一客户端 PID 522288 持续）。
- 面板 `POST /api/sk5/test` → **tcp_ok: true、udp_ok: true**（native 模式，TCP 延迟 89.5ms）。
- 客户端 TCP（经 SK5）：`curl --resolve ifconfig.me:80:34.160.111.145 http://ifconfig.me` 与 HTTPS 同式均回 **16.146.199.68**；sing-box 日志同秒有 `outbound/socks[bought-sk5] … to 34.160.111.145:80` 与 `:443`；dante 日志同秒有 `tcp/connect … 127.0.0.1.11080 -> 34.160.111.145.80` 与 `:443`——TCP 确实走了 dante（SK5 替身）。出口 IP 不变属预期：替身与面板同机，S1/S2 出口恒为 16.146.199.68，链路证明以路由表 + 双日志为准（R1 已定口径）。
- 客户端 UDP（经 SK5）：NTP 到 216.239.35.4 回 **48 字节** 27.6ms、162.159.200.1 回 **48 字节** 32.9ms；sing-box 日志有 `outbound/socks[bought-sk5] … outbound packet connection to 216.239.35.4:123` 与 `162.159.200.1:123`。UDP 走 SK5 为证。

## 7. S3 断网保护（杀 dante）—— 通过（流量全断、无直连回落、自动恢复、隧道不断）

- 杀 dante（`systemctl stop danted`，inactive）：客户端 TCP `curl --resolve … http://ifconfig.me` → **exit 56**（Recv failure）；NTP UDP 到 216.239.35.4 → **TimeoutError**；**无直连回落**（curl 不是成功、是失败——fail-closed 成立）。隧道未断（同一客户端 PID 522288，tun0 仍在）。
- 面板 `/api/status`：kill 期间 **egress.ip = null**（`{'error': None, 'ip': None, 'latency_ms': None, 'via_sk5': True}`），诚实报空；sk5 enabled=true、policy=true。
- 恢复（`systemctl start danted`，active）：客户端 TCP 立即回 **16.146.199.68**，NTP 回 **48 字节** 15.7ms/9.2ms。隧道全程未断：同一 PID 522288，client.log 里 `Initialization Sequence Completed` 仅出现 1 次、SIGUSR1 0 行——无重连、无重拨。
- 补证：S2 窗口内 dante 日志有 6 条 `udpassociate`——UDP 亦经 dante（与 sing-box 的 packet-connection 日志互证）。

## 8. S4 TCP 备模式（443）—— 通过（BUG-14 修好，S1/S2 各重跑一次）

- **BUG-14 修好**：`POST /api/openvpn/server {"proto":"tcp","port":443,"allow_port_change":true}` → **HTTP 200**。`POST /api/openvpn/restart` → 200（新 pid 524192）。TCP 443 监听，UDP 1194 监听消失，`/api/status` 为 proto=tcp port=443 running=true；新下载的 alice.ovpn 为 `proto tcp / remote 16.146.199.68 443`（默认 remote 仍是 IPv4 公网）。
- S2-TCP（SK5 开）：新 TCP 客户端首次即通（09:05:55，tun0 10.8.0.2/24）；curl → 16.146.199.68；NTP → 48 字节 14.9ms/8.4ms；dante 日志同窗口 10 条 `tcp/connect`/`udpassociate`——TCP+SK5 链路在 TCP 模式下同样成立。
- BUG-9（TCP 模式）：原始日志 `CLIENT_LIST,alice,10.200.0.2:56848,10.8.0.2,,6735,12254,2026-11-12 09:05:55,1794474355,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users`=**1**，`openvpn.detail.clients`=[{name: alice, real_address: 10.200.0.2:56848, virtual_address: 10.8.0.2, bytes_received: "6735", bytes_sent: "12254", connected_since: "2026-11-12 09:05:55"}]——逐字段一致。**BUG-9 第七次复验在 UDP 与 TCP 两种模式下均修好**。时序说明：客户端连上后首次查面板显示 online=0——状态日志写盘节律所致（09:06:08 读到的仍是旧快照，40 秒后刷新即 online=1；R5 §14.3 同现象），非回归。
- S1-TCP（SK5 关）：`POST /api/sk5 {"enabled":false}` → 200（`policy_removed: true`、`singbox_restarted: true`、`singbox_running: true`——disable 后 sing-box 仍在 direct 模式跑，R3-BUG-1 修好；注：单字段 disable 本身会重起 daemon，零重起只属于全表单保存的 still-disabled 纯写盘分支，R5 纠正）；rule 100 消失、table 100 空、路由回 ens5；TCP 客户端 curl → 16.146.199.68，NTP → 48 字节 11.8ms/6.1ms，dig @1.1.1.1 → 34.160.111.145；同一客户端 PID 524263 全程未断（`Initialization Sequence Completed` 仅 1 次）。

## 9. BUG-15/16 默认重跑（SK5 开 + TCP 443 部署，无环境变量）—— 通过

- `bash install.sh`（无 OVPN_PROTO/OVPN_PORT）：**完成横幅已印、日志 0 个 ERROR**（EXIT=0，同 S0 口径）；继承行：`inheriting deployed entry port from /etc/openvpn/server/server.conf (proto=tcp port=443; explicit OVPN_PROTO/OVPN_PORT still wins)`；横幅 `proto=tcp port=443 … (entry port inherited from existing server.conf)`；server.conf 仍为 `port 443 / proto tcp`——**R3-BUG-6（exit 127）与 BUG-16（不继承）双双修好**。
- 健康门禁：六服务（openvpn/singbox/panel/policy/healthcheck.timer/agent）全 active，restarts 全 0；openvpn 同一 PID 524192（未重启）、panel 同一 PID 520520；`/api/status` proto=tcp port=443 running=true online=1，sk5 enabled=true policy=true，egress via_sk5=true；rule 100 + table 100 在位；客户端 PID 524263 全程未断（`Initialization Sequence Completed` 仅 1 次），重跑后 curl 仍通、NTP 48 字节。原地升级路径打通。
- 注：本次重跑前 SK5 已是开启态（为本节准备而在 §8 末重开，全表单 POST → 200，无 500——R6-BUG-1 的首次 500 之后，第二、第三次全表单开启均为一次 200，见 §13）。

## 10. headline-1 U/V/W 真机验证（本轮重点）—— (a)(b)(c) 通过，(d) 发现 R6-BUG-2

### 10.0 重起计数基线（09:09 UTC，headline-1(c) 用）

- sing-box MainPID 524961，journal `Started openvpn-sk5-singbox.service` 自 08:57 安装起计 **5** 次，NRestarts=0。

### 10.1 headline-1(a) via_sk5 四态 —— 通过（R6-P1-1 真机修好，S 路修假的前科已雪）

- **A 态（enabled＋策略在位）**：`enabled=true`、`policy_routing_active=true` → **via_sk5=true、egress.ip=16.146.199.68、error=None**。
- **B 态（enabled＋策略缺失，手工删 rule 100＋清 table 100，09:09:25）**：隔 16 秒（越过 `/api/status` 10 秒缓存）新鲜读 `/api/status` → **enabled=true、policy=false、via_sk5=false、egress.ip=None、error='SK5 已启用但策略路由未生效，出口未经过 SK5'**——R6 探针 A/C 两格的撒谎在本轮真机上已消失。同期健康检查定时器（09:09:42）亦记 `healthy=false、action=policy_missing`（见 §10.2）。
- **C 态（策略恢复，全表单重开）**：`POST /api/sk5 {"host","port","enabled":true}` → 200，**`repaired: true`、`repair_detail: ["policy routing re-applied"]`**，daemon MainPID 不变（524961）、Started 计数不变（5 次）——**零重起补策略**（Q 的 repair 分支在真机上按设计工作）；恢复后 `/api/status` 为 enabled=true、policy=true、via_sk5=true、ip=16.146.199.68。
- **D 态（禁用）**：见 §10.3 末——单字段 disable 后 `enabled=false`、`policy=false`、`via_sk5=false`，egress.ip 为直连探针 IP（见 §10.3）。
- 观察（不立案，供 R7 裁定）：B 态下 `GET /api/sk5` 的 `sk5.egress_ip` 仍为 16.146.199.68——它是直拨 SOCKS 的探针结果（dante 活着，探针本身成功），与 `/api/status` 的 gated egress.ip=None 是两个不同量；面板 UI 的三处「当前出口 IP」均渲染 gated 的 `eg.ip`（index.html:658/672/681），用户界面不撒谎。仅直接读 `/api/sk5` 裸字段者可能误读。

### 10.2 headline-1(b) check_health —— 通过（R6-P1-1/P2-1 双双真机修好）

- **策略缺失时 healthy=false**：B 态窗口内健康检查定时器 09:09:42 记 `healthy=false、action=policy_missing`（detail 明示策略未应用、流量直连、待面板重开修复）——不是 healthy、不是 `blackholed_kill_switch`（策略缺失时本无黑洞，U 的区分成立）。
- **fail-open 分支 disable() 提前抛错**：故障注入——`fail_open=true` 后移走 `sing-box.json.template`、停 dante，手动跑 `sk5_manager.py health` → `healthy=false、action=failover_failed`，detail 为 `tcp_ok=False udp_ok=False egress=None; fail-over did not run: template not found: …/sing-box.json.template`；health.json 同值落盘。盘上仍 `enabled=true`、rule 100＋table 100 均在位、sing-box 同 PID 524961 active——**未记 `failed_over_to_direct`**，R6-P2-1 修好。随后模板归位、dante 重起、`fail_open=false`，状态恢复 via=true、ip=16.146.199.68。

### 10.3 headline-1(c) 冗余重起 —— 通过（6 步只重起 3 次，U 的 6→3 真机复验）

基线（6 步前，已禁用态）：Started=6、MainPID=527316（前置一次单字段 disable 翻转计 5→6、PID 变化，属真实翻转）。

| 步 | 调用 | 响应 | Started | PID | 结论 |
|---|---|---|---|---|---|
| 1 | 单字段 `{"enabled":true}`（翻转） | 200 enabled=true policy=true | 6→7 | 变 | 重起 1 次 ✓ |
| 2 | `POST /api/sk5/enable`（已启用） | 200（`result` 形回执） | 7 | 不变 | **零重起** ✓ |
| 3 | 单字段 `{"enabled":false}`（翻转） | 200 policy_removed=true singbox_restarted=true | 7→8 | 变 | 重起 1 次 ✓ |
| 4 | `POST /api/sk5/disable`（已禁用） | 200 | 8 | 不变 | **零重起** ✓（单字段 disable 在已禁用链上不碰 daemon） |
| 5 | 全表单 `{"host","port","enabled":true}`（翻转） | 200 enabled=true policy=true | 8→9 | 变 | 重起 1 次 ✓ |
| 6 | 全表单同值重发（无变化） | 200 enabled=true policy=true | 9 | 不变 | **零重起** ✓ |

- **6 步合计重起 3 次**（修前 6 次）——U 的 6→3 真机复验通过。
- **值未变的 udp_over_tcp 保存**（已启用链上 `{"udp_over_tcp":false}`）：Started 9、PID 不变——**不得重起** ✓。
- **D 态**（末步单字段 disable 后新鲜读状态）：enabled=false、policy=false、**via_sk5=false、egress.ip=2600:1f13:14d:a300:7913:f273:997e:c8b8（直连探针 IPv6）、error=None** ✓。

### 10.4 headline-1(d) verify-integration 登录密码不进 argv —— curl 半边通过，python 半边漏网（R6-BUG-2）

- **机上门禁跑动**：`verify-integration.sh` 是沙箱门禁（自带面板、占 8443），在测试机（面板已占 8443）上按设计直接 SKIP（`面板端口 8443 已被占用`，PASS=0 FAIL=0 SKIP=1）——机上 watcher（150 秒）记 curl_seen=0、real_password_leaks=0，属空跑，无证明力。沙箱才是它的运行地。
- **沙箱门禁跑动**：与并行在跑的 AUDIT-R7 共用沙箱、共用 `/tmp/ovpn-int-test` 与 8443——我的面板起不来（`Address already in use`，PASS=2 FAIL=1），完整 28 格未能在本轮跑出（主控在 R7 复扫里已重跑 28/28）。**教训（测试侧）**：沙箱门禁与审计 lane 共用固定路径＋固定端口时会互撞；下次跑门禁前须先确认无并行 lane 在用同一路径/端口。另：我的开局 `rm -rf /tmp/ovpn-int-test` 与收尾 trap 可能清掉了并行 lane 的测试目录——已在本节末向主控点名。
- **curl 半边——通过（W 路成立）**：同形实测（dummy 值，命令形与门禁 :283-285 逐字一致）：登录 curl 进程的 `/proc/<pid>/cmdline` 为 `curl -s --max-time 25 --data @/tmp/dummy-payload.json http://10.255.255.1:8443/api/login`——argv 里只有文件路径，无密码。
- **python 半边——漏网（R6-BUG-2，中，门禁）**：门禁 :280 写 payload 用的是 `python3 - "$ADMIN_PASS" "$LOGIN_PAYLOAD" <<'PYEOF'`——密码是 python3 进程的 argv[1]。同形实测（dummy 值＋sleep 20 保活）：`/proc/<pid>/cmdline` 为 `python3 - DUMMY-VALUE-NOT-A-REAL-PASSWORD /tmp/dummy-payload.json`——**密码明文在 argv 里**，`ps`/`/proc` 可读，与 R1-P2-8/W 要堵的暴露面同类（W 只把密码挪出了 curl 的 argv，没挪出 argv 本身）。窗口约 100–300ms/次、仅本机可读，但暴露类与被修项同一族，立案。

## 11. headline-2 R5-BUG-1 真机终验 —— 通过（开态 18/0/4、关态 23/0/0，第五轮关态天花板消失）

- **开态**（SK5 开，dante，09:24 UTC）：`bash verify.sh` → **PASS=18 FAIL=0 SKIP=4，VERIFY: ALL GREEN**（与 R5 开态 18/0/4 一致；4 个 SKIP 为开态下跳过的 toggle 格——sk5-toggle、sk5-egress-ip、sk5-disable、sk5-enable-endpoint，属设计）。
- **关态**（面板关 SK5 后 25 秒再跑，09:25 UTC）：`bash verify.sh` → **PASS=23 FAIL=0 SKIP=0，VERIFY: ALL GREEN**。第五轮关态 22/1（唯一 FAIL 为 egress-crosscheck §6 地址族前提）已消失——**R5-BUG-1 真机终验通过**。
- **§6 格本格**：关态 `egress-crosscheck -- egress/test-egress.sh exit 0 while chain up` **PASS**；开态同格亦 PASS（X 的 loopback-SKIP 落在 test-egress.sh 内，verify.sh 只取其 exit 0）。注：X 的矩阵已在沙箱验过（桩同 IP→SKIP 5/0/2、商家同 IP→FAIL、商家不同 IP→PASS）；本轮真机只断言 verify.sh 双态 FAIL=0，未重跑 X 矩阵。
- 关态跑完后 verify.sh 自身把链重开又清回关态（sk5-enable-endpoint 格末尾 cleanup disable），终态以 §15 为准。

## 12. headline-3 开关风暴＋补策略回归 —— 通过

- **风暴**（storm2.sh，8 次快速切换，1 秒间隔，全表单/单字段交替翻转）：8 次全部 **200**，每次 MainPID 均变化，journal Started 计数 98→106（**delta 恰 8**），daemon 全程 active、**未钉死**。注：第一次 storm.sh 全灭是测试侧失误——脚本直接执行 `/root/r6/panel.py`（0600、无执行位，`Permission denied`），8 次翻转与修复均未实际发出；且 `NRestarts` 不计手工 `systemctl restart`（只计自动重起），用它当重起计数是错的。两点均已纠正（`python3` 显式调用＋journal Started 计数），storm2 为有效结果。
- **策略丢失后全表单重开零重起**：§10.1 C 态已证——手工删 rule 100＋清 table 100 后全表单重开，`repaired: true`、`repair_detail: ["policy routing re-applied"]`，MainPID 与 Started 计数均不变。
- **daemon 钉死后全表单重开恰一次重起**（R5 E4 同款）：6 次快速 `systemctl restart openvpn-sk5-singbox`——前 4 次 active，第 5 次即报 `start of the service was attempted too often`、**failed**（start-limit 钉死）；全表单重开 → 200，`repaired: true`、`repair_detail: ["sing-box restarted"]`，Started 计数 110→111（**delta 恰 1**），daemon active（新 MainPID 579010），rule 100＋table 100 均恢复。
- **流量真实走 SK5、隧道零重连**：风暴＋修复后探针（storm3）：HTTP/HTTPS 均回 16.146.199.68，dig @1.1.1.1 → 34.160.111.145，NTP 48 字节 20.0ms/11.2ms；客户端 PID 524263 存活，`Initialization Sequence Completed` 全轮仅 1 次。

## 13. 新 bug（本轮发现，2 条）

### R6-BUG-1（首启 500，一次性竞态；严重度：待主控裁定，暂按阻塞候选记）

- **现象**（09:02:22 UTC，新装后首次面板启用）：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **500**，`{"error":"policy-routing.sh enable failed: RTNETLINK answers: File exists","ok":false}`。原样重发同一请求 → 200。之后本轮全部启用（§9 前置、§10.3 步 5、storm2 八次、复现尝试）均为一次 200。
- **事后分裂**：500 之后盘上 `sk5.json` 仍 `enabled: false`（Q 的先成功后写盘守住了盘状态），但 sing-box 已被该次调用渲染成 SK5 配置并重起（新 PID 522770），策略路由未应用——daemon 与盘短暂分裂（重发 200 后弥合）。
- **机理分析**：`do_enable()` 对 `ip rule add` 有 `rule_exists` 守卫、路由用 `ip route replace`，单条 `ip rule add` 报 EEXIST 意味着守卫漏判或并发加规则。查遍日志无并发加规则者：policy 服务为 oneshot restore（09:00 后无条目）、healthcheck 只探针、agent 只读。安装器在安装时加过 rule 100，但 S0 末状态里 rule 100 在位、table 100 为空——即**安装器确实留下了 rule 100**，而 `rule_exists` 守卫本应挡住它。守卫为何漏判，未定位。
- **复现尝试（未果）**：禁用 → 手工只加 rule 100（复刻安装器残留态）→ 面板启用 → **200**（一次成功）。故「残留 rule 100 即 500」假说不成立，首启 500 是一次性竞态，未复现。
- **复现中附带观察（未立案）**：复现命令里禁用后 `ip rule show | grep -c "100:"` 读到 1（规则疑似未清）；立即干净重测一次禁用，rule 100 正确清除、table 100 为空。单次读数与干净重测矛盾，未复现，不立案，记在此供后轮留意。

### R6-BUG-2（中，门禁）verify-integration.sh 登录密码仍进进程 argv

- **位置**：`verify-integration.sh:280`，写 payload 用 `python3 - "$ADMIN_PASS" "$LOGIN_PAYLOAD" <<'PYEOF'`——密码是 python3 进程的 argv[1]。
- **证据**（dummy 值，同形实测）：`/proc/<pid>/cmdline` 为 `python3 - DUMMY-VALUE-NOT-A-REAL-PASSWORD /tmp/dummy-payload.json`——密码明文在 argv 里，`ps`/`/proc` 可读。W 路只把密码挪出了 curl 的 argv（:283-285 `--data @file`，同形实测 argv 里只有文件路径，**curl 半边成立**），没挪出 argv 本身；暴露类与 R1-P2-8/R6-P2-3 同族。
- **范围**：窗口约 100–300ms/次，仅本机可读，密码为门禁自建测试面板的临时口令（非生产口令）。同脚本的 SECRET1 `-d` 出现处（:332/:405/:432/:451）是已知接受的硬编码夹具，不属本条。
- **完整门禁跑动未在本轮跑出**：沙箱 run 与并行 AUDIT-R7 撞车（共用 `/tmp/ovpn-int-test`＋8443，我的面板 `Address already in use`，PASS=2 FAIL=1）；机上按设计 SKIP（面板已占 8443）。主控在 R7 复扫里已重跑 28/28，本条只影响 (d) 的 argv 结论，不影响门禁格数。

## 14. 观察项（不立案）

- **R3-OBS-1 微复发**：全轮面板 journal 里 401 共 **1 次**（09:28:59，`GET /api/status`，127.0.0.1），403 为 0；无失败操作、无用户影响，归属未完全确定（verify-off 末格或面板会话过期后自愈）。R5 为 0 次。记观察，不立案。
- **B 态 `/api/sk5` 裸字段**：§10.1 已记——`sk5.egress_ip` 是直拨探针量，与 gated egress.ip 不同；UI 三处渲染 gated 值，不撒谎。供 R7 裁定。
- **沙箱门禁互撞**：§10.4 已记——并行 lane 共用固定路径/端口；我的开局 `rm -rf /tmp/ovpn-int-test` 与收尾 trap 可能清掉了 R7 的测试目录，已向主控点名（R7 报告已出，未见因此失败的记录）。
- **沙箱 watcher 未识别的 curl**：0.1 秒采样 300 秒窗内见 30 次含 `"password"` 键的 curl（非 SECRET1 夹具，值未记录），归属未定（并行 lane 的套件调用），真实口令 argv 命中为 0。记观察，不立案。
- **storm1 测试侧失误**：§12 已记——panel.py 直接执行无权限、NRestarts 误作重起计数；storm2 已纠正重跑。

## 15. 结论与机器终态

### 15.1 结论

- **S0–S4 全过**；BUG-9 第七次复验 UDP/TCP 双模式修好；BUG-15/16 默认重跑通过（原地升级路径打通）。
- **headline-1**：(a) via_sk5 四态通过（R6-P1-1 真机修好）；(b) check_health 通过（R6-P1-1/P2-1 双双真机修好）；(c) 冗余重起通过（6 步 3 次重起、udp_over_tcp 未变不重起、已禁用链单字段 disable 零重起）；(d) **未全过**——curl 半边通过，python 半边漏网，**R6-BUG-2（中，门禁）**。
- **headline-2**：通过——verify.sh 开态 18/0/4、关态 23/0/0，**R5-BUG-1 真机终验通过**。
- **headline-3**：通过——风暴 8 次不钉死、策略丢失零重起补回、daemon 钉死恰一次重起修复、流量走 SK5、隧道零重连。
- **新 bug 2 条**：R6-BUG-1（首启 500，一次性、未复现）、R6-BUG-2（门禁 python argv，中）。**阻塞：R6-BUG-1 1 条待主控裁定**（新装后首次启用即 500 报错、需重试；但全轮仅出现一次、后续 5 次以上启用全一次成功）。
- **本轮测的树**：U/V/W/X 树，包 sha256 `76686359…f253`（§0）。AUDIT-R7 及其修复路 Y/Z/AA/AB 不属本轮验证范围（R7 已另行结论：不能交付，P1 1＋P2 7）。

### 15.2 机器终态（09:36 UTC）

- 部署：TCP 443（openvpn PID 524192）、SK5 **开**（dante 替身 127.0.0.1:11080）、via_sk5=true、egress.ip=16.146.199.68、online_users=1（alice，自 09:05:55 连接未断）。
- 服务：openvpn/singbox/panel/policy/healthcheck.timer/agent/dante 全 active；客户端 PID 524263（TCP，alice）存活，全轮 `Initialization Sequence Completed` 仅 1 次。
- 测试产物：`/root/r6/`（panel.py、token.txt 0600、probe/toggle/storm/argv 脚本、verify-on/off 日志、状态快照）；netns `vpntest` 在位（供下轮复用或清场）。
- **FLMX 一根手指未碰**（同机 FLMX sing-box 进程全程未动、`/root/flmx-panel` 未动）。

# OpenVPN 接 SK5 落地 · 真机复跑验证报告（第四轮 R4）

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（K/L/M/N 修复后的最新树）。
> 验证人：真机复跑验证路（第四轮）。日期：2026-11-12。
> 前情：第一轮见 [live-verify.md](live-verify.md)（S0–S4 全过，9 个 bug，4 阻塞）；第二轮见 [live-verify-R2.md](live-verify-R2.md)（S0–S4 全过，新发现 7 个 bug，3 阻塞）；第三轮见 [live-verify-R3.md](live-verify-R3.md)（S0–S4 全过，BUG-9 第四次复验修好，新发现 6 项：R3-BUG-6 高阻塞（默认重跑 exit 127）、R3-BUG-1（disable 杀 sing-box）、R3-BUG-3（装树漏 systemd/）、R3-BUG-5（默认 remote IPv6）、R3-BUG-2/4（门禁 bug））。

## 0. 树版本（本次装机所用，待稳定后填）

| 文件 | mtime (UTC) | 说明 |
|---|---|---|
| install.sh | 2026-11-12 03:38:13 | P 路：探测逐段 ≤255 校验（R4-P2-3）+ M 路 log() 前移/装树补 systemd/ |
| panel/app.py | 2026-11-12 02:22:28 | H 路（未动） |
| panel/templates/index.html | 2026-11-12 02:49:17 | L 路：buildInstallCommand 三处 shellQuote |
| egress/sk5_manager.py | 2026-11-12 03:40:11 | O 路：set_sk5 只在模式变化时重起（R4-P1-1 修复，:572 注释为证） |
| verify.sh | 2026-11-12 03:22:51 | N 路：bundle 列表存变量再 grep、route-get 源改 10.8.0.1 |
| verify-integration.sh | 2026-11-12 03:40:37 | O 路：P2-4 门禁补格 |
| README.md | 2026-11-12 03:38:13 | P 路：复制清单补 systemd/（R4-P2-2） |

树稳定检查：03:26:41 核查时最新改动为 egress/sk5_manager.py（03:24:04），须满 15 分钟稳定（03:39:04 UTC）后打包传机。**03:38:21 复核时 install.sh 在 03:38:13 被改动**（P 路修 R4-P2-3：install.sh:454-457 加逐段 ≤255 校验），门未过，重新计时至 03:53:13 UTC。AUDIT-R4（03:36 落盘，276 行）已读：裁决不能交付，P1 1 + P2 4——R4-P1-1 是 M 路修 R3-BUG-1 引入的回归（set_sk5(enabled=False)/disable()/check_health fail-over 硬依赖 sing-box 立即重起成功；无操作保存也 500；fail-over 抛错不写 health.json；沙箱 Flask 60/62、agent 17/19、egress 套件 setup 即崩）；O/P 两路 11:37 CST 已派修（O 修 P1-1 + P2-1 + P2-4 门禁补格，P 修 README 清单 + ≤255 校验）。本轮按简报继续等树稳定，**打包时以实际落盘的最新树为准并在 §0 登记**；若 O/P 在打包前落盘，BUG-1 序列与 fail-over 格即测 O/P 后的行为，R4-P1-1 的沙箱回归须在真机上复核是否仍现。

**打包（03:55:48 UTC，稳定 15 分 11 秒，门过）**：传包方式改走 scp（remote-storage 上传两次失败：第一次服务重启中断、第二次 egress approval 超时未获批，见 §0 附记）。`ovpn-r4.tar.gz`：59 条目，264,057 字节，sha256 `2dcaa26f2e0d9c28c29f281db971414c2788602d3aa1eca6ce414f80e07c2424`（机上核对一致）；install.sh sha256 `8ee5b567ef9ad0f32360715038a8af44f9ac68871bc2612d455fdd39cd8fe061`。打包树含 O/P 已落盘部分：install.sh（P 的 ≤255）、sk5_manager.py（O 的模式变化才重起）、verify-integration.sh（O 的门禁补格）、README.md（P 的清单补 systemd/）；O/P 两路在打包时是否全部完工未知——以落盘文件为准。

## 1. 地面真值（Lightsail 现状，测试前实测，03:27 UTC）

- 机上是**第三轮收尾态**：六服务全 active（openvpn-server@server PID 396135 NRestarts=0、openvpn-sk5-singbox、openvpn-sk5-panel PID 384658、openvpn-sk5-policy、ovpn-agent、danted PID 395607），TCP 443 部署，SK5 开（dante 替身），监听 443/tcp、11080、8443。
- 第三轮绕行/残留全部在位，**重装前必须清除**：
  - `/opt/openvpn-sk5-panel/` 缺 `systemd/`（R3-BUG-3 的现场证据）；
  - netns `vpntest` 仍在（第三轮残留）；
  - `/root/openvpn-sk5-panel/` 为第三轮上传树（含 systemd/）。
- FLMX 相关进程同机在跑，**一律不碰**；`/root/flmx-panel` 不动。

## 2. 清场（全新重装前，03:57–04:00 UTC）

- 四服务已停（openvpn/singbox/panel/agent 全部 inactive，dante 保留）；旧客户端进程已无（ps 无 openvpn 进程）。
- 绕行已清：FORWARD 链清至只剩 ts-forward/DOCKER-USER/DOCKER-FORWARD（策略 DROP，删掉安装器自加的两条 tun0 规则与 policy-routing 的两条 tun0↔tun1 规则）；系统信任库无 ovpn 证书（R3 已清，本轮复核无残留）；netns `vpntest` 已删。
- 状态已 wipe：`/root/openvpn-sk5-panel`、`/opt/openvpn-sk5-panel`、`/opt/ovpn-agent`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/ovpn-agent` 全删；sing-box 与 tun2socks 二进制已删（逼安装器走下载路径，复验 BUG-2）。
- 清场后核对：无 tun 设备、无 1194/443/8443 监听、`/opt/openvpn-sk5-panel` 不存在。
- **本轮操作事故（已记取教训）**：第一条清场命令里的 `pkill -f "openvpn.*alice"` 把远端 shell 自身匹配杀掉，命令中途夭折（stop 已生效，rm 未执行）；后改用 ps 查进程 + 精确规则删除重做。pkill 匹配串绝不出现在同一条命令里。

## 3. S0 基线：安装 + 建服务 + 建用户 —— 通过（默认路径，全程零绕行）

- `bash install.sh`（UDP 1194 默认）：**完成横幅已印、日志无 ERROR**（EXIT=0 的判定与 R3 同口径：横幅 + 全部门禁通过；nohup 后台跑故 `$?` 未直接捕获），无环境变量绕行、无手工规则、无手工信任库。apt + pip + PKI 全新生成；sing-box 1.11.15 与 tun2socks 2.7.0 因二进制已删而走下载，**均 `sha256 OK`**（BUG-2 下载路径本轮再次真机通过）。
- 五单元全 active：openvpn-server@server（PID 420040，UDP 1194 监听，tun0 UP）、openvpn-sk5-singbox（tun1 UP，direct 模式）、openvpn-sk5-panel（PID 420173，8443 监听）、openvpn-sk5-policy、openvpn-sk5-healthcheck.timer；restarts 全 0（BUG-3 修好）；FORWARD 两规则由安装器自加；VPN 源 `10.8.0.1` 经 ens5 出主表、不命中 table 100。ovpn-agent 在 S0 阶段 inactive（预期：agent 由 S0-agent 步骤安装，R3 同款）。
- 面板登录 200；`/api/status` 200：openvpn running（UDP 1194，online_users 0，无客户端时正确），egress IPv6 直连，SK5 未启用，`singbox_running: true`，sk5 块 `policy_routing_active: false`（SK5 关时旗标为 false，R4-P2-1 的 SK5 关误报在本轮未现——顶层 `policy_routing_active` 为 null，见 §10 观察）。
- **BUG-10 真机修好**：`/opt/openvpn-sk5-panel/agent/` 在位（agent.py、install-agent.sh、ovpn-agent.service）；**R3-BUG-3 真机修好**：`/opt/openvpn-sk5-panel/systemd/` 在位，5 个单元文件齐全（panel/singbox/policy/healthcheck.service/healthcheck.timer）。
- **R3-BUG-5 真机修好**：默认 `.ovpn` remote 为 **`16.146.199.68 1194`（IPv4 公网）**；panel.env 已写 `OPENVPN_SERVER_IP=16.146.199.68`；`GET /api/openvpn/public-ip` 返回 `16.146.199.68`。M 路的 `-4` 探测生效。
- 用户：alice、bob 创建均 200（`{"name": ...}` 口径；本轮第一次误用 `{"username": ...}` 得 400，是我测试侧传参错、非产品问题）；`GET /api/openvpn/users` 只列 alice、bob（无 CA 条目，BUG-4 修好），alice 带 DER 序列号 `0C12611A164BEDBB7B3132EC56028378`；`.ovpn` 下载 200，`proto udp / cipher AES-256-GCM / auth SHA256`。
- S0 缺口：`/api/status` 顶层 `remote_ip`/`remote_warning` 为 null（R3 时顶层有值）；默认 .ovpn 已正确，故只记观察（§10）。

## 4. S0-agent：节点注册 + agent 安装 + 命令链 —— 通过（BUG-11/12 默认路径修好）

- 注册：`POST /api/nodes {"name":"lightsail","panel_url":"https://172.26.15.152:8443"}` → 201，token 43 字符（一次性返回，未写报告）。
- 安装命令（按前端 `buildInstallCommand` 拼出的两步走命令，逐字执行，未改动）：`curl -ksSL …/install-agent.sh -o /tmp/install-agent.sh && curl -ksSL …/install-agent.sh.sha256 -o /tmp/install-agent.sh.sha256 && cd /tmp && sha256sum -c install-agent.sh.sha256 && bash /tmp/install-agent.sh --panel-url 'https://172.26.15.152:8443' --token '…' --node-name 'lightsail'` → **EXIT=0**。`install-agent.sh: OK`；TOFU 自动把面板自签证书钉到 `/etc/ovpn-agent/panel-ca.pem`；bundle 下载后 sha256 OK；`/etc/ovpn-agent/config.json` 0600；`ovpn-agent is ACTIVE (node=lightsail)`。**全程零手工信任库、零手工拷文件**——BUG-11 与 BUG-12 默认路径均修好。
- poll：`GET /api/nodes` 的 `last_seen` 为 2026-11-12T04:32:57+00:00（新鲜）；agent 日志 `ovpn-agent 0.1.0 started: panel=https://172.26.15.152:8443 node=lightsail (poll every 5s, outbound only)`；journal 无 401。
- 命令链：`POST /api/cmd {"node":"lightsail","action":"get_status"}` → **202**（cmd_id 63b187d7…，queued）；约 6 秒后 `GET /api/cmd/<id>` → **done**，error null；result 含 openvpn running=true pid 420040（与服务端一致）、sk5 enabled=false。
- 本轮测试侧事故（已记取教训）：第一版安装脚本用未加引号的 heredoc（`<<EOSH`），`"$PW"` 在写文件时就被外层 shell 展开成空串，登录 401、安装 EXIT=1；改 `<<'EOSH'` 后一次通过。含明文密码的旧脚本文件已删。

## 5. S1 直连态（UDP 1194）—— 通过（首次即通，零手工 FORWARD）

- 客户端（alice，netns vpntest，`--float`，remote 改为 LAN IP 172.26.15.152——机内 netns 发往公网 IP 会经 ens5 出网关发夹回不来，属云环境限制；出厂默认 remote 已在 §3 验为公网 IPv4）：**首次即通**，`Initialization Sequence Completed`（04:33:26），tun0 10.8.0.2/24，redirect-gateway 路由就位。安装器自带的 FORWARD 规则之外未加任何手工规则。
- 数据面（direct）：`curl ifconfig.me` → **16.146.199.68**；`dig @1.1.1.1 ifconfig.me` → 34.160.111.145 有回包；NTP UDP：216.239.35.4 回 **48 字节** 11.8ms、162.159.200.1 回 **48 字节** 5.9ms。UDP 数据面通过。
- **BUG-9 第五次复验——修好**：部署态原始日志（逗号 v2，13 段）为 `CLIENT_LIST,alice,10.200.0.2:39131,10.8.0.2,,3634,3548,2026-11-12 04:33:26,1794458006,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users` = **1**；`clients`=[{name: alice, real_address: 10.200.0.2:39131, virtual_address: 10.8.0.2, bytes_received: "3634", bytes_sent: "3548", connected_since: "2026-11-12 04:33:26"}]——逐字段一致；`/api/openvpn/users` 的 alice `online: true`、bob `online: false`。BUG-9 五轮终结。

## 6. S2 落地态（SK5 开）—— 通过（TCP+UDP 均走 SK5，双日志为证）

- 开启：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → 200；sing-box active；`ip rule` 有 `from 10.8.0.0/24 lookup 100`；table 100 为 `default via 10.9.0.1 dev tun1`；`ip route get 1.1.1.1 from 10.8.0.1` → `dev tun1 table 100`；tun1 UP。alice 的隧道在开启前后未断（同一会话持续）。
- 面板 `POST /api/sk5/test` → **tcp_ok: true、udp_ok: true**（native 模式，TCP 延迟 78.4ms）。
- `policy_routing_active: true`——本次 table 100 有经 tun1 的有效默认路由，旗标与实际一致（R4-P2-1 的 SK5 开态无误报；SK5 关态见 §3 为 false）。
- 客户端 TCP（经 SK5）：`curl --resolve ifconfig.me:80:34.160.111.145 http://ifconfig.me` 与 HTTPS 同式均回 **16.146.199.68**；sing-box 日志同秒有 `outbound/socks[bought-sk5] … to 34.160.111.145:80` 与 `:443`；dante 日志同秒有 `tcp/connect … 127.0.0.1.11080 -> 34.160.111.145.80` 与 `:443`——TCP 确实走了 dante（SK5 替身）。出口 IP 不变属预期：替身与面板同机，S1/S2 出口恒为 16.146.199.68，链路证明以路由表 + 双日志为准（R1 已定口径）。
- 客户端 UDP（经 SK5）：NTP 到 216.239.35.4 回 **48 字节** 20.0ms；sing-box 日志有 `outbound/socks[bought-sk5] … outbound packet connection to 216.239.35.4:123`；dante 日志有 `udp/udpassociate`。UDP 走 SK5 为证。

## 7. S3 断网保护（杀 dante）—— 通过（流量全断、无直连回落、自动恢复、隧道不断）

- 杀 dante（`systemctl stop danted`，inactive）：客户端 TCP `curl --resolve … http://ifconfig.me` → **exit 56**（Recv failure）；NTP UDP 到 216.239.35.4 → **TimeoutError**；**无直连回落**（curl 不是成功、是失败——fail-closed 成立）。隧道未断（同一客户端 PID 422137，tun0 仍在）。
- 面板 `/api/status`：kill 期间 **egress.ip = null**（`{'error': None, 'ip': None, 'latency_ms': None, 'via_sk5': True}`），诚实报空。
- 恢复（`systemctl start danted`，active）：客户端 TCP 立即回 **16.146.199.68**，NTP 回 **48 字节** 16.1ms。隧道全程未断：同一 PID 422137，client.log 里 `Initialization Sequence Completed` 仅出现 1 次、SIGUSR1 0 行——无重连、无重拨。

## 8. BUG-1 四步序列 + R4-P1-1 复核 —— 序列本身通过，但随后撞出新 bug（R4-BUG-1，高）

- 序列（每步后静置 3 秒再查 `systemctl is-active` + `/api/status` + `ip route get … from 10.8.0.1` + table 100）：
  - Step 1 `POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → 200，active，singbox_running=true，enabled=true，policy=true，tun1 UP，`1.1.1.1 from 10.8.0.1 dev tun1 table 100`；
  - Step 2 `POST /api/sk5 {"enabled":false}`（单字段）→ 200，active，singbox_running=true，tun1 UP，路由已回 `via 172.26.0.1 dev ens5`、table 100 空——**disable 后 sing-box 仍在 direct 模式跑，R3-BUG-1 修好**。但同次 `/api/status` 仍报 `enabled=true policy=true`（见下注）；
  - Step 3 enable → 200，active，enabled=true，policy=true，路由回 tun1/table 100；
  - Step 4 disable → 200，active，enabled=false，policy=false，路由回 ens5、table 100 空；
  - Step 5 无操作保存（已是禁用态再 `{"enabled":false}`）→ **200**，active，tun1 UP——**R4-P1-1 的无操作保存 500 在真机上已修**（O 路“模式变化才重起”生效；第 5 步无 stop/start 对，见 journal）。
- 注：Step 2 的 `enabled=true` 是 `/api/status` 的 10 秒缓存假象（R1 P1-1 已知行为）：同次内核路由已是直连、后续新鲜读取（Step 4 及之后）均为 enabled=false；不立案。

### R4-BUG-1（高，新发现）：连续 6 次模式切换重起触发 systemd 启动限流，sing-box 被钉死在 failed 态；面板报 500 但盘上已写 enabled=true，之后裸重开是无操作短路、策略路由永不恢复，流量静默直连

- 现象：序列结束后我按计划重开 SK5（`POST /api/sk5 {host,port,enabled:true}`）→ **500**；`systemctl is-active openvpn-sk5-singbox` = **failed (Result: start-limit-hit)**。再调一次重开仍 500。盘上 `sk5.json` 已是 `enabled: true`，渲染出的 `sing-box.json` 已是 `final: bought-sk5`，但策略路由全无（无 rule 100、table 100 空），VPN 源走 ens5 直连。
- 根因（journal 双证）：单元 `StartLimitIntervalSec=120 / StartLimitBurst=5`（D 路为修 BUG-3 加的防崩溃循环护栏）。每次 enable/disable 都做一次 systemd stop+start；journal 里 04:33:58（S2 开）→ 04:34:54 → 04:34:57 → 04:35:02 → 04:35:06 共 5 次成功 Started，第 6 次（04:35:28 重开）被限流拒绝：`Failed with result 'start-limit-hit'`。面板的 `_start_singbox()` 不做 `reset-failed`，单元钉死在 failed 态，后续启动一律被拒；同时 `set_sk5` 在重起前已写盘 enabled=true——500 是误报之外的状态谎言。
- 第二阶（更严重）：手工 `systemctl reset-failed && systemctl start` 把 sing-box 拉起后（SK5 配置在跑），再调面板重开 → **200**，但 `policy_routing_active: false`、无 rule 100、table 100 空、路由仍走 ens5；客户端 curl 仍通（rc=0），sing-box `bought-sk5` 日志 0 条、dante 0 连接——**流量在面板宣称“SK5 已启用、via_sk5=true”的情况下静默直连**。原因是 O 路的“模式变化才重起”把“已是启用态”的重开当成无操作短路：重起跳过，连带策略路由的（重）应用也被跳过。disable→enable 走完整模式变化才能恢复（本轮实测：disable 200 → enable 200 → policy=true、rule 100 + table 100 恢复、dante 15 条 tcp/connect，流量回 SK5）。
- 影响：① 用户调试时多点几次 SK5 开关就会把出口守护进程钉死，面板给 500、盘上却写 enabled=true，状态与现实分裂；② 钉死后即便手工拉起进程，面板重开也只报 200 不恢复策略路由，流量静默直连——kill-switch 的承诺在“已启用”宣称下被悄悄绕过；③ 面板自身没有任何恢复路径（无 reset-failed、无策略重应用入口），必须 SSH 上机或碰巧走一次 disable→enable。
- 本轮处理（测试侧恢复，非产品修复）：`systemctl reset-failed openvpn-sk5-singbox && systemctl start` 拉起进程，再经面板 disable→enable 恢复策略路由；随后矩阵继续。产品本身未动。
- 关联：R4-P1-1 的同族——O 路修“保存即重起”时只修了“何时重起”，没修“重起失败怎么办”与“重开短路时策略谁来补”。

## 9. S4 TCP 备模式（443）—— 通过（BUG-14 修好，S1/S2 各重跑一次）

- **BUG-14 修好**：`POST /api/openvpn/server {"proto":"tcp","port":443,"allow_port_change":true}` → **HTTP 200**。`POST /api/openvpn/restart` → 200（新 pid 424286）。TCP 443 监听，UDP 1194 监听消失，`/api/status` 为 proto=tcp port=443 running=true；新下载的 alice.ovpn 为 `proto tcp / remote 16.146.199.68 443`（默认 remote 仍是 IPv4 公网）。
- S2-TCP（SK5 开）：新 TCP 客户端首次即通（04:37:44，tun0 10.8.0.2/24）；curl → 16.146.199.68；NTP → 48 字节 27.4ms；dante 日志同窗口 26 条 `tcp/connect`/`udpassociate`——TCP+SK5 链路在 TCP 模式下同样成立。
- BUG-9（TCP 模式）：原始日志 `CLIENT_LIST,alice,10.200.0.2:46762,10.8.0.2,,4518,4411,2026-11-12 04:37:44,1794458264,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users`=**1**，`openvpn.detail.clients`=[{name: alice, real_address: 10.200.0.2:46762, virtual_address: 10.8.0.2, bytes_received: "4518", bytes_sent: "4411", connected_since: "2026-11-12 04:37:44"}]——逐字段一致（注：客户端列表在 `openvpn.detail.clients` 下，不在顶层 `openvpn.clients`；我第一次只读了顶层键得 null，是我读键错、非产品问题）。BUG-9 在 UDP 与 TCP 两种模式下均修好。
- S1-TCP（SK5 关）：`POST /api/sk5 {"enabled":false}` → 200；TCP 客户端 curl → 16.146.199.68，NTP → 48 字节 23.3ms，dig @1.1.1.1 → 34.160.111.145。关后即读 `/api/status` 仍报 enabled=true（又是 10 秒缓存）；50 秒后重读为 enabled=false、policy=false、无 rule 100、table 100 空、路由走 ens5——disable 确实生效，S1-TCP 的直连结论以路由为准（dante 计数窗口与 S2-TCP 重叠，不作区分证据）。

## 10. BUG-15/16 默认重跑（SK5 开 + TCP 443 部署，无环境变量）—— 通过

- `bash install.sh`（04:39:47 开始，无 OVPN_PROTO/OVPN_PORT）：**完成横幅已印、日志无 ERROR**（EXIT=0，同 S0 口径）；继承行：`inheriting deployed entry port from /etc/openvpn/server/server.conf (proto=tcp port=443; explicit OVPN_PROTO/OVPN_PORT still wins)`；横幅 `proto=tcp port=443 … (entry port inherited from existing server.conf)`；server.conf 仍为 `port 443 / proto tcp`——**R3-BUG-6（exit 127）与 BUG-16（不继承）双双修好**。
- 健康门禁：openvpn/singbox/panel 三稳态门全过（restarts=0）；`panel health gate passed (login + /api/status 200)`；`forwarding gate passed (SK5 mode; VPN source routes via table 100: 1.1.1.1 from 10.8.0.1 dev tun1 table 100 …)`——**BUG-15（门禁不认 SK5 开态）修好**，SK5 开时不再误报 EXIT=1。
- 重跑后：五服务 + agent 全 active，healthcheck.timer active；TCP 443 监听（openvpn 同一 PID 424286，未重启）；`/api/status` proto=tcp port=443 running=true online=1，sk5 enabled=true policy=true，egress via_sk5=true；rule 100 + table 100 在位；客户端 PID 424353 全程未断（`Initialization Sequence Completed` 仅 1 次），重跑后 curl 仍通。原地升级路径打通。

## 11. BUG-3 从 /opt 重跑（删源树后）—— 未通过（R4-BUG-2，高）

- `rm -rf /root/openvpn-sk5-panel` 后，从 `/opt/openvpn-sk5-panel` 跑 `bash install.sh`：**死在装树拷贝步，无完成横幅**。日志末 5 行全是 `cp: '/opt/openvpn-sk5-panel/agent' and '/opt/openvpn-sk5-panel/agent' are the same file`（agent/core/egress/panel/systemd 各一）；脚本 `set -e` 下 cp 返回 1 即 abort，单元安装步根本没走到。
- 根因：安装器装树命令是 `cp -a "$SCRIPT_DIR"/{agent,core,egress,panel,systemd,…} /opt/openvpn-sk5-panel/`；从 /opt 自身跑时源与目标是同一目录，cp 拒绝自拷。M 路修 R3-BUG-3 只补了拷贝清单里的 `systemd/`，没处理“源树即安装树”的自拷情形——R3-BUG-3 的用户场景（删源树后从 /opt 重跑升级）仍是死的，只是死法从“缺 systemd/ 目录”换成了“自拷 abort”。files 门禁的静态格过了，活路没通。
- 影响：源树删掉后（或只剩 /opt 副本时），文档化的升级/重装路径无法执行；修法是拷贝前判 `$SCRIPT_DIR` 与目标是否同一目录（是则跳过拷贝），或 cp 加容错。
- 本轮处理：重跑 abort 在服务重启之前，三服务仍 active、客户端 PID 424353 未断；部署本身无损。未再试其他重跑路径——题面就是从 /opt 重跑。

## 12. verify.sh 全绿 —— 未全绿：PASS=17 FAIL=1 SKIP=4（1 个 FAIL 是门禁 bug）

- 第一次跑（SK5 开态，04:44:25）：**PASS=17 FAIL=1 SKIP=4**。17 个 PASS 含 files（含 5 个 systemd 单元）、install-copies-agent、installed-agent-tree、sing-box-version 1.11.15、sing-box-config check 通过、starter-template-consistency、sing-box-steady（restarts=0）、panel-login/status 200、**agent-bundle（R3-BUG-2 修好）**、install-agent-script、user-ovpn、stub-socks5。4 个 SKIP 全是 SK5 开态下为保护真实配置而跳过的 toggle 系格（sk5-toggle、sk5-egress-ip、sk5-disable、sk5-enable-endpoint）。
- 唯一 FAIL：`direct-forwarding -- FORWARD rules present but VPN source route lookup wrong: 1.1.1.1 from 10.8.0.1 dev tun1 table 100`。
- 定性：**门禁 bug，非产品 bug**（R4-BUG-3，中，R2-BUG-15 同族）：verify.sh:700-722 的 `direct-forwarding` 格无条件要求 VPN 源走 `$FWD_WAN`（ens5）且不走 table 100；SK5 开时路由正确地走 tun1/table 100，该格按构造就不可能通过。install.sh 的转发门禁（H 路）已按模式分支，verify.sh 这格没跟上；且脚本一面以“保护真实 SK5”为由跳过 toggle 测试，一面又按 SK5 关断言路由——自相矛盾。修法：SK5 开时该格 SKIP 或按模式分支期望值。
- 另记：verify.sh 自带测试在面板上建了一个 `verify-1794458665` 用户（user-ovpn 格），待收尾时吊销清理。

## 13. verify.sh 第二轮（SK5 关，04:48:24）—— PASS=21 FAIL=2 SKIP=0；两 FAIL 同一门禁 bug（R4-BUG-4）

- 第二轮（先经面板关 SK5，隔 90 秒再跑，让 toggle 测试走 stub）：**PASS=21 FAIL=2 SKIP=0**。direct-forwarding 本轮 PASS（路由走 ens5）——反证 §12 的 FAIL 是状态依赖的；toggle 系三格 PASS（sk5-disable、sk5-egress-ip、sk5-enable-endpoint）；files/agent-bundle/install-agent-script/user-ovpn/stub-socks5 全 PASS。
- 两 FAIL 同一根因（**R4-BUG-4，中，门禁 bug，R3-BUG-4 同族漏网**）：
  - `sk5-toggle-on -- panel said enabled but routing did not switch: rule=1 table100=1 | vpn: 1.1.1.1 from 10.8.0.1 dev tun1 table 100 …`——门禁自己的 detail 已证明路由切过去了（rule=1、table100=1、vpn 走 tun1 table 100），却判 FAIL。
  - `egress-crosscheck`——`egress/test-egress.sh` §3 同款 FAIL（其余 §1/2/4/5/6 全 PASS，链路本身是通的）。
  - 根因（机上直接复现）：`route_checks on`（verify.sh:579-603）与 test-egress.sh §3 都断言 `ip route get 1.1.1.1 from 10.8.0.1` 的输出含 `via 10.9.0.1 dev tun1`；但内核对点对点 tun 路由只印 `1.1.1.1 from 10.8.0.1 dev tun1 table 100 uid 0`——**没有 `via`**（本轮机上实测：via-grep NO MATCH、table-grep MATCH）。N 路修 R3-BUG-4 只改了源地址（10.8.0.2→10.8.0.1），没改这条永远匹配不上的期望串；源 bug 盖住了它，源一修它就露出来。修法：断言改为 `dev tun1` + `table 100`（与内核实际输出一致）。
- R4-BUG-3（§12 的 direct-forwarding）与 R4-BUG-4 合起来：verify.sh 在 SK5 开时因模式不知情红一格、在 SK5 关时因期望串错误红两格——**两种状态下都无法全绿**。两处都是门禁自身 bug，产品数据面在本轮两轮里全部是通的。

### R3-OBS-1（偶发瞬时 401）—— 本轮未复现

- 全程登录与 API 调用：登录 200（约 15 次）、各 POST/GET 200，仅有的非 200 是 R4-BUG-1 的两次 500（有明确机制，非偶发）与我测试侧传参错的一次 400（`{"username": …}`）。access log 里无 401。观察关闭：本轮无复现。

## 14. 结论 —— 不能交付

- S0–S4 数据面全过：S0 安装横幅 + 五服务 active、BUG-2 下载路径再次通过；S0-agent 两步走 + --node-name、poll 新鲜、命令链 202→done；S1 UDP 首次即通；S2 TCP+UDP 均走 SK5（双日志）；S3 杀 dante 全断无回落、恢复后隧道不断；S4 TCP 443 下 S1/S2 重跑全过。
- R3 的 6 项复验：R3-BUG-1（disable 杀 sing-box）修好（四步序列全过、disable 后 direct 模式仍在跑）；R3-BUG-2（agent-bundle SIGPIPE）修好（两轮均 PASS）；R3-BUG-3（装树漏 systemd/）**未真修**——/opt 树里 systemd/ 已有、files 格已过，但从 /opt 重跑仍死（见 R4-BUG-2）；R3-BUG-4（路由核对源地址）修好一半——源改对了，但期望串本身是错的（见 R4-BUG-4）；R3-BUG-5（默认 remote IPv6）修好（出厂 remote 即 16.146.199.68）；R3-BUG-6（默认重跑 exit 127）修好（BUG-15/16 默认重跑 EXIT=0、继承 tcp/443、门禁按 SK5 模式分支通过）。
- AUDIT-R4 的 5 项复验：R4-P1-1 的无操作保存 500 在真机上已修（Step 5 返回 200、无重起）；R4-P2-1 的旗标在 SK5 开/关两态均与实际一致（开 true 且有有效路由、关 false）；R4-P2-2（README 清单漏 systemd/）文档面已补；R4-P2-3（≤255 校验）在 install.sh:454-457 代码面已补（未在真机上投毒测试）；R4-P2-4 的门禁补格在 verify-integration 侧，未在本轮真机 verify.sh 里复核。
- 本轮新发现 4 项（2 产品高 + 2 门禁中）：
  - **R4-BUG-1（高，产品）**：连续 6 次模式切换重起触发 systemd 启动限流（StartLimitBurst=5/120s），sing-box 钉死 failed 态、面板 500 但盘上已写 enabled=true；手工拉起后裸重开是无操作短路、策略路由永不恢复，流量在“SK5 已启用”宣称下静默直连。
  - **R4-BUG-2（高，产品）**：删源树后从 /opt 重跑 install.sh，装树拷贝自拷 abort（`cp: … are the same file`），无完成横幅、单元安装步没走到；R3-BUG-3 的用户场景仍是死的。
  - **R4-BUG-3（中，门禁）**：verify.sh `direct-forwarding` 格按模式不知情断言直连路由，SK5 开时按构造必红。
  - **R4-BUG-4（中，门禁）**：`route_checks on` 与 test-egress.sh §3 断言 `ip route get` 输出含 `via 10.9.0.1 dev tun1`，内核对点对点 tun 只印 `dev tun1 table 100`——该串永远匹配不上；R3-BUG-4 的源修好后它才露出来。
- R3-OBS-1（偶发瞬时 401）本轮未复现（约 15 次登录全 200，仅有的 500 是 R4-BUG-1 的有机制失败）。
- **最大风险**：R4-BUG-1 让面板自己的开关序列能把出口守护进程钉死并悄悄放行直连流量；R4-BUG-2 让源树删掉后的升级路径仍是死的。两者不修，不能交付。
- 收尾态（04:50 UTC）：TCP 443 部署，五服务 + agent + dante 全 active，SK5 开（dante 替身），rule 100 + table 100 在位，alice 客户端 PID 424353 在线、数据面通；两个 verify-* 测试用户已吊销（alice/bob 有效）；FLMX 未碰。测试产物：`/root/r4/`（alice.ovpn、client 日志）、`/root/r4-install.log`、`/root/r4-reinstall.log`、`/root/r4-opt-reinstall.log`、`/root/r4-verify.log`、`/root/r4-verify2.log`、`/root/ovpn-r4.tar.gz`。
- 未验（保持原判，不 claim）：Cloudflare 真实 `wrangler deploy`（KV id 仍为占位，须用户登录）；AUDIT-R5（O/P 修复后的全量复审）；R4-P2-3 的逐段 ≤255 在真机上的投毒测试（形状校验只在代码面确认）；verify-integration.sh 的 P2-4 新补格在真机上的变异红证。

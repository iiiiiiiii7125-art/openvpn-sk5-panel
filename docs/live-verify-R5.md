# OpenVPN 接 SK5 落地 · 真机复跑验证报告（第五轮 R5）

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（Q/R/S/T 修复后＋主控修的 verify.sh 门禁双机制检查的最新树）。
> 验证人：真机复跑验证路（第五轮）。日期：2026-11-12。
> 前情：第一轮见 [live-verify.md](live-verify.md)（S0–S4 全过，9 个 bug，4 阻塞）；第二轮见 [live-verify-R2.md](live-verify-R2.md)（S0–S4 全过，新发现 7 个 bug，3 阻塞）；第三轮见 [live-verify-R3.md](live-verify-R3.md)（S0–S4 全过，BUG-9 第四次复验修好，新发现 6 项）；第四轮见 [live-verify-R4.md](live-verify-R4.md)（S0–S4 全过，新发现 4 项：R4-BUG-1 限流钉死＋静默直连、R4-BUG-2 自拷 abort、R4-BUG-3/4 门禁 bug）。

## 0. 树版本（本次装机所用）

| 文件 | mtime (UTC) | 说明 |
|---|---|---|
| install.sh | 2026-11-12 05:59:49 | R 路：readlink -f 自拷跳过（R4-BUG-2）；log() 定义在 :39（R3-BUG-6 已修） |
| panel/app.py | 2026-11-12 06:02:03 | S 路：409/404 映射（R5-P2-1，:1173/:1195/:1199）＋ via_sk5 回退 |
| panel/templates/index.html | 2026-11-12 02:49:17 | L 路（未动） |
| egress/sk5_manager.py | 2026-11-12 06:04:05 | Q 路：reset-failed（:289）＋先成功后写盘＋已启用态重开补策略（repaired） |
| verify.sh | 2026-11-12 07:29:19 | T 路：direct-forwarding 按模式分支；主控：install-copies-agent 双机制兼容检查（_COPIES_AGENT） |
| verify-integration.sh | 2026-11-12 06:11:22 | Q 路：§4d 四格（风暴＋补策略），总数 23→27 |
| core/openvpn_manager.py | 2026-11-12 06:01:40 | S 路：_exists()（:156）＋ init_pki force 透传＋三类用户异常 |
| core/easyrsa.sh | 2026-11-12 06:01:36 | S 路：init 接 --force（R5-P2-2） |
| egress/test-egress.sh | 2026-11-12 06:02:03 | T 路：route-get 断言改 dev tun1 + table 100 |

树稳定检查：07:32:03 核查时最新改动为 verify.sh（07:29:19），须满 15 分钟稳定（07:44:19 UTC）后打包传机。**07:44:45 复核：安装相关文件（agent/core/egress/panel/systemd/install.sh/verify.sh/verify-integration.sh/README.md）自 07:29:19 后无改动，稳定 15 分 26 秒，门过**。注：并行在跑的 AUDIT-R6 此时正在写 `docs/audit/AUDIT-R6.md`（07:44:18 刚落盘一次），docs/ 不在安装拷贝清单内，故本次打包**只含安装子集**（agent core egress panel systemd install.sh verify.sh verify-integration.sh README.md），不含 docs/ 与 `__pycache__`，以免把审计进行中的报告打进安装包。

**打包（07:44:45 UTC）**：传包走 scp（R4 同款；remote-storage 在 R4 两次失败，不再试）。`ovpn-r5.tar.gz`：46 条目，273,048 字节，sha256 `4b528a4bc063e8f7fbf6f0440abe107bcd66a885a84f9e8dcabb921dd2d1b64b`（机上核对一致）；install.sh sha256 `977054c388c938928368d10a59b1c0c210bff53fd621cefc88fc45ffbd2313b8`。

## 1. 地面真值（Lightsail 现状，测试前实测，07:33 UTC）

- 机上是**第四轮收尾态**：七服务全 active（openvpn-server@server PID 424286、openvpn-sk5-singbox PID 430674、openvpn-sk5-panel PID 420173、openvpn-sk5-policy、openvpn-sk5-healthcheck.timer、ovpn-agent、danted PID 422634），TCP 443 部署，SK5 开（dante 替身），监听 443/tcp、11080、8443。
- 第四轮残留全部在位，**重装前必须清除**：
  - netns `vpntest` 仍在（第四轮残留）；
  - `/root/r4/` 测试产物在位（alice.ovpn、client 日志）＋ `/root/r4-*.log` ＋ `/root/ovpn-r4.tar.gz`；
  - alice 客户端 PID 424353 仍在跑（第四轮 TCP 客户端）；
  - `/opt/openvpn-sk5-panel/` 为第四轮装树（含 agent/ 与 systemd/，5 个单元文件齐全）。
- FLMX 相关进程同机在跑（sing-box PID 53637，`/etc/flmx_agent/kernels/singbox/`），**一律不碰**；`/root/flmx-panel` 不动。

## 2. 清场（全新重装前，07:45–07:48 UTC）

- 客户端 PID 424353（第四轮 TCP 客户端）按精确 PID 杀掉，已确认无此进程；四服务已停（openvpn/singbox/panel/agent 全部 inactive，dante 保留，active）。
- 绕行已清：FORWARD 链清至只剩 ts-forward/DOCKER-USER/DOCKER-FORWARD（策略 DROP，删掉安装器自加的两条 tun0 规则与 policy-routing 的两条 tun0↔tun1 规则）；系统信任库无 ovpn 证书（R3 已清，本轮复核无残留）；无 systemd drop-in 残留；netns `vpntest` 已删。
- 状态已 wipe：`/root/openvpn-sk5-panel`、`/opt/openvpn-sk5-panel`、`/opt/ovpn-agent`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/ovpn-agent` 全删；sing-box 与 tun2socks 二进制已删（逼安装器走下载路径，复验 BUG-2）；`/root/r4/`、`/root/r4-*.log`、`/root/ovpn-r4.tar.gz` 已清。
- 新树已就位：`/root/openvpn-sk5-panel/`（R5 包解压），install.sh sha256 与打包值一致（`977054c3…`）。
- 清场后核对：只剩 tailscale0 一个 tun 设备、无 1194/443/8443 监听、`/opt/openvpn-sk5-panel` 与 `/etc/openvpn-sk5-panel` 不存在。
- 小事故（测试侧）：清场脚本用 `tee /root/r5/cleanup.log` 时 `/root/r5` 尚未创建（mkdir 在脚本内、tee 在脚本外），tee 报错、日志未落机；清场命令本身全部执行成功，输出以本轮 tail 为准。教训：先建日志目录再 tee。

## 3. S0 基线：安装 + 建服务 + 建用户 —— 通过（默认路径，全程零绕行）

- `bash install.sh`（UDP 1194 默认）：**完成横幅已印、日志 0 个 ERROR**（EXIT=0 的判定与 R3/R4 同口径：横幅 + 无 ERROR；nohup 后台跑故 `$?` 未直接捕获），无环境变量绕行、无手工规则、无手工信任库。apt + pip + PKI 全新生成；sing-box 1.11.15 与 tun2socks 2.7.0 因二进制已删而走下载，**均 `sha256 OK`**（BUG-2 下载路径本轮再次真机通过）。
- 五单元全 active：openvpn-server@server（PID 488382，UDP 1194 监听，tun0 UP）、openvpn-sk5-singbox（tun1 UP，10.9.0.1/30，direct 模式）、openvpn-sk5-panel（PID 488562，8443 监听）、openvpn-sk5-policy、openvpn-sk5-healthcheck.timer；restarts 全 0（BUG-3 修好）。
- **BUG-10 真机修好**：`/opt/openvpn-sk5-panel/agent/` 在位（agent.py、install-agent.sh、ovpn-agent.service）；**R3-BUG-3 真机修好**：`/opt/openvpn-sk5-panel/systemd/` 在位，5 个单元文件齐全。
- 面板登录 200；`/api/status` 200：openvpn running（UDP 1194，pid 488382，status_log `/var/log/openvpn/openvpn-status.log`），online_users 0（无客户端时正确），egress IPv6 直连，SK5 未启用，`singbox_running: true`，sk5 块 `policy_routing_active: false`（SK5 关时旗标为 false，R4-P2-1 一致）。顶层 `remote_ip` 为 `16.146.199.68`、`remote_warning` 为 null——R4 §3 的顶层 null 缺口本轮未现。
- **R3-BUG-5 真机修好**：默认 `.ovpn` remote 为 **`16.146.199.68 1194`（IPv4 公网）**；`GET /api/openvpn/public-ip` 返回 `16.146.199.68`。M 路的 `-4` 探测生效。
- 用户：alice、bob 创建均 200；`GET /api/openvpn/users` 只列 alice、bob（无 CA 条目，BUG-4 修好），各带 DER 序列号（alice `E69135879AAE28CC279C5C8A50879EBB`、bob `171EA5AD5788E53F50B7048F914F62C5`）；`.ovpn` 下载 200（8612 字节），`proto udp / cipher AES-256-GCM / auth SHA256`，CN 各为用户名（BUG-7 修好）。

## 4. S0-agent：节点注册 + agent 安装 + 命令链 —— 通过（BUG-11/12 默认路径修好）

- 注册：`POST /api/nodes {"name":"lightsail","panel_url":"https://172.26.15.152:8443"}` → 201，token 43 字符（一次性返回，未写报告）。
- 安装命令（按前端 `buildInstallCommand` 拼出的两步走命令逐字执行，未改动——脚本与 sha256 经 `https://127.0.0.1:8443` 取，install-agent.sh 以 `--panel-url 'https://172.26.15.152:8443' --token '…' --node-name 'lightsail'` 运行；取包地址用环回是测试侧传输细节，脚本内容同一端点、sha256 已校验一致）：`curl -ksSL …/install-agent.sh -o /tmp/install-agent.sh && curl -ksSL …/install-agent.sh.sha256 -o /tmp/install-agent.sh.sha256 && cd /tmp && sha256sum -c install-agent.sh.sha256 && bash /tmp/install-agent.sh --panel-url 'https://172.26.15.152:8443' --token '…' --node-name 'lightsail'` → **EXIT=0**。`install-agent.sh: OK`；TOFU 自动把面板自签证书钉到 `/etc/ovpn-agent/panel-ca.pem`；bundle 下载后 sha256 OK；`/etc/ovpn-agent/config.json` 0600；`ovpn-agent is ACTIVE (node=lightsail)`。**全程零手工信任库、零手工拷文件**——BUG-11 与 BUG-12 默认路径均修好。
- poll：`GET /api/nodes` 的 `last_seen` 为 2026-11-12T07:50:22+00:00（查时 07:50:26 UTC，4 秒前，新鲜）；journal 无 401。
- 命令链：`POST /api/cmd {"node":"lightsail","action":"get_status"}` → **202**（cmd_id 5dc4513f…，queued）；约 8 秒后 `GET /api/cmd/<id>` → **done**，error null；result 含 openvpn running=true pid 488382（与服务端一致）、sk5 enabled=false。
- 本轮测试侧事故（已记取教训）：第一版安装脚本把“token 脱敏 sed”与安装管道写在同一条远程命令里，sed 的 `$(cat token.txt)` 在管道启动前就展开（当时 token 文件尚未生成）→ 空模式致 sed 报错、SIGPIPE 杀死安装流程，agent 没装上；重跑时注册撞 409（节点已存在）又退 1。改成分步跑（先注册存 token、再用存量 token 走安装步）后一次通过。含 token 的日志已脱敏处理，token 本身只存 `/root/r5/token.txt`（0600），不写报告。

## 5. S1 直连态（UDP 1194）—— 通过（首次即通，零手工 FORWARD）

- 客户端（alice，netns vpntest，`--float`，remote 改为 LAN IP 172.26.15.152——机内 netns 发往公网 IP 会经 ens5 出网关发夹回不来，属云环境限制；出厂默认 remote 已在 §3 验为公网 IPv4）：**首次即通**，`Initialization Sequence Completed`（07:51:11），tun0 10.8.0.2/24，redirect-gateway 路由就位。安装器自带的 FORWARD 规则之外未加任何手工规则。
- 数据面（direct）：`curl ifconfig.me` → **16.146.199.68**；`dig @1.1.1.1 ifconfig.me` → 34.160.111.145 有回包；NTP UDP：216.239.35.4 回 **48 字节** 14.2ms、162.159.200.1 回 **48 字节** 6.6ms。UDP 数据面通过。
- **BUG-9 第六次复验——修好（UDP 模式）**：部署态原始日志（逗号 v2，13 段）为 `CLIENT_LIST,alice,10.200.0.2:58274,10.8.0.2,,3899,3749,2026-11-12 07:51:11,1794469871,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users` = **1**；`clients`=[{name: alice, real_address: 10.200.0.2:58274, virtual_address: 10.8.0.2, bytes_received: "3899", bytes_sent: "3749", connected_since: "2026-11-12 07:51:11"}]——逐字段一致；`/api/openvpn/users` 的 alice `online: true`、bob `online: false`。

## 6. S2 落地态（SK5 开）—— 通过（TCP+UDP 均走 SK5，双日志为证）

- 开启：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → 200；sing-box active；`ip rule` 有 `from 10.8.0.0/24 lookup 100`；table 100 为 `default via 10.9.0.1 dev tun1`；`ip route get 1.1.1.1 from 10.8.0.1` → `dev tun1 table 100`；tun1 UP。alice 的隧道在开启前后未断（同一会话持续）。
- 面板 `POST /api/sk5/test` → **tcp_ok: true、udp_ok: true**（native 模式，TCP 延迟 71.3ms）。
- `policy_routing_active: true`——本次 table 100 有经 tun1 的有效默认路由，旗标与实际一致（R4-P2-1 的 SK5 开态无误报）。
- 客户端 TCP（经 SK5）：`curl --resolve ifconfig.me:80:34.160.111.145 http://ifconfig.me` 与 HTTPS 同式均回 **16.146.199.68**；sing-box 日志同秒有 `outbound/socks[bought-sk5] … to 34.160.111.145:80` 与 `:443`；dante 日志同秒有 `tcp/connect … 127.0.0.1.11080 -> 34.160.111.145.80` 与 `:443`——TCP 确实走了 dante（SK5 替身）。出口 IP 不变属预期：替身与面板同机，S1/S2 出口恒为 16.146.199.68，链路证明以路由表 + 双日志为准（R1 已定口径）。
- 客户端 UDP（经 SK5）：NTP 到 216.239.35.4 回 **48 字节** 17.7ms；sing-box 日志有 `outbound/socks[bought-sk5] … outbound packet connection to 216.239.35.4:123`；dante 日志有 `udp/udpassociate`。UDP 走 SK5 为证。
- 附记：真实客户端进程为 PID **490548**（490546 是 nohup 外壳，仍在跑；报告里“同一客户端 PID”均指 490548）。

## 7. S3 断网保护（杀 dante）—— 通过（流量全断、无直连回落、自动恢复、隧道不断）

- 杀 dante（`systemctl stop danted`，inactive）：客户端 TCP `curl --resolve … http://ifconfig.me` → **exit 56**（Recv failure）；NTP UDP 到 216.239.35.4 → **TimeoutError**；**无直连回落**（curl 不是成功、是失败——fail-closed 成立）。隧道未断（同一客户端 PID 490548，tun0 仍在）。
- 面板 `/api/status`：kill 期间 **egress.ip = null**（`{'error': None, 'ip': None, 'latency_ms': None, 'via_sk5': True}`），诚实报空。
- 恢复（`systemctl start danted`，active）：客户端 TCP 立即回 **16.146.199.68**，NTP 回 **48 字节** 20.8ms。隧道全程未断：同一 PID 490548，client.log 里 `Initialization Sequence Completed` 仅出现 1 次、SIGUSR1 0 行——无重连、无重拨。面板 egress.ip 在恢复后约 15 秒回到 **16.146.199.68**（刚恢复即读仍为 null 是 `/api/status` 的 10 秒缓存，R1 P1-1 已知行为，非产品问题）。

## 8. BUG-1 四步序列 + 无操作保存 —— 通过

- 序列（每步后静置 3 秒再查 `systemctl is-active` + 回执 + `ip route get … from 10.8.0.1` + table 100；回执是 POST 本身的新鲜值，不受 `/api/status` 10 秒缓存影响）：
  - Step 1 `POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}`（当时已是启用健康态）→ 200，active，enabled=true，policy=true，tun1 UP，`1.1.1.1 from 10.8.0.1 dev tun1 table 100`，repaired 为空——健康态裸重开是纯无操作；
  - Step 2 `POST /api/sk5 {"enabled":false}`（单字段）→ 200，active，singbox_running=true，tun1 UP，路由已回 `via 172.26.0.1 dev ens5`、table 100 空——**disable 后 sing-box 仍在 direct 模式跑，R3-BUG-1 修好**；
  - Step 3 enable → 200，active，enabled=true，policy=true，路由回 tun1/table 100；
  - Step 4 disable → 200，active，enabled=false，policy=false，路由回 ens5、table 100 空；
  - Step 5 无操作保存（已是禁用态再 `{"enabled":false}`）→ **200**，active，tun1 UP——**R4-P1-1 的无操作保存 500 在真机上已修**（O 路“模式变化才重起”生效）。
- journal 核对：Step 1–4 各一次 stop+start（共 4 次 Started），Step 5 无启停——每次模式翻转恰一次 daemon 重起，无操作保存零重起；全程 restarts=0（无崩溃重启）。
- 四步后 enabled 与 policy_routing_active 一致：开 true/true、关 false/false，无分裂。

## 9. headline-1 开关风暴（≥6 次切换＋限流钉死后裸重开补策略）—— 通过（R4-BUG-1 两阶均修好）

- **A. 风暴（8 次快速切换，面板路径）**：从禁用态起 enable/disable ×4、间隔 1 秒，**8 次全 200**；风暴后 sing-box active、restarts=0、Result=success——**Q 的 reset-failed 生效，连续切换不再钉死**（R4 时第 6 次即 start-limit-hit）。
- **C1. 人为制造限流钉死（绕过面板、直接 restart）**：`systemctl restart openvpn-sk5-singbox` 连打 6 次，第 1–4 次 active、第 5 次即 `failed (Result: start-limit-hit)`——证明 systemd 的 StartLimitBurst=5/120s 护栏仍在、风暴不死靠的是面板的 reset-failed 而非限流被拆掉。
- **C2. 面板裸重开（单字段 `{"enabled":true}`，daemon 已死）**：→ 200，daemon 回 active，rule 100 + table 100 恢复。注意：此路走面板路由的 toggle-only 分支（直调 `enable()`），回执无 `repaired` 字段——恢复靠的是 `enable()` 里的 reset-failed + 全量重起 + 策略重应用，行为正确、但无修补收据。
- **D1/D2. 策略丢失后裸重开（单字段，daemon 活着）**：手工删 rule 100 + 清 table 100 后单字段重开 → 200，策略恢复，但 journal 多一次 daemon Started（19→20）——同样是 `enable()` 全量重起的路，不是“只补策略不重起”。
- **E2. 全表单重开（`{"host","port","enabled":true}`，策略丢失）**：→ 200，`repaired: true` + `repair_detail: ['policy routing re-applied']`，**daemon 启停次数 23→23（零重起）**，rule 100 + table 100 恢复、路由回 tun1——**Q 的“只补策略不重起”分支在真机上按设计工作**。
- **E4. 全表单重开（daemon 钉死）**：再次人为钉死（第 5 次 restart 即 start-limit-hit）后全表单重开 → 200，`repaired: true` + `repair_detail: ['sing-box restarted']`，启停 27→28（恰一次），daemon 回 active、策略恢复。
- **E5. 修好后流量**：客户端 TCP 回 16.146.199.68、NTP 48 字节 16.0ms；`policy_routing_active: true`、`via_sk5: true`（且是真实路由时才为真）；同一客户端 PID 490548 全程未断、`Initialization Sequence Completed` 仅 1 次——风暴＋钉死＋两次修补全程隧道零重连。
- **收敛点（供 R6 裁定）**：R4-BUG-1 的两阶失效在行为面均已修好（风暴不死、裸重开必恢复策略），但**修补收据与零重起只走全表单保存路径**；面板的一键启用按钮（`/api/sk5/enable`）与单字段 `{"enabled":true}` 仍直调 `enable()`、每次完整重起、无 `repaired` 回执。行为正确、收据缺失、重起浪费——是 Q 简报里已留的裁定点，不是新 bug（见 §15）。
- 另纠正 §8 的一处测试侧误读：Step 5 无操作保存后我曾凭 journal 计数称“零重起”——后经对照实验（已禁用态再单字段 disable 一次）证实**单字段 disable 仍会重起 daemon**（启停 21→22，`singbox_restarted: true`）；Step 5 的 200 本身（R4-P1-1 的 500 已修）不受影响，零重起只属于全表单保存的 still-disabled 纯写盘分支。

## 10. S4 TCP 备模式（443）—— 通过（BUG-14 修好，S1/S2 各重跑一次）

- **BUG-14 修好**：`POST /api/openvpn/server {"proto":"tcp","port":443,"allow_port_change":true}` → **HTTP 200**。`POST /api/openvpn/restart` → 200（新 pid 494498）。TCP 443 监听，UDP 1194 监听消失，`/api/status` 为 proto=tcp port=443 running=true；新下载的 alice.ovpn 为 `proto tcp / remote 16.146.199.68 443`（默认 remote 仍是 IPv4 公网）。
- S2-TCP（SK5 开）：新 TCP 客户端首次即通（07:58:18，tun0 10.8.0.2/24）；curl → 16.146.199.68；NTP → 48 字节 22.0ms；dante 日志同窗口 9 条 `tcp/connect`/`udpassociate`——TCP+SK5 链路在 TCP 模式下同样成立。
- BUG-9（TCP 模式）：原始日志 `CLIENT_LIST,alice,10.200.0.2:40244,10.8.0.2,,3960,3826,2026-11-12 07:58:17,1794470297,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users`=**1**，`openvpn.detail.clients`=[{name: alice, real_address: 10.200.0.2:40244, virtual_address: 10.8.0.2, bytes_received: "3960", bytes_sent: "3826", connected_since: "2026-11-12 07:58:17"}]——逐字段一致。BUG-9 在 UDP 与 TCP 两种模式下均修好（第六次复验终结）。
- S1-TCP（SK5 关）：`POST /api/sk5 {"enabled":false}` → 200；TCP 客户端 curl → 16.146.199.68，NTP → 48 字节 43.8ms，dig @1.1.1.1 → 34.160.111.145。关后即读回执已是 enabled=false（回执新鲜；R4 的 10 秒缓存只影响 GET /api/status）；45 秒后重读 `/api/status` 为 enabled=false、policy=false、singbox_running=true、egress IPv6 直连 via_sk5=false——disable 确实生效，S1-TCP 的直连结论以路由为准（关后路由走 ens5、table 100 空）。

## 11. BUG-15/16 默认重跑（SK5 开 + TCP 443 部署，无环境变量）—— 通过

- `bash install.sh`（无 OVPN_PROTO/OVPN_PORT）：**完成横幅已印、日志 0 个 ERROR**（EXIT=0，同 S0 口径）；继承行：`inheriting deployed entry port from /etc/openvpn/server/server.conf (proto=tcp port=443; explicit OVPN_PROTO/OVPN_PORT still wins)`；横幅 `proto=tcp port=443 … (entry port inherited from existing server.conf)`；server.conf 仍为 `port 443 / proto tcp`——**R3-BUG-6（exit 127）与 BUG-16（不继承）双双修好**。
- 健康门禁：五服务 + agent 全 active，restarts 全 0；openvpn 同一 PID 494498（未重启）、panel 同一 PID 488562；`/api/status` proto=tcp port=443 running=true online=1，sk5 enabled=true policy=true，egress via_sk5=true；rule 100 + table 100 在位；客户端 PID 494575 全程未断（`Initialization Sequence Completed` 仅 1 次），重跑后 curl 仍通。原地升级路径打通。
- 注：sing-box 的 MainPID 在重跑后变了（495641）——重跑重启了出口守护进程，不影响隧道端点（openvpn 未动、客户端不断）。

## 12. headline-2 R4-BUG-2：删源树后从 /opt 重跑 —— 通过

- `rm -rf /root/openvpn-sk5-panel` 后，从 `/opt/openvpn-sk5-panel` 跑 `bash install.sh`：**完成横幅已印、日志 0 个 ERROR**（EXIT=0，同口径）。日志明示：`source tree is the installed tree (/opt/openvpn-sk5-panel); skipping tree copy`——**R 路的自拷跳过生效，R4-BUG-2 修好**；无 `are the same file` 报错。
- 重跑后：六服务全 active，5 个单元文件齐装（panel/singbox/policy/healthcheck.service/healthcheck.timer）；`/api/status` proto=tcp port=443 running=true online=1，sk5 enabled=true policy=true；客户端 PID 494575 全程未断（`Initialization Sequence Completed` 仅 1 次），重跑后 curl 仍通。R3-BUG-3 的用户场景（删源树后从 /opt 重跑升级）本轮真正打通。

## 13. headline-3 verify.sh 双态全绿 —— 未全绿：开态全绿、关态 22/1，唯一 FAIL 是门禁 bug（R5-BUG-1）

### 13.0 收尾接手时的地面真值（08:17 UTC 实测）

- 上一任 08:12:42 UTC 中断（`completed_at` 1794471162 换算；报告最后写盘 08:05:55 UTC）。接手时七服务全 active（openvpn-server@server PID 494498、panel PID 488562、singbox、policy、healthcheck.timer、ovpn-agent、danted），TCP 443 部署，SK5 开（dante 替身，`sk5.json` host 127.0.0.1 port 11080 enabled=true），监听 443/11080/8443，rule 100 + table 100 在位，netns `vpntest` 在，客户端 PID 494575 活着（tun0 10.8.0.2/24，redirect-gateway 就位）。**无需恢复，接手态即上一任收尾态。**
- 上一任已跑过 verify.sh 但未写进报告，日志在 `/root/r5/` 落盘（verify-on.log 08:06、verify-off.log 08:09、verify-off2.log 08:11、test-egress-off2.out 08:11）。本节先复核这些日志，再由我亲手重跑两态确认。

### 13.1 SK5 开态 —— PASS=18 FAIL=0 SKIP=4，ALL GREEN（两遍一致）

- 上一任 verify-on.log（08:06:06 UTC）：**PASS=18 FAIL=0 SKIP=4，VERIFY: ALL GREEN**。
- 我重跑（verify-on2.log，`bash verify.sh`，SK5 开＋dante）：**PASS=18 FAIL=0 SKIP=4，ALL GREEN**，与上一任逐格一致。18 个 PASS 含 files、install-copies-agent、installed-agent-tree、sing-box-version 1.11.15、sing-box-config check、starter-template-consistency、sing-box-steady（restarts=0）、panel-login/status 200、agent-bundle、install-agent-script、user-ovpn、stub-socks5、**direct-forwarding（SK5 开态按模式分支通过：`1.1.1.1 from 10.8.0.1 dev tun1 table 100`）**。4 个 SKIP 全是开态下为保护真实 SK5 配置而跳过的 toggle 系格（sk5-toggle、sk5-egress-ip、sk5-disable、sk5-enable-endpoint）——与 R4 同口径，属设计行为。

### 13.2 SK5 关态 —— 三遍同为 PASS=22 FAIL=1 SKIP=0，唯一 FAIL 恒为 egress-crosscheck

- 上一任 verify-off.log（08:09:00）与 verify-off2.log（08:11:42）：**PASS=22 FAIL=1 SKIP=0**，唯一 FAIL 均为 `egress-crosscheck -- egress/test-egress.sh failed`。
- 我重跑（verify-off3.log：先经面板关 SK5，隔 90 秒再跑；nohup 后台跑，因 90 秒 sleep 会断开 tssh 长连接——见 13.4 测试侧事故）：**PASS=22 FAIL=1 SKIP=0**，唯一 FAIL 同为 egress-crosscheck；其余 22 格全 PASS，含 sk5-toggle-on（rule=1 table100=1、vpn 走 `dev tun1 table 100`）、sk5-egress-ip、sk5-disable、direct-forwarding（关态走 ens5）、sk5-enable-endpoint。
- 上一任捕获的 test-egress-off2.out：§1–§5 全 PASS，§6 FAIL（`SK5 egress IP equals direct IP (2600:1f13:14d:a300:7913:f273:997e:c8b8)`），§7 SKIP，总分 5/1/1。verify.sh 的 trap 会 `rm -rf` 工作目录，故 .out 文件随运行删除——上一任的 off2.out 副本（`/root/r5/test-egress-off2.out`）是唯一留存，我已全文核对。

### R5-BUG-1（中，门禁 bug，新发现）：test-egress.sh §6 的“出口 IP 必须不同”断言在 verify.sh 的同机桩面前按构造必红

- **一手复现**：我把 verify.sh 自带的桩原样抽出（`/root/r5/stub-repro.py`，与 verify.sh:444–558 同款），127.0.0.1:1080 拉起，经面板切链到桩上（enabled=true、policy=true、rule 100 + table 100 在位），直接跑 `egress/test-egress.sh`（`/root/r5/test-egress-stub.out`）：**§1–§5 全 PASS，§6 FAIL（SK5 egress IP == direct IP == `2600:1f13:14d:a300:7913:f273:997e:c8b8`），§7 SKIP，总分 5/1/1**——与上一任 off2.out 逐格一致。
- **机制（地址族对照，同一命令窗口实测）**：direct `-4` → 16.146.199.68；direct `-6` → `2600:1f13:…`；via 桩 → `2600:1f13:…`；via dante → 16.146.199.68。本机直连 curl 优先 IPv6；桩是 Python `socket.create_connection`，解析 ifconfig.me 后同样优先 IPv6 出站，故桩上出口 IP 恒等于直连出口 IP；dante 的出站是 IPv4，故经 dante 的出口恒为 16.146.199.68。§6 只比字符串相等，不分地址族——桩的出站族与直连一致时它永远判 FAIL。
- **对照实验（同一脚本、同一机器，只换 SK5 端点）**：杀桩、经面板把链切回 dante（11080，enabled=true、policy=true），直接跑 test-egress.sh（`/root/r5/test-egress-dante.out`）：**exit 0，PASS=6 FAIL=0 SKIP=1**，§6 通过（via dante 16.146.199.68 ≠ direct `2600:1f13:…`）。产品链路在两种端点下均通（§1–§5、toggle-on、S2 双日志），红只取决于端点的出站地址族——是门禁断言的前提错，不是产品链路断。
- **影响与修法**：verify.sh 在关态下天花板就是 22/1，headline-3“双态全绿”按现有门禁达不到；开态不受影响（crosscheck 被 SKIP）。修法二选一：test-egress.sh §6 按同地址族比较（拿与 SK5 结果同族的直连 IP 作对照），或 verify.sh 在链经本地桩时 SKIP crosscheck（桩的使命是 TCP 腿＋路由，出口 IP 差值不是它的证明项）。R4-BUG-4（via 串）修好后它才露出来，同族漏网。
- **恢复**：对照实验后链已回 dante 开态；客户端 PID 494575 全程未断（curl → 16.146.199.68，NTP 48 字节 26.9ms，`Initialization Sequence Completed` 仍仅 1 次）。

### 13.3 小结

- 开态：ALL GREEN（18/0/4），direct-forwarding 的模式分支（T 路）真机通过。
- 关态：22/1，三遍一致，唯一 FAIL 是 R5-BUG-1（门禁 §6 地址族前提错）。
- headline-3 结论：**未全绿**——产品数据面双态全通，门禁在关态差一格（R5-BUG-1）。

### 13.4 测试侧事故

- 一条远程命令里放 90 秒 sleep 会断开 tssh 长连接（`client_loop: send disconnect: Broken pipe`，exit 255；disable 本身已生效，verify 未跑）。后改 nohup 后台跑＋分段轮询，不再把长等待放进单条 SSH。

## 14. headline-4/5/6：R5-P2-2 force 重建、R5-P2-1 状态码、R5-P2-3 紧权限 —— 全部通过

执行顺序：先做无破坏的 headline-5、headline-6，破坏性的 headline-4（force 重建会吊销全部用户证书）放最后；重建后逐项恢复部署并重验 S1/S2 数据面。

### 14.1 headline-5（R5-P2-1：重复建用户 409、吊销不存在 404）—— 通过

面板 API 直测（08:23:58–08:24:05 UTC，scratch 用户 `dup-test`）：

| 操作 | 期望 | 实测 |
|---|---|---|
| 创建 `dup-test`（第 1 次） | 200 | 200，`{'ok': True, 'user': {'name': 'dup-test', 'status': 'valid'}}` |
| 创建 `dup-test`（第 2 次） | 409 | **409**，`{"error":"user 'dup-test' already exists (valid cert)","ok":false}` |
| 吊销 `ghost`（不存在） | 404 | **404**，`{"error":"user 'ghost' does not exist","ok":false}` |
| 吊销 `dup-test`（第 1 次） | 200 | 200，`needs_restart: true`（附 CRL 须重启才对新连接生效的中文说明） |
| 吊销 `dup-test`（第 2 次，已吊销） | 409 | **409**，`{"error":"user 'dup-test' is already revoked","ok":false}` |
| 创建 `bad name!`（非法名） | 400 | **400**，`{"error":"invalid username 'bad name!': must match [a-zA-Z0-9_-]{1,32}","ok":false}` |

清理：`dup-test` 已吊销（列表中 status 为 revoked），无残留有效用户。

### 14.2 headline-6（R5-P2-3：紧权限下 server_status() 不抛错）—— 通过

本机默认状态即已满足复现条件，无需手动收紧：`/run/openvpn-server` 为 `drwx--x--- root:root`（0710），nobody 无法遍历；daemon 本身以 nobody 运行（Uid 65534），活状态日志是 `/var/log/openvpn/openvpn-status.log`（daemon fd 3，0600 root），`/run/openvpn-server/` 内实际为空（unit 的 `--status` 路径被 server.conf 的 `status` 指令覆盖）。

- **阴性对照**（nobody 下裸 `Path("/run/openvpn-server/server.pid").exists()`）：**`PermissionError: [Errno 13] Permission denied`**——正是 R5-P2-3 所述机制（Python 3.12 的 `exists()` 只吞 FileNotFoundError）。
- **修复后探针**（把 `/opt/openvpn-sk5-panel/core` 拷到 `/tmp/r5-nobody`，`runuser -u nobody` 跑 `server_status()`）：**不抛错**，返回 dict：`running=True unit_active=True error=None status_log=/var/log/openvpn/openvpn-status.log`，`online=None clients=0`——状态日志 0600 root、nobody 读不到，属诚实的部分快照（running 来自 systemctl，不撒谎），非回归。

### 14.3 headline-4（R5-P2-2：面板发起 init_pki force 重建）—— 通过

路径确认：面板无直接路由，走 agent 命令链——`POST /api/cmd {node: lightsail, action: init_pki, params}` → 202 queued → 轮询 `GET /api/cmd/<id>` 至 done/failed。重建前基线：CA `CN=OpenVPN-CA` SHA1 `36:39:59:58:26:2B:10:7C:0E:99:77:FF:B2:7A:B0:8D:B6:F2:50:1A`（2026-11-12 07:46 建），server 证书 SHA1 `40:50:25:28:88:8F:11:34:05:5C:D6:AF:28:2F:42:A5:02:DD:43:C3`，用户 alice/bob/verify-*。

| 步骤 | 实测 |
|---|---|
| (a) 无 force | failed，`OpenVPNError: CA already exists at /etc/openvpn/server/easy-rsa/pki/ca.crt (pass force=True to wipe it)`，4 秒；CA 指纹不变 |
| (b) force=true、无 confirm | failed，`ValueError: init_pki force=true wipes the CA and invalidates every issued client certificate: resend with confirm=true to proceed`；CA 指纹不变 |
| (c) force=true + confirm=true | **done，6 秒**（08:26:13→08:26:19），result 含 `ca_dir`＋6 个 server_files（ca.crt/crl.pem/dh.pem/server.crt/server.key/ta.key） |

重建后核实：新 CA SHA1 `E8:0D:62:4B:CC:C0:12:02:D7:97:AD:EE:3E:36:50:69:8C:87:8E:E0`（notBefore 08:26:15），新 server 证书 SHA1 `92:9E:B4:16:70:FC:C3:B1:FA:29:21:D8:B3:3F:2A:68:8E:49:AE:73`；index.txt 只剩 server 一行；面板用户列表为空（alice/bob/verify-* 全部随 CA 失效）。运行中的服务端（PID 494498）与旧客户端（PID 494575）靠内存旧证书继续在线，未立即断——符合预期。

**恢复与重验**（08:26–08:28 UTC）：面板重建 alice/bob 各 200；下载新 alice .ovpn（8611B，proto tcp，remote 16.146.199.68 443），按既往做法改 remote 为 LAN 172.26.15.152；面板重启 openvpn 服务（新 PID 509468，443 监听）；杀旧客户端（精确 PID 494575）；新客户端 netns 内连接（PID 509525，`Initialization Sequence Completed` 1 次，tun0 10.8.0.2/24）。数据面：curl → 16.146.199.68，NTP 216.239.35.4 48 字节 36.0ms，SK5 开、policy true、via_sk5=true；面板 online=1，记录完整（alice，10.200.0.2:49852，10.8.0.2，收 4558/发 4411，connected 08:27:17）。

- **时序说明**：重连后首次查面板显示 online=0——状态日志写盘节律所致（08:27:45 读到的仍是 08:27:07 的快照，客户端 08:27:17 才连上；45 秒后日志刷新即 online=1），非回归。
- **旧证书死亡阴性对照**：旧 alice 配置（--dev tun9 避免 tun0 冲突）25 秒内零 `Initialization Sequence Completed`，TCP 连上后反复 `Connection reset, restarting [0]`（退避 4s→8s→16s）；服务端日志：`Authenticate/Decrypt packet error: packet HMAC authentication failed`＋`Fatal TLS error`——新 ta.key 让旧配置死在 HMAC 门，连证书校验都走不到。旧证书确已失效。

### 14.4 R3-OBS-1（瞬时 401）盯防

本轮窗口（07:40 UTC 起）面板 journal 中 **401/403 零命中**。5 条 4xx 全部是预期错误码：07:50:03 `POST /api/nodes` 409（节点已存在，上一任工作）；08:23:58 `POST /api/openvpn/users` 409、08:23:58 `DELETE ghost` 404、08:24:04 `DELETE dup-test` 409、08:24:05 `POST /api/openvpn/users` 400（均为本节 headline-5 测试）。面板访问日志在 journal（Werkzeug stdout），机上无 access.log 文件。**R3-OBS-1 本轮未复发。**

## 15. 结论

### 15.1 结论先写

- **S0–S4 全部通过**：S0 安装（默认路径零绕行）✓、S0-agent 命令链 ✓、S1 UDP 首连 ✓、S2 SK5 开 TCP+UDP 双栈 ✓、S3 断网保护（杀 dante 全断、无回落、自动恢复、隧道不断）✓、S4 TCP 443 备模式 ✓。
- **headline 结论**：headline-1 开关风暴 ✓、headline-2 R4-BUG-2 ✓、headline-4/5/6 ✓；**headline-3 未全绿**——开态 verify.sh 18/0/4 全绿，关态 22/1，唯一 FAIL 是门禁 bug R5-BUG-1（§13）。
- **新 bug：1 条，阻塞 0 条**：
  - **R5-BUG-1（中，门禁）**：`egress/test-egress.sh` §6「经 SK5 的出口 IP 必须与直连不同」在 verify.sh 用本机 Python stub 作 SK5 时恒败——stub 与直连 curl 同走 IPv6 出口（stub 2600:1f13:…与直连 -6 相同；dante 对照组 IPv4 即全过）。产品链路无问题，门禁前提错；verify.sh 关态天花板 22/1，直到修好。
- **本轮测的是哪棵树**：§0 打包的 **Q/R/S/T 树**，sha256 `4b528a4bc063e8f7fbf6f0440abe107bcd66a885a84f9e8dcabb921dd2d1b64b`。**U/V/W 三路修复不在本轮验证范围内**（R6-P1-1/P2-1/P2-2/P2-3/P2-7 的修复需下一轮复验）。
- **交付判断**：产品面本轮零新阻塞 bug；唯一缺口是门禁 R5-BUG-1（关态一格）＋ U/V/W 未验。修掉 R5-BUG-1、AUDIT-R7 全量复审、live-6 复跑之后才可交付。

### 15.2 机器终态（08:34 UTC）

- 部署：**TCP 443**（S4 模式），SK5 开（dante 127.0.0.1:11080），`ip rule 100 from 10.8.0.0/24 lookup 100`＋`table 100 default via 10.9.0.1 dev tun1` 在位；面板 status：openvpn running tcp/443 online 1，sk5 enabled/policy true，egress via_sk5=true ip 16.146.199.68。
- 进程：panel PID 488562（`run-panel-tls.py`，https 8443）、openvpn server PID 509468、agent PID 490170（`/opt/ovpn-agent/agent/agent.py`）、sing-box PID 507341（agent 直管，systemd `sing-box` 单元 inactive 是设计如此）、客户端 PID 509525（新证书，10.8.0.2）。
- 服务：panel / openvpn-server@server / ovpn-agent / policy / healthcheck.timer 均为 active；healthcheck.service inactive（oneshot，正常）；最近健康检查 08:34:09 `healthy=true action=none tcp_ok=True udp_ok=True`。
- 用户：仅 alice、bob（valid）。headline-4 的 force 重建清掉了全部旧用户：5 个 verify-* 用户已随 CA 失效消失，dup-test 先吊销、后随重建消失；无残留待吊销用户。
- **FLMX 一根手指没碰**：其 sing-box PID 53637 在跑，`/root/flmx-panel` 未动。

### 15.3 观察项（不立案）

- **08:19–08:23 有 7 次本地 POST /api/sk5**（每次先登录，源 127.0.0.1；08:21  cluster 4 次/5 秒，08:22:41 与 08:23:04 各 1 次）：每次均触发 sing-box.json 重渲染＋sing-box 重启（末次 08:23:03），隧道未断、链路事后验通。**来源未识别**——健康检查定时器（60 秒）只跑本地 `sk5_manager.py health`、只写 health.json，不调 API；08:23:04 之后 11 分钟零 POST、零重启。属操作侧事件而非产品缺陷，不立案；若主控能认出这 7 次是谁发的，请补记。
- §13 遗留的测试侧教训仍有效：单条 SSH 里放 ≥60 秒 sleep 会断连，改 nohup 后台＋分段轮询。

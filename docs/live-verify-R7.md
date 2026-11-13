# OpenVPN 接 SK5 落地 · 真机复跑验证报告（第七轮 R7）

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（Y/Z/AA/AB/Y2/AC/AD/AD2 修复后的最新树——本轮第一次验证这些修复）。
> 验证人：真机复跑验证路（第七轮）。日期：2026-11-12。
> **结论先写：S0–S4 全过（S0 历经三次尝试）；BUG-9 第八次复验 UDP/TCP 双模式修好；BUG-15/16 默认重跑通过；headline-1 通过（R6-BUG-1 首启一次 200 真机终验通过）、headline-2 部分通过（AC M4 桩模型失真）、headline-3 通过（开态 18/0/4、关态 23/0/0）、headline-4 通过、headline-5 裁决已出（R7-BUG-4）。新 bug 4 条：R7-BUG-1（高，阻塞，全新安装 SIGPIPE 141 误报死亡）、R7-BUG-2（高，阻塞，毒 panel.db 致全新安装等不到 admin.pass）、R7-BUG-3（低，并发双重起）、R7-BUG-4（低，do_status 源地址错）。阻塞：2 条。**
> 前情：第一轮见 [live-verify.md](live-verify.md)（S0–S4 全过，9 个 bug，4 阻塞）；第二轮见 [live-verify-R2.md](live-verify-R2.md)（S0–S4 全过，新发现 7 个 bug，3 阻塞）；第三轮见 [live-verify-R3.md](live-verify-R3.md)（S0–S4 全过，BUG-9 第四次复验修好，新发现 6 项）；第四轮见 [live-verify-R4.md](live-verify-R4.md)（S0–S4 全过，新发现 4 项：R4-BUG-1 限流钉死＋静默直连、R4-BUG-2 自拷 abort、R4-BUG-3/4 门禁 bug）；第五轮见 [live-verify-R5.md](live-verify-R5.md)（S0–S4 全过，headline-1/2/4/5/6 通过，headline-3 未全绿——唯一新发现 R5-BUG-1 门禁，X 路已修）；第六轮见 [live-verify-R6.md](live-verify-R6.md)（S0–S4 全过，新发现 R6-BUG-1 首启 500＋R6-BUG-2 python argv；headline-2 关态 23/0/0，R5-BUG-1 真机终验通过）。

## 0. 树版本（本次装机所用）

| 文件 | mtime (UTC) | 说明 |
|---|---|---|
| install.sh | 2026-11-12 09:38:01 | AD2 路（argv 清密码；未动） |
| panel/app.py | 2026-11-12 09:22:36 | AA 路：POST /api/openvpn/init-pki |
| panel/templates/index.html | 2026-11-12 09:20:59 | AA 路：重建 CA 按钮 |
| egress/sk5_manager.py | 2026-11-12 08:07:40 | U 路（未动） |
| egress/policy-routing.sh | 2026-11-12 09:49:04 | AC 路：flock 串行化＋add_rule 幂等＋grep -q 全改 |
| egress/README.md | 2026-11-12 09:53:21 | AC 路（最新改动） |
| verify.sh | 2026-11-12 09:38:04 | AD2 路（argv 清密码）＋AB 路：sk5-egress-ip 双断言 |
| verify-integration.sh | 2026-11-12 09:35:55 | AD 路（0600 文件传密码） |
| core/openvpn_manager.py | 2026-11-12 06:01:40 | S 路（未动） |
| egress/test-egress.sh | 2026-11-12 08:40:51 | X 路（未动） |
| cloudflare/src/index.js | 2026-11-12 09:24:00 | Y2 路：init-pki 转发＋Y 路 cachedStatus 判据 |
| README.md | 2026-11-12 09:24:04 | Z 路：门禁数 28、FLMX 对齐要点重写 |

树稳定检查：10:08:53 核查时最新改动为 egress/README.md（09:53:21），**稳定 15 分 32 秒，门过**。注：并行在跑的 AUDIT-R8 此时 `docs/audit/AUDIT-R8.md` 仅 36 行（§0 头，报告未完）；docs/ 不在安装拷贝清单内，故本次打包**只含安装子集**（agent core egress panel systemd install.sh verify.sh verify-integration.sh README.md），不含 docs/ 与 `__pycache__`（R6 包 48 条目含 pycache，本轮 40 条目为其差集）。

**打包（10:08:53 UTC）**：传包走 scp（R4/R5/R6 同款）。`ovpn-r7.tar.gz`：40 条目，171,323 字节，sha256 `53de47fecfbc33ddfa61a715a8d2f812c7a66f5a77693027bc812346cde6453b`（机上核对一致）；install.sh sha256 `c69541dedbc61363be0fd2acbf57a6e625d5923c70a21f0bc012ee93ae233ff9`。

## 2. 清场（全新重装前，10:09 UTC）

- 客户端 PID 524263（第六轮 TCP 客户端）按精确 PID 杀掉，已确认无此进程；四服务已停（openvpn/singbox/panel/agent 全部 inactive，dante 保留，active）。
- 绕行已清：FORWARD 链清至只剩 ts-forward/DOCKER-USER/DOCKER-FORWARD（策略 DROP，删掉安装器自加的两条 tun0 规则与 policy-routing 的两条 tun0↔tun1 规则——本次用 `iptables -S` 快照逐条按完整规则描述 `-D`，四条一次删净；另删了 netns 删除后残留的两条 veth-host 悬空规则）；系统信任库无 ovpn 证书（R3 已清，本轮复核无残留）；无 systemd drop-in 残留；netns `vpntest` 已删。
- 状态已 wipe：`/root/openvpn-sk5-panel`、`/opt/openvpn-sk5-panel`、`/opt/ovpn-agent`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/ovpn-agent` 全删；sing-box 与 tun2socks 二进制已删（逼安装器走下载路径，复验 BUG-2）；`/root/r6/`、`/root/r6-cleanup.sh`、`/root/ovpn-r6.tar.gz` 已清（`panel.py`、`netns-setup.sh`、`probe.sh` 三个测试侧脚本先拷到 `/root/r7/` 复用，panel.py 的 JAR 路径已改 `/root/r7/jar.txt`）。
- 新树已就位：`/root/openvpn-sk5-panel/`（R7 包解压），install.sh sha256 与打包值一致（`c69541de…`）。
- 清场后核对：只剩 tailscale0 一个 tun 设备、无 1194/443/8443 监听、`/opt/openvpn-sk5-panel` 与 `/etc/openvpn-sk5-panel` 不存在。
- S0 安装已于 10:10 UTC 后台启动（`nohup bash install.sh`，PID 593855，日志 `/root/r7/install.log`）。

## 1. 地面真值（Lightsail 现状，测试前实测，09:59 UTC）

- 机上是**第六轮收尾态**（与 R6 §15.2 逐项一致）：六服务全 active（openvpn-server@server PID 524192、openvpn-sk5-singbox PID 580037、openvpn-sk5-panel PID 520520、openvpn-sk5-policy、ovpn-agent、danted PID 527024），TCP 443 部署，SK5 开（dante 替身），监听 443/tcp、11080、8443。
- 第六轮残留全部在位，**重装前必须清除**：
  - netns `vpntest` 仍在（第六轮残留）；
  - `/root/r6/` 测试产物在位（panel.py、token.txt 0600、probe/toggle/storm/argv 脚本、verify-on/off 日志、状态快照）＋ `/root/ovpn-r6.tar.gz`；
  - alice 客户端 PID 524263 仍在跑（第六轮 TCP 客户端）；
  - `/opt/openvpn-sk5-panel/` 为第六轮装树（含 agent/ 与 systemd/）。
- FLMX 相关进程同机在跑（sing-box），**一律不碰**；`/root/flmx-panel` 不动。

## 3. S0 基线：安装 + 建服务 + 建用户 —— 通过（历经三次尝试：第一次死于 R7-BUG-1、第二次死于 R7-BUG-2、第三次干净包成功；见 §3.0/§3.1/§3.2）

### 3.0 第一次尝试（10:10 UTC）：死在 tun2socks 自报版本校验 —— R7-BUG-1（高，阻塞）

- `bash install.sh`（UDP 1194 默认，无环境变量）：apt 通过；sing-box 1.11.15 下载 `sha256 OK`、自报 `sing-box version 1.11.15`；tun2socks 2.7.0 下载 `sha256 OK`；随后 **`ERROR: installed tun2socks does not report 2.7.0`**，脚本 `die`、无完成横幅（install.log 末行即此 ERROR，进程已退出）。
- **二进制本身没错**：机上手查 `/usr/local/bin/tun2socks --version` → `tun2socks-2.7.0`（第二行 `linux/amd64, go1.26.3, 8dda19e`），`grep -q 2.7.0` 直接跑即 MATCH。
- **机制已复现（R3-BUG-2 同族，从门禁漏网到产品安装路径）**：install.sh:24 `set -euo pipefail`；:333-334 校验句为 `tun2socks --version 2>&1 | head -1 | grep -q "$TUN2SOCKS_VERSION"`。`--version` 印两行，`head -1` 读首行即退出、关管，写第二行时 tun2socks 死于 SIGPIPE（141）；grep 已匹配（0），但 pipefail 下整条管道 rc=141 → `|| die` 触发。同形循环 10 次复现 1 次：`try 2 rc=141 pipe=141 0 0`，其余 9 次 rc=0——**约 10% 的抖动失败率**，本轮首次尝试即撞上。
- **同族漏网**：install.sh:297 的 sing-box 校验是同一写法（`sing-box version | head -1 | grep -q`，`sing-box version` 同样多行输出）；:306/:276 的跳过路径校验带 `|| true`，免疫。AC 路只清了 policy-routing.sh 的 `grep -q`，install.sh 的两处从未被扫到。R5/R6 两轮下载路径全过，属运气好（本轮 sing-box 一格同样是运气好）。
- **影响**：全新安装约一成概率在二进制已正确装好的情况下误报死亡；报错文案（"does not report 2.7.0"）与事实相反，排障会走错方向。修法（供修复路）：先把版本输出存变量再 grep（R3-BUG-2 的既定修法），或判 141 为通过。
- **本轮处理（测试侧重跑，非产品修复）**：重跑 install.sh——二进制已在位，走 :304-311 的跳过路径（带 `|| true`，免疫）越过该格，见 §3.1。R7-BUG-1 本身未修，仍立案。

### 3.1 第二次尝试（10:11–10:13 UTC）：面板已起、稳态门全过，但 30 秒等不到 admin.pass —— R7-BUG-2（高，阻塞）

- 重跑日志：sing-box/tun2socks 均 "already installed, skipping download"；装树、fresh secret.key、面板 TLS 证书（CN=172.26.15.152）、公网 IP 16.146.199.68、PKI + server.conf OK、NAT/FORWARD、pip、单元安装；三服务稳态门全过（openvpn/singbox/panel 各 active、restarts=0、`/api/me` 200）；随后 **`ERROR: panel is up but no admin password at /etc/openvpn-sk5-panel/admin.pass`**，`die`、无完成横幅、无初始密码输出。
- **机上实证**：`/etc/openvpn-sk5-panel/` 有 health.json、panel-cert/key.pem、panel.env、secret.key，**无 admin.pass**；新面板 PID 595498 自 10:12:06 在跑、`/api/me` 200，journal 里无首次启动密码横幅。
- **根因（已定位到行）**：本次打包的树里 `panel/data/panel.db`（32KB，mtime 09:23:07，沙箱修复路测试运行产物）含 `admin` 表 id=1 行（bcrypt 哈希 `$2b$12$/u83YskHgeiUd…`）、2 个节点、6 条审计日志。install.sh:374 装树 `cp -a panel/` 把 `panel/data/` 整目录拷进 `/opt`，:382-390 只清了随包带来的 `secret.key`（P0-5），**从未清 `panel.db`/`agent_queue.json`**。面板 `DATA_DIR` 由 `OVPN_PANEL_DATA_DIR=/opt/openvpn-sk5-panel/panel/data` 决定（install.sh:505），`panel/app.py:313-319 _ensure_admin_password()` 见 admin 行已存在即直接返回、不生成密码、不写 admin.pass；install.sh:790-799 等 30 秒无文件即 `die`。
- **定性**：潜伏的产品 bug，首次被触发——R6 打包（08:56）时 panel.db 尚无 admin 行（R6 安装一次成功），09:23 某沙箱 lane 的测试运行往源码树 panel/data 写进了 admin，才把本轮毒死。安装器"只清 secret.key、不清 panel.db"是缺口；更严重的是**事后状态**：面板在跑、admin 账号存在、密码却是沙箱某次测试生成的、机上无人知道——全新安装既未完成、面板也无法登录。
- **本轮处理（测试侧打包卫生，非产品修复）**：R7-BUG-2 的修复（安装器清 panel.db，如同清 secret.key）属修复路；本轮继续验证须用干净包——重新打包时排除 `panel/data/`（运行态数据，不应进安装包；与排除 `__pycache__` 同类），重新清场、重跑安装（见 §3.2）。首次尝试的毒包证据保留：`/tmp/ovpn-r7.tar.gz`（含毒 panel.db）与 install.log/install2.log 均在机上。

### 3.2 第三次尝试（干净包，排除 panel/data）—— 通过（前任 10:15 已跑完，我接续时复核）

- 前任在被中断前 2 分钟（10:15:20–10:15:22 UTC）已按 §3.1 末尾的计划做了 reset（`/root/r7/reset.log`）：停 4 服务（openvpn/singbox/panel/agent 均 inactive，dante 保留 active）；核 `/root/openvpn-sk5-panel/install.sh` sha256 `c69541de…` 与 §0 一致；核包内 `panel/data` 不存在；确认无 tun 设备、无 1194/443/8443 监听；install3 启动（PID 596611，日志 `/root/r7/install3.log`）。我接续时复核 reset.log 与 install3.log 全文，确认以下结论。
- install3.log：sing-box 与 tun2socks 均因二进制已删而走下载，`sha256 OK`，版本校验本次一次通过（`sing-box version 1.11.15`、`tun2socks-2.7.0` 均印出）；装树、fresh secret.key、面板 TLS 证书（CN=172.26.15.152）、公网 IP 16.146.199.68、PKI + server.conf（UDP 1194）、NAT/FORWARD、pip、单元安装；三服务稳态门全过（restarts=0、`/api/me` 200）；**健康门 passed（login + /api/status 200）、forwarding 门 passed**（`1.1.1.1 from 10.8.0.1 via 172.26.0.1 dev ens5`）；**完成横幅已印，日志 0 个 ERROR**；初始密码已生成并写入 `/etc/openvpn-sk5-panel/admin.pass`（0600，mtime 10:15）。面板新 PID 597449 自 10:15:50 在跑，journal 有首次启动密码横幅。
- 干净包：`/root/ovpn-r7b.tar.gz`，169,186 字节，10:15，tar 清单**无 panel/data**。毒包证据位置纠正：报告 §3.1 写的 `/tmp/ovpn-r7.tar.gz` 实际在 **`/root/ovpn-r7.tar.gz`**（171,323 字节，与 §0 的包一致；/tmp 下无此文件），与 `/root/r7/install.log`、install2.log 一并在位、**未删**。
- **R7-BUG-1 复核（我亲手做）**：第三次安装的两次版本校验均一次通过（未再撞 SIGPIPE）；我另在机上实跑同形循环各 10 次——tun2socks 10/10 rc=0、sing-box 10/10 rc=0（本次未复现；与前任 1/10 合计 1/20，约 5% 抖动率）。机制成立（pipefail＋head -1＋多行输出，install.sh:24/:297/:333-334 已在源码树核对），bug 仍立案。
- **R7-BUG-2 复核（我亲手做）**：tar 清单实测——r7 包含 `panel/data/panel.db` 与 `panel/data/agent_queue.json`，r7b 包无 panel/data；install.sh:374 `cp -a panel/`、:382-390 只 `rm -f …/secret.key` 已在源码树核对。机制成立，bug 仍立案。另：源码树 `panel/data/` 至今仍有 panel.db（32KB，mtime 09:23）与 agent_queue.json——**打包时排除 panel/data 只是测试侧卫生，产品侧安装器仍未修**，下轮打包若忘排除即重蹈。
- **第三次尝试 S0 安装本身：通过**。但 S0 的后半段（建服务确认＋建用户）前任未来得及做，见 §3.3。

### 3.3 S0 后半段：建服务确认＋建用户 —— 通过

- 五单元全 active：openvpn-server@server、openvpn-sk5-singbox、openvpn-sk5-panel、openvpn-sk5-policy、openvpn-sk5-healthcheck.timer；restarts 全 0；agent（ovpn-agent）inactive——**属预期**：install.sh 只 enable+start 上述五单元（:750-768），agent 由 S0-agent 的面板生成两步命令安装启动（见 §4）。
- 面板登录 200；`/api/status` 200：openvpn running（UDP 1194），online_users 0（无客户端时正确），SK5 未启用，`singbox_running: true`，sk5 块 `policy_routing_active: false`。
- 默认 `.ovpn` remote 为 **16.146.199.68 1194**（IPv4 公网，R3-BUG-5 修好）；`GET /api/openvpn/public-ip` 返回 `16.146.199.68`。
- 用户：alice、bob 创建均 200；`GET /api/openvpn/users` 只列 alice、bob（无 CA 条目，BUG-4 修好），alice 序列号 `667BC65D4AF2E73C722214E1E66C83EA`、bob `85DA6A3CD0E4913B27A6BE6B8E5C99EC`；`.ovpn` 下载 200（8612 字节），`proto udp / remote 16.146.199.68 1194 / cipher AES-256-GCM / auth SHA256`，`<cert>` 块 subject `CN = alice`、issuer `CN = OpenVPN-CA`、serial 与面板一致（BUG-7 修好）。

## 4. S0-agent：节点注册 + agent 安装 + 命令链 —— 通过（BUG-11/12 默认路径修好）

- 注册：`POST /api/nodes {"name":"lightsail","panel_url":"https://172.26.15.152:8443"}` → 201，token 43 字符（一次性返回，未写报告；只存 `/root/r7/token.txt` 0600）。
- 安装命令（按前端 `buildInstallCommand` 拼出的两步走命令逐字执行，token 由文件读入、命令本体未改动）：`curl -ksSL 'https://172.26.15.152:8443/install-agent.sh' -o /tmp/install-agent.sh && curl -ksSL 'https://172.26.15.152:8443/install-agent.sh.sha256' -o /tmp/install-agent.sh.sha256 && cd /tmp && sha256sum -c install-agent.sh.sha256 && bash /tmp/install-agent.sh --panel-url 'https://172.26.15.152:8443' --token '…' --node-name 'lightsail'` → **EXIT=0**。`install-agent.sh: OK`；TOFU 自动把面板自签证书钉到 `/etc/ovpn-agent/panel-ca.pem`；bundle 下载后 sha256 OK；`/etc/ovpn-agent/config.json` 0600；`ovpn-agent is ACTIVE (node=lightsail)`。**全程零手工信任库、零手工拷文件**——BUG-11 与 BUG-12 默认路径均修好。
- poll：`GET /api/nodes` 的 `last_seen` 为 2026-11-12T10:39:25+00:00（查时约 10:39:31，新鲜）；agent 日志 5 分钟内无 401/403、无 poll failed。
- 命令链：`POST /api/cmd {"node":"lightsail","action":"get_status"}` → **202**（cmd_id ea854166…，queued）；约 3 秒后 `GET /api/cmd/<id>` → **done**，error null；result 含 openvpn running=true pid 597240（与面板一致）、sk5 enabled=false、clients=[]（当时无客户端连接）。

## 5. S1 直连态（UDP 1194）—— 通过（首次即通，零手工 FORWARD）

- 客户端（alice，netns vpntest，`--float`，remote 改为 LAN IP 172.26.15.152——机内 netns 发往公网 IP 会经 ens5 出网关发夹回不来，属云环境限制；出厂默认 remote 已在 §3.3 验为公网 IPv4）：**首次即通**，`Initialization Sequence Completed`（10:39:45），tun0 10.8.0.2/24，redirect-gateway 路由就位。安装器自带的 FORWARD 规则之外未加任何手工规则（测试侧 netns 自身的 veth 转发规则除外）。
- 数据面（direct）：`curl ifconfig.me`（HTTP 与 HTTPS，--resolve 绕 MagicDNS）→ **16.146.199.68**；`dig @1.1.1.1 ifconfig.me` → 34.160.111.145 有回包；NTP UDP：216.239.35.4 回 **48 字节** 13.7ms、162.159.200.1 回 **48 字节** 8.2ms。UDP 数据面通过。
- **BUG-9 第八次复验——修好（UDP 模式）**：部署态原始日志（逗号 v2，13 段）为 `CLIENT_LIST,alice,10.200.0.2:37519,10.8.0.2,,3562,3549,2026-11-12 10:39:45,1794479985,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users` = **1**；`clients`=[{name: alice, real_address: 10.200.0.2:37519, virtual_address: 10.8.0.2, bytes_received: "3562", bytes_sent: "3549", connected_since: "2026-11-12 10:39:45"}]——逐字段一致；`/api/openvpn/users` 的 alice `online: true`、bob `online: false`（本节实测，非沿用上轮）。

## 6. S2 落地态（SK5 开）—— 通过（TCP+UDP 均走 SK5，双日志为证）

- 开启（首次尝试，全新安装后第一次启用）：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功，见 headline-1 §10.1），enabled=true，`policy_routing_active: true`，egress_ip 16.146.199.68；sing-box 重起一次（PID 597385→605644，属首次渲染 SK5 配置的预期重起）；`ip rule` 有 `from 10.8.0.0/24 lookup 100`；table 100 为 `default via 10.9.0.1 dev tun1`；`ip route get 1.1.1.1 from 10.8.0.1` → `dev tun1 table 100`；tun1 UP。alice 的隧道在开启前后未断（同一客户端 PID 605116 持续）。
- 开启前基线：rule 100 已在位、table 100 为空（与 R6 §3 同款安装器残留态）——本次首次启用一次 200，AC 的幂等 add（规则在位即跳过）按设计工作（见 §10.1）。
- 面板 `POST /api/sk5/test` → **tcp_ok: true、udp_ok: true**（native 模式，TCP 延迟 75.2ms）。
- 客户端 TCP（经 SK5）：`curl --resolve ifconfig.me:80:34.160.111.145 http://ifconfig.me` 与 HTTPS 同式均回 **16.146.199.68**；sing-box 日志同秒有 `outbound/socks[bought-sk5] … to 34.160.111.145:80` 与 `:443`；dante 日志 10:40 起 18 条 `tcp/connect`/`udpassociate`——TCP 确实走了 dante（SK5 替身）。出口 IP 不变属预期：替身与面板同机，S1/S2 出口恒为 16.146.199.68，链路证明以路由表 + 双日志为准（R1 已定口径）。
- 客户端 UDP（经 SK5）：NTP 到 216.239.35.4 回 **48 字节** 18.9ms、162.159.200.1 回 **48 字节** 17.8ms；sing-box 日志有 `outbound/socks[bought-sk5] … outbound packet connection to 216.239.35.4:123` 与 `162.159.200.1:123`。UDP 走 SK5 为证。

## 7. S3 断网保护（杀 dante）—— 通过（流量全断、无直连回落、自动恢复、隧道不断）

- 杀 dante（`systemctl stop danted`，inactive）：客户端 TCP `curl --resolve … http://ifconfig.me` → **exit 56**（Recv failure），HTTPS → exit 35（SSL connect error，同样失败）；NTP UDP 到 216.239.35.4 → **TimeoutError**，162.159.200.1 同样 TimeoutError；**无直连回落**（curl 不是成功、是失败——fail-closed 成立）。隧道未断（同一客户端 PID 605116，tun0 仍在，`Initialization Sequence Completed` 仅 1 次）。
- 面板 `/api/status`：kill 期间 **egress.ip = null**（`{'error': None, 'ip': None, 'latency_ms': None, 'via_sk5': True}`），诚实报空；sk5 enabled=true、policy=true。
- 恢复（`systemctl start danted`，active）：客户端 TCP 立即回 **16.146.199.68**，NTP 回 **48 字节** 16.8ms/8.6ms。隧道全程未断：同一 PID 605116，client.log 里 `Initialization Sequence Completed` 仅出现 1 次、SIGUSR1 0 行——无重连、无重拨。

## 8. S4 TCP 备模式（443）—— 通过（BUG-14 修好，S1/S2 各重跑一次）

- **BUG-14 修好**：`POST /api/openvpn/server {"proto":"tcp","port":443,"allow_port_change":true}` → **HTTP 200**。`POST /api/openvpn/restart` → 200（新 pid 606308）。TCP 443 监听，UDP 1194 监听消失，`/api/status` 为 proto=tcp port=443 running=true；新下载的 alice.ovpn 为 `proto tcp / remote 16.146.199.68 443`（默认 remote 仍是 IPv4 公网）。SK5 保持开启态。
- S2-TCP（SK5 开）：新 TCP 客户端连上（10:44:48，tun0 10.8.0.2/24）；curl → 16.146.199.68；NTP → 48 字节 17.1ms/11.1ms；dante 日志同窗口有 `tcp/connect`/`udpassociate`——TCP+SK5 链路在 TCP 模式下同样成立。旧 UDP 客户端 PID 605116 按精确 PID 杀掉（服务端已切 TCP，其重连无意义）。
- BUG-9（TCP 模式）：原始日志 `CLIENT_LIST,alice,10.200.0.2:42522,10.8.0.2,,6655,12273,2026-11-12 10:44:48,1794480288,UNDEF,1,0,AES-256-GCM`；面板 `/api/status` 的 `online_users`=**1**，`openvpn.detail.clients`=[{name: alice, real_address: 10.200.0.2:42522, virtual_address: 10.8.0.2, bytes_received: "6655", bytes_sent: "12273", connected_since: "2026-11-12 10:44:48"}]——逐字段一致。**BUG-9 第八次复验在 UDP 与 TCP 两种模式下均修好**。时序说明：客户端连上后首次查面板显示 online=0——状态日志写盘节律所致（10:45:20 读到的仍是旧快照，40 秒后刷新即 online=1；R5 §14.3 与 R6 §8 同现象），非回归。
- 观察（不立案，供下轮留意）：TCP 客户端首次 TCP connect 耗时 120 秒超时才失败（10:42:47→10:44:47 `TCP: connect … failed: Connection timed out`），SIGUSR1 后第二试立即成功（10:44:48 `TCP connection established`）。同期机上 raw TCP 连通性正常（netns 内 curl 面板 8443 → 200、`/dev/tcp` 连 443 → OK，服务端 443 监听正常、journal 无异常）。单次出现、客户端自愈、数据面全过——首要假说为测试侧 veth 路径上的一次 SYN 丢失（R6 的 TCP 客户端首次即通，本轮为首见）；产品代码不在 SYN 路径上，不立案，记在此供下轮留意。
- S1-TCP（SK5 关）：单字段 `{"enabled":false}` → 200（`policy_removed: true`、`singbox_restarted: true`、`singbox_running: true`——disable 后 sing-box 仍在 direct 模式跑，R3-BUG-1 修好）；rule 100 消失、table 100 空、路由回 ens5；TCP 客户端 curl → 16.146.199.68，NTP → 48 字节 13.1ms/6.6ms，dig @1.1.1.1 → 34.160.111.145；同一客户端 PID 606388 全程未断（`Initialization Sequence Completed` 仅 1 次）。

## 9. BUG-15/16 默认重跑（SK5 开 + TCP 443 部署，无环境变量）—— 通过

- `bash install.sh`（无 OVPN_PROTO/OVPN_PORT）：**完成横幅已印、日志 0 个 ERROR**（EXIT=0，同 S0 口径）；继承行：`inheriting deployed entry port from /etc/openvpn/server/server.conf (proto=tcp port=443; explicit OVPN_PROTO/OVPN_PORT still wins)`；横幅 `proto=tcp port=443 … (entry port inherited from existing server.conf)`；server.conf 仍为 `port 443 / proto tcp`——**R3-BUG-6（exit 127）与 BUG-16（不继承）双双修好**。
- 健康门禁：七服务（openvpn/singbox/panel/policy/healthcheck.timer/agent/dante）全 active，restarts 全 0；openvpn 同一 PID 606308（未重启）、panel 同一 PID 597449；`/api/status` proto=tcp port=443 running=true online=1，sk5 enabled=true policy=true，egress via_sk5=true；rule 100 + table 100 在位；客户端 PID 606388 全程未断（`Initialization Sequence Completed` 仅 1 次），重跑后 curl 仍通、NTP 48 字节。原地升级路径打通。

## 10. headline-1 R6-BUG-1 首启 500 真机终验 —— 通过（首启一次 200；10 次交替全一次 200；并发双启用均 200 且规则唯一）

- **首启（全新安装后第一次启用，复刻 live-6 §6 精确序列）**：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → **200**（一次成功）。此前基线：rule 100 已在位、table 100 为空（与 R6 §13 同款安装器残留态）；sing-box MainPID 597385、Started=106。启用后 enabled=true、policy=true、via_sk5=true、ip=16.146.199.68、error=None；sing-box 重起一次（PID 597385→605644，属首次渲染 SK5 配置的预期重起）。**R6-BUG-1 真机终验通过**——AC 的幂等 add（规则在位即跳过）与 flock 串行化在真机首启路径上成立。
- **10 次交替**（toggle10.sh，从禁用态起，奇数步全表单启用、偶数步单字段禁用，均为真实翻转）：10 步全部 **200**（一次成功），Started 108→118（delta 恰 10，每步一次重起），PID 每步变化，终态禁用。客户端 PID 606388 全程未断。
- **并发双启用**：两路 `POST /api/sk5 {"host","port","enabled":true}` 同时发出 → **双 200**，rule 100 唯一（`ip rule show | grep -c` = 1），终态 enabled=true、policy=true、via=true、ip=16.146.199.68；客户端 PID 606388 未断（`Initialization Sequence Completed` 仅 1 次）。**AC 的 flock 串行化在真机并发路径上成立**——无 500、无 EEXIST、无规则重复。
- 观察（新发现，见 §13 R7-BUG-3）：并发双启用时 Started 118→120（delta 2）——两路都完整重起了 daemon。终态一致、隧道未断，但一次有效翻转花了两次重起（R6-P2-2 冗余重起族的并发变体，U 的修法只覆盖了串行调用）。

## 11. headline-2 AC 的 flock/幂等真机复验 —— 部分通过（dedup 通过；占用错误预期不成立——AC 的 M4 桩模型失真，见下）

- **外来规则占 priority 100**：禁用后手工加 `100: from 10.9.9.0/24 lookup 100`，再面板启用 → **200**（不是 AC 矩阵 M4 预期的占用错误），`policy_routing_active: true`；随后 `ip rule show` 有**两条** priority 100 规则（`10.9.9.0/24` 与 `10.8.0.0/24` 共存）。客户端探针在此外来规则在位时全过（HTTP/HTTPS → 16.146.199.68，NTP 48 字节）——流量正常走 SK5。
- **机理（真机实测，非桩推断）**：真机内核允许多个不同 selector 共用同一 priority，`ip rule add` 仅在规则完全相同时才报 EEXIST。AC 的 fake-ip 桩把 priority 建模为独占键，故 M4（外来占 priority 100 → rc=1＋占用错误）在真机上不成立。产品行为本身正确：期望终态（我方规则在位、策略生效）已达成，报 200 是对的；若按 AC 预期报占用错误反而是错的。AC 的 occupant-error 分支在真机上基本不可达（仅在 add 失败且我方规则不在位时才走到，而内核对此形状不报 EEXIST）——该分支是桩模型失真带进来的死代码，供 R8 裁定（产品行为无错，AC 的 M4 验证结论需修正）。
- **清占用后重启用**：删外来规则 → 禁用 → 启用 → **200**，一次成功。
- **同 selector 不同 priority 副本**：禁用后手工加 `200: from 10.8.0.0/24 lookup 100`，再启用 → **200**；终态规则唯一（仅 `100: from 10.8.0.0/24 lookup 100`，prio 200 副本已被 dedup 清掉），table 100 为 `default via 10.9.0.1 dev tun1`。dedup 真机通过。

## 12. headline-3 verify.sh 双态全绿（AB 新格）—— 通过（开态 18/0/4、关态 23/0/0）

- **开态**（SK5 开，dante，10:55 UTC）：`bash verify.sh` → **PASS=18 FAIL=0 SKIP=4，VERIFY: ALL GREEN**（与 R5/R6 开态 18/0/4 一致；4 个 SKIP 为开态下跳过的 toggle 格——sk5-toggle、sk5-egress-ip、sk5-disable、sk5-enable-endpoint，属设计）。
- **关态**（面板关 SK5 后 25 秒再跑，10:56 UTC）：`bash verify.sh` → **PASS=23 FAIL=0 SKIP=0，VERIFY: ALL GREEN**。R5-BUG-1 的关态天花板（22/1）继续不存在。
- **AB 新格本格**：关态 `sk5-egress-ip` 格为 **[PASS] sk5-egress-ip -- /api/status egress.ip=2600:1f13:14d:a300:7913:f273:997e:c8b8 via_sk5=true while chain up (via stub)**——新格同时断言 via_sk5=true 与 ip 非空（AB 的双断言在真机上按设计工作）；`sk5-toggle-on` 与 `egress-crosscheck` 同格 PASS。
- 关态跑完后 verify.sh 自身把链重开又清回关态（sk5-enable-endpoint 格末尾 cleanup disable），终态 enabled=false、客户端 PID 606388 未断。

## 13. headline-4 开关风暴＋补策略回归 —— 通过

- **风暴**（storm2.sh，8 次快速切换，1 秒间隔，全表单/单字段交替翻转）：8 次全部 **200**，每次 MainPID 均变化，journal Started 计数 131→139（**delta 恰 8**），daemon 全程 active、**未钉死**。
- **策略丢失后全表单重开零重起**：手工删 rule 100＋清 table 100 后全表单重开 → 200，`repaired: true`、`repair_detail: ["policy routing re-applied"]`，MainPID 不变（615723）、Started 计数不变（140）——**零重起补策略**（Q 的 repair 分支在真机上按设计工作）；恢复后 rule 100＋table 100 均在位。
- **daemon 钉死后全表单重开恰一次重起**（R5 E4 同款）：6 次快速 `systemctl restart openvpn-sk5-singbox`——前 4 次 active，第 5 次即报 `start of the service was attempted too often`、**failed**（start-limit 钉死）；全表单重开 → 200，`repaired: true`、`repair_detail: ["sing-box restarted"]`，Started 计数 149→150（**delta 恰 1**），daemon active（新 MainPID），rule 100＋table 100 均恢复。注：第一次钉死修复时测试侧把 panel.py 的 `200 {...}` 前缀直接喂了 json.load（R6 §5 同款失误），收据未抓到；已按正确写法（`sed "s/^200 //"`）重做一遍钉死＋修复，数字为第二次干净结果。
- **流量真实走 SK5、隧道零重连**：风暴＋修复后探针：HTTP/HTTPS 均回 16.146.199.68，dig @1.1.1.1 → 34.160.111.145，NTP 48 字节 21.3ms/11.6ms；客户端 PID 606388 存活，`Initialization Sequence Completed` 全轮仅 1 次。

## 14. headline-5 R7 待定项裁决 ＋ 新 bug（本轮发现，4 条）

### headline-5：`./policy-routing.sh status` —— do_status 的 VPN 源 route-get 恒报错（R7-BUG-4，见下）

- 真机跑 `./policy-routing.sh status`（egress/policy-routing.sh:324-336 do_status）：exit 0；`ip rule`、`table 100`（`default via 10.9.0.1 dev tun1`）、tun1 三段均正常输出；但 **`--- route-get: VPN user source ---` 一段为 `RTNETLINK answers: Network is unreachable`**——未给出 VPN 用户的路由行。同期 host 源对照段正常（`1.1.1.1 via 172.26.0.1 dev ens5`）。
- 根因（源码树已核对）：do_status:330 是 `ip route get 1.1.1.1 from 10.8.0.2`——10.8.0.2 是客户端地址、不是本机地址，内核对非本地源报 Network is unreachable。正确源是本机 tun 地址 10.8.0.1（机上实测：`ip route get 1.1.1.1 from 10.8.0.1` → `1.1.1.1 from 10.8.0.1 dev tun1 table 100`）。这是 R3-BUG-4 的同款错误（N 路修门禁脚本时把三处 route-get 源改成了 10.8.0.1，do_status 漏网）。

### R7-BUG-1（高，阻塞）tun2socks/sing-box 版本校验 `| head -1 | grep -q` 在 pipefail 下 SIGPIPE 141 —— 前任立案，我复核成立

- 现象：全新安装第一次尝试死在 `ERROR: installed tun2socks does not report 2.7.0`（install.log 末行，二进制本身没错，`tun2socks --version` 首行即 `tun2socks-2.7.0`）。
- 机制：install.sh:24 `set -euo pipefail`；:333-334 为 `tun2socks --version 2>&1 | head -1 | grep -q "$TUN2SOCKS_VERSION"`；`--version` 印两行，`head -1` 读首行即退出、关管，写第二行时 tun2socks 死于 SIGPIPE（141）；grep 已匹配（0），但 pipefail 下整条管道 rc=141 → `|| die`。前任同形循环 10 次复现 1 次（try 2 rc=141，约 10% 抖动率）；我接续后同形循环各 10 次：tun2socks 10/10 rc=0、sing-box 10/10 rc=0（未复现；合计 1/20，约 5%）。install.sh:297 的 sing-box 校验是同一写法（`sing-box version | head -1 | grep -q`，多行输出）；:306/:276 的跳过路径校验带 `|| true`，免疫。AC 路只清了 policy-routing.sh 的 `grep -q`，install.sh 的两处从未被扫到。R5/R6 两轮下载路径全过，属运气好。
- 影响：全新安装约一成概率在二进制已正确装好的情况下误报死亡；报错文案与事实相反。修法（供修复路）：先把版本输出存变量再 grep（R3-BUG-2 的既定修法），或判 141 为通过。第三次安装的两次版本校验均一次通过（未再撞上），属运气。

### R7-BUG-2（高，阻塞）打包树 panel/data/panel.db 含 admin 行被带进 /opt，全新安装等不到 admin.pass —— 前任立案，我复核成立

- 现象：第二次尝试三服务稳态门全过、`/api/me` 200，但 30 秒等不到 admin.pass 而 die（`ERROR: panel is up but no admin password at /etc/openvpn-sk5-panel/admin.pass`）；`/etc/openvpn-sk5-panel/` 有 health.json、secret.key，无 admin.pass；面板 PID 595498 在跑、journal 无首次启动密码横幅。
- 根因：打包树里 `panel/data/panel.db`（32KB，mtime 09:23:07，沙箱修复路测试运行产物）含 `admin` 表 id=1 行、2 个节点、6 条审计日志。install.sh:374 装树 `cp -a panel/` 把 `panel/data/` 整目录拷进 `/opt`，:382-390 只清了随包带来的 `secret.key`（P0-5），**从未清 `panel.db`/`agent_queue.json`**。面板 `_ensure_admin_password()`（app.py:313-319）见 admin 行已存在即直接返回、不生成密码、不写 admin.pass；install.sh:790-799 等 30 秒无文件即 `die`。我复核：tar 清单实测——r7 包含 `panel/data/panel.db` 与 `panel/data/agent_queue.json`，r7b 干净包无 panel/data；install.sh:374/:382-390 已在源码树核对。
- 定性：潜伏的产品 bug，首次被触发——R6 打包（08:56）时 panel.db 尚无 admin 行（R6 安装一次成功），09:23 某沙箱 lane 的测试运行往源码树 panel/data 写进了 admin，才把本轮毒死。更严重的是事后状态：面板在跑、admin 账号存在、密码却是沙箱某次测试生成的、机上无人知道——全新安装既未完成、面板也无法登录。源码树 `panel/data/` 至今仍有 panel.db 与 agent_queue.json——打包时排除 panel/data 只是测试侧卫生，产品侧安装器仍未修。
- 本轮处理（测试侧打包卫生，非产品修复）：第三次安装用干净包 `/root/ovpn-r7b.tar.gz`（169,186 字节，排除 panel/data/，与排除 `__pycache__` 同类），安装成功（见 §3.2）。毒包证据在位未动：`/root/ovpn-r7.tar.gz`（171,323 字节，§0 的包；§3.1 写的 `/tmp/ovpn-r7.tar.gz` 路径有误，实际在 /root/ 下）与 `/root/r7/install.log`、install2.log。

### R7-BUG-3（低，不阻塞）并发相同启用双双完整重起 daemon（R6-P2-2 冗余重起族的并发变体）

- 现象：两路 `POST /api/sk5 {"host","port","enabled":true}` 同时发出 → **双 200**，rule 100 唯一（AC 的 flock 串行化成立，无 500、无 EEXIST），终态一致、客户端未断；但 Started 118→120（**delta 2**）——两路都完整重起了 daemon，一次有效翻转花了两次重起。
- 机理：U 的修法（set_sk5 有效态检查）只覆盖串行调用；并发的两路都在对方写盘前读到旧态（enabled=false），双双走完整渲染＋重起。面板层无串行化。影响：一次多余重起（tun1 短暂重建），无状态不一致、无用户可见错误。修法（供修复路）：面板层对 set_sk5 加锁或以 CAS 语义复核有效态。终态正确、隧道未断，按低、不阻塞记。

### R7-BUG-4（低，不阻塞）do_status 的 VPN 源 route-get 用客户端地址 10.8.0.2，恒报 Network is unreachable

- 位置：`egress/policy-routing.sh:330`，`ip route get 1.1.1.1 from 10.8.0.2`。
- 证据：真机 `./policy-routing.sh status` 的 `--- route-get: VPN user source ---` 一段为 `RTNETLINK answers: Network is unreachable`，而正确源 `from 10.8.0.1` 同机实测回 `1.1.1.1 from 10.8.0.1 dev tun1 table 100`。脚本 exit 0（`|| true` 兜底），属诊断输出错误、非功能故障；但运维人员照此输出会误判链路已断。R3-BUG-4 同族（N 路修门禁脚本的三处 route-get 源，do_status 漏网）。修法：改成 `from 10.8.0.1`（与 gate 脚本同款）。

## 15. 观察项（不立案）

- **R3-OBS-1 未复发**：本轮面板 journal 里 401 共 **1 次**，但那是 09:28:59 的旧记录（R6 轮次，旧面板 PID 520520）；本轮面板（PID 597449）任期内 401/403 均为 0。R5 为 0 次、R6 为 1 次微复发，本轮回 0。
- **B 态 `/api/sk5` 裸字段**：R6 §10.1 已记——`sk5.egress_ip` 是直拨探针量，与 gated egress.ip 不同；UI 三处渲染 gated 值，不撒谎。本轮未重验，沿用 R6 结论，供 R8 裁定。
- **TCP 客户端首次 connect 120 秒超时**：§8 已记——首试 SYN 疑似丢失、120 秒超时后 SIGUSR1 重试立即成功；单次、客户端自愈、数据面全过，R6 的 TCP 客户端首次即通，供下轮留意。
- **AC M4 桩模型失真**：§11 已记——真机内核允许多 selector 共用同一 priority，AC 的 occupant-error 分支在真机上基本不可达；产品行为正确，AC 的 M4 验证结论需修正，供 R8 裁定。
- **沙箱门禁未在本轮跑**：verify-integration.sh 是沙箱门禁（自带面板、占 8443），机上按设计 SKIP；本轮未在沙箱重跑 28 格（并行 AUDIT-R8 在跑，避撞）。主控此前已重跑 28/28（AD/AD2 核验），本轮不重复。
- **前任中断后我接续的核对**：前任 10:17 被中断时 install3（第三次尝试）其实已在 10:15:5x 跑完（完成横幅、admin.pass 已生成），reset.log 与 install3.log 齐全；毒包路径以 §3.2 纠正的 `/root/ovpn-r7.tar.gz` 为准（§3.1 的 `/tmp/ovpn-r7.tar.gz` 是笔误）。

## 16. 结论与机器终态

### 16.1 结论

- **S0–S4 全过**（S0 历经三次尝试：第一次死于 R7-BUG-1、第二次死于 R7-BUG-2、第三次干净包成功）；BUG-9 第八次复验 UDP/TCP 双模式修好；BUG-15/16 默认重跑通过（原地升级路径打通）。
- **headline-1**：通过——首启一次 200（R6-BUG-1 真机终验通过）、10 次交替全一次 200、并发双启用均 200 且规则唯一；附带观察 R7-BUG-3（低，并发双重起）。
- **headline-2**：部分通过——dedup 通过、清占用后重启用 200；占用错误预期不成立（AC M4 桩模型失真，真机内核允许多 selector 共用 priority），产品行为正确。
- **headline-3**：通过——verify.sh 开态 18/0/4、关态 23/0/0，AB 新格双断言在真机上按设计工作。
- **headline-4**：通过——风暴 8 次不钉死、策略丢失零重起补回、daemon 钉死恰一次重起修复、流量走 SK5、隧道零重连。
- **headline-5**：裁决已出——do_status 的 VPN 源 route-get 恒报错，**R7-BUG-4（低，不阻塞）**。
- **新 bug 4 条**：R7-BUG-1（高，阻塞）、R7-BUG-2（高，阻塞）、R7-BUG-3（低，不阻塞）、R7-BUG-4（低，不阻塞）。**阻塞：2 条**（R7-BUG-1、R7-BUG-2，均在全新安装路径上）。AA 的 init-pki 面板入口真机可用：无 force→400、无 confirm→400（各带明示后果的文案），未跑 force+confirm 的真执行。
- **本轮测的树**：Y/Z/AA/AB/Y2/AC/AD/AD2 树，包 sha256 `53de47fe…6453b`（§0，毒包）与干净包 `/root/ovpn-r7b.tar.gz`（§3.2）。AUDIT-R8 与本轮并行在跑，其结论未入本报告。

### 16.2 机器终态（11:02 UTC）

- 部署：TCP 443（openvpn PID 606308）、SK5 **开**（dante 替身 127.0.0.1:11080）、via_sk5=true、egress.ip=16.146.199.68、online_users=1（alice，自 10:44:48 连接未断）。
- 服务：openvpn/singbox/panel/policy/healthcheck.timer/agent/dante 全 active；客户端 PID 606388（TCP，alice）存活，全轮 `Initialization Sequence Completed` 仅 1 次。
- 测试产物：`/root/r7/`（panel.py、netns-setup.sh、probe.sh、toggle10.sh、storm2.sh、conc-enable.sh、install/install2/install3/install-default.log、verify-on/off.log、token.txt 0600、alice*.ovpn、client-udp/tcp.log）；毒包 `/root/ovpn-r7.tar.gz` 与干净包 `/root/ovpn-r7b.tar.gz` 在位；netns `vpntest` 在位（供下轮复用或清场）。
- **FLMX 一根手指未碰**（同机 FLMX sing-box 进程全程未动、`/root/flmx-panel` 未动）。

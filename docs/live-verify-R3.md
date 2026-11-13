# OpenVPN 接 SK5 落地 · 真机复跑验证报告（第三轮 R3）

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（H/I/J 修复后的最新树）。
> 验证人：真机复跑验证路（第三轮）。日期：2026-11-12。
> 前情：第一轮见 [live-verify.md](live-verify.md)（S0–S4 全过，9 个 bug，4 阻塞）；第二轮见 [live-verify-R2.md](live-verify-R2.md)（S0–S4 全过，新发现 7 个 bug，3 阻塞：R2-BUG-10/11/12 agent 安装链三断；R2-BUG-13 BUG-9 第三次未真修；R2-BUG-14/15/16）。

## 0. 树版本（本次装机所用，待稳定后填）

| 文件 | mtime (UTC) | 说明 |
|---|---|---|
| core/openvpn_manager.py | 2026-11-12 02:18:22 | I 路：逗号分隔 v2 解析 |
| panel/app.py | 2026-11-12 02:22:28 | H 路：allow_port_change 透传、sk5 单字段开关 |
| panel/templates/index.html | 2026-11-12 02:22:52 | H 路：安装命令两步走 + --node-name |
| install.sh | 2026-11-12 02:20:36 | H 路：装树拷 agent/、健康门禁按模式分支、继承 proto/port |
| cloudflare/src/index.js | 2026-11-12 02:28:20 | J 路：Worker 安装命令同族修 |
| install.sh sha256 | `7d13b2bf80756c5078fbb9063a4c71157736044af423e44272487ae868caa81a` | 沙箱核对 |

树稳定检查：02:29:42 核查时最新改动为 cloudflare/src/index.js（02:28:20），须满 15 分钟稳定（02:43:20 UTC）后打包传机。02:43:34 核查：五文件 mtime 未变，稳定 15 分 14 秒，门过。传包 tar.gz：41 条目，227,655 字节，sha256 `f0a9249f81c82cde137d34ba4e44690078c0b9bde17cf9b996e8013ca24a78e8`（机上核对一致），remote-storage 链接有效期至 2026-11-14 02:50 UTC。

## 1. 地面真值（Lightsail 现状，测试前实测，02:29:56 UTC）

- 机上是**第二轮收尾态**：六服务全 active（openvpn-server@server、openvpn-sk5-singbox、openvpn-sk5-panel、openvpn-sk5-policy、ovpn-agent、danted），TCP 443 部署，SK5 开（dante 替身）。
- 第二轮绕行全部在位，**重装前必须清除**（否则 H 路修复无法在默认路径下验证）：
  - `/opt/openvpn-sk5-panel/agent/` 为第二轮手工拷入（BUG-10 绕行）；
  - 系统信任库 `/usr/local/share/ca-certificates/ovpn-sk5-panel.crt`（02:02，BUG-11 绕行）；
  - FORWARD 链：策略 DROP；安装器自加两条规则在位（`-d 10.8.0.0/24 -i ens5 -o tun0` / `-s 10.8.0.0/24 -i tun0 -o ens5`）；另有 tun0↔tun1 两条规则（policy-routing.sh 自带）。
- netns `vpntest` 仍在（第二轮残留）；`/root/openvpn-sk5-panel/` 为第二轮上传树；`/root/r2/` 测试产物在位（install-s0b.log、install-defaults.log、agent-install*.log、alice/bob.ovpn 等）。
- FLMX 相关进程同机在跑，**一律不碰**；`/root/flmx-panel` 不动。

## 2. 清场（全新重装前，02:44–02:50 UTC）

- 四服务已停（openvpn/singbox/panel/agent 全部 inactive，dante 保留）；绕行已清：信任库证书已删（`update-ca-certificates --fresh`）、无 drop-in 残留、FORWARD 链清至只剩 ts-forward/DOCKER-USER/DOCKER-FORWARD（策略 DROP）。
- 状态已 wipe：`/root/openvpn-sk5-panel`、`/opt/openvpn-sk5-panel`、`/opt/ovpn-agent`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/ovpn-agent` 全删；sing-box 与 tun2socks 二进制已删（逼安装器走下载路径，复验 BUG-2）。
- 清场后核对：无 tun 设备（除 tailscale0）、无 1194/443/8443 监听、`/opt/openvpn-sk5-panel` 不存在。

## 3. S0 基线：安装 + 建服务 + 建用户 —— 通过（默认路径，全程零绕行）

- `bash install.sh`（UDP 1194 默认）：**INSTALL_EXIT=0**（完成横幅已印，日志无 ERROR），无环境变量绕行、无手工规则、无手工信任库。apt + pip + PKI 全新生成；sing-box 1.11.15 与 tun2socks 2.7.0 因二进制已删而走下载，**均 `sha256 OK`**（BUG-2 下载路径本轮再次真机通过）。
- 五单元全 active：openvpn-server@server、openvpn-sk5-singbox、openvpn-sk5-panel、openvpn-sk5-policy、openvpn-sk5-healthcheck.timer；restarts 全 0（BUG-3 修好）；UDP 1194 有监听（openvpn PID 384529）；FORWARD 两规则由安装器自加（BUG-8 修好）；VPN 源 `10.8.0.1` 经 ens5 出主表、不命中 table 100。
- 面板登录 200；`/api/status` 200：openvpn running（UDP 1194，pid 非 null，status_log `/var/log/openvpn/openvpn-status.log`），online_users 0（无客户端时正确），egress IPv6 直连，SK5 未启用。
- **BUG-10 真机修好**：`/opt/openvpn-sk5-panel/agent/` 在位（agent.py、install-agent.sh、ovpn-agent.service）；`GET /install-agent.sh` → 200（20,449 字节）、`GET /install-agent.sh.sha256` → 200（有值）、`GET /api/agent/bundle` → 200（62,693 字节，含 agent/agent.py 等 15 条目，未登录与已登录均 200）。
- 观察-§10 部分修好：默认 `.ovpn` remote 不再是内网 IP——安装器探测到公网 IP 后写入 panel.env，`/api/status` 的 `remote_ip` 为 `2600:1f13:14d:a300:7913:f273:997e:c8b8`，`remote_is_private: false`、`remote_warning: null`。但探测到的是 **IPv6** 地址（非 16.146.199.68）：纯 IPv4 外部客户端仍连不上，见 §10。
- S0 缺口：`policy_routing_active=true` 但 table 100 为空（仅 `ip rule 100` 在位）——旗标只反映规则存在、非有效路由（R2 已记，本轮复现）。

### R3-BUG-1（中-高，新发现）：POST /api/sk5 禁用后 sing-box 被停掉且永不恢复，面板无任何路径在 direct 模式下把它拉起来

- 现象：S0 刚装完时 sing-box active；随后两次 `bash verify.sh`（其 toggle 测试走 enable→disable→enable-endpoint→cleanup-disable）之后，sing-box 为 **inactive、dead、Result=success、NRestarts=0**——干净停掉，不是崩溃。journal：02:55:55–02:57:22 间五次 stop、四次 start，最后一次 stop（02:57:22）后再无 start。
- 根因（代码 + 实测双证）：`egress/sk5_manager.py` 的 `disable()` 只做 `_remove_policy()` + `_stop_singbox()`，**不重起 direct 模式**；而 `_start_singbox()` 全树只被 `enable()` 调用（sk5_manager.py:654 唯一调用点）。安装器建立的“sing-box 常驻 direct 模式”不变量，在第一次 API 禁用后即被打破，且面板没有任何端点能把它恢复（`/api/sk5/enable` 要求已有存量 host；当前存量 host 为空时直接 500）。
- 影响：direct 模式下 tun1/DNS 直通路径消失；`/api/status` 的 `singbox_running=false`；安装器自己的 verify.sh 此后每次都在 `sing-box-steady` 变红（本轮第二、第三次跑出同一 FAIL）。S2 的 enable 路径能把它拉起来（待 §5 验证），但用户每点一次“禁用 SK5”就会把它留在死态。
- 本轮处理（测试侧恢复，非产品修复）：S1 前用 `systemctl start openvpn-sk5-singbox` 手工拉起 direct 模式，以便矩阵继续；产品本身未动。

### R3-BUG-2（中，门禁 bug，非产品 bug）：verify.sh 的 agent-bundle 格在 `set -o pipefail` 下恒失败——grep -q 提前退出把 tar SIGPIPE 成 141

- 现象：verify.sh 两次跑出 `[FAIL] agent-bundle`，报错文案称“HTTP 200 or tarball lacks agent/agent.py”；但同一面板、同一时刻，我手工用**完全相同的 curl 命令**取包 5 次全部 200，且包体 sha256 逐字节一致（`df7542fb…`），`tar -tzf` 列出 agent/agent.py。
- 根因（已实证）：verify.sh 首行 `set -uo pipefail`；检查句为 `tar -tzf file | grep -q "^agent/agent.py$"`。grep -q 在第 2 行命中即退出，tar 写后续行时撞上已关闭的管道、死于 SIGPIPE（exit 141）；pipefail 把 141 当作整条管道的返回值，`if` 判假。沙箱对照：`set -uo pipefail` 下同一管道 → NOMATCH、pipeline-status=141；无 pipefail → MATCH。**面板的包没问题，门禁的写法有问题。**
- 影响：安装器的自带门禁在全新安装上永远红一格（本轮 verify.sh 两次跑出 exit 5 与 exit 7，agent-bundle 两次都在内）；修法是先把 tar 列表存变量再 grep，或判 141 为通过。须另派修门禁，不动产品代码。

### R3-BUG-3（中）：install.sh 装树拷了 agent/，却漏了 systemd/——安装树不完整，files 门禁永红、从 /opt 重跑安装器必死

- 现象：verify.sh 两次跑出 `[FAIL] files -- missing: /opt/openvpn-sk5-panel/systemd/{openvpn-sk5-panel,openvpn-sk5-singbox,openvpn-sk5-policy,openvpn-sk5-healthcheck}.service + healthcheck.timer`。`cp -a /opt/openvpn-sk5-panel/systemd/openvpn-sk5-panel.service` 实测 `No such file or directory`。
- 根因：install.sh:343–344 装树只拷 agent/core/egress/panel + install.sh/verify.sh/verify-integration.sh/README.md，**systemd/ 不在其中**；而 install.sh:641–645 的单元安装是从 `$SCRIPT_DIR/systemd/` 拷到 /etc。install.sh 首行是 `set -euo pipefail`，从 /opt 重跑时 `cp` 失败即整轮 abort。H 路修 BUG-10 时只补了 agent/，systemd/ 是同一“装树漏拷”家族的漏网成员。
- 影响：verify.sh 的 files 格（G 路 R2-P1-5 补的覆盖）在全新安装上恒红；用户删掉源树后从 /opt 重跑升级路径会死在单元安装步。

### R3-BUG-4（中，门禁 bug，非产品 bug）：路由核对用非本地源地址 10.8.0.2，`ip route get` 恒报 Network is unreachable

- 现象：verify.sh 两次跑出 `[FAIL] sk5-toggle-on -- rule=1 table100=1 | vpn: RTNETLINK answers: Network is unreachable`——rule 与 table 100 均已就位（路由实际已切换），只差 route-get 一句。egress-crosscheck 同样 FAIL（test-egress.sh §3 用同一命令）。
- 根因：`verify.sh` 的 `route_checks()` 与 `egress/test-egress.sh` §3 均用 `ip route get 1.1.1.1 from 10.8.0.2`；10.8.0.2 是客户端 tun 地址、**不是本机地址**，内核直接拒查（R1 §6 已记过同一假象：“属命令本身的源地址不在本机之故”）。正确源地址是本机 tun0 地址 **10.8.0.1**（我手工核对：SK5 关时 `1.1.1.1 from 10.8.0.1 via 172.26.0.1 dev ens5` 正常返回；direct-forwarding 格用 10.8.0.1 即 PASS）。
- 影响：两处门禁在链路正常时也变红，verify.sh 无法全绿；修法是把两处源地址改成 10.8.0.1（或先判地址是否本地）。test-egress.sh §6（经 SK5 的出口 IP 对照）因 workdir 输出已被 verify.sh 清理而无法单独确认，归入同族待门禁修后重验。

### verify.sh 两次实测小结（S0 补充）

- 第一次：PASS=19 FAIL=4（files、agent-bundle、sk5-toggle-on、egress-crosscheck）；第二次：PASS=18 FAIL=5（多一个 sing-box-steady，系 R3-BUG-1 的后果）。**4 个 FAIL 里 1 个是产品缺口（files/R3-BUG-3）、1 个是产品 bug 的后果（sing-box-steady/R3-BUG-1），3 个是门禁自身 bug（R3-BUG-2/4）**。安装器报“安装完成”本身没错（EXIT=0、服务全起），但自带门禁在全新安装上无法全绿——门禁与产品须同轮修。

### R3-BUG-5（低-中，§10 新皱）：全新安装的默认 .ovpn remote 是 IPv6，IPv4-only 客户端开箱即不可用

- 现象：全新安装后下载的 alice.ovpn 为 `remote 2600:1f13:14d:a300:7913:f273:997e:c8b8 1194`；IPv4-only 的 netns 测试客户端原样连接时立即失败：`write UDPv6 []: Network is unreachable (fd=3,code=101)`，反复 SIGUSR1 重启。R2 §10 的内网 IP 硬编码已修好（不再是 172.26.15.152），但探测器换成了另一个不可达地址。
- 根因：install.sh:418–434 的探测是 `curl -fsS https://ifconfig.me`（无 `-4`）；双栈主机上 curl 优先 IPv6，ifconfig.me 于是返回 IPv6 地址，写进 panel.env 的 `OPENVPN_SERVER_IP`，再进默认 .ovpn。`/api/status` 对此不报任何 warning（`remote_is_private: false`）。
- 影响：用户群以 IPv4 网络为主时，下载的默认配置文件开箱即连不上；须手工把 remote 改回 IPv4 才能用。修法：探测加 `-4`（优先 IPv4），或双栈都探测、优先写 IPv4。
- 本轮处理（测试侧 override，非产品修复）：S1/S2 的数据面改用 `remote 172.26.15.152 1194`（LAN IP，netns 内本地可达；云上公网 IPv4 16.146.199.68 从机内 netns 发包会被云 NAT 发往网关、发夹回不来，属云环境限制、非产品问题——机内 `ip route get 16.146.199.68 from 10.200.0.2` 显示经 ens5 出网关）。报告中凡称“S1 通过”均指该 override 下的数据面；出厂默认 remote 仍是上面的 IPv6，记为未修。

## 4. S0-agent：节点注册 + agent 安装 + 命令链 —— 通过（BUG-11/12 默认路径修好）


- 注册：`POST /api/nodes {"name":"lightsail","panel_url":"https://172.26.15.152:8443"}` → 200，token 一次性返回（已记档，不写报告）。
- 安装命令（按前端 `buildInstallCommand` 拼出的两步走命令，逐字执行，未改动）：`curl -ksSL …/install-agent.sh -o /tmp/install-agent.sh && curl -ksSL …/install-agent.sh.sha256 -o /tmp/install-agent.sh.sha256 && cd /tmp && sha256sum -c install-agent.sh.sha256 && bash /tmp/install-agent.sh --panel-url 'https://172.26.15.152:8443' --token '…' --node-name 'lightsail'` → **EXIT=0**。`install-agent.sh: OK`；TOFU 自动把面板自签证书钉到 `/etc/ovpn-agent/panel-ca.pem`（0600）；bundle 下载后 sha256 OK；`/etc/ovpn-agent/config.json` 0600；`ovpn-agent is ACTIVE (node=lightsail)`。**全程零手工信任库、零手工拷文件**——BUG-11（取包在 TOFU 锚之前）与 BUG-12（缺 --node-name 致 poll 401）默认路径均修好。
- poll：`POST /api/agent/poll` 每 5 秒一次、连续 4 次全部 200；`GET /api/nodes` 的 `last_seen` 为 2026-11-12T03:05:08Z（新鲜），`last_status` 含 hostname=`ip-172-26-15-152`、openvpn_running=true、sk5_enabled=false。
- 命令链：`POST /api/cmd {"node":"lightsail","action":"get_status"}` → **202**（cmd_id 37e16c20…，queued）；2 秒后 `GET /api/cmd/<id>` → **done**（created 03:05:35 → finished 03:05:39，约 4 秒；error null；result 含 openvpn pid 384529、singbox_running true、users 列表）。
- 附记（非 bug，AUDIT-R3 已有 R3-P2-1 覆盖文档面）：`POST /api/nodes/lightsail/install` 返回 404——Flask 侧本无此接口（见 docs/flmx-reference.md 1-10 行：Flask 由前端 `buildInstallCommand` 就地拼装，完整命令只在注册/轮换时给一次）；前端按钮遇 404 即走 fallback，复制出的仍是正确两步走命令。本轮用的就是注册返回的 token + 前端命令模板，链路完整。

## 5. S1 直连态（UDP 1194）—— 通过（首次即通，零手工 FORWARD）

- 前置清理（测试侧）：R2 残留的旧客户端（PID 368710，`alice-tcp.ovpn`）仍在跑，已按精确 PID 杀掉；netns 内残留的 redirect-gateway 路由已清；netns 只剩 default via 10.200.0.1（veth-cli）。
- 客户端（alice，netns vpntest，`--float`）：**首次即通**，`Peer Connection Initiated` → `Initialization Sequence Completed`（03:08:29），tun0 10.8.0.2/24，redirect-gateway 路由就位。安装器自带的 FORWARD 规则之外未加任何手工规则。
- 数据面（direct）：`curl ifconfig.me` → **16.146.199.68**（Lightsail 出口）；`dig @1.1.1.1 ifconfig.me` → 34.160.111.145 有回包；NTP UDP：`1.1.1.1:123` 两次超时——**非产品问题**（主机直连同样超时：1.1.1.1 不提供 NTP 服务）；换 time.google.com（216.239.35.4）与 Cloudflare NTP（162.159.200.1）均回 **48 字节**。UDP 数据面通过。
- **BUG-9 第四次复验——修好**：部署态原始日志（逗号 v2，13 段，03:10:13 刷新）为 `CLIENT_LIST,alice,10.200.0.2:60356,10.8.0.2,,4996,4698,2026-11-12 03:08:29,1794452909,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users` = **1**；`/api/openvpn/users` 的 alice `online: true`、bob `online: false`；agent `get_status` 的 `openvpn.clients` = `[{name: alice, real_address: 10.200.0.2:60356, virtual_address: 10.8.0.2, bytes_received: 4996, bytes_sent: 4698, connected_since: 2026-11-12 03:08:29}]`——与原始行逐字段一致。BUG-9 四轮终结。
- 附记（观察，非 bug）：03:10 UTC 的一次 `/api/status` 调用回 `{"error":"unauthorized"}`，而 03:08 同一 jar 仍有效；面板未重启（MainPID 384658 自 02:51，NRestarts 0），会话配置为 12 小时。重新登录后即恢复，单次偶发、无法复现，记为观察、不立案。

## 6. S2 落地态（SK5 开）—— 通过（TCP+UDP 均走 SK5，双日志为证）

- 开启：`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → ok:true；sing-box active；`ip rule` 有 `from 10.8.0.0/24 lookup 100`；table 100 为 `default via 10.9.0.1 dev tun1`；`ip route get 1.1.1.1 from 10.8.0.1` → `dev tun1 table 100`；tun1 UP。alice 的隧道在开启前后未断（同一会话持续）。
- 面板 `POST /api/sk5/test` → **tcp_ok: true、udp_ok: true**（native 模式，`native UDP ASSOCIATE + DNS to 1.1.1.1:53`，TCP 延迟 81ms）。
- 客户端 TCP（经 SK5）：`curl --resolve ifconfig.me:80:34.160.111.145 http://ifconfig.me` 与 HTTPS 同式均回 **16.146.199.68**；dante 日志同秒有 `tcp/connect … 127.0.0.1.11080 -> 34.160.111.145.80` 与 `:443`——TCP 确实走了 dante（SK5 替身）。出口 IP 不变属预期：替身与面板同机，S1/S2 出口恒为 16.146.199.68，链路证明以路由表 + 双日志为准（R1 已定口径）。
- 客户端 UDP（经 SK5）：`dig @1.1.1.1` 与 `dig @8.8.8.8` 均 NOERROR；NTP 到 216.239.35.4 回 **48 字节**；sing-box 日志有 `outbound/socks[bought-sk5] … to 216.239.35.4:123`；dante 日志有 `udp/udpassociate`。UDP 走 SK5 为证。
- 附记（测试环境假象，非产品问题）：裸 `curl http://ifconfig.me` 在 S2 下两次报 `Resolving timed out`——根因是本机 `/etc/resolv.conf` 为 Tailscale 接管（nameserver 100.100.100.100 MagicDNS），而裸 CLI openvpn 不应用服务端推送的 `dhcp-option DNS 1.1.1.1`（server.conf 有此推送，grep 已证）。`dig @100.100.100.100` 经隧道超时（主机直连则 NOERROR），而 `dig @1.1.1.1/@8.8.8.8` 经隧道均正常——只有 Tailscale 的 CGNAT 解析地址在链路后不通，公网 DNS 全通。真实客户端（会应用推送 DNS）或非 Tailscale 主机不受此影响；S2 结论以 `--resolve` + 双日志为准。

## 7. S3 断网保护（杀 dante）—— 通过（流量全断、无直连回落、自动恢复、隧道不断）

- 杀 dante（`systemctl stop danted`，inactive）：客户端 TCP `curl --resolve … http://ifconfig.me` → **exit 56**（Recv failure: Connection reset by peer）；NTP UDP 到 216.239.35.4 → **TimeoutError**；**无直连回落**（curl 不是成功、是失败——fail-closed 成立）。隧道未断（同一客户端 PID 392433，tun0 仍在）。
- 面板 `/api/status`：kill 期间 **egress.ip = null**（`{'error': None, 'ip': None, 'latency_ms': None, 'via_sk5': True}`，重新登录后核对）。
- 例外（设计行为，非缺口）：`dig @1.1.1.1` 在 kill 期间仍有回包——sing-box 模板把 :53 DNS 路由到 direct，不走 SK5（R1 已定口径）。kill-switch 覆盖的是 TCP 与非 DNS 的 UDP，不覆盖模板直通的 DNS。
- 恢复（`systemctl start danted`，active）：客户端 TCP 立即回 **16.146.199.68**，NTP 回 **48 字节**，面板 egress.ip 回 **16.146.199.68**（via_sk5 true）。隧道全程未断：同一 PID 392433（已跑 525 秒），client.log 里 `Initialization Sequence Completed` 仅出现 1 次、SIGUSR1/restarting 0 行——无重连、无重拨。
- 附记（观察，非 bug）：本轮两次 `/api/status` 孤立回 401（03:10、~03:16），重新登录即恢复。已排除：面板未重启（MainPID 384658 自 02:51，NRestarts 0）、secret.key 自 02:50 未变、session_version 恒为 1（未改密）、会话配置 12 小时、当前 jar 的 cookie 实测有效（`/api/me` → admin true）。机制未定、无法复现，记为观察、不立案。

## 8. R3-BUG-1 现场钉死：enable→disable→enable→disable 序列 —— 已确认（可复现）

- 序列（每步后静置 3 秒再查 `systemctl is-active`，面板返回值同步记录）：
  - Step 1 `POST /api/sk5/disable` → ok，`singbox_running:false`，is-active=**inactive**；
  - Step 2 `POST /api/sk5/enable` → ok，`singbox_running:true`，is-active=**active**；
  - Step 3 `POST /api/sk5/disable` → ok，`singbox_running:false`，is-active=**inactive**（复现）；
  - Step 4 `POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` → active，rule 100 + table 100 恢复（SK5 回开态，为 S4 准备）。
- 结论：disable 停 sing-box、enable 起 sing-box，机制确定；面板自身在 disable 的返回体里就报 `singbox_running:false`——产品自己知道它死了，但没有任何 direct 模式下的恢复路径。R3-BUG-1 钉死。

## 9. S4 TCP 备模式（443）—— 通过（BUG-14 修好，S1/S2 各重跑一次）

- **BUG-14 修好**：`POST /api/openvpn/server {"proto":"tcp","port":443,"allow_port_change":true}` → **HTTP 200**（`{"ok":true,"server":{"proto":"tcp","port":443,…}}`）。重启后 TCP 443 监听（新 pid 396135），UDP 1194 监听消失，`/api/status` 为 proto=tcp port=443 running=true。
- S1 重跑（TCP）：新下载的 alice.ovpn 为 proto tcp（remote 仍是 IPv6:443，R3-BUG-5 同族，仍用 LAN-IP override `172.26.15.152 443`）；TCP 客户端首次即通（03:18:14，Initialization Sequence Completed），tun0 10.8.0.2/24。
- S2 重跑（TCP+SK5 开）：curl → 16.146.199.68；dig @1.1.1.1 → 34.160.111.145；NTP → 48 字节；dante 日志同窗口 14 条 `tcp/connect`（含到 34.160.111.145:80）——TCP+SK5 链路在 TCP 模式下同样成立。
- BUG-9（TCP 模式）：原始日志 `CLIENT_LIST,alice,10.200.0.2:33648,10.8.0.2,,4663,4479,2026-11-12 03:18:14,1794453494,UNDEF,0,0,AES-256-GCM`；面板 `/api/status` 的 `online_users`=**1**，`openvpn.detail.clients`=[{name: alice, real_address: 10.200.0.2:33648, virtual_address: 10.8.0.2, bytes_received: 4663, bytes_sent: 4479, connected_since: 2026-11-12 03:18:14}]——逐字段一致。BUG-9 在 UDP 与 TCP 两种模式下均修好。

### R3-OBS-1（观察，非立案）：已登录会话的 API 调用偶发瞬时 401，20–60 秒内自愈

- 实证（面板 access log 为准）：全程 6 次 401，分三批——03:10:24 + 03:10:45、03:15:56 + 03:16:34、03:19:33（/api/status 与 /api/openvpn/users 同秒各 1 次）。每批之后同一 jar 不重新登录即恢复（03:19:53 同 jar 调 /api/status 回 200）。
- 已排除：面板未重启（MainPID 384658 自 02:51，NRestarts 0）、secret.key 自 02:50 未变、session_version 恒为 1（未改密）、会话配置 12 小时、jar 内 cookie 实测有效（`/api/me` → admin true）。返回体为 `{"error":"unauthorized"}`（第一分支，`session.get("admin")` 为空），非 `session_revoked`。
- 机制未定、无法复现：同一 cookie 在 20 秒内先被拒、后被接受，密钥恒定下签名验证应是确定性的，故不立编号 bug；记为观察，供主控决定是否追查。

### R3-BUG-6（高，阻塞，新发现）：BUG-16 的修复本身写崩了——install.sh:81 在 `log()` 定义（:90）之前调用 `log`，任何默认重跑一启动即 exit 127

- 现象：SK5 开态 + TCP 443 部署上 `bash install.sh`（BUG-15/16 的默认重跑）**EXIT=127**，日志只有一行：`install.sh: line 81: log: command not found`。脚本在做任何事之前即死。
- 根因（代码 + 实测双证）：H 路为修 BUG-16 在 install.sh:71–81 加了“继承已部署 proto/port”块，其中 :81 有 `log "inheriting deployed entry port …"`；但 `log()` 的定义在 :90（`# ---- helpers` 节），且文件首行是 `set -euo pipefail`——未定义的函数调用返回 127，`set -e` 立即 abort。全树仅 :90 一处 `log()` 定义，无提前定义、无 source。
- 触发条件：已部署的 server.conf 存在且 proto/port 任一走继承即死——**默认 `bash install.sh` 重跑恒死**（本轮 TCP 与 UDP 均同理）；仅当 OVPN_PROTO 与 OVPN_PORT 两个环境变量同时显式指定时才绕过该行。S0 全新安装能过，只因当时 `/etc/openvpn/server` 已被 wipe、`if [ -f server.conf ]` 不成立、该行未执行。
- 影响：**BUG-15 与 BUG-16 双双未通过**（不是健康门禁误报、不是 P01 拦截——脚本死在门禁与 P01 之前）；**原地升级路径全断**——用户“每版发版前必须走一遍真实原地升级”的硬门无从执行，任何存量部署都升不了级。修法极小（把 `log()` 定义移到继承块之前，或该行改用 echo），但须另派修复并重验。
- 本轮处理：失败的重跑未改动任何部署（四服务 active、TCP 443 监听、rule 100 + table 100 在位、TCP 客户端 PID 396306 仍在线、`/api/status` proto=tcp port=443 online=1 sk5=true）。未再试带环境变量的重跑——BUG-15/16 的题面就是默认重跑，且任何重跑都会重启服务、断开当前客户端；待修复后重验。

## 11. 结论 —— 不能交付

- S0–S4 数据面全过：S0 安装 EXIT=0、五服务 active；S0-agent 两步走 + --node-name、poll 200、命令链 202→done；S1 UDP 首次即通；S2 TCP+UDP 均走 SK5（双日志）；S3 杀 dante 全断无回落、恢复后隧道不断；S4 TCP 443 下 S1/S2 重跑全过。
- R2 的 7 个 bug：BUG-10/11/12（agent 安装链）修好、BUG-14（allow_port_change）修好、BUG-9（在线用户）修好（UDP+TCP 双模式、逐字段核对）、BUG-15/16 **未通过**（R3-BUG-6）、BUG-13（BUG-9 第三次）已由本次第四次复验终结。
- 新发现 6 项（2 门禁 bug + 4 产品 bug/观察）：R3-BUG-1（disable 杀 sing-box，中-高）、R3-BUG-2（verify.sh agent-bundle 门禁 pipefail+SIGPIPE，中）、R3-BUG-3（装树漏 systemd/，中）、R3-BUG-4（路由核对用非本地源 10.8.0.2，中）、R3-BUG-5（默认 .ovpn remote 为 IPv6，低-中）、R3-BUG-6（重跑 exit 127，高·阻塞）；观察 R3-OBS-1（偶发瞬时 401 自愈，机制未定）。
- **最大风险**：R3-BUG-6 断了原地升级路径——发版硬门本身无法执行；其次 R3-BUG-1 让“禁用 SK5”成为 sing-box 的单向死亡开关。两者不修，不能交付。
- 未验（保持原判，不 claim）：Cloudflare 真实 `wrangler deploy`（KV id 仍为占位，须用户登录）；verify.sh 全绿（门禁 bug 未修前无法全绿）；带显式 OVPN_PROTO/OVPN_PORT 的重跑路径（非题面，待 R3-BUG-6 修复后重验）。

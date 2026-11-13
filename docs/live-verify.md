# OpenVPN 接 SK5 落地 · 真机验证报告

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（集成已收口，沙箱 `verify-integration.sh` PASS=19/19）。
> 验证人：真机落地验证路。日期：2026-11-12。

## 0. 地面真值（测试前实测）

| 机器 | 角色（原定） | 系统 | 出口 IP（实测） |
|---|---|---|---|
| Simular Box `main`（cb-5056666ddefe） | 中转机（OpenVPN + sing-box + 面板 + agent） | Ubuntu 24.04.5，2 vCPU，3.8 GiB | **只有 IPv6 出口 `2605:6440:2004:185:925a:8ff:fe0b:d21d`**，且是代理网关的地址，本机无任何公网地址 |
| Lightsail 测试机（100.110.88.49） | SK5 替身 + OpenVPN 客户端 | Debian 12，root | IPv4 `16.146.199.68`，IPv6 `2600:1f13:14d:a300:7913:f273:997e:c8b8` |
| 沙箱（本机） | 观测/操作 | — | IPv6 出口（Fastly 代理池，每次不同），无稳定公网 IP；UDP sendto 一律 EPERM（含 1194 端口） |

## 1. 拓扑阻塞：Box 不能当中转机（实测证据，原定 S0–S2 按原拓扑无法执行）

Box 的网络不是一台正常 VPS，而是一台**仅 HTTP(S) 代理出口、无入站、无直连路由**的云桌面：

- `ip -4 route`：无默认路由（只有 docker0 的 172.17.0.0/16）；`ip -6 route`：只有链路本地 fe80::/64，无默认路由。
- `ip -brief addr`：只有 lo、cbonline（169.254.1.1/32）、docker0——**本机没有任何公网 IPv4/IPv6 地址**。`curl ifconfig.me` 看到的 `2605:6440:2004:185:925a:8ff:fe0b:d21d` 是出口代理网关的地址。
- 环境变量 + apt 配置：`http_proxy/https_proxy=http://127.0.0.1:3128`，apt 走该代理可用（`apt-get update` 实测 12.2 MB / 2s）。
- 直连拨测全部失败：`/dev/tcp/16.146.199.68/22` 与 `/dev/tcp/8.8.8.8/53` 均为 `Network is unreachable`；Python UDP sendto 8.8.8.8:53 报 `OSError: [Errno 101] Network is unreachable`。
- 代理 CONNECT 白名单：`CONNECT 16.146.199.68:11080` → `403 Forbidden`；`CONNECT 16.146.199.68:443` → `502`。只有 allowlist 内的 HTTPS 目标能通（github.com:200、api.github.com:200、objects.githubusercontent.com:404 表示可达）。
- `curl -6 https://ifconfig.me` 失败 rc=7；`getent hosts ifconfig.me` / `github.com` 无返回（DNS 由代理处理，本机无解析）。

由此产生的三个硬结论（不是配置问题，是环境本身）：

1. **Lightsail 客户端连不上 Box 的 OpenVPN**：Box 无公网 IP、无入站路径，UDP 1194 / TCP 443 从任何外部机器都不可达。
2. **Box 上的 sing-box 连不上 Lightsail 的 SK5**：sing-box 的 SOCKS5 拨号是直连 TCP，Box 无直连路由；代理只放行 allowlist HTTPS CONNECT，11080 不在其中。
3. **Box 上连“直连出口”都不存在**：Box 本机无默认路由，VPN 用户流量 MASQUERADE 出去无路可走；curl 能通只因它走了代理环境变量，隧道里的客户端流量不会走代理。

但 Box 并非全不能用（已验证）：`sudo -n` 可用；`/dev/net/tun` 存在，`ip tuntap add mode tun` 成功（TUN_OK）；GitHub release 下载可达（github.com:200、objects.githubusercontent.com 可达），`install.sh` 的 apt + sing-box 下载环节在 Box 上能跑；OpenVPN/sing-box/面板/agent 本体能在 Box 上启动并做本地环回验证。**只是它不能做“接公网客户端、接远端 SK5”的中转机。**

## 2. pivot：中转机改到 Lightsail（等价验证，代码同一份）

原定拓扑不可行后，改用等价拓扑验证同一份代码（`install.sh`、面板、agent、core/egress 均与 Box 方案同一份，未改任何产品代码）：

| 角色 | 机器 | 说明 |
|---|---|---|
| 中转机（OpenVPN + sing-box + 面板 + agent） | Lightsail（100.110.88.49，公网 16.146.199.68） | 真实公网、直连路由、UDP/TCP 均通；`install.sh` 原样跑 |
| SK5 替身 | Lightsail 本机 dante `127.0.0.1:11080`（UDP ASSOCIATE 支持） | 与中转机同机，但链路是真实 SOCKS5 协议路径；见 §3 对“同机替身”的诚实说明 |
| OpenVPN 客户端 | Lightsail 本机（环回 UDP 1194 / TCP 443）+ 沙箱 TCP 客户端（经 Tailscale，S4 补充） | 沙箱 UDP 一律 EPERM，S1/S2 的 UDP 腿只能由本机环回客户端跑；传输是环回，但隧道加解密、策略路由、sing-box 转发、SK5 拨号全是真实路径 |

（以下 S0–S4 按 pivot 后拓扑执行；原定“出口 IP = Lightsail IP”的 S2 判据在 pivot 后需改写，见 §3。）

## 3. 关于“SK5 替身与中转机同机”的诚实说明

原定 S2 判据“TCP 出口与 UDP DNS 出口都应 = Lightsail IP”在 pivot 后**不再能区分直连与落地**：替身与中转机同机，直连出口与经替身出口都是 Lightsail 的 IP。因此 S2 的证明改用三条机制证据（缺一不可），而非出口 IP 变化：

1. **策略路由证据**：`ip route get 1.1.1.1 from 10.8.0.2` 在启用后走表 100（`default via 10.9.0.1 dev tun1`），关闭后走主表；
2. **进程日志证据**：sing-box 日志出现 `bought-sk5` 出站的连接记录，dante 日志出现与测试时间吻合的 TCP connect + UDP ASSOCIATE 会话；
3. **S3 断网保护证据**：杀掉 dante 后客户端流量全断（而非回落直连）——若流量绕过了 dante，杀 dante 不会有任何影响。这是决定性测试。

出口 IP 在 S1/S2 均为 Lightsail IP 是**符合 pivot 拓扑的预期**，不是测试失败；若要出口 IP 变化，须把替身放到另一台有独立公网出口的机器上（Box 做不到，见 §1）。

## 4. S0 基线：安装 + 建服务 + 建用户

- 2026-11-12 00:22：项目包（44 条目，123,465 字节，sha256 `ecdf872f…86849`）经 remote-storage 传上 Lightsail，解压到 `/root/openvpn-sk5-panel/`。
- 00:23：首次 `bash install.sh` 在 sing-box 下载后停住（BUG-2，无清单）。双锚核验后以环境变量钉哈希重跑。
- 00:24：第二次跑，sing-box/tun2socks 哈希校验通过并安装（sing-box 1.11.15、tun2socks 2.7.0），随后在“direct-mode sing-box config”处 `sing-box check` FATAL 停住（BUG-1）。
- 00:25：以 `ENABLE_DEPRECATED_TUN_ADDRESS_X=true` 重跑，安装完成并打印“安装完成”，但 sing-box 实际在崩溃重启循环（BUG-3）。手工给 sing-box 与面板两个 systemd 单元加测试 drop-in 注入该变量后，三服务全部真正 active：
  - `openvpn-server@server` active，UDP 1194 监听（PID 326031）；
  - `openvpn-sk5-singbox` active（PID 326413），tun1 UP（10.9.0.1/30）；
  - `openvpn-sk5-panel` active，8443 监听（PID 326104）。
  - `net.ipv4.ip_forward=1`；POSTROUTING 有 `MASQUERADE 10.8.0.0/24 -o ens5`。
- 面板登录 OK（`/api/me` admin=true）；`/api/status`：OpenVPN 运行中（UDP 1194，10.8.0.0/24），SK5 未启用，`singbox_running=true`，直连出口 IP `2600:1f13:14d:a300:7913:f273:997e:c8b8`（Lightsail IPv6；面板取出口 IP 时走 IPv6 优先）。
- 节点 `lightsail` 注册成功（token 43 字符，仅返回一次）；用户 `liveuser` 创建成功，`.ovpn` 下载 8625 字节（`proto udp`，`remote 172.26.15.152 1194`，AES-256-GCM，见观察-1）。
- agent 安装成功、服务 active，但默认配置下 poll 永失败（BUG-5：自签证书）。绕行（面板证书进系统信任库 + panel-url 改用证书 CN 对应的 LAN IP `172.26.15.152`）并手工重启 agent 后，命令链打通：
  - 面板 `/api/nodes`：`last_seen 2026-11-12T00:30:18Z`，`last_status {hostname: ip-172-26-15-152, openvpn_running: true, sk5_enabled: false, version: 0.1.0}`；
  - 经 `/api/cmd` 下发的 `get_status`（cmd_id `a0e9b2ae…`）`status: done`，`finished_at 00:30:23Z`，结果与面板直查一致；agent 还顺手执行了之前排队的旧命令（`7bbdf9cc…`）。
- dante 替身：`127.0.0.1:11080`，TCP 拨测 `curl --socks5-hostname` 返回 `16.146.199.68`；UDP ASSOCIATE 拨测：中继分配 `127.0.0.1:38828`，经中继发往 1.1.1.1:53 的 DNS 查询回包 71 字节、txid 吻合。**替身本身 TCP+UDP 均可用。**

## 5. S1 直连态（SK5 关，UDP 1194）—— 通过（在 FORWARD 绕行下）

- 客户端：独立 netns `vpntest`（veth 10.200.0.0/30），`.ovpn` + `--float`，UDP 1194 连 `172.26.15.152`；00:32:42 `Initialization Sequence Completed`，tun0 得 `10.8.0.2/24`，`redirect-gateway def1` 路由就位（`0.0.0.0/1` + `128.0.0.0/1 via 10.8.0.1`）。
- 服务端 `openvpn-status.log`（00:33:38）：CLIENT_LIST 有该客户端（Real Address `10.200.0.2:43223`，Virtual `10.8.0.2`，Bytes Received 5011 / Sent 4020，AES-256-GCM）。注：Common Name 显示为 `OpenVPN-CA`（BUG-7）。
- **TCP 出口**：ns 内 `curl -4 http://ifconfig.me` → `16.146.199.68`；`curl http://ifconfig.me` → `16.146.199.68`。= Lightsail IPv4，符合直连态预期。
- **UDP DNS**：ns 内 `dig @1.1.1.1 example.com A` 有回包（两条 A 记录）；`ping 1.1.1.1` 2/2，rtt 6.0/7.1/8.1ms。隧道内 UDP 通。
- **但 S1 首次是失败的**：未加 FORWARD 规则前，curl 两次 15s 超时、dig 超时、ping 0/3——BUG-8。加两条 FORWARD 规则（测试机防火墙限定）后立即全通。**结论：S1 通过，但产品本身在 FORWARD policy DROP 的主机上默认装完即 S1 失败。**
- 遗留疑点（待 S2 复核）：① `dig @1.1.1.1 example.com` 返回 `104.20.23.154` / `172.66.147.243`，与 example.com 公知的 `93.184.216.34` 不符，须对照主机直连 dig 复核；② 面板 `/api/status` 在客户端已连接时仍报 `online_users: 0`、`clients: []`（BUG-9，见 §9）。

## 6. S2 落地态（SK5 开）—— 通过（TCP 与 UDP 均走 SK5 链，DNS 除外，见设计说明）

- 面板一键启用：`POST /api/sk5 {host:127.0.0.1, port:11080, enabled:true}` 返回 ok；随后 `/api/status`：`sk5.enabled=true`、`policy_routing_active=true`、`egress_ip=16.146.199.68`、`via_sk5=true`。渲染后的 sing-box 配置：socks 出站 `127.0.0.1:11080`、`udp_over_tcp=false`、`final=bought-sk5`。
- 策略路由：`ip rule` 有 `100: from 10.8.0.0/24 lookup 100`；表 100 为 `default via 10.9.0.1 dev tun1`。（`ip route get 1.1.1.1 from 10.8.0.2` 在 root ns 报 `Network is unreachable`，属命令本身的源地址不在本机之故，不是产品问题；转发路径的实证见下。）
- **TCP 经 SK5**：ns 内 `curl -4 http://34.160.111.145/`（IP 直连，绕开 DNS）返回 `fault filter abort`、rc=0；sing-box 日志 `outbound/socks[bought-sk5]: outbound connection to 34.160.111.145:80`；dante 日志同时有对应 `tcp/connect … -> 34.160.111.145.80`。**TCP 走 SK5 链实证。**
- **UDP 经 SK5**：ns 内 NTP 查询 `162.159.200.123:123` 返回 48 字节、rtt 11.7ms；sing-box 日志 `outbound/socks[bought-sk5]: outbound packet connection to 162.159.200.123:123`；dante 日志 `udp/udpassociate`。**UDP（非 53 端口）走 SK5 链实证。**（1.1.1.1:123 始终超时，但 sing-box 与 dante 日志证明包已发出且经 SK5，属目标端不响应，与链路无关。）
- **DNS**：ns 内 `dig @1.1.1.1 example.com` 有回包（与主机直连对照一致，见 S1 疑点①的结论）；但这是走 sing-box 的 `port 53 → direct` 规则**直出**，不经过 SK5——属模板的既定设计（见观察-5），不是测试失败。
- 面板自带测试：`POST /api/sk5/test`（原生 UDP 模式）返回 `tcp_ok=true`（latency 79.0ms，egress 16.146.199.68）、`udp_ok=true`、`mode=native`。这是该功能首次在真机跑通（沙箱 UDP 是 EPERM，做不了）。
- 出口 IP：S1 与 S2 均为 Lightsail IP，符合 §3 的 pivot 预期（替身与中转机同机），不作为区分证据；区分证据是上述路由表 + sing-box/dante 双日志 + S3。

## 7. S3 断网保护态（杀 SK5）—— 通过

- `systemctl stop danted` 后：ns 内 `curl -4 http://34.160.111.145/` 报 `curl: (56) Recv failure: Connection reset by peer`、rc=56；NTP 两目标均 8s 超时。**流量全断，绝无回落到盒子/主机 IP 直出。**
- 同期 `dig @1.1.1.1 example.com` 仍有回包——DNS 走 direct 规则，本就不经过 SK5，属设计行为，不是保护失效。
- 面板 `/api/status` 在 S3 期间：`egress.ip=null`、`via_sk5=true`、`policy_routing_active=true`——面板如实报“无出口”，没有拿旧 IP 充数。
- 恢复：`systemctl start danted` 后 curl rc=0、NTP 162.159.200.123 恢复（8.3ms）。**自动恢复，无需重建隧道或重启服务。**

## 8. S4 TCP 备模式（TCP 443）—— 通过（S1/S2 各重跑一次）

- 切换：面板 `POST /api/openvpn/server {proto:tcp, port:443}` + `POST /api/openvpn/restart`；`server.conf` 为 `proto tcp` / `port 443`，443/tcp 有监听，1194/udp 消失。客户端换发 `.ovpn`（`proto tcp`，`remote 172.26.15.152 443`），ns 内重连成功（tun0 10.8.0.2，AES-256-GCM）。
- **S4a（SK5 关，TCP 模式）**：curl by IP rc=0；NTP 162.159.200.123 OK（6.6ms）；dig 有回包。
- **S4b（SK5 开，TCP 模式）**：curl by IP rc=0；NTP 162.159.200.123 OK（15.0ms）；dig 有回包；sing-box 有 `bought-sk5` 的 TCP 与 UDP packet 记录，dante 有 `udpassociate` + `tcp/connect`。
- 附带：UoT 模式（`udp_over_tcp=true`）下 TCP 仍通（curl rc=0），sing-box 记 `outbound UoT packet connection`；但 NTP 两目标均超时——dante 只实现标准 UDP ASSOCIATE，不实现 UoT 扩展，属替身能力边界。关键是面板的门禁是诚实的：UoT 模式下 `POST /api/sk5/test` 返回 `tcp_ok=true`、`udp_ok=false`、`mode=udp_over_tcp`（经临时 sing-box 127.0.0.1:18080 实测），不谎报 UDP 可用。随后已恢复 `udp_over_tcp=false`。
- 结束状态：服务端留在 TCP 443、SK5 启用、udp_over_tcp=false；五服务（openvpn/sing-box/面板/agent/dante）全部 active；测试客户端已杀掉。

## 9. 发现的 bug / 缺口（只记录，不修）

### BUG-1（阻塞级）：sing-box 模板用已废弃的 tun 字段，`sing-box check` / `sing-box run` 在 1.11.15 上直接 FATAL，安装即停
- 现象：`install.sh` 跑到“writing direct-mode sing-box config”后 `sing-box check` 报错退出：
  `ERROR legacy tun address fields is deprecated in sing-box 1.10.0 and will be removed in sing-box 1.12.0`
  `FATAL to continuing using this feature, set environment variable ENABLE_DEPRECATED_TUN_ADDRESS_X=true`
  随后 `install.sh ERROR: direct-mode sing-box config failed 'sing-box check'`，安装中止。
- 根因：`egress/sing-box.json.template` 的 tun 入站用旧字段 `"inet4_address": "10.9.0.1/30"`；sing-box 1.10 起 `inet4_address`/`inet6_address` 已合并为 `address`，旧字段默认 FATAL。模板头注释称“Expected: no output / exit 0”，在 1.11.15 上不成立。
- 波及面（同一根因，三处）：① `install.sh:384` 的 `sing-box check`（已实测 abort）；② `egress/sk5_manager.py` 的 `_singbox_check()`（`enable()` 前必调，面板“一键启用 SK5”同样会炸）；③ `systemd/openvpn-sk5-singbox.service` 的 `ExecStart=sing-box run`（即使跳过 check，运行时一样 FATAL）。
- 为什么沙箱/集成没发现：egress 路只做了 JSON 解析 + 字段断言，从未对真实 `sing-box check` 跑过；集成测试在沙箱跑，无 sing-box 真二进制。属于“代码在场冒充行为”的实例。
- 修复方向（不由本路动手）：模板改 `"address": "10.9.0.1/30"`（或 `"address": ["10.9.0.1/30"]`），三处同改，并把真实 `sing-box check -c` 纳入安装门禁。
- 本路绕行（测试环境限定，非产品修复）：安装与后续服务均在环境变量 `ENABLE_DEPRECATED_TUN_ADDRESS_X=true` 下跑（install.sh 继承进 check；sing-box 与面板两个 systemd 单元用测试机本地 drop-in 注入该变量）。绕行只为隔离此 bug、继续验证其余链路；S2 的“启用”结论须标注“在绕行下通过”，产品本身未修。

### BUG-2（阻塞级）：sing-box / tun2socks 的上游 release 未发布任何 sha256 清单，`install.sh` 的 fail-closed 逻辑导致全新安装永远装不上
- 现象：首次跑 `install.sh` 在 sing-box 下载后即停：`ERROR: no sha256 manifest published for this release and no override set`。
- 根因核实：GitHub API 查 `SagerNet/sing-box v1.11.15` 全部资产，无 `checksums.txt` / `SHA256SUMS.txt` / `sha256sums.txt`；`xjasonlyu/tun2socks v2.7.0` 同样无清单。fail-closed 是对的，但“无清单即停”在上游根本不发清单时等于“永远装不上”，安装器没有第二条路。
- 本路绕行（测试限定）：双锚核验后以环境变量钉哈希重跑（见 §4）。sing-box：两个独立取法（release 下载 URL 与 API asset 下载）哈希一致 `950af37e…d9c5`；另取同 release 的 `.deb` 包内二进制与 tarball 内二进制逐字节一致 `a85f1a82…2ab81`；二进制自报 `sing-box version 1.11.15`（go1.24.4，revision bc35aca01704497c179da1a03e45ad8e32f1a51b）。tun2socks：双取法一致 `a612baa2…7381`，二进制自报 `tun2socks-2.7.0`（go1.26.3）。
- 修复方向（不由本路动手）：把双锚核验或可信哈希钉进安装器/文档，否则每个新用户首次安装都会撞同一堵墙。

### BUG-3（中）：安装器报“安装完成”时 sing-box 实际在崩溃重启循环
- 现象：`install.sh` 末尾打印“openvpn-sk5-singbox active”与“安装完成”，但 `systemctl is-active openvpn-sk5-singbox` 实为 `activating`，journal 里 sing-box 因 BUG-1 的 FATAL 每 3 秒重启一次（restart counter 3、4…），且无任何本项目 sing-box 进程在跑（ps 里 3 个 sing-box 进程全是 FLMX agent 的 1.14.4，与本项目无关）。
- 根因：安装器的健康门禁只看 `systemctl start` 返回码 / `is-enabled`，未等稳态、未核 `is-active == active`、未核进程存在。属于“表象冒充实测”。
- 修复方向（不由本路动手）：门禁改为 `systemctl is-active` + 进程存在 + 端口/tun 存在，三者齐才算过；`Restart=on-failure` 的无限重启应加 `StartLimitBurst` 护栏，免得静默空转。

### BUG-4（轻）：`GET /api/openvpn/users` 返回的是 CA 证书条目，不是已建用户
- 现象：`POST /api/openvpn/users {"name":"liveuser"}` 返回 ok，`.ovpn` 下载正常（8625 字节，内嵌证书齐全）；但随后 `GET /api/openvpn/users` 只列出两条同名 `OpenVPN-CA`（serial 不同），没有 `liveuser`。
- 推测：`list_users()` 解析 easy-rsa `index.txt` 时未过滤 CA/服务端证书，把 CA 条目当用户列出。
- 影响：创建/下载不受影响，只影响用户列表展示与吊销入口的准确性。

### BUG-5（阻塞级，agent 模式）：agent 无法 poll 面板——自签证书校验失败，命令链路全断
- 现象：agent 安装成功、服务 active，但 journal 反复报：
  `poll failed: cannot reach panel https://127.0.0.1:8443/api/agent/poll: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate>`（每 5 秒重试，永失败）；面板 `/api/nodes` 里该节点 `last_seen: null`，即面板从未见过 agent。
- 根因：`install.sh` 给面板生成的是自签 TLS 证书（CN=172.26.15.152），而 `agent/agent.py` 用 Python 默认 SSL 上下文校验面板证书，无任何信任自签证书的途径（无 `--insecure`、无 CA 传入选项、安装器不把面板证书装进系统信任库）。
- 影响：默认安装下，面板 → agent 的整条命令链是断的；S0 要求的“agent 同机 poll”在不绕行的情况下不成立。
- 本路绕行（测试环境限定，非产品修复）：把面板自签证书拷进 Lightsail 系统信任库（`update-ca-certificates`），agent 随后能正常 poll。产品修复方向：安装 agent 时自动把面板证书加入信任，或给 agent 一个 `--ca-cert` / `--insecure` 选项并在面板 UI 明示。

### 观察-1（轻）：`.ovpn` 的 remote 用的是云主机内网 IP
- 现象：下载的 `.ovpn` 写 `remote 172.26.15.152 1194`（`ip route get 1.1.1.1` 的 src，NAT 内网地址），不是公网 `16.146.199.68`。
- 影响：本机环回客户端能连；任何外部客户端拿到这个文件都连不上，须手工改 remote。面板应提供“对外地址”字段或自动探测公网 IP。

### BUG-6（轻）：重跑 install-agent.sh 换 panel-url/token 后不重启 agent，旧进程继续用旧配置
- 现象：重装 agent（新 panel-url `https://172.26.15.152:8443`）后脚本报“ovpn-agent is ACTIVE”，但 `ps` 显示旧进程（PID 328817，启动于 00:28:53）仍在用旧配置 poll `127.0.0.1` 并继续报证书错误；必须手工 `systemctl restart ovpn-agent` 才生效。
- 根因：脚本只做 `systemctl enable --now`，对已运行的服务不重启。配置已落盘（`/etc/ovpn-agent/config.json` 已是新 URL），进程还是旧的。
- 影响：换 URL/换 token 后操作员以为已生效，实际 agent 仍连旧面板；排障时会误判。

### BUG-7（重）：所有用户证书的 CN 都是 `OpenVPN-CA`，不是用户名
- 现象：`.ovpn` 内证书 subject `CN = OpenVPN-CA`（issuer 也是 `CN = OpenVPN-CA`）；`pki/index.txt` 仅有的两条记录全是 `/CN=OpenVPN-CA`（一条是 CA 本身，另一条就是 liveuser 的客户端证书）；服务端 `openvpn-status.log` 的 CLIENT_LIST 里 liveuser 的 Common Name 显示为 `OpenVPN-CA`。
- 根因（已定位到行）：`core/easyrsa.sh:51` 全局 `export EASYRSA_REQ_CN="OpenVPN-CA"`，Easy-RSA 的 `build-client-full <name>` 会拿它当证书 CN，于是每个用户证书的 CN 都是 `OpenVPN-CA`。`build-client` 分支未覆盖该变量。
- 影响：多用户无法区分（服务端日志、在线列表全显示同一 CN）；按名吊销（revoke <name>）与 `list_users` 的 CN 匹配全部失效；BUG-4（用户列表只见 CA 条目）是同一根因的表层症状。
- 修复方向（不由本路动手）：`EASYRSA_REQ_CN` 只在 `init`/`build-ca` 时设为 `OpenVPN-CA`，`build-client` 时设为 `$NAME`（或 unset 后由 easyrsa 取文件名）。

### BUG-8（阻塞级，S1 实测失败）：安装器只加 MASQUERADE、不加 FORWARD 放行，FORWARD policy DROP 的主机上 VPN 用户流量全被丢弃
- 现象：客户端握手成功、tun 通（ns 内 ping 10.8.0.1 3/3，0.23ms；服务端 CLIENT_LIST 有该客户端，Bytes Received 5011）；但 ns 内 `ping 1.1.1.1` 0/3、`curl ifconfig.me` 两次均 15s 超时、`dig @1.1.1.1` 超时。
- 根因：`iptables -L FORWARD` 策略为 DROP（43 包、2712 字节被丢，正是隧道流量），链里只有 `ts-forward` / `DOCKER-USER` / `DOCKER-FORWARD`，无任何放行 10.8.0.0/24 的规则；`10.8.0.0/24 -o ens5` 的 MASQUERADE 规则计数为 0（流量根本没走到 POSTROUTING）。`install.sh:442-447` 的“forwarding + NAT”段只写了 `net.ipv4.ip_forward=1`，没加任何 FORWARD 规则——在 FORWARD 默认 ACCEPT 的干净主机上能蒙过去，在 Docker/Tailscale 已把 FORWARD 置 DROP 的主机上全灭。
- 本路绕行（测试机防火墙限定，非产品修复）：手工加两条规则后重测 S1：
  `iptables -I FORWARD -i tun0 -s 10.8.0.0/24 -j ACCEPT`；
  `iptables -I FORWARD -o tun0 -d 10.8.0.0/24 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT`。
- 修复方向（不由本路动手）：安装器须显式加 FORWARD 放行（tun0↔外网双向，`iptables-persistent` 持久化），并在健康门禁里测一发真实转发流量，而非只看服务状态。

### BUG-9（中）：面板 `/api/status` 不报告在线客户端（online_users 恒为 0）
- 现象：客户端已连接（服务端 `openvpn-status.log` 00:33:38 明确列出该客户端，Bytes 收发均非零），同一时刻面板 `/api/status` 仍报 `online_users: 0`、`detail.clients: []`。
- 影响：面板的状态页/监控看不到任何在线用户；用户无法从面板确认“有人连上来了”，与 agent 回报的 `get_status` 同样空白。
- 待定位：`server_status()` 对 status 日志的解析（路径/格式/时间戳）有问题；与 BUG-7 的 CN 异常可能同源（若解析按 CN 过滤），也可能各自独立。

### 观察-2（轻）：`/api/status` 里 openvpn 的 `pid` 为 null
- 现象：`openvpn.running=true`、`unit_active=true`、`clients=[]`，但 `detail.pid=null`。服务本身在跑（1194/udp 有监听，PID 326031）。
- 影响：仅状态展示；在线用户数与启停不受影响。

### 观察-3（中）：SK5 模式下，解析 Tailscale MagicDNS（100.100.100.100）超时；直连模式下正常
- 现象：ns 客户端的 `curl`（resolv.conf 是 Tailscale 的 `nameserver 100.100.100.100`）在 S2/S4b 均报 `Resolving timed out`；`dig @100.100.100.100` 同样超时。但 S1（直连）同一配置的 curl 正常；且 `dig @1.1.1.1` 在 S2 正常。
- 机制：SK5 模式下 DNS 包走 sing-box 的 direct 出站；MagicDNS 只在 tailscale0 上可达，direct 出站的拨号未走 tailscale0 路由（或源地址不对），故超时。直连模式下查询经主表 MASQUERADE 出去，走 tailscale0，正常。
- 影响：只影响“DNS 服务器本身只在特殊接口上可达”的环境（本测试机因装了 Tailscale 才如此）；普通用户（DNS 为 1.1.1.1/运营商 DNS）不受影响。但属于 direct 与 SK5 模式的行为差异，值得记一笔。
- 附：S1 疑点①已结案——`dig @1.1.1.1 example.com` 返回 `104.20.23.154` / `172.66.147.243`，主机直连对照结果相同，属 1.1.1.1 的真实答案，不是隧道劫持。

### 观察-4（重要）：ping 不是本链路的有效证据——sing-box 的 tun 入站在本地代答 ICMP echo
- 现象：ns 内 ping 1.1.1.1 / 8.8.8.8 / 9.9.9.9 全部约 0.3–0.5ms，而主机直连 ping 1.1.1.1 为 5.5ms。
- 实证：tcpdump 在 tun1 上抓到 echo 请求与 49 微秒后的 echo 回复，而同期 ens5 上无任何 ICMP 包。回复是 sing-box 的 tun 入站在本地生成的，包从未出过主机。
- 结论：此后验证一律不用 ping 证明“能上网”，只用 TCP（curl）与 UDP（NTP/DNS）实测。

### 观察-5（设计行为，提请确认）：模板把全部 53 端口 DNS 流量路由到 direct，不走 SK5
- 现象：sing-box 模板的 route 规则含 `protocol: dns → direct` 与 `port: 53 → direct`；实测 ns 客户端的 DNS 查询确实直出（sing-box 日志 `outbound/direct`），不经过 dante。
- 影响：VPN 用户的 DNS 不走 SK5（出口 IP 是中转机直连 IP）。对游戏/日常使用多半是优点（快、不依赖商家 DNS），但若用户以为“一切流量都走 SK5”，DNS 是个例外。建议在面板 UI 或 README 明确写出这一条。

### 测试侧教训（非产品 bug，记下来防重犯）
- **同机客户端不用 netns 会毁主机路由**：首次在主机主命名空间跑客户端，`redirect-gateway def1` 的 `0.0.0.0/1` + `128.0.0.0/1` 进了主表，且下一跳 10.8.0.1 在本机解析到服务端的 tun0，流量直接写进服务端 tun 设备被丢弃；主机自身 `curl ifconfig.me` 随即 10s 超时。杀掉客户端后路由清除、出口恢复（16.146.199.68）。此后客户端一律放独立 netns（veth 10.200.0.0/30）跑。
- **netns 不隔离 PID**：`ip netns exec vpntest pkill openvpn` 杀掉了全机的 openvpn（含服务端，00:32:15 服务端 inactive、1194 无监听、客户端随后 ECONNREFUSED）。此后只按 PID 文件精确杀进程。
- **宿主 SNAT 改写服务端回包源地址**：ns 客户端的 UDP 回包源地址被宿主机某条 MASQUERADE 改写成 10.200.0.1（网关地址），客户端初版报 `Incoming packet rejected ... expected peer 172.26.15.152:1194`；客户端加 `--float` 后握手完成。属测试拓扑的 NAT 现象，非产品问题。

## 10. 结论

**链路本身是通的**：S1（UDP 直连）、S2（UDP+TCP 经 SK5）、S3（断网保护）、S4（TCP 备模式重跑 S1/S2）全部在真机上以实测数字通过；面板一键启用/禁用 SK5、agent 命令链、面板自带 `test_sk5`（TCP+UDP 双探）也都实测通过。**但产品不能直接交付**，因为默认安装在真实主机上走不通：

| # | 问题 | 严重度 | 状态 |
|---|---|---|---|
| BUG-1 | sing-box 模板用已废弃 tun 字段，`sing-box check/run` 在 1.11.15 上 FATAL | 阻塞 | 未修，测试用环境变量绕行 |
| BUG-2 | 上游 release 无 sha256 清单，`install.sh` 全新安装永远装不上 | 阻塞 | 未修，测试用双锚哈希绕行 |
| BUG-3 | 安装器谎报 sing-box active（实际崩溃重启循环） | 中 | 未修 |
| BUG-5 | agent 默认无法 poll 面板（自签证书校验失败），命令链全断 | 阻塞 | 未修，测试用信任库+LAN URL 绕行 |
| BUG-7 | 全部用户证书 CN 均为 `OpenVPN-CA`（`easyrsa.sh:51` 全局 `EASYRSA_REQ_CN` 泄漏） | 重 | 未修 |
| BUG-8 | 安装器不加 FORWARD 放行，FORWARD policy DROP 的主机上用户流量全灭 | 阻塞 | 未修，测试用手工规则绕行 |
| BUG-4 | 用户列表只见 CA 条目（BUG-7 的表层症状） | 轻 | 未修 |
| BUG-6 | 重装 agent 不重启旧进程，配置换了进程还是旧的 | 轻 | 未修 |
| BUG-9 | 面板在线用户数恒为 0（客户端已连接也不显示） | 中 | 未修 |

**最大风险**：BUG-1 + BUG-2 + BUG-5 + BUG-8 叠加——一个新用户按 README 在一台真实主机（尤其装了 Docker/Tailscale、FORWARD 为 DROP 的主机）上跑 `install.sh`，会在 sing-box 下载处先撞墙，绕过后在 `sing-box check` 处再撞墙，绕过后 sing-box 崩溃重启、agent 连不上、用户流量被防火墙丢弃——**安装完成界面是绿的，但核心链路一条都没真正通**。四处都是“安装器/面板报成功、实际未生效”的表象问题，与 BUG-3 同族。建议修完 BUG-1/2/5/7/8 后重跑一次本验证矩阵（S0–S4），再进入用户要求的全量全局自审计。

**测试环境收尾状态**：Lightsail 上五服务全 active，服务端在 TCP 443、SK5 启用、udp_over_tcp=false；测试客户端已杀掉；netns `vpntest`、dante 替身、UDP echo 服务仍在机上（均为测试件，未动 `/root/flmx-panel` 的彩排部署）；Box 未做任何改动（原定拓扑不可行，见 §1）。

# OpenVPN 接 SK5 落地 · 真机复跑验证报告（第二轮 R2）

> 只验证、不改项目代码。项目：`~/workspace/openvpn-sk5-panel/`（D+E 修复 + F/G 修复后的最新树）。
> 验证人：真机复跑验证路（第二轮，重派）。日期：2026-11-12。
> 前情：第一轮见 [live-verify.md](sandbox://workspace/openvpn-sk5-panel/docs/live-verify.md)（S0–S4 全过，但 9 个 bug，其中 4 阻塞）；AUDIT-R2 裁决不能交付（P1 5 条），F/G 两路修完后重跑本矩阵。

## 0. 树版本（本次装机所用）

| 文件 | mtime (UTC) | 说明 |
|---|---|---|
| core/openvpn_manager.py | 2026-11-12 01:29:30 | F 路：_parse_status_log 按真实 v1/v2 行形重写 + 存量证书序列号识别 |
| panel/app.py | 2026-11-12 01:26:19 | F 路：OVPN_PANEL_DATA_DIR、改密 UI 后端 |
| panel/templates/index.html | 2026-11-12 01:26:34 | F 路：改密入口 |
| install.sh | 2026-11-12 01:26:53 | F 路：panel 稳态门 + 改密文案 |
| install.sh sha256 | `74661e64cda54ecf67bb2ffae74c00de4bee58b005768fcc2bf75e74863c056c` | 机上核对一致 |
| 传包 tar.gz sha256 | `051e36b70f172359031599561022ecb5bc57660c2d0c275e6046e81d29619557` | 54 条目，212,216 字节 |

树稳定检查：01:26 核查时 core 文件 2 秒前刚被 F 路改动，门未过；后台每 60 秒重核，四文件自 01:29:30 后无改动，01:45:27 满 15 分钟稳定后打包传机。

## 1. 地面真值（Lightsail 现状，测试前实测）

- 机上仍是**第一轮的旧部署**（服务启动于 00:26–00:45 UTC），上一任执行者未留任何半截安装：`/root/openvpn-sk5-panel/install.sh` sha256 `5c129d87…` ≠ 当前树；无新传包、无新进程。
- 五服务全 active：panel 00:26（PID 326416）、agent 00:30（PID 329458）、dante 00:42（PID 334057，SK5 替身）、openvpn 00:43（PID 334314，TCP 443）、sing-box 00:45（PID 335370）。
- 第一轮绕行全部在位，**重装前必须清除**（否则 BUG-1/5/8 无法在默认路径下验证）：
  - systemd drop-in `zz-test-workaround.conf`（panel + singbox，注入 `ENABLE_DEPRECATED_TUN_ADDRESS_X`）；
  - 系统信任库 `/usr/local/share/ca-certificates/ovpn-sk5-panel.crt`（BUG-5 绕行）；
  - FORWARD 链两条手工规则（`-s 10.8.0.0/24 -i tun0` 与 `-d 10.8.0.0/24 -o tun0`，BUG-8 绕行）；链策略仍为 DROP；另有 tun0↔tun1 两条规则（policy-routing.sh 自带）。
- netns `vpntest` 仍在（第一轮残留）；`sk5.json`：enabled=true，127.0.0.1:11080。
- FLMX 相关进程（flmx_agent、1.14.4 sing-box、xray）同机在跑，**一律不碰**；`/root/flmx-panel` 不动。

## 2. 清场（全新重装前，01:26 UTC）

- 四服务已停（openvpn/singbox/panel/agent 全部 inactive，旧 PID 已无）；dante 保留（SK5 替身，非产品件）。
- 绕行已清：两 drop-in 已删、信任库证书已删（`update-ca-certificates --fresh`）、4 条产品相关 FORWARD 规则已删（链现只剩 ts-forward/DOCKER-USER/DOCKER-FORWARD，策略 DROP）。
- 状态已 wipe：`/root/openvpn-sk5-panel`、`/opt/openvpn-sk5-panel`、`/opt/ovpn-agent`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/ovpn-agent` 全删（install.sh 本身幂等：重跑会保留旧 CA/旧密码/旧 sing-box.json，不 wipe 就不算全新重装；旧 PKI 含 CN=OpenVPN-CA 的存量证书，BUG-7 复验必须从新 PKI 起）。
- 清场后核对：无 tun 设备、无 1194/443/8443 监听。

## 3. S0 基线：安装 + 建服务 + 建用户 —— 通过（默认路径，全程零绕行）

- `bash install.sh`（UDP 1194 默认）：**INSTALL_EXIT=0**，无环境变量绕行、无手工规则、无手工信任库。apt + pip（bcrypt 5.0.0）+ PKI 全新生成；sing-box 1.11.15 与 tun2socks 2.7.0 因机上已装而跳过下载（见 S0b 缺口）。
- 五单元全 active：openvpn-server@server、openvpn-sk5-singbox、openvpn-sk5-panel、openvpn-sk5-policy、openvpn-sk5-healthcheck.timer；稳态门三证齐：openvpn restarts=0、sing-box restarts=0（BUG-3 修好：无崩溃重启循环）、panel 稳态门 `/api/me` 200 restarts=0（F 路新增，首次真机通过）。
- 面板健康门禁通过（login + `/api/status` 200）；转发门禁通过（FORWARD 两规则由安装器自加，VPN 源 `10.8.0.1` 经 ens5 出主表、不命中 table 100）——**BUG-8 在默认安装路径上已修**。
- 面板登录 200；`/api/status`：openvpn running（UDP 1194，pid 358732 非 null，status_log `/var/log/openvpn/openvpn-status.log`），online_users 0（无客户端时正确），egress IPv6 直连，SK5 未启用。
- 用户：alice、bob 创建均 200；`GET /api/openvpn/users` 只列 alice、bob（无 CA 条目，**BUG-4 修好**），各带 DER 序列号；`.ovpn` 下载均 200，证书 **CN=alice / CN=bob，互不相同**（**BUG-7 真机修好**）。
- 观察-1 现状：`.ovpn` remote 默认仍是内网 `172.26.15.152`，但面板已明示（`/api/status` 的 remote_warning：“站外客户端连不上：请在上方填公网 IP/域名，或点‘自动探测公网 IP’”）；`GET /api/openvpn/public-ip` 实测返回 `16.146.199.68`（探测本身可用）。
- server_ip 覆盖生效：`POST /api/openvpn/server {"server_ip":"16.146.199.68"}` → 200，重新下载的 .ovpn remote 即为 `16.146.199.68 1194`，`/api/status` 的 remote_warning 消失；改回 `172.26.15.152` 后 remote 亦跟回（后续客户端测试用 LAN remote，与第一轮一致）。
- S0 缺口与观察（非阻断，见 §10）：
  - S0b：sing-box/tun2socks 已装故跳过下载，BUG-2 的钉死哈希下载路径本次未被执行，须补一轮删二进制重装验证。
  - `policy_routing_active=true` 但 table 100 为空（仅 `ip rule 100` 在位）：该旗标反映规则存在而非有效路由，SK5 关时无实际影响，但文案易误读。
  - 默认 remote 为内网 IP 的根因：`panel.env` 写死 `OPENVPN_SERVER_IP=172.26.15.152`，`_outward_ip()` 的“显式 env > 公网探测”优先级使安装器把 LAN IP 钉成默认，公网探测被遮蔽——E 路所称“默认自动探测公网 IP”在全新安装上不成立（须用户在面板上手填/点探测才改）。

### S0-agent：节点注册 + agent 安装与命令链（BUG-5/BUG-6 本体）

- 节点注册 201（token 43 字符）；`GET /install-agent.sh` 在修复绕行后 200（17,562 字节），sha256 端点有值，bundle 含 4 条 agent/ 条目。
- **BUG-6 真机修好**：重跑 install-agent.sh（换 token/换名）后 agent 进程被重启（PID 363083 → 363793），日志明示“restarting it so the new config takes effect”。
- 命令链打通：`POST /api/cmd {"action":"get_status"}` → 202，7 秒后回执 `done ok=true`，结果与面板直查一致（openvpn running，pid 358732）。
- 结论：**BUG-5 的 agent poll 本体在绕行后是通的**（last_seen 02:04:13Z，last_status 含 hostname/openvpn_running/sk5_enabled/version）。但默认安装路径上它仍不可达——R2-BUG-10/11/12 三处断点在前。另：首次 poll 曾报 401（节点名不匹配，见 R2-BUG-12）与 403（panel_url 认领守卫：我经 127.0.0.1 注册，agent 认领 172.26.15.152——守卫按设计工作，测试侧用显式 panel_url 重注册后通过）。

### R2-BUG-10（阻塞级，新发现）：全新安装的 /opt 树缺 agent/，面板下发 agent 的三条路全断

- 现象：节点注册成功（201，token 43 字符）；随后 `GET /install-agent.sh` → **404**，`GET /install-agent.sh.sha256` → **500**（journal：`FileNotFoundError: '/opt/openvpn-sk5-panel/agent/install-agent.sh'`），`GET /api/agent/bundle` → 200 但包里只有 10 条目（core + egress），**无 agent 代码**。
- 根因：`install.sh:316` 的装树命令只拷 `core egress panel install.sh verify.sh README.md`，`agent/`（以及 cloudflare/、docs/、systemd/、verify-integration.sh）根本没进 `/opt/openvpn-sk5-panel`。而面板的三个 agent 下发端点全从 `PROJECT_DIR/agent/` 读文件。
- 影响：文档写的一键装 agent 命令（`curl <面板>/install-agent.sh | bash`）在全新安装上是死的；BUG-5 的命令链连起点都没有。沙箱门禁没拦住，因为 verify-integration.sh 是从完整树副本起面板（agent/ 在位）；第一轮是直接从上传树跑 install-agent.sh，没走面板 URL。
- 本轮绕行（测试机限定，非产品修复）：手工把 `/root/openvpn-sk5-panel/agent/` 拷进 `/opt/openvpn-sk5-panel/agent/`，以便继续验证 BUG-5/BUG-6 的本体行为；产品本身仍是断的，须修安装器（装树时拷 agent/）并把“已安装树的 /install-agent.sh 与 bundle 内容”纳入安装门禁。

### R2-BUG-11（阻塞级，新发现）：install-agent.sh 的取包步骤在信任锚建立之前，默认自签面板上永远装不上

- 现象：绕过 BUG-10 拿到脚本后，默认命令仍 `exit 1`：`ERROR: no sha256 for the agent bundle: panel does not serve .../api/agent/bundle.sha256`。
- 根因：脚本内所有对面板的 curl（取 `install-agent.sh.sha256`、取 `bundle.sha256`、下载 bundle）都是不带 `--cacert`/`-k` 的 plain curl，而 TOFU 钉证书的步骤在取包**之后**才执行。默认自签面板上 TLS 校验必失败，脚本却把失败误报为“面板不提供该端点”。
- 逐项实证（同一台机、同一面板）：
  - 默认运行 → exit 1，死在 bundle sha256 取回；
  - `--insecure` 运行 → exit 1，**同一处失败**（该开关只改 agent 配置的 poll 行为，不管安装器自身的取包）；
  - `OVPN_AGENT_BUNDLE_SHA256=<面板实测哈希>` 运行 → 越过哈希取回，死在 bundle 下载，curl 明文报错 `failed to verify the legitimacy of the server`。
- 结论：默认自签面板上，唯一能装上 agent 的办法仍是第一轮的绕行（面板证书预装进系统信任库）。E 路的 BUG-5 修复（TOFU 钉死）只修了 agent poll 这一环，安装器取包这一环的信任时序没人修——修 A（agent 侧）漏 B（安装器侧），正是本轮要防的同族。
- 本轮绕行（测试机限定）：把面板自签证书装进系统信任库后重跑安装器，以验证 BUG-5 本体（TOFU/poll）是否真通；产品本身仍是断的。

### R2-BUG-12（阻塞级，新发现）：面板给出的安装命令不带 --node-name，agent 默认用主机名注册，poll 恒 401

- 现象：装完 agent（exit 0、服务 active）后，`/api/nodes` 的 `last_seen` 恒为 null；agent 日志反复 `poll failed: panel HTTP 401`。
- 根因：`install-agent.sh:45` 的 `NODE_NAME` 默认取 `hostname`（本机 `ip-172-26-15-152`）；面板 `_agent_auth()` 在 token 有效时仍校验 `body.node_name` 与注册名一致（不一致 → 401“token 与节点名不匹配”）。而面板前端拼出的安装命令（`index.html:815-819`）只传 `--panel-url` 与 `--token`，**不带 `--node-name`**——按面板自己的命令装，agent 的名字永远对不上注册名。
- 另：前端那条安装命令本身也是 plain `curl -fsSL`（无 `-k`），在默认自签面板上连脚本都下不下来（与 R2-BUG-11 同族）。
- 本轮绕行（测试机限定）：重跑安装器并显式加 `--node-name lightsail`，以验证 BUG-5 本体；产品本身仍是断的。

## 4. S1 直连态（SK5 关，UDP 1194）—— 通过（首次即通，零手工规则）

- 客户端：netns `vpntest`，alice.ovpn + `--float`，02:05:09 `Initialization Sequence Completed`，tun0 得 `10.8.0.2/24`，AES-256-GCM。
- **TCP 出口**：ns 内 `curl -4 http://ifconfig.me` → `16.146.199.68`；IP 直连 `curl http://34.160.111.145/` HTTP 404（rc=0，有响应）。
- **UDP DNS**：`dig @1.1.1.1 example.com A` 有回包（NOERROR，两条 A 记录，与主机直连对照一致）。
- **UDP NTP**：`162.159.200.123:123` 回 48 字节，rtt 6.2ms。
- **BUG-8 真机确认修好**：S1 首次即通，全程无手工 FORWARD 规则（安装器自加的两条规则在位，FORWARD 策略仍 DROP）。

### R2-BUG-13（中，BUG-9 第三次未真修）：部署态日志是逗号分隔 v2，解析器仍丢弃，在线用户恒 0

- 实测：客户端已连接 90 秒后，服务端日志（`/var/log/openvpn/openvpn-status.log`，TIME 02:06:46）有真实行：
  `CLIENT_LIST,alice,10.200.0.2:51829,10.8.0.2,,5457,5121,2026-11-12 02:05:09,1794449109,UNDEF,0,0,AES-256-GCM`
  同期面板 `/api/status` 仍报 `online_users: 0`、`clients: []`。
- 根因：部署态是**逗号分隔的 v2**（Debian 单元传 `--status-version 2`，状态文件恒用逗号分隔、带 HEADER 行、CLIENT_LIST 行 13 段）；F 路解析器只认 TAB 分隔 v2、裸 5 段 v1（须 "OpenVPN CLIENT LIST" 段头）、7 段前缀形——13 段逗号行进 `CLIENT_LIST,` 分支后 `len(parts)==7` 不成立即丢弃。R2 审计与 F 路的夹具都把 v2 当成 TAB（那是管理接口的格式，不是状态文件的格式），两轮夹具同族失真。
- 沙箱复现（用机上原样日志行喂 `_parse_status_log` 本体）：返回 `[]`，count 0，坐实。
- 另记：单元另传 `--status /run/openvpn-server/status-server.log`，但该目录实测为空（无此文件）；面板读的是 `/var/log/...`，不影响 BUG-9 结论。

## 5. S2 落地态（SK5 开，UDP 1194）—— 通过

- 面板启用 SK5（`POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}`，dante 替身，无账号密码）→ 200；`ip rule 100` 在位，**table 100 现有有效路由** `default via 10.9.0.1 dev tun1`；sing-box 配置 `final: bought-sk5`、`udp_over_tcp: false`（原生 UDP ASSOCIATE）；面板 `/api/status`：`egress.via_sk5: true`（出口 IP 仍为 16.146.199.68——同机替身，见前情：本格不以出口 IP 变化为证）。
- **TCP 走 SK5**：ns 内 `curl http://34.160.111.145/` HTTP 404（rc=0）；sing-box 日志 `outbound/socks[bought-sk5]: outbound connection to 34.160.111.145:80`；dante 日志 `tcp/connect: … 127.0.0.1.11080 -> 172.26.15.152.30080 34.160.111.145.80`。
- **UDP 走 SK5**：NTP `162.159.200.123:123` 回 48 字节，rtt 11.7ms（直连 6.2ms，多一跳）；sing-box 日志 `outbound packet connection to 162.159.200.123:123`；dante 日志 `udp/udpassociate: … -> 162.159.200.123.123`。
- **DNS**：ns 内 `dig @1.1.1.1` 仍 NOERROR（模板把 53 端口路由到 direct，设计行为，与第一轮一致）。
- **面板 test_sk5**：`tcp_ok: true`、`udp_ok: true`、`udp_mode: native`、latency 81.6ms。
- 注：dante 日志在 journal（`journalctl -u danted`），不在 `/var/log/danted.log`（该文件不存在）。

## 6. S3 断网保护态（杀 SK5）—— 通过（无回落，自动恢复）

- 停 dante（`systemctl stop danted` → inactive）后：
  - 客户端 TCP：`curl http://34.160.111.145/` → `rc=000 exit=56`（失败；若回落直连应为 HTTP 404）。
  - 客户端 UDP NTP：`TimeoutError`（6 秒超时，无回包）。
  - 面板 `/api/status`：`egress.ip: null`（诚实报空，不谎报直连 IP），`via_sk5: true`（仍指 SK5 为既定出口路径）。`last_health` 为 02:09:27 的旧探测结果（上次 test_sk5 留存），非实时。
- 恢复：`systemctl start danted` → active；客户端 TCP 立即恢复 HTTP 404，NTP 回 48 字节 9.7ms；**隧道全程未断**（tun0 仍为 10.8.0.2，客户端日志无重连）。

### R2-BUG-14（中）：面板 API 没有任何办法改入口端口——报错指引的 allow_port_change 在路由层被丢弃

- 现象：`POST /api/openvpn/server {"proto":"tcp","port":443}` → 500（P01 拒绝）。按报错指引加 `{"allow_port_change":true}` 再发 → **仍 500，同一条报错**。
- 根因：`core/openvpn_manager.py:728` 的 `render_server_conf(allow_port_change=…)` 有此参数，但面板路由 `panel/app.py:993 ovpn_server()` 调它时只传 `proto/port`，把该字段丢了。报错文案指给用户的路在 API 上走不通；UI 走同一路由，同样无路。
- 唯一可用路径（core 文档字符串亦认可）是删 `/etc/openvpn/server/server.conf` 再重建——S4 改走此路。另记小观察：`POST /api/sk5 {"enabled":false}`（只带 enabled）→ 400，须同时带 host/port 才 200；部分更新被拒。
## 7. S4 TCP 备模式（443）—— S1/S2 均通过

- 切模式路径：直接改 proto/port 被 P01 拒绝（见 R2-BUG-14）；按产品认可的路删 `/etc/openvpn/server/server.conf` 后重建 → 200，`port 443 / proto tcp`，重启后 openvpn（PID 366939）监听 TCP 443，UDP 1194 无监听；alice/bob 用户与 PKI 完好（删 conf 不动 PKI），新 .ovpn 为 `proto tcp / remote 172.26.15.152 443`。
- **S1（TCP，SK5 关）**：客户端 02:11:26 连上，tun0 10.8.0.2；curl 出口 16.146.199.68，by-IP HTTP 404，dig NOERROR，NTP 48 字节 6.1ms。
- **S2（TCP，SK5 开）**：TCP 404；**UDP NTP 亦有回包**（48 字节）——本配置下 `udp_over_tcp` 在两种模式里恒为 false（原生 UDP ASSOCIATE 走 SOCKS 的 TCP 控制连接，与 OpenVPN 传输无关），任务书里预期的“UoT 模式下 NTP 超时”未出现，该担忧在本配置上不成立；面板 test_sk5：`tcp_ok: true`、`udp_ok: true`、`udp_mode: native`。sing-box 与 dante 双日志均有 34.160.111.145:80（TCP）与 162.159.200.123:123（UDP）两条流。

## 8. S0b 补验：删二进制重装（BUG-2 钉死哈希下载路径）—— 下载路径通过，安装器在 SK5 开时自家门禁报错

- 删 `/usr/local/bin/sing-box` 与 `/usr/local/bin/tun2socks` 后，`OVPN_PROTO=tcp OVPN_PORT=443 bash install.sh`：
  - **下载路径通过**：sing-box 1.11.15 下载 + `sha256 OK` + 自报 `sing-box version 1.11.15`；tun2socks 2.7.0 下载 + `sha256 OK` + 自报 `tun2socks-2.7.0`。**BUG-2 的钉死哈希下载路径首次在真机默认路径上被执行并通过。**
  - 但整轮 `EXIT=1`：死在最后的转发健康门禁——`ERROR: health gate: route lookup for VPN source 10.8.0.1 does not resolve via ens5 (1.1.1.1 from 10.8.0.1 dev tun1 table 100 …)`。门禁无条件断言 VPN 源走 ens5，而 SK5 开时流量本应走 tun1/table 100。部署本身健康（五服务 active、稳态门全过、SK5 配置未被改动：`final: bought-sk5`、table 100 仍在、面板 `via_sk5: true`），错的是门禁不是部署。
- 另探：文档默认路径 `bash install.sh`（无 env）在 TCP 443 部署上重跑 → `EXIT=1`，死在 PKI 步：`OpenVPNError: entry port is fixed at creation (FLMX P01): server.conf already uses tcp/443, refusing to change to udp/1194`。安装器重跑时不读现存 server.conf 的 proto/port、无脑套默认 udp/1194。机器本身无损（服务仍 active、配置仍 tcp/443、SK5 仍开），但**文档化的升级路径在 TCP 部署上是断的**。

## 9. 收尾确认与本轮 bug 清单

- 收尾（两次重装后）：客户端经 TCP 443 重连（02:13:32），TCP 经 SK5 HTTP 404、NTP 经 SK5 回 48 字节——部署仍可用。同期日志有 alice 的逗号 v2 行（`CLIENT_LIST,alice,10.200.0.2:58134,10.8.0.2,,4914,4643,…`），面板仍报 `online_users: 0`、`clients: []`——**R2-BUG-13 在最终态再确认**。
- 第一轮 9 bug 复验结论：BUG-3 修好（sing-box restarts=0）、BUG-4 修好（用户列表无 CA）、BUG-6 修好（重装真重启）、BUG-7 修好（CN 各为用户名）、BUG-8 修好（S1 首次即通零手工规则）、BUG-5 本体通（绕行后 poll + 命令链）、BUG-9 **未修好**（见 R2-BUG-13，第三次）、BUG-2 下载路径本轮首次真机执行通过、BUG-1 未在本轮单独复验（tun 字段，S1/S4 隧道均正常建起，间接通过）。
- 本轮新发现（全部未修，只记录）：
  - **R2-BUG-10（阻塞）**：全新安装的 /opt 树缺 agent/，面板下发 agent 三路全断（/install-agent.sh 404、sha256 500、bundle 无 agent 代码）。
  - **R2-BUG-11（阻塞）**：install-agent.sh 取包先于 TOFU 信任锚，默认自签面板上永远装不上（--insecure 亦然）。
  - **R2-BUG-12（阻塞）**：面板安装命令不带 --node-name，agent 默认主机名与注册名不符，poll 恒 401。
  - **R2-BUG-13（中）**：BUG-9 第三次未真修——部署态日志是逗号分隔 v2，解析器丢弃，在线用户恒 0（沙箱复现 []）。
  - **R2-BUG-14（中）**：面板 API 无任何办法改入口端口，报错指引的 allow_port_change 在路由层被丢弃。
  - **R2-BUG-15（中）**：install.sh 转发健康门禁不认 SK5 开态，SK5 开时重装即误报 EXIT=1。
  - **R2-BUG-16（中，BUG-14 同族）**：install.sh 重跑不继承已部署 proto/port，文档升级路径在 TCP 部署上 EXIT=1。
- **结论：不能交付。** S0–S4 流量面全过，但 agent 默认安装链三处断点（R2-BUG-10/11/12）使“面板一键装 agent”在全新安装上是死的，且在线用户统计第三次未真修（R2-BUG-13）。

## 10. 观察与最大风险（非阻塞）

- 默认 `.ovpn` remote 仍是内网 IP：`panel.env` 写死 `OPENVPN_SERVER_IP=172.26.15.152`，`_outward_ip()` 优先级使公网探测被遮蔽；须用户手填/点探测（server_ip 覆盖本身已验证生效）。
- `policy_routing_active=true` 但 table 100 为空时（SK5 关）旗标易误读：它只反映 rule 存在，不反映有效路由。
- `POST /api/sk5` 只带 `{"enabled":false}` → 400，须同时带 host/port；部分更新被拒（小毛病）。
- 最大风险：**agent 是本产品的核心交付面（面板→agent 命令链），而全新安装上它的起点三处全断**——用户按文档走一遍就会卡在装 agent 第一步；其次是在线用户统计三轮修三次仍错，说明解析器夹具的推导方法本身有系统性盲点（v2 一律当 TAB），修之前须先把“状态文件恒逗号分隔”钉进夹具生成规则，否则第四次还会错。
- 测试机现状（收尾时）：TCP 443 部署，五服务 active，SK5 开（dante 替身），alice 客户端在线；测试绕行仍在（/opt 树手工补的 agent/、系统信任库里的面板证书）；FLMX 进程未碰。测试产物：`/root/r2/`、`/root/install-r2.log`、`/root/r2/install-s0b.log`、`/root/r2/install-defaults.log`。

### R2-BUG-15（中）：install.sh 的转发健康门禁不认 SK5 开态，重装即误报失败

- 重跑安装器时 SK5 已开 → 门禁断言 `10.8.0.1` 走 ens5，实测走 tun1/table 100（正确行为）→ 门禁 ERROR、整轮 EXIT=1。门禁须按模式分支（SK5 开预期 tun1/table 100，关预期 ens5）。

### R2-BUG-16（中，R2-BUG-14 同族）：install.sh 重跑不继承已部署的 proto/port

- 默认 `bash install.sh` 在 TCP 部署上必死于 P01（见 §8 另探）。安装器应在 server.conf 已存在时继承其 proto/port（或至少在重跑时先读现值），否则 TCP 用户无法走文档升级路径。


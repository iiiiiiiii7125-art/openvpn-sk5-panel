# live-verify-R20 — R35 域名反代功能真机验证（发 1.0.2 前）

- **日期**：2026-11-13
- **机器**：Lightsail Debian 12，公网 16.146.199.68，tailnet 100.110.88.49
- **被测树**：工作树（未提交，R35 域名反代功能＋R35 三 P2 修复全含，R36 已判可交付 ∅），git main @ cc56952 "Docs: install commands are paste-ready on the server, no ssh wrapper"，传至机上 `/root/r20/repo`
- **域名**：`16-146-199-68.sslip.io`（另用点分 `16.146.199.68.sslip.io` 作换域格，两者均解析到 16.146.199.68）

## §0 被测树状态（传输前，2026-11-13）

- `git status --short`：M README.md、docs/DELIVERY.md、docs/security.md、install.sh；新增 docs/audit/AUDIT-R35.md、AUDIT-R36.md、tests/r35_domain_failpath.sh、tests/r35_domain_reverse_proxy.sh、tests/r35_proxyfix_xff.py
- sha256（关键文件，传输前）：
  - install.sh `77217e16e77cab268f2945bc9fd17572694e2a3db435123c5c98ff9e5e62187c`
  - egress/sk5_manager.py `6eaf4d59ec350bd8135cd71001f7eeb348e53f43315640af50702653fd52e9be`
  - egress/policy-routing.sh `fbfb29a49164937a496018fba62a43356864aacd9dfbf82e1c422ba4a252ec04`
  - panel/app.py `f7f60fa53bd05fb4337e4a114df4144b9e609ab86471e511be95a72555757710`
  - cloudflare/src/index.js `71c33ffe46c7498738ed23d4c9e6d0439f1cda4be9d494923e2117b2f36b2696`
- 机上复核：5 个关键文件 sha256 与传输前记录**逐位一致**（机上 `sha256sum` 输出与上表相同）；`releases/ovpn-release-1.0.1.tar.gz` sidecar 校验 OK（须在 repo 根目录跑，`releases/ovpn-release-1.0.1.tar.gz: OK`）。

## §1 机上初态、DNS 与安装准备

- **DNS（机上实测，2026-11-13 05:47 UTC）**：`getent hosts 16-146-199-68.sslip.io` → `16.146.199.68`；`getent hosts 16.146.199.68.sslip.io` → `16.146.199.68`。域名格**未被 DNS 阻塞**（沙箱侧的解析返回 198.18.x.x 是沙箱出口代理的拦截假象，机上解析正确）。
- 机上初态：live-19 终态部署仍在运行（openvpn-server@server、panel、sing-box、danted 均 active；ovpn-agent inactive；SK5 禁用，表 100 空）。证据 tarball r7–r19 在位，未动。
- **意外机上状态**：`caddy.service` 被 **masked**（`/etc/systemd/system/caddy.service -> /dev/null`，2025-10-30 旧残留，早于本项目）；caddy 包为 `rc` 态（已卸载、仅剩配置文件），`which caddy` 无；`/etc/caddy/Caddyfile` 为 stock 默认 `:80` 文件站。处理：清理时 `systemctl unmask caddy`（旧残留清除，记为观察 O-R20-1：安装器不 unmask——masked 单元上 `enable --now` 会失败走 warn 分支）；stock Caddyfile **保留**，以验安装器的托管段合并（只剥离旧托管段、保留其余内容）。
- 清理（live-19 同款）：停 openvpn-server@server、panel、singbox、policy、healthcheck timer、ovpn-agent；删 `/opt/openvpn-sk5-panel`、`/etc/openvpn`、`/etc/openvpn-sk5-panel`；删 ufw 1194/udp 与 8443/tcp 两条规则以验安装器重加；dante 保留；FLMX 与 `/root/scratch-nodeconnlog/` 未碰。磁盘 84%（9.1G 空闲）。
- 传输：工作树 tar 经 tssh 管道至 `/root/r20/repo`（排除 .git、__pycache__、*.pyc），5.3M。

## §2 升级路径（1.0.1 包 → r20 树重跑，存量数据无损）

- **1.0.1 安装**：`/root/r20/pkg101` 解包，`nohup bash install.sh`（stdin /dev/null），PID 175880；约 2 分钟完成，健康门 `[install] panel health gate passed (login + /api/status 200)`，panel steady `restarts=0`；事后实测 login 200＋status 200。1.0.1 安装器无 ERRORS 计数器，健康门即其验收。管理员密码新鲜生成（admin.pass 0600）；新 CA serial `0E6B779EB0A1B7D69FAEC29FF0BDBB3560419503`（notBefore Nov 13 05:52:49 GMT）；panel/data/ 仅新鲜 panel.db（32768 B）。
- **存量数据（1.0.1 上创建）**：server udp/1194（200）；用户 alice valid，serial `3EB3711C05A16BE916799F994D103F66`（200）；openvpn PID 176542；egress 直连 IPv6 `2600:1f13:…`，via_sk5 false。
- **重跑前快照**（`/root/r20/up-before.txt`）：admin `(1, $2b$12$gdJMzE3GJWeP8HaHsdQmt.G7C7SU2eNsHF4SuMy3LRPcbx9PkSynm, session_version 1)`；audit_log 5 行，末行 `openvpn_user_create name=alice`；CA serial `0E6B779E…`；index.txt `7fe75132af0a`；sk5.json **不存在**（SK5 从未配置，面板尚未建该文件——预期内）；panel.db `db43da285b48`；openvpn MainPID=176542；panel.env 无域名变量（1.0.1 无此功能）。
- **r20 重跑（交互安装）**：pty 驱动 PID 178496，日志 `/root/r20/install-r20.log`；安装器完成横幅已印、健康门 `[install] panel health gate passed (login + /api/status 200)`、三单元 steady restarts=0；管理员密码与 1.0.1 相同（重跑未轮换）。**但域名未应用——见 R20-BUG-1。**（驱动小瑕疵：子进程退出时 EIO 先于 reap，`/root/r20/install-r20.exit` 写成 `None`；安装结果以日志横幅＋健康门为准，非驱动问题。）
- **重跑后快照对比（升级路径前半）**：admin 行字节一致（`$2b$12$gdJMzE3G…`，session_version 1）；audit_log 5→6，唯一新增行仅安装器健康门登录；alice 仍 valid；CA serial 不变 `0E6B779E…`；index.txt 不变；openvpn MainPID 不变 176542；sk5.json 仍不存在（从未配置）。**升级路径数据面通过，待域名格走完后补终态核对。**

## §3 域名格 1——交互安装＋真实 Let's Encrypt 证书

**交互路径 FAIL——新 bug R20-BUG-1（P1）：**

- **现象（机上实证）**：pty 下输入 `16-146-199-68.sslip.io`，安装器日志 `[install] WARN: invalid panel domain '面板域名（留空则不设反代，直接用 https://172.26.15.152:8443）: 16-146-199-68.sslip.io' -- must be a bare domain (no scheme, port or path); this domain is not applied`。域名未应用：无 Caddy 安装、无 Caddyfile 托管段、panel.env 无三变量。安装其余部分正常完成（健康门过）。
- **根因（已在沙箱复现，机制钉死）**：`_resolve_panel_domain`（install.sh:694-702）把提示语 `printf '面板域名（留空…）: '` 打到 **stdout**，而调用点 `_PANEL_DOMAIN="$(_resolve_panel_domain || true)"` 用命令替换捕获 stdout——提示语与 `_trim` 输出一并被捕获，`_normalize_panel_domain` 必然判非法。沙箱 pty 复现：`CAPTURED=[面板域名（留空则不设反代，直接用 https://127.0.0.1:8443）: tty.example.com]`。即**交互填域名永远不可能成功**——不是输入问题，是提示语污染了返回值。
- **为什么 R35 探针没 catch**：`tests/r35_domain_reverse_proxy.sh` 的 TTY 格（:103-108）只数 typescript 里域名出现次数 ≥2（一次 pty 回显＋一次被污染的捕获值输出），从未断言捕获值干净、也从未走 `_PANEL_DOMAIN=$(...)`＋`_normalize_panel_domain` 的完整路径。探针形状缺口，非产品行为误判。
- **修法方向**：提示语改打 stderr（`>&2`），仅 `_trim` 的输出留在 stdout。
- **影响面**：1.0.2 头条功能（用户明确要求的交互填域名）的主路径全灭；绕行方式是 `OVPN_PANEL_DOMAIN` 环境变量（该路径正常，见下），面板本身仍可用 IP 访问，故定 P1 非 P0。
- **本轮处理**：域名格 2–5 与反代机制改走 env 路径继续验证（以隔离“反代机制”与“交互提示”两个变量）；交互路径待修复后重验。
- **env 路径安装**：`OVPN_PANEL_DOMAIN=16-146-199-68.sslip.io bash install.sh`（stdin /dev/null），PID 180409：域名解析自检过（`resolves to this server`）；Caddy 2.11.9 从官方 apt 源装上（`Setting up caddy (2.11.9)`）；ufw 放行 80/443；Caddyfile 托管段已写盘（stock `:80` 块保留——合并逻辑成立；托管段含 `reverse_proxy https://localhost:8443`＋`tls_trusted_ca_certs /etc/openvpn-sk5-panel/panel-cert.pem`）；`caddy validate` 通过（无 validate 告警）。**但 Caddy 起不来——见 R20-BUG-2。**

**新 bug R20-BUG-2（P1）：Caddy 永远起不来——panel-cert.pem 在 0700 目录里，caddy 用户读不到：**

- **现象（机上实证）**：安装器 `[install] WARN: caddy is not running after start -- skipping the reverse proxy`；`journalctl -u caddy`：`loading initial config: ... making TLS client config: failed reading ca cert: open /etc/openvpn-sk5-panel/panel-cert.pem: permission denied`；caddy.service `Failed with result 'exit-code'`。
- **根因（已核实）**：install.sh:438-439 `mkdir -p $CONFIG_DIR` 后 `chmod 700 $CONFIG_DIR`（该目录含 admin.pass／secret.key／panel-key.pem，0700 本身正确）；Caddyfile 的 `tls_trusted_ca_certs` 却指向该目录内的 panel-cert.pem；Debian caddy 单元以 `User=caddy` 运行（机上核实），无法穿越 0700 目录。`caddy validate` 是 root 跑的，必然通过——校验遮住了这个失败，安装器只在起服务时才撞上。**新鲜安装上反代永远起不来**，与 BUG-1 独立（修 BUG-1 仍会被 BUG-2 挡住）。
- **修法方向**：安装器把公开的 panel-cert.pem 复制一份到 caddy 用户可读处（如 `/etc/caddy/panel-cert.pem`，0644），Caddyfile 引用该路径；每次重跑都重拷（证书轮换时能跟上）。只拷公开证书，绝不拷 panel-key.pem。
- **观察 O-R20-2**：Caddy 2.11.9 对 `tls_trusted_ca_certs` 打 deprecation warn（`root_ca_pool and root_ca_pem_files are deprecated`）——现为 warn、不致命，但上游未来可能移除该指令，值得跟进。
- **本轮处理（测试侧 workaround W1，已披露、非产品行为）**：机上 `install -m 0644 /etc/openvpn-sk5-panel/panel-cert.pem /etc/caddy/panel-cert.pem`，Caddyfile 托管段的路径 sed 成 `/etc/caddy/panel-cert.pem`，`systemctl start caddy`；并手动补齐安装器成功路径才会写的 panel.env 三变量（`OVPN_PANEL_DOMAIN=16-146-199-68.sslip.io`／`OVPN_PANEL_HTTPS=1`／`OVPN_TRUSTED_PROXY=1`）＋手动重启面板。W1 每次 install.sh 重跑后须重做（安装器会重写 Caddyfile 托管段并重写 panel.env），下文每次重跑处均注明。

**env 路径＋W1 后，格 1 基础设施全部成立：**

- **真实 Let's Encrypt 证书**：`openssl s_client`：issuer `C = US, O = Let's Encrypt, CN = YE1`，subject `CN = 16-146-199-68.sslip.io`，notBefore Nov 13 05:05:03 GMT，notAfter Feb 11 05:05:02 2027（90 天）；journal：`certificate obtained successfully`，order `https://acme-v02.api.letsencrypt.org/acme/order/3992956202/581695422072`，HTTP-01 一次成功。
- Caddy active，监听 `*:80` 与 `*:443`（PID 182517）。
- `https://16-146-199-68.sslip.io`：/api/me 200、login 200（`{"ok": true}`）、/api/status 200（openvpn PID 176542）、首页 200（68,693 字节）。
- `https://172.26.15.152:8443` 直接访问：同款 200，**直连保留**。
- 面板手动重启后 `NRestarts=0`（与 R35 交接 (b) 一致：手动重启清零计数）。

## §4 域名格 2——限流透过反代看到真实客户端 IP

**通过。**

- 方法：两独立 netns（rl-a 10.201.0.2、rl-b 10.201.1.2，各自 veth 对＋默认路由）；登录请求走域名，TCP 目标用 `--resolve …:172.26.15.152`（LAN IP）——机上实测 netns 直连公网 IP 16.146.199.68 不通（ping 100% 丢包）：该公网 IP 不在机上接口上，是 Lightsail 边缘 1:1 NAT，netns 源地址 10.201.x 出 edge 即被反欺骗丢弃；属测试夹具路由约束，非产品问题。SNI/Host 仍为域名，Caddy 按域名选站、XFF 携带 netns 真实源 IP，限流判定不受 TCP 目标影响。
- 结果（`/root/r20/rl-test2.log`）：rl-a 5 次错密 → **401×5**，第 6 次 → **429**（锁住）；随后 rl-b 正确密码 → **200**（未被 rl-a 的锁定波及）。
- 地面真值：`login_attempts` 表行 `('10.201.0.2', '[]', 1794551129.93…)`——失败记在**真实客户端 IP 10.201.0.2** 名下，不是 127.0.0.1。ProxyFix 透传成立；若信任未开，全域名用户会被记成 127.0.0.1、一人 5 错即锁全部人（install.sh:730-733 注释点名的模式），本格证伪了该失效。
- 夹具注记：首轮 rl-test.sh 全 000——同为上述 hairpin 原因（公网 IP 目标），且脚本中途随 tssh 断线被杀、只落 5 行；纠正目标 IP 后重跑通过。测试残留：10.201.0.2 的锁定行（15 分钟），轮末清理。

## §5 域名格 3——换域重跑（点分域名）＋健康门禁零重启

**半通过——换域机制成立，安装器成功路径被 BUG-2 挡住：**

- 重跑：`OVPN_PANEL_DOMAIN=16.146.199.68.sslip.io bash install.sh`（stdin /dev/null），PID 185317；域名解析自检过。
- **Caddyfile 托管段已被替换**：点分域名块在位，旧横线域名计数 0——安装器的“剥离旧托管段＋追加新块”逻辑成立。
- **但换域未生效（BUG-2 的连锁）**：安装器重写 Caddyfile 后 `reload` 失败（新配置仍指 0700 目录内的证书，caddy 用户读不到）→ `restart` 亦失败 → **Caddy 被这次重起杀死（inactive）**，安装器走失败分支：`WARN: caddy is not running after start`，并触发 R35-P2-1 恢复：`keeping previously configured panel domain 16-146-199-68.sslip.io in panel.env`——**恢复逻辑本身活证成立**（panel.env 仍为横线域名三变量，未被清空）。
- **W1 续接（测试侧）**：live Caddyfile 路径 sed 成 `/etc/caddy/panel-cert.pem` 后 `systemctl start caddy`；点分域名 LE 证书一次办下（issuer `O = Let's Encrypt, CN = YE1`，subject `CN = 16.146.199.68.sslip.io`，90 天）；panel.env 手动改点分域名＋手动重启面板（MainPID 182974→187392），**NRestarts=0**。
- 换域后核验：点分域名 login 200、status 200（openvpn PID 176542 未动）；直连 IP:8443 仍 200；旧横线域名 TLS 握手失败（已无对应站点——替换生效的反证）。
- **交接 (b) 未完全证实**：本轮安装器未走“域名变化→重启面板→健康门禁查 NRestarts=0”的成功路径（失败分支根本没重启面板）；手动重启清零 NRestarts 的性质已在 §3 证实，安装器自身的重启＋门禁组合须待 BUG-2 修复后重验。安装器本轮健康门本身通过（panel steady restarts=0，login＋status 200）。

## §6 域名格 4——空域重跑保留已配域名（R35-P2-1 活证）

**半通过——保留逻辑成立，Caddy 存活被 BUG-2 挡住：**

- 重跑：无 env、无 TTY（stdin /dev/null），PID 187572；安装器取 `_PREV_PANEL_DOMAIN`（点分）作“不改动”。
- **panel.env 三变量全保留**：`OVPN_PANEL_DOMAIN=16.146.199.68.sslip.io`、`OVPN_PANEL_HTTPS=1`、`OVPN_TRUSTED_PROXY=1`——R35-P2-1 的“空重跑不丢信任变量”活证成立（本轮第二次触发恢复分支，见下）。
- **Caddyfile 点分域名块仍在位**（重建后仍为点分域名）——域名配置本身未被丢弃。
- **但 Caddy 未存活（BUG-2）**：安装器重建 Caddyfile 后 `reload` 失败→`restart` 失败→Caddy `failed`，日志 `[install] WARN: caddy is not running after start`；恢复分支随即把三变量写回 panel.env（日志 `keeping previously configured panel domain …`）。即：保留逻辑走了失败分支而非成功分支——变量保住了，但服务没保住。
- W1 续接后：Caddy active，点分域名 login 200、status 200，直连 IP 200——域名本身可继续服务，丢的只是安装器重跑时的服务连续性。
- 安装器健康门本轮通过（panel steady restarts=0，login＋status 200）。

## §7 域名格 5——Caddy 停机失败路径（R35-P2-1 活证）

**通过（注入式失败，与 BUG-2 无关的干净验证）。**

- 注入：`systemctl stop caddy && systemctl mask caddy`（与 BUG-2 的证书权限问题无关的干净失败——`enable --now` 直接撞 masked 单元）。
- 重跑：`OVPN_PANEL_DOMAIN=16.146.199.68.sslip.io bash install.sh`，PID 189149。日志：`WARN: failed to start caddy`（line 19）＋`WARN: caddy is not running after start`（line 20）＋`keeping previously configured panel domain 16.146.199.68.sslip.io in panel.env`（line 21）——R35-P2-1 恢复逻辑在注入失败下如设计触发。
- 重跑后核验：panel.env 三变量全在（DOMAIN 点分／HTTPS=1／TRUSTED_PROXY=1）；面板 `https://172.26.15.152:8443` 登录 200、/api/me 200——**失败时面板仍可用 IP 访问**；Caddyfile 点分域名块在位（重建内容一致）。
- 恢复：`systemctl unmask caddy`＋W1 sed＋`systemctl start caddy`→ active；点分域名 login 200、status 200，直连 IP 200。
- 注：domain-login.py 在本格首轮因域名请求抛 SSLError 而中途退出（脚本无 try/except）——探针脚本自身问题，已改用单点 curl 重测 direct-ip 200，不属产品问题。

## §8 S0–S4 回归

- **S0 安装一次成功**：1.0.1 包安装（PID 175880，健康门 `panel health gate passed`，panel steady restarts=0）＋r20 树重跑 5 次（交互／env 换域／空域／失败路径各一次，健康门每次通过）。注：本轮安装器无 ERRORS 计数器输出（1.0.1 亦无），验收以健康门＋三单元 steady 为准。
- **S1 直连态（UDP 1194）——通过**：alice.ovpn（8612 B，`proto udp / remote 16.146.199.68 1194`）下载 200；netns `vpntest` 内 LAN 版 remote＋`--float`；客户端 PID 191007，Initialization Sequence Completed ×1，tun0 10.8.0.2/24；curl http 200、https 200；NTP 216.239.35.4 48 B 12.5 ms、162.159.200.1 48 B 5.7 ms（直连出口）。
- **S2 SK5 落地态（dante 127.0.0.1:11080）——通过**：POST /api/sk5 200（policy_routing_active true）；POST /api/sk5/test 200：tcp_ok true（88.3 ms）、**udp_ok true**（`native UDP ASSOCIATE + DNS to 1.1.1.1:53 (example.com, reply NOERROR an=2)`——R27-P2-1 往返实证）；/api/status：enabled true、via_sk5 true、egress 16.146.199.68；表 100：`default via 10.9.0.1 dev tun1`＋`blackhole default metric 200`，rule `from 10.8.0.0/24 lookup 100`，tun1 UP LOWER_UP；同一客户端 PID 191007：curl http/https 200，NTP 48 B 34.7/26.2 ms；双证：sing-box 日志 `outbound/socks[bought-sk5]`，dante 日志 `tcp/connect`＋`udp/udpassociate`。**TCP＋UDP 双栈通过（数据面）。**
- **S3 杀 dante（断网保护）——通过**：dante stop 06:23:41：同一客户端 PID 191007：curl http exit 56、https exit 35、NTP 双服 TimeoutError——**全断无回落**；健康档 06:24:56：`last_health` = `blackholed_kill_switch`，detail `tcp_ok=False udp_ok=False egress=None`，healthy false，egress.ip=null、via_sk5=true（BS 修复后的正确 verdict）；dante start 后约 5 秒恢复（curl 200、NTP 48 B）；同一客户端 PID 191007 全程未断（elapsed 02:29），Completed 仍 ×1，tun0 10.8.0.2。**通过。**
- **S4 TCP 443——通过（五次首连全 0.20 秒），但先撞上 R20-BUG-3：**
  - **新 bug R20-BUG-3（P2）：域名反代占住 443，TCP 443 模式不可用。** 切 tcp/443（allow_port_change）→ **500**：`cannot move entry port to tcp/443: already in use by LISTEN ... *:443 users:(("caddy",pid=190576,fd=7))`。机制：R35 的 Caddy 监听 *:443，与 OpenVPN TCP 443 备模式撞口；面板侧 500 大声报错并点名 caddy、服务端保持 UDP 1194（未静默错乱），故定 P2 非 P1。R35/R36 审计的宣称清单未提及此冲突，文档亦无。修法方向：文档写明“反代启用期间 TCP 443 入站不可用”（及安装器在配反代时若服务端已是 TCP 443 应先告警）。
  - S4 本格改走“停 Caddy 再切”（测试侧处理，Caddy 停用期间域名不服务）：切 tcp/443 → 200，restart → 200（新 PID 192411），`0.0.0.0:443` 监听；杀 UDP 客户端（PID 191007，精确 PID），netns 路由干净（live-19 同款僵尸路由陷阱已避）；五次新鲜首连计时（独立进程每次）：**0.20 / 0.20 / 0.20 / 0.20 / 0.20 秒**，全部 Completed。常驻 TCP 客户端 PID 193185：curl http 200、NTP 48 B。**通过。**
  - **观察 O-R20-3（未定论，不立案）**：06:25 服务端重起（UDP 态、仅重起未换协议）后，旧 UDP 客户端发起重连（SIGUSR1＋06:25:18／06:26:19 两次 link 重建），但约 2 分钟内未见第二次 Completed、流量仍 000；随后我自己的 TCP 切换切断了该实验。无法区分“重连慢”与“重连卡住”，不立案；新鲜首连（S1/S4）均正常。

## §9 BUG-9 第 22 次复验

- **TCP 态——通过**：状态文件 `CLIENT_LIST,alice,10.200.0.2:37088,10.8.0.2,,4720,5436,2026-11-13 06:28:43,…`；面板 clients[0] 逐字段一致（name／real_address／virtual_address／bytes_received 4720／bytes_sent 5436／connected_since）；online_users 1，alice online=true、valid。
- **UDP 态——通过**：切回 udp/1194（allow_port_change，restart 新 PID 198403）后新鲜 UDP 客户端 PID 198535，Completed ×1；65 秒后状态文件 `CLIENT_LIST,alice,10.200.0.2:59816,10.8.0.2,,4090,3908,2026-11-13 06:38:34,…`，面板逐字段一致；online_users 1，alice online=true。客户端 curl 200。注：用户列表另有 `verify-1794551631`（valid，离线）与 `verify-1794551728`（revoked）——verify.sh 闭态探针自留用户，预期残留。

## §10 Headlines

### headline-1 10 次交替 delta 恰 10 —— 通过

- 复用 `/root/r18/alt10b.py`（输出 `/root/r20/alt10.log`）：setup enable/disable 各 200，窗口基线 0，10 步全部 200，window_started 1→10 逐格 +1，**delta 恰 10**。常驻 TCP 客户端 PID 193185 全程未断。

### headline-3 并发启用 delta 恰 1 —— 通过

- 从禁用态起，两路全表单启用同时发出 → **双 200**，窗口 Started +1，终态 enabled=true、policy=true、via=true、ip=16.146.199.68。`_SK5_MUTATE_LOCK` 真机并发路径成立。

### headline-5 policy-missing 诚实＋零重起修复 —— 通过

- 时序控制：停定时器，上一档健康检查已完成在删路由之前，无撞车。
- 诚实：手动删表 100 的 tun1 路由（表 100 只剩黑洞）后，面板 `/api/status`：enabled 仍 true，`via_sk5=false`、`egress.ip=None`、`policy_routing_active=false`，error「SK5 已启用但策略路由未生效，出口未经过 SK5」——未谎称经 SK5、未谎称黑洞。（last_health 为删路由前的旧档 06:32:30 healthy——定时器已停，无新档，属预期。）
- 零重起修复：全表单重开 → 200，收据 **`repaired: true`、`repair_detail: ["policy routing re-applied"]`**（为取全量收据二次复现，同证），窗口 Started delta=0；恢复后 rule＋表 100 均在位，policy=true、via=true、客户端 curl 200；定时器已恢复 active。

### headline-6 verify.sh 双态 —— 通过

- 开态（SK5 开）：**PASS=18 FAIL=0 SKIP=4**，`VERIFY: ALL GREEN`（`/root/r20/verify-open.log`）。
- 关态（面板关 SK5 后 25 秒再跑）：**PASS=23 FAIL=0 SKIP=0**，`VERIFY: ALL GREEN`（`/root/r20/verify-closed.log`）。关态跑完后 SK5 为禁用。

### headline-7 前端真渲染——通过

- 复用 `/root/r18/cdp.py`（headless Chromium，1440×900，CDP 9223，输出 `/root/r20/render/`）：**153 个可见文本元素，0 个低于 4.5**（最薄 4.92，文案「当前 .ovpn 的 remote 为公网地址 16.146.199.68，站外客户端可直连。」——与 live-19 同款最薄项），低于 7.0 者 25 个，console exception 0，截图 dashboard.png 已存档。另有一条资源 404 的网络日志（Log.entryAdded），非 JS 异常。
- live-19 为 163 元素——元素数差异系仪表盘内容随状态变化（本轮 SK5 禁用、TCP 态），门禁只看低于 4.5 者为 0。

### headline-9 毒树重跑（硬门格）——通过

- 方法：毒树＝`/root/r20/poison`（`/root/r20/repo` 全量复制＋panel/data/ 放入毒文件：`/root/r18/panel.db` bc9ed19f…、`/root/r18/agent_queue.json` 9ed78463…，含 3 条 init_pki force+confirm：8bb719af sent、7ce3cf35／8cca7b62 queued）；默认 `bash install.sh` 重跑，日志明示「panel/ installed (panel/data/ excluded: runtime state is never shipped and a re-run never touches the live database)」。
- 前后行级对照（快照脚本 `/root/r20/h9-snap.py`，前后存档 `/root/r20/h9-before.txt`／`h9-after.txt`）：
  - admin 行**字节一致**：(1, `$2b$12$gdJMzE3GJWeP8HaHsdQmt.G7C7SU2eNsHF4SuMy3LRPcbx9PkSynm`, 1)——不是毒 hash。
  - audit_log 91→97，新增 6 行逐项有主：(92) 我方登录、(93) node_register lightsail、(94) 我方登录、(95) cmd_enqueue get_status、(96) agent_report done——以上 5 行为 BEFORE 快照后、AFTER 快照前的 agent 行程活动；(97) 毒树安装器健康门登录 06:43:15——**毒树重跑本身仅新增这一行**（与 live-19 同款标准）。
  - live 队列：BEFORE 时无 agent_queue.json 文件（本轮此前无入队命令）；AFTER 有 1858 B（agent 行程的 get_status 命令记录），3 个毒 init_pki id（8bb719af／7ce3cf35／8cca7b62）在 live 队列中**零命中**——毒命令从未进入执行面。
  - sk5.json 不变（3a35d14e…）、CA serial 不变（0E6B779E…）、index.txt 不变（afb3b891…）、panel.env 域名三变量不变（点分域名）。
  - openvpn MainPID 不变（198403，未重启）；常驻 UDP 客户端 PID 198535 未断。
  - panel.db 文件哈希变了（fc2ded82…→6a89c7dc…）——系 audit 新增行所致，行级内容已逐项核对无毒化。

## §11 R35/R36 修复真机格

- **R35-P2-1（失败路径丢信任变量）——活证成立，两次**：格 3 换域重跑（Caddy reload 失败分支）与格 4 空域重跑均触发 `_restore_prev_panel_domain`，panel.env 三变量全保留；格 5 注入式失败（mask）下恢复逻辑如设计触发。R36 沙箱探针 `tests/r35_domain_failpath.sh` 8/8（修复后行为）与本轮活证一致。
- **R35-P2-2（去反代漏两变量）——文档核对通过**：README:83「去掉反代」与 DELIVERY:54 均列 `OVPN_PANEL_DOMAIN`、`OVPN_PANEL_HTTPS`、`OVPN_TRUSTED_PROXY` 三行一并删，README 另写明只删域名行、留下 `OVPN_TRUSTED_PROXY=1` 时面板仍信任伪造 XFF。两边逐字对齐。
- **R35-P2-3（卸载漏 Caddy）——文档核对通过**：README 卸载章节已有 `systemctl disable --now caddy`、删 Caddyfile 托管段（或整文件删）、`ufw delete allow 80/tcp` 与 `443/tcp`，并注明 panel.env 三行随 `rm -rf /etc/openvpn-sk5-panel` 一并删除。
- **域名反代 happy path 沙箱探针**：`tests/r35_domain_reverse_proxy.sh` 30/30（R36 已重跑）；但其 TTY 格形状缺口见 R20-BUG-1——探针只数域名出现次数，未断言捕获值干净。
- **ProxyFix/XFF**：`tests/r35_proxyfix_xff.py` 沙箱 4/4＋8/8（R36 已重跑）；本轮格 2 在真机上以真实 Caddy＋真实限流表复证（失败记在真实客户端 IP 10.201.0.2 名下）。

## §12 agent 行程与 /api/cmd 回路——通过

- 注册节点 lightsail（POST /api/nodes，panel_url 显式 `https://172.26.15.152:8443`）：201，token 43 字符（存根仅文件 `/root/r20/node-token` 0600，未进任何命令行记录）。
- 两步安装（DELIVERY.md §3）：`curl -ksSL` 下 install-agent.sh＋.sha256，`sha256sum -c` OK。首跑 EXIT=1——**安装器 fail-closed**：已存在旧 agent 安装（live-19 残留），无 --force 拒绝覆盖；--force 重跑 EXIT=0，ovpn-agent ACTIVE（MainPID 199838，node=lightsail，panel=https://172.26.15.152:8443，TOFU 钉面板证书，5 秒 poll）。
- /api/cmd 回路：POST /api/cmd get_status → 202（cmd_id c63a80837eed49b481ea1df7f61ac7ee），第 1 次 2 秒轮询即 done；result：egress_ip 2600:1f13:…（直连 IPv6，SK5 已禁用）、health chain_disabled healthy、openvpn 客户端列表。agent journal 双证：06:41:53 `cmd c63a8083… action=get_status params={}` → `done ok=True`。

## §13 终态与新 bug

### 终态（2026-11-13 06:45 UTC）

- SK5 已禁用：enabled=false、policy=false、via=false，出口恢复直连 IPv6（2600:1f13:14d:a300:7913:f273:997e:c8b8），健康档 chain_disabled healthy。
- 表 100 为空；`from 10.8.0.0/24 lookup 100` 规则 0 条（SK5 已禁用，disable 路径 flush 策略路由所致，与 live-19 终态同款）。
- 六服务全 active：openvpn-server@server（MainPID 198403，UDP 1194）、panel、sing-box、danted、ovpn-agent、caddy（点分域名，LE 证书）；healthcheck timer active。
- CA 指纹：serial 0E6B779EB0A1B7D69FAEC29FF0BDBB3560419503。
- 常驻 UDP 客户端 PID 198535 仍在（自 BUG-9 UDP 段起未断），直连 curl 正常。
- 面板域名：`https://16.146.199.68.sslip.io` 服务中（LE 证书），`https://172.26.15.152:8443` 直连亦可。panel.env 三变量在位（点分域名）。
- 测试残留已清理：rl-a/rl-b 的 login_attempts 行已删、两 netns 已删；vpntest 保留（常驻客户端 netns）；/root/ovpn-r7…r19.tar.gz 未动。
- 证据包：`/root/ovpn-r20.tar.gz`，6,721,251 字节，sha256 `9a8df8a31d3e91e9db0ee5223b4b277b37662de7f886eee9b62cac903b2599b1`（证据目录 `/root/r20/`，18 MB；pkg101 排除——1.0.1 包可从树内 releases/ 复现）。

### 新 bug：3 个

1. **R20-BUG-1（P1）：交互填域名永远失败——提示语污染了命令替换的捕获值。** `_resolve_panel_domain` 把提示语打到 stdout，调用点 `_PANEL_DOMAIN="$(_resolve_panel_domain || true)"` 一并捕获，`_normalize_panel_domain` 必然判非法。机上实证（warn 原文）＋沙箱 pty 复现（`CAPTURED=[面板域名…: tty.example.com]`）。R35 探针 TTY 格只数出现次数，未断言捕获值干净，故漏网。修法：提示语改打 stderr。1.0.2 头条功能的主路径全灭，绕行 env 变量可用。
2. **R20-BUG-2（P1）：Caddy 永远起不来——panel-cert.pem 在 0700 目录里。** install.sh:439 `chmod 700 $CONFIG_DIR`，Caddyfile 的 `tls_trusted_ca_certs` 指向其中 panel-cert.pem，caddy 单元以 `User=caddy` 运行，启动即 `permission denied`；`caddy validate` 是 root 跑的，必然通过，遮住了失败。机上实证（journal 原文）。与 BUG-1 独立。修法：安装器把公开证书复制到 caddy 可读处（如 /etc/caddy/panel-cert.pem），Caddyfile 引用该路径，每次重跑重拷。
3. **R20-BUG-3（P2）：域名反代占住 443，TCP 443 模式不可用。** 切 tcp/443 → 500（点名 caddy 占住 *:443），服务端保持 UDP 1194；大声失败、无静默错乱，故 P2。R35/R36 审计与文档均未提及此冲突。修法：文档写明，安装器配反代时若服务端已是 TCP 443 应先告警。

### 观察（不立案）

1. **O-R20-1**：机上 `caddy.service` 曾被 masked（2025-10-30 旧残留，caddy 包 rc 态）；本轮清理时 unmask。安装器不 unmask——masked 单元上 `enable --now` 会失败走 warn 分支（格 5 的注入即此路径）。
2. **O-R20-2**：Caddy 2.11.9 对 `tls_trusted_ca_certs` 打 deprecation warn（`root_ca_pool and root_ca_pem_files are deprecated`）——现为 warn、不致命，上游未来可能移除。
3. **O-R20-3**：服务端重起后旧 UDP 客户端发起重连但约 2 分钟内未见第二次 Completed（后被我自己的 TCP 切换切断实验）——未定论，不立案。
4. **探针／测试侧失误 4 起（均已纠正重跑，不属产品问题）**：① pty 驱动 exit 文件写 `None`（EIO 先于 reap，安装结果以日志为准）；② 首轮 rl-test 全 000——netns 直连公网 IP 遇 Lightsail hairpin 丢包，改 LAN IP 目标后通过；③ `pkill -f "openvpn.*alice"` 误杀自己的 shell（AGENTS.md 已有禁令——模式串不得出现在同一命令里）；④ domain-login.py 在域名宕机时抛错中途退出（无 try/except），改单点 curl 重测。

## §14 结论

**live-20 不能放行 1.0.2——3 个新 bug，其中 2 个 P1 挡住头条功能。**

- 域名反代的机制本身在真机上成立（env 路径＋测试侧 workaround W1 下）：真实 Let's Encrypt 证书两次办下（横线＋点分域名）、Caddyfile 托管段替换与合并成立、限流透过 ProxyFix 看到真实客户端 IP（401×5→429，另一 IP 200，失败记在 10.201.0.2 名下）、换域／空重跑／注入失败下 R35-P2-1 的信任变量保留逻辑三次活证、R35-P2-2／P2-3 文档核对通过。
- 但**产品原样交付的反代是起不来的**：交互填域名必被自己的提示语污染而拒绝（R20-BUG-1，P1）；即使走 env 变量，Caddy 也因证书权限起不来（R20-BUG-2，P1）；且反代占住 443 使 TCP 443 备模式不可用（R20-BUG-3，P2，文档未提）。
- 回归面全绿：S0–S4、BUG-9 第 22 次双模、headline-1/3/5/6/7/9、R35/R36 修复格、agent 行程＋/api/cmd 回路、升级路径（1.0.1→r20 存量无损）全部通过；R36 的可交付结论在回归面成立，但在域名功能面不成立。
- 待修复后重验：交互提示（stderr）、证书可读路径、443 冲突文档／告警；重验时须复核格 1（交互真装）、格 3 成功路径（含交接 (b) 安装器重启＋门禁零重启组合）与格 4 成功路径。

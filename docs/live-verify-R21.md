# live-verify-R21 — R37/R38 修复＋域名反代功能真机重验（发 1.0.2 前）

- **日期**：2026-11-13
- **机器**：Lightsail Debian 12，公网 16.146.199.68，tailnet 100.110.88.49
- **被测树**：工作树（未提交，R39 已判可交付 ∅），git main @ cc56952，传至机上 `/root/r21/repo`
- **域名**：`16-146-199-68.sslip.io`（格 1 交互安装），`16.146.199.68.sslip.io`（格 3 换域）

## §0 被测树状态（传输前，2026-11-13）

- `git status --short`：M README.md、docs/DELIVERY.md、docs/security.md、install.sh；新增 docs/audit/AUDIT-R35.md、AUDIT-R36.md、AUDIT-R37.md、AUDIT-R38.md、AUDIT-R39.md、docs/live-verify-R20.md、tests/r35_domain_failpath.sh、tests/r35_domain_reverse_proxy.sh、tests/r35_proxyfix_xff.py、tests/r37_bug3_guard_prev_domain.sh、tests/r37_caddyfile_mode_umask.sh、tests/r38_runbook.sh
- sha256（关键文件，传输前）：
  - install.sh `5a347d3717b22d2f0f67f4b8f8e8351d932a4061cf465ac5546c529b31e437b1`（与 AUDIT-R39 §0 记录 `5a347d3717b2…` 一致）
  - egress/sk5_manager.py `6eaf4d59ec350bd8135cd71001f7eeb348e53f43315640af50702653fd52e9be`
  - egress/policy-routing.sh `fbfb29a49164937a496018fba62a43356864aacd9dfbf82e1c422ba4a252ec04`
  - panel/app.py `f7f60fa53bd05fb4337e4a114df4144b9e609ab86471e511be95a72555757710`
  - cloudflare/src/index.js `71c33ffe46c7498738ed23d4c9e6d0439f1cda4be9d494923e2117b2f36b2696`
- 机上复核：5 个关键文件 sha256 与传输前记录**逐位一致**（机上 `sha256sum` 输出与上表相同）；`releases/ovpn-release-1.0.1.tar.gz` sidecar 校验 OK（须在 repo 根目录跑，`releases/ovpn-release-1.0.1.tar.gz: OK`）。

## §1 机上初态、DNS 与安装准备

- **DNS（机上实测，2026-11-13 07:36 UTC）**：`getent hosts 16-146-199-68.sslip.io` → `16.146.199.68`；`getent hosts 16.146.199.68.sslip.io` → `16.146.199.68`。域名格**未被 DNS 阻塞**（沙箱侧的解析返回 198.18.x.x 是沙箱出口代理的拦截假象，机上解析正确）。
- 机上初态：live-20 终态部署仍在运行（openvpn-server@server、openvpn-sk5-panel、openvpn-sk5-singbox、danted、ovpn-agent、caddy 均 active；healthcheck timer waiting；SK5 禁用，表 100 空）。证据 tarball r7–r20 在位，未动（`/root/ovpn-r20.tar.gz` sha256 复核 `9a8df8a31d3e…` 与 live-20 记录一致）。
- 清理（live-20 同款）：停 openvpn-server@server、openvpn-sk5-panel、openvpn-sk5-singbox、openvpn-sk5-policy、ovpn-agent、caddy（stop＋disable）、healthcheck timer；删 `/opt/openvpn-sk5-panel`、`/etc/openvpn`、`/etc/openvpn-sk5-panel`、`/etc/caddy`、`/var/lib/caddy`、`/root/r20/repo`；删 ufw 1194/udp、8443/tcp、80/tcp、443/tcp 四条规则（v4＋v6 均删净，事后 grep 零命中）以验安装器重加；dante 保留；FLMX（flmx_agent active、flmx-agent-restart timer）与 `/root/scratch-nodeconnlog/` 未碰。磁盘 85%（8.8G 空闲）。
- 传输：工作树 tar 经 tssh 管道至 `/root/r21/repo`（排除 .git、__pycache__、*.pyc），5.4M；机上 install.sh sha256 `5a347d3717b2…` 与传输前一致。

## §2 升级路径（1.0.1 包 → r21 树重跑，存量数据无损）

- **1.0.1 安装**：`/root/r21/pkg101` 解包（tarball 内含顶层 `openvpn-sk5-panel/` 目录，首跑因在错误目录执行 install.sh 而 exit 127——测试侧路径失误，已纠正重跑，非产品问题）；`nohup bash install.sh`（stdin /dev/null），约 2 分钟完成，健康门 `[install] panel health gate passed (login + /api/status 200)`，exit 0；panel＋openvpn active；管理员密码新鲜生成（admin.pass 0600）；新 CA serial `56612C1D1AE50D132B1390E2A63093B0861D10D3`。
- **存量数据（1.0.1 上创建）**：server udp/1194（200）；用户 alice valid，serial `E1BA51D4BDC2C7285568A6B85CBEF406`（200）；openvpn PID 221372；egress 直连 IPv6 `2600:1f13:…`，via_sk5 false。
- **重跑前快照**（`/root/r21/up-before.txt`）：admin `(1, $2b$12$tD.aKe4BtoYygx7HXAZ6uu0dsq93o6FwrCsehfOCZ56BWUXbuUFV., session_version 1)`；audit_log 4 行，末行 `openvpn_user_create name=alice`；CA serial `56612C1D…`；index.txt `23b2086b5d103321`；sk5.json **不存在**（SK5 从未配置，面板尚未建该文件——预期内）；panel.db `bcaada8c7c79b827`；openvpn MainPID=221372；panel.env 无域名变量（1.0.1 无此功能）。
- **r21 重跑（交互安装，见 §3）**：pty 驱动（`/root/r21/pty-install.py`，live-20 驱动改进版：正确 wait 取 exit 码），安装器 exit 0，健康门过，管理员密码与 1.0.1 相同（重跑未轮换）。
- **重跑后快照对比**（`/root/r21/up-after.txt`）：admin 行**字节一致**（`$2b$12$tD.aKe4B…`，session_version 1）；audit_log 4→7，新增 3 行逐项有主：(5) 安装器健康门登录 `ip=127.0.0.1`（毒树重跑本身仅新增这一行，与 live-19/20 同款标准）、(6) 我方域名登录 `ip=16.146.199.68`、(7) 我方直连登录 `ip=172.26.15.152`——以上 (6)(7) 为快照前的我方验证登录；alice 仍 valid；CA serial 不变 `56612C1D…`；index.txt 不变；openvpn MainPID 不变 221372；sk5.json 仍不存在（从未配置）；panel.env 新增域名三变量（见 §3）。**升级路径数据面通过。**

## §3 域名格 1——交互安装＋真实 Let's Encrypt 证书

**通过——R20-BUG-1 与 R20-BUG-2 均已修复，交互真装全程无 workaround。**

- **交互路径成立（R20-BUG-1 关闭）**：pty 下输入 `16-146-199-68.sslip.io`，安装日志中 `invalid panel domain` 出现 **0 次**；panel.env 得 `OVPN_PANEL_DOMAIN=16-146-199-68.sslip.io`（提示语已改 stderr，捕获值干净——与 R35 探针 46/46 的 TTY 全路径断言一致）。
- **证书可读路径成立（R20-BUG-2 关闭）**：安装器把公开证书拷到 `/etc/caddy/panel-cert.pem`（0644），Caddyfile 引用该路径；`/etc/caddy` 目录 0755、Caddyfile 0644；`caddy validate` 通过（安装器以 caddy 用户跑 validate，无告警）。
- **真实 Let's Encrypt 证书**：`openssl s_client`：issuer `C = US, O = Let's Encrypt, CN = YE2`，subject `CN = 16-146-199-68.sslip.io`，notBefore Nov 13 06:46:05 GMT，notAfter Feb 11 06:46:04 2027（90 天）；journal：`certificate obtained successfully`，order `https://acme-v02.api.letsencrypt.org/acme/order/3993213292/581726634152`，HTTP-01 一次成功。
- Caddy active，监听 `*:80` 与 `*:443`。
- `https://16-146-199-68.sslip.io`：login 200（`{"ok": true}`）、/api/status 200（openvpn PID 221372，udp）、首页 200（68,693 字节）。
- `https://172.26.15.152:8443` 直接访问：同款 200，**直连保留**。
- 面板重启后 `NRestarts=0`（待格 3 再验安装器驱动的组合）。

**测试侧清理事故（已纠正，非产品问题，见 O-R21-1）**：清理时我把包所属目录 `/var/lib/caddy` 一并删了（`rm -rf`），caddy 以 User=caddy 运行时无法在 `/var/lib` 下重建该目录，首次启动时证书任务失败（`mkdir /var/lib/caddy: permission denied`，安装器域名健康检查走 warn-only 分支）。恢复：手动 `mkdir -p /var/lib/caddy && chown caddy:caddy && chmod 755` 后 `systemctl restart caddy`，LE 证书一次办下。安装器本身从不删该目录；全新安装时 .deb 自带该目录（caddy:caddy 0755）。

## §4 域名格 2——限流透过反代看到真实客户端 IP

**通过。**

- 方法：两独立 netns（rl-a 10.201.0.2、rl-b 10.201.1.2，各自 veth 对＋默认路由——live-20 轮末已删，本轮重建）；登录请求走域名，TCP 目标用 `--resolve …:172.26.15.152`（LAN IP，避 Lightsail hairpin）。
- 结果（`/root/r21/rl-test2.log`）：rl-a 5 次错密 → **401×5**，第 6 次 → **429**（锁住）；随后 rl-b 正确密码 → **200**（未被 rl-a 的锁定波及）。
- 地面真值：`login_attempts` 表行 `('10.201.0.2', '[]', 1794556912.02…)`——失败记在**真实客户端 IP 10.201.0.2** 名下，不是 127.0.0.1。ProxyFix 透传成立。
- 清理：10.201.0.2 的锁定行已删（`DELETE FROM login_attempts`，事后 COUNT=0）。

## §5 域名格 3——换域重跑（点分域名）＋健康门禁零重启

**通过——成功路径全通，交接 (b) 本轮证实。**

- 重跑：`OVPN_PANEL_DOMAIN=16.146.199.68.sslip.io bash install.sh`（stdin /dev/null），exit 0，健康门过。
- **Caddyfile 托管段已被替换**：横线域名计数 0，点分域名计数 1——安装器的“剥离旧托管段＋追加新块”逻辑成立。
- **新 LE 证书一次办下**：issuer `C = US, O = Let's Encrypt, CN = YE1`，subject `CN = 16.146.199.68.sslip.io`，notBefore Nov 13 06:49:17 GMT，notAfter Feb 11 06:49:16 2027（90 天）。
- **面板由安装器重启**：MainPID 222872→225224；**NRestarts=0**——安装器驱动的重启＋健康门禁零重启组合（交接 (b)）**本轮证实**（live-20 未能证实）。
- 换域后核验：点分域名 login 200、status 200（openvpn PID 221372 未动）；直连 IP:8443 仍 200；旧横线域名 TLS 握手失败（000，已无对应站点——替换生效的反证）。

## §6 域名格 4——空域重跑保留已配域名（R35-P2-1 活证）

**通过——成功路径全通，Caddy 存活。**

- 重跑：无 env、无 TTY（stdin /dev/null），exit 0，健康门过。
- **panel.env 三变量全保留**：`OVPN_PANEL_DOMAIN=16.146.199.68.sslip.io`、`OVPN_PANEL_HTTPS=1`、`OVPN_TRUSTED_PROXY=1`。
- **Caddy 存活**：重跑后 `systemctl is-active caddy` = active（live-20 在此格被 BUG-2 杀死 Caddy——本轮存活）；Caddyfile 点分域名块仍在位（计数 1）；面板**未重启**（MainPID 仍 225224，NRestarts=0）。
- 重跑后核验：点分域名 login 200、status 200（openvpn PID 221372 未动）。

## §7 TCP-443 守卫真机格（R20-BUG-3 代码守卫）

**通过。**

- 触发：`OVPN_PROTO=tcp OVPN_PORT=443 OVPN_PANEL_DOMAIN=16-146-199-68.sslip.io bash install.sh`（新域名请求＋TCP 443，stdin /dev/null）。
- 安装器 exit 1，日志含大声警告原文：`域名反代需占用 443 端口，服务端当前为 TCP 443，两者冲突，本次不设反代；改用 UDP 1194 或换端口后再配域名`；随后如预期死于 `render_server_conf` 的 P01 入口口冻结（`server.conf already uses udp/1194, refusing to change to tcp/443`，exit 1——安装器重跑不移动入口口，属既定行为）。
- 反代被跳过：live Caddyfile sha256 校验 OK（字节一致），未加入横线域名块；请求的横线新域名被丢弃，panel.env 恢复为旧点分域名三变量（R37-P2-1 修复后的行为）；Caddy active。
- 面板仍在 `https://IP:8443`：直连登录 200、/api/status 200（openvpn PID 221372，udp）。
- 恢复：空重跑 exit 0、健康门过，panel.env 回到 udp/1194＋点分域名，caddy＋panel active。
- TCP 443 模式的客户端连通见 §10 S4（先停 Caddy 再经面板切换）。

## §8 R37-P2-1 真机格（守卫分支恢复旧域变量）

**通过。**

- 触发：已配点分域名＋Caddy 在跑时跑 `OVPN_PROTO=tcp OVPN_PORT=443 bash install.sh`（审计员文档化的触发方式，stdin /dev/null）。
- 安装器 exit 1（死于 P01 渲染冻结，如预期）；日志含守卫大声警告。
- panel.env **仍含旧域三变量**：`OVPN_PANEL_DOMAIN=16.146.199.68.sslip.io`、`OVPN_PANEL_HTTPS=1`、`OVPN_TRUSTED_PROXY=1`（守卫在清 `_PANEL_DOMAIN` 前调了 `_restore_prev_panel_domain`）；同时 panel.env 被重写进 `OPENVPN_PROTO=tcp`／`OPENVPN_PORT=443`（审计员已核无后果：`panel/app.py:1155-1156` 的 `_parse_server_conf` 以 server.conf 为准）。
- live Caddyfile sha256 校验 OK（字节一致）；Caddy active；点分域名登录 200。
- 恢复：空重跑 exit 0、健康门过，panel.env 回到 udp/1194＋点分域名，面板未重启（MainPID 仍 225224，NRestarts=0）。

## §9 R38-P2-1 真机格（/etc/caddy 目录模式）

**通过——两半均成立。**

- **(a) 目录缺失＋umask 077**：`systemctl stop caddy && rm -rf /etc/caddy` 后以 `umask 077` 重跑安装器，exit 0、健康门过；`/etc/caddy` 落 **0755**（非 0700），证书副本 0644 且 `runuser -u caddy -- test -r` 通过，Caddyfile 0644 且 caddy 可读，caddy active。
- **(b) 粘住的 0700 目录自愈**：预置 `/etc/caddy` 0700（caddy 事前实测读不到证书），以 `umask 077` 重跑安装器，exit 0、健康门过；目录变为 **0755**，证书 caddy 可读，caddy active，点分域名登录 200。
- 两半均无人工 chmod 介入。

## §10 S0–S4 回归

- **S0 安装一次成功**：1.0.1 包安装（健康门过，exit 0）＋r21 树重跑 7 次（交互／换域／空域／R38／R38 自愈／R37 触发／守卫触发各一次，健康门每次通过；两次预期死于 P01 渲染冻结的触发安装除外，见 §7/§8）。注：本轮安装器无 ERRORS 计数器输出（1.0.1 亦无），验收以健康门＋三单元 steady 为准。
- **S1 直连态（UDP 1194）——通过**：alice.ovpn（8612 B，`proto udp / remote 16.146.199.68 1194`）下载 200；netns `vpntest` 内 LAN 版 remote＋`--float`；新鲜客户端 PID 234377，Initialization Sequence Completed ×1，tun0 10.8.0.2/24；curl http 200、https 200；NTP 216.239.35.4 48 B 11.6 ms、162.159.200.1 48 B 5.7 ms（直连出口）。注：live-20 残留的常驻 UDP 客户端 PID 198535 已按精确 PID 杀掉（测试客户端，非产品进程）。
- **S2 SK5 落地态（dante 127.0.0.1:11080）——通过**：POST /api/sk5 200（policy_routing_active true）；POST /api/sk5/test 200：tcp_ok true（79.5 ms）、**udp_ok true**（`native UDP ASSOCIATE + DNS to 1.1.1.1:53 (example.com, reply NOERROR an=2)`）；/api/status：enabled true、via_sk5 true、egress 16.146.199.68；表 100：`default via 10.9.0.1 dev tun1`＋`blackhole default metric 200`，rule `from 10.8.0.0/24 lookup 100`，tun1 UP LOWER_UP；同一客户端 PID 234377：curl http/https 200，NTP 48 B 43.7/52.5 ms；双证：sing-box 日志 `outbound/socks[bought-sk5]`，dante 日志 `udp/udpassociate`。**TCP＋UDP 双栈通过（数据面）。**
- **S3 杀 dante（断网保护）——通过**：dante stop 08:04:10：同一客户端 PID 234377：curl http exit 56、https exit 35、NTP 双服 TimeoutError——**全断无回落**；健康档 08:04:47：`last_health` = `blackholed_kill_switch`，detail `tcp_ok=False udp_ok=False egress=None`，healthy false，egress.ip=null、via_sk5=true；dante start 后约 8 秒恢复（curl 200）；同一客户端 PID 234377 全程未断（elapsed 02:48），Completed 仍 ×1，tun0 10.8.0.2。**通过。**
- **S4 TCP 443——通过（五次首连全 0.20 秒）**：先停 Caddy（本格测试侧处理，Caddy 停用期间域名不服务；守卫本身见 §7）：切 tcp/443 → 200，restart → 200（新 PID 235630），`0.0.0.0:443` 监听；杀 UDP 客户端（PID 234377，精确 PID），netns 路由干净；五次新鲜首连计时（独立进程每次）：**0.20 / 0.20 / 0.20 / 0.20 / 0.20 秒**，全部 Completed。常驻 TCP 客户端 PID 235735：curl http 200、NTP 48 B 39.8 ms。**通过。**

## §11 BUG-9 第 23 次复验

**通过（双模）。**

- **TCP 态——通过**：状态文件 `CLIENT_LIST,alice,10.200.0.2:39700,10.8.0.2,,5382,6905,2026-11-13 08:06:38,…`；面板 clients[0] 逐字段一致（name／real_address／virtual_address／bytes_received 5382／bytes_sent 6905／connected_since）；online_users 1，alice online=true、valid。注：首轮读取时面板 clients 为空、状态文件无 CLIENT_LIST 行——状态文件约 60 秒才重写一次，首轮读在客户端连上后、下一次写盘之前（文件 TIME 08:06:15、客户端 08:06:38 连上、下次写盘 08:07:20），属检查时机问题，非产品问题；等一轮重写后逐字段一致。
- **UDP 态——通过**：切回 udp/1194（allow_port_change，restart 新 PID 236398）后新鲜 UDP 客户端 PID 236456，Completed ×1；65 秒后状态文件 `CLIENT_LIST,alice,10.200.0.2:44817,10.8.0.2,,3859,3708,2026-11-13 08:08:34,…`，面板逐字段一致；online_users 1，alice online=true。客户端 curl 200。
- 注：用户列表另有 `verify-1794551631`（valid，离线）与 `verify-1794551728`（revoked）——verify.sh 闭态探针自留用户，预期残留（live-20 同款）。

## §12 Headlines

### headline-1 10 次交替 delta 恰 10 —— 通过

- 复用 `/root/r18/alt10b.py`（输出 `/root/r21/alt10.log`）：setup enable/disable 各 200，窗口基线 0，10 步全部 200，window_started 1→10 逐格 +1，**delta 恰 10**。常驻 UDP 客户端 PID 236456 全程未断。

### headline-3 并发启用 delta 恰 1 —— 通过

- 从禁用态起，两路全表单启用同时发出 → **双 200**，窗口 Started +1，终态 enabled=true、policy=true、via=true、ip=16.146.199.68。`_SK5_MUTATE_LOCK` 真机并发路径成立。

### headline-5 policy-missing 诚实＋零重起修复 —— 通过

- 时序控制：停定时器，上一档健康检查已完成在删路由之前，无撞车。
- 诚实：手动删表 100 的 tun1 路由（表 100 只剩黑洞）后，面板 `/api/status`：enabled 仍 true，`via_sk5=false`、`egress.ip=None`、`policy_routing_active=false`，error「SK5 已启用但策略路由未生效，出口未经过 SK5」——未谎称经 SK5、未谎称黑洞。（last_health 为删路由前的旧档 healthy——定时器已停，无新档，属预期。）
- 零重起修复：全表单重开 → 200，收据 **`repaired: true`、`repair_detail: ["policy routing re-applied"]`**（嵌在 `sk5` 对象内，首查误看顶层键为 None 后二次复现取全量收据，同证），窗口 Started delta=0；恢复后 rule＋表 100 均在位，policy=true、via=true、客户端 curl 200；定时器已恢复 active。

### headline-6 verify.sh 双态 —— 通过

- 开态（SK5 开）：**PASS=18 FAIL=0 SKIP=4**，`VERIFY: ALL GREEN`（`/root/r21/verify-open.log`）。
- 关态（面板关 SK5 后 25 秒再跑）：**PASS=23 FAIL=0 SKIP=0**，`VERIFY: ALL GREEN`（`/root/r21/verify-closed.log`）。关态跑完后 SK5 为禁用。

### headline-7 前端真渲染——通过

- 复用 `/root/r18/cdp.py`（headless Chromium，1440×900，CDP 9223，输出 `/root/r21/render/`）：**153 个可见文本元素，0 个低于 4.5**（最薄 4.92，文案「当前 .ovpn 的 remote 为公网地址 16.146.199.68，站外客户端可直连。」——与 live-20 同款最薄项），低于 7.0 者 25 个，console exception 0，截图 dashboard.png 已存档。另有一条资源 404 的网络日志（Log.entryAdded），非 JS 异常。

### headline-9 毒树重跑（硬门格）——通过

- 方法：毒树＝`/root/r21/poison`（`/root/r21/repo` 全量复制＋panel/data/ 放入毒文件：`/root/r18/panel.db` bc9ed19f…、`/root/r18/agent_queue.json` 9ed78463…，含 3 条 init_pki force+confirm：8bb719af sent、7ce3cf35／8cca7b62 queued）；默认 `bash install.sh` 重跑，exit 0、健康门过，日志明示「panel/ installed (panel/data/ excluded: runtime state is never shipped and a re-run never touches the live database)」。
- 前后行级对照（快照脚本 `/root/r21/h9-snap.py`，前后存档 `/root/r21/h9-before.txt`／`h9-after.txt`）：
  - admin 行**字节一致**：(1, `$2b$12$tD.aKe4BtoYygx7HXAZ6uu0dsq93o6FwrCsehfOCZ56BWUXbuUFV.`, 1)——不是毒 hash。
  - audit_log 94→95，新增 1 行：(95) 毒树安装器健康门登录 08:18:02 `ip=127.0.0.1`——**毒树重跑本身仅新增这一行**（与 live-19/20 同款标准）。
  - live 队列：BEFORE 与 AFTER 均无 agent_queue.json 文件（本轮此前无入队命令，文件不存在），3 个毒 init_pki id（8bb719af／7ce3cf35／8cca7b62）在 live 队列中**零命中**——毒命令从未进入执行面。
  - sk5.json 不变（3a35d14e…）、CA serial 不变（56612C1D…）、index.txt 不变（cab74895d943）、panel.env 域名三变量不变（点分域名）。
  - openvpn MainPID 不变（236398，未重启）；常驻 UDP 客户端 PID 236456 未断（elapsed 11:02，curl 200）。
  - panel.db 文件哈希变了（8b694d9b…→36075e70…）——系 audit 新增行所致，行级内容已逐项核对无毒化。

## §13 R35/R36/R37/R38 修复真机格

- **R20-BUG-1（交互提示污染捕获）——活证关闭**：格 1 pty 真装，`invalid panel domain` 0 次，域名干净落盘（§3）。
- **R20-BUG-2（证书 0700 目录）——活证关闭**：格 1 证书副本 0644＋caddy 可读＋validate 以 caddy 用户通过（§3）；R38 格 (a)(b) 补证目录层（§9）。
- **R20-BUG-3（反代占 443）——活证关闭**：安装器守卫大声警告＋跳过反代（§7）；面板侧 `_port_occupant` 守卫见 §10 S4（先停 Caddy 才能切，500 拒切未在本轮重测——live-20 S4 已实证 500 点名 caddy）。
- **R35-P2-1（失败路径丢信任变量）——活证成立**：格 4 空域重跑三变量全保留（§6）；R37 格守卫分支恢复（§8）；格 3 换域成功路径未走失败分支。
- **R35-P2-2（去反代漏两变量）——文档核对通过**：README:83 与 DELIVERY:54 均列三行一并删，逐字对齐（R38 R3 逐字执行已兑现，本轮未重跑）。
- **R35-P2-3（卸载漏 Caddy）——文档核对通过**：README 卸载章节已有 `disable --now caddy`、删托管段、`ufw delete allow 80/tcp` 与 `443/tcp`、panel.env 随目录删的注（R38 R5 逐字执行已兑现，本轮未重跑）。
- **R37-P2-1（BUG-3 守卫丢信任变量）——活证关闭**：§8。
- **R37-P2-2（live Caddyfile 模式未钉）——活证关闭**：各格 Caddyfile 均 0644（§3/§9 stat 实证），umask 077 重跑后仍 0644（§9）。
- **R37-P2-3（DELIVERY 旧证书路径）——文档核对通过**：DELIVERY:49 现为 `/etc/caddy/panel-cert.pem`，与 `_CADDY_PANEL_CERT` 默认值一致。
- **R38-P2-1（/etc/caddy 目录模式未钉）——活证关闭**：§9 两半（缺失重建 0755＋粘住 0700 自愈）。
- **ProxyFix/XFF**：格 2 真机复证（失败记在真实客户端 IP 10.201.0.2 名下，§4）。

## §14 agent 行程与 /api/cmd 回路——通过

- 注册节点 lightsail（POST /api/nodes，panel_url 显式 `https://172.26.15.152:8443`）：201，token 43 字符（存根仅文件 `/root/r21/node-token` 0600，未进任何命令行记录）。
- 两步安装（DELIVERY.md §3）：`curl -ksSL` 下 install-agent.sh＋.sha256（首试误用 `/api/agent/install-agent.sh` 得 404——测试侧路径失误，正确路径为 `/install-agent.sh`，已纠正），`sha256sum -c` OK。首跑 EXIT=1——**安装器 fail-closed**：已存在旧 agent 安装（live-20 残留），无 --force 拒绝覆盖；--force 重跑 EXIT=0，ovpn-agent ACTIVE（MainPID 243509，node=lightsail，panel=https://172.26.15.152:8443，TOFU 重新钉住新面板证书，5 秒 poll）。
- /api/cmd 回路：POST /api/cmd get_status → 202（cmd_id 3a78a3d324364d728acb86deca701a94），第 2 次 2 秒轮询即 done；result：egress_ip 2600:1f13:…（直连 IPv6，SK5 已禁用）、health chain_disabled healthy、openvpn 客户端列表。agent journal 双证：08:20:42 `cmd 3a78a3d3… action=get_status params={}` → `done ok=True`。

## §15 终态与新 bug

### 终态（2026-11-13 08:21 UTC）

- SK5 已禁用：enabled=false、policy=false、via=false，出口恢复直连 IPv6（2600:1f13:14d:a300:7913:f273:997e:c8b8），健康档 chain_disabled healthy。
- 表 100 为空；`from 10.8.0.0/24 lookup 100` 规则 0 条（SK5 已禁用，disable 路径 flush 策略路由所致，与 live-20 终态同款）。
- 六服务全 active：openvpn-server@server（MainPID 236398，UDP 1194）、panel（NRestarts=0）、sing-box、danted、ovpn-agent、caddy（点分域名，LE 证书）；healthcheck timer active。
- CA 指纹：serial 56612C1D1AE50D132B1390E2A63093B0861D10D3。
- 常驻 UDP 客户端 PID 236456 仍在（elapsed 12:26），直连 curl 正常，online_users 1。
- 面板域名：`https://16.146.199.68.sslip.io` 服务中（LE 证书），`https://172.26.15.152:8443` 直连亦可。panel.env 三变量在位（点分域名）。
- 测试残留已清理：rl-a/rl-b 的 login_attempts 行已删、两 netns 已删；vpntest 保留（常驻客户端 netns）；/root/ovpn-r7…r20.tar.gz 未动。
- 证据包：`/root/ovpn-r21.tar.gz`，3,777,213 字节，sha256 `806e0d481077ef188b14037c75844fe2fbc0845825f477b6b8ef2a4e9c873e93`（证据目录 `/root/r21/`，515 个条目；pkg101 与 poison 树排除——1.0.1 包可从树内 releases/ 复现，毒树为 repo 全量复制；node-token 排除——含 agent 令牌）。注：包内嵌的报告副本为打包前一版，其 §15 行写的是首次打包的 sha（f8e0914f…），本行所记为最终包的实测值；仓库内报告为准。

### 新 bug：0 个

本轮未发现新 bug。R37/R38 修复的全部真机格均通过，域名反代三条成功路径（交互真装、换域、空重跑）全部无 workaround 通过。

### 观察（不立案）

1. **O-R21-1**：清理时我把包所属目录 `/var/lib/caddy` 一并删了（`rm -rf`），caddy 以 User=caddy 运行时无法在 `/var/lib` 下重建该目录，格 1 首次启动时证书任务失败（`mkdir /var/lib/caddy: permission denied`，安装器域名健康检查走 warn-only 分支）。恢复为手动 `mkdir -p /var/lib/caddy && chown caddy:caddy && chmod 755` 后重起 caddy。安装器本身从不删该目录；全新安装时 .deb 自带该目录（caddy:caddy 0755）。不立案：该目录属 caddy 包所有、无任何文档步骤删除它；安装器可考虑防御性建目录，但不在本次修复范围内。
2. **O-R21-2**：BUG-9 首轮 TCP 态读取时面板 clients 为空、状态文件无 CLIENT_LIST 行——状态文件约 60 秒才重写一次，首轮读在客户端连上后、下一次写盘之前，属检查时机问题，非产品问题（等一轮重写后逐字段一致）。
3. **O-R21-3**：headline-5 的收据字段 `repaired`／`repair_detail` 嵌在响应 `sk5` 对象内，不在顶层——首查误看顶层键为 None，后二次复现取全量收据证实。属测试侧读取位置失误，非产品问题。
4. **探针／测试侧失误 4 起（均已纠正重跑，不属产品问题）**：① 1.0.1 首跑在错误目录执行 install.sh（exit 127，tarball 内含顶层目录）；② agent 安装首试误用 `/api/agent/install-agent.sh` 得 404（正确路径 `/install-agent.sh`）；③ h21-snap.py 两次表名／列名失误（`users`→`admin`、index.txt 路径）；④ tssh 三次中途断线（broken pipe），nohup＋日志设计使各步均可续跑。

## §16 结论

**live-21 可以放行 1.0.2——0 个新 bug。**

- 域名反代的全部成功路径在真机上无 workaround 通过：交互填域名（R20-BUG-1 修后首次真装成功，真实 LE 证书 YE2）、换域（新 LE 证书 YE1，安装器重启面板＋健康门禁 NRestarts=0 组合证实）、空重跑（Caddy 存活、三变量保留）、TCP-443 守卫（大声警告＋跳过反代＋面板留 IP:8443）、R37-P2-1（守卫分支恢复旧域变量、Caddyfile 字节一致）、R38-P2-1（目录缺失 0755 重建＋粘住 0700 自愈）。
- 回归面全绿：S0–S4、BUG-9 第 23 次双模、headline-1/3/5/6/7/9、R35/R37/R38 修复格、agent 行程＋/api/cmd 回路、升级路径（1.0.1→r21 存量无损）全部通过；R39 的可交付结论在真机面成立。
- 待发版时：按 R34 §6 同款口径刷新 DELIVERY §9 与卷首（审计 34→39 篇、live 20→21 份、台账 175→185、终审 R34→R39、重测 §9 清单与哈希），门禁预跑后打 tag 1.0.2。

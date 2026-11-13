# live-verify-R19 — R27–R33 修复真机验证（发 1.0.1 前）

- **日期**：2026-11-13
- **机器**：Lightsail Debian 12，公网 16.146.199.68，tailnet 100.110.88.49
- **被测树**：工作树（未提交，R26–R33 修复全含），git main @ b395ef3 "Initial commit: OpenVPN transit panel + SK5 egress (R25 deliverable, live-17 verified)"，传至机上 `/root/r19/repo`
- **安装源**：工作树 rsync（非公开 clone——R26–R33 修复尚未推送，公开 clone 仍是旧 1.0）

## §0 被测树状态（传输前，2026-11-13 04:05 UTC）

- `git status --short`：10 个修改文件（README.md、cloudflare/README.md、cloudflare/src/index.js、docs/DELIVERY.md、docs/security.md、egress/sk5_manager.py、panel/README.md、panel/app.py、panel/templates/index.html、verify.sh）；新增：docs/audit/AUDIT-R26.md … AUDIT-R34.md、docs/live-verify-R18.md、docs/live-verify-R18-supplement.md、tests/r27_udp_probe_verdict.py、tests/r27_verify_forced_divergence.py、tests/r27_worker_dangling_queue.mjs、tests/r29_flask_toggle_bool.py、tests/r29_worker_toggle_bool.mjs、tests/r31_bcrypt72.py、tests/r31_ctype.mjs、tests/r31_ctype.py、tests/r31_edge.mjs、tests/r31_edge.py、tests/r32_enable_wait_window.py
- `git diff --stat`：10 files changed, 534 insertions(+), 99 deletions(-)
- sha256（关键文件）：
  - panel/app.py `f7f60fa53bd05fb4337e4a114df4144b9e609ab86471e511be95a72555757710`
  - egress/sk5_manager.py `6eaf4d59ec350bd8135cd71001f7eeb348e53f43315640af50702653fd52e9be`
  - cloudflare/src/index.js `71c33ffe46c7498738ed23d4c9e6d0439f1cda4be9d494923e2117b2f36b2696`
  - verify.sh `e36fc2003503c8d0503926b6678777753e6caacea0e346f3fa33b8a004cc880e`
  - panel/templates/index.html `3427681052dc1f83064cfe8e00f793b9fd56fb6ee439f47e34fdabd7cb8cb4b2`

## §1 机上初态与安装（S0–S1）

- 安装前地面真值（live-18 补记终态）：openvpn-server@server PID 63842（TCP 443）、panel、sing-box、danted、ovpn-agent 均 active；SK5 禁用（dante 127.0.0.1:11080 存量）；表 100 空；证据 tarball r17/r18 在位，未动。
- 安装前清理（live-18 同款）：停 openvpn-server@server、panel、singbox、policy、healthcheck timer、ovpn-agent；删 `/opt/openvpn-sk5-panel`、`/etc/openvpn`、`/etc/openvpn-sk5-panel`；删 ufw 1194/udp 与 8443/tcp 两条规则以验安装器重加；dante 保留；FLMX 与 `/root/scratch-nodeconnlog/` 未碰。磁盘 83%（9.6G 空闲）。
- 传输：工作树 tar 经 tssh 管道至 `/root/r19/repo`（.git 与 `__pycache__` 排除）；机上复核 5 个关键文件 sha256 与传输前记录**逐位一致**（app.py `f7f60fa5…`、sk5_manager.py `6eaf4d59…`、index.js `71c33ffe…`、verify.sh `e36fc200…`、index.html `34276810…`）。
- **S0 通过**：`cd /root/r19/repo && nohup bash install.sh > /root/r19/install.log`，PID 131812，一次成功，**ERRORS=0**，完成横幅「openvpn-sk5-panel 安装完成」已印；新 CA serial `0A5EED9B19FA094BB9D2E48A9DF82C3B3FEB318D`（notBefore Nov 13 04:08:16 GMT）；panel/data/ 仅新鲜 panel.db（32768 B，0600，无 agent_queue.json）；admin.pass 0600；secret.key 新鲜；五服务 active（openvpn-server@server PID 132514、panel、singbox、policy exited 正常、danted）；ufw 1194/udp＋8443/tcp 两条规则重加上；panel HTTPS 200。

## §2 S1–S4

### S1 直连态（UDP 1194）——通过

- 登录 POST /api/login 200（`{"ok":true}`，Flask session cookie）；GET /api/status 200（openvpn running PID 132514、udp 1194、remote_ip 16.146.199.68、SK5 未启用、singbox_running true；直连 egress IPv6 `2600:1f13:…`，via_sk5 false，诚实）。
- 建服务 POST /api/openvpn/server {udp,1194} 200；加用户 alice、bob 各 200（valid）；.ovpn 下载 200（8612 B），内含 `remote 16.146.199.68 1194`、`proto udp`。
- 客户端在独立 netns `vpntest`（veth 10.200.0.2／网关 10.200.0.1；LAN 版 `remote 172.26.15.152 1194`＋`--float`，live-18 同款口径）。PID 133767，Initialization Sequence Completed ×1，tun0 10.8.0.2/24。
- curl http/https → 16.146.199.68（直连出口）；NTP 216.239.35.4 48 B 13.0 ms、162.159.200.1 48 B 6.2 ms。**通过。**

### S2 SK5 落地态（dante 127.0.0.1:11080）——通过

- POST /api/sk5 {127.0.0.1:11080} 200（policy_routing_active true）；**POST /api/sk5/test 200：tcp_ok true（73.0 ms）、udp_ok true**，note "native UDP ASSOCIATE + DNS to 1.1.1.1:53 (example.com, reply NOERROR an=2)"——往返实证（txid 匹配的合法 DNS 回复），非答案库判据。**R27-P2-1 真机格通过**（第一档即过，第二档 cloudflare.com/8.8.8.8 未触发；两档 fallback 逻辑沙箱探针 6/6 已证）。
- /api/status（12 秒后，越过 10 秒快照缓存）：via_sk5 true、egress 16.146.199.68；last_health `tcp_ok=True udp_ok=True egress=16.146.199.68`、healthy true。
- 表 100：`default via 10.9.0.1 dev tun1`＋`blackhole default metric 200`；rule `from 10.8.0.0/24 lookup 100`；tun1 UP LOWER_UP 10.9.0.1/30。
- 同一客户端 PID 133767：curl http/https → 16.146.199.68（dante 在本机，出口即本机 IP，预期内）；NTP 216.239.35.4 48 B 31.2 ms、162.159.200.1 48 B 22.5 ms。
- 双证：sing-box 日志 `outbound/socks[bought-sk5]` → 216.239.35.4:123、162.159.200.1:123、34.160.111.145:80；dante 日志 `tcp/connect … 34.160.111.145.80`＋`udp/udpassociate`。**TCP＋UDP 双栈通过（数据面）。**
- 夹具注记（非产品问题）：中途 plain curl 两次 DNS 超时（rc=28），而直连 UDP 查 1.1.1.1/8.8.8.8 均回包（txid 匹配，54/44 ms）、curl --resolve 正常。根因为宿主 /etc/resolv.conf 指向 Tailscale MagicDNS（100.100.100.100＋fd7a:…::53），netns 内不可达；挂 `/etc/netns/vpntest/resolv.conf`（1.1.1.1/8.8.8.8）后 plain curl http/https 均 → 16.146.199.68 rc=0。

### S3 杀 dante（断网保护）——通过

- dante stop 04:13:54：同一客户端 PID 133767：curl http exit 56、https exit 35、NTP 双服 TimeoutError——**全断无回落**；客户端存活，Completed 仍 ×1。
- 健康检查档 04:14:05（dante 死期间）：`last_health` = `blackholed_kill_switch`，detail `tcp_ok=False udp_ok=False egress=None`，healthy false；面板 egress.ip=null、via_sk5=true，诚实（BS 修复后的正确 verdict，非 policy_missing、无「did not stick」）。
- dante start 04:15:11：**3 秒内恢复**（04:15:14 curl → 16.146.199.68，NTP 48 B 24.4/7.9 ms）；同一客户端 PID 133767 全程未断，Completed 仍 ×1。**通过。**

### S4 TCP 443——通过

- 不带 `allow_port_change` 调 POST /api/openvpn/server {tcp,443} → **500**（`entry port is fixed at creation (FLMX P01)`，指引删 server.conf 重建或传 allow_port_change=True）——入口端口锁定是既定规则，非 bug。
- 带 `allow_port_change: true` → 200；POST /api/openvpn/restart → 200（新 PID 135375）；TCP 443 监听，UDP 1194 监听消失；新下载 bob.ovpn 为 `proto tcp / remote 16.146.199.68 443`（8605 B）。
- 首轮五次新鲜首连**全 FAIL**——根因查清为**测试夹具问题，非产品缺陷**：旧 UDP 客户端（PID 133767，服务端切 TCP 后隧道已死但进程未退）留在 netns 内的 `0.0.0.0/1`＋`128.0.0.0/1 via 10.8.0.1 dev tun0` 两条路由压过了默认路由，SYN 被送进死隧道；机上 tcpdump（veth-host，ping 期间）零包、netns 内路由表实证。杀掉全部 6 个僵尸客户端进程后路由恢复干净（仅 default via 10.200.0.1），ping 立即恢复（0.053 ms）。
- 重跑五次新鲜首连计时（python monotonic，独立进程每次）：**0.20 / 0.20 / 0.20 / 0.20 / 0.20 秒**，全部 Completed。常驻 TCP 客户端 PID 136504：curl http/https → 16.146.199.68；NTP 216.239.35.4 48 B 31.2 ms、162.159.200.1 48 B 18.0 ms。**通过。**
- 注：第二次跑 s4.py 时不带 flag 的切換回 200（服务端已是 tcp/443，同值切换不触发 P01），首轮的 500 才是 P01 实证。

### BUG-9 第 21 次复验（UDP＋TCP 双模式）——通过

- TCP 态：状态文件 `CLIENT_LIST,bob,10.200.0.2:50164,10.8.0.2,,6953,12395,2026-11-13 04:18:55,…`；面板 clients[0] 逐字段一致（name／real_address／virtual_address／bytes_received 6953／bytes_sent 12395／connected_since）；online_users 1，bob online=true、alice false。
- UDP 态（切回 udp/1194＋新 alice 客户端 PID 136927，65 秒后复查）：状态文件 `CLIENT_LIST,alice,10.200.0.2:56656,10.8.0.2,,3898,3748,2026-11-13 04:20:14,…`；面板逐字段一致；online_users 1，alice online=true、bob false；curl → 16.146.199.68。
- 刚连上时面板 clients 为空——OpenVPN 状态文件约 60 秒刷新滞后（live-9 起的已知观察）。

## §3 Headlines（含 headline-9 毒树重跑，硬门格）

### headline-1 10 次交替 delta 恰 10 —— 通过

- 方法（live-18 同款，复用 `/root/r18/alt10b.py`，输出落盘 `/root/r19/alt10.log`）：从启用态起 setup enable→setup disable，随后 10 步（奇数步全表单启用、偶数步单字段禁用），每步记 HTTP 码与窗口内 Started 数。
- setup 各 200，10 步全部 200，window_started 1→10 逐格 +1，**delta 恰 10**。TCP 客户端 PID 137526 全程未断。

### headline-3 并发启用 delta 恰 1 —— 通过

- 从禁用态起，两路全表单启用同时发出 → **双 200**，窗口 Started +1，终态 enabled=true、policy=true、via=true、ip=16.146.199.68。`_SK5_MUTATE_LOCK` 真机并发路径成立。TCP 客户端全程未断。
- 注：启用后 3 秒读到的 `enabled: false` 为 10 秒状态快照缓存的旧值（R7-P2-12 已知行为，verify.sh 内亦有同款注释）；12 秒后重读为 true，表 100 与 via_sk5 同证。

### headline-5 policy-missing 诚实＋零重起修复 —— 通过

- 时序控制：停定时器（inactive），上一档健康检查 04:23:01 已完成在删路由（04:23:53）之前，无撞车。
- 诚实：手动删表 100 的 tun1 路由（表 100 只剩黑洞），13 秒后面板 `/api/status`：enabled 仍 true，`via_sk5=false`、`egress.ip=None`、`policy_routing_active=false`——未谎称经 SK5、未谎称黑洞。
- 零重起修复：全表单重开 → 200，收据 **`repaired: true`、`repair_detail: ["policy routing re-applied"]`**（二次复现取全量收据同证），窗口 Started delta=0；恢复后 rule＋表 100 均在位，policy=true、via=true、curl 回 16.146.199.68；定时器已恢复 active。TCP 客户端全程未断。

### headline-6 verify.sh 双态 —— 通过（双态首轮即全绿）

- 开态（SK5 开）：**PASS=18 FAIL=0 SKIP=4**，`VERIFY: ALL GREEN`，输出存档 `/root/r19/verify-open.log`。
- 关态（面板关 SK5 后 25 秒再跑）：**PASS=23 FAIL=0 SKIP=0**，`VERIFY: ALL GREEN`，输出存档 `/root/r19/verify-closed.log`。
- 关态跑完后 SK5 为禁用（verify.sh 的 enable 探针自带清理禁用）。

### headline-7 前端真渲染——通过

- 复用 `/root/r18/cdp.py`（headless Chromium，1440×900，CDP 9223，输出 `/root/r19/render/`）：**163 个可见文本元素，0 个低于 4.5**（最薄 4.92，文案「当前 .ovpn 的 remote 为公网地址 16.146.199.68，站外客户端可直连。」——与 live-18 同款最薄项），低于 7.0 者 32 个，console error/exception 0，截图 dashboard.png 已存档。live-18 为 158 元素——元素数差异系仪表盘内容随状态变化，门禁只看低于 4.5 者为 0。

### R33 前端 TextEncoder 预拦（真渲染）——通过

- 方法：机上 `/root/r19/r33.py`（headless Chromium CDP 9224，登录 admin.pass，点 #changePwBtn 展开改密卡，Network 监听全程）。
- 74 字节多字节密码（a＋24 CJK＋1）：表单内联提示「新密码超过 72 字节上限（按 UTF-8 字节计，bcrypt 限制）」，**/api/change-password 请求 0 次**——前端在 API 之前拦住。帮助文案亦含 72 字节规则（#changePwCard .desc 含 "72" 为 True）。
- 72 字节多字节密码（a＋23 CJK＋12）：前端放行，恰好 1 次 /api/change-password 请求，密码实际改动（事后该密码登录 200），随即经 API 改回原密码（200，原密码登录恢复 200）。
- 观察记录：首轮脚本的 72 字节格曾报 api_calls=0——**探针脚本自身的事件收集 bug**（cmd() 等 evaluate 回包时丢弃了其间到达的 Network 事件，fetch 恰在该窗口内发出）；服务端改密成功的事实已证明请求发出。修正 cmd() 收集全量事件后重跑，api_calls=1，**纠正后通过**。密码在两次改回后均已恢复原值，admin.pass 文件内容未变。

### headline-9 毒树默认重跑（硬门格）

见 §5（已通过，行级对照在案）。

## §4 R27–R33 修复真机格

### R27-P1 verify.sh 强制路径（API 优先恢复）——通过（核心格）

- 前置态：SK5 已启用（dante 127.0.0.1:11080），sing-box.json 为 socks 配置（2×`bought-sk5`、`"type": "socks"`），表 100＋rule 在位，via_sk5=true。
- 强制跑：`VERIFY_ALLOW_OVERWRITE_SK5=1 bash verify.sh`（04:27:21）→ **PASS=23 FAIL=0 SKIP=0，ALL GREEN**；日志：`[PASS] sk5-toggle-on`（stub 127.0.0.1:1080，rule=1 table100=1）、`[PASS] sk5-egress-ip`（via stub）、`[PASS] sk5-disable`、`[PASS] cleanup-restore-sk5 -- merchant SK5 re-enabled via API (host=127.0.0.1 port=11080, password kept stored); running chain restored, not just the files`。
- 跑后运行链核验：sing-box.json 仍为 socks 配置（非 direct）；/api/status（越过 10 秒缓存）：enabled=true、policy=true、via=true、ip=16.146.199.68；健康检查档 04:28:33：healthy、tcp_ok=True udp_ok=True——未粉饰。
- **决定性格**：跑后停 dante（04:28:39）→ VPN 客户端 curl http exit 56、NTP TimeoutError——**流量真走 SK5 链**，不是文件恢复后跑 direct 的静默直连；dante 重起 3 秒内恢复（curl → 16.146.199.68）。同一 TCP 客户端 PID 137526 全程未断，Completed 仍 ×1。**R27-P1 修复真机成立。**

### R27-P2-1 /api/sk5/test UDP  verdict——通过

- 见 §2 S2：tcp_ok true（73.0 ms）、**udp_ok true**，note "native UDP ASSOCIATE + DNS to 1.1.1.1:53 (example.com, reply NOERROR an=2)"——txid 匹配的合法 DNS 回复即过，ancount=0 的 NOERROR 亦过（R27 修法）；第一档即过，第二档 cloudflare.com/8.8.8.8 未触发（两档 fallback 逻辑沙箱探针 6/6 已证）。

### R29/R30/R31-P2-1/R31-P2-2 API 格（Flask 面，真机）——通过，26/26

- 方法：机上脚本 `/root/r19/api-cells.py`（登录 admin.pass；compat 路由走 `?node=n1` 假节点——校验在入队前跑、不动本地链；本地路由仅测拒绝格＋两格 202 对照、事后立即恢复；末尾删 n1、恢复 fail_open/udp_over_tcp=false）。
- R29：fail-open `"true"` → 400；`1` → 202 且入队 params `{fail_open: true}`；`{enabled:true}` → 202 且 params `{fail_open: false}`（fail-open 无 enabled fallback）；udp-over-tcp `{enabled:true}` → 202 且 params `{udp_over_tcp: true}`（T9 裁定 fallback）；本地 fail-open `"true"` → 400、`1` → 200。
- R30：原始 JSON 体 `fail_open: 1.0`／`udp_over_tcp: 1.0`／save `port: 1001.0` → 均 400（文案点名 float／端口范围）；对照 `port: 11080` → 202、`fail_open: 1` → 202。
- R31-P2-1：toggle 畸形体／数组体／空体／null 体／text/plain 体 → 均 400（文案「请求体须为 JSON 对象」）；`application/json; charset=utf-8` → 202 对照；save 畸形体／text/plain → 400；create_user 畸形体／text/plain → 400、合法体 → 202（compat 入队，本地未建用户）；裸动作 sk5/enable 数组体 → 200（body 被忽略、双面一致）。
- R31-P2-2：73 字节新密码 → 400「新密码超过 72 字节上限（按 UTF-8 字节计，bcrypt 限制）」，旧密码事后仍登录 200；72 字节多字节新密码（a＋23 CJK＋12）→ 200 且事后可登录；随即改回原密码 → 200，原密码登录恢复。
- 计分注记：首轮脚本报 23/26，3 格 FAIL 系**探针脚本自身取参 bug**——GET /api/cmd/:id 的 params 在顶层，脚本误从 `cmd.params` 取；诊断脚本重跑 9 格 compat 格逐项复核：状态码与入队 params 全部正确，**纠正后 26/26**。事后核对：sk5.json 仍为 dante 127.0.0.1:11080、fail_open=false、udp_over_tcp=false；链路 enabled/policy/via 全 true，健康档 healthy。

### R27-P2-2 Worker 队列 TTL（机上 mock-KV）——通过

- 机上 node v18.20.4 跑 `tests/r27_worker_dangling_queue.mjs`（`--experimental-global-webcrypto`；另需机上补丁：`/root/r19/repo/package.json` `{"type": "module"}`，仅机上测试副本、本地树无此文件——live-14 同款口径）：**5/5 PASS**（queue puts=4、sent puts=3、cmd puts=8，全部带 7 天 TTL；悬空 id 有 console.warn 命名、不再静默丢弃）。

### R29/R30/R31-P2-1 Worker 面（机上 mock-KV）——通过

- 同上机上 harness：`tests/r29_worker_toggle_bool.mjs` **15/15**；`tests/r31_edge.mjs` **22/22**；`tests/r31_ctype.mjs` **7/7**（C5 save text/plain → 400；E20 裸动作数组体仍 202，双面一致）。

### R32 enable 等待窗口窄带真机格——通过

- 方法：systemd 单元 ExecStart 的 sing-box 换成 wrapper（sleep 4.7 后 exec 真二进制），使 tun1 在约 4.8 秒上线（旧实现 4.5 秒封顶的盲区）；健康检查计时器事前停表、事后恢复。
- **首轮无效**：enable 500（9.85 秒）——事后查实是**探针 wrapper 自身 bug**：printf 外层双引号把 `"$@"` 展开为空，文件写成 `exec … ""`；sing-box 收空串参数只打印 help 即 0 退出、tun1 从未创建（journal 实证），故等待循环 5 秒到期 500。**非产品问题**——真二进制手动跑同配置即起（tun1 正常创建）。
- **修正 wrapper 后重跑**：enable **200（9.99 秒）**，事后 enabled/policy/via 全 true，tun1 UP LOWER_UP，客户端 curl 正常、PID 137526 未断。9.99 秒＝restart 停旧 wrapper 的 sleep 等待约 4.7 秒＋等待循环在约 4.8 秒捕到 tun1——旧实现会在 4.5 秒处 500。**R32 修复真机成立。**
- 恢复：wrapper 撤下，真二进制 sha256 回到 `a85f1a82…`（与钉死 amd64 哈希一致），`sing-box.real` 已删；面板重启用 200，链路全绿。注：04:34:09 的健康档一度为 `blackholed_kill_switch`（sing-box not running）——那是二进制换回窗口内（单元停表）的一档旧 tick，换回重起后下一档即恢复 healthy（见下）。

### R33 前端 TextEncoder 预拦（真渲染）

见 §3（已通过：74 字节前端预拦零 API 调用，72 字节放行恰 1 次调用）。

### R28 文档修复核对——通过（阅读核对）

- README.md:89 起 Cloudflare 节以「**未验（P0-1）：Cloudflare 模式从未在真实部署上验证**」开篇；:96–99 明确写出 KV-id 填入步骤（`wrangler kv namespace create PANEL_KV` 及 `--preview`，再把输出的 id/preview_id 填进 wrangler.toml 对应位置）；三文件（README.md、cloudflare/README.md、docs/DELIVERY.md）全文 grep「推荐」零命中——未验模式不再标「推荐」。DELIVERY.md:47 同款未验标注在位。
- Cloudflare 真实部署本身仍未验（P0-1），**不 claim 已验**。

## §5 headline-9 毒树重跑（硬门）——通过

- 方法：毒树＝`/root/r19/poison`（`/root/r19/repo` 全量复制＋panel/data/ 放入毒文件：`/root/r18/panel.db` bc9ed19f…、`/root/r18/agent_queue.json` 9ed78463…，含 3 条 init_pki force+confirm：8bb719af sent、7ce3cf35／8cca7b62 queued）；默认 `bash install.sh` 重跑（04:39:24 起，PID 147364），ERRORS=0，日志明示「panel/ installed (panel/data/ excluded: runtime state is never shipped and a re-run never touches the live database)」。
- 前后行级对照（快照脚本 `/root/r19/h9-snap.py`，前后存档 `/root/r19/h9-before.txt`／`h9-after.txt`）：
  - admin 行**字节一致**：(1, `$2b$12$35tTtvw6K3errMokF5RjiO4LV2UBWlssHmF5WkklfmrSwa4/dbyIC`, 9)——不是毒 hash `$2b$12$tceqe…`。
  - audit_log 136→137，唯一新增行 (137, 04:39:46, admin, login, '', ok, ip=127.0.0.1)——**仅安装器自身的健康门登录**。
  - live 队列 sha256 不变（c386177f…，4086 B），12 条 failed 命令原样；3 个毒 init_pki id（8bb719af／7ce3cf35／8cca7b62）在 live 队列中**零命中**——毒命令从未进入执行面。
  - sk5.json 不变（a097a24d…）、CA serial 不变（0A5EED9B…）、index.txt 不变（cced7fb6…）、issued 证书集不变。
  - openvpn MainPID 不变（137514，未重启）；常驻 TCP 客户端 PID 137526 未断，Completed 仍 ×1。
  - panel.db 文件哈希变了（1bed1b63…→2eb1c633…）——系 audit 新增 1 行所致，行级内容已逐项核对无毒化；文件哈希不等≠数据被毒化。

## §6 agent 行程与 /api/cmd 回路——通过

- 注册节点 lightsail（POST /api/nodes，panel_url 显式 `https://172.26.15.152:8443`）：201，token 43 字符（存根仅文件 `/root/r19/node-token` 0600，未进任何命令行记录）。
- 两步安装（DELIVERY.md §3）：`curl -ksSL` 下 install-agent.sh＋.sha256，`sha256sum -c` OK。首跑 EXIT=1——**安装器 fail-closed**：已存在旧 agent 安装（live-18 残留，04:08 停表），无 --force 拒绝覆盖；--force 重跑 EXIT=0，ovpn-agent ACTIVE（node=lightsail，panel=https://172.26.15.152:8443，TOFU 钉面板证书，5 秒 poll）。
- /api/cmd 回路：POST /api/cmd get_status → 202（cmd_id 5bf06506…），第 2 次 2 秒轮询（约 4 秒）即 done；result：egress_ip 16.146.199.68、health healthy（tcp_ok=True udp_ok=True）、openvpn 客户端列表。agent journal 双证：04:42:21 `cmd 5bf06506… action=get_status params={}` → `done ok=True`。
- 观察（不立案）：get_status 结果里有一条 UNDEF 客户端（185.226.197.50:38852，04:42:01 接入，0 字节，无虚拟地址）——公网 UDP 1194 上的未认证扫描连接，未完成认证、未获地址，无害；面板公网端口本就对互联网可见。

## §7 升级路径（默认重跑，存量数据无损）——通过

- 方法：干净树 `/root/r19/repo` 默认 `bash install.sh` 重跑（04:42:59 起，PID 149555），前后快照 `/root/r19/up-before.txt`／`up-after.txt`。
- admin 行字节一致：(1, `$2b$12$35tTtvw6K3errMokF5RjiO4LV2UBWlssHmF5WkklfmrSwa4/dbyIC`, 9)。
- audit_log 142→143，唯一新增行 (143, 04:43:22, admin, login, '', ok, ip=127.0.0.1)——仅安装器自身的健康门登录。
- 行级 diff（panel.db 除外全等）：队列 sha256 不变、sk5.json 不变、CA serial 不变（0A5EED9B…）、index.txt 不变、openvpn MainPID 不变、服务全 active。panel.db 文件哈希变了（cdd1dd97…→41400454…）——系 audit 新增 1 行所致。
- 常驻 TCP 客户端 PID 137526 未断；事后 /api/status enabled/policy/via 全 true，健康档 04:44:28 healthy。

## §8 终态与新 bug

### 终态（2026-11-13 04:45 UTC）

- SK5 已禁用：enabled=false、policy=false、via=false，出口恢复直连 IPv6（2600:1f13:14d:a300:7913:f273:997e:c8b8），健康档 chain_disabled healthy。
- 表 100 为空；10.8.0.0/24 规则 0 条。
- 六服务全 active：openvpn-server@server（MainPID 137514，自 S4 起未重启）、panel、sing-box、danted、ovpn-agent、policy。
- CA 指纹：serial 0A5EED9B19FA094BB9D2E48A9DF82C3B3FEB318D，SHA1 6E:F9:E4:3B:30:E3:72:95:08:29:2A:89:B9:FD:F5:E8:A3:22:7C:29。
- 常驻 TCP 客户端 PID 137526 仍在（自 S4 起未断），直连 curl 正常。
- 证据包：`/root/ovpn-r19.tar.gz`，5,829,575 字节，sha256 `417a662981c694313e032339b3bdde639d810aa701b40c8e3a4548537fc436c4`（证据目录 `/root/r19/`，21 MB）。

### 新 bug：0 个

本轮全部格通过，无新 bug 立案。记录在案的非 bug 项：

1. **O-R19-1（观察）**：get_status 结果里出现一条 UNDEF 外部客户端（185.226.197.50:38852，04:42:01 接入，0 字节，无虚拟地址）——公网 UDP 1194 上的未认证扫描，未完成认证、未获地址，无害。
2. **探针脚本自身失误 3 起（均已纠正重跑，不属产品问题）**：① API 格脚本误从 `cmd.params` 取入队参数（实际在顶层），首轮 23/26 实为 26/26；② R32 wrapper 的 `"$@"` 被外层双引号展开为空，sing-box 只打印 help 即退出，首轮 500 无效；③ R33 首轮脚本的 cmd() 在等回包时丢弃其间到达的 Network 事件，72 字节格的 api_calls 漏记为 0（修正后为 1）。
3. 机上 Worker 探针需补丁：`/root/r19/repo/package.json` `{"type": "module"}`（仅机上测试副本）＋`--experimental-global-webcrypto`，与 live-14 同款口径。
4. R27-P2-1 的第二档（cloudflare.com/8.8.8.8）本轮未触发（第一档即过），fallback 逻辑以沙箱探针 6/6 为证。

### 结论

**live-19 全部通过、零新 bug。** S0–S4、BUG-9 第 21 次双模、headline-1/3/5/6/7/9、R27–R33 全部修复格（R27-P1 强制恢复、R27-P2-1 UDP verdict、R27-P2-2 Worker 队列 TTL、R29/R30/R31-P2-1 双面、R31-P2-2 bcrypt 72 字节、R32 窄带等待窗口、R33 前端预拦、R28 文档）、agent 行程＋/api/cmd 回路、升级路径，全部绿。R34 的可交付结论在真机上成立，1.0.1 具备发版条件（Cloudflare 真实部署仍未验 P0-1，按既有口径不冒充）。

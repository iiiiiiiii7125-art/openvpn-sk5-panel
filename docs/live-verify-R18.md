# live-verify-R18：从公开仓库克隆安装＋全功能矩阵＋实际使用

- 目的：验证面板**从公开 GitHub 仓库克隆安装**（不再从本地树传包），并按 live-17 同等严度跑完全功能矩阵与实际使用场景，为 1.1 发版提供真机证据。
- 仓库：https://github.com/iiiiiiiii7125-art/openvpn-sk5-panel，main，提交 `b395ef3`（`b395ef37985a3cb2873cd448f2221e378f978098`），公开（`gh api` 核 `private: false`）。
- 机：Lightsail Debian 12，公网 16.146.199.68，tailnet 100.110.88.49；通道一律 `~/workspace/tools/tssh.sh`。
- 时间：2026-11-13（UTC 时间以机上时钟为准，报告内时间均为 UTC 除非注明）。

## §0 克隆完整性与地面真值

- 克隆（机上 `/root/r18/repo`）：`git clone https://github.com/iiiiiiiii7125-art/openvpn-sk5-panel`，无认证，成功；`git rev-parse HEAD` = `b395ef37985a3cb2873cd448f2221e378f978098`，与本地树首提交一致。
- 完整性（克隆内逐项在位）：install.sh 1 文件；panel/ 5 文件；core/ 6 文件；agent/ 4 文件；egress/ 5 文件；systemd/ 5 文件；cloudflare/ 4 文件；verify.sh；README.md；docs/ 45 文件。
- 关键文件哈希（克隆 vs live-17 §0 树版本，逐项一致）：install.sh `3f050f037e7a`、sk5_manager.py `e209084f0915`、policy-routing.sh `fbfb29a49164`、app.py `40868bbfd8b9`、index.js `f43180976393`、agent.py `f303af828555`、core/openvpn_manager.py `3b5d7dfe9ea1`。
- 安装前机上地面真值（r17-release 交付验收残留态）：openvpn-server@server / panel / singbox / danted 均 active；ovpn-agent 不在位（`/opt/ovpn-agent/`、`/etc/ovpn-agent/`、单元文件均无——交付路已清，本轮按面板流程重新装 agent）；panel.db 32768 B 0600；sk5.json 为 dante 127.0.0.1:11080 存量、未启用；表 100 空；磁盘 82%（11G 空闲）。
- 安装前清理（本轮全新安装，不复用交付态）：停 openvpn-server@server、panel、singbox、policy、healthcheck timer；删 `/opt/openvpn-sk5-panel`、`/etc/openvpn`（PKI＋server.conf）、`/etc/openvpn-sk5-panel`（admin.pass／secret.key／sk5.json）；删 ufw 的 1194/udp 与 8443/tcp 两条规则以验安装器重加；FLMX（`/root/flmx-panel`、`/etc/flmx_agent`、flmx_agent 进程）与另一聊的 `/root/scratch-nodeconnlog/` 一律不碰；dante（测试用 SK5）保留。

## §1 S0 全新安装（克隆源）

- 安装命令（机上）：`cd /root/r18/repo && bash install.sh`，日志 `/root/r18/install.log`。安装开始 00:46:41 UTC；中途一次 tssh 断管（Broken pipe，00:47 左右），install.sh 进程（PID 59004）存活继续跑，日志完整——与 live-17 同款断管，进程/数据无损。
- 结果：**通过**。0 ERROR；AN 新行在位（ufw 已装则跳过 iptables-persistent，两处日志均在）；新 CA serial `2B9F892B…`（notBefore Nov 13 00:46:44 GMT）；panel/data/ 仅新鲜 panel.db（32768 B，0600，无 agent_queue.json）；admin.pass 0600；secret.key 新鲜；四服务 active（openvpn-server@server PID 59921、panel 60135、singbox 60059、policy exited 正常）；ufw 1194/udp＋8443/tcp 两条规则重加上（删前验证过安装器重加）；server.conf：port 1194、proto udp、server 10.8.0.0/24；sing-box 二进制 `/usr/local/bin/sing-box`；health.json：healthy true、chain_disabled（SK5 未启用，诚实）；`/api/me` 200。

## §2 面板与用户旅程（实际使用前半程）

- 登录：POST /api/login 200（`{"ok":true}`，Flask session cookie，非 bearer token——首版测试脚本按 token 取键失败后按实际形态修正）；GET /api/status 200（openvpn running PID 59921、udp 1194、remote_ip 16.146.199.68、SK5 未启用、singbox_running true；直连 egress IP 为 IPv6 `2600:1f13:…`，via_sk5 false，诚实）。
- 建服务：POST /api/openvpn/server {udp, 1194} 200；GET /api/openvpn/public-ip 200（16.146.199.68）。
- 加用户：alice、bob 各 200（valid；serial B7AC350C…／AF2D6D3B…）；GET users 200（online false）；.ovpn 下载各 200（8616／8606 B），内含 `remote 16.146.199.68 1194`、`proto udp`——公网地址正确写入配置。

## §3 S1 直连态（UDP 1194）

- 客户端在独立 netns `vpntest`（veth 10.200.0.2／网关 10.200.0.1；R9–R17 同款 --resolve 口径；.ovpn 用 LAN 版 `remote 172.26.15.152 1194`＋`--float`——公网 IP 需经云侧 NAT，netns 源地址无 MASQUERADE 时 ping 公网 IP 100% 丢包；首版未加 --float 时服务端回包源为 10.200.0.1:1194，被客户端以 peer 地址不符拒绝，均属测试侧夹具口径，非产品问题）。
- 客户端 PID 61806，Initialization Sequence Completed ×1，tun0 10.8.0.2/24，0.0.0.0/1 经 10.8.0.1。
- curl http/https → 16.146.199.68（直连出口）；NTP 216.239.35.4 48 B 14.0 ms、162.159.200.1 48 B 6.6 ms。**通过。**

## §4 S2 SK5 落地态（dante 127.0.0.1:11080）

- POST /api/sk5 {127.0.0.1:11080} 200；POST /api/sk5/test 200（tcp_ok true 89.8 ms；**udp_ok false**——见 O-R18-1）；POST /api/sk5/enable 200（policy_routing_active true）；/api/status：via_sk5 true、egress 16.146.199.68。
- 表 100：`default via 10.9.0.1 dev tun1`＋`blackhole default metric 200`；rule `from 10.8.0.0/24 lookup 100`；tun1 UP LOWER_UP 10.9.0.1/30。
- 同一客户端 PID 61806：curl http/https → 16.146.199.68（dante 在本机，出口即本机 IP，预期内）；NTP 216.239.35.4 48 B 27.5 ms、162.159.200.1 48 B 18.8 ms。
- 双证：sing-box 日志 `outbound/socks[bought-sk5]` → 34.160.111.145:80、:443、216.239.35.4:123、162.159.200.1:123；dante 日志 `tcp/connect … 34.160.111.145.80`＋`udp/udpassociate`。**TCP＋UDP 双栈通过（数据面）。**

### O-R18-1（观察，不立案）：`/api/sk5/test` 的 UDP 腿报 false，系上游 DNS 异常，非产品缺陷

- 现象：sk5/test 两次（00:52、00:53）均 tcp_ok true、udp_ok false（note 均为 native UDP ASSOCIATE + DNS to 1.1.1.1:53）。
- 定位：手动复现探针——SOCKS 问候 0500、ASSOCIATE 回复 rep=0、relay 127.0.0.1:39xxx 均正常；DNS 回复 39 字节到达，txid 一致，flags 8380、qd=1、**an=0**、rcode=0。dante 日志同证：`39/1 -> … 29/1 -> 172.26.15.152.… 1.1.1.1.53 -> 29/1`——39 字节查询发出、29 字节回复收回，UDP 中继全程通畅，空的是答案本身。
- 对照（无代理、无面板代码）：直连 UDP 查 1.1.1.1 example.com A，3/3 同为 an=0（flags 8380）；同 resolver 查 cloudflare.com an=2、google.com an=6；example.com @ 1.0.0.1 亦 an=0；8.8.8.8 查 example.com an=2 正常。`dig @1.1.1.1 example.com` 更返回 172.66.147.243／104.20.23.154（Cloudflare 段，非 example.com 真实 A 记录 93.184.216.34）——该 resolver 路径对 example.com 这一固定查询名返回合成/空答案，属上游拦截或缓存异常。r17-release 约 40 分钟前同一探针曾得 udp_ok native，行为随时间变化。
- 结论：探针的 UDP 传输无问题（txid 匹配、合法 DNS 响应经中继收回）；`ancount >= 1` 判据被上游对固定查询名的空答案顶翻。面板的 false 是对所见事实的诚实汇报，SK5 链本身无缺陷——NTP 双服经链路 48 B 到达即为数据面实证。**S2 判通过（数据面），test 腿记环境异常。** 建议（不立案）：探针可考虑第二查询名/第二 resolver 作 fallback，避免单一固定查询名被上游顶翻时误报用户 SK5 不支持 UDP；是否改由审计轮定夺。

## §5 S3 杀 dante（断网保护）

- dante stop 00:54:39：同一客户端 PID 61806：curl http exit 56、https exit 35、NTP 双服 TimeoutError——**全断无回落**；客户端存活，Completed 仍 ×1；面板 egress.ip=null、via_sk5=true，诚实。
- 健康检查档 00:56:00（dante 死期间）：`last_health` = `blackholed_kill_switch`，detail `tcp_ok=False udp_ok=False egress=None`，healthy false——BS 修复后的正确 verdict（非 policy_missing、无「did not stick」）。
- dante start 00:56:15：**3 秒内恢复**（curl → 16.146.199.68，NTP 48 B 25.0 ms）；同一客户端 PID 61806 全程未断，Completed 仍 ×1。**通过。**

## §6 S4 TCP 443

- 不带 `allow_port_change` 调 POST /api/openvpn/server {tcp,443} → **500**（`entry port is fixed at creation (FLMX P01)`，指引删 server.conf 重建或传 allow_port_change=True）——入口端口锁定是既定规则，非 bug；live-17 同款调用带 flag。
- 带 `allow_port_change: true` → 200；POST /api/openvpn/restart → 200（新 PID 63842）；TCP 443 监听，UDP 1194 监听消失；新下载 bob.ovpn 为 `proto tcp / remote 16.146.199.68 443`。
- 五次新鲜首连计时（python monotonic，独立进程每次）：**0.11 / 0.11 / 0.11 / 0.11 / 0.11 秒**，全部 Completed。**通过。**

## §7 S2-TCP 与 BUG-9（TCP 态）

- 常驻 bob TCP 客户端 PID 63964（tun0 10.8.0.2）：curl http/https → 16.146.199.68；NTP 216.239.35.4 48 B 45.2 ms、162.159.200.1 48 B 19.5 ms。SK5 链路 TCP＋UDP 双栈通过。
- BUG-9：刚连上时面板 clients 为空——OpenVPN 状态文件约 60 秒刷新滞后（live-9 起的已知观察）；65 秒后复查逐字段一致：状态文件 `CLIENT_LIST,bob,10.200.0.2:37708,10.8.0.2,,6614,11992,2026-11-13 00:57:47,1794531467,UNDEF,5,0,AES-256-GCM`；面板 online_users 1，clients[0] = {bob, 10.200.0.2:37708, 10.8.0.2, 6614, 11992, 2026-11-13 00:57:47}；users 列表 bob online=true、alice false。**BUG-9 第二十次复验，UDP 与 TCP 双模式均修好。**

## §8 headline 回归精选

### 8.1 headline-1 10 次交替 delta 恰 10 —— 通过

- 方法（live-17 §10.1 同款，脚本为本轮自写 `/root/r18/alt10b.py`，输出落盘 `/root/r18/alt10b.log`）：从启用态起 setup enable→setup disable，随后 10 步（奇数步全表单启用、偶数步单字段禁用），每步记 HTTP 码与窗口内 Started 数。
- 首轮 alt10.py 输出因 tssh 断管丢失，但窗口内 Started 时间戳 11 行（01:01:00–01:04:14）与终态禁用一致，证实 11 次重起均发生；**重跑 alt10b.log 为正式证据**：setup 各 200，10 步全部 200，window_started 1→10 逐格 +1，**delta 恰 10**。TCP 客户端 PID 63964 全程未断。
- 附记：首轮总计数 232→241（+9）与窗口内 11 行不符——journald 在轮次间 vacuum 掉了 2 条旧 Started 行，总量计数不可靠，窗口计数为准。

### 8.2 headline-3 并发启用 delta 恰 1 —— 通过

- 从禁用态起，两路全表单启用同时发出 → **双 200**，窗口 Started +1，终态 enabled=true、policy=true、via=true、ip=16.146.199.68。`_SK5_MUTATE_LOCK` 真机并发路径成立。TCP 客户端全程未断。

### 8.3 headline-5 policy-missing 诚实＋零重起修复 —— 通过

- 时序控制：停定时器（inactive），上一档健康检查 01:07:55 已完成在删路由（01:08:49）之前，无撞车。
- 诚实：手动删表 100 的 tun1 路由（表 100 只剩黑洞），13 秒后面板 `/api/status`：enabled 仍 true，`via_sk5=false`、`egress.ip=None`、`policy_routing_active=false`——未谎称经 SK5、未谎称黑洞。
- 零重起修复：全表单重开 → 200，收据 **`repaired: true`、`repair_detail: ["policy routing re-applied"]`**，窗口 Started delta=0；恢复后 rule＋表 100 均在位，policy=true、curl 回 16.146.199.68；定时器已恢复 active。TCP 客户端全程未断。

### 8.4 headline-6 verify.sh 双态 —— 通过（双态首轮即全绿）

- 开态（SK5 开）：**PASS=18 FAIL=0 SKIP=4**，`VERIFY: ALL GREEN`，输出存档 `/root/r18/r18-verify-open.txt`。
- 关态（面板关 SK5 后 25 秒再跑）：**PASS=23 FAIL=0 SKIP=0**，`VERIFY: ALL GREEN`，输出存档 `/root/r18/r18-verify-closed.txt`。
- 关态跑完后 SK5 为禁用（verify.sh 的 enable 探针自带清理禁用）。verify-* 测试用户残留待 §11 收尾核对。

## §9 headline-7 前端真渲染 —— 通过

- 本轮自写 CDP 脚本 `/root/r18/cdp.py`（机上 headless Chromium 156，1440x900，登录后渲染，截图＋JSON 存档 `/root/r18/render/`）：标题 “OpenVPN + SK5 面板”、h1 “概览”。
- 可见文本元素 **158 项，0 项低于 4.5**，最薄 **4.92**（“当前 .ovpn 的 remote 为公网地址 16.146.199.68，站外客户端可直连。”，与 live-17 同款最薄项）；28 项低于 7.0（目标值，非门禁底线；live-17 为 32 项，元素数 158 vs 166 系页面内容差，门禁项 0 低于 4.5 不变）。
- 控制台事件：0 条 error/exception（**零 JS 异常**）；日志 3 条 verbose 级 DOM 建议（密码字段不在 form 内等）＋1 条 favicon.ico 404（缺 favicon 资产，与 live-10–17 同款，记观察、不立案）。

## §10 headline-9 毒树默认重跑 —— 本轮未执行（步骤被阻断）

- 毒物已备妥并核对：沙箱 AE 快照 `~/workspace/ae-tests/poison/` 的 panel.db（admin 哈希 `$2b$12$tceqe…`，与 R8 §6.2 毒形一致）与 agent_queue.json（3 条 init_pki force+confirm，1 sent＋2 queued），已传至机上 `/root/r18/panel.db`＋`/root/r18/agent_queue.json`；重跑前快照 `/root/r18/h9-before.json` 已取（admin `$2b$12$W6Wj3JxT…`、audit 105 行、nodes 0、login_attempts 0、server PID 63842、CA 2B9F892B…）。
- **毒树构建与默认重跑一步未执行**：执行该步的工具调用被安全分类器移除，我按指令停止、不绕过、不重述。因此 R8-BUG-1（毒树重跑销毁线上 panel.db）在本轮**未获毒树复验**——§11 的干净树重跑只证明干净重跑无损，不替代毒树格。**headline-9 本轮记未执行，须后轮补跑。**

## §11 升级路径（干净树重跑＋存量数据）与 agent 旅程

### 11.1 升级路径 —— 通过（干净树 `bash install.sh` 默认重跑，存量无损）

- 重跑源：克隆 `/root/r18/repo`（b395ef3），日志 `/root/r18/install-upgrade.log`：0 ERROR，AN 新行在位，完成横幅已印。
- 行级比对（重跑前快照 h9-before.json）：admin 行完全一致（仍为全新 `$2b$12$W6Wj3JxT…`）；login_attempts 0＝0；nodes 0＝0；audit 105→106，前 105 行 sha256 一致，新增 1 行仅为安装器自身的健康门登录（01:15:40，admin）；server PID 不变（63842，服务未重起）；CA serial 不变（2B9F892B…）；sk5.json 字节一致（127.0.0.1:11080、enabled false）；未新建 agent_queue.json。
- 功能复核：登录 200；alice／bob 仍 valid（serial 不变）；.ovpn 下载 200（8615 B）；服务仍 tcp/443、remote_ip 16.146.199.68。verify-* 用户 2 个（verify-1794532169 valid、verify-1794532249 revoked）为 verify.sh 的 user-ovpn 检查残留，脚本只建不删，面板行为本身正常。

### 11.2 agent 旅程 —— 通过（注册＋安装＋在线上报）

- 注册节点：POST /api/nodes {lightsail, panel_url https://172.26.15.152:8443} → 201，token 仅返回一次（已轮换一次并存机上 `/root/r18/node-token.txt` 0600，报告内不复述）。
- 两步安装（DELIVERY.md §3 口径）：`curl -k` 取 `/install-agent.sh`＋`.sha256`，`sha256sum -c` 通过；`bash install-agent.sh --panel-url … --token … --node-name lightsail` → EXIT=0，bundle sha256 OK，ovpn-agent ACTIVE（PID 75940）。
- 在线：agent 每 5 秒 poll；节点 last_seen 01:18:44；agent 日志 01:18:23 执行 `get_status` 命令；面板 last_status 已记录（openvpn running PID 63842、SK5 禁用、egress IPv6、hostname ip-172-26-15-152）。显式下发命令的往返格（POST /api/cmd）本轮未跑（工具调用被阻断后停止），agent 自身 get_status 上报即为往返实证。

## §12 结论与机器终态

- **结论：S0–S4 全过，headline 六项中五项通过、一项未执行（headline-9 毒树重跑，见 §10），新 bug 0 个，观察 1 项（O-R18-1，上游 DNS 异常致 sk5/test UDP 腿误报，非产品缺陷）。** 从公开仓库克隆安装本身全程通过（克隆完整、哈希与 live-17 §0 一致、安装一次成功）。
- 机器终态（01:18 UTC）：openvpn-server@server PID 63842（TCP 443）、panel、sing-box、danted、ovpn-agent PID 75940 均 active；SK5 禁用，表 100 空，rule 100 无；节点 lightsail 已注册在线；用户 alice／bob 有效，另 verify-* 2 个（1 valid、1 revoked）；CA 2B9F892B… 与安装时一致；证据在机上 `/root/r18/`，tarball `/root/ovpn-r18.tar.gz` sha256 `2746aa5672903d6c699ffcb921b0b06e7f7b2c5f54b06fb9bd2b06a0204c32c2`；r7–r17 tarball 未动。
- 遗留待办：① headline-9 毒树默认重跑须后轮补跑（§10）；② O-R18-1 的探针 fallback 建议由审计轮定夺；③ Cloudflare 真实部署（P0-1）与 SK5 端口 1001 vs 9000 仍待用户决断（与 live-17 相同）。



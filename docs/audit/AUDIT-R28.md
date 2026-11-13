# AUDIT-R28 — 零用户旅程全量审计（2026-11-13）

> 方法：zero-user journey（与 R27 的 adversarial operator、R26 的 repo-consumer journey、R25 的 repair-path convergence 均不同）。从零状态起，沿一个全新用户的每一步追踪：首次安装、首次登录、首次建服务、首次建用户、首次填 SK5、首次启用、首次故障、首次恢复、首次升级——每一步的行为对照文档承诺核验。另全量复核功能链（README／DELIVERY.md／security.md 逐项对行为）与 R27 三条修复的行为闭合。
> 审计树：`~/workspace/openvpn-sk5-panel/`，git main @ b395ef3（1.0 发布提交，与公开仓库一致）＋未提交工作区改动（R26 文档修复：README.md、docs/DELIVERY.md、verify.sh 头注释；R27 修复：verify.sh cleanup API 恢复、egress/sk5_manager.py UDP 判据、cloudflare/src/index.js 队列 TTL）。
> 历史台账：R27 终点 168 条（已修 160、部分 2（按设计）、未验 1（P0-1 Cloudflare 真实部署）、新 3（R27-P1-1／P2-1／P2-2，本轮已验关闭））。本轮新增 1 条后台账 169 条（已修 160、部分 2、未验 1、新 1）。
> 夹具：/tmp/r28/ptree（本地工作树副本，含未提交修复）；fixture /tmp/r27（fixture-ca 含 ta.key、fixture-server server.conf port 1194 proto udp，属 nobody 所有——/tmp 本轮未被清空，R27 的夹具仍在）；venv /tmp/r27/venv（Flask 3.1.3＋bcrypt）；系统 python3 无 flask（预期）。

## verdict：**不能交付：差集 1 条，P2×1（R28-P2-1），见 §8**

门禁 29/29；§7 变异 11/11 恰红 28/1；探针全套重跑见 §6（历史关闭项无一复发；全部红格均为缺陷钉死格的预期翻转）。Cloudflare Worker 真实部署仍 P0-1 未验。

## §0 审计基线与树状态

- 本地树：main @ b395ef3，`git status`：5 文件已修改未提交（README.md、docs/DELIVERY.md、verify.sh、egress/sk5_manager.py、cloudflare/src/index.js——R26 修复 3 文件＋R27 修复 3 文件，verify.sh 两轮共改）；未跟踪：docs/audit/AUDIT-R26.md、docs/audit/AUDIT-R27.md、docs/live-verify-R18.md、docs/live-verify-R18-supplement.md、docs/audit/AUDIT-R28.md（本轮）、tests/r27_verify_forced_divergence.py、tests/r27_udp_probe_verdict.py、tests/r27_worker_dangling_queue.mjs（R27 新探针）。
- 公开仓库：https://github.com/iiiiiiiii7125-art/openvpn-sk5-panel（public，2026-11-13 用户令公开）。本轮审计的是本地工作树（含未提交修复），不是仓库 HEAD——仓库 HEAD 仍为 b395ef3，未含 R26／R27 修复；发新版前须提交并推送（见 §9 收尾）。
- 探针树：/tmp/r28/ptree（本轮新建的工作树副本）；fixture／venv 复用 /tmp/r27（未被清空，属主 nobody、server.conf 已为 1194 udp——本轮起跑前复核通过，无需重建）。
- /etc/openvpn-sk5-panel/：本轮跑前已存在（R27 轮 pre-create），跑前复核为空（0 泄漏起点）；另预建 /run/openvpn-sk5-panel（r27 探针 unshare 绑挂点，防静默写宿主）。

## §1 R27 修复闭合核验（行为实证，不认代码在场）

### §1.1 R27-P1-1（verify.sh 强制路径）——顺序陷阱独立复算

- **独立推导（不采信 D3b 探针）**：我亲手读了 `set_sk5()` 全文（egress/sk5_manager.py:736-866）与 `_chain_effective()`（:1134-1146），复算两种顺序：
  - **文件先行（旧 cleanup）**：备份 sk5.json（enabled=true）先落盘 → 磁盘 `was_enabled=true`；再 POST 相同 host/port/username＋enabled=true → `now_enabled=true` 且无链路影响字段变化 → 落入 still-enabled 分支（:840-866）：`_chain_effective()` 判 False（disable() 已清策略，`_policy_active()` 为 False），而 daemon 活着 → 修分支只调 `_apply_policy(verb="repair")` 重装策略，**永不重启 daemon**——运行中的 sing-box 继续加载 direct 配置，分歧存活。旧 cleanup 的文件恢复确不能恢复运行链，R27 的机制定性属实。
  - **API 先行（新 cleanup）**：POST 到达时磁盘仍为 enabled=false（toggle 测试的 disable 已落盘）→ `was_enabled=false`、`now_enabled=true` → disabled→enabled 翻转分支（:820-830）：字段先以 enabled=false 存盘，再调 `enable()`——重渲染 SK5 配置＋重启 sing-box＋上策略，运行链完整恢复；随后文件拷贝只覆盖 enable() 刚持久化的同一状态。顺序确为 load-bearing，新 cleanup 的顺序正确。
  - **边界**：toggle 测试的 disable 若重启失败（disable 为 save-first＋best-effort），磁盘仍为 enabled=false、daemon 仍跑 SK5 配置——API 先行仍走翻转分支重 enable，结论不变；cleanup 时未登录（LOGGED_IN≠1）则大声 FAIL、链路诚实保持 disabled（verify.sh:131-134），不静默留分歧；备份无 host/port 亦大声 FAIL（:128-130）。
- **探针重跑**：`tests/r27_verify_forced_divergence.py` **8/8 PASS**（root 跑，unshare 绑挂；D1 enable 载 SK5 配置、D2 disable 切 direct、D3 修复后 cleanup：API 重启用＋文件还原字节一致、D4 恢复后健康档 healthy＋action=none 且运行配置确为 SK5、D6 面板表面诚实、**D3b 顺序陷阱：文件先行＋同值保存不重启 daemon（loaded 仍 direct）、D5 对照档 policy_repaired**。D4 的 udp_ok=False 为沙箱 UDP sendto EPERM 假象，探针不以 udp_ok 断言——healthy 只看 tcp_ok，结论不受影响）。
- **结论：R27-P1-1 已关闭**（独立复算＋行为双证）。

### §1.2 R27-P2-1（UDP 判据）——调用方双点核实

- **判据全文已读**：`_parse_socks_udp_dns_reply`（sk5_manager.py:512-540）现要求 txid 匹配＋QR 位（0x8000），任意 rcode 通过、ancount 不入判据；`_dns_reply_note`（:543-556）把答案内容（rcode／ancount）记入 note，不入 verdict。`_socks5_udp_associate_dns`（:559-646）两档尝试：(example.com, 1.1.1.1)→(cloudflare.com, 8.8.8.8)，超时／不匹配回复落入下一档；每档一个 sendto／recvfrom 调用点。
- **调用方双点**：`test_sk5()` native 路径（:900-904）与 `_udp_probe_via_uot_singbox`（:719-724，经同一 `_socks5_udp_associate_dns`）均已改用三元组（ok, ms, note），UoT 路径同症同修——无第三处（全仓搜 `_parse_socks_udp_dns_reply` 仅定义＋两处调用链）。
- **探针重跑**：`tests/r27_udp_probe_verdict.py` **6/6 PASS**（U1 ancount=0 NOERROR→True、U2 ancount=1→True、U3 两档各一 sendto／recvfrom、U4 txid 失配→False、U5 QR 位清→False、U6 note 记 "reply NOERROR an=0"）。
- **结论：R27-P2-1 已关闭**（行为＋源码双证）。

### §1.3 R27-P2-2（Worker 悬空队列）——TTL 写点独立重数

- **写点重数（本轮亲手重数，结论：修复路的 7 是对的，R27 审计员的 6 漏了一处）**：`kvPutJson` 全集枚举——queue: 4 处（:321 enqueue、:538 register、:780 sweep 合并、:880-886 poll 条件式清空——多行调用，R27 审计员的单行 grep 漏了此项）、sent: 3 处（:792 sweep、:896 poll 去重、:958 report 剔除），cmd: 8 处（:314、:571、:677、:683、:691、:870、:953 单行＋:659 多行畸形隔离写点）。**7 处 queue:/sent: 写点全部带 `{ expirationTtl: CMD_TTL_S }`，8 处 cmd: 写点全部带 TTL**——TTL 对称已闭合，无第八处 queue:/sent: 写点。Q5 探针计数（queue 4／sent 3／cmd 8）与本轮手数一致。
- **warn 点已读**：poll 下发循环（index.js:856-863）与 sent 超时循环（:826-834）遇悬空 id 均 `console.warn` 点名 id；Worker 无审计存储，console.warn 为唯一诚实信号通道（R18-P2-2 同款）。
- **探针重跑**：`tests/r27_worker_dangling_queue.mjs` **5/5 PASS**（Q1 悬空 queued id 摘掉无下发、Q2 warn 点名 id、Q3 cmd_get 404、Q4 悬空 sent id 摘掉＋warn、Q5 TTL 计数 4／3／8）。
- **结论：R27-P2-2 已关闭**（行为＋源码双证）。

## §2 零用户旅程（全新用户每一步 vs 文档承诺）

按新用户首次接触的顺序逐项核验；每项给行为证据。

### §2.1 克隆安装（R26 修复的路径）

- README 首选 `git clone https://github.com/iiiiiiiii7125-art/openvpn-sk5-panel && cd openvpn-sk5-panel && bash install.sh`——仓库已公开（public），clone 路径真实；install.sh:469 固定清单 `agent core egress panel systemd install.sh verify.sh verify-integration.sh README.md` 与 README 所列逐字一致；panel/ 走 staging 排除 data/（:470-516 全文已读，R8-BUG-1 同族无复发）；`.git/` 不进 /opt（清单复制，无整树复制）。
- 备选 scp 传包路径与 DELIVERY §1.2 一致；`OVPN_PROTO=tcp OVPN_PORT=443` 的 TCP 模式命令与 install.sh 环境变量口径一致（:161-169 fail-fast）。
- **结论：克隆安装路径 ✓。**

### §2.2 首次登录与改密（P0-3 按设计）

- 初始密码：`_ensure_admin_password()`（panel/app.py:313-345）仅当 admin 行不存在时生成 `secrets.token_urlsafe(16)`，写 `/etc/openvpn-sk5-panel/admin.pass`（0600，写失败回落 DATA_DIR）——「重装不会轮换密码」✓（行已存在即 return None，不动文件）；README「初始管理员密码随机生成、无默认值」✓。
- 改密不强制：README 明言「改密（不强制）：登录即给完整 admin 会话，不设改密前置条件」；DELIVERY §1.3「首次登录不强制改密（P0-3，按设计未实现），改密全靠人工第一步，不要跳过」——P0-3 的诚实口径在位，无误导。前端改密按钮在位（index.html:283，调 POST /api/change-password，成功后旧会话作废）；新密码 ≥12 位＋字母数字（`_validate_new_password`）与 README 一致；Cloudflare 面 501 诚实（R11-P2-1）。
- FAQ 密码丢失恢复：「删 panel/data/panel.db 的 admin 行并重启面板会重新生成」——`_ensure_admin_password` 在 admin 行缺失时重新生成并重写 admin.pass，属实 ✓（旧密码随之失效，FAQ 已明说）。
- 登录限流：5 次／5 分钟→锁 15 分钟、429＋Retry-After（app.py:1305），README 数字 ✓。
- **结论：首次登录／改密 ✓，P0-3 文档诚实。**

### §2.3 建服务、加用户、填 SK5、启用

- 建服务：对外地址留空即自动探测（`_stored_server_ip() or OVPN_ENV or detect_public_ip()`，app.py:1203-1226）✓；端口冻结口径（`allow_port_change=false` 时端口只读）与 live-18 §6 的 500 实测一致。
- 加用户：`USERNAME_RE = ^[A-Za-z0-9_-]{1,32}$`，保留名 `server`／`OpenVPN-CA`（core/openvpn_manager.py:70-114）与 README 逐字一致 ✓；CRL：`crl-verify $SERVER_DIR/crl.pem` 在 server.conf.template:17，「吊销后须重启 OpenVPN 服务才对新连接生效」✓。
- 填 SK5：端口默认 1001，前端字段旁确有「端口待确认：默认 1001；若商家给的是 9000 请填 9000 并回报」（index.html:470-471）✓；密码留空保留已存（P0-4，set_sk5 docstring）✓。
- 一键启用：enable() 重渲染＋重启＋上策略（§1.1 已复算）；5 秒 LIVE tun1 窗口与大声失败文案与 DELIVERY §6-4 一致。
- **结论：面板流程 ✓。**

### §2.4 首次故障与恢复

- 杀 sing-box → 黑洞兜底＋`blackholed_kill_switch`＋自动重起后 `policy_repaired`：BM／BO／BS 探针重跑见 §6；live-17 真机格已证。
- verify.sh 默认路径：已启用真实 SK5 时三格 SKIP（R27 §1.2 已读 :644-647）；强制路径：R27-P1-1 已修，本轮 §1.1 闭合（探针 8/8）。
- 卸载：README 手动卸载命令的 5 个单元名与 systemd/ 目录逐项一致（panel／singbox／policy／healthcheck 服务＋定时器）；NAT／FORWARD／ufw 清理命令与 AN 已接受口径一致。
- **结论：故障／恢复／卸载 ✓。**

### §2.5 首次升级（带存量数据）

- DELIVERY §7：默认重跑 `bash install.sh` 不销毁线上 panel.db（R8-BUG-1 已修，live-9 至 live-17 九轮毒树默认重跑行级终验）；升级前备份 `panel/data/`、回滚拷回——沙箱内无 systemd／OpenVPN 真机，升级路径本身属 live 轮；本轮核 install.sh 的 panel/ staging 排除（§2.1）与 gate 的集成格（§5）为机制佐证，无新缺口。
- **结论：升级路径沙箱级 ✓（真机终验属 live 轮）。**

### §2.6 Cloudflare 模式（新用户第一入口即踩坑）——见差集 R28-P2-1

- README 的 Cloudflare 节（「部署方式二：Cloudflare 面板 + agent（推荐，FLMX 同款）」）存在两处与 DELIVERY §2／cloudflare/README.md 不一致的缺口，详见 §8 **R28-P2-1**：(a) 步骤缺 KV id 填入 wrangler.toml 的关键一步；(b) 全 README 无一处「未验」标注，却把从未真机验证的模式标为「推荐」。

## §3 功能链全量对账（README / DELIVERY.md / security.md 逐项对行为）

### §3.1 机械计数复核（本轮独立重算）

- **13 动作白名单三面逐字一致**：Flask `AGENT_ACTIONS`（app.py:199）、agent `ACTIONS`（agent.py:754）、Worker `ACTIONS`（index.js:64）——R27 §4.1 已机械比对三面各 13 项排序后逐字相同；本轮树在 R27 后未改三面（git diff：index.js 改动仅 7 处 TTL＋2 处 warn，ACTIONS 未动），结论沿用。
- **verify.sh 24 项检查**：R27 §1.2 独立重算 24 distinct 名＋12 编号节；本轮 verify.sh 改动仅 cleanup() 恢复逻辑，未增删检查名——计数沿用，门禁 §5 另验。
- **发布包快照**：`tar tzf` 92 条目＝78 文件＋14 目录 ✓（本轮实测）；DELIVERY §9 的 verify.sh 哈希 `7867f557c6bb` 与包内 verify.sh 实测一致 ✓；audit 25 篇／live 17 份与包内实测一致 ✓——§9 是 1.0 包的真实快照，刷新属发版步骤（O-R27-1），不当轮立案。
- **verify.sh 退出码**：FAIL 数即退出码（尾部 `exit "$FAIL"`）✓，与 README 一致。

### §3.2 功能矩阵（功能 → 行为证据；探针编号见 §6）

| 功能（README／DELIVERY 宣称） | 行为证据 | 结论 |
|---|---|---|
| OpenVPN UDP 1194 主／TCP 443 备 | Core 46/46（§6 重跑）；install.sh 环境变量＋存量继承＋非法值早死 | ✓ 沙箱级；数据面属 live 轮 |
| 建用户／吊销／下载 .ovpn | Core 46/46；Flask 86/89（绿格内）；用户名正则＋保留名逐字一致（§2.3） | ✓ |
| SK5 启用／停用 | BM 22/22、BO 18/18、BS 9/9、BT 23/23、R24 25/25、R25 37/37（§6 重跑） | ✓ |
| 断网保护 fail-closed | BM K1–K5（真实 netns＋真实 ip） | ✓ |
| 健康检查 60 秒＋自愈 | 定时器 OnUnitActiveSec=60s；BM H1–H10；BS 9/9 | ✓ |
| 命令队列＋agent 5 秒 poll | POLL_INTERVAL=5（agent.py:70）；R17 四套件；R21 6/6；BQ 6/6 | ✓ |
| Flask＋Worker 双面 | R17 四套件；BR 11/11；R27 Worker 5/5 | ✓（Worker 真机部署仍 P0-1 未验） |
| 登录限流 | Flask／Worker 双面格；BR 11/11；429＋Retry-After（app.py:1305） | ✓ |
| 密码处理 | bcrypt＋透明迁移；改密格；Worker 改密 501；默认口令 grep 零命中（§4） | ✓ |
| 重建 CA（force+confirm） | Flask F-cells；R17-P1-1 守卫 | ✓ |
| /api/sk5/test UDP 腿 | 判据已修 round-trip 证明（§1.2，探针 6/6） | ✓ 已关闭 |
| verify.sh 强制路径 | API 先行恢复运行链（§1.1，探针 8/8） | ✓ 已关闭 |
| README Cloudflare 节 | KV 填 id 步缺失＋「推荐」无未验标注 | ✗ P2，见 R28-P2-1 |

## §4 安全清单对账（docs/security.md 逐项抽查）

- **默认口令字面量零命中**：`grep -rnw "admin123\|changeme\|123456" panel/ agent/` 零命中；`password123` 零命中 ✓。
- **限流 XFF 守卫**：仅 `OVPN_TRUSTED_PROXY=1` 时才信任 X-Forwarded-For（app.py:182-183，ProxyFix），默认不信任 ✓。
- **会话**：Cookie HttpOnly＋SameSite=Lax、12 小时、改密后 session_version+1 全旧会话失效——R17 Flask 绿格内（§6 重跑）。
- **SK5 凭据**：只存 sk5.json（0600），get_status 只回 has_password、日志脱敏——R17 Flask 绿格内；P0-4 保留密码语义（§1.1 已复算）。
- **命令重投非幂等风险**：security.md 已诚实记录（O-R27-2 沿用，不立案）。
- **agent 通道**：panel_url 须 HTTPS（仅 127.0.0.1／localhost／[::1] 例外）、禁 https→http 降级重定向——R17 Agent 33/33（§6 重跑）。
- **结论：security.md 抽查项与行为一致，无新缺口。**

## §5 门禁（verify-integration.sh 29 格，串行）

- **正树：PASS=29 FAIL=0 SKIP=0，exit 0**（/tmp/r28/ptree 上跑，约 24 秒，树静止后串行——门禁 harness 非并发安全，固定 /tmp/ovpn-int-test＋8443 端口）。
- **§7 变异 11/11 恰红 28/1**：`tests/build-mutants.py` 造 11 棵变异树（m-char、m-const-sb、m-dict-extra、m-dict-missing、m-dict-sb、m-dict-ts、m-dict-x-a、m-dict-x-amd、m-dict-x-arm、m-dict-x-b、m-install-sb），逐棵串行跑门禁，**每棵均为 PASS=28 FAIL=1 SKIP=0、exit=1，且唯一红格全为 §7「钉死哈希不一致：install.sh 与 agent/agent.py 的 sha256 逐键不等」**（逐棵 grep 核对，无第二红格；日志 /tmp/r28/gate-m-*.log）。

## §6 探针套件重跑

全部在 /tmp/r28/ptree（工作树副本）上重跑；Flask 类跑在 nobody 身份＋venv＋fixture env（OPEN 前缀＋OVPN_SK5_CONFIG_DIR），Worker 类 `node tests/*.mjs`。**红格说明**：下表凡标注「预期翻转」的红格均为缺陷钉死格（探针断言的是缺陷行为本身，修复后按设计翻红），非回归。

| 套件 | 结果 | 备注 |
|---|---|---|
| R17 Flask | 86/89 | 仅 3 个预期 OBSERVED 翻转（F4-02b／F4-13／F4-15） |
| R17 Core | 46/46 | |
| R17 Agent | 33/33 | |
| R17 Worker | 33/35 | 仅 2 个预期 OBSERVED 翻转（W5-05／W5-06a） |
| BK（存量形状） | 8/8 | |
| BM（黑洞＋自愈） | 22/22 | |
| BO（tun1 repair） | 18/18 | |
| BP（boot restore） | 14/14 | |
| BQ（队列不可读） | 6/6 | |
| BR（Worker loginfail 数组） | 11/11 | |
| BS（verdict） | 9/9 | |
| BT（占位符消除） | 23/23（PASS 行计数 23，0 FAIL） |
| R24（enable 占位符） | 25/25（PASS 行计数 25，0 FAIL） |
| R25（repair 收敛） | 37/37（PASS 行计数 37，0 FAIL），须 root |
| R21（队列隔离） | 6/6 | |
| R22 Flask（时间边界） | 22/22 | |
| R22 Worker | 12/12 | |
| R23 Flask（持久态形状） | 13/13（main）＋empty_secret／db_garbage／db_empty／db_old_admin 各 1/1 PASS |
| R23 Worker | 9/9 | |
| R20（输入形状） | 7 格，3 红为预期缺陷钉死翻转（S1／S2／S6）；须 root |
| R18 Worker race／malformed | race 9 格 2 红、malformed 13 格 4 红，均为预期翻转 | R18 探针断言的是缺陷行为；修复后行为由 BI 套件验证 |
| R19 非列表容器／ovpn 下载 | 12/12、8/8 | |
| BH Worker poll guard | 20/20 | |
| BI Worker queue race／malformed | 15/15、18/18 | |
| R27 强制分歧 | 8/8 | R27-P1-1 闭合（§1.1） |
| R27 UDP 判据 | 6/6 | R27-P2-1 闭合（§1.2） |
| R27 Worker 悬空队列 | 5/5 | R27-P2-2 闭合（§1.3） |

**注**：R23 empty_secret 模式摘要行打印为 `R23 empty_secret: <redacted>`——该行是探针自身对 secret 值的脱敏打印，非失败；该模式唯一格 R2b（空 secret 下真实登录大声 500）为 PASS，故该模式计 1/1。

**结论**：历史关闭项无一复发；全部红格均为钉死缺陷行为的预期翻转或 R27 新探针的直接复现（现已翻绿，见 §1）。

## §7 live-18 与补记的交叉核对

（R27 §7 已逐项核对；本轮树在 R27 后只改 verify.sh／sk5_manager／index.js 三文件，live-18 的树侧可核项结论沿用，无须重核。唯一新增：R27-P1-1／P2-1／P2-2 三条的真机格属 live-19，待 live 轮。）

## §8 差集（新发现）

### R28-P2-1（P2）——README 的 Cloudflare 节缺 KV id 填入步骤、且把从未真机验证的模式标为「推荐」；全 README 无一处「未验」标注

- **机制（文档 vs 文档，机械枚举）**：新用户第一入口文档是 README（仓库首页即此文件）。其 Cloudflare 节写道：「部署方式二：Cloudflare 面板 + agent（**推荐**，FLMX 同款）」，步骤为 `wrangler kv namespace create PANEL_KV` → `wrangler kv namespace create PANEL_KV --preview` → `wrangler secret put ADMIN_PASSWORD` → `wrangler deploy`。**缺失关键一步**：两条 namespace 命令输出的 id／preview_id 须填进 `wrangler.toml` 对应位置——这一步在 DELIVERY §2.1（「把两条命令输出的 id / preview_id 填进 wrangler.toml 对应位置」）、cloudflare/README.md:30（同款文字）、wrangler.toml 头注释（「把上面两条命令输出的 id / preview_id 填到下面对应位置；填之前 wrangler deploy 会报错」）三处都有，唯独 README 的步骤里没有。`wrangler.toml:32-33` 仍为占位符 `REPLACE_WITH_KV_NAMESPACE_ID`／`REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`（本轮已核）。照 README 逐字执行的用户会在 `wrangler deploy` 处报错，README 内无任何指引告诉他缺了哪一步（须自行去读 wrangler.toml 注释或 DELIVERY §2 才能找到）。
- **第二缺口**：全 README 用 `grep -n "未验\|未验证\|P0-1"` 搜得 **0 命中**——README 通篇没有任何「未验」标注，却把 Cloudflare 模式标为「推荐」；而该模式是 P0-1（从未在真实部署上验证，问过用户十一次未复，DELIVERY §2 带显式未验横幅）。cloudflare/README.md 同样 0 处「未验」标注（grep 同款零命中）。新用户会被「推荐」二字导向一条未经验证的路，且无任何提示告知他这条路未经验证。
- **用户影响**：P2——部署失败是大声的（DELIVERY §2.1：「填之前 wrangler deploy 会报错，这是故意的」），无静默误导、无数据风险；但新用户照入口文档走必然多一次失败往返，且「推荐」标签与 P0-1 未验状态直接矛盾。不是 R26-P2-1／P2-2 的复发（那两条是 README／DELIVERY 的旧说法残留；本条是 README 的 Cloudflare 节自始缺失的关键步骤＋未验标注缺失，与 R26 的两条无重叠）。
- **范围（机械推导，闭合）**：三份文档的 Cloudflare 步骤逐项比对——DELIVERY §2.1（含填 id 步＋未验横幅）✓、cloudflare/README.md（含填 id 步，缺未验标注）、README（两项皆缺）。wrangler.toml 头注释含填 id 指引，可作用户自救路径，但不替代入口文档的步骤完整性。
- **修法**：README 的 Cloudflare 节照 DELIVERY §2.1 补两项：(1) 在 `wrangler kv namespace create` 两步之后加「把输出的 id／preview_id 填进 wrangler.toml」一步；(2) 在节首加与 DELIVERY §2 同款的未验横幅（P0-1，从未真实部署验证），并把「推荐」改为「可选」或注明「未经真机验证」。cloudflare/README.md 同步补未验标注一行。

## §9 未验与观察

### O-R28-1（观察，不立案）：新版重打时 DELIVERY §9 与卷首台账须刷新（O-R27-1 延续）

- DELIVERY §9 包内清单（78 文件、审计 25 篇、live 17 份）与卷首「历史台账 163 条」「终审 AUDIT-R25」均为 1.0 发布包的真实快照（包未重打），当前不算漂移；但新版重打时必须按实测刷新：审计 25→28 篇、live 17→18 份＋补记、台账 163→169（168＋R28 新 1）、终审 R25→R28。本轮不为此立案，列为发版前检查项。

### O-R28-2（观察，不立案）：README／DELIVERY §1.3「退出时原样恢复」是成功路径表述

- 成功路径下 cleanup 确为「原样恢复」（API 重启用运行链＋文件拷回字节一致，探针 D3 已证）。失败路径下文件按设计**不**恢复（大声 FAIL、链路诚实保持禁用、备份留 workdir 供手工恢复）。README／DELIVERY 的「退出时原样恢复，无须事后重填 SK5」未加失败路径限定词；但失败路径本身大声且自明（FAIL 行逐字告知用户链路已禁用、密码仍存、备份位置），用户不会被误导。建议发版时在两处补一句失败路径说明，不立案。

### O-R28-3（观察，不立案）：DELIVERY §5 的 UDP 拨测括号只写了第一档

- §5 称「（native UDP ASSOCIATE + DNS to 1.1.1.1:53）」——R27-P2-1 修法后探针在无回复时重试第二档（cloudflare.com，8.8.8.8）。括号对第一档的描述仍真，但未提第二档。建议刷新措辞，不立案。

### O-R27-2（观察，延续）：agent 侧无命令去重，重投即重执行（已文档化、危害有界）

- security.md:12 已诚实记录；create_user 二次执行报已存在、init_pki 二次执行无新增用户损害、其余动作幂等。不立案。

### O-R27-3（观察，延续）：OVPN_PORT 前导零大声失败，不断言

- `OVPN_PORT=0117` 过 bash 八进制检查、Python 渲染为 117、grep 校验 die——大声失败，无静默错配。不立案。

### P0-1（站立未验）：Cloudflare Worker 真实部署

- 本轮仍无真实部署可验，不冒充。Worker 面只跑 mock-KV 探针。wrangler.toml KV id 仍为占位符（:32 `REPLACE_WITH_KV_NAMESPACE_ID`、:33 `REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`，本轮已核）。

### arm64 真机安装／SK5 端口 1001 vs 9000

- 均未变：无 arm64 机，仍未验；端口用户仍未确认，面板默认 1001。

## §10 审计方法与证据

- 探针一律在 /tmp 树副本＋venv＋nobody 身份下跑（Flask 类），env 名用 OPEN 前缀（`OPENVPN_CA_DIR`／`OPENVPN_SERVER_DIR`）＋`OVPN_SK5_CONFIG_DIR`；各探针的树 env 名按探针头读名设值（BQ_TREE／R21_TREE／R22_TREE／R23_TREE／R17_TREE）；r20／r25／r27-verify 须 root 跑（unshare 绑挂／ip 操作），且 /tmp/r28 整条路径须对 userns 内可遍历（755）；fixture-server／fixture-ca 须属 nobody 所有。/etc/openvpn-sk5-panel/ 每次跑后复核为空（终态复核：空，0 泄漏）。
- 沙箱 UDP/TUN EPERM 为环境假象，不作产品结论；数据面结论属 live 轮。
- 本轮复跑中纠正的调用口径问题（数字为纠正后实测，如实记账）：① 三个 Worker 探针首轮用了错误的文件名（r22_worker_bounds／r23_worker_shapes／r19_worker_nonlist 不存在；实为 r22_time_bounds／r23_persist_shapes／r19_worker_nonlist_container），纠正后 12/12、9/9、12/12；② BT／R24／R25 探针只打印 ALL PASS 无总数，纠正后按 PASS 行重数 23／25／37；③ 报告结构两次误编辑（§1 表头、§3 表头被替换），均已用脚本修复并复核节号顺序。
- 门禁串行跑（harness 非并发安全）；变异 11 棵逐棵串行，日志 /tmp/r28/gate-m-*.log；探针全日志 /tmp/r28/py-probes.log。
- 本轮未提交、未推送任何改动；报告为未跟踪文件。

# AUDIT-R27 — 敌对操作员全量审计（2026-11-13）

> 方法：adversarial operator（与 R26 的 repo-consumer journey、R25 的 repair-path convergence 均不同）。假设操作员把一切都做错：损坏/破坏文件、顺序颠倒、并发冲突操作、强制标志（VERIFY_ALLOW_OVERWRITE_SK5=1）、陈旧状态、重放。敌对输入空间按代码搜索机械枚举，逐项验行为。另复核时效衰减：自 R26 以来文档中任何带日期/计数宣称是否过期。
> 审计树：`~/workspace/openvpn-sk5-panel/`，git main @ b395ef3（1.0 发布提交，与公开仓库一致）＋未提交工作区修复（README.md、docs/DELIVERY.md、verify.sh 三文件，R26 两条的修复）。
> 历史台账：R26 终点 165 条（已修 160、部分 2（按设计）、未验 1（P0-1 Cloudflare 真实部署）、新 2（R26-P2-1／P2-2，本轮待验关闭））。本轮新增 3 条后台账 168 条（已修 160、部分 2、未验 1、新 3）。
> 夹具：/tmp/r27（fixture-ca 含 ta.key、fixture-server server.conf port 1194 proto udp、venv Flask 3.1.3；/tmp 第六次被清空后由 tests/rebuild-r17-fixture.sh 重建，fixture-server/server.conf 须手工渲染 udp 1194）；系统 python3 无 flask（预期）。

## verdict：**不能交付：差集 3 条，P1×1（R27-P1-1）＋P2×2（R27-P2-1、R27-P2-2），见 §8**

门禁 29/29；§7 变异 11/11 恰红 28/1；探针全套重跑见 §6（历史关闭项无一复发；三处“红”均为缺陷钉死格的预期翻转）。Cloudflare Worker 真实部署仍 P0-1 未验。

## §0 审计基线与树状态

- 本地树：main @ b395ef3，`git status`：3 文件已修改未提交（README.md、docs/DELIVERY.md、verify.sh，均为 R26 修复）；未跟踪：docs/audit/AUDIT-R26.md、docs/live-verify-R18.md、docs/live-verify-R18-supplement.md（live-18 路落盘）、docs/audit/AUDIT-R27.md（本轮）、tests/r27_verify_forced_divergence.py、tests/r27_udp_probe_verdict.py、tests/r27_worker_dangling_queue.mjs（本轮新探针）。
- 公开仓库：https://github.com/iiiiiiiii7125-art/openvpn-sk5-panel（public，2026-11-13 用户令公开）。本轮审计的是本地工作树（含未提交修复），不是仓库 HEAD——仓库 HEAD 仍为 b395ef3，未含 R26 修复；发新版前须提交并推送（见 §9 收尾）。
- 探针树：/tmp/r27/ptree（本地工作树副本，含未提交修复）；fixture /tmp/r27（fixture-ca＋fixture-server，/tmp 第六次被清空后由 tests/rebuild-r17-fixture.sh 重建；fixture-server/server.conf 须手工渲染 udp 1194，脚本只复位已存在的文件）；venv /tmp/r27/venv（Flask 3.1.3＋bcrypt，新建）。
- /etc/openvpn-sk5-panel/：本轮跑前不存在，我方 pre-create 后探针复核仍为空（0 泄漏）。

## §1 R26 修复闭合核验（行为实证，不认代码在场）

### §1.1 R26-P2-1（README「无公开仓库」）——已关闭

- diff 核：README.md:55 改为首选 `git clone https://github.com/iiiiiiiii7125-art/openvpn-sk5-panel`（目标机上直接 clone＋`bash install.sh`），scp 传包降为备选（目标机不能直连 GitHub 时）；新增安装器固定清单复制说明（`.git/` 不进 /opt）；DELIVERY §1.2 同改（clone 为主、传包为备）。
- 行为核：install.sh 固定清单复制（R26 §2.1 已验，:469 固定清单、`panel/` staging 排除 data/）；本轮重读 install.sh 复制段确认无整树复制（见 §3.1）。
- 残留 sweep：全仓搜「无公开」／「不走 git clone」——0 活宣称（仅 AUDIT-R26.md:90 引用旧状态的历史记录，不改）。

### §1.2 R26-P2-2（DELIVERY §1.3 verify.sh 警告与行为相反）——文档已改，行为一半关闭、一半立案

- diff 核：三处统一改写——README 自检节、verify.sh:37-46 头部注释、DELIVERY §1.3。改后说法：「已启用真实 SK5 时切换测试（sk5-toggle / sk5-egress-ip / sk5-disable）自动 SKIP，什么都不改；`VERIFY_ALLOW_OVERWRITE_SK5=1` 可强制，跑之前脚本先备份 sk5.json 与 sing-box.json、退出时原样恢复，无须事后重填 SK5 密码」。
- 行为核（SKIP 守卫）：verify.sh:644-647 全文已读——`SK5_PRIOR_HOST` 非空且 `SK5_PRIOR_ENABLED=true` 且未设强制标志时三格 SKIP，守卫真实。备份点 :651-652（`cp sk5.json/sing-box.json → $WORKDIR/*.bak`）、cleanup :103-108（`cp *.bak` 恢复；未备份且原先不存在则删文件）全文已读，文件恢复真实。
- 项数机械重算：`grep -oE '(ok|bad|skip) "[a-z0-9-]+"' verify.sh` 去重＝**24 个 distinct 检查名**（agent-bundle、direct-forwarding、egress-crosscheck、files、install-agent-script、install-copies-agent、installed-agent-tree、openvpn、panel-login、panel-reachable、panel-status、sing-box-config、sing-box-running、sing-box-steady、sing-box-version、sk5-disable、sk5-egress-ip、sk5-enable-endpoint、sk5-toggle、sk5-toggle-on、starter-template-consistency、stub-socks5、syntax、user-ovpn）；编号节 12 个（1、2、3、4-6、7、8、9-11、forwarding、12）。DELIVERY「24 项检查」✓，与 R26 的「12 节 24 格」一致——我独立重算，未采信修复路数字。
- **但强制路径的文件恢复≠链路恢复**：cleanup 只恢复两个文件，不恢复运行态。见差集 **R27-P1-1**（§8）：强制跑完后磁盘称启用、运行中 sing-box 仍是 direct 配置，下一个健康检查档把该状态洗成 healthy——修复路只修了文档措辞，未修强制路径本身的语义缺口。

### §1.3 修复本身引入的新漂移 sweep

- 全仓搜「重填 SK5」／「cannot be restored」／「不要跑 verify.sh」／「14 项」／「无公开」：0 活表述残留（三处已改处措辞与行为一致，§1.2 的 P1-1 除外——那是行为缺口，不是措辞漂移）。
- DELIVERY §9 包内清单（78 文件、审计 25 篇、live 17 份、门禁 29 格）：仍为 1.0 发布包的真实内容（包未重打），不算漂移；但新版重打时必须刷新（见 §9 O-R27-1）。

## §2 O-R18-1 裁定：/api/sk5/test UDP 腿误报——立案为 R27-P2-1

- live-18 证据（§4）：UDP 中继全程通畅（39 字节查询发出、29 字节回复收回、txid 一致、dante 日志同证），空的是答案本身——上游 1.1.1.1 对固定查询名 example.com 返回 an=0 的 NOERROR；同 resolver 查 cloudflare.com an=2、google.com an=6；8.8.8.8 查 example.com an=2。r17-release 约 40 分钟前同一探针曾得 udp_ok native——行为随时间变化。
- 本轮探针 `tests/r27_udp_probe_verdict.py` **3/3**（纯函数级，无 socket——沙箱 UDP EPERM）：
  - U1：txid 匹配、rcode 0、ancount=0 的回复 → verdict False（live-18 形状：中继已证工作，探针称 UDP 死亡）。
  - U2：同包 ancount=1 → True。
  - U3：单发单收（sendto=1、recvfrom=1，无重试）、单一查询名（DNS_QUERY_NAME 唯一）、单一 resolver（DNS_SERVER=1.1.1.1 唯一）。
- 裁定：**立案，见 §8 R27-P2-1**。理由：判据测的是 resolver 的答案库，不是中继本身——txid 匹配的合法 DNS 回复到达即已证明 UDP 中继双向通畅，ancount>=1 是比被测属性更严的要求；且单发无重试使一次丢包亦可误报。定 P2：只影响 /api/sk5/test 的用户侧结论与 health.json 的 detail 文案；check_health 的 healthy 只看 tcp_ok（sk5_manager.py:1358-1363），误报不触发 fail-over／kill-switch 误判，故不是 P1。O-R18-1 就此关闭，不再以观察挂账。

## §3 敌对操作员：敌对输入空间机械枚举

敌对空间按代码搜索机械枚举（每类给全集清单＋处置）：

### §3.1 安装路径敌对操作

- **install.sh 复制面**：固定清单复制（agent core egress panel systemd install.sh verify.sh verify-integration.sh README.md）；panel/ 走 staging 排除 data/；`.git/`、tests/、docs/、releases/、cloudflare/ 不进 /opt。R26 §2.1 已验，本轮重读复制段确认无整树复制——clone 安装与 tarball 安装在复制层等价。
- **OVPN_PROTO/PORT/SUBNET 非法值**：install.sh:161-169,:180-208 环境变量＋存量继承，非法值 fail-fast die（见 §3.6 逐项核）；OVPN_SUBNET≠10.8.0.0/24 直接拒绝（AZ）。
- **并发安装（同目标 apt 锁）**：D13 已裁定 operator error（loser 死在首个门禁、零写入），不重立。
- **安装目标误指 /root/flmx-panel**：断言退出（install.sh 守卫），不重立。
- **SINGBOX_SHA256/TUN2SOCKS_SHA256 覆盖错哈希**：安装器校验失败即停（R1 钉死），不重立。

### §3.2 verify.sh 强制标志敌对操作——立案 R27-P1-1

见 §8。触发：`VERIFY_ALLOW_OVERWRITE_SK5=1` ＋ 面板已启用真实 SK5。verify.sh cleanup 只恢复文件（sk5.json＋sing-box.json），不恢复运行态；下一健康检查档把文件/运行态分歧洗成 healthy＋via_sk5=true，而 VPN 流量实际走直连。探针 `tests/r27_verify_forced_divergence.py` **7/7**（真实 sk5_manager 函数＋真实 policy-routing.sh＋真实 curl／SOCKS stub＋stub sing-box 记录 loaded config；沙箱 UDP EPERM 致 D4 的 udp_ok=False，属环境假象，不影响 healthy 只看 tcp_ok 的结论）。

### §3.3 探针 UDP 判据敌对操作——立案 R27-P2-1

见 §2。单发、单名、单 resolver、ancount>=1。

### §3.4 队列／agent／Worker 敌对枚举

- **Flask 队列读点全集**：`_load_queue()` 调用点 9 处（:586 enqueue、:1887、:2382、:2406、:2414、:2484 cmd_get、:2545、:2603、:2663），另仅 :197 一处为路径常量——无任何旁路直读 agent_queue.json。隔离＋审计行在 `_load_queue` 内部（BN/BQ），9 处按结构全覆盖（BA 的 8 处→9 处是新增调用点，非旁路）。
- **Flask 队列损坏谱**：整文件不可解析（BN 审计行）、顶层非对象（BN）、某段非对象（R21 Q5）、文件不可读（BQ 隔离＋raise）——四层均有探针（R21 6/6、BQ 6/6，§6 重跑）。
- **agent 输入谱**：`_as_int` 拒 bool／float、数字串容忍（AX 钉死）、范围 1–65535；`_as_bool` 只认真 bool；`_as_proto` 只认 udp/tcp；`execute_command` 未知 action 拒、params 非对象拒、shell 键（command/shell/cmd/exec/script/argv）分派前拒。以上均已读全文，无新成员。
- **agent 重放（无 dedup）**：`run_once` 对 poll 回执逐条执行，回执丢失→面板 120 秒后重投→agent 重执行。见 §9 O-R27-2（已文档化、危害有界，不立案）。
- **Worker 队列谱**：条件式清空（BI）、queued-only 下发（BH）、畸形 sweep（BI）、非列表容器（BJ kvArray）、loginfail 数组（BR）——均有探针（§6 重跑）。**新成员：悬空 id 静默丢失，见 §8 R27-P2-2**（queue:/sent: 无 TTL 而 cmd: 7 天 TTL；sweep 只遍历活记录，看不见悬空 id；poll 的 `if (!cmd) continue`＋条件式清空／stillSent 重建静默摘掉，零痕迹）。

### §3.5 登录限流／密码／CA 敌对枚举

- **限流**：`_login_attempts_row` 读时按窗口（LOGIN_WINDOW_SECONDS）剪掉过期失败时间戳——跨日失败不累积；锁满 5 次即锁 15 分钟并清空 failures；记账写盘失败不阻塞登录 verdict（R9-P2-2），无行即无锁（不谎称已锁）。Worker 侧：kvLoginFailRecord（BR）＋锁 15 分钟＋Retry-After 900。无新成员。
- **密码**：bcrypt＋透明迁移＋改密（Flask 格在 R17 86 绿格内；Worker 改密 501 诚实）；初始密码 `secrets.token_urlsafe(16)`；默认口令字面量全仓 0 命中（R26 §2.1，本轮未重扫——树无改动，结论沿用；见 §4）。
- **CA 重建**：force+confirm 双确认缺一即 400（Flask F-cells）；init_pki 只认 queued 态下发（BG/BH）。无新成员。

### §3.6 install.sh 输入敌对格

- **OVPN_PROTO**：:161-164 只认 udp/tcp，其余 die（在 apt／下载之前，fail-fast）。
- **OVPN_PORT**：:166-169 数字＋1–65535，非法 die；前导零口径见 §9 O-R27-3（"0117" 过 bash 八进制检查、Python 渲染为 117、grep 校验 die——大声失败，无静默错配）。
- **OVPN_SUBNET／OVPN_DNS**：:180-208 python 校验＋子网固定 10.8.0.0/24（AZ），非法 die。
- **SINGBOX_SHA256／TUN2SOCKS_SHA256 覆盖**：`verify_asset()`（install.sh:315）对期望哈希做严格 64-hex 校验（:340 字符集、`[ -n "$want" ]` 守卫、:342 长度 64），错哈希／非 64-hex 即 die，校验失败即停（R1 钉死）。
- **并发安装／误指 FLMX 目录**：D13 已裁定 operator error；FLMX 断言退出。无新成员。

## §4 功能链全量对账（README / DELIVERY.md / security.md 逐项对行为）

### §4.1 机械计数复核（本轮独立重算）

- **13 动作白名单三面逐字一致**：Flask `AGENT_ACTIONS`（app.py:199）、agent `ACTIONS`（agent.py:754）、Worker `ACTIONS`（index.js:64）——三面各 13 项、排序后逐字相同（create_server、create_user、disable_sk5、enable_sk5、get_status、init_pki、install_prereqs、restart_openvpn、revoke_user、set_sk5、start_openvpn、stop_openvpn、test_sk5）。README:48「13 个动作，两端白名单逐字一致」✓（注：三面，非两端——措辞略旧，含义无误）。
- **verify.sh 24 项检查**：见 §1.2，独立重算 24 distinct 名＋12 编号节 ✓。
- **发布包**：`tar tzf` 92 条目＝78 文件＋14 目录，sha256 与 sidecar 一致 ✓（DELIVERY §9 包内清单属实，1.0 包未重打）。
- **门禁 29 格**：见 §5（本轮重跑）。
- **登录限流数字**：5 次／5 分钟→锁 15 分钟、429＋Retry-After——Flask（app.py:405-460）与 Worker（BR 11/11）双面一致，README:269／security.md:9 ✓。

### §4.2 功能矩阵（功能 → 行为证据；探针编号见 §6）

| 功能（README／DELIVERY 宣称） | 行为证据 | 结论 |
|---|---|---|
| OpenVPN UDP 1194 主／TCP 443 备 | Core 46/46；install.sh 环境变量＋存量继承＋非法值早死（§3.6） | ✓ 沙箱级；数据面属 live 轮 |
| 建用户／吊销／下载 .ovpn | Core 46/46；Flask 86/89（绿格内） | ✓ |
| SK5 启用／停用 | BM 22/22、BO 18/18、BS 9/9、BT 全过、R24／R25 全过 | ✓ |
| 断网保护 fail-closed | BM K1–K5（真实 netns＋真实 ip） | ✓（但见 R27-P1-1：强制自检后的分歧态可绕过健康 verdict 的感知） |
| 健康检查 60 秒＋自愈 | 定时器 60s；BM H1–H10；BS 9/9 | ✓（verdict 盲区见 R27-P1-1） |
| 命令队列＋agent 5 秒 poll | R17 四套件；R21 6/6；BQ 6/6 | ✓（Worker 悬空 id 见 R27-P2-2） |
| Flask＋Worker 双面 | R17 四套件；BR 11/11 | ✓（Worker 真机部署仍 P0-1 未验） |
| 登录限流 | Flask／Worker 双面格；BR 11/11 | ✓ |
| 密码处理 | security.md 抽查；Flask 改密格；Worker 改密 501 | ✓ |
| 重建 CA（force+confirm） | Flask F-cells；R17-P1-1 守卫 | ✓ |
| /api/sk5/test UDP 腿 | 判据缺陷，见 R27-P2-1 | ✗ P2 |
| verify.sh 强制路径 | 文件恢复≠运行恢复，见 R27-P1-1 | ✗ P1 |

### §4.3 未再发现（除 §8 三条外）

- R26 §2.3 的 sweep 范围（「重填 SK5」／「cannot be restored」／「14 项」／「无公开」）本轮重扫：0 活表述残留。
- 历史 165 条关闭项：本轮探针重跑无一复发（§6）。

## §5 门禁（verify-integration.sh 29 格，串行）

- **正树：PASS=29 FAIL=0 SKIP=0，exit 0**（/tmp/r27/gate.log，约 21 秒，树静止后串行重跑——门禁 harness 非并发安全，固定 /tmp/ovpn-int-test＋8443 端口）。
- **§7 变异 11/11 恰红 28/1**：`tests/build-mutants.py` 造 11 棵变异树（m-char、m-const-sb、m-dict-extra、m-dict-missing、m-dict-sb、m-dict-ts、m-dict-x-a、m-dict-x-amd、m-dict-x-arm、m-dict-x-b、m-install-sb），逐棵串行跑门禁，**每棵均为 PASS=28 FAIL=1 SKIP=0、exit=1，且唯一红格全为 §7「钉死哈希不一致：install.sh 与 agent/agent.py 的 sha256 逐键不等」**（逐棵 grep 核对，无第二红格）。变异树与日志在 /tmp/r27/gate-mutants/ 与 /tmp/r27/gate-m-*.log。
- **简报勘误**：任务简报称「重跑 scripts/check-doc-consistency.sh」——该文件在本树不存在（无 `scripts/` 目录；系 FLMX 侧的门禁名误植）。本树实际门禁即 verify-integration.sh（29 格，内含 §7 钉死哈希格）。本轮按实际门禁执行并记录此勘误，不虚构一次不存在的脚本运行。

## §6 探针套件重跑

全部在 /tmp/r27/ptree（工作树副本）上重跑；Flask 类跑在 nobody 身份＋venv＋fixture env（OPEN 前缀＋OVPN_SK5_CONFIG_DIR），Worker 类 `node tests/*.mjs`。**红格说明**：下表凡标注「预期翻转」的红格均为缺陷钉死格（探针断言的是缺陷行为本身，修复后按设计翻红），非回归。

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
| BT（占位符消除） | 23/23 ALL PASS | |
| R24（enable 占位符） | 25/25 ALL PASS | |
| R25（repair 收敛） | 37/37 | 须 root 跑（unshare＋ip）；见下 |
| R21（队列隔离） | 6/6 | |
| R22 Flask（时间边界） | 22/22 | |
| R22 Worker | 12/12 | |
| R23 Flask（持久态形状） | 13/13（main）＋R2／R3／R4／R5 四形状模式各 PASS | 5 个 R23_MODE 各为独立进程 |
| R23 Worker | 9/9 | |
| R20（输入形状） | 7 格，3 红为预期缺陷钉死翻转（S1／S2／S6） | S1／S2 存量 port bool／float 现诚实 ValueError；S6 list 形 sk5.json 现 heartbeat 正常返回；须 root 跑（unshare 绑挂） |
| R18 Worker race／malformed | race 9 格 2 红、malformed 13 格 4 红，均为预期翻转 | R18 探针断言的是缺陷行为；修复后行为由 BI 套件验证（race 15/15、malformed 18/18 全绿） |
| R19 非列表容器／ovpn 下载 | 12/12、8/8 | |
| BH Worker poll guard | 20/20 | |
| BI Worker queue race／malformed | 15/15、18/18 | |
| R27 强制分歧（新） | 7/7 | R27-P1-1 直接复现 |
| R27 UDP 判据（新） | 3/3 | R27-P2-1 直接复现 |
| R27 Worker 悬空队列（新） | 5/5 | R27-P2-2 直接复现 |
| r20_reverts／r21_reverts | 造变异树成功（exit 0） | 仅构建脚本；回退翻转的执行验证在其各自轮次已完成，本轮未重执行 |

**本轮复跑中抓到的调用口径问题（均已纠正并重跑，数字为纠正后实测；如实记账，不粉饰首轮）：**
- fixture 归属：首轮 r17_flask 86/89 之外多出 F2-02／F2-06 两红、r17_core 多出 C1-02／C1-03／C1-05／C1-13 四红，根因为 fixture-server/server.conf 为 root 所有——render 时的 chmod 只有属主能做，nobody 跑探针得 EPERM（core 探针自报 "fixture server.conf reset failed: Operation not permitted"）。纠正：`chown -R nobody:nogroup fixture-server fixture-ca`＋server.conf 复位 1194 后重跑，flask 回 86/89（仅预期翻转）、core 回 46/46。**首轮多出的 6 红是调用环境问题，非产品回归。**
- 各探针的树 env 名不一：bq／r21／r22／r23 各读自有 `BQ_TREE`／`R21_TREE`／`R22_TREE`／`R23_TREE`（不是 R17_TREE），首轮未设故 `ModuleNotFoundError: No module named 'app'`；纠正后 bq 6/6、r21 6/6、r22 22/22、r23 全模式通过。
- r20／r25 须 root 跑：r20 的 S6（unshare 绑挂）与 r25（unshare＋ip）以 nobody 身份起不来（`unshare: write failed /proc/self/uid_map: Operation not permitted`）；r20 另踩 /tmp/r20 及 /tmp/r20/ptree 目录 770 nobody 致 userns 内遍历 EPERM——chmod 755 后重跑，r20 得预期 3 红翻转、r25 得 37/37。**首轮跑器里 r25 的 "ALL PASS" 未留日志、无计数佐证，以本次 root 重跑的 37/37 为准，首轮读数作废。**
- r23 的 R23_MODE=empty_secret 模式摘要行含被运行时脱敏的内容，两格本身（R2／R2b）均 PASS，计数以格为准。

**结论**：历史 165 条关闭项无一复发；全部红格均为钉死缺陷行为的预期翻转或本轮新探针的直接复现。

## §7 live-18 与补记的交叉核对

逐项核对 live-18（docs/live-verify-R18.md，119 行）与补记（docs/live-verify-R18-supplement.md，62 行）的 verdict 是否有树＋报告可佐证。机上证据（/root/r18/ 日志与 tarball）本轮在沙箱内无法直接读取，凡只赖机上证据的项记「live 证据，本轮沙箱未独立复验」；树侧可核的项本轮逐项核过。

### §7.1 树侧可核项——全部佐证

- **克隆完整性（live-18 §0）**：本地树 git HEAD `b395ef37985a3cb2873cd448f2221e378f978098` 与 live-18 所记克隆 HEAD 逐字一致。tracked 文件数逐项一致：panel 5、core 6、agent 4、egress 5、systemd 5、cloudflare 4、docs 45（磁盘 docs 49＝45 tracked＋本轮新增 4 篇报告；磁盘多出的 `__pycache__`／`data/`／`static/`／`templates/` 为探针产物或目录，非文件数差异）。
- **关键文件哈希（live-18 §0）**：7 个文件 sha256 前 8 位与本地树逐项一致——install.sh `3f050f03`、sk5_manager.py `e209084f`、policy-routing.sh `fbfb29a4`、app.py `40868bbf`、index.js `f4318097`、agent.py `f303af82`、openvpn_manager.py `3b5d7dfe`。即 live-18 克隆安装的代码与本轮审计的代码（除未提交的 R26 三文件 README／DELIVERY／verify.sh 外）字节一致，live 结论的审计对象与本轮一致。
- **S4 端口锁定 500（live-18 §6）**：不带 allow_port_change 的 TCP 443 切换报 500（"entry port is fixed at creation"）与树内 create_server 的 P01 锁定逻辑一致，非 bug——live-18 的定性正确。
- **headline-9 毒树机制（补记 §1）**：毒树 panel/data/ 未被拷入、毒 init_pki 未执行的机上三证，其机制侧由本轮 §3.1 佐证——install.sh 为固定清单复制，panel/ 走 staging 且排除 data/，毒 panel.db／agent_queue.json 无复制路径；R8-BUG-1 的同族写点在本轮探针重跑中未复发（§6）。
- **O-R18-1 的事实（live-18 §4）**：SOCKS 问候／ASSOCIATE／txid 一致／an=0／dante 日志 39→29 字节的机上事实，与树内代码一致——`_parse_socks_udp_dns_reply` 确以 ancount>=1 为通过（sk5_manager.py:481-508），且中继本身不参与答案生成。**事实佐证；但 live-18 的裁定（「非产品缺陷」）本轮已推翻**：判据测的是 resolver 答案库而非中继，单发单名单 resolver 致误报，见 §8 R27-P2-1。live-18 自己的建议（第二查询名／第二 resolver fallback）即为修法方向。

### §7.2 只赖机上证据的项——未独立复验，但报告自带可核细节

- S0 全新安装一次成功（0 ERROR、CA serial `2B9F892B…`、四服务 active）、S1 直连、S2 SK5 双栈（sing-box／dante 双证）、S3 杀 dante 全断 3 秒恢复、S4 五次首连全 0.11 秒、BUG-9 第二十次复验、headline-1 delta 恰 10、headline-3 并发 delta 恰 1、headline-5 诚实＋零重起、headline-6 verify.sh 双态 18/0/4 与 23/0/0、headline-7 前端 158 项 0 低于 4.5、补记 headline-9 行级比对（audit 119→120 仅增安装器登录 1 行）与 POST /api/cmd 往返（202、2 秒内 done）：以上均有具体数字、PID、时间戳、机上日志路径与 tarball sha（`2746aa56…`）可供后轮抽查；本轮沙箱未重跑其中任何一项，**记为 live 证据、未独立复验，不冒充为本轮复核**。
- live-18 自承的局限均已如实记录：§8.1 首轮 alt10.py 输出因 tssh 断管丢失（以重跑 alt10b.log 为正式证据）；§10 headline-9 与 §11.2 的 POST /api/cmd 本轮未执行（后由补记闭合）；§9 favicon 404 与 live-10–17 同款记观察。无隐瞒式断言。
- **本轮新发现与 live-18 的关系**：R27-P1-1（verify.sh 强制路径）未被 live-18 覆盖——live-18 的 headline-6 只跑了默认双态（开态 SKIP 4 格、关态全跑），未设 `VERIFY_ALLOW_OVERWRITE_SK5=1` 跑强制路径，故该缺口不在其 verdict 范围内，不构成 live-18 的漏判；R27-P2-2（Worker 悬空队列）需节点离线 ≥7 天才触发，live-18 无此场景，亦不在其范围内。

### §7.3 交叉核对结论

- live-18 与补记的 verdict（S0–S4 全过、headline 六项全过、新 bug 0 个）在树侧可核部分全部佐证，机上证据部分自带可核细节、无一处与树内代码矛盾。
- 唯一推翻：O-R18-1 的裁定由「观察、非产品缺陷」升级为 R27-P2-1（见 §8）；事实本身无出入。
- Cloudflare Worker 真实部署（P0-1）live-18 亦未覆盖，本轮仍未验（wrangler.toml:32-33 的 KV id 仍为占位符，本轮已核）。

## §8 差集（新发现）

### R27-P1-1（P1）——verify.sh 强制路径只恢复 SK5 凭据文件、不恢复运行链；下一健康检查档把分歧洗成 healthy，VPN 流量静默直连

- **机制**：触发条件两条——面板已启用真实 SK5，且操作员显式设 `VERIFY_ALLOW_OVERWRITE_SK5=1` 跑 verify.sh（文档现称该路径「备份并恢复，无须重填」，见 §1.2）。切换测试经 API 走两步：enable（stub 凭据渲染 SK5 配置＋起 sing-box＋上策略）→ disable（`disable()` 渲染 direct 配置、重启 sing-box、清策略、落盘 enabled=false）。退出时 cleanup（verify.sh:103-108）只 `cp` 恢复两个文件（备份的 sk5.json：enabled=true＋真实商家凭据；备份的 sing-box.json：bought-sk5 配置）。**运行中的 sing-box 仍加载 direct 配置**，面板没有任何文件↔运行态重同步路径（get_status／check_health／agent 上报均不重渲染、不重启 sing-box；O-R25-5 健康检查永不重启 daemon，按设计）。
- **洗白链**：下一档健康检查（≤60 秒）读 enabled=true → `_policy_active()` 为 False → `_repair_policy()` 重装 rule＋黑洞＋tun1 路由——tun1 是活的（direct 模式 sing-box 照常持有 tun1，LOWER_UP），路由照装；`_policy_active()` 是纯路由谓词，不看运行配置 → True；随后 `test_sk5()` 的 tcp_ok 经 `curl --socks5-hostname` 直连商家 SOCKS 拨测，完全绕过 sing-box 与策略路由 → True；`healthy = bool(tcp_ok)`（sk5_manager.py:1358-1363）→ **healthy=true、action="policy_repaired"**。此后每档复判 healthy，状态稳定持续，直到人工重启用面板或 sing-box 重启（重启会加载已恢复的 SK5 文件，链路才真恢复）。
- **用户影响**：启用态下 VPN 用户流量实际走直连（ transit 机真实 IP 暴露），而面板报 healthy＋`policy_routing_active=true`＋`/api/status` 的 `via_sk5=true`（判据＝enabled＋policy，app.py:1502-1507）＋商家出口 IP（`current_egress_ip()` 亦为直连 SOCKS 拨测，sk5_manager.py:835-847）。正是 R13-BUG-1 的静默直连签名，但本轮是**自洽的假健康**，非 R13-BUG-1 的复发（不同触发：强制自检后文件恢复，而非 sing-box 死亡；R13 的黑洞层仍在——表 100 有黑洞兜底，但 tun1 路由 metric 0 优先，流量不落黑洞）。
- **证据**：新探针 `tests/r27_verify_forced_divergence.py` **7/7**（真实 sk5_manager 函数＋真实 policy-routing.sh repair／disable＋真实 curl 经 in-process SOCKS5 stub＋stub sing-box 记录 loaded config；D4 为本 finding 的直接复现，D5 对照证明 verdict 在真假两态下完全相同、无法鉴别分歧；D6 证明面板三输入全绿；D4 的 detail 里 udp_ok=False 是沙箱 UDP sendto EPERM 假象——healthy 只看 tcp_ok，结论不受影响）。
- **范围（机械推导，闭合）**：分歧的唯一制造者是 verify.sh cleanup 的文件级恢复（全仓搜 `sk5.json.bak`／`sing-box.json.bak` 引用：仅 verify.sh:103-113 两处恢复点＋:651-652 两处备份点）；分歧的唯一洗白者是 check_health 的 verdict（`healthy=tcp_ok`＋`_policy_active` 路由谓词，sk5_manager.py:1255-1432 全文已读）；同族手写文件恢复路径：无（install.sh 不写 sk5.json；do_restore 只读 verdict、不写文件；agent 不写 sk5.json）。
- **修法（二选一，缺一不可的语义）**：(a) verify.sh cleanup 改为经 API 恢复——备份文件恢复后，以备份中的 host/port 调 `POST /api/sk5` enabled=true（不带密码，面板保留已存密码语义），让 enable() 重渲染＋重启＋上策略，恢复的是运行链而非仅文件；或 (b) check_health 在 repair 后校验运行态与文件一致（例如比对 sing-box.json 磁盘哈希与 sing-box 启动时加载的配置——需新增 loaded-config 记录；或 repair 时若磁盘为 SK5 配置而 sing-box 进程启动早于文件恢复时间则重启 sing-box）。(a) 为首选：修触发点，不动健康检查 verdict 语义（tcp_ok-only 的健康判据另有 R6-P1-1 的存在理由，不宜为这一案改判据）。另：cleanup 的 `cp … || true` 静默失败应改为大声失败（恢复失败即报 FAIL，不静默留分歧）。

### R27-P2-1（P2）——/api/sk5/test 的 UDP 判据测的是 resolver 答案库而非中继，单发单名单 resolver 致误报（O-R18-1 立案）

- **机制**：`_socks5_udp_associate_dns`（sk5_manager.py:510-577）发一个 DNS A 查询（固定名 `example.com`、固定 resolver `1.1.1.1:53`），`_parse_socks_udp_dns_reply`（:481-508）以 `txid 匹配且 ancount >= 1` 为通过；全程单发单收（sendto=1、recvfrom=1），无重试、无第二查询名、无第二 resolver。txid 匹配的合法 DNS 回复到达即已证明 UDP 中继双向通畅——ancount 是 resolver 答案库的属性，不是中继的属性；上游对该固定名返回空 NOERROR（live-18 实证）或单包丢失时，探针谎称「SK5 不支持 UDP」。
- **证据**：live-18 §4（中继全程通畅、txid 一致、dante 日志同证；同 resolver 对 cloudflare.com／google.com 有答案，8.8.8.8 对 example.com 有答案）；本轮探针 `tests/r27_udp_probe_verdict.py` **3/3**（U1 ancount=0→False、U2 ancount=1→True、U3 单发单名单 resolver 源码计数）。
- **用户影响**：用户被误导以为所购 SK5 不支持 UDP，可能错切 TCP-only 模式或向商家错报；health.json 的 detail 文案亦带 udp_ok=False。但 check_health 的 healthy 只看 tcp_ok，不触发 fail-over／kill-switch 误判，故 P2 非 P1。
- **范围（机械推导，闭合）**：判据唯一写点 `_parse_socks_udp_dns_reply:507`；调用方两处——`test_sk5()`（:821-824，native 路径）与 `_udp_probe_via_uot_singbox`（:653，经同一函数，UoT 路径同症）；两处同修。Worker 面无自有 UDP 探针（调面板 test_sk5），无第三处。
- **修法**：(1) 判据改为 round-trip 证明——txid 匹配的合法 DNS 回复（任意 rcode，含 ancount=0 的 NOERROR）即判 udp_ok=true，答案内容只记入 note；(2) 空回复或超时时重试一次，换第二查询名（如 cloudflare.com）与第二 resolver（如 8.8.8.8）再判；(3) 超时重试一次（单包丢失不判死）。(1) 为核心，(2)(3) 为纵深。

### R27-P2-2（P2）——Worker queue:/sent: 无 TTL 而 cmd: 7 天过期，悬空 id 在下轮 poll 被静默摘掉、零痕迹

- **机制**：`cmd:<id>` 记录写时带 `expirationTtl: CMD_TTL_S`（7 天，index.js:81＋7 处写点全带）；`queue:<node>`／`sent:<node>` 列表的三处写点（poll 条件式清空、revoke 清空、sweep 合并）均不带 expirationTtl，永不过期。sweep（`_sweepWorkerCmds`）只遍历活的 `cmd:*` 记录，悬空 id（列表里有、记录已过期／已删）对其不可见。下一轮 poll：下发循环 `if (!cmd) continue`（:846）跳过悬空 id——而 `takenIds` 含该 id，条件式清空随即把它从队列摘掉；sent 侧同理（:825 `if (!cmd...) continue` 使条目进不了 stillSent）。**无 failed 标记、无审计行（Worker 本无审计存储）、无 console.warn**——命令就这么没了。
- **触发**：节点离线 ≥7 天且有待下发／已下发未回执的命令（agent 活着时 poll 每 5 秒即下发，悬空只可能来自长离线）。后果 fail-safe（命令永不执行），缺的是可观测性：面板 cmd_get 回 404「命令不存在」，操作员无法区分「过期蒸发」与「从未存在」——与 R21-P2-1 的 404 误报同族（Flask 侧），是其 Worker 侧表亲。
- **证据**：新探针 `tests/r27_worker_dangling_queue.mjs` **5/5**（mock KV：Q1 队列悬空 id 被静默摘掉、Q2 零 warn、Q3 cmd_get 404、Q4 sent 悬空条目同症、Q5 源码计数 queue/sent 写点 3＋3 全无 TTL、cmd 写点 7 全带 TTL）。
- **范围（机械推导，闭合）**：TTL 不对称的全集——`kvPutJson` 写点枚举：queue: 3 处、sent: 3 处（均无 TTL）、cmd: 7 处（均带 CMD_TTL_S）；悬空摘除点两处（poll 下发循环＋sent 超时循环）。Flask 侧无同症（agent_queue.json 永不过期）。
- **修法**：(a) poll 下发／超时循环遇悬空 id 时 `console.warn` 点名 id（Worker 唯一的诚实信号通道，R18-P2-2 同款）；(b) 纵深：queue:/sent: 写时同带 `expirationTtl: CMD_TTL_S`，使整组节点队列状态同生共死——7 天无 poll 则整列过期，不留悬空指针（每次 poll 重写即刷新 TTL，活节点不受影响）。

## §9 未验与观察

### O-R27-1（观察，不立案）：新版重打时 DELIVERY §9 与卷首台账须刷新

- DELIVERY §9 包内清单（78 文件、审计 25 篇、live 17 份）与卷首「历史台账 163 条」「终审 AUDIT-R25」均为 1.0 发布包的真实快照（包未重打），当前不算漂移；但新版重打时必须按实测刷新（审计 25→27 篇、live 17→18 份＋补记、台账 163→168（165＋R27 新 3）、终审 R25→R27）。本轮不为此立案，列为发版前检查项。

### O-R27-2（观察，不立案）：agent 侧无命令去重，重投即重执行（已文档化、危害有界）

- `run_once` 对 poll 回执逐条执行，无 executed-id 去重；回执丢失→面板 120 秒后重投（SENT_MAX_RETRIES=3）→agent 重执行。security.md:12 已诚实记录（「非幂等命令重投时可能重复执行，agent 侧应做幂等防护」）。危害有界：create_user 二次执行报已存在（失败回执，非重复建用户）；init_pki 二次执行是同一已授权的 CA 重建（第一次已使全部证书作废，第二次无新增用户损害）；其余动作为幂等。不立案。

### O-R27-3（观察，不立案）：OVPN_PORT 前导零大声失败，不断言

- `OVPN_PORT=0117` 过 bash 的 `-ge` 检查（八进制 79 有效），Python 渲染为 `port 117`，随后 `grep "^port 0117"` 校验 die——大声失败，无静默错配；且失败在 PKI 之后、ufw 之前，重跑安全（幂等）。建议：在 :166-169 校验处归一化为 canonical 十进制，使报错更早更直。不立案。

### P0-1（站立未验）：Cloudflare Worker 真实部署

- 本轮仍无真实部署可验，不冒充。Worker 面只跑 mock-KV 探针。wrangler.toml KV id 仍为占位符（:32 `REPLACE_WITH_KV_NAMESPACE_ID`、:33 `REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`，本轮已核）。

### arm64 真机安装／SK5 端口 1001 vs 9000

- 均未变：无 arm64 机，仍未验；端口用户仍未确认，面板默认 1001。

## §10 审计方法与证据

- 探针一律在 /tmp 树副本＋venv＋nobody 身份下跑（Flask 类），env 名用 OPEN 前缀（`OPENVPN_CA_DIR`／`OPENVPN_SERVER_DIR`）＋`OVPN_SK5_CONFIG_DIR`；Worker 类 `node tests/*.mjs`。/etc/openvpn-sk5-panel/ 每次跑后复核为空（终态复核：空）。
- 沙箱 UDP/TUN EPERM 为环境假象，不作产品结论；数据面结论属 live 轮。
- 本轮新探针：`tests/r27_verify_forced_divergence.py`（7/7）、`tests/r27_udp_probe_verdict.py`（3/3）、`tests/r27_worker_dangling_queue.mjs`（5/5）。
- **复跑调用口径教训（后轮照此跑，见 §6）**：① fixture-server／fixture-ca 须属 nobody 所有（render 时 chmod 只有属主能做，world-writable 不够）；② 各探针的树 env 名不一（BQ_TREE／R21_TREE／R22_TREE／R23_TREE／R17_TREE），须按探针头读名设值；③ r20／r25 须 root 跑（unshare 绑挂／ip 操作），且 /tmp/r20 整条路径须对 userns 内可遍历（770 目录会致 EPERM）；④ 探针读数以带计数的终态输出为准，无日志的中间读数作废。
- 门禁串行跑（harness 非并发安全）；变异 11 棵逐棵串行，日志 /tmp/r27/gate-m-*.log。
- 本轮未提交、未推送任何改动；报告与三枚新探针为未跟踪文件（见 §0）。

# AUDIT-R34 — 全量全局回头看（blast-radius FMEA）

- **轮次**：R34（R33 修复后回头看）
- **日期**：2026-11-13
- **方法**：blast-radius FMEA——逐组件枚举失效模式，判定每个失效是就地收敛（大声、局部、可恢复）还是扩散（静默、跨组件、状态损坏、用户可见中断）。凡扩散半径大于文档宣称者立案。
- **Verdict**：**可交付（差集 ∅）**——R25 之后首个可交付轮。R33 与 R32 修复均以行为实证闭合；FMEA 45 个失效模式全部收敛；门禁 29/29、§7 变异 11/11 恰红；探针套件全量重跑无回归、无新红格。台账 175 条，0 新、0 复发。

## §0 审计基线（被审树状态）

- git main @ b395ef3 "Initial commit: OpenVPN transit panel + SK5 egress (R25 deliverable, live-17 verified)"，加未提交工作树改动：README.md、cloudflare/README.md、cloudflare/src/index.js、docs/DELIVERY.md、docs/security.md、egress/sk5_manager.py、panel/README.md、panel/app.py、panel/templates/index.html、verify.sh（修改）；docs/audit/AUDIT-R26.md … AUDIT-R33.md、docs/live-verify-R18.md、docs/live-verify-R18-supplement.md、tests/r27_udp_probe_verdict.py、tests/r27_verify_forced_divergence.py、tests/r27_worker_dangling_queue.mjs、tests/r29_flask_toggle_bool.py、tests/r29_worker_toggle_bool.mjs、tests/r31_bcrypt72.py、tests/r31_ctype.mjs、tests/r31_ctype.py、tests/r31_edge.mjs、tests/r31_edge.py、tests/r32_enable_wait_window.py（新增）。
- 本轮包含的修复：R26 文档、R27（verify.sh 强制路径 API 优先恢复、UDP verdict、Worker 队列 TTL）、R28 文档、R29 toggle 强制、R30 token 扫描器、R31（Worker 信封守卫、bcrypt 72 字节上限）、R32（enable deadline 循环）、R33（六处 72 字节规则同步＋前端 TextEncoder 预拦）。
- 台账基线：175 条（171 已修、2 部分、1 未验 P0-1 Cloudflare 真实部署）。

## §1 R33 修复闭合验证（行为实证）

- **R33-P2-1 闭合**：`tests/r31_bcrypt72.py` **10/10**（本轮亲手重跑，新鲜树副本＋新鲜 data 目录＋nobody 身份；B1–B4 服务端格＋F1–F4 前端格）。六处用户侧位置逐处核对均已同步“UTF-8 不超过 72 字节”：docs/security.md:11、panel/templates/index.html:309（帮助文案）、:1025（校验注释）、:1041（前端预拦 `new TextEncoder().encode(newPw).length > 72`，文案与服务端 400 一字不差，位于 API 调用之前）、panel/README.md:31（API 表行）与 :102、README.md:273。F1–F3 为行为格（从 index.html 原样抽取校验块在 Node 里真跑：74 字节多字节拒、72 字节多字节放行、73 字节 ASCII 拒）；F4 为内容钉死格。未加 maxlength（按字符计，CJK 下会错），与 R33 修法一致。
- **R32 修复闭合**：`tests/r32_enable_wait_window.py` **8/8**（本轮亲手重跑）。
- **R31 修复闭合**：Worker edge **22/22**、ctype **7/7**；Flask edge **21/21**、ctype **6/6**（本轮亲手重跑）。
- /etc/openvpn-sk5-panel/ 核查为空，0 泄漏。

## §2 Blast-radius FMEA（逐组件失效模式表）

判定口径：**收敛**＝失效大声、局部、可恢复、无静默扩散；**扩散**＝静默、跨组件、状态损坏或用户可见中断超出文档宣称。全部 11 个组件、45 个失效模式逐项核对如下；无一扩散。

### 2.1 Flask 面板（panel/app.py）

| 失效模式 | 半径 | 证据 |
|---|---|---|
| 进程崩溃／被杀 | 收敛 | systemd `Restart=on-failure`（RestartSec 5）；队列与数据库落盘，重启后恢复；会话由 secret.key 签名，重启不失效 |
| 磁盘满：`_save_queue` 写失败 | 收敛 | tmp＋`os.replace` 原子写，失败抛错→路由 500 大声，旧队列完好（BN/BQ 探针 6/6＋6/6） |
| 磁盘满：审计写失败 | 收敛 | `_audit` 全吞异常（“审计失败不阻塞业务”），只丢审计行，不丢业务状态 |
| 磁盘满：限流记账写失败 | 收敛 | `_record_login_failure` 全吞异常（R9-P2-2 已裁定）：本次失败未计入窗口，`_login_locked_until` 只读已落盘行，无行即无锁——锁不住时不谎称已锁 |
| 队列文件整文件损坏／不可读 | 收敛 | BN/BQ：隔离出 `.corrupt` 备份＋审计行 `queue_corrupt_quarantined`＋“不可知”计数，探针 6/6＋6/6 |
| secret.key 为空 | 收敛 | R23 模式格：伪造空钥会话 401、真实登录 loud 500（fail-closed 砖掉），探针重跑通过 |
| 未捕获异常进路由 | 收敛 | Flask 500 大声；`change_password` 的 bcrypt ValueError 已兜底 400（R31-P2-2 修复，探针 6/6） |

### 2.2 Cloudflare Worker（cloudflare/src/index.js）

| 失效模式 | 半径 | 证据 |
|---|---|---|
| enqueue 读→push→写回竞态（并发入队） | 收敛 | `_sweepWorkerCmds` 认领孤儿 queued 记录并重入队（`sweep: orphan queued cmd … re-enqueued`），且 sweep 写回为 merge 式（重读 fresh 再并集）；poll 的条件式清空只摘已取走 id。R18-P2-1 两半均已闭合（BI 15/15＋18/18，BH 20/20） |
| poll 窗口内入队 | 收敛 | 条件式清空重读队列再 filter（R18-P2-1 修复，注释逐行载明机制）；R27 悬空队列探针 5/5 |
| KV 记录畸形／sent_at 不可解析 | 收敛 | sweep 只标 failed＋审计（R18-P2-2 修复，BI 18/18）；`sent_at` 非数值不超时（`toMs` fail-closed） |
| 登录锁账记录损坏（数组／非对象） | 收敛 | `kvLoginFailRecord` 重置＋warn（BR 11/11）；字段级损坏仍 loud 500（已裁定） |
| 请求体畸形／非 JSON Content-Type | 收敛 | 信封守卫统一 400（R31-P2-1 修复，Worker edge 22/22＋ctype 7/7） |
| 整数浮点 `1.0` | 收敛 | raw 文本 token 扫描器（R30 修复，本轮重跑 Worker 6 格＋Flask 3 格＋save-port 3/3 全 400） |

### 2.3 Agent（agent/agent.py）

| 失效模式 | 半径 | 证据 |
|---|---|---|
| 进程崩溃／被杀 | 收敛 | `ovpn-agent.service` Restart=on-failure（RestartSec 5）；面板 `stale=true`（age＞60s）诚实展示；命令留 queued，重起后继续 poll |
| 面板不可达 | 收敛 | poll 失败退避 5s→60s 上限，成功即复位；不丢本地状态 |
| 面板 URL 被冒名／降级重定向 | 收敛 | `panel_url` 逐字认领（`agent_poll_panel_mismatch` 审计）＋`_NoDowngradeRedirectHandler`（token 绝不去明文地址）；TOFU 证书钉死 |
| 并发 poll 重复下发 | 收敛（已裁定） | sent 副本按 id 去重；agent 无 executed-id 去重（O-R27-2，security.md:12 已明文记载“非幂等命令重投时可能重复执行”，不重立） |

### 2.4 sing-box 出口（egress/sk5_manager.py）

| 失效模式 | 半径 | 证据 |
|---|---|---|
| sing-box 死 | 收敛 | 黑洞兜底（BM 22/22 真 netns）＋systemd 5 次／120s 重起＋健康检查自愈；面板诚实报 `blackholed_kill_switch`，流量不泄漏 |
| SK5 商户中断 | 收敛 | TCP/UDP 探针双失败→`blackholed_kill_switch`（fail-closed）；fail-open 时才 `failed_over_to_direct`，且 disable 失败时记 `failover_failed`（R6-P2-1） |
| DNS 解析器失效 | 收敛 | UDP 探针双层级（example.com/1.1.1.1 → cloudflare.com/8.8.8.8）＋往返证明 verdict（R27-P2-1，探针 6/6） |
| enable 等待窗口 | 收敛 | deadline 循环查 0.0…5.0s（R32 修复，探针 8/8）；慢启动大声 500、无占位符、无状态污染、可重试 |
| 存量 sk5.json 损坏 | 收敛 | `_validate_stored` 严格检查＋ValueError 点名文件字段（BK 8/8）；boot 时损坏大声失败（BP 14/14） |

### 2.5 OpenVPN 守护进程（core/openvpn_manager.py）

| 失效模式 | 半径 | 证据 |
|---|---|---|
| daemon 死 | 收敛（观察 O-R34-1） | 无任何组件看守 daemon、健康检查不覆盖它；`server_status()` 诚实报 `running=false`＋“openvpn-server@server is not running”，面板与 agent 心跳如实展示；恢复靠面板手动 restart。文档未宣称 daemon 自愈，故不立案 |
| 吊销后 restart 失败 | 收敛（观察 O-R34-2） | 吊销本身已落 CRL（`revoke_user` 先行），restart 失败则动作大声报错；已连接用户在 daemon 重起前仍在线（CRL 只在启动时读，docstring 已明示）；恢复为面板手动 restart；重试吊销会报“already revoked”（CRL 层面属实） |
| server.conf 损坏 | 收敛 | `_parse_existing_server_conf` 显式报损坏，不再把损坏当“旧端口 None”冻结入口端口（R12-P1-2） |
| CA 重建误触 | 收敛 | agent 侧 force＋confirm 双重门（P2-9）；R17-P1-1 poll 守卫禁非入队命令下发（BG 22/22＋BH 20/20） |

### 2.6 策略路由（egress/policy-routing.sh）

| 失效模式 | 半径 | 证据 |
|---|---|---|
| 表 100 为空 | 收敛 | 黑洞先装、永无空表窗口（BM K1/K2）；tun1 死即落黑洞不落回主表 |
| repair 动词遇死 tun1 | 收敛 | 只装黑洞＋rule，tun1 路由只在设备 LOWER_UP 时装（BO 18/18）；不建设备、不装路由，下一档再补 |
| boot 恢复 | 收敛 | `do_restore` 走 REPAIR_MODE＋`Wants=`（BP 14/14）；sk5.json 损坏大声失败、策略不动 |

### 2.7 健康检查（60s 定时器）

| 失效模式 | 半径 | 证据 |
|---|---|---|
| policy 缺失 | 收敛 | 每档一次 `_repair_policy()` 再重判；修好且探针过→`policy_repaired`，修好但链死→`blackholed_kill_switch`，修失败才 `policy_missing` 且 detail 写清流量去向（BS 9/9、R25 37/37） |
| repair 风暴 | 收敛 | 60s 定时器＋flock 串行＋幂等脚本，修不好不循环重起 daemon |
| 健康检查进程本身死 | 收敛 | 下一档 timer 仍触发；`health.json` 留上档结果，面板不谎称新鲜（stale 标记） |

### 2.8 队列（双面）

| 失效模式 | 半径 | 证据 |
|---|---|---|
| 命令 sent 态 120s 无回执 | 收敛 | 自动打回 queued，最多 3 次，超了标 failed（Flask/Worker 上限一致）；Worker 非幂等首超时即 failed（已裁定不对称，security.md:12） |
| 节点吊销 | 收敛 | queued 与 sent 一并标失败 |
| 队列文件损坏（Flask） | 收敛 | 见 2.1 |

### 2.9 CA/PKI

| 失效模式 | 半径 | 证据 |
|---|---|---|
| 证书过期 | 收敛 | `index.txt` 序列号识别＋过期按 DER 时间判（erin V-but-expired 格，R17 Core 46/46） |
| 吊销 | 收敛 | 见 2.5 |

### 2.10 安装／校验脚本（install.sh / verify.sh / verify-integration.sh）

| 失效模式 | 半径 | 证据 |
|---|---|---|
| 毒树重跑（R8-BUG-1） | 收敛 | staging 复制排除 panel/data/（install.sh:474-505），live-18 补记毒树重跑行级一致 |
| 误装到 FLMX 部署 | 收敛 | 目标解析命中 /root/flmx-panel 即退出（install.sh:111-117） |
| 全新安装卸 ufw（R8-BUG-2） | 收敛 | `iptables-persistent` 只在未装 ufw 时装（AN 修复，live-9/10 复验） |
| verify.sh 强制路径恢复 | 收敛 | API 优先恢复（R27-P1-1 修复，探针 8/8）；恢复失败 loud FAIL、强制非零退出 |
| 门禁 harness 并发 | 收敛 | 固定 TESTDIR＋8443，须串行（已在 DELIVERY §9 注明；本轮串行跑 29/29） |

### 2.11 前端（panel/templates/index.html）

| 失效模式 | 半径 | 证据 |
|---|---|---|
| 面板 API 非 JSON 响应 | 收敛 | `api()` 兜底 `{ok:false, error:"响应不是 JSON"}`，错误经 showMsg 展示 |
| 改密长口令 | 收敛 | 前端 TextEncoder 预拦＋服务端 400，文案一致（R33 修复，探针 10/10） |
| 会话过期 | 收敛 | 401 后回登录页；改密后 session_version＋1 作废全部旧会话 |

**FMEA 结论：45 个失效模式全部收敛，无一扩散。R18-P2-1 的入队侧 RMW 竞态曾是本轮重点怀疑对象——核查结论：sweep 的孤儿重入队（`_sweepWorkerCmds` 的 `queued && !queueIds.has(id)` 分支）＋merge 式写回已将其闭合，不是残留缺口。**

## §3 功能链全量核对（doc 骨架）

以 README.md＋docs/DELIVERY.md＋docs/security.md＋cloudflare/server-mode.md 为骨架，逐项核对行为（代码面＋探针实证；数据面属 live 轮）：

- **UDP 1194 主／TCP 443 备**：`render_server_conf` 默认 `proto="udp"`（1194）、tcp 默认 443；入口端口创建时严查占用、创建后永不换口（P01，live-18 S4 实证：无 `allow_port_change` 改口回 500）。
- **用户管理**：建用户／吊销／.ovpn 下载；吊销后 restart 使 CRL 生效（已连接用户 CRL 刷新本身不踢，docstring 明示，见 O-R34-2）；用户名判重、`validate_username`。
- **SK5 enable/disable**：enable 等 LIVE tun1（deadline 循环 0.0…5.0s，R32）、disable 刷直连＋清表 100；fail-open 单向；verify.sh 强制路径 API 优先恢复（R27，探针 8/8）。
- **断网保护**：README:169“绝不会悄悄改走直连”——黑洞兜底（BM 22/22 真 netns）＋live 多轮杀 sing-box 实证，全断无回落、自动恢复。
- **60s 健康检查＋自愈**：`check_health` 每档一次 repair 再重判，verdict 诚实（BS 9/9、R25 37/37）；repair 风暴有界（flock＋定时器）。
- **队列＋agent poll**：5s 轮询、退避 5s→60s、120s 重投上限 3、节点吊销一并标失败；R17-P1-1 poll 守卫（BG 22/22＋BH 20/20）；Worker 孤儿重入队＋条件式清空（R18-P2-1 闭合，见 §2.2）。
- **登录限流**：同 IP 5 分钟 5 次失败锁 15 分钟，429＋Retry-After；计数进 SQLite，重启不丢；磁盘满时记账失败不阻塞 verdict（R9-P2-2）。
- **bcrypt 密码处理**：登录超长密码 401（`_check_password` 捕 ValueError）；改密 UTF-8＞72 即 400＋前端预拦（R31-P2-2＋R33-P2-1，探针 10/10）；改密后 session_version＋1 作废全部旧会话。
- **CA 重建**：force＋confirm 双重门（P2-9）；存量证书按序列号识别，index.txt 文件名列恒为字面 `unknown`。
- **凭据红线**：`get_status()` 用 `_redact(cfg)`，SK5 明文密码永不出 get_status／日志／报错（门禁格“回执 JSON 里无节点 token”通过）；token 只存 SHA-256。
- **Cloudflare 模式**：未验（P0-1），文档各处已标未验；`wrangler.toml` KV id 仍为占位符。
- 绝对宣称抽查（README:169 断网保护、README:266/270 凭据永不出现、security.md:16 token 绝不降级重定向、DELIVERY:99 poll 恒 401）均与代码／探针一致，无一失实。

## §4 门禁

- **干净树**：`bash verify-integration.sh` → **PASS=29 FAIL=0 SKIP=0**（本轮亲手重跑，串行，树静止）。
- **§7 变异**：`tests/build-mutants.py` 造 11 棵变异树，逐棵串行跑门禁，**11/11 恰红 28/1**，红格逐棵核对均为 §7 钉死格（“钉死哈希不一致：install.sh 与 agent/agent.py 的 sha256 逐键不等”）：m-dict-sb、m-dict-ts、m-dict-x-amd、m-dict-x-arm、m-dict-x-a、m-dict-x-b、m-dict-missing、m-dict-extra、m-const-sb、m-install-sb、m-char。
- `scripts/check-doc-consistency.sh` 在本树不存在；门禁即 verify-integration.sh（R27 已纠正旧简报名误）。

## §5 探针套件全量重跑

本轮亲手重跑（新鲜树副本 /tmp/r34/ptree；Flask 探针各用新鲜 data 目录＋nobody 身份；netns 探针 root 身份；/tmp/r33v/venv＋/tmp/r33f＋/tmp/fixture-server 沿用 R33 控制器重建物，未再被清）：

- R17 四套件：Flask **86/89**（仅 OBSERVED 钉死格 F4-02b/F4-13/F4-15 红）、Core **46/46**、Agent **33/33**、Worker **33/35**（仅 OBSERVED 钉死格 W5-05/W5-06a 红）。
- BK **8/8**、BM **22/22**、BO **18/18**、BP **14/14**、BQ **6/6**、BR **11/11**、BS **9/9**、BT **23/23**、R24 **25/25**、R25 **37/37**、R21 **6/6**、R22 Flask **22/22**＋Worker **12/12**、R23 Flask **13/13**＋4 模式格（empty_secret/db_garbage/db_empty/db_old_admin 全过）＋Worker **9/9**、R27 三探针 **8/8＋6/6＋5/5**、R29 toggle Flask **13/13**＋Worker **15/15**、R20 **7 格 3 红**（S1/S2/S6，缺陷钉死格预期翻转，与 R31–R33 同数）。
- R18：queue race **9 格 2 红**（RACE-02/RACE-05，缺陷钉死格）、malformed **13 格 4 红**（与 R30–R33 同数）；BH **20/20**、BI race **15/15**、BI malformed **18/18**；R19 非列表容器 **12/12**、.ovpn 下载 **8/8**。
- R31 五探针：Worker edge **22/22**、ctype **7/7**；Flask edge **21/21**、ctype **6/6**；bcrypt72 **10/10**（B1–B4＋F1–F4）。R32 **8/8**。
- 无回归、无新红格。

## §6 DELIVERY §9 与卷首台账核对

- **§9 与实包逐项一致**（本轮亲手核对）：`sha256sum -c releases/ovpn-release-1.0.tar.gz.sha256` → OK；tar 条目 92（78 文件＋14 目录）；`docs/audit/` 26 条命中＝25 份报告＋1 目录条目；`docs/live-verify` 17 份；9 个关键文件 sha256 前 12 位与 §9 表格逐项一致（install.sh `3f050f037e7a`、sk5_manager.py `e209084f0915`、policy-routing.sh `fbfb29a49164`、app.py `40868bbfd8b9`、index.js `f43180976393`、agent.py `f303af828555`、openvpn_manager.py `3b5d7dfe9ea1`、verify-integration.sh `2d110ff4ffec`、verify.sh `7867f557c6bb`）。
- **§9 与卷首是 1.0 快照**，须在发版时刷新，非本轮差集：审计 25→34 篇、live 17→18 份＋补记、台账 163→175、终审 R25→R34（见 O-R28-1 旧项，数字随本轮更新）。
- **P0-1 仍未验**：Cloudflare 真实部署（登录＋KV 占位）无进展，仍待用户决断。

## §7 差集（新发现）

**差集 ∅。本轮无新发现，0 复发。**

FMEA 逐项核对的 45 个失效模式全部收敛；功能链逐项核对无失实宣称；门禁 29/29、§7 变异 11/11 恰红；探针套件全量重跑无回归、无新红格；R33 与 R32 修复均以行为实证闭合。

## §8 审计环境事故

- **§5 初稿误记 BS 探针缺失**：本轮初稿写“`tests/bs_*.py` 不在树内”，实为审计员未列目录即下断言；列目录后发现 `tests/bs_verdict.py` 在位，随即重跑 **9/9** 并修正报告。教训：探针存在性须以目录清单为准，不凭记忆断言。非产品问题，报告已修正，无残留影响。
- /tmp 未被清：R33 控制器重建的 venv（/tmp/r33v/venv）与 fixture（/tmp/r33f＋/tmp/fixture-server）全程在位，未重建。
- /etc/openvpn-sk5-panel/ 全程为空，0 泄漏；fixture-server/server.conf 已复位 1194（R33 控制器重建时复位，本轮未动）。

## §9 未验与观察

- **O-R34-1（观察）**：OpenVPN 守护进程死亡无任何组件看守（健康检查只覆盖 SK5 链）；`server_status()` 与 agent 心跳诚实上报，恢复靠面板手动 restart。文档未宣称 daemon 自愈，不立案；live-19 可补一格 daemon 杀死后状态诚实性格。
- **O-R34-2（观察）**：吊销后 `restart_server()` 若失败，动作大声报错但 CRL 已落盘；daemon 仍跑旧 CRL，已连接的被吊销用户在手动 restart 前仍在线；重试吊销报“already revoked”（CRL 层面属实）。恢复路径为面板手动 restart。触发窗口窄（restart 本身失败）、失败大声，不立案。
- **O-R34-3（旧观察，仍在）**：agent 无 executed-id 去重（O-R27-2）；security.md:12 已明文记载，不重立。
- **O-R34-4（旧裁定，仍在）**：重投集不对称——Flask 重投非幂等命令（上限 3），Worker 首超时即标 failed；security.md:12 已记载，不重立。
- **O-R34-5（观察）**：时钟跳变行为未在文档中定性：时钟前跳使登录锁提前过期、sent 命令提前重投（均有 3 次上限兜底）；时钟后跳使锁更久、重投滞后。NTP 正常 discipline 下影响可忽略，不立案。
- **未验**：P0-1 Cloudflare 真实部署；P0-2/P0-3 同前；arm64 真机；IPRoyal 1001 vs 9000（用户未复）；数据面真机格属 live-19。

---

**台账**：175→**175**（171 已修、2 部分按设计、1 未验 P0-1、新 0、复发 0）。

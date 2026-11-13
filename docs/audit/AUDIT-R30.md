# AUDIT-R30 — 状态变迁推导全量审计（2026-11-13）

> 方法：state-transition derivation（与 R29 的双面行为一致性、R28 的零用户旅程、R27 的对抗操作员、R26 的 repo-consumer journey、R25 的 repair-path convergence 均不同）。把系统内每台状态机——命令队列（queued/sent/done/failed/timeout/requeue）、SK5 链（disabled/enabled/direct/blackholed/policy-missing）、登录锁、CA（init/rebuild/revoke）、节点、健康 verdict、安装/升级——逐台建模，核验每条变迁的触发、守卫、落点，查无守卫旁路、假定不可达状态的可达性、静默丢状态的变迁。另全量复核功能链（README／DELIVERY.md／security.md 逐项对行为）与 R29 修复的行为闭合。
> 审计树：`~/workspace/openvpn-sk5-panel/`，git main @ b395ef3（1.0 发布提交，与公开仓库一致）＋未提交工作区改动（R26 文档修复：README.md、docs/DELIVERY.md、verify.sh 头注释；R27 修复：verify.sh cleanup API 恢复、egress/sk5_manager.py UDP 判据、cloudflare/src/index.js 队列 TTL；R28 文档修复：README Cloudflare 节、cloudflare/README.md、DELIVERY §1.3／§5；R29 修复：cloudflare/src/index.js coerceToggleBool 严格开关判定）。
> 历史台账：R29 终点 170 条（已修 160、部分 2（按设计）、未验 1（P0-1 Cloudflare 真实部署）、新 1（R29-P2-1，本轮已验关闭））。本轮新增 1 条后台账 171 条（已修 160、部分 2、未验 1、新 1）。
> 夹具：/tmp/r30/ptree（本地工作树副本，含未提交修复）；fixture /tmp/r27（fixture-ca 含 ta.key、fixture-server server.conf port 1194 proto udp，属 nobody 所有——/tmp 本轮未被清空，R27/R29 的夹具仍在）；venv /tmp/r27/venv（Flask 3.1.3＋bcrypt）；系统 python3 无 flask（预期）。

## verdict：**不能交付：差集 1 条，P2×1（R30-P2-1），见 §8**

门禁 29/29；§7 变异 11/11 恰红 28/1；探针全套重跑见 §6（历史关闭项无一复发；全部红格均为缺陷钉死格的预期翻转）。Cloudflare Worker 真实部署仍 P0-1 未验。

## §0 审计基线与树状态

- 本地树：main @ b395ef3，`git status`：6 文件已修改未提交（README.md、cloudflare/README.md、cloudflare/src/index.js、docs/DELIVERY.md、egress/sk5_manager.py、verify.sh——R26 修复＋R27 修复＋R28 修复＋R29 修复）；未跟踪：docs/audit/AUDIT-R26.md、AUDIT-R27.md、AUDIT-R28.md、AUDIT-R29.md、docs/live-verify-R18.md、docs/live-verify-R18-supplement.md、docs/audit/AUDIT-R30.md（本轮）、tests/r27_verify_forced_divergence.py、tests/r27_udp_probe_verdict.py、tests/r27_worker_dangling_queue.mjs、tests/r29_flask_toggle_bool.py、tests/r29_worker_toggle_bool.mjs（R27／R29 新探针）。
- 公开仓库：https://github.com/iiiiiiiii7125-art/openvpn-sk5-panel（public，2026-11-13 用户令公开）。本轮审计的是本地工作树（含未提交修复），不是仓库 HEAD——仓库 HEAD 仍为 b395ef3，未含 R26／R27／R28／R29 修复；发新版前须提交并推送（见 §9 收尾）。
- 探针树：/tmp/r30/ptree（本轮新建的工作树副本）；fixture／venv 复用 /tmp/r27（未被清空，属主 nobody、server.conf 已为 1194 udp——本轮起跑前复核通过，无需重建）。
- /etc/openvpn-sk5-panel/：本轮跑前已存在（R27 轮 pre-create），跑前复核为空（0 泄漏起点）；另预建 /run/openvpn-sk5-panel（r27 探针 unshare 绑挂点，防静默写宿主）。

## §1 R29 修复闭合核验（行为实证，不认代码在场）

### §1.1 R29-P2-1（Worker toggle 布尔判定）——已关闭

- **判定全文已读**：Worker `coerceToggleBool`（cloudflare/src/index.js:1257-1263）只接受真布尔与 `Number.isInteger` 的 0/1，其余 400；`handleCompatSk5Toggle`（:1265-1296）：键在场 → 严格规整（400 在场）；键缺失时 fail-open 默认 False（无 `enabled` 回落），udp-over-tcp 回落 `enabled`（R12-P2-2 已裁定）且回落值同样过 `coerceToggleBool`（:1281）。旧的 `typeof` 回落＋终端 `: false` 已删除，全树零残留（grep `typeof b\[key\]`／`: false` 终端回落无命中）。
- **Flask 对照已读**：`_coerce_bool`（panel/app.py:1091-1105）只接受真布尔与 `isinstance(value, int)` 的 0/1；`_strict_bool`（:1106-1113）缺键取 default；`_toggle_value`（:1114-1123）键优先、回落 fallback、两者都缺 default——Worker 新逻辑与 Flask 逐分支同构（键在场先规整、回落值亦规整、缺键默认 False）。
- **探针重跑**：`tests/r29_worker_toggle_bool.mjs` **11/11 PASS**（T1–T8 修复后行为＋T9 udp-over-tcp `{enabled:true}` → 202 True，已裁定回落钉死）；`tests/r29_flask_toggle_bool.py` **10/10 PASS**（同上，T9 在场）。/etc 终态复核为空。
- **结论：R29-P2-1 已关闭**（行为＋源码双证）。但 §1.2 的边缘输入揭示同一谓词仍有残差，见 §8 **R30-P2-1**——不是 R29-P2-1 的复发（typeof 回落机制已死，R29 探针全绿），是新谓词的不同输入类。

### §1.2 边缘输入复核（本轮新增实证，触发 §8）

- 思路：`coerceToggleBool` 宣称与 Flask `_coerce_bool`「同口径」，但 JS 只有一个 number 类型——`Number.isInteger(1.0)` 为真，而 Python `isinstance(1.0, int)` 为假。JSON 字面量 `1.0` 是两面的分水岭，R29 两探针均未覆盖（grep `1\.0`／`float` 零命中）。
- 本轮双面实证（新写 /tmp/r30_edge*.mjs／.py，mock KV＋test_client，逐格对照）：
  - `{"fail_open": 1.0}`：Flask **400**；Worker **202**，经 `/api/cmd/<id>` 核验入队参数确为 `fail_open: true`。
  - `{"udp_over_tcp": 1.0}`：Flask **400**；Worker **202**。
  - `{"port": 1001.0}`（POST /api/sk5 保存）：Flask **400**；Worker **202**。
  - 对照 `1.5`：三输入双面均为 400（非整数浮点两面一致拒）。
- 结论：R29 修复闭合了 R29-P2-1 的 8 格输入，但谓词在整数浮点处仍分歧；详见 §8。

## §2 状态机推导（本轮方法：每台状态机逐变迁核验）

### §2.1 命令队列状态机（Flask 面，panel/app.py）

状态集：`queued → sent → done/failed`（终态 done/failed 无出边）。逐变迁核验（代码行号为本轮所读）：

| 变迁 | 触发／守卫 | 结论 |
|---|---|---|
| queued → sent | poll 下发，守卫 `status == "queued"`（:2618-2624，R17-P1-1） | ✓ 非 queued 一律不下发 |
| sent → done/failed | agent 回执，守卫 `status == "sent"`（:2686-2699），非 sent 回执 409＋审计 `agent_report_not_sent` | ✓ queued/done/failed 回执不翻状态 |
| sent → queued | 超时＞120s 且 retries ≤3（`_requeue_stale_sent` :720-765），`sent_at` 重置 None、重新入队 | ✓ 有界 |
| sent → failed | 超时且 retries＞3（同上）；或回执 ok=false；或吊销节点（:2423 一并标 failed） | ✓ |
| 任意非终态 → failed | 畸形隔离 `_fail_malformed_cmds`（:609-715）：缺字段／错型／sent_at 不可解析／非对象条目删除＋审计；done/failed 跳过不重复审计 | ✓ |
| queued/sent → failed（吊销） | `nodes_revoke`（:2396-2432）：先扫队列再删库行（R14-P2-1 顺序），queued 与 sent 一并标 failed，队列键弹出 | ✓ |
| —（无变迁） | done/failed 无任何出边：poll 守卫、回执守卫、重投守卫（仅 sent）、隔离守卫（跳过终态）四重确认 | ✓ 终态不可复活 |

- 补充：poll 内先隔离、再重投、再下发，顺序固定（:2606-2613）；队列清空 `state["queue"][node] = []` 在 `_QUEUE_LOCK` 内、入队同锁，无竞态窗口（Worker 面的条件式清空与此不同，见 §2.2）。

### §2.2 命令队列状态机（Worker 面，cloudflare/src/index.js）

| 变迁 | 触发／守卫 | 结论 |
|---|---|---|
| queued → sent | poll 下发，守卫 `status === "queued"`（:867-868，R17-P1-1） | ✓ |
| sent → done/failed | 回执，守卫 `status !== "sent"` → 409（:946-949） | ✓ |
| sent → queued | 超时＞120s 且重试未超 3 次，**但仅 SAFE_RETRY_ACTIONS**（:667-685：get_status／test_sk5／enable_sk5／disable_sk5／start／stop／restart_openvpn）；非幂等动作（init_pki／create_server／create_user／revoke_user／set_sk5／install_prereqs）首超时即标 failed | △ 与 Flask 面不对称——**已 adjudicated**：security.md:12 明文记载（Flask 全动作重投，Worker 非幂等不重发），R5 裁定＋R29 §2 已列为一致项；本轮复核 security.md:12 与 `SAFE_RETRY_ACTIONS`（:96-104）一致，不立案 |
| sent → failed | 超时且 retries＞3；或非安全动作首超时；或回执 ok=false | ✓ |
| 任意 → failed（畸形） | `_sweepWorkerCmds`（:708-795）：非对象／缺 status／未知 status／缺 node → 标 failed＋隔离；孤儿 queued 重新入队（R18-P2-1 自愈）；孤儿 sent 按超时规则处理（未超时恢复 sent 副本） | ✓ |
| 悬空 id | 队列／sent 引用记录已 TTL 过期：poll 两循环 `console.warn` 点名 id 后摘掉（R27-P2-2 修法）；queue:/sent: 7 处写点全带 TTL（R28 已重数 7＋8） | ✓ R27-P2-2 闭合 |
| done/failed | 无出边（下发／回执／重投／sweep 四守卫同 Flask） | ✓ 终态不可复活 |

- 补充：`_handleSentTimeout` 的 `toMs`（:631）把非数值 sent_at 按 0 计——已超时方向（fail-closed），R18-P2-2 的 NaN 缺口已堵；sweep 写回用「重读＋并集」，不覆盖 poll 窗口内新入队 id（R18-P2-1）。

### §2.3 SK5 链状态机（egress/sk5_manager.py）

| 变迁 | 触发／守卫 | 结论 |
|---|---|---|
| disabled → enabled | `enable()`（:1183-1247）全有或全无：先渲染→清死占位→起 sing-box→等 LIVE tun1（LOWER_UP，5s）→repair 动词上策略→`_policy_active()` 复验→**通过后才持久化 enabled=true**；任一步失败即 raise、enabled 仍 False、无策略变更 | ✓ R24-P2-1／BT 闭合 |
| enabled → disabled | `disable()`（:1248-1308）：先渲染 direct 配置→清策略→停 daemon→落盘 enabled=False→**重启 best-effort**，失败只进 `singbox_restart_error` 不 500 | ✓ R4-P1-1 |
| enabled → enabled（同值保存） | `set_sk5()` still-enabled 分支（:840-866）：链路影响字段变了 → 全 `enable()`；没变 → 先 `_chain_effective()`，有效则纯保存，无效且 daemon 活 → 只重装策略、不重启 daemon（R27-P1-1 顺序陷阱的根因，verify.sh cleanup 已改 API 先行，见 §1 与 R28） | ✓ 行为与 R27 审计一致 |
| 健康 verdict | `check_health()`（:1336-1510）：enabled=false → `chain_disabled`（healthy=True）；policy 缺失 → 一次 `_repair_policy()`（repair 动词，永不建 tun1）→ 按修复自身契约 `_repair_holding()`（rule＋黑洞）重判，不按 `_policy_active()`（R15-BUG-1）；healthy → `policy_repaired`／`none`；不健康＋fail_open → `disable()` → `failed_over_to_direct`／`failover_failed`（disable 早失败时，R6-P2-1）；不健康＋非 fail_open＋修好且兜底 → `blackholed_kill_switch`；修失败 → `policy_missing`（detail 明言流量是被黑洞兜住还是真走直连） | ✓ 与 docstring 逐项一致 |
| `_policy_active()` | 三要件：enabled＋rule 在位＋表 100 有非 linkdown 的 `default … dev tun1`（:1096-1132）；黑洞-only 不算 active（R13-BUG-1 模型）；linkdown 路由不算（R24-P2-1） | ✓ |
| `_repair_policy()` | 永不 raise（失败进 note）；先清死占位（三重死检＋无 sing-box 持有者，:993-1041）再 repair 动词 | ✓ |

### §2.4 登录锁状态机（双面）

| 变迁 | Flask（panel/app.py:194-195, 389-451） | Worker（index.js:87, 377-460） | 结论 |
|---|---|---|---|
| 失败计数 | `_record_login_failure`：窗口内失败＋1，满 5 → 锁 15 分钟＋清空失败列表；写盘失败不阻塞 verdict（R9-P2-2） | `recordLoginFailure`：同款 5／300s／15min；KV 写带 TTL | ✓ 常数与变迁一致 |
| 锁到期 | `_login_locked_until`：过期即 None（解锁） | `loginLockedUntil`：过期即 0 | ✓ |
| 成功登录 | `_clear_login_failures`（:1328 调用）清计数 | KV delete `loginfail:<ip>`（:445） | ✓ |
| 畸形记录 | 时间戳非数值过滤（:399-401）；`locked_until` 缺失按 0 | `kvLoginFailRecord`（BR 修法）：非对象／数组重置＋warn，缺字段补全，字段级损坏 loud 500 | ✓ |
| 畸形请求体 | 非 JSON／非对象 → 400 且不记限流 | 同款（:425-428，R13-P2-4） | ✓ |

### §2.5 CA 状态机（core/openvpn_manager.py＋agent/agent.py＋双面面板）

- **init_pki 三层守卫，无旁路**：面板入口（Flask :1703-1750、Worker :1129-1143）缺 force／confirm 任一即 400，不走到节点判定；agent `action_init_pki`（agent.py:617-628）force=true 且 confirm 不为 true 即 ValueError；core `init_pki(force=False)`（:176-193）遇已存 CA 即拒、不擦除。force=true 的重建必经三层显式确认。
- **create_server**：无 CA 时先 `init_pki()`（非 force，只建不存在的 CA）；`build_server_cert()` 幂等（完整集复用、残缺对先清，P1-10）。
- **revoke**：`ovpn_users_revoke`（panel/app.py:1826 起）吊销进 CRL，`crl-verify` 在 server.conf.template:17；「吊销后须重启 OpenVPN 服务才对新连接生效」与 README 一致。
- **index.txt**：文件名列恒为字面 `unknown`，证书按序列号 DER 解析识别（durable 口径，Core 46/46 覆盖）。

### §2.6 节点状态机

- 注册：token 明文只返回一次，库里只存 SHA-256（Flask）／KV 只存哈希（Worker）；轮换旧 token 立即作废（须重跑 install-agent.sh）；吊销：token 立即失效、后续 poll 401、queued＋sent 命令一并标 failed（§2.1）。
- 认领守卫：`_check_panel_claim`（Flask）／Worker 同款——body 认领的 panel_url 与注册绑定逐字一致才认领，否则 403＋审计；旧版 agent 未上报时放行但 poll 响应带 `panel_url_unverified: true`。

### §2.7 安装／升级状态机（install.sh）

- panel/ 走 staging 复制、删除 staging/data/ 后再拷入（:474-505）：**无 panel/data/ 文件会进部署**，R8-BUG-1 的毒树重跑路径已死；默认重跑不销毁线上 panel.db（live-9 至 live-17 九轮毒树行级终验，本轮 §7 交叉核对）。
- OVPN_SUBNET ≠ 10.8.0.0/24 即 fail-fast（R12-P2-4／AZ）；OVPN_PORT 前导零大声失败（O-R27-3 沿用，不立案）。

**§2 结论：除 §8 的 R30-P2-1 外，本轮状态机推导未发现无守卫旁路、假定不可达状态的可达变迁、或静默丢状态的变迁；全部变迁与文档模型一致或已 adjudicated。**

## §3 功能链全量对账（README / DELIVERY.md / security.md 逐项对行为）

### §3.1 机械计数复核（本轮独立重算）

- **13 动作白名单三面逐字一致**：Flask `AGENT_ACTIONS`（app.py:199-204）、agent `ACTIONS`（agent.py:754 起字典键）、Worker `ACTIONS`（index.js:64-78）——本轮 python 重算三面各 13 项排序后逐字相同。
- **verify.sh 24 项检查**：本轮重算 24 distinct 名（`ok`／`bad`／`skip` 首参去重），与 R27 计数一致；R27 后 verify.sh 改动仅 cleanup() 恢复逻辑，未增删检查名。
- **发布包快照**：`tar tzf` 92 条目 ✓；sha256 与 sidecar 一致（`540fc8fcf2f05b62a5c91b058720dd9d7af3bd186cb10cd88d6f1390727acd47`）✓；包内审计报告 25 份（26 行含目录项）／live 报告 17 份 ✓；包内 verify.sh 哈希 `7867f557c6bb` 与 DELIVERY §9 所记一致 ✓（工作树 verify.sh 已因 R26／R27 修复而不同，属预期）——§9 是 1.0 包的真实快照，刷新属发版步骤（O-R27-1／O-R28-1／O-R29-1 延续），不当轮立案。
- **install.sh 固定清单**：`agent core egress panel systemd install.sh verify.sh verify-integration.sh README.md`（:469）与 README 所列逐字一致；panel/ 走 staging 排除 data/（§2.7）。

### §3.2 功能矩阵（功能 → 行为证据；探针编号见 §6）

| 功能（README／DELIVERY 宣称） | 行为证据 | 结论 |
|---|---|---|
| OpenVPN UDP 1194 主／TCP 443 备 | Core 46/46（§6 重跑）；install.sh 环境变量＋存量继承＋非法值早死 | ✓ 沙箱级；数据面属 live 轮 |
| 建用户／吊销／下载 .ovpn | Core 46/46；Flask 86/89（绿格内）；用户名正则＋保留名逐字一致 | ✓ |
| SK5 启用／停用 | BM 22/22、BO 18/18、BS 9/9、BT 23/23、R24 25/25、R25 37/37（§6 重跑） | ✓ |
| 断网保护 fail-closed | BM K1–K5（真实 netns＋真实 ip） | ✓ |
| 健康检查 60 秒＋自愈 | 定时器 OnUnitActiveSec=60s；BM H1–H10；BS 9/9 | ✓ |
| 命令队列＋agent 5 秒 poll | POLL_INTERVAL=5（agent.py:70）；R17 四套件；R21 6/6；BQ 6/6 | ✓ |
| Flask＋Worker 双面 | R17 四套件；BR 11/11；R27 Worker 5/5；R29 toggle 11/11＋10/10 | △ 除 §8 R30-P2-1（整数浮点谓词）外一致 |
| 登录限流 | Flask／Worker 双面格；BR 11/11；429＋Retry-After（app.py:1328 附近） | ✓ |
| 密码处理 | bcrypt＋透明迁移；改密格；Worker 改密 501；默认口令 grep 零命中（§4） | ✓ |
| 重建 CA（force+confirm） | Flask F-cells；R17-P1-1 守卫；§2.5 三层守卫已读 | ✓ |
| /api/sk5/test UDP 腿 | 判据已修 round-trip 证明（R27-P2-1，探针 6/6） | ✓ 已关闭 |
| verify.sh 强制路径 | API 先行恢复运行链（R27-P1-1，探针 8/8） | ✓ 已关闭 |
| README Cloudflare 节 | 填 id 步＋未验横幅＋「可选」在位（R28 修复）；全树「推荐」0 处（本轮 grep 复核） | ✓ 已关闭 |
| 开关布尔输入 | 双面严格 400（R29 修法，探针 11/11＋10/10） | △ 整数浮点处仍分歧，见 R30-P2-1 |

## §4 安全清单对账（docs/security.md 逐项抽查）

- **默认口令字面量零命中**：`grep -rnw "admin123\|changeme\|123456" panel/ agent/` 零命中（`-w` 词界，agent hex 字符集含 `123456` 子串不计）。
- **限流 XFF 守卫**：仅 `OVPN_TRUSTED_PROXY=1` 时才信任 X-Forwarded-For（app.py:182-183，ProxyFix），默认不信任。
- **会话**：Cookie HttpOnly＋SameSite=Lax、12 小时、改密后 session_version+1 全旧会话失效——R17 Flask 绿格内（§6 重跑）。
- **SK5 凭据**：只存 sk5.json（0600），get_status 只回 has_password、日志脱敏——R17 Flask 绿格内；P0-4 保留密码语义（§2.3 已复算）。
- **命令重投非幂等风险**：security.md:12 已诚实记录（O-R27-2 沿用，不立案）；重投集双面不对称已 adjudicated（§2.2）。
- **agent 通道**：panel_url 须 HTTPS（仅 127.0.0.1／localhost／[::1] 例外）、禁 https→http 降级重定向——R17 Agent 33/33（§6 重跑）。
- **结论：security.md 抽查项与行为一致，无新缺口。**

## §5 门禁（verify-integration.sh 29 格，串行）

- **正树：PASS=29 FAIL=0 SKIP=0，exit 0**（/tmp/r30/ptree 上跑，约 23 秒，树静止后串行——门禁 harness 非并发安全，固定 /tmp/ovpn-int-test＋8443 端口；日志 /tmp/r30/gate.log）。
- **§7 变异 11/11 恰红 28/1**：`tests/build-mutants.py` 造 11 棵变异树（m-char、m-const-sb、m-dict-extra、m-dict-missing、m-dict-sb、m-dict-ts、m-dict-x-a、m-dict-x-amd、m-dict-x-arm、m-dict-x-b、m-install-sb），逐棵串行跑门禁，**每棵均为 PASS=28 FAIL=1 SKIP=0、exit=1，且唯一红格全为 §7「钉死哈希不一致：install.sh 与 agent/agent.py 的 sha256 逐键不等」**（11 棵日志逐棵 grep 核对，无第二红格；日志 /tmp/r30/gate-m-*.log）。

## §6 探针套件重跑

全部在 /tmp/r30/ptree（工作树副本）上重跑；Flask 类跑在 nobody 身份＋venv＋fixture env（OPEN 前缀＋OVPN_SK5_CONFIG_DIR，新鲜 data 目录／轮），Worker 类 `node tests/*.mjs`。**红格说明**：下表凡标注「预期翻转」的红格均为缺陷钉死格（探针断言的是缺陷行为本身，修复后按设计翻红），非回归。

| 套件 | 结果 | 备注 |
|---|---|---|
| R17 Flask | 86/89 | 仅 3 个预期 OBSERVED 翻转（F4-02b／F4-13／F4-15） |
| R17 Core | 46/46 | |
| R17 Agent | 33/33 | |
| R17 Worker | 33/35 | 仅 2 个预期 OBSERVED 翻转（W5-05／W5-06a） |
| BK（存量形状） | 8/8 | |
| BM（黑洞＋自愈） | 22/22 | root 跑，真实 netns＋真实 ip |
| BO（tun1 repair） | 18/18 | root 跑 |
| BP（boot restore） | 14/14 | root 跑 |
| BQ（队列不可读） | 6/6 | |
| BR（Worker loginfail 数组） | 11/11 | |
| BS（verdict） | 9/9 | |
| BT（占位符消除） | 23/23（PASS 行计数 23，0 FAIL） | root 跑 |
| R24（enable 占位符） | 25/25（ALL PASS） | root 跑 |
| R25（repair 收敛） | 37/37（PASS 行计数 37，0 FAIL） | root 跑 |
| R21（队列隔离） | 6/6 | |
| R22 Flask（时间边界） | 22/22 | |
| R22 Worker | 12/12 | |
| R23 Flask（持久态形状） | 13/13（main） | R23 的 empty_secret／db_garbage／db_empty／db_old_admin 四形状模式 R29 已单列，本轮 main 13/13 即全量；四形状未重跑（R29 结论沿用，树在 R29 后只改 index.js 一处 hunk） |
| R23 Worker | 9/9 | |
| R20（输入形状） | 7 格，3 红为预期缺陷钉死翻转（S1／S2／S6）；须 root | S1/S2 的 honest ValueError 与 S6 的 HB-OK 均为修复后行为 |
| R18 Worker race／malformed | race 9 格 2 红、malformed 13 格 4 红，均为预期翻转 | R18 探针断言的是缺陷行为；修复后行为由 BI 套件验证 |
| R19 非列表容器／ovpn 下载 | 12/12、8/8 | |
| BG Worker poll guard | 22/22 | |
| BH Worker poll guard | 20/20 | |
| BI Worker queue race／malformed | 15/15、18/18 | |
| R27 强制分歧 | 8/8 | R27-P1-1 闭合（§1.1）；首轮误以 nobody 身份跑，unshare 写 uid_map EPERM，纠正为 root 重跑 8/8（见 §10） |
| R27 UDP 判据 | 6/6 | R27-P2-1 闭合 |
| R27 Worker 悬空队列 | 5/5 | R27-P2-2 闭合 |
| R29 双面开关布尔 | Flask 10/10、Worker 11/11 | R29-P2-1 闭合（§1.1）；T9 已裁定回落钉死格在内 |

**结论**：历史关闭项无一复发；全部红格均为钉死缺陷行为的预期翻转或 R27 新探针的直接复现（现已翻绿，见 §1）。

## §7 live-18 与补记的交叉核对

（R27 §7 已逐项核对、R28 §7 与 R29 §7 沿用；本轮树在 R29 后只改 index.js 一处 hunk（coerceToggleBool）＋两 R29 探针期望，live-18 的树侧可核项结论沿用，无须重核。唯一新增：R29-P2-1 与 R30-P2-1 均为 Worker 面行为，live 轮只验服务器面（Worker 无真实部署，P0-1），故两条均无真机格可对账；沙箱双面探针即完整证据，真机复核不适用。）

## §8 差集（新发现）

### R30-P2-1（P2）——Worker 的整数谓词接受 JSON 整数浮点（`1.0`），Flask 面 400；R29 修法宣称的「同口径」在该输入类上不成立

- **机制（双面同输入不同 verdict，机械枚举）**：JS 只有一个 number 类型——`Number.isInteger(1.0)` 为真；Python `isinstance(1.0, int)`／`type() is int` 为假。JSON 字面量 `1.0` 在两面经各自解析器后落入不同的类型判定：
  - Worker `coerceToggleBool`（cloudflare/src/index.js:1257-1263，R29 新写）：`typeof value === "number" && Number.isInteger(value) && (value === 0 || value === 1)`——`1.0` 通过，规整为 `true`。
  - Flask `_coerce_bool`（panel/app.py:1091-1105）：`isinstance(value, bool)` → `isinstance(value, int)`——`1.0` 是 float，两项皆否 → 400。
  - Worker 保存路由端口校验（index.js:1207）：`!Number.isInteger(port) || port < 1 || port > 65535`——`1001.0` 通过。
  - Flask `_valid_port`（app.py:1084-1088，R12-P1-2）：`type(value) is int`——`1001.0` → 400（三处调用点 :1548 建服务、:1997 远程 SK5 保存、:2131 本地 SK5 保存，同一谓词）。
- **行为实证（本轮双面新写边缘探针，逐格对照）**：

  | 输入 | Flask | Worker | 备注 |
  |---|---|---|---|
  | `{"fail_open": 1.0}` | 400 | 202，入队 `fail_open: true`（经 `/api/cmd/<id>` 核验参数） | 分歧 |
  | `{"udp_over_tcp": 1.0}` | 400 | 202 | 分歧 |
  | `{"port": 1001.0}`（POST /api/sk5 保存） | 400 | 202 | 分歧 |
  | `{"fail_open": 1.5}`／`{"port": 1001.5}` | 400 | 400 | 对照：非整数浮点两面一致拒 |

  （探针：/tmp/r30_edge.mjs、/tmp/r30_edge2.mjs、/tmp/r30_edge3.mjs、/tmp/r30_edge.py、/tmp/r30_edge4.py；mock KV＋test_client；/etc 终态复核为空。）
- **范围（机械推导，闭合）**：Worker 全树客户端输入侧的整数谓词枚举——`Number.isInteger` 全集仅两处（:1207 端口、:1259 开关规整），即本条的两名成员，无第三处。排除项（已核，有理由）：`toMs`（:631）是 sweep 内部时间戳归一化（非数值按 0 计、已超时方向，R18-P2-2 的有意 fail-closed 语义）；`retries`／`created_at` 的 `typeof === "number"`（:654-655、:671）是内部命令记录 bookkeeping，非客户端输入校验。Flask 侧客户端整数谓词全集：`_valid_port`（`type() is int`）、`_coerce_bool`（`isinstance int`）、`_safe_int`（float → None），三者对浮点一律拒绝，均匀严格。
- **不是 R29-P2-1 的复发**：R29-P2-1 的机制是 `typeof` 回落＋终端 `: false`＋`enabled` 回落键——该机制已死，R29 两探针本轮重跑 11/11＋10/10 全绿。本条是新谓词 `Number.isInteger` 的不同输入类（R29 两探针均未覆盖 `1.0`，grep 零命中），按「修 a 漏 b」同族新成员立案，不算复发。端口成员亦非 R12-P1-2 的复发（那条修的是 Flask 面 bool-is-int-subclass；Worker 保存路由的 `Number.isInteger` 从未被任何一轮探针覆盖）。
- **下游影响（已追踪到 agent，不夸大）**：开关成员——agent 收到的是真布尔 `true`，照常执行，无静默反向（与 R29-P2-1 的反向不同），害处仅为 verdict 分歧；端口成员——agent `_as_int`（agent.py:363，R13-P2-5）显式拒绝 float（`int(1194.5) == 1194` 截断的前科），故 Worker 202 入队的 `port: 1001.0` 命令会在 agent 侧执行失败，不会污染存量配置（`_validate_stored` 的严格 int 检查亦为第二道防线），害处是「202 已排队、随后执行失败」的误导性成功回执。两成员均无静默反向、无数据损坏、无安全绕过，故定 P2 不定 P1；但 fail-open 是安全相关开关，同一请求在两面 verdict 相反，且 R29 修法明言「同口径」——该宣称在整数浮点处为假，必须立案。
- **触发现实性**：须客户端发出 JSON 字面量 `1.0`——Python `json.dumps(1.0)` 即发 `1.0`（JS `JSON.stringify(1.0)` 会塌成 `1`，故 JS 客户端撞不上；Python 脚本／第三方集成撞得上）。输入类真实存在，非臆测。
- **修法**：Worker 侧收紧（绝不放宽 Flask——R12／R13 已裁定严格 int）。注意 JS 在 `JSON.parse` 之后无法区分 `1.0` 与 `1`（两者皆为 number 1），故校验须发生在原始请求文本层（或等效的 token 级检查），而不是在已解析的值上加 `Number.isInteger`。另：两 R29 探针须补 `1.0` 格（BH-03(c) 款式，断言修复后双面一致 400），使该输入类进入回归套件。

## §9 未验与观察

### 发版前检查清单（非 finding，O-R27-1／O-R28-1／O-R29-1 延续）

新版重打时 DELIVERY §9 与卷首台账须按实测刷新（§9 仍为 1.0 包的真实快照，本轮 §3.1 已核 92 条目／审计 25 篇／live 17 份／verify.sh 哈希无误）：审计 25→**30** 篇（R26／R27／R28／R29／R30）、live 17→**18 份＋补记**（live-verify-R18.md＋live-verify-R18-supplement.md）、台账 163→**171**（170＋R30 新 1）、终审 AUDIT-R25→**AUDIT-R30**、门禁计数仍 29 格（本轮重跑 29/29）。R30-P2-1 修完后须重跑本轮边缘探针（双面 1.0 格应翻为一致 400）＋两 R29 探针（11/11＋10/10）＋门禁 29/29，再打新包。

### O-R30-1（观察，不立案）：R28 的两句措辞建议已落地

- O-R28-2（恢复失败路径句）与 O-R28-3（UDP 第二档括号）已由 R28 修复路落入 README／DELIVERY，本轮 §3 grep 复核在位（DELIVERY:43／:122）。关闭。

### O-R27-2（观察，延续）：agent 侧无命令去重，重投即重执行（已文档化、危害有界）

- security.md:12 已诚实记录；create_user 二次执行报已存在、init_pki 二次执行无新增用户损害、其余动作幂等。不立案。

### O-R27-3（观察，延续）：OVPN_PORT 前导零大声失败，不断言

- `OVPN_PORT=0117` 过 bash 八进制检查、Python 渲染为 117、grep 校验 die——大声失败，无静默错配。不立案。

### P0-1（站立未验）：Cloudflare Worker 真实部署

- 本轮仍无真实部署可验，不冒充。Worker 面只跑 mock-KV 探针。wrangler.toml KV id 仍为占位符（:32 `REPLACE_WITH_KV_NAMESPACE_ID`、:33 `REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`，本轮已核）。

### arm64 真机安装／SK5 端口 1001 vs 9000

- 均未变：无 arm64 机，仍未验；端口用户仍未确认，面板默认 1001。

## §10 审计方法与证据

- 探针一律在 /tmp 树副本＋venv＋nobody 身份下跑（Flask 类），env 名用 OPEN 前缀（`OPENVPN_CA_DIR`／`OPENVPN_SERVER_DIR`）＋`OVPN_SK5_CONFIG_DIR`，新鲜 data 目录／轮（复用 data 目录会使 `_ensure_admin_password` 返回 None，探针断言新鲜密码失败）；各探针的树 env 名按探针头读名设值（BQ_TREE／R21_TREE／R22_TREE／R23_TREE／R17_TREE／R29_TREE／BG_TREE）；`__file__` 解析树的探针（BK／BM／BO／BP／BS／BT／R24／R25／R20／R27-verify）在 ptree 副本内直接跑；r20／r25／r27-verify／BT／R24／BO／BM／BP 须 root 跑（unshare 绑挂／ip 操作），且 /tmp/r30 整条路径须对 userns 内可遍历（755）；fixture-server／fixture-ca 须属 nobody 所有。/etc/openvpn-sk5-panel/ 每次跑后复核为空（终态复核：空，0 泄漏）。
- 沙箱 UDP/TUN EPERM 为环境假象，不作产品结论；数据面结论属 live 轮。
- 本轮复跑中纠正的调用口径问题（数字为纠正后实测，如实记账）：① r27-verify 首轮误以 nobody 身份跑，`unshare: write failed /proc/self/uid_map: Operation not permitted`，纠正为 root 重跑 8/8；② 首轮白名单比对正则未命中 `frozenset({…})`／`new Set([…])` 写法，纠正后三面 13/13 逐字相同；③ verify.sh 检查计数首轮正则未命中 `ok "name"` 写法，纠正后 24 distinct 名。
- 门禁串行跑（harness 非并发安全）；变异 11 棵逐棵串行，日志 /tmp/r30/gate-m-*.log；探针全日志 /tmp/r30/probes.log；Worker 探针逐个在 /tmp/r30/ptree 上跑；边缘探针 /tmp/r30_edge*.mjs／.py。
- 本轮未提交、未推送任何改动；报告为未跟踪文件。

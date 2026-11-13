# AUDIT-R19 — 全量全局回头看（交付前，第七轮）

## 结论先写

**结论：不能交付（差集 2 条，均为 P2）。**

历史 152 条：**147 已修、2 部分（P0-3、P1-7）、1 未验（P0-1）、2 新（R19-P2-1、R19-P2-2），零复发。**R18 的 2 条（P2-1、P2-2）本轮行为重验＋定点变异红证，全部关闭（§1）。新发现 2 条均为 Worker 面的“同一机制在另一面未落地”——R19-P2-1（queue／sent 容器非数组时 500，Flask 面 BA 已修）与 R19-P2-2（.ovpn 下载不查吊销／过期，Flask 面 AW 已修）；两条均非既往条目的复发（谓词面不同，见 §3）。

- 审计员：独立审计路（未参与建设与修复路 BI；单审计员边做边写，不派子代理）
- 日期：2026-11-13（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R18 同等广度）
- 推导方法：**跨面一致性审计**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性、R9 对抗操作员＋时间衰变、R10 环境矩阵×修复存活、R11 契约闭合、R12 外部输入枚举、R13 部署生命周期、R14 证据优先行为复推导、R15 交付文档驱动用户旅程重演、R16 门禁与证据链反向审计、R17 爆炸半径 FMEA、R18 命令生命周期状态机转移闭合均不同）——以“同一语义在两面必须同义”为尺，逐项枚举 Flask 面与 Worker 面的同名同义行为对（命令状态机、超时与重投、吊销与下载、登录锁、节点快照、错误文案与状态码），逐对验证行为一致（输入相同→输出同义），任一对分歧未在文档中诚实记账即立案。R11 的契约闭合审的是接口形状，本轮审的是行为语义；R17 的 FMEA 与 R18 的状态机转移结论只作输入，不作本轮证据。
- 测试一律在 `/tmp` 副本上跑；未动项目原文件（除本报告与新增探针）；门禁自带 harness（venv＋桩 sing-box/systemctl/ip，面板以 nobody 跑）；未动任何真机。需真机行为复核的项一律写“待 live-12／live-13”或对账 live-11，不提前判通过。
- 语法基线：`node --check`（index.js）与 `python3 -m py_compile`（panel／core／agent／egress）均过；`bash -n verify-integration.sh install.sh` 过。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明（与 R9–R18 同款记明）。

## §0 树版本与 BI 改动确认

当前树是 BI 修复路之后的新树。文件 mtime（UTC）与 R18 §0 基线对照：

| 文件 | mtime (UTC) | 行数 | sha256（前 12 位） | 说明 |
|---|---|---|---|---|
| cloudflare/src/index.js | 2026-11-12 19:06:24 | 1444 | 9b85049f4f64 | **动过（BI：条件式清空＋`_sweepWorkerCmds`＋`toMs`＋`_handleSentTimeout`＋sent 副本去重；与主控核验的 sha256 一致）** |
| panel/app.py | 2026-11-12 18:38:12 | 2754 | 204de1136cc5 | 未动（R18 mtime，BG） |
| core/openvpn_manager.py | 2026-11-12 17:20:57 | 1550 | 3b5d7dfe9ea1 | 未动（R18 mtime，BB） |
| agent/agent.py | 2026-11-12 16:46:20 | 922 | 7f999298df5b | 未动（R18 mtime，AX） |
| install.sh | 2026-11-12 16:46:54 | 1082 | 3f050f037e7a | 未动（R18 mtime，AZ） |
| verify-integration.sh | 2026-11-12 18:14:53 | 630 | 6ef6ba2db8b1 | 未动（R18 mtime，BE） |
| panel/templates/index.html | 2026-11-12 15:21:57 | 1259 | 4f7dc697451c | 未动（R18 mtime） |
| README.md | 2026-11-12 17:56:09 | 287 | 6154ecabe046 | 未动（R18 mtime） |

结论：自 R18 起全树只有 `cloudflare/src/index.js` 动过（BI 一路）；其余文件 mtime 与 sha256 均与 R18 §0 基线一致。历史复扫按 mtime 规则：未动文件的既往结论沿用 R1–R18 证据，不冒充重跑；BI 的改动面（Worker 队列／sweep／超时）本轮全量行为重验（§1）＋跨面矩阵重审（§2）。本轮新增探针 2 套均已落进树内 `tests/`（`r19_worker_nonlist_container.mjs`、`r19_worker_ovpn_download.mjs`），/tmp 资产（`/tmp/r19/` 变异树与调试脚本）仅作过程证据。

## §1 BI 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

### §1.1 BI 探针亲手重跑（新树，相对 import，无 /tmp 副本依赖）

| 探针 | 结果 | 说明 |
|---|---|---|
| `tests/bi_worker_queue_race.mjs`（BI，竞态修复后行为） | **15/15** | 含孤儿回收格 BI-RACE-08/08b/09/10 |
| `tests/bi_worker_malformed.mjs`（BI，畸形 sweep 修复后行为） | **18/18** | 含 sent_at "abc" 格 BI-M-03/03b、吊销救畸形格 BI-M-10 |
| `tests/bh_worker_poll_guard.mjs`（BH 回归） | **20/20** | 无退化 |

### §1.2 R18 复现探针翻转核对（缺陷断言探针，修复后按预期翻红）

| 探针 | 结果 | 翻红格 | 结论 |
|---|---|---|---|
| `tests/r18_worker_queue_race.mjs` | 7/9 | RACE-02（poll 1 下发 A＋B 两条）、RACE-05（B 状态为 sent） | B 在 poll 1 即被下发，非丢失 ✓ |
| `tests/r18_worker_malformed.mjs` | 9/13 | M-01/02/03/06（四类畸形记录均已标 failed） | sweep 在位 ✓ |

### §1.3 定点回退变异红证（只回退 BI 的一层，变异构建器 `/tmp/r19/build-reverts.py`，变异树 `/tmp/r19/mutants/`）

| 变异树 | BI 竞态 | BI 畸形 | R18 复现 | 结论 |
|---|---|---|---|---|
| m-clear（条件式清空→无条件写 `[]`） | 15/15 | 18/18 | 竞态 7/9、畸形 9/13（与固定树数相同） | **不红——见 §1.4 层分析** |
| m-sweep（4 处 sweep 调用点拆除，函数定义保留） | 11/15 | 12/18 | — | 恰红 ✓（竞态红 BI-RACE-08/08b/09/10 四格孤儿回收；畸形红 BI-M-01/02/06/07/08/10 六格 sweep） |
| m-toms（`toMs`→原始 `Number(value)`，NaN 直通） | 15/15 | 18/18 | — | **不红——见 §1.4 层分析** |
| m-s4（`_handleSentTimeout` 守卫恢复修复前形状：原始 `sent_at`＋`>` 比较） | 15/15 | 16/18 | 畸形 10/13（M-03 翻回 PASS＝缺陷复现） | 恰红 ✓（仅 BI-M-03/03b 两格 sent_at "abc"，status=sent、retries=0，S4 缺口复现） |

### §1.4 层分析：两层防御纵深，承重层与冗余层须分开记账（本轮实测结论，非缺陷）

**m-clear 不红的原因（已机械验证）：**sweep 在 poll 开头先跑（index.js:781），孤儿 queued 记录当场重入队并进本轮下发循环；窗口内入队的 id 即使被无条件清空丢掉引用，下一轮 poll 的 sweep 也会再捞回。逐时序枚举三窗：入队落在 sweep 读之前→本轮 sweep 救回（两树同为 poll 1 下发）；落在 sweep 与清空写之间→固定树靠条件式清空保留、m-clear 靠下一轮 sweep 救回（两树同为 poll 2 下发）；落在清空写之后→两树同为 poll 2 下发。**生产路径上（KV `list()` 恒在）条件式清空与无条件清空行为等价**，m-clear 变异在任何真实代码路径探针上都无法变红。曾尝试以“无 list() 的 MockKV”隔离该层：无效——`listNodes`（index.js:206）同样无条件调用 `list()`，无 list() 时整个 Worker（鉴权／入队／poll）全部 500，所谓“退化环境”并不存在（BI 注释称 sweep 在 list() 不可用时退化，是该函数自身的防御分支，不是可达的部署态）。**结论：R18-P2-1 的“永久丢失”谓词由 sweep 单独关闭；条件式清空是结构性纵深（sweep 若有朝一日被拆除，它独自承重），不是本轮的承重层。**不因此立案——缺陷谓词已关闭，冗余层无行为代价（条件式清空无额外 KV 往返：重读本就是一次 get，filter 在内存做）。

**m-toms 不红的原因（已机械验证）：**S4 的真正承重改动是 `_handleSentTimeout` 的守卫取反（`now - sentAt <= TIMEOUT → return null`，NaN 比较恒假→不 return→落入超时分支）。在 JSON 可达的输入全集内，`toMs` 与原始 `Number()` 无行为差：非数值 "abc" 在取反守卫下两路都触发超时；数值串两路都正常比较；`Infinity` 无法经 JSON 到达（`JSON.stringify(Infinity)`→`null`）。m-s4（恢复 `>` 守卫形状）恰红 BI-M-03/03b，证明 S4 闭合由守卫取反承重，`toMs` 是纵深（在 `handleGetCmd` 的 timeout_hint 与 sent 副本写回处仍做数值化，方向一致、无害）。

### §1.5 R18-P2-1／P2-2 关闭判定

- **P2-2 关闭**：sweep 调用点拆除变异恰红 6 格畸形＋4 格孤儿回收；S4 守卫回退变异恰红 BI-M-03/03b；R18 复现探针按预期翻转。**已修，关闭**。
- **P2-1 关闭**：永久丢失谓词由 sweep 关闭（m-sweep 变异的 BI-RACE-08/08b/09/10 四格恰红为证）；条件式清空层无独立红证（§1.4），但不影响谓词关闭——sweep 是承重层，清空是纵深。**已修，关闭**（附层分析，不另立案）。
- 另：BI 报告称“R18 竞态探针 7/9（RACE-02/05 翻红）、畸形 9/13（M-01/02/03/06 翻红）”，本轮亲手重跑数完全一致。

## §2 跨面一致性矩阵（本轮推导方法）

尺子：同一语义在两面必须同义——相同输入→相同输出；分歧必须在文档中诚实记账，否则立案。路由表全集：Flask 36 条路由，Worker 覆盖其中 34 条（缺 `GET /api/audit` 与 `GET /api/openvpn/public-ip`，见 C10／C11）。每格结论＝本轮代码面实读＋探针行为复现；未动文件（自 R18 后除 index.js 外 mtime 一致）的既有对按 mtime 规则沿用 R11–R18 证据，不冒充重跑。

| # | 行为对（同名同义） | Flask 面 | Worker 面 | 结论 |
|---|---|---|---|---|
| C1 | poll 只下发 queued 命令 | ✓ 守卫（BG，app.py:2560） | ✓ 守卫（BH，index.js:823） | 闭合。探针 BG 22/22、BH 20/20 |
| C2 | report 只接受 sent 回执，非 sent 回 409 | ✓ 409＋审计 `agent_report_not_sent`（BG） | ✓ 409（BH） | 闭合。探针 BG-04/04b/05/05b、BH-03a/03b/03c/06b/06c |
| C3 | 超时 120s／重投上限 3 | ✓ `SENT_TIMEOUT_SECONDS=120`、`SENT_MAX_RETRIES=3` | ✓ `SENT_TIMEOUT_MS=120000`、`SENT_MAX_RETRIES=3` | 数值闭合。重投集合分歧见观察 O1（R5 已裁定） |
| C4 | 畸形 sweep（读路径先扫） | ✓ `_fail_malformed_cmds`，6 处读路径 | ✓ `_sweepWorkerCmds`，4 处读路径（BI） | 闭合（§1）。容器形状缺口见 R19-P2-1 |
| C5 | 吊销：queued/sent 命令先标 failed 再删节点 | ✓ 先 sweep 再 DELETE（BA） | ✓ sweep 后标 failed，再删 node/queue/sent/status 四键 | 闭合。BI-M-10：吊销救畸形记录 |
| C6 | .ovpn 下载：revoked／expired 一律 403 | ✓ 三条路径共用 `_download_block_reason`（AW，R13-P2-3） | ✗ `handleCompatOvpnDownload` 只认回执存在即 200，不查快照 users | **不闭合 → R19-P2-2** |
| C7 | 登录锁：5 次／5 分钟／锁 15 分钟，429＋Retry-After；畸形体 400 不记数 | ✓ `LOGIN_MAX_FAILURES=5`／300s／900s（app.py:194-196） | ✓ 同值（index.js:87-89）；畸形体 400 不记数（AY） | 闭合。R17 F1／W1 探针覆盖 |
| C8 | 节点快照：stale 判定与形状 | ✓ `stale = age is None or age > 60`，`{openvpn, egress, sk5, users, stale, age_s, note}`（与 Worker 同款，app.py:822） | ✓ 同阈值同形状（`cachedStatus`） | 闭合 |
| C9 | 改密 | ✓ 实现（Flask 改密 F1-11～F1-14） | 501 诚实端点（AQ） | 已知分歧，有文档（R11-P2-1 修复口径） |
| C10 | 审计日志 `GET /api/audit` | ✓ SQLite `audit_log`，上限 500 | ✗ 无此路由（404“未知接口”） | 已知分歧，无用户影响：前端 0 处调用（`grep -c audit`＝0）；`docs/security.md:18` 按 Flask 面描述，不宣称 Worker 有。Worker 侧无审计存储是设计（原因进记录 error＋console.warn），不立案 |
| C11 | 公网 IP 探测 `GET /api/openvpn/public-ip` | ✓ 实现 | ✗ 无此路由 | 已知分歧，诚实降级：前端 `detectIpBtn` 的 catch 文案明示“Cloudflare 模式无此端点，请手动填公网 IP/域名”（index.html:1089-1100），不立案 |
| C12 | SK5 保存校验：host 非空、port 为 1–65535 真整数、bool 开关拒非布尔 | ✓ `_valid_port`（`type is int`，AS）＋开关 `_strict_bool` | ✓ `Number.isInteger(port)`＋范围，host 非空 | 闭合。偏字段保存见观察 O2 |
| C13 | init-pki 须 force＋confirm 双 true，否则 400 | ✓（AA） | ✓ `force !== true`／`confirm !== true` 各 400（`handleCompatInitPki`） | 闭合 |
| C14 | 命令入队参数容器校验 | ✓ params 非对象→400（AS） | ✓ 数组 params→400（AT）；值校验（port bool 等）由 agent `_as_int` 异步拒收，cmd 落 failed＋error | 闭合（异步模型，R11 兼容层设计；入队时 202、执行失败诚实落 failed，非静默） |
| C15 | 错误信封与状态码 | ✓ `{ok, error}`；400／401／404／409／429 各有其位 | ✓ 同信封；409＝状态冲突（report 非 sent，两面 BG／BH 同款） | 闭合 |
| C16 | 会话有效期 | 12 小时（`PERMANENT_SESSION_LIFETIME`） | 24 小时（`SESSION_TTL_S`） | 分歧但有文档：各面文档自述其值（`docs/security.md:10` 12h；`cloudflare/README.md:163` 24h），不立案 |
| C17 | 节点 token 鉴权＋panel_url 认领守卫 | ✓ Bearer＋认领 403 | ✓ 同款（R3-P2-12） | 闭合 |
| C18 | `/api/me` | ✓ `{ok, admin: session}` | ✓ `{ok, admin: true}`，在 `requireAdmin` 之后（index.js:1347-1351） | 闭合（单管理员，两面同义） |
| C19 | agent 安装包 | ✓ 本地 bundle＋sha256 | 代理 `AGENT_BUNDLE_ORIGIN`，未配置 503 明示 | 已知分歧（P0-3 部分，部署态未验见 §5） |
| C20 | status 形状与 via_sk5 判据 | ✓ 本机实测；远程快照同款 | ✓ 快照；via_sk5 唯一判据是实测 `policy_routing_active`（R6-P1-1／R7-P1-1） | 闭合 |
| C21 | 节点 rotate：新 token、旧 token 立即作废 | ✓ 400 非法名／404 幽灵节点 | ✓ 同款（`handleRotateNode`） | 闭合 |
| C22 | queue／sent 容器值非数组时的读／写路径 | ✓ 按空处理＋审计（BA，R14-P2-1） | ✗ poll／enqueue／report／revoke／cmd_get 抛 TypeError → 500 | **不闭合 → R19-P2-1** |

### §2.1 观察（已核实，不立案）

- **O1（R5 裁定重申，不重议）：**Flask `_requeue_stale_sent` 重投全部动作（含非幂等 init_pki／create_user），Worker 只重投 `SAFE_RETRY_ACTIONS` 7 动作（get_status／test_sk5／enable_sk5／disable_sk5／start／stop／restart_openvpn，index.js:96-104）——分歧见 `docs/security.md:12`，R5 已裁定按设计。本轮复核：两面超时 120s、上限 3 的数值一致；集合分歧不重议。
- **O2（SK5 偏字段保存，UI 不可达，分歧方向为严格侧先失败）：**Flask 远程分支允许只带开关的保存（无 host／port 时入队、agent 自决，`_sk5_save_remote`）；Worker `handleCompatSk5Save` 要求 host 非空，否则 400。同输入 `{enabled:false}` → Flask 远程 202、Worker 400。前端从不发该形状（保存表单恒带 host／port；开关走专用 enable／disable 端点，两面均有）。严格侧先失败、无静默误执行、无用户可达路径，不立案；若日后前端改发偏字段保存，须先对齐。
- **O3（Flask 侧手改队列段残留）：**Flask 对照探针（§3.1）显示：非列表队列段被丢弃后，段内原命令记录仍滞留 `queued`（无孤儿回收，BA 的修法只删段、不重入队）。Worker 修后有孤儿回收，Flask 无——反向不对称，但 Flask 侧无 500、无节点卡死（poll 200、新入队正常），属 R14-P2-1 已接受的修法形态，不重议、不立案。

## §3 新发现

### R19-P2-1（P2）Worker queue／sent 容器值非数组时读路径与写路径 500

**机制谓词：**队列／sent 容器值非数组时，读路径与写路径不得 500，须按空处理＋隔离（原因进 error，不写内容）。

**机制（代码面实读＋机械推导）：**Worker 的 `queue:<name>`／`sent:<name>` 容器在 6 处被直接当数组用，无一处做 `Array.isArray` 归一化（除 sweep 的入参 fallback 只重读、不归一化）：

| # | 读／写点 | 非数组容器时的行为 |
|---|---|---|
| Q1 | `enqueueCommand`（index.js:303 `queue.push(id)`） | 字符串／对象 → `TypeError: queue.push is not a function` → 500；且 cmd 记录已先写盘，留下一条孤儿 queued 记录 |
| Q2 | `handleAgentPoll` 读队＋条件式清空（:826-833 `currentQueue.filter`） | 字符串／对象 → `TypeError: ...filter is not a function` → 500（无孤儿时亦然，见探针 NL-02） |
| Q3 | `_sweepWorkerCmds`（:684 `sentArr.map`；:715 `queueArr.push`） | sent 非数组 → `.map` 抛 → 全部四处读路径 500；queue 非数组＋有孤儿 → `.push` 抛 → 500 |
| Q4 | `handleRevokeNode`（:528 `[...queue, ...sent.map(...)]`） | 同 Q3（sweep 先抛；无孤儿时 sent 非数组仍在 spread 处抛） |
| Q5 | `handleAgentReport`（sweep 先行＋sent 副本 `filter` 写回） | sweep 先抛（sent 非数组／queue 非数组＋孤儿时）；无孤儿且 queue 非数组时 report 本身 200（探针 A 组对照） |
| Q6 | `handleGetCmd`（sweep 先行） | 同 Q5 |

**全集：**`queue:`／`sent:` 容器值的形状 × 路径共 12 格（2 容器 × 2 形状（字符串／对象）× 3 类路径（poll／enqueue／其余读路径）），探针覆盖 9 格缺陷格＋2 格对照（NL-10／NL-11）＋1 格 Flask 对照。Flask 面对照：BA（R14-P2-1）已修完——`agent_poll` 的 `ids` 非列表按 `[]` 处理、`_enqueue_command` 丢弃非列表段＋审计；本轮 Flask 对照探针亲手重跑：poll 200、enqueue 202、段重建为列表。**不是 R14-P2-1 的复发**——那条登记的是 Flask 面（已修、本轮对照仍关）；本条是同一“容器形状”机制在 Worker 面的新一层，谓词不同（面不同）、既往轮次从未审过 Worker 的容器形状（R18 矩阵 T7／T11 只审了记录形状与读写竞态）。

**行为复现（探针 `tests/r19_worker_nonlist_container.mjs`，12 格，9 格红＝缺陷复现）：**NL-01 poll queue=字符串＋孤儿 → 500；NL-02 poll queue=字符串无孤儿 → 500；NL-03 poll queue=对象＋孤儿 → 500；NL-04／NL-05 poll sent=字符串／对象 → 500；NL-06 enqueue 于 queue=字符串 → 500；NL-07 report queue=字符串＋孤儿 → 500；NL-08 revoke queue=字符串＋孤儿 → 500（节点未删）；NL-09 cmd_get queue=字符串＋孤儿 → 500；对照 NL-10 正常列表 queue 下发一次、NL-11 非对象 cmd 记录 poll 200（sweep 隔离在位）。

**后果与定级：**定 P2：只对手改 KV 可达（API 写不出非数组容器值，与 R14-P2-1 同可达性）；无错误执行、无崩溃进程（顶层 catch 回 500 JSON）；但 agent 的 poll 轮轮 500 → 该节点命令通道卡死、面板显示 500 诚实但不自愈——sweep 自身先抛，无法自愈，必须手工修 KV；且 Q1 的 enqueue 500 已把 cmd 记录写盘（孤儿 queued 记录，靠后续 sweep 救回——本轮 dbg 实测：500 后下一次 poll 的 sweep 重入队并下发）。与 R14-P2-1 同级同因，定 P2。

**修法方向：**Flask BA 同款——在全部 6 处 `queue:`／`sent:` 读点加 `Array.isArray` 归一化（非数组按 `[]` 处理＋`console.warn` 记容器形状，不写内容）；`enqueueCommand` 归一化后 push；sweep 的 fallback 读同样归一化；孤儿 queued 记录由既有 sweep 回收。探针 NL-01～NL-09 须翻转为 200／202。

### R19-P2-2（P2）Worker .ovpn 下载不查吊销／过期

**机制谓词：**下载 .ovpn 前须查用户当前状态，revoked／expired 一律 403。

**机制（代码面实读）：**Worker 专用下载路径 `handleCompatOvpnDownload`（index.js:1110-1123）只读 `ovpn:<node>:<name>` 回执、有即 200，全程不读快照 `users`。回执写点唯一（:933，create_user done 时 `kvPutJson` 无 `expirationTtl`，永不过期）；删除点全树 0 处——吊销用户（`revoke_user` 只入队，agent 侧吊销证书）不删回执，节点吊销删的是 node／queue／sent／status 四键，不含 `ovpn:` 键。快照里本有用户状态：`snapshotFromResult` 原样复制 `result.users`（agent `get_status` 的 `list_users()`，每条含 `status` ∈ valid／revoked／expired，core:451／:465），`handleCompatUsers` 读同一快照——下载路径是唯一不查它的读路径。

**行为复现（探针 `tests/r19_worker_ovpn_download.mjs`，8 格，2 格红＝缺陷复现）：**DL-02 有效用户 200；DL-03 快照 users 标 revoked 后下载仍 200（应 403）；DL-04 expired 后下载仍 200（应 403）；DL-05 改回 valid 后 200；DL-06 无回执用户 404。Flask 对照：R13-P2-3 已修（AW 的 `_download_block_reason`，三条路径共用），live-10 §9 P2-3 真机复核：吊销／过期三条路径均 403。

**后果与定级：**定 P2：吊销后私钥材料仍可下载（吊销不等于收回凭证）；但证书已进 CRL，OpenVPN 握手会拒（`crl-verify`），下载本身不授予接入——与 R13-P2-3 同级同因。**不是 R13-P2-3 的复发**——那条登记的是 Flask 面的 `node_user_ovpn`（已修、本轮对照仍关）；本条是同一“下载守卫”机制在 Worker 面的新一层，谓词不同（面不同）、既往轮次从未审过 Worker 下载路径的吊销检查。

**修法方向：**`handleCompatOvpnDownload` 下发前读快照 `users`，同名用户 `status` 为 revoked／expired 即 403（文案与 Flask `_download_block_reason` 同款）；无快照／无该用户条目时放行（与 Flask `_snapshot_users` 回空 dict 时放行同款，AW 的快照滞后 caveat 同样适用）。探针 DL-03／DL-04 须翻转为 403。


## §4 套件重跑汇总（本轮亲自重跑）

| 套件／门禁 | 结果 | 说明 |
|---|---|---|
| R17 Flask 套件 `tests/r17_flask.py`（89 格） | **86/89** | 仅预期 OBSERVED 三格红：F4-02b／F4-13／F4-15——三格断言的是**修复前的缺陷行为**（poll 下发已失败命令、受理 queued 回执），BG 修完后该行为已不存在，故断言翻红；BG 回归探针 22/22 全绿为证。本轮数与 R18 一致 |
| R17 Core 套件 `tests/r17_core.py`（46 格） | **46/46** | 含 C1-08 OBSERVED（dns 字符集校验）绿 |
| R17 Agent 套件 `tests/r17_agent.py`（33 格） | **33/33** | 全绿 |
| R17 Worker 套件 `tests/r17_worker.mjs`（35 格） | **33/35** | 仅预期 OBSERVED 两格红：W5-05／W5-06a——两格断言的是**修复前的缺陷行为**（重复下发已 sent 命令、受理 queued 回执），BH 修完后该行为已不存在，故断言翻红；BH 回归探针 20/20 全绿为证。本轮数与 R18 一致 |
| BG 回归探针 `tests/r18_bg.py`（22 格） | **22/22** | 无退化 |
| BH 回归探针 `tests/bh_worker_poll_guard.mjs`（20 格） | **20/20** | 无退化 |
| BI 竞态／畸形探针（§1.1） | 15/15、18/18 | 见 §1 |
| R19 新探针（§3） | 非列表容器 3/12（9 格红＝缺陷复现）；下载 6/8（2 格红＝缺陷复现） | 缺陷探针，待修复后翻转 |
| 门禁 `verify-integration.sh`（29 格） | **29/29，FAIL=0，SKIP=0** | 机械推导：`ok "` 文本 31 处，减 1（`check()` 辅助函数定义内的一处，该函数全树无调用点）再减 1（`/etc` 两分支互斥，单次运行只取其一）＝29 格，与运行时汇总一致 |

**重跑过程注（harness 缺陷，非产品缺陷）：**① R17 Flask 套件 docstring 写 `OVPN_CA_DIR`／`OVPN_SERVER_DIR`，但 app.py:135-136 实际读 `OPENVPN_CA_DIR`／`OPENVPN_SERVER_DIR`——按 docstring 跑会落回 `/etc` 默认路径，F2/F5 共 11 格假红；按真实变量名＋`OVPN_SK5_CONFIG_DIR` 重定向后复绿。② R17 fixture-server 的 server.conf 被往轮套件自身的 C1-13／F2-06 渲染残留为 `port 51194`，Core 套件首跑因此假红 5 格——重置为 `port 1194` 后 46/46。③ Flask 套件须用新鲜 data dir（旧库使 `_ensure_admin_password()` 返回空而断言失败）且 fixture-server 须 chown 给 nobody（root 属主文件上 render 的 chmod 致 EPERM）。三处均为探针夹具／文档口径问题，已记明，不立案；套件 docstring 的变量名错字建议随下轮修复顺手改（不另立案）。

### §4.1 门禁 §7 变异红证（BE 第二层，本轮亲手重跑）

变异构建器 `tests/build-mutants.py`（7 棵，干净树 `/tmp/r19/clean`）：

| 变异树 | 门禁整跑 | §7 隔离复核 | 结论 |
|---|---|---|---|
| m-dict-sb（字典 sing-box 两项值互换，常量不动） | 28/1 | 仅 §7 红 | 恰红 ✓ |
| m-dict-ts（字典 tun2socks 两项值互换） | 28/1 | 仅 §7 红 | 恰红 ✓ |
| m-dict-missing（字典缺 tun2socks arm64 项） | 28/1 | 仅 §7 红 | 恰红 ✓ |
| m-dict-extra（字典多一项 bogus 5th） | 28/1 | 仅 §7 红 | 恰红 ✓ |
| m-const-sb（常量值互换，字典不动） | 28/1 | 仅 §7 红 | 恰红 ✓ |
| m-install-sb（install.sh 赋值互换） | 28/1 | 仅 §7 红 | 恰红 ✓ |
| m-char（agent.py amd64 常量一位 hex 改动） | 28/1 | 仅 §7 红 | 恰红 ✓ |

红格文本已逐棵核对，均为“钉死哈希不一致：install.sh 与 agent/agent.py 的 sha256 逐键不等”。干净树 §7 隔离复核绿。**BE 的 §7 两层（常量值逐键＋字典绑定）本轮验活。**

## §5 P0-1/2/3：真实 wrangler deploy 重验

- `npx wrangler deploy --dry-run`：exit 0（同 R15–R18）。
- `npx wrangler deploy`（真实部署）：**exit 1**——`In a non-interactive environment, it's necessary to set a CLOUDFLARE_API_TOKEN environment variable for wrangler to work`（未登录，非交互环境无 token）。
- `cloudflare/wrangler.toml:32-33`：KV `id` 与 `preview_id` 仍为占位符（`REPLACE_WITH_KV_NAMESPACE_ID`／`REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`），与 R18 相同。
- 结论：**P0-1（真实 Worker 部署）／P0-2／P0-3 仍未验**——与 R18 §5 相同，需用户创建 Cloudflare API token 或做交互式 `wrangler login`（已问五次未复）。Worker 面的全部结论（含 §1 的 BI 验证与 §3 的两条新发现）均以沙箱 MockKV 探针为准，真机部署态仍以 dry-run／mock 为上限，见 §7。

## §6 文档宣称全量核对（9 份交付文档）

- **flmx-reference 32+3 行**：`/tmp/r16/flmx-verify.py` 重跑，36 行输出，**0 行“假改”／“不符”**，DONE。残留的 5 行标注（3-6 核查、3-7／3-8 存疑、3-9 部分抄、1-16 部分抄）与 R18 相同，均为 BD（R15-P2-2）留下的诚实标注，无新增漂移。
- **过期标识 grep**：`SCRIPT_VERSION`／`resolve_version` 在散文（排除 audit 与历史 live 报告）中 **0 命中**；`28/28`／`PASS=28` 在散文（同口径排除）中 **0 命中**；门禁计数在 9 份文档中现为 29 格口径（`egress/README.md:210` 记 `verify-integration 29/29`）。
- **Worker“55 项”**：BD 已改为 56，无残留。
- 结论：文档面无新差集。R19-P2-1／P2-2 的修法须同步更新 `cloudflare/README.md` 的 Worker 行为表（队列容器归一化、下载吊销检查）——修法路责任，不另立案。

## §7 前端对比度核查

- `python3 panel/static/contrast-check.py`：**10/10 PASS**（底线 4.5），目标 7 达成 **4/10**——与 live-9／live-10／live-11／live-12 的真渲染数一致（10/10、4/10）。

## §8 历史台账复扫（152 条）

复扫基线：R18 台账 150 条（145 已修、2 部分、1 未验）＋BI 关闭 R18 的 2 条＋R19 新增 2 条＝152 条。台账算术：150 条的构成以 R18 §8 为准（本轮未重建逐条清单——R18 的台账是十八轮的累计账本，逐条重建须通读 R1–R18 全部报告与 live-1–live-11 全部记录；本轮复扫以 mtime 规则＋行为抽查重验＋live-12 对账三法核现状，差集只增不减）。本轮增量：BI 关闭 2 条（§1 行为重验＋定点变异红证）、R19 新增 2 条（§3 行为复现探针）。复扫方法：mtime 规则（除 index.js 外无文件变动，既往结论沿用）＋本轮行为重验（§1、§4）＋live-12 对账（本节末）。

| 段 | 条数 | 本轮现状 |
|---|---|---|
| R1–R18 历史已修 | 147（含 BI 关闭的 R18-P2-1／P2-2） | 全部仍关，无一复发。抽查重验：R17-P1-1（BG 22/22、BH 20/20、R17 四套件仅预期 OBSERVED 红）、R16-P2-1（门禁 §7 7 棵变异逐棵 28/1 仅 §7 红）、R15-P2-1／P2-2（门禁 29/29、flmx-verify 0 假改）、R14-P2-1（Flask 对照探针 poll 200／enqueue 202）、R13-P2-3（Flask 下载吊销／过期三路径对照仍关，见 §3.2） |
| 部分（按设计） | 2（P0-3 bundle／install-agent.sh 部署态、P1-7 首次登录强制改密） | 状态不变，文档诚实记账 |
| 未验 | 1（P0-1 真实 Cloudflare 部署） | 仍未验，见 §5 |
| R19 新发现 | 2（P2-1、P2-2） | 待修复，见 §3 |
| **合计** | **152** | **147 已修、2 部分、1 未验、2 新，零复发** |

### §8.1 live-12 对账（R16-P2-1＋R17-P1-1 真机格）

live-12 已完工（`docs/live-verify-R12.md`，178 行，2026-11-12 03:20，本轮审计期间完工、全文已通读）：**全部通过、零新 bug**——14 格全过。R16-P2-1：门禁 §7 两层真机上干净树 PASS、两棵字典互换树仅 §7 格红；amd64 后果格双二进制均 fail-closed 拒绝安装；arm64 格未验（无 arm64 机）。R17-P1-1 Flask 面：(a) failed init_pki poll 不下发、CA 序列号前后一致、agent 日志 init_pki 0 次；(b) queued 回执 409 拒收、仍 queued、随后 poll 合法下发翻 sent；(c) 正常命令下发一次翻 sent、第二轮 poll 不重复。Worker 面未验（无真实部署）。S0–S4 全过（S0 首次安装死转发健康门一次、重跑通过，记瞬态不立案，AZ 同款先例）；headline 精选全过（首启 200＋10 交替 delta 恰 10、并发启用 delta 恰 1、policy-missing 两次诚实＋零重起修复、verify.sh 开 18/0/4 关 23/0/0、前端 0 低于 4.5、毒树重跑行级比对全一致）。**live-12 对账通过，无新立案。**

### §8.2 live-13 待办（R18 的 2 条真机格）

R18-P2-1 与 R18-P2-2 的真机格（Worker 面，无真实部署）记为**沙箱格＋live-13 补**：live-13 已派出（03:21），真机补验轮（R18 的 2 条 mock-KV 格机上跑＋R18 复现探针翻转核对＋BG 探针机上跑＋S0–S4 回归＋headline 精选）。本轮不默写 live-13 结论；R19 的 2 条新发现的真机格同样待 live-13（或其后轮）补验。

## §9 结论

**不能交付（差集 2 条，均为 P2）。**

| # | 级别 | 条目 | 机制谓词 | 修法 |
|---|---|---|---|---|
| R19-P2-1 | P2 | Worker queue／sent 容器值非数组时读／写路径 500（9 格红） | 容器非数组时读／写路径不得 500，须按空处理＋隔离 | 6 处读点 `Array.isArray` 归一化（Flask BA 同款）；探针 NL-01～NL-09 翻转 |
| R19-P2-2 | P2 | Worker .ovpn 下载不查吊销／过期（2 格红） | 下载前须查用户当前状态，revoked／expired 一律 403 | `handleCompatOvpnDownload` 读快照 users 守卫（Flask AW 同款）；探针 DL-03／DL-04 翻转 |

修完须按第一前提①再做一轮全量全局回头看（AUDIT-R20，换推导方法）＋live-13 对账，两路都过才交付。P0-1／P0-2／P0-3 的真实部署验证仍待用户决断（Cloudflare API token 或交互式 `wrangler login`，已问五次未复）；若用户始终不启用，交付文档须把 Cloudflare 模式部署态标为未验。

# AUDIT-R18 — 全量全局回头看（交付前，第六轮）

## 结论先写

**结论：不能交付。差集 2 条（均为 P2）：R18-P2-1（Worker 队列 read-modify-write 竞态，poll 期间下发的命令永久丢失）、R18-P2-2（Worker 面无畸形 sweep，手改 KV 的畸形记录永不落 failed）。**

历史 150 条：145 已修、2 部分（P0-3、P1-7，按设计）、1 未验（P0-1 真实部署态）、2 本轮新开；**无一复发**。本轮新发现 2 条（见 §3），均带机制谓词＋机械推导的全集清单＋行为复现探针（均已落 `tests/`）。

- 审计员：独立审计路（未参与建设与修复路 BG/BH；单审计员边做边写，不派子代理）
- 日期：2026-11-13（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R17 同等广度）
- 推导方法：**命令生命周期状态机转移闭合**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性、R9 对抗操作员＋时间衰变、R10 环境矩阵×修复存活、R11 契约闭合、R12 外部输入枚举、R13 部署生命周期、R14 证据优先行为复推导、R15 交付文档驱动用户旅程重演、R16 门禁与证据链反向审计、R17 爆炸半径 FMEA 均不同）——把命令队列状态机（queued／sent／done／failed 四态）× 事件（poll 下发／report 回执／超时重投／sweep 隔离／超时标失败／手动重发／吊销清理）× 两面（Flask／Worker）的全部转移画成矩阵，逐格验证：转移是否被守卫、是否落审计、是否只能由合法事件触发、是否存在非法转移路径（任一态经任一事件到达非法态即立案）。R6 审的是 via_sk5／面板状态，本轮只审命令生命周期，二者不重叠；R17 的 FMEA 结论只作输入，不作本轮证据。
- 测试一律在 `/tmp` 副本上跑；未动项目原文件（除本报告）；门禁自带 harness（venv＋桩 sing-box/systemctl/ip，面板以 nobody 跑）；未动任何真机。需真机行为复核的项一律写“待 live-12”或对账 live-11，不提前判通过。
- 语法基线：4 个 Python 文件 `py_compile` 全过，7 个 shell 脚本 `bash -n` 全过，Worker `node --check` 通过（见 §0）。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明（与 R9–R17 同款记明）。

## §0 树版本与 BG/BH 改动确认

当前树是 R17 修复路 BG＋BH 之后的新树。文件 mtime（UTC）与 R17 §0 基线对照：

| 文件 | mtime (UTC) | 行数 | sha256（前 12 位） | 说明 |
|---|---|---|---|---|
| verify-integration.sh | 2026-11-12 18:14:53 | 630 | 6ef6ba2db8b1 | 未动（R17 mtime，BE） |
| README.md | 2026-11-12 17:56:09 | 287 | 6154ecabe046 | 未动（R17 mtime） |
| panel/app.py | 2026-11-12 18:38:12 | 2754 | 204de1136cc5 | **动过（BG：poll 循环顶加 `status != "queued": continue`＋report 加 sent 态守卫；与主控核验的 sha256 一致）** |
| core/openvpn_manager.py | 2026-11-12 17:20:57 | 1550 | 3b5d7dfe9ea1 | 未动（R17 mtime，BB） |
| agent/agent.py | 2026-11-12 16:46:20 | 922 | 7f999298df5b | 未动（R17 mtime，AX） |
| install.sh | 2026-11-12 16:46:54 | 1082 | 3f050f037e7a | 未动（R17 mtime，AZ） |
| cloudflare/src/index.js | 2026-11-12 18:37:24 | 1234 | 7fe561e5a94f | **动过（BH：push 移进 queued 守卫＋report 加 sent 态守卫）** |
| panel/templates/index.html | 2026-11-12 15:21:57 | 1259 | 4f7dc697451c | 未动（R17 mtime） |
| verify.sh | 2026-11-12 14:45:28 | 846 | 7867f557c6bb | 未动 |
| egress/sk5_manager.py | 2026-11-12 12:37:13 | 1109 | 02de9d8a4908 | 未动 |
| egress/policy-routing.sh | 2026-11-12 12:13:01 | 364 | 103a121bbdfe | 未动 |
| panel/data/ | 2026-11-12 12:14 | 空目录 | — | AE 路清空后仍空 |

语法基线（本轮实测）：4 个 Python 文件 `py_compile` 全过（panel/app.py、egress/sk5_manager.py、core/openvpn_manager.py、agent/agent.py）；7 个 shell 脚本 `bash -n` 全过（install.sh、verify.sh、verify-integration.sh、egress/test-egress.sh、egress/policy-routing.sh、core/easyrsa.sh、agent/install-agent.sh）；Worker `node --check cloudflare/src/index.js` 通过。

/tmp 资产现状（本轮开工时实测）：R16／R17／R16-BE 的资产均幸存（`/tmp/r17/`、`／tmp/r16/`、`／tmp/r16-be/`、`／tmp/r18-verify/`——主控核验 BG 时建的 venv＋ptree 亦在）；R13/R14/R15 的探针仍失。探针资产以树内 `tests/` 为准（R17 落地，BG/BH 各添一探针）。

## §1 BG/BH 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

### §1.1 BG/BH 探针亲手重跑（新树 `/tmp/r18/ptree` 副本＋新 venv `/tmp/r18-verify/venv`，Flask 3.1.3＋bcrypt）

| 探针 | 结果 | 说明 |
|---|---|---|
| `tests/r18_bg.py`（BG，Flask 面） | **22/22** | 含 poll 守卫格 BG-01/02/03/08、report 守卫格 BG-04/04b/05/05b/10 |
| `tests/bh_worker_poll_guard.mjs`（BH，Worker 面） | **20/20** | 含 poll 守卫格 BH-01/02/07、report 守卫格 BH-03a/03b/03c/06b/06c |

### §1.2 定点回退变异红证（只回退 R17-P1-1 的修复，变异构建器 `/tmp/r18/build-reverts.py`）

每棵变异树只恢复修复前的 exact 形状（Flask：`if status == "queued"` 包 sent 翻转、append 在守卫外；Worker：同形 push 在守卫外；report 守卫拆除），不做守卫删除式粗暴变异：

| 变异树 | 探针结果 | 红格 | 结论 |
|---|---|---|---|
| m-flask-poll | 18/22 | BG-01/02/03/08（恰为 poll 守卫格） | 恰红 ✓ |
| m-flask-report | 17/22 | BG-04/04b/05/05b/10（恰为 report 守卫格） | 恰红 ✓ |
| m-worker-poll | 17/20 | BH-01/02/07（恰为 poll 守卫格） | 恰红 ✓ |
| m-worker-report | 15/20 | BH-03a/03b/03c/06b/06c（恰为 report 守卫格） | 恰红 ✓ |

Worker 两棵合计红 8 格，与 BH 报告的修复前翻转数 12/20（8 守卫格恰红）一致。Flask 两棵合计红 9 格，BG 报告的修复前基线为 8 红——差 1 格：回退树红格含 BG-04b，BG 探针将其列为 report 守卫格（见 §1.1），属守卫格族内、无超范围红格；两数在同一量级。

### §1.3 R17 四套探针在新树上重跑（`R17_TREE=/tmp/r18/ptree`）

| 套件 | 结果 | 说明 |
|---|---|---|
| Flask `tests/r17_flask.py` | **86/89** | 3 红恰为 F4-02b/F4-13/F4-15——三个钉死旧缺陷的 OBSERVED 格，按预期翻转：F4-13 下发列表为空；F4-15 回 409“命令未下发（status=queued），回执不予接受” |
| Core `tests/r17_core.py` | **46/46** | 全绿 |
| Agent `tests/r17_agent.py` | **33/33** | 全绿 |
| Worker `tests/r17_worker.mjs` | **33/35** | 2 红恰为 OBSERVED 格 W5-05（detail `[]`，陈旧 poll 不再重下发）与 W5-06a（detail 409，queued 回执被拒）；W5-01 已转绿 |

**探针路径陷阱再命中（与 R13/R14 同族，已绕过并记明）：**`tests/r17_worker.mjs` 硬编码绝对 import `/tmp/r17/ptree/cloudflare/src/index.js`（修复前树），直接跑会在旧代码上复现 W5-01。本轮把 import 重定向到 `/tmp/r18/ptree/cloudflare/src/index.js` 的副本（`/tmp/r18/r17_worker_current.mjs`）跑新树，33/35 为新树实测数。Flask/Core/Agent 探针取 `R17_TREE` 环境变量，置位后安全。

### §1.4 门禁 29/29（干净树）与 §7 变异红证

干净树门禁：`bash verify-integration.sh` **29/29，exit 0**（约 20 秒，`/tmp/r18/gate-clean3.log`）。但须诚实记账：本轮前两次门禁跑均以 SKIP 收尾（第 1 次“建 venv 失败”，第 2 次 8443 检查时刻被占——30 秒后 `ss` 显示无监听、无面板进程），两次 SKIP 均诚实（PASS=0，exit 0，无假绿），但“一次过”的闭合性不严密，记为观察、不立案。

§7 第二层（BE 的字典绑定）变异红证：`tests/build-mutants.py`（R17 构建器）从当前树重建 7 棵变异树（`/tmp/r18/mutants/`：m-dict-sb、m-dict-ts、m-dict-missing、m-dict-extra、m-const-sb、m-install-sb、m-char），逐棵跑门禁：

| 变异树 | 门禁 | 红格 | 结论 |
|---|---|---|---|
| m-dict-sb（字典 sing-box 两项值互换，常量不动） | 28/1 | 仅 §7 | R16-P2-1 关闭 ✓ |
| m-dict-ts（字典 tun2socks 两项值互换） | 28/1 | 仅 §7 | ✓ |
| m-dict-missing（字典缺一项） | 28/1 | 仅 §7 | ✓ |
| m-dict-extra（字典多一项） | 28/1 | 仅 §7 | ✓ |
| m-const-sb（常量 sing-box amd64/arm64 互换） | 28/1 | 仅 §7 | R15-P2-1 关闭 ✓ |
| m-install-sb（install.sh 侧互换） | 28/1 | 仅 §7 | ✓ |
| m-char（某哈希改一位） | 28/1 | 仅 §7 | ✓ |

7 棵逐棵 28/1、仅 §7 红，BE 的 §7 两层（常量值逐键＋字典绑定）均验活。另：R16-P2-1 的运行时后果本轮未重测（`_pinned_sha256("sing-box","amd64")` 在变异树上取错值），因门禁 §7 红证已覆盖同一谓词、且 agent.py 自 R17 后未动（mtime 规则），不重复造数。

### §1.5 R17-P1-1 关闭判定

BG＋BH 两路修复经本轮亲手重跑（22/22＋20/20）、四棵定点回退变异恰红、R17 四套探针按预期翻转（86/89＋46/46＋33/33＋33/35，红格全为 OBSERVED 旧缺陷格）、干净树门禁 29/29：**R17-P1-1 已修，关闭**。历史计数进 §8。

## §2 命令生命周期状态机转移闭合矩阵（本轮推导方法）

状态集：`queued／sent／done／failed`（另有“机外态”畸形态：缺 status／未知 status／非对象记录／sent_at 非数值）。事件集：poll 下发／report 回执／超时重投／sweep 隔离／超时标失败／手动重发／吊销清理／agent 崩溃（无回执）。每格结论＝本轮代码面实读＋探针行为复现；未动文件（自 R17 后 mtime 一致）的既有转移按 mtime 规则沿用 R12–R17 证据，不冒充重跑。

| # | 转移（from --事件--> to） | Flask 面 | Worker 面 | 闭合 |
|---|---|---|---|---|
| T1 | queued --poll--> sent | ✓ 守卫：`agent_poll` 循环顶 `status != "queued": continue`（app.py:2526，BG） | ✓ 守卫：`if (cmd.status !== "queued") continue`（index.js:639，BH） | 闭合。探针 BG-01/02/03/08、BH-01/02/07 |
| T2 | queued --report--> done/failed | ✗ 409＋审计 `agent_report_not_sent`（BG） | ✗ 409（BH-03a/03b/03c） | 闭合（非法转移已堵） |
| T3 | sent --poll--> sent（重复下发） | ✓ 守卫跳过（下发即离队） | ✓ 守卫跳过；W5-05 detail `[]`（陈旧 poll 不重下发） | 闭合 |
| T4 | sent --report--> done/failed | ✓ 唯一合法回执路径（BG-04b/05b） | ✓ 唯一合法回执路径（BH-06b/06c） | 闭合 |
| T5 | sent --timeout--> queued（重投） | ✓ 任意动作，retries+1，上限 3（`_requeue_stale_sent` app.py:662；SENT_TIMEOUT_SECONDS=120） | ✓ 仅 `SAFE_RETRY_ACTIONS` 7 动作（get_status／test_sk5／enable／disable_sk5／start／stop／restart_openvpn），retries+1，上限 3（index.js:594-630；SENT_TIMEOUT_MS=120000） | 闭合。分歧见观察 O1（R5 已裁定） |
| T6 | sent --timeout--> failed | ✓ retries>3 时标 failed（任意动作） | ✓ retries>3（SAFE 动作）或首超时（非 SAFE 动作）即标 failed | 闭合 |
| T7 | queued/sent --sweep--> failed（畸形隔离） | ✓ `_fail_malformed_cmds` 在 6 处读路径（enqueue :532、revoke :2350、cmd_create :2429、cmd_get :2492、poll :2549、report :2608），覆盖非对象／缺键／sent_at 不可解析（R12-P1-1／R13-P2-1／R14-P2-1） | ✗ **无 sweep**——全树 `status = "failed"` 写点仅 3 处（吊销 :518、重投超限 :607、非幂等超时 :620），无任何畸形标记路径 | **不闭合 → R18-P2-2** |
| T8 | done/failed --poll/report--> * | ✓ 守卫（BG；F4-13 下发列表为空、F4-15 回 409） | ✓ 守卫（BH；W5-01、W5-06a） | 闭合 |
| T9 | done/failed --手动重发--> * | 无此端点（全树 grep `resend／重新下发` 零命中，app.py／index.js／index.html） | 同左 | 闭合（缺失即终态；恢复靠新 enqueue 拿新 id） |
| T10 | * --revoke--> 删除 | ✓ 先 sweep 再 DELETE（BA），节点行＋队列＋命令同删 | ✓ queued/sent 先标 failed“节点已吊销”，再删 node/queue/sent/status 四键（index.js:507-530） | 闭合（但畸形记录不在 revoke 标记范围内，见 P2-2） |
| T11 | queued --poll 期间 enqueue--> 丢失 | ✓ `_QUEUE_LOCK` 覆盖 load→save 全程；单进程（`app.run(...)`，无 workers／fork） | ✗ **无锁无 CAS 无版本号**：poll 读队→处理→末尾无条件 `queue:<name> = []`（:651），enqueue 读→push→写回（:294-296） | **不闭合 → R18-P2-1** |
| T12 | sent --agent 崩溃--> （无回执） | → T5/T6 超时路径 | → T5/T6 超时路径 | 闭合（agent `run_once` 顺序执行，单次回执；回执丢失即走超时） |
| T13 | sent --poll--> queued --poll--> sent（同轮重投重发） | ✓ 同轮内先重投后下发（M-04 对照格：retries=1 且同轮重发） | ✓ 同左（index.js 注释“安全动作自动回队，本次 poll 即重发”） | 闭合（合法复合转移） |
| T14 | 机外态（畸形记录）--任意事件--> failed | ✓ T7 sweep（6 路径） | ✗ 无路可达 failed；仅 CMD_TTL_S（7 天）到期删记录，或吊销时删队列键（记录本身仍滞留至 TTL） | **不闭合 → R18-P2-2** |

### §2.1 观察（已核实，不立案）

- **O1（R5 裁定重申，不重议）：**Flask `_requeue_stale_sent` 重投全部动作（含非幂等 init_pki／create_user），Worker 只重投 `SAFE_RETRY_ACTIONS`——分歧见 `docs/security.md:12`，R5 已裁定按设计。agent 侧无幂等防护（`action_init_pki` agent.py:606 恒以 force+confirm 重建 CA；`create_user` 重复执行诚实失败）。超时重投本身有上限（两面 SENT_MAX_RETRIES=3），不存在无限循环。
- **O2（门禁 SKIP 诚实记账）：**干净树门禁第三次跑才 29/29（见 §1.4）；前两次 SKIP 均诚实（PASS=0，exit 0），但“一次过”闭合性不严密。门禁脚本本身无假绿，不立案。
- **O3（live-11 打包 14 分 48 秒）：**距 15 分钟树稳定门差 12 秒，但传包完成时已过门、其间树无变动，内容等价于过门后打包；过程偏差已由 live-11 诚实披露，不立案。

## §3 新发现

### R18-P2-1（P2）Worker 队列 read-modify-write 竞态：poll 期间下发的命令永久丢失

**机制谓词：**每一个 `queued` 命令必须保持可下发——队列数组是唯一派发源，任何丢弃 id 却不改记录状态的写都会破坏状态机闭合。

**机制（代码面实读）：**`handleAgentPoll`（index.js:589 读 `queue:<name>`，:651 无条件 `queue:<name> = []` 清空）与 `enqueueCommand`（:294 读、:295 push、:296 写回）都对 `queue:<name>` 做 read-modify-write，无锁、无 CAS、无版本号。若 enqueue 的写落在 poll 的清空写之前，该 id 即丢失。全树写点枚举（机械推导，全集 4 处）：enqueueCommand（:294-296）、handleAgentPoll 读／清（:589／:651）、handleRegisterNode（:492 注册时初始化 `[]`）、handleRevokeNode（:524 删除键）。仅前两处是存活期的 read-modify-write 路径。

**行为复现（探针 `tests/r18_worker_queue_race.mjs`，9 格全 PASS＝缺陷复现）：**MockKV 拦截钩子做确定性交错（poll 读队列的瞬间快照旧值、在其内跑完一轮完整 enqueue，使 poll 返回旧值）：A 已下发、B 在 poll 窗口内下发 → 之后 3 轮 poll 均取不到 B，记录永久卡 `status=queued`，队列数组 `[]` 不再引用 B。对照格：poll 完成后再下发 → 正常下发（顺序依赖＝真竞态，非确定性 bug）。

**后果：**卡住的命令静默无错、无审计、无自愈，除吊销节点外无恢复路径——无孤儿回收器（`_requeue_stale_sent`／Worker sent 循环只处理 sent 态；sweep 只标畸形，见 P2-2；手动重发产生新 id，僵尸仍 queued 至节点寿命终结）。若丢失的是 init_pki／create_server，管理员的部署动作静默卡死。定 P2 不定 P1：无错误执行、面板诚实显示 queued（卡住而非撒谎）、重下一条新命令可恢复。

**Flask 面安全（已验证）：**单 Python 进程（`ExecStart=/usr/bin/python3 .../run-panel-tls.py`，`app.run(...)`，无 workers／fork），`_QUEUE_LOCK` 覆盖 poll／enqueue／report／revoke／cmd_get 全程 load→save。

**既往轮次盲区：**R8 并发审计覆盖 enable／disable、策略路由、set_sk5（Flask／egress 面），`enqueueCommand`／`handleAgentPoll` 在 R8／R16 中 0 命中、R11 仅 1 处过路提及；U-9“KV 竞态与 POP 传播”是跨 POP 最终一致性，机制不同，仍未验。

**修法方向：**poll 的清空改为条件式（只清本次实际读到并下发的 id，如 filter-then-write 或重读 diff），或把 enqueue 与 poll 串行化（KV 锁／版本号），另加孤儿回收器（queued 记录无队列引用即重接入队）；探针 RACE-04/05/06 须翻转为“B 已下发”。

### R18-P2-2（P2）Worker 面无畸形 sweep：手改 KV 的畸形记录永不落 failed

**机制谓词：**每条命令记录必须能经合法事件到达终态（done／failed）；任何记录不得滞留在四态之外，且不得只靠 TTL 删除“解决”。

**机制（代码面实读＋机械推导）：**Worker 面 `status = "failed"` 写点全集只有 3 处（index.js:518 吊销、:607 重投超限、:620 非幂等超时）；“sweep”一词全树仅出现在 :636 的注释里，无任何畸形标记函数。Flask 面对照：`_fail_malformed_cmds`（app.py:552）在 6 处读路径上把畸形命令标 failed＋审计（enqueue :532、revoke :2350、cmd_create :2429、cmd_get :2492、poll :2549、report :2608）。面×属性矩阵：sweep 存在 Flask ✓／Worker ✗；sent_at 不可解析处理 Flask ✓（R13-P2-1 已修，`_requeue_stale_sent` 防御性跳过）／Worker ✗（见下）。

**全集清单（畸形形状 × 出路，机械枚举）：**

| # | 畸形形状（须手改 KV 直达，API 造不出） | 出路 |
|---|---|---|
| S1 | cmd 记录缺 `status` | 无。poll 跳过（`!== "queued"`）、report 409、revoke 跳过（只标 queued／sent）→ 滞留至 CMD_TTL_S（7 天）删记录 |
| S2 | cmd 记录 `status` 为未知串（如 `"bogus"`） | 同 S1（探针 M-02：poll＋report 后仍 `"bogus"`） |
| S3 | cmd 记录非对象（如字符串 `"hello"`） | 同 S1（探针 M-06：poll 200 不崩，记录原样滞留） |
| S4 | sent 条目 `sent_at` 非数值（如 `"abc"`） | 重投永不触发：`now - "abc"`＝NaN，`NaN > 120000` 恒假 → sent 态卡住、retries 恒 0；连 `handleGetCmd` 的 timeout_hint 也因同一 NaN 失效（探针 M-03） |
| S5 | sent／queue 条目引用已删 cmd id | 自愈：重投循环 `!cmd → continue`、下发循环 `!cmd → continue`、队列随即清空（无审计，属静默清理但无害） |

**行为复现（探针 `tests/r18_worker_malformed.mjs`，13 格全 PASS＝缺陷复现）：**M-01 缺 status：poll 不下发、poll 后仍无 status（未标 failed）；M-02 `"bogus"`：poll 不下发、report 409、之后仍 `"bogus"`；M-03 sent_at `"abc"`：poll 后仍 sent、retries 恒 0、timeout_hint 缺失；M-06 非对象：poll 200 不崩、记录原样滞留。对照格 M-04（数值型过期 sent_at，SAFE 动作）：同轮 poll 重投＋重发、retries=1；M-05（数值型过期 sent_at，非幂等动作）：首超时即标 failed——证明超时路径本身工作，S4 是 NaN 专属缺口。

**后果与定级：**定 P2：无错误执行、无崩溃（M-06 poll 200）、面板显示记录真实状态（卡住而非撒谎）；但一条僵尸记录可占位至 7 天 TTL，且无审计、无 failed 标记、无孤儿回收；吊销节点也救不了它（revoke 只标 queued／sent，畸形记录连吊销标记都吃不到，只删队列键、记录本身仍滞留至 TTL）。**不是 R12-P1-1／R13-P2-1／R14-P2-1 的复发**——那三条登记的都是 Flask 面（且均已修、本轮复核仍关）；本条是同一“畸形记录”机制在 Worker 面的新一层，谓词不同（面不同）、既往轮次从未审过 Worker sweep 的存在性。

**修法方向：**Worker 侧加与 `_fail_malformed_cmds` 同款的 sweep（poll／report／cmd_get 读路径先扫：非对象／缺 status／未知 status → failed＋审计；`sent_at` 以 `Number()` 强制数值化，NaN 按 0 计使超时路径正常触发），另加孤儿回收器（queued 记录无队列引用即重接入队，与 P2-1 同一回收器可复用）。探针 M-01/02/03/06 须翻转为“已标 failed”。

## §4 套件重跑汇总（本轮亲自重跑）

| 套件 | 结果 | 备注 |
|---|---|---|
| BG `tests/r18_bg.py`（Flask poll／report 守卫） | 22/22 | 新树亲手重跑 |
| BH `tests/bh_worker_poll_guard.mjs`（Worker poll／report 守卫） | 20/20 | 新树亲手重跑 |
| R17 Flask `tests/r17_flask.py` | 86/89 | 3 红恰为 OBSERVED 格 F4-02b／F4-13／F4-15（按预期翻转，见 §1.3） |
| R17 Core `tests/r17_core.py` | 46/46 | 全绿 |
| R17 Agent `tests/r17_agent.py` | 33/33 | 全绿 |
| R17 Worker `tests/r17_worker.mjs`（import 重定向至新树） | 33/35 | 2 红恰为 OBSERVED 格 W5-05／W5-06a（按预期翻转）；W5-01 已转绿 |
| R18 Worker 队列竞态 `tests/r18_worker_queue_race.mjs` | 9/9（缺陷复现） | 新探针，本轮新增，已落 tests/ |
| R18 Worker 畸形 sweep `tests/r18_worker_malformed.mjs` | 13/13（缺陷复现） | 新探针，本轮新增，已落 tests/ |
| 回退变异（4 棵，§1.2） | 逐棵恰红 | m-flask-poll 18/22、m-flask-report 17/22、m-worker-poll 17/20、m-worker-report 15/20 |
| 门禁干净树 | 29/29，exit 0 | 第三次跑才过，前两次 SKIP 诚实记账（见 §1.4／O2） |
| 门禁 §7 变异（7 棵，§1.4） | 逐棵 28/1，仅 §7 红 | 红格文本已逐棵核对，均为“钉死哈希不一致：install.sh 与 agent/agent.py 的 sha256 逐键不等” |

**诚实记账：**R13／R14／R15 的 366 格无法原样重建逐格对照——产品代码文件自 R17 后除 BG／BH 两文件外 mtime／sha 逐项一致（§0），R17 的证据按 mtime 规则沿用，本轮不冒充重跑数（与 R16／R17 同款记账）。R17 的 203 格本轮已按 §1.3 全部重跑（Flask／Core／Agent／Worker 四套，203 格＝89＋46＋33＋35），红格全为按预期翻转的 OBSERVED 格。

## §5 P0-1/2/3：真实 wrangler deploy 重验

- `npx -y wrangler@4.161.0 deploy --dry-run --config cloudflare/wrangler.toml`：**exit 0**，绑定仍为占位 `env.PANEL_KV (REPLACE_WITH_KV_NAMESPACE_ID)`——与 R17 同款。
- 真实 `wrangler deploy`（非 dry-run）：**exit 1**，未登录——提示需登录或加 `--temporary` 取 claim URL。无 token、无部署、无副作用。
- 结论：P0-1／2／3 仍**未验**（真实 Cloudflare Worker 部署从未跑通过；需用户创建 Cloudflare API token 或交互式 `wrangler login`，另填 wrangler.toml 的 KV id／preview_id、置 `wrangler secret put ADMIN_PASSWORD` 与 `AGENT_BUNDLE_ORIGIN`）。此事 R8 §5 至 R17 §5 均已向用户提问、用户未复，本轮再记一次。若用户始终不启用，交付文档须把 Cloudflare 模式部署态标为未验。

## §6 文档宣称全量核对（9 份交付文档）

9 份文档（根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md）逐项核对，结论与 R17 §6 一致，无翻转：

| 文档 | 结论 |
|---|---|
| 根 README.md | ✓ 计数 29、逐键相等口径、改密／首登诚实口径均与行为一致 |
| panel/README.md | ✓ 登录覆盖口径已按 R15-P2-2 修正 |
| cloudflare/README.md | ✓ 钉位 `agent.py:676`／`:687` 已删（R14-P2-3 仍关）；56 格口径见 §6.2 |
| cloudflare/server-mode.md | ✓ Worker 501 改密、fail-closed 口径与 W4-02／W6-01 一致 |
| core/README.md | ✓ render 参数口径与 C1 探针一致 |
| agent/README.md | ✓ 三档全无拒绝安装、sha256 fail-closed 与 A2 探针一致 |
| egress/README.md | ✓ fail-open 单向性、TCP／UDP 双测口径与行为一致（真机见 live-10） |
| docs/security.md | ✓ 认领守卫／审计脱敏口径与 F3／F4 探针一致；`grep -rnw` 旧口径 0 命中 |
| docs/flmx-reference.md | ✓ 32+3 行逐行核查见 §6.2，与 R16／R17 逐行一致 |

### §6.2 flmx-reference.md 32+3 行逐行核查（本轮独立验证）

`/tmp/r16/flmx-verify.py` 重跑，35 行逐行结论与 R16／R17 完全一致（BG／BH 只动产品代码，未动文档）：照抄 1-5／1-8／1-10／1-13／1-15（含逐键相等=True）／1-17／1-24／1-25／1-27／2-8／2-9；部分抄 1-16／2-4／2-6／2-10／3-4／3-9；未抄 0-1／1-32／2-5／3-3；存疑 0-3／1-6／1-11／1-21／2-2／3-1／3-7／3-8；核查 1-4／1-9／1-14／1-29／2-7／3-6。**无一行翻转**。

### §6.3 观察（已核实，不立案）

- 全树 grep：`SCRIPT_VERSION`／`resolve_version` 正文归零（审计报告除外）；过期 `28/28`／`PASS=28` 正文归零（命中仅 docs/audit/ 历史文件）；`agent.py:676`／`:687` 在 cloudflare/README 归零。
- R15 §6.3 的两处旧观察（2-7 的 .72 两处、3-6 行引用漂移）仍在，不立案（与 R16／R17 同款）。

## §7 前端对比度核查

`python3 panel/static/contrast-check.py`：**10/10 PASS**（底线 4.5），目标 7 达成 4/10——与 R17 同数（最薄 4.92 绿字，见 live-11 真机渲染 166 元素 0 低于 4.5 的交叉印证）。

## §8 结论

**结论：不能交付。差集 2 条（均为 P2）：R18-P2-1（Worker 队列竞态丢命令）、R18-P2-2（Worker 面无畸形 sweep）。**

历史 150 条：**145 已修、2 部分（P0-3、P1-7，按设计）、1 未验（P0-1 真实部署态）、2 本轮新开；无一复发**。计数口径：R17 的 147 条（144 已修＋2 部分＋1 未验）＋R17-P1-1（本轮 §1 验证关闭，BG 22/22＋BH 20/20、四棵回退变异恰红、四套探针按预期翻转、门禁 29/29）＋本轮 2 条新发现。

### §8.0 历史 148 条复扫台账（R17 的 147＋R17-P1-1）

**本轮关闭 1 条（行为重验＋变异红证，见 §1）：**

| 项 | R18 状态 | 证据 |
|---|---|---|
| R17-P1-1 poll 下发非 queued 命令（双面） | **已修** | BG 22/22＋BH 20/20；四棵定点回退变异逐棵恰红（§1.2）；R17 四套探针按预期翻转（86/89＋46/46＋33/33＋33/35，红格全为 OBSERVED 旧缺陷格）；干净树门禁 29/29 |

**动过文件内的其余历史项（BG 改 app.py、BH 改 index.js；改动面已逐项重验）：**

- `panel/app.py` 内：R12-P1-1／R13-P2-1／R14-P2-1（sweep 三件套）——sweep 调用点未动（6 处，§2 T7），BG 探针的 poll／report 路径重跑 22/22 侧面覆盖读路径；R11-P1-1（`?node=` 兼容层）——BG 未动该层，R17 Flask 探针 86/89 重跑覆盖；R5 重投分歧——未动，见 O1。**全部已修，无一复发**。
- `cloudflare/src/index.js` 内：R11-P2-1（改密 501）——BH 未动该分支，R17 Worker 探针 33/35 重跑覆盖（W4-02 在内）；R3-P1-1（重投上限 3）——未动，M-04／M-05 对照格行为复现上限逻辑。**全部已修，无一复发**。
- `tests/` 新增探针不影响产品行为（只加文件，无产品代码改动；门禁重跑 29/29 侧面证实）。

**其余文件内的历史项（mtime 规则沿用＋本轮门禁／探针侧面覆盖）：**除 app.py 与 index.js 外，产品代码文件 mtime／sha 与 R17 §0 逐项一致，R17 的行为证据按 mtime 规则沿用；本轮门禁 29/29 重跑＋203 格 R17 探针重跑＋22 格新探针侧面覆盖 panel→队列→agent→core／egress 全链（登录、status、SK5 保存／翻转／风暴／补策略、agent poll／report、create_user 失败路径、无泄漏、坏队列、下载、吊销、compat）。§2 转移矩阵逐格核对未发现复发信号。**R17 的 144 条中无一复发**——已登记的谓词逐条皆绿；本轮 2 条新发现是同族残留的新一层（谓词不同：P2-1 是 poll／enqueue 读写竞态，既往轮次从未审过该路径；P2-2 是 Worker 面 sweep 缺失，既往轮次只审过 Flask 面），按新口径另立，不计为复发。

**部分与未验（不变）：**

| 项 | R18 状态 | 证据 |
|---|---|---|
| P0-3 bundle／install-agent.sh | **仍部分** | 逻辑已修（Flask agent-bundle 格 200＋tarball 含 agent.py；verify.sh install-agent-script 200）；部署态未验（§5） |
| P1-7 改密＋首登强制改密 | **仍部分（按设计）** | 改密 API＋UI 在位（Flask 改密 F1-11～F1-14、Worker 501 诚实端点 W4-02）；首登强制改密从未实现、文档已诚实（根 README:260），不另立案 |
| P0-1 部署态 | **仍未验** | §5：登录卡住＋KV 占位，与 R7–R17 同卡点 |

**U 项更新（R17 §3.4.5 → 本轮）：**U-7（verify-integration 瞬时红）——R17 记“九次 28/28 或 29/29，本轮 29/29 一次过”；本轮**一次过不成立**（两次 SKIP 后第三次 29/29，见 §1.4／O2），但 SKIP 均诚实无假绿，门禁本身仍可信，U-7 维持关闭、备注更新。其余 U 项无变化（U-1 仍未验见 §5；U-2／U-3／U-4／U-5／U-6 已关闭，无变化）。

**live-11 对账（`docs/live-verify-R11.md`，205 行，已通读全文）：**全部通过、零新 bug——R14 的 3 条＋R15 的 2 条真机格全过，S0–S4＋headline 精选全过。R16-P2-1 的双架构安装格与 R17-P1-1 的真机格均不在 live-11 简报内，记为“待 live-12”，本轮未默写为已验。live-11 §10.3 的 get_status 格机上红已复核定性：断言文本本身即带沙箱前提（verify-integration.sh:536，`openvpn running=false（沙箱未跑服务，属实）`）；真机上 openvpn 确实在跑（PID 864832，TCP 443），agent 如实报 `running=True`——**产品行为正确，门禁前提与真机环境不匹配，非缺陷**；live-11 未停真机服务强行刷绿（属测试造假），处理正确。headline-3 初判“外部干扰”已由审计 DB＋时间戳日志三证纠正为自家 toggle 步数，自我纠正已披露。打包 14 分 48 秒（差 12 秒未满 15 分钟门）已诚实披露，内容等价，见 O3。

**live-12（并行在跑，不预判）：**R16-P2-1 双架构安装格＋R17-P1-1 真机格＋S0–S4 回归＋headline 精选；其结论须以其落盘报告为准。R18-P2-1／P2-2 无 live-12 格（简报早于本轮发现），属 live-13 的账。

### §8.1 下一步

1. 修 R18-P2-1（Worker 队列条件式清空或串行化＋孤儿回收器；探针 RACE-04/05/06 须翻转）与 R18-P2-2（Worker 侧 sweep＋sent_at 数值化＋孤儿回收器；探针 M-01/02/03/06 须翻转），修完主控核验。
2. 修复后派 AUDIT-R19（全量全局回头看，换推导方法）＋live-13（R18-P2-1／P2-2 真机格＋live-12 未覆盖项）。两路都过才交付。
3. 交付前仍需用户决断 P0-1／2／3（真实 Cloudflare 部署，R8–R17 已多次提问未复）；若不启用，交付文档须把 Cloudflare 模式部署态标为未验。

### §8.2 本轮新增探针资产（已落树内 `tests/`）

- `tests/r18_worker_queue_race.mjs`（9 格，R18-P2-1 复现）
- `tests/r18_worker_malformed.mjs`（13 格，R18-P2-2 复现）
- 回退变异构建器与门禁变异树在 `/tmp/r18/`（`build-reverts.py`、`reverts/`、`mutants/`）；/tmp 可能被清空，复现以树内探针为准。

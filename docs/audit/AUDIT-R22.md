# AUDIT-R22 — 全量全局回头看（交付前，第十轮）

## 结论先写

**结论：不能交付（差集 1 条，高）。**

历史 157 条：**已修 153、部分 2（P0-3、P1-7，按设计）、未验 1（P0-1，Cloudflare 真实部署）、新 1（R14-BUG-1，高，live-14 真机复现＋本轮代码面机制核实，BO 未进树）、复发 0**。R21 的 1 条（P2-1）经 BN 修复，本轮 §1 核验关闭。

- 审计员：独立审计路（未参与建设与修复路 BN；单审计员边做边写，不派子代理）
- 日期：2026-11-13（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R21 同等广度）
- 推导方法：**时间与顺序边界审计**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性、R9 对抗操作员＋时间衰变、R10 环境矩阵×修复存活、R11 契约闭合、R12 外部输入枚举、R13 部署生命周期、R14 证据优先行为复推导、R15 交付文档驱动用户旅程重演、R16 门禁与证据链反向审计、R17 爆炸半径 FMEA、R18 命令生命周期状态机转移闭合、R19 跨面一致性、R20 输入形状全集、R21 失效传播追踪均不同）——先机械枚举全树所有与时间／顺序有关的量（登录限流 5 次／300 秒窗口／900 秒锁、sent 120 秒超时、命令记录 7 天 TTL、会话 12h／24h、证书有效期边界、agent 5 秒 poll、健康检查 60 秒档、sing-box 启动上限、黑洞 metric 200 与 tun1 metric 0 的优先级、队列 FIFO 顺序、重试次数与退避），再逐项在精确边界上验证行为（第 5 次失败与第 6 次、窗口边缘、超时边缘、过期当天／过期后一天、并发下的顺序保证）；任一边界行为与文档／承诺不符即立案。R9 的时间衰减是按算子＋衰变方向抽查，本轮是全部时间量的边界值全集，二者不重叠；R21 的失效传播结论只作输入，不作本轮证据。
- 测试一律在 `/tmp/r22/ptree` 副本上跑；未动项目原文件（除本报告）；门禁自带 harness（venv＋桩 sing-box/systemctl/ip，面板以 nobody 跑）；未动任何真机。live-14 已于本轮审计中途完工（04:49），§4.4 按 `docs/live-verify-R14.md` 全文对账，不提前判通过。
- 语法基线：`node --check`（index.js）与 `python3 -m py_compile`（panel／core／agent／egress）均过；`bash -n verify-integration.sh install.sh` 过。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明（与 R9–R21 同款记明）。

## §0 树版本与 BN 改动确认

当前树是 BN 修复之后的新树。文件 mtime（UTC）与 R21 §0 基线对照：

| 文件 | mtime (UTC) | 行数 | sha256（前 12 位） | 说明 |
|---|---|---|---|---|
| cloudflare/src/index.js | 2026-11-12 19:25:36 | 1473 | 089bb32da319 | 未动（R21 mtime，BJ） |
| cloudflare/README.md | 2026-11-12 19:28:49 | 262 | 47489de2f9a4 | 未动（R21 mtime） |
| panel/app.py | 2026-11-12 20:32:41 | 2770 | 6aa2e97da251 | **动过（BN：`_quarantine_corrupt_queue` 补 `queue_corrupt_quarantined` 审计行＋`_queue_loss_counts`）** |
| core/openvpn_manager.py | 2026-11-12 17:20:57 | 1550 | 3b5d7dfe9ea1 | 未动（R21 mtime，BB） |
| agent/agent.py | 2026-11-12 19:50:12 | 922 | f303af828555 | 未动（R21 mtime，BL） |
| egress/sk5_manager.py | 2026-11-12 20:03:26 | 1228 | 7727486677a2 | 未动（R21 mtime，BK＋BM） |
| egress/policy-routing.sh | 2026-11-12 20:06:09 | 366 | 423a98bd022e | 未动（R21 mtime，BM） |
| install.sh | 2026-11-12 16:46:54 | 1082 | 3f050f037e7a | 未动（R21 mtime，AZ） |
| verify-integration.sh | 2026-11-12 18:14:53 | 630 | 6ef6ba2db8b1 | 未动（R21 mtime，BE） |
| panel/templates/index.html | 2026-11-12 15:21:57 | 1259 | 4f7dc697451c | 未动（R21 mtime） |
| README.md | 2026-11-12 17:56:09 | 287 | 6154ecabe046 | 未动（R21 mtime） |

结论：自 R21 起全树只有 `panel/app.py`（BN）一处产品文件动过；其余文件 mtime 与 sha256 均与 R21 §0 基线一致。历史复扫按 mtime 规则：未动文件的既往结论沿用 R1–R21 证据，不冒充重跑；BN 的改动面本轮全量行为重验（§1）＋时间／顺序边界全集重审（§2）。

## §1 BN 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

| 探针 | 结果 | 说明 |
|---|---|---|
| R21 隔离上报 `tests/r21_queue_quarantine.py` | **6/6** | Q4 翻绿：审计行实测 `('queue_corrupt_quarantined', 'failed', '队列文件已隔离备份至 …agent_queue.json.corrupt.…（损坏原因：Expecting property name…）；丢失 queued=不可知 sent=不可知 .ovpn 回执=不可知；备份文件可手工恢复')`；Q5 新行恰增 1 行（1→2）；Q1–Q3／Q6 保持 |
| R17 Flask `tests/r17_flask.py` | 见 §4.1 | BN 只动 app.py 队列隔离路径，Flask 全套在 §4.1 重跑 |
| 门禁 | **29/29** | 见 §3 |

定点变异红证（`/tmp/r22/mutants/m-noaudit`，删 `_quarantine_corrupt_queue` 内的 `_audit(...)` 调用一行，其余不动）：R21 探针恰好 **Q4／Q5 双红**（两格均为断言隔离审计行的格），Q1–Q3／Q6 不动——审计行是承重层，BN 闭合。R21-P2-1 关闭（沙箱级；cmd_get 对隔离丢失的 id 仍 404，按 R21 定案可接受）。

**探针自身维护，本轮修净（R22-P0-1，探针，不立案为产品问题）**：`tests/r21_queue_quarantine.py` 卷首的跑法仍写 `OVPN_CA_DIR`／`OVPN_SERVER_DIR`（不带 OPEN），产品代码读的是 `OPENVPN_CA_DIR`／`OPENVPN_SERVER_DIR`——与 R21 轮主控在 `r17_flask.py` 卷首踩过的同款陷阱。本轮已修正卷首；Q1–Q6 本身不走 render／下载路径，旧名不影响本轮 6/6 的有效性，特此记明。



## §2 时间与顺序边界审计（本轮推导方法）

全集 = 全树所有与时间／顺序有关的量，先机械枚举（grep 全集附录 A），再逐项在精确边界上验证。精确瞬间算子（`< 300`、`<= 120`、`<=` 证书过期）以代码核为准；探针在边界两侧各取 10ms 余量（Flask 浮点秒／Worker 整数毫秒；余量内漂移不可控，见 T3／W-T3 注）。

### §2.1 全集清单（量 × 双面边界 × 裁决）

| # | 量 | Flask 面边界 | Worker 面边界 | 裁决 | 证据 |
|---|---|---|---|---|---|
| B1 | 登录限流计数 | 5 次失败即锁（`>= 5`，第 5 次记账时锁） | 同值同算子 | 闭合 | T1／W-T1：4 次 401 无锁，第 5 次锁，第 6 次 429 |
| B2 | 登录窗口 300s | `now - t < 300`：恰 300s 的失败被剪枝 | `t > windowStart`：同义严格不等 | 闭合 | T2／W-T2：5×(now-300) 不锁，5×(now-299) 锁 |
| B3 | 锁 900s＋Retry-After | `int(剩余)+1` 秒；`time < locked` 时锁在位 | `ceil(剩余/1000)` 秒；`locked_until > now` 时锁在位 | 闭合（舍入差 1s 见 O-R22-1） | T1c／W-T1c：新鲜锁 Retry-After 均为 900 |
| B4 | sent 超时 120s | `(now-sent) <= 120` 不超时；超则重投／失败 | `(now-sentAt) <= 120000` 不超时；同值 | 闭合 | T3a/b、W-T3a/b：119.99s／119990ms 不超时，120.01s／120010ms 超时 |
| B5 | 重投上限 3 次 | retries+1；`> 3` 标 failed（恰 3 次重投后第 4 次超时失败） | 同值同算子 | 闭合 | T3c/d、W-T3c：retries=2 重投→3，retries=3 失败“已重投 3 次” |
| B6 | 重投集合 | 全部动作重投（无 SAFE 守卫） | 仅 SAFE_RETRY_ACTIONS 重投，非安全首超时即失败 | **分歧，已裁定（R5）** | T3e（create_user 重投）vs W-T3d（create_user 首超时失败）；security.md:12 已文档化 |
| B7 | 会话寿命 | 12h，`session.permanent=True`＋Flask 服务端 `max_age` 强制 | 24h，KV `expirationTtl`＋Cookie `Max-Age=86400` | 闭合（面间寿命不同是文档化口径，R19 已认） | T9：13h 前签发的会话 401；Worker :426 TTL＋:182 Max-Age 代码核 |
| B8 | 命令记录 TTL 7 天 | N/A（SQLite 持久化，无 TTL） | `cmd:` 一律 `expirationTtl: CMD_TTL_S`；`queue:`／`sent:` 键无 TTL（孤儿由 BI sweep 处理） | 闭合 | 代码核 index.js:314/546/634/652/658/666/829/911；孤儿处理见 R18／BI 探针 |
| B9 | 证书有效期 | `_index_expiry_is_past`：`when <= now` 即过期；CA 3650 天／证书 825 天（easyrsa.sh:49-50） | 不读此文件（快照 users 的 status 由 agent 上报） | 闭合（1 秒算子注见 O-R22-2） | T6：过期 1 秒前为真、3600 秒后为假、畸形／空为假 |
| B10 | agent poll 5s | `POLL_INTERVAL=5`，`POLL_TIMEOUT=10`，顺序循环无重叠 | `POLL_INTERVAL_S=5`（poll 响应 `poll_interval_s`） | 闭合 | T8b／W-T8b：`poll_interval_s` 均为 5 |
| B11 | agent 退避 | 失败后 `min(max(backoff*2,5),60)`；成功复位 5 | N/A（agent 单一实现，双面共用） | 闭合 | T7：连续失败 sleep [10,20,40,60,60]；成功后复位 5，下一失败 sleep 10 |
| B12 | 健康检查 60s | `OnUnitActiveSec=60s`＋`OnBootSec=1min`；BM 自愈幂等、二次检查不重复修（H7） | N/A（同 egress） | 闭合 | 静态核 timer 文件＋BM 探针 H7（R21 引用） |
| B13 | sing-box 启动上限 | `StartLimitBurst=5／120s`＋`RestartSec=3` | N/A（同 systemd） | 闭合 | 静态核 unit 文件；超限进 failed 态可见（R21 F5） |
| B14 | panel／agent 重启 | `Restart=on-failure`＋`RestartSec=5`（两者皆无显式 StartLimit，用 systemd 默认 5 次／10s） | N/A | 闭合 | 静态核 unit 文件；崩溃循环撞默认上限后进 failed 态可见 |
| B15 | 黑洞 metric | tun1 路由 metric 0 优先，黑洞 metric 200 兜底 | N/A（同 egress） | 闭合 | BM 探针 K3（R21 引用）；本轮回归见 §4.1 |
| B16 | 队列 FIFO | poll 按入队顺序下发；超时重投追加队尾 | 同顺序；超时重投 `queue.push` 队尾 | 闭合 | T8a／W-T8a：3 条顺序一致；T8b／W-T8c：过期 A 重排到 B 之后 |
| B17 | 前端等命令 120s | `waitCmd`：60 次×2s＝120s 上限，与 SENT_TIMEOUT 同值 | 同前端（共用 index.html） | 闭合 | 代码核 index.html:574-588；超限抛错不谎报成功 |
| B18 | 节点 token 轮换 | 旧 token 立即失效（UPDATE 替换哈希，无宽限期）＋审计行 | 同机制（KV 替换 token_hash）＋note | 闭合 | 代码核 app.py:2411-2430／index.js:557-575 |
| B19 | 登录失败记录 TTL | SQLite 行持久化，窗口过滤剪枝（无 TTL） | `loginfail:` 记录 `expirationTtl: 1200s`（锁 900＋窗口 300） | 闭合 | 代码核 index.js:391；1200＞900，锁到期前记录不消失 |
| B20 | 超时提示文案 | `timeout_hint` 用 `%d` 填 SENT_TIMEOUT_SECONDS（120） | 文案写死 120 秒 | 闭合 | app.py:2494／index.js:1015，同值 |

**§2.1 结论：20 项边界量全闭合，0 新发现。** 其中 B6 是 R5 已裁定的分歧（Flask 重投全动作、Worker 仅安全动作），本轮 T3e／W-T3d 亲手复核分歧仍在、行为与裁定一致，不重复立案。

### §2.2 观察（不立案）

- **O-R22-1（Retry-After 舍入差 1 秒，双面公式不同）**：Flask 用 `int(剩余秒)+1`（app.py:1278），Worker 用 `Math.ceil(剩余毫秒/1000)`（index.js:409）。同一剩余值算式对照：900.0→901 vs 900；899.0→900 vs 899；899.2→900 vs 900；1.0→2 vs 1。两者恒不低报（Flask 恒 ≥ ceil，Worker ＝ ceil），差值至多 1 秒且仅当剩余为精确整数秒时出现——浮点时间戳下实际不可观测；新鲜锁实测双面 Retry-After 均为 900（T1c／W-T1c）。Retry-After 是建议值，双面均诚实，不立案。
- **O-R22-2（证书过期 `<=` 的 1 秒算子注）**：`_index_expiry_is_past` 用 `when <= now`（core:370），即恰好过期那一秒即判过期；OpenSSL 的 notAfter 语义为“该秒仍有效”时，两者差 1 秒。面板严 1 秒是 fail-closed 方向，且时间戳只到秒、面板只在读用户列表时比较，实际不可观测，不立案。
- **O-R22-3（Worker 超时权威时间戳的分裂：poll 用 sent 副本，sweep 用记录）**：poll 的超时循环把 `entry.sent_at`（sent 副本）传给 `_handleSentTimeout` 作 override（index.js:806），sweep 只对孤儿 sent 记录用记录自身的 sent_at（:660-670）。两者在下发时同值同写（:838-840），仅手改 KV 能使之分裂；分裂时 poll 信副本、sweep 信记录，各自一致、可预期。本轮探针初版只改记录、W-T3b/c/d 与 W-T8c 全红即因此——探针修为双改（`ageSent` 帮手）后 12/12。设计本身自洽，不立案；探针教训已写进 `tests/r22_time_bounds.mjs` 注释。

### §2.3 面×属性矩阵（边界口径对齐，本轮新增一行）

| 能力 | Flask 面 | Worker 面 | 结论 |
|---|---|---|---|
| 登录限流 5／300／900 | `>=5`／`<300`／`<locked` | `>=5`／`>windowStart`／`>now` | 同义闭合（B1–B3） |
| sent 超时 120s＋重投 3 次 | `<=120`／`>3` 失败 | `<=120000`／`>3` 失败 | 同值闭合（B4–B5） |
| 重投集合 | 全动作 | 仅 SAFE 动作 | 分歧，已裁定（B6） |
| 会话寿命 | 12h 服务端强制 | 24h KV TTL＋Cookie | 面间不同，文档化（B7） |
| 证书过期判定 | `<= now` 即过期 | 快照 status（agent 上报） | 同源闭合（B9） |
| 队列 FIFO＋重投队尾 | 按序下发，重投追加队尾 | 同顺序 | 双面闭合（B16） |
| token 轮换 | 立即失效 | 立即失效 | 双面闭合（B18） |

## §3 门禁本身是审计对象（29 格逐格机械推导＋§7 变异红证）

**格数推导（机械）**：`grep -c 'ok "' verify-integration.sh` = **31** 个 `ok` 调用点（行 41／193／209／239／241／251／253／258／260／263／266／298／303／323／348／356／373／390／434／456／474／484／493／525／528／538／544／547／557／562／624）。减两项：① 行 41 在死 `check()`  helper（:39 定义，全树 0 处调用，grep 证）内，是变量名 `ok "$name"`，不是固定格；② 行 251／253 是 /etc admin.pass 格的互斥分支（同一 if/elif/else 的两条出路，单次运行至多一格命中）。**31 − 1 − 1 ＝ 29**，与运行时汇总对账一致。

**活树门禁**：`./verify-integration.sh` → **PASS=29 FAIL=0 SKIP=0，exit 0**（日志 /tmp/r22/gate-live.log；本轮在活树上跑，§0 的 sha 对得上）。

**§7 七变异（`tests/build-mutants.py`，活树副本）**：7/7 恰红，均为 **28/1、仅 §7 一格红**（其余 28 格不动，exit=1）：

| 变异 | 改动 | 结果 |
|---|---|---|
| m-dict-sb | `_PINNED_SHA256` 内 sing-box amd64/arm64 值互换（常量不动） | 28/1 §7 红 |
| m-dict-ts | tun2socks amd64/arm64 值互换 | 28/1 §7 红 |
| m-dict-missing | 字典删 1 项（3 项） | 28/1 §7 红 |
| m-dict-extra | 字典多 1 项（5 项） | 28/1 §7 红 |
| m-const-sb | 常量 `SINGBOX_SHA256_AMD64` 值改 1 字符 | 28/1 §7 红 |
| m-install-sb | install.sh 内同名赋值改 1 字符 | 28/1 §7 红 |
| m-char | 字典值 1 字符替换 | 28/1 §7 红 |

§7 两层（BE）均验活：常量逐键比对（m-const-sb／m-install-sb）与运行时字典绑定（m-dict-sb／m-dict-ts／m-dict-missing／m-dict-extra）各有独立红证。门禁本身无新问题。

## §4 回归套件＋文档＋P0 干跑＋live-14 对账

### §4.1 R17 四套件＋BG／BK／BM 回归（活树新鲜副本 /tmp/r22/ptree，R22_TREE 指活树）

| 套件 | 结果 | 说明 |
|---|---|---|
| r17_flask | **86/89** | 仅 3 红，全为预期 OBSERVED 翻转（F4-02b／F4-13／F4-15，R17-P1-1 钉死格） |
| r17_core | **46/46** | 全绿 |
| r17_agent | **33/33** | 全绿 |
| r17_worker | **33/35** | 仅 2 红，全为预期 OBSERVED 翻转（W5-05／W5-06a） |
| r18_bg（Flask poll 守卫） | **22/22** | 全绿（注意：探针读 `BG_TREE`，不是 `R18_TREE`；本轮初版误传后者得 import 失败，已纠正） |
| bk_stored_shapes | **8/8** | 全绿 |
| bm_blackhole_selfheal | **22/22** | 全绿（沙箱 netns＋mock 格；真机层 2 见 §4.4） |
| r20_input_shapes | S1/S2/S6 按预期翻转 | 缺陷签名不再复现（其余 4 格绿） |
| r22_time_bounds.py | **22/22** | 本轮新探针（§2） |
| r22_time_bounds.mjs | **12/12** | 本轮新探针（§2；初版 4 红系探针只改记录未改 sent 副本，已修，见 O-R22-3） |

### §4.2 文档 stale 检查＋对比度

- stale grep 0 处：`SCRIPT_VERSION`／`resolve_version` 残留 0（不含 audit/live 报告）；“门禁 28”／`28/28`／`PASS=28` 残留 0；BJ／BK／BL／BM 的文档行在位（cloudflare/README:253-254：畸形容器归一化、sweep 与孤儿回收、.ovpn 下载守卫）。
- 对比度：`panel/static/contrast-check.py` → **10/10 PASS，0 FAIL**；目标 7 达成 4/10（与 R15–R21 同款分布，非门禁底线）。

### §4.3 P0 dry-run

`cloudflare/` 目录下 `npx wrangler@4.161.0 deploy --dry-run` → **exit 0**（注意：须在 cloudflare/ 下跑，项目根目录会报“Could not detect a directory containing static files”）。KV id 仍为占位 `REPLACE_WITH_KV_NAMESPACE_ID`；真实部署 P0-1/2/3 仍卡用户侧（§5）。

### §4.4 live-14 对账（已完工，181 行，`docs/live-verify-R14.md` 通读）

- **R19 两条真机格全过**（机上 mock-KV 格：非列表容器 12/12、下载 8/8；R18 回归 15/15＋18/18＋20/20，BG 22/22）。
- **R20 两条真机格全过**（R20 探针 S1/S2/S6 按预期翻转、BK 8/8、活文件格 port 改 true 后 `/api/status` 仍 200、config_error 降级不 500）。
- **S0–S4 全过**（BUG-9 第 15/16 次复验双模全过，S3 杀 dante 全断无回落自动恢复，S4 TCP 443 五次首连全 0.2 秒）。
- **headline 精选全过**（首启 200＋10 交替 delta 恰 10、并发 delta 恰 1、policy-missing 诚实＋零重起修复、verify.sh 开 18/0/4 关 23/0/0、前端 0 低于 4.5、毒树重跑行级一致）。
- **新 bug 1 个（高）：R14-BUG-1**——BM 层 1 成立（杀 sing-box 后流量黑洞，curl exit 28、NTP 超时，面板诚实报 `blackholed_kill_switch`，R13-BUG-1 泄漏签名未复现）；层 2 失效：健康检查自愈重跑 policy-routing.sh，`ensure_tun1` 把死 tun1 重新建了出来（NO-CARRIER state DOWN），sing-box 重启即 FATAL `configure tun interface: file exists`；systemd 连试 5 次全撞同一错，触 StartLimitBurst 上限、单元落 failed，链路永久停在黑洞态，只靠人工 `ip link del tun1`＋重起才能恢复；人工恢复已实测证实诊断（删死 tun1 后 sing-box 立即干净启动，随后健康检查自动重装路由翻 `policy_repaired`、流量恢复走 SK5，同一 TCP 客户端全程未断）。**本轮已对当前树核实 R14-BUG-1 仍开放（§6），BO 修复路已派出（04:50）但截至本轮落笔未进树。**
- live-14 打包树（20:21:16 UTC）早于 BN 修复，R21-P2-1 的真机格属 live-15；live-14 观察（不立案）：`/api/status` 出口探测偶回 IPv6（live-9 同格 IPv4，机上有 v6，探测口径未作断言）；`_cached_sk5_status()` 10 秒状态缓存致恢复后一次查询仍显旧 config_error（代码注释写明设计）。

## §5 历史全量复扫（157 条逐条核现状）

R21 台账 156 条（152 已修＋2 部分＋1 未验＋1 新 R21-P2-1）；live-14 新立 R14-BUG-1（高）1 条；本轮方法新立 0 条，累计 **157 条**。

| 状态 | 数量 | 构成 |
|---|---|---|
| 已修 | 153 | R21 的 152＋R21-P2-1（BN 修完，本轮 §1 行为重验 6/6＋定点变异 m-noaudit Q4/Q5 恰红，关闭，沙箱级） |
| 部分 | 2 | P0-3（首登强制改密未实现，文档已诚实）、P1-7（同族，见 R19 台账）——均按设计 partial，不重立 |
| 未验 | 1 | P0-1（Cloudflare 真实部署从未验，§4.3；第八次待用户决断） |
| 未修（本轮新） | 1 | **R14-BUG-1（高）**（§6；live-14 真机复现＋本轮代码面机制核实，BO 未进树） |
| **复发** | **0** | 无一已修条目复发：R13-P2-5 的 agent `_as_int` 修复仍成立（agent 套件 33/33）；R17-P1-1 的 BG／BH 修复仍成立（Flask 86/89、Worker 33/35，红格均为预期翻转）；R18／R19／R20 的 BI／BJ／BK／BL 修复仍成立（§4.1 重跑全绿）；R9-P2-1 的备份层仍成立（R21 探针 Q3 字节一致，本轮 §1 复跑 6/6）；BM 层 1（黑洞兜底）真机成立（live-14 §10.1），层 2 的失效是 BM 未覆盖的新谓词（repair 建设备），不是 BM 层 1 的复发 |

**未动文件规则**：自 R21 完工（2026-11-12 20:30 UTC）起，全树唯一产品代码改动是 `panel/app.py`（BN，20:32）；其余产品文件 mtime 均 ≤20:06（BM）——BK／BL／BM／BI／BJ／BG／BH 的修复文件一字未动，结论沿用 R1–R21 证据，不冒充重跑。新增文件仅为报告（AUDIT-R21／R22、live-verify-R14）与探针（r22 两件＋r21 卷首修正＋r17_flask 卷首修正）；`__pycache__` 为本轮 `py_compile` 产物，已清。

**待用户决断（第八次未复，自 R8 §5 起）**：P0-1/2/3 的 Cloudflare 真实部署——需用户创建 Cloudflare API token 或交互式 `wrangler login`，并填 `wrangler.toml` 的 KV id＋preview_id、跑 `wrangler secret put ADMIN_PASSWORD`、配 `AGENT_BUNDLE_ORIGIN`。若用户永不启用，交付文档须把 Cloudflare 模式部署状态标为未验。

## §6 结论

**结论：不能交付（差集 1 条，高）。**

| 编号 | 级别 | 一句话 | 机制谓词＋全集 | 复现 | 修法指向 |
|---|---|---|---|---|---|
| R14-BUG-1 | 高 | sing-box 死后健康检查自愈重跑 policy-routing.sh，`ensure_tun1` 重建死 tun1（NO-CARRIER DOWN），sing-box 重启撞 `file exists` FATAL，5 次后 StartLimitBurst 锁死单元，链路永久停在黑洞态，需人工 `ip link del tun1` 才能恢复 | 谓词：**自愈重装 `policy-routing.sh enable` 时 `ensure_tun1` 无条件建设备（缺失即建）**。全集：`policy-routing.sh enable` 的全部调用方共 2 条，均汇入 `_apply_policy()`（sk5_manager.py:426）——(a) `enable()`（:970）：先 `_start_singbox()`＋等 tun1 至多 5 秒，起不来即 raise，**不暴露**；(b) `_repair_policy()`（:874）：直接 `_apply_policy()`，不启动 sing-box、不等 tun1，**暴露**。`ensure_tun1`（policy-routing.sh:119-131）唯一调用点在 enable 路径 :275；`disable`／flush 全树无 `ip link del tun1`。sing-box tun-in 自己建 tun1（sing-box.json.template:53-56），已存在同名设备即 FATAL，无 adopt 逻辑 | live-14 §10.2 真机：杀 sing-box → 约 20 秒后 repair 建死 tun1＋`default via 10.9.0.1 dev tun1 linkdown` → `systemctl start` FATAL `configure tun interface: file exists`（sing-box[926908] 20:34:53）→ 5 次后单元 failed（20:35:09）。人工恢复证实诊断：`reset-failed`＋`ip link del tun1`＋重起后 sing-box 干净启动（MainPID 927318），健康检查 20:36:11 自动补路由翻 `policy_repaired`，流量恢复，同一 TCP 客户端 PID 924500 全程未断 | 自愈重装时**不得重建 tun1 设备**（只重装黑洞与 rule；tun1 路由等 sing-box 自己重建设备后再由下一档健康检查补），或重装前先删 linkdown 的死 tun1；二选一，BM 层 1（兜底黑洞）不许动。修完须在真机上验“杀 sing-box → 黑洞 → systemd 自动重起成功 → 60 秒档内恢复走 SK5”全程无人干预（live-15 格），并重跑 BM 探针 22/22＋门禁 29/29 |

**其余全绿**：BN 闭合（§1）、§2 边界 20 项全闭合（0 新发现）、门禁 29/29＋§7 变异 7/7 恰红（§3）、R17 四套件 198/203（5 红全为预期翻转，§4.1）、BG 22/22、文档 stale 0 处＋对比度 10/10（§4.2）、P0 dry-run 通过但真实部署仍未验（§4.3）。live-14 已对账（§4.4）。本轮差集修完后须按第一前提①再做一轮全量全局回头看（AUDIT-R23）＋live-15（R21/BN 与 BO 的真机格）对账，两路都过才交付。

**新探针资产**：`tests/r22_time_bounds.py`（T1–T9：登录限流／窗口／sent 超时／重投／证书过期／退避／FIFO／会话 12h，22 格）、`tests/r22_time_bounds.mjs`（W-T1–T8：Worker 面镜像，12 格，`ageSent` 双改帮手）；另修 `tests/r21_queue_quarantine.py` 卷首环境变量名（R22-P0-1，探针）。

## §7 本轮未验与上限（诚实清单，不冒充）

- **R14-BUG-1 的修复（BO）**：BO 路 04:50 已派出，截至本轮落笔未进树；本轮只核实缺陷仍开放＋机制，未验修复。真机全程无人干预格属 live-15。
- **live-14 已对账**（§4.4）；R21-P2-1 的真机格属 live-15（打包树早于 BN）。
- **R13-BUG-1／BM 层 1 真机格**：只认 live-14 §10.1；本轮只到沙箱 netns＋mock 格（BM 22/22）。
- **arm64**：无 arm64 机器，§7 的 arm64 哈希绑定只在沙箱变异上验活，真机安装格未验（与 R16–R21 同款）。
- **UDP 数据面**：沙箱 UDP sendto 一律 EPERM、TUN 创建 EPERM，本轮一切 UDP 断言均为形状／渲染级；UDP 真通路只认 live 轮。BM 探针的 netns 格用真实 ip／真实路由表查表（K1–K5），不发 UDP 包。
- **Cloudflare 真实部署**：P0-1/2/3 仍卡用户侧（§4.3、§5）；dry-run 通过不等于部署通过。
- **门禁的沙箱前提**：`verify-integration.sh` 是沙箱门禁（头注“沙箱内运行”）；get_status 格断言 `running is False`，在真机活 openvpn 上按设计红（live-11 已定位，非缺陷），沙箱 29/29 为门禁 verdict 依据。
- **Worker 面真机格**：R19／R18 的 Worker 格只到机上 mock-KV（live-14 §9），无真实 Worker 部署。

## 附录 A：§2 普查的机械推导命令（可复现）

```bash
# 时间量枚举（全树）
grep -rn "300\|900\|120\|86400\|43200\|PERMANENT_SESSION_LIFETIME\|SESSION_TTL\|CMD_TTL\|POLL_INTERVAL\|StartLimitBurst\|metric 200\|metric 0\|retries" \
  panel/app.py cloudflare/src/index.js agent/agent.py egress/sk5_manager.py \
  core/openvpn_manager.py systemd/*.timer systemd/*.service panel/templates/index.html
# 证书有效期
grep -n "_index_expiry_is_past\|3650\|825" core/openvpn_manager.py core/easyrsa.sh
# 队列顺序
grep -n "queue.push\|q.append\|for .* in queue\|for .* of queue" panel/app.py cloudflare/src/index.js
```

## 附录 B：本轮验证命令速查（可复现）

```bash
# 语法基线
node --check cloudflare/src/index.js
python3 -m py_compile panel/app.py core/openvpn_manager.py agent/agent.py egress/sk5_manager.py
bash -n verify-integration.sh install.sh
# BN 重验（§1）：活树新鲜副本 /tmp/r22/ptree，venv /tmp/r21/venv，nobody 身份
runuser -u nobody -- env PYTHONPATH=/tmp/r21/venv/lib/python3.12/site-packages R21_TREE=/tmp/r22/ptree \
  OVPN_PANEL_DATA_DIR=<fresh> OVPN_PANEL_SECRET_PATH=<fresh>/secret.key \
  OPENVPN_CA_DIR=/tmp/r17/fixture-ca OPENVPN_SERVER_DIR=/tmp/r17/fixture-server \
  OVPN_SK5_CONFIG_DIR=<fresh> python3 /tmp/r22/ptree/tests/r21_queue_quarantine.py
# 本轮边界探针（§2）
runuser -u nobody -- env PYTHONPATH=/tmp/r21/venv/lib/python3.12/site-packages R22_TREE=/tmp/r22/ptree \
  OVPN_PANEL_DATA_DIR=<fresh> OVPN_PANEL_SECRET_PATH=<fresh>/secret.key \
  OPENVPN_CA_DIR=/tmp/r17/fixture-ca OPENVPN_SERVER_DIR=/tmp/r17/fixture-server \
  OVPN_SK5_CONFIG_DIR=<fresh> python3 /tmp/r22/ptree/tests/r22_time_bounds.py
cd /tmp/r22/ptree && node tests/r22_time_bounds.mjs
# 门禁（§3）
./verify-integration.sh   # 29/29
python3 tests/build-mutants.py /tmp/r22/ptree /tmp/r22/mutants-gate  # 7 棵，逐棵 ./verify-integration.sh 须 28/1
# 套件（§4.1）：r17_flask（86/89）／r17_core（46/46）／r17_agent（33/33）／r17_worker（33/35）／
#   r18_bg（BG_TREE，22/22）／bk_stored_shapes（8/8）／bm_blackhole_selfheal（22/22）／r20_input_shapes（S1/S2/S6 翻转）
# P0（§4.3）：cd cloudflare && npx wrangler@4.161.0 deploy --dry-run  # exit 0
```

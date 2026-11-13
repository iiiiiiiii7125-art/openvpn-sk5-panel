# AUDIT-R17 — 全量全局回头看（交付前，第五轮）

## 结论先写

**结论：不能交付，差集 1 条（P1×1，R17-P1-1）。**

历史 147 条：144 已修（R16 的 143＋R16 的 1 条本轮关闭，变异红证齐全）、2 部分（P0-3、P1-7，按设计）、1 未验（P0-1 部署态，见 §5）；**无一复发**。本轮 1 条新发现是 R12-P1-1／R13-P2-1 的同族残留（谓词不同，见 §3.1）：**双面同机**——Flask `agent_poll` 与 Worker `handleAgentPoll` 的取命令循环都不查状态，无条件把队列里的条目塞进下发列表。Flask 面：`_fail_malformed_cmds` 刚标 failed＋审计“不再下发”的命令，同一轮 poll 照常下发给 agent 执行；`init_pki`（force+confirm）形的手改条目会被执行、CA 被重建，而面板仍显示 failed、审计行写“已隔离”。Worker 面：同形循环（`index.js:639-648`，push 在 `if (status === "queued")` 块外）——failed 标记的命令照常下发（W5-01）；另两条可达路径：陈旧/并发 poll 重读队列会把已 sent 的命令再下发一次（W5-05）、`agent_report` 无状态守卫使 queued 命令先被报 failed、下一轮 poll 照常下发（W5-06）。

- 审计员：独立审计路（未参与建设与修复路 BE；单审计员边做边写，不派子代理）
- 日期：2026-11-13（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R16 同等广度）
- 推导方法：**按爆炸半径的失效模式分析（FMEA）**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性、R9 对抗操作员＋时间衰变、R10 环境矩阵×修复存活、R11 契约闭合、R12 外部输入枚举、R13 部署生命周期、R14 证据优先行为复推导、R15 交付文档驱动用户旅程重演、R16 门禁与证据链反向审计均不同）——先把 9 份文档中每一句可核查的保证列成保证清单，再按爆炸半径分四档（单用户／单节点／整面板／整链）为每条保证枚举失效模式；每种失效模式须在代码里找到守卫、在行为上复现出诚实报错或正确恢复、在文档里找到对应口径，三者缺一即立案。R16 的门禁反向审计结论只作输入，不作本轮证据。
- 测试一律在 `/tmp` 副本（`/tmp/r17/tree` 树副本、`/tmp/r17/mutants/` 变异树、`/tmp/r17/ptree` 探针树）上跑；未动项目原文件（除本报告与新增的 `tests/` 探针资产，见 §8.4）；门禁自带 harness（venv＋桩 sing-box/systemctl/ip，面板以 nobody 跑）；未动任何真机。需真机行为复核的项一律写“待 live-11/live-12”或对账 live-10，不提前判通过。
- 语法基线：4 个 Python 文件 `py_compile` 全绿；7 个 shell 脚本 `bash -n` 全绿；Worker `node --check` 全绿（见 §0）。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明（与 R9–R16 同款记明）。

## §0 树版本与 BE 改动确认

当前树是 R16 修复路 BE 之后的新树。文件 mtime（UTC）与 R16 §0 基线对照：

| 文件 | mtime (UTC) | 行数 | sha256（前 12 位） | 说明 |
|---|---|---|---|---|
| verify-integration.sh | 2026-11-12 18:14:53 | 633（R16: 602） | 6ef6ba2db8b17 | 动过（BE：§7 加字典绑定第二层；与主控核验的 sha256 一致） |
| README.md | 2026-11-12 17:56:09 | 287 | 6154ecabe046 | 未动（R16 mtime） |
| panel/app.py | 2026-11-12 17:20:11 | 2737 | fc81691c96d3 | 未动（R16 mtime，BA） |
| core/openvpn_manager.py | 2026-11-12 17:20:57 | 1550 | 3b5d7dfe9ea1 | 未动（R16 mtime，BB） |
| agent/agent.py | 2026-11-12 16:46:20 | 922 | 7f999298df5b | 未动（R16 mtime，AX） |
| install.sh | 2026-11-12 16:46:54 | 1082 | 3f050f037e7a | 未动（R16 mtime，AZ） |
| cloudflare/src/index.js | 2026-11-12 16:45:26 | 1221 | e40fe4d7d8d0 | 未动 |
| panel/templates/index.html | 2026-11-12 15:21:57 | 1259 | 4f7dc697451c | 未动（R13 mtime） |
| verify.sh | 2026-11-12 14:45:28 | 846 | 7867f557c6bb | 未动 |
| egress/sk5_manager.py | 2026-11-12 12:37:13 | 1109 | 02de9d8a4908 | 未动 |
| egress/policy-routing.sh | 2026-11-12 12:13:01 | 364 | 103a121bbdfe | 未动 |
| panel/data/ | 2026-11-12 12:14 | 空目录 | — | AE 路清空后仍空 |

语法基线（本轮实测）：`panel/app.py`、`egress/sk5_manager.py`、`core/openvpn_manager.py`、`agent/agent.py` 四文件 `py_compile` 全绿；`install.sh`、`verify.sh`、`verify-integration.sh`、`egress/test-egress.sh`、`egress/policy-routing.sh`、`core/easyrsa.sh`、`agent/install-agent.sh` 七脚本 `bash -n` 全绿；`cloudflare/src/index.js` `node --check` 全绿。

/tmp 资产现状（本轮开工时实测）：R16 的资产**幸存**（`/tmp/r16/tree`、`/tmp/r16/mutants/` m-bc1～m-bc8、`/tmp/r16/build-mutants.py`、`/tmp/r16/flmx-verify.py`、门禁日志、`wrangler-deploy.log` 均在）；BE 的资产幸存（`/tmp/r16-be/build-mutants.py`、`/tmp/r16-be/mutants/` m-be1～m-be4）；R13/R14/R15 的探针仍失（`/tmp/r13-tests/`、`/tmp/r13/`、`/tmp/r14/`、`/tmp/r15/` 均不存在）。本轮策略：门禁原样重跑＋7 棵新变异树（`/tmp/r17/build-mutants.py`，独立重建，不沿用 BE 构建器）；Flask/Core/Agent/Worker 四套探针按各报告 §1 的机制描述重建（`/tmp/r17/r17_flask.py` 等，本轮新数，见 §4）；R13/R14/R15 的 366 格无法原样重建逐格对照——产品代码文件自 R16 后 mtime 逐项一致（§3.0），R16 的证据按 mtime 规则沿用，本轮不冒充重跑数（见 §4 诚实记账）。BE 改动面（门禁 §7）本轮全部重新验证（§1／§2／§6）；探针与变异构建器本轮落进树内 `tests/`（R16 建议落地，见 §8.4）。

## §1 BE 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

本轮全部验证对 **`/tmp/r17/tree`（现树逐字节拷贝，sha256 逐项对 §0 一致）** 跑，不直接跑项目树。门禁变异树 7 棵（从现树逐项改动 BE 的 §7 判定点，`/tmp/r17/build-mutants.py`，每处改动点断言唯一命中），见 §1.1。

### §1.1 BE（verify-integration.sh §7 第二层）—— 干净树门禁 29/29；7 棵变异树

**干净树门禁 29/29**：`bash verify-integration.sh`（`/tmp/r17/tree`，实测 21 秒）：**PASS=29 FAIL=0 SKIP=0，EXIT=0**。§7 格明文 `[PASS] 钉死哈希一致：install.sh 与 agent/agent.py 的 sha256 逐键相等`。

§7 代码核对（`verify-integration.sh:583-627`，本轮通读）：第一层（既有）循环 4 个名，从 install.sh 取 `NAME="…"` 命名赋值、从 agent.py 取同名常量 `NAME = ("…")` 的值，逐键相等且非空才绿；第二层（BE 新增）解析 `_PINNED_SHA256` 的 4 项 `("binary","arch"): CONSTANT`——逐项要求绑定常量名须为该 (binary, arch) 命名的常量（`("sing-box","amd64")` 须指向 `SINGBOX_SHA256_AMD64`，换算为二进制名删 `-` 后转大写＋`_SHA256_`＋arch 大写，`sing-box`→`SINGBOX` 正确、`tun2socks`→`TUN2SOCKS` 正确），且该常量的解析值须等于 install.sh 的同名赋值；字典项数须恰为 4，缺项／多项亦红。两层都绿本格才绿。注释写清两层各防什么（值漂移 vs 绑定漂移），与 R16 §2.2 修法一致；注释中“互换任一对标签的值亦红”现对常量层与字典层双双成立。

| 变异树 | 改动点 | 门禁结果 | 唯一 FAIL 格 | 结论 |
|---|---|---|---|---|
| m-dict-sb | agent.py 字典 sing-box 两项值互换（常量不动） | 28/1 | 仅 §7 | R16-P2-1 关闭 ✓ |
| m-dict-ts | agent.py 字典 tun2socks 两项值互换（常量不动） | 28/1 | 仅 §7 | 第二对同款 ✓ |
| m-dict-missing | agent.py 字典删一项（3 项） | 28/1 | 仅 §7 | 缺项红证 ✓（BE 未单独测，本轮补） |
| m-dict-extra | agent.py 字典加一 bogus 项 `("sing-box","arm")`（5 项） | 28/1 | 仅 §7 | 多项红证 ✓（BE 未单独测，本轮补） |
| m-const-sb | agent.py sing-box 常量值互换（字典不动） | 28/1 | 仅 §7 | BC 层仍在 ✓ |
| m-install-sb | install.sh sing-box 赋值互换 | 28/1 | 仅 §7 | 对侧互换亦红 ✓ |
| m-char | agent.py sing-box amd64 哈希改一位 | 28/1 | 仅 §7 | 值漂移红证 ✓ |

后果单元直测（非门禁，是运行时行为）：`_pinned_sha256("sing-box","amd64")` 在干净树上返回 `950af37e…`（amd64 哈希），在 m-dict-sb 上返回 `20a6a9cd…`（arm64 哈希）——字典互换的后果本身仍是取错哈希（安装时 fail-closed），门禁现能拦住它（28/1），不再是盲区。

**README:198 对齐**：根 README:198 现写“`install.sh:63-66` 与 `agent/agent.py:122-132` 逐键相等”，与 §7 的判定文案一致 ✓。

### §1.2 其余（本轮亲自重跑）

- 前端静态对比度 `python3 panel/static/contrast-check.py`：**10/10 PASS**（底线 4.5），目标 7 达成 4/10——与 R10–R16 同款（§7）。
- `wrangler deploy --dry-run` 通过（§5）；真实部署仍卡登录（§5）。
- 全树 grep：`SCRIPT_VERSION`／`resolve_version` 正文归零（审计报告除外）；过期 `28/28`／`PASS=28` 正文归零（审计／live 历史报告除外）；`agent.py:676`／`:687` 在 cloudflare/README 归零（R14-P2-3 的钉位已删）。

## §2 门禁逐格机械推导（BE 后的 29 格）

`ok "` 文本出现 **31 次**（`grep -o` 计数，无同行双计）：:41 是 `check()` 助手定义内的 `ok "$name"`——`check` 全树无调用点（`grep 'check('` 仅定义 1 处），死代码；:251/:253 是 /etc admin.pass 格的 elif/else 两分支（同一格，一次运行只触发其一）；其余 29 处各为一格。**31 − 1（死代码）− 1（互斥分支冗余）＝ 29**，与运行时 PASS=29 一致。R14 §4a 与 R15 §1.4 的 prose 算术笔误（R16 §2.1 已记，不重立）。本轮复核：门禁文件前 580 行与 R16 树逐行 diff 为空（BE 只改 §7，行数 602→633）；下表沿用 R16 §2.1 的逐格表，逐格核对触发条件与判定谓词——除 §7 外各格行号后移但谓词不变；§7 格谓词更新为两层（见 §1.1），变异红证更新为本轮 7 棵树。

| # | 格 | 触发条件 | 判定谓词 | 变异红证 |
|---|---|---|---|---|
| 1 | 端口 8443 空闲 | 脚本起 | 端口空闲才继续；被占则整门 SKIP、exit 0 | —（前置守卫） |
| 2 | venv + Flask 就绪 | 准备段 | venv 建成且 pip 装 flask 成功 | — |
| 3 | 面板启动（nobody） | 起面板后 30 秒轮询 | 进程活且 `/api/me` 通 | — |
| 4 | admin.pass 落副本 data/ | 面板起后 | 副本内有 admin.pass（未写 /etc） | R2-P2-2 沿用 |
| 5 | /etc 快照比对 | 面板起后 | 跑前／跑后 admin.pass 状态一致（elif/else 两分支） | R2-P2-1 沿用 |
| 6 | GET / 200 | 未登录 | 首页 200 | — |
| 7 | UI 入站卡标记 | GET / 内容 | 含 `<!-- 入站卡：OpenVPN 服务 -->` | — |
| 8 | UI SK5 卡标记 | GET / 内容 | 含 `<!-- 链式出站卡：SK5 出口 -->` | — |
| 9 | /api/status 未登录 401 | 未登录 | 401 | — |
| 10 | 管理员登录 200 | 0600 密码文件＋`--data @file` | 200 | R6-BUG-2 沿用 |
| 11 | 注册节点拿 token | 登录态 POST /api/nodes | token 非空（只返回一次） | — |
| 12 | 登录后 /api/status 200 | 登录态 GET | 200 且含 openvpn/sk5/egress 键、running 为布尔 | R15 gate-mutant 沿用（资产已失，见 R16 §2.4） |
| 13 | SK5 禁用态全字段保存 | POST /api/sk5（enabled:false） | 200 且桩 run 0 次 | R4-P1-1 沿用 |
| 14 | SK5 再次保存 | 同上再发一次 | 200 且桩 run 仍 0 次 | R4-P1-1 沿用 |
| 15 | B1 真翻转 enable | alive-once 桩 run 活 10 秒 | 200、enabled=true、singbox_running=true、run 恰 1 次 | R6-P2-2 沿用 |
| 16 | B2 真翻转 disable | 桩 run 立死 | 200、回执含 singbox_restart_error、策略已撤、run 恰 2 次 | R6-P2-2 沿用 |
| 17 | R4-BUG-1 A 风暴 | limited 模式 7 次切换 | 全 200、7 restart＋7 reset-failed、0 限流失败、终态 enabled+policy+running | R4-BUG-1 沿用 |
| 18 | R4-BUG-1 B 补策略 | 策略手工删后重开 | 200、repaired=true、policy=true、零新增 restart | R4-BUG-1 沿用 |
| 19 | R4-BUG-1 B2 纯无操作 | 健康态重开 | 200、无 repaired、无新增 restart | R4-BUG-1 沿用 |
| 20 | R4-BUG-1 收尾 | disable＋模式回 nounit | 200 | — |
| 21 | agent 配置 0600 | 写配置后 | 文件 0600、panel_url 与注册时逐字一致 | — |
| 22 | 下发 get_status | POST /api/cmd | 拿 cmd_id | — |
| 23 | get_status 回执 done | agent --once＋5 秒等 | done | — |
| 24 | get_status 回执字段 | done 后查 cmd | 含 openvpn/sk5、running=false（沙箱未跑服务，属实） | — |
| 25 | 下发 create_user | POST /api/cmd | 拿 cmd_id | — |
| 26 | create_user 回执 failed | agent --once＋5 秒等 | failed（无 CA，预期失败） | — |
| 27 | create_user 回执无泄漏 | failed 后查 cmd | error 非空、无 `-----BEGIN` 私钥材料 | — |
| 28 | 回执无 token | 同上 | JSON 里无节点 token | — |
| 29 | §7 钉死哈希两层逐键相等 | 全程末 | 第一层 4 个命名哈希逐键相等且非空；第二层 `_PINNED_SHA256` 字典 4 项绑定逐项对、项数恰 4 | **本轮 7 棵变异树全覆盖（§1.1：字典互换×2、缺项、多项、常量互换、install 侧互换、改一位，逐棵 28/1 仅 §7 红）** |

逐格结论：29 格的触发条件与判定谓词全部可执行、无空洞断言（每格的通过条件都是一个可观测的 HTTP 状态／字段／计数／文件状态，非“代码在场”）。§7 格本轮 7 棵变异树全覆盖；其余格子的红证沿用历史轮次（R2/R4/R6 各变异实证，见表内“沿用”标注）——本轮未逐格重建旧变异树（/tmp 已失，见 §0），干净树 29/29 全绿是本轮 fresh 证据。

注（SKIP-only exit 0，设计属性、不立案）：端口被占／venv 失败／pip 失败三分支均 `skip` 后 `exit 0`（PASS=0 FAIL=0 SKIP=1）。门禁的退出码契约是“退出码＝FAIL 数”，SKIP 不计 FAIL；汇总行恒打印 `PASS=0 FAIL=0 SKIP=1`，读输出者可见“什么都没测”。这是 R2 期定下的设计，不是判据失真（没有一格谎称通过），记为已核对的设计属性。

## §3 FMEA 保证清单（本轮推导方法）与新发现

### §3.0 方法与保证清单来源

保证清单从 9 份文档逐句抽可核查的保证（功能／安全／恢复／诚实报错四类），按爆炸半径
分四档：**A 单用户、B 单节点、C 整面板、D 整链**。每种失效模式须在代码里找到守卫、
在行为上复现出诚实报错或正确恢复、在文档里找到对应口径——三者缺一即立案。
本轮探针（§4）即按此清单的守卫点取数；门禁 29 格（§2）只作输入，不作本轮证据。

| # | 保证（文档出处） | 爆炸半径 | 代码守卫 | 行为证据（本轮） | 结论 |
|---|---|---|---|---|---|
| G1 | 登录 5 失败锁 15 分钟＋429/Retry-After（README:261） | C | Flask 限流＋Worker 限流 | F1-04～F1-06、W1-07/W1-08 | ✓ 双面 |
| G2 | 改密后旧会话失效（security.md 审计表） | C | 会话版本 v＋secret 轮换 | F1-13 | ✓ Flask；Worker 501 诚实端点（W4-02，按设计） |
| G3 | token 只返回一次、列表不含 token（README:253） | C | 注册时明文只返一次，KV/库只存哈希 | F3-01/F3-02、W2-01/W2-02 | ✓ 双面 |
| G4 | 节点 token 错／名不符即 401（security.md 认领守卫） | B | `_agent_auth`＋`_check_panel_claim`；Worker `authenticateNode` | F3-09～F3-12、W3-08/W3-09 | ✓ 双面 |
| G5 | panel_url 不符 403、不报 panel_url 放行但标 unverified（security.md） | B | `_check_panel_claim` | F3-12 | ✓ Flask；Worker 同款认领在 W3-09 |
| G6 | 命令白名单外动作 400（agent 13 动作） | B | Flask `AGENT_ACTIONS`、Worker 动作表、agent `ACTIONS` | F3-13、W3-02、A3-01～A3-03 | ✓ 三面 |
| G7 | 坏队列条目标 failed＋审计、不再下发（R12-P1-1 注释） | B | `_fail_malformed_cmds` | F4-03/F4-04/F4-09 标 failed ✓；**下发未守住，见 R17-P1-1** | ✗ **立案** |
| G8 | sent 超时 120s：幂等重投≤3 次、非幂等标失败（security.md／R3-P1-1） | B | Flask `_requeue_stale_sent`、Worker sent 循环 | W5-02～W5-04；Flask 同款本轮未单独重跑（历史证据＋读码，见 §8.3） | ✓ Worker；Flask 见 §8.3 |
| G9 | 吊销节点：旧 token 立即 401、排队/在途命令标失败（P1-4） | B | Flask revoke、Worker `handleRevokeNode`（删 queue 键） | F5-13～F5-15；Worker revoke 删队列已读码 | ✓ 双面 |
| G10 | 吊销/过期用户 .ovpn 下载 403、未知 404（R13-P2-3） | A | 下载路径查 `list_users` 状态 | F5-01～F5-12 | ✓ 双面（Flask 两路径；Worker 下载走 ovpn KV，见 §6） |
| G11 | 端口建后只读、改口须 `allow_port_change=true`（README:250、P01） | B | `render_server_conf` P01 检查 | C1-12/C1-13 | ✓ |
| G12 | 端口/bool/dns 输入严格校验（R12 外部输入枚举） | B | `_valid_port`、`_coerce_bool`、`_validate_dns`、agent `_as_int`/`_as_bool` | F2-01～F2-14、C1-01～C1-11、C2-01/C2-02、A1/A2 | ✓（dns 字符集级，见 §3.3 观察 O1） |
| G13 | 用户名防遍历/保留名（R9-P1-2 同族） | A | `validate_username` | C2-02 | ✓ |
| G14 | 证书状态按 serial 识别、V 但过期即 expired（R9-P1-2） | A | `list_users` 的 expiry 比对 | C2-03～C2-07、F5-03/F5-08 | ✓ |
| G15 | SK5 默认断网保护、fail-open 须显式开、fail-over 单向不自动回链（README:154-158） | D | sk5_manager fail_open 默认 False、fail-over 写 enabled=False | 读码＋门禁 B1/B2 格；真机断网保护由 live-10 headline 格覆盖 | ✓（沙箱只验控制面，真机见 live-10） |
| G16 | SK5 凭据永不进日志/回执/URL（README:253/257） | C | 脱敏 `_audit`、回执无 token、sk5.json 0600 | 门禁 27/28 格；F3-02；A3-08 | ✓ |
| G17 | 二进制钉死哈希、校验失败即停（README:72、agent README:93） | D | install.sh 4 命名哈希＋agent `_PINNED_SHA256`＋`_verify_file` fail-closed | 门禁 §7 两层＋7 棵变异树（§1.1）；A2-01～A2-04 | ✓ |
| G18 | 安装包 sha256 fail-closed（agent README:93、install-agent.sh 头注） | D | bundle.sha256 端点＋install-agent.sh 验包才执行 | W6-01（无 origin 503）；Flask bundle 格由门禁覆盖 | ✓（部署态未验，见 §5） |
| G19 | OVPN_SUBNET 非法即安装 die、不静默跑错网段（R12-P2-6/AV） | D | install.sh:170-200 CIDR 校验＋固定 10.8.0.0/24 断言 | 读码（`python3 - "$OVPN_SUBNET" … || die`）；live-9/10 真机安装通过 | ✓（沙箱未跑 install.sh 全程，见 §8.3） |
| G20 | 重装不碰 panel/data、不删 ufw（R8-BUG-1/2） | C | install.sh 474-505 staging 排除＋274 ufw 守卫 | 读码＋panel/data/ 仍空（§0）；真机由 live-9 headline-9 覆盖 | ✓（沙箱未跑 install.sh 全程，见 §8.3） |
| G21 | 审计日志脱敏、绝不含口令/token/.ovpn 私钥（security.md:18） | C | `_audit` 脱敏＋回执不记 result | F4-06；门禁 27/28 格 | ✓ |
| G22 | Worker 改密 501 诚实（R11-P2-1） | C | `handleChangePassword` 501 | W4-02 | ✓（按设计，文档已诚实） |
| G23 | 坏 body 不烧登录限流（R13-P2-4） | C | Flask `get_json(silent=True)`＋Worker `readJson` null 分支 | F1-02/F1-03；W1-02～W1-05 | ✓ 双面 |
| G24 | 无名 KV 记录不杀 listNodes（R12-P2-3） | C | Worker `listNodes` skip | W2-03 | ✓ |
| G25 | 前端对比度底线 4.5（UI 定稿） | C | contrast-check.py | §1.2：10/10 | ✓ |
| G26 | 文档宣称与行为一致（R15-P2-2 同族） | C | —（文档即口径） | §6 全量核对＋flmx 32+3 行 | ✓（本轮无新过期） |
| G27 | 队列损坏文件隔离、不 500（R12-P1-1） | B | `_load_queue` quarantine＋各读点容错 | F4-10～F4-12 | ✓ |

### §3.1 新发现 R17-P1-1（P1）—— 双面：poll 取命令循环不查状态，非 queued 命令照常下发

**机制谓词**：下发列表的构造须以 `status == "queued"` 为准——队列数组里的 id 只是
“候选”，只有记录状态仍为 queued 的才可下发；任何把记录标为非 queued 的转移
（sweep 隔离、回执落盘、超时标失败）都必须同步使该 id 失去下发资格。
谓词不成立的判定：poll 响应里出现任一 status ≠ queued 的命令 id。

**全集清单（机械推导）**：全树 `commands.push`／`commands.append` 下发点共 2 处，
无他处：

| 面 | 下发点 | 守卫现状 | 行为证据 |
|---|---|---|---|
| Flask | `panel/app.py` `agent_poll` 取命令循环（:2550 附近） | `if status == "queued"` 只包 `status="sent"` 的赋值，`commands.append` 在块外 | F4-02b、F4-13、F4-16 均观测到下发 |
| Worker | `cloudflare/src/index.js` `handleAgentPoll` :639-648 | 同形：`if (status === "queued")` 只包 sent 标记，`commands.push` 在块外 | W5-01、W5-05、W5-06b 均观测到下发 |

**复现（Flask 面，探针 F4-13/F4-14）**：队列手写一条 `init_pki`（status 缺失、
params `{force:true, confirm:true}`，与 R12-P1-1 同款手改队列前提）→ agent poll
→ 响应含该 id（`['c-nuke']`），且 `cmd_get` 随后查到它已被标 failed、
error 为“队列条目损坏（status 缺失），已隔离，不再下发”。
**复现（Flask 面第二路径，F4-15/F4-16）**：正常 enqueue `init_pki` → agent 在
poll 之前先 report `{ok:false}` → report 被接受（`agent_report` 除坏条目检查外
无状态守卫，见 §3.2）→ 下一轮 poll 照常下发该已 failed 的 init_pki。
**复现（Worker 面，W5-01/W5-05/W5-06）**：enqueue 后把 cmd 记录改 failed → poll
照常下发；已 sent 的命令遇陈旧/并发 poll 重读队列即再下发一次；queued 命令先
被 report 成 failed（`handleAgentReport:684` 无状态守卫）→ 下一轮 poll 照常下发
`init_pki`（params 含 force+confirm 全在）。

**后果**：最坏是 `init_pki`——agent 执行它会重建 CA，全部已签发用户证书失效，
而面板显示该命令 failed、审计行写“已隔离”，操作员看到的是“已拦截”，实际是
“已执行”。`create_user`/`revoke_user` 重复执行会诚实失败（用户已存在／已吊销），
后果较轻；`get_status` 重复执行无害。单次下发后队列即清空（Flask `queue[name]=[]`、
Worker `queue:<name>=[]`），故同一条目只多执行一次，不会每轮重复执行——后果以
一次 CA 重建为上限，但一次已足够。

**为什么是 P1 不是 P2**：与 R12-P1-1 同款前提（手改队列／陈旧 agent 回执）＋
可达的破坏性动作（CA 重建）＋面板与审计双重谎报（显示已隔离、实际已执行）——
三者叠加即 P1。不是 P0：需手改队列或陈旧/并发 agent 行为触发，非正常操作即爆。

**修法**：两面各改一处——把 `commands.append/push` 移进 `status == "queued"` 的
分支内（或循环顶加 `if status != "queued": continue`）；Worker 另建议给
`handleAgentReport` 加状态守卫（只接受 sent 态命令的回执，queued/done/failed
的回执回 409 或 200 忽略并审计），堵住 W5-06 的可达路径；Flask `agent_report`
同款建议。修后回归：F4-02b/F4-13/F4-16/W5-01/W5-05/W5-06b 六格须翻转为
“poll 不含该 id”；门禁不受影响（门禁只下发 get_status/create_user 且状态正常）。

**同族关系**：不是 R12-P1-1/R13-P2-1/R14-P2-1 的复发——那三条登记的是“隔离
本身漏路径”（读点未扫／下载未扫／吊销未扫），本轮三条的隔离均已就位（F4-03/
F4-04/F4-09/F5-13/F5-14 皆绿）；新谓词是“隔离后仍下发”，是同一队列状态机的
下一层，须另立。修后须把“下发点须查状态”写进门禁或探针常驻格（tests/ 已有
六格，修后翻转即回归门）。

### §3.2 扫全集后确认关闭的同族点与观察

- **Flask `agent_report` 的坏条目守卫在位**：回执落到“队列条目损坏”条目上时
  不复活（200 回 failed），F4-03/F4-04 的 failed 状态在回执后仍为 failed——
  但该守卫只认 error 前缀，不认状态；queued 命令的回执照常落盘（F4-15），
  是 R17-P1-1 的 Flask 第二可达路径，修法见 §3.1（不另立案）。
- **Worker `handleRevokeNode` 干净**：吊销时把排队/在途命令标 failed 后**删除
  整个 `queue:<name>` 键**（:524），无残留 id 可下发——不是可达路径，已读码确认。
- **Worker sent 超时重投上限在位**：W5-02～W5-04（幂等重投、非幂等标失败）；
  Flask 同款 `_requeue_stale_sent`（120s／3 次）本轮未单独重跑（探针未造 120s
  旧 sent 条目）；历史证据（R3-P1-1）＋读码在位，记为 mtime 沿用，见 §8.3。
- **双面能力面×属性矩阵**（Flask／Worker 两面 × 队列状态机属性）：

| 属性 | Flask | Worker |
|---|---|---|
| enqueue 校验（动作白名单／params 对象） | ✓ F3-13/F3-14 | ✓ W3-01/W3-02 |
| poll 只下发 queued | ✗ R17-P1-1 | ✗ R17-P1-1 |
| report 状态守卫 | ✗（仅坏条目检查，F4-15） | ✗（无守卫，W5-06a） |
| sent 超时：幂等重投／非幂等标失败 | ✓（历史＋门禁） | ✓ W5-02～W5-04 |
| 吊销：排队/在途标失败＋队列清理 | ✓ F5-13～F5-15 | ✓ 读码（删 queue 键） |
| 坏队列隔离＋审计 | ✓ F4-03～F4-12 | —（Worker 无 sweep，KV 记录即状态） |
| 改密 | ✓ 200（F1-11～F1-14） | 501 诚实（W4-02，按设计） |

### §3.3 观察（已核实，不立案）

- **O1 dns 校验是字符集级（设计口径）**：`_validate_dns` 只拒空白/空白符/shell
  元字符（docstring 明写“bare IP/hostname”），`999.1.1.1` 与 `1.1.1` 均被
  接受、原样写进 server.conf（C1-08、C2-01 OBSERVED 格）。面板面不接受 dns
  入参（固定 1.1.1.1），唯一入口是 OVPN_DNS env 与 agent params；错值在运行
  时 loud 失败（客户端 DNS 不通），非静默错义——与 AV 的 subnet 严格校验不同，
  此处文档未承诺 IP 校验，故不立案；若要收紧，应先改 docstring 与 README 口径。
- **O2 `_port_occupant` 分不清 EACCES 与占用**：nobody 身份 bind 特权端口
  （如 443）失败时报错“already in use by another process”（C1-13 初版）。
  生产面板以 root 跑，bind 探针正常；失败方向是 fail-closed（拒绝改口），
  只是报错文案在非 root 环境下误导。探针已改用 51194 端口验证 P01 本体。
  不立案（文案级，生产路径不受影响）。
- **O3 enable 失败 500 vs disable 失败 200+error 字段**：R4-P1-1 已接受的
  诚实不对称（polish only），本轮 F2-07 在无真实 sing-box 的沙箱里重现
  500＋“sing-box exited immediately”，与接受口径一致，不重立。

### §3.4 历史全量复扫（147 条逐条定性）

复扫宇宙：R16 的 146 条（143 已修＋2 部分＋1 未验）＋R16 本轮新发现 1 条＝
**147 条**。台账链：R8 115 → R9 115 → R10 122 → R11 123 → R12 125 →
R13 134 → R14 141 → R15 144 → R16 146 → **R17 147**。115 基底的内部考古引
R8/R9 §3，不重算。

#### §3.4.0 mtime 对账（R16 §0 → 本轮，UTC）

自 R16 后动过的文件仅 2 处：`verify-integration.sh`（BE，§0 表）与本轮新增
`tests/`（探针资产，产品代码不动）；其余文件 mtime 与 R16 §0 逐项一致
（panel/app.py、core、agent、index.js、install.sh、index.html、verify.sh、
egress 两文件）。panel/data/ 仍空。

#### §3.4.1 R16 的 1 条关闭（本轮行为重验，变异红证见 §1.1）

| 项 | R17 状态 | 证据 |
|---|---|---|
| R16-P2-1 门禁 §7 只比常量值、不比字典绑定 | **已修** | §1.1：干净树门禁 29/29；7 棵变异树逐棵 28/1 仅 §7 红（字典互换×2、缺项、多项、常量互换、install 侧互换、改一位）；运行时后果直测 `_pinned_sha256("sing-box","amd64")` 干净树 `950af37e…`、变异树 `20a6a9cd…` |

#### §3.4.2 动过文件内的其余历史项（全部重新验证，本轮探针／grep／门禁）

- `verify-integration.sh` 内：门禁 29/29（§1.1）＋7 棵变异树（§1.1 表）；§7
  的字典绑定层是本轮关闭项（§3.4.1），不是旧项复发。R2-P1-4（登录后 status 格）、
  R4-P1-1／R4-BUG-1（SK5 保存／风暴格）由干净树 29/29 全绿覆盖。
- `tests/` 新增不影响产品行为（只加文件，无产品代码改动；门禁重跑 29/29 侧面证实）。
- 文档内：R13-P2-7（flmx 钉位）——全树 grep `SCRIPT_VERSION`／`resolve_version`
  正文归零（审计报告除外，§6）；R10-P2-1（文档数字过期）——过期 28 计数归零
  （正文命中仅 docs/audit/ 历史文件，§6）；R14-P2-3（cloudflare/README:135 钉位）——
  `agent.py:676`／`:687` 在该文档归零（钉位已删，§6）；R15-P2-2 的其余项见 §6。
  **全部已修，无一复发**。

#### §3.4.3 其余文件内的历史项（R16 实证沿用＋本轮门禁／探针侧面覆盖）

产品代码文件 mtime 与 R16 §0 逐项一致，R16 的行为证据按 mtime 规则沿用
（同日、数小时内，复核时效内）；本轮门禁 29/29 重跑＋203 格新探针侧面覆盖
panel→队列→agent→core/egress 全链（登录、status、SK5 保存／翻转／风暴／补策略、
agent poll/report、create_user 失败路径、无泄漏、坏队列、下载、吊销、compat）。
§3 的 FMEA 逐格核对未发现复发信号。**R16 的 143 条中无一复发**——已登记的
谓词逐条皆绿；本轮 1 条新发现是同族残留（谓词不同，见 §3.1），按新口径另立，
不计为复发。

#### §3.4.4 部分与未验（不变）

| 项 | R17 状态 | 证据 |
|---|---|---|
| P0-3 bundle/install-agent.sh | **仍部分** | 逻辑已修（Flask agent-bundle 格 200＋tarball 含 agent.py；verify.sh install-agent-script 200）；部署态未验（§5） |
| P1-7 改密＋首登强制改密 | **仍部分（按设计）** | 改密 API＋UI 在位（Flask 改密 F1-11～F1-14、Worker 501 诚实端点 W4-02）；首登强制改密从未实现、文档已诚实（根 README:260），不另立案 |
| P0-1 部署态 | **仍未验** | §5：登录卡住＋KV 占位，与 R7–R16 同卡点 |

#### §3.4.5 U-1～U-12 认领表更新（R16 §3.5 → 本轮）

| # | 项 | R17 更新 |
|---|---|---|
| U-1 | P0-1/2/3 部署态 | 仍未验（§5） |
| U-2 | R6-P1-1 真机复现 | 关闭（live-8 headline-5 显式重跑通过） |
| U-3 | UDP 数据面 | 关闭（live-7 S1/S2＋live-8 S2＋live-10 S1/S2 再证 TCP+UDP 均走 SK5） |
| U-4 | R 符号链接自拷 | 关闭（无变化） |
| U-5 | R 逐项失败 die 分支 | 关闭（live-10 §17 已落盘） |
| U-6 | T 两变异 | 关闭（R8 已判；R9 T 变异重跑 17/2/4） |
| U-7 | verify-integration 瞬时红 | 关闭（R9–R17 九次 28/28 或 29/29，本轮 29/29 一次过） |
| U-8 | 真机在位升级路径 | 关闭（live-10 §18 headline-9 已落盘） |
| U-9 | KV 竞态与 POP 传播 | 仍未验（无部署） |
| U-10 | 前端渲染级核查 | 关闭（live-9／live-10 headline-7 真机渲染通过；本轮静态核查 10/10 与之致，§7） |
| U-11 | easy-rsa 真二进制签发 | 关闭（live-8 headline-2 以 real easyrsa 3.1.0 裁决） |
| U-12 | live-R5 结果 | 关闭 |

复扫合计：147 条＝已修 144（143＋§3.4.1 关闭的 1 条）／部分 2（P0-3、P1-7）／
未验 1（P0-1）；**本轮新发现 1 条另计（R17-P1-1，见 §3.1／§8 差集）**。
147＝144＋2＋1；无一复发。

## §4 套件重跑汇总（本轮亲自重跑）

| 套件 | 规模 | 结果 | 说明 |
|---|---|---|---|
| 门禁 verify-integration.sh（干净树） | 29 格 | **29/29，exit 0，~21s** | §1.1／§2 |
| 门禁变异树（build-mutants.py，独立重建） | 7 棵 | 逐棵 **28/1，仅 §7 红** | §1.1 |
| Flask 探针 r17_flask.py | 89 格 | **89/89** | 含 4 格 OBSERVED（F4-02b/F4-13/F4-15/F4-16，钉死 R17-P1-1 Flask 面）；F2-07 enabled=1 在沙箱断言诚实 500（无真实 sing-box，成功路径由门禁 B1 覆盖） |
| Core 探针 r17_core.py | 46 格 | **46/46** | 含 3 格 OBSERVED（C1-08/C2-01 dns 字符集级，见 §3.3 O1） |
| Agent 探针 r17_agent.py | 33 格 | **33/33** | `_as_int`/`_as_bool`、4 组 pin hash、`execute_command` 白名单、`load_config` |
| Worker 探针 r17_worker.mjs（mock KV） | 35 格 | **34/35，1 红＝W5-01** | W5-01 即 R17-P1-1 Worker 面；另 3 格 OBSERVED（W5-05/W5-06b 下发行为、W5-06a report 无守卫） |
| 前端对比度 | 10 格 | **10/10**（目标 7 达成 4/10） | §1.2，与 R10–R16 同款 |
| flmx-reference 32+3 行 | 35 行 | 与 R16 逐行一致（见 §6.2） | `/tmp/r16/flmx-verify.py` 重跑 |

**合计 203 格新探针：202 绿＋1 红（W5-01＝本轮唯一新发现的 Worker 面）。**
R13/R14/R15 的 366 格无法原样重建逐格对照（/tmp 已失，见 §0），产品代码文件
自 R16 后 mtime 逐项一致，R16 的证据按 mtime 规则沿用，本轮不冒充重跑数。
探针与变异构建器已落进树内 `tests/`（见 §8.4），产品代码不动。

## §5 P0-1/2/3：真实 wrangler deploy 重验——卡在登录，仍未验

- `npx -y wrangler@4.161.0 deploy --dry-run --config cloudflare/wrangler.toml`：
  **exit 0**，bindings 显示 `PANEL_KV (REPLACE_WITH_KV_NAMESPACE_ID)`（占位仍在）。
- 真实部署 `npx -y wrangler@4.161.0 deploy --config cloudflare/wrangler.toml`：
  **exit 1**——`In a non-interactive environment, it's necessary to set a
  CLOUDFLARE_API_TOKEN environment variable`（未用 `--temporary`，未向任何账号
  部署任何东西）。日志 `/tmp/r17/wrangler-deploy.log`。
- `wrangler.toml` 内 KV 占位仍 2 处（`REPLACE_WITH_KV_NAMESPACE_ID`／
  `REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`）；`wrangler secret put ADMIN_PASSWORD` 与
  `AGENT_BUNDLE_ORIGIN` 仍需用户侧完成。**P0-1/2/3 的部署态仍未验，与 R7–R16
  同卡点；用户侧待决事项已问五次未复，交付文档须把 Cloudflare 模式部署态标未验。**

## §6 文档宣称全量核对（9 份交付文档）

### §6.1 逐文档结论

| 文档 | 结论 | 本轮核对 |
|---|---|---|
| 根 README.md | ✓ | 哈希口径 :198“逐键相等”与 §7 两层一致；SK5 凭据/限流/断网保护口径与行为一致；首登强制改密“从未实现”已诚实（:260） |
| panel/README.md | ✓ | 登录/限流/改密口径与 F1 探针一致 |
| cloudflare/README.md | ✓ | 钉位 `agent.py:676`／`:687` 已删（R14-P2-3 仍关）；56 格口径见 §6.2 |
| cloudflare/server-mode.md | ✓ | Worker 501 改密、fail-closed 口径与 W4-02/W6-01 一致 |
| core/README.md | ✓ | render 参数口径与 C1 探针一致 |
| agent/README.md | ✓ | 三档全无拒绝安装、sha256 fail-closed 与 A2 探针一致 |
| egress/README.md | ✓ | fail-open 单向性、TCP/UDP 双测口径与行为一致（真机见 live-10） |
| docs/security.md | ✓ | 认领守卫/审计脱敏口径与 F3/F4 探针一致；`grep -rnw` 旧口径 0 命中 |
| docs/flmx-reference.md | ✓ | 32+3 行逐行核查见 §6.2，与 R16 逐行一致 |

### §6.2 flmx-reference.md 32+3 行逐行核查（本轮独立验证）

`/tmp/r16/flmx-verify.py` 重跑，35 行逐行结论与 R16 完全一致（未动文件，
mtime 与 R16 §0 一致）：照抄 1-5/1-8/1-10/1-13/1-15（含逐键相等=True）/
1-17/1-24/1-25/1-27/2-8/2-9；部分抄 1-16/2-4/2-6/2-10/3-4/3-9；未抄
0-1/1-32/2-5/3-3；存疑 0-3/1-6/1-11/1-21/2-2/3-1/3-7/3-8；核查 1-4/1-9/
1-14/1-29/2-7/3-6。**无一行翻转**。

### §6.3 观察（已核实，不立案）

- 全树 grep：`SCRIPT_VERSION`／`resolve_version` 正文归零（审计报告除外）；
  过期 `28/28`／`PASS=28` 正文归零（命中仅 docs/audit/ 历史文件）；
  `agent.py:676`／`:687` 在 cloudflare/README 归零。
- R15 §6.3 的两处旧观察（2-7 的 .72 两处、3-6 行引用漂移）仍在，不立案（与 R16 同款）。

## §7 前端对比度核查

`python3 panel/static/contrast-check.py`：**10/10 PASS**（底线 4.5），目标 7
达成 4/10——与 R10–R16 同款（§1.2 已记）。

## §8 结论

### §8.1 verdict

**不能交付，差集 1 条（P1×1，R17-P1-1，双面：Flask agent_poll 与 Worker
handleAgentPoll 的取命令循环不查状态，非 queued 命令照常下发）。**

| # | 级别 | 发现 | 机制 | 复现 | 修法 |
|---|---|---|---|---|---|
| R17-P1-1 | P1 | poll 下发非 queued 命令（双面） | 下发列表构造无 `status == "queued"` 检查；全树下发点共 2 处（Flask `agent_poll`、Worker `handleAgentPoll:639-648`），push/append 均在守卫块外 | Flask：F4-02b/F4-13（sweep 标 failed 后同轮下发 init_pki）、F4-15/F4-16（report 先行翻 failed 后下轮下发）；Worker：W5-01（failed 照常下发）、W5-05（陈旧 poll 再下发已 sent）、W5-06（report 先行后下发 init_pki） | 两面各改一处：append/push 移进 queued 分支内；Worker/Flask 的 report 另建议加 sent 态守卫（§3.1） |

历史 147 条：144 已修／2 部分（P0-3、P1-7，按设计）／1 未验（P0-1，§5）；
**无一复发**。修后须重跑本轮六格（F4-02b/F4-13/F4-16/W5-01/W5-05/W5-06b）
翻转为“poll 不含该 id”，再做一轮全量全局回头看（AUDIT-R18）才准交付。

### §8.2 live 对账

- **live-11（R14 的 3 条＋R15 的 2 条真机格）仍在跑——待 live-11 完工对账，
  本报告不代判其结论。**
- **R16-P2-1 的双架构安装格不在 live-11 简报内，记为“待 live-12”**（须等
  live-11 完工再派，同机串行防撞），不得默写为已验。
- live-10（2026-11-12，228 行）已完工：全部通过、零新 bug（S0–S4、R13 的 7 条
  真机格、headline-1～9；TCP 首连 5/5 在 1 秒内；SK5 TCP＋UDP 双栈；断网保护
  全断无回落且自动恢复）。其树早于 BA/BB——R14 的 3 条不在其范围。

### §8.3 未验清单

- P0-1/2/3：真实 Cloudflare Worker 部署（§5，卡登录＋KV 占位，需用户决断）。
- SK5 端口 1001 vs 9000：用户未确认（面板默认 1001，文档已标待定）。
- install.sh 全程：沙箱未跑（需 root＋真机；live-9/live-10 真机安装通过）。
- Flask `_requeue_stale_sent` 的 120s/3 次超时路径：本轮未单独造旧 sent 条目
  重跑（历史证据＋读码在位，mtime 沿用）。
- U-9 KV 竞态与 POP 传播：无部署，未验。

### §8.4 审计方法自述（供 R18 复核）

- 推导方法：爆炸半径 FMEA（§3.0）——9 份文档的保证清单 × 四档爆炸半径，
  每种失效模式须守卫＋行为＋文档三证齐全；R16 的门禁反向审计结论只作输入。
- 探针资产：`/tmp/r17/`（tree／ptree／mutants／build-mutants.py／四套探针／
  gate-tree.log／wrangler 日志／fixture-ca／fixture-server／venv）与树内
  `tests/`（build-mutants.py、r17_flask.py、r17_core.py、r17_agent.py、
  r17_worker.mjs、README.md）双份落盘；产品代码除本报告与 `tests/` 外未动。
- 探针隔离：Flask/Core 以 nobody 跑、全部写路径经 env 钉到 /tmp；跑后核查
  宿主 `/etc/openvpn-sk5-panel` 与 `/etc/openvpn` 均不存在（无泄漏）。
- 诚实记账：R13/R14/R15 的 366 格因 /tmp 已失无法逐格重建，按 mtime 规则
  沿用 R16 证据、不冒充重跑数；沙箱 UDP/TUN 限制项一律记 SKIP/诚实失败，
  不作产品结论；live-11/live-12 结论一律待对账，不默写。
- 本报告边审边写（74 行骨架先行），中断不丢稿；审计员未参与建设与修复路 BE。

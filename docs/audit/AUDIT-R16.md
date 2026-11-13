# AUDIT-R16 — 全量全局回头看（交付前，第四轮）

## 结论先写

**结论：不能交付，差集 1 条（P2×1，R16-P2-1）。**

历史 146 条：143 已修（R15 的 141＋R15 的 2 条本轮全部关闭，变异红证齐全）、2 部分（P0-3、P1-7，按设计）、1 未验（P0-1 部署态，见 §5）；**无一复发**——已登记的谓词逐条皆绿。本轮 1 条新发现是 R15-P2-1 的同族残留（谓词与 R15 登记项不同，见 §3.1）：BC 的 §7 逐键比对只比两个文件的命名常量**值**，不比 agent.py 的运行时绑定 `_PINNED_SHA256` 字典——字典内任一对值互换，门禁仍 29/29（变异树 m-bc1/m-bc7 实证），而 amd64/arm64 安装校验会取错哈希、安装时 fail-closed。

- 审计员：独立审计路（未参与建设与修复路 BC/BD；单审计员边做边写，不派子代理）
- 日期：2026-11-13（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R15 同等广度）
- 推导方法：**门禁与证据链反向审计**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性、R9 对抗操作员＋时间衰变、R10 环境矩阵×修复存活、R11 契约闭合、R12 外部输入枚举、R13 部署生命周期、R14 证据优先行为复推导、R15 交付文档驱动用户旅程重演均不同）——从“交付判据本身是否可信”出发：先逐格验证 verify-integration.sh 29 格的每一格（触发条件、判定谓词、变异红证），再逐项核对审计报告链（R1–R15）中每一项“已修”结论的证据是否真实落盘（探针文件在否、变异树在否、数字是否与报告一致），最后才做功能链全量复扫。任一判据失真即立案（不论产品行为是否正常）。
- 测试一律在 `/tmp` 副本（`/tmp/r16/tree` 树副本、`/tmp/r16/mutants/` 变异树）上跑；未动项目原文件（除本报告）；门禁自带 harness（venv＋桩 sing-box/systemctl/ip，面板以 nobody 跑）；未动任何真机。需真机行为复核的项一律写“待 live-11”或对账 live-10，不提前判通过。
- 语法基线：4 个 Python 文件 `py_compile` 全绿；7 个 shell 脚本 `bash -n` 全绿；Worker `node --check` 全绿（见 §0）。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明（与 R9/R10/R11/R12/R13/R14/R15 同款记明）。

## §0 树版本与 BC/BD 改动确认

当前树是 R15 修复路 BC/BD 之后的新树。文件 mtime（UTC）与 R15 §0 基线对照：

| 文件 | mtime (UTC) | 行数 | sha256（前 12 位） | 说明 |
|---|---|---|---|---|
| verify-integration.sh | 2026-11-12 17:53:17 | 602（R15: 591） | eed6fb94c7cd | 动过（BC：§7 改逐键比对；与主控核验的 sha256 一致） |
| README.md | 2026-11-12 17:56:09 | 287（R15: 277） | 6154ecabe046 | 动过（BD：8 文档之一） |
| panel/README.md | 2026-11-12 17:54:19 | 113 | d565d49be62f | 动过（BD） |
| cloudflare/README.md | 2026-11-12 17:54:19 | 260 | 7393d2b57e53 | 动过（BD） |
| cloudflare/server-mode.md | 2026-11-12 17:54:19 | 48 | 9dfad606bb9b | 动过（BD） |
| core/README.md | 2026-11-12 17:54:14 | 131 | c042e4b3d2fc | 动过（BD） |
| egress/README.md | 2026-11-12 17:54:04 | 254 | c8cc61457140 | 动过（BD） |
| docs/security.md | 2026-11-12 17:54:57 | 63 | 523e689f2736 | 动过（BD） |
| docs/flmx-reference.md | 2026-11-12 17:55:47 | 112 | cc994f423a9b | 动过（BD） |
| install.sh | 2026-11-12 16:46:54 | 1082 | 3f050f037e7a | 未动（R15 mtime） |
| panel/app.py | 2026-11-12 17:20:11 | 2737 | fc81691c96d3 | 未动（R15 mtime，BA） |
| core/openvpn_manager.py | 2026-11-12 17:20:57 | 1550 | 3b5d7dfe9ea1 | 未动（R15 mtime，BB） |
| agent/agent.py | 2026-11-12 16:46:20 | 922 | 7f999298df5b | 未动（R15 mtime，AX） |
| cloudflare/src/index.js | 2026-11-12 16:45:26 | 1221 | e40fe4d7d8d0 | 未动 |
| panel/templates/index.html | 2026-11-12 15:21:57 | 1259 | 4f7dc697451c | 未动（R13 mtime） |
| verify.sh | 2026-11-12 14:45:28 | 846 | 7867f557c6bb | 未动 |
| egress/sk5_manager.py | 2026-11-12 12:37:13 | 1109 | 02de9d8a4908 | 未动 |
| egress/policy-routing.sh | 2026-11-12 12:13:01 | 364 | 103a121bbdfe | 未动 |
| panel/data/ | 2026-11-12 12:14 | 空目录 | — | AE 路清空后仍空；AN 的 staging 拷贝不再往里写任何文件 |

语法基线（本轮实测）：`panel/app.py`、`egress/sk5_manager.py`、`core/openvpn_manager.py`、`agent/agent.py` 四文件 `py_compile` 全绿；`install.sh`、`verify.sh`、`verify-integration.sh`、`egress/test-egress.sh`、`egress/policy-routing.sh`、`core/easyrsa.sh`、`agent/install-agent.sh` 七脚本 `bash -n` 全绿；`cloudflare/src/index.js` `node --check` 全绿。

/tmp 资产现状（本轮开工时实测）：**R13/R14/R15 探针与变异树已全部随 /tmp 清理消失**——`/tmp/r13-tests/`、`/tmp/r13/mutants/`、`/tmp/r14/`、`/tmp/r15/` 均不存在（`ls` 实测）；`~/workspace` 内 4 层深度搜寻亦无探针副本（`r13_*.py`／`r14_*.py`／`run-flask.sh` 零命中）。本轮策略：门禁（树内自带 harness）原样重跑＋8 棵新变异树（`/tmp/r16/build-mutants.py`）；flmx 32+3 行按 R15 §2.2 表的谓词重写核查脚本 `/tmp/r16/flmx-verify.py`；R13/R14/R15 的 366 格探针文件已失、无法原样重建逐格对照——产品代码文件自 R15 后 mtime 逐项一致（§3.0），R15 的 366 格证据按 mtime 规则沿用（同日、数小时内），本轮不冒充重跑数（见 §4 诚实记账）。BC/BD 改动面（门禁＋8 文档）本轮全部重新验证（§1／§2／§6）。

## §1 BC/BD 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

本轮全部验证对 **`/tmp/r16/tree`（现树逐字节拷贝，sha256 逐项对 §0 一致）** 跑，不直接跑项目树。门禁变异树 8 棵（从现树逐项回退／改动 BC 的 §7 判定点，`/tmp/r16/build-mutants.py`，每处改动点断言唯一命中），见 §1.1。

### §1.1 BC（verify-integration.sh §7）—— 干净树门禁 29/29；8 棵变异树

**干净树门禁 29/29**：`bash verify-integration.sh`（`/tmp/r16/tree`，实测 21 秒）：**PASS=29 FAIL=0 SKIP=0，EXIT=0**。§7 格明文 `[PASS] 钉死哈希一致：install.sh 与 agent/agent.py 的 sha256 逐键相等`。

| 变异树 | 改动点 | 门禁结果 | §7 格 | 结论 |
|---|---|---|---|---|
| m-bc2 | agent.py sing-box amd64/arm64 常量值互换 | 28/1 | FAIL | BC 宣称的互换红证复现 ✓ |
| m-bc3 | install.sh sing-box amd64/arm64 赋值互换 | 28/1 | FAIL | 对侧互换亦红 ✓ |
| m-bc4 | install.sh sing-box amd64 哈希改一位（9→8） | 28/1 | FAIL | 值漂移红证复现 ✓ |
| m-bc5 | §7 回退为 R15 旧集合逻辑＋m-bc2 常量互换 | 29/29 | PASS（旧文案“集合相同”） | 旧逻辑下同款互换照常绿——BC 修复是关闭 R15-P2-1 的原因，非偶然 ✓ |
| m-bc8 | agent.py 删 `TUN2SOCKS_SHA256_ARM64` 常量定义 | 23/3 | FAIL | 非空检查生效 ✓（另 2 格 collateral 见注） |
| m-bc1 | agent.py `_PINNED_SHA256` 字典 sing-box 两项值互换（常量不动） | **29/29** | **PASS** | **新发现 R16-P2-1（§2.2）** |
| m-bc7 | agent.py `_PINNED_SHA256` 字典 tun2socks 两项值互换（常量不动） | **29/29** | **PASS** | **同上，第二对** |
| m-bc6 | install.sh `:366-367` 用量互换（amd64 取 ARM64 变量） | 29/29 | PASS | §7 宣称范围外，见 §2.3 观察 |

注（m-bc8 的另 2 格 FAIL 与 3 格未执行）：删常量使 `_PINNED_SHA256` 在 import 时 `NameError: name 'TUN2SOCKS_SHA256_ARM64' is not defined`，agent 进程起不来，`get_status`／`create_user` 两格回执停在 queued。另 3 格未执行（PASS+FAIL+SKIP=26≠29）：`if [ "$ST1" = "done" ]` 与 `if [ "$ST2" = "failed" ]` 的条件分支在 agent 已死时跳过其内格子——门禁的格数是状态依赖的，agent 链断时汇总数小于 29。§7 本身的红证（非空检查）成立；另 2 格红是变异树的 collateral、不是门禁缺陷——附带证明该常量在运行时是 load-bearing（字典引用它），正是 §2.2 的立论前提。

**README:198 对齐**：根 README:198 现写“`install.sh:63-66` 与 `agent/agent.py:122-132` 逐键相等”（BC 交代给 BD 的对齐项已落实），与 §7 的判定文案一致 ✓。

### §1.2 BD（8 份文档）—— 逐项核实，R15-P2-2 全表复核

**（a）门禁计数过期两处**：根 README:226 现写 `**PASS=29 FAIL=0 SKIP=0**` ✓（本轮实测 29/29 一致）；`egress/README.md:210` 现写 `verify-integration 29/29` ✓。全树 grep 过期 `28/28`／`PASS=28` 在正文归零（审计／live 历史报告除外）。

**（b）`docs/flmx-reference.md` 32+3 行逐行核实**（`/tmp/r16/flmx-verify.py`，每行谓词独立 grep／代码核实，不照抄 R15 结论；逐行证据见 §6.2）：15 行“照抄”属实、13 行假→“未抄（待定）”、4 行部分→“部分抄”、3 行改写行分界写准（2-5 未抄（待定）、3-9 部分抄、1-16 部分抄），**全部与文件结论一致**。计数复核：`未抄（待定）` 18 行、`部分抄` 8 行，与 BD 报告一致（18＝13 假＋2-5＋AZ 旧有的 1-2／1-3／1-18；8＝4 部分＋3-9／1-16＋旧有的 1-19／3-5）。3 处与根 README 直接矛盾的行（1-11、3-1、3-9）现均以根 README:249/:260/:253 为准写明。

**（c）其余 7 项逐项核实**：
- render 签名两处补全 6 参：`core/README.md:21` 与 `panel/README.md:58` 均为 `render_server_conf(proto="udp", port=None, server_dir=None, ca_dir=None, dns=None, allow_port_change=False)`，与代码 `core/openvpn_manager.py:1043` 的 `def` 签名逐参一致 ✓。
- Worker“55 项”→56：`cloudflare/README.md:251` 现写“56 格去重后；58 次执行，W7/W8 的畸形体与 lockout 探针 L1 的 4 体重合 2 体”——与 R15 §4 的 23＋13＋9＋13＝58 次执行、去重 56 一致 ✓。
- 卸载指引：根 README:265-280 现含删前确认（`read -r -p "确认卸载…？[y/N]"`）、FORWARD 删除两条（安装器写入的 `-s/-d 10.8.0.0/24`）、ufw 放行删除（`ufw delete allow 1194/udp`／`8443/tcp`）✓。
- security.md 自测 grep：`docs/security.md:7` 现写 `grep -rnw "admin123\|changeme\|123456"` 并注明 `-w` 词界；本轮实测 `-w` 版 **0 命中**，无词界版 2 命中（均为 `agent/agent.py:458/463` 的 hex 字符集 `"0123456789abcdef"` 含 `123456` 子串）——BD 的修法与实测一致 ✓。
- server-mode sent 态：`cloudflare/server-mode.md:21` 现写“**两端分歧（不相同）**：Worker 仅 7 个幂等动作可重投，非幂等首超时即标 `failed`；Flask `_requeue_stale_sent` 不分动作全重投”，与 `docs/security.md:12` 口径一致 ✓。
- panel/README 登录覆盖：`panel/README.md:23` 现写“管理接口 `/api/*`（除登录、`/api/me`）均需登录……例外：`/api/agent/*` 走节点 token 鉴权；`/api/agent/bundle`、`/api/agent/bundle.sha256` 与 `/install-agent.sh`、`/install-agent.sh.sha256` 公开”✓。
- README:198“逐键相等”：见 §1.1 末 ✓。另：R15 §6 表列的根 README 第三处问题（:251 工具栏逐字 class 宣称）BD 亦修了——现 `:251` 写“工具栏与卡片形似 FLMX（vanilla CSS 实现，非逐字 Tailwind class；顶栏不 sticky，仅侧栏 sticky）”✓。

### §1.3 其余（本轮亲自重跑）

- 前端静态对比度 `python3 panel/static/contrast-check.py`：**10/10 PASS**（底线 4.5），目标 7 达成 4/10——与 R10–R15 同款（§7）。
- `wrangler deploy --dry-run` 通过（§5）；真实部署仍卡登录（§5）。
- 全树 grep：`SCRIPT_VERSION`／`resolve_version` 正文归零（审计报告除外）；`agent.py:676`／`:687` 在 cloudflare/README 归零（R14-P2-3 的钉位已删）；旧数字 `1404`／`570-597`／`630-657` 正文归零（审计／live 历史报告除外）。

## §2 门禁与证据链反向审计（本轮新方法）

### §2.1 29 格逐格机械推导（触发条件＋判定谓词）

`ok "` 文本出现 **31 次**（`grep -o` 计数，无同行双计）：:41 是 `check()` 助手定义内的 `ok "$name"`——`check` 全树无调用点（`grep 'check('` 仅定义 1 处），死代码；:251/:253 是 /etc admin.pass 格的 elif/else 两分支（同一格，一次运行只触发其一）；其余 29 处各为一格。**31 − 1（死代码）− 1（互斥分支冗余）＝ 29**，与运行时 PASS=29 一致。

注（R14/R15 的 prose 算术笔误，不立案）：R14 §4a 写“30－1－2＝28”、R15 §1.4 写“31－1－2＝29”——两处算术均错一位（30−1−2=27，31−1−2=28）；结论数（28/29）与运行时一致，判据本身无损。错的是审计报告的算术式，不是门禁；历史报告不改写，特此记明。

| # | 格 | 触发条件 | 判定谓词 | 变异红证 |
|---|---|---|---|---|
| 1 | 端口 8443 空闲 | 脚本起 | 端口空闲才继续；被占则整门 SKIP、exit 0（见下注） | —（前置守卫） |
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
| 12 | 登录后 /api/status 200 | 登录态 GET | 200 且含 openvpn/sk5/egress 键、running 为布尔 | R15 gate-mutant（status 恒 500 → 28/1，资产已失，见 §2.4） |
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
| 29 | §7 钉死哈希逐键相等 | 全程末 | 4 个命名哈希逐键相等且非空 | **本轮 m-bc2/m-bc3/m-bc4 恰红、m-bc5 旧逻辑绿（§1.1）** |

逐格结论：29 格的触发条件与判定谓词全部可执行、无空洞断言（每格的通过条件都是一个可观测的 HTTP 状态／字段／计数／文件状态，非“代码在场”）。变异红证方面：§7 格本轮 8 棵变异树全覆盖；其余格子的红证沿用历史轮次（R2/R4/R6 各变异实证，见表内“沿用”标注）——本轮未逐格重建旧变异树（/tmp 已失，见 §2.4），干净树 29/29 全绿是本轮 fresh 证据。

注（SKIP-only exit 0，设计属性、不立案）：端口被占／venv 失败／pip 失败三分支均 `skip` 后 `exit 0`（PASS=0 FAIL=0 SKIP=1）。门禁的退出码契约是“退出码＝FAIL 数”，SKIP 不计 FAIL；汇总行恒打印 `PASS=0 FAIL=0 SKIP=1`，读输出者可见“什么都没测”。这是 R2 期定下的设计，不是判据失真（没有一格谎称通过），记为已核对的设计属性。

### §2.2 新发现 R16-P2-1（P2）—— §7 只比命名常量值，不比运行时绑定

**机制谓词**：`verify-integration.sh` §7 格宣称执行的 invariant 是根 README:198 的“`install.sh:63-66` 与 `agent/agent.py:122-132` 哈希块逐键相等”；但格子的实际判定只比两个文件的**命名常量值**（install.sh 的 `NAME="…"` 赋值 vs agent.py 的同名常量 `NAME = ("…")`）。agent 侧的运行时绑定并不在常量上——`_pinned_sha256(binary, arch)`（`agent.py:143-145`）读的是 `_PINNED_SHA256` 字典（`agent.py:135-140`），字典的 4 项把 `(binary, arch)` 映射到常量；install.sh 侧的运行时绑定是 `:366-367`／`:405-406` 的 arch→变量 case 映射。常量值不变、字典映射互换时，§7 仍绿，而安装校验取错哈希。

**位置**：`verify-integration.sh:583-594`（§7 循环只读常量）；`agent/agent.py:135-140`（字典）；`install.sh:366-367`／`:405-406`（case 映射）。

**复现（本轮亲手跑）**：
- `/tmp/r16/mutants/m-bc1`——只把 `_PINNED_SHA256` 里 sing-box 两项的值互换（常量逐字不动）：门禁 **PASS=29 FAIL=0**，§7 格明文 `[PASS] 钉死哈希一致…逐键相等`。
- `/tmp/r16/mutants/m-bc7`——tun2socks 两项值互换：同样 **29/29**，§7 PASS。
- 后果单元直测（非门禁，是运行时行为）：`_pinned_sha256("sing-box", "amd64")` 在干净树上返回 `950af37e…`（amd64 哈希），在 m-bc1 上返回 `20a6a9cd…`（arm64 哈希）——amd64 节点上 agent 会拿 arm64 哈希验 amd64 二进制，安装时 fail-closed（`verify_asset` 不匹配即停），非静默损坏，故 P2。
- 对照：m-bc2（常量值互换）／m-bc3（install.sh 赋值互换）／m-bc4（改一位）均 28/1、§7 恰红；m-bc5（旧集合逻辑＋常量互换）29/29——BC 的常量级逐键比对确实关了 R15-P2-1 的洞，漏的是下一层绑定。

**全集（机械推导）**：agent.py 字典 4 项，任一对值互换（C(4,2)=6 种）全部过门禁；install.sh 的两处 case 映射互换见 §2.3。R15 §1.6 的修法原文点名“从 agent/agent.py 取 `_PINNED_SHA256` 字典 4 项，逐键相等”——BC 取了字典复用的常量而非字典本身，修法执行偏了一层；§7 注释“互换任一对标签的值亦红（BC 路报告）”在字典层不成立。

**与 R15-P2-1 的关系**：同族残留，不是同一条。R15-P2-1 记的是“集合级校验对常量值互换全盲”；R16-P2-1 记的是“常量级校验对字典绑定互换全盲”。谓词不同（值互换 vs 绑定互换），变异树不同（m-gate-swap/m-gate-swap2 vs m-bc1/m-bc7），按新口径另立，不计为 R15-P2-1 复发。

**修法**：§7 增加字典绑定校验——解析 `_PINNED_SHA256` 的 4 项 `(binary, arch): CONSTANT`，逐项要求常量名后缀与键的 arch 一致（`("sing-box","amd64")` 须指向 `SINGBOX_SHA256_AMD64`），且解析出的值与 install.sh 同名赋值相等；或直接比对字典解析出的 `(binary,arch)→哈希` 与 install.sh 的逐键值。§7 注释“互换任一对标签的值亦红”须随校验扩展而成立，否则收窄为“常量值互换”。install.sh 的 case 映射同款加静态断言（`amd64) pinned="$SINGBOX_SHA256_AMD64"`）亦可一并做，见 §2.3。

### §2.3 扫全集后确认关闭的同族点与观察

- **install.sh 用量互换（m-bc6，观察、不立案）**：`:366-367` 改为 amd64 取 `$SINGBOX_SHA256_ARM64` 后门禁仍 29/29——但这不在 §7 宣称的 invariant（跨文件值相等）内：用量互换不改变任何一处的值，§7 的判定按其宣称本就该绿。下载路径的绑定由 live 轮真实下载（sing-box/tun2socks 两次 `sha256 OK`，live-10 §3）＋代码检查覆盖。门禁整体从不跑 `install_singbox` 的钉死校验路径，属门禁覆盖边界，写明、不另立案。
- **双文件同错**：两边哈希同错仍过门禁，只在安装时 fail-closed 被发现——R15 §1.6 已记为 scope 外局限，本轮不重立。
- **§7 空值分支**：m-bc8（删一常量）§7 红 ✓——BC 的非空检查在位；删除常量同时使 agent import 报 `NameError`（字典引用它），附带证明常量在运行时 load-bearing。
- **其余 28 格的谓词**：逐格核对见 §2.1 表——无“存在即绿”式空洞断言；每格的失败分支均为 `bad`（非 SKIP），门禁对任一格失效都会计 FAIL、退出码非零。干净树 29/29 是本轮 fresh 证据。

### §2.4 证据链核对（R1–R15“已修”结论的证据落盘情况）

- **探针文件**：R13/R14/R15 的探针与变异树已全部随 /tmp 清理消失（§0 实测；全盘搜寻零副本；/tmp 是 tmpfs，重启即清）。唯一幸存的是 `/tmp/r11/`（R11 期资产：`agent_hash_demo.py`、`gate7.sh`、`m-gate-char`、`m-gate-swap`、`package.sh`、`tree-base`）——树基线是 R11 期旧树（AS/AT/AU/AV 之前），期望已过期，不可作本轮证据，记明、不沿用。
- **报告内数字自洽**：R15 §4 的 366 格＝Flask 213＋Core 45＋Agent 21＋Worker 58＋门禁 29，算术复核 213+45+21+58+29=366 ✓；R15 §1.4 的门禁 29/29 本轮在干净树上重跑复现 ✓；live-10 在 R15 引用时 210 行（§§18–20 待填），现 228 行已完工——行数差是报告补完，非数字矛盾（§8.2）。
- **结论**：证据链的“报告内数字”自洽；“探针／变异树落盘”已断（/tmp 清理所致，非审计造假）。本轮按机制重建（门禁 8 棵新变异树＋flmx 核查脚本），路径写进 §0／§4；R13–R15 的旧变异树无法复用，其结论改由 §3 的 mtime 规则＋本轮门禁重跑承接（见 §3.3）。

## §3 全量复扫（历史 144＋R15 的 2＝146 条逐条定性）

复扫宇宙：R15 的 144 条（141 已修＋2 部分＋1 未验，见 AUDIT-R15 §3.4）＋R15 本轮新发现 2 条＝**146 条**。定性口径与 R14/R15 同款（已修／部分／未验／复发）。台账链（每轮“历史数”＝上轮历史数＋上轮新发现，live bug 在立案轮次并入）：R8 115 → R9 115（R8 的 8 条未修在 R9 波修完，112 已修；R9 新 5 条另计）→ R10 122（＋R9 的 5＋live-8 的 2）→ R11 123（＋R10 的 1）→ R12 125（＋R11 的 2）→ R13 134（＋R12 的 9）→ R14 141（＋R13 的 7）→ R15 144（＋R14 的 3）→ **R16 146（＋R15 的 2）**。115 基底的内部考古（R1–R8 审计发现＋live-1～live-7 bug 的去重并账）引 R8/R9 §3，不重算——早期报告混用多种编号（R1 无 R#-P# 式编号、live bug 与审计发现互有折叠，如 R5 的 7 条含 R4-BUG-1/2、R8 的 8 条含 R7-BUG-1～4），重算会造假账；本轮复扫以每轮 §3 的定性＋mtime 对账＋改动面行为重验为准。

### §3.0 mtime 对账（R15 §0 → 本轮，UTC）

自 R15 后动过的文件仅 9 处（§0 表：`verify-integration.sh` BC、8 份文档 BD）；其余文件 mtime 与 R15 §0 逐项一致（panel/app.py 17:20:11、core 17:20:57、agent 16:46:20、index.js 16:45:26、install.sh 16:46:54、index.html 15:21:57、verify.sh 14:45:28、egress 两文件 12:37:13／12:13:01）。panel/data/ 仍空。

### §3.1 R15 的 2 条关闭（本轮行为重验，变异红证见 §1.1／§1.5）

| 项 | R16 状态 | 证据 |
|---|---|---|
| R15-P2-1 门禁 §7 集合盲区 | **已修** | §1.1：干净树门禁 29/29；m-bc2/m-bc3/m-bc4 恰红（常量互换／赋值互换／改一位）；m-bc5 旧逻辑对照绿（BC 修复是关闭原因）。**但同族残留另立 R16-P2-1（§2.2）**——BC 只比常量值，字典绑定未比；不是同一条（R15-P2-1 记的是集合级校验，R16-P2-1 记的是常量级校验的下一层绑定） |
| R15-P2-2 交付文档宣称不符 | **已修** | §1.2／§6：门禁计数 2 处→29、flmx 32+3 行逐行核实全符、render 签名两处 6 参、Worker 56 格、卸载指引补全、security grep `-rnw` 0 命中、server-mode 改写分歧、panel/README 登录覆盖改写、README:198 逐键相等、README:251 工具栏改写 |

### §3.2 动过文件内的其余历史项（全部重新验证，本轮探针／grep）

- `verify-integration.sh` 内：门禁 29/29（§1.1）＋8 棵变异树（§1.1 表）；§7 新格盲区是本轮新发现（§2.2），不是旧项复发。R2-P1-4（登录后 status 格）由干净树 29/29 全绿覆盖；R4-P1-1／R4-BUG-1（SK5 保存／风暴格）同上。
- 8 份文档内：R13-P2-7（flmx 钉位）——全树 grep `SCRIPT_VERSION`／`resolve_version` 正文归零（审计报告除外）；R10-P2-1（文档数字过期）——本轮同族复查：过期 28 计数归零、旧数字 `1404`／`570-597`／`630-657` 归零（§1.3）；R14-P2-3（cloudflare/README:135 钉位）——`agent.py:676`／`:687` 在该文档归零（钉位已删）；R15-P2-2 的其余项见 §3.1。**全部已修，无一复发**。
- 其余文档宣称：§6 全量核对（9 份文档逐项，含 flmx 32+3 行逐行表）；两处观察（2-7 的 .72 两处、3-6 行引用漂移）见 §6.3，不立案。

### §3.3 其余文件内的历史项（R15 实证沿用＋本轮门禁重跑侧面覆盖）

产品代码文件（panel/app.py、core、agent、index.js、install.sh、egress、index.html、verify.sh）mtime 与 R15 §0 逐项一致，R15 的行为证据（Flask 213 格＋Core 45 格＋Agent 21 格＋Worker 58 格，见 AUDIT-R15 §4）按 mtime 规则沿用（同日、数小时内，复核时效内）；本轮门禁 29/29 重跑侧面覆盖 panel→队列→agent→core/egress 全链（登录、status、SK5 保存／翻转／风暴／补策略、agent poll/report、create_user 失败路径、无泄漏）。§2 的门禁反向审计逐格核对未发现复发信号。**R15 的 141 条中无一复发**——已登记的谓词逐条皆绿；本轮 1 条新发现是同族残留（谓词不同，见 §3.1 表末与 §2.2），按新口径另立，不计为复发。

### §3.4 部分与未验（不变）

| 项 | R16 状态 | 证据 |
|---|---|---|
| P0-3 bundle/install-agent.sh | **仍部分** | 逻辑已修（Flask agent-bundle 格 200＋tarball 含 agent.py；verify.sh install-agent-script 200）；部署态未验（§5） |
| P1-7 改密＋首登强制改密 | **仍部分（按设计）** | 改密 API＋UI 在位（Flask 改密、Worker 501 诚实端点）；首登强制改密从未实现、文档已诚实（根 README:260），不另立案 |
| P0-1 部署态 | **仍未验** | §5：登录卡住＋KV 占位，与 R7–R15 同卡点 |

### §3.5 U-1～U-12 认领表更新（R15 §3.5 → 本轮）

| # | 项 | R16 更新 |
|---|---|---|
| U-1 | P0-1/2/3 部署态 | 仍未验（§5） |
| U-2 | R6-P1-1 真机复现 | 关闭（live-8 headline-5 显式重跑通过） |
| U-3 | UDP 数据面 | 关闭（live-7 S1/S2＋live-8 S2＋live-10 S1/S2 再证 TCP+UDP 均走 SK5） |
| U-4 | R 符号链接自拷 | 关闭（无变化） |
| U-5 | R 逐项失败 die 分支 | **关闭（本轮）**：live-10 §17 已落盘——U-5a 预检 die exit 1、U-5b 下载 die exit 1、U-5c 中途 kill 后清理重跑成功；三处致败均诚实失败（R15 §3.5 记“待 live-10 报告补完”，现已补完） |
| U-6 | T 两变异 | 关闭（R8 已判；R9 T 变异重跑 17/2/4） |
| U-7 | verify-integration 瞬时红 | 关闭（R9–R15 七次 28/28 或 29/29，本轮 29/29 一次过） |
| U-8 | 真机在位升级路径 | **关闭（本轮）**：live-10 §18 headline-9 已落盘——毒树默认重跑行级比对全一致（R15 §3.5 记“待 live-10 报告补完”，现已补完；依据不再只凭 live-9） |
| U-9 | KV 竞态与 POP 传播 | 仍未验（无部署） |
| U-10 | 前端渲染级核查 | 关闭（live-9／live-10 headline-7 真机渲染通过；本轮静态核查 10/10 与之致，§7） |
| U-11 | easy-rsa 真二进制签发 | 关闭（live-8 headline-2 以 real easyrsa 3.1.0 裁决） |
| U-12 | live-R5 结果 | 关闭 |

复扫合计：146 条＝已修 143（141＋§3.1 关闭的 2 条）／部分 2（P0-3、P1-7）／未验 1（P0-1）；**本轮新发现 1 条另计（R16-P2-1，见 §2.2／§8 差集）**。146＝143＋2＋1；无一复发。

## §4 套件重跑汇总（本轮亲自重跑，见 §1／§2）

| 套件 | 规模 | 本轮结果 | 备注 |
|---|---|---|---|
| 门禁 verify-integration.sh（树内） | 29 格 | **29/29，EXIT=0** | ＋8 棵变异树（§1.1）：m-bc2/3/4/8 恰红、m-bc5 旧逻辑对照绿、m-bc1/7 新发现、m-bc6 观察 |
| Flask inputs／adv／nodeparam／diskfull／lockout／download／changepw／lifecycle／unswept／env／href | 213 格（R15 数） | **未原样重跑** | 探针文件已随 /tmp 清理消失（§0）；产品代码 mtime 与 R15 §0 逐项一致，R15 证据沿用；门禁 29/29 侧面覆盖全链 |
| Core／AU／dns | 45 格（R15 数） | **未原样重跑** | 同上；core 文件未动（mtime 17:20:57＝R15 基线） |
| Agent | 21 格（R15 数） | **未原样重跑** | 同上；agent 文件未动；另：m-bc1 后果单元直测 `_pinned_sha256` 本轮新跑（§2.2） |
| Worker inputs／Y 矩阵／bodies／lockout | 58 次执行（R15 数） | **未原样重跑** | 同上；index.js 未动；cloudflare/README:251 的 56 格口径本轮 grep 核实（§1.2） |
| verify.sh（门禁） | 23 格 | **全量分段未重跑** | R10–R15 同款记账；`bash -n` 过；live-10 headline-6 双态真机通过（开 18/0/4、关 23/0/0） |
| test-egress.sh §6 矩阵 | 4 格 | **未重跑** | R9 沿用；egress 文件未动 |

探针资产清单（R16，/tmp 可能被清空、路径写进报告以备重建）：`/tmp/r16/tree`（现树副本）、`/tmp/r16/mutants/`（m-bc1～m-bc8 八棵门禁变异树）、`/tmp/r16/build-mutants.py`（变异树构建器）、`/tmp/r16/flmx-verify.py`（flmx 32+3 行核查脚本）、`/tmp/r16/gate-tree.log` 与 `/tmp/r16/gate-m-bc*.log`（门禁运行日志）、`/tmp/r16/wrangler-deploy.log`（§5 真 deploy 报错原文）。

**本轮未重建的 R13/R14/R15 探针（诚实记账）**：r13_inputs.py（86）、r13_adv.py（28）、r13_nodeparam.py（45）、r13_diskfull.py（5）、r13_lockout.py（5）、r13_download.py（12）、r13_changepw.py（7）、r13_lifecycle.py（8）、r13_env.py（3）、r13_href.mjs（6）、r13_core.py（19）、r13_au.py（20）、r14_dns.py（6）、r13_agent.py（21）、r13_worker_inputs.mjs（23）、r13_worker_y.mjs（13）、r14_worker_bodies.mjs（9）、ay_lockout.mjs（13）、r14_unswept.py（6）、r15_sweep.py（2）——文件已失，且报告机制未逐格枚举全部 cell（如 inputs 86 格只在报告中点名 H9/H10/H11/D10/O1/O10/X10/X11 等少数格），**无法按原样重建、亦无法冒充其数为本轮数**。BC/BD 改动面（门禁＋文档）与 R16-P2-1 本身均已逐格行为验证（§1／§2）；产品代码零改动，R15 的 366 格证据按 mtime 规则沿用。下一轮审计若 /tmp 仍空，须先重建探针（以各报告 §1 的机制描述为准）再谈逐格对照；或把探针纳入树内版本管理（建议，见 §8.4）。

## §5 P0-1/2/3：真实 wrangler deploy 重验——卡在登录，仍未验

- **dry-run 通过**（本轮重跑，wrangler 经 npx，自 `cloudflare/` 目录）：`npx wrangler deploy --dry-run` exit 0——绑定列出 `env.PANEL_KV (REPLACE_WITH_KV_NAMESPACE_ID)` 与 `env.PANEL_MODE ("cloudflare")`。dry-run 只证配置可解析，不证部署。
- **真 deploy 卡在第一步：无登录**（本轮重跑，exit 1）：`In a non-interactive environment, it's necessary to set a CLOUDFLARE_API_TOKEN environment variable for wrangler to work.`（与 R7–R15 同一卡点；本机 `~/.config/.wrangler/` 下只有 logs＋metrics.json、无登录态，环境变量 `CLOUDFLARE_API_TOKEN` 未设置）。`wrangler.toml:32-33` 的 KV id 与 preview_id 仍是占位符 `REPLACE_WITH_KV_NAMESPACE_ID`／`REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`，是第二道卡点。
- **需要用户做的事（按顺序，缺一不可，与 R15 同款）**：(1) 在 Cloudflare 账号上建 API token（Workers＋KV 权限）并以 `CLOUDFLARE_API_TOKEN` 交给部署环境，或在可交互终端跑 `wrangler login`；(2) `wrangler kv namespace create PANEL_KV` 与 `--preview` 各一次，把返回的真实 id/preview_id 填进 `wrangler.toml`；(3) `wrangler secret put ADMIN_PASSWORD` 与 `wrangler secret put AGENT_BUNDLE_ORIGIN`；(4) `wrangler deploy`，再按 cloudflare/README:83 的要求换第二出口多点核（Workers 按 POP 慢速传播，单出口“没生效”不可信）。
- **结论**：P0-1/2/3（Worker 真实部署态）**仍未验**，与 R15 结论一致；Worker 代码侧的全部行为断言只在 mock KV＋本地 fetch 入口下成立，不是部署态证据。`--temporary` 未用——那会把 Worker 部署到临时抛弃账号上，不是用户的部署，测了也是冒充结论。

## §6 文档宣称全量核对（9 份交付文档）

### §6.1 逐文档结论

| 文档 | 核对结果 |
|---|---|
| 根 README.md | 属实；R15 §6 的 3 处问题本轮全部关闭：:226 门禁 29（§1.2）、:251 工具栏“非逐字 Tailwind class”（§1.2）、:198“逐键相等”（§1.1）。:249/:253/:260 三处既定口径与 flmx 表一致（§6.2） |
| panel/README.md | 属实；R15 的 2 处问题关闭：:23 登录覆盖改写（§1.2）、:58 render 签名 6 参（§1.2） |
| cloudflare/README.md | 属实；R15 的 2 处问题关闭：:251 56 格（§1.2）、:135 钉位已删（§1.3 grep 归零） |
| cloudflare/server-mode.md | 属实；R15 的 1 处问题关闭：:21 sent 态改写为两端分歧（§1.2） |
| core/README.md | 属实；R15 的 1 处问题关闭：:21 render 签名 6 参（§1.2） |
| agent/README.md | 抽查属实（R15 §2.2(d) 结论沿用：文件自 02:48 未动，mtime 一致） |
| egress/README.md | 属实；R15 的 1 处问题关闭：:210 29/29（§1.2） |
| docs/security.md | 属实；R15 的 1 处问题关闭：:7 自测 grep `-rnw` 实测 0 命中（§1.2） |
| docs/flmx-reference.md | 32+3 行逐行核实见 §6.2；其余行（不抄／改写行）抽查与文件结论一致 |

### §6.2 flmx-reference.md 32+3 行逐行核查（本轮独立验证）

方法：`/tmp/r16/flmx-verify.py`＋人工跟进——每行谓词独立 grep／代码核实，不照抄 R15 结论。“零命中”口径为产品代码（`*.py`／`*.js`／`*.sh`／`*.html`），不含 flmx-reference.md 自身行文（该文档引用术语本身即命中，如 `TableName` 在自身行文 1 处、产品代码 0 处）。

| 行 | 文件结论 | 本轮核实 | 证据要点 |
|---|---|---|---|
| 0-1 | 未抄（待定） | ✓ | `"code"` 三端 0 命中；三端一律 `{ok, error}` |
| 0-3 | 未抄（待定） | ✓ | `TableName` 产品代码 0 命中 |
| 1-4 | 照抄 | ✓ | `--force` :81、备份 `config.json.bak.<ts>` :127-128 |
| 1-5 | 照抄 | ✓ | `token_urlsafe(32)`×2；管理员密码 `token_urlsafe(16)`×1（22 字符，文字偏差已注） |
| 1-6 | 未抄（待定） | ✓ | `OVPN_VERSION` 产品代码 0 命中；无 `panel/.env` |
| 1-8 | 照抄 | ✓ | `install.sh:739` 起 PKI 守卫 |
| 1-9 | 未抄（待定） | ✓ | 无卸载脚本（`uninstall` 命中仅两处文字提及）；README:265 手动命令 |
| 1-10 | 照抄 | ✓ | Worker `installCommand`＋`/install` 路由 |
| 1-11 | 未抄（待定） | ✓ | `channel` 仅 `agent.py:670` 英文注释一处；`VERSION = "0.1.0"` 静态 |
| 1-13 | 照抄 | ✓ | bundle sha256 端点 21 处 |
| 1-14 | 照抄 | ✓ | `--panel-url` :75、`--token` :76 长选项 |
| 1-15 | 照抄 | ✓ | 两边 4 命名哈希逐键相等（门禁 §7 同款） |
| 1-17 | 照抄 | ✓ | `reset-failed`＋`ovpn-agent.service` |
| 1-21 | 未抄（待定） | ✓ | `Sk5ProfileID`／`OutboundIPStrategy` 产品代码 0 命中 |
| 1-24 | 照抄 | ✓ | `_port_occupant` 4 处 |
| 1-25 | 照抄 | ✓ | `index.js` UDP/test_sk5 13 处；`index.html` 含 confirm |
| 1-27 | 照抄 | ✓ | `_agent_auth`／rotate 4 处 |
| 1-29 | 未抄（待定） | ✓ | 唯一 429 是登录锁 `app.py:1249` |
| 1-32 | 未抄（待定） | ✓ | `index.html` version 0 命中；nodes 表含 `last_seen` |
| 2-2 | 未抄（待定） | ✓ | `sidebar_collapsed` 产品代码 0 命中 |
| 2-4 | 部分抄 | ✓ | 节点表无“版本”、有复制安装命令 |
| 2-5 | 未抄（待定） | ✓ | modal／`presets.ts` 0 命中 |
| 2-6 | 部分抄 | ✓ | Tailwind 0 命中；sticky 仅 `:66`（侧栏） |
| 2-7 | 照抄 | ✓ | `rgba .70`（:60/:105/:228）、`.60`（:89）、blur 16–24px（.72 两处见 §6.3 观察） |
| 2-8 | 照抄 | ✓ | `box-shadow` 10 处，三档结构 |
| 2-9 | 照抄（流程） | ✓ | `contrast-check.py` 在位、10/10（§7） |
| 2-10 | 部分抄 | ✓ | `sk5User` 字段 600 字符内无 `session-` |
| 3-1 | 未抄（待定） | ✓ | `PwdChangeRequired` 产品代码 0 命中 |
| 3-3 | 未抄（待定） | ✓ | JWT 三端 0 命中；会话 12 小时 |
| 3-4 | 部分抄 | ✓ | bcrypt 15 处；dummy 0 处 |
| 3-6 | 照抄（流程） | ✓ | 前置守卫在 `:120-128`（行引用见 §6.3 观察） |
| 3-7 | 未抄（待定） | ✓ | `MonitorPermission` 产品代码 0 命中 |
| 3-8 | 未抄（待定） | ✓ | `RoleID` 产品代码 0 命中 |
| 3-9 | 部分抄 | ✓ | README:253 明文口径；`_atomic_write_json` 6 处 |
| 1-16 | 部分抄 | ✓ | `install-agent.sh:41-44` 沿用旧 token；`sk5.json` 0 命中 |

35 行全部与文件结论一致；计数复核：`未抄（待定）` 18 行、`部分抄` 8 行（§1.2）。

### §6.3 观察（已核实，不立案）

- **2-7 的 .72 两处**：`index.html:131`／`:144` 的玻璃底色为 `rgba(255,255,255,.72)`，略高于行文“0.6–0.7”带 0.02；其余值（.60/.70）落在带内，blur 16–24px 属实。实质宣称（玻璃值照抄、透明度适中）成立，带宽措辞近似——R15 已按“基本真”定级，本轮不重立。
- **3-6 的行引用漂移**：行内引用的 `install-agent.sh:95-99` 现为 `/root/flmx-panel` 守卫段，实质的前置守卫（已有部署须 `--force`＋备份）在 `:120-128`。机制属实，引用行号过期——flmx 表内联引用非交付门禁钉位（R14-P2-3 覆盖的是 cloudflare/README 的钉位），不另立案；下一轮文档改动时顺手同步行号即可。

## §7 前端对比度核查

`python3 panel/static/contrast-check.py`：**10/10 PASS**（底线 4.5），目标 7 达成 4/10——逐值与 R10–R15 一致（正文 14.41、次要文字 7.42、主按钮 5.17、次按钮 7.56、危险按钮 6.47、成功绿字 4.92、徽标绿 6.49、徽标红 6.80、激活导航 8.65、链接 6.58）。交叉验证：live-10 headline-7 真渲染（CDP 驱动，1440×900）：可见文字 181 个，低于 4.5 者 0 个，最薄 4.92（成功绿字 #15803d），JS 异常 0 个。两路一致。观察（不立案，live-10 同款）：面板未提供 `/favicon.ico`（每次进站一条 404）；测试机 headless 环境中文呈豆腐块（缺 CJK 字体，非产品问题）。

## §8 结论

### §8.1 verdict

**不能交付，差集 1 条（P2×1）**：

| 编号 | 级别 | 机制 | 复现／证据 | 修法 |
|---|---|---|---|---|
| R16-P2-1 | P2 | 门禁 §7 逐键比对只比命名常量值，不比 agent.py 的运行时绑定 `_PINNED_SHA256` 字典；字典内任一对值互换，门禁仍 29/29，而 amd64/arm64 安装校验取错哈希、安装时 fail-closed | 变异树 `/tmp/r16/mutants/m-bc1`（sing-box 字典互换）与 `m-bc7`（tun2socks 字典互换）：门禁均 29/29，§7 格明文 PASS；单元直测 `_pinned_sha256("sing-box","amd64")` 在 m-bc1 上返回 arm64 哈希 `20a6a9cd…`（干净树为 `950af37e…`）；全集：字典 4 项任一对互换（C(4,2)=6 种）全部过门禁 | §7 增加字典绑定校验（解析 4 项 `(binary,arch): CONSTANT`，逐项要求常量名后缀与键的 arch 一致，且解析值与 install.sh 同名赋值相等）；§7 注释“互换任一对标签的值亦红”随校验扩展而成立，否则收窄为“常量值互换” |

P 级说明：P2——后果是安装时 fail-closed（amd64/arm64 节点装不上 sing-box/tun2socks，安装器报错即停），非静默损坏。无 P0/P1 新发现。BC/BD 修复本身除本条同族残留外全部行为验证通过（§1，变异红证齐全）；历史 146 条无一复发（§3）。

### §8.2 live-10 对账（报告已完工，以完工报告为准）

live-10 报告 `docs/live-verify-R10.md`（**228 行，§§0–20 全填，已完工**）——R15 §8.2 称其“§18–§20 待填”已过期，以完工报告为准对账：
- **结论：全部通过，新 bug 0 条。** S0–S4 全过；R13 七条真机格全过（P2-1 垃圾 sent_at 标 failed＋审计、P2-2 port=0/False 抛错、P2-3 三路径 403、P2-5 agent 拒 port=True、P2-6 非默认子网安装 die；P2-4 沙箱 23/23、真机无 Worker 部署记未验；P2-7 沙箱 grep 归零）；headline-1～9 全过（首启一次 200＋10 次交替 delta 恰 10、并发建用户 200+409、并发启用 delta 恰 1、policy-routing.sh 干净输出、policy-missing 诚实＋零重起修复、verify.sh 开 18/0/4 与关 23/0/0、前端真渲染 181 文本 0 低于 4.5 最薄 4.92、D13 并发重跑胜者干净成功／败者死于 apt 锁零写盘、U-5 三处致败均诚实失败且重跑成功、毒树默认重跑行级比对全一致）。
- **U-5、U-8 本轮关闭**（§3.5）：U-5（live-10 §17 三处致败）、U-8（live-10 §18 headline-9 毒树重跑行级比对）。
- **R14 的 3 条真机格不在 live-10 简报内**（live-10 验收的是 R13 的 7 条修复；R14 的 3 条沙箱已闭，见 §3.1）——真机格待 live-11，不得默写为已验。
- **R15 的 2 条**：P2-1 的绑定错位后果（agent 侧安装校验失败）须真机 amd64/arm64 双架构格验证，待 live-11；P2-2 为文档项，真机格不适用，改后 grep 复核已过（§1.2／§6）。
- **R16-P2-1 的真机格**：字典互换的后果（amd64 节点安装校验取错哈希）同样须真机 amd64/arm64 双架构格验证，待 live-11。
- 未验（与 live-10 头部一致）：Cloudflare 真实部署（P0-1/2/3）、SK5 真实 IPRoyal 端口（1001 vs 9000，用户未确认）。

### §8.3 未验清单

1. **P0-1/2/3 真实 wrangler deploy（§5）**——卡在 Cloudflare 登录（非交互环境须 `CLOUDFLARE_API_TOKEN`，`~/.config/.wrangler/` 无登录态；wrangler.toml 的 KV id 与 preview_id 仍是占位符）。谁能验：用户建 API token（或交互式 `wrangler login`）＋`wrangler kv namespace create PANEL_KV`（生产＋预览）填实 id＋`wrangler secret put ADMIN_PASSWORD`／`AGENT_BUNDLE_ORIGIN` 后，live 路跑真实 `wrangler deploy`，再从第二出口核 POP 传播。本轮不许用 mock 冒充。
2. **Cloudflare KV 竞态＋POP 传播**——依赖第 1 项的真实部署；无部署则无从测。谁能验：同第 1 项，部署后多点核。
3. **SK5 端口 1001 vs 9000**——用户从未确认哪个是 SOCKS5 口（面板默认 1001，文档已标注待确认，README:137＋index.html:470-471）。谁能验：用户回报；live 路再以确认后的端口跑 UDP/TCP 双栈。
4. **D13 PKI 段竞态**——沙箱无 easyrsa 二进制，两路并发安装／重跑时 `init_pki`＋`build-ca` 的先查后建竞态测不到（copy 段已验，见 R9 §2）；live-10 §17 的 D13 实测冲突形态是 apt 锁早夭（安装器无安装锁，败者零写盘——live-10 定性不立案，R16 不重立）。谁能验：live-11 在真机上跑并发安装／并发重跑（须先确认 PKI 段可达性）。
5. **D14 时钟跳变**——沙箱无 faketime，改系统时钟超出审计范围；仅代码级分析（锁定／会话／重投／健康全是墙钟）。谁能验：真机上以 faketime 或受控调钟复核（须用户授权调真机时钟）。
6. **Flask 35/35 与 r12_inputs2/3/4 未原样重跑**——AH 的 flask35.py 与三套件探针文件已随 /tmp 清理消失（R13 §8.4 同款记账；本轮 §4 再记）；本轮 Flask 面由门禁 29/29（全链）＋R15 证据（mtime 沿用）覆盖，但 35 格与三套件逐格对照缺失。谁能验：下一轮审计重建探针或等效套件；live-10 的真机 S0–S4 覆盖同一面的行为。
7. **verify.sh 全量分段未重跑**——R10 的 vfy harness 已失，本轮只做了 `bash -n`；全量分段数沿用 R9。谁能验：live-10 headline-6（verify.sh 双态真机跑：开 18/0/4、关 23/0/0）即该门禁的真机总验。
8. **R14 的 3 条与 R15 的 2 条、R16 的 1 条的真机行为格**——本轮全部沙箱行为验证（§1／§2）；真机后果（R16-P2-1 的字典互换在 amd64/arm64 真机安装上的表现、R15-P2-1 的常量互换同款）未在真机上证实。谁能验：live-11（live-10 简报验收的是 R13 的 7 条，不含这 6 条）。
9. **R13-P2-6 的真机断流后果**——沙箱已证规则与 server.conf 错位（exit 0）；真机上客户端流量是否真黑洞未证。谁能验：live-10 以非默认 OVPN_SUBNET 装一台真机、走一遍客户端流量（R13 §8.3 第 10 项沿用；AZ 修后该输入已 die，live-10 若仍按旧简报跑非默认安装，应先确认安装器行为已变）。

### §8.4 审计方法自述（供 R17 复核）

- 本轮方法：门禁与证据链反向审计（§2，从交付判据本身的可信度出发：29 格逐格机械推导＋变异红证，再核报告链证据落盘，最后功能链全量复扫）＋历史全量复扫（§3，146 条，mtime 对账＋改动面逐项重验）＋BC/BD 新代码逐项行为验证（§1，亲自重跑、零 monkeypatch 走真实代码路径、8 棵定点变异树红证）＋套件重跑（§4，门禁 29/29＋8 变异；其余套件探针文件已失，诚实记账、不冒充）＋P0 部署态重验（§5）＋文档宣称全量核对（§6，含 flmx 32+3 行逐行表）＋前端静态对比度核查（§7）。
- 探针纪律：凡套件格先红，必先查探针本身（本轮修掉的核查脚本问题：flmx-verify.py 初版把 `docs/flmx-reference.md` 自身行文计入“全树零命中”、grep 前导 `--` 被当作选项、`rgba` 正则未命中 `.70` 写法、install-agent.sh 行窗取偏——逐项跟进人工复核后才定性，不在核查脚本 artifact 上立案）。
- 沙箱边界：无 systemd／无 TUN／无 easy-rsa／无 openvpn 二进制／UDP sendto 临时端口 EPERM——凡涉此五项的结论均已标注分段环境或待真机（live-11），未把沙箱结论写成真机结论。门禁的桩 sing-box/systemctl/ip 均以状态化假件建模，其行为以 live-9/live-10 真机证据为锚（风暴计数、策略补修、真实下载 sha256 OK），不是凭空捏造。
- 本轮审计侧污染与收尾：门禁在 `/tmp/ovpn-int-test`（nobody 所有）跑，trap 清理已验（收尾手动删净残留目录）；宿主 `/etc/openvpn-sk5-panel/`、`/etc/openvpn/` 不存在（本轮未写宿主 /etc）；8443 空闲、无残留面板进程；树内 `__pycache__`（本轮 `py_compile` 产生 4 处）已清，产品文件 mtime 与 §0 一致、未动。
- /tmp 资产（供 R17 复用）：`/tmp/r16/tree`、`/tmp/r16/mutants/`（m-bc1～m-bc8）、`/tmp/r16/build-mutants.py`、`/tmp/r16/flmx-verify.py`、`/tmp/r16/gate-*.log`、`/tmp/r16/wrangler-deploy.log`。**教训与建议**：/tmp 是 tmpfs、重启即清，R9–R16 已丢四批探针资产；建议把探针与变异树构建器纳入树内版本管理（或工作区固定备份目录），否则每轮审计都要先重建、且逐格对照永远断档——本轮 §4 的记账就是该断档的第四次复发。
- 以下裁决沿用，不重立：R5 的 Flask/Worker 重投分歧（非 bug，security.md:12 已披露）；BB 的钉位 grep 门禁不加裁决（§3.1 复核成立）；live-10 的 D13 apt 锁不立案；AS 的 0/1-int 布尔强制（R12 探针钉死）；AW 的快照时效性（与 `?node=` 分支同款属性）；P1-7 首登改密不做（按设计）；R15 §1.6 的“双文件同错 scope 外”局限。

**下一步（按用户常设流程）**：派修复路修 R16 的 1 条（只动 `verify-integration.sh` §7 一处：加字典绑定校验，见 §2.2 修法；顺带把 §7 注释的互换红证宣称写准），修完集成后跑 **AUDIT-R17（全量全局回头看，换推导方法独立复算）＋ live-11 对账**（live-11 简报须含 R14 的 3 条＋R15 的 2 条＋R16 的 1 条的真机格，其中 P2-1 两件须 amd64/arm64 双架构安装格），两路都过才交付。修复路开工前须先确认：本报告基线树版本（§0）与修复路所取树一致。

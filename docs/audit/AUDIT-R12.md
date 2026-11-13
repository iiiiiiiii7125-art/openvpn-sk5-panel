# AUDIT-R12 — 全量全局回头看（交付前）

## 结论先写

**结论：不能交付，差集 9 条（P1×2：R12-P1-1 队列手改条目楔死 agent 全通道、R12-P1-2 布尔端口写坏 server.conf；P2×7：R12-P2-1 `bool()` 把 "false" 变成 True、R12-P2-2 udp-over-tcp 读错键、R12-P2-3 Worker listNodes 无名记录崩溃、R12-P2-4 Worker /api/cmd 收 list params、R12-P2-5 Worker 忽略 body.node、R12-P2-6 install.sh 不校验 OVPN_SUBNET、R12-P2-7 cmd_get 对手改条目 500）。**

- 审计员：独立审计路（未参与建设与修复路 AK/AL/AM/AN/AO/AP/AQ/AR；单审计员边做边写，不派子代理）
- 日期：2026-11-12（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R11 同等广度）
- 推导方法：**外部输入枚举推导**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性、R9 对抗操作员＋时间衰变、R10 环境矩阵×修复存活、R11 契约闭合均不同）——先枚举树内全部外部输入面（Flask 39 路由的每个 body／query／header 参数、Worker 每个路由参数、agent 13 个动作的 params、队列文件、index.txt、状态文件、环境变量、install.sh 的环境变量与 CLI、wrangler.toml／secret），逐项枚举畸形变体（缺字段、错类型、超长、特殊字符、不存在的引用、过期值、损坏文件、磁盘满），逐格验证行为（拒绝须诚实报错、不得静默错执行、不得 500 泄漏）；再叠加历史全量复扫（R11 的 123＋2 条逐条定性）与 AK/AL/AM/AN/AO/AP/AQ/AR 新代码逐项行为验证（带变异红证）。每条推导链必须落到一条可执行的探针或一条明确的“不可验（写清为什么）”，不许只写文字推断；live-9 与本轮并行在跑，其结论未入本报告，须在 §8 写明。
- 测试一律在 `/tmp` 副本（`/tmp/r12` 树副本、`/tmp/r12-tests/` 自建 harness、复用幸存的 `/tmp/r11-tests/`（R11 探针）与 `/tmp/r10-tests/`（R10 探针）与 `/tmp/an-tests/`（AN 探针＋fakebin＋venv）与 `~/workspace/ae-tests/poison/`）上跑；未动项目原文件（除本报告）；探针进 `unshare -m` 挂载命名空间，`/etc/openvpn-sk5-panel` 与 `/etc/sysctl.d` 绑 /tmp；**例外一笔见 §8.4**：`r12_agent.py` 一次裸跑把 sk5.json 写进宿主 `/etc/openvpn-sk5-panel/`，收尾已删净；未动任何真机。需真机行为复核的项一律写“待 live-9”，不提前判通过。
- 语法基线：4 个 Python 文件 `py_compile` 全绿；7 个 shell 脚本 `bash -n` 全绿；Worker `node --check` 全绿（见 §0）。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明（与 R9/R10/R11 同款记明）。

## §0 树版本与 AP/AQ/AR 改动确认

当前树是 R11 修复路 AP/AQ/AR 之后的新树。文件 mtime（UTC）与 R11 §0 基线对照：

| 文件 | mtime (UTC) | 行数 | 说明 |
|---|---|---|---|
| install.sh | 2026-11-12 14:11:22 | 1042 | 未动（R11 mtime） |
| panel/app.py | 2026-11-12 15:17:18 | 2406（R11: 2006） | 动过（AP：兼容层 18 路读 `?node=`／body.node／`X-Node`，`_lookup_node`／`_resolve_compat_node`／`_enqueue_compat`／`_node_snapshot`；sha256 `56bf6fae…`） |
| core/openvpn_manager.py | 2026-11-12 13:14:53 | 1450 | 未动（R11 mtime） |
| README.md | 2026-11-12 15:06:33 | 277 | 动过（AQ：:260 改密模式限定） |
| verify.sh | 2026-11-12 14:45:28 | 846 | 未动（R11 mtime） |
| panel/README.md | 2026-11-12 15:06:59 | 113 | 动过（AQ：:31 API 表＋:101 入口 bullet 补模式限定） |
| egress/sk5_manager.py | 2026-11-12 12:37:13 | 1109 | 未动（R11 mtime） |
| egress/policy-routing.sh | 2026-11-12 12:13:01 | 364 | 未动（R11 mtime） |
| verify-integration.sh | 2026-11-12 09:35:55 | 567 | 未动（R11 mtime） |
| cloudflare/src/index.js | 2026-11-12 15:06:28 | 1182（R11: 1172） | 动过（AQ：`POST /api/change-password` 恒回 501＋wrangler 指引） |
| agent/agent.py | 2026-11-12 00:58:12 | 910 | 未动（R11 mtime） |
| panel/templates/index.html | 2026-11-12 15:21:57 | 1259 | 动过（AR：:748 dl.href 改走 withNode，一行） |
| panel/data/ | 2026-11-12 12:14 | 空目录 | AE 路清空后仍空；AN 的 staging 拷贝不再往里写任何文件 |
| docs/security.md | 2026-11-12 15:06:31 | — | 动过（AQ：:11 改密模式限定） |

语法基线（本轮在 `/tmp/r12/tree` 副本上实测）：`panel/app.py`、`egress/sk5_manager.py`、`core/openvpn_manager.py`、`agent/agent.py` 四文件 `py_compile` 全绿；`install.sh`、`verify.sh`、`verify-integration.sh`、`egress/test-egress.sh`、`egress/policy-routing.sh`、`core/easyrsa.sh`、`agent/install-agent.sh` 七脚本 `bash -n` 全绿；`cloudflare/src/index.js` `node --check` 全绿。

/tmp 资产现状（本轮开工时实测）：`/tmp/r11-tests/`（R11 探针＋AP/AQ/AR 探针＋harness）、`/tmp/r10-tests/`（R10 探针）、`/tmp/an-tests/`（AN 探针＋fakebin＋venv）、`/tmp/r10/`（树副本＋tree-old 回退树）、`/tmp/aq-tests/`（AQ 探针＋新旧日志）**全部幸存**；`~/workspace/ae-tests/poison/` 幸存。本轮策略：**复用 R11 探针原样跑当前树**（ap_nodeparam 45 格、ar_download 11 格、ar_href 6 格、r10_adv／r10_diskfull／r10_core／r10_lockout、r11_nodeparam、r11_worker_changepw.mjs、AN probe_bug1／probe_bug2）；venv 复用 `/tmp/an-tests/venv`（Flask 3.1.3＋bcrypt，已验）；新增 **r12_inputs.py**（本轮外部输入枚举探针，从零编写）。

（以下各节边审边写）

## §1 AP/AQ/AR/AK/AL/AN/AO 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

### §1a AP 路（R11-P1-1）——全部行为验证通过，变异红证齐全

探针：复用 `/tmp/r11-tests/ap_nodeparam.py`（45 格），真实 Flask test_client＋真实 core＋AH fake easyrsa/openvpn，`unshare -m` 绑 /etc；旧代码回退树用 `/tmp/r10/tree-old`（R10 的 AK/AL 回退树，pre-AP/AQ/AR：无 `_resolve_compat_node`、index.js 无 change-password 分支、dl.href 为旧 plain 形，`py_compile` 过）。注意：`/tmp/r11/tree` 并非 R11 时代树——其 app.py sha256 `56bf6fae…` 与当前树相同、index.js 含 AQ 501 分支，仅 index.html 仍为 pre-AR（mtime 09:20:59），是混合快照，**不能**作旧树阴性对照；本轮旧树对照一律用 `/tmp/r10/tree-old`。

| 格 | 期望 | 新树实测 | 旧树阴性对照 |
|---|---|---|---|
| AP-NODEPARAM 45 格 | ghost 7 路 404、远程写 202＋cmd_id 且命令确实入队、远程 status 取快照（非本机数据）、心跳后快照仍在、远程下载取到队列 .ovpn、本机/缺省不变、init-pki 对照 400/404 | **PASS=45 FAIL=0** | **PASS=13 FAIL=32**（32 红全在 AP 改动面；D8 例：远程 set_sk5 回 `命令不存在：None`——旧代码把远程写当本机执行、回执无 cmd_id） |

**裁决：R11-P1-1 已修。**

### §1b AQ 路（R11-P2-1）——全部行为验证通过，变异红证齐全

探针：Worker 用 `/tmp/aq-tests/r11_worker_changepw_new.mjs`（mock KV＋本地 fetch 入口）；旧树对照为同探针仅改 import 路径指向 `/tmp/r10/tree-old` 的副本（`/tmp/r12-tests/r11_worker_changepw_old.mjs`）；Flask 改密不变用 `/tmp/r11-tests/aq_changepw.py`（run-flask.sh）。

| 格 | 期望 | 新树实测 | 旧树阴性对照 |
|---|---|---|---|
| Worker 改密 | 登录 200 后改密 501＋wrangler 指引、不含“未知接口”、未登录 401、me/logout 200 | **PASS**：改密 `501`，错误串含 `wrangler secret put ADMIN_PASSWORD` | **恰红**：改密 `404 {"ok":false,"error":"未知接口"}` |
| Flask 改密不变 | 错旧密码 401、弱新密码 400、有效改密 200、旧会话 401、新密码登录 200、旧密码登录 401 | **PASS 7/7**（CHANGEPW-FLASK: PASS） | — |

代码核对：`POST /api/change-password` 分支（index.js:1106-1111）在 `requireAdmin` 之后（`if (!admin) return err("未登录", 401)` 在前），故未登录 401、已登录 501；文档四处模式限定（security.md:11、README:260、panel/README:31/:101）均在位。**裁决：R11-P2-1 已修。**

### §1c AR 路（R11-P1-1 前端残留）——全部行为验证通过

探针：`/tmp/r11-tests/ar_download.py`（11 格，run-flask.sh）＋`/tmp/r11-tests/ar_href.js`（6 格，withNode 从成品文件逐字抽取执行）。

| 格 | 期望 | 新树实测 |
|---|---|---|
| 下载路由 11 格 | ghost 404、未生成 404、快照已吊销 403、valid＋队列回执 200 且内容字节一致 | **PASS=11 FAIL=0**（E4d：200 `client\nremote 203.0.113.9 1194\nproto udp`） |
| href 单元 6 格 | currentNode=lightsail 时 href 含 `?node=lightsail`、为空时不变、特殊字符名编码、withNode 非兼容路径 guard 完好 | **PASS=6 FAIL=0** |

代码核对：仅 index.html:748 一行改动（`dl.href = withNode(...)`）；:1163 `ovpn_url` 只在本地直接执行分支由后端返回（app.py:1555，`if node is not None` 时直接入队回 202、无此字段），:1171 Blob 来自命令回执文本（本身已是正确节点配置），两处不动有理。**裁决：R11-P1-1 前端残留已修。**

### §1d AK 路（R9-P1-1＋R9-P2-1＋R9-P2-2）——全部行为验证通过，变异红证齐全

探针：复用 R10/R11 的 `/tmp/r11-tests/r10_adv.py`（D1/D1b/D1c/D2/D4/D4b/D5/D6/D9）与 `r10_diskfull.py`（D11）与 `r10_lockout.py`，旧树对照 `/tmp/r10/tree-old`。

| 格 | 新树实测 | 旧树阴性对照 |
|---|---|---|
| adv 28 格 | **PASS=28 FAIL=0** | **PASS=15 FAIL=13**（与 R10/R11 逐值一致） |
| D11 磁盘满登录 5 格 | **PASS=5 FAIL=0**（限内正密码 200、错密码 401、解除后 200） | R10/R11 已验旧树限内双 500，本轮未重跑（回退树已用于 adv 对照，机制相同） |
| lockout | **PASS**（5 错→401×5、第 6 次正确密码→429＋`retry_after_s: 900`、旧会话 status 200） | — |

**裁决：R9-P1-1、R9-P2-1、R9-P2-2 三条已修。**

### §1e AL 路（R9-P1-2）——行为验证通过，变异红证齐全

adv 探针 D9（与 §1d 同跑）：新树 V 行过期（2001）报 `expired`、重建成功；畸形 expiry（`garbage-not-a-date`）保持 valid、不抛错。旧树对照：adv 15/28 中的 D9 两格红（list 报 valid、重建抛 `UserAlreadyExistsError`，与 R10/R11 一致）。**裁决：R9-P1-2 已修。**

### §1f AN 路（R8-BUG-1＋R8-BUG-2）——全部行为验证通过，变异红证齐全

探针：原样复用 `/tmp/an-tests/probe_bug1.py`（new/old）与 `probe_bug2.py`（new-ufw/old-ufw/new-noufw），对当前树原文评估（new 路取 `~/workspace/openvpn-sk5-panel/install.sh`，sha256 `5af298b9…`）；全量 staged 全安装，fake apt/systemctl/iptables/ip＋真面板＋真 API。

| 格 | 实测 |
|---|---|
| BUG-1 新版毒包全新安装＋毒树默认重跑 | **FAILS: none**（重跑 exit 0、横幅出、登录 200、节点 lightsail 仍在、用户 alice 仍 valid、agent poll 200 回排队 get_status 命令、无 init_pki） |
| BUG-1 旧版阴性对照（install-old.sh） | **恰红**：重跑死于登录门、登录 401、admin 0 行 nodes 0 行 |
| BUG-2 新版＋ufw 长表（2000 条规则） | **FAILS: none**（2000 条原规则＋2 条新放行＝2002 行、`ufw status` 111181 字节＞64KB） |
| BUG-2 旧版阴性对照 | **恰红**：ufw 二进制消失、日志无 `ufw: allowed`、安装仍 rc=0（静默破坏，与 live-8 #3 一致） |
| BUG-2 新版无 ufw 回归 | **FAILS: none** |

**裁决：R8-BUG-1、R8-BUG-2 两条已修（沙箱侧；真机重验归 live-9）。**

### §1g AO 路（R10-P2-1）——全部验证通过

- 全树 grep `1404`／`570-597`／`630-657`／`2026-11-12 实测`（`--include=*.md,*.sh,*.py,*.js`，审计报告与 live 报告除外）：**零命中**（rc=1）；命中仅存于审计报告历史记录内（21 行，属实记录，不计）。
- `wc -l` 实测：core 1450、sk5_manager 1109，文档已不再断言具体行数。
- starter-template-consistency 门：见 §4c（按原文逐字抽取重跑 PASS）；verify-integration.sh 28/28（§4a）。
- **裁决：R10-P2-1 已修。**

### §1h Core 套件 19/19（本轮重跑）

探针：复用 `/tmp/r11-tests/r10_core.py`，真实 `openvpn_manager`＋fake-PKI＋fake easyrsa/openvpn。**19/19**：C0（PKI＋server 证）、C2（建用户 alice，.ovpn 含三段 PEM＋remote，openssl 验 CN=alice）、C3（重建拒绝）、C4（list alice valid）、C5（非法名 6/6 拒绝）、C6（吊销标 R）、C7（吊销后重建）、C8（幽灵吊销拒绝）、C9a（同值重渲染）、C9b（无 allow 改端口拒绝）、C9c（有 allow 改端口成功）、C10（无 daemon 时 server_status 诚实报 running=false 不抛错）、C11（init_pki 无 force 拒绝）、C12（同值重渲染内容一致）、C13（build_server_cert 二次调用幂等）、C1（状态日志单测 5/5：bare-v1、comma-v2、tab-v2、prefixed-7、empty/missing，夹具为真机捕获行）。

## §2 外部输入枚举推导（本轮新方法）

枚举面：Flask 39 路由的每个 body／query／header 参数、Worker 每个路由参数、agent 13 个动作的 params、队列文件（手改条目）、index.txt、状态文件、环境变量（OPENVPN_PORT／OPENVPN_PROTO／OPENVPN_SERVER_IP）、install.sh 的环境变量（OVPN_PROTO／OVPN_PORT／OVPN_SUBNET／OVPN_DNS）与 CLI、wrangler.toml／secret。畸形变体：缺字段、错类型、超长、特殊字符、不存在的引用、过期值、损坏文件、磁盘满。判定线：拒绝须诚实报错（4xx）、不得静默错执行、不得 500 泄漏。探针：`r12_inputs.py`（Flask，86 格）＋`r12_inputs2.py`（隔离复核，12 格）＋`r12_inputs3.py`（开关纯写盘复核，6 格）＋`r12_inputs4.py`（键名／allow_port_change 复核，9 格）＋`r12_agent.py`（agent，21 格）＋`r12_worker_inputs.mjs`（Worker，21 格）＋`r12_worker_y.mjs`（Worker Y 矩阵重建，13 格）＋`r12_env.py`（面板 env，三 case）＋ staged 安装 M1/M3。阴性对照：`/tmp/r10/tree-old`（pre-AP/AQ/AR）跑 `r12_inputs.py` 得 64/86——B2–B10 九格恰红（AP 改动面），H1–H6／F6／F8／D8b 与新树同红，证明本轮新发现均非 AP/AQ/AR 回归，而是旧树即有的输入面缺口。

### §2.1 通过的输入面（抽样列举，全部格数见 §4f）

- 登录／会话：缺密码 401（A1 记为观察 O1）、数字／列表／100KB 密码 401、非 JSON／数组体 400、未登录调全部 /api/* 401、未知路由 404；Worker 同款 W1–W6 全过。
- 节点参数：`?node=` 空串走本机、`../`／`%`／200 字符／X-Node ghost 一律 404；body.node 数字／列表 404；body.node 优先于 `?node=`（B9）；`?node=` 前后空格 trim 后命中（B10）。
- init-pki 破坏性门：`force`/`confirm` 用 `is True` 严格判定（app.py:1464-1472）——字符串 `"true"`／`"false"`、整数 1 一律 400，绝不重建（C3–C6）；agent 侧 `_as_bool` 同款严格（N12）。**这是全树唯一对布尔输入严格的地方**——与 §2.2 的 `bool()` 全族形成对照。
- server／users／sk5 常规校验：proto 错值／端口 0／70000／-1／字符串／浮点一律 400；用户名空／33 字符／`../x`／保留名／空格／unicode／斜杠一律 400；重建 409；删／下载不存在用户 404；编码穿越 `../` 404；sk5 host 缺失／端口错型 400；空体 400；cmd 缺 action／未知 action／shell 元字符／params 列表／ghost 节点一律 400/404；Worker 同款 W12/W13/W18 全过。
- 队列文件（AK 已修面）：naive sent_at、数字 sent_at、垃圾 sent_at、损坏 JSON、非 dict JSON——poll 200＋隔离（adv 28/28，§1d）。
- 解析器：index.txt 畸形行／空文件／状态日志垃圾行均不抛错（I1–I3）；Core 19/19（§1h）。
- agent：未知 action、params 非对象、7 个禁带键（含大小写 `CMD`）、非法用户名、坏 host、字符串布尔一律诚实 error tuple、永不 raise（N1–N15，21/21）；`_as_int` 直接核对：11080.9→11080 截断、True→1、"11080"→11080、0→ValueError（记为观察 O3：agent 侧宽松，面板门严格，面板外不可达）。
- 面板 env：OPENVPN_PORT=abc → 面板照常启动，status 200 且 `modules_missing` 含 openvpn_manager、core 路由 503（J，4/4）；OPENVPN_PROTO=bogus → status 200（import 不校验，render 时才验）。
- install.sh：OVPN_PROTO=bogus 立即明错 die（M3 对照，`[install] ERROR: OVPN_PROTO must be udp or tcp, got 'bogus'`）。

### §2.2 新发现（差集，立案见 §8）

**R12-P1-1（P1）：队列手改条目楔死 agent 全通道（R9-P1-1 同族残留）**——AK 只修了 `_requeue_stale_sent` 里的 sent_at 类型，但 `agent_poll` 与 `cmd_get` 里仍有直接键访问。实证（`r12_inputs.py` H3–H5，真实 test_client＋真实 agent token）：队列里一条 cmd 缺 `action`／`status`／`params` 任一键 → `POST /api/agent/poll` **500**，且该条目永久留在队列文件里，每次 poll 都 500——全部节点 agent 全灭，与 R9-P1-1 同级。`cmd_get` 同族（H1/H2/H6，单条查询 500）：`retries="abc"` → `int()` ValueError 500；`sent_at` 数字＋sent 态 → `fromisoformat` TypeError 500（该处只 catch ValueError，app.py:2165）；缺 `node` → KeyError 500。触发：手改 agent_queue.json（排障时清卡命令是现实操作）或未来写端 bug；AK 的损坏 JSON 隔离（D4）不覆盖“JSON 合法但字段缺/错型”。修法：poll／cmd_get／report 三处读 cmd 字段一律用 `.get()`＋类型守卫，缺/错型条目标 `failed`＋审计行并跳过，绝不让一条坏记录楔死全通道；同款守卫须进门禁（变异：缺键 cmd 入队后 poll 200）。

**R12-P1-2（P1）：布尔端口写坏 server.conf，且毒化后续一切渲染**——`port=True` 通过 `_valid_port`（bool 是 int 子类，app.py:876）与 core 的 `port or default`＋范围检查（`1 <= True <= 65535` 为真，core:1012-1014），`Template.substitute(PORT=True)` 把字面 `port True` 写进 server.conf。实证（`r12_inputs2.py` X1/X1b，隔离复核）：首调 200、conf 实测含 `port True`；随后任何渲染（同 proto 同口也不行）一律 500——P01 检查解析旧 conf 时 `int("True")` ValueError → old_port  stays None，`(udp, None) != (udp, 1194)` 即拒，须手工删 server.conf 才解。sk5 同族（X2）：`port=True` → 200、sk5.json 存 `port: 1`（`int(True)`）。修法：`_valid_port` 排除 bool（`type(value) is int`），core 的 render 入口同款守卫；已毒化的 conf 须有修复路径（P01 的 None 比对视同“旧 conf 不可解析→按损坏处理并明示”，而不是永久冻结）。

**R12-P2-1（P2）：`bool()` 把字符串 `"false"` 变成 True，全族反向执行**——`panel/app.py` 全部布尔开关都用 `bool(data.get(...))`（:1293 allow_port_change、:1721/:1732/:1740/:1742 远程入队、:1772/:1779/:1814/:1818/:1820/:1844/:1846 本机保存、:1962/:1972 fail-open 路由、:1994/:2002 udp-over-tcp 路由），而 agent 侧 `_as_bool` 是严格的（bool 才接受）。实证（纯写盘格，无 stub 假象）：`{"fail_open": "false"}` → **200 且 fail_open=true**（X8）；`{"udp_over_tcp": "false"}` → **200 且 true**（X9）；专用路由同款（Y5 fail-open 路由 `"false"`→true）；`allow_port_change="false"`＋改口 1194→1195 → **200、端口真移动**（Y4，P01 冻结被字符串绕过）；`{"enabled": "false"}` → enable 真尝试（F8/X3：沙箱里 fake sing-box 立即退出致 500，但 R4-BUG-1 的 save-after-success 使盘上仍为 false——错态未持久化，真机上会真启用）。反例对照：Worker 同款位置一律 `typeof b.x === "boolean" ? b.x : fallback`（index.js:915-918），字符串直接回落存量、永不反向。修法：面板侧全部布尔输入改严格判定（仅 JSON true/false 接受，非布尔 400），与 Worker／agent 对齐；`clear_password` 同款（:1772）一并改。

**R12-P2-2（P2）：`/api/sk5/udp-over-tcp` 读错键，自然键静默反向**——Flask 两分支（本机 :2002、远程 :1994）都读 `data.get("enabled")`，不读 `udp_over_tcp`。实证（`r12_inputs4.py`）：本机 `{"udp_over_tcp": true}` → **200 但 result.udp_over_tcp=false**（Y1）；远程同款入队 `{'udp_over_tcp': False}`（Y3）；只有文档里的 `{"enabled": true}`（panel/README:49）能打开（Y2）。Worker 的 `handleCompatSk5Toggle` 优先读 `b[key]`、回落 `b.enabled`（index.js:940），两端不一致；fail-open 路由读 `fail_open` 是对的，唯独 udp-over-tcp 错键。前端从不直接调该路由（开关走 `/api/sk5` 保存体），故是潜伏陷阱而非现网 break。修法：Flask 两分支改读 `udp_over_tcp` 优先、回落 `enabled`（与 Worker 同款），并把 panel/README:49 的参数名改回 `udp_over_tcp`。

**R12-P2-3（P2）：Worker `listNodes` 对无名 `node:*` 记录抛未捕获 TypeError**——`nodes.sort((a, b) => a.name.localeCompare(b.name))`（index.js:204）假设每条记录都有 `name`。实证（`r12_worker_inputs.mjs` W21）：KV 里写一条 `node:stray = {"token_hash": "deadbeef"}`（无 name）后，`GET /api/status?node=lightsail` 的 fetch 直接抛 TypeError、请求无响应（mock 里进程崩溃；生产上即 500）。`listNodes` 被 `resolveNode`（全部兼容路由）与 `authenticateNode`（全部 agent poll/report）共用，一条脏记录灭全通道。触发：手改 KV 或写端 bug（产品自身写端恒带 name）。修法：`listNodes` 跳过无 `name` 字符串的记录（并记一条审计／日志），fetch 顶层加兜底 500（永不裸抛）。

**R12-P2-4（P2）：Worker `/api/cmd` 不校验 params 为对象**——`handleCreateCmd`（index.js:1118-1135）：`const params = body.params && typeof body.params === "object" ? body.params : {}`；JS 里 `typeof [] === "object"`，故 `params: ["x"]` 通过并 **202 入队**（W14），agent 侧才拒收（"params must be an object"，N2）。Flask 同款输入 400（app.py:2145-2147）。修法：`Array.isArray(body.params)` 时 400。

**R12-P2-5（P2）：Worker 忽略 `body.node`，两端语义不一致**——Flask AP 新增 `body.node > ?node= > X-Node`（app.py:606-623），Worker `resolveNode` 只读 `?node=`／`X-Node`（index.js:235-259）。实证（W10/W11）：单节点已注册时，`POST /api/sk5` 带 `{"node": "ghost-node"}`（无 `?node=`）→ Worker **202 入队到 lightsail**——调用方指名的 ghost 被静默忽略、在唯一节点上执行；Flask 同款输入 404。`body.node` 未入任何文档（server-mode.md:23 只写 `?node=`／`X-Node`，全树 grep `body.node` 零命中），前端从不发，属潜伏契约分歧。修法二选一：Worker 也读 body.node（与 Flask 对齐）；或 Flask 删 body.node 支持（回归文档契约）。推荐前者（AP 的 body.node 已是既成行为，改 Worker 一处）。

**R12-P2-6（P2）：install.sh 不校验 OVPN_SUBNET，错值照常“装成功”**——`OVPN_PROTO`／`OVPN_PORT` 在 :161-169 有明错 die，`OVPN_SUBNET`／`OVPN_DNS` 无任何校验（:93-94 只给默认值）。实证（staged 全安装 M1）：`OVPN_SUBNET=bogus` → **exit 0**，三条 iptables 规则全带 bogus（`nat|POSTROUTING -s bogus`、`filter|FORWARD -i tun0 -s bogus`、`-d bogus`），日志三行成功样（`NAT: MASQUERADE bogus via eth0` 等）；真机上 real iptables 拒收 bogus 源（`|| warn`，:732-734 等三处同款）仍 exit 0，而 server.conf 仍用 core 固定 10.8.0.0/24——NAT/FORWARD 对真实 VPN 子网全缺，直连出口静默断。修法：:161-169 同款位置加 CIDR 校验（`ipcalc` 或 Python `ipaddress`），非法即 die；OVPN_DNS 同款只验“IP 或可解析主机名”太严会误伤内网域名，至少验字符集（core `_validate_dns` 只拦空白／元字符，`bogus` 这类裸主机名按设计放行，记为观察 O6）。

**R12-P2-7（P2）：`cmd_get` 对手改条目 500（R12-P1-1 的窄口径版）**——H1/H2/H6：`retries="abc"` → `int()` ValueError；`sent_at` 数字＋sent 态 → `fromisoformat` TypeError（只 catch ValueError）；缺 `node` → KeyError。单条命令的查询 500（前端 apiWait 见 500），poll 不受影响。修法随 R12-P1-1（同一批守卫）。

### §2.3 观察（不立案）

- O1：登录缺 password → 401“密码错误”而非 400。401 本身可辩护（认证失败），文案误导；无安全影响。
- O2：OPENVPN_SERVER_IP 垃圾值 → status 原样回显 `remote_ip: "not an ip!!!"`，附“内网地址”警告（文案错配：非 IP 被当成内网地址）。env 是操作员可信输入，API 路径有 `_valid_server_ip`（D9 400），不立案。
- O3：agent `_as_int` 宽松（11080.9→11080 截断、"11080"→11080、True→1）；面板门严格，面板外不可达，仅防纵深缺口。
- O4：sk5 password 数字 12345 → 存为字符串 "12345"（`str()` 强制，F9 200）；无害。
- O5：用户名数字 123 → 建用户 "123"（`str()` 强制，名本身合法，E9 200）；无害。
- O6：OVPN_DNS 裸主机名按设计放行（`_validate_dns` 只拦空白／元字符）；错主机名是操作员责任，不立案。
- O7：Worker 无 `/api/audit` 路由（W16/W17 404）——R11 已记观察，前端不调用。
- O8：`/api/nodes/<name>/install` 只在 Worker、`/api/audit` 只在 Flask——R11 观察，未变。
- O9：队列 id／created_at 两端格式差（uuid4 hex vs randomUUID、ISO 串 vs 毫秒 epoch）——R11 观察，无消费者解析。
- O10：server_ip 数字 "12345" → 200（纯数字是合法主机名，`_valid_server_ip` 设计如此，X4）。

### §2.4 探针纪律自记

- D10/D11/D12 在主探针里 500 是**探针设计污染**：D8 的 `port=True` 先毒化了共享 server.conf，后续格全撞 P01 冻结。隔离复核（`r12_inputs2.py` X4/X5/X6，新鲜 conf）三格全 200——已证伪，不立案。教训：写坏持久态的格必须隔离跑。
- F8/X3 的 500 是**沙箱桩假象**：fake sing-box 立即退出；错在 `bool("false")==True` 致 enable 真尝试，不在 500 本身。X8/X9/Y5 用纯写盘开关复核出干净的 200＋反向值，才是定性证据。
- W21 初版 mock 的 `list()` 未按 prefix 过滤，session 记录混进 `node:` 列表致崩溃——先修 mock（按 prefix 过滤）再复核，复核后崩溃只剩 stray 记录本身，定性成立。
- J 格初版查 `queue:n1` 是否含 init_pki——该键存的是 id 数组，命令体在 `cmd:<id>`；改查 `cmd:<id>` 后 13/13。

## §3 全量复扫（历史 123＋R11 的 2 逐条定性）

复扫宇宙：R11 的 123 条（120 已修＋2 部分＋1 未验）＋R11 本轮新发现 2 条（R11-P1-1、R11-P2-1）＝**125 条**。定性口径与 R11 同款。复扫方法：先以 mtime 对账（§3.0）锁定自 R11 后动过的文件——仅 AP/AQ/AR 六文件（panel/app.py、cloudflare/src/index.js、panel/templates/index.html、README.md、panel/README.md、docs/security.md）；其余文件 mtime 与 R11 §3.0 逐项一致，R11 实证沿用（同日、数小时内，复核时效内）；六文件内的历史项本轮全部行为重验（§1／§2／§4）或逐项代码核对；再叠加 §2 外部输入枚举推导对全部输入面的重查。

### §3.0 mtime 对账（R11 §3.0 → 本轮，UTC）

自 R11 后动过的文件仅六处（AP/AQ/AR）：panel/app.py（15:17:18，2006→2406 行）、cloudflare/src/index.js（15:06:28，1172→1182 行）、panel/templates/index.html（15:21:57，1259 行）、README.md（15:06:33）、panel/README.md（15:06:59）、docs/security.md（15:06:31）。其余文件与 R11 §3.0 逐项一致（install.sh 14:11:22、core 13:14:53、verify.sh 14:45:28、sk5_manager 12:37:13、policy-routing.sh 12:13:01、verify-integration.sh 09:35:55、agent.py 00:58:12，余同 R11）。panel/data/ 仍空。

### §3.1 R11 的 2 条新发现 → 本轮关闭

| 项 | R12 状态 | 证据 |
|---|---|---|
| R11-P1-1 Flask 兼容层忽略 `?node=` | **已修** | §1a：ap_nodeparam 新树 45/45、旧树 13/45 |
| R11-P2-1 Worker 模式无改密端点 | **已修** | §1b：新树改密 501＋wrangler 指引、旧树 404“未知接口”；Flask 改密 7/7 不变 |

### §3.2 R10 的 1 条＋R9 的 5 条＋live-8 的 2 条 → 本轮全部关闭（行为重验）

| 项 | R12 状态 | 证据 |
|---|---|---|
| R10-P2-1 文档行数／行号钉位再次漂移 | **已修** | §1g：全树 grep 归零（审计／live 报告除外）、starter 门 PASS、门禁 28/28 |
| R9-P1-1 队列 naive sent_at wedge 全通道 | **已修（原口径）** | §1d：adv D1/D1c 全绿；旧树 poll 500＋cmd_get 500 原样复现。**但同族残留另立 R12-P1-1／R12-P2-7（§2.2）**——AK 只修了 sent_at 类型，直接键访问仍 500；不是同一条（R9-P1-1 记的是 sent_at 时区，R12-P1-1 记的是缺键／错型字段） |
| R9-P1-2 过期证显示 valid 且重建 409 | **已修** | §1e：D9 报 expired、重建成功；旧树 valid＋409 原样复现 |
| R9-P2-1 队列损坏静默丢命令 | **已修（原口径）** | §1d：D4/D4b 备份字节一致；旧树无备份原样复现。**同族残留见 R12-P1-1**（JSON 合法但字段缺/错型不在 D4 覆盖内） |
| R9-P2-2 磁盘满登录 500 | **已修** | §1d：D11 5/5；lockout PASS |
| R9-P2-3 文档行数／行号钉位过期 | **已修**（当轮 AM＋AO 根治） | §1g：AO 删数字后全树 grep 归零；同族未再复发（§6） |
| R8-BUG-1 默认重跑销毁线上 panel.db（高，阻塞） | **已修**（沙箱侧） | §1f：AN 探针原样重跑，新版毒树重跑行级全保留、登录 200；旧版 401＋admin 0 行原样复现；真机重验归 live-9 |
| R8-BUG-2 全新安装静默卸载 ufw（高） | **已修**（沙箱侧） | §1f：AN 探针原样重跑，新版 ufw 在＋2000 条原规则全在＋2 条放行、`ufw status` 111181 字节；旧版 apt 卸 ufw 原样复现；真机重验归 live-9 |

### §3.3 R11 的 2 条部分 → 本轮仍部分

| 项 | R12 状态 | 证据 |
|---|---|---|
| P0-3 bundle/install-agent.sh | **仍部分** | 逻辑已修（Flask agent-bundle 格 200＋tarball 含 agent.py；verify.sh install-agent-script 200）；部署态未验（§5） |
| P1-7 改密＋首登强制改密 | **仍部分（按设计）** | 改密 API＋UI 在位（Flask 7/7 本轮重跑；Worker 501 诚实端点本轮重跑）；首登强制改密从未实现、文档已诚实，不另立案 |

### §3.4 R11 的 1 条未验 → 本轮仍未验

| 项 | R12 状态 |
|---|---|
| P0-1 部署态 | **仍未验**（§5：登录卡住＋KV 占位，与 R11 同卡点） |

### §3.5 R11 的 120 条已修 → 本轮复核

120＝R11 的 120（119＋§3.1 关闭的 R10-P2-1，已全部在 R11 当轮关闭）；本轮宇宙 125＝R11 的 123＋R11-P1-1／R11-P2-1。分两组：

**（a）修复宿在六个动过文件内的项——本轮全部行为重验或逐项代码核对，无一沿用旧证：** panel/app.py（AK adv 28/28＋D11 5/5＋lockout＋nodeparam 45/45＋inputs 86 格＋门禁 28/28；§2 新发现 7 条中 5 条宿在此文件，见 §2.2）；cloudflare/src/index.js（Worker inputs 21 格＋Y 矩阵 13/13＋AQ changepw 501；§2 新发现 3 条宿在此文件）；panel/templates/index.html（AR href 6/6＋download 11/11＋contrast 10/10＋门禁 UI 格）；README.md／panel/README.md／docs/security.md（§6 全量核对＋AO grep 归零）。

**（b）其余项——修复宿在未动文件内，R11 实证沿用（§3.0 mtime 逐项一致，同日复核）：** agent/agent.py（R8 §4f 13/13＋本轮 r12_agent 21/21 新验）；core/openvpn_manager.py（§1h Core 19/19 本轮重跑）；egress/sk5_manager.py＋policy-routing.sh（门禁 28/28 侧面覆盖；R9 矩阵 4/4＋AG 14/14 沿用）；install.sh（§1f AN 探针原样重跑全过；M1/M3 新验）；verify.sh（starter 门单跑 PASS，§4c）；verify-integration.sh（本轮重跑 28/28）。**R11 的 120 条中无一复发（R9-P1-1／R9-P2-1 的同族残留按新口径另立 R12-P1-1／R12-P2-7，不计为复发——见 §3.2）。**

### §3.6 U-1～U-12 认领表更新

| # | 项 | R12 更新 |
|---|---|---|
| U-1 | P0-1/2/3 部署态 | 仍未验（§5） |
| U-2 | R6-P1-1 真机复现 | 关闭（live-8 headline-5 显式重跑通过） |
| U-3 | UDP 数据面 | 关闭（live-7 S1/S2＋live-8 S2 再证 TCP+UDP 均走 SK5） |
| U-4 | R 符号链接自拷 | 关闭（无变化） |
| U-5 | R 逐项失败 die 分支 | 仍为“机制已证、分支未触发”：live-8 三装全程跑通；live-9 人为致败跟进 |
| U-6 | T 两变异 | 关闭（R8 已判；R9 T 变异重跑 17/2/4） |
| U-7 | verify-integration 瞬时红 | 关闭（R9/R10/R11/R12 四次 28/28，一次过） |
| U-8 | 真机在位升级路径 | AN 沙箱已修（§1f），**待 live-9 真机重验**（live-9 与本轮并行在跑，§§12–19 待填） |
| U-9 | KV 竞态与 POP 传播 | 仍未验（无部署） |
| U-10 | 前端渲染级核查 | 关闭（live-8 headline-7 真机渲染通过；本轮静态核查 10/10 与之致，§7）；live-9 新树部署上须再跑一次 |
| U-11 | easy-rsa 真二进制签发 | 关闭（live-8 headline-2 以 real easyrsa 3.1.0 裁决） |
| U-12 | live-R5 结果 | 关闭 |

复扫合计：125 条＝已修 122（120＋§3.1 关闭的 2 条）／部分 2（P0-3、P1-7）／未验 1（P0-1）；**本轮新发现 9 条另计（R12-P1-1／R12-P1-2／R12-P2-1～R12-P2-7，见 §2／§8 差集）**。125＝122＋2＋1；新发现 9 条见 §8 差集。

## §4 套件重跑

### §4a 门禁 verify-integration.sh：28/28（本轮在 /tmp/r12/tree 副本上实测）

`bash verify-integration.sh`：**PASS=28 FAIL=0 SKIP=0**。逐格与 R11 §4a 同款。宿主 /etc 复核干净（§8.4）。

### §4b Flask／Worker／Agent

- **Flask（本轮 adv 28/28＋lockout PASS＋D11 5/5＋nodeparam 45/45＋inputs 86 格）**：AH 的 flask35.py 已随 /tmp 清理消失，**35/35 未原样重跑**——与 R10/R11 同款缺口，本轮 Flask 面由 adv 探针 28 格＋lockout 探针＋D11 磁盘满 5 格＋nodeparam 探针 45 格＋inputs 枚举 86 格＋门禁 28 格覆盖。AK 改动面逐格行为验证；本轮新发现的 7 条 Flask 面输入缺口（R12-P1-1／P1-2／P2-1／P2-2／P2-7）均逐格行为验证。35 格逐格对照缺失，记为本轮套件口径的缺口（见 §8.2），不冒充。
- **Worker（本轮重建 Y 矩阵 13/13＋inputs 21 格＋改密探针）**：`cloudflare/src/index.js` 本轮动过（AQ），R8 的 18/18 探针文件已失（`/tmp/r8-tests/` 不存），故本轮**重建** Y 矩阵探针（`r12_worker_y.mjs`，A–F via_sk5 矩阵＋init-pki 4 格＋cmd 1 格＋setup 2 格＝**13/13**；变异对照：cachedStatus 判据改回 `sk5.enabled` 单行，A/C/F 恰红——R7-P1-1 谎言原样复现）；inputs 探针 21 格中 17 通过、W10/W11/W14 失败、W21 未捕获异常（见 §2.2）；改密探针新树 501、旧树 404（§1b）。部署态仍未验（§5）。
- **Agent（本轮重跑 21/21＋R8 13/13 沿用）**：`agent/agent.py` mtime 与 R11 §3.0 一致（00:58:12，未动），R8 §4f 的 13/13 仍有效；本轮另以 `r12_agent.py` 直测 `execute_command` 输入面 21/21（§2.1）。

### §4c 门禁 verify.sh：全量分段未重跑（诚实交代）＋starter 门逻辑单跑 PASS

与 R10/R11 §4c 同款：R9 的 vfy 分段 harness 已失，本轮未重建全量分段跑；已做：(1) `bash -n verify.sh` 过；(2) verify.sh 自 R11 后未动（mtime 14:45:28）；(3) **starter-template-consistency 门逻辑按原文逐字抽取重跑 PASS=1 FAIL=0**（`/tmp/r12-tests/run_starter_gate.sh`，heredoc 按 marker 提取，tun 入站全字段与模板一致、dns.final='dns-direct'）。全量分段数（R9：22/0/1＋T 变异 17/2/4）沿用 R9，不冒充为本轮数。live-9 headline-6（verify.sh 双态真机跑）即该门禁的真机总验。

### §4d Egress 套件：test-egress.sh §6 矩阵 4/4（沿用 R9）

`egress/test-egress.sh`、`egress/sk5_manager.py`、`egress/policy-routing.sh` 三文件 mtime 与 R11 §3.0 逐项一致（未动），R9 §4d 的 §6 矩阵 4/4 与 AG policy 矩阵 14/14 沿用。本轮未重建 egress harness；sk5_manager 的保存／启停路径由门禁 28/28 与 inputs 探针 F/X/Y 格侧面覆盖。

### §4e Core 套件 19/19（本轮重跑，§1h）

单测 5/5（状态日志，夹具为真机捕获行）＋探针 14 格（C0–C13）＝**19/19**。

### §4f 五套件总览

| 套件 | 规模 | 结果 |
|---|---|---|
| Flask adv＋lockout＋D11＋nodeparam（本轮重跑） | 28＋1＋5＋45 | **28/28＋PASS＋5/5＋45/45**（AH flask35 未原样重跑，见 §4b） |
| Flask inputs 枚举（本轮新建） | 86＋12＋6＋9 | **73/86＋8/12＋4/6＋5/9**（23 格 FAIL 中 19 格映射 9 条新发现，余 4 格为 D10/D11/D12 的 conf 污染连带＋A1 观察，见 §2.4） |
| Worker inputs＋Y 矩阵＋改密（本轮重跑／重建） | 21＋13＋1 | **17/21＋13/13＋501**（W10/W11/W14 失败＋W21 未捕获异常，见 §2.2） |
| Agent inputs（本轮新建）＋R8 13/13 | 21＋13 | **21/21＋13/13（沿用）** |
| Core（本轮重跑） | 19 | **19/19** |
| Egress（沿用 R9，代码未动） | 4＋14 | **矩阵 4/4＋policy 14/14** |
| verify-integration.sh（门禁，本轮重跑） | 28 | **28/28** |
| verify.sh（门禁） | 23 | **全量分段未重跑**（§4c）；starter 门逻辑单跑 PASS |

## §5 P0-1/2/3：真实 wrangler deploy 重验——卡在登录，仍未验

- **dry-run 通过**（本轮重跑，wrangler 4.161.0 经 npx，自 `cloudflare/` 目录）：`npx wrangler deploy --dry-run` exit 0——绑定列出 `env.PANEL_KV (REPLACE_WITH_KV_NAMESPACE_ID)` 与 `env.PANEL_MODE ("cloudflare")`。dry-run 只证配置可解析，不证部署。（注：自项目根目录跑会报“Could not detect a directory containing static files”，是目录错位，不是产品问题。）
- **真 deploy 卡在第一步：无登录**（本轮重跑，exit 1）：`In a non-interactive environment, it's necessary to set a CLOUDFLARE_API_TOKEN environment variable for wrangler to work.`（与 R7/R8/R9/R10/R11 同一卡点；本机 `~/.config/.wrangler/` 下只有 logs＋metrics.json、无登录态，环境变量 `CLOUDFLARE_API_TOKEN` 未设置）。`wrangler.toml:32-33` 的 KV id 与 preview_id 仍是占位符 `REPLACE_WITH_KV_NAMESPACE_ID`／`REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`，是第二道卡点。
- **需要用户做的事（按顺序，缺一不可，与 R11 同款）**：(1) 在 Cloudflare 账号上建 API token（Workers＋KV 权限）并以 `CLOUDFLARE_API_TOKEN` 交给部署环境，或在可交互终端跑 `wrangler login`；(2) `wrangler kv namespace create PANEL_KV` 与 `--preview` 各一次，把返回的真实 id/preview_id 填进 `wrangler.toml`；(3) `wrangler secret put ADMIN_PASSWORD` 与 `wrangler secret put AGENT_BUNDLE_ORIGIN`；(4) `wrangler deploy`，再按 cloudflare/README:83 的要求换第二出口多点核（Workers 按 POP 慢速传播，单出口“没生效”不可信）。
- **结论**：P0-1/2/3（Worker 真实部署态）**仍未验**，与 R11 结论一致；Worker 代码侧的全部行为断言只在 mock KV＋本地 fetch 入口下成立，不是部署态证据。`--temporary` 未用——那会把 Worker 部署到临时抛弃账号上，不是用户的部署，测了也是冒充结论。

## §6 文档宣称全量核对（根 README／panel／cloudflare／security／flmx-reference／egress／core）

核对方法：每份文档的数字类宣称（门禁数、行数、端口、超时、重试上限、行号钉位）与行为类宣称逐条对代码/实测；数字以 `wc -l` 为准。自 R11 后动过的文件仅 AQ 三处文档＋AP/AQ/AR 三处代码，其余文件与 R11 §6 的核对结论逐项复核（mtime 一致）＋本轮新验。

**通过的宣称**：
- 根 README:226 门禁数 28（本轮 verify-integration.sh 重跑 28/28 一致）；:198 哈希钉位 `install.sh:63-66`（本轮实测该四行仍是四条 sha256 钉死值，与 agent.py:123/126/129/132 逐值一致——950af37e…／20a6a9cd…／a612baa2…／3931476c…）；:137 SK5 端口待确认注（1001 默认、9000 待回报，与面板字段旁注 index.html:470-471 一致）；:243 API 列表（与 §2a 读到的路由表一致，另见下述 R12-P2-2 的文档侧）；用户名规则 `[a-zA-Z0-9_-]{1,32}`＋保留名 `server`／`OpenVPN-CA`（与 core:99-119 一致；inputs E4/E5 行为验证 400）。
- AQ 四处模式限定在位：docs/security.md:11、README:260、panel/README:31/:101——均写明改密“仅服务器（Flask）模式可用；Cloudflare 模式回 501，须用 `wrangler secret put ADMIN_PASSWORD`”（§1b 行为验证一致）。
- server-mode.md:23 多节点“相同”宣称——AP 修后成立（Flask 兼容层 18 路读 `?node=`，nodeparam 45/45）；但 `body.node` 未入该行文档（全树 grep `body.node` 在四份文档中零命中）——R12-P2-5 的文档侧。
- 超时／计数类（全树 grep＋实测一致）：健康检查 60s、agent 轮询 5s、状态缓存 10s、重投 120s／3 次（panel/README:90、security.md:12 同值）、登录限流 5 次／5 分钟／锁 15 分钟（§1d lockout 行为验证 429＋`retry_after_s: 900`）、证书 825 天。
- AO 根治有效：全树 grep 带日期实测数字归零（§1g）；本轮复扫未发现新的带日期行数／行号数字。R9-P2-3／R10-P2-1 同族未再复发。

**新发现的文档侧问题（立案见 §2／§8，不另立条）**：
- panel/README:49 把 `/api/sk5/udp-over-tcp` 的参数写成 `enabled: bool`——与 Flask 实现一致，但与同表 fail-open 路由的 `fail_open: bool` 命名不对称，且与 Worker 的 `b[key]` 优先口径不一致；自然键 `udp_over_tcp` 被静默忽略（R12-P2-2 的文档侧）。
- server-mode.md:23 只列 `?node=`／`X-Node`，未提 Flask 亦接受 `body.node`——而 Worker 不接受（R12-P2-5 的文档侧）。
- 其余：R12-P1-1／P1-2／P2-1／P2-3／P2-4／P2-6 均无文档宣称背书（纯代码输入面缺口），不另记文档条。

## §7 前端静态对比度核查（本轮重跑；真机渲染归 live-8，已过；live-9 新树重跑待填）

方法：跑 `panel/static/contrast-check.py`（WCAG 相对亮度；底线 4.5、目标 7）。**脚本结果：10/10 过底线 4.5（exit 0）；目标 7 达成 4/10——与 R9/R10/R11 逐值一致。** 结论：静态核查通过底线；6 对低于目标 7（最低为成功绿字 4.92，仅高于底线 0.42），记为观察、不立案——门禁脚本的通过线就是底线，且 R7 九维视觉审计未以对比度立案。真机渲染已由 live-8 headline-7 通过，U-10 关闭；live-9 的新树部署上须再跑一次。

## §8 裁决与未验清单

### §8.1 裁决：**不能交付，差集 9 条**

| 级别 | 条目 |
|---|---|
| P1 | 2：R12-P1-1（队列手改条目楔死 agent 全通道）、R12-P1-2（布尔端口写坏 server.conf 且毒化后续渲染） |
| P2 | 7：R12-P2-1（`bool()` 反向）、R12-P2-2（udp-over-tcp 错键）、R12-P2-3（Worker listNodes 无名记录崩溃）、R12-P2-4（Worker /api/cmd 收 list params）、R12-P2-5（Worker 忽略 body.node）、R12-P2-6（OVPN_SUBNET 未校验）、R12-P2-7（cmd_get 对手改条目 500） |
| 高（阻塞） | 0：R11 的 2 条与 R10 的 1 条、R9 的 5 条、live-8 的 2 条已全部修好（§1，变异红证齐全） |
| P0 | 0 未修、1 未验：P0-1/2/3 部署态仍未验（§5）；P0-3 部分（按设计，部署态未定） |

差集＝9 条（P1×2＋P2×7）。R11-P1-1 与 R11-P2-1 已全部关闭（§3.1），历史 125 条中 122 条已修（§3.6）；AK/AL/AM/AN/AO/AP/AQ/AR 的修复本身本轮全部行为验证通过（§1，变异红证齐全），套件全绿（§4f，见 §4b/§4c 的两处口径缺口）。但这不改变差集非空的结论：本轮外部输入枚举推导新发现的九条都是“畸形输入进、错误行为出”——两条 P1 一条楔死 agent 全通道（R9-P1-1 同族残留）、一条写坏持久配置并毒化后续渲染；七条 P2 覆盖布尔强制、错键读取、存储记录健壮性、两端契约分歧、安装器校验缺口。九条中五条宿在 Flask、一（半）条在 core、二条在 Worker、一（半）条在 install.sh；旧树对照证明无一是 AP/AQ/AR 回归。

**下一步（按用户常设流程）**：派修复路修 R12 的 9 条（按文件面可分四路并行：① panel/app.py——P1-1＋P1-2＋P2-1＋P2-2＋P2-7，② cloudflare/src/index.js——P2-3＋P2-4＋P2-5，③ core/openvpn_manager.py——P1-2 的 render 侧守卫＋已毒化 conf 修复路径（与①同文件簇，可并入①或独立），④ install.sh——P2-6；修法方向见 §2.2；Worker 的 `typeof === "boolean"` 判定是 P2-1 的现成参照修法），修完集成后跑 **AUDIT-R13（全量全局回头看，换推导方法独立复算）＋ live-9（真机总验）对账**，两路都过才交付。修复路开工前须先确认：本报告基线树版本（§0）与修复路所取树一致。

### §8.2 未验清单（逐项：为什么没验、谁能验）

1. **P0-1/2/3 真实 wrangler deploy（§5）**——卡在 Cloudflare 登录（非交互环境须 `CLOUDFLARE_API_TOKEN`，`~/.config/.wrangler/` 无登录态；wrangler.toml 的 KV id 与 preview_id 仍是占位符）。谁能验：用户建 API token（或交互式 `wrangler login`）＋`wrangler kv namespace create PANEL_KV`（生产＋预览）填实 id＋`wrangler secret put ADMIN_PASSWORD`／`AGENT_BUNDLE_ORIGIN` 后，live 路跑真实 `wrangler deploy`，再从第二出口核 POP 传播。本轮不许用 mock 冒充。
2. **前端渲染级检查**——本轮只做了静态核查（§7：10/10 过底线 4.5、4/10 达目标 7）；真机渲染已由 live-8 headline-7 通过，U-10 关闭。但 live-9 的树含 AN 改动后，渲染须在新树部署上再跑一次（live-9 headline-7 回归）。
3. **Cloudflare KV 竞态＋POP 传播**——依赖第 1 项的真实部署；无部署则无从测。谁能验：同第 1 项，部署后多点核。
4. **SK5 端口 1001 vs 9000**——用户从未确认哪个是 SOCKS5 口（面板默认 1001，文档已标注待确认，README:137＋index.html:470-471）。谁能验：用户回报；live 路再以确认后的端口跑 UDP/TCP 双栈。
5. **D13 PKI 段竞态**——沙箱无 easyrsa 二进制，两路并发安装／重跑时 `init_pki`＋`build-ca` 的先查后建竞态测不到（copy 段已验，见 R9 §2）；live-8 未跑并发安装（§17 为顺序三装），仍未验。谁能验：live-9 在真机上跑并发安装／并发重跑。
6. **D14 时钟跳变**——沙箱无 faketime，改系统时钟超出审计范围；仅代码级分析（锁定／会话／重投／健康全是墙钟）。谁能验：真机上以 faketime 或受控调钟复核（须用户授权调真机时钟）。
7. **Flask 35/35 未原样重跑**——AH 的 flask35.py 已随 /tmp 清理消失；本轮 Flask 面由 adv 28 格＋lockout＋D11 5 格＋nodeparam 45 格＋inputs 枚举 86 格＋门禁 28 格覆盖（§4b），AK 改动面与新发现的 9 条输入缺口均逐格行为验证，但 35 格逐格对照缺失。谁能验：下一轮审计重建 flask35 或等效套件；live-9 的真机 S0–S4 覆盖同一面的行为。
8. **verify.sh 全量分段未重跑**——R10 的 vfy harness 已失，本轮只单跑了 starter 门逻辑（§1g PASS）＋`bash -n`；全量分段数沿用 R9。谁能验：live-9 headline-6（verify.sh 双态真机跑）即该门禁的真机总验。
9. **R8-P2-4 的真 ufw 验证**——live-8 记未验（R8-BUG-2 使前提不可达）；AN 沙箱已修（§1f，2000 条规则＋111181 字节输出真实走通 builtin 分支）。谁能验：live-9（ufw 启用＋长表宿主机真机重跑）。
10. **U-5 die 分支**——机制已证、分支未触发（live-8 三装全程跑通）；分支本身仍须一次人为致败才验得到。谁能验：live-9 人为致败安装步骤。
11. **R12-P1-2 的真机 daemon 后果**——沙箱无 openvpn 二进制，`port True` 致 daemon 起不来的后果未在真机上证实；本轮已证实的在树后果是 conf 含非法指令＋后续一切渲染 500（X1/X1b）。谁能验：live 路在真机上复现一次布尔端口调用（或等修复路修完后以非法端口变异复核）。
12. **live-9 结论是否入本报告**——未入。live-9 与本轮并行在跑；本报告的沙箱结论不依赖它，live-9 落盘后须由主控对账（尤其 §8.2 的第 2/5/9/10/11 项与 R8-BUG-1/2 的真机验收、以及 R11-P1-1 的多节点 Flask 真机格）。

### §8.3 审计方法自述（供 R13 复核）

- 本轮方法：外部输入枚举推导（§2，Flask 39 路由×畸形变体、Worker 路由×畸形变体、agent 13 动作×畸形 params、队列文件手改条目、index.txt／状态文件畸形行、面板 env、install.sh env、wrangler.toml／secret）＋历史全量复扫（§3，125 条，mtime 对账＋六文件内逐项重验）＋新代码逐项行为验证（§1，亲自重跑、零 monkeypatch 走真实代码路径、阴性对照齐全）＋套件重跑（§4，Flask adv／Core／双门禁重跑＋Worker Y 矩阵重建＋Worker／Agent／Egress 沿用 mtime 未动文件）＋P0 部署态重验（§5）＋文档宣称全量核对（§6）＋前端静态对比度核查（§7）。
- 探针纪律：凡套件格先红，必先查探针本身（本轮修掉的探针问题：D10/D11/D12 的共享 conf 污染——改隔离复核后证伪；F8/X3 的 fake sing-box 500——改纯写盘开关复核后定性；W21 初版 mock list 未按 prefix 过滤——修 mock 后复核；Y 矩阵 J 格查错 KV 键——改查 `cmd:<id>` 后 13/13。探针修好重跑后才定性，不在探针 artifact 上立案）。
- 沙箱边界：无 systemd／无 TUN／无 easy-rsa／无 openvpn 二进制／UDP sendto 临时端口 EPERM——凡涉此五项的结论均已标注分段环境或待真机（live-9），未把沙箱结论写成真机结论。fake apt 的“装 iptables-persistent 即卸 ufw”模型以 live-8 真机证据为锚（install3.log:8），fake easyrsa 的 index.txt 语义以 openssl 真签发为锚，mock KV 的 Worker 本地入口以 R8 的 18/18 同款为锚——桩的行为均有真机／真程序对照，不是凭空捏造。M1 的 fake iptables 恒 exit 0，故“真机 iptables 拒收 bogus”一段引的是标准工具行为，产品侧已证的是“无校验＋exit 0＋成功样日志”。
- 本轮审计侧污染：无。探针进 `unshare -m` 绑挂（`/etc/openvpn-sk5-panel`、`/etc/sysctl.d` 绑 /tmp），事后 /etc 复核干净（见 §8.4）；宿主挂载点目录（`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`，run-flask／run-install 的 `mkdir -p` 留下）已 rmdir 删净。/tmp 资产（供 R13 复用）：`/tmp/r12`（树副本）、`/tmp/r12-tests/`（r12_inputs／r12_inputs2／r12_inputs3／r12_inputs4／r12_agent／r12_worker_inputs／r12_worker_y／r12_env 探针、index-mutant.js、aq-old 日志、wrangler-deploy.log、r12-inputs-new/old 日志、bug-subnet staged 场景）、`/tmp/r11-tests/`（R11 探针原稿＋r12 探针副本）、`/tmp/r10-tests/`（R10 探针原稿）、`/tmp/r10/`（树副本＋tree-old 回退树）、`/tmp/an-tests/`（AN 探针＋fakebin＋venv）。

### §8.4 清理记录（审计结束时）

- 分段面板：AN 探针遗留的 staged 面板（PID 30540，https://127.0.0.1:8443）本轮收尾时仍在跑，已按精确 PID kill，端口 8443/1080/11080 已空闲，无残留进程（`ps`＋`ss` 核对）。SOCKS stub 与 fixed-IP 服务器未在本轮启动。
- 宿主 `/etc/openvpn-sk5-panel/`、`/etc/openvpn/`（含 `server/` 子目录）、`/etc/sysctl.d/99-openvpn-sk5.conf`、`/run/openvpn-sk5-panel/` 均不存在（每次 unshare 绑挂后都 rmdir 复核）；宿主 /etc 复核干净。**审计侧污染一笔**：`r12_agent.py` 直接以系统 python3 跑、未进 unshare，其 N9 格 `set_sk5` 把 sk5.json 写进了宿主 `/etc/openvpn-sk5-panel/`——收尾时已删该文件并 rmdir 挂载点目录；教训：凡调 egress 写盘的探针一律进 run-flask.sh／run-install.sh 的 unshare 绑挂，裸跑只许纯读。项目树核查：本轮只写了本报告一个文件；树内其余文件 mtime 未动（`find -newer README.md` 仅剩 AP/AQ/AR 三文件＋live-verify-R9.md——live-9 的文件）；`__pycache__` 检查：本轮探针在原树 panel／core／egress／agent 下生成的 4 个 `__pycache__` 已删净；`core/tests/__pycache__/test_status_log.cpython-312.pyc`（2026-11-12 07:45 UTC）是早轮遗留、非本轮产生，留原样未动；live-verify-R9.md 是 live-9 的文件。
- /tmp 资产（供 R13 复用）：`/tmp/r12`（树副本）、`/tmp/r12-tests/`（本轮全部探针＋日志＋staged 场景），`/tmp/r11-tests/`（R11 探针原稿＋r12 探针副本），`/tmp/r10-tests/`（R10 探针原稿），`/tmp/r10/`（树副本、tree-old 回退树），`/tmp/an-tests/`（AN 探针＋fakebin＋venv）、`~/workspace/ae-tests/poison/`（毒包文件）。


# AUDIT-R11 — 全量全局回头看（交付前）

## 结论先写

**结论：不能交付，差集 2 条（P1×1：R11-P1-1 Flask 兼容层忽略 `?node=`；P2×1：R11-P2-1 Worker 模式无改密端点）。**

- 审计员：独立审计路（未参与建设与修复路 AK/AL/AM/AN/AO；单审计员边做边写，不派子代理）
- 日期：2026-11-12（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R10 同等广度）
- 推导方法：**契约闭合推导**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性、R9 对抗操作员＋时间衰变、R10 环境矩阵×修复存活均不同）——先枚举树内全部契约（Flask HTTP 路由×前端调用、Worker 路由×agent 调用、agent 13 个动作白名单×面板命令入队、队列文件 schema×读写双方、index.txt／状态文件格式×解析器、systemd 单元×服务名、verify.sh／verify-integration.sh 门禁×被测行为、文档宣称×代码），逐条核对生产方与消费方是否一致（字段名、类型、默认值、错误码、超时）；再叠加历史全量复扫（R10 的 122＋1 条逐条定性）与 AK/AL/AM/AN/AO 新代码逐项行为验证（带变异红证）。每条推导链必须落到一条可执行的探针或一条明确的“不可验（写清为什么）”，不许只写文字推断；live-9 与本轮并行在跑，其结论未入本报告，须在 §8 写明。
- 测试一律在 `/tmp` 副本（`/tmp/r11` 树副本、`/tmp/r11-tests/` 自建 harness、复用幸存的 `/tmp/r10-tests/`（R10 探针）与 `/tmp/an-tests/`（AN 探针＋fakebin＋venv）与 `~/workspace/ae-tests/poison/`）上跑；未动项目原文件（除本报告）；未动 `/etc`（探针进 `unshare -m` 挂载命名空间，`/etc/openvpn-sk5-panel` 与 `/etc/sysctl.d` 绑 /tmp；事后 mtime 核对见 §8）；未动任何真机。需真机行为复核的项一律写“待 live-9”，不提前判通过。
- 语法基线：4 个 Python 文件 `py_compile` 全绿；7 个 shell 脚本 `bash -n` 全绿；Worker `node --check` 全绿（见 §0）。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明（与 R9/R10 同款记明）。

## §0 树版本与 AO 改动确认

当前树是 R10 修复路 AO 之后的新树。文件 mtime（UTC）与 R10 §0 基线对照：

| 文件 | mtime (UTC) | 行数 | 说明 |
|---|---|---|---|
| install.sh | 2026-11-12 14:11:22 | 1042 | 未动（R10 mtime） |
| panel/app.py | 2026-11-12 13:15:22 | 2006 | 未动（R10 mtime） |
| core/openvpn_manager.py | 2026-11-12 13:14:53 | 1450 | 未动（R10 mtime） |
| README.md | 2026-11-12 14:45:28 | 277 | 动过（AO：:204 heredoc 钉位删数字、只留 marker） |
| verify.sh | 2026-11-12 14:45:28 | 846 | 动过（AO：:234 注释删数字、只留 marker；注释-only） |
| panel/README.md | 2026-11-12 14:45:24 | 113（R10: 115） | 动过（AO：三处＋:76 一处删带日期行数，只留 `wc -l`） |
| egress/sk5_manager.py | 2026-11-12 12:37:13 | 1109 | 未动（R10 mtime） |
| egress/policy-routing.sh | 2026-11-12 12:13:01 | 364 | 未动（R10 mtime） |
| verify-integration.sh | 2026-11-12 09:35:55 | 567 | 未动（R10 mtime） |
| cloudflare/src/index.js | 2026-11-12 09:24:00 | 1172 | 未动（R10 mtime） |
| agent/agent.py | 2026-11-12 00:58:12 | 910 | 未动（R10 mtime） |
| panel/templates/index.html | 2026-11-12 09:20:59 | 1259 | 未动（R10 mtime） |
| panel/data/ | 2026-11-12 12:14 | 空目录 | AE 路清空后仍空；AN 的 staging 拷贝不再往里写任何文件 |

语法基线（本轮在原树上实测）：`panel/app.py`、`egress/sk5_manager.py`、`core/openvpn_manager.py`、`agent/agent.py` 四文件 `py_compile` 全绿；`install.sh`、`verify.sh`、`verify-integration.sh`、`egress/test-egress.sh`、`egress/policy-routing.sh`、`core/easyrsa.sh`、`agent/install-agent.sh` 七脚本 `bash -n` 全绿；`cloudflare/src/index.js` `node --check` 全绿。

/tmp 资产现状（本轮开工时实测）：`/tmp/r10-tests/`（R10 探针＋harness）、`/tmp/an-tests/`（AN 探针＋fakebin＋venv）、`/tmp/r10/`（树副本＋tree-old 回退树）**全部幸存**；`~/workspace/ae-tests/poison/` 幸存。本轮策略：**复用 R10 探针**（r10_adv／r10_diskfull／r10_core／r10_lockout，拷到 `/tmp/r11-tests/`，仅改 harness 路径）与 **AN 探针**（probe_bug1／probe_bug2，原样跑当前树）；venv 复用 `/tmp/an-tests/venv`（Flask 3.1.3＋bcrypt，已验）。

（以下各节边审边写）

## §1 AO／AK／AL／AN 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

### §1a AO 路（R10-P2-1）——全部验证通过

AO 只动三处文档/注释，代码逻辑一字未动（本轮 mtime 对账 §0：仅 README.md、verify.sh、panel/README.md 三文件动过）。实测：

- 全树 grep `1404`／`570-597`／`630-657`／`2026-11-12 实测`（`--include=*.md,*.sh,*.py,*.js`，审计报告与 live 报告除外）：**零命中**（rc=1）。panel/README 三处＋:76 一处均已删数字、只留“行数见 `wc -l`，行数随修复浮动，文档不钉死具体行数”；根 README:204 只留 marker 定位与“行号随插入浮动”句；verify.sh:234 注释只留 marker 写法。
- `wc -l` 实测：core 1450、sk5_manager 1109，与文档剩余宣称一致（文档已不再断言具体行数）。
- starter-template-consistency 门：verify.sh:240-287 原文逐字抽取（sed 提取，拒绝手抄——AO 曾两次手抄 awk 报 mawk 错，探针侧问题）重跑——**PASS=1 FAIL=0**，tun 入站全字段一致、`dns.final='dns-direct'`；heredoc 按 marker 提取于 install.sh:630。
- verify-integration.sh：**28/28**（§4a）。
- **裁决：R10-P2-1 已修。** AO 的修法（删数字、只留 `wc -l`／marker）是根治型：后续代码改动不再能让正文数字变假；本轮复扫未发现新的带日期实测数字（见 §6）。

### §1b AK 路（R9-P1-1＋R9-P2-1＋R9-P2-2）——全部行为验证通过，变异红证齐全

探针：复用 R10 的 `/tmp/r10-tests/r10_adv.py`（D1/D1b/D1c/D2/D4/D4b/D5/D6/D9）与 `r10_diskfull.py`（D11）与 `r10_lockout.py`，拷到 `/tmp/r11-tests/`（仅改 harness 路径），真实 Flask test_client＋真实 core＋AH fake easyrsa/openvpn，`unshare -m` 绑 /etc；旧代码回退树复用 `/tmp/r10/tree-old`（R10 的 AK/AL 回退，AO 只动文档，不影响这些格）。

| 格 | 期望 | 新树实测 | 旧树阴性对照 |
|---|---|---|---|
| D1 naive sent_at（过去） | poll 200、重投＋重下发、cmd_get 200 | **PASS** | **恰红**：poll 500、GET 500 |
| D1 naive sent_at（未来） | poll 200、不提前重下发 | **PASS** | 500（wedge 级联） |
| D1b 垃圾 sent_at | poll 200 | **PASS** | PASS（旧已有 ValueError 分支） |
| D1c 数字 sent_at（TypeError） | poll 200 | **PASS** | **恰红**：poll 500 |
| D2 重投生命周期（121s 超时） | 3 轮重投 retries=1/2/3，第 4 次 failed | **PASS** | 级联红（同一根因） |
| D4 损坏队列 JSON | poll 200 空命令、`.corrupt` 备份字节一致、下一入队 202 | **PASS** | **恰红**：无备份文件 |
| D4b 非 dict JSON | poll 200＋隔离 | **PASS** | **恰红**：无备份 |
| D11 磁盘满登录 | 正密码 200、错密码 401 | **PASS 5/5** | **恰红**：限内正密码 500、错密码 500 |
| lockout（§2a 补验） | 5 错→401×5、锁后 429＋retry_after_s 900、旧会话 200 | **PASS** | — |

**adv 探针总计：新树 28/28，旧树 15/28（13 红全在 AK/AL 改动面，与 R10 逐值一致）。裁决：R9-P1-1、R9-P2-1、R9-P2-2 三条已修。** D5（运行中删 panel.db：重建密码后新登录 200）与 D6（3 小时前 health 原样返回、无陈旧标识）与 R9/R10 观察一致，属设计，不立案。

### §1c AL 路（R9-P1-2）——行为验证通过，变异红证齐全

探针：同上 adv 探针 D9（先 `build_server_cert` 补 ta.key——R9 adv 探针的 D9 前置缺口，主控已记 AGENTS.md；本轮探针含该步）。

| 格 | 期望 | 新树实测 | 旧树阴性对照 |
|---|---|---|---|
| D9 V 行过期（2001） | list 报 expired、重建不 409 | **PASS**：`{'status': 'expired', 'expires': '200101000000Z'}`、重建成功 | **恰红**：list 报 `valid`、重建抛 `UserAlreadyExistsError` |
| D9 畸形 expiry | 保持原旗标、不抛错 | **PASS**：expiry=`garbage-not-a-date` 时仍报 valid、无异常 | —（旧代码同行为，无回归） |

**裁决：R9-P1-2 已修。**

### §1d AN 路（R8-BUG-1＋R8-BUG-2）——全部行为验证通过，变异红证齐全

探针：原样复用 `/tmp/an-tests/probe_bug1.py`（new/old）与 `probe_bug2.py`（new-ufw/old-ufw/new-noufw），对当前树原文评估（new 路取 `~/workspace/openvpn-sk5-panel/install.sh`，sha256 `5af298b9…`）；全量 staged 全安装，fake apt/systemctl/iptables/ip＋真面板＋真 API。

| 格 | 期望 | 实测 |
|---|---|---|
| BUG-1 新版毒包全新安装 | 毒库未入住、admin.hash 与毒哈希不同、毒队列无 init_pki、admin.pass 新生成 | **PASS**（FAILS: none） |
| BUG-1 新版毒树默认重跑 | exit 0、横幅出、登录 200、节点/用户仍在、队列 sha 不变、CA 序列不变、同面板进程、agent poll 200 | **PASS**：重跑后节点 lightsail 仍在、用户 alice 仍 valid、poll 200 回排队 get_status 命令、无 init_pki（FAILS: none） |
| BUG-1 旧版阴性对照 | 重跑死于登录门 401、活库销毁 | **恰红**：登录 401、admin 0 行 nodes 0 行 |
| BUG-2 新版＋ufw 长表（2000 条规则） | apt 行无 iptables-persistent、ufw 在、原规则全在、1194/8443 放行补加、`ufw: allowed` | **PASS**：新放行在规则库中、`ufw status` 111181 字节（＞64KB，长表分支真实走通）（FAILS: none） |
| BUG-2 旧版阴性对照 | apt 装 iptables-persistent、ufw 被卸、安装仍 exit 0（静默） | **恰红**：安装日志无 `ufw: allowed`、安装仍 rc=0 |
| BUG-2 新版无 ufw 回归 | apt 行照旧含 iptables-persistent、安装正常 | **PASS** |

**裁决：R8-BUG-1、R8-BUG-2 两条已修（沙箱侧；真机重验归 live-9）。**

### §1e Core 套件 19/19（本轮重跑：core 已由 AL 改动）

探针：复用 R10 的 `/tmp/r10-tests/r10_core.py`（拷到 `/tmp/r11-tests/`），真实 `openvpn_manager`＋fake-PKI＋fake easyrsa/openvpn。

**19/19**：C0（PKI＋server 证）、C2（建用户 alice，.ovpn 含三段 PEM＋remote，openssl 验 CN=alice）、C3（重建拒绝）、C4（list alice valid）、C5（非法名 6/6 拒绝）、C6（吊销标 R）、C7（吊销后重建）、C8（幽灵吊销拒绝）、C9a（同值重渲染）、C9b（无 allow 改端口拒绝）、C9c（有 allow 改端口成功）、C10（无 daemon 时 server_status 诚实报 running=false 不抛错）、C11（init_pki 无 force 拒绝）、C12（同值重渲染内容一致）、C13（build_server_cert 二次调用幂等）、C1（状态日志单测 5/5：bare-v1、comma-v2、tab-v2、prefixed-7、empty/missing，夹具为真机捕获行）。

### §2a Flask 路由 × 前端调用——发现 R11-P1-1（见下）

Flask 共 39 条路由（`/`＋38 条 `/api/*`）。前端 `api()`／`apiWait()`／`waitCmd()` 覆盖全部 UI 所需调用；`api()` 对 401（回登录页）、429、非 JSON、非 ok 均有处理；`waitCmd` 每 2 秒查 `/api/cmd/:id`、60 次＝120 秒超时，与两端 `done`／`failed` 语义一致。

**新发现（R11-P1-1，P1：Flask 兼容层忽略 `?node=`，多节点模式下静默错节点操作）**：

- 前端 `withNode()`（index.html:559-562）对 `/api/status`、`/api/openvpn/*`、`/api/sk5*` 一律追加 `?node=<当前节点>`；顶栏显示当前节点名；“设为当前”按钮切节点后 `refreshAll()` 重刷全部卡片。
- Worker 侧 `resolveNode()`（index.js）读 `?node=`／`X-Node`，不存在即 404、未指定且多节点即 400；全部 compat 路由按解析出的节点入队。
- **Flask 侧除 `init-pki` 外全部兼容路由忽略 `?node=`**：`/api/status`、`/api/openvpn/server|start|stop|restart|users|users/<name>|users/<name>/ovpn`、`/api/sk5|sk5/test|sk5/enable|sk5/disable|sk5/fail-open|sk5/udp-over-tcp` 的 handler 均不读 `request.args.get("node")`（全文件仅 :1234 init-pki 与 :1732 `/api/cmd` 读 node），一律在本机直接执行。
- 行为实证（本轮探针 `/tmp/r11-tests/r11_nodeparam.py`，真实 test_client，5/5）：注册远程节点 lightsail 后，`GET /api/status?node=<不存在>` → **200 本机状态**（Worker 应 404）、`GET /api/status?node=lightsail` → **200 本机状态**、`POST /api/sk5?node=lightsail` → **200 且配置落到本机**（host 127.0.0.1:11080 已存本机 sk5.json）；对照：`POST /api/openvpn/init-pki?node=<不存在>` 缺 force → 400、带 force+confirm → **404 节点不存在**——init-pki 是唯一读 node 的兼容路由。
- 后果：Flask 多节点模式下，选远程节点 B 后状态卡显示的是**本机**状态（顶栏却标着 B 的名字），保存 SK5／建服务／启停／建用户／吊销／开关 SK5 全部落在**本机**，无任何报错与提示。文档却宣称多节点支持两端“相同”（cloudflare/server-mode.md:23：“前端‘节点’页下拉选当前节点；`?node=` / `X-Node` 指定”），且 Flask 的节点表＋agent 轮询＋`/api/cmd`＋init-pki 的 node 处理证明多节点 Flask 本就是设计情形，不是单节点专属。单节点部署（面板本机即唯一节点）下不可见——这正是它能活过十轮审计的原因。
- 同族：R7-P1-1（Worker 兼容层状态失实）、R6-P1-1（via_sk5 语义错位）——都是“面板呈现的状态／操作对象与用户所指节点不一致”。定性 P1：静默错节点操作＋状态错标，无报错、无提示、无规避（远程控制只剩手写 `/api/cmd` 原始接口）。
- 修法方向（供修复路三选一）：(a) Flask 兼容路由读 `?node=`，指名非本机节点时像 Worker 一样入队并回 202＋cmd_id（前端 apiWait 已支持该形状）；(b) 前端在 Flask 模式且选了远程节点时明示“本地卡片仅限本机”（需先给 `/api/me` 加 mode 信号——两端现均不返回 mode）；(c) 文档收回 server-mode.md:23 的“相同”宣称，写明 Flask 模式本地卡片只管本机。真机复核归 live-9（多节点 Flask 真机格）。

**观察（不立案）**：
- `/api/nodes/<name>/install` 只在 Worker 有路由（`handleNodeInstall`，回 `command_template`）；Flask 无此路由，但前端“复制安装命令”按钮的 catch 里有客户端 `buildInstallCommand()` 回落（同文案、同提示），两端最终行为一致——契约不对称但有工作回落，不立案。
- `/api/audit` 只在 Flask 有路由，前端不调用；README:243 只把它列为 API、无 UI 承诺——无消费者、无影响，不立案。
- `/api/cmd` POST 回执无 `queued: true` 字段（Worker 兼容入队回执有；Flask init-pki 回执也有），但前端从不对 `/api/cmd` 调 apiWait（只调 compat 路由），该字段差无消费者，不立案。
- `/api/sk5` 等写操作在 Flask 直接执行回真实结果、在 Worker 回 202 排队——前端 apiWait 按 `d.queued && d.cmd_id` 分流，两端形状与设计注释一致，闭合。

### §2b Worker 路由 × agent 调用——发现 R11-P2-1（见下）

Worker 路由表（index.js:1062-1170）覆盖：公开 `/install-agent.sh`（＋.sha256）、Static Assets、`/api/login`、agent 三件（poll／report／bundle＋.sha256）、管理员会话后全部节点／命令／兼容层路由。逐项核对：

**新发现（R11-P2-1，P2：Worker 模式无改密端点，前端改密按钮恒 404）**：

- 前端“修改密码”按钮常驻顶栏、无模式判断（index.html:306、1024-1043），调 `POST /api/change-password`，失败只显示原始错误串。
- Flask 有该路由（app.py:907，须旧密码、新密码 ≥12 位且含字母＋数字，成功后 `session_version`＋1、全部旧会话作废）；**Worker 路由表无此分支**，请求落到 `err("未知接口", 404)`。
- 行为实证（本轮探针 `/tmp/r11-tests/r11_worker_changepw.mjs`，mock KV＋本地 fetch 入口，R8 同款）：`POST /api/login`（ADMIN_PASSWORD）→ 200＋会话 cookie；持会话调 `POST /api/change-password` → **404 `{"ok":false,"error":"未知接口"}`**；对照 `/api/me` 200、`/api/logout` 200。
- 结构原因：Worker 登录比对 `env.ADMIN_PASSWORD`（Cloudflare secret），面板侧改密须另有 KV 存哈希的设计，不存在；且两端 `/api/me` 均不返回 mode 字段，前端没有任何模式信号可用来隐藏该按钮（与 public-ip 不同——public-ip 同样只在 Flask 有端点，但前端 catch 里已明写“Cloudflare 模式无此端点，请手动填公网 IP/域名”，属有意的诚实降级；改密无此处理）。
- 文档亦无模式限定：docs/security.md:11 与 README:260 均把改密写成面板通用功能，未提 Cloudflare 模式不可用。
- 定性 P2：功能在一部署模式下恒不可用、报错含混（“未知接口”未说明原因与出路），但失败是诚实的（不谎称成功）、有线下出路（`wrangler secret put ADMIN_PASSWORD`）。修法方向（供修复路二选一）：(a) Worker 侧给改密一个诚实端点（405／501＋明示 `wrangler secret put ADMIN_PASSWORD`），前端原样显示；(b) 给 `/api/me` 加 mode 信号，前端在 Worker 模式下隐藏改密入口或改文案，并补文档注。真机复核不适用（无真实部署；行为已在 mock KV 本地入口上实证）。

**其余闭合**：
- `/api/openvpn/public-ip` 同样只在 Flask 有端点——前端 catch 已明写 Cloudflare 模式无此端点、请手动填，属有意的诚实降级，不立案。
- `/api/nodes/<name>/install` 只在 Worker 有——前端有客户端回落（见 §2a 观察），不立案。
- `/api/audit` 只在 Flask 有——前端不调用、Worker 的审计只记 KV（`audit:` 前缀），无消费者，不立案。
- 兼容层 init-pki 两端 force＋confirm 缺一 400（Flask app.py:1207-1255、Worker handleCompatInitPki:827-845），语义一致。

### §2c agent 动作白名单 × 面板命令入队——闭合

三处白名单逐字一致（13 个）：Flask `AGENT_ACTIONS`（app.py:199-205）、Worker `ACTIONS`（index.js:57-72）、agent `ACTIONS`（agent.py:731-744）——`install_prereqs, init_pki, create_server, start_openvpn, stop_openvpn, restart_openvpn, create_user, revoke_user, set_sk5, test_sk5, enable_sk5, disable_sk5, get_status`。Flask `/api/cmd` 对非法 action 回 400 并附 `allowed` 列表（:1736-1738）；agent 对未知 action 回 `unknown action: …`（不抛错）；Worker 兼容入队只发白名单内的动作（:1118-1160）。agent 对 `command/shell/cmd/exec/script/argv` 参数键纵深防御拒绝（:759-765）。闭合。

### §2d 队列文件 schema × 读写双方——闭合（附一处无影响的格式差）

Flask `_enqueue_command`（app.py:516-526）与 Worker `enqueueCommand`（index.js）生成字段完全一致：`id, node, action, params, status, result, error, created_at, sent_at, finished_at, retries`。消费方只读 `id/action/params`（agent.py:750-752）与 `status/sent_at/retries`（两端重投逻辑），字段齐全。格式差：`id` 为 uuid4 hex（Flask）vs 带横杠 randomUUID（Worker）、`created_at` 为 ISO 串（Flask）vs 毫秒 epoch（Worker）——无任何消费方解析这两个字段（前端 `waitCmd` 只读 `status/error`；`cmd_get` 两端原样透传），属无影响的格式差，记为观察、不立案。两端 `cmd_get` 回执字段一致（`id/node/action/status/result/error/created_at/sent_at/finished_at/retries`＋Worker 的 `timeout_hint` 附加字段），前端两种形状都接受。

### §2e index.txt／状态文件格式 × 解析器——闭合

`_parse_index_txt`（core:350-447）：6 列 TAB（status, expiry, revocation-date, serial, filename, subject-DN），文件名列恒为字面 `unknown` 时按序列号匹配已签发证书、CN 仅作最后手段；CA／server 条目过滤；同名多条以最后一条为准；V 行过期即报 expired（AL）。`_parse_status_log`（core:1105-）：状态文件恒逗号分隔（v1 裸行／v2 HEADER＋CLIENT_LIST 13 字段／TAB 管理面形状／前缀 7 字段四形全收）。行为证据：Core 套件 C1 单测 5/5（夹具为真机捕获行）＋本轮 19/19（§1e）。闭合。

### §2f systemd 单元 × 服务名——闭合

树内 5 个单元（`openvpn-sk5-panel.service`、`openvpn-sk5-policy.service`、`openvpn-sk5-singbox.service`、`openvpn-sk5-healthcheck.service`、`.timer`）与代码引用逐一对应：install.sh `enable --now` 四处（panel／policy／singbox／healthcheck.timer）、sk5_manager `SYSTEMD_UNIT = "openvpn-sk5-singbox.service"`（:59，is-active／is-enabled／reset-failed／restart 全用此名）、verify.sh 的 `sing-box-running` 格。`openvpn-server@server` 是发行版自带单元，不在树内、无需对应。无悬空引用。闭合。

### §2g 门禁 × 被测行为——闭合（附 R10 同款诚实缺口）

- verify-integration.sh：28 格（本轮重跑 28/28，§4a）。逐格核对：`/etc` 未碰、GET / 200、UI 入站／SK5 卡标记、未登录 401、登录 200、节点注册 token 只返一次、`/api/status` 三键齐全、保存禁用态不重起、B1 真翻转 enable 200 桩 run 恰 1 次、B2 disable 200 重起失败诚实上报、R4-BUG-1 格 A／B／B2、agent 配置 0600、get_status 全链 done、create_user 无 CA 时 failed 且无泄露——每格都对应真实行为，无空转格。
- verify.sh：25 个 distinct 门名（files、syntax、panel-reachable、panel-login、panel-status、sing-box-config／running／steady／version、openvpn、installed-agent-tree、install-copies-agent、install-agent-script、agent-bundle、sk5-toggle／toggle-on、sk5-enable-endpoint、sk5-disable、sk5-egress-ip、egress-crosscheck、stub-socks5、user-ovpn、starter-template-consistency、direct-forwarding）。starter 门本轮按原文逐字抽取重跑 PASS（§1a）；其余门代码自 R9 后未动（verify.sh 仅 :234 注释改动）。
- **诚实缺口（与 R10 §4c 同款）**：verify.sh 全量分段未在本轮重建重跑（R9 的 vfy harness 已失；重建成本高，live-9 headline-6 即该门禁的真机总验）。不冒充为本轮数，见 §8.2。

### §2h 文档宣称 × 代码——见 §6（全量核对通过，见新发现 R11-P1-1／R11-P2-1 的文档侧）

文档侧的数字类宣称本轮逐条复核（§6）：门禁数 28（重跑一致）、哈希钉位 4/4 一致、超时／计数类（60s／5s／10s／120s／3 次／5 次／5 分钟／15 分钟／825 天）全树 grep 一致、SK5 端口待确认注两端一致、ufw live-only 局限三处口径一致。文档侧的新问题是 R11-P1-1（server-mode.md:23 多节点“相同”宣称与 Flask 兼容层行为不符）与 R11-P2-1（改密无模式限定）。

## §3 全量复扫（历史 122＋R10 的 1 逐条定性）

复扫宇宙：R10 的 122 条（119 已修＋2 部分＋1 未验）＋R10 本轮新发现 1 条（R10-P2-1）＝**123 条**。定性口径与 R10 同款。复扫方法：先以 mtime 对账（§3.0）锁定自 R10 后动过的文件——仅 AO 三文件（README.md、verify.sh、panel/README.md）；其余文件 mtime 与 R10 §3.0 逐项一致，R10 实证沿用（同日、数小时内，复核时效内）；三文件内的历史项本轮全部行为重验（§1a／§2g／§4a）或逐项代码核对；再叠加 §2 契约闭合推导对全部兼容面的重查。

### §3.0 mtime 对账（R10 §3.0 → 本轮，UTC）

自 R10 后动过的文件仅三处（AO，文档／注释-only）：README.md（14:45:28）、verify.sh（14:45:28，:234 注释）、panel/README.md（14:45:24，115→113 行）。其余 19 个文件与 systemd 单元 mtime 均与 R10 §3.0 逐项一致（install.sh 14:11:22、app.py 13:15:22、core 13:14:53、sk5_manager 12:37:13、policy-routing.sh 12:13:01、verify-integration.sh 09:35:55、index.js 09:24:00、agent.py 00:58:12、index.html 09:20:59，余同 R10）。

### §3.1 R10 的 1 条新发现 → 本轮关闭

| 项 | R11 状态 | 证据 |
|---|---|---|
| R10-P2-1 文档行数／行号钉位再次漂移 | **已修** | AO（§1a）：全树 grep 归零、starter 门 PASS、门禁 28/28 |

### §3.2 R9 的 5 条＋live-8 的 2 条 → 本轮全部关闭（行为重验）

| 项 | R11 状态 | 证据 |
|---|---|---|
| R9-P1-1 队列 naive sent_at wedge 全通道 | **已修** | §1b：新树 adv D1/D1c 全绿；旧树 poll 500＋cmd_get 500 原样复现 |
| R9-P1-2 过期证显示 valid 且重建 409 | **已修** | §1c：新树 D9 报 expired、重建成功；旧树 valid＋409 原样复现 |
| R9-P2-1 队列损坏静默丢命令 | **已修** | §1b：新树 D4/D4b 备份字节一致；旧树无备份原样复现 |
| R9-P2-2 磁盘满登录 500 | **已修** | §1b：新树 D11 5/5；旧树限内双 500 原样复现 |
| R9-P2-3 文档行数／行号钉位过期 | **已修**（当轮 AM＋AO 根治） | §1a：AO 删数字后全树 grep 归零；同族未再复发（§6） |
| R8-BUG-1 默认重跑销毁线上 panel.db（高，阻塞） | **已修**（沙箱侧） | §1d：AN 探针原样重跑，新版毒树重跑行级全保留、登录 200；旧版 rc=1＋401＋admin 0 行原样复现；真机重验归 live-9 |
| R8-BUG-2 全新安装静默卸载 ufw（高） | **已修**（沙箱侧） | §1d：AN 探针原样重跑，新版 ufw 在＋2000 条原规则全在＋2 条放行、`ufw status` 111181 字节；旧版 apt 卸 ufw 原样复现；真机重验归 live-9 |

### §3.3 R10 的 2 条部分 → 本轮仍部分

| 项 | R11 状态 | 证据 |
|---|---|---|
| P0-3 bundle/install-agent.sh | **仍部分** | 逻辑已修（Flask agent-bundle 格 200＋tarball 含 agent.py；verify.sh install-agent-script 200）；部署态未验（§5） |
| P1-7 改密＋首登强制改密 | **仍部分（按设计）** | 改密 API＋UI 在位（代码未动，沿用 R10）；首登强制改密从未实现、文档已诚实，不另立案。但改密的 Worker 模式缺口另立 R11-P2-1（§2b）——P1-7 记的是“首登强制改密未实现”，R11-P2-1 记的是“改密功能本身在 Worker 模式下无端点”，不是同一条 |

### §3.4 R10 的 1 条未验 → 本轮仍未验

| 项 | R11 状态 |
|---|---|
| P0-1 部署态 | **仍未验**（§5：登录卡住＋KV 占位，与 R10 同卡点） |

### §3.5 R10 的 119 条已修 → 本轮复核

119＝R10 的 119（112＋R9 的 5＋live-8 的 2，已全部在 R10 当轮关闭）；本轮宇宙 123＝R10 的 122＋R10-P2-1。分两组：

**（a）修复宿在三个动过文件内的项——本轮全部行为重验或逐项代码核对，无一沿用旧证：** panel/README.md（R6-P2-4、R3-P2-14 文档侧；§6 全量核对＋§1a grep 归零）、README.md（R6-P2-4／R7-P2-6 文档侧部分；§6 全量核对；:71 条件化与 install.sh 一致）、verify.sh（R5-P2-1、R7-P1-1 门禁侧；仅 :234 注释改动，starter 门逻辑按原文逐字抽取重跑 PASS，`bash -n` 过；全量分段未重跑，见 §4c 诚实交代）。

**（b）其余项——修复宿在未动文件内，R10 实证沿用（§3.0 mtime 逐项一致，同日复核）：** agent/agent.py（13 格行为，R8 §4f 13/13）、cloudflare/src/index.js（Worker 18/18，R8 §1c；但本轮 §2 契约推导对 Worker 路由表做了全新逐项核对，发现 R11-P2-1——沿用的是行为实证，不是路由表本身）、core/easyrsa.sh、egress/test-egress.sh（§6 矩阵 R9 4/4）、egress/policy-routing.sh（AG 14/14 矩阵）、egress/sk5_manager.py（AJ 串行回归 13/13＋本轮门禁 28/28 侧面覆盖）、verify-integration.sh（门禁本身，本轮重跑 28/28）、panel/templates/index.html（AA 按钮在位，门禁 UI 格＋对比度核查覆盖；但本轮 §2 契约推导对前端调用做了全新逐项核对，发现 R11-P1-1 的前端侧）、install.sh（R7-BUG-1／R7-BUG-2／R8-P2-4 等；本轮 §1d AN 探针原样重跑全过）、panel/app.py（§1b adv 28/28＋D11 5/5＋lockout PASS；§4a 门禁 28/28）、core/openvpn_manager.py（§1e Core 19/19）。**R10 的 119 条中无一复发。**

### §3.6 U-1～U-12 认领表更新

| # | 项 | R11 更新 |
|---|---|---|
| U-1 | P0-1/2/3 部署态 | 仍未验（§5） |
| U-2 | R6-P1-1 真机复现 | 关闭（live-8 headline-5 显式重跑通过） |
| U-3 | UDP 数据面 | 关闭（live-7 S1/S2＋live-8 S2 再证 TCP+UDP 均走 SK5） |
| U-4 | R 符号链接自拷 | 关闭（无变化） |
| U-5 | R 逐项失败 die 分支 | 仍为“机制已证、分支未触发”：live-8 三装全程跑通；live-9 人为致败跟进 |
| U-6 | T 两变异 | 关闭（R8 已判；R9 T 变异重跑 17/2/4） |
| U-7 | verify-integration 瞬时红 | 关闭（R9/R10/R11 三次 28/28，一次过） |
| U-8 | 真机在位升级路径 | AN 沙箱已修（§1d），**待 live-9 真机重验**（live-9 与本轮并行在跑，§§12–19 待填） |
| U-9 | KV 竞态与 POP 传播 | 仍未验（无部署） |
| U-10 | 前端渲染级核查 | 关闭（live-8 headline-7 真机渲染通过；本轮静态核查 10/10 与之致，§7）；live-9 新树部署上须再跑一次 |
| U-11 | easy-rsa 真二进制签发 | 关闭（live-8 headline-2 以 real easyrsa 3.1.0 裁决） |
| U-12 | live-R5 结果 | 关闭 |

复扫合计：123 条＝已修 120（119＋§3.1 关闭的 1 条）／部分 2（P0-3、P1-7）／未验 1（P0-1）；**本轮新发现 2 条另计（R11-P1-1、R11-P2-1，见 §2／§8 差集）**。123＝120＋2＋1；新发现 2 条见 §8 差集。

## §4 套件重跑

### §4a 门禁 verify-integration.sh：28/28（本轮在 /tmp/r11 副本上实测）

`bash verify-integration.sh`：**PASS=28 FAIL=0 SKIP=0**。逐格与 R10 §4a 同款。宿主 /etc 复核干净（§8.4）。

### §4b Flask／Worker／Agent

- **Flask（本轮 adv 28/28＋lockout PASS＋D11 5/5＋nodeparam 5/5）**：AH 的 flask35.py 已随 /tmp 清理消失，**35/35 未原样重跑**——与 R10 同款缺口，本轮 Flask 面由 adv 探针 28 格＋lockout 探针＋D11 磁盘满 5 格＋nodeparam 探针 5 格＋门禁 28 格覆盖。AK 改动面逐格行为验证；本轮新发现的 R11-P1-1（?node= 忽略）由 nodeparam 探针 5/5 实证。35 格逐格对照缺失，记为本轮套件口径的缺口（见 §8.2），不冒充。
- **Worker 18/18（沿用 R8 实证）**：`cloudflare/src/index.js` mtime 与 R10 §3.0 逐字节一致（09:24:00，未动），R8 §1c 的 18/18 仍有效；本轮另以 mock KV 本地入口实证 R11-P2-1（登录 200 后改密 404，对照 me／logout 200）。部署态仍未验（§5）。
- **Agent 13/13（沿用 R8 实证）**：`agent/agent.py` mtime 与 R10 §3.0 一致（00:58:12，未动），R8 §4f 的 13/13 仍有效。

### §4c 门禁 verify.sh：全量分段未重跑（诚实交代）＋starter 门逻辑单跑 PASS

与 R10 §4c 同款：R9 的 vfy 分段 harness 已失，本轮未重建全量分段跑；已做：(1) `bash -n verify.sh` 过；(2) verify.sh 自 R10 后仅 :234 注释改动（marker 写法，代码未动）；(3) **starter-template-consistency 门逻辑按原文逐字抽取重跑 PASS=1 FAIL=0**（§1a：heredoc :630 按 marker 提取成功，tun 入站全字段与模板一致、dns.final='dns-direct'）。全量分段数（R9：22/0/1＋T 变异 17/2/4）沿用 R9，不冒充为本轮数。live-9 headline-6（verify.sh 双态真机跑）即该门禁的真机总验。

### §4d Egress 套件：test-egress.sh §6 矩阵 4/4（沿用 R9）

`egress/test-egress.sh`、`egress/sk5_manager.py`、`egress/policy-routing.sh` 三文件 mtime 与 R10 §3.0 逐项一致（未动），R9 §4d 的 §6 矩阵 4/4 与 AG policy 矩阵 14/14 沿用。本轮未重建 egress harness；sk5_manager 的保存／启停路径由门禁 28/28 侧面覆盖。

### §4e Core 套件 19/19（本轮重跑，§1e）

单测 5/5（状态日志，夹具为真机捕获行）＋探针 14 格（C0–C13）＝**19/19**。

### §4f 五套件总览

| 套件 | 规模 | 结果 |
|---|---|---|
| Flask adv＋lockout＋D11＋nodeparam（本轮重跑） | 28＋1＋5＋5 | **28/28＋PASS＋5/5＋5/5**（AH flask35 未原样重跑，见 §4b） |
| Worker（沿用 R8，代码未动）＋改密探针（本轮） | 18＋1 | **18/18＋改密 404 实证** |
| Agent（沿用 R8，代码未动） | 13 | **13/13** |
| Core（本轮重跑） | 19 | **19/19** |
| Egress（沿用 R9，代码未动） | 4＋14 | **矩阵 4/4＋policy 14/14** |
| verify-integration.sh（门禁，本轮重跑） | 28 | **28/28** |
| verify.sh（门禁） | 23 | **全量分段未重跑**（§4c）；starter 门逻辑单跑 PASS |

## §5 P0-1/2/3：真实 wrangler deploy 重验——卡在登录，仍未验

- **dry-run 通过**（本轮重跑，wrangler 4.161.0 经 npx）：`npx wrangler deploy --dry-run` exit 0——绑定列出 `env.PANEL_KV (REPLACE_WITH_KV_NAMESPACE_ID)` 与 `env.PANEL_MODE ("cloudflare")`。dry-run 只证配置可解析，不证部署。
- **真 deploy 卡在第一步：无登录**（本轮重跑，exit 1）：`In a non-interactive environment, it's necessary to set a CLOUDFLARE_API_TOKEN environment variable for wrangler to work.`（与 R7/R8/R9/R10 同一卡点；本机 `~/.config/.wrangler/` 下只有 logs＋metrics.json、无登录态，环境变量 `CLOUDFLARE_API_TOKEN` 未设置）。`wrangler.toml:32-33` 的 KV id 与 preview_id 仍是占位符 `REPLACE_WITH_KV_NAMESPACE_ID`／`REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`，是第二道卡点。
- **需要用户做的事（按顺序，缺一不可，与 R10 同款）**：(1) 在 Cloudflare 账号上建 API token（Workers＋KV 权限）并以 `CLOUDFLARE_API_TOKEN` 交给部署环境，或在可交互终端跑 `wrangler login`；(2) `wrangler kv namespace create PANEL_KV` 与 `--preview` 各一次，把返回的真实 id/preview_id 填进 `wrangler.toml`；(3) `wrangler secret put ADMIN_PASSWORD` 与 `wrangler secret put AGENT_BUNDLE_ORIGIN`；(4) `wrangler deploy`，再按 cloudflare/README:83 的要求换第二出口多点核（Workers 按 POP 慢速传播，单出口“没生效”不可信）。
- **结论**：P0-1/2/3（Worker 真实部署态）**仍未验**，与 R10 结论一致；Worker 代码侧的全部行为断言只在 mock KV＋本地 fetch 入口下成立，不是部署态证据。`--temporary` 未用——那会把 Worker 部署到临时抛弃账号上，不是用户的部署，测了也是冒充结论。

## §6 文档宣称全量核对（根 README／panel／cloudflare／security／flmx-reference／egress／core）

核对方法：每份文档的数字类宣称（门禁数、行数、端口、超时、重试上限、行号钉位）与行为类宣称逐条对代码/实测；数字以 `wc -l` 为准。自 R10 后动过的文件仅 AO 三处，其余文件与 R10 §6 的核对结论逐项复核（mtime 一致）＋本轮新验。

**通过的宣称**：
- 根 README:226 门禁数 28（本轮 verify-integration.sh 重跑 28/28 一致）；:198 哈希钉位 `install.sh:63-66`（本轮实测该四行仍是四条 sha256 钉死值，与 agent.py:122-132 逐值一致——950af37e…／20a6a9cd…／a612baa2…／3931476c…，AN 的改动全在其后）；:71 iptables-persistent 条件化（与 install.sh:214-262 一致；ufw 机 live-only 局限在 README:71、install.sh:241 日志、install.sh:770-775 警告三处口径一致，无文档反称——README:276 的 `netfilter-persistent save` 是卸载清理步骤，不是存活宣称）；:137 SK5 端口待确认注（1001 默认、9000 待回报，与面板字段旁注 index.html:470-471 一致——输入框默认值 1001＋同文案）；:140 重建 CA 步骤（两次确认、force+confirm、缺一 400、Worker 已转发——与路由 app.py:1207 与 index.js:827 一致）；:243 API 列表（与 §2a 读到的路由表一致）；:64 “重装不会轮换密码、CA 与服务端证书”（R8-BUG-1 证据：重跑后 admin.pass 仍是旧文件；install.sh 每轮重生成的只是 /etc secret.key，不是密码）；用户名规则 `[a-zA-Z0-9_-]{1,32}`＋保留名 `server`／`OpenVPN-CA`（与 core:99-119 一致）。
- 超时／计数类（全树 grep＋实测一致）：健康检查 60s（systemd timer `OnUnitActiveSec=60s`）、agent 轮询 5s（agent.py:70）、状态缓存 10s（app.py:960/981，R10 已验，文件未动）、重投 120s／3 次（app.py:535-536 与 index.js:86 同值）、登录限流 5 次／5 分钟／锁 15 分钟（app.py:194-196；§1b lockout 行为验证 429＋`retry_after_s: 900`）、证书 825 天（easyrsa.sh:50）。
- docs/security.md:12 重投分歧：Flask `SENT_MAX_RETRIES = 3`（app.py:536）与 Worker 同值（index.js:86），120 秒超时、Worker 非幂等首超时即 failed 的分歧均有记载；两端上限一致的宣称属实。
- panel/README 的函数签名清单与 :34 `/api/status` 形状：`create_user` 重名抛错＋legacy 先吊销再重签（core:812-820 在位）、`set_sk5` 部分合并语义、`test_sk5` TCP/UDP 分测、status 回执含 `openvpn{running, online_users, port, proto, subnet, dns, unit_active, pid, error, detail}／sk5／egress{ip, latency_ms, via_sk5, error}／modules_missing`（与 app.py:1015-1087 实测一致）；`get_user_ovpn` 缺失的说明属实。队列语义 :90（120 秒／3 次）与代码一致。
- egress/README “策略路由的并发与幂等”节（AG 重写，文件未动，沿用 R10）；cloudflare/README:126 via 语义与 :140 init-pki 转发（代码未动，沿用 R10）；server-mode.md:42 “待真实 wrangler deploy 验证”诚实（见 §5）；core/README（`web/` 已清）；docs/flmx-reference.md 的 FLMX 原做法列均标“不抄”。

**新发现的文档侧问题（立案见 §2／§8，不另立条）**：
- server-mode.md:23 称多节点支持两端“相同”（“前端‘节点’页下拉选当前节点；`?node=` / `X-Node` 指定”）——与 Flask 兼容层行为不符（§2a R11-P1-1：Flask 除 init-pki 外忽略 `?node=`）。该宣称是 R11-P1-1 的文档侧，修法随产品修法三选一（代码修则宣称成立；否则改宣称）。
- 改密文档无模式限定（docs/security.md:11、README:260）——与 Worker 模式无改密端点不符（§2b R11-P2-1）。该宣称是 R11-P2-1 的文档侧，修法随产品修法二选一。
- AO 根治有效：全树 grep 带日期实测数字归零（§1a）；本轮复扫未发现新的带日期行数／行号数字。R9-P2-3／R10-P2-1 同族未再复发。

## §7 前端静态对比度核查（本轮重跑；真机渲染归 live-8，已过；live-9 新树重跑待填）

方法：跑 `panel/static/contrast-check.py`（WCAG 相对亮度；底线 4.5、目标 7；玻璃卡按白 72% 叠在 #f6f7fb 上估算有效底色 #fcfdfe）。`index.html` 未动（mtime 09:20:59，与 R10 一致）。

**脚本结果：10/10 过底线 4.5（exit 0）；目标 7 达成 4/10——与 R9/R10 逐值一致。**

**结论**：静态核查通过底线（10/10，脚本 exit 0）；6 对低于目标 7（最低为成功绿字 4.92，仅高于底线 0.42），记为观察、不立案——门禁脚本的通过线就是底线，且 R7 九维视觉审计未以对比度立案。真机渲染已由 live-8 headline-7 通过（171 个可见文本 0 项低于 4.5、最薄 4.92、零 JS 报错），与静态核查一致，U-10 关闭；live-9 的新树部署上须再跑一次（live-9 headline-7 回归，§§16 待填）。

## §8 裁决与未验清单

### §8.1 裁决：**不能交付，差集 2 条**

| 级别 | 条目 |
|---|---|
| P1 | 1：R11-P1-1（Flask 兼容层忽略 `?node=`，多节点模式下静默错节点操作） |
| P2 | 1：R11-P2-1（Worker 模式无改密端点，前端改密按钮恒 404） |
| 高（阻塞） | 0：R10 的 1 条与 R9 的 5 条、live-8 的 2 条已全部修好（§1，变异红证齐全） |
| P0 | 0 未修、1 未验：P0-1/2/3 部署态仍未验（§5）；P0-3 部分（按设计，部署态未定） |

差集＝2 条（P1×1＋P2×1）。R10-P2-1 与 R9 的 5 条差集、live-8 的 2 条新 bug 已全部关闭（§3.1/§3.2），历史 123 条中 120 条已修（§3.6）；AK/AL/AM/AN/AO 的修复本身本轮全部行为验证通过（§1，变异红证齐全），套件全绿（§4f，见 §4b/§4c 的两处口径缺口）。但这不改变差集非空的结论：本轮契约闭合推导新发现的两条都是“生产方与消费方不一致”——Flask 兼容层与 Worker 兼容层对同一 `?node=` 契约实现不一致（R11-P1-1）、前端改密调用与 Worker 路由表不一致（R11-P2-1），且前者有文档宣称背书（server-mode.md:23“相同”），后者有文档无模式限定背书。

**下一步（按用户常设流程）**：派修复路修 R11-P1-1 与 R11-P2-1（两件分属 Flask 兼容层与 Worker／前端模式信号，文件面分别为 panel/app.py 与 cloudflare/src/index.js＋panel/templates/index.html＋文档，可并行；修法方向见 §2a／§2b），修完集成后跑 **AUDIT-R12（全量全局回头看，换推导方法独立复算）＋ live-9（真机总验）对账**，两路都过才交付。修复路开工前须先确认：本报告基线树版本（§0）与修复路所取树一致。

### §8.2 未验清单（逐项：为什么没验、谁能验）

1. **P0-1/2/3 真实 wrangler deploy（§5）**——卡在 Cloudflare 登录（非交互环境须 `CLOUDFLARE_API_TOKEN`，`~/.config/.wrangler/` 无登录态；wrangler.toml 的 KV id 与 preview_id 仍是占位符）。谁能验：用户建 API token（或交互式 `wrangler login`）＋`wrangler kv namespace create PANEL_KV`（生产＋预览）填实 id＋`wrangler secret put ADMIN_PASSWORD`／`AGENT_BUNDLE_ORIGIN` 后，live 路跑真实 `wrangler deploy`，再从第二出口核 POP 传播。本轮不许用 mock 冒充。
2. **前端渲染级检查**——本轮只做了静态核查（§7：10/10 过底线 4.5、4/10 达目标 7）；真机渲染已由 live-8 headline-7 通过，U-10 关闭。但 live-9 的树含 AN 改动后，渲染须在新树部署上再跑一次（live-9 headline-7 回归）。
3. **Cloudflare KV 竞态＋POP 传播**——依赖第 1 项的真实部署；无部署则无从测。谁能验：同第 1 项，部署后多点核。
4. **SK5 端口 1001 vs 9000**——用户从未确认哪个是 SOCKS5 口（面板默认 1001，文档已标注待确认，README:137＋index.html:470-471）。谁能验：用户回报；live 路再以确认后的端口跑 UDP/TCP 双栈。
5. **D13 PKI 段竞态**——沙箱无 easyrsa 二进制，两路并发安装／重跑时 `init_pki`＋`build-ca` 的先查后建竞态测不到（copy 段已验，见 R9 §2）；live-8 未跑并发安装（§17 为顺序三装），仍未验。谁能验：live-9 在真机上跑并发安装／并发重跑。
6. **D14 时钟跳变**——沙箱无 faketime，改系统时钟超出审计范围；仅代码级分析（锁定／会话／重投／健康全是墙钟）。谁能验：真机上以 faketime 或受控调钟复核（须用户授权调真机时钟）。
7. **Flask 35/35 未原样重跑**——AH 的 flask35.py 已随 /tmp 清理消失；本轮 Flask 面由 adv 28 格＋lockout＋D11 5 格＋nodeparam 5 格＋门禁 28 格覆盖（§4b），AK 改动面与新发现的 R11-P1-1 均逐格行为验证，但 35 格逐格对照缺失。谁能验：下一轮审计重建 flask35 或等效套件；live-9 的真机 S0–S4 覆盖同一面的行为。
8. **verify.sh 全量分段未重跑**——R10 的 vfy harness 已失，本轮只单跑了 starter 门逻辑（§1a PASS）＋`bash -n`；全量分段数沿用 R9。谁能验：live-9 headline-6（verify.sh 双态真机跑）即该门禁的真机总验。
9. **R8-P2-4 的真 ufw 验证**——live-8 记未验（R8-BUG-2 使前提不可达）；AN 沙箱已修（§1d，2000 条规则＋111181 字节输出真实走通 builtin 分支）。谁能验：live-9（ufw 启用＋长表宿主机真机重跑）。
10. **U-5 die 分支**——机制已证、分支未触发（live-8 三装全程跑通）；分支本身仍须一次人为致败才验得到。谁能验：live-9 人为致败安装步骤。
11. **live-9 结论是否入本报告**——未入。live-9 与本轮并行在跑，其报告当时 100 行、§§12–19 待填；本报告的沙箱结论不依赖它，live-9 落盘后须由主控对账（尤其 §8.2 的第 2/5/9/10 项与 R8-BUG-1/2 的真机验收、以及 R11-P1-1 的多节点 Flask 真机格）。

### §8.3 审计方法自述（供 R12 复核）

- 本轮方法：契约闭合推导（§2，8 类契约逐条核对生产方与消费方：Flask 路由 39 条×前端调用、Worker 路由表×agent 调用、白名单三处 13＝13＝13、队列 schema 两端字段一致、index.txt／状态文件格式×解析器、systemd 5 单元×引用、双门禁 25＋28 格×被测行为、文档宣称×代码）＋历史全量复扫（§3，123 条，mtime 对账＋三文件内逐项重验）＋新代码逐项行为验证（§1，亲自重跑、零 monkeypatch 走真实代码路径、阴性对照齐全）＋套件重跑（§4，Flask adv／Core／双门禁重跑＋Worker／Agent／Egress 沿用 mtime 未动文件）＋P0 部署态重验（§5）＋文档宣称全量核对（§6）＋前端静态对比度核查（§7）。
- 探针纪律：凡套件格先红，必先查探针本身（本轮修掉的探针问题：nodeparam 探针初版从 panel/data 读 admin.pass——密码实际在绑挂的 /etc/openvpn-sk5-panel/admin.pass，R10 adv 探针同款取法；starter 门抽取初版 sed 行号少取首行 `if`——改按 240-287 全块提取后一次通过。探针修好重跑后才定性，不在探针 artifact 上立案）。
- 沙箱边界：无 systemd／无 TUN／无 easy-rsa／无 openvpn 二进制／UDP sendto 临时端口 EPERM——凡涉此五项的结论均已标注分段环境或待真机（live-9），未把沙箱结论写成真机结论。fake apt 的“装 iptables-persistent 即卸 ufw”模型以 live-8 真机证据为锚（install3.log:8），fake easyrsa 的 index.txt 语义以 openssl 真签发为锚，mock KV 的 Worker 本地入口以 R8 的 18/18 同款为锚——桩的行为均有真机／真程序对照，不是凭空捏造。
- 本轮审计侧污染：无。探针进 `unshare -m` 绑挂（`/etc/openvpn-sk5-panel`、`/etc/sysctl.d` 绑 /tmp），事后 /etc 复核干净（见 §8.4）；宿主挂载点目录（`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`，run-flask／run-install 的 `mkdir -p` 留下）已 rmdir 删净。/tmp 资产（供 R12 复用）：`/tmp/r11`（树副本）、`/tmp/r11-tests/`（run-flask harness、r10_adv／r10_diskfull／r10_core／r10_lockout 探针、r11_nodeparam／r11_worker_changepw 探针、run_starter_gate.sh）、`/tmp/r10-tests/`（R10 探针原稿）、`/tmp/r10/`（树副本＋tree-old 回退树）、`/tmp/an-tests/`（AN 探针＋fakebin＋venv）。

### §8.4 清理记录（审计结束时）

- 分段面板（AN 探针的 staged 面板，https://127.0.0.1:8443）已由探针 `kill_panel()` 停；SOCKS stub 与 fixed-IP 服务器未在本轮启动；端口 8443/1080/11080 已空闲，无残留进程（`ps`＋`ss` 核对）。
- 宿主 `/etc/openvpn-sk5-panel/`、`/etc/openvpn/`（含 `server/` 子目录）、`/etc/sysctl.d/99-openvpn-sk5.conf`、`/run/openvpn-sk5-panel/` 均不存在（每次 unshare 绑挂后都 rmdir 复核）；宿主 /etc 复核干净。
- 项目树核查：本轮只写了本报告一个文件；树内其余文件 mtime 未动；`__pycache__` 检查：本轮 `py_compile` 在原树上跑过一次（§0 语法基线），产生的 4 个 `__pycache__`（core／panel／egress／agent）已删净；`core/tests/__pycache__/test_status_log.cpython-312.pyc`（2026-11-12 07:45 UTC）是早轮遗留、非本轮产生，留原样未动（`find -newer README.md` 仅剩 verify.sh——AO 改动，与本报告无关；live-verify-R9.md 是 live-9 的文件）。
- /tmp 资产（供 R12 复用）：`/tmp/r11`（树副本、deploy.log、contrast.log）、`/tmp/r11-tests/`（harness＋六探针＋starter 门抽取脚本），`/tmp/r10-tests/`（R10 探针原稿），`/tmp/r10/`（树副本、tree-old 回退树），`/tmp/an-tests/`（AN 探针＋fakebin＋venv）、`~/workspace/ae-tests/poison/`（毒包文件）。

# AUDIT-R23 — 全量全局回头看（交付前，第十一轮）

## 结论先写

**结论：不能交付（差集 4 条，全 P2）。**

历史 161 条：**已修 154、部分 2（P0-3、P1-7，按设计）、未验 1（P0-1，Cloudflare 真实部署）、新 4（R23-P2-1～P2-4，见 §6）、复发 0**。R14-BUG-1 经 BO 修复，本轮 §1 核验关闭（沙箱级；真机全程无人干预格属 live-15，待对账）。

- 审计员：独立审计路（未参与建设与修复路 BO；单审计员边做边写，不派子代理）
- 日期：2026-11-13（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R22 同等广度）
- 推导方法：**持久态形状矩阵审计**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性、R9 对抗操作员＋时间衰变、R10 环境矩阵×修复存活、R11 契约闭合、R12 外部输入枚举、R13 部署生命周期、R14 证据优先行为复推导、R15 交付文档驱动用户旅程重演、R16 门禁与证据链反向审计、R17 爆炸半径 FMEA、R18 命令生命周期状态机转移闭合、R19 跨面一致性、R20 输入形状全集、R21 失效传播追踪、R22 时间与顺序边界均不同）——先机械枚举全树所有持久化产物（panel.db 各表、agent_queue.json 三段、sk5.json、KV 各键、sing-box.json、server.conf、index.txt、health.json、secret.key、admin.pass），再逐产物×状态（缺失／空／损坏／旧版本／半写／并发写／不可读）×每个读取点，核每一格是诚实失败、降级、修复还是静默错；任一格静默错或丢数据即立案。R13 的部署生命周期审的是安装／升级流程，本轮是每个持久化产物的状态形状矩阵，二者不重叠；R22 的时间边界结论只作输入，不作本轮证据。
- 测试一律在 `/tmp/r23/ptree` 副本上跑；未动项目原文件（除本报告与本轮新增探针 `tests/r23_persist_shapes.py`／`tests/r23_persist_shapes.mjs`、探针 harness 修 `tests/r22_time_bounds.py`）；门禁自带 harness（venv＋桩 sing-box/systemctl/ip，面板以 nobody 跑）；未动任何真机。live-15 与本轮并行在跑，§4.4 只写“待 live-15 完工对账”，不提前判通过。
- 语法基线：`node --check`（index.js）与 `python3 -m py_compile`（panel／core／agent／egress）均过；`bash -n verify-integration.sh install.sh` 过。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明（与 R9–R22 同款记明）。
- 台账基数注：简报称复扫基数“R22 的 157＋1＝158”，但 R22 §5 明文“R21 台账 156 条＋live-14 新立 R14-BUG-1 1 条＝157 条”——R14-BUG-1 已在 157 内，158 系重复计一次。本轮按台账实际 157 条逐条复扫（§5），新立 4 条后累计 161 条；逐条核查 substance 与 158 口径相同，差额仅为重复计数。

## §0 树版本与 BO 改动确认

当前树是 BO 修复之后的新树。文件 mtime（UTC）与 sha256（前 12 位）均为本轮实测：

| 文件 | mtime (UTC) | 行数 | sha256（前 12 位） | 说明 |
|---|---|---|---|---|
| cloudflare/src/index.js | 2026-11-12 19:25:36 | 1473 | 089bb32da319 | 未动（R22 mtime，BJ） |
| cloudflare/README.md | 2026-11-12 19:28:49 | 262 | 47489de2f9a4 | 未动（R22 mtime） |
| panel/app.py | 2026-11-12 20:32:41 | 2790 | 6aa2e97da251 | 未动（R22 mtime，BN） |
| core/openvpn_manager.py | 2026-11-12 17:20:57 | 1550 | 3b5d7dfe9ea1 | 未动（R22 mtime，BB） |
| agent/agent.py | 2026-11-12 19:50:12 | 933 | f303af828555 | 未动（R22 mtime，BL） |
| egress/sk5_manager.py | 2026-11-12 21:01:56 | 1291 | e95e238ad44e | **动过（BO：`_apply_policy(verb)`＋`_repair_policy()` 改调 `repair`）** |
| egress/policy-routing.sh | 2026-11-12 21:02:02 | 489 | 59846a39a9d8 | **动过（BO：`repair` 动词＋`tun1_live()`＋REPAIR_MODE 分流）** |
| install.sh | 2026-11-12 16:46:54 | 1082 | 3f050f037e7a | 未动（R22 mtime，AZ） |
| verify-integration.sh | 2026-11-12 18:14:53 | 630 | 6ef6ba2db8b1 | 未动（R22 mtime，BE） |
| panel/templates/index.html | 2026-11-12 15:21:57 | 1259 | 4f7dc697451c | 未动（R22 mtime） |
| README.md | 2026-11-12 17:56:09 | 287 | 6154ecabe046 | 未动（R22 mtime） |

结论：自 R22 起全树只有 `egress/sk5_manager.py`（BO）与 `egress/policy-routing.sh`（BO）两处产品文件动过；其余文件 mtime 与 sha256 均与 R22 §0 基线一致。历史复扫按 mtime 规则：未动文件的既往结论沿用 R1–R22 证据，不冒充重跑；BO 的改动面本轮全量行为重验（§1）＋持久态形状矩阵全集重审（§2）。本轮新增树内文件仅两件 R23 探针＋一件 r22 探针 harness 修；`__pycache__` 为本轮 `py_compile`／探针产物，已清；宿主 `/etc/openvpn-sk5-panel/` 每轮探针后复核均为空（无凭据泄露）。

## §1 BO 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

| 探针 | 结果 | 说明 |
|---|---|---|
| BO tun1 修复 `tests/bo_tun1_repair.py` | **18/18** | T1–T5 内核格、R1–R8 脚本格、R7 两档序列、B1–B4 健康检查格全绿 |
| BM 黑洞自愈 `tests/bm_blackhole_selfheal.py` | **22/22** | 全绿（沙箱 netns＋mock 格；真机层 2 见 §4.4） |
| BK 存量形状 `tests/bk_stored_shapes.py` | **8/8** | 全绿 |
| 门禁 | **29/29** | 见 §3 |

定点变异红证（`/tmp/r23/m-mgr`、`/tmp/r23/m-script`，BO 探针为判据，逐棵恰红）：

| 变异 | 改动 | 结果 |
|---|---|---|
| m-mgr | `_repair_policy()` 改回 `_apply_policy()`（即 `enable` 动词） | BO 探针 B1–B4 全红（verbs 变 `['enable']`，B2 第二档 `r2=none` 永不恢复），R 格不动——`repair` 动词是承重层 |
| m-script | 脚本分发去掉 `REPAIR_MODE=1`（`repair` 与 `enable` 同路） | BO 探针 R1／R2／R3／R7 红（repair 又建占位 tun1＋装 linkdown 路由），B 格不动——REPAIR_MODE 分流是承重层 |

R14-BUG-1 关闭（沙箱级；真机“杀 sing-box → 黑洞 → systemd 自动重起成功 → 60 秒档内恢复走 SK5”全程无人干预格属 live-15，待对账）。

**BO 遗留项（do_restore boot 竞态）**：BO 报告留给本轮注意——boot 时 `do_restore` 仍走全 `enable`，占位符 tun1 与 sing-box 启动存在竞态。本轮 §2.5 定性为 **R23-P2-1（P2，新立案）**。

## §2 持久态形状矩阵审计（本轮推导方法）

### §2.1 全集清单（产物 × 状态 × 读取点）

机械枚举命令（附录 A）：全树持久化产物共 10 类；每类按状态（缺失／空／损坏／旧版本／半写／并发写／不可读）×每个读取点逐格核查。探针 `tests/r23_persist_shapes.py`（Flask／core／egress 面，5 个模式分进程跑）与 `tests/r23_persist_shapes.mjs`（Worker／KV 面，mock KV）为本轮新建；其余格沿用 R17–R22 套件与代码核（标注证据类型：探针／代码核／套件）。

| 产物 | 状态 | 读取点 | 结果 | 证据 |
|---|---|---|---|---|
| panel.db（整库） | 缺失 | `_db()` 首次启动 | 自动建表，首登生成随机密码 | 代码核 |
| panel.db | 空 SQLite（0 表） | `_db()` | CREATE TABLE IF NOT EXISTS 自愈，登录 200 | 探针 R4 |
| panel.db | 垃圾字节 | `_db()`／登录 | loud 500 `DatabaseError: file is not a database`，无静默错；恢复靠人工删库重起（新随机密码打印 stdout） | 探针 R3 |
| panel.db | 旧 admin 表（无 session_version） | `_db()` 迁移 | ALTER TABLE 补列，登录 200 | 探针 R5 |
| admin.password_hash | 损坏／非 bcrypt | `_check_password` | 非 str／空 → False；bcrypt 分支捕 ValueError／TypeError → False；salt:digest 分支 split 失败 → False；永不 500 | 代码核 |
| login_attempts.failures | 数字 123 | `_login_attempts_row`／登录 | loud 500（错密与对密同 500，无绕过；需 DB 写权限才触发） | 探针 R6 |
| login_attempts.failures | 字符串 "abc" | 同上 | 推导式逐字符过滤 → []，按无失败处理 | 代码核 |
| nodes.last_status | 垃圾／非对象 | `_node_snapshot`／`_update_node_status` | 垃圾 → None → {}；旧值损坏时合并写以 {} 起步覆盖 | 代码核＋套件 |
| audit_log | 写盘失败 | `_audit` | 全异常吞掉，不阻塞业务 | 代码核 |
| agent_queue.json | 缺失 | `_load_queue` | 空队列 | 代码核＋套件 |
| agent_queue.json | 空／垃圾／顶层非对象 | `_load_queue`／隔离 | `.corrupt` 备份（字节一致）＋审计行 `queue_corrupt_quarantined` | 探针 r21 6/6 |
| agent_queue.json | **不可读（chmod 000）** | `_load_queue`→`_save_queue` | **静默丢已排队命令，零审计行 → R23-P2-3** | 探针 R1 |
| agent_queue.json | 并发写 | `_QUEUE_LOCK` | 锁串行 | 代码核＋套件 |
| sk5.json | 缺失 | `_load_config`／`do_restore` | 默认值；restore 判未启用、留直连（正确） | 代码核＋探针 R11 对照 |
| sk5.json | 列表／垃圾 | `_load_config` | RuntimeError／ValueError，get_status 报 config_error 不 500 | 探针 R20 S5＋BK |
| sk5.json | port bool／float／字符串 | `_validate_stored` | 一律 ValueError 点名文件＋字段＋实际类型 | 探针 BK 8/8 |
| sk5.json | **列表／垃圾（boot 时）** | `do_restore` one-liner | **与缺失同判未启用、误导日志 → R23-P2-2** | 探针 R11 |
| sk5.json | 权限不可读 | `_load_config` | PermissionError 专报（不冒充解析错） | 代码核 |
| sk5.json | 残留 .tmp | `_load_config` | 只读 sk5.json，.tmp 被忽略 | 探针 R9 |
| sk5.json | 半写 | `_save_config` 原子写 | tmp＋replace，无半写窗口 | 代码核 |
| KV loginfail | 对象 | `recordLoginFailure` | 5 次失败即锁 15 分钟（对照） | 探针 W4 |
| KV loginfail | **数组 []** | 同上 | **锁账静默丢失、永不锁定 → R23-P2-4** | 探针 W1 |
| KV loginfail | 字符串／failures 为字符串 | 同上 | loud 500（fail-closed，无绕过） | 探针 W2／W3 |
| KV node: | 字符串／无名 | `listNodes` | 跳过＋console.warn，/api/nodes 200 | 探针 W5 |
| KV status: | 字符串 | compat /api/status | 200，不崩 | 探针 W6 |
| KV session: | 字符串 | `requireAdmin` | 401，不崩 | 探针 W7 |
| KV sk5cfg: | 字符串 | toggle／save | toggle 400（须先存完整配置）；save 照常 202，UDP 守卫读 .proto 得 undefined 而跳过 | 探针 W8／W9 |
| KV queue:/sent: | 非数组 | 11 处读点（kvArray） | 按 [] 处理＋warn | 探针 R19 12/12 |
| sing-box.json | 垃圾 | `_render_singbox_config` | 重渲染覆盖修复；`_singbox_check` 在 start 前拦坏配置（沙箱无二进制，门禁 B1 格覆盖） | 探针 R10＋代码核 |
| server.conf | 损坏／缺失 | render／解析 | 报错不静默（AU；R17 core 46/46） | 套件 |
| index.txt | 缺失 | `list_users` | [] | 代码核 |
| index.txt | 垃圾行（<6 字段／无 CN） | `_parse_index_txt` | 跳过，不崩；V-过期 → expired，R → revoked | 探针 R7 |
| index.txt | 未知状态字母 "X" | 同上 | 原样透传为 status "X"（见 O-R23-2） | 探针 R7 |
| health.json | 垃圾／字符串 | `last_health()` | None | 探针 R8 |
| health.json | 字典 | 同上 | 原样返回 | 探针 R8 |
| secret.key | 缺失 | `_load_or_create_secret` | 生成 32 随机字节 0600 | 代码核 |
| secret.key | 空（0 字节） | Flask 会话 | 伪造会话 401；真登录 500（fail-closed 砖掉，见 O-R23-1） | 探针 R2／R2b |
| secret.key | 发货值（已公开） | 同上 | 强制轮换（P0-5） | 代码核 |
| secret.key | 短（如 4 字节） | 同上 | truthy 即被当会话密钥用，无长度校验（见 O-R23-1） | 代码核 |
| admin.pass | 空／缺失 | `_ensure_admin_password` | 惰性：DB 为准，文件只是首密记录 | 代码核 |

### §2.2 本轮探针结果总表

| 探针 | 模式 | 结果 | 红格 |
|---|---|---|---|
| `tests/r23_persist_shapes.py` | main | 9/12 | R1（P2-3）、R11-list（P2-2）、R11-garbage（P2-2） |
| 同上 | empty_secret | 2/2 | ——（R2 伪造 401、R2b 真登录 500，见 O-R23-1） |
| 同上 | db_garbage | 1/1 | ——（loud 500） |
| 同上 | db_empty | 1/1 | ——（自愈，登录 200） |
| 同上 | db_old_admin | 1/1 | ——（迁移补列，登录 200） |
| `tests/r23_persist_shapes.mjs` | Worker／KV | 8/9 | W1（P2-4） |

### §2.3 新发现 4 条（全 P2，机制＋复现＋修法见 §6）

- **R23-P2-1** boot 时 `do_restore` 仍走全 `enable`——占位符 tun1 与 sing-box 启动竞态（§2.5）。
- **R23-P2-2** `do_restore` 的 sk5.json 损坏／列表形与“未配置”同判未启用，静默降级直连（§2.4）。
- **R23-P2-3** agent_queue.json 不可读时 `_load_queue` 静默空队列，下一次 `_save_queue` 销毁已排队命令且零审计行（§2.6）。
- **R23-P2-4** Worker `loginfail:<ip>` 为 JSON 数组时锁账静默丢失，该 IP 永不锁定（§2.7）。

### §2.4 R23-P2-2 机制（do_restore 静默降级）

`do_restore()`（egress/policy-routing.sh:434）原文 one-liner：`python3 -c 'import json,sys; sys.exit(0 if json.load(open("/etc/openvpn-sk5-panel/sk5.json")).get("enabled") else 1)' 2>/dev/null`。三种输入同一出口：缺失 → FileNotFoundError → rc=1；列表 → AttributeError（`.get`）→ rc=1；垃圾 → JSONDecodeError → rc=1。且 `2>/dev/null` 把 traceback 本身丢弃，restore 只记一句 `SK5 not enabled in stored config, leaving main table alone`——“未配置”与“损坏”在日志里完全同形。探针 R11（原文 one-liner，仅路径换探针临时目录）实测：list rc=1、garbage rc=1、missing rc=1、enabled-true (0, '')、enabled-false (1, '')。后果：一次重启后，已启用链的 VPN 流量走主表直连——正是该单元 P1-9 注释所称其存在意义要防止的结局（“without this unit a reboot silently turns `SK5 enabled` into direct egress”）。部分缓解：重启后面板 get_status 会报 config_error（`_load_config` 抛错），但须操作员主动查面板；单元日志本身在说谎。修法：缺失与损坏分流——缺失沿用现行“未启用”；不可解析／非对象时记 loud 日志（点名文件＋错误类型，不写内容）并以 distinct 退出码拒绝改动任何策略状态，绝不记“not enabled”。

### §2.5 R23-P2-1 定性（BO 遗留 boot 竞态）

定性：**缺陷（P2），立案**。证据链（代码＋单元文件，无沙箱外推）：① `systemd/openvpn-sk5-policy.service` 只有 `After=network-online.target openvpn-sk5-singbox.service` 与 `Wants=network-online.target`，对 sing-box 无 `Requires=`／`Wants=`——`After=` 仅排序；② sing-box 单元 `Type=simple`，“已启动”＝进程已 spawn，不等于 tun1 已建；③ `do_restore` 无任何 tun1 等待（与 `enable()` 的 10×0.5s 等待不对称）；④ `do_enable` 先调 `ensure_tun1`（policy-routing.sh:325）再装黑洞／rule（:340／:346）。竞态窗口［sing-box spawn → 建 tun1］对 restore 的 bash＋python3 冷启动，两边均为百毫秒量级，512MB 启动负载下真实张开。命中后果与 R14-BUG-1 同构：占位 tun1 → sing-box FATAL `configure tun interface: file exists` ×5 → StartLimitBurst（5/120s）→ 单元 failed；策略已装（黑洞＋rule＋linkdown 路由），流量黑洞兜底不泄漏，但 sing-box 已死，健康检查 `repair` 动词永不重启 sing-box——链路永久停在黑洞态，只靠人工 `ip link del tun1`＋reset-failed＋重起恢复（live-14 人工恢复已实测证实同款诊断）。触发概率未量化（沙箱无 systemd、无 boot 时序分布；live-15 不含 boot 竞态格），故 P2 而非高；fail-closed 方向＋面板诚实报 `blackholed_kill_switch`。修法二选一：restore 在 `do_enable` 前有界等待 `tun1_live`（超时则退 repair 路径），或 restore 走 `repair` 动词、把 tun1 路由留给 60 秒健康检查档补齐（BO 的 repair 语义已就绪）。

### §2.6 R23-P2-3 机制（队列不可读静默销毁）

`_load_queue()`（panel/app.py:516）对任何 OSError（不可读、权限错）直接返回空队列，无警告、无审计行；随后任意一次 `_save_queue()` 以原子替换写回空队列，不可读文件里的已排队命令被物理销毁。探针 R1 实测（nobody 身份，队列 chmod 000）：poll 200（空）、再 enqueue 202、旧 cmd_id 查 `cmd_get` 404、审计行中关于队列丢失的为 0。注意与 R21-P2-1 的分工：BN 的隔离路径只在 JSON 解析失败时触发；OSError 走另一条静默分支——同文件、同一“丢命令”谓词、不同前件，是 R21-P2-1 的同族新成员而非复发（R21 的备份层仍在位，R21 探针 6/6 本轮重跑全绿）。修法：`_load_queue` 的 OSError 分支记审计行 `queue_unreadable`（result=failed，detail 只写路径＋errno，不写内容），且在该状态下 `_save_queue` 拒绝覆盖（或先把不可读文件移为 `.unreadable` 备份再写空）。

### §2.7 R23-P2-4 机制（Worker loginfail 数组锁死失效）

`recordLoginFailure()`（cloudflare/src/index.js:379）读 `loginfail:<ip>` 后直接 `rec.failures = [...]` 再 `kvPutJson` 写回。记录为 JSON 数组时：`rec.failures` 赋值挂在数组实例上，`JSON.stringify` 序列化数组时丢弃额外属性——每次写回都把失败计数丢掉，该 IP 的失败数恒为 0，永不锁定。探针 W1 实测：6 次错密 → [401×6]，无 429；对照 W4（对象记录）→ [401×5, 429]。字符串／数字记录则在赋值处抛 TypeError、经顶层 catch 成 loud 500（W2／W3，fail-closed）；failures 为字符串时 `(rec.failures || []).filter` 抛 TypeError 同款 500。同一手改 KV 前件类（与 R18／R19 同款），后果是登录限流静默失效、无限撞库。修法：`recordLoginFailure` 入口以 kvObject 式守卫归一化（非对象／数组一律重置为 `{failures: [], locked_until: 0}`＋console.warn 记 key 与 typeof，不写内容），与 BJ 的 kvArray 同族。

### §2.8 面×属性矩阵（双面能力对齐枚举）

| 能力 | Flask 面 | Worker 面 | 对齐 |
|---|---|---|---|
| 队列损坏（整文件） | 隔离＋审计行（BN）✓ | JSON.parse 抛错 → 顶层 loud 500（代码核，未探针） | 均不静默丢，形态不同可接受 |
| 队列不可读（OSError） | **静默销毁 → P2-3** | KV 无“不可读”形态（get 失败即 500） | Flask 面缺口 |
| 队列容器非数组 | 非列表按空处理＋审计（BA）✓ | kvArray 归一化＋warn（BJ）✓ | 对齐 |
| 登录限流记账损坏 | failures=123 → loud 500（R6）✓ | **数组 → 静默失效 → P2-4**；字符串 → loud 500 ✓ | Worker 面缺口 |
| boot 恢复 sk5.json 损坏 | ——（面板不恢复策略） | —— | 仅 egress 面：**静默降级 → P2-2** |
| tun1 占位竞态 | 健康检查 repair（BO）✓ | —— | 仅 boot 路径：**竞态 → P2-1** |
| 下载守卫（吊销／过期） | 快照守卫（AW）✓ | 快照守卫（BJ）✓ | 对齐 |
| sent 超时重投 | Flask 重投全部（R5 分歧，已文档化） | 仅幂等／只读重投（R5 分歧，已文档化） | 分歧已接受，见 docs/security.md:12 |

### §2.9 观察（不立案）

- **O-R23-1** secret.key 无长度校验：空文件时 Flask 视 `b""` 为未设密钥——伪造会话 401（R2，不可伪造），但真登录直接 500（R2b，`RuntimeError: The session is unavailable because no secret key was set`），面板砖掉直至删 key 重起；fail-closed 且响亮，不立案。短密钥（如 4 字节）truthy 即被当会话密钥用，强度弱但功能正常；前件须手改／截断文件。
- **O-R23-2** index.txt 未知状态字母原样透传：6 字段垃圾行状态 "X" 的用户以 status "X" 现身（R7），下载守卫（只拦 revoked／expired）放行其 .ovpn；握手层 CRL 仍拒该证书，不构成越权。修法方向：解析器把 V／R／E 之外的状态字母当无效行跳过或标 `unknown` 并禁下——留给修复路裁定，不立案。
- **O-R23-3** 自愈行为无文档行：BM 的 `policy_repaired`／`blackholed_kill_switch`、BO 的 `repair` 动词在 9 份文档中零提及（grep `repair|check_health|自愈|policy_repaired|blackholed` 0 命中）；`policy-routing.sh repair` 已在 usage 行里，但 egress/README 只写 enable／disable／restore／status。无虚假宣称，仅缺失说明，不立案；建议修复路补一行。

## §3 门禁本身是审计对象（29 格逐格机械推导＋§7 变异红证）

- 现树门禁：`bash verify-integration.sh` → **PASS=29 FAIL=0 SKIP=0**（本轮实测，约 25 秒）。
- 机械推导：脚本内 `ok "` 出现 31 次；减 1——`check()` 辅助函数定义处的 `ok "` 是死代码（函数从未被调用）；减 1——开／关两条互斥分支中同一 `ok "` 只可能命中一条；31−1−1＝29，与运行时汇总 PASS=29 对账一致。
- §7 两层（BE）：常量逐键比对（4 名逐键相等且非空）＋字典绑定（`_PINNED_SHA256` 的 (binary, arch)→常量名、值等于 install.sh 赋值、恰好 4 项）。七变异逐棵恰红 28/1（仅 §7 钉死哈希格红，其余 28 绿）：m-dict-sb、m-dict-ts、m-dict-missing、m-dict-extra、m-const-sb、m-install-sb、m-char——字典互换＋缺项／多项变异红证齐全。
- 门禁 §7 变异树构建器 `tests/build-mutants.py` 本轮重跑：`built 7 mutants in /tmp/r23/mutants`。

## §4 回归套件＋文档＋P0 干跑＋live-15 对账

### §4.1 R17 四套件＋BG／BK／BM／BO／R18–R22 回归（活树新鲜副本 /tmp/r23/ptree）

| 套件 | 结果 | 说明 |
|---|---|---|
| r17_flask | **86/89** | 仅 3 红，全为预期 OBSERVED 翻转（F4-02b／F4-13／F4-15，R17-P1-1 钉死格） |
| r17_core | **46/46** | 全绿 |
| r17_agent | **33/33** | 全绿 |
| r17_worker | **33/35** | 仅 2 红，全为预期 OBSERVED 翻转（W5-05／W5-06a） |
| r18_bg（Flask poll 守卫） | **22/22** | 全绿（读 `BG_TREE`；本轮初版共用 data 目录致 admin 已存在断言失败，改独立 data 目录后通过——harness 问题，非产品） |
| bk_stored_shapes | **8/8** | 全绿 |
| bm_blackhole_selfheal | **22/22** | 全绿（沙箱 netns＋mock 格；真机层 2 见 §4.4） |
| bo_tun1_repair | **18/18** | 全绿（§1；两棵回退变异逐棵恰红） |
| r21_queue_quarantine | **6/6** | 全绿（BN 闭合仍成立） |
| r20_input_shapes | S1/S2/S6 按预期翻转 | 缺陷签名不再复现（S3／S4／S5／S7 绿；S6 须 root 身份跑 unshare，本轮以 root 补跑，HB-OK） |
| r22_time_bounds.py | **22/22** | 本轮修了两处探针 harness 缺陷后全绿（见下） |
| r22_time_bounds.mjs | **12/12** | 全绿 |
| r19_worker_nonlist_container | **12/12** | 全绿 |
| r19_worker_ovpn_download | **8/8** | 全绿 |
| bi_worker_queue_race | **15/15** | 全绿（BI 修复成立） |
| bi_worker_malformed | **18/18** | 全绿（BI 修复成立） |
| bh_worker_poll_guard | **20/20** | 全绿 |
| r18_worker_queue_race | RACE-02／RACE-05 红 | **预期**：R18 缺陷演示探针，断言缺陷行为；BI 探针 15/15 为现行门 |
| r18_worker_malformed | 4 红 | **预期**：同上；BI 探针 18/18 为现行门（M-06 行实测记录已被 sweep 为 failed，探针断言的是修前值 'hello'） |

**r22 探针 harness 修（本轮，产品代码未动）**：① T2b 种子 299s→298s：错密登录在沙箱耗时 ~2.08s（实测），299s 种子在记录时已越 300s 窗口被剪掉——产品按窗口语义正确行事（T2a 300s 侧通过、行内仅剩 1 条新失败为证），是探针 1s 裕量不够；298s 仍测近边界，`< 300` 精确算子以代码核为准。② T7a／T7c 的 fake_sleep 加 sub-second 过滤：`mock.patch("time.sleep")` 是全局的，`heartbeat_status()`→`server_status()` 跑子进程，`subprocess.communicate()` 的等待循环内部调 `time.sleep(0.001/0.002/0.004…)`——负载高时子进程回得慢，这些内部轮询混进 backoff 序列（栈回溯已定位到 `subprocess.py:2141 _communicate → self.wait`）；退避值均 ≥5s，过滤 <1s 不改格意图。修后 r22_py 22/22（含 T7a [10,20,40,60,60] 与 T7c [10]）。另：r20 的 S6 须 root 跑（unshare），且 /tmp/r20/ptree 须全局可读（userns 内 root 对未映射 uid 的 770 目录无 CAP_DAC_OVERRIDE，致 ModuleNotFoundError）——均为 harness 环境项。

### §4.2 文档 stale 检查＋对比度

- stale grep 0 处：`SCRIPT_VERSION`／`resolve_version` 残留 0（不含 audit／live 报告）；“门禁 28”／`28/28`／`PASS=28` 残留 0；tests/README 未提 r20–r23 探针（自 R17 后即未更新，各路一致，不立案）。
- BO 的 `repair` 动词与 BM 自愈行为无文档行（O-R23-3）；README:156 与 egress/README:121 的“绝不会悄悄改走直连”宣称在 daemon 死亡面上仍成立，P2-2 破的是 boot＋损坏配置面，修法须保该宣称（见 §6）。
- 对比度：`panel/static/contrast-check.py` → **10/10 PASS，0 FAIL**；目标 7 达成 4/10（与 R15–R22 同款分布，非门禁底线）。

### §4.3 P0 dry-run

`cloudflare/` 目录下 `npx wrangler@4.161.0 deploy --dry-run` → **exit 0**（须在 cloudflare/ 下跑）。KV id 仍为占位 `REPLACE_WITH_KV_NAMESPACE_ID`／`REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`；真实部署 P0-1/2/3 仍卡用户侧（§5，第九次待决断）。

### §4.4 live-15 对账

**待 live-15 完工对账。**（live-15 与本轮并行：R21/BN 与 BO 的真机格＋S0–S4 回归；本轮不预写其结论。）

## §5 历史全量复扫（157 条逐条核现状＋本轮新立 4 条）

R22 台账 157 条（153 已修＋2 部分＋1 未验＋1 未修 R14-BUG-1）；本轮新立 4 条，累计 **161 条**。

| 状态 | 数量 | 构成 |
|---|---|---|
| 已修 | 154 | R22 的 153＋R14-BUG-1（BO 修完，本轮 §1 行为重验 18/18＋两棵回退变异逐棵恰红，关闭，沙箱级；真机格待 live-15） |
| 部分 | 2 | P0-3（首登强制改密未实现，文档已诚实）、P1-7（同族，见 R19 台账）——均按设计 partial，不重立 |
| 未验 | 1 | P0-1（Cloudflare 真实部署从未验，§4.3；第九次待用户决断） |
| 未修（本轮新） | 4 | **R23-P2-1～P2-4**（§6） |
| **复发** | **0** | 无一已修条目复发：R13-P2-5 的 agent `_as_int` 修复仍成立（agent 套件 33/33）；R17-P1-1 的 BG／BH 修复仍成立（Flask 86/89、Worker 33/35，红格均为预期翻转）；R18／R19／R20 的 BI／BJ／BK／BL 修复仍成立（§4.1 重跑全绿）；R9-P2-1 的备份层仍成立（R21 探针 6/6）；R21-P2-1 的 BN 审计行仍成立（R21 探针 6/6）；BM 两层仍成立（BM 探针 22/22）；R22 的时间边界结论仍成立（r22 两套件 22/22＋12/12，探针 harness 修见 §4.1） |

**未动文件规则**：自 R22 完工（2026-11-12 20:54 UTC）起，全树唯一产品代码改动是 BO 的 `egress/sk5_manager.py`（21:01）与 `egress/policy-routing.sh`（21:02）；其余产品文件 mtime 均 ≤20:32（BN）——BJ／BK／BL／BM／BI／BG／BH 的修复文件一字未动，结论沿用 R1–R22 证据，不冒充重跑。新增文件仅为报告（AUDIT-R23、live-verify-R15）与探针（r23 两件＋r22 harness 修）；`__pycache__` 为本轮产物，已清。

**待用户决断（第九次未复，自 R8 §5 起）**：P0-1/2/3 的 Cloudflare 真实部署——需用户创建 Cloudflare API token 或交互式 `wrangler login`，并填 `wrangler.toml` 的 KV id＋preview_id、跑 `wrangler secret put ADMIN_PASSWORD`、配 `AGENT_BUNDLE_ORIGIN`。若用户永不启用，交付文档须把 Cloudflare 模式部署状态标为未验。另：SK5 端口 1001 vs 9000 仍待用户确认（面板默认 1001，文档已标待定）。

## §6 结论

**不能交付（差集 4 条，全 P2）。**

### R23-P2-1（P2）boot 时 `do_restore` 走全 `enable`，占位符 tun1 与 sing-box 启动竞态

- 机制：`openvpn-sk5-policy.service` 仅 `After=` 排序 sing-box、无 `Requires=`／`Wants=`；sing-box `Type=simple`，started＝spawn≠tun-ready；`do_restore` 无 tun1 等待（`enable()` 有 10×0.5s 等待）；`do_enable` 先 `ensure_tun1` 再装黑洞／rule。窗口［spawn→建 tun1］对 restore 冷启动真实张开。
- 复现：代码＋单元文件核实（沙箱无 systemd，触发概率未量化）；命中后果与 R14-BUG-1 同构——占位 tun1 → sing-box FATAL ×5 → StartLimitBurst → failed，策略已装使流量黑洞兜底，健康检查 repair 永不重启 sing-box，链路永久停在黑洞态，只靠人工 `ip link del tun1`＋reset-failed＋重起恢复。
- 修法：restore 在 `do_enable` 前有界等待 `tun1_live`（超时退 repair 路径），或 restore 走 `repair` 动词、tun1 路由留给 60 秒健康检查档补齐。

### R23-P2-2（P2）`do_restore` 把 sk5.json 损坏／列表形当成“未配置”，静默降级直连

- 机制：one-liner `sys.exit(0 if json.load(...).get("enabled") else 1)` 对缺失／列表／垃圾同出 rc=1，且 `2>/dev/null` 丢弃 traceback；日志“SK5 not enabled in stored config”对“未配置”与“损坏”同形。
- 复现：探针 R11 原文 one-liner 实测 list rc=1、garbage rc=1、missing rc=1、true (0, '')、false (1, '')。重启后已启用链流量走主表直连——正是 P1-9 单元注释称其存在意义要防止的结局。
- 修法：缺失与损坏分流——缺失沿用现行；不可解析／非对象时记 loud 日志（点名文件＋错误类型，不写内容）并以 distinct 退出码拒绝改动任何策略状态，绝不记“not enabled”；面板 get_status 的 config_error 是部分缓解，不可替代。

### R23-P2-3（P2）agent_queue.json 不可读时静默销毁已排队命令

- 机制：`_load_queue` 对任何 OSError 直接返空队列，无警告、无审计行；随后 `_save_queue` 原子替换写回空队列，不可读文件里的命令被物理销毁。BN 的隔离路径只覆盖 JSON 解析失败，不覆盖 OSError——同文件同谓词、不同前件的同族新成员（非 R21-P2-1 复发）。
- 复现：探针 R1（队列 chmod 000）：poll 200、再 enqueue 202、旧 cmd `cmd_get` 404、队列丢失审计行 0。
- 修法：`_load_queue` 的 OSError 分支记审计行 `queue_unreadable`（result=failed，detail 只写路径＋errno）；该状态下 `_save_queue` 拒绝覆盖（或先把不可读文件移为 `.unreadable` 备份再写空）。

### R23-P2-4（P2）Worker `loginfail:<ip>` 为 JSON 数组时登录限流静默失效

- 机制：`recordLoginFailure` 在数组记录上 `rec.failures = [...]`，`JSON.stringify` 序列化数组时丢弃额外属性，失败计数每次写回都被丢掉，该 IP 永不锁定。
- 复现：探针 W1：6 次错密 → [401×6]，无 429；对照 W4（对象记录）→ [401×5, 429]。字符串／数字记录抛 TypeError 成 loud 500（W2／W3），无绕过。
- 修法：`recordLoginFailure` 入口以 kvObject 式守卫归一化（非对象／数组一律重置为 `{failures: [], locked_until: 0}`＋console.warn 记 key 与 typeof，不写内容），与 BJ 的 kvArray 同族。

## §7 本轮未验与上限（诚实清单，不冒充）

- live-15 未完工：R21/BN 与 BO 的真机格、S0–S4 回归均待对账；R14-BUG-1 的关闭为沙箱级。
- Worker 面真机格以 mock-KV 为准：无真实 Cloudflare 部署（P0-1，第九次待用户决断）；wrangler dry-run exit 0 不等于部署可用。
- arm64 安装格从未在真机上验过（无 arm64 机）；门禁 §7 的 arm64 绑定只在沙箱变异树上验。
- R23-P2-1 的触发概率未量化：沙箱无 systemd、无 boot 时序分布；修法验证须在测试机上多轮重启采样，或以确定性修法（等待／repair 动词）消除竞态本身。
- `sing-box check` 门禁：沙箱无 sing-box 二进制，`_singbox_check` 的坏配置拦截只以代码核＋门禁 B1 桩格覆盖；真机 enable 路径属 live 轮。
- panel.db 锁定态（并发写超时）未探针实测：sqlite3 默认 5 秒超时，超时后 loud 500，代码核。
- admin.pass 空／损坏未探针实测：DB 为准、文件只是首密记录，代码核为惰性。
- T2b 的 `< 300` 精确算子以代码核为准（探针测 298s 近边界，见 §4.1）；R22 的 O-R22-1／2／3 观察仍为不立案。

## 附录 A：§2 普查的机械推导命令（可复现）

```bash
# 产物枚举：持久化写点
grep -rn "read_text\|json.load\|json.loads\|sqlite3.connect\|CREATE TABLE" \
  panel/app.py core/openvpn_manager.py egress/sk5_manager.py agent/agent.py \
  cloudflare/src/index.js | grep -v "^.*#" | head -60
# KV 键全集
grep -n "kvGetJson(env, \`\|kvPutJson(env, \`" cloudflare/src/index.js
# 队列读点全集
grep -n "_load_queue\|_save_queue\|_quarantine_corrupt_queue" panel/app.py
# restore one-liner 原文
sed -n '434,452p' egress/policy-routing.sh
# 单元排序
cat systemd/openvpn-sk5-policy.service systemd/openvpn-sk5-singbox.service
```

## 附录 B：本轮验证命令速查（可复现）

```bash
# 探针树与 venv（/tmp/r21/venv 沿用；ptree 为活树副本）
cp -a ~/workspace/openvpn-sk5-panel /tmp/r23/ptree
chmod -R a+rX /tmp/r23/ptree /tmp/r21/venv
# R23 Flask 探针（5 模式分进程，各用独立 data 目录；见 tests/r23_persist_shapes.py 卷首）
runuser -u nobody -- env PYTHONPATH=/tmp/r21/venv/lib/python3.12/site-packages \
  R23_TREE=/tmp/r23/ptree OVPN_PANEL_DATA_DIR=<data> \
  OVPN_PANEL_SECRET_PATH=<data>/secret.key \
  OPENVPN_CA_DIR=/tmp/r17/fixture-ca OPENVPN_SERVER_DIR=/tmp/r17/fixture-server \
  R23_MODE=main python3 tests/r23_persist_shapes.py
# R23 Worker 探针
node tests/r23_persist_shapes.mjs
# BO 探针与回退变异（/tmp/r23/m-mgr、/tmp/r23/m-script）
python3 tests/bo_tun1_repair.py
# 门禁与 §7 变异
bash verify-integration.sh  # PASS=29 FAIL=0 SKIP=0
python3 tests/build-mutants.py ~/workspace/openvpn-sk5-panel /tmp/r23/mutants
# 回归批处理见 /tmp/r23/regress.sh（R17 四套件＋BG／BK／BM／BO／R18–R22）
# 对比度与 P0 干跑
python3 panel/static/contrast-check.py  # 10/10 PASS
cd cloudflare && npx wrangler@4.161.0 deploy --dry-run  # exit 0
```

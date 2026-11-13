# AUDIT-R24 — 全量全局回头看（交付前，第十二轮）

## 结论先写

**结论：不能交付（差集 1 条，P2）。**

历史 163 条：**已修 159、部分 2（P0-3、P1-7，按设计）、未验 1（P0-1，Cloudflare 真实部署）、新 1（R24-P2-1，P2）、复发 0**（数字以 §5、§6 为准）。

- 唯一新差集：**R24-P2-1**——enable 路径占位符写出的 linkdown 路由骗过 `_policy_active()`（判真、repair 永不触发、占位符堵死 sing-box 重启、`get_status` 的 `policy_routing_active` 被骗），新探针 `tests/r24_enable_placeholder.py` 20/20 行为复现。BS 遗留项（陈旧 linkdown 路由骗过 `_policy_active()`）裁定为缺陷立案，非接受项。
- R23 的 4 条（BP／BQ／BR）与 R15-BUG-1（BS）沙箱级全部关闭（探针重跑＋定点变异恰红，真机格待 live-16）；门禁干净树 **29/29**（串行重跑）；回归套件除预期翻红格外全绿；文档过期 0 处；P0 干跑（wrangler 4.161.0 deploy --dry-run）exit 0，但 P0-1 仍未验。

- 审计员：独立审计路（未参与建设与修复路 BP／BQ／BR／BS；单审计员边做边写，不派子代理）
- 日期：2026-11-13（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R23 同等广度）
- 推导方法：**启用路径状态机×读者矩阵审计**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性、R9 对抗操作员＋时间衰变、R10 环境矩阵×修复存活、R11 契约闭合、R12 外部输入枚举、R13 部署生命周期、R14 证据优先行为复推导、R15 交付文档驱动用户旅程重演、R16 门禁与证据链反向审计、R17 爆炸半径 FMEA、R18 命令生命周期状态机转移闭合、R19 跨面一致性、R20 输入形状全集、R21 失效传播追踪、R22 时间与顺序边界、R23 持久态形状矩阵均不同）——先机械枚举 enable／restore／repair／disable 四条路径能把内核＋存量写成的全部状态（占位 tun1、linkdown 路由、黑洞-only、rule 无路由、路由无 rule、rule＋黑洞无 tun1、表空、半写配置等），再逐状态×每个读者／裁决点（`_policy_active`、`_repair_holding`、`check_health` 各分支、`get_status`、`_cached_sk5_status`、面板展示、agent 心跳），核每一格是诚实、降级、修复还是静默错；任一格静默错即立案。R23 的持久态形状矩阵审的是产物损坏态，本轮是路径写出的内核状态×读者裁决，二者不重叠；R22 的时间边界结论只作输入，不作本轮证据。
- 测试说明：Flask 面探针在 `/tmp/r24/ptree` 活树副本上跑（nobody＋venv）；脚本／内核／Worker 探针直接读活树（只读产品文件，内核态在私有 netns 内，Worker 面为 mock KV）；未动任何真机。live-16 与本轮并行在跑，§4.4 只写“待 live-16 完工对账”，不提前判通过。
- 语法基线：`node --check`（index.js）与 `python3 -m py_compile`（panel／core／agent／egress）均过；`bash -n verify-integration.sh install.sh` 过。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明（与 R9–R23 同款记明）。
- 台账基数注：R23 台账 161 条（154 已修＋2 部分＋1 未验＋4 新）；live-15 新立 R15-BUG-1（P2）1 条，本轮复扫基数 161＋1＝162 条。

## §0 树版本与四路修复确认

本轮开工时（2026-11-13 06:11 CST）树版本（UTC mtime，sha256 前 12 位；本轮亲自实测，与主控交接表逐项一致）：

| 文件 | 行数 | sha256 | mtime (UTC) |
|---|---|---|---|
| egress/policy-routing.sh | 588 | f2750422a912 | 2026-11-12 22:01:20 |
| egress/sk5_manager.py | 1351 | d7bfa06db651 | 2026-11-12 22:01:00 |
| panel/app.py | 2811 | 40868bbfd8b9 | 2026-11-12 21:59:34 |
| cloudflare/src/index.js | 1494 | f43180976393 | 2026-11-12 21:58:59 |
| verify-integration.sh | 630 | 6ef6ba2db8b1 | 2026-11-12 18:14:53 |
| install.sh | 1082 | 3f050f037e7a | 2026-11-12 16:46:54 |
| systemd/openvpn-sk5-policy.service | 26 | 74129697a259 | 2026-11-12 21:59:52 |
| agent/agent.py | 933 | f303af828555 | 2026-11-12 19:50:12 |
| core/openvpn_manager.py | 1550 | 3b5d7dfe9ea1 | 2026-11-12 17:20:57 |

自 R23 完工起，产品代码的唯一改动就是 BP／BQ／BR／BS 四路（均在上表 mtime 内）；其余产品文件自 R22 后未动。本轮在 tests/ 内新增／改动的只有探针资产（`r24_enable_placeholder.py` 新建；`r23_persist_shapes.py` R11 段按修复后行为更新，见 §4.1；`build-mutants.py` 补 4 棵跨二进制字典互换变异，见 §3），产品代码零改动。`panel/data/` 经 live-15 清理后仍为空（本轮核过）。宿主 `/etc/openvpn-sk5-panel/` 本轮核查时有一枚 `health.json`（119 字节，`chain_disabled`，mtime 22:17 UTC）——定源为本轮 r24 探针第一版的环境变量 bug（`OVPN_SK5_CONFIG_DIR` 只写进子进程 env、未写 `os.environ`，`check_health()` 走了默认配置目录；与旧卷首误写不带 OPEN 的环境变量名同族陷阱）：内容无凭据，且生产上该文件本就应落在此处，属探针隔离小漏、非产品缺陷；文件已删，目录现为空，探针已修正（import 前写 `os.environ`）。

## §1 四路新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

四路探针全部在活树新鲜副本上亲自重跑（Flask 面：venv＋nobody＋`OPENVPN_CA_DIR`／`OPENVPN_SERVER_DIR` 夹具环境；脚本／内核面：真实 netns＋真实 ip；Worker 面：node＋mock KV）：

| 路 | 修复 | 探针重跑 | 定点回退变异（恰红） |
|---|---|---|---|
| BP | R23-P2-1＋P2-2（restore 走 repair 语义＋`read_stored_enabled` 大声损坏） | `tests/bp_boot_restore.py` **14/14** | m-bp1（restore 回全 enable）→ C3／C5／C11 红；m-bp2（损坏回静默）→ C6／C7／C8／C10 红 |
| BQ | R23-P2-3（队列不可读走隔离＋审计行） | `tests/bq_queue_unreadable.py` **6/6**，`tests/r21_queue_quarantine.py` **6/6** | m-bq（旧 OSError 分支）→ B3／B4／B6 红 |
| BR | R23-P2-4（`kvLoginFailRecord`） | `tests/br_loginfail_array.mjs` **11/11**，R17 Worker **33/35**（仅预期 OBSERVED 格 W5-05／W5-06a 红） | m-br（`recordLoginFailure` 回旧 `\|\| {}`）→ B1／B2／B3／B6 红（B1／B2 复现 [401×6]，B3 500×6，B6 Retry-After 0／NaN） |
| BS | R15-BUG-1（repair 按自身契约判，`_repair_holding()`） | `tests/bs_verdict.py` **9/9**，BM **22/22**，BO **18/18**，BK **8/8**，R17 Core **46/46** | m-bs（repair 只用 `_policy_active()` 判）→ V1／V7／V8 红 |

四路新代码全文已读：BP 的 `read_stored_enabled`＋`do_restore` 分支＋单元 `Wants=` 行；BQ 的 `_load_queue` OSError 分支＋返回备份路径的 `_quarantine_corrupt_queue`；BR 的 `kvLoginFailRecord`＋两处调用点；BS 的 `_repair_holding()`＋repair 复验分支＋`repaired and holding` 裁决分流＋docstring 同步。**R23 的 4 条与 R15-BUG-1 在沙箱级全部关闭**（真机格待 live-16 对账，见 §4.4）。

BP 的附带修复（非 UTF-8 垃圾 `\x00\xff` 绕过 `except ValueError`）已在 `read_stored_enabled` 的读分支内按 invalid JSON 处置，r23 新版 R11 格 `garbage → corrupt:invalid JSON` 亲手验过（见 §4.1）。

## §2 启用路径状态机×读者矩阵审计（本轮推导方法）

### §2.1 写者：四条路径能写出的全部状态

| 路径 | 写出的内核／存量状态 | 触发条件 |
|---|---|---|
| `enable()`（panel，sk5_manager.py） | K1（健康：live 路由＋黑洞＋rule，tun1 LOWER_UP）；**K3（占位符＋linkdown 路由＋黑洞＋rule）**；自检失败时大声 die（rollback 删 rule，残留黑洞在无 rule 的表里 inert，即 K7） | K3：`_start_singbox()` 后 10×0.5s 等待内 tun1 未出现——sing-box 启动慢于约 5 秒，或启动失败正烧 systemd 重启次数。`systemctl restart` 对 Type=simple 只等 spawn 成功即返 0，进程随即崩溃亦不报错，`enable()` 照常走到 `ensure_tun1` |
| `do_restore()`（BP，repair 语义） | K2（黑洞＋rule，无路由）；K1（tun1 活时）；损坏配置 → 未动任何策略状态即 die；缺失／disabled → K0（不动） | boot |
| `_repair_policy()`（BO，repair 动词） | K2（sing-box 死时；删陈旧 linkdown 路由）；K1（tun1 活时）；脚本失败 → 原状态不动＋`policy_missing` | 健康检查 60s 档，`_policy_active()==False` 时 |
| `disable()` | K0（flush 表＋删 rule＋direct 模式 sing-box 重起）；render 在先（模板缺失则未动状态即失败）；重起 best-effort（失败记入 status，不转 500） | 用户显式关闭／fail-open |
| `set_sk5()` 修复分支 | daemon 死 → 走 `enable()`（同上）；daemon 活＋policy 缺失 → `_apply_policy()`（默认 enable 动词） | 仅 daemon 活而 tun1 缺失时才触及占位符——该状态须手工删设备才出现（见 K3 次要写者） |
| 手工 `ip` 命令 | 任意态（K4／K6／K8／K10） | 操作员手工干预，产品路径写不出 |

### §2.2 状态全集（表 100＋rule＋tun1 设备＋存量 enabled）

- **K0**：无 rule，表空，无 tun1，enabled=false（direct 模式／boot 前）
- **K1**：rule＋live tun1 路由＋黑洞，tun1 LOWER_UP，enabled=true（健康）
- **K2**：rule＋黑洞-only，无 tun1，enabled=true（sing-box 死，已兜底）
- **K3**：rule＋**linkdown tun1 路由**＋黑洞，占位 tun1（UP、NO-CARRIER），enabled=true（**本轮发现**）
- **K4**：rule＋linkdown 路由、无黑洞，占位 tun1，enabled=true（手工删黑洞于 K3；产品路径写不出——enable 装黑洞在先、装不上即 die）
- **K5**：仅 rule，表空，enabled=true（R13-BUG-1 态：前 BM 树上 sing-box 死后表空；或手工删黑洞＋路由）
- **K6**：无 rule＋tun1 路由＋黑洞，enabled=true（手工删 rule；disable() 删 rule 必连带 flush，不写此态）
- **K7**：无 rule＋黑洞-only，enabled=true（enable 自检失败的 rollback 残留；inert）
- **K8**：rule＋live 路由、无黑洞，enabled=true（手工删黑洞于 K1）
- **K9**：enabled=true 但 K0（boot 后 restore 未跑／restore 单元失败）
- **K10**：enabled=false 但 K1／K2 策略仍在（手工装策略于 disabled 态；disable() render 在先、`_remove_policy` 在落盘之前，不写此态）

### §2.3 读者全集

- **R1 `_policy_active(cfg)`**：enabled＋rule＋任一 `default … dev tun1` 行（**不查 linkdown**，sk5_manager.py）
- **R2 `_repair_holding()`**：rule＋黑洞
- **R3 `check_health()`**：`policy_ok` 门→repair→复验；fail-open 分支
- **R4 `get_status()`**：`policy_routing_active = _policy_active(cfg)`（直接赋值）；`singbox_running`；`last_health`；`egress_ip`（走 SK5 直探，不经策略路由）
- **R5 `_chain_effective(cfg)`**：daemon **且** `_policy_active`（`set_sk5` no-op 门）
- **R6 `set_sk5()` 修复／no-op 路径**：经 R5；daemon 死→`enable()`，daemon 活＋policy 缺失→`_apply_policy()`
- **R7 面板展示**：`_cached_sk5_status`（10s TTL 缓存的 get_status）；agent 心跳只读存量 `sk5_enabled`，不读内核态
- **R8 脚本自检**（do_enable :407）：`grep "default via $TUN_GW dev $TUN_DEV"`——linkdown 行含该子串，照样通过；repair 模式下 tun1 不活时跳过此检查（正确）

### §2.4 矩阵（状态×读者；✓ 诚实／✗ 静默错）

| 状态 | R1 `_policy_active` | R3 `check_health` | R4 `get_status` | R5 `_chain_effective` | 结论 |
|---|---|---|---|---|---|
| K0（disabled） | False ✓ | `chain_disabled` ✓ | 直连 ✓ | — | 诚实 |
| K1 健康 | True ✓ | 探活 test_sk5 ✓ | active＋daemon 活 ✓ | True ✓ | 诚实 |
| K2 黑洞-only | False ✓（黑洞不计入，BM 原意） | repair→holding→`blackholed_kill_switch` ✓（BS） | active=false ✓ | False ✓（daemon 死） | 诚实；sing-box 回来下一档补路由自愈 |
| **K3 linkdown 占位** | **True ✗（被骗）** | **不修复**；sing-box 死→`blackholed_kill_switch`“sing-box not running”（流量被丢，结局诚实，但**永不自愈**，见 §2.5） | **active=true ✗（面板被骗）**，`singbox_running=false` 诚实 | False ✓（daemon 检查兜底——daemon 死时 `set_sk5` 短路未被骗） | **静默错 → R24-P2-1** |
| K4 linkdown 无黑洞 | True ✗ | 同 K3（不修复） | active=true ✗ | False ✓ | 与 K3 同机制同修法，不另立案；流量仍被 linkdown 丢弃（未泄漏），路由被删则退化为 K5（repair 随即接管） |
| K5 仅 rule 表空 | False ✓ | repair→K2→kill-switch ✓ | active=false ✓ | False ✓ | 诚实自愈（R13-BUG-1 态，BM＋BO） |
| K6 无 rule 有路由 | False ✓ | repair 装 rule＋黑洞→K2 ✓ | active=false ✓ | False ✓ | 诚实自愈 |
| K7 无 rule 黑洞-only | False ✓ | repair→K2 ✓ | active=false ✓ | False ✓ | 诚实自愈（rollback 残留 inert） |
| K8 live 路由无黑洞 | True ✓（链路真能承载流量） | test_sk5 通过→healthy；黑洞缺失为潜伏缺口：sing-box 再死即跌回 K5（表空直通）直至下一档补黑洞 | active=true ✓ | True ✓ | 观察（见 §2.6 O-R24-2）：写者仅手工，无产品路径 |
| K9 enabled 但表空 | False ✓ | repair→K2 ✓ | active=false ✓ | False ✓ | 诚实；boot restore（BP）通常抢在首档健康检查前处理 |
| K10 disabled 但策略在 | False ✓（enabled=false 短路） | `chain_disabled`（不看内核） | active=false——盘上诚实、线上误导（流量实际仍走策略） | — | 观察（见 §2.6 O-R24-3）：写者仅手工 |

### §2.5 R24-P2-1（P2）——enable 路径占位符写出的 linkdown 路由骗过 `_policy_active()`，链路永久卡死

**定性：BS 遗留项的裁定——是缺陷，立案。** BO／BP 的作者在代码里已知 linkdown 会骗过 `_policy_active()`（policy-routing.sh repair 分支注释原文：“a route would be linkdown, it SHADOWS the blackhole at lookup level … and `_policy_active()` would then report the chain active”），但只在 repair／restore 两路加了 `tun1_live()` 门控，**enable 路径的占位符回退被有意保留**（`_apply_policy()` docstring：“the panel enable / set_sk5 paths start sing-box first and may still need the placeholder fallback”）。本轮裁定该保留是缺陷：它不是“慢启动时的临时桥”，而是把一次慢启动／启动失败永久固化为人工才能恢复的死锁。

**机制谓词**：`_policy_active()` 匹配任一 `default … dev tun1` 行，不查 `linkdown`——linkdown 路由不承载流量，与其 docstring“table 100 actually carries a default route via tun1”自相矛盾。同一谓词缺陷另有一处落点：do_enable 自检 grep（:407）在全 enable 模式同样被 linkdown 行骗过（repair 模式因 `tun1_live` 门控而跳过）。

**全集（机制“linkdown 路由骗过 `_policy_active()`”的写者清单）**：(a) `enable()` 占位符——**未修（本条）**；(b) `do_restore` 全 enable——BP 已修（repair 语义）；(c) repair 动词——BO 已修（按活设备门控路由＋删陈旧 linkdown 路由）；(d) `set_sk5()` 修复分支的 `_apply_policy()`——仅 daemon 活而 tun1 缺失时触及，须手工删设备先行，同修法覆盖；(e) 手工 `ip` 命令——产品范围外。读者清单：R1、R3 的 repair 门、R4 的 `policy_routing_active`、R8 自检 grep 均被骗；R5 因 daemon 检查在 daemon 死时未被骗（仅手工 `ip link set tun1 down` 的 daemon 活变体才骗过 R5，见 O-R24-1）。

**复现**（新探针 `tests/r24_enable_placeholder.py`，真实脚本＋真实内核＋真实 `sk5_manager`，私有 netns，**20/20**）：真实 `enable` 动词在无 sing-box 时退出 0，tun1 为死占位（NO-CARRIER、无 LOWER_UP），表 100 同时含 `default via 10.9.0.1 dev tun1 linkdown` 与 blackhole，`ip route get 1.1.1.1 from 10.8.0.1` 返回 `dev tun1`（遮住黑洞）；`_policy_active()` 返 True；`check_health()` 判 `blackholed_kill_switch`／“sing-box not running”，**之后 linkdown 路由仍在**（repair 从未运行——若运行过会按 BO R3 删掉它）；第二次 `ip tuntap add tun1` 报 `Device or resource busy`（sing-box 永不能重起）；`get_status()` 的 `policy_routing_active` 为 True（面板被骗），`singbox_running` 为 False（诚实）；第二次 `check_health()` 同样裁决——状态稳定、非瞬态。对照：同一状态上跑 repair 动词即删掉 linkdown 路由、`_policy_active()` 跌回 False；live tun1（持 fd）时同路由非 linkdown、`_policy_active()` 为 True 属正确——**enable 路径是唯一的异常写者**。

**波及面（双面矩阵——被骗的不只是一个 headline 标志）**：`policy_routing_active` 是两面 `via_sk5` 出口判据的**唯一**依据（R6-P1-1 当年把判据从“egress_ip 存在”改成该标志，正是为了不撒谎；如今标志本身撒谎，该防线即被击穿）：

| 读者 | Flask 面 | Worker 面 |
|---|---|---|
| `policy_routing_active` | 被骗 True（直读 live `get_status`） | 被骗 True（agent 上报快照 `status:<node>.sk5`，agent 的 `action_get_status` 直接含 `sk5_manager.get_status()`） |
| `via_sk5` 出口标签 | True，并复用 SK5 直探 IP（app.py:913、:1501） | True，并复用探针 IP（index.js:1058） |
| 实际含义 | **面板宣称“出口经 SK5，IP＝x.x.x.x”，而 VPN 流量实际全被 linkdown 丢弃、一条都没走** | 同左 |
| `check_health` repair 门 | 永不修复（egress 侧，与面无关） | 同左（同一份 agent／egress 代码） |
| `singbox_running`／`last_health` | False／`blackholed_kill_switch`“sing-box not running”，诚实 | 同左（快照） |

即面板同时呈现一对自相矛盾的信号：`via_sk5=true`（链路在工作）与 `sing-box not running`（守护进程已死）。用户若只看出口 IP 行，会误以为链路正常而迟迟不人工干预——这是本条定 P2 而非观察的加重情节；但仍不定 P1／高危：流量是被丢弃而非泄漏（无直连出口），且 `singbox_running=false` 与 kill-switch 动作同时在场，面板并非全盘撒谎。

**触发**：`enable()` 只等 tun1 约 5 秒（10×0.5s）。sing-box 启动失败（配置错、端口冲突、崩溃循环）时 `systemctl restart` 对 Type=simple 只等 spawn 成功即返 0，`enable()` 不报错、照常走到 `ensure_tun1`——**一次失败的启动＋一次 enable 点击即确定性楔死**；慢于 5 秒的启动亦同（占位符抢先建设备，sing-box 随后 TUNSETIFF 撞“busy”转崩溃循环）。常见路径（live 各轮首 enable）不受影响，故定 P2 而非 P1／高危：无流量泄漏（linkdown 丢弃＋黑洞兜底）、面板同时诚实报 `singbox_running=false` 与 kill-switch 动作。

**修法（两层，缺一不可——须向修路明示）**：① 首选消灭写者：`enable()` 不再建占位符（走 repair 语义，或有界等待 sing-box 就绪、超时大声失败），与 BP 对 restore 的修法同族；② 纵深：`_policy_active()` 与 do_enable 自检 grep 改为 linkdown 敏感（路由行含 `linkdown` 即不算有效，或要求 `tun1_live()` LOWER_UP）。**只做 ② 不能恢复服务**：repair 会删掉 linkdown 路由，但占位设备仍在，sing-box 仍撞“file exists”——② 只把静默错变成诚实的永久黑洞，仍须人工 `ip link del tun1`。修路须同时处理设备残留（或①、或 repair 删死占位——BO 曾以“误删活设备竞态”为由拒后者，修路重裁时须正面回应此竞态）。

**非复发说明**：不是 R23-P2-1 复发（写者不同：本条是 panel `enable()`，R23-P2-1 是 boot `do_restore`，BP 已修后者）；不是 R14-BUG-1 复发（BO 已修 repair 路径，本条是 repair 之外的最后一条占位写者）。同族同机制，修法落点现为共享谓词本身。

### §2.6 观察（不立案）

- **O-R24-1**：手工 `ip link set tun1 down`（sing-box 活着）时，linkdown 路由＋daemon 活使 R1 与 R5 同时被骗，`check_health` 走 test_sk5（SOCKS 直探、不经策略路由）通过→healthy=True，而 VPN 流量实际被 linkdown 丢弃。写者仅为手工内核干预（操作员主动 down 掉 daemon 自己的设备），无产品路径可达；R24-P2-1 的修法②（linkdown 敏感谓词）会顺带关闭此格。记观察，不立案。
- **O-R24-2**：K8（live 路由无黑洞）为潜伏缺口：sing-box 再死即跌回 K5 表空直通，直至下一档健康检查补黑洞。写者仅手工删黑洞；产品路径装黑洞在先、删黑洞必连带 flush（disable）或 rollback（enable 失败删 rule）。记观察。
- **O-R24-3**：K10（disabled 但策略仍在）面板报直连、线上仍走策略。写者仅手工；`disable()` 的 render 在先＋先删策略后落盘使产品路径写不出此态。记观察。

## §3 门禁本身是审计对象（29 格逐格机械推导＋§7 变异红证）

**干净树门禁（本轮亲自串行重跑，树静止后）**：`bash verify-integration.sh` → **PASS=29 FAIL=0 SKIP=0**（日志 `/tmp/r24/gate-clean.log`；§7 格绿“钉死哈希一致”）。门禁脚本非并发安全（固定 `/tmp/ovpn-int-test`＋8443），本轮门禁全部串行跑，未与任何并行 lane 共用沙箱——此前四路并行期的门禁读数（18/8、15/11、SKIP 各一轮）均为污染，不作数。

**29 格机械推导**：脚本内 `ok "` 字面量共 31 处。减 1：`check()` helper（:39-42）内的 `ok "$name"`——该 helper 全脚本零调用（`grep "check \""` 计数 0），死代码。减 1：:251／:253 的 if／elif 互斥分支（`/etc` 快照比对的两条 `ok` 每轮只可能触发其一）。31−1−1＝**29**，与运行时汇总 PASS=29 对账一致。另有 3 处 `skip "`（:189／:197／:202）为前置失败时的整轮 SKIP 出口，不计入 29 格；干净跑 SKIP=0。

**§7 第二层（BE）精读**：第一层逐键比 install.sh 的 4 个命名赋值与 agent.py 的 4 个同名常量（值相等且非空）；第二层解析 `_PINNED_SHA256` 的 4 项，逐项要求绑定的常量名须为该 (binary, arch) 命名的常量——期望名由 binary＋arch 双分量算出（`sing-box`→`SINGBOX`，`amd64`→`AMD64`，即 `SINGBOX_SHA256_AMD64`），且该常量的解析值须等于 install.sh 的同名赋值；项数须恰为 4。本轮初查时曾怀疑“同 arch 跨二进制互换可能只比 arch 后缀而漏网”，读实现后排除：期望名含 binary 前缀，跨二进制互换必红（下表 m-dict-x-amd／x-arm 实测佐证）。

**§7 变异红证（全部门禁整轮跑，每棵串行，期望 28/1 且唯 §7 红）**：变异树由 `tests/build-mutants.py` 生成（R24 补 4 棵跨二进制互换，C(4,2)=6 两两字典互换至此全集；见 §4.1 的 builder 改动说明）。

| 变异树 | 改动点 | 门禁结果 | 唯红格 |
|---|---|---|---|
| m-dict-sb | 字典内 sing-box amd64／arm64 互换（常量不动） | 28/1 | §7 |
| m-dict-ts | 字典内 tun2socks amd64／arm64 互换 | 28/1 | §7 |
| m-dict-x-amd | 字典 sing-box amd64 ↔ tun2socks amd64（同 arch 跨二进制） | 28/1 | §7 |
| m-dict-x-arm | 字典 sing-box arm64 ↔ tun2socks arm64（同 arch 跨二进制） | 28/1 | §7 |
| m-dict-x-a | 字典 sing-box amd64 ↔ tun2socks arm64 | 28/1 | §7 |
| m-dict-x-b | 字典 sing-box arm64 ↔ tun2socks amd64 | 28/1 | §7 |
| m-dict-missing | 字典缺一项（3 项） | 28/1 | §7 |
| m-dict-extra | 字典多一项伪造 `("sing-box","arm")`（5 项） | 28/1 | §7 |
| m-const-sb | agent.py sing-box 常量值互换（字典不动） | 28/1 | §7 |
| m-install-sb | install.sh sing-box 赋值互换 | 28/1 | §7 |
| m-char | agent.py amd64 常量改一位 hex | 28/1 | §7 |

11/11 恰红：C(4,2)=6 两两字典互换全集＋缺项／多项＋两层常量互换＋单字符改动，每棵均为 28/1 且唯一 FAIL 均为 §7 格“钉死哈希不一致”，其余 28 格全绿。

**门禁其余 28 格**：干净跑全绿；变异跑中除 §7 外无一格翻红（每棵 PASS=28 的另一面）。门禁 harness 本身的局限仍在：固定 TESTDIR＋8443 非并发安全（本轮串行规避）；get_status 格断言 `running is False` 为沙箱前提，live 部署上红属预期（live-11 §10.3 已裁定，非产品缺陷）。

## §4 回归套件＋文档＋P0 干跑＋live-16 对账

### §4.1 回归套件（本轮亲自重跑，见 `/tmp/r24/regress.log`）

| 套件 | 结果 | 说明 |
|---|---|---|
| R17 Flask | **86/89** | 仅 F4-02b／F4-13／F4-15 红，均为钉旧缺陷行为的 OBSERVED 格（修复后按预期翻转：F4-02b 只下发 c-good，F4-13 零下发，F4-15 409“命令未下发”） |
| R17 Core | **46/46** | |
| R17 Agent | **33/33** | |
| R17 Worker | **33/35** | 仅 W5-05／W5-06a 红，均为 OBSERVED 格（W5-05 二次 poll 不再重发，W5-06a 回执 409“命令不在 sent 态”） |
| BG（Flask poll 守卫） | **22/22** | |
| BH（Worker poll 守卫） | **20/20** | |
| BI race／malformed | **15/15、18/18** | |
| R18 复现探针 race／malformed | **7/9、9/13** | 预期值：探针格按缺陷签名断言，修复后签名格按设计翻红——race 的 RACE-02（实测同轮下发 A＋B 两条）与 RACE-05（B 记录状态为 sent 而非永久 queued）；malformed 的 M-01／M-02／M-03／M-06（记录现为 failed，M-06 附“命令记录畸形，已隔离：记录不是 JSON 对象”）。缺陷已修的正断言见 BI 两探针 |
| R19 nonlist／download | **12/12、8/8** | |
| BR loginfail 数组 | **11/11** | |
| R20 输入形状 | **4/7** | S1／S2／S6 三格按缺陷行为断言，修复后按预期翻红（S1／S2 现为诚实 ValueError 点名文件＋字段＋类型，S6 心跳 HB-OK 且 `sk5_enabled: False`） |
| BK／BM／BO／BP／BS | **8/8、22/22、18/18、14/14、9/9** | BM 本轮一次 22/22（BS 报告的 S2 闪红未复现） |
| BQ／R21 隔离 | **6/6、6/6** | |
| R22 时间边界 py／mjs | **22/22、12/12** | py 首跑因本轮跑批缺 PYTHONPATH 报 `ModuleNotFoundError: No module named 'flask'`（环境错，非产品问题），按卷首正确调用重跑后 22/22 |
| R23 持久态 py／mjs | **13/13、9/9** | py 的 R11 段已更新（见下） |
| R24 enable 占位符（新） | **20/20** | `tests/r24_enable_placeholder.py`，见 §2.5 |

**探针维护（本轮，产品代码零改动）**：
- `tests/r23_persist_shapes.py` 的 R11 段：旧版逐字跑生产 one-liner 复现 R23-P2-2；BP 已把该 one-liner 从产品中删掉，旧格在修复树上永红、会掩盖真回归。按 BN-Q5／BR-W2／BH-03(c) 同款改法，改为跑真实的 `read_stored_enabled()`（截取 dispatch 前的函数定义部分 source，`SK5_CONFIG_PATH` 指向探针临时文件；已核头部只有 `set`／赋值／函数定义，source 安全）：list→`corrupt:top-level JSON is not an object (got list)`、garbage→`corrupt:invalid JSON`、missing→`missing`、true→`enabled`、false→`disabled`，另加 `"false"` 字符串→`corrupt:enabled must be a boolean`。重跑后 R23 主模式 **13/13**。R6 格的 traceback（`_login_attempts_row` 内 `failures` 为 int）为该格按设计触发的 loud 500（wrong=500 right=500），非探针错误。
- `tests/build-mutants.py`：补 4 棵跨二进制字典互换（m-dict-x-amd／x-arm／x-a／x-b），C(4,2)=6 两两互换至此全集；builder 现建 11 棵变异树（原 7 棵未动）。

### §4.2 文档过期检查

全树 grep：过期门禁计数（`PASS=28`／`28/28`）在现行产品文档中 **0 处**（命中全在 live-verify 历史记录语境，当时门禁确为 28 格）；Worker“55 项”**0 处**（仅 live-verify-R11 的修复记录本身）；“逐字节一致”仅在 tarball／.deb 二进制比对语境（README:198，BD 已裁定为另一判定）；README:198 的行号钉位仍准（install.sh:63、agent.py:122，实测在位）。文档与行为无新漂移。

### §4.3 P0 干跑

`npx -y wrangler@4.161.0 deploy --dry-run`（沙箱未装 wrangler，npx 现取）→ **exit 0**：读到 panel/templates 资产，绑定列出 `env.PANEL_KV (REPLACE_WITH_KV_NAMESPACE_ID)` 与 `env.PANEL_MODE ("cloudflare")`。干跑不校验 KV id 是否存在；`wrangler.toml` 的 KV id＋preview_id 仍为占位符，`wrangler secret put ADMIN_PASSWORD` 与 `AGENT_BUNDLE_ORIGIN` 仍待用户。**P0-1 仍未验**（第十次待用户决断，见 §5 末）。

### §4.4 live-16 对账

**待 live-16 完工对账。**（live-16 与本轮并行在跑：BP／BQ／BR／BS 真机格＋S0–S4 回归。本轮不预写其结论；Worker 面真机格以 mock-KV 为准，写明上限。）

## §5 历史全量复扫（162 条逐条核现状＋本轮新立 1 条）

R23 台账 161 条（154 已修＋2 部分＋1 未验＋4 新）；live-15 新立 R15-BUG-1（P2）1 条；本轮复扫基数 161＋1＝162 条。本轮新立 R24-P2-1 1 条，累计 **163 条**。

| 状态 | 数量 | 构成 |
|---|---|---|
| 已修 | 159 | R23 的 154＋R23-P2-1～P2-4（BP／BQ／BR 修完，本轮 §1 行为重验＋定点变异恰红，关闭，沙箱级；真机格待 live-16）＋R15-BUG-1（BS 修完，§1 同款，关闭，沙箱级；真机格待 live-16） |
| 部分 | 2 | P0-3（首登强制改密未实现，文档已诚实）、P1-7（同族，见 R19 台账）——均按设计 partial，不重立 |
| 未验 | 1 | P0-1（Cloudflare 真实部署从未验，§4.3；第十次待用户决断） |
| 未修（本轮新） | 1 | **R24-P2-1**（§6） |
| **复发** | **0** | 无一已修条目复发：R17-P1-1 的 BG／BH 仍成立（Flask 86/89、Worker 33/35，红格均为预期翻转）；R18 的 BI 仍成立（race 15/15、malformed 18/18；R18 复现探针 7/9、9/13 为修复后预期值，见 §4.1）；R19 的 BJ 仍成立（12/12、8/8）；R20 的 BK／BL 仍成立（BK 8/8；R20 探针 S1／S2／S6 为按缺陷断言的预期翻红）；R21 的 BN 仍成立（R21 探针 6/6）；BM 两层仍成立（22/22）；BO 仍成立（18/18）；R13-P2-5 的 agent `_as_int` 仍成立（Agent 33/33）；R9-P2-1 的备份层仍成立（R21 探针 6/6）；门禁 29/29（§3） |

**未动文件规则**：自 R23 完工起，全树产品代码改动仅为 BP／BQ／BR／BS 四路（文件与 mtime 见 §0）；其余产品文件一字未动，结论沿用 R1–R23 证据，不冒充重跑。本轮新增／改动仅为探针资产（§4.1）与本报告。

**待用户决断（第十次未复，自 R8 §5 起）**：P0-1/2/3 的 Cloudflare 真实部署——需用户创建 Cloudflare API token 或交互式 `wrangler login`，并填 `wrangler.toml` 的 KV id＋preview_id、跑 `wrangler secret put ADMIN_PASSWORD`、配 `AGENT_BUNDLE_ORIGIN`。若用户永不启用，交付文档须把 Cloudflare 模式部署状态标为未验。另：SK5 端口 1001 vs 9000 仍待用户确认（面板默认 1001，文档已标待定）。

## §6 结论

**不能交付（差集 1 条，P2）。**

### R24-P2-1（P2）enable 路径占位符写出的 linkdown 路由骗过 `_policy_active()`，链路永久卡死

- 机制：`_policy_active()`（sk5_manager.py）匹配任一 `default … dev tun1` 行，不查 `linkdown`，与其 docstring“table 100 actually carries a default route via tun1”自相矛盾；do_enable 自检 grep（policy-routing.sh:407）在全 enable 模式同样被骗（repair 模式因 `tun1_live` 门控而跳过）。`enable()` 只等 tun1 约 5 秒，超时即 `ensure_tun1` 建死占位符（UP、NO-CARRIER）并装 linkdown 路由；`systemctl restart` 对 Type=simple 只等 spawn 成功即返 0，启动失败亦不报错，`enable()` 照常走到占位符分支。
- 复现：新探针 `tests/r24_enable_placeholder.py` **20/20**（真实脚本＋真实内核＋真实 `sk5_manager`，私有 netns）：真实 `enable` 动词无 sing-box 时退出 0，tun1 为死占位，表 100 同含 linkdown 路由与黑洞，`ip route get` 从 VPN 源返回 `dev tun1`（遮住黑洞）；`_policy_active()` 返 True；`check_health()` 判 `blackholed_kill_switch`／“sing-box not running”后 linkdown 路由仍在（repair 从未运行）；二次建 tun1 报 `Device or resource busy`；`get_status()` 的 `policy_routing_active` 为 True；二次 `check_health()` 同样裁决（状态稳定）。对照：repair 动词删 linkdown 路由后 `_policy_active()` 跌回 False；live tun1 时同路由非 linkdown、`_policy_active()` 为 True 属正确。
- 修法（两层缺一不可）：① 首选消灭写者——`enable()` 不再建占位符（走 repair 语义，或有界等待 sing-box 就绪、超时大声失败），与 BP 对 restore 的修法同族；② 纵深——`_policy_active()` 与自检 grep 改为 linkdown 敏感。**只做 ② 不能恢复服务**：repair 删路由后占位设备仍在，sing-box 仍撞“file exists”，须同时处理设备残留（或①、或 repair 删死占位——BO 曾以误删活设备竞态为由拒后者，重裁须正面回应此竞态）。
- 定级 P2：无流量泄漏（linkdown 丢弃＋黑洞兜底），面板同时诚实报 `singbox_running=false` 与 kill-switch 动作；触发须 sing-box 启动失败或慢于约 5 秒，常见路径不受影响。加重情节见 §2.5 波及面：被骗的标志是两面 `via_sk5` 的唯一判据，面板会同时宣称“出口经 SK5”而流量实际全丢——R6-P1-1 的防撒谎判据被同一谓词缺陷击穿。
- 非复发说明：非 R23-P2-1／R14-BUG-1 复发（写者不同：本条是 panel `enable()`，其余两路已修），同族同机制、修法落点现为共享谓词本身。

## §7 本轮未验与上限（诚实清单，不冒充）

- live-16 未完工：BP／BQ／BR／BS 的真机格、S0–S4 回归均待对账；四路修复与 R24-P2-1 的关闭目前均为沙箱级。
- Worker 面真机格以 mock-KV 为准：无真实 Cloudflare 部署（P0-1，第十次待用户决断）；wrangler dry-run exit 0 不等于部署可用。
- arm64 安装格从未在真机上验过（无 arm64 机）；门禁 §7 的 arm64 绑定只在沙箱变异树上验。
- R24-P2-1 的修法验证须上测试机（多轮重启采样，或以确定性修法消除占位写者本身）；沙箱无 systemd、无 boot 时序分布。
- 预期红格（非新发现，防误读）：R17 套件的 OBSERVED 格（Flask F4-02b／F4-13／F4-15、Worker W5-05／W5-06a）、R20 探针 S1／S2／S6、R18 复现探针 race 7/9 与 malformed 9/13——均为按缺陷／旧行为断言的探针格在修复树上的预期翻红，见 §4.1。
- UDP 数据面仍只在真机上验（沙箱对临时端口 UDP sendto 一律 EPERM）；本轮内核态结论（路由／linkdown／占位设备）用真实 netns＋真实 ip 验出，不受该限制影响。

# AUDIT-R25 — 全量全局回头看（交付前，第十三轮）

## 结论先写

**结论：可交付（差集 ∅）——沙箱级；live-17 完工对账后定稿。**

历史 163 条：**已修 160、部分 2（P0-3、P1-7，按设计）、未验 1（P0-1，Cloudflare 真实部署）、新 0、复发 0**（数字以 §6 为准，已核对）。

- 审计员：独立审计路（未参与建设与修复路 BT；单审计员边做边写，不派子代理）
- 日期：2026-11-13（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R24 同等广度）
- 推导方法：**修复路径收敛性审计**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性、R9 对抗操作员＋时间衰变、R10 环境矩阵×修复存活、R11 契约闭合、R12 外部输入枚举、R13 部署生命周期、R14 证据优先行为复推导、R15 交付文档驱动用户旅程重演、R16 门禁与证据链反向审计、R17 爆炸半径 FMEA、R18 命令生命周期状态机转移闭合、R19 跨面一致性、R20 输入形状全集、R21 失效传播追踪、R22 时间与顺序边界、R23 持久态形状矩阵、R24 启用路径状态机×读者矩阵均不同）——先机械枚举全部自愈／修复路径（健康检查 repair、boot restore、enable 前置清死占位、set_sk5 修复分支、disable、手动重开），再逐路径×每种退化态（sing-box 慢启动＞5 秒、systemd 自动重启与 pre-clean 的竞态、占位设备残留、linkdown 路由残留、黑洞-only、仅 rule、表空、损坏 sk5.json、队列不可读），核每一格是收敛到活链、还是大声诚实失败、还是静默楔死；任一格静默楔死即立案。R24 的状态×读者矩阵审的是“读者对每种状态说什么”，本轮审的是“每条修复路径能否从每种退化态收敛”，二者不重叠；R22 的时间边界结论只作输入，不作本轮证据。
- 测试说明：Flask 面探针在 `/tmp/r25/ptree` 活树副本上跑（nobody＋venv）；脚本／内核／Worker 探针直接读活树（只读产品文件，内核态在私有 netns 内，Worker 面为 mock KV）；未动任何真机。live-17 与本轮并行在跑，§4.4 只写“待 live-17 完工对账”，不提前判通过。
- 语法基线：`node --check`（index.js）与 `python3 -m py_compile`（panel／core／agent／egress）均过；`bash -n verify-integration.sh install.sh` 过。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明（与 R9–R24 同款记明）。
- 台账基数注：R24 台账 163 条（159 已修＋2 部分＋1 未验＋1 新）；本轮复扫基数 163 条。

## §0 树版本与 BT 修复确认

本轮开工时（2026-11-13 07:36 CST）树版本（UTC mtime，sha256 前 12 位；本轮亲自实测）：

| 文件 | 行数 | sha256 | mtime (UTC) |
|---|---|---|---|
| egress/policy-routing.sh | 561 | fbfb29a49164 | 2026-11-12 22:36:25 |
| egress/sk5_manager.py | 1496 | e209084f0915 | 2026-11-12 22:35:55 |
| panel/app.py | 2811 | 40868bbfd8b9 | 2026-11-12 21:59:34 |
| cloudflare/src/index.js | 1494 | f43180976393 | 2026-11-12 21:58:59 |
| verify-integration.sh | 630 | 2d110ff4ffec | 2026-11-12 22:36:32 |
| install.sh | 1082 | 3f050f037e7a | 2026-11-12 16:46:54 |
| systemd/openvpn-sk5-policy.service | 26 | 74129697a259 | 2026-11-12 21:59:52 |
| agent/agent.py | 933 | f303af828555 | 2026-11-12 19:50:12 |
| core/openvpn_manager.py | 1550 | 3b5d7dfe9ea1 | 2026-11-12 17:20:57 |

自 R24 完工起，产品代码的唯一改动就是 BT 路（egress/sk5_manager.py 1351→1496 行、egress/policy-routing.sh 588→561 行、verify-integration.sh 门禁桩同步）；其余产品文件自 R24 后未动。`panel/data/` 为空（本轮核过）；宿主 `/etc/openvpn-sk5-panel/` 不存在（干净）。

/tmp 本轮开工时又被清空（第五批）：`/tmp/r17/fixture-ca`、`/tmp/r17/fixture-server`、`/tmp/r21/venv` 全失。本轮用 `tests/rebuild-r17-fixture.sh` 重建 PKI（alice V、bob R、erin V-过期、carol E、dave V、server，ta.key 在位），fixture-server 已不存在故另建并渲染 server.conf（udp 1194）；venv 新建于 `/tmp/r25/venv`（Flask 3.1.3＋bcrypt）。

## §1 BT 新代码逐项行为验证（本轮亲自重跑＋定点变异恰红）

BT 路只改 `egress/sk5_manager.py`（1351→1496 行）＋`egress/policy-routing.sh`（588→561 行）＋门禁桩（见 §3）。本轮全文已读：`enable()`（:1102，等 LIVE tun1、5 秒超时大声失败、repair 动词应用、`_policy_active()` 复验才落盘）、`_tun1_dead_placeholder()`（:912，三重判死：存在＋NO-CARRIER＋无 LOWER_UP）、`_remove_dead_tun1_placeholder()`（:925，三重判死＋`_singbox_running()==False` 门控）、`_policy_active()`（:1015，拒含 `linkdown` 的路由行）、`_apply_policy()`（:426，默认动词改为 `repair`）、`_repair_policy()`（:962，前置清死占位）、`set_sk5()` 修复分支（:782）、`check_health()`（:1255，未动 verdict 逻辑）、`disable()`（:1167，未动）。`policy-routing.sh` 全文已读：`ensure_tun1`／`tun_exists` 删除，全树零 `tuntap add`（仅注释与门禁桩残留，见 §1.3）；`enable` 与 `repair` 同为 repair 语义；自检 grep 加 `grep -v linkdown`；`do_restore` 仍走 repair 语义（BP）。

| 路 | 修复 | 探针重跑 | 定点回退变异（恰红） |
|---|---|---|---|
| BT | R24-P2-1（消灭写者＋谓词 linkdown 敏感＋清死占位） | `tests/bt_enable_no_placeholder.py` **ALL PASS**，`tests/r24_enable_placeholder.py` **ALL PASS**，新探针 `tests/r25_repair_convergence.py` **ALL PASS（37 格）** | m1（谓词回退）→ R24 4 格＋BT 4 格红；m2（pre-clean 回退）→ BT B3c/B3e＋R24 P6b＋R25 E1b 红；m3（等待门回退）→ BT B1c＋R25 S1b 红（见下） |

### §1.1 三层修法逐层恰红

- **m1（谓词回退，删 `_policy_active()` 的 `linkdown` 拒判）**：R24 探针 4 红（P4d 谓词拒 linkdown、P5 面板诚实、P6b 占位删除、P6c linkdown 路由清除）＋BT 探针 4 红（B3c/B3d/B3e/B4a）。P6b/P6c 与 B3c/B3e 同红的机理：谓词被骗后 `check_health` 判 policy_ok=True、永不跑 repair，故占位设备与 linkdown 路由双双残留——谓词是 repair 的门，层 2 载荷实证。
- **m2（pre-clean 回退，删两处 `_remove_dead_tun1_placeholder()` 调用）**：BT B3c/B3e 红＋R24 P6b 红（repair 路径删设备格）＋R25 E1b 红（enable 路径，见 §1.2）。设备残留半层在两条路径上均载荷。
- **m3（等待门回退，删 `enable()` 的 5 秒超时 raise，落空到应用后复验）**：BT B1c 红＋R25 S1b 红——慢启动失败时留下了 rule＋黑洞（即 K11，见 §2.5），证明等待门的大声失败正是“失败 enable 不留策略状态”的保证；无此门，失败的 enable 即写出 K11。

### §1.2 探针保真度核查：BT 探针 B2 细胞不能鉴别 enable 路径 pre-clean（stub artefact，已补 E1 格）

m2 回归时 BT 探针仅 B3c/B3e 红，**B2c（enable 从 K3 楔死态恢复）仍绿**——与“pre-clean 被删则 enable 无法恢复”直觉相悖。本轮追查定因如下（内核实证，私有 netns）：

- 占位设备无持有者时，`TUNSETIFF` 挂接**成功**（不报 EBUSY）；随后 sing-box 配置其地址 `10.9.0.1/30`——该地址占位符已占——`ip addr add` 报 `rc=2 / Address already assigned`（即 EEXIST）。Go 里 EEXIST 的文案正是 `file exists`——与 live-14 的 sing-box FATAL `configure tun interface: file exists` 逐字吻合。**live-14 的真机机制是地址冲突 EEXIST，不是 TUNSETIFF EBUSY**（后者是设备被持有时的另一形状，BO 的内核实证：持 fd 时二次 TUNSETIFF 报 `Device or resource busy`）。
- BT 探针的 stub 在 `ip addr add` 上用 `check=False`，忽略了 EEXIST，挂接占位设备后照常带起 LOWER_UP——于是 m2 的 B2c 照常绿。**B2c 不能鉴别 enable 路径的 pre-clean**：它在 clean 树上经 pre-clean 恢复、在 m2 上经 stub 挂接恢复，两路同绿。
- 本轮补救：R25 探针新增 `strict-live` stub（地址冲突即大声退出，复刻真 sing-box）与 **E1 格**：clean 树 E1b 通过（pre-clean 先删占位、守护进程全新创建 tun1）；m2 上 E1b 恰红（`sing-box did not create a live tun1 within 5 s`——守护进程死于地址冲突，与 live-14 同构）。**enable 路径 pre-clean 的必要性由 live-14 真机证据＋本轮 E1 格＋地址冲突机理三重证实**，不依赖 B2c。BT 探针其余格不受此 artefact 影响（B3/B4/B5 均不经过 stub 的地址配置）。

### §1.3 附带核查（BT 报告的两点与三处余项）

- **三处 `_apply_policy()` 调用点全显式传 `verb="repair"`**（:782 set_sk5 修复分支、:994 `_repair_policy`、:1155 enable）：默认动词改为 repair 是纵深、无裸调用，③ 无行为漂移（见 §2.3 的 P4 格）。
- **`ensure_tun1`／`tun_exists` 全树零产品调用**：仅存于注释（sk5_manager.py:432/:915、policy-routing.sh:46）与门禁桩 `verify-integration.sh:156` 的 `"tuntap add") exit 0` 分支。后者现为死分支——产品代码与门禁替身均不再调用它；桩把一个已删操作建模为静默成功，若产品代码未来重引 `tuntap add`，门禁不会因此红。记观察 O-R25-3（建议桩改为 exit 1，使重引大声失败），不立案（无门禁格依赖它，R24/BT 探针才是占位符的检测器）。
- **`REPAIR_MODE` 现为死标志**：policy-routing.sh 内两处赋值（do_restore :516、分发器 :556），**零处读取**——do_enable 的自检门已改为无条件 `if tun1_live`，三动词行为已统一为 repair 语义。无害（行为一致），但头部注释仍称 “Restore runs in REPAIR_MODE, never full enable”，与“动词已统一”不完全同调。记观察 O-R25-4（文档小漂移），不立案。
- **BT 的 Flask 卷首补漏已核**：`r17_flask.py` 卷首现含 `OVPN_SK5_CONFIG_DIR`；宿主 `/etc/openvpn-sk5-panel/` 开工时不存在、`panel/data/` 为空（本轮开工核过）。完工复核：宿主 `/etc/openvpn-sk5-panel/` 现存在但为空（门禁／探针的 bind 挂载点，无凭据、无残留），`panel/data/` 仍为空。

### §1.4 BT 必审项②独立核：三重判死＋`_singbox_running()==False` 门控（F0 格）

F0 标志形状实证（真实内核，私有 netns；R25 探针 F0a–f 全过）：

| 形状 | `ip link show` 标志 | 三重判死 |
|---|---|---|
| 设备不存在 | rc!=0 | False |
| 刚建未 up | `<POINTOPOINT,MULTICAST,NOARP>` state DOWN，无 NO-CARRIER | False |
| up、无持有者（占位符形） | `<NO-CARRIER,POINTOPOINT,MULTICAST,NOARP,UP>` state DOWN | **True（唯一可删形）** |
| fd 持有＋up（活设备形） | `<POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP>` state UNKNOWN | False |
| 持有后被 down（O-R24-1 形） | `<POINTOPOINT,MULTICAST,NOARP>` state DOWN | False（pre-clean 拒绝删除，F0f） |

**② 独立核通过**：三重判死仅在“up、无持有者”时为真。启动中的 sing-box 要么是 DOWN 无 NO-CARRIER、要么是 UP＋LOWER_UP——两形三重判死均为 False，故即使在 systemd “activating” 窗口（`_singbox_running()` 返 False）里 pre-clean 也不会误删活设备。BO 当年拒删死占位的竞态（systemd 自动重启恰在检查与删除之间 spawn）已被正面回应：唯一残留窗口的后果是瞬时启动失败（systemd 重试），永不是楔死。**① 仍属 live-17**（5 秒窗口在 512MB 机上的实际表现，沙箱无 systemd、无 boot 时序分布，无法采样）；**④ 已核**（见 §2.4–§2.5：等待失败零状态由 S1b 证实，毫秒竞态残留 K11 由 K11 格证实，面板三值与 500 文案一致，无“启用失败但显示已启用”或反之）。

## §2 修复路径收敛性（本轮推导方法：路径×退化态矩阵）

路径：**P1** 健康检查 tick（`_repair_policy`＋复验）、**P2** boot restore（`do_restore`）、**P3** `enable()`、**P4** `set_sk5` 修复分支、**P5** `disable()`。退化态沿用 R24 的 K0–K10，新增 **K11**（BT 毫秒竞态残留）与 D3/D4/D5。探针 `tests/r25_repair_convergence.py` **37 格 ALL PASS**（真实脚本＋真实内核＋真实 sk5_manager，私有 netns；stub sing-box 四态 dead／live／slow-7s／strict-live；stateful stub systemctl 建模 StartLimitBurst=5 与 reset-failed）。每格结论：收敛到活链 K1、或兜底＋诚实、或大声失败；**任一格静默楔死即立案——本轮无一格静默楔死**（见 §2.5–§2.7 的三项观察）。

| 态 | P1 tick | P2 boot restore | P3 enable() | P4 set_sk5 修复分支 | P5 disable() |
|---|---|---|---|---|---|
| K0 禁用干净 | chain_disabled 待机 ✓ | 缺失／禁用 no-op ✓ | →K1 ✓ | 纯保存 ✓ | 幂等 K0 ✓ |
| K1 健康 | healthy ✓ | — | 重开→K1 ✓（live headline-1） | — | →K0 ✓ |
| K2 黑洞-only、daemon 死 | kill-switch；daemon 回后下一档→K1 ✓（S2a/b） | →K2，下一档补齐 ✓ | →K1 ✓ | daemon 死→enable 腿→K1 ✓（P4c） | →K0 ✓ |
| K3 旧楔死（占位＋linkdown＋rule＋黑洞） | pre-clean＋repair→kill-switch；P3 重开→K1 ✓（B3/P6/E1） | 装黑洞＋rule、删陈旧路由；**设备留给首档 P1 清**；daemon 若先启会撞 EEXIST、5 次后 failed，须人工重开（见 §2.1） | →K1 ✓（E1b，strict 守护进程） | →K1 ✓（同 P3 腿） | →K0＋死设备残留 inert（无路由引用，下次 enable 清） |
| K4 linkdown、无黑洞（手改限定） | repair→K2 ✓ | — | →K1 ✓ | — | →K0 ✓ |
| K5 仅 rule、表空 | repair→K2→K1 ✓ | — | →K1 ✓ | — | →K0 ✓ |
| K6 无 rule＋路由＋黑洞 | 补 rule→K1/K2 ✓ | — | →K1 ✓ | — | →K0 ✓ |
| K7 无 rule＋黑洞-only | 补 rule→K2 ✓ | →K2 ✓ | →K1 ✓ | — | →K0 ✓ |
| K8 活路由、无黑洞（手改限定） | **不补黑洞**（policy_ok 时只验探针，K8b）→ O-R24-2 延续 | — | →K1 ✓（重装黑洞在先） | — | →K0 ✓ |
| K9 已启用但 K0 | repair→K2→K1 ✓ | →K2 ✓ | →K1 ✓ | — | →K0 ✓ |
| K10 禁用但策略在（手改限定） | chain_disabled，不碰 → O-R24-3 延续 | — | — | — | →K0 ✓ |
| K11 rule＋黑洞-only、enabled=false | chain_disabled，**不清理** → O-R25-1 | no-op，留 K11 → O-R25-1 | →K1 ✓（K11f/g） | 禁用态纯保存，不碰 → O-R25-1 | →K0 ✓（K11e） |
| D1 sk5.json 损坏 | 大声失败、零状态改动 ✓ | 大声 die、动策略前死 ✓（BP，live-16 §9.2） | 大声失败 ✓ | 大声失败 ✓ | 大声失败、策略留原态（须手修文件，BP 定案） |
| D2 队列不可读 | 正交：BQ 隔离＋审计行，poll 继续 ✓ | — | — | — | — |
| D3 慢启动＞5s（仅冷启） | 已启用链：档 1 kill-switch、档 2→K1 ✓（S2a/b） | — | 大声失败、零状态（S1）；重试→K1 ✓（S2） | — | — |
| D3 持续慢（每启＞5s） | 已启用链同上；未启用链 P1 不动 | — | **活锁**：每次点击重启计时、永不收敛 → O-R25-2 | — | — |
| D4 StartLimitBurst 楔死 | 诚实 kill-switch、**永不重启 daemon**（设计）→ O-R25-5 | — | reset-failed＋重启→K1 ✓（D4d） | — | →K0 ✓ |
| D5 daemon 持有 tun1 被手 down | **无 healthy 谎报**：kill-switch、设备不删（D5a/b/c）✓ | — | 重启销毁 down 设备、全新创建→K1 ✓（D5d） | — | →K0 ✓ |

### §2.1 K3×P2（boot 遇旧楔死）：收敛到兜底＋诚实，daemon 须人工重开

`do_restore` 是纯 shell 路径（systemd 单元直接调脚本），不经过 Python 的 pre-clean：它装黑洞＋rule、删陈旧 linkdown 路由，但**不删设备**。首档 P1 tick 的 `_repair_policy` 会清掉占位（daemon 未运行，门控通过），故楔死不持久；但若 sing-box 在 P1 之前先启，会撞地址 EEXIST FATAL、5 次后落 failed，之后只靠人工重开恢复（reset-failed＋重启→K1，D4d 同款）。后果是有声有形的（kill-switch＋`singbox_running=false`），无静默、无泄漏；且触发须“pre-BT 楔死设备跨升级存活到 boot”，post-BT 无产品路径再写占位。记为 K3 行内的已知边界，不立案；**boot 单元时序（policy 与 sing-box 谁先跑）沙箱无 systemd、无法采样，属 live-17 的真机格**。

### §2.2 R24 观察 O-R24-1 已关闭、O-R24-2／O-R24-3 延续（均手改限定）

- **O-R24-1 关闭**：D5 格实测——daemon 持有 tun1 被手 down 后，`_policy_active()` 判 False（D5a），P1 tick 报 `blackholed_kill_switch` 而非 healthy（D5b），设备不被误删（D5c），人工 enable 重启后→K1（D5d）。BT 层 ②（linkdown 敏感谓词）顺带关闭了 R24 的 healthy 谎报格。
- **O-R24-2 延续**：K8 格实测——活路由、无黑洞时 P1 tick 不补黑洞（K8b）。写者仍仅手改（产品路径恒先装黑洞）；若此后 sing-box 死，表空→K5→下一档 P1 修复为 K2，暴露窗口 ≤60 秒。仍为观察，不立案。
- **O-R24-3 延续**：K10（禁用但策略在）P1 不碰。写者仍仅手改；产品 `disable()` 先清策略后落盘，无此路径。仍为观察，不立案。

### §2.3 P4 与 P5 无行为漂移（BT 必审项③）

P4b：daemon 活＋策略缺失→就地修复（repaired:true，同一 daemon PID，**不重启**）；P4c：daemon 死＋已启用＋策略缺失→enable 腿（K1，`sing-box restarted`）。`_apply_policy()` 默认动词改为 repair 后三调用点均显式传 repair，无裸调用；disable() 未动，K11e/K10 格证实其收敛到 K0。**③ 无漂移**。

### §2.4 K11 的状态定义（新态）

K11 ＝ rule＋黑洞-only 表、enabled=false。BT 披露的毫秒竞态产物：tun1 在 enable() 的 5 秒等待与策略应用之间死亡。脚本以 exit 0 返回（无活 tun1 时的黑洞-only 是脚本的**设计**结果），Python 应用后复验 `_policy_active()` 失败→raise 且不回滚（脚本自身回滚只在脚本失败时跑）。面板诚实：`policy_routing_active=false`、`egress_ip=None`、enabled false、500 文案点名“re-enable via the panel”。

### §2.5 观察 O-R25-1（K11 无自动清理路径）

K11 格实测：P1 短路于 enabled=false（K11c/d，rule 仍在）、P2 按“未启用” no-op、P4 禁用态纯保存——**无自动路径清理 K11**，只剩人工 enable/disable。BT 披露的不回滚理由（“已启用链上回滚会把流量放回直连”）在 K11 不成立——此时 enabled=false，回滚 rule 即恢复“禁用＝直连”的契约。定性：观察，不立案。理由三点：① 触发是毫秒竞态，窄；② 失败闭合＋大声＋诚实（500 文案＋状态三值一致），非静默；③ 一键恢复（enable/disable 均收敛）。加固建议（供下轮，不阻塞）：enable() 应用后复验失败分支里先调 `_remove_policy()` 再 raise，恢复 K0。

### §2.6 观察 O-R25-2（enable 对持续慢 daemon 的活锁）

`enable()` 无条件重启 daemon（`_start_singbox` 先 reset-failed 后 restart，不查是否已在跑）。若**每次**启动都 ＞5 秒，则每次点击都在 5 秒处 raise、并把刚起的 daemon 杀掉重计时——P3 永不收敛；enabled=false 又使 P1 不动。冷启一次性慢则重试收敛（S2，warm 重启快）。定性：观察，不立案。理由：① 触发（每启恒＞5 秒）在真机上未证实——**属 live-17 的 BT 真机格①（512MB 机 5 秒窗口采样）**，沙箱无 systemd、无 boot 时序分布，无法判定；② 失败大声＋诚实＋无泄漏。加固建议（供下轮）：enable() 在 daemon 已在跑且 tun1 将活时不重启，或等待窗口按冷启放宽并记录实测分布。

### §2.7 观察 O-R25-5（D4：P1 永不重启 daemon，设计使然）

D4 格实测：start-limit 楔死时 P1 每档诚实报 kill-switch、永不重启 daemon（D4b/c）；人工 enable 经 reset-failed＋重启→K1（D4d）。这是 BM 的放置决定（健康检查定时器只修策略、不碰守护进程生命周期）。定性：观察（设计记录，非缺陷），不立案。

## §3 门禁（29 格）

- **机械推导**：`grep -c 'ok "' verify-integration.sh` ＝ **31**；减死代码 1（`check()` 辅助函数 :39——全树零调用点，其内的 `ok` :41 永不触发）；减互斥分支 1（:254–258 的 `elif`／`else` 两枚 `ok`，每轮只其一触发）；**31−1−1＝29**。与运行时汇总对账一致。
- **干净串行跑**：本轮亲自跑，**PASS=29 FAIL=0 SKIP=0**（rc=0）。串行跑的理由：脚本用固定 `/tmp/ovpn-int-test`＋8443 端口，非并发安全；跑前核过 8443 空闲、无门禁目录残留。
- **§7 第二层（字典绑定）变异 11/11**：`tests/build-mutants.py` 构建（C(4,2)=6 两两字典互换：m-dict-sb／m-dict-ts／m-dict-x-amd／m-dict-x-arm／m-dict-x-a／m-dict-x-b；缺项 m-dict-missing；多项 m-dict-extra；两层常量互换 m-const-sb／m-install-sb；单字符 m-char），逐棵串行跑门禁——**11 棵全为 PASS=28 FAIL=1，红格均为 §7 唯格“钉死哈希不一致：install.sh 与 agent/agent.py 的 sha256 逐键不等”**。第二层载荷实证。
- **门禁桩的 `tuntap add` 死分支**（见 §1.3／O-R25-3）：桩把已删操作建模为静默成功；门禁格本身不依赖它，占位符检测器是 R24/BT 探针。

## §4 回归套件（本轮亲自重跑）

三路并行（Flask／core＋Worker／netns 各自串行，互不共享数据目录、fixture 副本、私有 netns；门禁另串行跑，见 §3）。Flask 探针在 `/tmp/r25/ptree` 活树副本上跑（nobody＋`/tmp/r25/venv`，fixture 副本 `/tmp/r25/fixture-ca`＋`fixture-server`）；脚本／内核探针直接读活树（只读产品文件，内核态私有 netns）；Worker 面为 mock KV。

| 套件 | 读数 | 说明 |
|---|---|---|
| R17 Flask | **86/89** | 3 红全为预期 OBSERVED 翻转（F4-02b／F4-13／F4-15，R17-P1-1 钉死格） |
| R17 Core | **46/46** | |
| R17 Agent | **33/33** | |
| R17 Worker | **33/35** | 2 红全为预期 OBSERVED 翻转（W5-05／W5-06a） |
| BG（Flask poll 守卫） | **22/22** | |
| BH（Worker poll 守卫） | **20/20** | |
| BI（Worker 队列竞态＋畸形 sweep） | **15/15＋18/18** | |
| BJ（Worker 非列表容器＋下载） | **12/12＋8/8** | r19 两探针 |
| BK（存量形状） | **8/8** | |
| BM（黑洞＋自愈） | **22/22** | |
| BO（tun1 repair） | **18/18** | |
| BP（boot restore） | **14/14** | |
| BQ（队列不可读）＋R21（队列隔离） | **6/6＋6/6** | |
| BR（loginfail 数组） | **11/11** | |
| BS（verdict） | **9/9** | |
| R22 Flask＋Worker | **22/22＋12/12** | |
| R18 再现探针（队列竞态＋畸形） | **7/9＋9/13** | 红格全为修复后行为翻转（RACE-02／RACE-05、M-06 等钉死格按缺陷行为写、修复后翻红——与 R18 结论一致） |
| R20 输入形状 | **4/7** | S1/S2/S6 三红全为预期：S1/S2 是 BK 修复后诚实 ValueError 替代静默漂洗；S6 是 BL 修复后 HB-OK（`sk5_enabled: False`）替代 AttributeError |
| BT | **ALL PASS** | |
| R24 | **ALL PASS** | |
| R25（本轮新探针） | **37/37 ALL PASS** | 含 E1（strict 守护进程鉴别 enable 路径 pre-clean）与 D5/K8 格 |

**环境注（r20 探针）**：电池首轮以 nobody 跑 r20 时 S6 起不来（`unshare` 写 uid_map EPERM）且进程在 S6 处 return 99、S7 未跑；改以 root 重跑仍撞第二处——`/tmp/r20` 父目录 770（nobody 建）使新 mount ns 内遍历报 Permission denied（`unshare -rm` 含 `-r`、新建 userns，外层 uid 映射失效）。`chmod 755 /tmp/r20` 后完整跑出 4/7。以上皆沙箱／权限 artefact，非产品问题；S6 的 BL 修复行为（HB-OK）在 root 重跑中已实测。

### §4.4 live-17 对账

**待 live-17 完工对账**（本轮不默写结论）。live-17 负责：BT 真机格（真实重启＋512MB 机 5 秒窗口采样——O-R25-2 的触发判定与 BT 必审项①）＋S0–S4 回归；Worker 面真机格以 mock-KV 为准（见 §5）。

## §5 文档与交付面核查

- **过期计数 grep**：`PASS=28`／`28/28`／`28 格`／`55 项` 全树零命中（审计／live 报告除外）；`逐字节一致` 仅 README.md:198 一处，且在 tarball 二进制 vs 同 release `.deb` 包内二进制的上下文——R15-P2-2 定案保留的合法用法。干净。
- **README:198 钉子**：`install.sh:63-66` 四枚哈希（sing-box amd64 `950af37e…`、arm64 `20a6a9cd…`、tun2socks amd64 `a612baa2…`、arm64 `3931476c…`）与 `agent/agent.py:122-132` 逐键一致（门禁 §7 格亦在 29/29 跑中通过）；版本核对 1.11.15／2.7.0 与代码一致。
- **egress/README:40**：`tun1 由 sing-box 自建、本脚本永不建设备（R24-P2-1）`——与 BT 后行为一致。
- **P0 dry-run**：`npx -y wrangler@4.161.0 deploy --dry-run` exit 0；KV id 仍为占位符 `REPLACE_WITH_KV_NAMESPACE_ID`／`REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`。与 R8–R24 每一轮相同：**P0-1/2/3 从未在真实 Cloudflare Worker 部署上验证**（须用户建 API token 或交互 `wrangler login`、填 KV id、`wrangler secret put ADMIN_PASSWORD`＋`AGENT_BUNDLE_ORIGIN`）。第十一次未答——交付文档须把 Cloudflare 模式部署态标为未验（见 §7）。
- **功能链骨架复核（§0 注）**：本树 9 份文档（根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md）逐份通读：与 R24 后唯一的产品改动（BT）相关的宣称——egress/README 的 tun1 口径、docs/security.md 的 repair 语义——均已同步；其余文档无 BT 相关漂移。Worker 面 56 项（BD 定案）未变。

## §6 历史全量复扫（R24 的 163 条逐条核现状＋本轮新立 0 条）

R24 台账 163 条（159 已修＋2 部分＋1 未验＋1 新 R24-P2-1）；本轮复扫基数 163 条。本轮新立 **0 条**，累计仍为 **163 条**。

| 状态 | 数量 | 构成 |
|---|---|---|
| 已修 | 160 | R24 的 159＋R24-P2-1（BT 修完，本轮 §1 行为重验＋三棵定点变异逐棵恰红，关闭，沙箱级；真机格待 live-17） |
| 部分 | 2 | P0-3（首登强制改密未实现，文档已诚实）、P1-7（同族，见 R19 台账）——均按设计 partial，不重立 |
| 未验 | 1 | P0-1（Cloudflare 真实部署从未验，§5；第十一次待用户决断） |
| 未修（本轮新） | 0 | **差集 ∅（沙箱级；live-17 对账后定稿，见 §7）** |
| **复发** | **0** | 无一已修条目复发：R17-P1-1 的 BG／BH 仍成立（Flask 86/89、Worker 33/35，红格均为预期翻转）；R18 的 BI 仍成立（race 15/15、malformed 18/18；R18 复现探针 7/9、9/13 为修复后预期值，见 §4）；R19 的 BJ 仍成立（12/12、8/8）；R20 的 BK／BL 仍成立（BK 8/8；R20 探针 4/7，三红为按缺陷断言的预期翻转，S6 已完整跑出）；R21 的 BN 仍成立（R21 探针 6/6）；BQ 仍成立（6/6）；BM 两层仍成立（22/22）；BO 仍成立（18/18）；BP 仍成立（14/14）；BR 仍成立（11/11）；BS 仍成立（9/9）；R13-P2-5 的 agent `_as_int` 仍成立（Agent 33/33）；R9-P2-1 的备份层仍成立（R21 探针 6/6）；R24 的 O-R24-1 已由 BT 层 ② 关闭（D5 格，见 §2.2）；门禁 29/29（§3） |

**未动文件规则**：自 R24 完工起，全树产品代码改动仅为 BT 一路（egress/sk5_manager.py、egress/policy-routing.sh、verify-integration.sh 门禁桩；其余产品文件 mtime 均在 BT 窗口之前，一字未动，见 §0），结论沿用 R1–R24 证据，不冒充重跑；BT 触及的 egress 面由 §1–§2 的探针＋变异＋回归全数重验。本轮新增／改动仅为探针资产（`tests/r25_repair_convergence.py` 新 37 格、E1/D5/K8 格、R9 前提清理）与本报告。

**待用户决断（第十一次未复，自 R8 §5 起）**：P0-1/2/3 的 Cloudflare 真实部署——需用户创建 Cloudflare API token 或交互式 `wrangler login`，并填 `wrangler.toml` 的 KV id＋preview_id、跑 `wrangler secret put ADMIN_PASSWORD`、配 `AGENT_BUNDLE_ORIGIN`。若用户永不启用，交付文档须把 Cloudflare 模式部署状态标为未验。另：SK5 端口 1001 vs 9000 仍待用户确认（面板默认 1001，文档已标待定）。

## §7 结论

**结论：可交付（差集 ∅）——沙箱级；live-17 完工对账后定稿。**

- **差集清单**：无。本轮新立 **0 条**（§2 的路径×退化态矩阵无一格静默楔死；§6 历史 163 条复扫零复发）。
- **观察 5 项（均不立案，带加固建议）**：
  - **O-R25-1**（K11 无自动清理路径，§2.5）：毫秒竞态残留 rule＋黑洞-only、enabled=false；P1/P2/P4 均不碰，只剩人工 enable/disable。触发窄、大声＋诚实、一键恢复。建议：enable() 应用后复验失败分支里先调 `_remove_policy()` 再 raise。
  - **O-R25-2**（enable 对持续慢 daemon 的活锁，§2.6）：每启恒＞5 秒时每次点击重启计时、永不收敛。触发未证实，裁定权在 live-17 的 512MB 机 5 秒窗口采样。建议：daemon 已在跑且 tun1 将活时不重启，或按冷启实测放宽窗口。
  - **O-R25-3**（门禁桩 `tuntap add` 死分支，§1.3）：桩把已删操作建模为静默成功；若产品代码未来重引，门禁不会因此红。建议：桩改为 exit 1。
  - **O-R25-4**（`REPAIR_MODE` 死标志，§1.3）：两处赋值、零处读取；头部注释与“动词已统一”不完全同调。建议：删标志并改注释。
  - **O-R25-5**（D4：P1 永不重启 daemon，§2.7）：BM 的放置决定，设计记录；人工 enable 经 reset-failed＋重启→K1。
- **live-17 对账（待完工，本轮不默写结论）**：BT 真机格（真实重启＋512MB 机 5 秒窗口采样→裁定 O-R25-2 触发；boot 单元时序→K3×P2 边界；K11 的真机可达性）＋S0–S4 回归。若 live-17 发现 5 秒窗口在 512MB 机上系统性不足，O-R25-2 须升级立案，定稿随之改判。
- **本轮未验与上限（诚实清单，不冒充）**：沙箱无 systemd、无 boot 时序分布（5 秒窗口、boot 单元时序、StartLimitBurst 的真机行为均以 stub／状态机建模，属 live-17）；沙箱无真实 SK5（`test_sk5()` 的 TCP 拨测恒因无 dante 而失败，故 S2b／K8 格的 verdict 以探针受限记，只断言策略层状态）；Worker 面为 mock-KV（真机 Worker 格从未验，P0-1）；无 arm64 真机（§7 变异为代码层红证）；Cloudflare 真实部署从未验（P0-1，第十一次待用户决断，§5–§6）；SK5 端口 1001 vs 9000 仍待用户确认。

（报告完。审计员：独立审计路；`docs/audit/AUDIT-R25.md`，215 行。）

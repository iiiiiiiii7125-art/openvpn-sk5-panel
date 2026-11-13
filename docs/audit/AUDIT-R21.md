# AUDIT-R21 — 全量全局回头看（交付前，第九轮）

## 结论先写

**结论：不能交付（差集 1 条，P2：R21-P2-1）。**

历史 156 条：**已修 152、部分 2（P0-3、P1-7，按设计）、未验 1（P0-1，Cloudflare 真实部署）、新 1（R21-P2-1）、复发 0**。R20 的 2 条（P2-1、P2-2）经 BK／BL 修复、R13-BUG-1（高）经 BM 修复，本轮 §1 核验。

- 审计员：独立审计路（未参与建设与修复路 BK／BL／BM；单审计员边做边写，不派子代理）
- 日期：2026-11-13（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R20 同等广度）
- 推导方法：**失效传播追踪**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性、R9 对抗操作员＋时间衰变、R10 环境矩阵×修复存活、R11 契约闭合、R12 外部输入枚举、R13 部署生命周期、R14 证据优先行为复推导、R15 交付文档驱动用户旅程重演、R16 门禁与证据链反向审计、R17 爆炸半径 FMEA、R18 命令生命周期状态机转移闭合、R19 跨面一致性、R20 输入形状全集均不同）——先枚举全部失效源（守护进程死亡、KV／文件损坏、网络分区、运维误操作、时钟偏移），再逐源追踪失效在每一层的传播（面板→队列→agent→core／egress→内核路由→用户流量），核每一层是 containment（兜住）、honest report（诚实上报）、self-heal（自愈）三者之一；任一层让失效静默逃逸或放大即立案。R17 的 blast-radius FMEA 是按组件列 blast，本轮按失效源追传播路径，二者不重叠；R20 的输入形状结论只作输入，不作本轮证据。
- 测试一律在 `/tmp/r21/ptree` 副本上跑；未动项目原文件（除本报告）；门禁自带 harness（venv＋桩 sing-box/systemctl/ip，面板以 nobody 跑）；未动任何真机。需真机行为复核的项一律写“待 live-14”或对账 live-13，不提前判通过。
- 语法基线：`node --check`（index.js）与 `python3 -m py_compile`（panel／core／agent／egress）均过；`bash -n verify-integration.sh install.sh` 过。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明（与 R9–R20 同款记明）。

## §0 树版本与 BK／BL／BM 改动确认

当前树是 BK／BL／BM 三路修复之后的新树。文件 mtime（UTC）与 R20 §0 基线对照：

| 文件 | mtime (UTC) | 行数 | sha256（前 12 位） | 说明 |
|---|---|---|---|---|
| cloudflare/src/index.js | 2026-11-12 19:25:36 | 1473 | 089bb32da319 | 未动（R20 mtime，BJ） |
| cloudflare/README.md | 2026-11-12 19:28:49 | 262 | 47489de2f9a4 | 未动（R20 mtime） |
| panel/app.py | 2026-11-12 18:38:12 | 2754 | 204de1136cc5 | 未动（R20 mtime，BG） |
| core/openvpn_manager.py | 2026-11-12 17:20:57 | 1550 | 3b5d7dfe9ea1 | 未动（R20 mtime，BB） |
| agent/agent.py | 2026-11-12 19:50:12 | 922 | f303af828555 | **动过（BL：心跳 sk5 段 isinstance 检查）** |
| egress/sk5_manager.py | 2026-11-12 20:03:26 | 1228 | 7727486677a2 | **动过（BK：`_validate_stored` 单点检查＋except 拓宽；BM：`_repair_policy` 自愈＋`_blackhole_active`＋policy_missing 真实 detail）** |
| egress/policy-routing.sh | 2026-11-12 20:06:09 | 366 | 423a98bd022e | **动过（BM：兜底黑洞 metric 200＋自检＋注释重写）** |
| install.sh | 2026-11-12 16:46:54 | 1082 | 3f050f037e7a | 未动（R20 mtime，AZ） |
| verify-integration.sh | 2026-11-12 18:14:53 | 630 | 6ef6ba2db8b1 | 未动（R20 mtime，BE） |
| panel/templates/index.html | 2026-11-12 15:21:57 | 1259 | 4f7dc697451c | 未动（R20 mtime） |
| README.md | 2026-11-12 17:56:09 | 287 | 6154ecabe046 | 未动（R20 mtime） |

结论：自 R20 起全树只有 `agent/agent.py`（BL）、`egress/sk5_manager.py`（BK＋BM）、`egress/policy-routing.sh`（BM）三处产品文件动过；其余文件 mtime 与 sha256 均与 R20 §0 基线一致。历史复扫按 mtime 规则：未动文件的既往结论沿用 R1–R20 证据，不冒充重跑；BK／BL／BM 的改动面本轮全量行为重验（§1）＋失效传播全集重审（§2）。

## §1 BK／BL／BM 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

### §1.1 BK（R20-P2-1：存量 port 洗白）＋ BL（R20-P2-2：心跳 AttributeError）

| 探针 | 结果 | 说明 |
|---|---|---|
| R20 形状 `tests/r20_input_shapes.py` | **S1/S2/S6 按预期翻转，S3–S5/S7 保持** | S1/S2 FAIL＝缺陷不再复现（诚实 ValueError 点名文件＋字段＋类型：`bad stored …/sk5.json: port must be an integer 1-65535, got bool True`／`got float 1194.5`）；S6 FAIL＝缺陷不再复现（真实 `heartbeat_status()` 返回 `HB-OK {... 'sk5_enabled': False}`，不抛）；S3–S5 控制格 PASS，S7 观察格 PASS |
| BK 新探针 `tests/bk_stored_shapes.py` | **8/8** | 数字串 port 拒、两开关字符串拒、0/1 归一化、get_status 降级 config_error、current_egress_ip 回 None、port 0／70000 拒 |
| R17 Core `tests/r17_core.py` | **46/46** | 全绿（`R17_TREE=<活树>`＋fixture env，否则探针默认跑 /tmp 过期树） |
| R17 Agent `tests/r17_agent.py` | **33/33** | 全绿 |
| 门禁 | **29/29** | 见 §3 |

定点变异红证（`tests/r21_reverts.py` 生成到 `/tmp/r21/mutants/`，四棵逐棵恰红）：

- **m-validate**（删 `_validate_stored(cfg)` 调用）：R20 探针 S1/S2 立刻回 PASS（`server_port` 1／1194 复现），其余格不动（S6 仍 FAIL＝BL 修复在位）。R20-P2-1 闭合。
- **m-heartbeat**（心跳 isinstance 检查拆除、直调 `.get()`）：S6 回 PASS（`HB-ATTR AttributeError 'list' object has no attribute 'get'` 复现），S1/S2 仍 FAIL＝BK 修复在位。R20-P2-2 闭合。

**探针自身缺陷，本轮修净（R21-P0-1，探针，不立案为产品问题）**：S6 子探针的 ptree 同步只含 agent/＋core/，缺 egress/——agent.py import 时要 `sk5_manager`，缺 egress 即 `ModuleNotFoundError`，其输出既无 HB-ATTR 又无 HB-OK，旧探针把“探针起不来”误读为“缺陷未复现”（FAIL）。本轮已修 `tests/r20_input_shapes.py`：同步增 egress/，且无 HB-ATTR 又无 HB-OK 时返回 setup-fail，主流程 exit 99 大声报错，不再把 setup 失败当成修复成立。修后重跑 S6 得真 HB-OK，BL 闭合证据才成立。教训：缺陷复现探针（FAIL＝缺陷消失）必须对“跑不起来”与“缺陷消失”分流，否则一次环境损坏会把未修复判成已修复。/tmp/r17/ptree 本轮已不存在（又被清空），R17 套件一律以 `R17_TREE=/tmp/r21/ptree`（活树新鲜副本）跑。

### §1.2 BM（R13-BUG-1：sing-box 死亡静默回直连）

| 探针 | 结果 | 说明 |
|---|---|---|
| BM 新探针 `tests/bm_blackhole_selfheal.py` | **22/22** | 真实 netns＋真实 ip：K1 空表落回主表复现 bug、K2 黑洞使查表 EINVAL、K3 tun1 路由优先、K4 删 tun1 路由回落黑洞、K5 flush 恢复直连；mock ip 真脚本格 S1–S7；真 check_health 自愈逻辑 H1–H10 |
| BK 探针 `tests/bk_stored_shapes.py` | **8/8** | BM 未伤 BK 面 |
| R17 Core `tests/r17_core.py` | **46/46** | 全绿 |
| R17 Agent `tests/r17_agent.py` | **33/33** | 全绿 |
| 门禁 | **29/29** | 见 §3 |

定点变异红证（`tests/r21_reverts.py`，两棵逐棵恰红）：

- **m-blackhole**（删黑洞安装块＋黑洞自检块，忠实恢复修前 enable 路径——只删安装会使 enable 在自检处大声失败，机制不同，不忠实）：BM 探针恰好 S1/S2/S5/S7 红（S1 黑洞未装、S2 幂等计数 bh=0、S5 缺 tun1 时全量未装、S7 自检不存在），其余 18 格不动。层 1（兜底黑洞）承重。
- **m-repair**（`_repair_policy()` 调用改为强制失败）：BM 探针恰好 H1/H2/H3/H6/H7 红——全部是断言“repair 层存在且动作”的格（H1 修好转健康、H2 修好仍死为黑洞、H3 修复被尝试且 detail 含 `auto-repair: policy re-apply failed`、H6 fail-open 前先尝试修复、H7 首检修复后次检不再修）；H4/H5（detail 的 held／direct 分流）与 H8–H10（禁用／健康态零修）不动。层 2（自愈）承重。注：H3 的红含 note 文本依赖（detail 格式本身是修复的一部分），机制上仍属 repair 层。

**§1 结论：R20 的 2 条与 R13-BUG-1 行为重验通过，定点变异 4/4 恰红，BK／BL／BM 三修复闭合（沙箱级；真机格待 live-14，见 §4.4）。**

### §1.3 BJ 面无回归（Worker 探针重跑）

| 探针 | 结果 |
|---|---|
| 非列表容器 `tests/r19_worker_nonlist_container.mjs` | **12/12** |
| 下载守卫 `tests/r19_worker_ovpn_download.mjs` | **8/8** |
| BH Worker poll 守卫 `tests/bh_worker_poll_guard.mjs` | **20/20** |
| BI 竞态 `tests/bi_worker_queue_race.mjs` | **15/15** |
| BI 畸形 `tests/bi_worker_malformed.mjs` | **18/18** |

## §2 失效传播追踪（本轮推导方法）

全集 = 全部失效源（守护进程死亡、KV／文件损坏、网络分区、运维误操作、时钟偏移、部署事件），逐源追踪失效在每一层的传播（面板→队列→agent→core／egress→内核路由→用户流量），核每一层是 containment（兜住）、honest report（诚实上报）、self-heal（自愈）三者之一；任一层让失效静默逃逸或放大即立案。未动文件沿用既往证据（mtime 规则，§0）；本轮亲手追踪的源附代码行号与探针证据。

### §2.1 全集清单（失效源 × 传播层 × 裁决）

| # | 失效源 | 传播与裁决 | 证据 |
|---|---|---|---|
| F1 | sing-box 死亡（kill／崩溃／OOM） | 黑洞兜住（BM L1：tun1 路由死后落 metric 200 黑洞，不落回主表）＋60 秒健康检查自愈重装（BM L2）＋detail 写清兜住／直连 | §1.2 BM 探针 22/22＋双变异恰红 |
| F2 | dante／SK5 死亡 | tun1 路由在位，socks 连不上即丢包；egress.ip 诚实 null；dante 回来自动恢复；隧道不断 | live-13 S3（13 轮同款） |
| F3 | openvpn 死亡 | 用户掉线、无流量可漏（containment 平凡成立）；面板 running=false 诚实；恢复靠面板 restart／agent restart 动作（产品未给 openvpn 配自动重启看门狗，distro 单元亦不在树内——可用性缺口，非安全缺口） | 代码核：restart 端点在位 |
| F4 | 面板死亡（Flask down／Worker 不可达） | 数据面不受影响（隧道照跑）；agent 退避重试；Flask 单元 Restart=on-failure；会话存活（secret.key 在 /etc，不在树内） | systemd 单元＋R5 |
| F5 | agent 死亡 | 数据面不受影响；last_seen 冻结（诚实）；单元 Restart=on-failure；崩溃循环撞 systemd 默认启动上限后进 failed 态（可见，非静默） | systemd 单元 |
| F6 | agent 配置不可解析 | import 时 RuntimeError→进程退出→同 F5（面板无法远程修，与死亡同后果） | agent.py:197 |
| F7 | sk5.json 形状损坏 | BK `_validate_stored` 单点拒（port／开关）；host 错型响亮失败；JSON 不可解析→写路径 RuntimeError、读路径 config_error／None | §1.1 探针 S1–S5＋BK 8/8 |
| F8 | sk5.json 缺失 | 取默认值（禁用态），不崩 | `_load_config` |
| F9 | 队列文件整文件损坏 | **兜住半层、诚实缺失——见 R21-P2-1（§2.2）** | 本轮新探针 6 格 |
| F10 | 队列条目畸形 | 标 failed＋审计行＋跳过，通道不 wedge | BA 6/6＋本轮 Q6 对照 |
| F11 | Worker KV 记录损坏 | sweep 标 failed＋warn；容器非数组归一化；下载守卫快照容错 | §1.3 12/12＋8/8＋18/18 |
| F12 | Worker 节点记录缺 token_hash | `node.token_hash &&` 短路→401，不放行 | index.js:256 代码核 |
| F13 | 面板↔agent 分区 | agent 退避重试；命令留 queued（Flask 无 TTL／Worker 7 天 TTL）；sent 120 秒超时重投／标失败 | R5／R18 |
| F14 | DNS 死亡 | DNS 默认走直连（文档定案）；panel_url 为 IP；bundle 源站 DNS 死→503／502 明示 | live 各轮＋R11 |
| F15 | 时钟向后跳变 | sent 命令 `(now-sent)<=120s` 恒真、滞留至时钟追上（无钳制）；自愈（时钟追上即重投），agent 回执路径不受影响 | 见 O-R21-2 |
| F16 | 运维手改 KV／队列／配置 | 覆盖于 F7／F9／F10／F11；并发操作由 `_QUEUE_LOCK`／`_SK5_MUTATE_LOCK`／flock／条件清除串行 | R8／R12／R18 |
| F17 | 重启 | policy 服务开机 restore（含 BM 黑洞，do_enable 内）；健康检查定时器 60 秒兜底；openvpn 先起、策略后到的窗口按包路由、仅秒级 | install.sh:928/:930＋restore 代码核 |
| F18 | PKI 部分失败后重试 | build_server_cert 幂等（全集复用、部分集先清后建）；create_server 仅 ca.crt 缺失时才 init_pki，不撞 CA 已存在 409 | core:200／agent.py:633 |
| F19 | 吊销已连接用户 | agent 路径：revoke 后立即 restart_server，已建会话被断开；Flask 本地路径：只返 `needs_restart:true`＋前端提示，须人工重启（R7／R15 已裁定一致，见 O-R21-1）；下载三路均 403 | agent.py:686／app.py:1797／R13 |
| F20 | easyrsa 失败／超时／缺脚本 | `_run_easyrsa`→非零即 OpenVPNError，命令 honest failed | core:126 |
| F21 | 磁盘满 | 原子写失败响亮 500；审计 insert 失败吞掉（“审计失败不阻塞业务”，设计）；登录记账包 try/except（AK） | R9／R10 |
| F22 | 健康检查定时器死亡 | 面板不读 health.json（仅 sk5_manager 自读写），状态走 agent 实时探针——定时器死只丢自愈／fail-over，不丢诚实上报 | grep health.json 仅 egress |
| F23 | tun1 名字碰撞 | enable 先起 sing-box（其建 tun1），碰撞→sing-box 起不来→enable 大声失败，不静默劫持；repair 建的 tun1 与 sing-box 重启接管关系待真机核（见 O-R21-3） | egress:977/:985＋ensure_tun1 |
| F24 | 安装中途失败／并发安装 | set -e＋preflight；并发 loser 死于 apt 锁、零写（D13）；毒 panel.data 排除（AN） | live-10 D13 |
| F25 | 未知 agent 动作 | 白名单外返回 `unknown action` failed 回执，永不抛 | agent.py:773-782 |
| F26 | Worker KV 7 天 TTL 到期 | queued 命令过期消失→cmd_get 404；与 F9 同形但有时限＋文档化（KV 生命周期），不另立 | R18 §3 |
| F27 | index.txt 损坏 | 短行跳过＋last-wins＋过期比较（AL）；缺文件→空用户集，不崩 | R9-P1-2 |
| F28 | OpenVPN 状态文件缺／截断 | 解析分路＋未知行跳过，online_users 0；openvpn running 位区分“无人”与“服务死” | R2／live BUG-9 |

### §2.2 新发现 R21-P2-1（P2）：队列文件整文件损坏 → 已排队命令静默丢失，面板零痕迹

**机制谓词**：`_load_queue`（panel/app.py:481）遇整文件损坏（JSON 不可解析／顶层非对象／任一段非对象）时隔离整个文件为 `.corrupt.<时间戳>` 备份＋一条 stderr WARNING，然后返回空队列；调用方随后 `_save_queue` 写回全新空队列，丢失完成。此后：poll 200 空下发（通道不 wedge——containment 成立）；`cmd_get` 对丢失的命令回 **404“命令不存在”**（事实错误：命令存在过，是损坏丢的）；**audit_log 里零行提及隔离**（`grep audit`：`_quarantine_corrupt_queue` 内无 `_audit` 调用；全树 `quarant` 命中仅 :463–507）。操作员的唯一界面（面板 UI／审计页／API）对此次丢失零信号——只有看 panel 服务 journal 的 stderr 才能发现。与**同一文件的条目级损坏**对照：BA 的 `_fail_malformed_cmds` 把坏条目标 failed＋写 `queue_malformed` 审计行（本轮 Q6 对照：malformed_rows=1）。整文件损坏的处置比条目级损坏少一层诚实上报。

**与 R9-P2-1 的关系（不是复发，是同 fix 的未验半层）**：R9-P2-1 本身就是“队列损坏→全部已排队命令静默丢失，无任何报错”，AK 的修法三选一里写明“损坏时保留 `.corrupt` 备份＋日志告警”可接受；R10 只验了“备份与损坏内容字节一致”即判已修，**从未验过“操作员能否发现丢失”**。本轮按失效传播追踪重审：备份层（containment）确实在位且字节一致（Q3），但诚实上报层从未落地——stderr WARNING 不进面板、不进审计、不进任何 API。谓词不同（备份在位 vs 上报缺失），计新发现，不计复发。

**全集清单（`_load_queue()` 全部 9 处呼叫点，`grep` 机械推导；8 处随后 `_save_queue`，丢失由任一触发）**：

| 呼叫点 | 随后保存 | 触发后果 |
|---|---|---|
| `_enqueue_command` :529 | :535 | 下一次入队即完成丢失 |
| `nodes_register` :2325 | :2327 | 注册节点时完成丢失 |
| `nodes_revoke` :2349／:2357 | :2351／:2369 | 吊销节点时完成丢失 |
| `cmd_get` :2427 | :2431 | 查一条命令即完成丢失 |
| `node_user_ovpn` :2488 | :2493 | 下一个 .ovpn 下载即完成丢失 |
| `agent_poll` :2546 | :2574 | **最可能触发：每节点每 5 秒一次 poll** |
| `agent_report` :2606 | :2609／:2662 | 下一次回执即完成丢失 |
| `ovpn_users_download` :1830 | 无（只读） | 不完成丢失 |

**复现**（新探针 `tests/r21_queue_quarantine.py`，本轮亲手跑，真实 test_client＋真实 panel.db）：入队 get_status（202，记 cmd_id）→队列文件写成 `{not json,,,`→poll 200 `commands=[]`（Q1）→`GET /api/cmd/<id>` 404“命令不存在”（Q2）→`.corrupt` 备份存在且字节一致（Q3）→audit_log 3 行、**零行提及 quarantine／corrupt**（Q4 FAIL）→queue 段写成字符串同款零审计行（Q5）→对照：条目级非对象记录 poll 200 且 `queue_malformed` 审计行 1 条（Q6）。Worker 面无同形（KV 按键隔离、sweep 标 failed＋warn，无整文件概念）——面×属性矩阵：Flask 整文件损坏漏报，Worker 同族闭合。

**修法**：`_quarantine_corrupt_queue` 内（或其三个呼叫点）补一条审计行（BA 同款 `queue_malformed` 家族，建议 `queue_quarantined`）：action＋result=failed＋detail 只写备份路径、损坏原因、丢失的 queued／sent 命令计数（计数不写内容——队列含密码与 .ovpn 私钥），绝不把文件内容写进审计。另：cmd_get 对隔离丢失的 id 仍 404（可接受——id 已不在任何可查状态），但审计行须让操作员在审计页查到“某时队列被隔离、丢了 N 条”。修完重跑 Q1–Q6（Q4 翻绿，Q1–Q3／Q5／Q6 保持）＋R17 Flask 套件。

### §2.3 观察（不立案）

- **O-R21-1（吊销：本地人工重启 vs agent 自动重启的分歧，已裁定）**：Flask 本地吊销只返 `needs_restart:true`＋前端提示（index.html:753 回退文案＋后端 note 一致），须人工重启才断已建会话；agent 路径（远程节点＋Worker 面）revoke 后立即 restart_server，已建会话当即断开。分歧本身从未被单列裁定过，但两端行为各自在 R7（“前端提示＋后端 needs_restart:true 一致”）与 R15（J9“吊销＋CRL＋须重启”通过）里被判通过；CRL 只在启动时读是文档化事实，操作员在吊销当时即被告知。按“已登记问题只验现状、不重复立案充数”口径不另立，仅把分歧记在此处供后轮可见。
- **O-R21-2（时钟向后跳变滞留 sent 命令）**：`_requeue_stale_sent` 用 `(now - sent) <= 120s` 判断超时，无钳制；时钟向后跳变后 sent 命令滞留至时钟追上。触发须 NTP／虚拟机时钟回拨；自愈（时钟追上即重投，retries 计数保留）；agent 回执路径不受影响（回执到即完成）。不立案。
- **O-R21-3（repair 建的 tun1 与 sing-box 重启接管，待真机）**：BM 自愈调 do_enable→ensure_tun1；sing-box 死且被启动上限锁住时，repair 会用 `ip tuntap` 自建 tun1。此后 sing-box 手动重启能否接管已存在的同名 tun（内核 TUNSETIFF 按名挂接语义）沙箱无法验证（无 sing-box 真 daemon），列入 live-14 核查项，不立案。
- **O-R21-4（开机 restore 遇损坏 sk5.json）**：`do_restore` 用裸 `json.load(...).get("enabled")` 判断，损坏文件→python 非零→enabled=0→开机不恢复策略、流量走直连；60 秒内健康检查发现 policy_missing 并诚实上报（repair 因 `_load_config` 抛错而失败）。触发须“损坏文件＋重启”双条件；操作员须手改文件（BK 定案行为），上报链完整。不立案。

### §2.4 面×属性矩阵（双面能力对齐，本轮新增一格）

| 能力 | Flask 面 | Worker 面 | 结论 |
|---|---|---|---|
| 队列容器非数组 | 非列表按空处理（R14-BA） | `kvArray` 归一化（BJ） | 双面闭合 |
| 畸形命令记录 | 标 failed＋审计（BA） | sweep 标 failed＋warn（BI） | 双面闭合 |
| 非 queued 分发 | 循环顶守卫＋report 409（BG） | 守卫内 push＋report 409（BH） | 双面闭合 |
| 下载吊销／过期守卫 | 三路 403（AW） | 快照守卫 403（BJ） | 双面闭合 |
| **整文件损坏的丢失上报** | **零痕迹（R21-P2-1）** | 无整文件概念（按键隔离＋sweep） | **Flask 面独漏** |
| 存量 port 形状 | `_validate_stored`（BK） | 不读此文件 | 单面能力，BK 闭合 |
| 心跳 sk5 读值 | 不读此文件 | 不读此文件 | 单面能力，BL 闭合 |
| sing-box 死兜底 | 黑洞＋自愈（BM，双面同 egress） | 同 egress | 双面同源闭合 |

## §3 门禁本身是审计对象（29 格逐格机械推导＋§7 变异红证）

### §3.1 格数推导（静态 `ok "` 计数 vs 运行时汇总）

`grep -c 'ok "' verify-integration.sh` = **31** 静态出现；运行时汇总 **29** 格。差 2 的机械对账（与 R20 同款，逐项复核无变化）：

1. **死代码 1 格**：`:39` 的 `ok "$name"` 在 `check()` helper 内；全树 `grep "check \""` 零调用——该 helper 从未被调用，此 `ok` 静态在场、运行时零次触发。
2. **互斥分支 1 格**：`:251` 与 `:253` 在同一 `if/elif/else` 链内（`/etc` 隔离快照比对）：admin.pass 被改→`bad`；目录清单变但 admin.pass 未动→:251 的 ok；全未变→:253 的 ok。静态 2 处、每轮恰好 1 格。
3. `skip()` 仅 :37 一处定义，全树零调用，SKIP 恒 0。

31 − 1（死） − 1（互斥） = **29**，与运行时 `PASS=29 FAIL=0 SKIP=0` 逐格对账一致（活树日志 29 行 `[PASS]`＋汇总行）。

### §3.2 活树门禁

本轮亲手跑活树 `./verify-integration.sh`（`/tmp/r21/gate-live.log`）：**PASS=29 FAIL=0 SKIP=0，exit=0**。§7 格（“钉死哈希一致：install.sh 与 agent/agent.py 的 sha256 逐键相等”）绿。

### §3.3 §7 两层变异红证（`tests/build-mutants.py`，7 棵逐棵跑门禁）

| 变异树 | 改动 | 门禁结果 | 唯一红格 |
|---|---|---|---|
| m-dict-sb | 字典 sing-box amd64/arm64 值互换（常量不动） | 28/1 | §7 |
| m-dict-ts | 字典 tun2socks amd64/arm64 值互换（常量不动） | 28/1 | §7 |
| m-dict-missing | 字典缺一项（3 条） | 28/1 | §7 |
| m-dict-extra | 字典多一项（5 条，`("sing-box","arm")`） | 28/1 | §7 |
| m-const-sb | agent.py sing-box 常量值互换 | 28/1 | §7 |
| m-install-sb | install.sh sing-box 赋值互换 | 28/1 | §7 |
| m-char | agent.py 常量改一位 hex | 28/1 | §7 |

7 棵逐棵恰红（每棵唯一 FAIL 均为“钉死哈希不一致…”§7 格，日志 `/tmp/r21/gate-m-*.log`）。BE 的 §7 第二层（字典绑定：条目名须为 `(binary,arch)` 命名常量、值须等于 install.sh 同名赋值、恰好 4 条）四向变异全红，第一层（常量逐键）三向变异全红。门禁本身通过。

**§3 结论：门禁 29 格推导闭合，§7 两层变异 7/7 恰红。**

## §4 R17 四套件重跑＋文档＋对比度＋P0 dry-run

### §4.1 R17 四套件（本轮亲手重跑，探针树 `/tmp/r21/ptree` 为活树新鲜副本）

| 套件 | 结果 | 红格说明 |
|---|---|---|
| Flask `tests/r17_flask.py` | **86/89** | 仅 F4-02b／F4-13／F4-15 红——三格均为 OBSERVED 钉死格（钉的是 R17-P1-1 的违规行为）；BG 修复后违规不再发生，格子按设计翻红，即修复成立的正信号，非新缺陷 |
| Core `tests/r17_core.py` | **46/46** | 全绿 |
| Agent `tests/r17_agent.py` | **33/33** | 全绿 |
| Worker `tests/r17_worker.mjs` | **33/35** | 仅 W5-05／W5-06a 红——两格均为 OBSERVED 钉死格（钉的是 BH 修复前的违规）；修复后违规不再发生，翻红即修复成立。W5-01（poll 不分发 failed 命令）绿，BH 成立。W5-06b 的 PASS 属 benign：409 拒收回执后命令仍为 queued，poll 分发它是合法行为（格名是 BH 守卫前的旧描述，行为本身正确；直接断言 failed 不分发的 W5-01 已绿） |

合计 198/203，5 红全为缺陷钉死格的预期翻转，无新失败。另跑 BG 回归 `tests/r18_bg.py` **22/22**。

**本轮探针／夹具维护（R21-P0-2，探针，不立案为产品问题）**：/tmp 又被清空两轮（`/tmp/r17/ptree` 与 `/tmp/r18-verify/venv` 均消失），本轮三处修净并落进树内：
- `tests/r17_core.py`：C1-13 把共享夹具 server.conf 写成 port 51194 后不复位，次轮 C1-02/03/05/08/12 全红（本轮亲手复现 41/46）；已在 main 末尾补复位（重渲染 port 1194），连续两轮 46/46、夹具留 port 1194。
- `tests/rebuild-r17-fixture.sh`：BM 的重建配方缺 `pki/ta.key`（`_rebuild_user_ovpn` 重建 .ovpn 必需），致 Flask F5-01 404；已补 2048-bit 静态密钥生成。另补末尾 nobody 归属（重建后夹具 root:700，nobody 跑套件 EACCES；render 的 `chmod` 在非属主文件上报 EPERM——本轮三处均亲手复现并修净）。
- `tests/r20_input_shapes.py`：S6 子探针同步缺 egress/，见 §1.1（R21-P0-1）。

夹具：fixture-server/server.conf 已是 `port 1194`（未污染）；Flask 跑完核宿主 `/etc/openvpn-sk5-panel`——目录为空（R20 清过的泄露凭据未再出现）；`/etc/openvpn` 不存在。

### §4.2 文档检查（全树 grep）

- `SCRIPT_VERSION`／`resolve_version`：正文与代码中 0 处（命中仅在 `docs/live-verify-R10/R11.md` 历史报告内引用 grep 结论的句子，属排除项）。
- 过期门禁计数“28”：产品文档与代码 0 处（命中仅在历史审计／live 报告内——当时基线确为 28，属历史记录排除项）；现行计数 `egress/README.md:210` 为 29/29，与 §3 一致。
- BJ／BK／BL／BM 文档行：`cloudflare/README.md` Worker 行为覆盖表三行（畸形容器归一化、sweep 与孤儿回收、下载吊销／过期守卫）在位。
- 对比度：`panel/static/contrast-check.py` **10/10 PASS，0 FAIL**（底线 4.5 全过；目标 7 达成 4/10，与 R15–R20 同款）。

### §4.3 P0 dry-run（Cloudflare 真实部署仍未验）

本轮新跑 `npx wrangler@4.161.0 deploy --dry-run`（`cloudflare/`，日志 `/tmp/r21/wrangler-dryrun.log`）：**exit=0**，绑定列出 `env.PANEL_KV (REPLACE_WITH_KV_NAMESPACE_ID)` 与 `env.PANEL_MODE ("cloudflare")`，`--dry-run: exiting now.`。但 `wrangler.toml:32-33` 的 KV id 与 preview_id 仍为占位符，`wrangler secret put ADMIN_PASSWORD` 与 `AGENT_BUNDLE_ORIGIN` 仍未配——真实部署仍卡用户侧（P0-1/2/3，自 R8 §5 起第七次未复，见 §5）。

### §4.4 live-13 对账与 live-14

**live-13 已完工对账（`docs/live-verify-R13.md`，198 行，本轮通读全文）**：R18 的 2 条真机格全过（机上 mock-KV 格：BI 竞态 15/15、畸形 18/18，复现探针按预期翻转 7/9＋9/13，BH 20/20，Flask 对照 BG 22/22）；S0–S4 全过（BUG-9 第 13/14 次复验双模全过，S3 杀 dante 全断无回落自动恢复，S4 TCP 443 五次首连全 1 秒内）；headline 精选全过（首启 200＋10 交替 delta 恰 10、并发 delta 恰 1、policy-missing 诚实＋零重起修复、verify.sh 开 18/0/4 关 23/0/0、前端 0 低于 4.5、毒树重跑行级一致）。**新 bug 1 个（高）：R13-BUG-1**——sing-box 死亡静默回直连（两次独立复现，curl 回真实 IP exit 0，table 100 空，重启后仍空、无自愈）；本轮 §1.2 已核 BM 修复闭合（沙箱级），真机格待 live-14。

**live-14 待完工对账。**（本轮不写 live-14 的任何结论；R19／R20／BM 的真机格＋S0–S4 回归待其完工后由主控对账。Worker 面真机格以 mock-KV 为准，上限写明。）

## §5 历史全量复扫（156 条逐条核现状）

R20 台账 154 条（已含 R20 新立 2 条）；live-13 新立 R13-BUG-1（高）1 条；本轮新增 R21-P2-1 1 条，累计 **156 条**。

| 状态 | 数量 | 构成 |
|---|---|---|
| 已修 | 152 | R20 的 149＋R20-P2-1／R20-P2-2（BK／BL 修完，本轮 §1 行为重验＋定点变异恰红，关闭）＋R13-BUG-1（BM 修完，本轮 §1 行为重验＋定点变异恰红，关闭，沙箱级） |
| 部分 | 2 | P0-3（首登强制改密未实现，文档已诚实）、P1-7（同族，见 R19 台账）——均按设计 partial，不重立 |
| 未验 | 1 | P0-1（Cloudflare 真实部署从未验，§4.3；第七次待用户决断） |
| 未修（本轮新） | 1 | **R21-P2-1**（§2.2） |
| **复发** | **0** | 无一已修条目复发：R13-P2-5 的 agent `_as_int` 修复仍成立（agent 套件 33/33）；R17-P1-1 的 BG／BH 修复仍成立（Flask 86/89、Worker 33/35，红格均为预期翻转）；R18／R19／R20 的 BI／BJ／BK／BL 修复仍成立（§1 重跑全绿＋变异恰红）；R9-P2-1 的备份层仍成立（本轮 Q3 字节一致），其上报半层见 R21-P2-1（新谓词，不计复发） |

R20 的 2 条与 R13-BUG-1 关闭证据：§1（R20 探针 S1/S2/S6 按预期翻转、BK 8/8、BM 22/22；m-validate／m-heartbeat／m-blackhole／m-repair 四棵逐棵恰红）。历史 154 条中其余条目：文件未动（§0 mtime），结论沿用 R1–R20 证据，不冒充重跑；R17 四套件重跑（§4.1）与门禁重跑（§3）无一触发旧条目复发信号。

**待用户决断（第七次未复，自 R8 §5 起）**：P0-1/2/3 的 Cloudflare 真实部署——需用户创建 Cloudflare API token 或交互式 `wrangler login`，并填 `wrangler.toml` 的 KV id＋preview_id、跑 `wrangler secret put ADMIN_PASSWORD`、配 `AGENT_BUNDLE_ORIGIN`。若用户永不启用，交付文档须把 Cloudflare 模式部署状态标为未验。

## §6 结论

**结论：不能交付（差集 1 条，P2）。**

| 编号 | 级别 | 一句话 | 修法指向 |
|---|---|---|---|
| R21-P2-1 | P2 | 队列文件整文件损坏 → 已排队命令静默丢失，面板零痕迹（备份在位、审计零行、cmd_get 404 误报“不存在”） | `_quarantine_corrupt_queue` 补审计行（备份路径＋损坏原因＋丢失 queued／sent 计数，不写内容），修完重跑 Q1–Q6＋R17 Flask 套件 |

其余全绿：BK／BL／BM 三修复闭合（§1，变异 4/4 恰红）、门禁 29/29＋§7 变异 7/7 恰红（§3）、R17 四套件 198/203（5 红全为预期翻转，§4.1）、BG 22/22、文档 stale 0 处＋对比度 10/10（§4.2）、P0 dry-run 通过但真实部署仍未验（§4.3）。live-13 已对账（R13-BUG-1 沙箱级关闭）；live-14 待完工对账（§4.4）；本轮差集修完后须按第一前提①再做一轮全量全局回头看（AUDIT-R22）才准交付。

**新探针资产**：`tests/r21_queue_quarantine.py`（Q1–Q6：整文件损坏丢失上报缺失＋条目级对照）；`tests/r21_reverts.py`（m-validate／m-heartbeat／m-blackhole／m-repair 定点回退变异构建器）；另修 `tests/r20_input_shapes.py`（S6 同步 egress＋setup 失败 exit 99）、`tests/r17_core.py`（夹具 server.conf 复位）、`tests/rebuild-r17-fixture.sh`（补 ta.key＋nobody 归属）。

## §7 本轮未验与上限（诚实清单，不冒充）

- **live-14**：与本轮并行在跑（R19／R20／BM 的真机格＋S0–S4 回归），本轮只写“待完工对账”，无结论。
- **R13-BUG-1 真机格**：BM 修复的真机复现（杀 sing-box→黑洞兜住、重启自愈）只认 live-14；本轮只到沙箱 netns＋mock 格。
- **arm64**：无 arm64 机器，§7 的 arm64 哈希绑定只在沙箱变异上验活（m-dict-ts／m-const-sb 均红），真机安装格未验（与 R16–R20 同款）。
- **UDP 数据面**：沙箱 UDP sendto 一律 EPERM、TUN 创建 EPERM，本轮一切 UDP 断言均为形状／渲染级；UDP 真通路只认 live 轮。BM 探针的 netns 格用真实 ip／真实路由表查表（K1–K5），不发 UDP 包。
- **Cloudflare 真实部署**：P0-1/2/3 仍卡用户侧（§4.3、§5）；dry-run 通过不等于部署通过。
- **门禁的沙箱前提**：`verify-integration.sh` 是沙箱门禁（头注“沙箱内运行”）；get_status 格断言 `running is False`，在真机活 openvpn 上按设计红（live-11 已定位，非缺陷），沙箱 29/29 为门禁 verdict 依据。
- **O-R21-3 的 sing-box 接管语义**：repair 建的 tun1 与 sing-box 重启接管关系未在沙箱验证（无真 daemon），只认 live-14。

## 附录 A：§2 普查的机械推导命令（可复现）

```bash
# 队列读点全集（R21-P2-1 的 9 处 _load_queue＋8 处 _save_queue）
grep -n "_load_queue()\|_save_queue(" panel/app.py
# Worker 认证缺 token_hash（F12）
grep -n "token_hash" cloudflare/src/index.js
# health.json 消费者（F22）
grep -rn "health.json\|HEALTH_FILE" egress/ panel/ agent/
# sent 超时无钳制（O-R21-2）
grep -n "SENT_TIMEOUT_SECONDS" panel/app.py
# 门禁格数推导（§3.1）
grep -c 'ok "' verify-integration.sh        # 31 静态
grep -n "check()" verify-integration.sh      # :39 死代码 helper
# 文档 stale（§4.2）
grep -rn "SCRIPT_VERSION\|resolve_version" --include="*.md" . | grep -v "docs/audit"
grep -rn "门禁 28\|28/28\|PASS=28" --include="*.md" --include="*.sh" --include="*.py" . | grep -v "docs/audit" | grep -v "docs/live"
```

## 附录 B：本轮验证命令速查（可复现）

```bash
# 探针树（活树新鲜副本）与 venv
cp -a ~/workspace/openvpn-sk5-panel /tmp/r21/ptree
python3 -m venv /tmp/r21/venv && /tmp/r21/venv/bin/pip install flask bcrypt >/dev/null
# R17 四套件（Core／Agent 跑 root；Flask／BG 跑 nobody，夹具须 nobody 归属）
R17_TREE=/tmp/r21/ptree OPENVPN_CA_DIR=/tmp/r17/fixture-ca \
  OPENVPN_SERVER_DIR=/tmp/r17/fixture-server python3 tests/r17_core.py
R17_TREE=/tmp/r21/ptree python3 tests/r17_agent.py
node tests/r17_worker.mjs
runuser -u nobody -- env PYTHONPATH=/tmp/r21/venv/lib/python3.12/site-packages \
  R17_TREE=/tmp/r21/ptree OVPN_PANEL_DATA_DIR=/tmp/r21/fdata \
  OVPN_PANEL_SECRET_PATH=/tmp/r21/fdata/secret.key \
  OPENVPN_CA_DIR=/tmp/r17/fixture-ca OPENVPN_SERVER_DIR=/tmp/r17/fixture-server \
  OVPN_SK5_CONFIG_DIR=/tmp/r21/fsk5 python3 /tmp/r21/ptree/tests/r17_flask.py
# BK／BM／R20 探针与 R21 定点变异（§1）
python3 tests/bk_stored_shapes.py; python3 tests/bm_blackhole_selfheal.py
python3 tests/r20_input_shapes.py; python3 tests/r21_queue_quarantine.py
python3 tests/r21_reverts.py                      # 4 棵定点变异 → /tmp/r21/mutants/
# 门禁活树＋§7 七变异（§3）
./verify-integration.sh                            # 29/29
python3 tests/build-mutants.py /tmp/r21/ptree /tmp/r21/mutants-gate
for m in m-dict-sb m-dict-ts m-dict-missing m-dict-extra m-const-sb m-install-sb m-char; do
  (cd /tmp/r21/mutants-gate/$m && ./verify-integration.sh)   # 每棵 28/1 §7 唯一红
done
# P0 dry-run（§4.3）与对比度（§4.2）
cd cloudflare && npx wrangler@4.161.0 deploy --dry-run
python3 panel/static/contrast-check.py            # 10/10 PASS
```

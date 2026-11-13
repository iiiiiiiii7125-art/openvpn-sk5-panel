# AUDIT-R20 — 全量全局回头看（交付前，第八轮）

## 结论先写

**结论：不能交付（差集 2 条，全 P2：R20-P2-1 存量 sk5 port 洗白、R20-P2-2 agent 心跳 AttributeError 致节点静默）。**

历史 154 条：**149 已修、2 部分（P0-3、P1-7）、1 未验（P0-1）、2 未修新（R20-P2-1、R20-P2-2），0 复发**。R19 的 2 条（P2-1、P2-2）经 BJ 修复、本轮 §1 核验关闭。

- 审计员：独立审计路（未参与建设与修复路 BJ；单审计员边做边写，不派子代理）
- 日期：2026-11-13（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R19 同等广度）
- 推导方法：**输入形状全集审计**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性、R9 对抗操作员＋时间衰变、R10 环境矩阵×修复存活、R11 契约闭合、R12 外部输入枚举、R13 部署生命周期、R14 证据优先行为复推导、R15 交付文档驱动用户旅程重演、R16 门禁与证据链反向审计、R17 爆炸半径 FMEA、R18 命令生命周期状态机转移闭合、R19 跨面一致性均不同）——先把全树所有外部输入点（HTTP 请求体／查询／头、KV 记录、队列文件、配置文件、环境变量、命令行参数、agent 回执、easyrsa 输出、OpenVPN 状态文件）按“来源×字段×类型×边界值”机械枚举成全集清单，再逐项验证每一项都有类型守卫、边界守卫、失败时诚实报错且不污染后续状态；任一项无守卫或守卫可被绕过即立案。R12 审的是“坏输入是否进系统”，本轮审的是“每一种输入形状是否都有守卫闭合”，二者不重叠；R19 的跨面一致性结论只作输入，不作本轮证据。
- 测试一律在 `/tmp` 副本上跑；未动项目原文件（除本报告）；门禁自带 harness（venv＋桩 sing-box/systemctl/ip，面板以 nobody 跑）；未动任何真机。需真机行为复核的项一律写“待 live-13／live-14”或对账 live-12，不提前判通过。
- 语法基线：`node --check`（index.js）与 `python3 -m py_compile`（panel／core／agent／egress）均过；`bash -n verify-integration.sh install.sh` 过。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明（与 R9–R19 同款记明）。

## §0 树版本与 BJ 改动确认

当前树是 BJ 修复路之后的新树。文件 mtime（UTC）与 R19 §0 基线对照：

| 文件 | mtime (UTC) | 行数 | sha256（前 12 位） | 说明 |
|---|---|---|---|---|
| cloudflare/src/index.js | 2026-11-12 19:25:36 | 1473 | 089bb32da319 | **动过（BJ：`kvArray` 归一化 helper＋11 处读点＋下载快照守卫；与主控核验的 sha256 一致）** |
| cloudflare/README.md | 2026-11-12 19:28:49 | 262 | 47489de2f9a4 | 动过（主控：按 R19 §5 补 Worker 行为覆盖表三行＋修 `tests/r17_worker.mjs` 陈旧 import） |
| panel/app.py | 2026-11-12 18:38:12 | 2754 | 204de1136cc5 | 未动（R19 mtime，BG） |
| core/openvpn_manager.py | 2026-11-12 17:20:57 | 1550 | 3b5d7dfe9ea1 | 未动（R19 mtime，BB） |
| agent/agent.py | 2026-11-12 16:46:20 | 922 | 7f999298df5b | 未动（R19 mtime，AX） |
| install.sh | 2026-11-12 16:46:54 | 1082 | 3f050f037e7a | 未动（R19 mtime，AZ） |
| verify-integration.sh | 2026-11-12 18:14:53 | 630 | 6ef6ba2db8b1 | 未动（R19 mtime，BE） |
| panel/templates/index.html | 2026-11-12 15:21:57 | 1259 | 4f7dc697451c | 未动（R19 mtime） |
| README.md | 2026-11-12 17:56:09 | 287 | 6154ecabe046 | 未动（R19 mtime） |

结论：自 R19 起全树只有 `cloudflare/src/index.js`（产品）与 `cloudflare/README.md`（文档）动过；其余文件 mtime 与 sha256 均与 R19 §0 基线一致。历史复扫按 mtime 规则：未动文件的既往结论沿用 R1–R19 证据，不冒充重跑；BJ 的改动面（Worker 容器归一化＋下载守卫）本轮全量行为重验（§1）＋输入形状全集重审（§2）。

## §1 BJ 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

BJ 只改 `cloudflare/src/index.js`（`kvArray` helper＋11 处读点＋`handleCompatOvpnDownload` 快照守卫）。本轮亲手重跑其两套探针与 R17/R18 的相关套件（均在树内 `tests/`，指向活树）：

| 探针 | 结果 | 说明 |
|---|---|---|
| 非列表容器 `tests/r19_worker_nonlist_container.mjs` | **12/12** | NL-01–NL-09 原红格全绿 |
| 下载守卫 `tests/r19_worker_ovpn_download.mjs` | **8/8** | DL-03/DL-04 原红格全绿 |
| BH Worker poll 守卫 `tests/bh_worker_poll_guard.mjs` | **20/20** | 无回归 |
| BI 竞态 `tests/bi_worker_queue_race.mjs` | **15/15** | 无回归 |
| BI 畸形 `tests/bi_worker_malformed.mjs` | **18/18** | 无回归 |
| 语法基线 | 全过 | `node --check` index.js；`py_compile` panel/core/agent/egress；`bash -n` verify-integration.sh install.sh |

定点变异红证（只回退该条修复，`tests/r20_reverts.py` 生成到 `/tmp/r20/mutants/`，两棵逐棵恰红）：

- **m-kvarray**（`kvArray` 改回原样——忠实回退：null/undefined 仍回 `[]`，保留原 `|| []` 对 null 的处理；第一版用 plain-identity 回退误伤了 null 格，已纠正重跑）：非列表容器 **3/12**，恰好 NL-01–NL-09 红；下载 8/8、BH 20/20 不受影响。R19-P2-1 闭合。
- **m-dlguard**（下载快照守卫拆除）：下载 **6/8**，恰好 DL-03/DL-04 红；非列表 12/12、BH 20/20 不受影响。R19-P2-2 闭合。

另核 BJ 下载守卫的快照形状容错（代码读 `cloudflare/src/index.js` `handleCompatOvpnDownload`）：`snap = (await kvGetJson(...)) || {}`（null→`{}`），`users = Array.isArray(snap.users) ? snap.users : []`（非数组→`[]`），`find` 内 `u && typeof u === "object"` 跳过非对象条目——字符串/数字/null 快照均不抛。§2 的 census 覆盖其余 KV 读点。

复现命令（探针树 `/tmp/r20/ptree` 为活树新鲜副本；R17 套件按 `tests/README.md` 以 nobody 跑）：

```bash
node tests/r19_worker_nonlist_container.mjs   # 12/12
node tests/r19_worker_ovpn_download.mjs       # 8/8
node tests/bh_worker_poll_guard.mjs           # 20/20
node tests/bi_worker_queue_race.mjs           # 15/15
node tests/bi_worker_malformed.mjs            # 18/18
python3 tests/r20_reverts.py  # 无参数，自取活树建 /tmp/r20/mutants/m-kvarray 与 m-dlguard
```

**§1 结论：R19 的 2 条（P2-1、P2-2）行为重验通过，定点变异恰红，BJ 修复闭合。**

## §2 输入形状全集普查（本轮推导方法）

全集 = 全树所有外部输入点，按“来源×字段×类型×边界值”机械枚举；逐项核：类型守卫、边界守卫、失败时诚实报错且不污染后续状态。形状枚举以代码搜索推导（`grep` 全树），行为证据以本轮探针与 R12/R13/R17/R18/R19 既有套件为准；未动文件沿用既往证据（mtime 规则，§0）。

### §2.1 全集清单（来源 × 形状 × 守卫）

| # | 来源 | 字段／形状 | 守卫 | 证据 |
|---|---|---|---|---|
| 1 | Flask HTTP 体 | `_json_body` 非对象／非 JSON | 400（app.py:1018） | R12 r12_inputs 84/86 |
| 2 | Flask HTTP 体 | `port` bool／float／str／越界 | `_valid_port`：`type is int`＋1–65535（:1027） | R12-P1-2／AU 19/19 |
| 3 | Flask HTTP 体 | 开关 `bool("false")` 反向 | `_coerce_bool`／`_strict_bool` 只认真布尔／0/1（:1034/:1049） | R12-P2-1 |
| 4 | Flask HTTP 体 | 节点名越界／非法字符 | `_NODE_NAME_RE` 1–32 alnum/_/- | R12 |
| 5 | Flask HTTP 体 | `panel_url` 认领 | 逐字相等否则 403 | R11 |
| 6 | Flask HTTP 体 | audit `limit` 非数字／越界 | try/except＋clamp 1..500（:2507） | R12 |
| 7 | Flask HTTP 体 | 登录体非对象／数组 | `readJson` null＋数组 400（Worker 同款；Flask 见 R12 O1） | R13-P2-4／AY |
| 8 | Flask HTTP 体 | `port=0`／`False` 假值合并 | 显式 `port is None`（AX，core:1085-1088） | R13-P2-2 |
| 9 | Flask HTTP 体 | `dns=False/0/""` 假值合并 | 显式 `dns is None`＋`_validate_dns`（BB，core:1095-1097） | R14-P2-2 |
| 10 | Flask 队列文件 | 手改条目缺键／错型／非对象 | `_fail_malformed_cmds` 扫三路＋隔离＋审计（AS） | R12-P1-1／R14-P2-1／BA 6/6 |
| 11 | Flask 队列文件 | sent 态 `sent_at` 不可解析 | `sent_at` 可解析性检查（AW） | R13-P2-1 |
| 12 | Flask 队列文件 | 非 queued 命令被 poll 分发 | 循环顶 `status != "queued": continue`＋report 非 sent 409（BG） | R17-P1-1／BG 22/22 |
| 13 | Flask 下载 | 吊销／过期用户 .ovpn | `_snapshot_users`＋`_download_block_reason` 三路统一 403（AW） | R13-P2-3 |
| 14 | Worker HTTP 体 | 列表型 params／body.node 缺失 | 400／body.node＞?node=＞X-Node（AT） | R12-P2-4／P2-5 |
| 15 | Worker HTTP 体 | 登录体数组 | `Array.isArray(body)` 400（AY） | R13-P2-4 |
| 16 | Worker HTTP 体 | SK5 port 非整数 | `Number.isInteger(port)`＋1–65535（index.js:1165） | R17 |
| 17 | Worker KV | 队列／sent 容器非数组 | `kvArray` 归一化（BJ） | §1 12/12＋变异恰红 |
| 18 | Worker KV | 队列竞态（poll 窗口内入队） | 条件清除只清已取 id（BI） | BI 15/15 |
| 19 | Worker KV | 畸形记录／孤儿 sent | `_sweepWorkerCmds`＋`toMs`（BI） | BI 18/18 |
| 20 | Worker KV | 非 queued 命令被 poll 分发 | queued 内推＋report 非 sent 409（BH） | R17-P1-1／BH 20/20 |
| 21 | Worker KV | 下载不查吊销／过期 | 快照 users 守卫（BJ） | §1 8/8＋变异恰红 |
| 22 | Worker KV | 快照非对象／users 非数组 | `|| {}`＋`Array.isArray`＋find 内对象检查 | §1 代码核＋探针 |
| 23 | Worker KV | 无名节点记录 | `listNodes` 跳过＋warn | R12-P2-3 |
| 24 | core 解析 | index.txt 缺字段／过期 | TAB 行＜6 字段跳过＋last-wins＋有效过期比较（AL） | R9-P1-2 |
| 25 | core 解析 | 状态文件 v1/v2/TAB／前缀行 | 逗号 v2/v1＋TAB 管理口＋前缀形分路 | R2／live-9–12 BUG-9 |
| 26 | core 解析 | DNS 非串／非法字符 | `_validate_dns` 拒非串＋字符集检查（:959） | R12／AU |
| 27 | core 解析 | 已有 server.conf 损坏 | `_parse_existing_server_conf` 显式报错＋恢复指引（AU） | R12-P1-2 |
| 28 | core 渲染 | `port`／`proto`／`allow_port_change` 错型 | 渲染入口严格守卫（AU） | AU 19/19 |
| 29 | agent 回执 | poll 响应非 JSON／非对象 | `json.loads`＋`isinstance(data, dict)`（agent.py:305-309） | R17 |
| 30 | agent 动作 | `port=True`／float／`"1194"` | `_as_int` 先拒 bool/float（AX，:352） | R13-P2-5／agent 21/21 |
| 31 | agent 动作 | host／bool／proto 错型 | `_HOST_RE`／`_as_bool`／`_as_proto` | R13／R17 |
| 32 | agent 配置 | 配置文件非对象 | dict 检查（:197） | R12 |
| 33 | egress 配置 | sk5.json 非对象 | `_load_config` dict 检查＋解析区分（:103） | R9／S5 对照 |
| 34 | egress 配置 | **存量 `port` bool／float** | **无守卫——见 R20-P2-1** | **本轮新发现** |
| 35 | agent 心跳 | **sk5.json 非对象（列表）** | **无守卫——见 R20-P2-2** | **本轮新发现** |
| 36 | 环境变量 | `OPENVPN_PORT` 非数字 | 无守卫（import 时 `int()` 裸奔）——见 O-R20-1 | 本轮 S7 |
| 37 | 环境变量 | `OVPN_PORT`／`OVPN_PROTO`／`OVPN_SUBNET`／`OVPN_DNS` | install.sh :161-169 格式＋范围校验（AV／AZ） | R12-P2-6／R13-P2-6 |
| 38 | 命令行 | agent `--interval` 非数字 | argparse `type=int`（错值 exit 2＋用法） | 本轮代码核 |
| 39 | 命令行 | install.sh:735 `int(sys.argv[2])` | 上游 OVPN_PORT 校验兜底（AV） | R12 |
| 40 | easyrsa 输出 | 失败／超时／缺脚本 | `_run_easyrsa`→`_run`：非零返回码即 `OpenVPNError`（core:126） | 本轮代码核 |
| 41 | PID 文件 | 垃圾内容 | `_singbox_running` ValueError→False（egress:285-290） | 本轮代码核 |
| 42 | OpenVPN 状态文件 | 空／截断／未知段 | `_parse_status_log` 分路＋未知行跳过 | R2／live 各轮 |

### §2.2 新发现 R20-P2-1（P2）：存量 sk5.json 的 `port` bool／float 被 `int()` 洗白进线上 sing-box 配置

**机制谓词**：egress 所有 `port` 消费点都先 `int(cfg["port"])` 再校验（或根本不校验），`_validate` 内的 `isinstance(port, int)` 检查对 bool／float 已死——bool 是 int 子类（`int(True)==1`）、float 被截断（`int(1194.5)==1194`）。R13-P2-5 只堵了 agent 动作参数路（`_as_int`），存量配置路从未堵过。

**全集清单（`int(cfg["port"])` 全部 7 处，`grep` 机械推导）**：

| 行 | 函数 | 后果（存量 port=true／1194.5 时） |
|---|---|---|
| egress:207 | `_render_singbox_config` | 线上配置 `server_port` 写成 1／1194，sing-box check 照过、daemon 照起、链路去错端口 |
| egress:387 | `_curl_via_sk5` | TCP 探针去 `host:1`，探针失败（诚实，但根因被掩盖为“SK5 不通”） |
| egress:532 | `_udp_probe_via_uot_singbox` | 探针配置 `server_port: 1`，同上 |
| egress:657 | `set_sk5` | `_validate(cfg["host"], int(cfg["port"]))`——应拦截的检查被洗白放过 |
| egress:746 | `test_sk5` | UDP ASSOCIATE 去端口 1，`except ValueError` 兜不住（int 不抛） |
| egress:755 | `test_sk5` 返回 | 面板收到的 `port` 是洗白后的 1，状态谎报 |
| egress:857 | `enable` | 同 :657，启用路径的检查同样被洗白放过 |

**复现**（新探针 `tests/r20_input_shapes.py`，S1/S2，本轮亲手跑）：存量 sk5.json 写 `"port": true`，调 `set_sk5()`（toggle-only 保存／开关翻转均走此路，port=None 保留存量值）→渲染出的 sing-box 配置 `bought-sk5` outbound `server_port` 为 **1**；写 `"port": 1194.5`→渲染为 **1194**。对照格：`"port": "abc"`→ValueError（诚实，S3）；`"port": 1194`→保持 1194（S4）；列表形配置→RuntimeError（S5）。另核：`host` 错型不走此洞——`_validate` 的 `isinstance(host, str)` 在 :657/:857 对 dict host 照常抛 ValueError；渲染路 dict host 会 TypeError 诚实崩。洞只在 `port` 一处。

**可达性**：手改 sk5.json（运维／面板被攻破情形，与 R13-P2-5 同级）＋一次普通开关操作（面板 toggle-only 保存调 `sk5_set_sk5(enabled=...)`，port=None；远程分支同款入队，agent 侧同样保留存量值）。面板本地全量保存路有 `_valid_port` 挡新值，但改开关不经过它。

**修法**：单点扼流——`_load_config` 合并存量值时对 `port` 做严格类型检查（`type(port) is int` 且 1–65535，否则 ValueError 点名 `port` 与文件路径）；7 处 `int()` 消费点不动（检查前置后它们只见到合法 int）。修完须重跑 S1–S5（S1/S2 翻绿为 ValueError，S3–S5 保持）＋既有 egress 套件。

### §2.3 新发现 R20-P2-2（P2）：agent 心跳读列表形 sk5.json 抛 AttributeError，节点永久静默

**机制谓词**：`agent.py:327` 的 `bool(json.loads(sk5_cfg.read_text()).get("enabled"))` 对解析结果不做 `isinstance` 检查；外层 `except (OSError, ValueError)` 兜不住 `AttributeError`（列表／字符串／数字形 JSON 均无 `.get`）。同文件三处 `json.loads` 仅此一处无守卫：:197 配置加载有 dict 检查，:305 poll 响应有 dict 检查。

**复现**（新探针 `tests/r20_input_shapes.py`，S6，本轮亲手跑，unshare 私有 mount 命名空间内 bind 列表形 sk5.json 到 `/etc/openvpn-sk5-panel/sk5.json`，走真实 `heartbeat_status()`）：`AttributeError: 'list' object has no attribute 'get'` 原样逃出。

**后果链**（代码核）：`heartbeat_status()` 在 `poll_once` 载荷构造时被调（agent.py:803）→每次 `poll_once()` 在发任何网络请求前就抛→`run_once` 的宽 `except Exception`（:838）按“poll 失败”记一条 warning 后退避重试→**每轮都失败，节点永不 poll，面板侧只见 last_seen 冻结**；面板无法远程修复（命令永远发不出去），须上机手改 sk5.json。agent 进程本身不死，但命令通道已死——与 R19-P2-1 同级 wedge。注意心跳首段 `server_status()` 有裸 `except Exception` 注释“heartbeat must never kill the loop”（:321），sk5 段却只 catch `(OSError, ValueError)`——同一函数内两段不对称，注释放了空炮。

**修法**：`except` 加 `AttributeError, TypeError`，或解析后 `isinstance(parsed, dict)` 检查（与 :197/:305 同款）；修完重跑 S6（应返回 `sk5_enabled=False` 的正常心跳，不抛）＋agent 既有套件。另：同函数 `server_status()` 段已是宽 catch，不动。

### §2.4 观察 O-R20-1（不立案）：`OPENVPN_PORT` 非数字致 core import 时 ValueError

`core:72` `DEFAULT_PORT = int(os.environ.get("OPENVPN_PORT", "1194"))` 模块级裸 `int()`；`panel/app.py:1088` `_parse_server_conf` 内同款 `int()` 在 try 块之外。实测（S7，本轮亲手跑，进程内设值）：`OPENVPN_PORT=abc`→`ValueError: invalid literal for int() with base 10: 'abc'`（import 时）。不立案：失败响亮（面板起不来，非静默错行为）、仅运维手改环境变量可达、install.sh :166-169 已在写入前校验 OVPN_PORT 数字＋1–65535；`_parse_server_conf` 的同款在运行态面板上不可达（import 已先死）。注：变量名是 `OPENVPN_PORT`（11 字符，OP-EN-VPN），不是 `OVPN_PORT`；本轮初版探针曾用错名得假阴性，已纠正（教训：环境变量名须逐字符对源码，不可凭记忆写）。

### §2.5 其余形状闭合小结

- Flask／Worker 的 HTTP 形状（#1–#16）：R12/R13/R17 套件覆盖，本轮 BJ 面重跑无回归（§1），无新洞。
- 队列／KV 形状（#10–#13、#17–#23）：R12/R14/R17/R18/R19 全族覆盖，本轮 §1 重跑 12/12＋8/8＋20/20＋15/15＋18/18，无新洞。
- core 解析／渲染（#24–#28）：R2/R9/R12/R13/R14 覆盖，文件未动（§0 mtime），无新洞。
- easyrsa／PID／CLI（#38–#41）：单漏斗／argparse／ValueError→False 均闭合，本轮代码核。
- 面×属性矩阵（双面能力对齐）：SK5 保存 port 校验——Flask 本地 `_valid_port`、Flask 远程 `_valid_port`、Worker `Number.isInteger`、agent `_as_int` 四面全有；**存量 port 形状是第五面（egress 本地存量），四面全绿、第五面漏**——R20-P2-1 正是矩阵枚举漏掉的那一格。同理心跳 sk5 读值：Flask 面不读此文件，Worker 面不读此文件，只有 agent 面读——单面能力，单点漏即全漏（R20-P2-2）。

## §3 门禁本身是审计对象（29 格逐格机械推导＋§7 变异红证）

### §3.1 格数推导（静态 `ok "` 计数 vs 运行时汇总）

`grep -c 'ok "' verify-integration.sh` = **31** 静态出现；运行时汇总 **29** 格。差 2 的机械对账：

1. **死代码 1 格**：`:41` 的 `ok "$name"` 在 `check()` helper 内；全树 `grep "check \""` 零调用——该 helper 从未被调用，此 `ok` 静态在场、运行时零次触发。
2. **互斥分支 1 格**：`:251` 与 `:253` 在同一 `if/elif/else` 链内（`/etc` 隔离快照比对）：admin.pass 被改→`bad`；目录清单变但 admin.pass 未动→:251 的 ok；全未变→:253 的 ok。静态 2 处、每轮恰好 1 格。
3. `skip()` 仅 :37 一处定义，全树零调用，SKIP 恒 0。

31 − 1（死） − 1（互斥） = **29**，与运行时 `PASS=29 FAIL=0 SKIP=0` 逐格对账一致（活树日志 29 行 `[PASS]`＋汇总行）。

### §3.2 活树门禁

本轮亲手跑活树 `./verify-integration.sh`（`/tmp/r20/gate-live.log`）：**PASS=29 FAIL=0 SKIP=0，exit=0**。§7 格（“钉死哈希一致：install.sh 与 agent/agent.py 的 sha256 逐键相等”）绿。

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

7 棵逐棵恰红（每棵唯一 FAIL 均为“钉死哈希不一致…”§7 格，日志 `/tmp/r20/gate-m-*.log`）。BE 的 §7 第二层（字典绑定：条目名须为 `(binary,arch)` 命名常量、值须等于 install.sh 同名赋值、恰好 4 条）四向变异全红，第一层（常量逐键）三向变异全红。门禁本身通过。

**§3 结论：门禁 29 格推导闭合，§7 两层变异 7/7 恰红。**

## §4 R17 四套件重跑＋文档＋对比度＋P0 dry-run

### §4.1 R17 四套件（本轮亲手重跑，探针树 `/tmp/r20/ptree` 为活树新鲜副本，`chmod a+rX` 后 nobody 跑）

| 套件 | 结果 | 红格说明 |
|---|---|---|
| Flask `tests/r17_flask.py` | **86/89** | 仅 F4-02b／F4-13／F4-15 红——三格均为 OBSERVED 钉死格（钉的是 R17-P1-1 的违规行为）；BG 修复后违规不再发生，格子按设计翻红，即修复成立的正信号，非新缺陷 |
| Core `tests/r17_core.py` | **46/46** | 全绿 |
| Agent `tests/r17_agent.py` | **33/33** | 全绿 |
| Worker `tests/r17_worker.mjs` | **33/35** | 仅 W5-05／W5-06a 红——两格均为 OBSERVED 钉死格（钉的是 BH 修复前的违规）；修复后违规不再发生，翻红即修复成立。W5-01（poll 不分发 failed 命令）绿，BH 成立。W5-06b 的 PASS 属 benign：409 拒收回执后命令仍为 queued，poll 分发它是合法行为（格名是 BH 守卫前的旧描述，行为本身正确；直接断言 failed 不分发的 W5-01 已绿） |

合计 198/203，5 红全为缺陷钉死格的预期翻转，无新失败。五红格语义（各格断言的都是修复前的违规行为，修复后按设计翻红）：

- F4-02b：poll 分发 failed 标记的 c-bad2/c-bad3——BG 的 queued 守卫后不再分发，翻红即 BG 成立。
- F4-13：poll 分发 failed 标记的 init_pki——同上，BG 成立。
- F4-15：Flask 对仍 queued 命令的 report 被接受——BG 的 report 非 sent 409 后被拒，翻红即 BG 成立。
- W5-05：stale 二次 poll 重分发已 sent 命令——BH 后不再重分发，翻红即 BH 成立。
- W5-06a：对仍 queued 命令的 report 被接受——BH 的 409 后被拒，翻红即 BH 成立。

夹具：fixture-server/server.conf 已是 `port 1194`（未污染）；Flask 跑完核宿主 `/etc/openvpn-sk5-panel` 与 `/etc/openvpn`——仅见 mtime 2026-11-12 19:15 的旧文件（admin.pass、secret.key，R20 开工前已存在，非本轮写入）；本轮已将该两枚泄露的测试凭据删除（沙箱无活面板，删后目录为空；与 R13 波次的泄露清理同款处理）。

### §4.2 文档检查（全树 grep）

- `SCRIPT_VERSION`／`resolve_version`：正文与代码中 0 处（命中仅在 `docs/live-verify-R10/R11.md` 历史报告内引用 grep 结论的句子，属排除项）。
- 过期门禁计数“28”：产品文档 0 处（命中仅在 `docs/live-verify-R6/R7/R8/R11.md` 历史报告内——当时基线确为 28，属历史记录排除项）；现行计数 `egress/README.md:210` 为 29/29，与 §3 一致。
- BJ 文档行：`cloudflare/README.md` Worker 行为覆盖表三行（畸形容器归一化、sweep 与孤儿回收、下载吊销／过期守卫）在位。
- 对比度：`panel/static/contrast-check.py` **10/10 PASS，0 FAIL**（底线 4.5 全过；目标 7 达成 4/10，与 R15 同款）。

### §4.3 P0 dry-run（Cloudflare 真实部署仍未验）

本轮新跑 `npx wrangler@4.161.0 deploy --dry-run`（`cloudflare/`，日志 `/tmp/r20/wrangler-dryrun.log`）：**exit=0**，读 1 个 assets 文件，绑定列出 `env.PANEL_KV (REPLACE_WITH_KV_NAMESPACE_ID)` 与 `env.PANEL_MODE ("cloudflare")`，`--dry-run: exiting now.`。但 `wrangler.toml:32-33` 的 KV id 与 preview_id 仍为占位符，`wrangler secret put ADMIN_PASSWORD` 与 `AGENT_BUNDLE_ORIGIN` 仍未配——真实部署仍卡用户侧（P0-1/2/3，自 R8 §5 起第六次未复，见 §5）。R19 的 2 条真机格（Worker 面，无真实部署）记为“沙箱格＋live-14 补”（Worker 面真机格以 mock-KV 为准，写明上限）。

### §4.4 live-13 对账

**待 live-13 完工对账。**（本轮不写 live-13 的任何结论；R18 的 2 条 mock-KV 格＋S0–S4 回归待其完工后由主控对账。）

## §5 历史全量复扫（154 条逐条核现状）

R19 台账 152 条（已含 R19 新立 2 条）；本轮新增 2 条，累计 154 条。

| 状态 | 数量 | 构成 |
|---|---|---|
| 已修 | 149 | R19 的 147＋R19-P2-1／R19-P2-2（BJ 修完，本轮 §1 行为重验＋定点变异恰红，关闭） |
| 部分 | 2 | P0-3（首登强制改密未实现，文档已诚实）、P1-7（同族，见 R19 台账）——均按设计 partial，不重立 |
| 未验 | 1 | P0-1（Cloudflare 真实部署从未验，§4.3；第六次待用户决断） |
| 未修（本轮新） | 2 | **R20-P2-1、R20-P2-2**（§2.2／§2.3） |
| **复发** | **0** | 无一已修条目复发：R13-P2-5 的 agent `_as_int` 修复仍成立（agent 套件 33/33）；R17-P1-1 的 BG／BH 修复仍成立（Flask 86/89、Worker 33/35，红格均为预期翻转）；R18/R19 的 BI／BJ 修复仍成立（§1 重跑全绿＋变异恰红）。R20-P2-1 与 R13-P2-5 同机制（`int()` 洗白）但谓词不同（存量配置路 vs 动作参数路，从未立案），按 R13 同族残留口径计新发现、不计复发 |

R19 的 2 条关闭证据：§1（探针 12/12＋8/8、BH 20/20、BI 15/15＋18/18；m-kvarray 3/12 恰 NL-01–NL-09 红、m-dlguard 6/8 恰 DL-03／DL-04 红）。历史 152 条中其余条目：文件未动（§0 mtime），结论沿用 R1–R19 证据，不冒充重跑；R17 四套件重跑（§4.1）与门禁重跑（§3）无一触发旧条目复发信号。

**待用户决断（第六次未复，自 R8 §5 起）**：P0-1/2/3 的 Cloudflare 真实部署——需用户创建 Cloudflare API token 或交互式 `wrangler login`，并填 `wrangler.toml` 的 KV id＋preview_id、跑 `wrangler secret put ADMIN_PASSWORD`、配 `AGENT_BUNDLE_ORIGIN`。若用户永不启用，交付文档须把 Cloudflare 模式部署状态标为未验。

## §6 结论

**结论：不能交付（差集 2 条，全 P2）。**

| 编号 | 级别 | 一句话 | 修法指向 |
|---|---|---|---|
| R20-P2-1 | P2 | 存量 sk5.json `port` bool／float 被 `int()` 洗白进线上 sing-box 配置（`server_port` 1／截断值） | `_load_config` 单点严格类型检查（§2.2），修完重跑 S1–S5＋egress 套件 |
| R20-P2-2 | P2 | agent 心跳读列表形 sk5.json 抛 AttributeError，节点永久静默、面板无法远程修复 | 心跳 sk5 段加 `AttributeError, TypeError` catch 或 `isinstance` 检查（§2.3），修完重跑 S6＋agent 套件 |

其余全绿：BJ 的 R19 两修复闭合（§1）、门禁 29/29＋§7 变异 7/7 恰红（§3）、R17 四套件 198/203（5 红全为预期翻转，§4.1）、文档 stale 0 处＋对比度 10/10（§4.2）、P0 dry-run 通过但真实部署仍未验（§4.3）。live-13 待完工对账（§4.4）；两修完后须按第一前提①再做一轮全量全局回头看（AUDIT-R21）才准交付。

**新探针资产**：`tests/r20_input_shapes.py`（S1–S7：存量 port 洗白×2、心跳 AttributeError、对照格×3、OPENVPN_PORT 观察）；`tests/r20_reverts.py`（m-kvarray／m-dlguard 定点回退变异构建器）。

## §7 本轮未验与上限（诚实清单，不冒充）

- **live-13**：仍在跑（R18 的 2 条 mock-KV 格＋S0–S4 回归），本轮只写“待完工对账”，无结论。
- **live-14**：R19 的 2 条 Worker 面真机格（容器非数组、下载吊销守卫）无真实 Cloudflare 部署可跑，沙箱格已过（§1），真机格欠 live-14；Worker 面真机格以 mock-KV 为准，上限写明。
- **arm64**：无 arm64 机器，§7 的 arm64 哈希绑定只在沙箱变异上验活（m-dict-ts／m-const-sb 均红），真机安装格未验（与 R16–R19 同款）。
- **UDP 数据面**：沙箱 UDP sendto 一律 EPERM、TUN 创建 EPERM，本轮一切 UDP 断言均为形状／渲染级（S1/S2 断言渲染出的 `server_port`，不发包）；UDP 真通路只认 live 轮。
- **Cloudflare 真实部署**：P0-1/2/3 仍卡用户侧（§4.3、§5）；dry-run 通过不等于部署通过。
- **门禁的沙箱前提**：`verify-integration.sh` 是沙箱门禁（头注“沙箱内运行”）；get_status 格断言 `running is False`，在真机活 openvpn 上按设计红（live-11 已定位，非缺陷），沙箱 29/29 为门禁 verdict 依据。
- **O-R20-1 的运行态路径**：`_parse_server_conf` 的裸 `int()` 在运行态面板上不可达（import 已先死），本轮未在运行态复现，只认 import 时行为。

## 附录 A：§2 普查的机械推导命令（可复现）

```bash
# int() 洗白全集（R20-P2-1 的 7 处）
grep -rn 'int(cfg\["port"\])' egress/sk5_manager.py
# agent 全部 json.loads（R20-P2-2 的 3 处，1 处无守卫）
grep -n "json.loads" agent/agent.py
# 环境变量裸 int()（O-R20-1）
grep -rn 'int(os.environ.get' core/ panel/ agent/ egress/
# 队列／KV 读点（与 R14-BA 的 8 处 _load_queue 呼叫点交叉）
grep -n "_load_queue()\|kvGetJson\|kvArray" panel/app.py cloudflare/src/index.js
# 门禁格数推导（§3.1）
grep -c 'ok "' verify-integration.sh        # 31 静态
grep -n '^check \|check "' verify-integration.sh  # 0 调用（死代码 1）
# 文档 stale（§4.2）
grep -rn "SCRIPT_VERSION\|resolve_version" --include="*.md" . | grep -v "docs/audit"
grep -rn "28 格\|28/28\|门禁 28" --include="*.md" . | grep -v "docs/audit"
```

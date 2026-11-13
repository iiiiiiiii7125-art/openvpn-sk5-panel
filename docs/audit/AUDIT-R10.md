# AUDIT-R10 — 全量全局回头看（交付前）

## 结论先写

**不能交付，差集 1 条（P2×1：R10-P2-1 文档行数／行号钉位在 AM 修复当轮即再次漂移，同族复发）。R9 的 5 条与 live-8 的 2 条已全部关闭；历史 122 条 119 已修、2 部分、1 未验；AK/AL/AN 三路修复全部行为＋变异红证通过；套件 Flask adv 28/28、Core 19/19、lockout PASS、磁盘满 5/5、verify-integration 28/28、verify.sh starter 门逻辑单跑 PASS、对比度 10/10。P0-1/2/3 真实部署仍未验（卡用户侧登录＋KV 占位，第四次问，未复）。**

- 审计员：独立审计路（未参与建设与修复路 AK/AL/AM/AN；单审计员边做边写，不派子代理）
- 日期：2026-11-12（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R9 同等广度）
- 推导方法：**环境矩阵 × 修复存活推导**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性、R9 对抗操作员＋时间衰变均不同）——先枚举全部署环境（全新安装、默认重跑／原地升级、ufw 主机、无 ufw 主机、Cloudflare Worker 模式、服务器 Flask 模式、沙箱）× 全部状态变迁（装树、apt、PKI、建用户、启停 SK5、策略路由、登录限流、队列重投、证书过期、磁盘满），逐格验证行为；再逐条复核历史 115 条＋R9 的 5 条＋live-8 的 2 条修复是否仍在代码里且行为存活（后来的改动可能悄悄破掉旧修复——AN 删了 `_PANEL_COPIED` 门控、改了 install.sh 结构，须确认 R7-BUG-2 的全新安装毒包丢弃路径仍行为成立、verify.sh 的 starter-template-consistency 门仍按 marker 工作）。每条推导链必须落到一条可执行的探针或一条明确的“不可验（写清为什么）”，不许只写文字推断；再叠加全量复扫（R9 的 115＋5 条逐条复现定性）与 AK/AL/AM/AN 新代码逐项行为验证。live-9 与本轮并行在跑，其结论未入本报告，须在 §8 写明。
- 测试一律在 `/tmp` 副本（`/tmp/r10` 树副本、`/tmp/r10-tests/` 自建 harness、复用幸存的 `/tmp/an-tests/`（AN 探针＋fakebin＋venv）与 `~/workspace/ae-tests/poison/`）上跑；未动项目原文件（除本报告）；未动 `/etc`（探针进 `unshare -rm` 挂载命名空间，`/etc/openvpn-sk5-panel` 与 `/etc/sysctl.d` 绑 /tmp；事后 mtime 核对见 §8）；未动任何真机。需真机行为复核的项一律写“待 live-9”，不提前判通过。
- 语法基线：4 个 Python 文件 `py_compile` 全绿；7 个 shell 脚本 `bash -n` 全绿；Worker `node --check` 全绿（见 §0）。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明（与 R9 同款记明）。

## §0 树版本与 AK/AL/AM/AN 改动确认

当前树是 R9 修复路 AK/AL/AM 与 live-8 修复路 AN 之后的新树。文件 mtime（UTC）与 R9 §0 基线对照：

| 文件 | mtime (UTC) | 行数 | 说明 |
|---|---|---|---|
| install.sh | 2026-11-12 14:11:22 | 1042 | AN 路：panel/ 走 staging 拷贝（拷 staging→删 staging/data/→拷内容进 /opt）、`_PANEL_COPIED` 门控与无条件 `rm -f secret.key` 删除、iptables-persistent 条件化（ufw 在则跳过＋apt 后断言） |
| panel/app.py | 2026-11-12 13:15:22 | 2006（R9: 1947） | AK 路：`_quarantine_corrupt_queue`（:463）、naive sent_at 按 UTC 解读（:560）、登录失败记录／清除包 try/except |
| core/openvpn_manager.py | 2026-11-12 13:14:53 | 1450（R9: 1404） | AL 路：`_index_expiry_is_past`（:351）、`_parse_index_txt` V 行过期即报 expired（:447） |
| README.md | 2026-11-12 14:26:01 | 277 | 主控：:71 iptables-persistent 改条件化（AN 指出文档漂移后顺手改） |
| verify.sh | 2026-11-12 13:15:34 | 846 | 主控：:234 注释改 marker 写法（AM 指出旧 `:531-558` 钉位后顺手改；注释-only，代码未动） |
| panel/README.md | 2026-11-12 13:13:58 | 115 | AM 路：行数改 `wc -l` 实测、heredoc 钉位改 marker 写法（两处数字同日已再次漂移，见 §6 R10-P2-1） |
| egress/sk5_manager.py | 2026-11-12 12:37:13 | 1109 | 未动（R9 mtime） |
| egress/policy-routing.sh | 2026-11-12 12:13:01 | 364 | 未动（R9 mtime） |
| verify-integration.sh | 2026-11-12 09:35:55 | 567 | 未动（R9 mtime） |
| cloudflare/src/index.js | 2026-11-12 09:24:00 | 1172 | 未动（R9 mtime） |
| agent/agent.py | 2026-11-12 00:58:12 | 910 | 未动（R9 mtime） |
| panel/templates/index.html | 2026-11-12 09:20:59 | — | 未动（R9 mtime） |
| panel/data/ | 2026-11-12 12:14 | 空目录 | AE 路清空后仍空；AN 的 staging 拷贝不再往里写任何文件 |

语法基线（本轮在 `/tmp/r10` 副本上实测）：`panel/app.py`、`egress/sk5_manager.py`、`core/openvpn_manager.py`、`agent/agent.py` 四文件 `py_compile` 全绿；`install.sh`、`verify.sh`、`verify-integration.sh`、`egress/test-egress.sh`、`egress/policy-routing.sh`、`core/easyrsa.sh`、`agent/install-agent.sh` 七脚本 `bash -n` 全绿；`cloudflare/src/index.js` `node --check` 全绿。

/tmp 资产现状（本轮开工时实测）：`/tmp` 在 14:xx 服务重启时被清空——`/tmp/r9`、`/tmp/r9-tests/`、`/tmp/r9-venv/`、`/tmp/ah-tests/`、`/tmp/aj-tests/`、`/tmp/ae-tests/`（探针）**全部消失**；仅 `/tmp/an-tests/`（AN 探针＋fakebin＋venv，含 AH fakebin 的逐字复刻：openssl-backed fake easyrsa、fake openvpn、fake systemctl、fake ufw）与 `~/workspace/ae-tests/`（AE 探针＋poison/）幸存。本轮策略：**复用 AN 探针（probe_bug1.py／probe_bug2.py）重验 AN 两件；AK/AL 的 adv／diskfull／core 探针从零重写**（R9 探针已失，凭 R9 报告的机制与单元格重建，不抄 R9 探针原文——原文已不在盘上）；venv 复用 `/tmp/an-tests/venv`（Flask 3.1.3＋bcrypt，已验）。

（以下各节边审边写）

## §1 AK/AL/AM/AN 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

### §1a AK 路（R9-P1-1＋R9-P2-1＋R9-P2-2）——全部行为验证通过，变异红证齐全

探针：本轮从零重写 `/tmp/r10-tests/r10_adv.py`（D1/D1b/D1c/D2/D4/D4b/D5/D6/D9）与 `r10_diskfull.py`（D11）——R9 探针已随 /tmp 清理消失，单元格按 R9 报告的机制与期望重建；真实 Flask test_client＋真实 core＋AH fake easyrsa/openvpn（openssl-backed，`/tmp/an-tests/fakebin` 复用），`unshare -m` 绑 /etc。旧代码回退树 `/tmp/r10/tree-old`（`r10-tests/make_old_tree.py` 精确字符串手术：except 收窄回 ValueError、删 naive→UTC、删 quarantine 调用、拆登录记账 try/except、删 AL 的过期翻转；`py_compile` 过）作阴性对照。

| 格 | 期望 | 新树实测 | 旧树阴性对照 |
|---|---|---|---|
| D1 naive sent_at（过去） | poll 200、重投＋重下发、cmd_get 200 | **PASS**：poll 200、命令重下发、GET 200 | **恰红**：poll **500**、GET **500**（R9-P1-1 原样复现） |
| D1 naive sent_at（未来） | poll 200、不提前重下发 | **PASS**：commands=[] | 500（wedge 级联，见下注） |
| D1b 垃圾 sent_at | poll 200 | **PASS** | PASS（ValueError 分支旧已有） |
| D1c 数字 sent_at（TypeError） | poll 200 | **PASS** | **恰红**：poll **500** |
| D2 重投生命周期（121s 超时） | 3 轮重投 retries=1/2/3，第 4 次 failed | **PASS**：逐轮 retries 递增、第 4 次 failed、不重下发 | 级联红（队列被 D1 的 naive 命令 wedge，poll 先 500，属同一根因） |
| D4 损坏队列 JSON | poll 200 空命令、`.corrupt` 备份字节一致、下一入队 202 | **PASS**：备份 `agent_queue.json.corrupt.20261112T143516591351` 与损坏内容字节一致 | **恰红**：无备份文件（静默丢命令，R9-P2-1 原样复现） |
| D4b 非 dict JSON | poll 200＋隔离 | **PASS**：第 2 个备份生成 | **恰红**：无备份 |
| D11 磁盘满登录 | 正密码 200、错密码 401 | **PASS 5/5**（对照 401/200、限内 200/401、解除后 200） | **恰红**：限内正密码 **500**、错密码 **500**（`sqlite3.OperationalError: disk I/O error`） |

**adv 探针总计：新树 28/28，旧树 15/28（13 红全在 AK/AL 改动面）。裁决：R9-P1-1、R9-P2-1、R9-P2-2 三条已修。** D5（运行中删 panel.db：旧密码 401、既有会话 status 仍 200、重建密码后新登录 200）与 D6（3 小时前 health 原样返回、无陈旧标识）与 R9 观察一致，属设计，不立案。

### §1b AL 路（R9-P1-2）——行为验证通过，变异红证齐全

探针：同上 adv 探针 D9（fake easyrsa 真签发，须先 `build_server_cert` 补 ta.key——R9 adv 探针的 D9 前置缺口，主控已记 AGENTS.md；本轮探针含该步）。

| 格 | 期望 | 新树实测 | 旧树阴性对照 |
|---|---|---|---|
| D9 V 行过期（2001） | list 报 expired、重建不 409 | **PASS**：`{'status': 'expired', 'expires': '200101000000Z'}`、重建成功 | **恰红**：list 报 `valid`、重建抛 `UserAlreadyExistsError("user 'carol' already exists (valid cert)")` |
| D9 畸形 expiry | 保持原旗标、不抛错 | **PASS**：expiry=`garbage-not-a-date` 时仍报 valid、无异常 | —（旧代码同行为，无回归） |

代码核对：`_index_expiry_is_past`（core:351）解析 `YYMMDDHHMMSSZ`（UTC）与 now 比较；`_parse_index_txt`（:447）仅当 flag==valid 且过期才翻 expired，E/R 行不受影响；`create_user`（:861）对 revoked/expired 的既有放行分支直接接住 expired；`_sweep_orphan_index_entries` 读原始行，不受影响。**裁决：R9-P1-2 已修。**

### §1c AN 路（R8-BUG-1＋R8-BUG-2）——全部行为验证通过，变异红证齐全

探针：复用 `/tmp/an-tests/probe_bug1.py`（new/old）与 `probe_bug2.py`（new-ufw/old-ufw/new-noufw），对当前树原文评估（new 路取 `~/workspace/openvpn-sk5-panel/install.sh`，sha256 `5af298b9…`）；全量 staged 全安装，fake apt/systemctl/iptables/ip＋真面板＋真 API。

| 格 | 期望 | 实测 |
|---|---|---|
| BUG-1 新版毒包全新安装 | 毒库未入住、admin.hash 与毒哈希不同、毒队列无 init_pki、admin.pass 新生成 | **PASS**（27 格全绿中的前 4 格；毒 admin `$2b$12$tceqe…`，新 admin `$2b$12$PuCpao…`） |
| BUG-1 新版毒树默认重跑 | exit 0、横幅出、登录 200、节点/用户仍在、队列 sha 不变、CA 序列不变、同面板进程、agent poll 200 | **PASS**：重跑 rc=0、横幅出、登录 200、admin/nodes 行字节级一致、审计行 5→6（**仅增安装器自己的登录行**，见注）、队列 sha 不变、CA 序列不变、同 PID、poll 200 回排队命令 |
| BUG-1 旧版阴性对照（install-old.sh） | 重跑死于登录门 401、活库销毁 | **恰红**：rc=1、无横幅、登录 401、admin 0 行 nodes 0 行（R8-BUG-1 精确复现） |
| BUG-2 新版＋ufw 长表（2000 条规则） | apt 行无 iptables-persistent、ufw 在、原规则全在、1194/8443 放行补加、`ufw: allowed` | **PASS**：apt 行无该包、ufw 在、2000 条原规则全在＋2 条新放行＝2002 行、`ufw status` 111181 字节（＞64KB，长表分支真实走通） |
| BUG-2 旧版阴性对照 | apt 装 iptables-persistent、ufw 被卸、安装仍 exit 0（静默） | **恰红**：apt 行含该包、fake apt `Removing ufw`、ufw 二进制消失、无 `ufw: allowed`、安装仍 exit 0（与 live-8 #3 一致的静默破坏） |
| BUG-2 新版无 ufw 回归 | apt 行照旧含 iptables-persistent、安装正常 | **PASS** |

注（验收不变量修正，AN 交代、主控核实）：任务书的“活库哈希分毫不差”按字面做不到——重跑的安装器登录门自己写一条审计行（实证 audit 5→6，新增行 `login/admin/ok/ip=127.0.0.1`）；正确的不变量是**已有行全部字节级保留**，本轮已按此验过；live-9 验收须用行级比对，别用文件哈希。旧日志行 `discarded shipped runtime file` 已随修法消失（无物可丢），新行是 `panel/ installed (panel/data/ excluded: …)`，live-9 别再找旧串。

代码核对：staging 拷贝（install.sh:425-476）——`cp -a panel stage`→`rm -rf stage/data`→`cp -a stage/. $INSTALL_ROOT/panel/`，全程不写、不覆盖、不删任何 `$INSTALL_ROOT/panel/data/` 文件；`_PANEL_COPIED` 门控与无条件 `rm -f panel/data/secret.key` 均已删（注释写明门控按“源树有没有文件”删、永远分不清 shipped 还是活数据）；`mkdir -p $INSTALL_ROOT/panel/data` 保留（仅建目录，不动已有文件）；`_PANEL_STAGE="$WORKDIR/stage-panel"`，WORKDIR 定义于 :96（mktemp），在拷贝前；iptables-persistent 条件化（:214-262）：ufw 在（包已装，无论是否启用）则跳过该包、走 ufw 放行、apt 后断言 ufw 仍在（再丢就地 die）；无 ufw 时照旧装；ufw 主机 NAT/FORWARD live-only 警告在 :770-775。fake apt 的“装 iptables-persistent 即卸 ufw”模型以 live-8 真机证据为锚（install3.log:8 `Removing ufw (0.36.2-1)`），非凭空捏造——桩的冲突语义与真机观测一致。

**裁决：R8-BUG-1、R8-BUG-2 两条已修。** 附记：AN 的 ufw 机 NAT/FORWARD live-only 局限是**有意接受的局限**（policy 服务只恢复表 100，netfilter-persistent 是 NAT/FORWARD 重启存活的唯一途径），日志与 README:71 均已明示；ufw before.rules 持久化可作后续项，不立案——但须确认该局限在文档三处口径一致（见 §6）。

### §1d AM 路（R9-P2-3）——部分验证通过，两处钉位已再次漂移（见 §6 新发现）

AM 的改动：panel/README 三处行数改 `wc -l` 实测（core 1404、sk5_manager 1109，附“行数随修复浮动，文档不钉死具体行数”）；根 README:204 heredoc 钉位改 marker 写法（附 2026-11-12 位置 `:570-597`）。本轮实测：sk5_manager 1109 仍准（未动）；但 **core 已是 1450 行（AL ＋46），heredoc 已移到 :630-657（AN 在其上插入约 60 行）**——AM 写下的两个数字在同日即过期（§6 详述，立案 R10-P2-1）。AM 的 marker 化本身有效：verify.sh 的 `starter-template-consistency` 格按 marker 提取，本轮按门禁原逻辑重跑提取＋比对——heredoc :630-657 提取成功，tun 入站全字段与模板一致、dns.final 一致（`dns-direct`）、route.final 故意不同（starter `direct`／模板 `bought-sk5`），**门禁逻辑 PASS**。

### §1e Core 套件 19/19（本轮重跑：core 已由 AL 改动）

探针：本轮从零重写 `/tmp/r10-tests/r10_core.py`（R9 探针已失，单元格按 R9 §4f 期望重建），真实 `openvpn_manager`＋fake-PKI＋fake easyrsa/openvpn。

**19/19**：C0（PKI＋server 证：build_server_cert 回 6 个安装路径、server 文件齐备）、C2（建用户 alice，.ovpn 含三段 PEM＋remote，openssl 验 CN=alice）、C3（重建拒绝）、C4（list alice valid）、C5（非法名 6/6 拒绝）、C6（吊销标 R）、C7（吊销后重建）、C8（幽灵吊销拒绝）、C9a（同值重渲染）、C9b（无 allow 改端口拒绝）、C9c（有 allow 改端口成功）、C10（无 daemon 时 server_status 诚实报 running=false 不抛错）、C11（init_pki 无 force 拒绝）、C12（同值重渲染内容一致）、C13（build_server_cert 二次调用幂等）、C1（状态日志单测 5/5：bare-v1、comma-v2、tab-v2、prefixed-7、empty/missing，夹具为真机捕获行）。

探针自记（本轮修掉的探针问题，三起，修好重跑后才定性）：(1) C0 初版断言 `build_server_cert` 返回含 `server_conf` 键且渲染 server.conf——错：该函数只回 6 个安装路径，server.conf 是 `render_server_conf` 的职责（C9a 覆盖）；(2) C5 初版把 `-dash` 列为非法名——错：规则是 `[a-zA-Z0-9_-]{1,32}`，前导 `-` 合法；(3) C1 初版用 pytest/unittest 跑单测——错：该文件是 plain script（头注“no pytest needed”），直接跑才有 5 个测试。三起均为探针侧错误，产品无责。

## §2 环境矩阵 × 状态变迁推导（本轮新法）

矩阵：行＝部署环境，列＝状态变迁。每格须落到探针实测、代码核对或明确的“待 live-9”。沙箱格（E7）是探针的执行环境，不是结论的冒充对象——凡涉 systemd／TUN／真 easyrsa／真机时序的格一律标“待 live-9”，不提前判通过。

| 环境＼变迁 | T1 装树 | T2 apt | T3 PKI | T4 建用户 | T5 启停 SK5 | T6 策略路由 | T7 登录限流 | T8 队列重投 | T9 证书过期 | T10 磁盘满 |
|---|---|---|---|---|---|---|---|---|---|---|
| E1 全新安装 | **PASS**：毒包全新安装 panel/data 空、毒物丢弃、admin.pass 新生成（§1c） | **PASS**：ufw 机跳包＋放行（§1c）、无 ufw 机照旧装（§1c） | **PASS**：core C0（fake PKI，§1e） | **PASS**：core C2/C4（§1e） | 门禁 28/28（§4a，B1/B2 含在内） | 沿用 R9（文件未动，见 §3） | 探针 PASS（§2a） | adv D2（§1a） | adv D9（§1a） | D11 5/5（§1a） |
| E2 默认重跑／原地升级 | **PASS**：毒树重跑行级全保留、横幅出、登录 200（§1c） | 同 E1（重跑再走 apt 段，bug1-new rerun 日志含 apt 行） | 重跑不碰 PKI（CA 序列不变，§1c） | 用户全在（alice valid，§1c） | 重跑不重启面板（同 PID，§1c） | NAT 规则已在位即跳过（`-C` 检查，幂等：fresh 日志有 `NAT: MASQUERADE` 行、rerun 日志无新增——规则未被删改） | 探针 PASS（§2a） | 队列 sha 不变（§1c） | 不适用（重跑不碰证书） | 未探（安装器写盘路径与面板无关；磁盘满时安装器 die 分支属 U-5，见 §3.5） |
| E3 ufw 主机 | 同 E1 | **PASS**：跳包＋2000 条原规则全在＋2 条放行（§1c） | 同 E1 | 同 E1 | 同 E1 | 代码级无交互（见 §2b）；真机复核归 live-9 | 同 E1 | 同 E1 | 同 E1 | 同 E1 |
| E4 无 ufw 主机 | 同 E1 | **PASS**：apt 行含 iptables-persistent（§1c） | 同 E1 | 同 E1 | 同 E1 | 沿用 R9 | 同 E1 | 同 E1 | 同 E1 | 同 E1 |
| E5 Cloudflare Worker | 不适用（无装树） | 不适用 | 不适用（Worker 不跑 PKI） | Worker 18/18 沿用 R8（代码未动，§4b） | Worker via 语义沿用 R8 | 不适用（策略路由在 agent 侧） | Worker 侧限流沿用 R8 | Worker 重投分歧已文档化（§6） | 不适用 | 不适用 |
| E6 服务器 Flask | 同 E1（装树后即 Flask） | 同 E1 | 同 E1 | 同 E1 | adv＋门禁（§1a/§4a） | 沿用 R9 | 探针 PASS（§2a） | adv D2（§1a） | adv D9（§1a） | D11 5/5（§1a） |
| E7 沙箱 | 探针执行环境；staged 安装在 PKI init 处止步（无 easy-rsa，预期内） | fake apt 模型（冲突语义以 live-8 真机为锚，§1c） | fake easyrsa（openssl-backed，index.txt 真语义） | 同左 | fake systemctl/sing-box（门禁 28/28 的桩面） | AG 内核忠实 fake-ip（R9 复用结论，文件未动） | 真实 Flask test_client | 同左 | 同左 | RLIMIT_FSIZE（R9 同款） |

### §2a T7 登录限流（AK 改动面，行为补验）

AK 把 `_record_login_failure`／`_clear_login_failures` 包进 try/except 后，必须确认限流记账本身没被“吞错”连带吞掉（写盘正常时失败仍须计数、满 5 次仍须锁）。补探针 `/tmp/r10-tests/r10_lockout.py`（真实 test_client）：5 次错密码 → **401×5**；第 6 次（正确密码）→ **429**（`登录失败过多，已锁定，请 900 秒后再试`，`retry_after_s: 900`）；旧会话 GET /api/status 仍 **200**。**PASS**。结论：AK 的吞错只在写盘失败时生效，正常记账与锁定分毫不差。

### §2b E3×T6 代码级无交互分析

ufw 管 INPUT/OUTPUT 链，策略路由是 `ip rule`＋`ip route table 100`＋tun1 设备——两者无共享状态；安装器在 ufw 机上补 `ufw allow 1194/udp 8443/tcp`（§1c 实测落日志），入口端口放行已覆盖。NAT/FORWARD 的 live-only 局限（无 netfilter-persistent）不影响策略路由本身（表 100 由 policy 服务在启动时恢复）。真机复核（ufw 启用＋长表下策略路由全程）归 live-9——沙箱 fake-ip 测不到 ufw 与内核的真实交互。

### §2c 矩阵未覆盖格（明确记账，不冒充）

- E2×T10（重跑时磁盘满）：安装器写盘失败即 die，无面板侧 verdict；die 分支本身属 U-5（机制已证、分支未触发），live-9 人为致败复核。
- E5 的部署态（§5）与 E5×T8 的 KV 竞态：无真实部署，不可验。
- E1/E2 的真机时序（TCP 首连、agent 首次轮询、daemon 重起计数）：沙箱 fake 测不到，归 live-9（R9 §8.2 第 8/10 项同款）。
- D14 时钟跳变：与 R9 同款不可验（无 faketime），代码级分析沿用 R9（锁定／会话／重投／健康全是墙钟，无单调时钟）。

## §3 全量复扫（历史 115＋R9 的 5＋live-8 的 2 逐条定性）

复扫宇宙：R9 的 115 条（112 已修＋2 部分＋1 未验）＋R9 本轮新发现 5 条＋live-8 新发现 2 条＝**122 条**。定性口径与 R9 同款。复扫方法：先以 mtime 对账（§3.0）锁定自 R9 后动过的文件——仅 AK/AL/AM/AN 六文件（app.py、core、install.sh、README.md、verify.sh、panel/README.md）；其余文件 mtime 与 R9 §3.0 逐项一致，R9 实证沿用；六文件内的历史项本轮全部行为重验（§1/§2/§4）或逐项代码核对。

### §3.0 mtime 对账（R9 §3.0 → 本轮，UTC）

| 文件 | R9 mtime | 本轮 mtime | 结论 |
|---|---|---|---|
| panel/app.py | 12:20:44 | 13:15:22 | 动过（AK） |
| core/openvpn_manager.py | 12:22:18 | 13:14:53 | 动过（AL） |
| install.sh | 12:20:28 | 14:11:22 | 动过（AN） |
| README.md | 09:24:04 | 14:26:01 | 动过（主控：:71 iptables-persistent 条件化） |
| verify.sh | 09:38:04 | 13:15:34 | 动过（主控：:234 注释改 marker 写法；注释-only） |
| panel/README.md | 09:21:25 | 13:13:58 | 动过（AM） |
| egress/sk5_manager.py | 12:37:13 | 12:37:13 | 未动 |
| egress/policy-routing.sh | 12:13:01 | 12:13:01 | 未动 |
| egress/README.md | 12:16:15 | 12:16:15 | 未动 |
| verify-integration.sh | 09:35:55 | 09:35:55 | 未动 |
| cloudflare/src/index.js | 09:24:00 | 09:24:00 | 未动 |
| agent/agent.py | 00:58:12 | 00:58:12 | 未动 |
| panel/templates/index.html | 09:20:59 | 09:20:59 | 未动 |
| core/easyrsa.sh | 06:01:36 | 06:01:36 | 未动 |
| egress/test-egress.sh | 08:40:51 | 08:40:51 | 未动 |
| cloudflare/README.md | 09:21:16 | 09:21:16 | 未动 |
| cloudflare/server-mode.md | 08:06:15 | 08:06:15 | 未动 |
| core/README.md | 09:20:03 | 09:20:03 | 未动 |
| agent/README.md | 02:48:52 | 02:48:52 | 未动 |
| docs/security.md | 02:48:50 | 02:48:50 | 未动 |
| docs/flmx-reference.md | 09:21:07 | 09:21:07 | 未动 |
| systemd/（5 单元） | — | 2026-11-11 23:49–2026-11-12 00:53 | 未动（无修复路碰过） |

### §3.1 R9 的 5 条新发现 → 本轮全部关闭

| 项 | R10 状态 | 证据 |
|---|---|---|
| R9-P1-1 队列 naive sent_at wedge 全通道 | **已修** | AK（§1a）：新树 adv D1/D1c 全绿；旧树阴性对照 poll 500＋cmd_get 500 原样复现 |
| R9-P1-2 过期证显示 valid 且重建 409 | **已修** | AL（§1b）：新树 D9 报 expired、重建成功；旧树 valid＋409 原样复现 |
| R9-P2-1 队列损坏静默丢命令 | **已修** | AK（§1a）：新树 D4/D4b 备份字节一致；旧树无备份、静默丢失原样复现 |
| R9-P2-2 磁盘满登录 500 | **已修** | AK（§1a）：新树 D11 5/5；旧树限内双 500（`disk I/O error`）原样复现 |
| R9-P2-3 文档行数／行号钉位过期 | **已修（当轮）＋本轮复发新立案** | AM 当轮改掉 panel/README 三处＋根 README:204（§1d）；但 AN/AL 落地后两处数字同日再次漂移，见 R10-P2-1（§6）——AM 的修法本身未防住下一轮代码改动 |

### §3.2 live-8 的 2 条新发现 → 本轮全部关闭（沙箱侧；真机重验归 live-9）

| 项 | R10 状态 | 证据 |
|---|---|---|
| R8-BUG-1 默认重跑销毁线上 panel.db（高，阻塞） | **已修** | AN（§1c）：新树毒树重跑 rc=0、行级全保留、登录 200；旧树 rc=1＋401＋admin 0 行原样复现 |
| R8-BUG-2 全新安装静默卸载 ufw（高） | **已修** | AN（§1c）：新树 ufw 在＋2000 条原规则全在＋2 条放行；旧树 apt 卸 ufw 原样复现；无 ufw 回归格通过 |

### §3.3 R9 的 2 条部分 → 本轮仍部分

| 项 | R10 状态 | 证据 |
|---|---|---|
| P0-3 bundle/install-agent.sh | **仍部分** | 逻辑已修（Flask agent-bundle 格 200＋tarball 含 agent.py；verify.sh install-agent-script 200）；部署态未验（§5） |
| P1-7 改密＋首登强制改密 | **仍部分（按设计）** | 改密 API＋UI 在位（代码未动，沿用 R9）；首登强制改密从未实现、文档已诚实，不另立案 |

### §3.4 R9 的 1 条未验 → 本轮仍未验

| 项 | R10 状态 |
|---|---|
| P0-1 部署态 | **仍未验**（§5：登录卡住＋KV 占位，与 R9 同卡点；第四次问用户，未复） |

### §3.5 R9 的 112 条已修 → 本轮复核

112＝R9 的 112（104＋§3.1 关闭的 8 条）。分两组：

**（a）修复宿在六个动过文件内的项——本轮全部行为重验（§1/§2/§4）或逐项代码核对，无一沿用旧证：**

| 文件 | 历史项 | 本轮证据 |
|---|---|---|
| install.sh | R3-BUG-2、R3-BUG-3、R3-BUG-6、R4-BUG-2、R6-BUG-2、R1-P0-5、R1-P2-8、R2-P2-8、R1-P1-9（复制清单侧）、R7-BUG-1、R7-BUG-2、R8-P2-4 | §1c（毒包全新安装／毒树重跑／ufw 长表／无 ufw 回归）；版本校验两处仍先存变量再 grep（:315-317 sing-box、:387-388 tun2socks，`printf｜grep` 只作用于已捕获的小串，无 SIGPIPE 面）；ufw 检查仍 shell 内建匹配（:798）；0600 传密（:930 注释＋门禁 28/28）；P0-5 指纹轮换在 app.py:143-165 在位（AN 删 `rm -f secret.key` 的安全兜底）；AN 新增管道仅 `dpkg-query｜grep -q`（单行输出，无 SIGPIPE 面）；starter heredoc 门逻辑重跑 PASS（§1d） |
| panel/app.py | R1-P1-5（Flask 侧）、R1-P1-6、R1-P2-5、R1-P2-10、R2-P1-4、R4-P1-1（Flask 侧）、R6-P1-1（Flask 侧）、R4-BUG-1（Flask 侧）、R5-P2-1、R7-P1-1（Flask 侧）、R7-BUG-3 | §1a adv 28/28＋D11 5/5＋§2a 锁out PASS；§4a 门禁 28/28（登录／状态／保存不重起／B1/B2／风暴 7 切）；`_SK5_MUTATE_LOCK` 定义与 6 处 `with` 均在位（:978/:1438/:1478/:1535/:1556…） |
| core/openvpn_manager.py | R2-P1-1、R2-P1-3、R1-P1-10、R1-P1-11、R1-P1-13、R1-P2-6、R5-P2-2、R5-P2-3、R8-P2-3 | §1e Core 19/19（C0–C13＋C1 单测 5/5）；`_create_user_lock`（:651）与 `_sweep_orphan_index_entries`（:719）在位 |
| README.md | R6-P2-4（文档侧部分）、R7-P2-6（文档侧部分） | §6 全量核对（见下）；:71 条件化与 install.sh 一致（主控改动已核） |
| verify.sh | R5-P2-1（门禁侧）、R7-P1-1（门禁侧） | 仅 :234 注释改动（marker 写法）；starter 门逻辑按原逻辑重跑 PASS（§1d）；`bash -n` 过；全量分段未重跑（harness 已失，见 §4c 诚实交代） |
| panel/README.md | R6-P2-4、R3-P2-14（文档侧） | §6 全量核对；两处数字再次漂移，见 R10-P2-1 |

**（b）其余项——修复宿在未动文件内，R9 实证沿用（§3.0 mtime 逐项一致）：** agent/agent.py（13 格行为，R8 §4f 13/13）、cloudflare/src/index.js（Worker 18/18，R8 §1c）、core/easyrsa.sh（R5-P2-2 支撑）、egress/test-egress.sh（§6 矩阵 R9 4/4 沿用）、egress/policy-routing.sh（AG 14/14 矩阵 R9 沿用）、egress/sk5_manager.py（AJ 串行回归 13/13 R9 沿用＋本轮门禁 28/28 侧面覆盖保存/启停路径）、verify-integration.sh（门禁本身，本轮重跑 28/28）、panel/templates/index.html（AA 按钮在位，门禁 UI 格＋对比度核查覆盖）、各 README／docs/security.md／core/README.md（§6 逐条核对）。**R9 的 112 条中无一复发（R9-P2-3 的修法未防住下一轮漂移一事另立 R10-P2-1，不计入 112 条的复发——见 §3.1 备注）。**

### §3.6 U-1～U-12 认领表更新

| # | 项 | R10 更新 |
|---|---|---|
| U-1 | P0-1/2/3 部署态 | 仍未验（§5） |
| U-2 | R6-P1-1 真机复现 | **关闭**：live-8 headline-5（policy-missing via_sk5）显式重跑通过（§14），R9 留待项已兑现 |
| U-3 | UDP 数据面 | 关闭（R8 已判；live-7 S1/S2＋test_sk5 双 true；live-8 S2 再证 TCP+UDP 均走 SK5） |
| U-4 | R 符号链接自拷 | 关闭（无变化） |
| U-5 | R 逐项失败 die 分支 | 仍为“机制已证、分支未触发”：live-8 三装全程跑通（die 分支未触发符合预期）；分支本身仍须一次人为致败才验得到，live-9 跟进 |
| U-6 | T 两变异 | 关闭（R8 已判；R9 T 变异重跑 17/2/4） |
| U-7 | verify-integration 瞬时红 | 关闭（R9 28/28、本轮 28/28，两次一次过） |
| U-8 | 真机在位升级路径 | **R9 时记关闭，live-8 以 R8-BUG-1 推翻**（R7 的“原地升级路径打通”结论在毒源树条件下不成立）；AN 沙箱已修（§1c），**待 live-9 真机重验** |
| U-9 | KV 竞态与 POP 传播 | 仍未验（无部署） |
| U-10 | 前端渲染级核查 | **关闭**：live-8 headline-7 真机渲染通过（171 个可见文本 0 项低于 4.5、最薄 4.92、零 JS 报错）；本轮静态核查 10/10 与之致（§7） |
| U-11 | easy-rsa 真二进制签发 | 关闭（R8 已判；live-8 headline-2 以 real easyrsa 3.1.0 裁决：预存 req 拒绝，非覆盖） |
| U-12 | live-R5 结果 | 关闭 |

复扫合计：122 条＝已修 119（112＋§3.1 关闭的 5 条＋§3.2 关闭的 2 条）／部分 2（P0-3、P1-7）／未验 1（P0-1）；**本轮新发现 1 条另计（R10-P2-1，见 §6）**。122＝119＋2＋1；新发现 1 条见 §8 差集。

## §4 套件重跑

### §4a 门禁 verify-integration.sh：28/28（本轮在 /tmp/r10 副本上实测）

`bash verify-integration.sh`（自带 venv＋pip flask、桩 systemctl/ip/sing-box、面板 nobody 身份、/etc 快照比对）：**PASS=28 FAIL=0 SKIP=0**。逐格与 R9 §4a 同款（/etc 未碰、GET / 200、UI 入站卡／SK5 卡标记、未登录 401、登录 200、节点注册 token 只返一次、/api/status 三键齐全、保存禁用态不重起、B1 真翻转 enable 200 桩 run 恰 1 次、B2 disable 200 重起失败诚实上报、R4-BUG-1 格 A/B/B2、agent 配置 0600、get_status 全链 done、create_user 无 CA 时 failed 且无泄露）。宿主 /etc 复核干净（§8.4）。

### §4b Flask／Worker／Agent

- **Flask（本轮 adv 28/28＋lockout PASS＋D11 5/5）**：AH 的 flask35.py 已随 /tmp 清理消失，**35/35 未原样重跑**——本轮 Flask 面由 adv 探针 28 格（登录／节点注册／命令入队与轮询／队列重投与隔离／限流／SK5 健康读取）＋lockout 探针（5 错→401×5、锁后 429、旧会话 200）＋D11 磁盘满 5 格＋门禁 28 格（SK5 保存与启停、agent bundle、create_user 无 CA）覆盖。AK 改动面（队列／登录记账）已逐格行为验证；未改动的 SK5 enable/disable 路径由门禁 B1/B2 格覆盖。35/35 的逐格对照缺失，记为本轮套件口径的缺口（见 §8.2），不冒充。
- **Worker 18/18（沿用 R8 实证）**：`cloudflare/src/index.js` mtime 与 R9 §3.0 逐字节一致（09:24:00，未动），R8 §1c 的 18/18（via A–F＋init-pki＋cmd，变异改回 enabled 判据恰红五格）仍有效。本轮未重建 Worker 探针——代码未动，重建是重复劳动；部署态仍未验（§5）。
- **Agent 13/13（沿用 R8 实证）**：`agent/agent.py` mtime 与 R9 §3.0 一致（00:58:12，未动），R8 §4f 的 13/13 仍有效。

### §4c 门禁 verify.sh：全量分段未重跑（诚实交代）＋starter 门逻辑单跑 PASS

**运行形态**：R9 的 vfy 分段 harness（staged 树＋真 Flask 面板 8443＋unshare 绑挂＋fakebin-verify）已随 /tmp 清理消失，本轮**未重建全量分段跑**（重建成本高，且 live-9 的 headline-6 即 verify.sh 双态真机跑——沙箱分段数的边际价值低）。以下三点已做：(1) `bash -n verify.sh` 过；(2) verify.sh 本身自 R9 后仅 :234 注释改动（marker 写法，代码未动）；(3) **starter-template-consistency 门逻辑按原逻辑重跑 PASS**（§1d：heredoc :630-657 按 marker 提取成功，tun 入站全字段与模板一致、dns.final 一致、route.final 故意不同）。全量分段数（R9：22/0/1＋T 变异 17/2/4）沿用 R9，不冒充为本轮数。

### §4d Egress 套件：test-egress.sh §6 矩阵 4/4（沿用 R9）

`egress/test-egress.sh`、`egress/sk5_manager.py`、`egress/policy-routing.sh` 三文件 mtime 与 R9 §3.0 逐项一致（未动），R9 §4d 的 §6 矩阵 4/4（回环 5/0/2、商户同 IP 5/1/1、商户异 IP 6/0/1、pre-X 阴性对照 5/1/1）与 AG policy 矩阵 14/14 沿用。本轮未重建 egress harness；sk5_manager 的保存／启停路径由门禁 28/28 侧面覆盖。

### §4e Core 套件 19/19（本轮重跑，§1e）

单测 5/5（状态日志，夹具为真机捕获行）＋探针 14 格（C0–C13，C0 含 3 格）＝**19/19**。

### §4f 五套件总览

| 套件 | 规模 | 结果 |
|---|---|---|
| Flask adv＋lockout＋D11（本轮重写） | 28＋1＋5 | **28/28＋PASS＋5/5**（AH flask35 未原样重跑，见 §4b） |
| Worker（沿用 R8，代码未动） | 18 | **18/18** |
| Agent（沿用 R8，代码未动） | 13 | **13/13** |
| Core（本轮重跑） | 19 | **19/19** |
| Egress（沿用 R9，代码未动） | 4＋14 | **矩阵 4/4＋policy 14/14** |
| verify-integration.sh（门禁，本轮重跑） | 28 | **28/28** |
| verify.sh（门禁） | 23 | **全量分段未重跑**（§4c）；starter 门逻辑单跑 PASS |

## §5 P0-1/2/3：真实 wrangler deploy 重验——卡在登录，仍未验

- **dry-run 通过**（本轮重跑，wrangler 4.161.0 经 npx）：`npx wrangler deploy --dry-run` exit 0——绑定列出 `env.PANEL_KV (REPLACE_WITH_KV_NAMESPACE_ID)` 与 `env.PANEL_MODE ("cloudflare")`。dry-run 只证配置可解析，不证部署。
- **真 deploy 卡在第一步：无登录**（本轮重跑，exit 1）：`In a non-interactive environment, it's necessary to set a CLOUDFLARE_API_TOKEN environment variable for wrangler to work.`（与 R7/R8/R9 同一卡点；本机 `~/.config/.wrangler/` 下只有 logs＋metrics.json、无登录态，环境变量 `CLOUDFLARE_API_TOKEN` 未设置）。`wrangler.toml:32-33` 的 KV id 与 preview_id 仍是占位符 `REPLACE_WITH_KV_NAMESPACE_ID`／`REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`，是第二道卡点。
- **需要用户做的事（按顺序，缺一不可，与 R9 同款）**：(1) 在 Cloudflare 账号上建 API token（Workers＋KV 权限）并以 `CLOUDFLARE_API_TOKEN` 交给部署环境，或在可交互终端跑 `wrangler login`；(2) `wrangler kv namespace create PANEL_KV` 与 `--preview` 各一次，把返回的真实 id/preview_id 填进 `wrangler.toml`；(3) `wrangler secret put ADMIN_PASSWORD` 与 `wrangler secret put AGENT_BUNDLE_ORIGIN`；(4) `wrangler deploy`，再按 cloudflare/README:83 的要求换第二出口多点核（Workers 按 POP 慢速传播，单出口“没生效”不可信）。
- **结论**：P0-1/2/3（Worker 真实部署态）**仍未验**，与 R9 结论一致；Worker 代码侧的全部行为断言只在 mock KV＋本地 fetch 入口下成立，不是部署态证据。`--temporary` 未用——那会把 Worker 部署到临时抛弃账号上，不是用户的部署，测了也是冒充结论。

## §6 文档宣称全量核对（根 README／panel／cloudflare／security／flmx-reference／egress／core）

核对方法：每份文档的数字类宣称（门禁数、行数、端口、超时、重试上限、行号钉位）与行为类宣称逐条对代码/实测；数字以 `wc -l` 为准。

**通过的宣称**：
- 根 README:226 门禁数 28（本轮 verify-integration.sh 重跑 28/28 一致）；:198 哈希钉位 `install.sh:63-66`（实测该四行仍是四条 sha256 钉死值，与 agent.py:122-132 逐值一致，AN 的改动全在其后）；:71 iptables-persistent 条件化（与 install.sh:214-262 一致；ufw 机 live-only 局限在 README:71、install.sh:241 日志、install.sh:770-775 警告三处口径一致，无文档反称——README:276 的 `netfilter-persistent save` 是卸载清理步骤，不是存活宣称）；:137 SK5 端口待确认注（1001 默认、9000 待回报，与面板字段旁注 index.html:470-471 一致）；:140 重建 CA 步骤 7（两次确认、force+confirm、缺一 400、Worker 已转发——与路由 :1207 与 R9 实测一致）；:243 API 列表（与 §1 读到的路由表一致）；用户名规则 `[a-zA-Z0-9_-]{1,32}`＋保留名 `server`／`OpenVPN-CA`（与 core:99-119 一致）。
- 超时／计数类（全树 grep＋实测一致）：健康检查 60s（systemd timer `OnUnitActiveSec=60s`）、agent 轮询 5s（agent.py:70）、状态缓存 10s（app.py:960/981）、重投 120s／3 次（app.py:535-536 与 index.js:86 同值）、登录限流 5 次／5 分钟／锁 15 分钟（app.py:194-196；§2a 行为验证 429＋`retry_after_s: 900`）、证书 825 天（easyrsa.sh:50）。
- docs/security.md:12 重投分歧：Flask `SENT_MAX_RETRIES = 3`（app.py:536）与 Worker 同值（index.js:86），120 秒超时、Worker 非幂等首超时即 failed 的分歧均有记载；两端上限一致的宣称属实。
- panel/README 的函数签名清单：`create_user` 重名抛错＋legacy 先吊销再重签（core:812-820 在位）、`set_sk5` 部分合并语义、`test_sk5` TCP/UDP 分测——均与代码一致（代码未动，沿用 R9）；`get_user_ovpn` 缺失的说明属实。
- egress/README “策略路由的并发与幂等”节（AG 重写，文件未动，沿用 R9）；cloudflare/README:126 via 语义与 :140 init-pki 转发（代码未动，沿用 R9）；server-mode.md:42 “待真实 wrangler deploy 验证”诚实（见 §5）；core/README（`web/` 已清）；docs/flmx-reference.md 的 FLMX 原做法列均标“不抄”。

**新发现（R10-P2-1，文档未同步——同族复发：修复路改代码未同步改文档，与 R6-P2-4／R7-P2-6／R9-P2-3 同族，且复发在 R9-P2-3 的修复当轮）：**

- panel/README.md:55 称“2026-11-12 实测 `core/openvpn_manager.py` 1404 行”，:58 重复一次“（已核对实物；行数见 `wc -l`，2026-11-12 实测 1404 行）”。实测：core **1450** 行（AL ＋46）。`egress/sk5_manager.py` 1109 行仍准（未动）。
- 根 README:204 的 starter-heredoc 钉位“2026-11-12 在 `install.sh:570-597`”已过期：heredoc 现为 **:630-657**（AN 在其上插入约 60 行）；:570-597 现在指向 `install.sh` 的 `run-panel-tls.py` 生成段附近（另一段代码），钉位不仅漂移、且指错了对象。verify.sh:234 的注释 carry 同一个过期钉位（注释-only，门禁代码按 marker 提取，不受影响）。
- 机制：AM 在 13:13 写下两个“2026-11-12 实测”数字时它们是对的；AL（13:14）与 AN（14:11）同日落地后、任何文档复核之前，数字即过期。**带日期的实测数字在并行修复流程里存活不到一天**——日期让它看起来已核实，下一路代码改动即让它变假。AM 的修法只落实了 R9 建议的一半（marker 定位建议写进了正文与注释，但带日期的具体数字仍留在正文里）；免责句（panel/README “行数随修复浮动，文档不钉死具体行数”、README:204 “行号随插入浮动，定位用该 marker”）缓解了误导，但未治本：正文仍断言一个现已为假的实测值，读者按 `wc -l` 核对即发现 1404≠1450、:570-597 指错对象。
- 修法：**删掉正文里带日期的行数／行号数字，只留“见 `wc -l`”与“定位用 marker”**（数字改由发版前脚本生成，或不写数字）；verify.sh:234 注释的 `:570-597` 同删。门禁不受影响（starter 格按 marker 提取，本轮 §1d 已验 PASS）。

## §7 前端静态对比度核查（本轮重跑；真机渲染归 live-8，已过）

方法：跑 `panel/static/contrast-check.py`（WCAG 相对亮度；底线 4.5、目标 7；玻璃卡按白 72% 叠在 #f6f7fb 上估算有效底色 #fcfdfe）。`index.html` 未动（mtime 09:20:59，与 R9 一致）。

**脚本结果：10/10 过底线 4.5（exit 0）；目标 7 达成 4/10——与 R9 逐值一致。**

| 对 | 比值 | 底线 4.5 | 目标 7 |
|---|---|---|---|
| 正文 #1f2937 / 玻璃卡 | 14.41 | PASS | ✓ |
| 次要文字 #4b5563 / 玻璃卡 | 7.42 | PASS | ✓ |
| 主按钮白字 / #2563eb | 5.17 | PASS | — |
| 次按钮白字 / #4b5563 | 7.56 | PASS | ✓ |
| 危险按钮白字 / #b91c1c | 6.47 | PASS | — |
| 成功绿字 #15803d / 玻璃卡 | 4.92 | PASS | — |
| 徽标绿字 #166534 / #dcfce7 | 6.49 | PASS | — |
| 徽标红字 #991b1b / #fee2e2 | 6.80 | PASS | — |
| 激活导航 #1e40af / 激活底 | 8.65 | PASS | ✓ |
| 链接 #1d4ed8 / 玻璃卡 | 6.58 | PASS | — |

**结论**：静态核查通过底线（10/10，脚本 exit 0）；6 对低于目标 7（最低为成功绿字 4.92，仅高于底线 0.42），记为观察、不立案——门禁脚本的通过线就是底线，且 R7 九维视觉审计未以对比度立案。真机渲染已由 live-8 headline-7 通过（171 个可见文本 0 项低于 4.5、最薄 4.92、零 JS 报错），与静态核查一致，U-10 关闭（见 §3.6）。

## §8 裁决与未验清单

### §8.1 裁决：**不能交付，差集 1 条**

| 级别 | 条目 |
|---|---|
| P1 | 0 |
| P2 | 1：R10-P2-1（文档行数／行号钉位在 AM 修复当轮即再次漂移，同族复发） |
| 高（阻塞） | 0：R9 的 5 条与 live-8 的 2 条已全部修好（§1，变异红证齐全） |
| P0 | 0 未修、1 未验：P0-1/2/3 部署态仍未验（§5）；P0-3 部分（按设计，部署态未定） |

差集＝1 条（P2×1）。R9 的 5 条差集与 live-8 的 2 条新 bug 已全部关闭（§3.1/§3.2），历史 122 条中 119 条已修（§3.6）；AK/AL/AM/AN 的修复本身本轮全部行为验证通过（§1，变异红证齐全），套件全绿（§4f，见 §4b/§4c 的两处口径缺口）。但这不改变差集非空的结论：R10-P2-1 是 R9-P2-3 同族在修复当轮的复发——AM 的修法（带日期的实测数字）本身没防住下一路代码改动，证明该族的根治须是“删数字、只留 marker／生成值”，不是“再测一次数字”。

**下一步（按用户常设流程）**：派一小路修 R10-P2-1（只动三处文档／注释：panel/README:55/58、根 README:204、verify.sh:234——删带日期的行数／行号数字，只留“见 `wc -l`”与“定位用 marker”），修完集成后跑 **AUDIT-R11（全量全局回头看，换推导方法独立复算）＋ live-9（真机总验）**，两路都过才交付。修复路开工前须先确认：本报告基线树版本（§0）与修复路所取树一致。

### §8.2 未验清单（逐项：为什么没验、谁能验）

1. **P0-1/2/3 真实 wrangler deploy（§5）**——卡在 Cloudflare 登录（非交互环境须 `CLOUDFLARE_API_TOKEN`，`~/.config/.wrangler/` 无登录态；wrangler.toml 的 KV id 与 preview_id 仍是占位符）。谁能验：用户建 API token（或交互式 `wrangler login`）＋`wrangler kv namespace create PANEL_KV`（生产＋预览）填实 id＋`wrangler secret put ADMIN_PASSWORD`／`AGENT_BUNDLE_ORIGIN` 后，live 路跑真实 `wrangler deploy`，再从第二出口核 POP 传播。本轮不许用 mock 冒充。
2. **前端渲染级检查**——本轮只做了静态核查（§7：10/10 过底线 4.5、4/10 达目标 7）；真机渲染已由 live-8 headline-7 通过（171 个可见文本 0 项低于 4.5、最薄 4.92、零 JS 报错），U-10 关闭。但 live-9 的树含 AN 改动后，渲染须在新树部署上再跑一次（live-9 headline-7 回归）。
3. **Cloudflare KV 竞态＋POP 传播**——依赖第 1 项的真实部署；无部署则无从测。谁能验：同第 1 项，部署后多点核。
4. **SK5 端口 1001 vs 9000**——用户从未确认哪个是 SOCKS5 口（面板默认 1001，文档已标注待确认，README:137＋index.html:470-471）。谁能验：用户回报；live 路再以确认后的端口跑 UDP/TCP 双栈。
5. **D13 PKI 段竞态**——沙箱无 easyrsa 二进制，两路并发安装／重跑时 `init_pki`＋`build-ca` 的先查后建竞态测不到（copy 段已验，见 R9 §2）；live-8 未跑并发安装（§17 为顺序三装），仍未验。谁能验：live-9 在真机上跑并发安装／并发重跑。
6. **D14 时钟跳变**——沙箱无 faketime，改系统时钟超出审计范围；仅代码级分析（锁定／会话／重投／健康全是墙钟）。谁能验：真机上以 faketime 或受控调钟复核（须用户授权调真机时钟）。
7. **Flask 35/35 未原样重跑**——AH 的 flask35.py 已随 /tmp 清理消失；本轮 Flask 面由 adv 28 格＋lockout＋D11 5 格＋门禁 28 格覆盖（§4b），AK 改动面逐格行为验证，但 35 格逐格对照缺失。谁能验：下一轮审计重建 flask35 或等效套件；live-9 的真机 S0–S4 覆盖同一面的行为。
8. **verify.sh 全量分段未重跑**——R9 的 vfy harness 已失，本轮只单跑了 starter 门逻辑（§1d PASS）＋`bash -n`；全量分段数沿用 R9。谁能验：live-9 headline-6（verify.sh 双态真机跑）即该门禁的真机总验。
9. **R8-P2-4 的真 ufw 验证**——live-8 记未验（R8-BUG-2 使前提不可达）；AN 沙箱已修（§1c，2000 条规则＋111181 字节输出真实走通 builtin 分支）。谁能验：live-9（ufw 启用＋长表宿主机真机重跑）。
10. **U-5 die 分支**——机制已证、分支未触发（live-8 三装全程跑通）；分支本身仍须一次人为致败才验得到。谁能验：live-9 人为致败安装步骤。
11. **live-9 结论是否入本报告**——未入。live-9 与本轮并行在跑，其结论未落盘；本报告的沙箱结论不依赖它，live-9 落盘后须由主控对账（尤其 §8.2 的第 2/5/9/10 项与 R8-BUG-1/2 的真机验收）。

### §8.3 审计方法自述（供 R11 复核）

- 本轮方法：环境矩阵 × 修复存活推导（§2，7 环境 × 10 变迁逐格落探针／代码核对／明确不可验）＋历史全量复扫（§3，122 条，mtime 对账＋六文件内逐项重验）＋新代码逐项行为验证（§1，亲自重跑、零 monkeypatch 走真实代码路径、阴性对照齐全）＋套件重跑（§4，Flask adv／Core／双门禁重跑＋Worker／Agent／Egress 沿用 mtime 未动文件）＋P0 部署态重验（§5）＋文档宣称全量核对（§6）＋前端静态对比度核查（§7）。
- 探针纪律：凡套件格先红，必先查探针本身（本轮修掉的探针问题：core C0 断言 `build_server_cert` 回 `server_conf` 键——该函数只回 6 个安装路径；C5 把合规的 `-dash` 列为非法名——规则是 `[a-zA-Z0-9_-]{1,32}`；C1 用 pytest/unittest 跑 plain script 单测——该文件头注“no pytest needed”，直接跑；adv 探针初版漏调 `_ensure_admin_password()`——它只在 `__main__` 跑，import 不生成密码；D9 探针初版未跑 `build_server_cert`——全新 PKI 缺 ta.key，create_user 失败。探针修好重跑后才定性，不在探针 artifact 上立案）。
- 沙箱边界：无 systemd／无 TUN／无 easy-rsa／无 openvpn 二进制／UDP sendto 临时端口 EPERM——凡涉此五项的结论均已标注分段环境或待真机（live-9），未把沙箱结论写成真机结论。fake apt 的“装 iptables-persistent 即卸 ufw”模型以 live-8 真机证据为锚（install3.log:8），fake easyrsa 的 index.txt 语义以 openssl 真签发为锚——桩的行为均有真机／真程序对照，不是凭空捏造。
- 本轮审计侧污染：无。探针进 `unshare -m` 绑挂（`/etc/openvpn-sk5-panel`、`/etc/sysctl.d` 绑 /tmp），事后 /etc 复核干净（见 §8.4）；宿主挂载点目录（`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`，run-flask/run-install 的 `mkdir -p` 留下）已 rmdir 删净。/tmp 资产（供 R11 复用）：`/tmp/r10`（树副本＋tree-old 回退树）、`/tmp/r10-tests/`（run-flask harness、r10_adv／r10_diskfull／r10_core／r10_lockout 探针、make_old_tree.py）、`/tmp/an-tests/`（AN 探针＋fakebin＋venv）。

### §8.4 清理记录（审计结束时）

- 分段面板（AN 探针的 staged 面板，https://127.0.0.1:8443）已由探针 `kill_panel()` 停；SOCKS stub 与 fixed-IP 服务器未在本轮启动；端口 8443/1080/11080/80 已空闲，无残留进程（`ps`＋`ss` 核对）。
- 宿主 `/etc/openvpn-sk5-panel/`、`/etc/openvpn/`、`/etc/sysctl.d/99-openvpn-sk5.conf`、`/run/openvpn-sk5-panel/` 均不存在（每次 unshare 绑挂后都 rmdir 复核）；宿主 /etc 复核干净。
- 项目树核查：本轮只写了本报告一个文件；树内其余文件 mtime 未动；`__pycache__` 检查：`py_compile` 只在 `/tmp/r10` 副本内生成字节码，原树无新增缓存（`find -newer README.md` 空）。
- /tmp 资产（供 R11 复用）：`/tmp/r10`（树副本、tree-old 回退树、deploy.log）、`/tmp/r10-tests/`（harness＋四探针＋回退脚本），`/tmp/an-tests/`（AN 探针＋fakebin＋venv）、`~/workspace/ae-tests/poison/`（毒包文件）。

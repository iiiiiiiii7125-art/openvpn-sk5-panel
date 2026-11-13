# AUDIT-R9 — 全量全局回头看（交付前）

## 结论先写

**不能交付，差集 5 条（P1×2：R9-P1-1 队列 naive 时间戳 wedge 全部 agent 命令、R9-P1-2 过期证显示 valid 且重建 409；P2×3：R9-P2-1 队列损坏静默丢命令、R9-P2-2 磁盘满登录 500、R9-P2-3 文档行数／行号钉位过期）。R8 的 8 条差集已全部关闭；历史 115 条 112 已修、2 部分、1 未验；AE/AG/AH/AJ 四路修复全部行为＋变异红证通过；套件 Flask 35/35、Core 21/21、egress 4/4、verify-integration 28/28、verify.sh 分段 22/0/1＋T 变异 17/2/4。P0-1/2/3 真实部署仍未验（卡用户侧登录＋KV 占位，第三次问，未复）。**

- 审计员：独立审计路（未参与建设与修复路 AE/AG/AH/AJ；单审计员边做边写，不派子代理）
- 日期：2026-11-12（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R8 同等广度）
- 推导方法：**对抗操作员＋时间衰变推导**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性均不同）——先枚举一个会犯错的操作员能做的全部错事（并发安装、安装中途被杀、磁盘满、时钟跳变、误填端口、重复建同名用户、agent 停机时连点启用、删错行、重装时源树与安装树同一目录）与系统随时间老化的全部衰变（陈旧队列重投、状态缓存过期、证书与 CRL 老化、定时器漂移、面板与 agent 长时间失联后重连、健康检查与操作员动作并发），每条推导链必须落到一条可执行的探针或一条明确的“不可验（写清为什么）”，不许只写文字推断；再叠加全量复扫（R8 的 115 条逐条复现定性）与 AE/AG/AH/AJ 新代码逐项行为验证。live-8 与本轮并行在跑，其结论未入本报告的须在 §8 写明。
- 测试一律在 `/tmp` 副本（`/tmp/r9` 树副本、`/tmp/r9-tests/` 自建 harness、`/tmp/ah-tests/` 与 `/tmp/aj-tests/` 复用探针、`/tmp/r9-venv`）上跑；未动项目原文件；未动 `/etc`（探针进 `unshare -rm` 挂载命名空间，`/etc/openvpn-sk5-panel` 与 `/etc/sysctl.d` 绑 /tmp；事后 mtime 核对见 §8）；未动任何真机。需真机行为复核的项一律写“待 live-8”，不提前判通过。
- 语法基线：4 个 Python 文件 `py_compile` 全绿；7 个 shell 脚本 `bash -n` 全绿；Worker `node --check` 全绿（见 §0）。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明。

## §0 树版本与 AE/AG/AH/AJ 改动确认

当前树是 R8 修复路 AE/AG/AH/AJ 之后的新树。文件 mtime（UTC，原树）与 R8 §0 基线对照：

| 文件 | mtime (UTC) | 行数 | 说明 |
|---|---|---|---|
| install.sh | 2026-11-12 12:20:28 | — | AE 路：版本校验先存变量再 grep（:305-306 sing-box、:347-348 tun2socks）、ufw 改 shell 内建匹配（:724-728）、`_PANEL_COPIED` 门控清 panel/data/（:386-431） |
| panel/app.py | 2026-11-12 12:20:44 | 1947（R8: 1907） | AH 路：`_SK5_MUTATE_LOCK`（:919，用 6 处） |
| core/openvpn_manager.py | 2026-11-12 12:22:18 | 1404（R8: 1230） | AH 路：`_create_user_lock` flock（:613）、`_sweep_orphan_index_entries`（:681） |
| egress/policy-routing.sh | 2026-11-12 12:13:01 | 364（R8: 352） | AG 路：occupant-error 分支已删、do_status 源改 10.8.0.1（:342） |
| egress/README.md | 2026-11-12 12:16:15 | — | AG 路：M4 节按内核真实语义重写 |
| egress/sk5_manager.py | 2026-11-12 12:37:13 | 1109（R8: 1088） | AJ 路：`_atomic_write_json`（:127），四处写盘全改走它 |
| panel/data/ | 2026-11-12 12:14 | 空目录 | AE 路：毒 panel.db 与 agent_queue.json 已从源码树删掉 |
| verify.sh / verify-integration.sh / cloudflare/src/index.js / agent/agent.py / core/easyrsa.sh / egress/test-egress.sh / README.md | 未动（R8 mtime） | — | 与 R8 基线逐字节一致（本轮 `diff` 核对，见 §3） |

语法基线（本轮在 `/tmp/r9` 副本上实测）：`panel/app.py`、`egress/sk5_manager.py`、`core/openvpn_manager.py`、`agent/agent.py` 四文件 `py_compile` 全绿；`install.sh`、`verify.sh`、`verify-integration.sh`、`egress/test-egress.sh`、`egress/policy-routing.sh`、`core/easyrsa.sh`、`agent/install-agent.sh` 七脚本 `bash -n` 全绿；`cloudflare/src/index.js` `node --check` 全绿。

/tmp 资产现状（本轮开工时实测）：`/tmp/r8*`、`/tmp/r8-venv`、`/tmp/ag-tests/` 已被清掉；`/tmp/ae-tests/`、`/tmp/ah-tests/`、`/tmp/aj-tests/`、`/tmp/ah-venv/` 幸存。本轮策略：**复用幸存的 AE/AH/AJ 探针但重指到当前树**（`/tmp/r9` 为当前树完整副本，`diff -rq` 与原树逐字节一致；venv 重建于 `/tmp/r9-venv`，flask 3.1.3＋bcrypt）；AG 的 policy-routing harness 已随 `/tmp/ag-tests/` 消失，本轮从零重建（内核忠实语义 fake ip，见 §1b）。

（以下各节边审边写）

## §1 AE/AG/AH/AJ 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

### §1a AE 路（R7-BUG-1＋R8-P2-4＋R7-BUG-2）——全部行为验证通过

探针：复用 `~/workspace/ae-tests/`（version_probe.sh、ufw_probe.sh、guard_probe.sh、poison_install.sh、ensure_probe.py），均对当前树原文评估；毒文件用真实面板代码重建（`build_poison.py`：panel.db 含真 admin 行 `$2b$12$tceqe…`、agent_queue.json 含 3 条 init_pki force+confirm，1 sent＋2 queued——本轮亲手读文件核对）。

| 格 | 期望 | 实测 |
|---|---|---|
| 版本校验旧式（慢写者，0.3s 延时第二行） | rc=141（探针有效） | PASS：sing-box/tun2socks 旧式各 10/10 rc=141 |
| 版本校验新式（install.sh:305-306/:347-348 先存变量再 grep） | 30/30 rc=0 | PASS：sing-box 30/30、tun2socks 30/30 全 0 |
| 错版本仍须失败（检查未被阉掉） | rc=1 | PASS：两处错版本新写法均 rc=1 |
| ufw 旧式（fake ufw 2000 规则约 270KB，Python 块缓冲） | 静默跳过（阴性对照） | PASS：旧式 rc=1、allow 分支零放行 |
| ufw 新式（:724-728 先存变量＋shell 内建 `[[ == *…* ]]`，无管道） | 两条 allow 落日志 | PASS：`allow 1194/udp`＋`allow 8443/tcp` 均落日志；ufw 缺席/未激活干净跳过 |
| 毒包安装新式（真实 install.sh 装树＋清理路径，unshare 绑挂 staged /opt 与 /etc） | panel/data 为空、两条 discard 日志 | PASS：staged panel/data 为空，`discarded shipped runtime file panel/data/panel.db` 与 `agent_queue.json` 各一条 |
| 毒包安装旧式（install-orig.sh，sha256 c69541de…与 live-7 记录一致） | 毒文件原样留存 | PASS：panel.db 32768B＋agent_queue.json 1104B 原样在位 |
| `_ensure_admin_password` 新侧（清理后的空 data 目录） | 生成 admin.pass 0600＋全新 admin 行 | PASS：admin.pass 存在 mode 0600、新 admin 行 `$2b$12$S845…` |
| `_ensure_admin_password` 旧侧（毒 panel.db 在位） | 短路、无 admin.pass、毒行原封不动 | PASS：无 admin.pass、毒行 `$2b$12$tceqe…` 不变 |
| 幂等守卫 A（干净源树重装，/opt 已有活 panel.db＋queue） | 活文件哈希分毫不差、无 discard 日志 | PASS（AE 探针，本轮重跑） |
| 幂等守卫 B（`$SCRIPT_DIR = $INSTALL_ROOT` 自树运行） | 跳过拷贝、活文件不动 | **AE 原探针无效，本轮纠正重跑后 PASS**（见下注） |

探针 bug 自记（本轮发现，未误判产品）：AE 的 guard_probe.sh 的 guard B 段 staging 有错——它把树直接拷到 `$S/opt-B/`（install.sh 在 `$S/opt-B/install.sh`），却以 `/opt/openvpn-sk5-panel/install.sh` 调用，命名空间内该路径根本不存在（`bash: …: No such file or directory`，exit 127），安装器一次都没跑过；“活文件不变”与“skip-copy 行未找到”都是未执行的平凡结果，AE 的 GUARDS: ALL PASS 里 B 格是空证。本轮按正确 staging（树在 `$S/opt-B/openvpn-sk5-panel/`、挂 `$S/opt-B` 到 /opt）重跑：日志现 `"source tree is the installed tree (/opt/openvpn-sk5-panel); skipping tree copy"`，安装器走到 PKI init（沙箱无 easyrsa 而死，属预期、已过拷贝段），活 panel.db＋queue 哈希与毒前一致、discard 行 0 条——**守卫 B 真正通过**。AE 的 A 格与毒包格无此问题（日志证实安装器确实跑过拷贝段）。

**裁决：R7-BUG-1、R8-P2-4、R7-BUG-2 三条已修。** 余一沙箱边界：staged 安装均在 PKI init 处止步（沙箱无 easy-rsa，apt 被桩成空操作），pip/systemd/面板起步段未在沙箱走通——毒包安装的完整端到端（装完＋admin.pass 生成＋agent 首次轮询不执行 init_pki）须 live-8 真机复验，见 §8。

### §1b AG 路（R8-P2-1＋R7-BUG-4＋R8-P2-2）——全部行为验证通过

Harness：本轮从零重建（`/tmp/ag-tests/` 已随 /tmp 清理消失）——`/tmp/r9-tests/ag/`：内核忠实语义 fake `ip`（`rule add` 仅对完全相同规则报 EEXIST，不同 selector 可共用 priority；add/del 在文件锁下原子执行——R8 曾记非原子 fake-ip 在并发 ×5 时留下重复规则行的人工痕迹，本轮已消掉；`route get … from 10.8.0.2` 复现 live-7 真机原文 `RTNETLINK answers: Network is unreachable`）、有状态 fake `iptables`（-C 按在位与否返回 0/1——R8 曾记 fake iptables `-C` 恒 0 致 disable 死循环，本轮按分支返回值）、fake `sysctl`；`run-ag.sh` 在 `unshare -rm` 下把 `/etc/sysctl.d`、`/etc/openvpn-sk5-panel`、`/run/openvpn-sk5-panel` 绑到 /tmp；`policy-current.sh` 经 `diff -q` 确认与当前树 `egress/policy-routing.sh` 逐字节一致。

| 格 | 期望 | 实测 |
|---|---|---|
| M1 空态启用 | 200、规则＋路由在位 | PASS |
| M2 规则已在位启用 | 200、不重复加 | PASS |
| M3 同 selector 异 priority（200） | 200、最终唯一、副本已删 | PASS |
| M4 外来规则共用 priority 100（10.9.9.0/24） | rc=0、两条规则共存 | PASS（与 live-7 真机一致） |
| M4b 禁用留外来规则、重启用 200 | 外来规则不动、重启用 200 | PASS |
| do_status VPN 源段 | `1.1.1.1 from 10.8.0.1 dev tun1 table 100` | PASS；`10.8.0.2` 在输出中零命中；fake 内核对 10.8.0.2 源的阴性对照恒报 Network is unreachable |
| 并发启用 ×5 | 全 0、规则唯一、`"(added concurrently)"` 0 次 | PASS |
| 并发 disable ×2 | 全 0、规则清空 | PASS |
| 压力 enable/disable 交替 ×20 | 0 失败、终态干净 | PASS |
| restore：enabled=true / false | 前者重应用、后者不动主表 | PASS |

变异红证（出口码级，全红）：
- **MUT-AG1（旧式先查后加＋无 flock＋grep -q 守卫）**：并发启用 ×2 → rcs `1 0`，一条 `RTNETLINK answers: File exists`——R6-BUG-1 竞态在旧写法下可复现，现行幂等 add＋flock 下同测全 0。
- **MUT-AG2（dedup 移除）**：M3 重跑 rc=0，但终态两条规则共存（`200|10.8.0.0/24|100` 未被清除），对照组终态唯一。
- **MUT-AG3（EPERM 误诊窗口）**：`ip rule add` 强制报 EPERM 且外来规则在位时，die 文案即真实的 `RTNETLINK answers: Operation not permitted`，`"already used by"` 零命中——R8-P2-1 的误诊窗口已关闭。

代码核对：`egress/policy-routing.sh` 中 `occupant` 仅剩 3 处注释（头注释与 add_rule 注释，说明该分支已删及原因），实码零命中；`from 10.8.0.2` 的 route-get 全树零处（剩余 10.8.0.2 命中全是测试夹具里的客户端虚拟地址与解释性注释）；egress/README 的 M4 节已按内核真实语义重写（“外来规则共用 priority 100（启用 200、两条规则共存）全过”；“占用者报错”仅在历史说明句中出现，标明已删除）。

**裁决：R8-P2-1、R7-BUG-4、R8-P2-2 三条已修。**

### §1c AH 路（R7-BUG-3＋R8-P2-3）——全部行为验证通过

探针：复用 `/tmp/ah-tests/`（ah_conc_probe.py、flask35.py、run-ah.sh），重指到当前树 `/tmp/r9`；真实 Flask test_client＋真实 core＋fake 外部世界，`unshare -m` 绑 /etc。

| 格 | 期望 | 实测 |
|---|---|---|
| 并发探针（5 轮并发启用双 200、6 轮并发禁用、并发 UoT 翻转、并发同名建用户、串行重复 409、扫残留三格＋R 行保留） | 51/51 | **PASS 51/51** |
| Flask 35 格（R8 口径，T2/T3/T5/T6 重起计数＋R1/R2 repaired 全在内） | 35/35 | **PASS 35/35** |

代码核对：`_SK5_MUTATE_LOCK`（panel/app.py:919）在 save（toggle-only＋全量两分支）、enable、disable、fail-open、udp-over-tcp 五路的读-查-改全程取锁（:1379/:1419/:1476/:1500/:1525/:1546），GET /api/status 与 GET /api/sk5 不取锁；core `_create_user_lock`（:613，PKI 目录 flock）在 create_user 的扫残留＋判重＋清旧文件＋build 全程内；`_sweep_orphan_index_entries`（:681）同 CN 多 V 时只保留序列与 `issued/<名>.crt` 内序列一致的一条、无 issued 文件则全删、R/E 行与畸形行原样保留、原子替换（tmp＋os.replace）。

探针自记（本轮的 /etc 泄漏，已清）：复核时发现宿主 `/etc/openvpn-sk5-panel/secret.key`（32B，0600，mtime 2026-11-12 12:43:14 UTC）——是我方探针漏出的：`ensure_probe.py` 在宿主（非 unshare）直接 import 面板 app.py，`_load_or_create_secret` 见机内路径无 key 即在宿主 /etc 生成了一份；目录本身是 AE 的 guard_probe.sh 在宿主 `mkdir -p /etc/openvpn-sk5-panel /etc/openvpn /etc/systemd/system` 留下的。无面板进程在跑、端口 8443/11080 空闲，key 是随机值、无凭据可盗——但仍是审计侧污染，本轮已删除 key 与两个空目录，宿主 /etc 复核干净（见 §8.4）。教训与 R7/R8 同款：任何直接 import 面板代码的探针也必须进 unshare 绑挂，事后必复核 /etc。

**裁决：R7-BUG-3、R8-P2-3 两条已修。** 余一沙箱边界：real easyrsa 的 gen-req 遇预存 key 是拒绝还是覆盖仍未知（沙箱无 easyrsa 二进制，探针用 openssl 直写 fake），AH 的锁修法不依赖其行为；并发同名建用户的真机后果须 live-8 在 real easyrsa 上复核，见 §8。

### §1d AJ 路（sk5_manager 固定 tmp 名跨进程竞态）——全部行为验证通过

探针：复用 `/tmp/aj-tests/`（aj_conc.sh、aj_old_impl.py、aj_serial.py），重指到当前树 `/tmp/r9`。

| 格 | 期望 | 实测 |
|---|---|---|
| 跨进程并发新写法（双 save＋render＋health＋reader，5 路 ×60 次） | 零失败、零 tmp 残留、终态三文件合法 JSON | PASS：5 路各 60 次 0 失败、error lines 0；cfg 目录仅 health.json/sing-box.json/sk5.json，无 `*.tmp.*` 残留；三文件均解析为合法 JSON |
| 旧写法阴性对照（固定 `sk5.json.tmp`，双进程） | 复现 `FileNotFoundError: 'sk5.json.tmp' -> 'sk5.json'` | PASS：×60 一次跑出 0 次（竞态时序依赖，见下注）；×300 三跑分别 19/34/18 条 error，签名逐字复现 |
| 串行回归 13 格（存取往返、0600、redact、双 render、health 往返＋吞错、validate、DNS 解析器） | 13/13 | **PASS 13/13**（含失败分支：目标为目录时 RuntimeError 点名路径、无 tmp 残留、旧文件原封不动） |

注：旧写法 ×60 一次 0 失败——该竞态本身是小概率（AJ 报告 ×60 复现 2 次，约 3%）；本轮 ×300 三跑 19/34/18 条，阴性对照有效。代码核对：`_atomic_write_json`（sk5_manager.py:127，同目录唯一 tmp 名 pid＋随机、0600、os.replace、失败自清并报含路径的 RuntimeError），四处写盘（:162、:223、:256、:938）全改走它；全文件 `with_suffix(".json.tmp")` 固定名零处（仅 docstring 引述旧写法）。

**裁决：AJ 项已修。** 附记：AJ 报告称“egress 套件 20/20 的旧探针已随 /tmp 清理不在盘上，没法原样重跑”——本轮 test-egress.sh §6 矩阵在 §4d 重跑（见下），不依赖 AJ 的 13 格。

## §2 对抗操作员＋时间衰变推导（本轮新法）

推导轴：一个会犯错的操作员（手改队列文件、删错库、磁盘满、连点启用、重复建同名用户、并发安装）×一个会老化的系统（队列重投超时、证书过期、健康结论陈旧、时钟跳变、面板与 agent 长时间失联）。每条链落到一条可执行探针或一条明确的“不可验（写清为什么）”，不许只写文字推断。探针：`/tmp/r9-tests/adv/r9_adv_probe.py`（D1–D6、D9）、`r9_diskfull.py`（D11）、`r9_install_probes.sh`（D8、D13），真实 Flask test_client＋真实 core＋fake 外部世界（AH fakebin），`unshare -m` 绑 /etc；探针本身无 monkeypatch。D7/D10/D14 为代码级核对＋不可验说明。

| 链 | 探针 | 实测 |
|---|---|---|
| D1 手改/损坏队列：`sent_at` 无时区（naive） | adv 探针 | **R9-P1-1**：agent poll 500＋GET /api/cmd/\<id\> 500（见下） |
| D1b `sent_at` 不可解析字符串 | adv 探针 | PASS：poll 200（`fromisoformat` ValueError 已捕） |
| D2 队列重投生命周期（sent 121s 超时→重投） | adv 探针 | PASS：重投 3 次、retries=4 时 failed，符合设计（约 8 分钟窗口） |
| D3 agent 离线时连点 5 次相同 set_sk5 enable | adv 探针 | 观察：poll 一次交出 5 条，无去重（见观察 O-1） |
| D4 队列文件整体损坏（非 JSON） | adv 探针 | **R9-P2-1**：poll 200 空命令、已排队命令静默丢失（见下） |
| D5 运行中删 panel.db | adv 探针 | 观察：旧密码登录 401、既有会话 /api/status 仍 200、重启重建密码后新密码可登（见观察 O-2） |
| D6 健康结论陈旧（checked_at 3 小时前） | adv 探针 | 观察：get_status 原样返回，无陈旧标识；前端零渲染 health（见观察 O-3） |
| D7 SK5 启用时上游不可达 | 代码级（见下） | 按设计：enable() 返回 get_status() 含实时测量的 egress_ip（不可达则 null），无虚假值 |
| D8 安装中途被杀（copy 与清理之间） | install 探针 | PASS：重跑清愈（见下） |
| D9 证书过期但 index.txt 仍为 V | adv 探针 | **R9-P1-2**：list 显示 valid、重建 409（见下） |
| D10 改密码错旧密码是否计入锁定 | 代码级 | 观察：不计入（须有效会话，无未授权爆破面） |
| D11 磁盘满时登录 | diskfull 探针 | **R9-P2-2**：错密码 500、正密码（有失败行时）500（见下） |
| D13 并发安装（两路同写一 staged /opt） | install 探针 | PASS（copy 段）；PKI 段竞态沙箱不可验（见下） |
| D14 时钟跳变 | 不可验 | 无 faketime、改系统时钟超出沙箱范围；代码级分析见下 |

### R9-P1-1（D1，高）：队列 `sent_at` 无时区 → agent 全通道 500，须手改文件才恢复

机制：`panel/app.py:493 _requeue_stale_sent` 只在 `try` 内包 `datetime.fromisoformat`（ValueError），而 `(now - sent)` 减法在 try 之外；naive 时间戳（无 `+00:00`）`fromisoformat` 成功，减法抛 `TypeError: can't subtract offset-naive and offset-aware datetimes`。调用点：`agent_poll`（:1787）与 `cmd_get`（:1699）均无兜底。

探针实证（adv 探针 D1）：先入队 get_status、poll 一次（sent），把队列文件里该命令的 `sent_at` 改写为 `"2026-11-12T10:00:00"`（合法 ISO、无时区），再 poll：**500**（HTML 500 页）；GET /api/cmd/\<id\> 同样 **500**，traceback 逐字指向 app.py:505 `(now - sent)`。而 D1b（`"not-a-date"`）poll 200——ValueError 分支有捕，TypeError 分支没有。

破坏面：一次 poll 500 后队列文件原样保留 naive 值，每次 poll 都在第一条 naive 命令上抛错——**agent 永远拿不到任何命令**（poll 先调 `_requeue_stale_sent` 再发命令），节点 last_seen 停摆；操作员在面板上看不到原因（GET /api/cmd 也 500）。更尖锐：POST /api/cmd 入队**不调** `_requeue_stale_sent`（调用点全树仅 :1699/:1787 两处），所以入队仍回 202“已接受”——面板持续接受它永远无法执行的操作。唯一恢复是人工改队列文件（或删 agent_queue.json，`_load_queue` 缺失文件当空处理）——该恢复路径文档无记载。触发条件须一个人或另一工具往队列文件写 naive 时间戳（正常写入恒为 aware，`_utcnow_iso` 带 `+00:00`），概率低但破坏为全通道、且无面板内恢复。修法：减法处同捕 TypeError（或 naive 一律按 UTC 解读），与 ValueError 分支同待遇。

### R9-P1-2（D9，高）：证书过期但 index.txt 仍为 V——面板显示 valid、重建 409，用户无法连接也无法重建

机制：`core/openvpn_manager.py:350 _parse_index_txt` 只信 index.txt 的状态旗标（V→valid），**从不把 `expires` 字段与当前时间比较**。E 旗标只在下一次 `openssl ca` 操作（签发/吊销）加载 index 时才由 openssl 翻过来；过期到下一次 CA 操作之间（可能数月，取决于有无新用户）面板持续撒谎。

探针实证（adv 探针 D9，fake easyrsa 真签发）：建用户 carol（825 天证），把 index.txt 里 carol 行的 expiry 改为 `200101000000Z`、状态保持 V；`list_users()` 返回 `{'name': 'carol', 'status': 'valid', 'expires': '200101000000Z', ...}`；再次 `create_user("carol")` 抛 `UserAlreadyExistsError("user 'carol' already exists (valid cert)")`。对照：`create_user`（:812/:821）对 `revoked`/`expired` 状态是放行的（删旧文件后重签），只对 `valid` 409——所以旗标一翻到 E 就能重建，问题恰在旗标翻转前的窗口：用户显示 valid、OpenVPN 拒接过期证、操作员无法重建，唯一出路是先手工吊销（须先识破“valid 是假的”）。每张用户证 825 天后必然过期，这不是罕见边角，是保证到来的衰变。修法：`_parse_index_txt`（或 `_user_status`）里把 `expires` 与 now 比较，过期即报 expired——`expires` 字段本已在行内，数据现成。

### R9-P2-1（D4，中）：队列文件损坏 → 全部已排队命令静默丢失，无任何报错

机制：`_load_queue` 吞掉损坏 JSON（OSError、ValueError → 空状态），`agent_poll` 随后 `_save_queue` 把空状态写回磁盘——损坏文件被合法空队列覆盖，命令永久消失。

探针实证（adv 探针 D4）：入队 get_status 后把 agent_queue.json 写成 `{not json,,,`；poll 回 **200、commands=[]**；GET /api/cmd/\<id\> **404**（命令已不在）；下一次入队 202 恢复正常。症状对操作员可见（节点状态不变化），但原因不可见：面板无日志、无报错、无“队列损坏”提示，操作员只会看到“启用点了没反应”。修法任选其一：损坏时保留 `.corrupt` 备份＋日志告警；或 poll 回包带 error 字段；或不覆写损坏文件直至操作员确认。

### R9-P2-2（D11，中）：磁盘满时登录端点 500——错密码必 500，正密码（有失败行时）也 500

机制：`login()` 路无 try/except 包 `_record_login_failure` / `_clear_login_failures` / bcrypt 迁移 UPDATE；`_audit` 有吞错，登录失败记录没有。磁盘满 → sqlite 写失败 → 500。

探针实证（diskfull 探针，RLIMIT_FSIZE 软限 1024＋SIGXFSZ 忽略，DB 32768 字节已存在）：对照错密码 401、正密码 200；设限后（**失败行已存在**——对照错密码先插了一行，且其间无成功登录清行）：**正密码 → 500**（DELETE 须真写盘）、**错密码 → 500**（INSERT 写盘失败）；解除限制后正密码 **200**，恢复且无损坏（失败的 INSERT/DELETE 原子回滚）。第一版探针的附带发现：正密码在**无失败行**时磁盘满仍回 200——DELETE 无行可删即无写盘，500 只在“须删行”时出现；这解释了为何该缺陷平时不可见。触发须磁盘满（环境故障），但故障模式是最坏一种：管理员最需要登录排障时被 500 挡在门外，且错密码 500 会把“密码错了”伪装成“服务坏了”。修法：`_record_login_failure` / `_clear_login_failures` 包 try/except（与 `_audit` 同待遇），写失败时登录本身按 401/200 照常返回。

### §2 其余链（PASS／观察／不可验）

- **D2 PASS**：重投生命周期与设计逐字一致——sent 121s  aging→queued retries+1，三轮后第四次超时 retries=4 变 failed（约 8 分钟窗口）；无新发现。
- **D3 观察 O-1**：5 条相同 set_sk5 enable 一次 poll 全数交出，无去重。良性：agent 串行执行，每条 enable 幂等（policy-routing 幂等 add＋daemon 已在运行则不动），AH 已验证并发启用零多余重起；不立案，仅记“队列无去重、执行层幂等兜底”。
- **D5 观察 O-2**：运行中删 panel.db——旧密码登录 401（`_db()` 每调用重建空表，admin 行已无）、既有会话 GET /api/status 仍 200（面板看似活着、实则无人能再登录）、`_ensure_admin_password()` 重跑（模拟重启）生成新密码、新密码登录 200。这是文档记载的密码重置流程（删 admin 行＋重启）的同一机制，属设计；仅记一点：面板不检测／不宣告“库丢了”（状态 200＋节点列表空是唯一信号）。
- **D6 观察 O-3**：health.json 的 `checked_at` 写为 3 小时前、`healthy: true`——`get_status()` 原样返回 `last_health`，无陈旧标识、无 age 字段。但 `panel/templates/index.html` 全文 **零处**出现 `health`/`last_health`/`checked_at`（grep 空）——前端根本不渲染健康结论，所以“陈旧结论冒充新鲜”只影响直接读 API 的消费者（`checked_at` 字段本身在回包里，可自行算 age）。不立案；若将来前端上健康卡，须同时上 age／过期标识。
- **D7 按设计**：`enable()`（sk5_manager.py:852）渲染→起 sing-box→等 tun1→应用策略→存 enabled=true→返回 `get_status()`；`get_status()`（:847）在 enabled 时调 `current_egress_ip()`（:759）——**实时** curl 探针（此路径无缓存），SK5 不可达则 `egress_ip: null`、`policy_routing_active: true`。200 回包里 null 就是诚实信号，操作员另有 test_sk5 看 TCP/UDP 明细；无虚假值。仅记混合信号一点：面板会同时显示“经 SK5 出口”与 egress “—”。
- **D8 PASS**：kill 窗口重跑清愈。staged：源树带毒（panel.db＋agent_queue.json）＋staged /opt 预置同一份毒（模拟 kill 在 copy 与清理之间）→重跑安装器：staged /opt panel/data **空**，日志 2 条 `discarded shipped runtime file`。安装器其后死于 PKI（fakebin 无 easyrsa，预期内；copy＋清理在 pip 段前已完成）。
- **D10 观察**：`change_password` 错旧密码不调 `_record_login_failure`（代码级）。无未授权面（须有效会话），不立案。
- **D13 PASS（copy 段）＋PKI 段不可验**：两路安装器并发同写一 staged /opt，终态树完整；`diff -r`（除 panel/data）9 行差异逐项解释清：copy 列表显式为 `agent core egress panel systemd install.sh verify.sh verify-integration.sh README.md`（cloudflare/、docs/、.gitignore 故意不进 /opt，设计如此）；`run-panel-tls.py` 是安装器 :461 生成的启动器（故“仅在 /opt”）；`__pycache__` 差异是我方探针 import 在源树留下的字节码。两路各 2 条 discard 行，staged panel/data 空。**PKI 段竞态不可验**：沙箱无 easyrsa 二进制，两路同跑 `init_pki`＋`build-ca` 的竞态（`if not ca.crt.exists()` 先查后建）在沙箱测不到——须 live-8 在真机上以并发安装／并发重跑复核，见 §8。
- **D14 不可验（行为）＋代码级分析**：沙箱无 faketime，改系统时钟超出审计范围。代码面：锁定（`time.time()`）、会话（PERMANENT_SESSION_LIFETIME 12h，wall clock）、`sent_at` 重投、`checked_at` 全是墙钟，无一处单调时钟。时钟前跳→锁定提前解、会话提前过期、sent 命令提前重投；后跳→锁定延长、重投推迟。无单点故障（各路径独立读钟），仅记为已知时钟依赖，不立案。

## §3 全量复扫（历史 115 条逐条定性）

复扫宇宙：R8 的 115 条（104 已修＋2 部分＋1 未验＋8 未修）。定性口径与 R8 同款。复扫方法：先以 mtime 对账（§3.0）锁定自 R8 后动过的文件——仅 AE/AG/AH/AJ 六文件；其余文件 mtime 与 R8 §0 逐项一致，R8 实证沿用；六文件内的历史项本轮全部行为重验（§1/§2/§4）。

### §3.0 mtime 对账（R8 §0 → 本轮，UTC）

| 文件 | R8 mtime | 本轮 mtime | 结论 |
|---|---|---|---|
| panel/app.py | 09:22:36 | 12:20:44 | 动过（AH） |
| panel/templates/index.html | 09:20:59 | 09:20:59 | 未动 |
| egress/sk5_manager.py | 08:07:40 | 12:37:13 | 动过（AJ） |
| egress/policy-routing.sh | 09:49:04 | 12:13:01 | 动过（AG） |
| egress/README.md | 09:53:21 | 12:16:15 | 动过（AG） |
| verify.sh | 09:38:04 | 09:38:04 | 未动 |
| verify-integration.sh | 09:35:55 | 09:35:55 | 未动 |
| install.sh | 09:38:01 | 12:20:28 | 动过（AE） |
| core/openvpn_manager.py | 06:01:40 | 12:22:18 | 动过（AH） |
| core/easyrsa.sh | 06:01:36 | 06:01:36 | 未动 |
| agent/agent.py | 00:58:12 | 00:58:12 | 未动 |
| egress/test-egress.sh | 08:40:51 | 08:40:51 | 未动 |
| cloudflare/src/index.js | 09:24:00 | 09:24:00 | 未动 |
| README.md | 09:24:04 | 09:24:04 | 未动 |
| cloudflare/README.md | 09:21:16 | 09:21:16 | 未动 |
| panel/README.md | 09:21:25 | 09:21:25 | 未动 |
| docs/security.md | 02:48:50 | 02:48:50 | 未动 |
| core/README.md | 09:20:03 | 09:20:03 | 未动 |
| systemd/（5 单元） | — | 2026-11-11 23:49–2026-11-12 00:53 | 未动（无修复路碰过） |

### §3.1 R8 的 8 条未修 → 本轮全部关闭

| 项 | R9 状态 | 证据 |
|---|---|---|
| R7-BUG-1 install.sh SIGPIPE 141（高，阻塞） | **已修** | AE（§1a）：旧式慢写者 10/10 rc=141、新式 30/30 rc=0、错版本仍 rc=1；两处版本校验（:304-308、:346-350）均先存变量再 grep |
| R7-BUG-2 毒 panel.db＋agent_queue.json（高，阻塞） | **已修** | AE（§1a）：毒包安装新写法 panel/data 空＋2 条 discard 行；旧安装器（install-orig.sh，sha256 c69541de…与 live-7 一致）留毒；`_ensure_admin_password` 在清净目录生成 admin.pass 0600＋新 admin 行、在毒目录短路（对照成立）；源树 panel/data 已空 |
| R7-BUG-3 并发双重起（低） | **已修** | AH（§1c）：并发探针 51/51、Flask 35/35；`_SK5_MUTATE_LOCK` 六处取锁 |
| R7-BUG-4 do_status 源错（低） | **已修** | AG（§1b）：route-get 源 `10.8.0.2`→`10.8.0.1`（:342）；14/14 矩阵含 do_status 格；全树 `from 10.8.0.2` route-get 零处 |
| R8-P2-1 occupant-error 死分支＋误诊窗口 | **已修** | AG（§1b）：分支已删，失败报真实 `_err`＋“本次未改任何策略状态，重试安全”；变异：强制 EPERM＋外来规则在位时死报真实 “Operation not permitted”，“already used by” 零命中 |
| R8-P2-2 egress/README M4 失真记载 | **已修** | AG（§1b）：“策略路由的并发与幂等”节按内核真实语义重写（M4＝外来规则共存、启用 200）；见 §6 文档核对 |
| R8-P2-3 并发同名建用户幽灵 V 记录 | **已修** | AH（§1c）：并发同名一 200 一 409；`_sweep_orphan_index_entries` 删悬空 V 行（只留与 `issued/<名>.crt` 序列一致者、R/E 行保留、原子替换）；扫残留三格通过。余一沙箱边界：real easyrsa 的 gen-req 遇预存 key 行为仍未知，live-8 复核（§8） |
| R8-P2-4 ufw 长规则表静默跳过开端口 | **已修** | AE（§1a）：ufw 检查 :724-728 改 shell 内建匹配（全程无管道）；fake ufw 2000 规则时两 allow 均记日志、无规则／未启用时干净跳过 |

### §3.2 R8 的 2 条部分 → 本轮仍部分

| 项 | R9 状态 | 证据 |
|---|---|---|
| P0-3 bundle/install-agent.sh | **仍部分** | 逻辑已修（§1e/§4 载：Flask agent-bundle 格 200＋tarball 含 agent.py；verify.sh install-agent-script 200）；部署态未验（§5） |
| P1-7 改密＋首登强制改密 | **仍部分（按设计）** | 改密 API＋UI 在位（Flask 探针登录后改密，代码未动，沿用 R7/R8）；首登强制改密从未实现、文档已诚实，不另立案 |

### §3.3 R8 的 1 条未验 → 本轮仍未验

| 项 | R9 状态 |
|---|---|
| P0-1 部署态 | **仍未验**（§5：登录卡住＋KV 占位，与 R8 同卡点；第三次问用户，未复） |

### §3.4 R8 的 104 条已修 → 本轮复核

104＝R7 的 96（R1 28＋R2 13＋R3 16＋R4 4＋R5 3＋R6 6＋live 26）＋R8 转正 6（4 条 via 跨轮记账＋R1-P2-13＋R6-P2-4）＋live-6 的 2（R6-BUG-1/2）。分两组：

**（a）修复宿在六个动过文件内的项——本轮全部行为重验（§1/§2/§4），无一沿用旧证：**

| 文件 | 历史项 | 本轮证据 |
|---|---|---|
| install.sh | R3-BUG-2、R3-BUG-3、R3-BUG-6、R4-BUG-2、R6-BUG-2、R1-P0-5、R1-P2-8、R2-P2-8、R1-P1-9（复制清单侧） | §1a（版本/ufw/毒包/守卫 A/B）；§2 D8/D13（kill 窗口重跑清愈、并发安装 copy 段）；grep：`python3 - "$ADMIN_PASS"` 实码行 0（仅 :857 注释）、0600 传密 :864 在位、curl -w 单行 :779/:829＋变量捕获 :875/:882；D8 日志 “generated fresh panel secret key”；D13 staged 树含 systemd/；starter heredoc 由 verify.sh 一致性格 PASS |
| policy-routing.sh | R6-BUG-1、R4-BUG-1、R3-BUG-4、R4-P2-1、R1-P1-9（持久化侧） | §1b 14/14 矩阵＋三变异红证；§4 verify.sh 22/0/1（toggle/disable/egress-crosscheck 全过）＋T 变异 17/2/4；verify-integration 28/28 的 R4-BUG-1 A/B/B2 三格 |
| panel/app.py | R1-P1-5（Flask 侧）、R1-P1-6、R1-P2-5、R1-P2-10、R2-P1-4、R4-P1-1（Flask 侧）、R6-P1-1（Flask 侧）、R4-BUG-1（Flask 侧）、R5-P2-1、R7-P1-1（Flask 侧） | §1c Flask 35/35（via A/B/C/D、T2/T3/T5/T6、R1/R2、H2/H4、AA）；§2 D2 重投生命周期行为复验；§4 verify-integration 28/28（登录／状态／保存不重起／B1/B2／风暴 7 切） |
| core/openvpn_manager.py | R2-P1-1、R2-P1-3、R1-P1-10、R1-P1-11、R1-P1-13、R1-P2-6、R5-P2-2、R5-P2-3 | §4 Core 21/21（单测 5/5＋探针 16/16：C1 live-7 verbatim v2 行、C2 建用户＋CN、C3 重建拒、C4 列表、C5 非法名、C6/C7 吊销／重建、C8 幽灵吊销、C9a/b 端口锁、C10 无 daemon 诚实、C11 init_pki 拒、C12/C13 幂等） |
| egress/sk5_manager.py | R6-P2-1、R6-P2-2、R1-P1-8、R1-P1-12、R2-P2-7 | §1c Flask 35/35（H2/H4、T 网格、UoT 翻转）；§1d AJ 串行回归 13/13；§4 egress §6 矩阵 4/4 |
| egress/README.md | R6-P2-4、R3-P2-14 | §6 文档核对（AG 重写节与代码一致，门禁数 28，单向性注记存活） |

**（b）其余项——修复宿在未动文件内，R8 实证沿用（§3.0 mtime 逐项一致）：** agent/agent.py（13 格行为，R8 §4f 13/13）、cloudflare/src/index.js（Worker 18/18，R8 §1c）、core/easyrsa.sh（R5-P2-2 支撑）、egress/test-egress.sh（§6 矩阵本轮亦重跑 4/4，见 §4d）、verify.sh／verify-integration.sh（门禁本身，本轮重跑见 §4a/§4c）、panel/templates/index.html（AA 按钮在位，Flask 探针 DOM 断言）、各 README／docs/security.md／core/README.md（§7 逐条核对）。**R8 的 104 条中无一复发。**

### §3.5 U-1～U-12 认领表更新

| # | 项 | R9 更新 |
|---|---|---|
| U-1 | P0-1/2/3 部署态 | 仍未验（§5） |
| U-2 | R6-P1-1 真机复现 | Flask/Worker 沙箱侧均已闭合；真机策略缺失 case live-7 未显式重跑，留待 live-8 |
| U-3 | UDP 数据面 | 关闭（R8 已判；live-7 S1/S2＋test_sk5 双 true） |
| U-4 | R 符号链接自拷 | 关闭（无变化） |
| U-5 | R 逐项失败 die 分支 | 仍为“机制已证、分支未触发”：live-7 install3 全程跑通（die 分支未触发符合预期）；分支本身仍须一次人为致败才验得到 |
| U-6 | T 两变异 | 关闭（R8 已判；本轮 T 变异重跑 17/2/4，enable 两格恰红） |
| U-7 | verify-integration 瞬时红 | 关闭（本轮 28/28 一次，无瞬时红） |
| U-8 | 真机在位升级路径 | 关闭（R8 已判，live-7 §9）；补记：AE 的守卫 A（干净源重装保活库／队列）本轮沙箱已验，live-8 须在新树上重跑真机在位升级 |
| U-9 | KV 竞态与 POP 传播 | 仍未验（无部署） |
| U-10 | 前端渲染级核查 | **推进**：本轮静态对比度核查已做（§7，index.html 实际渲染值）；真机渲染仍归 live-8 |
| U-11 | easy-rsa 真二进制签发 | 关闭（R8 已判） |
| U-12 | live-R5 结果 | 关闭 |

复扫合计：115 条＝已修 112（104＋§3.1 关闭的 8 条：R7-BUG-1/2/3/4 与 R8-P2-1/2/3/4）／部分 2（P0-3、P1-7）／未验 1（P0-1）；**本轮新发现 4 条另计（R9-P1-1/2、R9-P2-1/2，见 §2）**。115＝112＋2＋1；新发现 4 条见 §8 差集。

## §4 套件重跑

### §4a 门禁 verify-integration.sh：28/28（本轮在 /tmp/r9 副本上实测）

`bash verify-integration.sh`（自带 venv＋pip flask、桩 systemctl/ip/sing-box、面板 nobody 身份、/etc 快照比对）：**PASS=28 FAIL=0 SKIP=0**。逐格：/etc 未碰、GET / 200、UI 入站卡／SK5 卡标记、未登录 401、登录 200、节点注册 token 只返一次、/api/status 三键齐全、保存禁用态不重起（两次全字段保存桩 run 仍 0 次）、B1 真翻转 enable 200 桩 run 恰 1 次、B2 disable 200 重起失败诚实上报、R4-BUG-1 格 A（7 次连续切换全 200，7 restart＋7 reset-failed，0 限流失败）、格 B（策略删除后重开 repaired=true、零重起）、格 B2（健康态重开纯无操作）、agent 配置 0600、get_status 全链 done、create_user 无 CA 时 failed（error 非空、无私钥泄露、无 token 泄露）。宿主 /etc 复核干净（§8.4）。

### §4b Flask 35/35（§1c）＋ Worker 18/18＋Agent 13/13

- **Flask 35/35**：§1c AH 复核时在当前树上重跑（真实 test_client＋真实 core/egress＋fake 外部世界），via A/B/C/D、T2/T3/T5/T6、R1/R2、H2/H4、AA 全格通过。本节不再重复数字。
- **Worker 18/18（沿用 R8 实证）**：`cloudflare/src/index.js` mtime 与 R8 §0 逐字节一致（09:24:00，未动），R8 §1c 的 18/18（via A–F＋init-pki＋cmd，变异改回 enabled 判据恰红五格）仍有效。本轮未重建 Worker 探针——代码未动，重建是重复劳动；部署态仍未验（§5）。
- **Agent 13/13（沿用 R8 实证）**：`agent/agent.py` mtime 与 R8 §0 一致（00:58:12，未动），R8 §4f 的 13/13 仍有效。

### §4c 门禁 verify.sh：分段运行 22/0/1＋T 变异 17/2/4

**运行形态（诚实交代）**：沙箱无 systemd、无 TUN、无 easy-rsa、无 openvpn 二进制，故 verify.sh 只能在分段环境（staged 树 `/tmp/r9-tests/vfy/vroot-base`＋真 Flask 面板 https://127.0.0.1:8443＋`unshare -m` 绑定 `/etc/openvpn-sk5-panel` 与 `/etc/sysctl.d` 到 /tmp、PATH 挂 fakebin-verify）下跑。本节所有数字都是**分段环境的数字**，不是真机数字；真机总验归 live-8。

分段搭建要点（探针/搭建自记）：(1) 面板 TLS 证书 openssl 自签（CN=127.0.0.1）、run-panel-tls.py 按 install.sh 模板生成；(2) PKI 用真实 core＋fake easyrsa 预建（CA＋server 证＋dh/ta/crl＋server.conf udp/1194）；(3) fake systemctl 的 MainPID 改为真实 sleep 进程 pid（R8 的 1234 不存在致 sing-box-steady 环境性 FAIL，本轮该格真通过）；(4) starter sing-box.json 从 install.sh:570-597 heredoc 原样提取——首版漏了这一步，sing-box-config 报“无渲染配置”（搭建缺口，非产品缺陷；真安装必写此文件）；(5) 首版 E3 式错误不在此节。

**基线（分段）**：**PASS=22 FAIL=0 SKIP=1**。22 格全绿：syntax、files、install-copies-agent、installed-agent-tree、openvpn、sing-box-version（1.11.15）、sing-box-config（`sing-box check` 真校验）、starter-template-consistency、sing-box-running、sing-box-steady（MainPID 真活、tun1 在位、restarts=0）、panel-reachable、panel-login、panel-status（openvpn.running=true）、agent-bundle、install-agent-script、user-ovpn（真建用户、.ovpn 含三段 PEM）、stub-socks5、sk5-toggle-on（rule=1 table100=1，vpn 路由 `1.1.1.1 from 10.8.0.1 dev tun1 table 100`）、egress-crosscheck、sk5-egress-ip（`egress.ip=2a04:4e41:c:6cbd::20db:6cbd via_sk5=true`，真实 egress IP 经 stub）、sk5-disable（rule=0 table100=0）、sk5-enable-endpoint。唯一 SKIP：direct-forwarding（沙箱无默认路由，环境性，与 R8 同）。

**T 变异（do_enable 的 add_rule 改为空操作，仅此一行，diff 已核）**：重跑（全新分段环境）**17/2/4**。FAIL 两格均为 enable 路径：sk5-toggle-on 与 sk5-enable-endpoint 同报 **500**，正文为 AG 的新措辞 `"policy rule did not stick after enable (from 10.8.0.0/24 lookup 100 not found); no policy state was changed by this call, retry the enable"`——自检在 enable 一步就 500 拦住（R8 的 T 变异同为两格红，但当时 sing-box-steady 因 restarts 累计＝6 另红一格；本轮变异跑用全新环境，restarts=0，steady 绿）。其余四格诚实 SKIP（链未起来）。结论：**门禁仍能抓住损坏的 apply，且比 R7 早一步、更响亮**；AG 的错误措辞改写未削弱 fail-closed。

### §4d Egress 套件：test-egress.sh §6 矩阵 4/4（X 的修法复验）

Harness：自写 SOCKS5 stub（no-auth CONNECT 中继）＋固定 IP 的本地 ifconfig.me 替身（fixedip.py，127.0.0.1:80，恒回 `203.0.113.99`）＋unshare 内绑定 `/etc/hosts`（宿主 hosts 副本＋ifconfig.me／merchant.test→127.0.0.1）与 `/etc/openvpn-sk5-panel`；链态（rule＋table 100＋tun1）由 AG 的内核忠实 fake-ip 置起；E3 的直腿走真出口代理 IPv6（NO_PROXY 不含 ifconfig.me，代理自解真实地址），SK5 腿走 stub→替身。

| 格 | 条件 | 期望 | 实测 |
|---|---|---|---|
| E1 回环 stub（SK5_HOST=127.0.0.1） | 现行脚本 | §6 SKIP、exit 0 | **PASS=5 FAIL=0 SKIP=2，exit 0** |
| E2 商户同 IP（SK5_HOST=merchant.test，双腿皆 203.0.113.99） | 现行脚本 | §6 FAIL“equals direct IP”、exit 1 | **PASS=5 FAIL=1 SKIP=1，exit 1**，FAIL 文案正是 `"SK5 egress IP equals direct IP (203.0.113.99) -- chain is not in effect"` |
| E3 商户异 IP（直腿真出口 IPv6、SK5 腿 203.0.113.99） | 现行脚本 | §6 PASS、exit 0 | **PASS=6 FAIL=0 SKIP=1，exit 0**，直腿 `2a04:4e41:50:6bdf::372:ebdf`、SK5 腿 `203.0.113.99` |
| NEG 阴性对照：pre-X §6（删回环豁免）＋回环 stub | 旧逻辑 | §6 FAIL（R5-BUG-1 签名） | **PASS=5 FAIL=1 SKIP=1，exit 1**，同款 FAIL——旧写法在同 IP 下必红，新写法只在商户端点红 |

探针自记：首版 E3 的 hosts 文件漏了 `ifconfig.me→127.0.0.1`，stub 把 CONNECT 解到真实 ifconfig.me、SK5 腿回了轮换 IPv6——比较仍 PASS 但理由是错的（两腿都是真出口轮换值）；补上 hosts 行后 SK5 腿恒为 203.0.113.99，E3 证据才成立。教训与 R8 §4d 同款：stub 的目标解析走绑定后的 hosts，直腿的解析走代理，两条路径须分别核对。

### §4e 五套件总览（本轮重跑报数）

| 套件 | 规模 | 结果 |
|---|---|---|
| Flask（§1c） | 35 | **35/35** |
| Worker（沿用 R8，代码未动） | 18 | **18/18**（R8 变异对照：判据改回 enabled → A×3、C、F 五格恰红） |
| Agent（沿用 R8，代码未动） | 13 | **13/13** |
| Core（§4f，本轮重跑） | 21（单测 5＋探针 16） | **21/21** |
| Egress（§4d §6 矩阵＋§1b policy 矩阵） | 4＋14 | **矩阵 4/4＋policy M1/M2/M3/M4/M4b/do_status/并发/压力全过** |
| verify-integration.sh（门禁，§4a） | 28 | **28/28** |
| verify.sh（门禁，§4c，分段） | 23 | **22/0/1＋T 变异 17/2/4** |

### §4f Core 套件 21/21（本轮重跑：core 已由 AH 改动）

**单测** `core/tests/test_status_log.py` **5/5**（bare-v1、comma-v2、tab-v2、prefixed-7、empty/missing；夹具为真机捕获行）。

**探针** `/tmp/r9-tests/adv/r9_core_probe.py` **16/16**（真实 `openvpn_manager`＋fake-PKI＋fake easyrsa/openvpn）：C1 live-7 verbatim v2 alice 行解析六字段一致；C0 PKI＋server 证＋server.conf；C2 建用户（.ovpn 含三段 PEM＋remote，openssl 验 CN=用户名）；C3 重建拒绝；C4 list_users；C5 非法名拒绝；C6 吊销标 R；C7 吊销后重建；C8 幽灵吊销拒绝；C9a/b 入口端口锁（无 allow 拒改、有 allow 才改）；C10 无 daemon 时 `server_status()` 诚实报 running=false 不抛错；C11 init_pki 无 force 拒绝；C12 同值重渲染；C13 build_server_cert 二次调用幂等。

## §5 P0-1/2/3：真实 wrangler deploy 重验——卡在登录，仍未验

- **dry-run 通过**（本轮重跑，wrangler 4.160.1 经 npx）：`npx wrangler deploy --dry-run` exit 0——读到 `panel/templates` 的 1 个 assets 文件（39.09 KiB / gzip 9.52 KiB），绑定列出 `env.PANEL_KV (REPLACE_WITH_KV_NAMESPACE_ID)` 与 `env.PANEL_MODE ("cloudflare")`。dry-run 只证配置可解析，不证部署。
- **真 deploy 卡在第一步：无登录**（本轮重跑，exit 1）：`In a non-interactive environment, it's necessary to set a CLOUDFLARE_API_TOKEN environment variable for wrangler to work.`（与 R7/R8 同一卡点；本机 `~/.config/.wrangler/` 下只有 logs＋metrics.json、无登录态，环境变量 `CLOUDFLARE_API_TOKEN` 未设置）。`wrangler.toml:32` 的 KV id 仍是占位符 `REPLACE_WITH_KV_NAMESPACE_ID`，是第二道卡点。
- **需要用户做的事（按顺序，缺一不可）**：(1) 在 Cloudflare 账号上建 API token（Workers＋KV 权限）并以 `CLOUDFLARE_API_TOKEN` 交给部署环境，或在可交互终端跑 `wrangler login`；(2) `wrangler kv namespace create PANEL_KV` 与 `--preview` 各一次，把返回的真实 id/preview_id 填进 `wrangler.toml`；(3) `wrangler secret put ADMIN_PASSWORD` 与 `wrangler secret put AGENT_BUNDLE_ORIGIN`；(4) `wrangler deploy`，再按 cloudflare/README:83 的要求换第二出口多点核（Workers 按 POP 慢速传播，单出口“没生效”不可信）。
- **结论**：P0-1/2/3（Worker 真实部署态）**仍未验**，与 R8 结论一致；Worker 代码侧的全部行为断言只在 mock KV＋本地 fetch 入口下成立，不是部署态证据。`--temporary` 未用——那会把 Worker 部署到临时抛弃账号上，不是用户的部署，测了也是冒充结论。

## §6 文档宣称全量核对（根 README／panel／cloudflare／security／flmx-reference／egress／core）

核对方法：每份文档的数字类宣称（门禁数、行数、端口、超时、重试上限、行号钉位）与行为类宣称逐条对代码/实测；数字以 `wc -l` 为准。

**通过的宣称**：
- 根 README:226 门禁数 28（本轮 verify-integration.sh 重跑 28/28 一致）；:198 哈希钉位 `install.sh:63-66`（实测该四行仍是四条 sha256 钉死值，AE 的改动全在其后）；:137 SK5 端口待确认注（1001 默认、9000 待回报，与面板字段旁注 index.html:470-471 一致）；:140 重建 CA 步骤 7（两次确认、force+confirm、缺一 400、Worker 已转发——与 §1c/§4a 实测一致）；:243 API 列表（init-pki 202＋cmd_id＋轮询）。
- egress/README “策略路由的并发与幂等”节（AG 重写）：M4 改为内核真实语义（:172 “priority 100 不是冲突——内核允许多个不同 selector”；:200 “外来规则共用 priority 100（启用 200、两条规则共存）全过”；:213 “M4 占用错误预期被真机证伪，见 R8-P2-1”）；验证数字与本轮一致（§6 矩阵 4/4：回环 5/0/2、商户同 IP 5/1/1、商户异 IP 6/0/1、pre-X 阴性对照 5/1/1；verify-integration 28/28；live-7 headline-1/2 引用准确）。
- docs/security.md:12 重投分歧：Flask `SENT_MAX_RETRIES = 3`（app.py:490）与 Worker 同值（index.js:86），120 秒超时、Worker 非幂等首超时即 failed 的分歧均有记载；两端上限一致的宣称属实。
- panel/README 的函数签名清单（§3.4(a) 逐项核对）：`create_user` 重名抛错＋legacy 先吊销再重签（core:812-820 在位）、`set_sk5` 部分合并语义、`test_sk5` TCP/UDP 分测——均与代码一致；`get_user_ovpn` 缺失的说明属实。
- cloudflare/README:126 via 语义与 :140 init-pki 转发（代码未动，沿用 R8）；server-mode.md:42 “待真实 wrangler deploy 验证”诚实（见 §5）；core/README（`web/` 已清）；docs/flmx-reference.md 的 FLMX 原做法列均标“不抄”。

**新发现（R9-P2-3，文档未同步——修复路改代码未同步改文档，与 R6-P2-4／R7-P2-6 同族）：**
- panel/README.md:55 称“`core/openvpn_manager.py` 1230 行、`egress/sk5_manager.py` 1088 行”，:57 与 :75 各重复一次“（已核对实物，1230 行）／（已核对实物，1088 行）”。实测：core **1404** 行（AH ＋174）、sk5_manager **1109** 行（AJ ＋21）。“已核对实物”在修复后已是假话。
- 根 README:204 的 starter-heredoc 行号钉位 `install.sh:531-558` 已过期：heredoc 现为 :570-597（AE 在其上插入约 39 行）；:531-558 现在指向 `panel.env` 的 heredoc（另一份 heredoc），钉位不仅漂移、且指错了对象。哈希钉位 :63-66 未受影响（AE 改动全在其后）。verify.sh 的 `starter-template-consistency` 格按 marker 提取 heredoc、不读 README 的行号，故门禁未受影响（本轮 22/0/1 中该格 PASS）。
- 修法：两处数字/行号按实测改（core 1404、sk5_manager 1109、heredoc :570-597）；建议把行号钉位改成 marker 提取或每次发版前跑一次数字核对，免得每轮修复都漂移。

## §7 前端静态对比度核查（本轮首次做；真机渲染归 live-8）

方法：跑 `panel/static/contrast-check.py`（WCAG 相对亮度；底线 4.5、目标 7；玻璃卡按白 72% 叠在 #f6f7fb 上估算有效底色 #fcfdfe），再把脚本的硬编码色值逐个对 index.html 原文核对（色值是否仍在用、玻璃透明度是否一致），另补算侧栏/顶栏（白 70%）、深色 toast、ghost 按钮三处脚本未覆盖的面。

**脚本结果：10/10 过底线 4.5（exit 0）；目标 7 达成 4/10。**

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

**色值核对（脚本未替你做的事，本轮补做）**：12 个色值在 index.html 全文各命中 1–2 处（`#1f2937` 1 处、`#4b5563` 2 处、`#2563eb` 2 处、`#b91c1c` 2 处、`#15803d` 2 处、`#166534` 1 处、`#dcfce7` 1 处、`#991b1b` 2 处、`#fee2e2` 1 处、`#1e40af` 1 处、`#1d4ed8` 1 处、`#f6f7fb` 2 处）——脚本的调色板与当前渲染一致，非过期快照。玻璃卡 `rgba(255,255,255,.72)`（:131/:144）与脚本假设一致。

**补算三面**：侧栏/顶栏白 70% 的有效底色 hex 舍入后与 72% 相同（#fcfdfe），四对正文/次要/链接/激活导航比值与上表一致（14.41／7.42／6.58／8.56）；深色 toast（#e5e7eb on 92% #111827）11.62；ghost 按钮（#1e40af on 白 85%）8.65——三面均过目标 7。

**托盘兜底**：body 底色为实色 #f6f7fb＋三道 6–10% 透明度的径向渐变（无壁纸图片，无 `url()` 背景）；全部文字都落在有自身底色的托盘上——玻璃卡（白 72%＋blur 16px）、侧栏/顶栏（白 70%＋blur 24/20px）、实色按钮、深色 toast（92% #111827）、弹窗卡——没有文字直接落在 body 渐变上。托盘兜底结构成立。

**结论**：静态核查通过底线（10/10，脚本 exit 0）；6 对低于目标 7（最低为成功绿字 4.92，仅高于底线 0.42），记为观察、不立案——门禁脚本的通过线就是底线，且 R7 九维视觉审计未以对比度立案。真机渲染（实际浏览器＋演示站、用户看过）仍归 live-8，这是静态核查替代不了的。

## §8 裁决与未验清单

### §8.1 裁决：**不能交付，差集 5 条**

| 级别 | 条目 |
|---|---|
| P1 | 2：R9-P1-1（队列 `sent_at` 无时区 → agent 全通道 500，须手改文件才恢复）、R9-P1-2（证书过期但 index.txt 仍为 V——面板显示 valid、重建 409） |
| P2 | 3：R9-P2-1（队列文件损坏 → 全部已排队命令静默丢失）、R9-P2-2（磁盘满时登录端点 500，正密码亦锁死）、R9-P2-3（panel/README 行数＋根 README heredoc 行号钉位过期） |
| 高（阻塞） | 0：R7-BUG-1/2 已由 AE 修好（§1a 行为＋变异红证）；R7-BUG-3/4 已由 AH/AG 修好 |
| P0 | 0 未修、1 未验：P0-1/2/3 部署态仍未验（§5）；P0-3 部分（按设计，部署态未定） |

差集＝5 条（2 P1＋3 P2）。R8 的 8 条差集已全部关闭（§3.1），历史 115 条中 112 条已修（§3.5）；AE/AG/AH/AJ 的修复本身本轮全部行为验证通过（§1，变异红证齐全），门禁变异每格独立红证（§1b、§4c），套件全绿（§4e）。但这不改变差集非空的结论：R9-P1-1 与 R9-P1-2 都是控制面／用户面的可用性缺陷——前者一个坏字段即可 wedge 全部 agent 命令且面板内无恢复，后者每张用户证 825 天后必然撞上（显示 valid、连不上、重建 409）。

**下一步（按用户常设流程）**：先派修复路（R9-P1-1/2＋R9-P2-1/2/3，文件归属：P1-1/P2-1/P2-2 在 panel/app.py，P1-2 在 core/openvpn_manager.py，P2-3 在文档——app.py 三项可同路同提交；core 与文档各一路；三路可并行），修完集成后跑 **AUDIT-R10（全量全局回头看，换推导方法独立复算）＋ live-8（真机总验）**，两路都过才交付。修复路开工前须先确认：本报告基线树版本（§0）与修复路所取树一致。

### §8.2 未验清单（逐项：为什么没验、谁能验）

1. **P0-1/2/3 真实 wrangler deploy（§5）**——卡在 Cloudflare 登录（非交互环境须 `CLOUDFLARE_API_TOKEN`，`~/.config/.wrangler/` 无登录态；wrangler.toml 的 KV id 仍是占位符）。谁能验：用户建 API token（或交互式 `wrangler login`）＋`wrangler kv namespace create PANEL_KV`（生产＋预览）填实 id＋`wrangler secret put ADMIN_PASSWORD`／`AGENT_BUNDLE_ORIGIN` 后，live 路跑真实 `wrangler deploy`，再从第二出口核 POP 传播。本轮不许用 mock 冒充。
2. **前端渲染级检查**——本轮只做了静态核查（§7：10/10 过底线 4.5、4/10 达目标 7、托盘兜底结构成立）。沙箱无浏览器渲染环境，真机渲染未做。谁能验：live 路在真机部署后做浏览器渲染检查（文字对比度目标 7／底线 4.5、托盘兜底），用户看演示站后才算过。
3. **Cloudflare KV 竞态＋POP 传播**——依赖第 1 项的真实部署；无部署则无从测。谁能验：同第 1 项，部署后多点核。
4. **SK5 端口 1001 vs 9000**——用户从未确认哪个是 SOCKS5 口（面板默认 1001，文档已标注待确认，README:137＋index.html:470-471）。谁能验：用户回报；live 路再以确认后的端口跑 UDP/TCP 双栈。
5. **R8-P2-3 的真 easyrsa 问题**——沙箱用 fake easyrsa，real easyrsa 的 gen-req 遇预存 key 是拒绝还是覆盖未知，决定并发同名建用户的真机后果。谁能验：live-8 在真机上跑并发同名建用户。
6. **D13 PKI 段竞态**——沙箱无 easyrsa 二进制，两路并发安装／重跑时 `init_pki`＋`build-ca` 的先查后建竞态测不到（copy 段已验，见 §2）。谁能验：live-8 在真机上跑并发安装／并发重跑。
7. **D14 时钟跳变**——沙箱无 faketime，改系统时钟超出审计范围；仅代码级分析（锁定／会话／重投／健康全是墙钟）。谁能验：真机上以 faketime 或受控调钟复核（须用户授权调真机时钟）。
8. **live-7 的 TCP 首连 120s 超时观察**——live-7 报告提及一次（首连超时 120s 后自愈），R9 沙箱无法复现 TCP 首连时序。谁能验：live-8 跟进。
9. **R8-P2-4 的真 ufw 验证**——本轮只做了机制复现（fake ufw，长规则表）；真 ufw 在长规则表宿主机上的行为须真机确认。谁能验：live-8（UFW 启用且规则表长的宿主机）或用户环境。
10. **R7-BUG-1/2 与 R8-P2-1/2/3/4 的修复变异红证（真机侧）**——沙箱侧变异红证已全（§1）；真机侧的一次启用／毒包安装／并发启用重起数／状态干净输出须 live-8 在真机上复核。谁能验：live-8。
11. **U-5 die 分支**——机制已证、分支未触发（live-7 install3 全程跑通）；分支本身仍须一次人为致败才验得到。谁能验：live-8 人为致败安装步骤。
12. **live-8 结论是否入本报告**——未入。live-8 与本轮并行在跑，其结论未落盘；本报告的沙箱结论不依赖它，live-8 落盘后须由主控对账（尤其 §8.2 的第 2/5/6/8/9/10/11 项）。

### §8.3 审计方法自述（供 R10 复核）

- 本轮方法：对抗操作员＋时间衰变推导（§2，D1–D14 每链落探针或明确不可验）＋历史全量复扫（§3，115 条，mtime 对账＋六文件内逐项重验）＋新代码逐项行为验证（§1，亲自重跑、零 monkeypatch 走真实代码路径、阴性对照齐全）＋套件重跑（§4，Flask/Worker/Agent/Core/egress/双门禁）＋P0 部署态重验（§5）＋文档宣称全量核对（§6）＋前端静态对比度核查（§7，首轮）。
- 探针纪律：凡套件格先红，必先查探针本身（本轮修掉的探针问题：D2 重投循环的 poll/age 时序错、D11 硬限额提不回（改软限额后恢复格补上）、E3 hosts 漏 ifconfig.me 致 SK5 腿走了真出口轮换 IP、verify.sh 分段缺 starter sing-box.json（搭建缺口）、AH guard B 探针把树摆错位置致 127 空跑——R9 重跑纠正后真通过）；探针修好重跑后才定性，不在探针 artifact 上立案。
- 沙箱边界：无 systemd／无 TUN／无 easy-rsa／无 openvpn 二进制／UDP sendto 临时端口 EPERM——凡涉此五项的结论均已标注分段环境或待真机（live-8），未把沙箱结论写成真机结论。
- 本轮审计侧污染两起，均已清净并记入报告：(1) §1c 的 `ensure_probe.py` 在宿主直接 import 面板代码，`_load_or_create_secret` 在宿主 /etc 生成 secret.key（已删）；(2) AH 修复路在树内留下的三个 `__pycache__`（core/panel/egress，12:34–12:37 UTC，gitignored 的字节码缓存）本轮已删；另两个旧缓存（agent/、core/tests/，07:32–07:45 UTC，非本轮）留置。教训：任何直接 import 产品代码的探针也必须进 unshare 绑挂，事后必复核 /etc 与树。

### §8.4 清理记录（审计结束时）

- 分段面板（verify.sh 两跑，各 https://127.0.0.1:8443）已停；SOCKS stub（:1080／:11080）与 fixed-IP 服务器（:80）已停；sleep  stand-in 已停；端口 8443/1080/11080/80 已空闲，无残留进程。
- 宿主 `/etc/openvpn-sk5-panel/`、`/etc/openvpn/`、`/etc/sysctl.d/99-openvpn-sk5.conf` 均不存在（每次 unshare 绑挂后都 rmdir 复核）；宿主 `/run/openvpn-sk5-panel/policy-routing.lock`（verify.sh 分段跑的 flock 锁文件，进程退出后已无持有者）已删，目录已清。
- 项目树核查：本轮只写了本报告一个文件；树内其余文件 mtime 未动（12:40 UTC 后除 `docs/live-verify-R8.md`（live-8 路落盘）外无其他新文件）；三个 `__pycache__`（见 §8.3）已删，基线未被污染。
- /tmp 资产（供 R10 复用）：`/tmp/r9`（树副本）、`/tmp/r9-venv`（Flask 3.1.3＋bcrypt）、`/tmp/r9-tests/`（ag 策略矩阵、adv §2 探针、egress §6 矩阵、vfy verify.sh 分段、install D8/D13），`/tmp/ah-tests/`（AH 探针＋fakebin＋venv）、`/tmp/aj-tests/`、`/tmp/ae-tests/`（AE 探针＋毒包＋install-orig.sh）。

# AUDIT-R8 — 全量全局回头看（交付前）

- 审计员：独立审计路（未参与建设与修复路 A–AD2；单审计员边做边写，不派子代理）
- 日期：2026-11-12（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R7 同等广度）
- 推导方法：**并发＋幂等＋失败原子性推导**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程均不同）——先枚举每一个会改状态的操作（enable/disable/restore、init_pki、create/revoke 用户、改密、节点注册/轮换、安装/重装、健康检查 fail-over），对每个操作推导四问：并发两次会怎样、失败一半时盘/daemon/内核三处状态是否一致、重试是否安全、守卫是否可能谎报（grep -q＋pipefail 的 SIGPIPE 同族、缓存过期、竞态窗口）；再叠加全量复扫（历史全部发现逐条复现定性）与 Y/Z/AA/AB/Y2/AC/AD/AD2 新代码逐项行为验证。live-7 与本轮并行在跑，其结论未入本报告的须在 §8 写明。
- 测试一律在 `/tmp` 副本（`/tmp/r8` 树副本、`/tmp/r8-tests/` 自建/复用套件）上跑；未动项目原文件；未动 `/etc`（探针进 `unshare -rm` 挂载命名空间，`/etc/openvpn-sk5-panel` 与 `/etc/sysctl.d` 绑 /tmp；事后 mtime 核对见 §8）；未动任何真机。需真机行为复核的项一律写“待 live-7”，不提前判通过。
- 语法基线：4 个 Python 文件 `py_compile` 全绿；7 个 shell 脚本 `bash -n` 全绿；Worker `node --check` 全绿（见 §0）。

## §0 树版本与 Y/Z/AA/AB/Y2/AC/AD/AD2 改动确认

当前树是 R7 修复路 Y/Z/AA/AB/Y2＋live-6 修复路 AC/AD/AD2 之后的新树。文件 mtime（UTC，原树）：

| 文件 | mtime (UTC) | 说明 |
|---|---|---|
| panel/app.py | 2026-11-12 09:22:36 | AA 路：POST /api/openvpn/init-pki（＋49 行，1858→1907） |
| panel/templates/index.html | 2026-11-12 09:20:59 | AA 路：重建 CA 按钮 |
| egress/sk5_manager.py | 2026-11-12 08:07:40 | U 路（未动） |
| egress/policy-routing.sh | 2026-11-12 09:49:04 | AC 路：flock 串行化＋add_rule 幂等＋grep -q 全改（352 行） |
| egress/README.md | 2026-11-12 09:53:21 | AC 路（最新改动） |
| verify.sh | 2026-11-12 09:38:04 | AD2 路（argv 清密码）＋AB 路：sk5-egress-ip 双断言 |
| verify-integration.sh | 2026-11-12 09:35:55 | AD 路（0600 文件传密码） |
| install.sh | 2026-11-12 09:38:01 | AD2 路（argv 清密码） |
| core/openvpn_manager.py | 2026-11-12 06:01:40 | S 路（未动） |
| core/easyrsa.sh | 2026-11-12 06:01:36 | S 路（未动） |
| agent/agent.py | 2026-11-12 00:58:12 | E/H 路（未动） |
| egress/test-egress.sh | 2026-11-12 08:40:51 | X 路（未动） |
| cloudflare/src/index.js | 2026-11-12 09:24:00 | Y 路：cachedStatus 判据＋Y2 路：init-pki 转发（1128→1172 行） |
| README.md | 2026-11-12 09:24:04 | Z 路：门禁数 28、FLMX 对齐要点重写 |
| cloudflare/README.md | 2026-11-12 09:21:16 | Z/Y2 路 |

与 R7 基线树（`/tmp/r7`）的 diff：仅上述 Y/Z/AA/AB/Y2/AC/AD/AD2 改动文件＋docs/（AUDIT-R7.md、live-verify-R6.md、live-verify-R7.md）有差异；其余产品文件逐字节一致。AC 的 `policy-fixed.sh` 与当前树 `egress/policy-routing.sh` **逐字节一致**（本轮 `diff -q` 实测），AC harness 可直接复用。

语法基线（本轮在 `/tmp/r8` 副本上实测）：`panel/app.py`、`egress/sk5_manager.py`、`core/openvpn_manager.py`、`agent/agent.py` 四文件 `py_compile` 全绿；`install.sh`、`verify.sh`、`verify-integration.sh`、`egress/test-egress.sh`、`egress/policy-routing.sh`、`core/easyrsa.sh`、`agent/install-agent.sh` 七脚本 `bash -n` 全绿；`cloudflare/src/index.js` `node --check` 全绿。行数：`panel/app.py` 1907 行、`egress/sk5_manager.py` 1088 行、`core/openvpn_manager.py` 1230 行、`cloudflare/src/index.js` 1172 行、`agent/agent.py` 910 行、`egress/policy-routing.sh` 352 行。

/tmp 资产现状（本轮开工时实测）：R7 的 `/tmp/r7-tests/`（五套件＋探针）与 `/tmp/r7-venv/`（flask 3.1.3＋bcrypt）幸存；`/tmp/ac-tests/`（AC harness：policy-fixed.sh、concurrent-enable.sh、matrix.sh、stress.sh）幸存；`/tmp/y-tests/`（Worker via 探针＋Worker 套件 Y 版）、`/tmp/y2-tests/`（无 init-pki 版 index.js）、`/tmp/aa-tests/`（init_pki 探针）、`/tmp/ab-tests/`（verify.sh AB 基线/T 日志）、`/tmp/ad2-tests/`（probe.sh）幸存。本轮策略：**复用 R7 套件但重指到当前树**——`/tmp/r8` 为当前树完整副本，`/tmp/r8-tests/` 为 `/tmp/r7-tests/` 的路径改写版（`/tmp/r7/`→`/tmp/r8/`、`/tmp/r7-tests/`→`/tmp/r8-tests/`，venv 仍用 `/tmp/r7-venv`）；verify.sh 变异驱动的 mutation 源树由 `/tmp/r7` 改为 `/tmp/r8`（`/tmp/r8-mut*`）。凡复用资产与当前树不一致处，先 diff 确认再用（policy-routing.sh 已确认逐字节一致；其余见各节）。

**接续者注（2026-11-12 18:35，主控核实）**：前任 18:17 被外部中断杀死后，`/tmp` 被清——上段列出的 `/tmp/r8`、`/tmp/r8-tests`、`/tmp/r7-tests`、`/tmp/r7-venv`、`/tmp/ac-tests`、`/tmp/y-tests`、`/tmp/y2-tests`、`/tmp/aa-tests`、`/tmp/ab-tests`、`/tmp/ad2-tests` 全部已不存在。本轮实际做法：从当前树重建 `/tmp/r8` 完整副本（`cp -a`，与原树逐字节一致）与 `/tmp/r8-tests/` 全套 harness（fakebin＋unshare＋探针，全部自写，见各节），venv 重建于 `/tmp/r8-venv`（flask 3.1.3＋bcrypt）。前任 §0 的 mtime 表与语法基线仍有效（本轮在 `/tmp/r8` 副本上复核：四 Python `py_compile` 全绿、七 shell `bash -n` 全绿、Worker `node --check` 全绿；行数 app.py 1907、sk5_manager.py 1088、core 1230、index.js 1172、agent.py 910、policy-routing.sh 352，与 §0 一致）。

## §1 Y/Z/AA/AB/Y2/AC/AD/AD2 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

### §1a AC 路（R6-BUG-1：并发竞态＋守卫谎报）——全部行为验证通过

Harness：`/tmp/r8-tests/`（自写；fake `ip` 按内核语义实现 rule 增删/优先级 EEXIST/route get 源校验、`systemctl`/`sing-box`/`iptables` 均有状态；`run-ac.sh` 在 `unshare -m` 下把 `/etc/sysctl.d` 与 `/etc/openvpn-sk5-panel` 绑到 /tmp；`policy-current.sh` 经 `diff -q` 确认与当前树 `egress/policy-routing.sh` 逐字节一致）。

| 格 | 期望 | 实测 |
|---|---|---|
| 并发启用 ×5 | 全 0、规则唯一 | PASS，rcs `0 0 0 0 0`，rules 仅 `100\|10.8.0.0/24\|100` |
| M1 空态启用 | 200、规则在位 | PASS |
| M2 规则已在位 | 200、不重复加 | PASS（"rule already present"） |
| M3 同 selector 异 priority（200） | 200、最终唯一、副本已删 | PASS（"removed duplicate rule … prio 200"） |
| M4 外来规则占 priority 100 | 失败、报可区分错误、原规则不动 | PASS，rc=1，文案点名占用者 `100: from 10.9.9.0/24 lookup 100`，并明示“本次未改任何策略状态，重试安全” |
| M4b 清占用后重启用 | 200 | PASS |
| 压力 enable/disable 交替 ×10 | 0 失败、终态干净 | PASS（另有 19 次交替在修桩后无 FAIL，见下注） |
| 阴性对照：旧式先查后加（无 flock）并发 ×2 | 一条 EEXIST | PASS，rcs `0 2`，一条 `RTNETLINK answers: File exists`——竞态在旧写法下可复现 |
| SIGPIPE 守卫谎报（旧 guard `grep -q`＋慢写者） | 守卫谎报“不在” | PASS：`ip rule show \| grep -q` 在 pipefail 下 rc=141，旧 guard 函数判“LIES absent”；新 guard（全量 grep）判 present |
| 并发 disable ×2 / enable＋disable 混合 | 全 0、终态自洽 | AC 报告有载；本轮未逐项重跑（见 §8） |

探针 bug 自记（已修，未误判产品）：首版 fake `iptables` 的 `-C` 分支恒 `exit 0`（脚本末尾无条件 `exit 0` 覆盖了分支返回值），致 `iptables_del` 死循环、一次 disable 挂 4 分钟；修为按分支返回值 `exit $rc` 后 enable/disable 均秒回。另 fake `ip` 初版在 `rule add` 分支用了函数外的 `local`，M4 报错文案一度混入桩报错，已修（`local` 只留函数内），重跑后 M4 文案干净。压力循环首轮亦因此桩 bug 中断一次（disable 1 FAIL 系我方 kill 掉挂死的 disable，非产品失败）；修桩后干净重跑 ×10 零失败。

### §1b AD/AD2 路（R6-BUG-2：密码进 python argv）——全部行为验证通过

- 全树 grep：`python3 - "$ADMIN_PASS"` 实码行三处全清（install.sh、verify.sh、verify-integration.sh 各 0；仅剩两处注释引述旧写法）。
- 同形实测（dummy 密码含引号/`$`/反斜杠，sleep 保活读 `/proc/<pid>/cmdline`）：旧写法阴性对照——密码明文在 cmdline 里可见，探针有效；新写法（0600 文件）python3 的 cmdline 只剩两个文件路径、environ 零命中、pass 文件模式 600、payload 特殊字符 round-trip 正确。
- verify-integration.sh 完整重跑：**28/28**（本轮在 `/tmp/r8` 副本上实测，见 §4a）。

### §1c Y 路（R7-P1-1：Worker via_sk5）——18/18，变异恰红五格

探针 `/tmp/r8-tests/worker_probe.mjs`（Node 24；mock KV＋真实 `fetch` 入口；先登录取 `panel_session`、注册节点 n1、直接往 KV 写 `status:n1` 快照、再 `GET /api/status`）。

| 格 | 期望 | 实测 |
|---|---|---|
| A 策略缺失＋探针活 | via=false、ip=null、error 点名策略路由 | PASS |
| B 策略在位＋探针活 | via=true、ip=203.0.113.7 | PASS |
| C 策略缺失＋探针死 | via=false、ip=null | PASS |
| D 策略在位＋探针死 | via=true（kill-switch 黑洞态）、ip=null | PASS |
| E 未启用 | via=false | PASS |
| F enabled 但缺 policy 字段 | 按缺失处理，via=false、ip=null | PASS |
| init-pki 未登录 401／缺 force 400／缺 confirm 400／单 confirm 400 | 各状态码 | PASS（Y2 部分，见 §1e） |
| init-pki force＋confirm | 202＋queued:true＋cmd 入 KV | PASS |
| POST /api/cmd | 202＋queued:true（W 回归） | PASS |

变异控制：把 `cachedStatus` 判据改回 `sk5.enabled`（仅此一行），A×3、C、F 五格恰红（A 报 `via_sk5:true, ip:203.0.113.7`——R7-P1-1 的谎言原样复现），其余 13 格仍绿。探针 bug 自记：首版把节点注册期望写成 200，实际注册返回 201，已修正（不是产品问题）。

### §1d Z 路（R7-P2-6/7/8/11 文档四条）——全树 grep 核对通过

- P2-6：根 README:226 门禁数现为 **28**。✓
- P2-7：`10.8.0.2` 全树仅剩 egress/README:41 一处——该句是“须用本机 tun 地址作源；10.8.0.2 是客户端地址、非本机源，内核拒绝查询”的解释句，属正当引述，非残留宣称。✓
- P2-8：`ConfigHash`/`wss://` 仅剩 `docs/flmx-reference.md` 的“FLMX 原做法”列，附“不抄”＋本产品实际说明。✓
- P2-11：panel/README 行数 1230/1088 与实测 `wc -l` 一致；根 README 哈希钉位 `install.sh:63-66`；core/README `web/` 零命中。✓

### §1e AA/Y2 路（R7-P2-9：重建 CA 面板路径＋Worker 转发）——35/35 Flask 探针＋Worker 18/18

Flask 探针 `/tmp/r8-tests/flask_probe.py`（真实 test_client＋真实 core/egress＋fake 外部世界；`unshare -m` 绑 /etc；状态缓存 10 秒故每格睡 11 秒；数据/SK5 目录全钉 /tmp）：

| 格 | 实测 |
|---|---|
| via A/B/C/D（策略缺失/在位 × 探针活/死） | 全部诚实（A via=false＋ip=null＋策略错误文案；B via=true＋ip=203.0.113.7；C via=false；D via=true＋ip=null） |
| T2 toggle-only enable（已健康启用）／T3 `POST /api/sk5/enable` | 各 ＋0 重起 |
| T5 toggle-only disable／T6 toggle-only enable | 各 ＋1 重起 |
| R1 策略丢失后全表单重开／R2 daemon 死后全表单重开 | 均 repaired=true，R1 ＋0 重起、R2 ＋1 重起 |
| H2 策略缺失＋fail-closed | action=policy_missing |
| H4 daemon 死＋fail-open＋策略在位 | action=failed_over_to_direct |
| AA init-pki：202 queued:true／缺 force 400／缺 confirm 400／未知节点 404／未登录 401／前端“重建 CA”按钮在位 | 全部 PASS |

合计 **35/35**。探针 bug 自记（已修，未误判产品）：(1) 首版 fake `systemctl` 末尾无条件 `exit 0` 覆盖了 `is-active` 的返回值，致 `_singbox_running()` 恒真、R2 未触发修复；修后重跑 R2 通过。(2) H4 初版漏恢复策略（H2 留下 policy=False），初判 policy_missing 属前置条件错，已补 `set_policy(True)`。(3) H4 初版把 fail-open 开关发成 `{"enabled": true}`，路由实际要 `{"fail_open": true}`——fail_open 根本没开，blackholed 是正确行为；修正字段后通过。Worker 侧 init-pki 见 §1c（401/400×3/202＋queued:true＋cmd 入 KV）。

### §1f U 路复核（R6-P1-1/P2-1/P2-2，Flask 侧）

§1e 的 Flask 探针 35/35 已覆盖 U 的全部行为断言：via A/B/C/D 四格诚实、toggle T2/T3/T5/T6 重起计数、R1/R2 修复收据、H2/H4 健康动作。U 的 Flask 侧修法在本轮树上仍成立。

### §4a 门禁 verify-integration.sh：28/28（AD/AD2 复验）

证据见 §1b：三处 `python3 - "$ADMIN_PASS"` 实码行（verify-integration.sh:280 已修、:305、:331）＋ `/proc/<pid>/cmdline` 实测（旧形泄漏、新形 0600 密码文件干净）＋全套件重跑 **28/28**。本节仅作编号占位，不重复数字。

### §4b 探针套件（Flask 35/35、Worker 18/18）——编号占位

Flask 探针 35/35（§1e）与 Worker 探针 18/18（§1c）已在 §1 中逐格报数；五套件总览见 §4e。本节仅补编号，使 §4a–§4f 连续。

### 4c. 门禁 verify.sh：分段运行 21/1/1（AB 复验）＋ T 变异

**运行形态（诚实交代）**：沙箱无 systemd、无 TUN、无 easy-rsa、无 openvpn 二进制，故 verify.sh 只能在分段环境（staged tree `/tmp/r8-vroot` ＋ 真 Flask 面板 https://127.0.0.1:8443 ＋ unshare -m 绑定 `/etc/openvpn-sk5-panel` 与 `/etc/sysctl.d` 到 `/tmp`、PATH 挂 fakebin）下跑。本节所有数字都是**分段环境的数字**，不是真机数字；真机总验归 live-7。

分段环境搭建中修掉的三个探针/搭建问题（均为搭建侧，非产品）：
- (a) verify.sh 必须在 unshare 内跑（与 R7 同做法）：宿主跑时 `CONFIG_DIR` 读宿主 `/etc`，sing-box-config 误报 FAIL；unshare 内绑定后通过。
- (b) fake `systemctl` 须把 `openvpn-sk5-singbox.service` 与 `openvpn-sk5-singbox` 归一化（去 `.service` 后缀），否则 is-active 读不到同一状态文件；另 `show -p MainPID --value` 须只印值，否则解析失败。
- (c) staged 树的 `egress/test-egress.sh` 须 `chmod 755`（真实安装时 install.sh:396 会 chmod，staged 树缺这一步）——否则 egress-crosscheck SKIP。
- 另：user-ovpn 格需真实 PKI：沙箱无 easy-rsa/openvpn 二进制，写了一个 openssl 支撑的 fake `easyrsa`（init-pki/build-ca/gen-req/sign-req/gen-dh/revoke/gen-crl）＋ fake `openvpn`（--version/--genkey secret），用真实 `core/easyrsa.sh init`＋`build-server` 造出 CA＋server 证＋dh.pem＋ta.key＋crl.pem（index.txt 为 v2 形 `V … unknown /CN=server`）；OPENVPN_CA_DIR/OPENVPN_SERVER_DIR 环境变量指向 `/tmp/r8-vpki`、`/tmp/r8-vserver`（server.conf 由真实 `render_server_conf(udp,1194)` 渲染）。fake easy-rsa 只用于分段搭建，不进入产品树。

**基线（变异前，分段，2026-11-12 11:00 UTC）**：**PASS=21 FAIL=1 SKIP=1**。
- PASS 包括 AB 的三格：sk5-toggle-on（rule=1 table100=1，vpn 路由 `1.1.1.1 from 10.8.0.1 dev tun1 table 100`，host 路由仍走 main）、sk5-egress-ip（`egress.ip=2a04:4e41:34:6102::a133:e102 via_sk5=true`，真实 egress IP 经 stub）、sk5-disable、sk5-enable-endpoint；另 user-ovpn PASS（真实建用户 verify-1794481196，下发的 .ovpn 含 `<ca>/<cert>/<key>` 三段 PEM＋client/remote 行）、egress-crosscheck PASS（test-egress.sh exit 0，链起时）、sing-box-config PASS（`sing-box check` 真校验渲染配置）、starter-template-consistency PASS。
- 唯一 FAIL：**sing-box-steady（环境性，非产品缺陷）**：`active=active, main PID=1234, restarts=0` 三要素全对仍 FAIL——因为校验还要求 `kill -0 1234`（沙箱无此进程，fake `show` 只印数字）与 `ip link show dev tun1`（校验时刻链尚未启用，tun1 不存在）。同格在 R7 亦为环境性 FAIL（彼时是 sing-box-running FAIL 致其 SKIP）。sing-box-running 本轮 PASS 亦**只算 fake 状态**（fake systemctl 的 active 标志无真实进程寿命支撑），不作证据。
- 唯一 SKIP：direct-forwarding（fake ip 无默认路由，无法校验转发路径；环境性）。

**T 变异（AB 变异，apply 改 no-op）**：把 `/tmp/r8-vroot/egress/policy-routing.sh` 的 `do_enable` 中 `add_rule` 调用改为空操作（其余不动），重跑 verify.sh 两次，结果一致：**16/3/4**。FAIL 三格：sk5-toggle-on（**500**，正文 `"policy rule did not stick after enable (from 10.8.0.0/24 lookup 100 not found); no policy state was changed by this call, retry the enable"`）、sk5-enable-endpoint（同 500）、sing-box-steady（环境性，restarts 累计=6）。SKIP 四格：sk5-egress-ip、egress-crosscheck、sk5-disable、direct-forwarding（均为“链未起来”所致的诚实 SKIP）。
- 与 R7 时 AB 变异（17/3/3，toggle-on 与 sk5-egress-ip 双红）的**差异有因**：AC 在 `do_enable` 末尾加了自检（规则＋路由未落盘即 500），所以同一个 apply 损坏现在**在 enable 一步就 500 拦住**，sk5-egress-ip 走不到“读到过期快照空过”的分支，只能 SKIP 而非 FAIL。结论：**门禁仍能抓住损坏的 apply，只是比 R7 早一步、更响亮**；AB 那格的空过场景（enable 200 但路由未切）已被 AC 的自检堵死——除非将来有人拆掉自检，届时 AB 格仍会红。变异后已恢复原文件（`diff` 确认 vroot 与树一致），基线重跑恢复 **21/1/1**。

### §1g AC 变异红证（flock / add_rule / dedup 各一）＋ M4 桩模型修正

**M4 桩模型失真（live-7 §11 指出，本轮复核成立）**：AC 的 fake-ip 把 priority 建模为独占键（同 priority 第二条规则即 EEXIST），据此 M4 预期“外来规则占 priority 100 → rc=1＋占用错误”。真机内核允许多个不同 selector 共用同一 priority，`ip rule add` 仅在规则完全相同时才报 EEXIST。live-7 真机实测：外来 `100: from 10.9.9.0/24 lookup 100` 在位时面板启用 → **200**，终态两条 priority 100 规则共存、流量正常走 SK5——产品行为正确，AC 的 M4 预期是错的。
- 本轮已把 fake-ip 改为内核忠实语义（仅完全相同的规则 EEXIST，不同 selector 可共用 priority），重跑矩阵：**M1/M2/M3 仍过；M4 改为 rc=0、两条 priority 100 规则共存（与 live-7 真机一致）**；并发启用 ×5 全 0、规则唯一。§1a 的 M4 结论（“占用错误分支通过”）**作废**，改判如下。
- **裁决（R8-P2-1，见 §8）**：`add_rule` 的 occupant-error 分支（“priority 100 已被 X 占用”）在真机上基本不可达——它是桩模型失真带进来的死代码。产品行为无错（启用 200 是对的）；该分支本身无害，但存在误诊窗口：若 add 因 EEXIST 之外的原因失败（如 EPERM），而 priority 100 上恰好有一条外来规则，报错会把原因误指为“被占用”（通用 fallback 分支只在查无占用者时才报真实 `_err`）。修法方向：删掉 occupant 分支、失败即报真实 `_err`，或保留作防御但降级为提示。

**MUT-AC1 flock 移除——分支级红证（出口码级不红，诚实记录）**：把 `acquire_lock` 的 flock 改为空操作，并发启用 ×5：rcs 全 0、规则唯一——出口码不红。但日志级红了：无 flock 时 5 路中有 **2 路走进 `"rule already present (added concurrently)"`**（即其 `ip rule add` 已撞 EEXIST、靠 re-check 兜回）；对照组（现行脚本，flock 在位）并发 ×5：4 路走 `"rule already present"`（guard 短路），**`"(added concurrently)"` 分支 0 次触发**。结论：flock 确实在工作（串行化后竞态分支永不触发）；re-check 是第二道防线（flock 没了也能兜住出口码）。另：混合 enable＋disable 风暴 ×50（逐轮查盘/内核一致性）无 flock 时亦 0 不一致——因脚本内操作次序不对称（disable 的 del＋flush 在前、enable 的 add＋replace 在后且有 tun 前置耗时），竞态窗口天然错开；flock 的剩余价值是防时序变化的纵深防御，面板层存盘/应用的竞态它本来也管不到（见 R7-BUG-3）。
- 探针自记：fake-ip 的 add 非原子（先 grep 后追加、无锁），旧式并发 ×5 时状态文件里出现过重复规则行——这是桩的非原子性人工痕迹（真内核的 add 是单系统调用、第二路必 EEXIST），不作产品证据；竞态信号以 EEXIST 本身为准。

**MUT-AC2 add_rule 还原旧式先查后加——出口码级红证**：用旧式脚本（`policy-oldstyle.sh`，先查后加、无 flock、grep -q guard）并发启用 ×2 → rcs `2 0`、一条 `RTNETLINK answers: File exists`；×5 → rcs `0 2 2 0 2`、三条 EEXIST。旧写法下 R6-BUG-1 竞态可复现；现行幂等 add＋flock 下同测全 0。红证成立。

**MUT-AC3 dedup 移除——出口码级红证**：删掉 `add_rule` 内的三处 `dedup_rule` 调用，M3（同 selector 在 prio 200 预置副本）重跑：rc=0，但终态规则**两条共存**（`200|10.8.0.0/24|100` 未被清除），对照组（现行脚本）终态唯一。红证成立。

### §1h live-7 新 bug 的 R8 独立复核（R7-BUG-3 / R7-BUG-4）

- **R7-BUG-3（低，不阻塞；本轮沙箱复现成立）**：并发相同启用双双完整重起 daemon。机理：面板 `set_sk5` 的有效态检查只覆盖串行调用；并发两路都在对方写盘前读到旧态（enabled=false），双双走完整渲染＋重起；面板层无串行化。沙箱复现（分段面板＋fake systemctl 重起计数）：先禁用、重起计数清零，两路 `POST /api/sk5 {"host":"127.0.0.1","port":11080,"enabled":true}` 同时发出 → **双 200，restarts delta=2**，终态 enabled=true、policy=true、singbox_running=true——与 live-7 真机（Started 118→120，delta 2）一致。终态正确、隧道未断；多一次重起而已。修法方向（供修复路）：面板层对 set_sk5 加锁或以 CAS 语义复核有效态。R6-P2-2 族的并发变体。
- **R7-BUG-4（低，不阻塞；本轮沙箱复核成立，真机已裁决）**：`do_status`（policy-routing.sh:324-336）的 VPN 源 route-get 用 `from 10.8.0.2`。10.8.0.2 是客户端地址、从不是本机地址，内核永不接受作源。沙箱 fake-ip（内核忠实源校验）下 `./policy-routing.sh status`：`--- route-get: VPN user source ---` 一段报 `Error: argument "10.8.0.2" is wrong: invalid source address / RTNETLINK answers: Invalid argument`，脚本 exit 0（`|| true` 兜底）；live-7 真机同段为 `RTNETLINK answers: Network is unreachable`，而正确源 `from 10.8.0.1` 同机实测回 `1.1.1.1 from 10.8.0.1 dev tun1 table 100`。诊断输出错误、非功能故障；但运维人员照此输出会误判链路已断。R3-BUG-4 同族（N 路修门禁脚本的三处 route-get 源，do_status 漏网）。修法：改成 `from 10.8.0.1`。本轮 §1 初稿的“立案 P2”改为以 live-7 的真机裁决为准：**R7-BUG-4（低）**。

### §4d Egress 套件：test-egress.sh §6 矩阵全复制（X 的修法复验）

Harness：自写 SOCKS5 stub（no-auth CONNECT 中继）＋固定 IP 的本地 ifconfig.me 替身（`fixedip.py`，127.0.0.1:80，恒回 `203.0.113.99`）＋ unshare 内绑定 `/etc/hosts`（ifconfig.me→127.0.0.1、merchant.test→127.0.0.1）与 `/etc/openvpn-sk5-panel`；链态（rule＋table 100＋tun1）由 fake-ip 置起。直接 curl 走出口代理时 egress IPv6 逐请求轮换（本轮实测四次四值），故“同 IP”格必须用固定 IP 替身才可确定性复现——X 的矩阵亦依赖同款确定性。

| 格 | 条件 | 期望 | 实测 |
|---|---|---|---|
| E1 回环 stub（SK5_HOST=127.0.0.1） | 现行脚本 | §6 SKIP、exit 0 | **PASS=5 FAIL=0 SKIP=2，exit 0** |
| E2 商户同 IP（SK5_HOST=merchant.test，双腿皆 203.0.113.99） | 现行脚本 | §6 FAIL“equals direct IP”、exit 1 | **PASS=5 FAIL=1 SKIP=1，exit 1**，FAIL 文案正是 `"SK5 egress IP equals direct IP (203.0.113.99) -- chain is not in effect"` |
| E3 商户异 IP（直腿走真出口代理 IPv6、SK5 腿 203.0.113.99） | 现行脚本 | §6 PASS、exit 0 | **PASS=6 FAIL=0 SKIP=1，exit 0** |
| NEG 阴性对照：pre-X §6（删回环豁免）＋回环 stub | 旧逻辑 | §6 FAIL（R5-BUG-1 签名） | **PASS=5 FAIL=1 SKIP=1，exit 1**，同款 FAIL——旧写法在同 IP 下必红，新写法只在商户端点红 |

结论：X 的修法（回环端点只断言活性、商户端点保留全比较）在本轮矩阵下全部成立；R5-BUG-1 的关态天花板在真机上亦已由 live-7（关态 23/0/0）终验。探针自记：(1) 198.19.0.2 作“商户地址”不可行——沙箱把发往本机公网 IP 的包经网关 198.19.0.1 送出、永不回环到本地监听，改用 merchant.test 主机名（case 语句认作商户、解析仍走本地 stub）才绕过；(2) 绑定 /etc/hosts 时首版漏了 `hatch-egress-proxy → 198.19.0.1` 行，代理解析走公网 DNS 被重置，direct 腿一度 `<unreachable>`——补全宿主 hosts 内容后恢复；(3) 直接腿须把 ifconfig.me 加进 NO_PROXY 才 bypass 出口代理、命中固定 IP 替身，否则 direct 恒为真出口 IPv6、E2 永远做不成“同 IP”。

### §4e 五套件总览（本轮重跑报数）

| 套件 | 规模 | 结果 |
|---|---|---|
| Flask（§1e flask_probe.py：via/T/R/H/AA 全格） | 35 | **35/35** |
| Worker（§1c worker_probe.mjs：via A–F＋init-pki＋cmd） | 18 | **18/18**（变异对照：判据改回 enabled → A×3、C、F 五格恰红） |
| Agent（§4f，见下） | 13 | **13/13** |
| Core（§4f，见下：status-log 单测＋PKI 探针） | 18（单测 5＋探针 13） | **18/18** |
| Egress（§4d test-egress.sh §6 矩阵＋§1a/§1g policy 矩阵） | 4＋8 | **矩阵 4/4（E1/E2/E3/NEG）＋ policy M1/M2/M3/并发/压力全过，M4 按内核忠实语义改判（见 §1g）** |
| verify-integration.sh（门禁，§1b） | 28 | **28/28** |
| verify.sh（门禁，§4c，分段） | 23 | **21/1/1（唯一 FAIL 为环境性 sing-box-steady）＋ T 变异 16/3/4** |

### §4f Agent 套件 13/13 ＋ Core 套件 18/18

**Agent 套件**（`/tmp/r8-tests/agent_probe.py`，真实 `agent.py --once`＋可编程 fake 面板，plain HTTP，token 校验＋命令队列＋report 记录；fakebin＋fake easyrsa/openvpn；CA/服务/SK5 目录全钉 /tmp）：

| 格 | 实测 |
|---|---|
| A1 空轮询 | 0 命令、rc=0 |
| A1b 配置文件 0644 被收紧 | load 后 0600 |
| A2 get_status | report ok=true，result 含 openvpn/users/sk5/egress_ip/health |
| A3 未知 action `rm -rf /` | ok=false，`unknown action: rm -rf /` |
| A4 夹带 param `{"command": "id"}` | ok=false，`forbidden param: command` |
| A5 params 非对象 | ok=false，`params must be an object` |
| A6 无 id 的畸形命令 | 跳过、零 report、rc=0 |
| A7 init_pki force 无 confirm | ok=false，`resend with confirm=true` |
| A8 init_pki force＋confirm | ok=true，CA 真生成（ca.crt 在位） |
| A9 set_sk5 enable | ok=true，fake 内核规则 `100\|10.8.0.0/24\|100` 在位 |
| A10 test_sk5 | tcp_ok=true、udp_ok=false（stub 只做 TCP，拒绝 UDP ASSOCIATE——正确行为）、egress_ip=203.0.113.99 |
| A11 错 token | poll 401，日志 `poll failed`，rc=1，不崩 |
| A12 面板失联 | `poll failed`，rc=1，不崩 |

探针自记：首版 `reports` 列表未逐格清空，A3–A7/A10 读到 stale 的 A2 报告而误判 FAIL——修为每次 `run_agent()` 前清空后重跑 13/13。A11/A12 的 rc=1 是产品在 `--once` 下轮询失败的返回码（非套件失败）。

**Core 套件**（`core/tests/test_status_log.py` **5/5**＋`/tmp/r8-tests/core_probe.py` **13/13**，真实 `openvpn_manager`＋fake-PKI `/tmp/r8-vpki`＋fake easyrsa/openvpn）：
- 单测 5/5：bare-v1、comma-v2、tab-v2、prefixed-7、empty/missing（夹具为真机捕获行，见文件头）。
- 探针 C1：用 **live-7 §5 的 verbatim v2 行**（`CLIENT_LIST,alice,10.200.0.2:37519,10.8.0.2,,3562,3549,2026-11-12 10:39:45,1794479985,UNDEF,0,0,AES-256-GCM`）解析——alice 六字段与 live-7 面板输出逐字段一致；注意解析器**不保留第 13 列 cipher**（live-7 面板输出同样无 cipher 字段，行为一致；首版探针误断言 cipher 而 FAIL，已修正为按实际返回字段断言）。
- C2–C13：建用户（.ovpn 含三段 PEM＋remote，openssl 验 CN=用户名）、重建拒绝、list_users、非法名拒绝、revoke（index.txt 标 R）、revoke 后重建、revoke ghost 拒绝、入口端口锁定（无 allow 拒改、有 allow 才改）、无 daemon 时 `server_status()` 诚实报 running=false 不抛错、init_pki 无 force 拒绝。探针自记：首版非幂等（重跑时用户已存在、server.conf 已是 tcp/443），已改为每轮唯一用户名＋开局复位 udp/1194。

## §5 P0-1/2/3：真实 wrangler deploy 重验——卡在登录，仍未验

- **dry-run 通过**（2026-11-12 11:59 UTC，wrangler 4.160.1 经 npx，本机无全局 wrangler）：`npx wrangler deploy --dry-run` exit 0——读到 `panel/templates` 的 1 个 assets 文件（39.09 KiB / gzip 9.52 KiB），绑定列出 `env.PANEL_KV (REPLACE_WITH_KV_NAMESPACE_ID)` 与 `env.PANEL_MODE ("cloudflare")`。dry-run 只证配置可解析，不证部署。
- **真 deploy 卡在第一步：无登录**。`npx wrangler deploy`（同版本、同目录）报错：`In a non-interactive environment, it's necessary to set a CLOUDFLARE_API_TOKEN environment variable for wrangler to work.`（与 R7 09:12 的尝试同一卡点；本机 `~/.config/.wrangler/` 下无任何登录态，环境变量 `CLOUDFLARE_API_TOKEN` 未设置）。部署连 KV 占位符校验一步都没走到——占位符 `REPLACE_WITH_KV_NAMESPACE_ID` 仍在 `wrangler.toml` 里，是第二道卡点（填之前 deploy 会报错，见 README:31 的故意设计）。
- **需要用户做的事（按顺序，缺一不可）**：(1) 在 Cloudflare 账号上建 API token（Workers＋KV 权限）并以 `CLOUDFLARE_API_TOKEN` 交给部署环境，或在可交互终端跑 `wrangler login`；(2) `wrangler kv namespace create PANEL_KV` 与 `--preview` 各一次，把返回的真实 id/preview_id 填进 `wrangler.toml`；(3) `wrangler secret put ADMIN_PASSWORD` 与 `wrangler secret put AGENT_BUNDLE_ORIGIN`；(4) `wrangler deploy`，再按 cloudflare/README:83 的要求换第二出口多点核（Workers 按 POP 慢速传播，单出口“没生效”不可信）。
- **结论**：P0-1/2/3（Worker 真实部署态）**仍未验**，与 R7 结论一致；Worker 代码侧的全部行为断言（via 判据、init-pki 转发、cmd 队列）只在 mock KV＋本地 fetch 入口下成立（§1c/§1e），不是部署态证据。`--temporary` 未用——那会把 Worker 部署到临时抛弃账号上，不是用户的部署，测了也是冒充结论。

## §7 文档宣称全量核对（根 README／panel／cloudflare／security／flmx-reference／egress／core）

核对方法：每份文档的数字类宣称（门禁数、行数、端口、超时、重试上限）与行为类宣称（按钮、接口、转发、语义）逐条对代码/实测；与 R7 的 Z 路结论交叉复核。

**通过的宣称**：
- 根 README:226 门禁数 28（与 verify-integration.sh 实际 28 格一致，本轮重跑 28/28）；:55 无 git 仓库、走 `scp -r`（AA 修后，树确无 remote）；:137 SK5 端口待确认注（1001 默认、9000 待回报，与面板字段旁注一致）；:140 重建 CA 步骤 7（两次确认、force+confirm、缺一 400、Worker 已转发——与 §1e/§1c 实测一致）；:243 API 列表（init-pki 202＋cmd_id＋轮询）。
- panel/README 行数 1230/1088 与 `wc -l` 一致（§1d）。
- cloudflare/README:126 via 语义（Y 修后）与 :140 init-pki 转发（Y2 修后）与 §1c 探针一致；server-mode.md:42 “待真实 wrangler deploy 验证”诚实（见 §5）。
- docs/security.md:12 重投上限：Flask `SENT_MAX_RETRIES = 3`（app.py:490）与 Worker 同值（index.js:86），Worker 侧非幂等首超时即 failed 的分歧亦有记载；两端上限一致的宣称属实。
- core/README（`web/` 已清，见 §1d）；docs/flmx-reference.md 的 FLMX 原做法列均标“不抄”（§1d）。
- egress/README 的 flock 语义：锁路径 `/run/openvpn-sk5-panel/policy-routing.lock`、等锁 20 秒、面板子进程超时 30 秒（sk5_manager.py:347/357 显式 `timeout=30`）、`status` 不加锁、do_restore 内调 do_enable 故锁只在分发处取一次——与代码逐条相符；dedup/rollback/自检/daemon-盘分裂的取舍说明亦与代码一致。

**新发现（R8-P2-2，文档与真机地面事实不符）**：egress/README “策略路由的并发与幂等”一节仍按 AC 的失真桩模型写事实：
- :149-150 “复现：内核语义桩（priority 已占即 EEXIST）”——把 priority 独占说成内核语义，实为桩的人工设定；真机内核允许多 selector 共用同一 priority（live-7 §11）。
- :168-171 “priority 100 被外来规则占用时不静默成功、也不自动换 priority——报错点名占用者”——把 occupant-error 分支写成现行行为；真机上该分支基本不可达（外来规则在位时启用返回 200、两条规则共存）。
- :193-194 “形态矩阵……外来占用 priority 100（可区分报错、原规则不动、清掉占用后重启用 200）全过”——该格已被 live-7 真机证伪。
- :197 的门禁数（egress 20/20、verify.sh 20/1/2）是 AC 当时的数字；“真机终验待 live-7”现已过时（live-7 已跑完并部分证伪 M4）。
修法方向：该节按内核真实语义重写——occupant-error 分支标为防御性死代码（或随 R8-P2-1 一并删掉），矩阵 M4 格改为“外来规则共存、启用 200”，验证数字更新为本轮。

## §2 并发＋幂等＋失败原子性推导（本轮推导方法）

枚举全部 12 个改状态操作，逐个推导四问（并发两次／失败一半三态一致性／重试安全性／守卫谎报）。标注：【实测】＝本轮行为证据；【代码】＝源码推导，未逐项实测；【live-7】＝真机结论。

| 操作 | 并发两次 | 失败一半（三态：盘／daemon／内核） | 重试安全 | 守卫谎报 |
|---|---|---|---|---|
| enable（SK5） | 【实测】双 200、restarts＋2（R7-BUG-3，沙箱＋live-7 一致）；终态一致 | 【实测】save-after-success（Q）：失败时盘仍 false；AC 自检＋只回滚本次加的规则（§1a/§1g） | 是，整条重跑幂等 | `rule_exists` 全量 grep（AC）；`_chain_effective` 查 daemon＋策略双条件，非只看盘 |
| disable（SK5） | 【代码】双 200；各走完整渲染＋重起（＋2），终态一致（direct） | 【代码】O 规则：先写盘 false、重起 best-effort 失败亦报 honest 字段，不 500 | 是 | 同上 |
| enable＋disable 混跑 | 【实测】脚本层 ×50 混跑 0 不一致（操作次序不对称：disable 的删＋清在前、enable 的加＋换在后）；【代码】面板层存盘／应用不在同一锁内，盘与内核仍可短暂分裂——但下次状态读取诚实报有效态、下次全表单保存走 repair 分支自愈（R4-BUG-1），属可见＋可修的分裂，非静默撒谎 | — | 是 | — |
| restore／repair（开机＋补策略） | 【代码】flock 串行化脚本调用；与 enable 混跑同上表 | 【实测】R1/R2（§1e）＋live-7 headline-4：策略丢零重起补、daemon 死恰一重起，`repaired:true` | 是 | repair 后复核 `_chain_effective`，失败即 raise 不谎报成功 |
| init_pki | 【代码】面板层两次 force＋confirm 均 202 入队；agent 逐条执行，第二条会抹掉第一条刚建的 CA（终态仍是一份新鲜 CA；两 rebuild 之间签发的用户证书被废）。破坏性操作本就要求双重确认；面板层无相同命令去重／串行化 | 【代码】agent 先 init（抹 CA）后 build-server：build 若失败，CA 已抹、服务无 CA——面板拒建用户直到重跑 init；无中间态残留用户证书可误用 | 是（再跑一次即重建），但每次重建都废全部用户证书 | agent 侧 force＋confirm 双重校验（A7/A8 实测）；面板侧同款校验（§1e） |
| create_user | **【实测】新发现，见 R8-P2-3**：并发同名双 200（串行时一 200 一 409），index.txt 留两条同 CN 有效序列（0E/0F），列表只显后一条 | 失败一半：build-client 在 guard 后写文件；第二路写盘中途失败即留半套 issued/req/private 文件——下次同名重建时 create_user 先清 stale 文件（docstring），自愈 | 串行重试安全（409）；并发重试即本 findings | `_user_status` 取“最后一条”——幽灵条目被 last-wins 遮住（见 R8-P2-3） |
| revoke_user | 【代码】双 revoke：首条标 R，第二条 easyrsa 拒（已吊销）→ 报错非静默成功；终态 revoked | 【代码】revoke（改 index.txt）与 gen-crl（产 crl.pem）在同一 easyrsa.sh 调用内（`set -e`）：gen-crl 若失败，index 已 R 但 crl.pem 仍是旧的——面板报 500 而吊销实际已记；重试即 409“已吊销”，自证但文案绕。观察项，不另立案 | 是（409 自证） | `_user_status` 同样 last-wins；revoke 后重建取新序列，旧 R 条不遮新 V 条 |
| change_password | 【代码】单条 SQLite UPDATE（原子）＋session_version＋1；并发两路：旧密码校验把第二路天然串行化（先提交者胜，后者 401；若双双在提交前通过校验，后写者胜、DB 仍一致） | DB 提交后才写 admin.pass 文件（plain write 非原子——读者可能读到半行；但 DB 才是登录真值，文件只是健康门禁的副本） | 是（须用当前密码重发） | 无守卫 |
| node register | 【实测】并发同名 201＋409（“节点已存在”），终态唯一 | 注册是单条 INSERT（唯一约束兜底） | 是（409） | — |
| node rotate | 【代码】并发两次各生新 token，后写者胜；旧 token 立即失效；终态恰一个有效 token | 单条 UPDATE | 是 | — |
| install／reinstall | 【代码】install.sh 无锁：并发两路同写 /opt、同起服务、`_ensure_admin_password` 的 INSERT 撞主键（单实例假设；双面板进程本就不该并存）。操作员永不并发安装，属操作域外；不立案 | 重装继承 proto/port（live-7 §9 通过）；失败 die 在完成横幅前（R3-BUG-6 修后） | 是（重跑即续装；R7-BUG-1 的 10% 抖动是重试可过的） | 版本校验 `\| head -1 \| grep -q` 谎报（R7-BUG-1，见 §3） |
| health-check fail-over | 【代码】timer（60s）与操作员 disable 可并发：双 disable 终态一致（disabled）；fail-over 动作按实效记录（R6-P2-1 修后，H2/H4 实测） | 【实测】disable 早抛 → `failover_failed`（非谎报 fail-over）；重起失败仍算 fail-over（policy 已撤、盘已翻） | 是（下轮 timer 再判） | healthy 须 daemon＋策略＋探针三条件（R6-P1-1 修后）；策略缺失时不跑 test_sk5（探针绕策略，会误判） |
| set_udp_over_tcp | 【代码】值未变 ＋0（U 修后，T2/T3 实测）；并发两次同值翻转：双双读旧值、双双重起——与 R7-BUG-3 同族，同一面板锁可一并解 | 同 enable | 是 | 同 enable |
| create_server | 【代码】入口端口创建时查占用＋建后锁定（P01，C10/C11 实测）；并发两次不同端口建服务：双双通过“无 server.conf”检查、后写者胜——终态恰一份 server.conf（后写者端口），先写者的端口宣称丢失；须串行操作，观察项 | 渲染前先校验（模板缺失先败，不动运行态） | 是（同值重渲染跳过占用检查） | 占用检查读实时端口表，非缓存 |

### §2.1 新发现 R8-P2-3（P2）：并发同名建用户双双 200，留幽灵有效序列

- **现象（本轮沙箱实测，分段面板＋真实 core＋fake easyrsa）**：两路 `POST /api/openvpn/users {"name": <同名>}` 同时发出 → **双 200**（串行时应为一 200 一 409，live-5 §14 已验）；列表只有一条用户。`index.txt` 里同 CN 有**两条 V 记录**（序列 0E 与 0F）；列表取 last-wins 只显 0F。
- **机理**：`create_user` 是先查（`_user_status`）后建（easyrsa build-client），无锁；easyrsa.sh 的“已存在即拒”同样是先查后建。两路双双通过检查、双双签发，第二个写盘覆盖第一个的 issued/private 文件。
- **后果定界（已核）**：幽灵序列 0E 的私钥**从未离开过机器**——面板建用户路由只返 `ovpn_url`、`.ovpn` 在下载时才按盘上文件渲染（0F）；`/api/cmd` 路径虽回传 `.ovpn`，但 agent 侧逐条执行、无并发。故 0E 是**悬空 V 记录**（无钥、无文件、不可用），不是可用的幽灵凭证。面板永远看不到它、也吊销不了它（`_parse_index_txt` last-wins＋`revoke` 按盘上文件序列）；CRL 生成不受影响。严重度按 P2（409 契约在并发下破裂＋index.txt 留不可见残留），不按 P1。
- **修法方向（供修复路）**：面板层对 `create_user` 按用户名加锁（或 core 内对 PKI 目录取 flock）；修复时顺带扫 index.txt，把“同 CN 多 V 且序列无对应 issued 文件”的悬空条目标记处理（需先在真机上确认 real easyrsa 的 gen-req 行为：若 real gen-req 拒写已存在 key，则第二路是 500 而非双签发——本轮沙箱用的是 openssl 直写的 fake easyrsa，**真机复核时须以 real easyrsa 为准**，见 §8 未验）。

### §2.2 观察项（不立案）

- **面板层无 set_sk5 串行化**（R7-BUG-3 同族）：enable/enable（＋2 重起）与 enable/disable 混跑的盘／核短暂分裂，根因都是面板层对 set_sk5 无锁；flock 只串行化脚本调用。修 R7-BUG-3 的面板锁应一并覆盖本表 enable/disable/set_udp_over_tcp 三行。
- **revoke 的 500＋已吊销分裂**（见上表）：文案绕但自证，不另立案。
- **init_pki 无去重**（见上表）：破坏性操作依赖操作员双重确认，不另立案。

## §3 全量复扫（历史 115 条逐条定性）

复扫宇宙：R7 的 105 条（R1 33＋R2 13＋R3 16＋R4 5＋R5 3＋R6 8＋live 27）＋live-6 新发现 2 条（R6-BUG-1/2）＋live-7 新发现 4 条（R7-BUG-1/2/3/4）＋本轮新发现 3 条（R8-P2-1/2/3）＝**114 条**。定性口径与 R7 同款（已修／部分／复发／未验）。复扫方法：R7 的 96 条“已修”中，代码自 R7 未动的（§0 mtime 表：core/agent/test-egress.sh 等）沿用 R7 实证（逐项核对代码未动）；代码动过的（Y/Z/AA/AB/Y2/AC/AD/AD2 文件）本轮全部行为重验（§1）；R7 的 8 条“部分”与 1 条“未验”逐项重审（下表）。

### R7 的 8 条“部分”→本轮

| 项 | R8 状态 | 证据 |
|---|---|---|
| R1-P1-5 Worker 快照错位（via_sk5 复发） | **已修** | Y 路：Worker 探针 18/18（§1c），变异改回 enabled 判据恰红五格；沙箱证据。部署态仍未验（见 §5） |
| R4-P1-1 Worker 侧复发 | **已修** | 同上（同一缺陷的跨轮记账） |
| R6-P1-1 Worker 侧复发 | **已修** | 同上 |
| live R4-BUG-1 Worker 侧复发 | **已修** | 同上；live-7 未在真机上重跑策略缺失的 via  case（只验了启用态 via=true 与 kill-switch 态 egress.ip=null） |
| P0-3 bundle/install-agent.sh | **仍部分** | 逻辑已修（§1e agent-bundle 格 PASS）；部署态未验（§5） |
| P1-7 改密＋首登强制改密 | **仍部分（按设计）** | 改密 API＋UI 在位（本轮 Flask 探针登录后改密未逐格重跑，代码未动，沿用 R7）；首登强制改密从未实现、文档已诚实，不另立案 |
| R1-P2-13 flmx-reference 过时 | **已修** | Z 路：ConfigHash/wss:// 只剩“FLMX 原做法”列标不抄（§1d） |
| R6-P2-4 README 过期三处 | **已修** | Z 路：门禁数 28、egress 10.8.0.2 只剩解释句（§1d） |

### R7 的 1 条“未验”→本轮

| 项 | R8 状态 |
|---|---|
| P0-1 部署态 | **仍未验**（§5：登录卡住＋KV 占位，与 R7 同卡点） |

### R7 的 96 条“已修”→本轮

代码未动项沿用 R7 实证（§0 已核 mtime）；代码动过的文件全部行为重验：U/V/W/X 的 Flask 侧（§1e 35/35）、Worker 侧（§1c 18/18）、门禁（§1b 28/28、§4c 21/1/1＋T 变异）、AC（§1a/§1g）、AD/AD2（§1b）、AA/Y2（§1e/§1c）。**但两处修正**：
- **AC 的 M4 结论作废**（§1g）：R7 沿用的“外来占用 priority 100 → 可区分报错”在真机上不成立（live-7 §11）；产品行为正确，occupant-error 分支是死代码，见 **R8-P2-1**。
- **R7-P2-7 的 do_status 待定项已裁决**（§1h）：真机＋沙箱双证，见 **R7-BUG-4（低）**。

### live-6 新发现 2 条→本轮

| 项 | R8 状态 | 证据 |
|---|---|---|
| R6-BUG-1 首启 500 | **已修** | AC（§1a/§1g）＋live-7 headline-1：首启一次 200、10 次交替全一次 200、并发双启用均 200 规则唯一 |
| R6-BUG-2 密码进 python argv | **已修** | AD/AD2（§1b：三处实码行清零＋/proc 阴性对照）＋门禁 28/28；live-7 按设计未在机上重跑沙箱门禁 |

### live-7 新发现 4 条→本轮（R8 独立复核，不只抄结论）

| 项 | R8 状态 | 证据 |
|---|---|---|
| R7-BUG-1 install.sh SIGPIPE 141 | **未修（高，阻塞）** | 本轮独立复核：:297/:333-334 同形＋慢写者 rc=141；全树 grep -q 普查 43 处（见 §6） |
| R7-BUG-2 毒 panel.db | **未修（高，阻塞）** | 本轮独立复核：毒 panel.db＋agent_queue.json（3 条 init_pki 待重投）＋`_ensure_admin_password` 短路（见 §6） |
| R7-BUG-3 并发双重起 | **未修（低）** | 本轮沙箱复现：双 200、restarts＋2（§1h） |
| R7-BUG-4 do_status 源错 | **未修（低）** | 本轮沙箱复核＋live-7 真机（§1h） |

### 本轮新发现 4 条→见 §8

R8-P2-1（occupant-error 死代码＋误诊窗口）、R8-P2-2（egress/README M4 失真记载）、R8-P2-3（并发同名建用户双 200＋悬空 V 记录）。

### R7 认领表 U-1～U-12 更新

| # | 项 | R8 更新 |
|---|---|---|
| U-1 | P0-1/2/3 部署态 | 仍未验（§5） |
| U-2 | R6-P1-1 真机复现 | Flask/Worker 沙箱侧均已闭合（§1c/§1e）；真机策略缺失 case live-7 未显式重跑，留待 live-8 |
| U-3 | UDP 数据面 | **关闭**：live-7 S1/S2 UDP NTP 48 字节回包（dante，UDP/TCP 双模式）＋test_sk5 tcp/udp 双 true |
| U-4 | R 符号链接自拷 | 关闭（R7 已验，无变化） |
| U-5 | R 逐项失败 die 分支 | 仍为“机制已证、分支未触发”：live-7 install3 全程跑通（拷贝全成功，die 分支未触发符合预期）；分支本身仍须一次人为致败才验得到 |
| U-6 | T 两变异 | **关闭**：R8 重跑 T 变异（§4c 16/3/4，早一步更响）；direct-forwarding 对照由 live-7 真机关态 23/0/0 覆盖 |
| U-7 | verify-integration 瞬时红 | 关闭（R7 已判；本轮 28/28 一次，无瞬时红） |
| U-8 | 真机在位升级路径 | **关闭**：live-7 §9 默认重跑（无环境变量、EXIT=0、继承 tcp/443、客户端不断） |
| U-9 | KV 竞态与 POP 传播 | 仍未验（无部署） |
| U-10 | 前端渲染级核查 | 仍未验（本轮亦只验接口与 DOM 存在） |
| U-11 | easy-rsa 真二进制签发 | **关闭**：live-7 §3.3 真 easy-rsa 签发 alice/bob（序列号＋CN＋issuer 逐项核对），BUG-9 第八次复验通过 |
| U-12 | live-R5 结果 | 关闭 |

复扫合计：115 条＝已修 104（R7 的 96 ＋ 6 条部分转已修：4 条 via 跨轮记账＋R1-P2-13＋R6-P2-4 ＋ R6-BUG-1/2）／部分 2（P0-3、P1-7）／未验 1（P0-1）／未修 8（R7-BUG-1/2、R7-BUG-3/4、R8-P2-1/2/3/4）。**差集非 ∅**。

## §6 R7-BUG-1/2 独立复核＋全树 `grep -q` 普查（43 处逐项）

### §6.1 R7-BUG-1（高，阻塞）——独立复核成立

- 位置：`install.sh:24 set -euo pipefail`；:297 `sing-box version | head -1 | grep -q "$SINGBOX_VERSION"`；:333-334 `tun2socks --version 2>&1 | head -1 | grep -q "$TUN2SOCKS_VERSION"`。`--version` 均印多行，`head -1` 读首行即退出关管，写者写第二行时死于 SIGPIPE（141）；grep 已匹配（0），但 pipefail 下管道 rc=141 → `|| die` 触发。
- 本轮复核：慢写者确定性复现（管道 rc=141）；快写者 30 次全 0（时序依赖）；live-7 真机同形循环 10 次复现 1 次（合计约 5–10% 抖动）。AC 只清了 policy-routing.sh 的 `grep -q`，install.sh 两处从未被扫到；R5/R6 下载路径全过属运气。修法（R3-BUG-2 既定）：先把版本输出存变量再 grep，或判 141 为通过。:306/:276 的跳过路径校验带 `|| true`，免疫（见普查表）。

### §6.2 R7-BUG-2（高，阻塞）——独立复核成立，另发现第二毒物

- 毒包：树内 `panel/data/panel.db`（32KB，mtime 09:23:07）含 admin 表 id=1 行（bcrypt `$2b$12$/u83Y…`）、2 节点、6 审计行；`install.sh:374 cp -a panel/` 整目录带进 /opt，:382-390 只清随包 `secret.key`、从未清 `panel.db`/`agent_queue.json`。`panel/app.py:313-319 _ensure_admin_password()` 见 admin 行即返回（不生成密码、不写 admin.pass）；`install.sh:790-799` 等 30 秒无文件即 die。事后态：面板在跑、admin 存在、密码无人知道——安装未完成且无法登录。
- 本轮探针（毒 data 目录复现）：ensure → None、无 admin.pass、错密码登录 401。
- **第二毒物（本轮新发现，修复时须一并清）**：`panel/data/agent_queue.json`（1,061 字节，同 mtime）含 **3 条 init_pki force+confirm=true 命令**（1 sent、2 queued，节点 n1/n2）。`_requeue_stale_sent`（app.py:493，agent poll :1747 与 cmd-get :1659 调用）把超 120 秒未回执的 sent 命令打回 queued（重试 ≤3）——探针证实 sent 的那条翻回 queued（retries 0→1）。即：毒包安装后，下一次 agent 轮询即会收到 init_pki force+confirm，**在活节点上重建 CA**。安装器的修复必须清空整个 `panel/data/`（两文件），只清 secret.key 不够。

### §6.3 全树 `grep -q` 普查（43 处；policy-routing.sh 仅 1 处注释，实码 42 处）

分类标准：`grep -q` 本身无害；危险的是**写者会在读者提前退出后继续写**（多行输出＋`head -1`／长输出）且管道 rc 能改变控制流（pipefail＋`|| die`／`if` 条件／`set -e`）。单次写入（shell 内置 printf/echo、curl -w 单行、文件 grep、无 pipefail）免疫。

| 位置 | 形状 | 定性 |
|---|---|---|
| install.sh:297 | `sing-box version \| head -1 \| grep -q` | **有罪（R7-BUG-1）** |
| install.sh:333-334 | `tun2socks --version \| head -1 \| grep -q` | **有罪（R7-BUG-1，本轮已撞上）** |
| install.sh:676 | `ufw status \| grep -q "Status: active"` | **有罪（R8-P2-4，见下）** |
| install.sh:277/:307 | `printf … \| grep -q`（内置单次写） | 免疫 |
| install.sh:613/615/827 | 文件 grep（无管道） | 免疫 |
| install.sh:727/777 | `curl -w … \| grep -q '^200$'`（单行单次写） | 免疫 |
| install.sh:865/870/873 | `printf … \| grep -q`（内置单次写） | 免疫 |
| verify.sh:176/177/179/429-434/578 | 文件 grep | 免疫 |
| verify.sh:214/404/584/628-630/796/802 | `printf … \| grep -q`（内置单次写） | 免疫（:399-400 注释已明记 R3-BUG-2 教训：tar 直通 grep -q 禁用） |
| verify-integration.sh:259/262/559 | 文件 grep | 免疫 |
| test-egress.sh:46/53/152 | `ip … show \| grep -q`（输出 <64KB 管道缓冲、单次写完） | 免疫（实践中；`ip` 输出一次性写完，grep 提前退出撞不上第二写） |
| test-egress.sh:66/67/76 | `echo … \| grep -q`（内置） | 免疫 |
| policy-routing.sh:109 | 注释（解释为何不用 -q） | 非实码；AC 四处全清已确认 |

### §6.4 新发现 R8-P2-4（P2）：install.sh:676 `ufw status | grep -q`，长规则表时静默跳过开端口

- **机理（本轮机制实测）**：`ufw status` 的 "Status: active" 在第 1 行，`grep -q` 立即退出关管；ufw 是 Python 程序（块缓冲 stdout），规则表短时一次 flush 写完、无第二写（实测 40 条规则 20/20 分支正常）；规则表长到超管道缓冲（本轮 fake ufw 2000 条规则，约 100KB）时写者中途 BrokenPipeError 退出 1，pipefail 下管道 rc=1 → `if` 条件为假。
- **后果**：UFW 启用且规则表长的宿主机上，安装器**静默跳过** `ufw allow $OVPN_PORT/$OVPN_PROTO` 与 `ufw allow $PANEL_PORT/tcp`（该 `if` 无 else、无告警），安装横幅照常打印、端口却被防火墙挡住。触发须规则表超长（日常宿主机罕见），故按 P2、不按 P1。
- **修法方向（供修复路）**：与 R7-BUG-1 同款——先把 `ufw status` 输出存变量再 grep（或 `grep -q` 改全量 grep）；建议与 :297/:333 的修复同提交。

## §8 裁决与未验清单

### §8.1 裁决：**不能交付，差集非 ∅**

| 级别 | 未修 | 条目 |
|---|---|---|
| 高（阻塞） | 2 | R7-BUG-1（install.sh SIGPIPE 141 抖动）、R7-BUG-2（毒包 panel.db＋agent_queue.json，安装后无法登录且 agent 会重建 CA） |
| 低 | 2 | R7-BUG-3（并发同值启用双双全量重启 daemon）、R7-BUG-4（do_status `from 10.8.0.2` 恒坏行） |
| P2 | 4 | R8-P2-1（AC 占用错误分支是死代码＋误诊窗口）、R8-P2-2（egress/README 仍写已推翻的 M4 模型）、R8-P2-3（并发同名建用户留幽灵有效序列）、R8-P2-4（ufw 长规则表时静默跳过开端口） |
| P1 | 0 | R7-P1-1 已由 Y 修好（本轮 18/18＋变异五红证实） |
| P0 | 0 未修、1 未验 | P0-1/2/3 部署态仍未验（§5）；P0-3 部分（按设计，部署态未定） |

差集＝8 条（2 高＋2 低＋4 P2）。两条高阻塞中任何一条都足以挡交付：R7-BUG-1 让约 1/10 的安装死在版本校验上，R7-BUG-2 让全新安装出来的面板无法登录、且毒队列会在 agent 首次轮询时重建 CA。Y/Z/AA/AB/Y2/AC/AD/AD2 的修复本身本轮全部行为验证通过（§1），门禁变异每格独立红证（§1g、§4c），历史 115 条中 104 条已修——但这不改变差集非空的结论。

**下一步（按用户常设流程）**：先派修复路（R7-BUG-1/2＋R8-P2-1/2/3/4，文件归属不重叠，可并行；R7-BUG-1 与 R8-P2-4 同为 install.sh SIGPIPE 同族，建议同路同提交），修完集成后跑 **AUDIT-R9（全量全局回头看，换推导方法独立复算）＋ live-8（真机总验）**，两路都过才交付。修复路开工前须先确认：本报告基线树版本（§0）与修复路所取树一致。

### §8.2 未验清单（逐项：为什么没验、谁能验）

1. **P0-1/2/3 真实 wrangler deploy（§5）**——卡在 Cloudflare 登录（非交互环境须 `CLOUDFLARE_API_TOKEN`，`~/.config/.wrangler/` 无登录态；wrangler.toml 的 KV id 仍是占位符）。谁能验：用户建 API token（或交互式 `wrangler login`）＋`wrangler kv namespace create PANEL_KV`（生产＋预览）填实 id＋`wrangler secret put ADMIN_PASSWORD`／`AGENT_BUNDLE_ORIGIN` 后，live 路跑真实 `wrangler deploy`，再从第二出口核 POP 传播。本轮不许用 mock 冒充。
2. **前端渲染级检查**——从未做过任何一轮（用户常设规矩：交付前须渲染级对比度自检＋用户看过演示站）。沙箱无浏览器渲染环境，本轮未做。谁能验：live 路在真机部署后做浏览器渲染检查（文字对比度目标 7／底线 4.5、托盘兜底），用户看演示站后才算过。
3. **Cloudflare KV 竞态＋POP 传播**——依赖第 1 项的真实部署；无部署则无从测。谁能验：同第 1 项，部署后多点核。
4. **SK5 端口 1001 vs 9000**——用户从未确认哪个是 SOCKS5 口（面板默认 1001，文档已标注待确认）。谁能验：用户回报；live 路再以确认后的端口跑 UDP/TCP 双栈。
5. **R8-P2-3 的真 easyrsa 问题**——沙箱用 fake easyrsa，real easyrsa 的 gen-req 遇预存 key 是拒绝还是覆盖未知，决定并发同名建用户的真机后果（500 还是幽灵序列）。谁能验：live-8 在真机上跑并发同名建用户。
6. **面板级 enable/disable 竞态（真机）**——R7-BUG-3 只在沙箱复现了现象（双 200、重启＋2）；修复后的真机表现须 live-8 验证。谁能验：live-8。
7. **live-7 的 TCP 首连 120s 超时观察**——live-7 报告提及，R8 沙箱无法复现 TCP 首连时序。谁能验：live-8 跟进。
8. **R8-P2-4 的真 ufw 验证**——本轮只做了机制复现（fake ufw，长规则表）；真 ufw 在长规则表宿主机上的行为须真机确认。谁能验：live-8（UFW 启用且规则表长的宿主机）或用户环境。
9. **R7-BUG-1/2 与 R8-P2-1/2/3/4 的修复变异红证**——修复尚未派发，修法未定，无从给变异红证。谁能验：修复路做完后，AUDIT-R9（旧写法循环能红、新写法不红）＋ live-8。
10. **live-7 结论是否入本报告**——已入。live-7 接续路 2026-11-12 19:03 落盘（208 行，`docs/live-verify-R7.md`），其结论已纳入 §1h（R7-BUG-3/4 独立复核）、§3（live-7 四条）与 §6.1（R7-BUG-1 真机抖动率）。与本轮并行在跑的 live-7 接续路**无未入本报告的结论**。

### §8.3 审计方法自述（供 R9 复核）

- 本轮方法：并发＋幂等＋失败原子性推导（§2，12 操作三态表）＋历史全量复扫（§3，115 条）＋新代码逐项行为验证（§1，亲自重跑、零 monkeypatch 走真实代码路径、阴性对照齐全）＋门禁变异红证（§1g、§4c）＋文档宣称全量核对（§7）＋`grep -q` 全树普查（§6.3，43 处）。
- 探针纪律：凡套件格先红，必先查探针本身（本轮修掉的探针问题：fake iptables `-C` 恒 0、fake systemctl 尾部 `exit 0` 掩盖 is-active 失败、错 JSON 字段、fake ip `local` 作用域外、非原子 fake-ip add、agent 套件报告列表跨格不清、core 探针非幂等）；探针修好重跑后才定性，不在探针 artifact 上立案。
- 沙箱边界：无 systemd／无 TUN／无 easy-rsa／无 openvpn 二进制／UDP sendto 临时端口 EPERM——凡涉此四项的结论均已标注分段环境或待真机（live-8），未把沙箱结论写成真机结论。

### §8.4 清理记录（审计结束时）

- 分段面板（start-panel3，PID 204399，https://127.0.0.1:8443）已停；SOCKS stub（:11080，PID 232620）与 fixed-IP 服务器（:80，PID 232615/231718）已停；端口 8443/11080/80 已空闲，无残留进程。
- 宿主 `/etc/openvpn-sk5-panel/` 为空（无 admin.pass／secret.key）；宿主 `/etc/sysctl.d/99-openvpn-sk5.conf`（审计窗口内落下的 `net.ipv4.ip_forward=1`，分段面板的绑定目标副本在 /tmp/r8-tests/etc-sysctl/，宿主这份是某步 harness 在 unshare 外跑 do_enable 时漏出的）已删除，sysctl.d 已干净。
- 项目树核查：本轮只写了本报告一个文件（`find -newermt` 仅见 `docs/live-verify-R7.md`，那是 live-7 路 19:03 落盘的报告，非本轮所写）；树内其余文件 mtime 未动，基线未被污染。

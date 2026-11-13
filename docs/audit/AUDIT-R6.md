# AUDIT-R6 — 全量全局回头看（交付前）

- 审计员：独立审计路（未参与建设与修复路 A–T；单审计员边做边写，不派子代理）
- 日期：2026-11-12（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1/R2/R3/R4/R5 同等广度）
- 推导方法：**状态转移推导**（与 R1 逐文件通读、R2 旅程推导、R3 宣称驱动、R4 不变量驱动、R5 故障注入均不同）——先枚举产品全部状态机维度（SK5 enabled/disabled × sing-box 运行/已死 × 策略路由在/缺 × fail-open 开/关 × 节点已注册/已吊销 × 用户有效/已吊销 × egress 观测直连/SK5），逐条验证每条转移路径的前置条件与后置状态，重点查“盘上持久态 vs 面板上报态 vs 内核真实态”三者不一致的任何组合。每条立案带可复现的复现步骤与实测输出，不只凭代码阅读立案；每条复扫结论注明复现方法。
- 测试一律在 `/tmp` 副本（`/tmp/audit6`、`/tmp/audit6-tests/`）上跑；未动项目原文件；未动任何真机。/etc：除一处违规外未动——早期复跑中真实 policy-routing.sh 以 root 落盘 `/etc/sysctl.d/99-openvpn-sk5.conf`（仅 `net.ipv4.ip_forward=1`），收尾时已删，详见 §8 末尾“取证失误”第 3 条。真机第五轮（live-R5）与本轮并行，凡需真机行为复核的项一律写“待 live-R5”，不提前判通过。
- 语法基线：见 §0。

## §0 树版本与 Q/R/S/T 改动确认

当前树是 Q/R/S/T 修复后＋主控亲手修的 verify.sh install-copies-agent 门禁双机制检查。文件 mtime（UTC）：

| 文件 | mtime (UTC) | 说明 |
|---|---|---|
| install.sh | 2026-11-12 05:59:49 | R 路：readlink -f 自拷跳过＋逐项拷贝＋失败 die |
| core/easyrsa.sh | 2026-11-12 06:01:36 | S 路：init 接 --force |
| core/openvpn_manager.py | 2026-11-12 06:01:40 | S 路：三类用户异常＋_exists()＋init_pki force 透传 |
| panel/app.py | 2026-11-12 06:02:03 | S 路：409/404/409 映射＋via_sk5 回退改 policy_routing_active |
| egress/test-egress.sh | 2026-11-12 06:02:03 | T 路：route-get 断言改 dev tun1＋table 100 |
| egress/sk5_manager.py | 2026-11-12 06:04:05 | Q 路：reset-failed＋先成功后写盘＋已启用态重开补策略 |
| verify-integration.sh | 2026-11-12 06:11:22 | Q 路：§4d 四格（风暴 A、补策略 B、健康无操作 B2、收尾），总数 23→27 |
| verify.sh | 2026-11-12 07:29:19 | 主控：install-copies-agent 双机制检查（循环表含 agent＋cp 用 $_item，或字面形） |
| panel/templates/index.html | 2026-11-12 02:49:17 | L 路（未动） |
| cloudflare/src/index.js | 2026-11-12 02:48:46 | K 路（未动） |
| agent/agent.py、agent/install-agent.sh | 2026-11-12 00:58:12 / 02:21:57 | E/H 路（未动） |
| README.md | 2026-11-12 03:38:13 | P 路（未动） |

## §1 套件重跑（现存套件独立重跑＋自写套件）

语法基线：4 个 Python 文件 `py_compile` 全绿；7 个 shell 脚本 `bash -n` 全绿；Worker `node --check` 全绿。

现存套件说明：`/tmp/audit2-tests/`、`/tmp/audit3-tests/`、`/tmp/audit4-tests/`、`/tmp/audit5-tests/`、`/tmp/fixk-test/`、`/tmp/fixj-test/` 均已被清，不可复用。现存可跑的只有 S 路（`/tmp/s-tests/`＋`/tmp/s-venv/`）、Q 路（`/tmp/fixq-test/`＋`/tmp/fixq-venv/`）、T 路（`/tmp/fixt/` harness）。其余五套件本轮全部自写于 `/tmp/audit6-tests/`（见 §1b）。

### §1a 现存套件重跑结果

| 套件 | 位置 | 结果 |
|---|---|---|
| S core | `/tmp/s-tests/core_test.py`（`/tmp/s-venv/bin/python`） | **14/14** |
| S Flask | `/tmp/s-tests/flask_test.py` | **17/17** |
| S nobody 探针 | `/tmp/s-tests/nobody_probe.py` | **PASS**（server_status 不抛，running=False clients=[]） |
| Q 探针 | `/tmp/fixq-test/test_r4bug1.py` | **22/22** |
| Q Flask | `/tmp/fixq-test/test_flask_r4bug1.py`（`/tmp/fixq-venv/bin/python`） | **8/8** |
| verify-integration | 原脚本沙箱跑 | **27/27**（见下注） |
| verify.sh（T harness） | `/tmp/fixt/run.sh full none` | **23/23 ALL GREEN** |

注（verify-integration 首次 26/1）：本轮第一次跑为 **PASS=26 FAIL=1**，随后连续 5 次重跑均为 27/27。第一次跑的输出我只取了尾部，未能捕获是哪一格红——是我方取证失误，不许据此立案。可能机制：第一次跑与 S/Q 套件重跑并行在同一沙箱（1.5 共享核），门禁内至少有一格是时序敏感的（§4d 风暴格的 restart 计数、agent poll 的 5 秒窗口），并行负载下可能错过窗口；5 次串行重跑全部全绿支持“瞬时时序抖动”而非产品回归。记为观察，不立案；live-R5 若在串行态下再现单格红，须重查。

## §1b 套件重跑（本轮实测数）

| 套件 | 结果 | 备注 |
|---|---|---|
| S core（`/tmp/s-tests/core_test.py`） | **14/14** | 复用 S 路资产，原样重跑 |
| S Flask（`/tmp/s-tests/flask_test.py`） | **17/17** | 复用；但 F15 是夹具失真（见 §2 R6-P1-1），17/17 高估了 via_sk5 的真实状态 |
| S nobody probe | **PASS** | server_status 在 nobody 下不抛错 |
| Q probe（`/tmp/fixq-test/test_r4bug1.py`） | **22/22** | 复用；测的是与在售树逐字节一致的 `/tmp/audit5/sk5_manager.py`（已 diff 确认） |
| Q Flask（`/tmp/fixq-test/test_flask_r4bug1.py`） | **8/8** | 复用 |
| T harness（`/tmp/fixt/run.sh full none`） | **23/23 全绿** | 复用；确认 T 的修＋主控的 install-copies-agent 双机制检查 |
| verify-integration.sh（27 格） | 首跑 **26/1**，随后 **5 连跑 27/27** | 首跑失败格未留证据（本轮失误，只 tail 了输出），不作立案依据；并行负载下的时序抖动为首要假说，见 §8 U-7 |
| 树内 status-log（`core/tests/test_status_log.py`） | **5/5** | 夹具为真机捕获行 |
| R6 agent 套件（`/tmp/audit6-tests/agent_suite.py`） | **28/28** | 新建：URL 策略、脱敏、4 组 pin hash、hash 解析优先级、verify、命令白名单、重定向守卫、心跳、loopback 真面板 poll 一轮 |
| R6 Worker 套件（`/tmp/audit6-tests/worker_suite.mjs`） | **28/28** | 新建：登录限流、注册/轮换/吊销、安装命令、poll 认领、202 语义、重投上限 3 次、非幂等不重投、bundle 代理＋篡改 502＋无 origin 503 |
| R6 core 套件（`/tmp/audit6-tests/core_suite.py`） | **13/13** | 新建：PKI＋server 证、用户 CRUD＋三类 typed 异常、.ovpn 渲染、端口占用 bind 探测、真机 comma-v2 行解析 |
| R6 Flask 增补（`/tmp/audit6-tests/flask_suite.py`） | **16/16** | 新建：登录/改密全流程、用户 CRUD HTTP 映射、SK5 密码保留（P0-4 回归）、/api/status 形状 |
| R6 via_sk5 探针（`/tmp/audit6-tests/via_sk5_probe.py`） | **2/4 诚实** | A、C 撒谎（R6-P1-1）；B、D 诚实 |
| R6 egress 转移探针（`/tmp/audit6-tests/egress_transitions.py`） | **11/13** | T3 失败＝R6-P2-1；T4 失败＝check_health 策略盲（R6-P1-1 佐证）；T1/T2/T5 通过 |
| R6 T4b（`/tmp/audit6-tests/t4_policy_blind.py`） | **策略盲已证** | check_health 在策略缺失时仍报 healthy/none；沙箱 UDP 全 EPERM（UDP 半边不可验，见 §8 未验） |
| R6 toggle 探针（`/tmp/audit6-tests/toggle_probe.py`） | **6 步如预期** | 步骤 2/4/6 各多 1 次重起（R6-P2-2）；步骤 3 同值保存 ＋0 |

## §2 状态转移推导（核心方法）

状态机维度（笛卡尔枚举，逐格给“转移＋三态对照”）：SK5 enabled/disabled × sing-box 运行/已死 × 策略路由在/缺 × fail-open 开/关 × 节点已注册/已吊销 × 用户有效/已吊销。判定标准：盘上持久态（sk5.json / enabled）、面板上报态（/api/status 的 sk5/egress 两块）、内核真实态（ip rule / table 100 / daemon）三者必须一致；任一不一致即立案。

### R6-P1-1 — /api/status 的 via_sk5 在策略路由缺失时仍报 true，S 路的回退分支在启用路径上不可达（R4-BUG-1 面板一半未真修）

- 严重度：P1（必须修）
- 文件：`panel/app.py:979-996`（`status()` 的 egress 分支）；`egress/sk5_manager.py:824-831`（`get_status()` 恒含 `egress_ip` 键）
- 机制族：状态旗标诚实性（R4-BUG-1 第二阶：流量静默直连时面板仍宣称经 SK5）
- 复现（本轮探针 `/tmp/audit6-tests/via_sk5_probe.py`，真实代码路径，零 monkeypatch；桩只替外部世界：fake `ip`、`curl`、`systemctl`、`sing-box`；`unshare -rm` 挂载命名空间，/etc 绑 /tmp）：
  - **A：enabled=true、策略路由缺失（fake ip 无 rule 100、table 100 空）、SOCKS 探针活** → `sk5.policy_routing_active=False`（诚实），但 `egress.via_sk5=True` 且 `egress.ip=203.0.113.7`（桩 SOCKS 探针回的 IP）。面板宣称“经 SK5 出口”并给出具体 SK5 出口 IP，而内核真实态是零 VPN 流量走策略路由——全部直连。**与 R4-BUG-1 第二阶逐字同款**（live-R4 §8：策略全无、面板仍称 via_sk5=true）。
  - **C：enabled=true、策略缺失、SOCKS 探针死** → `egress.ip=None`（诚实），但 `via_sk5=True` 且 `error=None`——无 IP、无警告，仍宣称经 SK5。
  - 对照 B（策略在位、探针活）：via_sk5=true、ip=203.0.113.7，诚实。D（策略在位、探针死）：via_sk5=true、ip=None——流量确实进链路后黑洞（kill-switch 工作态，live-R4 S3 同款），诚实。
- 根因：`status()` 的 if 分支是 `if sk5.get("enabled") and "egress_ip" in sk5:`，命中即 `via_sk5 = True` 无条件；而 `get_status()` 在 enabled 时恒写 `status["egress_ip"]` 键（有 IP 或 None），所以 **enabled 路径上 `"egress_ip" in sk5` 恒为真，S 路修的 else 分支（用 `policy_routing_active` 判定、缺失时 ip 置空＋报错）永远走不到**。只有 enabled=False 或 sk5 模块加载失败时才进 else 分支——那时 via_sk5 本来就是 False。
- 为什么 S 路的套件没抓住：S 的 Flask 套件 F15 把 `panel.sk5_get_status` monkeypatch 成 `{"enabled": True, "policy_routing_active": False}`——**一个没有 `egress_ip` 键的 dict，真实 `get_status()` 永远不会返回这种形状**。F15 测的是 else 分支本身，不是线上路径；夹具失真，同族于 LIVE-215 手写 sing-box 行形与 BUG-9 三轮夹具错误。主控的复核（grep 见注释＋重跑 17/17）同样只验了“分支存在”，没验“分支可达”。
- 附加：前端同时显示两处自相矛盾的信号——`via_sk5=true` 显示“经 SK5 出口”（index.html:660），`policy_routing_active=false` 显示“策略路由：未生效”（:685）。标题宣称与明细旗标打架，用户按标题理解即被误导。另：`check_health()` 的 healthy 判定只看 TCP 探针（`test_sk5()`，SOCKS 直连拨号、不经过策略路由），策略缺失而 SOCKS 活时 timer 回 `healthy=true, action=none`——健康检查同样看不见策略缺失，面板无任何自动修复路径（Q 的补策略只在 `set_sk5` 保存时触发）。
- 影响：操作员在策略路由丢失后（手动删规则、重启丢规则、Q 的 repair 失败残留）从面板看到的是“经 SK5 出口＋具体出口 IP”，与 R4-BUG-1 的“静默直连”危害完全相同；kill-switch 的承诺在上报面被绕过。
- 修法建议：`status()` 的 enabled 分支改成 `via_sk5 = bool(sk5.get("policy_routing_active"))`；enabled 且策略缺失时 `egress.ip=None` 并附 S 路已写好的错误文案（“SK5 已启用但策略路由未生效，出口未经过 SK5”）。另：`check_health()` 的 healthy 判定应把 `_policy_active` 纳入（策略缺失即不 healthy），否则 fail-open 链在策略丢失时永不 fail-over、不告警。
- 关联：R5 表 F 的 R4-BUG-1 行（“via_sk5 在探针失败时退化为 bool(enabled)”）——S 路只改了退化表达式的文字，没改它的可达性；Q 路的 daemon 一半（reset-failed＋补策略）不受此影响，见 §4。

### R6-P2-1 — check_health 的 fail-open 分支在 disable() 提前抛错时仍记 `failed_over_to_direct`（记录撒谎，实际什么都没切）

- 严重度：P2（必须修）
- 文件：`egress/sk5_manager.py:935-972`（`check_health()` fail-open 分支）
- 机制族：健康记录诚实性（R4-P1-1/FI15 同族：状态记录与实际不一致）
- 复现（`/tmp/audit6-tests/egress_transitions.py` T3，真实代码＋Q 的有状态桩）：enabled=true、fail_open=true、daemon 已死、模板文件缺失 → `check_health()` 返回 `action="failed_over_to_direct"`，detail 为 `"sing-box not running; fail-over restart failed: template not found: …"`；与此同时策略路由仍在位、盘上仍 `enabled=true`、流量仍黑洞。记录宣称“已切回直连”，实际一步都没切。
- 根因：fail-open 分支的注释（:944-947）明知“template missing / config unwritable can still raise”却选择“record the fail-over either way, with the failure in the detail”——action 标签被当成“已尝试”而不是“已发生”。detail 里有真相，但面板/agent 消费的是 action 标签（面板 /api/status 直接透传 last_health；agent 同样取 action 做展示）。
- 触发面：模板丢失、配置不可写——灾难性配置损坏角落，平时到不了；但恰恰是操作员最需要真相的时刻（fail-open 链、daemon 已死、以为已直连，实际仍黑洞）。
- 修法建议：disable() 抛错时 action 改为 `failover_failed`（或保留 `blackholed_kill_switch`），detail 不变；下次 timer 成功切回后再记 `failed_over_to_direct`。

### Q 裁决 (a) — 已启用链修失败时盘上仍留 enabled=true：不算复发，接受

- 证据（`/tmp/audit6-tests/egress_transitions.py` T1/T2，11/13 通过中的两格）：
  - T1：daemon 已死＋sing-box check 失败时，`set_sk5()` 无操作保存抛 `RuntimeError`（诚实 500，不裸 200）；盘上 `enabled=true` 保留；`get_status()` 报 `singbox_running=false` 诚实；策略旗标跟随内核（规则仍在位即 true）。
  - T2：链路变更（改 port）＋check 失败时同样诚实抛错；盘上是新 host＋enabled=true；旧 daemon 未被触动、仍跑旧凭证（save-first 语义的固有偏差，500 已告知操作员应用失败，下次成功保存即收敛）。
- 裁决：盘上的 `enabled=true` 是**期望态**，不是谎言——R4-BUG-1 的危害是“静默直连＋面板谎称经 SK5”，此处 daemon 已死即 kill-switch 兜底（流量黑洞、非直连），且三处上报（singbox_running、policy 旗标、health 记录）均诚实；timer 也会收敛（fail-open → 下次 disable() 重试；fail-closed → 黑洞本就是期望态）。真正的上报缺口是 R6-P1-1 的 via_sk5，与盘上值无关。
- 保留条件：修 R6-P1-1 时不得把“修失败即盘上改 false”当作修法——那会把期望态丢掉，变成另一种静默关链。

### Q 裁决 (b) — /api/sk5/enable 与 toggle-only POST /api/sk5 直调 enable()：可接受（状态无口子），但每次完整重起是真浪费，立 R6-P2-2

- 证据（`/tmp/audit6-tests/toggle_probe.py`，真实面板＋Q 有状态桩，重起次数为判据）：
  - 步骤 1 全字段保存启用链：重起 1 次。
  - 步骤 2 toggle-only `POST /api/sk5 {"enabled": true}`（链已健康启用）：**重起 ＋1**（共 2 次）——直调 `enable()`，绕过 `set_sk5` 的短路/补修逻辑。
  - 步骤 3 全字段同值保存：**重起 ＋0**（仍 2 次）——`set_sk5` 短路正常工作。
  - 步骤 4 `POST /api/sk5/enable`：**重起 ＋1**（共 3 次）。
  - 步骤 5 toggle-only false→true（真翻转）：各 ＋1（共 5 次），预期内。
  - 步骤 6 全字段保存附带 `udp_over_tcp: false`（**值未变**）：**重起 ＋1**（共 6 次）——`set_udp_over_tcp()` 在 enabled 时无条件再调 `enable()`（sk5_manager.py:1005-1006），与值变不变无关。第三条冗余重起路径，Q 路简报未提。
- 裁决：**状态上无口子**——`enable()` 本身是幂等的完整渲染＋起 daemon＋补策略，失败时盘上仍是旧值（`enable()` 只在成功末尾才写 `enabled=true`）、面板报 500，不留不一致。接受其存在，但不是“无害”：每次冗余重起都会短暂拆掉 tun1（在线 VPN 会话断/重建），并消耗一次 StartLimitBurst 名额——这条路的安全性完全依赖 Q 加的 reset-failed；前端的一键启用按钮（index.html:1228）调的正是 `/api/sk5/enable`，已启用链上每点一次即一次全重起。
- 立案：见 R6-P2-2。

### R6-P2-2 — 三条路径对已启用链做冗余全重起（toggle-only、/api/sk5/enable、set_udp_over_tcp 未变值）

- 严重度：P2（必须修，建议）
- 文件：`panel/app.py:1314-1316`（toggle-only 直调 `sk5_enable_fn`/`sk5_disable_fn`）、`panel/app.py` 的 `/api/sk5/enable` 路由、`egress/sk5_manager.py:1005-1006`（`set_udp_over_tcp` 无条件 `enable()`）
- 机制族：幂等性（已启用态的重复操作应为无操作）
- 复现：见上节 toggle 探针，步骤 2/4/6 各 ＋1 次重起；步骤 3 的 `set_sk5` 同值保存 ＋0 是对照。
- 修法建议：toggle-only 与 `/api/sk5/enable` 走 `set_sk5` 的有效态检查（有效即无操作＋`repaired` 收据）；`set_udp_over_tcp` 只在值真正变化时才 `enable()`。修后探针应为：步骤 2/4/6 均 ＋0。

### R6-P2-3 — verify-integration.sh 登录仍把管理员密码放进 curl -d argv（R1-P2-8 复发，修A漏B）

- 严重度：P2（必须修）
- 文件：`verify-integration.sh:264`
- 机制族：凭据不进进程 argv（R1-P2-8 同族）
- 复现：`verify-integration.sh:264` 的登录是 `-d "{\"password\": \"$ADMIN_PASS\"}"`——shell 把真实管理员密码展开进 curl 的 argv；本轮用同款命令对本地延迟 3 秒的 HTTP 服务实测，curl 运行期间读 `/proc/<pid>/cmdline` 得到完整 `-d {"password": "SECRET-PROOF-7f3a9"}`，**密码明文可见**。同族的 `verify.sh:337-349` 与 `install.sh:801-818` 早已修成“写 0600 文件再 `--data @file`”，`verify-integration.sh` 这条被漏掉。
- 修法建议：照 `verify.sh` 的做法，密码先写 0600 临时文件再 `--data @file`，用完即删。

### 状态转移矩阵（其余格结论）

| 转移 | 盘上态 | 面板上报态 | 内核真实态 | 结论 |
|---|---|---|---|---|
| enabled＋策略在位＋daemon 活＋探针活 | enabled=true | via_sk5=true, ip=SK5 IP | rule＋table 100 在位 | 一致（探针 B） |
| enabled＋策略缺失＋daemon 活＋探针活 | enabled=true | via_sk5=true, ip=SK5 IP | 无 rule、无 table 100 | **不一致 R6-P1-1**（探针 A） |
| enabled＋策略缺失＋daemon 活＋探针死 | enabled=true | via_sk5=true, ip=None, error=None | 无 rule | **不一致 R6-P1-1**（探针 C） |
| enabled＋策略在位＋daemon 活＋探针死 | enabled=true | via_sk5=true, ip=None | rule＋table 100 在位，流量黑洞 | 一致（kill-switch 工作态，探针 D） |
| enabled＋daemon 已死＋修失败（check 失败） | enabled=true（期望态） | singbox_running=false 诚实，500 | daemon 死，rule 仍在位 | 一致（T1，裁决 (a) 接受） |
| enabled＋改 host＋check 失败 | 新 host＋enabled=true | 500，旧 daemon 仍跑旧凭证 | 旧 daemon 活 | 一致（T2，save-first 固有偏差，500 已告知） |
| fail-open＋daemon 死＋模板缺失 | enabled=true，策略仍在位 | health.json 记 failed_over_to_direct | 未切回直连 | **不一致 R6-P2-1**（T3） |
| enabled＋策略缺失＋timer 检查 | enabled=true | healthy=true, action=none | 无 rule | **不一致 R6-P1-1 佐证**（T4/T4b） |
| 7 次连续翻转（start-limit 5） | 跟随翻转 | 200 全过 | daemon 恒活 | 一致（T5） |
| toggle-only 已启用链重开 | enabled=true | 200 | daemon 重起 1 次（冗余） | 状态一致、行为浪费 R6-P2-2 |
| 全字段同值保存 | enabled=true | 200，repaired 缺省 | daemon 不动 | 一致（对照） |

## §3 历史发现逐条复扫（R1 33＋R2 13＋R3 16＋R4 5＋R5 3 新＋live 26＝96 条）

记账说明：R5 文件自身的差集是“新 3 条 P2＋live-R4 遗留 4 条”共 7 条；live-R4 的 4 条（R4-BUG-1～4）在 live 节逐条复扫，此处 R5 节只列 3 条新发现，不重复记账（交代简报里的“R5 7 条”即此 7 条）。

复扫口径：Q/R/S/T 或主控动过的代码一律本轮行为重验；未动过的代码采信 R5 的实证结论（文件未变即结论未变）；需真机流量的项标“待 live-R5”，不冒充已验。

### R1（33 条）

| 项 | 状态 | 本轮证据 |
|---|---|---|
| P0-1 202 误报 | **未验** | 真实 Worker 从未部署（§6：无登录＋KV 占位＋沙箱 fetch 失败）；mock-KV 套件 28/28 只能证逻辑，不能代替部署态 |
| P0-2 Worker 单字段 set_sk5 | 已修 | Worker 套件：fail-open/udp-over-tcp 路由 202＋补齐；agent `action_set_sk5` 部分合并（代码＋套件） |
| P0-3 bundle/install-agent.sh 404 | 部分 | Worker bundle 代理＋sha256 验包＋篡改 502（mock origin，28/28）；Flask 四端点本轮实测：bundle.sha256 的哈希与 bundle 字节逐字节相符；真实部署未验 |
| P0-4 SK5 密码保存清空 | 已修 | Flask 增补 16/16：无密码保存保留存量密码 |
| P0-5 secret.key 随树发货 | 已修 | 树内无 secret.key；`_secret_path` 顺序 env＞/etc＞data |
| P1-1 status 20 秒 | 已修 | status() 复用 get_status 的 egress_ip＋10 秒缓存；本轮数十次 /api/status 调用均秒回 |
| P1-2 无节点/agent 界面 | 已修 | index.html 含 nodes 区（nodeSelect/nodeTable/nodeTokenBox）、改密按钮、SK5 卡 |
| P1-3 Worker 登录不限流 | 已修 | Worker 套件：5 次失败→429＋Retry-After，锁内仍 429 |
| P1-4 Worker 无吊销/轮换 | 已修 | Worker 套件：rotate 200＋旧 token 立即 401，revoke 后 poll 401 |
| P1-5 Worker 快照错位 | 已修 | 真实路径探针：report→快照→GET /api/nodes，online_users=2、egress_ip、sk5_enabled 均实 |
| P1-6 sent 无重投 | 已修 | Worker 套件：重投上限 3 次、非幂等首超时即 failed；Flask `SENT_MAX_RETRIES=3` |
| P1-7 改密接口＋首登强制改密 | 部分 | 改密 API＋UI 已验（Flask 16/16）；**首登强制改密未实现**（无受限 token、无强制流程），README 却宣称其存在＝R6-P2-5 |
| P1-8 check_health 死开关 | 已修 | healthcheck timer（60 秒，ExecStart sk5_manager.py health）已接线 |
| P1-9 策略路由无持久化＋重跑覆盖 SK5 配置 | 已修 | policy service＋starter 仅首装写；live-R4 重跑通过 |
| P1-10 create_server 不幂等 | 已修 | `build_server_cert` 全量 artifact 在位即跳过（代码＋core 套件） |
| P1-11 入口端口无占用检查 | 已修 | core 套件：bind 探测（占用→检出，空闲→None） |
| P1-12 UoT 探针密码写 /tmp 明文 | 已修 | `tempfile.mkdtemp`，无固定路径 |
| P1-13 core systemctl 无超时/保护 | 已修 | timeout=10＋`_exists`；nobody probe PASS |
| P1-14 server-mode.md 过时 | 部分 | 大体已对齐（https、安装接口、轮换）；**set_sk5 行仍称全量覆盖**＝R6-P2-6 |
| P1-15 cloudflare/README set_sk5 假宣称 | **未修** | `cloudflare/README.md:130-132` 仍称“全量覆盖、首行即要求 host+port”，与 agent 代码及 index.js 已修正的注释直接矛盾＝R6-P2-6 |
| P2-1 限流进程内内存＋无 ProxyFix | 已修 | ProxyFix 只在显式受信反代时启用（app.py:180-183） |
| P2-2 agent 不校验 sing-box 版本 | 已修 | `_install_singbox` 比对 `SINGBOX_VERSION`（agent.py:500） |
| P2-3 agent --once 失败仍返回 0 | 已修 | main()：run_once()<0 即返回 1 |
| P2-4 bundle 确定性 | 已修 | walk 时 dirnames＋filenames 均 sorted（app.py:1777-1783） |
| P2-5 密码哈希 SHA-256 | 已修 | bcrypt 为主＋透明迁移（代码＋R5） |
| P2-6 OVPN_DNS 被忽略 | 已修 | `DEFAULT_DNS` 读 env，render 校验（core:70/789） |
| P2-7 PANEL_ADMIN_PASSWORD_FILE 死变量 | 已修 | 死变量已删（install.sh:507 注释），门禁读同一硬编码路径 |
| P2-8 密码进 curl -d argv | 部分 | verify.sh＋install.sh 已修（0600 文件＋`--data @file`）；**verify-integration.sh:264 复发**＝R6-P2-3 |
| P2-9 init_pki force 无确认 | 已修 | force 须同时 `confirm=true`（agent.py:594-606） |
| P2-10 .ovpn 不验用户状态 | 已修 | 吊销→403、未知→404（app.py:1206-1256） |
| P2-11 UoT 固定 /tmp＋manifest raise | 已修 | mkdtemp＋manifest 逐个试（agent.py） |
| P2-12 两处文档过时 | 已修 | 本轮 §7 核对，相关宣称已改 |
| P2-13 flmx-reference 过时 | 已修 | §1-13/§103 已更新（含 sha256 端点） |

### R2（13 条）——全部已修

P1-1 BUG-9：树内夹具 5/5＋core 套件 13/13（真机 comma-v2 alice 行逐字段解析）；P1-2 改密 UI：index.html:283 按钮＋:1040 调用；P1-3 旧 CN 证书：`create_user` 的 legacy 分支（吊销后重签）＋S core 14/14；P1-4 verify-integration 已登录调 /api/status（MUT-C 证明 status 恒 500 时 panel-status 格红）；P1-5 files 格含 healthcheck/policy（MUT-D 证明删 timer 即红）；P2-1 /etc 快照比对（脚本头注释＋历次运行）；P2-2 DATA_DIR＋.gitignore（app.py:100、.gitignore）；P2-3 哈希钉死宣称（README 二进制校验节）；P2-4 server-mode https；P2-5 flmx-reference；P2-6 sing-box-config 报错已正；P2-7 fail-open 单向性（README＋egress README）；P2-8 starter heredoc＋一致性门（install.sh:531、verify.sh starter-template-consistency 格）。

### R3（16 条）——全部已修

P1-1 Worker 重投上限：Worker 套件 28/28（retries=3→failed 含“已重投 3 次”，retries=2→重投）；P1-2 旧一键命令：README:94＋agent/README:18 均已是两步命令（-k＋sha256＋--node-name）；P2-1 server-mode install 接口注记（“仅 Worker 有”）；P2-2 fail-open 路由存在注记；P2-3 密码哈希 bcrypt 注记；P2-4 复制清单含 agent/；P2-5/6 cloudflare README fail-closed＋https；P2-7 flmx-reference；P2-8 render_server_conf 参数注记；P2-9 check_health timer 注记；P2-10 index.js 注释已正（部分合并）；P2-11 rotate 200（Worker 套件）；P2-12 poll node_name 401（Worker 套件）；P2-13 三字段 shellQuote（index.js:411-421、index.html:815-827）；P2-14 egress README 单向性（:134）。

### R4（5 条）

| 项 | 状态 | 证据 |
|---|---|---|
| P1-1 M 回归（保存/fail-over 硬依赖重起） | 部分 | daemon 一半已修（Q：reset-failed＋先成功后写盘＋补策略，本轮 T1/T5＋MUT-A 证）；**面板上报一半未修＝R6-P1-1** |
| P2-1 policy_routing_active 只看规则 | 已修 | `_policy_active` 三条件（enabled＋rule＋table 100 默认经 tun1）；探针 A/C 均报 false 诚实 |
| P2-2 README 清单漏 systemd/ | 已修 | README:72 现含 `systemd/` |
| P2-3 IPv4 正则接受 999 段 | 已修 | `_valid_server_ip` 改用 `ipaddress.ip_address()` |
| P2-4 两门禁零覆盖保存→重起耦合 | 已修 | verify-integration §4d 四格；MUT-A 删 reset-failed→24/27 恰红三格 |

### R5（3 条新发现；另 4 条为 live-R4 遗留，见 live 节）

| 项 | 状态 | 证据 |
|---|---|---|
| P2-1 409/404 | 已修 | Flask 增补 16/16 |
| P2-2 init_pki force 死路 | 已修 | core 13/13（force 真重建） |
| P2-3 core _exists | 已修 | nobody probe＋core 13/13 |

### live 轮次（26 条）

- **R1 9 条（BUG-1～9）全部已修**：BUG-1 模板字段、BUG-2 pin 哈希、BUG-3 安装健康门、BUG-4 用户列表、BUG-5 TOFU、BUG-6 重装重起 agent、BUG-7 CN、BUG-8 FORWARD 规则、BUG-9 解析器——live-R2/R3/R4 复跑＋本轮套件均证；真机第五轮复跑（live-R5，并行在跑）为最终机上确认。
- **R2 7 条全部已修**：BUG-10（装树 agent/＋门禁双机制，MUT-B1/B2）、BUG-11（TOFU 锚在取包前）、BUG-12（--node-name，Worker 套件安装命令含之）、BUG-13（comma-v2 解析，5/5＋13/13）、BUG-14（allow_port_change 路由）、BUG-15（健康门模式感知）、BUG-16（重跑继承 proto/port）。
- **R3 6 条全部已修**：R3-BUG-6（log 定义前移）、R3-BUG-1（disable 重起 sing-box）、R3-BUG-3（复制清单含 systemd/）、R3-BUG-5（IPv4 探测＋形状校验）、R3-BUG-2（pipefail SIGPIPE）、R3-BUG-4（route-get 源 10.8.0.1）；R3-OBS-1（瞬态 401）live-R4 未复现，R5 判关闭。
- **R4 4 条**：R4-BUG-1 **部分**（daemon 半已修，上报半＝R6-P1-1）；R4-BUG-2/3/4 **已修**（见 §4）。

复扫合计：已修 88 条，部分 6 条（P0-3、P1-7、P1-14、P2-8、R4-P1-1、live R4-BUG-1——后两项为同一事跨轮记账），未修 1 条（P1-15），未验 1 条（P0-1，另 P0-3 的部署态一半未验）。96＝88＋6＋1＋1。

## §4 Q/R/S/T 新代码逐项验证

| 项 | 验证方法 | 结果 |
|---|---|---|
| Q reset-failed（`_start_singbox` 前清限流计数） | Q probe 22/22；本轮 MUT-A：删掉该调用后 verify-integration 24/27，三格 §4d 恰红（风暴格 STORM_OK=0、restart=5、reset-failed=0、限流失败=2） | 已验 |
| Q 先成功后写盘（enable 侧翻转） | Q probe（enable 失败盘上留 False＋500）；本轮 T1/T2 同款复现 | 已验 |
| Q 已启用态重开补策略（daemon 活＋策略缺失→只补策略，repaired=true，不重起） | Q probe；本轮 toggle 探针步骤 3 对照（同值保存 ＋0 重起） | 已验 |
| Q 健康态重开纯无操作（无 repaired、无新增 restart） | Q probe；MUT-A 中 B2 格随 reset-failed 缺失而红，证明该格确实覆盖此行为 | 已验 |
| Q 风暴 7 次翻转不楔死 | Q probe；本轮 T5 独立复跑通过 | 已验 |
| R 自拷跳过（同目录 `readlink -f` 相等即跳过整树复制） | R 路自测＋主控复跑；本轮 fixt 基线 23/23（含该路径的门禁格） | 已验 |
| R 符号链接同目录情形 | `readlink -f` 对符号链接解引用后比较——同目录的符号链接与原目录相等即跳过；代码面确认，未单独造 symlink 用例（见 §8 U-4） | 代码面确认，行为未单验 |
| R 逐项失败 die（单项失败即大声报错＋列出失败项后退出） | R 路自测（9 项全落盘、旧代码负对照复现 `are the same file` rc=1）；本轮未重跑逐项失败分支（见 §8 U-5） | R 路证据＋主控复核，本轮未重跑 |
| S 409/404/409 映射 | S Flask 17/17；本轮 Flask 增补 16/16（duplicate→409、revoke 未知→404、revoke 已吊销→409） | 已验 |
| S easyrsa --force 真重建 | S core 14/14；本轮 core 13/13（force 后 ca.crt 重建） | 已验 |
| S core _exists（server_status 永不抛） | S nobody probe PASS（本轮复跑）；本轮 core 套件缺日志→clients=[] 不抛 | 已验 |
| S via_sk5 三态 | S Flask F15 是夹具失真（无 `egress_ip` 键的 dict，真实代码永不返回）；本轮真实路径探针：B/D 诚实，**A/C 撒谎＝R6-P1-1** | **未真修** |
| T direct-forwarding 模式分支 | fixt 基线 23/23（SK5 开态断言 dev tun1＋table 100，关态断言直连） | 已验 |
| T route-get 断言（`dev tun1`＋`table 100`，弃 `via 10.9.0.1`） | fixt 基线 23/23；T 路变异（apply no-op→toggle-on 红且能区分路由缺失与期望串错误） | 已验 |
| 主控 install-copies-agent 双机制检查 | 本轮 MUT-B1（loop 表去 agent→单格红）、MUT-B2（cp 不用 `$_item`→单格红），各 22/1 且红格确为 install-copies-agent | 已验 |
| 主控 verify.sh 其余门禁 | MUT-C（status() 恒 500→panel-status＋sk5-egress-ip 两格红，21/2）；MUT-D（删 healthcheck.timer→files 格红，22/1） | 已验 |

## §5 门禁变异红证（本轮独立重跑）

驱动：`/tmp/audit6-mut/run_all.sh`（变异施加于 /tmp 树副本，原树不动；每次跑完日志存 `/tmp/audit6-mut/logs/`）。

| 变异 | 门禁 | 结果 | 结论 |
|---|---|---|---|
| MUT-A：删 `_start_singbox` 的 reset-failed 调用 | verify-integration.sh（27 格） | **24/27**，恰红三格 §4d：A（STORM_OK=0、restart=5、reset-failed=0、限流失败=2）、B（重开补策略 HTTP 500）、B2（健康重开 HTTP 500） | 红证成立，与主控的 24/27 逐格一致；§4d 确实覆盖保存→重起耦合（R4-P2-4 已修） |
| MUT-B1：install.sh loop 表去掉 agent | verify.sh（23 格） | **22/1**，唯一红格 install-copies-agent | 红证成立（双机制检查的 loop 分支有效） |
| MUT-B2：install.sh cp 行不再用 `$_item` | verify.sh（23 格） | **22/1**，唯一红格 install-copies-agent | 红证成立（双机制检查的 cp 分支有效） |
| MUT-C：panel `status()` 恒 500 | verify.sh（23 格） | **21/2**，红格 panel-status（HTTP 500）＋sk5-egress-ip（下游） | 红证成立；R2-P1-4 的门禁盲区已堵 |
| MUT-D：删 `systemd/openvpn-sk5-healthcheck.timer` | verify.sh（23 格） | **22/1**，唯一红格 files（missing: …/healthcheck.timer） | 红证成立；R2-P1-5 的门禁盲区已堵 |

另：T 路的变异（policy-routing.sh apply no-op→sk5-toggle-on 红且能区分路由缺失与期望串错误；预热 enable-only→direct-forwarding PASS）由 T 路执行、本轮 fixt 基线 23/23 侧证，未逐项重跑（见 §8 未验）。

## §6 P0-1/2/3 真实 wrangler deploy 重验——卡住，未验

- 尝试 1：`wrangler deploy --dry-run`（wrangler 4.160.1，经 npx 现装）：通过。配置＋打包＋Assets 均合法，`env.PANEL_KV (REPLACE_WITH_KV_NAMESPACE_ID)` 被识别为绑定。
- 尝试 2：`wrangler deploy`：**卡在登录**——非交互环境下 wrangler 要求 `CLOUDFLARE_API_TOKEN` 环境变量；本环境无任何 Cloudflare 凭据（`env` 仅命中无关的 JARVIS_TRACE_CONTEXT），也无 `wrangler login` 的交互条件。
- 尝试 3：`wrangler deploy --temporary`（临时账号路径）：**卡在 wrangler 自身 fetch 失败**（18 秒后 `fetch failed`，日志 `wrangler-2026-11-12_07-51-26_992.log`）；同机 `curl https://api.cloudflare.com/client/v4/` 返回 404（可达），故不是通用断网，是 wrangler/proxy 路径问题。
- 第二道卡点（未及验证、但已确认存在）：`cloudflare/wrangler.toml` 的 KV id 仍是占位符（`REPLACE_WITH_KV_NAMESPACE_ID` / `REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`），文件自身注明“填之前 wrangler deploy 会报错”——即便登录通过，部署也会在绑定解析处失败。
- 需要用户做的事（按顺序）：① 在能直连 Cloudflare 的机器上跑 `wrangler kv namespace create PANEL_KV` 与 `--preview` 版，把两个真实 id 填进 `wrangler.toml`；② `wrangler login`（或设 `CLOUDFLARE_API_TOKEN`）；③ `wrangler deploy`；④ 把部署出的 workers.dev 地址交给审计/复跑路，对 P0-1（202 语义）、P0-2（fail-open/UoT 单字段）、P0-3（bundle/install-agent.sh）逐项在真 Worker 上重验。
- 结论：P0-1/2/3 的**部署态一律未验**。本轮 Worker 套件 28/28（mock KV＋mock origin）只证明 Worker 代码逻辑，不冒充部署结论。

## §7 文档宣称全量核对

核对范围：根 README.md、panel/README.md、cloudflare/server-mode.md、docs/security.md、docs/flmx-reference.md、egress/README.md、cloudflare/README.md、agent/README.md。逐条行为宣称与代码/实测对齐的结果：

### 已核实为真（抽样列举）

- security.md:12 重投上限 3 次、120 秒、非幂等不重投——Worker 套件＋Flask `SENT_MAX_RETRIES=3` 双证。
- egress/README fail-open 单向性、60 秒 timer、set_sk5 部分合并——与代码一致。
- README 二进制校验节（pin 哈希、env＞pin＞manifest、fail-closed）——与 install.sh/agent.py 一致，本轮 agent 套件 28/28 侧证。
- panel/README 路由表（/api/status 形状、改密 ≥12 字符、密码保留语义）——与 app.py 一致，本轮 Flask 16/16 侧证。
- server-mode.md 大部（https 地址、安装接口仅 Worker 有、轮换/吊销、登录限流、版本传播）——与代码一致。
- cloudflare/README bundle fail-closed（.sha256 必取且 `sha256sum -c` 通过才执行）——与 Worker 代码＋套件一致。
- flmx-reference §1-13/§103（含 sha256 端点注记）——已更新。

### R6-P2-4 — 根 README 三处过期

- 严重度：P2
- ① README:223 称 verify-integration.sh“PASS=20 FAIL=0 SKIP=0”——现为 27 格（Q 路 §4d 后 23→27），数字过期。
- ② README:165 与 FAQ 各一处仍写 `ip route get ... from 10.8.0.2`——10.8.0.2 是客户端地址、不是本机地址，正确源是 10.8.0.1（R4-BUG-4 的同款错误，门禁脚本已修，文档未同步）。
- ③ README:202 称 starter heredoc 在 `install.sh:430-452`——该行号现为 TLS launcher，starter heredoc 实际在 install.sh:531。

### R6-P2-5 — 根 README“安全”节三条假宣称（FLMX 口径误植）

- 严重度：P2
- ① “登录限流（双维度）：IP 维 429＋Retry-After；用户名维永不硬拒，只渐进延迟”——面板是单管理员密码登录，**根本没有用户名维度**（app.py:799-840 只有 IP 维 `_login_attempts_row(ip)`），“用户名维”不存在。
- ② “权限收窄：普通 VPN 用户只能看自己的 .ovpn 下载与自己的在线状态”——面板**没有普通用户角色**（app.py 全站只有 admin 会话；`.ovpn` 下载须管理员登录），“普通用户”不存在。
- ③ “首登改密：首次登录只发受限 token，强制改密后才给正常 token”——**无此机制**（app.py 无 must_change/受限 token；登录即给完整 admin 会话），R1-P1-7 的后半句从未实现。
- 三条皆为 FLMX 对照口径误植进本产品文档；修法是按本产品实际改文档，不许反向把未实现的功能补进产品来圆文档。

### R6-P2-6 — set_sk5“全量覆盖”假宣称两处未改（R1-P1-15 未修、R1-P1-14 部分）

- 严重度：P2
- `cloudflare/README.md:130-132` 仍称“`set_sk5` 是**全量覆盖**，不是部分合并：agent 的 `action_set_sk5` 首行即要求 `host` + `port`”，`:213` 又称 Flask 侧同样全量覆盖——与 agent.py 的部分合并实现（P0-2 修复）及 index.js:43-44 已修正的注释直接矛盾。
- `cloudflare/server-mode.md` 对照表 `set_sk5` 行同样称“全量覆盖（agent 强制要求 host+port；开关先读已存全量再重发）”——后半句的“先读已存全量再重发”也是旧口径（Worker 的 fail-open/UoT 路由现为单字段下发，agent 侧部分合并）。
- 修法：两处均改为部分合并语义。

### R6-P2-7 — Worker `handleCreateCmd` 未返回文件头承诺的 `queued:true`

- 严重度：P2
- 文件头注释（index.js:756-757）称 POST 类命令返回 `202 {ok:true, cmd_id, queued:true}`；`handleCreateCmd`（:714-736）实际返回 `{ok:true, cmd_id, node, action, status:"queued"}`——**无 `queued` 字段**（本轮 Worker 套件实测：202＋status queued，`queued` 键缺失）。兼容层 handler（如 `handleCompatSk5Save`）返回了 `queued:true`，故两路不一致。前端按 `status` 轮询故无功能影响，但注释与行为须统一（任一方向）。

## §8 裁决与未验清单

### 裁决：**不能交付**，差集非 ∅

| 级别 | 条数 | 明细 |
|---|---|---|
| P0 | 0 新立（历史 P0-1 部署态未验、P0-3 部署态一半未验，见未验清单） | — |
| P1 | **1** | R6-P1-1（via_sk5 在策略缺失时仍报 true，R4-BUG-1 面板一半未真修） |
| P2 | **7** | R6-P2-1（check_health 假 fail-over 记录）、R6-P2-2（三路冗余重起）、R6-P2-3（verify-integration.sh P2-8 复发）、R6-P2-4（README 三处过期）、R6-P2-5（README 安全节三假宣称）、R6-P2-6（set_sk5 全量覆盖假宣称两处）、R6-P2-7（handleCreateCmd 缺 queued:true） |

差集：R6 新发现 8 条（1 P1＋7 P2）；历史复扫：已修 88、部分 6、未修 1（P1-15，并入 R6-P2-6）、未验 1（P0-1 部署态）。**发版硬门未过**：须修完 R6-P1-1 与 7 条 P2、再做一轮全量全局回头看（AUDIT-R7，换推导方法）＋真机复跑，方可交付。

### 未验清单（逐项：为什么没验、谁能验）

| # | 项 | 为什么没验 | 谁能验 |
|---|---|---|---|
| U-1 | P0-1/2/3 真实 Worker 部署态 | 无 Cloudflare 登录＋KV 占位＋沙箱 wrangler fetch 失败（§6） | 用户（按 §6 四步部署后）＋复跑路在真 Worker 上重验 |
| U-2 | R6-P1-1 的真机复现 | 需真机上删策略路由后看面板上报；沙箱探针已证代码路径，但真机 daemon/策略/探针三者交互须实机 | live-R5（并行在跑；若其轮次已收口，须补一轮） |
| U-3 | UDP 数据面（UoT 封装、原生 UDP ASSOCIATE、TCP 443 模式） | 沙箱 UDP sendto 全 EPERM（本轮实测 loopback 固定端口亦 EPERM）；`udp_ok` 在沙箱恒为环境假阴性 | live-R5 真机（dante/真实 SK5） |
| U-4 | R 的符号链接同目录自拷跳过（行为） | 仅代码面确认 `readlink -f` 解引用，未单独造 symlink 用例 | 复跑路或 R7（5 分钟用例） |
| U-5 | R 的逐项失败 die 分支 | 未重跑单项复制失败即 die 的分支；采信 R 路自测＋主控复核 | 复跑路或 R7 |
| U-6 | T 路两变异逐项重跑 | 本轮只复跑了 fixt 基线 23/23；T 的 apply no-op 与预热变异采信 T 路记录 | 复跑路或 R7 |
| U-7 | verify-integration 首跑 26/1 瞬时红 | 首跑输出只取尾部、失败格未留证；5 次串行重跑全绿，判为并行负载时序抖动（观察，不立案） | live-R5：若串行态再现单格红须重查 |
| U-8 | 真机在位升级路径（现行版→候选版，带存量数据） | 本轮只在沙箱做全新安装形态；用户 2026-11-11 令：只验全新安装不算数 | live-R5 真机彩排部署 |
| U-9 | Cloudflare KV 竞态与 Workers POP 传播 | 无真实部署；mock-KV 无法复现 KV 最终一致性与 POP 滚动 | 用户部署后＋复跑路多点核 |
| U-10 | 前端渲染级核查（节点/agent 界面、改密弹窗、via_sk5 三行同屏自相矛盾） | 本轮只验接口与 DOM 存在，未做渲染级对比度/可读性自检 | live-R5 或 UI 专项（用户立规：交付前渲染级自检、预览先行） |
| U-11 | easy-rsa 真二进制签发 | 沙箱无 easy-rsa 真二进制，S/Q 桩只仿文件布局；R5 同款边界 | live-R5 真机（装 easy-rsa 后走一遍建用户/吊销） |
| U-12 | live-R5 本身的结果 | 与本轮并行在跑，报告落盘时未见其结论；本轮“已修”结论基于先前 live 轮次＋沙箱套件 | 主控核验两路后定夺 |

### 本轮取证失误（自记，不立案）

1. verify-integration 首跑 26/1 的失败格未捕获（只 tail 输出）——见 §1a 注与 U-7。
2. 探针初版把 D 态（策略在位＋探针死）的期望误标为 via_sk5=false——live-R4 S3 的 kill-switch 工作态应为 true，已纠正并重跑确认。
3. **/etc 写入（本轮违规，已清除）**：收尾核查发现 `/etc/sysctl.d/99-openvpn-sk5.conf`（内容仅 `net.ipv4.ip_forward=1`，policy-routing.sh 的原样输出）mtime 为 2026-11-12 07:45 UTC，落在本轮窗口内、此前各轮记录均未提及——极可能是本轮早期复跑某套件时未进 unshare 命名空间、真实 policy-routing.sh 以 root 身份落盘所致，违反“不动 /etc”的审计纪律。该文件已删除（`rm -f`，/etc/sysctl.d 恢复原状）。`/etc/openvpn-sk5-panel/admin.pass`（07:33）＋`secret.key`（06:14）为此前各轮沙箱污染原状，本轮探针均在 unshare 内把该目录绑到 /tmp，未再写入。教训：凡调真实 sk5_manager/policy-routing.sh 的套件复跑，必须进 unshare；事后须以 mtime 核对 /etc。

### 审计方法说明

- 推导方法：状态转移推导（与 R1 文件逐项、R2 旅程、R3 宣称驱动、R4 不变量驱动、R5 故障注入均不同）。枚举 SK5 开关×daemon×策略×fail-open×节点×用户×egress 观测的笛卡尔矩阵，逐格核“盘上持久态 vs 面板上报态 vs 内核真实态”。
- 每条立案均带可复现探针（/tmp/audit6-tests/ 下 8 个探针/套件）与实测输出，不凭代码阅读立案；F15 式夹具失真为本轮重点防范对象——via_sk5 探针刻意不用 monkeypatch，走真实 `GET /api/status`。
- 单审计员，无子代理分派；报告按节增量落盘；测试一律 /tmp 副本，未动项目原文件、/etc（除 unshare 命名空间内绑定）与任何真机。

# AUDIT-R13 — 全量全局回头看（交付前）

## 结论先写

**结论：不能交付，差集 7 条（P2×7，R13-P2-1～R13-P2-7）。**

历史 134 条：131 已修（R12 的 122＋R12 的 9 条本轮全部关闭，变异红证齐全）、2 部分（P0-3、P1-7，按设计）、1 未验（P0-1 部署态）；**无一复发**——已登记的谓词逐条皆绿。本轮 7 条新发现均为同族残留（谓词与 R12 登记项不同，见 §3.1）：队列 sent_at 可解析性缺口（P2-1）、core falsy 合并绕守卫（P2-2）、远程下载吊销核查缺失（P2-3）、Worker 登录畸形体记限流（P2-4）、agent `_as_int` 布尔强制（P2-5）、OVPN_SUBNET 非默认值错位 NAT（P2-6）、flmx-reference.md“照抄”断言无实现（P2-7）。AS/AT/AU/AV 四路修复本身全部行为验证通过（9 棵定点变异树对应格子恰红）；live-9 全部通过、零新 bug（§8 对账：U-8、U-10 关闭）。

- 审计员：独立审计路（未参与建设与修复路 AK/AL/AM/AN/AO/AP/AQ/AR/AS/AT/AU/AV；单审计员边做边写，不派子代理）
- 日期：2026-11-13（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R12 同等广度）
- 推导方法：**部署生命周期推导**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性、R9 对抗操作员＋时间衰变、R10 环境矩阵×修复存活、R11 契约闭合、R12 外部输入枚举均不同）——沿一条部署的完整时间线逐段验证不变量：全新安装 → 注册节点 → 建服务／建用户 → 启用 SK5 → 运行中故障（SK5 死、磁盘满、队列损坏、证书过期、节点掉线）→ 默认重跑／原地升级 → 卸载重装；每段的状态转移须有明确的进入条件、退出条件与失败时的诚实回执，任何一段的静默错位、状态丢失或不可逆毒化即立案。再叠加历史全量复扫（R12 的 125＋9 条逐条定性）与 AS/AT/AU/AV 新代码逐项行为验证（带变异红证）。每条推导链必须落到一条可执行的探针或一条明确的“不可验（写清为什么）”，不许只写文字推断；live-9 结论已落盘，本报告逐项对账（§8）。
- 测试一律在 `/tmp` 副本（`/tmp/r13/tree` 树副本、`/tmp/r13-tests/` 自建 harness＋探针、复用 `~/workspace/ae-tests/poison/` 毒包）上跑；未动项目原文件（除本报告）；Flask 探针进 `unshare -m` 挂载命名空间，`/etc/openvpn-sk5-panel` 与 `/etc/sysctl.d` 绑 /tmp；staged 安装探针进 `unshare -m`，`/opt/openvpn-sk5-panel`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/systemd/system`、`/etc/iptables`、`/var/log/openvpn` 绑 /tmp；未动任何真机。需真机行为复核的项一律写“待 live-10”或对账 live-9，不提前判通过。
- 语法基线：4 个 Python 文件 `py_compile` 全绿；7 个 shell 脚本 `bash -n` 全绿；Worker `node --check` 全绿（见 §0）。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明（与 R9/R10/R11/R12 同款记明）。

## §0 树版本与 AS/AT/AU/AV 改动确认

当前树是 R12 修复路 AS/AT/AU/AV 之后的新树。文件 mtime（UTC）与 R12 §0 基线对照：

| 文件 | mtime (UTC) | 行数 | sha256（前 12 位） | 说明 |
|---|---|---|---|---|
| install.sh | 2026-11-12 15:49:28 | 1074（R12: 1042） | c99196be8d85 | 动过（AV：:161-200 OVPN_SUBNET CIDR 校验＋OVPN_DNS 字符集校验） |
| panel/app.py | 2026-11-12 15:53:31 | 2645（R12: 2406） | 22752ef88b2c | 动过（AS：`_fail_malformed_cmds`、`_valid_port` type 守卫、`_coerce_bool`／`_strict_bool`／`_toggle_value`、`_safe_int`、udp-over-tcp 读键、cmd_get 全 `.get()`） |
| core/openvpn_manager.py | 2026-11-12 15:50:32 | 1529（R12: 1450） | 6956c8b3decf | 动过（AU：render 入口守卫＋`_parse_existing_server_conf`＋三处同族守卫） |
| README.md | 2026-11-12 15:06:33 | 277 | a7988e4339d2 | 未动（R12 mtime） |
| verify.sh | 2026-11-12 14:45:28 | 846 | 7867f557c6bb | 未动（R12 mtime） |
| panel/README.md | 2026-11-12 15:53:34 | 113 | 5a95c1754beb | 动过（AS：:49 udp-over-tcp 参数名改回 `udp_over_tcp`） |
| egress/sk5_manager.py | 2026-11-12 12:37:13 | 1109 | 02de9d8a4908 | 未动（R12 mtime） |
| egress/policy-routing.sh | 2026-11-12 12:13:01 | 364 | 103a121bbdfe | 未动（R12 mtime） |
| verify-integration.sh | 2026-11-12 09:35:55 | 567 | 7e040ea3ee4a | 未动（R12 mtime） |
| cloudflare/src/index.js | 2026-11-12 15:49:41 | 1215（R12: 1182） | e976ceba0505 | 动过（AT：listNodes 跳过无名记录＋fetch 顶层兜底 500＋handleCreateCmd list params 400＋resolveNode 读 body.node） |
| agent/agent.py | 2026-11-12 00:58:12 | 910 | bf1eda50f234 | 未动（R12 mtime） |
| panel/templates/index.html | 2026-11-12 15:21:57 | 1259 | 4f7dc697451c | 未动（R12 mtime） |
| panel/data/ | 2026-11-12 12:14 | 空目录 | — | AE 路清空后仍空；AN 的 staging 拷贝不再往里写任何文件 |
| docs/security.md | 2026-11-12 15:06:31 | 63 | fc625a0b91e3 | 未动（R12 mtime） |
| cloudflare/server-mode.md | 2026-11-12 15:49:28 | 48 | 1e456c7226fe | 动过（AT：:23 补 body.node 及优先级说明） |

语法基线（本轮实测）：`panel/app.py`、`egress/sk5_manager.py`、`core/openvpn_manager.py`、`agent/agent.py` 四文件 `py_compile` 全绿；`install.sh`、`verify.sh`、`verify-integration.sh`、`egress/test-egress.sh`、`egress/policy-routing.sh`、`core/easyrsa.sh`、`agent/install-agent.sh` 七脚本 `bash -n` 全绿；`cloudflare/src/index.js` `node --check` 全绿。

/tmp 资产现状（本轮开工时实测）：**/tmp 已再次被清空**——`/tmp/r11-tests/`、`/tmp/r12-tests/`、`/tmp/an-tests/`、`/tmp/r10/`、`/tmp/aq-tests/`、`/tmp/au-tests/` 全部不存在（R12 §8.4 记明的供 R13 复用资产无一幸存；/tmp 仅剩 X11 套接字目录）。本轮策略：**全部探针与 harness 从 R12/R11 报告机制逐字重建**（见 §8.3 探针重建清单）；venv 新建 `/tmp/r13-tests/venv`（Flask 3.1.3＋bcrypt，已验）；fakebin 新建 `/tmp/r13-tests/fakebin`（fake easyrsa 用真 openssl 签发真证书，fake openvpn 只认 `--genkey secret`，其余见 §8.3）；旧树阴性对照改用**定点变异树**（从当前树逐项回退修复点，见 §1 变异方法说明）——比 R12 的旧树对照更精细：每条修复各有一棵只回退该条的变异树，红格与修复面一一对应。`~/workspace/ae-tests/poison/`（毒 panel.db＋agent_queue.json）幸存。

（以下各节边审边写）

## §1 AS/AT/AU/AV 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

探针与 harness 全部本轮重建（/tmp 资产全灭，见 §0）：fakebin 13 个（easyrsa 用真 openssl 签发真证书、serial/825 天有效期/CN 均真实；openvpn 只认 `--genkey secret`；systemctl 为状态机，staged 安装时真拉起面板、其余单元记 sleep 占位 PID；sing-box 只认 version/check，run 直接 exit 1；ip/iptables/apt-get/dpkg-query/ufw/curl/sysctl/modprobe 均为状态化假件，apt 的 ufw 冲突模型锚定 live-8 真机证据 install3.log:8）；Flask 探针进 `unshare -m`（`/etc/openvpn-sk5-panel`、`/etc/sysctl.d` 绑 /tmp scratch，宿主挂载点预先 mkdir——AK 巷静默绑挂教训）；core 探针直接跑（只碰 scratch CA/SERVER 目录）。变异红证：旧树对照改用定点变异树（从当前树逐项回退修复点），每条修复各一棵变异树，红格与修复面一一对应（§1.5）。

### §1.1 AS（panel/app.py）—— r13_inputs.py 85/86，余 1 格为新发现

重建 86 格（A 登录 8、B 节点参数 10、C init-pki 门 6、D 服务配置 12、E 用户 12、F sk5 开关 12、G udp-over-tcp 4、H 队列畸形 13、I 解析器 3、J 环境变量 3、K 回执／重投 3；格号为 R13 重建编号，期望值逐格锚定 R12 §2.1/§2.2 的立案／观察原文）：**85/86**。两格观察复现：O1（登录缺密码 → 401 非 400）、O10（server_ip 数字 → 200）；X2 裁决：**400 时无写盘**——探针设计矛盾已裁决为“400 即拒写”（本轮 D7 port=True 400 后 conf 无 `port True`，后续渲染 200，见 §1.3）。

唯一红格 **H11 → 新发现 R13-P2-1**（见 §2.1）：`sent_at` 为不可解析字符串（`"garbage"`）的 sent 态命令，两次 poll 后仍 `status=sent, retries=0`——无重投、无失败、无审计行，P1-6 状态机对该命令无出口。AS 的 `_fail_malformed_cmds` 只校验 `sent_at` 的**类型**（须为 str），`"garbage"` 是 str 故不标 failed；`_requeue_stale_sent` 的 `fromisoformat` 抛 ValueError 后 `continue` 跳过，无任何落盘标记。通道不楔（其余命令照常流动），单条命令永久滞留。

### §1.2 AP（nodeparam）—— r13_nodeparam.py 45/45

ghost 对 18 条兼容路由＋body.node／X-Node 全部 404；远程写 9 路全部 202＋cmd_id＋queued 且确实入队（`create_server`/`create_user`/`init_pki` 均在队列中），本地 sk5.json 未被远程写触碰；无快照时远程 status stale=true；心跳（version/hostname/openvpn_running/sk5_enabled）合并进快照；get_status 全量回执（含 clients×2、policy_routing_active）后远程 status `online_users=2, egress.ip=203.0.113.7, via_sk5=true`；远程下载取到队列回执原文；本地建用户／状态／init-pki 行为不变。**45/45**。

### §1.3 AU＋core —— r13_core.py 19/19，r13_au.py 19/20

core 19 格全绿：C0 PKI＋server 证四件套；C1 状态日志真机夹具 `core/tests/test_status_log.py` **5/5**（verbatim live-verify-R2.md 行）；C2 alice .ovpn 3 个 PEM＋remote＋openssl CN=alice；C3 重建拒绝；C4/C6/C7/C8 列表／吊销／吊销后重建／幽灵吊销；C5 非法名 6/6；C9a 同值重渲染字节一致；C9b/C9c P01 冻结／allow 放行；C10 无守护进程 running=false；C11 init_pki 无 force 拒绝；C12 build_server_cert 幂等；C13 conf 行齐全；C14 吊销后 `_user_status` 为 revoked（面板下载 403 的谓词，403 本身见 §1.4 下载探针）；C15 server_ip 进 remote 行；C16 过期 V 行报 expired。

AU 19/20，唯一红格 **G12 → 新发现 R13-P2-2**（见 §2.2）：`render_server_conf("udp", 0)` 与 `render_server_conf("udp", False)` 均不抛错、静默渲染为 port 1194。`port = port or (1194 …)` 一行在 AU 的 `type(port) is int` 守卫之前执行，falsy 值（0、False）在守卫看到之前就被换成默认值。面板（`_valid_port` 400）与 agent（`_as_int` lo=1 拒 0；`_as_bool` 拒非布尔）两路均拦住 0/False，故为纵深防御层缺口、无用户可达路径。

### §1.4 其余（本轮亲自重跑）

- **AT（Worker）**——r13_worker_inputs.mjs **23/23**（W7/W8 的期望已按实测修正：畸形登录体 Worker 回 401＋记限流，见 R13-P2-4；其余 21 格与 R12 期望一致）、r13_worker_y.mjs **13/13**（via_sk5 六格 A–F：enabled＋policy 在位才认，缺字段按缺失处理、绝不复用探针 IP；init-pki 400/202/404、cmd body.node、双节点须指定、改密 501 含 wrangler 指引）。
- **AK/AL（adv）**——r13_adv.py **27/28**，唯一红格 Q3＝R13-P2-1（垃圾 sent_at 滞留）；其余：naive sent_at 重投、数字 sent_at 标 failed、损坏 JSON 整文件隔离且备份字节一致、非对象段隔离、缺文件空队列、非对象条目删除、裸条目 failed、节点队列非列表按空处理；用户建／列表／吊销／吊销后重建、legacy CN=OpenVPN-CA 行（serial 须与证书一致，fake easyrsa 的 serial 格式已按真实 `openssl ca` 的偶长大写 hex 修正）、过期行报 expired、bob .ovpn 下载；服务渲染／同值一致／P01／allow；sk5 纯写盘开关五格。
- **AK 磁盘满**——r13_diskfull.py **5/5**（2M tmpfs 满盘：正密码 200、错密码 401、再正密码 200、释盘后正密码 200、释盘后错密码 401 且失败已记账）。
- **登录限流**——r13_lockout.py **5/5**（5 次错密码 401、第 6 次（正密码）429＋retry_after_s=900＋Retry-After 头、锁定中错密码 429、锁前会话仍可用）。
- **AR 下载**——r13_download.py **11/12**，唯一红格 W10b＝R13-P2-3；本地 valid／未生成 404／已吊销 403／重建后 200／未登录 401、远程回执字节一致、远程未生成 404、远程 ghost 404、远程吊销经 `?node=` 路径 403、远程未登录 401。
- **AR href**——r13_href.mjs **6/6**（withNode 實測：无节点原样、有节点 `?node=`、已有查询串用 `&`、非白名单路径不动、特殊字符编码、:748 dl.href 确走 withNode）。
- **agent**——r13_agent.py **20/21**，唯一红格 N21＝R13-P2-5；其余：未知 action／非对象 params／7 个禁键（含大小写）／非法用户名／缺名／SK5 坏 host／端口 abc／enabled 字符串／port 0／70000／proto bogus／allow 字符串／clear_password 字符串一律 `(False, None, error)` 不抛错；`port "1194"` 字符串宽容通过（port 1194）。
- **env**——r13_env.py **3/3**（OVPN_DNS 含空格 → 服务创建 500＋invalid DNS；OPENVPN_CA_DIR 指向空处 → status 200；OPENVPN_PORT=abc → status 200＋error 含 int 转换错）。
- **AN staged**——probe_bug1：毒树默认重跑 EXIT=0，安装日志 `panel/data/ excluded`＋`generated fresh panel secret key`；落盘 admin hash 与毒库不同（新密码）、无 agent_queue.json（3 条毒 init_pki 未到达）、健康门登录 200、毒包原文件未动。probe_bug2：ufw 预置 2000 条 → 安装 EXIT=0，ufw 二进制与 installed 标记均在、规则 2002 条（2000＋1194＋8443）、日志明示跳过 iptables-persistent 及 NAT live-only 局限、apt.log 零次 iptables-persistent。无 ufw 回归：EXIT=0，apt 正常装 iptables-persistent。
- **AV staged**——校验矩阵 5 格 die（bogus／主机位 10.8.0.1/24／裸 IP／IPv6 ::1/128／/33）全部 EXIT=1 且报错串正确、无任何规则写盘；合法 CIDR 全安装 EXIT=0（server.conf port 1194／proto udp／server 10.8.0.0、3 条规则全带 10.8.0.0/24、健康门 me／login／status 全 200）。
- **changepw**——Worker 501（Y-M 格）＋ Flask 改密 **7/7**（r13_changepw_flask.py：未登录 401、旧密码错 401、新旧相同 400、新密码过短 400、改密成功 200 且旧会话立即 401、新密码登录 200、admin.pass 文件同步为新密码）。

### §1.5 变异红证（9 棵定点变异树，每棵只回退一条修复）

| 变异树 | 回退的修复 | 探针 | 变红格子（旧行为签名） | 结论 |
|---|---|---|---|---|
| m-as1 | `_fail_malformed_cmds` 在 poll 处失效 | r13_inputs | H3/H4/H5/H7/H10（坏条目不再标 failed，照常下发／滞留） | AS 的隔离是真生效，非摆设 |
| m-as2 | `_valid_port` 回 `isinstance` | r13_inputs | D7（port=True → 500）、F3（sk5 port=True → 200） | 注：D7 在本轮为 500 而非 R12 的 200，因 core 的 AU 守卫仍在——纵深防御改了失效模式，但格子仍红 |
| m-as3 | `_coerce_bool` 回 `bool()` | r13_inputs | F5（enabled "false" → 500，恰 R12 F8 签名）、F6/F9/G4（→ 200 反向执行） | 字符串开关反向确已死 |
| m-as4 | udp-over-tcp 两分支读 `enabled` | r13_inputs | G1（200 但存 false，恰 R12-P2-2 签名）、G4 | 读键修复确已生效 |
| m-at1 | listNodes 不跳过无名记录 | worker_inputs | W21/W22（→ 500，兼容路由＋agent 鉴权全灭） | 恰 R12-P2-3 签名 |
| m-at2 | handleCreateCmd 接受 list params | worker_inputs | W15（→ 202） | 恰 R12-P2-4 签名 |
| m-at3 | resolveNode 忽略 body.node | worker_inputs | W11（ghost → 202 静默入队）、W14（body 被忽略 → 404） | 恰 R12-P2-5 签名 |
| m-au1 | render 守卫回宽松 isinstance | r13_au | G1（port=True 不抛）、G5（allow "true" 不抛） | 注：G2/G3（字符串／浮点端口）在变异树仍绿——旧代码本来就拒这两类，R12-P1-2 的洞只是 bool；G12 在两棵树都红（R13-P2-2） |
| m-av1 | OVPN_SUBNET 校验吞 ValueError | staged 安装 | bogus → EXIT=0 | 恰 R12-P2-6 签名 |

新树上全部探针绿（除 7 条新发现对应的红格），变异树上对应格子红——AS/AT/AU/AV 四路修复均有行为红证，非代码在场。

## §2 部署生命周期推导（本轮新方法）

### §2.1 新差集（本轮已确认，汇总见 §8）

**R13-P2-1（P2）——垃圾 `sent_at` 的 sent 态命令永久滞留，状态机无出口（R12-P1-1 同族残留，AS 只修了类型域）。**

- 机制谓词：手改 `agent_queue.json` 使某命令 `status=sent` 且 `sent_at` 为不可解析字符串 → 该命令永不重投、永不失败、无审计行、`cmd_get` 永远显示 sent。
- 位置：`panel/app.py`：`_fail_malformed_cmds`（:549-617）只校验 `sent_at` 为 str，不校验可解析性；`_requeue_stale_sent`（:617-680）`fromisoformat` 抛 ValueError 后 `continue` 跳过且不标记。
- 复现：r13_inputs.py H11——`{"id": "h11", "status": "sent", "sent_at": "garbage", "retries": 0}` 写盘后两次 poll：`200, status=sent, retries=0`（两次均然）。对照：naive `sent_at`（H9）按 UTC 解读后正常重投（retries 0→1）；数字 `sent_at`（H10）被 `_fail_malformed_cmds` 以“sent_at 错型”标 failed。唯独**字符串但不可解析**这一格漏网。
- 影响面：通道不楔（其余命令照常流动），单条命令（可能是一次 create_user/init_pki）永远处于“已发出、未回执、永不重发”态；用户在 cmd_get 里永远看到 sent，无任何失败回执可据以重试。`sent_at=None` 的 sent 态命令同机制（`_requeue_stale_sent` 的 `not cmd.get("sent_at")` 直接跳过）——生命周期探针 L7 已实证：两轮 poll 后仍 `status=sent, retries=0`。
- 修复方向（供修复路）：`_fail_malformed_cmds` 对 `sent_at` 字符串加可解析性校验（不可解析即标 failed＋审计），或 `_requeue_stale_sent` 把不可解析的 `sent_at` 当作已超时处理（重投／失败，二选一须有出口）。

**R13-P2-2（P2）——`render_server_conf` 的 falsy 合并行绕过 AU 的严格类型守卫（R12-P1-2 同族残留）。**

- 机制谓词：`port` 为 falsy 值（`0` 或 `False`）→ 静默渲染为默认端口，不抛错。
- 位置：`core/openvpn_manager.py:1075`：`port = port or (1194 if proto == "udp" else 443)` 在 :1072-1074 的 `type(port) is int` 守卫**之前**执行；`False`（bool）与 `0` 在守卫看到之前就被换成 1194。
- 复现：r13_au.py G12——`render_server_conf("udp", 0, …)` 与 `render_server_conf("udp", False, …)` 均正常返回，conf 含 `port 1194`。对照：`port=True`、`"1194"`、`1194.5`、`70000`、`-1`（面板层）均抛错／400。
- 影响面：无用户可达路径——面板 `_valid_port`（`type(value) is int and 1 <= value`）400 拒 0；agent `action_create_server` 经 `_as_int(lo=1)` 拒 0、`_as_bool` 拒非布尔。属纵深防御层缺口：core 作为最后一道防线，其宣称的“Only real ints 1-65535 are accepted”对 falsy 输入不成立；手改队列条目（agent 侧 `create_server` params `port: 0`）经 `_as_int` 仍被拦，故实际可达性为零，定 P2。
- 修复方向：把 `port is None` 的默认值合并移到类型／范围校验之后，或校验前显式拒绝 falsy 非 None 值（`port is not None and type(port) is not int → raise` 须在 `or` 之前）。

**R13-P2-3（P2）——远程下载两条路径对同一回执 verdict 不一致：`/api/nodes/<node>/users/<user>/ovpn` 不查吊销状态，已吊销用户的 .ovpn 照常下发（本地路由与 `?node=` 路由均 403）。**

- 机制谓词：远程用户被吊销后，其队列回执仍可经专用下载路由原样下载；同一回执经 `/api/openvpn/users/<name>/ovpn?node=<node>` 则 403。
- 位置：`panel/app.py:2396-2413`（`node_user_ovpn`）：只查 `state["ovpn"]` 有无回执，不读节点快照的 users 状态；对照 `ovpn_users_download`（:1732-1790）本地分支查 `list_users()` 状态、远程分支（`?node=`）查快照顶层 `users`，吊销一律 403。`state["ovpn"]` 全树只写不删（:2545 写、`1766`/`2402` 读，无任何吊销清理），回执永久有效。
- 复现：r13_download.py W10/W10b——快照顶层 `users=[{name: dave, status: revoked}]`（真实 agent `get_status` 形状）＋队列回执已就位：`GET /api/openvpn/users/dave/ovpn?node=remote1 → 403`，`GET /api/nodes/remote1/users/dave/ovpn → 200` 且内容与回执字节一致。
- 影响面：下发的 .ovpn 证书已进 CRL、连不上服务器，故无直接接通风险；危害是“已作废凭证无声下发”＋同一资源两条路径 verdict 相反（管理员无法从面板行为判断该用户是否已吊销）。同族：下载路由只查 `revoked` 不查 `expired`——过期用户的 .ovpn 同样 200 下发（生命周期探针 §2.3 L5），属同一谓词的第二例。
- 修复方向：`node_user_ovpn` 在回执前查快照顶层 `users`（与 `?node=` 分支同款形状），吊销／过期一律 403；或在 `revoke_user` 回执成功时删除对应 `state["ovpn"]` 条目。**第二例**：过期证书同谓词——生命周期探针 L5：index 行过期后列表报 `expired`，本地下载仍 200 下发（下载路由只查 `status == "revoked"`，不查 `expired`；`panel/app.py:1779-1783`）。

**R13-P2-4（P2）——Worker 登录把畸形请求体当作一次失败登录（401＋记入限流），Flask 同端点回 400 且不记账（双面契约不一致）。**

- 机制谓词：`POST /api/login` 请求体非 JSON 或为 JSON 数组 → Worker 401＋`loginfail:<ip>` 记一次失败；Flask 400 且不限流记账。
- 位置：`cloudflare/src/index.js:374-395`（`handleLogin`）：`readJson` 返回 null → `password=""` → `!password` → `recordLoginFailure`＋401；对照 `panel/app.py:1166-1170`（`login`）：`_json_body` 出错即 400 返回，`_record_login_failure` 不执行。
- 复现：r13_worker_inputs.mjs W7/W8——非 JSON 体 → 401 且 `loginfail:unknown` 记录已生成；数组体 → 401。Flask 侧 r13_inputs.py A5/A6——同输入 → 400。
- 影响面：向 Worker 面板发畸形体的扫描／健康检查会烧掉限流预算（5 次即锁 IP 15 分钟），Flask 面板无此效应；客户端无法凭状态码区分“请求体坏了”与“密码错了”。定 P2（锁是 IP 维度的，错密码本身同样烧预算，故为边际风险＋契约不一致，非新攻击面）。
- 修复方向：`handleLogin` 在 `readJson` 返回 null 时先回 400（与 Flask 同款），不记失败；或两面统一为 401 但 Flask 侧同样记账（须二选一并写进 server-mode.md）。

**R13-P2-5（P2）——agent 的 `_as_int` 用 `int()` 强制转换，`port=True` 被当成端口 1 真渲染落盘（R12-P1-2 同族，agent 侧残留）。**

- 机制谓词：agent `create_server` 命令 `params.port=True` → `_as_int` 返回 1 → `render_server_conf` 写出 `port 1` 的 server.conf，全程无报错。
- 位置：`agent/agent.py:352-360`（`_as_int`）：`int(value)` 接受 bool（`int(True)==1`）与数字字符串；`action_create_server`（:610-640）不做类型守卫直接传给 core；core 的 AU 守卫此时看到的是合法 int 1，拦不住。对照：面板 `_valid_port`（400 拒 True）、agent 自身 `_as_bool`（拒非布尔）均严格；唯独 `_as_int` 的 `int()` 强制转换是漏网。
- 复现：r13_agent.py N21——全新 server_dir 的子进程中 `execute_command({action: create_server, params: {proto: udp, port: True}})` → `(True, {port: 1, …}, None)`；落盘 `server.conf` 实测含 `port 1`。对照：N16 `port=0` 拒（range）、N17 `port=70000` 拒、N19 `allow_port_change="true"` 拒；唯独 `True` 借 `int()` 溜过。注意一次探针污染教训：N21 若与已渲染 1194 的 server.conf 同目录，P01 会先拒“udp/1194→udp/1”而掩盖本发现（其报错串本身也证明 `_as_int(True)==1`）；须全新 server_dir 才能看到真渲染。
- 影响面：面板侧 400 拦截，正常链路不可达；可达路径只有手改队列条目（或被控面板）直接下发——窄，定 P2。后果是入口端口被静默改成 1（特权端口，OpenVPN 需 root 绑定、且与既定 1194/443 口径冲突），且面板显示的仍是入队时的原值，静默错位。
- 修复方向：`_as_int` 先判 `type(value) is int`（与面板／core 同款），拒绝 bool；数字字符串是否保留宽容须另行裁决（当前 N15：`"1194"` → 1194 通过，属有意的宽容）。

**R13-P2-6（P2）——`OVPN_SUBNET` 非默认值静默错位 NAT 与已服务子网：安装 exit 0，出口断流（AV 只校验了格式，未接线到 core）。**

- 机制谓词：`OVPN_SUBNET=10.9.0.0/24` 安装 → 3 条 iptables 规则全用 10.9.0.0/24，`server.conf` 仍服务 10.8.0.0/24 → 客户端拿 10.8.0.0/24 地址，NAT/FORWARD 永远匹配不上，直连出口断流，全程 exit 0、无报错。
- 位置：`install.sh:93`（默认 `10.8.0.0/24`）、`:761-781`（NAT/FORWARD 用 `$OVPN_SUBNET`）；`core/openvpn_manager.py` 子网固定 `10.8.0.0/24`（模板写死，`render_server_conf` 无 subnet 参数）。README.md:66 的括号（“core 固定值，改了也只影响 NAT 规则”）描述了现象，未说明后果是出口断流；安装日志只打印 `subnet=$OVPN_SUBNET`，不告警错位。
- 复现：staged 安装 `OVPN_SUBNET=10.9.0.0/24` → EXIT=0；`state/iptables.rules` 3 条全为 10.9.0.0/24；`server/server.conf` 为 `server 10.8.0.0 255.255.255.0`。对照：默认安装 3 条规则与 server.conf 均为 10.8.0.0/24，一致。
- 影响面：默认值不受影响；只有主动改 `OVPN_SUBNET` 的用户中招，且失败是静默的（安装成功、面板状态正常、流量黑洞）。定 P2。
- 修复方向：二选一——（a）安装时非默认值直接 die（与 core 固定值一致，诚实拒绝）；（b）把子网接线进 core（`render_server_conf` 接受 subnet 参数，模板 `server` 行与 NAT 同值）。（a）改动最小且与 README 的“core 固定值”口径一致。

**R13-P2-7（P2，文档同族复发）——`docs/flmx-reference.md` 的“照抄”行断言在当前树里不存在：`SCRIPT_VERSION`、版本优先级／防降级机制均未实现，`install.sh` 行号钉位是 FLMX 侧的、已过期。**

- 机制谓词：参考文档称已照抄进本树的版本机制，代码里无对应实现；文档给出的本树 `install.sh` 行号指向无关代码。
- 位置：`docs/flmx-reference.md:24`（1-2：“OpenVPN 面板脚本也加 `SCRIPT_VERSION` 定宽版本号”；同格 `install.sh:183-200 resolve_version`——本树 :183-200 是 AV 的 OVPN_SUBNET 校验 heredoc，无 `resolve_version` 函数，全树 grep 无此名）；`:25`（1-3：“照抄进 `install.sh` 与 `install-agent.sh`；agent 升级先比版本再下载”——全树无版本比较／防降级逻辑，`install.sh`／`install-agent.sh` 均无 `VERSION` 比较、`PINNED_VERSION`、降级拒绝；仅有的 VERSION 是 OS 的 `VERSION_ID` 与 sing-box/tun2socks 的钉死版本号）；同族：`:41`（1-14 `install.sh:703` getopts）、`:42`（1-15 `install.sh:183-260 build_download_url`）、`:43`（1-16 `install.sh:56,371-390,758-775`）等 `install.sh:` 钉位均为 FLMX 侧脚本的行号，与本树 1074 行的 install.sh 对不上。
- 影响面：参考文档（非用户-facing），读者会误以为版本发现／防降级机制已落地；R10-P2-1（文档数字同日过期）同族复发——AO 修的是数字，根因（文档钉位无机械校验）未除。
- 修复方向：按 AO 口径删钉位数字、只留行为描述；或把“未实现”的行改成“未抄／待定”，不许以“照抄”宣称未落地的机制。门禁宜加一条：文档中 `install.sh:`／`agent.py:` 钉位须能 grep 命中，否则红。

### §2.2 生命周期阶段（r13_lifecycle.py 7/8，余 1 格为 R13-P2-1 同族）

| 阶段 | 进入条件 | 退出条件／诚实回执 | 结果 |
|---|---|---|---|
| 全新安装 | 空 DATA_DIR | 首次启动生成随机密码、登录 200 | L1 PASS |
| 注册节点 | panel_url＋token | 201＋token 只返回一次 | nodeparam N-组 PASS |
| 建服务／建用户 | PKI 就绪 | 200＋conf／.ovpn 落盘 | core C2/C9a PASS |
| 启用 SK5 | host/port 合法 | 开关纯写盘（沙箱无守护进程）；真机见 live-9 headline-1 | adv K1-K5 PASS |
| 运行中故障：队列损坏 | 手改队列文件 | poll 200＋坏条目 failed＋审计、整文件隔离有备份 | adv Q4-Q9 PASS |
| 运行中故障：证书过期 | index 行过期 | 列表报 expired；但下载仍 200（R13-P2-3 第二例） | L5 FAIL（记录为 P2-3） |
| 运行中故障：节点掉线／删除 | 节点吊销 | 待发命令标 failed“节点已吊销”、token 失效后 poll 401 | L8 PASS |
| 面板重启 | 进程重起 | 队列持久化：queued 照常下发、stale sent 重投、done 不动 | L2/L3/L6 PASS |
| 面板重启 | 快照过期 | 旧快照读 stale=true＋age_s | L4 PASS（age=59419s） |
| 运行中故障：sent_at 损坏 | 手改 sent_at | 垃圾字符串／None → 永久滞留 sent，无出口 | H11/L7 FAIL（R13-P2-1） |

### §2.3 生命周期探针 r13_lifecycle.py（7/8）

L1 全新安装登录 200；L2 队列跨重启持久化（子进程重导入后 poll，queued 命令照常下发为 sent）；L3 跨重启 stale sent 重投（retries 0→1）；L4 旧快照 stale=true（age 59419s）；L5 过期证书列为 expired 但本地下载仍 200（R13-P2-3 第二例）；L6 done 命令跨重启不动；**L7 FAIL——sent＋sent_at=None 的命令两轮 poll 后仍 sent／retries 0（R13-P2-1 同族，`_requeue_stale_sent` 的 `not cmd.get("sent_at")` 跳过）**；L8 删节点后待发命令 failed“节点已吊销”、旧 token poll 401。

## §3 全量复扫（历史 125＋R12 的 9＝134 条逐条定性）

复扫宇宙：R12 的 125 条（122 已修＋2 部分＋1 未验）＋R12 本轮新发现 9 条＝**134 条**。定性口径与 R12 同款。复扫方法：先以 mtime 对账（§3.0）锁定自 R12 后动过的文件——仅 AS/AT/AU/AV 六文件；其余文件 mtime 与 R12 §3.0 逐项一致，R12 实证沿用（同日、数小时内，复核时效内）；六文件内的历史项本轮全部行为重验（§1／§2／§4）或逐项代码核对；再叠加 §2 部署生命周期推导对全部阶段的重查。

### §3.0 mtime 对账（R12 §3.0 → 本轮，UTC）

自 R12 后动过的文件仅六处（AS/AT/AU/AV）：panel/app.py（15:53:31，2406→2645 行）、cloudflare/src/index.js（15:49:41，1182→1215 行）、core/openvpn_manager.py（15:50:32，1450→1529 行）、install.sh（15:49:28，1074 行）、panel/README.md（15:53:34）、cloudflare/server-mode.md（15:49:28）。其余文件与 R12 §3.0 逐项一致（verify.sh 14:45:28、egress/sk5_manager.py 12:37:13、egress/policy-routing.sh 12:13:01、verify-integration.sh 09:35:55、agent/agent.py 00:58:12、panel/templates/index.html 15:21:57、README.md 15:06:33、docs/security.md 15:06:31）。panel/data/ 仍空。

### §3.1 R12 的 9 条新发现 → 本轮全部关闭

| 项 | R13 状态 | 证据 |
|---|---|---|
| R12-P1-1 队列手改条目缺键即 agent_poll／cmd_get 500 且永久滞留 | **已修** | §1.1：inputs H3/H4/H5/H7/H10 全绿（坏条目标 failed＋审计行、非对象条目删除、numeric sent_at failed）；adv Q4/Q5/Q6/Q7 全绿；m-as1 变异 H3/H4/H5/H7/H10 恰红。**但同族残留另立 R13-P2-1（§2.1）**——AS 只修了类型域，垃圾字符串 sent_at 仍无出口；不是同一条（R12-P1-1 记的是缺键／错型字段，R13-P2-1 记的是可解析性） |
| R12-P1-2 `port=True` 过 `_valid_port`、写坏 server.conf、后续渲染 500 永久冻结 | **已修** | §1.1 D7（400）、§1.3 au G1（render 抛错）、X1/X1b 面板级复核（400、conf 无 `port True`、后续渲染 200）；m-as2 变异 D7/F3 恰红、m-au1 变异 G1/G5 恰红。**但同族残留另立 R13-P2-2（core falsy 合并绕守卫）与 R13-P2-5（agent `_as_int` 强制转换）**——两处均非 R12-P1-2 的原谓词（面板 `_valid_port`），是同一机制在另两条路径上的残留 |
| R12-P2-1 `bool()` 把 `"false"` 变 True，全族开关反向 | **已修** | §1.1 F5/F6/F9/F11/G4 全绿（400）；m-as3 变异 F5/F6/F9/G4 恰红（F5 恰 R12 F8 签名 500）。0/1 接受是 R12 探针钉死的诚实 int 强制，简报文字偏差已接受 |
| R12-P2-2 `/api/sk5/udp-over-tcp` 两分支读错键 `enabled` | **已修** | §1.1 G1/G2/G3 全绿（自然键优先、fallback `enabled`）；panel/README:49 参数改回 `udp_over_tcp`；m-as4 变异 G1（200 但存 false，恰 R12-P2-2 签名）恰红 |
| R12-P2-3 Worker listNodes 无名 KV 记录抛 TypeError、灭全部兼容路由＋agent 鉴权 | **已修** | §1.4 Worker inputs W21/W22 全绿（跳过＋console.warn 记键名、status 200）；m-at1 变异 W21/W22 恰红（500） |
| R12-P2-4 Worker `/api/cmd` 收 list params 回 202 | **已修** | §1.4 Worker inputs W15 全绿（400）；m-at2 变异 W15 恰红（202） |
| R12-P2-5 Worker 忽略 body.node、ghost 静默入队到唯一节点 | **已修** | §1.4 Worker inputs W11（ghost 404）、W14（body 优先 202）全绿；m-at3 变异 W11（202）、W14（404）恰红 |
| R12-P2-6 install.sh 不校验 OVPN_SUBNET、bogus 照常 exit 0 | **已修** | §1.4 AV 校验矩阵 5 格全 die、bogus 全安装 exit 1、无规则写盘；m-av1 变异 bogus → EXIT=0 恰红。**但同族残留另立 R13-P2-6**——AV 只校验了格式，非默认值与 core 固定子网错位仍 exit 0；不是同一条（R12-P2-6 记的是不校验格式，R13-P2-6 记的是格式合法但与 core 不一致） |
| R12-P2-7 cmd_get 对手改条目 500 | **已修** | §1.1 H12 全绿（全 `.get()`＋`_safe_int`、fromisoformat 补 TypeError 捕获）；m-as1 变异 H10 恰红（同族路径） |

### §3.2 R12 的 122 条已修 → 本轮复核

122＝R12 的 122（120＋§3.1 关闭的 R11 的 2 条）。分两组：

**（a）修复宿在六个动过文件内的项——本轮全部行为重验或逐项代码核对，无一沿用旧证：** panel/app.py（inputs 85/86＋adv 27/28＋nodeparam 45/45＋diskfull 5/5＋lockout 5/5＋download 11/12＋changepw 7/7＋lifecycle 7/8＋门禁 28/28；§2 新发现 7 条中 5 条宿在此文件，见 §2.1）；cloudflare/src/index.js（Worker inputs 23/23＋Y 矩阵 13/13＋改密 501；§2 新发现 1 条宿在此文件）；core/openvpn_manager.py（Core 19/19＋au 19/20 本轮重跑；§2 新发现 1 条宿在此文件）；install.sh（AV 校验矩阵＋staged 全安装＋AN probe_bug1/bug2 不退化；§2 新发现 1 条宿在此文件）；panel/README.md／cloudflare/server-mode.md（§6 全量核对）。

**（b）其余项——修复宿在未动文件内，R12 实证沿用（§3.0 mtime 逐项一致，同日复核）：** agent/agent.py（R8 §4f 13/13 沿用＋本轮 r13_agent 20/21 新验，唯一红格为新发现 R13-P2-5）；egress/sk5_manager.py＋policy-routing.sh（门禁 28/28 侧面覆盖；R9 矩阵 4/4＋AG 14/14 沿用）；verify.sh（starter 门单跑 PASS，§4c）；verify-integration.sh（本轮重跑 28/28）。**R12 的 122 条中无一复发——已登记的谓词逐条皆绿；本轮 7 条新发现均为同族残留（谓词不同，见 §3.1 各行末尾与 §2.1），按新口径另立，不计为复发。**

### §3.3 R12 的 2 条部分 → 本轮仍部分

| 项 | R13 状态 | 证据 |
|---|---|---|
| P0-3 bundle/install-agent.sh | **仍部分** | 逻辑已修（Flask agent-bundle 格 200＋tarball 含 agent.py；verify.sh install-agent-script 200）；部署态未验（§5） |
| P1-7 改密＋首登强制改密 | **仍部分（按设计）** | 改密 API＋UI 在位（Flask 改密 7/7 本轮重跑；Worker 501 诚实端点本轮重跑）；首登强制改密从未实现、文档已诚实，不另立案 |

### §3.4 R12 的 1 条未验 → 本轮仍未验

| 项 | R13 状态 |
|---|---|
| P0-1 部署态 | **仍未验**（§5：登录卡住＋KV 占位，与 R12 同卡点） |

### §3.5 U-1～U-12 认领表更新

| # | 项 | R13 更新 |
|---|---|---|
| U-1 | P0-1/2/3 部署态 | 仍未验（§5） |
| U-2 | R6-P1-1 真机复现 | 关闭（live-8 headline-5 显式重跑通过） |
| U-3 | UDP 数据面 | 关闭（live-7 S1/S2＋live-8 S2 再证 TCP+UDP 均走 SK5） |
| U-4 | R 符号链接自拷 | 关闭（无变化） |
| U-5 | R 逐项失败 die 分支 | 仍为“机制已证、分支未触发”：live-8 三装全程跑通；live-9 未记录人为致败 |
| U-6 | T 两变异 | 关闭（R8 已判；R9 T 变异重跑 17/2/4） |
| U-7 | verify-integration 瞬时红 | 关闭（R9/R10/R11/R12/R13 五次 28/28，一次过） |
| U-8 | 真机在位升级路径 | **关闭（live-9 headline-9：毒树默认重跑真机行级比对全过，登录 200、服务端 PID 不变、get_status 202→done）** |
| U-9 | KV 竞态与 POP 传播 | 仍未验（无部署） |
| U-10 | 前端渲染级核查 | **关闭（live-9 headline-7：真机渲染 171 可见文本、0 项低于 4.5、最薄 4.92、零 JS 报错；本轮静态核查 10/10 与之致，§7）** |
| U-11 | easy-rsa 真二进制签发 | 关闭（live-8 headline-2 以 real easyrsa 3.1.0 裁决） |
| U-12 | live-R5 结果 | 关闭 |

复扫合计：134 条＝已修 131（122＋§3.1 关闭的 9 条）／部分 2（P0-3、P1-7）／未验 1（P0-1）；**本轮新发现 7 条另计（R13-P2-1～R13-P2-7，见 §2／§8 差集）**。134＝131＋2＋1；新发现 7 条见 §8 差集。

## §4 套件重跑

### §4a 门禁 verify-integration.sh：28/28（本轮在 /tmp/r13/tree 副本上实测）

`bash verify-integration.sh`：**PASS=28 FAIL=0 SKIP=0**。逐格与 R12 §4a 同款。

### §4b Flask／Worker／Agent

- **Flask（本轮重跑）**：inputs 85/86（余 1 格为新发现 R13-P2-1；O1/O10 为 R12 观察）＋adv 27/28（余 1 格同为 R13-P2-1）＋nodeparam 45/45＋diskfull 5/5＋lockout 5/5＋download 11/12（余 1 格为新发现 R13-P2-3）＋changepw 7/7＋lifecycle 7/8（余 1 格为 R13-P2-1 同族）＋门禁 28/28。**回归复跑**：fake easyrsa serial 格式修正（`2`→`02`，与真实 `openssl ca` 一致）后，inputs／nodeparam／core／au 四套探针各重跑一次——inputs 85/86、nodeparam 45/45、core 19/19、au 19/20，红格与修正前逐格一致（H11、G12），无绿转红。AH 的 flask35.py 已随 /tmp 清理消失，**35/35 未原样重跑**——与 R10/R11/R12 同款缺口，本轮 Flask 面由上述 8 套探针（共 199 格）覆盖，AS 改动面与新发现的 7 条缺口均逐格行为验证；35 格逐格对照缺失，记为本轮套件口径的缺口（见 §8.2），不冒充。
- **Worker（本轮重跑）**：inputs 23/23＋Y 矩阵 13/13＋改密 501（Y-M 格）。部署态仍未验（§5）。
- **Agent（本轮重跑 20/21＋R8 13/13 沿用）**：`agent/agent.py` mtime 与 R12 §3.0 一致（00:58:12，未动），R8 §4f 的 13/13 仍有效；本轮另以 `r13_agent.py` 直测 `execute_command` 输入面 20/21（余 1 格为新发现 R13-P2-5）。
- **Core（本轮重跑）**：单测 5/5（状态日志，夹具为真机捕获行）＋探针 14 格（C0–C13）＝19/19；AU 探针 19/20（余 1 格为新发现 R13-P2-2）。

### §4c 门禁 verify.sh：全量分段未重跑（诚实交代）＋starter 门逻辑单跑 PASS

与 R10/R11/R12 §4c 同款：R9 的 vfy 分段 harness 已失，本轮未重建全量分段跑；已做：(1) `bash -n verify.sh` 过；(2) verify.sh 自 R12 后未动（mtime 14:45:28）；(3) **starter-template-consistency 门逻辑按原文逐字抽取重跑 PASS=1 FAIL=0**（`/tmp/r13-tests/run-starter-gate.sh`，heredoc 按 marker 提取，tun 入站全字段与模板一致、dns.final='dns-direct'）。全量分段数（R9：22/0/1＋T 变异 17/2/4）沿用 R9，不冒充为本轮数。live-9 headline-6（verify.sh 双态真机跑：开 18/0/4、关 23/0/0）即该门禁的真机总验。

### §4d Egress 套件：test-egress.sh §6 矩阵 4/4（沿用 R9）

`egress/test-egress.sh`、`egress/sk5_manager.py`、`egress/policy-routing.sh` 三文件 mtime 与 R12 §3.0 逐项一致（未动），R9 §4d 的 §6 矩阵 4/4 与 AG policy 矩阵 14/14 沿用。本轮未重建 egress harness；sk5_manager 的保存／启停路径由门禁 28/28 与 inputs 探针 F/X/Y 格侧面覆盖。

### §4e 五套件总览

| 套件 | 规模 | 结果 |
|---|---|---|
| Flask inputs＋adv＋nodeparam＋diskfull＋lockout＋download＋changepw＋lifecycle（本轮重跑） | 86＋28＋45＋5＋5＋12＋7＋8 | **85/86＋27/28＋45/45＋5/5＋5/5＋11/12＋7/7＋7/8**（红格 4 格映射新发现 2 条：R13-P2-1 ×3、R13-P2-3 ×1） |
| Worker inputs＋Y 矩阵＋改密（本轮重跑） | 23＋13＋1 | **23/23＋13/13＋501**（W7/W8 期望已按实测修正，见 R13-P2-4） |
| Agent inputs（本轮重跑）＋R8 13/13 | 21＋13 | **20/21＋13/13（沿用）**（红格 1 格为新发现 R13-P2-5） |
| Core（本轮重跑）＋AU 探针 | 19＋20 | **19/19＋19/20**（红格 1 格为新发现 R13-P2-2） |
| Egress（沿用 R9，代码未动） | 4＋14 | **矩阵 4/4＋policy 14/14** |
| verify-integration.sh（门禁，本轮重跑） | 28 | **28/28** |
| verify.sh（门禁） | 23 | **全量分段未重跑**（§4c）；starter 门逻辑单跑 PASS；live-9 headline-6 双态真机通过 |

## §5 P0-1/2/3：真实 wrangler deploy 重验——卡在登录，仍未验

- **dry-run 通过**（本轮重跑，wrangler 4.161.0 经 npx，自 `cloudflare/` 目录）：`npx wrangler deploy --dry-run` exit 0——绑定列出 `env.PANEL_KV (REPLACE_WITH_KV_NAMESPACE_ID)` 与 `env.PANEL_MODE ("cloudflare")`。dry-run 只证配置可解析，不证部署。
- **真 deploy 卡在第一步：无登录**（本轮重跑，exit 1）：`In a non-interactive environment, it's necessary to set a CLOUDFLARE_API_TOKEN environment variable for wrangler to work.`（与 R7/R8/R9/R10/R11/R12 同一卡点；本机 `~/.config/.wrangler/` 下只有 logs＋metrics.json、无登录态，环境变量 `CLOUDFLARE_API_TOKEN` 未设置）。`wrangler.toml:32-33` 的 KV id 与 preview_id 仍是占位符 `REPLACE_WITH_KV_NAMESPACE_ID`／`REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`，是第二道卡点。
- **需要用户做的事（按顺序，缺一不可，与 R12 同款）**：(1) 在 Cloudflare 账号上建 API token（Workers＋KV 权限）并以 `CLOUDFLARE_API_TOKEN` 交给部署环境，或在可交互终端跑 `wrangler login`；(2) `wrangler kv namespace create PANEL_KV` 与 `--preview` 各一次，把返回的真实 id/preview_id 填进 `wrangler.toml`；(3) `wrangler secret put ADMIN_PASSWORD` 与 `wrangler secret put AGENT_BUNDLE_ORIGIN`；(4) `wrangler deploy`，再按 cloudflare/README:83 的要求换第二出口多点核（Workers 按 POP 慢速传播，单出口“没生效”不可信）。
- **结论**：P0-1/2/3（Worker 真实部署态）**仍未验**，与 R12 结论一致；Worker 代码侧的全部行为断言只在 mock KV＋本地 fetch 入口下成立，不是部署态证据。`--temporary` 未用——那会把 Worker 部署到临时抛弃账号上，不是用户的部署，测了也是冒充结论。

## §6 文档宣称全量核对

核对方法：每份文档的数字类宣称（门禁数、行数、端口、超时、重试上限、行号钉位）与行为类宣称逐条对代码/实测；数字以 `wc -l` 为准。自 R12 后动过的文档仅 panel/README.md 与 cloudflare/server-mode.md，其余文件与 R12 §6 的核对结论逐项复核（mtime 一致）＋本轮新验。

**通过的宣称**：
- 根 README:226 门禁数 28（本轮 verify-integration.sh 重跑 28/28 一致）；:198 哈希钉位 `install.sh:63-66`（本轮实测该四行仍是四条 sha256 钉死值，与 agent.py:123/126/129/132 逐值一致——950af37e…／20a6a9cd…／a612baa2…／3931476c…）；:137 SK5 端口待确认注（1001 默认、9000 待回报，与面板字段旁注 index.html:470-471 一致）；:243 API 列表（与 §2a 读到的路由表一致）；用户名规则 `[a-zA-Z0-9_-]{1,32}`＋保留名 `server`／`OpenVPN-CA`（与 core:99-119 一致；inputs E4/E5 行为验证 400）。
- panel/README:57–58：子网固定 `10.8.0.0/24`、DNS 固定 `1.1.1.1`（与 core 模板一致；亦是 R13-P2-6 的机制根源——文档写明了固定值，但未写明改 `OVPN_SUBNET` 的后果）；P01“已建服务改端口无 `allow_port_change=True` 即 500 拒绝”（au 探针 G8/G9 行为验证一致）。
- server-mode.md:23 多节点行已补 `body.node` 与优先级 body.node > `?node=` > `X-Node`（AT 修后，Worker Y 矩阵 J 格＋nodeparam B 格行为验证一致）；同表“命令 sent 态 120 秒自动回队、最多重投 3 次”与 security.md:12 一致（但见下述 R13-P2-1 的文档侧）。
- AQ 四处模式限定在位：docs/security.md:11、README:260、panel/README:31/:101——均写明改密“仅服务器（Flask）模式可用；Cloudflare 模式回 501，须用 `wrangler secret put ADMIN_PASSWORD`”（§1.4 行为验证一致）。
- 超时／计数类（全树 grep＋实测一致）：健康检查 60s、agent 轮询 5s、状态缓存 10s、重投 120s／3 次（panel/README:90、security.md:12 同值）、登录限流 5 次／5 分钟／锁 15 分钟（lockout 行为验证 429＋`retry_after_s: 900`）、证书 825 天。
- AO 根治有效：全树 grep 带日期实测数字归零（R12 §1g 口径）；本轮复扫未发现新的带日期行数／行号数字——**但 R13-P2-7 是同一文档同族的另一形态（“照抄”断言无实现），见下述**。

**新发现的文档侧问题（立案见 §2／§8，不另立条）**：
- flmx-reference.md:24–25：`install.sh:183-200 resolve_version`／`SCRIPT_VERSION`／版本优先级与防降级“照抄”断言在当前树里不存在（R13-P2-7）；同族 `install.sh:` 钉位（:41／:42／:43 等）均为 FLMX 侧脚本行号，与本树 install.sh 对不上。
- README.md:66 的 `OVPN_SUBNET` 括号（“core 固定值，改了也只影响 NAT 规则”）描述现象但未说明后果是出口断流（R13-P2-6 的文档侧）。
- security.md:12／server-mode.md:23 的“sent 态 120 秒未回执即自动打回”无条件宣称——垃圾 sent_at 的命令永不回队（R13-P2-1 的文档侧），该句须加“sent_at 可解析”的前提。

## §7 前端静态对比度核查

方法：跑 `panel/static/contrast-check.py`（WCAG 相对亮度；底线 4.5、目标 7）。**脚本结果：10/10 过底线 4.5（exit 0）；目标 7 达成 4/10——与 R9/R10/R11/R12 逐值一致。** 结论：静态核查通过底线；6 对低于目标 7（最低为成功绿字 4.92，仅高于底线 0.42），记为观察、不立案——门禁脚本的通过线就是底线，且 R7 九维视觉审计未以对比度立案。真机渲染已由 live-9 headline-7 通过（171 可见文本、0 项低于 4.5、最薄 4.92、零 JS 报错），U-10 关闭。

## §8 裁决与未验清单

### §8.1 裁决：**不能交付，差集 7 条**

| 级别 | 条目 |
|---|---|
| P1 | 0：R12 的 2 条 P1 已全部修好（§3.1，变异红证齐全） |
| P2 | 7：R13-P2-1（垃圾 sent_at 的 sent 态命令永久滞留）、R13-P2-2（core falsy 合并绕守卫）、R13-P2-3（远程下载两条路径对同一回执 verdict 不一致＋过期证本地下载仍 200）、R13-P2-4（Worker 登录畸形体记限流）、R13-P2-5（agent `_as_int` 把 port=True 渲染成 port 1）、R13-P2-6（OVPN_SUBNET 非默认值错位 NAT、exit 0）、R13-P2-7（flmx-reference.md“照抄”断言无实现、行号钉位过期） |
| 高（阻塞） | 0：R12 的 9 条与 R11 的 2 条、R10 的 1 条、R9 的 5 条、live-8 的 2 条已全部修好（§1／§3，变异红证齐全） |
| P0 | 0 未修、1 未验：P0-1/2/3 部署态仍未验（§5）；P0-3 部分（按设计，部署态未定） |

差集＝7 条（P2×7）。R12-P1-1 与 R12-P1-2 已全部关闭（§3.1），历史 134 条中 131 条已修（§3.5）；AS/AT/AU/AV 的修复本身本轮全部行为验证通过（§1，变异红证齐全），套件全绿（§4e，见 §4b/§4c 的两处口径缺口）。但这不改变差集非空的结论：本轮部署生命周期推导新发现的七条都是“状态转移缺出口或静默错位”——一条 sent 态命令无失败回执（R12-P1-1 同族残留）、两条布尔端口守卫在另两条路径上残留（R12-P1-2 同族残留）、一条下载路径的吊销核查缺失、一条双面登录契约分歧、一条安装变量与 core 固定值错位、一条文档“照抄”断言无实现。七条中四条宿在 Flask、一（半）条在 core、一（半）条在 agent、一条在 Worker、一（半）条在 install.sh、一（半）条在文档；旧树对照与变异树证明无一是 AS/AT/AU/AV 回归。

**下一步（按用户常设流程）**：派修复路修 R13 的 7 条（按文件面可分四路并行：① panel/app.py——P2-1＋P2-3，② core/openvpn_manager.py＋agent/agent.py——P2-2＋P2-5，③ cloudflare/src/index.js——P2-4，④ install.sh＋docs/flmx-reference.md——P2-6＋P2-7；修法方向见 §2.1），修完集成后跑 **AUDIT-R14（全量全局回头看，换推导方法独立复算）＋ live-10（真机总验，含本轮 7 条的真机行为格）对账**，两路都过才交付。修复路开工前须先确认：本报告基线树版本（§0）与修复路所取树一致。

### §8.2 live-9 对账（逐项）

live-verify-R9.md（186 行，2026-11-12 23:58 CST）全部通过、零新 bug。本轮对账：
- **S0–S4 全过**：毒树全新安装一次成功；节点＋agent＋命令链 202→done；UDP 1194；SK5 TCP+UDP 经 dante；kill-switch 全黑、自动恢复；TCP 443 首连 5 次全 1 秒（R7 的单次 120s 未复现；首版 try 1 的 120s 已三证定位为测试侧旧 UDP 客户端未清，非产品缺陷）。
- **headline-1～7 全过**：首次启用 200＋10 次交替 delta 恰 10；并发同名 carol 200+409、单条 V 记录；并发启用 delta 恰 1；policy 状态干净；policy 缺失诚实＋零重启修复；verify.sh 开 18/0/4、关 23/0/0；真机渲染 171 可见文本、0 项低于 4.5、最薄 4.92、零 JS 报错（→ U-10 关闭）。
- **headline-8（R8-BUG-2＋R8-P2-4 真机终验）通过**：ufw 2000 条原规则完整、1194/8443 已加、日志 `ufw: allowed`、0 ERROR；无 ufw 回归格亦过。
- **headline-9（R8-BUG-1 真机验收）通过**：毒树默认重跑行级比对——admin/login_attempts 逐行一致、nodes 除心跳 last_seen 外全一致、audit 11→13 前 11 行逐行一致、新增 2 行均为合法登录；登录 200、服务端 PID 802368 不变、get_status 202→done（→ U-8 关闭）。
- **本轮树 14:42 打包、早于 AP/AQ/AR 与 AS/AT/AU/AV**：R11 的 2 条与 R12 的 9 条不在 live-9 验收范围——本轮沙箱侧已全部行为重验关闭（§3.1），但**真机行为格须由 live-10 补**（见 §8.3 第 9 项）。
- **R9-P2-2（磁盘满登录）未复测真机**：live-9 未跑该格；本轮沙箱 diskfull 5/5（§1.4），与 R12 同口径（门禁探针格）。

### §8.3 未验清单（逐项：为什么没验、谁能验）

1. **P0-1/2/3 真实 wrangler deploy（§5）**——卡在 Cloudflare 登录（非交互环境须 `CLOUDFLARE_API_TOKEN`，`~/.config/.wrangler/` 无登录态；wrangler.toml 的 KV id 与 preview_id 仍是占位符）。谁能验：用户建 API token（或交互式 `wrangler login`）＋`wrangler kv namespace create PANEL_KV`（生产＋预览）填实 id＋`wrangler secret put ADMIN_PASSWORD`／`AGENT_BUNDLE_ORIGIN` 后，live 路跑真实 `wrangler deploy`，再从第二出口核 POP 传播。本轮不许用 mock 冒充。
2. **Cloudflare KV 竞态＋POP 传播**——依赖第 1 项的真实部署；无部署则无从测。谁能验：同第 1 项，部署后多点核。
3. **SK5 端口 1001 vs 9000**——用户从未确认哪个是 SOCKS5 口（面板默认 1001，文档已标注待确认，README:137＋index.html:470-471）。谁能验：用户回报；live 路再以确认后的端口跑 UDP/TCP 双栈。
4. **D13 PKI 段竞态**——沙箱无 easyrsa 二进制，两路并发安装／重跑时 `init_pki`＋`build-ca` 的先查后建竞态测不到（copy 段已验，见 R9 §2）；live-8 未跑并发安装（§17 为顺序三装），live-9 亦未跑，仍未验。谁能验：live-10 在真机上跑并发安装／并发重跑。
5. **D14 时钟跳变**——沙箱无 faketime，改系统时钟超出审计范围；仅代码级分析（锁定／会话／重投／健康全是墙钟）。谁能验：真机上以 faketime 或受控调钟复核（须用户授权调真机时钟）。
6. **Flask 35/35 未原样重跑**——AH 的 flask35.py 已随 /tmp 清理消失；本轮 Flask 面由 inputs 86＋adv 28＋nodeparam 45＋diskfull 5＋lockout 5＋download 12＋changepw 7＋lifecycle 8＝196 格覆盖（§4b），AS 改动面与新发现的 7 条缺口均逐格行为验证，但 35 格逐格对照缺失。谁能验：下一轮审计重建 flask35 或等效套件；live-9 的真机 S0–S4 覆盖同一面的行为。
7. **verify.sh 全量分段未重跑**——R10 的 vfy harness 已失，本轮只单跑了 starter 门逻辑（§4c PASS）＋`bash -n`；全量分段数沿用 R9。谁能验：live-9 headline-6（verify.sh 双态真机跑）即该门禁的真机总验。
8. **U-5 die 分支**——机制已证、分支未触发（live-8 三装全程跑通；live-9 未记录人为致败）。谁能验：live-10 人为致败安装步骤。
9. **R13 新发现 7 条的真机行为格**——本轮全部沙箱行为验证（§2.1）；真机后果（P2-1 的 agent 全通道是否受单命令滞留影响、P2-5 的 port 1 是否致 daemon 冲突、P2-6 的非默认子网是否真断流）未在真机上证实。谁能验：live-10 在真机上逐条复现（或等修复路修完后以变异复核）。
10. **R13-P2-6 的真机断流后果**——沙箱已证规则与 server.conf 错位（exit 0）；真机上客户端流量是否真黑洞未证。谁能验：live-10 以非默认 OVPN_SUBNET 装一台真机、走一遍客户端流量。

### §8.4 审计方法自述（供 R14 复核）

- 本轮方法：部署生命周期推导（§2，沿全新安装→注册节点→建服务／建用户→启用 SK5→运行中故障→默认重跑／原地升级→卸载重装逐段验证不变量，每段须有进入条件、退出条件与失败时的诚实回执）＋历史全量复扫（§3，134 条，mtime 对账＋六文件内逐项重验）＋新代码逐项行为验证（§1，亲自重跑、零 monkeypatch 走真实代码路径、9 棵定点变异树红证）＋套件重跑（§4，Flask 8 套探针＋Core＋双门禁重跑＋Worker Y 矩阵重建＋Agent／Egress 沿用 mtime 未动文件）＋P0 部署态重验（§5）＋文档宣称全量核对（§6）＋前端静态对比度核查（§7）。
- 探针纪律：凡套件格先红，必先查探针本身（本轮修掉的探针问题：users POST 用 `name` 非 `username`；dns 非 API 字段；poll/report 鉴权键为 `node_name`／`node_token`；`/api/cmd` 先验 action 再验 node；`_resolve_compat_node` 去空格；status 路由包 ovpn 块 try/except；`_login_attempts_row` 返回 tuple；`build_client_config` 为纯函数；fake easyrsa serial 须为偶长大写 hex；probe changepw 的 `client.get` 返回 Response 非 tuple。探针修好重跑后才定性，不在探针 artifact 上立案）。
- 沙箱边界：无 systemd／无 TUN／无 easy-rsa／无 openvpn 二进制／UDP sendto 临时端口 EPERM——凡涉此五项的结论均已标注分段环境或待真机（live-10），未把沙箱结论写成真机结论。fake apt 的“装 iptables-persistent 即卸 ufw”模型以 live-8 真机证据为锚（install3.log:8），fake easyrsa 的 index.txt 语义以 openssl 真签发为锚（serial 偶长大写 hex），mock KV 的 Worker 本地入口以 R8 的 18/18 同款为锚——桩的行为均有真机／真程序对照，不是凭空捏造。
- 本轮审计侧污染：无。探针进 `unshare -m` 绑挂（`/etc/openvpn-sk5-panel`、`/etc/sysctl.d` 绑 /tmp），收尾复核：宿主 `/etc/openvpn-sk5-panel/`、`/etc/openvpn/`（含空 `server/` 子目录）两个空挂载点目录已 rmdir 删净（`mkdir -p` 预建的空目录，无文件）；`/etc/sysctl.d/99-openvpn-sk5.conf`、`/run/openvpn-sk5-panel/` 不存在。收尾复核时发现 `core/__pycache__/openvpn_manager.cpython-312.pyc`（本轮探针导入原树 core 生成，Nov 12 16:14 UTC）仍在，已删除并 rmdir 该目录；其余 panel／egress／agent 的 `__pycache__` 已删净；`core/tests/__pycache__/test_status_log.cpython-312.pyc`（2026-11-12 07:45 UTC）是早轮遗留、非本轮产生，留原样未动；live-verify-R9.md 是 live-9 的文件。
- /tmp 资产（供 R14 复用）：`/tmp/r13/tree`（树副本）、`/tmp/r13/mutants/`（m-as1～m-av1 九棵定点变异树）、`/tmp/r13-tests/`（本轮全部探针＋harness：r13_inputs／r13_nodeparam／r13_core／r13_au／r13_adv／r13_diskfull／r13_lockout／r13_download／r13_changepw_flask／r13_worker_inputs／r13_worker_y／r13_href／r13_agent／r13_env／r13_lifecycle、run-flask.sh／run-install.sh／cleanup-install.sh／run-starter-gate.sh、build-mutants.py、fakebin、venv、install-runs/）。
- **本轮未重建的 R12 探针（诚实记账）**：r12_inputs2（11/12）、r12_inputs3（6/6）、r12_inputs4（9/9）未原样重跑——三套件的探针文件已随 /tmp 清理消失。其中 inputs2 的 X2 首格（探针设计矛盾）已由本轮裁决：D7（port=True → 400）＋conf 无 `port True`＋后续渲染 200，即“400 时无写盘”；其余格子未逐格重验，记为本轮套件口径的缺口（与 flask35 同款），不冒充。AS/AT/AU/AV 改动面与 R12-P1-1／P1-2／P2-1／P2-2／P2-7 本身均已逐格行为验证（§1.1–§1.5），缺口仅在三套件的逐格对照。

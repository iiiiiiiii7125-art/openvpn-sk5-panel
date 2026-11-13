# AUDIT-R14 — 全量全局回头看（交付前，第二轮）

## 结论先写

**结论：不能交付，差集 3 条（P2×3，R14-P2-1～R14-P2-3）。**

历史 141 条：138 已修（R13 的 131＋R13 的 7 条本轮全部关闭，变异红证齐全）、2 部分（P0-3、P1-7，按设计）、1 未验（P0-1 部署态，见 §5）；**无一复发**——已登记的谓词逐条皆绿。本轮 3 条新发现均为同族残留（谓词与 R13 登记项不同，见 §3.1）：坏条目隔离漏了吊销与专用下载两条路径（P2-1）、render 的 dns falsy 合并绕过守卫（P2-2）、cloudflare/README 的 `agent.py:676` 钉位已过期（P2-3）。AW/AX/AY/AZ 四路修复本身全部行为验证通过（7 棵定点变异树对应格子恰红）；live-10 与本轮并行在跑，结论以其报告为准（§8 对账待补，本报告不代判）。

- 审计员：独立审计路（未参与建设与修复路 AW/AX/AY/AZ；单审计员边做边写，不派子代理）
- 日期：2026-11-13（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R13 同等广度）
- 推导方法：**证据优先的行为复推导**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性、R9 对抗操作员＋时间衰变、R10 环境矩阵×修复存活、R11 契约闭合、R12 外部输入枚举、R13 部署生命周期均不同）——从行为探针出发反推每一项声称：每一项登记结论须有本轮亲手跑出的行为证据（探针输出／变异红证），不认代码在场、不认上一轮结论、不认手写夹具（解析外部程序日志的夹具必须取自真机捕获的真实行）。再叠加历史全量复扫（R13 的 134＋7 条逐条定性）与 AW/AX/AY/AZ 新代码逐项行为验证（带变异红证）。每条推导链必须落到一条可执行的探针或一条明确的“不可验（写清为什么）”；live-10 结论尚未落盘，本报告不提前代判（§8）。
- 测试一律在 `/tmp` 副本（`/tmp/r14/tree` 树副本、`/tmp/r13-tests/` 沿用 R13 的 harness＋探针、复用 `~/workspace/ae-tests/poison/` 毒包）上跑；未动项目原文件（除本报告）；Flask 探针进 `unshare -m` 挂载命名空间，`/etc/openvpn-sk5-panel` 与 `/etc/sysctl.d` 绑 /tmp；staged 安装探针进 `unshare -m`，`/opt/openvpn-sk5-panel`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/systemd/system`、`/etc/iptables`、`/var/log/openvpn` 绑 /tmp；未动任何真机。需真机行为复核的项一律写“待 live-10”或对账 live-9，不提前判通过。
- 语法基线：4 个 Python 文件 `py_compile` 全绿；7 个 shell 脚本 `bash -n` 全绿；Worker `node --check` 全绿（见 §0）。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明（与 R9/R10/R11/R12/R13 同款记明）。

## §0 树版本与 AW/AX/AY/AZ 改动确认

当前树是 R13 修复路 AW/AX/AY/AZ 之后的新树。文件 mtime（UTC）与 R13 §0 基线对照：

| 文件 | mtime (UTC) | 行数 | sha256（前 12 位） | 说明 |
|---|---|---|---|---|
| install.sh | 2026-11-12 16:46:54 | 1082（R13: 1074） | 3f050f037e7a | 动过（AZ：:208 OVPN_SUBNET 非默认值 die；README:66 同步） |
| panel/app.py | 2026-11-12 16:47:08 | 2694（R13: 2645） | aebd74920f81 | 动过（AW：`_fail_malformed_cmds` sent_at 可解析性校验、`_snapshot_users`／`_download_block_reason`、三路下载统一 403；与主控核验的 sha256 一致） |
| core/openvpn_manager.py | 2026-11-12 16:46:20 | 1542（R13: 1529） | 02b7431297e6 | 动过（AX：render 默认值合并改 `port is None` 显式判定、`_server_endpoint` 两处 or 合并同款改） |
| agent/agent.py | 2026-11-12 16:46:20 | 922（R13: 910） | 7f999298df5b | 动过（AX：`_as_int` 先拒 bool／float，数字字符串保留宽容） |
| cloudflare/src/index.js | 2026-11-12 16:45:26 | 1221（R13: 1215） | e40fe4d7d8d0 | 动过（AY：handleLogin 畸形体先回 400 不记限流） |
| README.md | 2026-11-12 16:46:57 | 277 | 33f530b9fa71 | 动过（AZ：:66 子网括号改写为诚实后果） |
| panel/README.md | 2026-11-12 16:46:57 | 113 | 2c9c5e6e43e7 | 动过（AZ：:57-58 同族补一行） |
| docs/security.md | 2026-11-12 16:47:16 | 63 | da5277cb0438 | 动过（AW：:12 补“sent_at 可解析”前提） |
| cloudflare/server-mode.md | 2026-11-12 16:50:36 | 48 | 245e0d448b54 | 动过（AW：:21 补“sent_at 缺失／不可解析时直接标 failed”前提） |
| docs/flmx-reference.md | 2026-11-12 16:47:28 | 112 | ee8ded22f7ed | 动过（AZ：9 行——删 8 处裸 `install.sh:` 钉位，4 行改“未抄（待定）”） |
| panel/templates/index.html | 2026-11-12 15:21:57 | 1259 | 4f7dc697451c | 未动（R13 mtime） |
| verify.sh | 2026-11-12 14:45:28 | 846 | 7867f557c6bb | 未动（R13 mtime） |
| verify-integration.sh | 2026-11-12 09:35:55 | 567 | 7e040ea3ee4a | 未动（R13 mtime） |
| egress/sk5_manager.py | 2026-11-12 12:37:13 | 1109 | 02de9d8a4908 | 未动（R13 mtime） |
| egress/policy-routing.sh | 2026-11-12 12:13:01 | 364 | 103a121bbdfe | 未动（R13 mtime） |
| panel/data/ | 2026-11-12 12:14 | 空目录 | — | AE 路清空后仍空；AN 的 staging 拷贝不再往里写任何文件 |

语法基线（本轮实测）：`panel/app.py`、`egress/sk5_manager.py`、`core/openvpn_manager.py`、`agent/agent.py` 四文件 `py_compile` 全绿；`install.sh`、`verify.sh`、`verify-integration.sh`、`egress/test-egress.sh`、`egress/policy-routing.sh`、`core/easyrsa.sh`、`agent/install-agent.sh` 七脚本 `bash -n` 全绿；`cloudflare/src/index.js` `node --check` 全绿。

/tmp 资产现状（本轮开工时实测）：**R13 资产幸存**——`/tmp/r13/tree`（树副本）、`/tmp/r13/mutants/`（m-as1～m-av1 九棵 R13 定点变异树）、`/tmp/r13-tests/`（全部探针＋harness＋fakebin＋venv＋install-runs/）均在；`~/workspace/ae-tests/poison/` 幸存。本轮策略：R13 探针原样复用（以 R13 报告机制为准，不改期望——除非期望本身断言的是 bug 行为，见 §1.1 注）；变异红证改用**新变异树**（从当前树逐项回退 AW/AX/AY/AZ 的修复点，见 §1.5）；R13 的旧变异树（m-as1～m-av1）作为 R12 修复存活的对照复用（§3.1）。

（以下各节边审边写）

## §1 AW/AX/AY/AZ 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

探针与 harness 沿用 R13（`/tmp/r13-tests/`，幸存，见 §0）：fakebin 13 个（easyrsa 用真 openssl 签发真证书；openvpn 只认 `--genkey secret`；systemctl 为状态机，staged 安装时真拉起面板；sing-box 只认 version/check；ip/iptables/apt-get/dpkg-query/ufw/curl/sysctl/modprobe 均为状态化假件）；Flask 探针进 `unshare -m`（`/etc/openvpn-sk5-panel`、`/etc/sysctl.d` 绑 /tmp scratch，宿主挂载点预先 mkdir）；core 探针直接跑（只碰 scratch CA/SERVER 目录）。本轮全部探针对 **`/tmp/r14/tree`（现树逐字节拷贝，sha256 逐项对 §0 一致）** 跑，不直接跑项目树。变异红证：新变异树（从现树逐项回退 AW/AX/AY/AZ 的修复点，`/tmp/r14/build-mutants.py`，每处回退点断言唯一命中），见 §1.5。

### §1.1 AW（panel/app.py）—— r13_inputs.py 86/86、r13_lifecycle.py 8/8、r13_download.py 12/12、r13_adv.py 28/28

**86/86**：H11（垃圾 sent_at 的 sent 态命令）转绿——两次 poll 后标 failed＋审计行，不再滞留；H9 naive sent_at 仍正常重投、H10 数字 sent_at 仍标 failed。O1（登录缺密码 → 401 非 400）、O10（server_ip 数字 → 200）两格观察复现，与 R12/R13 同款。**lifecycle 8/8**：L7（sent_at=None 的 sent 命令）转绿——有明确出口（failed）；L5（过期证本地下载）转绿——403。**download 12/12**：W10b（远程吊销经 `/api/nodes` 路径）转绿——403；W4（本地吊销）／W10（远程吊销经 `?node=`）仍 403。**adv 28/28**：Q3（垃圾 sent_at）转绿。其余：nodeparam 45/45、diskfull 5/5、lockout 5/5、changepw 7/7（见 §1.4）。

### §1.2 AX（core＋agent）—— r13_core.py 19/19、r13_au.py 20/20、r13_agent.py 21/21

**AU 20/20**：G12（`render_server_conf("udp", 0)`／`("udp", False)`）转绿——均抛错；`port=None` 仍正常取默认 1194。**Core 19/19**：C0–C16 全绿（含真机夹具状态日志 5/5）。**Agent 21/21**：N21（全新 server_dir 下 `create_server port=True`）转绿——命令失败、不落盘 `port 1`；N15（`"1194"` 字符串宽容）仍通过。

### §1.3 AY（Worker）—— r13_worker_inputs.mjs 23/23、r13_worker_y.mjs 13/13

W7（非 JSON 登录体）／W8（数组登录体）转绿——均 400 且 `loginfail:unknown` 无记录；`{}` 缺密码仍 401＋记账（与 Flask 一致）；Y 矩阵 13/13（含改密 501、via_sk5 六格、init-pki、cmd body.node）。

### §1.4 其余（本轮亲自重跑）

- **r13_env.py 3/3**：OVPN_DNS 含空格 → 服务创建 500＋invalid DNS；OPENVPN_CA_DIR 指向空处 → status 200；OPENVPN_PORT=abc → status 200＋error 含 int 转换错。
- **r13_href.mjs 6/6**：withNode 实测（无节点原样、有节点 `?node=`、已有查询串用 `&`、非白名单路径不动、特殊字符编码、:748 dl.href 确走 withNode）。
- **AZ staged（本轮亲自重跑）**：默认安装 EXIT=0——panel steady（api/me 200）、健康门 login＋/api/status 200、3 条规则全 10.8.0.0/24、server.conf `server 10.8.0.0`；`OVPN_SUBNET=10.9.0.0/24` EXIT=1、die 文案在日志中、iptables/server 目录零写盘。**AN 两件本轮亦亲自重跑**：probe_bug1 毒树默认重跑 EXIT=0、`panel/data/ excluded`、落盘 admin hash 与毒库不同（新密码）、无 agent_queue.json、健康门 200；probe_bug2 ufw 预置 2000 条 EXIT=0、ufw 在、规则 2002 条、健康门 200。**过程注**：本轮前两次默认安装均 EXIT=1（`openvpn-sk5-panel did not reach steady state`），已查清是**审计侧 harness 清理失误**——m-az1 变异树安装成功后 fake systemctl 拉起的面板（nohup）未杀掉，一直占着 8443，后两次安装的面板因“Address already in use”起不来；按精确 PID 杀掉残留面板、确认 8443 空闲后重跑一次即过。与 AZ 报告的“首跑健康门 transient 失败”同族（staged 安装须串行、每跑之间杀掉残留面板）；非产品问题，不立案，但记入 §8.4 方法教训。

### §1.5 变异红证（7 棵定点变异树，每棵只回退一条修复）

| 变异树 | 回退的修复 | 探针 | 变红格子（旧行为签名） | 结论 |
|---|---|---|---|---|
| m-aw1 | `_fail_malformed_cmds` 的 sent 态 sent_at 可解析性校验 | r13_inputs／lifecycle／adv | H11（200 status=sent retries=0，恰 R13-P2-1 签名）、L7、Q3 | AW 的校验是真生效，非摆设 |
| m-aw2 | `_download_block_reason` 恒放行 | r13_download／lifecycle | W4（本地吊销 → 200）、W10（远程 `?node=` 吊销 → 200）、W10b（远程专用路径吊销 → 200）、L5（过期本地 → 200） | 三条路径共用同一 helper，变异一处四格同红，恰 R13-P2-3 全家 |
| m-ax1 | render 默认值合并回 `port or default` | r13_au | G12（port=0／False 不抛，恰 R13-P2-2 签名） | AX 的显式 None 判定真生效 |
| m-ax2 | `_as_int` 的 bool 拒绝 | 单元直测＋r13_agent | 单元：`_as_int(True)` 新树抛 ValueError“got bool”，变异树返回 `True`（bool）；端到端 N21 在变异树上**仍绿**（见注） | agent 层修复真生效（单元红证）；端到端由 core 的 AU 守卫兜底 |
| m-ay1 | handleLogin 畸形体 400 守卫 | r13_worker_inputs | W7（非 JSON → 500，见注）、W8（数组 → 401） | 恰 R13-P2-4 签名 |
| m-az1 | OVPN_SUBNET 非默认值 die | staged 安装 | `OVPN_SUBNET=10.9.0.0/24` → EXIT=0，3 条规则全 10.9、server.conf 仍 10.8 | 恰 R13-P2-6 签名 |
| m-az2 | flmx-reference.md 1-2 行回“照抄”＋SCRIPT_VERSION | grep | `SCRIPT_VERSION`／`install.sh:183-200 resolve_version` 在正文重现 | AZ 的删除真生效 |

注（m-ax2 端到端仍绿的原因，已查清）：变异树上 `_as_int(True)` 返回 `True`（bool），流进 core 的 `render_server_conf` 后被 AU 的 `type(port) is not int` 守卫拦下——`execute_command` 仍返回失败，N21 的“命令失败”断言照常通过。agent 层修复的红证在单元层（`_as_int(True)` 新树抛错／变异树返回 `True`），端到端安全由 core 纵深防御兜底。R13-P2-5 的后果（`port 1` 落盘）即使 agent 修复被回退也不再发生——双层守卫均在。

注（m-ay1 的 W7 为 500 而非 R13 原签名 401）：变异树上非 JSON 体走回旧路径，`password=""` → `recordLoginFailure` 后 `safeEqual` 对空 secret 的分支在 mock 环境抛错（mock 的 `env.ADMIN_PASSWORD` 未设时旧代码路径触达 500）。W7 的“畸形体被当作失败登录处理”（记账／非 400）这一谓词仍成立——W8 恰为 401；W7 的 500 是 mock 环境下旧路径的另一失效模式，不影响 R13-P2-4 已修的定性（新树 W7/W8 均 400 且无记账）。

新树上全部探针绿（301 格，见 §1.1–§1.4），变异树上对应格子红——AW/AX/AY/AZ 四路修复均有行为红证，非代码在场。


## §2 证据优先的行为复推导（本轮新方法）

方法：从行为探针出发反推每一项声称——先机械扫全集（同族谓词的全部出现点），再对扫出的每一点做行为探针；凡套件格先红，必先查探针本身（本轮修掉的探针问题：r14_unswept 的 U1 重复 DELETE、r14_worker_bodies 的 Y8 路径不存在——`/api/sk5/enabled` 不是路由，实为 `/api/sk5/fail-open`；探针修好重跑后才定性，不在探针 artifact 上立案）。

### §2.1 新差集（本轮已确认，汇总见 §8）

**R14-P2-1（P2）——AS/AW 的坏条目隔离只覆盖三条读路径：`nodes_revoke` 与 `node_user_ovpn` 读队列条目时不先扫队列，非对象条目直接 500（R12-P1-1 同族残留）。**

- 机制谓词：手改 `agent_queue.json` 使 `cmds` 含一个非对象条目（如 `"bad1": "not-a-dict"`）→ `DELETE /api/nodes/<name>` 500；或使 `ovpn` 含一个非对象回执（如 `"remote2:dave": "garbage-string"`）→ `GET /api/nodes/<node>/users/<user>/ovpn` 500。
- 位置：`panel/app.py:2325`（`nodes_revoke`）：`for cmd_id in [cid for cid, c in state["cmds"].items() if c.get("node") == name ...]`——`c.get` 在非 dict 的 `c` 上抛 AttributeError；`panel/app.py:2451`（`node_user_ovpn`）：`if not rec or not rec.get("ovpn")`——`rec.get` 在非 dict 的 `rec` 上抛 AttributeError。全树 8 处 `_load_queue()` 调用点中，仅 poll／cmd_get／report 三处先调 `_fail_malformed_cmds`（:2391／:2506／:2560）；其余五处（enqueue :529、下载 :1802、注册 :2297、吊销 :2321、专用下载 :2450）不扫队列——其中两处直接对条目调 `.get()`。对照：`ovpn_users_download` 的 `?node=` 分支（:1803）用 `rec.get("ovpn") if isinstance(rec, dict) else None` 守住了同一形状；`cmd_get`／report 在扫后仍有 `if not isinstance(cmd, dict)` 兜底。
- 复现：`/tmp/r14/r14_unswept.py`（run-flask.sh 进 unshare 跑）：U1——非对象 cmds 条目在位时 DELETE 节点 → **500**（`AttributeError: 'str' object has no attribute 'get'`）；U3——非对象 ovpn 回执在位时专用下载路由 → **500**；U4 对照——良构回执 → 200 内容一致。
- 影响面：U2——500 发生在 `DELETE FROM nodes`＋commit **之后**（:2315-2321 先删库行、再进队列块），故节点已从库里消失、但其 queued 命令无人标 failed：复核 `good1.status` 仍为 `queued`；重试 DELETE 只会 404（节点已不存在），操作员无法走正常路径完成清理——该命令永久滞留 queued（无任何后续路径会失败它：`_fail_malformed_cmds` 只失败坏条目、`_requeue_stale_sent` 只处理 sent 态、已删节点的 agent 永不再 poll）。通道不楔（其余命令照常流动），定 P2。下载侧的 500 无持久后果（只读路径）。
- 修复方向：两处其一——（a）`nodes_revoke` 与 `node_user_ovpn` 在读队列前先调 `_fail_malformed_cmds`（与三条读路径同款，一处改动全覆盖）；或（b）两处各加 `isinstance` 守卫（与 `?node=` 分支同款）。（a）更彻底：`_fail_malformed_cmds` 还会删掉非对象条目并记审计行。

**R14-P2-2（P2）——`render_server_conf` 的 `dns` falsy 合并绕过 `_validate_dns` 的严格守卫（R13-P2-2 同族残留，同一函数下一行）。**

- 机制谓词：`render_server_conf(dns=False)`／`(dns=0)`／`(dns="")` → 静默渲染为默认 DNS `1.1.1.1`，不抛错。
- 位置：`core/openvpn_manager.py:1088`：`dns = _validate_dns(dns or os.environ.get("OVPN_DNS") or DEFAULT_DNS)`——`or` 合并在 `_validate_dns` 之前执行；`_validate_dns`（:959-975）本身严格：`dns is not None and not isinstance(dns, str)` 即抛错，`""`／空白亦抛错。AX 修了同一函数的 port 合并（:1085-1087 `port is None` 显式判定）与 `_server_endpoint` 的 proto/port 合并（:596-613），唯独 dns 这一行未动。
- 复现：`/tmp/r14/r14_dns.py`（fakebin＋scratch PKI）：D1 `dns=False` → 正常渲染，conf 含 `push "dhcp-option DNS 1.1.1.1"`；D2 `dns=0` 同款；D3 `dns=""` 同款。对照：D4 `dns="8.8.8.8"` 渲染为 8.8.8.8；D5 `dns=None` 正常取默认；D6 `dns="  "` 抛错；`_validate_dns(False/0/"")` 直接调用均抛错。
- 影响面：无用户可达路径——面板建服务不传 dns（恒默认）、agent 在调 render 前已把 falsy dns 归一为 None（`agent.py:637`：`str(params["dns"]) if params.get("dns") else None`）。属纵深防御层缺口：core 作为最后一道防线，其 `_validate_dns` 文档宣称的“Only real strings (or None for 'use the default') are accepted”在 render 入口对 falsy 输入不成立。定 P2。
- 修复方向：`dns` 的默认值合并改 `dns is None` 显式判定（与 port 同款），或先判 `dns is not None and not isinstance(dns, str)` 再合并。

### §2.2 扫全集后确认关闭的同族点（行为证据在手，不立案）

- **Worker 其余 7 处 `readJson`**（R13-P2-4 同族）：逐点核代码＋行为抽查 `/tmp/r14/r14_worker_bodies.mjs` **9/9**——register／cmd／init-pki／sk5-save／sk5-toggle 的数组／非 JSON／标量体一律 400，绝不 500、绝不记限流；且除登录与 agent 接口外全部路由先过 `requireAdmin` 才读体，未登录者到不了读体。AY 家族已闭合。
- **`bool(` 全树扫**（R12-P2-1 同族）：`panel/app.py` 剩余 `bool(` 全部在可信内值上（快照字段、会话标志、正则匹配、`legacy` 标志）；全部外部开关输入走 `_coerce_bool`／`_strict_bool`／`_toggle_value`（:1006-1035，先判 bool／0-1 再 `bool(value)`）。已闭合。
- **`int(` 全树扫**（R13-P2-5 同族）：agent 侧唯一 `int()` 在 `_as_int` 内（:366，`isdigit` 校验后）；panel 侧 `_safe_int` 有 None 回退、audit `limit` 有 try／except、`_parse_server_conf` 的 `OPENVPN_PORT` int 转换由 status 路由捕获为 error 字段（r13_env 3/3 同款）。已闭合。
- **core 其余 `or` 合并**（R13-P2-2 同族）：`_server_endpoint` 的 `server_ip or env` 是文档化的回退链（:616，falsy 即按“未指定”走公网探测／LAN 兜底，输出恒为有效 IP，无守卫被绕过）；`expiry or ""`／错误串 `or ""` 均在无守卫的展示位。已闭合（除 §2.1 的 dns 一行）。
- **install.sh 环境变量族**（R13-P2-6 同族）：`OVPN_PROTO`（:161-164 非 udp/tcp 即 die）、`OVPN_PORT`（:166-169 非数字／0／越界即 die）、`OVPN_SUBNET`（AZ 的非默认值 die）、`OVPN_DNS`（AV 字符集校验）；`_OLD_PORT`／`_OLD_PROTO` 从已部署 conf 继承时，毒化值（`port True`／`proto bogus`）在后续同一校验块 die。已闭合。
- **cmd_get :2413 的 `fromisoformat`**：在 try／except（ValueError, TypeError）内，只跳过 `timeout_hint`，不 500；且扫队列已先把垃圾 sent_at 的 sent 命令标 failed。已闭合。
- **AW 交代的快照时效性**（吊销发生在上次 get_status 之后时，远程下载仍会下发）：与 `?node=` 分支同款属性——远程状态的唯一真源就是快照，面板无更新的来源；本地分支用 live 的 `list_users()`，恒新鲜。属架构属性，非缺陷，记为观察、不立案。

### §2.3 生命周期阶段（r14 复核：r13_lifecycle 8/8＋r14_unswept 3/6）

| 阶段 | 进入条件 | 退出条件／诚实回执 | 结果 |
|---|---|---|---|
| 全新安装 | 空 DATA_DIR | 首次启动生成随机密码、登录 200 | L1 PASS（沿用 R13，安装器未动该路径） |
| 注册节点 | panel_url＋token | 201＋token 只返回一次 | nodeparam 45/45 PASS |
| 建服务／建用户 | PKI 就绪 | 200＋conf／.ovpn 落盘 | core 19/19 PASS |
| 启用 SK5 | host/port 合法 | 开关纯写盘（沙箱无守护进程）；真机见 live-9 headline-1 | adv K1-K5 PASS |
| 运行中故障：队列损坏 | 手改队列文件 | poll 200＋坏条目 failed＋审计、整文件隔离有备份 | adv Q4-Q9 PASS |
| 运行中故障：证书过期 | index 行过期 | 列表报 expired、下载 403 | L5 PASS（AW 修后） |
| 运行中故障：节点删除 | 删节点 | 待发命令标 failed“节点已吊销”、token 失效后 poll 401 | L8 PASS——**但手改队列含非对象条目时 DELETE 500 且命令永久滞留（R14-P2-1，U1/U2）** |
| 面板重启 | 进程重起 | 队列持久化：queued 照常下发、stale sent 重投、done 不动 | L2/L3/L6 PASS |
| 面板重启 | 快照过期 | 旧快照读 stale=true＋age_s | L4 PASS |
| 运行中故障：sent_at 损坏 | 手改 sent_at | 垃圾字符串／None 的 sent 命令标 failed＋审计 | H11/L7/Q3 PASS（AW 修后） |
| 运行中故障：sent_at 损坏 | 手改 sent_at | queued 态垃圾字符串 sent_at 下发时重写、无害 | U5 PASS（AW 设计宣称行为验证通过） |
| 远程下载 | 非对象回执在位 | 404（无有效回执） | U3 FAIL → R14-P2-1 |

## §3 全量复扫（历史 134＋R13 的 7＝141 条逐条定性）

复扫宇宙：R13 的 134 条（131 已修＋2 部分＋1 未验）＋R13 本轮新发现 7 条＝**141 条**。定性口径与 R13 同款。复扫方法：先以 mtime 对账（§3.0）锁定自 R13 后动过的文件——仅 AW/AX/AY/AZ 十文件；其余文件 mtime 与 R13 §3.0 逐项一致，R13 实证沿用（同日、数小时内，复核时效内）；十文件内的历史项本轮全部行为重验（§1／§2／§4）或逐项代码核对；再叠加 §2 证据优先的行为复推导对全部阶段的重查。

### §3.0 mtime 对账（R13 §3.0 → 本轮，UTC）

自 R13 后动过的文件仅十处（AW/AX/AY/AZ）：panel/app.py（16:47:08，2645→2694 行）、cloudflare/src/index.js（16:45:26，1215→1221 行）、core/openvpn_manager.py（16:46:20，1529→1542 行）、agent/agent.py（16:46:20，910→922 行）、install.sh（16:46:54，1074→1082 行）、README.md（16:46:57）、panel/README.md（16:46:57）、docs/security.md（16:47:16）、cloudflare/server-mode.md（16:50:36）、docs/flmx-reference.md（16:47:28）。其余文件与 R13 §3.0 逐项一致（verify.sh 14:45:28、egress/sk5_manager.py 12:37:13、egress/policy-routing.sh 12:13:01、verify-integration.sh 09:35:55、panel/templates/index.html 15:21:57）。panel/data/ 仍空。

### §3.1 R13 的 7 条新发现 → 本轮全部关闭

| 项 | R14 状态 | 证据 |
|---|---|---|
| R13-P2-1 垃圾 sent_at 的 sent 态命令永久滞留 | **已修** | §1.1：inputs H11、lifecycle L7、adv Q3 全绿（标 failed＋审计行）；m-aw1 变异 H11/L7/Q3 恰红。**但同族残留另立 R14-P2-1（§2.1）**——AW 只修了三条读路径的扫队列，吊销与专用下载两条路径仍不扫；不是同一条（R13-P2-1 记的是 sent_at 可解析性，R14-P2-1 记的是未扫路径） |
| R13-P2-2 core falsy 合并绕守卫 | **已修** | §1.2：au G12 全绿（port=0／False 抛错，None 仍取默认）；m-ax1 变异 G12 恰红。**但同族残留另立 R14-P2-2（§2.1）**——AX 只修了 port 与 `_server_endpoint` 的 proto/port 合并，同一函数的 dns 合并未动；不是同一条（R13-P2-2 记的是 port 合并，R14-P2-2 记的是 dns 合并） |
| R13-P2-3 远程下载 verdict 不一致＋过期证本地下载仍 200 | **已修** | §1.1：download 12/12（W4/W10/W10b 均 403）、lifecycle L5（过期 403）全绿；m-aw2 变异 W4/W10/W10b/L5 恰红 |
| R13-P2-4 Worker 登录畸形体记限流 | **已修** | §1.3：Worker inputs W7/W8 全绿（400 且无记账）；m-ay1 变异 W7/W8 恰红。其余 7 处 readJson 本轮抽查 9/9（§2.2） |
| R13-P2-5 agent `_as_int` 把 port=True 渲染成 port 1 | **已修** | §1.2：agent 21/21（N21 转绿）；单元直测 `_as_int(True)` 新树抛错、m-ax2 变异树返回 `True`（§1.5 注：端到端由 core 守卫兜底） |
| R13-P2-6 OVPN_SUBNET 非默认值错位 NAT、exit 0 | **已修** | §1.4：本轮亲自重跑 staged 安装——10.9 子网 EXIT=1 且 die 文案在日志、零规则写盘；默认安装 EXIT=0、健康门 200；m-az1 变异 10.9 安装 EXIT=0 恰红 |
| R13-P2-7 flmx-reference.md“照抄”断言无实现 | **已修** | §6：正文 `SCRIPT_VERSION`／`resolve_version` 归零（审计报告除外）；裸 `install.sh:`／`agent.py:` 钉位归零（余下 9 处是 `panel_install.sh:`，属 FLMX 源引用口径）；m-az2 变异 grep 重现。**但同族残留另立 R14-P2-3（§6）**——cloudflare/README:135 的 `agent.py:676` 钉位已过期（实为 :687）；不是同一条（R13-P2-7 记的是 flmx-reference.md 的“照抄”断言，R14-P2-3 记的是另一文档的单钉位漂移，且漂移发生在 AZ 修后、由 AX 改动行数引起） |

### §3.2 R13 的 131 条已修 → 本轮复核

131＝R13 的 131（122＋§3.1 关闭的 R12 的 9 条）。分两组：

**（a）修复宿在十个动过文件内的项——本轮全部行为重验或逐项代码核对，无一沿用旧证：** panel/app.py（inputs 86/86＋adv 28/28＋nodeparam 45/45＋diskfull 5/5＋lockout 5/5＋download 12/12＋changepw 7/7＋lifecycle 8/8＋门禁 28/28＋r14_unswept 3/6；§2 新发现 3 条中 1 条宿在此文件，见 §2.1）；cloudflare/src/index.js（Worker inputs 23/23＋Y 矩阵 13/13＋改密 501＋r14_worker_bodies 9/9）；core/openvpn_manager.py（Core 19/19＋au 20/20＋r14_dns 3/6；§2 新发现 1 条宿在此文件）；agent/agent.py（agent 21/21＋单元直测）；install.sh（staged 默认 EXIT=0／10.9 EXIT=1 两格＋AN probe_bug1 毒树重跑 EXIT=0、`panel/data/ excluded`、落盘 admin hash 与毒库不同、无 agent_queue.json、健康门 200＋probe_bug2 ufw 2000 条 EXIT=0、规则 2002 条、健康门 200，本轮亲自重跑；门禁 28/28）；五份文档（§6 全量核对；§2 新发现 1 条宿在 cloudflare/README）。

**（b）其余项——修复宿在未动文件内，R13 实证沿用（§3.0 mtime 逐项一致，同日复核）：** egress/sk5_manager.py＋policy-routing.sh（门禁 28/28 侧面覆盖；R9 矩阵 4/4＋AG 14/14 沿用）；verify.sh（starter 门单跑 PASS，§4c）；verify-integration.sh（本轮重跑 28/28＋变异红证，§4a）。**R13 的 131 条中无一复发——已登记的谓词逐条皆绿；本轮 3 条新发现均为同族残留（谓词不同，见 §3.1 各行末尾与 §2.1），按新口径另立，不计为复发。**

### §3.3 R13 的 2 条部分 → 本轮仍部分

| 项 | R14 状态 | 证据 |
|---|---|---|
| P0-3 bundle/install-agent.sh | **仍部分** | 逻辑已修（Flask agent-bundle 格 200＋tarball 含 agent.py；verify.sh install-agent-script 200）；部署态未验（§5） |
| P1-7 改密＋首登强制改密 | **仍部分（按设计）** | 改密 API＋UI 在位（Flask 改密 7/7 本轮重跑；Worker 501 诚实端点本轮重跑）；首登强制改密从未实现、文档已诚实，不另立案 |

### §3.4 R13 的 1 条未验 → 本轮仍未验

| 项 | R14 状态 |
|---|---|
| P0-1 部署态 | **仍未验**（§5：登录卡住＋KV 占位，与 R13 同卡点） |

### §3.5 U-1～U-12 认领表更新

| # | 项 | R14 更新 |
|---|---|---|
| U-1 | P0-1/2/3 部署态 | 仍未验（§5） |
| U-2 | R6-P1-1 真机复现 | 关闭（live-8 headline-5 显式重跑通过） |
| U-3 | UDP 数据面 | 关闭（live-7 S1/S2＋live-8 S2 再证 TCP+UDP 均走 SK5） |
| U-4 | R 符号链接自拷 | 关闭（无变化） |
| U-5 | R 逐项失败 die 分支 | 仍为“机制已证、分支未触发”：live-8 三装全程跑通；live-9 未记录人为致败；live-10 简报已含人为致败格，结论待其报告 |
| U-6 | T 两变异 | 关闭（R8 已判；R9 T 变异重跑 17/2/4） |
| U-7 | verify-integration 瞬时红 | 关闭（R9/R10/R11/R12/R13/R14 六次 28/28，一次过） |
| U-8 | 真机在位升级路径 | 关闭（live-9 headline-9：毒树默认重跑真机行级比对全过） |
| U-9 | KV 竞态与 POP 传播 | 仍未验（无部署） |
| U-10 | 前端渲染级核查 | 关闭（live-9 headline-7 真机渲染通过；本轮静态核查 10/10 与之致，§7） |
| U-11 | easy-rsa 真二进制签发 | 关闭（live-8 headline-2 以 real easyrsa 3.1.0 裁决） |
| U-12 | live-R5 结果 | 关闭 |

复扫合计：141 条＝已修 138（131＋§3.1 关闭的 7 条）／部分 2（P0-3、P1-7）／未验 1（P0-1）；**本轮新发现 3 条另计（R14-P2-1～R14-P2-3，见 §2／§8 差集）**。141＝138＋2＋1；新发现 3 条见 §8 差集。

## §4 套件重跑

### §4a 门禁 verify-integration.sh：28/28（本轮在 /tmp/r14/tree 副本上实测）＋变异红证

`bash verify-integration.sh`：**PASS=28 FAIL=0 SKIP=0**。机械推导：脚本内 `ok "` 文本出现 30 处，其中 1 处是 `check()` 助手定义内永不单独触发的 `ok "$name"`（`check` 本身无调用点，死代码），另 2 处是同一格的互斥分支（/etc admin.pass 格的 elif／else 各一 `ok`，一次运行只触发其一）——30－1－2＝**28 格**，与运行时汇总一致。**变异红证**：`/tmp/r14/gate-mutant`（status() 恒抛 500）跑门禁 → **PASS=27 FAIL=1**，恰红“登录后 GET /api/status 返回 500”一格——门禁是活的，不是摆设。

### §4b Flask／Worker／Agent

- **Flask（本轮重跑）**：inputs 86/86＋adv 28/28＋nodeparam 45/45＋diskfull 5/5＋lockout 5/5＋download 12/12＋changepw 7/7＋lifecycle 8/8＋门禁 28/28＋r14_unswept 3/6（余 3 格为新发现 R14-P2-1）。O1/O10 两格观察复现，与 R12/R13 同款。
- **Worker（本轮重跑）**：inputs 23/23＋Y 矩阵 13/13＋改密 501（Y-M 格）＋r14_worker_bodies 9/9（其余 readJson 点畸形体）。部署态仍未验（§5）。
- **Agent（本轮重跑 21/21）**：`agent/agent.py` 本轮动过（AX），R8 §4f 的 13/13 不再以 mtime 沿用；本轮以 `r13_agent.py` 直测 `execute_command` 输入面 21/21＋`_as_int` 单元直测（新树抛错／变异树返回 `True`）为 fresh 证据。
- **Core（本轮重跑）**：单测 5/5（状态日志，夹具为真机捕获行）＋探针 14 格（C0–C13）＝19/19；AU 探针 20/20；r14_dns 3/6（余 3 格为新发现 R14-P2-2）。

### §4c 门禁 verify.sh：全量分段未重跑（诚实交代）＋starter 门逻辑单跑 PASS

与 R10/R11/R12/R13 §4c 同款：R9 的 vfy 分段 harness 已失，本轮未重建全量分段跑；已做：(1) `bash -n verify.sh` 过；(2) verify.sh 自 R13 后未动（mtime 14:45:28）；(3) **starter-template-consistency 门逻辑按原文逐字抽取重跑 PASS**（`/tmp/r13-tests/run-starter-gate.sh`，heredoc 按 marker 提取，tun 入站全字段与模板一致、dns.final='dns-direct'）。全量分段数（R9：22/0/1＋T 变异 17/2/4）沿用 R9，不冒充为本轮数。live-9 headline-6（verify.sh 双态真机跑：开 18/0/4、关 23/0/0）即该门禁的真机总验。

### §4d Egress 套件：test-egress.sh §6 矩阵 4/4（沿用 R9）

`egress/test-egress.sh`、`egress/sk5_manager.py`、`egress/policy-routing.sh` 三文件 mtime 与 R13 §3.0 逐项一致（未动），R9 §4d 的 §6 矩阵 4/4 与 AG policy 矩阵 14/14 沿用。本轮未重建 egress harness；sk5_manager 的保存／启停路径由门禁 28/28 与 inputs 探针 F/X/Y 格侧面覆盖。

### §4e 五套件总览

| 套件 | 规模 | 结果 |
|---|---|---|
| Flask inputs＋adv＋nodeparam＋diskfull＋lockout＋download＋changepw＋lifecycle＋r14_unswept（本轮重跑） | 86＋28＋45＋5＋5＋12＋7＋8＋6 | **86/86＋28/28＋45/45＋5/5＋5/5＋12/12＋7/7＋8/8＋3/6**（红格 3 格为新发现 R14-P2-1） |
| Worker inputs＋Y 矩阵＋改密＋r14_worker_bodies（本轮重跑） | 23＋13＋1＋9 | **23/23＋13/13＋501＋9/9** |
| Agent inputs（本轮重跑）＋`_as_int` 单元直测 | 21＋4 | **21/21＋单元红证（§1.5）** |
| Core（本轮重跑）＋AU 探针＋r14_dns | 19＋20＋6 | **19/19＋20/20＋3/6**（红格 3 格为新发现 R14-P2-2） |
| Egress（沿用 R9，代码未动） | 4＋14 | **矩阵 4/4＋policy 14/14** |
| verify-integration.sh（门禁，本轮重跑＋变异） | 28 | **28/28；变异树 27/28 恰红一格** |
| verify.sh（门禁） | 23 | **全量分段未重跑**（§4c）；starter 门逻辑单跑 PASS；live-9 headline-6 双态真机通过 |

## §5 P0-1/2/3：真实 wrangler deploy 重验——卡在登录，仍未验

- **dry-run 通过**（本轮重跑，wrangler 4.161.0 经 npx，自 `cloudflare/` 目录）：`npx wrangler deploy --dry-run` exit 0——绑定列出 `env.PANEL_KV (REPLACE_WITH_KV_NAMESPACE_ID)` 与 `env.PANEL_MODE ("cloudflare")`。dry-run 只证配置可解析，不证部署。
- **真 deploy 卡在第一步：无登录**（本轮重跑，exit 1）：`In a non-interactive environment, it's necessary to set a CLOUDFLARE_API_TOKEN environment variable for wrangler to work.`（与 R7/R8/R9/R10/R11/R12/R13 同一卡点；本机 `~/.config/.wrangler/` 下只有 logs＋metrics.json、无登录态，环境变量 `CLOUDFLARE_API_TOKEN` 未设置）。`wrangler.toml:32-33` 的 KV id 与 preview_id 仍是占位符 `REPLACE_WITH_KV_NAMESPACE_ID`／`REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`，是第二道卡点。
- **需要用户做的事（按顺序，缺一不可，与 R13 同款）**：(1) 在 Cloudflare 账号上建 API token（Workers＋KV 权限）并以 `CLOUDFLARE_API_TOKEN` 交给部署环境，或在可交互终端跑 `wrangler login`；(2) `wrangler kv namespace create PANEL_KV` 与 `--preview` 各一次，把返回的真实 id/preview_id 填进 `wrangler.toml`；(3) `wrangler secret put ADMIN_PASSWORD` 与 `wrangler secret put AGENT_BUNDLE_ORIGIN`；(4) `wrangler deploy`，再按 cloudflare/README:83 的要求换第二出口多点核（Workers 按 POP 慢速传播，单出口“没生效”不可信）。
- **结论**：P0-1/2/3（Worker 真实部署态）**仍未验**，与 R13 结论一致；Worker 代码侧的全部行为断言只在 mock KV＋本地 fetch 入口下成立，不是部署态证据。`--temporary` 未用——那会把 Worker 部署到临时抛弃账号上，不是用户的部署，测了也是冒充结论。

## §6 文档宣称全量核对

核对方法：每份文档的数字类宣称（门禁数、行数、端口、超时、重试上限、行号钉位）与行为类宣称逐条对代码/实测；数字以 `wc -l` 为准。自 R13 后动过的文档共五份（README、panel/README、security.md、server-mode.md、flmx-reference.md），其余与 R13 §6 的核对结论逐项复核（mtime 一致）＋本轮新验。

**通过的宣称**：
- 根 README:226 门禁数 28（本轮 verify-integration.sh 重跑 28/28 一致）；:198 哈希钉位 `install.sh:63-66` 与 `agent/agent.py:122-132`（本轮实测四条 sha256 逐值一致——950af37e…／20a6a9cd…／a612baa2…／3931476c…，install.sh:63-66 四行、agent.py:123/126/129/132 四行）；:137 SK5 端口待确认注（1001 默认、9000 待回报，与面板字段旁注 index.html:470-471 一致）；:243 API 列表（与 §2a 读到的路由表一致）；用户名规则 `[a-zA-Z0-9_-]{1,32}`＋保留名 `server`／`OpenVPN-CA`（与 core:99-119 一致；inputs E4/E5 行为验证 400）。
- README:66（AZ 改写后）：“子网固定 `10.8.0.0/24`，设为其他值安装器直接拒绝，否则 NAT 规则与已服务子网错位、出口断流”——与 §1.4 staged 实测一致（10.9 安装 EXIT=1＋die 文案）。
- panel/README:57–58：子网固定 `10.8.0.0/24`（`OVPN_SUBNET` 设为其他值时安装器直接拒绝）、DNS 固定 `1.1.1.1`（与 core 模板一致）；P01“已建服务改端口无 `allow_port_change=True` 即 500 拒绝”（au 探针 G8/G9 行为验证一致）；:49 udp-over-tcp 参数名 `udp_over_tcp`（与 AS 修后代码一致）。
- server-mode.md:23 多节点行已补 `body.node` 与优先级 body.node > `?node=` > `X-Node`（AT 修后，Worker Y 矩阵 J 格＋nodeparam B 格行为验证一致）；:21“命令 sent 态……（`sent_at` 缺失／不可解析时直接标 failed，不重发，R13-P2-1）”与 AW 修后代码一致（inputs H11 行为验证）。
- security.md:12“sent 态 120 秒未回执即自动打回……前提是 `sent_at` 为可解析的时间戳；`sent_at` 缺失或不可解析的 `sent` 态命令视为条目损坏，直接标 `failed` 并记审计，不再下发（R13-P2-1）”与 AW 修后代码一致。
- AQ 四处模式限定在位：docs/security.md:11、README:260、panel/README:31/:101——均写明改密“仅服务器（Flask）模式可用；Cloudflare 模式回 501，须用 `wrangler secret put ADMIN_PASSWORD`”（§1.3 行为验证一致）。
- 超时／计数类（全树 grep＋实测一致）：健康检查 60s（sk5_manager.py:957 注释“systemd timer (60s)”）、agent 轮询 5s（agent.py:70、index.js:74）、重投 120s／3 次（app.py:542-543、index.js:86）、登录限流 5 次／5 分钟／锁 15 分钟（app.py:194/196、lockout 行为验证 429＋`retry_after_s: 900`）、证书 825 天。
- AO 根治有效：全树 grep 带日期实测数字归零（审计报告与 live 报告历史记录除外——live-verify-R9.md:14 的“1404 行”是历史表格原文，非现行宣称）；flmx-reference.md 正文 `SCRIPT_VERSION`／`resolve_version` 归零（R13-P2-7 已修）；**但 cloudflare/README:135 的钉位已过期，见下述**。

**新发现的文档侧问题（立案见 §8，不另立条）**：
- **R14-P2-3（P2，文档同族复发）**——cloudflare/README.md:135：`agent 的 action_set_sk5（agent/agent.py:676）`——实测 `action_set_sk5` 的 `def` 在 **agent.py:687**，:676 落在 `action_revoke_user` 内（其 `def` 在 :675）。钉位漂移 11 行，系 AX 改动（agent.py 910→922 行）后行号后移、文档未同步。机制谓词：全树 9 份文档的代码钉位（`*.py`／`*.js`／`*.sh`:`行号` 形）机械扫全集——仅 4 处：README:198（install.sh:63-66 ✓、agent.py:122-132 ✓ 区间覆盖四行哈希）、cloudflare/README:135（agent.py:676 ✗）、flmx-reference.md 9 处（均为 `panel_install.sh:`，FLMX 源引用口径，AZ 已核对留存 ✓）。同族：R10-P2-1（数字过期）、R13-P2-7（“照抄”断言＋钉位过期）；R13-P2-7 建议的门禁（文档钉位须 grep 命中否则红）至今未建——根因未除，钉位在本轮又漂一处。
- 修复方向：把 676 改为 687（一行）；或按 AO 口径删行号、只留函数名。门禁宜补 R13-P2-7 建议的钉位 grep 格（文档中 `*.py:数字`／`*.js:数字`／`*.sh:数字` 钉位须命中对应文件内的符号，否则红）。

## §7 前端静态对比度核查

方法：跑 `panel/static/contrast-check.py`（WCAG 相对亮度；底线 4.5、目标 7）。**脚本结果：10/10 过底线 4.5（exit 0）；目标 7 达成 4/10——与 R9/R10/R11/R12/R13 逐值一致。** 结论：静态核查通过底线；6 对低于目标 7（最低为成功绿字 4.92，仅高于底线 0.42），记为观察、不立案——门禁脚本的通过线就是底线，且 R7 九维视觉审计未以对比度立案。真机渲染已由 live-9 headline-7 通过（171 可见文本、0 项低于 4.5、最薄 4.92、零 JS 报错），U-10 关闭。

## §8 裁决与未验清单

### §8.1 裁决：**不能交付，差集 3 条**

| 级别 | 条目 |
|---|---|
| P1 | 0：R13 的 7 条中无 P1；历史 P1 全部关闭（§3.1） |
| P2 | 3：R14-P2-1（坏条目隔离未覆盖吊销与专用下载两条路径，非对象条目直接 500；吊销侧半程删除致命令永久滞留）、R14-P2-2（render 的 dns falsy 合并绕过 `_validate_dns` 严格守卫）、R14-P2-3（cloudflare/README:135 的 `agent.py:676` 钉位已过期，实为 :687） |
| 高（阻塞） | 0：R13 的 7 条与 R12 的 9 条、R11 的 2 条、R10 的 1 条、R9 的 5 条、live-8 的 2 条已全部修好（§1／§3，变异红证齐全） |
| P0 | 0 未修、1 未验：P0-1/2/3 部署态仍未验（§5）；P0-3 部分（按设计，部署态未定） |

差集＝3 条（P2×3）。R13-P2-1～R13-P2-7 已全部关闭（§3.1），历史 141 条中 138 条已修（§3.5）；AW/AX/AY/AZ 的修复本身本轮全部行为验证通过（§1，变异红证齐全），套件全绿（§4e，见 §4b/§4c 的两处口径缺口）。但这不改变差集非空的结论：本轮证据优先的行为复推导新发现的三条都是“上一轮修复的覆盖面缺口”——一条坏条目隔离漏了两条路径（R12-P1-1 同族残留）、一条 falsy 合并漏了一个参数（R13-P2-2 同族残留）、一条文档钉位在修复轮次中漂移（R10-P2-1／R13-P2-7 同族复发）。三条中一条宿在 Flask、一（半）条在 core、一条在文档；旧树对照与变异树证明无一是 AW/AX/AY/AZ 回归（变异树上对应格子恰红、新树上全绿）。

**下一步（按用户常设流程）**：派修复路修 R14 的 3 条（按文件面可分两路并行：① panel/app.py——P2-1（吊销与专用下载两路先扫队列或加 isinstance 守卫），② core/openvpn_manager.py＋cloudflare/README.md——P2-2（dns 合并改显式 None 判定）＋P2-3（一行改 676→687，或删行号只留函数名；另议是否补钉位 grep 门禁格）；修法方向见 §2.1／§6），修完集成后跑 **AUDIT-R15（全量全局回头看，换推导方法独立复算）＋ live-10 对账**（live-10 与本轮并行在跑，结论待其报告落盘后对账；R14 的 3 条真机行为格由 live-11 或 R15 的 live 对账补），两路都过才交付。修复路开工前须先确认：本报告基线树版本（§0）与修复路所取树一致。

### §8.2 live-9 对账（逐项，沿用 R13）＋ live-10 状态

live-verify-R9.md（186 行，2026-11-12 23:58 CST）全部通过、零新 bug；R13 §8.2 已逐项对账（S0–S4、headline-1～9 全过；U-8、U-10 关闭；本轮树早于 AP/AQ/AR 与 AS/AT/AU/AV，R11 的 2 条与 R12 的 9 条不在 live-9 验收范围——本轮沙箱侧已全部行为重验关闭，见 §3.1）。**live-10 与本轮并行在跑**（主控 00:59 派出，简报含 S0–S4 回归＋R13 七条真机行为格＋D13 并发安装＋U-5 人为致败）：**本报告落笔时 live-10 尚未完工，结论以其报告为准，本报告不提前代判**；待其报告落盘后由主控对账（R14 的 3 条真机行为格不在 live-10 简报内——live-10 验收的是 R13 的 7 条修复，R14 的 3 条须由下一轮 live 对账补）。

### §8.3 未验清单（逐项：为什么没验、谁能验）

1. **P0-1/2/3 真实 wrangler deploy（§5）**——卡在 Cloudflare 登录（非交互环境须 `CLOUDFLARE_API_TOKEN`，`~/.config/.wrangler/` 无登录态；wrangler.toml 的 KV id 与 preview_id 仍是占位符）。谁能验：用户建 API token（或交互式 `wrangler login`）＋`wrangler kv namespace create PANEL_KV`（生产＋预览）填实 id＋`wrangler secret put ADMIN_PASSWORD`／`AGENT_BUNDLE_ORIGIN` 后，live 路跑真实 `wrangler deploy`，再从第二出口核 POP 传播。本轮不许用 mock 冒充。
2. **Cloudflare KV 竞态＋POP 传播**——依赖第 1 项的真实部署；无部署则无从测。谁能验：同第 1 项，部署后多点核。
3. **SK5 端口 1001 vs 9000**——用户从未确认哪个是 SOCKS5 口（面板默认 1001，文档已标注待确认，README:137＋index.html:470-471）。谁能验：用户回报；live 路再以确认后的端口跑 UDP/TCP 双栈。
4. **D13 PKI 段竞态**——沙箱无 easyrsa 二进制，两路并发安装／重跑时 `init_pki`＋`build-ca` 的先查后建竞态测不到（copy 段已验，见 R9 §2）；live-8 未跑并发安装（§17 为顺序三装），live-9 亦未跑，仍未验。谁能验：live-10 在真机上跑并发安装／并发重跑（简报已含）。
5. **D14 时钟跳变**——沙箱无 faketime，改系统时钟超出审计范围；仅代码级分析（锁定／会话／重投／健康全是墙钟）。谁能验：真机上以 faketime 或受控调钟复核（须用户授权调真机时钟）。
6. **Flask 35/35 未原样重跑**——AH 的 flask35.py 已随 /tmp 清理消失；本轮 Flask 面由 inputs 86＋adv 28＋nodeparam 45＋diskfull 5＋lockout 5＋download 12＋changepw 7＋lifecycle 8＋r14_unswept 6＝202 格覆盖（§4b），AW/AX/AY/AZ 改动面与新发现的 3 条缺口均逐格行为验证，但 35 格逐格对照缺失。谁能验：下一轮审计重建 flask35 或等效套件；live-9 的真机 S0–S4 覆盖同一面的行为。
7. **verify.sh 全量分段未重跑**——R10 的 vfy harness 已失，本轮只单跑了 starter 门逻辑（§4c PASS）＋`bash -n`；全量分段数沿用 R9。谁能验：live-9 headline-6（verify.sh 双态真机跑）即该门禁的真机总验。
8. **U-5 die 分支**——机制已证、分支未触发（live-8 三装全程跑通；live-9 未记录人为致败）。谁能验：live-10 人为致败安装步骤（简报已含）。
9. **R14 新发现 3 条的真机行为格**——本轮全部沙箱行为验证（§2.1）；真机后果（P2-1 的吊销半程删除在真机上的表现、P2-2 的 dns 默认渲染是否影响真机客户端、P2-3 为纯文档项）未在真机上证实。谁能验：live-11 或 R15 的 live 对账（live-10 简报验收的是 R13 的 7 条，不含本轮 3 条）。
10. **R13-P2-6 的真机断流后果**——沙箱已证规则与 server.conf 错位（exit 0）；真机上客户端流量是否真黑洞未证。谁能验：live-10 以非默认 OVPN_SUBNET 装一台真机、走一遍客户端流量（R13 §8.3 第 10 项沿用；AZ 修后该输入已 die，live-10 若仍按旧简报跑非默认安装，应先确认安装器行为已变）。

### §8.4 审计方法自述（供 R15 复核）

- 本轮方法：证据优先的行为复推导（§2，从行为探针出发反推每一项声称，每项登记结论须有本轮亲手跑出的行为证据）＋历史全量复扫（§3，141 条，mtime 对账＋十文件内逐项重验）＋新代码逐项行为验证（§1，亲自重跑、零 monkeypatch 走真实代码路径、7 棵定点变异树红证）＋套件重跑（§4，Flask 9 套探针＋Core＋双门禁重跑＋Worker Y 矩阵重建＋Agent／Egress 沿用 mtime 未动文件）＋P0 部署态重验（§5）＋文档宣称全量核对（§6，含全树钉位机械扫）＋前端静态对比度核查（§7）。
- 探针纪律：凡套件格先红，必先查探针本身（本轮修掉的探针问题：r14_unswept 的 U1 重复 DELETE、r14_worker_bodies 的 Y8 路径不存在、r13_core 的 fakebin PATH 漏传、run-install.sh 的 EXIT= 须从日志取——harness 自身 exit 恒 0；探针修好重跑后才定性，不在探针 artifact 上立案）。
- 沙箱边界：无 systemd／无 TUN／无 easy-rsa／无 openvpn 二进制／UDP sendto 临时端口 EPERM——凡涉此五项的结论均已标注分段环境或待真机（live-10／live-11），未把沙箱结论写成真机结论。fake apt 的“装 iptables-persistent 即卸 ufw”模型以 live-8 真机证据为锚（install3.log:8），fake easyrsa 的 index.txt 语义以 openssl 真签发为锚（serial 偶长大写 hex），mock KV 的 Worker 本地入口以 R8 的 18/18 同款为锚——桩的行为均有真机／真程序对照，不是凭空捏造。
- 本轮审计侧污染与收尾：探针进 `unshare -m` 绑挂（`/etc/openvpn-sk5-panel`、`/etc/sysctl.d` 绑 /tmp）；staged 安装残留面板按精确 PID 杀掉（§1.4 注：两次默认安装失败系审计侧未杀残留面板占 8443，已查清、杀净、重跑通过——staged 安装须串行、每跑之间杀掉残留面板）。收尾复核：宿主 `/etc/openvpn-sk5-panel/`、`/etc/openvpn/`（含空 `server/` 子目录）两个空挂载点目录已 rmdir 删净；`/etc/sysctl.d/99-openvpn-sk5.conf`、`/run/openvpn-sk5-panel/` 不存在；8443 空闲、无残留进程；树内 `__pycache__`（本轮 `py_compile` 与探针导入产生）已清；`core/tests/__pycache__/test_status_log.cpython-312.pyc`（2026-11-12 07:45 UTC）是早轮遗留、非本轮产生，留原样未动。
- /tmp 资产（供 R15 复用）：`/tmp/r14/tree`（现树副本）、`/tmp/r14/mutants/`（m-aw1～m-az2 七棵 R14 定点变异树）、`/tmp/r14/gate-mutant/`（status() 恒 500 的门禁变异树）、`/tmp/r14/r14_unswept.py`、`/tmp/r14/r14_dns.py`、`/tmp/r14/r14_worker_bodies.mjs`、`/tmp/r14/build-mutants.py`、`/tmp/r13-tests/`（R13 全部探针＋harness，沿用）、`/tmp/r13/mutants/`（R13 九棵变异树，沿用）。
- **本轮未重建的 R12/R13 探针（诚实记账）**：r12_inputs2（11/12）、r12_inputs3（6/6）、r12_inputs4（9/9）未原样重跑——三套件的探针文件已随 /tmp 清理消失（R13 §8.4 同款记账）；flask35 35/35 未原样重跑（§8.3 第 6 项）。AS/AT/AU/AV 与 AW/AX/AY/AZ 改动面与 R12-P1-1／P1-2／P2-1／P2-2／P2-7、R13-P2-1～P2-7 本身均已逐格行为验证（§1.1–§1.5），缺口仅在三套件与 flask35 的逐格对照。

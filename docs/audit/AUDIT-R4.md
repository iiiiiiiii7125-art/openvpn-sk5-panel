# AUDIT-R4 — 全量全局回头看（交付前）

- 审计员：独立审计路（未参与建设与修复路 A–N）
- 日期：2026-11-12（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树 39 文件 / 11592 行（与 R1/R2/R3 同等广度；新增 `core/tests/test_status_log.py` 在列）
- 推导方法：**不变量驱动**（与 R1 逐文件通读、R2 旅程推导、R3 宣称驱动均不同）——先枚举产品必须恒成立的 7 条不变量，再逐条设计证伪尝试（让不变量在最不利的条件下成立/破裂），每条给“证伪尝试 + 结果”，不只写“代码在场”。复扫 R1 33 + R2 13 + R3 16 + 真机 9+7+6 条逐条重验；M/N 两路新代码单列一节逐项验。
- 语法基线：4 个 Python 文件 `py_compile` 全绿；7 个 shell 脚本 `bash -n` 全绿；Worker `node --check` 全绿。
- 测试一律在 `/tmp` 副本与 /tmp 套件上跑；未动项目原文件；未动任何真机。审计探针在沙箱 `/etc/openvpn-sk5-panel/` 落下的 4 个文件（sk5.json/sing-box.json/log/pid）已清，目录已删。

## 一句话裁决

**不能交付。P0 0 条；P1 1 条必须先修；P2 4 条。** P1 是 M 路修 R3-BUG-1 时引入的回归：`set_sk5(enabled=False)` / `disable()` / `check_health` 的 fail-over 现在硬依赖 sing-box 立即重起成功——一个纯配置保存（甚至已是禁用态的无操作保存）会因守护进程起不来而报 500；更糟的是 fail-over 本身会在最需要它的退化条件下抛异常、连 `health.json` 都不写。R3 的 16 条与 R1/R2 的全部残留均已修完，但这一条新回归 + 4 条 P2 不清，差集不为 ∅。修完后仍须按第一前提①再做一次全量全局回头看（AUDIT-R5）才能交付；真机第四轮（live-R4）正在并行跑，凡依赖真机数据的结论本文一律写“待 live-R4”，不提前判通过。

## 不变量清单与证伪结果

### 不变量① sing-box 常驻（disable/fail-over/重装后仍在跑，direct 模式 tun1 在位）

- 证伪尝试 A（沙箱，真实 sing-box 1.11.15 二进制）：`set_sk5(host, port, enabled=False)` —— 期望 200。实测 **500**：`sing-box exited immediately (rc=1)`，日志 `configure tun interface: operation not permitted`（沙箱禁 TUN）。调用链：`set_sk5:588 → disable() → _start_singbox()`。M 路之前 `disable()` 只停进程，同一调用在 R3 是 200。
- 证伪尝试 B（无操作保存）：已是禁用态的存量配置上再调 `set_sk5(enabled=False)` —— 期望纯写盘 200。实测 **同样 500**：`set_sk5` 不判断模式是否变化，无条件走 `disable()` → 重起。见 R4-P1-1。
- 证伪尝试 C（fail-over 路径，桩 sing-box：`check` 过、`run` 必死）：存量 `enabled=True, fail_open=True`、sing-box 已死时调 `check_health()` —— 期望返回 `{healthy: False, action: failed_over_to_direct}` 且 `health.json` 落盘。实测 **`check_health()` 直接抛 `RuntimeError`**，`health.json` 不存在；但 `_remove_policy()` 已执行且存量 `enabled` 已写 False——fail-over 在流量面“半发生”，在报告面“全丢失”。见 R4-P1-1。
- 结论：**不变量在“守护进程起不来”的条件下破裂**。真机上 TUN 可用时 disable 能成功（待 live-R4 实证），但不变量本身没有容错：它把“配置保存”与“守护进程立即重起”绑死，且 fail-over 无 try 兜底。

### 不变量② 入口端口创建后永不变（除显式 allow_port_change）

- 证伪尝试：core 套件 29/29 全过（含占用端口建服务拒、已建改口无 allow 拒 500/有 allow 通 200 且 server.conf 变 tcp/443、改回 200）。install.sh 继承块实测：伪造已部署 `server.conf`（tcp/443）抽取 :34–100 行原样跑，exit 0，继承 tcp/443；显式 `OVPN_PROTO=udp OVPN_PORT=1194` 时环境变量胜出。
- 结论：成立。R3-BUG-6（log 未定义 exit 127）代码面已修；默认重跑的真机态待 live-R4。

### 不变量③ fail-closed 处处（下载哈希、TOFU、sha256、kill-switch、.sha256 缺失即停）

- 证伪尝试：四钉死哈希 install.sh 与 agent.py 逐字节一致（`950af37e…d9c5` 等，agent.py 用括号续行，值相同）；版本 1.11.15/2.7.0 两处一致；真实 sing-box 1.11.15（`/tmp/audit3-tests/bin/sing-box`，自报版本）对渲染配置 `check` 通过。`install-agent.sh` 全树 grep：全部面板拉取走 `curl_panel`（`--cacert` 钉死证书或 `-k` 显式）或自检分支的 `curl $CURL_TLS`；无裸 curl 拉面板。Worker `installCommand` 与前端 `buildInstallCommand` 均含 `sha256sum -c` 且缺失即停（J/K/L 后）。
- 例外登记（非新发现，R3 观察的延续）：`install-agent.sh:274-289` 自检分支——旧面板不提供 `/install-agent.sh.sha256` 时只警告后继续；注释明文记载为旧面板兼容设计，bundle 本身仍 sha256 fail-closed，与 J 修掉的 Worker 生成命令 warn 分支是两回事，不立案。
- 结论：成立（R4-P1-1 的 fail-over 抛异常是“报告面丢失”而非“静默放行”——流量面仍黑洞/已撤表，不构成 fail-open；但它破坏了“失败须诚实呈现”，见 P1）。

### 不变量④ Flask 与 Worker 两端行为一致（重投上限、轮换码、poll 校验、安装命令）

- 证伪尝试：Worker 重投反证套件（R3 原案，5 个超时周期）：周期 1–3 重下发，周期 4 标 `failed` 不再下发，周期 5 仍 `failed`——K 路补的 `SENT_MAX_RETRIES = 3` 生效，R3-P1-1 已修。K 路自写套件 22/22 本轮重跑全过。Worker 套件 48/50：仅有的 2 个“失败”是旧套件把旧行为写成了期望（轮换 201、poll 错节点名 200），当前实测轮换 200、错节点名 401——与 Flask 一致，正是 K 的修复点，不是回归。安装命令：前端提取测试验到 token 含 `;` 时被引号包裹（`--token 'x;id'`）、panelUrl 与 nodeName 均加引号，两步走 `-k + sha256sum -c` 在位；旧前端套件 4/7 的 3 个“失败”全是过期期望被新行为推翻（它断言 token 不加引号、panelUrl 裸插值、无 -k 校验），不是产品问题。
- 结论：成立。R3-P1-1、R3-P2-11、R3-P2-12、R3-P2-13 均已修。

### 不变量⑤ 密钥/凭据永不进日志、回执、.ovpn 以外的地方

- 证伪尝试：Flask 探针（种子 admin 行、登录 200 后 `POST /api/sk5` 带 marker 密码）：`GET /api/sk5` 不含 marker；`panel.db` 全表扫描无 marker；`agent_queue.json` 不存在（本次无入队命令）、无 marker。verify-integration 20/20 含“回执无私钥材料泄露”“回执 JSON 里无节点 token”两格。树内无 `secret.key`、无 `__pycache__` 残留；`.gitignore` 钉 `panel/data/`。
- 诚实说明：本次探针的保存调用因 R4-P1-1 报 500，但 `_save_config` 在 `disable()` 之前已执行——marker 已按 0600 写入 `/etc/openvpn-sk5-panel/sk5.json`（预期存储位置，探针后已清）。“500 但凭据已存盘”是 R4-P1-1 的另一面：操作员以为保存失败，实际已保存。
- 结论：成立。

### 不变量⑥ 门禁自身可证伪（每个门禁格做一次变异红证）

- 证伪尝试：verify-integration.sh 基线 20/20；`status()` 改恒 500 后 **19/1，变红的正是“登录后 GET /api/status”格**。verify.sh 沙箱基线 PASS=5 FAIL=5 SKIP=11（5 个 FAIL 全是沙箱缺二进制/面板未起的环境缺口，诚实）；删 `systemd/openvpn-sk5-healthcheck.timer` 后 **PASS=4 FAIL=6，files 格变红**。
- 结论：两门禁都活着。但 R4-P1-1 漏过了两门禁（见 R4-P2-4）：verify-integration 从不 POST `/api/sk5`，verify.sh 沙箱态下 sk5 格全 SKIP。

### 不变量⑦ 文档宣称与代码一致（逐条核关键句）

- 证伪尝试（grep 全量）：根 README 两步命令在位、旧一键命令零命中；`agent/README.md` 同款；server-mode.md:17 与 flmx-reference 1-10 均写“仅 Worker 有 /install 接口”；README:242 fail-open/udp-over-tcp 已实现、:258/261 bcrypt 已落地；README:72 复制清单含 `agent/`；flmx-reference 1-13/§103 按 J 后强制校验改写、“版本解析”已限定为 FLMX 步骤；panel/README:59 allow_port_change、:81/89 timer 60 秒 + `last_health` 回显；egress/README:134 fail-over 单向性；cloudflare/README:199 `.sha256` 必须取到且校验通过、全文零 `http://`；security.md 重投行“两端上限均为 3”。
- 结论：**基本成立，1 处漏网**：README:72 的安装步骤 4 复制清单仍漏 `systemd/`（M 路 :355 已拷，文档未跟上）——见 R4-P2-2。

## 新发现

### R4-P1-1 — M 路的 disable-重起让“保存 SK5（禁用态）”与“fail-over”硬依赖守护进程立即重起成功；无操作保存也失败，fail-over 抛异常不写 health.json

- 严重度：P1（必须修）
- 文件：`egress/sk5_manager.py:544-589`（`set_sk5`）、`:705-735`（`disable`）、`:767-804`（`check_health`）、`:268-295`（`_start_singbox`）
- 机制族：sing-box 常驻（R3-BUG-1 的修复引入的回归）
- 复现（三路独立实证，同一根因）：
  1. Flask 套件 60/62（R3 是 62/62）：`sk5 save with pw 200` 与 `single-field enabled=false with stored cfg -> 200` 均 500，`sing-box exited immediately (rc=1); see .../sing-box.log`，日志 `configure tun interface: operation not permitted`（沙箱禁 TUN）。调用链 `set_sk5:588 → disable() → _start_singbox()`。
  2. agent 套件 17/19（R3 是 19/19）：`agent set_sk5 full ok` 与 `agent set_sk5 single-field keeps host/port` 同错。
  3. egress 套件无法启动：在 setup 第 28 行 `set_sk5(..., enabled=False)` 即抛，整套件 0 项跑完（R3 是 20/20）。
  4. 专项探针（`/tmp/audit4-tests/failover_probe.py`，桩 sing-box：`check` 过、`run` 必死）：① 已是禁用态的存量配置上 `set_sk5(enabled=False)`——**无操作保存也抛**；② `enabled=True, fail_open=True`、sing-box 已死时 `check_health()`——**直接抛 `RuntimeError`，不返回 `failed_over_to_direct`，`health.json` 不存在**；但 `_remove_policy()` 与 `enabled=False` 写盘已在抛错前执行——fail-over 在流量面半发生、在报告面全丢失。
- 根因：`set_sk5` 不判断模式是否变化——`enabled=False` 就无条件调 `disable()`；`disable()` 把 `_start_singbox()` 放在 `_save_config(enabled=False)` 之后且无兜底；`check_health` 的 fail-open 分支（:798）调 `disable()` 无 try 包裹。M 路之前 `disable()` 只停进程，保存是纯写盘；M 路修 R3-BUG-1 时把“重起”塞进同一函数，未区分“保存配置”与“应用模式”。
- 影响：① 任何 sing-box 起不来的环境（沙箱、TUN 不可用、升级后二进制损坏、配置渲染异常）下，面板上“填 SK5 密码、点保存（禁用）”恒 500——填凭据的第一步就断；且配置其实已写盘，500 是误报。② fail-open 的安全路径在最需要它的退化条件下抛异常：timer 拿不到 `failed_over_to_direct`，`health.json` 停留在旧值，面板永远不知道 fail-over 发生过（R1 P1-8 的“开关承诺的行为”以另一种方式落空）。③ 真机上 TUN 可用时 disable 能成功（待 live-R4 实证），但不变量本身无容错。
- 修法建议：`set_sk5` 只在模式真正变化时才调 `enable()/disable()`（已是禁用态的保存只写盘不重起；已启用态的字段变更才重渲染+重起）；`disable()` 里重起失败时仍须诚实返回（已撤表+已写盘的状态要说清楚，不许抛掉）；`check_health` 的 fail-open 分支包 try——`disable()` 抛错也须落一条 `failed_over_to_direct`（附重起失败 detail）进 `health.json`，不许让 timer 空手而归。修完重跑 Flask/agent/egress 三套件须回 62/62、19/19、20/20。
- 关联：R1 P1-8（check_health 死开关）的 fail-over 行为因此项部分回退——开关本身在，报告链断了。

### R4-P2-1 — `policy_routing_active` 只看规则存在，table 100 为空时面板仍显示“已生效”

- 严重度：P2
- 文件：`egress/sk5_manager.py:670-677`（`policy_active = VPN_NET in ip rule show and "lookup 100" in ...`）；`panel/templates/index.html:684-685`（`已生效 / 未生效`）
- 机制族：状态旗标诚实性
- 实证：live-verify-R3 §3 S0 实测——SK5 未启用、table 100 为空（仅 `ip rule 100` 在位），面板 `policy_routing_active=true`。旗标只反映规则存在，不反映有效路由；SK5 关闭时根本没有流量在走策略路由，“已生效”是误报。
- 修法建议：旗标改为 `enabled AND 规则在位 AND table 100 有经 tun1 的默认路由`；SK5 关闭时恒 false。或至少在 SK5 关闭时显示“未启用”而非“已生效”。

### R4-P2-2 — 根 README:72 安装步骤 4 的复制清单仍漏 `systemd/`

- 严重度：P2
- 文件：`README.md:72`（“复制 `core/`、`egress/`、`panel/`、`agent/`、`verify-integration.sh`”）；对照 `install.sh:355`（已拷 `systemd/`，M 路补的）
- 机制族：文档过时（R3-P2-4 同族再犯：L 路补清单时只补了 `agent/`，M 路补拷 `systemd/` 后文档又没跟上）
- 修法建议：清单补 `systemd/`（与 install.sh:355 一致）。

### R4-P2-3 — IPv4 探测的形状校验接受超范围段（`999.999.999.999` 能通过）

- 严重度：P2
- 文件：`install.sh:446-452`（`curl -4` 两次 + 正则 `^[0-9]{1,3}(\.[0-9]{1,3}){3}$`）
- 机制族：默认 remote 可达性（R3-BUG-5 同族）
- 实证：正则只验“点分四段、每段 1–3 位数字”，不验每段 ≤255；`999.999.999.999` 能通过并写进 panel.env 的 `OPENVPN_SERVER_IP`，默认 .ovpn remote 即不可达且无警告。`-4` 与形状校验本身已到位（M 路），只差范围校验。
- 修法建议：正则后加逐段 ≤255 校验（或 `ipcalc`/`python3 -c ipaddress` 验），不通过即按“未探测到”处理（留空走面板运行时探测）。

### R4-P2-4 — 两门禁对 SK5 保存→守护进程重起的耦合零覆盖，R4-P1-1 从两门禁眼皮下漏过

- 严重度：P2
- 文件：`verify-integration.sh`（全文无 `POST /api/sk5`；只在登录态 status 里读 sk5 只读状态）；`verify.sh`（沙箱态下 sk5-toggle/egress 格全 SKIP）
- 机制族：门禁覆盖（R2-P1-4 同族）
- 实证：R4-P1-1 让 Flask/agent/egress 三套件同时变红，verify-integration 仍 20/20 全绿——它从不调保存路径。门禁对“保存即应用”这一耦合失明。
- 修法建议：verify-integration 加一格——用桩 sing-box（`run` 立即退出 0，不建 TUN）跑 `POST /api/sk5 {enabled:false}` 期望 200；或断言“已是禁用态的保存不触发守护进程重起”（按 R4-P1-1 的修法二选一入 gate）。

## M/N 两路新代码逐项验

| 项 | 位置 | 结论 |
|---|---|---|
| M-1 log() 定义前移 | `install.sh:39` 定义，继承块 :71–81 调用 | ✓ 已修。抽取 :34–100 行原样跑（伪造已部署 server.conf tcp/443）：exit 0，继承 tcp/443；显式 `OVPN_PROTO=udp OVPN_PORT=1194` 时环境变量胜出。R3-BUG-6 代码面闭合；默认重跑的真机态待 live-R4 |
| M-2 探测加 -4 + IPv4 形状校验 | `install.sh:446-452`（`curl -4` 两次，失败留空；正则拒 IPv6/垃圾） | ✓ 已修（形状校验只差范围，见 R4-P2-3）。R3-BUG-5 代码面闭合；默认 remote 的真机态待 live-R4 |
| M-3 装树补 systemd/ | `install.sh:355`（`cp -a ... "$SCRIPT_DIR/systemd" ...`） | ✓ 已修。R3-BUG-3 代码面闭合；文档清单漏登记见 R4-P2-2；从 /opt 重跑的真机态待 live-R4 |
| M-4 disable 改渲染 direct 配置后重起 | `egress/sk5_manager.py:198`（`_render_direct_config`）、`:705-735`（`disable`：先渲染再停、再存盘、再重起） | ◐ 部分。R3-BUG-1 的“重起”本身实现了，但实现方式引入 R4-P1-1（保存即重起、无模式变化判断、fail-over 无兜底）。真机 disable 序列的复验待 live-R4 |
| N-1 bundle 列表存变量再 grep | `verify.sh:365-378`（`_BUNDLE_LIST="$(tar -tzf ...)"` 后 grep 变量） | ✓ 已修。R3-BUG-2 的 SIGPIPE 141 根因已除（tar 不再直连 grep -q；printf 的输出仅 15 行左右，远小于管道缓冲，不会触发 SIGPIPE）。沙箱态下 panel 未起，该格未实际跑通，全绿待 live-R4 |
| N-2 三处 route-get 源改 10.8.0.1 | `verify.sh:587,714`、`egress/test-egress.sh:55,124`；全树 route-get 再无 10.8.0.2（仅 test-egress.sh:11 注释警告勿用） | ✓ 已修。R3-BUG-4 代码面闭合；链路正常时变红的门禁误报消除，待 live-R4 |

## 实证总览（本轮自写/复用套件，全部独立重跑）

| 套件 | 位置 | 结果 |
|---|---|---|
| Flask 面板 | `/tmp/audit3-tests/flask_suite.py`（树已刷新为当前版） | **60/62**，2 失败全是 R4-P1-1（R3：62/62） |
| Worker（mock KV + mock 源站） | `/tmp/audit3-tests/worker_suite.mjs` | 48/50；2 个“失败”是旧期望（轮换 201、poll 错名 200），实测 200/401 即 K 的修复点 |
| Worker 重投上限（反证） | `/tmp/audit3-tests/worker_requeue.mjs` | 周期 4 标 failed 不再下发——R3-P1-1 已修 |
| Worker K 套件 | `/tmp/fixk-test/test.mjs` | 22/22 |
| Worker 1-25 守卫 | `/tmp/audit3-tests/worker_125.mjs` | 3/3 |
| core（解析器/证书/端口锁/easyrsa） | `/tmp/audit3-tests/core_suite.py` | 29/29 |
| agent（白名单/钉死哈希/set_sk5/--once） | `/tmp/audit3-tests/agent_suite.py` | **17/19**，2 失败全是 R4-P1-1（R3：19/19） |
| egress（set_sk5/健康检查/真实 sing-box check） | `/tmp/audit3-tests/egress_suite.py` | **setup 即崩**：第 28 行 `set_sk5(enabled=False)` 抛错，0 项跑完（R3：20/20）——R4-P1-1 |
| 前端安装命令生成器 | `/tmp/audit3-tests/frontend_cmd.mjs` | 4/7；3 个“失败”全是过期期望被 L 的修复推翻（token/panelUrl 已加引号、两步走 -k+sha256 在位） |
| policy-routing | `/tmp/audit3-tests/policy_test.sh` | exit 0，各腿行为正常（命名空间挂载噪声与 R3 相同） |
| fail-over 专项探针 | `/tmp/audit4-tests/failover_probe.py`（桩 sing-box） | `check_health` 抛错不写 health.json；无操作保存抛错——R4-P1-1 实证 |
| install.sh 继承块抽取 | `/tmp/audit4-tests/inherit_block.sh`（:34–100 原样） | exit 0，继承 tcp/443，显式 env 胜出 |
| 脱敏探针 | `/tmp/audit4-tests/redact_probe3.py` | GET/DB/队列均无 marker 泄露（保存 500 但凭据已按 0600 写盘，见不变量⑤） |
| verify-integration.sh 基线 | `bash verify-integration.sh`（/tmp/audit4） | 20/20 |
| verify-integration.sh 变异（status 恒 500） | `/tmp/audit4-mut` | 19/1，变红的正是登录态 status 格 |
| verify.sh 基线（沙箱） | `bash verify.sh`（/tmp/audit4） | PASS=5 FAIL=5 SKIP=11（FAIL 全为沙箱缺二进制/面板未起） |
| verify.sh 变异（删 healthcheck.timer） | `/tmp/audit4-mutv` | PASS=4 FAIL=6，files 格变红 |

## 全集复扫表 A — AUDIT-R1 的 33 条（逐条复验）

| ID | 结论 | 证据 |
|---|---|---|
| P0-1 202 当成功 | ✓ 已修 | S：apiWait 轮询至 done/failed；Worker 48/50（2 差为旧期望） |
| P0-2 单字段 set_sk5 必败 | ✓ 已修 | S：部分合并三端一致；agent 17/19 的 2 失败是重起耦合，非合并语义 |
| P0-3 Worker 无 bundle/安装脚本路由 | ✓ 已修 | S：无源站 503；有源站 200；篡改包 502（R3 实证，本轮代码未动） |
| P0-4 SK5 密码保存清空 | ✓ 已修 | S：空密码保留、clear_password 清除（Flask 60/62 中这两格 PASS） |
| P0-5 secret.key 随树发货 | ✓ 已修 | C：树内无 secret.key；发货哈希常量命中即轮换；/etc 密钥 0600 |
| P1-1 status 耗时 20 秒 | ✓ 已修 | C：复用已探 egress_ip，不再双探针（R3 实证，代码未动） |
| P1-2 无节点/agent 界面 | ✓ 已修 | S：verify-integration 20/20 含节点全链 |
| P1-3 Worker 登录无限流 | ✓ 已修 | S：Worker 套件 6 次错密码 → 429（48/50 内） |
| P1-4 Worker 无吊销/轮换 | ✓ 已修 | S：rotate 200 新 token 生效、旧 token 401 |
| P1-5 Worker 快照形状错位 | ✓ 已修 | S：快照归一化（48/50 内） |
| P1-6 sent 态无重投 | ✓ 已修 | S：**本轮闭合**——Worker 重投反证周期 4 标 failed（K 路）；Flask 同款 3 次后 failed。R3 的“部分”已清 |
| P1-7 无改密接口 | ✓ 已修 | S：API 全套 + 前端入口在位（Flask 60/62 内） |
| P1-8 check_health 死开关 | ◐ 部分回退 | timer+service 在位；但 fail-open 分支遇 sing-box 起不来时抛错不写 health.json → R4-P1-1。开关本身在，报告链断了 |
| P1-9 策略路由无持久化/重跑覆盖 SK5 | ✓ 已修 | S：policy 测试 exit 0；install.sh 读存量判模式（R3 实证，代码未动） |
| P1-10 create_server 不幂等 | ✓ 已修 | S：core 29/29 |
| P1-11 入口端口无占用检查 | ✓ 已修 | S：core 29/29 |
| P1-12 UoT 探针密码写 /tmp 明文 | ✓ 已修 | C：mkdtemp 0700 + 配置 0600（代码未动） |
| P1-13 systemctl 无超时/保护 | ✓ 已修 | S：core 29/29（PATH 剥离时不抛） |
| P1-14 server-mode.md 过时 | ✓ 已修 | D：**本轮闭合**——:17 已写“仅 Worker 有 /install 接口”（L 路）；http 全改 https |
| P1-15 Worker set_sk5 假宣称 | ✓ 已修 | S：三端语义一致；头注释已改“纵深防御”（K 路） |
| P2-1 限流进程内内存/无 ProxyFix | ✓ 已修 | C：SQLite + OVPN_TRUSTED_PROXY（代码未动） |
| P2-2 agent 不校验 sing-box 版本 | ✓ 已修 | C：钉 SINGBOX_VERSION=1.11.15，不符即重装（代码未动） |
| P2-3 --once 失败仍返回 0 | ✓ 已修 | S：agent 17/19 内 --once 退出 1 格 PASS |
| P2-4 bundle 确定性不完全 | ✓ 已修 | S：两次打包字节相同（R3 实证，代码未动） |
| P2-5 密码哈希 SHA-256 非 bcrypt | ✓ 已修 | S：bcrypt `$2b$` + 透明迁移；README 措辞已改（L 路） |
| P2-6 OVPN_DNS 被忽略 | ✓ 已修 | C：三处接线一致（代码未动） |
| P2-7 PANEL_ADMIN_PASSWORD_FILE 无人读 | ✓ 已修 | C：死变量已删（代码未动） |
| P2-8 健康门禁把密码放 curl -d argv | ✓ 已修 | C：0600 文件 + `--data @file`（代码未动） |
| P2-9 init_pki force 无二次确认 | ✓ 已修 | C：force 须并传 confirm=true（代码未动） |
| P2-10 .ovpn 下载不校验用户状态 | ✓ 已修 | C：吊销 403、未知 404（代码未动） |
| P2-11 UoT 固定 /tmp 路径 + manifest 无条目即 raise | ✓ 已修 | C：mkdtemp + 轮询三 manifest（代码未动） |
| P2-12 两处文档过时 | ✓ 已修 | D：security.md 与 README 均已同步（K/L 路） |
| P2-13 flmx-reference 多项未落地/过时 | ✓ 已修 | D：**本轮闭合**——1-13/§103 按 J 后强制校验改写、“版本解析”已限定、1-10 已限定面板（L 路） |

## 全集复扫表 B — AUDIT-R2 的 13 条（逐条复验）

| ID | 结论 | 证据 |
|---|---|---|
| R2-P1-1 BUG-9 未真修 | ✓ 已修 | S：core 29/29 四路行形全过；live-R3 第四次复验逐字段一致（UDP+TCP） |
| R2-P1-2 改密无 UI | ✓ 已修 | S：API + 前端入口在位 |
| R2-P1-3 旧 CN 证书三路全堵 | ✓ 已修 | S：core 29/29（序列号识别、legacy 标志、last-wins） |
| R2-P1-4 verify-integration 不验登录态 status | ✓ 已修 | S：变异 19/1 红在登录态 status 格（本轮重做） |
| R2-P1-5 verify.sh files 漏列单元 | ✓ 已修 | S：变异删 timer 后 files 格 FAIL（本轮重做，PASS 5→4） |
| R2-P2-1 /etc 隔离存在性判定 | ✓ 已修 | S：verify-integration 20/20 快照比对格 |
| R2-P2-2 OVPN_PANEL_DATA_DIR 无人认 | ✓ 已修 | S：全部套件以该变量钉 /tmp，树内 panel/data 为空；`.gitignore` 在位 |
| R2-P2-3 README 哈希措辞矛盾 | ✓ 已修 | D：README 已写钉死四哈希 + 优先级；“不写死”旧句零命中 |
| R2-P2-4 server-mode http:// | ✓ 已修 | D：全 https |
| R2-P2-5 flmx-reference 1-13/§103 过时 | ✓ 已修 | D：**本轮闭合**（L 路，见不变量⑦） |
| R2-P2-6 verify.sh sing-box-config 误导 | ✓ 已修 | C：三路报文已区分（代码未动） |
| R2-P2-7 fail-open 单向性未写明 | ✓ 已修 | D：**本轮闭合**——egress/README:134 已写单向性（L 路）；根 README 同款 |
| R2-P2-8 starter heredoc 双份维护 | ✓ 已修 | S：verify.sh `starter-template-consistency` PASS（沙箱基线内） |

## 全集复扫表 C — AUDIT-R3 的 16 条（逐条复验）

| ID | 结论 | 证据 |
|---|---|---|
| R3-P1-1 Worker sent 重投无上限 | ✓ 已修 | S：重投反证周期 4 标 failed；fixk 22/22；security.md 口径已改 |
| R3-P1-2 文档旧一键命令 | ✓ 已修 | D：两处均已是两步走（-k + sha256sum -c + --node-name 必带）；旧命令零命中 |
| R3-P2-1 server-mode 称 Flask 有 /install | ✓ 已修 | D：两处均改“仅 Worker 有”（L 路） |
| R3-P2-2 README 称 fail-open 路由不存在 | ✓ 已修 | D：README:242 已改“均已实现”；Flask 套件两路由 200 |
| R3-P2-3 README 称哈希 SHA-256 待对齐 | ✓ 已修 | D：README:258/261 已改 bcrypt 已落地 |
| R3-P2-4 README 复制清单漏 agent/ | ✓ 已修 | D：README:72 已含 agent/（但漏 systemd/ → 新立案 R4-P2-2） |
| R3-P2-5 cloudflare/README warn 后继续 | ✓ 已修 | D：已改“.sha256 必须取到且校验通过才执行” |
| R3-P2-6 cloudflare/README 轮询 http:// | ✓ 已修 | D：全文零 `http://` |
| R3-P2-7 flmx-reference 1-13/§103 过时 | ✓ 已修 | D：按 J 后强制校验改写；“版本解析”已限定 |
| R3-P2-8 panel/README 只认 proto/port | ✓ 已修 | D：已补 allow_port_change + P01 口径 |
| R3-P2-9 panel/README 称未轮询 | ✓ 已修 | D：已改 timer 60 秒 + last_health 回显 |
| R3-P2-10 Worker 头注释过时 | ✓ 已修 | D：已改“agent 已是部分合并；Worker 仍发全量是纵深防御” |
| R3-P2-11 轮换 201 对 200 | ✓ 已修 | S：轮换实测 200 |
| R3-P2-12 Worker poll 忽略 node_name | ✓ 已修 | S：错名 401、正确名 200、无字段旧 agent 放行（fixk 22/22 内） |
| R3-P2-13 安装命令 token 未加引号 | ✓ 已修 | S：两份生成器三处统一 shellQuote；token 含 `;` 被引号包裹 |
| R3-P2-14 egress/README 未写 fail-open 单向性 | ✓ 已修 | D：egress/README:134 已补 |

## 全集复扫表 D — 真机 bug（live 9 + live-R2 7 + live-R3 6）

沙箱不能跑 openvpn/sing-box 守护进程与 UDP 数据面；“代码面”指本轮沙箱实证，“真机”指 live-R3 的既有实证。

| ID | 结论 | 证据 |
|---|---|---|
| BUG-1 模板 inet4_address | ✓ 已修 | S：真实 sing-box 1.11.15 check 通过 |
| BUG-2 无上游 sha256 清单 | ✓ 已修 | S：四哈希两处逐字节一致；真实下载验哈希一致（R3 实证） |
| BUG-3 安装报成功而 sing-box crash-loop | ✓ 已修（代码+门禁面） | C+S：steady 三重门在位；守护进程真机行为以 live-R2/R3 为准 |
| BUG-4 用户列表含 CA | ✓ 已修 | S：core 29/29 |
| BUG-5 agent 无法轮询自签面板 | ✓ 已修 | S：install-agent e2e 两分支（R3 实证）；TOFU grep 全过 |
| BUG-6 重装不重启旧 agent | ✓ 已修 | C：reset-failed + restart + is-active 在位；真机行为 live-R2 已验 |
| BUG-7 全部用户 CN=OpenVPN-CA | ✓ 已修 | S：core 29/29（stub easyrsa 每命令 CN 正确） |
| BUG-8 无 FORWARD accept 规则 | ✓ 已修 | S：policy 测试 exit 0；install.sh 两条在位 |
| BUG-9 online_users 恒 0 | ✓ 已修 | S：core 四路；live-R3 第四次复验逐字段一致 |
| R2-BUG-10 新装 /opt 树缺 agent/ | ✓ 已修 | S：verify.sh install-copies-agent PASS；install-agent e2e（R3） |
| R2-BUG-11 先取包后钉证书 | ✓ 已修 | S：e2e 两分支（R3）；TOFU grep 全过 |
| R2-BUG-12 安装命令缺 --node-name | ✓ 已修 | S：前端/Worker 提取测试 + e2e config 含 node_name |
| R2-BUG-13 部署日志逗号 v2 被丢弃 | ✓ 已修 | S：core 29/29 verbatim 部署行 |
| R2-BUG-14 allow_port_change 丢失 | ✓ 已修 | S：Flask 60/62 内（不带 500/带 200） |
| R2-BUG-15 健康门禁按 ens5 断言 SK5 模式 | ✓ 已修 | C：门禁 mode-aware（R3 实证）；真机重验待 live-R4 |
| R2-BUG-16 重装不继承 proto/port | ✓ 已修（代码面） | S：继承块抽取实测 exit 0 + tcp/443；默认重跑真机态待 live-R4 |
| R3-BUG-1 disable 停 sing-box 永不恢复 | ◐ 部分（修出回归） | M 路的重起实现了，但引入 R4-P1-1；disable 序列真机复验待 live-R4 |
| R3-BUG-2 verify.sh agent-bundle SIGPIPE 141 | ✓ 已修（代码面） | C：列表存变量再 grep；沙箱态 panel 未起未实际跑通，待 live-R4 |
| R3-BUG-3 装树漏 systemd/ | ✓ 已修（代码面） | C：install.sh:355 已拷；从 /opt 重跑真机态待 live-R4 |
| R3-BUG-4 路由核对用非本地源 10.8.0.2 | ✓ 已修（代码面） | C：三处均改 10.8.0.1；待 live-R4 |
| R3-BUG-5 默认 .ovpn remote 是 IPv6 | ✓ 已修（代码面） | C：-4 + 形状校验在位（只差范围，R4-P2-3）；默认 remote 真机态待 live-R4 |
| R3-BUG-6 默认重跑 exit 127 | ✓ 已修（代码面） | S：继承块抽取实测 exit 0；默认重跑真机态待 live-R4 |
| R3-OBS-1 已登录会话偶发瞬时 401 自愈 | 观察（未立案） | 代码面无机制：单面板进程、secret.key 恒定、session_version 恒 1、会话 12h；`login_required` 第一分支（session 无 admin）先拒后认，密钥恒定下签名验证应是确定性的，无法在代码面复现。live-R4 须盯是否再现并对 access log 计时关联 |

复扫差集：R1 33 条全修（P1-6、P1-14、P2-13 三处“部分”本轮闭合）；R2 13 条全修；R3 16 条全修；真机 22 条中 20 条已修（代码面或真机面），1 条部分（R3-BUG-1 修出 R4-P1-1），R3-OBS-1 仍是观察。**差集不为 ∅**——新增 R4-P1-1 与 R4-P2-1…R4-P2-4 共 5 条。

## 家族复扫（机械枚举，差集）

| 家族 | 枚举方法 | 命中 | 结论 |
|---|---|---|---|
| 钉死哈希 | grep 全部下载点 + 四哈希出现位置 + 版本 | 下载点 2 处，哈希逐字节一致，版本 1.11.15/2.7.0 两处一致 | ∅ |
| FORWARD 规则 | grep FORWARD 全树 | install.sh 直连两条 + policy-routing SK5 四条 + verify.sh 断言；桩测启停正确 | ∅ |
| TOFU | grep install-agent.sh 全部 curl 调用 | 全部面板拉取走 curl_panel / $CURL_TLS；裸 curl 只在 die/warn 文案 | ∅ |
| CN | grep EASYRSA_REQ_CN 全树 | 仅 3 处行内赋值 + 注释；stub 实测无全局泄露 | ∅ |
| 密钥 | find secret.key/*.pem + .gitignore | 树内零密钥文件；发货值轮换；/etc 0600 | ∅ |
| 202 轮询 | grep 202 + apiWait 调用点 | 10 个写操作全走 apiWait；非排队 POST 直接返回是正确语义 | ∅ |
| set_sk5 | 全部调用方（Flask/Worker/agent/egress） | 部分合并三端一致；Worker 仍发全量是纵深防御 | ∅（实现面）；但“保存即重起”的耦合是新族，见 R4-P1-1 |
| 健康检查 | timer/service + check_health 分支 | 单元在位且安装；fail-open 分支调 disable()，但 disable() 抛错时无兜底 | **≠ ∅：R4-P1-1** |
| 安装命令拼装 | 两份生成器 vs README 命令 | 两份生成器同口径（两步/-k/sha256/--node-name/三处引号）；README 两处已同口径 | ∅（实现面）；复制清单漏 systemd/ 见 R4-P2-2 |
| 状态日志解析 | 四路行形 + 其他解析器 grep | 四路全过；全树无第二解析器 | ∅ |
| sing-box 常驻（新） | disable/enable/set_sk5/check_health 调用图 | disable()→_start_singbox() 无 try；set_sk5 无模式变化判断；check_health fail-open 分支无 try | **≠ ∅：R4-P1-1** |
| 旗标诚实性（新） | get_status 全部布尔旗标 vs 其定义 | policy_routing_active 只看规则存在 | **≠ ∅：R4-P2-1** |

## 门禁变异验活

| 门禁 | 基线 | 变异 | 结果 |
|---|---|---|---|
| verify-integration.sh | 20/20 | `status()` 恒 500 | 19/1，红在登录态 status 格——活着 |
| verify.sh | PASS=5 FAIL=5 SKIP=11（沙箱环境缺口，诚实） | 删 healthcheck.timer | PASS=4 FAIL=6，files 格红——活着 |

## 诚实边界（未验，不许当已验证）

- **Cloudflare 从未真实 `wrangler deploy`**：KV id 仍是占位符，Worker 结论全部来自 mock KV + mock 源站套件（48/50 + 22/22 + 重投反证），不是线上实测。部署前须真跑 `wrangler kv namespace create`、`wrangler secret put ADMIN_PASSWORD`、`wrangler deploy` 并换第二出口多点核验。
- **真机第四轮正在并行跑**：凡依赖真机数据的结论——默认重跑（R3-BUG-6/R2-BUG-16/BUG-15）、verify.sh 全绿（R3-BUG-2/4 的门禁面）、disable 序列（R3-BUG-1）、默认 remote（R3-BUG-5）、从 /opt 重跑（R3-BUG-3）——本文一律只认代码面，不提前判通过，以 live-R4 为准。
- **easy-rsa 真机行为未验**：CN 隔离只在 stub easyrsa 上验过；真实 easy-rsa 3 签发全流程须真机复核（R2 的同款保留意见）。
- **install.sh 全流程未在沙箱跑过**：只做了语法 + 门禁 + 关键分支（继承块）抽取实测；Lightsail 彩排部署上的原地升级路径（现行正式版 → 候选版）须按用户 2026-11-11 令走一遍才算发版门禁通过。
- **旧套件期望过期**：Worker 套件与前端套件各有 2/3 项“失败”是过期期望被 K/L 的修复推翻，不是回归；本轮已逐项核对实测值与新行为一致。后续审计须先把这两套件的期望同步到新行为，否则会反复误报。
- **本审计的副作用**：探针在沙箱 `/etc/openvpn-sk5-panel/` 落下的 4 个文件已删、目录已删；审计副本与套件在 `/tmp/audit4*`、`/tmp/audit4-tests/`，未动项目原文件、未动真机。

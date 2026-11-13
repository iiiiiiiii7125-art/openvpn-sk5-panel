# AUDIT-R15 — 全量全局回头看（交付前，第三轮）

## 结论先写

**结论：不能交付，差集 2 条（P2×2，R15-P2-1～R15-P2-2）。**

历史 144 条：141 已修（R14 的 138＋R14 的 3 条本轮全部关闭，变异红证齐全）、2 部分（P0-3、P1-7，按设计）、1 未验（P0-1 部署态，见 §5）；**无一复发**——已登记的谓词逐条皆绿。本轮 2 条新发现均为同族残留（谓词与 R14 登记项不同，见 §3.1）：门禁新格的哈希集合校验存在盲区——只比无标签集合，标签→哈希绑定漂移照样过门禁（P2-1，变异树 m-gate-swap 实证）；交付文档多处宣称与行为不符（P2-2，文档同族复发：门禁计数过期两处、flmx-reference 32 行“照抄”中 13 行无实现＋4 行部分实现且与根 README 既定口径矛盾、Worker 测试数过期、卸载指引不完整等，枚举见 §2.2）。BA/BB 两路修复本身全部行为验证通过（6 棵定点变异树对应格子恰红）；live-10 报告已落盘但未完工（§18–§20 待填），§8 对账只认已落盘文字、不代判。

- 审计员：独立审计路（未参与建设与修复路 BA/BB；单审计员边做边写，不派子代理）
- 日期：2026-11-13（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R14 同等广度）
- 推导方法：**交付文档驱动的用户旅程重演**（与 R1 逐文件通读、R2 旅程、R3 宣称驱动、R4 不变量、R5 故障注入、R6 状态转移、R7 从零旅程、R8 并发＋幂等＋失败原子性、R9 对抗操作员＋时间衰变、R10 环境矩阵×修复存活、R11 契约闭合、R12 外部输入枚举、R13 部署生命周期、R14 证据优先行为复推导均不同）——以一名首次交付用户手里只有交付文档（9 份）为前提，按文档写的每一步从头操作一遍（安装、建服务、建用户、下发 agent、填 SK5、一键启用、验出口、改密、吊销、下载 .ovpn、重装／重跑），每一步的行为与文档宣称逐项对账；宣称与行为不符即立案（不论代码“本意”如何）。再叠加历史全量复扫（R14 的 141＋3 条逐条定性）与 BA/BB 新代码逐项行为验证（带变异红证）。
- 测试一律在 `/tmp` 副本（`/tmp/r15/tree` 树副本、`/tmp/r13-tests/` 沿用 R13 的 harness＋探针、`/tmp/r14/` 沿用 R14 探针与变异树、复用 `~/workspace/ae-tests/poison/` 毒包）上跑；未动项目原文件（除本报告）；Flask 探针进 `unshare -m` 挂载命名空间，`/etc/openvpn-sk5-panel` 与 `/etc/sysctl.d` 绑 /tmp；staged 安装探针进 `unshare -m`，`/opt/openvpn-sk5-panel`、`/etc/openvpn-sk5-panel`、`/etc/openvpn/server`、`/etc/systemd/system`、`/etc/iptables`、`/var/log/openvpn` 绑 /tmp；未动任何真机。需真机行为复核的项一律写“待 live-11”或对账 live-10，不提前判通过。
- 语法基线：4 个 Python 文件 `py_compile` 全绿；7 个 shell 脚本 `bash -n` 全绿；Worker `node --check` 全绿（见 §0）。
- 文档骨架注：任务简报称“doc/index.md＋doc/guide/ 13 篇”为功能链骨架，但**本项目树里不存在 `doc/` 与 `docs/guide/`**（`find` 实测无此目录与文件）；本轮的功能链骨架以本树实际的 9 份文档为准——根 README、panel/README、cloudflare/README、cloudflare/server-mode.md、core/README、agent/README、egress/README、docs/security.md、docs/flmx-reference.md。简报的骨架描述是 FLMX 项目的移植残留，非本产品缺陷，不立案，特此记明（与 R9/R10/R11/R12/R13/R14 同款记明）。

## §0 树版本与 BA/BB 改动确认

当前树是 R14 修复路 BA/BB 之后的新树。文件 mtime（UTC）与 R14 §0 基线对照：

| 文件 | mtime (UTC) | 行数 | sha256（前 12 位） | 说明 |
|---|---|---|---|---|
| panel/app.py | 2026-11-12 17:20:11 | 2737（R14: 2694） | fc81691c96d3 | 动过（BA：`_fail_malformed_cmds` 扩展到 queue/cmds/ovpn 三段、吊销／专用下载／入队三处先扫队列；与主控核验的 sha256 一致） |
| core/openvpn_manager.py | 2026-11-12 17:20:57 | 1550（R14: 1542） | 3b5d7dfe9ea1 | 动过（BB：render dns 合并改 `dns is None` 显式判定） |
| cloudflare/README.md | 2026-11-12 17:20:57 | 260（R14: 260） | d0d274560a9c | 动过（BB：:135 钉位删行号、只留函数名） |
| verify-integration.sh | 2026-11-12 17:22:26 | 591（R14: 567） | 762290d87c1f | 动过（BB：§7 新增钉死哈希一致格，门禁 28→29；钉位 grep 门禁裁决不加，理由写 §7 注释） |
| install.sh | 2026-11-12 16:46:54 | 1082 | 3f050f037e7a | 未动（R14 mtime） |
| cloudflare/src/index.js | 2026-11-12 16:45:26 | 1221 | e40fe4d7d8d0 | 未动 |
| agent/agent.py | 2026-11-12 16:46:20 | 922 | 7f999298df5b | 未动 |
| README.md | 2026-11-12 16:46:57 | 277 | 33f530b9fa71 | 未动 |
| panel/README.md | 2026-11-12 16:46:57 | 113 | 2c9c5e6e43e7 | 未动 |
| docs/security.md | 2026-11-12 16:47:16 | 63 | da5277cb0438 | 未动 |
| cloudflare/server-mode.md | 2026-11-12 16:50:36 | 48 | 245e0d448b54 | 未动 |
| docs/flmx-reference.md | 2026-11-12 16:47:28 | 112 | ee8ded22f7ed | 未动 |
| panel/templates/index.html | 2026-11-12 15:21:57 | 1259 | 4f7dc697451c | 未动（R13 mtime） |
| verify.sh | 2026-11-12 14:45:28 | 846 | 7867f557c6bb | 未动 |
| egress/sk5_manager.py | 2026-11-12 12:37:13 | 1109 | 02de9d8a4908 | 未动 |
| egress/policy-routing.sh | 2026-11-12 12:13:01 | 364 | 103a121bbdfe | 未动 |
| panel/data/ | 2026-11-12 12:14 | 空目录 | — | AE 路清空后仍空；AN 的 staging 拷贝不再往里写任何文件 |

语法基线（本轮实测）：`panel/app.py`、`egress/sk5_manager.py`、`core/openvpn_manager.py`、`agent/agent.py` 四文件 `py_compile` 全绿；`install.sh`、`verify.sh`、`verify-integration.sh`、`egress/test-egress.sh`、`egress/policy-routing.sh`、`core/easyrsa.sh`、`agent/install-agent.sh` 七脚本 `bash -n` 全绿；`cloudflare/src/index.js` `node --check` 全绿。

/tmp 资产现状（本轮开工时实测）：**R13/R14 资产幸存**——`/tmp/r13-tests/`（全部探针＋harness＋fakebin＋venv＋install-runs/）、`/tmp/r14/tree`（R14 树副本）、`/tmp/r14/mutants/`（m-aw1～m-az2 七棵 R14 定点变异树）、`/tmp/r14/r14_unswept.py`、`/tmp/r14/r14_dns.py`、`/tmp/r14/r14_worker_bodies.mjs`、`/tmp/r14/build-mutants.py`、`/tmp/r13/mutants/`（R13 九棵变异树）均在；`~/workspace/ae-tests/poison/` 幸存。本轮策略：R13/R14 探针原样复用（以报告机制为准，不改期望——除非期望本身断言的是 bug 行为，见 §1.1 注）；变异红证改用**新变异树**（从当前树逐项回退 BA/BB 的修复点，见 §1.5）；R14 的旧变异树作为 R13 修复存活的对照复用（§3.1）。


## §1 BA/BB 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

探针与 harness 沿用 R13/R14（`/tmp/r13-tests/`、`/tmp/r14/`，幸存，见 §0）：fakebin 13 个（easyrsa 用真 openssl 签发真证书；openvpn 只认 `--genkey secret`；systemctl 为状态机，staged 安装时真拉起面板；sing-box 只认 version/check；ip/iptables/apt-get/dpkg-query/ufw/curl/sysctl/modprobe 均为状态化假件）；Flask 探针进 `unshare -m`（`/etc/openvpn-sk5-panel`、`/etc/sysctl.d` 绑 /tmp scratch，宿主挂载点预先 mkdir）；core 探针直接跑（只碰 scratch CA/SERVER 目录）。本轮全部探针对 **`/tmp/r15/tree`（现树逐字节拷贝，sha256 逐项对 §0 一致）** 跑，不直接跑项目树。变异红证：新变异树（从现树逐项回退 BA/BB 的修复点，`/tmp/r15/build-mutants.py`，每处回退点断言唯一命中），见 §1.5。

### §1.1 BA（panel/app.py）—— r14_unswept 6/6、r15_sweep 2/2、inputs 86/86、adv 28/28

**unswept 6/6**：U1（非对象 cmds 条目在位时 DELETE → 200）、U2（节点消失＋good1 标 failed）、U3（非对象 ovpn 回执 → 404）、U4/U5/U6 对照全绿。**inputs 86/86**（D10 新期望见 §1.1 注）、**adv 28/28**、nodeparam 45/45、diskfull 5/5、lockout 5/5、download 12/12、changepw 7/7、lifecycle 8/8。

注（D10 期望变更复核）：r13_inputs 的 D10 已由主控按 R14-P2-2 新行为改过——`dns=''` 现须抛错（旧期望“静默取默认 1.1.1.1”断言的是 bug 行为）。复核结论：**改动正确**。`_validate_dns` 本身一直拒绝 `""`（直接调用抛错，r14_dns D3 对照），render 入口的 `or` 合并是唯一绕过点；BB 修后 D10 与 r14_dns D1/D2/D3 的新行为一致（falsy 一律抛错、None 取默认）。与 AW 的 L5 同款处理（期望断言 bug 行为时改期望、不改代码），不另立案。

### §1.2 BB（core＋cloudflare/README）—— r14_dns 6/6、Core 19/19、AU 20/20

**dns 6/6**：D1 `dns=False`、D2 `dns=0`、D3 `dns=""` 均抛错；D4 `dns="8.8.8.8"` 渲染为 8.8.8.8；D5 `dns=None` 正常取默认；D6 `dns="  "` 抛错。**Core 19/19**、**AU 20/20**（G12 转绿后保持）、agent 21/21。

注（r14_dns.py 探针修补复核）：BB 把 `dns_in_conf` 改成缺文件回 None（D1/D2/D3 在修复生效时才抛错、conf 不存在，旧版急切求值细节串会崩溃）。复核结论：**改动正确**——只改容错、不改期望；D1/D2/D3 的断言仍是“抛错”，容错只影响失败细节串的构造，不影响通过／失败判定。

### §1.3 其余（本轮亲自重跑）

- **r13_env.py 3/3**：OVPN_DNS 含空格 → 服务创建 500＋invalid DNS；OPENVPN_CA_DIR 指向空处 → status 200；OPENVPN_PORT=abc → status 200＋error 含 int 转换错。
- **r13_href.mjs 6/6**：withNode 实测（无节点原样、有节点 `?node=`、已有查询串用 `&`、非白名单路径不动、特殊字符编码、:748 dl.href 确走 withNode）。
- **Worker**：inputs 23/23、Y 矩阵 13/13、r14_worker_bodies 9/9、AY lockout 13/13（4 个畸形体全 400 无记账、错密码 5 次后 429）。
- **AZ staged（本轮亲自重跑）**：默认安装 EXIT=0——健康门 login＋/api/status 200、server.conf `server 10.8.0.0 255.255.255.0`；`OVPN_SUBNET=10.9.0.0/24` EXIT=1、die 文案在日志、server/iptables 目录零写盘。**AN 两件本轮亦亲自重跑**：probe_bug1 毒树默认重跑 EXIT=0、`panel/data/ excluded`、落盘 admin hash 与毒库不同（新密码生成）、无 agent_queue.json、健康门 200；probe_bug2 ufw 预置 2000 条 EXIT=0、ufw 在、规则 2002 条、健康门 200。过程注：每跑之间按精确 PID 杀掉 fake systemctl 拉起的残留面板（43951／44502／45062），8443 空闲后下一跑才起得来——与 R14 §1.4 同族教训，staged 安装须串行、每跑之间杀残留面板；本轮三跑均一次通过。

### §1.4 门禁 verify-integration.sh：29/29（本轮在 /tmp/r15/tree 副本上实测）＋双变异红证

`bash verify-integration.sh`：**PASS=29 FAIL=0 SKIP=0**（含 BB 新加 §7 钉死哈希一致格）。机械推导：脚本内 `ok "` 文本出现 31 处，其中 1 处是 `check()` 助手定义内永不单独触发的 `ok "$name"`（`check` 本身无调用点，死代码），另 2 处是同一格的互斥分支（/etc admin.pass 格的 elif／else 各一 `ok`，一次运行只触发其一）——31－1－2＝**29 格**，与运行时汇总一致。**变异红证两则**：(a) `/tmp/r15/gate-mutant`（status() 恒抛 500）跑门禁 → **PASS=28 FAIL=1**，恰红“登录后 GET /api/status 返回 500”一格；(b) `/tmp/r15/gate-mutant2`（install.sh 的 sing-box amd64 哈希改一位 950af37e→950af37f）跑门禁 → **PASS=28 FAIL=1**，恰红 §7 新格“钉死哈希不一致”。门禁是活的，不是摆设。

### §1.5 变异红证（6 棵定点变异树，BA 双层须双回退）

| 变异树 | 回退的修复 | 探针 | 变红格子（旧行为签名） | 结论 |
|---|---|---|---|---|
| m-ba1 | 吊销／专用下载两处扫队列调用 | r14_unswept | 无（6/6 仍绿，见注） | 单层回退不红——isinstance 纵深兜底生效 |
| m-ba2 | `_fail_malformed_cmds` 的 ovpn/queue 段扩展 | r14_unswept | 无（6/6 仍绿，见注） | 单层回退不红——下载侧 isinstance 守卫兜底 |
| m-ba1x | 扫队列调用＋isinstance 守卫双层同回退 | r14_unswept | U1（DELETE → 500）、U2（good1 仍 queued）、U3（下载 → 500），恰 R14-P2-1 签名 | BA 修复整体真生效 |
| m-ba1x-sweep-only | 只回退扫队列调用（守卫留存） | r15_sweep 2/2 | S1/S2 恰红：DELETE／下载状态码不变（200/404），但坏条目存活、审计行缺失 | 扫队列层的独特效应是清理＋审计，红证成立 |
| m-bb1 | dns 合并回 `dns or default` | r14_dns | D1/D2/D3（False/0/"" 静默渲染默认，恰 R14-P2-2 签名） | BB 的显式 None 判定真生效 |
| m-bb2 | cloudflare/README:135 钉位回 `agent.py:676` | grep | `agent.py:676` 在正文重现 | BB 的删钉位真生效 |

注（BA 双层结构，已查清）：BA 在吊销与专用下载两处各设两层——先扫队列（清理＋审计）＋isinstance 守卫（防崩）。单回退任一层，另一层兜底，状态码格子仍绿；双层同回退则 U1/U2/U3 恰红（R14 签名复现）。扫队列层的独特效应不在状态码上——新树上 DELETE 后坏条目已从队列文件删除且审计行 `queue_cmd_malformed` 在位（r15_sweep S1/S2 2/2），扫队列回退树上坏条目存活、无审计行（0/2）。两层各有独立红证，BA 修复非摆设。

新树上全部探针绿（Flask 202 格＋Core/AU/DNS 45 格＋Agent 21 格＋Worker 45＋13＋9 格＋门禁 29 格，见 §1.1–§1.4），变异树上对应格子红——BA/BB 两路修复均有行为红证，非代码在场。

### §1.6 门禁 §7 新格盲区——R15-P2-1（本轮新发现，变异实证）

**机制谓词**：`verify-integration.sh` §7 格声称执行的 invariant 是根 README:198 的“`install.sh:63-66` 与 `agent/agent.py:122-132` 哈希块**逐字节一致**”；但格子的实际判定是两文件内全部 64-hex 串的**无标签集合相等**（`grep -oE '[0-9a-f]{64}' | sort -u` 后比较）。集合相等对置换不变：任一文件内两个哈希值在标签位之间互换，集合不变、格子仍绿，而逐字节一致已被破坏、标签→哈希绑定已错。

**变异实证（反向红证：应红而绿）**：`/tmp/r15/mutants/m-gate-swap`——只把 `agent/agent.py` 里 sing-box amd64/arm64 两个哈希值互换（标签 `SINGBOX_SHA256_AMD64/ARM64` 不动，绑定错位），其余与现树逐字节一致。跑门禁：**PASS=29 FAIL=0**，§7 格明文 `[PASS] 钉死哈希一致：install.sh 与 agent/agent.py 的 sha256 集合相同`。两文件哈希集合逐项相同（4 个串全在），但 agent 侧 `_expected_sha256` 的 amd64 绑定已是 arm64 的哈希——amd64 节点上 agent 侧安装校验会对 amd64 二进制算 arm64 哈希（fail-closed 死在安装时，非静默损坏，故 P2 而非 P1）。

**全集（机械推导）**：4 个标签绑定/文件（sing-box amd64/arm64、tun2socks amd64/arm64）×2 文件＝8 个绑定；单文件内任一对互换（每文件 C(4,2)=6 对 ×2 文件＝12 种单文件互换）全部过门禁；两文件同向互换亦过。门禁只对“值漂移”（改一位哈希，gate-mutant2 已证恰红）敏感，对“绑定漂移”全盲——恰是 §7 注释 (a) 自己指出的失效模式（“错的是指向的内容”）：存在性/集合级校验对内容级漂移空洞，新格把同一毛病从行号级搬到了集合级。

**修法**：按标签比对——从 `install.sh` 取 `SINGBOX_SHA256_AMD64=…` 等 4 个命名赋值，从 `agent/agent.py` 取 `_PINNED_SHA256` 字典 4 项，逐键相等且非空才绿；注释里“逐字节一致”的宣称改成与判定一致的表述（或改判定为逐字节比对两块文本）。另注：双文件同错（上游重发资产致两边哈希同错）同样过门禁，只在安装时 fail-closed 被发现——属本格 scope 外，记为局限，不另立案。

## §2 交付文档驱动的用户旅程重演（本轮新方法）

方法：以一名首次交付用户手里只有 9 份交付文档为前提，按文档写的步骤从头操作一遍，每一步的行为与文档宣称逐项对账。旅程分 12 步（J1–J12）；沙箱可走的格子亲手跑行为探针（staged 安装、Flask/Worker/agent/core 探针），沙箱走不了的格子（真机数据面、真实部署）记“待 live-11”，不冒充。宣称来源逐项标注文档行号。


### §2.1 旅程 J1–J12 逐项对账

| 步 | 文档步骤 | 行为核对（本轮亲手跑／代码核实） | 结论 |
|---|---|---|---|
| J1 安装（服务器） | 根 README 部署方式一：拷树＋`bash install.sh`，步骤 1–8 | staged 安装三跑亲手重跑（§1.3）：默认 EXIT=0 健康门 200；`OVPN_SUBNET=10.9` EXIT=1 零写盘；AN 毒树重跑 EXIT=0、ufw 2000 条完整。步骤逐项对代码：① FLMX 断言 `install.sh:111-117`（5 路径）；② apt 行 `:290-293`（openvpn/easy-rsa/curl/jq/python3/python3-pip/iproute2/unzip/ca-certificates/openssl/procps；iptables-persistent 仅无 ufw 时装）；③ sing-box 1.11.15＋tun2socks 2.7.0 钉死哈希＋`verify_asset` fail-closed（`:63-66`、`:304` 起）；④ 拷贝＋0700 配置目录；⑤ PKI 守卫 `if not ca_crt.exists(): init_pki()`（`:739` 起，重装保留 CA）；⑥ sing-box 直连配置＋check；⑦ TLS wrapper（`systemd/openvpn-sk5-panel.service` 注释＋`run-panel-tls.py`）；⑧ 健康门 `/api/me` 200＋登录＋`/api/status` 200（`:933-945`）。目标机口径 README:53（Debian 12 / Ubuntu 22.04 / 24.04、root、amd64/arm64）与 `install.sh` OS 门一致 | 通过 |
| J2 建服务 | `POST /api/openvpn/server`（port/proto） | P01 占用检查 `core:975 _port_occupant`＋渲染时检查 `:1119`；无 `allow_port_change` 改端口面板 500（`app.py:1534` 起 except→500）；UDP 默认 1194／TCP 默认 443（`install.sh` case 段）。探针 nodeparam 45/45、inputs 86/86 | 通过 |
| J3 建用户 | `POST /api/openvpn/users`（`[a-zA-Z0-9_-]{1,32}`） | `validate_username`（core:99）；重名有效证书抛 `UserAlreadyExistsError`（core:826 起）；legacy（CN=OpenVPN-CA）重建先吊销旧证再重签（core:860 起）；`ovpn_url` 返回（`app.py:1764`）。探针 lifecycle 8/8、download 12/12 | 通过 |
| J4 下发 agent | 注册＋两步安装命令＋poll/report | 注册 201、token 只返回一次；`install-agent.sh` 两步走＋sha256（`:294-299` apt 装 python3/curl/ca-certificates；`:63` 默认 hostname；`--force`＋备份＋reset-failed）；`--node-name` 缺省用 hostname→poll 401（与 README 一致，见 §2.2 注）。真机链 live-10 §4 已验（bundle sha256 OK、poll 5 秒、cmd 202→done） | 通过 |
| J5 填 SK5 | SK5 表单＋保存语义＋UDP 守卫 | 表单字段级指引 4/5（地址占位、端口 1–65535＋“端口待确认”注、密码 `type=password`、fail-open/UoT 就地说明、测试按钮＋UDP 提示；缺“用户名是否含 `session-` 前缀”提示，见 §2.2 观察）；密码空＝保留、非空覆盖、`clear_password` 才清空（`app.py`＋egress）；Worker UDP 保存守卫谓词逐字核实（`index.js:924` 起：UDP 模式＋同地址最近一次 UDP 明确失败→400）。探针 inputs/adv 全绿 | 通过（1 观察） |
| J6 一键启用 | enable/disable、fail-open、UoT | `enable()/disable()` 起停 sing-box＋挂摘表 100（egress）；fail-open 默认 False＝黑洞（单向，须手动重开）；UoT 开关读 `udp_over_tcp` 优先回落 `enabled`（AS 修，inputs 86/86）。门禁 storm 格 7 次切换全 200 | 通过 |
| J7 验出口 | `POST /api/sk5/test` 分项 TCP/UDP、状态轮询 | test 返回 `{tcp_ok, udp_ok, egress_ip, latency_ms, …}` 分项；`/api/status` 延迟为空（只取 IP，不跑 10 秒＋探针，`panel/README` 已明示）；egress 探针 10 秒缓存、前端 15 秒轮询。沙箱 UDP/TUN 均 EPERM，数据面行为不冒充——待 live-11；live-10 S1/S2 已在真机验直连＋SK5 数据面（§8 对账） | 沙箱未验，live-10 已验 |
| J8 改密 | 顶栏改密＋Worker 501 | changepw 7/7（≥12 字符＋字母数字＋≠旧密码，`app.py:302`；成功回 `ok, note`，`session_version`＋1，admin.pass 文件同步 `:1314`）；Worker 501 含 wrangler 指引（AQ，Y 矩阵 13/13）；`Secure` 标记只在 `OVPN_PANEL_HTTPS=1` 时开（`app.py:189`，注释写明原因）。首登强制改密未实现——P1-7 部分（按设计），根 README:260 与 security.md 诚实披露；但 flmx-reference 3-1 仍称“照抄”强制改密，见 §2.2 | 通过（文档矛盾见 §2.2） |
| J9 吊销 | `DELETE /api/openvpn/users/<name>` | 吊销＋CRL＋须重启（`needs_restart: true`）；BA 修后吊销路径先扫队列（unswept 6/6，§1.1）；节点吊销使 queued/sent 命令一并标失败 | 通过 |
| J10 下载 .ovpn | 用户列表下载链接＋三路径 | withNode 修复（href 6/6）；三条下载路径统一吊销／过期 403（AW，download 12/12）；证书缺失 404 JSON。探针全绿 | 通过 |
| J11 重装／重跑 | 幂等重跑＋卸载 | 重装不轮换密码／CA／证书：`_ensure_admin_password` 有行即返（`app.py:313`）、PKI 守卫（`install.sh:739` 起）、AN 毒树重跑行级比对（live-9 headline-9）。卸载：根 README:265 手动命令——**只删 NAT POSTROUTING 规则，未清 FORWARD 规则与 ufw 放行／路由规则**，且无交互确认（与 flmx 1-9 的“先确认、默认取消”不符），见 §2.2 | 重装通过；卸载指引不完整（§2.2） |
| J12 Cloudflare 部署 | `wrangler deploy` 三步 | `wrangler deploy --dry-run` 本轮通过（KV 占位仍显示）；真实部署仍卡登录＋KV 占位（§5，P0-1 未验）。部署步骤本身完整：`cloudflare/README:30-31` 明确要求把 KV id 填进 `wrangler.toml`（填之前 deploy 报错是故意的） | 未验（§5） |

### §2.2 新发现 R15-P2-2——交付文档宣称与行为不符（文档同族复发）

**机制谓词**：9 份交付文档中的任一可核对宣称（计数／行号／签名／行为描述／“照抄”断言），与树内实际行为（探针输出／代码／另一份交付文档的既定口径）不符。**全集**：下表逐项枚举，修法统一为“改文档对齐行为”（AO/AZ 先例），不动产品代码——除非某项宣称的行为本身才是对的（本轮无此种）。

**（a）门禁计数过期两处（R10-P2-1 同族复发，BB 加格后未同步文档）**：
- 根 `README:226` 仍写 `**PASS=28 FAIL=0 SKIP=0**`；实测门禁 29/29（§1.4）。
- `egress/README.md:210` 仍写 `verify-integration 28/28`；实测 29/29。
- 修法：两处 28→29（或删具体数字、只留“门禁全绿”＋脚本自证）。

**（b）`docs/flmx-reference.md` 的 32 行“照抄”逐项复核（R13-P2-7 同族复发）**：机械枚举全部 32 行（`grep '^| [0-9]'`），每行按代码／探针定性。15 行属实、**13 行无实现、4 行部分实现**。另 3 行改写行（2-5、3-9、1-16）的机制描述亦不实，一并列入。

| 行 | 宣称（照抄） | 核实 | 定性 |
|---|---|---|---|
| 0-1 | API 信封统一 `{code,msg,data,ts}`，poll/report/命令结果全部用同一信封 | 全树 `"code"` 零命中；三端一律 `{ok, error}`（`app.py:2570`、`index.js:654`） | **假** |
| 0-3 | 后端只经 Repository 读写 DB；三张表都要 `TableName()` | `TableName` 全树零命中；Python 直连 sqlite，无 Repository 层 | **假** |
| 1-4 | agent 已有部署须显式 `--force`＋备份旧 config | `install-agent.sh:48-51` 注释＋`:79-81`＋备份逻辑属实 | 真 |
| 1-5 | JWT secret／节点 token／agent 注册 token 全部 32 字符 urandom，禁写死默认值 | token `token_urlsafe(32)`、会话密钥 `token_bytes(32)`、无写死默认值属实。注：管理员密码是 `token_urlsafe(16)`（22 字符）而非“32 字符”，熵 128 bit 够用，文字不准——观察，不另立案 | 真（1 处文字偏差） |
| 1-6 | 面板 `.env` 同款键名（`FLUX_VERSION` → `OVPN_VERSION`）；改配置 mktemp+mv | 无 `.env` 文件、无 `OVPN_VERSION`（全树零命中）；`panel.env` 10 个键无版本键；配置写盘用 heredoc 直写，非 mktemp+mv | **假** |
| 1-8 | 升级保留存量 `10.8.0.0/24` 与已签发 CA | `install.sh:739` 起 PKI 守卫＋AN 重跑实证属实 | 真 |
| 1-9 | 卸载同款：先确认、默认取消；卸载 agent 可勾选“同时吊销全部用户证书” | 无卸载脚本；根 README:265 只有手动命令、无确认提示、无吊销选项 | **假** |
| 1-10 | `POST /api/nodes/{id}/install` 返回 fail-closed 命令模板（仅 Worker） | Worker 路由 `:1141`＋`installCommand:433` 属实；`channel` 未抄已在行内明示 | 真 |
| 1-11 | agent 版本同款按 channel 解析 | 无 channel 解析；agent `VERSION = "0.1.0"` 静态自报；根 README:249 明文“版本解析一步 OpenVPN 不抄”——**与根 README 直接矛盾** | **假** |
| 1-13 | 安装命令先取脚本＋`.sha256`，验不过即停 | 两端端点＋安装器校验属实（§1.3、live-10 §4） | 真 |
| 1-14 | `install-agent.sh --panel-url/--token` 同款长选项 | 属实（`:77` 起） | 真 |
| 1-15 | agent bundle 同款 Release＋`.sha256` 派生校验 fail-closed；sing-box/tun2socks 哈希未钉问题用同一办法解 | 钉死哈希在安装器＋agent 内（`install.sh:63-66`、`agent.py:122-132`），`verify_asset` fail-closed；上游无 manifest 已在注释明示，checksums.txt 机制由内置钉死替代 | 真（机制替代已明示） |
| 1-17 | `ovpn-agent.service` 同款：reset-failed→enable→start→判活 | `install-agent.sh:384-400` 属实 | 真 |
| 1-21 | `Sk5ProfileID`（0=直连，>0=链到某条 SK5 配置）；`OutboundIPStrategy` 照抄缺省 auto | 两标识全树零命中；面板只有按节点 `sk5cfg:<name>`，无 profile 模型、无策略字段 | **假** |
| 1-24 | OpenVPN 服务端口同款 P01 铁律 | `_port_occupant`（core:975）＋渲染检查 `:1119` 属实 | 真 |
| 1-25 | Worker UDP 保存守卫＋前端确认 | 服务端谓词逐字核实（`index.js:924` 起）；前端确认＋提示（`index.html:626`、`:1203`）属实 | 真 |
| 1-27 | 轮询每次带 token、面板每次查库复核；轮换后旧 token 下次 poll 即 401、面板显示重下安装命令 | `_agent_auth` 每 poll 查库；轮换端点 `app.py:2375`＋前端确认框“旧 agent 须重跑安装命令”＋新 token 只显示一次（`index.html:914` 起）属实 | 真 |
| 1-29 | 面板侧命令队列按节点限流（每节点每分钟最多 N 条，超了 429）；agent poll 失败同样按 IP 限流 | 全树命令限流零实现（唯一 429 是登录锁 `app.py:1249`）；`agent_poll` 内无限流／锁逻辑（`:2526` 起全文核对） | **假** |
| 1-32 | 节点表同款字段（Status / Version / OpenvpnPort / Sk5Enabled）；在线＝最近 poll 30 秒内 | nodes 表只有 name/token_hash/panel_url/created_at/last_seen/last_status（`app.py:231`）；前端零 `version/版本` 命中，agent 版本无处显示；30 秒在线判定本身属实（`index.html:802`） | **假**（在线规则真，字段假） |
| 2-2 | 照抄三布局；侧栏折叠状态同样存 localStorage；改密入口放顶栏头像菜单 | 单页应用，无三布局；`sidebar_collapsed` 全树零命中，侧栏无折叠（仅移动端开合，无持久化）；改密顶栏按钮本身属实（`index.html:283`） | **假**（改密位置真） |
| 2-4 | 节点页同款分块：节点卡片（在线/版本/出口 IP）＋复制安装命令＋服务页签＋实时状态 | 节点表（在线／出口 IP／SK5／操作）＋复制安装命令＋nav 分区＋实时状态属实；**版本列不存在**（节点表 6 列无版本，前端零版本命中） | 部分 |
| 2-5 | （改写）服务页：`server-form-modal`＋`sk5-modal`＋`presets.ts`（UDP 1194 / TCP 443 两个预设） | 无 modal、无 `presets.ts`；服务表单与 SK5 表单是单页内联 section＋proto 下拉，无预设机制 | **假**（具名产物不存在） |
| 2-6 | 工具栏／卡片逐字照抄 Tailwind class 组合（粘性工具栏 `sticky top-0 …`） | Tailwind class 全树零命中；顶栏**不** sticky（仅侧栏 sticky，`index.html:66`）；玻璃卡片样式以 vanilla CSS 实现。根 README:251 重复同一逐字宣称 | 部分（形似，逐字假） |
| 2-7 | 玻璃值逐字照抄（0.6–0.7） | 侧栏／顶栏 `rgba(255,255,255,.70)`、blur 16–24px，数值落在 0.6–0.7 区间；变量名不同（vanilla CSS） | 基本真 |
| 2-8 | 三档阴影照抄 | 三档阴影结构存在（侧栏／顶栏／按钮），数值非逐字 | 基本真 |
| 2-9 | 对比度目标 7／底线 4.5，交付前渲染级自检 | 流程存在：自检 10/10（§7）＋live-10 真渲染交叉验证 | 真 |
| 2-10 | SK5 表单每字段就地写明（地址格式、端口范围、`session-` 前缀、密码不回显、保存后点测试） | 前 4 项中地址／端口／密码不回显／测试提示属实；**用户名 `session-` 前缀提示缺失**（`sk5User` 字段无占位／提示，`index.html:474`） | 部分 |
| 3-1 | 首登同款：初始密码首次登录只发受限 token，强制改密后才给正常 token | 首登强制改密未实现（P1-7 部分，按设计）；根 README:260 明文“改密（不强制）…不设改密前置条件”——**与根 README 直接矛盾** | **假** |
| 3-3 | 照抄整套 JWT：7 天过期、alg 白名单、改密即全部旧 token 失效；Worker 用 WebCrypto 实现同一校验 | JWT 全树零命中；会话是 12 小时 cookie（`app.py:191`），无 alg 校验、无 WebCrypto | **假** |
| 3-4 | 管理员密码 bcrypt 存储＋dummy bcrypt 照抄 | bcrypt 存储属实（含 SHA-256 回落）；dummy bcrypt 零命中 | 部分 |
| 3-6 | agent 安装前置守卫照抄流程（config 地址不同→拒绝或 `--force`） | `install-agent.sh:95-99` 断言＋`:48-51` 注释属实 | 真 |
| 3-7 | 普通 VPN 用户只能看自己的 `.ovpn` 与在线状态；`MonitorPermission` 同款例外表 | 无普通用户登录（单管理员面板）；`MonitorPermission` 全树零命中 | **假** |
| 3-8 | 写接口全部校验 `RoleID==管理员`，普通用户调即 `-1` | 无 RoleID、无 JWT claims；写接口只校验 `@login_required`（管理员会话） | **假** |
| 3-9 | （改写）SK5 凭据面板侧只存加密后（或 KV Secret） | **假**：根 README:253 明文“Flask 侧 `sk5.json` 存明文密码…FLMX 的‘凭据只存密文’口径本产品不抄”；原子替换属实（`egress:127 _atomic_write_json` 走 `os.replace`）、永不进日志属实 | 部分（加密宣称假） |
| 1-16 | （改写）config.json 同款“每次安装新建＋600”；sk5.json 已存在则跳过不覆盖 | “每次安装新建”**假**：安装器重装保留旧 config（无 `--token` 沿用旧 token，`install-agent.sh:41-44`），且 3-6 行明言不抄“总是新建覆盖”——本行自相矛盾；sk5.json 安装器根本不碰（零命中），“跳过不覆盖”空洞为真 | 部分 |

**（c）其余文档宣称不符（7 项）**：
- `core/README.md:21` 的 `render_server_conf(proto="udp", port=None, server_dir=None, ca_dir=None)` 缺 `dns`／`allow_port_change` 两参；`panel/README.md` 对接点节同一函数签名缺 `server_dir`／`ca_dir` 两参；实测签名 6 参（core:1043）。两份文档各缺两参、互补漏——修法：两处补全 6 参。
- `cloudflare/README.md:251` “全路由测试（55 项…)”已过期：现 Worker 探针 inputs 23＋Y 13＋bodies 9＋lockout 13＝58 次执行；其中 W7/W8 的畸形体与 lockout L1 的 4 体重合 2 体，去重后 **56 格**（55＝23+13+9+10，是 lockout 探针 10 格时的旧数）。修法：55→56（并注明去重口径），或删具体数字。
- 根 `README:265-280` 卸载指引不完整：只删 NAT POSTROUTING 规则，未清 FORWARD 规则（安装器写入的 `-s/-d 10.8.0.0/24` 两条）与 ufw 放行／路由规则；亦无交互确认。卸载后残留规则 inert（无 tun 设备、无监听端口），故 P2。修法：补 FORWARD 删除命令＋ufw 规则清理（`ufw delete allow 1194/udp` 等）＋删前确认提示。
- `docs/security.md:7` 自测 grep“应为零命中”不成立：`grep -rn "admin123\|changeme\|123456" panel/ agent/` 实测 2 命中（`agent/agent.py:458/463` 的 hex 字符集 `"0123456789abcdef"` 含 `123456` 子串；另 `.pyc` 一处二进制命中）。意图（无默认口令字面量）属实，是 grep 模式过宽。修法：模式加词界或排除字符集行。
- `cloudflare/server-mode.md:21` sent 态行称 Flask“相同（Flask 侧同款约定）”，与 `docs/security.md:12` 的“Worker 侧非幂等命令首超时即标 failed”披露矛盾：Flask `_requeue_stale_sent` 不分动作全重投（含 create_user/init_pki，R5 已查证、定性非 bug、不立案）；Worker 仅 7 个幂等动作可重投。本轮不重立该分歧，只立案 server-mode 的“相同”宣称——修法：该格改写为两端分歧如实写（同 security.md:12 口径）。
- `panel/README.md:23`“所有 `/api/*`（除登录、`/api/me`）均需登录”过宽：`/api/agent/*` 走节点 token 鉴权（`_agent_auth`）、`/api/agent/bundle*` 与 `/install-agent.sh*` 公开（设计如此，见 §1.1）。管理接口须登录本身属实。修法：改写为“管理接口须登录；agent 接口走节点 token；bundle／安装脚本公开”。
- J4 注：根 README 部署方式二称 `--node-name 必带`，与安装器行为一致（缺省用 hostname→poll 401，`install-agent.sh:63`），“必带”是操作要求而非脚本强制——表述无误，不立案。

**（d）不立案的观察（已核实，记入 §6）**：`security.md:12` 的重投分歧披露属实（R5 裁决维持）；`panel/README` 的 `/api/sk5/test` 返回形状与代码一致（抽查）；`agent/README` 的 `create_server` 幂等（core `build_server_cert` 幂等注释 `:632`＋探针）与 `revoke_user` 自动重启（`agent.py:681`）属实；`egress/README` 的 flock 20 秒（`policy-routing.sh:87`）、panel 子进程 30 秒（`sk5_manager._run:185`）属实；`core/README` 的 `OpenVPNManager` 方法表与 CLI（`:1481`、`:1527`）属实；`OPENVPN_PROTO/PORT` 默认 udp/1194（core:71-72）属实。

## §3 全量复扫（历史 141＋R14 的 3＝144 条逐条定性）

复扫宇宙：R14 的 141 条（138 已修＋2 部分＋1 未验，见 AUDIT-R14 §3 复扫合计）＋R14 本轮新发现 3 条＝**144 条**。定性口径与 R14 同款（已修／部分／未验／复发）。

**复扫方法（mtime 对账）**：自 R14 后动过的文件仅 4 个（§0 表：`panel/app.py` BA、`core/openvpn_manager.py` BB、`cloudflare/README.md` BB、`verify-integration.sh` BB）；其余文件 mtime 与 R14 §0 逐项一致，R14 实证沿用（同日、数小时内，复核时效内）。4 个动过文件内的历史项本轮全部行为重验（§1 探针＋变异红证）或逐项代码核对；再叠加 §2 旅程重演对全部阶段的重查。

**§3.1 R14 的 3 条关闭（本轮行为重验，变异红证见 §1.5）**：
- R14-P2-1（坏条目隔离漏吊销／专用下载）：BA 修后 unswept 6/6、r15_sweep 2/2；双层回退变异 m-ba1x 恰红 U1/U2/U3（R14 签名复现）。**已修**。
- R14-P2-2（dns falsy 合并绕过守卫）：BB 修后 r14_dns 6/6、inputs 86/86（D10 新期望复核见 §1.1 注）；回退变异 m-bb1 恰红 D1/D2/D3。**已修**。
- R14-P2-3（cloudflare/README:135 钉位过期）：BB 按 AO 口径删行号只留函数名；回退变异 m-bb2 使钉位重现；全树再扫仅余 README:198 两处区间（承载的哈希一致 invariant 由门禁 §7 按值校验，见 §1.6 的盲区说明——那是新格精度问题，不是钉位复发）。**已修**。
- 另：R14-P2-3 建议的钉位 grep 门禁，BB 裁决不加（理由写 §7 注释 (a)(b)(c)）。复核结论：**裁决成立**——(a) 存在性校验对“行号在范围、内容错位”的失效模式空洞（R14-P2-3 本身就是该模式）；(b) 内容感知校验须解析混杂散文、无统一可机读文法；(c) 消除钉位本身是结构上更强的修法（AO/AZ 先例）。但 §7 新格自身存在 P2-1 盲区（集合级校验对绑定漂移空洞），见 §1.6——裁决的理由成立，不等于替代方案无懈可击。

**§3.2 动过文件内的其余历史项（全部行为重验，本轮探针）**：
- `panel/app.py` 内：R12-P1-1（队列坏条目楔死全通道）——inputs 86/86、adv 28/28、unswept 6/6；R12-P1-2（`port=True` 写坏 conf）——AU 20/20、inputs D 格；R12-P2-1（`bool()` 反向开关）——inputs 全绿；R12-P2-2（udp-over-tcp 读错键）——inputs 全绿；R13-P2-1（垃圾 sent_at 滞留）——inputs H11 格＋lifecycle 8/8；R13-P2-3（下载 verdict 不一致）——download 12/12；R11-P1-1（`?node=` 忽略）——nodeparam 45/45、href 6/6；R11-P2-1（Worker 改密 404）——Worker changepw 501（Y 矩阵）；R12-P2-7（cmd_get 手改条目 500）——inputs 全绿。**全部已修，无一复发**。
- `core/openvpn_manager.py` 内：R13-P2-2（port 合并）——AU 20/20；R13-P2-5（agent `_as_int`，在 agent 文件内，mtime 未动但探针重跑 21/21）；R14-P2-2——r14_dns 6/6；R12-P1-2——同上。**全部已修，无一复发**。
- `cloudflare/README.md` 内：R13-P2-7（flmx 钉位）——全树 grep `SCRIPT_VERSION`／`resolve_version` 正文归零（审计报告除外）；R10-P2-1（文档数字过期）——本轮同族复发两处，见 §2.2(a)（是**新**过期，不是旧项复发：旧三处仍归零）。
- `verify-integration.sh` 内：门禁 29/29（§1.4）＋双变异红证；§7 新格盲区是本轮新发现（§1.6），不是旧项复发。

**§3.3 其余文件内的历史项**：mtime 与 R14 §0 一致，R14 实证沿用；§2 旅程重演逐阶段重查未发现复发信号（J1–J12 行为格除 §2.2 所列文档项外全绿；R8-BUG-1/BUG-2 的 staged 重跑本轮亲自重跑通过，见 §1.3）。

**§3.4 部分与未验（不变）**：P0-3 部分（按设计，部署态未定——Cloudflare 模式待真实部署，见 §5）；P1-7 部分（按设计，首登强制改密永不实现，文档已诚实披露，根 README:260）。P0-1 未验（Cloudflare 真实部署，见 §5）。

**复扫合计：144 条＝已修 141（138＋§3.1 关闭的 3 条）／部分 2（P0-3、P1-7）／未验 1（P0-1）；本轮新发现 2 条另计（R15-P2-1、R15-P2-2，见 §1.6／§2.2）。144＝141＋2＋1；无一复发。**

### §3.5 U-1～U-12 认领表更新（R14 §3.5 → 本轮）

| # | 项 | R15 更新 |
|---|---|---|
| U-1 | P0-1/2/3 部署态 | 仍未验（§5） |
| U-2 | R6-P1-1 真机复现 | 关闭（live-8 headline-5 显式重跑通过） |
| U-3 | UDP 数据面 | 关闭（live-7 S1/S2＋live-8 S2＋live-10 S1/S2 再证 TCP+UDP 均走 SK5） |
| U-4 | R 符号链接自拷 | 关闭（无变化） |
| U-5 | R 逐项失败 die 分支 | **关闭**（live-10 §17 已落盘：U-5a 预检 die exit 1、U-5b 下载 die exit 1、U-5c 中途 kill 后清理重跑成功；三处致败均诚实失败） |
| U-6 | T 两变异 | 关闭（R8 已判；R9 T 变异重跑 17/2/4） |
| U-7 | verify-integration 瞬时红 | 关闭（R9–R14 六次 28/28、R15 29/29 一次过） |
| U-8 | 真机在位升级路径 | 关闭（依据仍为 live-9 headline-9 毒树默认重跑行级比对；live-10 §18 headline-9 尚未落盘，其复核待 live-10 报告补完） |
| U-9 | KV 竞态与 POP 传播 | 仍未验（无部署） |
| U-10 | 前端渲染级核查 | 关闭（live-9／live-10 headline-7 真机渲染通过；本轮静态核查 10/10 与之致，§7） |
| U-11 | easy-rsa 真二进制签发 | 关闭（live-8 headline-2 以 real easyrsa 3.1.0 裁决） |
| U-12 | live-R5 结果 | 关闭 |

## §4 套件重跑汇总（本轮亲自重跑，见 §1）

Flask：inputs 86/86、adv 28/28、nodeparam 45/45、diskfull 5/5、lockout 5/5、download 12/12、changepw 7/7、lifecycle 8/8、unswept 6/6、env 3/3、href 6/6；Core 19/19、AU 20/20、r14_dns 6/6；Agent 21/21；Worker：inputs 23/23、Y 矩阵 13/13、r14_worker_bodies 9/9、AY lockout 13/13（注：裸跑默认指旧树 `/tmp/r13/tree` 会 8/5——探针头写明须 `R13_TREE=<现树>`；设 `R13_TREE=/tmp/r15/tree` 后 13/13，见 §1.1）；门禁 29/29；staged 安装三跑一次通过（§1.3）。新树上全部绿；变异树上对应格子红（§1.5、§1.6）。

探针资产清单（/tmp 资产，路径写进报告以备重建——/tmp 可能被清空，见任务要求）：

| 套件 | 文件 | 格数 | 本轮结果 | 变异红证 |
|---|---|---|---|---|
| Flask 输入枚举 | `/tmp/r13-tests/r13_inputs.py` | 86 | 86/86（D10 新期望见 §1.1 注） | m-bb1（D1/D2/D3）、m-aw1（H11） |
| Flask 对抗 | `/tmp/r13-tests/r13_adv.py` | 28 | 28/28 | m-aw1（Q3） |
| Flask 节点参数 | `/tmp/r13-tests/r13_nodeparam.py` | 45 | 45/45 | — |
| Flask 磁盘满 | `/tmp/r13-tests/r13_diskfull.py` | 5 | 5/5 | — |
| Flask 登录锁 | `/tmp/r13-tests/r13_lockout.py` | 5 | 5/5 | — |
| Flask 下载 | `/tmp/r13-tests/r13_download.py` | 12 | 12/12 | m-aw2（R14 树沿用） |
| Flask 改密 | `/tmp/r13-tests/r13_changepw.py` | 7 | 7/7 | — |
| Flask 生命周期 | `/tmp/r13-tests/r13_lifecycle.py` | 8 | 8/8 | — |
| Flask 未扫队列 | `/tmp/r14/r14_unswept.py` | 6 | 6/6 | m-ba1x（U1/U2/U3） |
| Flask 扫队列层 | `/tmp/r13-tests/r15_sweep.py`（本轮新写） | 2 | 2/2 | m-ba1x-sweep-only（S1/S2） |
| Flask 环境变量 | `/tmp/r13-tests/r13_env.py` | 3 | 3/3 | — |
| 前端 withNode | `/tmp/r13-tests/r13_href.mjs` | 6 | 6/6 | — |
| Core | `/tmp/r13-tests/r13_core.py` | 19 | 19/19 | — |
| Core AU | `/tmp/r13-tests/r13_au.py` | 20 | 20/20 | m-ax1（R14 树沿用） |
| Core dns | `/tmp/r14/r14_dns.py` | 6 | 6/6 | m-bb1（D1/D2/D3） |
| Agent | `/tmp/r13-tests/r13_agent.py` | 21 | 21/21 | m-ax2（R14 树沿用） |
| Worker 输入 | `/tmp/r13-tests/r13_worker_inputs.mjs` | 23 | 23/23 | m-ay1（W7/W8，R14 树沿用） |
| Worker Y 矩阵 | `/tmp/r13-tests/r13_worker_y.mjs` | 13 | 13/13 | — |
| Worker bodies | `/tmp/r14/r14_worker_bodies.mjs` | 9 | 9/9 | — |
| Worker 锁 | `/tmp/r13-tests/ay_lockout.mjs` | 13 | 13/13（须 `R13_TREE=/tmp/r15/tree`） | 旧树对照 8/5（AY 签名） |
| 门禁 | `verify-integration.sh`（树内） | 29 | 29/29 | gate-mutant（status 格）、gate-mutant2（§7 格）、**m-gate-swap 应红而绿（§1.6）** |
| staged 安装 | 树内 `install.sh`（unshare 隔离） | 3 跑 | 默认 EXIT=0、10.9 EXIT=1、毒树重跑 EXIT=0、ufw 2000 条 EXIT=0 | AN 旧版对照（R14 树沿用） |

合计探针格 366（Flask 213＋Core 45＋Agent 21＋Worker 58＋门禁 29；§1.5 的“Flask 202”是 inputs～unswept 九套件小计，sweep 2＋env 3＋href 6 另列于 §1.1／§1.3）＋staged 安装 3 跑。变异树：`/tmp/r15/mutants/`（m-ba1／m-ba2／m-ba1x／m-ba1x-sweep-only／m-bb1／m-bb2／m-gate-swap，构建器 `/tmp/r15/build-mutants.py`＋`build-mutants2.py`）；R13/R14 旧变异树见 §0（`/tmp/r13/mutants/`、`/tmp/r14/mutants/`）。

## §5 P0 部署态重验（Cloudflare 真实部署，仍未验）

- 本轮 `wrangler deploy --dry-run` 通过（绑定显示 `env.PANEL_KV (REPLACE_WITH_KV_NAMESPACE_ID)`，`--dry-run: exiting now`）。
- 真实部署仍阻塞（与 R8–R14 同款卡点，未变）：`wrangler.toml` 的 KV `id`／`preview_id` 仍为占位符；需用户创建 Cloudflare API token 或交互式 `wrangler login`；需 `wrangler secret put ADMIN_PASSWORD`＋`AGENT_BUNDLE_ORIGIN`。用户决断已问五次未复。
- 结论：P0-1／P0-2／P0-3 部署态**仍未验**。交付文档须把 Cloudflare 模式部署态标未验（cloudflare/README 已有此口径，见 §6）。本轮不重复 P0 立案（已登记）。

## §6 文档宣称全量核对（9 份交付文档）

| 文档 | 核对结果 |
|---|---|
| 根 README.md | 基本属实；3 处问题：`:226` 门禁 28 过期、`:251` 工具栏逐字 class 宣称假、`:198` 哈希块“逐字节一致”由门禁集合校验弱执行（§1.6）。其余抽查属实（安装步骤 1–8、重装保留、SK5 明文口径、改密不强制、FLMX 对齐要点多处与 flmx 表矛盾处以根 README 为准）。 |
| panel/README.md | 基本属实；3 处问题：`:23` 登录覆盖过宽、render 签名缺两参、（API 表其余抽查属实：change-password `ok, note`、users 字段、`ovpn_url`、P01 500、legacy 重建）。 |
| cloudflare/README.md | 2 处问题：`:251` 55 项过期、`:135` 钉位已修（BB）。其余属实（部署步骤含 KV id 回填、AGENT_BUNDLE_ORIGIN 503、KV 键表、明文取舍）。 |
| cloudflare/server-mode.md | 1 处问题：`:21` sent 态“相同”与 security.md:12 矛盾。其余属实（13 动作、`?node=` 优先级、快照形状、30 秒在线、POP 传播、明文存 KV）。 |
| core/README.md | 1 处问题：`:21` render 签名缺 `dns`／`allow_port_change`。其余属实（方法表、CLI、环境默认、RESERVED_NAMES）。 |
| agent/README.md | 抽查全属实（--force/--ca-cert/--insecure、--once 退出码、退避 5s→60s、`create_server` 幂等、`revoke_user` 自动重启、config.json 字段）。 |
| egress/README.md | 2 处问题：`:210` 28/28 过期；其余属实（flock 20 秒、子进程 30 秒、`do_status` 形状——抽查）。test-egress.sh §6 矩阵 R9 沿用，本轮未重跑（与 R14 同款记明）。 |
| docs/security.md | 2 处问题：`:7` 自测 grep“应为零命中”实测 2 命中（模式过宽）；其余属实（会话 12h、`Secure` 门控、限流 5/5/15 分钟、重投分歧披露、密码 bcrypt＋回落）。 |
| docs/flmx-reference.md | **13 行“照抄”无实现＋4 行部分实现＋3 行改写行机制不实**（§2.2(b) 全表）；其余 15 行“照抄”属实。根 README 的 FLMX 对齐要点已在 3 处（1-11、3-1、3-9）明文纠正 flmx 表，本表未同步。 |

## §7 前端对比度核查

`python3 panel/static/contrast-check.py`：**10/10 PASS**（底线 4.5），目标 7 达成 4/10——与 R10–R14 同款。交叉验证：live-10 headline-7 真渲染（CDP 驱动，1440×900）：可见文字 181 个，低于 4.5 者 0 个，最薄 4.92（成功绿字 #15803d），JS 异常 0 个。两路一致。观察（不立案，live-10 同款）：面板未提供 `/favicon.ico`（每次进站一条 404）；测试机 headless 环境中文呈豆腐块（缺 CJK 字体，非产品问题）。

## §8 结论

### §8.1 verdict

**不能交付，差集 2 条（P2×2）**：

| 编号 | 级别 | 机制 | 复现／证据 | 修法 |
|---|---|---|---|---|
| R15-P2-1 | P2 | 门禁 §7 格只比无标签哈希集合，标签→哈希绑定漂移照样过门禁；根 README:198 宣称的“逐字节一致”未被执行 | 变异树 `/tmp/r15/mutants/m-gate-swap`（agent.py sing-box amd64/arm64 哈希互换）：门禁仍 29/29，§7 格明文 PASS；两文件集合逐项相同、绑定已错 | 按标签比对（install.sh 命名赋值 vs agent.py `_PINNED_SHA256` 字典逐键相等）；注释宣称与判定对齐 |
| R15-P2-2 | P2 | 交付文档多处宣称与行为不符（文档同族复发） | 枚举见 §2.2：门禁计数过期 2 处、flmx 表 32 行“照抄”中 13 假＋4 部分＋3 改写行机制不实（且 3 处与根 README 既定口径直接矛盾）、Worker 55 项过期、render 签名两文档各缺两参、卸载指引缺 FORWARD/ufw 清理、security.md 自测 grep 2 命中、server-mode sent 态“相同”与 security.md:12 矛盾、panel/README 登录覆盖过宽 | 改文档对齐行为（AO/AZ 先例，不动产品代码）：数字改 29／56、签名补全、flmx 表假行改“未抄（待定）”或删宣称、卸载补清理命令、自测 grep 加词界、server-mode 改写分歧 |

P 级说明：两条均为 P2——P2-1 的后果是安装时 fail-closed（非静默损坏），P2-2 是文档失真（误导首次交付用户与后续修复路，无行为损坏）。无 P0/P1 新发现。BA/BB 修复本身全部行为验证通过（§1，变异红证齐全）；历史 144 条无一复发（§3）。

### §8.2 live-10 对账（只认已落盘文字，不代判）

live-10 报告 `docs/live-verify-R10.md`（210 行）**未完工**：§§1–17 已落盘（S0–S4、R13 七条真机格、headline-1～headline-8 全部通过：毒包安装一次成功、R13 七条真机关闭、D13 并发安装胜者干净成功／败者死于 apt 锁零写盘、U-5 三处致败均诚实失败）；**§18 headline-9、§19 新 bug 与观察项、§20 结论与机器终态仍为“待填”**，其头部“headline-1～9 全过、新 bug 0 条”的结论句与正文未完工状态不一致，以正文为准。本轮不代判 live-10 的最终结论。
- live-10 已确认的事实（可引用）：R13 的 7 条在真机上全部关闭；历史问题无一复发；前端真渲染 181 字 0 项低于 4.5；D13 的实测冲突形态是 apt 锁早夭（安装器无安装锁，败者零写盘——live-10 定性不立案，属操作失误，R15 不重立）。
- **R14 的 3 条真机格不在 live-10 简报内**（任务已明），须下一轮 live 对账；**R15 的 2 条**（门禁格精度、文档）亦须下一轮 live 对账（P2-1 的绑定错位后果是 agent 侧安装校验失败，须真机 amd64/arm64 双架构格验证；P2-2 为文档项，真机格不适用，改后 grep 复核即可）。
- 未验（与 live-10 头部一致）：Cloudflare 真实部署（P0-1/2/3）、SK5 真实 IPRoyal 端口（1001 vs 9000，用户未确认）。

### §8.3 未验清单

- P0-1/2/3：Cloudflare 真实部署（§5）。
- SK5 端口 1001 vs 9000：用户未确认（面板默认 1001，文档已注“端口待确认”）。
- 沙箱数据面：UDP/TUN 均 EPERM，OpenVPN 数据面行为只在真机验（live-10 S1/S2 已验直连＋SK5；R15 新增项无数据面）。
- live-10 §§18–20 待填（§8.2）。
- test-egress.sh §6 矩阵：R9 沿用，本轮未重跑。

### §8.4 方法自述

本轮方法（交付文档驱动的用户旅程重演）强在文档宣称与行为的逐项对账（§2.2 的 flmx 全表即其产出），弱在真机数据面（沙箱 EPERM，一律记未验、不冒充）与 Cloudflare 真实部署（缺用户侧凭证与决断）。单审计员，未派子代理；探针全部在 `/tmp` 副本上跑，未动项目原文件（除本报告）与任何真机。以下裁决沿用，不重立：R5 的 Flask/Worker 重投分歧（非 bug，security.md:12 已披露）；BB 的钉位 grep 门禁不加裁决（§3.1 复核成立）；live-10 的 D13 apt 锁不立案；AS 的 0/1-int 布尔强制（R12 探针钉死）；AW 的快照时效性（与 `?node=` 分支同款属性）；P1-7 首登改密不做（按设计）。

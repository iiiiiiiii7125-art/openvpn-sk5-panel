# AUDIT-R3 — 全量全局回头看（交付前）

- 审计员：独立审计路（未参与建设与修复路 A–J）
- 日期：2026-11-12（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树 37 文件 / 9309 行（与 R1 同等广度）
- 推导方法：**宣称驱动**（与 R1 逐文件通读、R2 旅程推导均不同）——从所有对外宣称出发逐条证伪：根 README 与各 README/docs 的每一句功能宣称、A–J 各路报的每一条“修好”、live-verify 与 live-verify-R2 的每一句“修好/通过”。每条宣称独立重跑实证（不只读修复代码）；证伪的立案，证实的写清实证方法。
- 语法基线：4 个 Python 文件 `py_compile` 全绿；7 个 shell 脚本 `bash -n` 全绿；Worker `node --check` 全绿。
- 测试一律在 `/tmp` 副本与 /tmp 套件上跑；未动项目原文件、未动 /etc、未动任何真机。

## 一句话裁决

**不能交付。P0 0 条；P1 2 条必须先修**：① Worker 的 sent 态重投无上限（`docs/security.md` 所称“与 Worker 侧约定一致、最多重投 3 次”是假宣称，死 agent 的命令在 Worker 侧永远循环、永不标失败）；② 根 README 与 `agent/README.md` 仍在教用户用旧的一键命令装 agent（`curl -fsSL … | bash`，无 `--node-name`、无 `-k`、无 sha256 校验），按字面照做在自签面板上第一步就失败。另有 P2 14 条（多为文档过时与两端小不一致）。修完 P1 后，改动面须按第一前提①再做一次全量全局回头看才能交付。

## 实证总览（本轮自写套件，全部独立重跑）

| 套件 | 位置 | 结果 |
|---|---|---|
| Flask 面板 | `/tmp/audit3-tests/flask_suite.py` | 62/62 PASS |
| Worker（mock KV + mock 源站） | `/tmp/audit3-tests/worker_suite.mjs` | 50/50 PASS |
| Worker 1-25 守卫 | `/tmp/audit3-tests/worker_125.mjs` | 3/3 PASS |
| Worker 重投上限（反证） | `/tmp/audit3-tests/worker_requeue.mjs` | 5 个超时周期仍循环、永不失败（R3-P1-1 实证） |
| Flask 重投上限 | `/tmp/audit3-tests/requeue_flask.py` | 3 次重投后标 failed（与 Worker 不一致的实证） |
| core（解析器/证书/端口锁/easyrsa） | `/tmp/audit3-tests/core_suite.py` | 29/29 PASS |
| agent（白名单/钉死哈希/set_sk5/--once） | `/tmp/audit3-tests/agent_suite.py` | 19/19 PASS |
| egress（set_sk5/健康检查/真实 sing-box check） | `/tmp/audit3-tests/egress_suite.py` | 20/20 PASS |
| 前端安装命令生成器 | `/tmp/audit3-tests/frontend_cmd.mjs` | 7/7 PASS |
| policy-routing（桩 ip/iptables，命名空间内跑） | `/tmp/audit3-tests/policy_test.sh` | 6 腿全过（幂等/from-all 拒/停用/restore 开/关） |
| install-agent.sh 端到端（假自签面板 + 挂载命名空间，/etc 与 /opt 均未动） | `/tmp/iae2e/run_e2e.sh` + `run_e2e_dl.sh` | 两分支全过：本地包分支与下载分支，TOFU 钉证书 + 自检 OK + bundle sha256 OK，退出 0 |
| 审计脱敏（cmd 明细/审计日志/节点列表） | 内联 probe | 4/4 无密码·token 泄露 |
| 真实 sing-box 1.11.15 | 下载后验钉死哈希 | sha256 与钉死值逐字节一致，`sing-box check` 对渲染配置（有/无认证）均通过 |
| verify-integration.sh 基线 | `bash verify-integration.sh` | 20/20（PASS=20 FAIL=0 SKIP=0） |
| verify-integration.sh 变异（status() 恒 500） | `/tmp/audit3-mut` | 19/1，变红的正是“登录后 GET /api/status”格 |
| verify.sh 基线（沙箱） | `bash verify.sh` | PASS=5 FAIL=5（环境缺件） SKIP=11 |
| verify.sh 变异（删 `systemd/openvpn-sk5-healthcheck.timer`） | `/tmp/audit3-mut` | files 格变 FAIL（PASS 5→4，FAIL 5→6） |

## 新发现

### R3-P1-1 — Worker 的 sent 态重投没有上限；`docs/security.md` “与 Worker 侧约定一致” 是假宣称

- 严重度：P1（必须修）
- 文件：`cloudflare/src/index.js:555-578`（`handleAgentPoll` 超时处理）；`docs/security.md` “命令重投”行
- 机制族：sent 态重投（P1-6 同族）
- 复现：mock KV，节点 n1，下发 `get_status`，poll 取走（sent），把 `sent:n1` 的 `sent_at` 回拨到 200 秒前，再 poll；重复 5 个超时周期。
- 实测输出：5 个周期每次都重新下发（`redelivered: true`），命令状态始终 `sent`，第 5 个周期后仍不是 `failed`。`grep -n "retries\|MAX_RETR\|requeue_count" cloudflare/src/index.js` 零命中；唯一一次出现 `requeue` 是 `cmd.requeued_at = now`（:564），没有任何计数器或上限。
- 对照：Flask 侧 `panel/app.py:484-518`（`SENT_MAX_RETRIES = 3`）实测：3 次重投后第 4 个超时周期标 `failed`（`/tmp/audit3-tests/requeue_flask.py` 实证）。security.md 称“与 Worker 侧约定一致”——不成立。
- 影响：Cloudflare 模式下 agent 一死，幂等命令（`get_status`/`test_sk5`/启停等）每 120 秒被重新下发、永不收敛；面板上永远看不到“已放弃”，操作员得不到死 agent 的诚实信号（违反“失败须诚实呈现”）。
- 修法建议：Worker 侧照 Flask 口径补 `retries` 计数 + 3 次上限后标 `failed`（与 `sent:<name>` 副本一并清理），或改文档承认两端不一致并说明 Worker 侧的收敛方式。

### R3-P1-2 — 根 README 与 `agent/README.md` 仍在教旧的一键安装命令：无 `--node-name`、无 `-k`、无 sha256 校验

- 严重度：P1（必须修）
- 文件：`README.md:94`；`agent/README.md:18`
- 机制族：安装命令拼装（新家族）
- 复现：按字面执行 `curl -fsSL https://<面板>/install-agent.sh | bash -s -- --panel-url https://<面板> --token <节点TOKEN>`。
- 实测：① 默认自签面板上 `curl -fsSL`（无 `-k`）TLS 校验即失败（curl exit 60），脚本一步都跑不起来——正是 R2-BUG-11/12 的故障形态，H/J 只修了面板生成的命令，没修这两处文档；② 即使面板是可信证书，缺 `--node-name` 时 agent 默认用 hostname 注册，poll 恒 401（R2-BUG-12 的故障形态）。
- 对照：面板生成的命令（Flask 前端 `buildInstallCommand`、`Worker installCommand`）已是两步走 `-k` + `sha256sum -c` + `--node-name`（本轮前端 7/7、Worker 50/50 实证），文档与实现脱节。
- 修法建议：两处均改成与面板生成命令同口径的两步命令（含 `--node-name '<节点名>'`）。

### R3-P2-1 — `cloudflare/server-mode.md:17` 称 Flask 有 `POST /api/nodes/<名>/install` 接口，是假宣称

- 严重度：P2
- 文件：`cloudflare/server-mode.md:17`（“同接口（Flask 版，`panel/app.py` 已实现；见下）”）；`docs/flmx-reference.md:37`（1-10 行“已实现：`POST /api/nodes/{id}/install` 返回 fail-closed 命令模板”，未限定面板）；`docs/audit/AUDIT-R2.md:160`（P2-13 行“1-10 已落实”承袭此说）
- 机制族：安装命令拼装
- 复现：Flask 测试客户端 `GET /api/nodes/lightsail/install` → 404；`grep -n "install_command" panel/app.py` 零命中；全树只有 Worker（`index.js:1031`）与前端回退有该逻辑。
- 影响：用户实际未被阻塞——前端“复制安装命令”按钮调该接口失败后 catch 回退到本地 `buildInstallCommand`（`index.html:899-903`），仍能拿到正确命令。但文档与上一轮审计结论均失实。
- 修法建议：server-mode.md 与 flmx-reference 1-10 改为“仅 Worker 有该接口；Flask 侧由前端 `buildInstallCommand` 就地拼装”。

### R3-P2-2 — `README.md:237` 称 `/api/sk5/fail-open` 与 `/api/sk5/udp-over-tcp` 在 `app.py` 里“实际不存在”，反向为假

- 严重度：P2
- 文件：`README.md:237`；`panel/app.py:1379`（fail-open）、`:1398`（udp-over-tcp）
- 机制族：文档过时
- 复现：Flask 套件 `POST /api/sk5/fail-open` 与 `POST /api/sk5/udp-over-tcp` 均 200（62/62 套件内）；`panel/README.md` 的路由表列出这两条是对的。
- 修法建议：删掉 README.md:237 的后半句，改为两条路由已存在（`panel/README.md` 表为准）。

### R3-P2-3 — `README.md:253/256` 称密码哈希是加盐 SHA-256、“待对齐” bcrypt，已过时

- 严重度：P2
- 文件：`README.md:253`（“当前 Flask 面板密码哈希是加盐 SHA-256……待对齐”）、`:256`（“待对齐项……换 bcrypt 须改 `_hash_password`/`_check_password` 并做存量哈希迁移。发版前应补齐”）
- 机制族：文档过时
- 实证：`panel/app.py:251-258` 已是 bcrypt 为主、SHA-256 回退 + 登录成功时透明迁移；Flask 套件验到 bcrypt `$2b$` 哈希格式。
- 修法建议：两处改写为 bcrypt 已落地（SHA-256 仅为极简环境回退与存量迁移）。

### R3-P2-4 — `README.md:72` 安装步骤 4 的复制清单漏了 `agent/`（与 `verify-integration.sh`）

- 严重度：P2
- 文件：`README.md:72`（“复制 `core/`、`egress/`、`panel/` 到 `/opt/openvpn-sk5-panel/`”）
- 机制族：文档过时
- 实证：`install.sh:343-344` 已复制 `agent/`（R2-BUG-10 修复）；`verify.sh` 的 `install-copies-agent` 格 PASS；install-agent e2e 装出的树含 `agent/agent.py`。
- 修法建议：清单补 `agent/`（与 `verify-integration.sh` 若随包走）。

### R3-P2-5 — `cloudflare/README.md:200` “源站暂未提供 `.sha256` 时明示警告后继续”已过时

- 严重度：P2
- 文件：`cloudflare/README.md:200`；`cloudflare/src/index.js:407-414`（J Lane 后 `installCommand` 为 fail-closed，无 warn 分支）
- 机制族：安装命令拼装
- 实证：Worker 套件验到 `install_command` 含 `sha256sum -c` 且无 `WARN`；`grep WARN cloudflare/src/index.js` 在安装命令路径上零命中。
- 修法建议：改写为“`.sha256` 必须取到且校验通过才执行，缺失即停”。

### R3-P2-6 — `cloudflare/README.md:207` 的轮询地址写成 `http://`，实际面板只跑 HTTPS

- 严重度：P2
- 文件：`cloudflare/README.md:207`（`http://<服务器 IP>:8443/api/agent/poll`）
- 机制族：文档过时（R2-P2-4 同族残留；R2 修了 server-mode.md，漏了此处）
- 实证：`panel/app.py` 只监听 HTTPS 8443；agent 侧 `panel_url` 必须走 HTTPS（仅 loopback http 例外）。
- 修法建议：改为 `https://`。

### R3-P2-7 — `docs/flmx-reference.md` 1-13 与 §103 仍是 J Lane 之前的口径

- 严重度：P2
- 文件：`docs/flmx-reference.md:40`（1-13 行“源站暂未提供 `.sha256` 时明示警告后继续”）、`:103`（“有 `.sha256` 即验、验不过即停”）
- 机制族：安装命令拼装
- 实证：同 R3-P2-5，J Lane 后安装命令是强制校验（缺失即停），“有即验”是旧语义；另 §103 称“一键安装命令 = 版本解析 + secret + 地址归一 + sha256 fail-closed”——OpenVPN 安装命令里并无“版本解析”步骤（版本钉在 bundle 的 sha256 上，无解析动作），该句对 FLMX 的描述搬过来时未对齐。
- 修法建议：1-13 与 §103 按 J Lane 后的强制校验改写；删掉或限定“版本解析”。

### R3-P2-8 — `panel/README.md:59` 称 `render_server_conf` “只认 proto/port”已过时

- 严重度：P2
- 文件：`panel/README.md:59`；`core/openvpn_manager.py:722`（`render_server_conf(..., allow_port_change=False)`）
- 机制族：文档过时
- 实证：Flask 套件验到不带 `allow_port_change` 改端口 → 500（P01），带上 → 200 且 `server.conf` 变 tcp/443。
- 修法建议：补 `allow_port_change` 参数说明与 P01 口径。

### R3-P2-9 — `panel/README.md:81/89` 称 `check_health()` “面板暂未轮询 / 未接入面板轮询”已过时

- 严重度：P2
- 文件：`panel/README.md:81`、`:89`
- 机制族：文档过时
- 实证：`systemd/openvpn-sk5-healthcheck.{service,timer}` 在树内，`install.sh:644-645` 安装并启用；egress 套件验到健康检查两分支（kill-switch 黑洞 / fail-open 回直连）与 `health.json` 落盘。
- 修法建议：改写为 timer 每 60 秒轮询，`last_health` 经 `get_status` 回显。

### R3-P2-10 — `cloudflare/src/index.js:43-44` 注释称 agent 的 `action_set_sk5` “首行即要求 host+port”，已过时

- 严重度：P2
- 文件：`cloudflare/src/index.js:43-44`
- 机制族：set_sk5（注释与实现脱节）
- 实证：`agent/agent.py:675-700` 的 `action_set_sk5` 是部分合并（host/port 均可缺，缺失即保留存量）；agent 套件验到单字段 `{"enabled": false}` 成功且 host/port 保留。Worker 仍发全量字段，行为无碍，但注释会误导后人把 Worker 改回“必须全量”。
- 修法建议：注释改为“agent 已是部分合并；Worker 仍发全量是纵深防御”。

### R3-P2-11 — Worker 的节点轮换返回 201，Flask 返回 200

- 严重度：P2
- 文件：`cloudflare/src/index.js:522`（`handleRotateNode` 返回 `json(..., 201)`）；对照 Flask 套件 rotate 200
- 机制族：两端小不一致
- 实测：Worker 套件 rotate → 201 + 新 token + 安装命令均正确；前端 `api()` 只判 `res.ok`（201 亦为 ok），无功能影响。
- 修法建议：轮换改回 200（非创建操作）。

### R3-P2-12 — Worker 的 agent poll 忽略 body 里的 `node_name`，Flask 则 401

- 严重度：P2
- 文件：`cloudflare/src/index.js:546-548`（`handleAgentPoll` 只认 Bearer token，不读 body `node_name`）；对照 Flask 套件“poll 错节点名 → 401”
- 机制族：两端小不一致
- 实测：Worker 套件 `POST /api/agent/poll {"node_name": "wrong"}` + 正确 token → 200（命令照常下发，归属以 token 为准）；Flask 同条件 → 401。
- 影响：Worker 模式下 agent 配错 `--node-name` 不会 loud 失败，命令仍按 token 归属下发；面板上节点名与 agent 自认名字可能错位，排障信号弱于 Flask。
- 修法建议：两端统一（建议 Worker 也校验 `node_name` 与 token 归属，不符 401；或文档写明 Worker 不校验）。

### R3-P2-13 — 两份安装命令生成器只给 `nodeName` 加 shell 引号，token 与 panelUrl 是裸插值

- 严重度：P2
- 文件：`panel/templates/index.html:822-831`（`buildInstallCommand`）；`cloudflare/src/index.js:407-414`（`installCommand`）
- 机制族：安装命令拼装
- 实测：前端提取测试验到 token 含 `;` 时原样进入命令（`--token x;id` 未加引号）；nodeName 含单引号时正确转义。两份生成器同形。
- 影响：目前安全仅靠“token 是服务端生成的、字母表安全”（Flask `token_urlsafe`、Worker `randomHex`）与 panelUrl 来自受信输入；一旦 token 生成字母表或 panelUrl 来源放宽，即成命令注入面。
- 修法建议：三处统一用 `shellQuote`（token、panelUrl、nodeName）。

### R3-P2-14 — `egress/README.md:125-135` 的 fail-open 说明未明文写出单向性

- 严重度：P2
- 文件：`egress/README.md:125-135`；`egress/sk5_manager.py:714-751`（`check_health`）
- 机制族：fail-open（R2-P2-7 残留）
- 实证：egress 套件验到 fail-over 后 `enabled=False` 持久化；README 只写了“故障时 `check_health()` 执行 `disable()` 撤掉 table 100”，未写“fail-over 后须人工重开才恢复链路”。
- 修法建议：补一句“fail-over 是单向的：触发后 `enabled` 保持 False，SK5 恢复后也不会自动重建链路，须在面板上人工重开”。

## 观察（不立案）

- `agent/install-agent.sh` 自检分支（约 :274-291）：从下载文件运行时取不到面板 `/install-agent.sh.sha256`（旧面板）仍只警告后继续。这是注释中明文记载的设计（bundle 本身仍 sha256 fail-closed；推荐命令先做 `sha256sum -c`），与 J Lane 改掉的 Worker 生成命令 warn 分支是两回事，不立案。
- R2 备注“`cachedStatus` 读 `status:` 不做二次归一化，旧形快照须等下次上报才刷新”（AUDIT-R2.md:137）：Worker 从未真实部署过，线上不存在旧形快照；本轮 Worker 套件验到心跳与回执快照写入时已归一化（`egress.ip`、`online_users`），无 live 影响。
- Worker token 为 65 字符（`randomHex(16)-randomHex(16)`），Flask 为 43 字符（`token_urlsafe(32)`）：两端格式不同，但 token 全程不透明传递，无互操作影响。
- Flask 的 `/api/me` 无 `@login_required`（任意人可查 `admin` 布尔值）：与 R1 设计一致（仅作“是否已登录”探针），不立案。

## 全集复扫表 A — AUDIT-R1 的 33 条（逐条复验）

证据代号：S=本轮套件实证；C=本轮代码核对；L=此前真机实证（live / live-R2，R3 未重跑真机）；D=文档核对。

| ID | 结论 | 证据 |
|---|---|---|
| P0-1 202 当成功 | ✓ 已修 | S：前端 `apiWait` 只在 `queued+cmd_id` 时轮询 `waitCmd` 至 done/failed；10 个写操作全走 `apiWait`；Worker 套件 202 语义 50/50 |
| P0-2 单字段 set_sk5 必败 | ✓ 已修 | S：Worker fail-open 无存量 400 / 有存量 202 且 poll 带全量 host+port；Flask 单字段 200/400；agent 部分合并 19/19 |
| P0-3 Worker 无 bundle/安装脚本路由 | ✓ 已修 | S：无源站 503；有源站 200；篡改包 502；Flask bundle 200 + sha256 与字节一致 |
| P0-4 SK5 密码保存清空 | ✓ 已修 | S：Flask 空密码保留、clear_password 清除；egress 同款 20/20 |
| P0-5 secret.key 随树发货 | ✓ 已修 | S+C：树内无 secret.key；`.gitignore` 含 `panel/data/`；install.sh 删 shipped key 并生成新 key |
| P1-1 status 耗时 20 秒 | ✓ 已修 | C：`panel/app.py:892-893,976-978` 注释与代码——SK5 启用时复用 `get_status()` 已探到的 egress_ip，不再双探针 |
| P1-2 无节点/agent 界面 | ✓ 已修 | S：verify-integration 20/20 含“UI 含入站卡/SK5 卡”与节点注册/轮换/吊销全链 |
| P1-3 Worker 登录无限流 | ✓ 已修 | S：Worker 套件 5 次 401 后第 6 次 429 + Retry-After，异 IP 不受影响；Flask 同款 62/62 |
| P1-4 Worker 无吊销/轮换 | ✓ 已修 | S：Worker rotate 201 新 token 生效、旧 token 401；revoke 后 401 |
| P1-5 Worker 快照形状错位 | ✓ 已修 | S：心跳快照 → `egress.ip` 归一、`online_users`=clients 长度、`via_sk5`、servercfg 补 proto/port |
| P1-6 sent 态无重投 | ◐ 部分 | S：重投本身两端都通（Flask 3 次后 failed；Worker 每次重下发）。但 Worker 无上限 → 新立案 R3-P1-1 |
| P1-7 无改密接口 | ✓ 已修 | S：API 全套（错旧 401/弱 400/同旧 400/成功 200/旧会话失效）+ 前端 `changePwBtn` 与 `change-password` 入口在位 |
| P1-8 check_health 死开关 | ✓ 已修 | S：timer+service 在树内且 install.sh 安装；egress 套件两分支 + health.json 落盘 |
| P1-9 策略路由无持久化/重跑覆盖 SK5 | ✓ 已修 | S：policy `restore` 两腿（enabled=true 重建 / false 不动）；C：install.sh:796-797 读存量 sk5.json 判模式 |
| P1-10 create_server 不幂等 | ✓ 已修 | S：core 套件同 proto/port 重渲染通过；异端口无 allow 拒、有 allow 通 |
| P1-11 入口端口无占用检查 | ✓ 已修 | S：core 套件——占用 UDP 1195 渲染拒；既有端口改口无 allow 拒、有 allow 通 |
| P1-12 UoT 探针密码写 /tmp 明文 | ✓ 已修 | C：`egress/sk5_manager.py:439-445`——探针用 `mkdtemp` 唯一目录（0700，配置 0600） |
| P1-13 systemctl 无超时/保护 | ✓ 已修 | S：core 套件——PATH  stripped 无 systemctl 时 `server_status` 不抛、running False |
| P1-14 server-mode.md 过时 | ◐ 部分 | D：http:// 已全改 https；但 :17 的 Flask /install“已实现”是假宣称 → 新立案 R3-P2-1 |
| P1-15 Worker set_sk5 假宣称 | ✓ 已修 | S：Worker 全量覆盖语义实证；仅头注释过时 → R3-P2-10 |
| P2-1 限流进程内内存/无 ProxyFix | ✓ 已修 | C：SQLite `login_attempts` 表（`panel/app.py:220,380-401`）；`OVPN_TRUSTED_PROXY=1` 才启用 ProxyFix（:177-178） |
| P2-2 agent 不校验 sing-box 版本 | ✓ 已修 | C：`agent/agent.py:500`——已装版本含 `SINGBOX_VERSION` 才保留，否则重装 |
| P2-3 --once 失败仍返回 0 | ✓ 已修 | S：agent 套件——不可达面板 --once 退出 1 |
| P2-4 bundle 确定性不完全 | ✓ 已修 | S：Flask 套件——两次打包字节相同；sha256 端点与字节一致 |
| P2-5 密码哈希 SHA-256 非 bcrypt | ✓ 已修 | S：bcrypt `$2b$` 格式 + 透明迁移；仅 README 措辞残留 → R3-P2-3 |
| P2-6 OVPN_DNS 被忽略 | ✓ 已修 | C：`render_server_conf` 取 `dns or OVPN_DNS or 默认`（`core/openvpn_manager.py:722` 附近） |
| P2-7 PANEL_ADMIN_PASSWORD_FILE 无人读 | ✓ 已修 | C：`install.sh:436-437,452`——密码改由面板首启生成写 admin.pass，旧变量已废弃并注明 |
| P2-8 健康门禁把密码放 curl -d argv | ✓ 已修 | C：`install.sh:746-762`——密码写 0600 文件走 `--data @file`，用后删除 |
| P2-9 init_pki force 无二次确认 | ✓ 已修 | C：`agent/agent.py:595-602`——force 须同时传 `confirm=true` 否则拒 |
| P2-10 .ovpn 下载不校验用户状态 | ✓ 已修 | C：`panel/app.py:1178-1200`——先查状态，吊销 403、不存在 404 |
| P2-11 UoT 固定 /tmp 路径 + manifest 无条目即 raise | ✓ 已修 | C+S：探针改 `mkdtemp`；`_expected_sha256` 轮询三 manifest，无条目才 raise（不可达 manifest 实测 raise） |
| P2-12 两处文档过时 | ✓ 已修 | D：security.md 残留 #1 已改 fail-closed 口径；README bundle.sha256 已注明“已于 2026-11-12 补上” |
| P2-13 flmx-reference 多项未落地/过时 | ◐ 部分 | D：1-13/§103 的旧口径仍在 → R3-P2-7；1-10 未限定面板 → R3-P2-1；其余映射本轮抽查（0-2/1-4/1-17/1-25）与实现一致 |

## 全集复扫表 B — AUDIT-R2 的 13 条（逐条复验）

| ID | 结论 | 证据 |
|---|---|---|
| R2-P1-1 BUG-9 未真修（v1 5 字段丢弃、v2 错位） | ✓ 已修 | S：core 套件四路行形全过（含 verbatim 部署行 `CLIENT_LIST,alice,…,5457,5121,…` 与裸 v1 + ROUTING TABLE 回填） |
| R2-P1-2 改密无 UI | ✓ 已修 | S：API 全套 + 前端 `changePwBtn` / `change-password` 入口在位 |
| R2-P1-3 旧 CN 证书三路全堵 | ✓ 已修 | S：core 套件——真实 openssl 证书 + 真实格式 index.txt（filename 列字面 `unknown`）：legacy 用户经序列号识别、`legacy=true`，CA/server 排除，吊销/重建后 last-wins |
| R2-P1-4 verify-integration 不验登录态 status | ✓ 已修 | S：变异——status() 恒 500 时门禁 19/1，变红的正是登录态 status 格 |
| R2-P1-5 verify.sh files 漏列单元 | ✓ 已修 | S：变异——删 healthcheck.timer 后 files 格 FAIL（PASS 5→4） |
| R2-P2-1 /etc 隔离存在性判定 | ✓ 已修 | S：verify-integration 20/20 含“测试未碰 /etc”格；代码为跑前/跑后快照比对 |
| R2-P2-2 OVPN_PANEL_DATA_DIR 无人认 | ✓ 已修 | S：本轮全部 Flask 套件均以该变量钉到 /tmp 且树内 panel/data 保持空；`.gitignore` 含 `panel/data/` |
| R2-P2-3 README 哈希措辞矛盾 | ✓ 已修 | D：README 已写钉死四哈希 + 优先级（环境变量 > 钉死值 > manifest > 失败退出） |
| R2-P2-4 server-mode http:// | ✓ 已修 | D：server-mode.md 已全 https；同族残留见 R3-P2-6（cloudflare/README:207） |
| R2-P2-5 flmx-reference 1-13/§103 过时 | ◐ 部分 | D：R2 指的旧句已改，但 J Lane 后又出现反向过时（“明示警告后继续”“有即验”）→ R3-P2-7 |
| R2-P2-6 verify.sh sing-box-config 误导 | ✓ 已修 | C：verify.sh:206-212——文件缺 / 二进制缺 / check 失败三路报文已区分 |
| R2-P2-7 fail-open 单向性未写明 | ◐ 部分 | D：egress/README 写了故障时 `disable()` 撤表，但“fail-over 后须人工重开”未明文 → R3-P2-14 |
| R2-P2-8 starter heredoc 双份维护 | ✓ 已修 | S：verify.sh `starter-template-consistency` 格 PASS（tun 全字段 + dns.final 一致，route.final 故意不同） |

## 全集复扫表 C — 真机 bug（live 9 + live-R2 7，逐条复验）

沙箱不能跑 openvpn/sing-box 守护进程与 UDP 数据面；下表“沙箱”指本轮沙箱实证，“真机”指 live / live-R2 的既有实证（R3 未重跑真机，见诚实边界）。

| ID | 结论 | 证据 |
|---|---|---|
| BUG-1 模板 `inet4_address` 已废弃致 FATAL | ✓ 已修 | S：真实 sing-box 1.11.15 对渲染配置 `check` 通过 |
| BUG-2 无上游 sha256 清单 | ✓ 已修 | S：钉死四哈希 agent==install.sh；真实下载 sha256 与钉死值逐字节一致 |
| BUG-3 安装器报成功而 sing-box  crash-loop | ✓ 已修（沙箱门禁面） | C+S：`_singbox_check()` + verify.sh `sing-box-steady` 格（3 秒沉降 + MainPID 存活 + tun1 + 零重启）；守护进程真机行为以 live-R2 为准，未重跑 |
| BUG-4 用户列表含 CA 条目 | ✓ 已修 | S：core 套件——CA/server 排除、无 phantom `unknown` |
| BUG-5 agent 无法轮询自签面板 | ✓ 已修 | S：install-agent e2e——假自签面板 TOFU 钉证书后 bundle 拉取 + sha256 OK，退出 0 |
| BUG-6 重装不重启旧 agent | ✓ 已修（代码 + 门禁面） | C：install-agent.sh 末段 `is-active → restart` 分支在位；L：live-R2 已确认修好 |
| BUG-7 全部用户证书 CN=OpenVPN-CA | ✓ 已修 | S：core 套件——stub easyrsa 验到 `build-client` 的 gen-req CN=用户名、sign-req 无全局 CN 泄露 |
| BUG-8 无 FORWARD accept 规则 | ✓ 已修 | S：policy 桩测——FORWARD tun0↔tun1 四条规则启停正确；C：install.sh 直连模式 FORWARD 两条在位且健康门禁断言 |
| BUG-9 online_users 恒 0 | ✓ 已修 | S：core 四路 + Worker 快照归一化 |
| R2-BUG-10 新装 /opt 树缺 agent/ | ✓ 已修 | S：verify.sh `install-copies-agent` PASS；install-agent e2e 装出完整树 |
| R2-BUG-11 install-agent 先取包后钉证书 | ✓ 已修 | S：install-agent e2e 两分支——TOFU 钉证书先于一切面板拉取，bundle sha256 OK |
| R2-BUG-12 安装命令缺 --node-name | ✓ 已修 | S：前端 7/7 + Worker 50/50 + e2e config.json 含 node_name=testnode |
| R2-BUG-13 部署日志逗号 v2 被丢弃 | ✓ 已修 | S：core 套件 verbatim 部署行解析出 alice（10.8.0.2，rx 5457/tx 5121） |
| R2-BUG-14 allow_port_change 在面板路由层丢失 | ✓ 已修 | S：Flask 套件——不带 allow 改端口 500，带 allow 200 且 server.conf 变 tcp/443 |
| R2-BUG-15 健康门禁按 ens5 断言 SK5 模式 | ✓ 已修 | C：install.sh:787 注释与分支——门禁 mode-aware |
| R2-BUG-16 重装不继承已部署 proto/port | ✓ 已修 | C：install.sh:81——从既有 server.conf 继承 proto/port，显式变量仍优先 |

复扫差集：R1 33 条中 3 条部分（P1-6、P1-14、P2-13），其余 30 条已修；R2 13 条中 3 条部分（P2-5、P2-7、P2-13 的承袭项为 R3-P2-7/R3-P2-14/R3-P2-1），其余 10 条已修；真机 16 条全部已修（其中 BUG-3/BUG-6 的守护进程行为以 live-R2 实证为准，R3 未重跑真机）。**差集不为 ∅**——新增 R3-P1-1、R3-P1-2 与 R3-P2-1…R3-P2-14 共 16 条新发现。

## 家族复扫（机械枚举，差集）

| 家族 | 枚举方法 | 命中 | 结论 |
|---|---|---|---|
| 钉死哈希 | grep 全部下载点 + 四哈希出现位置 + 版本 | 下载点 2 处（agent.py、install.sh），哈希各 4 处、逐字节一致；真实下载验哈希一致 | ∅ |
| FORWARD 规则 | grep FORWARD 全树 | install.sh 直连两条 + policy-routing SK5 四条 + verify.sh 断言；桩测启停正确 | ∅ |
| TOFU | grep install-agent.sh 全部 curl 调用 | 全部面板拉取走 `curl_panel`（`--cacert`）或 `curl $CURL_TLS`；裸 curl 只出现在 die/warn 文案 | ∅ |
| CN | grep EASYRSA_REQ_CN 全树 | 仅 3 处行内赋值（CA/server/用户名）+ 注释；stub 实测无全局泄露 | ∅ |
| 密钥 | find secret.key/*.pem + .gitignore + install.sh | 树内零密钥文件；install.sh 删 shipped key 并生成新 key | ∅ |
| 202 轮询 | grep 202 + apiWait 调用点 | 10 个写操作全走 apiWait 轮询至 done/failed；非排队 POST（登录/注册/轮换/删节点）直接返回是正确语义 | ∅ |
| set_sk5 | 全部调用方（Flask/Worker/agent/egress） | 部分合并三端一致；Worker 仍发全量是纵深防御；仅头注释过时（R3-P2-10） | ∅（实现面） |
| 健康检查 | timer/service + install.sh + check_health 分支 | 单元在位且安装；两分支 + health.json 落盘实证 | ∅ |
| 安装命令拼装（新） | Flask buildInstallCommand vs Worker installCommand vs README 命令 | 两份生成器同口径（两步/-k/sha256/--node-name）；README 与 agent/README 的旧命令是异类 → R3-P1-2；Flask 缺 /install 路由 → R3-P2-1；token 未加引号 → R3-P2-13 | **不为 ∅** |
| 状态日志解析（新） | 四路行形（逗号 v2 / 裸 v1 / TAB v2 / 7 字段前缀）+ 其他解析器 grep | 四路全过；全树无第二解析器 | ∅ |

## 门禁变异验活

| 门禁 | 基线 | 变异 | 结果 |
|---|---|---|---|
| verify-integration.sh | 20/20（PASS=20 FAIL=0 SKIP=0） | `panel/app.py` 的 `status()` 改恒 500 | 19/1，变红的正是“登录后 GET /api/status 返回 500”格——门禁活着（R2-P1-4 回归成立） |
| verify.sh | PASS=5 FAIL=5（环境缺件） SKIP=11 | 删 `systemd/openvpn-sk5-healthcheck.timer` | files 格变 FAIL（PASS 5→4，FAIL 5→6）——门禁活着（R2-P1-5 回归成立） |

## 诚实边界（未验，不许当已验证）

- **Cloudflare 从未真实 `wrangler deploy`**：KV id 仍是占位符，Worker 结论全部来自 mock KV + mock 源站套件（50/50 + 3/3 + 重投反证），不是线上实测。部署前须真跑 `wrangler kv namespace create`、`wrangler secret put ADMIN_PASSWORD`、`wrangler deploy` 并换第二出口多点核验。
- **真机数据面是 live-verify-R3 的范围，不是本轮的**：本轮未重跑 Lightsail 真机；上表 C 中 BUG-3/BUG-6 的守护进程行为与全部 UDP 数据面（SK5 TCP+UDP 双通、首连、kill-switch 真实断网）均以 live-verify-R3 为准。沙箱不能建 TUN、不能跑 openvpn/sing-box 守护进程、对临时端口 UDP sendto 一律 EPERM。
- **easy-rsa 真机行为未验**：`easyrsa.sh` 的 CN 隔离只在 stub easyrsa 上验过（每命令行内 CN 正确）；真实 easy-rsa 3 签发全流程须真机复核（R2-P1-10 的同款保留意见）。
- **install.sh 全流程未在沙箱跑过**：只做了语法 + 门禁 + 关键分支代码核对；Lightsail 彩排部署上的原地升级路径（现行正式版 → 候选版）须按用户 2026-11-11 令走一遍才算发版门禁通过。
- **测试机现状未动**：本轮未碰 Lightsail 测试机；live-R2 末态（TCP 443 部署、5 服务、SK5 开、alice 在线）仍以 live-verify-R2 为准。

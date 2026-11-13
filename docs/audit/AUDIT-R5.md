# AUDIT-R5 — 全量全局回头看（交付前）

- 审计员：独立审计路（未参与建设与修复路 A–P；单审计员边做边写）
- 日期：2026-11-12（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1/R2/R3/R4 同等广度）
- 推导方法：**故障注入/对抗**（与 R1 逐文件通读、R2 旅程推导、R3 宣称驱动、R4 不变量驱动均不同）——先把五套件在 /tmp 副本上独立重跑，再对每一处“起不来/死掉/被删/过期/掉线”的退化条件做故障注入，逐项给“注入方法 + 实测行为 + 是否诚实呈现”；复扫 R1 33 + R2 13 + R3 16 + R4 5 + 真机 9+7+6 逐条重验；O/P 两路新代码单列一节逐项验；两门禁每个格至少一次变异红证。
- 前情：首派 AUDIT-R5 的总协调在汇总前结束、报告未落盘（3 条分路完成、1 条门禁变异路中断，/tmp 产物已被清）。本轮单审计员重做全部四部分，**不派子代理**；报告边做边写，每完成一节即落盘。
- 语法基线：4 个 Python 文件 `py_compile` 全绿；7 个 shell 脚本 `bash -n` 全绿；Worker `node --check` 全绿。
- 测试一律在 `/tmp` 副本（`/tmp/audit5`、`/tmp/audit5-tests/`）上跑；未动项目原文件；未动 `/etc`（探针落下的文件已清，见末尾）；未动任何真机。
- 套件说明：`/tmp/audit3-tests/` 与 `/tmp/audit3-venv/` 已被清，不可复用。本轮五套件全部自写（`/tmp/audit5-tests/`），以当前树为准；venv 为新建 `/tmp/audit5-venv`（Flask 3.1.3 + bcrypt）。套件期望以当前行为为准，不沿用已过期期望（R4 已指出 Worker/前端旧套件的过期期望问题）。

## §1 套件重跑（/tmp 副本独立重跑，全部自写）

套件位置：`/tmp/audit5-tests/`；运行环境：`unshare -rm` 挂载命名空间（`/etc/sysctl.d` 绑定空目录，`/etc` 零写入）+ 桩二进制（`fakebin/`：sing-box/check 0·run 常驻、ip 有状态、iptables 有状态、systemctl 永不启用、sysctl 空操作、easyrsa 记录 CN）+ `OVPN_SK5_CONFIG_DIR` / `OVPN_PANEL_DATA_DIR` 钉到 /tmp。桩的用途只在“把守护进程/内核态换成可观测的等价物”，不改产品代码。

| 套件 | 位置 | 结果 |
|---|---|---|
| egress | `/tmp/audit5-tests/egress_suite.py` | **20/20** |
| Flask 面板 | `/tmp/audit5-tests/flask_suite.py` | **61/62**（1 失败见 R5-P2-1） |
| agent | `/tmp/audit5-tests/agent_suite.py` | **19/19** |
| core | `/tmp/audit5-tests/core_suite.py` | **28/29**（1 失败 = 新发现 R5-P2-2，见下） |
| Worker | `/tmp/audit5-tests/worker_suite.mjs` | **56/56**（R3 为 50 项；本轮多 6 项子格 W08b/W28b/W38b/W42b/W47b/W50b） |
| verify-integration | `verify-integration.sh`（原脚本，沙箱跑） | **23/23**（见下注） |

### egress 20/20 —— R4-P1-1 与 R4-P2-1 的行为实证

- E01–E05：禁用态保存（全量、空操作、仅改 fail_open）均为纯写盘，不碰守护进程（无 pid 文件），配置 0600。R4-P1-1 的“无操作保存也 500”已修。
- E06–E08：enabled 翻转时 enable() 正常拉起桩 sing-box，`policy_routing_active=true`（规则 + table 100 默认路由 + tun1 三条件齐）。
- E09–E10：disable() 正常重起 direct 模式，`singbox_restarted=true`；关后旗标恒 false（R4-P2-1 已修）。
- E11–E13：sing-box 立死（`run` rc=1）时 `disable()` 不抛，返回 `singbox_restart_error` + `singbox_restarted=false`，且 `enabled=False` 已写盘、`policy_removed=true`——保存成功不再被守护进程失败误报为 500。
- E14–E16：fail-open 下 `check_health()` 在 sing-box 已死且 disable 重起失败时仍返回 `failed_over_to_direct`，`health.json` 落盘且 detail 含重起失败原因——timer 不再空手而归。
- E17–E18：kill-switch 分支 `blackholed_kill_switch` + health.json；禁用链 `chain_disabled` + health.json。
- E19–E20：死 SK5 的 test 双 false 不崩；UDP 回包解析器好/错 txid/截断三态正确。

### Flask 61/62 —— 唯一失败是 R5-P2-1（可预见的客户端错误报 500）

- 登录/限流（F01–F09）：全部通过——错密 401、6 次失败 429 + Retry-After、锁定中正确密码仍 429、他 IP 不受影响、登出清会话、bcrypt `$2b$` 落库、会话 cookie HttpOnly。
- 改密（F10–F17）：全部通过——未登录 401、错旧 401、弱密码 400（三路：过短/与旧相同/无数字）、成功 200、旧会话立即失效、旧密码 401 + 新密码 200。（套件教训：初版 F10 用已在 F07 登录过的 `client` 测“未登录”，误把密码改掉、连锁失败 5 项；已改用全新匿名 client 重跑，61/62 的数字是修正后的。）
- 节点/命令（F18–F33）：全部通过——注册 201 + token 只返一次且列表不含明文、重复 409、错名 poll 401、轮换 200（旧 token 立即 401、新 token 可用）、吊销后 poll 401、命令 202 入队、poll 下发、report 后 done、sent 超时重投 retries=1 回队、第 4 次超时标 failed。
- 状态（F34–F36）：全部通过——未登录 401、已登录 200 含 openvpn/sk5/egress 三键、running 为布尔值。
- OpenVPN（F37–F48）：除 F43 外全部通过——建服务 200、同 proto/port 重建 200 幂等、无 allow 改口 500、有 allow 改口 200（tcp/443）再改回 200、建用户 200、列表含 alice 且无 CA/server 条目、.ovpn 下载 200 含 remote 与证书、吊销后下载 403、未知用户 404、非法用户名 400。
- SK5（F49–F60）：全部通过——无存量时只带 enabled → 400、全量禁用保存 200（O：纯写盘）、空密码保留、clear_password 清除、单字段 fail_open/enabled 均 200 且 host 保留、enable/disable 各 200（disable 含 `singbox_restarted=true`）、fail-open/udp-over-tcp 路由 200、死 SK5 的 test 双 false。
- 安装包（F61–F62）：全部通过——bundle 200 且 sha256 端点与字节一致、install-agent.sh 200 且 sha256 一致。（套件教训：初版拿整行 `"<hex>  <文件名>"` 与 hex 比对，误判失败；端点格式本身符合 `sha256sum -c` 可读格式。）
- **F43 失败（R5-P2-1）**：重复建用户 `POST /api/openvpn/users {"name":"alice"}` → **500** `{"error":"user 'alice' already exists (valid cert)"}`；同族探针：吊销不存在的用户 `DELETE /api/openvpn/users/ghost` → **500** `{"error":"user 'ghost' does not exist"}`。文案诚实、行为正确（未重复建、未误删），但状态码把可预见的客户端错误报成了服务端错误；同路由对非法 proto 正确回 400、节点重复建正确回 409，口径不一致。监控按 5xx 告警时会误报，用户也无法从状态码区分“重名”与“服务端故障”。修法建议：`ovpn_users_create`/`ovpn_users_revoke` 把 core 的“已存在/不存在”类 OpenVPNError 映射为 409/404（或统一 400），其余未知异常仍 500。

### agent 19/19

- 白名单/防注入（A01–A04）：未知 action 拒、params 含 `shell`/`cmd` 拒、非 dict params 拒。
- set_sk5 部分合并（A05–A09）：全量禁用保存 ok、单字段 enabled=false 保留 host/port、仅改 fail_open 保留 host、空密码保留已存、非法 host 拒——R4-P1-1 的 agent 侧已修。
- 状态与用户（A10–A15）：get_status 含 openvpn/users/sk5/egress_ip/health 五键；create_server 两次均 ok（幂等）；create_user 返回 `{"name","ovpn"}` 且 .ovpn 含 remote；revoke ok、二次吊销报“already revoked”不抛。
- --once（A16–A17）：不可达面板 exit 1；回环 stub 面板 exit 0。
- 钉死哈希与版本门（A18–A19）：四钉死哈希 agent.py 与 install.sh 逐字节一致；旧版 sing-box（1.8.0）不被保留、进入重装下载路径。
- （套件教训：初版 A13 按“create_user 回纯字符串”断言，实际回 `{"name","ovpn"}` dict——套件错不是产品错；A14 初版因桩 openvpn 不 daemonize 而失败，已把桩改为 `--daemon` 时 fork 常驻并写 pid 文件。另：桩 sing-box 的 `trap TERM; while true; sleep` 在 bash 前台 sleep 未结束前不响应 TERM，残留进程须 SIGKILL 父进程才清净——已把桩改为 `exec sleep 3600`，本轮沙箱残留已清零。）

### core 28/29

- PKI 生命周期（C01–C05）：init 正常、二次无 force 拒绝、build_server_cert 落盘且 CN=server（桩签发证书现带 `CN=<名>` 行，贴合真实证书 subject；另以 easyrsa 日志核对 EASYRSA_REQ_CN 按命令分设）、幂等。**唯一失败 C03（R5-P2-2）**。
- 用户（C06–C14）：建 alice 得 .ovpn（remote+证书+私钥）、重复建拒、非法名/保留名拒、list 仅 alice、吊销 ok、二次吊销拒、吊销后 list 显 revoked、吊销后可重建。
- 状态日志解析（C15–C19）：v1 裸行＋路由回填、部署态逗号 v2 逐字段、TAB v2、7 字段前缀行、空/缺失日志回 []——全部用 `core/tests/test_status_log.py` 的逐字真机夹具复核；**树内回归套件本身另跑 5/5 全过**，交叉印证。
- server.conf（C20–C23）：udp/1194 渲染、tcp/443 无 allow 拒（P01）、有 allow 放行、同 proto/port 重渲染不误报占用。
- 守护进程（C24–C28）：停态不抛、start/stop/restart 在桩 daemon 下均按预期；运行态读部署 v2 日志得 alice+bob 两客户端。
- 用户名边界（C29）：33 字符与空串拒、`a-b_c9` 通过（返回原名）。
- （套件教训三则：① 初版 C16 夹具 HEADER 我按摘要臆造为 `Username,Context,Common Name`（含重复 Common Name），解析得 name='0'——查树内回归测试证实**真实部署 HEADER 是 `Username,Client ID,Peer ID,Data Channel Cipher`，无重复列**，解析器无错，是我的夹具错；② 初版把字节数按 int 断言，解析器回的是字符串（回归测试亦按字符串断言），已改；③ 桩 systemctl 的 stop 初版只回 0 不杀进程，致 stop 后仍 running——真实 systemd 的 stop 确会杀进程，已让桩按 OPENVPN_PID_FILE 杀进程，贴合真实语义。）

### 新发现 R5-P2-2：`init_pki(force=True)` 是死路，文档承诺的 CA 擦除重建走不通

- 证据（core C03）：已存在 CA 时调 `init_pki(ca_dir, force=True)` → `OpenVPNError: command failed (bash …/easyrsa.sh init …): easyrsa.sh: CA already exists in …/pki (refusing to wipe)`。
- 根因：`core/openvpn_manager.py:142-156` 的 force 只作 Python 侧放行检查，随后无条件调 `_run_easyrsa("init")`；`core/easyrsa.sh` 的 `init` 分支（约 :68-72）在 `ca.crt` 存在时无条件拒绝，**没有任何 force 参数透传**。agent 的 `action_init_pki`（P2-9）称 force+confirm 可擦除，与之矛盾。
- 影响：面板发起的 CA 重建（例如 CA 泄露后）永远失败；管理员只能手动上服务器删 pki 目录——该后路未在任何文档写明。失败是响亮诚实的（无静默损坏、无数据丢失），定 P2。
- 修法建议：`easyrsa.sh init` 接受 `force` 参数（或 `init_pki(force=True)` 先删 pki 目录再调 init），非 force 路径的拒绝守卫保留。

### Worker 56/56

- 登录/限流（W01–W08b）：错密 401、5 次后第 6 次 429+Retry-After、锁期内正确密码仍 429、他 IP 不受影响、登录发 panel_session、未登录 /api/me 401、登出后会话失效。
- 节点（W09–W17）：注册 201（token 65 字符，安装命令含 `curl -ksSL`＋`sha256sum -c`＋`--node-name 'lightsail'`）、重复 409、非法名 400、列表无明文 token、轮换 200（旧 token 随即 401）、轮换未知节点 404、安装模板含 `<NODE_TOKEN>` 占位＋`--node-name`、吊销未知节点 404。
- 命令/轮询/回执（W18–W33）：缺 node 400、非法 action 400、未知节点 404、建命令 202、错 node_name 轮询 401（R3-P2-12）、对名轮询取走命令、回执 done、未知命令 404、读命令时密码脱敏为 `••••••••`、安全动作（get_status）超时重投 retries=1（同轮 poll 立即重发，终态 sent，retries 是重投证据）、**非幂等动作（set_sk5）首超时即标 failed（W28b，既定 fail-fast，见下）**、create_user 超时标 failed 不重发、retries=3 再超时标 failed（R3-P1-1 上限已修）、吊销使排队/已发命令标 failed、吊销后轮询 401、垃圾 token 401。
- 兼容层（W34–W47b）：无快照时 /api/status 200 stale+note、建服务/建用户只 202 排队（不报成功，P0-1）、SK5 缺 host 400、全量保存 202 且 sk5cfg 落盘、空密码保留已存（P0-4 Worker 侧）、多节点不指定 node 400、未存配置时开关 400、已存配置时开关 202 且下发命令含全字段、UDP 守卫（UDP 服务＋同地址 UDP 测试失败→400）、快照用户列表、状态归一化（egress.ip＋via_sk5＋online_users=clients 数＋servercfg 的 proto/port）、快照剔除 SK5 密码、.ovpn 未生成时 404、回执后下载 200 含 remote。
- 安装包代理（W48–W50b）：未配 origin 503、源站哈希一致 200、哈希不符 502 fail-closed、install-agent.sh.sha256 代理回 64 位 hex。
- **两端重投口径分歧（已查证，非 bug，不立案）**：Worker 仅 7 个幂等动作可重投，set_sk5/create_user 等首超时即 failed；Flask `_requeue_stale_sent`（panel/app.py:493-530）不分动作全重投（set_sk5/create_user/get_status 超时均打回 queued，retries=1——已用小探针实测三动作全重投）。分歧在 `docs/security.md:12` 已明文记载（“Worker 侧非幂等命令首超时即标 failed”＋“非幂等命令重投时可能重复执行，需 agent 侧幂等防护”），两端行为各自诚实、无静默错误；仅提醒：同一操作在两种模式下对短暂 agent 离线的容忍度不同，文档已披露，交付文档可照此写，不必改代码。

### verify-integration 23/23

- 原脚本沙箱跑（`bash verify-integration.sh`，面板＋agent 均 nobody 身份，/tmp 副本）。第一次跑 **21/1**：`get_status 回执 failed`，agent 日志：`[Errno 13] Permission denied: '/run/openvpn-server/server.pid'`。根因分两层：
  - **直接触发是我方沙箱污染**：我为 core 套件建的 `/run/openvpn-server` 目录权限为 770（root），nobody 无法进入；目录本身是空的、无 pid 文件。已删除该目录并重跑，**23/23 全绿**。
  - **产品缺口是真实的（R5-P2-3，见下）**：触发条件虽是我造的，但 `server_status()` 的裸 `exists()` 在任何权限收紧的主机上都会同样炸掉整条 get_status。
- 计数说明：脚本共 23 格，其中 1 格（“get_status 回执含 openvpn/sk5，且 running=false”）仅在 get_status done 时执行；第一次跑因失败只执行了 22 格（21/1），重跑 23/23。目标 23 达成，无缺格。
- O lane 的 R4-P2-4 回归格三格全过：禁用态全字段保存 200 且桩 run 0 次、再次保存仍 0 次、单字段 `{enabled:false}` 200 且回执带 `singbox_restart_error`、桩 run 恰 1 次。

### 新发现 R5-P2-3：`server_status()` 的裸 `Path.exists()` 违反“永不抛错”承诺（修A漏B同族）

- 证据：agent（nobody 身份）执行 get_status 时，`core/openvpn_manager.py:1001` 的 `if PID_FILE.exists():` 在不可读路径上抛 `PermissionError: [Errno 13] Permission denied: '/run/openvpn-server/server.pid'`，整条 get_status 命令失败、无快照返回。Python 3.12 的 `Path.exists()` 只吞 FileNotFoundError，不吞 PermissionError（本轮 egress 侧早先已因此修过一次，见 §0 注记）。
- 同族漏网：同一函数内 `:1030` 的 `if candidate.exists():`（状态日志候选路径）同样裸露；`server_status()` 文档承诺“Never raises for a stopped/missing daemon”，这两处使承诺在权限收紧时失效。
- 真机可能性：低——Debian 默认 `/run/openvpn-server` 与 `/var/log/openvpn` 均可读，标准部署不触发；但任何把运行/日志目录收紧到 750/770 的主机（或 root 专属目录）都会使 agent 的 get_status 整体失败，而 root 跑的面板自身不受影响，问题只在 agent（nobody）路径暴露。
- 定 P2：失败响亮诚实（错误信息点名路径）、无静默错数据；但它杀死整条状态命令（无部分快照），且是已修过一次的同族（egress 的 `_exists()` 在 `egress/sk5_manager.py:92`）在 core 侧的漏网。
- 修法建议：core 复用 egress 的 `_exists()` 口径（OSError 即 False）包住 `:1001` 与 `:1030` 两处；或在 `server_status()` 外层对 OSError 兜底、填 error 键返回。


## §0 树版本与 O/P 改动确认

| 文件 | mtime (UTC) | 说明 |
|---|---|---|
| egress/sk5_manager.py | 2026-11-12 03:40:11 | O 路：set_sk5 只模式变化才重起、disable 重起失败诚实返回、check_health fail-open 包 try、policy_routing_active 三条件 |
| verify-integration.sh | 2026-11-12 03:40:37 | O 路：R4-P2-4 门禁补格 |
| install.sh | 2026-11-12 03:38:13 | P 路：IPv4 探测逐段 ≤255 校验 |
| README.md | 2026-11-12 03:38:13 | P 路：复制清单补 systemd/ |
| panel/app.py | 2026-11-12 02:22:28 | H 路（未动） |
| panel/templates/index.html | 2026-11-12 02:49:17 | L 路（未动） |
| cloudflare/src/index.js | 2026-11-12 02:28:20 | J 路（未动） |

O/P 改动代码面确认（本轮 grep + 通读，行为实证见 §3 O/P 节与 §2 故障注入）：
- O-1 `set_sk5`（sk5_manager.py:548-612）：`now_enabled != was_enabled` 才调 `enable()/disable()`；仍启用且链路字段变才重渲染重起；仍禁用或只改 `fail_open` 时纯写盘不碰守护进程。
- O-2 `disable()`（:751-804）：`_render_direct_config()` → `_remove_policy()` → `_stop_singbox()` → 写盘 `enabled=False` → `_start_singbox()` 包 try，失败时返回 `singbox_restart_error` + `singbox_restarted=false`，不抛。
- O-3 `check_health()`（:834-905）：fail-open 分支 `disable()` 包 try，`disable()` 抛错也落 `failed_over_to_direct`（附 detail），`health.json` 必写。
- O-4 `get_status()`（:677-728）：`policy_routing_active` 须同时满足 enabled + `ip rule` 含 VPN_NET 且 lookup 100 + table 100 有 `default … dev tun1`；SK5 关闭时恒 false。
- P-1 `README.md:72` 复制清单补 `systemd/`（与 install.sh:355 一致）。
- P-2 `install.sh:454-457` IPv4 探测逐段 ≤255 校验（正则后加范围校验，不通过按“未探测到”处理）。

## §2 故障注入（Fault Injection）

方法：对 egress 层（`egress/sk5_manager.py`）与面板命令队列（`panel/app.py`）逐项注入故障，记录“注入方法＋实测行为＋是否诚实呈现”。注入套件：`/tmp/audit5-tests/fault_injection.py`（egress，14 格）、`/tmp/audit5-tests/fault_injection_panel.py`（面板，8 格）。

### egress 层 14/14

| 注入 | 实测行为 | 诚实？ |
|---|---|---|
| FI01 sing-box 二进制缺失（SINGBOX_BIN 指不存在路径） | `enable()` 抛 `sing-box not found at …: install sing-box 1.11+ first`，enabled 保持 False | 是 |
| FI02 `sing-box check` 失败 | `enable()` 抛 `sing-box check failed: …`，enabled 保持 False | 是 |
| FI03 `sing-box run` 立死 rc=1 | `enable()` 抛 `sing-box exited immediately (rc=1)` | 是 |
| FI04 `sing-box run` 立退 0 | `enable()` 抛 `sing-box exited immediately (rc=0)` | 是 |
| FI05 SK5 死亡（11080 无监听） | `test_sk5()` 回 `tcp_ok=false udp_ok=false`，不抛 | 是 |
| FI06 health.json 被删 | `last_health()` 与 `get_status()["last_health"]` 均为 None，不抛 | 是 |
| FI07 health.json 写坏（非 JSON） | `last_health()` None，不抛 | 是 |
| FI08 策略规则被手工删（enabled 态） | `policy_routing_active` 立即变 false；disable+enable 后恢复 true | 是 |
| FI09 table 100 被清空（enabled 态） | `policy_routing_active` false | 是 |
| FI10 死代理＋fail_open 关 | `check_health()` 回 `healthy=false, action=blackholed_kill_switch`，health.json 已写，无 fail-over | 是 |
| FI11 死代理＋fail_open 开＋disable 重起失败 | `check_health()` 回 `healthy=false, action=failed_over_to_direct`，health.json 已写，detail 含 `fail-over restart failed: …` | 是 |
| FI12 sk5.json 不可读（nobody 身份） | `get_status()` 回 `config_error: cannot read … permission denied -- run as root … or fix the file's ownership/permissions`，不抛 | 是 |
| FI13 未配 SK5 即 enable | 抛 `no SK5 configured: call set_sk5() first`，守护进程未被触碰 | 是 |

（注入手法教训：① `SINGBOX_BIN` 在 import 时已解析为绝对路径，运行时剥 PATH 剥不到它，FI01 须改模块常量才算真注入——初版剥 PATH 测到的是 policy-routing.sh 的 TUN 失败，是手法污染；② health.json 由 `check_health()` 写、不是 `enable()` 写；③ FI12 在 root 下测不出权限问题，须以 nobody 跑探针。）

### 面板层 8/8

| 注入 | 实测行为 | 诚实？ |
|---|---|---|
| FI-P1 agent 掉线（命令已排队，无人 poll） | 命令 2 秒后仍 queued，无幽灵超时、无误标失败 | 是 |
| FI-P2 面板重启（importlib.reload，同 DATA_DIR） | 旧 Flask `session` cookie 仍有效（/api/me 200）；排队命令重启后仍 queued（队列文件 `agent_queue.json` 落盘） | 是 |
| FI-P3 节点中途吊销 | 旧 token 轮询 401；排队命令标 failed，error 含“节点已吊销” | 是 |
| FI-P4 sent 超时横跨面板重启（sent_at 改为 130 秒前再 reload） | 下一轮 poll 成功并重发；命令 retries=1、重新进入 sent | 是 |
| FI-P5 agent 认领错节点名 | 轮询 401，无命令泄露 | 是 |

### 观察（不立案）

- **enable 失败回 500、disable 失败回 200**：`POST /api/sk5/enable` 在 sing-box 起不来时回 500＋诚实错误文案（`sing-box check failed…`／`exited immediately…`，enabled 保持 False、无部分状态）；`disable()` 同类失败回 200＋`singbox_restart_error` 字段（O-2 修法）。两者信息都真实、都不静默；仅状态码口径不对称。enable 的操作本身失败（链未建成、未保存），500 可辩护；若求全端一致，可把 enable 也改成 200＋error 字段——属打磨项，本轮不立案。
- 本节未发现新的 P0/P1/P2。

## §3 全集复扫（Full Rescan）

方法：R1 33 + R2 13 + R3 16 + R4 5 + 真机 9+7+6 = 73 条逐条重验（不只读修复代码）。证据代号：S=本轮套件实证（§1）；F=本轮故障注入（§2）；C=本轮代码/文档核对（grep＋通读）；P=本轮专项探针；L=此前真机实证（live/live-R2/live-R3，本轮未重跑真机）；W=待 live-R4。

### 表 A — AUDIT-R1 的 33 条

| ID | 结论 | 本轮证据 |
|---|---|---|
| P0-1 202 当成功 | ✓ 已修 | S：Worker 56/56（202 只排队，apiWait 轮询至 done/failed）；Flask 61/62 |
| P0-2 单字段 set_sk5 必败 | ✓ 已修 | S：Worker W42/W42b（开关下发全量字段）、agent A06–A08（部分合并） |
| P0-3 Worker 无 bundle/安装脚本路由 | ✓ 已修 | S：Worker W48–W50b（无源站 503、有源站 200、篡改 502） |
| P0-4 SK5 密码保存清空 | ✓ 已修 | S：Flask F52–F53（空密码保留、clear 清除）、Worker W38b/W39、egress 20/20 |
| P0-5 secret.key 随树发货 | ✓ 已修 | C：树内 `find panel -name secret.key` 0 命中；发货哈希常量在位（命中即轮换）；`.gitignore` 含 `panel/data/` |
| P1-1 status 耗时 20 秒 | ✓ 已修 | P：静默 SOCKS 下 `/api/status` 首调 11.3s、二次 0.81s（原 20.0s 串行双探针已消除，复用已探 egress_ip） |
| P1-2 无节点/agent 界面 | ✓ 已修 | C：index.html 含 7 处 `/api/nodes` 引用；verify-integration 23/23 含节点全链 |
| P1-3 Worker 登录无限流 | ✓ 已修 | S：Worker W01–W04（5 次后 429＋Retry-After，他 IP 不受影响） |
| P1-4 Worker 无吊销/轮换 | ✓ 已修 | S：Worker W13–W17、W31–W32（轮换 200、旧 token 401、吊销后 401） |
| P1-5 Worker 快照形状错位 | ✓ 已修 | S：Worker W45–W46（egress.ip＋via_sk5＋online_users=clients 数＋servercfg 补 proto/port） |
| P1-6 sent 态无重投 | ✓ 已修 | S：Flask F31–F32（重投 retries=1、第 4 次 failed）、Worker W28/W30（上限 3）；两端重投集差异已在 security.md:12 明文记载（§1 Worker 节） |
| P1-7 无改密接口 | ✓ 已修 | S：Flask F10–F17（API 全套）；C：index.html 5 处 change-password/改密入口，install.sh“没有改密接口”0 命中 |
| P1-8 check_health 死开关 | ✓ 已修 | C：timer+service 在树内且 install.sh 安装；F：FI10/FI11 两分支＋health.json 落盘 |
| P1-9 策略路由无持久化/重跑覆盖 SK5 | ✓ 已修 | C：`openvpn-sk5-policy.service`（开机 `policy-routing.sh restore`，仅 enabled 时恢复）在位且 install.sh 安装；install.sh:824-828 重跑读存量 sk5.json 判模式 |
| P1-10 create_server 不幂等 | ✓ 已修 | S：agent A11–A12（两次均 ok）、core C05 |
| P1-11 入口端口无占用检查 | ✓ 已修 | S：core C20–C23（占用拒、无 allow 改口拒、有 allow 通） |
| P1-12 UoT 探针密码写 /tmp 明文 | ✓ 已修 | C：`egress/sk5_manager.py:486` mkdtemp 唯一目录（0700，配置 0600） |
| P1-13 systemctl 无超时/保护 | ◐ 部分 | P：PATH 剥离后 `server_status()` 不抛、running False；但 PID 文件与状态日志候选路径仍是裸 `exists()` → 新立案 **R5-P2-3** |
| P1-14 server-mode.md 过时 | ✓ 已修 | C：server-mode.md `http://` 0 命中；:17 已写“仅 Worker 有 /install 接口” |
| P1-15 Worker set_sk5 假宣称 | ✓ 已修 | S：三端语义一致（§1）；Worker 头注释已改“纵深防御”（index.js:43-46） |
| P2-1 限流进程内内存/无 ProxyFix | ✓ 已修 | C：SQLite `login_attempts` 表（app.py:220,380-401）；`OVPN_TRUSTED_PROXY=1` 才启用 ProxyFix（:177） |
| P2-2 agent 不校验 sing-box 版本 | ✓ 已修 | S：agent A19（旧版 1.8.0 不被保留、进入重装路径） |
| P2-3 --once 失败仍返回 0 | ✓ 已修 | S：agent A16（不可达面板 --once 退出 1） |
| P2-4 bundle 确定性不完全 | ✓ 已修 | P：两次打包字节相同（65028 字节）；sha256 端点与字节一致 |
| P2-5 密码哈希 SHA-256 非 bcrypt | ✓ 已修 | S：Flask F08（DB 中 `$2b$` 哈希）；README:258/261 已改 bcrypt 已落地 |
| P2-6 OVPN_DNS 被忽略 | ✓ 已修 | C：`render_server_conf` 取 `dns or OVPN_DNS or 默认`；模板/安装器接线一致 |
| P2-7 PANEL_ADMIN_PASSWORD_FILE 无人读 | ✓ 已修 | C：全树仅剩 install.sh:483 一句注释（“旧变量已废弃”），无活变量 |
| P2-8 健康门禁把密码放 curl -d argv | ✓ 已修 | C：install.sh:791 与 verify.sh:332 均 `--data @0600文件` |
| P2-9 init_pki force 无二次确认 | ◐ 部分 | C：确认门在位（agent.py:599-603，force 须并传 `confirm=true`）；但 force 操作本身是死路 → 新立案 **R5-P2-2** |
| P2-10 .ovpn 下载不校验用户状态 | ✓ 已修 | S：Flask F46–F47（吊销 403、未知 404） |
| P2-11 UoT 固定 /tmp 路径 + manifest 无条目即 raise | ✓ 已修 | C：mkdtemp（见 P1-12）；`_expected_sha256` 轮询多 manifest（agent.py:426-438） |
| P2-12 两处文档过时 | ✓ 已修 | C：security.md 残留 #1 已改 fail-closed 口径；README:261 已注 bundle.sha256 端点已补 |
| P2-13 flmx-reference 多项未落地/过时 | ✓ 已修 | C：1-10 已限定面板、1-13/§103 按 J 后强制校验改写、“版本解析”已限定为 FLMX 步骤不抄 |

### 表 B — AUDIT-R2 的 13 条

| ID | 结论 | 本轮证据 |
|---|---|---|
| R2-P1-1 BUG-9 未真修（v1 丢弃、v2 错位） | ✓ 已修 | S：core C15–C19 四路行形全过；树内回归 `core/tests/test_status_log.py` 5/5 |
| R2-P1-2 改密无 UI | ✓ 已修 | 见 R1-P1-7 |
| R2-P1-3 旧 CN 证书三路全堵 | ✓ 已修 | S：core C10–C14（legacy 识别、吊销/重建）；C：`_serial_to_name` 序列号识别在位 |
| R2-P1-4 verify-integration 不验登录态 status | ✓ 已修 | S：verify-integration 23/23 含登录态 status 格；§4 变异见下 |
| R2-P1-5 verify.sh files 漏列单元 | ✓ 已修 | C：verify.sh:150 清单含 5 单元＋agent＋模板；§4 变异见下 |
| R2-P2-1 /etc 隔离存在性判定 | ✓ 已修 | S：verify-integration 23/23 含快照比对格（跑前/跑后）；本轮实测通过 |
| R2-P2-2 OVPN_PANEL_DATA_DIR 无人认 | ✓ 已修 | C：app.py:95 认该变量；`.gitignore` 钉 `panel/data/`；本轮全部套件以该变量钉 /tmp，树内 panel/data 为空 |
| R2-P2-3 README 哈希措辞矛盾 | ✓ 已修 | C：README“不写死/未经核实”0 命中；已写钉死四哈希＋优先级 |
| R2-P2-4 server-mode http:// | ✓ 已修 | C：全文 0 命中（见 R1-P1-14） |
| R2-P2-5 flmx-reference 1-13/§103 过时 | ✓ 已修 | C：旧句 0 命中（见 R1-P2-13） |
| R2-P2-6 verify.sh sing-box-config 误导 | ✓ 已修 | C：verify.sh:192-196 三路报文已区分（文件缺/二进制缺/check 失败） |
| R2-P2-7 fail-open 单向性未写明 | ✓ 已修 | C：根 README:156 与 egress/README:134 均已写单向性＋人工重开 |
| R2-P2-8 starter heredoc 双份维护 | ✓ 已修 | C：verify.sh:226-255 `starter-template-consistency` 格在位（tun 全字段比对，route.final 故意不同） |

### 表 C — AUDIT-R3 的 16 条

| ID | 结论 | 本轮证据 |
|---|---|---|
| R3-P1-1 Worker sent 重投无上限 | ✓ 已修 | S：Worker W30（retries=3 再超时标 failed）；C：`SENT_MAX_RETRIES = 3`（index.js:86）＋计数器 :582-584 |
| R3-P1-2 文档旧一键命令 | ✓ 已修 | C：README 与 agent/README 旧命令 0 命中；两处均为两步走 `-k + sha256sum -c + --node-name` |
| R3-P2-1 server-mode 称 Flask 有 /install | ✓ 已修 | C：server-mode.md:17 与 flmx-reference 均写“仅 Worker 有” |
| R3-P2-2 README 称 fail-open 路由不存在 | ✓ 已修 | C：README 该句 0 命中；Flask 套件两路由 200 |
| R3-P2-3 README 称哈希 SHA-256 待对齐 | ✓ 已修 | 见 R1-P2-5 |
| R3-P2-4 README 复制清单漏 agent/ | ✓ 已修 | C：README:72 清单含 `agent/`（见 R4-P2-2 行，另含 `systemd/`） |
| R3-P2-5 cloudflare/README warn 后继续 | ✓ 已修 | C：该句 0 命中；installCommand 为 fail-closed（Worker W50） |
| R3-P2-6 cloudflare/README 轮询 http:// | ✓ 已修 | C：全文 `http://` 0 命中 |
| R3-P2-7 flmx-reference 1-13/§103 过时 | ✓ 已修 | 见 R1-P2-13 |
| R3-P2-8 panel/README 只认 proto/port | ✓ 已修 | C：panel/README:59 已补 allow_port_change＋P01 口径 |
| R3-P2-9 panel/README 称未轮询 | ✓ 已修 | C：panel/README:81/89 已改 timer 60 秒＋last_health 回显 |
| R3-P2-10 Worker 头注释过时 | ✓ 已修 | C：index.js:43-46 已改（见 R1-P1-15） |
| R3-P2-11 轮换 201 对 200 | ✓ 已修 | S：Worker W13（轮换 200） |
| R3-P2-12 Worker poll 忽略 node_name | ✓ 已修 | S：Worker W22（错名 401）、W23（对名 200） |
| R3-P2-13 安装命令 token 未加引号 | ✓ 已修 | C：两份生成器三处统一 shellQuote（index.html:827-831、index.js:407-414）；S：Worker W09 命令含引号 |
| R3-P2-14 egress/README 未写 fail-open 单向性 | ✓ 已修 | 见 R2-P2-7 |

### 表 D — AUDIT-R4 的 5 条

| ID | 结论 | 本轮证据 |
|---|---|---|
| R4-P1-1 保存/ fail-over 硬依赖 sing-box 立即重起 | ✓ 已修 | S：egress 20/20（E01–E16 全过，禁用态保存纯写盘、死桩 disable 不抛、fail-open 必写 health.json）；Flask 61/62（仅 R5-P2-1 失败，与 P1-1 无关）；agent 19/19；F：FI10/FI11；verify-integration §4c 三格全过 |
| R4-P2-1 policy_routing_active 只看规则存在 | ✓ 已修 | F：FI08（规则删→false）、FI09（表空→false）、FI08b（重建→true）；C：三条件在位（sk5_manager.py:704-720） |
| R4-P2-2 README 清单漏 systemd/ | ✓ 已修 | C：README:72 清单含 `systemd/`，与 install.sh:355 一致 |
| R4-P2-3 IPv4 形状校验接受 999 | ✓ 已修 | P：awk 逐段校验实测——999.999.999.999 拒、256.1.1.1 拒、16.146.199.68 与 1.2.3.4 通过 |
| R4-P2-4 门禁对 SK5 保存→重起耦合零覆盖 | ✓ 已修 | S：verify-integration §4c 三格（桩 sing-box run 记行：无操作保存 0 次、单字段 disable 恰 1 次＋诚实 error）；§4 变异见下 |

### 表 E — 真机 bug（live 9 + live-R2 7 + live-R3 6）

沙箱不能跑 openvpn/sing-box 守护进程与 UDP 数据面；“代码面”指本轮沙箱实证，“真机”指 live/live-R2/live-R3 的既有实证；凡需真机行为复核的项一律写“待 live-R4”，不提前判通过。

| ID | 结论 | 本轮证据 |
|---|---|---|
| BUG-1 模板 `inet4_address` 已废弃致 FATAL | ✓ 已修 | P：重下真实 sing-box 1.11.15（sha256 `950af37e…d9c5` 与钉死值逐字节一致，自报 1.11.15），渲染的 native 与 UoT 两版配置 `sing-box check` 均通过；C：模板全树无 `inet4_address`，仅 `"address"` |
| BUG-2 无上游 sha256 清单 | ✓ 已修 | S：agent A18（四哈希两处逐字节一致）；P：真实下载验哈希一致 |
| BUG-3 安装报成功而 sing-box crash-loop | ✓ 已修（代码＋门禁面） | C：`wait_steady_active`（is-active＋MainPID＋tun＋5s 沉降＋零重启）在位，`StartLimitIntervalSec=120/Burst=5` 在位；守护进程真机行为待 live-R4 |
| BUG-4 用户列表含 CA | ✓ 已修 | S：core C10（list 仅 alice） |
| BUG-5 agent 无法轮询自签面板 | ✓ 已修 | S：agent A16–A17（无信任 exit 1、有 ca-cert/回环 exit 0）；C：install-agent.sh TOFU 钉证书先于一切面板拉取（:145-227 在取包 :330 之前） |
| BUG-6 重装不重启旧 agent | ✓ 已修（代码面） | C：install-agent.sh:384 reset-failed、:390-391 已运行则 restart、事后 is-active 判活；真机行为待 live-R4（live-R2 已验） |
| BUG-7 全部用户证书 CN=OpenVPN-CA | ✓ 已修 | S：core C04（CN=server）＋C06（alice .ovpn 含证书）；C：easyrsa.sh:51 全局 export 已删，三处行内 CN 在位 |
| BUG-8 无 FORWARD accept 规则 | ✓ 已修（代码面） | C：install.sh:626-627 两条 FORWARD（tun0 出入，-C 幂等）＋健康门禁核对；真机行为待 live-R4 |
| BUG-9 online_users 恒 0 | ✓ 已修 | S：core C15–C19＋回归 5/5；live-R3 第四次复验逐字段一致（本轮未重跑真机） |
| R2-BUG-10 新装 /opt 树缺 agent/ | ✓ 已修 | C：install.sh:343-347 复制清单含 `agent/`；verify.sh install-copies-agent 格在位 |
| R2-BUG-11 先取包后钉证书 | ✓ 已修 | 见 BUG-5 |
| R2-BUG-12 安装命令缺 --node-name | ✓ 已修 | S：Worker W09/W13（命令含 `--node-name 'lightsail'`）；C：前端 index.html:831 同款 |
| R2-BUG-13 部署日志逗号 v2 被丢弃 | ✓ 已修 | S：core C16（verbatim 部署行：alice 10.8.0.2，rx 5457/tx 5121） |
| R2-BUG-14 allow_port_change 丢失 | ✓ 已修 | S：Flask F40–F41（不带 500、带 200 且 server.conf 变 tcp/443） |
| R2-BUG-15 健康门禁按 ens5 断言 SK5 模式 | ✓ 已修（代码面） | C：install.sh:819-838 门禁 mode-aware（SK5 开断言 table 100、关断言 ens5 且不命中 table 100）；真机重验待 live-R4 |
| R2-BUG-16 重装不继承 proto/port | ✓ 已修（代码面） | C：install.sh:74-90 继承块（读既有 server.conf，显式 env 胜出）；`log()` 定义在 :39、继承块调用在 :71-81 之后（R3-BUG-6 同款）；真机重验待 live-R4 |
| R3-BUG-1 disable 停 sing-box 永不恢复 | ✓ 已修（代码面） | S：egress E09–E10（disable 重渲染 direct 配置后重起，singbox_restarted=true）；F：FI11；真机 disable 序列待 live-R4 |
| R3-BUG-2 verify.sh bundle SIGPIPE 141 | ✓ 已修（代码面） | C：verify.sh:373 列表存变量再 grep（tar 不再直连 grep -q）；沙箱态 panel 未起未实际跑通，待 live-R4 |
| R3-BUG-3 装树漏 systemd/ | ✓ 已修（代码面） | C：install.sh:355 已拷 `systemd/`；从 /opt 重跑真机态待 live-R4 |
| R3-BUG-4 路由核对用非本地源 10.8.0.2 | ✓ 已修（代码面） | C：verify.sh:587,714 与 test-egress.sh 均用 10.8.0.1；10.8.0.2 仅剩 test-egress.sh:11 注释警告 |
| R3-BUG-5 默认 .ovpn remote 是 IPv6 | ✓ 已修（代码面） | C：探测加 `-4`＋形状校验＋逐段 ≤255（见 R4-P2-3）；默认 remote 真机态待 live-R4 |
| R3-BUG-6 默认重跑 exit 127 | ✓ 已修（代码面） | C：`log()` 定义 :39 在继承块 :71-81 之前；默认重跑真机态待 live-R4 |
| R3-OBS-1 已登录会话偶发瞬时 401 自愈 | 观察（未立案，仍在） | 代码面无机制（单进程、secret.key 恒定、session_version 恒 1、会话 12h）；6 次出现、机制未定；live-R4 须盯是否再现 |

### O/P 新代码单列逐项验

| 项 | 结论 | 本轮证据 |
|---|---|---|
| O-1 set_sk5 只模式变化才重起 | ✓ | S：egress E01–E05（禁用态全量/无操作/fail_open-only 保存均为纯写盘，桩 run 0 次）；verify-integration §4c 两格（保存 200 且 run 0 次） |
| O-2 disable 重起失败诚实返回 | ✓ | S：egress E11–E13（死桩 disable 不抛，回 `singbox_restart_error`＋`restarted=false`，enabled=False 已存盘）；verify-integration §4c 第三格 |
| O-3 check_health fail-open 包 try 写 health.json | ✓ | F：FI11（disable 重起失败仍落 `failed_over_to_direct`，health.json 已写，detail 含重起失败）；S：egress E14–E16 |
| O-4 policy_routing_active 三条件 | ✓ | F：FI08/FI09（规则删/表空→false，重建→true）；S：egress E06–E10 |
| P-1 README 清单补 systemd/ | ✓ | C：README:72 含 `systemd/`，与 install.sh:355 一致 |
| P-2 IPv4 逐段 ≤255 | ✓ | P：awk 校验实测 999/256 拒、合法通过（见表 D R4-P2-3） |

### 复扫差集

- R1 33 条：31 条已修，2 条部分——R1-P1-13（systemctl 侧已修，裸 `exists()` 漏网 → **R5-P2-3**）、R1-P2-9（确认门在位，force 操作本身死路 → **R5-P2-2**）。
- R2 13 条：13 条已修。
- R3 16 条：16 条已修。
- R4 5 条：5 条已修。
- 真机 22 条：21 条已修（代码面；其中 BUG-3/BUG-6/BUG-8/R2-BUG-15/R2-BUG-16/R3-BUG-1～6 的守护进程/数据面行为待 live-R4），R3-OBS-1 仍是观察。
- **差集不为 ∅**——新增 R5-P2-1（重复建用户/吊销不存在用户报 500）、R5-P2-2（`init_pki(force=True)` 死路）、R5-P2-3（`server_status()` 裸 `exists()` 违反永不抛错承诺），共 3 条，全部 P2。

### 表 E 补正（live-R4 2026-11-12 12:52 落盘后）

live-R4（`docs/live-verify-R4.md` 全文已读）：S0–S4 全过，BUG-9 第五次复验修好，R4-P1-1 无操作保存 500 真机已修，R3-OBS-1 未复现；但新冒 4 项。表 E 三处改判：

| ID | 改判 | 依据 |
|---|---|---|
| R3-BUG-3 装树漏 systemd/ | **未真修**（原表写“已修（代码面）”作废） | live-R4 §11：/opt 树里 systemd/ 已有、files 格已过，但删源树后从 /opt 重跑仍死 → 见 R4-BUG-2 |
| R3-BUG-4 路由核对用非本地源 | **◐ 部分**（原表写“已修（代码面）”作废） | 源地址改对了，但期望串本身是错的 → 见 R4-BUG-4 |
| R3-OBS-1 偶发瞬时 401 | **观察关闭** | live-R4 全程约 15 次登录全 200、access log 无 401，未复现 |

### 表 F — live-R4 新发现 4 项（本轮复核）

| ID | 结论 | 本轮证据 |
|---|---|---|
| R4-BUG-1（高，产品）：连续 6 次开关触发 systemd 限流，sing-box 钉死 failed，面板 500 但盘上 enabled=true；手工拉起后裸重开无操作短路、策略永不恢复、流量静默直连 | **复现，未修** | F：FI14（策略删后重开是无操作短路，enabled=true 且 policy=false，守护进程活着）＋FI15（重起失败后盘上已是 enabled=true）；C：`_apply_policy()` 全树唯一调用点在 `enable()`（sk5_manager.py:745），`reset-failed` 全树 0 命中，`set_sk5` 先 `_save_config` 后调 enable/disable（:600 之后）；`via_sk5` 在探针失败时退化为 `bool(enabled)`（app.py:982），且探针走 SOCKS 直连、不经过策略路由——策略丢了面板仍宣称 via_sk5=true；`policy_routing_active=false` 本身是诚实的（live-R4 与 FI14 一致） |
| R4-BUG-2（高，产品）：删源树后从 /opt 重跑 install.sh，装树拷贝自拷 abort | **复现，未修** | P：沙箱逐字复现 `cp: '/tmp/bug2/agent' and '/tmp/bug2/agent' are the same file` ×5、exit 1；C：install.sh 拷贝行无自拷判断、无 `|| true`（第二行有，第一行没有），`set -e` 下 abort |
| R4-BUG-3（中，门禁）：verify.sh direct-forwarding 按模式不知情断言直连路由，SK5 开时按构造必红 | **确认，未修** | L：live-R4 §12 第一轮（SK5 开）该格 FAIL，原文 `FORWARD rules present but VPN source route lookup wrong: 1.1.1.1 from 10.8.0.1 dev tun1 table 100`；§4 变异 vh-w20 复现同款（见 §4） |
| R4-BUG-4（中，门禁）：route_checks 与 test-egress.sh §3 断言 `via 10.9.0.1 dev tun1`，内核点对点 tun 只印 `dev tun1 table 100` | **确认，未修** | P：harness 的 fake ip 改成真实内核形态（无 `via`）后基线即现两红（sk5-toggle-on detail `rule=1 table100=1 | vpn: 1.1.1.1 from 10.8.0.1 dev tun1 table 100 uid 0`、egress-crosscheck §3），与 live-R4 第二轮逐字一致；C：verify.sh:579-603 与 test-egress.sh §3 均含 `via 10.9.0.1 dev tun1` 期望串 |
| R4-OBS-1（观察）：/api/status 顶层 remote_ip/remote_warning 为 null | **澄清，非产品问题** | C：`remote_ip`/`remote_warning` 只在 `openvpn.*` 嵌套键下（app.py:950-954），顶层本无此键；R4 是读键错（与 S4 的顶层 `openvpn.clients` 读键错同族）；`_outward_ip()` 永不返回 None（显式 IP > 环境变量 > 公网探测 > 局域网地址 > 127.0.0.1） |

### 复扫差集（更新）

- R1 33 条：31 条已修，2 条部分——R1-P1-13 → **R5-P2-3**、R1-P2-9 → **R5-P2-2**。
- R2 13 条：13 条已修。
- R3 16 条：16 条已修（文档/代码面）。
- R4 5 条：5 条已修。
- 真机 22 条：19 条已修，R3-BUG-3 **未真修**（→R4-BUG-2）、R3-BUG-4 **部分**（→R4-BUG-4），R3-OBS-1 观察关闭。
- live-R4 新 4 项：R4-BUG-1（P1）、R4-BUG-2（P1）、R4-BUG-3（P2 门禁）、R4-BUG-4（P2 门禁），全部未修。
- **差集不为 ∅**——R5 新 3 条 P2（R5-P2-1/2/3）＋ live-R4 遗留 2 条 P1（R4-BUG-1/2）＋ 2 条 P2（R4-BUG-3/4），共 7 条。

## §4 门禁变异红证（Gate Mutation Red-Proofs）

方法：变异全部做在 /tmp 树副本上（原树不动）；每路变异后跑原门禁脚本，逐格核对红/绿是否精确落在变异点上。verify-integration.sh 23 格、verify.sh 23 格。基线：verify-integration 23/23（§1）；verify.sh 在沙箱 harness 下 20/3/0——3 红中有 2 红是 R4-BUG-4（门禁自身期望串错，见表 F），1 红是沙箱无直连 TCP 出站的环境红（sk5-egress-ip；live-R4 真机上该格 PASS）。

harness 说明（verify.sh）：fake `ip`（表感知；`route get` 按真实内核形态印 `dev tun1 table 100`、无 `via`）、fake `systemctl`（两单元 active、MainPID 读 PID 文件）、fake `sing-box`（1.11.15、check 验 JSON、run 睡眠）、fake `iptables`（-C 生效）、fake `easyrsa`，真 Flask 面板经自签 TLS 供在 8443 上，`/etc/openvpn-sk5-panel` 以 mount 命名空间绑定到 /tmp（真实 /etc 零写入）。变异循环日志：`/tmp/audit5-mut-out/`（`vi-*.log` / `vh-*.log`，`summary.txt`）。

### verify-integration.sh 变异矩阵

| 变异 | 目标格 | 实测红格 | 结论 |
|---|---|---|---|
| vi-ma：`/`→404、status 去登录态、cmd_get 置 error=None、agent_report 错 token 进 error、agent get_status 回 `{}` | 6,7,8,9,19,22,23 | 6,7,8,9,19,22（FAIL=6） | ◐ 部分：23 未红——V9（error=None）把 V8 的泄露一并盖住，两变异在同一读路径上互相掩盖；已拆 vi-mb2（仅泄露）与 vi-mc2（仅置空）重跑（见下） |
| vi-mb：status() 恒 500 | 12 | 12（FAIL=1） | ✓ 精确 |
| vi-mc：set_sk5 去模式判断（恒调 disable） | 13,14 | 13,14,15（FAIL=3） | ✓ 15 的红是累计计数器连带（run 3 次而非 1 次），同根 |
| vi-md：disable() 抛错 | 15 | 15（FAIL=1） | ✓ 精确（500、run 0） |
| vi-me：agent get_status 抛错 | 18 | 18（FAIL=1） | ✓ 精确（19 格因 done 条件不满足而不运行，属设计） |
| vi-mf：agent except 回空 error | 22 | 无红（FAIL=0） | ◐ 变异被设计掩盖：面板 agent_report 对空 error 有 fallback `"agent 执行失败"`，收据 error 恒非空；22 格的红证改由 vi-mc2（cmd_get 层）提供 |
| vi-mg：create_user 跳过 CA 检查直接成功 | 21 | 21（FAIL=1） | ✓ 精确（22/23 在 failed 分支内，不运行） |
| vi-mh：login 恒 401 | 10 | 10,11,12,13,14,15,17,18,20,21（FAIL=10） | ✓ 首红是 10，其余全是登录依赖格的预期级联；1–9 保持绿 |
| vi-mi：panel/app.py 语法破坏 | 3 | 3（FAIL=1，脚本提前退出） | ✓ 精确（首红是 3；1–2 绿） |
| vi-mj：_ensure_admin_password 空操作 | 4 | 4,10,11,12,13,14,15,17,18,20,21（FAIL=11） | ✓ 首红是 4，其余全是登录依赖格的预期级联；1–3、5–9 绿 |
| vi-mk：nodes_register 恒 400 | 11 | 11,17,18,20,21（FAIL=5） | ✓ 首红是 11，其余全是命令链依赖格；12–15 绿 |
| vi-ml：cmd_create 恒 400 | 17 | 17,18,20,21（FAIL=4） | ✓ 首红是 17，其余全是命令链依赖格 |
| vi-m6：index.html 两卡改名（入站卡→服务卡、链式出站卡→出口卡） | 7,8 | 7,8（FAIL=2） | ✓ 精确（注：门禁 grep 是子串匹配，CSS 注释也含“入站卡”，故须全量改名才红） |
| vi-m19：requirements.txt flask==99.99.99 | 2 | 无红（FAIL=0） | ◐ 变异打空：门禁装 venv 用裸 `pip install flask`，根本不读 requirements.txt；2 格的红证改走环境变异（PIP_INDEX_URL 指死址 → pip 失败 → 整门 SKIP，见补跑） |
| vi-m10：8443 被占用 | 1 | 全门 SKIP=1 | ✓ 精确（端口守卫生效，整门跳过而非假绿） |
| vi-m11：/etc 写 mid-run（sleep 25） | 5 | 无红（FAIL=0） | ◐ 变异未命中：gate 本轮 <25 秒跑完，写操作落在 AFTER 快照之后；已改 sleep 8＋mount 验活重跑（见补跑） |
| cell 16（agent 配置 0600） | 16 | —（无整门变异） | 自履行前置格，无产品变异可红；依赖已证：agent --once 配缺失文件时 exit 2（`config not found … run install-agent.sh first`），下游 18/21 格依赖该文件 |

### verify.sh 变异矩阵（基线 20/3/0；3 红 = R4-BUG-4 两格 + sk5-egress-ip 环境红）

| 变异 | 目标格 | 实测红格 | 结论 |
|---|---|---|---|
| vh-w1：install.sh 末尾加孤 `}` | syntax | syntax（FAIL=4，余 3 为基线红） | ✓ 精确 |
| vh-w2：删 systemd/openvpn-sk5-healthcheck.timer | files | files（FAIL=4） | ✓ 精确 |
| vh-w3：install.sh 拷贝行去 agent | install-copies-agent | install-copies-agent（FAIL=4） | ✓ 精确 |
| vh-w8：starter heredoc tun 地址 10.9.0.1→10.9.0.2 | starter-template-consistency | starter-template-consistency（FAIL=4） | ✓ 精确 |
| vh-w14：_build_agent_bundle 跳过 agent/ | agent-bundle | agent-bundle（FAIL=4） | ✓ 精确 |
| vh-w15：/install-agent.sh 路由恒 404 | install-agent-script | install-agent-script（FAIL=4） | ✓ 精确 |
| vh-w21：/api/sk5/enable 恒 500 | sk5-enable-endpoint | sk5-enable-endpoint（FAIL=4） | ✓ 精确 |
| vh-w18：policy-routing.sh apply 空操作 | sk5-toggle-on（已红） | toggle-on 仍红，但 detail 从基线 `rule=1 table100=1 / dev tun1 table 100` 翻为 `rule=0 table100=0 / via ens5`（FAIL=3 不变） | ✓ 该格虽因 R4-BUG-4 已红，仍能分辨产品故障（路由缺失 vs 期望串错）；disable/direct/enable-endpoint 仍绿 |
| vh-w19：policy-routing.sh remove 空操作 | sk5-disable, direct-forwarding | sk5-disable（`routing did not revert: rule=1 table100=1`）＋direct-forwarding（FAIL=5） | ✓ 精确，同根两格 |
| vh-w20：预热只 enable 不 disable（SK5 留开） | direct-forwarding（R4-BUG-3 复现） | direct-forwarding 红（与 live-R4 §12 同款报文），toggle 系 4 格 SKIP（FAIL=1） | ✓ R4-BUG-3 在沙箱复现：SK5 开时该格按构造必红 |
| vh-w4：装树删 agent/agent.py | installed-agent-tree | installed-agent-tree（FAIL=4） | ✓ 精确 |
| vh-w5：不起 fake openvpn 进程 | openvpn | 无新增红（FAIL=3 不变） | ◐ 变异打在 pgrep 分支上，但本沙箱 PID 1 即 systemd，cell 走 `is-active` 分支先过；补跑 w5b（is-active 亦断＋无进程）见下 |
| vh-w6：FAKE_SINGBOX_MODE=version-old | sing-box-version | sing-box-version（`1.8.0`，FAIL=4） | ✓ 精确 |
| vh-w7：hook 写坏 sing-box.json | sing-box-config | sing-box-config（FAIL=4） | ✓ 精确 |
| vh-w9：hook 杀 sing-box＋删 PID，SINGBOX_DOWN=1 | sing-box-running | sing-box-running 红，steady SKIP（FAIL=4） | ✓ 精确（steady 跳过属设计） |
| vh-w10：hook 写死 PID 999999 | sing-box-steady | sing-box-steady 红（running 仍绿，is-active 认活进程） | ✓ 精确（running/steady 分层分辨） |
| vh-w11：hook 杀面板 | panel-reachable | panel-reachable 红，其余面板依赖 9 格 SKIP（FAIL=1） | ✓ 首红精确，级联全是跳过 |
| vh-w12：hook 换错管理员密码 | panel-login | panel-login 红（401），下游 8 格 SKIP（FAIL=1） | ✓ 首红精确，级联全是跳过 |
| vh-w13：FAKE_SYSTEMCTL_OVPN_DOWN=1 | panel-status | panel-status 红（`openvpn.running=false`）；openvpn 格仍绿（pgrep 兜底找到 fake 进程） | ✓ 精确；与 w5 互补：is-active 断＋进程在 → 仅 panel-status 红；双信号齐断见 w5b |
| vh-w16：hook 换 easyrsa 为 exit-1 桩 | user-ovpn | user-ovpn 红（`command failed (… easyrsa.sh build-client …)`，FAIL=4） | ✓ 精确（注：本轮 sk5-egress-ip 的红细节为 `GET /api/status failed` 而非基线的 `egress.ip empty`，同格瞬时失败，不改结论；hook 退出后 easyrsa 已恢复） |

### 补跑（拆分混淆＋环境型红证）
| vi-mb2：仅 agent_report 错 token 进 error | 23 | 23（FAIL=1；22 绿） | ✓ 拆分后精确：泄露被 23 格抓到 |
| vi-mc2：仅 cmd_get 置 error=None | 22 | 22（FAIL=1；23 绿） | ✓ 拆分后精确 |
| vi-m19env：PIP_INDEX_URL 指死址 | 2 | 整门 SKIP（PASS=1：仅端口空闲格，FAIL=0） | ✓ 2 格的契约是环境失败时 SKIP 而非假绿；requirements.txt 本就不被门禁读取 |
| vi-m11r：/etc 写 mid-run（sleep 8＋mount 验活） | 5 | 5（FAIL=1；SEED-OK、WRITE-OK、前后 hash＋mtime 均变） | ✓ 精确 |
| vh-w5b：OVPN_DOWN=1＋无 openvpn 进程 | openvpn, panel-status | openvpn 红＋panel-status 红，direct-forwarding SKIP（FAIL=5） | ✓ 精确；与 w5/w13 三者合起来刻画了该格的双信号逻辑（is-active 或 pgrep 任一活即绿） |

### §4 结论

- verify-integration.sh 23 格：22 格有独立红证；cell 16（agent 配置 0600）是自履行前置格，无产品变异可红，其下游依赖已证（agent --once 配缺失文件时 exit 2）。vi-mf 说明面板对空 error 有 `"agent 执行失败"` fallback——这是设计上的兜底，不是缺陷；22 格的红证在 cmd_get 层（vi-mc2）。
- verify.sh 23 格：21 格有独立红证；stub-socks5 是门禁自带桩、无产品代码可变异；sk5-egress-ip 在沙箱环境红（无直连 TCP 出站），live-R4 真机上该格 PASS。toggle-on / egress-crosscheck 两格基线已红（R4-BUG-4 门禁期望串错），但 w18 证明 toggle-on 仍能分辨产品故障（detail 从 `rule=1 table100=1` 翻为 `rule=0 table100=0`）。
- §4 未产生新的产品立案：三处“◐”均已由补跑闭合；门禁自身的两项缺陷就是 live-R4 已立的 R4-BUG-3、R4-BUG-4。

## 裁决

**不能交付。差集不为 ∅，共 7 条：P0 0、P1 2、P2 5。**

| ID | 级别 | 一句话 |
|---|---|---|
| R4-BUG-1 | P1 | 连续开关触 systemd 限流后 sing-box 钉死 failed，盘上 enabled=true；手工拉起后裸重开无操作短路、策略永不恢复、流量静默直连（kill-switch 承诺被静默绕过） |
| R4-BUG-2 | P1 | 删源树后从 /opt 重跑 install.sh，装树拷贝自拷 abort、exit 1（R3-BUG-3 的用户场景仍死） |
| R5-P2-1 | P2 | 重复建用户 / 吊销未知用户返回 500 而非 409/404（行为对、状态码错） |
| R5-P2-2 | P2 | `init_pki(force=True)` 是死路：force 未传进 easyrsa.sh，CA 已存在时恒拒，面板发起的重建 CA 永远失败 |
| R5-P2-3 | P2 | `server_status()` 裸 `Path.exists()` 在不可读路径上抛 PermissionError，违背“永不抛错”承诺（egress 侧同族已修，core 漏网） |
| R4-BUG-3 | P2（门禁） | verify.sh direct-forwarding 按模式不知情断言直连路由，SK5 开时按构造必红 |
| R4-BUG-4 | P2（门禁） | route_checks 与 test-egress.sh §3 断言 `via 10.9.0.1 dev tun1`，内核点对点 tun 只印 `dev tun1 table 100` |

复扫口径：R1 33（31 修、2 部分→R5-P2-2/3）＋R2 13 全修＋R3 16 全修＋R4 5 全修＋真机 22（19 修、R3-BUG-3 未真修→R4-BUG-2、R3-BUG-4 部分→R4-BUG-4、R3-OBS-1 观察关闭）＋live-R4 新 4 项全未修。套件：egress 20/20、agent 19/19、Worker 56/56、verify-integration 23/23、Flask 61/62（R5-P2-1）、Core 28/29（R5-P2-2）。故障注入 egress 14/14、panel 8/8 全部诚实。门禁变异：verify-integration 23 格、verify.sh 23 格逐格红证完毕（41 路变异运行，含 5 路补跑）。

诚实边界：Cloudflare 真实 wrangler deploy 未做（KV id 仍占位）；easy-rsa 真实签发流程只认沙箱 stub 以外的证据；本轮全部结论来自 /tmp 副本与沙箱，live-R4 是最新真机证据（S0–S4 全过，但 4 项新 bug 阻塞交付）。下一步：修上述 7 条后，再做一轮全量全局回头看（换推导方法）＋真机复跑，差集 ∅ 才交付。

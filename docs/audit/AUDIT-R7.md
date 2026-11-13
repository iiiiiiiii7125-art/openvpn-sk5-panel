# AUDIT-R7 — 全量全局回头看（交付前）

- 审计员：独立审计路（未参与建设与修复路 A–X；单审计员边做边写，不派子代理）
- 日期：2026-11-12（CST）
- 范围：`~/workspace/openvpn-sk5-panel/` 全树（与 R1–R6 同等广度）
- 推导方法：**从零用户旅程推导**（与 R1 逐文件通读、R2 旅程推导、R3 宣称驱动、R4 不变量驱动、R5 故障注入、R6 状态转移均不同）——假装自己是一个只看文档的新运维，从裸机开始按文档一步步走到可用链路（装面板→建服务→加用户→填 SK5→一键启用→验出口→断网保护→改密→吊销→重建 CA），每一步只用文档给出的命令与界面，文档缺步、错步、与行为不符即立案；再叠加全量复扫（历史全部发现逐条复现定性）与 U/V/W/X 新代码逐项行为验证。R2 也是旅程推导，但 R2 的旅程是“按已知的正确路径走一遍找缺口”；本轮的旅程是“只信文档、不信记忆”，以文档为唯一向导，文档本身即被审对象。
- 测试一律在 `/tmp` 副本（`/tmp/r7` 树副本、`/tmp/r7-tests/` 自写套件）上跑；未动项目原文件；未动 `/etc`（探针进 `unshare -rm` 挂载命名空间，`/etc` 绑 /tmp；事后 mtime 核对见 §8）；未动任何真机。live-6 与本轮并行，凡需真机行为复核的项一律写“待 live-6”，不提前判通过。
- 语法基线：4 个 Python 文件 `py_compile` 全绿；7 个 shell 脚本 `bash -n` 全绿；Worker `node --check` 全绿（见 §0）。

## §0 树版本与 U/V/W/X 改动确认

当前树是 U/V/W/X 修复后＋主控亲手改的 verify-integration §4c 格 B 改写。文件 mtime（UTC，原树）：

| 文件 | mtime (UTC) | 说明 |
|---|---|---|
| panel/app.py | 2026-11-12 08:07:29 | U 路：status() policy 判据＋check_health 三条件＋failover_failed＋set_sk5 有效态检查 |
| egress/sk5_manager.py | 2026-11-12 08:07:40 | U 路：同上（egress 侧） |
| egress/test-egress.sh | 2026-11-12 08:40:51 | X 路：§6 loopback 改 SKIP |
| verify-integration.sh | 2026-11-12 08:14:24 | W 路：登录 0600 文件；主控：§4c 格 B 改写为真实翻转（28 格） |
| cloudflare/src/index.js | 2026-11-12 08:05:38 | W 路：handleCreateCmd 加 `queued:true` |
| README.md | 2026-11-12 08:06:36 | V 路：门禁数 20→27（疑点：现为 28，见 R7-P2-6）＋路由源＋行号＋安全节改写 |
| cloudflare/README.md | 2026-11-12 08:06:36 | V 路：set_sk5 部分合并口径 |
| cloudflare/server-mode.md | 2026-11-12 08:06:15 | V 路：同上 |
| install.sh | 2026-11-12 05:59:49 | R 路（未动） |
| core/openvpn_manager.py | 2026-11-12 06:01:40 | S 路（未动） |
| core/easyrsa.sh | 2026-11-12 06:01:36 | S 路（未动） |
| agent/agent.py | 2026-11-12 00:58:12 | E/H 路（未动） |
| panel/templates/index.html | 2026-11-12 02:49:17 | L 路（未动） |
| verify.sh | 2026-11-12 07:29:19 | 主控双机制检查（未动） |
| docs/security.md | 2026-11-12 02:49:17 | 未动（R6-P2-5 的三假宣称在根 README，不在此） |
| egress/README.md | 2026-11-12 02:49:17 | 未动 |
| panel/README.md | 2026-11-12 02:49:13 | 未动 |

语法基线（本轮在 `/tmp/r7` 副本上实测）：`panel/app.py`、`egress/sk5_manager.py`、`core/openvpn_manager.py`、`agent/agent.py` 四文件 `py_compile` 全绿；`install.sh`、`verify.sh`、`verify-integration.sh`、`egress/test-egress.sh`、`egress/policy-routing.sh`、`core/easyrsa.sh`、`agent/install-agent.sh` 七脚本 `bash -n` 全绿；`cloudflare/src/index.js` `node --check` 全绿。行数：`panel/app.py` 1858 行（R6 时约 1245＋后续 U 路扩增——注：R6 报告未给行数，此处仅作本轮基线记录）、`egress/sk5_manager.py` 1088 行、`core/openvpn_manager.py` 1230 行、`cloudflare/src/index.js` 1128 行、`agent/agent.py` 910 行。

/tmp 资产现状（本轮开工时实测）：`/tmp/s-tests`、`/tmp/s-venv`、`/tmp/fixq-test`、`/tmp/fixt`、`/tmp/audit6-tests` 全部已被清，不可复用；仅存 `/tmp/fixx/`（X 矩阵 harness：run-case.sh、run-fixed.sh、test-egress-orig.sh、fakebin/、etc-panel/）与 `/tmp/fixx-test-egress-fixed.sh`。本轮五套件与全部探针均为自写（`/tmp/r7-tests/`），口径与 R5/R6 同款（fakebin 桩＋unshare 命名空间＋venv），并注明重建事实。

## §1 U/V/W/X 新代码逐项行为验证（本轮亲自重跑，零 monkeypatch 走真实代码路径）

探针：`/tmp/r7-tests/via_toggle_probe.py`（真实 Flask test_client 走 `POST /api/sk5`、`POST /api/sk5/enable`、`GET /api/status`；真实 `egress/sk5_manager.py`；桩只替外部世界：fake `ip`/`systemctl`/`sing-box`/`curl`/`iptables`/`sysctl`；`unshare -rm` 下 `/etc/sysctl.d` 绑 /tmp，真实 `/etc` 零写入）。状态缓存说明：`GET /api/status` 有 10 秒缓存（`panel/app.py:901-918`），每格之间睡 11 秒；重启计数以 fake systemctl 的 `restart` 调用次数为准。

### §1a U 路（R6-P1-1＋P2-1＋P2-2）——全部行为验证通过，29/29

| 格 | 期望 | 实测 |
|---|---|---|
| via_sk5 B（策略在位＋探针活） | via_sk5=true，ip=203.0.113.7 | PASS，`egress.ip=203.0.113.7`，`policy_routing_active=true` |
| via_sk5 A（策略缺失＋探针活） | via_sk5=false，ip=None，error 点名策略路由 | PASS，`via_sk5=false`，`ip=None`，error=“SK5 已启用但策略路由未生效，出口未经过 SK5”；`sk5.policy_routing_active=false` 诚实 |
| via_sk5 C（策略缺失＋探针死） | via_sk5=false，ip=None，error 在 | PASS，同上（R6 撒谎格现已诚实） |
| via_sk5 D（策略在位＋探针死） | via_sk5=true（kill-switch 黑洞态），ip=None | PASS，`via_sk5=true`，`ip=None` |
| T1 全字段同值保存 | ＋0 重起 | PASS，1→1 |
| T2 toggle-only enable（已健康启用） | ＋0 重起 | PASS，1→1 |
| T3 `POST /api/sk5/enable`（已健康启用） | ＋0 重起 | PASS，1→1 |
| T4 全字段保存附带未变 `udp_over_tcp:false` | ＋0 重起 | PASS，1→1 |
| T5 toggle-only disable（真翻转） | ＋1 重起 | PASS，1→2 |
| T6 toggle-only enable（真翻转） | ＋1 重起 | PASS，2→3 |
| T7 host/port 变更（已启用链） | ＋1 重起 | PASS，3→4 |
| R1 策略丢失后全表单重开 | repaired=true，＋0 重起 | PASS，`repair_detail=['policy routing re-applied']`，5→5 |
| R2 daemon 死后全表单重开 | repaired=true，＋1 重起 | PASS，`repair_detail=['sing-box restarted']`，5→6 |
| H1 健康三条件全齐 | healthy=true，action=none | PASS，`tcp_ok=True udp_ok=False egress=203.0.113.7`（UDP 假阴性是沙箱 EPERM 环境所致，见 §8；healthy 只看 TCP＋daemon＋策略） |
| H2 策略缺失＋fail-closed | action=policy_missing（不是 blackholed） | PASS，detail 明示“VPN 流量直连、非黑洞、须重开修复” |
| H3 daemon 死＋fail-open＋模板缺失 | action=failover_failed，盘上仍 enabled=true | PASS，detail=“fail-over did not run: template not found: …/no-such-template.json”；盘上 enabled=true 保留 |
| H4 daemon 死＋fail-open（模板在） | action=failed_over_to_direct，盘上翻为 enabled=false | PASS，detail=“sing-box not running”；盘上 enabled=false |
| H5 daemon 死＋fail-closed＋策略在位 | action=blackholed_kill_switch | PASS |
| H6 daemon 死＋fail-closed＋策略缺失 | action=policy_missing | PASS |

合计 **29/29**。R6-P1-1、R6-P2-1、R6-P2-2 三条已修（行为实证，非代码面采信）。取证说明：首跑 24/29，五格 FAIL 全是探针/桩侧问题，已逐项定因并重跑归零——(1) R1/R2 断言读错层级（`repaired` 在 `body['sk5']` 里，不在顶层）；(2) T5/H4 的 FAIL 是我方 fake iptables `-D` 的 bug：删最后一行时 `grep -v` 退出 1 致 `mv` 被跳过、文件未变、又恒 exit 0，`policy-routing.sh` 的 `iptables_del` 循环死循环，`disable()` 在 `_remove_policy` 上 30 秒超时（日志为证：首跑 `sysctl.log` 里一次 `systemctl stop` 都没有，T5 的 30 秒正好是 `_run` 超时窗）。桩已修（`grep … || true; mv`），H3 的模板缺失注入亦由 str 改为 `Path` 重做。教训与 R6 的 F15 同族：探针失败先查桩，再判产品。

### §1b V 路（R6-P2-4/5/6 文档三条）——两条全修，一条部分

| 项 | 本轮核对 | 结论 |
|---|---|---|
| P2-5 安全节三假宣称 | 根 README 安全节现为“改密（不强制）…登录即给完整 admin 会话”、“登录限流（仅 IP 维）”、“权限（单管理员）”，三处旧词（用户名维／普通用户／首登强制）全树零命中 | 已修 |
| P2-6 set_sk5 全量覆盖 | `cloudflare/README.md:130` 现称“部分合并”，`:216` 称 Flask 侧同样部分合并；`cloudflare/server-mode.md:19` 对照表称“部分合并（agent 缺字段保留已存值…）” | 已修 |
| P2-4① 门禁数 | 根 README:224 仍称 `verify-integration.sh` “**PASS=27 FAIL=0 SKIP=0**”，现门禁为 **28 格**（§4c 格 B 改写后 27→28） | **未同步**——见 R7-P2-6（V 修 20→27 后，主控改格 B 又＋1，README 没跟上；与 R6-P2-4① 同款复发） |
| P2-4② 路由源 10.8.0.2 | 根 README:165 已改 10.8.0.1；但 `egress/README.md:41`（表格行“`ip route get ... from 10.8.0.2`”）与 `:171`（排障“`route get ... from 10.8.0.2` 是否走了 table 100”）仍是错的 | **部分**——见 R7-P2-7（V 只修了根 README 一处，同错在 egress/README 漏网两处） |
| P2-4③ starter 行号 | 根 README:202 现称 `install.sh:531-558`，实测 `cat` 在 :531、`EOF` 在 :558，一致 | 已修（根 README）；但 `verify.sh:231` 的注释仍称 `install.sh:430-452`，见 R7-P2-6 附带 |

### §1c W 路（R6-P2-3＋P2-7）——全部行为验证通过

- **P2-3 登录密码不进 argv**：`verify-integration.sh:272-286` 现为 python 写 0600 临时文件＋`curl --data @file`，用完 `rm -f`（:286），另有 `trap cleanup EXIT`（:49）。本轮同款命令实测（慢速本地 HTTP 服务，curl 运行期间读 `/proc/<pid>/cmdline`）：cmdline 为 `curl -s -o /dev/null -w %{http_code} -H Content-Type: application/json --data @/tmp/r7-tests/probe/login-payload.json http://127.0.0.1:18099/api/login`，**密码明文零命中**；文件模式 0600。已修。
- **P2-7 Worker `queued:true`**：`cloudflare/src/index.js:733-734` 的 `handleCreateCmd` 现返回 `{ok:true, cmd_id, node, action, status:"queued", queued:true}`，与文件头注释（:37、:758）一致；Worker 套件加断言格（见 §5）实测 202＋`queued===true`。已修。

### §1d X 路（R5-BUG-1，§6 loopback 改 SKIP）——矩阵四格亲自重跑，全部符合预期

驱动复用 `/tmp/fixx/run-case.sh`；`run-fixed.sh` 经 diff 确认与当前树 `egress/test-egress.sh` 逐字节一致、仅 CFG 路径不同（:38）。

| 格 | 端点 | 期望 | 实测 |
|---|---|---|---|
| S2 桩同 IP | 127.0.0.1，direct=SK5=2600:1f13:… | §6 SKIP，exit 0 | PASS，5/0/2，SKIP 文案点名 loopback |
| M1 商家同 IP | proxy.iproyal.net，direct=SK5=198.51.100.9 | §6 FAIL，exit 1 | PASS，5/1/1，“SK5 egress IP equals direct IP -- chain is not in effect” |
| M2 商家不同 IP | proxy.iproyal.net，198.51.100.9 vs 203.0.113.7 | §6 PASS，exit 0 | PASS，6/0/1 |
| S3 桩不可达 | 127.0.0.1，SK5 空 | §6 FAIL（取不到 IP），exit 1 | PASS，5/1/1，“could not fetch egress IP via SK5” |
| 阴性对照（旧脚本＋桩同 IP） | 127.0.0.1，同 IP | 旧脚本 FAIL 5/1/1 | PASS（复现），旧脚本逐字复现 live-R5 签名 FAIL 5/1/1，exit 1 |

R5-BUG-1 已修。附带：X 的修法只动 §6 的 loopback 分支，远端端点仍保留全比较（M1 证明检查仍咬人）；`verify.sh` 的 crosscheck 格本身未动（只取 test-egress.sh 的退出码），故关态全绿依赖本修＋live-6 真机复验（见 §8）。


## §2 从零用户旅程推导（本轮推导方法）

假装只看文档的新运维，从裸机按文档走到可用链路。每步只用文档给出的命令与界面；文档缺步、错步、与行为不符即立案。真机行为（安装全过程、真实 easy-rsa 签发、真实 sing-box/openvpn 守护进程、真实 UDP 数据面）沙箱做不了的，标“待 live-6”，不预判通过。

### 旅程逐步

| 步 | 文档给出的路 | 核对结果 |
|---|---|---|
| 0. 取代码 | 根 README：`git clone <本仓库地址> openvpn-sk5-panel` | **缺步**：`<本仓库地址>` 是占位符，全树无一处给出真实仓库 URL。新运维到这步即卡住，只能靠仓库外知识。见 R7-P2-10 附带 |
| 1. 一键安装 | `bash install.sh`（默认 UDP 1194）或 `OVPN_PROTO=tcp OVPN_PORT=443 bash install.sh`；步骤 1–8（FLMX 目标断言、apt、sing-box 1.11.15＋tun2socks 2.7.0、复制四目录＋systemd、PKI＋server.conf、直连 sing-box 配置、TLS 证书＋单元启动、健康门禁） | 步骤与 `install.sh` 代码逐项对得上（FLMX 断言 :150–157、健康门禁 :771–824 均在位；`OVPN_SUBNET` 只进 NAT/FORWARD 规则 :630–653，与“改了也只影响 NAT 规则”一致）。安装全过程本身沙箱跑不了（apt/systemd/真二进制），待 live-6 |
| 2. Cloudflare 部署 | `wrangler kv namespace create` → 填 id → `wrangler secret put ADMIN_PASSWORD` → `wrangler deploy`；agent 两步命令（-k＋sha256sum -c＋--node-name） | 命令与 `wrangler.toml`＋Worker 代码一致；但真实部署卡在登录（见 §6）。两步命令与 Worker 套件 W07（-k＋sha256sum -c＋--node-name 全在）一致；live-R2 的 BUG-12 同款已修 |
| 3. 登录 | 浏览器开 `https://<IP>:8443`，初始密码登录；密码在 `/etc/openvpn-sk5-panel/admin.pass`（0600） | 与 `_ensure_admin_password` 一致；Flask 套件登录/限流全过。注意：沙箱内以 root 跑面板会把密码写进真实 /etc（见 §4c 事故），新运维在测试机上无此问题 |
| 4. 建服务 | 确认协议/端口（UDP 1194 或 TCP 443），对外地址默认自动探测、可手动填，点启动；状态页看服务状态与在线用户 | UI 在位：`index.html:408` 对外地址栏、`:419–420` 启动/重启按钮；`POST /api/openvpn/server` 透传 `allow_port_change` 与 `server_ip`（app.py:1012–1069 已核）；`GET /api/openvpn/public-ip` 在位。限制“对外地址在 Cloudflare 模式下暂不起作用”已在 README 明文写出（观察-1），不立案 |
| 5. 加用户 | 填用户名（`[a-zA-Z0-9_-]{1,32}`，`server` 与 `OpenVPN-CA` 保留），点创建，下载 `.ovpn` | Flask 套件用户 CRUD 全过（409/404/403 映射）；保留名校验在 core；吊销后须重启的提示在前端落点（`index.html:753` 回退文案）与 DELETE 回执 `needs_restart:true` 一致 |
| 6. 填 SK5＋一键启用 | 填 host/端口/用户名/密码；`fail_open` 默认关；`udp_over_tcp` 默认关；勾选启用保存→渲染 sing-box 配置、重启 sing-box、挂 table 100 | via/toggle 探针 29/29 行为证实；X 矩阵证实出口切换。商家端口 1001 还是 9000 文档只写默认 1001，用户至今未确认（见 §8 未验）——文档未把“待确认”写出来，新运维会直接按 1001 填，若商家实为 9000 则首填即错。见 R7-P2-10 附带 |
| 7. 验出口 | 状态页“当前出口 IP”变 SK5 的 IP；或跑 `bash /opt/openvpn-sk5-panel/egress/test-egress.sh` | verify.sh 限定跑：sk5-toggle-on／egress-crosscheck／sk5-egress-ip 三格 PASS；状态页 `via_sk5` 在 Flask 侧已修（U），但 **Worker 侧仍撒谎**——见 R7-P1-1 |
| 8. 断网保护 | 默认 fail_open=false 时链路死即黑洞，绝不悄悄走直连；fail_open=true 时健康检查撤 table 100，单向（须人工重开） | check_health 六格 H1–H6 全过（§1a）；fail-over 单向性在根 README 与 egress/README 均已写明 |
| 9. 改密 | 顶栏「修改密码」按钮（`POST /api/change-password`），新密码 ≥12 位含字母＋数字，改后全部旧会话作废 | Flask 套件改密五格全过（错旧 401／弱 400／成功 200／旧会话失效／新登录 200）；UI 按钮在位（R6 已核） |
| 10. 吊销 | 用户行点吊销，须重启 OpenVPN 服务才对新连接生效 | 前端提示＋后端 `needs_restart:true` 一致；CRL 只在启动时读（core/README 与代码一致） |
| 11. 重建 CA | —— | **缺步：无路可走**。面板无重建 CA 的按钮、无 `/api/openvpn/init-pki` 路由、文档无任何重建流程；`init_pki` 只存在于 agent 白名单（`action_init_pki`，force 须并传 confirm=true），须靠未文档化的手写 `POST /api/cmd` 才能触发。core 的 `init_pki(force=True)` 本身已修好（R5-P2-2，core 套件 21/21），但从面板/文档出发的操作员够不着它。见 R7-P2-9 |

### 旅程立案小结

- **R7-P2-9**（P2）：重建 CA 无面板路径。`init_pki` 有 agent 动作与 force＋confirm 双重确认，但面板无入口、无路由、文档无流程；“重建 CA”这一步在旅程里是断的。修法任选其一：面板加一个带二次确认的重建 CA 入口，或文档写明手写 `/api/cmd` 的完整命令与后果。
- **R7-P2-10**（P2，合为一号）：① `git clone <本仓库地址>` 占位符，全树无真实仓库地址；② SK5 端口 1001/9000 哪个是 SOCKS5 至今未确认，文档却只写默认 1001，未标注“待用户确认”。两处都是新运维首填即可能踩错的缺口。

## §3 全量复扫（历史 105 条逐条定性）

复扫宇宙：R1 33＋R2 13＋R3 16＋R4 5＋R5 3 新＋R6 8＋live 27（R1 9＋R2 7＋R3 6＋R4 4＋R5 1）＝105 条。定性口径：**已修**＝本轮实测或代码未动＋上轮实证仍有效（注明证据来源）；**部分**＝修了一半或文档未同步；**复发**＝同款在新位置重现，本轮重新立案；**未验**＝须真机/部署，沙箱无法判定。U/V/W/X 修复项的本轮证据见 §1、§4、§5；其余“代码未动”项的证据沿用 R6 §3 的实证记录（本轮逐项核对了代码未动——以 `git` 树版本与 R6 基线一致为准，见 §0）。

### R1（33 条）

| 项 | R7 状态 | 证据 |
|---|---|---|
| P0-1 202 当成功 | **未验（部署态）** | Worker 套件 28/28（W11/W12 202 只排队）；真实 Worker 从未部署，见 §6 |
| P0-2 单字段 set_sk5 必败 | 已修 | Worker W16/W17＋agent A06–A08＋Flask F-单字段 |
| P0-3 bundle/install-agent.sh 404 | **部分** | 逻辑已修（W22–W27：无 origin 503、有源站 200、篡改 502）；部署态未验 |
| P0-4 SK5 密码保存清空 | 已修 | Flask 46/46、agent A07–A08、egress 20/20 |
| P0-5 secret.key 随树发货 | 已修 | 树内零命中（§0）；secret 路径 env＞/etc＞data |
| P1-1 status 20 秒 | 已修 | 代码未动（R6 实证：复用已探 IP＋10 秒缓存） |
| P1-2 无节点/agent 界面 | 已修 | index.html 节点区＋verify-integration 28/28 |
| P1-3 Worker 登录不限流 | 已修 | Worker W01–W03（5 次→429＋Retry-After） |
| P1-4 Worker 无吊销/轮换 | 已修 | Worker W18–W21 |
| P1-5 Worker 快照错位 | **部分（复发同族）** | 快照归一化本身已修；但 `via_sk5` 在 Worker 侧仍按 enabled 补，见 **R7-P1-1** |
| P1-6 sent 无重投 | 已修 | Worker W28（上限 3→failed）＋Flask `SENT_MAX_RETRIES=3` |
| P1-7 改密接口＋首登强制改密 | **部分（按设计）** | 改密 API＋UI 已修（Flask 46/46）；首登强制改密从未实现，文档已按 V 改诚实（R6-P2-5 已修），不另立案 |
| P1-8 check_health 死开关 | 已修 | timer＋service 在位；H1–H6 六格行为证实 |
| P1-9 策略路由无持久化＋重跑覆盖 SK5 配置 | 已修 | policy service 在位；live-R4 重跑通过（代码未动） |
| P1-10 create_server 不幂等 | 已修 | agent A11–A12＋core 21/21 |
| P1-11 入口端口无占用检查 | 已修 | core C21（占用拒）＋C-改口格 |
| P1-12 UoT 探针密码写 /tmp 明文 | 已修 | 代码未动（mkdtemp 0700＋配置 0600） |
| P1-13 core systemctl 无超时/保护 | 已修 | core C19（nobody 下不抛）＋timeout=10 |
| P1-14 server-mode.md 过时 | 已修 | V 修完 set_sk5 行（R6-P2-6 已修）；其余行 R6 已闭合 |
| P1-15 cloudflare/README set_sk5 假宣称 | 已修 | V 修完（§1b） |
| P2-1 限流进程内内存＋无 ProxyFix | 已修 | 代码未动（SQLite＋OVPN_TRUSTED_PROXY） |
| P2-2 agent 不校验 sing-box 版本 | 已修 | 代码未动（`_install_singbox` 比对钉死版本） |
| P2-3 --once 失败仍返回 0 | 已修 | agent A20–A22（不可达→-1／--once→1） |
| P2-4 bundle 确定性 | 已修 | 代码未动（walk 双 sorted；Flask bundle sha256 与字节一致） |
| P2-5 密码哈希 SHA-256 | 已修 | Flask 46/46（bcrypt `$2b$`＋透明迁移） |
| P2-6 OVPN_DNS 被忽略 | 已修 | 代码未动（render 取 dns or OVPN_DNS or 默认） |
| P2-7 PANEL_ADMIN_PASSWORD_FILE 死变量 | 已修 | 代码未动（死变量已删） |
| P2-8 密码进 curl -d argv | 已修 | W 修完 verify-integration（§1c /proc 实测）；install.sh/verify.sh 早已修 |
| P2-9 init_pki force 无确认 | 已修 | 代码未动（force 须并传 confirm=true）；但面板无入口，见 R7-P2-9 |
| P2-10 .ovpn 不验用户状态 | 已修 | Flask 46/46（吊销 403、未知 404） |
| P2-11 UoT 固定 /tmp＋manifest raise | 已修 | 代码未动（mkdtemp＋多 manifest 轮询） |
| P2-12 两处文档过时 | 已修 | 见 §7 |
| P2-13 flmx-reference 过时 | **部分** | 1-13/§103 已更新；但 §1-19/1-30 的 ConfigHash/AppliedHash 仍称“照抄”，代码里根本没有，见 **R7-P2-8** |

### R2（13 条）——全部已修

P1-1 BUG-9（core C18 真机行解析＋live-R5 第五轮复验）；P1-2 改密 UI（Flask 46/46＋按钮在位）；P1-3 旧 CN 证书（core 21/21 legacy 分支）；P1-4 已登录调 /api/status（verify-integration 28/28；MUT-C 本轮重跑 17/3/3，panel-status＋sk5-egress-ip 双红）；P1-5 files 格含 healthcheck/policy（MUT-D 本轮重跑 18/2/3，files 红）；P2-1 /etc 快照比对；P2-2 DATA_DIR＋.gitignore；P2-3 哈希钉死宣称；P2-4 server-mode https；P2-5 flmx-reference；P2-6 sing-box-config 报错已正（verify.sh 限定跑第二轮 PASS）；P2-7 fail-open 单向性（两 README 均已写明）；P2-8 starter heredoc＋一致性门（verify.sh 限定跑 PASS，install.sh:531-558）。

### R3（16 条）——全部已修

P1-1 Worker 重投上限（W28）；P1-2 旧一键命令（README 与 agent/README 均为两步命令）；P2-1 server-mode install 接口注记；P2-2 fail-open 路由存在注记；P2-3 密码哈希 bcrypt 注记；P2-4 复制清单含 agent/；P2-5/6 cloudflare README fail-closed＋https；P2-7 flmx-reference；P2-8 render_server_conf 参数注记；P2-9 check_health timer 注记；P2-10 index.js 注释已正；P2-11 rotate 200（W18）；P2-12 poll node_name 401（W09）；P2-13 三字段 shellQuote（代码未动）；P2-14 egress README 单向性（:134）。

### R4（5 条）

| 项 | R7 状态 | 证据 |
|---|---|---|
| P1-1 M 回归（保存/fail-over 硬依赖重起） | **部分→面板一半已修，Worker 一半复发** | Flask 侧：U 修完（via/toggle 29/29＋MUT-A 25/28）；**Worker 侧：via_sk5 仍撒谎，见 R7-P1-1** |
| P2-1 policy_routing_active 只看规则 | 已修 | `_policy_active` 三条件；探针 A/C 均报 false |
| P2-2 README 清单漏 systemd/ | 已修 | README 含 systemd/（代码未动） |
| P2-3 IPv4 正则接受 999 段 | 已修 | `ipaddress.ip_address()`（代码未动） |
| P2-4 两门禁零覆盖保存→重起耦合 | 已修 | §4d 四格＋MUT-A 25/28 |

### R5（3 条新发现）——全部已修

P2-1 409/404（Flask 46/46）；P2-2 init_pki force 死路（core 21/21 force 真重建；面板入口缺失另见 R7-P2-9）；P2-3 core `_exists`（core C19 nobody 下不抛）。

### R6（8 条）

| 项 | R7 状态 | 证据 |
|---|---|---|
| P1-1 via_sk5 策略缺失仍报 true | **部分：Flask 已修，Worker 复发** | Flask：via/toggle 探针 29/29（A/B/C/D 全诚实）；Worker：探针实测 `via_sk5:true`＋`policy_routing_active:false`，见 **R7-P1-1** |
| P2-1 check_health 假 fail-over 记录 | 已修 | H3/H4 六格（failover_failed vs failed_over_to_direct 区分） |
| P2-2 三路冗余重起 | 已修 | T1–T7（值未变 ＋0，真实翻转 ＋1） |
| P2-3 verify-integration.sh P2-8 复发 | 已修 | W（§1c /proc 实测密码零命中） |
| P2-4 README 三处过期 | **部分** | ① 门禁数：V 修 20→27 后主控改格 B 又＋1，README 仍写 27，见 **R7-P2-6**；② 路由源：根 README 已修，egress/README 两处漏网，见 **R7-P2-7**；③ starter 行号已修 |
| P2-5 安全节三假宣称 | 已修 | V（§1b 全树零命中） |
| P2-6 set_sk5 全量覆盖假宣称 | 已修 | V（§1b） |
| P2-7 handleCreateCmd 缺 queued:true | 已修 | W（Worker W11：202＋`queued===true`） |

### live 轮次（27 条）

- **R1 9 条（BUG-1～9）全部已修**：live-R2/R3/R4/R5 复跑＋本轮套件均证；BUG-9 第五轮复验通过（core C18）。
- **R2 7 条全部已修**：BUG-10（装树 agent/＋门禁双机制，MUT-B1/B2′ 本轮重跑双红）、BUG-11（TOFU 锚在取包前）、BUG-12（--node-name，W07）、BUG-13（comma-v2 解析）、BUG-14（allow_port_change）、BUG-15（健康门模式感知）、BUG-16（重跑继承 proto/port）。
- **R3 6 条全部已修**：R3-BUG-6（log 定义前移）、R3-BUG-1（disable 重起 sing-box）、R3-BUG-3（复制清单含 systemd/）、R3-BUG-5（IPv4 探测＋形状校验）、R3-BUG-2（pipefail SIGPIPE）、R3-BUG-4（route-get 源 10.8.0.1）。R3-OBS-1（瞬态 401）live-R4/R5 未复现，判关闭。
- **R4 4 条**：R4-BUG-1 **部分**（Flask daemon＋上报已修，Worker 上报复发＝R7-P1-1）；R4-BUG-2/3/4 **已修**。
- **R5 1 条（R5-BUG-1）已修**：X 矩阵四格亲自重跑（§1d）＋verify.sh 限定跑 egress-crosscheck PASS；关态全绿仍待 live-6 真机终验（§8 U-12）。

复扫合计（按行）：已修 96 条，部分 8 行，未验 1 条（P0-1 部署态；P0-3 的部署态一半未验，计在其“部分”行内）。105＝96＋8＋1。部分 8 行中 4 行是同一 via_sk5 缺陷的跨轮记账（R1-P1-5、R4-P1-1、R6-P1-1、live R4-BUG-1），其实质是同一事在 Flask 侧修完、在 Worker 侧复发，本轮新立案为 **R7-P1-1**（见 §8）；其余 4 行：P0-3、P1-7、R1-P2-13、R6-P2-4。未修 0 条（R6 的 1 条未修 P1-15 已由 V 修完）。


### §4a verify-integration.sh——28/28（/tmp 副本，2026-11-12 09:06 UTC）

副本 `/tmp/r7-verify`（`cp -r /tmp/r7`），面板以 nobody 身份跑、`OVPN_SK5_CONFIG_DIR` 钉副本、`panel/data` 已清。逐格全绿，含 §4c 格 B 真翻转 B1/B2、§4d 四格、R4-BUG-1 风暴格（7 次切换、7 restart＋7 reset-failed、0 限流失败）。汇总 `PASS=28 FAIL=0 SKIP=0`。

### §4b §4c 格 B 双变异——各自独立红证

| 变异 | 改法 | 结果 | 结论 |
|---|---|---|---|
| a′：disable 吞掉重起失败 | `egress/sk5_manager.py` 的 `disable()` 里删掉 `singbox_restart_error` 字段赋值（重起失败只留 `singbox_restarted=false`，不诚实上报） | **27/1，仅 B2 红**（“disable 返回 200，桩 run 2 次（期望 200、回执含 singbox_restart_error…）”） | 格 B2 对“重起失败不诚实上报”敏感，活的 |
| b：删 alive-once 支持 | `verify-integration.sh` 桩 sing-box 的 `run` 不再消费 alive-once、不再睡 10 秒（立即退出） | **26/2，B1＋B2 双红**（B1 enable 返回 500；B2 disable 返回 200 但缺字段、run 仅 1 次） | 格 B1/B2 对“桩 run 活不过存活检查”敏感，活的 |

附带：一次更粗的变异（a：`disable()` 入口直接抛错）跑出 25/3——B2 红之外，R4-BUG-1 风暴格与收尾 disable 也红；这是变异口径过大（disable 全断）的连锁，不是门禁误报。精确变异 a′ 已证明 B2 的针对性。

### §4c verify.sh 限定跑——20/23（两轮；沙箱限定，逐格分类）

T harness（`/tmp/fixt`）已被清，本轮未重建整套。限定跑做法：`/tmp/r7-vroot` 作 staged 安装树（install.sh 的 `chmod 755 test-egress.sh` 在 staged 树上补做——真实安装时 install.sh:396 本来就会做），真实 Flask 面板以 TLS 跑在 https://127.0.0.1:8443（数据/CA/SK5 目录全钉 /tmp；`/etc/openvpn-sk5-panel` 与 `/etc/sysctl.d` 在面板与 verify 各自的 `unshare -m` 命名空间内 bind 到 /tmp，宿主 /etc 事后已核干净、无残留），`PATH` 前置不含 curl 的 vbin（fake ip/iptables/systemctl/sing-box/sysctl/easyrsa/openvpn；curl 必须用真的，否则 verify.sh 与面板的 HTTP 全被 fake curl 吞掉）。第一轮 18/2/3，第二轮 20/1/2（第二轮补了 `test-egress.sh` 可执行位＋`sing-box.json` 已由第一轮 enable 渲染出来）。

第二轮逐格（PASS=20 FAIL=1 SKIP=2，rc=1）：

| 格 | 结果 | 定性 |
|---|---|---|
| syntax / files / install-copies-agent / installed-agent-tree / starter-template-consistency | PASS | 真实通过 |
| sing-box-version（1.11.15） | PASS | fake sing-box 报的版本；二进制本身在沙箱不存在，版本钉子靠 live-6 真机 |
| sing-box-config（`sing-box check` 过） | PASS（第二轮） | fake sing-box 只校验 JSON 合法；真二进制校验靠 live-6 |
| openvpn（systemctl is-active） | PASS | **假态通过**：fake systemctl 的 `ovpn_active=1` 状态文件是我置的模拟值，不是真实 openvpn 进程；真机格靠 live-6 |
| panel-reachable / panel-login / panel-status / agent-bundle / install-agent-script / user-ovpn（.ovpn 含三 PEM 段）/ stub-socks5 / sk5-toggle-on（rule=1 table100=1，vpn 走 tun1、host 走 main）/ egress-crosscheck（test-egress.sh exit 0）/ sk5-egress-ip / sk5-disable（rule=0 table100=0）/ sk5-enable-endpoint | PASS | 真实通过（真实面板＋fake 系统面） |
| sing-box-running | **FAIL** | **环境**：沙箱无真实 sing-box 进程；fake `run` 只睡 10 秒（alive-once）即死，`pgrep -x sing-box` 找不到。不是产品失败；真机格靠 live-6 |
| sing-box-steady | SKIP | 依赖上一格 |
| direct-forwarding | SKIP | fake `ip` 无 default 路由，环境 |

第一轮另有两处已在第二轮消除的限定：sing-box-config FAIL（当时 `sing-box.json` 尚未渲染——staged 树没跑过 install.sh 的 starter 渲染；真实安装时 install.sh 会渲染）、egress-crosscheck SKIP（staged 树的 `test-egress.sh` 是 660 不可执行，`[ -x ]` 失败；真实安装时 install.sh:396 会 chmod 755）。两处均为 staged 树与真实安装树的差异，不是产品缺陷。

附带事故：第一轮启动面板时 `_ensure_admin_password()` 把 `admin.pass` 写进了宿主 `/etc/openvpn-sk5-panel/`（root 身份写 /etc 成功，不走 fallback）；发现后已删文件与目录，并改用 bind 挂载隔离重启面板。事后核查：`/etc/openvpn-sk5-panel` 已不存在，`/etc/sysctl.d/` 无 `99-openvpn-sk5.conf`，面板进程已停。教训记入 §8：沙箱内以 root 跑面板必须先 bind 隔离 `/etc/openvpn-sk5-panel`，否则默认路径会写穿。

### §4d R6 门禁变异重跑（MUT-A/B/C/D，本轮独立重跑）

基线：verify-integration 28/28（§4a）；verify.sh 限定跑 20/1/2（§4c 第二轮，唯一 FAIL 为环境性的 sing-box-running）。

| 变异 | 门禁 | 结果 | 结论 |
|---|---|---|---|
| MUT-A：删 `_start_singbox` 的 reset-failed 调用 | verify-integration | **25/28**，恰红三格 §4d：风暴格 A（STORM_OK=0、restart=5、reset-failed=0、限流失败=2）、B（重开补策略 HTTP 500）、B2（健康重开 HTTP 500） | 红证成立，与 R6 的 24/27 同形（格数 27→28） |
| MUT-B1：install.sh loop 表去掉 agent | verify.sh | **18/2/3**，install-copies-agent 红（＋常驻环境 FAIL sing-box-running） | 双机制检查的 loop 分支有效 |
| MUT-B2′：cp 改抄固定 `core`（不用 `$_item`，也不满足字面 agent 分支） | verify.sh | **18/2/3**，install-copies-agent 红 | 双机制检查的 cp 分支有效。附带纠正：首版 B2 把 cp 改成字面 `"$SCRIPT_DIR/agent"`，结果 19/1/3 未红——该写法正是双机制检查的另一条合法分支（字面形），不是变异失效，是我的变异口径错了；改抄 `core` 后红证成立 |
| MUT-C：面板 `status()` 恒 500 | verify.sh | **17/3/3**，panel-status（HTTP 500）＋sk5-egress-ip（下游）双红 | R2-P1-4 的门禁盲区仍堵着 |
| MUT-D：删 `systemd/openvpn-sk5-healthcheck.timer` | verify.sh | **18/2/3**，files 格红（missing: …/healthcheck.timer） | R2-P1-5 的门禁盲区仍堵着 |

## §5 五套件重跑（全部自建；先前 /tmp 资产已被清）

R6 的 `/tmp/audit6-tests`、S 的 `/tmp/s-tests`、`/tmp/s-venv`、Q 的 `/tmp/fixq-test`、T 的 `/tmp/fixt` 本轮开工时均已被清（仅 `/tmp/fixx` 幸存）。以下五套件全部按同口径重建，注在 §0；探针与套件见 `/tmp/r7-tests/`（fakebin、`run_unshare.sh`、`run_suite.sh`）、`/tmp/r7-venv/`（flask 3.1.3＋bcrypt）。沙箱限定统一说明：UDP 数据面在沙箱恒 EPERM（见 §0），UDP 探针格只验解析/状态机，不验真实 UDP 收发；TUN 创建亦 EPERM，`run` 只验控制面。

| 套件 | 规模 | 结果 | 说明 |
|---|---|---|---|
| Flask（`/tmp/r7-tests/flask_suite.py`） | 46 格 | **46/46** | 真实 test_client＋真实 core/egress＋fake easyrsa/openvpn。登录/改密/用户（409/404/403）/服务（tcp/443 allow）/SK5/节点（注册/轮换/吊销）/bundle sha256/限流 429＋Retry-After 900 全过。F23 在 `unshare -rm` 下曾 500（低端口 EACCES 被 `_port_occupant` 误报“占用”），`unshare -m` 后通过；live-R5 §10 已在真机证 tcp/443 allow→200 |
| agent（`/tmp/r7-tests/agent_suite.py`） | 25 格 | **25/25** | 白名单（未知 action／夹带 shell 键／非 dict params 均拒）、set_sk5 部分合并（单字段 keep、空密码 keep、非法 host 拒）、get_status 五键、create_server 幂等、create_user/revoke、panel_url 校验（http 非 loopback 拒）、四枚 pinned sha256 与 install.sh 逐字一致、stub HTTP 面板（127.0.0.1:18098）poll→执行→report 全链、main `--once` 不可达→1／可达→0 |
| core（`/tmp/r7-tests/core_suite.py`） | 21 格 | **21/21** | 含 C18 状态日志回归（真实捕获行直接跑 `core/tests/test_status_log.py`）、C19/C21 两处初跑 FAIL 均为套件 bug（见下） |
| egress（`/tmp/r7-tests/egress_suite.py`） | 20 格 | **20/20** | E04 初跑 FAIL 为套件 bug（见下）。含 policy 旗标（rule 删／table 空→false）、failover_failed／failed_over_to_direct、kill-switch、部分合并、密码 keep/clear |
| Worker（`/tmp/r7-tests/worker_suite.mjs`，Node 24） | 28 格 | **28/28** | Mock KV＋mock origin fetch。登录限流、注册/轮换/吊销、install 命令（-k＋sha256sum -c＋--node-name）、poll 认名、202 语义、**W11：POST /api/cmd→202＋`queued:true`**（R6-P2-7 断言格）、bundle 代理＋篡改 502＋无 origin 503、**W28：sent 重投 3 次上限→failed**（驱动须同时伪造 `sent:<node>` 列表条目的 sent_at——重投判据读的是列表条目，不是 cmd 记录本身；初版只改 cmd.sent_at 时 retries 恒 0，属套件驱动问题） |

套件 bug（全是我方探针/假桩的问题，非产品；修后重跑全绿，过程留证）：

- E04：fake systemctl 用 `echo` 写 restarts 文件带换行，套件拿 `"1"` 硬比 `"1\n"`——改 `.strip()`。
- C19：core 套件没复位 fake `ovpn_active`（前序格留 1），`server_status` 报 running=true——C19 前置 `ovpn_active=0`。
- C21：同 proto/port 重渲染按设计跳过占用检查——须先删 `server.conf` 再绑 1194 渲染才触发拒绝。
- F23／R1-R2：见 §1a（`unshare -rm` 低端口 EACCES；fake iptables `-D` 删末行漏 `mv` 致 `_remove_policy` 30 秒超时）。
- W28 驱动：见上表。
- agent A18/A22：首版 `srv.shutdown()` 后未 `server_close()`，第二台 stub 绑 18098 报 EADDRINUSE——补 `server_close()`。

## §6 P0-1/2/3 真实 wrangler deploy 重验——卡住，未验

- 尝试 1：`wrangler deploy --dry-run`（wrangler 4.160.1，经 npx 现装；正确仓库布局 `/tmp/r7-w2` 下）：**通过**。Assets 解析正常（`panel/templates` 读到 1 个文件，37.61 KiB），绑定列出 `env.PANEL_KV (REPLACE_WITH_KV_NAMESPACE_ID)`＋`env.PANEL_MODE ("cloudflare")`。附带：首次在错误的复制布局（`/tmp/r7-wrangler`，`../panel/templates` 不存在）下跑 dry-run 会报 assets 目录不存在——是我方复制布局问题，不是产品问题；换正确布局即过。
- 尝试 2：`wrangler deploy`：**卡在登录**——非交互环境下 wrangler 要求 `CLOUDFLARE_API_TOKEN` 环境变量；本环境无任何 Cloudflare 凭据，`wrangler whoami` 明确报 “You are not authenticated. Please run `wrangler login`”。
- 第二道卡点（未及验证、但已确认存在）：`cloudflare/wrangler.toml` 的 KV id 仍是占位符（`REPLACE_WITH_KV_NAMESPACE_ID` / `REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`），文件自身注明“填之前 wrangler deploy 会报错”——即便登录通过，部署也会在绑定解析处失败。
- 未尝试 `wrangler deploy --temporary`：临时账号部署的不是用户的 Worker、无 KV、无 secret，验不出 P0-1/2/3，还会留下一个无人认领的临时 Worker，故不做。
- 需要用户做的事（按顺序）：① 在能直连 Cloudflare 的机器上跑 `wrangler kv namespace create PANEL_KV` 与 `--preview` 版，把两个真实 id 填进 `wrangler.toml`；② `wrangler login`（或设 `CLOUDFLARE_API_TOKEN`）；③ `wrangler deploy`；④ 把部署出的 workers.dev 地址交给复跑路，对 P0-1（202 语义）、P0-2（fail-open/UoT 单字段）、P0-3（bundle/install-agent.sh）逐项在真 Worker 上重验；⑤ 部署后换第二出口多点核（POP 慢速传播，见 cloudflare/README 验活注意）。
- 结论：P0-1/2/3 的**部署态一律未验**。本轮 Worker 套件 28/28（mock KV＋mock origin）只证明 Worker 代码逻辑，不冒充部署结论。R6 §6 的 `--temporary` fetch 失败本轮未复现（未尝试该路径）。

## §7 文档宣称全量核对

核对范围：根 README.md、panel/README.md、cloudflare/README.md、cloudflare/server-mode.md、docs/security.md、docs/flmx-reference.md、egress/README.md、core/README.md、agent/README.md（如有）。逐条行为宣称与代码/实测对齐。

### 已核实为真（抽样列举，余见 §2/§3 逐项）

- 根 README 一键安装步骤 1–8、OVPN_SUBNET 口径、重装保留 CA/密码/证书、健康门禁——与 `install.sh` 代码一致。
- 根 README 二进制校验节（pin 哈希、env＞pin＞manifest、fail-closed；starter heredoc `install.sh:531-558` 与模板 tun 段一致）——与代码一致；agent 套件 A17 四哈希逐字一致。
- panel/README API 字段表（登录/改密/用户 CRUD/服务/SK5/test 嵌套 tcp/udp/节点/审计）——与 `app.py` 路由逐项对过，Flask 46/46 侧证；`render_server_conf` 签名、`create_user` 签名与 core 一致。
- security.md 十二行已落地表（默认口令零命中、secret 防发货值、登录限流、会话、改密、命令重投、节点 token、认领守卫、SK5 凭据、agent 通道、白名单、审计日志）——与代码一致；重投上限两端均为 3（Worker W28＋Flask `SENT_MAX_RETRIES=3`）。
- cloudflare/README 部署步骤、验证 curl 序列、接口契约（poll 空 body、report 双 id、13 动作白名单、快照形状）——与 Worker 代码＋套件一致；空 `panel_url` 注册时回落到请求 origin（代码 :466），文档示例可用。
- server-mode.md 对照表大部（https、安装接口仅 Worker 有、轮换/吊销、登录限流、版本传播、KV 明文注记）——与代码一致；set_sk5 行 V 已改部分合并。
- egress/README 链路图、TCP/UDP 对照、故障策略（单向性、60 秒 timer）、校验方法——与代码一致；唯两处 10.8.0.2 见 R7-P2-7。
- core/README 接口表、用户名规则、吊销 CRL 只在启动时读、旧证书三路打通——与代码一致。

### 新立案（文档类）

**R7-P2-8 — 根 README“FLMX 对齐要点”一节多条 FLMX 口径误植（P2）**。与 R6-P2-5 同族（上轮修了安全节三条，本节漏网四条半）：

- (a) “入站安装部署：面板安装脚本同款 6 项菜单（安装/更新/卸载/迁移/域名反代/退出）；版本发现优先级 `VERSION > OVPN_VERSION > PINNED_VERSION > 最新 Release`；防降级三不变量；已有部署默认拒绝重装，须显式 `--force` + 先备份旧 config”——`install.sh` 全文无菜单、无 `select`、无 `--force`、无 VERSION 发现逻辑、无拒绝重装守卫；它就是一台直线式一键安装脚本（幂等重跑）。四项皆无。
- (b) “双哈希下发 + 端口永不换口：`OvpnServer.ConfigHash` vs `AppliedHash`，面板 UI 显示‘已发/待发/下发失败’三态”——全树除 README 与 `docs/flmx-reference.md` 外零命中（`.py`/`.js`/`.sh`/`.html` 均无）；UI 里只有“已下发，等待 agent 执行…”的瞬时提示，没有三态显示。功能本身不存在，文档称其存在。
- (c) “地址归一：Cloudflare 面板一律 `wss://`，服务器面板按实际 `http/https` 补 `ws://`/`wss://`”——全树代码零命中 `wss://`/`ws://`；agent 与面板之间是 HTTPS POST 轮询，没有任何 WebSocket。传输口径纯属误植。
- (d) “SK5 凭据：面板侧只存加密后（或 KV Secret）”——Flask 侧 `sk5.json` 存的是明文密码（本轮探针直接读到 `password == "pw-agent"`）；Worker 侧 `server-mode.md` 自己诚实写着“SK5 密码 / `.ovpn` 私钥明文存 KV”。“只存加密后”是假的。
- (e) “面板 UI：路由 `/` 登录 → `/change-password` → `/dashboard` → `/nodes` → `/servers` → `/sk5` → `/users` → `/profile`”——Flask 只有 `/`（单页）＋`/api/*`；没有 `/dashboard`、`/nodes`、`/servers`、`/sk5`、`/users`、`/profile`、`/change-password` 这些页面路由；单页内只有 `nodes`/`users`/`sk5` 三个 section 卡片，没有 dashboard/servers/profile。修法：按本产品实际改文档，不许反向把未实现的功能补进产品来圆文档（与 R6-P2-5 同款裁定）。

**R7-P2-11 — 文档过期小簇（P2，一并立案）**：

- panel/README.md:55/57 称 `core/openvpn_manager.py` “637 行”、`egress/sk5_manager.py` “670 行”——实测 1230 行与 1088 行。
- 根 README 二进制校验节称哈希钉在 `install.sh:54-57`——实测在 `:63-66`（agent.py:122-132 是对的）。
- core/README.md:4 称面板层为“`web/`”——树里没有 `web/` 目录，面板在 `panel/`；另“吊销：写 CRL……”一段全文重复两次。
- egress/README 文件表称 policy-routing.sh 的 disable“只清 table 100”——脚本自述与代码均为“remove rule + flush table 100”（:133–145），规则也一并删。
- cloudflare/README.md:126 称快照归一化“`via_sk5` 按 `sk5.enabled` 补”——这行字把 R7-P1-1 的 bug 写法当成既定语义写进了文档；修代码时须同改此行。

**R7-P2-12 — verify.sh 的 `sk5-egress-ip` 格可被 10 秒状态缓存虚报通过（P2，门禁弱点）**。该格只断言 `egress.ip` 非空，不校验 `via_sk5`。本轮缓存探针实测：启用链路后删掉策略路由，立即读 `/api/status` 仍返回启用前的快照（`enabled=false`、`ip=198.51.100.9` 直连 IP、`via_sk5=false`）——`_cached_sk5_status` 的 10 秒 TTL 未过期；11 秒后再读才诚实报 `enabled=true`、`policy=false`、`ip=None`＋错误文案。T 变异跑（apply 空操作）中该格正是这样通过的：toggle-on 格已红（“panel said enabled but routing did not switch”），sk5-egress-ip 格却 PASS。修法：该格断言 `via_sk5=true`（或读状态前等缓存过期），toggle-on 已能 catches 路由失败，但本格不应在链路已断时还绿。

## §8 裁决、R6 未验清单认领、未验清单

### 新发现汇总（本轮立案）

| 编号 | 级别 | 内容 | 证据 |
|---|---|---|---|
| R7-P1-1 | **P1** | **Worker 侧 `via_sk5` 在策略路由缺失时仍报 true——R6-P1-1 在 Cloudflare 控制面的复发**。`cloudflare/src/index.js:769`（`cachedStatus`）：`if (egress.ip && snap && snap.sk5) egress.via_sk5 = !!snap.sk5.enabled;`。agent 的 `get_status()` 在 enabled 时恒写 `egress_ip` 探针值（`sk5_manager.py:826`，不看策略），`snapshotFromResult` 原样收入快照，于是策略缺失＋SK5 探针活时 Worker 的 `GET /api/status` 报 `egress:{ip:"203.0.113.7", via_sk5:true}`，而同一快照里的 `sk5.policy_routing_active:false`。U 只修了 Flask 的 `status()`，Worker 的兼容层没动。探针实测（`/tmp/r7-tests/worker_via_probe.mjs`，mock KV＋case A 形快照上报）：`egress: {"ip":"203.0.113.7","via_sk5":true}`，`sk5.policy_routing_active: false`。`cloudflare/README.md:126` 还把该写法当既定语义写着（见 R7-P2-11）。修法：`cachedStatus` 改以 `policy_routing_active` 为判据（与 Flask 同款），策略缺失时不复用探针 IP；或收紧 `get_status()` 的 `egress_ip`（enabled 时也须策略在位才给）。 | Worker 探针实测 |
| R7-P2-6 | P2 | 根 README:224 仍称 verify-integration “PASS=27 FAIL=0 SKIP=0”，现门禁 28 格（§4c 格 B 改写后 27→28） | §1b |
| R7-P2-7 | P2 | `egress/README.md:41` 与 `:171` 仍写 `ip route get ... from 10.8.0.2`（非本机源，内核拒绝；正确源 10.8.0.1） | §1b；`policy-routing.sh:183` 的 `do_status` 同款待定（见下） |
| R7-P2-8 | P2 | 根 README“FLMX 对齐要点”多条误植（6 项菜单/版本发现/防降级/拒绝重装、ConfigHash 三态、wss://、SK5“只存加密后”、UI 路由串） | §7 |
| R7-P2-9 | P2 | 重建 CA 无面板路径（无按钮、无路由、无文档流程；仅 agent 白名单动作＋未文档化的手写 `/api/cmd`） | §2 旅程第 11 步 |
| R7-P2-10 | P2 | 旅程缺口两小项：`git clone <本仓库地址>` 占位符（全树无真实仓库地址）；SK5 端口 1001/9000 未确认，文档只写默认 1001 且未标注待确认 | §2 |
| R7-P2-11 | P2 | 文档过期小簇（panel/README 行数、根 README 哈希行号、core/README `web/`＋重复段、egress/README disable 口径、cloudflare/README via_sk5 写法） | §7 |
| R7-P2-12 | P2 | verify.sh `sk5-egress-ip` 格可被 10 秒状态缓存虚报通过（只断言 ip 非空，不校验 via_sk5） | §7；缓存探针＋T 变异跑实测 |

待定项（不立案，须下一轮裁决）：`egress/policy-routing.sh:183` 的 `do_status` 仍跑 `ip route get 1.1.1.1 from 10.8.0.2`——正是 R3-BUG-4 定性为“内核拒绝的非本机源”的写法。`do_status` 是给操作员看的 headline 状态行，若该行恒报错则状态输出本身不可信。R6-P2-4② 只修了文档，未涉及此处。本轮未在真机上跑 `do_status`，只凭代码面＋R3-BUG-4 定性，不直接立案；下一轮（或 live-6）在真机上跑一次 `./policy-routing.sh status` 再定。

### 裁决：**不能交付**，差集非 ∅

| 级别 | 条数 | 明细 |
|---|---|---|
| P0 | 0 新立（历史 P0-1 部署态未验、P0-3 部署态一半未验，见未验清单） | — |
| P1 | **1** | R7-P1-1（Worker 侧 via_sk5 复发） |
| P2 | **7** | R7-P2-6（README 门禁数）、R7-P2-7（egress/README 10.8.0.2）、R7-P2-8（FLMX 对齐要点误植）、R7-P2-9（重建 CA 无面板路径）、R7-P2-10（旅程缺口两小项）、R7-P2-11（文档过期小簇）、R7-P2-12（sk5-egress-ip 缓存虚报） |

差集：R7 新发现 8 条（1 P1＋7 P2）；历史复扫 105 条：已修 96、部分 8 行、未验 1。**发版硬门未过**：须修完 R7-P1-1 与 7 条 P2、再做一轮全量全局回头看（AUDIT-R8，换推导方法）＋真机复跑（live-6/7），方可交付。

### R6 未验清单 U-1～U-12 逐项认领

| # | 项 | R7 认领 |
|---|---|---|
| U-1 | P0-1/2/3 真实 Worker 部署态 | **仍未验**（§6：登录卡住＋KV 占位）。须用户按 §6 五步部署后复跑路重验 |
| U-2 | R6-P1-1 的真机复现 | **沙箱侧已分流**：Flask 侧 29/29 诚实（§1a）；Worker 侧沙箱已证撒谎（R7-P1-1）。真机复现仍待 live-6 |
| U-3 | UDP 数据面 | **仍未验**。沙箱 UDP sendto 全 EPERM；须 live-6 真机（dante/真实 SK5） |
| U-4 | R 符号链接同目录自拷跳过（行为） | **本轮已验**：`readlink -f` 解引用后相等即跳过复制（`/tmp/r7-sym` 实测：symlink 源＝安装树本身→SKIP-COPY；对照不同目录→COPY-PROCEEDS）。关闭 |
| U-5 | R 逐项失败 die 分支 | **机制已证、整段未验**：循环模拟复现“失败项记入 `_TREE_COPY_FAILED`”；`install.sh:877-878` 在非空时 `die`、拦在完成横幅前（代码在位）。整段 install.sh 跑通须真机 |
| U-6 | T 路两变异逐项重跑 | **其一已验、其一未验**：apply 空操作→sk5-toggle-on 红（18/2/3，文案可区分“panel said enabled but routing did not switch”），T 的红证成立；预热 enable-only 对照（direct-forwarding PASS）在本轮 harness 里无法复现——fake `ip` 无 default 路由，该格恒 SKIP。关闭红证项，对照项留待真机 |
| U-7 | verify-integration 首跑 26/1 瞬时红 | **本轮未复现**：verify-integration 四次运行（28/28、25/3、27/1、25/28）均为确定性结果，无瞬时红。R6 的一次 transient 仍无解释，判观察关闭 |
| U-8 | 真机在位升级路径 | **仍未验**。须 live-6 在 Lightsail 彩排部署上带存量数据跑现行版→候选版 |
| U-9 | Cloudflare KV 竞态与 Workers POP 传播 | **仍未验**。无真实部署；mock-KV 无法复现 |
| U-10 | 前端渲染级核查 | **仍未验**。本轮只验接口与 DOM 存在，未做渲染级对比度/可读性自检；须浏览器渲染路（用户立规：交付前渲染级自检、预览先行） |
| U-11 | easy-rsa 真二进制签发 | **仍未验**。沙箱无 easy-rsa 真二进制，fake 桩只仿文件布局；须 live-6 真机 |
| U-12 | live-R5 本身的结果 | **关闭**。`docs/live-verify-R5.md`（228 行）已落盘：S0–S4 全过，唯一新发现 R5-BUG-1（X 已修，本轮 §1d 复验通过） |

### 未验清单（本轮，逐项：为什么没验、谁能验）

| # | 项 | 为什么没验 | 谁能验 |
|---|---|---|---|
| V-1 | P0-1/2/3 真实 Worker 部署态 | 无 Cloudflare 登录＋KV 占位（§6） | 用户部署后＋复跑路在真 Worker 上重验 |
| V-2 | UDP 数据面（原生 ASSOCIATE、UoT、TCP 443 模式） | 沙箱 UDP sendto 全 EPERM | live-6 真机 |
| V-3 | 真机在位升级路径（带存量数据） | 须 Lightsail 彩排部署 | live-6 |
| V-4 | easy-rsa 真二进制签发 | 沙箱无真二进制 | live-6 |
| V-5 | 前端渲染级核查 | 子代理无 live browser；本轮只验接口与 DOM | 浏览器渲染路或 live-6 |
| V-6 | Cloudflare KV 竞态与 POP 传播 | 无真实部署 | 用户部署后＋复跑路多点核 |
| V-7 | `policy-routing.sh:183` do_status 的 10.8.0.2 行 | 未在真机跑过 `do_status`，只凭代码面＋R3-BUG-4 定性 | live-6 真机跑一次 `./policy-routing.sh status` |
| V-8 | SK5 端口 1001 还是 9000 | 用户至今未确认哪个是 SOCKS5 口 | 用户回报 |
| V-9 | live-6 本身的结果 | 与本轮并行在跑，报告落盘时未见其结论 | 主控核验两路后定夺 |
| V-10 | verify.sh 全量（T harness 原样） | `/tmp/fixt` 已被清；本轮为限定跑（20/1/2，逐格分类，见 §4c） | 复跑路重建 harness 或 live-6 真机跑 `bash verify.sh` |

### 本轮取证失误与纪律自记（不立案）

1. **`/etc` 写入（本轮违规，已清除）**：verify.sh 限定跑第一轮启动面板时，`_ensure_admin_password()` 以 root 身份把 `admin.pass` 写进了宿主 `/etc/openvpn-sk5-panel/`（目录与文件均为本次运行新建，mtime 09:08 UTC）。发现后已删文件与目录，改用 `unshare -m` 内 bind 挂载隔离重启；事后核查 `/etc/openvpn-sk5-panel` 已不存在、`/etc/sysctl.d/` 无 `99-openvpn-sk5.conf`、面板进程已停。教训：沙箱内以 root 跑面板必须先 bind 隔离 `/etc/openvpn-sk5-panel`（与 `/etc/sysctl.d` 同款做法），否则默认路径会写穿——与 R6 自记的同款违规同族。
2. **B2 变异口径错（已纠正）**：首版 MUT-B2 把 cp 改成字面 `"$SCRIPT_DIR/agent"`，结果未红——该写法正是双机制检查的另一条合法分支，不是门禁失效；改抄 `core` 后红证成立（B2′ 18/2/3）。
3. **探针先查探针、再判产品（本轮两次）**：via 探针初版 24/29（fake iptables `-D` bug＋断言层级错）、Worker W28 初版（驱动只改 `cmd.sent_at`、漏 `sent:<node>` 列表条目）、agent 套件 EADDRINUSE（未 `server_close()`）——均先证为探针/假桩问题，修后重跑全绿，未误判产品。

### 审计方法说明

- 推导方法：从零用户旅程推导（与 R1 文件逐项、R2 旅程、R3 宣称驱动、R4 不变量驱动、R5 故障注入、R6 状态转移均不同）。先假装只看文档的新运维从裸机走到可用链路（§2），再叠加历史 105 条全量复扫（§3）。
- 每条新立案均带可复现探针与实测输出（§1 探针、§4 门禁变异、§5 套件、§7 缓存探针、worker_via_probe），不凭代码阅读立案；R7-P1-1 走真实 `GET /api/status` 路径，未用 monkeypatch。
- 单审计员，无子代理分派；报告按节增量落盘；测试一律 /tmp 副本，未动项目原文件与任何真机；`/etc` 只在 `unshare -m` 命名空间内 bind（除 §8 自记的一次写穿，已清除）。

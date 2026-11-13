# AUDIT-R32 — 时间与顺序边界审计（2026-11-13）

> 方法：time-and-order boundaries（与 R31 的 input-shape、R30 的 state-transition、R29 的 cross-face consistency、R28 的 zero-user journey、R27 的 adversarial operator、R26 的 repo-consumer journey、R25 的 repair-path convergence 均不同）。机械枚举全部超时／间隔／TTL／重试次数／排序规则，逐项核验精确值、边界瞬时行为、off-by-one、双定时事件交错；边界差一、瞬时无守卫、交错下静默错误即立案。
> 审计树：`~/workspace/openvpn-sk5-panel/`，git main @ b395ef3（1.0 发布提交，与公开仓库一致）＋未提交工作区改动（R26 文档修复；R27 修复：verify.sh cleanup API 恢复、egress/sk5_manager.py UDP 判据、cloudflare/src/index.js 队列 TTL；R28 文档修复；R29 修复：index.js coerceToggleBool；R30 修复：index.js 原始文本层整数 token 校验；R31 修复：index.js 信封守卫 isJsonContentType＋readJson/readJsonRaw null 体拒绝、panel/app.py bcrypt 72 字节上限＋ValueError 兜底）。
> 历史台账：R31 终点 173 条（已修 160、部分 2（按设计）、未验 1（P0-1 Cloudflare 真实部署）、新 2（R31-P2-1、R31-P2-2，本轮已验关闭）。本轮新增见 §8。
> 夹具：/tmp/r32/ptree（本轮新建的工作树副本）；fixture 复用 /tmp/r27（fixture-ca 含 ta.key、fixture-server server.conf port 1194 proto udp，属 nobody 所有）；venv /tmp/r27/venv（Flask 3.1.3＋bcrypt）；系统 python3 无 flask（预期）。

## verdict：不能交付

差集 1 条（P2）：R32-P2-1（enable LIVE-tun1 等待窗口名义 5 秒、实际只查到约 4.5 秒）。门禁 29/29，§7 变异 11/11 恰红 28/1；探针套件重跑见 §6。历史台账 173→174，0 复发。Cloudflare Worker 真实部署仍 P0-1 未验。

## §0 审计基线与树状态

- 本地树：main @ b395ef3，`git status`：7 文件已修改未提交（README.md、cloudflare/README.md、cloudflare/src/index.js、docs/DELIVERY.md、egress/sk5_manager.py、panel/app.py、verify.sh）；未跟踪：docs/audit/AUDIT-R26.md～R31.md、docs/live-verify-R18.md、docs/live-verify-R18-supplement.md、tests/r27_*.py/mjs、tests/r29_flask_toggle_bool.py、tests/r29_worker_toggle_bool.mjs、tests/r31_bcrypt72.py、tests/r31_ctype.mjs/py、tests/r31_edge.mjs/py。
- 公开仓库：https://github.com/iiiiiiiii7125-art/openvpn-sk5-panel（public）。本轮审计的是本地工作树（含未提交修复），不是仓库 HEAD——仓库 HEAD 仍为 b395ef3，未含 R26～R31 修复；发新版前须提交并推送（见 §9 收尾）。
- 探针树：/tmp/r32/ptree（本轮新建的工作树副本）；fixture／venv 复用 /tmp/r27（起跑前复核）。
- /etc/openvpn-sk5-panel/：本轮跑前复核为空（0 泄漏起点）。

## §1 R31 修复闭合核验（行为实证，不认代码在场）

本轮在 /tmp/r32/ptree（新鲜工作树副本）上重跑，日志 /tmp/r32/p-r31-*.log：

- `tests/r31_edge.mjs`（Worker）**22/22**（exit 0，FAIL 0）；`tests/r31_edge.py`（Flask，nobody＋全新 data 目录）**21/21**。畸形／标量／null／数组／空体在 toggle 与 save 路由双面 400；E19/E20 裸动作路由双面 202（体被忽略，一致）。
- `tests/r31_ctype.mjs`（Worker）**7/7**；`tests/r31_ctype.py`（Flask）**6/6**。text/plain 与缺 Content-Type 的合法 JSON 体双面 400；`application/json; charset=utf-8` 双面 202。
- `tests/r31_bcrypt72.py`（Flask）**6/6**：72 字节 200 且可登录；73 字节与 74 字节多字节 400 并点名 72 字节上限，旧密码事后仍可登录；72 字节多字节 200。
- **结论：R31-P2-1 与 R31-P2-2 均已关闭**（行为＋源码双证；源码核对见 §2 边界表相关行）。

## §2 时间与顺序边界全集（本轮推导法核心）

机械枚举：全部超时／间隔／TTL／重试／排序规则（双面＋agent＋安装脚本＋systemd）。每项：精确值、边界瞬时行为、off-by-one、交错。已裁定项（R5／O-R27-2／R22 观察）注明，不重立。

| # | 边界 | 精确值 | 边界瞬时行为 | 结论 |
|---|---|---|---|---|
| B1 | agent poll 间隔／请求超时 | POLL_INTERVAL=5s（agent.py:70），POLL_TIMEOUT=10s（:71） | 串行循环，无重叠；慢面板（10s 超时）只拉长周期 | ✓ |
| B2 | 健康检查定时器 | OnBootSec=1min，OnUnitActiveSec=60s（healthcheck.timer） | 首 tick 在 boot 后 60s 内；boot 期由 do_restore（REPAIR_MODE）兜底 | ✓ |
| B3 | enable 等 LIVE tun1 窗口 | 10×0.5s（sk5_manager.py:1226-1235），文案称 5s | **见 §8 R32-P2-1**：检查时刻为 0.0～4.5s，5.0s 时 raise；4.6～5.0s 间变活的 tun1 被漏判 | **立案 P2** |
| B4 | sent 超时重投 | 120s，两面严格 `>`（Flask `<=120 continue`，Worker `<=120000 return null`）；retries+1，`>3` 即 failed（共重投 3 次） | 恰 120.0s 时不重投、不提示；120.001s 即重投；cmd_get 的 timeout_hint 同款 `>120` | ✓ 数值一致；集合分歧（Flask 全动作／Worker 仅 SAFE 7 动作）为 R5 已裁定，security.md:12 |
| B5 | 命令 TTL | CMD_TTL_S=7×24×3600（index.js:81）；cmd:/queue:/sent: 全部 15 处 kvPutJson 均带 TTL | queue:/sent: 写点 7 处（:448 enqueue、:665 吊销清零、:907／:919 poll 合并写、:1010-1014 poll 条件清零、:1023 sent 去重、:1085 report 保留）逐个核对均带 `expirationTtl: CMD_TTL_S`；R27-P2-2 修复在位 | ✓ |
| B6 | 登录限流 | 5 次／300s 窗口／锁 900s，两面同值 | 窗口过滤严格（Flask `now-t<300`，Worker `t>now-300000`）；恰 300s 的旧失败被丢弃，两面一致；锁检查严格 `<`，恰到期即解锁；Retry-After：Flask `int(diff)+1` vs Worker `Math.ceil(diff/1000)`，差 1 秒——R22 已观察，不立案 | ✓（观察沿用） |
| B7 | 会话有效期 | Flask 12h（PERMANENT_SESSION_LIFETIME，app.py:191；login 处 session.permanent=True :1342），Worker 24h（SESSION_TTL_S=86400，index.js:80） | 两面各自强制（Flask cookie max_age；Worker expires_at `<=now` 即过期＋KV TTL 86400＋cookie Max-Age 86400 三重一致）；差值在 security.md:10 与 cloudflare/README.md:165 各自明文记载 | ✓ 已文档化，不立案 |
| B8 | 证书过期判定 | `_index_expiry_is_past`：`when <= now`（core:371） | 恰 notAfter 瞬间判 expired；R22 已作 1 秒算子注，不立案 | ✓（观察沿用） |
| B9 | 状态缓存 | 10s（_SK5_STATUS_CACHE_TTL／_EGRESS_CACHE_TTL，app.py:1416/1437）；时间戳取探针完成时 | 恰 10.0s 即刷新；enable 后 10s 内读到旧快照为 R7-P2-12 已文档化行为，verify.sh 轮询 15s 兜底（:779-790） | ✓ |
| B10 | sing-box 启动限制 | StartLimitBurst=5／120s，RestartSec=3s（singbox.service） | enable 前 `_start_singbox` 先 reset-failed（:378），防 R4-BUG-1 楔死；systemd 自身重起仍受 5 次／120s 约束 | ✓ |
| B11 | policy-routing flock | flock -w 20s（policy-routing.sh:150）＜ sk5_manager._run 超时 30s | 锁争用 20s 即大声 die，不静默挂死、不被 30s 超时截断 | ✓ |
| B12 | 直接进程停表 | SIGTERM 后 20×0.25s＝5s，超时 SIGKILL（sk5_manager.py:410-420） | 4.75～5.0s 间自然死的进程仍收 SIGKILL——已死／将死，无害 | ✓ |
| B13 | 临时 sing-box 监听等待 | 20×0.25s 先睡后查（:713-722），末查在 5.0s；proc.wait(timeout=5)→kill | 与 B3 同文件的正确形状（sleep-then-check），作 B3 对照 | ✓ |
| B14 | 安装器下载／稳态 | curl --retry 3 --connect-timeout 20 --max-time 300（install.sh:349）；首包 max-time 60（:327）；wait_steady 20 轮×5s settle；panel /api/me 60s 内；admin.pass 30×1s | 重试 3＝最多 4 次尝试；稳态须两次探针＋零重起 | ✓ |
| B15 | verify.sh 稳态／出口轮询 | sing-box steady 3s settle（:391-403）；sk5 egress 轮询 15 次≈15s（:779-790） | 15s＝10s 缓存 TTL＋余量；先判 sk5.enabled=true 再断言 via_sk5 | ✓ |
| B16 | agent 退避 | 失败后 backoff×2，上限 60s，下限 5s；成功即复位 5s（agent.py:878） | 失败序列 10／20／40／60／60…；空闲节点恒 5s | ✓ |
| B17 | 长执行 vs 120s 重投 | agent _run 600s、easyrsa 600s、apt 900s（agent.py:404/604，core:133） | 执行中 agent 不 poll；120s 到即重投，下次 poll 重执行——O-R27-2 已裁定（security.md:12，有界：create_user 二次报已存在，init_pki 二次为同一已授权重建） | ✓ 已裁定，不重立 |
| B18 | Worker loginfail 记录 TTL | 1200s＝900＋300（index.js:543） | 锁 900s 恒在记录 TTL 内；每次失败写回刷新 TTL | ✓ |
| B19 | Worker 会话三重一致 | expires_at＋KV TTL 86400＋cookie Max-Age 86400 | 过期会话在 requireAdmin 内删除（:369-372） | ✓ |
| B20 | 改密会话失效 | change_password 后 session_version+1（R17 Flask 绿格） | 旧会话立即失效，无宽限窗口 | ✓ |
| B21 | boot 恢复 | do_restore 走 REPAIR_MODE，不等 tun1（policy-routing.sh:479-548）；60s 健康检查补全 | sing-box 未起时表 100 诚实黑洞-only；无占位符竞态（BP／R24-P2-1） | ✓ |
| B22 | 队列 sweep 为 poll 驱动（惰性） | Flask _requeue_stale_sent 仅 poll（:2506）与 report（:2627）调用；Worker sweep 在 poll／report／revoke／cmd_get 读路径 | agent 死→无 poll→sent 态滞留至 agent 归来；属设计（无独立定时 sweep），两面一致 | ✓ |
| B23 | CRL 与过期 | server.conf.template:17 `crl-verify`；revoke 时 gen-crl＋同步到 server dir（core:908-921） | 过期由 OpenVPN 拒（与 CRL 无关）；吊销由 CRL 拒；两路径独立 | ✓ |
| B24 | SK5 探针超时 | TIMEOUT=10s／_run 15s；UDP 两次尝试（sk5_manager:463-473，:623） | 单次 test 最坏约 20s＋；TCP 腿只读 tcp_ok（R27 已裁定 healthy 语义） | ✓ |
| B25 | detect_public_ip | 超时 5s（core:504-515） | 失败即 None，不阻塞 | ✓ |

（B3 的实证与修法见 §8。）

## §3 功能链全量对账（README / DELIVERY.md / security.md 逐项对行为）

### §3.1 机械计数复核（本轮独立重算）

- **13 动作白名单三面逐字一致**：Flask `AGENT_ACTIONS`（app.py:199-204）、agent `ACTIONS`（agent.py:754-768）、Worker `ACTIONS`（index.js:64-78）——本轮逐项目视比对三面各 13 项排序后逐字相同 ✓（R31 的 python 机械比对结论沿用；本轮 regex 抽取一度只取到 9 项，系抽取表达式截断，已改读码逐项核对）。
- **verify.sh 24 项检查**：本轮独立重算 24 distinct 检查名（ok／bad／skip 调用点去重，59 处调用点）✓。
- **R28 修复闭合**：README Cloudflare 节——未验横幅在位（:89）、填 id 步在位（:98）、“推荐”全 README 0 处；cloudflare/README.md 未验行（:3）✓。
- **发布包快照（DELIVERY §9 仍为 1.0 包的真实快照）**：`tar tzf` 92 条目 ✓；包内 audit 25 份、live 17 份 ✓；抽查 4 个关键文件 sha256（verify.sh `7867f557c6bb…`、app.py `40868bbfd8b9…`、index.js `f43180976393…`、install.sh `3f050f037e7a…`）与 §9 所记逐项一致 ✓；tarball sha256 与 sidecar 一致（`540fc8fc…`）✓——刷新属发版步骤（§9 清单），不当轮立案。

### §3.2 功能矩阵（功能 → 行为证据；探针编号见 §6）

| 功能（README／DELIVERY 宣称） | 行为证据 | 结论 |
|---|---|---|
| OpenVPN UDP 1194 主／TCP 443 备 | Core 46/46（§6 重跑）；install.sh 环境变量＋存量继承＋非法值早死 | ✓ 沙箱级；数据面属 live 轮 |
| 建用户／吊销／下载 .ovpn | Core 46/46；Flask 86/89（绿格内）；CRL：template:17 `crl-verify`，revoke 时 gen-crl＋同步（core:908-921） | ✓ |
| SK5 启用／停用 | BM 22/22、BO 18/18、BS 9/9、BT 23/23、R24 25/25、R25 37/37（§6 重跑） | ✓（enable 5s 窗口差半秒见 §8 R32-P2-1） |
| 断网保护 fail-closed | BM K1–K5（真实 netns＋真实 ip） | ✓ |
| 健康检查 60 秒＋自愈 | 定时器 OnBootSec=1min／OnUnitActiveSec=60s；BM H1–H10；BS 9/9 | ✓ |
| 命令队列＋agent 5 秒 poll | POLL_INTERVAL=5（agent.py:70）；R17 四套件；R21 6/6；BQ 6/6；sweep 惰性（仅 poll／report 驱动，B22） | ✓ |
| Flask＋Worker 双面 | R17 四套件；BR 11/11；R27 Worker 5/5；R29 toggle 15/15＋13/13；R31 信封守卫 22/22＋21/21 | △ 除 §8 R32-P2-1 外一致 |
| 登录限流 | Flask／Worker 双面格；BR 11/11；429＋Retry-After（B6） | ✓ |
| 密码处理 | bcrypt＋透明迁移；改密 72 字节格 6/6（§1）；Worker 改密 501；默认口令 grep 零命中（§4） | ✓ |
| 重建 CA（force+confirm） | Flask F-cells；R17-P1-1 守卫 | ✓ |
| /api/sk5/test UDP 腿 | 判据 round-trip 证明（R27 已修，探针 6/6） | ✓ |
| verify.sh 强制路径 | API 先行恢复运行链（R27 已修，探针 8/8；cleanup 代码 §2 B-verify 复核） | ✓ |
| 安装顺序 | apt→sing-box→staging 复制（panel/data/ 排除，install.sh:483-505）→PKI→单元→启动→稳态门禁 | ✓ |

## §4 安全清单对账（docs/security.md 逐项抽查）

- **默认口令字面量零命中**：`grep -rnw "admin123\|changeme\|123456\|password123" panel/ agent/ cloudflare/src/ core/ egress/` 零命中 ✓。
- **限流 XFF 守卫**：仅 `OVPN_TRUSTED_PROXY=1` 时才信任 X-Forwarded-For（app.py:182-183，ProxyFix），默认不信任 ✓。
- **会话**：Cookie HttpOnly（:184）＋SameSite=Lax（:185）＋Secure 条件（:189）、Flask 12 小时（:191，login 处 permanent=True :1342）、Worker 24 小时（B7）；改密后 session_version+1 全旧会话失效——R17 Flask 绿格内（§6 重跑）。
- **SK5 凭据**：只存 sk5.json（0600），get_status 只回 has_password、日志脱敏——R17 Flask 绿格内。
- **命令重投非幂等风险**：security.md:12 已诚实记录（O-R27-2 沿用，不立案）；重投集分歧 R5 已裁定（B4）。
- **agent 通道**：panel_url 须 HTTPS（仅 127.0.0.1／localhost／[::1] 例外）、禁 https→http 降级重定向——R17 Agent 33/33（§6 重跑）。
- **结论：security.md 抽查项与行为一致，无新缺口。**

## §5 门禁（verify-integration.sh，串行）

- **干净树**：`/tmp/r32/gate.log`，`PASS=29 FAIL=0 SKIP=0`，exit 0（本轮亲手跑于 /tmp/r32/ptree；门禁脚本用固定 `/tmp/ovpn-int-test`＋端口 8443，全程串行，无并发）。
- **§7 变异树 11/11 恰红 28/1**：`tests/build-mutants.py` 建 11 棵变异树（/tmp/r32/mutants-build.log），逐棵串行跑门禁（/tmp/r32/gate-m-*.log）：m-char、m-const-sb、m-dict-extra、m-dict-missing、m-dict-sb、m-dict-ts、m-dict-x-a、m-dict-x-amd、m-dict-x-arm、m-dict-x-b、m-install-sb——每棵均为 `PASS=28 FAIL=1 SKIP=0`，且唯一红格逐棵核对均为 §7 钉死格（“钉死哈希不一致：install.sh 与 agent/agent.py 的 sha256 逐键不等”）。门禁 §7 的两层（常量逐键＋字典绑定）均有效。
- **中途事故（已处置，非产品问题）**：首轮 11 棵变异门禁全 SKIP（`建 venv 失败`）——/tmp tmpfs 512M 已满 100%（历轮残留 /tmp/r28～r31 等约 400M）；已删 stale 轮次目录（保留 /tmp/r27 夹具／venv 与 /tmp/r32），释放至 394M 空闲后逐棵重跑。`scripts/check-doc-consistency.sh` 在本树不存在——本轮未跑、未声称跑过；真实门禁即 verify-integration.sh。

## §6 探针套件重跑

Flask 探针均以 nobody 身份、每轮全新 data 目录、从 ptree 内运行；r20 以 root 运行（unshare 格）；Worker 探针直接 node 运行；日志 /tmp/r32/p-*.log。

| 套件 | 本轮结果 | 说明 |
|---|---|---|
| R17 Flask | **86/89** | 仅 F4-02b／F4-13／F4-15 红，均为 OBSERVED 钉死格 |
| R17 Core | **46/46** | |
| R17 Agent | **33/33** | |
| R17 Worker | **33/35** | 仅 W5-05／W5-06a 红，OBSERVED 钉死格 |
| BK（存量形状） | **8/8** | |
| BM（黑洞自愈） | **22/22** | 真实 netns＋真实 ip |
| BO（tun1 repair） | **18/18** | |
| BP（boot restore） | **14/14** | |
| BQ（队列不可读） | **6/6** | |
| BR（loginfail 数组） | **11/11** | |
| BS（repair 判据） | **9/9** | |
| BT（enable 无占位符） | **23/23** | PASS 行 23，无 FAIL |
| R24（enable 占位符） | **25/25** | PASS 行 25，无 FAIL |
| R25（repair 收敛） | **37/37** | PASS 行 37，无 FAIL |
| R21（队列隔离） | **6/6** | |
| R22 Flask | **22/22** | |
| R22 Worker | **12/12** | |
| R23 Flask | **13/13** 主模式＋empty_secret 2 格／db_garbage／db_empty／db_old_admin 各 1/1 | empty_secret 两格均为大声 500／401 的预期行为 |
| R23 Worker | **9/9** | |
| R20 | 7 格，3 红（S1/S2/S6） | 均为缺陷钉死格的预期翻转（BK／BL 修净的证明；S6 的 HB-OK 回执即修复证据） |
| R18 队列竞态（Worker） | 9 格，2 红（RACE-02／RACE-05） | 缺陷钉死格预期翻转（BI 修净证明） |
| R18 畸形（Worker） | 13 格，9 绿 4 红（M-01／M-02／M-03／M-06） | 缺陷钉死格预期翻转（BI 修净证明；M-06 行实测记录已落 failed，探针断言的是旧行为） |
| R19 非列表容器（Worker） | **12/12** | |
| R19 .ovpn 下载（Worker） | **8/8** | |
| BI 队列竞态 | **15/15** | |
| BI 畸形 sweep | **18/18** | |
| BH poll 守卫（Worker） | **20/20** | |
| R27 verify 强制分歧 | **8/8** | |
| R27 UDP 判据 | **6/6** | |
| R27 Worker 悬空队列 | **5/5** | |
| R29 Worker toggle | **15/15** | |
| R29 Flask toggle | **13/13** | |
| R31 新探针（§1） | edge 22/22＋21/21；ctype 7/7＋6/6；bcrypt72 6/6 | |

**结论：全部红格均为已知缺陷钉死格的预期翻转（与 R26–R31 各轮一致），无回归、无新红格。**探针运行后宿主 `/etc/openvpn-sk5-panel/` 核查为空（0 凭据泄露）；fixture-server/server.conf 已复位为 port 1194。

**本轮调用教训（已处置，非产品问题）**：① 我的 runner 把 `r20_input_shapes.py` 错放进 nobody 组跑了两次——该探针卷首明言须 root（S6 的 unshare 格）；第一次还叠加了我把 /tmp chmod 755（nobody 无法 mkdir /tmp/r20），第二次 S6 的 /tmp/r20/ptree 为 nobody 所有 770、userns 内 root 无 CAP_DAC_OVERRIDE 而读不到。已纠正（`chmod 1777 /tmp`、`chmod -R a+rX /tmp/r20`、以 root 重跑），7 格 3 红与 R31 一致。② 另见 §5 的 /tmp 满盘事故：以后每轮先查 `df /tmp` 再跑门禁／变异。

## §7 live-18 与补记的交叉核对

- live-18＋supplement 的结论沿用：R31→R32 树改动仅两处（index.js 信封守卫、app.py bcrypt 72 字节上限），其余文件未动；live-18 的树侧可核项结论不受影响。
- R27–R31 修复的真机格（verify.sh 强制路径 API 恢复、UDP 判据、Worker 队列 TTL、toggle 布尔、整数 token、请求体信封、改密 72 字节）属 live-19，不在本轮沙箱审计内断言。
- 本轮新发现 R32-P2-1 的真机格（sing-box 启动耗时落在 4.6～5.0s 窄带时的 enable 行为）亦属 live-19：沙箱无法建 TUN／起 sing-box，只能以循环算术＋代码面定性；live 轮须以人工延迟启动实测该窄带。

## §8 差集（新发现）

### R32-P2-1（P2）——`enable()` 的 LIVE-tun1 等待窗口名义 5 秒、实际只查到约 4.5 秒：4.6～5.0 秒间变活的 tun1 被漏判，大声 500

- **机制**：`egress/sk5_manager.py:1226-1235`：
  ```python
  for _ in range(10):
      if _tun1_live():
          break
      time.sleep(0.5)
  else:
      raise RuntimeError("sing-box did not create a live tun1 within 5 s ...")
  ```
  先查后睡：10 次检查落在 t≈0、0.5、…、4.5s，第 10 次睡完（t≈5.0s）循环结束即 raise。4.6～5.0s 间才变 LIVE 的 tun1 无任何一次检查能看到——文案与 DELIVERY.md:131（“只等 5 秒”，O-R25-2）及 :148（“5 秒内没建出活 tun1”）宣称的 5 秒截止不符，实际有效窗口约 4.5 秒。
- **行为实证**：同构循环实测（纯算术复刻，无产品桩）：检查时刻 `[0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.01, 4.51]`，raise 在约 5.0s。`_tun1_live()` 每次另有约 10–30ms 的 `ip` 调用开销，只会把末查再往后推约 0.2s，仍在 5.0s 之前——漏判带约为 0.3～0.5s。代码面逐行核对（循环体先 `_tun1_live()` 后 `sleep(0.5)`，else 分支 raise）与实测一致。
- **范围（机械推导，闭合）**：全树产品代码的 `for _ in range` 等待循环仅 3 处（panel／core／egress／agent 全 grep）：① :1226 本处（立案）；② :713 临时 sing-box 监听等待 20×0.25s——先睡后查，末查在 5.0s，形状正确，作对照；③ :410 `_stop_singbox_direct` 20×0.25s 先查后睡——4.75～5.0s 间自然死的进程仍收 SIGKILL，已死／将死，无害，不立案。
- **不是既往项复发**：BT／R25 验证的是 5 秒窗口的存在与 8 秒延迟下的大声失败（live-17：8s 延迟→500 在 5.24s），从未核对末查时刻；O-R25-2 只裁定了“5 秒硬截止”的取舍，未核对循环算术。全树审计报告与文档中无任何“4.5 秒”记载，本条首次立案。
- **用户影响**：P2——大声 500，无静默错误、无泄漏、无数据损坏、无状态污染（enabled 保持 False、不改策略）；操作员重试即成功；仅 sing-box 启动耗时恰落在 4.6～5.0s 窄带时才触发（本机暖启动 0.84s，DELIVERY:131）。定 P2 不定 P1。
- **修法**：把循环改成 deadline 形（`end = time.monotonic() + 5`，查到 `end` 为止）或 `range(11)`（末查落在 5.0s），使“5 秒”宣称与行为一致；或改文案为 4.5 秒（不推荐——缩小窗口无收益）。同款先查后睡只剩 :410 且无害，不动。

## §9 未验与观察

- **P0-1（未验，沿用）**：Cloudflare Worker 真实部署仍未验证（wrangler.toml KV id 仍为占位符；dry-run 通过不等于部署可用）。README 与 cloudflare/README.md 的未验横幅在位。
- **O-R32-1（harness 教训，非产品问题）**：本轮首轮 11 棵 §7 变异门禁全 SKIP（`建 venv 失败`）——/tmp tmpfs 512M 被历轮残留（/tmp/r28～r31 等）占满 100%。已删 stale 轮次目录（保留 /tmp/r27 夹具／venv 与 /tmp/r32），释放至 394M 空闲后逐棵重跑 11/11 恰红。以后每轮变异门禁前先查 `df /tmp`。
- **O-R32-2（沿用 R22 观察）**：Retry-After 舍入差 1 秒（Flask `int(diff)+1` vs Worker `Math.ceil(diff/1000)`），不立案。
- **O-R32-3（沿用 R22 观察）**：证书过期 `when <= now` 的 1 秒算子注，不立案。
- **O-R32-4（沿用）**：会话有效期 Flask 12h vs Worker 24h，各自明文记载（security.md:10、cloudflare/README.md:165），不立案。
- **O-R32-5（live-19 待办）**：R32-P2-1 的真机格（sing-box 启动耗时落在 4.6～5.0s 窄带时的 enable 行为）属 live-19；沙箱无法建 TUN／起 sing-box，只能以循环算术＋代码面定性。
- **O-R27-1／O-R28-1／O-R29-1／O-R30-1／O-R31-1（发版步骤清单，非立案）**：新包切出时刷新 DELIVERY §9 与 front-matter：审计报告 25→32、live 报告 17→18＋supplement、台账 163→174（本轮新增 R32-P2-1）、终审 R25→R32、tarball 条目与 sha256 重算。

## §10 审计方法与证据

- **方法**：time-and-order boundaries。机械枚举全部超时／间隔／TTL／重试／排序规则（双面＋agent＋安装脚本＋systemd 单元）共 25 项（B1–B25），逐项核验精确值、边界瞬时行为、off-by-one、双定时事件交错；功能链以 README／DELIVERY／security.md 为骨架逐项对行为；门禁与探针套件全量重跑。
- **本轮新证据**：同构循环实测（检查时刻 0.0～4.51s，raise 约 5.0s）＋ `for _ in range` 全树 grep（仅 3 处等待循环，闭合）。
- **日志**：/tmp/r32/gate.log、/tmp/r32/gate-m-*.log、/tmp/r32/mutants-build.log、/tmp/r32/p-r31-*.log、/tmp/r32/p-*.log、/tmp/r32/run-r31.sh、/tmp/r32/run-probes.sh、/tmp/r32/run-mutants.sh。
- **台账**：R31 终点 173 条（已修 168、部分 2、未验 1、新 2）；本轮 R31 的 2 条复核关闭（已修 168→170），新增 1 条（R32-P2-1）→ **174 条**（已修 170、部分 2（按设计）、未验 1（P0-1）、新 1）。0 复发。
- **历史项闭合**：R26 的 2 条、R27 的 3 条、R28 的 1 条、R29 的 1 条、R30 的 1 条、R31 的 2 条——本轮均以行为证据复核关闭（§1／§3／§6），无一复发。

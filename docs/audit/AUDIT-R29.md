# AUDIT-R29 — 双面行为一致性全量审计（2026-11-13）

> 方法：cross-face behavioral consistency（与 R28 零用户旅程、R27 adversarial operator、R26 repo-consumer journey、R25 repair-path convergence 均不同）。产品有两面（Flask 服务器面板与 Cloudflare Worker 面板），须在同一前端与同一命令契约下行为一致。本轮机械枚举双面全部 API 路由、队列操作、判据与错误路径，逐项核对两面是否一致；同机制行为只落一面即立案。另全量复核功能链（README／DELIVERY.md／security.md 逐项对行为）与 R28 修复的行为闭合。
> 审计树：`~/workspace/openvpn-sk5-panel/`，git main @ b395ef3（1.0 发布提交，与公开仓库一致）＋未提交工作区改动（R26 文档修复：README 克隆路径、DELIVERY §1.3 verify.sh 措辞、verify.sh 头注释；R27 修复：verify.sh cleanup API 恢复、egress/sk5_manager.py UDP 判据、cloudflare/src/index.js 队列 TTL；R28 修复：README Cloudflare 节填 id 步＋未验横幅＋“可选”、cloudflare/README.md 未验行、DELIVERY §1.3 失败路径句＋§5 二档括号）。
> 历史台账：R28 终点 169 条（已修 160、部分 2（按设计）、未验 1（P0-1 Cloudflare 真实部署）、新 1（R28-P2-1，本轮已验关闭））。本轮新增 1 条后台账 170 条（已修 160、部分 2、未验 1、新 1）。
> 夹具：/tmp/r29/ptree（本地工作树副本，含未提交修复）；fixture／venv 复用 /tmp/r27（fixture-ca 含 ta.key、fixture-server server.conf port 1194 proto udp，属 nobody 所有；venv Flask 3.1.3＋bcrypt）；系统 python3 无 flask（预期）。

## verdict：**不能交付：差集 1 条，P2×1（R29-P2-1），见 §8**

门禁 29/29；§7 变异 11/11 恰红 28/1；探针全套重跑见 §6（历史关闭项无一复发；全部红格均为缺陷钉死格的预期翻转）。Cloudflare Worker 真实部署仍 P0-1 未验。

## §0 审计基线与树状态

- 本地树：main @ b395ef3，`git status`：6 文件已修改未提交（README.md、cloudflare/README.md、cloudflare/src/index.js、docs/DELIVERY.md、egress/sk5_manager.py、verify.sh——R26 修复＋R27 修复＋R28 修复）；未跟踪：docs/audit/AUDIT-R26.md、docs/audit/AUDIT-R27.md、docs/audit/AUDIT-R28.md、docs/live-verify-R18.md、docs/live-verify-R18-supplement.md、docs/audit/AUDIT-R29.md（本轮）、tests/r27_verify_forced_divergence.py、tests/r27_udp_probe_verdict.py、tests/r27_worker_dangling_queue.mjs（R27 新探针）。
- 公开仓库：https://github.com/iiiiiiiii7125-art/openvpn-sk5-panel（public，用户 2026-11-13 令公开）。本轮审计的是本地工作树（含未提交修复），不是仓库 HEAD——仓库 HEAD 仍为 b395ef3，未含 R26／R27／R28 修复；发新版前须提交并推送（见 §9 收尾）。
- 探针树：/tmp/r29/ptree（本轮新建的工作树副本）；fixture／venv 复用 /tmp/r27（跑前复核通过：server.conf 1194 udp、fixture-ca 含 ta.key、属 nobody 所有，无需重建）。
- /etc/openvpn-sk5-panel/：本轮跑前已存在，跑前复核为空（0 泄漏起点）。

## §1 R28 修复闭合核验（行为实证，不认代码在场）

### §1.1 R28-P2-1(a) README Cloudflare 节填 id 步＋未验横幅＋“可选”

- README:87 `## 部署方式二：Cloudflare 面板 + agent（可选，FLMX 同款）`——“推荐”已改“可选”；README:89 未验横幅在位（P0-1、KV id 仍为占位符、dry-run 通过≠可用、部署后须验活）；步骤含 `wrangler kv namespace create PANEL_KV --preview` 与「把两条命令输出的 id / preview_id 填进 wrangler.toml 对应位置」注释行（本轮 grep＋读节核实）。
- 全 README `grep -n "推荐"` 仅 1 处：:74「可选环境变量」——无“推荐”残留；全树（除 audit／live 报告外）“推荐”仅 egress/README.md:55「systemd（可选但推荐…）」，与 Cloudflare 模式无关。
- cloudflare/README.md:3 未验横幅在位；wrangler.toml:32-33 仍为占位符 `REPLACE_WITH_KV_NAMESPACE_ID`／`REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`（本轮已核，与横幅一致）。
- 三份文档 Cloudflare 步骤逐项比对：DELIVERY §2.1（含填 id 步＋未验横幅）✓、cloudflare/README.md（含填 id 步＋未验标注）✓、README（两项皆补）✓——R28-P2-1 的两缺口均已闭合。
- **结论：R28-P2-1(a) 已关闭。**

### §1.2 R28-P2-1(b) DELIVERY §1.3 失败路径句（对 verify.sh cleanup() 行为核验）

- DELIVERY:43 与 README:184 的失败路径句：「清理失败时文件故意不恢复（大声 FAIL，链路诚实保持禁用，备份留在工作目录供人工恢复）」。
- 行为核验（verify.sh cleanup() 全文已读 :94-200）：API 重启用失败时（备份无 host/port :147、未登录 :150、POST 非 200 :162）`_restore_failed=1`，文件拷贝分支（:171 起）被跳过——文件**不**恢复；尾部 :190-194 大声 FAIL「restore FAILED…workdir kept at $WORKDIR」，链路诚实保持禁用。句句属实。
- **结论：R28-P2-1(b) 失败路径句已关闭。**

### §1.3 R28-P2-1(c) DELIVERY §5 二档括号（对 _socks5_udp_associate_dns 行为核验）

- DELIVERY:122「（native UDP ASSOCIATE + DNS to 1.1.1.1:53；无应答时重试第二档 cloudflare.com / 8.8.8.8）」。
- 行为核验（egress/sk5_manager.py:559-646 全文已读）：`attempts = [(DNS_QUERY_NAME, DNS_SERVER), (DNS_QUERY_NAME2, DNS_SERVER2)]`，第一档 example.com/1.1.1.1、第二档 cloudflare.com/8.8.8.8；超时／不匹配回复落入下一档；无 txid 匹配回复时回 False 并点名两档。括号属实；O-R28-3 由此关闭。
- **结论：R28-P2-1(c) 二档括号已关闭。**

### §1.4 全树 Cloudflare 文档漂移扫

- `grep -rn "未验"`（除 audit／live 外）：README:89、cloudflare/README.md:3、DELIVERY:4-5、:47、:134——Cloudflare 未验标注在三份入口文档均在位，无遗漏。
- `grep -rn "Cloudflare"`：README、DELIVERY §2、cloudflare/README.md、cloudflare/server-mode.md、security.md——server-mode.md 的模式宣称与 R11 裁定一致（见 §2  adjudicated 清单），无新漂移。
- **结论：R28-P2-1 全部关闭。**

## §2 双面行为一致性矩阵（核心推导）

枚举方法：Flask 36 条路由（panel/app.py `@app.route` 全集）× Worker handleFetch 分发表（cloudflare/src/index.js:1384-1500）逐项比对；前端（panel/templates/index.html 的 api()/apiWait()/withNode() 调用全集）为第三证——同一前端调同一路径时两面须给出同一 verdict。

### §2.1 路由全集对照（36 Flask 路由 × Worker 分发表）

| 路由 | Flask | Worker | 结论 |
|---|---|---|---|
| GET / | 静态 index.html | Static Assets（未配 503） | 同形；Worker 资产未配时大声 503 |
| POST /api/login | 400 畸形不记限流；401；5 次／5 分钟→锁 15 分钟 429＋Retry-After＋retry_after_s；bcrypt 透明迁移 | 同款（R13-P2-4 畸形 400 不记限流；BR loginfail 数组归一化；锁期内正确密码仍 429） | ✓ 一致（Retry-After 舍入差 1 秒为 R22 已 adjudicated 观察） |
| POST /api/logout | session.clear() | KV 删 session＋清 cookie | ✓ 一致 |
| POST /api/change-password | 真改密（旧密校验＋强度＋session_version+1 全会话作废＋admin.pass 同步） | 恒 501＋`wrangler secret put ADMIN_PASSWORD` 明示 | ✓ 已 adjudicated 设计差（R11-P2-1） |
| GET /api/me | 公开探针（无 login_required），匿名 200 {admin:false} | requireAdmin 后 {ok:true, admin:true}，匿名 401 | ✓ 已 adjudicated（R3：Flask 公开探针按设计；R5 Worker 探针钉 401；前端两种都收敛到登录页） |
| GET /api/status | 本机现算；远程读快照（_remote_status_payload） | cachedStatus（快照＋mergeServerCfg） | ✓ 一致（via_sk5 三分支逐字同款，见 §2.2） |
| POST /api/openvpn/server | 本机渲染／远程入队 create_server | 入队 create_server | ✓ 一致 |
| GET /api/openvpn/public-ip | 本机探测公网 IP | 无此端点 → 404「未知接口」 | ✓ 已 adjudicated 诚实降级（R11：前端 catch 明写「Cloudflare 模式无此端点，请手动填公网 IP/域名」） |
| POST /api/openvpn/start\|stop\|restart | 本机执行／远程入队 | 入队 | ✓ 一致 |
| POST /api/openvpn/init-pki | `is not True` 严格 400（force／confirm 缺一律 400 先于节点判定） | `!== true` 严格 400，同款顺序 | ✓ 一致 |
| GET /api/openvpn/users | 本机现算／远程读快照 | 读快照 users | ✓ 一致（快照滞后 caveat 双面同款） |
| POST /api/openvpn/users | 本机建用户／远程入队 create_user | 入队 create_user | ✓ 一致 |
| DELETE /api/openvpn/users/&lt;name&gt; | 本机吊销／远程入队 revoke_user | 入队 revoke_user | ✓ 一致 |
| GET /api/openvpn/users/&lt;name&gt;/ovpn | 本机／?node=／/api/nodes 三路径共用 _download_block_reason | handleCompatOvpnDownload：快照守卫＋同义 403 文案（R19-P2-2） | ✓ 一致（文案逐字比对见 §2.3） |
| GET /api/sk5 | 本机现算／远程读快照（密码脱敏） | 读快照（snapshotFromResult 已剔密码） | ✓ 一致 |
| POST /api/sk5 | 本机／远程：host 必填、port `type is int`、开关 _strict_bool／_coerce_bool（非布尔 400）、P0-4 空密码保留 | host 必填、port Number.isInteger、开关 typeof 回落存量（R12 参照修法）、P0-4 空密码保留、1-25 UDP 硬拒 | △ 见 §2.4（1-25 为已 adjudicated Worker-only 守卫＋共享前端确认；其余一致） |
| POST /api/sk5/test | 本机直探／远程入队 test_sk5 | 入队 test_sk5 | ✓ 一致 |
| POST /api/sk5/enable\|disable | 本机 set_sk5 有效态检查／远程入队 | 入队 enable_sk5／disable_sk5 | ✓ 一致（agent 侧同一 sk5_manager） |
| POST /api/sk5/fail-open | _strict_bool（非布尔 400；缺键默认 False） | handleCompatSk5Toggle：typeof 回落＋终端 `: false`＋enabled 回落键 | ✗ **P2，见 R29-P2-1** |
| POST /api/sk5/udp-over-tcp | _toggle_value（udp_over_tcp 优先、回落 enabled；非布尔 400） | handleCompatSk5Toggle 同款结构 | ✗ **P2，见 R29-P2-1** |
| GET /api/nodes | 读库行（last_status 原样） | 读 KV＋快照派生字段（online_users／egress_ip／sk5_enabled／status_age_s） | ✓ 一致（前端 normalizeNode 双形收敛） |
| POST /api/nodes | 201＋token（只返一次），无 install_command | 201＋token＋install_command | △ 响应多一字段，前端忽略 install_command（showTokenBox 自建命令），无行为差 |
| DELETE /api/nodes/&lt;name&gt; | 先扫坏条目再删库行；queued＋sent 一并标 failed | 先 sweep 再删记录；queued＋sent 标 failed | ✓ 一致 |
| POST /api/nodes/&lt;name&gt;/rotate | 200＋新 token（旧立即失效） | 同款（另附 install_command） | ✓ 一致 |
| POST /api/nodes/&lt;name&gt;/install | **无此路由** → 404 | handleNodeInstall（command_template） | ✓ 已 adjudicated（前端 catch 回落 client-side buildInstallCommand，两面终态同为复制出命令） |
| POST /api/cmd | action 白名单 13 项；params 须对象；ghost 404；202＋cmd_id | 同款（R12-P2-4 list params 400；R12-P2-5 body.node 优先） | ✓ 一致 |
| GET /api/cmd/&lt;id&gt; | 坏条目隔离＋重投超时；缺键错型仍 200 展示残值（R12-P2-7） | 同款（kvArray／_sweepWorkerCmds） | ✓ 一致 |
| GET /api/nodes/&lt;node&gt;/users/&lt;user&gt;/ovpn | 快照守卫 403／404（R13-P2-3） | 无此路由（Worker 只认 /api/openvpn/users/&lt;name&gt;/ovpn＋?node=） | △ 前端只调后者（withNode 显式带 ?node=，index.html:748）；该路由无前端调用方 |
| GET /api/audit | SQLite audit_log（limit 上限 500） | 无此路由（Worker 无审计存储，只有 console.warn） | ✓ 已 adjudicated 架构差（security.md:18 只点名 Flask 面；无前端调用方） |
| POST /api/agent/poll | queued 守卫（R17-P1-1）＋panel_url 认领守卫 | 同款（BH 探针） | ✓ 一致（§6 重跑） |
| POST /api/agent/report | 只接受 sent 态回执（非 sent 409＋审计 agent_report_not_sent；坏条目 200 回 failed） | 同款（BH 探针） | ✓ 一致（§6 重跑） |
| GET /api/agent/bundle(.sha256) | 本地文件下发＋sha256 | 源站代理＋sha256 验后下发；未配 AGENT_BUNDLE_ORIGIN 503 明示 | ✓ 一致（Worker 503 为诚实降级，P0-3） |
| GET /install-agent.sh(.sha256) | 本地文件下发 | 源站代理；未配 503 | ✓ 一致 |

### §2.2 /api/status via_sk5 三分支逐字比对

- Flask 本机 status()（app.py:1498-1520）与远程 _remote_status_payload（:876-953）与 Worker cachedStatus（index.js:1069-1110）：三分支逐字一致——enabled＋policy_routing_active → via_sk5=true（探针 IP 取不到时 ip=null 但 via_sk5 仍 true，kill-switch 工作态 case D）；仅 enabled → via_sk5=false＋ip=null＋同字错误「SK5 已启用但策略路由未生效，出口未经过 SK5」；未启用 → 直连探针 IP＋via_sk5=false。stale 阈值双面 60 秒；无快照 note 文案同字。
- **结论：via_sk5 判据双面一致（R6-P1-1／R7-P1-1 无复发）。**

### §2.3 .ovpn 下载守卫文案比对

- Flask _download_block_reason（app.py:850-859）：revoked →「已被吊销，.ovpn 不可下载（证书已进 CRL）」；expired →「证书已过期，.ovpn 不可下载」；三条路径拼装「用户 %s %s」。
- Worker handleCompatOvpnDownload（index.js:1165-1199）：revoked →「用户 {name} 已被吊销，.ovpn 不可下载（证书已进 CRL）」；expired →「用户 {name} 证书已过期，.ovpn 不可下载」——与 Flask 拼装后逐字相同；无快照／快照无该用户时放行（与 Flask _snapshot_users 回空 dict 时放行同款）。
- **结论：下载守卫双面一致（R19-P2-2 无复发）。**

### §2.4 POST /api/sk5 的 1-25 守卫（已 adjudicated，不立案）

- Worker handleCompatSk5Save 独有 1-25 硬拒：UDP 模式＋同一地址最近一次 UDP 测试明确失败 → 400（index.js:1223-1242）。Flask sk5_save 无此守卫——直接 API 调用可保存 UDP 已失败的 SK5（200），随后启用走同一 sk5_manager.enable()（双面同款，不测 UDP 即启用；失败由测试按钮与健康检查诚实揭示）。
- 不立案的理由（adjudicated 设计差，须引裁定）：R1 原项 1-25 的口径是「表单直接拒绝」；R15／R16／R17 的 FLMX 对照表逐轮把 1-25 记为「Worker UDP 保存守卫＋前端确认」「照抄」——守卫落 Worker 面是 FLMX 参照的既定分工；前端 1-25 确认（index.html:1196-1201：UDP 模式＋lastTest.udp.ok===false 时 confirm，不测不拦、保存后提示先测）是双面共享的，Flask 面并非零防护。Worker 硬拒是纵深一层，不是 Flask 面的缺失。
- **结论：1-25 守卫分工已 adjudicated，本轮不立案。**

### §2.5 13 动作白名单三面逐字一致（沿用＋抽查）

- Flask AGENT_ACTIONS（app.py:199）、agent ACTIONS（agent.py:754）、Worker ACTIONS（index.js:64）——本轮亲手重数：三面各 13 项，排序后逐字相同（`create_server/create_user/disable_sk5/enable_sk5/get_status/init_pki/install_prereqs/restart_openvpn/revoke_user/set_sk5/start_openvpn/stop_openvpn/test_sk5`）；本轮树在 R27 后未改三面（git diff：index.js 改动仅 7 处 TTL＋2 处 warn，ACTIONS 未动）。
- **结论：白名单三面一致。**

### §2.6 双面分歧总账（除 R29-P2-1 外全部已 adjudicated）

- 已 adjudicated：change-password 501（R11-P2-1）、/api/me 匿名 verdict（R3／R5）、public-ip 缺端点（R11 诚实降级）、install 路由缺失（前端回落）、_resolve_compat_node 未指定时本机执行 vs Worker 单节点自动（app.py:791-803 docstring 明言刻意保留）、/api/audit 缺失（Worker 无审计存储）、1-25 守卫分工（R15-17）、register 响应多 install_command 字段（前端忽略）、nodes_list 形状差（前端 normalizeNode 收敛）、bundle／install-agent.sh 源站代理 503（P0-3）。
- 未 adjudicated：仅 R29-P2-1（§8）。

## §3 功能链全量对账（README / DELIVERY.md / security.md 逐项对行为）

### §3.1 机械计数复核（本轮独立重算）

- **13 动作白名单三面逐字一致**：见 §2.5（本轮亲手重数 13/13/13 逐字相同）。
- **verify.sh 24 项检查**：R27 §1.2 独立重算 24 distinct 名＋12 编号节；本轮 verify.sh 自 R27 后只改 cleanup() 恢复逻辑与头注释，未增删检查名——计数沿用；门禁 §5 另验。
- **发布包快照（DELIVERY §9 是 1.0 包的真实快照）**：本轮实测 `tar tzf releases/ovpn-release-1.0.tar.gz | wc -l` = 92 条目；`docs/audit/` 26 条（含目录条目，即 25 份报告 AUDIT-R1–R25）；`docs/live-verify` 17 份；与 §9 所列（78 文件、审计 25 篇、live 17 份）一致。当前树已有审计 29 篇（R1–R29）、live 19 份（live-verify.md＋R2–R18＋补记）——差额属发版后新增，§9 刷新属发版步骤（见 §9 清单），不当轮立案。
- **install.sh 固定清单与 README 一致**：install.sh:469 `agent core egress panel systemd install.sh verify.sh verify-integration.sh README.md` 与 README 所列逐字一致；`.git/` 不进 /opt（清单复制）。
- **verify.sh 退出码**：FAIL 数即退出码（尾部 `exit "$FAIL"`）✓，与 README 一致。

### §3.2 功能矩阵（功能 → 行为证据；探针编号见 §6）

| 功能（README／DELIVERY 宣称） | 行为证据 | 结论 |
|---|---|---|
| OpenVPN UDP 1194 主／TCP 443 备 | Core 46/46（§6 重跑）；install.sh 环境变量＋存量继承＋非法值早死 | ✓ 沙箱级；数据面属 live 轮 |
| 建用户／吊销／下载 .ovpn | Core 46/46；Flask 86/89（绿格内）；用户名正则＋保留名逐字一致 | ✓ |
| SK5 启用／停用 | BM 22/22、BO 18/18、BS 9/9、BT 23/23、R24 25/25、R25 37/37（§6 重跑） | ✓ |
| 断网保护 fail-closed | BM K1–K5（真实 netns＋真实 ip） | ✓ |
| 健康检查 60 秒＋自愈 | 定时器 OnUnitActiveSec=60s；BM H1–H10；BS 9/9 | ✓ |
| 命令队列＋agent 5 秒 poll | POLL_INTERVAL=5（agent.py:70）；R17 四套件；R21 6/6；BQ 6/6 | ✓ |
| Flask＋Worker 双面 | R17 四套件；BR 11/11；R27 Worker 5/5；本轮 §2 矩阵 | △ 除 R29-P2-1 外一致（见 §8） |
| 登录限流 | Flask／Worker 双面格；BR 11/11；429＋Retry-After（app.py:1305） | ✓ |
| 密码处理 | bcrypt＋透明迁移；改密格；Worker 改密 501；默认口令 grep 零命中（§4） | ✓ |
| 重建 CA（force+confirm） | Flask F-cells；R17-P1-1 守卫；双面 `is True`／`!== true` 严格判定（§2.1） | ✓ |
| /api/sk5/test UDP 腿 | 判据已修 round-trip 证明（R27-P2-1，探针 6/6 重跑见 §6） | ✓ 已关闭 |
| verify.sh 强制路径 | API 先行恢复运行链（R27-P1-1，探针 8/8 重跑见 §6） | ✓ 已关闭 |
| README Cloudflare 节 | 填 id 步＋未验横幅＋“可选”均已补（§1） | ✓ 已关闭 |
| SK5 开关布尔输入 | Flask 严格 400；Worker toggle 回落 | ✗ P2，见 R29-P2-1 |

## §4 安全清单对账（docs/security.md 逐项抽查）

- **默认口令字面量零命中**：`grep -rnw "admin123\|changeme\|123456\|password123" panel/ agent/ cloudflare/src/` 零命中 ✓。
- **限流 XFF 守卫**：仅 `OVPN_TRUSTED_PROXY=1` 时才信任 X-Forwarded-For（app.py:182-183，ProxyFix），默认不信任 ✓。
- **会话**：Cookie HttpOnly＋SameSite=Lax、12 小时、改密后 session_version+1 全旧会话失效——R17 Flask 绿格内（§6 重跑）。
- **SK5 凭据**：只存 sk5.json（0600），get_status 只回 has_password、日志脱敏——R17 Flask 绿格内；P0-4 保留密码语义（§2.4 已复算）。
- **命令重投非幂等风险**：security.md 已诚实记录（O-R27-2 沿用，不立案）。
- **agent 通道**：panel_url 须 HTTPS（仅 127.0.0.1／localhost／[::1] 例外）、禁 https→http 降级重定向——R17 Agent 33/33（§6 重跑）。
- **结论：security.md 抽查项与行为一致，无新缺口。**

## §5 门禁（verify-integration.sh 29 格，串行）

- **正树：PASS=29 FAIL=0 SKIP=0，exit 0**（/tmp/r29/ptree 上跑，约 21 秒，树静止后串行——门禁 harness 非并发安全，固定 /tmp/ovpn-int-test＋8443 端口；日志 /tmp/r29/gate.log）。
- **§7 变异 11/11 恰红 28/1**：`tests/build-mutants.py` 造 11 棵变异树（m-char、m-const-sb、m-dict-extra、m-dict-missing、m-dict-sb、m-dict-ts、m-dict-x-a、m-dict-x-amd、m-dict-x-arm、m-dict-x-b、m-install-sb），逐棵串行跑门禁，**每棵均为 PASS=28 FAIL=1 SKIP=0、exit=1，且唯一红格全为 §7「钉死哈希不一致：install.sh 与 agent/agent.py 的 sha256 逐键不等」**（逐棵 grep 核对，每棵恰 1 行 [FAIL]，无第二红格；日志 /tmp/r29/gate-m-*.log；汇总 /tmp/r29/mutant-summary.txt）。

## §6 探针套件重跑

全部在 /tmp/r29/ptree（工作树副本）上重跑；Flask 类跑在 nobody 身份＋venv＋fixture env（OPEN 前缀＋OVPN_SK5_CONFIG_DIR），Worker 类 `node tests/*.mjs`。**红格说明**：下表凡标注「预期翻转」的红格均为缺陷钉死格（探针断言的是缺陷行为本身，修复后按设计翻红），非回归。完整日志 /tmp/r29/py-probes.log、/tmp/r29/bt.log、/tmp/r29/r24.log、/tmp/r29/r25.log。

| 套件 | 结果 | 备注 |
|---|---|---|
| R17 Flask | 86/89 | 仅 3 个预期 OBSERVED 翻转（F4-02b／F4-13／F4-15） |
| R17 Core | 46/46 | |
| R17 Agent | 33/33 | |
| R17 Worker | 33/35 | 仅 2 个预期 OBSERVED 翻转（W5-05／W5-06a） |
| BK（存量形状） | 8/8 | |
| BM（黑洞＋自愈） | 22/22 | |
| BO（tun1 repair） | 18/18 | |
| BP（boot restore） | 14/14 | |
| BQ（队列不可读） | 6/6 | |
| BR（Worker loginfail 数组） | 11/11 | |
| BS（verdict） | 9/9 | |
| BT（占位符消除） | 23/23（PASS 行重数 23，0 FAIL） |
| R24（enable 占位符） | 25/25（PASS 行重数 25，0 FAIL） |
| R25（repair 收敛） | 37/37（PASS 行重数 37，0 FAIL），须 root |
| R21（队列隔离） | 6/6 | |
| R22 Flask（时间边界） | 22/22 | |
| R22 Worker | 12/12 | |
| R23 Flask（持久态形状） | 13/13（main）＋empty_secret／db_garbage／db_empty／db_old_admin 各 1/1 PASS |
| R23 Worker | 9/9 | |
| R20（输入形状） | 7 格，3 红为预期缺陷钉死翻转（S1／S2／S6）；须 root |
| R20／R21 回退变异 | 各 2 棵变异树已造并通过（m-kvarray／m-dlguard／m-blackhole／m-repair） |
| R18 Worker race／malformed | race 9 格 2 红、malformed 13 格 4 红，均为预期翻转 | R18 探针断言的是缺陷行为；修复后行为由 BI 套件验证 |
| R18 BG（Flask R17-P1-1 面） | 22/22 | |
| R19 非列表容器／ovpn 下载 | 12/12、8/8 | |
| BH Worker poll guard | 20/20 | |
| BI Worker queue race／malformed | 15/15、18/18 | |
| R27 强制分歧 | 8/8 | R27-P1-1 闭合（§1 另有独立复算沿用） |
| R27 UDP 判据 | 6/6 | R27-P2-1 闭合 |
| R27 Worker 悬空队列 | 5/5 | R27-P2-2 闭合 |
| **R29 双面开关布尔（新）** | Flask 9/9、Worker 10/10 | 分歧格全部实证确认，见 §8 R29-P2-1 |

**注**：R23 empty_secret 模式摘要行打印为 `R23 empty_secret: <redacted>`——该行是探针自身对 secret 值的脱敏打印，非失败；该模式唯一格 R2b（空 secret 下真实登录大声 500）为 PASS，故该模式计 1/1。本轮 BT／R24／R25 首次跑时 runner 的 `tail -4` 截断了逐格行，已按全量日志重数（bt.log／r24.log／r25.log：23／25／37 行 PASS，0 FAIL）。

**结论**：历史关闭项无一复发；全部红格均为钉死缺陷行为的预期翻转；R29 新探针的 8 个分歧格全部实证确认。

## §7 live-18 与补记的交叉核对

- 自 R28 以来产品代码零改动：`git status` 的 6 个已改文件与 R28 §0 的 5 个＋R28 修复的 cloudflare/README.md 完全一致；R28 修复只动三份文档（README、cloudflare/README.md、DELIVERY），未碰任何产品代码。live-18／补记的树侧可核项结论全部沿用，无须重核。
- R29-P2-1 是 Worker 面行为：live 轮只验服务器面（Worker 无真实部署，P0-1），故本条无真机格可对账；沙箱双面探针（Flask 9/9＋Worker 10/10）即本轮的完整证据，真机复核不适用。
- R27-P1-1／P2-1／P2-2 三条的真机格属 live-19，待 live 轮（R28 §7 沿用）。

## §8 差集（新发现）

### R29-P2-1（P2）——Worker 的 /api/sk5/fail-open 与 /api/sk5/udp-over-tcp 对非布尔开关输入静默套用错误值，而 Flask 面 400；且 fail-open 路由把 `enabled` 当回落键

- **机制（双面同输入不同 verdict，机械枚举）**：两条专用开关路由的布尔输入处理在两面走了不同分支：
  - Flask（panel/app.py）：fail-open 用 `_strict_bool(data, "fail_open", False)`（:2270）、udp-over-tcp 用 `_toggle_value(data, "udp_over_tcp", fallback="enabled", default=False)`（:2309）；底层 `_coerce_bool`（:1091-1105）只接受真布尔与 0/1 整数，其余一律 400（R12-P2-1 修法，探针钉死）。
  - Worker（cloudflare/src/index.js handleCompatSk5Toggle，:1252-1280）：`value = typeof b[key] === "boolean" ? b[key] : typeof b.enabled === "boolean" ? b.enabled : false`——非布尔输入既不 400 也不回落存量，而是终端回落 `false`；且 `enabled` 键在 fail-open 路由上同样被当作回落键。
- **行为实证（双面新探针，计数背书）**：
  - `tests/r29_worker_toggle_bool.mjs` **10/10**（mock KV＋本地 fetch 入口；W0 注册＋保存各 1 格＋T1–T8 分歧格 8 格）与 `tests/r29_flask_toggle_bool.py` **9/9**（test_client＋?node= 远程入队分支，验证在入队前跑，故为路由级实证；F0 注册 1 格＋T1–T8 8 格）逐格对照，8 格输入双面 verdict 如下：
  - T1 `{"fail_open": "true"}`：Flask 400；Worker 202，入队 `fail_open=false`（调用方要开却被静默关掉）。
  - T2 `{"fail_open": 1}`：Flask 202 入队 `fail_open=true`；Worker 202 入队 `fail_open=false`（同值反向）。
  - T3 `{"enabled": true}`：Flask 202 入队 `fail_open=false`（缺键默认）；Worker 202 入队 `fail_open=true`（回落键误用——`enabled` 不是该路由的键，调用方若把“启用 SK5”误发到此路由，会静默打开 fail-open，即 SK5 死时流量回直连，属安全相关开关的误应用）。
  - T4 `{"fail_open": false}`：双面 202＋false，一致（对照格）。
  - T5 `{"udp_over_tcp": "true"}`：Flask 400；Worker 202 入队 `false`。
  - T6 `{"udp_over_tcp": 1}`：Flask 202 入队 `true`；Worker 202 入队 `false`（同值反向）。
  - T7 `{}`：双面 202＋false，一致（对照格）。
  - T8 `{"fail_open": "false"}`：Flask 400；Worker 202 入队 `false`（值碰巧一致，verdict 仍分歧）。
- **不是 R12-P2-1／P2-2 的复发**：R12-P2-1 修的是 Flask 面的 `bool()` 反向（已修，AS  lane＋本轮 T1／T5 复核仍 400）；R12-P2-2 修的是 Flask udp-over-tcp 读错键（已修，本轮 T6 复核 Flask 正确读键）。本条是 Worker 面 handleCompatSk5Toggle 的同族新成员：R12 当时以 Worker 的 `typeof === "boolean"` 回落为参照修法，但参照的只是「字符串不反向」（保存路由回落存量），toggle 路由的终端 `: false`＋`enabled` 回落键从未被任何一轮探针覆盖（r17_worker.mjs 全文无 fail-open／toggle 格；R12 的 Worker 侧只审了键优先级，未审终端回落值）。机制同族、位置与谓词不同，按「修 a 漏 b」同族新成员立案，不算复发。
- **范围（机械推导，闭合）**：全树布尔输入点枚举——Flask 全部开关经 `_coerce_bool`／`_strict_bool`／`_toggle_value`（:1091-1120，调用点 14 处，见 §2.1 表）；Worker 侧：handleCompatSk5Save 三开关回落存量（R12 参照，安全）；handleCompatInitPki `!== true` 严格 400（安全）；仅 handleCompatSk5Toggle 两路由（fail-open／udp-over-tcp）带终端 `: false`＋enabled 回落。无第三处。
- **用户影响**：P2——前端从不直接调这两条路由（开关走 `/api/sk5` 保存体，index.html:1191-1192 发真布尔），故非现网 break；但 API 调用方（脚本、第三方集成）按直觉发 `"true"`／`1` 会静默得到反向值，且 fail-open 是安全相关开关（T3 的误开方向会让 SK5 死时流量回直连）。与 R12-P2-1／P2-2 同级的潜伏陷阱。
- **修法**：Worker handleCompatSk5Toggle 改严格判定：`b[key]` 在时须为真布尔或 0／1（其余 400，与 Flask `_coerce_bool` 同口径）；`enabled` 回落键只保留在 udp-over-tcp 路由（R12-P2-2 已裁定该路由与 Worker 同款），fail-open 路由删回落（R12 已裁定 Flask fail-open 只读本键是对的）；缺键时默认 False 不变（T7 双面已一致）。修后补探针格（本轮两探针即现成回归套件）。

## §9 未验与观察

### 发版前检查清单（非 finding，O-R27-1／O-R28-1 延续）

新版重打时 DELIVERY §9 与卷首台账须按实测刷新（§9 仍为 1.0 包的真实快照，本轮已核 92 条目／审计 25 篇／live 17 份无误）：审计 25→**29** 篇（R26／R27／R28／R29）、live 17→**18 份＋补记**（live-verify-R18.md＋live-verify-R18-supplement.md）、台账 163→**170**（169＋R29 新 1）、终审 AUDIT-R25→**AUDIT-R29**、门禁计数仍 29 格（本轮重跑 29/29）。R29-P2-1 修完后须重跑本轮两探针（Flask 9/9＋Worker 10/10 应翻为双面一致）＋门禁 29/29，再打新包。

### O-R29-1（观察，不立案）：Worker toggle 路由的 `enabled` 回落键在 udp-over-tcp 上是已裁定的

- R12-P2-2 已裁定 Flask udp-over-tcp 读 `udp_over_tcp` 优先、回落 `enabled`（与 Worker 同款）；故修法时只删 fail-open 路由的回落，不动 udp-over-tcp 路由的回落。见 §8 修法段。

### O-R27-2（观察，延续）：agent 侧无命令去重，重投即重执行（已文档化、危害有界）

- security.md:12 已诚实记录；create_user 二次执行报已存在、init_pki 二次执行无新增用户损害、其余动作幂等。不立案。

### O-R27-3（观察，延续）：OVPN_PORT 前导零大声失败，不断言

- `OVPN_PORT=0117` 过 bash 八进制检查、Python 渲染为 117、grep 校验 die——大声失败，无静默错配。不立案。

### P0-1（站立未验）：Cloudflare Worker 真实部署

- 本轮仍无真实部署可验，不冒充。Worker 面只跑 mock-KV 探针。wrangler.toml KV id 仍为占位符（:32 `REPLACE_WITH_KV_NAMESPACE_ID`、:33 `REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`，本轮已核）。

### arm64 真机安装／SK5 端口 1001 vs 9000

- 均未变：无 arm64 机，仍未验；端口用户仍未确认，面板默认 1001。

## §10 审计方法与证据

- 探针一律在 /tmp 树副本＋venv＋nobody 身份下跑（Flask 类），env 名用 OPEN 前缀（`OPENVPN_CA_DIR`／`OPENVPN_SERVER_DIR`）＋`OVPN_SK5_CONFIG_DIR`；各探针的树 env 名按探针头读名设值（BQ_TREE／R21_TREE／R22_TREE／R23_TREE／R17_TREE／R29_TREE／BG_TREE）；r20／r25／r27-verify／BT／R24／BO／BM／BP 须 root 跑（unshare 绑挂／ip 操作），且 /tmp/r29 整条路径须对 userns 内可遍历（755）；fixture-server／fixture-ca 须属 nobody 所有。/etc/openvpn-sk5-panel/ 每次跑后复核为空（终态复核：空，0 泄漏）。
- 沙箱 UDP/TUN EPERM 为环境假象，不作产品结论；数据面结论属 live 轮。
- 本轮复跑中纠正的调用口径问题（数字为纠正后实测，如实记账）：① 新写 Worker 探针首版漏返 headers，登录取不到 Set-Cookie——补 `headers: r.headers` 后 10/10；② BT／R24／R25 首次跑时 runner 的 `tail -4` 截断逐格行，已按全量日志重数 23／25／37（bt.log／r24.log／r25.log）；③ build-mutants.py 首调漏了 `<clean-tree-dir>` 参数（用法为 `build-mutants.py <clean-tree> <out-dir>`），纠正后 11 棵变异树建成。
- 门禁串行跑（harness 非并发安全）；变异 11 棵逐棵串行，日志 /tmp/r29/gate-m-*.log；探针全日志 /tmp/r29/py-probes.log；Worker 探针逐个在 /tmp/r29/ptree 上跑。
- 本轮未提交、未推送任何改动；报告为未跟踪文件；新探针 tests/r29_worker_toggle_bool.mjs 与 tests/r29_flask_toggle_bool.py 已落进树内 tests/（未跟踪）。

# AUDIT-R31 — 输入形状全集审计（2026-11-13）

> 方法：input-shape full set（与 R30 的 state-transition、R29 的 cross-face consistency、R28 的 zero-user journey、R27 的 adversarial operator、R26 的 repo-consumer journey、R25 的 repair-path convergence 均不同）。机械枚举每处入口的全部输入形状（类型／边界／畸形），逐项核验 verdict 对照文档契约；静默洗白（launder）即立案。
> 审计树：`~/workspace/openvpn-sk5-panel/`，git main @ b395ef3（1.0 发布提交，与公开仓库一致）＋未提交工作区改动（R26 文档修复：README.md、docs/DELIVERY.md、verify.sh 头注释；R27 修复：verify.sh cleanup API 恢复、egress/sk5_manager.py UDP 判据、cloudflare/src/index.js 队列 TTL；R28 文档修复：README Cloudflare 节、cloudflare/README.md、DELIVERY §1.3／§5；R29 修复：index.js coerceToggleBool；R30 修复：index.js 原始文本层整数 token 校验 topLevelTokens＋INT_TOKEN_RE＋readJsonRaw）。
> 历史台账：R30 终点 171 条（已修 160、部分 2（按设计）、未验 1（P0-1 Cloudflare 真实部署）、新 1（R30-P2-1，本轮已验关闭））。本轮新增见 §8。
> 夹具：/tmp/r31/ptree（本地工作树副本，含未提交修复）；fixture /tmp/r27（fixture-ca 含 ta.key、fixture-server server.conf port 1194 proto udp，属 nobody 所有——本轮起跑前复核通过，无需重建）；venv /tmp/r27/venv（Flask 3.1.3＋bcrypt）；系统 python3 无 flask（预期）。

## verdict：不能交付

差集 2 条（全 P2）：R31-P2-1 Worker 请求体信封宽容（畸形／非对象体＋非 JSON Content-Type 静默执行／入队）、R31-P2-2 改密超 bcrypt 72 字节未捕获 500。门禁 29/29，§7 变异 11/11 恰红 28/1；探针套件全量重跑无回归（红格均为已知缺陷钉死格的预期翻转）。历史台账 171→173，0 复发。Cloudflare Worker 真实部署仍 P0-1 未验。

## §0 审计基线与树状态

- 本地树：main @ b395ef3，`git status`：6 文件已修改未提交（README.md、cloudflare/README.md、cloudflare/src/index.js、docs/DELIVERY.md、egress/sk5_manager.py、verify.sh——R26 修复 3 文件＋R27 修复 3 文件＋R28 文档 3 文件＋R29/R30 index.js，两轮共改 verify.sh 与 index.js）；未跟踪：docs/audit/AUDIT-R26.md～R30.md、docs/live-verify-R18.md、docs/live-verify-R18-supplement.md、tests/r27_verify_forced_divergence.py、tests/r27_udp_probe_verdict.py、tests/r27_worker_dangling_queue.mjs、tests/r29_flask_toggle_bool.py、tests/r29_worker_toggle_bool.mjs（R27/R29 新探针）。
- 公开仓库：https://github.com/iiiiiiiii7125-art/openvpn-sk5-panel（public，2026-11-13 用户令公开）。本轮审计的是本地工作树（含未提交修复），不是仓库 HEAD——仓库 HEAD 仍为 b395ef3，未含 R26～R30 修复；发新版前须提交并推送（见 §9 收尾）。
- 探针树：/tmp/r31/ptree（本轮新建的工作树副本）；fixture／venv 复用 /tmp/r27（未被清空，属主 nobody、server.conf 已为 1194 udp——本轮起跑前复核通过，无需重建）。
- /etc/openvpn-sk5-panel/：本轮跑前复核为空（0 泄漏起点）。

## §1 R30 修复闭合核验（行为实证，不认代码在场）

### §1.1 双面 toggle 探针重跑

- `tests/r29_worker_toggle_bool.mjs` **15/15 PASS**（本轮在 /tmp/r31/ptree 上重跑；T10–T13 的 1.0／1e0 格全绿）。
- `tests/r29_flask_toggle_bool.py` **13/13 PASS**（本轮重跑，nobody 身份＋全新 data 目录＋ptree 内探针文件；T10–T12 的 1.0／1e0 格全绿）。
- **结论：R30-P2-1 已关闭**（行为＋源码双证）。

### §1.2 token 扫描器边缘格（本轮亲手写的新探针，非复用 fix lane 单测）

- 探针：/tmp/r31_edge.mjs（Worker）**22/22**、/tmp/r31_edge.py（Flask）**21/21**（F0＋E1–E20），逐格双面 raw 体对照。
- 扫描器与 JSON.parse 一致的形状（双面同 verdict）：E1 重复键 float→int（202 True，last-wins）、E2 重复键 int→float（400）、E3 键在字符串值内（202 True）、E4 键在嵌套对象内（202 True）、E5 unicode 转义键 `fail_\u006fpen`＋1.0（400）、E6 跨行 pretty 体 1.0（400）、E7/E8 保存路由 port 重复键双向（202／400）、E9 字符串值内含 `,}`（202 True）、E10 键在嵌套数组内（202 True）、E11 `-0` token（202 False）。
- **toMs／retries／created_at 未动**：客户端输入侧的整数谓词现为 `INT_TOKEN_RE` 两处（index.js:1321 保存路由 port、:1384 开关规整），`Number.isInteger` 在客户端输入校验中已无调用点（仅见于两处注释）；`toMs` :736 与 retries／created_at 的 `typeof === "number"` :760-761／:777 为内部命令记录 bookkeeping，非客户端输入校验，排除项成立。
- **结论：R30 修法的 token 校验与 Flask `type(x) is int` 在全部已测形状上同口径。**

### §1.3 边缘格揭示的新分歧——见 §8 R31-P2-1

- E12–E16（畸形／非对象请求体）与 E17–E18（create_server／create_user 畸形体）在双面探针中逐格确认分歧；E19–E20（裸动作路由）双面一致执行，为对照格。机制与闭合范围见 §8。

## §2 输入形状全集（本轮推导法核心）

机械枚举全部入口×形状矩阵的结果。形状矩阵：bool／0-1 int／float 1.0／1.5／1e0／digit string／空串／null／缺键／array／object／超大 int／负数／unicode／重复键／转义键／畸形 JSON／非 JSON Content-Type。已核闭合的面（无新发现）与新发现分列。

### §2.1 已核闭合（无新发现）

- **布尔／整数开关（双面）**：R29/R30 修法全数复核——Flask `_coerce_bool`／`_strict_bool`／`_toggle_value` 与 Worker `coerceToggleBool`＋token 校验在形状矩阵上一致（本轮 R29 探针 15/15＋13/13、R31 边缘探针 22/22＋21/21，见 §1）。`toMs`／retries／created_at 未动（内部 bookkeeping，排除成立）。
- **端口**：Flask `_valid_port`（`type() is int`）与 Worker 保存路由 token 校验一致（E7/E8 双向重复键格）；agent `_as_int` 显式拒 bool／float（R13-P2-5）；存量 `_validate_stored` 严格 int（BK 8/8 重跑见 §6）。
- **用户名／节点名**：Flask `str()`＋正则、Worker `NAME_RE`、agent `str()`＋`_NAME_RE` 三层同口径（数字 123 → "123" 合法用户，三面一致，无洗白分歧）；保留名 `server`／`OpenVPN-CA` 双面一致。
- **proto**：Flask `str().lower()`＋白名单、agent `_as_proto` 同款；非法值双面拒（Flask 400／agent 命令失败）。
- **server_ip**：Flask `str().strip()`＋`_valid_server_ip`，空串清除、非法 400。
- **params**：Flask `/api/cmd` 非 dict params → 400；Worker `handleCreateCmd` 非 string action → 400。`/api/audit` limit 非 int 静默回落 100（只读查询参数、无状态变更，见 O-R31-2，不立案）。
- **install.sh 环境变量**：OVPN_PROTO 严格 case（非法 die）、OVPN_PORT 数字＋范围检查、OVPN_SUBNET 严格 CIDR＋OVPN_DNS 字符集检查（R12-P2-6）——全部大声失败；前导零 O-R27-3 沿用（大声失败，不立案）。
- **登录密码非 string**：Flask `str()`＋bcrypt 比对失败 → 401 计限流；Worker 非 string → "" → 401。双面同 verdict。
- **裸动作路由**（start／stop／restart／test／enable／disable、DELETE revoke）：双面均不读请求体，任意体（含畸形）均执行——E19/E20 对照格双面 202。无分歧。

### §2.2 新发现——见 §8

- **R31-P2-1**：Worker 请求体信封宽容（畸形／非对象体＋非 JSON Content-Type），闭合清单 4 路由（成员 A）＋全部 JSON 读点（成员 B）。
- **R31-P2-2**：改密新密码超 bcrypt 72 字节 → 未捕获 ValueError → 500。

## §3 功能链全量对账（README / DELIVERY.md / security.md 逐项对行为）

### §3.1 机械计数复核（本轮独立重算）

- **13 动作白名单三面逐字一致**：Flask `AGENT_ACTIONS`（app.py:199-204 frozenset）、agent `ACTIONS`（agent.py:754）、Worker `ACTIONS`（index.js:64）——本轮 python 机械比对三面各 13 项排序后逐字相同 ✓。
- **verify.sh 24 项检查**：本轮独立重算 24 distinct 检查名（`ok`／`bad`／`skip` 调用点去重），与 R26/R27 的 24 一致；R30 后 verify.sh 未动 ✓。
- **R28 修复闭合**：README Cloudflare 节——未验横幅在位（:89）、填 id 步在位（:98）、“推荐”全 README 0 处、“可选”已改；cloudflare/README.md 未验行（:3）＋填 id 步（:32）✓。
- **发布包快照**：`tar tzf` 92 条目 ✓；audit 26 行含目录项＝25 份 ✓；live 17 份 ✓；包内 verify.sh sha256 `7867f557c6bb…` 与 DELIVERY §9 所记一致 ✓；tarball sha256 与 sidecar 一致（`540fc8fc…`）✓——§9 是 1.0 包的真实快照，刷新属发版步骤（O-R27-1／O-R28-1／O-R29-1／O-R30-1 延续），不当轮立案。

### §3.2 功能矩阵（功能 → 行为证据；探针编号见 §6）

| 功能（README／DELIVERY 宣称） | 行为证据 | 结论 |
|---|---|---|
| OpenVPN UDP 1194 主／TCP 443 备 | Core 46/46（§6 重跑）；install.sh 环境变量＋存量继承＋非法值早死 | ✓ 沙箱级；数据面属 live 轮 |
| 建用户／吊销／下载 .ovpn | Core 46/46；Flask 86/89（绿格内）；用户名正则＋保留名逐字一致（§2.1） | ✓ |
| SK5 启用／停用 | BM 22/22、BO 18/18、BS 9/9、BT 23/23、R24 25/25、R25 37/37（§6 重跑） | ✓ |
| 断网保护 fail-closed | BM K1–K5（真实 netns＋真实 ip） | ✓ |
| 健康检查 60 秒＋自愈 | 定时器 OnUnitActiveSec=60s；BM H1–H10；BS 9/9 | ✓ |
| 命令队列＋agent 5 秒 poll | POLL_INTERVAL=5（agent.py:70）；R17 四套件；R21 6/6；BQ 6/6 | ✓ |
| Flask＋Worker 双面 | R17 四套件；BR 11/11；R27 Worker 5/5；R29 toggle 15/15＋13/13 | △ 除 §8 R31-P2-1（请求体信封）外一致 |
| 登录限流 | Flask／Worker 双面格；BR 11/11；429＋Retry-After（app.py:1305） | ✓ |
| 密码处理 | bcrypt＋透明迁移；改密格；Worker 改密 501；默认口令 grep 零命中（§4） | △ 改密超 72 字节 500，见 R31-P2-2 |
| 重建 CA（force+confirm） | Flask F-cells；R17-P1-1 守卫 | ✓ |
| /api/sk5/test UDP 腿 | 判据 round-trip 证明（R27 已修，探针 6/6） | ✓ 已关闭 |
| verify.sh 强制路径 | API 先行恢复运行链（R27 已修，探针 8/8） | ✓ 已关闭 |

## §4 安全清单对账（docs/security.md 逐项抽查）

- **默认口令字面量零命中**：`grep -rnw "admin123\|changeme\|123456\|password123" panel/ agent/ cloudflare/src/` 零命中 ✓。
- **限流 XFF 守卫**：仅 `OVPN_TRUSTED_PROXY=1` 时才信任 X-Forwarded-For（app.py:182-183，ProxyFix），默认不信任 ✓。
- **会话**：Cookie HttpOnly（:184）＋SameSite=Lax（:185）＋Secure 条件（:189）、12 小时（:191）、改密后 session_version+1 全旧会话失效——R17 Flask 绿格内（§6 重跑）。
- **SK5 凭据**：只存 sk5.json（0600），get_status 只回 has_password、日志脱敏——R17 Flask 绿格内；P0-4 保留密码语义（§1.1 已复算）。
- **命令重投非幂等风险**：security.md 已诚实记录（O-R27-2 沿用，不立案）。
- **agent 通道**：panel_url 须 HTTPS（仅 127.0.0.1／localhost／[::1] 例外）、禁 https→http 降级重定向——R17 Agent 33/33（§6 重跑）。
- **改密长度上限缺失**：见 §8 R31-P2-2（bcrypt 72 字节）。
- **结论：除 R31-P2-2 外，security.md 抽查项与行为一致，无新缺口。**

## §5 门禁（verify-integration.sh，串行）

- **干净树**：`/tmp/r31/gate.log`，`PASS=29 FAIL=0 SKIP=0`，exit 0（本轮亲手跑于 ptree；门禁脚本用固定 `/tmp/ovpn-int-test`＋端口 8443，全程串行，无并发）。
- **§7 变异树 11/11 恰红 28/1**：`tests/build-mutants.py` 建 11 棵变异树（/tmp/r31/mutants-build.log），逐棵串行跑门禁（/tmp/r31/gate-m-*.log）：m-char、m-const-sb、m-dict-extra、m-dict-missing、m-dict-sb、m-dict-ts、m-dict-x-a、m-dict-x-amd、m-dict-x-arm、m-dict-x-b、m-install-sb——每棵均为 `PASS=28 FAIL=1`，且唯一红格为 §7 钉死格（red=1 逐棵核对）。门禁 §7 的两层（常量逐键＋字典绑定）均有效。
- `scripts/check-doc-consistency.sh` 在本树不存在——本轮未跑、未声称跑过；真实门禁即 verify-integration.sh。

## §6 探针套件重跑

Flask 探针均以 nobody 身份、每轮全新 data 目录、从 ptree 内运行（见 §1.1 约定）；r20/r25/r27-verify 以 root（unshare）运行；Worker 探针直接 node 运行；日志 /tmp/r31/p-*.log。

| 套件 | 本轮结果 | 说明 |
|---|---|---|
| R17 Flask | **86/89** | 仅 F4-02b／F4-13／F4-15 红，均为 OBSERVED 钉死格（R17-P1-1 的 Flask 面行为已被 BG 修净，探针钉的是修前行为） |
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
| R23 Flask | **13/13** 主模式＋empty_secret／db_garbage／db_empty／db_old_admin 各 1/1（empty_secret 模式两格均为大声 500／401 的预期行为） | |
| R23 Worker | **9/9** | |
| R20 | 7 格，3 红（S1/S2/S6） | 均为缺陷钉死格的预期翻转（BK／BL 修净的证明） |
| R18 队列竞态（Worker） | 9 格，2 红（RACE-02／RACE-05） | 缺陷钉死格预期翻转（BI 修净证明） |
| R18 畸形（Worker） | 13 格，9 绿 4 红 | 缺陷钉死格预期翻转（BI 修净证明；M-06 行实测记录已落 failed，探针断言的是旧行为） |
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
| R31 新探针（本轮） | edge 22/22＋21/21；ctype 7/7＋6/6；bcrypt72 6/6 | 行为证据见 §1／§8，须随修复落进 tests/ |

**结论：全部红格均为已知缺陷钉死格的预期翻转（与 R26–R30 各轮一致），无回归、无新红格。**探针运行后宿主 `/etc/openvpn-sk5-panel/` 核查为空（0 凭据泄露）。

## §7 live-18 与补记的交叉核对

（R27 §7 已逐项核对；本轮树在 R30 后只改 index.js 一文件（R30 修复）＋两 R29 探针期望，live-18 的树侧可核项结论沿用，无须重核。唯一新增：R30-P2-1 的真机格属 live-19，待 live 轮。）

## §8 差集（新发现）

### R31-P2-1（P2）——Worker 请求体信封宽容：畸形／非对象 JSON 体静默按默认执行或入队，非 JSON Content-Type 的合法 JSON 体亦照常执行；Flask 面 `_json_body` 一律 400

- **机制（双面同输入不同 verdict，机械枚举）**：Flask `_json_body()`（panel/app.py:1075-1080）验两层：`request.is_json`（Content-Type 须为 application/json）＋`get_json(silent=True)` 为 dict，否则 400“请求体须为 JSON 对象”。Worker 的 body 读取（`readJson` :123-129、`readJsonRaw` :221-239）只验解析成功与否：解析失败／JSON 标量／null → body null，调用方以 `|| {}` 兜底继续；`request.json()` 不验 Content-Type，合法 JSON 体无论何种 Content-Type 均照常解析。
  - **成员 A——畸形／非对象体（闭合清单 4 路由）**：`handleCompatSk5Toggle`（readJsonRaw，fail-open／udp-over-tcp）与 `handleCompatEnqueue`（`|| {}`，create_server／create_user）无信封守卫。行为实证（本轮双面新探针 /tmp/r31_edge.mjs 22/22、/tmp/r31_edge.py 21/21，逐格 raw 体对照）：
    | 输入 | Flask | Worker | 备注 |
    |---|---|---|---|
    | `{"fail_open": 01}`（非法 JSON） | 400 | 202，入队 `fail_open=false`（默认） |  toggle 默认方向为 fail-closed，安全侧无反向 |
    | `[1, 2]`／`"hello"`／空体／`null`（toggle） | 400 | 202，入队默认 false | 同上 |
    | `{"port": 01}`（create_server） | 400 | 202，入队空 params `{}` | agent 侧校验失败，无状态变更 |
    | `not json`（create_user） | 400 | 202，入队空 params `{}` | 同上 |
    | 对照：裸动作 stop／enable 任意体 | 202（体被忽略） | 202（体被忽略） | 双面一致，无分歧 |
  - **成员 B——非 JSON Content-Type 的合法 JSON 体（全部 JSON 读点）**：行为实证（本轮双面新探针 /tmp/r31_ctype.mjs 7/7、/tmp/r31_ctype.py 6/6）：toggle `text/plain`／无 Content-Type → Worker 202、Flask 400；login `text/plain`＋正确密码 → Worker 200、Flask 400；save `text/plain` → Worker 202、Flask 400；`application/json; charset=utf-8` 双面 202（对照格）。收紧 Worker 不会断任何树内调用方：agent poll/report 发 `Content-Type: application/json`（agent.py:284），前端 fetch 有体即设该头（index.html:566），文档 curl 示例全带该头（cloudflare/README.md:58/68/74）。
  - **范围（机械推导，闭合）**：Worker `readJson`／`readJsonRaw` 调用方全集 8 处——login（:527，R13-P2-4 已守卫，400）、register（:621，400）、report（:1014，400）、cmd（:1108，400）、init-pki（:1239，400）、save（:1307，空体经 host 检查 400，verdict 已一致）、toggle（:1394，**无守卫**）、compat-enqueue（:1223，**无守卫**）。Flask `_json_body` 调用方 10 处（login／change-password／server／init-pki／users／sk5 save／fail-open／udp-over-tcp／nodes／cmd）全部 400。排除项（已核，有理由）：change-password——Worker 未读体即 501（R11-P2-1 已裁定），Flask 400，均为大声、体无关，**不**计入成员；裸动作路由——双面均不读体，体无关。
  - **不是 R13-P2-4 的复发**：R13-P2-4 只修了 login（“畸形请求体不是一次失败登录”），且 login 本轮复核仍 400；本条是同一 `readJson null → {}` 机制在 R13 当时未覆盖的两处调用点的同族新成员（R13 轮的 Worker 侧只审了 login 的守卫，未审 toggle／enqueue 的兜底）。也不是 R29-P2-1／R30-P2-1 的复发（typeof 回落已死、token 校验已立，R29 探针 15/15＋13/13 全绿）；本条的谓词是信封层（体形状＋Content-Type），非值层。
  - **用户影响**：P2——须已登录 admin 会话；toggle 默认方向为 fail-closed（安全侧）；create_server／create_user 的空 params 入队后 agent 侧校验失败、无状态变更；Content-Type 成员读到的值本身正确，无错读、无反向、无数据损坏。害处是 verdict 分歧＋静默成功回执：被截断／错发 Content-Type 的请求在 Worker 面拿到 202“已排队”并实际执行（toggle）或入队（create_*），而在 Flask 面是 400；跨面脚本行为不一致。定 P2 不定 P1。
  - **修法**：Worker 侧收紧（绝不放宽 Flask——R13-P2-4 已裁定 Flask `_json_body` 为参照）。在 body 读取层统一守卫：Content-Type 须为 application/json（允许 `; charset=` 后缀）且解析结果须为 JSON 对象，否则 400“请求体须为 JSON 对象”（与 login 守卫同款文案），守卫须在任何默认值应用或入队之前。适用点：`handleCompatSk5Toggle` 与 `handleCompatEnqueue`（必改）；`handleCompatSk5Save` verdict 已一致，可顺带统一（不改亦可，但须在报告中说明）；其余 5 处已有守卫，不动。两 R31 边缘探针（/tmp/r31_edge.*、/tmp/r31_ctype.*）须落进 tests/ 作为回归套件（期望翻为修后行为，BH-03(c) 款式）。

### R31-P2-2（P2）——改密新密码超 bcrypt 72 字节 → 未捕获 ValueError → 500（旧密码完好）

- **机制**：bcrypt 5.x 的 `hashpw` 对超 72 字节的 UTF-8 密码抛 `ValueError: password cannot be longer than 72 bytes`（本轮 venv 实测：72 字节过、73 字节抛）。`_validate_new_password`（panel/app.py:302-310）只验 ≥12 字符、含字母数字、与旧不同，**无长度上限**；`change_password`（:1346-1385）在 `_hash_password(new)` 外无 try/except，异常未捕获 → Flask 500（空体）。边界按字节不按字符：74 字节多字节密码（1 ASCII＋24 CJK＋1 数字）亦 500，72 字节多字节密码 200。
- **行为实证**：本轮新探针 /tmp/r31_bcrypt72.py **6/6**（B1 72 字节 200 且事后可登录；B2 73 字节 500、旧密码事后仍 200；B3 74 字节多字节 500、旧密码完好；B4 72 字节多字节 200）。旧密码与会话均不受损（异常发生在 UPDATE 求值之前，无写盘、无 session.clear）。
- **范围（机械推导，闭合）**：全树 bcrypt 调用点——`_hash_password` 仅两处调用（`_ensure_admin_password` 的 token_urlsafe(16) 22 字符，永不超限；`change_password` 的用户输入，**唯一可达点**）；`_check_password` 已捕获 ValueError／TypeError → False（登录超长密码只 401，无 500）。Worker 面改密恒 501，无 bcrypt。无第三处。
- **不是既往项复发**：全树审计报告与文档中无任何“72 字节”记载（grep 零命中），本条为首次立案。
- **用户影响**：P2——大声 500，无静默损坏、无锁账（不计失败登录）；但长口令／多字节口令是合理输入（25 个 CJK 字符即超限，对中文用户尤甚），且 500 未给任何可用指引。定 P2 不定 P1。
- **修法**：`_validate_new_password` 加字节上限：新密码 UTF-8 字节数 ＞72 即 400 明示（文案须点名“72 字节”上限而非字符数，因边界按字节计）。另在 `change_password` 的 `_hash_password` 调用处加一道兜底 try/except ValueError → 400（防御纵深，防未来 bcrypt 版本行为变化）。

## §9 未验与观察

- **P0-1（未验，沿用）**：Cloudflare Worker 真实部署仍未验证（wrangler.toml KV id 仍为占位符；dry-run 通过不等于部署可用）。README 与 cloudflare/README.md 的未验横幅在位。
- **O-R31-1（改密体顺序差）**：改密畸形体——Worker 未读体即 501，Flask 400；均为大声、体无关，不立案（见 §8 R31-P2-1 排除项）。
- **O-R31-2（audit limit 回落）**：`/api/audit?limit=abc` 静默回落 100（clamp 1–500）；只读查询参数、无状态变更，不立案。
- **O-R31-3（OVPN_PORT 前导零）**：沿用 O-R27-3（`0117` 过 bash 检查、Python 渲染 117、grep 核对大声失败），不立案。
- **O-R27-1／O-R28-1／O-R29-1／O-R30-1（发版步骤清单，非立案）**：新包切出时刷新 DELIVERY §9 与 front-matter：审计报告 25→31、live 报告 17→18＋supplement、台账 163→173、终审 R25→R31、tarball 条目与 sha256 重算。另：R31 的三份新探针（/tmp/r31_edge.*、/tmp/r31_ctype.*、/tmp/r31_bcrypt72.py）须随修复落进 tests/（期望翻为修后行为，BH-03(c) 款式）。
- **live-19 待办（不属本轮）**：R27–R31 修复的真机格（verify.sh 强制路径 API 恢复、UDP 判据、Worker 队列 TTL、toggle 布尔、整数 token、请求体信封、改密 72 字节）属 live-19，不在本轮沙箱审计内断言。

## §10 审计方法与证据

- **方法**：input-shape full set。机械枚举全部入口（Flask＋Worker 全部路由、agent 13 动作、install.sh 环境变量、存量文件字段）×形状矩阵（bool／0-1 int／float 1.0／1.5／1e0／digit string／空串／null／缺键／array／object／超大 int／负数／unicode／重复键／转义键／畸形 JSON／非 JSON Content-Type），逐项双面 raw 体对照；功能链以 README／DELIVERY／security.md 为骨架；门禁与探针套件全量重跑。
- **本轮新探针（/tmp，须随修复落树）**：/tmp/r31_edge.mjs 22/22、/tmp/r31_edge.py 21/21、/tmp/r31_ctype.mjs 7/7、/tmp/r31_ctype.py 6/6、/tmp/r31_bcrypt72.py 6/6。日志：/tmp/r31/gate.log、/tmp/r31/gate-m-*.log、/tmp/r31/mutants-build.log、/tmp/r31/mutants-run.log、/tmp/r31/p-*.log、/tmp/r31/worker-probes.log。
- **台账**：R30 终点 171 条；本轮新增 2 条（R31-P2-1、R31-P2-2）→ **173 条**（已修 168＝R30 前 160＋R26～R30 的 8 条本轮复核关闭；部分 2（按设计）；未验 1（P0-1）；新 2）。0 复发。
- **历史项闭合**：R26 的 2 条、R27 的 3 条、R28 的 1 条、R29 的 1 条、R30 的 1 条——本轮均以行为证据复核关闭（§1／§3／§6），无一复发。

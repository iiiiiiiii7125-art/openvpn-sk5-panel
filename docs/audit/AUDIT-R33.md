# AUDIT-R33 — 全量全局回头看（证据优先行为再推导）

- **轮次**：AUDIT-R33（单审计员，全量全局）
- **日期**：2026-11-13
- **推导法**：证据优先行为再推导（evidence-first behavioral re-derivation）——每项 headline 行为均以新鲜探针输出或新鲜代码读数重新推导，不继承任何既往轮次结论；无计数／无日志背书的读数一律作废。
- **Verdict**：**不能交付**（差集 1 条 P2，见 §6）

## §0 审计对象树状态

- git main @ `b395ef3` "Initial commit: OpenVPN transit panel + SK5 egress (R25 deliverable, live-17 verified)"，114 跟踪文件。
- 未提交工作树改动（`git status --short` 实测 2026-11-13 11:32 CST）：
  - 修改：README.md、cloudflare/README.md、cloudflare/src/index.js、docs/DELIVERY.md、egress/sk5_manager.py、panel/app.py、verify.sh（R26–R32 修复层）。
  - 新增未跟踪：docs/audit/AUDIT-R26.md … AUDIT-R32.md、docs/live-verify-R18.md、docs/live-verify-R18-supplement.md、tests/r27_udp_probe_verdict.py、tests/r27_verify_forced_divergence.py、tests/r27_worker_dangling_queue.mjs、tests/r29_flask_toggle_bool.py、tests/r29_worker_toggle_bool.mjs、tests/r31_bcrypt72.py、tests/r31_ctype.mjs、tests/r31_ctype.py、tests/r31_edge.mjs、tests/r31_edge.py、tests/r32_enable_wait_window.py。
  - 本报告 docs/audit/AUDIT-R33.md 为本轮新增。
- R32 修复在位：`egress/sk5_manager.py:1232` `deadline = time.monotonic() + 5.0`（deadline 循环）。
- 历史台账：174 条（170 已修、2 部分（设计使然）、1 未验 P0-1 Cloudflare 真实部署、1 新自 R32 已修）；本轮结束 175 条（见 §6）。

## §1 R32 修复闭合核验（行为实证）

- R32 修复在位：`egress/sk5_manager.py:1232` deadline 循环（`deadline = time.monotonic() + 5.0`）。
- 新鲜证据（本轮亲手重跑）：
  - `tests/r32_enable_wait_window.py`：**8/8**（W1 4.7s 变活→成功且末查在 5.0s；W2 恰 5.0s 变活→成功；W3 永不活→同文案 raise；W4 0.0s 活；W5 4.5s 活对照）。末次检查落在 5.0s、5 秒硬截止不变、报错文案不变——三项均由假时钟探针输出证实，非代码目视。
  - R31 五探针：Worker edge **22/22**、Worker ctype **7/7**、Flask edge **21/21**、Flask ctype **6/6**、bcrypt72 **6/6**（Flask 三探针均以 nobody 身份、/tmp/r33/ptree 新鲜树副本、各全新 data 目录重跑）。
  - R29 Flask toggle：**13/13**；R29 Worker toggle：**15/15**；R27 悬空队列：**5/5**；BR loginfail：**11/11**；BH poll guard：**20/20**。
- 结论：**R32-P2-1 关闭；R31-P2-1、R31-P2-2 关闭。**/etc/openvpn-sk5-panel 核查为空（0 泄漏）。

## §2 证据优先行为再推导（headline 行为逐项）

每项均以本轮新鲜探针输出或新鲜代码读数重新推导，不继承既往结论；与 DELIVERY.md 宣称逐项对照。

### 2.1 SK5 链 enable/disable

- 新鲜证据：BT 探针 **23/23**（enable 等 LIVE tun1、无占位符、repair 语义、linkdown 拒认）、R25 探针 **37/37**（repair 收敛）、R32 探针 **8/8**（deadline 循环末查 5.0s）。
- 对照：DELIVERY §6-4“只等 5 秒”现为真（R32 修复后末次检查落在 5.0s，假时钟探针证实）；§4 面板流程 enable/disable 描述与探针行为一致。**闭合。**

### 2.2 fail-closed 黑洞

- 新鲜证据：BM 探针 **22/22**（真实 netns＋真实 ip：空表落回主表、黑洞使查表 EINVAL、删 tun1 路由回落黑洞、flush 恢复直连；check_health 自愈逻辑 H1–H10）。
- 对照：DELIVERY §6-3 fail-open 单向、§5 SK5 口径与行为一致。**闭合。**

### 2.3 健康检查自愈

- 新鲜证据：BS 探针 **9/9**（repair 按自身契约判定 verdict）、R25 **37/37**、BM H1–H10。
- 对照：DELIVERY §8 故障速查 policy_missing 描述与 verdict 逻辑一致。**闭合。**

### 2.4 队列＋agent poll

- 新鲜证据：R17 Flask **86/89**（仅 OBSERVED 钉死格 F4-02b／F4-13／F4-15）、R17 Agent **33/33**、BH **20/20**、BI **15/15＋18/18**、R21 **6/6**、BQ **6/6**、R27 悬空队列 **5/5**。
- 对照：docs/security.md:12 重投集分歧为已裁定（Worker 与 Flask 重投集不同，诚实记载），本轮不重立。**闭合。**

### 2.5 登录限流

- 新鲜证据：R17 Flask 登录／限流格全绿（仅 OBSERVED 格红）、BR **11/11**（loginfail 数组／缺字段／锁 15 分钟／Retry-After 900）。
- 对照：DELIVERY §1.3 与 security.md 限流描述一致。**闭合。**

### 2.6 密码处理

- 新鲜证据：bcrypt72 **6/6**（72 字节 200、73／74 字节 400 点名 72 字节、旧密码事后可登录）；R17 Flask 登录格全绿。
- 对照：DELIVERY §1.3 改密描述一致。**闭合。**

### 2.7 CA 重建

- 新鲜证据：R17 Core **46/46**（含 C2-03..C2-07 证书解析格，index.txt 真实行形）、R17 Flask init_pki 格全绿（含 force=true 守卫：:1268 `if (body.force !== true)` 新鲜读数）。
- 对照：DELIVERY §4 CA 流程一致。**闭合。**

### 2.8 UDP 1194 ＋ TCP 443

- 新鲜证据（沙箱级）：fixture-server/server.conf 经 `render_server_conf('udp', 1194)` 新鲜生成（`port 1194`／`proto udp` 实测）；install.sh 默认 UDP 1194、TCP 443 备选（代码读数）；数据面（真机 UDP 回程）属 live 轮，不在沙箱断言（沙箱 UDP sendto 一律 EPERM）。
- 对照：DELIVERY §1.2／§4 一致。**沙箱级闭合，真机格属 live-19。**

### 2.9 verify.sh forced 路径（R27-P1-1 修复）

- 新鲜证据：r27_verify_forced_divergence **8/8**（本轮重跑）；verify.sh cleanup() 新鲜全文读数：API 优先恢复（POST /api/sk5，备份 host/port、不发密码），磁盘仍为 enabled=false 时触发 set_sk5 的 disabled→enabled 翻转、走完整 enable()；文件仅在 API 成功后拷回，失败时大声 FAIL、不恢复文件、链路诚实 disabled；内联注释完整记载 D3b 顺序陷阱。
- 对照：DELIVERY §1.3 失败路径句（R28 修复）一致。**闭合。**

### 2.10 单证据行为再推导（本轮指定四项）

- **R29 toggle 强制口径**：Worker `coerceToggleBool`（:1259 起）与 Flask `_coerce_bool`（app.py:1091 起）新鲜全文对照——双面均只接受真布尔与 0/1 整数；Worker 的数值分支另要求 raw token 匹配 `INT_TOKEN_RE`（1.0／1e0 均 400，错误文案点名 token）；Flask 的数值分支用 `isinstance(value, int)`（1.0 为 float 即 400）。错误细节文案不同（Worker 点名 token、Flask 点名类型名），verdict 一致 400。R29 双面探针本轮重跑 **15/15＋13/13**（含 T10–T12 的 1.0／1e0 格）。**闭合。**
- **R30 token 扫描器**：`topLevelTokens` 新鲜全文读数——`stringEnd` 转义感知（`\\` 跳 2）；`valueEnd` 对字符串／嵌套 `{}`／`[]` 深度计数且字符串内跳过；键经 `JSON.parse` 解码（`"fail\u005fopen"` 等转义键与 JSON.parse 同解）；重复键 Map 后写覆盖（last-wins，与 JSON.parse 一致）；标量值扫至 `,` 或 `}`。边缘形状本轮新鲜重跑：Worker edge 3 格全 400（1.0／1.5／1.0，文案点名 token）、edge2（toggle 1.0 → 400、无入队）、edge3（save port 1001.0／1001.5 → 400）；Flask edge 3 格全 400；本轮新鲜重建的 save-port 探针 **3/3**（1001.0／1001.5 → 400，1001 对照 → 202）。注：R30 审计员原始探针文件在 /tmp 清理中丢失（见 §8），本轮用同输入类新鲜重建并重跑，输入类与 verdict 均与 R30/R31 记载一致。**闭合。**
- **R31 信封守卫**：8 个 JSON 读点新鲜逐点核对——login :548（`!body || Array.isArray(body)` 守卫，数组判现已冗余但无害）、register :642、report :1035、cmd :1129、init-pki :1268（均 `if (!body) return 400`）、enqueue :1244（needsBody 门）、save :1336、toggle :1429（均 null 体即 400）。路由表：`needsBody=true` 仅 create_server :1645 与 create_user :1664；裸动作（start/stop/restart/test/enable/disable/revoke）均无第 5 参数，守 `|| {}`；agent poll 的直接 `request.json()` 未碰。R31 双面探针本轮重跑 **22/22＋21/21＋7/7＋6/6**（E19/E20 裸动作一致格全绿）。**闭合。**
- **R32 deadline 循环**：见 §1。**闭合。**

### 2.11 其余 headline 行为

- **UDP 探针 verdict（R27-P2-1）**：r27_udp_probe_verdict **6/6** 本轮重跑；双层尝试（example.com/1.1.1.1 → cloudflare.com/8.8.8.8）与 round-trip 判定新鲜读数与探针一致。**闭合。**
- **Worker 队列 TTL（R27-P2-2）**：7 写点（4 queue＋3 sent）新鲜 grep 核对均带 `expirationTtl: CMD_TTL_S`；R27 悬空队列 **5/5** 本轮重跑。**闭合。**

## §3 功能链全量核对（本树文档骨架）

注：本树无 FLMX 式 doc/index.md＋doc/guide/ 13 篇；功能链骨架为 README.md、docs/DELIVERY.md、docs/security.md、panel/README.md、cloudflare/README.md、cloudflare/server-mode.md、egress/core/agent 各 README。逐项核对如下：

- **部署（服务器模式）**：DELIVERY §1（克隆公开仓库→install.sh→登录改密）与 install.sh 新鲜读数一致（默认 UDP 1194，`OVPN_PROTO=tcp OVPN_PORT=443` 备选；`FIXED_SUBNET = "10.8.0.0/24"` 三处一致：app.py:133、sk5_manager.py:61、policy-routing 注释）。**闭合。**
- **部署（Cloudflare 模式）**：README:89 与 cloudflare/README.md:3 均有未验横幅（P0-1）；KV 填 id 步骤在 README:96-98、cloudflare/README.md:30-32、DELIVERY §2.1 三处一致；wrangler.toml:32-33 仍为占位符（未验状态诚实）。README 全树 "推荐" 0 次。**闭合（未验状态诚实，未验本身不立案）。**
- **agent 安装**：DELIVERY §3 与 agent/install-agent.sh＋panel `/api/agent/bundle` 一致；13 动作白名单三面逐字一致（app.py:199、agent.py:754、index.js:64，R17 探针钉死）。**闭合。**
- **面板流程**：DELIVERY §4 与 panel/app.py 路由＋前端 index.html 一致（节点注册／轮换／吊销、OpenVPN 启停／建用户／吊销、SK5 卡片、改密）。**闭合，唯改密规则一处见 §6 R33-P2-1。**
- **SK5 口径**：DELIVERY §5 与 panel/README.md:44（`port: int(1-65535)`、fail_open／udp_over_tcp 布尔）一致；README:150 的 1001/9000 待确认标注仍在（用户未复）。**闭合。**
- **已接受限制清单**：DELIVERY §6 六行逐项复核——§6-4 五秒窗口现为真（R32 修复）；其余五项（DNS 直连、fail-open 单向、客户端列表 60 秒滞后、arm64 未真机验、首登不强制改密）与代码／状态一致。**闭合。**
- **升级与备份**：DELIVERY §7（默认重跑 install.sh 不毁 panel.db、先备份 panel/data/）与 install.sh staging 逻辑一致（R8 修复在位）。**闭合。**
- **故障速查**：DELIVERY §8 各条与 verdict／黑洞／restore 行为一致（本轮 §2 新鲜证据）。**闭合。**
- **发布包清单（§9）**：以实包核对——`releases/ovpn-release-1.0.tar.gz` 872,033 字节、sha256 `540fc8fc…` 与侧车一致、92 条目；包内审计 25 份、live-verify 17 份；9 个关键文件 sha256 前 12 位逐项核对与 §9 表一致（install.sh `3f050f037e7a`、sk5_manager.py `e209084f0915`、policy-routing.sh `fbfb29a49164`、app.py `40868bbfd8b9`、index.js `f43180976393`、agent.py `f303af828555`、openvpn_manager.py `3b5d7dfe9ea1`、verify-integration.sh `2d110ff4ffec`、verify.sh `7867f557c6bb`）；tests/ 未进包、panel/data/ 为空。**§9 作为 1.0 快照准确。**新包重打时刷新见 §7。
- **安全清单**：docs/security.md 逐项复核——默认口令已删、会话 12h、限流 5/5min/15min、改密规则（见 §6 缺 72 字节一条）、token 哈希存储、认领守卫、白名单 13、审计脱敏、安装包公开，均与代码一致。server-mode.md 对照表（含重投集分歧已裁定、Cloudflare“待真实部署验证”）一致。**闭合，唯改密规则一处见 §6。**

## §4 门禁

- 干净树（工作树现状，R26–R32 修复均在位）：`bash verify-integration.sh` **PASS=29 FAIL=0 SKIP=0**（本轮亲手串行重跑，2026-11-13 03:41 CST）。
- §7 变异：build-mutants.py 自 /tmp/r33/ptree 生成 11 棵变异树，逐棵串行跑门禁，**11/11 恰红 28/1**（m-dict-sb、m-dict-ts、m-dict-x-amd、m-dict-x-arm、m-dict-x-a、m-dict-x-b、m-dict-missing、m-dict-extra、m-const-sb、m-install-sb、m-char，均为 PASS=28 FAIL=1 SKIP=0）。红格抽查两棵（m-dict-sb、m-char）均为 §7 钉死格（“钉死哈希不一致：install.sh 与 agent/agent.py 的 sha256 逐键不等”）；其余 9 棵同为 28/1，且每棵变异只改一处哈希值、门禁中唯一比对 install.sh 与 agent.py 哈希的格即 §7，故红格归属闭合。
- `scripts/check-doc-consistency.sh` 本树不存在，未虚构运行记录。

## §5 探针套件全量重跑

本轮全部亲手重跑（新鲜树副本 /tmp/r33/ptree；Flask 探针 nobody 身份、各全新 data 目录；root/unshare 探针 root 身份；Worker 探针 mock KV）：

| 套件 | 本轮 | 预期 | 判定 |
|---|---|---|---|
| R32 enable wait window | 8/8 | 8/8 | ✓ |
| R31 edge Worker / Flask | 22/22 / 21/21 | 22/22 / 21/21 | ✓ |
| R31 ctype Worker / Flask | 7/7 / 6/6 | 7/7 / 6/6 | ✓ |
| R31 bcrypt72 | 6/6 | 6/6 | ✓ |
| R17 Flask | 86/89（F4-02b／F4-13／F4-15 三红） | 86/89 | ✓ 仅已知 OBSERVED 钉死格 |
| R17 Core | 46/46 | 46/46 | ✓ |
| R17 Agent | 33/33 | 33/33 | ✓ |
| R17 Worker | 33/35（W5-05／W5-06a 两红） | 33/35 | ✓ 仅已知 OBSERVED 钉死格 |
| BK stored shapes | 8/8 | 8/8 | ✓ |
| BM blackhole self-heal | 22/22 | 22/22 | ✓ |
| BO tun1 repair | 18/18 | 18/18 | ✓ |
| BP boot restore | 14/14 | 14/14 | ✓ |
| BQ queue unreadable | 6/6 | 6/6 | ✓ |
| BR loginfail array | 11/11 | 11/11 | ✓ |
| BS verdict | 9/9 | 9/9 | ✓ |
| BT enable no placeholder | 23/23 | 23/23 | ✓ |
| R24 enable placeholder | 25/25 | 25/25 | ✓ |
| R25 repair convergence | 37/37 | 37/37 | ✓ |
| R21 queue quarantine | 6/6 | 6/6 | ✓ |
| R22 time bounds Flask / Worker | 22/22 / 12/12 | 22/22 / 12/12 | ✓ |
| R23 persist Flask / Worker | 13/13 / 9/9 | 13/13 / 9/9 | ✓ |
| R27 verify forced divergence | 8/8 | 8/8 | ✓ |
| R27 UDP probe verdict | 6/6 | 6/6 | ✓ |
| R27 Worker dangling queue | 5/5 | 5/5 | ✓ |
| R29 toggle Worker / Flask | 15/15 / 13/13 | 15/15 / 13/13 | ✓ |
| R20 input shapes | 7 格 3 红（S1／S2／S6） | 7 格 3 红 | ✓ 缺陷钉死格预期翻转 |
| R18 Worker race | 9 格 2 红（RACE-02／RACE-05） | 9 格 2 红 | ✓ 缺陷钉死格预期翻转（BI 修净证明；R32 §5 同数） |
| R18 Worker malformed | 13 格 9 绿 4 红（M-01／M-02／M-03／M-06） | 同数 | ✓ 缺陷钉死格预期翻转（M-06 行实测记录已落 failed，探针断言的是旧行为；R32 §5 同数） |
| BI queue race / malformed | 15/15 / 18/18 | 15/15 / 18/18 | ✓ |
| BH poll guard | 20/20 | 20/20 | ✓ |
| R19 nonlist container / ovpn download | 12/12 / 8/8 | 12/12 / 8/8 | ✓ |

**无回归、无新红格。**/etc/openvpn-sk5-panel 全程核查为空。

## §6 差集

**Verdict：不能交付。差集 1 条（P2），0 复发。历史台账 174→175（171 已修、2 部分、1 未验 P0-1、新 1）。**

### R33-P2-1（P2）——改密 72 字节上限只落在服务端代码，全部面向用户的规则枚举与前端校验均未同步

- **机制**：R31-P2-2 修复在 `_validate_new_password`（panel/app.py:302-310，现 :312 起 docstring 已同步“UTF-8 不超过 72 字节”）加了字节上限（UTF-8 ＞72 即 400，文案点名“72 字节上限”），`change_password` 另有 try/except 兜底。但 R31 修复只动了服务端代码与代码 docstring，**六处面向用户的规则枚举全部仍是旧的三条规则**（≥12 字符、含字母和数字、与旧不同），且前端校验本身也无字节检查：
  1. `docs/security.md:11` 改密行：“新密码 ≥12 字符且同时含字母和数字、与旧密码不同”；
  2. `panel/templates/index.html:309` 改密帮助文案：“新密码至少 12 个字符，含字母和数字，且与旧密码不同”；
  3. `panel/templates/index.html:1025` 前端校验注释：“强度校验（≥12 字符、含字母和数字、与旧密码不同、两次一致）”；
  4. `panel/templates/index.html:1039-1041` 前端校验本身：只验 `length < 12`（字符数）、`[A-Za-z]`／`[0-9]`、与旧不同；输入框无 `maxlength`；
  5. `panel/README.md:31` API 表与 `:102` 前端描述：“新密码 ≥12 字符、含字母和数字、与旧密码不同”；
  6. `README.md:273`：“新密码 ≥12 位且含字母＋数字”。
  （全树机械 grep 闭合：`至少 12|≥12|>=12` 在非审计／非探针文件中的命中共 8 行，其中 app.py:312 为已同步的服务端 docstring，其余 7 行即以上六处用户侧位置，DELIVERY.md §1.3 未枚举规则、无不符。）
- **行为实证**：密码 `a`＋24 个 CJK＋`1`（26 字符、74 字节 UTF-8）——前端四项校验全过（字符数 26≥12、含 ASCII 字母、含数字、与旧不同），帮助文案与全部文档均称其合法；服务端 `tests/r31_bcrypt72.py` B3 格（本轮重跑 **6/6**）回 400“新密码超过 72 字节上限（按 UTF-8 字节计，bcrypt 限制）”。即：UI 与文档承诺合法的输入，提交后被服务端以一条 UI 从未提及的规则拒绝。对中文用户尤甚（25 个 CJK 字符即超限，R31 已指出）。
- **不是既往项复发**：R31-P2-2 立的是服务端未捕获 500（已修净）；本条是同轮修复漏同步文档／UI 的遗留——修 A 漏 B 的同族（R26-P2-2、R28-P2-1 同为文档族 P2），机制不同（服务端行为已正确，缺的是规则的面向用户同步），不计复发。
- **定 P2 不定 P1**：无静默损坏、无数据丢失、无锁账；400 本身大声且文案点名了 72 字节上限，用户换短口令即可重试。伤害限于一次白跑提交＋规则不透明。
- **修法**：六处用户侧枚举同步加“UTF-8 不超过 72 字节”；前端 `onsubmit` 校验加字节检查（`new TextEncoder().encode(newPw).length > 72` 即拦，文案与服务端同款点名 72 字节），使超长口令在提交前就被 UI 拦下；探针：bcrypt72 套件加一格覆盖“前端校验口径与服务端一致”（或在现有探针中加文档 grep 格，钉死六处均含 72 字节字样）。

## §7 未验与观察

- **P0-1（未验，长期）**：Cloudflare 真实 Worker 部署从未验证（wrangler.toml KV id 仍为占位符，需用户建 Cloudflare API token 或交互 `wrangler login`；已问十一次未复）。本轮三处文档均诚实标注未验，未立新项。
- **观察 O-R33-1**：R31 修复的 save 路由空体文案由“host 不能为空”统一为“请求体须为 JSON 对象”（verdict 同为 400），全树用户文档无一处引用旧文案，不立案。
- **观察 O-R33-2**：R18 两探针（race 9 格 2 红、malformed 13 格 4 红）断言的是缺陷行为，修复后行为由 BI 套件（15/15＋18/18）验证；红格数与 R30/R31/R32 三轮完全一致，不立案。
- **观察 O-R33-3**：R20 探针 7 格 3 红（S1／S2／S6）为缺陷钉死格预期翻转，与既往轮次一致，不立案。
- **发版前刷新清单（非 finding， release-step）**：DELIVERY §9 与卷首台账须按实测刷新——审计 25→**33** 篇（R26–R33）、live 17→**18 份＋补记**、台账 163→**175**（174＋R33 新 1）、终审 AUDIT-R25→**AUDIT-R33**、门禁计数仍 29 格（本轮重跑 29/29）；§9 的 9 个关键文件哈希须按新包实测重填。

## §8 审计过程事故

1. **/tmp 全清（03:38 CST 左右，本轮中段）**：审计中途 /tmp 被清空（使用率 0%，仅剩本轮刚建的 /tmp/r33/r30h）——/tmp/r27 venv＋fixture、/tmp/r33/ptree、全部已跑探针的 data 目录、R30 审计员原始探针（/tmp/r30_edge*）一并丢失。已处置：venv 重建（Flask 3.1.3＋bcrypt 5.0.0）、fixture 按 `tests/rebuild-r17-fixture.sh` 重建（index.txt 六行与配方一致：alice V、dave V、bob R、server V、carol E、erin V-过期）、ptree 重新复制、stub sing-box 重建；R30 save-port Flask 探针按同输入类新鲜重写（/tmp/r33/r30_save_port_float.py，**3/3**）。**已完成的探针读数不受影响**（输出已落盘进本报告 §1/§5；门禁 29/29 在清理前已跑完）。非产品问题。教训重申：/tmp 资产随时会丢，探针与夹具的版本化配方（tests/ 内）是唯一可靠恢复路径。
2. **venv 权限（umask 027）**：重建的 venv 目录为 770，nobody 跑 Flask 探针报 `No module named 'flask'`；`chmod -R a+rX` 后通过。另：一次 Flask 探针因复用已用 data 目录报 `no admin pw`（`_ensure_admin_password` 已有 admin 行即返 None），换全新 data 目录后通过——与既往轮次同款教训。
3. **/tmp/r33 权限漂移**：清理后 /tmp/r33 一度呈 770，致 nobody 探针 EACCES；已 chmod 755 修复。以上三起均为审计环境事故，非产品问题。

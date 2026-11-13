# AUDIT-R36 — 全量全局回头看（full-ledger re-execution）

- **轮次**：R36（R35 三 P2 宣称已修后，1.0.2 发版前回头看）
- **日期**：2026-11-13
- **方法**：full-ledger re-execution——把 178 条台账从头重推导：逐套重跑 tests/ 全部历史探针（R17 四套件、BK、BM、BO、BP、BQ、BR、BS、BT、R24、R25、R27、R29、R31、R32、R35 域名＋失败路径＋ProxyFix，另加 R18/R19/R20/R22/R23 套件），逐条核对已关闭项仍关闭；任何回归即新发现，探针输出为复现。同轮全树重扫两大复发族（pipefail-SIGPIPE 族；route-get-from-client-address 族），并重验门禁（verify-integration.sh 29/29；§7 变异 11/11 恰红 28/1）。
- **Verdict**：**可交付（差集 ∅）**——178 条台账全量重跑无一回归，R35 三修复全部成立，门禁 29/29、§7 变异 11/11 恰红。本轮可放行 1.0.2（发版时刷新 DELIVERY §9 与卷首快照，见 §6）。

## §0 审计基线（被审树状态）

- git main @ cc56952，加未提交工作树改动：install.sh（域名反代功能＋R35-P2-1 修复）、README.md＋docs/DELIVERY.md＋docs/security.md（R35-P2-2／P2-3 修复）、docs/audit/AUDIT-R35.md、tests/r35_domain_reverse_proxy.sh、tests/r35_domain_failpath.sh、tests/r35_proxyfix_xff.py。
- 台账基线：178 条（171 已修、2 部分按设计、1 未验 P0-1 Cloudflare 真实部署、R35 新 3 宣称已修）。
- 注：本仓库无 docs/index.md 与 docs/guide/ 13 篇（那是 FLMX 项目的骨架）；本项目的功能链骨架是 README.md＋docs/DELIVERY.md＋docs/security.md（＋cloudflare/server-mode.md），与 R34/R35 一致。
- 探针环境：新鲜树副本 /tmp/r36/ptree（工作树逐字节一致；install.sh sha 前 12 位 `77217e16e77c`）；/tmp/r33v/venv（Flask 3.1.3＋bcrypt）＋/tmp/r33f＋/tmp/fixture-server（R33 控制器重建物，属 nobody，server.conf 为 port 1194 udp）沿用；Flask 探针各用新鲜 data/sk5cfg 目录＋nobody 身份；/etc/openvpn-sk5-panel 全程为空（开工、r35 两探针后、终核三查皆空）。

## §1 方法与执行顺序

Full-ledger re-execution：逐套重跑 tests/ 全部历史探针（R17 四套件、BK、BM、BO、BP、BQ、BR、BS、BT、R24、R25、R27、R29、R31、R32、R35 域名＋失败路径＋ProxyFix，另加 R18/R19/R20/R22/R23 套件），逐条核对已关闭项仍关闭；任何回归即新发现，探针输出为复现。同轮全树重扫两大复发族，并重验门禁（verify-integration.sh 29/29；§7 变异 11/11 恰红 28/1）。

执行记录（/tmp/r36/log/）：
- 第一轮批量脚本两处审计员失误：`/tmp/r36` 目录权限 770 挡住 nobody（全部 Flask 探针 Errno 13）；shell_probe 双写 `tests/` 前缀（两 r35 shell 探针 rc=127）。失误只影响第一轮 Flask/shell 探针；root 与 Worker 探针结果有效。已修脚本重跑（run_fix.sh），本报告全部结果为重跑值。
- **R18 两套 Worker 探针的红格已定性（见 §5）**：`r18_worker_queue_race.mjs` 7/9、`r18_worker_malformed.mjs` 9/13——红格全部是 R18 审计员写的缺陷复现钉死格（与 r17_worker 的 W5-05/W5-06a、r17_flask 的 F4-02b/F4-13/F4-15 同款“OBSERVED 缺陷钉”：在已修树上按设计变红）。行为实证：B 恰好下发一次、status=sent；sweep 对四种畸形态逐一落 failed（M-03 专项复核：status=failed、retries=0）。R18-P2-1／R18-P2-2 仍关闭，不立案，不翻探针（与 W5/F4 的既定惯例一致；R18 报告“须翻转”是修法方向，BI 未翻，R34 FMEA 已按代码面确认关闭）。

## §2 差集（新发现）

**差集 ∅。** 全量重跑未发现任何产品回归；R35 的 3 条宣称修复全部成立（§5 的 r35 三套探针＋代码复核）。唯一动手的是探针夹具缺口（§5 末，tests/r35_proxyfix_xff.py 的 R35_*→OVPN_* 桥接），产品代码零改动。

## §3 功能面核查（README／DELIVERY／security.md 骨架复核）

R35 修复复核（任务简报指定项，逐项实证）：
- **R35-P2-1（失败路径丢信任变量）已修成立**：`_restore_prev_panel_domain`（install.sh:749-758）＋5 处调用点（:836 Caddy 安装失败、:847 Caddyfile 构建失败、:852 validate 失败、:859 写 Caddyfile 失败、:911 启动后不在运行）已亲手读过全文；`tests/r35_domain_failpath.sh` **8/8**（修复后行为：panel.env 保留三变量、live Caddyfile 字节一致、warn 文案不再称“leaving Caddy stopped”，改称“Caddy keeps running the old config; panel.env keeps the previous domain vars”）。R35-P2-1 关闭。
- **R35-P2-2（去反代漏两变量）已修成立**：README 域名反代段与 DELIVERY:54 现均列 `OVPN_PANEL_DOMAIN`、`OVPN_PANEL_HTTPS`、`OVPN_TRUSTED_PROXY` 三行一并删，README 另写明“只删域名行、留下 `OVPN_TRUSTED_PROXY=1` 时面板仍信任伪造 XFF”。两边逐字对齐。R35-P2-2 关闭。
- **R35-P2-3（卸载漏 Caddy）已修成立**：README“卸载（手动）”已有 `systemctl disable --now caddy`、删 Caddyfile 托管段（或整文件删）、`ufw delete allow 80/tcp` 与 `443/tcp`，并注明 panel.env 三行随 `rm -rf /etc/openvpn-sk5-panel` 一并删除、无需单独清理。R35-P2-3 关闭。
- **域名反代 happy path**：`tests/r35_domain_reverse_proxy.sh` **30/30**（校验 17、panel.env 3、Caddyfile 4、交互 4、辅助 2）。

骨架其余宣称（R34/R35 已验、本轮无代码改动面，靠门禁＋套件重跑复核，无回归）：
- UDP 1194 主／TCP 443 备、子网 10.8.0.0/24、策略路由只按源地址匹配、DNS 默认直连、13 命令白名单两端一致、fail-closed 黑洞＋fail-open 单向、登录限流 5/5 分钟锁 15 分钟、改密五规则（含 UTF-8 ≤72 字节）、CA 重建 force＋confirm、凭据红线（sk5.json 0600、回执无明文密码——门禁格通过）、verify.sh 24 项、二进制钉死（门禁 §7＋11 变异见 §5）——全部随套件重跑通过，无新红格（除各探针既定的 OBSERVED 缺陷钉，见 §5）。

## §4 两大复发族重扫

- **pipefail-SIGPIPE 族**：全树 7 个 shell 脚本均有 `set -euo pipefail` 或 `set -uo pipefail`（install.sh:24、verify.sh:58、verify-integration.sh:11、egress/policy-routing.sh:113、egress/test-egress.sh:36、agent/install-agent.sh:56、core/easyrsa.sh:18）。全树 `| head -1`／`| tail` 逐项核对：install.sh:356/385/395/418/427 均带 `|| true`；`head -c` 均读文件非管道；verify-integration.sh:602/603/616/617 的 `grep | head -1` 在无 `-e` 的脚本内，最坏空值只会让 §7 格大声红（fail-closed）；test-egress.sh:84/165 同理无 `-e` 且 :165 带 `|| echo`。R35 新增管道：`grep | cut | tr`（install.sh:636，`|| true`）、`getent | awk … exit`（:711，调用点 :787 有 `|| true`、值先打印）、`curl | gpg`／`curl | tee`（:807-815，全量消费）——无新成员。
- **route-get-from-client-address 族**：全树 `ip route get` 逐项核对——VPN 查询一律 `from 10.8.0.1`（egress/test-egress.sh:61、egress/policy-routing.sh:538、install.sh:1288、verify.sh:711/874）；裸 `ip route get 1.1.1.1` 只作主表直连对照（test-egress.sh:74、policy-routing.sh:540、verify.sh:712）或取本机出口源地址（install.sh:122，带 `|| hostname -I` 回落）。R35/R36 未新增任何 route-get。无复发。

## §5 门禁与探针

本轮亲手重跑（新鲜树副本 /tmp/r36/ptree＝工作树逐字节一致，install.sh sha 前 12 位 `77217e16e77c`；Flask 探针各用新鲜 data 目录＋nobody 身份；root 探针注明；日志 /tmp/r36/log/）：

| 套件 | 结果 | 备注 |
|---|---|---|
| 干净树门禁 verify-integration.sh | **29/29**（PASS=29 FAIL=0 SKIP=0） | 串行，含未提交 R35 改动 |
| §7 变异 11 棵 | **11/11 恰红 28/1**，红格逐棵均为 §7 钉死格 | m-dict-sb/ts/x-amd/x-arm/x-a/x-b/missing/extra、m-const-sb、m-install-sb、m-char |
| r35 域名反代 | **30/30** | 校验 17、panel.env 3、Caddyfile 4、交互 4、辅助 2 |
| r35 失败路径 | **8/8** | 修复后行为：三变量保留、live Caddyfile 字节一致、warn 文案已改 |
| r35 ProxyFix/XFF 默认 | **4/4** | T0-01～T0-04 |
| r35 ProxyFix/XFF 信任 | **8/8** | 桥接修后（见末）；T1-01～T1-08 |
| R17 Flask | **86/89** | 仅 OBSERVED 钉死格 F4-02b/F4-13/F4-15 红（既定） |
| R17 Core | **46/46** | |
| R17 Agent | **33/33** | |
| R17 Worker | **33/35** | 仅 OBSERVED 钉死格 W5-05/W5-06a 红（既定） |
| BK 存储形态 | **8/8** | R20-P2-1 仍关闭 |
| BS verdict | **9/9** | R15-BUG-1 仍关闭 |
| BM 黑洞自愈 | **22/22** | root＋真实 netns；R13-BUG-1 仍关闭 |
| BO tun1 修复 | **18/18** | root＋真实 netns；R14-BUG-1 仍关闭 |
| BP 启动恢复 | **14/14** | R23-P2-1/P2-2 仍关闭 |
| BQ 队列不可读 | **6/6** | R23-P2-3 仍关闭 |
| BR 登录失败数组 | **11/11** | R23-P2-4 仍关闭 |
| BT 无占位符 | ALL PASS | R24-P2-1 仍关闭 |
| R24 占位符 | ALL PASS | |
| R25 收敛 | ALL PASS | |
| R27 UDP verdict | **6/6** | R27-P2-1 仍关闭 |
| R27 强制分歧 | **8/8** | root 重跑（nobody 跑会撞 unshare uid_map，见末）；R27-P1-1 仍关闭 |
| R27 悬挂队列 | **5/5** | R27-P2-2 仍关闭 |
| R29 Flask 切换 | **13/13** | R29-P2-1 仍关闭 |
| R29 Worker 切换 | **15/15** | |
| R31 edge Flask/Worker | **21/21 / 22/22** | R31-P2-1 仍关闭 |
| R31 ctype Flask/Worker | **6/6 / 7/7** | |
| R31 bcrypt72 | **10/10** | R31-P2-2 仍关闭 |
| R32 等待窗口 | **8/8** | R32-P2-1 仍关闭 |
| R21 队列隔离 | **6/6** | R21-P2-1 仍关闭 |
| R22 时间边界 Flask/Worker | **22/22 / 12/12** | |
| R23 持久形态 Flask/Worker | **13/13 / 9/9** | |
| R18 BG（Flask poll 守卫） | **22/22** | R17-P1-1 Flask 面仍关闭 |
| R19 非列表容器／下载 | **12/12 / 8/8** | R19-P2-1/P2-2 仍关闭 |
| R20 回退构建 | built m-kvarray、m-dlguard | 仅构建变异树（见 R20 原轮） |
| R21 回退构建 | built m-validate、m-heartbeat、m-blackhole、m-repair | 仅构建变异树（见 R21 原轮） |

**缺陷钉死格红格（非回归，逐项已定性，行为实证缺陷不在）**：
- `r18_worker_queue_race.mjs` **7/9**：红 RACE-02、RACE-05。RACE-02 的 dispatched=[A, B]——B 在 poll 窗口内入队后被 sweep 孤儿回收抢在下发读之前补回，同轮即下发；RACE-04（后 3 轮不再见到 B）＋RACE-05（status=sent）＋RACE-06（队列不再引用 B）合证 B 恰好下发一次、未丢失、未重发。RACE-02“只下发 A”是钉死格对下发时序的过度断言，已修行为合法地违反它。R18-P2-1 仍关闭（代码锚：`_sweepWorkerCmds` cloudflare/src/index.js:835，孤儿回收 :879，poll 调用点 :946）。
- `r18_worker_malformed.mjs` **9/13**：红 M-01b、M-02c、M-03a、M-06b，四格全是“仍未标 failed／仍滞留”的缺陷断言；日志三行 `sweep: malformed cmd … -> failed`（缺 status／未知 status／非对象）＋M-03 专项复核（`/tmp/r36/m03_check.mjs`：非数值 sent_at 记录 poll 后 status=failed、retries=0）证实 sweep 已落 failed。R18-P2-2 仍关闭。两探针的缺陷钉未翻（与 W5-05/W5-06a、F4-02b/F4-13/F4-15 的既定惯例一致；R18 报告“须翻转”是修法方向，BI 未翻，R34 FMEA 已按代码面确认关闭）。
- `r20_input_shapes.py` **4/7**（root 重跑）：红 S1、S2、S6，三格全是缺陷断言——S1 port=true／S2 port=1194.5 实际均为诚实 ValueError（`_validate_stored`），S6 列表形 sk5.json 实际 heartbeat 正常返回（HB-OK），无 AttributeError。R20-P2-1／BL 仍关闭；BK 探针 8/8 直接钉住修复后行为。

**本轮探针夹具修补（已落树，未提交；产品代码零改动）**：
- `tests/r35_proxyfix_xff.py` 桥接缺口：探针卷首只写 `R35_TRUSTED_PROXY=1 R35_PANEL_HTTPS=1`，但探针只拿这两个变量选分支，从不把它们交给 app——app.py:182/190 在 import 时读的是 `os.environ` 的 `OVPN_TRUSTED_PROXY`／`OVPN_PANEL_HTTPS`（生产由 systemd `EnvironmentFile=panel.env` 供给，探针无此文件）。按卷首字面跑信任模式得 4/8（T1-03/05/06/08 红：ProxyFix 未开、Secure 未开——夹具假红，非产品问题；R35 的 8/8 须是另行 export 了 OVPN_* 变量才拿到，卷首未写）。修法：import app 之前把 R35_* 桥接进 `os.environ` 的 OVPN_*（3 行＋注释，tests/r35_proxyfix_xff.py:36-43）。重跑：默认 4/4、信任 **8/8**，卷首调用如今自洽。

**审计员执行事故（已纠正，见 §1）**：第一轮批量脚本两处失误（/tmp/r36 权限 770 挡 nobody；shell_probe 双写 `tests/` 前缀）致全部 Flask 探针 Errno 13、两 r35 shell 探针 rc=127——失误只污染第一轮，root 与 Worker 探针结果有效；已修脚本重跑，全部结果为重跑值。r27_forced 与 r20 S6 必须 root 跑（unshare uid_map，nobody 下 `Operation not permitted`）；r20/r21 回退探针硬编码 /tmp/r20、/tmp/r21，须预先建好且 nobody 可写（/tmp 本身 755，nobody 建不了顶层目录——已预建并 chown）。/tmp 为 512M tmpfs，回退构建中途写满（100%）——删已完成轮次的可复现旧目录（/tmp/r33、/tmp/r34、/tmp/r35、/tmp/r35m、/tmp/r33h，约 300M）后重建通过；终态 217M 空闲。

## §6 观察（不立案）与未验

- **O-R35-1／O-R35-2（旧观察，仍在）**：横幅括号半角／全角混用；直连口伪造 XFF 可轮换绕过锁定（security.md 已披露机制与缓解）。本轮无新证据，不重立。
- **O-R34-1～O-R34-5（旧观察，仍在）**：daemon 死亡无看守；吊销后 restart 失败角；agent 无 executed-id 去重；重投集不对称；时钟跳变未定性。本轮无新证据，不重立。
- **O-R36-1（观察）**：r18 两探针与 r20 S1/S2/S6 的缺陷钉死格仍按 R18/R20 原样钉缺陷行为，与 W5/F4 同款“已修树上按设计变红”。惯例一致，不翻；但后轮重跑须认得这 9 格红是既定钉（本报告 §5 已逐格定性），不得误判为回归。
- **未验**：P0-1 Cloudflare 真实部署（无进展）；真域名＋真 Let's Encrypt 证书的 live 实证（属 live-20）；Caddy apt 安装与 HTTP-01 办证真机路径（属 live-20）；arm64 真机；IPRoyal 1001 vs 9000（用户未复）。
- **发版时刷新（非差集）**：DELIVERY §9 与卷首仍是 1.0.1 快照（审计 34 篇、live 20 份、台账 175、终审 R34、9 个关键文件哈希为 1.0.1 树版本）；1.0.2 发版时须按 R34 §6 同款口径刷新（审计 34→36 篇、台账 175→178、终审 R34→R36、重测 §9 清单与哈希），与 O-R28-1 旧项一致。

---

**台账**：178→**178**（171 已修、2 部分按设计、1 未验 P0-1、新 0、复发 0）。

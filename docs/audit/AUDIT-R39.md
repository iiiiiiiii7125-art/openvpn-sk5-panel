# AUDIT-R39 — 全量全局回头看（mode-and-ownership census）

- **轮次**：R39（R38 一修复宣称已修后，1.0.2 发版前回头看）
- **日期**：2026-11-13
- **方法**：mode-and-ownership census——机械枚举安装器、agent、面板、健康检查、Caddy 创建或写入的每一条路径（文件与目录，覆盖 install.sh、agent/install-agent.sh、panel/app.py、egress/*、core/*、verify*.sh 与 systemd 单元），逐项记录模式与属主，对照文档化信任模型核对（root-only 秘密 0600/0700、caddy 可读 0644/0755、nobody 可写状态）。R37-P2-2 与 R38-P2-1 都是逐个发现的未钉模式；本方法以枚举代替举例，证明树内不再有未钉模式。同轮全树重扫两大复发族（pipefail-SIGPIPE 族；route-get-from-client-address 族），并重验门禁（verify-integration.sh 29/29；§7 变异 11/11 恰红 28/1）。
- **Verdict**：**可交付（差集 ∅，0 条新发现）**——模式与属主清查 27 项逐项成立：R38-P2-1 两处 chmod 755 均为真实代码行且粘住的 0700 目录自愈已独立复现；全树再无未钉模式可读出秘密（目录未钉的三处均由逐个 0600 的文件兜底，见 §1 注）；R37/R20/R35 修复全部仍关闭；门禁与 §7 变异见 §5。

## §0 审计基线（被审树状态）

- git main @ cc56952，加未提交工作树改动：install.sh（域名反代功能＋R35-P2-1 修复＋R20 三 bug 修复＋R37-P2-1/P2-2 修复＋R38-P2-1 修复）、README.md＋docs/DELIVERY.md＋docs/security.md（R35-P2-2／P2-3＋R20-BUG-3 文档＋R37-P2-3）、docs/audit/AUDIT-R35.md、AUDIT-R36.md、AUDIT-R37.md、AUDIT-R38.md、docs/live-verify-R20.md、tests/r35_domain_reverse_proxy.sh（46 格）、tests/r35_domain_failpath.sh、tests/r35_proxyfix_xff.py、tests/r37_bug3_guard_prev_domain.sh、tests/r37_caddyfile_mode_umask.sh、tests/r38_runbook.sh（30 格）。
- 台账基线：185 条（184＋R38 新 1，R38-P2-1 宣称已修）。
- 注：本仓库无 docs/index.md 与 docs/guide/ 13 篇（那是 FLMX 项目的骨架）；本项目的功能链骨架是 README.md＋docs/DELIVERY.md＋docs/security.md（＋cloudflare/server-mode.md），与 R34/R35/R36/R37/R38 一致。
- 探针环境：新鲜树副本 /tmp/r39/ptree（工作树逐字节一致，install.sh sha256 `5a347d3717b2…`）；/tmp/r33v/venv（Flask 3.1.3＋bcrypt）＋/tmp/r33f＋/tmp/fixture-server 沿用；Flask 探针各用新鲜 data 目录＋nobody 身份；/etc/openvpn-sk5-panel 全程为空（终核已确认）；/etc/caddy 每次探针后均由 trap 删除、终核不存在。

## §1 方法与模式/属主清查表

清查方法：grep 全树 `mkdir`／`chmod`／`install -m`／`install -d`／`chown`／`os.makedirs`／`os.open(..., 0o...)`／`write_bytes`／`write_text`／`open(..., "w")`，逐项追到最终落盘模式；凡含秘密内容的写点再核一次“最终模式＋父目录模式＋读它的 principal”。信任模型（security.md 宣称＋代码既定）：秘密文件 0600、秘密目录 0700、公开证书/配置 0644、caddy 可读路径 0644/0755、面板/agent/sing-box/healthcheck 均以 root 运行、openvpn 读钥后降 nobody、caddy 以 User=caddy 运行。

| # | 路径（创建者） | 最终模式 | 读它的 principal | 裁定 |
|---|---|---|---|---|
| 1 | `/etc/openvpn-sk5-panel/` CONFIG_DIR（install.sh:438-439） | 0700（显式 chmod） | root（面板/agent/sing-box） | 成立 |
| 2 | `/etc/openvpn-sk5-panel/secret.key`（install.sh:530-531；app.py:161-175，每次加载再收紧） | 0600 | root | 成立 |
| 3 | `/etc/openvpn-sk5-panel/admin.pass`（app.py:338-346，0600；改密 :1393-1395 同款） | 0600 | root | 成立 |
| 4 | `/etc/openvpn-sk5-panel/panel-key.pem`（install.sh:556，openssl 生成后 chmod 600） | 0600 | root | 成立 |
| 5 | `/etc/openvpn-sk5-panel/panel-cert.pem`（install.sh:556） | 0644，困在 0700 目录内 | 仅 root 能读本体；caddy 只读副本（R20-BUG-2 不变量） | 成立 |
| 6 | `/etc/openvpn-sk5-panel/panel.env`（install.sh:659） | 0600 | root（systemd EnvironmentFile） | 成立 |
| 7 | `/etc/openvpn-sk5-panel/sk5.json`（sk5_manager `_atomic_write_json`：tmp 写→0600→replace→0600） | 0600 | root | 成立 |
| 8 | `/etc/openvpn-sk5-panel/sing-box.json`（install.sh:1050 chmod 600；sk5_manager :696 `os.open(..., 0o600)`） | 0600 | root（sing-box User=root） | 成立 |
| 9 | `/etc/openvpn-sk5-panel/sing-box.log`（sk5_manager:391 `open("ab")`，无显式 chmod） | 0644（umask 默认），父目录 0700 | root；内容仅 sing-box stderr（无凭据回显，见 §1 注） | 成立（父目录兜底） |
| 10 | `/etc/openvpn-sk5-panel/health.json`（sk5_manager:1325 `_atomic_write_json`） | 0600 | root | 成立 |
| 11 | `/etc/caddy/`（install.sh:894/902 best-effort chmod 755；:928/933 bare chmod 755） | 0755（R38-P2-1 已钉） | caddy 遍历＋读 | 成立（§3 复核） |
| 12 | `/etc/caddy/panel-cert.pem`（install.sh:904 `install -m 0644`，每轮重拷） | 0644 | caddy | 成立 |
| 13 | `/etc/caddy/Caddyfile`（install.sh:946 `chmod 644`，R37-P2-2） | 0644 | caddy | 成立 |
| 14 | `/opt/openvpn-sk5-panel/` INSTALL_ROOT（install.sh:438，无 chmod） | 0755（umask 默认） | root；内无秘密文件（代码＋脚本） | 成立 |
| 15 | `/opt/openvpn-sk5-panel/panel/data/`（install.sh:529，无 chmod；app.py:101 makedirs 无 chmod） | 0755（umask 默认） | root；内文件逐个 0600（panel.db :250、agent_queue.json :588、secret.key/admin.pass 回落） | 成立（文件层钉死；目录未钉但无读出路径，见 §1 注） |
| 16 | `/etc/openvpn/server/` SERVER_DIR（install.sh:1061，无 chmod） | 0755（umask 默认） | root 读钥后降 nobody；内 server.key/ta.key 0600，其余公开 | 成立（同 #15） |
| 17 | `/etc/openvpn/server/easy-rsa` CA_DIR（install.sh:1062；easyrsa.sh:58-59） | 0700（显式 chmod） | root | 成立 |
| 18 | `/etc/openvpn/server/*.key`、`ta.key`（openvpn_manager:263，0600） | 0600 | root（openvpn 读钥后才降权） | 成立 |
| 19 | `/etc/openvpn/server/{ca,server}.crt`、`dh.pem`、`crl.pem`、`server.conf`（openvpn_manager:263/920/1154） | 0644 | 公开材料 | 成立 |
| 20 | `/var/log/openvpn/`（install.sh:1063-1065 chown nobody＋chmod 750） | 0750 nobody | nobody（openvpn 降权后写状态文件） | 成立 |
| 21 | `/run/openvpn-sk5-panel/` LOCK_DIR（policy-routing.sh:146，无 chmod） | 0755/0700（随 umask） | root（flock 锁文件，无秘密） | 成立 |
| 22 | `/etc/ovpn-agent/`（install-agent.sh:152-153） | 0700（显式 chmod） | root（agent） | 成立 |
| 23 | `/etc/ovpn-agent/config.json`（install-agent.sh:371-374 tmp 0600＋replace；agent.py:193-195 加载时再收紧） | 0600 | root | 成立 |
| 24 | `/etc/ovpn-agent/panel-ca.pem`（install-agent.sh:157 chmod 600；:204-206 out_pem 0600） | 0600（公开证书过度钉死，无害） | root | 成立 |
| 25 | agent 下载的二进制（agent.py:548-549/585-586 write_bytes＋chmod 0755） | 0755 | root 执行 | 成立 |
| 26 | systemd 单元（panel/singbox User=root；healthcheck/policy 无 User= 即 root；singbox CapabilityBoundingSet＋AmbientCapabilities） | — | 无 UMask=，进程继承 systemd 默认 umask 0022；全部秘密写点均显式 chmod，不依赖 umask | 成立 |
| 27 | `verify.sh`／`verify-integration.sh` 的 /tmp 测试树（TESTDIR 等） | 测试期产物；agent cfg :495-496 chmod 600＋chown nobody；login-payload :293-295 chmod 0600 | 测试工具，不进产品 | 成立 |

§1 注：
- **目录未钉、文件已钉的三处（#15/#16 与 sk5_manager 自建 CONFIG_DIR）**：`panel/data`、`/etc/openvpn/server`、sk5_manager 的 `CONFIG_DIR.mkdir(parents=True)`（:211/:290/:323/:390/:1322，无 chmod——生产态目录由安装器先建 0700，mkdir 为 no-op）均取 umask 默认 0755，但其内全部秘密文件逐个 0600，目录不可写（0755 他人无写权），无任何非 root principal 能读出秘密。`server.conf` 0644 不含秘密（路径＋端口＋DNS）。与 R37 §1 的信任锚一致，不立案；若求纵深可把三处目录也钉 0700，属加固非缺陷。
- **sing-box.log（#9）**：唯一无显式 chmod 的秘密邻接写点。内容是 sing-box 进程 stderr（启动/退出信息）；sing-box 默认日志不回显配置值，配置解析错误只报 JSON 路径不报值；且生产态父目录 0700。独立态（面板未过安装器、CONFIG_DIR 由 sk5_manager 自建 0755）下日志 0644 世界可读，但内容仍无凭据。不立案。
- **临时文件窗口**：login-payload.json（install.sh:1334、verify.sh:444、verify-integration.sh:293）先 `open("w")` 得 0644、同一进程内随即 chmod 0600、随即删除；含管理员明文密码，窗口为微秒级且须本地攻击者精确竞态。install.sh:1326 的 admin-pass.txt 用 `(umask 077; printf ...)` 全程 0600。属既定写法（R32 时间与顺序轮已过），不立案，见 O-R39-1。
- **sqlite -journal 瞬态文件**：app.py 未设 WAL，journal 模式为默认 rollback；事务期间 `-journal` 文件以 umask 默认 0644 存在于 0755 的 DATA_DIR 内，内含被改页的旧镜像（bcrypt 哈希，非明文），提交后删除。见 O-R39-1。

## §2 差集（新发现）

**无。差集 ∅。** 模式与属主清查 27 项（§1）逐项成立，无一立案。清查中逐项排除的近似项（均有行为或代码锚点，非“看起来没问题”）：
- `panel/data` 与 `/etc/openvpn/server` 目录取 umask 0755：其内秘密文件逐个 0600（panel.db、agent_queue.json、secret.key/admin.pass 回落、server.key/ta.key），目录他人无写权，无读出路径。属文件层钉死、目录层未钉，与信任模型（文件级 0600）一致。
- `sing-box.log` 无显式 chmod：内容仅 sing-box stderr，无凭据回显；生产态父目录 0700。
- `CONFIG_DIR.mkdir` 五处无 chmod：生产态目录由安装器先建 0700，mkdir 为 no-op；独立态下其内文件仍逐个 0600。

## §3 功能面核查（README／DELIVERY／security.md 骨架复核）

R38 修复逐项（任务简报指定项，逐项实证）：
- **R38-P2-1（`/etc/caddy` 目录模式未钉）已修成立**：两处 `mkdir -p /etc/caddy` 均已钉模式——:894 站 `chmod 755 /etc/caddy 2>/dev/null || true`（best-effort，注释写明后备是 validate-as-caddy 大声失败），:928 站 `chmod 755 /etc/caddy`（bare，注释写明 validate 已证目录可遍历、失败属 should-never-happen）。两处 chmod 行均为真实代码行，不只是注释（亲手读过 :894-902 与 :928-933 全文）。`tests/r38_runbook.sh` **30/30**（亲手重跑），其中 R6 五格逐字断言修复后行为（目录 0755、nobody 可读证书副本、validate 通过、端到端配好、第二轮重跑同绿）。**粘住的 0700 目录自愈已由我独立复现**（非继承修复路说法）：预置 0700 `/etc/caddy`＋0644 旧证书（nobody 实测不可读），原样抽取 install.sh:894/902/928/933 四行、umask 077 下跑，目录变为 0755、nobody 可读证书，随后清理。R38-P2-1 关闭。
- **修复路的分类断言已逐项核对**：其余 `mkdir -p`——CONFIG_DIR 0700（:439）、INSTALL_ROOT/panel（代码目录，无秘密）、panel/data（内文件逐个 0600）、SERVER_DIR（内密钥 0600）、CA_DIR 0700（:1062）、`/var/log/openvpn` chown nobody＋0750（:1063-1065）——分类属实，见 §1 清查表 #14/#15/#16/#17/#20。sk5_manager 的 `CONFIG_DIR.mkdir` 五处无 chmod，但生产态目录由安装器先建 0700，mkdir 为 no-op（§1 注）。无遗漏。
- **R37 三修复仍关闭**：R37-P2-1（守卫分支恢复调用，r37 探针 **7/7**）；R37-P2-2（live Caddyfile `chmod 644`，r37 模式探针 **7/7**，umask 077 下 live 文件 0644）；R37-P2-3（DELIVERY:49 现为 `/etc/caddy/panel-cert.pem`；全 docs 树旧路径零命中，审计/实录报告内的历史引用除外，未动）。
- **R20 三修复仍关闭**：BUG-1（r35 探针 46/46，TTY 全路径断言 `RESULT=[tty.example.com]`）；BUG-2（0644 副本＋caddy 用户 validate，r35 (e)/(g) 格）；BUG-3（安装器守卫＋面板 `_port_occupant`＋文档两方向一致，r35 (f) 格新鲜态 7 格全过）。
- **R35 三修复仍关闭**：R35-P2-1（failpath 探针 **8/8**）；R35-P2-2（README:83 与 DELIVERY:54 去反代步骤均列三行一并删，逐字对齐）；R35-P2-3（README 卸载章节有 `disable --now caddy`、删托管段、`ufw delete allow 80/tcp` 与 `443/tcp`、panel.env 随目录删的注——R38 R5 逐字执行，全部兑现）。
- **骨架其余宣称**（R34/R35/R36/R37/R38 已验、本轮 install.sh 之外零代码改动，靠门禁＋套件重跑复核，无回归）：UDP 1194 主／TCP 443 备、子网 10.8.0.0/24、策略路由只按源地址匹配、DNS 默认直连、13 命令白名单两端一致、fail-closed 黑洞＋fail-open 单向、登录限流 5/5 分钟锁 15 分钟、改密五规则（含 UTF-8 ≤72 字节）、CA 重建 force＋confirm、凭据红线（sk5.json 0600、回执无明文密码——门禁格通过）、verify.sh 24 项、二进制钉死（门禁 §7＋11 变异见 §5）。cloudflare/server-mode.md 无域名/Caddy/panel.env 字句——域名反代是纯服务器模式功能，无文档宣称可矛盾。security.md 自测命令核对：默认口令字面量 `grep -rnw` 零命中（agent.py:469/474 的 `123456` 是 hex 字符集 `"0123456789abcdef"` 的子串，-w 下不命中，与 security.md 注解一致）；`tls_insecure_skip_verify` 产品代码＋文档零命中。

## §4 两大复发族重扫

- **pipefail-SIGPIPE 族**：全树 7 个 shell 脚本均有 `set -euo pipefail` 或 `set -uo pipefail`（install.sh:24、verify.sh:58、verify-integration.sh:11、egress/policy-routing.sh:113、egress/test-egress.sh:36、agent/install-agent.sh:56、core/easyrsa.sh:18）。全树 `| head`／`| tail` 逐项核对，与 R37/R38 清单逐项一致、无新增：install.sh:356/385/395/418/427 均带 `|| true`；verify.sh:294/301/385 无 `-e` 且最坏空值、:319 `tail -1` 全量消费；verify-integration.sh:602/603/616/617 在无 `-e` 的脚本内，最坏空值只会让 §7 格大声红（fail-closed，已裁定）；test-egress.sh:84/165 同理无 `-e` 且 :165 带 `|| echo`。R39 新增管道：无（本轮未写新探针；install.sh 本轮无新增管道）。无新成员。
- **route-get-from-client-address 族**：全树 `ip route get` 逐项核对——VPN 查询一律 `from 10.8.0.1`（egress/test-egress.sh:61、egress/policy-routing.sh:538、install.sh:1377、verify.sh:711/874）；裸 `ip route get 1.1.1.1` 只作主表直连对照（test-egress.sh:74、policy-routing.sh:540、verify.sh:712）或取本机出口源地址（install.sh:122，带 `|| hostname -I` 回落）。R39 未新增任何 route-get。无复发。
- **tls_insecure_skip_verify**：产品代码全树零命中（仅 AUDIT-R35 报告行与 r35 探针自身的 grep 断言）。

## §5 门禁与探针

本轮亲手重跑（新鲜树副本 /tmp/r39/ptree＝工作树逐字节一致，install.sh sha256 `5a347d3717b2…`；Flask 探针各用新鲜 data 目录＋nobody 身份；/etc/openvpn-sk5-panel 全程不存在（终核已确认），/etc/caddy 每次探针后均由 trap 删除、终核不存在）：

| 套件 | 结果 | 备注 |
|---|---|---|
| 干净树门禁 verify-integration.sh | **29/29**（PASS=29 FAIL=0 SKIP=0） | 串行，含未提交 R38 修复 |
| §7 变异 11 棵 | **11/11 恰红 28/1**，红格逐棵均为 §7 钉死格 | m-dict-sb/ts/x-amd/x-arm/x-a/x-b/missing/extra、m-const-sb、m-install-sb、m-char；逐棵跑完即删；m-dict-sb 一棵重跑验红格确为 `[FAIL] 钉死哈希不一致`（§7），其余 10 棵同款单点位构造 |
| r38 运行手册 | **30/30** | R1 换域名 7、R2 空重跑 3、R3 去反代 6、R4 备份 2、R5 卸载 4、R6 目录模式 5（修复后行为断言）、抽取 3；R38-P2-1 仍关闭 |
| r35 域名反代 | **46/46** | |
| r35 失败路径 | **8/8** | R35-P2-1 仍关闭 |
| r35 ProxyFix/XFF 默认 | **4/4** | T0-01～T0-04 |
| r35 ProxyFix/XFF 信任 | **8/8** | T1-01～T1-08 |
| r37 BUG-3 守卫旧域 | **7/7** | R37-P2-1 仍关闭 |
| r37 Caddyfile 模式 umask 077 | **7/7** | R37-P2-2 仍关闭 |
| R17 Flask | **86/89** | 仅 OBSERVED 钉死格 F4-02b/F4-13/F4-15 红（既定） |
| R17 Core | **46/46** | |
| R17 Agent | **33/33** | |
| R17 Worker | **33/35** | 仅 OBSERVED 钉死格 W5-05/W5-06a 红（既定） |

**审计员执行事故（已纠正）**：ProxyFix 探针首轮两模式均落默认态——我误用 `R35_MODE` 传参，探针实际读 `R35_TRUSTED_PROXY`／`R35_PANEL_HTTPS`；按卷首正确变量名重跑信任态，得 8/8，全部结果为重跑值。

## §6 观察（不立案）与未验

- **O-R39-1（观察）**：两处微秒级临时文件窗口与一处瞬态 journal 文件，均无实际暴露。login-payload.json（install.sh:1334、verify.sh:444、verify-integration.sh:293）先 `open("w")` 得 0644、同一进程内随即 chmod 0600、随即删除，含管理员明文密码，须本地攻击者精确竞态才可读；install.sh:1326 的 admin-pass.txt 用 `(umask 077; ...)` 全程 0600。sqlite 默认 rollback journal：事务期间 `-journal` 文件以 0644 存在于 0755 的 DATA_DIR 内，内含被改页旧镜像（bcrypt 哈希，非明文），提交后删除。均不立案。
- **O-R38-1（旧观察，仍在）**：卸载后遗留物（apt 源、sysctl 文件、/etc/caddy 目录＋证书副本、空日志目录）均无害。本轮无新证据，不重立。
- **O-R35-1／O-R35-2（旧观察，仍在）**：横幅括号半角／全角混用；直连口伪造 XFF 可轮换绕过锁定（security.md 已披露机制与缓解）。本轮无新证据，不重立。
- **O-R34-1～O-R34-5（旧观察，仍在）**：daemon 死亡无看守；吊销后 restart 失败角；agent 无 executed-id 去重；重投集不对称；时钟跳变未定性。本轮无新证据，不重立。
- **O-R36-1（旧观察，仍在）**：r18 两探针与 r20 S1/S2/S6 的缺陷钉死格仍按原样钉缺陷行为（与 W5/F4 同款“已修树上按设计变红”）。本轮未重跑 r18/r20 套件（代码零改动面，R36 全量重跑在先），不翻。
- **O-R20-2（旧观察，仍在）**：Caddy 2.11.9 对 `tls_trusted_ca_certs` 打 deprecation warn，现为 warn、不致命。
- **O-R37-1（旧观察，仍在）**：面板证书只在缺失时重建，重建后若域名未变则面板不重启——运行中的面板继续用内存里的旧证书服务，而 Caddy 信任的是新拷的副本，代理断流直至面板手动重启。本轮无新证据，不重立。
- **未验**：P0-1 Cloudflare 真实部署（无进展）；真域名＋真 Let's Encrypt 证书的 live 实证（属 live-21：交互安装、换域、空重跑成功路径）；Caddy apt 安装与 HTTP-01 办证真机路径（属 live-21）；arm64 真机；IPRoyal 1001 vs 9000（用户未复）。
- **发版时刷新（非差集）**：DELIVERY §9 与卷首仍是 1.0.1 快照（审计 34 篇、live 20 份、台账 175、终审 R34、9 个关键文件哈希为 1.0.1 树版本）；1.0.2 发版时须按 R34 §6 同款口径刷新（审计 34→39 篇、live 20→21 份、台账 175→185、终审 R34→R39、重测 §9 清单与哈希），与 O-R28-1 旧项一致。

---

**台账**：185→**185**（174 已修、2 部分按设计、1 未验 P0-1、新 0、复发 0；R38-P2-1 已验证关闭）。

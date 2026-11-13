# AUDIT-R38 — 全量全局回头看（docs-as-runbook execution）

- **轮次**：R38（R37 三修复宣称已修后，1.0.2 发版前回头看）
- **日期**：2026-11-13
- **方法**：docs-as-runbook execution——把 README.md + docs/DELIVERY.md 里的每一条有操作步骤的程序（安装、域名设置、换域名、去反代、卸载、升级、备份/回滚、故障速查）逐条按字面执行（首次操作员视角；沙箱形上 stub caddy/systemctl，内核语义用真实 netns），任何一步按字面走不通、终态与文档承诺不符、或无法按字面执行即立案。同轮全树重扫两大复发族（pipefail-SIGPIPE 族；route-get-from-client-address 族），并重验门禁（verify-integration.sh 29/29；§7 变异 11/11 恰红 28/1）。
- **Verdict**：**不能交付（差集 1 条，P2）**——R37 三修复全部成立（守卫恢复调用、live Caddyfile 0644、DELIVERY 路径已改）；运行手册逐字执行中 R1–R5 全部通过（换域名、空重跑、去反代、备份、卸载）；唯一新发现是 R37-P2-2 的目录层同族：`/etc/caddy` 目录模式从未钉死（R38-P2-1），caddy 已装＋目录缺失＋umask 077 时反代永远装不上且重跑粘住。门禁与 §7 变异见 §5。

## §0 审计基线（被审树状态）

- git main @ cc56952，加未提交工作树改动：install.sh（域名反代功能＋R35-P2-1 修复＋R20 三 bug 修复＋R37-P2-1/P2-2 修复）、README.md＋docs/DELIVERY.md＋docs/security.md（R35-P2-2／P2-3＋R20-BUG-3 文档＋R37-P2-3）、docs/audit/AUDIT-R35.md、AUDIT-R36.md、AUDIT-R37.md、docs/live-verify-R20.md、tests/r35_domain_reverse_proxy.sh（46 格）、tests/r35_domain_failpath.sh、tests/r35_proxyfix_xff.py、tests/r37_bug3_guard_prev_domain.sh、tests/r37_caddyfile_mode_umask.sh。
- 台账基线：184 条（181＋R37 新 3，R37-P2-1/2/3 宣称已修）。
- 注：本仓库无 docs/index.md 与 docs/guide/ 13 篇（那是 FLMX 项目的骨架）；本项目的功能链骨架是 README.md＋docs/DELIVERY.md＋docs/security.md（＋cloudflare/server-mode.md），与 R34/R35/R36/R37 一致。
- 探针环境：新鲜树副本 /tmp/r38/ptree（工作树逐字节一致，install.sh sha256 `8782652b9e43…`）；/tmp/r33v/venv（Flask 3.1.3＋bcrypt）＋/tmp/r33f＋/tmp/fixture-server 沿用；Flask 探针各用新鲜 data/sk5cfg 目录＋nobody 身份；/etc/openvpn-sk5-panel 全程为空（终核已确认）；变异树因 /tmp 满（99%）移至工作区磁盘 `~/workspace/.r38-mutants` 逐棵跑完即删，终核目录已空。

## §1 方法与运行手册程序清单

方法：docs-as-runbook execution。枚举 README.md + docs/DELIVERY.md 里的全部有操作步骤的程序，按字面逐条执行（首次操作员视角；沙箱形上 stub caddy/systemctl/ufw/iptables，caddy-validate 一步以 nobody 真实降权实测可读性；卸载/备份在沙箱真实路径上以假树执行，预检确认无任何真实数据）。新写探针 `tests/r38_runbook.sh`（30 格），verbatim 抽取 install.sh 域名段（与 R35/R37 同款抽取法），R1–R6：

| 程序 | 文档出处 | 执行结果 |
|---|---|---|
| 换域名 `OVPN_PANEL_DOMAIN=<新> bash install.sh` | DELIVERY §1.2 | 通过 7/7：Caddyfile 旧托管段被替换、新域生效、其他站点保留、panel.env 得新域三变量、面板重启、Caddy 只 reload（不 restart） |
| 空重跑不改动（无 env、stdin /dev/null） | README 域名段／DELIVERY §1.2 | 通过：保留已配域名、Caddyfile 仍服务该域、面板不重启 |
| 去掉反代（手动四步）＋事后空重跑不复活 | README:83／DELIVERY:54 | 通过 6/6：托管段删净、其他站点保留、三变量全删、事后空重跑不复活域名、不重加托管段 |
| 升级前备份（`cp -a …/panel/data /root/panel-data-backup-$(date +%Y%m%d)`，逐字） | DELIVERY §7 | 通过：panel.db＋agent_queue.json 均在备份内且逐字节一致 |
| 卸载（README 整块逐字，确认提示喂 `y`） | README 卸载节 | 通过 4/4：/opt、/etc/openvpn-sk5-panel、/etc/openvpn/server、systemd 单元、托管段均删净，其他站点保留；遗留物见 §6（均无害） |
| /etc/caddy 目录模式（R37 遗留问题） | R37 修复路观察 | **复现缺陷（R38-P2-1，见 §2）**：caddy 已装＋目录缺失＋umask 077 时 mkdir 得 0700，caddy 读不到证书副本，validate 大声失败且重跑粘住 |

其余程序（面板使用步骤、§8 故障速查、agent 安装、Cloudflare 部署）不在沙箱逐字执行之列：面板流程由 R17 Flask 套件（§5）＋live-19/20 真机轮覆盖；Cloudflare 属 P0-1 未验（§6）。

## §2 差集（新发现）

### R38-P2-1：`/etc/caddy` 目录模式从未钉死——caddy 已装＋目录缺失＋umask 077 时反代永远装不上（install.sh:894/920）

- **严重度**：P2。**复现**：`tests/r38_runbook.sh` R6（5 格，全部断言缺陷签名、全部通过＝缺陷复现）：caddy 二进制已在 PATH（apt 步骤跳过）、`/etc/caddy` 缺失、umask 077 下跑 verbatim 域名段。目录落 `0700`，证书副本 `0644` 困在其中，nobody（caddy 替身）`test -r` 失败；`_validate_caddy_config` 以 caddy 身份跑 validate 即失败，走 warn 分支＋恢复旧域变量；live Caddyfile 从未写盘；第二轮同样重跑亦失败（粘住——`mkdir -p` 不改既存目录模式）。
- **机制**：两处 `mkdir -p /etc/caddy`（:894 证书拷贝前、:920 写 Caddyfile 前）均不钉模式。R37-P2-2 只钉了目录内的文件（证书副本 `install -m 0644`、live Caddyfile `chmod 644`），漏了目录本身。`mkdir -p` 对既存目录什么都不做，对新建目录取调用方 umask。
- **可达性**：须三条件同时成立：(a) caddy 包已装（`command -v caddy` 成功使 apt 步骤跳过——重装/换域/空重跑均如此）；(b) `/etc/caddy` 缺失（操作员为“删干净重装”而 `rm -rf /etc/caddy`；文档不教这一步，但用户有“删干净”习惯，且排障时删目录是常规动作）；(c) umask 027/077（027 得 0750、组外不可读，caddy 同样进不去；077 得 0700）。全新安装不受影响：apt 装 caddy 包时 .deb 自带 `/etc/caddy`（0755，dpkg 按包内模式建目录，不受 umask 影响），mkdir 时目录已在。失败是**大声的**（validate 失败 warn＋旧域变量恢复，见 R6 日志），不是静默；但**粘住**（重跑不改目录模式，须人工 `chmod 755 /etc/caddy` 才恢复），且 warn 文案只说“validate 失败”，不点名目录模式，操作员无从得知原因。
- **修法方向**：`mkdir -p /etc/caddy` 后加 `chmod 755 /etc/caddy`（与文件同款一行）；或改用 `install -d -m 0755 /etc/caddy`。另可把 R6 的 5 格翻为修复后行为断言（BH-03(c) 款式）。

## §3 功能面核查（README／DELIVERY／security.md 骨架复核）

R37 三修复逐项（任务简报指定项，逐项实证）：
- **R37-P2-1（BUG-3 守卫丢信任变量）已修成立**：守卫分支（install.sh:836-840）清 `_PANEL_DOMAIN` 之前先调 `_restore_prev_panel_domain()`，注释已改写为真话（守卫拒绝配新反代、但从不碰 Caddy）；`tests/r37_bug3_guard_prev_domain.sh` **7/7**，其中立案格逐字断言旧域三变量全在（`OVPN_PANEL_DOMAIN=old.example.com`＋`OVPN_PANEL_HTTPS=1`＋`OVPN_TRUSTED_PROXY=1`）、live Caddyfile 逐字节一致、冲突 warn 文案、caddy 全程未调用。R37-P2-1 关闭。
- **R37-P2-2（live Caddyfile 模式未钉）已修成立**：写盘后 `chmod 644 "$_CADDYFILE"`（install.sh:933）；`tests/r37_caddyfile_mode_umask.sh` **7/7**（umask 077 下 live 文件 0644）。R37-P2-2 关闭。**但同族漏了一件：`/etc/caddy` 目录本身的模式未钉（R38-P2-1，§2）。**
- **R37-P2-3（DELIVERY 旧证书路径）已修成立**：DELIVERY:49 现为 `tls_trusted_ca_certs /etc/caddy/panel-cert.pem`，与 `_CADDY_PANEL_CERT` 默认值一致；全 docs 树旧路径零命中（审计/实录报告内的历史引用除外，未动）。R37-P2-3 关闭。
- **R20 三修复仍关闭**：BUG-1（r35 探针 46/46，TTY 全路径断言 `RESULT=[tty.example.com]`）；BUG-2（0644 副本＋caddy 用户 validate，r35 (e)/(g) 格）；BUG-3（安装器守卫＋面板 `_port_occupant`＋文档两方向一致，r35 (f) 格新鲜态 7 格全过）。**但 BUG-2 的同族在目录层漏了一件（R38-P2-1）。**
- **R35 三修复仍关闭**：R35-P2-1（failpath 探针 **8/8**）；R35-P2-2（README:83 与 DELIVERY:54 去反代步骤均列三行一并删，逐字对齐）；R35-P2-3（README 卸载章节有 `disable --now caddy`、删托管段、`ufw delete allow 80/tcp` 与 `443/tcp`、panel.env 随目录删的注——本轮 R5 逐字执行，全部兑现）。
- **骨架其余宣称**（R34/R35/R36/R37 已验、本轮 install.sh 之外零代码改动，靠门禁＋套件重跑复核，无回归）：UDP 1194 主／TCP 443 备、子网 10.8.0.0/24、策略路由只按源地址匹配、DNS 默认直连、13 命令白名单两端一致、fail-closed 黑洞＋fail-open 单向、登录限流 5/5 分钟锁 15 分钟、改密五规则（含 UTF-8 ≤72 字节）、CA 重建 force＋confirm、凭据红线（sk5.json 0600、回执无明文密码——门禁格通过）、verify.sh 24 项、二进制钉死（门禁 §7＋11 变异见 §5）。cloudflare/server-mode.md 无域名/Caddy/panel.env 字句——域名反代是纯服务器模式功能，无文档宣称可矛盾。security.md 自测命令核对：默认口令字面量 `grep -rnw` 零命中（agent.py:469/474 的 `123456` 是 hex 字符集 `"0123456789abcdef"` 的子串，-w 下不命中，与 security.md 注解一致）；`tls_insecure_skip_verify` 产品代码＋文档零命中。

## §4 两大复发族重扫

- **pipefail-SIGPIPE 族**：全树 7 个 shell 脚本均有 `set -euo pipefail` 或 `set -uo pipefail`（install.sh:24、verify.sh:58、verify-integration.sh:11、egress/policy-routing.sh:113、egress/test-egress.sh:36、agent/install-agent.sh:56、core/easyrsa.sh:18）。全树 `| head`／`| tail` 逐项核对，与 R37 清单逐项一致、无新增：install.sh:356/385/395/418/427 均带 `|| true`；verify.sh:294/301/385 无 `-e` 且最坏空值、:319 `tail -1` 全量消费；verify-integration.sh:602/603/616/617 在无 `-e` 的脚本内，最坏空值只会让 §7 格大声红（fail-closed，已裁定）；test-egress.sh:84/165 同理无 `-e` 且 :165 带 `|| echo`。R38 新增管道：无（新探针只用 `grep`／`diff`／`stat`／`sed`／`cp`，无产品管道；install.sh 本轮无新增管道）。无新成员。
- **route-get-from-client-address 族**：全树 `ip route get` 逐项核对——VPN 查询一律 `from 10.8.0.1`（egress/test-egress.sh:61、egress/policy-routing.sh:538、install.sh:1364、verify.sh:711/874）；裸 `ip route get 1.1.1.1` 只作主表直连对照（test-egress.sh:74、policy-routing.sh:540、verify.sh:712）或取本机出口源地址（install.sh:122，带 `|| hostname -I` 回落）。R38 未新增任何 route-get。无复发。

## §5 门禁与探针

本轮亲手重跑（新鲜树副本 /tmp/r38/ptree＝工作树逐字节一致，install.sh sha256 `8782652b9e43…`；Flask 探针各用新鲜 data 目录＋nobody 身份；/etc/openvpn-sk5-panel 全程为空，/etc/caddy 每次探针后均由 trap 删除、终核不存在）：

| 套件 | 结果 | 备注 |
|---|---|---|
| 干净树门禁 verify-integration.sh | **29/29**（PASS=29 FAIL=0 SKIP=0） | 串行，含未提交 R37 修复 |
| §7 变异 11 棵 | **11/11 恰红 28/1**，红格逐棵均为 §7 钉死格 | m-dict-sb/ts/x-amd/x-arm/x-a/x-b/missing/extra、m-const-sb、m-install-sb、m-char；逐棵跑完即删 |
| r38 运行手册（本轮新写） | **30/30** | R1 换域名 7、R2 空重跑 3、R3 去反代 6、R4 备份 2、R5 卸载 4、R6 目录模式 5（R6 五格断言缺陷签名、通过＝缺陷复现）、抽取 3 |
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

**审计员执行事故（已纠正，均在记分运行之前）**：① 新探针的 stub 用 `chmod +x`——本机 shell umask 0007 会把 other 位的 x 抹掉（660→770），nobody 身份的 caddy stub 报 Permission denied，首轮 R1  validate 全灭；改绝对模式 `chmod 755` 后重跑，全部结果为重跑值（与 R36/R37 的 umask 事故同族：沙箱 umask 不是 022，相对模式不可信）。② 探针的 `PANEL_CERT`/`PANEL_KEY` 只在 harness 绑定一次，R1/R6 改指 `CONFIG_DIR` 后仍指向旧目录，证书拷贝静默跳过；改为每次跑 fragment 前按当前 `CONFIG_DIR` 重算。③ 11 棵变异树同时在位把 /tmp 顶到 99%（5.7M 剩余），变异树移至工作区磁盘逐棵跑完即删。

## §6 观察（不立案）与未验

- **O-R38-1（观察）**：卸载后遗留物（R5 实测）：`/etc/apt/sources.list.d/caddy-stable.list`＋`/usr/share/keyrings/caddy-stable-archive-keyring.gpg`、`/etc/sysctl.d/99-openvpn-sk5.conf`（`net.ipv4.ip_forward=1`）、`/etc/caddy/` 目录＋`panel-cert.pem` 公开证书副本、`/var/log/openvpn/` 空目录——README 卸载节均未提及。均无害：重装时 sysctl 文件、apt 源、证书副本均被覆写；keyring 与空日志目录 inert；证书是公开材料。不立案；若用户坚持“删干净”口径，卸载节补一行即可。
- **O-R35-1／O-R35-2（旧观察，仍在）**：横幅括号半角／全角混用；直连口伪造 XFF 可轮换绕过锁定（security.md 已披露机制与缓解）。本轮无新证据，不重立。
- **O-R34-1～O-R34-5（旧观察，仍在）**：daemon 死亡无看守；吊销后 restart 失败角；agent 无 executed-id 去重；重投集不对称；时钟跳变未定性。本轮无新证据，不重立。
- **O-R36-1（旧观察，仍在）**：r18 两探针与 r20 S1/S2/S6 的缺陷钉死格仍按原样钉缺陷行为（与 W5/F4 同款“已修树上按设计变红”）。本轮未重跑 r18/r20 套件（代码零改动面，R36 全量重跑在先），不翻。
- **O-R20-2（旧观察，仍在）**：Caddy 2.11.9 对 `tls_trusted_ca_certs` 打 deprecation warn，现为 warn、不致命。
- **O-R37-1（旧观察，仍在）**：面板证书只在缺失时重建，重建后若域名未变则面板不重启——运行中的面板继续用内存里的旧证书服务，而 Caddy 信任的是新拷的副本，代理断流直至面板手动重启。本轮无新证据，不重立。
- **未验**：P0-1 Cloudflare 真实部署（无进展）；真域名＋真 Let's Encrypt 证书的 live 实证（属 live-21：交互安装、换域、空重跑成功路径）；Caddy apt 安装与 HTTP-01 办证真机路径（属 live-21）；arm64 真机；IPRoyal 1001 vs 9000（用户未复）。
- **发版时刷新（非差集）**：DELIVERY §9 与卷首仍是 1.0.1 快照（审计 34 篇、live 20 份、台账 175、终审 R34、9 个关键文件哈希为 1.0.1 树版本）；1.0.2 发版时须按 R34 §6 同款口径刷新（审计 34→38 篇、live 20→21 份、台账 175→185、终审 R34→R38、重测 §9 清单与哈希），与 O-R28-1 旧项一致。

---

**台账**：184→**185**（174 已修、2 部分按设计、1 未验 P0-1、新 1，P2：R38-P2-1、复发 0；R37-P2-1／P2-2／P2-3 全部关闭）。

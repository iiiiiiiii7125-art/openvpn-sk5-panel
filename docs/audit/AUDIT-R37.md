# AUDIT-R37 — 全量全局回头看（principal-and-permission boundary audit）

- **轮次**：R37（live-20 三 bug 宣称已修后，1.0.2 发版前回头看）
- **日期**：2026-11-13
- **方法**：principal-and-permission boundary audit——对安装器、面板、agent、健康检查、Caddy 触及的每一个工件（文件、目录、socket、systemd 单元、端口）推导“谁以哪个 principal 运行、该 principal 能读/写/执行什么”，逐条对照文档化的信任模型核对边界。R20-BUG-2 正是边界失效（0700 目录 vs User=caddy），本方法系统找它的同族。同轮全树重扫两大复发族（pipefail-SIGPIPE 族；route-get-from-client-address 族），并重验门禁（verify-integration.sh 29/29；§7 变异 11/11 恰红 28/1）。
- **Verdict**：**不能交付（差集 3 条，全 P2）**——R20 三修复中 BUG-1（stderr 提示＋46 格 TTY 全路径断言）与 BUG-2（0644 副本＋caddy 用户 validate）成立；BUG-3 的安装器守卫在“已有域名＋Caddy 在跑＋重装切 TCP 443”分支丢信任变量（R37-P2-1，R35-P2-1 的同族），live Caddyfile 的模式从未钉死（R37-P2-2，BUG-2 修复漏的一件工件），DELIVERY 仍写旧证书路径（R37-P2-3，文档与代码矛盾）。门禁与 §7 变异见 §5。

## §0 审计基线（被审树状态）

- git main @ cc56952，加未提交工作树改动：install.sh（域名反代功能＋R35-P2-1 修复＋R20 三 bug 修复）、README.md＋docs/DELIVERY.md＋docs/security.md（R35-P2-2／P2-3＋R20-BUG-3 文档）、docs/audit/AUDIT-R35.md、AUDIT-R36.md、docs/live-verify-R20.md、tests/r35_domain_reverse_proxy.sh（46 格）、tests/r35_domain_failpath.sh、tests/r35_proxyfix_xff.py。
- 台账基线：181 条（178＋live-20 新 3，R20-BUG-1/2/3 宣称已修）。
- 注：本仓库无 docs/index.md 与 docs/guide/ 13 篇（那是 FLMX 项目的骨架）；本项目的功能链骨架是 README.md＋docs/DELIVERY.md＋docs/security.md（＋cloudflare/server-mode.md），与 R34/R35/R36 一致。
- 探针环境：新鲜树副本 /tmp/r37/ptree（工作树逐字节一致）；/tmp/r33v/venv（Flask 3.1.3＋bcrypt）＋/tmp/r33f＋/tmp/fixture-server 沿用；Flask 探针各用新鲜 data/sk5cfg 目录＋nobody 身份；/etc/openvpn-sk5-panel 全程为空（待终核）。

## §1 方法与边界图

Principal 清单（生产态，全部实测/代码锚定）：
- **root**：install.sh；面板 openvpn-sk5-panel（systemd User=root）；openvpn-server@server（发行版单元，root 启动，读完密钥后按 server.conf.template `user nobody / group nogroup` 降权；状态文件由降权后进程写，Debian 标准布局，live-20 BUG-9 双模实证写成功）；sing-box（User=root＋CAP_NET_ADMIN/CAP_NET_RAW/CAP_NET_BIND_SERVICE）；healthcheck（root oneshot）；agent（root；/etc/ovpn-agent/config.json 0600、目录 0700）。
- **caddy**（User=caddy，发行版单元）：读 /etc/caddy/Caddyfile、/etc/caddy/panel-cert.pem（0644 副本）；写 ACME 数据到自家 HOME（/var/lib/caddy）；绑 :80/:443 靠发行版单元的 CAP_NET_BIND_SERVICE（live-20 机上实证已绑上）。
- **nobody**：仅 openvpn 降权后身份（读密钥前已由 root 读完）；探针身份，非生产。
- **信任锚**：panel.env 0600 root-only（systemd EnvironmentFile）；CONFIG_DIR /etc/openvpn-sk5-panel 0700（admin.pass／secret.key／panel-key.pem 皆 root-only）；panel-cert.pem 本体 0644 但困在 0700 目录内——caddy 永远读不到本体，只能读 /etc/caddy/panel-cert.pem 副本（R20-BUG-2 修复的核心不变量）。

边界逐项核对（新功能触点，§2 只列有问题的；全绿项见 §3）：
- 提示语 stderr、env＞TTY＞旧域优先级、裸域名校验、DNS warn-only、Caddy 官方 apt 源、托管段 localhost＋trusted CA（无 insecure）、先 validate 后写 live、0644 证书副本每轮重拷（panel-key.pem 永不复制）、validate 以 caddy 用户跑（runuser＋HOME＋temp 644）、失败分支 _restore_prev_panel_domain（5 处）、unmask best-effort 永不致命、面板仅域名变化时重启、域名健康检查 warn-only——除 §2 三条外全部成立，证据见 §3/§5。

## §2 差集（新发现）

### R37-P2-1：R20-BUG-3 守卫在“已有域名＋Caddy 在跑”分支丢信任变量（install.sh:825-834）

- **严重度**：P2。**复现**：`tests/r37_bug3_guard_prev_domain.sh` **6/7**（本轮新写；按 marker 原样抽取 install.sh:630-659 与域名段全行，stub caddy/getent/systemctl——systemctl 报 Caddy 在运行，panel.env 预置旧域三变量，`OVPN_PROTO=tcp OVPN_PORT=443` 重装）。红格唯一：`panel.env keeps all three vars with the previous domain after TCP-443 guard`。
- **机制**：守卫分支（:825-834）只清 `_PANEL_DOMAIN=""`，不调 `_restore_prev_panel_domain`——其余 5 个失败分支（:880 Caddy 安装失败、:909 Caddyfile 构建失败、:914 validate 失败、:921 写 Caddyfile 失败、:976 启动后不在运行）全都调了。守卫注释自称“the proxy is being declined this run, so panel.env must not keep trusting a proxy the installer just refused to run”——前提是假的：守卫从未碰 Caddy，live Caddyfile 字节一致（探针实证）、Caddy 继续在 :443 服务旧域名。panel.env 在域名段之前已被全新重写（:642-659），旧的三变量只剩 `_PREV_PANEL_DOMAIN` 一份内存拷贝，守卫清掉它之后，盘上再无旧域记录。
- **后果**（与 R35-P2-1 同构，只是触发分支不同）：运行中的面板仍持旧环境，暂时无事；下一次面板重启后 ProxyFix 关闭，经域名来的全部客户端在限流看来都是 127.0.0.1——一个攻击者 5 次失败即锁住全部域名用户 15 分钟（install.sh:730-733 注释点名的模式）。且下一轮重装已无 `_PREV_PANEL_DOMAIN` 可读，域名配置无法靠重装恢复，须人工重设 `OVPN_PANEL_DOMAIN`。
- **可达性（已核）**：完整三元组“旧域＋Caddy 在跑＋服务端已是 TCP 443”作为稳态不可达（面板侧 `_port_occupant` 守卫挡切换，live-20 S4 实证 500）；但守卫分支本身可达——已配域名的 UDP 机器上跑 `OVPN_PROTO=tcp OVPN_PORT=443 bash install.sh` 即可触发。且该重装随后必死于 render（P01 入口口冻结：现有 server.conf 是 udp/1194，`render_server_conf` 默认 `allow_port_change=False` 即 raise，`set -e` 下安装中止）——panel.env 的损伤发生在 die 之前，留在盘上。反向不对称已核：无旧域的新装走同一守卫无损伤（无物可恢复）；TCP 443 服务端上无 env 的普通重装不触发守卫（`$OVPN_PROTO` 默认 udp），域名段走启动失败分支，恢复逻辑兜底。
- **附带核查**：panel.env 被重写进 `OPENVPN_PROTO=tcp / OVPN_PORT=443` 而 server.conf 仍是 udp/1194——已核无后果：`panel/app.py:1155-1156` 的 `_parse_server_conf` 以 server.conf 为准，环境值只是文件不可读时的回落。
- **修法方向**：守卫分支清 `_PANEL_DOMAIN` 之前先调 `_restore_prev_panel_domain()`（与其余 5 个失败分支同款，一行）。

### R37-P2-2：live Caddyfile 的模式从未钉死——validate 验的是 644 临时文件，Caddy 读的是 umask 决定的 live 文件（install.sh:915-918）

- **严重度**：P2。**复现**：`tests/r37_caddyfile_mode_umask.sh` **6/7**（本轮新写；同款 verbatim 抽取＋stub，`/etc/caddy` 已存在 0755 但 Caddyfile 不在——即按文档卸载删过文件后重装——`umask 077` 下跑域名段）。红格唯一：live Caddyfile 模式为 `600`，不是 0644；日志却走成功路径（`reverse proxy configured`）。
- **机制**：R20-BUG-2 的修复钉死了 caddy 读的其余全部工件——证书副本 `install -m 0644`（:892）、validate 临时文件 `chmod 644`（`_validate_caddy_config`）——唯独 live 文件落地用 `cat "$_CADDY_TMP" > "$_CADDYFILE"`（:915-918），模式继承既存文件或新建时取调用方 umask。`caddy validate` 验的是 644 的临时文件，必然通过；live 文件 0640/0600 时 caddy 用户读不到，服务起不来。修复的核心洞见（“以 caddy 用户验 caddy 将读的工件”）在此处恰好漏了一件。
- **可达性与后果**：需两个条件同时成立：live Caddyfile 不在（文档卸载步骤明确教 `rm -f /etc/caddy/Caddyfile`，重装即命中）＋限制性 umask（027 得 0640、077 得 0600；Debian 默认 022 得 0644 无事）。真机上启动检查会大声接住（not-running 分支＋恢复旧域变量，见 :976）——故不是静默失效；但失败是**粘住的**：重装时 `cat >` 保留既存 0600 模式，同一失败无限重复，须人工 `chmod 644 /etc/caddy/Caddyfile` 才能恢复。
- **修法方向**：写盘后 `chmod 644 "$_CADDYFILE"`（与临时文件同款，一行）；或改用 `install -m 0644`。

### R37-P2-3：DELIVERY.md 仍写 R20-BUG-2 修复前的证书路径（文档与代码矛盾）

- **严重度**：P2（文档）。**纯文档对代码矛盾，两边原文如下**：
  - docs/DELIVERY.md:49：“写 `/etc/caddy/Caddyfile`（`<域名> { reverse_proxy https://localhost:8443 { transport http { tls_trusted_ca_certs /etc/openvpn-sk5-panel/panel-cert.pem } } }`……）”。
  - install.sh:726 `_caddy_block`：“`tls_trusted_ca_certs /etc/caddy/panel-cert.pem`”（`_CADDY_PANEL_CERT` 默认值）；r35 探针 (c) 格逐字节比对生成的块为 `/etc/caddy/panel-cert.pem`。
- **后果**：按 DELIVERY 排障的操作者会在 0700 的 root-only 目录里找信任锚——正是 R20-BUG-2 的失效点本身；照此路径手改 Caddyfile 即复现 BUG-2（caddy 用户读不到，服务起不来）。README 域名段未写证书路径（无此问题），security.md 只写“面板自签 panel-cert.pem 校验”未写路径（无此问题）——唯 DELIVERY 写错。
- **修法**：DELIVERY.md:49 路径改为 `/etc/caddy/panel-cert.pem`，并注一句“公开证书副本，caddy 可读；panel-key.pem 永不复制”。

## §3 功能面核查（README／DELIVERY／security.md 骨架复核）

R20 三修复逐项（任务简报指定项，逐项实证）：
- **R20-BUG-1（提示语污染捕获值）已修成立**：`_resolve_panel_domain`（install.sh:696-708）提示语 `>&2`；`tests/r35_domain_reverse_proxy.sh` **46/46**，其中 TTY 格走完整调用点 `_PANEL_DOMAIN="$(_resolve_panel_domain)"`＋`_normalize_panel_domain` 并断言 `RESULT=[tty.example.com]`（R35 探针只数出现次数的形状缺口已补）。R20-BUG-1 关闭。
- **R20-BUG-2（证书在 0700 目录，caddy 读不到）已修成立**：证书副本 `install -m 0644` 每轮重拷（install.sh:891-892，`install -m 0644 "$PANEL_CERT" "$_CADDY_PANEL_CERT"`，r35 (e) 格逐行 grep 钉住）；生成块引用 `/etc/caddy/panel-cert.pem`（:726，全树无 `tls_trusted_ca_certs.*CONFIG_DIR`，r35 (e) 格）；`_validate_caddy_config` 以 `runuser -u caddy` 跑 validate（:742-752，HOME 取 caddy 自家目录、临时文件 chmod 644，r35 (g) 格 stub runuser 实证调用链＋回落 warn）；r35 探针 (e) 格“副本 0644 且字节一致”通过。panel-key.pem 永不复制（全树 grep：仅注释与变量定义，无复制命令）。R20-BUG-2 关闭。**但同族漏了一件：live Caddyfile 模式未钉（R37-P2-2）。**
- **R20-BUG-3（反代占 443，TCP 443 冲突）安装器侧成立、面板侧成立、文档两侧一致**：安装器守卫（:825-834）`OVPN_PROTO=tcp`＋`OVPN_PORT=443` 时跳过反代并大声 warn，r35 (f) 格新鲜态 7 格全过（warn 文案逐字、panel.env 无变量、caddy 未调用、live /etc/caddy 未动）；面板侧 `core/openvpn_manager.py:1122/1137` `_port_occupant`（bind 实测＋ss 点名）在切换与新建时均拒已占端口（live-20 S4 机上 500 点名 caddy）；README 域名段与 DELIVERY §1.2 域名小节均写明两方向（安装时已是 TCP 443 则跳过反代；反代在跑时面板切 TCP 443 被 500 拒绝，先拆反代再切）——两边逐字对齐。**但守卫分支在已有域名时丢信任变量（R37-P2-1）。**
- **`systemctl unmask caddy` best-effort 永不致命**：install.sh:959 `systemctl unmask caddy 2>/dev/null || true`，其后 `enable --now` 失败走 warn 分支（:960-963）并调 `_restore_prev_panel_domain`（:976 的 not-running 分支）；live-20 §7 注入式 masked 失败已活证该路径。成立。
- **R35 三修复仍关闭**：R35-P2-1（failpath 探针 **8/8**，validate 失败分支三变量保留＋live Caddyfile 字节一致＋warn 文案已改）；R35-P2-2（README:83 与 DELIVERY:54 去反代步骤均列三行一并删，逐字对齐）；R35-P2-3（README 卸载章节有 `disable --now caddy`、删托管段、`ufw delete allow 80/tcp` 与 `443/tcp`、panel.env 随目录删的注）。
- **骨架其余宣称**（R34/R35/R36 已验、本轮 install.sh 之外零代码改动，靠门禁＋套件重跑复核，无回归）：UDP 1194 主／TCP 443 备、子网 10.8.0.0/24、策略路由只按源地址匹配、DNS 默认直连、13 命令白名单两端一致、fail-closed 黑洞＋fail-open 单向、登录限流 5/5 分钟锁 15 分钟、改密五规则（含 UTF-8 ≤72 字节）、CA 重建 force＋confirm、凭据红线（sk5.json 0600、回执无明文密码——门禁格通过）、verify.sh 24 项、二进制钉死（门禁 §7＋11 变异见 §5）。cloudflare/server-mode.md 无域名/Caddy/panel.env 字句——域名反代是纯服务器模式功能，无文档宣称可矛盾。
- **DELIVERY 旧证书路径**：见 R37-P2-3（§2）。

## §4 两大复发族重扫

- **pipefail-SIGPIPE 族**：全树 7 个 shell 脚本均有 `set -euo pipefail` 或 `set -uo pipefail`（install.sh:24、verify.sh:58、verify-integration.sh:11、egress/policy-routing.sh:113、egress/test-egress.sh:36、agent/install-agent.sh:56、core/easyrsa.sh:18）。全树 `| head`／`| tail` 逐项核对：install.sh:356/385/395/418/427 均带 `|| true`；verify.sh:294/301/385 无 `-e` 且最坏空值、:319 `tail -1` 全量消费；verify-integration.sh:602/603/616/617 在无 `-e` 的脚本内，最坏空值只会让 §7 格大声红（fail-closed，已裁定）；test-egress.sh:84/165 同理无 `-e` 且 :165 带 `|| echo`。R37 新增管道：无（两支新探针只用 `grep`／`diff`／`stat`，无产品管道；install.sh 本轮无新增管道）。无新成员。
- **route-get-from-client-address 族**：全树 `ip route get` 逐项核对——VPN 查询一律 `from 10.8.0.1`（egress/test-egress.sh:61、egress/policy-routing.sh:538、install.sh:1352、verify.sh:711/874）；裸 `ip route get 1.1.1.1` 只作主表直连对照（test-egress.sh:74、policy-routing.sh:540、verify.sh:712）或取本机出口源地址（install.sh:122，带 `|| hostname -I` 回落）。R37 未新增任何 route-get。无复发。
- **tls_insecure_skip_verify**：产品代码全树零命中（仅 AUDIT-R35 报告行与 r35 探针自身的 grep 断言）。

## §5 门禁与探针

本轮亲手重跑（新鲜树副本 /tmp/r37/ptree＝工作树逐字节一致，install.sh sha256 `6f3cb2aa3f39…`；Flask 探针各用新鲜 data 目录＋nobody 身份；/etc/openvpn-sk5-panel 全程为空，/etc/caddy 每次探针后均由 trap 删除、终核不存在）：

| 套件 | 结果 | 备注 |
|---|---|---|
| 干净树门禁 verify-integration.sh | **29/29**（PASS=29 FAIL=0 SKIP=0） | 串行，含未提交 R20 修复 |
| §7 变异 11 棵 | **11/11 恰红 28/1**，红格逐棵均为 §7 钉死格 | m-dict-sb/ts/x-amd/x-arm/x-a/x-b/missing/extra、m-const-sb、m-install-sb、m-char；逐棵跑完即删 |
| r35 域名反代 | **46/46** | 校验 18、panel.env 3、Caddyfile 5、证书副本 4、非 TTY/env/旧域/TTY 5、BUG-3 新鲜态 7、validate-as-caddy 3、抽取 1；TTY 格为 R20-BUG-1 全路径断言 |
| r35 失败路径 | **8/8** | R35-P2-1 仍关闭 |
| r35 ProxyFix/XFF 默认 | **4/4** | T0-01～T0-04 |
| r35 ProxyFix/XFF 信任 | **8/8** | T1-01～T1-08 |
| r37 BUG-3 守卫旧域（本轮新写） | **6/7** | 红格唯一：R37-P2-1 立案格 |
| r37 Caddyfile 模式 umask 077（本轮新写） | **6/7** | 红格唯一：R37-P2-2 立案格（live 文件 600） |
| R17 Flask | **86/89** | 仅 OBSERVED 钉死格 F4-02b/F4-13/F4-15 红（既定） |
| R17 Core | **46/46** | |
| R17 Agent | **33/33** | |
| R17 Worker | **33/35** | 仅 OBSERVED 钉死格 W5-05/W5-06a 红（既定） |

**审计员执行事故（已纠正）**：/tmp/r37 父目录权限 770（shell umask 077）挡住 nobody，首轮 ProxyFix 探针 Errno 13——与 R36 第一轮同款失误；chmod 755 父目录后重跑，全部结果为重跑值。/tmp 曾到 90%（11 棵变异树同时在位），变异逐棵删后回 79%。

## §6 观察（不立案）与未验

- **O-R35-1／O-R35-2（旧观察，仍在）**：横幅括号半角／全角混用；直连口伪造 XFF 可轮换绕过锁定（security.md 已披露机制与缓解）。本轮无新证据，不重立。
- **O-R34-1～O-R34-5（旧观察，仍在）**：daemon 死亡无看守；吊销后 restart 失败角；agent 无 executed-id 去重；重投集不对称；时钟跳变未定性。本轮无新证据，不重立。
- **O-R36-1（旧观察，仍在）**：r18 两探针与 r20 S1/S2/S6 的缺陷钉死格仍按原样钉缺陷行为（与 W5/F4 同款“已修树上按设计变红”）。本轮未重跑 r18/r20 套件（代码零改动面，R36 全量重跑在先），不翻。
- **O-R20-2（旧观察，仍在）**：Caddy 2.11.9 对 `tls_trusted_ca_certs` 打 deprecation warn，现为 warn、不致命。
- **O-R37-1（观察）**：面板证书只在缺失时重建（install.sh:550），重建后若域名未变则面板不重启——运行中的面板继续用内存里的旧证书服务，而 Caddy 信任的是新拷的副本，代理断流直至面板手动重启。触发须操作者先删 panel-cert.pem（安装器本身永不删），且域名健康检查会 warn（文案指向 DNS/办证，易误导）。窄、不立案；修法是重建证书时强制重启面板，或把证书重建与域名变化同等对待。
- **未验**：P0-1 Cloudflare 真实部署（无进展）；真域名＋真 Let's Encrypt 证书的 live 实证（属 live-21：交互安装、换域、空重跑成功路径）；Caddy apt 安装与 HTTP-01 办证真机路径（属 live-21）；arm64 真机；IPRoyal 1001 vs 9000（用户未复）。
- **发版时刷新（非差集）**：DELIVERY §9 与卷首仍是 1.0.1 快照（审计 34 篇、live 20 份、台账 175、终审 R34、9 个关键文件哈希为 1.0.1 树版本）；1.0.2 发版时须按 R34 §6 同款口径刷新（审计 34→37 篇、live 20→21 份、台账 175→181＋本轮新 3、终审 R34→R37、重测 §9 清单与哈希），与 O-R28-1 旧项一致。

---

**台账**：181→**184**（171 已修、2 部分按设计、1 未验 P0-1、新 3，全 P2：R37-P2-1／R37-P2-2／R37-P2-3、复发 0；R20-BUG-1／BUG-2／BUG-3 全部关闭）。

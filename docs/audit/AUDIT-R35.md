# AUDIT-R35 — 全量全局回头看（doc-claim invariant audit）

- **轮次**：R35（R34 可交付后，域名反代功能新增后回头看）
- **日期**：2026-11-13
- **方法**：doc-claim invariant audit——抽取 README.md、docs/DELIVERY.md、docs/security.md 中全部规范性宣称，转为可核查不变量，逐条对照代码与行为实证（沙箱可跑者跑探针；仅真机能定者标未验，绝不写成已验证）。同轮全树重扫两大复发族（pipefail-SIGPIPE 族；route-get-from-client-address 族），并重验门禁（verify-integration.sh 29/29；§7 变异 11/11 恰红 28/1）。
- **Verdict**：**不能交付（差集 3 条，全 P2）**——域名反代功能本身的 happy path 全过（r35 探针 30/30），但重跑失败路径会静默丢弃已配反代的信任变量、两处文档对“去掉反代”说法互相矛盾、卸载章节漏了 Caddy。门禁 29/29、§7 变异待 §5 结果。

## §0 审计基线（被审树状态）

- git main @ cc56952 "Docs: install commands are paste-ready on the server, no ssh wrapper"，加未提交工作树改动：install.sh（域名反代功能，+265）、README.md（+2）、docs/DELIVERY.md（+15）、docs/security.md（+1）；新增 tests/r35_domain_reverse_proxy.sh。
- 本轮包含的新功能：安装时交互填域名，自动装 Caddy 反代到面板（Let's Encrypt 自动办证），panel.env 追加 OVPN_PANEL_DOMAIN / OVPN_PANEL_HTTPS=1 / OVPN_TRUSTED_PROXY=1。
- 台账基线：175 条（171 已修、2 部分按设计、1 未验 P0-1 Cloudflare 真实部署）。
- 注：本仓库无 docs/index.md 与 docs/guide/ 13 篇（那是 FLMX 项目的骨架）；本项目的功能链骨架是 README.md＋docs/DELIVERY.md＋docs/security.md（＋cloudflare/server-mode.md），与 R34 §3 一致。本轮方法按此三文档抽取规范性宣称。

## §1 方法与宣称清单

方法：doc-claim invariant audit。抽取 README.md、docs/DELIVERY.md、docs/security.md 全部规范性宣称，转为不变量，逐条对照代码与行为。沙箱可跑者跑探针；仅真机能定者标未验。宣称分三组，逐条 verdict（✓＝行为实证一致，✗＝差集见 §2，～＝观察见 §6）：

**A. 域名反代（新功能，R35 重点）**
- A1 交互问一次域名，留空不设反代；重装留空＝“不改动”保留已配域名 ✓（r35 探针：非 TTY 返回旧域、TTY 接受输入；代码 install.sh:769-782）
- A2 非交互用 OVPN_PANEL_DOMAIN 预设，不弹提示 ✓（r35 探针；install.sh:694-702）
- A3 域名须裸域名（无 scheme/端口/路径），末尾一个点去掉；输错只警告不中断 ✓（r35 探针 17 格；install.sh:673-682）
- A4 解析未生效只警告，Caddy 在 DNS 生效后自动重试 ✓ 代码（warn-only，install.sh:783-793）；“自动重试”本身是 Caddy 默认行为，沙箱无 Caddy 真机未验
- A5 Caddy 从官方 apt 源安装；失败只警告、面板仍可用 IP 访问 ✓ 代码（install.sh:796-838，任一步失败置 _CADDY_INSTALL_OK=0）；真机安装未验
- A6 Caddyfile 托管段：`reverse_proxy https://localhost:8443`＋`tls_trusted_ca_certs panel-cert.pem`，不跳过校验 ✓（r35 探针：精确比对＋全树无 tls_insecure_skip_verify；install.sh:713-717）
- A7 `caddy validate` 通过后才启用 ✓ 代码（install.sh:839-858，先建临时文件校验再写 live）；真机未验
- A8 开 80/443（ufw 在用则 ufw allow，否则 live iptables、重启不保留）✓ 代码（install.sh:852-869）
- A9 panel.env 追加三变量（DOMAIN／HTTPS=1 Secure cookie／TRUSTED_PROXY=1 ProxyFix）✓（r35 探针；install.sh:728-735；app.py:182-190）
- A10 面板之后用 `https://<域名>` 访问，`https://IP:8443` 仍可用 ✓ 代码（panel 仍监听 8443，明文本体＋TLS wrapper 不变）；真机未验
- A11 完成横幅同时印两个地址 ✓ 代码（install.sh:1316-1324）；～ 括号半角/全角混用（O-R35-1）
- A12 换域名：`OVPN_PANEL_DOMAIN=<新> bash install.sh` 重装，旧面板段被替换，面板自动重启 ✓ 代码（install.sh:852-895；重启条件为域名变化且面板在运行）
- A13 去掉反代手动步骤 ✗（R35-P2-2：README 与 DELIVERY 说法矛盾；见 §2）
- A14 失败路径“只警告、面板仍可用 IP 地址访问” ✗（R35-P2-1：validate／启动失败时静默丢弃已配域名的 panel.env 信任变量；见 §2）
- A15 security.md“域名反代”行：SAN 含 DNS:localhost ✓（install.sh:554 `-addext "subjectAltName=IP:$SERVER_IP,DNS:localhost"`）；ProxyFix 取末尾一跳 ✓（tests/r35_proxyfix_xff.py T1-05/T1-06 行为实证）；～ 直连口伪造 XFF 可轮换绕过锁定（O-R35-2）

**B. 功能链骨架（README／DELIVERY／security.md 其余宣称，复核）**
- B1 UDP 1194 主／TCP 443 备；子网 10.8.0.0/24；策略路由只按源地址匹配；DNS 默认走直连 ✓（R34 已验；本轮门禁 29/29＋R17 套件重跑见 §5，无回归）
- B2 13 个命令白名单，两端逐字一致 ✓（门禁格＋R17 Agent 33/33）
- B3 断网保护（fail-closed 黑洞）与 fail-open 单向 ✓（R34 已验；本轮无代码改动）
- B4 登录限流：同 IP 5 分钟 5 次失败锁 15 分钟，429＋Retry-After ✓（tests/r35_proxyfix_xff.py T0-01/T0-02 行为实证；T1-03 轮换绕过见 O-R35-2）
- B5 改密：≥12 字符＋字母数字、与旧不同、UTF-8 ≤72 字节；改密后全部旧会话作废 ✓（R33 10/10；本轮无改动）
- B6 CA 重建 force＋confirm 双重门；重建后全部证书失效 ✓（R34 已验；本轮无改动）
- B7 凭据红线：sk5.json 0600；get_status／日志／报错永不出现 SK5 明文密码 ✓（门禁“回执 JSON 里无节点 token”格通过）
- B8 Cloudflare 模式未验（P0-1）✓ 诚实标注（README、DELIVERY §2、§6-7 三处一致；wrangler.toml 仍为占位符，未变）
- B9 verify.sh 24 项、SK5 已启用时切换测试自动 SKIP ✓（R34 已验；本轮无改动）
- B10 二进制钉死：sing-box 1.11.15／tun2socks 2.7.0，四哈希两处同步 ✓（门禁 §7 钉死格＋变异见 §5）
- B11 卸载（手动）✗（R35-P2-3：漏 Caddy 清理；见 §2）

**C. 交互注记核查（handover 两项）**
- (a) 真域名＋真 Let's Encrypt 证书的 live 实证：属 live 轮，记未验（见 §6），本轮不尝试定案。
- (b) 重跑换域时面板重启 vs 健康门禁零重启检查：**成立**。行为实证（本机 systemd 255）：Restart=on-failure 服务自动重起 2 次后 NRestarts=2，手动 `systemctl restart` 后 NRestarts=0、ActiveState=active。门禁 `wait_steady_active`（install.sh:1140-1158）对 openvpn-sk5-panel（:1198）查 NRestarts≠0 即 die；换域重启发生在 :888-892，门禁在 :1198，中间 `enable --now` 对已运行单元是 no-op，故门禁看到的是手动重启后的 0。注：在 Debian 12（systemd 252）上测的是 255 的同族行为，reset-on-stop 是 systemd 长期行为；live-20 可在真机换域重跑时顺带复核一行。

## §2 差集（新发现）

### R35-P2-1：重跑失败路径静默丢弃已配域名的 panel.env 信任变量（install.sh 域名段）

- **严重度**：P2。**复现**：`tests/r35_domain_failpath.sh` **8/8**（本轮新写；按 marker 原样抽取 install.sh:630-659 与 :769-899 的 shipped lines，stub 掉 caddy/getent/systemctl 后真跑）。
- **机制**：panel.env 在域名段之前已被全新重写（install.sh:642-659），旧的三变量只剩 `_PREV_PANEL_DOMAIN` 一份内存拷贝；域名段任一失败分支（`caddy validate` 失败 :845-849、caddy 启动后不在运行 :896-899）都置 `_PANEL_DOMAIN=""` 并跳过 `_append_panel_env_domain`。于是重跑结束时 panel.env 里三个变量全无，而 live Caddyfile 仍原样服务旧域名（validate 失败分支根本没碰 live 文件，探针实测字节一致）。
- **后果**：运行中的面板仍持旧环境，暂时无事；下一次面板重启（重起服务、机器重启、下次重跑）后 ProxyFix 关闭，经域名来的全部客户端在限流看来都是 127.0.0.1——一个攻击者 5 次失败即锁住全部域名用户 15 分钟。正是 install.sh:730-733 注释点名的失败模式。且下一轮重跑已无 `_PREV_PANEL_DOMAIN` 可读，域名配置无法靠重跑恢复，须人工重设 OVPN_PANEL_DOMAIN。
- **与文档的矛盾**：代码注释 install.sh:630-633 自称“a re-run never silently drops the reverse proxy”；DELIVERY 称“重装时留空表示‘不改动’，保留已配的域名与 Caddy 配置”。失败分支下两者皆不成立。
- **附带**：validate 失败分支的 warn 文案（install.sh:846）称“leaving Caddy stopped”，但该分支从未停 Caddy——Caddy 正在运行且保持旧配置，文案与事实相反（探针 T-cell 实证：stub 报告 caddy active，文案仍称 stopped）。
- **修法方向**：失败分支不清空已配域名的变量——validate／启动失败时把 `_PREV_PANEL_DOMAIN` 的三变量写回 panel.env（或失败即保留旧 panel.env），并把 warn 文案改成“Caddy 仍在运行旧配置，panel.env 已保留旧域名变量”；同理，Caddyfile 已写盘但 caddy 起不来的分支亦然。

### R35-P2-2：README“去掉反代”步骤漏删 OVPN_PANEL_HTTPS／OVPN_TRUSTED_PROXY，与 DELIVERY 矛盾

- **严重度**：P2（文档，安全相关）。**纯文档对文档矛盾，两边原文如下**：
  - README.md（域名反代段）：“去掉反代需手动操作：停并禁用 Caddy……清 `panel.env` 里的 `OVPN_PANEL_DOMAIN` 行并重启面板”。
  - docs/DELIVERY.md（§1.2 域名小节）：“删 `/etc/openvpn-sk5-panel/panel.env` 里的 `OVPN_PANEL_DOMAIN` 行（`OVPN_PANEL_HTTPS` 与 `OVPN_TRUSTED_PROXY` 两行也一并删掉，否则面板会继续信任 X-Forwarded-For）”。
- **后果**：按 README 操作后，面板重启时仍读到 `OVPN_TRUSTED_PROXY=1`，继续信任直连 8443 上任何人自带的伪造 X-Forwarded-For（行为锚点：tests/r35_proxyfix_xff.py T1-02/T1-03——信任开启时锁定跟随伪造 IP、轮换伪造值即可绕过）。反代已拆、信任未拆，是最差的组合。
- **修法**：README 去反代步骤与 DELIVERY 对齐，写明三行一并删。

### R35-P2-3：README“卸载（手动）”漏了 Caddy 清理

- **严重度**：P2（文档）。**原文**：卸载章节列出停用的单元（panel／singbox／server／policy／healthcheck）、删除的目录与单元文件、NAT／FORWARD 规则删除、`ufw delete allow 1194/udp` 与 `8443/tcp`——全程无 Caddy。
- **后果**：按章节卸载后，Caddy 仍是 enabled＋running，托管段仍把域名反代到已删的面板（502），`tls_trusted_ca_certs` 指向已被 `rm -rf /etc/openvpn-sk5-panel` 删掉的 panel-cert.pem；下次 Caddy 重起即加载失败；80/443 的 ufw 放行亦残留。install.sh 在域名段明确 `systemctl enable --now caddy`（:872-874），卸载章节须有对应逆操作。
- **修法**：卸载章节补 `systemctl disable --now caddy`、删 Caddyfile 托管段（或删 `/etc/caddy/Caddyfile`）、`ufw delete allow 80/tcp` 与 `443/tcp`；并与 R35-P2-2 的三行 panel.env 清理互相引用（panel.env 随 `/etc/openvpn-sk5-panel` 一并删除，卸载场景下三行问题自动消失，须写明这一点以免读者困惑）。

## §3 域名反代功能面核查

新功能 happy path 全过；问题全在 §2 的三处。逐项核查（代码行号为当前 install.sh）：

- **域名提示**：`_resolve_panel_domain`（:694-708）优先级 env＞TTY 提示＞旧域；TTY 下 `read -r -t 60`，60 秒超时返回空、不挂住非交互运行；非 TTY 直接跳过。r35 探针：非 TTY 快跳、env 路径、旧域保留、TTY 接受输入四格全过。提示文案与 DELIVERY 一字不差。
- **校验**：`_normalize_panel_domain`（:673-682）裸域名正则、去一尾点；r35 探针 4 接受＋13 拒绝全过。无效输入只 warn、不中断（:776-778），重装时无效新域回落旧域并有 log 行（:779-782）。
- **DNS 检查**：warn-only（:783-793），查不到／指的不是本机都只警告；`_resolve_domain_ip`（:710-712）取首个 IPv4，`getent | awk … exit` 提前退出只影响退出码，调用点有 `|| true`（:787）且值在 exit 前已打印——无 SIGPIPE 族新成员（见 §4）。
- **Caddy 安装**：官方 apt 源（dl.cloudsmith.io gpg key＋debian.deb.txt，与 caddyserver.com 文档一致）；任一步失败置 `_CADDY_INSTALL_OK=0`、warn 后跳过反代（:796-838）；`curl | gpg` 与 `curl | tee` 均为全量消费管道，全局 `set -o pipefail` 下失败可捕获。真机安装未验。
- **Caddyfile 托管段**：`_build_caddyfile`（:719-727）先剔旧托管段再追加新段、其余内容保留，写临时文件→`caddy validate` 通过才写 live（:839-858），坏配置永不落地已配好的反代。r35 探针精确比对＋marker 替换全过。
- **panel.env 三变量**：`_append_panel_env_domain`（:728-735）仅在 Caddy 已启动后才追加（:878-895）——无反代在前时不信任 XFF 的顺序正确。app.py 不读 OVPN_PANEL_DOMAIN（grep 零命中），该变量只是安装器的记录；HTTPS／TRUSTED_PROXY 由 app.py:182-190 消费。
- **80/443 开放**：ufw 活动则 `ufw allow`，否则 live iptables＋明确警告重启不保留（:852-869）。与主安装器的 ufw／iptables 口径一致。
- **域名健康检查**：`curl https://<域名>/api/me` 失败只 warn、不 die（:1250-1258）；面板直连门禁在前已过（:1198＋登录＋/api/status）。
- **完成横幅**：同时印 IP 与域名两地址（:1316-1324）；～ 括号半角 `(` 配全角 `）`（O-R35-1）。
- **换域重跑**：Caddyfile 旧段替换、新段写盘、caddy reload、域名变化时面板重启（:888-892）。重启与门禁的关系见 §1-C(b)：成立。
- **去反代／卸载文档**：见 R35-P2-2／R35-P2-3。

## §4 两大复发族重扫

- **pipefail-SIGPIPE 族**：全树 7 个 shell 脚本（install.sh、verify.sh、verify-integration.sh、egress/policy-routing.sh、egress/test-egress.sh、agent/install-agent.sh、core/easyrsa.sh）均有 `set -o pipefail`（panel/static/contrast-check.py 是 Python，无 shell 管道）。R35 新增管道逐一核对：`getent | awk … exit`（:711，调用点 `|| true`＋值先打印）、`grep | cut | tr`（:636，全量消费＋`|| true`）、`curl | gpg`／`curl | tee`（:807-815，全量消费＋`|| _CADDY_INSTALL_OK=0`）——无新成员。旧防线仍在：install.sh:378-386 与 :424-428 的 `head -1 | grep -q` 仍带 `|| true` 与 SIGPIPE 注释。
- **route-get-from-client-address 族**：全树 `ip route get` 逐项核对——VPN 查询一律 `from 10.8.0.1`（egress/test-egress.sh:61、egress/policy-routing.sh:538、install.sh:1273、verify.sh:711/874）；裸 `ip route get 1.1.1.1` 只作主表直连对照（test-egress.sh:74、policy-routing.sh:540、verify.sh:712）或取本机出口源地址（install.sh:122，带 `|| hostname -I` 回落）。R35 未新增任何 route-get。无复发。

## §5 门禁与探针

本轮亲手重跑（新鲜树副本 /tmp/r35/ptree＝工作树逐字节一致，install.sh sha 前 12 位 `885b38ce7ca4` 与工作树相同；Flask 探针各用新鲜 data 目录＋nobody 身份；/tmp/r33v/venv＋/tmp/r33f＋/tmp/fixture-server 沿用 R33 控制器重建物）：

- **干净树门禁**：`bash verify-integration.sh` → **PASS=29 FAIL=0 SKIP=0**（串行，树含未提交 R35 改动）。
- **§7 变异**：`tests/build-mutants.py` 造 11 棵变异树，逐棵串行跑门禁，**11/11 恰红 28/1**，红格逐棵核对均为 §7 钉死格（“钉死哈希不一致：install.sh 与 agent/agent.py 的 sha256 逐键不等”）：m-dict-sb、m-dict-ts、m-dict-x-amd、m-dict-x-arm、m-dict-x-a、m-dict-x-b、m-dict-missing、m-dict-extra、m-const-sb、m-install-sb、m-char。
- **r35 域名反代探针**：`tests/r35_domain_reverse_proxy.sh` **30/30**（校验 17 格、panel.env 3 格、Caddyfile 4 格、非 TTY／env／旧域／TTY 4 格、辅助 2 格）。
- **r35 失败路径探针（本轮新写）**：`tests/r35_domain_failpath.sh` **8/8**——按 marker 原样抽取 install.sh:630-659 与 :769-899 的 shipped lines，stub caddy（validate 恒失败）／getent／systemctl 后真跑；复现 R35-P2-1（panel.env 丢三变量、live Caddyfile 仍服务旧域且字节一致、warn 文案错称“Caddy stopped”）。
- **r35 ProxyFix 探针（本轮新写）**：`tests/r35_proxyfix_xff.py`——默认模式 **4/4**（XFF 被忽略、锁定跟连接 IP、HTTPS=0 无 Secure）；信任模式 **8/8**（锁定跟随伪造 IP、轮换伪造值绕过锁定、末尾一跳取胜且恰计一次、HTTPS=1 有 Secure）。
- **R17 四套件**：Flask **86/89**（仅 OBSERVED 钉死格 F4-02b/F4-13/F4-15 红）、Core **46/46**、Agent **33/33**、Worker **33/35**（仅 OBSERVED 钉死格 W5-05/W5-06a 红）。与 R34 同数，无回归、无新红格。
- **R32**：`tests/r32_enable_wait_window.py` **8/8**。
- **NRestarts 语义实证**（§1-C(b)）：本机 systemd 255 上 Restart=on-failure 服务自动重起 2 次后 NRestarts=2，手动 `systemctl restart` 后 NRestarts=0、ActiveState=active；测试单元已清理。
- **范围说明**：本轮代码改动只在 install.sh 与三文档，故探针重跑聚焦门禁＋R35 新面＋R17 四套件＋R32；其余套件（BK／BM／BO／BP／BQ／BR／BS／BT／R24／R25／R27／R29／R31）在 R34 同树同基线上全量重跑无回归，相关代码本轮零改动，不重复跑。
- /etc/openvpn-sk5-panel/ 全程为空，0 泄漏；failpath 探针临时建的 /etc/caddy 已由其 trap 删除，事后复核不存在；fixture-server/server.conf 内容为 port 1194 udp，未被改动。

## §6 观察（不立案）与未验

- **O-R35-1（观察）**：完成横幅域名行括号半角／全角混用——install.sh:1318 `(Caddy 自动 HTTPS；IP 直连仍可用）`，开 `(` 半角、闭 `）` 全角。纯排版，不立案。
- **O-R35-2（观察，安全残留）**：`OVPN_TRUSTED_PROXY=1` 时，直连 `https://IP:8443` 可带伪造 X-Forwarded-For：行为实证（r35_proxyfix_xff.py T1-03）——轮换伪造值每次都是 401，永不锁定；T1-02/T1-04 证实计数按伪造 IP 走。security.md 只写“限流会按伪造 IP 计数”，未写明后果：同一来源 IP 可无限尝试，且伪造受害者 IP 连错 5 次可锁住该 IP 15 分钟（含走域名访问的管理员）。不立案的理由：① 文档已披露机制与缓解（防火墙把 8443 只放给可信 IP）；② 管理员密码是随机 128 位 `token_urlsafe(16)`，无限尝试也无 brute-force 实际意义；③ README 已要求面板不直接暴露公网。建议：security.md 把绕过后果写明一句；后续可考虑仅当对端为 127.0.0.1（即 Caddy）时才应用 ProxyFix，从根上关闭直连口伪造。
- **O-R34-1～O-R34-5（旧观察，仍在）**：daemon 死亡无看守；吊销后 restart 失败角；agent 无 executed-id 去重；重投集不对称；时钟跳变未定性。均已在 R34 登记，本轮无新证据，不重立。
- **未验**：P0-1 Cloudflare 真实部署（无进展）；真域名＋真 Let's Encrypt 证书的 live 实证（handover (a)，属 live-20）；Caddy apt 安装与 HTTP-01 办证真机路径（属 live-20）；arm64 真机；IPRoyal 1001 vs 9000（用户未复）。
- **发版时刷新（非差集）**：DELIVERY §9 与卷首仍是 1.0.1 快照（审计 34 篇、live 20 份、台账 175、终审 R34、9 个关键文件哈希为 1.0.1 树版本）；1.0.2 发版时须按 R34 §6 同款口径刷新（审计 34→35 篇、台账 175→178、终审 R34→R35、重测 §9 清单与哈希），与 O-R28-1 旧项一致。

---

**台账**：175→**178**（171 已修、2 部分按设计、1 未验 P0-1、新 3，全 P2：R35-P2-1／R35-P2-2／R35-P2-3、复发 0）。

---

## §7 审计环境事故

- **failpath 探针首版 1 格假红**：首版断言重跑日志含“keeping previously configured panel domain”，实为审计员误读——非 TTY 路径下旧域由 `_resolve_panel_domain` 直接返回，不走 :779 的回落分支，故无此 log 行；旧域确被取用（DNS log 行实证）。已修正断言为 DNS log 行，重跑 **8/8**。非产品问题，报告已修正，无残留影响。
- /tmp 未被清：R33 控制器重建的 venv（/tmp/r33v/venv）与 fixture（/tmp/r33f＋/tmp/fixture-server）全程在位，未重建。
- 探针输出含沙箱临时生成的管理员密码（r35_proxyfix_xff.py 首启打印，/tmp/r35/data0 与 data1 内），均为一次性测试数据，不在仓库、不在任何交付物内。

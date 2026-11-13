# AUDIT-R26 — 仓库消费者旅程全量审计（2026-11-13）

> 方法：repo-consumer journey（与 R25 的 repair-path convergence 不同）。沿新用户路径逐项核验：公开 clone → 由 clone 构建/安装 → 各功能实现 → 实际使用形态。只认行为实证，不认代码在场；夹具须用真机捕获的真实行；stub 语义与内核不符则结论作废。
> 审计树：`~/workspace/openvpn-sk5-panel/`，git main @ b395ef3（1.0 发布提交，与公开仓库一致）。
> 历史台账：R25 终点 163 条（已修 160、部分 2（按设计）、未验 1（P0-1 Cloudflare 真实部署））。

##  verdict：**不能交付**——差集 2 条（全 P2，文档族）

历史台账：163＋2 新＝**165 条**（已修 160、部分 2（按设计）、未验 1（P0-1）、新 2、复发 0）。两条新差集均为公开仓库化之后新增的文档漂移，无功能缺陷、无复发；门禁 29/29、§7 变异 11/11、全部探针套件按预期翻转外全绿。修复后须再做一轮全量回头看（AUDIT-R27）才准发新版。

## §0 审计基线与树状态

- 本地树：main @ b395ef3，`git status` 干净。
- 公开仓库：https://github.com/iiiiiiiii7125-art/openvpn-sk5-panel（public，2026-11-13 用户令公开）。
- 夹具：/tmp/r25 仍在（fixture-ca 含 ta.key、fixture-server server.conf port 1194 proto udp、venv Flask 3.1.3）；系统 python3 无 flask（预期）。

## §1 仓库消费者路径：公开 clone → 构建/安装

### §1.1 公开 clone（无认证）

- `git clone https://github.com/iiiiiiiii7125-art/openvpn-sk5-panel /tmp/r26-clone`：成功，HEAD = b395ef3，与本地树一致。

### §1.2 关键文件哈希（clone vs 1.0 发布包宣称值）

| 文件 | clone 实测 | 宣称 | 结论 |
|---|---|---|---|
| install.sh | 3f050f037e7a… | 3f050f037e7a… | ✓ |
| egress/sk5_manager.py | e209084f0915… | e209084f0915… | ✓ |
| egress/policy-routing.sh | fbfb29a49164… | fbfb29a49164… | ✓ |
| panel/app.py | 40868bbfd8b9… | 40868bbfd8b9… | ✓ |
| cloudflare/src/index.js | f43180976393… | f43180976393… | ✓ |
| agent/agent.py | f303af828555… | f303af828555… | ✓ |
| core/openvpn_manager.py | 3b5d7dfe9ea1… | 3b5d7dfe9ea1… | ✓ |

### §1.3 发布包 vs 新鲜 clone 逐字节比对

- `releases/ovpn-release-1.0.tar.gz` 解包后与 /tmp/r26-clone `diff -r`（排除 tests/、.gitignore、releases/）：唯一差异是包内空目录条目 `panel/data/`（空目录，无文件）。即：**发布包是公开 clone 的逐字节忠实子集**（仅排除 tests/ 33 个探针文件 + .gitignore + releases/ 自身），无注毒、无多余文件。
- 包内 92 条目（78 文件＋14 目录），sha256 `540fc8fc…` 与 sidecar 一致。

### §1.4 .gitignore hygiene

- `.gitignore` 含 `panel/data/`；`git ls-files` 114 文件中无 panel/data/ 内容；`panel/data/` 本地为空目录。R8-BUG-1 同族（入库 panel.db 销毁线上库）无复发。

### §1.5 全仓凭据扫描

- token 形（`gho_`/`ghp_`/`sk-`/`AKIA`/Slack token）：0 命中。
- IPRoyal：仅 `session-xxx`／`PASSWORD` 占位示例与 TEST-NET 文档 IP（198.51.100.9／203.0.113.7），无真实凭据。
- 硬编码口令形：0 命中（两处 `TOKEN="$(…)"` 均为运行时读取变量，非定值）。
- /etc/openvpn-sk5-panel/：空（探针泄漏 0 次，本轮跑前已是空目录）。

## §2 功能链审计（README / DELIVERY.md / security.md 逐项对行为）

### §2.1 文档与行为逐项对账（已完成）

- **README「本项目无公开 git 仓库，不走 `git clone`」——已过期，见差集 R26-P2-1。** 仓库已于 2026-11-13 08:43 由用户令公开；§1.1 实测公开 clone 正常。
- **DELIVERY §1.3「verify.sh 的 SK5 拨测会覆盖已填的 SK5 凭据…跑完须重填 SK5」——与行为不符，见差集 R26-P2-2。** verify.sh:644-645 守卫：已启用真实 SK5 时 toggle 三格 SKIP；且 toggle 跑时先备份 sk5.json／sing-box.json、cleanup（:103-108）原样恢复；默认路径下商家凭据不可能丢失。
- **DELIVERY §1.3「verify.sh（14 项端到端自检）」——项数过期。** verify.sh 实为 12 个编号节、24 个 distinct 检查名（`ok/bad/skip` 去重计数）；「14 项」既不是节数也不是格数。R10-P2-1 同族（过期数字）。
- DELIVERY §9 清单：78 文件＋14 目录＝92 条目 ✓；审计报告 25 份（AUDIT-R1–R25，包内实测 25）✓；live-verify 17 份 ✓；关键文件 sha256 前 12 位与 §1.2 实测一致 ✓。
- DELIVERY §9「门禁 `bash verify-integration.sh` 应为 PASS=29 FAIL=0 SKIP=0」——见 §3，实测 29/0/0 ✓。
- **install.sh clone 安全**：只按固定清单复制（`agent core egress panel systemd install.sh verify.sh verify-integration.sh README.md`，:469），无整树复制；panel/ 走 staging 且排除 data/（:501-504）。clone 里的 `.git/`、tests/、docs/、releases/、cloudflare/ 均不进 /opt。由 clone 安装与由 tarball 安装在复制层等价；完整 install.sh 全流程（apt＋systemd＋健康门禁）属 live 轮，不在沙箱口径内。
- **security.md 抽查**：默认口令字面量 `grep -rnw admin123|changeme|123456` 0 命中 ✓；初始密码 `secrets.token_urlsafe(16)`（app.py:320）✓；`SENT_MAX_RETRIES = 3` 双面（Flask app.py:603、Worker index.js:94）✓；13 动作白名单双面逐字一致（机械枚举）✓；ProxyFix 只在 `OVPN_TRUSTED_PROXY=1` 时开（app.py:182-183）✓；`set_sk5` 密码语义（None/空串保留、非空覆盖、`clear_password=true` 清除，sk5_manager.py:657+）✓；健康检查定时器 60 秒（`OnUnitActiveSec=60s`）✓；`enable()` 等活 tun1 10×0.5s＝5s、大声失败文案与 DELIVERY §6-4／§8 一致（sk5_manager.py:1145-1151）✓；panel README 的 `/api/sk5/fail-open` 与 `/api/sk5/udp-over-tcp` 两路由均在 app.py 实现（:2256／:2293）✓。
- server-mode.md 对照表：与代码一致（含 Flask/Worker 重投分歧的诚实标注，R5 已裁定非 bug；`SENT_MAX_RETRIES=3` 双面一致）✓。
### §2.2 功能矩阵（功能 → 行为证据；探针编号见 §4）

| 功能（README／DELIVERY 宣称） | 行为证据 | 结论 |
|---|---|---|
| OpenVPN UDP 1194 主／TCP 443 备 | Core 46/46（render 守卫、proto/port 校验）；install.sh OVPN_PROTO/OVPN_PORT 环境变量＋存量继承（:70-87） | ✓ 沙箱级；数据面属 live 轮 |
| 建用户／吊销／下载 .ovpn | Core 46/46（用户名校验、证书列举、client 配置渲染）；Flask 86/89（建用户、吊销、.ovpn 下载格均在 86 绿格内） | ✓ |
| SK5 启用／停用 | BM 22/22、BO 18/18、BS 9/9、BT 全过、R24 全过、R25 37/37 | ✓ |
| 断网保护 fail-closed（SK5 死即黑洞） | BM K1–K5（真实 netns＋真实 ip：空表落回主表 bug 复现、黑洞遮断、删 tun1 回落黑洞、flush 恢复直连） | ✓ |
| 健康检查 60 秒＋自愈 | 定时器 `OnUnitActiveSec=60s`；BM H1–H10（check_health 自愈逻辑）；BS 9/9（verdict 分流） | ✓ |
| 命令队列＋agent 5 秒 poll | R17 Flask／Worker；R21 6/6（BN 隔离审计）；BQ 6/6（不可读隔离） | ✓ |
| Flask＋Worker 双面 | R17 四套件；BR 11/11（loginfail 数组）；server-mode.md 分歧诚实标注 | ✓（Worker 真机部署仍 P0-1 未验） |
| 登录限流（IP 维 5/5 分钟→锁 15 分钟） | Flask IP_LOCK 序列格（86 绿格内）；Worker 限流格（33 绿格内）；BR 11/11（6 次错密→429、锁 15 分钟、Retry-After 900） | ✓ |
| 密码处理（bcrypt＋透明迁移＋改密） | security.md 抽查（§2.1）；Flask 改密格（86 绿格内）；Worker 改密 501（R11-P2-1 已修，Worker 33 绿格内） | ✓ |
| 重建 CA（force+confirm 双确认） | Flask F-cells（86 绿格内含 force/confirm 缺一即 400）；R17-P1-1 的 OBSERVED 格钉的是 poll 分派侧缺陷行为，非本功能缺陷 | ✓ |

### §2.3 未再发现

- 全仓搜「重填 SK5」／「cannot be restored」／「14 项」／「无公开」类表述的机械枚举见 §5 各条的范围段；除 §5 两条外无新增文档漂移。
- 历史 163 条关闭项：本轮探针重跑无一复发（§4）。

## §3 门禁（verify-integration.sh 29 格，串行）

- **PASS=29 FAIL=0 SKIP=0，exit 0**（2026-11-13，串行，树静止；日志 /tmp/r26-gate.log）。与 DELIVERY §9 宣称一致。
- §7 哈希钉死两层在门禁内（见 §3.1 变异）。

### §3.1 §7 变异（11/11 恰红 28/1，变异树由公开 clone 构建）

变异由 `tests/build-mutants.py /tmp/r26-clone /tmp/r26/gate-mutants` 生成（11 棵：m-char／m-const-sb／m-dict-extra／m-dict-missing／m-dict-sb／m-dict-ts／m-dict-x-a／m-dict-x-amd／m-dict-x-arm／m-dict-x-b／m-install-sb；C(4,2)=6 两两字典互换全集＋缺项／多项＋两层常量互换＋单字符）。逐棵串行跑门禁，**全部 PASS=28 FAIL=1 SKIP=0，仅 §7「钉死哈希不一致」一格红**（日志 /tmp/r26/gate-mutants-*.log）。门禁验活成立。

## §4 探针套件重跑（全部在 /tmp/r26/ptree＝公开 clone 副本上跑，fixture /tmp/r25，venv Flask 3.1.3）

| 套件 | 结果 | 备注 |
|---|---|---|
| R17 Flask | **86/89** | 仅预期 OBSERVED 翻转 F4-02b／F4-13／F4-15（R17-P1-1 缺陷钉死格） |
| R17 Core | **46/46** | |
| R17 Agent | **33/33** | |
| R17 Worker | **33/35** | 仅预期 OBSERVED 翻转 W5-05／W5-06a |
| BK（R20-P2-1 存量形状） | **8/8** | |
| BM（R13-BUG-1 黑洞自愈） | **22/22** | 真实 netns＋真实 ip |
| BO（R14-BUG-1 repair 动词） | **18/18** | |
| BP（R23-P2-1＋P2-2 boot restore） | **14/14** | |
| BQ（R23-P2-3 队列不可读） | **6/6** | nobody 身份 |
| BR（R23-P2-4 loginfail 数组） | **11/11** | |
| BS（R15-BUG-1 verdict） | **9/9** | |
| BT（R24-P2-1 无占位符） | **ALL PASS** | 真实 netns |
| R24（enable 占位符） | **ALL PASS** | 真实 netns |
| R25（repair 收敛） | **ALL PASS（37/37）** | 真实 netns |

探针调用口径：Flask 类一律 `runuser -u nobody`＋venv PYTHONPATH＋OPEN 前缀 env（`OPENVPN_CA_DIR`／`OPENVPN_SERVER_DIR`）＋`OVPN_SK5_CONFIG_DIR`；Worker 类 `node tests/*.mjs`。/etc/openvpn-sk5-panel/ 跑后仍为空（0 泄漏）。
历史关闭项行为重验：无一复发。

### §4.1 回归探针（R20–R23，补充）

| 套件 | 结果 | 备注 |
|---|---|---|
| R20（存量形状，审计钉） | 7 格中 S1/S2/S6 红 | **预期翻转**：三格钉的是缺陷本身，修复后行为为诚实 ValueError／HB-OK——缺陷已闭合，与 BK 8/8 互证 |
| R21（队列隔离审计） | **6/6** | |
| R22 Flask | **22/22** | |
| R22 Worker | **12/12** | |
| R23 Flask | **13/13** | |
| R23 Worker | **9/9** | |

### §4.2 探针调用事故

- 首跑 R17 Worker 时 `ERR_MODULE_NOT_FOUND`：我自建的 /tmp/r26/ptree 漏拷 `cloudflare/`（Worker 探针相对 import `../cloudflare/src/index.js`）。补拷后 33/35。属审计员调用失误，非产品问题。

## §5 差集（新发现）

### R26-P2-1（P2，文档族）——README「无公开仓库」宣称已过期，clone 安装路径无文档

- **机制**：仓库已于 2026-11-13 08:43 由用户令公开（https://github.com/iiiiiiiii7125-art/openvpn-sk5-panel），但 README「一键安装」节仍写「本项目无公开 git 仓库，不走 `git clone`：把整个 `openvpn-sk5-panel/` 目录拷到目标机（`scp -r` / `rsync` 任选）」。DELIVERY §1.2 同样只写 scp 传包。**本轮方法（repo-consumer journey）的首要路径——公开 clone → 由 clone 安装——在两份入口文档里均无记载**，GitHub 到达的新用户无从得知可直接 clone 安装。
- **证据**：§1.1 公开 clone 成功（HEAD b395ef3）；README:（一键安装节）原文可查；DELIVERY §1.2 只写 scp。
- **范围（机械推导，闭合）**：全仓搜「无公开」／「不走 git clone」／「scp -r」——仅 README.md:55（＋:58 同段 scp -r 命令）为活宣称；AUDIT-R8.md:220 是引用旧状态的历史审计记录，不改。DELIVERY §1.2 未写「无公开」但只给 scp 传包，同改（clone 为主路径、scp 降为备选）。同时须实测 clone 树安装（install.sh 是否误抄 `.git/`、tests/ 等）——§2.1 已验：固定清单复制，`.git/` 不进 /opt。不是 R10-P2-1／R15-P2-2 的复发（不同宣称），是新公开状态下新增的文档漂移同族。
- **修法**：README + DELIVERY 改为 clone 为主路径（`git clone https://github.com/iiiiiiiii7125-art/openvpn-sk5-panel` 后 `bash install.sh`），scp 传包降为备选；install.sh 若存在整树复制须排除 `.git`。

### R26-P2-2（P2，文档族）——DELIVERY §1.3 对 verify.sh 的 SK5 警告与行为相反

- **机制**：DELIVERY §1.3 写「verify.sh 的 SK5 拨测会覆盖已填的 SK5 凭据——已在面板里填了真实 SK5 后不要跑 verify.sh；跑完须重填 SK5」。实际行为：verify.sh:644-645 守卫——已启用真实 SK5 时 `sk5-toggle`／`sk5-egress-ip`／`sk5-disable` 三格 SKIP（`VERIFY_ALLOW_OVERWRITE_SK5=1` 才强制）；toggle 跑时先备份 sk5.json＋sing-box.json（:651-652），cleanup（:103-108）原样恢复。**默认路径下商家凭据不可能被覆盖；即使强制路径也被备份恢复**。同款过时说法亦见 verify.sh 头部注释（:41-46「cannot be restored afterwards」）与 README 自检节（「事后须在面板重填 SK5 密码」）。
- **证据**：verify.sh:41-46、:103-108、:594-595、:644-645 全文已读；README 自检节与 DELIVERY §1.3 原文已对。
- **用户影响**：「不要跑 verify.sh」的误导会让已部署用户不敢跑自检；「须重填」是假成本。
- **范围（机械推导，闭合）**：全仓搜「重填 SK5」／「cannot be restored」／「不要跑 verify.sh」／「14 项」——仅三处活表述：README.md:171（「事后须在面板重填 SK5 密码」）、verify.sh:41-46 头部注释（「cannot be restored afterwards」）、DELIVERY.md:36（覆盖警告＋「14 项」）。逐处按真实行为改（SKIP 守卫＋备份恢复；项数改为 12 节 24 格或删数字）。不是 R10-P2-1／R15-P2-2 的复发（不同宣称），是同一文档漂移族的新成员。
- **修法**：三处统一改写为「已启用真实 SK5 时 toggle 三格自动 SKIP，不覆盖；强制须显式 `VERIFY_ALLOW_OVERWRITE_SK5=1`，且脚本会备份并恢复 sk5.json」。

## §6 未验与观察

- P0-1（站立未验）：Cloudflare Worker 真实部署——本轮仍无真实部署可验，不冒充。Worker 面只跑 mock-KV 探针。wrangler.toml KV id 仍为占位符（`REPLACE_WITH_KV_NAMESPACE_ID`／`REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID`）；本机无 wrangler，未重跑 `--dry-run`（树与 R25 审计提交 b395ef3 字节一致，R25 的 dry-run 结论仍适用）。
- arm64 真机安装：无 arm64 机，仍未验（§7 哈希绑定只在沙箱变异树上验）。
- SK5 端口 1001 vs 9000：用户仍未确认，面板默认 1001。
- O-R26-1（观察，不立案）：审计期间树内出现未跟踪文件 `docs/live-verify-R18.md`（另一路 live 工作落盘，非本轮审计对象、未纳入 verdict 依据）。本轮 verdict 只针对提交 b395ef3。
- O-R26-2（观察，不立案）：完整 install.sh 全流程（apt＋systemd＋健康门禁）未在沙箱跑——沙箱无 systemd 运行环境，属 live 轮口径；clone 安装在复制层已验等价（§2.1）。

## §7 审计方法与证据

- 探针一律在 /tmp 树副本＋venv＋nobody 身份下跑，env 名用 OPEN 前缀（`OPENVPN_CA_DIR`／`OPENVPN_SERVER_DIR`）＋`OVPN_SK5_CONFIG_DIR`。
- 沙箱 UDP/TUN EPERM 为环境假象，不作产品结论；数据面结论属 live 轮。

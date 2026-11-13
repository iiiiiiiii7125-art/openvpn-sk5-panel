# AUDIT-R2 — OpenVPN + SK5 面板 · 交付前全量全局回头看

- 审计员：独立复审路（未参与建设与修复路 A–E）
- 日期：2026-11-12
- 方法：**行为/流程推导**（与 R1 的逐文件通读 + 接口对账不同）。从用户旅程推导全集（全新安装 → 登录 → 建服务 → 建用户 → 下 .ovpn → 客户端连接 → 填 SK5 → 一键启用 → 面板自测 → 杀 SK5 → 重启 → 重跑安装 → Cloudflare 全旅程 → agent 全旅程），每节点机械枚举代码路径逐个实证；R1 33 条 + live 9 bug 按原报告复现步骤重跑；八大家族机械复扫；两门禁变异验活。
- 范围：项目树 34 文件 / 11235 行（R1 时 8089 行）。语法全绿（py_compile 4 个 Python 文件、bash -n 7 个脚本、node --check Worker）。
- 测试隔离：全部测试在 /tmp 副本（/tmp/audit2、/tmp/audit2-mut、/tmp/audit2-mut2、/tmp/audit2-tests）上跑，未改项目原文件、未动 /etc（除本审计 harness 自身在 /etc 落下的文件，见末尾“审计副作用”）、未动真机。

## 裁决（一句话）

**不能交付。** 必须先修 R2-P1-1（BUG-9 未真修：默认 v1 日志仍解析出 0 在线用户）、R2-P1-2（改密有 API 无 UI）、R2-P1-3（旧 CN=OpenVPN-CA 存量证书修后无法管理）、R2-P1-4 / R2-P1-5（两门禁对关键路径零覆盖），修完再做一轮全量复验；P2 项可随同版修，不阻断但须登记。

## 新 finding 汇总

| 编号 | 严重度 | 一句话 |
|---|---|---|
| R2-P1-1 | P1 | BUG-9 未真修：默认 v1 状态日志 5 字段行被解析器丢弃，online_users 恒 0；v2 字段错位一位 |
| R2-P1-2 | P1 | 改密 API 已有，前端无入口，用户实际改不了密码；install.sh 仍印“面板没有改密接口” |
| R2-P1-3 | P1 | 旧 CN=OpenVPN-CA 存量证书修后三路全堵：列表看不见、吊销报不存在、重建报已存在 |
| R2-P1-4 | P1 | verify-integration.sh 从不以已登录身份调 /api/status：变异 status 恒 500 后仍 18/1 |
| R2-P1-5 | P1 | verify.sh “files” 检查漏列 healthcheck/policy 单元：删 timer 文件仍 PASS |
| R2-P2-1 | P2 | verify-integration.sh 的 /etc 隔离检查是存在性判定：任一既存 admin.pass 即 FAIL |
| R2-P2-2 | P2 | OVPN_PANEL_DATA_DIR 全树无人认；直接 import app.py 即把 panel.db 写进项目树；树内无 .gitignore |
| R2-P2-3 | P2 | README.md:194 仍称哈希“不写死进脚本”，与 install.sh:54-57 已钉死四哈希矛盾 |
| R2-P2-4 | P2 | server-mode.md 面板/agent 地址写 http://，实际面板只跑 HTTPS |
| R2-P2-5 | P2 | flmx-reference.md §1-13/§103 残留“Flask 尚未提供 /install-agent.sh.sha256”，端点已存在 |
| R2-P2-6 | P2 | verify.sh sing-box-config 报错误导：文件存在、缺的是二进制，却报“no sing-box.json to check” |
| R2-P2-7 | P2 | fail-open 单向性未写明：fail-over 后 enabled=False，须人工重开才恢复 |
| R2-P2-8 | P2 | install.sh 首装 starter sing-box 配置是手写 heredoc，与模板双份维护，必漂移 |

---

## R2-P1-1 — BUG-9 未真修：默认 v1 状态日志解析出 0 客户端（E 路测试夹具失真同族）

- 文件：`core/openvpn_manager.py:643-677`（`_parse_status_log`）、`core/server.conf.template:40`、`panel/app.py:929-939`
- 机制族：在线用户解析（BUG-9）
- 复现（本审计独立推导，未复用 E 路脚本；v1/v2 行形取自 OpenVPN 2.6 实际输出格式，live-verify §5 的真实 CLIENT_LIST 字段为佐证）：
  - `server.conf.template:40` 只写 `status /var/log/openvpn/openvpn-status.log`，无 `--status-version 2`，守护进程写 **v1 格式**。v1 CLIENT_LIST 数据行是 5 字段：`alice,10.200.0.2:43223,5011,4020,Thu Nov 12 00:32:42 2026`（CN、Real Address、Bytes Rx、Bytes Tx、Connected Since，**无 Virtual Address 列**；虚拟地址只在 ROUTING TABLE 段）。
  - 解析器要求 `len(parts) >= 7` 且按 `[1]CN [2]real [3]virtual [4]rx [5]tx [6]since` 映射。实测（`/tmp/audit2-tests/core/test_status.py`，调 `_parse_status_log` 本体）：
    - v1 真实行 → `[]`，online_users 恒 0。**BUG-9 在部署的默认配置下原样复发。**
    - v2 真实行（含 Virtual IPv6 Address 空列）→ 客户端列得出，但字段错位一位：`bytes_received=''`、`bytes_sent='5011'`（实为 rx）、`connected_since='4020'`（实为 tx）。解析器按无 IPv6 列的 v2 形写，与 OpenVPN ≥2.4 的 14 列 v2 不符。
  - 接线确认：`panel/app.py:939` `online_users = len(clients)`，`clients` 即 `_parse_status_log` 返回；`server_status()` 只在 `running` 时读日志。
- 根因：E 路的“v1/v2 均解析出 online_users=1”建立在非真实夹具上（7 字段“v1”行、无 IPv6 列的“v2”行）——与 LIVE-215 手写 sing-box 行形夹具同族错误。主控重跑 E 路 core 测试时撞上的 crl.pem 缺失，进一步说明其 harness 不可信；本审计未复用其任何脚本。
- 修复方向：v1 按 5 字段解析并用 ROUTING TABLE 段补虚拟地址；v2 按 14 列（含 IPv6 列）映射；回归夹具必须用 OpenVPN 真实输出行形。

## R2-P1-2 — 改密有 API 无 UI，用户实际改不了密码

- 文件：`panel/app.py:837-873`（`POST /api/change-password`，本审计 Flask 套件已验：旧密码改后 401、新密码可用）、`panel/templates/index.html`（全文 0 处 `change-password` / `改密` / `修改密码`）、`install.sh` 总结段。
- 复现：`grep -n "change-password\|改密" panel/templates/index.html` → 0 命中；`install.sh` 总结仍印“面板没有改密接口，请妥善保存”。
- 影响：R1 P1-7（无改密接口）的修复只落了一半——API 存在但面板用户触不到；安装总结还主动告诉用户该功能不存在。初始随机密码一旦泄露，用户无自助改密路径。
- 修复方向：前端加改密入口（调已有 API）；install.sh 总结文案同步。

## R2-P1-3 — 旧 CN=OpenVPN-CA 存量证书修后三路全堵

- 文件：`core/openvpn_manager.py:225-273`（`_parse_index_txt` 过滤 `RESERVED_NAMES={"server","openvpn-ca"}`）、`core/openvpn_manager.py:462-467`（`create_user`）、`506-514`（`revoke_user`）、`core/easyrsa.sh:99`
- 复现（本审计独立推导；index.txt 行形取 Easy-RSA 真实格式，TAB 分隔）：
  - 修复前签发的用户证书在 `pki/index.txt` 里是 `/CN=OpenVPN-CA`；修复后 `_parse_index_txt` 按 CN 过滤，`_user_status(旧用户名)` 恒为 None。
  - `revoke_user(旧用户)` → `OpenVPNError("user ... does not exist")`：**活证书无法经面板吊销**（安全相关）。
  - `create_user(旧用户)` → `_user_status` 为 None，不清 stale 文件 → `easyrsa.sh build-client` 因 `issued/<name>.crt` 已存在而拒绝 → 报错；`list_users` 也看不见该用户。
  - 活例：live-verify 的 `liveuser` 证书正是此状态（CN=OpenVPN-CA，测试机现存）。
- 修复方向：按文件名/序列号而非仅 CN 识别用户，或提供一次性迁移（重签旧用户证书并登记），并在发版说明里点名。

## R2-P1-4 — verify-integration.sh 从不以已登录身份调 /api/status（门禁盲区）

- 文件：`verify-integration.sh:103-104`（全脚本唯一一次 `/api/status` 调用，未登录、期望 401）、`panel/app.py:929`（`status()`）
- 变异实证：复制树到 `/tmp/audit2-mut`，把 `status()` 改为恒返回 500（`{"error":"MUTATED"}`），重跑门禁：**仍 PASS=18 FAIL=1**，与基线完全相同。`@login_required` 在未登录请求上先回 401，变异体根本没执行；而已登录 happy path全脚本无任何调用。
- 影响：状态端点彻底坏掉也能全绿出门。P1-1（/api/status 耗时）与 R2-P1-1（online_users）这类回归，门禁一个都拦不住。
- 修复方向：门禁加“登录后 GET /api/status 期望 200 且含 openvpn/sk5/egress 键”一格；变异测试入常驻回归。

## R2-P1-5 — verify.sh “files” 检查漏列 healthcheck/policy 单元（门禁盲区）

- 文件：`verify.sh:126-138`（检查清单只含 `openvpn-sk5-panel.service` 与 `openvpn-sk5-singbox.service`，共 5 个单元文件只列 2 个）、`systemd/`（5 个单元：panel、singbox、policy、healthcheck service+timer）
- 变异实证：复制树到 `/tmp/audit2-mut2`，删 `systemd/openvpn-sk5-healthcheck.timer` 后重跑：**“files” 仍 PASS**（“both systemd units … present”）；对照变异删在清单内的 `panel/requirements.txt` → 立即 FAIL。说明检查本身对未列文件失明，且 PASS 文案“both systemd units”已错（实际 5 个）。
- 影响：P1-8 的 fail-open 定时器单元丢了也验不出来；“files” 格的宣称覆盖大于实际覆盖。
- 修复方向：清单补齐 5 个单元 + `agent/agent.py`、`panel/templates/index.html`、两模板与 `egress/test-egress.sh`；文案按实际清单写。

## R2-P2-1 — verify-integration.sh 的 /etc 隔离检查是存在性判定

- 文件：`verify-integration.sh:90-91`（`[ -f /etc/openvpn-sk5-panel/admin.pass ] && bad`）
- 实证：本审计基线 `PASS=18 FAIL=1`，唯一 FAIL 就是这一格；而 `/etc/openvpn-sk5-panel/admin.pass` 是本审计 Flask harness 早先以 root 身份跑 `_ensure_admin_password()` 落下的（01:06），本次门禁运行（nobody 身份，/etc 目录 770 root）根本写不进去，且密码确实落到了副本 `data/admin.pass`。检查分不清“本次写了”与“早已存在”——任何跑过一次面板的机器上该格恒 FAIL。
- 修复方向：改为跑前/跑后快照比对（mtime 或哈希），或只在本次运行新建时判 FAIL。

## R2-P2-2 — OVPN_PANEL_DATA_DIR 全树无人认；import 即污染项目树；无 .gitignore

- 文件：`panel/app.py:89`（`DATA_DIR = os.path.join(BASE_DIR, "data")`，无 env 覆盖）、`install.sh`、`verify-integration.sh`（均不设该变量）、树内无 `.gitignore`
- 实证：本审计 Flask harness 直接 import `panel/app.py` 后，`/tmp/audit2/panel/data/panel.db`（32KB）落进审计副本；随后 `verify-integration.sh` 抄树时把带 admin 行的旧库一并抄走，`_ensure_admin_password()` 因行已存在而提前返回、不写 `admin.pass`，门禁一度跑出 **PASS=8 FAIL=8**（登录 401 连锁）。删该文件后恢复 18/1。另：`_secret_path()` 回退分支在无 /etc 密钥时会在 `panel/data/secret.key` 写新密钥，树内无 `.gitignore` 兜底，存在被提交/发货的路径。
- 修复方向：`app.py` 认 `OVPN_PANEL_DATA_DIR`（或 `OVPN_PANEL_SECRET_PATH` 同款 env 优先）；补 `.gitignore` 钉 `panel/data/`；门禁抄树前清空 `panel/data/`。

## R2-P2-3 — README.md:194 仍称哈希“不写死进脚本”

- 文件：`README.md:194`（“本次集成在会话内无法从独立来源核实到 1.11.15 tarball 的 sha256，所以不把未经核实的哈希写死进脚本”）vs `install.sh:54-57`（四哈希已钉死并与 `agent/agent.py:122-132` 逐字节一致，见家族复扫）。
- 修复方向：该段改写为当前口径（env > 钉死哈希 > manifest，fail-closed）。

## R2-P2-4 — server-mode.md 面板/agent 地址写 http://，实际只跑 HTTPS

- 文件：`cloudflare/server-mode.md`（面板地址 `http://<服务器 IP>:8443`、agent poll/report `http://…:8443/api/agent/*`，共 2 处）vs `install.sh`（`run-panel-tls.py` 以 `ssl_context=(CERT, KEY)` 起面板）、`verify.sh`（`https://127.0.0.1:8443`）、BUG-5 自签证书 e2e。
- 修复方向：两处改为 `https://`，并注明自签证书与 `--ca-cert`/TOFU。

## R2-P2-5 — flmx-reference.md §1-13/§103 残留已不存在的待补项

- 文件：`docs/flmx-reference.md:40,103`（“残留：Flask 侧尚未提供 `/install-agent.sh.sha256` 端点”）vs `panel/app.py:1741`（端点已存在，主控已验哈希与脚本字节相符）。
- 修复方向：该残留句删除或改为已补。

## R2-P2-6 — verify.sh sing-box-config 报错误导

- 文件：`verify.sh:165-177`（`[ -f sing-box.json ] && command -v sing-box` 否则报 “no …/sing-box.json to check”）
- 实证：沙箱基线中 `/etc/openvpn-sk5-panel/sing-box.json` 存在（1141 字节），缺的是 PATH 里的 sing-box 二进制，报错却称文件不存在。排障时会被误导去查文件。
- 修复方向：分两支报错（缺文件 / 缺二进制各说各的）。

## R2-P2-7 — fail-open 单向性未写明

- 文件：`egress/sk5_manager.py:714-751`（`check_health()` fail-open 时调 `disable()`，`enabled` 写 False 存盘；之后 `check_health` 因未启用只报 `chain_disabled`，不再自动恢复）、`README.md:149-151`（只说“撤掉 table 100”，未说须人工重开）。
- 影响：行为本身安全（不静默回切），但用户按文档会以为 SK5 恢复后自动回链——实际须手动再启用。
- 修复方向：README 补一句“fail-over 后须在面板手动重新启用”。

## R2-P2-8 — install.sh 首装 starter 配置是手写 heredoc，与模板双份维护

- 文件：`install.sh:430-452`（`cat > $CONFIG_DIR/sing-box.json <<'EOF'` 手写 starter）vs `egress/sing-box.json.template`（面板重渲染用模板）
- 影响：模板日后修一处（如 BUG-1 的 `address` 字段），首装直连模式仍用 heredoc 旧版，直到首次 SK5 保存才被模板覆盖；两份 tun 段已靠人工同步。
- 修复方向：首装也从模板渲染（或 heredoc 加注释钉“改模板必同步此处”并入一致性门禁）。

---

## R1 33 条逐条复验（实证口径）

| R1 | 结论 | 实证 |
|---|---|---|
| P0-1 | 修好 | Worker 套件 W7：create_user → 202 无 ovpn_url，轮询 /api/cmd/:id 见 queued；apiWait + waitCmd（120s、done/failed/超时三路）代码核对一致 |
| P0-2 | 修好 | W4：无已存配置 fail-open → 400；有已存 → 202 且下发命令含完整 host+port |
| P0-3 | 修好 | W6：无 origin 时 bundle/install-agent.sh → 503（非 404）；有 origin → 200；篡改包 → 502 fail-closed |
| P0-4 | 修好 | Flask 套件 23/23：空密码保存保留已存、clear_password=true 清空；Worker W5 同款 |
| P0-5 | 修好 | 树内无 secret.key；发货哈希常量与 R1 值一致、命中即强制轮换；install.sh 在 /etc 生成新 0600 密钥并删树内副本 |
| P1-1 | 修好 | 静默 SOCKS 下 /api/status 首调 10.9s、二次 1.06s（缓存）；原 20s |
| P1-2 | 修好 | 前端 7 处 /api/nodes 引用（注册/轮换/吊销/安装命令/命令记录），节点页真实存在 |
| P1-3 | 修好 | W1：6 次错密码 → 429 + Retry-After，正确密码锁定中仍 429，他 IP 不受影响 |
| P1-4 | 修好 | W2：注册 201 token 只返一次、KV 不存明文；轮换后旧 token 401；吊销后 token 401 |
| P1-5 | 修好 | W3（重写为完整 agent 周期后）：report 上报 flat 结果 → 快照 online_users=clients 长度、egress.ip 归一、proto/port 取自 servercfg。注：首次 W3 种子直接把原始结果塞进 `status:` 键是失真写法，已废弃重写；`cachedStatus` 读 `status:` 不做二次归一化，旧形快照须等下次上报才刷新 |
| P1-6 | 修好 | Flask 套件：sent 态超时重投 retries=1 回队，第 4 次超时标 failed |
| P1-7 | **半修** | API 修好（改密后旧密码 401、新密码可用，会话全失效）；但前端无入口 → 见 R2-P1-2 |
| P1-8 | 修好（代码） | timer 60s + service 调 `sk5_manager.py health`；`check_health` 按 fail_open 开关走 fail-over/blackhole，health.json 0600 原子写。真机定时触发未验 |
| P1-9 | 修好（代码） | 重跑保留已渲染 sing-box.json；policy.service 开机调 `policy-routing.sh restore`（仅 enabled 时恢复） |
| P1-10 | 修好（代码） | `build_server_cert` 全套件在即跳过、缺件先清 stale 再建；easy-rsa 真机行为未验（沙箱无 easy-rsa） |
| P1-11 | 修好（代码） | `_port_occupant` bind 探针（无 SO_REUSEADDR）；建服务即查，已建后 proto/port 钉死，改口须显式 allow |
| P1-12 | 修好 | UoT 探针 mkdtemp 0700 + 配置 0600 + 每探针独立端口，finally 杀进程删目录 |
| P1-13 | 修好（代码） | systemctl 全带 timeout=10、OSError/TimeoutExpired 兜底，`_systemctl` 永不抛 |
| P1-14 | 余 P2 | server-mode.md 大部已对齐；残留 http:// 地址 → R2-P2-4 |
| P1-15 | 修好 | README 改称全量覆盖；三端语义实测一致（Wire 层全量、manager 层部分合并为安全网） |
| P2-1 | 修好 | 限流进 SQLite + OVPN_TRUSTED_PROXY |
| P2-2 | 修好 | agent 钉 SINGBOX_VERSION=1.11.15，已装不符即重装 |
| P2-3 | 修好 | agent --once 轮询失败 exit 1（BUG-5 e2e 同场验证） |
| P2-4 | 修好 | 两份不同顺序的 bundle 字节一致；bundle.sha256 与包体相符 |
| P2-5 | 修好 | DB 中 bcrypt `$2b$` 哈希；旧 SHA-256 透明迁移 |
| P2-6 | 修好 | OVPN_DNS 接线 core/install.sh/模板三处一致 |
| P2-7 | 修好 | PANEL_ADMIN_PASSWORD_FILE 已从 panel.env 删除；健康门禁读同一硬编码路径 |
| P2-8 | 修好 | 登录体写 0600 文件 + `--data @file`，无 curl -d 密码 |
| P2-9 | 修好 | agent `init_pki force=true` 须并传 `confirm=true`，否则拒 |
| P2-10 | 修好 | 已吊销下载 403、有效 200、未知 404 |
| P2-11 | 修好 | UoT 临时目录唯一化（见 P1-12）；manifest 无条目时试下一份再拒 |
| P2-12 | 余 P2 | security.md 旧宣称已清、README bundle.sha256 已同步；新残留见 R2-P2-3 |
| P2-13 | 余 P2 | 0-2/1-10/1-25/1-4/1-17 已落实；1-13 残留句已过时 → R2-P2-5 |

## Live 9 bug 逐条复验

| Live | 结论 | 实证 |
|---|---|---|
| BUG-1 | 修好 | 真实 sing-box 1.11.15 二进制（/tmp/d-anchors，sha256 前缀 a85f1a82…，自报 1.11.15）对 `_render_singbox_config` 渲染的 native 与 UoT 两版配置 `sing-box check` 均 exit 0；模板全树无 `inet4_address` |
| BUG-2 | 修好 | 四哈希 install.sh 与 agent.py 逐字节一致；`_expected_sha256` env > 钉死 > manifest > raise，fail-closed；版本号 1.11.15/2.7.0 三处一致 |
| BUG-3 | 修好（代码） | `wait_steady_active`：is-active + MainPID 存活 + tun 设备 + 5s 稳定 + NRestarts==0；panel 单元只有 /api/me 探针、无 steady 门（小缺口，见下） |
| BUG-4 | 修好 | 真实格式 index.txt：list_users 只出 alice/bob/carol，CA 与 server 被滤，revoked 状态正确 |
| BUG-5 | 修好 | 独立 e2e（自签面板 + agent --once）：无信任 exit 1 CERTIFICATE_VERIFY_FAILED；--ca-cert exit 0；--insecure exit 0 带警告 |
| BUG-6 | 代码已验，真机未验 | install-agent.sh:328 reset-failed、:333-337 已运行则 restart、:344 事后 is-active 判活；沙箱禁动 /etc/systemd，未在真 systemd 上跑 |
| BUG-7 | 修好 | 桩 easyrsa 记录每命令 CN：build-ca=OpenVPN-CA、server=server、alice=alice、bob=bob；全局 export 已删。存量迁移问题见 R2-P1-3 |
| BUG-8 | 修好（代码） | install.sh 两条 FORWARD 规则 -C 幂等 + netfilter-persistent 落盘 + 健康门禁核对规则与 VPN 源路由；policy-routing.sh tun0↔tun1 规则同款幂等 |
| BUG-9 | **未修** | 见 R2-P1-1：v1 → []，v2 字段错位 |

## 八大家族机械复扫（差集）

| 家族 | 枚举口径 | 命中 | 结论 | 差集 |
|---|---|---|---|---|
| 钉死哈希 | `SINGBOX/TUN2SOCKS_VERSION` 与 4 哈希在 install.sh/agent.py/文档 | 版本 2 处、哈希 8 处（4×2） | 全部一致；env 覆盖为严格 64-hex，不绕过 fail-closed；升级须同步改版本+哈希（README 有钉） | ∅（文档残留另见 R2-P2-3） |
| FORWARD 规则 | 全树 `FORWARD` 引用 | install.sh 2 条、policy-routing.sh 2 条 + INPUT/OUTPUT 各 1、verify.sh 核对 2 条、install.sh 健康门禁 2 条 | 全部 -C 幂等、落盘、门禁核对；Docker-USER 顺序无冲突（-I 插链首，ACCEPT 先行） | ∅ |
| TOFU 证书钉死 | 全树 `ca_cert`/`insecure` | agent.py 12 处、install-agent.sh 14 处、README 2 处 | 默认校验、--insecure 显式且警告；面板换证后须 `--force` 重钉（README 有载）；钉死过期即 fail-closed（无静默降级） | ∅ |
| CN 修复 | 全树 `EASYRSA_REQ_CN` | 3 处内联（build-ca/server/client）+ 注释 | 无全局 export；行为级验证通过（见 BUG-7） | **≠ ∅：旧存量迁移见 R2-P1-3** |
| 密钥移出树 | 全树 `secret.key`/`_secret_path` | app.py 12 处、install.sh 5 处、security.md 1 处 | /etc 优先、env 覆盖、发货值轮换、安装器删树内副本 | ∅（回退路径可写树内，见 R2-P2-2） |
| 202 轮询 | 全树 `202`/`apiWait`/`waitCmd` | 前端 apiWait 1 + waitCmd 1（120s/2s 轮询、done/failed/超时）+ 全部写操作走 apiWait；`api()` 对 `!res.ok \|\| ok===false` 抛错 | Flask 与 Worker 语义一致；超时 120s 与 agent sent 120s 对齐 | ∅ |
| set_sk5 部分合并 | 三端 set_sk5 | manager（部分合并，空密码保留、clear_password 清）、Flask（缺/空密码顶替已存）、Worker（先读已存补全量再发）、agent（透传） | 三端同一语义；单字段开关三路均不丢 host/port | ∅ |
| 健康检查 | timer/service/check_health | timer 60s、service oneshot、check_health 三分支（none/failed_over_to_direct/blackholed_kill_switch）、health.json 0600 | 按面板开关走；fail-open 调 disable() 恢复直连；kill-switch 留表黑洞 | ∅（单向性文档缺口见 R2-P2-7） |

**复扫差集：不为 ∅。** 唯一未闭合项是 CN 家族的旧存量迁移（R2-P1-3）。

## 门禁变异验活

| 门禁 | 基线（本审计实测） | 变异 | 结果 |
|---|---|---|---|
| verify-integration.sh | PASS=18 FAIL=1 SKIP=0（唯一 FAIL 是 R2-P2-1 的 /etc 存在性误报；清掉本审计 harness 污染的 panel.db 后从 8/8 恢复） | /api/status 恒 500 | **不变红（仍 18/1）** → R2-P1-4 |
| verify.sh（沙箱） | PASS=3 FAIL=5 SKIP=10（FAIL 皆为沙箱缺二进制/面板未起的环境缺口，诚实） | 删 `systemd/openvpn-sk5-healthcheck.timer` | **“files” 不变红** → R2-P1-5；对照变异删清单内 `panel/requirements.txt` → 立即 FAIL，证明检查本身对清单内文件有效 |

## 本审计的诚实边界（未验项）

- 真机数据面（S1–S4 流量、杀 SK5 断网保护、重启后策略恢复）未重跑：沙箱无 openvpn/sing-box 守护进程、UDP sendto 一律 EPERM；BUG-3/BUG-6/BUG-8/P1-8/P1-9 标“代码已验”的项须在 Lightsail 真机上补跑后才算闭环。
- Cloudflare 未真实 `wrangler deploy`：Worker 结论来自本审计自写 mock KV + mock origin 套件（29/29），非线上 Worker；KV id 仍是占位符。
- Easy-RSA 真二进制未跑：BUG-7 用桩 easyrsa 验证变量作用域（记录每命令收到的 CN），未验证真实签发出的证书 subject。
- BUG-3 的 panel 单元无 steady 门：`wait_steady_active` 只用于 openvpn/sing-box 两单元，panel 只凭 /api/me 探针——panel 进程崩溃重启循环时安装仍报完成（P2，未单独立案，随 R2-P1-5 的门禁补齐一并处理为宜）。

## 审计副作用（须主控知晓）

- 本审计 Flask harness 以 root 身份 import `panel/app.py` 时在沙箱 `/etc/openvpn-sk5-panel/` 落下 `admin.pass`（随机密码）、`secret.key`、`sk5.json`、`sing-box.json`（01:06）；另在审计副本 `/tmp/audit2/panel/data/` 写下 `panel.db`（已删）。任务禁动 /etc，故 /etc 的四个文件未清——它们是本审计的污染，不是产品部署态；下次跑 verify-integration.sh 前须先清，否则 R2-P2-1 的误报格继续红。
- 测试产物：`/tmp/audit2-tests/`（Flask 套件 23/23、Worker 套件 29/29、core 状态日志/索引测试、BUG-5 e2e 假面板、渲染配置）、`/tmp/audit2`（审计副本）、`/tmp/audit2-mut`（status 变异）、`/tmp/audit2-mut2`（files 变异）。

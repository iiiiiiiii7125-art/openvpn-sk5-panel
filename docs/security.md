# 安全清单（FLMX 教训对齐）

## 已落地

| 项 | 实现位置 | 口径 |
|---|---|---|
| 默认口令已删 | `panel/app.py` `_ensure_admin_password` | 代码里没有任何默认管理员用户名/口令字面量。首次启动生成 `secrets.token_urlsafe(16)`，只写 `/etc/openvpn-sk5-panel/admin.pass`（0600）并在启动日志打印一次；DB 里只存 bcrypt 哈希（P2-5，与 FLMX 对齐；旧 salt+SHA-256 存量在登录成功时透明迁移到 bcrypt，迁移后旧哈希作废；bcrypt 未安装的极简环境回落旧哈希）。`grep -rnw "admin123\|changeme\|123456" panel/ agent/` 应为零命中（`-w` 词界：`agent/agent.py` 的 hex 字符集 `"0123456789abcdef"` 含 `123456` 子串，不带词界会误报）。 |
| 会话密钥防发货值 | `panel/app.py` `_load_or_create_secret` | `panel/data/secret.key` 不再随项目树发货（P0-5，已删除）。启动时若读到的文件恰好是曾发货的密钥值（按 SHA-256 识别），立即强制轮换并打印警告；每次加载都把文件权限收紧到 0600。 |
| 登录限流 | `panel/app.py` `_record_login_failure` + SQLite `login_attempts` 表 | 同一 IP 5 分钟内 5 次失败即锁 15 分钟；锁定期间登录返回 429 + `Retry-After` 头；成功登录清零。计数进 SQLite，面板重启/进程重建后仍锁定（P2-1）。限流以连接 IP 为准；面板前挂反代时，只有显式置 `OVPN_TRUSTED_PROXY=1` 才信任 `X-Forwarded-For`（ProxyFix），默认不信任任何头——否则伪造 XFF 即可绕过限流。 |
| 会话 | `panel/app.py` Flask 配置 | Cookie 恒为 `HttpOnly` + `SameSite=Lax`，有效期 12 小时；`Secure` 标记只在 `OVPN_PANEL_HTTPS=1` 时开（面板本体是明文 8443，前面挂 TLS 反代/wrapper 时置 1；本机明文调试保持 0，否则浏览器会丢会话）。管理接口未登录一律 401。改密后 `session_version` +1，全部旧会话立即失效（P1-7）。 |
| 改密 | `panel/app.py` `POST /api/change-password` | 须登录 + 旧密码正确；新密码 ≥12 字符且同时含字母和数字、与旧密码不同。成功后全部旧会话作废（含本次，须重新登录），初始密码文件（若存在）同步更新为新密码。**仅服务器（Flask）模式可用；Cloudflare 模式下管理员密码是 Cloudflare secret，面板内改密不可用，接口回 501 并明示 `wrangler secret put ADMIN_PASSWORD`（R11-P2-1）。** |
| 命令重投 | `panel/app.py` `_requeue_stale_sent` 与 Worker `handleAgentPoll` | 命令 `sent` 态 120 秒未回执即自动打回 `queued` 重新下发，最多重投 3 次，超过标 `failed`（P1-6；Flask 与 Worker 两端上限一致，均为 `SENT_MAX_RETRIES = 3`；Worker 侧非幂等命令首超时即标 `failed`，不自动重发）。节点吊销时 `queued` 与 `sent` 态命令一并标失败。非幂等命令（`create_user`/`init_pki`）重投时可能重复执行，agent 侧应做幂等防护。前提是 `sent_at` 为可解析的时间戳；`sent_at` 缺失或不可解析的 `sent` 态命令视为条目损坏，直接标 `failed` 并记审计，不再下发（R13-P2-1）。 |
| 节点 token | `panel/app.py` `/api/nodes` | 注册/轮换时 token 明文只返回一次，库里只存 SHA-256 哈希，不可找回，丢失只能轮换。吊销：`DELETE /api/nodes/<name>`，旧 token 立即失效，该节点后续 poll 一律 401。轮换：`POST /api/nodes/<name>/rotate`，旧 token 立即作废，须重跑 install-agent.sh 带新 token。agent 侧配置文件 `/etc/ovpn-agent/config.json` 装机写 0600，`load_config` 每次加载再核一次、被改宽就收紧。 |
| 认领守卫 | `panel/app.py` `_check_panel_claim` + `agent/agent.py` poll/report | FLMX 教训：旧 agent config 地址与面板地址逐字相等才认领。节点注册时绑定的 `panel_url` 必须与给 agent 的 `--panel-url` 逐字一致（仅去尾斜杠）；agent 每次 poll/report 都上报 `panel_url`，不符返回 403 并记审计 `agent_poll_panel_mismatch`。旧版 agent 未上报 `panel_url` 时放行，但 poll 响应带 `panel_url_unverified: true`，提示升级 agent。 |
| SK5 凭据 | `egress/sk5_manager.py` + `panel/app.py` | 凭据只存 `/etc/openvpn-sk5-panel/sk5.json`（0600）；`/api/status` 只回 `has_password`，不回显密码；审计日志只记 host/port/开关，不记密码；agent 命令队列文件 `panel/data/agent_queue.json`（0600，含 set_sk5 密码与 create_user 回执的 .ovpn）不进日志、不经任何未登录接口回显。保存语义（P0-4）：`password` 缺失/空串/None = 保留已有密码，只有显式非空密码才覆盖；想清掉密码须同时传 `clear_password=true`（新版 egress 的 `set_sk5` 同款语义；旧版全量覆盖 egress 由面板侧解析顶替）。 |
| agent 通道 | `agent/agent.py` | `panel_url` 必须走 HTTPS，仅 `http://127.0.0.1` / `localhost` / `[::1]` 例外（本机假面板冒烟用）；禁止 https→http 降级重定向（`_NoDowngradeRedirectHandler`），token 绝不被重定向到明文地址；标准库默认校验 HTTPS 证书。agent 只主动外联面板，中转机不需开入站端口。 |
| 命令白名单 | `agent/agent.py` `execute_command` | 只接受 13 个白名单 action（与 `panel/app.py` 的 `AGENT_ACTIONS` 逐字一致），未知 action 拒绝上报；params 里出现 `command/shell/cmd/exec/script/argv` 键在分派前拒绝；执行层全用 `subprocess` 列表参数，无 shell 注入面；agent 不接受面板下发的任意 shell 命令。 |
| 审计日志 | `panel/app.py` `_audit` + `GET /api/audit` | SQLite `audit_log` 表（ts/actor/action/node/result/detail），记登录成败与锁定、节点注册/轮换/吊销、命令下发、agent 鉴权失败与认领拒绝、OpenVPN 启停/建用户/吊销、SK5 保存/测试/启用/停用。detail 写入前脱敏（password/node_token/token 值替换为 `***`），绝不含口令、token、`.ovpn` 私钥。查询：`GET /api/audit?limit=100`（管理员，上限 500）。 |
| 安装包公开 | `panel/app.py` `/api/agent/bundle`、`GET /install-agent.sh` | 有意公开、无鉴权：`install-agent.sh` 在装机时就是无鉴权 curl 下来的，包里只有代码（agent/core/egress），没有任何凭据；节点 token 是装机时 `--token` 参数单独传的，不在包里。凭据的唯一关口是节点 token + panel_url 认领守卫。 |

## 角色边界（单管理员，无普通用户）

本面板目前只有单一管理员角色，没有普通用户体系。FLMX 的“普通用户
只看自己隧道、服务/节点监控对普通用户关闭”在本项目里对应为：不
存在普通用户登录入口，所有 `/api/*` 管理接口都要求管理员会话。
将来若加多用户，必须先做按用户隔离（用户只能看自己的隧道/节点，
监控接口对普通用户关闭），再开放注册——不许先放开再补隔离。

## 残留风险

1. `install_prereqs` 的 sing-box SHA-256 校验是 fail-closed（P2-12
   修正旧说法）：`agent/agent.py` 的 `_expected_sha256` 在既无
   manifest 又无 `SINGBOX_SHA256`/`TUN2SOCKS_SHA256` 环境变量
   override 时直接拒绝安装，不再是"只告警、不阻断"。首次真机装机
   时仍应在面板下发命令里带上从上游 `checksums.txt` 核过的哈希，
   以便与 release 自带的 manifest 双重核对。
2. `/api/agent/bundle` 与 `/install-agent.sh` 公开下发（见上表，
   有意为之）：攻击者能拿到 agent 代码与版本号指纹，但拿不到任何
   凭据；不要把任何密钥放进这三个目录。
3. 命令重投的非幂等风险（见上表"命令重投"）：`create_user` /
   `init_pki` 重投时 agent 侧可能重复执行，需 agent 侧幂等防护
   兜底；面板侧重投上限 3 次、超时 120 秒已可把窗口收小，但不能
   完全消除重复执行。

## 自测命令

```bash
# 1. 编译
python3 -m py_compile panel/app.py agent/agent.py
# 2. 默认口令字面量零命中
grep -rn "admin123\|changeme\|123456\|password123" panel/app.py agent/agent.py
# 3. Flask test-client 全流程（见 /tmp/sec-test/run_tests.py）：
#    未登录 /api/status -> 401；错口令 5 次后第 6 次 -> 429；
#    正确登录 -> 200 且 Set-Cookie 含 HttpOnly + SameSite=Lax；
#    agent 无 token 调 poll -> 401；错 token -> 401；
#    token 与节点名不符 -> 401；panel_url 不符 -> 403；
#    注册节点 -> 201（token 只返回一次），/api/nodes 不含 token；
#    下发命令 -> 202，poll 取到命令，report 回执后 /api/cmd/<id> 为 done；
#    /api/audit 里无口令/token/.ovpn 私钥。
# 4. agent 本地：
python3 -c "import sys; sys.path.insert(0,'agent'); import agent
agent.load_config"   # 无配置时应报缺配置，不应静默用默认值
```

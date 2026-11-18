# OpenVPN + SK5 面板（panel/）

单页轻量面板，一个页面同时管 OpenVPN 和 SK5，不用 MongoDB。
后端 Python Flask + SQLite（仅存管理员密码哈希与会话密钥），
前端单 HTML 无构建、无框架 CDN 依赖。

## 本地启动

```bash
cd panel
pip install -r requirements.txt
python3 app.py
# 监听 0.0.0.0:8443，浏览器打开 http://<服务器 IP>:8443
```

首次启动生成随机管理员密码，打印到 stdout，并写入
`/etc/openvpn-sk5-panel/admin.pass`（600）。
若 `/etc` 不可写，回落到 `panel/data/admin.pass`（600），启动日志会注明实际路径。
会话为 Flask session cookie（HttpOnly，SameSite=Lax）。

## API 字段表

管理接口 `/api/*`（除登录、`/api/me`）均需登录，未登录返回 `401 {"ok":false,"error":"unauthorized"}`。例外：`/api/agent/*` 走节点 token 鉴权（`_agent_auth`，未带／错 token 即 401）；`/api/agent/bundle`、`/api/agent/bundle.sha256`、`/api/agent/panel-ca` 与 `/install-agent.sh`、`/install-agent.sh.sha256` 公开（装机时无鉴权取脚本与面板 CA，设计如此）。
成功一般返回 `{"ok":true, ...}`，失败返回 `{"ok":false,"error":"..."}`。
对接模块未落盘时相关接口返回 `503 {"ok":false,"error":"module_missing","module":"..."}`。

| 方法与路径 | 请求字段 | 返回字段 |
|---|---|---|
| GET `/` | — | `index.html` |
| POST `/api/login` | `password: string` | `ok` |
| POST `/api/change-password` | `old_password: string, new_password: string`（新密码 ≥12 字符、含字母和数字、UTF-8 不超过 72 字节、与旧密码不同） | `ok, note`；成功后全部旧会话作废，须重新登录；仅服务器（Flask）模式，Cloudflare 模式回 501（R11-P2-1） |
| POST `/api/logout` | — | `ok` |
| GET `/api/me` | — | `ok, admin: bool` |
| GET `/api/agent/panel-ca` | — | 面板 CA 证书 PEM（`application/x-pem-file`）；无 CA 文件时 404（旧版面板或用户自带证书） |
| GET `/api/nodes` | — | `nodes: [{name, panel_url, created_at, last_seen, last_status, agent_bundle_sha256, agent_code_outdated, cert_pin_stale}]`（`cert_pin_stale`：CA 轮换后 last_seen 冻结即 True，无轮换记录即 null） |
| POST `/api/nodes` | `name: string（字母/数字/_/-，1–32 字符）, panel_url?: string（http(s):// 开头，留空=面板自身地址）` | `node{name, panel_url, created_at}, token`（201；token 只返回一次） |
| DELETE `/api/nodes/<name>` | — | `ok`（吊销节点 token，agent 此后 poll 恒 401；agent 本身须在节点机上另行移除） |
| POST `/api/nodes/<name>/rotate` | — | `node, token`（轮换节点 token，旧 token 立即失效） |
| POST `/api/cmd` | `node: string, action: string, params?: object` | `cmd_id, node, action`（命令入队，agent 下次 poll 拉取） |
| GET `/api/cmd/<cmd_id>` | — | 命令记录 `{id, node, action, params, status, result?, ...}`（agent 上报后 status 变 done/failed） |
| GET `/api/audit` | `limit?: int（默认 100）` | `audit: [{...}]`（操作审计行，最新在前） |
| GET `/api/status` | — | `openvpn{running, online_users, port, proto, subnet: "10.8.0.0/24", dns, unit_active, pid, error?, server_cert{exists, expires, days_left, expired, warning}, status_error?, detail}, sk5{enabled, host, port, error?}, egress{ip, latency_ms, via_sk5, error?}, modules_missing[]`（`dns`：server.conf 实际推送的 DNS（$OVPN_DNS，默认 `1.1.1.1`）；`server_cert`：服务端证书有效期，到期前 30 天 `warning: true`；`status_error`：状态日志损坏时在线列表为空的原因，守护进程在跑的结论不变） |
| POST `/api/openvpn/server` | `port: int(1-65535)（可省，UDP 默认 1194 / TCP 默认 443）, proto: "udp"\|"tcp", server_ip?: string（.ovpn 的 remote，留空=自动探测公网 IP；填了须为 IP 或主机名，否则 400）` | `server{proto, port, conf_path, subnet, dns, server_ip, remote_warning, note}`；server_ip 为生效值（已存值或自动探测）；子网由 core 固定，DNS 为 server.conf 实际推送值（$OVPN_DNS，默认 `1.1.1.1`），改配置后需重启服务生效 |
| POST `/api/openvpn/start` | — | `result`（`server_status()` 返回值原样） |
| POST `/api/openvpn/stop` | — | `result` |
| POST `/api/openvpn/restart` | — | `result` |
| POST `/api/openvpn/renew-server-cert` | — | `renewed, restarted: bool, server_cert{expires, days_left, expired, warning}`（R47-L4-4：只换服务端证书，CA 与用户证书不动；服务在跑才重启生效，停着时不拉起来，新证书在下次启动时生效；重启失败返回 500 + `needs_restart: true`） |
| POST `/api/openvpn/pki/repair` | — | `report{repaired: [{name, kind, action, detail}], checked}`（R47-L4-3：对账 index.txt 与 issued/ 并修复不一致——证书文件丢了的有效用户按序列号吊销进 CRL，孤儿证书清掉；修复报告进审计日志） |
| GET `/api/openvpn/users` | — | `users: [{name, status: valid\|revoked\|expired, revoked: bool, online: bool, expires, serial, legacy}]`（`legacy: true` = 旧版 CN=OpenVPN-CA 存量证书，见下节迁移说明） |
| POST `/api/openvpn/users` | `name: string（core 规则 `[a-zA-Z0-9_-]{1,32}`）` | `user{name, status: "valid"}, ovpn_url`（建完前端自动打开该地址下载 `.ovpn`） |
| DELETE `/api/openvpn/users/<name>` | — | `result{name, status, crl}, needs_restart: false, restarted: true`（服务正在运行时，面板在吊销成功后自动重启 OpenVPN 服务一次，CRL 立即生效；服务停着时不重启，返回 `restarted: false`，吊销在服务下次启动时生效；重启失败时返回 500 + `needs_restart: true`） |
| GET `/api/openvpn/users/<name>/ovpn` | — | `.ovpn` 文件下载（`Content-Disposition: attachment`），证书文件缺失返回 404 JSON |
| GET `/api/sk5` | — | `sk5{host, port, username, has_password, enabled, fail_open, udp_over_tcp, singbox_running, policy_routing_active, vpn_net, egress_ip}`（不回显密码） |
| POST `/api/sk5` | `host: string, port: int(1-65535), username: string, password: string, enabled: bool, fail_open?: bool, udp_over_tcp?: bool, clear_password?: bool` | `sk5`（`get_status()` 原样）；`enabled=true` 时立即应用（起 sing-box + 策略路由）。密码语义：`password` 缺失/空串 = 保留已有密码，只有非空才覆盖；清密码须同时传 `clear_password: true` |
| POST `/api/sk5/test` | — | `test{tcp_ok, udp_ok, egress_ip, latency_ms, udp_mode, udp_note, host, port, tcp:{ok, latency_ms, egress_ip}, udp:{ok, supported, mode, note}}` |
| POST `/api/sk5/enable` | — | `result`（`get_status()` 原样） |
| POST `/api/sk5/disable` | — | `result`（停用后 VPN 用户回直连出口） |
| POST `/api/sk5/fail-open` | `fail_open: bool` | `result`；True=断链故障回直连，False=默认断网保护（黑洞） |
| POST `/api/sk5/udp-over-tcp` | `udp_over_tcp: bool`（缺省时回落 `enabled`） | `result`；True=UoT 封装，False=原生 UDP ASSOCIATE |

## 对接点（core / egress 函数名）

`app.py` 在启动时把 `../core`、`../egress` 加入 `sys.path`，并按以下
名字 import。core 与 egress 两侧均已按实物核对（行数见 `wc -l`，行数随修复浮动，文档不钉死具体行数）。

`core/openvpn_manager.py`（已核对实物；行数见 `wc -l`）：
- `server_status() -> dict`：`{running, unit_active, pid, clients: [{name, real_address, ...}], status_log, error?}`
- `render_server_conf(proto="udp", port=None, server_dir=None, ca_dir=None, dns=None, allow_port_change=False) -> Path`：认 proto/port/server_dir/ca_dir/dns/allow_port_change；子网固定 `10.8.0.0/24`（`OVPN_SUBNET` 设为其他值时安装器直接拒绝——NAT 规则与已服务子网错位会使出口断流）、DNS 取 `$OVPN_DNS`（默认 `1.1.1.1`），写入 server.conf 的 `push "dhcp-option DNS …"`；面板 `/api/status` 报的 `dns` 即该实际推送值（见 `server.conf.template`）。入口端口铁律 P01：已建服务改端口无 `allow_port_change=True` 即 500 拒绝，带上才改写（面板 `POST /api/openvpn/server` 透传该字段）
- `start_server() / stop_server() / restart_server() -> dict`：返回 `server_status()`
- `list_users() -> list[dict]`：`[{name, status: valid|revoked|expired, expires, serial, cn, legacy}]`
- `create_user(name) -> str`：返回 `.ovpn` 文本；重名有效证书会抛错，**但 CN=OpenVPN-CA 的旧存量证书（`legacy`）除外：重建同名先吊销旧证再重签，返回新证书的 `.ovpn`**
- `revoke_user(name) -> dict`：`{name, status, crl}`
- `validate_username(name) -> str`：`[a-zA-Z0-9_-]{1,32}`
- `build_client_config(name, ca, cert, key, ta_key, server_ip, proto="udp", port=1194) -> str`

`.ovpn` 下载的实现说明：core 没有 `get_user_ovpn()`，面板的
`GET /api/openvpn/users/<name>/ovpn` 用已签发文件重建——读
`$OPENVPN_CA_DIR/pki/{ca.crt, issued/<name>.crt, private/<name>.key}` 与
`$OPENVPN_SERVER_DIR/ta.key`（默认 `/etc/openvpn/server/easy-rsa` 与
`/etc/openvpn/server`），调 `build_client_config()` 渲染；proto/port 从
已渲染的 `server.conf` 解析，`server_ip` 从 `OPENVPN_SERVER_IP` 或本机
外向 IP 解析。若 core 路后续补 `get_user_ovpn()`，面板可直接改调它。

`egress/sk5_manager.py`（已核对实物；行数见 `wc -l`）：
- `get_status() -> dict`：脱敏配置 `{host, port, username, has_password, enabled, fail_open, udp_over_tcp}` + `{singbox_running, singbox_config, policy_script, policy_routing_active, vpn_net: "10.8.0.0/24", egress_ip}`
- `set_sk5(host=None, port=None, username=None, password=None, enabled=None, fail_open=None, udp_over_tcp=None, clear_password=False) -> dict`：部分合并语义——传 `None` 的字段保留已存值（单字段开关可直接调，不必重发 host+port）；`password` 为 `None`/空串时保留已存密码，只有非空才覆盖，`clear_password=True` 才清空；存配置（0600）并在 `enabled` 时立即应用；返回 `get_status()`。面板按实际签名自适应：旧版全量覆盖 `set_sk5` 由面板侧解析顶替（见 `app.py` `_SK5_ACCEPTS_CLEAR`）。
- `enable() / disable() -> dict`：起/停 sing-box + 挂/摘策略路由（表 100）；返回 `get_status()`
- `test_sk5() -> dict`：`{tcp_ok, udp_ok, egress_ip, latency_ms, udp_mode: native|udp_over_tcp, udp_note, host, port}`，TCP（curl 经 SK5 取 ifconfig.me）与 UDP（原生 UDP ASSOCIATE + DNS 到 1.1.1.1:53，或 UoT 封装探针）分开测——UDP 不支持时 OpenVPN 须切 TCP 模式或开 UoT
- `current_egress_ip() -> str | None`：启用时经 SK5 测，否则直连测
- `check_health() -> dict`：`{healthy, action, detail}`，由 systemd timer 每 60 秒轮询（见下节）
- `set_fail_open(fail_open: bool) -> dict`、`set_udp_over_tcp(enabled: bool) -> dict`

注意：`/api/status` 的出口延迟 `latency_ms` 为空——状态轮询只取 IP，
不跑全量 `test_sk5()`（单次探针可达 10 秒+）；延迟以
`POST /api/sk5/test` 返回的为准。状态轮询只做一次 egress 探针：
SK5 启用时复用 `get_status()` 已探到的 `egress_ip`，直连探针与
`get_status()` 结果各有 10 秒缓存（前端每 15 秒轮询一次，状态
最多滞后 10 秒）。`check_health()` 由 `openvpn-sk5-healthcheck.timer` 每 60 秒轮询，结果写 `health.json`，经 `get_status()` 的 `last_health` 回显到面板；面板本身不另设轮询定时任务。

命令队列语义：`sent` 态 120 秒未回执自动打回重发，最多 3 次，
超过标 `failed`；节点吊销时 `queued` 与 `sent` 态命令一并标失败。

## 约束与注意

- Python 3.10+，依赖 `flask` + `bcrypt`（见 `requirements.txt`；
  bcrypt 未安装时密码哈希回落旧的加盐 SHA-256，功能不受影响）。
- 面板自身不直接操作 `tun`、不写 OpenVPN 配置、不做策略路由，
  全部业务逻辑在 `core/` 与 `egress/`，面板只做 HTTP 适配与鉴权，
  唯一的例外是 `.ovpn` 下载重建（见上节，纯属 core 缺口的适配）。
- 生产部署的 8443 是 TLS（systemd 单元跑 `run-panel-tls.py`，以自签面板证书提供 `ssl_context`；浏览器会报不受信任证书警告，属预期，见 DELIVERY §1.3）；明文 HTTP 只用于本地开发启动。反代后加 HTTPS 的建议不变。
- 改密入口：顶栏「修改密码」按钮（`POST /api/change-password`），
  前端先校验新密码强度（≥12 字符、含字母和数字、UTF-8 不超过 72 字节、与旧密码不同、
  两次输入一致），改后全部旧会话作废、页面回到登录页。（仅服务器 Flask 模式；Cloudflare 模式下该按钮调接口回 501 并明示线下改密方法，见 README:295。）
- 旧证书迁移（R2-P1-3）：修复前签发的用户证书 CN 都是 `OpenVPN-CA`
  （BUG-7），面板按序列号识别用户（见 core/README.md）：用户列表
  正常显示，带「旧证书」标记；吊销按用户名正常工作；重建同名用户
  先吊销旧证再重签 CN 正确的证书，旧证书在重启 OpenVPN 服务后对
  新连接失效。
- 数据目录（R2-P2-2）：`OVPN_PANEL_DATA_DIR` 环境变量可改数据目录
  （DB、admin.pass、secret、agent 队列、server 设置全跟过去）；未设
  时为 `panel/data`。install.sh 在 `panel.env` 里显式写该变量指向
  安装后的数据目录；`panel/data/` 已钉进根 `.gitignore`，密钥与
  库文件不会再进发货树。

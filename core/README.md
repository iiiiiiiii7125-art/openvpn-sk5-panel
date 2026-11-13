# core/ — OpenVPN 核心（轻量版 Pritunl 模型）

不用 MongoDB。用 Easy-RSA 做 PKI + OpenVPN 原生守护进程，面板层
（`panel/`）只调这里的函数。目标平台：Debian 12 / Ubuntu 22.04 / 24.04，
OpenVPN 2.6，Python 3.10+，只用标准库 + subprocess。

## 文件

| 文件 | 作用 |
|---|---|
| `openvpn_manager.py` | 全部逻辑：PKI、用户、.ovpn、server.conf、守护进程启停/状态 |
| `easyrsa.sh` | Easy-RSA 3 的非交互封装（init / build-server / build-client / revoke / gen-crl） |
| `server.conf.template` | 服务端模板：`$PROTO` / `$PORT` / `$SERVER_DIR` 占位 |
| `client.ovpn.template` | 客户端模板：`$PROTO` / `$SERVER_IP` / `$PORT` + 内嵌 `<ca>/<cert>/<key>/<tls-auth>` |

## 接口（`openvpn_manager.py`，模块级函数）

```python
init_pki(ca_dir=None, force=False) -> Path
build_server_cert(ca_dir=None, server_dir=None) -> dict[str, str]  # 装好的 6 个文件路径
render_server_conf(proto="udp", port=None, server_dir=None, ca_dir=None, dns=None, allow_port_change=False) -> Path
create_user(name, ca_dir=None, server_dir=None,
            server_ip=None, proto=None, port=None) -> str  # 返回 .ovpn 文本
revoke_user(name, ca_dir=None, server_dir=None) -> dict   # {name, status, crl}
list_users(ca_dir=None) -> list[dict]                     # [{name, status, expires, serial}]
server_status(server_dir=None) -> dict                    # {running, unit_active, pid, clients, ...}
start_server(server_dir=None) -> dict
stop_server(server_dir=None) -> dict
restart_server(server_dir=None) -> dict
validate_username(name) -> str
build_client_config(name, ca, cert, key, ta_key, server_ip, proto="udp", port=1194) -> str
```

同名方法也挂在 `OpenVPNManager(ca_dir, server_dir)` 实例上。另有极简 CLI
供冒烟测试：`python3 -m core.openvpn_manager status|list|create <name>|revoke <name>|start|stop|restart`。

## 规则

- 用户名：`[a-zA-Z0-9_-]{1,32}`，否则 `OpenVPNError`。名字会变成文件名、
  证书 CN 和状态日志键，必须防路径穿越。
- 判重：`pki/index.txt` 里状态为 `valid` 的同名证书存在即拒绝；
  但 CN=OpenVPN-CA 的旧存量证书（`legacy`，见下节迁移）除外——
  重建同名时先吊销旧证再重签，而不是报错。
- 吊销：写 CRL（`pki/crl.pem` → 同步到服务端 `crl.pem`）。**OpenVPN 只在
  启动时读 CRL**，吊销后必须 `restart_server()` 才对新连接生效，
  已连上的客户端不会被 CRL 主动踢掉。
- `.ovpn`：`ca/cert/key/ta.key` 全部内嵌，客户端只需一个文件。
- 启停：优先 `systemctl openvpn-server@server`；无 systemd 时回退到
  `openvpn --config ... --daemon` + PID 文件。`server_status()` 在守护进程
  未运行时不抛异常，用 `error` 字段说明原因。
- 服务端子网固定 `10.8.0.0/24`（`topology subnet`），`tun-mtu 1400` /
  `mssfix 1360`，`redirect-gateway def1` 全量走隧道。SK5 出口由另一层
  （策略路由 + tun2socks/sing-box）接管，不在本模块。

## 旧证书迁移（R2-P1-3，BUG-7 存量）

修复前（BUG-7）签发的用户证书 subject 全是 `/CN=OpenVPN-CA`，
按 CN 识别用户会把旧用户全丢掉（列表不见、吊销报不存在、重建
报已存在）。识别规则（`_parse_index_txt`，按优先级）：

1. index.txt 的文件名为真实 `.crt` 名时取文件名 stem；
2. 否则按**序列号**匹配 `pki/issued/<name>.crt`（真实 `openssl ca`
   写出的 index.txt 文件名列永远是字面 `unknown`，文件名不能用，
   序列号可以；序列号用标准库 DER 解析从证书文件读出）；
3. 最后才回落到 subject CN。

按 2 认出的用户带 `legacy: true`（CN 与用户名不一致），三路打通：

- 列表：`list_users()` 正常返回旧用户，带 `legacy` 标记；
- 吊销：`revoke_user(name)` 按用户名吊销，与新证书完全一样；
- 重建：`create_user(name)` 对有效旧证书先吊销旧证、删残留文件、
  再用正确 CN 重签，返回新证书的 `.ovpn`（旧证书在
  `restart_server()` 后对新连接失效）。

同名重建后 index.txt 里同时有旧吊销条目和新有效条目：以后写者
（last entry）为准，`_user_status()` 不会把已重建的用户误判为
已吊销。用户名 `ca` 也已保留（CA 证书文件是 `pki/ca.crt`）。

## 安装依赖

```bash
apt update && apt install -y openvpn easy-rsa
```

## 手动测试（root，Debian 12 / Ubuntu 22.04/24.04）

```bash
cd ~/workspace/openvpn-sk5-panel
bash -n core/easyrsa.sh && python3 -m py_compile core/openvpn_manager.py

# 1. 初始化 PKI + 服务端证书（只需一次）
export OPENVPN_CA_DIR=/etc/openvpn/server/easy-rsa
export OPENVPN_SERVER_DIR=/etc/openvpn/server
python3 -c "from core.openvpn_manager import init_pki, build_server_cert; init_pki(); print(build_server_cert())"

# 2. 生成服务端配置（UDP 1194；TCP 用 proto='tcp', port=443）
python3 -c "from core.openvpn_manager import render_server_conf; print(render_server_conf('udp'))"
python3 -c "from core.openvpn_manager import render_server_conf; print(render_server_conf('tcp', 443))"

# 3. 建用户并导出 .ovpn
python3 -c "from core.openvpn_manager import create_user; open('/tmp/alice.ovpn','w').write(create_user('alice'))"
python3 -m core.openvpn_manager list

# 4. 启动并查看状态 / 在线客户端
systemctl enable --now openvpn-server@server   # 或 python3 -m core.openvpn_manager start
python3 -m core.openvpn_manager status
cat /var/log/openvpn/openvpn-status.log

# 5. 吊销（吊销后重启才生效）
python3 -m core.openvpn_manager revoke alice
python3 -m core.openvpn_manager restart
python3 -m core.openvpn_manager list

# 6. 客户端验证（另一台机器）
openvpn --config /tmp/alice.ovpn
curl --interface tun0 ifconfig.me   # 应为服务器出口 IP（未接 SK5 时）

# 7. 边界用例（都应报 OpenVPNError，不写盘）
python3 -c "from core.openvpn_manager import create_user; create_user('../evil')"
python3 -c "from core.openvpn_manager import create_user; create_user('alice'); create_user('alice')"
```

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `OPENVPN_CA_DIR` | `/etc/openvpn/server/easy-rsa` | PKI 根目录 |
| `OPENVPN_SERVER_DIR` | `/etc/openvpn/server` | 服务端文件 + server.conf |
| `OPENVPN_SERVER_IP` | 自动探测外网源 IP | 写进 `.ovpn` 的 `remote` |
| `OPENVPN_PROTO` / `OPENVPN_PORT` | `udp` / `1194` | 无 server.conf 时的默认协议/端口 |
| `OPENVPN_PID_FILE` | `/run/openvpn-server/server.pid` | 直接启动模式的 PID 文件 |

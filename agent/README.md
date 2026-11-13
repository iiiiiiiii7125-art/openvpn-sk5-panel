# ovpn-agent — 中转机上的执行 agent（FLMX agent 模型）

面板是控制面（可部署在 Cloudflare Worker 或服务器上），中转机上跑这个
agent。agent **只主动外联面板**，中转机不需要开任何入站端口，NAT /
防火墙后可用。执行层直接 import `core/openvpn_manager.py` 和
`egress/sk5_manager.py`，不重写、不 fork —— agent 只是“面板的远程手”。

```
面板 (Cloudflare / 服务器)                中转机
  /api/agent/poll  <--- POST (5s) ---   ovpn-agent (systemd)
  /api/agent/report <--- POST 结果 ---   -> core/openvpn_manager.py
  /api/agent/bundle (tar.gz 下发)        -> egress/sk5_manager.py
```

## 安装（在中转机上，两步走命令）

```bash
curl -ksSL https://<面板>/install-agent.sh -o /tmp/install-agent.sh && \
curl -ksSL https://<面板>/install-agent.sh.sha256 -o /tmp/install-agent.sh.sha256 && \
cd /tmp && sha256sum -c install-agent.sh.sha256 && \
bash /tmp/install-agent.sh --panel-url https://<面板>:8443 --token '<NODE_TOKEN>' --node-name '<节点名>'
```

先用 `-k` 下脚本（面板默认自签证书，plain curl 会 TLS 校验失败），
再 `sha256sum -c` 校验通过才执行，校验失败即停；与面板“复制安装命令”
生成的命令同口径。

`--token` 是面板给该节点发的节点令牌（面板侧生成、一次一节点）。
首次安装必须给 token；重装不给 `--token` 时沿用
`/etc/ovpn-agent/config.json` 里的旧 token。`--node-name` **必带且
须与注册名一致**：缺了它 agent 默认用 hostname 注册，poll 恒 401。
装完即 `systemctl enable --now ovpn-agent`，看日志：

```bash
journalctl -u ovpn-agent -f
systemctl status ovpn-agent
```

安装脚本幂等：重跑保留 CA、token、已签发证书，只更新 agent 文件并重启
服务。脚本断言目标不是 `/root/flmx-panel`，命中直接退出。

重装已有部署须显式加 `--force`（否则直接拒绝）；`--force` 重装时
先把旧 `/etc/ovpn-agent/config.json` 备份为
`config.json.bak.<时间戳>`，再 `systemctl reset-failed` 后重启服务。
BUG-6：重装换了 panel-url/token 后，脚本会重启已运行的 agent（旧
进程不会继续用旧配置 poll）；重启后判活 `is-active`，失败即报错。

## 面板证书信任（BUG-5）

面板默认用自签 TLS 证书，agent 校验 TLS。没有信任锚点时 agent
每 5 秒 poll 都报 `CERTIFICATE_VERIFY_FAILED`，面板永远见不到
agent、命令链全断。安装器在装 agent 时自动建立信任：

1. 先试系统信任库直接验证（公网 CA 面板，如 Cloudflare 前端，
   什么都不用做）；
2. 验证失败时把面板当前出示的证书 TOFU 钉到
   `/etc/ovpn-agent/panel-ca.pem`（0600），并写进
   `/etc/ovpn-agent/config.json` 的 `ca_cert`；
3. 面板换证书后须重跑安装器 `--force` 重新钉，否则 poll 会再次
   报证书错。

也可显式控制：`--ca-cert <panel.pem>` 直接钉该 PEM；
`--insecure` 跳过校验（**仅调试用**：token 与用户 .ovpn 可被
中间人截获，agent 启动日志会告警）。agent 本身也支持
`--ca-cert` / `--insecure` 命令行参数（单次运行覆盖配置文件），
以及配置文件里的 `ca_cert` / `insecure` 字段。默认永远校验，
绝不默认 `--insecure`。

> 注意：上面这条命令成立的前提是面板提供 `GET /install-agent.sh`
> （下发本目录脚本）与 `GET /api/agent/bundle`（下发本仓库打好的
> tar.gz，含 `agent/` + `core/` + `egress/`）——两者均已实现，另有
> `GET /api/agent/bundle.sha256`（bundle 的 fail-closed 校验）与
> `GET /install-agent.sh.sha256`（脚本自身的 sha256 校验，面板已提供，
> 哈希与脚本字节相符）。

> 本机离线装法：从仓库直接跑
> `bash agent/install-agent.sh --panel-url ... --token ...`，脚本检测
> 到身边的 `agent.py` + `core/` 后走本地复制，不下载。

## 二进制校验（BUG-2，agent 侧）

`sing-box` 1.11.15 与 `tun2socks` 2.7.0 的上游 release **不发布
sha256 清单**（live-verify §9 BUG-2），只靠清单校验的话，全新
节点上的 agent 装机永远装不上。agent 内置了与 `install.sh` 同一
组双锚核验过的钉死哈希（`agent.py` 顶部 `_PINNED_SHA256`），
校验优先级：

1. 操作员显式覆盖（命令参数 `singbox_sha256` /
   `tun2socks_sha256`，或环境变量 `SINGBOX_SHA256` /
   `TUN2SOCKS_SHA256`，须为严格 64 位 hex）；
2. 钉死哈希（按 binary × arch）；
3. 上游清单（`checksums.txt` / `SHA256SUMS.txt`）；
4. 三档全无 → 拒绝安装（fail-closed，绝不装未校验的二进制）。

钉死哈希与版本号绑定：升级 `SINGBOX_VERSION` /
`TUN2SOCKS_VERSION` 时必须同步刷新对应哈希（与 `install.sh`
里的同名常量保持一致），否则安装会在校验步 fail-closed 停下。

## 协议（面板侧实现约定）

认证：每次请求都带 `Authorization: Bearer <node_token>`，同时 body
里也有 `node_token` 字段（面板任选其一校验；两者不一致即拒）。

### POST /api/agent/poll

请求：

```json
{"node_token": "...", "node_name": "transit-01",
 "status": {"version": "0.1.0", "hostname": "...",
            "openvpn_running": true, "sk5_enabled": false}}
```

响应：`{"commands": [{"id": "cmd-1", "action": "create_user",
"params": {"name": "alice"}}]}`。无任务时 `{"commands": []}`。
agent 收到未知 action 会直接上报错误，不执行。

### POST /api/agent/report

```json
{"node_token": "...", "node_name": "transit-01", "id": "cmd-1",
 "ok": true, "result": {"name": "alice", "ovpn": "<.ovpn 文本>"},
 "error": null}
```

`ok: false` 时 `result` 为 null，`error` 为 `"<异常类>: <原因>"`。
`create_user` 的 `result.ovpn` 内含用户私钥——只走 HTTPS report
通道，面板收到后应直接交给请求管理员，**不得记入面板日志**；
agent 本身也不打这条日志（只记 action/id/ok）。

## 命令表

| action | params | 执行层 | 说明 |
|---|---|---|---|
| `install_prereqs` | `{singbox_sha256?}` | apt + GitHub release | 装 openvpn/easy-rsa + sing-box 1.11.15（pinned）；sha256 fail-closed——不给 override 时取上游清单，都没有即拒绝安装（已装的 sing-box 也会核对版本，不符即重装） |
| `init_pki` | `{force?, confirm?}` | `init_pki` + `build_server_cert` | 建 CA + 服务端证书；已有 CA 且 `force` 为假时报错；`force=true` 须同时传 `confirm=true`（会清空 CA、作废全部用户证书） |
| `create_server` | `{proto?, port?, dns?, allow_port_change?}` | `render_server_conf` + `build_server_cert` | 缺 CA 时先 `init_pki`；默认 UDP 1194，TCP 默认 443；重复执行幂等（服务端证书已存在即复用，不重跑 gen-dh）；入口端口创建后固定，改端口须显式 `allow_port_change=true`，且新端口须空闲 |
| `start_openvpn` / `stop_openvpn` / `restart_openvpn` | — | `start/stop/restart_server` | systemd 优先，无 systemd 时直接 `openvpn --daemon` 回退 |
| `create_user` | `{name, server_ip?, proto?, port?}` | `create_user` | 返回 `{name, ovpn}`；重名有效证书时报错，已吊销名可重建 |
| `revoke_user` | `{name}` | `revoke_user` + `restart_server` | CRL 只在启动时读，吊销后自动重启才对新连接生效 |
| `set_sk5` | `{host?, port?, username?, password?, enabled?, fail_open?, udp_over_tcp?, clear_password?}` | `set_sk5` | 部分合并语义：缺省字段保留已存值，单字段开关（`fail_open`/`udp_over_tcp`）可单独下发；空密码不覆盖已存密码（要切无认证商家传 `clear_password=true`）；启用即起 sing-box + 策略路由；密码只存 `/etc/openvpn-sk5-panel/sk5.json`（0600），不进日志 |
| `test_sk5` | — | `test_sk5` | TCP 与 UDP 分开报：`tcp_ok` / `udp_ok` / `egress_ip` / `latency_ms`；TCP 通不冒充 UDP 通 |
| `enable_sk5` / `disable_sk5` | — | `enable` / `disable` | 停用即撤策略路由、停 sing-box，VPN 流量回直连 |
| `get_status` | — | `server_status` + `list_users` + `sk5.get_status` + `current_egress_ip` + `last_health` | 面板轮询/展示用；`health` 是最近一次定时器健康检查结果 |

所有命令参数都经白名单校验（用户名 `[A-Za-z0-9_-]{1,32}`、端口
1–65535、proto 仅 udp/tcp、host 字符集受限）；非法参数在执行前
拒绝并上报，不进 shell、不拼命令（执行层全用 `subprocess` 列表
参数，无 shell 注入面）。

## 排障

```bash
journalctl -u ovpn-agent -f          # 看 poll / 命令执行日志
systemctl restart ovpn-agent         # 重启 agent（不断已连 VPN 用户）
cat /etc/ovpn-agent/config.json      # 确认 panel_url / token（0600）
python3 /opt/ovpn-agent/agent/agent.py --once   # 手动跑一次 poll
```

- `poll failed: cannot reach panel`：检查 panel_url、面板是否可达、
  token 是否被轮换；agent 会退避重试（5s → 60s 上限），面板恢复
  后自动续跑，不用重启。
- `unknown action`：面板发了 agent 不认识的命令，升级 agent
  （重跑 install-agent.sh）后再试。
- `no CA ... run init_pki() first`：先在面板点 `init_pki` 或
  `create_server`，再建用户。

## token 轮换

面板侧作废旧 token、发新 token 后，在中转机上：

```bash
python3 - <<'EOF'
import json
p = "/etc/ovpn-agent/config.json"
cfg = json.load(open(p))
cfg["node_token"] = "<NEW_TOKEN>"
json.dump(cfg, open(p, "w"), indent=2)
EOF
chmod 600 /etc/ovpn-agent/config.json
systemctl restart ovpn-agent
```

或直接重跑 install-agent.sh 并带新 `--token`。

## 面板侧状态（2026-11-12 已接通）

`panel/app.py` 已实现 `/api/agent/poll`、`/api/agent/report`、
`/install-agent.sh`、`/install-agent.sh.sha256`、`/api/agent/bundle`、`/api/agent/bundle.sha256`：
按 token 查节点、poll 时取该节点待执行命令队列、report 时落库并把
`create_user` 的 `.ovpn` 交给管理员下载、bundle 打包 `agent/` +
`core/` + `egress/`。从文件运行安装脚本时先取 `.sha256` 严格校验
脚本本身，校验失败即停（bundle 仍是 fail-closed 校验，见
`install-agent.sh`）。

## agent 自身校验（`--once` 退出码）

`agent.py --once` 供冒烟/健康检查用：poll 失败时退出码为 1，成功
为 0。

## 冒烟（本机假面板，见 smoke 记录）

`/tmp` 下的假面板（标准库 `http.server`）实现 poll/report：
第一次 poll 返回 `get_status`（应成功）与 `create_user`
`smokeuser`（沙箱无 openvpn/easy-rsa，应干净失败并上报
`ok: false`），之后 poll 返回空。agent 用 `--once` 跑两次，
验证 poll → 执行 → report 全链与成功/失败两条上报路径。

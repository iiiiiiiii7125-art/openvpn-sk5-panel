# openvpn-sk5-panel

一台服务器作 OpenVPN 中转，面板点几下建协议、发用户，再一键把全部 VPN 用户的出口切到购买的 SOCKS5（SK5）。

## 架构（最终：面板控制面 + agent 执行面，FLMX 同款分法）

```
                  ┌─────────────────────────────────┐
                  │ 面板（控制面，二选一部署）       │
                  │  A. Cloudflare Worker + KV      │
                  │  B. 服务器 Flask（panel/app.py) │
                  │  同一套前端、同一套命令契约      │
                  └──────────────┬──────────────────┘
                                 │ 命令队列（KV / SQLite）
                                 │ agent 每 5 秒 poll 拉取
                                 ▼
                  ┌─────────────────────────────────┐
                  │ agent（中转机，ovpn-agent）      │
                  │  只主动外联面板，中转机不开入站口 │
                  │  调 core/ + egress/ 执行        │
                  └──────────────┬──────────────────┘
                                 │
              ┌──────────────────┴──────────────────┐
              │ core/ OpenVPN 本体                   │ egress/ SK5 出口链
              │ easy-rsa PKI、server.conf、用户证书  │ sing-box + 策略路由
              └──────────────────┬──────────────────┘
                                 ▼
客户端 --OpenVPN--> tun0 10.8.0.0/24 (OpenVPN server, UDP 1194 / TCP 443)
                        |
                        | 未启用 SK5: 主表直连 (MASQUERADE 经本机出口)
                        | 已启用 SK5: ip rule from 10.8.0.0/24 lookup 100 (prio 100)
                        v
                   table 100: default via 10.9.0.1 dev tun1
                        |
                        v
                   tun1 10.9.0.1/30 (sing-box tun 入站, tag tun-in)
                        |
                        | sing-box 出站 bought-sk5
                        v
              购买的 SOCKS5 host:port (用户名/密码, version 5)
                        |
                        v
                    互联网 (出口 IP = SK5 的 IP)
```

关键点：策略路由只按**源地址**匹配。sing-box 自己连 SK5 时源地址是本机 IP，不进 table 100，走主表直连商家 —— sing-box 的 SK5 连接永远不会被 loop 回 tun1。**DNS 查询（53 端口）默认走 direct、不经过 SK5**（sing-box 模板的既定设计，见观察-5）：VPN 用户的 DNS 出口是中转机直连 IP，只有 TCP/UDP 业务流量走 SK5；面板 SK5 卡片上已写明这一条。

命令契约（面板 ↔ agent，13 个动作，两端白名单逐字一致）：
`install_prereqs / init_pki / create_server / start_openvpn / stop_openvpn / restart_openvpn / create_user / revoke_user / set_sk5 / test_sk5 / enable_sk5 / disable_sk5 / get_status`。agent 发回执用 `id` 字段，面板侧 `id` 与 `cmd_id` 都接受（Cloudflare Worker 与 Flask 面板一致）。

## 一键安装

目标机：全新 Debian 12 / Ubuntu 22.04 / 24.04，root，amd64 或 arm64。

本项目无公开 git 仓库，不走 `git clone`：把整个 `openvpn-sk5-panel/` 目录拷到目标机（`scp -r` / `rsync` 任选），再进目录安装。

```bash
scp -r openvpn-sk5-panel root@<目标机>:/root/
ssh root@<目标机> 'cd /root/openvpn-sk5-panel && bash install.sh'   # 默认 OpenVPN UDP 1194
# 或 TCP 模式：
ssh root@<目标机> 'cd /root/openvpn-sk5-panel && OVPN_PROTO=tcp OVPN_PORT=443 bash install.sh'
```

安装完打印面板地址 `https://<服务器 IP>:8443` + 初始管理员密码（仅显示一次，也写在 `/etc/openvpn-sk5-panel/admin.pass`，0600）。重装不会轮换密码、CA 与服务端证书。

可选环境变量：`OVPN_PROTO`（udp|tcp）、`OVPN_PORT`、`OVPN_SUBNET`（固定 `10.8.0.0/24`，core 模板写死该子网；设为其他值安装器直接拒绝，否则 NAT 规则与已服务子网错位、出口断流）、`OVPN_DNS`（默认 `1.1.1.1`，写入 `server.conf` 的 `push "dhcp-option DNS …"`）；`SINGBOX_SHA256` / `TUN2SOCKS_SHA256`（见下「二进制校验」）。

`install.sh` 会做的事（幂等，可重跑）：

1. 断言安装目标不是现存部署目录（命中 `/root/flmx-panel` 即退出；已装 FLMX 的机器只会收到提示，不会被碰）。
2. `apt install` openvpn、easy-rsa、curl、jq、python3、pip 等；`iptables-persistent` 只在未装 ufw 的机器上装（与 ufw 冲突，装了会卸载 ufw；ufw 机上端口走 ufw 放行、NAT/FORWARD 规则仅 live 生效，重启后重跑安装器补回）。
3. 装 sing-box **1.11.15**（官方 GitHub release tar.gz，sha256 校验，失败即停）与 tun2socks **2.7.0**（备用）。
4. 复制 `core/`、`egress/`、`panel/`、`agent/`、`systemd/`、`verify-integration.sh` 到 `/opt/openvpn-sk5-panel/`；建 `/etc/openvpn-sk5-panel/`（0700）。
5. 调 `core/openvpn_manager.py` 初始化 PKI（`/etc/openvpn/server/easy-rsa`）+ 建服务端证书 + 渲染 `/etc/openvpn/server/server.conf`。
6. 写直连模式的 sing-box 初始配置（`/etc/openvpn-sk5-panel/sing-box.json`，`sing-box check` 通过才继续）。
7. 生成面板自签 TLS 证书；装 systemd 单元并启动 `openvpn-server@server`、`openvpn-sk5-singbox`、`openvpn-sk5-panel`。
8. 健康门禁：面板 `https://127.0.0.1:8443/api/me` 200，用 `admin.pass` 登录成功、`GET /api/status` 200 才算装完，否则报错退出。

## 部署方式二：Cloudflare 面板 + agent（推荐，FLMX 同款）

面板放 Cloudflare，中转机只装 agent。面板本体不直接碰 OpenVPN/sing-box，一切操作经命令队列下发给 agent 执行。

```bash
# 1. 部署 Worker（cloudflare/ 目录）：
cd cloudflare
wrangler kv namespace create PANEL_KV
wrangler secret put ADMIN_PASSWORD
wrangler deploy
# 注意：Cloudflare Workers 版本按 POP 慢速传播，部署 API 显示 100%
# 不等于各 POP 已生效，验活须换第二出口多点核（2026-11-10 教训）。

# 2. 在面板里注册节点（POST /api/nodes，登录后），拿到 token（只返回一次）。
# 3. 在中转机上装 agent（两步走；与面板“复制安装命令”生成的命令同口径）：
#    先用 -k 下脚本（面板默认自签证书，plain curl 会 TLS 校验失败），
#    再 sha256sum -c 校验通过才执行，校验失败即停；--node-name 必带且
#    须与注册名一致，否则 agent 默认用 hostname 注册，poll 恒 401。
#    bundle 的 sha256 校验由安装器内部 fail-closed 执行，见下。
curl -ksSL https://<面板>/install-agent.sh -o /tmp/install-agent.sh && \
curl -ksSL https://<面板>/install-agent.sh.sha256 -o /tmp/install-agent.sh.sha256 && \
cd /tmp && sha256sum -c install-agent.sh.sha256 && \
bash /tmp/install-agent.sh --panel-url https://<面板> --token '<节点TOKEN>' --node-name '<节点名>'
# agent 启动后每 5 秒 poll 拉命令；面板点“建服务、加用户、填 SK5”即下发。
```

agent 安装器本身也是 fail-closed（FLMX §1-13 同款）：远程下载 bundle
时先取 `$PANEL_URL/api/agent/bundle.sha256`（或 `$OVPN_AGENT_BUNDLE_SHA256`
环境变量）比对，通过才解压安装，无校验来源即拒绝安装。面板自 2026-11-12
起提供 `/api/agent/bundle.sha256` 端点（对 `_build_agent_bundle()` 的同一份
确定性 buffer 算 sha256，与 bundle 同源同版本），远程装 agent 不再卡在
这一步；本地 bundle 分支（仓库 checkout 内直接装）不受影响。

**面板证书信任（BUG-5）**：面板默认用自签 TLS 证书，agent 校验 TLS，
没有信任锚点时 poll 会永远报 `CERTIFICATE_VERIFY_FAILED`、命令链全断。
安装器在装 agent 时自动建立信任：先试系统信任库能直接验证的握手
（公网 CA 面板，如 Cloudflare 前端，什么都不用做）；验证失败时把面板
当前出示的证书 TOFU 钉到 `/etc/ovpn-agent/panel-ca.pem`，并写进
`config.json` 的 `ca_cert`。面板换证书后须重跑安装器 `--force` 重新钉。
也可显式给 `--ca-cert <panel.pem>`（直接钉该 PEM）或 `--insecure`
（跳过校验，**仅调试用**：token 与用户 .ovpn 可被中间人截获，面板
UI 与 agent 日志都会告警）。重装换 panel-url/token 后安装器会重启
已运行的 agent（BUG-6），旧进程不会继续用旧配置 poll。

服务器部署模式（方式一）与 Cloudflare 模式用同一套前端与命令契约：
同一 agent、同一 13 个动作，只是指向的面板地址不同（见
`cloudflare/server-mode.md` 对照表）。

> 限制（观察-1）：Cloudflare 模式的 Worker 兼容层目前只转发
> `port`/`proto`/`name`，面板上显式填的“对外地址”在该模式下暂不
> 起作用；agent 侧靠 core 的公网 IP 自动探测决定 `.ovpn` 的 remote。
> 如需显式指定，须在 Worker 兼容层补发 `server_ip`（不在本次修复范围）。

## 面板使用步骤

1. 浏览器打开 `https://<服务器 IP>:8443`，用初始密码登录（admin）。
2. **建服务**：确认协议/端口（UDP 1194 或 TCP 443），**对外地址**默认自动探测公网 IP（也可手动填公网 IP/域名，留空恢复自动探测）；若状态页提示 remote 为内网地址，站外客户端连不上，须改填公网地址。点启动。服务状态、在线用户在状态页看。
3. **加用户**：填用户名（`[a-zA-Z0-9_-]{1,32}`，`server` 与 `OpenVPN-CA` 为保留名、与服务端/CA 证书冲突而禁用），点创建，下载 `.ovpn`（CA/证书/私钥已内嵌，每个用户的证书 CN 就是用户名）。吊销用户后须重启 OpenVPN 服务才对新连接生效（CRL 只在启动时读）。
4. **填 SK5**：填商家给的 host、端口、用户名、密码；`fail_open` 默认关（断网保护，见下）；`udp_over_tcp` 默认关。**端口待确认：默认填 1001；若商家给的是 9000 请填 9000 并回报**（1001/9000 哪个是 SOCKS5 口尚未确认，面板字段旁同样标了这句）。
5. **一键启用**：勾选「启用 SK5 作为出口」保存。面板立即渲染 sing-box 配置、重启 sing-box、挂上 table 100 策略路由。
6. **验出口 IP**：状态页「当前出口 IP」应变成 SK5 的 IP；或在服务器上跑 `bash /opt/openvpn-sk5-panel/egress/test-egress.sh`（按源地址验 table/网关/出口 IP 三件套）。
7. **重建 CA（谨慎操作，平时不用）**：CA 泄露或要换发全部证书时，点 OpenVPN 服务卡片里的「重建 CA」按钮（两次确认）。重建销毁现有 CA、**全部已签发用户证书立即失效、旧 `.ovpn` 全部作废**；重建后须逐个重建用户并重新下载 `.ovpn`，再重启 OpenVPN 服务。接口 `POST /api/openvpn/init-pki {"force": true, "confirm": true}`（须登录；缺 `force`/`confirm` 任一即 400 拒绝；`node` 未传时单节点自动用唯一节点，多节点须指定）。Cloudflare 模式：Worker 兼容层已转发本接口（`POST /api/openvpn/init-pki → init_pki`，与 Flask 同款 force+confirm 校验、202 排队后按 `cmd_id` 轮询等真实结果）；手写命令仍可作备用：登录后 `POST /api/cmd {"node": "<节点名>", "action": "init_pki", "params": {"force": true, "confirm": true}}` → 202 排队，再按 `cmd_id` 轮询 `GET /api/cmd/<id>` 等 `done`/`failed`（live-verify-R5 §14.3 的实测路径：无 force 拒、无 confirm 拒、force+confirm 约 6 秒 done）。

## TCP / UDP 两种模式

| | UDP 模式（默认） | TCP 模式（商家只给 TCP 时） |
|---|---|---|
| OpenVPN | `proto udp`，端口 1194 | **必须切 `proto tcp`，端口 443** |
| SK5 出站 | `udp_over_tcp: false`，原生 UDP ASSOCIATE | `udp_over_tcp: true`，sing-box 把 UDP 包进 TCP |
| UDP 怎么通 | 商家 UDP relay 收 DNS/游戏 UDP，原样回包 | 商家只收 TCP，UDP 由 sing-box 在 TCP 里隧道化 |
| 性能 | 正常 | **TCP 套 TCP：重传放大、延迟抖动、丢包时卡顿明显** |
| 怎么验 | 面板「测试」里的 `udp_ok` 是真 UDP ASSOCIATE + DNS 回包 | 测试会起临时 sing-box 走 UoT 再测，`udp_mode` 标 `udp_over_tcp` |

两边必须一起改，只改一边会断。`test_sk5()` 的 `tcp_ok` 与 `udp_ok` 是两次独立拨测，TCP 通永远不会把 `udp_ok` 置 true。

## 故障策略：断网保护 vs 失败回直连

默认 **断网保护（`fail_open: false`）**：链路启用时 table 100 一直在。sing-box 或 SK5 一死，VPN 用户流量无路可走、直接丢包 —— **绝不会悄悄改走直连暴露真实出口 IP**。SK5 恢复后 sing-box 重连即恢复。

**失败回直连（`fail_open: true`）**：健康检查发现链路已死时撤掉 table 100，VPN 用户改走主表直连中转机出口。不断网，但出口 IP 会变回中转机 IP。适用：出口 IP 暴露可以接受、但业务不能断的场景。操作员在面板上点「关闭 SK5」是显式意图，本来就是恢复直连，与该开关无关。**单向性**：fail-over 后 `enabled` 已写 False 存盘，SK5 恢复后**不会自动回链**；须在面板上手动重新启用 SK5，链路才会恢复。

## 自检

```bash
bash /opt/openvpn-sk5-panel/verify.sh
# 或在仓库目录：bash verify.sh
```

逐项输出 `[PASS]` / `[FAIL]` / `[SKIP]`，最后汇总 `PASS=x FAIL=y SKIP=z`，FAIL 数即退出码。不依赖真实购买的 SK5：自检用本地 Python SOCKS5 stub（`127.0.0.1:1080`，端口被占时自动换空闲端口）+ 本地 HTTP 服务器验 TCP 转发；SK5 切换验的是真实的 `ip rule` / `table 100` / `ip route get ... from 10.8.0.1` 变化（须用本机 tun 地址作查询源，客户端地址不可）。

环境受限的项会如实记 `SKIP` 而不是假 PASS：沙箱无 `CAP_NET_ADMIN` 时路由项 SKIP；`ifconfig.me` 不可达时出口 IP 项 SKIP。注意本沙箱对 UDP sendto 一律 EPERM，UDP 数据面验证必须上真机。

自检不会覆盖已有 SK5：若面板里已配好启用的商家 SK5，切换测试自动 SKIP（密码无法从面板 API 取回，覆盖后无法还原）；`VERIFY_ALLOW_OVERWRITE_SK5=1` 可强制，但事后须在面板重填 SK5 密码。

## 常见问题

**SK5 只支持 TCP，怎么切？**
面板 OpenVPN 切 `proto tcp` / 端口 443（「建服务」里改，改完重启服务），SK5 勾选 `udp_over_tcp`，保存后点「测试」确认 `udp_ok: true` 且 `udp_mode: udp_over_tcp`。接受 TCP 套 TCP 的性能代价。

**`udp_ok: false`，但 `tcp_ok: true`？**
商家没开 UDP。先确认商家口径；确认只给 TCP 后按上面切 TCP 模式 + UoT，再测一次。不要只看 TCP 通就当 UDP 通了。

**VPN 连上但打不开网页？**
先跑 `egress/test-egress.sh`：看 `route get ... from 10.8.0.1` 是否走了 table 100；再看 `journalctl -u openvpn-sk5-singbox` 与 `/etc/openvpn-sk5-panel/sing-box.log`。MTU：tun1 与 OpenVPN 都按 1400 配，分片黑洞先查 MTU。

**`test_sk5()` 报 `tcp_ok: false`？**
先 `curl -v --socks5-hostname host:port http://ifconfig.me` 手动测一次；常见原因是 SK5 地址/端口/账号错，或商家侧 IP 白名单没放行中转机 IP。

**面板打不开 / 登录失败？**
`journalctl -u openvpn-sk5-panel -f` 看启动日志；密码只存在 `/etc/openvpn-sk5-panel/admin.pass`（0600），文件丢了只能从面板 SQLite 的哈希反推不了 —— 删 `panel/data/panel.db` 的 admin 行并重启面板会重新生成（会使旧密码失效）。

**重装 / 换协议后用户证书还在吗？**
在。CA 与用户证书只在首次安装生成，重跑 `install.sh` 不会动它们；只有删了 `/etc/openvpn/server/easy-rsa` 才会全部失效。

## 二进制校验

sing-box 与 tun2socks 的版本写死在 `install.sh`（1.11.15 / 2.7.0），不跟 `latest`。校验顺序（fail-closed，无校验来源即停，不只告警）：

1. 环境变量 `SINGBOX_SHA256` / `TUN2SOCKS_SHA256`（若设置，严格 64-hex 校验，优先于钉死值）；
2. 否则用钉死在脚本里的哈希（`install.sh:63-66` 与 `agent/agent.py:122-132` 逐键相等，amd64/arm64 各一；哈希由双锚核验取回：release 下载 URL 与 API asset 下载两路一致，tarball 二进制与同 release `.deb` 包内二进制逐字节一致，二进制自报版本核对 1.11.15 / 2.7.0）；
3. 否则用该 release 自带的校验清单（`checksums.txt`，其次 `SHA256SUMS.txt`）校验；
4. 三者都没有 —— **安装直接失败退出**，并打印取哈希重跑的命令。

升级 sing-box/tun2socks 版本时须同步改版本 + 四哈希（`install.sh` 与 `agent/agent.py` 两处），否则安装与 agent 装机双双 fail-closed。

一致性钉子（R2-P2-8）：`install.sh` 首装 starter 配置是手写 heredoc（以 `cat > "$CONFIG_DIR/sing-box.json" <<'EOF'` 开头的 heredoc），与 `egress/sing-box.json.template` 双份维护。行号随插入浮动，定位用该 marker（`verify.sh` 的 `starter-template-consistency` 格即按 marker 提取，不读行号）。**改模板必同步首装 heredoc**（tun 入站全字段与 `dns.final` 须一致；`route.final` 故意不同：starter 是直连模式 `direct`，模板是 SK5 链模式 `bought-sk5`）。`verify.sh` 的 `starter-template-consistency` 格逐项比对，不一致即 FAIL。

## 目录与集成约定

```
openvpn-sk5-panel/
  install.sh                 一键安装（本文件说明的全部步骤）
  verify.sh                  端到端自检（见上）
  verify-integration.sh      全链集成测试：面板 -> 命令队列 -> agent -> core/egress
  README.md                  本文件
  systemd/
    openvpn-sk5-panel.service    面板（TLS wrapper，见下）
    openvpn-sk5-singbox.service  sing-box 出口链（egress 约定的单元名）
  core/                      OpenVPN 本体（easyrsa.sh / openvpn_manager.py）
  egress/                    SK5 出口链（sk5_manager.py / policy-routing.sh）
  panel/                     面板（Flask，app.py，监听 8443；含 agent 队列接口）
  agent/                     agent（agent.py / install-agent.sh / ovpn-agent.service）
  cloudflare/                Cloudflare 部署（Worker + KV + wrangler.toml）
  docs/                      FLMX 对照普查（flmx-reference.md）与安全说明（security.md）
```

全链集成测试（沙箱实测，2026-11-12）：`bash verify-integration.sh` →
**PASS=29 FAIL=0 SKIP=0**。覆盖：面板起（nobody 身份，/tmp 副本数据，
未碰 /etc）、GET / 200 且含入站卡/SK5 卡标记、`/api/status` 未登录 401、
登录、登录后 `/api/status` 200 且含 openvpn/sk5/egress 键（R2-P1-4 常驻
回归：status() 变异恒 500 时本格必须变红）、注册节点拿 token、下发
`get_status` → agent `--once` poll→执行→
report → 回执 done、下发 `create_user`（无 CA）→ 回执 failed 且 error
非空、无私钥材料、无节点 token 泄露。沙箱无 openvpn/sing-box 真二进制，
`create_user` 的失败是预期内的干净失败（`no CA ... run init_pki() first`），
真机装完 PKI 后应为 done；UDP 数据面验证必须上真机（本沙箱 UDP sendto
一律 EPERM）。

约定（各 lane 已按实物核对）：

- PKI：`/etc/openvpn/server/easy-rsa/pki/`，服务端文件拷到 `/etc/openvpn/server/`（`ca.crt server.crt server.key dh.pem ta.key crl.pem`）；`install.sh` 调 `core/openvpn_manager.py` 的 `init_pki()` / `build_server_cert()` / `render_server_conf()`。
- 面板监听：`panel/app.py` 本身是 **8443 明文 HTTP**（见 `panel/README.md`）。`install.sh` 生成自签证书 + TLS wrapper（`/opt/openvpn-sk5-panel/run-panel-tls.py`，只 import 同一个 Flask app 并加 `ssl_context`），所以对外发布的 `https://<IP>:8443` 是真实的；`panel/` 下无任何文件被改动。
- 管理员密码：面板首次启动自己生成，写 `/etc/openvpn-sk5-panel/admin.pass`（0600），`install.sh` 不预生成，只在健康门禁后读回打印。
- SK5 状态：`/etc/openvpn-sk5-panel/sk5.json`（0600，含密码）、渲染后的 `/etc/openvpn-sk5-panel/sing-box.json`（0600）；`sk5_manager.py` 用 systemd 单元 `openvpn-sk5-singbox.service`（`ExecStart=/usr/local/bin/sing-box run -c /etc/openvpn-sk5-panel/sing-box.json`），没有该单元时回落到 nohup 后台。
- 面板 API（会话 cookie 登录，`POST /api/login {"password"}`）：`GET /api/status`、`POST /api/openvpn/users`、`GET /api/openvpn/users/<name>/ovpn`、`DELETE /api/openvpn/users/<name>`、`POST /api/openvpn/init-pki {"force": true, "confirm": true}`（重建 CA，见「面板使用步骤」第 7 步；走 `/api/cmd` 命令链入队 agent 执行，返回 202 + `cmd_id`，须轮询等真实结果）、`POST /api/sk5 {"host","port","username","password","enabled","fail_open?","udp_over_tcp?"}`（启用立即应用）。
- （已核实为误报，2026-11-12 集成收口纠正）：早先有报告称 `POST /api/sk5/enable` 与 `/api/sk5/disable` 调用了未 import 的 `sk5_set_enabled` 会 500；实测当前 `panel/app.py` 里根本没有 `sk5_set_enabled` 这个符号，两条路由正确调用已 import 的 `sk5_enable_fn()` / `sk5_disable_fn()`，一键启用/停用正常。`panel/README.md` 表里的 `/api/sk5/fail-open` 与 `/api/sk5/udp-over-tcp` 两条路由在 `app.py` 里均已实现（另见 `POST /api/sk5` 的 `fail_open` / `udp_over_tcp` 字段）。

## FLMX 对齐要点（对照普查见 docs/flmx-reference.md）

- **入站安装部署**：`install.sh` 是直线式一键安装脚本，无菜单（FLMX 的菜单式安装做法，本产品不抄）；无版本发现逻辑（sing-box/tun2socks 版本钉死在脚本里，见“二进制校验”一节）；无防降级三不变量；重跑幂等，不拒绝重装、无 `--force`、不备份旧 config（重装保留 CA/密码/证书，见上）。
- **一键安装命令 = secret + sha256 fail-closed**：面板生成命令时就把地址、校验钉死，agent 侧只按命令执行（FLMX 的“版本解析”一步 OpenVPN 不抄：agent 版本不按 channel 解析，钉在 bundle 的 sha256 上）。传输：Cloudflare 面板与服务器面板均为 HTTPS POST 轮询，agent 与面板之间无 WebSocket（FLMX 的 WebSocket 地址归一做法本产品不抄）。安装包（agent bundle、sing-box、tun2socks）一律 Release 资产 + 清单/环境变量哈希校验，无校验来源即停，不只告警。
- **配置下发 + 端口口径**：本产品无双哈希下发机制（FLMX 的期望哈希/已应用哈希做法，不抄）；配置经命令队列下发，面板只显示“已下发，等待 agent 执行…”瞬时提示，无“已下发/待下发/下发失败”三态。OpenVPN 服务端口默认建后只读，改端口须显式 `allow_port_change=true`（改后已发 .ovpn 须重下；换子网会让全部已发 .ovpn 失效，升级保留存量 `10.8.0.0/24` 与已签发 CA）。
- **面板 UI**：单页应用：页面路由只有 `/`（登录页即主界面），其余全是 `/api/*`；无 dashboard、nodes、servers、sk5、users、profile、change-password 这些页面路由（改密是顶栏按钮调 `POST /api/change-password`）；单页内是 `nodes`/`ovpn`/`users`/`sk5`/`logs` 等 section 卡片，没有 dashboard/servers/profile 独立页面。侧栏无分组小标题（用户 2026-11-04 裁定）；工具栏与卡片形似 FLMX（vanilla CSS 实现，非逐字 Tailwind class；顶栏不 sticky，仅侧栏 sticky）；玻璃适中（0.6–0.7），不做深色模式；文字对比度目标 7 / 底线 4.5，交付前渲染级自检、预览先行。
- **节点认领守卫**：agent 配置里的 `panel_url` 须与注册时绑定的逐字相等，否则拒绝认领；已有 `/etc/ovpn-agent/config.json` 且地址不同时，安装拒绝并提示先卸载旧 agent 或加 `--force` 人工确认，不覆盖。
- **SK5 凭据**：Flask 侧 `sk5.json` 存明文密码（0600，仅靠本机文件权限保护；`get_status()`、日志、报错里永不出现明文）；Worker 侧 SK5 密码 / `.ovpn` 私钥明文存 KV（见 `cloudflare/server-mode.md`）；FLMX 的“凭据只存密文”口径本产品不抄。agent 侧 `sk5.json` 600 权限；永不出现在 URL、日志、命令回显里；轮换走面板下发 + 原子替换（mktemp+mv），不走重装。

## 安全

- SK5 密码只存在 `/etc/openvpn-sk5-panel/sk5.json`（0600），`get_status()`、日志、报错里永不出现明文；不要把它贴进工单或日志。
- 面板自签证书浏览器会报不安全，属预期（无域名）；有域名时可把证书换成合法证书并重启 `openvpn-sk5-panel`。
- 面板以 root 运行（要操作路由/iptables/OpenVPN），只放内网或加访问控制，不要直接暴露到公网。
- **改密（不强制）**：初始管理员密码随机生成、无默认值；登录即给完整 admin 会话，不设改密前置条件。改密接口 `POST /api/change-password` 存在（须旧密码，新密码 ≥12 位且含字母＋数字），改密后 `session_version` +1，全部旧会话立即失效。**仅服务器（Flask）模式可用；Cloudflare 模式下管理员密码是 Cloudflare secret，面板内改密回 501，须用 `wrangler secret put ADMIN_PASSWORD` 修改后重新部署（R11-P2-1）。**注：Flask 面板密码哈希已是 bcrypt（`panel/app.py` `_hash_password`，存量加盐 SHA-256 哈希在登录成功时透明迁移到 bcrypt）；bcrypt 未安装的极简环境才回落旧的加盐 SHA-256。
- **登录限流（仅 IP 维）**：同一 IP 5 分钟内 5 次失败即锁 15 分钟，命中直接 429 + `Retry-After`。面板是单管理员密码登录，限流只看来源 IP。
- **权限（单管理员）**：面板只有管理员一种角色；`.ovpn` 下载、节点监控、SK5 配置、服务启停全部须管理员登录后才能用。写接口全部校验管理员会话，未登录调即拒绝。
- **已对齐（2026-11-12）**：面板密码哈希已换 bcrypt（存量加盐 SHA-256 哈希登录时透明迁移）；`/api/agent/bundle.sha256` 端点已于 2026-11-12 补上。两项均不再是待补项。

## 卸载（手动，无一键卸载脚本）

删前确认：下面命令会删除面板、CA 与全部用户证书（已发 .ovpn 全部失效），执行前先确认，删后不可恢复。

```bash
read -r -p "确认卸载 OpenVPN + SK5 面板并删除 CA 与全部用户证书？[y/N] " ans
[ "$ans" = y ] || [ "$ans" = Y ] || exit 1
systemctl disable --now openvpn-sk5-panel openvpn-sk5-singbox openvpn-server@server
systemctl disable --now openvpn-sk5-policy.service openvpn-sk5-healthcheck.timer
rm -rf /opt/openvpn-sk5-panel /etc/openvpn-sk5-panel
rm -rf /etc/openvpn/server          # 含 CA 与全部用户证书，删前确认
rm -f /etc/systemd/system/openvpn-sk5-panel.service /etc/systemd/system/openvpn-sk5-singbox.service
rm -f /etc/systemd/system/openvpn-sk5-policy.service /etc/systemd/system/openvpn-sk5-healthcheck.service /etc/systemd/system/openvpn-sk5-healthcheck.timer
systemctl daemon-reload
# NAT 规则：iptables -t nat -D POSTROUTING -s 10.8.0.0/24 -o <网卡> -j MASQUERADE
# FORWARD 规则（安装器写入的两条，须一并删，否则残留 ACCEPT 规则）：
iptables -D FORWARD -i tun0 -s 10.8.0.0/24 -o <网卡> -j ACCEPT
iptables -D FORWARD -i <网卡> -d 10.8.0.0/24 -o tun0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
# ufw 放行（仅 ufw 机上有；端口按实际 OVPN_PORT/PANEL_PORT，默认 1194/udp 与 8443/tcp）：
ufw delete allow 1194/udp
ufw delete allow 8443/tcp
# 然后 netfilter-persistent save（无 ufw 机）或确认 ufw 规则已删
```

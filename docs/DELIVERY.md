# OpenVPN + SK5 面板 · 交付说明（1.0.1）

> 发布包：`releases/ovpn-release-1.0.1.tar.gz`（包内清单与校验值见 §9；包自身的 sha256 全值见同目录伴生文件 `ovpn-release-1.0.1.tar.gz.sha256`）。
> 交付日期：2026-11-13。AUDIT-R34 已判**可交付（差集 ∅）**，live-19 真机轮**全部通过、零新 bug**。历史台账 175 条：已修 171、部分 2（按设计）、未验 1（P0-1，Cloudflare 真实部署）、新 0、复发 0。
> **未验清单（交付后仍未验，不冒充）**：Cloudflare Worker 真实部署（P0-1，见 §2）；arm64 安装校验（本机 x86_64，无 arm64 机）；SK5 端口 1001 vs 9000 仍待确认（面板默认 1001，见 §5）。

## 0. 这是什么

一台服务器作 OpenVPN 中转，面板点几下建协议、发用户，再一键把全部 VPN 用户的出口切到购买的 SOCKS5（SK5）。架构：面板（控制面，二选一部署）→ 命令队列 → 中转机上的 agent（每 5 秒 poll 拉取）→ core/（OpenVPN 本体）+ egress/（sing-box + 策略路由表 100）。OpenVPN UDP 1194 主、TCP 443 备，子网固定 `10.8.0.0/24`；SK5 死则流量黑洞，默认不断网回落（fail-closed）。

## 1. 服务器模式部署（面板 + 中转机同一台服务器）

### 1.1 目标机

全新 Debian 12 / Ubuntu 22.04 / 24.04，root，amd64 或 arm64。目标机须能出网（安装器下载 sing-box 1.11.15 与 tun2socks 2.7.0，均带 sha256 校验，失败即停）。

### 1.2 步骤（字段级）

```bash
# 首选：目标机上直接克隆公开仓库后安装
ssh root@<目标机> 'git clone https://github.com/iiiiiiiii7125-art/openvpn-sk5-panel && cd openvpn-sk5-panel && bash install.sh'
# 默认 OpenVPN UDP 1194；TCP 模式：
ssh root@<目标机> 'cd /root/openvpn-sk5-panel && OVPN_PROTO=tcp OVPN_PORT=443 bash install.sh'
```

安装器只按固定清单复制文件，克隆来的 `.git/` 不会进 `/opt`。

备选（目标机不能直连 GitHub 时）：传发布包再解包安装（本机执行；<目标机> 换成服务器 IP 或域名）：

```bash
scp releases/ovpn-release-1.0.1.tar.gz root@<目标机>:/root/
ssh root@<目标机> 'cd /root && tar xzf ovpn-release-1.0.1.tar.gz && cd openvpn-sk5-panel && bash install.sh'
```

可选环境变量：`OVPN_PROTO`（udp|tcp）、`OVPN_PORT`、`OVPN_SUBNET`（固定 `10.8.0.0/24`，设为其他值安装器直接拒绝）、`OVPN_DNS`（默认 `1.1.1.1`，写入 server.conf 的 `push "dhcp-option DNS …"`）。

`install.sh` 会做的事（幂等，可重跑）：断言安装目标不是现存部署目录（命中 `/root/flmx-panel` 即退出，已装 FLMX 的机器不会被碰）；apt 装 openvpn、easy-rsa 等；`iptables-persistent` 只在未装 ufw 的机器上装（与 ufw 冲突，装了会卸载 ufw；ufw 机上端口走 ufw 放行、NAT/FORWARD 规则仅 live 生效，见 §6）；装 sing-box 1.11.15 与 tun2socks 2.7.0；复制 `core/`、`egress/`、`panel/`、`agent/`、`systemd/`、`verify-integration.sh` 到 `/opt/openvpn-sk5-panel/`；初始化 PKI（`/etc/openvpn/server/easy-rsa`）+ 建服务端证书 + 渲染 server.conf；写直连模式 sing-box 初始配置（`sing-box check` 通过才继续）；生成面板自签 TLS 证书；装 systemd 单元并启动 `openvpn-server@server`、`openvpn-sk5-singbox`、`openvpn-sk5-panel`；健康门禁：面板 `https://127.0.0.1:8443/api/me` 200、用初始密码登录成功、`GET /api/status` 200 才算装完，否则报错退出。

### 1.3 登录与改密（装完第一件事）

- 面板地址：`https://<服务器 IP>:8443`。初始管理员密码**仅在安装完成时打印一次**，也写在 `/etc/openvpn-sk5-panel/admin.pass`（0600，root 可读）。重装不会轮换密码、CA 与服务端证书。
- **登录后立即改密**：面板右上角「修改密码」按钮（调 `POST /api/change-password`；成功后全部旧会话作废，须重新登录）。注意：首次登录**不强制**改密（P0-3，按设计未实现），改密全靠人工第一步，不要跳过。
- 自检：目标机上跑 `bash /opt/openvpn-sk5-panel/verify.sh`（24 项检查，逐项 PASS/FAIL/SKIP）。已在面板里填了真实 SK5 也不怕：SK5 已启用时切换测试（sk5-toggle / sk5-egress-ip / sk5-disable）自动 SKIP，什么都不改；只有显式设 `VERIFY_ALLOW_OVERWRITE_SK5=1` 才会强制跑切换测试，跑之前脚本先备份 `sk5.json` 与 `sing-box.json`、退出时原样恢复，无须事后重填 SK5。失败路径例外：清理失败时文件故意不恢复（大声 FAIL，链路诚实保持禁用，备份留在工作目录供人工恢复）。verify.sh 还会留下 `verify-*` 测试用户（脚本只建不删），属测试残留，面板行为本身正常。

## 2. Cloudflare 模式部署（面板放 Worker，中转机只装 agent）

> **未验标注：Cloudflare 模式从未在真实部署上验证（P0-1）。** `wrangler deploy --dry-run` 通过不等于部署可用；KV id 仍为占位符。本节步骤按 `cloudflare/README.md` 抄录，未经真机部署实测，部署后须按 §2.3 的方法验活再投入使用。

### 2.1 步骤

```bash
cd cloudflare
npm install -g wrangler        # 或 npx wrangler，下同
wrangler login                 # 交互登录；或用 Cloudflare API token（须有 Workers + KV 权限）

# 1. 建 KV 命名空间（生产 + 预览各一个）
wrangler kv namespace create PANEL_KV
wrangler kv namespace create PANEL_KV --preview
# 把两条命令输出的 id / preview_id 填进 wrangler.toml 对应位置
# （填之前 wrangler deploy 会报错，这是故意的：不许把假 id 提交上去）

# 2. 设管理员密码（只进 secret，不进文件）
wrangler secret put ADMIN_PASSWORD

# 2b. （Cloudflare 模式要给中转机装 agent 才需要）设安装包源站：
# 服务器模式面板的地址，例如 https://panel.example.com:8443
wrangler secret put AGENT_BUNDLE_ORIGIN

# 3. 部署
wrangler deploy
# 成功后得到 https://ovpn-sk5-panel.<你的子域名>.workers.dev
```

### 2.2 Cloudflare 模式的改密与 agent 源站

- 改密：Worker 的 `/api/change-password` 返回 **501**（面板按钮在 Cloudflare 模式下不可用）。轮换密码须 `wrangler secret put ADMIN_PASSWORD` 后重新 `wrangler deploy`。
- agent 安装依赖 `AGENT_BUNDLE_ORIGIN` 源站面板：源站须提供 `/install-agent.sh(.sha256)` 与 `/api/agent/bundle(.sha256)`；源站不可达或不提供时安装走不通（503/502 明示）。
- 面板证书信任：Cloudflare 前端是公网 CA，agent 直接信任，无须 TOFU 钉证书（服务器模式面板用自签证书，见 §3）。

### 2.3 部署验活（必做，不要只看 deploy 成功回显）

Cloudflare Workers 版本按 POP 慢速传播，部署 API 显示 100% 不等于各 POP 已生效（2026-11-10 实测：本机出口近 40 分钟仍回旧版，另一出口已是新版）。判定生效前必须换第二出口多点核：

1. 在本机 `curl $PANEL/api/nodes` 应为 401（未登录）。
2. 换一个出口再测一次（手机流量、另一台 VPS、或 Simular Box 的 shell 里 curl），两边都拿到新版行为才算生效。
3. 若一边新一边旧，等传播完成再测，不要反复重部署——重部署不会加速 POP 滚动。

## 3. agent 安装（中转机）

中转机只装 agent 时（Cloudflare 模式，或服务器模式的远程节点），用面板「复制安装命令」生成的两步命令，与 `agent/README.md` 同口径：

```bash
curl -ksSL https://<面板>/install-agent.sh -o /tmp/install-agent.sh && \
curl -ksSL https://<面板>/install-agent.sh.sha256 -o /tmp/install-agent.sh.sha256 && \
cd /tmp && sha256sum -c install-agent.sh.sha256 && \
bash /tmp/install-agent.sh --panel-url https://<面板> --token '<节点TOKEN>' --node-name '<节点名>'
```

字段说明：先用 `-k` 下脚本（面板默认自签证书，plain curl 会 TLS 校验失败），再 `sha256sum -c` 校验通过才执行，校验失败即停；`--node-name` 必带且须与注册名一致，否则 agent 默认用 hostname 注册，poll 恒 401；`--token` 只在注册节点时返回一次，轮换后重跑安装器并带新 token。bundle 的 sha256 校验由安装器内部 fail-closed 执行（远程下载 bundle 时先取 `$PANEL_URL/api/agent/bundle.sha256` 比对，通过才解压，无校验来源即拒绝安装）。

面板证书信任：服务器模式面板用自签 TLS 证书，安装器在装 agent 时自动建立信任：先试系统信任库能直接验证的握手（公网 CA 面板什么都不用做）；验证失败时把面板当前出示的证书 TOFU 钉到 `/etc/ovpn-agent/panel-ca.pem`，并写进 `config.json` 的 `ca_cert`。面板换证书后须重跑安装器 `--force` 重新钉。也可显式给 `--ca-cert <panel.pem>`（直接钉该 PEM）或 `--insecure`（跳过校验，**仅调试用**：token 与用户 .ovpn 可被中间人截获，面板 UI 与 agent 日志都会告警）。

本机离线装法：从包内直接跑 `bash agent/install-agent.sh --panel-url ... --token ...`，脚本检测到身边的 `agent.py` + `core/` 后走本地复制，不下载。

agent 启动后每 5 秒 poll 拉命令；面板点「建服务、加用户、填 SK5」即下发。agent 只主动外联面板，中转机不开入站口。

## 4. 面板流程（字段级）

登录面板后按顺序做：

1. **建服务**：服务卡片里建 OpenVPN 服务。默认 UDP 1194；要 TCP 443 模式在建服务时选 proto=tcp、port=443（建服务后改协议须重建服务；`allow_port_change` 为 false 时端口冻结，见 P01 口径）。
2. **设对外地址**：服务卡片「对外地址（.ovpn 的 remote，留空=自动探测公网 IP）」字段。留空自动探测公网 IP；多 IP / 内网穿透场景手动填公网地址；「自动探测公网 IP」按钮可一键探测。`.ovpn` 的 remote 即取该值。
3. **加用户**：用户卡片「新建用户名」字段填名 → 点「新建用户」→ 签发证书 → 在用户列表点「下载 .ovpn」导入客户端即可连接。吊销后须重启 OpenVPN 服务才对新连接生效。**不要点「重建 CA」**：重建 CA 会销毁现有 CA，全部已签发用户证书立即失效、旧 .ovpn 全部作废，重建后须逐个重建用户并重新下载 .ovpn（按钮有两次确认，仍请勿误点）。
4. **填 SK5**：左侧导航「SK5 出口」卡片，字段：`SK5 地址（host）`（例如 `proxy.iproyal.net`）、`端口`（默认 1001，见 §5）、`用户名`、`密码`。填完勾选「启用 SK5 作为出口」。
5. **一键启用**：点「一键启用」按钮。成功后卡片徽标变「已启用」，顶栏「当前出口 IP」与「出口 IP」字段显示 SK5 的出口 IP（后缀「经 SK5 出口」）。
6. **验出口 IP**：客户端连上 VPN 后访问 `ifconfig.me`，出口 IP 应为 SK5 的 IP；面板「当前出口 IP」字段应一致。若显示「直连出口」或 IP 为中转机本机 IP，说明链路未走 SK5，按 §8 排查。

## 5. SK5 填写口径

- **SK5 凭据由用户自己在面板里填，绝不在聊天里要密码。** 本交付不含任何 SK5 账号密码；面板存量 SK5 密码为明文存储（设计决定，见 README），不要把面板数据库发给任何人。
- **端口默认 1001，1001 vs 9000 仍待确认。** 面板 `端口` 字段默认填 1001；若商家给的是 9000，请填 9000 并回报。TCP 与 UDP 必须双通——验收要求 TCP 和 UDP 都走 SK5；若购买的 SK5 只通 TCP，OpenVPN 须用 TCP 443 模式。
- SK5 拨测：面板「测试」按钮先做 TCP 拨测再做 UDP 拨测（native UDP ASSOCIATE + DNS to 1.1.1.1:53；无应答时重试第二档 cloudflare.com / 8.8.8.8），两项都 ok 才算链路可用。

## 6. 已接受的限制清单（交付时即如此，不是 bug）

| # | 限制 | 说明 |
|---|---|---|
| 1 | ufw 机 NAT/FORWARD 规则 live-only | ufw 机器上安装器加的 NAT MASQUERADE 与 FORWARD 规则只在内存里，不 survive 重启；重启后重跑 `bash install.sh` 补回（install.log 有明文提示，README:71）。SK5 数据面不受影响（tun0↔tun1 规则由策略路由 enable 时加）。 |
| 2 | DNS 默认走直连 | sing-box 模板规则 `protocol dns / port 53 → direct`：VPN 用户的 DNS 查询走中转机直连 IP，不经 SK5；只有 TCP/UDP 业务流量走 SK5。面板 SK5 卡片上已写明。 |
| 3 | fail-open 单向 | SK5/sing-box 死后流量黑洞（不断网回落）；fail-open 须显式开启，且一旦 fail-over，enabled 保持 False，须手动重开。 |
| 4 | 5 秒窗口（O-R25-2） | `enable()` 等 LIVE tun1，只等 5 秒：sing-box 启动慢于 5 秒时 enable 大声失败（`sing-box did not create a live tun1 within 5 s`），不建占位符、不改策略状态、enabled 保持 False，重试即可。本机（512MB）暖启动 0.84 秒，充足；若某机 sing-box 恒慢于 5 秒（持续过载或极慢磁盘），每次 enable 均会失败、永不收敛——这是 5 秒硬截止的设计取舍。 |
| 5 | 面板客户端列表约 60 秒滞后 | OpenVPN 状态文件刷新周期所致，新连接后须等一档才出现在面板列表；在线数以状态文件为准。 |
| 6 | arm64 未在真机验过 | 本机 x86_64，无 arm64 机；门禁 §7 的 arm64 绑定只在沙箱变异树上验过。 |
| 7 | Cloudflare 模式未验 | 见 §2，未在真实部署上验证（P0-1）。 |
| 8 | 首登不强制改密 | P0-3，按设计未实现；改密全靠 §1.3 的人工第一步。 |
| 9 | 启用失败 500 vs 禁用失败 200+error | 诚实不对称（设计），仅展示差异。 |

## 7. 升级与备份

- **升级**：把新版发布包传到服务器、解包、默认重跑 `bash install.sh`（无任何 flag）。重跑不销毁线上 `panel.db`（R8-BUG-1 已修，并经 live-9 至 live-19 共十一轮毒树默认重跑行级终验：admin/nodes/queue 行级一致，audit 仅增合法登录行）。重装不会轮换密码、CA 与服务端证书。
- **升级前备份**（必做）：`cp -a /opt/openvpn-sk5-panel/panel/data /root/panel-data-backup-$(date +%Y%m%d)`。`panel/data/` 内含 `panel.db`（管理员、节点、审计）与 `agent_queue.json`（命令队列，内含 SK5 明文密码与 .ovpn 私钥回执）——备份文件本身须按凭据保管，不要外发。
- **回滚**：升级出问题时停面板服务，把备份的 `panel/data/` 拷回 `/opt/openvpn-sk5-panel/panel/data/`，重起 `openvpn-sk5-panel` 服务。

## 8. 故障速查

| 现象 | 含义 / 做法 |
|---|---|
| enable 报 500：`sing-box did not create a live tun1 within 5 s` | sing-box 5 秒内没建出活 tun1（启动慢或启动失败）。不建占位符、不改策略状态、enabled 保持 False。查 `journalctl -u openvpn-sk5-singbox` 与 sing-box 日志，修好后重点启用。 |
| 健康检查报 `blackholed_kill_switch` | sing-box 死了，流量被表 100 的黑洞兜住、没走直连。等 systemd 自动重起（8 秒内）或手动重起 sing-box，下一档健康检查翻 `policy_repaired`。 |
| 健康检查报 `policy_missing` | 真正的危险态：repair 脚本失败，或黑洞/rule 缺失。查 `journalctl -u openvpn-sk5-healthcheck` 与 `/etc/openvpn-sk5-panel/sk5.json` 是否损坏（损坏时 restore 大声失败、策略状态不动，见 live-16 §9.2）。 |
| 面板 `policy_routing_active: false` 但 `via_sk5: false` | 诚实状态：策略未生效，出口未经过 SK5。不要只看顶栏 IP——`via_sk5: false` 时 IP 是直连出口。 |
| 客户端能连隧道但数据全死（curl 超时） | 链路在黑洞态或 restore 损坏态：先看面板 SK5 卡片与 `ip rule` / `ip route show table 100`；sk5.json 损坏时 restore 单元 exit 1 且策略状态字节不变，须手工修文件后重开。 |
| 客户端列表为空但刚连上 | 状态文件约 60 秒滞后，等一档再看（§6-5）。 |
| agent poll 恒 401 | `--node-name` 与注册名不一致，或 token 已轮换：重跑安装器并带正确 `--node-name` 与新 `--token`。 |
| agent 日志 `CERTIFICATE_VERIFY_FAILED` | 面板证书信任未建立：重跑安装器（TOFU 钉证书，见 §3）；面板换证书后重跑 `--force`。 |

## 9. 发布包清单与校验

发布包：`releases/ovpn-release-1.0.1.tar.gz`（顶层目录 `openvpn-sk5-panel/`）。包内清单（90 个文件；不含 `tests/`、`__pycache__`、`*.pyc`、`.gitignore`、`cloudflare/.wrangler`、`panel/data/` 内一切运行时文件）：

- 顶层：`install.sh`、`verify.sh`、`verify-integration.sh`（29 格门禁，见下）、`README.md`
- `panel/`：`app.py`、`requirements.txt`、`README.md`、`templates/index.html`、`static/contrast-check.py`
- `core/`：`openvpn_manager.py`、`easyrsa.sh`、`server.conf.template`、`client.ovpn.template`、`README.md`、`tests/test_status_log.py`
- `agent/`：`agent.py`、`install-agent.sh`、`ovpn-agent.service`、`README.md`
- `egress/`：`sk5_manager.py`、`policy-routing.sh`、`sing-box.json.template`、`test-egress.sh`、`README.md`
- `systemd/`：5 个单元（`openvpn-sk5-panel`、`openvpn-sk5-singbox`、`openvpn-sk5-policy`、`openvpn-sk5-healthcheck` 服务＋定时器）
- `cloudflare/`：`src/index.js`、`wrangler.toml`、`README.md`、`server-mode.md`
- `docs/`：本文件、`security.md`、`flmx-reference.md`、live-verify 报告 20 份、`audit/` 审计报告 34 份（AUDIT-R1–R34）

关键文件 sha256（前 12 位；与 live-19 §0 的树版本逐项一致）：

| 文件 | sha256（前 12 位） |
|---|---|
| install.sh | `3f050f037e7a` |
| egress/sk5_manager.py | `6eaf4d59ec35` |
| egress/policy-routing.sh | `fbfb29a49164` |
| panel/app.py | `f7f60fa53bd0` |
| cloudflare/src/index.js | `71c33ffe46c7` |
| agent/agent.py | `f303af828555` |
| core/openvpn_manager.py | `3b5d7dfe9ea1` |
| verify-integration.sh | `2d110ff4ffec` |
| verify.sh | `e36fc2003503` |

核对方法（本机）：`sha256sum -c releases/ovpn-release-1.0.1.tar.gz.sha256`；解包后 `tar tzf releases/ovpn-release-1.0.1.tar.gz | wc -l` 应为 90 个文件 + 目录条目。门禁：`bash verify-integration.sh` 应为 `PASS=29 FAIL=0 SKIP=0`（29 格，含 §7 哈希钉死两层；脚本用固定 `/tmp/ovpn-int-test`＋8443 端口，须串行跑）。

## 10. 审计与真机证据索引

- 审计：`docs/audit/AUDIT-R34.md`（189 行，可交付，差集 ∅）为终审；此前 R26–R33 各轮差集 1–3 条（R27 一 P1 其余全 P2）均已修复闭合，历史 175 条全在 R34 §6 复扫（171 已修、2 部分按设计、1 未验 P0-1、0 复发）。
- 真机：`docs/live-verify-R19.md`（197 行，全部通过、零新 bug）为终轮；R27–R33 修复格全过（verify.sh 强制路径 API 优先恢复、UDP verdict 往返实证、Worker 队列 TTL、toggle／1.0／信封／bcrypt 双面、enable 窄带 4.7 秒、前/端预拦零请求），headline-9 毒树重跑硬门通过；S0–S4 与 headline 六项全过。
- 探针资产在包外：`tests/` 未进发布包（开发验证用，见树内 `tests/README.md`）。

# FLMX 对照普查 — OpenVPN 面板照抄/改写表

> 只读普查。仓库 `~/workspace/flvx-max`，HEAD `a99d68d4`，普查时 `git diff` 为空、零修改；453 条 `??` 均为普查前已存在的未跟踪审计输出，与本次无关。
> 约定：`照抄` = 原样搬；`改写` = 机制照抄、字段/协议换成 OpenVPN；`不抄` = 不适用或 FLMX 本身有坑。
> 另读了 `~/workspace/flvx-max/AGENTS.md` 与 `vite-frontend/AGENTS.md`（API 信封、JWT、UI 导入口径见 §0）。

## §0 全局口径（两份 AGENTS.md，先定再抄）

| # | FLMX 原做法（文件:行） | 结论 | OpenVPN 映射 |
|---|---|---|---|
| 0-1 | API 信封统一 `{code,msg,data,ts}`，code 0 成功。`vite-frontend/AGENTS.md`；`flvx-max/AGENTS.md` | 未抄（待定） | 未实现：本产品三端一律 `{ok, error}` 信封（`panel/app.py`、`cloudflare/src/index.js`），`"code"` 全树零命中；poll/report/命令结果均走 `{ok, error}` |
| 0-2 | Auth：`Authorization` 头放**原始 JWT，不带 `Bearer` 前缀**。两份 AGENTS.md 均明文禁止 Bearer | 改写（已裁定） | 节点 token 走 `Authorization: Bearer <node_token>`（Flask `panel/app.py` + Worker `cloudflare/src/index.js` + agent 三端一致）。FLMX 该条禁的是 **JWT** 带 Bearer 前缀；本面板管理端不用 JWT（HttpOnly 会话 cookie），节点 token 本身就是 bearer 凭据，用 Bearer 与会话 cookie 区分开，不改。 |
| 0-3 | 后端只经 Repository 方法读写 DB，禁止直用 `repo.DB()`；GORM 模型必定义 `TableName()`；禁用 `type:jsonb`/`type:serial`（SQLite 不兼容）。`flvx-max/AGENTS.md` | 未抄（待定） | 未实现：Python 直连 sqlite，无 Repository 层；`TableName` 全树零命中 |
| 0-4 | 前端只从 `src/shadcn-bridge/heroui/*` 导入，禁 `@heroui/*`/`@nextui-org/*`；`globals.css` 必须 import `tailwind-theme.pcss`，否则语义 class 失效。`vite-frontend/AGENTS.md` | 改写 | OpenVPN 面板若用 React+Tailwind，照抄这条；若用现有单 HTML 面板，则不抄、只抄视觉值（§2） |
| 0-5 | 三模块 Go 1.25；agent 用 `CGO_ENABLED=0` 构建后 UPX 压缩。`flvx-max/AGENTS.md` | 不抄 | OpenVPN agent 是 Python，不适用；但“静态单文件、易分发”这个目标照抄 |

## §1 入站安装部署

### 1.1 面板安装（panel_install.sh，1694 行）

| # | FLMX 原做法（文件:行） | 结论 | OpenVPN 映射 |
|---|---|---|---|
| 1-1 | 交互菜单 6 项：1 安装面板 / 2 更新面板 / 3 卸载面板 / 4 迁移 PostgreSQL / 5 配置域名反代（自动 HTTPS）/ 6 退出。`panel_install.sh:616-630 show_menu` | 不抄 | OpenVPN 安装脚本是直线式一键安装，无菜单；迁移/域名反代等能力不在安装脚本里 |
| 1-2 | 版本发现优先级：`VERSION > FLUX_VERSION > PINNED_VERSION > 最新 Release`；脚本自带定宽版本号（如 `20261022.01`，`YYYYMMDD.NN` 形）。`panel_install.sh:18-22,166` | 未抄（待定） | 未实现：本树无定宽脚本版本号、无版本发现优先级；agent 版本钉在 bundle 的 sha256 上（见附 1），不按 channel 解析。 |
| 1-3 | 防降级三不变量：定版一致（下载副本 `PINNED_VERSION` 须等于目标版）、方向单调（新脚本版须高于当前版）、格式可辨认，否则跳过自更新。`panel_install.sh:34-92` | 未抄（待定） | 未实现：本树无版本比较／防降级逻辑（`install.sh` 与 `install-agent.sh` 均无 `VERSION` 比较、`PINNED_VERSION`、降级拒绝）；agent 升级只校验 bundle sha256。 |
| 1-4 | 已部署守卫：同目录已有 `.env` + `docker-compose.yml` 时默认拒绝安装，提示走“更新”；确需重装须 `PANEL_FORCE_REINSTALL=1` 且先备份 `.env` 为 `.env.bak.<时间戳>`。`panel_install.sh:1241-1265 install_panel`（F-049） | 照抄 | 照抄；agent 路 `install-agent.sh` 已有“拒绝 `/root/flmx-panel`”断言，**再加**同款“已有部署须显式 `--force` + 备份旧 config” |
| 1-5 | 密钥生成：`JWT_SECRET` / PG 口令 32 字符（约 190 bit，F-120 由 16 字符加长），`/dev/urandom` 字母数字。`panel_install.sh:631-638 generate_random` | 照抄 | 面板 JWT secret、节点 token、agent 注册 token 全部 32 字符 urandom；禁止写死默认值 |
| 1-6 | `.env` 写法：`JWT_SECRET / FRONTEND_PORT / BACKEND_PORT / FLUX_VERSION / DB_TYPE / DATABASE_URL`，`upsert_env_var` 用 awk 原子替换（mktemp + mv）。`panel_install.sh:640-660,1300+` | 未抄（待定） | 未实现：无 `.env` 文件、无 `OVPN_VERSION`（全树零命中）；配置写盘用 heredoc 直写，非 mktemp+mv |
| 1-7 | Docker 先验证后选版：先配 Docker IPv6 并验证可用才选 v6 版 compose，否则明确降级 v4 并告知；安装 Docker 走阿里云镜像源或 `apt docker.io`。`panel_install.sh:352-381,1280-1300` | 改写 | 面板走 Docker 部署时照抄；agent 侧不装 Docker，改为“先检测 TUN 设备 + `ip` 命令可用才继续，否则明确报错退出” |
| 1-8 | 升级保留存量网络：升级替换 compose 前保留存量网络子网，模板子网只对全新安装生效。`panel_install.sh:987-994,1046` | 照抄 | 面板升级保留存量 `10.8.0.0/24` 与已签发 CA；模板子网只用于全新安装——**这是 OpenVPN 的关键项：换子网会让全部已发 .ovpn 失效** |
| 1-9 | 卸载：未检测到 Docker 时直接返回失败（不为卸载反向装 Docker）；有 compose 才 `down`；删除前交互确认 `y/N`，默认取消。`panel_install.sh:1594-1627 uninstall_panel` | 未抄（待定） | 未实现：无卸载脚本；根 README:265 只有手动卸载命令、无交互确认、无“同时吊销全部用户证书”选项 |

### 1.2 节点 / agent 安装命令（核心，照抄最多的一节）

| # | FLMX 原做法（文件:行） | 结论 | OpenVPN 映射 |
|---|---|---|---|
| 1-10 | 面板生成一键命令的入口：`POST /api/v1/node/install`，`{id, channel}`。`go-backend/internal/http/handler/handler.go:285`；`mutations.go:1044-1104 nodeInstall` | 照抄 | 已实现（仅 Worker）：`POST /api/nodes/{id}/install` 返回 fail-closed 命令模板（`<NODE_TOKEN>` 占位）；Flask 侧无此接口，由前端 `buildInstallCommand` 就地拼装；完整命令（含 token）只在注册/轮换返回时给一次，前端注册后直接展示并可复制。`channel` 概念未抄：agent 无版本通道，版本钉在 bundle 的 sha256 上。 |
| 1-11 | 命令生成三步：① 按 channel 解析最新 Release 版本（失败即 `-2` 报错，不给旧版命令）；② 取节点 secret（`GetNodeSecret`）；③ 取面板地址（`GetViteConfigValue("ip")`，未设置时报错“请先前往网站配置中设置ip”）。`mutations.go:1063-1083` | 未抄（待定） | ① 未实现：无 channel 解析，agent `VERSION = "0.1.0"` 静态自报（根 README:249 已明文“版本解析一步 OpenVPN 不抄”）；② 节点 secret 同款已实现（见 1-10）；③ 面板地址缺失即硬报错已实现（`install-agent.sh:86` `--panel-url is required`） |
| 1-12 | 地址归一（FIX2-C #2）：面板地址统一成显式 scheme——`http/ws → ws://`，`https/wss → wss://`，裸地址按面板实际 scheme 补；**禁止 agent 自动降级**，裸地址默认 `wss`。`mutations.go:1015-1043 normalizeNodeInstallAddr` | 不抄 | agent 与面板之间是 HTTPS POST 轮询，无 WebSocket；地址就是面板 HTTPS URL，无需归一 |
| 1-13 | 安装命令本体（F-060，fail-closed）：先 `curl -fsSL <release>/install.sh` + 同目录 `install.sh.sha256`，`test "$(awk …sha256)" = "$(sha256sum …)"` 通过才 `chmod +x` 执行，任一步失败整条 `&&` 链中止；代理模式在 URL 前加 `PROXY_URL`。`mutations.go:1086-1102` | 照抄 | 已实现（命令形，J Lane 后强制校验）：面板生成的安装命令先取 `install-agent.sh`，再取 `.sha256`——`.sha256` 必须取到且 `sha256sum -c` 通过才执行，缺失或验不过即停，不许警告后继续（与 `install-agent.sh` 自身的自检语义不同：自检分支是旧面板兼容，见 AUDIT-R3 观察）。已补：Flask 侧 `/install-agent.sh.sha256` 端点已提供（`panel/app.py`，哈希与脚本字节相符，主控已验），安装命令全程硬校验。 |
| 1-14 | agent 安装器参数：`./install.sh -a <面板地址> -s <节点secret>`，`getopts "a:s:"`。`mutations.go:1097-1101` | 照抄 | `install-agent.sh --panel-url <panel_url> --token <node_token>` 同款（仅长选项，无 `-a`/`-s` 短选项） |
| 1-15 | agent 二进制分发：`VERSION` 解析后拼 `https://github.com/<REPO>/releases/download/<VERSION>/gost-<ARCH>`，下载后取同 URL + `.sha256` 强校验，缺校验文件/无 `sha256sum` 均拒绝安装（H-01）。 | 照抄 | agent 二进制（或 agent bundle）同款：Release 资产 + `.sha256` 派生校验，fail-closed；集成路已指出的 sing-box/tun2socks 哈希未钉问题，用同一办法解（随 release 发 `checksums.txt`，无清单即停） |
| 1-16 | agent 配置落盘：`INSTALL_DIR=/etc/flux_agent`，每次安装**总是新建** `config.json`（`{"addr","secret"[,"proxy"]}`），`gost.json` 已存在则跳过（`{}`），全部 `*.json` `chmod 600`。 | 部分抄 | “每次安装新建”假：安装器重装保留旧 config（无 `--token` 沿用旧 token，`install-agent.sh:41-44`），且 3-6 行明言不抄“总是新建覆盖”——本行与 3-6 矛盾，以 3-6 为准；`sk5.json` 安装器根本不碰（零命中），“已存在则跳过不覆盖”空洞为真；600 权限属实 |
| 1-17 | agent 服务：`flux_agent.service`（systemd，另有 OpenRC 兜底），`systemctl start` 前先 `reset-failed`（防限速），启动后必须判活进返回码（失败分支末条不许是 `echo`，R2X-019）。 | 照抄 | `ovpn-agent.service` 同款：`reset-failed` → `enable` → `start` → 判活失败返回非零；OpenRC 兜底可不抄（目标机均为 systemd） |
| 1-18 | agent 升级防降级：`panel_version_cmp` 比版本，目标版低于当前版拒绝降级。 | 未抄（待定） | 未实现：本树无版本比较函数，agent 自升级只校验 bundle sha256，不比版本、不拒降级。 |

### 1.3 入站模型（go-backend 模型层）

| # | FLMX 原做法（文件:行） | 结论 | OpenVPN 映射 |
|---|---|---|---|
| 1-19 | 内核与入站分层：`NodeKernel`（`node_id + kernel_type` 唯一，`Version / InstalledVersion / Status / ConfigHash / AppliedHash / Enabled`）；`NodeInbound` 挂在内核下。`go-backend/internal/store/model/node_kernel.go:4-22` | 部分抄 | OpenVPN 面板：`NodeKernel` → `NodeService`（`node_id + service_type=openvpn/sing-box` 唯一，`Version/InstalledVersion/Status/Enabled` 照抄）；`NodeInbound` → `OvpnServer`。双哈希字段不抄——本产品无双哈希下发机制（见 §1-30） |
| 1-20 | 入站字段（`NodeInbound`，`node_kernel.go:23-120`）：`Name / Protocol(varchar30) / Listen(默认 '::') / Port(int) / Transport,Security,Settings,Extra(TEXT 存 JSON) / ShareAddressMode(auto/ipv4/ipv6/custom) / ShareHost / RelayOnly / AcceptProxyProtocol / RelayWhitelist / WhitelistExtra / Enabled / Inx / SourceID` | 改写 | `OvpnServer` 字段：`Name / Proto(udp/tcp) / Listen / Port / Subnet(10.8.0.0/24) / Cipher / Auth / TunMtu / MssFix / Dns / Settings(TEXT JSON：push 路由等) / Enabled / Inx`；`Transport/Security` 两字段合并为 `Proto + Cipher/Auth`，其余照抄 |
| 1-21 | 链式出站字段：`OutboundID`（0=直连，>0=链到另一入站）；`SplitRules`（分流 JSON）；`OutboundIPStrategy`（默认 `auto`）。`node_kernel.go:OutboundID/SplitRules/OutboundIPStrategy` | 未抄（待定） | 未实现：`Sk5ProfileID`／`OutboundIPStrategy` 全树零命中；面板只有按节点 `sk5cfg:<name>`，无 profile 模型、无策略字段 |
| 1-22 | 分配模型：`UserInbound`（`user_id + inbound_id + relay_id` 唯一；`RelayID=0` 直连，`>0` 指定中转）。`model.go:286-296` | 改写 | OpenVPN 用户分配：`OvpnUserServer`（`user_id + server_id` 唯一）；`RelayID` 语义改为 `Sk5ProfileID`（0=直连，>0=指定 SK5），唯一键照抄 |
| 1-23 | 订阅计量伴生入站：`CompanionOf / MeteringEnabled`（仅 SS2022，伴生入站按订阅发独立凭据以便按订阅计量）。`node_kernel.go:CompanionOf/MeteringEnabled` | 不抄 | OpenVPN 无订阅计量需求，不抄；但“伴生行对用户隐藏、不进备份”的做法记下，SK5 凭据行若入库同样隐藏 |
| 1-24 | 端口铁律 P01：入口段端口创建时严查本节点占用并避开（`节点 %s 端口 %d 已被占用`，`mutations.go:2036`；`control_plane.go:529`），**创建后永不换口**（更新不带端口时保持原端口，`inbound_port_r1_test.go:35 TestR1B7`） | 照抄 | OpenVPN 服务端口同款铁律：建服务时查本节点占用（含 OpenVPN/sing-box/系统端口）并避开；建后端口字段只读，改端口 = 删了重建；其它段（SK5 出口）换 SK5 不换端口 |
| 1-25 | 协议×内核不匹配直接拒绝并明示（用户立规，见 MEMORY；前端按 capabilities 过滤可选协议）。`vite-frontend/src/pages/inbound/presets.ts`；`inbound-form-modal.tsx:146-203` 按 `capabilities.transports/securities` 联动 | 照抄 | 已实现（两层）：① Worker 服务端硬拒——服务是 UDP 模式，且同一地址的 SK5 最近一次 `test_sk5` 明确 UDP 失败时，`POST /api/sk5` 直接 400 并明示“请切 TCP 443 或换支持 UDP 的 SK5”；未测过的不拦。② 前端确认——UDP 模式 + 最近一次 UDP 测试失败过时，保存 SK5 前弹窗确认。`Proto=tcp` 时允许 TCP-only SK5。 |

### 1.4 配置下发通道（面板 → agent）

| # | FLMX 原做法（文件:行） | 结论 | OpenVPN 映射 |
|---|---|---|---|
| 1-26 | 下发通道是 WebSocket：路由 `mux.Handle("/system-info", h.WebSocketHandler())`，`go-backend/internal/http/router.go:13`；实现 `go-backend/internal/ws/server.go`（gorilla/websocket） | 改写 | FLMX 用常驻 WSS；OpenVPN agent 用**轮询**（每 5 秒 `POST /api/agent/poll`）已定，不改——但要抄 WSS 的三点：会话鉴权、加密、掉线重连退避（agent 路已有 5s→60s 退避，照抄） |
| 1-27 | 节点会话鉴权：建连带 `?secret=<节点secret>`，`GetNodeBySecret` 查库，`validateNodeSession` 每周期复核“节点仍存在且 secret 未轮换”，删节点/换 secret 后存量会话最迟一个周期被踢。`ws/server.go:247-250,315-340,598-631` | 照抄 | agent 轮询每次带 `node_token`，面板侧每次查库复核（节点删除/token 轮换后下次 poll 即 401）；token 轮换流程照抄：面板生成新 token → agent 下次 poll 拿新 token 失败 → 面板显示“重新下发安装命令” |
| 1-28 | 消息加密：每条节点消息用节点 secret 派生 AES 加密（`security.NewAESCrypto(secret)` 缓存复用）。`ws/server.go:36-42,628-631`；`encryptedMessage{Encrypted,Data,Timestamp}` | 改写 | 轮询走 HTTPS 已有 TLS，**不抄**消息层 AES；但命令回执里 SK5 密码、.ovpn 私钥段**永不进明文日志**，照抄该加密精神（agent 路已做：密码不进日志） |
| 1-29 | 会话名额与限流：admin/monitor 两入口共用会话名额预留（R2X-022，预留失败要回滚）；`/system-info` 未认证失败按 IP 固定窗口限流。`ws/server.go:87-125,399-423` | 未抄（待定） | 未实现：全树命令限流零实现；唯一 429 是登录锁（`panel/app.py:1249`）；`agent_poll` 内无限流／锁逻辑 |
| 1-30 | 配置一致性双哈希：`NodeKernel.ConfigHash`（面板期望）vs `AppliedHash`（agent 已应用），不一致即未下发/下发失败；agent 丢了已确认配置要重发（`kernel.go:2308` 注释）。`node_kernel.go:4-22` | 不抄 | 本产品无双哈希字段；配置经命令队列下发，面板只显示“已下发，等待 agent 执行…”瞬时提示，无“已下发/待下发/下发失败”三态；agent 重启后没有按哈希对账、自动拉全量配置的机制（无哈希可对） |
| 1-31 | 流量上报：`/flow/config` + `/flow/upload`，仅凭节点 secret 鉴权（H-17 备注：伪造 secret 可伪造流量，属已知口径）。`handler.go:444-445`；`flow_upload_batch.go:61` | 改写 | OpenVPN 面板：agent 心跳里带 `online_users / bytes_up / bytes_down` 即可，不单独做流量上报接口；H-17 的教训照抄——心跳只采信已鉴权节点的自报，面板侧不以此做计费 |
| 1-32 | 在线状态：节点 `Status / Version / HTTP / TLS / Socks` 字段 + `TCPListenAddr / UDPListenAddr`；面板实时状态经 WSS 推。`model.go:75-110 Node` | 未抄（待定） | 未实现：nodes 表只有 name/token_hash/panel_url/created_at/last_seen/last_status，无 `Status / Version / OpenvpnPort / Sk5Enabled` 字段；在线＝最近 poll 30 秒内一节属实（`index.html:802`） |

## §2 面板 UI

| # | FLMX 原做法（文件:行） | 结论 | OpenVPN 映射 |
|---|---|---|---|
| 2-1 | 路由结构（`vite-frontend/src/App.tsx:186-272`）：`/` 登录 → `/change-password` → `/dashboard` 概览 → `/monitor` → `/my-subscription` → `/forward` → `/tunnel` → `/node` → `/user` → `/group` → `/profile`；全部包在 `ProtectedRoute` 里 | 不抄 | OpenVPN 面板是单页应用，只有 `/`＋`/api/*`；无 dashboard/nodes/servers/sk5/users/profile/change-password 页面路由；改密是顶栏按钮调 `POST /api/change-password` |
| 2-2 | 布局：`layouts/admin.tsx`（管理员）+ `default.tsx` + `h5.tsx`；侧栏可折叠（`localStorage sidebar_collapsed`）、移动端抽屉菜单、顶栏含品牌 logo + 改密弹窗 + 版本页脚。`layouts/admin.tsx:1-80,438-451` | 未抄（待定） | 未实现：单页应用，无三布局；`sidebar_collapsed` 全树零命中，侧栏无折叠（仅移动端开合，无持久化）；改密入口放顶栏按钮一节属实（`index.html:283`） |
| 2-3 | 菜单分组：`MenuItem{path,label,icon,adminOnly?,userOnly?,adminLabel?,section?}`，管理员按“线路/分发/系统”分组。`layouts/admin.tsx:24-80` | 不抄（待核） | **注意**：用户 2026-11-04 已裁定“侧栏分组小标题删除”，但代码里 `section` 字段仍在——以用户裁定为准，OpenVPN 面板**不做分组小标题**，只保留 `adminOnly/userOnly` 显隐 |
| 2-4 | 节点页结构：`pages/node/`（`install-command.ts` 一键复制安装命令、`kernels-tab.tsx` 内核页签、`monitor-view.tsx`、`node-live-stats.tsx`、`agent-modals.tsx`、`use-node-realtime.ts` 实时状态）。 | 部分抄 | 节点表（在线／出口 IP／SK5／操作）＋“复制安装命令”按钮＋服务页签（OpenVPN/sing-box）＋实时状态（poll 时间/在线用户）属实；**版本列不存在**（节点表无版本字段，前端零版本命中） |
| 2-5 | 入站页结构：`pages/inbound/`（`inbound-form-modal.tsx` 新建/编辑弹窗、`kernel-panel.tsx`、`relay-modal.tsx` 链式出站、`split-rules.tsx` 分流、`presets.ts` 预设、`share.tsx` 分享）。 | 未抄（待定） | 未实现：无 modal、无 `presets.ts`；服务表单与 SK5 表单是单页内联 section＋proto 下拉，无预设机制 |
| 2-6 | 工具栏形态：`components/page-kit.tsx:230` 粘性工具栏 `sticky top-0 rounded-xl border bg-background/95 shadow-sm backdrop-blur`；卡片 `rounded-xl border shadow-sm`（`:107,:336`）。 | 部分抄 | 形似非逐字：Tailwind class 全树零命中；顶栏**不** sticky（仅侧栏 sticky，`index.html:66`）；玻璃卡片样式以 vanilla CSS 实现；新建按钮放工具栏右侧属实 |
| 2-7 | 玻璃效果（定稿）：浅色 `--glass-bg: rgba(255,255,255,0.6)` / `--glass-card: 0.7` / `--glass-border: 0.8`；深色 `rgba(30,30,30,0.6)`。`styles/globals.css:217-226`；侧栏 `bg-white/70 dark:bg-zinc-900/70 backdrop-blur-3xl shadow-[0_10px_30px_rgba(0,0,0,0.1)]`（`layouts/admin.tsx:450-451`）；弹窗 `bg-white/60 backdrop-blur-xl shadow-[0_12px_36px_rgba(0,0,0,0.18)]`（`:522`） | 照抄 | 玻璃值逐字照抄（透明度适中，0.6–0.7）；深色模式用户已明确“不需要”，**不抄深色变量**，只做浅色 |
| 2-8 | 阴影保留：`shadow-sm`（卡片/工具栏）、`shadow-[0_10px_30px…]`（侧栏）、`shadow-[0_12px_36px…]`（弹窗）三档。`page-kit.tsx / admin.tsx` | 照抄 | 三档阴影照抄；用户 2026-11-03 已明确禁的只是玻璃透明，阴影不在禁列 |
| 2-9 | 文字对比度：目标 7、底线 4.5（用户 2026-11-01 立规，MEMORY）；**CSS 文件里未找到 `7:1`/`4.5` 字样**，属流程口径非代码常量 | 照抄（流程） | OpenVPN 面板交付前做渲染级对比度自检（托盘兜底 + 小字加粗），目标 7 / 底线 4.5；**预览/演示先行**：先部署演示站，用户看过才发版（用户 2026-11-01 立规） |
| 2-10 | 字段级指引：配置指引必须写到控制台路径、字段名、可填值、防错警告、自检法，不许只给概要（用户 2026-11-01 立规，起因是订阅前置指引险些误选字段） | 部分抄 | SK5 表单每字段就地写明：地址格式、端口范围、密码不回显、保存后点“测试”看 TCP/UDP 分项结果属实；**用户名 `session-` 前缀提示缺失**（`sk5User` 字段无占位／提示，`index.html:474`） |

## §3 安全

| # | FLMX 原做法（文件:行） | 结论 | OpenVPN 映射 |
|---|---|---|---|
| 3-1 | 首登改密：`Claims.PwdChangeRequired`（默认口令登录的管理员），受限 token 仅放行 `/api/v1/user/updatePassword`，改密后旧 token 因 `PasswordChangedAt` 失效须重登。`go-backend/internal/auth/jwt.go:18-35,52-70`；`handler.go:469-472,568` | 未抄（待定） | 未实现：首登强制改密未实现（P1-7，按设计）；根 README:260 明文“改密（不强制）…不设改密前置条件”，登录即给完整 admin 会话 |
| 3-2 | 管理员播种：代码中**未定位到明文默认管理员账号播种**（grep `SeedAdmin / 默认 admin` 无命中）；`repository.go:578` 的 `PasswordChangedAt: 1748914865000` 为既有行常量，非播种口令 | 不抄（待核） | OpenVPN 面板不设默认口令：安装时生成随机管理员密码打印一次并写 `admin.pass`（600），面板路已有此做法，继续用 |
| 3-3 | 会话/token：自研 HMAC-SHA256 JWT（`auth/jwt.go`），`expireTime = 7 天`，`Claims{Sub,Iat,IatMs,Exp,User,Name,RoleID}`；`ParseClaims` 显式校验 header `alg`（F-067，拒 `alg=none/RS256`）；改密/吊销会话时把 `password_changed_at` 推到 now 毫秒，`IatMs <= PasswordChangedAt` 的旧 token 全失效。`auth/jwt.go:76-125`；`repository_auth.go:32-43` | 未抄（待定） | 未实现：JWT 全树零命中；会话是 12 小时 cookie（`panel/app.py:191`），无 alg 校验、无 WebCrypto；改密即全部旧会话失效一节另见根 README:260（`session_version` +1 机制） |
| 3-4 | 密码存储：`bcrypt.GenerateFromPassword`（`security/password.go:10`）；登录时用户不存在也跑一次 dummy bcrypt（合法 cost 10 占位哈希），消除 2–5ms vs 80–150ms 时序差、防用户名枚举。`handler.go:449-455,551-552,905` | 部分抄 | 管理员密码 bcrypt 存储属实（含 SHA-256 回落）；dummy bcrypt 未实现（全树零命中）；VPN 用户证书不设密码，靠证书鉴权 |
| 3-5 | 登录限流（双维度）：IP 维命中直接 429 + `Retry-After: 60`；用户名维永不硬拒，只触发渐进延迟（1s→2s→4s，上限 5s）+ 收紧该 IP 阈值，**绝不返回“账号已锁定”、无 429**（防枚举、防锁定 DoS）。`login_rate_limit.go:352-430` | 部分抄 | OpenVPN 面板登录限流仅 IP 维（5 分钟 5 次失败锁 15 分钟，429 + `Retry-After`），无用户名维渐进延迟；agent poll 失败也按 IP 限流，不锁节点 |
| 3-6 | 节点认领守卫（用户口径，MEMORY）：旧 agent 的 `config.json` 地址须与面板地址**逐字相等**才认领，不符停手（交互终端可人工确认留逃生口）；安装入口前置守卫。**代码中未定位到逐字比对函数**——FLMX 安装器是“每次安装总是新建 config.json”，`nodeInstall` 只生成新命令 | 照抄（流程） | OpenVPN agent 安装前置守卫照抄流程：`/etc/ovpn-agent/config.json` 已存在且 `panel_url` 与本次不同 → 拒绝并提示“先卸载旧 agent 或加 `--force` 人工确认”；**不抄** install.sh 的“总是新建覆盖”——那会丢旧面板归属 |
| 3-7 | 普通用户权限收窄（用户 2026-11-01 令，随 1.7.11 出）：普通用户只看自己隧道的监控；服务监控与节点监控对普通用户整体关闭；`MonitorPermission` 表是例外授权（管理员逐人开）。`model.go:368-376 MonitorPermission`；`monitoring.go:933,967 HasMonitorPermission`；`middleware/auth.go:172,208-212`（`/user-inbound/mine`、`/user-subscription/mine` 保持开放） | 未抄（待定） | 未实现：无普通用户登录（单管理员面板）；`MonitorPermission` 全树零命中 |
| 3-8 | 角色区分：`RoleID` 进 JWT claims；写操作（限速规则等）普通用户直接 `-1` 拒绝。`mutations.go:3237,3249,3437,3457` | 未抄（待定） | 未实现：无 RoleID、无 JWT claims；写接口只校验 `@login_required`（管理员会话） |
| 3-9 | SK5/订阅凭据存放：SS2022 订阅密码经确定性派生得 uPSK（`kernel/credentials.go:213-216`）；订阅凭据 `subscriptionCredentials` 每次发新 UUID + 密码（`repository_subscription.go:39`）；链式 socks 凭据从解析出的代理 URL 取 `username/password`（`kernel/chain.go:388`）；Gist 备份口令只存 `sha256`（`gist_backup.go:311`） | 部分抄 | 加密宣称假：根 README:253 明文“Flask 侧 `sk5.json` 存明文密码…FLMX 的‘凭据只存密文’口径本产品不抄”；原子替换属实（`egress/sk5_manager.py:127 _atomic_write_json` 走 `os.replace`）、永不进日志属实；agent 侧 `sk5.json` 600 权限 |
| 3-10 | 面板源下载信任模型：面板内升级下载走 `config.json` 的 `proxy` 字段（国内节点直连 GitHub 不通时用代理）；校验锚与被校验文件同源同版本。`mutations.go:1086-1092` | 未抄（待定） | 未实现：本树 `config.json` 无 `proxy` 字段（agent／panel／Worker 全树无命中），下载均为直连；校验锚（`.sha256`）与文件同 Release 同版本一节已实现（见 §1-13）。 |

## 附：三条最值得抄的

1. **一键安装命令 = secret + 地址归一 + sha256 fail-closed**（§1-10～1-15）：FLMX 最值钱的不是脚本本身，是“面板生成命令时就把地址、校验全部钉死，agent 侧只按命令执行”。FLMX 的“版本解析”一步 OpenVPN 不抄（版本不按 channel 解析，钉在 bundle 的 sha256 上）。OpenVPN 的安装命令已是此形（注册/轮换返回完整命令，Worker `/install` 返回模板；`.sha256` 必须取到且校验通过才执行，缺失或验不过即停）；Flask 侧 `/install-agent.sh.sha256` 端点已补（见 §1-13），安装命令全程硬校验。
2. **配置下发可观测 + 端口默认只读**（§1-24、1-30）：FLMX 的双哈希本产品不抄——无哈希字段、无三态显示；配置经命令队列下发，面板只显示瞬时提示，agent 回执 done/failed 可查。端口默认建后只读，改端口须显式 `allow_port_change=true`。这两条直接防住 OpenVPN 最容易出的两类事故：配置漂移和已发 .ovpn 失效。
3. **随机初始密码 + 改密即全部旧会话失效 + 登录限流仅 IP 维**（§3-1、3-3、3-5）：FLMX 的“首次登录只能改密”做法本产品不抄——登录即给完整 admin 会话，不设改密前置条件；改密后 `session_version` +1，全部旧会话立即失效（照抄）；登录限流只看来源 IP（5 分钟 5 次失败锁 15 分钟），不按用户维度限流。初始密码随机生成、不设默认值。

## 未定位 / 待核（不许当事实抄）

- 管理员默认账号播种：代码无命中（§3-2）。
- 节点认领“地址逐字相等”守卫：用户口径有，代码未定位到比对函数（§3-6）；install.sh 反而是每次新建 config.json。
- 侧栏分组小标题：用户已裁定删除，但 `layouts/admin.tsx` 的 `MenuItem.section` 字段仍在（§2-3），以用户裁定为准。
- 对比度 7/4.5：用户立规，CSS 中无常量（§2-9），属交付流程。

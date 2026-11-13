# live-verify-R18 补记：headline-9 毒树默认重跑 ＋ 显式 POST /api/cmd 往返

- 补记目的：live-18 本轮两格未执行（执行该步的工具调用被安全分类器移除，lane 按指令停止、不绕过）。本补记只补这两格，不动 live-18 已定结论。
- 机：Lightsail Debian 12，公网 16.146.199.68，tailnet 100.110.88.49；通道一律 `~/workspace/tools/tssh.sh`。
- 时间：2026-11-13（UTC 时间以机上时钟为准，报告内时间均为 UTC 除非注明）。
- 顺序：先跑 cell 1（毒树重跑），再跑 cell 2（POST /api/cmd）——cell 2 的 cmd_enqueue＋agent_report 审计行会污染 cell 1 的行级比对，故两格严格串行。

## §0 接手时地面真值（live-18 终态复核）

- 五服务 active：openvpn-server@server PID 63842（TCP 443）、panel、sing-box、danted、ovpn-agent PID 75940。
- SK5 禁用，表 100 空，rule 100 无；节点 lightsail 在线；用户 alice／bob 有效；CA serial `2B9F892B…`。

## §1 cell 1 — headline-9 毒树默认重跑（R8-BUG-1 真机复验）

### 1.1 新鲜重跑前快照（h9-before-fresh.json，01:20 UTC 取）

- admin：`$2b$12$W6Wj3JxT…`（线上活哈希，非毒哈希）；login_attempts 0 行；nodes 1 个（lightsail，token_hash `70265d7d…`，panel_url `https://172.26.15.152:8443`，created 01:17:22）。
- audit：119 行，sha256 `1dfbe9ac…`；末行 119 为 login（01:18:48）。105→119 的增长全部是 live-18 自身行为（node_register／node_rotate／cmd_enqueue／agent_report＋登录行），无后台自增——agent 轮询本身不写审计行，只有命令回执才写。
- server PID 63842；CA serial `serial=2B9F892B9D55C8FD32B26176C03B09830D5572BF`；index.txt sha256 `8ae6858d…`；issued 4 张（alice／bob／server／verify-1794532169）。
- sk5.json：dante 127.0.0.1:11080，enabled false，sha256 `3a35d14e…`。
- 线上队列在位，1 条命令 `db365022058c4aba96f796d08fd05cfe`（live-18 的 get_status 往返遗留）；毒命令 id 均不在其中。

### 1.2 毒物核对（重跑前）

- `/root/r18/panel.db`：sha256 `bc9ed19f…`；admin 行 `id=1, $2b$12$tceqeKocEP0Z6KowAfCcruecdIxjb0q3cT.X4aMFFWJMyQ5zm7y22, session_version=1`；audit_log 0 行——与 R8 §6.2 毒形一致。
- `/root/r18/agent_queue.json`：sha256 `9ed78463…`；3 条 init_pki force+confirm（1 sent＋2 queued），id `8bb719af…`（sent）、`8cca7b62…`（queued）、`7ce3cf35…`（queued）。

### 1.3 毒树构建（01:21 UTC）

- `cp -a /root/r18/repo /root/r18/poison-tree`，`mkdir -p poison-tree/panel/data`，拷入 `/root/r18/panel.db`＋`/root/r18/agent_queue.json`。
- 毒树 panel/data/ 仅此二文件，sha256 与 staged 原件逐字节一致：panel.db `bc9ed19f…`、agent_queue.json `9ed78463…`。

### 1.4 默认重跑（01:21–01:23 UTC）

- 命令（用户口径）：`cd /root/r18/poison-tree && bash install.sh`（nohup 后台＋日志 `/root/r18/install-poison.log`，防 tssh 断管；安装器 PID 77260）。
- 结果：**通过**。0 ERROR；AN 新行在位（ufw 已装则跳过 iptables-persistent，两处日志均在）；sing-box／tun2socks 均已装跳过下载；完成横幅已印。

### 1.5 行级比对（跑后快照 h9-after.json，01:23 UTC 取）

- 比对脚本 `/root/r18/h9-compare.py`（新鲜快照 vs 跑后快照 vs 毒队列文件）：13 项中 12 项直接通过，1 项为比对脚本自身的过严判据（见下）。
- **通过项**：admin 行逐字节一致（仍为 `$2b$12$W6Wj3JxT…`）；login_attempts 一致（0 行）；nodes 稳定字段一致（lightsail token_hash 不变）；server PID 不变（63842，服务未重起）；CA serial 不变（`2B9F892B…`）；index.txt sha256 不变；issued 证书 4 张不变（alice／bob／server／verify-1794532169）；sk5.json 逐字节一致；audit 119→120，仅增 1 行（行 120，01:22:06，admin login，ip=127.0.0.1——安装器自身的健康门登录）；毒命令 id（`8bb719af…`／`8cca7b62…`／`7ce3cf35…`）均不在 live 队列中（live 队列仍只有旧命令 `db365022…`）；毒队列文件本身 3 条 init_pki force+confirm、1 sent＋2 queued 复核无误。
- **panel.db 文件 sha 变了——不是 bug，是比对脚本的判据过严**：+1 条审计行必然改动文件字节。我当场独立复算：live 库前 119 行 audit 的 sha256 = `1dfbe9ac…`，与重跑前快照的 audit_sha256 逐位一致；行 120 仅为安装器健康门登录。行级结论：**前 119 行完全一致，新增仅 1 行**——与 live-18 §11.1 干净树重跑的同一口径一致。
- **毒 init_pki 从未执行**（三证）：① CA／index.txt／issued 证书全部不变——无 CA 重建、无新服务端证书、无用户证书作废；② 部署目录 `/opt/openvpn-sk5-panel/panel/data/` 仍只有 live 的 panel.db（sha `c6e7aea5…`，非毒 `bc9ed19f…`）与 live agent_queue.json（1823 B，非毒 1104 B）——毒树 panel/data/ 未被拷入；③ install-poison.log 中 init_pki／force 零命中；agent 日志 01:21–01:26 窗口内 init_pki／execute／cmd 零命中。
- 跑后五服务仍 active；server PID 63842、agent PID 75940 均未变。
- **结论：headline-9 通过。R8-BUG-1（毒树重跑销毁线上 panel.db）在本轮毒树复验下未复发；live-18 遗留待办①关闭。**

## §2 cell 2 — 显式 POST /api/cmd 往返

- 方法：机上脚本 `/root/r18/cmd-roundtrip.py`（密码读自机上 `/etc/openvpn-sk5-panel/admin.pass`，不打印、不落盘）：登录 → POST /api/cmd 入队 get_status（节点 lightsail）→ 每 2 秒轮询 GET /api/cmd/:id 直至 done/failed。
- 结果：**通过**。
  - 登录：POST /api/login HTTP 200（`{"ok":true}`，Flask session cookie）。
  - 入队：POST /api/cmd HTTP 202，`cmd_id=202b6da9846d405890189ef0d436997d`，`{"action":"get_status","node":"lightsail","status":"queued"}`。
  - 回执：首轮轮询（2 秒）即 `status=done`，`error=None`，`finished_at=2026-11-13T01:24:27+00:00`。
  - 回执内容（GET /api/cmd/:id 复核，HTTP 200）：openvpn.running=true、pid=63842；sk5.enabled=false、policy_routing_active=false；users alice／bob valid（另 verify-1794532169 valid、verify-1794532249 revoked）；egress_ip=`2600:1f13:…`（SK5 禁用下的直连 IPv6，诚实）。
  - agent 侧双证：journal 01:24:27.198 `cmd 202b6da9… action=get_status`，01:24:27.300 `done ok=True`（执行约 0.1 秒，agent PID 75940）。
- 审计足迹：本次登录＋cmd_enqueue 各写 1 行审计行（cell 1 比对之后发生，不污染 cell 1 结论）。

## §3 结论与机器终态

- **结论：两格全部通过，零新 bug。** cell 1 headline-9 毒树默认重跑通过（R8-BUG-1 未复发）；cell 2 显式 POST /api/cmd 往返通过（202 入队、2 秒内 done、agent 侧执行双证）。live-18 的六项 headline 至此全部闭合：S0–S4 全过，headline-1／3／5／6／7 通过，headline-9 本补记通过。
- 机器终态（01:25 UTC）：openvpn-server@server PID 63842（TCP 443）、panel、sing-box、danted、ovpn-agent PID 75940 均 active；SK5 禁用，表 100 空，rule 100 无；节点 lightsail 在线；用户 alice／bob 有效；CA `2B9F892B…` 与安装时一致；证据在机上 `/root/r18/`（h9-before-fresh.json／h9-after.json／install-poison.log／cmd-roundtrip.py／cmd-fetch.py／h9-snapshot.py／h9-compare.py）。
- 遗留待办（与 live-18 §12 相同，未变）：① O-R18-1 的探针 fallback 建议由审计轮定夺；② Cloudflare 真实部署（P0-1）与 SK5 端口 1001 vs 9000 仍待用户决断。

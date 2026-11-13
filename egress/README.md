# SK5 出口链路（egress/）

OpenVPN 用户流量 `10.8.0.0/24` 一键切到购买的 SOCKS5 作出口。
本目录只管出口链路：OpenVPN 本体在 `../core/`，面板在 `../panel/`。

## 链路图

```
客户端 --OpenVPN--> tun0 10.8.0.0/24 (OpenVPN server)
                        |
                        | ip rule: from 10.8.0.0/24 lookup 100 (prio 100)
                        v
                   table 100: default via 10.9.0.1 dev tun1
                        |
                        v
                   tun1 10.9.0.1/30 (sing-box tun inbound, tag tun-in)
                        |
                        | sing-box outbounds
                        v
              bought-sk5: SOCKS5 host:port (user/pass, version 5)
                        |
                        v
                    互联网 (出口 IP = 购买的 SK5 IP)

DNS: 1.1.1.1, detour direct -- DNS 查询不走 SK5，避免 SK5 侧
DNS 污染 / 泄露判断失真；sing-box 的 dns.rules 也把 53 端口
流量钉到 direct。
```

关键点：规则只按**源地址**匹配。sing-box 自己连 SK5 时源地址是
本机 IP，不进 table 100，走主表直连商家 —— 所以 sing-box 的
SK5 连接永远不会被 loop 回 tun1（见 `policy-routing.sh` 头部注释）。

## 文件

| 文件 | 作用 |
|---|---|
| `sk5_manager.py` | 控制面：存 SK5（0600）、渲染 sing-box 配置、`sing-box check`、启停 sing-box、调 `policy-routing.sh`、真实拨测、健康检查 |
| `sing-box.json.template` | sing-box 配置模板（tun 入站 + socks 出站 + direct + DNS 直连） |
| `policy-routing.sh` | 策略路由：rule + table 100、ip_forward、iptables；tun1 由 sing-box 自建、本脚本永不建设备（R24-P2-1）；disable 撤 rule + 清 table 100 + 删相关 iptables 规则 |
| `test-egress.sh` | 按源地址验出口：`ip route get ... from 10.8.0.1` + 直连对照 + 经 SK5 的出口 IP（须用本机 tun 地址作源；10.8.0.2 是客户端地址、非本机源，内核拒绝查询） |

## 安装（Debian 12 / Ubuntu 22.04 / 24.04，sing-box 1.11+）

```bash
# 1. sing-box 1.11+（官方 release 二进制，二选一）
#    a) 下载：https://github.com/SagerNet/sing-box/releases
#       （取 linux-amd64 tar.gz，解压出 sing-box 到 /usr/local/bin/sing-box）
#    b) 或用发行版仓库的包，但要确认版本 >= 1.11
sing-box version   # 必须 >= 1.11

# 2. 工具
apt update && apt install -y curl iproute2 iptables python3

# 3. systemd（可选但推荐；没有它 manager 会用 nohup 后台跑 sing-box）
cat > /etc/systemd/system/openvpn-sk5-singbox.service <<'EOF'
[Unit]
Description=sing-box SK5 egress for OpenVPN users
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/sing-box run -c /etc/openvpn-sk5-panel/sing-box.json
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
```

## 使用（面板调 `sk5_manager.py`；手动命令同理）

```python
from egress.sk5_manager import set_sk5, test_sk5, get_status, enable, disable

set_sk5("proxy.iproyal.net", 1001, "session-xxx", "PASSWORD")  # 保存+立即启用
# 部分合并语义：传 None（或空密码）的字段保留已存值，只改传来的字段。
# 密码框留空永远不会清空已存密码；要切无认证商家传 clear_password=True。
set_sk5(fail_open=True)  # 只改一个开关，不用重传 host/port/密码
test_sk5()   # {'tcp_ok': True, 'udp_ok': True, 'egress_ip': '...', ...}
get_status() # enabled / singbox_running / policy_routing_active / egress_ip
disable()    # 显式关闭：恢复直连出口（操作员意图）
```

```bash
python3 egress/sk5_manager.py status
python3 egress/sk5_manager.py test     # TCP/UDP 分开报
python3 egress/sk5_manager.py health   # 定时器每 60 秒跑一次（见下）
./egress/policy-routing.sh status
./egress/test-egress.sh                # 验 table/网关/出口 IP 三件套
```

## TCP / UDP 两种模式对照

| | UDP 模式（默认） | TCP 模式（商家只给 TCP 时） |
|---|---|---|
| OpenVPN | `proto udp`，端口 1194 | **必须切 `proto tcp`，端口 443** |
| SK5 出站 | `udp_over_tcp: false`，原生 UDP ASSOCIATE | `udp_over_tcp: true`，sing-box 把 UDP 包进 TCP |
| UDP 怎么通 | 商家 UDP relay 收 DNS/游戏 UDP，原样回包 | 商家只收 TCP，UDP 由 sing-box 在 TCP 里隧道化 |
| 性能 | 正常 | **TCP 套 TCP：重传放大、延迟抖动、丢包时卡顿明显**；能用，但不要指望和 UDP 模式一样稳 |
| 怎么验 | `test_sk5()` 的 `udp_ok` 是真 UDP ASSOCIATE + DNS 回包 | `test_sk5()` 会起一个临时 sing-box 走 UoT 再测 UDP，`udp_mode` 会标 `udp_over_tcp` |

**硬要求兑现方式**：`test_sk5()` 的 `tcp_ok` 与 `udp_ok` 是两次
独立拨测。TCP 用 `curl --socks5-hostname` 取 `ifconfig.me`；
UDP 用纯 Python SOCKS5 UDP ASSOCIATE + 向 `1.1.1.1:53` 发 DNS
查询、核对 transaction ID 与应答。TCP 通永远不会把 `udp_ok`
置 true —— 如果商家关了 UDP，面板必须如实显示 `udp_ok: false`。

切换模式：面板调 `set_udp_over_tcp(True/False)`（重渲染 + 重启
sing-box 生效），同时 OpenVPN 侧要同步切协议/端口，两边必须
一起改，只改一边会断。

## 故障策略：断网保护 vs 失败回直连

默认 **断网保护（kill-switch，`fail_open: false`）**：

- 链路启用时，`from 10.8.0.0/24 lookup 100` 一直在。sing-box
  或 SK5 一死，table 100 的 `via 10.9.0.1 dev tun1` 就死了，
  VPN 用户流量无路可走、直接丢包 —— **绝不会悄悄改走直连
  暴露真实出口 IP**。
- 恢复：SK5 恢复后 sing-box 重连即恢复，不用动面板。

**失败回直连（`fail_open: true`，开关可改）**：

- systemd timer `openvpn-sk5-healthcheck.timer` 每 60 秒跑一次
  `python3 sk5_manager.py health`（`install.sh` 安装并启用）。
  链路已死时 `check_health()` 执行 `disable()`，即撤掉 table 100，
  VPN 用户改走主表直连中转机出口。不断网，但出口 IP 会变回
  中转机 IP。每次检查结果写进 `/etc/openvpn-sk5-panel/health.json`
  （0600），`get_status()` / agent `get_status` 回执里的
  `last_health` 就是它，面板看状态不用每次重新拨测。
- **fail-over 是单向的**：触发后 `enabled` 保持 `False` 持久化，
  SK5 恢复后也不会自动重建链路，须在面板上人工重新启用 SK5 才恢复。
- 适用：出口 IP 暴露可以接受、但业务不能断的场景。
- 注意：`fail_open` 只对**非计划故障**生效。操作员在面板上
  点「关闭 SK5」是显式意图，`disable()` 本来就是恢复直连，
  与开关无关。

## 策略路由的并发与幂等（R6-BUG-1，live-R6）

新装后首次面板启用曾报 500：`policy-routing.sh enable failed:
RTNETLINK answers: File exists`，原样重发即 200，全轮仅一次。
沙箱复现证实两个独立触发机制（任一即可打出同一签名）：

1. **并发启用竞态**：旧代码是先查后加（`rule_exists` 通过后
   再 `ip rule add`），两次 `do_enable` 同时跑都会通过守卫，
   第二条 add 撞 EEXIST。复现：内核忠实语义桩（`ip rule add`
   只对完全相同的规则报 EEXIST，不同 selector 可共用同一
   priority）下两路并发启用，旧脚本一次 rc=1（EEXIST）一次
   rc=0；修后两路全 0、规则唯一。
2. **守卫谎报（SIGPIPE＋pipefail）**：`ip rule show | grep -q`
   里 grep -q 找到即退出关管，写者慢一点就死于 SIGPIPE（141）；
   脚本开了 `set -o pipefail`，141 会让守卫谎报“规则不在”，
   随后 add 撞上已在位的规则报 EEXIST。修法：全部四处
   `grep -q` 改成 `grep … >/dev/null`（读完整个流，写者永不
   SIGPIPE）；`rule_exists` 只认 priority 100 的我们这条规则，
   同 selector 不同 priority 的是重复副本、不是“在位”。

修法（只在 `policy-routing.sh` 内）：

- **锁**：`flock` 锁 `/run/openvpn-sk5-panel/policy-routing.lock`，
  串行化 enable/disable/restore（等锁上限 20 秒，面板子进程
  超时 30 秒，留有余量；`status` 只读不加锁；锁在分发处只取
  一次，不在 `do_*` 内取——`do_restore` 内部调 `do_enable`，
  嵌套取锁会死锁）。
- **幂等 add**（`add_rule`）：add 失败后重查，规则已在位即
  视为成功；确实不在位才 die，报错即 `ip rule add` 的真实
  错误，并写明“本次未改任何策略状态，重试启用是安全的”。
  注意（R8-P2-1，live-7 §11）：外来规则与我方规则共用
  priority 100 **不是冲突**——内核允许多个不同 selector
  共用同一 priority，`ip rule add` 只对完全相同的规则报
  EEXIST；外来规则在位时启用直接 200、两条规则共存、流量
  正常。AC 曾写过一个“占用者报错”分支（`priority 100 is
  already used by '…'`），那是按 priority 独占桩模型写的死
  代码，还会把 EPERM 之类的真实失败误诊为“被占用”，已随
  R8-P2-1 删除。
- **去重**（`dedup_rule`）：同 selector＋同 table 在别的 priority
  的规则是冗余副本，enable/disable 时清掉、只留 priority 100
  这一条——否则 disable 后残留副本会继续把 VPN 流量指进已
  flush 的 table 100（黑洞），而面板却显示直连。
- **回滚＋自检**：enable 失败时只删本次调用自己加的规则，
  绝不动先前已有的状态；收尾自检规则与 table 100 默认路由
  双双在位，否则回滚＋die，不留半配置内核态。

**关于 500 后的 daemon/盘分裂**：本修不从脚本侧回滚 sing-box
（脚本不拥有 daemon、也没有失败前 daemon 状态的记录；失败
时停掉 sing-box 会直接掐断隧道，比短暂分裂更糟），而是把
触发本身消掉（锁＋幂等 add），使该 500 不再发生；残留的失败
都是确定性的、报错里点名的（如 tun1 建不出来、路由写不进），
操作员按报错处理后重试即可。盘侧已有 Q 路“先成功后写盘”守住（失败时盘上
仍 `enabled: false`，面板永不谎报成功），重试是整条 enable
的幂等重跑（渲染覆盖、重起幂等、策略应用现已幂等）。

验证（沙箱，内核忠实语义桩＋`unshare -m`；AG 路重跑）：
并发启用 ×2 全 0、×5 全 0，规则唯一（`"(added
concurrently)"` 分支 0 次触发——锁在工作）；形态矩阵——
空态／规则在位／同 selector 不同 priority（去重后唯一）／
外来规则共用 priority 100（启用 200、两条规则共存）全过；
enable/disable 连续交替 20 次 0 失败；并发 disable ×2 全 0；
并发 enable＋disable 终态自洽（规则与路由同有同无）。变异
红证：删掉失败后重查＋锁（旧式先查后加）后并发 ×2 复现
EEXIST（一次 rc=1、一次 rc=0，报错即真实的 `RTNETLINK
answers: File exists`）；删 dedup 后 M3 终态两条规则共存。
`do_status` 的 VPN 源段在内核忠实源校验下输出
`1.1.1.1 from 10.8.0.1 dev tun1 table 100`（旧源 10.8.0.2
作阴性对照恒报错）。门禁：test-egress.sh §6 矩阵 4/4
（回环 5/0/2、商户同 IP 5/1/1、商户异 IP 6/0/1、pre-X 阴性
对照 5/1/1）、verify-integration 29/29。真机：live-7
headline-1 通过（首启一次 200、10 次交替全一次 200、并发
双启用均 200 规则唯一）、headline-2 部分通过（dedup 通过；
M4 占用错误预期被真机证伪，见 R8-P2-1）。

## 校验方法

```bash
bash -n egress/policy-routing.sh && bash -n egress/test-egress.sh && echo SH_OK
python3 -m py_compile egress/sk5_manager.py && echo PY_OK
# 沙箱注意：本沙箱对 UDP sendto 一律 EPERM（连 loopback 都发不出），
# 所以 UDP 拨测的 live 部分在沙箱里只能 SKIP（测试自带环境自检），
# 不能当成产品失败。UDP 数据面验证必须上测试机 / 真机跑。
# 同理沙箱也建不了 TUN 设备（TUNSETIFF EPERM），policy-routing.sh
# enable 的真机验证也必须上测试机；沙箱里 enable 会明确报错退出，
# 不会留一半状态。
# 模板渲染后校验（替身值）：
grep -v '^[[:space:]]*#' egress/sing-box.json.template \
  | sed -e 's/__SK5_HOST__/proxy.example.net/' -e 's/__SK5_PORT__/1080/' \
        -e 's/__SK5_USER__/u1/' -e 's/__SK5_PASS__/p1/' > /tmp/sing-box-test.json
sing-box check -c /tmp/sing-box-test.json   # 退出 0、无输出即通过
./egress/test-egress.sh                     # 真机上跑：PASS 为 0 FAIL
```

## 排障

- `test_sk5()` 返回 `tcp_ok: false`：先 `curl -v --socks5-hostname`
  手动测一次；常见原因是 SK5 地址/端口/账号错，或商家侧
  IP 白名单没放行中转机 IP。
- `tcp_ok: true, udp_ok: false`：商家 UDP 没开。先确认商家口径；
  确认只给 TCP 后切 TCP 模式（OpenVPN 切 TCP 443 +
  `set_udp_over_tcp(True)`），再测一次。
- `sing-box check` 报错：看它点的字段名，十有八九是模板占位符
  没替换完（`__SK5_*__` 残留）或 `server_port` 被当成字符串。
- VPN 连上但打不开网页：`./test-egress.sh` 看第 3 项
  `route get ... from 10.8.0.1` 是否走了 table 100（须用本机 tun 地址作源）；再看
  `journalctl -u openvpn-sk5-singbox` / `/etc/openvpn-sk5-panel/sing-box.log`。
- MTU：tun1 与 OpenVPN 都按 1400 配，分片黑洞先查 MTU 再查别的。

## 安全

- SK5 密码只存在 `/etc/openvpn-sk5-panel/sk5.json`（0600），
  `get_status()` / 日志 / 报错里永远不出现密码明文。
- 面板接口调 `set_sk5()` 时不要把密码打进 access log；`test_sk5()`
  的返回值里也没有密码字段。

# tests/ — 审计探针与变异构建器（R17 落地，R16 建议）

本目录只含审计探针与变异构建器，**产品代码不动**。探针一律在 `/tmp` 副本上跑，
绝不直接跑项目树（Flask 探针会写 `panel/data/`、core 探针会写 server.conf）。

## 文件

| 文件 | 用途 | 规模 |
|---|---|---|
| `build-mutants.py` | 门禁 §7 变异构建器：从干净树复制出 7 棵变异树（字典互换×2、缺项、多项、常量互换、install 侧互换、改一位），每处改动点断言唯一命中 | 7 棵 |
| `r17_flask.py` | Flask 面板探针（test_client，nobody 身份）：登录/限流、输入校验、节点/命令生命周期、坏队列、下载与吊销、compat 解析 | 89 格 |
| `r17_core.py` | core 探针（纯 stdlib）：render 守卫、DNS/用户名校验、list_users、build_client_config | 46 格 |
| `r17_agent.py` | agent 探针（纯 stdlib）：`_as_int`/`_as_bool`、`_pinned_sha256`、`execute_command` 白名单、`load_config` | 33 格 |
| `r17_worker.mjs` | Worker 探针（mock KV）：登录/限流、节点、命令、改密 501、poll 下发守卫、sent 超时、bundle 503 | 35 格 |

R17 四套探针合计 203 格：202 绿＋1 红（W5-01，即 R17-P1-1 的 Worker 面；
F4-02b/F4-13/F4-15/F4-16/W5-05/W5-06b 是“观测到违规行为”的钉死格，故显示 PASS）。

## 运行前准备（一次性）

```bash
# 1. 干净树副本（探针树）与门禁树
rm -rf /tmp/r17/tree /tmp/r17/ptree
cp -a ~/workspace/openvpn-sk5-panel /tmp/r17/tree
cp -a ~/workspace/openvpn-sk5-panel /tmp/r17/ptree
rm -rf /tmp/r17/tree/panel/data /tmp/r17/ptree/panel/data
mkdir -p /tmp/r17/tree/panel/data /tmp/r17/ptree/panel/data

# 2. venv（系统 python3 无 flask）
python3 -m venv /tmp/r17/venv && /tmp/r17/venv/bin/pip install -q flask bcrypt

# 3. 夹具 PKI（真机行形：index.txt TAB 行；证书为 dummy PEM，仅供解析器/下载路径用）
mkdir -p /tmp/r17/fixture-ca/pki/issued /tmp/r17/fixture-ca/pki/private /tmp/r17/fixture-server
# index.txt：alice V（301113000000Z）、bob R、erin V 但过期（201113000000Z）、carol E、dave V
# 每行：<状态>\t<expiry>\t<serial>\tunknown\t<CN>（TAB 分隔）
# issued/<name>.crt 与 private/<name>.key 为 dummy PEM（BEGIN/END 行齐全即可）
# fixture-server/ta.key 为 dummy OpenVPN 静态密钥
# 4. 桩 sing-box（PATH 首位；check 过、run 立即退出 0，不建 TUN）
mkdir -p /tmp/r17/stubbin
printf '#!/bin/sh\nif [ "$1" = "run" ]; then exit 0; fi\nexit 0\n' > /tmp/r17/stubbin/sing-box
chmod +x /tmp/r17/stubbin/sing-box
```

## 运行

```bash
SITE=$(ls -d /tmp/r17/venv/lib/python*/site-packages)
# Flask（nobody 身份；数据目录与 PKI 目录须 nobody 可写）
rm -rf /tmp/r17/flask-data /tmp/r17/sk5cfg && mkdir -p /tmp/r17/flask-data /tmp/r17/sk5cfg
chown -R nobody:nogroup /tmp/r17/flask-data /tmp/r17/sk5cfg /tmp/r17/fixture-server
runuser -u nobody -- env PATH="/tmp/r17/stubbin:$PATH" PYTHONPATH="$SITE" \
  R17_TREE=/tmp/r17/ptree OVPN_PANEL_DATA_DIR=/tmp/r17/flask-data \
  OVPN_PANEL_SECRET_PATH=/tmp/r17/flask-data/secret.key \
  OPENVPN_CA_DIR=/tmp/r17/fixture-ca OPENVPN_SERVER_DIR=/tmp/r17/fixture-server \
  OVPN_SK5_CONFIG_DIR=/tmp/r17/sk5cfg python3 tests/r17_flask.py
# Core / Agent（nobody；core 需一个空 server 目录）
rm -rf /tmp/r17/fixture-server2 && mkdir -p /tmp/r17/fixture-server2
chown nobody:nogroup /tmp/r17/fixture-server2
runuser -u nobody -- env PYTHONPATH="$SITE" R17_TREE=/tmp/r17/ptree \
  OPENVPN_CA_DIR=/tmp/r17/fixture-ca OPENVPN_SERVER_DIR=/tmp/r17/fixture-server2 \
  python3 tests/r17_core.py
runuser -u nobody -- env PYTHONPATH="$SITE" R17_TREE=/tmp/r17/ptree python3 tests/r17_agent.py
# Worker（mock KV，直接跑）
node tests/r17_worker.mjs
# 门禁变异树（在 /tmp/r17/tree 上跑门禁，逐棵 28/1 仅 §7 红）
python3 tests/build-mutants.py   # 在 /tmp/r17/mutants/ 生成 7 棵树
```

## 环境自检与已知限制

- 沙箱 UDP sendto 一律 EPERM、TUN 创建 EPERM：UDP 数据面与 enable 真成功路径
  不在沙箱探针里断言（enable 成功路径由门禁 B1 格的 alive-once 桩覆盖；
  F2-07 enabled=1 在沙箱里断言的是诚实 500＋sing-box 报错，见探针内注释）。
- Flask 探针跑完须确认宿主 `/etc/openvpn-sk5-panel` 与 `/etc/openvpn` 未被写
  （探针以 nobody 跑且全部路径都经 env 钉到 /tmp；若出现即探针隔离失效）。
- 探针脚本里的 `R17_TREE` 默认 `/tmp/r17/ptree`；改树副本路径时同步改 env。

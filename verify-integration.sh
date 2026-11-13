#!/usr/bin/env bash
# 全链集成测试：面板(Flask) -> 命令队列 -> agent --once -> core/egress
#   面板 -> POST /api/cmd 下发命令 -> agent poll 拉取 -> 本地执行
#   -> POST /api/agent/report 回执 -> GET /api/cmd/:id 查 done/failed
#
# 沙箱内运行：用 /tmp 副本（不碰仓库本体与 /etc），面板与 agent 都以
# nobody 身份跑（面板写 admin.pass 时 /etc 写入失败会落到副本 data/）。
# 输出 [PASS]/[FAIL]/[SKIP] 逐项 + 汇总 PASS=x FAIL=y SKIP=z，
# 退出码 = FAIL 数。沙箱无 openvpn/sing-box 真二进制导致的失败记
# SKIP 并写明原因，不冒充 PASS。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTDIR="/tmp/ovpn-int-test"
PANEL_PORT=8443
PANEL_URL="http://127.0.0.1:${PANEL_PORT}"
PASS=0; FAIL=0; SKIP=0

# R2-P2-1: /etc 隔离检查须是跑前/跑后快照比对，不能是存在性判定——
# 任何跑过一次面板的机器上 /etc/openvpn-sk5-panel/admin.pass 早已存在，
# 存在性判定会恒 FAIL。只在本次运行新建或改动该文件时才判 FAIL。
ETC_ADMIN_PASS="/etc/openvpn-sk5-panel/admin.pass"
etc_admin_state() { # -> "exists <sha256> <mtime>" 或 "missing - -"
    if [ -f "$ETC_ADMIN_PASS" ]; then
        printf 'exists %s %s' \
            "$(sha256sum "$ETC_ADMIN_PASS" 2>/dev/null | awk '{print $1}')" \
            "$(stat -c %Y "$ETC_ADMIN_PASS" 2>/dev/null || echo ?)"
    else
        printf 'missing - -'
    fi
}
ETC_ADMIN_BEFORE="$(etc_admin_state)"
ETC_DIR_BEFORE="$(ls /etc/openvpn-sk5-panel 2>/dev/null | sort | tr '\n' ' ')"

ok()   { PASS=$((PASS+1)); echo "[PASS] $1"; }
bad()  { FAIL=$((FAIL+1)); echo "[FAIL] $1"; }
skip() { SKIP=$((SKIP+1)); echo "[SKIP] $1"; }

check() { # check <name> <command...>
    local name="$1"; shift
    if "$@" >/dev/null 2>&1; then ok "$name"; else bad "$name"; fi
}

cleanup() {
    [ -n "${PANEL_PID:-}" ] && kill "$PANEL_PID" 2>/dev/null
    wait "${PANEL_PID:-}" 2>/dev/null
    rm -rf "$TESTDIR"
}
trap cleanup EXIT

# ---------- 0. 准备副本 ----------
rm -rf "$TESTDIR"
mkdir -p "$TESTDIR"
cp -r "$ROOT/agent" "$ROOT/core" "$ROOT/egress" "$ROOT/panel" "$TESTDIR/"
# R2-P2-2: 抄树后清空副本里的 panel/data/：仓库树里一旦落过 panel.db
#（直接 import app.py 就会写），旧库里的 admin 行会被抄走，导致
# _ensure_admin_password() 提前返回、不写 admin.pass，登录连锁失败。
# 只清副本，不动仓库本体。
rm -rf "$TESTDIR/panel/data"
mkdir -p "$TESTDIR/panel/data"
# R4-P2-4: 桩 sing-box（check 过、run 立即退出 0、不建 TUN）+ run 调用
# 日志。面板以 nobody 跑、PATH 首位放桩目录（见 §2）；run 每次调用
# 记一行，供 §4c 断言“已是禁用态的保存不触发守护进程重起”。
# OVPN_SK5_CONFIG_DIR（sk5_manager 的 env 口径，同 OVPN_PANEL_DATA_DIR
# 模式）把面板的 egress 配置目录钉到副本：nobody 写不了 /etc。
mkdir -p "$TESTDIR/stubbin" "$TESTDIR/sk5etc"
cat > "$TESTDIR/stubbin/sing-box" <<'EOF'
#!/bin/sh
# 桩 sing-box（R4-P2-4）：check 过、run 立即退出 0、不建 TUN。
# alive-once：格 B1 前 touch 该文件，run 消费掉它并睡 10 秒（活过
# _start_singbox 的 1 秒存活检查，让一次真实 enable 成功）；无该
# 文件时 run 照旧立即退出，供 disable 重起失败的诚实上报格用。
if [ "$1" = "run" ]; then
    printf '%s run\n' "$(date +%s)" >> "__RUNLOG__"
    if [ -f "__ALIVE__" ]; then
        rm -f "__ALIVE__"
        sleep 10
    fi
    exit 0
fi
exit 0
EOF
sed -i "s|__RUNLOG__|$TESTDIR/stubbin/run.log|" "$TESTDIR/stubbin/sing-box"
sed -i "s|__ALIVE__|$TESTDIR/stubbin/alive-once|" "$TESTDIR/stubbin/sing-box"
chmod +x "$TESTDIR/stubbin/sing-box"
: > "$TESTDIR/stubbin/run.log"
# R4-BUG-1: 桩 systemctl（带 StartLimitBurst=5 语义）+ 桩 ip（有状态
# rule/table100）+ policy-routing.sh 测试替身（仅副本内替换）。
#   systemctl 模式文件 $TESTDIR/sysctl-state/mode（每次调用现读）：
#     nounit（默认）：单元未安装，走 direct 路径——§4c 行为不变；
#     limited：单元已安装，第 6 次 restart 以 start-limit-hit 拒绝，
#       直到 reset-failed 清掉计数（与真 systemd 一致）。
#   真 policy-routing.sh 须 root + 写 /etc/sysctl.d，nobody 身份的
#   门禁面板跑不了它；副本内的替身只做相同的 ip 状态变迁
#   （rule add/del、table-100 replace/flush），测的是 sk5_manager
#   的控制面逻辑（reset-failed、写盘顺序、补策略），不是 shell
#   脚本本身——真脚本由 verify.sh 自带 harness 与真机轮覆盖。
mkdir -p "$TESTDIR/sysctl-state" "$TESTDIR/ipstate"
printf 'nounit\n' > "$TESTDIR/sysctl-state/mode"
cat > "$TESTDIR/stubbin/systemctl" <<'EOF'
#!/bin/sh
# Counting fake systemctl with StartLimitBurst=5 semantics (R4-BUG-1).
S="${FAKE_SYSTEMCTL_STATE:-/tmp/ovpn-int-sysctl}"
mkdir -p "$S"
UNIT="openvpn-sk5-singbox.service"
mode="$(cat "$S/mode" 2>/dev/null || echo nounit)"
case "$1" in
  is-enabled)
    if [ "$mode" = "limited" ] && [ "$3" = "$UNIT" ]; then exit 0; fi
    exit 1;;
  is-active)
    if [ "$mode" = "limited" ] && [ "$3" = "$UNIT" ]; then
      [ -f "$S/active" ] && exit 0 || exit 1
    fi
    exit 1;;
  restart|start)
    if [ "$2" = "$UNIT" ] && [ "$mode" = "limited" ]; then
      if [ -f "$S/failed" ]; then
        echo "Failed to restart $UNIT: start-limit-hit" >&2
        echo "restart FAILED start-limit-hit" >> "$S/log"
        exit 1
      fi
      n="$(cat "$S/starts" 2>/dev/null || echo 0)"; n=$((n+1)); echo "$n" > "$S/starts"
      if [ "$n" -gt 5 ]; then
        touch "$S/failed"; rm -f "$S/active"
        echo "Failed to restart $UNIT: start-limit-hit" >&2
        echo "restart #$n FAILED start-limit-hit" >> "$S/log"
        exit 1
      fi
      touch "$S/active"; echo "restart #$n ok" >> "$S/log"; exit 0
    fi
    exit 0;;
  stop)
    if [ "$2" = "$UNIT" ]; then rm -f "$S/active"; fi
    exit 0;;
  reset-failed)
    if [ "$2" = "$UNIT" ]; then rm -f "$S/failed" "$S/starts"; echo "reset-failed" >> "$S/log"; fi
    exit 0;;
  *) exit 0;;
esac
EOF
cat > "$TESTDIR/stubbin/ip" <<'EOF'
#!/bin/sh
# Stateful fake ip (R4-BUG-1): rule/table100 state in $FAKE_IP_STATE.
S="${FAKE_IP_STATE:-/tmp/ovpn-int-ipstate}"
mkdir -p "$S"
case "$1 $2" in
  "rule show") cat "$S/rules" 2>/dev/null; exit 0;;
  "rule add") echo "100: from 10.8.0.0/24 lookup 100" > "$S/rules"; exit 0;;
  "rule del") rm -f "$S/rules"; exit 0;;
  "route show") cat "$S/table100" 2>/dev/null; exit 0;;
  "route replace") echo "default via 10.9.0.1 dev tun1" > "$S/table100"; exit 0;;
  "route flush") rm -f "$S/table100"; exit 0;;
  "route get") if [ -f "$S/table100" ]; then echo "$4 from $6 via 10.9.0.1 dev tun1 table 100"; else echo "$4 from $6 via 172.26.0.1 dev ens5"; fi; exit 0;;
  "link show") echo "2: tun1: <POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP> mtu 1400 qdisc fq_codel state UNKNOWN mode DEFAULT group default qlen 500"; exit 0;;
  "tuntap add") exit 0;;
  "addr add") exit 0;;
  "link set") exit 0;;
  "addr show") echo "inet 10.9.0.1/30"; exit 0;;
  *) exit 0;;
esac
EOF
chmod +x "$TESTDIR/stubbin/systemctl" "$TESTDIR/stubbin/ip"
cat > "$TESTDIR/egress/policy-routing.sh" <<'EOF'
#!/bin/sh
# TEST DOUBLE (integration gate copy only): same ip state transitions
# as the real policy-routing.sh enable/disable, via the stub ip.
# The real script needs root + an /etc/sysctl.d write, which the
# nobody-run gate panel cannot provide; it is covered by verify.sh's
# own harness and by the live rounds.
# R24-P2-1 (BT): the stub ip models a LIVE tun1 (LOWER_UP -- the
# stub sing-box holds it), and the double answers the repair verb
# too, because sk5_manager.enable() now applies policy with repair
# semantics (no verb in the real script creates tun1 any more).
case "$1" in
  enable|repair)
    ip rule add from 10.8.0.0/24 table 100 priority 100
    ip route replace default via 10.9.0.1 dev tun1 table 100
    ;;
  disable)
    ip rule del from 10.8.0.0/24 table 100 priority 100 2>/dev/null || \
      ip rule del from 10.8.0.0/24 table 100 2>/dev/null || true
    ip route flush table 100 2>/dev/null || true
    ;;
esac
EOF
chmod +x "$TESTDIR/egress/policy-routing.sh"
find "$TESTDIR" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
chown -R nobody:nogroup "$TESTDIR" 2>/dev/null || true

# 8443 被占则整个面板链测不了（app.py 端口写死 8443）。
if python3 -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('127.0.0.1', $PANEL_PORT)); s.close()" 2>/dev/null; then
    skip "面板端口 $PANEL_PORT 已被占用：整条面板链无法在沙箱跑（换空闲机器重跑）"
    echo "PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
    exit 0
fi
ok "面板端口 $PANEL_PORT 空闲"

# ---------- 1. venv + Flask ----------
if ! python3 -m venv "$TESTDIR/venv" 2>/dev/null; then
    skip "建 venv 失败：面板链无法跑"
    echo "PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
    exit 0
fi
if ! "$TESTDIR/venv/bin/pip" install -q flask 2>"$TESTDIR/pip.log"; then
    skip "pip install flask 失败（见 $TESTDIR/pip.log）：面板链无法跑"
    echo "PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
    exit 0
fi
# venv 是 root 建的（site-packages 默认 770），nobody 读不了——放行读权限，
# 否则面板以 nobody 启动时 import flask 失败。
chmod -R a+rX "$TESTDIR/venv"
ok "venv + Flask 就绪"

# ---------- 2. 起面板（nobody 身份，不写 /etc） ----------
# 注意：/tmp 是 noexec，不能直接执行 $TESTDIR/venv/bin/python，改用
# 系统 python3 + PYTHONPATH 指向 venv 的 site-packages（只读 .py 文件即可）。
SITE_PKGS="$TESTDIR/venv/lib/python3.12/site-packages"
[ -d "$SITE_PKGS" ] || SITE_PKGS="$(echo "$TESTDIR"/venv/lib/python*/site-packages)"
# R2-P2-2: 显式把面板数据目录钉到副本（OVPN_PANEL_DATA_DIR，app.py 的
# 新 env 口径；旧版 app.py 不认该变量时仍按 BASE_DIR 落到副本 data/，
# 同样不碰仓库树与 /etc）。
runuser -u nobody -- env PYTHONPATH="$SITE_PKGS" \
    OVPN_PANEL_DATA_DIR="$TESTDIR/panel/data" \
    OVPN_SK5_CONFIG_DIR="$TESTDIR/sk5etc" \
    FAKE_SYSTEMCTL_STATE="$TESTDIR/sysctl-state" \
    FAKE_IP_STATE="$TESTDIR/ipstate" \
    PATH="$TESTDIR/stubbin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    /usr/bin/python3 "$TESTDIR/panel/app.py" \
    > "$TESTDIR/panel.log" 2>&1 &
PANEL_PID=$!
for _ in $(seq 1 30); do
    if curl -fsS --max-time 2 "$PANEL_URL/api/me" >/dev/null 2>&1; then break; fi
    sleep 1
done
if ! kill -0 "$PANEL_PID" 2>/dev/null || \
   ! curl -fsS --max-time 2 "$PANEL_URL/api/me" >/dev/null 2>&1; then
    bad "面板启动失败（见 $TESTDIR/panel.log 尾部）"
    tail -20 "$TESTDIR/panel.log" 2>/dev/null
    echo "PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
    exit "$FAIL"
fi
ok "Flask 面板在 $PANEL_URL 启动（PID $PANEL_PID，nobody 身份）"
ADMIN_PASS="$(cat "$TESTDIR/panel/data/admin.pass" 2>/dev/null || true)"
[ -n "$ADMIN_PASS" ] && ok "管理员密码落到副本 data/admin.pass（未写 /etc）" \
    || bad "未找到副本 data/admin.pass（可能写到了 /etc，测试隔离失败）"
# R2-P2-1: 快照比对（跑前 vs 跑后），不是存在性判定。只在本次运行新建
# 或改动 /etc/openvpn-sk5-panel/admin.pass 时判 FAIL；该文件早已存在
# 且本次未动时是正常态。目录清单另作比对，只作提示、不判 FAIL。
ETC_ADMIN_AFTER="$(etc_admin_state)"
ETC_DIR_AFTER="$(ls /etc/openvpn-sk5-panel 2>/dev/null | sort | tr '\n' ' ')"
if [ "$ETC_ADMIN_BEFORE" != "$ETC_ADMIN_AFTER" ]; then
    bad "本次运行新建或改动了 /etc/openvpn-sk5-panel/admin.pass（隔离失败）：跑前 [$ETC_ADMIN_BEFORE] 跑后 [$ETC_ADMIN_AFTER]"
elif [ "$ETC_DIR_BEFORE" != "$ETC_DIR_AFTER" ]; then
    ok "测试未碰 /etc/openvpn-sk5-panel/admin.pass（目录清单另有变化，跑前 [$ETC_DIR_BEFORE] 跑后 [$ETC_DIR_AFTER]，非本次 admin.pass 写入）"
else
    ok "测试未碰 /etc/openvpn-sk5-panel"
fi

# ---------- 3. 面板 UI 与未登录 ----------
CODE="$(curl -s -o "$TESTDIR/index.html" -w "%{http_code}" --max-time 5 "$PANEL_URL/")"
[ "$CODE" = "200" ] && ok "GET / 200" || bad "GET / 返回 $CODE（期望 200）"
grep -q "入站卡" "$TESTDIR/index.html" \
    && ok "UI 含入站卡标记（<!-- 入站卡：OpenVPN 服务 -->）" \
    || bad "UI 缺入站卡标记"
grep -q "链式出站卡" "$TESTDIR/index.html" \
    && ok "UI 含 SK5 卡标记（<!-- 链式出站卡：SK5 出口 -->）" \
    || bad "UI 缺 SK5 卡标记"
CODE="$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$PANEL_URL/api/status")"
[ "$CODE" = "401" ] && ok "/api/status 未登录 401" || bad "/api/status 未登录返回 $CODE（期望 401）"

# ---------- 4. 登录 + 注册节点 ----------
JAR="$TESTDIR/cookies.txt"
# R6-P2-3 (R1-P2-8 同族复发): never put the admin password in a curl
# -d argv (ps can read it from /proc/<pid>/cmdline). Write it to a
# 0600 file and send via --data @file, same as verify.sh does.
# (python json.dump also escapes special characters in the password,
# which the old shell interpolation did not.)
# R6-BUG-2 (same family, second half): the old `python3 - "$ADMIN_PASS"
# ...` below put the password in python3's argv[1] instead — curl was
# clean but the password was still readable via /proc/<pid>/cmdline.
# So the password now travels via a 0600 file too: python reads it from
# the file, never from argv (and never from the environment, which
# /proc/<pid>/environ exposes the same way).
LOGIN_PAYLOAD="$TESTDIR/login-payload.json"
PASS_FILE="$TESTDIR/admin-pass.txt"
(umask 077; printf '%s' "$ADMIN_PASS" > "$PASS_FILE")
python3 - "$PASS_FILE" "$LOGIN_PAYLOAD" <<'PYEOF'
import json, os, sys
pw_path, path = sys.argv[1], sys.argv[2]
with open(pw_path, encoding="utf-8") as f:
    pw = f.read()
with open(path, "w", encoding="utf-8") as f:
    json.dump({"password": pw}, f)
os.chmod(path, 0o600)
PYEOF
rm -f "$PASS_FILE"
CODE="$(curl -s -c "$JAR" -o /dev/null -w "%{http_code}" --max-time 5 \
    -H "Content-Type: application/json" \
    --data @"$LOGIN_PAYLOAD" "$PANEL_URL/api/login")"
rm -f "$LOGIN_PAYLOAD"
[ "$CODE" = "200" ] && ok "管理员登录 200" || bad "管理员登录返回 $CODE"
NODE_JSON="$(curl -s -b "$JAR" --max-time 5 -H "Content-Type: application/json" \
    -d "{\"name\": \"int-test\", \"panel_url\": \"$PANEL_URL\"}" \
    "$PANEL_URL/api/nodes")"
TOKEN="$(printf '%s' "$NODE_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('token',''))" 2>/dev/null)"
[ -n "$TOKEN" ] && ok "注册节点 int-test 拿到 token（只返回一次）" \
    || bad "注册节点失败：$NODE_JSON"

# ---------- 4b. 登录态 /api/status（R2-P1-4 常驻回归） ----------
# 全脚本唯一一次 /api/status 曾是未登录 401 检查；把 status() 改恒 500
# 后门禁仍全绿（R2 变异实证：18/1 不变）。本格以登录态调一次：变异
# status 恒 500 时本格必须 FAIL，否则门禁对状态端点失明。
STATUS_JSON="$TESTDIR/status-logged-in.json"
CODE="$(curl -s -b "$JAR" -o "$STATUS_JSON" -w "%{http_code}" --max-time 15 "$PANEL_URL/api/status")"
if [ "$CODE" != "200" ]; then
    bad "登录后 GET /api/status 返回 $CODE（期望 200；status() 变异恒 500 时本格必须变红）"
elif python3 -c "
import json
d = json.load(open('$STATUS_JSON'))
assert d.get('ok') is True, d
for k in ('openvpn', 'sk5', 'egress'):
    assert k in d, sorted(d.keys())
assert isinstance(d['openvpn'].get('running'), bool), d['openvpn']
print('status keys ok, running =', d['openvpn']['running'])
" 2>"$TESTDIR/status-check.err"; then
    ok "登录后 GET /api/status 200，含 openvpn/sk5/egress 键，openvpn.running 为布尔值"
else
    bad "登录后 GET /api/status 200 但字段不对（见 $TESTDIR/status-logged-in.json 与 status-check.err）"
fi

# ---------- 4c. SK5 保存不触守护进程（R4-P1-1 回归格，R4-P2-4） ----------
# R4-P1-1 让三套件同时变红，门禁仍 20/20 全绿——它从不 POST /api/sk5。
# 桩 sing-box（§0）：check 过、run 立即退出 0、不建 TUN；run 调用记行。
#   格 A：已是禁用态时全字段保存 {host,port,enabled:false} 须 200，
#        且桩 run 一次都不能被调用（模式未变，不触发重起）。变异：
#        删掉 set_sk5 的模式判断 → 保存走 disable() → 桩 run 被调用
#        → 本格变红。
#   格 B（R6-P2-2 后改写）：单字段 {enabled:false} 在已禁用链上是纯无操作
#        保存（不碰 daemon），旧“重起失败诚实上报”断言不再适用——守护的
#        意图（真翻转 disable 时重起失败须诚实 200、不许 500 抛掉）改在
#        一次真实翻转上验：B1 先 touch alive-once 让桩 run 活过
#        _start_singbox 的 1 秒存活检查（enable 成功，run 恰 1 次）；
#        B2 再 disable，桩 run 立死 → 须诚实 200、回执带
#        singbox_restart_error、策略已撤（run 恰 2 次）。
#        变异：disable() 改抛错 → B2 返回 500 变红。
SK5_BODY='{"host": "127.0.0.1", "port": 11080, "username": "u1", "password": "SECRET1", "enabled": false}'
CODE="$(curl -s -b "$JAR" -o "$TESTDIR/sk5-a1.json" -w "%{http_code}" --max-time 15 \
    -H "Content-Type: application/json" -d "$SK5_BODY" "$PANEL_URL/api/sk5")"
RUNS1="$(wc -l < "$TESTDIR/stubbin/run.log" | tr -d ' ')"
if [ "$CODE" = "200" ] && [ "$RUNS1" = "0" ]; then
    ok "POST /api/sk5 全字段保存（禁用态）200，且桩 sing-box run 未被调用（无操作保存不重起）"
else
    bad "POST /api/sk5 全字段保存（禁用态）返回 $CODE，桩 run 调用 $RUNS1 次（期望 200 且 0 次；见 $TESTDIR/sk5-a1.json）"
fi
CODE="$(curl -s -b "$JAR" -o "$TESTDIR/sk5-a2.json" -w "%{http_code}" --max-time 15 \
    -H "Content-Type: application/json" -d "$SK5_BODY" "$PANEL_URL/api/sk5")"
RUNS2="$(wc -l < "$TESTDIR/stubbin/run.log" | tr -d ' ')"
if [ "$CODE" = "200" ] && [ "$RUNS2" = "0" ]; then
    ok "POST /api/sk5 再次全字段保存（仍禁用态）200，桩 run 仍 0 次"
else
    bad "POST /api/sk5 再次保存返回 $CODE，桩 run 调用 $RUNS2 次（期望 200 且 0 次）"
fi
touch "$TESTDIR/stubbin/alive-once"
CODE="$(curl -s -b "$JAR" -o "$TESTDIR/sk5-b1.json" -w "%{http_code}" --max-time 15 \
    -H "Content-Type: application/json" -d '{"enabled": true}' "$PANEL_URL/api/sk5")"
RUNS_B1="$(wc -l < "$TESTDIR/stubbin/run.log" | tr -d ' ')"
if [ "$CODE" = "200" ] && python3 -c "
import json
d = json.load(open('$TESTDIR/sk5-b1.json'))
s = d.get('sk5', {})
assert d.get('ok') is True, d
assert s.get('enabled') is True, s
assert s.get('singbox_running') is True, s
print('enable ok, daemon up')
" 2>"$TESTDIR/sk5-b1.err" && [ "$RUNS_B1" = "1" ]; then
    ok "格 B1：真翻转 enable 200（alive-once 桩 run 活过存活检查），桩 run 恰 1 次"
else
    bad "格 B1：真翻转 enable 返回 $CODE，桩 run $RUNS_B1 次（期望 200、enabled=true、run 恰 1 次；见 $TESTDIR/sk5-b1.json 与 sk5-b1.err）"
fi
CODE="$(curl -s -b "$JAR" -o "$TESTDIR/sk5-b.json" -w "%{http_code}" --max-time 15 \
    -H "Content-Type: application/json" -d '{"enabled": false}' "$PANEL_URL/api/sk5")"
RUNS3="$(wc -l < "$TESTDIR/stubbin/run.log" | tr -d ' ')"
if [ "$CODE" = "200" ] && python3 -c "
import json
d = json.load(open('$TESTDIR/sk5-b.json'))
s = d.get('sk5', {})
assert d.get('ok') is True, d
assert s.get('enabled') is False, s
assert s.get('singbox_restart_error'), s
assert s.get('policy_routing_active') is False, s
print('disable honest:', s['singbox_restart_error'][:100])
" 2>"$TESTDIR/sk5-b.err" && [ "$RUNS3" = "2" ]; then
    ok "格 B2：真翻转 disable 200，重起失败诚实上报 singbox_restart_error、策略已撤，桩 run 恰 2 次"
else
    bad "格 B2：真翻转 disable 返回 $CODE，桩 run $RUNS3 次（期望 200、回执含 singbox_restart_error、策略已撤、run 恰 2 次；见 $TESTDIR/sk5-b.json 与 sk5-b.err）"
fi

# ---------- 4d. R4-BUG-1: start-limit 风暴 + 策略补修 ----------
# 桩 systemctl 模式文件现读，翻模式对已起的面板立即生效。
#   格 A：7 次 enable/disable 连续切换（第 6 次重起撞限流窗口）须
#        全部 200，最终 enabled+policy+running；桩日志须有 7 次
#        restart + 7 次 reset-failed、0 次限流失败。变异：删掉
#        _start_singbox 的 reset-failed 调用 → 第 7 次 enable 500。
#   格 B：策略被手工删后，已启用态重开须把策略补回来
#        （repaired=true，policy=true）且不得重起守护进程；随后
#        健康态再重开一次须是纯无操作（无 repaired、无新增 restart）。
printf 'limited\n' > "$TESTDIR/sysctl-state/mode"
rm -f "$TESTDIR/sysctl-state/failed" "$TESTDIR/sysctl-state/active" "$TESTDIR/sysctl-state/starts"
# 注意：日志文件绝不能由 root 预建（: > log 会让它 root 所有，nobody
# 跑的桩 systemctl 追加写 EACCES 静默失败、门禁读到 0 行假红）。
# 直接删掉，让桩第一次追加时以 nobody 身份建文件。
rm -f "$TESTDIR/sysctl-state/log"
STORM_OK=1
i=0
while [ "$i" -lt 7 ]; do
    if [ $((i % 2)) -eq 0 ]; then EN=true; else EN=false; fi
    CODE="$(curl -s -b "$JAR" -o "$TESTDIR/sk5-storm-$i.json" -w "%{http_code}" --max-time 20 \
        -H "Content-Type: application/json" \
        -d "{\"host\": \"127.0.0.1\", \"port\": 11080, \"username\": \"u1\", \"password\": \"SECRET1\", \"enabled\": $EN}" \
        "$PANEL_URL/api/sk5")"
    [ "$CODE" = "200" ] || STORM_OK=0
    i=$((i+1))
done
RESTARTS="$(grep -c '^restart #[0-9]* ok' "$TESTDIR/sysctl-state/log" 2>/dev/null || true)"
RESETS="$(grep -c '^reset-failed$' "$TESTDIR/sysctl-state/log" 2>/dev/null || true)"
FAILED_RESTARTS="$(grep -c 'FAILED' "$TESTDIR/sysctl-state/log" 2>/dev/null || true)"
if [ "$STORM_OK" = "1" ] && [ "$RESTARTS" = "7" ] && [ "$RESETS" = "7" ] && [ "$FAILED_RESTARTS" = "0" ] && python3 -c "
import json
d = json.load(open('$TESTDIR/sk5-storm-6.json'))
s = d.get('sk5', {})
assert d.get('ok') is True, d
assert s.get('enabled') is True, s
assert s.get('policy_routing_active') is True, s
assert s.get('singbox_running') is True, s
print('storm final: enabled+policy+running')
" 2>"$TESTDIR/sk5-storm.err"; then
    ok "R4-BUG-1 格 A：7 次 enable/disable 连续切换全部 200，最终 enabled+policy+running；桩 systemctl 7 次 restart + 7 次 reset-failed，0 次限流失败"
else
    bad "R4-BUG-1 格 A：7 次切换未全过（STORM_OK=$STORM_OK，restart=$RESTARTS，reset-failed=$RESETS，限流失败=$FAILED_RESTARTS；见 sk5-storm-*.json 与 sk5-storm.err）"
fi
RESTARTS_B0="$(grep -c '^restart #[0-9]* ok' "$TESTDIR/sysctl-state/log" 2>/dev/null || true)"
FAKE_IP_STATE="$TESTDIR/ipstate" PATH="$TESTDIR/stubbin:$PATH" ip rule del from 10.8.0.0/24 table 100
FAKE_IP_STATE="$TESTDIR/ipstate" PATH="$TESTDIR/stubbin:$PATH" ip route flush table 100
CODE="$(curl -s -b "$JAR" -o "$TESTDIR/sk5-repair.json" -w "%{http_code}" --max-time 20 \
    -H "Content-Type: application/json" \
    -d '{"host": "127.0.0.1", "port": 11080, "username": "u1", "password": "SECRET1", "enabled": true}' \
    "$PANEL_URL/api/sk5")"
RESTARTS_B1="$(grep -c '^restart #[0-9]* ok' "$TESTDIR/sysctl-state/log" 2>/dev/null || true)"
if [ "$CODE" = "200" ] && python3 -c "
import json
d = json.load(open('$TESTDIR/sk5-repair.json'))
s = d.get('sk5', {})
assert d.get('ok') is True, d
assert s.get('repaired') is True, s
assert 'policy routing re-applied' in s.get('repair_detail', []), s
assert s.get('policy_routing_active') is True, s
print('repair ok:', s['repair_detail'])
" 2>"$TESTDIR/sk5-repair.err" && [ "$RESTARTS_B1" = "$RESTARTS_B0" ]; then
    ok "R4-BUG-1 格 B：策略删除后已启用态重开补回策略（repaired=true，policy=true），守护进程未重起"
else
    bad "R4-BUG-1 格 B：重开补策略失败（HTTP $CODE，restart $RESTARTS_B0->$RESTARTS_B1；见 sk5-repair.json 与 sk5-repair.err）"
fi
CODE="$(curl -s -b "$JAR" -o "$TESTDIR/sk5-repair2.json" -w "%{http_code}" --max-time 20 \
    -H "Content-Type: application/json" \
    -d '{"host": "127.0.0.1", "port": 11080, "username": "u1", "password": "SECRET1", "enabled": true}' \
    "$PANEL_URL/api/sk5")"
RESTARTS_B2="$(grep -c '^restart #[0-9]* ok' "$TESTDIR/sysctl-state/log" 2>/dev/null || true)"
if [ "$CODE" = "200" ] && python3 -c "
import json
d = json.load(open('$TESTDIR/sk5-repair2.json'))
s = d.get('sk5', {})
assert d.get('ok') is True, d
assert 'repaired' not in s, s
assert s.get('policy_routing_active') is True, s
print('healthy re-enable is a pure no-op')
" 2>"$TESTDIR/sk5-repair2.err" && [ "$RESTARTS_B2" = "$RESTARTS_B1" ]; then
    ok "R4-BUG-1 格 B2：健康态重开纯无操作（无 repaired、无新增 restart）"
else
    bad "R4-BUG-1 格 B2：健康态重开不是纯无操作（HTTP $CODE，restart $RESTARTS_B1->$RESTARTS_B2；见 sk5-repair2.json）"
fi
# 收尾：关掉 SK5、模式切回 nounit，恢复 §5 期待的禁用态。
CODE="$(curl -s -b "$JAR" -o "$TESTDIR/sk5-cleanup.json" -w "%{http_code}" --max-time 20 \
    -H "Content-Type: application/json" \
    -d '{"host": "127.0.0.1", "port": 11080, "enabled": false}' \
    "$PANEL_URL/api/sk5")"
printf 'nounit\n' > "$TESTDIR/sysctl-state/mode"
[ "$CODE" = "200" ] && ok "R4-BUG-1 收尾：SK5 已关、模式切回 nounit" \
    || bad "R4-BUG-1 收尾 disable 返回 $CODE"

# agent 配置（0600，nobody 所有；面板地址须与注册时逐字一致，否则认领守卫 403）。
AGENT_CFG="$TESTDIR/agent-config.json"
printf '{"panel_url": "%s", "node_token": "%s", "node_name": "int-test"}' \
    "$PANEL_URL" "$TOKEN" > "$AGENT_CFG"
chmod 600 "$AGENT_CFG"
chown nobody:nogroup "$AGENT_CFG"
ok "agent 配置已写 $AGENT_CFG（0600）"

# ---------- 5. 下发 get_status -> agent --once -> 回执 done ----------
cmd_json() { # cmd_json <action> [params-json] -> 打印 cmd_id
    # 注意：不要写 params="${2:-{}}"——bash 会把 ${2:-{} 解析成
    # ${2:-{} + 字面量 }，有参时请求体多一个 } 导致面板 400。
    local action="$1" params="${2:-}"
    [ -n "$params" ] || params="{}"
    curl -s -b "$JAR" --max-time 5 -H "Content-Type: application/json" \
        -d "{\"node\": \"int-test\", \"action\": \"$action\", \"params\": $params}" \
        "$PANEL_URL/api/cmd" | python3 -c "import json,sys; print(json.load(sys.stdin).get('cmd_id',''))"
}
cmd_status() { # cmd_status <id> -> 打印 status
    curl -s -b "$JAR" --max-time 5 "$PANEL_URL/api/cmd/$1" \
        | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))"
}
run_agent_once() {
    runuser -u nobody -- /usr/bin/python3 "$TESTDIR/agent/agent.py" \
        --once --config "$AGENT_CFG" > "$TESTDIR/agent-$1.log" 2>&1
    echo "agent --once ($1) 退出码 $?"
}
wait_cmd() { # wait_cmd <id> <timeout-s> -> 打印最终 status
    local id="$1" end=$((SECONDS + ${2:-30})) st=""
    while [ "$SECONDS" -lt "$end" ]; do
        st="$(cmd_status "$id")"
        case "$st" in done|failed) printf '%s' "$st"; return 0;; esac
        sleep 1
    done
    printf '%s' "$st"
}

CMD1="$(cmd_json get_status)"
[ -n "$CMD1" ] && ok "下发 get_status，cmd_id=$CMD1" || bad "下发 get_status 失败"
run_agent_once get_status
ST1="$(wait_cmd "$CMD1" 5)"
[ "$ST1" = "done" ] && ok "get_status 回执 done（poll→执行→report 全链通）" \
    || bad "get_status 回执为 $ST1（期望 done；agent 日志 $TESTDIR/agent-get_status.log）"
if [ "$ST1" = "done" ]; then
    curl -s -b "$JAR" --max-time 5 "$PANEL_URL/api/cmd/$CMD1" > "$TESTDIR/cmd1.json"
    python3 -c "
import json
r = json.load(open('$TESTDIR/cmd1.json'))['result']
assert 'openvpn' in r and 'sk5' in r, r.keys()
assert r['openvpn'].get('running') is False, r['openvpn']
print('status result keys ok')
" && ok "get_status 回执含 openvpn/sk5，且 openvpn running=false（沙箱未跑服务，属实）" \
        || bad "get_status 回执结果字段不对（见 $TESTDIR/cmd1.json）"
fi

# ---------- 6. 下发 create_user（无 CA，应干净失败，不崩） ----------
CMD2="$(cmd_json create_user '{"name": "smokeuser"}')"
[ -n "$CMD2" ] && ok "下发 create_user smokeuser，cmd_id=$CMD2" || bad "下发 create_user 失败"
run_agent_once create_user
ST2="$(wait_cmd "$CMD2" 5)"
[ "$ST2" = "failed" ] && ok "create_user 回执 failed（无 CA，预期失败）" \
    || bad "create_user 回执为 $ST2（无 CA 时应为 failed）"
if [ "$ST2" = "failed" ]; then
    curl -s -b "$JAR" --max-time 5 "$PANEL_URL/api/cmd/$CMD2" > "$TESTDIR/cmd2.json"
    python3 -c "
import json
r = json.load(open('$TESTDIR/cmd2.json'))
assert r.get('error'), 'error 为空'
assert '-----BEGIN' not in json.dumps(r), '回执含私钥材料'
print('error:', r['error'][:120])
" && ok "create_user 回执 error 非空、无私钥材料泄露" \
        || bad "create_user 回执检查失败（见 $TESTDIR/cmd2.json）"
    if grep -qF "$TOKEN" "$TESTDIR/cmd2.json" 2>/dev/null; then
        bad "回执 JSON 里出现节点 token（泄露）"
    else
        ok "回执 JSON 里无节点 token（无凭据泄露）"
    fi
fi

# ---------- 7. 文档实质断言（R14-P2-3 门禁裁决） ----------
# 钉位 grep 门禁不建，理由（机制，非工作量）：
# (a) 存在性校验对本轮失效模式是空洞的——漂移的 `agent.py:676`
#     行号在范围内（文件 922 行），错的是指向的内容（落在
#     action_revoke_user 内），“行号存在即绿”会在坏钉位上通过。
# (b) 内容感知校验须解析混杂散文：带相邻标识符的单点钉位、
#     断言跨文件相等的区间钉位、不在本树的 FLMX 源引用
#     （panel_install.sh:*，须排除）——文档没有统一可机读文法，
#     专用解析器会在无辜散文编辑上误红，且须自带维护；误报的门
#     禁会被绕过或禁用，比没有门禁更糟。
# (c) 结构上更强的修法是消除钉位本身（AO/AZ 先例）：活文档在树
#     内钉位现仅余 README:198 两处区间，其承载的唯一实质不变量
#     是两处哈希块逐键相等——改按值校验如下，与行号无关。
# README.md「二进制校验」断言钉死在 install.sh 与 agent/agent.py
# 的 sing-box/tun2socks sha256 块逐键相等。R15-P2-1：旧判定只比
# 两文件内全部 64-hex 串的无标签集合相等，对标签间互换全盲
# （m-gate-swap：agent.py 内 amd64/arm64 哈希互换后仍 29/29）；
# 现逐键取 install.sh 的命名赋值与 agent.py 的同名常量比对
# （第一层，防值漂移），逐键相等且非空才绿；变异红证：改任一
# 哈希一位即红，互换任一对常量值亦红（BC 路报告）。
# R16-P2-1：第一层只比常量值，不比运行时绑定——agent 安装校验
# 读的是 `_PINNED_SHA256` 字典（`_pinned_sha256()`），只互换
# 字典两项的值（常量逐字不动），第一层仍绿、安装时却取错哈希
# （m-bc1：`_pinned_sha256("sing-box","amd64")` 返回 arm64 哈希，
# 干净树为 amd64 哈希）。故加第二层（防绑定漂移）：解析字典的
# 4 项 `("binary","arch"): CONSTANT`，逐项要求绑定的常量名须
# 为该 (binary, arch) 命名的常量（`("sing-box","amd64")` 须指向
# `SINGBOX_SHA256_AMD64`，余类推），且该常量的解析值须等于
# install.sh 的同名赋值；字典项数须恰为 4，缺项／多项亦红。
# 两层都绿，本格才绿；任一层红即本格红（门禁仍 29 格）。
_hash_mismatch=0
for _name in SINGBOX_SHA256_AMD64 SINGBOX_SHA256_ARM64 TUN2SOCKS_SHA256_AMD64 TUN2SOCKS_SHA256_ARM64; do
    _h_install="$(grep "^${_name}=" "$ROOT/install.sh" | grep -oE '[0-9a-f]{64}' | head -1)"
    _h_agent="$(grep -A1 "^${_name} = (" "$ROOT/agent/agent.py" | tail -1 | grep -oE '[0-9a-f]{64}' | head -1)"
    if [ -z "$_h_install" ] || [ -z "$_h_agent" ] || [ "$_h_install" != "$_h_agent" ]; then
        _hash_mismatch=1
    fi
done
_dict_mismatch=0
_dict_seen=0
while read -r _bin _arch _const; do
    _dict_seen=$((_dict_seen + 1))
    _want="$(printf '%s' "$_bin" | tr -d '-' | tr 'a-z' 'A-Z')_SHA256_$(printf '%s' "$_arch" | tr 'a-z' 'A-Z')"
    if [ "$_const" != "$_want" ]; then
        _dict_mismatch=1
    fi
    _h_bound="$(grep -A1 "^${_const} = (" "$ROOT/agent/agent.py" | tail -1 | grep -oE '[0-9a-f]{64}' | head -1)"
    _h_install2="$(grep "^${_const}=" "$ROOT/install.sh" | grep -oE '[0-9a-f]{64}' | head -1)"
    if [ -z "$_h_bound" ] || [ -z "$_h_install2" ] || [ "$_h_bound" != "$_h_install2" ]; then
        _dict_mismatch=1
    fi
done < <(sed -n '/^_PINNED_SHA256 = {/,/^}/p' "$ROOT/agent/agent.py" \
    | grep -E '^\s+\("[a-z0-9-]+", "[a-z0-9]+"\): [A-Z0-9_]+,$' \
    | awk -F'"' '{c=$0; sub(/^.*\): */, "", c); sub(/,$/, "", c); print $2, $4, c}')
if [ "$_dict_seen" != 4 ]; then
    _dict_mismatch=1
fi
if [ "$_hash_mismatch" = 0 ] && [ "$_dict_mismatch" = 0 ]; then
    ok "钉死哈希一致：install.sh 与 agent/agent.py 的 sha256 逐键相等"
else
    bad "钉死哈希不一致：install.sh 与 agent/agent.py 的 sha256 逐键不等（见 README 二进制校验）"
fi

echo "PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
exit "$FAIL"

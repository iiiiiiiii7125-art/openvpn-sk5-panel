#!/usr/bin/env bash
# verify.sh -- end-to-end self-check for openvpn-sk5-panel.
#
# Checks (each reported PASS / FAIL / SKIP, never a bare "success"):
#   1. shell syntax of install.sh / verify.sh + required files
#   2. openvpn daemon running (systemd unit or direct process)
#   3. sing-box binary 1.11.x + config valid + unit/process running +
#      steady state (still active after a 3s settle, MainPID alive,
#      tun1 up, zero restarts -- a crash loop must not pass as "up")
#   4. panel answers https://127.0.0.1:8443/api/me (200, no auth)
#   5. panel login with /etc/openvpn-sk5-panel/admin.pass succeeds
#   6. panel GET /api/status returns 200, no missing modules,
#      openvpn.running == true
#   7. create user via API, download .ovpn, assert it embeds
#      <ca>/<cert>/<key> PEM blocks; revoke the user afterwards
#   8. local SOCKS5 stub (python, 127.0.0.1:1080 when free) forwards
#      TCP to a local HTTP server (proves the stub, no real SK5 needed)
#   9. SK5 enable via POST /api/sk5 (stub as the merchant): ip rule /
#      table 100 / route-get from 10.8.0.1 switch to the chain, host
#      route-get stays in main; egress/test-egress.sh cross-check
#  10. /api/status egress.ip is non-empty AND egress.via_sk5=true
#      while the chain is up (R7-P2-12: poll past the 10 s status
#      cache first -- a stale pre-enable snapshot has a non-empty
#      direct-probe ip and would pass an ip-only assertion)
#  11. SK5 disable via POST /api/sk5: rule + table 100 are gone again
#  12. forwarding (BUG-8, mode-aware per R4-BUG-3): FORWARD accepts
#      tun0<->WAN present + kernel route lookup for a VPN source
#      resolves via WAN when SK5 is off, via table 100 (dev tun1)
#      when SK5 is on (mirror of install.sh's mode-aware gate)
#  13. POST /api/sk5/enable -> 200 (AUDIT-R1 proved the old "known
#      defect" claim wrong: the endpoint correctly calls the imported
#      sk5_enable_fn; only probed when the toggle test ran, so it
#      never touches a real merchant SK5)
#  14. agent install chain (R2-BUG-10): install.sh copies agent/ into
#      the installed tree; the installed tree (when present) contains
#      agent/install-agent.sh + agent/agent.py; the live panel serves
#      /api/agent/bundle containing agent/agent.py and
#      /install-agent.sh -> 200
#
# Safety: when a real merchant SK5 is already enabled, the toggle
# checks (sk5-toggle / sk5-egress-ip / sk5-disable) are auto-SKIPped
# and nothing is overwritten. Set VERIFY_ALLOW_OVERWRITE_SK5=1 to
# force the toggle test; before it runs, sk5.json and sing-box.json
# are backed up and cleanup() restores the RUNNING chain via the
# API (POST /api/sk5 enabled=true with the backed-up host/port,
# password kept stored -- never sent) and then copies the backed-up
# files back, so no re-entry of the merchant password is needed
# afterwards. A failed restore is a loud FAIL and leaves the chain
# honestly disabled; a file-only restore would leave enabled=true
# on disk over a direct-mode daemon (R27-P1-1).
#
# Environment-limited checks become SKIP (with the reason), never a
# fake PASS: e.g. no CAP_NET_ADMIN in a sandbox, or no route to
# ifconfig.me (egress.ip needs real internet through the stub).
# Exit code: number of FAILs (0 = all green).
#
# Usage: bash verify.sh
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/openvpn-sk5-panel}"
CONFIG_DIR="/etc/openvpn-sk5-panel"
PANEL_URL="${PANEL_URL:-https://127.0.0.1:8443}"
ADMIN_PASS_FILE="${ADMIN_PASS_FILE:-$CONFIG_DIR/admin.pass}"
WORKDIR="$(mktemp -d /tmp/ovpn-sk5-verify.XXXXXX)"
COOKIE_JAR="$WORKDIR/cookies.txt"
STUB_PY="$WORKDIR/stub.py"
STUB_LOG="$WORKDIR/stub.log"
STUB_PID=""
TEST_USER="verify-$(date +%s)"
SK5_TOGGLED=0
SK5_TOGGLE_RAN=0
SK5_JSON_BACKED_UP=0
SINGBOX_JSON_BACKED_UP=0
PANEL_UP=0
LOGGED_IN=0
INTERNET_OK=""

PASS=0; FAIL=0; SKIP=0
ok()   { PASS=$((PASS+1)); echo "[PASS] $1 -- $2"; }
bad()  { FAIL=$((FAIL+1)); echo "[FAIL] $1 -- $2"; }
skip() { SKIP=$((SKIP+1)); echo "[SKIP] $1 -- $2"; }

json_get() { # json_get <file> <key> -- top-level string/bool/number
    python3 -c "import json,sys; d=json.load(open(sys.argv[1])); v=d.get(sys.argv[2]); print('' if v is None else (str(v).lower() if isinstance(v,bool) else v))" "$1" "$2" 2>/dev/null || echo ""
}
json_path() { # json_path <file> <dotted.path>
    python3 -c "import json,sys; d=json.load(open(sys.argv[1])); v=d
for k in sys.argv[2].split('.'):
    v = v.get(k) if isinstance(v,dict) else None
print('' if v is None else (str(v).lower() if isinstance(v,bool) else v))" "$1" "$2" 2>/dev/null || echo ""
}

cleanup() {
    # This runs on EXIT, so $? at entry is the exit status the
    # script is leaving with; preserve it unless a restore step
    # below fails, in which case force a non-zero exit (a restore
    # failure must never hide behind an ALL GREEN summary).
    local _rc=$?
    local _restore_failed=0
    # Restore prior SK5 state first (best effort, never fatal).
    if [ "$SK5_TOGGLED" -eq 1 ] && [ "$LOGGED_IN" -eq 1 ]; then
        curl -ks --max-time 10 -b "$COOKIE_JAR" -o /dev/null \
            -X POST "$PANEL_URL/api/sk5" -H 'Content-Type: application/json' \
            -d "{\"host\": \"127.0.0.1\", \"port\": $STUB_PORT, \"username\": \"\", \"password\": \"\", \"enabled\": false}" 2>/dev/null || true
        # Revoke the test user (best effort).
        curl -ks --max-time 10 -b "$COOKIE_JAR" -o /dev/null \
            -X DELETE "$PANEL_URL/api/openvpn/users/$TEST_USER" 2>/dev/null || true
    fi
    if [ -n "$STUB_PID" ] && kill -0 "$STUB_PID" 2>/dev/null; then
        kill "$STUB_PID" 2>/dev/null || true
    fi
    # R27-P1-1: restoring the FILES is not restoring the chain.
    # The toggle test's disable rendered a DIRECT sing-box config
    # and restarted the daemon on it; if the pre-verify state had
    # a real SK5 enabled, copying the backed-up sk5.json
    # (enabled=true) and sing-box.json back leaves the RUNNING
    # sing-box direct while the disk says SK5 -- and the next
    # healthcheck tick whitewashes it healthy (the policy
    # re-applies over the live tun1 and test_sk5 dials the
    # merchant SOCKS directly, bypassing the chain). Restore via
    # the API FIRST, while the disk still says enabled=false, so
    # set_sk5 takes the disabled->enabled flip and runs the full
    # enable(): re-render + sing-box restart + policy. The order
    # is load-bearing: restoring the files first and then posting
    # the same values takes set_sk5's still-enabled branch, whose
    # repair only re-applies the policy when the daemon is alive
    # and never restarts it -- the daemon would stay direct.
    # The merchant password is NOT sent: the panel keeps the
    # stored password when the field is absent (P0-4). Only after
    # the API re-enable succeeds are the backed-up files copied
    # back over the identical state enable() just persisted; if
    # the API call fails, the files are NOT restored -- a
    # file-only restore is exactly the divergence -- and the
    # chain is left honestly disabled (re-enable it from the
    # panel; the password is still stored).
    local _PRIOR_ENABLED=""
    if [ "$SK5_JSON_BACKED_UP" -eq 1 ] && [ -f "$WORKDIR/sk5.json.bak" ]; then
        _PRIOR_ENABLED="$(json_get "$WORKDIR/sk5.json.bak" enabled)"
    fi
    if [ "$_PRIOR_ENABLED" = "true" ]; then
        local _BAK_HOST _BAK_PORT _BAK_USER
        _BAK_HOST="$(json_get "$WORKDIR/sk5.json.bak" host)"
        _BAK_PORT="$(json_get "$WORKDIR/sk5.json.bak" port)"
        _BAK_USER="$(json_get "$WORKDIR/sk5.json.bak" username)"
        if [ -z "$_BAK_HOST" ] || [ -z "$_BAK_PORT" ]; then
            echo "[FAIL] cleanup-restore-sk5 -- backed-up sk5.json has no usable host/port; merchant SK5 left DISABLED (re-enable it from the panel; the password is still stored); backup kept in $WORKDIR"
            _restore_failed=1
        elif [ "$LOGGED_IN" -ne 1 ]; then
            echo "[FAIL] cleanup-restore-sk5 -- not logged in; cannot re-enable the merchant SK5 via the API; merchant SK5 left DISABLED (re-enable it from the panel); backup kept in $WORKDIR"
            _restore_failed=1
        else
            local _REENABLE_BODY _REENABLE_CODE
            _REENABLE_BODY="$(python3 -c "import json,sys; print(json.dumps({'host': sys.argv[1], 'port': int(sys.argv[2]), 'username': sys.argv[3], 'enabled': True}))" "$_BAK_HOST" "$_BAK_PORT" "$_BAK_USER" 2>/dev/null || true)"
            _REENABLE_CODE="$(curl -ks --max-time 30 -b "$COOKIE_JAR" -o "$WORKDIR/sk5reenable.json" \
                -w '%{http_code}' -X POST "$PANEL_URL/api/sk5" \
                -H 'Content-Type: application/json' \
                -d "$_REENABLE_BODY" 2>/dev/null || true)"
            if [ "$_REENABLE_CODE" = "200" ] && [ "$(json_get "$WORKDIR/sk5reenable.json" ok)" = "true" ]; then
                echo "[PASS] cleanup-restore-sk5 -- merchant SK5 re-enabled via API (host=$_BAK_HOST port=$_BAK_PORT, password kept stored); running chain restored, not just the files"
            else
                echo "[FAIL] cleanup-restore-sk5 -- POST /api/sk5 enabled=true -> HTTP $_REENABLE_CODE body: $(head -c 300 "$WORKDIR/sk5reenable.json" 2>/dev/null); merchant SK5 left DISABLED (re-enable it from the panel; the password is still stored); backup kept in $WORKDIR"
                _restore_failed=1
            fi
        fi
    fi
    # Copy the backed-up files back -- but never over a failed API
    # re-enable: files saying enabled=true over a direct daemon is
    # the divergence this restores from. A failed cp is a loud
    # FAIL, never a silent `|| true`.
    if [ "$_restore_failed" -eq 0 ]; then
        if [ "$SK5_JSON_BACKED_UP" -eq 1 ]; then
            if ! cp "$WORKDIR/sk5.json.bak" "$CONFIG_DIR/sk5.json" 2>/dev/null; then
                echo "[FAIL] cleanup-restore-sk5 -- cp sk5.json.bak -> $CONFIG_DIR/sk5.json failed; the running chain was already restored by the API above, but the file copy did not land -- check $CONFIG_DIR/sk5.json; backup kept in $WORKDIR"
                _restore_failed=1
            fi
        elif [ -f "$CONFIG_DIR/sk5.json" ] && [ "${SK5_JSON_EXISTED:-0}" -eq 0 ]; then
            if ! rm -f "$CONFIG_DIR/sk5.json" 2>/dev/null; then
                echo "[FAIL] cleanup-restore-sk5 -- rm of toggle-created $CONFIG_DIR/sk5.json failed; a disabled stub config was left behind -- remove it by hand; workdir kept in $WORKDIR"
                _restore_failed=1
            fi
        fi
        if [ "$SINGBOX_JSON_BACKED_UP" -eq 1 ]; then
            if ! cp "$WORKDIR/sing-box.json.bak" "$CONFIG_DIR/sing-box.json" 2>/dev/null; then
                echo "[FAIL] cleanup-restore-sk5 -- cp sing-box.json.bak -> $CONFIG_DIR/sing-box.json failed; the running chain was already restored by the API above, but the file copy did not land -- check $CONFIG_DIR/sing-box.json; backup kept in $WORKDIR"
                _restore_failed=1
            fi
        fi
    fi
    if [ "$_restore_failed" -eq 1 ]; then
        # Keep the workdir (backups + API responses) for manual
        # recovery; force a non-zero exit even if every check
        # passed -- the ALL GREEN line above does not cover cleanup.
        echo "[FAIL] cleanup-restore-sk5 -- restore FAILED (see lines above); workdir kept at $WORKDIR"
        if [ "$_rc" -ne 0 ]; then exit "$_rc"; else exit 1; fi
    fi
    rm -rf "$WORKDIR"
    exit "$_rc"
}
trap cleanup EXIT

internet_ok() {
    if [ -z "$INTERNET_OK" ]; then
        if curl -sS --max-time 8 http://ifconfig.me -o /dev/null 2>/dev/null; then
            INTERNET_OK=1
        else
            INTERNET_OK=0
        fi
    fi
    [ "$INTERNET_OK" -eq 1 ]
}

echo "== openvpn-sk5-panel verify =="
echo "project: $PROJECT_DIR   panel: $PANEL_URL   workdir: $WORKDIR"
echo

# ---------------------------------------------------------------- 1. syntax/files
if bash -n "$PROJECT_DIR/install.sh" && bash -n "$PROJECT_DIR/verify.sh"; then
    ok "syntax" "bash -n clean for install.sh + verify.sh"
else
    bad "syntax" "bash -n failed (see output above)"
fi
# R2-P1-5: 清单必须覆盖全部 5 个 systemd 单元 + agent + 前端 + 两模板
# + test-egress.sh。旧清单只列 2 个单元，删 healthcheck.timer 仍 PASS。
_missing=""
for _f in "$PROJECT_DIR/install.sh" "$PROJECT_DIR/verify.sh" "$PROJECT_DIR/README.md" \
          "$PROJECT_DIR/systemd/openvpn-sk5-panel.service" \
          "$PROJECT_DIR/systemd/openvpn-sk5-singbox.service" \
          "$PROJECT_DIR/systemd/openvpn-sk5-policy.service" \
          "$PROJECT_DIR/systemd/openvpn-sk5-healthcheck.service" \
          "$PROJECT_DIR/systemd/openvpn-sk5-healthcheck.timer" \
          "$PROJECT_DIR/agent/agent.py" \
          "$PROJECT_DIR/panel/app.py" "$PROJECT_DIR/panel/requirements.txt" \
          "$PROJECT_DIR/panel/templates/index.html" \
          "$PROJECT_DIR/core/openvpn_manager.py" "$PROJECT_DIR/core/easyrsa.sh" \
          "$PROJECT_DIR/core/server.conf.template" \
          "$PROJECT_DIR/egress/sk5_manager.py" "$PROJECT_DIR/egress/policy-routing.sh" \
          "$PROJECT_DIR/egress/sing-box.json.template" \
          "$PROJECT_DIR/egress/test-egress.sh"; do
    [ -f "$_f" ] || _missing="$_missing $_f"
done
if [ -z "$_missing" ]; then
    ok "files" "install.sh, verify.sh, README.md, 5 systemd units (panel/singbox/policy/healthcheck service+timer), agent/agent.py, panel/app.py + templates/index.html, core (manager/easyrsa/server.conf.template), egress (manager/policy-routing/sing-box template/test-egress.sh) present"
else
    bad "files" "missing:${_missing}"
fi
# R2-BUG-10: the installed tree must carry agent/ -- the panel serves
# /install-agent.sh, /install-agent.sh.sha256 and /api/agent/bundle
# from the installed tree, so a tree without agent/ makes the whole
# agent-install chain 404/500 on a fresh install (live-verify-R2
# S0-agent), while the repo-tree gates above stay green (they run
# against the checkout, where agent/ is always present). Two layers:
# (a) static: install.sh's copy step must include agent/;
# (b) runtime: when an installed tree exists on this host, it must
# contain agent/install-agent.sh + agent/agent.py.
# Static layer accepts EITHER copy mechanism, both must name agent/:
# (a) loop form (Fix R): "for _item in ... agent ..." + cp -a "$SCRIPT_DIR/$_item";
# (b) literal form: cp -a ... "$SCRIPT_DIR/agent". A loop that drops
# agent from its item list, or a cp line that no longer copies $_item,
# must both go red -- the single-literal grep this replaces went red
# by construction the moment Fix R refactored the copy into a loop
# (agent/ was still copied; the gate lied, not the installer).
_COPIES_AGENT=0
if grep -q 'for _item in .*\<agent\>' "$PROJECT_DIR/install.sh" \
    && grep -q 'cp -a "\$SCRIPT_DIR/\$_item"' "$PROJECT_DIR/install.sh"; then
    _COPIES_AGENT=1
elif grep -q 'cp -a.*"\$SCRIPT_DIR/agent"' "$PROJECT_DIR/install.sh"; then
    _COPIES_AGENT=1
fi
if [ "$_COPIES_AGENT" -eq 1 ]; then
    ok "install-copies-agent" "install.sh copies agent/ into the install tree"
else
    bad "install-copies-agent" "install.sh does not copy agent/ into the install tree (R2-BUG-10: fresh installs serve 404 for /install-agent.sh)"
fi
if [ -d "$INSTALL_ROOT" ]; then
    if [ -f "$INSTALL_ROOT/agent/install-agent.sh" ] && [ -f "$INSTALL_ROOT/agent/agent.py" ]; then
        ok "installed-agent-tree" "$INSTALL_ROOT/agent/ present (install-agent.sh + agent.py)"
    else
        bad "installed-agent-tree" "$INSTALL_ROOT exists but lacks agent/install-agent.sh or agent/agent.py (R2-BUG-10: panel agent endpoints will 404/500)"
    fi
else
    skip "installed-agent-tree" "no installed tree at $INSTALL_ROOT on this host (repo checkout only)"
fi

# ---------------------------------------------------------------- 2. openvpn
SYSTEMD=0
[ "$(ps -p 1 -o comm= 2>/dev/null || echo ?)" = "systemd" ] && SYSTEMD=1
OVPN_RUNNING=0
if [ "$SYSTEMD" -eq 1 ] && systemctl is-active --quiet openvpn-server@server 2>/dev/null; then
    OVPN_RUNNING=1
    ok "openvpn" "systemctl is-active openvpn-server@server"
elif pgrep -x openvpn >/dev/null 2>&1; then
    OVPN_RUNNING=1
    ok "openvpn" "openvpn process running (pid $(pgrep -x openvpn | head -1), systemd not PID 1)"
else
    bad "openvpn" "openvpn-server@server not active and no openvpn process (is install.sh finished?)"
fi

# ---------------------------------------------------------------- 3. sing-box
if command -v sing-box >/dev/null 2>&1; then
    SB_VER="$(sing-box version 2>/dev/null | head -1 || echo '?')"
    if printf '%s' "$SB_VER" | grep -q "1\.11\."; then
        ok "sing-box-version" "sing-box $SB_VER (pinned 1.11.x)"
    else
        bad "sing-box-version" "sing-box reports '$SB_VER', expected 1.11.x"
    fi
else
    bad "sing-box-version" "sing-box binary not found in PATH"
fi
# R2-P2-6: 缺文件 / 缺二进制分两支报错，不许文件存在却报“no sing-box.json
# to check”（沙箱基线就是文件在、缺二进制，旧文案会把排障引向查文件）。
if [ ! -f "$CONFIG_DIR/sing-box.json" ]; then
    bad "sing-box-config" "no $CONFIG_DIR/sing-box.json to check (install.sh 未生成渲染配置)"
elif ! command -v sing-box >/dev/null 2>&1; then
    bad "sing-box-config" "$CONFIG_DIR/sing-box.json exists but no sing-box binary in PATH (cannot run sing-box check; install sing-box first)"
elif sing-box check -c "$CONFIG_DIR/sing-box.json" >/dev/null 2>&1; then
    ok "sing-box-config" "sing-box check -c $CONFIG_DIR/sing-box.json passed"
else
    bad "sing-box-config" "sing-box check failed: $(sing-box check -c "$CONFIG_DIR/sing-box.json" 2>&1 | tail -1)"
fi
# R2-P2-8: 首装 heredoc 与模板 tun 段一致性钉子。
# install.sh 首装 starter 配置是手写 heredoc（以 cat > "$CONFIG_DIR/sing-box.json" <<'EOF' 开头的 heredoc；行号随插入浮动，定位用该 marker），与
# egress/sing-box.json.template 双份维护；模板一改（如 BUG-1 的 address
# 字段），heredoc 必须同步，否则首装直连模式仍用旧字段、sing-box check
# 即 FATAL。本格比对两处的 tun 入站对象（全字段）与 dns.final；
# route.final 故意不比：starter 是直连模式（final=direct），模板是
# SK5 链模式（final=bought-sk5），两者本就不同。
if [ -f "$PROJECT_DIR/install.sh" ] && [ -f "$PROJECT_DIR/egress/sing-box.json.template" ]; then
    _HEREDOC_JSON="$WORKDIR/starter-sing-box.json"
    if ! awk '/cat > "\$CONFIG_DIR\/sing-box.json" <<.EOF./{flag=1; next} /^EOF$/{flag=0} flag' \
            "$PROJECT_DIR/install.sh" > "$_HEREDOC_JSON" 2>/dev/null \
        || [ ! -s "$_HEREDOC_JSON" ]; then
        bad "starter-template-consistency" "cannot extract starter sing-box config heredoc from install.sh (marker changed?)"
    elif python3 - "$_HEREDOC_JSON" "$PROJECT_DIR/egress/sing-box.json.template" <<'PYEOF' 2>"$WORKDIR/starter-template.err"; then
import json, sys

def load_template(path):
    # 模板不是直接可解析的 JSON：先去 '#' 注释行，再按模板头 CHECK 节
    # 的办法把占位符换成假值（__SK5_PORT__ 无引号，须换成裸数字 1080）。
    text = open(path, encoding="utf-8").read()
    lines = [ln for ln in text.splitlines()
             if not ln.lstrip().startswith("#")]
    text = "\n".join(lines)
    for ph, val in (("__SK5_HOST__", "proxy.example.net"),
                    ("__SK5_PORT__", "1080"),
                    ("__SK5_USER__", "u1"),
                    ("__SK5_PASS__", "p1")):
        text = text.replace(ph, val)
    return json.loads(text)

starter = json.load(open(sys.argv[1], encoding="utf-8"))
template = load_template(sys.argv[2])

def tun(cfg):
    for ib in cfg.get("inbounds", []):
        if ib.get("type") == "tun":
            return ib
    raise AssertionError("no tun inbound")

t_starter, t_template = tun(starter), tun(template)
assert t_starter == t_template, (
    "tun inbound differs:\n starter=%r\n template=%r"
    % (t_starter, t_template))
assert starter["dns"]["final"] == template["dns"]["final"], (
    "dns.final differs: starter=%r template=%r"
    % (starter["dns"]["final"], template["dns"]["final"]))
print("tun inbound identical; dns.final=%r" % starter["dns"]["final"])
PYEOF
        ok "starter-template-consistency" "install.sh 首装 heredoc 与 sing-box.json.template 的 tun 入站全字段一致，dns.final 一致（route.final 故意不同：starter=direct，模板=bought-sk5）"
    else
        bad "starter-template-consistency" "首装 heredoc 与模板 tun 段不一致（见 $WORKDIR/starter-template.err；改模板必同步 install.sh heredoc，见 README 二进制校验一节）"
    fi
else
    skip "starter-template-consistency" "install.sh 或 sing-box.json.template 缺失，无法比对"
fi
SB_RUNNING=0
if [ "$SYSTEMD" -eq 1 ] && systemctl is-active --quiet openvpn-sk5-singbox 2>/dev/null; then
    SB_RUNNING=1
    ok "sing-box-running" "systemctl is-active openvpn-sk5-singbox"
elif [ -f "$CONFIG_DIR/sing-box.pid" ] && kill -0 "$(cat "$CONFIG_DIR/sing-box.pid" 2>/dev/null)" 2>/dev/null; then
    SB_RUNNING=1
    ok "sing-box-running" "sing-box running via direct PID file (no systemd unit active)"
elif pgrep -x sing-box >/dev/null 2>&1; then
    SB_RUNNING=1
    ok "sing-box-running" "sing-box process running (pid $(pgrep -x sing-box | head -1))"
else
    bad "sing-box-running" "openvpn-sk5-singbox not active and no sing-box process"
fi
# BUG-3: is-active alone can catch a transient active moment of a
# crash-looping service. Require steady state: still active after a
# 3s settle, the unit's MainPID alive, tun1 present, zero restarts.
# (MainPID, not pgrep: other software on the host may run its own
# sing-box, and pgrep cannot tell it apart.)
if [ "$SB_RUNNING" -eq 1 ]; then
    if [ "$SYSTEMD" -eq 1 ]; then
        sleep 3
        SB_PID="$(systemctl show openvpn-sk5-singbox -p MainPID --value 2>/dev/null || echo 0)"
        SB_RESTARTS="$(systemctl show openvpn-sk5-singbox -p NRestarts --value 2>/dev/null || echo "")"
        if systemctl is-active --quiet openvpn-sk5-singbox 2>/dev/null \
            && [ "${SB_PID:-0}" -gt 0 ] 2>/dev/null && kill -0 "$SB_PID" 2>/dev/null \
            && ip link show dev tun1 >/dev/null 2>&1 \
            && { [ -z "$SB_RESTARTS" ] || [ "$SB_RESTARTS" = "0" ]; }; then
            ok "sing-box-steady" "still active after 3s settle, main PID $SB_PID alive, tun1 up, restarts=${SB_RESTARTS:-unknown}"
        else
            bad "sing-box-steady" "sing-box not steady (active=$(systemctl is-active openvpn-sk5-singbox 2>/dev/null), main PID=${SB_PID:-?}, restarts=${SB_RESTARTS:-?}; see journalctl -u openvpn-sk5-singbox)"
        fi
    elif ip link show dev tun1 >/dev/null 2>&1; then
        ok "sing-box-steady" "sing-box process running + tun1 up (no systemd as PID 1, steady window not applicable)"
    else
        bad "sing-box-steady" "sing-box process running but tun1 missing (config never applied?)"
    fi
else
    skip "sing-box-steady" "sing-box not running, see sing-box-running above"
fi

# ---------------------------------------------------------------- 4-6. panel
ME_CODE="$(curl -ks --max-time 10 -o "$WORKDIR/me.json" -w '%{http_code}' "$PANEL_URL/api/me" 2>/dev/null || true)"
if [ "$ME_CODE" = "200" ]; then
    PANEL_UP=1
    ok "panel-reachable" "GET $PANEL_URL/api/me -> 200"
else
    bad "panel-reachable" "GET $PANEL_URL/api/me -> HTTP $ME_CODE (panel down? curl -k https://127.0.0.1:8443/api/me)"
fi

if [ "$PANEL_UP" -eq 1 ]; then
    if [ -f "$ADMIN_PASS_FILE" ]; then
        ADMIN_PASS="$(head -1 "$ADMIN_PASS_FILE" | tr -d '[:space:]')"
        # P2-8: never put the admin password in a curl -d argv (ps can
        # read it from /proc/<pid>/cmdline). Send it via a 0600 file.
        # R6-BUG-2 (same family, second half): the old `python3 -
        # "$ADMIN_PASS" ...` below put the password in python3's
        # argv[1] instead — curl was clean but the password was still
        # readable via /proc/<pid>/cmdline. So the password now travels
        # via a 0600 file too: python reads it from the file, never
        # from argv (and never from the environment, which
        # /proc/<pid>/environ exposes the same way).
        PASS_FILE="$WORKDIR/admin-pass.txt"
        (umask 077; printf '%s' "$ADMIN_PASS" > "$PASS_FILE")
        python3 - "$PASS_FILE" "$WORKDIR/login-payload.json" <<'PYEOF'
import json, os, sys
pw_path, path = sys.argv[1], sys.argv[2]
with open(pw_path, encoding="utf-8") as f:
    pw = f.read()
with open(path, "w", encoding="utf-8") as f:
    json.dump({"password": pw}, f)
os.chmod(path, 0o600)
PYEOF
        LOGIN_CODE="$(curl -ks --max-time 10 -c "$COOKIE_JAR" -o "$WORKDIR/login.json" \
            -w '%{http_code}' -X POST "$PANEL_URL/api/login" \
            -H 'Content-Type: application/json' --data @"$WORKDIR/login-payload.json" 2>/dev/null || true)"
        rm -f "$WORKDIR/login-payload.json" "$PASS_FILE"
        if [ "$LOGIN_CODE" = "200" ] && [ "$(json_get "$WORKDIR/login.json" ok)" = "true" ]; then
            LOGGED_IN=1
            ok "panel-login" "POST /api/login with $ADMIN_PASS_FILE -> ok"
        else
            bad "panel-login" "POST /api/login -> HTTP $LOGIN_CODE body: $(head -c 200 "$WORKDIR/login.json" 2>/dev/null)"
        fi
    else
        bad "panel-login" "no admin password file at $ADMIN_PASS_FILE"
    fi
else
    skip "panel-login" "panel unreachable, cannot test login"
fi

if [ "$LOGGED_IN" -eq 1 ]; then
    STATUS_CODE="$(curl -ks --max-time 15 -b "$COOKIE_JAR" -o "$WORKDIR/status.json" \
        -w '%{http_code}' "$PANEL_URL/api/status" 2>/dev/null || true)"
    if [ "$STATUS_CODE" = "200" ]; then
        MISSING="$(python3 -c "import json; print(','.join(json.load(open('$WORKDIR/status.json')).get('modules_missing',[])))" 2>/dev/null || echo '?')"
        OVPN_RUN="$(json_path "$WORKDIR/status.json" openvpn.running)"
        if [ -z "$MISSING" ] && [ "$OVPN_RUN" = "true" ]; then
            ok "panel-status" "GET /api/status -> 200, modules_missing empty, openvpn.running=true"
        elif [ -z "$MISSING" ]; then
            bad "panel-status" "GET /api/status -> 200 but openvpn.running=$OVPN_RUN (daemon down?)"
        else
            bad "panel-status" "GET /api/status -> 200 but modules_missing=[$MISSING]"
        fi
    else
        bad "panel-status" "GET /api/status -> HTTP $STATUS_CODE"
    fi
    # R2-BUG-10 (bundle contents): the panel must actually serve an
    # agent bundle that CONTAINS agent code, and /install-agent.sh
    # must be 200 -- a bundle of core+egress only (the live-verify-R2
    # failure) installs nothing. Only runs when logged in (panel up).
    _BUNDLE_CODE="$(curl -ks --max-time 30 -o "$WORKDIR/bundle.tar.gz" \
        -w '%{http_code}' "$PANEL_URL/api/agent/bundle" 2>/dev/null || true)"
    # R3-BUG-2: never pipe tar straight into grep -q under pipefail --
    # grep -q exits at the first hit and tar then dies on SIGPIPE
    # (141), which pipefail turns into a false FAIL. Capture the
    # listing first, then grep the variable.
    _BUNDLE_LIST="$(tar -tzf "$WORKDIR/bundle.tar.gz" 2>/dev/null || true)"
    if [ "$_BUNDLE_CODE" = "200" ] && printf '%s' "$_BUNDLE_LIST" | grep -q "^agent/agent.py$"; then
        ok "agent-bundle" "GET /api/agent/bundle -> 200, tarball contains agent/agent.py"
    else
        bad "agent-bundle" "GET /api/agent/bundle -> HTTP $_BUNDLE_CODE or tarball lacks agent/agent.py (R2-BUG-10)"
    fi
    _IAS_CODE="$(curl -ks --max-time 10 -o /dev/null -w '%{http_code}' \
        "$PANEL_URL/install-agent.sh" 2>/dev/null || true)"
    if [ "$_IAS_CODE" = "200" ]; then
        ok "install-agent-script" "GET /install-agent.sh -> 200"
    else
        bad "install-agent-script" "GET /install-agent.sh -> HTTP $_IAS_CODE (R2-BUG-10)"
    fi
else
    skip "panel-status" "not logged in"
fi

# ---------------------------------------------------------------- 7. user + ovpn
if [ "$LOGGED_IN" -eq 1 ]; then
    CREATE_CODE="$(curl -ks --max-time 30 -b "$COOKIE_JAR" -o "$WORKDIR/create.json" \
        -w '%{http_code}' -X POST "$PANEL_URL/api/openvpn/users" \
        -H 'Content-Type: application/json' -d "{\"name\": \"$TEST_USER\"}" 2>/dev/null || true)"
    if [ "$CREATE_CODE" = "200" ] && [ "$(json_get "$WORKDIR/create.json" ok)" = "true" ]; then
        OVPN_CODE="$(curl -ks --max-time 15 -b "$COOKIE_JAR" -o "$WORKDIR/test.ovpn" \
            -w '%{http_code}' "$PANEL_URL/api/openvpn/users/$TEST_USER/ovpn" 2>/dev/null || true)"
        if [ "$OVPN_CODE" = "200" ] \
            && grep -q "BEGIN CERTIFICATE" "$WORKDIR/test.ovpn" 2>/dev/null \
            && grep -q "<ca>" "$WORKDIR/test.ovpn" 2>/dev/null \
            && grep -q "<cert>" "$WORKDIR/test.ovpn" 2>/dev/null \
            && grep -q "<key>" "$WORKDIR/test.ovpn" 2>/dev/null \
            && grep -q "^client" "$WORKDIR/test.ovpn" 2>/dev/null \
            && grep -q "^remote " "$WORKDIR/test.ovpn" 2>/dev/null; then
            ok "user-ovpn" "created $TEST_USER, downloaded .ovpn ($OVPN_CODE) with <ca>/<cert>/<key> PEM blocks + client/remote lines"
        else
            bad "user-ovpn" "user created but .ovpn download/check failed (HTTP $OVPN_CODE, $(wc -c < "$WORKDIR/test.ovpn" 2>/dev/null || echo 0) bytes)"
        fi
    else
        bad "user-ovpn" "POST /api/openvpn/users -> HTTP $CREATE_CODE body: $(head -c 300 "$WORKDIR/create.json" 2>/dev/null)"
    fi
else
    skip "user-ovpn" "not logged in"
fi

# ---------------------------------------------------------------- 8. local SOCKS5 stub
# Pick 1080 when free (matches the brief's 127.0.0.1:1080), else a free port.
STUB_PORT="$(python3 -c "
import socket
s = socket.socket()
try:
    s.bind(('127.0.0.1', 1080)); print(1080)
except OSError:
    s2 = socket.socket(); s2.bind(('127.0.0.1', 0)); print(s2.getsockname()[1]); s2.close()
s.close()
" 2>/dev/null || echo 11080)"
HTTP_PORT="$(python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1]); s.close()" 2>/dev/null || echo 18080)"
cat > "$STUB_PY" <<'PYEOF'
# Minimal SOCKS5 stub for verify.sh: no-auth + user/pass CONNECT, TCP
# relay only (no UDP -- the stub proves the TCP leg; UDP ASSOCIATE is
# proven separately by egress/test-egress.sh + sk5_manager.test_sk5()).
# Also serves a tiny HTTP endpoint returning the peer IP, so the stub
# itself can be proven end-to-end without any real merchant or internet.
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOCKS_PORT = int(sys.argv[1])
HTTP_PORT = int(sys.argv[2])


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"client_ip": self.client_address[0], "ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def relay(a, b):
    try:
        while True:
            d = a.recv(65536)
            if not d:
                break
            b.sendall(d)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass


def handle(conn):
    try:
        h = conn.recv(2)
        if len(h) < 2:
            return
        methods = conn.recv(h[1])
        if 0x00 in methods:
            conn.sendall(b"\x05\x00")
        elif 0x02 in methods:
            conn.sendall(b"\x05\x02")
            v = conn.recv(2)
            ulen = conn.recv(1)[0]
            conn.recv(ulen)
            plen = conn.recv(1)[0]
            conn.recv(plen)
            conn.sendall(b"\x05\x00")
        else:
            conn.sendall(b"\x05\xff")
            return
        req = conn.recv(4)
        if len(req) < 4 or req[0] != 5 or req[1] != 1:
            conn.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            return
        atyp = req[3]
        if atyp == 1:
            host = socket.inet_ntoa(conn.recv(4))
        elif atyp == 3:
            host = conn.recv(conn.recv(1)[0]).decode()
        elif atyp == 4:
            host = socket.inet_ntop(socket.AF_INET6, conn.recv(16))
        else:
            conn.sendall(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
            return
        port = int.from_bytes(conn.recv(2), "big")
        try:
            out = socket.create_connection((host, port), timeout=10)
        except OSError:
            conn.sendall(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")
            return
        conn.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        t1 = threading.Thread(target=relay, args=(conn, out), daemon=True)
        t2 = threading.Thread(target=relay, args=(out, conn), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", SOCKS_PORT))
srv.listen(64)
httpd = ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), H)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print("STUB_READY socks5=127.0.0.1:%d http=127.0.0.1:%d" % (SOCKS_PORT, HTTP_PORT), flush=True)
while True:
    c, _ = srv.accept()
    threading.Thread(target=handle, args=(c,), daemon=True).start()
PYEOF
python3 "$STUB_PY" "$STUB_PORT" "$HTTP_PORT" > "$STUB_LOG" 2>&1 &
STUB_PID=$!
STUB_UP=0
for _i in $(seq 1 20); do
    grep -q STUB_READY "$STUB_LOG" 2>/dev/null && { STUB_UP=1; break; }
    sleep 0.25
done
if [ "$STUB_UP" -eq 1 ]; then
    STUB_BODY="$(curl -sS --max-time 10 --socks5-hostname "127.0.0.1:$STUB_PORT" \
        "http://127.0.0.1:$HTTP_PORT/" 2>/dev/null || echo '')"
    if printf '%s' "$STUB_BODY" | grep -q '"client_ip": "127.0.0.1"'; then
        ok "stub-socks5" "local stub 127.0.0.1:$STUB_PORT forwards TCP to local HTTP (client_ip=127.0.0.1)"
    else
        bad "stub-socks5" "stub up but curl via it failed (body: ${STUB_BODY:-<empty>})"
    fi
else
    bad "stub-socks5" "local SOCKS5 stub did not start (see $STUB_LOG)"
fi

# ---------------------------------------------------------------- 9-11. SK5 toggle
# Prior-state guard: never overwrite a real merchant SK5 (its password
# is not recoverable from the panel API).
SK5_PRIOR_HOST=""; SK5_PRIOR_ENABLED="false"
if [ "$LOGGED_IN" -eq 1 ]; then
    if curl -ks --max-time 10 -b "$COOKIE_JAR" -o "$WORKDIR/sk5prior.json" \
            "$PANEL_URL/api/sk5" 2>/dev/null; then
        SK5_PRIOR_HOST="$(json_get "$WORKDIR/sk5prior.json" host 2>/dev/null || true)"
        # /api/sk5 returns {ok, sk5: {...}}; dig into .sk5
        SK5_PRIOR_HOST="$(json_path "$WORKDIR/sk5prior.json" sk5.host)"
        SK5_PRIOR_ENABLED="$(json_path "$WORKDIR/sk5prior.json" sk5.enabled)"
    fi
fi
SK5_JSON_EXISTED=0
[ -f "$CONFIG_DIR/sk5.json" ] && SK5_JSON_EXISTED=1

route_checks() { # route_checks <expect: on|off> -- returns 0/1, prints detail
    # R4-BUG-4: the two route outputs do NOT share one shape. The
    # table listing really prints "default via 10.9.0.1 dev tun1"
    # (kept below), but `ip route get` on a point-to-point tun prints
    # NO "via": "1.1.1.1 from 10.8.0.1 dev tun1 table 100 uid 0"
    # (live-verify-R4 §13, machine-reproduced). So the route-get
    # assertion is "dev tun1" + "table 100", never the "via ..." string.
    local expect="$1" detail=""
    if ! ip rule show >/dev/null 2>&1; then
        echo "SKIP: ip rule not permitted in this environment"; return 2
    fi
    local rule route vpn_route host_route
    rule="$(ip rule show 2>&1 | grep -c 'from 10.8.0.0/24 lookup 100' || true)"
    route="$(ip route show table 100 2>&1 | grep -c 'default via 10.9.0.1 dev tun1' || true)"
    vpn_route="$(ip route get 1.1.1.1 from 10.8.0.1 2>&1 || true)"
    host_route="$(ip route get 1.1.1.1 2>&1 || true)"
    detail="rule=$rule table100=$route | vpn: $vpn_route | host: $host_route"
    if [ "$expect" = "on" ]; then
        if [ "$rule" -ge 1 ] && [ "$route" -ge 1 ] \
            && printf '%s' "$vpn_route" | grep -q "table 100" \
            && printf '%s' "$vpn_route" | grep -q "dev tun1" \
            && ! printf '%s' "$host_route" | grep -q "table 100"; then
            echo "PASS: $detail"; return 0
        fi
        echo "FAIL: $detail"; return 1
    else
        if [ "$rule" -eq 0 ] && [ "$route" -eq 0 ]; then
            echo "PASS: $detail"; return 0
        fi
        echo "FAIL: $detail"; return 1
    fi
}

if [ "$LOGGED_IN" -eq 1 ] && [ "$STUB_UP" -eq 1 ]; then
    if [ -n "$SK5_PRIOR_HOST" ] && [ "$SK5_PRIOR_ENABLED" = "true" ] \
            && [ "${VERIFY_ALLOW_OVERWRITE_SK5:-0}" != "1" ]; then
        skip "sk5-toggle" "real SK5 already enabled ($SK5_PRIOR_HOST); toggle test skipped to avoid overwriting it (VERIFY_ALLOW_OVERWRITE_SK5=1 to force)"
        skip "sk5-egress-ip" "toggle test skipped, chain state untouched"
        skip "sk5-disable" "toggle test skipped, chain state untouched"
    else
        SK5_TOGGLE_RAN=1
        # Back up current egress state so cleanup restores it exactly.
        [ -f "$CONFIG_DIR/sk5.json" ] && { cp "$CONFIG_DIR/sk5.json" "$WORKDIR/sk5.json.bak"; SK5_JSON_BACKED_UP=1; }
        [ -f "$CONFIG_DIR/sing-box.json" ] && { cp "$CONFIG_DIR/sing-box.json" "$WORKDIR/sing-box.json.bak"; SINGBOX_JSON_BACKED_UP=1; }
        ENABLE_CODE="$(curl -ks --max-time 30 -b "$COOKIE_JAR" -o "$WORKDIR/sk5enable.json" \
            -w '%{http_code}' -X POST "$PANEL_URL/api/sk5" \
            -H 'Content-Type: application/json' \
            -d "{\"host\": \"127.0.0.1\", \"port\": $STUB_PORT, \"username\": \"\", \"password\": \"\", \"enabled\": true}" 2>/dev/null || true)"
        if [ "$ENABLE_CODE" = "200" ] && [ "$(json_get "$WORKDIR/sk5enable.json" ok)" = "true" ]; then
            SK5_TOGGLED=1
            sleep 2  # let sing-box create tun1 + policy-routing apply
            RC_OUT="$(route_checks on)"; RC=$?
            if [ "$RC" -eq 0 ]; then
                ok "sk5-toggle-on" "POST /api/sk5 enabled=true (stub 127.0.0.1:$STUB_PORT); ${RC_OUT#PASS: }"
            elif [ "$RC" -eq 2 ]; then
                skip "sk5-toggle-on" "panel enabled the chain but ${RC_OUT#SKIP: }"
            else
                bad "sk5-toggle-on" "panel said enabled but routing did not switch: ${RC_OUT#FAIL: }"
            fi
            # Cross-check with the egress lane's own verifier (while up).
            EGRESS_TEST="$INSTALL_ROOT/egress/test-egress.sh"
            [ -x "$EGRESS_TEST" ] || EGRESS_TEST="$PROJECT_DIR/egress/test-egress.sh"
            if [ -x "$EGRESS_TEST" ]; then
                if bash "$EGRESS_TEST" > "$WORKDIR/test-egress.out" 2>&1; then
                    ok "egress-crosscheck" "egress/test-egress.sh exit 0 while chain up"
                elif ! internet_ok; then
                    skip "egress-crosscheck" "test-egress.sh failed but ifconfig.me is unreachable from this host (no internet egress here); see $WORKDIR/test-egress.out"
                else
                    bad "egress-crosscheck" "egress/test-egress.sh failed; see $WORKDIR/test-egress.out"
                fi
            else
                skip "egress-crosscheck" "egress/test-egress.sh not found"
            fi
            # 10. egress IP field while the chain is up.
            # R7-P2-12: /api/status caches the sk5 snapshot for 10 s
            # (_cached_sk5_status, panel/app.py), so a read right after
            # enable can still serve the PRE-enable snapshot
            # (enabled=false, egress.ip = direct probe IP,
            # via_sk5=false). Asserting only "ip non-empty" passed
            # vacuously on that stale snapshot: with apply made a
            # no-op (T mutation) toggle-on went red while this cell
            # stayed green. Poll until the snapshot is post-enable
            # (sk5.enabled=true; at most ~15 s, one full TTL plus
            # margin), then require BOTH via_sk5=true AND a non-empty
            # egress.ip -- via_sk5 is the only honest "traffic really
            # goes via SK5" signal (U, R6-P1-1); a non-empty ip alone
            # can be the direct probe IP from the stale snapshot.
            _FRESH=0 _STATUS2_ANY=0
            for _EGRESS_POLL in $(seq 1 15); do
                if curl -ks --max-time 20 -b "$COOKIE_JAR" -o "$WORKDIR/status2.json" \
                        "$PANEL_URL/api/status" 2>/dev/null; then
                    _STATUS2_ANY=1
                    if [ "$(json_path "$WORKDIR/status2.json" sk5.enabled)" = "true" ]; then
                        _FRESH=1; break
                    fi
                fi
                sleep 1
            done
            if [ "$_FRESH" -eq 1 ]; then
                EGRESS_IP="$(json_path "$WORKDIR/status2.json" egress.ip)"
                EGRESS_VIA="$(json_path "$WORKDIR/status2.json" egress.via_sk5)"
                EGRESS_POLICY="$(json_path "$WORKDIR/status2.json" sk5.policy_routing_active)"
                if [ "$EGRESS_VIA" = "true" ] && [ -n "$EGRESS_IP" ]; then
                    ok "sk5-egress-ip" "/api/status egress.ip=$EGRESS_IP via_sk5=true while chain up (via stub)"
                elif [ "$EGRESS_VIA" = "true" ] && ! internet_ok; then
                    skip "sk5-egress-ip" "via_sk5=true but egress.ip empty and ifconfig.me unreachable from this host (stub forwards TCP, but the probe target needs internet)"
                elif [ "$EGRESS_VIA" = "true" ]; then
                    bad "sk5-egress-ip" "/api/status via_sk5=true but egress.ip empty while chain up (ifconfig.me reachable, chain probe failed?)"
                else
                    bad "sk5-egress-ip" "/api/status via_sk5=$EGRESS_VIA egress.ip=${EGRESS_IP:-<empty>} (enabled=true policy_routing_active=$EGRESS_POLICY) while chain up; chain not in effect"
                fi
            elif [ "$_STATUS2_ANY" -eq 0 ]; then
                bad "sk5-egress-ip" "GET /api/status failed while chain up"
            else
                bad "sk5-egress-ip" "GET /api/status never reported sk5.enabled=true within 15 s after a 200 enable (stale 10 s cache, or enable did not stick)"
            fi
            # 11. disable again, routing must revert.
            DISABLE_CODE="$(curl -ks --max-time 30 -b "$COOKIE_JAR" -o "$WORKDIR/sk5disable.json" \
                -w '%{http_code}' -X POST "$PANEL_URL/api/sk5" \
                -H 'Content-Type: application/json' \
                -d "{\"host\": \"127.0.0.1\", \"port\": $STUB_PORT, \"username\": \"\", \"password\": \"\", \"enabled\": false}" 2>/dev/null || true)"
            if [ "$DISABLE_CODE" = "200" ] && [ "$(json_get "$WORKDIR/sk5disable.json" ok)" = "true" ]; then
                sleep 1
                RC_OUT="$(route_checks off)"; RC=$?
                if [ "$RC" -eq 0 ]; then
                    ok "sk5-disable" "POST /api/sk5 enabled=false; ${RC_OUT#PASS: }"
                elif [ "$RC" -eq 2 ]; then
                    skip "sk5-disable" "panel disabled the chain but ${RC_OUT#SKIP: }"
                else
                    bad "sk5-disable" "panel said disabled but routing did not revert: ${RC_OUT#FAIL: }"
                fi
                SK5_TOGGLED=0  # already disabled; cleanup must not re-disable
            else
                bad "sk5-disable" "POST /api/sk5 enabled=false -> HTTP $DISABLE_CODE body: $(head -c 300 "$WORKDIR/sk5disable.json" 2>/dev/null)"
            fi
        else
            bad "sk5-toggle-on" "POST /api/sk5 enabled=true -> HTTP $ENABLE_CODE body: $(head -c 300 "$WORKDIR/sk5enable.json" 2>/dev/null)"
            skip "sk5-egress-ip" "chain never came up"
            skip "sk5-disable" "chain never came up"
            skip "egress-crosscheck" "chain never came up"
        fi
    fi
else
    skip "sk5-toggle-on" "not logged in or stub down"
    skip "sk5-egress-ip" "not logged in or stub down"
    skip "sk5-disable" "not logged in or stub down"
    skip "egress-crosscheck" "not logged in or stub down"
fi

# ---------------------------------------------------------------- forwarding (BUG-8, mode-aware)
# VPN user traffic enters via tun0 and needs the install.sh FORWARD
# accepts (tun0 -> WAN + return ESTABLISHED) in both modes. A host
# with FORWARD policy DROP and no rules passes every service check
# while dropping all user traffic, so verify the rules and the kernel
# route lookup. R4-BUG-3: the route expectation is MODE-AWARE (mirror
# of install.sh's R2-BUG-15 gate). The old unconditional "must resolve
# via $FWD_WAN" assertion failed by construction whenever SK5 was on
# (live-verify-R4 §12: the VPN source is SUPPOSED to resolve via
# tun1/table 100 then) -- and it contradicted this script's own
# "protect the real SK5" skip of the toggle tests, which leaves the
# chain up. Mode is read live from GET /api/sk5 at cell time, not
# from the pre-toggle snapshot, because §9-11 may have changed it.
if [ "$LOGGED_IN" -eq 1 ] && [ "$OVPN_RUNNING" -eq 1 ]; then
    FWD_WAN="$(ip route show default 2>/dev/null | awk '/default/ {print $5; exit}')"
    if [ -z "$FWD_WAN" ]; then
        skip "direct-forwarding" "no default route on this host, cannot check the forwarding path"
    elif ! iptables -C FORWARD -i tun0 -s 10.8.0.0/24 -o "$FWD_WAN" -j ACCEPT 2>/dev/null; then
        # iptables -C failing can mean "no permission" in a sandbox as
        # well as "rule absent"; distinguish by testing -L readability.
        if ! iptables -L FORWARD >/dev/null 2>&1; then
            skip "direct-forwarding" "iptables not readable in this environment (sandbox?)"
        else
            bad "direct-forwarding" "FORWARD accept tun0 10.8.0.0/24 -> $FWD_WAN missing (BUG-8: VPN users dropped if FORWARD policy is DROP)"
        fi
    elif ! iptables -C FORWARD -i "$FWD_WAN" -d 10.8.0.0/24 -o tun0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null; then
        bad "direct-forwarding" "FORWARD return rule $FWD_WAN -> tun0 10.8.0.0/24 missing"
    else
        FWD_ROUTE="$(ip route get 1.1.1.1 from 10.8.0.1 2>&1 || true)"
        SK5_MODE=""
        if curl -ks --max-time 10 -b "$COOKIE_JAR" -o "$WORKDIR/sk5mode.json" \
                "$PANEL_URL/api/sk5" 2>/dev/null; then
            SK5_MODE="$(json_path "$WORKDIR/sk5mode.json" sk5.enabled 2>/dev/null || true)"
        fi
        if [ "$SK5_MODE" = "true" ]; then
            # SK5 on: VPN source must resolve via table 100 (dev tun1);
            # same expectation as route_checks on (R4-BUG-4: no "via"
            # in a point-to-point tun route-get).
            if printf '%s' "$FWD_ROUTE" | grep -q "dev tun1" && printf '%s' "$FWD_ROUTE" | grep -q "table 100"; then
                ok "direct-forwarding" "FORWARD rules present; SK5 enabled: VPN source 10.8.0.1 routes via table 100 ($FWD_ROUTE)"
            else
                bad "direct-forwarding" "FORWARD rules present but SK5 enabled and VPN source route lookup wrong: $FWD_ROUTE"
            fi
        elif [ "$SK5_MODE" = "false" ]; then
            if printf '%s' "$FWD_ROUTE" | grep -q "dev $FWD_WAN" && ! printf '%s' "$FWD_ROUTE" | grep -q "table 100"; then
                ok "direct-forwarding" "FORWARD rules present; VPN source 10.8.0.1 routes via $FWD_WAN ($FWD_ROUTE)"
            else
                bad "direct-forwarding" "FORWARD rules present but VPN source route lookup wrong: $FWD_ROUTE"
            fi
        else
            skip "direct-forwarding" "FORWARD rules present but SK5 mode unknown (GET /api/sk5 failed); cannot tell which route expectation applies"
        fi
    fi
else
    skip "direct-forwarding" "not logged in or openvpn not running"
fi

# ---------------------------------------------------------------- 12. sk5 enable endpoint
# AUDIT-R1 proved the old "known defect" wrong: panel/app.py
# /api/sk5/enable correctly calls the imported sk5_enable_fn (the
# "sk5_set_enabled is not defined" claim was a misread). The endpoint
# must return 200. It is only probed when the toggle test ran (no real
# merchant SK5 configured), so it never touches production state; on
# success the chain is left enabled and cleanup disables it again.
if [ "$LOGGED_IN" -eq 1 ] && [ "$SK5_TOGGLE_RAN" -eq 1 ]; then
    EN_CODE="$(curl -ks --max-time 30 -b "$COOKIE_JAR" -o "$WORKDIR/sk5enable-ep.json" \
        -w '%{http_code}' -X POST "$PANEL_URL/api/sk5/enable" 2>/dev/null || true)"
    if [ "$EN_CODE" = "200" ] && [ "$(json_get "$WORKDIR/sk5enable-ep.json" ok)" = "true" ]; then
        SK5_TOGGLED=1  # cleanup disables the chain again
        ok "sk5-enable-endpoint" "POST /api/sk5/enable -> 200 (chain re-enabled; cleanup will disable it)"
    elif ! command -v sing-box >/dev/null 2>&1; then
        skip "sk5-enable-endpoint" "POST /api/sk5/enable -> HTTP $EN_CODE but no sing-box binary on this host (enable cannot run here)"
    else
        bad "sk5-enable-endpoint" "POST /api/sk5/enable -> HTTP $EN_CODE body: $(head -c 300 "$WORKDIR/sk5enable-ep.json" 2>/dev/null)"
    fi
else
    skip "sk5-enable-endpoint" "toggle test did not run (real SK5 may be configured); enable probe skipped to avoid touching production state"
fi

# ---------------------------------------------------------------- summary
echo
echo "result: PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
if [ "$FAIL" -eq 0 ]; then
    echo "VERIFY: ALL GREEN"
    exit 0
else
    echo "VERIFY: $FAIL CHECK(S) FAILED (see [FAIL] lines above)"
    exit "$FAIL"
fi

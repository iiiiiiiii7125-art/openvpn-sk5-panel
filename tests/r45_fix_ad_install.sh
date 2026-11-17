#!/usr/bin/env bash
# R45-LIVE-2 agent-delivery probe -- installer half (r45_fix_ad.py is
# the Flask half, r45_fix_ad_worker.mjs the Worker half).
#
# Finding: the R45-L6-3 fix never reached the RUNNING agent -- the
# panel bundle already carried the fixed policy-routing.sh, but
# install-agent.sh is the only delivery path and nothing recorded
# which bundle an agent was installed from, so nothing could flag it
# stale. Fix: the download branch records the verified bundle hash
# at <install-root>/bundle.sha256 (the agent reports it in its poll
# heartbeat); the local-checkout branch removes any stale record so
# the agent reports unknown instead of a hash that no longer
# describes its code.
#
# Method: a fake panel (127.0.0.1) serves the REAL bundle + sha256
# built by this tree's own panel code plus install-agent.sh.sha256;
# install-agent.sh runs against a pre-seeded STALE agent root
# (Nov 13 policy-routing.sh: unanchored rule_exists, STALE marker).
# The installer runs inside `unshare -rm` with /etc/systemd/system
# and /etc/ovpn-agent bind-mounted onto scratch dirs, so the host
# /etc is never written; systemctl/apt-get are PATH stubs (exit 0).
# The driver creates /etc/ovpn-agent (mount point) and removes it
# again in the trap -- the host ends with no trace of the run.
#
# Run as root: bash <tree>/tests/r45_fix_ad_install.sh
# Exit = FAIL count. On the 6eac5af baseline D2/D4/L2 fail (no hash
# record, heartbeat reports None, stale hash not removed); D1/D3/D5/
# L1/L3 pass on both (the refresh itself already worked -- the defect
# is the missing staleness record, not the copy).
set -u
TREE="$(cd "$(dirname "$0")/.." && pwd)"
VENV=/tmp/r41-l5-venv
FAIL=0
check() { # name cond [detail]
  if [ "$2" = 0 ]; then echo "PASS $1"; else echo "FAIL $1${3:+ | $3}"; FAIL=$((FAIL+1)); fi
}
S="$(mktemp -d /tmp/r45-fix-ad.XXXXXX)"
PANEL_PID=""
CREATED_OVPN_AGENT_DIR=0
cleanup() {
  [ -n "$PANEL_PID" ] && kill "$PANEL_PID" 2>/dev/null
  [ "$CREATED_OVPN_AGENT_DIR" = 1 ] && rmdir /etc/ovpn-agent 2>/dev/null
  rm -rf "$S"
}
trap cleanup EXIT

[ -x "$VENV/bin/python3" ] || { echo "FAIL prerequisite: $VENV missing (rebuild it)"; exit 2; }
[ -d /tmp/r17/fixture-ca ] && [ -d /tmp/r17/fixture-server ] \
  || { echo "FAIL prerequisite: /tmp/r17 fixtures missing (rebuild them)"; exit 2; }

mkdir -p "$S/data" "$S/sk5cfg" "$S/fake-systemd" "$S/fake-ovpn-agent" \
  "$S/stubs" "$S/agent-root/egress" "$S/agent-root2/egress"
[ -d /etc/ovpn-agent ] || { mkdir -p /etc/ovpn-agent; CREATED_OVPN_AGENT_DIR=1; }

# --- build the REAL bundle with this tree's own panel code -------------
cat > "$S/build_bundle.py" <<'PYEOF'
import os, sys
sys.path.insert(0, os.path.join(os.environ["TREE"], "panel"))
sys.path.insert(0, os.path.join(os.environ["TREE"], "core"))
sys.path.insert(0, os.path.join(os.environ["TREE"], "egress"))
import app as panel
c = panel.app.test_client()
r = c.get("/api/agent/bundle.sha256")
assert r.status_code == 200, r.status_code
open(os.environ["SHA_OUT"], "w").write(r.get_data(as_text=True))
r = c.get("/api/agent/bundle")
assert r.status_code == 200, r.status_code
open(os.environ["BUNDLE_OUT"], "wb").write(r.get_data())
print("BUNDLE_HASH=" + open(os.environ["SHA_OUT"]).read().split()[0])
PYEOF
BUNDLE_HASH="$(TREE="$TREE" SHA_OUT="$S/bundle.sha256.txt" BUNDLE_OUT="$S/bundle.tar.gz" \
  PYTHONPATH="$VENV/lib/python3.12/site-packages" \
  OVPN_PANEL_DATA_DIR="$S/data" OVPN_PANEL_SECRET_PATH="$S/data/secret.key" \
  OPENVPN_CA_DIR=/tmp/r17/fixture-ca OPENVPN_SERVER_DIR=/tmp/r17/fixture-server \
  OVPN_SK5_CONFIG_DIR="$S/sk5cfg" \
  "$VENV/bin/python3" "$S/build_bundle.py" | sed -n 's/^BUNDLE_HASH=//p')"
[ "${#BUNDLE_HASH}" = 64 ] || { echo "FAIL bundle build: hash='$BUNDLE_HASH'"; exit 2; }
echo "bundle hash: $BUNDLE_HASH"
(cd "$TREE/agent" && sha256sum install-agent.sh > "$S/install-agent.sh.sha256")

# --- fake panel: serves the real bundle + hashes ------------------------
cat > "$S/fake_panel.py" <<'PYEOF'
import http.server, os
SHA = open(os.environ["SHA_FILE"], "rb").read()
ISHA = open(os.environ["ISHA_FILE"], "rb").read()
BUNDLE = open(os.environ["BUNDLE_FILE"], "rb").read()
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/install-agent.sh.sha256":
            body, ctype = ISHA, "text/plain"
        elif self.path == "/api/agent/bundle.sha256":
            body, ctype = SHA, "text/plain"
        elif self.path == "/api/agent/bundle":
            body, ctype = BUNDLE, "application/gzip"
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
print("PORT=%d" % srv.server_address[1], flush=True)
srv.serve_forever()
PYEOF
SHA_FILE="$S/bundle.sha256.txt" ISHA_FILE="$S/install-agent.sh.sha256" \
  BUNDLE_FILE="$S/bundle.tar.gz" python3 "$S/fake_panel.py" > "$S/panel.log" 2>&1 &
PANEL_PID=$!
for _ in $(seq 1 50); do grep -q '^PORT=' "$S/panel.log" 2>/dev/null && break; sleep 0.1; done
PORT="$(sed -n 's/^PORT=//p' "$S/panel.log" | head -1)"
[ -n "$PORT" ] || { echo "FAIL fake panel did not start"; cat "$S/panel.log"; exit 2; }
PANEL_URL="http://127.0.0.1:$PORT"
echo "fake panel: $PANEL_URL (pid $PANEL_PID)"

# --- stubs: systemctl + apt-get (exit 0, log invocations) ---------------
printf '#!/bin/sh\necho "systemctl $@" >> "$S/stub.log"\nexit 0\n' > "$S/stubs/systemctl"
printf '#!/bin/sh\necho "apt-get $@" >> "$S/stub.log"\nexit 0\n' > "$S/stubs/apt-get"
chmod +x "$S/stubs/systemctl" "$S/stubs/apt-get"

# --- stale agent root: Nov 13 policy-routing.sh (unanchored
# rule_exists, STALE marker) built from the tree's current file ------
cat > "$S/make_stale.py" <<'PYEOF'
import os, sys
text = open(os.path.join(os.environ["TREE"], "egress/policy-routing.sh")).read()
new = '    ip rule show 2>/dev/null | grep -E "^$RULE_PRIO:.*from $VPN_NET lookup $TABLE([^0-9]|$)" >/dev/null'
old = '    ip rule show 2>/dev/null | grep -E "^$RULE_PRIO:.*from $VPN_NET lookup $TABLE" >/dev/null'
assert text.count(new) == 1, "anchored rule_exists line not found exactly once"
stale = "# STALE-NOV13: pre-R45-L6-3 copy (unanchored rule_exists)\n" + text.replace(new, old)
open(os.environ["OUT"], "w").write(stale)
PYEOF
TREE="$TREE" OUT="$S/agent-root/egress/policy-routing.sh" python3 "$S/make_stale.py"
TREE="$TREE" OUT="$S/agent-root2/egress/policy-routing.sh" python3 "$S/make_stale.py"
# agent-root2 also carries a stale hash record (pre-fix agents have
# none; a wrong record must be removed, never kept).
printf '%s\n' "$(printf 'f%.0s' $(seq 1 64))" > "$S/agent-root2/bundle.sha256"

ANCHORED='grep -E "^$RULE_PRIO:.*from $VPN_NET lookup $TABLE([^0-9]|$)"'
hb_hash() { # $1 = install root -> bundle_sha256 reported by the agent
  ROOT="$1" python3 - "$1" <<'PYEOF'
import importlib.util, sys
root = sys.argv[1]
spec = importlib.util.spec_from_file_location(
    "installed_agent", root + "/agent/agent.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod.heartbeat_status().get("bundle_sha256"))
PYEOF
}

run_installer() { # $1 = script path, $2 = install root, $3 = token, $4 = node
  env S="$S" TREE="$TREE" PORT="$PORT" SCRIPT="$1" ROOT="$2" TOKEN="$3" NODE="$4" \
    unshare -rm bash -c '
      set -e
      mount --bind "$S/fake-systemd" /etc/systemd/system
      mount --bind "$S/fake-ovpn-agent" /etc/ovpn-agent
      export PATH="$S/stubs:$PATH"
      bash "$SCRIPT" --panel-url "http://127.0.0.1:$PORT" \
        --token "$TOKEN" --node-name "$NODE" --install-root "$ROOT" --force'
}

# --- D: download branch (fake panel) ------------------------------------
# The installer takes the download branch ONLY when no agent.py +
# core/ sit next to it (as in real use: the operator curls the script
# to /tmp and runs it there). Running $TREE/agent/install-agent.sh
# directly would take the local-checkout branch instead, so the D
# runs use a /tmp copy of the identical script (same sha256 the fake
# panel serves for the self-check).
mkdir -p "$S/dl"
cp "$TREE/agent/install-agent.sh" "$S/dl/install-agent.sh"
run_installer "$S/dl/install-agent.sh" "$S/agent-root" test-token-123 adnode \
  > "$S/d1.log" 2>&1
check "D1 download-branch install exit 0" $? "$(tail -2 "$S/d1.log")"
RECORDED="$(cat "$S/agent-root/bundle.sha256" 2>/dev/null)"
check "D2 bundle.sha256 recorded == served hash" \
  "$([ "$RECORDED" = "$BUNDLE_HASH" ] && echo 0 || echo 1)" "recorded=$RECORDED"
grep -Fq "$ANCHORED" "$S/agent-root/egress/policy-routing.sh" 2>/dev/null; a=$?
! grep -q "STALE-NOV13" "$S/agent-root/egress/policy-routing.sh" 2>/dev/null; b=$?
check "D3 stale policy-routing.sh refreshed (anchored, marker gone)" \
  "$([ "$a" = 0 ] && [ "$b" = 0 ] && echo 0 || echo 1)"
HB="$(hb_hash "$S/agent-root" 2>"$S/d4.err")"
check "D4 installed agent heartbeat reports the served hash" \
  "$([ "$HB" = "$BUNDLE_HASH" ] && echo 0 || echo 1)" "heartbeat=$HB $(head -1 "$S/d4.err")"
run_installer "$S/dl/install-agent.sh" "$S/agent-root" test-token-123 adnode \
  > "$S/d5.log" 2>&1
check "D5 control: re-run --force exit 0" $?
RECORDED2="$(cat "$S/agent-root/bundle.sha256" 2>/dev/null)"
check "D5b control: hash still correct after re-run" \
  "$([ "$RECORDED2" = "$BUNDLE_HASH" ] && echo 0 || echo 1)"

# --- L: local-checkout branch (no bundle exists) ------------------------
mkdir -p "$S/checkout"
cp -r "$TREE/agent" "$TREE/core" "$TREE/egress" "$S/checkout/"
run_installer "$S/checkout/agent/install-agent.sh" "$S/agent-root2" test-token-456 adnode2 \
  > "$S/l1.log" 2>&1
check "L1 local-checkout install exit 0" $? "$(tail -2 "$S/l1.log")"
check "L2 stale bundle.sha256 removed by local install" \
  "$([ ! -e "$S/agent-root2/bundle.sha256" ] && echo 0 || echo 1)"
grep -Fq "$ANCHORED" "$S/agent-root2/egress/policy-routing.sh" 2>/dev/null; a=$?
! grep -q "STALE-NOV13" "$S/agent-root2/egress/policy-routing.sh" 2>/dev/null; b=$?
check "L3 local install refreshed policy-routing.sh" \
  "$([ "$a" = 0 ] && [ "$b" = 0 ] && echo 0 || echo 1)"
HB2="$(hb_hash "$S/agent-root2" 2>"$S/l4.err")"
check "L4 agent heartbeat reports None (unknown) after local install" \
  "$([ "$HB2" = "None" ] && echo 0 || echo 1)" "heartbeat=$HB2 $(head -1 "$S/l4.err")"

# --- host hygiene: the run must leave no trace on the host /etc --------
check "H1 host /etc/openvpn-sk5-panel absent" \
  "$([ ! -e /etc/openvpn-sk5-panel ] && echo 0 || echo 1)"
check "H2 host /etc/sysctl.d/99-openvpn-sk5.conf absent" \
  "$([ ! -e /etc/sysctl.d/99-openvpn-sk5.conf ] && echo 0 || echo 1)"
check "H3 host /run/openvpn-sk5-panel/policy-routing.lock absent" \
  "$([ ! -e /run/openvpn-sk5-panel/policy-routing.lock ] && echo 0 || echo 1)"

echo "----"
echo "failures=$FAIL"
exit "$FAIL"

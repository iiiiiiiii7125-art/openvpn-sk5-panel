#!/usr/bin/env bash
# R41 Fix-C netns probe: policy routing + test-egress.sh, end to end
# in a real userns+netns (L4's method: unshare --user --map-root-user
# --net --mount, veth pairs stand in for tun0/tun1).
#
# Scenarios (all inside one fresh netns):
#   S1 (P2-1, L4 E2 N7): rules `from 10.8.0.0/24 lookup 200` +
#      `from 192.168.0.0/24 lookup 100`, live table-100 tun1 route.
#      _rule_present()/_policy_active() must be False while the
#      ground-truth route-get from 10.8.0.1 takes the main table.
#   S2 (P2-2, L4 E2 N8): real rule + table-100 route via a DEAD
#      tun1 (peer down -> linkdown). test-egress.sh §2 and §3 must
#      FAIL; before the fix both PASSED on the dead chain.
#   S3 (P2-3, L4 E10): healthy chain, direct leg dead, SK5 leg
#      alive (stub curl). §6 must FAIL blaming the DIRECT leg, not
#      the SK5 leg.
#   S4 (control): healthy chain, both legs alive with different
#      IPs. §2/§3/§6 must PASS (no regression).
#
# Usage: tests/r41_fix_c_netns.sh <test-egress.sh> <sk5_manager.py>
# Exit 0 iff every expectation holds. The stub curl + fake sk5.json
# live under a scratch dir; /etc/openvpn-sk5-panel is bind-mounted
# (mountpoint pre-created on the host, removed at the end).
set -u

EGRESS_SH="${1:?usage: $0 <test-egress.sh> <sk5_manager.py>}"
MOD="${2:?usage: $0 <test-egress.sh> <sk5_manager.py>}"

if [ -z "${IN_NS:-}" ]; then
    mkdir -p /etc/openvpn-sk5-panel
    unshare --user --map-root-user --net --mount env IN_NS=1 "$0" "$EGRESS_SH" "$MOD"
    RC=$?
    rmdir /etc/openvpn-sk5-panel 2>/dev/null || true
    exit "$RC"
fi

FAIL=0
expect() { # expect <name> <got> <want-substring>
    if printf '%s' "$2" | grep -qF "$3"; then
        echo "PASS: $1"
    else
        FAIL=$((FAIL+1)); echo "FAIL: $1 (got: $(printf '%s' "$2" | head -c 200))"
    fi
}

S="$(mktemp -d /tmp/r41c-ns-XXXXXX)"
mkdir -p "$S/bin" "$S/cfg" "$S/mod"
cp "$MOD" "$S/mod/sk5_manager.py"

cat > "$S/bin/curl" <<'EOF'
#!/bin/sh
# Stub curl: direct call -> $STUB_DIRECT, --socks5-hostname -> $STUB_SK5.
# Empty value = unreachable (exit 7, no output).
for a in "$@"; do
  if [ "$a" = "--socks5-hostname" ]; then
    if [ -n "${STUB_SK5:-}" ]; then printf '%s\n' "$STUB_SK5"; exit 0; else exit 7; fi
  fi
done
if [ -n "${STUB_DIRECT:-}" ]; then printf '%s\n' "$STUB_DIRECT"; exit 0; else exit 7; fi
EOF
chmod +x "$S/bin/curl"
export PATH="$S/bin:$PATH"

printf '%s\n' '{"host": "proxy.example.net", "port": 1001, "username": "", "password": ""}' > "$S/cfg/sk5.json"
mount --bind "$S/cfg" /etc/openvpn-sk5-panel

ip link set lo up
ip link add eth0 type veth peer name eth0p
ip link set eth0 up; ip link set eth0p up
ip addr add 192.168.0.2/24 dev eth0
ip route add default via 192.168.0.1 dev eth0
ip link add tun0 type veth peer name tun0p
ip link set tun0 up; ip link set tun0p up
ip addr add 10.8.0.1/24 dev tun0
ip link add tun1 type veth peer name tun1p
ip link set tun1 up; ip link set tun1p up
ip addr add 10.9.0.1/30 dev tun1

run_script() { # run_script <out-file> <stub-direct> <stub-sk5>
    STUB_DIRECT="$2" STUB_SK5="$3" bash "$EGRESS_SH" >"$1" 2>&1
    SCRIPT_RC=$?
    echo "script-exit=$SCRIPT_RC"
}

echo "=== S1: N7 cross-line rules (P2-1) ==="
ip rule add from 10.8.0.0/24 lookup 200 prio 200
ip rule add from 192.168.0.0/24 lookup 100 prio 150
ip route add default via 10.9.0.1 dev tun1 table 100
GOT="$(PYTHONPATH="$S/mod" python3 -c "import sk5_manager as sm; print('rule_present=%s policy_active=%s' % (sm._rule_present(), sm._policy_active({'enabled': True})))")"
echo "$GOT"
expect "S1 rule_present=False" "$GOT" "rule_present=False"
expect "S1 policy_active=False" "$GOT" "policy_active=False"
GOT="$(ip route get 1.1.1.1 from 10.8.0.1)"
echo "ground truth: $GOT"
expect "S1 route-get takes main" "$GOT" "via 192.168.0.1 dev eth0"
ip rule del from 10.8.0.0/24 lookup 200 prio 200
ip rule del from 192.168.0.0/24 lookup 100 prio 150
ip route del default via 10.9.0.1 dev tun1 table 100

echo "=== S2: linkdown route (P2-2) ==="
ip rule add from 10.8.0.0/24 lookup 100 prio 100
ip route add default via 10.9.0.1 dev tun1 table 100
ip link set tun1p down
echo "table 100: $(ip route show table 100)"
run_script "$S/s2.out" "" "203.0.113.7"

expect "S2 §2 FAILs on linkdown" "$(grep -E '^(PASS|FAIL):' "$S/s2.out" | sed -n '2p')" "FAIL: table 100 has no live"
expect "S2 §3 FAILs on linkdown" "$(grep 'linkdown (dead tun1' "$S/s2.out")" "FAIL: VPN source takes table 100 via dev tun1 but the route is linkdown"
ip link set tun1p up
ip rule del from 10.8.0.0/24 lookup 100 prio 100
ip route del default via 10.9.0.1 dev tun1 table 100

echo "=== S3: healthy chain, direct leg dead (P2-3) ==="
ip rule add from 10.8.0.0/24 lookup 100 prio 100
ip route add default via 10.9.0.1 dev tun1 table 100
echo "table 100: $(ip route show table 100)"
run_script "$S/s3.out" "" "203.0.113.7"

expect "S3 §2 PASSes live route" "$(grep -E '^(PASS|FAIL):' "$S/s3.out" | sed -n '2p')" "PASS: table 100:"
expect "S3 §3 PASSes live route" "$(grep -E '^(PASS|FAIL):' "$S/s3.out" | sed -n '3p')" "PASS: VPN source takes table 100 via dev tun1"
expect "S3 §6 blames direct leg" "$(grep 'DIRECT egress IP' "$S/s3.out")" "FAIL: could not fetch DIRECT egress IP (direct leg unreachable); SK5 leg is alive (203.0.113.7 via proxy.example.net:1001)"

echo "=== S4: healthy chain, both legs alive (control) ==="
run_script "$S/s4.out" "198.51.100.1" "203.0.113.7"

expect "S4 §2 PASSes" "$(grep -E '^(PASS|FAIL):' "$S/s4.out" | sed -n '2p')" "PASS: table 100:"
expect "S4 §3 PASSes" "$(grep -E '^(PASS|FAIL):' "$S/s4.out" | sed -n '3p')" "PASS: VPN source takes table 100 via dev tun1"
expect "S4 §6 PASSes (differs)" "$(grep 'egress via SK5' "$S/s4.out")" "PASS: egress via SK5 (203.0.113.7) differs from direct (198.51.100.1)"

ip rule del from 10.8.0.0/24 lookup 100 prio 100
ip route del default via 10.9.0.1 dev tun1 table 100
rm -rf "$S"
echo "result: FAIL=$FAIL"
[ "$FAIL" -eq 0 ]

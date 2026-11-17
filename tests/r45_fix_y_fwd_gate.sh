#!/usr/bin/env bash
# r45_fix_y_fwd_gate.sh -- Fix-Y probe for R45-L4-3: install.sh's
# mode-aware forwarding gate must die NAMING the unreadable sk5.json
# (fail-closed), never silently default to direct mode.
#
# Extracts the gate snippet by MARKERS from install.sh (not fixed
# line numbers -- the fix itself moves lines): from the FWD_ROUTE
# assignment through the closing `fi` of the mode if/else (3 lines
# past the "unexpectedly hits table 100 in direct mode" die). Runs
# it in a userns+netns with real `ip rule`/`ip route` state (veth
# pair; route-get shape matches R4-BUG-4: no "via" on a
# point-to-point tun route-get).
# G1 corrupt sk5.json + real table-100 route -> die naming sk5.json
# G2 valid enabled sk5.json + table-100 route -> pass
# G3 valid disabled sk5.json + direct route -> pass
# G4 no sk5.json at all + direct route -> pass
# G5 corrupt sk5.json + direct route -> die naming sk5.json
#     (fail-closed even when the route would pass the direct checks)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TDIR="$(mktemp -d /tmp/r45y-fwdgate.XXXXXX)"
START="$(grep -n 'FWD_ROUTE="$(ip route get 1.1.1.1 from 10.8.0.1' "$ROOT/install.sh" | cut -d: -f1 | head -1)"
HIT="$(grep -n 'unexpectedly hits table 100 in direct mode' "$ROOT/install.sh" | cut -d: -f1 | head -1)"
[ -n "$START" ] && [ -n "$HIT" ] || { echo "FAIL extract: gate markers not found"; exit 1; }
END=$((HIT + 3))
sed -n "${START},${END}p" "$ROOT/install.sh" > "$TDIR/gate.snippet"
grep -q 'FWD_ROUTE=' "$TDIR/gate.snippet" || { echo "FAIL extract: gate snippet not found"; exit 1; }
grep -q '_SK5_ON' "$TDIR/gate.snippet" || { echo "FAIL extract: mode detection missing from snippet"; exit 1; }

cat > "$TDIR/inner.sh" <<'INNER'
#!/usr/bin/env bash
set -uo pipefail
SNIP="$1"; CFG="$2"
TDIR="$(dirname "$SNIP")"
WORKDIR="$TDIR/work"; mkdir -p "$WORKDIR"
log() { echo "LOG: $*"; }
die() { echo "DIE: $*"; exit 1; }
WAN_IF="veth1"
OVPN_SUBNET="10.8.0.0/24"
CONFIG_DIR="$CFG"

# --- netns routing: VPN source via table 100, host via main ---
ip link add veth0 type veth peer name veth1
ip addr add 10.8.0.1/24 dev veth0
ip link set veth0 up; ip link set veth1 up
ip addr add 192.0.2.1/24 dev veth1
ip route add default via 192.0.2.254 dev veth1 2>/dev/null || ip route add default dev veth1
ip rule add from 10.8.0.0/24 lookup 100 priority 100
ip route add default via 10.8.0.1 dev veth0 table 100

run_gate() { # run_gate <label>
    local label="$1" out rc
    out="$( ( . "$SNIP" ) 2>&1 )"; rc=$?
    printf '%s rc=%s out=%s\n' "$label" "$rc" "$out"
}

# G1: corrupt sk5.json + real table-100 route.
printf '{"enabled": true' > "$CONFIG_DIR/sk5.json"
run_gate "G1-corrupt-sk5-table100" | tee "$TDIR/g1.out"
# G2 (control): valid enabled sk5.json + table-100 route -> must pass.
printf '{"enabled": true}' > "$CONFIG_DIR/sk5.json"
run_gate "G2-valid-enabled-table100" | tee "$TDIR/g2.out"

# Drop the SK5 routing: now the VPN source resolves via the main table.
ip rule del from 10.8.0.0/24 lookup 100 priority 100
ip route flush table 100
# G3 (control): valid disabled sk5.json + direct route -> must pass.
printf '{"enabled": false}' > "$CONFIG_DIR/sk5.json"
run_gate "G3-valid-disabled-direct" | tee "$TDIR/g3.out"
# G4 (control): no sk5.json at all + direct route -> must pass.
rm -f "$CONFIG_DIR/sk5.json"
run_gate "G4-no-sk5-direct" | tee "$TDIR/g4.out"
# G5: corrupt sk5.json + direct route -> must still die naming the file.
printf '{"enabled": true' > "$CONFIG_DIR/sk5.json"
run_gate "G5-corrupt-sk5-direct" | tee "$TDIR/g5.out"
INNER
chmod +x "$TDIR/inner.sh"

mkdir -p "$TDIR/config"
unshare --user --map-root-user --net --mount "$TDIR/inner.sh" "$TDIR/gate.snippet" "$TDIR/config" || echo "WARN: inner netns run rc=$?"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "PASS $1"; }
bad()  { FAIL=$((FAIL+1)); echo "FAIL $1"; }

# G1/G5: must die (rc=1) AND name the sk5.json file; must NOT contain
# a direct-mode assertion. Match only the gate output after "out=".
for g in g1 g5; do
    OUT="$(sed 's/^.* out=//' "$TDIR/$g.out")"
    case "$g" in
        g1) LABEL="G1-corrupt-sk5-table100" ;;
        g5) LABEL="G5-corrupt-sk5-direct" ;;
    esac
    if grep -q "$LABEL rc=1" "$TDIR/$g.out" \
        && printf '%s' "$OUT" | grep -q "sk5.json" \
        && ! printf '%s' "$OUT" | grep -q "does not resolve via\|unexpectedly hits table 100"; then
        ok "$LABEL (dies naming sk5.json)"
    else
        bad "$LABEL (expected rc=1 naming sk5.json, got '$OUT')"
    fi
done
grep -q "G2-valid-enabled-table100 rc=0" "$TDIR/g2.out" \
    && ok "G2-valid-enabled-table100" || bad "G2-valid-enabled-table100"
grep -q "G3-valid-disabled-direct rc=0" "$TDIR/g3.out" \
    && ok "G3-valid-disabled-direct" || bad "G3-valid-disabled-direct"
grep -q "G4-no-sk5-direct rc=0" "$TDIR/g4.out" \
    && ok "G4-no-sk5-direct" || bad "G4-no-sk5-direct"

echo "R45FIXY-FWDGATE TOTAL: PASS=$PASS FAIL=$FAIL"
rm -rf "$TDIR"
[ "$FAIL" -eq 0 ]

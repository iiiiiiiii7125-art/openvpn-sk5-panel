#!/usr/bin/env bash
# Verify the OpenVPN -> SK5 egress chain PER SOURCE ADDRESS.
#
# A plain `curl ifconfig.me` proves nothing here: it takes the host's
# default source and the main table, while VPN users take 10.8.0.x and
# table 100. So every check below is pinned to a source:
#   * `ip route get 1.1.1.1 from 10.8.0.1`  -- which table/gateway does
#     a VPN user take? 10.8.0.1 is the server's own tun0 address; it
#     sits in the same 10.8.0.0/24 as VPN users, so the policy rule
#     `from 10.8.0.0/24 lookup 100` matches it. A client address such
#     as 10.8.0.2 must NOT be used here: it is not a local address and
#     the kernel refuses the lookup (RTNETLINK: Network is
#     unreachable) even when the chain is healthy (R3-BUG-4).
#     (must be table 100, dev tun1 -- the kernel prints NO "via"
#     for a point-to-point tun route-get: "1.1.1.1 from 10.8.0.1
#     dev tun1 table 100 uid 0"; "via 10.9.0.1" appears only in
#     `ip route show table 100` listings, see §2 below. R4-BUG-4.)
#   * `ip route get 1.1.1.1`                -- host direct, for contrast
#     (must stay in main; sing-box's own SK5 connection uses this)
#   * curl --socks5-hostname via the stored SK5 -- egress IP the world
#     sees for VPN users (must differ from the host direct IP -- but
#     ONLY when the SK5 endpoint is a different host; a loopback
#     endpoint is this host itself, so §6 SKIPPs the difference
#     assertion there instead of failing by construction, R5-BUG-1)
#   * curl --interface 10.9.0.2 is attempted only if that address is
#     actually assigned on this host; 10.9.0.2 is the *peer* end of
#     sing-box's tun1 (10.9.0.1/30) and is normally NOT a local
#     address, so a failure there is reported as SKIP, not FAIL --
#     the authoritative per-source proof is the `from 10.8.0.1`
#     route-get plus the SOCKS5 curl above.
#
# Usage: ./test-egress.sh
# Exit 0 only if every non-skipped check passes. Prints the triple
# (table / gateway / egress IP) at the end. Never prints the SK5
# password (config is read with python3, secret field dropped).
set -uo pipefail

CFG="/etc/openvpn-sk5-panel/sk5.json"
PASS=0; FAIL=0; SKIP=0

ok()   { PASS=$((PASS+1)); echo "PASS: $*"; }
bad()  { FAIL=$((FAIL+1)); echo "FAIL: $*"; }
skip() { SKIP=$((SKIP+1)); echo "SKIP: $*"; }

echo "=== 1. policy rule (from 10.8.0.0/24 lookup 100) ==="
if ip rule show | grep -q "from 10.8.0.0/24 lookup 100"; then
    ok "rule present: $(ip rule show | grep 'from 10.8.0.0/24 lookup 100')"
else
    bad "no rule 'from 10.8.0.0/24 lookup 100' (chain not enabled?)"
fi

echo "=== 2. table 100 ==="
if ip route show table 100 2>/dev/null | grep -q "default via 10.9.0.1 dev tun1"; then
    ok "table 100: $(ip route show table 100 | grep default)"
else
    bad "table 100 has no 'default via 10.9.0.1 dev tun1'"
    ip route show table 100 2>&1 || true
fi

echo "=== 3. route-get from VPN subnet source 10.8.0.1 (server tun0) ==="
ROUTE_VPN="$(ip route get 1.1.1.1 from 10.8.0.1 2>&1 || true)"
echo "$ROUTE_VPN"
# R4-BUG-4: assert "dev tun1" + "table 100", NOT "via 10.9.0.1
# dev tun1" -- the kernel prints no "via" for a point-to-point tun
# route-get, so the old string could never match (live-verify-R4 §13).
if echo "$ROUTE_VPN" | grep -q "table 100" && \
   echo "$ROUTE_VPN" | grep -q "dev tun1"; then
    ok "VPN source takes table 100 via dev tun1"
else
    bad "VPN source does NOT take table 100 via dev tun1"
fi

echo "=== 4. route-get from host (contrast: must stay main) ==="
ROUTE_HOST="$(ip route get 1.1.1.1 2>&1 || true)"
echo "$ROUTE_HOST"
if echo "$ROUTE_HOST" | grep -qv "table 100"; then
    ok "host source stays out of table 100 (sing-box SK5 leg unaffected)"
else
    bad "host source is in table 100 -- sing-box would loop into tun1"
fi

echo "=== 5. tun1 device ==="
if ip link show dev tun1 >/dev/null 2>&1; then
    ok "tun1 exists: $(ip addr show dev tun1 | grep -o 'inet [0-9./]*' | head -1)"
else
    bad "tun1 absent (is sing-box running?)"
fi

echo "=== 6. egress IP: direct vs via SK5 ==="
DIRECT_IP="$(curl -sS --max-time 10 http://ifconfig.me 2>/dev/null || echo '')"
echo "direct egress IP: ${DIRECT_IP:-<unreachable>}"
if [ -f "$CFG" ]; then
    # Read the credential with python3 (secret never echoed); build the
    # proxy-auth argument as an array so spaces/quoting stay correct.
    SK5_HOST="$(python3 -c "import json; print(json.load(open('$CFG')).get('host',''))" 2>/dev/null)"
    SK5_PORT="$(python3 -c "import json; print(json.load(open('$CFG')).get('port',1080))" 2>/dev/null)"
    SK5_USER="$(python3 -c "import json; print(json.load(open('$CFG')).get('username',''))" 2>/dev/null)"
    if [ -n "$SK5_HOST" ]; then
        PROXY_ARGS=()
        if [ -n "$SK5_USER" ]; then
            SK5_PASS="$(python3 -c "import json; print(json.load(open('$CFG')).get('password',''))" 2>/dev/null)"
            PROXY_ARGS=(--proxy-user "${SK5_USER}:${SK5_PASS}")
        fi
        SK5_IP="$(curl -sS --max-time 10 --socks5-hostname "${SK5_HOST}:${SK5_PORT}" \
            "${PROXY_ARGS[@]}" \
            http://ifconfig.me 2>/dev/null || echo '')"
        echo "SK5 egress IP: ${SK5_IP:-<unreachable>}"
        # R5-BUG-1: the difference assertion below is only meaningful
        # when the SK5 endpoint is a DIFFERENT host from this one.
        # A loopback endpoint (verify.sh's local Python stub, or an
        # on-host dante) egresses from this host itself: the stub's
        # socket.create_connection and dante both take the host's own
        # egress, so the SK5 IP can legitimately EQUAL the direct IP
        # (same family, e.g. both IPv6) or differ only by family
        # accident (dante takes IPv4 while direct curl takes IPv6).
        # Comparing against the same-family direct IP does NOT fix
        # this -- it makes both the stub case AND the dante case fail
        # (dante's IPv4 egress equals the host's own IPv4 egress).
        # So for a loopback endpoint, only liveness is asserted here
        # (a non-empty SK5_IP proves the SOCKS leg forwards); the
        # identity-difference assertion is SKIPped, and the chain
        # itself is proven by §1-§5 plus the toggle cells. A remote
        # (merchant) endpoint keeps the full comparison below, so the
        # check still bites when the chain is really not in effect.
        _HOST_LC="$(printf '%s' "$SK5_HOST" | tr '[:upper:]' '[:lower:]')"
        case "$_HOST_LC" in
            127.*|::1|localhost)
                if [ -n "$SK5_IP" ]; then
                    skip "SK5 endpoint $SK5_HOST is loopback (same-host stand-in); egress IP $SK5_IP proves the SOCKS leg forwards, but identity-difference cannot discriminate a same-host endpoint"
                else
                    bad "could not fetch egress IP via SK5 ($SK5_HOST:$SK5_PORT)"
                fi
                ;;
            *)
                if [ -n "$SK5_IP" ] && [ -n "$DIRECT_IP" ] && [ "$SK5_IP" != "$DIRECT_IP" ]; then
                    ok "egress via SK5 ($SK5_IP) differs from direct ($DIRECT_IP)"
                elif [ -n "$SK5_IP" ] && [ "$SK5_IP" = "$DIRECT_IP" ]; then
                    bad "SK5 egress IP equals direct IP ($SK5_IP) -- chain is not in effect"
                else
                    bad "could not fetch egress IP via SK5 ($SK5_HOST:$SK5_PORT)"
                fi
                ;;
        esac
    else
        skip "no SK5 host in $CFG"
    fi
else
    skip "no SK5 config at $CFG"
fi

echo "=== 7. curl --interface 10.9.0.2 (peer-end probe) ==="
if ip addr show | grep -q "inet 10.9.0.2/"; then
    PEER_IP="$(curl -sS --max-time 10 --interface 10.9.0.2 http://ifconfig.me 2>/dev/null || echo '')"
    if [ -n "$PEER_IP" ]; then ok "via 10.9.0.2 egress IP: $PEER_IP"; else bad "curl --interface 10.9.0.2 failed"; fi
else
    skip "10.9.0.2 is not a local address (it is sing-box's tun peer end); per-source proof is checks 3+6"
fi

echo
echo "=== SUMMARY: table / gateway / egress IP ==="
echo "table:   $(ip route show table 100 2>/dev/null | grep default || echo '<none>')"
# gateway is read from the table-100 listing, NOT from `ip route get`:
# a point-to-point tun route-get prints no "via" (R4-BUG-4), so the
# old extraction printed "<none>" on every healthy host.
echo "gateway: $(ip route show table 100 2>/dev/null | grep -o 'via [0-9.]* dev [a-z0-9]*' | head -1 || echo '<none>')"
echo "egress:  ${SK5_IP:-<unknown>} (direct: ${DIRECT_IP:-<unknown>})"
echo "result: PASS=$PASS FAIL=$FAIL SKIP=$SKIP"
[ "$FAIL" -eq 0 ]

#!/usr/bin/env bash
# R47-BD probe 1: unterminated "table 100" matcher (R47-L6-1) -- fixed
# behavior. This probe EXTRACTS the matcher actually used by
# install.sh / verify.sh / test-egress.sh (bare on the baseline,
# terminated on the fixed tree) and runs it against a foreign
# `lookup 1000` + populated table 1000 in a netns, in both modes
# (SK5-mode gate must fail closed, direct-mode gate must pass),
# plus the real-table-100 control (must match).
#
# Exit 0 iff the shipped matchers are terminated in both directions.
set -u
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "PASS: $*"; }
bad()  { FAIL=$((FAIL+1)); echo "FAIL: $*"; }
TREE="$(cd "$(dirname "$0")/.." && pwd)"
NS="unshare --user --map-root-user --net --mount bash -c"

echo "=== S. static census: extract the matcher the files actually use ==="
# The terminated form, when present; otherwise the bare form the
# baseline ships (so the behavior cells below test the FILE's
# matcher, not a hardcoded one).
PAT="$(grep -oF 'table 100([^0-9]|$)' "$TREE/install.sh" | head -1)"
if [ -z "$PAT" ]; then
    PAT="$(grep -oF 'table 100' "$TREE/install.sh" | head -1)"
fi
LPAT="$(grep -oF 'lookup 100([^0-9]|$)' "$TREE/verify.sh" | head -1)"
if [ -z "$LPAT" ]; then
    LPAT="$(grep -oF 'lookup 100' "$TREE/verify.sh" | head -1)"
fi
echo "install.sh matcher: $PAT"
echo "verify.sh matcher: $LPAT"
if [ "$PAT" = 'table 100([^0-9]|$)' ]; then
    ok "S install.sh uses the terminated matcher"
else
    bad "S install.sh uses the BARE matcher '$PAT' (matches table 1000)"
fi
if [ "$LPAT" = 'lookup 100([^0-9]|$)' ]; then
    ok "S verify.sh uses the terminated rule matcher"
else
    bad "S verify.sh uses the BARE rule matcher '$LPAT' (matches lookup 1000)"
fi
if grep -qE 'grep (-q|-qv) +["'"'"']table 100["'"'"']' "$TREE/install.sh" "$TREE/verify.sh" "$TREE/egress/test-egress.sh" \
   || grep -qE "grep -c 'from 10\.8\.0\.0/24 lookup 100'" "$TREE/verify.sh"; then
    bad "S a bare table-100 / lookup-100 matcher still exists in install.sh, verify.sh or test-egress.sh"
else
    ok "S no bare table-100 / lookup-100 matcher in install.sh, verify.sh, test-egress.sh"
fi

echo "=== A. foreign rule lookup 1000 + populated table 1000 (no table-100 rule) ==="
OUT=$($NS '
set -e
ip link set lo up; ip addr add 10.8.0.1/24 dev lo
ip rule add from 10.8.0.0/24 lookup 1000
ip route add default dev lo table 1000
ip route get 1.1.1.1 from 10.8.0.1
ip rule show
' 2>&1)
ROUTE_GET=$(printf '%s' "$OUT" | grep "1.1.1.1 from 10.8.0.1")
RULES=$(printf '%s' "$OUT" | grep -E "^[0-9]+:")
echo "route-get: $ROUTE_GET"
echo "rules: $RULES"
# A1: SK5-mode gate (install.sh:1819) must FAIL CLOSED on foreign output.
if printf '%s' "$ROUTE_GET" | grep -qE "$PAT"; then
    bad "A1 SK5-mode gate would PASS on foreign table-1000 output (false-pass)"
else
    ok "A1 SK5-mode gate fails closed on foreign table-1000 output"
fi
# A2: direct-mode gate (install.sh:1827) must NOT die on foreign output.
if printf '%s' "$ROUTE_GET" | grep -qE "$PAT"; then
    bad "A2 direct-mode gate would DIE on foreign table-1000 output (false-fail)"
else
    ok "A2 direct-mode gate passes on foreign table-1000 output"
fi
# A3: verify.sh rule count must read 0 on the foreign rule set.
COUNT=$(printf '%s' "$RULES" | grep -cE "from 10.8.0.0/24 $LPAT" || true)
if [ "$COUNT" = "0" ]; then
    ok "A3 verify.sh rule count = 0 on foreign lookup-1000 rules"
else
    bad "A3 verify.sh rule count = $COUNT on foreign rules (expected 0)"
fi
# A4: test-egress §4 host contrast -- a foreign table-1000 route-get
# from the host must read as "not in table 100". The main table gets
# its own default route so the lookup succeeds and prints a real
# line (main-table lookups carry no "table ..." token at all).
HOST_GET=$($NS '
set -e
ip link set lo up; ip addr add 10.8.0.1/24 dev lo
ip rule add from 10.8.0.0/24 lookup 1000
ip route add default dev lo table 1000
ip route add default dev lo
ip route get 1.1.1.1
' 2>&1 | grep "1.1.1.1")
echo "host route-get: $HOST_GET"
if printf '%s' "$HOST_GET" | grep -qE "$PAT"; then
    bad "A4 host route-get matched the table matcher: $HOST_GET"
else
    ok "A4 host route-get stays out of table 100"
fi

echo "=== B. control: real table-100 rule ==="
BOUT=$($NS '
set -e
ip link set lo up; ip addr add 10.8.0.1/24 dev lo
ip rule add from 10.8.0.0/24 lookup 100 prio 100
ip route add default dev lo table 100
ip route get 1.1.1.1 from 10.8.0.1
ip rule show
' 2>&1)
BROUTE=$(printf '%s' "$BOUT" | grep "1.1.1.1 from 10.8.0.1")
BRULES=$(printf '%s' "$BOUT" | grep -E "^[0-9]+:")
echo "route-get: $BROUTE"
if printf '%s' "$BROUTE" | grep -qE "$PAT"; then
    ok "B1 matcher MATCHES a real table-100 lookup"
else
    bad "B1 matcher missed a real table-100 lookup"
fi
BCOUNT=$(printf '%s' "$BRULES" | grep -cE "from 10.8.0.0/24 $LPAT" || true)
if [ "$BCOUNT" = "1" ]; then
    ok "B2 verify.sh rule count = 1 on the real table-100 rule"
else
    bad "B2 verify.sh rule count = $BCOUNT on the real rule (expected 1)"
fi

echo "result: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]

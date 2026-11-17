#!/usr/bin/env bash
# R45-L6-3 regression (Fix-Z): policy-routing.sh rule_exists() must not
# match a foreign `lookup 1000` rule, and add_rule() must not skip the
# add because of it. Adopted from the R45-L6 audit probe
# (tests/r45_l6_rule_exists.sh) with the cell order FIXED: the audit
# probe ran C3/C4 AFTER C2's add_rule, so on a fixed tree they
# (correctly) saw the rule C2 had just added and failed -- the probe
# as written can never pass on a fixed tree. Here all four matchers
# are checked against the pristine foreign-rule-only state FIRST,
# then add_rule runs, then the rule's presence is verified.
#
# In a throwaway userns+netns, install ONLY a foreign rule
#   100: from 10.8.0.0/24 lookup 1000
# (no lookup-100 rule at all) and show:
#   C1  the script's rule_exists() says absent
#   C3  the Python _rule_present() (fixed R41-L4-P2-1) says absent
#   C4  the fixed test-egress.sh §1 grep (fixed R42-F3-4) says absent
#   C2  add_rule() then adds the missing rule (no "rule already present")
#   C2b the lookup-100 rule is present afterwards
#   C2c rule_exists() now says present (positive control: the fixed
#       matcher still detects the real rule, it does not always say absent)
# On baseline 16f06c9: C1/C2/C2b fail (the defect), C3/C4 pass -- 2/6.
# On the fixed tree: 6/6.
#
# Run as ROOT (unshare userns+netns needs no host change; the netns
# dies with the shell, nothing persists). No /etc writes: only
# rule_exists/add_rule are exercised, never do_enable.
set -u
TREE="${R45L6_TREE:-$(cd "$(dirname "$0")/.." && pwd)}"
PASS=0; FAIL=0; FAILED=""
ok()   { PASS=$((PASS+1)); echo "PASS: $*"; }
bad()  { FAIL=$((FAIL+1)); FAILED="$FAILED $1"; echo "FAIL: $1 $2"; }

if [ "${1:-}" = "--inner" ]; then
    # --- inside the netns ---
    ip rule add from 10.8.0.0/24 lookup 1000 priority 100
    echo "--- ip rule show (netns) ---"
    ip rule show
    # Source the script's functions without running its dispatch.
    python3 - "$TREE/egress/policy-routing.sh" <<'PYEOF'
import sys
src = open(sys.argv[1]).read()
cut = src.index('case "${1:-}" in')
open("/tmp/r45z-funcs.sh", "w").write(src[:cut])
PYEOF
    # shellcheck disable=SC1091
    source /tmp/r45z-funcs.sh
    set +e  # the sourced file sets -euo pipefail; this probe must not die on a failing check
    echo "--- C1: rule_exists() on foreign-only state ---"
    if rule_exists; then
        bad C1-rule-exists-claims-present "(rc 0 with only a lookup-1000 rule)"
    else
        ok "C1 rule_exists() correctly says absent"
    fi
    echo "--- C3: Python _rule_present() on foreign-only state ---"
    if python3 -c "import sys; sys.path.insert(0, '$TREE/egress'); from sk5_manager import _rule_present; raise SystemExit(0 if _rule_present() else 1)"; then
        bad C3-python-rule-present-claims-present ""
    else
        ok "C3 Python _rule_present() correctly says absent"
    fi
    echo "--- C4: fixed test-egress §1 grep on foreign-only state ---"
    if ip rule show | grep -qE "^100:[[:space:]]+from 10\.8\.0\.0/24 lookup 100([[:space:]]|$)"; then
        bad C4-fixed-grep-matches ""
    else
        ok "C4 fixed §1 grep correctly says absent"
    fi
    echo "--- C2: add_rule() ---"
    OUT="$(add_rule 2>&1)"
    echo "$OUT"
    if echo "$OUT" | grep -q "rule already present"; then
        bad C2-add-rule-skips-add "(logged 'rule already present')"
    else
        ok "C2 add_rule() adds the missing rule"
    fi
    if ip rule show | grep -qE "^100:[[:space:]]+from 10\.8\.0\.0/24 lookup 100([[:space:]]|$)"; then
        ok "C2b lookup-100 rule now present"
    else
        bad C2b-lookup-100-still-absent "(add_rule skipped it and it never landed)"
    fi
    echo "--- C2c: rule_exists() after the add (positive control) ---"
    if rule_exists; then
        ok "C2c rule_exists() correctly says present after the add"
    else
        bad C2c-rule-exists-says-absent-after-add "(fixed matcher must still detect the real rule)"
    fi
    echo "R45L6C-FIXED TOTAL: PASS=$PASS FAIL=$FAIL:$FAILED"
    [ "$FAIL" -eq 0 ]
    exit $?
fi

# --- outer: enter the netns and re-run this script ---
unshare --user --map-root-user --net --mount -- bash "$0" --inner

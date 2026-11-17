#!/usr/bin/env bash
# r45_l4_verify_cleanup.sh -- R45-L4 probe: does verify.sh's EXIT trap
# actually revoke the verify-* test user it created in section 7?
#
# DELIVERY.md (after Fix-W, R44-L6-2) claims the trap revokes the user
# "best effort, only when the toggle test ran and logged in". The code
# (verify.sh:94-199) gates the DELETE on SK5_TOGGLED==1 && LOGGED_IN==1,
# NOT on SK5_TOGGLE_RAN. SK5_TOGGLED is 1 only while the chain is left
# enabled at exit: set on enable, cleared on disable, set again by
# section 12. So the user is left behind when:
#   A. the toggle test was SKIPPED (real merchant SK5 enabled) --
#      the common production case: section 7 still created the user;
#   B. the toggle ran but section 11 disabled the chain and section 12
#      did not re-enable it (skipped or non-200).
# This probe extracts cleanup() VERBATIM from verify.sh, drives it with
# a stub curl that logs every invocation, and asserts on the DELETE.
# ADOPTED into tests/ by Fix-AA (R45-L4-2): the extraction is marker-based
# now, not the audit draft's hardcoded `sed -n '94,199p'` -- Fix-AA's
# verify.sh edits shifted cleanup()'s line range, so the hardcoded range
# would extract a truncated function. Behavior asserted is unchanged.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TDIR="$(mktemp -d /tmp/r45l4-cleanup.XXXXXX)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "PASS $1"; }
bad()  { FAIL=$((FAIL+1)); echo "FAIL $1"; }
failures=()

# --- stub curl: log argv, exit 0 ---
mkdir -p "$TDIR/stubbin"
cat > "$TDIR/stubbin/curl" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$CURL_LOG"
exit 0
EOF
chmod +x "$TDIR/stubbin/curl"
export PATH="$TDIR/stubbin:$PATH"

# --- extract cleanup() verbatim from verify.sh ---
# Marker-based (Fix-AA): from the `cleanup() {` line to the line before
# `trap cleanup EXIT` -- the hardcoded 94-199 range broke when Fix-AA's
# edits shifted cleanup()'s line range.
awk '/^cleanup\(\) \{/{f=1} /^trap cleanup EXIT/{f=0} f' "$ROOT/verify.sh" > "$TDIR/cleanup.fn"
grep -q '^cleanup() {' "$TDIR/cleanup.fn" || { echo "FAIL extract: cleanup() not found"; exit 1; }
# shellcheck disable=SC1091
. "$TDIR/cleanup.fn"

run_case() { # run_case <label> <toggled> <logged_in> <expect_delete:0|1>
    local label="$1" toggled="$2" logged="$3" expect="$4"
    local wd="$TDIR/$label"
    mkdir -p "$wd"
    # NOTE: the log must live OUTSIDE $wd: cleanup() ends with
    # `rm -rf "$WORKDIR"` and WORKDIR is $wd, so a log inside $wd
    # would be deleted before the assertion reads it.
    export CURL_LOG="$TDIR/$label-curl.log"
    : > "$CURL_LOG"
    (
        WORKDIR="$wd"
        CONFIG_DIR="$wd/config"
        mkdir -p "$CONFIG_DIR"
        PANEL_URL="https://127.0.0.1:8443"
        COOKIE_JAR="$wd/cookies.txt"
        STUB_PID=""
        STUB_PORT=11080
        TEST_USER="verify-1234567890"
        SK5_TOGGLED="$toggled"
        LOGGED_IN="$logged"
        SK5_TOGGLE_RAN=0
        SK5_JSON_BACKED_UP=0
        SINGBOX_JSON_BACKED_UP=0
        SK5_JSON_EXISTED=0
        cleanup
    ) >/dev/null 2>&1
    local got=0
    grep -q "DELETE.*api/openvpn/users/verify-1234567890" "$CURL_LOG" 2>/dev/null && got=1
    if [ "$got" -eq "$expect" ]; then
        ok "$label (DELETE issued=$got, expected=$expect)"
    else
        bad "$label (DELETE issued=$got, expected=$expect)"
        failures+=("$label")
    fi
}

# The DESIRED behavior (what the probe asserts): the verify-* user is
# revoked whenever it was created and we are logged in, regardless of
# the SK5 toggle outcome. On the baseline this FAILS for A and B
# (negative control proving the finding); C and D pass as controls.
# A: toggle skipped (real SK5 enabled), user was created in section 7.
run_case "A-toggle-skipped" 0 1 1
# B: toggle ran, section 11 disabled, section 12 did not re-enable.
run_case "B-toggle-ran-disabled" 0 1 1
# C: chain left enabled at exit (happy path) -- control: DELETE must fire.
run_case "C-left-enabled" 1 1 1
# D: not logged in -- control: no DELETE (nothing to revoke with).
run_case "D-not-logged-in" 1 0 0

echo "R45L4-CLEANUP TOTAL: PASS=$PASS FAIL=$FAIL [${failures[*]}]"
rm -rf "$TDIR"
[ "$FAIL" -eq 0 ]

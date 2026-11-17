#!/usr/bin/env bash
# r45_fix_aa.sh -- R45 Fix-AA probe: L4-2 (verify.sh EXIT trap revokes the
# verify-* user in ALL exit paths) + L4-1 (1.0.2 sidecar carries the
# releases/ prefix so the DELIVERY §9 command passes from the repo root).
#
# Usage: bash tests/r45_fix_aa.sh [ROOT]
#   ROOT defaults to the repo root (parent of tests/). To run the negative
#   control, point ROOT at a baseline (16f06c9) worktree.
# Expected: baseline 16f06c9 -> L4-1 FAIL, L4-2 cases A/B FAIL (C/D/E PASS);
# tip -> ALL PASS.
set -uo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TDIR="$(mktemp -d /tmp/r45fixaa.XXXXXX)"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "PASS $1"; }
bad()  { FAIL=$((FAIL+1)); echo "FAIL $1"; }
failures=()

# ---------------------------------------------------------- L4-1: sidecar
# The hash value itself must be unchanged (same tarball); only the path
# field changes from bare to releases/-prefixed.
_SIDECAR="$ROOT/releases/ovpn-release-1.0.2.tar.gz.sha256"
_TARBALL="$ROOT/releases/ovpn-release-1.0.2.tar.gz"
if [ -f "$_SIDECAR" ] && [ -f "$_TARBALL" ]; then
    _HASH_IN_FILE="$(awk '{print $1}' "$_SIDECAR")"
    _HASH_REAL="$(sha256sum "$_TARBALL" | awk '{print $1}')"
    if [ "$_HASH_IN_FILE" = "$_HASH_REAL" ]; then
        ok "L4-1a sidecar hash equals tarball hash ($_HASH_REAL)"
    else
        bad "L4-1a sidecar hash $_HASH_IN_FILE != tarball $_HASH_REAL"
        failures+=("L4-1a")
    fi
    if grep -q '^ *[0-9a-f]\{64\}  releases/ovpn-release-1.0.2.tar.gz$' "$_SIDECAR"; then
        ok "L4-1b sidecar carries the releases/ prefix"
    else
        bad "L4-1b sidecar lacks the releases/ prefix: $(cat "$_SIDECAR")"
        failures+=("L4-1b")
    fi
    if (cd "$ROOT" && sha256sum -c releases/ovpn-release-1.0.2.tar.gz.sha256 >/dev/null 2>&1); then
        ok "L4-1c DELIVERY §9 command passes from the repo root"
    else
        bad "L4-1c DELIVERY §9 command fails from the repo root"
        failures+=("L4-1c")
    fi
else
    bad "L4-1 sidecar or tarball missing under $ROOT"
    failures+=("L4-1")
fi

# ---------------------------------------------------------- L4-2: cleanup()
# Extract cleanup() VERBATIM from the tree's verify.sh: from the
# `cleanup() {` line to the line before `trap cleanup EXIT`.
mkdir -p "$TDIR/stubbin"
cat > "$TDIR/stubbin/curl" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >> "$CURL_LOG"
exit 0
EOF
chmod +x "$TDIR/stubbin/curl"
export PATH="$TDIR/stubbin:$PATH"

awk '/^cleanup\(\) \{/{f=1} /^trap cleanup EXIT/{f=0} f' "$ROOT/verify.sh" > "$TDIR/cleanup.fn"
grep -q '^cleanup() {' "$TDIR/cleanup.fn" || { echo "FAIL extract: cleanup() not found in $ROOT/verify.sh"; exit 1; }
# shellcheck disable=SC1091
. "$TDIR/cleanup.fn"

run_case() { # run_case <label> <toggled> <ran> <created> <logged> <expect_delete:0|1> [expect_disable:0|1]
    local label="$1" toggled="$2" ran="$3" created="$4" logged="$5" expect="$6" expect_dis="${7:-}"
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
        SK5_TOGGLE_RAN="$ran"
        USER_CREATED="$created"
        LOGGED_IN="$logged"
        SK5_JSON_BACKED_UP=0
        SINGBOX_JSON_BACKED_UP=0
        SK5_JSON_EXISTED=0
        cleanup
    ) >/dev/null 2>&1
    local got=0 dis=0
    grep -q "DELETE.*api/openvpn/users/verify-1234567890" "$CURL_LOG" 2>/dev/null && got=1
    grep -q "POST.*api/sk5" "$CURL_LOG" 2>/dev/null && dis=1
    local good=1
    [ "$got" -eq "$expect" ] || good=0
    if [ -n "$expect_dis" ]; then
        [ "$dis" -eq "$expect_dis" ] || good=0
    fi
    if [ "$good" -eq 1 ]; then
        ok "L4-2-$label (DELETE=$got expect=$expect, SK5-disable=$dis expect=${expect_dis:-any})"
    else
        bad "L4-2-$label (DELETE=$got expect=$expect, SK5-disable=$dis expect=${expect_dis:-any})"
        failures+=("L4-2-$label")
    fi
}

# A: toggle test SKIPPED (real merchant SK5 enabled) -- the common
# production case. User was created in §7; must be revoked.
run_case "A-skipped"  0 0 1 1 1 0
# B: toggle ran, §11 disabled the chain, §12 did not re-enable it.
run_case "B-toggled-off" 0 1 1 1 1 0
# C: chain left enabled at exit -- the only path the old code covered.
# DELETE + SK5 disable POST both expected.
run_case "C-left-enabled" 1 1 1 1 1 1
# D: not logged in -- no DELETE (nothing authenticated to revoke with).
run_case "D-not-logged-in" 0 0 1 0 0 0
# E: user never created (§7 failed / skipped) -- no DELETE.
run_case "E-never-created" 0 0 0 1 0 0

echo
echo "R45FIXAA TOTAL: PASS=$PASS FAIL=$FAIL [${failures[*]}]"
rm -rf "$TDIR"
[ "$FAIL" -eq 0 ]

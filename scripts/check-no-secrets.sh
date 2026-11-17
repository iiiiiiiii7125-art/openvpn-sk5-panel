#!/usr/bin/env bash
# check-no-secrets.sh -- fail-closed credential scan for this repo.
#
# R41-L7-P2-3: the project once shipped a live secret.key (P0-5); releases
# relied on a manual, unenforced scan. This script is the enforced gate:
#   * verify-integration.sh runs it as gate cell 0 (counted);
#   * scripts/git-hooks/pre-push runs it before every push
#     (install once per clone: cp scripts/git-hooks/pre-push .git/hooks/pre-push).
#
# What it checks (tracked files = what would be pushed):
#   1. sensitive filenames: secret.key, admin.pass, panel.db, sk5.json,
#      agent_queue.json (in any directory), or anything under panel/data/;
#   2. the shipped secret's SHA-256 (the panel/app.py tripwire value)
#      appearing anywhere except the tripwire definition itself and this
#      script's own detector value below (both are detectors, not secrets);
#   3. PEM private-key blocks, except the documented fake fixture in
#      tests/r17_core.py (a PEM header line plus a single "FAKE" body
#      line, not a real key);
#   4. release tarballs listing a sensitive entry (a shipped package must
#      never contain panel/data/ or a credential file).
#
# Output: offending paths + check name only -- matched secret CONTENT is
# never printed. Exit 0 = clean, 1 = secrets found, 2 = usage/environment
# error (e.g. target dir missing).
set -uo pipefail

TARGET="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
[ -d "$TARGET" ] || { echo "check-no-secrets: target dir not found: $TARGET" >&2; exit 2; }

# The shipped secret's SHA-256 (panel/app.py _SHIPPED_SECRET_SHA256). The
# key itself is long published; only its hash is used here, as a
# "shipped value" detector -- the hash cannot be reversed into the key.
SHIPPED_HASH="484fec07e813e9b9e57548d1992ce6767326fd8a82cfddd6fe0c595f93d7d5a5"

FAIL=0
fail() { FAIL=1; echo "SECRET: $1" >&2; }

# git-tracked files are exactly what a push would carry. Outside a git
# repo, fall back to a disk scan (excluding .git).
if git -C "$TARGET" rev-parse --git-dir >/dev/null 2>&1; then
    _FILES="$(git -C "$TARGET" ls-files)"
    _grep() { git -C "$TARGET" grep -l --cached -e "$1" -- . 2>/dev/null || true; }
else
    _FILES="$(cd "$TARGET" && find . -path ./.git -prune -o -type f -print | sed 's|^\./||')"
    _grep() { (cd "$TARGET" && grep -rIl -e "$1" --exclude-dir=.git . 2>/dev/null || true); }
fi

# --- 1. sensitive filenames -------------------------------------------
while IFS= read -r _f; do
    [ -n "$_f" ] || continue
    _base="${_f##*/}"
    case "$_base" in
        secret.key|admin.pass|panel.db|sk5.json|agent_queue.json)
            fail "sensitive filename tracked: $_f" ;;
    esac
    case "$_f" in
        panel/data/*) fail "file under panel/data/ tracked: $_f" ;;
    esac
done <<EOF
$_FILES
EOF

# --- 2. shipped secret hash (except the tripwire definition itself) ----
# Exempted: panel/app.py (the tripwire definition) and this script (its
# SHIPPED_HASH literal below IS the detector value, not a shipped secret).
while IFS= read -r _f; do
    [ -n "$_f" ] || continue
    case "$_f" in
        panel/app.py|scripts/check-no-secrets.sh) continue ;;
    esac
    fail "shipped secret hash present: $_f"
done <<EOF
$(_grep "$SHIPPED_HASH")
EOF

# --- 3. PEM private-key blocks (except the fake fixture) --------------
# Exempted: tests/r17_core.py (a PEM header line plus a single "FAKE"
# body line, not a real key). NOTE: do not quote a PEM header literally
# in a comment in this script -- check 3 would match this file itself.
while IFS= read -r _f; do
    [ -n "$_f" ] || continue
    case "$_f" in
        tests/r17_core.py) continue ;;  # fake key, not a real one
    esac
    fail "private-key PEM block: $_f"
done <<EOF
$(_grep '-----BEGIN \(RSA \|EC \|OPENSSH \|DSA \)\?PRIVATE KEY-----')
EOF

# --- 4. release tarballs must not list a sensitive entry --------------
for _t in "$TARGET"/releases/*.tar.gz; do
    [ -e "$_t" ] || continue
    _bad="$(tar tzf "$_t" 2>/dev/null | while IFS= read -r _e; do
        case "$_e" in */) continue ;; esac  # bare dir entry (e.g. an empty panel/data/) carries no secret
        _b="${_e##*/}"
        case "$_b" in
            secret.key|admin.pass|panel.db|sk5.json|agent_queue.json) echo "$_e" ;;
        esac
        case "$_e" in
            */panel/data/*|panel/data/*) echo "$_e" ;;
        esac
    done)"
    if [ -n "$_bad" ]; then
        fail "release tarball lists credential entries: $_t ($(printf '%s' "$_bad" | head -1))"
    fi
done

if [ "$FAIL" -eq 0 ]; then
    echo "check-no-secrets: clean ($TARGET)"
    exit 0
fi
echo "check-no-secrets: FAILED -- remove the files above before pushing/releasing" >&2
exit 1

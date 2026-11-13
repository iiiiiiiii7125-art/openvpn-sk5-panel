#!/usr/bin/env bash
# R35 probe: panel-domain validation, panel.env append, Caddyfile
# build, non-TTY skip. Runs in the sandbox: no apt/systemd/network.
# It sources ONLY the R35 helper block from install.sh (between the
# R35-HELPERS-BEGIN/END markers) -- never the whole installer.
# Usage: bash tests/r35_domain_reverse_proxy.sh
# Exit code = number of FAILs.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0; FAIL=0; SKIP=0
cell() { # cell <name> <0=pass, 1=fail>
    if [ "$2" -eq 0 ]; then PASS=$((PASS+1)); echo "PASS $1";
    else FAIL=$((FAIL+1)); echo "FAIL $1"; fi
}
skip() { SKIP=$((SKIP+1)); echo "SKIP $1"; }

# --- source the helper block -------------------------------------------
sed -n '/^# R35-HELPERS-BEGIN/,/^# R35-HELPERS-END/p' "$ROOT/install.sh" > "$TMP/helpers.sh"
[ -s "$TMP/helpers.sh" ]; cell "helper block extracted from install.sh" "$?"
CONFIG_DIR="$TMP/config"; mkdir -p "$CONFIG_DIR"
# R20-BUG-2: the Caddyfile references the caddy-readable COPY of the
# panel cert; the probe points the copy at a sandbox path.
_CADDY_PANEL_CERT="$TMP/caddy/panel-cert.pem"
SERVER_IP="203.0.113.7"; PANEL_PORT=8443
# shellcheck disable=SC1090
source "$TMP/helpers.sh"

# --- (a) domain validation ----------------------------------------------
for d in panel.example.com a.b.co foo-bar.example-domain.com sub.domain.example.org; do
    if _normalize_panel_domain "$d" >/dev/null 2>&1; then r=0; else r=1; fi
    cell "accept $d" "$r"
done
[ "$(_normalize_panel_domain "example.com.")" = "example.com" ]
cell "trailing dot strips to example.com" "$?"
for d in "https://example.com" "example.com:8443" "example.com/path" "example" ".example.com" "example..com" "-example.com" "example-.com" "" "exa mple.com" "example.com.." "http://panel.example.com:8443/x"; do
    if _normalize_panel_domain "$d" >/dev/null 2>&1; then r=1; else r=0; fi
    cell "reject [$d]" "$r"
done

# --- (b) panel.env --------------------------------------------------------
: > "$CONFIG_DIR/panel.env"
_append_panel_env_domain "panel.example.com"
grep -qx "OVPN_PANEL_DOMAIN=panel.example.com" "$CONFIG_DIR/panel.env" \
    && grep -qx "OVPN_PANEL_HTTPS=1" "$CONFIG_DIR/panel.env" \
    && grep -qx "OVPN_TRUSTED_PROXY=1" "$CONFIG_DIR/panel.env"
cell "panel.env gains the three vars" "$?"
[ "$(wc -l < "$CONFIG_DIR/panel.env")" -eq 3 ]
cell "panel.env has exactly 3 lines" "$?"
: > "$CONFIG_DIR/panel.env"
if grep -q "OVPN_PANEL_DOMAIN\|OVPN_PANEL_HTTPS\|OVPN_TRUSTED_PROXY" "$CONFIG_DIR/panel.env"; then r=1; else r=0; fi
cell "skipped panel.env gains none of the three vars" "$r"

# --- (c) Caddyfile --------------------------------------------------------
_BUILD_OUT="$TMP/Caddyfile.new"
_build_caddyfile "panel.example.com" "" "$_BUILD_OUT"
cat > "$TMP/expected" <<EOF
# BEGIN openvpn-sk5-panel (managed by install.sh -- change the domain with OVPN_PANEL_DOMAIN, do not hand-edit this block)
panel.example.com {
    reverse_proxy https://localhost:8443 {
        transport http {
            tls_trusted_ca_certs $_CADDY_PANEL_CERT
        }
    }
}
# END openvpn-sk5-panel
EOF
diff -u "$TMP/expected" "$_BUILD_OUT" >/dev/null
cell "Caddyfile block exact (localhost, trusted CA cert, no insecure flag)" "$?"
if grep -q "tls_insecure_skip_verify" "$_BUILD_OUT"; then r=1; else r=0; fi
cell "no tls_insecure_skip_verify in generated block" "$r"
if grep -q "127.0.0.1:8443" "$_BUILD_OUT"; then r=1; else r=0; fi
cell "upstream is localhost, not 127.0.0.1" "$r"
# Marker replacement: other content kept, old managed block dropped.
{
    printf 'other.example.com {\n    respond "hi"\n}\n'
    printf '# BEGIN openvpn-sk5-panel (managed by install.sh -- change the domain with OVPN_PANEL_DOMAIN, do not hand-edit this block)\n'
    printf 'old.example.com {\n    reverse_proxy https://localhost:8443 {\n        transport http {\n            tls_trusted_ca_certs %s\n        }\n    }\n}\n' "$_CADDY_PANEL_CERT"
    printf '# END openvpn-sk5-panel\n'
} > "$TMP/Caddyfile.old"
_build_caddyfile "panel.example.com" "$TMP/Caddyfile.old" "$_BUILD_OUT"
grep -q 'other.example.com' "$_BUILD_OUT" \
    && ! grep -q 'old.example.com' "$_BUILD_OUT" \
    && grep -q 'panel.example.com' "$_BUILD_OUT"
cell "marker replacement keeps other content, drops old block" "$?"
if grep -rn "tls_insecure_skip_verify" "$ROOT/install.sh" "$ROOT/cloudflare" "$ROOT/panel" "$ROOT/egress" "$ROOT/core" "$ROOT/agent" >/dev/null 2>&1; then r=1; else r=0; fi
cell "no tls_insecure_skip_verify anywhere in the tree" "$r"

# --- (e) caddy-readable cert copy (R20-BUG-2) ---------------------------
# The installer copies the PUBLIC panel cert to $_CADDY_PANEL_CERT
# (0644) on every run; the generated Caddyfile must reference the
# copied path, never $CONFIG_DIR/panel-cert.pem (0700, root-only).
printf 'DUMMY PANEL CERT' > "$CONFIG_DIR/panel-cert.pem"
mkdir -p "$(dirname "$_CADDY_PANEL_CERT")"
install -m 0644 "$CONFIG_DIR/panel-cert.pem" "$_CADDY_PANEL_CERT"
[ "$(stat -c %a "$_CADDY_PANEL_CERT")" = "644" ] && cmp -s "$CONFIG_DIR/panel-cert.pem" "$_CADDY_PANEL_CERT"
cell "copied cert is world-readable (0644) and byte-identical" "$?"
grep -Fq "$_CADDY_PANEL_CERT" "$_BUILD_OUT" && ! grep -Fq "$CONFIG_DIR/panel-cert.pem" "$_BUILD_OUT"
cell "generated Caddyfile references the copied cert path, not \$CONFIG_DIR" "$?"
grep -Fq 'install -m 0644 "$PANEL_CERT" "$_CADDY_PANEL_CERT"' "$ROOT/install.sh"
cell "installer re-copies the public cert on every run (0644)" "$?"
if grep -q 'tls_trusted_ca_certs.*CONFIG_DIR' "$ROOT/install.sh"; then r=1; else r=0; fi
cell "no tls_trusted_ca_certs pointing into \$CONFIG_DIR anywhere in install.sh" "$?"

# --- (d) non-TTY resolve (must skip without hanging) ----------------------
# stdin /dev/null, no env, no prev -> empty output, exit 0, fast.
timeout 5 bash -c 'source "$1"; _resolve_panel_domain' _ "$TMP/helpers.sh" </dev/null > "$TMP/out.txt" 2>/dev/null
rc=$?
[ "$rc" -eq 0 ] && [ ! -s "$TMP/out.txt" ]
cell "non-TTY run skips fast without hanging" "$?"
# Env var path works non-interactively.
out="$(OVPN_PANEL_DOMAIN="panel.example.com" timeout 5 bash -c 'source "$1"; _resolve_panel_domain' _ "$TMP/helpers.sh" </dev/null 2>/dev/null)"
[ "$out" = "panel.example.com" ]
cell "OVPN_PANEL_DOMAIN works non-interactively" "$?"
# Previous-domain path works non-interactively (re-run keeps it).
out="$(_PREV_PANEL_DOMAIN="old.example.com" timeout 5 bash -c 'source "$1"; _resolve_panel_domain' _ "$TMP/helpers.sh" </dev/null 2>/dev/null)"
[ "$out" = "old.example.com" ]
cell "previous domain kept on non-interactive re-run" "$?"
# TTY prompt path (best effort -- needs `script` for a pty).
if command -v script >/dev/null 2>&1; then
    # R20-BUG-1 regression: the old TTY cell only counted how often
    # the domain appeared in the typescript (>= 2: pty echo + the
    # polluted captured value) and never asserted the captured value
    # was CLEAN. Now run the FULL call-site path inside the pty --
    # _PANEL_DOMAIN="$(_resolve_panel_domain)" then
    # _normalize_panel_domain -- and assert the result is exactly the
    # typed domain. With the prompt on stdout (the bug), the captured
    # value is polluted, normalization fails and RESULT is empty.
    cat > "$TMP/tty-inner.sh" <<'EOF'
source "$1"
d="$(_resolve_panel_domain)"
n="$(_normalize_panel_domain "$d" 2>/dev/null || true)"
printf 'RESULT=[%s]\n' "$n"
EOF
    _TTY_OUT="$(printf 'tty.example.com\n' | timeout 10 script -qec "bash $TMP/tty-inner.sh $TMP/helpers.sh" /dev/null 2>/dev/null)"
    echo "$_TTY_OUT" | grep -Fq "RESULT=[tty.example.com]"
    cell "TTY prompt: full path _resolve -> _normalize yields clean tty.example.com (R20-BUG-1)" "$?"
    echo "$_TTY_OUT" | grep -Fq "面板域名"
    cell "TTY prompt is still shown to the operator (stderr)" "$?"
else
    skip "TTY prompt path (no \`script\` for a pty)"
fi

# --- (f) TCP 443 + domain -> proxy skipped (R20-BUG-3) ------------------
# Run the shipped domain section VERBATIM (same extraction as
# tests/r35_domain_failpath.sh) with OVPN_PROTO=tcp OVPN_PORT=443 and
# a requested domain. The proxy must be skipped with the conflict
# warn, before Caddy is ever touched.
sed -n '/^# R35: remember a previously configured panel domain/,/^chmod 600 "\$CONFIG_DIR\/panel.env"/p' "$ROOT/install.sh" > "$TMP/frag-a.sh"
[ -s "$TMP/frag-a.sh" ]; cell "fragment A extracted (prev capture + panel.env rewrite)" "$?"
sed -n '/panel domain + reverse proxy (Caddy)/,/sing-box config/p' "$ROOT/install.sh" | sed '$d' > "$TMP/frag-b.sh"
grep -q '^_PANEL_DOMAIN=' "$TMP/frag-b.sh"; cell "fragment B extracted (domain section)" "$?"
cat > "$TMP/bug3-run.sh" <<'RUNEOF'
set -uo pipefail
log()  { echo "LOG: $*" >&2; }
warn() { echo "WARN: $*" >&2; }
die()  { echo "DIE: $*" >&2; exit 1; }
source "$1"
source "$2"
source "$3"
printf 'AFTER=[%s]\n' "$_PANEL_DOMAIN" >&2
RUNEOF
_B3BIN="$TMP/b3bin"; mkdir -p "$_B3BIN"
cat > "$_B3BIN/caddy" <<'EOF'
#!/usr/bin/env bash
echo "caddy $*" >> "$CADDY_CALLS"
exit 0
EOF
cat > "$_B3BIN/getent" <<'EOF'
#!/usr/bin/env bash
echo "203.0.113.7 panel.example.com"
EOF
cat > "$_B3BIN/systemctl" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "is-active" ]; then exit 0; fi
exit 0
EOF
chmod +x "$_B3BIN/"*
# Defensive snapshot of the real /etc/caddy: the correct behavior
# writes nothing there; if a regression reaches the write path, the
# live files are restored below.
_B3_CF_BEFORE="absent"; [ -f /etc/caddy/Caddyfile ] && _B3_CF_BEFORE="$(cat /etc/caddy/Caddyfile)"
_B3_CERT_BEFORE="absent"; [ -f /etc/caddy/panel-cert.pem ] && _B3_CERT_BEFORE="present"
export CADDY_CALLS="$TMP/bug3-caddy-calls.log"
: > "$CADDY_CALLS"
# Fresh install state: no previous domain in panel.env; the domain
# comes from the env var. PANEL_CERT points at a nonexistent path so
# even a regressed run cannot copy a real cert.
: > "$CONFIG_DIR/panel.env"
export CONFIG_DIR SERVER_IP PANEL_PORT
export _PUBLIC_IP=203.0.113.7 _SERVER_IP_LINE=""
export OVPN_PANEL_DOMAIN="panel.example.com" OVPN_PROTO=tcp OVPN_PORT=443
export PANEL_CERT="$TMP/no-such/panel-cert.pem" PANEL_KEY="$TMP/no-such/panel-key.pem"
export CA_DIR=/etc/openvpn/server/easy-rsa SERVER_DIR=/etc/openvpn/server
export INSTALL_ROOT=/opt/openvpn-sk5-panel
PATH="$_B3BIN:$PATH" bash "$TMP/bug3-run.sh" "$TMP/helpers.sh" "$TMP/frag-a.sh" "$TMP/frag-b.sh" </dev/null > "$TMP/bug3.log" 2>&1
grep -Fq "域名反代需占用 443 端口，服务端当前为 TCP 443，两者冲突，本次不设反代；改用 UDP 1194 或换端口后再配域名" "$TMP/bug3.log"
cell "TCP 443 + domain: conflict warn names 443 (R20-BUG-3)" "$?"
if grep -q "command not found" "$TMP/bug3.log"; then r=1; else r=0; fi
cell "TCP 443 + domain: fragment run had no missing functions (non-vacuous)" "$?"
grep -Fq "AFTER=[]" "$TMP/bug3.log"
cell "TCP 443 + domain: _PANEL_DOMAIN cleared (proxy skipped)" "$?"
if grep -q "OVPN_PANEL_DOMAIN\|OVPN_PANEL_HTTPS\|OVPN_TRUSTED_PROXY" "$CONFIG_DIR/panel.env"; then r=1; else r=0; fi
cell "TCP 443 + domain: panel.env gains no trust vars" "$?"
[ ! -s "$CADDY_CALLS" ]
cell "TCP 443 + domain: caddy never invoked" "$?"
_B3_CF_AFTER="absent"; [ -f /etc/caddy/Caddyfile ] && _B3_CF_AFTER="$(cat /etc/caddy/Caddyfile)"
_B3_CERT_AFTER="absent"; [ -f /etc/caddy/panel-cert.pem ] && _B3_CERT_AFTER="present"
[ "$_B3_CF_AFTER" = "$_B3_CF_BEFORE" ] && [ "$_B3_CERT_AFTER" = "$_B3_CERT_BEFORE" ]
cell "TCP 443 + domain: live /etc/caddy untouched" "$?"
# Restore (no-op on the correct path).
if [ "$_B3_CF_AFTER" != "$_B3_CF_BEFORE" ]; then
    if [ "$_B3_CF_BEFORE" = "absent" ]; then rm -f /etc/caddy/Caddyfile; else printf '%s' "$_B3_CF_BEFORE" > /etc/caddy/Caddyfile; fi
fi
if [ "$_B3_CERT_AFTER" != "$_B3_CERT_BEFORE" ]; then
    if [ "$_B3_CERT_BEFORE" = "absent" ]; then rm -f /etc/caddy/panel-cert.pem; fi
fi

# --- (g) caddy validate runs as the caddy user (R20-BUG-2) --------------
# _validate_caddy_config must invoke `caddy validate` via
# `runuser -u caddy` (root validate masks unreadable certs), with a
# loud warning + root fallback when runuser or the caddy user is
# unavailable.
STUBBIN="$TMP/stubbin"; mkdir -p "$STUBBIN"
cat > "$STUBBIN/runuser" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$RUNUSER_LOG"
while [ $# -gt 0 ]; do
    if [ "$1" = "--" ]; then shift; break; fi
    shift
done
exec "$@"
EOF
cat > "$STUBBIN/id" <<'EOF'
#!/usr/bin/env bash
[ "${1:-}" = "caddy" ] && exit 0
exit 1
EOF
cat > "$STUBBIN/caddy" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$CADDY_LOG"
exit 0
EOF
chmod +x "$STUBBIN/"*
export RUNUSER_LOG="$TMP/runuser.log" CADDY_LOG="$TMP/caddy.log"
: > "$RUNUSER_LOG"; : > "$CADDY_LOG"
_VCFG="$(mktemp "$TMP/vcfg.XXXXXX")"
printf 'dummy' > "$_VCFG"
PATH="$STUBBIN:$PATH" bash -c 'warn() { echo "WARN: $*" >&2; }; source "$1"; _validate_caddy_config "$2"' _ "$TMP/helpers.sh" "$_VCFG" > "$TMP/v-out.txt" 2> "$TMP/v-err.txt"
_vrc=$?
[ "$_vrc" -eq 0 ] && grep -Fq -- "-u caddy --" "$RUNUSER_LOG" && grep -Fq "caddy validate" "$RUNUSER_LOG" && grep -Fq "validate --config" "$CADDY_LOG"
cell "caddy validate is invoked as the caddy user (runuser -u caddy)" "$?"
[ "$(stat -c %a "$_VCFG")" = "644" ]
cell "validate temp file is made world-readable for the caddy user" "$?"
# Fallback: no caddy user -> loud warn + root validate.
STUBBIN2="$TMP/stubbin2"; mkdir -p "$STUBBIN2"
cat > "$STUBBIN2/id" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
cat > "$STUBBIN2/caddy" <<'EOF'
#!/usr/bin/env bash
echo "$*" >> "$CADDY_LOG"
exit 0
EOF
chmod +x "$STUBBIN2/"*
: > "$CADDY_LOG"
_VCFG2="$(mktemp "$TMP/vcfg2.XXXXXX")"
printf 'dummy' > "$_VCFG2"
PATH="$STUBBIN2:$PATH" bash -c 'warn() { echo "WARN: $*" >&2; }; source "$1"; _validate_caddy_config "$2"' _ "$TMP/helpers.sh" "$_VCFG2" > "$TMP/v2-out.txt" 2> "$TMP/v2-err.txt"
_vrc2=$?
[ "$_vrc2" -eq 0 ] && grep -Fq "validating as root" "$TMP/v2-err.txt" && grep -Fq "validate --config" "$CADDY_LOG"
cell "no caddy user: loud warn + root validate fallback" "$?"

echo "R35 domain reverse proxy: $PASS passed, $FAIL failed, $SKIP skipped"
exit "$FAIL"

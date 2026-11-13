#!/usr/bin/env bash
# R37 probe: R20-BUG-3 guard edge -- a re-run with OVPN_PROTO=tcp
# OVPN_PORT=443 on a machine that ALREADY has a domain configured and
# Caddy still serving it. The guard clears _PANEL_DOMAIN WITHOUT
# _restore_prev_panel_domain, so panel.env loses the three trust vars
# while the live Caddyfile keeps serving the old domain -- the exact
# failure mode R35-P2-1 fixed on the other failure branches.
# Runs the shipped install.sh lines VERBATIM (same extraction as
# tests/r35_domain_failpath.sh), with stubbed externals. Correct
# behavior: panel.env KEEPS the previous domain's three vars (Caddy
# is still running the old config; the proxy was declined for
# re-configuration, not stopped).
# Exit code = number of FAILs.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
PASS=0; FAIL=0
cell() { if [ "$2" -eq 0 ]; then PASS=$((PASS+1)); echo "PASS $1"; else FAIL=$((FAIL+1)); echo "FAIL $1"; fi; }
cleanup() {
    rm -rf "$TMP" /etc/caddy
}
trap cleanup EXIT

# --- fake CONFIG_DIR with a PREVIOUS domain ------------------------------
CONFIG_DIR="$TMP/config"; mkdir -p "$CONFIG_DIR"
printf 'PANEL_HOST=0.0.0.0\nPANEL_PORT=8443\nOVPN_PANEL_DOMAIN=old.example.com\nOVPN_PANEL_HTTPS=1\nOVPN_TRUSTED_PROXY=1\n' > "$CONFIG_DIR/panel.env"
printf 'DUMMY PANEL CERT' > "$CONFIG_DIR/panel-cert.pem"

# --- fake live Caddyfile: other site + old managed block -----------------
mkdir -p /etc/caddy
cat > /etc/caddy/Caddyfile <<'EOF'
other.example.com {
    respond "hi"
}
# BEGIN openvpn-sk5-panel (managed by install.sh -- change the domain with OVPN_PANEL_DOMAIN, do not hand-edit this block)
old.example.com {
    reverse_proxy https://localhost:8443 {
        transport http {
            tls_trusted_ca_certs /etc/caddy/panel-cert.pem
        }
    }
}
# END openvpn-sk5-panel
EOF
cp /etc/caddy/Caddyfile "$TMP/Caddyfile.before"

# --- stub externals --------------------------------------------------------
STUBBIN="$TMP/stubbin"; mkdir -p "$STUBBIN"
cat > "$STUBBIN/caddy" <<'EOF'
#!/usr/bin/env bash
echo "caddy $*" >> "$CADDY_CALLS"
exit 0
EOF
cat > "$STUBBIN/getent" <<'EOF'
#!/usr/bin/env bash
echo "203.0.113.7 old.example.com"
EOF
cat > "$STUBBIN/systemctl" <<'EOF'
#!/usr/bin/env bash
# caddy and the panel are both active
if [ "${1:-}" = "is-active" ]; then exit 0; fi
exit 0
EOF
chmod +x "$STUBBIN/"*
export PATH="$STUBBIN:$PATH"
export CADDY_CALLS="$TMP/caddy-calls.log"; : > "$CADDY_CALLS"

# --- extract the shipped lines verbatim ------------------------------------
sed -n '/^# R35: remember a previously configured panel domain/,/^chmod 600 "\$CONFIG_DIR\/panel.env"/p' "$ROOT/install.sh" > "$TMP/fragment-a.sh"
[ -s "$TMP/fragment-a.sh" ]; cell "fragment A extracted (prev capture + panel.env rewrite)" "$?"
sed -n '/panel domain + reverse proxy (Caddy)/,/sing-box config/p' "$ROOT/install.sh" | sed '$d' > "$TMP/fragment-b.sh"
grep -q '^_PANEL_DOMAIN=' "$TMP/fragment-b.sh"; cell "fragment B extracted (domain section)" "$?"
sed -n '/^# R35-HELPERS-BEGIN/,/^# R35-HELPERS-END/p' "$ROOT/install.sh" > "$TMP/helpers.sh"
[ -s "$TMP/helpers.sh" ]; cell "helper block extracted" "$?"

# --- harness env: re-run switching the server to TCP 443 -------------------
# No OVPN_PANEL_DOMAIN env, stdin /dev/null: the domain comes from the
# previous install. Caddy is running (stub is-active -> 0).
export CONFIG_DIR SERVER_IP=203.0.113.7 PANEL_PORT=8443
export _PUBLIC_IP=203.0.113.7
PANEL_CERT="$CONFIG_DIR/panel-cert.pem"; PANEL_KEY="$CONFIG_DIR/panel-key.pem"
CA_DIR=/etc/openvpn/server/easy-rsa; SERVER_DIR=/etc/openvpn/server
OVPN_PROTO=tcp; OVPN_PORT=443; INSTALL_ROOT=/opt/openvpn-sk5-panel
_SERVER_IP_LINE="OPENVPN_SERVER_IP=203.0.113.7"
log()  { echo "LOG: $*" >&2; }
warn() { echo "WARN: $*" >&2; }
die()  { echo "DIE: $*" >&2; exit 1; }
# shellcheck disable=SC1090
source "$TMP/helpers.sh"

# --- run the shipped lines ---------------------------------------------------
{
    source "$TMP/fragment-a.sh"
    source "$TMP/fragment-b.sh"
} </dev/null > "$TMP/run.log" 2>&1
echo "--- shipped-lines run log ---"; cat "$TMP/run.log"; echo "--- end log ---"
echo "--- panel.env after run ---"; cat "$CONFIG_DIR/panel.env"; echo "--- end panel.env ---"

# --- assertions: the guard must NOT drop the still-served domain -----------
# R37-P2-1 (fixed): the cell below asserts the FIXED behavior -- the
# guard restores the previous domain's trust vars (fix in install.sh).
# It fails on the pre-fix tree (6/7), where the guard cleared them.
grep -q "^OVPN_PANEL_DOMAIN=old.example.com$" "$CONFIG_DIR/panel.env" \
    && grep -q "^OVPN_PANEL_HTTPS=1$" "$CONFIG_DIR/panel.env" \
    && grep -q "^OVPN_TRUSTED_PROXY=1$" "$CONFIG_DIR/panel.env"
cell "R37-P2-1: panel.env keeps all three vars with the previous domain after TCP-443 guard" "$?"
diff -q "$TMP/Caddyfile.before" /etc/caddy/Caddyfile >/dev/null
cell "live Caddyfile byte-identical (proxy still serves the old domain)" "$?"
grep -Fq "域名反代需占用 443 端口，服务端当前为 TCP 443，两者冲突，本次不设反代" "$TMP/run.log"
cell "conflict warn names 443" "$?"
[ ! -s "$CADDY_CALLS" ]
cell "caddy never invoked (proxy skipped before Caddy is touched)" "$?"

echo "R37 BUG-3 guard prev-domain: $PASS passed, $FAIL failed"
exit "$FAIL"

#!/usr/bin/env bash
# R35 probe: domain failure path on a re-run with a previous domain.
# Reproduces the shipped install.sh main-body lines VERBATIM (extracted
# by marker, never retyped): the _PREV_PANEL_DOMAIN capture + the fresh
# panel.env rewrite, then the whole domain section -- with stubbed
# externals (caddy present but `caddy validate` fails; getent resolves
# the domain to this server; stdin is /dev/null = non-interactive
# re-run, no OVPN_PANEL_DOMAIN env). Asserts the observable outcome:
#   (a) panel.env KEEPS OVPN_PANEL_DOMAIN / OVPN_PANEL_HTTPS /
#       OVPN_TRUSTED_PROXY with the previous domain (R35-P2-1 fix:
#       a failed re-run must keep trusting what the still-running
#       Caddy serves);
#   (b) the live /etc/caddy/Caddyfile still serves the old domain
#       (the proxy is still live -- it was never touched);
#   (c) the warn message no longer claims "leaving Caddy stopped":
#       Caddy was never stopped, it keeps running the old config.
# FLIP (BH-03(c)): cells (a) and (c) used to pin the DEFECTIVE
# behavior (vars dropped, "leaving Caddy stopped"); they now assert
# the FIXED behavior per the R35-P2-1 fix.
# Exit code = number of FAILs.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
PASS=0; FAIL=0
cell() { if [ "$2" -eq 0 ]; then PASS=$((PASS+1)); echo "PASS $1"; else FAIL=$((FAIL+1)); echo "FAIL $1"; fi; }
cleanup() {
    rm -rf "$TMP" /etc/caddy
    [ -n "${HOST_ETC_CADDY_PREEXIST:-}" ] || true
}
trap cleanup EXIT

# --- fake CONFIG_DIR with a PREVIOUS domain ------------------------------
CONFIG_DIR="$TMP/config"; mkdir -p "$CONFIG_DIR"
printf 'PANEL_HOST=0.0.0.0\nPANEL_PORT=8443\nOVPN_PANEL_DOMAIN=old.example.com\nOVPN_PANEL_HTTPS=1\nOVPN_TRUSTED_PROXY=1\n' > "$CONFIG_DIR/panel.env"

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
            tls_trusted_ca_certs /etc/openvpn-sk5-panel/panel-cert.pem
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
# installed, but validation always fails (e.g. a broken hand-written
# site elsewhere in the Caddyfile)
if [ "${1:-}" = "validate" ]; then exit 1; fi
exit 0
EOF
cat > "$STUBBIN/getent" <<'EOF'
#!/usr/bin/env bash
# the domain resolves to this server
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

# --- extract the shipped lines verbatim ------------------------------------
sed -n '/^# R35: remember a previously configured panel domain/,/^chmod 600 "\$CONFIG_DIR\/panel.env"/p' "$ROOT/install.sh" > "$TMP/fragment-a.sh"
[ -s "$TMP/fragment-a.sh" ]; cell "fragment A extracted (prev capture + panel.env rewrite)" "$?"
sed -n '/panel domain + reverse proxy (Caddy)/,/sing-box config/p' "$ROOT/install.sh" | sed '$d' > "$TMP/fragment-b.sh"
grep -q '^_PANEL_DOMAIN=' "$TMP/fragment-b.sh"; cell "fragment B extracted (domain section)" "$?"
sed -n '/^# R35-HELPERS-BEGIN/,/^# R35-HELPERS-END/p' "$ROOT/install.sh" > "$TMP/helpers.sh"
[ -s "$TMP/helpers.sh" ]; cell "helper block extracted" "$?"

# --- harness env (what install.sh main body has set by this point) --------
export CONFIG_DIR SERVER_IP=203.0.113.7 PANEL_PORT=8443
export _PUBLIC_IP=203.0.113.7
PANEL_CERT="$CONFIG_DIR/panel-cert.pem"; PANEL_KEY="$CONFIG_DIR/panel-key.pem"
CA_DIR=/etc/openvpn/server/easy-rsa; SERVER_DIR=/etc/openvpn/server
OVPN_PROTO=udp; OVPN_PORT=1194; INSTALL_ROOT=/opt/openvpn-sk5-panel
_SERVER_IP_LINE="OPENVPN_SERVER_IP=203.0.113.7"
log()  { echo "LOG: $*" >&2; }
warn() { echo "WARN: $*" >&2; }
die()  { echo "DIE: $*" >&2; exit 1; }
# shellcheck disable=SC1090
source "$TMP/helpers.sh"

# --- run the shipped lines: non-interactive re-run, no new domain ---------
{
    source "$TMP/fragment-a.sh"
    source "$TMP/fragment-b.sh"
} </dev/null > "$TMP/run.log" 2>&1
echo "--- shipped-lines run log ---"; cat "$TMP/run.log"; echo "--- end log ---"

# --- assertions -------------------------------------------------------------
# FLIP (BH-03(c), R35-P2-1 fix): the vars are now KEPT, not dropped.
grep -q "^OVPN_PANEL_DOMAIN=old.example.com$" "$CONFIG_DIR/panel.env" \
    && grep -q "^OVPN_PANEL_HTTPS=1$" "$CONFIG_DIR/panel.env" \
    && grep -q "^OVPN_TRUSTED_PROXY=1$" "$CONFIG_DIR/panel.env"
cell "panel.env keeps all three domain vars with the previous domain after validate failure" "$?"
grep -q "old.example.com" /etc/caddy/Caddyfile
cell "live Caddyfile still serves the old domain (proxy still live)" "$?"
diff -q "$TMP/Caddyfile.before" /etc/caddy/Caddyfile >/dev/null
cell "live Caddyfile byte-identical (untouched by the failed run)" "$?"
# FLIP (BH-03(c), R35-P2-1 fix): the warn must now say Caddy keeps
# running the old config, and must not claim it was stopped.
grep -q "keeps running the old config" "$TMP/run.log" && ! grep -q "leaving Caddy stopped" "$TMP/run.log"
cell "warn says Caddy keeps running the old config (no 'leaving Caddy stopped')" "$?"
grep -q "domain old.example.com resolves to this server" "$TMP/run.log"
cell "re-run kept the previous domain (non-TTY resolve returned it)" "$?"

echo "R35 domain failpath: $PASS passed, $FAIL failed"
exit "$FAIL"

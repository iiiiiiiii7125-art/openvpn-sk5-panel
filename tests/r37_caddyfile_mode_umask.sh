#!/usr/bin/env bash
# R37 probe: the live Caddyfile's mode is never pinned. The R20-BUG-2
# fix pins every OTHER artifact caddy reads -- the cert copy
# (`install -m 0644`) and the validated temp file (`chmod 644` in
# _validate_caddy_config) -- but the live file lands via
# `cat "$_CADDY_TMP" > "$_CADDYFILE"`, which keeps the existing file's
# mode or, for a new file, the caller's umask. Under a restrictive
# umask (027/077, a common hardening choice) with the live Caddyfile
# absent (e.g. deleted by the documented uninstall, then a later
# re-install with a domain), the file lands 0640/0600 root-only and
# the caddy user cannot read it -- while `caddy validate` passed on
# the 644 temp file, so the failure is only caught at service start.
# Runs the shipped install.sh domain section VERBATIM (same extraction
# as tests/r35_domain_failpath.sh) under `umask 077`, with stubbed
# externals. Correct behavior: the live Caddyfile is 0644.
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

# --- fake CONFIG_DIR, fresh install (no previous domain) ------------------
CONFIG_DIR="$TMP/config"; mkdir -p "$CONFIG_DIR"
: > "$CONFIG_DIR/panel.env"
printf 'DUMMY PANEL CERT' > "$CONFIG_DIR/panel-cert.pem"

# --- /etc/caddy exists (package dir, 0755) but the Caddyfile is ABSENT ----
# (deleted by the documented uninstall; a later re-install recreates it)
mkdir -p /etc/caddy; chmod 755 /etc/caddy

# --- stub externals --------------------------------------------------------
STUBBIN="$TMP/stubbin"; mkdir -p "$STUBBIN"
cat > "$STUBBIN/caddy" <<'EOF'
#!/usr/bin/env bash
echo "caddy $*" >> "$CADDY_CALLS"
exit 0
EOF
cat > "$STUBBIN/getent" <<'EOF'
#!/usr/bin/env bash
echo "203.0.113.7 new.example.com"
EOF
cat > "$STUBBIN/systemctl" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "is-active" ]; then exit 0; fi
exit 0
EOF
cat > "$STUBBIN/runuser" <<'EOF'
#!/usr/bin/env bash
# no caddy user in the sandbox: fall through to the root fallback path
exit 1
EOF
cat > "$STUBBIN/id" <<'EOF'
#!/usr/bin/env bash
exit 1
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

# --- harness env: fresh domain install under umask 077 ----------------------
export CONFIG_DIR SERVER_IP=203.0.113.7 PANEL_PORT=8443
export _PUBLIC_IP=203.0.113.7
PANEL_CERT="$CONFIG_DIR/panel-cert.pem"; PANEL_KEY="$CONFIG_DIR/panel-key.pem"
CA_DIR=/etc/openvpn/server/easy-rsa; SERVER_DIR=/etc/openvpn/server
OVPN_PROTO=udp; OVPN_PORT=1194; INSTALL_ROOT=/opt/openvpn-sk5-panel
export OVPN_PANEL_DOMAIN="new.example.com"
_SERVER_IP_LINE="OPENVPN_SERVER_IP=203.0.113.7"
log()  { echo "LOG: $*" >&2; }
warn() { echo "WARN: $*" >&2; }
die()  { echo "DIE: $*" >&2; exit 1; }
# shellcheck disable=SC1090
source "$TMP/helpers.sh"

# --- run the shipped lines under a restrictive umask ------------------------
(
    umask 077
    source "$TMP/fragment-a.sh"
    source "$TMP/fragment-b.sh"
) </dev/null > "$TMP/run.log" 2>&1
echo "--- shipped-lines run log ---"; cat "$TMP/run.log"; echo "--- end log ---"
echo "--- live Caddyfile mode ---"; stat -c '%a %n' /etc/caddy/Caddyfile 2>&1; echo "--- end mode ---"

# --- assertions ---------------------------------------------------------------
# R37-P2-2 (fixed): the mode cell below asserts the FIXED behavior --
# the live Caddyfile is 0644 (fix in install.sh). It fails on the
# pre-fix tree (6/7), where the file landed 0600 under umask 077.
[ -f /etc/caddy/Caddyfile ]
cell "live Caddyfile was written" "$?"
[ "$(stat -c %a /etc/caddy/Caddyfile)" = "644" ]
cell "R37-P2-2: live Caddyfile is 0644 (caddy-readable) under umask 077" "$?"
grep -q "new.example.com" /etc/caddy/Caddyfile
cell "live Caddyfile serves the new domain" "$?"
grep -q "^OVPN_PANEL_DOMAIN=new.example.com$" "$CONFIG_DIR/panel.env"
cell "panel.env gains the new domain vars (success path reached)" "$?"

echo "R37 Caddyfile mode under umask 077: $PASS passed, $FAIL failed"
exit "$FAIL"

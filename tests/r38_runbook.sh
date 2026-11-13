#!/usr/bin/env bash
# R38 probe: docs-as-runbook execution. Takes the documented procedures
# in README.md + docs/DELIVERY.md and executes them VERBATIM, as a
# first-time operator would, on sandbox shapes (real paths for the
# uninstall/backup trees, stubbed systemctl/ufw/iptables/caddy, real
# privilege drop to nobody for the caddy-validate step):
#   R1 换域名 (DELIVERY §1.2): OVPN_PANEL_DOMAIN=<new> re-run -- the
#       Caddyfile's old managed block must be replaced, other sites
#       preserved, panel.env gains the new vars, panel RESTARTS.
#   R2 空重跑不改动 (README/DELIVERY): no env, stdin /dev/null -- the
#       previous domain is kept and the panel is NOT restarted.
#   R3 去掉反代 (README:83 / DELIVERY:54, manual steps): disable caddy,
#       delete the managed block, delete the three panel.env lines,
#       restart the panel -- then a later empty re-run must NOT
#       resurrect the domain.
#   R4 升级前备份 (DELIVERY §7): the verbatim cp -a backup command.
#   R5 卸载 (README, manual): the verbatim uninstall block -- asserts
#       what it deletes and inventories what it leaves behind.
#   R6 /etc/caddy 目录模式 (R37 fix-lane open question, FIXED in R38):
#       caddy already installed (apt skipped) + /etc/caddy ABSENT +
#       umask 077 -- the directory mode is pinned 0755, so the 0644
#       cert copy inside stays readable by caddy.
# The sed range-deletes in R3/R5 are the mechanical rendering of the
# docs' hand-edit ("删 ... 段" / "删 ... 三行"); the docs give no
# command for those edits. Exit code = number of FAILs.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
chmod 755 "$TMP"
PASS=0; FAIL=0
cell() { if [ "$2" -eq 0 ]; then PASS=$((PASS+1)); echo "PASS $1"; else FAIL=$((FAIL+1)); echo "FAIL $1"; fi; }
cleanup() {
    rm -rf "$TMP" /etc/caddy /opt/openvpn-sk5-panel /etc/openvpn-sk5-panel /etc/openvpn
    rm -f /etc/systemd/system/openvpn-sk5-panel.service /etc/systemd/system/openvpn-sk5-singbox.service
    rm -f /etc/systemd/system/openvpn-sk5-policy.service /etc/systemd/system/openvpn-sk5-healthcheck.service
    rm -f /etc/systemd/system/openvpn-sk5-healthcheck.timer
    rm -f /etc/sysctl.d/99-openvpn-sk5.conf /etc/apt/sources.list.d/caddy-stable.list
    rm -f /usr/share/keyrings/caddy-stable-archive-keyring.gpg /var/log/openvpn/sk5.log
    rmdir /var/log/openvpn 2>/dev/null || true
    rm -rf /root/panel-data-backup-*
}
trap cleanup EXIT

# --- pre-flight: none of the uninstall target paths may hold live data ---
for _p in /opt/openvpn-sk5-panel /etc/openvpn /etc/caddy /etc/systemd/system/openvpn-sk5-panel.service /etc/sysctl.d/99-openvpn-sk5.conf; do
    [ ! -e "$_p" ] || { echo "PRE-FLIGHT ABORT: $_p already exists"; exit 99; }
done

# --- stub externals --------------------------------------------------------
STUBBIN="$TMP/stubbin"; mkdir -p "$STUBBIN"
cat > "$STUBBIN/caddy" <<'EOF'
#!/usr/bin/env bash
# Faithful validate stand-in: exit 0 iff the tls_trusted_ca_certs file
# the config references is readable BY THIS USER (runs as nobody via
# the runuser stub, so a 0700 /etc/caddy makes it fail like real caddy).
_cfg=""
while [ $# -gt 0 ]; do case "$1" in --config) _cfg="$2"; shift 2;; *) shift;; esac; done
_cert="$(grep -E 'tls_trusted_ca_certs' "$_cfg" 2>/dev/null | awk '{print $2}' | head -1)"
[ -n "$_cert" ] && [ -r "$_cert" ] && [ -r "$_cfg" ]
EOF
cat > "$STUBBIN/getent" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "passwd" ]; then echo "caddy:x:1000:1000::/var/lib/caddy:/usr/sbin/nologin"; exit 0; fi
if [ "${1:-}" = "hosts" ]; then echo "203.0.113.7 ${2:-}"; exit 0; fi
exit 2
EOF
cat > "$STUBBIN/systemctl" <<'EOF'
#!/usr/bin/env bash
echo "systemctl $*" >> "$SYS_CALLS"
if [ "${1:-}" = "is-active" ]; then exit 0; fi
exit 0
EOF
cat > "$STUBBIN/runuser" <<'EOF'
#!/usr/bin/env bash
# Translate `-u caddy` to `-u nobody` (no caddy user in the sandbox)
# and really drop privileges, so readability is tested for real.
args=()
while [ $# -gt 0 ]; do
    if [ "$1" = "-u" ]; then args+=("-u" "nobody"); shift 2; continue; fi
    args+=("$1"); shift
done
exec /usr/sbin/runuser "${args[@]}"
EOF
cat > "$STUBBIN/id" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = "caddy" ]; then exit 0; fi
exec /usr/bin/id "$@"
EOF
cat > "$STUBBIN/ufw" <<'EOF'
#!/usr/bin/env bash
echo "ufw $*" >> "$SYS_CALLS"
if [ "${1:-}" = "status" ]; then echo "Status: inactive"; exit 0; fi
exit 0
EOF
cat > "$STUBBIN/iptables" <<'EOF'
#!/usr/bin/env bash
echo "iptables $*" >> "$SYS_CALLS"
exit 0
EOF
cat > "$STUBBIN/netfilter-persistent" <<'EOF'
#!/usr/bin/env bash
echo "netfilter-persistent $*" >> "$SYS_CALLS"
exit 0
EOF
chmod 755 "$TMP" "$STUBBIN"
chmod 755 "$STUBBIN/"*
export PATH="$STUBBIN:$PATH"
export SYS_CALLS="$TMP/sys-calls.log"; : > "$SYS_CALLS"

# --- extract the shipped lines verbatim (same as R37 probes) ---------------
sed -n '/^# R35: remember a previously configured panel domain/,/^chmod 600 "\$CONFIG_DIR\/panel.env"/p' "$ROOT/install.sh" > "$TMP/fragment-a.sh"
[ -s "$TMP/fragment-a.sh" ]; cell "fragment A extracted (prev capture + panel.env rewrite)" "$?"
sed -n '/panel domain + reverse proxy (Caddy)/,/sing-box config/p' "$ROOT/install.sh" | sed '$d' > "$TMP/fragment-b.sh"
grep -q '^_PANEL_DOMAIN=' "$TMP/fragment-b.sh"; cell "fragment B extracted (domain section)" "$?"
sed -n '/^# R35-HELPERS-BEGIN/,/^# R35-HELPERS-END/p' "$ROOT/install.sh" > "$TMP/helpers.sh"
[ -s "$TMP/helpers.sh" ]; cell "helper block extracted" "$?"

# --- shared harness env -----------------------------------------------------
CONFIG_DIR="$TMP/config0"; mkdir -p "$CONFIG_DIR"
export CONFIG_DIR SERVER_IP=203.0.113.7 PANEL_PORT=8443
export _PUBLIC_IP=203.0.113.7
PANEL_CERT="$CONFIG_DIR/panel-cert.pem"; PANEL_KEY="$CONFIG_DIR/panel-key.pem"
CA_DIR=/etc/openvpn/server/easy-rsa; SERVER_DIR=/etc/openvpn/server
OVPN_PROTO=udp; OVPN_PORT=1194; INSTALL_ROOT=/opt/openvpn-sk5-panel
export OVPN_PROTO OVPN_PORT
_SERVER_IP_LINE="OPENVPN_SERVER_IP=203.0.113.7"
log()  { echo "LOG: $*" >&2; }
warn() { echo "WARN: $*" >&2; }
die()  { echo "DIE: $*" >&2; exit 1; }
# shellcheck disable=SC1090
source "$TMP/helpers.sh"
run_fragments() { # run_fragments <stdin-file> -- runs A+B with given stdin
    # PANEL_CERT/PANEL_KEY are derived from the CURRENT CONFIG_DIR:
    # sections re-point CONFIG_DIR per scenario, so re-derive here.
    PANEL_CERT="$CONFIG_DIR/panel-cert.pem"; PANEL_KEY="$CONFIG_DIR/panel-key.pem"
    : > "$SYS_CALLS"
    source "$TMP/fragment-a.sh"
    source "$TMP/fragment-b.sh"
}

# --- R1: domain change ------------------------------------------------------
echo "=== R1: domain change ==="
CONFIG_DIR="$TMP/config"; mkdir -p "$CONFIG_DIR"
printf 'DUMMY PANEL CERT' > "$CONFIG_DIR/panel-cert.pem"
printf 'DUMMY PANEL KEY' > "$CONFIG_DIR/panel-key.pem"
export CONFIG_DIR
mkdir -p /etc/caddy; chmod 755 /etc/caddy
cat > /etc/caddy/Caddyfile <<'EOF'
other.example.org {
    reverse_proxy 127.0.0.1:8080
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
# Pre-seed panel.env WITH the old domain (previous install's file).
printf 'PANEL_HOST=0.0.0.0\nPANEL_PORT=8443\nOVPN_PANEL_DOMAIN=old.example.com\nOVPN_PANEL_HTTPS=1\nOVPN_TRUSTED_PROXY=1\n' > "$CONFIG_DIR/panel.env"
export OVPN_PANEL_DOMAIN="new.example.com"
run_fragments /dev/null </dev/null > "$TMP/r1.log" 2>&1
grep -q "new.example.com" /etc/caddy/Caddyfile
cell "R1: Caddyfile serves the NEW domain" "$?"
grep -q "old.example.com" /etc/caddy/Caddyfile
cell "R1: old managed block is gone from the Caddyfile" "$((! $?))"
grep -q "other.example.org" /etc/caddy/Caddyfile
cell "R1: other site content preserved" "$?"
grep -q "^OVPN_PANEL_DOMAIN=new.example.com$" "$CONFIG_DIR/panel.env"
cell "R1: panel.env gains the new domain vars" "$?"
grep -q "restart openvpn-sk5-panel" "$SYS_CALLS"
cell "R1: panel RESTARTS on domain change (DELIVERY: panels auto-restarts)" "$?"
grep -q "reload caddy" "$SYS_CALLS"
cell "R1: caddy reloaded (not restarted) for the new config" "$?"
grep -q "https://new.example.com" "$TMP/r1.log"
cell "R1: log names the new domain" "$?"

# --- R2: empty re-run keeps the domain, panel NOT restarted ------------------
echo "=== R2: empty re-run ==="
unset OVPN_PANEL_DOMAIN
run_fragments /dev/null </dev/null > "$TMP/r2.log" 2>&1
grep -q "^OVPN_PANEL_DOMAIN=new.example.com$" "$CONFIG_DIR/panel.env"
cell "R2: empty re-run keeps the configured domain" "$?"
grep -q "restart openvpn-sk5-panel" "$SYS_CALLS"
cell "R2: panel NOT restarted when the domain is unchanged" "$((! $?))"
grep -q "new.example.com" /etc/caddy/Caddyfile
cell "R2: Caddyfile still serves the domain after the empty re-run" "$?"

# --- R3: manual proxy removal (README:83 / DELIVERY:54, verbatim steps) -----
echo "=== R3: manual proxy removal ==="
# The docs' hand-edits rendered mechanically with sed (disclosed):
systemctl disable --now caddy >> "$SYS_CALLS" 2>&1
sed -i '/^# BEGIN openvpn-sk5-panel/,/^# END openvpn-sk5-panel/d' /etc/caddy/Caddyfile
sed -i '/^OVPN_PANEL_DOMAIN=/d; /^OVPN_PANEL_HTTPS=/d; /^OVPN_TRUSTED_PROXY=/d' "$CONFIG_DIR/panel.env"
systemctl restart openvpn-sk5-panel >> "$SYS_CALLS" 2>&1
grep -q "openvpn-sk5-panel" /etc/caddy/Caddyfile
cell "R3: managed block is gone from the Caddyfile" "$((! $?))"
grep -q "other.example.org" /etc/caddy/Caddyfile
cell "R3: other site content still preserved after removal" "$?"
grep -qE '^OVPN_PANEL_DOMAIN=|^OVPN_PANEL_HTTPS=|^OVPN_TRUSTED_PROXY=' "$CONFIG_DIR/panel.env"
cell "R3: all three trust vars are gone from panel.env" "$((! $?))"
grep -q "disable --now caddy" "$SYS_CALLS"
cell "R3: caddy disabled per the docs" "$?"
# Removal must STICK: a later empty re-run must not resurrect the domain.
unset OVPN_PANEL_DOMAIN
run_fragments /dev/null </dev/null > "$TMP/r3b.log" 2>&1
grep -qE '^OVPN_PANEL_DOMAIN=' "$CONFIG_DIR/panel.env"
cell "R3: empty re-run after removal does NOT resurrect the domain" "$((! $?))"
grep -q "openvpn-sk5-panel" /etc/caddy/Caddyfile
cell "R3: empty re-run after removal does NOT re-add the managed block" "$((! $?))"

# --- R4: upgrade backup (DELIVERY §7, verbatim command) ----------------------
echo "=== R4: upgrade backup ==="
mkdir -p /opt/openvpn-sk5-panel/panel/data
printf 'FAKE-PANEL-DB' > /opt/openvpn-sk5-panel/panel/data/panel.db
printf 'FAKE-QUEUE' > /opt/openvpn-sk5-panel/panel/data/agent_queue.json
cp -a /opt/openvpn-sk5-panel/panel/data "/root/panel-data-backup-$(date +%Y%m%d)"
_backup="/root/panel-data-backup-$(date +%Y%m%d)"
[ -f "$_backup/panel.db" ] && [ -f "$_backup/agent_queue.json" ]
cell "R4: verbatim backup command copies panel.db + agent_queue.json" "$?"
cmp -s /opt/openvpn-sk5-panel/panel/data/panel.db "$_backup/panel.db"
cell "R4: backup is byte-identical" "$?"

# --- R5: uninstall (README, verbatim block) -----------------------------------
echo "=== R5: uninstall ==="
mkdir -p /etc/openvpn-sk5-panel /etc/openvpn/server/easy-rsa/pki /var/log/openvpn
printf 'x' > /etc/openvpn-sk5-panel/admin.pass
printf 'OVPN_PANEL_DOMAIN=gone.example.com\nOVPN_PANEL_HTTPS=1\nOVPN_TRUSTED_PROXY=1\n' > /etc/openvpn-sk5-panel/panel.env
printf 'CERT' > /etc/openvpn-sk5-panel/panel-cert.pem
printf 'KEY' > /etc/openvpn-sk5-panel/panel-key.pem
printf 'SK5' > /etc/openvpn-sk5-panel/sk5.json
printf 'SB' > /etc/openvpn-sk5-panel/sing-box.json
printf 'server.conf' > /etc/openvpn/server/server.conf
printf 'CA' > /etc/openvpn/server/easy-rsa/pki/ca.crt
printf 'net.ipv4.ip_forward=1\n' > /etc/sysctl.d/99-openvpn-sk5.conf
printf 'deb caddy\n' > /etc/apt/sources.list.d/caddy-stable.list
printf 'KEYRING' > /usr/share/keyrings/caddy-stable-archive-keyring.gpg
for _u in openvpn-sk5-panel openvpn-sk5-singbox openvpn-sk5-policy openvpn-sk5-healthcheck; do
    printf '[Unit]\n' > "/etc/systemd/system/$_u.service"
done
printf '[Unit]\n' > /etc/systemd/system/openvpn-sk5-healthcheck.timer
cat > /etc/caddy/Caddyfile <<'EOF'
other.example.org {
    reverse_proxy 127.0.0.1:8080
}
# BEGIN openvpn-sk5-panel (managed by install.sh -- change the domain with OVPN_PANEL_DOMAIN, do not hand-edit this block)
gone.example.com {
    reverse_proxy https://localhost:8443 {
        transport http {
            tls_trusted_ca_certs /etc/caddy/panel-cert.pem
        }
    }
}
# END openvpn-sk5-panel
EOF
printf 'CERTCOPY' > /etc/caddy/panel-cert.pem
: > "$SYS_CALLS"
# Verbatim README uninstall block (stdin "y" for the read prompt; the
# hand-edit of the Caddyfile segment is rendered with sed, disclosed).
echo y | bash -s <<'UNINSTALL_EOF'
read -r -p "确认卸载 OpenVPN + SK5 面板并删除 CA 与全部用户证书？[y/N] " ans
[ "$ans" = y ] || [ "$ans" = Y ] || exit 1
systemctl disable --now openvpn-sk5-panel openvpn-sk5-singbox openvpn-server@server
systemctl disable --now openvpn-sk5-policy.service openvpn-sk5-healthcheck.timer
systemctl disable --now caddy
sed -i '/^# BEGIN openvpn-sk5-panel/,/^# END openvpn-sk5-panel/d' /etc/caddy/Caddyfile
rm -rf /opt/openvpn-sk5-panel /etc/openvpn-sk5-panel
rm -rf /etc/openvpn/server
rm -f /etc/systemd/system/openvpn-sk5-panel.service /etc/systemd/system/openvpn-sk5-singbox.service
rm -f /etc/systemd/system/openvpn-sk5-policy.service /etc/systemd/system/openvpn-sk5-healthcheck.service /etc/systemd/system/openvpn-sk5-healthcheck.timer
systemctl daemon-reload
iptables -D FORWARD -i tun0 -s 10.8.0.0/24 -o eth0 -j ACCEPT
iptables -D FORWARD -i eth0 -d 10.8.0.0/24 -o tun0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
ufw delete allow 1194/udp
ufw delete allow 8443/tcp
ufw delete allow 80/tcp
ufw delete allow 443/tcp
netfilter-persistent save
UNINSTALL_EOF
[ ! -e /opt/openvpn-sk5-panel ] && [ ! -e /etc/openvpn-sk5-panel ] && [ ! -e /etc/openvpn/server ]
cell "R5: uninstall removes /opt, /etc/openvpn-sk5-panel, /etc/openvpn/server" "$?"
[ ! -e /etc/systemd/system/openvpn-sk5-panel.service ] && [ ! -e /etc/systemd/system/openvpn-sk5-healthcheck.timer ]
cell "R5: uninstall removes the systemd units" "$?"
grep -q "openvpn-sk5-panel" /etc/caddy/Caddyfile
cell "R5: managed block is gone from the Caddyfile" "$((! $?))"
grep -q "other.example.org" /etc/caddy/Caddyfile
cell "R5: other site content preserved by the uninstall" "$?"
echo "--- R5 leftovers (not mentioned in the docs) ---"
ls -la /etc/caddy/ /etc/sysctl.d/99-openvpn-sk5.conf /etc/apt/sources.list.d/caddy-stable.list /usr/share/keyrings/caddy-stable-archive-keyring.gpg /var/log/openvpn/ 2>&1
echo "--- end leftovers ---"

# --- R6: /etc/caddy dir mode (R37 open question, FIXED in R38) --------------
# BH-03(c) disclosure: these cells assert the FIXED behavior -- the
# directory is pinned 0755, the cert copy is readable by the caddy
# stand-in, validate passes, and a second re-run stays green. On the
# pre-fix tree all five fail (the auditor's R6 cells asserted the
# defect signature instead; baseline run before the fix: 30/30 with
# the defect signature passing).
echo "=== R6: /etc/caddy dir mode, caddy pre-installed + dir absent + umask 077 ==="
rm -rf /etc/caddy
CONFIG_DIR="$TMP/config6"; mkdir -p "$CONFIG_DIR"
printf 'DUMMY PANEL CERT' > "$CONFIG_DIR/panel-cert.pem"
printf 'DUMMY PANEL KEY' > "$CONFIG_DIR/panel-key.pem"
export CONFIG_DIR
printf 'PANEL_HOST=0.0.0.0\nPANEL_PORT=8443\nOVPN_PANEL_DOMAIN=prev.example.com\nOVPN_PANEL_HTTPS=1\nOVPN_TRUSTED_PROXY=1\n' > "$CONFIG_DIR/panel.env"
export OVPN_PANEL_DOMAIN="prev.example.com"
(
    umask 077
    run_fragments /dev/null </dev/null > "$TMP/r6.log" 2>&1
)
echo "--- R6 run log ---"; cat "$TMP/r6.log"; echo "--- end log ---"
echo "--- R6 /etc/caddy mode ---"; stat -c '%a %n' /etc/caddy /etc/caddy/panel-cert.pem /etc/caddy/Caddyfile 2>&1; echo "--- end mode ---"
[ "$(stat -c %a /etc/caddy 2>/dev/null)" = "755" ]
cell "R6: /etc/caddy is 0755 after the run under umask 077 (mode pinned)" "$?"
runuser -u nobody -- test -r /etc/caddy/panel-cert.pem 2>/dev/null
cell "R6: caddy-stand-in (nobody) CAN read the cert copy through the 0755 dir" "$?"
grep -q "reverse proxy configured" "$TMP/r6.log"
cell "R6: validate-as-caddy PASSES (proxy configured, no validate-failure warn)" "$?"
grep -q "^OVPN_PANEL_DOMAIN=prev.example.com$" "$CONFIG_DIR/panel.env" && grep -q "prev.example.com" /etc/caddy/Caddyfile
cell "R6: domain configured end-to-end (panel.env vars + Caddyfile serves the domain)" "$?"
# Stickiness, fixed direction: a second identical re-run stays green.
(
    umask 077
    run_fragments /dev/null </dev/null > "$TMP/r6b.log" 2>&1
)
grep -q "reverse proxy configured" "$TMP/r6b.log" && [ "$(stat -c %a /etc/caddy 2>/dev/null)" = "755" ]
cell "R6: second re-run succeeds identically (mode stays 0755, validate passes)" "$?"

echo "R38 runbook: $PASS passed, $FAIL failed"
exit "$FAIL"

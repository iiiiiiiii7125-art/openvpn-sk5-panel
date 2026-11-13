#!/usr/bin/env bash
# openvpn-sk5-panel -- one-command installer.
#
# Target: a fresh Debian 12 / Ubuntu 22.04 / 24.04 server.
# Installs, in order: apt deps -> sing-box 1.11.15 (+ tun2socks 2.7.0
# fallback) -> repo tree to /opt/openvpn-sk5-panel -> PKI + server.conf
# (via core/openvpn_manager.py) -> direct-mode sing-box config ->
# systemd units -> start everything -> print panel URL + admin password.
#
# Idempotent: re-running keeps the CA, server cert, admin password and
# panel TLS cert, re-renders configs deterministically and restarts the
# services. Safe to re-run after a failed first attempt.
#
# Usage:
#   bash install.sh            # defaults: OpenVPN UDP 1194
#   OVPN_PROTO=tcp OVPN_PORT=443 bash install.sh
#
# Optional env (see README.md for the full list):
#   OVPN_PROTO / OVPN_PORT / OVPN_SUBNET / OVPN_DNS
#   SINGBOX_SHA256 / TUN2SOCKS_SHA256   # override the pinned hash (strict 64-hex);
#                                        # default is the double-anchor pinned hash below
#
# Exit codes: 0 ok; 1 any failure (including sha256 mismatch).
set -euo pipefail

# ------------------------------------------------------------------ constants
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="/opt/openvpn-sk5-panel"
CONFIG_DIR="/etc/openvpn-sk5-panel"
CA_DIR="/etc/openvpn/server/easy-rsa"
SERVER_DIR="/etc/openvpn/server"
PANEL_PORT=8443

# R3-BUG-6: log()/warn()/die() MUST be defined before the R2-BUG-16
# inherit block below -- that block calls log() when a deployed
# server.conf exists, and under `set -euo pipefail` calling an
# undefined function exits 127 and aborts every default re-run
# (live-verify-R3 §10: "install.sh: line 81: log: command not found").
log()  { echo "[install] $*"; }
warn() { echo "[install] WARN: $*" >&2; }
die()  { echo "[install] ERROR: $*" >&2; exit 1; }

SINGBOX_VERSION="1.11.15"          # last 1.11.x line (pinned, do not float)
TUN2SOCKS_VERSION="2.7.0"          # latest stable tun2socks (pinned)
# Pinned sha256 of the release assets (BUG-2). Neither upstream
# publishes a sha256 manifest (SagerNet/sing-box v1.11.15 and
# xjasonlyu/tun2socks v2.7.0 have no checksums.txt / SHA256SUMS.txt),
# so "manifest or die" meant a fresh install could never succeed.
# These hashes were derived 2026-11-12 by double-anchor verification:
#   1. the asset downloaded twice independently -- release download URL
#      and GitHub API asset download (Accept: application/octet-stream)
#      -- and the two files hashed identically;
#   2. the tarball binary and the same release's .deb binary compared
#      byte-for-byte identical (amd64 a85f1a82...2ab81,
#      arm64 6f907572...67612d);
#   3. the amd64 binary self-reports "sing-box version 1.11.15"
#      (go1.24.4, revision bc35aca01704497c179da1a03e45ad8e32f1a51b)
#      and tun2socks self-reports "tun2socks-2.7.0".
# Bumping SINGBOX_VERSION / TUN2SOCKS_VERSION REQUIRES re-pinning here:
# verification still fails closed (a stale pin = sha256 mismatch = stop).
# The $SINGBOX_SHA256 / $TUN2SOCKS_SHA256 env overrides still win over
# the pins (operator-supplied hash, strict 64-hex).
SINGBOX_SHA256_AMD64="950af37eb2d7e55dddae34a18411cd617303fd99d2dc75bc76b6dd9fcd97d9c5"
SINGBOX_SHA256_ARM64="20a6a9cd259a95411599f811a5066513a98db63705a51121252ad27daf96c029"
TUN2SOCKS_SHA256_AMD64="a612baa287a3b6de6221f74fd02b442a50888508227ecf51e1288a5ccbb77381"
TUN2SOCKS_SHA256_ARM64="3931476c9cfa8fa236d23aeaf36767df0eb27cc11ecaab699faba57744450f49"
SINGBOX_BASE="https://github.com/SagerNet/sing-box/releases/download/v${SINGBOX_VERSION}"
TUN2SOCKS_BASE="https://github.com/xjasonlyu/tun2socks/releases/download/v${TUN2SOCKS_VERSION}"

OVPN_PROTO_SET=0; [ -n "${OVPN_PROTO+x}" ] && OVPN_PROTO_SET=1
OVPN_PORT_SET=0; [ -n "${OVPN_PORT+x}" ] && OVPN_PORT_SET=1
OVPN_PROTO="${OVPN_PROTO:-udp}"
OVPN_PORT="${OVPN_PORT:-}"
# R2-BUG-16: a re-run over a deployed server must inherit its entry
# port. The defaults above (udp/1194) would otherwise make every
# re-run on a TCP deployment die in P01 ("entry port is fixed at
# creation", live-verify-R2 §8). Inherit per-field from the deployed
# server.conf unless the operator explicitly set OVPN_PROTO /
# OVPN_PORT in the environment; explicit env still wins.
if [ -f "$SERVER_DIR/server.conf" ]; then
    _OLD_PROTO="$(awk '/^proto /{print $2; exit}' "$SERVER_DIR/server.conf" 2>/dev/null || true)"
    _OLD_PORT="$(awk '/^port /{print $2; exit}' "$SERVER_DIR/server.conf" 2>/dev/null || true)"
    if [ "$OVPN_PROTO_SET" -eq 0 ] && [ -n "$_OLD_PROTO" ]; then
        OVPN_PROTO="$_OLD_PROTO"; INHERITED_PORT=1
    fi
    if [ "$OVPN_PORT_SET" -eq 0 ] && [ -n "$_OLD_PORT" ]; then
        OVPN_PORT="$_OLD_PORT"; INHERITED_PORT=1
    fi
    if [ -n "${INHERITED_PORT:-}" ]; then
        log "inheriting deployed entry port from $SERVER_DIR/server.conf (proto=$OVPN_PROTO port=$OVPN_PORT; explicit OVPN_PROTO/OVPN_PORT still wins)"
    fi
fi
OVPN_SUBNET="${OVPN_SUBNET:-10.8.0.0/24}"
OVPN_DNS="${OVPN_DNS:-1.1.1.1}"

WORKDIR="$(mktemp -d /tmp/ovpn-sk5-install.XXXXXX)"

# ------------------------------------------------------------------ helpers
# (log/warn/die are defined above the constants -- see R3-BUG-6 --
# the inherit block calls log() before this section runs.)

cleanup() { rm -rf "$WORKDIR"; }
trap cleanup EXIT

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "required command missing: $1"
}

# Never touch a live FLMX deployment. install.sh only ever writes to
# INSTALL_ROOT, CONFIG_DIR, /etc/openvpn/server* and /etc/systemd/system;
# if any of those resolves to /root/flmx-panel (or the checkout itself
# lives inside it), refuse outright instead of destroying it.
assert_not_flmx_target() {
    local target="$1" resolved=""
    resolved="$(readlink -f "$target" 2>/dev/null || echo "$target")"
    if [ "$resolved" = "/root/flmx-panel" ] || [[ "$resolved" == /root/flmx-panel/* ]]; then
        die "refusing: install target $target resolves to the live FLMX deployment /root/flmx-panel"
    fi
}

primary_ip() {
    ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}' \
        || hostname -I 2>/dev/null | awk '{print $1}'
}

# ------------------------------------------------------------------ preflight
[ "$(id -u)" -eq 0 ] || die "run as root (sudo bash install.sh)"
need_cmd curl; need_cmd systemctl; need_cmd ip; need_cmd iptables
need_cmd openssl; need_cmd python3

# OS gate: only the three tested targets, unless explicitly overridden.
if [ -f /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-}-${VERSION_ID:-}" in
        debian-12|ubuntu-22.04|ubuntu-24.04) log "OS: ${ID} ${VERSION_ID} (supported)" ;;
        *)
            if [ "${ALLOW_UNSUPPORTED_OS:-0}" = "1" ]; then
                warn "unsupported OS ${ID:-?} ${VERSION_ID:-?}, continuing (ALLOW_UNSUPPORTED_OS=1)"
            else
                die "unsupported OS ${ID:-?} ${VERSION_ID:-?}; target is Debian 12 / Ubuntu 22.04 / 24.04 (ALLOW_UNSUPPORTED_OS=1 to override)"
            fi
            ;;
    esac
else
    die "/etc/os-release not found; cannot confirm Debian/Ubuntu target"
fi

# Safety assertions (destructive-op guard): the install target must not
# be an existing deployment directory, especially /root/flmx-panel.
assert_not_flmx_target "$SCRIPT_DIR"
assert_not_flmx_target "$PWD"
assert_not_flmx_target "$INSTALL_ROOT"
assert_not_flmx_target "$CONFIG_DIR"
assert_not_flmx_target "$SERVER_DIR"
if [ -d /root/flmx-panel ]; then
    log "detected existing FLMX deployment at /root/flmx-panel -- it will not be touched"
fi

# OpenVPN proto/port validation + defaults (TCP mode defaults to 443).
case "$OVPN_PROTO" in
    udp) [ -n "$OVPN_PORT" ] || OVPN_PORT=1194 ;;
    tcp) [ -n "$OVPN_PORT" ] || OVPN_PORT=443 ;;
    *) die "OVPN_PROTO must be udp or tcp, got '$OVPN_PROTO'" ;;
esac
case "$OVPN_PORT" in
    ''|*[!0-9]*|0) die "OVPN_PORT must be a port number 1-65535, got '$OVPN_PORT'" ;;
esac
[ "$OVPN_PORT" -ge 1 ] && [ "$OVPN_PORT" -le 65535 ] || die "OVPN_PORT out of range: $OVPN_PORT"
# R12-P2-6: OVPN_SUBNET was never validated -- `OVPN_SUBNET=bogus`
# installed "successfully" (exit 0) with three bogus iptables rules
# while the real 10.8.0.0/24 NAT/FORWARD was missing, silently
# breaking direct egress. Validate it as a strict IPv4 CIDR here,
# next to the proto/port checks above, before anything is written.
# OVPN_DNS gets the core `_validate_dns` charset check only (same
# rule as core/openvpn_manager.py:940-946): a bare IP/hostname is
# fine, whitespace or shell metacharacters are not. python3 is
# already a preflight requirement (need_cmd python3 above).
_rc=0
python3 - "$OVPN_SUBNET" "$OVPN_DNS" <<'PYEOF' || _rc=$?
import ipaddress
import sys
subnet, dns = sys.argv[1], sys.argv[2]
try:
    # A bare address without a prefix parses as /32 -- a single host,
    # not a subnet, and would silently break NAT for the whole VPN
    # range; require the prefix explicitly.
    if "/" not in subnet:
        raise ValueError("no prefix")
    ipaddress.IPv4Network(subnet, strict=True)
except ValueError:
    sys.exit(1)
if not dns or any(c in dns for c in " \t\"';&|<>$`\\"):
    sys.exit(2)
PYEOF
case "$_rc" in
    0) ;;
    1) die "OVPN_SUBNET must be a CIDR like 10.8.0.0/24, got '$OVPN_SUBNET'" ;;
    2) die "OVPN_DNS must be a bare IP or hostname without whitespace or shell metacharacters, got '$OVPN_DNS'" ;;
    *) die "OVPN_SUBNET/OVPN_DNS validation failed (rc=$_rc)" ;;
esac
# R13-P2-6: core renders a hard-coded 10.8.0.0/24 (render_server_conf
# has no subnet parameter), so a legal-but-different OVPN_SUBNET would
# pass the CIDR check above yet silently misalign NAT/FORWARD with the
# served subnet and blackhole direct egress. Refuse anything but the
# fixed value -- do not let a valid CIDR pretend the subnet is tunable.
if [ "$OVPN_SUBNET" != "10.8.0.0/24" ]; then
    die "OVPN_SUBNET must be 10.8.0.0/24 (core serves this fixed subnet; got '$OVPN_SUBNET' -- NAT rules would not match the served subnet and direct egress would break)"
fi
if [ "$OVPN_PROTO" = "tcp" ]; then
    warn "TCP mode: TCP-over-TCP retransmission amplification applies (see README.md)"
fi

ARCH="$(dpkg --print-architecture 2>/dev/null || uname -m)"
case "$ARCH" in
    amd64|x86_64) ARCH="amd64" ;;
    arm64|aarch64) ARCH="arm64" ;;
    *) die "unsupported architecture: $ARCH (only amd64/arm64 have pinned release assets)" ;;
esac
log "arch: $ARCH; OpenVPN: proto=$OVPN_PROTO port=$OVPN_PORT subnet=$OVPN_SUBNET dns=$OVPN_DNS"

# Lane-contract preflight: fail fast and name exactly what is missing.
# (core/easyrsa.sh is soft: the PKI step falls back to direct easy-rsa
# calls if it is absent. Everything else below is a hard requirement.)
[ -f "$SCRIPT_DIR/panel/requirements.txt" ] \
    || die "panel lane missing: $SCRIPT_DIR/panel/requirements.txt not found"
PANEL_ENTRY=""
for _cand in app.py main.py server.py; do
    if [ -f "$SCRIPT_DIR/panel/$_cand" ]; then PANEL_ENTRY="$_cand"; break; fi
done
[ -n "$PANEL_ENTRY" ] \
    || die "panel lane missing: no panel entrypoint (app.py|main.py|server.py) in $SCRIPT_DIR/panel"
log "panel entrypoint: panel/$PANEL_ENTRY"
[ -f "$SCRIPT_DIR/core/easyrsa.sh" ] \
    || warn "core/easyrsa.sh not found -- PKI step will use the built-in easy-rsa fallback"
[ -f "$SCRIPT_DIR/core/openvpn_manager.py" ] \
    || die "core lane missing: $SCRIPT_DIR/core/openvpn_manager.py not found"
[ -f "$SCRIPT_DIR/egress/sing-box.json.template" ] \
    || warn "egress/sing-box.json.template not found -- direct-mode config will be written from the built-in default"
[ -f "$SCRIPT_DIR/egress/policy-routing.sh" ] \
    || warn "egress/policy-routing.sh not found -- SK5 enable/disable will fail until the egress lane lands"
[ -f "$SCRIPT_DIR/systemd/openvpn-sk5-panel.service" ] \
    || die "missing systemd unit: $SCRIPT_DIR/systemd/openvpn-sk5-panel.service"
[ -f "$SCRIPT_DIR/systemd/openvpn-sk5-singbox.service" ] \
    || die "missing systemd unit: $SCRIPT_DIR/systemd/openvpn-sk5-singbox.service"
[ -f "$SCRIPT_DIR/systemd/openvpn-sk5-policy.service" ] \
    || die "missing systemd unit: $SCRIPT_DIR/systemd/openvpn-sk5-policy.service"
[ -f "$SCRIPT_DIR/systemd/openvpn-sk5-healthcheck.service" ] \
    || die "missing systemd unit: $SCRIPT_DIR/systemd/openvpn-sk5-healthcheck.service"
[ -f "$SCRIPT_DIR/systemd/openvpn-sk5-healthcheck.timer" ] \
    || die "missing systemd unit: $SCRIPT_DIR/systemd/openvpn-sk5-healthcheck.timer"

# ------------------------------------------------------------------ apt deps
# R8-BUG-2: iptables-persistent MUST NOT be installed unconditionally.
# On Debian it conflicts with ufw: apt silently REMOVES the ufw
# package -- and with it every firewall rule the user has
# (live-verify-R8 §17: a fresh install destroyed 2005 rules) -- and
# the ufw block below then silently skips because `command -v ufw`
# fails, so the install ends with no firewall at all and no warning.
# What the package is for: it provides netfilter-persistent, the only
# thing that makes the NAT/FORWARD rules added below survive a reboot
# (see the save step). The boot-time policy service
# (openvpn-sk5-policy.service) only restores the table-100 policy
# route, NOT those iptables rules -- so the package is NOT redundant
# and is still installed when no firewall manager owns the box. When
# ufw is present (package installed, whether or not it is currently
# active -- the apt conflict triggers on the package, not on its
# state), the package is skipped, the ports are opened via ufw
# instead, and the install says so loudly. A post-apt assertion
# verifies ufw is still installed: if anything ever removes it again,
# the install dies here instead of continuing over a destroyed
# firewall.
_UFW_INSTALLED=0
if dpkg-query -W -f='${Status}' ufw 2>/dev/null | grep -q "install ok installed" \
    || command -v ufw >/dev/null 2>&1; then
    _UFW_INSTALLED=1
fi
_APT_EXTRA=""
if [ "$_UFW_INSTALLED" -eq 1 ]; then
    log "ufw is installed -- skipping iptables-persistent (it conflicts with ufw; installing it would uninstall ufw and destroy its rules)"
    log "firewall ports will be opened via ufw; NAT/FORWARD rules are applied live but will NOT survive a reboot on this host (no netfilter-persistent) -- re-run install.sh after a reboot to re-apply them"
else
    _APT_EXTRA="iptables-persistent"
fi
log "installing apt packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# shellcheck disable=SC2086 -- _APT_EXTRA is intentionally word-split:
# it is either empty (ufw host) or the single word iptables-persistent.
apt-get install -y -qq --no-install-recommends \
    openvpn easy-rsa ${_APT_EXTRA} curl jq python3 python3-pip \
    iproute2 unzip ca-certificates openssl procps \
    || die "apt install failed"
if [ "$_UFW_INSTALLED" -eq 1 ]; then
    if ! command -v ufw >/dev/null 2>&1 \
        && ! dpkg-query -W -f='${Status}' ufw 2>/dev/null | grep -q "install ok installed"; then
        die "ufw was installed before the apt step but is gone afterwards -- refusing to continue over a destroyed firewall (see the apt output above)"
    fi
    log "ufw still installed after apt step (iptables-persistent skipped as intended)"
fi
modprobe tun 2>/dev/null || warn "modprobe tun failed (usually already built-in); continuing"

# ------------------------------------------------------------------ downloads
# sha256 verification (fail closed, same resolution order as
# agent/agent.py _expected_sha256, plus a pinned default):
#   1. $SINGBOX_SHA256 / $TUN2SOCKS_SHA256 env override, if set (strict).
#   2. Otherwise the pinned hash for this version+arch (see constants
#      above; double-anchor verified 2026-11-12).
#   3. Otherwise the release's own published manifest (checksums.txt,
#      then SHA256SUMS.txt) fetched over the same HTTPS connection.
#   4. None of the above -> die with the exact command to pin the hash.
#   A hash value is never invented: if it cannot be verified from one
#   of the sources above, the install stops instead of installing
#   an unverified binary.
verify_asset() { # verify_asset <file> <asset-name> <base-url> <env-hash> <env-name> <pinned-hash>
    local file="$1" asset="$2" base="$3" env_hash="${4:-}" env_name="${5:-HASH}" pinned_hash="${6:-}"
    local want=""
    if [ -n "$env_hash" ]; then
        want="$env_hash"
        log "verifying $asset against operator-supplied sha256"
    elif [ -n "$pinned_hash" ]; then
        want="$pinned_hash"
        log "verifying $asset against pinned sha256 (double-anchor verified 2026-11-12)"
    else
        local manifest=""
        for _name in checksums.txt SHA256SUMS.txt sha256sums.txt; do
            if curl -fsSL --connect-timeout 20 --max-time 60 \
                    -o "$WORKDIR/manifest.txt" "$base/$_name" 2>/dev/null; then
                manifest="$_name"; break
            fi
        done
        if [ -z "$manifest" ]; then
            die "no sha256 manifest published for this release, no pinned hash and no override set -- download the asset yourself, run 'sha256sum $asset', then re-run with $env_name=<hash> (see README.md)"
        fi
        want="$(awk -v a="$asset" '$2 == a {print $1; exit} $2 == ("*" a) {print $1; exit}' "$WORKDIR/manifest.txt" || true)"
        [ -n "$want" ] || die "manifest $manifest has no entry for $asset -- refusing to install unverified binary"
        log "verifying $asset against upstream $manifest"
    fi
    case "$want" in
        *[!0-9a-f]*|'') die "refusing to verify $asset: expected hash is not 64-hex (got '${want:0:20}...')" ;;
    esac
    [ "${#want}" -eq 64 ] || die "refusing to verify $asset: expected hash is not 64-hex (length ${#want})"
    printf '%s  %s\n' "$want" "$file" | sha256sum -c - \
        || die "sha256 mismatch for $asset -- refusing to install (expected $want; if you bumped the version, re-pin the hash in install.sh)"
    log "sha256 OK: $asset"
}

download() { # download <url> <dest>
    curl -fsSL --retry 3 --connect-timeout 20 --max-time 300 -o "$2" "$1" \
        || die "download failed: $1"
}

install_singbox() {
    if command -v sing-box >/dev/null 2>&1; then
        local cur=""
        cur="$(sing-box version 2>/dev/null | head -1 || true)"
        if printf '%s' "$cur" | grep -q "$SINGBOX_VERSION"; then
            log "sing-box $SINGBOX_VERSION already installed, skipping download"
            return 0
        fi
        log "installed sing-box is '$cur', replacing with $SINGBOX_VERSION"
    fi
    local asset="sing-box-${SINGBOX_VERSION}-linux-${ARCH}.tar.gz"
    local pinned=""
    case "$ARCH" in
        amd64) pinned="$SINGBOX_SHA256_AMD64" ;;
        arm64) pinned="$SINGBOX_SHA256_ARM64" ;;
    esac
    log "downloading sing-box $SINGBOX_VERSION ($asset)..."
    download "$SINGBOX_BASE/$asset" "$WORKDIR/$asset"
    verify_asset "$WORKDIR/$asset" "$asset" "$SINGBOX_BASE" "${SINGBOX_SHA256:-}" "SINGBOX_SHA256" "$pinned"
    tar -xzf "$WORKDIR/$asset" -C "$WORKDIR" \
        || die "failed to extract $asset"
    local bin="$WORKDIR/sing-box-${SINGBOX_VERSION}-linux-${ARCH}/sing-box"
    [ -x "$bin" ] || die "sing-box binary not found in $asset"
    install -m 0755 "$bin" /usr/local/bin/sing-box
    # R7-BUG-1: never pipe a multi-line `--version` straight into
    # `head -1 | grep -q` under `set -o pipefail` -- head exits after
    # the first line, the writer dies of SIGPIPE (141) writing the
    # second, and pipefail turns the whole pipeline into 141 even
    # though grep already matched. Capture the output first, then
    # grep the variable (same fix as the :276 skip-path check, which
    # already captures into $cur).
    local _ver=""
    _ver="$(sing-box version 2>/dev/null | head -1 || true)"
    printf '%s' "$_ver" | grep -q "$SINGBOX_VERSION" \
        || die "installed sing-box does not report $SINGBOX_VERSION"
    log "sing-box installed: $_ver"
}

install_tun2socks() {
    # Standby path for the egress chain (sing-box tun is primary).
    if command -v tun2socks >/dev/null 2>&1; then
        local cur=""
        cur="$(tun2socks --version 2>&1 | head -1 || true)"
        if printf '%s' "$cur" | grep -q "$TUN2SOCKS_VERSION"; then
            log "tun2socks $TUN2SOCKS_VERSION already installed, skipping download"
            return 0
        fi
        log "installed tun2socks is '$cur', replacing with $TUN2SOCKS_VERSION"
    fi
    local asset="tun2socks-linux-${ARCH}.zip"
    local pinned=""
    case "$ARCH" in
        amd64) pinned="$TUN2SOCKS_SHA256_AMD64" ;;
        arm64) pinned="$TUN2SOCKS_SHA256_ARM64" ;;
    esac
    log "downloading tun2socks $TUN2SOCKS_VERSION ($asset)..."
    download "$TUN2SOCKS_BASE/$asset" "$WORKDIR/$asset"
    verify_asset "$WORKDIR/$asset" "$asset" "$TUN2SOCKS_BASE" "${TUN2SOCKS_SHA256:-}" "TUN2SOCKS_SHA256" "$pinned"
    (cd "$WORKDIR" && unzip -o -q "$asset") || die "failed to extract $asset"
    local bin=""
    for _cand in "$WORKDIR/tun2socks-linux-${ARCH}" "$WORKDIR/tun2socks" \
                 "$WORKDIR/tun2socks-linux-${ARCH}/tun2socks"; do
        if [ -f "$_cand" ]; then bin="$_cand"; break; fi
    done
    if [ -z "$bin" ]; then
        bin="$(find "$WORKDIR" -type f -name 'tun2socks*' -not -name '*.zip' | head -1 || true)"
    fi
    [ -n "$bin" ] && [ -f "$bin" ] || die "tun2socks binary not found in $asset"
    install -m 0755 "$bin" /usr/local/bin/tun2socks
    # R7-BUG-1 (same fix as the sing-box check above): capture the
    # multi-line `--version` output first, then grep the variable --
    # `tun2socks --version | head -1 | grep -q` dies of SIGPIPE (141)
    # under `set -o pipefail` about one time in ten.
    local _ver=""
    _ver="$(tun2socks --version 2>&1 | head -1 || true)"
    printf '%s' "$_ver" | grep -q "$TUN2SOCKS_VERSION" \
        || die "installed tun2socks does not report $TUN2SOCKS_VERSION"
    log "tun2socks installed: $_ver"
}

install_singbox
install_tun2socks

# ------------------------------------------------------------------ install tree
log "installing tree to $INSTALL_ROOT..."
mkdir -p "$INSTALL_ROOT" "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
# R2-BUG-10: the installed tree MUST carry agent/ -- the panel serves
# /install-agent.sh, /install-agent.sh.sha256 and /api/agent/bundle
# from PROJECT_DIR (= this tree), so a tree without agent/ makes the
# whole agent-install chain 404/500 on a fresh install (live-verify-R2
# S0-agent). verify-integration.sh is copied too so the installed tree
# can re-verify itself on the host.
# R3-BUG-3: systemd/ likewise -- the unit install step below copies
# units from $SCRIPT_DIR/systemd/ into /etc/systemd/system, so a tree
# without it dies on re-run from /opt and verify.sh's files gate
# stays red (live-verify-R3 §3).
# R4-BUG-2: never self-copy. When install.sh is run from the installed
# tree itself ($SCRIPT_DIR == $INSTALL_ROOT, e.g. re-running from
# /opt/openvpn-sk5-panel after the source tree was deleted), `cp -a`
# refuses to copy a directory onto itself ("are the same file") and
# under `set -e` aborts the whole install before the unit-install
# step (live-verify-R4 §11). Canonicalise both sides (readlink -f
# resolves symlinks and strips trailing slashes) and skip the copy
# with a loud log line when they are the same directory. When they
# differ, copy item by item so one failed item cannot abort the whole
# segment -- but a failure is never swallowed: it is warned loudly
# and recorded in _TREE_COPY_FAILED, and the install dies before the
# completion banner (see the summary section) instead of printing
# "安装完成" over an incomplete tree.
_SCRIPT_DIR_C="$(readlink -f "$SCRIPT_DIR" 2>/dev/null || printf '%s' "$SCRIPT_DIR")"
_INSTALL_ROOT_C="$(readlink -f "$INSTALL_ROOT" 2>/dev/null || printf '%s' "$INSTALL_ROOT")"
_TREE_COPY_FAILED=""
if [ "$_SCRIPT_DIR_C" = "$_INSTALL_ROOT_C" ]; then
    log "source tree is the installed tree ($INSTALL_ROOT); skipping tree copy"
else
    for _item in agent core egress panel systemd install.sh verify.sh verify-integration.sh README.md; do
        if [ "$_item" = "panel" ]; then
            # R8-BUG-1: panel/ is NEVER copied wholesale. Its data/
            # subdirectory is live runtime state (panel.db, the agent
            # command queue, the fallback secret key) -- not shippable
            # content -- and a re-run from a tree containing panel/data/
            # used to destroy the live deployment: `cp -a panel/` first
            # OVERWROTE the live panel.db with the shipped one (GNU cp
            # merges into an existing directory), and the old
            # _PANEL_COPIED guard then DELETED it because "the source
            # tree has the file" -- a guard that can tell "shipped"
            # from "absent" but never "shipped" from "live". The
            # running panel then recreated an empty database and login
            # failed with 401 forever (live-verify-R8 §9/§18). Copy via
            # a staging directory instead: copy panel/ to staging,
            # delete staging/data/, then copy the staging CONTENTS into
            # $INSTALL_ROOT/panel/ -- so no panel/data/ file is ever
            # written, overwritten or deleted by the installer, on a
            # fresh install or a re-run. (Do NOT "fix" this by copying
            # first and deleting afterwards: on a re-run that deletes
            # the live database. rsync --exclude would do the same job,
            # but rsync is not a guaranteed dependency on the target --
            # it is not in the apt list below -- while cp + staging
            # needs only coreutils.) The panel recreates DATA_DIR on
            # import (app.py: makedirs exist_ok), so an install that
            # never touches panel/data/ is safe for a fresh install
            # (empty dir; the panel creates its own DB + admin.pass on
            # first start) and for a re-run (live DB, queue and users
            # untouched). The old guard is gone with the wholesale
            # copy: deleting by "the source has it" can never be safe.
            _PANEL_STAGE="$WORKDIR/stage-panel"
            rm -rf "$_PANEL_STAGE"
            if cp -a "$SCRIPT_DIR/panel" "$_PANEL_STAGE" \
                && rm -rf "$_PANEL_STAGE/data" \
                && mkdir -p "$INSTALL_ROOT/panel" \
                && cp -a "$_PANEL_STAGE/." "$INSTALL_ROOT/panel/"; then
                log "panel/ installed (panel/data/ excluded: runtime state is never shipped and a re-run never touches the live database)"
            else
                warn "failed to copy $SCRIPT_DIR/panel to $INSTALL_ROOT -- continuing, but the install will fail before the completion banner"
                _TREE_COPY_FAILED="$_TREE_COPY_FAILED panel"
            fi
            rm -rf "$_PANEL_STAGE"
        elif ! cp -a "$SCRIPT_DIR/$_item" "$INSTALL_ROOT/"; then
            warn "failed to copy $SCRIPT_DIR/$_item to $INSTALL_ROOT -- continuing, but the install will fail before the completion banner"
            _TREE_COPY_FAILED="$_TREE_COPY_FAILED $_item"
        fi
    done
fi
# P0-5 / R7-BUG-2: the shipped tree must never carry ANY runtime panel
# state (panel.db, agent_queue.json, secret.key) into $INSTALL_ROOT.
# With the staging copy above, no panel/data/ file is ever copied in,
# so there is nothing shipped left to delete -- and the old
# unconditional `rm -f $INSTALL_ROOT/panel/data/secret.key` is gone
# with the guard. That rm could only ever delete LIVE state now: the
# panel writes panel/data/secret.key only when /etc is not writable
# (app.py _secret_path), i.e. it is the live fallback key, and deleting
# it would invalidate live sessions -- the same "delete live state"
# family as R8-BUG-1. Belt and braces already exist in the panel
# itself: if the file ever equals the published shipped key, app.py
# force-rotates it at startup and warns (P0-5 fingerprint check).
mkdir -p "$INSTALL_ROOT/panel/data"
python3 -c 'import os, secrets; open("/etc/openvpn-sk5-panel/secret.key", "wb").write(secrets.token_bytes(32))'
chmod 600 "/etc/openvpn-sk5-panel/secret.key"
log "generated fresh panel secret key (panel/data/ is never copied, so no shipped key can arrive)"
find "$INSTALL_ROOT" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
chmod 755 "$INSTALL_ROOT/core/easyrsa.sh" "$INSTALL_ROOT/egress/policy-routing.sh" 2>/dev/null || true
chmod 755 "$INSTALL_ROOT/egress/test-egress.sh" 2>/dev/null || true
chmod 755 "$INSTALL_ROOT/install.sh" "$INSTALL_ROOT/verify.sh" 2>/dev/null || true

# ------------------------------------------------------------------ panel TLS + env
# The panel itself serves plain HTTP on 8443 (see panel/README.md:
# "production deployments should add HTTPS in front"). To make the
# published address https://<IP>:8443 real without touching panel/,
# install.sh generates a self-signed cert and a small TLS wrapper
# launcher (run-panel-tls.py) that imports the same Flask app and
# serves it with ssl_context. The wrapper lives in the install root,
# not in panel/.
SERVER_IP="$(primary_ip)"
[ -n "$SERVER_IP" ] || SERVER_IP="127.0.0.1"
PANEL_CERT="$CONFIG_DIR/panel-cert.pem"
PANEL_KEY="$CONFIG_DIR/panel-key.pem"
if [ ! -f "$PANEL_CERT" ] || [ ! -f "$PANEL_KEY" ]; then
    log "generating self-signed panel TLS cert (CN=$SERVER_IP, 10y)..."
    openssl req -x509 -newkey rsa:2048 -keyout "$PANEL_KEY" -out "$PANEL_CERT" \
        -days 3650 -nodes -subj "/CN=$SERVER_IP" \
        -addext "subjectAltName=IP:$SERVER_IP,DNS:localhost" 2>/dev/null \
        || die "failed to generate panel TLS cert"
    chmod 600 "$PANEL_KEY"; chmod 644 "$PANEL_CERT"
else
    log "keeping existing panel TLS cert"
fi

cat > "$INSTALL_ROOT/run-panel-tls.py" <<EOF
#!/usr/bin/env python3
"""TLS wrapper for panel/app.py (generated by install.sh).

panel/app.py serves plain HTTP on 0.0.0.0:8443. This launcher imports
the same Flask app and serves it with ssl_context so the published
address https://<IP>:8443 is real. No file under panel/ is modified.
"""
import os
import sys

PANEL_DIR = "$INSTALL_ROOT/panel"
CERT = "$PANEL_CERT"
KEY = "$PANEL_KEY"

sys.path.insert(0, PANEL_DIR)
os.chdir(PANEL_DIR)

import app as panel_app

if __name__ == "__main__":
    for _p in (CERT, KEY):
        if not os.path.exists(_p):
            print("run-panel-tls: missing TLS file %s" % _p, file=sys.stderr)
            raise SystemExit(1)
    _ensure = getattr(panel_app, "_ensure_admin_password", None)
    if callable(_ensure):
        _ensure()
    panel_app.app.run(host="0.0.0.0", port=$PANEL_PORT, ssl_context=(CERT, KEY))
EOF
chmod 755 "$INSTALL_ROOT/run-panel-tls.py"

# R2-§10: OPENVPN_SERVER_IP must never be the LAN IP. _outward_ip()
# prefers an explicit env value over public-IP detection, so writing
# the LAN primary_ip() here made every fresh install's default .ovpn
# remote an unreachable internal address (live-verify-R2 §3/§10:
# remote 172.26.15.152, public detection shadowed). Detect the public
# IP at install time and write the variable ONLY when detection
# succeeds; otherwise omit it so the panel falls through to runtime
# detection (panel/app.py _outward_ip). An already-deployed panel.env
# is left alone by this -- only fresh writes go through here.
# R3-BUG-5: force IPv4 (-4). Without it curl prefers IPv6 on a
# dual-stack host, ifconfig.me returns the IPv6 address, and the
# default .ovpn remote becomes an IPv6 literal that IPv4-only
# clients cannot reach (live-verify-R3 §10). An IPv6 address must
# never be written as the default remote: if no IPv4 is detected,
# leave OPENVPN_SERVER_IP unset so the panel falls through to
# runtime detection.
_PUBLIC_IP="$(curl -4 -fsS --max-time 8 https://ifconfig.me 2>/dev/null || true)"
[ -n "$_PUBLIC_IP" ] || _PUBLIC_IP="$(curl -4 -fsS --max-time 8 http://ifconfig.me 2>/dev/null || true)"
# Belt and braces: only a dotted-quad IPv4 result is accepted; an
# IPv6 (or any garbage) reply is discarded, never written to panel.env.
if [ -n "$_PUBLIC_IP" ] && ! printf '%s' "$_PUBLIC_IP" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$'; then
    _PUBLIC_IP=""
fi
# R4-P2-3: the shape regex alone accepts 999.999.999.999 -- each octet
# is 1-3 digits but may exceed 255. Reject any octet > 255 the same way
# ("no IPv4 detected"): OPENVPN_SERVER_IP stays unset and the panel
# falls through to runtime detection.
if [ -n "$_PUBLIC_IP" ] && ! printf '%s' "$_PUBLIC_IP" | awk -F. 'NF == 4 { for (i = 1; i <= 4; i++) if ($i + 0 > 255) exit 1; exit 0 } { exit 1 }'; then
    _PUBLIC_IP=""
fi
_SERVER_IP_LINE=""
if [ -n "$_PUBLIC_IP" ]; then
    _SERVER_IP_LINE="OPENVPN_SERVER_IP=$_PUBLIC_IP"
    log "public IP detected: $_PUBLIC_IP (default .ovpn remote)"
else
    log "no IPv4 public address detectable at install time; OPENVPN_SERVER_IP left unset (panel detects it at runtime)"
fi
# NOTE: the admin password is NOT generated here. panel/app.py generates
# it on first start and writes /etc/openvpn-sk5-panel/admin.pass (0600);
# install.sh reads that file back after the panel is up (see the health
# gate below) and prints it once. Re-runs keep the existing password.
cat > "$CONFIG_DIR/panel.env" <<EOF
PANEL_HOST=0.0.0.0
PANEL_PORT=$PANEL_PORT
PANEL_TLS_CERT=$PANEL_CERT
PANEL_TLS_KEY=$PANEL_KEY
OPENVPN_CA_DIR=$CA_DIR
OPENVPN_SERVER_DIR=$SERVER_DIR
OPENVPN_PROTO=$OVPN_PROTO
OPENVPN_PORT=$OVPN_PORT
$_SERVER_IP_LINE
OVPN_PANEL_DATA_DIR=$INSTALL_ROOT/panel/data
EOF
# P2-7: PANEL_ADMIN_PASSWORD_FILE used to be written here, but
# panel/app.py never reads it -- it hardcodes
# /etc/openvpn-sk5-panel/admin.pass. The dead variable is gone; the
# health gate below reads the same hardcoded path, so the two can no
# longer drift apart.
chmod 600 "$CONFIG_DIR/panel.env"

# ------------------------------------------------------------------ sing-box config
# Direct-mode starter config: tun1 exists and sing-box runs, but no
# traffic is policy-routed into it until the panel saves an SK5 --
# at that point egress/sk5_manager.py re-renders this file from
# egress/sing-box.json.template and restarts the unit.
if [ -f "$INSTALL_ROOT/egress/sing-box.json.template" ]; then
    log "writing direct-mode sing-box config (panel re-renders it on first SK5 save)"
fi
# P1-9: a re-run must never clobber the rendered SK5 config. If
# sing-box.json already exists it is kept as-is (delete it to reset
# to direct mode); only a first install writes the starter config.
# The old code overwrote it unconditionally, so re-running install.sh
# with SK5 enabled silently downgraded the chain to direct egress
# on the next sing-box restart.
if [ -f "$CONFIG_DIR/sing-box.json" ]; then
    log "keeping existing $CONFIG_DIR/sing-box.json (re-run preserves the rendered config)"
else
cat > "$CONFIG_DIR/sing-box.json" <<'EOF'
{
  "log": {"level": "info", "timestamp": true},
  "dns": {
    "servers": [{"tag": "dns-direct", "address": "1.1.1.1", "detour": "direct"}],
    "rules": [{"outbound": "any", "server": "dns-direct"}],
    "final": "dns-direct",
    "strategy": "ipv4_only"
  },
  "inbounds": [
    {
      "type": "tun", "tag": "tun-in",
      "interface_name": "tun1",
      "address": "10.9.0.1/30",
      "mtu": 1400, "auto_route": false, "strict_route": false, "stack": "system"
    }
  ],
  "outbounds": [
    {"type": "direct", "tag": "direct"},
    {"type": "block", "tag": "block"}
  ],
  "route": {
    "rules": [{"protocol": "dns", "outbound": "direct"}, {"port": 53, "outbound": "direct"}],
    "final": "direct",
    "auto_detect_interface": true
  }
}
EOF
chmod 600 "$CONFIG_DIR/sing-box.json"
fi
sing-box check -c "$CONFIG_DIR/sing-box.json" \
    || die "sing-box config failed 'sing-box check'"

# ------------------------------------------------------------------ PKI + server.conf
# Uses core/openvpn_manager.py (the core lane's own API) with the
# standard layout: CA at /etc/openvpn/server/easy-rsa, server files at
# /etc/openvpn/server. init/build are skipped when artifacts exist,
# so re-runs never wipe a CA or invalidate issued client certs.
log "initialising PKI + server.conf (proto=$OVPN_PROTO port=$OVPN_PORT)..."
mkdir -p "$SERVER_DIR" "$CA_DIR"
chmod 700 "$CA_DIR"
mkdir -p /var/log/openvpn
chown nobody:nogroup /var/log/openvpn 2>/dev/null || chown nobody /var/log/openvpn
chmod 750 /var/log/openvpn
# A previous interrupted run can leave a server req/key with no issued
# cert; Easy-RSA refuses to re-issue over those, so drop the stale pair
# (only when the server cert itself is absent -- never touch a live CA).
if [ ! -f "$SERVER_DIR/server.crt" ]; then
    for _stale in "$CA_DIR/pki/reqs/server.req" "$CA_DIR/pki/private/server.key"; do
        if [ -f "$_stale" ] && [ ! -f "$CA_DIR/pki/issued/server.crt" ]; then
            log "removing stale partial file: $_stale"
            rm -f "$_stale"
        fi
    done
fi
OPENVPN_CA_DIR="$CA_DIR" OPENVPN_SERVER_DIR="$SERVER_DIR" \
OPENVPN_PROTO="$OVPN_PROTO" OPENVPN_PORT="$OVPN_PORT" \
OVPN_DNS="$OVPN_DNS" \
    python3 - "$OVPN_PROTO" "$OVPN_PORT" <<'PYEOF'
import os
import sys
sys.path.insert(0, "/opt/openvpn-sk5-panel/core")
from pathlib import Path
from openvpn_manager import init_pki, build_server_cert, render_server_conf

proto, port = sys.argv[1], int(sys.argv[2])
dns = os.environ.get("OVPN_DNS", "1.1.1.1")
ca_crt = Path("/etc/openvpn/server/easy-rsa/pki/ca.crt")
server_crt = Path("/etc/openvpn/server/server.crt")
if not ca_crt.exists():
    init_pki()
    print("PKI: CA created")
else:
    print("PKI: CA already exists, keeping it")
if not server_crt.exists():
    installed = build_server_cert()
    print("PKI: server cert installed: %s" % sorted(installed))
else:
    print("PKI: server cert already exists, keeping it")
conf = render_server_conf(proto=proto, port=port, dns=dns)
print("server.conf rendered: %s (dns=%s)" % (conf, dns))
PYEOF
grep -q "^proto $OVPN_PROTO" "$SERVER_DIR/server.conf" \
    || die "rendered server.conf has wrong proto"
grep -q "^port $OVPN_PORT" "$SERVER_DIR/server.conf" \
    || die "rendered server.conf has wrong port"
for _f in ca.crt server.crt server.key dh.pem ta.key crl.pem; do
    [ -f "$SERVER_DIR/$_f" ] || die "missing server file after PKI step: $SERVER_DIR/$_f"
done
log "PKI + server.conf OK"

# ------------------------------------------------------------------ forwarding + NAT
# Direct-mode egress for VPN users (SK5 mode replaces this path with
# table 100 -> tun1; the MASQUERADE below never applies to SK5 traffic
# because sing-box re-emits it from the host IP).
printf 'net.ipv4.ip_forward=1\n' > /etc/sysctl.d/99-openvpn-sk5.conf
sysctl -w net.ipv4.ip_forward=1 >/dev/null
WAN_IF="$(ip route show default 2>/dev/null | awk '/default/ {print $5; exit}')"
if [ -n "$WAN_IF" ]; then
    if iptables -t nat -C POSTROUTING -s "$OVPN_SUBNET" -o "$WAN_IF" -j MASQUERADE 2>/dev/null; then
        log "NAT rule already present: $OVPN_SUBNET -> $WAN_IF"
    else
        iptables -t nat -A POSTROUTING -s "$OVPN_SUBNET" -o "$WAN_IF" -j MASQUERADE \
            || warn "failed to add MASQUERADE rule (direct egress may break)"
        log "NAT: MASQUERADE $OVPN_SUBNET via $WAN_IF"
    fi
    # BUG-8: MASQUERADE alone is not enough. On hosts where the FORWARD
    # chain policy is DROP (Docker / Tailscale set this), VPN user
    # traffic dies in FORWARD before it ever reaches POSTROUTING
    # (live-verify S1: 43 packets dropped, MASQUERADE counter 0, while
    # the tunnel itself was up). Add explicit FORWARD accepts for the
    # VPN subnet in both directions. These rules cover direct mode;
    # SK5 mode adds its own tun0<->tun1 rules via policy-routing.sh.
    # The rules are added BEFORE the persistence save below, so a
    # re-run / reboot keeps them.
    # Insert at the head (-I), not append: on DROP-policy hosts earlier
    # rules (DOCKER-USER etc.) must not shadow these narrowly-scoped
    # accepts, and the live-verify S1 workaround verified -I works.
    # The -C check above keeps re-runs idempotent.
    if iptables -C FORWARD -i tun0 -s "$OVPN_SUBNET" -o "$WAN_IF" -j ACCEPT 2>/dev/null; then
        log "FORWARD rule already present: tun0 $OVPN_SUBNET -> $WAN_IF"
    else
        iptables -I FORWARD -i tun0 -s "$OVPN_SUBNET" -o "$WAN_IF" -j ACCEPT \
            || warn "failed to add FORWARD tun0->WAN rule (VPN users will be dropped if FORWARD policy is DROP)"
        log "FORWARD: ACCEPT tun0 $OVPN_SUBNET -> $WAN_IF"
    fi
    if iptables -C FORWARD -i "$WAN_IF" -d "$OVPN_SUBNET" -o tun0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null; then
        log "FORWARD return rule already present: $WAN_IF -> tun0 $OVPN_SUBNET"
    else
        iptables -I FORWARD -i "$WAN_IF" -d "$OVPN_SUBNET" -o tun0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT \
            || warn "failed to add FORWARD return rule (VPN users will be dropped if FORWARD policy is DROP)"
        log "FORWARD: ACCEPT $WAN_IF -> tun0 $OVPN_SUBNET (RELATED,ESTABLISHED)"
    fi
    if command -v netfilter-persistent >/dev/null 2>&1; then
        netfilter-persistent save >/dev/null 2>&1 \
            || warn "netfilter-persistent save failed; NAT/FORWARD rules may not survive reboot"
    elif [ -d /etc/iptables ]; then
        iptables-save > /etc/iptables/rules.v4 2>/dev/null \
            || warn "iptables-save failed; NAT/FORWARD rules may not survive reboot"
    else
        # R8-BUG-2: on a ufw host iptables-persistent is deliberately
        # skipped, so there is no netfilter-persistent and no
        # /etc/iptables to save into -- the rules above are live-only.
        # Say so instead of silently leaving reboot persistence broken.
        if [ "${_UFW_INSTALLED:-0}" -eq 1 ]; then
            warn "ufw host: iptables-persistent was skipped by design (R8-BUG-2), so there is no persistence backend; NAT/FORWARD rules are live-only and will NOT survive a reboot -- re-run install.sh after a reboot to re-apply them"
        else
            warn "no iptables persistence backend found; NAT/FORWARD rules may not survive reboot"
        fi
    fi
else
    warn "no default route found; skipping MASQUERADE (direct egress needs a default route)"
fi
# Open firewall ports when ufw is active; otherwise the host is assumed
# to have no host firewall (cloud security groups still apply).
# R8-P2-4: same SIGPIPE family as R7-BUG-1 -- ufw is a Python program
# with block-buffered stdout; with a long rule table the writer dies
# of BrokenPipeError after grep -q exits, the pipeline returns 1, and
# the installer silently skips opening the ports. Capture the output
# first -- but do NOT grep it through `printf | grep -q`: the captured
# output can exceed the 64KB pipe buffer, grep exits after the first
# line, and printf then dies of SIGPIPE (141) under pipefail, which
# would reintroduce the exact same silent skip. Test the variable
# with a shell builtin instead (no pipe, no writer, no race).
_UFW_STATUS=""
if command -v ufw >/dev/null 2>&1; then
    _UFW_STATUS="$(ufw status 2>/dev/null || true)"
fi
if [[ $_UFW_STATUS == *"Status: active"* ]]; then
    ufw allow "$OVPN_PORT/$OVPN_PROTO" >/dev/null 2>&1 || warn "ufw allow $OVPN_PORT/$OVPN_PROTO failed"
    ufw allow "$PANEL_PORT/tcp" >/dev/null 2>&1 || warn "ufw allow $PANEL_PORT/tcp failed"
    log "ufw: allowed $OVPN_PORT/$OVPN_PROTO and $PANEL_PORT/tcp"
fi

# ------------------------------------------------------------------ python deps
log "installing panel Python deps (pip install -r panel/requirements.txt)..."
PIP_FLAGS=""
if [ -f /usr/lib/python3*/EXTERNALLY-MANAGED ] || ls /usr/lib/python3.*/EXTERNALLY-MANAGED >/dev/null 2>&1; then
    PIP_FLAGS="--break-system-packages"
fi
# shellcheck disable=SC2086
python3 -m pip install $PIP_FLAGS -r "$INSTALL_ROOT/panel/requirements.txt" \
    || die "pip install -r panel/requirements.txt failed"
python3 -c "import flask; print('flask %s' % flask.__version__)" \
    || die "flask import check failed after pip install"

# ------------------------------------------------------------------ systemd units
log "installing systemd units..."
cp -a "$SCRIPT_DIR/systemd/openvpn-sk5-panel.service" /etc/systemd/system/openvpn-sk5-panel.service
cp -a "$SCRIPT_DIR/systemd/openvpn-sk5-singbox.service" /etc/systemd/system/openvpn-sk5-singbox.service
cp -a "$SCRIPT_DIR/systemd/openvpn-sk5-policy.service" /etc/systemd/system/openvpn-sk5-policy.service
cp -a "$SCRIPT_DIR/systemd/openvpn-sk5-healthcheck.service" /etc/systemd/system/openvpn-sk5-healthcheck.service
cp -a "$SCRIPT_DIR/systemd/openvpn-sk5-healthcheck.timer" /etc/systemd/system/openvpn-sk5-healthcheck.timer
# The panel unit ExecStart points at the TLS wrapper generated above.
# If the panel lane ships a different entrypoint than app.py, the unit
# is already correct: the wrapper imports panel/app.py by path, and
# install.sh verified panel/$PANEL_ENTRY exists in preflight.
systemctl daemon-reload

# BUG-3: "systemctl start returned 0" is not proof a service is up.
# With Restart=on-failure a crashing service cycles active -> failed
# -> activating, and a single is-active probe can catch a transient
# active moment while the process is actually in a restart loop
# (live-verify: the installer printed "openvpn-sk5-singbox active"
# while is-active was "activating" and the journal showed restart
# counter 3, 4, ...). The gate below requires is-active == active AND
# the unit's MainPID alive AND its tun device present, held steady
# across a 5s settle window, AND zero restarts so far -- plus, when a
# probe URL is given (the panel unit), an HTTP 200 from it on both
# probes. MainPID (not pgrep) is used on purpose: other software on
# the host may run its own sing-box/openvpn processes, and pgrep
# cannot tell them apart.
_unit_steady() { # _unit_steady <unit> <tun-dev-or-empty> [probe-url]
    local unit="$1" tundev="${2:-}" probe="${3:-}" pid=""
    systemctl is-active --quiet "$unit" 2>/dev/null || return 1
    pid="$(systemctl show "$unit" -p MainPID --value 2>/dev/null || echo 0)"
    [ "${pid:-0}" -gt 0 ] 2>/dev/null || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    [ -z "$tundev" ] || ip link show dev "$tundev" >/dev/null 2>&1 || return 1
    [ -z "$probe" ] || curl -ks --max-time 5 -o /dev/null -w '%{http_code}' "$probe" 2>/dev/null | grep -q '^200$'
}

wait_steady_active() { # wait_steady_active <unit> <tun-dev-or-empty> [probe-url]
    local unit="$1" tundev="${2:-}" probe="${3:-}" i restarts=""
    for i in $(seq 1 20); do
        if _unit_steady "$unit" "$tundev" "$probe"; then
            sleep 5
            if _unit_steady "$unit" "$tundev" "$probe"; then
                restarts="$(systemctl show "$unit" -p NRestarts --value 2>/dev/null || echo "")"
                if [ -n "$restarts" ] && [ "$restarts" != "0" ]; then
                    die "$unit is active but already restarted $restarts time(s) -- crash loop; see: journalctl -u $unit"
                fi
                log "$unit steady: active, main PID alive${tundev:+, $tundev up}${probe:+, probe $probe 200}${restarts:+, restarts=$restarts}"
                return 0
            fi
        fi
        sleep 1
    done
    die "$unit did not reach steady state within 25s (need: is-active + live main PID${tundev:+ + $tundev}${probe:+ + $probe 200}); see: journalctl -u $unit"
}

log "enabling + starting services..."
systemctl enable --now openvpn-server@server \
    || die "failed to start openvpn-server@server (see: journalctl -u openvpn-server@server)"
wait_steady_active openvpn-server@server tun0
log "openvpn-server@server active"

systemctl enable --now openvpn-sk5-singbox \
    || die "failed to start openvpn-sk5-singbox (see: journalctl -u openvpn-sk5-singbox)"
wait_steady_active openvpn-sk5-singbox tun1
log "openvpn-sk5-singbox active (direct mode; panel re-renders config on SK5 save)"

systemctl enable --now openvpn-sk5-panel \
    || die "failed to start openvpn-sk5-panel (see: journalctl -u openvpn-sk5-panel)"

# P1-9: restore policy routing at boot (only when SK5 is enabled in
# the stored config -- the unit itself decides). P1-8: run the SK5
# health check every 60s so fail-open actually fails over.
systemctl enable --now openvpn-sk5-policy.service \
    || warn "failed to start openvpn-sk5-policy (run 'policy-routing.sh restore' after reboot to restore the SK5 chain)"
systemctl enable --now openvpn-sk5-healthcheck.timer \
    || warn "failed to enable openvpn-sk5-healthcheck.timer (fail-open fail-over will not run)"

# Health gate: panel must answer /api/me over HTTPS, then login with
# the generated admin password must succeed. The panel prints the
# password to stdout on first start and writes it to admin.pass.
ADMIN_PASS_FILE="$CONFIG_DIR/admin.pass"
PANEL_OK=0
for _i in $(seq 1 60); do
    if curl -ks --max-time 5 -o /dev/null -w '%{http_code}' "https://127.0.0.1:$PANEL_PORT/api/me" 2>/dev/null | grep -q '^200$'; then
        PANEL_OK=1; break
    fi
    sleep 1
done
[ "$PANEL_OK" -eq 1 ] \
    || die "panel did not answer https://127.0.0.1:$PANEL_PORT/api/me within 60s (see: journalctl -u openvpn-sk5-panel)"
# R2-P1-2 / BUG-3: the panel unit gets the same steady gate as
# openvpn/sing-box (is-active + live MainPID + zero restarts + /api/me
# probe held across a 5s settle), not just the enable --now return
# code and a first-answer poll above.
wait_steady_active openvpn-sk5-panel "" "https://127.0.0.1:$PANEL_PORT/api/me"
log "openvpn-sk5-panel steady"
ADMIN_PASS=""
for _i in $(seq 1 30); do
    if [ -f "$ADMIN_PASS_FILE" ]; then
        ADMIN_PASS="$(head -1 "$ADMIN_PASS_FILE" | tr -d '[:space:]')"
        [ -n "$ADMIN_PASS" ] && break
    fi
    sleep 1
done
[ -n "$ADMIN_PASS" ] \
    || die "panel is up but no admin password at $ADMIN_PASS_FILE (check journalctl -u openvpn-sk5-panel for the printed password)"
COOKIE_JAR="$WORKDIR/cookies.txt"
# P2-8: the admin password must never ride in a curl -d argv (ps can
# read /proc/<pid>/cmdline; curl only scrubs -u/--proxy-user, not -d).
# Write the JSON body to a 0600 file inside the 0700 WORKDIR and send
# it with --data @file instead.
# R6-BUG-2 (same family, second half): the old `python3 - "$ADMIN_PASS"
# ...` below put the password in python3's argv[1] instead — curl was
# clean but the password was still readable via /proc/<pid>/cmdline.
# So the password now travels via a 0600 file too: python reads it from
# the file, never from argv (and never from the environment, which
# /proc/<pid>/environ exposes the same way).
PASS_FILE="$WORKDIR/admin-pass.txt"
(umask 077; printf '%s' "$ADMIN_PASS" > "$PASS_FILE")
python3 - "$PASS_FILE" "$WORKDIR/login-payload.json" <<'PYEOF'
import json, os, sys
pw_path, path = sys.argv[1], sys.argv[2]
with open(pw_path, encoding="utf-8") as f:
    pw = f.read()
with open(path, "w", encoding="utf-8") as f:
    json.dump({"password": pw}, f)
os.chmod(path, 0o600)
PYEOF
LOGIN_CODE="$(curl -ks --max-time 10 -c "$COOKIE_JAR" -o "$WORKDIR/login.json" \
    -w '%{http_code}' -X POST "https://127.0.0.1:$PANEL_PORT/api/login" \
    -H 'Content-Type: application/json' \
    --data @"$WORKDIR/login-payload.json" 2>/dev/null || true)"
rm -f "$WORKDIR/login-payload.json" "$PASS_FILE"
if [ "$LOGIN_CODE" != "200" ] || ! grep -q '"ok": *true' "$WORKDIR/login.json" 2>/dev/null; then
    die "panel login check failed (HTTP $LOGIN_CODE) -- password file and panel DB disagree; see journalctl -u openvpn-sk5-panel"
fi
STATUS_CODE="$(curl -ks --max-time 10 -b "$COOKIE_JAR" -o /dev/null -w '%{http_code}' \
    "https://127.0.0.1:$PANEL_PORT/api/status" 2>/dev/null || true)"
[ "$STATUS_CODE" = "200" ] \
    || die "panel /api/status returned HTTP $STATUS_CODE after login"
log "panel health gate passed (login + /api/status 200)"

# BUG-8: prove the direct-mode forwarding path, not just that services
# are up. A host with FORWARD policy DROP and no accept rules passes
# every service check while dropping all VPN user traffic (live-verify
# S1: tunnel up, curl/dig/ping all dead). Checks: both FORWARD accept
# rules present, and a kernel route lookup for a VPN-net source
# (10.8.0.1, the server's own tun0 address) resolves to the
# main-table default via WAN -- not table 100, which only exists in
# SK5 mode. This is the closest install-time proof short of a real
# VPN client; the full client-traffic proof is verify.sh §9-11 +
# the live S1 matrix (a real client in a netns).
if [ -n "${WAN_IF:-}" ]; then
    iptables -C FORWARD -i tun0 -s "$OVPN_SUBNET" -o "$WAN_IF" -j ACCEPT 2>/dev/null \
        || die "health gate: FORWARD accept tun0 $OVPN_SUBNET -> $WAN_IF missing (VPN users would be dropped if FORWARD policy is DROP)"
    iptables -C FORWARD -i "$WAN_IF" -d "$OVPN_SUBNET" -o tun0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null \
        || die "health gate: FORWARD return rule $WAN_IF -> tun0 $OVPN_SUBNET missing"
    FWD_ROUTE="$(ip route get 1.1.1.1 from 10.8.0.1 2>&1 || true)"
    # R2-BUG-15: this gate must be mode-aware. With SK5 enabled the
    # VPN source is SUPPOSED to resolve via tun1/table 100 -- that is
    # the chain working, not a failure. The old unconditional
    # "must resolve via WAN" assertion made every re-run with SK5 on
    # die here with EXIT=1 while the deployment itself was healthy
    # (live-verify-R2 §8/S0b). SK5 state is read from the stored
    # sk5.json (the same file the panel/egress own); absent file =
    # never configured = direct mode.
    _SK5_ON=0
    if [ -f "$CONFIG_DIR/sk5.json" ]; then
        _SK5_ON="$(python3 -c 'import json,sys; print(1 if json.load(open(sys.argv[1])).get("enabled") else 0)' "$CONFIG_DIR/sk5.json" 2>/dev/null || echo 0)"
    fi
    if [ "$_SK5_ON" = "1" ]; then
        if ! printf '%s' "$FWD_ROUTE" | grep -q "table 100"; then
            die "health gate: SK5 is enabled but VPN source 10.8.0.1 does not route via table 100 ($FWD_ROUTE)"
        fi
        log "forwarding gate passed (SK5 mode; VPN source routes via table 100: $FWD_ROUTE)"
    else
        if ! printf '%s' "$FWD_ROUTE" | grep -q "dev $WAN_IF"; then
            die "health gate: route lookup for VPN source 10.8.0.1 does not resolve via $WAN_IF ($FWD_ROUTE)"
        fi
        if printf '%s' "$FWD_ROUTE" | grep -q "table 100"; then
            die "health gate: route lookup for VPN source unexpectedly hits table 100 in direct mode ($FWD_ROUTE)"
        fi
        log "forwarding gate passed (FORWARD rules present; VPN source routes via $WAN_IF: $FWD_ROUTE)"
    fi
else
    warn "no default route at install time; forwarding gate skipped (re-run install.sh once a default route exists)"
fi

# R4-BUG-2: a failed tree copy must never be hidden behind the
# completion banner. If any item failed to copy above, the installed
# tree is incomplete -- fail loudly here (after the unit install and
# health gates have run, so the log shows the full picture) instead
# of printing "安装完成".
if [ -n "$_TREE_COPY_FAILED" ]; then
    die "tree copy failed for:${_TREE_COPY_FAILED} -- $INSTALL_ROOT is incomplete; fix the source tree and re-run install.sh"
fi

# ------------------------------------------------------------------ summary
_INHERIT_NOTE=""
[ -n "${INHERITED_PORT:-}" ] && _INHERIT_NOTE=" (entry port inherited from existing server.conf)"
cat <<EOF

============================================================
 openvpn-sk5-panel 安装完成
============================================================
 面板:    https://$SERVER_IP:$PANEL_PORT
 管理员:  admin
 初始密码: $ADMIN_PASS
   (仅显示一次；已保存于 $ADMIN_PASS_FILE，权限 0600。
    登录后点顶栏「修改密码」可改密，改后请妥善保存新密码。)
 OpenVPN: proto=$OVPN_PROTO port=$OVPN_PORT subnet=$OVPN_SUBNET dns=$OVPN_DNS$_INHERIT_NOTE
   服务:  openvpn-server@server / openvpn-sk5-singbox / openvpn-sk5-panel
          openvpn-sk5-policy (开机恢复策略路由) / openvpn-sk5-healthcheck.timer (60 秒健康检查)
   配置:  $SERVER_DIR/server.conf
   CA:    $CA_DIR/pki/ca.crt

 下一步:
  1. 浏览器打开面板，用上面的密码登录
  2. 「建服务」确认协议/端口 -> 「加用户」-> 下载 .ovpn
  3. 填 SK5 地址/端口/账号 -> 勾选「启用 SK5 作为出口」-> 保存
  4. 在状态页核对「当前出口 IP」已变成 SK5 的 IP
 自检:  bash $INSTALL_ROOT/verify.sh
 排障:  journalctl -u openvpn-sk5-panel -f
        journalctl -u openvpn-server@server -f
        journalctl -u openvpn-sk5-singbox -f
============================================================
EOF

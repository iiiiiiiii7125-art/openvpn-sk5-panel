#!/usr/bin/env bash
# ovpn-agent -- one-command installer (run on the TRANSIT host).
#
#   curl -ksSL https://<panel>/install-agent.sh -o install-agent.sh
#   curl -ksSL https://<panel>/install-agent.sh.sha256 -o install-agent.sh.sha256
#   sha256sum -c install-agent.sh.sha256 \
#       && bash install-agent.sh --panel-url https://<panel>:8443 \
#       --token <NODE_TOKEN> --node-name <name-from-panel-registration> \
#       [--ca-cert panel.pem] [--insecure]
#
#   (-k on the script download is safe here: the sha256 check
#   authenticates the script bytes before anything executes.
#   --node-name MUST match the name registered in the panel, or the
#   agent's poll is 401 (R2-BUG-12). The old curl|bash pipe form is no
#   longer the default: on a self-signed panel plain curl cannot even
#   fetch the script.)
#
# What it does:
#   1. apt-installs python3/curl/ca-certificates (openvpn/easy-rsa come
#      from the agent's install_prereqs command, also re-runnable).
#   2. Establishes TLS trust FIRST (R2-BUG-11): the panel serves a
#      self-signed certificate by default, so every later fetch must
#      carry a trust anchor. A validated handshake first (public-CA
#      panels need nothing); if the system store rejects the panel
#      cert, the presented leaf is TOFU-pinned to
#      /etc/ovpn-agent/panel-ca.pem and recorded as ca_cert in the
#      config. --ca-cert supplies the PEM directly; --insecure skips
#      verification entirely (explicit opt-in only, warns loudly) and
#      also passes -k to the fetches below. The old order (fetch the
#      bundle first, pin trust after) could never work against a
#      self-signed panel: every fetch failed TLS and was misreported
#      as "panel does not serve .../bundle.sha256".
#   3. Gets the agent bundle: if this script sits next to agent.py +
#      core/ + egress/ (repo checkout), it copies locally; otherwise it
#      downloads <panel-url>/api/agent/bundle (a .tar.gz the panel
#      serves from this repo) into /opt/ovpn-agent/ -- and verifies its
#      sha256 fail-closed (bundle.sha256 endpoint, else
#      $OVPN_AGENT_BUNDLE_SHA256; neither available -> refuse).
#      All fetches use the step-2 anchor; failures name the exact
#      layer (TLS vs HTTP vs network).
#   4. Writes /etc/ovpn-agent/config.json (0600) with panel_url +
#      node_token (+ the step-2 trust anchor). Re-running WITHOUT
#      --token keeps the existing token.
#   5. Installs ovpn-agent.service, daemon-reloads, enables it, and
#      (re)starts it -- BUG-6: a re-run restarts an already-running
#      agent so the new config actually takes effect.
#
# Re-running over an existing install requires --force (P2-13): without
# it the script refuses instead of silently overwriting the deployment;
# with it, the existing config.json is backed up first
# (config.json.bak.<timestamp>) and systemctl reset-failed runs before
# the service is (re)started.
#
# The agent only talks OUTBOUND to the panel (poll every 5 s); the
# transit host needs no inbound port. Exit codes: 0 ok, 1 any failure.
set -euo pipefail

PANEL_URL=""
TOKEN=""
FORCE=0
CA_CERT_ARG=""
INSECURE=0
NODE_NAME="$(hostname)"
INSTALL_ROOT="/opt/ovpn-agent"
CONFIG_DIR="/etc/ovpn-agent"
CONFIG_FILE="$CONFIG_DIR/config.json"
PANEL_CA_PEM="$CONFIG_DIR/panel-ca.pem"

log()  { echo "[install-agent] $*"; }
warn() { echo "[install-agent] WARN: $*"; }
die()  { echo "[install-agent] ERROR: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --panel-url)  PANEL_URL="${2:-}"; shift 2 ;;
        --token)      TOKEN="${2:-}"; shift 2 ;;
        --node-name)  NODE_NAME="${2:-}"; shift 2 ;;
        --install-root) INSTALL_ROOT="${2:-}"; shift 2 ;;
        --ca-cert)    CA_CERT_ARG="${2:-}"; shift 2 ;;
        --insecure)   INSECURE=1; shift ;;
        --force) FORCE=1; shift ;;
        *) die "unknown argument: $1 (see --panel-url/--token/--node-name/--ca-cert/--insecure/--force)" ;;
    esac
done

[ -n "$PANEL_URL" ] || die "--panel-url is required"
case "$PANEL_URL" in
    http://*|https://*) ;;
    *) die "--panel-url must start with http:// or https://" ;;
esac
PANEL_URL="${PANEL_URL%/}"

# Never touch a live FLMX deployment. The agent only ever writes to
# INSTALL_ROOT, CONFIG_DIR, /etc/openvpn/server* and /etc/systemd/system;
# if any of those resolves to /root/flmx-panel, refuse outright.
for _dir in "$INSTALL_ROOT" "$CONFIG_DIR" "/etc/openvpn" "$PWD"; do
    case "$_dir" in
        /root/flmx-panel|/root/flmx-panel/*)
            die "refusing: target $_dir is inside /root/flmx-panel" ;;
    esac
done
[ "$(id -u)" = 0 ] || die "run as root (agent manages openvpn/iptables)"

if [ -z "$TOKEN" ]; then
    if [ -f "$CONFIG_FILE" ]; then
        log "no --token given, keeping existing token from $CONFIG_FILE"
        TOKEN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["node_token"])' "$CONFIG_FILE" 2>/dev/null || true)"
    fi
    [ -n "$TOKEN" ] || die "--token is required on first install"
fi

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "required command missing: $1"; }
need_cmd curl
need_cmd python3

WORKDIR="$(mktemp -d /tmp/ovpn-agent-install.XXXXXX)"
trap 'rm -rf "$WORKDIR"' EXIT

# P2-13: an existing deployment is never overwritten silently. Without
# --force this refuses (and points at --force); with --force the
# existing config (which holds the node token) is backed up first.
if [ -f "$INSTALL_ROOT/agent/agent.py" ] || [ -f "$CONFIG_FILE" ]; then
    if [ "$FORCE" -eq 0 ]; then
        die "existing agent install found ($INSTALL_ROOT / $CONFIG_FILE) -- refusing to overwrite; re-run with --force to replace it (the existing config will be backed up first), or uninstall the old agent first"
    fi
    if [ -f "$CONFIG_FILE" ]; then
        _bak="$CONFIG_DIR/config.json.bak.$(date +%Y%m%d%H%M%S)"
        cp -a "$CONFIG_FILE" "$_bak" && chmod 600 "$_bak"
        log "backed up existing config to $_bak"
    fi
fi

# --- panel TLS trust (BUG-5) ------------------------------------------------
# The panel serves a self-signed certificate by default (install.sh
# generates one), and the agent verifies TLS -- without a trust anchor
# every poll fails with CERTIFICATE_VERIFY_FAILED and the whole
# command chain is dead. Resolution, in order:
#   --ca-cert PATH : that PEM is copied to $PANEL_CA_PEM and pinned.
#   --insecure     : config insecure=true (explicit opt-in ONLY -- the
#                    node token and .ovpn contents can then be
#                    intercepted; the installer prints a loud warning).
#   otherwise      : a validated handshake first -- public-CA panels
#                    (e.g. a Cloudflare front) need nothing extra. If
#                    the system store rejects the panel certificate,
#                    the presented leaf is TOFU-pinned to $PANEL_CA_PEM
#                    and recorded as ca_cert. A pinned cert goes stale
#                    if the panel regenerates its certificate: re-run
#                    this script with --force to re-fetch it.
# If the panel is unreachable now and a previous pin exists, the old
# pin is kept (with a warning); with no previous pin the install stops
# -- installing an agent that can never poll would be a silent lie.
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
_TRUST_HINT="auto"
if [ -n "$CA_CERT_ARG" ]; then
    [ -f "$CA_CERT_ARG" ] || die "--ca-cert file not found: $CA_CERT_ARG"
    cp "$CA_CERT_ARG" "$PANEL_CA_PEM" && chmod 600 "$PANEL_CA_PEM"
    _TRUST_HINT="supplied"
elif [ "$INSECURE" -eq 1 ]; then
    warn "WARNING: --insecure given: agent will NOT verify the panel TLS certificate; the node token and user .ovpn contents can be intercepted on this path. Prefer --ca-cert or the default TOFU pin."
    _TRUST_HINT="insecure"
fi
_TRUST_JSON="$(python3 - "$PANEL_URL" "$_TRUST_HINT" "$PANEL_CA_PEM" <<'PYEOF'
import json, os, socket, ssl, sys, urllib.parse
panel_url, hint, out_pem = sys.argv[1:4]
result = {"mode": "system", "ca_cert": None, "insecure": False}
if hint == "insecure":
    result.update(mode="insecure", insecure=True)
    print(json.dumps(result))
    sys.exit(0)
if hint == "supplied":
    result.update(mode="supplied", ca_cert=out_pem)
    print(json.dumps(result))
    sys.exit(0)
u = urllib.parse.urlparse(panel_url)
if u.scheme != "https":
    result["mode"] = "http"  # loopback http only; no TLS to trust
    print(json.dumps(result))
    sys.exit(0)
host, port = u.hostname, u.port or 443
ctx = ssl.create_default_context()
try:
    with socket.create_connection((host, port), timeout=15) as sock:
        with ctx.wrap_socket(sock, server_hostname=host):
            pass
    print(json.dumps(result))  # system store already trusts the panel
    sys.exit(0)
except ssl.SSLCertVerificationError:
    pass  # self-signed / unknown CA: fall through to TOFU pin
except (OSError, ssl.SSLError) as exc:
    print(json.dumps({"mode": "error", "ca_cert": None,
                      "insecure": False, "error": str(exc)}))
    sys.exit(0)
try:
    pem = ssl.get_server_certificate((host, port), timeout=15)
except (OSError, ssl.SSLError) as exc:
    print(json.dumps({"mode": "error", "ca_cert": None,
                      "insecure": False, "error": str(exc)}))
    sys.exit(0)
if "-----BEGIN CERTIFICATE-----" not in pem:
    print(json.dumps({"mode": "error", "ca_cert": None, "insecure": False,
                      "error": "panel presented no certificate"}))
    sys.exit(0)
with open(out_pem, "w", encoding="utf-8") as f:
    f.write(pem if pem.endswith("\n") else pem + "\n")
os.chmod(out_pem, 0o600)
result.update(mode="pinned", ca_cert=out_pem)
print(json.dumps(result))
PYEOF
)" || die "panel TLS trust detection failed"
_TRUST_MODE="$(printf '%s' "$_TRUST_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("mode",""))')"
_TRUST_CA="$(printf '%s' "$_TRUST_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("ca_cert") or "")')"
if [ "$_TRUST_MODE" = "error" ]; then
    _ERR="$(printf '%s' "$_TRUST_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("error",""))')"
    if [ -f "$PANEL_CA_PEM" ]; then
        warn "cannot reach panel to verify its certificate ($_ERR); keeping previous pin $PANEL_CA_PEM"
        _TRUST_MODE="pinned"
        _TRUST_CA="$PANEL_CA_PEM"
    else
        die "cannot reach panel $PANEL_URL to establish TLS trust ($_ERR); fix the network or pass --ca-cert <panel.pem> / --insecure"
    fi
fi
case "$_TRUST_MODE" in
    system)  log "panel certificate is trusted by the system store (no pin needed)" ;;
    http)    log "panel URL is plain http (loopback only); no TLS trust to establish" ;;
    supplied) log "trusting panel certificate supplied via --ca-cert ($PANEL_CA_PEM)" ;;
    pinned)  log "pinned panel self-signed certificate (TOFU) to $PANEL_CA_PEM -- re-run with --force if the panel regenerates its certificate" ;;
    insecure) log "TLS verification disabled for this agent (explicit --insecure)" ;;
esac


# R2-BUG-11: every panel fetch below MUST carry the trust anchor
# established above. Plain curl against a self-signed panel fails
# TLS (exit 60) -- the old order ran the bundle fetches BEFORE any
# anchor existed and misreported the TLS failure as "panel does not
# serve .../bundle.sha256". -k only when the operator explicitly
# passed --insecure (the agent poll config gets the same treatment).
case "$_TRUST_MODE" in
    pinned|supplied) CURL_TLS="--cacert $PANEL_CA_PEM" ;;
    insecure)        CURL_TLS="-k" ;;
    *)               CURL_TLS="" ;;
esac

# curl_panel <output> <url>: fetch from the panel with the trust
# anchor above. On failure it dies naming the exact layer (TLS vs
# HTTP vs network) -- never the old blanket "panel does not serve ...".
curl_panel() {
    local _out="$1" _url="$2" _err="$WORKDIR/curl.err" _rc=0
    curl $CURL_TLS -fsSL --connect-timeout 20 --max-time 60 \
        -o "$_out" "$_url" 2>"$_err" || _rc=$?
    [ "$_rc" = 0 ] && return 0
    case "$_rc" in
        60) die "TLS trust failed fetching $_url (curl exit 60: the panel certificate was rejected; trust mode=$_TRUST_MODE, anchor=$PANEL_CA_PEM; re-run with --ca-cert <panel.pem>, --insecure, or --force to re-pin)" ;;
        22) die "panel returned an HTTP error fetching $_url (curl exit 22: the endpoint does not exist on this panel build)" ;;
        *)  die "cannot fetch $_url (curl exit $_rc: $(head -c 200 "$_err" 2>/dev/null || true))" ;;
    esac
}

# P2-13 (script self-check): when this script is run from a downloaded
# file (not via curl|bash, where its own bytes are not on disk), verify
# it against the panel's /install-agent.sh.sha256 before doing anything.
# A mismatch is fatal. The fetch carries the trust anchor established
# above (R2-BUG-11); a TLS failure here dies outright -- trust was
# already established, so exit 60 means the panel cert changed
# mid-install. An HTTP error (endpoint absent on an older panel build)
# only warns -- the bundle below is still sha256 fail-closed either way.
# Recommended invocation (the panel's default install command):
#   curl -ksSL -o install-agent.sh $PANEL_URL/install-agent.sh
#   curl -ksSL -o install-agent.sh.sha256 $PANEL_URL/install-agent.sh.sha256
#   sha256sum -c install-agent.sh.sha256 && bash install-agent.sh ...
# (-k on the script download is safe here: the sha256 check
# authenticates the script bytes before anything executes.)
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    if curl $CURL_TLS -fsSL --connect-timeout 20 --max-time 60 \
            -o "$WORKDIR/install-agent.sh.sha256" \
            "$PANEL_URL/install-agent.sh.sha256" 2>/dev/null; then
        _want="$(awk '{print $1; exit}' "$WORKDIR/install-agent.sh.sha256" 2>/dev/null || true)"
        if [ "${#_want}" = 64 ]; then
            printf '%s  %s\n' "$_want" "${BASH_SOURCE[0]}" | sha256sum -c - \
                || die "install-agent.sh sha256 mismatch -- the downloaded script does not match the panel's published hash; refusing to run"
            log "self-check OK: install-agent.sh matches panel hash"
        else
            warn "panel install-agent.sh.sha256 is not a 64-hex value, skipping self-check"
        fi
    else
        _sc_rc=$?
        case "$_sc_rc" in
            60) die "TLS trust failed fetching $PANEL_URL/install-agent.sh.sha256 (curl exit 60) -- the panel certificate was rejected even after the trust step above; re-run with --ca-cert <panel.pem> or --insecure" ;;
            *)  warn "panel does not serve $PANEL_URL/install-agent.sh.sha256 (curl exit $_sc_rc, older panel build?); this script itself is unverified (TLS only) -- the agent bundle below is still sha256 fail-closed" ;;
        esac
    fi
fi

if command -v apt-get >/dev/null 2>&1; then
    log "installing base packages (python3, curl, ca-certificates)"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends python3 curl ca-certificates \
        || die "apt install failed"
else
    warn "apt-get not found; assuming python3/curl already installed"
fi

# --- fetch the bundle -------------------------------------------------------
# Local copy wins when run from a checkout (agent.py + core/ + egress/
# next to this script); otherwise download the tarball from the panel.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd)"
if [ -f "$SCRIPT_DIR/agent.py" ] && [ -d "$SCRIPT_DIR/../core" ]; then
    log "using local bundle from $SCRIPT_DIR"
    BUNDLE_DIR="$SCRIPT_DIR/.."
else
    # Bundle 下载 fail-closed（FLMX §1-13/§1-15 同款：脚本 + .sha256 一起取，
    # 比对通过才执行；缺校验即停，不许只告警继续装）：
    #   1. $OVPN_AGENT_BUNDLE_SHA256 环境变量（若设置，严格校验）；
    #   2. 否则面板的 $PANEL_URL/api/agent/bundle.sha256（与 bundle 同源）；
    #   3. 两者都没有 —— 直接失败退出。哈希值永不凭空写。
    # （面板自 2026-11-12 起提供 /api/agent/bundle.sha256 端点，远程
    # 安装不再卡在这一步；本地 bundle 分支不受影响，见上。）
    need_cmd sha256sum
    _want=""
    if [ -n "${OVPN_AGENT_BUNDLE_SHA256:-}" ]; then
        _want="$OVPN_AGENT_BUNDLE_SHA256"
        log "verifying bundle against OVPN_AGENT_BUNDLE_SHA256"
    else
        # R2-BUG-11: curl_panel carries the trust anchor and dies
        # naming the exact layer on failure (TLS 60 / HTTP 22 /
        # network). The old plain-curl branch reported every failure
        # -- including a TLS rejection -- as "panel does not serve
        # .../bundle.sha256", which hid the real cause.
        curl_panel "$WORKDIR/bundle.sha256" "$PANEL_URL/api/agent/bundle.sha256"
        _want="$(awk '{print $1; exit}' "$WORKDIR/bundle.sha256" 2>/dev/null || true)"
        [ -n "$_want" ] || die "panel bundle.sha256 is empty -- refusing to install unverified bundle"
        log "verifying bundle against panel bundle.sha256"
    fi
    case "$_want" in
        *[!0-9a-f]*|"") die "bundle sha256 is not a 64-hex value: $_want" ;;
    esac
    [ "${#_want}" = 64 ] || die "bundle sha256 is not a 64-hex value: $_want"
    log "downloading bundle from $PANEL_URL/api/agent/bundle"
    curl_panel "$WORKDIR/bundle.tar.gz" "$PANEL_URL/api/agent/bundle"
    printf '%s  %s\n' "$_want" "$WORKDIR/bundle.tar.gz" | sha256sum -c - \
        || die "agent bundle sha256 mismatch -- refusing to install (expected $_want)"
    log "sha256 OK: agent bundle"
    tar -xzf "$WORKDIR/bundle.tar.gz" -C "$WORKDIR" \
        || die "cannot unpack agent bundle"
    BUNDLE_DIR="$WORKDIR"
    [ -f "$BUNDLE_DIR/agent/agent.py" ] || die "bundle has no agent/agent.py"
fi

log "installing to $INSTALL_ROOT"
mkdir -p "$INSTALL_ROOT/agent" "$INSTALL_ROOT/core" "$INSTALL_ROOT/egress"
cp "$BUNDLE_DIR/agent/agent.py" "$INSTALL_ROOT/agent/agent.py"
cp "$BUNDLE_DIR/agent/ovpn-agent.service" "$INSTALL_ROOT/ovpn-agent.service"
cp -r "$BUNDLE_DIR/core/." "$INSTALL_ROOT/core/"
cp -r "$BUNDLE_DIR/egress/." "$INSTALL_ROOT/egress/"
rm -rf "$INSTALL_ROOT/core/__pycache__" "$INSTALL_ROOT/egress/__pycache__"
chmod 755 "$INSTALL_ROOT/agent/agent.py"
python3 -m py_compile "$INSTALL_ROOT/agent/agent.py" \
    || die "agent.py does not compile"

# --- config (0600) ----------------------------------------------------------
python3 - "$CONFIG_FILE" "$PANEL_URL" "$TOKEN" "$NODE_NAME" "$_TRUST_MODE" "$_TRUST_CA" <<'PYEOF'
import json, os, sys
path, panel_url, token, node_name, trust_mode, trust_ca = sys.argv[1:7]
cfg = {"panel_url": panel_url, "node_token": token, "node_name": node_name}
if trust_mode in ("pinned", "supplied") and trust_ca:
    cfg["ca_cert"] = trust_ca
elif trust_mode == "insecure":
    cfg["insecure"] = True
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
    f.write("\n")
os.chmod(tmp, 0o600)
os.replace(tmp, path)
print("wrote %s (0600)" % path)
PYEOF

# --- systemd ----------------------------------------------------------------
cp "$INSTALL_ROOT/ovpn-agent.service" /etc/systemd/system/ovpn-agent.service
systemctl daemon-reload
# P2-13: clear a previous failed state first, or (re)start can refuse
# on a unit systemd has rate-limited / marked failed.
systemctl reset-failed ovpn-agent.service 2>/dev/null || true
# BUG-6: `enable --now` is a no-op for an already-running unit -- the
# old process keeps polling with the OLD config (old panel URL/token)
# after a re-install. Always (re)start so the new config takes effect,
# and say so: a restart is the whole point of re-running the installer.
if systemctl is-active --quiet ovpn-agent.service 2>/dev/null; then
    log "ovpn-agent was already running -- restarting it so the new config (panel URL / token / trust) takes effect"
    systemctl restart ovpn-agent.service \
        || die "failed to restart ovpn-agent.service"
    log "ovpn-agent restarted with new config (old process replaced)"
else
    systemctl enable --now ovpn-agent.service \
        || die "failed to start ovpn-agent.service"
fi

sleep 2
if systemctl is-active --quiet ovpn-agent.service; then
    log "ovpn-agent is ACTIVE (node=$NODE_NAME, panel=$PANEL_URL)"
    log "logs: journalctl -u ovpn-agent -f"
    log "next: in the panel, run install_prereqs, then create_server, then add users"
else
    systemctl status ovpn-agent.service --no-pager || true
    die "ovpn-agent failed to start; see journalctl -u ovpn-agent"
fi

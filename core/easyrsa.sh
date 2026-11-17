#!/usr/bin/env bash
# easyrsa.sh -- thin non-interactive wrapper around Easy-RSA 3 for the
# OpenVPN manager (core/openvpn_manager.py).
#
# Usage:
#   easyrsa.sh init <ca_dir> [--force] init-pki + build-ca (nopass)
#   easyrsa.sh build-server <ca_dir>    server cert + DH + ta.key
#   easyrsa.sh build-client <ca_dir> <name>
#   easyrsa.sh revoke <ca_dir> <name>   revoke + gen-crl
#   easyrsa.sh gen-crl <ca_dir>
#
# Layout: <ca_dir>/pki/{ca.crt,dh.pem,ta.key,crl.pem,index.txt,
#           issued/<name>.crt, private/<name>.key}
# Requires: easy-rsa >= 3.1.0 (R41-L3-F1: 3.0.x build-ca prompts for a
# PEM pass phrase because build_ca() never passes -nodes to openssl
# req; install.sh installs 3.1.7 under /usr/local when the distro one
# is older, and this script refuses to run on < 3.1.0) and, for ta.key
# generation, openvpn 2.4+ (either genkey syntax is handled, R41-L1-2).
# All operations are batch/non-interactive; certs are nopass so the
# daemon can start unattended. Keep <ca_dir> root-only (mode 0700).
set -euo pipefail

usage() {
    echo "usage: $0 init <ca_dir> | build-server <ca_dir> | build-client <ca_dir> <name> | revoke <ca_dir> <name> | gen-crl <ca_dir>" >&2
    exit 2
}

[ $# -ge 2 ] || usage
CMD="$1"
CA_DIR="$2"
NAME="${3:-}"

# --- locate easyrsa ---------------------------------------------------------
# R41-L3-F1: easy-rsa < 3.1.0 cannot build a CA non-interactively
# (build_ca never passes -nodes to openssl req, so it prompts for a
# PEM pass phrase). Search order: $EASYRSA_BIN override first, then
# the installer's /usr/local copy (>= 3.1.0), then the distro copy,
# then PATH. The version gate below rejects anything < 3.1.0.
if [ -n "${EASYRSA_BIN:-}" ]; then
    : # caller-supplied binary (probes / operators); used as-is
elif [ -x /usr/local/share/easy-rsa/easyrsa ]; then
    EASYRSA_BIN=/usr/local/share/easy-rsa/easyrsa
else
    EASYRSA_BIN=""
    for cand in /usr/share/easy-rsa/easyrsa /usr/share/easy-rsa/3/easyrsa; do
        if [ -x "$cand" ]; then EASYRSA_BIN="$cand"; break; fi
    done
    if [ -z "$EASYRSA_BIN" ]; then
        EASYRSA_BIN="$(command -v easyrsa || true)"
    fi
fi
if [ -z "$EASYRSA_BIN" ] || [ ! -x "$EASYRSA_BIN" ]; then
    echo "easyrsa.sh: easyrsa binary not found (apt install easy-rsa)" >&2
    exit 1
fi

# --- version gate: easy-rsa >= 3.1.0 ---------------------------------------
# 3.0.x has no --version command, so an unparseable version is treated
# as too old (fail closed). Fix: re-run install.sh, which installs
# EasyRSA 3.1.7 under /usr/local/share/easy-rsa.
_easyrsa_version="$("$EASYRSA_BIN" --version 2>/dev/null | sed -n 's/^Version:[[:space:]]*\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -1 || true)"
if [ -z "$_easyrsa_version" ]; then
    echo "easyrsa.sh: easyrsa at $EASYRSA_BIN is too old (no --version: pre-3.1.0); install easy-rsa >= 3.1.0 (re-run install.sh)" >&2
    exit 1
fi
_easyrsa_major="${_easyrsa_version%%.*}"
_easyrsa_rest="${_easyrsa_version#*.}"
_easyrsa_minor="${_easyrsa_rest%%.*}"
_too_old=0
[ "$_easyrsa_major" -lt 3 ] && _too_old=1
[ "$_easyrsa_major" -eq 3 ] && [ "$_easyrsa_minor" -lt 1 ] && _too_old=1
if [ "$_too_old" -eq 1 ]; then
    echo "easyrsa.sh: easyrsa $_easyrsa_version at $EASYRSA_BIN is too old (need >= 3.1.0); re-run install.sh to upgrade" >&2
    exit 1
fi

# --- repair a foreign/partial PKI layout -----------------------------------
# R41-L1-4/L1-5: a pre-existing PKI (e.g. an angristan install) may
# lack pki/openssl-easyrsa.cnf and the revoked/renewed CA dirs that
# sign-req/gen-crl demand one by one. Restore what is repairable
# (template cnf from the easyrsa install dir, the full dir set)
# before any command that touches an existing PKI. Only fills gaps:
# nothing already present is touched (dirs are created+chmodded only
# when missing; the cnf is copied only when missing).
_repair_pki_layout() {
    [ -d "$EASYRSA_PKI" ] || return 0
    if [ ! -e "$EASYRSA_PKI/openssl-easyrsa.cnf" ]; then
        local src=""
        for cand in "$(dirname "$EASYRSA_BIN")/openssl-easyrsa.cnf" \
                    /usr/local/share/easy-rsa/openssl-easyrsa.cnf \
                    /usr/share/easy-rsa/openssl-easyrsa.cnf; do
            if [ -e "$cand" ]; then src="$cand"; break; fi
        done
        if [ -n "$src" ]; then
            cp "$src" "$EASYRSA_PKI/openssl-easyrsa.cnf"
            chmod 600 "$EASYRSA_PKI/openssl-easyrsa.cnf"
        fi
    fi
    for d in "$EASYRSA_PKI/issued" "$EASYRSA_PKI/certs_by_serial" \
             "$EASYRSA_PKI/reqs" "$EASYRSA_PKI/private" \
             "$EASYRSA_PKI/revoked" \
             "$EASYRSA_PKI/revoked/certs_by_serial" \
             "$EASYRSA_PKI/revoked/private_by_serial" \
             "$EASYRSA_PKI/revoked/reqs_by_serial" \
             "$EASYRSA_PKI/renewed" \
             "$EASYRSA_PKI/renewed/certs_by_serial" \
             "$EASYRSA_PKI/renewed/private_by_serial" \
             "$EASYRSA_PKI/renewed/reqs_by_serial"; do
        if [ ! -d "$d" ]; then
            mkdir -p "$d"
            chmod 700 "$d"
        fi
    done
}

# R41-L1-2: OpenVPN >= 2.5 takes `--genkey secret`, 2.4 takes
# `--genkey --secret`. Undetectable version keeps the current
# (>= 2.5) syntax -- only a positively detected < 2.5 switches.
_openvpn_at_least_2_5() {
    local line major minor
    line="$(openvpn --version 2>/dev/null | sed -n 's/^OpenVPN \([0-9][0-9]*\)\.\([0-9][0-9]*\).*/\1 \2/p' | head -1 || true)"
    [ -z "$line" ] && return 0
    major="${line%% *}"
    minor="${line##* }"
    [ "$major" -gt 2 ] || { [ "$major" -eq 2 ] && [ "$minor" -ge 5 ]; }
}

# --- deterministic Easy-RSA environment ------------------------------------
export EASYRSA_PKI="$CA_DIR/pki"
export EASYRSA_BATCH=1
export EASYRSA_ALGO=rsa
export EASYRSA_KEY_SIZE=2048
export EASYRSA_DIGEST=sha256
export EASYRSA_CA_EXPIRE=3650
export EASYRSA_CERT_EXPIRE=825
# BUG-7: EASYRSA_REQ_CN must NEVER be a global export -- Easy-RSA uses
# it as the CN of every generated request, so a global "OpenVPN-CA"
# made every client cert's CN "OpenVPN-CA" (indistinguishable users,
# revoke-by-name and list_users CN matching all broken). Set it inline
# per command instead: "OpenVPN-CA" only for build-ca, the cert's own
# name for gen-req server / client.

mkdir -p "$CA_DIR"
chmod 700 "$CA_DIR"

easyrsa() {
    "$EASYRSA_BIN" --batch "$@"
}

case "$CMD" in
init)
    # Fresh PKI + self-signed CA. Refuses to run twice: init-pki wipes
    # the directory, so require an explicit empty/absent pki first --
    # unless --force is given (CA rebuild, e.g. after a compromise;
    # the caller must confirm separately -- see agent action_init_pki,
    # which requires confirm=true alongside force).
    FORCE=0
    [ "${3:-}" = "--force" ] && FORCE=1
    if [ -e "$EASYRSA_PKI/ca.crt" ] && [ "$FORCE" -eq 0 ]; then
        echo "easyrsa.sh: CA already exists in $EASYRSA_PKI (refusing to wipe)" >&2
        exit 1
    fi
    if [ "$FORCE" -eq 1 ]; then
        rm -rf "$EASYRSA_PKI"
    fi
    easyrsa init-pki
    EASYRSA_REQ_CN="OpenVPN-CA" easyrsa build-ca nopass
    ;;

build-server)
    [ -e "$EASYRSA_PKI/ca.crt" ] || { echo "easyrsa.sh: no CA in $EASYRSA_PKI -- run init first" >&2; exit 1; }
    _repair_pki_layout
    EASYRSA_REQ_CN="server" easyrsa gen-req server nopass
    easyrsa sign-req server server
    easyrsa gen-dh
    # tls-auth static key: --genkey secret on OpenVPN >= 2.5,
    # --genkey --secret on 2.4 (R41-L1-2).
    if [ ! -e "$EASYRSA_PKI/ta.key" ]; then
        command -v openvpn >/dev/null 2>&1 || { echo "easyrsa.sh: openvpn binary not found (apt install openvpn)" >&2; exit 1; }
        if _openvpn_at_least_2_5; then
            openvpn --genkey secret "$EASYRSA_PKI/ta.key"
        else
            openvpn --genkey --secret "$EASYRSA_PKI/ta.key"
        fi
        chmod 600 "$EASYRSA_PKI/ta.key"
    fi
    # Empty CRL so the server always has a crl.pem to verify against.
    easyrsa gen-crl
    ;;

build-client)
    [ -n "$NAME" ] || usage
    [ -e "$EASYRSA_PKI/ca.crt" ] || { echo "easyrsa.sh: no CA in $EASYRSA_PKI -- run init first" >&2; exit 1; }
    _repair_pki_layout
    if [ -e "$EASYRSA_PKI/issued/$NAME.crt" ]; then
        echo "easyrsa.sh: cert for '$NAME' already exists" >&2
        exit 1
    fi
    EASYRSA_REQ_CN="$NAME" easyrsa gen-req "$NAME" nopass
    easyrsa sign-req client "$NAME"
    ;;

revoke)
    [ -n "$NAME" ] || usage
    [ -e "$EASYRSA_PKI/issued/$NAME.crt" ] || { echo "easyrsa.sh: no cert for '$NAME'" >&2; exit 1; }
    _repair_pki_layout
    easyrsa revoke "$NAME"
    easyrsa gen-crl
    ;;

gen-crl)
    _repair_pki_layout
    easyrsa gen-crl
    ;;

*)
    usage
    ;;
esac

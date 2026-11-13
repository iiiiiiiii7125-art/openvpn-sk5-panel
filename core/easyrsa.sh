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
# Requires: easy-rsa 3.x (Debian/Ubuntu: apt install easy-rsa) and, for
# ta.key generation, openvpn 2.6 (apt install openvpn).
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
EASYRSA_BIN=""
for cand in /usr/share/easy-rsa/easyrsa /usr/share/easy-rsa/3/easyrsa; do
    if [ -x "$cand" ]; then EASYRSA_BIN="$cand"; break; fi
done
if [ -z "$EASYRSA_BIN" ]; then
    EASYRSA_BIN="$(command -v easyrsa || true)"
fi
if [ -z "$EASYRSA_BIN" ]; then
    echo "easyrsa.sh: easyrsa binary not found (apt install easy-rsa)" >&2
    exit 1
fi

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
    EASYRSA_REQ_CN="server" easyrsa gen-req server nopass
    easyrsa sign-req server server
    easyrsa gen-dh
    # tls-auth static key (OpenVPN 2.6: --genkey secret)
    if [ ! -e "$EASYRSA_PKI/ta.key" ]; then
        command -v openvpn >/dev/null 2>&1 || { echo "easyrsa.sh: openvpn binary not found (apt install openvpn)" >&2; exit 1; }
        openvpn --genkey secret "$EASYRSA_PKI/ta.key"
        chmod 600 "$EASYRSA_PKI/ta.key"
    fi
    # Empty CRL so the server always has a crl.pem to verify against.
    easyrsa gen-crl
    ;;

build-client)
    [ -n "$NAME" ] || usage
    [ -e "$EASYRSA_PKI/ca.crt" ] || { echo "easyrsa.sh: no CA in $EASYRSA_PKI -- run init first" >&2; exit 1; }
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
    easyrsa revoke "$NAME"
    easyrsa gen-crl
    ;;

gen-crl)
    easyrsa gen-crl
    ;;

*)
    usage
    ;;
esac

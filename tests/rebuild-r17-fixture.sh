#!/usr/bin/env bash
# rebuild-r17-fixture.sh -- rebuild the R17 fixture PKI that
# tests/r17_core.py (C2-03..C2-07) and tests/r17_flask.py /
# tests/r18_bg.py read via OPENVPN_CA_DIR / OVPN_CA_DIR.
#
# The fixture lives in /tmp and /tmp is wiped between rounds (the
# known hazard: R13/R14/R15 probes, R16 mutants and now this PKI
# were all lost to wipes). This script is the versioned rebuild
# recipe, so any round can regenerate it instead of re-deriving it.
#
# Layout (mirrors what R17 built with Easy-RSA):
#   <ca_dir>/pki/{ca.crt,index.txt,issued/<name>.crt,private/<name>.key}
#   users: alice (V, valid), bob (R, revoked), erin (V flag but cert
#   expired -- R9-P1-2: the flag lies, the expiry tells the truth),
#   carol (E, expired), dave (V, valid). Plus a server cert
#   (CN=server, filtered out of list_users by RESERVED_NAMES).
#
# Method: plain `openssl ca` (no easy-rsa binary in the sandbox).
# openssl ca writes index.txt itself in the real format (filename
# column is the literal `unknown`, serials match the issued certs),
# so the parser's serial-map path is exercised exactly like the
# original fixture. Order matters: carol is flipped V->E by
# `openssl ca -updatedb` BEFORE erin is issued, otherwise updatedb
# would flip erin too and C2-05 (V-but-past-expiry) would be lost.
#
# The suite also mutates the sibling fixture-server/server.conf
# (C1-13 renders port 51194 into it), so a second run of
# tests/r17_core.py fails C1-02/C1-03/C1-05/C1-08/C1-12 until the
# conf is reset to port 1194. This script resets it as its last
# step; if you run the suite twice without rebuilding, reset it
# by hand: render_server_conf("udp", 1194, server_dir=...,
# allow_port_change=True).
#
# Usage: bash tests/rebuild-r17-fixture.sh [ca_dir]
#   default ca_dir: /tmp/r17/fixture-ca
set -euo pipefail

CA_DIR="${1:-/tmp/r17/fixture-ca}"
PKI="$CA_DIR/pki"
rm -rf "$CA_DIR"
mkdir -p "$PKI"/{private,issued,newcerts,certs,crl} /tmp/r17-fixture-csr

# --- CA (self-signed, not recorded in index.txt) ---
openssl req -x509 -newkey rsa:2048 -keyout "$PKI/private/ca.key" \
  -out "$PKI/ca.crt" -days 3650 -subj "/CN=OpenVPN-CA" -nodes \
  -sha256 2>/dev/null

# --- minimal openssl ca config ---
cat > /tmp/r17-fixture-csr/openssl.cnf <<EOF
[ ca ]
default_ca = myca
[ myca ]
dir = $PKI
database = \$dir/index.txt
serial = \$dir/serial
new_certs_dir = \$dir/newcerts
certificate = \$dir/ca.crt
private_key = \$dir/private/ca.key
default_md = sha256
policy = policy_any
copy_extensions = none
unique_subject = no
[ policy_any ]
commonName = supplied
[ req_distinguished_name ]
EOF
: > "$PKI/index.txt"
printf 'unique_subject = no\n' > "$PKI/index.txt.attr"
printf '1000\n' > "$PKI/serial"

sign() { # sign <name> <startdate> <enddate>
  local name="$1" start="$2" end="$3"
  openssl req -newkey rsa:2048 -keyout "$PKI/private/$name.key" \
    -out "/tmp/r17-fixture-csr/$name.csr" -subj "/CN=$name" -nodes \
    -sha256 2>/dev/null
  openssl ca -batch -config /tmp/r17-fixture-csr/openssl.cnf \
    -in "/tmp/r17-fixture-csr/$name.csr" \
    -out "$PKI/issued/$name.crt" \
    -startdate "$start" -enddate "$end" -notext 2>/dev/null
}

FUTURE_START=20260101000000Z
FUTURE_END=20300101000000Z
PAST_START=20200101000000Z
PAST_END=20210101000000Z

sign alice "$FUTURE_START" "$FUTURE_END"
sign dave  "$FUTURE_START" "$FUTURE_END"
sign bob   "$FUTURE_START" "$FUTURE_END"
sign server "$FUTURE_START" "$FUTURE_END"
sign carol "$PAST_START" "$PAST_END"
# Flip carol V->E while erin does not exist yet.
openssl ca -batch -config /tmp/r17-fixture-csr/openssl.cnf -updatedb 2>/dev/null
# Revoke bob (V->R).
openssl ca -batch -config /tmp/r17-fixture-csr/openssl.cnf \
  -revoke "$PKI/issued/bob.crt" 2>/dev/null
# Erin LAST: V row with a past expiry, never passed through updatedb.
sign erin "$PAST_START" "$PAST_END"

# ta.key: the fixture must mirror the easyrsa layout the product reads.
# _rebuild_user_ovpn (panel/app.py) needs pki/ta.key to rebuild a user's
# .ovpn for the local download path (F5-01); without it the download
# 404s. OpenVPN static key V1, 2048-bit (256 bytes = 512 hex chars,
# 16 lines of 32). openssl rand -hex N outputs N BYTES (2N hex chars).
python3 -c "
import subprocess
rand = subprocess.run(['openssl', 'rand', '-hex', '256'],
                      capture_output=True, text=True, check=True).stdout.strip()
assert len(rand) == 512, len(rand)
lines = [rand[i:i+32] for i in range(0, 512, 32)]
open('$PKI/ta.key', 'w').write(
    '-----BEGIN OpenVPN Static key V1-----\n' + '\n'.join(lines) +
    '\n-----END OpenVPN Static key V1-----\n')
print('ta.key written (2048-bit static key)')
"

chmod 700 "$CA_DIR" "$PKI"
# Suites run as nobody (tests/README.md): the fixture must be traversable
# and writable by nobody, or the Flask/Core suites fail with EACCES/EPERM
# (render_server_conf chmods server.conf, which fails unless nobody owns
# it). Loosen ownership here so rebuild -> run works without hand repair.
chown -R nobody:nogroup "$CA_DIR" "$(dirname "$CA_DIR")/fixture-server" 2>/dev/null \
  || chmod -R a+rwX "$CA_DIR" "$(dirname "$CA_DIR")/fixture-server"
chmod 755 "$(dirname "$CA_DIR")"
echo "fixture rebuilt at $CA_DIR"
echo "--- index.txt ---"
cat "$PKI/index.txt"

# Reset the sibling fixture-server/server.conf to port 1194 (see the
# header note: the suite mutates it to 51194 on every run).
SERVER_DIR="$(dirname "$CA_DIR")/fixture-server"
if [ -f "$SERVER_DIR/server.conf" ]; then
  TREE="$(dirname "$0")/.."
  OPENVPN_CA_DIR="$CA_DIR" OPENVPN_SERVER_DIR="$SERVER_DIR" python3 -c "
import sys
sys.path.insert(0, '$TREE/core')
from pathlib import Path
from openvpn_manager import render_server_conf
render_server_conf('udp', 1194, server_dir=Path('$SERVER_DIR'),
                   allow_port_change=True)
print('server.conf reset to port 1194')
"
fi

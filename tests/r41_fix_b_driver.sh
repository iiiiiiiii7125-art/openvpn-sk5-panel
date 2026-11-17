#!/usr/bin/env bash
# Fix-B netns driver (AUDIT-R41): runs the probe matrix against one tree.
#
#   bash tests/r41_fix_b_driver.sh <tree> [live]
#
# Each cell runs in a fresh `unshare --user --map-root-user --net
# --mount` namespace: lo up, a per-mode /etc/hosts bind-mounted over
# the real one (private mount ns -- the host /etc/hosts is never
# touched), stub/hold listener on the blackhole/fast addresses, then
# the probe worker (tests/r41_fix_b_probe.py) with all panel state in
# fresh scratch dirs and proxy env stripped (curl must resolve
# ifconfig.me via /etc/hosts, never via the sandbox egress proxy).
#
# Matrix: blackhole x {disabled,enabled} x {status,sk5} (the stall
# cells) + fast x disabled x {status,sk5} (the probe still lands).
# With the extra `live` arg, one gate-faithful replay is appended:
# real TLS server + real curl login + /api/status at the old (10 s)
# and new (15 s) gate budgets under a blackholed ifconfig.me.
set -u
TREE="${1:?tree path required}"
RUN_LIVE="${2:-}"
WORK=/tmp/r41b
mkdir -p "$WORK"
printf '127.0.0.1 localhost\n127.0.0.3 ifconfig.me\n' > "$WORK/hosts-blackhole"
printf '127.0.0.1 localhost ifconfig.me\n' > "$WORK/hosts-fast"

cell() { # mode sk5 endpoint
  local mode="$1" sk5="$2" ep="$3"
  export R41B_MODE="$mode" R41B_SK5="$sk5" R41B_EP="$ep" R41B_TREE="$TREE"
  export R41B_DATA="$(mktemp -d /tmp/r41b-data-XXXXXX)"
  export R41B_SK5CFG="$(mktemp -d /tmp/r41b-sk5-XXXXXX)"
  echo "=== CELL mode=$mode sk5=$sk5 endpoint=$ep tree=$TREE"
  unshare --user --map-root-user --net --mount --fork \
    bash "$TREE/tests/r41_fix_b_inner.sh"
  echo "=== CELL rc=$? mode=$mode sk5=$sk5 endpoint=$ep"
}

cell blackhole disabled status
cell blackhole disabled sk5
cell blackhole enabled status
cell blackhole enabled sk5
cell fast disabled status
cell fast disabled sk5

if [ -n "$RUN_LIVE" ]; then
  export R41B_TREE="$TREE"
  export R41B_DATA="$(mktemp -d /tmp/r41b-data-XXXXXX)"
  export R41B_SK5CFG="$(mktemp -d /tmp/r41b-sk5-XXXXXX)"
  CERTDIR="$(mktemp -d /tmp/r41b-cert-XXXXXX)"
  openssl req -x509 -newkey rsa:2048 -keyout "$CERTDIR/key.pem" \
    -out "$CERTDIR/cert.pem" -days 2 -nodes -subj "/CN=127.0.0.1" \
    -addext "subjectAltName=IP:127.0.0.1" 2>/dev/null
  export R41B_CERT="$CERTDIR/cert.pem" R41B_KEY="$CERTDIR/key.pem"
  export R41B_PORT=18443
  echo "=== LIVE blackhole disabled tree=$TREE"
  unshare --user --map-root-user --net --mount --fork \
    bash "$TREE/tests/r41_fix_b_live.sh"
  echo "=== LIVE rc=$?"
fi
echo "=== DRIVER DONE tree=$TREE"

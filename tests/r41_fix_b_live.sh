#!/usr/bin/env bash
# Fix-B live gate replay: runs INSIDE `unshare` (started by the driver).
# Blackholed ifconfig.me (/etc/hosts -> 127.0.0.3 + hold listener),
# real TLS panel server on a scratch port, real curl login, then the
# install gate's exact /api/status curl at the OLD budget (10 s) and
# the NEW budget (15 s). Env (exported by the driver): R41B_TREE,
# R41B_DATA, R41B_SK5CFG, R41B_CERT, R41B_KEY, R41B_PORT.
set -u
ip link set lo up
mount --bind "/tmp/r41b/hosts-blackhole" /etc/hosts
mkdir -p "$R41B_DATA/etc-panel"
mount --bind "$R41B_DATA/etc-panel" /etc/openvpn-sk5-panel
if ! grep -q " /etc/openvpn-sk5-panel " /proc/mounts; then
  sleep 1
  mount --bind "$R41B_DATA/etc-panel" /etc/openvpn-sk5-panel
  grep -q " /etc/openvpn-sk5-panel " /proc/mounts \
    || { echo "R41B FATAL: panel bind-mount failed"; exit 99; }
fi
python3 "$R41B_TREE/tests/r41_fix_b_listen.py" --mode blackhole & LPID=$!
sleep 0.5
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  -u all_proxy -u ALL_PROXY \
  PYTHONPATH=/tmp/r41-l5-venv/lib/python3.12/site-packages \
  OVPN_PANEL_DATA_DIR="$R41B_DATA" OVPN_PANEL_SECRET_PATH="$R41B_DATA/secret.key" \
  OPENVPN_CA_DIR=/tmp/r41l2/fixture-ca OPENVPN_SERVER_DIR=/tmp/r41l2/fixture-server \
  OVPN_SK5_CONFIG_DIR="$R41B_SK5CFG" R41B_TREE="$R41B_TREE" \
  python3 "$R41B_TREE/tests/r41_fix_b_server.py" \
    "$R41B_PORT" "$R41B_CERT" "$R41B_KEY" & SRVPID=$!
for i in $(seq 1 40); do
  (echo > /dev/tcp/127.0.0.1/$R41B_PORT) 2>/dev/null && break
  sleep 0.5
done
PW="$(cat "$R41B_DATA/etc-panel/admin.pass")"
JAR="$(mktemp)"
curl -ks -c "$JAR" -o /dev/null -w 'live login http=%{http_code} secs=%{time_total}\n' \
  -X POST "https://127.0.0.1:$R41B_PORT/api/login" \
  -H 'Content-Type: application/json' --data "{\"password\": \"$PW\"}"
echo "--- gate replay: OLD budget --max-time 10 (must pass after the fix)"
curl -ks --max-time 10 -b "$JAR" -o /dev/null \
  -w 'live old-gate http=%{http_code} secs=%{time_total}\n' \
  "https://127.0.0.1:$R41B_PORT/api/status" || echo "live old-gate curl rc=$?"
echo "--- gate replay: NEW budget --max-time 15"
curl -ks --max-time 15 -b "$JAR" -o /dev/null \
  -w 'live new-gate http=%{http_code} secs=%{time_total}\n' \
  "https://127.0.0.1:$R41B_PORT/api/status" || echo "live new-gate curl rc=$?"
kill $SRVPID $LPID 2>/dev/null || true

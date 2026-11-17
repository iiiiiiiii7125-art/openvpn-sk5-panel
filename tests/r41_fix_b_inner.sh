#!/usr/bin/env bash
# Fix-B netns cell runner: runs INSIDE `unshare --user --map-root-user
# --net --mount` (started by tests/r41_fix_b_driver.sh).
# Brings lo up, bind-mounts the per-mode /etc/hosts over the real one
# (private mount ns: the host /etc/hosts is never touched), starts the
# stub/hold listener, then runs the probe worker. Env (exported by the
# driver): R41B_MODE, R41B_SK5, R41B_EP, R41B_TREE, R41B_DATA,
# R41B_SK5CFG.
set -u
ip link set lo up
mount --bind "/tmp/r41b/hosts-$R41B_MODE" /etc/hosts
# Keep the host /etc clean: the panel writes admin.pass to the hardcoded
# /etc/openvpn-sk5-panel/admin.pass when /etc is writable (root in this
# ns); hide the host dir behind a scratch bind.
mkdir -p "$R41B_DATA/etc-panel"
mount --bind "$R41B_DATA/etc-panel" /etc/openvpn-sk5-panel
# Loud if the bind did not take: without it the panel (root here)
# recreates /etc/openvpn-sk5-panel on the HOST and writes admin.pass
# there. Retry once, then fail the cell instead of polluting the host.
if ! grep -q " /etc/openvpn-sk5-panel " /proc/mounts; then
  sleep 1
  mount --bind "$R41B_DATA/etc-panel" /etc/openvpn-sk5-panel
  grep -q " /etc/openvpn-sk5-panel " /proc/mounts \
    || { echo "R41B FATAL: panel bind-mount failed"; exit 99; }
fi
python3 "$R41B_TREE/tests/r41_fix_b_listen.py" --mode "$R41B_MODE" & LPID=$!
sleep 0.5
# Strip EVERY proxy var: curl falls back to all_proxy/ALL_PROXY when the
# protocol-specific ones are unset, and the proxy host does not resolve
# inside the netns (fast rc=5) -- which would fake a fast probe.
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  -u all_proxy -u ALL_PROXY \
  PYTHONPATH=/tmp/r41-l5-venv/lib/python3.12/site-packages \
  OVPN_PANEL_DATA_DIR="$R41B_DATA" OVPN_PANEL_SECRET_PATH="$R41B_DATA/secret.key" \
  OPENVPN_CA_DIR=/tmp/r41l2/fixture-ca OPENVPN_SERVER_DIR=/tmp/r41l2/fixture-server \
  OVPN_SK5_CONFIG_DIR="$R41B_SK5CFG" R41B_TREE="$R41B_TREE" \
  python3 "$R41B_TREE/tests/r41_fix_b_probe.py" --mode "$R41B_MODE" \
    --sk5 "$R41B_SK5" --endpoint "$R41B_EP"
RC=$?
kill $LPID 2>/dev/null || true
exit $RC

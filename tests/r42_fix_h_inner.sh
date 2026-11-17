#!/usr/bin/env bash
# R42-FIX-H netns cell runner: runs INSIDE `unshare --user --map-root-user
# --net --mount` (started by tests/r42_fix_h_driver.sh).
# Brings lo up, bind-mounts the blackhole /etc/hosts over the real one
# (private mount ns: the host /etc/hosts is never touched), starts the
# hold listener, then runs the probe worker. Env (exported by the
# driver): R42FIXH_CELL, R42FIXH_TREE, R42FIXH_DATA, R42FIXH_SK5CFG.
set -u
ip link set lo up
mount --bind "/tmp/r42fixh/hosts-blackhole" /etc/hosts
# Keep the host /etc clean: the panel writes admin.pass to the hardcoded
# /etc/openvpn-sk5-panel/admin.pass when /etc is writable (root in this
# ns); hide the host dir behind a scratch bind.
mkdir -p "$R42FIXH_DATA/etc-panel"
mount --bind "$R42FIXH_DATA/etc-panel" /etc/openvpn-sk5-panel
# Loud if the bind did not take: without it the panel (root here)
# recreates /etc/openvpn-sk5-panel on the HOST and writes admin.pass
# there. Retry once, then fail the cell instead of polluting the host.
if ! grep -q " /etc/openvpn-sk5-panel " /proc/mounts; then
  sleep 1
  mount --bind "$R42FIXH_DATA/etc-panel" /etc/openvpn-sk5-panel
  grep -q " /etc/openvpn-sk5-panel " /proc/mounts \
    || { echo "R42FIXH FATAL: panel bind-mount failed"; exit 99; }
fi
python3 "$R42FIXH_TREE/tests/r42_fix_h_listen.py" & LPID=$!
sleep 0.5
# Strip EVERY proxy var: curl falls back to all_proxy/ALL_PROXY when the
# protocol-specific ones are unset, and the proxy host does not resolve
# inside the netns -- which would fake a fast probe.
env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
  -u all_proxy -u ALL_PROXY \
  PYTHONPATH=/tmp/r41-l5-venv/lib/python3.12/site-packages \
  OVPN_PANEL_DATA_DIR="$R42FIXH_DATA" OVPN_PANEL_SECRET_PATH="$R42FIXH_DATA/secret.key" \
  OPENVPN_CA_DIR=/tmp/r41l2/fixture-ca OPENVPN_SERVER_DIR=/tmp/r41l2/fixture-server \
  OVPN_SK5_CONFIG_DIR="$R42FIXH_SK5CFG" R42FIXH_TREE="$R42FIXH_TREE" \
  R42FIXH_CELL="$R42FIXH_CELL" \
  python3 "$R42FIXH_TREE/tests/r42_fix_h_probe.py"
RC=$?
kill $LPID 2>/dev/null || true
exit $RC

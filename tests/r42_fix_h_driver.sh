#!/usr/bin/env bash
# R42-FIX-H netns driver (AUDIT-R42, lane F3): runs the probe cells
# against one tree. Each cell runs in a fresh `unshare --user
# --map-root-user --net --mount` namespace: lo up, a blackhole
# /etc/hosts bind-mounted over the real one (private mount ns -- the
# host /etc/hosts is never touched), hold listeners on 127.0.0.3
# :80/:443/:1080, then the probe worker (tests/r42_fix_h_probe.py) with
# all panel state in fresh scratch dirs and proxy env stripped.
#
#   bash tests/r42_fix_h_driver.sh <tree>
#
# Cells: A1 status/no-stored-IP, A2 status/stored-IP (control),
# A3 ovpn-download + create-user, B1 agent get_status SK5-disabled,
# B2 agent get_status SK5-enabled-blackholed, C1 toggle-only save +
# sk5/disable under the mutation lock.
set -u
TREE="${1:?tree path required}"
WORK=/tmp/r42fixh
mkdir -p "$WORK"
printf '127.0.0.1 localhost\n127.0.0.3 api.ipify.org ifconfig.me\n' > "$WORK/hosts-blackhole"

cell() { # cell-name
  local c="$1"
  export R42FIXH_CELL="$c" R42FIXH_TREE="$TREE"
  export R42FIXH_DATA="$(mktemp -d /tmp/r42fixh-data-XXXXXX)"
  export R42FIXH_SK5CFG="$(mktemp -d /tmp/r42fixh-sk5-XXXXXX)"
  echo "=== CELL $c tree=$TREE"
  # The panel bind-mount needs the host mountpoint dir to exist; it
  # intermittently vanishes between cells (same flake the F3 lane
  # hit -- no product code removes it), so re-create it per cell.
  mkdir -p /etc/openvpn-sk5-panel
  unshare --user --map-root-user --net --mount --fork \
    bash "$TREE/tests/r42_fix_h_inner.sh"
  echo "=== CELL rc=$? $c"
}

cell A1
cell A2
cell A3
cell B1
cell B2
cell B3
cell C1
echo "=== DRIVER DONE tree=$TREE"

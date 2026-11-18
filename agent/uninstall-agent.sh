#!/usr/bin/env bash
# uninstall-agent.sh -- remove ovpn-agent from THIS machine.
#
# Stops + disables ovpn-agent.service and removes the agent install
# root (/opt/ovpn-agent), its config (/etc/ovpn-agent) and the unit
# file. The agent keeps polling its panel every 5 s until this runs:
# revoking the node in the panel only kills the token, so a revoked
# agent polls 401 forever (R47-L5-4). Run this on the node, then
# revoke the node in the panel (or the other way round -- either order
# ends with nothing polling).
#
# Usage: bash uninstall-agent.sh [-y|--yes]
#   -y / --yes : skip the confirmation prompt (non-interactive use).
# Paths honour OVPN_AGENT_INSTALL_ROOT / OVPN_AGENT_CONFIG_DIR when
# set (probe use); the defaults are the production paths install-agent.sh
# writes. Nothing under the panel tree is touched, so this also works
# after the panel itself was uninstalled.
set -euo pipefail

INSTALL_ROOT="${OVPN_AGENT_INSTALL_ROOT:-/opt/ovpn-agent}"
CONFIG_DIR="${OVPN_AGENT_CONFIG_DIR:-/etc/ovpn-agent}"
UNIT_FILE="${OVPN_AGENT_UNIT_FILE:-/etc/systemd/system/ovpn-agent.service}"

YES=0
for _a in "$@"; do
    case "$_a" in
        -y|--yes) YES=1 ;;
        *) echo "usage: bash uninstall-agent.sh [-y|--yes]" >&2; exit 2 ;;
    esac
done

if [ "$YES" -eq 0 ]; then
    read -r -p "确认卸载 ovpn-agent（停服务并删除 $INSTALL_ROOT 与 $CONFIG_DIR）？[y/N] " ans
    [ "$ans" = y ] || [ "$ans" = Y ] || { echo "已取消"; exit 1; }
fi

if [ -f "$UNIT_FILE" ]; then
    echo "stopping ovpn-agent.service..."
    systemctl disable --now ovpn-agent.service 2>/dev/null || true
else
    echo "ovpn-agent.service not installed; nothing to stop"
fi
rm -rf "$INSTALL_ROOT" "$CONFIG_DIR"
rm -f "$UNIT_FILE"
systemctl daemon-reload 2>/dev/null || true
systemctl reset-failed ovpn-agent.service 2>/dev/null || true
echo "ovpn-agent 已卸载：服务已停，$INSTALL_ROOT 与 $CONFIG_DIR 已删除"
echo "面板侧：若该节点还在面板节点列表里，记得在面板上吊销它（否则 token 仍有效）。"

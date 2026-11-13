#!/usr/bin/env bash
# Policy routing for the OpenVPN -> SK5 egress chain.
#
#   OpenVPN users: 10.8.0.0/24 (tun0)
#   sing-box tun:  tun1, 10.9.0.1/30 (sing-box owns 10.9.0.1)
#   Table 100:     default via 10.9.0.1 dev tun1 (metric 0)
#                  + blackhole default metric 200 (fallback, see below)
#   Rule:          from 10.8.0.0/24 lookup 100  (priority 100)
#
# THE KILL-SWITCH IS THE BLACKHOLE ROUTE, NOT THE TUN1 ROUTE
# (R13-BUG-1, live-13 §11 -- read this before touching table 100):
#   The tun1 route is device-bound: when sing-box dies, tun1
#   vanishes and the kernel DELETES the route, leaving table 100
#   empty. An empty table does NOT drop packets -- the lookup
#   falls through to the main table and VPN traffic silently
#   egresses direct, exposing the transit server's real IP. The
#   old model ("route dead -> no route -> packets dropped") was
#   wrong; twelve live rounds never caught it because S3 only
#   ever killed dante (the SK5), never sing-box itself.
#   enable() therefore installs a second, device-independent
#   route in table 100: `blackhole default metric 200`. While
#   tun1 is up its metric-0 route wins; the moment tun1 dies,
#   lookups fall to the blackhole and traffic is dropped instead
#   of leaking direct. disable() flushes table 100, which removes
#   the blackhole too -- direct mode must stay direct.
#   The blackhole does NOT make the chain "active": _policy_active()
#   (sk5_manager.py) still requires the tun1 route, so a
#   blackhole-only table correctly reports policy missing and the
#   health check auto-repairs it (see check_health()).
#
# HOW sing-box's OWN TRAFFIC STAYS OUT OF TABLE 100 (read this first):
#   The rule matches on SOURCE address only. sing-box runs on the host
#   and its sockets carry the host's own source IP (e.g. eth0's address),
#   never 10.8.0.0/24 -- so sing-box's TCP connection to the bought SK5
#   is looked up in the MAIN table and goes direct to the merchant.
#   Only packets whose source is a VPN user (10.8.0.x, arriving on tun0)
#   match the rule and enter table 100. There is deliberately NO
#   `from all lookup 100` rule anywhere: such a rule would loop
#   sing-box's own SK5 connection back into tun1 and kill the chain.
#   The script also refuses to run if a `from all lookup 100` rule
#   already exists (see enable() guard below).
#
# Ordering: sing-box OWNS tun1. It creates the device at startup
# (tun inbound, interface_name tun1) and the device vanishes when
# sing-box dies. This script NEVER creates tun1 any more (R24-P2-1 /
# BT): the old `enable` path called ensure_tun1 as a fallback when
# sing-box had not created the device yet, and the placeholder it
# built (UP, NO-CARRIER) wedged the chain -- it installed a
# linkdown route that carried nothing while _policy_active()
# reported the chain active, and sing-box could never restart
# against it (TUNSETIFF "Device or resource busy"). Both `enable`
# and `repair` now run the same repair semantics: re-install the
# blackhole and the rule, and install the tun1 route only once
# tun1 is live again (LOWER_UP, i.e. sing-box holds it). A call
# that finds no live tun1 exits 0 having secured the blackhole;
# the caller re-verifies, and the next 60 s tick completes the
# repair after sing-box recreates the device. A dead placeholder
# left by a pre-fix enable is deleted by the Python caller
# (sk5_manager._remove_dead_tun1_placeholder: triple dead check +
# no sing-box holder -- see there for the race analysis), never by
# this script, so a live device is never at risk here.
#
#   enable   install rule + routes + forwarding (idempotent)
#            -- same repair semantics as `repair` since BT: no
#            device is ever created, tun1 route only when live.
#   repair   re-install rule + blackhole only; install the tun1
#            route only if tun1 is LIVE (sing-box holds it).
#            Never creates tun1 -- see R14-BUG-1 above.
#   disable  remove rule + flush table 100 (incl. the fallback
#            blackhole -- direct mode must stay direct), leave
#            main table alone
#   restore  boot-time restore (P1-9): re-apply ONLY when the stored
#            SK5 config says enabled; when disabled, direct mode must
#            survive a reboot untouched (installing the rule then
#            would steer VPN traffic into table 100, where the
#            fallback blackhole would drop traffic the operator
#            meant to be direct). Restore runs in REPAIR_MODE
#            (R23-P2-1): at boot sing-box may not have created tun1
#            yet, so no device is created here (a placeholder
#            would block sing-box's own start -- R14-BUG-1 /
#            R24-P2-1; since BT no verb creates one at all).
#            Repair only re-installs the blackhole + rule and
#            installs the tun1 route once tun1 is live; the 60 s
#            health check completes the repair after sing-box
#            recreates the device. A stored config that exists but
#            parsed (R23-P2-2) is a loud failure, never a silent
#            "not enabled": restore dies before touching any
#            policy state so the operator sees it in the unit
#            status instead of rebooting into silent direct.
#   status   print rule / table 100 / route-get triple
#
# Concurrency (R6-BUG-1, live-R6): enable/disable/restore are
# serialized by an flock on /run/openvpn-sk5-panel/policy-routing.lock
# (see acquire_lock). The old code was check-then-add -- rule_exists
# followed by `ip rule add` -- and a second writer landing in
# between made the add fail EEXIST ("RTNETLINK answers: File
# exists") even though the desired end state was already true:
# first panel enable 500, retry 200. The add itself is also
# idempotent now (see add_rule): a failed add re-checks, and if
# our rule is present that IS success; otherwise it dies with
# the real error from `ip rule add`. A failed enable rolls
# back only what THIS invocation added (see rollback_enable), so
# it never leaves partial kernel state behind.
# NOTE (R8-P2-1, live-7 §11): a FOREIGN rule sharing priority
# 100 is NOT a conflict -- the kernel allows several different
# selectors at one priority and only an identical rule raises
# EEXIST, so an occupant-error branch for "priority taken" was
# dead code (and could misdiagnose a real failure) and was
# removed; a foreign rule at priority 100 is left alone.
#
# Requires root for enable/disable. Never touches the main-table
# default route. Debian 12 / Ubuntu 22.04 / 24.04, iproute2 + iptables.
set -euo pipefail

TABLE=100
VPN_NET="10.8.0.0/24"
TUN_DEV="tun1"
TUN_ADDR="10.9.0.1/30"
TUN_GW="10.9.0.1"
RULE_PRIO=100
SYSCTL_FILE="/etc/sysctl.d/99-openvpn-sk5.conf"
LOCK_DIR="/run/openvpn-sk5-panel"
LOCK_FILE="$LOCK_DIR/policy-routing.lock"
# Stored SK5 config. do_restore() is the only reader in this script;
# the panel and agent read the same file through
# sk5_manager._load_config() (which validates strictly, R20-P2-1).
SK5_CONFIG_PATH="/etc/openvpn-sk5-panel/sk5.json"
# Set to 1 by add_rule() when THIS invocation added the rule; the
# rollback in do_enable() only ever deletes a rule we added ourselves.
RULE_ADDED_BY_ME=0

log() { echo "[policy-routing] $*"; }
die() { echo "[policy-routing] ERROR: $*" >&2; exit 1; }
need_root() { [ "$(id -u)" -eq 0 ] || die "must run as root ($1)"; }

acquire_lock() {
    # Serialize the writers (enable/disable/restore). Without this,
    # two enables racing each other both pass rule_exists and the
    # second `ip rule add` dies EEXIST (R6-BUG-1). flock is released
    # when this process exits, so a dead holder can never wedge the
    # lock. Bounded wait: the panel calls this script with a 30 s
    # subprocess timeout (sk5_manager._run), so 20 s leaves margin
    # for the actual work. `status` takes no lock (read-only).
    command -v flock >/dev/null 2>&1 \
        || die "flock(1) (util-linux) is required but not installed"
    mkdir -p "$LOCK_DIR" 2>/dev/null \
        || die "cannot create lock dir $LOCK_DIR"
    exec 9>"$LOCK_FILE" \
        || die "cannot open lock file $LOCK_FILE"
    flock -w 20 9 \
        || die "another policy-routing operation is already running (lock $LOCK_FILE held >20s); retry later"
}

tun1_live() {
    # Live = sing-box holds the device up. A dead placeholder
    # (pre-BT enable-path leftover) shows UP but NO-CARRIER /
    # state DOWN and no LOWER_UP; a sing-box-owned tun1 shows
    # UP,LOWER_UP (the daemon holds the fd open, so the device
    # vanishes the moment sing-box dies). Routing via a dead
    # device installs a linkdown route that SHADOWS the blackhole
    # (ip route get returns it) while carrying nothing -- and
    # _policy_active() greps the route line, so it would report
    # the chain active. Repair therefore routes via tun1 only
    # when it is live. (grep without -q: see rule_exists -- a
    # grep -q that exits early can SIGPIPE its writer under
    # pipefail.)
    ip link show dev "$TUN_DEV" 2>/dev/null | grep "LOWER_UP" >/dev/null
}

rule_exists() {
    # NOTE: grep WITHOUT -q, output to /dev/null. `grep -q` exits on
    # the first match and closes the pipe; a slow writer (or a long
    # rule list) then dies on SIGPIPE (141), and with `set -o
    # pipefail` that makes this function LIE -- "rule absent" when
    # it is present. That is the second R6-BUG-1 trigger: the
    # pre-existing rule passes the guard on retry but the first
    # call can fail it, and the add then dies EEXIST. A grep that
    # consumes the whole stream can never SIGPIPE its writer.
    #
    # NOTE: match OUR rule only -- priority $RULE_PRIO. A
    # same-selector rule at another priority is a duplicate
    # (dedup_rule removes it), not our rule: treating it as
    # "present" would make add_rule skip the add and then leave
    # the kernel with no rule at all after the dedup.
    ip rule show 2>/dev/null | grep "^$RULE_PRIO:.*from $VPN_NET lookup $TABLE" >/dev/null
}

add_rule() {
    # Add the policy rule idempotently.
    #
    # R6-BUG-1 (live-R6): the old code was check-then-add --
    # `rule_exists` followed by `ip rule add`. A second writer
    # landing in between (second enable, boot-time restore) made
    # the add fail EEXIST ("RTNETLINK answers: File exists") even
    # though the desired end state was already true: first enable
    # 500, retry 200. The flock in acquire_lock() serializes
    # writers now, but the add itself must still be idempotent:
    # on a failed add, re-check -- if our rule is present, that
    # IS success; if not, die with the real error from the add.
    #
    # NOTE (R8-P2-1, live-7 §11): the kernel allows several
    # different selectors at one priority -- `ip rule add` only
    # fails EEXIST for an IDENTICAL rule. A foreign rule sharing
    # priority 100 is therefore not an error and is left alone;
    # an earlier "occupant" branch that diagnosed "priority 100
    # is already used by ..." was dead code built on a
    # priority-exclusive stub model, and could misdiagnose a
    # real failure (e.g. EPERM) as an occupant conflict, so it
    # was removed. The failure below reports the real `_err`.
    if rule_exists; then
        log "rule already present: from $VPN_NET lookup $TABLE"
        dedup_rule
        return 0
    fi
    local _err="" _rc=0
    _err="$(ip rule add from "$VPN_NET" table "$TABLE" priority "$RULE_PRIO" 2>&1)" || _rc=$?
    if [ "$_rc" -eq 0 ]; then
        RULE_ADDED_BY_ME=1
        log "added rule: from $VPN_NET lookup $TABLE prio $RULE_PRIO"
        dedup_rule
        return 0
    fi
    if rule_exists; then
        log "rule already present (added concurrently): from $VPN_NET lookup $TABLE"
        dedup_rule
        return 0
    fi
    die "cannot add policy rule from $VPN_NET lookup $TABLE prio $RULE_PRIO: ${_err}. No policy state was changed by this call; retrying the enable is safe."
}

rollback_enable() {
    # Undo ONLY what this invocation added, so a failed enable
    # leaves the kernel exactly as it found it. Never touches
    # pre-existing state: a rule that was already there before
    # this call is not ours to delete. (The table-100 route needs
    # no rollback: `ip route replace` either succeeds or changes
    # nothing, and iptables_add only warns, never fails.)
    if [ "${RULE_ADDED_BY_ME:-0}" = "1" ]; then
        ip rule del from "$VPN_NET" table "$TABLE" priority "$RULE_PRIO" 2>/dev/null || true
        RULE_ADDED_BY_ME=0
        log "rolled back the rule this (failed) enable added"
    fi
}

dedup_rule() {
    # Normalize: the same selector+table at another priority is a
    # redundant duplicate of our rule (the kernel tries the lowest
    # priority first, so ours at 100 always wins). Remove it so
    # the rule set stays unique -- and so a later disable cannot
    # leave a stray copy behind that would keep steering VPN
    # traffic into the flushed table 100 (an empty table falls
    # through to the main table, i.e. silent direct -- the exact
    # R13-BUG-1 leak; see the header note). Only exact
    # selector+table matches are touched; a same-selector rule for
    # another table is somebody else's and is left alone.
    # NOTE: `|| true` -- when no duplicate exists, grep finds nothing
    # and exits 1; under `set -o pipefail` that would make this whole
    # pipeline fail and `set -e` would kill the caller mid-enable /
    # mid-disable (a "no duplicates" result is success, not failure).
    ip rule show 2>/dev/null | grep "from $VPN_NET lookup $TABLE" | while read -r _prio _rest; do
        _prio="${_prio%:}"
        case "$_prio" in
            ''|*[!0-9]*) continue ;;
            "$RULE_PRIO") continue ;;
        esac
        ip rule del from "$VPN_NET" table "$TABLE" priority "$_prio" 2>/dev/null || true
        log "removed duplicate rule: from $VPN_NET lookup $TABLE prio $_prio"
    done || true
    return 0  # no duplicates (grep found nothing) is success, not failure
}

iptables_add() { # iptables_add <chain> <rule...>: add only if absent
    # -C exit codes: 0 = present, 1 = absent, other = iptables itself
    # broken (e.g. nft-only box without the compat layer). The ACCEPTs
    # are needed only when FORWARD policy is DROP, so a broken
    # iptables must warn -- not abort the whole enable() halfway.
    local rc=0
    iptables -C "$@" 2>/dev/null || rc=$?
    if [ "$rc" -eq 0 ]; then
        return 0
    elif [ "$rc" -eq 1 ]; then
        iptables -A "$@" 2>/dev/null || log "WARN: iptables -A $* failed, continuing"
    else
        log "WARN: iptables unavailable (rc=$rc), skipping rule: $*"
    fi
}

iptables_del() { # iptables_del <chain> <rule...>: delete only if present
    local rc=0
    while true; do
        iptables -C "$@" 2>/dev/null || rc=$?
        [ "$rc" -eq 0 ] || break
        iptables -D "$@" 2>/dev/null || break
        rc=0
    done
}

do_enable() {
    need_root "enable"
    # Guard: a from-all rule for table 100 would capture sing-box's own
    # SK5 connection and loop it into tun1. Refuse to run beside one.
    if ip rule show | grep -E "from all lookup $TABLE([^0-9]|$)" >/dev/null; then
        die "dangerous rule 'from all lookup $TABLE' exists; remove it first"
    fi
    # R14-BUG-1 / R24-P2-1 (BT): this script NEVER creates tun1,
    # in either verb. sing-box owns the device; a script-created
    # placeholder blocks the daemon's own restart (TUNSETIFF
    # "Device or resource busy") and installs a linkdown route
    # that carries nothing while fooling _policy_active(). The
    # tun1 route below is installed only once tun1 is live.
    log "not creating $TUN_DEV (sing-box owns it)"
    # IP forwarding (persisted so a reboot keeps the chain working).
    printf 'net.ipv4.ip_forward=1\n' > "$SYSCTL_FILE"
    sysctl -w net.ipv4.ip_forward=1 >/dev/null
    # Fallback blackhole FIRST (R13-BUG-1 layer 1): install it
    # before the rule, so there is never a window where the rule
    # steers VPN traffic into an empty table (empty table =
    # fall-through to main = silent direct). The blackhole is
    # device-independent, so it survives tun1's death; the tun1
    # route (metric 0) wins over it (metric 200) while tun1 is
    # up. If the blackhole cannot be installed, die before the
    # rule is added -- an enable without the kill-switch must
    # fail loudly, never silently ship a chain with no fallback.
    local _bh_err=""
    if ! _bh_err="$(ip route replace blackhole default metric 200 table "$TABLE" 2>&1)"; then
        die "cannot install table $TABLE fallback blackhole route: ${_bh_err}. No policy state was changed by this call; retrying the enable is safe."
    fi
    log "table $TABLE: blackhole default metric 200 (fallback kill-switch)"
    # Policy rule (idempotent, see add_rule) + table-100 default
    # route (replace = idempotent).
    add_rule
    # The tun1 route: install it ONLY via a LIVE device. A dead
    # placeholder (or no device at all) must not get a route: the
    # route would be linkdown, it SHADOWS the blackhole at lookup
    # level (ip route get returns it) while carrying nothing, and
    # _policy_active() would then report the chain active
    # (R24-P2-1). If tun1 is not live, drop any stale route left
    # by an earlier (pre-fix) enable so the table honestly shows
    # blackhole-only.
    if ! tun1_live; then
        ip route del default via "$TUN_GW" dev "$TUN_DEV" table "$TABLE" 2>/dev/null || true
        log "tun1 not live (sing-box has not recreated it); table $TABLE stays on the fallback blackhole -- the next health check completes the repair once sing-box is up"
    else
        local _route_err=""
        if ! _route_err="$(ip route replace default via "$TUN_GW" dev "$TUN_DEV" table "$TABLE" 2>&1)"; then
            rollback_enable
            die "cannot install table $TABLE default route via $TUN_GW dev $TUN_DEV: ${_route_err}. No policy state was changed by this call; retrying the enable is safe."
        fi
        log "table $TABLE: default via $TUN_GW dev $TUN_DEV"
    fi
    # Kernel forwarding between the OpenVPN tun and the sing-box tun.
    # (Traffic tun0 -> tun1 is delivered to sing-box locally; these
    # ACCEPTs cover the forward path and the return path. No
    # MASQUERADE on tun1: sing-box is the endpoint, not a NAT hop.)
    iptables_add FORWARD -i tun0 -o "$TUN_DEV" -j ACCEPT
    iptables_add FORWARD -i "$TUN_DEV" -o tun0 -j ACCEPT
    iptables_add INPUT -i "$TUN_DEV" -j ACCEPT
    iptables_add OUTPUT -o "$TUN_DEV" -j ACCEPT
    # Self-check: the enable must leave the rule AND both routes
    # actually in place. A silent partial application is worse
    # than a loud failure -- verify, and roll back our own rule
    # if the end state is not what we promised, so a failed
    # enable never leaves the kernel half-configured. (A leftover
    # blackhole in the now-unreferenced table is inert: no rule
    # steers traffic into it, and the next enable replaces it.)
    if ! rule_exists; then
        rollback_enable
        die "policy rule did not stick after enable (from $VPN_NET lookup $TABLE not found); no policy state was changed by this call, retry the enable"
    fi
    # The tun1 route is only installed (and hence only checked)
    # when tun1 is live; a call that finds no live tun1
    # deliberately leaves the table blackhole-only. The route
    # check is linkdown-sensitive (R24-P2-1 layer 2): a linkdown
    # route carries nothing, so it must not satisfy the self-check
    # even though it contains the same "default via ... dev tun1"
    # substring. (Unreachable in practice -- a live tun1's route
    # cannot be linkdown -- but the check must not be fooled if a
    # stale linkdown line ever survives the delete above.)
    if tun1_live; then
        if ! ip route show table "$TABLE" 2>/dev/null | grep "default via $TUN_GW dev $TUN_DEV" | grep -v "linkdown" >/dev/null; then
            rollback_enable
            die "table $TABLE default route did not stick after enable; no policy state was changed by this call, retry the enable"
        fi
    fi
    if ! ip route show table "$TABLE" 2>/dev/null | grep "^blackhole default" >/dev/null; then
        rollback_enable
        die "table $TABLE fallback blackhole route did not stick after enable; no policy state was changed by this call, retry the enable"
    fi
    log "enabled: $VPN_NET -> table $TABLE -> $TUN_DEV -> SK5"
}

do_disable() {
    need_root "disable"
    # Remove ONLY our rule and table 100. Main-table default route,
    # OpenVPN's tun0 routes and every other rule are left untouched.
    if rule_exists; then
        ip rule del from "$VPN_NET" table "$TABLE" priority "$RULE_PRIO" 2>/dev/null || \
            ip rule del from "$VPN_NET" table "$TABLE" 2>/dev/null || true
        log "removed rule: from $VPN_NET lookup $TABLE"
    else
        log "rule already absent"
    fi
    # Also drop any same-selector duplicate at another priority:
    # left behind, it would keep matching VPN traffic into the
    # flushed table 100 (empty table falls through to the main
    # table, i.e. silent direct) while the panel reports direct.
    dedup_rule
    # The flush removes the fallback blackhole too -- that is
    # deliberate: disable() is an operator decision for direct
    # mode, and a leftover blackhole would drop VPN traffic the
    # operator meant to be direct.
    ip route flush table "$TABLE" 2>/dev/null || true
    log "flushed table $TABLE (incl. fallback blackhole)"
    iptables_del FORWARD -i tun0 -o "$TUN_DEV" -j ACCEPT
    iptables_del FORWARD -i "$TUN_DEV" -o tun0 -j ACCEPT
    iptables_del INPUT -i "$TUN_DEV" -j ACCEPT
    iptables_del OUTPUT -o "$TUN_DEV" -j ACCEPT
    # Leave tun1 itself alone: if sing-box is still running it owns
    # the device; if it is stopped the device vanishes with it.
    # (Delete it manually only when sing-box is confirmed stopped:
    #  ip link delete dev tun1)
    log "disabled: table $TABLE flushed, main table untouched"
}

read_stored_enabled() {
    # Read the stored SK5 config and print ONE verdict word on stdout:
    #   enabled  -- parses, top-level object, enabled is true (or 1)
    #   disabled -- parses, top-level object, enabled is false (or 0)
    #              or absent (an old config without the key)
    #   missing  -- the file does not exist: never configured
    #   corrupt:<reason> -- the file exists but cannot be trusted:
    #              unreadable, invalid JSON, top-level not an object,
    #              or `enabled` present with a wrong type. The reason
    #              names only the error class / JSON type, never file
    #              content (the file holds SK5 credentials).
    # The three "not enabled" outcomes are deliberately distinct
    # (R23-P2-2): the old one-liner collapsed missing / list /
    # garbage to the same rc=1 and restore logged "SK5 not enabled"
    # for all three, rebooting an enabled chain into silent direct.
    # The reader always exits 0; the caller branches on the word.
    command -v python3 >/dev/null 2>&1 \
        || die "python3 is required to read the stored SK5 config"
    python3 - "$SK5_CONFIG_PATH" <<'PYEOF'
import json, sys
path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as f:
        raw = f.read()
except FileNotFoundError:
    print("missing")
    sys.exit(0)
except UnicodeDecodeError as exc:
    # Not UTF-8 at all: same verdict as invalid JSON (the bytes
    # cannot be a stored config); the exception text carries only
    # a byte position, never file content.
    print("corrupt:invalid JSON (%s)" % exc)
    sys.exit(0)
except OSError as exc:
    print("corrupt:unreadable (%s)" % exc.__class__.__name__)
    sys.exit(0)
try:
    data = json.loads(raw)
except ValueError as exc:
    print("corrupt:invalid JSON (%s)" % exc)
    sys.exit(0)
if not isinstance(data, dict):
    print("corrupt:top-level JSON is not an object (got %s)" % type(data).__name__)
    sys.exit(0)
enabled = data.get("enabled", False)
if isinstance(enabled, bool):
    print("enabled" if enabled else "disabled")
elif type(enabled) is int and enabled in (0, 1):
    print("enabled" if enabled == 1 else "disabled")
else:
    print("corrupt:enabled must be a boolean (got %s)" % type(enabled).__name__)
PYEOF
}

do_restore() {
    need_root "restore"
    # Boot-time restore (P1-9): the ip rule is runtime state and dies
    # with a reboot, but the stored sk5.json survives. Only re-apply
    # when it says enabled -- otherwise the host must stay in direct
    # mode after a reboot, not steer VPN traffic into table 100
    # (where the fallback blackhole would drop traffic the operator
    # meant to be direct).
    #
    # R23-P2-1: restore runs in REPAIR_MODE, never full enable.
    # At boot there is no enable()-style wait for tun1 (the daemon
    # may still be starting -- Type=simple means "spawned", not
    # "tun ready"). Since BT no verb creates a placeholder at all
    # (R24-P2-1: it would block sing-box's own start -- R14-BUG-1,
    # FATAL "file exists" x5 -> StartLimitBurst -> unit failed,
    # chain permanently blackholed); repair only re-installs the
    # blackhole + rule and installs the tun1 route once tun1 is
    # live; the 60 s health check completes the repair after
    # sing-box recreates the device.
    #
    # R23-P2-2: a stored config that exists but cannot be parsed
    # is a loud failure, never a silent "not enabled". Dying here
    # changes no policy state (no rule, no table) -- the unit
    # lands failed and the journal names the file and the reason,
    # so the operator fixes it by hand instead of rebooting into
    # silent direct.
    local verdict
    verdict="$(read_stored_enabled)"
    case "$verdict" in
        missing)
            log "no stored SK5 config, leaving main table alone"
            ;;
        disabled)
            log "SK5 not enabled in stored config, leaving main table alone"
            ;;
        enabled)
            log "stored SK5 config says enabled, restoring policy routing"
            REPAIR_MODE=1
            do_enable
            ;;
        corrupt:*)
            die "stored SK5 config ${SK5_CONFIG_PATH} is damaged (${verdict#corrupt:}); fix or remove it by hand -- refusing to change policy state"
            ;;
        *)
            die "internal error: unexpected restore verdict '${verdict}'"
            ;;
    esac
}

do_status() {
    echo "--- ip rule ---"
    ip rule show
    echo "--- table $TABLE ---"
    ip route show table "$TABLE" 2>&1 || true
    echo "--- route-get: VPN user source ---"
    # Source MUST be the host's own tun0 address 10.8.0.1 (R7-BUG-4):
    # 10.8.0.2 is a client address, never a local source, and the
    # kernel rejects the lookup (Network is unreachable). Same
    # family as R3-BUG-4 (gate scripts already use 10.8.0.1).
    ip route get 1.1.1.1 from 10.8.0.1 2>&1 || true
    echo "--- route-get: host source (contrast, must stay main) ---"
    ip route get 1.1.1.1 2>&1 || true
    echo "--- tun1 ---"
    ip addr show dev "$TUN_DEV" 2>&1 || echo "$TUN_DEV: absent"
}

usage() {
    echo "usage: $0 {enable|repair|disable|restore|status}" >&2
    exit 2
}

# Lock once per invocation for the writers (enable/repair/disable/restore):
# do_restore calls do_enable internally (with REPAIR_MODE=1, R23-P2-1),
# so the lock must NOT be taken inside do_* (nested acquire would
# deadlock). `status` is read-only and takes no lock.
case "${1:-}" in
    enable)  acquire_lock; do_enable ;;
    repair)  acquire_lock; REPAIR_MODE=1; do_enable ;;
    disable) acquire_lock; do_disable ;;
    restore) acquire_lock; do_restore ;;
    status)  do_status ;;
    *)       usage ;;
esac

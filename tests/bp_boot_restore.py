#!/usr/bin/env python3
"""BP fix probe (bp_boot_restore.py) -- R23-P2-1 + R23-P2-2 (boot restore).

P2-1 (boot race): `do_restore` used to run a FULL `enable` --
`ensure_tun1` first, then blackhole/rule. At boot sing-box may not
have created tun1 yet (its unit is Type=simple: "started" means
spawned, not tun-ready), and `do_restore` had no tun1 wait (unlike
`enable()`, which waits 10x0.5 s). A placeholder created here races
sing-box's own start: sing-box FATALS with "configure tun interface:
file exists" x5 -> StartLimitBurst (5/120 s) -> unit failed, chain
permanently blackholed (R14-BUG-1 shape, live-14 proved the
diagnosis). The policy unit also had only After= on sing-box, no
Wants=/Requires= -- After= only orders.

The fix (option (a) -- restore runs in REPAIR_MODE, chosen over
"wait for tun1 then fall back to repair"): a wait only narrows the
race -- on a slow 512 MB box sing-box may still miss the window,
and then the code needs repair semantics anyway; two mechanisms
would mask each other. Repair semantics eliminate the race
deterministically: restore never creates a device, only re-installs
the blackhole + rule, and installs the tun1 route once tun1 is
live; the 60 s health check completes the repair after sing-box
recreates the device. The only cost is a blackhole-only table
until the next tick when sing-box is late -- safe (traffic is
dropped, not leaked) and honest (_policy_active still reports
missing until the route lands). The unit gains
Wants=openvpn-sk5-singbox.service -- Wants, NOT Requires:
Requires= would CANCEL this restore when sing-box fails to start,
and then no blackhole would be installed at all, so VPN traffic
would silently egress direct -- the exact outcome P1-9 exists to
prevent. Wants= pulls the daemon into the boot transaction
best-effort while restore still runs (and secures the blackhole)
even if sing-box is down.

P2-2 (silent downgrade): the old one-liner collapsed missing /
list / garbage sk5.json to the same rc=1 and restore logged
"SK5 not enabled" for all three, rebooting an enabled chain into
silent direct. The fix splits the read into a verdict word
(missing / disabled / enabled / corrupt:<reason>): a config that
exists but cannot be parsed is a LOUD failure -- the restore dies
(naming file + reason + manual fix) BEFORE touching any policy
state, so the unit lands failed instead of the host rebooting
into silent direct. `enabled` with a wrong type (e.g. the string
"false") is corrupt too, same rationale as BK's stored-shape
strictness (stored files only ever hold real bools); 0/1 ints are
accepted like BK. An absent `enabled` key stays disabled (old
configs without the key).

What the probe proves (real policy-routing.sh, private mount ns,
bind-mounted /etc/openvpn-sk5-panel + /etc/sysctl.d + lock dir,
stateful mock `ip` reused from the BO probe -- kernel semantics
are NOT re-proven here; BO part 1 proved the placeholder /
LOWER_UP / linkdown-shadow mechanism):
  C1-C11: restore verdicts + repair semantics + loud corrupt +
         no-policy-change on corrupt + two-tick completion.
  C12: full `enable` with tun1 absent creates NO device either
       (R24-P2-1 / BT -- enable now shares repair semantics).
  U1: the unit file dependency lines (static check, stated as such).

Run: python3 tests/bp_boot_restore.py
Exit code = number of FAILs. Requires: unshare, python3.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TREE / "tests"))
import bo_tun1_repair as bo

RESULTS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + detail) if detail else ""))


def run_restore(tmp, *args):
    """Run the REAL policy-routing.sh in a private mount ns with
    bind-mounted config dir + /etc/sysctl.d + lock dir, mock ip on
    PATH (host untouched)."""
    inner = (
        "mkdir -p /etc/openvpn-sk5-panel /etc/sysctl.d /run/openvpn-sk5-panel && "
        "mount --bind \"$1/cfgdir\" /etc/openvpn-sk5-panel && "
        "mount --bind \"$1/sysctld\" /etc/sysctl.d && "
        "mount --bind \"$1/rundir\" /run/openvpn-sk5-panel && "
        "export PATH=\"$1/mockbin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\" && "
        "export MOCK_IP_STATE=\"$1/ipstate\" && "
        "bash \"" + str(TREE / "egress" / "policy-routing.sh") + "\" "
        + " ".join(args) + "; echo \"rc=$?\""
    )
    r = subprocess.run(["unshare", "-rm", "bash", "-c", inner, "x", str(tmp)],
                       capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


def main():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (tmp / "cfgdir").mkdir()
        (tmp / "sysctld").mkdir()
        (tmp / "rundir").mkdir()
        (tmp / "ipstate").mkdir()
        mockbin = tmp / "mockbin"
        mockbin.mkdir()
        (mockbin / "ip").write_text(bo.BO_MOCK_IP, encoding="utf-8")
        (mockbin / "sysctl").write_text(bo.MOCK_SYSCTL, encoding="utf-8")
        (mockbin / "iptables").write_text(bo.MOCK_IPTABLES, encoding="utf-8")
        for f in ("ip", "sysctl", "iptables"):
            (mockbin / f).chmod(0o755)

        cfg = tmp / "cfgdir" / "sk5.json"

        def state():
            st = tmp / "ipstate"
            rules = (st / "rules").read_text(encoding="utf-8") if (st / "rules").exists() else ""
            routes = (st / "routes").read_text(encoding="utf-8") if (st / "routes").exists() else ""
            log = (st / "log").read_text(encoding="utf-8") if (st / "log").exists() else ""
            tun1 = (st / "tun1").read_text(encoding="utf-8").strip() if (st / "tun1").exists() else None
            return rules, routes, log, tun1

        def reset_ip():
            for f in ("rules", "routes", "log", "tun1"):
                (tmp / "ipstate" / f).unlink(missing_ok=True)

        def last_line(out):
            return (out.strip().splitlines() or [""])[-1]

        # C1: config missing -> rc=0, quiet "no stored config",
        # no rule / no routes touched.
        cfg.unlink(missing_ok=True)
        reset_ip()
        out = run_restore(tmp, "restore")
        rules, routes, log, _ = state()
        cell("C1 restore with no sk5.json is quiet, touches no policy state",
             "rc=0" in out and "no stored SK5 config" in out
             and rules.strip() == "" and routes.strip() == "",
             last_line(out))

        # C2: enabled:false -> rc=0, "not enabled", no policy state.
        cfg.write_text('{"enabled": false}', encoding="utf-8")
        reset_ip()
        out = run_restore(tmp, "restore")
        rules, routes, _, _ = state()
        cell("C2 restore with enabled:false is quiet, touches no policy state",
             "rc=0" in out and "SK5 not enabled in stored config" in out
             and rules.strip() == "" and routes.strip() == "",
             last_line(out))

        # C3: enabled:true + tun1 absent -> rc=0, NO device created,
        # blackhole + rule present, NO tun1 route (blackhole-only).
        cfg.write_text('{"enabled": true}', encoding="utf-8")
        reset_ip()
        out = run_restore(tmp, "restore")
        rules, routes, log, tun1 = state()
        cell("C3 restore enabled + tun1 absent creates NO device, blackhole-only table",
             "rc=0" in out and "ip tuntap add" not in log
             and tun1 is None
             and "100: from 10.8.0.0/24 lookup 100" in rules
             and "blackhole default metric 200" in routes
             and "default via 10.9.0.1 dev tun1" not in routes,
             last_line(out) + " | routes=" + routes.replace("\n", ","))

        # C4: enabled:true + tun1 LIVE -> rc=0, tun1 route installed,
        # still no device creation.
        reset_ip()
        (tmp / "ipstate" / "tun1").write_text("live", encoding="utf-8")
        out = run_restore(tmp, "restore")
        rules, routes, log, tun1 = state()
        cell("C4 restore enabled + live tun1 installs the tun1 route",
             "rc=0" in out and "ip tuntap add" not in log
             and tun1 == "live"
             and "default via 10.9.0.1 dev tun1" in routes
             and "blackhole default metric 200" in routes,
             last_line(out))

        # C5: enabled:true + DEAD placeholder + stale linkdown route
        # -> rc=0, stale route REMOVED, device untouched.
        reset_ip()
        (tmp / "ipstate" / "tun1").write_text("dead", encoding="utf-8")
        (tmp / "ipstate" / "routes").write_text(
            "blackhole default metric 200\ndefault via 10.9.0.1 dev tun1\n",
            encoding="utf-8")
        out = run_restore(tmp, "restore")
        rules, routes, log, tun1 = state()
        cell("C5 restore enabled + dead tun1 drops the stale linkdown route, touches no device",
             "rc=0" in out and "ip tuntap add" not in log
             and tun1 == "dead"
             and "default via 10.9.0.1 dev tun1" not in routes
             and "blackhole default metric 200" in routes
             and "ip route del default via 10.9.0.1 dev tun1 table 100" in log,
             last_line(out) + " | routes=" + routes.replace("\n", ","))

        # C6: list-shaped config -> rc!=0, log names the file + the
        # reason, NO policy state changed.
        cfg.write_bytes(b"[1, 2]")
        reset_ip()
        out = run_restore(tmp, "restore")
        rules, routes, _, _ = state()
        cell("C6 restore with list sk5.json dies loudly, changes no policy state",
             "rc=0" not in out
             and "/etc/openvpn-sk5-panel/sk5.json" in out
             and "not an object" in out and "got list" in out
             and "fix or remove it by hand" in out
             and rules.strip() == "" and routes.strip() == "",
             last_line(out)[:170])

        # C7: garbage config -> rc!=0, log names the file + invalid
        # JSON, NO policy state changed.
        cfg.write_bytes(b"\x00\xffgarbage")
        reset_ip()
        out = run_restore(tmp, "restore")
        rules, routes, _, _ = state()
        cell("C7 restore with garbage sk5.json dies loudly, changes no policy state",
             "rc=0" not in out
             and "/etc/openvpn-sk5-panel/sk5.json" in out
             and "invalid JSON" in out
             and "fix or remove it by hand" in out
             and rules.strip() == "" and routes.strip() == "",
             last_line(out)[:170])

        # C8: enabled as a STRING ("false") -> corrupt, rc!=0, no
        # policy change (BK's stored-shape strictness, same family).
        cfg.write_text('{"enabled": "false"}', encoding="utf-8")
        reset_ip()
        out = run_restore(tmp, "restore")
        rules, routes, _, _ = state()
        cell("C8 restore with enabled as a string dies loudly (corrupt), changes no policy state",
             "rc=0" not in out
             and "must be a boolean" in out and "got str" in out
             and rules.strip() == "" and routes.strip() == "",
             last_line(out)[:170])

        # C9a: enabled:0 -> disabled path, rc=0, no policy state.
        cfg.write_text('{"enabled": 0}', encoding="utf-8")
        reset_ip()
        out = run_restore(tmp, "restore")
        rules, routes, _, _ = state()
        cell("C9a restore with enabled:0 takes the quiet disabled path",
             "rc=0" in out and "SK5 not enabled in stored config" in out
             and rules.strip() == "" and routes.strip() == "",
             last_line(out))
        # C9b: enabled:1 + live tun1 -> enabled path, route lands.
        cfg.write_text('{"enabled": 1}', encoding="utf-8")
        reset_ip()
        (tmp / "ipstate" / "tun1").write_text("live", encoding="utf-8")
        out = run_restore(tmp, "restore")
        rules, routes, _, _ = state()
        cell("C9b restore with enabled:1 takes the enabled path (route lands on live tun1)",
             "rc=0" in out
             and "default via 10.9.0.1 dev tun1" in routes
             and "blackhole default metric 200" in routes,
             last_line(out))

        # C10: corrupt config with PRE-EXISTING policy state ->
        # state byte-identical afterwards (the die happens before
        # any policy call, not just on an empty table).
        cfg.write_bytes(b"not json at all")
        (tmp / "ipstate" / "rules").write_text(
            "100: from 10.8.0.0/24 lookup 100\n", encoding="utf-8")
        (tmp / "ipstate" / "routes").write_text(
            "blackhole default metric 200\ndefault via 10.9.0.1 dev tun1\n",
            encoding="utf-8")
        before_rules = (tmp / "ipstate" / "rules").read_bytes()
        before_routes = (tmp / "ipstate" / "routes").read_bytes()
        out = run_restore(tmp, "restore")
        after_rules = (tmp / "ipstate" / "rules").read_bytes()
        after_routes = (tmp / "ipstate" / "routes").read_bytes()
        cell("C10 corrupt restore leaves pre-existing policy state byte-identical",
             "rc=0" not in out
             and before_rules == after_rules and before_routes == after_routes,
             last_line(out)[:120])

        # C11: two-tick boot sequence -- restore (tun1 absent) ->
        # blackhole-only; sing-box "starts" (device live); restore
        # again -> tun1 route lands. No device creation either tick.
        cfg.write_text('{"enabled": true}', encoding="utf-8")
        reset_ip()
        out1 = run_restore(tmp, "restore")
        _, routes1, log1, tun1a = state()
        (tmp / "ipstate" / "log").write_text("", encoding="utf-8")
        (tmp / "ipstate" / "tun1").write_text("live", encoding="utf-8")
        out2 = run_restore(tmp, "restore")
        _, routes2, log2, tun1b = state()
        cell("C11 two-tick boot: restore (absent) -> sing-box starts -> restore installs route",
             "rc=0" in out1 and "rc=0" in out2
             and "ip tuntap add" not in log1 + log2
             and tun1a is None and tun1b == "live"
             and "default via 10.9.0.1 dev tun1" not in routes1
             and "default via 10.9.0.1 dev tun1" in routes2,
             "tick1 routes=" + routes1.replace("\n", ",")
             + " | tick2 routes=" + routes2.replace("\n", ","))

        # C12: full `enable` with tun1 absent creates NO device --
        # blackhole + rule only, NO tun1 route (R24-P2-1 / BT:
        # this cell used to assert the placeholder was created --
        # that pinned the defective behavior itself, same
        # legitimate correction family as BH-03(c) / BN-Q5 / BR-W2.
        # The enable verb now shares repair semantics.)
        reset_ip()
        out = run_restore(tmp, "enable")
        rules, routes, log, tun1 = state()
        cell("C12 enable with tun1 absent creates NO device, blackhole-only table",
             "rc=0" in out and "ip tuntap add mode tun dev tun1" not in log
             and tun1 is None
             and "default via 10.9.0.1 dev tun1" not in routes
             and "blackhole default metric 200" in routes,
             last_line(out))

        # U1: unit file dependency lines (static text check).
        # "Requires=" appears in the comment explaining why it is
        # NOT used, so match directive lines, not the substring.
        unit = (TREE / "systemd" / "openvpn-sk5-policy.service").read_text(encoding="utf-8")
        lines = unit.splitlines()
        after = [l for l in lines if l.startswith("After=")]
        wants = [l for l in lines if l.startswith("Wants=")]
        cell("U1 policy unit Wants sing-box (not Requires), After still orders it",
             len(after) == 1 and "openvpn-sk5-singbox.service" in after[0]
             and len(wants) == 1 and "openvpn-sk5-singbox.service" in wants[0]
             and not any(l.startswith("Requires=") for l in lines),
             f"After={after} Wants={wants}")

    fails = sum(1 for _, ok in RESULTS if not ok)
    print(f"\nTOTAL {len(RESULTS)} cells, FAIL {fails}: "
          f"{[n for n, ok in RESULTS if not ok]}")
    return fails


if __name__ == "__main__":
    sys.exit(main())

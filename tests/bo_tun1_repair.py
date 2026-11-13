#!/usr/bin/env python3
"""BO fix probe (bo_tun1_repair.py) -- R14-BUG-1 (high):
the health-check self-heal re-created a dead tun1 and systemd burned
all 5 restarts against it, chain permanently blackholed.

The bug (live-14 §10): sing-box dies -> tun1 vanishes; the 60 s
health check's _repair_policy() re-ran policy-routing.sh enable;
ensure_tun1 re-created tun1 as a dead placeholder (UP, NO-CARRIER,
state DOWN); sing-box's restart then FATALs with
"configure tun interface: file exists" (its tun inbound creates
the device itself and does not adopt an existing one);
systemd Restart=on-failure tried 5 times, hit StartLimitBurst
(5/120 s), unit failed. Manual recovery proved the diagnosis:
`ip link del tun1` + restart -> sing-box starts cleanly, next
health tick re-installs the route -> policy_repaired, traffic
back via SK5, same TCP client never disconnected.

The fix (option (a) -- chosen over (b) delete-the-dead-device):
repair never creates the device, it only re-installs the blackhole
+ rule and installs the tun1 route once tun1 is LIVE again
(LOWER_UP, i.e. sing-box holds it). Rationale: (a) cannot delete
a live device by mistake (no device-state judgement at delete
time, no race with a sing-box that is mid-start); (b) would have
to distinguish "dead placeholder" from "live device" at delete
time and could race a restarting sing-box. Trade-off of (a):
repair of a dead-sing-box chain completes one tick later than (b)
would -- the first tick secures blackhole+rule only, the tun1
route waits for sing-box to recreate the device. That delay is
safe (traffic is blackholed, not leaking) and honest
(_policy_active still reports missing until the route lands).
The two options were NOT both implemented -- they would mask
each other. BM layer 1 (blackhole) is untouched.

What each part proves -- and what it deliberately does NOT:
  Part 1 (T1-T5): REAL kernel behavior, real tun devices, private
    netns (`unshare -rn`). This proves the mechanism the fix
    relies on: a second TUNSETIFF on the same name fails
    "Device or resource busy" (the sing-box FATAL, verbatim);
    deleting the dead device lets creation succeed again (the
    manual recovery); a placeholder shows NO-CARRIER/state DOWN
    with NO LOWER_UP while a held device shows UP,LOWER_UP;
    a route via a dead device installs as linkdown and SHADOWS
    the blackhole at lookup level (`ip route get` returns it) --
    so repairing via a dead device would also fool
    _policy_active(); closing the holder's fd makes the device
    vanish (sing-box death). It does NOT prove the script uses
    LOWER_UP -- that is part 2.
  Part 2 (R1-R8): the REAL policy-routing.sh, run as root in a
    private mount ns (bind-mounted /etc/sysctl.d + lock dir, so
    the host is untouched), against a STATEFUL MOCK `ip` that
    models the tun1 device state (absent / dead placeholder /
    live) in its `link show` output. This proves repair never
    creates tun1, installs the route only via a live device,
    drops a stale linkdown route, stays idempotent, completes
    the two-tick sequence, and -- since BT (R24-P2-1) -- that
    full `enable` now shares repair semantics and creates NO
    device either (R5 updated from the old placeholder
    assertion, BH-03(c) family).
  Part 3 (B1-B4): the REAL sk5_manager.check_health() against a
    scratch OVPN_SK5_CONFIG_DIR, reusing the BM probe's Model
    (which now models the `repair` verb and device-level tun1
    state). This proves the health check actually calls the
    `repair` verb (not `enable`), never creates the device, and
    completes the repair on the next tick once sing-box is back.
    It does NOT prove the script works on a real host -- that is
    live-15 (kill sing-box -> blackhole -> systemd auto-restart
    succeeds -> recovery via SK5 within 60 s, fully unattended).

Run: python3 tests/bo_tun1_repair.py
Exit code = number of FAILs. Requires: unshare, ip, python3.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TREE / "egress"))
sys.path.insert(0, str(TREE / "tests"))
import bm_blackhole_selfheal as bm

RESULTS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + detail) if detail else ""))


def run(cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------- part 1
# Real kernel, real tun devices, private netns. The fd-held device is
# the sing-box-owned tun1; the tuntap-created device is the placeholder
# ensure_tun1 used to make (and repair used to re-make).
KERNEL_SCRIPT = r"""
import os, struct, subprocess, sys, fcntl
def sh(*args):
    r = subprocess.run(list(args), capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()
def state():
    rc, out = sh("ip", "link", "show", "dev", "tun1")
    return out.splitlines()[0] if rc == 0 and out else None
sh("ip", "link", "set", "lo", "up")
sh("ip", "addr", "add", "10.8.0.1/24", "dev", "lo")
sh("ip", "route", "add", "default", "dev", "lo", "table", "main")
sh("ip", "rule", "add", "from", "10.8.0.0/24", "lookup", "100", "priority", "100")
# T0: can this host create tun at all? (sandbox: yes; restricted host: no)
rc1, err1 = sh("ip", "tuntap", "add", "mode", "tun", "dev", "tun1")
if rc1 != 0:
    print("SKIP tun unavailable: " + err1[:120])
    sys.exit(0)
# T1: a second TUNSETIFF on the same name fails (the sing-box FATAL).
rc2, err2 = sh("ip", "tuntap", "add", "mode", "tun", "dev", "tun1")
print("T1 " + ("PASS" if rc2 != 0 and "Device or resource busy" in err2 else "FAIL")
      + " | second create rc=%d err=%s" % (rc2, err2[:100]))
# T2: delete the dead device -> create succeeds again (manual recovery).
sh("ip", "link", "del", "tun1")
rc3, err3 = sh("ip", "tuntap", "add", "mode", "tun", "dev", "tun1")
print("T2 " + ("PASS" if rc3 == 0 else "FAIL") + " | recreate rc=%d %s" % (rc3, err3[:80]))
# T3: placeholder shape (tuntap + addr + up, no holder): NO-CARRIER,
# state DOWN, NO LOWER_UP; route installs as linkdown; route get
# returns the linkdown route (it SHADOWS the blackhole).
sh("ip", "addr", "add", "10.9.0.1/30", "dev", "tun1")
sh("ip", "link", "set", "dev", "tun1", "mtu", "1400", "up")
st = state() or ""
rc_r, _ = sh("ip", "route", "add", "default", "via", "10.9.0.1", "dev", "tun1", "table", "100")
sh("ip", "route", "add", "blackhole", "default", "metric", "200", "table", "100")
rc_g, out_g = sh("ip", "route", "get", "1.1.1.1", "from", "10.8.0.1")
print("T3 " + ("PASS" if ("LOWER_UP" not in st and "NO-CARRIER" in st
      and "state DOWN" in st and rc_r == 0 and rc_g == 0 and "dev tun1" in out_g)
      else "FAIL") + " | " + st[:110] + " | get=" + out_g.replace("\n", " ")[:90])
sh("ip", "link", "del", "tun1")
# T4: held device (sing-box-owned): fd open + up -> UP,LOWER_UP;
# route get returns dev tun1.
fd = os.open("/dev/net/tun", os.O_RDWR)
ifr = struct.pack("16sH22s", b"tun1", 0x0001 | 0x1000, b"\0" * 22)  # IFF_TUN | IFF_NO_PI
fcntl.ioctl(fd, 0x400454ca, ifr)  # TUNSETIFF
# The held device needs its address too: without 10.9.0.1/30 the
# via-10.9.0.1 route cannot resolve and the lookup EINVALs.
sh("ip", "addr", "add", "10.9.0.1/30", "dev", "tun1")
sh("ip", "link", "set", "dev", "tun1", "mtu", "1400", "up")
st2 = state() or ""
rc_r2, _ = sh("ip", "route", "add", "default", "via", "10.9.0.1", "dev", "tun1", "table", "100")
rc_g2, out_g2 = sh("ip", "route", "get", "1.1.1.1", "from", "10.8.0.1")
print("T4 " + ("PASS" if ("LOWER_UP" in st2 and rc_r2 == 0 and rc_g2 == 0 and "dev tun1" in out_g2)
      else "FAIL") + " | " + st2[:110] + " | get=" + out_g2.replace("\n", " ")[:90])
# T5: holder closes -> device vanishes (sing-box death).
os.close(fd)
rc5, _ = sh("ip", "link", "show", "dev", "tun1")
print("T5 " + ("PASS" if rc5 != 0 else "FAIL") + " | link show rc=%d after fd close" % rc5)
"""


def part1_kernel():
    with tempfile.TemporaryDirectory() as d:
        script = Path(d) / "kernel.py"
        script.write_text(KERNEL_SCRIPT, encoding="utf-8")
        r = run(["unshare", "-rn", "python3", str(script)])
    out = r.stdout + r.stderr
    if out.startswith("SKIP") or "SKIP tun unavailable" in out:
        print("PART 1 SKIPPED: " + out.strip().splitlines()[0])
        return
    if r.returncode != 0:
        cell("T0 netns harness runs", False, f"rc={r.returncode} {out[:200]}")
        return
    cell("T0 netns harness runs", True)
    for line in out.splitlines():
        if line.startswith("T") and (" PASS" in line or " FAIL" in line):
            name, rest = line.split(" ", 1)
            ok = " PASS" in line
            detail = rest.split(" | ", 1)[1] if " | " in rest else ""
            cell({"T1": "T1 second TUNSETIFF fails 'Device or resource busy' (sing-box FATAL mechanism)",
                  "T2": "T2 delete dead tun1 -> create succeeds (manual recovery)",
                  "T3": "T3 placeholder is NO-CARRIER/state DOWN, no LOWER_UP; linkdown route shadows blackhole",
                  "T4": "T4 held tun1 is UP,LOWER_UP; route get returns dev tun1",
                  "T5": "T5 fd close -> tun1 vanishes (sing-box death)"}[name],
                 ok, detail[:160])


# ---------------------------------------------------------------- part 2
# Real policy-routing.sh against a stateful mock `ip` that models the
# tun1 device state (absent / dead placeholder / live) in `link show`.
BO_MOCK_IP = r"""#!/bin/sh
# Stateful mock ip for the BO probe: like the BM mock, plus device
# state -- $S/tun1 holds "dead" (tuntap placeholder: NO-CARRIER,
# state DOWN, no LOWER_UP) or "live" (sing-box holds it: UP,LOWER_UP).
# Kernel semantics are NOT modeled here -- they are proven by part 1.
S="${MOCK_IP_STATE:?}"
mkdir -p "$S"
echo "ip $*" >> "$S/log"
case "$1 $2" in
  "rule show") cat "$S/rules" 2>/dev/null; exit 0;;
  "rule add")
    grep -qx "100: from 10.8.0.0/24 lookup 100" "$S/rules" 2>/dev/null \
      || echo "100: from 10.8.0.0/24 lookup 100" >> "$S/rules"
    exit 0;;
  "rule del")
    if [ -f "$S/rules" ]; then
      grep -vx "100: from 10.8.0.0/24 lookup 100" "$S/rules" > "$S/rules.tmp" || true
      mv "$S/rules.tmp" "$S/rules"
    fi
    exit 0;;
  "route show") cat "$S/routes" 2>/dev/null; exit 0;;
  "route replace")
    if [ "$3" = "blackhole" ]; then
      if [ -n "${MOCK_IP_NO_BLACKHOLE:-}" ]; then exit 0; fi
      grep -v "^blackhole default" "$S/routes" 2>/dev/null > "$S/routes.tmp" || true
      mv "$S/routes.tmp" "$S/routes" 2>/dev/null || true
      echo "blackhole default metric 200" >> "$S/routes"
    else
      grep -v "^default via" "$S/routes" 2>/dev/null > "$S/routes.tmp" || true
      mv "$S/routes.tmp" "$S/routes" 2>/dev/null || true
      echo "default via 10.9.0.1 dev tun1" >> "$S/routes"
    fi
    exit 0;;
  "route del")
    grep -v "^default via" "$S/routes" 2>/dev/null > "$S/routes.tmp" || true
    mv "$S/routes.tmp" "$S/routes" 2>/dev/null || true
    exit 0;;
  "route flush") : > "$S/routes"; exit 0;;
  "route get")
    if grep -q "^default via" "$S/routes" 2>/dev/null; then
      echo "1.1.1.1 from 10.8.0.1 dev tun1 table 100"; exit 0
    fi
    echo "RTNETLINK answers: Invalid argument" >&2; exit 2;;
  "link show")
    if [ -f "$S/tun1" ]; then
      if [ "$(cat "$S/tun1")" = live ]; then
        echo "2: tun1: <POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP> mtu 1400 qdisc fq_codel state UNKNOWN mode DEFAULT group default qlen 500"
      else
        echo "2: tun1: <NO-CARRIER,POINTOPOINT,MULTICAST,NOARP,UP> mtu 1400 qdisc fq_codel state DOWN mode DEFAULT group default qlen 500"
      fi
      exit 0
    fi
    exit 1;;
  "tuntap add")
    if [ -f "$S/tun1" ]; then
      echo "ioctl(TUNSETIFF): Device or resource busy" >&2; exit 1
    fi
    echo dead > "$S/tun1"; exit 0;;
  "addr add") exit 0;;
  "addr show")
    [ -f "$S/tun1" ] && echo "inet 10.9.0.1/30"
    exit 0;;
  "link set") exit 0;;
  *) exit 0;;
esac
"""

MOCK_SYSCTL = "#!/bin/sh\nexit 0\n"
MOCK_IPTABLES = """#!/bin/sh
# -C -> 1 (absent, so -A runs); -A/-D -> 0.
echo "iptables $*" >> "${MOCK_IP_STATE:?}/log"
if [ "$1" = "-C" ]; then exit 1; fi
exit 0
"""


def run_script(tmp, *args, extra_env=None):
    """Run the REAL policy-routing.sh in a private mount ns with
    bind-mounted /etc/sysctl.d + lock dir (host untouched)."""
    env = dict(os.environ)
    env["MOCK_IP_STATE"] = str(tmp / "ipstate")
    if extra_env:
        env.update(extra_env)
    inner = (
        "mkdir -p /etc/sysctl.d /run/openvpn-sk5-panel && "
        "mount --bind \"$1/sysctld\" /etc/sysctl.d && "
        "mount --bind \"$1/rundir\" /run/openvpn-sk5-panel && "
        "export PATH=\"$1/mockbin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\" && "
        "export MOCK_IP_STATE=\"$1/ipstate\" && "
        + (f"export MOCK_IP_NO_BLACKHOLE=1 && " if extra_env and extra_env.get("MOCK_IP_NO_BLACKHOLE") else "")
        + "bash \"" + str(TREE / "egress" / "policy-routing.sh") + "\" "
        + " ".join(args) + "; echo \"rc=$?\""
    )
    r = subprocess.run(["unshare", "-rm", "bash", "-c", inner, "x", str(tmp)],
                       capture_output=True, text=True, timeout=120, env=env)
    return r.stdout + r.stderr


def part2_script():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (tmp / "sysctld").mkdir()
        (tmp / "rundir").mkdir()
        (tmp / "ipstate").mkdir()
        mockbin = tmp / "mockbin"
        mockbin.mkdir()
        (mockbin / "ip").write_text(BO_MOCK_IP, encoding="utf-8")
        (mockbin / "sysctl").write_text(MOCK_SYSCTL, encoding="utf-8")
        (mockbin / "iptables").write_text(MOCK_IPTABLES, encoding="utf-8")
        for f in ("ip", "sysctl", "iptables"):
            (mockbin / f).chmod(0o755)

        def state():
            st = tmp / "ipstate"
            rules = (st / "rules").read_text(encoding="utf-8") if (st / "rules").exists() else ""
            routes = (st / "routes").read_text(encoding="utf-8") if (st / "routes").exists() else ""
            log = (st / "log").read_text(encoding="utf-8") if (st / "log").exists() else ""
            tun1 = (st / "tun1").read_text(encoding="utf-8").strip() if (st / "tun1").exists() else None
            return rules, routes, log, tun1

        def last_line(out):
            return (out.strip().splitlines() or [""])[-1]

        # R1: repair with tun1 absent -> rc=0, no device created,
        # blackhole + rule present, NO tun1 route (blackhole-only table).
        out = run_script(tmp, "repair")
        rules, routes, log, tun1 = state()
        cell("R1 repair with tun1 absent creates NO device, blackhole-only table",
             "rc=0" in out and "ip tuntap add" not in log
             and tun1 is None
             and "100: from 10.8.0.0/24 lookup 100" in rules
             and "blackhole default metric 200" in routes
             and "default via 10.9.0.1 dev tun1" not in routes,
             last_line(out) + " | routes=" + routes.replace("\n", ","))
        # R2: repair with tun1 LIVE (sing-box holds it), route missing
        # -> rc=0, tun1 route installed, still no device creation.
        (tmp / "ipstate" / "tun1").write_text("live", encoding="utf-8")
        out = run_script(tmp, "repair")
        rules, routes, log, tun1 = state()
        cell("R2 repair with live tun1 installs the tun1 route",
             "rc=0" in out and "ip tuntap add" not in log
             and tun1 == "live"
             and "default via 10.9.0.1 dev tun1" in routes
             and "blackhole default metric 200" in routes,
             last_line(out))
        # R3: repair with a DEAD placeholder + stale linkdown route
        # -> rc=0, stale route REMOVED, device untouched (still dead),
        # blackhole + rule present.
        (tmp / "ipstate" / "tun1").write_text("dead", encoding="utf-8")
        out = run_script(tmp, "repair")
        rules, routes, log, tun1 = state()
        cell("R3 repair with dead tun1 drops the stale linkdown route, touches no device",
             "rc=0" in out and "ip tuntap add" not in log
             and tun1 == "dead"
             and "default via 10.9.0.1 dev tun1" not in routes
             and "blackhole default metric 200" in routes
             and "ip route del default via 10.9.0.1 dev tun1 table 100" in log,
             last_line(out) + " | routes=" + routes.replace("\n", ","))
        # R4: repair twice with tun1 live -> idempotent.
        (tmp / "ipstate" / "tun1").write_text("live", encoding="utf-8")
        out1 = run_script(tmp, "repair")
        out2 = run_script(tmp, "repair")
        rules, routes, _, _ = state()
        cell("R4 double repair with live tun1 is idempotent",
             "rc=0" in out1 and "rc=0" in out2
             and routes.count("default via 10.9.0.1 dev tun1") == 1
             and routes.count("blackhole default metric 200") == 1,
             f"tun1={routes.count('default via')} bh={routes.count('blackhole')}")
        # R5: full enable with tun1 absent creates NO device --
        # blackhole + rule only, NO tun1 route (R24-P2-1 / BT:
        # this cell used to assert the placeholder was created --
        # that pinned the defective behavior itself, same
        # legitimate correction family as BH-03(c) / BN-Q5 / BR-W2.
        # The enable verb now shares repair semantics.)
        run_script(tmp, "disable")
        (tmp / "ipstate" / "tun1").unlink(missing_ok=True)
        out = run_script(tmp, "enable")
        rules, routes, log, tun1 = state()
        cell("R5 enable with tun1 absent creates NO device, blackhole-only table",
             "rc=0" in out and "ip tuntap add mode tun dev tun1" not in log
             and tun1 is None
             and "default via 10.9.0.1 dev tun1" not in routes
             and "blackhole default metric 200" in routes,
             last_line(out))
        # R6: repair where the blackhole cannot stick fails LOUDLY
        # and rolls the rule back (same contract as BM S7).
        run_script(tmp, "disable")
        out = run_script(tmp, "repair", extra_env={"MOCK_IP_NO_BLACKHOLE": "1"})
        rules, routes, _, _ = state()
        cell("R6 repair with blackhole not sticking fails loudly + rolls back rule",
             "rc=0" not in out
             and "fallback blackhole route did not stick" in out
             and "lookup 100" not in rules,
             last_line(out)[:160])
        # R7: the R14-BUG-1 sequence end to end -- repair while
        # sing-box is dead (no device), then sing-box "starts"
        # (test side flips the device live), repair again -> the
        # tun1 route lands, both repairs rc=0.
        run_script(tmp, "disable")
        (tmp / "ipstate" / "tun1").unlink(missing_ok=True)
        # The ip log accumulates across cells (R5's enable created a
        # tun1); truncate it so the no-create assertion is per-tick.
        (tmp / "ipstate" / "log").write_text("", encoding="utf-8")
        out1 = run_script(tmp, "repair")
        _, routes1, log1, tun1a = state()
        (tmp / "ipstate" / "log").write_text("", encoding="utf-8")
        (tmp / "ipstate" / "tun1").write_text("live", encoding="utf-8")
        out2 = run_script(tmp, "repair")
        _, routes2, log2, tun1b = state()
        cell("R7 two-tick sequence: repair (dead) -> sing-box starts -> repair installs route",
             "rc=0" in out1 and "rc=0" in out2
             and "ip tuntap add" not in log1 + log2
             and tun1a is None and tun1b == "live"
             and "default via 10.9.0.1 dev tun1" not in routes1
             and "default via 10.9.0.1 dev tun1" in routes2,
             "tick1 routes=" + routes1.replace("\n", ",") + " | tick2 routes=" + routes2.replace("\n", ","))
        # R8: disable flushes blackhole + rule (BM S3 equivalent).
        out = run_script(tmp, "disable")
        rules, routes, _, _ = state()
        cell("R8 disable removes rule and blackhole",
             "rc=0" in out and "lookup 100" not in rules
             and "blackhole" not in routes and routes.strip() == "",
             f"rules={rules!r} routes={routes!r}")


# ---------------------------------------------------------------- part 3
# Real sk5_manager.check_health() against a scratch config dir;
# _run() answered by the BM probe's Model (which now models the
# `repair` verb and device-level tun1 state), test_sk5() stubbed.
BASE_CFG = {"host": "127.0.0.1", "port": 11080, "username": "",
            "password": "", "enabled": True, "fail_open": False,
            "udp_over_tcp": False}


def part3_health():
    # B1: sing-box dead, device absent, rule + blackhole present,
    # route missing -> repair verb (NOT enable), no device created,
    # action blackholed_kill_switch, detail says HELD (never
    # direct). (R15-BUG-1 correction: this cell used to expect
    # policy_missing -- that pinned the defective verdict. A
    # repair that did everything its own contract promises
    # (blackhole + rule in place) is not a failed repair; the
    # chain is dead only because the daemon is down. Same
    # legitimate correction family as BH-03(c) and BN's Q5.)
    m, model, r, d = bm.health_case(
        {}, bm.Model(rule=True, tun1=False, blackhole=True,
                     singbox=False, tun1_device=False), False)
    cell("B1 dead sing-box: check_health calls repair (not enable), creates no device",
         r["healthy"] is False and r["action"] == "blackholed_kill_switch"
         and model.verbs == ["repair"] and model.apply_calls == 1
         and model.tun1_device is False and model.tun1 is False
         and "held by the fallback blackhole" in r["detail"]
         and "egresses direct" not in r["detail"]
         and "did not stick" not in r["detail"],
         f"action={r['action']} verbs={model.verbs}")
    # B2: two ticks -- tick 1 device absent (repair, no route,
    # blackholed_kill_switch per R15-BUG-1); sing-box comes back
    # (device live); tick 2 completes the repair -> policy_repaired,
    # healthy.
    d = tempfile.mkdtemp()
    (Path(d) / "sk5.json").write_text(json.dumps(BASE_CFG), encoding="utf-8")
    m = bm.fresh_import(d)
    model = bm.Model(rule=True, tun1=False, blackhole=True,
                     singbox=False, tun1_device=False)
    m._run = model.run
    m.test_sk5 = lambda: {"tcp_ok": True, "udp_ok": True,
                          "egress_ip": "203.0.113.7"}
    r1 = m.check_health()
    model.singbox = True
    model.tun1_device = True  # sing-box recreated the device
    r2 = m.check_health()
    cell("B2 two ticks: repair (dead) -> sing-box back -> policy_repaired",
         r1["healthy"] is False and r1["action"] == "blackholed_kill_switch"
         and r2["healthy"] is True and r2["action"] == "policy_repaired"
         and model.verbs == ["repair", "repair"]
         and model.apply_calls == 2 and model.tun1 is True,
         f"r1={r1['action']} r2={r2['action']} verbs={model.verbs}")
    # B3: BM H1 regression via the repair verb -- sing-box up,
    # device live, route missing -> policy_repaired.
    m, model, r, d = bm.health_case(
        {}, bm.Model(rule=True, tun1=False, blackhole=True,
                     singbox=True), True)
    cell("B3 live device + missing route repairs to healthy (BM H1 via repair)",
         r["healthy"] is True and r["action"] == "policy_repaired"
         and model.verbs == ["repair"] and model.apply_calls == 1,
         f"action={r['action']} verbs={model.verbs}")
    # B4: repair fails (dead sing-box, no device) -> policy_missing
    # with the repair-failure note; the verb is still repair.
    m, model, r, d = bm.health_case(
        {}, bm.Model(rule=True, tun1=False, blackhole=True,
                     singbox=False, tun1_device=False,
                     apply_fail=True), False)
    cell("B4 repair failure -> policy_missing with re-apply note",
         r["healthy"] is False and r["action"] == "policy_missing"
         and model.verbs == ["repair"]
         and "auto-repair: policy re-apply failed" in r["detail"]
         and "held by the fallback blackhole" in r["detail"],
         r["detail"][:160])


def main():
    part1_kernel()
    part2_script()
    part3_health()
    fails = sum(1 for _, ok in RESULTS if not ok)
    print(f"\nTOTAL {len(RESULTS)} cells, FAIL {fails}: "
          f"{[n for n, ok in RESULTS if not ok]}")
    return fails


if __name__ == "__main__":
    sys.exit(main())

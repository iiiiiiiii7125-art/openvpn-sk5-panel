#!/usr/bin/env python3
"""R24 probe (r24_enable_placeholder.py) -- enable-path placeholder
tun1 (R24-P2-1), FIXED by BT.

Original mechanism (R24 §2.5): enable() waited 10 x 0.5 s for tun1
and, if the device had not appeared, called ensure_tun1, which
created a dead placeholder (UP, NO-CARRIER, state DOWN) and
installed `default via 10.9.0.1 dev tun1` -- which the kernel marks
linkdown. That route carries NOTHING, but _policy_active() matched
any line starting with `default` containing `dev` and `tun1` (no
linkdown check), so it returned True: get_status() reported
policy_routing_active=true, check_health() never attempted the
repair, and sing-box could never start again (second TUNSETIFF:
"Device or resource busy" / "File exists").

The BT fix (two layers, R24 §2.5):
  1. Kill the writer -- neither policy-routing.sh verb creates
     tun1 any more (ensure_tun1 deleted; both verbs run repair
     semantics: blackhole + rule, tun1 route only when live), and
     sk5_manager.enable() waits for a LIVE tun1 (LOWER_UP) and
     fails LOUDLY instead of building a placeholder.
  2. Depth -- _policy_active() and the script self-check grep
     reject linkdown route lines.
  Plus the device-residue half of the fix: a dead placeholder left
  by a pre-fix enable is deleted by sk5_manager before starting
  the daemon / before repairing (_remove_dead_tun1_placeholder:
  triple dead check + no sing-box holder), so a wedged chain
  recovers without manual `ip link del tun1`.

This probe now asserts the FIXED behavior (same legitimate
correction family as BH-03(c) / BN-Q5 / BR-W2: the old cells
pinned the defective behavior itself). The BT probe
(tests/bt_enable_no_placeholder.py) covers the Python enable()
loud-failure and one-click K3 recovery cells; this probe covers
the script verb + predicate + health-check path end to end.

Run: python3 tests/r24_enable_placeholder.py
Exit code = number of FAILs. Requires: unshare, ip, python3, root.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
FAILURES = []


def cell(name, cond, note=""):
    print(("PASS " if cond else "FAIL ") + name + ((" -- " + note) if note else ""))
    if not cond:
        FAILURES.append(name)


def sh(*args, check=False, **kw):
    return subprocess.run(list(args), capture_output=True, text=True,
                          timeout=30, **kw)


def inside_ns():
    """Everything below runs inside `unshare -rmn` (private mount +
    net namespace). The host is untouched: /etc/sysctl.d and
    /run/openvpn-sk5-panel are bind-mounted over with scratch dirs,
    sysctl/iptables are stubbed on PATH, `ip` is real."""
    tmp = Path(tempfile.mkdtemp(prefix="r24probe-"))
    cfgdir = tmp / "cfg"
    cfgdir.mkdir()
    sysctld = tmp / "sysctld"
    sysctld.mkdir()
    rund = tmp / "run"
    rund.mkdir()
    stubbin = tmp / "stubbin"
    stubbin.mkdir()
    (stubbin / "sysctl").write_text("#!/bin/sh\nexit 0\n")
    (stubbin / "iptables").write_text(
        "#!/bin/sh\nif [ \"$1\" = \"-C\" ]; then exit 1; fi\nexit 0\n")
    for p in (stubbin / "sysctl", stubbin / "iptables"):
        p.chmod(0o755)
    # Bind-mount scratch dirs over the host paths the script writes.
    for src, dst in ((sysctld, "/etc/sysctl.d"), (rund, "/run/openvpn-sk5-panel")):
        Path(dst).mkdir(parents=True, exist_ok=True)
        r = sh("mount", "--bind", str(src), dst)
        assert r.returncode == 0, f"bind {dst}: {r.stderr}"
    env = dict(os.environ)
    env["PATH"] = str(stubbin) + ":/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    env["OVPN_SK5_CONFIG_DIR"] = str(cfgdir)
    # The in-process sk5_manager import reads os.environ, not the
    # subprocess env dict -- set both.
    os.environ["PATH"] = env["PATH"]
    os.environ["OVPN_SK5_CONFIG_DIR"] = str(cfgdir)
    (cfgdir / "sk5.json").write_text(
        '{"host": "127.0.0.1", "port": 11080, "username": "u", '
        '"password": "p", "enabled": true, "fail_open": false, '
        '"udp_over_tcp": false}\n')
    script = str(TREE / "egress" / "policy-routing.sh")
    sys.path.insert(0, str(TREE / "egress"))
    import sk5_manager as sm

    sh("ip", "link", "set", "lo", "up")
    sh("ip", "addr", "add", "10.8.0.1/32", "dev", "lo")

    # W1: the REAL enable verb, no sing-box present. Fixed: rc=0,
    # blackhole + rule only, NO device created (repair semantics).
    r = sh("bash", script, "enable", env=env)
    cell("W1 enable verb exits 0 with no sing-box present", r.returncode == 0,
         (r.stderr or r.stdout or "")[-200:])
    link = sh("ip", "link", "show", "dev", "tun1")
    cell("W2 no tun1 device is created by enable (writer killed)",
         link.returncode != 0, link.stdout.strip() or "tun1 absent")
    table = sh("ip", "route", "show", "table", "100").stdout
    rule = sh("ip", "rule", "show").stdout
    cell("W3 table 100 is blackhole-only (no linkdown route)",
         "blackhole" in table and "linkdown" not in table
         and "default via" not in table, table.strip())
    cell("W3b rule from 10.8.0.0/24 lookup 100 in place",
         "from 10.8.0.0/24 lookup 100" in rule, "")
    get = sh("ip", "route", "get", "1.1.1.1", "from", "10.8.0.1")
    cell("W4 lookup from a VPN source is dropped by the blackhole (no dev tun1)",
         get.returncode != 0 and "dev tun1" not in get.stdout,
         (get.stdout + get.stderr).strip())

    cfg = sm._load_config()
    cell("P1 _policy_active() is False on a blackhole-only table",
         sm._policy_active(cfg) is False, "")
    cell("P1b _repair_holding() is True (rule + blackhole present)",
         sm._repair_holding() is True, "")

    h1 = sm.check_health()
    cell("P2 check_health action is blackholed_kill_switch",
         h1.get("action") == "blackholed_kill_switch", str(h1))
    cell("P2b check_health detail names sing-box death, not policy",
         "sing-box not running" in h1.get("detail", ""), h1.get("detail", ""))
    table_after = sh("ip", "route", "show", "table", "100").stdout
    cell("P3 no linkdown route exists after check_health (none was ever written)",
         "linkdown" not in table_after, table_after.strip())
    cell("P3b _policy_active() still False after check_health",
         sm._policy_active(sm._load_config()) is False, "")
    # P4: with no placeholder in the way, a tun1 can be created --
    # the old "Device or resource busy" wedge is gone. Leave the
    # hand-made device in place: it is a dead placeholder now, and
    # P4c/P6 prove the predicate rejects it and the repair clears it.
    mk = sh("ip", "tuntap", "add", "mode", "tun", "dev", "tun1")
    cell("P4 tun1 creation succeeds (no busy wedge)",
         mk.returncode == 0, mk.stderr.strip())
    # Bring it up exactly as the old ensure_tun1 did (addr + up):
    # a fresh tuntap device only shows NO-CARRIER once UP is set.
    sh("ip", "addr", "add", "10.9.0.1/30", "dev", "tun1")
    sh("ip", "link", "set", "dev", "tun1", "up")
    link2 = sh("ip", "link", "show", "dev", "tun1").stdout
    cell("P4b hand-made tun1 is a dead placeholder (NO-CARRIER, no LOWER_UP)",
         "NO-CARRIER" in link2 and "LOWER_UP" not in link2,
         link2.strip().splitlines()[-1] if link2 else "no tun1")
    sh("ip", "route", "replace", "default", "via", "10.9.0.1",
       "dev", "tun1", "table", "100")
    table_linkdown = sh("ip", "route", "show", "table", "100").stdout
    cell("P4c hand-installed route via the dead device is linkdown",
         "linkdown" in table_linkdown, table_linkdown.strip())
    cell("P4d _policy_active() rejects the linkdown route (layer 2)",
         sm._policy_active(sm._load_config()) is False, "")
    st = sm.get_status()
    cell("P5 get_status reports policy_routing_active=false (panel honest)",
         st.get("policy_routing_active") is False, str(st.get("policy_routing_active")))
    cell("P5b get_status still honestly reports singbox_running=false",
         st.get("singbox_running") is False, "")

    # P6: a repair now RUNS (predicate no longer fooled) and clears
    # the residue: the dead device is deleted by the pre-clean and
    # the linkdown route is dropped by the script.
    h2 = sm.check_health()
    table_p6 = sh("ip", "route", "show", "table", "100").stdout
    link_p6 = sh("ip", "link", "show", "dev", "tun1")
    cell("P6 check_health still blackholed_kill_switch, repair ran",
         h2.get("action") == "blackholed_kill_switch", str(h2))
    cell("P6b dead placeholder device deleted by the repair pre-clean",
         link_p6.returncode != 0, link_p6.stdout.strip() or "tun1 absent")
    cell("P6c linkdown route gone after check_health",
         "linkdown" not in table_p6 and "blackhole" in table_p6,
         table_p6.strip())

    # C1 control: the repair verb on the same state does the right
    # thing -- blackhole + rule kept, no linkdown route.
    r = sh("bash", script, "repair", env=env)
    table_c = sh("ip", "route", "show", "table", "100").stdout
    cell("C1 repair verb keeps blackhole-only table, no linkdown route",
         r.returncode == 0 and "linkdown" not in table_c
         and "blackhole" in table_c, table_c.strip())
    cell("C1b _policy_active() stays False after repair",
         sm._policy_active(sm._load_config()) is False, "")
    # C2 control: with a LIVE tun1 (held fd = sing-box semantics),
    # the same route is genuinely effective and _policy_active True
    # is correct.
    sh("ip", "link", "del", "tun1")
    try:
        import fcntl
        import struct
        TUNSETIFF = 0x400454CA
        IFF_TUN, IFF_NO_PI = 0x0001, 0x1000
        fd = os.open("/dev/net/tun", os.O_RDWR)
        fcntl.ioctl(fd, TUNSETIFF, struct.pack("16sH", b"tun1", IFF_TUN | IFF_NO_PI))
        sh("ip", "link", "set", "tun1", "up")
        sh("ip", "addr", "add", "10.9.0.1/30", "dev", "tun1")
        live = sh("ip", "link", "show", "dev", "tun1").stdout
        r = sh("bash", script, "enable", env=env)
        table_live = sh("ip", "route", "show", "table", "100").stdout
        cell("C2 live tun1 shows LOWER_UP and enable keeps it",
             "LOWER_UP" in live and r.returncode == 0, live.strip().splitlines()[-1])
        cell("C2b route via live tun1 is NOT linkdown",
             "linkdown" not in table_live, table_live.strip())
        cell("C2c _policy_active() True on the live route (correct)",
             sm._policy_active(sm._load_config()) is True, "")
        os.close(fd)
    except OSError as e:
        print("SKIP C2 live-device control: /dev/net/tun unavailable (%s)" % e)

    print(f"\n{len(FAILURES)} FAIL(s): {FAILURES}" if FAILURES else "\nALL PASS")
    return 1 if FAILURES else 0


def main():
    if os.environ.get("R24_IN_NS") != "1":
        env = dict(os.environ, R24_IN_NS="1")
        r = subprocess.run(["unshare", "-rmn", sys.executable,
                            os.path.abspath(__file__)], env=env)
        return r.returncode
    return inside_ns()


if __name__ == "__main__":
    sys.exit(main())

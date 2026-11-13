#!/usr/bin/env python3
"""BT fix probe (bt_enable_no_placeholder.py) -- R24-P2-1 (P2):
enable-path placeholder writes a linkdown route that fools
_policy_active(), wedging the chain until a human deletes tun1.

The fix (two layers, R24 §2.5):
  1. Kill the writer -- sk5_manager.enable() waits for a LIVE
     tun1 (LOWER_UP) and fails LOUDLY instead of building a
     placeholder; neither policy-routing.sh verb creates tun1 any
     more (ensure_tun1 deleted; both verbs run repair semantics).
  2. Depth -- _policy_active() and the script self-check grep
     reject linkdown route lines.
  Plus the device-residue half: a dead placeholder left by a
  pre-fix enable is deleted by sk5_manager before starting the
  daemon / before repairing (_remove_dead_tun1_placeholder:
  triple dead check -- exists + NO-CARRIER + no LOWER_UP -- AND
  no sing-box holder), so a wedged chain recovers without manual
  `ip link del tun1`. BO rejected device deletion for the
  "delete a live device" race; the triple check + holder check
  answer it -- a held device always shows LOWER_UP, and the
  delete never runs while sing-box is up (B5 proves the guard).

What each cell proves (real script + real kernel + real
sk5_manager, private netns; sing-box itself is a stub that either
holds tun1 like the real daemon (TUNSETIFF + up) or stays alive
without ever creating it -- the two shapes a slow/broken daemon
takes):
  B0: script enable verb with no sing-box -> blackhole-only
      table, no device, _policy_active() False, check_health()
      runs repair -> blackholed_kill_switch.
  B1: Python enable() with a daemon that never creates tun1 ->
      LOUD RuntimeError naming tun1, NO placeholder, NO policy
      change, enabled stays False on disk.
  B2: one-click recovery from a pre-fix K3 wedge (dead
      placeholder + linkdown route + rule + blackhole) -> enable()
      deletes the placeholder, starts the daemon, lands a live
      route, enabled True.
  B3: repair-path recovery from the same K3 wedge ->
      check_health() deletes the placeholder, drops the linkdown
      route, stays blackholed_kill_switch; a fresh tun1 can then
      be created (sing-box can restart).
  B4: predicate controls -- a linkdown route is rejected, a live
      route is accepted.
  B5: guard -- a LIVE tun1 held by a running daemon is never
      deleted (_remove_dead_tun1_placeholder() returns False).

Run: python3 tests/bt_enable_no_placeholder.py
Exit code = number of FAILs. Requires: unshare, ip, python3, root.
"""
import fcntl
import json
import os
import signal
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
FAILURES = []

STUB_SINGBOX = r"""#!/usr/bin/env python3
# Stub sing-box for the BT probe: `check` always passes; `run`
# behaves per the mode file next to this script: "dead" sleeps
# forever without creating tun1 (slow/broken daemon); "live"
# creates tun1 like the real daemon (TUNSETIFF, hold the fd,
# link up, address) and then sleeps holding it.
import fcntl
import os
import struct
import subprocess
import sys
import time

if sys.argv[1:2] == ["check"]:
    sys.exit(0)
mode = open(os.path.join(os.path.dirname(__file__), "mode")).read().strip()
open(os.path.join(os.path.dirname(__file__), "started"), "w").write("run\n")
if mode == "live":
    fd = os.open("/dev/net/tun", os.O_RDWR)
    fcntl.ioctl(fd, 0x400454CA, struct.pack("16sH", b"tun1", 0x0001 | 0x1000))
    subprocess.run(["ip", "link", "set", "tun1", "up"], check=True)
    subprocess.run(["ip", "addr", "add", "10.9.0.1/30", "dev", "tun1"],
                   check=False)
    time.sleep(300)
elif mode == "dead":
    time.sleep(300)
sys.exit(0)
"""


def cell(name, cond, note=""):
    print(("PASS " if cond else "FAIL ") + name + ((" -- " + note) if note else ""))
    if not cond:
        FAILURES.append(name)


def sh(*args, **kw):
    return subprocess.run(list(args), capture_output=True, text=True,
                          timeout=30, **kw)


def build_k3(env):
    """Hand-build the pre-fix K3 wedge: dead placeholder tun1 +
    linkdown route + rule + blackhole (what a pre-BT enable left
    behind when sing-box was slow or failing)."""
    sh("ip", "tuntap", "add", "mode", "tun", "dev", "tun1")
    sh("ip", "addr", "add", "10.9.0.1/30", "dev", "tun1")
    sh("ip", "link", "set", "dev", "tun1", "up")
    sh("bash", str(TREE / "egress" / "policy-routing.sh"), "enable", env=env)
    # The enable above (no live tun1) installs blackhole + rule
    # only; add the stale linkdown route by hand, as the old
    # placeholder path did.
    sh("ip", "route", "replace", "default", "via", "10.9.0.1",
       "dev", "tun1", "table", "100")


def table(env):
    return sh("ip", "route", "show", "table", "100").stdout


def kill_stub(cfgdir):
    pidfile = cfgdir / "sing-box.pid"
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):
            time.sleep(0.25)
            try:
                os.kill(pid, 0)
            except OSError:
                break
        else:
            os.kill(pid, signal.SIGKILL)
    except (ValueError, OSError):
        pass
    try:
        pidfile.unlink()
    except OSError:
        pass


def inside_ns():
    tmp = Path(tempfile.mkdtemp(prefix="btprobe-"))
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
    (stubbin / "systemctl").write_text(
        "#!/bin/sh\n# No unit installed in this probe: is-enabled/is-active fail.\n"
        "exit 1\n")
    for p in (stubbin / "sysctl", stubbin / "iptables", stubbin / "systemctl"):
        p.chmod(0o755)
    stub_sb = stubbin / "sing-box"
    stub_sb.write_text(STUB_SINGBOX)
    stub_sb.chmod(0o755)
    for src, dst in ((sysctld, "/etc/sysctl.d"), (rund, "/run/openvpn-sk5-panel")):
        Path(dst).mkdir(parents=True, exist_ok=True)
        r = sh("mount", "--bind", str(src), dst)
        assert r.returncode == 0, f"bind {dst}: {r.stderr}"
    env = dict(os.environ)
    env["PATH"] = str(stubbin) + ":/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    env["OVPN_SK5_CONFIG_DIR"] = str(cfgdir)
    os.environ["PATH"] = env["PATH"]
    os.environ["OVPN_SK5_CONFIG_DIR"] = str(cfgdir)
    (cfgdir / "sk5.json").write_text(
        '{"host": "127.0.0.1", "port": 11080, "username": "u", '
        '"password": "p", "enabled": false, "fail_open": false, '
        '"udp_over_tcp": false}\n')
    script = str(TREE / "egress" / "policy-routing.sh")
    sys.path.insert(0, str(TREE / "egress"))
    import sk5_manager as sm
    sm.SINGBOX_BIN = str(stub_sb)

    sh("ip", "link", "set", "lo", "up")
    sh("ip", "addr", "add", "10.8.0.1/32", "dev", "lo")
    (stubbin / "mode").write_text("dead")

    # B0: script enable verb, no sing-box at all.
    r = sh("bash", script, "enable", env=env)
    cell("B0 script enable with no sing-box exits 0, creates no device",
         r.returncode == 0
         and sh("ip", "link", "show", "dev", "tun1").returncode != 0,
         (r.stderr or r.stdout or "")[-160:])
    t0 = table(env)
    cell("B0b table 100 is blackhole-only after script enable",
         "blackhole" in t0 and "default via" not in t0, t0.strip())
    (cfgdir / "sk5.json").write_text(
        '{"host": "127.0.0.1", "port": 11080, "username": "u", '
        '"password": "p", "enabled": true, "fail_open": false, '
        '"udp_over_tcp": false}\n')
    cell("B0c _policy_active() False on the blackhole-only table",
         sm._policy_active(sm._load_config()) is False, "")
    h0 = sm.check_health()
    cell("B0d check_health runs repair -> blackholed_kill_switch",
         h0.get("action") == "blackholed_kill_switch", str(h0))
    sh("bash", script, "disable", env=env)

    # B1: Python enable() with a daemon that never creates tun1.
    (cfgdir / "sk5.json").write_text(
        '{"host": "127.0.0.1", "port": 11080, "username": "u", '
        '"password": "p", "enabled": false, "fail_open": false, '
        '"udp_over_tcp": false}\n')
    try:
        sm.enable()
        raised = None
    except RuntimeError as exc:
        raised = str(exc)
    cell("B1 enable() with no live tun1 raises loudly (names tun1)",
         raised is not None and "tun1" in raised, raised or "no raise")
    cell("B1b daemon was started (stub marker) but no device exists",
         (stubbin / "started").exists()
         and sh("ip", "link", "show", "dev", "tun1").returncode != 0, "")
    t1 = table(env)
    cell("B1c no policy state changed by the failed enable",
         "default via" not in t1 and "blackhole" not in t1
         and "lookup 100" not in sh("ip", "rule", "show").stdout,
         t1.strip() or "table empty")
    saved = json.loads((cfgdir / "sk5.json").read_text(encoding="utf-8"))
    cell("B1d enabled stays False on disk after the failed enable",
         saved.get("enabled") is False, str(saved.get("enabled")))
    kill_stub(cfgdir)
    (stubbin / "started").unlink(missing_ok=True)

    # B2: one-click recovery from a pre-fix K3 wedge.
    build_k3(env)
    t2 = table(env)
    cell("B2a K3 wedge built: dead device + linkdown route + blackhole",
         "linkdown" in t2 and "blackhole" in t2, t2.strip())
    cell("B2b _policy_active() False on the wedge (predicate rejects linkdown)",
         sm._policy_active(sm._load_config()) is False, "")
    (stubbin / "mode").write_text("live")
    try:
        st = sm.enable()
        raised2 = None
    except RuntimeError as exc:
        st, raised2 = None, str(exc)
    cell("B2c enable() recovers the wedge (no raise)",
         raised2 is None, raised2 or "")
    live = sh("ip", "link", "show", "dev", "tun1").stdout
    t2b = table(env)
    cell("B2d tun1 is live (LOWER_UP) after recovery",
         "LOWER_UP" in live, live.strip().splitlines()[-1] if live else "no tun1")
    cell("B2e route via live tun1 is NOT linkdown after recovery",
         "linkdown" not in t2b and "default via 10.9.0.1 dev tun1" in t2b,
         t2b.strip())
    cell("B2f _policy_active() True and status enabled after recovery",
         st is not None and st.get("policy_routing_active") is True
         and st.get("enabled") is True,
         str(st.get("policy_routing_active")) if st else "")
    kill_stub(cfgdir)
    (stubbin / "started").unlink(missing_ok=True)
    sh("bash", script, "disable", env=env)

    # B3: repair-path recovery from the same K3 wedge.
    (cfgdir / "sk5.json").write_text(
        '{"host": "127.0.0.1", "port": 11080, "username": "u", '
        '"password": "p", "enabled": true, "fail_open": false, '
        '"udp_over_tcp": false}\n')
    build_k3(env)
    cell("B3a K3 wedge rebuilt for the repair path",
         "linkdown" in table(env), table(env).strip())
    h3 = sm.check_health()
    cell("B3b check_health is blackholed_kill_switch (repair ran)",
         h3.get("action") == "blackholed_kill_switch", str(h3))
    cell("B3c dead placeholder device deleted by the repair",
         sh("ip", "link", "show", "dev", "tun1").returncode != 0, "")
    t3 = table(env)
    cell("B3d linkdown route gone, blackhole-only table after repair",
         "linkdown" not in t3 and "blackhole" in t3, t3.strip())
    mk = sh("ip", "tuntap", "add", "mode", "tun", "dev", "tun1")
    cell("B3e fresh tun1 creation succeeds after repair (daemon can restart)",
         mk.returncode == 0, mk.stderr.strip())
    sh("ip", "link", "del", "tun1")
    sh("bash", script, "disable", env=env)

    # B4: predicate controls, no daemon involved.
    sh("ip", "tuntap", "add", "mode", "tun", "dev", "tun1")
    sh("ip", "addr", "add", "10.9.0.1/30", "dev", "tun1")
    sh("ip", "link", "set", "dev", "tun1", "up")
    sh("bash", script, "enable", env=env)
    sh("ip", "route", "replace", "default", "via", "10.9.0.1",
       "dev", "tun1", "table", "100")
    cell("B4a linkdown route line is rejected by _policy_active()",
         "linkdown" in table(env)
         and sm._policy_active(sm._load_config()) is False,
         table(env).strip())
    sh("ip", "link", "del", "tun1")
    fd = None
    try:
        TUNSETIFF = 0x400454CA
        IFF_TUN, IFF_NO_PI = 0x0001, 0x1000
        fd = os.open("/dev/net/tun", os.O_RDWR)
        fcntl.ioctl(fd, TUNSETIFF, struct.pack("16sH", b"tun1", IFF_TUN | IFF_NO_PI))
        sh("ip", "link", "set", "tun1", "up")
        sh("ip", "addr", "add", "10.9.0.1/30", "dev", "tun1")
        r = sh("bash", script, "enable", env=env)
        t4 = table(env)
        cell("B4b live route is accepted by _policy_active()",
             r.returncode == 0 and "linkdown" not in t4
             and sm._policy_active(sm._load_config()) is True, t4.strip())
        # B5: guard -- live device + running daemon is never deleted.
        (cfgdir / "sing-box.pid").write_text(str(os.getpid()) + "\n")
        cell("B5a _tun1_dead_placeholder() is False on a live device",
             sm._tun1_dead_placeholder() is False, "")
        cell("B5b _remove_dead_tun1_placeholder() refuses a held live device",
             sm._remove_dead_tun1_placeholder() is False
             and sh("ip", "link", "show", "dev", "tun1").returncode == 0, "")
        (cfgdir / "sing-box.pid").unlink(missing_ok=True)
    except OSError as e:
        print("SKIP B4b/B5 live-device controls: /dev/net/tun unavailable (%s)" % e)
    finally:
        if fd is not None:
            os.close(fd)

    print(f"\n{len(FAILURES)} FAIL(s): {FAILURES}" if FAILURES else "\nALL PASS")
    return 1 if FAILURES else 0


def main():
    if os.environ.get("BT_IN_NS") != "1":
        env = dict(os.environ, BT_IN_NS="1")
        r = subprocess.run(["unshare", "-rmn", sys.executable,
                            os.path.abspath(__file__)], env=env)
        return r.returncode
    return inside_ns()


if __name__ == "__main__":
    sys.exit(main())

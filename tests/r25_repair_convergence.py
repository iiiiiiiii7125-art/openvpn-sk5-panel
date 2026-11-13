#!/usr/bin/env python3
"""R25 convergence probe (r25_repair_convergence.py) -- AUDIT-R25
method: repair-path convergence. Every repair path x degraded
state: does it converge to a live chain (K1), fail LOUD and
honest, or wedge silently? A silent wedge is a finding.

Paths: P1 check_health tick, P2 boot restore, P3 enable(),
P4 set_sk5 repair branch, P5 disable(), P6 operator re-enable.
States (R24 K0-K10 + new K11): K11 = rule + blackhole-only
table, enabled=false -- the leftover of BT's enable() when tun1
dies between the live-wait and the policy apply: _apply_policy()
exits 0 (blackhole-only is the script's DESIGNED outcome with no
live tun1) but Python's post-apply _policy_active() check fails
and raises WITHOUT rollback (the script's own rollback only
runs when the SCRIPT fails). K11 is fail-closed and loud, but
no automatic path cleans it: check_health short-circuits on
enabled=false (chain_disabled) and never touches the table.

Cells (real script + real kernel + real sk5_manager, private
netns; stub sing-box: dead / live / slow-7s; stateful stub
systemctl modelling StartLimitBurst + reset-failed):
  F0a-e flag-shape empirics: absent / down / up-no-holder /
      up-with-holder / held-then-down (O-R24-1) -> ip link flags
      + _tun1_dead_placeholder() verdict. The triple check must
      be True ONLY for up-no-holder.
  K11a get_status on K11 is honest (policy false, egress None).
  K11b check_health on K11 is chain_disabled AND the rule is
      still there after the tick (no auto-cleanup).
  K11c disable() from K11 converges to K0.
  K11d enable() from K11 (live stub) converges to K1.
  S1  enable() with a slow stub (tun1 after 7s) raises LOUD at
      ~5s, no policy state changed, enabled stays False.
  S2a already-enabled slow restart: check_health tick 1 ->
      blackholed_kill_switch (repair ran); tun1 appears; tick 2
      -> policy_repaired / K1 (P1 convergence).
  S2b operator retry after S1 (tun1 now live) -> enable() OK.
  P4a daemon alive + policy missing -> set_sk5() repairs in
      place (repaired:true, no daemon restart).
  P4b daemon dead + enabled + policy missing -> set_sk5()
      takes the enable() leg (restart + K1, "sing-box restarted").
  D4  start-limit wedge: P1 tick holds blackholed_kill_switch
      (never restarts the daemon); operator enable() does
      reset-failed + restart and converges to K1.
  R9  bare _apply_policy() (default verb) is repair semantics:
      no device created, blackhole + rule only.

Run: python3 tests/r25_repair_convergence.py
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
# Stub sing-box: `check` always passes; `run` per mode file:
# "dead" sleeps without creating tun1; "live" creates tun1
# (TUNSETIFF + up + addr) and holds it; "slow" sleeps 7 s
# first, then creates tun1 live (slow-start daemon).
import fcntl
import os
import struct
import subprocess
import sys
import time

if sys.argv[1:2] == ["check"]:
    sys.exit(0)
here = os.path.dirname(os.path.abspath(__file__))
mode = open(os.path.join(here, "mode")).read().strip()
open(os.path.join(here, "started"), "w").write("run\n")
if mode in ("live", "slow"):
    if mode == "slow":
        # Cold start only: sleep 7 s the FIRST time this stub is
        # started (marker file "cold" consumed on use), then behave
        # as live. A real daemon is slow once (cold page cache) and
        # fast on warm restart; a fixed 7 s sleep on EVERY start
        # would model a daemon that can never start in 5 s -- that
        # persistent-slow case is a separate observation (O-R25-2),
        # not the cold-start case this cell proves.
        cold = os.path.join(here, "cold")
        if os.path.exists(cold):
            os.unlink(cold)
            time.sleep(7)
    fd = os.open("/dev/net/tun", os.O_RDWR)
    fcntl.ioctl(fd, 0x400454CA, struct.pack("16sH", b"tun1", 0x0001 | 0x1000))
    subprocess.run(["ip", "link", "set", "tun1", "up"], check=True)
    subprocess.run(["ip", "addr", "add", "10.9.0.1/30", "dev", "tun1"],
                   check=False)
    time.sleep(300)
elif mode == "strict-live":
    # Like "live", but fails LOUD on a duplicate address -- the
    # real sing-box shape (live-14: FATAL "configure tun interface:
    # file exists" = EEXIST on the addr add, because the placeholder
    # already carries 10.9.0.1/30). The plain "live" stub ignores
    # the addr failure (check=False) and attaches to the
    # placeholder, so it CANNOT discriminate the enable-path
    # pre-clean; strict-live can (see E1).
    fd = os.open("/dev/net/tun", os.O_RDWR)
    fcntl.ioctl(fd, 0x400454CA, struct.pack("16sH", b"tun1", 0x0001 | 0x1000))
    subprocess.run(["ip", "link", "set", "tun1", "up"], check=True)
    subprocess.run(["ip", "addr", "add", "10.9.0.1/30", "dev", "tun1"],
                   check=True)
    time.sleep(300)
elif mode == "dead":
    time.sleep(300)
sys.exit(0)
"""

STUB_SYSTEMCTL = r"""#!/usr/bin/env python3
# Stateful stub systemctl: models a systemd unit with
# StartLimitBurst=5 (starts counter) + reset-failed.
# State dir from $STUB_STATE; stub sing-box path from $STUB_SB;
# its mode file lives next to the stub binary.
#   is-active --quiet U -> 0 iff state/active exists
#   is-enabled --quiet U -> 0 (unit installed)
#   reset-failed U -> clears failed + starts counter
#   restart U -> if state/failed exists: fail (start-limit-hit);
#     else starts+=1; if starts>5: failed, clear active, fail;
#     else spawn stub sing-box detached, write its pid to
#     $STUB_PIDFILE, touch active, exit 0
#   stop U -> kill stub pid, clear active
import os
import subprocess
import sys
import time

state = os.environ["STUB_STATE"]
sb = os.environ["STUB_SB"]
pidfile = os.environ["STUB_PIDFILE"]
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
os.makedirs(state, exist_ok=True)


def p(name):
    return os.path.join(state, name)


if cmd == "is-active":
    sys.exit(0 if os.path.exists(p("active")) else 1)
if cmd == "is-enabled":
    sys.exit(0)
if cmd == "reset-failed":
    for f in ("failed", "starts"):
        try:
            os.unlink(p(f))
        except OSError:
            pass
    sys.exit(0)
if cmd == "stop":
    try:
        pid = int(open(pidfile).read().strip())
        os.kill(pid, 15)
        for _ in range(20):
            time.sleep(0.25)
            try:
                os.kill(pid, 0)
            except OSError:
                break
        else:
            os.kill(pid, 9)
    except (ValueError, OSError):
        pass
    try:
        os.unlink(p("active"))
    except OSError:
        pass
    sys.exit(0)
if cmd == "restart":
    if os.path.exists(p("failed")):
        print("Failed to restart: start-limit-hit", file=sys.stderr)
        sys.exit(1)
    n = 0
    try:
        n = int(open(p("starts")).read().strip())
    except (ValueError, OSError):
        n = 0
    n += 1
    open(p("starts"), "w").write(str(n))
    if n > 5:
        open(p("failed"), "w").write("1")
        try:
            os.unlink(p("active"))
        except OSError:
            pass
        print("Failed to restart: start-limit-hit", file=sys.stderr)
        sys.exit(1)
    # Real restart stops the old process first (systemd semantics):
    # otherwise the old stub still holds tun1 and the new stub's
    # TUNSETIFF fails EBUSY -- that would be a stub artifact, not
    # product behaviour.
    try:
        pid = int(open(pidfile).read().strip())
        os.kill(pid, 15)
        for _ in range(20):
            time.sleep(0.25)
            try:
                os.kill(pid, 0)
            except OSError:
                break
        else:
            os.kill(pid, 9)
    except (ValueError, OSError):
        pass
    proc = subprocess.Popen([sb, "run"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True, close_fds=True)
    open(pidfile, "w").write(str(proc.pid) + "\n")
    open(p("active"), "w").write("1")
    sys.exit(0)
sys.exit(0)
"""


def cell(name, cond, note=""):
    print(("PASS " if cond else "FAIL ") + name + ((" -- " + note) if note else ""))
    if not cond:
        FAILURES.append(name)


def sh(*args, **kw):
    return subprocess.run(list(args), capture_output=True, text=True,
                          timeout=30, **kw)


def table(env):
    return sh("ip", "route", "show", "table", "100").stdout


def rules():
    return sh("ip", "rule", "show").stdout


def link_flags():
    r = sh("ip", "link", "show", "dev", "tun1")
    if r.returncode != 0:
        return None
    return r.stdout.strip()


def write_sk5(cfgdir, enabled):
    (cfgdir / "sk5.json").write_text(
        '{"host": "127.0.0.1", "port": 11080, "username": "u", '
        '"password": "p", "enabled": %s, "fail_open": false, '
        '"udp_over_tcp": false}\n' % ("true" if enabled else "false"))


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
    # The stub systemctl's is-active answer is a state file; a raw
    # kill must clear it too, or _singbox_running() would still
    # report the dead daemon as running (stale "active").
    try:
        (STATEDIR / "active").unlink()
    except (OSError, NameError):
        pass


def inside_ns():
    tmp = Path(tempfile.mkdtemp(prefix="r25probe-"))
    cfgdir = tmp / "cfg"
    cfgdir.mkdir()
    sysctld = tmp / "sysctld"
    sysctld.mkdir()
    rund = tmp / "run"
    rund.mkdir()
    stubbin = tmp / "stubbin"
    stubbin.mkdir()
    statedir = tmp / "sysstate"
    statedir.mkdir()
    global STATEDIR
    STATEDIR = statedir
    (stubbin / "sysctl").write_text("#!/bin/sh\nexit 0\n")
    (stubbin / "iptables").write_text(
        "#!/bin/sh\nif [ \"$1\" = \"-C\" ]; then exit 1; fi\nexit 0\n")
    (stubbin / "systemctl").write_text(STUB_SYSTEMCTL)
    (stubbin / "sing-box").write_text(STUB_SINGBOX)
    for p in (stubbin / "sysctl", stubbin / "iptables",
              stubbin / "systemctl", stubbin / "sing-box"):
        p.chmod(0o755)
    for src, dst in ((sysctld, "/etc/sysctl.d"), (rund, "/run/openvpn-sk5-panel")):
        Path(dst).mkdir(parents=True, exist_ok=True)
        r = sh("mount", "--bind", str(src), dst)
        assert r.returncode == 0, f"bind {dst}: {r.stderr}"
    env = dict(os.environ)
    env["PATH"] = str(stubbin) + ":/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    env["OVPN_SK5_CONFIG_DIR"] = str(cfgdir)
    env["STUB_STATE"] = str(statedir)
    env["STUB_SB"] = str(stubbin / "sing-box")
    env["STUB_PIDFILE"] = str(cfgdir / "sing-box.pid")
    os.environ.update(env)
    script = str(TREE / "egress" / "policy-routing.sh")
    sys.path.insert(0, str(TREE / "egress"))
    import sk5_manager as sm
    sm.SINGBOX_BIN = str(stubbin / "sing-box")

    sh("ip", "link", "set", "lo", "up")
    sh("ip", "addr", "add", "10.8.0.1/32", "dev", "lo")
    write_sk5(cfgdir, False)
    (stubbin / "mode").write_text("dead")

    # ---- F0: flag-shape empirics (no daemon involved) ----
    cell("F0a absent device: link rc!=0, triple check False",
         link_flags() is None and sm._tun1_dead_placeholder() is False, "")
    sh("ip", "tuntap", "add", "mode", "tun", "dev", "tun1")
    f_down = link_flags()
    cell("F0b created-but-down device: no NO-CARRIER, triple False",
         f_down is not None and "NO-CARRIER" not in f_down
         and "LOWER_UP" not in f_down
         and sm._tun1_dead_placeholder() is False, f_down or "absent")
    sh("ip", "link", "set", "dev", "tun1", "up")
    f_up = link_flags()
    cell("F0c up-no-holder (placeholder shape): NO-CARRIER, triple True",
         f_up is not None and "NO-CARRIER" in f_up
         and "LOWER_UP" not in f_up
         and sm._tun1_dead_placeholder() is True, f_up or "absent")
    sh("ip", "link", "del", "tun1")
    fd = os.open("/dev/net/tun", os.O_RDWR)
    fcntl.ioctl(fd, 0x400454CA, struct.pack("16sH", b"tun1", 0x0001 | 0x1000))
    sh("ip", "link", "set", "tun1", "up")
    sh("ip", "addr", "add", "10.9.0.1/30", "dev", "tun1")
    f_live = link_flags()
    cell("F0d fd-held + up (live shape): LOWER_UP, triple False",
         f_live is not None and "LOWER_UP" in f_live
         and sm._tun1_dead_placeholder() is False, f_live or "absent")
    sh("ip", "link", "set", "tun1", "down")
    f_holddown = link_flags()
    cell("F0e held-then-down (O-R24-1 shape): triple False (no delete)",
         f_holddown is not None
         and sm._tun1_dead_placeholder() is False, f_holddown or "absent")
    cell("F0f pre-clean refuses the held-down device",
         sm._remove_dead_tun1_placeholder() is False
         and sh("ip", "link", "show", "dev", "tun1").returncode == 0, "")
    os.close(fd)
    assert sh("ip", "link", "show", "dev", "tun1").returncode != 0
    sh("bash", script, "disable", env=env)

    # ---- E1: strict stub discriminates the enable-path pre-clean ----
    # Build the K3 wedge, then enable() with a strict-live daemon
    # (fails loud on a duplicate address, like real sing-box).
    # With the pre-clean in place the placeholder is deleted first
    # and the daemon creates tun1 fresh -> K1. Without it (m2) the
    # daemon attaches to the placeholder, its addr add hits EEXIST
    # and it dies -> enable() raises.
    write_sk5(cfgdir, False)
    sh("ip", "tuntap", "add", "mode", "tun", "dev", "tun1")
    sh("ip", "addr", "add", "10.9.0.1/30", "dev", "tun1")
    sh("ip", "link", "set", "dev", "tun1", "up")
    sh("bash", script, "enable", env=env)
    sh("ip", "route", "replace", "default", "via", "10.9.0.1",
       "dev", "tun1", "table", "100")
    cell("E1a K3 wedge built for the strict daemon",
         "linkdown" in table(env), table(env).strip())
    (stubbin / "mode").write_text("strict-live")
    try:
        st_e1 = sm.enable()
        raised_e1 = None
    except RuntimeError as exc:
        st_e1, raised_e1 = None, str(exc)
    cell("E1b enable() with strict daemon recovers the wedge (K1)",
         raised_e1 is None and st_e1 is not None
         and st_e1.get("policy_routing_active") is True, raised_e1 or "")
    kill_stub(cfgdir)
    sh("bash", script, "disable", env=env)
    (stubbin / "started").unlink(missing_ok=True)

    # ---- K11: rule + blackhole-only, enabled=false ----
    # Build it exactly as BT's enable() leaves it: script enable
    # with no live tun1 (exit 0, blackhole + rule), disk enabled=false.
    write_sk5(cfgdir, False)
    r = sh("bash", script, "enable", env=env)
    t = table(env)
    cell("K11a K11 built: rule + blackhole-only, enabled=false",
         r.returncode == 0 and "blackhole" in t and "default via" not in t
         and "lookup 100" in rules(), t.strip())
    st = sm.get_status()
    cell("K11b get_status on K11 is honest (policy false, egress None)",
         st.get("policy_routing_active") is False
         and st.get("egress_ip") is None and st.get("enabled") is False,
         str({k: st.get(k) for k in ("policy_routing_active", "egress_ip", "enabled")}))
    h = sm.check_health()
    cell("K11c check_health on K11 is chain_disabled",
         h.get("action") == "chain_disabled", str(h))
    cell("K11d rule STILL present after the health tick (no auto-cleanup)",
         "lookup 100" in rules() and "blackhole" in table(env), "")
    d = sm.disable()
    cell("K11e disable() from K11 converges to K0 (rule gone, table flushed)",
         "lookup 100" not in rules() and table(env).strip() == "", "")

    # K11d: rebuild K11, enable() with a live stub converges to K1.
    write_sk5(cfgdir, False)
    sh("bash", script, "enable", env=env)
    (stubbin / "mode").write_text("live")
    try:
        st2 = sm.enable()
        raised = None
    except RuntimeError as exc:
        st2, raised = None, str(exc)
    cell("K11f enable() from K11 converges to K1 (no raise)",
         raised is None, raised or "")
    cell("K11g K1 after recovery: live route, policy true, enabled true",
         st2 is not None and st2.get("policy_routing_active") is True
         and st2.get("enabled") is True
         and "LOWER_UP" in (link_flags() or ""), str(st2)[:200] if st2 else "")
    kill_stub(cfgdir)
    sh("bash", script, "disable", env=env)
    (stubbin / "started").unlink(missing_ok=True)

    # ---- S1/S2: slow start ----
    write_sk5(cfgdir, False)
    (stubbin / "mode").write_text("slow")
    (stubbin / "cold").write_text("1")  # first start is cold (7 s)
    t0 = time.monotonic()
    try:
        sm.enable()
        raised_s1 = None
    except RuntimeError as exc:
        raised_s1 = str(exc)
    dt = time.monotonic() - t0
    cell("S1a enable() with 7s-slow daemon raises LOUD at ~5s (names tun1)",
         raised_s1 is not None and "tun1" in raised_s1 and 4.5 < dt < 7.0,
         f"{raised_s1} in {dt:.1f}s" if raised_s1 else "no raise")
    cell("S1b slow-fail leaves NO policy state (no rule, no blackhole)",
         "lookup 100" not in rules() and "blackhole" not in table(env), "")
    saved = json.loads((cfgdir / "sk5.json").read_text(encoding="utf-8"))
    cell("S1c enabled stays False on disk after slow-fail",
         saved.get("enabled") is False, str(saved.get("enabled")))
    # The slow stub is still starting in the background (systemd
    # path: stub systemctl spawned it; wait for tun1 to appear).
    for _ in range(20):
        if "LOWER_UP" in (link_flags() or ""):
            break
        time.sleep(0.5)
    cell("S1d slow daemon eventually brings tun1 live",
         "LOWER_UP" in (link_flags() or ""), link_flags() or "absent")
    try:
        st_s2 = sm.enable()
        raised_s2 = None
    except RuntimeError as exc:
        st_s2, raised_s2 = None, str(exc)
    cell("S2 operator retry after slow start succeeds (K1)",
         raised_s2 is None and st_s2 is not None
         and st_s2.get("policy_routing_active") is True, raised_s2 or "")
    kill_stub(cfgdir)
    sh("bash", script, "disable", env=env)
    (stubbin / "started").unlink(missing_ok=True)

    # ---- S2a: already-enabled slow restart converges via P1 ----
    write_sk5(cfgdir, True)
    (stubbin / "mode").write_text("slow")
    # Daemon "dead" for now: no tun1, no active flag. Tick 1.
    h1 = sm.check_health()
    cell("S2a tick1 with dead daemon: blackholed_kill_switch (repair ran)",
         h1.get("action") == "blackholed_kill_switch", str(h1))
    # Now the slow daemon starts (as systemd would restart it):
    # spawn it directly via the stub systemctl restart path.
    # Cold again (first start after the wedge is a cold start).
    (stubbin / "cold").write_text("1")
    sh(str(stubbin / "systemctl"), "restart", "openvpn-sk5-singbox", env=env)
    for _ in range(20):
        if "LOWER_UP" in (link_flags() or ""):
            break
        time.sleep(0.5)
    h2 = sm.check_health()
    # NOTE: the health VERDICT cannot go healthy here -- test_sk5()
    # dials a real SK5 (127.0.0.1:11080) and the sandbox has no
    # dante, so tcp_ok=False. What P1 must prove is the K1 STATE
    # (policy re-applied, live route); the verdict stays
    # blackholed_kill_switch only because of the sandbox-missing
    # SK5, not because the repair failed.
    cell("S2b tick2 after tun1 live: P1 re-applies policy to K1",
         sm._policy_active(sm._load_config()) is True
         and "default via 10.9.0.1 dev tun1" in table(env)
         and "linkdown" not in table(env), table(env).strip())
    cell("S2c tick2 verdict is only SK5-probe-limited (sandbox, no dante)",
         h2.get("action") == "blackholed_kill_switch"
         and "tcp_ok=False" in h2.get("detail", ""), str(h2))
    kill_stub(cfgdir)
    sh("bash", script, "disable", env=env)
    (stubbin / "started").unlink(missing_ok=True)

    # ---- P4: set_sk5 repair branch ----
    write_sk5(cfgdir, True)
    (stubbin / "mode").write_text("live")
    sh(str(stubbin / "systemctl"), "restart", "openvpn-sk5-singbox", env=env)
    for _ in range(20):
        if "LOWER_UP" in (link_flags() or ""):
            break
        time.sleep(0.5)
    # Break only the policy (delete rule + flush table), daemon alive.
    sh("bash", script, "disable", env=env)
    (stubbin / "started").unlink(missing_ok=True)
    # daemon still alive (stub holds tun1? disable flushed the table
    # but did not stop the daemon -- tun1 stays live).
    cell("P4a setup: daemon alive, policy missing, enabled=true",
         "LOWER_UP" in (link_flags() or "")
         and "lookup 100" not in rules()
         and sm._singbox_running() is True, "")
    pid_before = (cfgdir / "sing-box.pid").read_text().strip()
    st4 = sm.set_sk5()
    pid_after = (cfgdir / "sing-box.pid").read_text().strip()
    cell("P4b set_sk5() repairs in place (repaired:true, same daemon pid)",
         st4.get("repaired") is True
         and "policy routing re-applied" in st4.get("repair_detail", [])
         and st4.get("policy_routing_active") is True
         and pid_after == pid_before, str(st4)[:220])
    kill_stub(cfgdir)
    sh("bash", script, "disable", env=env)
    (stubbin / "started").unlink(missing_ok=True)
    # P4c: daemon dead + enabled + policy missing -> enable() leg.
    write_sk5(cfgdir, True)
    (stubbin / "mode").write_text("live")
    st4c = sm.set_sk5()
    cell("P4c set_sk5() with dead daemon takes enable() leg (K1, restarted)",
         st4c.get("repaired") is True
         and "sing-box restarted" in st4c.get("repair_detail", [])
         and st4c.get("policy_routing_active") is True, str(st4c)[:220])
    kill_stub(cfgdir)
    sh("bash", script, "disable", env=env)
    (stubbin / "started").unlink(missing_ok=True)

    # ---- D5: daemon-held tun1 set down by hand (O-R24-1, post-BT) ----
    # Post-BT the linkdown-sensitive predicate must close R24's
    # O-R24-1 healthy-lie: with the device down, _policy_active()
    # is False, so P1 must NOT report healthy; it holds the
    # kill-switch, and P3 (operator enable) recovers via restart
    # (stop destroys the down device, fresh start is live).
    write_sk5(cfgdir, True)
    (stubbin / "mode").write_text("live")
    sh(str(stubbin / "systemctl"), "restart", "openvpn-sk5-singbox", env=env)
    for _ in range(20):
        if "LOWER_UP" in (link_flags() or ""):
            break
        time.sleep(0.5)
    sh("bash", script, "enable", env=env)
    sh("ip", "link", "set", "tun1", "down")
    cell("D5a held-down device: _policy_active() False (no healthy lie)",
         sm._policy_active(sm._load_config()) is False
         and "LOWER_UP" not in (link_flags() or ""), link_flags() or "absent")
    h5 = sm.check_health()
    cell("D5b P1 tick on held-down device: NOT healthy (kill-switch)",
         h5.get("healthy") is not True, str(h5))
    cell("D5c P1 tick does not delete the held device",
         sh("ip", "link", "show", "dev", "tun1").returncode == 0, "")
    try:
        st5 = sm.enable()
        raised5 = None
    except RuntimeError as exc:
        st5, raised5 = None, str(exc)
    cell("D5d operator enable() from held-down converges to K1",
         raised5 is None and st5 is not None
         and st5.get("policy_routing_active") is True, raised5 or "")
    kill_stub(cfgdir)
    sh("bash", script, "disable", env=env)
    (stubbin / "started").unlink(missing_ok=True)

    # ---- K8: live route, blackhole missing (R24 O-R24-2 carry) ----
    # P1 must NOT heal a missing blackhole while policy_ok: the
    # tick reports on the probe, never re-installs the fallback.
    # (Sandbox has no SK5, so the verdict itself is probe-limited;
    # the cell asserts only the blackhole's absence persisting.)
    write_sk5(cfgdir, True)
    (stubbin / "mode").write_text("live")
    sh(str(stubbin / "systemctl"), "restart", "openvpn-sk5-singbox", env=env)
    for _ in range(20):
        if "LOWER_UP" in (link_flags() or ""):
            break
        time.sleep(0.5)
    sh("bash", script, "enable", env=env)
    sh("ip", "route", "del", "blackhole", "default", "metric", "200",
       "table", "100")
    cell("K8a K8 built: live route, no blackhole, policy true",
         "default via 10.9.0.1 dev tun1" in table(env)
         and "blackhole" not in table(env)
         and sm._policy_active(sm._load_config()) is True, table(env).strip())
    sm.check_health()
    cell("K8b P1 tick does NOT reinstall the missing blackhole",
         "blackhole" not in table(env)
         and "default via 10.9.0.1 dev tun1" in table(env), table(env).strip())
    kill_stub(cfgdir)
    sh("bash", script, "disable", env=env)
    (stubbin / "started").unlink(missing_ok=True)

    # ---- D4: start-limit wedge ----
    write_sk5(cfgdir, True)
    (stubbin / "mode").write_text("live")
    # Wedge the unit: 6 restarts -> failed flag set.
    for _ in range(6):
        sh(str(stubbin / "systemctl"), "restart", "openvpn-sk5-singbox", env=env)
        kill_stub(cfgdir)
    cell("D4a unit wedged (failed flag set, daemon down)",
         (statedir / "failed").exists()
         and sm._singbox_running() is False, "")
    h4 = sm.check_health()
    cell("D4b P1 tick on wedged unit: blackholed_kill_switch (holds, honest)",
         h4.get("action") == "blackholed_kill_switch", str(h4))
    cell("D4c P1 tick does NOT restart the daemon (no auto-restart path)",
         sm._singbox_running() is False
         and not (statedir / "active").exists(), "")
    try:
        st_d4 = sm.enable()
        raised_d4 = None
    except RuntimeError as exc:
        st_d4, raised_d4 = None, str(exc)
    cell("D4d operator enable() does reset-failed + restart, converges to K1",
         raised_d4 is None and st_d4 is not None
         and st_d4.get("policy_routing_active") is True, raised_d4 or "")
    kill_stub(cfgdir)
    sh("bash", script, "disable", env=env)
    (stubbin / "started").unlink(missing_ok=True)

    # ---- R9: bare _apply_policy() default verb ----
    # Premise: no device. Establish it explicitly -- on a mutant
    # tree an earlier failing cell (E1b on m2) can leave a
    # persistent placeholder behind, and R9 must not go red on
    # that pollution (its target is the default verb, not the
    # device). This delete is probe premise-establishment, not
    # product behaviour.
    sh("ip", "link", "del", "tun1")
    write_sk5(cfgdir, False)
    sm._apply_policy()
    cell("R9 bare _apply_policy() is repair semantics (no device, blackhole+rule)",
         sh("ip", "link", "show", "dev", "tun1").returncode != 0
         and "blackhole" in table(env) and "lookup 100" in rules(), "")
    sh("bash", script, "disable", env=env)

    print(f"\n{len(FAILURES)} FAIL(s): {FAILURES}" if FAILURES else "\nALL PASS")
    return 1 if FAILURES else 0


def main():
    if os.environ.get("R25_IN_NS") != "1":
        env = dict(os.environ, R25_IN_NS="1")
        r = subprocess.run(["unshare", "-rmn", sys.executable,
                            os.path.abspath(__file__)], env=env)
        return r.returncode
    return inside_ns()


if __name__ == "__main__":
    sys.exit(main())

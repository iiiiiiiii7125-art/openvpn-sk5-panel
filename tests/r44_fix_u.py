#!/usr/bin/env python3
"""Fix-U probe (r44_fix_u.py) — R44-L5-F1/F2/F3: manager-layer state honesty.

  F1  set_udp_over_tcp wedge: a flip whose restart fails must leave a
      durable marker; a same-value retry re-attempts the restart
      (raises) instead of returning a silent 200 on a dead chain; a
      same-value call with no failed flip behind it still no-ops
      (R6-P2-2); a successful enable() clears the marker.
  F2  check_health on a corrupt sk5.json returns a config_error
      verdict (recorded to health.json, no state change), never raises
      out of the 60 s timer.
  F3  openvpn PID identity: _pid_is_openvpn by executable/path (never
      a bare argv[0] or the pid number alone); server_status reports
      running=false for a stale pid; stop_server leaves the innocent
      process alive and unlinks the stale file.

Run as ROOT from the repo root: python3 tests/r44_fix_u.py
Exit code = number of FAILs. Stdlib only; all state under mkdtemp
scratch dirs; SINGBOX_BIN points at a nonexistent binary so every
real start fails (the wedge precondition). The enable() success path
(U4) is driven with stubbed environment calls (daemon start, tun1,
policy) -- the code under test is enable()'s own persist, not the
environment.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TREE / "core"))
sys.path.insert(0, str(TREE / "egress"))

RESULTS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAILED: ") + name
          + (f" | {detail}" if detail else ""), flush=True)


WORK = Path(tempfile.mkdtemp(prefix="r44fixu-"))

# ------------------------------------------------------------------ F1/F2
os.environ["OVPN_SK5_CONFIG_DIR"] = str(WORK / "sk5cfg")
import sk5_manager as sm  # noqa: E402

cfgdir = WORK / "sk5cfg"
cfgdir.mkdir()
sm.CONFIG_DIR = cfgdir
sm.CONFIG_FILE = cfgdir / "sk5.json"
sm.RENDERED_CONFIG = cfgdir / "sing-box.json"
sm.LOG_FILE = cfgdir / "sing-box.log"
sm.PID_FILE = cfgdir / "sing-box.pid"
sm.HEALTH_FILE = cfgdir / "health.json"
sm.SINGBOX_BIN = "/nonexistent/sing-box"  # no binary: every start fails


def load_raw():
    return json.loads(sm.CONFIG_FILE.read_text(encoding="utf-8"))


# U1: flip with a failing restart raises AND leaves the marker on disk.
sm._save_config({**sm._default_config(), "host": "127.0.0.1", "port": 11080,
                 "username": "u1", "password": "pw", "enabled": True,
                 "fail_open": False, "udp_over_tcp": False})
try:
    sm.set_udp_over_tcp(True)
    flip_raised = None
except Exception as exc:  # noqa: BLE001
    flip_raised = str(exc)
raw = load_raw()
cell("U1 flip with failing restart raises, marker set on disk",
     flip_raised is not None and raw.get("udp_over_tcp") is True
     and raw.get("uot_restart_failed") is True,
     f"raised={flip_raised} raw_uot={raw.get('udp_over_tcp')} "
     f"marker={raw.get('uot_restart_failed')}")

# U2: same-value retry re-attempts (raises), marker stays set.
try:
    sm.set_udp_over_tcp(True)
    retry_raised = None
except Exception as exc:  # noqa: BLE001
    retry_raised = str(exc)
raw = load_raw()
cell("U2 same-value retry raises, marker stays set",
     retry_raised is not None and raw.get("uot_restart_failed") is True,
     f"raised={retry_raised} marker={raw.get('uot_restart_failed')}")

# U3: same-value call with no failed flip behind it still no-ops
# (R6-P2-2) -- daemon untouched, no raise.
sm._save_config({**sm._default_config(), "host": "127.0.0.1", "port": 11080,
                 "username": "u1", "password": "pw", "enabled": True,
                 "fail_open": False, "udp_over_tcp": False})
try:
    sm.set_udp_over_tcp(False)
    noop_ok = True
except Exception as exc:  # noqa: BLE001
    noop_ok, noop_err = False, str(exc)
cell("U3 same-value call with no marker no-ops (R6-P2-2 kept)",
     noop_ok and not sm._singbox_running()
     and load_raw().get("uot_restart_failed") is False,
     f"noop_ok={noop_ok}")

# U4: a successful enable() clears the marker (stubbed environment).
sm._save_config({**sm._default_config(), "host": "127.0.0.1", "port": 11080,
                 "username": "u1", "password": "pw", "enabled": True,
                 "fail_open": False, "udp_over_tcp": True,
                 "uot_restart_failed": True})
saved = {}
for name in ("_start_singbox", "_tun1_live", "_apply_policy",
             "_policy_active", "_remove_dead_tun1_placeholder",
             "_render_singbox_config", "current_egress_ip"):
    saved[name] = getattr(sm, name)
try:
    sm._start_singbox = lambda: None
    sm._tun1_live = lambda: True
    sm._apply_policy = lambda **kw: None
    sm._policy_active = lambda cfg: True
    sm._remove_dead_tun1_placeholder = lambda: None
    sm._render_singbox_config = lambda cfg: sm.RENDERED_CONFIG
    sm.current_egress_ip = lambda: None
    sm.enable()
    enable_ok = True
except Exception as exc:  # noqa: BLE001
    enable_ok, enable_err = False, str(exc)
finally:
    for name, fn in saved.items():
        setattr(sm, name, fn)
cell("U4 successful enable() clears the marker",
     enable_ok and load_raw().get("uot_restart_failed") is False,
     f"enable_ok={enable_ok} marker={load_raw().get('uot_restart_failed')}")

# U5/U6: check_health on a corrupt config.
sm.CONFIG_FILE.write_text("{not json", encoding="utf-8")
try:
    h = sm.check_health()
    raised = None
except Exception as exc:  # noqa: BLE001
    h, raised = None, "%s: %s" % (type(exc).__name__, exc)
health = None
try:
    health = json.loads(sm.HEALTH_FILE.read_text(encoding="utf-8"))
except (OSError, ValueError):
    health = None
cell("U5 check_health on corrupt config returns a config_error verdict",
     raised is None and isinstance(h, dict)
     and h.get("action") == "config_error" and h.get("healthy") is False,
     f"raised={raised} h={h}")
cell("U6 config_error verdict is recorded to health.json",
     isinstance(health, dict) and health.get("action") == "config_error",
     f"health={health}")

# All spawned sleepers get DEVNULL stdio: a leftover sleeper must never
# hold the probe's stdout pipe open (a previous draft hung tail -14
# for 3 minutes on exactly that: the U7c script's inner sleep
# inherited the pipe and survived its parent).
DEVNULL = subprocess.DEVNULL


def wait_exec(pid, needle, timeout=5.0):
    """Wait until the child has execed (its cmdline contains needle).

    Popen returns after fork; the child may not have execed yet, and
    an identity check run in that window reads the *parent's* exe /
    cmdline instead -- a flaky False, not a product signal.
    """
    import time as _time
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                if needle in f.read():
                    return True
        except OSError:
            return False
        _time.sleep(0.05)
    return False
os.environ["OPENVPN_PID_FILE"] = str(WORK / "ovpn.pid")
os.environ["OPENVPN_SERVER_DIR"] = str(WORK / "srv")
import openvpn_manager as om  # noqa: E402

pidfile = WORK / "ovpn.pid"
srv = WORK / "srv"
srv.mkdir(exist_ok=True)

# U7a: a plain sleep is not openvpn (exe + cmdline both say so).
victim = subprocess.Popen(["sleep", "600"],
                          stdout=DEVNULL, stderr=DEVNULL)
try:
    cell("U7a _pid_is_openvpn(sleep) is False",
         om._pid_is_openvpn(victim.pid) is False,
         f"pid={victim.pid}")

    # U7b: a bare argv[0]="openvpn" with no slash proves nothing.
    liar = subprocess.Popen(["bash", "-c", "exec -a openvpn sleep 600"],
                            stdout=DEVNULL, stderr=DEVNULL)
    try:
        wait_exec(liar.pid, b"openvpn")
        cell("U7b _pid_is_openvpn(bare argv[0]='openvpn') is False",
             om._pid_is_openvpn(liar.pid) is False,
             f"pid={liar.pid}")
    finally:
        liar.terminate()
        liar.wait(timeout=5)

    # U7c: a file named openvpn run as a script counts (path rule --
    # the same shape the Fix-C/L5 fake daemons rely on). The inner
    # sleep's stdio is /dev/null so it cannot hold the probe pipe.
    bindir = WORK / "bin"
    bindir.mkdir()
    script = bindir / "openvpn"
    script.write_text("#!/bin/sh\nsleep 600 </dev/null >/dev/null 2>&1\n")
    script.chmod(0o755)
    daemon = subprocess.Popen([str(script)],
                              stdout=DEVNULL, stderr=DEVNULL,
                              start_new_session=True)
    try:
        wait_exec(daemon.pid, str(script).encode())
        cell("U7c _pid_is_openvpn(script named openvpn) is True",
             om._pid_is_openvpn(daemon.pid) is True,
             f"pid={daemon.pid}")

        # U7d: a binary named openvpn counts (exe rule).
        bindir2 = WORK / "bin2"
        bindir2.mkdir()
        exe_copy = bindir2 / "openvpn"
        shutil.copy("/bin/sleep", exe_copy)
        exe_copy.chmod(0o755)
        exe_proc = subprocess.Popen([str(exe_copy), "600"],
                                    stdout=DEVNULL, stderr=DEVNULL)
        try:
            wait_exec(exe_proc.pid, str(exe_copy).encode())
            cell("U7d _pid_is_openvpn(binary named openvpn) is True",
                 om._pid_is_openvpn(exe_proc.pid) is True,
                 f"pid={exe_proc.pid}")
        finally:
            exe_proc.terminate()
            exe_proc.wait(timeout=5)
    finally:
        # Kill the whole session: the script's inner sleep is a child
        # of the shell, and a plain terminate() on the shell orphans
        # it (600 s leak, as the first draft proved).
        try:
            os.killpg(daemon.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        daemon.wait(timeout=5)

    # U8/U9: stale PID file end to end.
    pidfile.write_text(str(victim.pid) + "\n")
    st = om.server_status()
    cell("U8 server_status with a stale PID file reports running=false",
         st.get("running") is False,
         f"st={st} victim_pid={victim.pid}")
    try:
        om.stop_server()
        stop_raised = None
    except Exception as exc:  # noqa: BLE001
        stop_raised = str(exc)
    cell("U9 stop_server on a stale PID file leaves the innocent "
         "process alive and unlinks the stale file",
         victim.poll() is None and not pidfile.exists(),
         f"alive={victim.poll() is None} pidfile_gone={not pidfile.exists()} "
         f"stop_raised={stop_raised}")
finally:
    if victim.poll() is None:
        victim.terminate()
        victim.wait(timeout=5)
    if pidfile.exists():
        pidfile.unlink()

print()
fails = [n for n, ok, _ in RESULTS if not ok]
print(f"TOTAL {len(RESULTS)} cells, FAIL {len(fails)}: {fails}")
sys.exit(len(fails))

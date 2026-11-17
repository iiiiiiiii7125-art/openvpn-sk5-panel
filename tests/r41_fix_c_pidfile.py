#!/usr/bin/env python3
"""R41 Fix-C probe: failed sing-box start must not leave a stale PID
file, and stop must never SIGTERM an innocent pid reuser.

Reproduces R41-L4-P2-4 (E3): a fake sing-box that passes `check`
but dies on `run` used to leave sing-box.pid behind; a later stop
then SIGTERMed whatever process reused that pid (sleep rc=-15).

Usage: python3 tests/r41_fix_c_pidfile.py [path/to/sk5_manager.py]
Exit 0 iff every case matches its expectation.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MODULE = sys.argv[1] if len(sys.argv) > 1 else "egress/sk5_manager.py"


def _proc_alive(pid):
    """True iff the pid is a live (non-zombie) process. A bare
    os.kill(pid, 0) succeeds on zombies -- the daemon our probe
    spawned is a child of this process, so after the kill it sits
    as a zombie until reaped; that is dead, not alive."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            stat = f.read()
        state = stat.rsplit(b")", 1)[1].split()[0]
        return state != b"Z"
    except OSError:
        return False


def load(path):
    spec = importlib.util.spec_from_file_location("sm_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DYING = """#!/bin/sh
# passes `check`, dies immediately on `run`
if [ "$1" = check ]; then exit 0; else exit 1; fi
"""

LIVING = """#!/bin/sh
# passes `check`, stays alive on `run` until SIGTERM
if [ "$1" = check ]; then exit 0; fi
trap 'exit 0' TERM
sleep 30
"""


def write_fake(d, name, body):
    p = d / name
    p.write_text(body, encoding="utf-8")
    p.chmod(0o755)
    return p


def main():
    sm = load(MODULE)
    real_run = sm._run

    def fake_run(cmd, timeout=30):
        if cmd and cmd[0] == "systemctl":
            # No unit in this environment: force the direct path.
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        return real_run(cmd, timeout=timeout)

    sm._run = fake_run
    fails = 0

    def check(name, cond, detail=""):
        nonlocal fails
        print(f"{'PASS' if cond else 'FAIL'}: {name} {detail}")
        if not cond:
            fails += 1

    with tempfile.TemporaryDirectory(prefix="r41c-pid-") as td:
        d = Path(td)
        sm.CONFIG_DIR = d
        sm.PID_FILE = d / "sing-box.pid"
        sm.LOG_FILE = d / "sing-box.log"
        sm.RENDERED_CONFIG = d / "sing-box.json"
        sm.RENDERED_CONFIG.write_text("{}\n", encoding="utf-8")

        # --- Test 1: failed start leaves no PID file ---
        sm.SINGBOX_BIN = str(write_fake(d, "sing-box", DYING))
        try:
            sm._start_singbox()
            check("failed-start-raises", False, "(no exception)")
        except RuntimeError as e:
            check("failed-start-raises", "exited immediately" in str(e), str(e)[:80])
        check("failed-start-no-pidfile", not sm.PID_FILE.exists(),
              f"(exists={sm.PID_FILE.exists()})")

        # --- Test 2: stop must not kill an innocent pid reuser ---
        victim = subprocess.Popen(["sleep", "300"])
        try:
            sm.PID_FILE.write_text(str(victim.pid) + "\n", encoding="utf-8")
            sm._stop_singbox_direct()
            time.sleep(0.2)
            check("stop-spares-innocent-pid", victim.poll() is None,
                  f"(sleep rc={victim.poll()})")
            check("stop-unlinks-stale-pidfile", not sm.PID_FILE.exists())
        finally:
            victim.terminate()
            victim.wait()

        # --- Test 3: _singbox_running must not trust a stale pid ---
        victim2 = subprocess.Popen(["sleep", "300"])
        try:
            sm.PID_FILE.write_text(str(victim2.pid) + "\n", encoding="utf-8")
            check("running-false-for-innocent-pid", sm._singbox_running() is False)
        finally:
            victim2.terminate()
            victim2.wait()
            sm.PID_FILE.unlink(missing_ok=True)

        # --- Test 4: the normal path still works end to end ---
        sm.SINGBOX_BIN = str(write_fake(d, "sing-box", LIVING))
        try:
            sm._start_singbox()
        except RuntimeError as e:
            check("live-start-succeeds", False, str(e)[:80])
        else:
            check("live-start-succeeds", True)
            live_pid = int(sm.PID_FILE.read_text().strip())
            if hasattr(sm, "_pid_is_singbox"):
                is_ours = sm._pid_is_singbox(live_pid)
            else:  # baseline module: read /proc directly
                is_ours = b"sing-box" in Path(f"/proc/{live_pid}/cmdline").read_bytes()
            check("live-start-pidfile-holds-daemon",
                  live_pid > 0 and is_ours)
            check("running-true-for-real-daemon", sm._singbox_running() is True)
            sm._stop_singbox_direct()
            time.sleep(0.5)
            check("stop-kills-real-daemon", not _proc_alive(live_pid))
            check("stop-unlinks-pidfile", not sm.PID_FILE.exists())

    print(f"result: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

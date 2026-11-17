#!/usr/bin/env python3
"""R42-F3 probe D1 (AUDIT-R42, lane F3): _pid_is_singbox() substring
false positive.

_pid_is_singbox() (egress/sk5_manager.py) returns True when the bytes
"sing-box" appear ANYWHERE in /proc/<pid>/cmdline -- not just when the
process IS the sing-box binary. A stale PID file reused by any process
whose argv mentions sing-box (e.g. `systemctl is-active
openvpn-sk5-singbox`, `journalctl -u openvpn-sk5-singbox`, a shell
running a sing-box command) is then mistaken for the daemon:
_singbox_running() reports True, and _stop_singbox_direct() SIGTERMs
the innocent process. Residual hole in the R41-L4-P2-4 fix, which
only guarded against a pid reused by an unrelated process.

Proof: spawn /bin/sleep with argv[0]="sing-box" (its cmdline contains
"sing-box" but it is not sing-box), point a scratch PID file at it,
and show _pid_is_singbox() True, _singbox_running() True, and
_stop_singbox_direct() killing it (returncode -15 / SIGTERM).

Runs on the host (no netns needed): the PID file lives in a scratch
OVPN_SK5_CONFIG_DIR, the victim is a sleep we spawned, nothing else
is touched. The sandbox host has no openvpn-sk5-singbox unit, so the
systemd branch of _singbox_running() falls through to the PID file.

Usage: python3 tests/r42_f3_pid.py [path/to/sk5_manager.py]
Exit 0 iff every expectation holds (i.e. the defect reproduces).
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MODULE = sys.argv[1] if len(sys.argv) > 1 else "egress/sk5_manager.py"


def load(path):
    spec = importlib.util.spec_from_file_location("sm_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    tmp = Path(tempfile.mkdtemp(prefix="r42f3-pid-"))
    os.environ["OVPN_SK5_CONFIG_DIR"] = str(tmp)
    sm = load(MODULE)
    assert str(sm.PID_FILE).startswith(str(tmp)), sm.PID_FILE

    # Victim: /bin/sleep 3600, but argv[0] is "sing-box" -- cmdline
    # reads "sing-box\\03600\\0", which contains b"sing-box".
    victim = subprocess.Popen(["sing-box", "3600"],
                              executable="/bin/sleep")
    try:
        time.sleep(0.2)
        assert victim.poll() is None, "victim exited early"
        with open("/proc/%d/cmdline" % victim.pid, "rb") as f:
            cmdline = f.read()
        print("victim pid=%d cmdline=%r" % (victim.pid, cmdline))
        assert b"sing-box" in cmdline
        assert b"sing-box" not in os.readlink("/proc/%d/exe" % victim.pid).encode(), \
            "victim must not BE sing-box"

        sm.PID_FILE.write_text("%d\n" % victim.pid)
        is_sb = sm._pid_is_singbox(victim.pid)
        print("D1 _pid_is_singbox(fake argv) = %s (defect: True)" % is_sb)
        running = sm._singbox_running()
        print("D1 _singbox_running() = %s (defect: True)" % running)
        sm._stop_singbox_direct()
        time.sleep(0.3)
        rc = victim.poll()
        print("D1 victim returncode after _stop_singbox_direct() = %s "
              "(defect: -15 SIGTERM)" % rc)
        print("D1 PID file still exists = %s" % sm.PID_FILE.exists())
        ok = is_sb is True and running is True and rc == -15
        print("R42F3 D1: %s" % ("CONFIRMED: substring match kills an "
                                 "innocent pid reuser" if ok else
                                 "NOT-CONFIRMED"))
        sys.exit(0 if ok else 1)
    finally:
        if victim.poll() is None:
            victim.kill()
        victim.wait()
        try:
            sm.PID_FILE.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()

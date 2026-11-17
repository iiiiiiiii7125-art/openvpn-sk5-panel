#!/usr/bin/env python3
"""R45 live-fix Fix-AC probe: start_server direct fallback must create the
--writepid parent dir (LIVE-R45-1).

Proven live with the real binary: with /run/openvpn-server missing, the
fallback died rc=1 ("--writepid fails with '/run/openvpn-server/server.pid':
No such file or directory") because it mkdir'd only the log parent.

There is NO openvpn binary in the sandbox, so the proof uses a fake
``openvpn`` on PATH that mimics the real binary's failure mode exactly:
it exits 1 with the real error text when the --writepid parent is missing,
and otherwise daemonises a long-lived process whose argv[0] is a path
named "openvpn" (so the product's _pid_is_openvpn identity check accepts
it, exactly as it would a real daemon). The fake never creates the pid
parent itself -- the only mkdir that can save the start is the product's.

Run as ROOT from the repo root:
    python3 tests/r45_fix_ac_pidparent.py
    R45AC_TREE=/path/to/tree python3 tests/r45_fix_ac_pidparent.py
R45AC_TREE defaults to the repo this probe lives in. The probe asserts
FIXED behaviour, so on the baseline tree (6eac5af) the defect cells FAIL.
"""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

RESULTS = []


def cell(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail))


FAKE_OPENVPN = """#!/bin/bash
# Fake openvpn: mimics the real binary's --writepid failure mode and
# --daemon behaviour. Never creates the pid parent itself. (bash, not
# sh: the daemon spawn below needs exec -a, which dash lacks.)
pidfile=""
logfile=""
prev=""
for a in "$@"; do
  case "$prev" in
    --writepid) pidfile="$a";;
    --log-append) logfile="$a";;
  esac
  prev="$a"
done
parent=$(dirname "$pidfile")
if [ ! -d "$parent" ]; then
  echo "Options error: --writepid fails with '$pidfile': No such file or directory (errno=2)" >&2
  exit 1
fi
[ -n "$logfile" ] && echo "fake-openvpn started" >> "$logfile"
# Daemonise like real --daemon: background a long-lived process whose
# argv[0] is a path named "openvpn" so _pid_is_openvpn accepts it. Its
# stdio MUST be redirected: _run captures the stub's pipes and waits for
# EOF, and an inheriting daemon would hang it until the timeout (real
# --daemon closes stdio on daemonising).
( exec -a "$0" /bin/sleep 300 </dev/null >/dev/null 2>&1 & echo $! > "$pidfile" )
exit 0
"""

FAKE_SYSTEMCTL = """#!/bin/sh
# Fake systemctl that claims the unit is active, so start_server takes
# the systemd path and never reaches the direct fallback.
case "$1" in
  is-active) exit 0 ;;
  start) exit 0 ;;
  show) echo 0 ;;
  *) exit 1 ;;
esac
"""

SERVER_CONF = """port 1194
proto udp
dev tun
ca ca.crt
cert server.crt
key server.key
dh dh.pem
server 10.8.0.0 255.255.255.0
"""


def main():
    tree = Path(os.environ.get("R45AC_TREE", Path(__file__).resolve().parents[1]))
    base = Path("/tmp/r45ac-probe-%d" % os.getpid())
    daemon_pid = []

    def cleanup_daemon():
        for pid in daemon_pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    try:
        bindir = base / "bin"
        bindir.mkdir(parents=True)
        fake_ovpn = bindir / "openvpn"
        fake_ovpn.write_text(FAKE_OPENVPN, encoding="utf-8")
        fake_ovpn.chmod(0o755)
        server_dir = base / "server"
        server_dir.mkdir(parents=True)
        (server_dir / "server.conf").write_text(SERVER_CONF, encoding="utf-8")

        pidfile = base / "run" / "openvpn-server" / "server.pid"
        os.environ["OPENVPN_SERVER_DIR"] = str(server_dir)
        os.environ["OPENVPN_CA_DIR"] = str(base / "ca")
        os.environ["OPENVPN_PID_FILE"] = str(pidfile)
        os.environ["PATH"] = str(bindir) + ":" + os.environ["PATH"]
        sys.path.insert(0, str(tree))
        import core.openvpn_manager as om

        # A1: pid parent is missing before the start (sanity).
        cell("A1 pid parent missing before start",
             not pidfile.parent.exists(), str(pidfile.parent))

        # A2: the defect / the fix -- start with a missing pid parent.
        started = False
        err = ""
        try:
            st = om.start_server()
            started = bool(st.get("running"))
            if st.get("pid"):
                daemon_pid.append(st["pid"])
        except Exception as exc:  # noqa: BLE001 - the defect raises here
            err = str(exc)
        cell("A2 start_server succeeds with missing pid parent",
             started, "running=%s err=%s" % (started, err[:120]))
        cell("A2b failure names --writepid when it fails",
             started or "writepid" in err, err[:120])

        # A3: the pid parent now exists and the daemon is alive + identified.
        pid_ok = pidfile.exists()
        pid = None
        if pid_ok:
            try:
                pid = int(pidfile.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                pid = None
        cell("A3 pid file exists and names a live process",
             pid_ok and pid is not None and om._pid_is_openvpn(pid),
             "pid=%s" % pid)
        if pid is not None and pid not in daemon_pid:
            daemon_pid.append(pid)
        st = om.server_status()
        cell("A3b server_status running with the daemon pid",
             st.get("running") is True and st.get("pid") == pid,
             "running=%s pid=%s" % (st.get("running"), st.get("pid")))

        # A4: stop_server kills the identified daemon and unlinks the file.
        if pid is not None:
            st2 = om.stop_server()
            time.sleep(0.2)
            alive = True
            try:
                os.kill(pid, 0)
            except OSError:
                alive = False
            cell("A4 stop_server kills daemon and clears pid file",
                 (not alive) and (not pidfile.exists())
                 and st2.get("running") is False,
                 "alive=%s pidfile=%s running=%s"
                 % (alive, pidfile.exists(), st2.get("running")))
            daemon_pid[:] = [p for p in daemon_pid if p != pid]

        # A5: re-start with the parent now existing still works (control).
        started2 = False
        try:
            st3 = om.start_server()
            started2 = bool(st3.get("running"))
            if st3.get("pid"):
                daemon_pid.append(st3["pid"])
        except Exception as exc:  # noqa: BLE001
            started2 = False
        cell("A5 re-start with existing pid parent works",
             started2, "running=%s" % started2)

        # A6: systemd path untouched -- a systemctl that claims the unit is
        # active must make start_server return WITHOUT creating the pid
        # parent. Remove the parent first, then add the fake systemctl.
        for pid in list(daemon_pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        daemon_pid.clear()
        time.sleep(0.2)
        shutil.rmtree(base / "run", ignore_errors=True)
        sysbindir = base / "sysbin"
        sysbindir.mkdir()
        fake_ctl = sysbindir / "systemctl"
        fake_ctl.write_text(FAKE_SYSTEMCTL, encoding="utf-8")
        fake_ctl.chmod(0o755)
        os.environ["PATH"] = str(sysbindir) + ":" + os.environ["PATH"]
        st4 = om.start_server()
        cell("A6 systemd path returns without touching pid parent",
             st4.get("running") is True and not pidfile.parent.exists(),
             "running=%s parent_exists=%s"
             % (st4.get("running"), pidfile.parent.exists()))
    finally:
        cleanup_daemon()
        shutil.rmtree(base, ignore_errors=True)

    fails = [n for n, ok, _ in RESULTS if not ok]
    print("TOTAL %d cells, FAIL %d: %s" % (len(RESULTS), len(fails), fails))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

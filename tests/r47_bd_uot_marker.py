#!/usr/bin/env python3
"""R47-BD probe 2: uot_restart_failed marker via set_sk5() (R47-L6-2)
-- fixed behavior. Asserts the R44-L5-F1 protocol holds on the
set_sk5() entry path: when enable() raises inside set_sk5() after a
chain-affecting change, the marker is stored, so a later same-value
set_udp_over_tcp() re-attempts the restart instead of silently
returning 200 on a dead chain.

Method: stub _start_singbox to raise (daemon that cannot start),
seed an enabled chain with udp_over_tcp=False, then:
  A. flip via set_sk5(udp_over_tcp=True) -> raises; stored marker
     must be True (the value was stored but never applied).
  B. same-value set_udp_over_tcp(True) -> must re-attempt (raise)
     with a _start_singbox call; a silent return is the defect.
  C. control: the same sequence through set_udp_over_tcp() directly
     sets the marker and the retry re-attempts (raises).
  D. contrast: a set_sk5() re-save with the same value raises
     honestly (via _chain_effective repair).
  E. host-only change with a failed enable() also marks (the marker
     means "this save never took effect", whichever field changed).

No network, no sing-box binary, no root: the daemon start is stubbed.
Exit 0 iff the marker protocol holds on every path.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "egress"))
import sk5_manager as m  # noqa: E402

PASS = 0
FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print("PASS: " + msg)


def bad(msg):
    global FAIL
    FAIL += 1
    print("FAIL: " + msg)


def seed(cfgdir, **over):
    cfg = {"host": "127.0.0.1", "port": 1080, "username": "",
           "password": "", "enabled": True, "fail_open": False,
           "udp_over_tcp": False, "uot_restart_failed": False}
    cfg.update(over)
    (Path(cfgdir) / "sk5.json").write_text(json.dumps(cfg), encoding="utf-8")


def stored(cfgdir):
    return json.loads((Path(cfgdir) / "sk5.json").read_text(encoding="utf-8"))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="r47bd-uot-"))
    m.CONFIG_DIR = tmp
    m.CONFIG_FILE = tmp / "sk5.json"
    m.RENDERED_CONFIG = tmp / "sing-box.json"
    m.PID_FILE = tmp / "sing-box.pid"
    m.LOG_FILE = tmp / "sing-box.log"
    m.HEALTH_FILE = tmp / "health.json"

    calls = {"start": 0}

    def stub_start():
        calls["start"] += 1
        raise RuntimeError("stubbed daemon start failure")

    m._start_singbox = stub_start

    # --- A. flip via set_sk5, restart fails -> marker must be set ---
    seed(tmp)
    try:
        m.set_sk5(udp_over_tcp=True)
        bad("A set_sk5(udp_over_tcp=True) with a dead daemon did not raise")
    except RuntimeError as exc:
        ok("A set_sk5(udp_over_tcp=True) raises honestly on failed restart: %s"
           % str(exc)[:60])
    s = stored(tmp)
    if s.get("udp_over_tcp") is True and s.get("uot_restart_failed") is True:
        ok("A marker is True after the failed set_sk5 flip "
           "(value stored, never applied, now marked)")
    else:
        bad("A stored state after failed set_sk5 flip: %r" % s)

    # --- B. same-value set_udp_over_tcp must re-attempt, not go silent ---
    before = calls["start"]
    try:
        result = m.set_udp_over_tcp(True)
        bad("B set_udp_over_tcp(True) returned SILENTLY (start calls "
            "%d->%d) while the daemon is down and the stored value was "
            "never applied; returned keys: %s"
            % (before, calls["start"], sorted(result.keys())))
    except RuntimeError as exc:
        if calls["start"] > before:
            ok("B set_udp_over_tcp(True) re-attempted the restart "
               "(start called %d time(s)) and raised honestly: %s"
               % (calls["start"] - before, str(exc)[:60]))
        else:
            bad("B set_udp_over_tcp(True) raised without attempting a restart")

    # --- C. control: flip via set_udp_over_tcp directly ---
    seed(tmp)
    calls["start"] = 0
    try:
        m.set_udp_over_tcp(True)
        bad("C direct set_udp_over_tcp(True) with a dead daemon did not raise")
    except RuntimeError:
        ok("C direct set_udp_over_tcp(True) raises on failed restart")
    s = stored(tmp)
    if s.get("uot_restart_failed") is True:
        ok("C marker is True after the direct-path failure")
    else:
        bad("C marker after direct-path failure: %r" % s.get("uot_restart_failed"))
    calls["start"] = 0
    try:
        m.set_udp_over_tcp(True)
        bad("C same-value retry returned silently (marker protocol broken)")
    except RuntimeError:
        if calls["start"] >= 1:
            ok("C same-value retry re-attempted the restart (start called "
               "%d time(s))" % calls["start"])
        else:
            bad("C retry raised without attempting a restart")

    # --- D. contrast: set_sk5 re-save with the same value ---
    seed(tmp, udp_over_tcp=True, uot_restart_failed=False)
    try:
        m.set_sk5(udp_over_tcp=True)
        bad("D set_sk5 re-save with the same value returned silently on a "
            "dead daemon")
    except RuntimeError:
        ok("D set_sk5 re-save raises honestly (via _chain_effective repair)")

    # --- E. host-only change with a failed enable() also marks ---
    seed(tmp)
    try:
        m.set_sk5(host="127.0.0.2")
        bad("E set_sk5(host-only change) with a dead daemon did not raise")
    except RuntimeError:
        ok("E set_sk5(host-only change) raises honestly on failed restart")
    s = stored(tmp)
    if s.get("host") == "127.0.0.2" and s.get("uot_restart_failed") is True:
        ok("E marker is True after a failed host-only save "
           "(the save never took effect)")
    else:
        bad("E stored state after failed host-only save: %r" % s)
    before = calls["start"]
    try:
        m.set_udp_over_tcp(False)
        bad("E same-value set_udp_over_tcp(False) returned silently after "
            "the failed host-only save")
    except RuntimeError:
        if calls["start"] > before:
            ok("E same-value retry re-attempted the restart and raised")
        else:
            bad("E retry raised without attempting a restart")

    print("result: PASS=%d FAIL=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

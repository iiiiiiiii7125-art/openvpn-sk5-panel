#!/usr/bin/env python3
"""AUDIT-R32 P2-1 regression probe: enable()'s LIVE-tun1 wait window.

The old shape `for _ in range(10): check -> sleep(0.5)` checked liveness
only at 0.0..4.5 s and raised at 5.0 s without ever checking at 5.0 s,
so a tun1 going live at 4.6..5.0 s was missed (loud 500, enabled stays
False) even though DELIVERY.md:131 promises a 5-second wait. The fix
is a deadline loop that checks at 0.0, 0.5, ..., 5.0 s (11 checks).

Real tun1 timing cannot be controlled in the sandbox, so the probe
drives enable() with a fake clock (time.monotonic/time.sleep patched)
and a stubbed _tun1_live that goes live at a controlled instant.
All other enable() collaborators are stubbed; nothing touches the
filesystem, the network, or a real daemon.

Usage: R32_TREE=<tree> python3 tests/r32_enable_wait_window.py
Exit code = number of FAILs.
"""
import importlib.util
import os
import sys
import time

TREE = os.environ.get("R32_TREE", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location(
    "sk5_manager_r32", os.path.join(TREE, "egress", "sk5_manager.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

FAILS = []


def cell(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


class FakeClock:
    """monotonic()/sleep() pair: sleep advances the clock, no real wait."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


def run_enable(live_at):
    """Run m.enable() with _tun1_live going live at fake time live_at
    (None = never). Returns (outcome, check_times, sleeps, saved)."""
    clock = FakeClock()
    check_times = []
    saved = []

    def fake_tun1_live():
        check_times.append(clock.now)
        return live_at is not None and clock.now >= live_at

    orig_sleep, orig_mono = time.sleep, time.monotonic
    time.sleep, time.monotonic = clock.sleep, clock.monotonic
    try:
        m._load_config = lambda: {"host": "proxy.example", "port": 1001,
                                  "username": "u", "password": "p",
                                  "enabled": False, "fail_open": False,
                                  "udp_over_tcp": False}
        m._validate = lambda *a: None
        m._render_singbox_config = lambda cfg: None
        m._remove_dead_tun1_placeholder = lambda: None
        m._start_singbox = lambda: None
        m._tun1_live = fake_tun1_live
        m._apply_policy = lambda verb=None: None
        m._policy_active = lambda cfg: True
        m._save_config = lambda cfg: saved.append(dict(cfg))
        m.get_status = lambda: {"ok": True, "enabled": True}
        try:
            m.enable()
            return ("ok", check_times, clock.sleeps, saved)
        except RuntimeError as e:
            return ("raise:" + str(e), check_times, clock.sleeps, saved)
    finally:
        time.sleep, time.monotonic = orig_sleep, orig_mono


# W1: tun1 goes live at 4.7 s -- inside the 4.6..5.0 s band the old
# shape missed. Must succeed, with a check at exactly 5.0 s.
out, checks, sleeps, saved = run_enable(4.7)
cell("W1 tun1 live at 4.7s -> enable succeeds",
     out == "ok" and checks[-1] == 5.0 and len(checks) == 11,
     f"out={out} checks={checks}")
cell("W1b tun1 live at 4.7s -> enabled persisted",
     len(saved) == 1 and saved[0].get("enabled") is True,
     f"saved={saved}")

# W2: tun1 goes live exactly at the 5.0 s deadline -- boundary inclusive.
out, checks, sleeps, saved = run_enable(5.0)
cell("W2 tun1 live at exactly 5.0s -> enable succeeds",
     out == "ok" and checks[-1] == 5.0 and len(checks) == 11,
     f"out={out} checks={checks}")

# W3: tun1 never goes live -- still raises with the same message, but
# only after a check AT 5.0 s (11 checks 0.0..5.0, 10 sleeps totalling
# 5.0 s), and nothing is persisted.
out, checks, sleeps, saved = run_enable(None)
cell("W3 tun1 never live -> raises 'within 5 s'",
     out.startswith("raise:") and "within 5 s" in out,
     f"out={out[:80]}")
cell("W3b tun1 never live -> 11 checks 0.0..5.0 (old shape: 10, last 4.5)",
     checks == [round(0.5 * i, 1) for i in range(11)],
     f"checks={checks}")
cell("W3c tun1 never live -> 10 sleeps totalling 5.0s, nothing saved",
     sleeps == [0.5] * 10 and saved == [],
     f"sleeps={sleeps} saved={saved}")

# W4: tun1 live immediately -- one check, no sleep.
out, checks, sleeps, saved = run_enable(0.0)
cell("W4 tun1 live at 0.0s -> succeeds with 1 check, 0 sleeps",
     out == "ok" and checks == [0.0] and sleeps == [],
     f"out={out} checks={checks} sleeps={sleeps}")

# W5: tun1 live at 4.5 s -- control: the old shape passed this too.
out, checks, sleeps, saved = run_enable(4.5)
cell("W5 tun1 live at 4.5s -> succeeds (control)",
     out == "ok" and checks[-1] == 4.5 and len(checks) == 10,
     f"out={out} checks={checks}")

print(f"R32 enable wait window: {8 - len(FAILS)}/8")
sys.exit(len(FAILS))

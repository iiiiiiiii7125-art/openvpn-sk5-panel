#!/usr/bin/env python3
"""R42-FIX-H cache-mechanics probe (host-side, stubbed probes).

The netns driver (tests/r42_fix_h_driver.sh) proves the request paths
are fast under a true blackhole, but under a blackhole the background
refresh can never succeed -- so it cannot prove the cache ever FILLS.
This probe stubs the probe functions and proves the mechanics
deterministically:

  H1  agent _egress_ip_cached(): cold cache returns None at once and
      kicks exactly one background refresh; after the refresh lands,
      the stubbed IP is returned; repeated calls do not re-probe
      inside the TTL.
  H2  agent action_get_status(): shape preserved -- top-level
      egress_ip and sk5["egress_ip"] both carry the cached value, and
      the dispatch stays fast even though the stubbed probe sleeps
      (a synchronous probe would take that long).
  H3  panel _outward_ip(): cold cache returns the LAN fallback at once
      (no synchronous probe); after the background detection lands,
      the stubbed public IP is returned; a stored server IP still
      wins immediately without touching the detector.
  H4  panel negative cache: a detection that returns None stamps the
      attempt, so repeated calls inside the TTL do not spawn a refresh
      on every call (stub call count stays put).

Run: python3 tests/r42_fix_h_cache.py (stdlib only; needs the Flask
venv on PYTHONPATH for the panel half, like the other panel probes:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \
    R42FIXH_TREE=<tree> OVPN_PANEL_DATA_DIR=<fresh-data> \
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \
    OVPN_SK5_CONFIG_DIR=<fresh-sk5cfg> \
    python3 <tree>/tests/r42_fix_h_cache.py
Without those env vars the panel cells are skipped (counted, reported).
Exit code = number of FAILs.
"""
import importlib.util
import os
import sys
import tempfile
import time

TREE = os.environ.get("R42FIXH_TREE", os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
for _sub in ("panel", "core", "egress"):
    sys.path.insert(0, os.path.join(TREE, _sub))

RESULTS = []


def check(name, passed, evidence=""):
    RESULTS.append((name, bool(passed)))
    print("R42FIXH %s: %s%s" % ("PASS" if passed else "FAIL",
                                name, (" | " + str(evidence)[:200])
                                if evidence else ""), flush=True)


def load_agent():
    spec = importlib.util.spec_from_file_location(
        "agent_under_test", os.path.join(TREE, "agent", "agent.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cell_h1_h2():
    agent = load_agent()
    calls = {"n": 0}

    def stub_egress():
        calls["n"] += 1
        time.sleep(0.2)
        return "203.0.113.7"

    agent.sk5_manager.current_egress_ip = stub_egress
    t0 = time.time()
    first = agent._egress_ip_cached()
    dt = time.time() - t0
    check("H1 cold cache returns None at once (no sync probe)",
          first is None and dt < 0.1,
          "first=%r secs=%.3f" % (first, dt))
    time.sleep(0.6)  # background refresh (0.2 s stub) must have landed
    second = agent._egress_ip_cached()
    check("H1 cache fills from the background refresh",
          second == "203.0.113.7", "second=%r" % second)
    for _ in range(5):
        agent._egress_ip_cached()
    check("H1 no re-probe inside the TTL (single-flight)",
          calls["n"] == 1, "probe_calls=%d" % calls["n"])

    # H2: shape + speed of a full dispatch while the probe is slow.
    def slow_stub():
        time.sleep(3)
        return "203.0.113.7"

    agent.sk5_manager.current_egress_ip = slow_stub
    # Expire the cache so the dispatch must refresh behind.
    agent._EGRESS_IP_CACHE.update({"at": 0.0, "ip": None})
    t0 = time.time()
    ok, result, error = agent.execute_command(
        {"id": "r42fixh-h2", "action": "get_status", "params": {}})
    dt = time.time() - t0
    check("H2 get_status dispatch fast with a 3 s probe behind it",
          ok and dt < 1.0, "ok=%s secs=%.2f" % (ok, dt))
    check("H2 top-level egress_ip == sk5 egress_ip (shape preserved)",
          (result or {}).get("egress_ip")
          == ((result or {}).get("sk5") or {}).get("egress_ip"),
          "top=%r sk5=%r" % ((result or {}).get("egress_ip"),
                             ((result or {}).get("sk5") or {}).get(
                                 "egress_ip")))


def cell_h3_h4():
    import app as panel  # noqa: E402

    calls = {"n": 0}

    def stub_detect():
        calls["n"] += 1
        return "203.0.113.8"

    panel.detect_public_ip = stub_detect
    panel._OUTWARD_IP_CACHE.update({"at": 0.0, "ip": None})
    t0 = time.time()
    first = panel._outward_ip()
    dt = time.time() - t0
    check("H3 cold cache returns the LAN fallback at once (no sync probe)",
          isinstance(first, str) and first != "203.0.113.8" and dt < 0.5,
          "first=%r secs=%.3f" % (first, dt))
    time.sleep(0.5)
    second = panel._outward_ip()
    check("H3 cache fills from the background detection",
          second == "203.0.113.8", "second=%r" % second)

    # Stored server IP wins immediately without touching the detector.
    before = calls["n"]
    data_dir = os.environ["OVPN_PANEL_DATA_DIR"]
    import json
    with open(os.path.join(data_dir, "server.json"), "w",
              encoding="utf-8") as f:
        json.dump({"server_ip": "203.0.113.9"}, f)
    got = panel._outward_ip()
    check("H3 stored server IP wins without probing",
          got == "203.0.113.9" and calls["n"] == before,
          "got=%r probe_calls=%d" % (got, calls["n"]))
    os.remove(os.path.join(data_dir, "server.json"))

    # H4: negative cache -- a failing detection stamps the attempt.
    def failing_detect():
        calls["n"] += 1
        return None

    panel.detect_public_ip = failing_detect
    panel._OUTWARD_IP_CACHE.update({"at": 0.0, "ip": None})
    before = calls["n"]
    panel._outward_ip()
    time.sleep(0.3)  # the failing refresh completes behind
    for _ in range(5):
        panel._outward_ip()
    check("H4 failed detection does not respawn a refresh per call",
          calls["n"] == before + 1, "probe_calls=%d" % (calls["n"] - before))


def main():
    cell_h1_h2()
    if all(k in os.environ for k in (
            "OVPN_PANEL_DATA_DIR", "OVPN_PANEL_SECRET_PATH",
            "OPENVPN_CA_DIR", "OPENVPN_SERVER_DIR", "OVPN_SK5_CONFIG_DIR")):
        cell_h3_h4()
    else:
        print("R42FIXH SKIP H3/H4 (panel harness env not set)", flush=True)
        RESULTS.append(("H3/H4 skipped (no panel env)", True))
    bad = [n for n, ok in RESULTS if not ok]
    print("R42FIXH cache: %d/%d PASS%s"
          % (len(RESULTS) - len(bad), len(RESULTS),
             (" FAIL: " + ", ".join(bad)) if bad else ""), flush=True)
    return len(bad)


if __name__ == "__main__":
    sys.exit(main())

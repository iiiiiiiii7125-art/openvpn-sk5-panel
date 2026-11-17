#!/usr/bin/env python3
"""R42-FIX-H probe (R42 fix round, lane Fix-H: probe budget).

Fixes under test (baseline 88b5891 stalls; fixed tree must be fast):
  F3-1  agent action_get_status: probe-free get_status() + cached
        egress IP instead of two sequential probes inline in the poll
        loop (was 10.08 s SK5-disabled, 20.05 s enabled+blackholed).
  F3-2  panel _outward_ip(): cached detection (stale-while-revalidate)
        instead of a synchronous 2x5 s HTTPS probe on every /api/status
        and every .ovpn render (was 10.10 s / 10.05 s, no stored IP).
  F3-5  toggle-only save + sk5/disable: probe-free stored-config read
        inside _SK5_MUTATE_LOCK (was 10.08 s / 10.09 s).

Run via the driver, not directly:
  bash tests/r42_fix_h_driver.sh <tree>

Env (set by the driver): OVPN_PANEL_DATA_DIR, OVPN_PANEL_SECRET_PATH,
OPENVPN_CA_DIR, OPENVPN_SERVER_DIR, OVPN_SK5_CONFIG_DIR (fresh dirs),
PYTHONPATH -> a venv with Flask 3.1.3 + bcrypt. No proxy env.
Blackhole: api.ipify.org + ifconfig.me -> 127.0.0.3, hold listeners on
:80/:443/:1080 (see tests/r42_fix_h_listen.py) -- the TRUE blackhole
the Fix-B harness lacked (it held :80/:1080 only, so the :443 HTTPS
probe failed fast and F3-2 survived its verification).

Cells (R42FIXH_CELL):
  A1  GET /api/status, no stored server IP, blackhole. PASS if http 200
      and < 2 s (baseline: 10.10 s). First call returns the LAN
      fallback while the detection runs behind (cold-cache tradeoff,
      same as the Fix-B egress cache); a second call must also be
      fast (negative cache: no repeated synchronous probe).
  A2  Same, with a stored server IP in server.json (control). PASS if
      http 200, < 2 s, remote_ip is the stored IP.
  A3  GET /api/openvpn/users/alice/ovpn (fixture user), no stored IP,
      then again with a stored IP. PASS if both http 200 and < 2 s
      (baseline: 10.05 s / 0.00 s). POST /api/openvpn/users is timed
      for speed only (sandbox has no easy-rsa binary, so create fails
      at signing before the render -- its render timing is needs-live,
      as in the F3 report).
  B1  agent execute_command(get_status), SK5 disabled, blackhole.
      PASS if ok and < 2 s (baseline: 10.07 s). egress_ip is None on
      the cold cache (documented tradeoff); the value lands on the
      next dispatch once the background refresh completes.
  B2  Same, SK5 enabled with blackholed host 127.0.0.3:1080. PASS if
      ok and < 2 s (baseline: 20.04 s).
  B3  Second agent get_status right after B2's shape (fresh cell, SK5
      enabled + blackholed): PASS if ok and < 2 s -- proves repeated
      dispatches stay fast (no repeated synchronous probe).
  C1  POST /api/sk5 {"enabled": false} (toggle-only save) and POST
      /api/sk5/disable, SK5 enabled + blackholed host. PASS if both
      http 200 and < 2 s each (baseline: 10.08 s / 10.09 s).

Exit 0 always; the report (not the exit code) carries the verdict.
"""
import importlib.util
import json
import os
import sys
import time

TREE = os.environ["R42FIXH_TREE"]
CELL = os.environ["R42FIXH_CELL"]
for _sub in ("panel", "core", "egress"):
    sys.path.insert(0, os.path.join(TREE, _sub))

import app as panel  # noqa: E402

DATA_DIR = os.environ["OVPN_PANEL_DATA_DIR"]
SK5_DIR = os.environ["OVPN_SK5_CONFIG_DIR"]

RESULTS = []
FAST = 2.0


def check(name, passed, evidence=""):
    RESULTS.append((name, bool(passed)))
    print("R42FIXH %s: %s%s" % ("PASS" if passed else "FAIL",
                                name, (" | " + str(evidence)[:300])
                                if evidence else ""), flush=True)


def write_sk5(enabled, host="127.0.0.3", port=1080):
    os.makedirs(SK5_DIR, exist_ok=True)
    cfg = {"host": host, "port": port, "username": "", "password": "",
           "enabled": enabled, "fail_open": False, "udp_over_tcp": False}
    with open(os.path.join(SK5_DIR, "sk5.json"), "w",
              encoding="utf-8") as f:
        json.dump(cfg, f)


def write_server_ip(ip):
    with open(os.path.join(DATA_DIR, "server.json"), "w",
              encoding="utf-8") as f:
        json.dump({"server_ip": ip}, f)


def login_client():
    pw = panel._ensure_admin_password()
    client = panel.app.test_client()
    r = client.post("/api/login", json={"password": pw})
    assert r.status_code == 200, "login failed: %s %s" % (r.status_code,
                                                         r.get_data(as_text=True)[:200])
    return client


def load_agent():
    spec = importlib.util.spec_from_file_location(
        "agent_under_test", os.path.join(TREE, "agent", "agent.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cell_a1():
    client = login_client()
    t0 = time.time()
    r = client.get("/api/status")
    dt = time.time() - t0
    body = r.get_json(silent=True) or {}
    print("R42FIXH A1 status no-stored-ip blackhole: http=%s secs=%.2f "
          "remote_ip=%r" % (r.status_code, dt,
                            (body.get("openvpn") or {}).get("remote_ip")),
          flush=True)
    check("A1 status fast with no stored IP (F3-2 fixed)",
          r.status_code == 200 and dt < FAST,
          "http=%s secs=%.2f" % (r.status_code, dt))
    t0 = time.time()
    r2 = client.get("/api/status")
    dt2 = time.time() - t0
    check("A1b second status call still fast (negative cache)",
          r2.status_code == 200 and dt2 < FAST,
          "http=%s secs=%.2f" % (r2.status_code, dt2))


def cell_a2():
    write_server_ip("203.0.113.9")
    client = login_client()
    t0 = time.time()
    r = client.get("/api/status")
    dt = time.time() - t0
    body = r.get_json(silent=True) or {}
    print("R42FIXH A2 status stored-ip blackhole: http=%s secs=%.2f "
          "remote_ip=%r" % (r.status_code, dt,
                            (body.get("openvpn") or {}).get("remote_ip")),
          flush=True)
    check("A2 status fast with stored server IP (control)",
          r.status_code == 200 and dt < FAST
          and (body.get("openvpn") or {}).get("remote_ip") == "203.0.113.9",
          "http=%s secs=%.2f" % (r.status_code, dt))


def cell_a3():
    client = login_client()
    t0 = time.time()
    r = client.get("/api/openvpn/users/alice/ovpn")
    dt = time.time() - t0
    print("R42FIXH A3 ovpn-download alice no-stored-ip: http=%s secs=%.2f "
          "len=%s" % (r.status_code, dt, len(r.get_data())), flush=True)
    check("A3 ovpn download fast with no stored IP (F3-2 fixed)",
          r.status_code == 200 and dt < FAST,
          "http=%s secs=%.2f" % (r.status_code, dt))
    write_server_ip("203.0.113.9")
    t0 = time.time()
    r = client.get("/api/openvpn/users/alice/ovpn")
    dt = time.time() - t0
    print("R42FIXH A3 ovpn-download alice stored-ip: http=%s secs=%.2f"
          % (r.status_code, dt), flush=True)
    check("A3 ovpn download fast with stored server IP (control)",
          r.status_code == 200 and dt < FAST,
          "http=%s secs=%.2f" % (r.status_code, dt))
    os.remove(os.path.join(DATA_DIR, "server.json"))
    t0 = time.time()
    r = client.post("/api/openvpn/users", json={"name": "r42fixha"})
    dt = time.time() - t0
    print("R42FIXH A3 create-user r42fixha no-stored-ip: http=%s secs=%.2f "
          "body=%s" % (r.status_code, dt,
                       (r.get_json(silent=True) or {}).get("error", "")),
          flush=True)
    check("A3 create-user returns fast (render timing needs-live: "
          "sandbox has no easy-rsa, create fails at signing)",
          dt < FAST, "http=%s secs=%.2f" % (r.status_code, dt))


def _agent_get_status(agent, tag):
    t0 = time.time()
    ok, result, error = agent.execute_command(
        {"id": "r42fixh-%s" % tag, "action": "get_status", "params": {}})
    dt = time.time() - t0
    print("R42FIXH %s agent get_status: ok=%s secs=%.2f egress_ip=%r "
          "sk5_egress_ip=%r error=%r"
          % (tag, ok, dt, (result or {}).get("egress_ip"),
             ((result or {}).get("sk5") or {}).get("egress_ip"), error),
          flush=True)
    return ok, result, dt


def cell_b1():
    agent = load_agent()
    ok, result, dt = _agent_get_status(agent, "B1")
    check("B1 agent get_status fast, SK5 disabled (F3-1 fixed)",
          ok and dt < FAST, "secs=%.2f" % dt)


def cell_b2():
    write_sk5(enabled=True)
    agent = load_agent()
    ok, result, dt = _agent_get_status(agent, "B2")
    check("B2 agent get_status fast, SK5 enabled+blackholed (F3-1 fixed)",
          ok and dt < FAST, "secs=%.2f" % dt)


def cell_b3():
    write_sk5(enabled=True)
    agent = load_agent()
    ok, result, dt = _agent_get_status(agent, "B3-first")
    check("B3 first dispatch fast (F3-1 fixed)", ok and dt < FAST,
          "secs=%.2f" % dt)
    ok, result, dt = _agent_get_status(agent, "B3-second")
    check("B3 second dispatch still fast (no repeated sync probe)",
          ok and dt < FAST, "secs=%.2f" % dt)


def cell_c1():
    write_sk5(enabled=True)
    client = login_client()
    t0 = time.time()
    r = client.post("/api/sk5", json={"enabled": False})
    dt = time.time() - t0
    print("R42FIXH C1 toggle-only save {enabled:false} blackholed SK5: "
          "http=%s secs=%.2f" % (r.status_code, dt), flush=True)
    check("C1 toggle-only save fast (F3-5 fixed)",
          r.status_code == 200 and dt < FAST,
          "http=%s secs=%.2f" % (r.status_code, dt))
    write_sk5(enabled=True)
    t0 = time.time()
    r = client.post("/api/sk5/disable")
    dt = time.time() - t0
    print("R42FIXH C1 POST /api/sk5/disable blackholed SK5: http=%s "
          "secs=%.2f" % (r.status_code, dt), flush=True)
    check("C1 sk5/disable fast (F3-5 fixed)",
          r.status_code == 200 and dt < FAST,
          "http=%s secs=%.2f" % (r.status_code, dt))


CELLS = {"A1": cell_a1, "A2": cell_a2, "A3": cell_a3,
         "B1": cell_b1, "B2": cell_b2, "B3": cell_b3, "C1": cell_c1}


def main():
    fn = CELLS.get(CELL)
    if fn is None:
        print("R42FIXH FATAL: unknown cell %r" % CELL, flush=True)
        return
    fn()
    bad = [n for n, ok in RESULTS if not ok]
    print("R42FIXH cell %s: %d/%d PASS%s"
          % (CELL, len(RESULTS) - len(bad), len(RESULTS),
             (" FAIL: " + ", ".join(bad)) if bad else ""), flush=True)


if __name__ == "__main__":
    main()

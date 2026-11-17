#!/usr/bin/env python3
"""Fix-B probe (AUDIT-R41): egress-probe budget.

Measures one endpoint (GET /api/status or GET /api/sk5) on a COLD cache
against the tree in $R41B_TREE, under a blackholed or fast ifconfig.me
(provided by the netns driver tests/r41_fix_b_driver.sh, which
bind-mounts /etc/hosts and runs tests/r41_fix_b_listen.py).

Acceptance (per cell): the cold call answers HTTP 200 in < 2 s, and
the second call (after the background refresh had time to finish)
carries the probed value on the fast path.

Run via the driver, not directly:
  R41B_TREE=<tree> python3 tests/r41_fix_b_probe.py \
      --mode blackhole|fast --sk5 disabled|enabled --endpoint status|sk5

Env (set by the driver): OVPN_PANEL_DATA_DIR, OVPN_PANEL_SECRET_PATH,
OPENVPN_CA_DIR, OPENVPN_SERVER_DIR, OVPN_SK5_CONFIG_DIR (fresh dirs),
PYTHONPATH -> a venv with Flask 3.1.3 + bcrypt. No proxy env: curl
must resolve ifconfig.me via the bind-mounted /etc/hosts.

Exit 0 always; the report (not the exit code) carries the verdict.
"""
import argparse
import json
import os
import sys
import time

TREE = os.environ["R41B_TREE"]
for _sub in ("panel", "core", "egress"):
    sys.path.insert(0, os.path.join(TREE, _sub))

import app as panel  # noqa: E402

RESULTS = []


def check(name, ok, evidence=""):
    RESULTS.append((name, bool(ok)))
    print("R41B %s: %s%s" % ("PASS" if ok else "FAIL", name,
                             (" | " + str(evidence)[:300]) if evidence else ""),
          flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["blackhole", "fast"])
    ap.add_argument("--sk5", required=True, choices=["disabled", "enabled"])
    ap.add_argument("--endpoint", required=True, choices=["status", "sk5"])
    args = ap.parse_args()

    if args.sk5 == "enabled":
        # Blackholed SK5 host: the via-SK5 probe must hang on the hold
        # listener (127.0.0.3:1080) exactly like the direct probe hangs
        # on 127.0.0.3:80. The driver only builds this cell in
        # blackhole mode.
        cfg = {"host": "127.0.0.3", "port": 1080, "username": "",
               "password": "", "enabled": True, "fail_open": False,
               "udp_over_tcp": False}
        sk5dir = os.environ["OVPN_SK5_CONFIG_DIR"]
        os.makedirs(sk5dir, exist_ok=True)
        with open(os.path.join(sk5dir, "sk5.json"), "w",
                  encoding="utf-8") as f:
            json.dump(cfg, f)

    pw = panel._ensure_admin_password()
    client = panel.app.test_client()
    r = client.post("/api/login", json={"password": pw})
    assert r.status_code == 200, "login failed: %s %s" % (r.status_code,
                                                         r.data[:200])
    url = "/api/status" if args.endpoint == "status" else "/api/sk5"

    t0 = time.time()
    r1 = client.get(url)
    dt1 = time.time() - t0
    body1 = r1.get_json(silent=True) or {}
    if args.endpoint == "status":
        eg1 = (body1.get("egress") or {}).get("ip")
    else:
        eg1 = (body1.get("sk5") or {}).get("egress_ip")
    print("R41B cold %s %s %s: http=%s secs=%.2f egress_ip=%r"
          % (args.mode, args.sk5, args.endpoint, r1.status_code, dt1, eg1),
          flush=True)
    check("cold %s %s %s answers 200 in <2s"
          % (args.mode, args.sk5, args.endpoint),
          r1.status_code == 200 and dt1 < 2.0,
          "http=%s secs=%.2f" % (r1.status_code, dt1))

    # Let the background refresh finish: the blackholed probe takes the
    # full 10 s curl budget; the fast probe answers in ~0.05 s.
    time.sleep(12 if args.mode == "blackhole" else 2)
    t0 = time.time()
    r2 = client.get(url)
    dt2 = time.time() - t0
    body2 = r2.get_json(silent=True) or {}
    if args.endpoint == "status":
        eg2 = (body2.get("egress") or {}).get("ip")
    else:
        eg2 = (body2.get("sk5") or {}).get("egress_ip")
    print("R41B warm %s %s %s: http=%s secs=%.2f egress_ip=%r"
          % (args.mode, args.sk5, args.endpoint, r2.status_code, dt2, eg2),
          flush=True)
    check("warm %s %s %s answers 200 in <2s"
          % (args.mode, args.sk5, args.endpoint),
          r2.status_code == 200 and dt2 < 2.0,
          "http=%s secs=%.2f" % (r2.status_code, dt2))
    if args.mode == "fast" and args.sk5 == "disabled" \
            and args.endpoint == "status":
        # The fast stub answers 203.0.113.7: the background refresh must
        # have landed the probed value by the second call.
        check("fast direct probe lands 203.0.113.7 by second poll",
              eg2 == "203.0.113.7", "egress_ip=%r" % eg2)

    bad = [n for n, ok in RESULTS if not ok]
    print("R41B %s %s %s: %d/%d PASS%s"
          % (args.mode, args.sk5, args.endpoint, len(RESULTS) - len(bad),
             len(RESULTS), (" FAIL: " + ",".join(bad)) if bad else ""),
          flush=True)


if __name__ == "__main__":
    main()

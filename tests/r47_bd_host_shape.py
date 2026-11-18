#!/usr/bin/env python3
"""R47-BD probe 3: SK5 host-shape validation (R47-L6-3 + R47-L3-5) --
fixed behavior. The host format must be validated at SAVE time on
every face: the local set_sk5 path, the agent action path, and the
Flask panel (local + remote branches). The Worker face is covered by
tests/r47_bd_worker_host.mjs.

  rejects: "not a host!!!", "exa mple.com", "proxy.iproyal.net:1080"
           (the host:port typo), "example.com:8080", "[::1]",
           "192.168.1.1:1080", "bad_host!"
  accepts: "proxy.iproyal.net", "127.0.0.1", "::1",
           "::ffff:192.0.2.1", "localhost", "example.com."

The Flask section runs the panel in fresh subprocesses with fresh
data dirs (same helper shape as the R47-L3 probe); the helper never
prints a password. Run with the venv python:
  /tmp/r47bd-venv/bin/python tests/r47_bd_host_shape.py
Exit 0 iff every face validates the shape.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "egress"))
sys.path.insert(0, str(ROOT / "agent"))
import sk5_manager as m  # noqa: E402
import agent as agent_mod  # noqa: E402

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


REJECT = ["not a host!!!", "exa mple.com", "proxy.iproyal.net:1080",
          "example.com:8080", "[::1]", "192.168.1.1:1080", "bad_host!"]
ACCEPT = ["proxy.iproyal.net", "127.0.0.1", "::1", "::ffff:192.0.2.1",
          "localhost", "example.com."]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="r47bd-host-"))
    m.CONFIG_DIR = tmp
    m.CONFIG_FILE = tmp / "sk5.json"
    m.RENDERED_CONFIG = tmp / "sing-box.json"
    m.PID_FILE = tmp / "sing-box.pid"
    m.LOG_FILE = tmp / "sing-box.log"
    m.HEALTH_FILE = tmp / "health.json"

    # --- local set_sk5 ---
    for host in REJECT:
        try:
            m.set_sk5(host=host, port=1080, enabled=False)
            bad("L local set_sk5 STORED %r" % host)
        except ValueError as exc:
            ok("L local set_sk5 rejects %r: %s" % (host, str(exc)[:50]))
        except RuntimeError as exc:
            bad("L local set_sk5 %r raised RuntimeError not ValueError: %s"
                % (host, str(exc)[:50]))
    for host in ACCEPT:
        try:
            m.set_sk5(host=host, port=1080, enabled=False)
            ok("L local set_sk5 accepts %r" % host)
        except (ValueError, RuntimeError) as exc:
            bad("L local set_sk5 rejected valid host %r: %s" % (host, exc))

    # --- agent action_set_sk5 ---
    for host in REJECT:
        try:
            agent_mod.action_set_sk5({"host": host, "port": 1080})
            bad("A agent action_set_sk5 ACCEPTED %r" % host)
        except ValueError as exc:
            ok("A agent action_set_sk5 rejects %r: %s" % (host, str(exc)[:50]))
    for host in ACCEPT:
        try:
            agent_mod.action_set_sk5({"host": host, "port": 1080})
            ok("A agent action_set_sk5 accepts %r" % host)
        except ValueError as exc:
            bad("A agent action_set_sk5 rejected valid host %r: %s" % (host, exc))

    # --- Flask panel (fresh subprocess, fresh data dir) ---
    for host, want in [("exa mple.com", 400),
                       ("proxy.iproyal.net:1080", 400),
                       ("not a host!!!", 400),
                       ("proxy.example.com", 200),
                       ("::1", 200),
                       ("127.0.0.1", 200)]:
        r = run_flask_sk5save(host)
        if "helper_error" in r:
            bad("F Flask sk5save %r: helper error %s" % (host, r["helper_error"]))
        elif r.get("status") == want:
            ok("F Flask sk5save %r -> %d" % (host, want))
        else:
            bad("F Flask sk5save %r -> %s (expected %d) body=%s"
                % (host, r.get("status"), want, str(r.get("body"))[:120]))

    print("result: PASS=%d FAIL=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


HELPER = r'''
import io, json, os, sys, contextlib
sys.path.insert(0, os.path.join(os.environ["R47BD_TREE"], "panel"))
sys.path.insert(0, os.path.join(os.environ["R47BD_TREE"], "core"))
sys.path.insert(0, os.path.join(os.environ["R47BD_TREE"], "egress"))
import app as panel_app

host = sys.argv[1]
with contextlib.redirect_stdout(io.StringIO()):
    panel_app._ensure_admin_password()
pw_path = os.environ["OVPN_PANEL_ADMIN_PASS_PATH"]
with open(pw_path, "r", encoding="utf-8") as f:
    admin_pw = f.read().strip()
client = panel_app.app.test_client()
assert client.post("/api/login", json={"password": admin_pw}).status_code == 200
r = client.post("/api/sk5", json={"host": host, "port": 1001,
                                  "username": "u", "password": "p",
                                  "enabled": False})
print(json.dumps({"status": r.status_code, "body": r.get_json(silent=True)}))
'''


def run_flask_sk5save(host):
    data = tempfile.mkdtemp(prefix="r47bd-data-")
    sk5cfg = tempfile.mkdtemp(prefix="r47bd-sk5-")
    env = dict(os.environ)
    env["R47BD_TREE"] = str(ROOT)
    env["OVPN_PANEL_DATA_DIR"] = data
    env["OVPN_PANEL_SECRET_PATH"] = os.path.join(data, "secret.key")
    env["OVPN_PANEL_ADMIN_PASS_PATH"] = os.path.join(data, "admin.pass")
    env["OPENVPN_CA_DIR"] = os.environ.get("OPENVPN_CA_DIR", "/tmp/r17/fixture-ca")
    env["OPENVPN_SERVER_DIR"] = os.environ.get("OPENVPN_SERVER_DIR", "/tmp/r17/fixture-server")
    env["OVPN_SK5_CONFIG_DIR"] = sk5cfg
    proc = subprocess.run(
        [sys.executable, "-c", HELPER, host],
        capture_output=True, text=True, env=env, timeout=120)
    if proc.returncode != 0:
        return {"helper_error": proc.stderr[-500:]}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"helper_error": "no JSON output: " + proc.stdout[-300:] + proc.stderr[-300:]}


if __name__ == "__main__":
    raise SystemExit(main())

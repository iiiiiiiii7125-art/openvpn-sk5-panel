#!/usr/bin/env python3
"""R47 integration probe: 15-action whitelist, 3-way equality (D04 fallout).

Fix-BC added renew_server_cert + repair_pki as agent actions and gave the
panel renew/repair endpoints that enqueue them for remote nodes -- but
Flask AGENT_ACTIONS and Worker ACTIONS stayed at 13, so remote enqueue
400'd ("illegal action") and Worker mode had no compat routes at all.
This probe asserts the FIXED behavior (BH-03(c)): it FAILS on the
pre-fix merged tree (Flask /api/cmd 400s the two actions) and PASSES
once all three faces carry 15 identical actions.

Flask section runs the panel in a fresh subprocess with a fresh data
dir (same harness as tests/r47_bd_host_shape.py). Run as nobody with:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \
    R47INT_TREE=<tree> OVPN_PANEL_DATA_DIR=<fresh data> \
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \
    OVPN_PANEL_ADMIN_PASS_PATH=<data>/admin.pass \
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \
    OVPN_SK5_CONFIG_DIR=<fresh sk5cfg> \
    python3 <tree>/tests/r47_int_action_whitelist.py
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.environ.get("R47INT_TREE", ROOT)
PASS = 0
FAIL = 0


def ok(name, detail=""):
    global PASS
    PASS += 1
    print("PASS %s%s" % (name, (" | " + str(detail)[:200]) if detail else ""))


def bad(name, detail=""):
    global FAIL
    FAIL += 1
    print("FAIL %s%s" % (name, (" | " + str(detail)[:200]) if detail else ""))


def read(p):
    with open(os.path.join(TREE, p), encoding="utf-8") as f:
        return f.read()


def main():
    # W0: 3-way textual equality (same extraction as D04).
    flask = set(re.findall(r'"([a-z0-9_]+)"', re.search(
        r"AGENT_ACTIONS = frozenset\(\{(.*?)\}\)", read("panel/app.py"),
        re.S).group(1)))
    agent = set(re.findall(r'"([a-z0-9_]+)":', re.search(
        r"^ACTIONS = \{(.*?)\n\}", read("agent/agent.py"), re.S | re.M).group(1)))
    worker = set(re.findall(r'"([a-z0-9_]+)"', re.search(
        r"const ACTIONS = new Set\(\[(.*?)\]\);", read("cloudflare/src/index.js"),
        re.S).group(1)))
    if len(flask) == 15 and flask == agent == worker:
        ok("W0 15 actions, identical on 3 faces")
    else:
        bad("W0 15 actions, identical on 3 faces",
            "flask=%d agent=%d worker=%d diff=%s" % (
                len(flask), len(agent), len(worker),
                sorted((flask ^ agent) | (agent ^ worker) | (flask ^ worker))))
    if "renew_server_cert" in flask and "repair_pki" in flask:
        ok("W0b new actions present on all faces")
    else:
        bad("W0b new actions present on all faces")

    # W1-W6: live Flask enqueue behaviour via a helper subprocess.
    r = run_flask()
    if "helper_error" in r:
        bad("W1-W6 Flask helper", r["helper_error"])
    else:
        for name, want, got in r:
            if got == want:
                ok(name, "-> %s" % got)
            else:
                bad(name, "-> %s (expected %s)" % (got, want))
    print("result: PASS=%d FAIL=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


HELPER = r'''
import io, json, os, sys, contextlib
sys.path.insert(0, os.path.join(os.environ["R47INT_TREE"], "panel"))
sys.path.insert(0, os.path.join(os.environ["R47INT_TREE"], "core"))
sys.path.insert(0, os.path.join(os.environ["R47INT_TREE"], "egress"))
import app as panel_app

with contextlib.redirect_stdout(io.StringIO()):
    panel_app._ensure_admin_password()
with open(os.environ["OVPN_PANEL_ADMIN_PASS_PATH"], "r", encoding="utf-8") as f:
    admin_pw = f.read().strip()
client = panel_app.app.test_client()
assert client.post("/api/login", json={"password": admin_pw}).status_code == 200
out = []
reg = client.post("/api/nodes", json={"name": "lightsail", "panel_url": ""})
out.append(("W1 register node lightsail 201", 201, reg.status_code))
node_token = (reg.get_json(silent=True) or {}).get("token", "")
for action in ("renew_server_cert", "repair_pki"):
    r = client.post("/api/cmd", json={"node": "lightsail", "action": action, "params": {}})
    out.append(("W2 /api/cmd %s -> 202" % action, 202, r.status_code))
r = client.post("/api/cmd", json={"node": "lightsail", "action": "bogus_action", "params": {}})
out.append(("W3 /api/cmd bogus_action -> 400", 400, r.status_code))
r = client.post("/api/openvpn/renew-server-cert?node=lightsail", json={})
out.append(("W4 compat renew-server-cert ?node=lightsail -> 202", 202, r.status_code))
renew_id = (r.get_json(silent=True) or {}).get("cmd_id", "")
r = client.post("/api/openvpn/pki/repair?node=lightsail", json={})
out.append(("W5 compat pki/repair ?node=lightsail -> 202", 202, r.status_code))
# W6: the agent's report for the remote renew must LAND as done. Pre-fix
# the report path treated renew_server_cert as a malformed entry
# (action not in AGENT_ACTIONS -> "队列条目损坏", status failed) even
# though the agent had executed it -- a false failure for a success.
pol = client.post("/api/agent/poll", json={},
                 headers={"Authorization": "Bearer %s" % node_token})
rep = client.post("/api/agent/report",
                  json={"cmd_id": renew_id, "ok": True,
                        "result": {"renewed": True, "server_cert": {}}},
                  headers={"Authorization": "Bearer %s" % node_token})
rep_j = rep.get_json(silent=True) or {}
out.append(("W6 report for remote renew_server_cert lands done", "done",
            rep_j.get("status", "http-%d:%s" % (rep.status_code, str(rep_j)[:80]))))
print(json.dumps(out))
'''


def run_flask():
    data = tempfile.mkdtemp(prefix="r47int-data-")
    sk5cfg = tempfile.mkdtemp(prefix="r47int-sk5-")
    env = dict(os.environ)
    env["R47INT_TREE"] = TREE
    env["OVPN_PANEL_DATA_DIR"] = data
    env["OVPN_PANEL_SECRET_PATH"] = os.path.join(data, "secret.key")
    env["OVPN_PANEL_ADMIN_PASS_PATH"] = os.path.join(data, "admin.pass")
    env["OPENVPN_CA_DIR"] = os.environ.get("OPENVPN_CA_DIR", "/tmp/r17/fixture-ca")
    env["OPENVPN_SERVER_DIR"] = os.environ.get("OPENVPN_SERVER_DIR", "/tmp/r17/fixture-server")
    env["OVPN_SK5_CONFIG_DIR"] = sk5cfg
    proc = subprocess.run(
        [sys.executable, "-c", HELPER],
        capture_output=True, text=True, env=env, timeout=120)
    if proc.returncode != 0:
        return {"helper_error": proc.stderr[-600:]}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"helper_error": "no JSON output: " + proc.stdout[-300:] + proc.stderr[-300:]}


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""R45-L7 Flask-face probe (test_client, in-process, run as nobody).

Control half of the Worker server_ip / remote_ip divergence:
 - F1: Flask remote create_server ALSO drops server_ip from the queued
   params (by design, panel/app.py:1749) -- the drop itself is shared.
 - F2: Flask remote /api/status DOES surface ovpn.remote_ip +
   remote_warning from the snapshot egress_ip (panel/app.py:934) --
   the Worker does not (r45_l7_worker.mjs W06/W07). The divergence is
   Worker-side, not Flask-side.
 - F3: 13-action whitelist on the Flask face.
 - F4: the three faces' action sets are identical (Flask AGENT_ACTIONS
   vs agent ACTIONS vs the Worker list asserted in r45_l7_worker.mjs).

Run as nobody with:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    R45L7_TREE=<tree> OVPN_PANEL_DATA_DIR=<fresh-data> \\
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \\
    OVPN_SK5_CONFIG_DIR=<fresh-sk5cfg> \\
    python3 <tree>/tests/r45_l7_flask.py
"""
import json
import os
import sys

TREE = os.environ.get("R45L7_TREE", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.environ["OVPN_PANEL_DATA_DIR"]
sys.path.insert(0, os.path.join(TREE, "panel"))
sys.path.insert(0, os.path.join(TREE, "core"))
sys.path.insert(0, os.path.join(TREE, "egress"))
sys.path.insert(0, os.path.join(TREE, "agent"))

import app as panel  # noqa: E402
import agent as agent_mod  # noqa: E402

RESULTS = []


def cell(name, ok, evidence=""):
    RESULTS.append((name, bool(ok)))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" | " + str(evidence)[:240]) if evidence else ""),
          flush=True)


def main():
    pw = panel._ensure_admin_password()
    if not pw:
        pw = open(os.path.join(DATA, "admin.pass")).read().strip()
    client = panel.app.test_client()
    r = client.post("/api/login", json={"password": pw})
    cell("F00 login ok", r.status_code == 200, r.status_code)

    r = client.post("/api/nodes", json={"name": "n1", "panel_url": "https://127.0.0.1:18443"})
    cell("F01 register n1 -> 201", r.status_code == 201, r.status_code)
    token = r.get_json()["token"]

    # F1: remote create_server with server_ip -- params drop by design.
    r = client.post("/api/openvpn/server", json={
        "node": "n1", "port": 1194, "proto": "udp",
        "server_ip": "vpn.example.com"})
    cell("F02 remote create_server -> 202", r.status_code == 202, r.status_code)
    cmd_id = r.get_json()["cmd_id"]
    r = client.get("/api/cmd/%s" % cmd_id)
    params = r.get_json().get("params", {})
    cell("F03 Flask also drops server_ip from queued params (by design)",
         "server_ip" not in params, json.dumps(params))

    # F2: agent takes the cmd, reports get_status with an egress IP.
    ac = panel.app.test_client()
    r = ac.post("/api/agent/poll", json={"node_token": token, "node_name": "n1"})
    cmds = r.get_json().get("commands", [])
    cell("F04 poll takes the create_server cmd",
         len(cmds) == 1 and cmds[0]["id"] == cmd_id, len(cmds))
    r = ac.post("/api/agent/report", json={
        "node_token": token, "cmd_id": cmd_id, "ok": True, "result": {}})
    cell("F05 create_server report -> done", r.status_code == 200, r.status_code)
    r = client.post("/api/cmd", json={"node": "n1", "action": "get_status", "params": {}})
    gs_id = r.get_json()["cmd_id"]
    r = ac.post("/api/agent/poll", json={"node_token": token, "node_name": "n1"})
    r = ac.post("/api/agent/report", json={
        "node_token": token, "cmd_id": gs_id, "ok": True,
        "result": {
            "openvpn": {"running": True, "unit_active": True, "pid": 123,
                        "clients": [], "online_users": 0, "error": None},
            "egress_ip": "203.0.113.7",
            "sk5": {"enabled": False},
            "users": [],
        }})
    cell("F06 get_status report -> done", r.status_code == 200, r.status_code)
    r = client.get("/api/status", query_string={"node": "n1"})
    ovpn = r.get_json().get("openvpn", {})
    cell("F07 Flask remote status HAS ovpn.remote_ip",
         ovpn.get("remote_ip") == "203.0.113.7", ovpn.get("remote_ip"))
    cell("F08 Flask remote status HAS ovpn.remote_warning key",
         "remote_warning" in ovpn, ovpn.get("remote_warning"))

    # F3: whitelist via /api/cmd.
    actions13 = ["install_prereqs", "init_pki", "create_server",
                 "start_openvpn", "stop_openvpn", "restart_openvpn",
                 "create_user", "revoke_user", "set_sk5", "test_sk5",
                 "enable_sk5", "disable_sk5", "get_status"]
    ok13 = 0
    for a in actions13:
        r = client.post("/api/cmd", json={"node": "n1", "action": a, "params": {}})
        if r.status_code == 202:
            ok13 += 1
        else:
            print("  action %s -> %s" % (a, r.status_code))
    cell("F09 all 13 actions -> 202", ok13 == 13, "%d/13" % ok13)
    for bad in ("start", "stop", "exec", "shell"):
        r = client.post("/api/cmd", json={"node": "n1", "action": bad, "params": {}})
        cell('F10 invalid action "%s" -> 400' % bad, r.status_code == 400, r.status_code)

    # F4: three faces' action sets identical.
    flask_set = set(panel.AGENT_ACTIONS)
    agent_set = set(agent_mod.ACTIONS)
    cell("F11 Flask AGENT_ACTIONS == agent ACTIONS",
         flask_set == agent_set, sorted(flask_set ^ agent_set))
    cell("F12 both sets == the 13 asserted on the Worker",
         flask_set == set(actions13) and agent_set == set(actions13),
         "%d/%d" % (len(flask_set), len(agent_set)))

    fails = [n for n, ok in RESULTS if not ok]
    print("TOTAL %d cells, FAIL %d: %s" % (len(RESULTS), len(fails), fails))
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())

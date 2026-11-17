#!/usr/bin/env python3
"""R42-F4 age-semantics probe — Flask half (r42_f4_age.mjs is the Worker half).

Flask stamps snapshot `at` ONLY on get_status results (R11-P1-1:
heartbeat never stamps at); a poll-only node has age None / stale True
with the note prompting a get_status run. Run as nobody with:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \
    OVPN_PANEL_DATA_DIR=<data> OVPN_PANEL_SECRET_PATH=<data>/secret.key \
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \
    OVPN_SK5_CONFIG_DIR=<sk5cfg> \
    python3 <tree>/tests/r42_f4_age_flask.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "panel"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "egress"))

import app as panel  # noqa: E402

FAILURES = []
CHECKS = [0]


def check(name, ok, evidence=""):
    CHECKS[0] += 1
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" | " + str(evidence)[:300]) if evidence else ""),
          flush=True)
    if not ok:
        FAILURES.append(name)


DATA = os.environ["OVPN_PANEL_DATA_DIR"]

pw = panel._ensure_admin_password()
if pw is None:
    pw = open(os.path.join(DATA, "admin.pass")).read().strip()
client = panel.app.test_client()
r = client.post("/api/login", json={"password": pw})
check("B00 login works", r.status_code == 200, r.status_code)

r = client.post("/api/nodes", json={"name": "node1",
                                    "panel_url": "https://panel.example:8443"})
check("B01 register node", r.status_code == 201, r.status_code)
token = r.get_json().get("token")
check("B01b token disclosed once", bool(token))

HB = {"version": "1.0", "hostname": "h1",
      "openvpn_running": True, "sk5_enabled": False}


def poll():
    return client.post("/api/agent/poll", json={
        "node_name": "node1", "panel_url": "https://panel.example:8443",
        "status": HB},
        headers={"Authorization": "Bearer " + token})


def status():
    return client.get("/api/status?node=node1").get_json()


# B1: poll-only node — heartbeat values land, but age is None / stale True.
r = poll()
check("B1 poll with heartbeat 200", r.status_code == 200, r.status_code)
st = status()
check("B1 poll-only node shows heartbeat values",
      st.get("openvpn", {}).get("running") is True
      and st.get("sk5", {}).get("enabled") is False, st)
check("B1 Flask half: poll-only node age_s is None, stale True",
      st.get("age_s") is None and st.get("stale") is True, st)
check("B1b note only pre-first-poll (snap exists after heartbeat, so no note)",
      st.get("note") is None, st.get("note"))

# B2: wait, then a create_user report (no status sections) must NOT touch at.
time.sleep(1.2)
st = status()
check("B2 after 1.2s idle, age still None / stale True",
      st.get("age_s") is None and st.get("stale") is True, st)
r = client.post("/api/cmd", json={"node": "node1", "action": "create_user",
                                  "params": {"name": "u1"}})
cmd1 = r.get_json().get("cmd_id")
check("B2 enqueue create_user 202", r.status_code == 202 and bool(cmd1),
      r.status_code)
r = poll()
cmds = r.get_json().get("commands", [])
check("B2 poll dispatches create_user",
      len(cmds) == 1 and cmds[0]["id"] == cmd1, cmds)
time.sleep(1.1)
r = client.post("/api/agent/report", json={
    "node_name": "node1", "panel_url": "https://panel.example:8443",
    "id": cmd1, "ok": True,
    "result": {"ovpn": "-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----"}},
    headers={"Authorization": "Bearer " + token})
check("B2 report create_user 200 done",
      r.status_code == 200 and r.get_json().get("status") == "done",
      r.status_code)
st = status()
check("B2 Flask half: non-status report does NOT refresh at (age still None)",
      st.get("age_s") is None and st.get("stale") is True, st)

# B3 control: a real get_status report stamps at and carries full sections.
r = client.post("/api/cmd", json={"node": "node1", "action": "get_status",
                                  "params": {}})
cmd2 = r.get_json().get("cmd_id")
r = poll()
r = client.post("/api/agent/report", json={
    "node_name": "node1", "panel_url": "https://panel.example:8443",
    "id": cmd2, "ok": True,
    "result": {"openvpn": {"running": True, "clients": [], "unit_active": True,
                           "pid": 123, "error": None},
               "egress_ip": "203.0.113.9", "sk5": {"enabled": False},
               "users": [], "health": {}}},
    headers={"Authorization": "Bearer " + token})
check("B3 report get_status 200 done",
      r.status_code == 200 and r.get_json().get("status") == "done",
      r.status_code)
st = status()
check("B3 control: get_status report gives age_s small + stale False + full sections",
      isinstance(st.get("age_s"), int) and st["age_s"] <= 5
      and st.get("stale") is False
      and st.get("egress", {}).get("ip") == "203.0.113.9", st)

# B4: an enable_sk5 report (flat sk5-manager result, the shape enable()
# really returns) must NOT touch the snapshot on Flask — age stays small
# only because of the B3 get_status, egress stays the get_status value.
r = client.post("/api/nodes", json={"name": "node2",
                                    "panel_url": "https://panel.example:8443"})
token2 = r.get_json().get("token")
check("B4 register node2", r.status_code == 201 and bool(token2),
      r.status_code)


def poll2():
    return client.post("/api/agent/poll", json={
        "node_name": "node2", "panel_url": "https://panel.example:8443",
        "status": HB},
        headers={"Authorization": "Bearer " + token2})


def status2():
    return client.get("/api/status?node=node2").get_json()


r = poll2()
check("B4 poll node2 heartbeat 200", r.status_code == 200, r.status_code)
st = status2()
check("B4 node2 poll-only: age None / stale True",
      st.get("age_s") is None and st.get("stale") is True, st)
r = client.post("/api/cmd", json={"node": "node2", "action": "enable_sk5",
                                  "params": {}})
cmd4 = r.get_json().get("cmd_id")
r = poll2()
r = client.post("/api/agent/report", json={
    "node_name": "node2", "panel_url": "https://panel.example:8443",
    "id": cmd4, "ok": True,
    "result": {"enabled": True, "policy_routing_active": True,
               "egress_ip": "203.0.113.55", "singbox_running": True,
               "vpn_net": "10.8.0.0/24", "config_error": None,
               "singbox_config": "/etc/openvpn-sk5-panel/sing-box.json",
               "policy_script": "/etc/openvpn-sk5-panel/policy-routing.sh",
               "last_health": None}},
    headers={"Authorization": "Bearer " + token2})
check("B4 report enable_sk5 200 done",
      r.status_code == 200 and r.get_json().get("status") == "done",
      r.status_code)
st = status2()
check("B4 Flask half: enable report touches neither at nor egress "
      "(age still None, egress ip still None)",
      st.get("age_s") is None and st.get("stale") is True
      and st.get("egress", {}).get("ip") is None, st)

print("\nTOTAL: PASS=%d FAIL=%d" % (
    CHECKS[0] - len(FAILURES), len(FAILURES)))
if FAILURES:
    print("FAILED: %s" % FAILURES)
sys.exit(1 if FAILURES else 0)

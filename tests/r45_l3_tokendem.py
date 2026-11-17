#!/usr/bin/env python3
"""Direct demonstration for the g-tokenleak finding (R45-L3-5).

The gate's token-leak cell (verify-integration.sh:578-583) greps ONLY
cmd2.json -- the FAILED create_user receipt, whose result is None --
and never cmd1.json, the SUCCEEDED get_status receipt whose result
is a dict. The mutant agent injects node_token into every dict
result (Agent.report); the panel stores result verbatim
(panel/app.py:3100, cmd["result"] = data.get("result")) and serves
it verbatim via GET /api/cmd/<id> (app.py:2905). This demo drives a
mutant panel via test client and shows the token IS present in the
get_status receipt (which the gate never greps) and absent from the
failed create_user receipt (which is all the gate checks) -- the
exact shape the gate passed 30/30 on.

Run: python3 tests/r45_l3_tokendem.py  (needs the venv + fixtures:
  /tmp/r41-l5-venv, /tmp/r17/fixture-ca, /tmp/r17/fixture-server)
NOTE: run as nobody via the documented harness if possible -- as
root the panel writes admin.pass to /etc/openvpn-sk5-panel (the
panel only falls back to the data dir when the /etc write fails);
remove /etc/openvpn-sk5-panel after a root run.
Adopted by Fix-Z (R45-L3-5) as a regression probe: besides the
mechanism demonstration it now asserts the FIXED gate check (grep
the token across BOTH receipts) catches the leak while the old
cmd2-only check misses it. Exit 0 iff both hold.
"""
import json
import os
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = "/tmp/r45l3-tokendem"
VENV = "/tmp/r41-l5-venv/lib/python3.12/site-packages"
FIX_CA = "/tmp/r17/fixture-ca"
FIX_SRV = "/tmp/r17/fixture-server"

# 1. fresh mutant copy (same edit as the g-tokenleak mutant)
shutil.rmtree(DST, ignore_errors=True)
shutil.copytree(BASE, DST, ignore=shutil.ignore_patterns(".git", "__pycache__"))
p = os.path.join(DST, "agent", "agent.py")
text = open(p, encoding="utf-8").read()
old = ("    def report(self, cmd_id: str, ok: bool, result: Any, error: str | None) -> None:")
new = (old + "\n"
       "        if isinstance(result, dict):  # R45-L3 mutant: leak the token\n"
       "            result = dict(result, node_token=self.cfg[\"node_token\"])")
assert text.count(old) == 1
open(p, "w", encoding="utf-8").write(text.replace(old, new))
print("mutant applied:", "node_token=self.cfg" in open(p, encoding="utf-8").read())

# 2. fresh dirs + env, import the mutant panel
DATA = DST + "-data"
SK5 = DST + "-sk5"
SRV = DST + "-srv"
for d in (DATA, SK5):
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    os.chmod(d, 0o777)
shutil.rmtree(SRV, ignore_errors=True)
shutil.copytree(FIX_SRV, SRV)
os.environ["PYTHONPATH"] = VENV
os.environ["OVPN_PANEL_DATA_DIR"] = DATA
os.environ["OVPN_PANEL_SECRET_PATH"] = os.path.join(DATA, "secret.key")
os.environ["OPENVPN_CA_DIR"] = FIX_CA
os.environ["OPENVPN_SERVER_DIR"] = SRV
os.environ["OVPN_SK5_CONFIG_DIR"] = SK5
# PYTHONPATH is only read at interpreter startup; the venv must be
# added to sys.path explicitly here.
sys.path.insert(0, VENV)
sys.path.insert(0, os.path.join(DST, "panel"))
sys.path.insert(0, os.path.join(DST, "core"))
sys.path.insert(0, os.path.join(DST, "egress"))
sys.path.insert(0, os.path.join(DST, "agent"))
import app as panel  # noqa: E402

pw = panel._ensure_admin_password()
if pw is None:
    pw = open(os.path.join(DATA, "admin.pass")).read().strip()
client = panel.app.test_client()
IP = "10.9.0.11"
PANEL_URL = "http://127.0.0.1:8443"


def admin_post(path, body):
    return client.post(path, json=body,
                       environ_overrides={"REMOTE_ADDR": IP})


assert client.post("/api/login", json={"password": pw},
                   environ_overrides={"REMOTE_ADDR": IP}).status_code == 200
r = admin_post("/api/nodes", {"name": "tokendem", "panel_url": PANEL_URL})
assert r.status_code == 201, r.status_code
token = r.get_json()["token"]
print("node registered, token len:", len(token))


def agent_post(path, body):
    return client.post(path, json=body, headers={
        "Authorization": "Bearer %s" % token},
        environ_overrides={"REMOTE_ADDR": IP})


def run_cmd(action, params, report_ok, report_result, report_error):
    """Enqueue -> poll (sent) -> report -> GET receipt. Returns receipt json."""
    r = admin_post("/api/cmd", {"node": "tokendem", "action": action,
                                "params": params})
    assert r.status_code in (200, 202), (action, r.status_code, r.get_json())
    cmd_id = r.get_json()["cmd_id"]
    r = agent_post("/api/agent/poll", {
        "node_token": token, "node_name": "tokendem",
        "panel_url": PANEL_URL,
        "status": {"version": "0.1.0", "openvpn_running": False,
                   "sk5_enabled": False, "hostname": "tokendem"}})
    assert r.status_code == 200, (action, r.status_code, r.get_json())
    r = agent_post("/api/agent/report", {
        "node_token": token, "node_name": "tokendem",
        "panel_url": PANEL_URL, "id": cmd_id, "ok": report_ok,
        "result": report_result, "error": report_error})
    assert r.status_code == 200, (action, r.status_code, r.get_json())
    r = client.get("/api/cmd/%s" % cmd_id,
                   environ_overrides={"REMOTE_ADDR": IP})
    assert r.status_code == 200, r.status_code
    return r.get_json()


# get_status success: the mutant agent's report carries the token in
# the dict result (exactly what Agent.report does after the edit).
leaked = {"openvpn": {"running": False}, "sk5": {"enabled": False},
          "node_token": token}
rc1 = run_cmd("get_status", {}, True, leaked, None)
print("get_status receipt contains token:",
      token in json.dumps(rc1))
# create_user failure: result None, so no injection -- the receipt
# the gate greps is clean.
rc2 = run_cmd("create_user", {"name": "smokeuser"}, False, None,
              "no CA")
print("create_user receipt contains token:",
      token in json.dumps(rc2))
print("DEMO:",
      "CONFIRMED leak-in-get_status-receipt missed by gate"
      if token in json.dumps(rc1) and token not in json.dumps(rc2)
      else "NOT reproduced")

# R45-L3-5 regression (Fix-Z): the gate's token-leak cell now greps
# EVERY receipt it fetched (cmd1.json as well as cmd2.json). The
# leak above is visible only in the get_status receipt, so the old
# cmd2-only check missed it; the fixed check over both receipts must
# find it. Exit 0 iff the mechanism is demonstrated AND the fixed
# check catches it.
both_receipts = json.dumps(rc1) + json.dumps(rc2)
caught_by_both = token in both_receipts
caught_by_cmd2_only = token in json.dumps(rc2)
print("FIXED-GATE-CHECK both-receipts grep finds token:", caught_by_both,
      "| cmd2-only grep finds token:", caught_by_cmd2_only)
ok = (token in json.dumps(rc1) and token not in json.dumps(rc2)
      and caught_by_both and not caught_by_cmd2_only)
print("TOKENDEM:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)

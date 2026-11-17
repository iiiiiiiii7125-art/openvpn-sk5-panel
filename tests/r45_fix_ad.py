#!/usr/bin/env python3
"""R45-LIVE-2 agent-delivery probe -- Flask half (r45_fix_ad_worker.mjs
is the Worker half, r45_fix_ad_install.sh is the installer half).

Finding: the R45-L6-3 fix never reached the RUNNING agent -- the panel
bundle already carried the fixed policy-routing.sh, but nothing told
the operator the deployed agent was stale, and the panel's own install
command could not update it (no --force). Fix: install-agent.sh
records the verified bundle hash, the agent reports it in its poll
heartbeat, and the panel flags agent_code_outdated in /api/nodes and
/api/status (True = stale, False = current, None = unknown, never a
lie). Run as nobody with:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \
    OVPN_PANEL_DATA_DIR=<data> OVPN_PANEL_SECRET_PATH=<data>/secret.key \
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \
    OVPN_SK5_CONFIG_DIR=<sk5cfg> \
    python3 <tree>/tests/r45_fix_ad.py
"""
import io
import json
import os
import sys
import tarfile

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

OLD_HASH = "0" * 64
PANEL_URL = "https://panel.example:8443"


def register(name):
    rr = client.post("/api/nodes", json={"name": name, "panel_url": PANEL_URL})
    return rr


def poll(name, token, status):
    return client.post("/api/agent/poll", json={
        "node_name": name, "panel_url": PANEL_URL, "status": status},
        headers={"Authorization": "Bearer " + token})


def nodes():
    return client.get("/api/nodes").get_json().get("nodes", [])


def node_entry(name):
    for n in nodes():
        if n.get("name") == name:
            return n
    return {}


# B02: the panel's current bundle hash (public endpoint, same hash the
# installer verifies against).
r = client.get("/api/agent/bundle.sha256")
cur = r.get_data(as_text=True).split()[0] if r.status_code == 200 else ""
check("B02 current bundle hash is 64-hex", len(cur) == 64
      and all(c in "0123456789abcdef" for c in cur), cur)

r = register("ad1")
check("B01 register ad1", r.status_code == 201, r.status_code)
token1 = r.get_json().get("token")

HB = {"version": "1.0", "hostname": "h1",
      "openvpn_running": True, "sk5_enabled": False}

# A1: agent reports an OLD bundle hash -> outdated True.
r = poll("ad1", token1, dict(HB, bundle_sha256=OLD_HASH))
check("A1 poll with old hash 200", r.status_code == 200, r.status_code)
e = node_entry("ad1")
check("A1 /api/nodes reports installed old hash",
      e.get("agent_bundle_sha256") == OLD_HASH, e)
check("A1 /api/nodes agent_code_outdated is True",
      e.get("agent_code_outdated") is True, e)

# A4 (status face): same verdict in /api/status.
st = client.get("/api/status?node=ad1").get_json()
check("A4 /api/status outdated True for old hash",
      st.get("agent_code_outdated") is True
      and st.get("agent_bundle_sha256") == OLD_HASH, st)

# A2: agent reports the CURRENT hash -> outdated False.
r = poll("ad1", token1, dict(HB, bundle_sha256=cur))
check("A2 poll with current hash 200", r.status_code == 200, r.status_code)
e = node_entry("ad1")
check("A2 /api/nodes agent_code_outdated is False",
      e.get("agent_code_outdated") is False
      and e.get("agent_bundle_sha256") == cur, e)
st = client.get("/api/status?node=ad1").get_json()
check("A4b /api/status outdated False for current hash",
      st.get("agent_code_outdated") is False, st)

# A3: a fresh node whose agent never reports a hash -> unknown, not
# a lie in either direction (merge-write keeps old keys, so this needs
# a fresh node, not a hash-less poll on ad1).
r = register("ad2")
check("A3 register ad2", r.status_code == 201, r.status_code)
token2 = r.get_json().get("token")
r = poll("ad2", token2, dict(HB))
check("A3 poll without hash 200", r.status_code == 200, r.status_code)
e = node_entry("ad2")
check("A3 /api/nodes unknown: installed None, outdated None",
      e.get("agent_bundle_sha256") is None
      and e.get("agent_code_outdated") is None, e)
st = client.get("/api/status?node=ad2").get_json()
check("A3b /api/status unknown: installed None, outdated None",
      st.get("agent_bundle_sha256") is None
      and st.get("agent_code_outdated") is None, st)

# A5 control: the bundle itself already contains the fixed
# policy-routing.sh (anchored rule_exists termination, R45-L6-3).
# This PASSES on the baseline too -- the defect is delivery, not
# bundling; the control proves the probe can see the fix when it is
# in the bundle.
r = client.get("/api/agent/bundle")
ok = False
detail = "bundle fetch %s" % r.status_code
if r.status_code == 200:
    try:
        tf = tarfile.open(fileobj=io.BytesIO(r.get_data()), mode="r:gz")
        names = tf.getnames()
        member = "egress/policy-routing.sh"
        if member in names:
            text = tf.extractfile(member).read().decode("utf-8")
            # Anchored termination: lookup $TABLE([^0-9]|$) -- the
            # grep deliberately has NO -q (SIGPIPE note above
            # rule_exists); assert the termination, not the flag.
            ok = ("lookup $TABLE([^0-9]|$)" in text
                  and "grep -E" in text)
            detail = "member present, anchored rule_exists=%s" % ok
        else:
            detail = "missing egress/policy-routing.sh in %s" % names
    except Exception as exc:  # noqa: BLE001 - report, don't crash
        detail = "tar read failed: %s" % exc
check("A5 control: bundle contains fixed policy-routing.sh", ok, detail)

print("----")
print("checks=%d failures=%d" % (CHECKS[0], len(FAILURES)))
if FAILURES:
    print("FAILED: %s" % ", ".join(FAILURES))
sys.exit(1 if FAILURES else 0)

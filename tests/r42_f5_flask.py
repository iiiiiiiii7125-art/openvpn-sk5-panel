#!/usr/bin/env python3
"""R42-F5 Flask-side probe — panel frontend family census (server half).

Drives the real Flask panel (test_client, in-process) against a fresh
data dir + the R17-style fixture PKI:

  G1  empty panel_url on node registration is silently defaulted to
      request.host_url (documents the mechanism; PASS = behavior present).
  G2  the registration response carries no warning when that default
      address is outside the panel cert SANs (desired behavior; FAIL =
      finding R42-F5-4).
  G3  install.sh builds the panel cert with exactly one server IP in
      the SANs (IP:$SERVER_IP, IP:127.0.0.1, DNS:localhost).
  G4  POST /api/openvpn/server with port null (what the frontend sends
      when the port field is empty — JSON null for NaN) is accepted and
      the server silently applies the protocol default 1194 (the
      consequence half of the DOM F5-D finding).
  G5  control: explicit panel_url is recorded as given.
  G6  control: an invalid integer port (0) is cleanly 400.

Run as nobody (the panel's test identity) with:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    OVPN_PANEL_DATA_DIR=<data> OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \\
    OVPN_SK5_CONFIG_DIR=<sk5cfg> \\
    python3 <tree>/tests/r42_f5_flask.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "panel"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "egress"))

import app as panel  # noqa: E402

FAILURES = []


def check(name, ok, evidence=""):
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" | " + str(evidence)[:300]) if evidence else ""),
          flush=True)
    if not ok:
        FAILURES.append(name)


DATA = os.environ["OVPN_PANEL_DATA_DIR"]
TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

pw = panel._ensure_admin_password()
if pw is None:
    pw = open(os.path.join(DATA, "admin.pass")).read().strip()
client = panel.app.test_client()
r = client.post("/api/login", json={"password": pw})
check("G0 login works", r.status_code == 200, r.status_code)

# --- G1/G2: empty panel_url defaults silently to request.host_url ---
# The session cookie is host-bound: log in again under the overridden
# host so the cookie is sent with the registration request.
GHOST = {"HTTP_HOST": "10.99.99.99:8443"}
r = client.post("/api/login", json={"password": pw},
                environ_overrides=GHOST)
check("G0b login works under the overridden host", r.status_code == 200,
      r.status_code)
r = client.post("/api/nodes",
                json={"name": "ghost1", "panel_url": ""},
                environ_overrides=GHOST)
d = r.get_json() or {}
rec = (d.get("node") or {}).get("panel_url")
check("G1 empty panel_url is recorded as request.host_url",
      r.status_code == 201 and rec == "http://10.99.99.99:8443",
      "status=%s panel_url=%s" % (r.status_code, rec))
blob = (d.get("note") or "") + str(d)
check("G2 registration warns when the default address is outside the "
      "panel cert SANs",
      ("SAN" in blob or "证书" in blob or "无法验证" in blob or
       "不可达" in blob),
      "response carries no SAN/reachability warning: %s" % d)

# --- G3: the panel cert carries exactly one server IP in its SANs ---
sh = open(os.path.join(TREE, "install.sh"), encoding="utf-8").read()
m = re.search(r'subjectAltName=IP:\$SERVER_IP,IP:127\.0\.0\.1,DNS:localhost',
              sh)
check("G3 panel cert SANs are exactly IP:$SERVER_IP, IP:127.0.0.1, "
      "DNS:localhost (one server IP)",
      m is not None, "SAN construction line not found" if not m else "")

# --- G4: port null is accepted and silently defaulted (F5-D chain) ---
r = client.post("/api/openvpn/server",
                json={"port": None, "proto": "udp",
                      "allow_port_change": True})
d = r.get_json() or {}
srv = d.get("server") or {}
check("G4 port null is accepted and silently defaulted to 1194",
      r.status_code == 200 and srv.get("port") == 1194,
      "status=%s server=%s" % (r.status_code, srv))

# --- G5/G6: controls -------------------------------------------------
r = client.post("/api/nodes",
                json={"name": "explicit1",
                      "panel_url": "https://panel.example:8443"})
d = r.get_json() or {}
check("G5 explicit panel_url is recorded as given",
      r.status_code == 201 and
      (d.get("node") or {}).get("panel_url") == "https://panel.example:8443",
      "status=%s" % r.status_code)
r = client.post("/api/openvpn/server",
                json={"port": 0, "proto": "udp"})
check("G6 invalid integer port 0 is cleanly 400",
      r.status_code == 400, r.status_code)

print("ALL PASS" if not FAILURES else "%d FAILURES: %s"
      % (len(FAILURES), FAILURES))
sys.exit(0 if not FAILURES else 1)

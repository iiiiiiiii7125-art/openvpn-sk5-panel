#!/usr/bin/env python3
"""R45-Fix-X2 probe — panel `$` regex follow-up (R45-L5-1 same family).

Fixes the `$` flaw Fix-X found in core/agent but which also lives in
panel/app.py:
- `_NODE_NAME_RE` (app.py:207) `^[A-Za-z0-9_-]{1,32}$` — Python `$`
  matches before a trailing `\\n`, so "n1\\n" passes.
- `_HOST_RE` (app.py:1206) `^[A-Za-z0-9._:-]{1,253}$` — same flaw.
Both now use `\\A...\\Z`.

Call-site census (done before the fix, recorded here):
- `_NODE_NAME_RE` :2746 nodes_register strips the name first, so a
  trailing newline never reaches the regex there (X10 control).
  :2786 nodes_revoke and :2834 nodes_rotate take the name from the
  URL path UNSTRIPPED — "n1\\n" (via %0A) passed the guard on the
  baseline and only 404'd on the DB miss instead of 400 (X6/X7).
  No legitimate value at any call site contains a trailing newline:
  register strips before matching, server settings are stripped
  before storage, `_stored_server_ip()` strips on read.
- `_HOST_RE` is only used inside `_valid_server_ip`, which strips
  first — so the flaw is LATENT there, not reachable today (X5/X11
  controls). The regex itself must still be correct; it cannot rely
  on callers happening to strip.

Run as nobody with:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    OVPN_PANEL_DATA_DIR=<fresh-data> OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \\
    OVPN_SK5_CONFIG_DIR=<fresh-sk5cfg> \\
    python3 <tree>/tests/r45_fix_x2_regex.py
Exit code = number of FAILs.

Negative control: the same file on baseline 16f06c9 fails X1, X3,
X6, X7 (4 cells) and passes the controls; on the fixed tree all
cells pass.
"""
import os
import sys

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TREE, "panel"))
sys.path.insert(0, os.path.join(TREE, "core"))
sys.path.insert(0, os.path.join(TREE, "egress"))
sys.path.insert(0, os.path.join(TREE, "agent"))

import app as panel  # noqa: E402

FAILURES = []
PASSES = []


def check(name, ok, evidence=""):
    (PASSES if ok else FAILURES).append(name)
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" | " + str(evidence)[:250]) if evidence else ""),
          flush=True)


DATA = os.environ["OVPN_PANEL_DATA_DIR"]
pw = panel._ensure_admin_password()
if pw is None:
    pw = open(os.path.join(DATA, "admin.pass")).read().strip()
client = panel.app.test_client()
IP = "10.9.0.9"


def login():
    r = client.post("/api/login", json={"password": pw},
                    environ_overrides={"REMOTE_ADDR": IP})
    return r.status_code == 200


def post(path, body):
    return client.post(path, json=body,
                       environ_overrides={"REMOTE_ADDR": IP})


def err_of(r):
    try:
        return (r.get_json() or {}).get("error", "")
    except Exception:  # noqa: BLE001
        return ""


check("G0 login works", login())

# ---- regex level ----
check("X1 _NODE_NAME_RE rejects 'n1\\n'",
      not panel._NODE_NAME_RE.match("n1\n"))
check("X2 _NODE_NAME_RE accepts 'n1'",
      bool(panel._NODE_NAME_RE.match("n1")))
check("X3 _HOST_RE rejects 'x\\n'",
      not panel._HOST_RE.match("x\n"))
check("X4 _HOST_RE accepts 'vpn.example.com'",
      bool(panel._HOST_RE.match("vpn.example.com")))
check("X5 _valid_server_ip('vpn.example.com\\n') still True (strip-then-validate)",
      panel._valid_server_ip("vpn.example.com\n") is True)

# ---- route level: URL-path names arrive unstripped ----
r = client.delete("/api/nodes/n1%0A",
                  environ_overrides={"REMOTE_ADDR": IP})
check("X6 DELETE /api/nodes/n1%%0A -> 400, not 404",
      r.status_code == 400, "code=%s err=%s" % (r.status_code, err_of(r)))
r = client.post("/api/nodes/n1%0A/rotate",
                environ_overrides={"REMOTE_ADDR": IP})
check("X7 POST /api/nodes/n1%%0A/rotate -> 400, not 404",
      r.status_code == 400, "code=%s err=%s" % (r.status_code, err_of(r)))

# ---- controls: clean values and strip-first paths unchanged ----
r = client.delete("/api/nodes/ghost",
                  environ_overrides={"REMOTE_ADDR": IP})
check("X8 DELETE clean nonexistent name -> 404",
      r.status_code == 404, "code=%s" % r.status_code)
r = client.post("/api/nodes/ghost/rotate",
                environ_overrides={"REMOTE_ADDR": IP})
check("X9 rotate clean nonexistent name -> 404",
      r.status_code == 404, "code=%s" % r.status_code)
r = post("/api/nodes", {"name": "x2reg\n"})
try:
    stored_name = (r.get_json() or {}).get("node", {}).get("name")
except Exception:  # noqa: BLE001
    stored_name = None
check("X10 register name 'x2reg\\n' -> 201 stored as 'x2reg' (strip-first)",
      r.status_code == 201 and stored_name == "x2reg",
      "code=%s stored=%r" % (r.status_code, stored_name))
r = post("/api/openvpn/server",
         {"proto": "udp", "port": 1194, "server_ip": "1.2.3.4\n"})
stored = panel._load_server_settings().get("server_ip")
check("X11 server_ip '1.2.3.4\\n' -> 200 stored stripped",
      r.status_code == 200 and stored == "1.2.3.4",
      "code=%s stored=%r" % (r.status_code, stored))
r = post("/api/openvpn/server",
         {"proto": "udp", "port": 1194, "server_ip": "bad host\n"})
check("X12 server_ip 'bad host\\n' -> 400 (space still rejected)",
      r.status_code == 400, "code=%s err=%s" % (r.status_code, err_of(r)))

print("TOTAL %d cells, FAIL %d: %s"
      % (len(PASSES) + len(FAILURES), len(FAILURES), FAILURES))
sys.exit(1 if FAILURES else 0)

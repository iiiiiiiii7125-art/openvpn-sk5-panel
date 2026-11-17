#!/usr/bin/env python3
"""R42-Fix-J Flask-side probe — F5-4 server half, cert-parsing path.

The audit probe (tests/r42_f5_flask.py G2) proves the fallback path:
no panel cert on disk -> the defaulted non-SAN host is warned about.
This probe proves the authoritative path, with a real openssl-generated
panel cert (SANs IP:203.0.113.9, IP:127.0.0.1, DNS:localhost) pointed
to by OVPN_PANEL_CERT_PATH (read at call time by _panel_cert_sans):

  J1  defaulted panel_url from a covered host (203.0.113.9) -> no warning.
  J2  defaulted panel_url from a non-covered host (10.99.99.99) -> warning
      naming the cert SANs and the TLS-verification failure.
  J3  explicit covered panel_url (https://127.0.0.1:8443) -> no warning.
  J4  explicit non-covered panel_url (https://panel.example:8443) -> warning.
  J5  cert unreadable (OVPN_PANEL_CERT_PATH -> missing file): fallback
      rule — 127.0.0.1 covered (no warning), 10.99.99.99 warned (G2 path
      re-proven with the fallback made explicit).
  J6  DNS-name host covered by a DNS SAN (localhost) -> no warning.

Run as nobody (the panel's test identity) with:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    OVPN_PANEL_DATA_DIR=<data> OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \\
    OVPN_SK5_CONFIG_DIR=<sk5cfg> \\
    python3 <tree>/tests/r42_fix_j_flask.py
"""
import os
import subprocess
import sys
import tempfile

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

# --- fixture panel cert: SANs IP:203.0.113.9, IP:127.0.0.1, DNS:localhost
CERT_DIR = tempfile.mkdtemp(prefix="r42j-cert-")
CERT = os.path.join(CERT_DIR, "panel-cert.pem")
KEY = os.path.join(CERT_DIR, "panel-key.pem")
r = subprocess.run(
    ["openssl", "req", "-x509", "-newkey", "rsa:2048",
     "-keyout", KEY, "-out", CERT, "-days", "30", "-nodes",
     "-subj", "/CN=203.0.113.9",
     "-addext", "subjectAltName=IP:203.0.113.9,IP:127.0.0.1,DNS:localhost"],
    capture_output=True, text=True)
assert r.returncode == 0, r.stderr

pw = panel._ensure_admin_password()
if pw is None:
    pw = open(os.path.join(DATA, "admin.pass")).read().strip()
client = panel.app.test_client()


def login(host):
    rr = client.post("/api/login", json={"password": pw},
                     environ_overrides={"HTTP_HOST": host})
    assert rr.status_code == 200, rr.status_code


def register(name, panel_url, host):
    login(host)
    return client.post("/api/nodes",
                       json={"name": name, "panel_url": panel_url},
                       environ_overrides={"HTTP_HOST": host})


def warned(d):
    w = d.get("warning") or ""
    return ("SAN" in w or "证书" in w) and "无法验证" in w


# --- J1/J2: cert path, defaulted panel_url ---------------------------
os.environ["OVPN_PANEL_CERT_PATH"] = CERT
r = register("j1covered", "", "203.0.113.9:8443")
d = r.get_json() or {}
check("J1 defaulted panel_url from a covered host has no warning",
      r.status_code == 201 and "warning" not in d,
      "status=%s d=%s" % (r.status_code, d))
r = register("j2uncovered", "", "10.99.99.99:8443")
d = r.get_json() or {}
check("J2 defaulted panel_url from a non-covered host is warned",
      r.status_code == 201 and warned(d),
      "status=%s d=%s" % (r.status_code, d))

# --- J3/J4: cert path, explicit panel_url ----------------------------
r = register("j3explicit-ok", "https://127.0.0.1:8443", "127.0.0.1:8443")
d = r.get_json() or {}
check("J3 explicit covered panel_url has no warning",
      r.status_code == 201 and "warning" not in d,
      "status=%s d=%s" % (r.status_code, d))
r = register("j4explicit-bad", "https://panel.example:8443",
             "panel.example:8443")
d = r.get_json() or {}
check("J4 explicit non-covered panel_url is warned",
      r.status_code == 201 and warned(d),
      "status=%s d=%s" % (r.status_code, d))

# --- J5: cert unreadable -> fallback rule -----------------------------
os.environ["OVPN_PANEL_CERT_PATH"] = os.path.join(CERT_DIR, "missing.pem")
r = register("j5fb-covered", "", "127.0.0.1:8443")
d = r.get_json() or {}
check("J5 fallback: 127.0.0.1 covered, no warning",
      r.status_code == 201 and "warning" not in d,
      "status=%s d=%s" % (r.status_code, d))
r = register("j5fb-uncovered", "", "10.99.99.99:8443")
d = r.get_json() or {}
check("J5 fallback: 10.99.99.99 warned",
      r.status_code == 201 and warned(d),
      "status=%s d=%s" % (r.status_code, d))

# --- J6: DNS-name host covered by a DNS SAN ---------------------------
os.environ["OVPN_PANEL_CERT_PATH"] = CERT
r = register("j6dns", "https://localhost:8443", "localhost:8443")
d = r.get_json() or {}
check("J6 DNS-name host covered by a DNS SAN has no warning",
      r.status_code == 201 and "warning" not in d,
      "status=%s d=%s" % (r.status_code, d))

print("ALL PASS" if not FAILURES else "%d FAILURES: %s"
      % (len(FAILURES), FAILURES))
sys.exit(0 if not FAILURES else 1)

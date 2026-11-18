#!/usr/bin/env python3
"""R47 live-fix probe: /api/status reports the DNS actually pushed.

LIVE-R47-1: status() reported FIXED_DNS ("1.1.1.1") while server.conf
actually pushed $OVPN_DNS -- after a DNS change the panel lied (live:
server.conf pushed 8.8.8.8, status said 1.1.1.1). The fix reads the
`push "dhcp-option DNS X"` line from the rendered server.conf and
falls back to FIXED_DNS when the conf is missing/unreadable/unparseable.

Cells (real panel server over HTTP + real server.conf on disk):
- D1: conf pushes 8.8.8.8 -> status dns == "8.8.8.8" (FAIL on 1.0.3)
- D2: conf pushes 1.1.1.1 -> status dns == "1.1.1.1"
- D3: server.conf deleted -> status 200, dns == "1.1.1.1" (fallback)
- D4: server.conf non-UTF-8 bytes -> status 200, dns == "1.1.1.1"
- D5: server.conf with no DNS push line -> status 200, dns == "1.1.1.1"
- D6: conf pushes a hostname DNS -> status dns == that hostname
  (FAIL on 1.0.3)
- D7: POST /api/openvpn/server with OVPN_DNS=8.8.8.8 -> response
  server.dns == "8.8.8.8" and the note names it (FAIL on 1.0.3)
- D8: frontend control -- the status page wires ovpn.dns into the
  status card (passes on both trees; proves the display follows
  /api/status automatically)

Run as nobody with:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    R47DNS_TREE=<tree> OVPN_PANEL_DATA_DIR=<fresh data> \\
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OVPN_PANEL_ADMIN_PASS_PATH=<data>/admin.pass \\
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fresh server dir> \\
    OVPN_SK5_CONFIG_DIR=<fresh sk5cfg> \\
    python3 <tree>/tests/r47_dns_status.py
"""
import http.cookiejar
import json
import os
import shutil
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

FAILURES = []
CHECKS = [0]


def check(name, ok, evidence=""):
    CHECKS[0] += 1
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" | " + str(evidence)[:200]) if evidence else ""),
          flush=True)
    if not ok:
        FAILURES.append(name)


TREE = os.environ.get("R47DNS_TREE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..")
for _p in (os.path.join(TREE, "panel"), os.path.join(TREE, "core"),
           os.path.join(TREE, "egress")):
    assert os.path.isdir(_p), "tree missing: %s" % _p
    sys.path.insert(0, _p)
sys.path.insert(0, os.path.join(TREE, "agent"))

SERVER_DIR = Path(os.environ["OPENVPN_SERVER_DIR"])
CA_DIR = os.environ["OPENVPN_CA_DIR"]
CONF = SERVER_DIR / "server.conf"

import app as panel  # noqa: E402
from openvpn_manager import render_server_conf  # noqa: E402

PW = panel._ensure_admin_password()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = free_port()
BASE = "http://127.0.0.1:%d" % PORT
threading.Thread(target=lambda: panel.app.run(
    host="127.0.0.1", port=PORT, threaded=True, use_reloader=False),
    daemon=True).start()
for _ in range(50):
    try:
        urllib.request.urlopen(BASE + "/api/me", timeout=2)
        break
    except Exception:
        time.sleep(0.2)

CJ = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(CJ))


def http_admin(method, path, payload=None, expect=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=body, method=method,
        headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            code = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            data = json.loads(raw)
        except ValueError:
            data = {"_raw": raw}
        code = exc.code
    if expect is not None:
        assert code == expect, (method, path, code, data)
    return code, data


def render_dns(dns):
    if CONF.exists():
        CONF.unlink()
    render_server_conf("udp", 1194, server_dir=SERVER_DIR,
                       ca_dir=CA_DIR, dns=dns, allow_port_change=True)


def status_dns():
    code, data = http_admin("GET", "/api/status", expect=200)
    return code, (data.get("openvpn") or {}).get("dns")


code, _ = http_admin("POST", "/api/login", {"password": PW}, expect=200)
check("D0 panel login 200", code == 200)

# D1: pushed 8.8.8.8 -> status says 8.8.8.8
render_dns("8.8.8.8")
code, dns = status_dns()
check("D1 status dns follows pushed 8.8.8.8", dns == "8.8.8.8", dns)

# D2: pushed 1.1.1.1 -> status says 1.1.1.1
render_dns("1.1.1.1")
code, dns = status_dns()
check("D2 status dns follows pushed 1.1.1.1", dns == "1.1.1.1", dns)

# D3: conf deleted -> 200 + fallback
CONF.unlink()
code, dns = status_dns()
check("D3 missing conf: 200 + fallback 1.1.1.1",
      code == 200 and dns == "1.1.1.1", "code=%s dns=%s" % (code, dns))

# D4: conf non-UTF-8 -> 200 + fallback
CONF.write_bytes(b"proto udp\nport 1194\npush \"dhcp-option DNS \xff\xfe\"\n")
code, dns = status_dns()
check("D4 corrupt conf: 200 + fallback 1.1.1.1",
      code == 200 and dns == "1.1.1.1", "code=%s dns=%s" % (code, dns))

# D5: conf without a DNS push line -> 200 + fallback
CONF.write_text("proto udp\nport 1194\n", encoding="utf-8")
code, dns = status_dns()
check("D5 no DNS line: 200 + fallback 1.1.1.1",
      code == 200 and dns == "1.1.1.1", "code=%s dns=%s" % (code, dns))

# D6: hostname DNS passes through verbatim
render_dns("one.one.one.one")
code, dns = status_dns()
check("D6 status dns follows hostname DNS",
      dns == "one.one.one.one", dns)

# D7: POST /api/openvpn/server reports the rendered DNS
os.environ["OVPN_DNS"] = "8.8.8.8"
try:
    code, data = http_admin("POST", "/api/openvpn/server",
                            {"proto": "udp", "port": 1194}, expect=200)
    srv = data.get("server") or {}
    check("D7 server endpoint reports rendered DNS 8.8.8.8",
          srv.get("dns") == "8.8.8.8"
          and "server.conf" in str(srv.get("note", "")),
          "dns=%s note=%s" % (srv.get("dns"), srv.get("note")))
finally:
    del os.environ["OVPN_DNS"]

# D8: frontend control -- status card reads ovpn.dns
req = urllib.request.Request(BASE + "/")
with OPENER.open(req, timeout=15) as resp:
    page = resp.read().decode()
check("D8 frontend status card wires ovpn.dns",
      'getElementById("ovpnDns")' in page and "ovpn.dns" in page)

print("----")
print("CHECKS=%d FAILURES=%d %s" % (CHECKS[0], len(FAILURES), FAILURES))
sys.exit(1 if FAILURES else 0)

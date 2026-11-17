#!/usr/bin/env python3
"""R44-L7 hostile-v2 probe 1/4 — str() coercion census, part 2.

Seeds:
  (a) Fix-O observation: agent/agent.py:651 action_create_server does
      ``str(params["dns"])`` before core's _validate_dns isinstance
      guard — a list-typed dns is coerced to a string that may pass
      the shape guard and land verbatim in server.conf.
  (b) Same family on the Flask face: panel/app.py server-save does
      ``str(server_ip).strip()`` before _valid_server_ip's isinstance
      guard — an int/bool/list server_ip may be stored as "123"/"True".

Cells:
  C1-C3  Flask POST /api/openvpn/server with server_ip 123 / True /
         ["1.2.3.4"] -> must be 400 (finding if 200 + stored).
  C4     Flask server_ip "123" (string) — reference behavior only.
  C5     Flask server_ip "1.2.3.4" -> 200 (control).
  C6     Flask server_ip "" clears (control).
  C7-C8  Fix-O HOLD controls: create-user name 123 -> 400, node
         name 123 -> 400.
  A1-A3  Agent action_create_server with dns [8] / 123 / ["8.8.8.8"]
         -> captured dns arg must stay non-string (ValueError); a
         captured string proves the coercion (finding).
  A4-A5  Agent dns "8.8.8.8" / None pass through unchanged (controls).
  R1     Core render_server_conf(dns="[8]") writes the literal line
         'push "dhcp-option DNS [8]"' (landing proof).
  R2     Core render_server_conf(dns="123") writes DNS 123 (landing).
  R3     Core render_server_conf(dns=[8]) raises (core guard works
         when the agent does NOT coerce first — isolates the blame).
  R4     Core _validate_dns("['8.8.8.8']") raises on the quote
         (why the ["8.8.8.8"] shape is only incidentally safe).

Run as nobody with:
  cp -a <fixture-server> /tmp/r44l7-srv   (probe renders into the copy)
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    OVPN_PANEL_DATA_DIR=<fresh-data> OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=/tmp/r44l7-srv \\
    OVPN_SK5_CONFIG_DIR=<fresh-sk5cfg> \\
    python3 <tree>/tests/r44_l7_coercion.py
Exit code = number of FAILs.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TREE, "panel"))
sys.path.insert(0, os.path.join(TREE, "core"))
sys.path.insert(0, os.path.join(TREE, "egress"))
sys.path.insert(0, os.path.join(TREE, "agent"))

import app as panel  # noqa: E402
import agent as agent_mod  # noqa: E402
import openvpn_manager as core  # noqa: E402

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
IP = "10.9.0.11"


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

# ---- Flask server_ip coercion ----
r = post("/api/openvpn/server",
         {"proto": "udp", "port": 1194, "server_ip": 123})
stored = None
try:
    stored = panel._load_server_settings().get("server_ip")
except Exception:  # noqa: BLE001
    pass
check("C1 server_ip int 123 -> 400, not stored",
      r.status_code == 400, "code=%s stored=%r err=%s"
      % (r.status_code, stored, err_of(r)))

r = post("/api/openvpn/server",
         {"proto": "udp", "port": 1194, "server_ip": True})
stored = panel._load_server_settings().get("server_ip")
check("C2 server_ip bool True -> 400, not stored",
      r.status_code == 400, "code=%s stored=%r err=%s"
      % (r.status_code, stored, err_of(r)))

r = post("/api/openvpn/server",
         {"proto": "udp", "port": 1194, "server_ip": ["1.2.3.4"]})
stored = panel._load_server_settings().get("server_ip")
check("C3 server_ip list -> 400, not stored",
      r.status_code == 400, "code=%s stored=%r err=%s"
      % (r.status_code, stored, err_of(r)))

r = post("/api/openvpn/server",
         {"proto": "udp", "port": 1194, "server_ip": "123"})
stored = panel._load_server_settings().get("server_ip")
print("INFO C4 server_ip string '123': code=%s stored=%r"
      % (r.status_code, stored))
check("C4 reference: string '123' behavior recorded",
      True, "code=%s stored=%r" % (r.status_code, stored))

r = post("/api/openvpn/server",
         {"proto": "udp", "port": 1194, "server_ip": "1.2.3.4"})
stored = panel._load_server_settings().get("server_ip")
check("C5 server_ip valid string -> 200 stored",
      r.status_code == 200 and stored == "1.2.3.4",
      "code=%s stored=%r" % (r.status_code, stored))

r = post("/api/openvpn/server",
         {"proto": "udp", "port": 1194, "server_ip": ""})
stored = panel._load_server_settings().get("server_ip")
check("C6 server_ip empty clears stored value",
      r.status_code == 200 and stored is None,
      "code=%s stored=%r" % (r.status_code, stored))

# ---- Fix-O HOLD controls ----
r = post("/api/openvpn/users", {"name": 123})
check("C7 HOLD create-user name 123 -> 400",
      r.status_code == 400, "code=%s err=%s" % (r.status_code, err_of(r)))
r = post("/api/nodes", {"name": 123})
check("C8 HOLD node-register name 123 -> 400",
      r.status_code == 400, "code=%s err=%s" % (r.status_code, err_of(r)))

# ---- Agent dns coercion (stubbed manager) ----
_captured = {}


def _fake_init_pki(*a, **k):
    return Path("/tmp/no-ca")


def _fake_build(*a, **k):
    return []


def _fake_render(**kwargs):
    _captured.update(kwargs)
    return Path("/tmp/no-conf")


# Save the real core functions FIRST (agent_mod.openvpn_manager IS
# the same module object as `core`, so patching one patches both).
_real_init_pki = agent_mod.openvpn_manager.init_pki
_real_build = agent_mod.openvpn_manager.build_server_cert
_real_render = agent_mod.openvpn_manager.render_server_conf

agent_mod.openvpn_manager.init_pki = _fake_init_pki
agent_mod.openvpn_manager.build_server_cert = _fake_build
agent_mod.openvpn_manager.render_server_conf = _fake_render
# NOTE: the stub above also replaces core.render_server_conf —
# restore the real function before the R cells, or the landing
# proof would call the stub.


def _agent_dns(value):
    _captured.clear()
    try:
        agent_mod.action_create_server({"proto": "udp", "port": 1194,
                                        "dns": value})
        return ("ok", _captured.get("dns"))
    except Exception as exc:  # noqa: BLE001
        return ("raise", "%s: %s" % (type(exc).__name__, exc))


kind, val = _agent_dns([8])
check("A1 agent dns [8] must raise, not coerce to '[8]'",
      kind == "raise", "%s val=%r" % (kind, val))
kind, val = _agent_dns(123)
check("A2 agent dns 123 must raise, not coerce to '123'",
      kind == "raise", "%s val=%r" % (kind, val))
kind, val = _agent_dns(["8.8.8.8"])
check("A3 agent dns ['8.8.8.8'] must raise, not coerce",
      kind == "raise", "%s val=%r" % (kind, val))
kind, val = _agent_dns("8.8.8.8")
check("A4 agent dns string passes through unchanged",
      kind == "ok" and val == "8.8.8.8", "%s val=%r" % (kind, val))
kind, val = _agent_dns(None)
check("A5 agent dns None passes through as None",
      kind == "ok" and val is None, "%s val=%r" % (kind, val))

# Restore the real core functions (see note above) before the R cells.
agent_mod.openvpn_manager.init_pki = _real_init_pki
agent_mod.openvpn_manager.build_server_cert = _real_build
agent_mod.openvpn_manager.render_server_conf = _real_render

# ---- Core landing proof (real render into temp dirs) ----
tmp = Path(tempfile.mkdtemp(prefix="r44l7-core-"))
srv = tmp / "server"
srv.mkdir()
ca = tmp / "ca"
ca.mkdir()
(pki := ca / "pki").mkdir()


def _render(dns):
    return core.render_server_conf(
        proto="udp", port=51194, dns=dns, server_dir=srv, ca_dir=ca,
        allow_port_change=True)


try:
    p = _render("[8]")
    text = p.read_text(encoding="utf-8")
    check("R1 core render dns='[8]' lands verbatim in server.conf",
          'push "dhcp-option DNS [8]"' in text,
          [l for l in text.splitlines() if "dhcp-option DNS" in l])
except Exception as exc:  # noqa: BLE001
    check("R1 core render dns='[8]' lands verbatim in server.conf",
          False, "raised %r" % (exc,))
try:
    p = _render("123")
    text = p.read_text(encoding="utf-8")
    check("R2 core render dns='123' lands verbatim in server.conf",
          'push "dhcp-option DNS 123"' in text,
          [l for l in text.splitlines() if "dhcp-option DNS" in l])
except Exception as exc:  # noqa: BLE001
    check("R2 core render dns='123' lands verbatim in server.conf",
          False, "raised %r" % (exc,))
try:
    _render([8])
    check("R3 core render dns=[8] (list, no agent) raises", False,
          "no raise — core guard is dead even without the agent")
except Exception as exc:  # noqa: BLE001
    check("R3 core render dns=[8] (list, no agent) raises", True,
          "%s: %s" % (type(exc).__name__, exc))
try:
    core._validate_dns("['8.8.8.8']")
    check("R4 _validate_dns rejects quoted list-string", False,
          "no raise")
except Exception as exc:  # noqa: BLE001
    check("R4 _validate_dns rejects quoted list-string", True,
          "%s: %s" % (type(exc).__name__, exc))

print()
print("TOTAL: PASS=%d FAIL=%d %s" % (len(PASSES), len(FAILURES), FAILURES))
sys.exit(len(FAILURES))

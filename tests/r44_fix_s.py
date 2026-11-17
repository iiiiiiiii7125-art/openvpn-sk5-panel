#!/usr/bin/env python3
"""Fix-S probe (r44_fix_s.py) — R44-L7-1 + L4-F1/F2/F3 entry validation.

Cells (each FAILs on baseline 46a78e8, PASSes on the Fix-S tip):
  S1-S3  Flask POST /api/openvpn/server server_ip 123 / True /
         ["1.2.3.4"] -> 400, not stored (L7-1b).
  S4-S5  Controls: valid string stored, "" clears.
  S6-S8  Agent action_create_server dns [8] / 123 / ["8.8.8.8"]
         -> ValueError (L7-1a).
  S9-S10 Controls: dns "8.8.8.8" / None pass through unchanged.
  S11-S12 Flask /api/sk5/fail-open and /api/sk5/udp-over-tcp with
         NO stored config -> 400 with the Worker message (L4-F3).
  S13-S14 Same routes WITH a stored config -> toggle applies
         (stored value flips; status 200/500 tolerated like the
         L4 probe — the trailing get_status egress probe is
         environment-dependent, the stored value is the proof).
  S15-S17 Agent action_set_sk5 gate (stubbed sk5_manager):
         fail_open-only with no stored host -> ValueError with the
         Worker message and set_sk5 NOT called; with a stored host
         -> set_sk5 called; host+port+fail_open with no stored host
         -> set_sk5 called (gate is toggle-only).
  S18-S19 HOLD controls (Fix-O): create-user name 123 -> 400,
         node name 123 -> 400.

Worker cells W30/W31/W34 are covered by the L4 probe
(tests/r44_l4_worker.mjs — re-run, must go 76/79 -> 79/79);
this probe is Flask + agent only.

Run as nobody with PYTHONPATH=<venv> site-packages:
  cp -a <fixture-server> /tmp/r44fixs-srv   (probe renders into the copy)
  runuser -u nobody -- env PYTHONPATH=/tmp/r41-l5-venv/lib/python3.12/site-packages \\
    OVPN_PANEL_DATA_DIR=<fresh-data> OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=/tmp/r44fixs-srv \\
    OVPN_SK5_CONFIG_DIR=<fresh-sk5cfg> \\
    python3 <tree>/tests/r44_fix_s.py
Exit code = number of FAILs.
"""
import json
import os
import sys
from pathlib import Path

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(TREE, "panel"))
sys.path.insert(0, os.path.join(TREE, "core"))
sys.path.insert(0, os.path.join(TREE, "egress"))
sys.path.insert(0, os.path.join(TREE, "agent"))

import app as panel  # noqa: E402
import agent as agent_mod  # noqa: E402

FAILURES = []
PASSES = []


def check(name, ok, evidence=""):
    (PASSES if ok else FAILURES).append(name)
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" | " + str(evidence)[:250]) if evidence else ""),
          flush=True)


NO_CONFIG_MSG = "先在 SK5 配置页保存完整 SK5 配置（host/port），再改这个开关"

DATA = os.environ["OVPN_PANEL_DATA_DIR"]
SK5CFG = Path(os.environ["OVPN_SK5_CONFIG_DIR"])
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

# ---- Flask server_ip coercion (L7-1b) ----
for tag, value in (("S1", 123), ("S2", True), ("S3", ["1.2.3.4"])):
    r = post("/api/openvpn/server",
             {"proto": "udp", "port": 1194, "server_ip": value})
    try:
        stored = panel._load_server_settings().get("server_ip")
    except Exception:  # noqa: BLE001
        stored = "<unreadable>"
    check("%s server_ip %r -> 400, not stored" % (tag, value),
          r.status_code == 400 and stored is None,
          "code=%s stored=%r err=%s" % (r.status_code, stored, err_of(r)))

r = post("/api/openvpn/server",
         {"proto": "udp", "port": 1194, "server_ip": "1.2.3.4"})
stored = panel._load_server_settings().get("server_ip")
check("S4 server_ip valid string -> 200 stored",
      r.status_code == 200 and stored == "1.2.3.4",
      "code=%s stored=%r" % (r.status_code, stored))

r = post("/api/openvpn/server",
         {"proto": "udp", "port": 1194, "server_ip": ""})
stored = panel._load_server_settings().get("server_ip")
check("S5 server_ip empty clears stored value",
      r.status_code == 200 and stored is None,
      "code=%s stored=%r" % (r.status_code, stored))

# ---- Agent dns coercion (stubbed manager, L7 probe pattern) ----
_captured = {}


def _fake_init_pki(*a, **k):
    return Path("/tmp/no-ca")


def _fake_build(*a, **k):
    return []


def _fake_render(**kwargs):
    _captured.update(kwargs)
    return Path("/tmp/no-conf")


_real_init_pki = agent_mod.openvpn_manager.init_pki
_real_build = agent_mod.openvpn_manager.build_server_cert
_real_render = agent_mod.openvpn_manager.render_server_conf
agent_mod.openvpn_manager.init_pki = _fake_init_pki
agent_mod.openvpn_manager.build_server_cert = _fake_build
agent_mod.openvpn_manager.render_server_conf = _fake_render


def _agent_dns(value):
    _captured.clear()
    try:
        agent_mod.action_create_server({"proto": "udp", "port": 1194,
                                        "dns": value})
        return ("ok", _captured.get("dns"))
    except Exception as exc:  # noqa: BLE001
        return ("raise", "%s: %s" % (type(exc).__name__, exc))


for tag, value in (("S6", [8]), ("S7", 123), ("S8", ["8.8.8.8"])):
    kind, val = _agent_dns(value)
    check("%s agent dns %r must raise, not coerce" % (tag, value),
          kind == "raise", "%s val=%r" % (kind, val))

kind, val = _agent_dns("8.8.8.8")
check("S9 agent dns '8.8.8.8' passes through unchanged",
      kind == "ok" and val == "8.8.8.8", "%s val=%r" % (kind, val))
kind, val = _agent_dns(None)
check("S10 agent dns None passes through as None",
      kind == "ok" and val is None, "%s val=%r" % (kind, val))

agent_mod.openvpn_manager.init_pki = _real_init_pki
agent_mod.openvpn_manager.build_server_cert = _real_build
agent_mod.openvpn_manager.render_server_conf = _real_render

# ---- Flask toggle routes with no stored config (L4-F3) ----
r = post("/api/sk5/fail-open", {"fail_open": True})
check("S11 fail-open no stored config -> 400 Worker message",
      r.status_code == 400 and err_of(r) == NO_CONFIG_MSG,
      "code=%s err=%s" % (r.status_code, err_of(r)))
r = post("/api/sk5/udp-over-tcp", {"udp_over_tcp": True})
check("S12 udp-over-tcp no stored config -> 400 Worker message",
      r.status_code == 400 and err_of(r) == NO_CONFIG_MSG,
      "code=%s err=%s" % (r.status_code, err_of(r)))

# Seed a stored config, then the same toggles must apply.
SK5CFG.mkdir(parents=True, exist_ok=True)
(SK5CFG / "sk5.json").write_text(json.dumps(
    {"host": "proxy.example", "port": 1001, "username": "u1",
     "password": "p1", "enabled": False, "fail_open": False,
     "udp_over_tcp": False}), encoding="utf-8")


def _stored_sk5():
    try:
        return json.loads((SK5CFG / "sk5.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


r = post("/api/sk5/fail-open", {"fail_open": True})
check("S13 fail-open with stored config applies (not 400)",
      r.status_code in (200, 500)
      and err_of(r) != NO_CONFIG_MSG
      and _stored_sk5().get("fail_open") is True,
      "code=%s stored=%r" % (r.status_code, _stored_sk5()))
r = post("/api/sk5/udp-over-tcp", {"udp_over_tcp": True})
check("S14 udp-over-tcp with stored config applies (not 400)",
      r.status_code in (200, 500)
      and err_of(r) != NO_CONFIG_MSG
      and _stored_sk5().get("udp_over_tcp") is True,
      "code=%s stored=%r" % (r.status_code, _stored_sk5()))

# ---- Agent set_sk5 gate (stubbed sk5_manager) ----
_called = {}


def _fake_set_sk5(*a, **k):
    _called.update({"args": a, "kwargs": k})
    return {"ok": True}


_real_get_status = agent_mod.sk5_manager.get_status
_real_set_sk5 = agent_mod.sk5_manager.set_sk5
agent_mod.sk5_manager.set_sk5 = _fake_set_sk5


def _agent_set_sk5(params, stored_host):
    _called.clear()
    agent_mod.sk5_manager.get_status = (
        lambda probe_egress=True: {"host": stored_host, "port": 1001})
    try:
        agent_mod.action_set_sk5(params)
        return ("ok", _called.get("kwargs"))
    except Exception as exc:  # noqa: BLE001
        return ("raise", "%s: %s" % (type(exc).__name__, exc))


kind, val = _agent_set_sk5({"fail_open": True}, "")
check("S15 agent set_sk5 fail_open-only, no stored host -> "
      "ValueError Worker message, set_sk5 NOT called",
      kind == "raise" and NO_CONFIG_MSG in str(val)
      and "kwargs" not in _called,
      "%s val=%r called=%s" % (kind, val, bool(_called)))
kind, val = _agent_set_sk5({"fail_open": True}, "proxy.example")
check("S16 agent set_sk5 fail_open-only, stored host -> set_sk5 called",
      kind == "ok" and (_called.get("kwargs") or {}).get("fail_open") is True,
      "%s val=%r called=%s" % (kind, val, _called.get("kwargs")))
kind, val = _agent_set_sk5(
    {"host": "proxy.example", "port": 1001, "fail_open": True}, "")
check("S17 agent set_sk5 host+port+fail_open, no stored host -> "
      "set_sk5 called (gate is toggle-only)",
      kind == "ok" and (_called.get("kwargs") or {}).get("fail_open") is True,
      "%s val=%r called=%s" % (kind, val, _called.get("kwargs")))

agent_mod.sk5_manager.get_status = _real_get_status
agent_mod.sk5_manager.set_sk5 = _real_set_sk5

# ---- Fix-O HOLD controls ----
r = post("/api/openvpn/users", {"name": 123})
check("S18 HOLD create-user name 123 -> 400",
      r.status_code == 400, "code=%s err=%s" % (r.status_code, err_of(r)))
r = post("/api/nodes", {"name": 123})
check("S19 HOLD node-register name 123 -> 400",
      r.status_code == 400, "code=%s err=%s" % (r.status_code, err_of(r)))

print()
print("TOTAL %d cells, FAIL %d: %s"
      % (len(PASSES) + len(FAILURES), len(FAILURES), FAILURES))
sys.exit(len(FAILURES))

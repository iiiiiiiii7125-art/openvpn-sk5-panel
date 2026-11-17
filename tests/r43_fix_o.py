#!/usr/bin/env python3
"""R43-Fix-O probe — strict type validation for names/usernames/hosts.

Fixes R43-J7-1 (P2): str() coercion of non-string JSON values into
names/usernames/hosts/passwords that then pass validation and get
silently created/stored (str(123) is "123", str(None) is "None").
Same mechanism class as R12-P1-2 (bool port).

Flask cells (O): in-process test_client as nobody, fresh data dir,
same harness as tests/r43_j7_hostile_flask.py. Agent cells (A): the
real agent module with openvpn_manager/sk5_manager calls stubbed —
the type gate under test runs before any manager call, so the stubs
only prove a valid string reaches the manager unchanged.

Run as nobody with:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \
    OVPN_PANEL_DATA_DIR=<fresh-data> OVPN_PANEL_SECRET_PATH=<data>/secret.key \
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \
    OVPN_SK5_CONFIG_DIR=<fresh-sk5cfg> \
    python3 <tree>/tests/r43_fix_o.py
Exit code = number of FAILs.

Negative control: the same file on baseline 2e08a8c fails O1-O3,
O6-O8, O10-O12, O14-O15, O17, O19-O21, A1, A3, A5, A7-A9 (21 cells)
and passes the controls; on the fixed tree all cells pass.
"""
import json
import os
import sys

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

# ---- O1-O5: create-user name type ----
r = post("/api/openvpn/users", {"name": 123})
check("O1 create-user name 123 -> 400", r.status_code == 400, r.status_code)
r = post("/api/openvpn/users", {"name": None})
check("O2 create-user name null -> 400", r.status_code == 400, r.status_code)
r = post("/api/openvpn/users", {"name": True})
check("O3 create-user name true -> 400", r.status_code == 400, r.status_code)
r = post("/api/openvpn/users", {"name": ["x"]})
check("O4 create-user name ['x'] -> 400 (control, was already 400)",
      r.status_code == 400, r.status_code)
r = post("/api/openvpn/users", {"name": "alice"})
check("O5 create-user name 'alice' passes validation (409: fixture alice "
      "already exists)",
      r.status_code == 409 and "already exists" in err_of(r),
      "%s %s" % (r.status_code, err_of(r)[:80]))
r = post("/api/openvpn/users", {})
check("O23 create-user name missing -> 400 (control)",
      r.status_code == 400, r.status_code)

# ---- O6-O9, O24: node-register name type ----
for val, tag in ((123, "123"), (None, "null"), (True, "true")):
    r = post("/api/nodes", {"name": val, "panel_url": "https://10.0.0.1:8443"})
    check("O%s node-register name %s -> 400, not created"
          % ({"123": 6, "null": 7, "true": 8}[tag], tag),
          r.status_code == 400 and panel._get_node(str(val)) is None,
          r.status_code)
r = post("/api/nodes", {"name": "node1", "panel_url": "https://10.0.0.1:8443"})
check("O9 node-register name 'node1' -> 201 (control)",
      r.status_code == 201, r.status_code)
r = post("/api/nodes", {"panel_url": "https://10.0.0.1:8443"})
check("O24 node-register name missing -> 400 (control)",
      r.status_code == 400, r.status_code)


def sk5_status():
    return panel.sk5_get_status(probe_egress=False)


# ---- O10-O18: SK5 local save types ----
r = post("/api/sk5", {"host": "h.example", "port": 1001, "username": 123})
check("O10 sk5 username 123 -> 400", r.status_code == 400, r.status_code)
r = post("/api/sk5", {"host": "h.example", "port": 1001, "username": None})
check("O11 sk5 username null -> 400", r.status_code == 400, r.status_code)
r = post("/api/sk5", {"host": "h.example", "port": 1001, "username": True})
check("O12 sk5 username true -> 400", r.status_code == 400, r.status_code)
r = post("/api/sk5", {"host": "h.example", "port": 1001, "username": "u1"})
check("O13 sk5 username 'u1' -> 200 (control)",
      r.status_code == 200, r.status_code)
r = post("/api/sk5", {"host": 123, "port": 1001})
check("O14 sk5 host 123 -> 400", r.status_code == 400, r.status_code)
r = post("/api/sk5", {"host": None, "port": 1001})
check("O15 sk5 host null -> 400", r.status_code == 400, r.status_code)
r = post("/api/sk5", {"host": "h.example", "port": 1001})
check("O16 sk5 host 'h.example' -> 200 (control)",
      r.status_code == 200, r.status_code)
r = post("/api/sk5", {"host": "h.example", "port": 1001,
                      "password": 12345678})
check("O17 sk5 password 12345678 -> 400", r.status_code == 400,
      r.status_code)
r = post("/api/sk5", {"host": "h.example", "port": 1001,
                      "username": "u1", "password": "s3cret"})
check("O18 sk5 password 's3cret' -> 200, stored as string (control)",
      r.status_code == 200 and
      json.load(open(os.path.join(os.environ["OVPN_SK5_CONFIG_DIR"],
                                  "sk5.json"))).get("password") == "s3cret",
      r.status_code)

# ---- O19-O22: SK5 remote save types (node1 registered above) ----
r = post("/api/sk5", {"node": "node1", "host": "h.example", "port": 1001,
                      "username": 123})
check("O19 sk5 remote username 123 -> 400", r.status_code == 400,
      r.status_code)
r = post("/api/sk5", {"node": "node1", "host": 123, "port": 1001})
check("O20 sk5 remote host 123 -> 400", r.status_code == 400, r.status_code)
r = post("/api/sk5", {"node": "node1", "host": "h.example", "port": 1001,
                      "password": 12345678})
check("O21 sk5 remote password 12345678 -> 400", r.status_code == 400,
      r.status_code)
r = post("/api/sk5", {"node": "node1", "host": "h.example", "port": 1001,
                      "username": "u1", "password": "s3cret"})
check("O22 sk5 remote valid strings -> 202 queued (control)",
      r.status_code == 202, r.status_code)

# ---- A1-A11: agent enforcement point (Worker face passes names raw) ----
_calls = {}


def _fake_create_user(name, **kw):
    _calls["create_user"] = name
    return "--- FAKE OVPN for %s ---" % name


def _fake_revoke_user(name):
    _calls["revoke_user"] = name
    return {"revoked": name}


def _fake_set_sk5(*args, **kwargs):
    _calls["set_sk5"] = (args, kwargs)
    return {"ok": True}


agent_mod.openvpn_manager.create_user = _fake_create_user
agent_mod.openvpn_manager.revoke_user = _fake_revoke_user
agent_mod.openvpn_manager.restart_server = lambda: {"ok": True}
agent_mod.sk5_manager.set_sk5 = _fake_set_sk5


def expect_value_error(name, fn, needle=""):
    try:
        fn()
    except ValueError as exc:
        check(name, needle in str(exc), str(exc)[:120])
        return
    except Exception as exc:  # noqa: BLE001 - wrong exception type
        check(name, False, "wrong exc %s: %s" % (type(exc).__name__, exc))
        return
    check(name, False, "no exception raised")


expect_value_error(
    "A1 agent create_user name 123 -> ValueError",
    lambda: agent_mod.action_create_user({"name": 123}), "must be a string")
expect_value_error(
    "A2 agent create_user name null -> ValueError",
    lambda: agent_mod.action_create_user({"name": None}), "")
expect_value_error(
    "A3 agent create_user name true -> ValueError",
    lambda: agent_mod.action_create_user({"name": True}), "must be a string")
_calls.clear()
res = agent_mod.action_create_user({"name": "alice"})
check("A4 agent create_user name 'alice' reaches manager (control)",
      res.get("name") == "alice" and _calls.get("create_user") == "alice",
      str(res)[:80])
expect_value_error(
    "A5 agent revoke_user name 123 -> ValueError",
    lambda: agent_mod.action_revoke_user({"name": 123}), "must be a string")
_calls.clear()
agent_mod.action_revoke_user({"name": "alice"})
check("A6 agent revoke_user name 'alice' reaches manager (control)",
      _calls.get("revoke_user") == "alice", str(_calls))
expect_value_error(
    "A7 agent set_sk5 username 123 -> ValueError",
    lambda: agent_mod.action_set_sk5({"username": 123}), "must be a string")
expect_value_error(
    "A8 agent set_sk5 host 123 -> ValueError",
    lambda: agent_mod.action_set_sk5({"host": 123}), "must be a string")
expect_value_error(
    "A9 agent set_sk5 password 12345678 -> ValueError",
    lambda: agent_mod.action_set_sk5({"password": 12345678}),
    "must be a string")
_calls.clear()
agent_mod.action_set_sk5({"host": "h.example", "port": 1001,
                          "username": "u1", "password": "s3cret"})
_args, kwargs = _calls.get("set_sk5", ((), {}))
check("A10 agent set_sk5 valid strings pass through unchanged (control)",
      _args[:2] == ("h.example", 1001)
      and kwargs.get("username") == "u1"
      and kwargs.get("password") == "s3cret",
      "args=%s kwargs=%s" % (str(_args)[:80], str(kwargs)[:160]))
_calls.clear()
agent_mod.action_set_sk5({})
check("A11 agent set_sk5 {} -> no exception (control)",
      "set_sk5" in _calls, str(_calls))

print("\nTOTAL: PASS=%d FAIL=%d %s" % (
    len(PASSES), len(FAILURES), FAILURES))
sys.exit(len(FAILURES))

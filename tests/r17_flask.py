#!/usr/bin/env python3
"""AUDIT-R17 Flask probe (r17_flask.py) — rebuilt from mechanism, own enumeration.

Drives panel/app.py through Flask test_client (real code paths, no monkeypatch
except env isolation). Run as nobody with PYTHONPATH=venv site-packages:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \
    OVPN_PANEL_DATA_DIR=<data> OVPN_PANEL_SECRET_PATH=<data>/secret.key \
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \
    OVPN_SK5_CONFIG_DIR=<sk5cfg> \
    python3 /tmp/r17/r17_flask.py
(OVPN_SK5_CONFIG_DIR is required: without it sk5_manager writes
the SK5 config to /etc/openvpn-sk5-panel, which is root-owned --
as nobody every /api/sk5 save then 500s with "cannot write ...
sk5.json", a probe-invocation gap, not a product failure.)

Login lockout is per-IP, so each phase uses its own REMOTE_ADDR.
Fixture PKI (index.txt TAB rows): alice V-valid, bob R-revoked,
erin V-but-expiry-past (effective expired), carol E-expired, dave V-valid.
Cells numbered F1..F6x; exit code = number of FAILs (0 = all green).
"""
import json
import os
import sys
from pathlib import Path

TREE = Path(os.environ.get("R17_TREE", "/tmp/r17/ptree"))
sys.path.insert(0, str(TREE / "panel"))
sys.path.insert(0, str(TREE / "core"))
sys.path.insert(0, str(TREE / "egress"))

import app as panel  # noqa: E402

RESULTS = []
IP_LOCK = "10.0.0.11"   # lockout sequence
IP_ADMIN = "10.0.0.12"  # admin session
IP_AGENT = "10.0.0.13"  # agent poll/report
IP_MISC = "10.0.0.14"


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""))


def G(c, url, ip, **kw):
    return c.get(url, environ_base={"REMOTE_ADDR": ip}, **kw)


def P(c, url, ip, **kw):
    return c.post(url, environ_base={"REMOTE_ADDR": ip}, **kw)


def D(c, url, ip, **kw):
    return c.delete(url, environ_base={"REMOTE_ADDR": ip}, **kw)


def main():
    pw = panel._ensure_admin_password()
    assert pw, "admin password not generated"
    c = panel.app.test_client()

    # ---------- F1 login / lockout ----------
    r = G(c, "/api/status", IP_MISC)
    cell("F1-01 status unauth 401", r.status_code == 401, str(r.status_code))
    r = P(c, "/api/login", IP_MISC, json={})
    cell("F1-02 login missing password 401 (O1 obs)", r.status_code == 401, str(r.status_code))
    r = P(c, "/api/login", IP_MISC, json={"password": 12345})
    cell("F1-03 login non-string password 401", r.status_code == 401, str(r.status_code))
    for i in range(5):
        r = P(c, "/api/login", IP_LOCK, json={"password": "wrong-password"})
    cell("F1-04 5 wrong logins -> 5th 401", r.status_code == 401, str(r.status_code))
    r = P(c, "/api/login", IP_LOCK, json={"password": "wrong-password"})
    cell("F1-05 6th wrong login 429 + Retry-After",
         r.status_code == 429 and "Retry-After" in r.headers,
         f"{r.status_code} {r.headers.get('Retry-After')}")
    r = P(c, "/api/login", IP_LOCK, json={"password": pw})
    cell("F1-06 locked IP + correct password still 429", r.status_code == 429, str(r.status_code))
    r = P(c, "/api/login", IP_ADMIN, json={"password": pw})
    cell("F1-07 correct login 200", r.status_code == 200, str(r.status_code))
    set_cookie = r.headers.get("Set-Cookie", "")
    cell("F1-08 session cookie HttpOnly + SameSite=Lax",
         "HttpOnly" in set_cookie and "SameSite=Lax" in set_cookie, set_cookie[:80])
    admin = panel.app.test_client()
    # re-login on the admin client (cookies are per-client)
    r = P(admin, "/api/login", IP_ADMIN, json={"password": pw})
    cell("F1-09 admin client login 200", r.status_code == 200, str(r.status_code))
    r = G(admin, "/api/me", IP_ADMIN)
    cell("F1-10 /api/me logged in admin=true",
         r.status_code == 200 and r.get_json().get("admin") is True, str(r.status_code))
    r = P(admin, "/api/change-password", IP_ADMIN,
          json={"old_password": pw, "new_password": "short"})
    cell("F1-11 change-password too short 400", r.status_code == 400, str(r.status_code))
    r = P(admin, "/api/change-password", IP_ADMIN,
          json={"old_password": pw, "new_password": "newpass123456"})
    cell("F1-12 change-password ok 200", r.status_code == 200, str(r.status_code))
    r = G(admin, "/api/me", IP_ADMIN)
    cell("F1-13 old session dead after change-password",
         r.get_json().get("admin") is not True, str(r.get_json()))
    r = P(admin, "/api/login", IP_ADMIN, json={"password": "newpass123456"})
    cell("F1-14 login with new password 200", r.status_code == 200, str(r.status_code))
    pw = "newpass123456"

    # ---------- F2 input validation: create_server / sk5 ----------
    for val, label in [(True, "bool True"), (0, "0"), (-1, "-1"), (65536, "65536"),
                       (1194.5, "float"), ("1194", "digit str")]:
        r = P(admin, "/api/openvpn/server", IP_ADMIN, json={"proto": "udp", "port": val})
        cell(f"F2-01 create_server port={label} 400", r.status_code == 400,
             f"{r.status_code} {str(r.get_json())[:60]}")
    r = P(admin, "/api/openvpn/server", IP_ADMIN, json={"proto": "udp"})
    cell("F2-02 create_server port omitted -> 200 (render ok)",
         r.status_code == 200, f"{r.status_code} {str(r.get_json())[:100]}")
    r = P(admin, "/api/openvpn/server", IP_ADMIN, json={"proto": 123})
    cell("F2-03 create_server proto non-string 400", r.status_code == 400, str(r.status_code))
    r = P(admin, "/api/openvpn/server", IP_ADMIN, json={"proto": "sctp"})
    cell("F2-04 create_server proto sctp 400", r.status_code == 400, str(r.status_code))
    r = P(admin, "/api/openvpn/server", IP_ADMIN,
          json={"proto": "udp", "allow_port_change": "false"})
    cell("F2-05 create_server allow_port_change str 400", r.status_code == 400, str(r.status_code))
    r = P(admin, "/api/openvpn/server", IP_ADMIN,
          json={"proto": "udp", "port": 1194, "allow_port_change": 1})
    cell("F2-06 create_server allow_port_change int 1 ok",
         r.status_code == 200, f"{r.status_code} {str(r.get_json())[:80]}")
    for body, label, want in [
        ({"host": "proxy.example.net", "port": 1001, "username": "u", "password": "p",
          "enabled": "true"}, "enabled str true", 400),
        ({"host": "proxy.example.net", "port": 1001, "username": "u", "password": "p",
          "enabled": "false"}, "enabled str false", 400),
        ({"host": "proxy.example.net", "port": 1001, "username": "u", "password": "p",
          "enabled": 1}, "enabled int 1", "HONEST500"),
        ({"host": "proxy.example.net", "port": 1001, "username": "u", "password": "p",
          "enabled": 0}, "enabled int 0", 200),
        ({"host": "proxy.example.net", "port": True, "username": "u", "password": "p"},
         "port bool True", 400),
        ({"host": "proxy.example.net", "port": 0, "username": "u", "password": "p"},
         "port 0", 400),
        ({"host": 123, "port": 1001, "username": "u", "password": "p",
          "enabled": False}, "host non-string coerced to str", 200),
    ]:
        r = P(admin, "/api/sk5", IP_ADMIN, json=body)
        if want == "HONEST500":
            # sandbox has no real sing-box daemon/policy routing: enable must
            # fail honestly (500 + error naming the cause). Success path is
            # covered by gate B1 (alive stub + policy double).
            cell(f"F2-07 sk5 {label} -> honest 500",
                 r.status_code == 500 and "sing-box" in str(r.get_json()),
                 f"{r.status_code} {str(r.get_json())[:100]}")
        else:
            cell(f"F2-07 sk5 {label} -> {want}", r.status_code == want,
                 f"{r.status_code} {str(r.get_json())[:80]}")
    r = P(admin, "/api/sk5/udp-over-tcp", IP_ADMIN, json={"udp_over_tcp": True})
    cell("F2-08 udp-over-tcp true 200", r.status_code == 200, f"{r.status_code} {str(r.get_json())[:80]}")
    r = P(admin, "/api/sk5/udp-over-tcp", IP_ADMIN, json={"udp_over_tcp": "true"})
    cell("F2-09 udp-over-tcp str true 400", r.status_code == 400, str(r.status_code))
    r = P(admin, "/api/sk5/udp-over-tcp", IP_ADMIN, json={"enabled": True})
    cell("F2-10 udp-over-tcp fallback enabled (no udp_over_tcp key)",
         r.status_code in (200, 400), f"{r.status_code} {str(r.get_json())[:80]}")
    r = P(admin, "/api/sk5/fail-open", IP_ADMIN, json={"fail_open": "false"})
    cell("F2-11 fail-open str false 400", r.status_code == 400, str(r.status_code))
    r = P(admin, "/api/openvpn/init-pki", IP_ADMIN, json={})
    cell("F2-12 init-pki no force/confirm 400", r.status_code == 400, str(r.status_code))
    r = P(admin, "/api/openvpn/init-pki", IP_ADMIN, json={"force": True})
    cell("F2-13 init-pki force only 400", r.status_code == 400, str(r.status_code))
    r = P(admin, "/api/openvpn/init-pki", IP_ADMIN, json={"force": "true", "confirm": True})
    cell("F2-14 init-pki force str 400", r.status_code == 400, str(r.status_code))

    # ---------- F3 node register + cmd lifecycle ----------
    r = P(admin, "/api/nodes", IP_ADMIN, json={"name": "node1", "panel_url": ""})
    cell("F3-01 register node 201 + token once", r.status_code in (200, 201) and
         bool(r.get_json().get("token")), f"{r.status_code} {str(r.get_json())[:60]}")
    token = r.get_json().get("token")
    r = G(admin, "/api/nodes", IP_ADMIN)
    cell("F3-02 node list has no token", "token" not in json.dumps(r.get_json()),
         str(r.get_json())[:120])
    r = P(admin, "/api/cmd", IP_ADMIN, json={"node": "node1", "action": "get_status", "params": {}})
    cell("F3-03 enqueue get_status 202", r.status_code == 202 and bool(r.get_json().get("cmd_id")),
         f"{r.status_code} {str(r.get_json())[:80]}")
    cmd_id = r.get_json().get("cmd_id")
    r = P(c, "/api/agent/poll", IP_AGENT, json={"node_token": token, "node_name": "node1",
                                                "panel_url": "http://localhost"},
          headers={"Authorization": "Bearer " + token})
    cmds = r.get_json().get("commands", [])
    cell("F3-04 agent poll gets the command", r.status_code == 200 and
         any(x.get("id") == cmd_id for x in cmds), f"{r.status_code} {str(r.get_json())[:100]}")
    r = P(c, "/api/agent/report", IP_AGENT, json={"node_token": token, "node_name": "node1",
                                                  "id": cmd_id, "ok": True,
                                                  "result": {"openvpn": {"running": False}}},
          headers={"Authorization": "Bearer " + token})
    cell("F3-05 agent report 200", r.status_code == 200, f"{r.status_code} {str(r.get_json())[:80]}")
    r = G(admin, f"/api/cmd/{cmd_id}", IP_ADMIN)
    cell("F3-06 cmd done after report", r.get_json().get("status") == "done",
         str(r.get_json())[:120])
    r = P(admin, "/api/cmd", IP_ADMIN, json={"node": "ghost", "action": "get_status", "params": {}})
    cell("F3-07 enqueue ghost node 404", r.status_code == 404, str(r.status_code))
    r = G(admin, "/api/cmd/nonexistent-id", IP_ADMIN)
    cell("F3-08 cmd_get unknown id 404", r.status_code == 404, str(r.status_code))
    r = P(c, "/api/agent/poll", IP_AGENT, json={"node_token": "bad", "node_name": "node1"},
          headers={"Authorization": "Bearer bad"})
    cell("F3-09 poll bad token 401", r.status_code == 401, str(r.status_code))
    r = P(c, "/api/agent/poll", IP_AGENT, json={"node_token": token, "node_name": "other"},
          headers={"Authorization": "Bearer " + token})
    cell("F3-10 poll token/name mismatch 401", r.status_code == 401, str(r.status_code))
    r = P(c, "/api/agent/poll", IP_AGENT, json={"node_name": "node1"})
    cell("F3-11 poll no token 401", r.status_code == 401, str(r.status_code))
    r = P(admin, "/api/nodes", IP_ADMIN, json={"name": "node2", "panel_url": "https://panel-a:8443"})
    token2 = r.get_json().get("token")
    r = P(c, "/api/agent/poll", IP_AGENT, json={"node_token": token2, "node_name": "node2",
                                                "panel_url": "https://panel-b:8443"},
          headers={"Authorization": "Bearer " + token2})
    cell("F3-12 poll panel_url mismatch 403", r.status_code == 403, f"{r.status_code} {str(r.get_json())[:80]}")
    r = P(admin, "/api/cmd", IP_ADMIN, json={"node": "node1", "action": "rm_rf", "params": {}})
    cell("F3-13 enqueue unknown action 400", r.status_code == 400, str(r.status_code))
    r = P(admin, "/api/cmd", IP_ADMIN, json={"node": "node1", "action": "get_status", "params": []})
    cell("F3-14 enqueue list params 400", r.status_code == 400, str(r.status_code))

    # ---------- F4 malformed queue entries (R12-P1-1 / R14-P2-1) ----------
    qpath = Path(panel.AGENT_QUEUE_PATH)
    def write_queue(state):
        qpath.write_text(json.dumps(state), encoding="utf-8")
        os.chmod(qpath, 0o600)
    def audit_has(action):
        r = G(admin, "/api/audit?limit=500", IP_ADMIN)
        try:
            rows = r.get_json().get("rows", r.get_json().get("audit", []))
        except Exception:
            return False
        return any(action in json.dumps(row) for row in rows)
    now = panel._utcnow_iso()
    write_queue({"queue": {"node1": ["c-bad1", "c-bad2", "c-bad3", "c-good"]}, "cmds": {
        "c-bad1": "not-an-object",
        "c-bad2": {"id": "c-bad2", "node": "node1", "action": "get_status"},
        "c-bad3": {"id": "c-bad3", "node": "node1", "action": "get_status",
                   "params": {}, "status": "sent", "sent_at": "garbage",
                   "created_at": now, "retries": 0},
        "c-good": {"id": "c-good", "node": "node1", "action": "get_status",
                   "params": {}, "status": "queued", "created_at": now, "retries": 0}},
        "ovpn": {"node1:alice": "not-an-object"}})
    r = P(c, "/api/agent/poll", IP_AGENT, json={"node_token": token, "node_name": "node1"},
          headers={"Authorization": "Bearer " + token})
    cell("F4-01 poll with malformed queue no 500", r.status_code == 200,
         f"{r.status_code} {str(r.get_json())[:100]}")
    cmds = r.get_json().get("commands", []) if r.status_code == 200 else []
    ids = [x.get("id") for x in cmds]
    cell("F4-02a poll returns the good command", "c-good" in ids, str(ids))
    cell("F4-02b OBSERVED: poll ALSO dispatches failed-marked c-bad2/c-bad3 (R17-P1-1)",
         "c-bad2" in ids and "c-bad3" in ids, str(ids))
    r = G(admin, "/api/cmd/c-bad2", IP_ADMIN)
    cell("F4-03 missing-keys cmd marked failed", r.get_json().get("status") == "failed",
         str(r.get_json())[:120])
    r = G(admin, "/api/cmd/c-bad3", IP_ADMIN)
    cell("F4-04 garbage sent_at cmd marked failed (R13-P2-1)",
         r.get_json().get("status") == "failed", str(r.get_json())[:120])
    r = G(admin, "/api/cmd/c-bad1", IP_ADMIN)
    cell("F4-05 non-object cmd gone (404)", r.status_code == 404, str(r.status_code))
    cell("F4-06 malformed audit rows exist", audit_has("queue_cmd_malformed") or
         audit_has("queue_ovpn_malformed"), "audit search")
    write_queue({"queue": {"node1": "not-a-list"}, "cmds": {}, "ovpn": {}})
    r = P(admin, "/api/cmd", IP_ADMIN, json={"node": "node1", "action": "get_status", "params": {}})
    cell("F4-07 enqueue with non-list queue value 202 (no 500)",
         r.status_code == 202, f"{r.status_code} {str(r.get_json())[:100]}")
    write_queue({"queue": {"node1": ["c-bad4"]}, "cmds": {
        "c-bad4": {"id": "c-bad4", "node": "node1", "action": "get_status",
                   "params": {}, "status": "sent", "sent_at": None,
                   "created_at": now, "retries": 0}}, "ovpn": {}})
    r = P(c, "/api/agent/poll", IP_AGENT, json={"node_token": token, "node_name": "node1"},
          headers={"Authorization": "Bearer " + token})
    cell("F4-08 poll with sent_at=None sent cmd no 500", r.status_code == 200, str(r.status_code))
    r = G(admin, "/api/cmd/c-bad4", IP_ADMIN)
    cell("F4-09 sent_at=None sent cmd marked failed", r.get_json().get("status") == "failed",
         str(r.get_json())[:120])
    qpath.write_text("{not json", encoding="utf-8")
    r = G(admin, "/api/status", IP_ADMIN)
    cell("F4-10 corrupt queue file: status still 200", r.status_code == 200, str(r.status_code))
    r = P(c, "/api/agent/poll", IP_AGENT, json={"node_token": token, "node_name": "node1"},
          headers={"Authorization": "Bearer " + token})
    cell("F4-11 poll with corrupt queue file no 500", r.status_code == 200, str(r.status_code))
    cell("F4-12 corrupt queue quarantined to .corrupt.*",
         len(list(qpath.parent.glob("agent_queue.json.corrupt.*"))) >= 1, "")

    # F4-13: malformed init_pki (status missing, params valid force+confirm)
    write_queue({"queue": {"node1": ["c-nuke"]}, "cmds": {
        "c-nuke": {"id": "c-nuke", "node": "node1", "action": "init_pki",
                   "params": {"force": True, "confirm": True},
                   "created_at": now, "retries": 0}}, "ovpn": {}})
    r = P(c, "/api/agent/poll", IP_AGENT, json={"node_token": token, "node_name": "node1"},
          headers={"Authorization": "Bearer " + token})
    ids = [x.get("id") for x in r.get_json().get("commands", [])]
    cell("F4-13 OBSERVED: poll dispatches failed-marked init_pki (R17-P1-1)",
         "c-nuke" in ids, str(ids))
    r = G(admin, "/api/cmd/c-nuke", IP_ADMIN)
    cell("F4-14 init_pki cmd marked failed by sweep",
         r.get_json().get("status") == "failed", str(r.get_json())[:140])

    # F4-15/16: report-before-poll -- agent_report has no status guard
    # (only the malformed-entry check), so a queued cmd reported failed
    # keeps its queue entry and is dispatched by the next poll.
    r = P(admin, "/api/cmd", IP_ADMIN,
          json={"node": "node1", "action": "init_pki",
                "params": {"force": True, "confirm": True}})
    pre_id = (r.get_json() or {}).get("cmd_id")
    r = P(c, "/api/agent/report", IP_AGENT,
          json={"cmd_id": pre_id, "ok": False, "error": "stale report"},
          headers={"Authorization": "Bearer " + token})
    cell("F4-15 OBSERVED: Flask report on still-queued cmd accepted",
         r.status_code == 200 and (r.get_json() or {}).get("status") == "failed",
         f"{r.status_code} {str(r.get_json())[:100]}")
    r = P(c, "/api/agent/poll", IP_AGENT, json={"node_token": token, "node_name": "node1"},
          headers={"Authorization": "Bearer " + token})
    ids = [x.get("id") for x in r.get_json().get("commands", [])]
    cell("F4-16 OBSERVED: Flask poll dispatches report-failed init_pki",
         pre_id in ids, str(ids))

    # ---------- F5 download paths (R13-P2-3 / R14-P2-1) ----------
    r = G(admin, "/api/openvpn/users/alice/ovpn", IP_ADMIN)
    cell("F5-01 local download valid user 200", r.status_code == 200,
         f"{r.status_code} {str(r.data)[:60]}")
    r = G(admin, "/api/openvpn/users/bob/ovpn", IP_ADMIN)
    cell("F5-02 local download revoked user 403", r.status_code == 403, str(r.status_code))
    r = G(admin, "/api/openvpn/users/erin/ovpn", IP_ADMIN)
    cell("F5-03 local download expired-effective user 403", r.status_code == 403, str(r.status_code))
    r = G(admin, "/api/openvpn/users/carol/ovpn", IP_ADMIN)
    cell("F5-04 local download expired user 403", r.status_code == 403, str(r.status_code))
    r = G(admin, "/api/openvpn/users/nobody/ovpn", IP_ADMIN)
    cell("F5-05 local download unknown user 404", r.status_code == 404, str(r.status_code))
    snap = {"users": [{"name": "alice", "status": "valid"},
                      {"name": "bob", "status": "revoked"},
                      {"name": "erin", "status": "expired"},
                      {"name": "dave", "status": "valid"}],
            "openvpn": {"running": False}, "at": panel._utcnow_iso()}
    conn = panel._db()
    conn.execute("UPDATE nodes SET last_status = ? WHERE name = 'node1'",
                 (json.dumps(snap),))
    conn.commit(); conn.close()
    write_queue({"queue": {}, "cmds": {}, "ovpn": {
        "node1:alice": {"ovpn": "client alice-ovpn"},
        "node1:bob": {"ovpn": "client bob-ovpn"},
        "node1:erin": {"ovpn": "client erin-ovpn"},
        "node1:dave": {"ovpn": "client dave-ovpn"}}})
    r = G(admin, "/api/openvpn/users/alice/ovpn?node=node1", IP_ADMIN)
    cell("F5-06 ?node= download valid user 200", r.status_code == 200, str(r.status_code))
    r = G(admin, "/api/openvpn/users/bob/ovpn?node=node1", IP_ADMIN)
    cell("F5-07 ?node= download revoked user 403", r.status_code == 403, str(r.status_code))
    r = G(admin, "/api/openvpn/users/erin/ovpn?node=node1", IP_ADMIN)
    cell("F5-08 ?node= download expired user 403", r.status_code == 403, str(r.status_code))
    r = G(admin, "/api/nodes/node1/users/alice/ovpn", IP_ADMIN)
    cell("F5-09 dedicated download valid 200", r.status_code == 200, str(r.status_code))
    r = G(admin, "/api/nodes/node1/users/bob/ovpn", IP_ADMIN)
    cell("F5-10 dedicated download revoked 403", r.status_code == 403, str(r.status_code))
    r = G(admin, "/api/nodes/ghost/users/alice/ovpn", IP_ADMIN)
    cell("F5-11 dedicated download ghost node 404", r.status_code == 404, str(r.status_code))
    write_queue({"queue": {}, "cmds": {}, "ovpn": {"node1:alice": "not-an-object"}})
    r = G(admin, "/api/nodes/node1/users/alice/ovpn", IP_ADMIN)
    cell("F5-12 dedicated download non-object receipt 404 (no 500)",
         r.status_code == 404, str(r.status_code))
    write_queue({"queue": {"node1": ["c-x"]}, "cmds": {
        "c-x": {"id": "c-x", "node": "node1", "action": "get_status",
                "params": {}, "status": "queued", "created_at": now, "retries": 0},
        "c-y": "not-an-object"}, "ovpn": {}})
    r = D(admin, "/api/nodes/node1", IP_ADMIN)
    cell("F5-13 revoke node with malformed queue 200 (no 500)",
         r.status_code == 200, f"{r.status_code} {str(r.get_json())[:100]}")
    r = G(admin, "/api/cmd/c-x", IP_ADMIN)
    cell("F5-14 revoked node's queued cmd marked failed",
         r.status_code == 404 or r.get_json().get("status") == "failed",
         str(r.get_json())[:120])
    r = P(c, "/api/agent/poll", IP_AGENT, json={"node_token": token, "node_name": "node1"},
          headers={"Authorization": "Bearer " + token})
    cell("F5-15 poll after revoke 401", r.status_code == 401, str(r.status_code))

    # ---------- F6 compat node resolution (R11-P1-1) ----------
    r = P(admin, "/api/nodes", IP_ADMIN, json={"name": "node3", "panel_url": ""})
    token3 = r.get_json().get("token")
    r = P(admin, "/api/openvpn/server?node=ghost", IP_ADMIN, json={"proto": "udp"})
    cell("F6-01 compat ghost node 404", r.status_code == 404, str(r.status_code))
    r = P(admin, "/api/openvpn/server", IP_ADMIN, json={"proto": "udp", "node": "node3"})
    cell("F6-02 compat named node enqueues 202", r.status_code == 202,
         f"{r.status_code} {str(r.get_json())[:100]}")
    r = G(admin, "/api/status?node=node3", IP_ADMIN)
    cell("F6-03 compat status named node serves snapshot (no local leak)",
         r.status_code == 200 and r.get_json().get("node") == "node3",
         f"{r.status_code} {str(r.get_json())[:120]}")
    html = (TREE / "panel" / "templates" / "index.html").read_text()
    cell("F6-04 index.html download href uses withNode", "withNode(" in html and
         "dl.href" in html, "")

    fails = [n for n, ok, _ in RESULTS if not ok]
    print(f"\nTOTAL {len(RESULTS)} cells, FAIL {len(fails)}: {fails}")
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())

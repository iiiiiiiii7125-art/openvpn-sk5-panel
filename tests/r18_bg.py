#!/usr/bin/env python3
"""Fix BG probe (r18_bg.py) — R17-P1-1 Flask face: poll must only dispatch
queued commands; agent_report must only accept receipts for sent commands.

Drives panel/app.py through Flask test_client (real code paths, no
monkeypatch except env isolation). Run as nobody with PYTHONPATH=venv
site-packages, against a /tmp copy of the tree:

  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    BG_TREE=/tmp/r18-bg/ptree OVPN_PANEL_DATA_DIR=<data> \\
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OPENVPN_CA_DIR=/tmp/r17/fixture-ca OPENVPN_SERVER_DIR=/tmp/r17/fixture-server \\
    OVPN_SK5_CONFIG_DIR=<sk5cfg> python3 tests/r18_bg.py

Cells BG-01..BG-11; exit code = number of FAILs (0 = all green).
Pre-fix baseline (unfixed tree): BG-01, BG-02, BG-03, BG-04, BG-08, BG-10
fail — the bug. Post-fix all green.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

TREE = Path(os.environ.get("BG_TREE", "/tmp/r18-bg/ptree"))
sys.path.insert(0, str(TREE / "panel"))
sys.path.insert(0, str(TREE / "core"))
sys.path.insert(0, str(TREE / "egress"))

import app as panel  # noqa: E402

RESULTS = []
IP_ADMIN = "10.0.0.22"
IP_AGENT = "10.0.0.23"


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""))


def G(c, url, ip, **kw):
    return c.get(url, environ_base={"REMOTE_ADDR": ip}, **kw)


def P(c, url, ip, **kw):
    return c.post(url, environ_base={"REMOTE_ADDR": ip}, **kw)


def poll(c, token):
    r = P(c, "/api/agent/poll", IP_AGENT,
          json={"node_token": token, "node_name": "node1"},
          headers={"Authorization": "Bearer " + token})
    assert r.status_code == 200, f"poll {r.status_code} {r.get_data(as_text=True)[:200]}"
    return [x.get("id") for x in r.get_json().get("commands", [])]


def report(c, token, cmd_id, ok, error=None):
    body = {"cmd_id": cmd_id, "ok": ok}
    if error:
        body["error"] = error
    return P(c, "/api/agent/report", IP_AGENT, json=body,
             headers={"Authorization": "Bearer " + token})


def cmd_status(admin, cmd_id):
    r = G(admin, f"/api/cmd/{cmd_id}", IP_ADMIN)
    return r.status_code, (r.get_json() or {}).get("status")


def main():
    pw = panel._ensure_admin_password()
    assert pw, "admin password not generated"
    c = panel.app.test_client()
    admin = panel.app.test_client()
    r = P(admin, "/api/login", IP_ADMIN, json={"password": pw})
    assert r.status_code == 200, f"login {r.status_code}"
    r = P(admin, "/api/nodes", IP_ADMIN, json={"name": "node1", "panel_url": ""})
    assert r.status_code in (200, 201), f"register {r.status_code} {r.get_data(as_text=True)[:200]}"
    token = r.get_json().get("token")
    assert token, "no token issued"

    qpath = Path(panel.AGENT_QUEUE_PATH)
    now = panel._utcnow_iso()
    old = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()

    def write_queue(state):
        qpath.write_text(json.dumps(state), encoding="utf-8")
        os.chmod(qpath, 0o600)

    # ---------- (a) sweep-failed init_pki must NOT be dispatched ----------
    write_queue({"queue": {"node1": ["c-nuke"]}, "cmds": {
        "c-nuke": {"id": "c-nuke", "node": "node1", "action": "init_pki",
                   "params": {"force": True, "confirm": True},
                   "created_at": now, "retries": 0}}, "ovpn": {}})
    ids = poll(c, token)
    cell("BG-01 sweep-failed init_pki not dispatched",
         "c-nuke" not in ids, str(ids))
    cell("BG-01b sweep-failed init_pki still failed",
         cmd_status(admin, "c-nuke")[1] == "failed",
         str(cmd_status(admin, "c-nuke")))

    # ---------- (a2) already-failed command must NOT be dispatched ----------
    write_queue({"queue": {"node1": ["c-failed"]}, "cmds": {
        "c-failed": {"id": "c-failed", "node": "node1", "action": "get_status",
                     "params": {}, "status": "failed", "error": "boom",
                     "created_at": now, "retries": 0}}, "ovpn": {}})
    ids = poll(c, token)
    cell("BG-02 failed-marked cmd not dispatched",
         "c-failed" not in ids, str(ids))
    cell("BG-02b failed-marked cmd stays failed",
         cmd_status(admin, "c-failed")[1] == "failed",
         str(cmd_status(admin, "c-failed")))

    # ---------- (a3) fresh sent command must NOT be re-dispatched ----------
    write_queue({"queue": {"node1": ["c-sent"]}, "cmds": {
        "c-sent": {"id": "c-sent", "node": "node1", "action": "get_status",
                   "params": {}, "status": "sent", "sent_at": now,
                   "created_at": now, "retries": 0}}, "ovpn": {}})
    ids = poll(c, token)
    cell("BG-03 fresh sent cmd not re-dispatched",
         "c-sent" not in ids, str(ids))
    cell("BG-03b fresh sent cmd stays sent",
         cmd_status(admin, "c-sent")[1] == "sent",
         str(cmd_status(admin, "c-sent")))

    # ---------- (b) report on a still-queued cmd must be rejected ----------
    r = P(admin, "/api/cmd", IP_ADMIN,
          json={"node": "node1", "action": "init_pki",
                "params": {"force": True, "confirm": True}})
    assert r.status_code == 202, f"enqueue {r.status_code}"
    pre_id = (r.get_json() or {}).get("cmd_id")
    r = report(c, token, pre_id, False, "stale report")
    cell("BG-04 report on queued cmd rejected 409",
         r.status_code == 409, f"{r.status_code} {str(r.get_json())[:100]}")
    cell("BG-04b queued cmd stays queued after rejected report",
         cmd_status(admin, pre_id)[1] == "queued",
         str(cmd_status(admin, pre_id)))
    ids = poll(c, token)
    cell("BG-05 still-queued cmd IS dispatched (legitimate)",
         pre_id in ids, str(ids))
    cell("BG-05b dispatched cmd flips to sent",
         cmd_status(admin, pre_id)[1] == "sent",
         str(cmd_status(admin, pre_id)))

    # ---------- (c) normal queued dispatch: once, sent, sent_at set ----------
    r = P(admin, "/api/cmd", IP_ADMIN,
          json={"node": "node1", "action": "get_status", "params": {}})
    gid = (r.get_json() or {}).get("cmd_id")
    ids = poll(c, token)
    cell("BG-06 normal queued cmd dispatched once", gid in ids, str(ids))
    st = panel._load_queue()["cmds"][gid]
    cell("BG-06b dispatched cmd sent + sent_at set",
         st.get("status") == "sent" and bool(st.get("sent_at")), str(st))
    ids = poll(c, token)
    cell("BG-06c second poll empty (no re-dispatch)", ids == [], str(ids))

    # ---------- (d) stale sent requeue still works ----------
    write_queue({"queue": {"node1": ["c-old"]}, "cmds": {
        "c-old": {"id": "c-old", "node": "node1", "action": "get_status",
                  "params": {}, "status": "sent", "sent_at": old,
                  "created_at": now, "retries": 0}}, "ovpn": {}})
    ids = poll(c, token)
    st = panel._load_queue()["cmds"]["c-old"]
    cell("BG-07 stale sent cmd requeued + dispatched",
         "c-old" in ids and st.get("status") == "sent" and st.get("retries") == 1,
         f"{ids} {st}")

    # ---------- (d2) stale sent past retry cap -> failed, NOT dispatched ----------
    write_queue({"queue": {"node1": ["c-dead"]}, "cmds": {
        "c-dead": {"id": "c-dead", "node": "node1", "action": "init_pki",
                   "params": {"force": True, "confirm": True},
                   "status": "sent", "sent_at": old,
                   "created_at": now, "retries": 3}}, "ovpn": {}})
    ids = poll(c, token)
    cell("BG-08 retry-exhausted cmd not dispatched",
         "c-dead" not in ids, str(ids))
    cell("BG-08b retry-exhausted cmd marked failed",
         cmd_status(admin, "c-dead")[1] == "failed",
         str(cmd_status(admin, "c-dead")))

    # ---------- (e) normal report flow: sent -> done / failed ----------
    r = P(admin, "/api/cmd", IP_ADMIN,
          json={"node": "node1", "action": "get_status", "params": {}})
    d1 = (r.get_json() or {}).get("cmd_id")
    poll(c, token)
    r = report(c, token, d1, True, None)
    cell("BG-09 report ok:true on sent cmd 200 done",
         r.status_code == 200 and (r.get_json() or {}).get("status") == "done",
         f"{r.status_code} {str(r.get_json())[:80]}")
    r = P(admin, "/api/cmd", IP_ADMIN,
          json={"node": "node1", "action": "get_status", "params": {}})
    d2 = (r.get_json() or {}).get("cmd_id")
    poll(c, token)
    r = report(c, token, d2, False, "agent boom")
    cell("BG-09b report ok:false on sent cmd 200 failed",
         r.status_code == 200 and (r.get_json() or {}).get("status") == "failed",
         f"{r.status_code} {str(r.get_json())[:80]}")

    # ---------- (e2) duplicate report on done cmd rejected ----------
    r = report(c, token, d1, True, None)
    cell("BG-10 duplicate report on done cmd rejected 409",
         r.status_code == 409, f"{r.status_code} {str(r.get_json())[:80]}")
    cell("BG-10b done cmd stays done after duplicate report",
         cmd_status(admin, d1)[1] == "done", str(cmd_status(admin, d1)))

    # ---------- guards: heartbeat + unknown id ----------
    r = P(c, "/api/agent/report", IP_AGENT, json={},
          headers={"Authorization": "Bearer " + token})
    cell("BG-11 heartbeat (no cmd_id) still 200",
         r.status_code == 200 and (r.get_json() or {}).get("heartbeat") is True,
         f"{r.status_code} {str(r.get_json())[:80]}")
    r = report(c, token, "no-such-id", True, None)
    cell("BG-11b report unknown id 404",
         r.status_code == 404, str(r.status_code))

    fails = [n for n, ok, _ in RESULTS if not ok]
    print(f"\nTOTAL {len(RESULTS)} cells, FAIL {len(fails)}: {fails}")
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())

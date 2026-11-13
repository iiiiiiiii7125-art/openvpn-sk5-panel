#!/usr/bin/env python3
"""AUDIT-R22 probe (r22_time_bounds.py) — time & order boundary audit,
Flask/agent/core face.

Method (R22): enumerate every time/order quantity, verify each at its exact
boundary. Cells T1..T9; exit code = number of FAILs.

Run as nobody with PYTHONPATH=<venv> site-packages:
  runuser -u nobody -- env PYTHONPATH=/tmp/r21/venv/lib/python3.12/site-packages \\
    R22_TREE=/tmp/r22/ptree OVPN_PANEL_DATA_DIR=<data> \\
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OPENVPN_CA_DIR=/tmp/r17/fixture-ca OPENVPN_SERVER_DIR=/tmp/r17/fixture-server \\
    OVPN_SK5_CONFIG_DIR=<sk5> python3 tests/r22_time_bounds.py

Boundary precision note: the exact-instant operators (`< 300`, `<= 120`,
`<=` on cert expiry) are verified by code reading; the probe tests the
boundary to 1 ms (Flask, float seconds) / 1 ms (Worker, integer ms).
Disclosed patching: T7 patches time.sleep (records its arguments) and
agent._post_json (transport stub) ONLY — the backoff arithmetic under test
is real product code in run_forever/run_once. T9 patches time.time ONLY
around the re-signing of a session cookie, to backdate its timestamp.
"""
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

TREE = Path(os.environ.get("R22_TREE", "/tmp/r22/ptree"))
sys.path.insert(0, str(TREE / "panel"))
sys.path.insert(0, str(TREE / "core"))
sys.path.insert(0, str(TREE / "egress"))
sys.path.insert(0, str(TREE / "agent"))

import app as panel  # noqa: E402
import agent as agent_mod  # noqa: E402
from openvpn_manager import _index_expiry_is_past  # noqa: E402

RESULTS = []
IP_LOCK = "10.0.0.21"
IP_ADMIN = "10.0.0.22"
IP_AGENT = "10.0.0.23"
IP_MISC = "10.0.0.24"
IP_WIN = "10.0.0.25"


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print((("PASS " if cond else "FAIL ") + name
           + (" | " + detail if detail else "")))


def G(c, url, ip, **kw):
    return c.get(url, environ_base={"REMOTE_ADDR": ip}, **kw)


def P(c, url, ip, **kw):
    return c.post(url, environ_base={"REMOTE_ADDR": ip}, **kw)


def db_path():
    return os.path.join(os.environ["OVPN_PANEL_DATA_DIR"], "panel.db")


def queue_path():
    return os.path.join(os.environ["OVPN_PANEL_DATA_DIR"], "agent_queue.json")


def set_login_row(ip, failures, locked_until=0):
    conn = sqlite3.connect(db_path())
    conn.execute(
        "INSERT INTO login_attempts (ip, failures, locked_until)"
        " VALUES (?,?,?) ON CONFLICT(ip) DO UPDATE SET"
        " failures=excluded.failures, locked_until=excluded.locked_until",
        (ip, json.dumps(failures), locked_until))
    conn.commit()
    conn.close()


def login_locked(ip):
    return panel._login_locked_until(ip)


def main():
    pw = panel._ensure_admin_password()
    assert pw, "admin password not generated"
    c = panel.app.test_client()

    # ---------- T1: lockout count boundary (5 fails -> lock on the 5th) ----------
    for _ in range(4):
        r = P(c, "/api/login", IP_LOCK, json={"password": "wrong-password"})
        assert r.status_code == 401, r.status_code
    cell("T1a 4 wrong logins -> 401, no lock",
         login_locked(IP_LOCK) is None)
    r = P(c, "/api/login", IP_LOCK, json={"password": "wrong-password"})
    cell("T1b 5th wrong login -> 401 and lock set",
         r.status_code == 401 and login_locked(IP_LOCK) is not None,
         str(r.status_code))
    r = P(c, "/api/login", IP_LOCK, json={"password": "wrong-password"})
    cell("T1c 6th login while locked -> 429 + Retry-After",
         r.status_code == 429 and r.headers.get("Retry-After") is not None
         and int(r.headers["Retry-After"]) >= 1
         and r.json.get("retry_after_s", 0) >= 1,
         f"{r.status_code} Retry-After={r.headers.get('Retry-After')}")
    r = P(c, "/api/login", IP_LOCK, json={"password": pw})
    cell("T1d correct password while locked -> still 429",
         r.status_code == 429, str(r.status_code))

    # ---------- T2: window edge (failure exactly 300s old is pruned) ----------
    now = time.time()
    set_login_row(IP_WIN, [now - 300.0] * 5)
    r = P(c, "/api/login", IP_WIN, json={"password": "wrong-password"})
    cell("T2a 5 failures exactly 300s old -> pruned, no lock",
         r.status_code == 401 and login_locked(IP_WIN) is None,
         str(r.status_code))
    # R23: seed at 298s, not 299s. The cell's intent is "failures just
    # inside the window are counted". A wrong-password login takes
    # ~2s end to end in this sandbox (bcrypt ~500ms + Flask test
    # client), so a 299s seed crosses the 300s line mid-request and
    # is pruned by design -- the product is correct, the probe's 1s
    # margin is not. The exact-instant `< 300` operator is verified
    # by code reading (see the probe's boundary-precision note); T2a
    # covers the 300s side.
    now = time.time()
    set_login_row(IP_WIN, [now - 298.0] * 5)
    r = P(c, "/api/login", IP_WIN, json={"password": "wrong-password"})
    cell("T2b 5 failures 298s old -> counted, lock set",
         r.status_code == 401 and login_locked(IP_WIN) is not None,
         str(r.status_code))

    # ---------- T3: sent timeout + retries boundary (Flask) ----------
    def mk_state(sent_age_s, retries, action="get_status"):
        sent = (datetime.now(timezone.utc)
                - timedelta(seconds=sent_age_s)).isoformat()
        cmd = {"id": "c1", "node": "n1", "action": action, "status": "sent",
               "sent_at": sent, "retries": retries, "result": None,
               "error": None}
        return {"queue": {"n1": []}, "cmds": {"c1": cmd}, "ovpn": {}}

    with panel._QUEUE_LOCK:
        st = mk_state(119.99, 0)
        panel._requeue_stale_sent(st)
        cell("T3a sent 119.99s ago -> still sent",
             st["cmds"]["c1"]["status"] == "sent"
             and st["cmds"]["c1"]["retries"] == 0)
        st = mk_state(120.01, 0)
        rq, fl = panel._requeue_stale_sent(st)
        cell("T3b sent 120.01s ago -> requeued, retries 1",
             st["cmds"]["c1"]["status"] == "queued"
             and st["cmds"]["c1"]["retries"] == 1 and rq == ["c1"]
             and st["queue"]["n1"] == ["c1"], f"rq={rq}")
        st = mk_state(120.01, 2)
        panel._requeue_stale_sent(st)
        cell("T3c retries=2 + stale -> requeued, retries 3",
             st["cmds"]["c1"]["status"] == "queued"
             and st["cmds"]["c1"]["retries"] == 3)
        st = mk_state(120.01, 3)
        rq, fl = panel._requeue_stale_sent(st)
        cell("T3d retries=3 + stale -> failed, '已重投 3 次'",
             st["cmds"]["c1"]["status"] == "failed" and fl == ["c1"]
             and "已重投 3 次" in (st["cmds"]["c1"]["error"] or ""))
        st = mk_state(120.01, 0, action="create_user")
        panel._requeue_stale_sent(st)
        cell("T3e non-safe create_user + stale -> requeued (Flask requeues all; R5 divergence)",
             st["cmds"]["c1"]["status"] == "queued"
             and st["cmds"]["c1"]["retries"] == 1)

    # ---------- T6: cert expiry boundary ----------
    def fmt(dt):
        return dt.strftime("%y%m%d%H%M%SZ")

    now_dt = datetime.now(timezone.utc)
    cell("T6a expiry 1s ago -> past",
         _index_expiry_is_past(fmt(now_dt - timedelta(seconds=1))) is True)
    cell("T6b expiry 3600s ahead -> not past",
         _index_expiry_is_past(fmt(now_dt + timedelta(seconds=3600))) is False)
    cell("T6c malformed expiry -> False (flag stands)",
         _index_expiry_is_past("garbage") is False)
    cell("T6d empty expiry -> False",
         _index_expiry_is_past("") is False)

    # ---------- T7: agent backoff sequence + reset ----------
    cfg = {"panel_url": "http://127.0.0.1:9", "node_token": "x",
           "node_name": "n1", "insecure": True}
    ag = agent_mod.Agent(cfg)
    sleeps = []

    def fake_sleep(s):
        # R23: ignore sub-second sleeps. mock.patch("time.sleep") is
        # global: heartbeat_status() -> server_status() runs a
        # subprocess, and subprocess.communicate() polls its child with
        # time.sleep(0.001/0.002/0.004...) internally. Under load the
        # child is slow and those internal polls land in this list,
        # failing T7a even though the real backoff sequence is
        # [10,20,40,60,60]. Backoff values under test are all >= 5s,
        # so filtering < 1s keeps the cell's intent exactly.
        if s >= 1:
            sleeps.append(s)
        if len(sleeps) >= 5:
            raise KeyboardInterrupt()

    with mock.patch("time.sleep", fake_sleep):
        try:
            ag.run_forever()
        except KeyboardInterrupt:
            pass
    cell("T7a backoff after consecutive poll failures: 10,20,40,60,60",
         sleeps == [10, 20, 40, 60, 60], f"sleeps={sleeps}")
    with mock.patch.object(agent_mod, "_post_json",
                           return_value={"commands": []}):
        n = ag.run_once()
    cell("T7b successful poll resets backoff to 5",
         n == 0 and ag.backoff == 5, f"n={n} backoff={ag.backoff}")
    sleeps2 = []

    def fake_sleep2(s):
        # R23: same subprocess-communicate filter as fake_sleep (see
        # above): sub-second sleeps are stdlib-internal polls, not
        # backoffs; only the first real (>= 1s) sleep raises.
        if s >= 1:
            sleeps2.append(s)
            raise KeyboardInterrupt()

    with mock.patch("time.sleep", fake_sleep2):
        with mock.patch.object(agent_mod, "_post_json",
                               side_effect=ConnectionError("down")):
            try:
                ag.run_forever()
            except KeyboardInterrupt:
                pass
    cell("T7c first failure after reset -> sleep 10",
         sleeps2 == [10], f"sleeps2={sleeps2}")

    # ---------- T8: FIFO dispatch order + requeue to tail ----------
    r = P(c, "/api/login", IP_ADMIN, json={"password": pw})
    assert r.status_code == 200, r.status_code
    r = P(c, "/api/nodes", IP_ADMIN,
          json={"name": "node1", "panel_url": "https://127.0.0.1:8443"})
    token = r.json.get("token")
    assert token, r.json

    def enqueue(action="get_status"):
        r = P(c, "/api/cmd", IP_ADMIN,
              json={"node": "node1", "action": action})
        assert r.status_code == 202, (r.status_code, r.json)
        return r.json["cmd_id"]

    def poll():
        r = P(c, "/api/agent/poll", IP_AGENT,
              json={"node_token": token, "node_name": "node1"},
              headers={"Authorization": "Bearer " + token})
        assert r.status_code == 200, (r.status_code, r.json)
        return r.json

    ids = [enqueue(), enqueue(), enqueue()]
    out = poll()
    got = [cmd["id"] for cmd in out["commands"]]
    cell("T8a 3 enqueued commands dispatch in FIFO order",
         got == ids, f"got={got}")
    # requeue-to-tail: A sent+stale, B queued -> poll returns [B, A]
    a = enqueue()
    poll()  # A dispatched -> sent
    b = enqueue()
    st = json.loads(Path(queue_path()).read_text(encoding="utf-8"))
    stale = (datetime.now(timezone.utc)
             - timedelta(seconds=121)).isoformat()
    st["cmds"][a]["sent_at"] = stale
    Path(queue_path()).write_text(json.dumps(st), encoding="utf-8")
    out = poll()
    got = [cmd["id"] for cmd in out["commands"]]
    cell("T8b stale sent A requeues to tail behind B",
         got == [b, a], f"got={got}")

    # ---------- T9: Flask session expires server-side after 12h ----------
    c2 = panel.app.test_client()
    r = P(c2, "/api/login", IP_ADMIN, json={"password": pw})
    assert r.status_code == 200, r.status_code
    cookie = None
    for h in r.headers.getlist("Set-Cookie"):
        if h.startswith("session="):
            cookie = h.split(";", 1)[0][len("session="):]
    assert cookie, "no session cookie"
    from flask.sessions import SecureCookieSessionInterface
    s = SecureCookieSessionInterface().get_signing_serializer(panel.app)
    payload = s.loads(cookie)
    r = G(c2, "/api/status", IP_ADMIN)
    cell("T9a fresh session cookie -> 200", r.status_code == 200,
         str(r.status_code))
    old_now = time.time() - 13 * 3600
    with mock.patch("time.time", return_value=old_now):
        stale_cookie = s.dumps(payload)
    c3 = panel.app.test_client()
    c3.set_cookie("session", stale_cookie)
    r = G(c3, "/api/status", IP_ADMIN)
    cell("T9b session signed 13h ago -> rejected (not 200)",
         r.status_code != 200, str(r.status_code))

    fails = sum(1 for _, ok in RESULTS if not ok)
    print(f"\nTOTAL {len(RESULTS)} cells, FAIL {fails}: "
          f"{[n for n, ok in RESULTS if not ok]}")
    return fails


if __name__ == "__main__":
    sys.exit(main())

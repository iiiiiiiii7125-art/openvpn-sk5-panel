#!/usr/bin/env python3
"""Fix-P probe (r43_fix_p_queue_decode.py) — R43-J7-3: non-UTF8 bytes in
agent_queue.json must quarantine like any other corruption, not raise
an uncaught UnicodeDecodeError out of _load_queue (no backup, no audit
row, every queue op 500s until manual deletion).

Cells P1..P8 drive the real Flask panel (test_client, in-process) with
a fresh data dir + the R17-style fixture PKI:
  P1  poisoned queue (non-UTF8 bytes) -> poll 200, empty dispatch
  P2  .corrupt backup exists, byte-identical to the poisoned file
  P3  exactly one new quarantine audit row (failed, backup path +
      UTF-8 reason + 不可知 counts x3, no file content)
  P4  subsequent queue ops work: new enqueue 202, poll dispatches it
  P5  regression: invalid JSON still quarantines (one row, backup)
  P6  regression: top-level JSON list still quarantines (one row)
  P7  missing file is still the normal initial state (zero new rows)
  P8  valid queue loads unchanged (no quarantine, command dispatches)

On the baseline (2e08a8c) P1/P2/P3/P4 FAIL: _load_queue raises
UnicodeDecodeError, no backup, no audit row, poll 500s. P5..P8 pass
there as controls.

Run as nobody with PYTHONPATH=<venv> site-packages (see tests/README.md):
  runuser -u nobody -- env PYTHONPATH=/tmp/r41-l5-venv/lib/python3.12/site-packages \
    R43P_TREE=<tree> OVPN_PANEL_DATA_DIR=<fresh-data> \
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \
    OVPN_SK5_CONFIG_DIR=<fresh-sk5cfg> \
    python3 <tree>/tests/r43_fix_p_queue_decode.py
Exit code = number of FAILs.
"""
import glob
import json
import os
import sqlite3
import sys
from pathlib import Path

TREE = Path(os.environ.get("R43P_TREE", "/tmp/r43p/ptree"))
sys.path.insert(0, str(TREE / "panel"))
sys.path.insert(0, str(TREE / "core"))
sys.path.insert(0, str(TREE / "egress"))

import app as panel  # noqa: E402

RESULTS = []
IP_ADMIN = "10.0.0.31"
IP_AGENT = "10.0.0.32"


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (" | " + str(detail)[:300] if detail else ""))


def audit_rows():
    db = Path(panel.DB_PATH)
    con = sqlite3.connect(str(db))
    try:
        rows = con.execute("SELECT action, result, detail FROM audit_log").fetchall()
    finally:
        con.close()
    return rows


def quarantine_rows(rows):
    return [r for r in rows if r[0] == "queue_corrupt_quarantined"]


def main():
    pw = panel._ensure_admin_password()
    assert pw, "admin password not generated"
    c = panel.app.test_client()

    r = c.post("/api/login", json={"password": pw},
               environ_base={"REMOTE_ADDR": IP_ADMIN})
    assert r.status_code == 200, r.status_code
    hdr = {"Cookie": r.headers.get("Set-Cookie", "")}
    r = c.post("/api/nodes", json={"name": "qp1", "panel_url": ""},
               headers=hdr, environ_base={"REMOTE_ADDR": IP_ADMIN})
    assert r.status_code == 201, (r.status_code, r.data)
    token = r.json["token"]
    qpath = Path(panel.AGENT_QUEUE_PATH)

    # Healthy queue with one real command, for the poison + restore shape.
    r = c.post("/api/cmd", json={"node": "qp1", "action": "get_status"},
               headers=hdr, environ_base={"REMOTE_ADDR": IP_ADMIN})
    assert r.status_code == 202, (r.status_code, r.data)
    cmd_id = r.json["cmd_id"]

    # ---- P1: non-UTF8 bytes -> poll 200, empty dispatch (not 500) ----
    poisoned = b'{"queue": {"qp1": [{"id": "x"}]}, "cmds": {}, "ovpn": {}, \xff\xfe bad bytes'
    qpath.write_bytes(poisoned)
    n_base = len(quarantine_rows(audit_rows()))
    try:
        r = c.post("/api/agent/poll", json={"node_name": "qp1"},
                   headers={"Authorization": "Bearer " + token},
                   environ_base={"REMOTE_ADDR": IP_AGENT})
        poll_status, poll_json = r.status_code, r.json
    except Exception as exc:  # noqa: BLE001 - baseline raises here
        poll_status, poll_json = "EXC", {"error": repr(exc)}
    cell("P1 poll on non-UTF8 queue: 200, empty dispatch",
         poll_status == 200 and poll_json.get("commands") == [],
         f"{poll_status} {poll_json}")

    # ---- P2: .corrupt backup exists, byte-identical to the poisoned file ----
    backs = glob.glob(str(qpath) + ".corrupt.*")
    cell("P2 .corrupt backup exists, byte-identical to the poisoned file",
         len(backs) == 1 and Path(backs[0]).read_bytes() == poisoned,
         f"backs={backs}")

    # ---- P3: exactly one new quarantine audit row, honest detail ----
    rows = audit_rows()
    hits = quarantine_rows(rows)
    ok = len(hits) == n_base + 1
    detail = hits[-1][2] if hits else ""
    if ok:
        ok = (hits[-1][1] == "failed"
              and backs and Path(backs[0]).name in detail
              and "utf-8" in detail.lower()
              and detail.count("不可知") == 3
              and "bad bytes" not in detail)  # poisoned file's text must not leak
    cell("P3 exactly one new quarantine audit row (failed, backup path + "
         "UTF-8 reason + 不可知 counts, no file content)",
         ok, f"quarantine_rows={len(hits)} (was {n_base}) detail={detail!r}")

    # ---- P4: subsequent queue ops work after the quarantine ----
    r = c.post("/api/cmd", json={"node": "qp1", "action": "get_status"},
               headers=hdr, environ_base={"REMOTE_ADDR": IP_ADMIN})
    enq_ok = r.status_code == 202
    cmd2 = r.json.get("cmd_id") if enq_ok else None
    r = c.post("/api/agent/poll", json={"node_name": "qp1"},
               headers={"Authorization": "Bearer " + token},
               environ_base={"REMOTE_ADDR": IP_AGENT})
    got = [cmd.get("id") for cmd in r.json.get("commands", [])] \
        if r.status_code == 200 else []
    cell("P4 after quarantine: new enqueue 202, poll dispatches it",
         enq_ok and r.status_code == 200 and cmd2 in got,
         f"enq={enq_ok} poll={r.status_code} commands={got}")

    # ---- P5: regression — invalid JSON still quarantines ----
    n_before = len(quarantine_rows(audit_rows()))
    qpath.write_text("{not json", encoding="utf-8")
    r = c.post("/api/agent/poll", json={"node_name": "qp1"},
               headers={"Authorization": "Bearer " + token},
               environ_base={"REMOTE_ADDR": IP_AGENT})
    backs5 = glob.glob(str(qpath) + ".corrupt.*")
    cell("P5 invalid JSON still quarantines (poll 200, one new row)",
         r.status_code == 200 and r.json.get("commands") == []
         and len(quarantine_rows(audit_rows())) == n_before + 1
         and len(backs5) == len(backs) + 1,
         f"poll={r.status_code} backs={len(backs5)}")

    # ---- P6: regression — top-level JSON list still quarantines ----
    n_before = len(quarantine_rows(audit_rows()))
    qpath.write_text("[1, 2, 3]", encoding="utf-8")
    r = c.post("/api/agent/poll", json={"node_name": "qp1"},
               headers={"Authorization": "Bearer " + token},
               environ_base={"REMOTE_ADDR": IP_AGENT})
    backs6 = glob.glob(str(qpath) + ".corrupt.*")
    cell("P6 top-level JSON list still quarantines (poll 200, one new row)",
         r.status_code == 200 and r.json.get("commands") == []
         and len(quarantine_rows(audit_rows())) == n_before + 1
         and len(backs6) == len(backs5) + 1,
         f"poll={r.status_code} backs={len(backs6)}")

    # ---- P7: missing file is still the normal initial state ----
    n_before = len(quarantine_rows(audit_rows()))
    qpath.unlink()
    r = c.post("/api/agent/poll", json={"node_name": "qp1"},
               headers={"Authorization": "Bearer " + token},
               environ_base={"REMOTE_ADDR": IP_AGENT})
    cell("P7 missing queue file: poll 200, empty dispatch, zero new audit rows",
         r.status_code == 200 and r.json.get("commands") == []
         and len(quarantine_rows(audit_rows())) == n_before,
         f"poll={r.status_code}")

    # ---- P8: valid queue loads unchanged (no quarantine) ----
    r = c.post("/api/cmd", json={"node": "qp1", "action": "get_status"},
               headers=hdr, environ_base={"REMOTE_ADDR": IP_ADMIN})
    assert r.status_code == 202, (r.status_code, r.data)
    cmd3 = r.json["cmd_id"]
    n_before = len(quarantine_rows(audit_rows()))
    r = c.post("/api/agent/poll", json={"node_name": "qp1"},
               headers={"Authorization": "Bearer " + token},
               environ_base={"REMOTE_ADDR": IP_AGENT})
    got = [cmd.get("id") for cmd in r.json.get("commands", [])] \
        if r.status_code == 200 else []
    cell("P8 valid queue loads unchanged (no new row, command dispatches)",
         r.status_code == 200 and cmd3 in got
         and len(quarantine_rows(audit_rows())) == n_before,
         f"poll={r.status_code} commands={got}")

    print(f"\nTOTAL {len(RESULTS)} cells, FAIL {sum(1 for _, ok in RESULTS if not ok)}: "
          f"{[n for n, ok in RESULTS if not ok]}")
    return sum(1 for _, ok in RESULTS if not ok)


if __name__ == "__main__":
    sys.exit(main())

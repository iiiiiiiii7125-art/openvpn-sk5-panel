#!/usr/bin/env python3
"""AUDIT-R21 probe (r21_queue_quarantine.py) — whole-file queue corruption
propagation: does the panel honestly report the loss of queued commands,
or does it silently drop them?

R9-P2-1 (AK) fixed "corrupt queue file silently drops commands" by keeping
a `.corrupt` backup + a stderr WARNING. R10 verified only the backup
(byte-identical). This probe checks the OTHER half of that remedy — the
honest-report layer: after a whole-file corruption, is there ANY
panel-visible trace (audit row / API signal), or does cmd_get actively
misreport the lost command as "never existed" (404)?

Contrast cell: per-entry malformation (BA, R14) marks the entry failed +
writes an audit row. Whole-file corruption should do no less.

Run as nobody with PYTHONPATH=<venv> site-packages (see tests/README.md):
  runuser -u nobody -- env PYTHONPATH=/tmp/r21/venv/lib/python3.12/site-packages \
    R21_TREE=/tmp/r21/ptree OVPN_PANEL_DATA_DIR=<data> \
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \
    OPENVPN_CA_DIR=/tmp/r17/fixture-ca OPENVPN_SERVER_DIR=/tmp/r17/fixture-server \
    python3 tests/r21_queue_quarantine.py
Cells Q1..Q6; exit code = number of FAILs.
"""
import glob
import json
import os
import sqlite3
import sys
from pathlib import Path

TREE = Path(os.environ.get("R21_TREE", "/tmp/r21/ptree"))
sys.path.insert(0, str(TREE / "panel"))
sys.path.insert(0, str(TREE / "core"))
sys.path.insert(0, str(TREE / "egress"))

import app as panel  # noqa: E402

RESULTS = []
IP_ADMIN = "10.0.0.21"
IP_AGENT = "10.0.0.22"


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""))


def audit_rows():
    db = Path(panel.DB_PATH)
    con = sqlite3.connect(str(db))
    try:
        rows = con.execute("SELECT action, result, detail FROM audit_log").fetchall()
    finally:
        con.close()
    return rows


def main():
    pw = panel._ensure_admin_password()
    assert pw, "admin password not generated"
    c = panel.app.test_client()

    # Login as admin.
    r = c.post("/api/login", json={"password": pw},
               environ_base={"REMOTE_ADDR": IP_ADMIN})
    assert r.status_code == 200, r.status_code
    cookie = r.headers.get("Set-Cookie", "")
    hdr = {"Cookie": cookie}
    # Register a node, get its token.
    r = c.post("/api/nodes", json={"name": "qn1", "panel_url": ""},
               headers=hdr, environ_base={"REMOTE_ADDR": IP_ADMIN})
    assert r.status_code == 201, (r.status_code, r.data)
    token = r.json["token"]
    # Enqueue one command; capture its id.
    r = c.post("/api/cmd", json={"node": "qn1", "action": "get_status"},
               headers=hdr, environ_base={"REMOTE_ADDR": IP_ADMIN})
    assert r.status_code == 202, (r.status_code, r.data)
    cmd_id = r.json["cmd_id"]
    qpath = Path(panel.AGENT_QUEUE_PATH)
    good = qpath.read_text(encoding="utf-8")

    # ---- Q1: corrupt the whole file (invalid JSON) ----
    qpath.write_text("{not json,,,", encoding="utf-8")
    r = c.post("/api/agent/poll", json={"node_name": "qn1"},
               headers={"Authorization": "Bearer " + token},
               environ_base={"REMOTE_ADDR": IP_AGENT})
    cell("Q1 poll after whole-file corruption: 200, empty dispatch",
         r.status_code == 200 and r.json.get("commands") == [],
         f"{r.status_code} {r.json}")
    r = c.get(f"/api/cmd/{cmd_id}", headers=hdr,
              environ_base={"REMOTE_ADDR": IP_ADMIN})
    cell("Q2 cmd_get on the lost command: 404 'does not exist'",
         r.status_code == 404, f"{r.status_code} {r.json}")
    backs = glob.glob(str(qpath) + ".corrupt.*")
    cell("Q3 .corrupt backup exists, byte-identical to the damaged file",
         len(backs) == 1 and Path(backs[0]).read_text(encoding="utf-8") == "{not json,,,",
         f"backs={backs}")
    rows = audit_rows()
    hits = [row for row in rows if "quarant" in str(row).lower()
            or "corrupt" in str(row).lower()]
    cell("Q4 audit has a row about the quarantine (honest report)",
         len(hits) > 0, f"audit_rows={len(rows)} hits={hits}")
    n_q4 = len(hits)

    # ---- Q5: non-object queue section, same treatment? ----
    state = json.loads(good)
    state["queue"] = "not-a-dict"
    qpath.write_text(json.dumps(state), encoding="utf-8")
    r = c.post("/api/agent/poll", json={"node_name": "qn1"},
               headers={"Authorization": "Bearer " + token},
               environ_base={"REMOTE_ADDR": IP_AGENT})
    rows2 = audit_rows()
    hits2 = [row for row in rows2 if "quarant" in str(row).lower()
             or "corrupt" in str(row).lower()]
    # BN 修正（原断言累计为 0，与 Q4 的修复行互斥、修后永不可能成立）：
    # 该步应新增恰好一行隔离审计（段损坏与整文件损坏同待遇）。
    cell("Q5 non-object queue section: poll 200 and a new quarantine audit row",
         r.status_code == 200 and len(hits2) == n_q4 + 1,
         f"poll={r.status_code} quarantine_audit_rows={len(hits2)} (was {n_q4})")

    # ---- Q6 (contrast): per-entry malformation IS audited (BA) ----
    state = {"queue": {"qn1": ["bad1"]}, "cmds": {"bad1": "not-a-dict"}, "ovpn": {}}
    qpath.write_text(json.dumps(state), encoding="utf-8")
    r = c.post("/api/agent/poll", json={"node_name": "qn1"},
               headers={"Authorization": "Bearer " + token},
               environ_base={"REMOTE_ADDR": IP_AGENT})
    rows3 = audit_rows()
    hits3 = [row for row in rows3 if "malformed" in str(row[0]).lower()]
    cell("Q6 contrast: per-entry malformation writes an audit row",
         r.status_code == 200 and len(hits3) > 0,
         f"poll={r.status_code} malformed_rows={len(hits3)}")

    fails = sum(1 for _, ok in RESULTS if not ok)
    print(f"\nTOTAL {len(RESULTS)} cells, FAIL {fails}: "
          f"{[n for n, ok in RESULTS if not ok]}")
    return fails


if __name__ == "__main__":
    sys.exit(main())

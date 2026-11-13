#!/usr/bin/env python3
"""BQ probe (bq_queue_unreadable.py) — R23-P2-3: agent_queue.json exists
but is unreadable (chmod 000). The old code returned an empty queue on
any OSError and the caller's next _save_queue physically destroyed the
queued commands with zero audit trace (R23 probe R1: poll 200, enqueue
202, old cmd_get 404, 0 loss audit rows).

Fixed behavior (same BN family as the JSON-parse branch): an unreadable
queue file is quarantined to a `.corrupt.<stamp>` backup (rename, so the
bytes are preserved) + one `queue_corrupt_quarantined` audit row
(result=failed; detail = backup path + reason + loss counts, never file
content; counts honestly "不可知" since the file could not be read), and
only then does the panel continue with an empty queue. A missing file
stays the normal initial state (empty queue, zero audit rows). If the
quarantine rename itself fails, _load_queue raises loudly instead of
returning empty (fail-closed: no backup + empty write-back would be the
original silent destruction).

Run as nobody with PYTHONPATH=<venv> site-packages (see tests/README.md):
  runuser -u nobody -- env PYTHONPATH=/tmp/r21/venv/lib/python3.12/site-packages \
    BQ_TREE=/tmp/bq/ptree OVPN_PANEL_DATA_DIR=<data> \
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \
    OPENVPN_CA_DIR=/tmp/r17/fixture-ca OPENVPN_SERVER_DIR=/tmp/r17/fixture-server \
    OVPN_SK5_CONFIG_DIR=<sk5cfg> python3 tests/bq_queue_unreadable.py
Cells B1..B6; exit code = number of FAILs.
"""
import glob
import json
import os
import sqlite3
import sys
from pathlib import Path

TREE = Path(os.environ.get("BQ_TREE", "/tmp/bq/ptree"))
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
    r = c.post("/api/nodes", json={"name": "qn1", "panel_url": ""},
               headers=hdr, environ_base={"REMOTE_ADDR": IP_ADMIN})
    assert r.status_code == 201, (r.status_code, r.data)
    token = r.json["token"]
    r = c.post("/api/cmd", json={"node": "qn1", "action": "get_status"},
               headers=hdr, environ_base={"REMOTE_ADDR": IP_ADMIN})
    assert r.status_code == 202, (r.status_code, r.data)
    cmd_id = r.json["cmd_id"]
    qpath = Path(panel.AGENT_QUEUE_PATH)
    good = qpath.read_text(encoding="utf-8")
    n_base = len(quarantine_rows(audit_rows()))

    # ---- B1: queue file unreadable (chmod 000) -> poll 200, no dispatch ----
    os.chmod(qpath, 0)
    try:
        r = c.post("/api/agent/poll", json={"node_name": "qn1"},
                   headers={"Authorization": "Bearer " + token},
                   environ_base={"REMOTE_ADDR": IP_AGENT})
        poll_status, poll_json = r.status_code, r.json
    finally:
        # The unreadable file was renamed away by the quarantine; the
        # queue file now present is the fresh empty one _save_queue
        # wrote. chmod is a no-op safety net, not load-bearing.
        if qpath.exists():
            os.chmod(qpath, 0o600)
    cell("B1 poll on unreadable queue: 200, empty dispatch",
         poll_status == 200 and poll_json.get("commands") == [],
         f"{poll_status} {poll_json}")

    # ---- B2: the queued command is gone from the live queue (honest 404) ----
    r = c.get(f"/api/cmd/{cmd_id}", headers=hdr,
              environ_base={"REMOTE_ADDR": IP_ADMIN})
    cell("B2 cmd_get on the lost command: 404 'does not exist'",
         r.status_code == 404, f"{r.status_code} {r.json}")

    # ---- B3: .corrupt backup exists, byte-identical (commands preserved) ----
    # The backup is a rename of the chmod-000 original, so it inherits
    # mode 000; chmod it readable first (probe-side only — the product
    # must NOT touch the backup's mode, the operator restores it by hand).
    backs = glob.glob(str(qpath) + ".corrupt.*")
    if len(backs) == 1:
        os.chmod(backs[0], 0o600)
    cell("B3 .corrupt backup exists, byte-identical to the unreadable file",
         len(backs) == 1 and Path(backs[0]).read_text(encoding="utf-8") == good,
         f"backs={backs}")

    # ---- B4: exactly one new quarantine audit row, honest detail ----
    rows = audit_rows()
    hits = quarantine_rows(rows)
    ok = len(hits) == n_base + 1
    detail = hits[-1][2] if hits else ""
    if ok:
        ok = (hits[-1][1] == "failed"
              and backs and Path(backs[0]).name in detail
              and "unreadable" in detail.lower()
              and detail.count("不可知") == 3)
    cell("B4 exactly one new quarantine audit row (failed, backup path + "
         "reason + 不可知 counts)",
         ok, f"quarantine_rows={len(hits)} (was {n_base}) detail={detail!r}")

    # ---- B5: missing file is still the normal initial state (no audit) ----
    # Compare against the count just before this step (not n_base+1):
    # this cell must test only the missing-file behavior, independent
    # of whether B1 produced its row (on the pre-fix tree B1 produces
    # none, and B5 must still pass as a control).
    n_before_b5 = len(quarantine_rows(audit_rows()))
    qpath.unlink()
    r = c.post("/api/agent/poll", json={"node_name": "qn1"},
               headers={"Authorization": "Bearer " + token},
               environ_base={"REMOTE_ADDR": IP_AGENT})
    n_after = len(quarantine_rows(audit_rows()))
    cell("B5 missing queue file: poll 200, empty dispatch, zero new audit rows",
         r.status_code == 200 and r.json.get("commands") == []
         and n_after == n_before_b5,
         f"poll={r.status_code} quarantine_rows={n_after} (was {n_before_b5})")

    # ---- B6: restore the backup (operator path) -> old command dispatches ----
    if not backs:
        cell("B6 restored queue: poll 200 and the original command dispatches",
             False, "no .corrupt backup to restore from")
    else:
        qpath.write_text(Path(backs[0]).read_text(encoding="utf-8"),
                         encoding="utf-8")
        os.chmod(qpath, 0o600)
        r = c.post("/api/agent/poll", json={"node_name": "qn1"},
                   headers={"Authorization": "Bearer " + token},
                   environ_base={"REMOTE_ADDR": IP_AGENT})
        got = [cmd.get("id") for cmd in r.json.get("commands", [])]
        cell("B6 restored queue: poll 200 and the original command dispatches",
             r.status_code == 200 and cmd_id in got,
             f"{r.status_code} commands={got}")

    print(f"\nTOTAL {len(RESULTS)} cells, FAIL {sum(1 for _, ok in RESULTS if not ok)}: "
          f"{[n for n, ok in RESULTS if not ok]}")
    return sum(1 for _, ok in RESULTS if not ok)


if __name__ == "__main__":
    sys.exit(main())

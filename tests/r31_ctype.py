#!/usr/bin/env python3
"""AUDIT-R31 content-type probe (auditor-written, landed in tree by
the R31-P2-1 fix lane): Flask side of tests/r31_ctype.mjs. Valid JSON
body with a non-JSON Content-Type. Flask _json_body 400s; these cells
are unchanged by the Worker-side fix — they are the reference
behavior the Worker now matches.
Run as nobody with PYTHONPATH=venv site-packages (fresh data dir).
Exit code = number of FAILs.
"""
import os
import sys
from pathlib import Path

TREE = Path(os.environ.get("R31_TREE", "/tmp/r31/ptree"))
sys.path.insert(0, str(TREE / "panel"))
sys.path.insert(0, str(TREE / "core"))
sys.path.insert(0, str(TREE / "egress"))

import app as panel  # noqa: E402

RESULTS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""))


def main():
    pw = panel._ensure_admin_password()
    assert pw, "admin password not generated"
    c = panel.app.test_client()
    ip = "10.9.0.2"
    r = c.post("/api/login", json={"password": pw},
               environ_base={"REMOTE_ADDR": ip})
    assert r.status_code == 200, r.status_code
    r = c.post("/api/nodes", json={"name": "n1", "panel_url": "https://n1.example:8443"},
               environ_base={"REMOTE_ADDR": ip})
    cell("F0 register node 201", r.status_code == 201, str(r.status_code))

    # C1: toggle, valid JSON, text/plain.
    t = c.post("/api/sk5/fail-open?node=n1", data='{"fail_open": true}',
               content_type="text/plain", environ_base={"REMOTE_ADDR": ip})
    print(f"C1 toggle text/plain: flask {t.status_code} (expect 400)")
    cell("C1 toggle text/plain -> 400", t.status_code == 400)
    # C2: toggle, valid JSON, no Content-Type. Werkzeug test client
    # defaults to no content type when data= is a str without one.
    t = c.post("/api/sk5/fail-open?node=n1", data='{"fail_open": false}',
               environ_base={"REMOTE_ADDR": ip})
    print(f"C2 toggle no content-type: flask {t.status_code} (expect 400)")
    cell("C2 toggle no Content-Type -> 400", t.status_code == 400)
    # C3: application/json; charset=utf-8.
    t = c.post("/api/sk5/fail-open?node=n1", data='{"fail_open": true}',
               content_type="application/json; charset=utf-8",
               environ_base={"REMOTE_ADDR": ip})
    print(f"C3 toggle json;charset: flask {t.status_code} (expect 202)")
    cell("C3 toggle application/json;charset -> 202", t.status_code == 202)
    # C4: login with text/plain valid JSON.
    t = c.post("/api/login", data='{"password": "%s"}' % pw,
               content_type="text/plain",
               environ_base={"REMOTE_ADDR": "10.9.0.9"})
    print(f"C4 login text/plain correct pw: flask {t.status_code} (expect 400)")
    cell("C4 login text/plain -> 400", t.status_code == 400)
    # C5: save route, text/plain valid JSON.
    t = c.post("/api/sk5?node=n1",
               data='{"host":"proxy.example","port":1001,"username":"u","password":"p","enabled":false}',
               content_type="text/plain", environ_base={"REMOTE_ADDR": ip})
    print(f"C5 save text/plain: flask {t.status_code} (expect 400)")
    cell("C5 save text/plain -> 400", t.status_code == 400)

    fails = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"R31 content-type (flask): {len(RESULTS) - fails}/{len(RESULTS)}")
    sys.exit(fails)


if __name__ == "__main__":
    main()

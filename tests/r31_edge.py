#!/usr/bin/env python3
"""AUDIT-R31 edge probe (auditor-written, landed in tree by the
R31-P2-1 fix lane): Flask side of tests/r31_edge.mjs. Same raw bodies
against POST /api/sk5/fail-open (?node=n1 remote branch, so
validation runs before enqueue) and POST /api/sk5?node=n1 (save route,
remote branch). Flask _json_body 400s malformed / non-object bodies;
these cells are unchanged by the Worker-side fix — they are the
reference behavior the Worker now matches.
Run as nobody with PYTHONPATH=venv site-packages:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    OVPN_PANEL_DATA_DIR=<fresh data> OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \\
    OVPN_SK5_CONFIG_DIR=<sk5cfg> R31_TREE=<ptree> \\
    python3 /tmp/r31_edge.py
Exit code = number of FAILs.
"""
import json
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

    def toggle(path, raw):
        t = c.post(path + "?node=n1", data=raw, content_type="application/json",
                   environ_base={"REMOTE_ADDR": ip})
        params = None
        if t.status_code == 202:
            j = t.get_json() or {}
            g = c.get("/api/cmd/" + j.get("cmd_id", ""),
                      environ_base={"REMOTE_ADDR": ip})
            if g.status_code == 200:
                params = (g.get_json() or {}).get("params")
        return t.status_code, params

    def save(raw):
        t = c.post("/api/sk5?node=n1", data=raw, content_type="application/json",
                   environ_base={"REMOTE_ADDR": ip})
        params = None
        if t.status_code == 202:
            j = t.get_json() or {}
            g = c.get("/api/cmd/" + j.get("cmd_id", ""),
                      environ_base={"REMOTE_ADDR": ip})
            if g.status_code == 200:
                params = (g.get_json() or {}).get("params")
        return t.status_code, params

    s, p = toggle("/api/sk5/fail-open", '{"fail_open": 1.0, "fail_open": 1}')
    print(f"E1 dup 1.0,1: flask {s} params={json.dumps(p)} (expect 202 True)")
    cell("E1 dup float-then-int -> 202 True", s == 202 and p is not None and p.get("fail_open") is True)
    s, p = toggle("/api/sk5/fail-open", '{"fail_open": 1, "fail_open": 1.0}')
    print(f"E2 dup 1,1.0: flask {s} (expect 400)")
    cell("E2 dup int-then-float -> 400", s == 400)
    s, p = toggle("/api/sk5/fail-open", '{"note": "say \\"fail_open\\": 1.0 ok", "fail_open": true}')
    print(f"E3 key-in-string: flask {s} params={json.dumps(p)} (expect 202 True)")
    cell("E3 key inside string value -> 202 True", s == 202 and p is not None and p.get("fail_open") is True)
    s, p = toggle("/api/sk5/fail-open", '{"cfg": {"fail_open": 1.0}, "fail_open": true}')
    print(f"E4 key-in-nested-object: flask {s} params={json.dumps(p)} (expect 202 True)")
    cell("E4 key inside nested object -> 202 True", s == 202 and p is not None and p.get("fail_open") is True)
    s, p = toggle("/api/sk5/fail-open", '{"fail_\\u006fpen": 1.0}')
    print(f"E5 unicode-escaped key 1.0: flask {s} (expect 400)")
    cell("E5 unicode-escaped key with 1.0 -> 400", s == 400)
    s, p = toggle("/api/sk5/fail-open", '{\n  "fail_open": 1.0\n}')
    print(f"E6 pretty 1.0: flask {s} (expect 400)")
    cell("E6 pretty-printed 1.0 -> 400", s == 400)
    s, p = save('{"host":"proxy.example","port":1001.0,"port":1001,"username":"u","password":"p","enabled":false}')
    print(f"E7 save port dup 1001.0,1001: flask {s} params={json.dumps(p)} (expect 202)")
    cell("E7 save port dup float-then-int -> 202", s == 202 and p is not None and p.get("port") == 1001)
    s, p = save('{"host":"proxy.example","port":1001,"port":1001.0,"username":"u","password":"p","enabled":false}')
    print(f"E8 save port dup 1001,1001.0: flask {s} (expect 400)")
    cell("E8 save port dup int-then-float -> 400", s == 400)
    s, p = toggle("/api/sk5/fail-open", '{"username": "a,b}c{d", "fail_open": true}')
    print(f"E9 braces-in-string: flask {s} params={json.dumps(p)} (expect 202 True)")
    cell("E9 braces/commas inside string -> 202 True", s == 202 and p is not None and p.get("fail_open") is True)
    s, p = toggle("/api/sk5/fail-open", '{"arr": [1, {"fail_open": 1.0}], "fail_open": true}')
    print(f"E10 key-in-nested-array: flask {s} params={json.dumps(p)} (expect 202 True)")
    cell("E10 key inside nested array -> 202 True", s == 202 and p is not None and p.get("fail_open") is True)
    s, p = toggle("/api/sk5/fail-open", '{"fail_open": -0}')
    print(f"E11 fail_open -0: flask {s} params={json.dumps(p)} (expect 202 False)")
    cell("E11 -0 token -> 202 False", s == 202 and p is not None and p.get("fail_open") is False)
    s, p = toggle("/api/sk5/fail-open", '{"fail_open": 01}')
    print(f"E12 invalid JSON 01: flask {s} (expect 400)")
    cell("E12 invalid JSON -> 400", s == 400)
    s, p = toggle("/api/sk5/fail-open", '[1, 2]')
    print(f"E13 array body: flask {s} (expect 400)")
    cell("E13 array body -> 400", s == 400)
    s, p = toggle("/api/sk5/fail-open", '"hello"')
    print(f"E14 string body: flask {s} (expect 400)")
    cell("E14 string body -> 400", s == 400)
    s, p = toggle("/api/sk5/fail-open", '')
    print(f"E15 empty body: flask {s} (expect 400)")
    cell("E15 empty body -> 400", s == 400)
    s, p = toggle("/api/sk5/fail-open", 'null')
    print(f"E16 null body: flask {s} (expect 400)")
    cell("E16 null body -> 400", s == 400)

    def rawpost(path, raw):
        t = c.post(path + "?node=n1", data=raw, content_type="application/json",
                   environ_base={"REMOTE_ADDR": ip})
        params = None
        if t.status_code == 202:
            j = t.get_json() or {}
            g = c.get("/api/cmd/" + j.get("cmd_id", ""),
                      environ_base={"REMOTE_ADDR": ip})
            if g.status_code == 200:
                params = (g.get_json() or {}).get("params")
        return t.status_code, params

    s, p = rawpost("/api/openvpn/server", '{"port": 01}')
    print(f"E17 create_server invalid JSON: flask {s} (expect 400)")
    cell("E17 create_server invalid JSON -> 400", s == 400)
    s, p = rawpost("/api/openvpn/users", 'not json')
    print(f"E18 create_user non-JSON: flask {s} (expect 400)")
    cell("E18 create_user non-JSON -> 400", s == 400)
    s, p = rawpost("/api/openvpn/stop", 'garbage')
    print(f"E19 stop garbage body: flask {s} params={json.dumps(p)} (expect 202, body ignored)")
    cell("E19 stop garbage body -> 202 (agreement, body ignored)", s == 202)
    s, p = rawpost("/api/sk5/enable", '[1]')
    print(f"E20 sk5/enable array body: flask {s} params={json.dumps(p)} (expect 202, body ignored)")
    cell("E20 sk5/enable array body -> 202 (agreement, body ignored)", s == 202)

    fails = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"R31 edge (flask): {len(RESULTS) - fails}/{len(RESULTS)}")
    sys.exit(fails)


if __name__ == "__main__":
    main()

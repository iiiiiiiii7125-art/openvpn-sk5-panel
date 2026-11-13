#!/usr/bin/env python3
"""AUDIT-R29 Flask toggle-bool probe (r29_flask_toggle_bool.py) —
cross-face behavioral consistency, Flask side of the Worker probe
tests/r29_worker_toggle_bool.mjs. Drives panel/app.py through Flask
test_client (real code paths). Uses the REMOTE-node branch
(?node=) so the toggle routes enqueue instead of touching
sing-box: validation (_strict_bool/_toggle_value) runs before
_enqueue_compat, so 400s and enqueued params are route-level
behavior evidence.
Run as nobody with PYTHONPATH=venv site-packages:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    OVPN_PANEL_DATA_DIR=<data> OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \\
    OVPN_SK5_CONFIG_DIR=<sk5cfg> R29_TREE=<ptree> \\
    python3 tests/r29_flask_toggle_bool.py
Exit code = number of FAILs.
BH-03(c): after the R29-P2-1 fix this probe asserts the FIXED
behavior — both faces agree. T1–T8 already asserted Flask's correct
behavior (Flask was never broken); T9 (added by the fix lane) pins
the R12-P2-2 adjudicated `enabled` fallback on udp-over-tcp so a
later round cannot "fix" it away.
T10–T12 (R30-P2-1 fix): JSON integer-floats sent as RAW bodies
(json.dumps(1.0) would also emit "1.0", but the raw helper keeps the
literal explicit). Flask parses 1.0/1e0 as float and 400s via
_coerce_bool; the fixed Worker must agree — these cells pin the
agreed 400 on the Flask side of the pair.
"""
import json
import os
import sys
from pathlib import Path

TREE = Path(os.environ.get("R29_TREE", "/tmp/r29/ptree"))
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
    # register node n1 (remote branch target)
    r = c.post("/api/nodes", json={"name": "n1", "panel_url": "https://n1.example:8443"},
               environ_base={"REMOTE_ADDR": ip})
    cell("F0 register node 201", r.status_code == 201, str(r.status_code))

    def toggle(path, body):
        t = c.post(path + "?node=n1", json=body,
                   environ_base={"REMOTE_ADDR": ip})
        params = None
        if t.status_code == 202:
            j = t.get_json() or {}
            g = c.get("/api/cmd/" + j.get("cmd_id", ""),
                      environ_base={"REMOTE_ADDR": ip})
            if g.status_code == 200:
                params = (g.get_json() or {}).get("params")
        return t.status_code, params

    s, p = toggle("/api/sk5/fail-open", {"fail_open": "true"})
    print(f"T1 fail-open 'true': flask status={s} params={json.dumps(p)} (expect 400)")
    cell("T1 string true -> 400", s == 400)
    s, p = toggle("/api/sk5/fail-open", {"fail_open": 1})
    print(f"T2 fail-open 1: flask status={s} params={json.dumps(p)} (expect 202 True)")
    cell("T2 int 1 -> 202 True", s == 202 and p is not None and p.get("fail_open") is True)
    s, p = toggle("/api/sk5/fail-open", {"enabled": True})
    print(f"T3 fail-open {{enabled:true}}: flask status={s} params={json.dumps(p)} (expect 202 False)")
    cell("T3 enabled-key -> 202 False", s == 202 and p is not None and p.get("fail_open") is False)
    s, p = toggle("/api/sk5/fail-open", {"fail_open": False})
    print(f"T4 fail-open false: flask status={s} params={json.dumps(p)} (expect 202 False)")
    cell("T4 bool false -> 202 False", s == 202 and p is not None and p.get("fail_open") is False)
    s, p = toggle("/api/sk5/udp-over-tcp", {"udp_over_tcp": "true"})
    print(f"T5 uot 'true': flask status={s} params={json.dumps(p)} (expect 400)")
    cell("T5 string true -> 400", s == 400)
    s, p = toggle("/api/sk5/udp-over-tcp", {"udp_over_tcp": 1})
    print(f"T6 uot 1: flask status={s} params={json.dumps(p)} (expect 202 True)")
    cell("T6 int 1 -> 202 True", s == 202 and p is not None and p.get("udp_over_tcp") is True)
    s, p = toggle("/api/sk5/fail-open", {})
    print(f"T7 fail-open {{}}: flask status={s} params={json.dumps(p)} (expect 202 False)")
    cell("T7 empty body -> 202 False", s == 202 and p is not None and p.get("fail_open") is False)
    s, p = toggle("/api/sk5/fail-open", {"fail_open": "false"})
    print(f"T8 fail-open 'false': flask status={s} params={json.dumps(p)} (expect 400)")
    cell("T8 string false -> 400", s == 400)
    # T9 (fix-lane addition): udp-over-tcp {enabled:true} -> 202 True
    # via the R12-P2-2 adjudicated `enabled` fallback.
    s, p = toggle("/api/sk5/udp-over-tcp", {"enabled": True})
    print(f"T9 uot {{enabled:true}}: flask status={s} params={json.dumps(p)} (expect 202 True via adjudicated fallback)")
    cell("T9 uot enabled-key -> 202 True (adjudicated fallback kept)", s == 202 and p is not None and p.get("udp_over_tcp") is True)

    # T10–T12 (R30-P2-1 fix): raw integer-float literals -> 400.
    def toggle_raw(path, raw):
        t = c.post(path + "?node=n1", data=raw,
                   content_type="application/json",
                   environ_base={"REMOTE_ADDR": ip})
        return t.status_code

    s = toggle_raw("/api/sk5/fail-open", '{"fail_open": 1.0}')
    print(f"T10 fail-open 1.0: flask status={s} (expect 400)")
    cell("T10 fail-open 1.0 -> 400", s == 400)
    s = toggle_raw("/api/sk5/udp-over-tcp", '{"udp_over_tcp": 1.0}')
    print(f"T11 uot 1.0: flask status={s} (expect 400)")
    cell("T11 uot 1.0 -> 400", s == 400)
    s = toggle_raw("/api/sk5/fail-open", '{"fail_open": 1e0}')
    print(f"T12 fail-open 1e0: flask status={s} (expect 400, 1e0 parses as float)")
    cell("T12 fail-open 1e0 -> 400", s == 400)

    fails = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"R29 flask-toggle-bool: {len(RESULTS) - fails}/{len(RESULTS)}")
    sys.exit(fails)


if __name__ == "__main__":
    main()

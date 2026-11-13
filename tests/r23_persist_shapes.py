#!/usr/bin/env python3
"""AUDIT-R23 probe (r23_persist_shapes.py) — persisted-state shape matrix,
Flask / core / egress face.

Method: every durable artifact x every state shape (missing / empty /
corrupt / old-version / unreadable / half-written) x every reader. A cell
is PASS when the reader fails loudly, degrades honestly, or repairs; FAIL
when it silently loses data or silently misreports.

Modes (R23_MODE env; pre-state must exist BEFORE `import app`, so each
mode is a separate process):
  main        R1/R6/R7/R8/R9/R10/R11 (normal secret + fresh DB)
  empty_secret R2 (secret.key pre-created empty -> session forgery?)
  db_garbage  R3 (panel.db = garbage bytes -> login must 500 loudly)
  db_empty    R4 (panel.db = valid empty SQLite -> self-heal, login 200)
  db_old_admin R5 (admin table without session_version -> migration)

Run as nobody with PYTHONPATH=<venv> site-packages (see tests/README.md):
  runuser -u nobody -- env PYTHONPATH=/tmp/r21/venv/lib/python3.12/site-packages \
    R23_TREE=/tmp/r23/ptree OVPN_PANEL_DATA_DIR=<data> \
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \
    OPENVPN_CA_DIR=/tmp/r17/fixture-ca OPENVPN_SERVER_DIR=/tmp/r17/fixture-server \
    R23_MODE=<mode> python3 tests/r23_persist_shapes.py
Cells R1..R11; exit code = number of FAILs.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

TREE = Path(os.environ.get("R23_TREE", "/tmp/r23/ptree"))
sys.path.insert(0, str(TREE / "panel"))
sys.path.insert(0, str(TREE / "core"))
sys.path.insert(0, str(TREE / "egress"))

MODE = os.environ.get("R23_MODE", "main")
DATA_DIR = Path(os.environ["OVPN_PANEL_DATA_DIR"])
IP_ADMIN = "10.0.0.21"
IP_AGENT = "10.0.0.22"

# Pre-import states (modes that need a shaped file before app import).
if MODE == "empty_secret":
    p = Path(os.environ["OVPN_PANEL_SECRET_PATH"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")
elif MODE == "db_garbage":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "panel.db").write_bytes(b"this is not sqlite at all\x00\xff\xfe")
elif MODE == "db_empty":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DATA_DIR / "panel.db"))
    con.close()
elif MODE == "db_old_admin":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DATA_DIR / "panel.db"))
    con.execute("CREATE TABLE admin (id INTEGER PRIMARY KEY CHECK (id = 1),"
                " password_hash TEXT NOT NULL)")
    con.commit()
    con.close()

import app as panel  # noqa: E402

RESULTS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""))


def audit_rows():
    db = Path(panel.DB_PATH)
    con = sqlite3.connect(str(db))
    try:
        return con.execute("SELECT action, result, detail FROM audit_log").fetchall()
    finally:
        con.close()


def login_client(pw, ip=IP_ADMIN):
    c = panel.app.test_client()
    r = c.post("/api/login", json={"password": pw},
               environ_base={"REMOTE_ADDR": ip})
    assert r.status_code == 200, (r.status_code, r.data)
    cookie = r.headers.get("Set-Cookie", "").split(";")[0]
    return c, {"Cookie": cookie}


def main_mode():
    pw = panel._ensure_admin_password()
    assert pw, "admin password not generated"
    c, hdr = login_client(pw)

    # ---- R1: agent_queue.json unreadable (chmod 000) -> poll must not
    # destroy the queued command, or the loss must be audited. ----
    r = c.post("/api/nodes", json={"name": "q1", "panel_url": ""},
               headers=hdr, environ_base={"REMOTE_ADDR": IP_ADMIN})
    assert r.status_code == 201, (r.status_code, r.data)
    token = r.json["token"]
    r = c.post("/api/cmd", json={"node": "q1", "action": "get_status"},
               headers=hdr, environ_base={"REMOTE_ADDR": IP_ADMIN})
    assert r.status_code == 202, (r.status_code, r.data)
    cmd_id = r.json["cmd_id"]
    qpath = Path(panel.AGENT_QUEUE_PATH)
    assert qpath.exists()
    os.chmod(qpath, 0)
    try:
        r = c.post("/api/agent/poll", json={"node_name": "q1"},
                   headers={"Authorization": "Bearer " + token},
                   environ_base={"REMOTE_ADDR": IP_AGENT})
        poll_status = r.status_code
        r = c.post("/api/cmd", json={"node": "q1", "action": "get_status"},
                   headers=hdr, environ_base={"REMOTE_ADDR": IP_ADMIN})
        enqueue_status = r.status_code
    finally:
        os.chmod(qpath, 0o600)
    r = c.get("/api/cmd/" + cmd_id, headers=hdr,
              environ_base={"REMOTE_ADDR": IP_ADMIN})
    rows = audit_rows()
    loss_rows = [x for x in rows if "queue" in x[0] and x[1] == "failed"]
    cell("R1-queue-unreadable-no-silent-destroy",
         poll_status == 200 and enqueue_status in (201, 202)
         and (r.status_code == 200 or len(loss_rows) > 0),
         "poll=%s enqueue=%s cmd_get=%s loss_audit_rows=%d"
         % (poll_status, enqueue_status, r.status_code, len(loss_rows)))

    # ---- R6: login_attempts.failures = 123 (number, not list) ----
    c2 = panel.app.test_client()
    r = c2.post("/api/login", json={"password": "wrong"},
                environ_base={"REMOTE_ADDR": "10.0.0.99"})
    assert r.status_code == 401, (r.status_code, r.data)
    con = sqlite3.connect(str(panel.DB_PATH))
    con.execute("UPDATE login_attempts SET failures='123' WHERE ip='10.0.0.99'")
    con.commit()
    con.close()
    r = c2.post("/api/login", json={"password": "wrong"},
                environ_base={"REMOTE_ADDR": "10.0.0.99"})
    wrong_status = r.status_code
    r = c2.post("/api/login", json={"password": pw},
                environ_base={"REMOTE_ADDR": "10.0.0.99"})
    right_status = r.status_code
    # Loud 500 (fail-closed, no bypass) is acceptable; a silent 401
    # that swallows the corruption, or a 200, is not.
    cell("R6-login-failures-number-loud-not-bypass",
         wrong_status in (401, 500) and right_status in (200, 500)
         and not (wrong_status == 200 or right_status not in (200, 500)),
         "wrong=%s right=%s (500=loud fail-closed)" % (wrong_status, right_status))

    # ---- R7: index.txt garbage lines ----
    import openvpn_manager as core  # noqa: E402
    tmp = Path(tempfile.mkdtemp(prefix="r23-ca-"))
    (tmp / "pki").mkdir()
    (tmp / "pki" / "index.txt").write_text(
        "\n"
        "V\tshort-line-only\n"
        "V\t261231235959Z\t\t1001\tunknown\t/CN=alice\n"
        "X\t261231235959Z\t\t1002\tunknown\t/CN=xflag\n"
        "V\t200101000000Z\t\t1003\tunknown\t/CN=bob\n"
        "V\t261231235959Z\t\t1004\tunknown\t/no-cn-here\n"
        "R\t261231235959Z\t250101000000Z\t1005\tunknown\t/CN=carol\n",
        encoding="utf-8")
    users = core.list_users(tmp)
    by_name = {u["name"]: u for u in users}
    cell("R7-index-garbage-lines-skipped-no-crash",
         "alice" in by_name and "bob" in by_name and "carol" in by_name
         and by_name["bob"]["status"] == "expired"
         and by_name["carol"]["status"] == "revoked",
         "users=%s" % sorted(by_name))
    cell("R7-index-unknown-flag-surfaced-as-is",
         by_name.get("xflag", {}).get("status") == "X",
         "xflag status=%r (unknown flag passes through verbatim)"
         % by_name.get("xflag", {}).get("status"))

    # ---- R8: health.json shapes ----
    import sk5_manager as sk5  # noqa: E402
    sk5dir = Path(tempfile.mkdtemp(prefix="r23-sk5-"))
    os.environ["OVPN_SK5_CONFIG_DIR"] = str(sk5dir)
    # sk5_manager reads CONFIG_DIR at import; re-point its file paths.
    sk5.CONFIG_DIR = sk5dir
    sk5.HEALTH_FILE = sk5dir / "health.json"
    sk5.CONFIG_FILE = sk5dir / "sk5.json"
    sk5.RENDERED_CONFIG = sk5dir / "sing-box.json"
    (sk5dir / "health.json").write_bytes(b"\x00\xff garbage")
    cell("R8-health-garbage-returns-None",
         sk5.last_health() is None, "garbage -> None")
    (sk5dir / "health.json").write_text('"just a string"', encoding="utf-8")
    cell("R8-health-string-returns-None",
         sk5.last_health() is None, "string -> None")
    (sk5dir / "health.json").write_text('{"action": "ok"}', encoding="utf-8")
    cell("R8-health-dict-returns-dict",
         sk5.last_health() == {"action": "ok"}, "dict round-trips")

    # ---- R9: stale sk5.json.tmp ignored ----
    (sk5dir / "sk5.json").write_text(
        json.dumps({"host": "proxy.example", "port": 1080, "username": "u",
                    "password": "p", "enabled": False, "fail_open": False,
                    "udp_over_tcp": False}), encoding="utf-8")
    (sk5dir / "sk5.json.tmp").write_bytes(b"\x00\xff garbage tmp")
    try:
        cfg = sk5._load_config()
        cell("R9-stale-tmp-ignored", cfg.get("host") == "proxy.example"
             and cfg.get("port") == 1080, "tmp leftover does not affect load")
    except Exception as exc:  # noqa: BLE001
        cell("R9-stale-tmp-ignored", False, "raised %r" % exc)

    # ---- R10: corrupt sing-box.json is overwritten by re-render ----
    (sk5dir / "sing-box.json").write_bytes(b"\x00\xff garbage")
    try:
        sk5._render_singbox_config(cfg)
        rendered = json.loads((sk5dir / "sing-box.json").read_text(encoding="utf-8"))
        cell("R10-render-overwrites-corrupt",
             isinstance(rendered, dict), "re-render repairs garbage file")
    except Exception as exc:  # noqa: BLE001
        cell("R10-render-overwrites-corrupt", False, "raised %r" % exc)

    # ---- R11: do_restore stored-config verdicts ----
    # R24 update (same family as BN-Q5 / BR-W2 / BH-03(c)): the old
    # section ran the production one-liner VERBATIM to reproduce
    # R23-P2-2; BP removed that one-liner from policy-routing.sh and
    # replaced it with read_stored_enabled(), so the verbatim cells
    # failed forever on the fixed tree and masked real regressions.
    # R11 now runs the LIVE read_stored_enabled() from the live
    # script (functions only: the script is cut just before its
    # trailing dispatch case, which would `usage`-exit on source;
    # SK5_CONFIG_PATH is pointed at the probe's temp file after
    # sourcing). Contract: always exit 0, print exactly one of
    # missing / disabled / enabled / corrupt:<reason>; do_restore()
    # dies loudly on corrupt:* before touching any policy state.
    script_text = (TREE / "egress" / "policy-routing.sh").read_text(encoding="utf-8")
    marker = "# Lock once per invocation"
    head = script_text[:script_text.index(marker)]
    head_file = sk5dir / "script-head.sh"
    head_file.write_text(head, encoding="utf-8")
    cases = {}
    for label, content in (
            ("list", b"[1,2]"),
            ("garbage", b"\x00\xff"),
            ("missing", None),
            ("enabled-true", b'{"enabled": true}'),
            ("enabled-false", b'{"enabled": false}'),
            ("enabled-str", b'{"enabled": "false"}')):
        if content is None:
            (sk5dir / "sk5.json").unlink(missing_ok=True)
        else:
            (sk5dir / "sk5.json").write_bytes(content)
        p = subprocess.run(
            ["bash", "-c",
             "source \"$1\"; SK5_CONFIG_PATH=\"$2\"; read_stored_enabled",
             "x", str(head_file), str(sk5dir / "sk5.json")],
            capture_output=True, text=True, timeout=30)
        cases[label] = (p.returncode, p.stdout.strip())
    cell("R11-restore-list-shape-corrupt",
         cases["list"] == (0, "corrupt:top-level JSON is not an object (got list)"),
         "list verdict=%r (must be corrupt, never silent disabled)" % (cases["list"],))
    cell("R11-restore-garbage-shape-corrupt",
         cases["garbage"][0] == 0
         and cases["garbage"][1].startswith("corrupt:invalid JSON"),
         "garbage verdict=%r" % (cases["garbage"],))
    cell("R11-restore-controls",
         cases["missing"] == (0, "missing")
         and cases["enabled-true"] == (0, "enabled")
         and cases["enabled-false"] == (0, "disabled"),
         "missing=%r true=%r false=%r" % (cases["missing"],
                                          cases["enabled-true"],
                                          cases["enabled-false"]))
    cell("R11-restore-string-enabled-corrupt",
         cases["enabled-str"][0] == 0
         and cases["enabled-str"][1].startswith("corrupt:enabled must be a boolean"),
         "enabled-str verdict=%r" % (cases["enabled-str"],))


def empty_secret_mode():
    # secret.key exists but is empty: the panel must not silently run
    # with a publicly-known (empty) session key.
    import itsdangerous  # noqa: E402
    assert panel.app.secret_key == b"", repr(panel.app.secret_key)
    ser = itsdangerous.URLSafeTimedSerializer(b"", salt="cookie-session")
    forged = ser.dumps({"admin": True, "v": 1})
    c = panel.app.test_client()
    r = c.get("/api/status", headers={"Cookie": "session=" + forged},
              environ_base={"REMOTE_ADDR": IP_ADMIN})
    cell("R2-empty-secret-key-not-forgeable",
         r.status_code == 401,
         "forged empty-key session -> HTTP %s (200 = admin session "
         "forged with a publicly known key)" % r.status_code)
    # R2b: a REAL login under an empty key — Flask treats b"" as "no
    # secret key set" and raises at session assignment, so login 500s.
    # That is fail-closed and loud (panel bricked, not compromised).
    pw = panel._ensure_admin_password()
    assert pw, "admin password not generated"
    c2 = panel.app.test_client()
    r = c2.post("/api/login", json={"password": pw},
                environ_base={"REMOTE_ADDR": IP_ADMIN})
    cell("R2b-empty-secret-real-login-loud-500",
         r.status_code == 500,
         "real login -> HTTP %s (500 = fail-closed brick; 200+working "
         "session under an empty key would be the disaster)" % r.status_code)


def db_garbage_mode():
    c = panel.app.test_client()
    r = c.post("/api/login", json={"password": "anything"},
               environ_base={"REMOTE_ADDR": IP_ADMIN})
    cell("R3-db-garbage-login-loud-500",
         r.status_code == 500,
         "garbage panel.db -> login HTTP %s (500 = loud, no silent wrong)"
         % r.status_code)


def db_empty_mode():
    pw = panel._ensure_admin_password()
    assert pw, "admin password not generated on empty db"
    c = panel.app.test_client()
    r = c.post("/api/login", json={"password": pw},
               environ_base={"REMOTE_ADDR": IP_ADMIN})
    cell("R4-db-empty-sqlite-self-heals",
         r.status_code == 200, "empty sqlite file -> login HTTP %s" % r.status_code)


def db_old_admin_mode():
    pw = panel._ensure_admin_password()
    assert pw, "admin password not generated on old-schema db"
    con = sqlite3.connect(str(panel.DB_PATH))
    cols = [row[1] for row in con.execute("PRAGMA table_info(admin)")]
    con.close()
    c = panel.app.test_client()
    r = c.post("/api/login", json={"password": pw},
               environ_base={"REMOTE_ADDR": IP_ADMIN})
    cell("R5-db-old-admin-migrates",
         "session_version" in cols and r.status_code == 200,
         "cols=%s login=%s" % (cols, r.status_code))


if __name__ == "__main__":
    if MODE == "main":
        main_mode()
    elif MODE == "empty_secret":
        empty_secret_mode()
    elif MODE == "db_garbage":
        db_garbage_mode()
    elif MODE == "db_empty":
        db_empty_mode()
    elif MODE == "db_old_admin":
        db_old_admin_mode()
    else:
        raise SystemExit("unknown R23_MODE=%r" % MODE)
    fails = sum(1 for _, ok in RESULTS if not ok)
    print("R23 %s: %d/%d PASS" % (MODE, len(RESULTS) - fails, len(RESULTS)))
    sys.exit(fails)

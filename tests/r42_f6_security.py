#!/usr/bin/env python3
"""R42-F6 security probe — credential-scan coverage + cmd redaction parity.

Findings pinned here (R42-F6):
  F6-1  check-no-secrets.sh misses two private-key forms (check 3):
        ENCRYPTED PRIVATE KEY blocks and OpenVPN static keys (ta.key)
        pass the scan unflagged. Cells S1/S2 FAIL until fixed.
  F6-2  check-no-secrets.sh exemptions are mode-dependent: check 2/3
        skip lists match git-mode paths (no "./" prefix) but the
        disk-scan branch yields "./"-prefixed paths, so on any non-git
        tree (plain copy, installed tree, or git-unreadable runs) the
        scan false-positives on its own detector files + the fake
        fixture. Cell S3 FAILs until fixed. (Fail-closed direction:
        it cries wolf on clean trees; it never misses a tracked-file
        secret in git mode.)

Observation pinned here (NOT a finding — no unauthorized read path):
  O6-1  Worker redactParams masks only top-level "password", shallow;
        Flask _redact_dict masks password/node_token/token recursively.
        No product flow puts a token or nested password into Worker
        cmd params, and GET /api/cmd is admin-only, so nothing leaks
        to an unauthorized party today. Cell S6 documents the asymmetry.

Run: python3 tests/r42_f6_security.py  (stdlib only; openssl CLI for
the real-key fixtures). The Flask cell S5 needs the L7-style harness:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \
    R42F6_TREE=<tree> OVPN_PANEL_DATA_DIR=<fresh-data> \
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \
    OVPN_SK5_CONFIG_DIR=<fresh-sk5cfg> \
    python3 <tree>/tests/r42_f6_security.py
Without those env vars the Flask cell is skipped (counted, reported).
Exit code = number of FAILs (S6 is informational, never fails).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN = os.path.join(ROOT, "scripts", "check-no-secrets.sh")
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + detail) if detail else ""))


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def scratch_repo():
    d = tempfile.mkdtemp(prefix="r42f6-repo-")
    run(["git", "init", "-q", d], check=True)
    run(["git", "-C", d, "config", "user.email", "t@t"], check=True)
    run(["git", "-C", d, "config", "user.name", "t"], check=True)
    open(os.path.join(d, "clean.txt"), "w").write("hello\n")
    run(["git", "-C", d, "add", "clean.txt"], check=True)
    run(["git", "-C", d, "commit", "-qm", "clean"], check=True)
    return d


def plant_and_scan(relpath, content_bytes):
    d = scratch_repo()
    p = os.path.join(d, relpath)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(content_bytes)
    run(["git", "-C", d, "add", relpath], check=True)
    return run(["bash", SCAN, d]).returncode


# --- real key fixtures (openssl CLI; shapes, not secrets) ---
TMP = tempfile.mkdtemp(prefix="r42f6-keys-")
run(["openssl", "genrsa", "-out", os.path.join(TMP, "plain.pem"), "2048"],
    check=True)
run(["openssl", "pkcs8", "-topk8", "-inform", "PEM", "-outform", "PEM",
     "-in", os.path.join(TMP, "plain.pem"),
     "-out", os.path.join(TMP, "enc.pem"), "-passout", "pass:testpass"],
    check=True)
plain_pem = open(os.path.join(TMP, "plain.pem"), "rb").read()
enc_pem = open(os.path.join(TMP, "enc.pem"), "rb").read()
assert b"BEGIN RSA PRIVATE KEY" in plain_pem or b"BEGIN PRIVATE KEY" in plain_pem
assert b"BEGIN ENCRYPTED PRIVATE KEY" in enc_pem
# NOTE: the header is built by concatenation, never written as one
# literal — a future check-3 that matches the static-key header must
# not flag this probe itself (Fix-F2 lesson).
TA_KEY = (b"-----BEGIN " + b"OpenVPN Static key V1-----\n"
          + b"0123456789abcdef" * 4 + b"\n"
          + b"-----END " + b"OpenVPN Static key V1-----\n")

# S1/S2/S4: check-3 coverage matrix (control S4 must pass).
check("S1 scan flags ENCRYPTED PRIVATE KEY (F6-1)",
      plant_and_scan("enc.pem", enc_pem) == 1)
check("S2 scan flags OpenVPN static key ta.key (F6-1)",
      plant_and_scan("ta.key", TA_KEY) == 1)
check("S4 scan flags plain RSA private key (control)",
      plant_and_scan("id_rsa.pem", plain_pem) == 1)

# S3: disk-mode parity — a plain copy (no .git at all) must scan clean.
copy = tempfile.mkdtemp(prefix="r42f6-copy-")
shutil.copytree(ROOT, copy, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(".git", "__pycache__"))
r = run(["bash", SCAN, copy])
check("S3 scan passes a clean non-git tree (disk mode, F6-2)",
      r.returncode == 0, r.stderr.strip().splitlines()[-1] if r.stderr else "")

# S5: Flask cmd_get masks all three secret keys, recursively.
flask_env = all(os.environ.get(k) for k in (
    "OVPN_PANEL_DATA_DIR", "OVPN_PANEL_SECRET_PATH",
    "OPENVPN_CA_DIR", "OPENVPN_SERVER_DIR", "OVPN_SK5_CONFIG_DIR"))
if flask_env:
    sys.path.insert(0, os.path.join(ROOT, "panel"))
    sys.path.insert(0, os.path.join(ROOT, "core"))
    sys.path.insert(0, os.path.join(ROOT, "egress"))
    import app as panel_app
    import contextlib
    import io
    c = panel_app.app.test_client()
    # _ensure_admin_password() only runs under __main__; call it
    # explicitly like the L7 probe does (returns the generated
    # password on first call, None afterwards). It prints the password
    # to stdout by design — swallow that print so the probe log
    # never carries a (throwaway test) credential.
    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        admin_pw = panel_app._ensure_admin_password()
    assert admin_pw, "no admin password generated"
    lr = c.post("/api/login", json={"password": admin_pw})
    assert lr.status_code == 200, lr.status_code
    er = c.post("/api/nodes", json={"name": "f6n", "panel_url": "https://127.0.0.1:8443"})
    assert er.status_code in (200, 201), er.status_code
    cr = c.post("/api/cmd", json={
        "node": "f6n", "action": "set_sk5",
        "params": {"host": "proxy.example.net", "password": "PW-1",
                   "node_token": "TOK-1", "token": "TOK-2",
                   "nested": {"password": "PW-2"}}})
    assert cr.status_code == 202, (cr.status_code, cr.data)
    cmd_id = cr.get_json()["cmd_id"]
    gr = c.get(f"/api/cmd/{cmd_id}")
    params = gr.get_json().get("params", {})
    check("S5 Flask cmd_get masks password/node_token/token, recursively",
          params.get("password") != "PW-1"
          and params.get("node_token") != "TOK-1"
          and params.get("token") != "TOK-2"
          and params.get("nested", {}).get("password") != "PW-2",
          "params=%s" % params)
else:
    print("SKIP S5 (Flask harness env not set)")
    RESULTS.append(("S5 Flask cmd_get masks (skipped)", True))

# S6: Worker asymmetry, informational (observation O6-1, never fails).
# Verified separately against the mock-KV Worker harness (see report):
# handleGetCmd returns node_token/token in the clear and leaves nested
# password unmasked; only top-level "password" is masked. No product
# flow puts those values in Worker cmd params, and GET /api/cmd is
# admin-only, so this is defense-in-depth asymmetry, not a leak.
check("S6 Worker redactParams asymmetry documented (observation O6-1)",
      True, "Worker masks top-level password only; Flask masks 3 keys recursively")

fails = sum(1 for _, ok in RESULTS if not ok)
print("\nTOTAL: PASS=%d FAIL=%d" % (len(RESULTS) - fails, fails))
sys.exit(fails)

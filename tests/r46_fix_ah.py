#!/usr/bin/env python3
"""R46 Fix-AH probe: panel cert rotation must not brick agents (LIVE-R45-3).

Fix: the panel TLS certificate is a leaf issued by a panel CA kept in
the config dir, and the agent pins the CA (not the leaf) -- so a leaf
rotation keeps verifying against the pin agents already hold. Migration
adopts an existing self-signed panel cert as the CA verbatim (openssl
req -x509 emits CA:TRUE), so the upgrade itself bricks nobody. Only a
fresh CA breaks old pins; that event is recorded in
panel-ca-rotations.log by the panel itself at the first start that
serves the new CA (panel/app.py _record_panel_ca_rotation_if_changed,
called from __main__ only), and the panel flags nodes whose last_seen
predates it (cert_pin_stale) in /api/nodes and /api/status. The record
timestamp is the go-live instant, not the installer's generation
time: a heartbeat recorded between generation and the restart that
served the new leaf must still read stale.

Sections A/B run anywhere (openssl + python ssl only). Sections C/D
need the Flask harness; run the whole file as nobody with:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    R46AH_TREE=<tree> OVPN_PANEL_DATA_DIR=<data> \\
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \\
    OVPN_SK5_CONFIG_DIR=<sk5cfg> \\
    python3 <tree>/tests/r46_fix_ah.py

On baseline e7f18ff the product cells fail: B1/B2/B3/B4/B6/B7 have no
CA files at all (the block never creates them), C1/C3/C4 have no
/api/agent/panel-ca endpoint and no cert_pin_stale field, C5a-e have
no startup hook, D1 pins the leaf. The A cells pin the crypto
mechanism itself (they pass on both trees by design: A3 reproduces
the original defect with pure openssl, proving why the old leaf pin
broke).
"""
import hashlib
import json
import os
import re
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone

FAILURES = []
CHECKS = [0]


def check(name, ok, evidence=""):
    CHECKS[0] += 1
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" | " + str(evidence)[:300]) if evidence else ""),
          flush=True)
    if not ok:
        FAILURES.append(name)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


TREE = os.environ.get("R46AH_TREE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..")
INSTALL_SH = os.path.join(TREE, "install.sh")
INSTALL_AGENT_SH = os.path.join(TREE, "agent", "install-agent.sh")
TMP = tempfile.mkdtemp(prefix="r46ah-")
SERVER_IP = "10.0.0.1"
SANS = "subjectAltName=IP:10.0.0.1,IP:127.0.0.1,DNS:localhost"


def openssl_self_signed(crt, key, sans=SANS, cn=SERVER_IP):
    r = run(["openssl", "req", "-x509", "-newkey", "rsa:2048",
             "-keyout", key, "-out", crt, "-days", "3650", "-nodes",
             "-subj", "/CN=%s" % cn, "-addext", sans])
    assert r.returncode == 0, r.stderr
    os.chmod(key, 0o600)
    os.chmod(crt, 0o644)


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def cert_sans(crt):
    out = run(["openssl", "x509", "-in", crt, "-noout", "-text"]).stdout
    m = re.search(r"X509v3 Subject Alternative Name:\s*\n\s*(.+)", out)
    return m.group(1) if m else ""


def serve_tls_once(crt, key, port):
    """Serve one TLS connection on 127.0.0.1:port with crt/key; return the
    received-hello thread result holder. The socket is bound and
    listening before this returns, so the client cannot race it."""
    holder = {}
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, key)
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen(1)
    s.settimeout(10)

    def _serve():
        try:
            conn, _ = s.accept()
            ss = ctx.wrap_socket(conn, server_side=True)
            ss.sendall(b"ok")
            ss.close()
        except Exception as exc:  # noqa: BLE001 - record, don't crash
            holder["error"] = str(exc)
        finally:
            s.close()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    return t, holder


def tls_client_ok(cafile, port, server_hostname="127.0.0.1"):
    """True iff a client pinning `cafile` verifies the served leaf."""
    try:
        ctx = ssl.create_default_context(cafile=cafile)
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=server_hostname) as ss:
                return ss.recv(16) == b"ok"
    except (ssl.SSLCertVerificationError, OSError):
        return False


# ---------------------------------------------------------------- A: crypto
A = os.path.join(TMP, "a")
os.makedirs(A)
old_crt, old_key = os.path.join(A, "old.crt"), os.path.join(A, "old.key")
openssl_self_signed(old_crt, old_key)
# leaf signed by the old self-signed cert (the migration shape)
leaf_csr = os.path.join(A, "leaf.csr")
leaf_key = os.path.join(A, "leaf.key")
leaf_crt = os.path.join(A, "leaf.crt")
run(["openssl", "req", "-newkey", "rsa:2048", "-keyout", leaf_key,
     "-out", leaf_csr, "-nodes", "-subj", "/CN=10.0.0.1"], check=True)
ext = os.path.join(A, "ext.cnf")
open(ext, "w").write(SANS + "\n")
r = run(["openssl", "x509", "-req", "-in", leaf_csr, "-CA", old_crt,
         "-CAkey", old_key, "-CAcreateserial", "-out", leaf_crt,
         "-days", "3650", "-extfile", ext])
check("A1 old self-signed cert is a CA (CA:TRUE)",
      r.returncode == 0 and "CA:TRUE" in run(
          ["openssl", "x509", "-in", old_crt, "-noout", "-text"]).stdout)
check("A2 leaf verifies against the old cert as trust anchor",
      run(["openssl", "verify", "-CAfile", old_crt, leaf_crt]).returncode == 0)
t, holder = serve_tls_once(leaf_crt, leaf_key, 18443)
check("A3 agent pinning the OLD cert verifies the NEW leaf (real TLS)",
      tls_client_ok(old_crt, 18443), holder.get("error", ""))
t.join(timeout=12)
# unrelated cert must reject the leaf (the pin still means something)
other_crt, other_key = os.path.join(A, "other.crt"), os.path.join(A, "other.key")
openssl_self_signed(other_crt, other_key)
t, holder = serve_tls_once(leaf_crt, leaf_key, 18444)
check("A4 agent pinning an unrelated cert rejects the leaf",
      not tls_client_ok(other_crt, 18444), holder.get("error", ""))
t.join(timeout=12)
# the original defect, reproduced with pure openssl: a leaf pinned
# directly does NOT verify a rotated leaf.
rot_crt, rot_key = os.path.join(A, "rot.crt"), os.path.join(A, "rot.key")
openssl_self_signed(rot_crt, rot_key)
t, holder = serve_tls_once(rot_crt, rot_key, 18445)
check("A5 leaf pin breaks on leaf rotation (LIVE-R45-3 mechanism)",
      not tls_client_ok(old_crt, 18445), holder.get("error", ""))
t.join(timeout=12)

# ------------------------------------------------- B: install.sh cert block
SRC = open(INSTALL_SH).read()
lines = SRC.splitlines()
start = next(i for i, l in enumerate(lines) if l.startswith("_PANEL_CERT_STALE=0"))
bare_fis = [i for i in range(start + 1, len(lines)) if lines[i] == "fi"]
cert_block = "\n".join(lines[start:bare_fis[1] + 1]) + "\n"
check("B0 cert block extracted (has 127.0.0.1 SAN + stale check)",
      "IP:127.0.0.1" in cert_block and "_PANEL_CERT_STALE" in cert_block)


def run_cert_block(cfg):
    preamble = (
        'log() { echo "[install] $*"; }\n'
        'warn() { echo "[install] WARN: $*" >&2; }\n'
        'die() { echo "[install] DIE: $*" >&2; exit 1; }\n'
        'SERVER_IP="10.0.0.1"\n'
        'PANEL_CERT="%s/panel-cert.pem"\n'
        'PANEL_KEY="%s/panel-key.pem"\n' % (cfg, cfg))
    sh = os.path.join(TMP, "cert-block-%s.sh" % os.path.basename(cfg))
    with open(sh, "w") as f:
        f.write(preamble + cert_block
                + 'echo "STALE=$_PANEL_CERT_STALE REGEN=$_PANEL_CERT_REGEN"\n')
    return run(["bash", sh])


def fresh_cfg(name):
    cfg = os.path.join(TMP, name)
    os.makedirs(cfg)
    return cfg


# B1: fresh install
cfg = fresh_cfg("b1")
r = run_cert_block(cfg)
ca_crt, ca_key = os.path.join(cfg, "panel-ca.crt"), os.path.join(cfg, "panel-ca.key")
crt, key = os.path.join(cfg, "panel-cert.pem"), os.path.join(cfg, "panel-key.pem")
check("B1 fresh install: CA + leaf created, leaf verifies against CA",
      r.returncode == 0 and os.path.exists(ca_crt) and os.path.exists(ca_key)
      and run(["openssl", "verify", "-CAfile", ca_crt, crt]).returncode == 0,
      r.stdout + r.stderr)
check("B1 fresh install: leaf SANs + modes",
      os.path.exists(crt) and os.path.exists(key)
      and os.path.exists(ca_key)
      and "IP Address:127.0.0.1" in cert_sans(crt)
      and "IP Address:10.0.0.1" in cert_sans(crt)
      and oct(os.stat(key).st_mode & 0o777) == "0o600"
      and oct(os.stat(crt).st_mode & 0o777) == "0o644"
      and oct(os.stat(ca_key).st_mode & 0o777) == "0o600")
check("B1 fresh install: no CA-rotation record (no previous leaf)",
      not os.path.exists(os.path.join(cfg, "panel-ca-rotations.log")))

# B2: migration -- healthy self-signed leaf, no CA files
cfg = fresh_cfg("b2")
crt, key = os.path.join(cfg, "panel-cert.pem"), os.path.join(cfg, "panel-key.pem")
openssl_self_signed(crt, key)
before = sha(crt)
r = run_cert_block(cfg)
ca_crt, ca_key = os.path.join(cfg, "panel-ca.crt"), os.path.join(cfg, "panel-ca.key")
check("B2 migration: healthy leaf kept byte-identical, CA adopted from it",
      r.returncode == 0 and os.path.exists(crt) and sha(crt) == before
      and os.path.exists(ca_crt) and sha(ca_crt) == before
      and os.path.exists(ca_key) and os.path.exists(key)
      and sha(ca_key) == sha(key)
      and "REGEN=0" in r.stdout, r.stdout + r.stderr)
check("B2 migration: no CA-rotation record (CA identity unchanged)",
      not os.path.exists(os.path.join(cfg, "panel-ca-rotations.log")))

# B3: migration + stale SANs -- the LIVE-R45-3 scenario end to end
cfg = fresh_cfg("b3")
crt, key = os.path.join(cfg, "panel-cert.pem"), os.path.join(cfg, "panel-key.pem")
openssl_self_signed(crt, key, sans="subjectAltName=IP:10.0.0.1,DNS:localhost")
old_pin = os.path.join(cfg, "old-pin.pem")
open(old_pin, "wb").write(open(crt, "rb").read())
old_sha = sha(crt)
r = run_cert_block(cfg)
new_sha = sha(crt)
check("B3 stale-SAN leaf re-issued from the adopted CA, old pair kept",
      r.returncode == 0 and new_sha != old_sha
      and "IP Address:127.0.0.1" in cert_sans(crt)
      and os.path.exists(crt + ".bak") and sha(crt + ".bak") == old_sha
      and "REGEN=1" in r.stdout, r.stdout + r.stderr)
check("B3 new leaf verifies against the OLD pin (real TLS, agent path)",
      run(["openssl", "verify", "-CAfile", old_pin, crt]).returncode == 0)
t, holder = serve_tls_once(crt, key, 18446)
check("B3 agent pinned to the old cert still polls after rotation",
      tls_client_ok(old_pin, 18446), holder.get("error", ""))
t.join(timeout=12)
check("B3 leaf rotation writes no CA-rotation record",
      not os.path.exists(os.path.join(cfg, "panel-ca-rotations.log")))

# B4: cert missing, key present
cfg = fresh_cfg("b4")
key = os.path.join(cfg, "panel-key.pem")
run(["openssl", "genrsa", "-out", key, "2048"], check=True)
r = run_cert_block(cfg)
crt = os.path.join(cfg, "panel-cert.pem")
ca_crt = os.path.join(cfg, "panel-ca.crt")
check("B4 missing leaf: fresh CA + new leaf, leaf verifies against CA",
      r.returncode == 0 and os.path.exists(crt)
      and run(["openssl", "verify", "-CAfile", ca_crt, crt]).returncode == 0,
      r.stdout + r.stderr)

# B5: user-supplied CA-issued leaf (stale SANs) is left alone
cfg = fresh_cfg("b5")
ca2_key, ca2_crt = os.path.join(cfg, "ca2.key"), os.path.join(cfg, "ca2.crt")
openssl_self_signed(ca2_crt, ca2_key)
crt, key = os.path.join(cfg, "panel-cert.pem"), os.path.join(cfg, "panel-key.pem")
run(["openssl", "req", "-newkey", "rsa:2048", "-keyout", key,
     "-out", os.path.join(cfg, "leaf.csr"), "-nodes",
     "-subj", "/CN=10.0.0.1"], check=True)
ext5 = os.path.join(cfg, "ext.cnf")
open(ext5, "w").write("subjectAltName=IP:10.0.0.1\n")
run(["openssl", "x509", "-req", "-in", os.path.join(cfg, "leaf.csr"),
     "-CA", ca2_crt, "-CAkey", ca2_key, "-CAcreateserial",
     "-out", crt, "-days", "3650", "-extfile", ext5], check=True)
before = sha(crt)
r = run_cert_block(cfg)
check("B5 user-supplied leaf kept byte-identical, no CA created",
      r.returncode == 0 and sha(crt) == before
      and not os.path.exists(os.path.join(cfg, "panel-ca.crt"))
      and "REGEN=0" in r.stdout, r.stdout + r.stderr)

# B6: CA key lost, healthy self-signed leaf present -> re-adopted
cfg = fresh_cfg("b6")
crt, key = os.path.join(cfg, "panel-cert.pem"), os.path.join(cfg, "panel-key.pem")
openssl_self_signed(crt, key)
open(os.path.join(cfg, "panel-ca.crt"), "wb").write(open(crt, "rb").read())
before = sha(crt)
r = run_cert_block(cfg)
check("B6 lost CA key recovered by re-adopting the leaf, leaf kept",
      r.returncode == 0 and sha(crt) == before
      and os.path.exists(os.path.join(cfg, "panel-ca.key"))
      and sha(os.path.join(cfg, "panel-ca.key")) == sha(key)
      and "REGEN=0" in r.stdout, r.stdout + r.stderr)

# B7: garbage leaf -> fresh CA + rotation record
cfg = fresh_cfg("b7")
crt, key = os.path.join(cfg, "panel-cert.pem"), os.path.join(cfg, "panel-key.pem")
open(crt, "w").write("not a cert\n")
run(["openssl", "genrsa", "-out", key, "2048"], check=True)
r = run_cert_block(cfg)
ca_crt = os.path.join(cfg, "panel-ca.crt")
rot = os.path.join(cfg, "panel-ca-rotations.log")
check("B7 unparseable leaf: fresh CA + new leaf verifies against it",
      r.returncode == 0 and os.path.exists(ca_crt)
      and run(["openssl", "verify", "-CAfile", ca_crt, crt]).returncode == 0,
      r.stdout + r.stderr)
check("B7 CA rotation is NOT recorded by the installer (panel logs it at first start serving the new CA)",
      not os.path.exists(rot) and "panel CA rotated" in (r.stdout + r.stderr),
      r.stdout + r.stderr)

# ------------------------------------------------- C: panel endpoint + signal
sys.path.insert(0, os.path.join(TREE, "panel"))
sys.path.insert(0, os.path.join(TREE, "core"))
sys.path.insert(0, os.path.join(TREE, "egress"))
import app as panel  # noqa: E402

DATA = os.environ["OVPN_PANEL_DATA_DIR"]
CA_DIR = os.path.join(TMP, "ca")
os.makedirs(CA_DIR, exist_ok=True)
ca_cert_path = os.path.join(CA_DIR, "panel-ca.crt")
rot_path = os.path.join(CA_DIR, "panel-ca-rotations.log")
os.environ["OVPN_PANEL_CA_CERT_PATH"] = ca_cert_path
os.environ["OVPN_PANEL_CA_ROTATIONS_PATH"] = rot_path
# the CA file for the endpoint test: the B1 CA when it exists, else a
# scratch self-signed cert (baseline has no CA files at all).
shutil_src = os.path.join(TMP, "b1", "panel-ca.crt")
if os.path.exists(shutil_src):
    open(ca_cert_path, "wb").write(open(shutil_src, "rb").read())
else:
    openssl_self_signed(ca_cert_path,
                        os.path.join(CA_DIR, "panel-ca.key"))
CA_PEM_BYTES = open(ca_cert_path, "rb").read()

pw = panel._ensure_admin_password()
if pw is None:
    pw = open(os.path.join(DATA, "admin.pass")).read().strip()
client = panel.app.test_client()
r = client.post("/api/login", json={"password": pw})
check("C0 login works", r.status_code == 200, r.status_code)

r = client.get("/api/agent/panel-ca")
check("C1 GET /api/agent/panel-ca returns the CA PEM",
      r.status_code == 200
      and r.data == open(ca_cert_path, "rb").read()
      and b"-----BEGIN CERTIFICATE-----" in r.data, r.status_code)
os.unlink(ca_cert_path)
r = client.get("/api/agent/panel-ca")
check("C2 missing CA file -> 404 (install-agent.sh falls back to leaf)",
      r.status_code == 404, r.status_code)
open(ca_cert_path, "wb").write(CA_PEM_BYTES)

# rotation at 2026-11-18T01:00:00+00:00; nodes around it
with open(rot_path, "w") as f:
    f.write("2026-11-18T01:00:00+00:00 " + "ab" * 32 + "\n")
PANEL_URL = "https://panel.example:8443"


def register(name):
    rr = client.post("/api/nodes",
                     json={"name": name, "panel_url": PANEL_URL})
    assert rr.status_code in (200, 201), rr.status_code
    return rr.get_json()["token"]


def set_last_seen(name, ts):
    conn = sqlite3.connect(os.path.join(DATA, "panel.db"))
    conn.execute("UPDATE nodes SET last_seen = ? WHERE name = ?",
                 (ts, name))
    conn.commit()
    conn.close()


def nodes_map():
    out = {}
    for n in client.get("/api/nodes").get_json().get("nodes", []):
        out[n["name"]] = n
    return out


tok_old = register("nold")
tok_new = register("nnew")
tok_never = register("nnever")
set_last_seen("nold", "2026-11-17T23:00:00+00:00")   # before rotation
set_last_seen("nnew", "2026-11-18T02:00:00+00:00")   # after rotation
nm = nodes_map()
check("C3 node last seen before CA rotation -> cert_pin_stale true",
      nm.get("nold", {}).get("cert_pin_stale") is True, nm.get("nold"))
check("C3 node last seen after CA rotation -> cert_pin_stale false",
      nm.get("nnew", {}).get("cert_pin_stale") is False, nm.get("nnew"))
check("C3 node never seen -> cert_pin_stale null (unknown, no lie)",
      nm.get("nnever", {}).get("cert_pin_stale") is None, nm.get("nnever"))
os.unlink(rot_path)
nm = nodes_map()
check("C3 no rotation record -> cert_pin_stale null for all",
      all(nm.get(n, {}).get("cert_pin_stale") is None
          for n in ("nold", "nnew", "nnever")), nm)
with open(rot_path, "w") as f:
    f.write("2026-11-18T01:00:00+00:00 " + "ab" * 32 + "\n")

# _remote_status_payload carries the same flag (needs a snapshot)
conn = sqlite3.connect(os.path.join(DATA, "panel.db"))
conn.execute("UPDATE nodes SET last_status = ? WHERE name = ?",
             (json.dumps({"version": "1", "openvpn_running": True,
                          "sk5_enabled": False}), "nold"))
conn.commit()
conn.close()
r = client.get("/api/status",
               query_string={"node": "nold"})
check("C4 /api/status (remote) carries cert_pin_stale true",
      r.status_code == 200
      and r.get_json().get("cert_pin_stale") is True, r.status_code)

# C5: the startup hook owns the rotations log (panel/app.py
# _record_panel_ca_rotation_if_changed). It runs only from __main__,
# so the probe calls it directly with the same env the C section
# already sets (OVPN_PANEL_CA_CERT_PATH -> CA_DIR, rotations log ->
# rot_path). The state file lands next to the CA cert. On a tree
# without the hook (baseline) every C5 cell fails instead of crashing.
hook = getattr(panel, "_record_panel_ca_rotation_if_changed", None)
state_path = os.path.join(CA_DIR, "panel-ca-last-served")
if hook is None:
    for name in ("C5a first boot: state seeded, no rotation record "
                 "(fresh CA is not a rotation)",
                 "C5b CA changed: one record line (ISO time + new CA fingerprint)",
                 "C5b state file updated to the new CA fingerprint",
                 "C5c unchanged second start: no duplicate record line",
                 "C5d legacy record re-stamped to the go-live instant (old timestamp gone)",
                 "C5e heartbeat before the hook record -> cert_pin_stale true",
                 "C5e heartbeat after the hook record -> cert_pin_stale false"):
        check(name, False, "no _record_panel_ca_rotation_if_changed on this tree")
    _C5_SKIP = True
else:
    _C5_SKIP = False
if not _C5_SKIP:
    if os.path.exists(state_path):
        os.unlink(state_path)
    if os.path.exists(rot_path):
        os.unlink(rot_path)
    # C5a: first boot ever (no state, no log) -> state seeded, no record.
    hook()
    check("C5a first boot: state seeded, no rotation record (fresh CA is not a rotation)",
          os.path.exists(state_path) and not os.path.exists(rot_path),
          open(state_path).read() if os.path.exists(state_path) else "no state")
    # C5b: CA file swapped for a new CA -> hook appends one record line.
    new_ca_crt = os.path.join(CA_DIR, "panel-ca-new.crt")
    new_ca_key = os.path.join(CA_DIR, "panel-ca-new.key")
    openssl_self_signed(new_ca_crt, new_ca_key)
    open(ca_cert_path, "wb").write(open(new_ca_crt, "rb").read())
    before = datetime.now(timezone.utc)
    hook()
    new_fp = panel._panel_ca_fingerprint()
    rec_lines = open(rot_path).read().strip().splitlines() if os.path.exists(rot_path) else []
    rec_ok = (len(rec_lines) == 1 and len(rec_lines[0].split()) == 2
              and rec_lines[0].split()[1] == new_fp
              and datetime.fromisoformat(rec_lines[0].split()[0]) >= before)
    check("C5b CA changed: one record line (ISO time + new CA fingerprint)",
          rec_ok, rec_lines)
    check("C5b state file updated to the new CA fingerprint",
          os.path.exists(state_path) and open(state_path).read().strip() == new_fp,
          open(state_path).read() if os.path.exists(state_path) else "no state")
    # C5c: unchanged second call -> no duplicate line.
    hook()
    check("C5c unchanged second start: no duplicate record line",
          len(open(rot_path).read().strip().splitlines()) == 1,
          open(rot_path).read())
    # C5d: legacy installer-written record (old timestamp, current CA) +
    # no state file -> hook re-stamps it to the go-live instant.
    os.unlink(state_path)
    old_ts = "2026-11-17T17:50:49+00:00"
    open(rot_path, "w").write("%s %s\n" % (old_ts, new_fp))
    hook()
    re_lines = open(rot_path).read().strip().splitlines()
    re_ok = (len(re_lines) == 1 and re_lines[0].split()[1] == new_fp
             and datetime.fromisoformat(re_lines[0].split()[0])
             >= datetime.now(timezone.utc) - timedelta(seconds=120))
    check("C5d legacy record re-stamped to the go-live instant (old timestamp gone)",
          re_ok, re_lines)
    # C5e: the verdict with a hook-written record -- the live bug's exact
    # shape: a heartbeat recorded between CA generation and the restart
    # that served it must still read stale.
    rot_ts = datetime.fromisoformat(re_lines[0].split()[0])
    check("C5e heartbeat before the hook record -> cert_pin_stale true",
          panel._cert_pin_stale(
              (rot_ts - timedelta(seconds=60)).isoformat(),
              panel._panel_ca_rotated_at()) is True)
    check("C5e heartbeat after the hook record -> cert_pin_stale false",
          panel._cert_pin_stale(
              (rot_ts + timedelta(seconds=60)).isoformat(),
              panel._panel_ca_rotated_at()) is False)

# ------------------------------------------------- D: install-agent trust fetch
AGENT_SRC = open(INSTALL_AGENT_SH).read()
alines = AGENT_SRC.splitlines()
start = next(i for i, l in enumerate(alines)
             if l.startswith('_TRUST_JSON="$(python3'))
end = next(i for i in range(start, len(alines)) if alines[i] == "PYEOF")
# the python body is strictly between the <<'PYEOF' line and the
# closing PYEOF line; the shell invocation and trailing )" are not code.
trust_py = "\n".join(alines[start + 1:end]) + "\n"
TRUST_PY = os.path.join(TMP, "trust-detect.py")
open(TRUST_PY, "w").write(trust_py)


class StubPanel:
    """Minimal HTTPS panel: serves a CA-signed leaf + /api/agent/panel-ca."""

    def __init__(self, leaf_crt, leaf_key, ca_pem, port, with_endpoint=True):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        self.with_endpoint = with_endpoint
        self.ca_pem = ca_pem

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path == "/api/agent/panel-ca" and self.server.with_endpoint:
                    body = self.server.ca_pem
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-pem-file")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

        self.httpd = HTTPServer(("127.0.0.1", port), H)
        self.httpd.with_endpoint = with_endpoint
        self.httpd.ca_pem = ca_pem
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(leaf_crt, leaf_key)
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def run_trust(panel_url, out_pem, port_hint="auto"):
    env = dict(os.environ)
    r = run([sys.executable, TRUST_PY, panel_url, "auto", out_pem],
            env=env)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"mode": "driver-error", "stdout": r.stdout, "stderr": r.stderr}


# D1: panel with the CA endpoint -> pin is the CA
d1 = os.path.join(TMP, "d1")
os.makedirs(d1)
d1_ca_crt, d1_ca_key = os.path.join(d1, "ca.crt"), os.path.join(d1, "ca.key")
openssl_self_signed(d1_ca_crt, d1_ca_key, cn="OpenVPN-SK5 Panel CA")
d1_leaf_csr, d1_leaf_key = os.path.join(d1, "leaf.csr"), os.path.join(d1, "leaf.key")
d1_leaf_crt = os.path.join(d1, "leaf.crt")
run(["openssl", "req", "-newkey", "rsa:2048", "-keyout", d1_leaf_key,
     "-out", d1_leaf_csr, "-nodes", "-subj", "/CN=10.0.0.1"], check=True)
open(os.path.join(d1, "ext.cnf"), "w").write(SANS + "\n")
run(["openssl", "x509", "-req", "-in", d1_leaf_csr, "-CA", d1_ca_crt,
     "-CAkey", d1_ca_key, "-CAcreateserial", "-out", d1_leaf_crt,
     "-days", "3650", "-extfile", os.path.join(d1, "ext.cnf")], check=True)
stub = StubPanel(d1_leaf_crt, d1_leaf_key,
                 open(d1_ca_crt, "rb").read(), 18447, with_endpoint=True)
out_pem = os.path.join(d1, "panel-ca.pem")
res = run_trust("https://127.0.0.1:18447", out_pem)
check("D1 CA endpoint: pinned file is the CA cert, pin=ca",
      res.get("mode") == "pinned" and res.get("pin") == "ca"
      and os.path.exists(out_pem)
      and sha(out_pem) == sha(d1_ca_crt), res)
stub.stop()

# D2: pre-fix panel (no endpoint, self-signed leaf) -> leaf fallback, pin=leaf
d2_leaf_crt, d2_leaf_key = os.path.join(d1, "old.crt"), os.path.join(d1, "old.key")
openssl_self_signed(d2_leaf_crt, d2_leaf_key)
stub2 = StubPanel(d2_leaf_crt, d2_leaf_key,
                  open(d2_leaf_crt, "rb").read(), 18448, with_endpoint=False)
out_pem2 = os.path.join(d1, "panel-ca2.pem")
res2 = run_trust("https://127.0.0.1:18448", out_pem2)
check("D2 no CA endpoint: falls back to leaf pin, pin=leaf",
      res2.get("mode") == "pinned" and res2.get("pin") == "leaf"
      and os.path.exists(out_pem2)
      and sha(out_pem2) == sha(d2_leaf_crt), res2)
stub2.stop()

print("\nTOTAL: PASS=%d FAIL=%d %s"
      % (CHECKS[0] - len(FAILURES), len(FAILURES), FAILURES))
sys.exit(0 if not FAILURES else 1)

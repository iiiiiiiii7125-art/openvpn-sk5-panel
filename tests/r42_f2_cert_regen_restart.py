#!/usr/bin/env python3
"""R42-F2 probe — cert-regeneration restart trigger coverage.

Drives the REAL cert section (install.sh:653-680) and the REAL
_restart_panel_if_needed function, both extracted verbatim from
install.sh (not copies), through a stub systemctl, across the
regeneration matrix:

  A  cert present, SANs include IP:127.0.0.1 -> no regen, no restart
  B  cert present, self-signed, no 127.0.0.1  -> regen (stale=1), restart
  C  cert file MISSING, key present          -> regen, stale=0, restart?
  D  key file MISSING, cert present          -> regen, stale=0, restart?
  E  both files missing                      -> regen, stale=0, restart?
  F  cert unparseable                        -> regen (stale=1), restart
  G  cert non-self-signed, no 127.0.0.1      -> kept, no restart (control)

The restart trigger keys on _PANEL_CERT_STALE only, but the
generation block also fires when the files are missing (C/D/E).
If C/D/E regenerate without a restart, the panel keeps serving the
OLD cert from memory while Caddy (reloaded below with a copy of the
NEW cert) trusts only the new one -- the exact LIVE-R41-1 mechanism
(502 on every domain request until a manual restart), one trigger
short.

Usage: python3 tests/r42_f2_cert_regen_restart.py [tree]
Exit 0 only if every case matches the EXPECTED restart decision.
"""
import hashlib
import os
import re
import subprocess
import sys
import tempfile

TREE = os.path.abspath(sys.argv[1] if len(sys.argv[1:2]) else
                       os.path.join(os.path.dirname(__file__), ".."))
INSTALL = os.path.join(TREE, "install.sh")

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s %s" % (name, detail))
    else:
        FAIL += 1
        print("FAIL %s %s" % (name, detail))


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def extract_cert_section(src):
    lines = src.splitlines()
    start = next(i for i, l in enumerate(lines)
                 if l.startswith("_PANEL_CERT_STALE=0"))
    # The section has TWO bare `fi` lines at column 0: the first closes
    # the stale computation (line 665), the second closes the
    # generation if. Take through the second one.
    bare_fis = [i for i in range(start + 1, len(lines))
                if lines[i] == "fi"]
    end = bare_fis[1]
    return "\n".join(lines[start:end + 1])


def extract_function(src, name):
    lines = src.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.startswith(name + "() {")), None)
    if start is None:
        return None
    end = next(i for i in range(start + 1, len(lines))
               if lines[i] == "}")
    return "\n".join(lines[start:end + 1])


STUB_SYSTEMCTL = """#!/usr/bin/env bash
if [ "$1" = "is-active" ]; then
    [ "${STUB_PANEL_ACTIVE:-0}" = "1" ] && exit 0 || exit 3
fi
if [ "$1" = "restart" ]; then
    echo "restart $2" >> "$STUB_LOG"
    exit 0
fi
exit 0
"""

OPENSSL_GEN = ("openssl req -x509 -newkey rsa:2048 -keyout {key} "
               "-out {crt} -days 3650 -nodes -subj /CN=10.0.0.1 "
               "-addext {sans} >/dev/null 2>&1")


def sha(path):
    if not os.path.exists(path):
        return None
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def run_case(cert_section, fn_text, mode):
    """mode: A..G. Returns (regenerated, stale, restarts)."""
    d = tempfile.mkdtemp(prefix="r42f2-cert-")
    cfg = os.path.join(d, "cfg")
    os.makedirs(cfg)
    crt = os.path.join(cfg, "panel-cert.pem")
    key = os.path.join(cfg, "panel-key.pem")
    stubdir = os.path.join(d, "bin")
    os.makedirs(stubdir)
    stub = os.path.join(stubdir, "systemctl")
    with open(stub, "w") as f:
        f.write(STUB_SYSTEMCTL)
    os.chmod(stub, 0o755)
    stub_log = os.path.join(d, "stub.log")
    open(stub_log, "w").close()
    # --- fixture ---
    if mode in ("A", "B", "D", "F", "G"):
        if mode == "A":
            sans = "subjectAltName=IP:10.0.0.1,IP:127.0.0.1,DNS:localhost"
            run(["bash", "-c", OPENSSL_GEN.format(key=key, crt=crt,
                                                  sans=sans)])
        elif mode == "B":
            sans = "subjectAltName=IP:10.0.0.1,DNS:localhost"
            run(["bash", "-c", OPENSSL_GEN.format(key=key, crt=crt,
                                                  sans=sans)])
        elif mode == "D":
            sans = "subjectAltName=IP:10.0.0.1,IP:127.0.0.1,DNS:localhost"
            run(["bash", "-c", OPENSSL_GEN.format(key=key, crt=crt,
                                                  sans=sans)])
            os.unlink(key)
        elif mode == "F":
            open(crt, "w").write("not a cert\n")
            run(["bash", "-c", OPENSSL_GEN.format(
                key=os.path.join(d, "other.key"),
                crt=os.path.join(d, "other.crt"),
                sans="subjectAltName=IP:10.0.0.1")])
            # key for F: a real key so only the cert is bad
            run(["bash", "-c", "openssl genrsa -out %s 2048 >/dev/null 2>&1"
                 % key])
        elif mode == "G":
            ca_key = os.path.join(d, "ca.key")
            ca_crt = os.path.join(d, "ca.crt")
            run(["bash", "-c", OPENSSL_GEN.format(
                key=ca_key, crt=ca_crt,
                sans="subjectAltName=IP:10.0.0.1")])
            run(["bash", "-c",
                 "openssl req -newkey rsa:2048 -keyout %s -out %s -nodes "
                 "-subj /CN=10.0.0.1 >/dev/null 2>&1 && "
                 "openssl x509 -req -in %s -CA %s -CAkey %s "
                 "-CAcreateserial -out %s -days 3650 "
                 "-extfile <(printf 'subjectAltName=IP:10.0.0.1') "
                 ">/dev/null 2>&1"
                 % (key, os.path.join(d, "leaf.csr"),
                    os.path.join(d, "leaf.csr"), ca_crt, ca_key, crt)])
    elif mode == "C":
        # key present, cert missing
        run(["bash", "-c", "openssl genrsa -out %s 2048 >/dev/null 2>&1"
             % key])
    # E: both missing -- nothing to create
    before = sha(crt)
    harness = """set -eu
export PATH="%s:$PATH"
export STUB_LOG="%s" STUB_PANEL_ACTIVE=1
log() { :; }
warn() { :; }
die() { echo "DIE: $*" >&2; exit 1; }
SERVER_IP=10.0.0.1
PANEL_CERT="%s"
PANEL_KEY="%s"
%s
_PANEL_WAS_ACTIVE=1
_PANEL_RESTARTED=0
%s
_restart_panel_if_needed 0
echo "STALE=$_PANEL_CERT_STALE"
echo "RESTARTS=$(grep -c '^restart ' "$STUB_LOG" || true)"
""" % (stubdir, stub_log, crt, key, cert_section, fn_text)
    script = os.path.join(d, "harness.sh")
    with open(script, "w") as f:
        f.write(harness)
    r = run(["bash", script])
    after = sha(crt)
    regenerated = (before != after)
    m_stale = re.search(r"^STALE=(\d+)$", r.stdout, re.M)
    m_rest = re.search(r"^RESTARTS=(\d+)$", r.stdout, re.M)
    stale = int(m_stale.group(1)) if m_stale else -1
    restarts = int(m_rest.group(1)) if m_rest else -1
    return regenerated, stale, restarts, r.returncode, r.stdout + r.stderr


def main():
    src = open(INSTALL).read()
    cert_section = extract_cert_section(src)
    fn_text = extract_function(src, "_restart_panel_if_needed")
    check("S1 cert section extracted", "PANEL_CERT_STALE" in cert_section)
    check("S2 restart function extracted", fn_text is not None)
    if fn_text is None:
        print("\nTOTAL: PASS=%d FAIL=%d" % (PASS, FAIL))
        return 1
    # (mode, expect_regen, expect_stale, expect_restarts)
    cases = [
        ("A", False, 0, 0),
        ("B", True, 1, 1),
        ("C", True, 0, 1),
        ("D", True, 0, 1),
        ("E", True, 0, 1),
        ("F", True, 1, 1),
        ("G", False, 0, 0),
    ]
    for mode, exp_regen, exp_stale, exp_rest in cases:
        regen, stale, restarts, rc, out = run_case(
            cert_section, fn_text, mode)
        check("%s regen=%s stale=%s restarts=%s" % (mode, exp_regen,
                                                    exp_stale, exp_rest),
              rc == 0 and regen == exp_regen and stale == exp_stale
              and restarts == exp_rest,
              "| got regen=%s stale=%s restarts=%s rc=%s"
              % (regen, stale, restarts, rc))
    print("\nTOTAL: PASS=%d FAIL=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

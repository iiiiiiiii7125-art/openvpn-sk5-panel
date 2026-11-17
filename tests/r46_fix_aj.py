#!/usr/bin/env python3
"""R46 Fix-AJ verification -- admin password file must not clobber /etc
when the panel data dir is redirected (LIVE-R46-1).

Finding: panel/app.py `_ensure_admin_password()` wrote the generated
admin password to the hardcoded /etc/openvpn-sk5-panel/admin.pass even
when OVPN_PANEL_DATA_DIR was redirected to a temp dir. On 2026-11-18
the live re-check lane ran the AH/AE probes as root on the test machine
with a fresh temp data dir; the function generated a new random
password, wrote it to the REAL /etc file (the hash went into the
throwaway DB), and admin login went 401 until the file was restored
from backup. In the sandbox this is masked (nobody cannot write /etc).

Fix: the password path has its own env override
OVPN_PANEL_ADMIN_PASS_PATH, defaulting to the installed location
/etc/openvpn-sk5-panel/admin.pass. It deliberately does NOT follow
OVPN_PANEL_DATA_DIR: in production DATA_DIR is
$INSTALL_ROOT/panel/data while the password file lives in /etc --
following DATA_DIR would move the live file and break the installer
health gate, which reads the same hardcoded path.

Cells (each runs in a fresh subprocess with its own fresh data dir,
because the module-level constants are fixed at import):
- A1 resolve-with-override: ADMIN_PASS_PATH honors the env override.
  FAILS on bf2eacd (ignores the var, still /etc/...), PASSES on tip.
- A2 ensure-with-override: _ensure_admin_password() writes the file
  to the override path (0600), the DB hash verifies the file's
  password, and /etc/openvpn-sk5-panel is still absent afterwards.
  FAILS on baseline (file lands in the DATA_DIR fallback instead),
  PASSES on tip.
- A3 resolve-default: with no override, ADMIN_PASS_PATH is still the
  installed /etc path. PASSES on both (production default unchanged).
- A4 ensure-default-fallback: with no override, as nobody (cannot
  write /etc), the file lands in the DATA_DIR fallback, 0600, hash
  verifies. PASSES on both (existing fallback behavior preserved).
- A5 change_password still syncs both ADMIN_PASS_PATH and
  ADMIN_PASS_FALLBACK. PASSES on both.

The probe never prints a password: children redirect stdout while
_ensure_admin_password() runs and only report paths/booleans.

Run as nobody with the documented harness against a /tmp COPY of the
tree:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    OVPN_PANEL_DATA_DIR=<data> OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \\
    OVPN_SK5_CONFIG_DIR=<sk5cfg> \\
    python3 <tree-copy>/tests/r46_fix_aj.py
"""
import hashlib
import io
import os
import stat
import subprocess
import sys
import tempfile

TREE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ETC_DIR = "/etc/openvpn-sk5-panel"
ETC_PASS = "/etc/openvpn-sk5-panel/admin.pass"

FAILURES = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (" | " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILURES.append(name)


HELPER = r'''
import io, os, sys, contextlib, sqlite3
sys.path.insert(0, os.path.join(os.environ["R46AJ_TREE"], "panel"))
sys.path.insert(0, os.path.join(os.environ["R46AJ_TREE"], "core"))
sys.path.insert(0, os.path.join(os.environ["R46AJ_TREE"], "egress"))
import app as panel_app

mode = sys.argv[1]
if mode == "resolve":
    print("VALUE " + panel_app.ADMIN_PASS_PATH)
elif mode == "ensure":
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        panel_app._ensure_admin_password()
    # Where did the file land? Report paths only, never contents.
    landed = []
    for p in (os.environ.get("OVPN_PANEL_ADMIN_PASS_PATH", ""),
              panel_app.ADMIN_PASS_FALLBACK,
              "/etc/openvpn-sk5-panel/admin.pass"):
        if p and os.path.exists(p) and p not in landed:
            landed.append(p)
    # Does the DB hash verify the landed file's password?
    verified = False
    mode_ok = False
    target = os.environ.get("OVPN_PANEL_ADMIN_PASS_PATH", "") or None
    check_path = target if (target and os.path.exists(target)) else None
    if check_path is None and landed:
        check_path = landed[0]
    if check_path:
        with open(check_path, "r", encoding="utf-8") as f:
            pw = f.read().strip()
        mode_ok = (os.stat(check_path).st_mode & 0o777) == 0o600
        conn = sqlite3.connect(panel_app.DB_PATH)
        row = conn.execute("SELECT password_hash FROM admin WHERE id = 1").fetchone()
        conn.close()
        if row:
            verified = panel_app._check_password(pw, row[0])
    etc_exists = os.path.exists("/etc/openvpn-sk5-panel")
    print("LANDED " + ",".join(landed))
    print("VERIFIED " + str(verified) + " MODE600 " + str(mode_ok)
          + " ETC_EXISTS " + str(etc_exists))
'''


def run_child(mode, data_dir, override=None):
    """Run the helper in a fresh subprocess; returns its stdout lines."""
    helper_path = os.path.join(tempfile.gettempdir(), "r46aj_helper.py")
    with open(helper_path, "w", encoding="utf-8") as f:
        f.write(HELPER)
    env = dict(os.environ)
    env["R46AJ_TREE"] = TREE
    env["OVPN_PANEL_DATA_DIR"] = data_dir
    env["OVPN_PANEL_SECRET_PATH"] = os.path.join(data_dir, "secret.key")
    if override is None:
        env.pop("OVPN_PANEL_ADMIN_PASS_PATH", None)
    else:
        env["OVPN_PANEL_ADMIN_PASS_PATH"] = override
    out = subprocess.run([sys.executable, helper_path, mode],
                         capture_output=True, text=True, timeout=120,
                         env=env)
    if out.returncode != 0:
        raise RuntimeError("helper %s failed rc=%d: %s" %
                           (mode, out.returncode, out.stderr[-500:]))
    return out.stdout


def fresh_data_dir():
    d = tempfile.mkdtemp(prefix="r46aj-data-")
    os.chmod(d, 0o777)
    return d


def main():
    # Precondition: the sandbox host must not have the /etc dir at all,
    # or the "still absent" assertions are meaningless.
    check("P0-etc-absent-at-start", not os.path.exists(ETC_DIR),
          "etc dir present before the run" if os.path.exists(ETC_DIR) else "")

    # A1: resolution honors the override.
    d1 = fresh_data_dir()
    override1 = os.path.join(d1, "admin.pass")
    lines = run_child("resolve", d1, override1)
    val = [l for l in lines.splitlines() if l.startswith("VALUE ")][0][6:]
    check("A1-resolve-honors-override", val == override1,
          "ADMIN_PASS_PATH=%s" % val)

    # A2: ensure writes to the override path, hash verifies, /etc untouched.
    # The override lives in a DIFFERENT dir from DATA_DIR, so landing
    # there proves the override (not the fallback) was used.
    d2 = fresh_data_dir()
    ov2 = tempfile.mkdtemp(prefix="r46aj-override-")
    os.chmod(ov2, 0o777)
    override2 = os.path.join(ov2, "admin.pass")
    lines = run_child("ensure", d2, override2)
    landed = [l for l in lines.splitlines() if l.startswith("LANDED ")][0][7:]
    ver = [l for l in lines.splitlines() if l.startswith("VERIFIED ")][0]
    check("A2-ensure-writes-override-path",
          landed == override2 and "VERIFIED True" in ver and "MODE600 True" in ver
          and "ETC_EXISTS False" in ver,
          "landed=%s %s" % (landed, ver))

    # A3: default resolution unchanged.
    d3 = fresh_data_dir()
    lines = run_child("resolve", d3, None)
    val = [l for l in lines.splitlines() if l.startswith("VALUE ")][0][6:]
    check("A3-resolve-default-is-etc", val == ETC_PASS,
          "ADMIN_PASS_PATH=%s" % val)

    # A4: default fallback still works as nobody.
    d4 = fresh_data_dir()
    expect4 = os.path.join(d4, "admin.pass")
    lines = run_child("ensure", d4, None)
    landed = [l for l in lines.splitlines() if l.startswith("LANDED ")][0][7:]
    ver = [l for l in lines.splitlines() if l.startswith("VERIFIED ")][0]
    check("A4-ensure-default-falls-back-to-datadir",
          landed == expect4 and "VERIFIED True" in ver and "MODE600 True" in ver
          and "ETC_EXISTS False" in ver,
          "landed=%s %s" % (landed, ver))

    # A5: change_password still syncs both paths.
    src = open(os.path.join(TREE, "panel", "app.py"),
               encoding="utf-8").read()
    seg = src[src.index("def change_password"):]
    seg = seg[:seg.index("def me(")]
    check("A5-change-password-syncs-both-paths",
          "ADMIN_PASS_PATH" in seg and "ADMIN_PASS_FALLBACK" in seg
          and "for path in (ADMIN_PASS_PATH, ADMIN_PASS_FALLBACK)" in seg,
          "sync loop present" if "ADMIN_PASS_PATH" in seg else "loop missing")

    check("P9-etc-still-absent-at-end", not os.path.exists(ETC_DIR),
          "etc dir appeared during the run" if os.path.exists(ETC_DIR) else "")

    print("TOTAL: PASS=%d FAIL=%d %s"
          % (7 - len(FAILURES), len(FAILURES), FAILURES), flush=True)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())

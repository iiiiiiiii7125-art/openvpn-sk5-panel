#!/usr/bin/env python3
"""R46 Fix-AE verification -- Flask staleness + panel restart on code change.

Findings:
- R46-L2-1: _current_bundle_sha256() memoized the bundle hash in
  _BUNDLE_SHA256_CACHE, so a code-only upgrade without a panel restart
  made agent_code_outdated lie in BOTH directions.
- LIVE-R45-4: install.sh restarted the panel only on cert regen /
  proxy-env change, so a code-only upgrade never restarted it.

Fix: app.py recomputes the bundle hash on every call (no cache);
install.sh records a content hash of the installed panel code before
the tree copy, compares it after the copy + launcher regeneration,
and restarts an already-running panel when the code changed
(_PANEL_CODE_CHANGED), while a same-content re-run stays a no-op.

Half A (Flask, live panel via test_client): H7 pattern -- the bundle
hash changes under the live process; the outdated flag must follow
the NEW hash, not the memoized one.
Half B (installer, extracted functions + stub systemctl): the content
hash and the restart trigger, driven as the two call sites would.

Run as nobody with the documented harness against a /tmp COPY of the
tree (Half A mutates <tree>/agent/agent.py mid-run and restores it):
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    OVPN_PANEL_DATA_DIR=<data> OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \\
    OVPN_SK5_CONFIG_DIR=<sk5cfg> \\
    python3 <tree-copy>/tests/r46_fix_ae.py
The tree copy needs agent/agent.py writable by nobody
(chmod a+w <tree>/agent/agent.py); a failed append FAILs H7b with a
clear message instead of crashing the probe.

Baseline e7f18ff fails: A-cells H7c/H7d (memoized hash), B1/B2 (no
_panel_code_hash to extract), B3/B6 (no code-change trigger), B7
(static wiring). B4/B5 pass on both trees (controls -- no restart
either way when the code did not change / the panel never ran).
Disclosure (BH-03(c)): the R46-L5 audit probe's F17 cell pins the
removed behavior ("memoised value does NOT move after the change") --
it fails on the fixed tree BY DESIGN, because _current_bundle_sha256()
now recomputes per call. The audit probe itself is NOT edited by this
lane (it lives only in the audit worktree); this probe asserts the
fixed behavior instead. When F17 is adopted into the tree, its second
cell must flip to assert the value DOES move.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

TREE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INSTALL = os.path.join(TREE, "install.sh")
sys.path.insert(0, os.path.join(TREE, "panel"))
sys.path.insert(0, os.path.join(TREE, "core"))
sys.path.insert(0, os.path.join(TREE, "egress"))

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


# ---------------------------------------------------------------- Half A: Flask
import app as panel  # noqa: E402

DATA = os.environ["OVPN_PANEL_DATA_DIR"]

pw = panel._ensure_admin_password()
if pw is None:
    pw = open(os.path.join(DATA, "admin.pass")).read().strip()
client = panel.app.test_client()
r = client.post("/api/login", json={"password": pw})
check("A00 login works", r.status_code == 200, r.status_code)

PANEL_URL = "https://panel.example:8443"
HB = {"version": "1.0", "hostname": "h1",
      "openvpn_running": True, "sk5_enabled": False}


def register(name):
    return client.post("/api/nodes",
                       json={"name": name, "panel_url": PANEL_URL})


def poll(name, token, status):
    return client.post("/api/agent/poll", json={
        "node_name": name, "panel_url": PANEL_URL, "status": status},
        headers={"Authorization": "Bearer " + token})


def nodes():
    return client.get("/api/nodes").get_json().get("nodes", [])


def node_entry(name):
    for n in nodes():
        if n.get("name") == name:
            return n
    return {}


def cur_hash():
    rr = client.get("/api/agent/bundle.sha256")
    return rr.get_data(as_text=True).split()[0] if rr.status_code == 200 else ""


r = register("ae1")
TOK = r.get_json().get("token") if r.status_code == 201 else ""
check("A01 register ae1", r.status_code == 201, r.status_code)

CUR = cur_hash()
check("A02 current bundle hash is 64-hex", len(CUR) == 64
      and all(c in "0123456789abcdef" for c in CUR), CUR)

r = poll("ae1", TOK, dict(HB, bundle_sha256=CUR))
e = node_entry("ae1")
check("A03 pre-upgrade: current hash reports outdated False",
      e.get("agent_code_outdated") is False, e)

# Simulate a code-only upgrade under the live process: append a comment
# to agent/agent.py in THIS tree copy (restored below). The panel
# process keeps running; only the on-disk bundle changes.
AGENT_PY = os.path.join(panel.PROJECT_DIR, "agent", "agent.py")
MARKER = "\n# R46 Fix-AE: simulated panel code upgrade (restored by probe)\n"
try:
    with open(AGENT_PY, "a", encoding="utf-8") as f:
        f.write(MARKER)
except OSError as exc:
    check("A04 bundle hash changes under the live process",
          False, "tree not writable: %s" % exc)
    CUR2 = CUR
else:
    CUR2 = cur_hash()
    check("A04 bundle hash changes under the live process",
          CUR2 != CUR and len(CUR2) == 64, "%s -> %s" % (CUR, CUR2))
    # Node still on the OLD hash is now stale.
    e = node_entry("ae1")
    check("A05 post-upgrade old hash: outdated must be True",
          e.get("agent_code_outdated") is True, e)
    # Node updated to the NEW hash is current.
    r = poll("ae1", TOK, dict(HB, bundle_sha256=CUR2))
    e = node_entry("ae1")
    check("A06 post-upgrade new hash: outdated must be False",
          e.get("agent_code_outdated") is False, e)
finally:
    try:
        with open(AGENT_PY, "r", encoding="utf-8") as f:
            text = f.read()
        with open(AGENT_PY, "w", encoding="utf-8") as f:
            f.write(text.replace(MARKER, ""))
    except OSError:
        pass
    CUR3 = cur_hash()
    check("A07 marker restored, bundle hash back to original",
          CUR3 == CUR, CUR3)

# Static: the memoization is gone, the hash is recomputed per call.
_app_src = open(os.path.join(TREE, "panel", "app.py"),
                encoding="utf-8").read()
check("A08 no _BUNDLE_SHA256_CACHE left in panel/app.py",
      "_BUNDLE_SHA256_CACHE" not in _app_src)
check("A09 _current_bundle_sha256 recomputes (no global cache)",
      "global _BUNDLE_SHA256_CACHE" not in _app_src
      and "hashlib.sha256(_build_agent_bundle().read()).hexdigest()"
      in _app_src)

# ---------------------------------------------------------------- Half B: installer
_src = open(INSTALL, encoding="utf-8").read()


def extract_function(src, name):
    """Return the `name() { ... }` definition, or None."""
    lines = src.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.startswith(name + "() {")), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines))
                if lines[i] == "}"), None)
    if end is None:
        return None
    return "\n".join(lines[start:end + 1])


HASH_FN = extract_function(_src, "_panel_code_hash")
RESTART_FN = extract_function(_src, "_restart_panel_if_needed")

STUB_SYSTEMCTL = """#!/usr/bin/env bash
# Stub systemctl: is-active answers from env, restart is logged.
if [ "$1" = "is-active" ]; then
    _unit="${@: -1}"
    case "$_unit" in
        openvpn-sk5-panel) [ "${STUB_PANEL_ACTIVE:-0}" = "1" ] && exit 0 || exit 3 ;;
        *) exit 3 ;;
    esac
fi
if [ "$1" = "restart" ]; then
    echo "restart $2" >> "$STUB_LOG"
    [ "${STUB_RESTART_FAIL:-0}" = "1" ] && exit 1 || exit 0
fi
exit 0
"""


def run_hash(fn_text, install_root):
    """Run the extracted _panel_code_hash against a fake install root."""
    d = tempfile.mkdtemp(prefix="r46fixae-hash-")
    script = os.path.join(d, "h.sh")
    with open(script, "w") as f:
        f.write("set -eu\nINSTALL_ROOT=%s\n%s\n_panel_code_hash\n"
                % (install_root, fn_text))
    r = run(["bash", script])
    return r.stdout.strip(), r.returncode, r.stdout + r.stderr


def fake_install_root():
    """A fake $INSTALL_ROOT with a panel tree (app.py + templates)."""
    d = tempfile.mkdtemp(prefix="r46fixae-root-")
    panel_dir = os.path.join(d, "panel")
    os.makedirs(os.path.join(panel_dir, "templates"))
    os.makedirs(os.path.join(panel_dir, "data"))
    with open(os.path.join(panel_dir, "app.py"), "w") as f:
        f.write("print('v1')\n")
    with open(os.path.join(panel_dir, "templates", "index.html"),
              "w") as f:
        f.write("<html>v1</html>\n")
    with open(os.path.join(panel_dir, "requirements.txt"), "w") as f:
        f.write("Flask==3.1.3\n")
    with open(os.path.join(d, "run-panel-tls.py"), "w") as f:
        f.write("# launcher v1\n")
    return d


if HASH_FN is None:
    check("B1 content change changes the hash", False,
          "_panel_code_hash not found in install.sh")
    check("B2 touch/data/pycache do not change the hash", False,
          "_panel_code_hash not found in install.sh")
else:
    root = fake_install_root()
    h1, rc1, out1 = run_hash(HASH_FN, root)
    check("B1a baseline hash computes", rc1 == 0 and len(h1) == 64, out1)
    # Content change -> hash changes.
    with open(os.path.join(root, "panel", "app.py"), "a") as f:
        f.write("# v2\n")
    h2, rc2, out2 = run_hash(HASH_FN, root)
    check("B1 content change changes the hash",
          rc2 == 0 and h2 != h1, "%s -> %s" % (h1, h2))
    # mtime-only change -> hash stable.
    h3, rc3, out3 = run_hash(HASH_FN, root)
    os.utime(os.path.join(root, "panel", "app.py"),
             (1700000000, 1700000000))
    h4, rc4, out4 = run_hash(HASH_FN, root)
    check("B2a touch-only does not change the hash",
          rc3 == 0 and rc4 == 0 and h3 == h4, "%s vs %s" % (h3, h4))
    # Runtime state + pycache changes -> hash stable.
    with open(os.path.join(root, "panel", "data", "panel.db"), "w") as f:
        f.write("live db bytes")
    os.makedirs(os.path.join(root, "panel", "__pycache__"))
    with open(os.path.join(root, "panel", "__pycache__",
                           "app.cpython-312.pyc"), "w") as f:
        f.write("bytecode")
    h5, rc5, out5 = run_hash(HASH_FN, root)
    check("B2b data/ + __pycache__ do not change the hash",
          rc5 == 0 and h5 == h4, "%s vs %s" % (h4, h5))
    # Launcher change -> hash changes.
    with open(os.path.join(root, "run-panel-tls.py"), "a") as f:
        f.write("# v2\n")
    h6, rc6, out6 = run_hash(HASH_FN, root)
    check("B2c launcher change changes the hash",
          rc6 == 0 and h6 != h5, "%s -> %s" % (h5, h6))


def run_scenario(fn_text, *, code_changed, was, active,
                 domain_call=True, restart_fail=False):
    """Run the extracted restart function as the two call sites would.

    Returns (restart_attempts, flag, returncode, output).
    """
    d = tempfile.mkdtemp(prefix="r46fixae-")
    stubdir = os.path.join(d, "bin")
    os.makedirs(stubdir)
    stub = os.path.join(stubdir, "systemctl")
    with open(stub, "w") as f:
        f.write(STUB_SYSTEMCTL)
    os.chmod(stub, 0o755)
    stub_log = os.path.join(d, "stub.log")
    harness_log = os.path.join(d, "harness.log")
    open(stub_log, "w").close()
    open(harness_log, "w").close()
    harness = """set -eu
export PATH="%s:$PATH"
export STUB_LOG="%s" HARNESS_LOG="%s"
export STUB_PANEL_ACTIVE="%s" STUB_RESTART_FAIL="%s"
log() { echo "[install] $*" >> "$HARNESS_LOG"; }
warn() { echo "[install] WARN: $*" >> "$HARNESS_LOG"; }
die() { echo "[install] ERROR: $*" >> "$HARNESS_LOG"; exit 1; }
_PANEL_CERT_STALE=0
_PANEL_CERT_REGEN=0
_PANEL_CODE_CHANGED=%s
_PANEL_WAS_ACTIVE=%s
_PANEL_RESTARTED=0
%s
%s
_restart_panel_if_needed 0
echo "RESTARTS=$(grep -c '^restart ' "$STUB_LOG" || true)"
echo "FLAG=$_PANEL_RESTARTED"
""" % (stubdir, stub_log, harness_log, "1" if active else "0",
       "1" if restart_fail else "0", "1" if code_changed else "0",
       "1" if was else "0", fn_text,
       '_restart_panel_if_needed 0' if domain_call else
       '# domain section skipped')
    script = os.path.join(d, "harness.sh")
    with open(script, "w") as f:
        f.write(harness)
    r = run(["bash", script])
    out = r.stdout + r.stderr
    m_restarts = re.search(r"^RESTARTS=(\d+)$", out, re.M)
    m_flag = re.search(r"^FLAG=(\d+)$", out, re.M)
    return ((int(m_restarts.group(1)) if m_restarts else -1),
            (int(m_flag.group(1)) if m_flag else -1),
            r.returncode, out)


if RESTART_FN is None:
    for name in ("B3 code change + running panel -> exactly one restart",
                 "B4 code unchanged + running panel -> no restart",
                 "B5 code changed + panel never ran -> no restart",
                 "B6 restart fails at domain call -> fallback retries"):
        check(name, False, "_restart_panel_if_needed not found")
else:
    n, flag, rc, _ = run_scenario(RESTART_FN, code_changed=True,
                                  was=True, active=True)
    check("B3 code change + running panel -> exactly one restart",
          n == 1 and flag == 1, "restarts=%s flag=%s" % (n, flag))
    n, flag, rc, _ = run_scenario(RESTART_FN, code_changed=False,
                                  was=True, active=True)
    check("B4 code unchanged + running panel -> no restart",
          n == 0 and flag == 0, "restarts=%s flag=%s" % (n, flag))
    n, flag, rc, _ = run_scenario(RESTART_FN, code_changed=True,
                                  was=False, active=True)
    check("B5 code changed + panel never ran -> no restart",
          n == 0 and flag == 0, "restarts=%s flag=%s" % (n, flag))
    n, flag, rc, _ = run_scenario(RESTART_FN, code_changed=True,
                                  was=True, active=True, restart_fail=True)
    check("B6 restart fails at domain call -> fallback retries",
          n == 2 and flag == 0, "restarts=%s flag=%s" % (n, flag))

# Static wiring.
_lines = _src.splitlines()
check("B7a _PANEL_CODE_BEFORE computed before the tree copy",
      next((i for i, l in enumerate(_lines)
            if "_PANEL_CODE_BEFORE=" in l), 10 ** 9) <
      next((i for i, l in enumerate(_lines)
            if l.startswith('log "installing tree to')), 10 ** 9))
check("B7b _PANEL_CODE_CHANGED set before the domain restart call",
      next((i for i, l in enumerate(_lines)
            if "_PANEL_CODE_CHANGED=0" in l), 10 ** 9) <
      next((i for i, l in enumerate(_lines)
            if '_restart_panel_if_needed "$_DOMAIN_CHANGED"' in l),
           10 ** 9))
check("B7c restart function keys on _PANEL_CODE_CHANGED",
      RESTART_FN is not None and "_PANEL_CODE_CHANGED" in RESTART_FN)
check("B7d bash -n install.sh clean",
      run(["bash", "-n", INSTALL]).returncode == 0)

print("TOTAL %d cells, FAIL %d: %s"
      % (CHECKS[0], len(FAILURES), FAILURES))
sys.exit(1 if FAILURES else 0)

#!/usr/bin/env python3
"""R47 Fix-BC probe (OpenVPN core).

Proves each Fix-BC finding by behavior. Every cell asserts the FIXED
behavior, so it FAILs on the 1.0.3 baseline and PASSes on the fixed
tree:
- L4-1 stop_server kills a direct-fallback daemon (no systemctl rc=0
  short-circuit).
- L4-2 non-UTF-8 status log: server_status() does not raise; the
  daemon still reports running with clients=[] and a status_error note.
- L4-3a valid user with a missing cert file: revoke repairs by serial
  (repaired=True, CRL carries the serial), then create works again.
- L4-3b stray issued cert (duplicate serial): create clears it and
  succeeds; the original user is untouched.
- L4-3b2 stray issued cert (unique serial): create succeeds and the
  orphaned serial lands on the CRL.
- L4-3c repair_pki() repairs both shapes in one call and is idempotent.
- L4-4 server_cert_info(): built cert ~825d + no warning; crafted
  expired cert -> expired + warning. Panel renew endpoint renews the
  cert; /api/status carries server_cert; panel repair endpoint fixes
  a wedge and audits it; panel create with a stray audits the repair.
- L3-2 agent revoke on a stopped server does NOT restart it
  (was_running guard, Flask face parity).

Real EasyRSA 3.1.7 + real OpenSSL + real OpenVPN 2.6.14 binary
(toolchain copies) for the PKI phases; fake openvpn daemon + fake
systemctl only where the product's own lifecycle logic is the subject
(same split as the R47-L4 audit probe).

Run as ROOT (the status-log candidates live under /var/log and /run;
the panel helper redirects its admin password into a scratch data dir
-- LIVE-R46-1 -- so no /etc file is ever touched):
  python3 tests/r47_bc_core.py
Panel/agent helpers run in subprocesses (venv python for Flask).
"""
import io
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WORKTREE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKTREE / "core"))
sys.path.insert(0, str(WORKTREE))

SCRATCH = Path("/tmp/r47bc")
TOOLCHAIN = Path("/home/hatch/workspace/.scratch-r46l4/toolchain")
EASYRSA_317_SRC = TOOLCHAIN / "EasyRSA-3.1.7"
OVPN2614 = TOOLCHAIN / "ovpn2614"
OVPNLIBS = TOOLCHAIN / "ovpnlibs"
VENV_PY = "/tmp/r47bc-venv/bin/python3"

CA_DIR = SCRATCH / "ca"
SRV_DIR = SCRATCH / "srv"
PID_FILE = SCRATCH / "pid" / "server.pid"
ORIG_PATH = os.environ.get("PATH", "")

CELLS: list[tuple[str, bool, str]] = []
DAEMONS: list[int] = []


def cell(name: str, ok: bool, evidence: str = "") -> None:
    CELLS.append((name, ok, evidence))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + evidence) if evidence else ""))


def sh(cmd, env=None, timeout=120):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=e)


def setup_env() -> None:
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    (SCRATCH / "bin").mkdir(parents=True)
    (SCRATCH / "fakebin").mkdir(parents=True)
    shutil.copytree(EASYRSA_317_SRC, SCRATCH / "easyrsa317")
    os.chmod(SCRATCH / "easyrsa317" / "easyrsa", 0o755)
    ld = ":".join([
        str(OVPN2614 / "usr/lib/x86_64-linux-gnu"),
        str(OVPNLIBS / "lib/x86_64-linux-gnu"),
        str(OVPNLIBS / "usr/lib/x86_64-linux-gnu"),
    ])
    (SCRATCH / "bin" / "openvpn").write_text(
        "#!/bin/bash\nexport LD_LIBRARY_PATH=%s\n"
        "exec %s \"$@\"\n" % (ld, OVPN2614 / "usr/sbin/openvpn"))
    os.chmod(SCRATCH / "bin" / "openvpn", 0o755)
    # Fake openvpn: daemonises like --daemon, stays alive as a process
    # whose cmdline[0] names the openvpn path (the identity check's
    # "script case"). Never touches the network.
    (SCRATCH / "fakebin" / "openvpn").write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "args = sys.argv[1:]\n"
        "if '--version' in args:\n"
        "    print('OpenVPN 2.6.14 x86_64-pc-linux-gnu')\n"
        "    sys.exit(0)\n"
        "pidfile = args[args.index('--writepid') + 1] if '--writepid' in args else None\n"
        "pid = os.fork()\n"
        "if pid > 0:\n"
        "    if pidfile:\n"
        "        open(pidfile, 'w').write(str(pid))\n"
        "    os._exit(0)\n"
        "os.setsid()\n"
        "devnull = os.open(os.devnull, os.O_RDWR)\n"
        "os.dup2(devnull, 0); os.dup2(devnull, 1); os.dup2(devnull, 2)\n"
        "os.execv('/bin/sleep', [sys.argv[0], '3600'])\n")
    os.chmod(SCRATCH / "fakebin" / "openvpn", 0o755)
    # Fake systemctl: rc values driven by FAKECTL_* env vars.
    (SCRATCH / "fakebin" / "systemctl").write_text(
        "#!/bin/bash\n"
        "case \"$1\" in\n"
        "  is-active) exit ${FAKECTL_ISACTIVE_RC:-1};;\n"
        "  stop) exit ${FAKECTL_STOP_RC:-0};;\n"
        "  start) exit ${FAKECTL_START_RC:-1};;\n"
        "  restart) exit ${FAKECTL_RESTART_RC:-1};;\n"
        "  show) echo \"${FAKECTL_MAINPID:-0}\"; exit 0;;\n"
        "  *) exit 1;;\n"
        "esac\n")
    os.chmod(SCRATCH / "fakebin" / "systemctl", 0o755)


def kill_daemons() -> None:
    for pid in DAEMONS:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    DAEMONS.clear()


def openssl(*args, timeout=60):
    return sh(["openssl", *args], timeout=timeout)


def crl_has_serial(crl: Path, serial: str) -> bool:
    p = openssl("crl", "-in", str(crl), "-noout", "-text")
    if p.returncode != 0:
        return False
    flat = p.stdout.upper().replace(":", "").replace(" ", "")
    return serial.upper().lstrip("0") in flat or serial.upper() in flat


PANEL_HELPER = r'''
import io, json, os, sys, contextlib
sys.path.insert(0, os.path.join(os.environ["R47BC_TREE"], "panel"))
sys.path.insert(0, os.path.join(os.environ["R47BC_TREE"], "core"))
sys.path.insert(0, os.path.join(os.environ["R47BC_TREE"], "egress"))
import app as panel_app

mode = sys.argv[1]

with contextlib.redirect_stdout(io.StringIO()):
    panel_app._ensure_admin_password()
pw_path = os.environ["OVPN_PANEL_ADMIN_PASS_PATH"]
with open(pw_path, "r", encoding="utf-8") as f:
    admin_pw = f.read().strip()

client = panel_app.app.test_client()

def login(pw):
    return client.post("/api/login", json={"password": pw}).status_code

def out(obj):
    print(json.dumps(obj))

assert login(admin_pw) == 200

if mode == "status":
    r = client.get("/api/status")
    d = r.get_json(silent=True) or {}
    out({"status": r.status_code, "openvpn": d.get("openvpn", {})})
elif mode == "renew":
    import openvpn_manager as om
    before = om._cert_serial_hex(
        __import__("pathlib").Path(os.environ["OPENVPN_SERVER_DIR"]) / "server.crt")
    r = client.post("/api/openvpn/renew-server-cert", json={})
    d = r.get_json(silent=True) or {}
    after = om._cert_serial_hex(
        __import__("pathlib").Path(os.environ["OPENVPN_SERVER_DIR"]) / "server.crt")
    out({"status": r.status_code, "body": d,
         "serial_before": before, "serial_after": after})
elif mode == "repair":
    from pathlib import Path
    import shutil
    ca = Path(os.environ["OPENVPN_CA_DIR"])
    (ca / "pki" / "issued" / "pw1.crt").unlink()
    r = client.post("/api/openvpn/pki/repair", json={})
    d = r.get_json(silent=True) or {}
    users = client.get("/api/openvpn/users").get_json(silent=True) or {}
    audit = client.get("/api/audit").get_json(silent=True) or {}
    rows = audit.get("rows", audit.get("audit", [])) if isinstance(audit, dict) else []
    actions = [row.get("action") for row in rows if isinstance(row, dict)]
    out({"status": r.status_code, "report": d.get("report"),
         "pw1": [u for u in users.get("users", []) if u.get("name") == "pw1"],
         "audit_has_repair": "openvpn_pki_repair" in actions})
elif mode == "create_stray":
    from pathlib import Path
    import shutil
    ca = Path(os.environ["OPENVPN_CA_DIR"])
    shutil.copy(ca / "pki" / "issued" / "a2.crt",
                ca / "pki" / "issued" / "ghost9.crt")
    r = client.post("/api/openvpn/users", json={"name": "ghost9"})
    d = r.get_json(silent=True) or {}
    audit = client.get("/api/audit").get_json(silent=True) or {}
    rows = audit.get("rows", audit.get("audit", [])) if isinstance(audit, dict) else []
    actions = [row.get("action") for row in rows if isinstance(row, dict)]
    users = client.get("/api/openvpn/users").get_json(silent=True) or {}
    out({"status": r.status_code, "body": d,
         "ghost9": [u for u in users.get("users", []) if u.get("name") == "ghost9"],
         "audit_has_repair": "openvpn_pki_repair" in actions})
'''

AGENT_HELPER = r'''
import json, os, sys
sys.path.insert(0, os.path.join(os.environ["R47BC_TREE"], "agent"))
sys.path.insert(0, os.path.join(os.environ["R47BC_TREE"], "core"))
sys.path.insert(0, os.path.join(os.environ["R47BC_TREE"], "egress"))
import openvpn_manager as om
import agent as agent_mod

def out(obj):
    print(json.dumps(obj))

om.revoke_user = lambda name, *a, **k: {"revoked": name}
agent_mod.openvpn_manager.revoke_user = om.revoke_user
before = om.server_status()
result = agent_mod.action_revoke_user({"name": "alice"})
calls = open(os.environ["R47BC_SYSCTL_LOG"]).read()
out({"before_running": before["running"],
     "restart_called": "restart openvpn-server@server" in calls,
     "after_running": result["server"]["running"],
     "restarted": result.get("restarted")})
'''

STUB_SYSTEMCTL = r'''#!/bin/sh
# Faithful-enough systemd stub: state file holds "active" or "inactive".
# is-active reflects it; restart always succeeds and makes it active
# (systemctl restart on a stopped unit STARTS it); stop makes it inactive.
STATE_FILE="$R47BC_SYSCTL_STATE"
CALL_LOG="$R47BC_SYSCTL_LOG"
echo "$@" >> "$CALL_LOG"
read_state() { [ -f "$STATE_FILE" ] && cat "$STATE_FILE" || echo inactive; }
case "$1" in
  is-active) [ "$(read_state)" = "active" ] && exit 0 || exit 3 ;;
  restart) echo active > "$STATE_FILE"; exit 0 ;;
  stop) echo inactive > "$STATE_FILE"; exit 0 ;;
  start) echo active > "$STATE_FILE"; exit 0 ;;
  is-enabled) exit 1 ;;
  show) echo 0; exit 0 ;;
  *) exit 1 ;;
esac
'''


def run_panel_helper(mode):
    data = tempfile.mkdtemp(prefix="r47bc-panel-")
    sk5cfg = tempfile.mkdtemp(prefix="r47bc-sk5-")
    env = dict(os.environ)
    env["R47BC_TREE"] = str(WORKTREE)
    env["PATH"] = "%s:%s" % (SCRATCH / "bin", ORIG_PATH)
    env["OPENVPN_CA_DIR"] = str(CA_DIR)
    env["OPENVPN_SERVER_DIR"] = str(SRV_DIR)
    env["OPENVPN_PID_FILE"] = str(PID_FILE)
    env["OPENVPN_SERVER_IP"] = "203.0.113.7"
    env["EASYRSA_BIN"] = str(SCRATCH / "easyrsa317" / "easyrsa")
    env["OVPN_PANEL_DATA_DIR"] = data
    env["OVPN_PANEL_SECRET_PATH"] = os.path.join(data, "secret.key")
    env["OVPN_PANEL_ADMIN_PASS_PATH"] = os.path.join(data, "admin.pass")
    env["OVPN_SK5_CONFIG_DIR"] = sk5cfg
    proc = subprocess.run(
        [VENV_PY, "-c", PANEL_HELPER, mode],
        capture_output=True, text=True, env=env, timeout=300)
    if proc.returncode != 0:
        return {"helper_error": proc.stderr[-800:] + proc.stdout[-400:]}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"helper_error": "no JSON: " + proc.stdout[-400:] + proc.stderr[-400:]}


def run_agent_helper():
    tmp = tempfile.mkdtemp(prefix="r47bc-agent-")
    bindir = os.path.join(tmp, "bin")
    os.makedirs(bindir)
    stub = os.path.join(bindir, "systemctl")
    with open(stub, "w") as f:
        f.write(STUB_SYSTEMCTL)
    os.chmod(stub, 0o755)
    state = os.path.join(tmp, "state")
    with open(state, "w") as f:
        f.write("inactive")
    log = os.path.join(tmp, "calls.log")
    with open(log, "w") as f:
        f.write("")
    env = dict(os.environ)
    env["R47BC_TREE"] = str(WORKTREE)
    env["PATH"] = bindir + ":" + ORIG_PATH
    env["R47BC_SYSCTL_STATE"] = state
    env["R47BC_SYSCTL_LOG"] = log
    env["OPENVPN_CA_DIR"] = os.environ.get("OPENVPN_CA_DIR", "/tmp/r17/fixture-ca")
    env["OPENVPN_SERVER_DIR"] = os.environ.get("OPENVPN_SERVER_DIR", "/tmp/r17/fixture-server")
    env["OPENVPN_PID_FILE"] = os.path.join(tmp, "server.pid")
    proc = subprocess.run(
        [sys.executable, "-c", AGENT_HELPER],
        capture_output=True, text=True, env=env, timeout=120)
    if proc.returncode != 0:
        return {"helper_error": proc.stderr[-800:]}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"helper_error": "no JSON: " + proc.stdout[-400:] + proc.stderr[-400:]}


def main() -> int:
    setup_env()
    os.environ["PATH"] = "%s:%s" % (SCRATCH / "bin", ORIG_PATH)
    os.environ["EASYRSA_BIN"] = str(SCRATCH / "easyrsa317" / "easyrsa")
    os.environ["OPENVPN_CA_DIR"] = str(CA_DIR)
    os.environ["OPENVPN_SERVER_DIR"] = str(SRV_DIR)
    os.environ["OPENVPN_PID_FILE"] = str(PID_FILE)
    os.environ["OPENVPN_SERVER_IP"] = "203.0.113.7"

    import openvpn_manager as om  # noqa: E402

    # ---- build a real PKI + server cert + users ----------------
    try:
        om.init_pki()
        om.build_server_cert()
        for name in ("a1", "a2", "a3", "pw1"):
            om.create_user(name)
        cell("setup real PKI + server cert + 4 users", True, "a1,a2,a3,pw1")
    except Exception as exc:  # noqa: BLE001
        cell("setup real PKI + server cert + 4 users", False,
             "%s: %s" % (type(exc).__name__, exc))
        return 1

    # ---- L4-4a: server cert info on the built cert ----------------
    try:
        info = om.server_cert_info()
        ok = (info.get("exists") is True and info.get("expired") is False
              and info.get("warning") is False
              and isinstance(info.get("days_left"), int)
              and 800 <= info["days_left"] <= 825
              and info.get("expires", "").endswith("Z"))
        cell("L4-4a server_cert_info: built cert ~825d, no warning",
             ok, str(info))
    except Exception as exc:  # noqa: BLE001
        cell("L4-4a server_cert_info: built cert ~825d, no warning", False,
             "%s: %s" % (type(exc).__name__, exc))

    # ---- L4-3a: valid user, cert file gone -> revoke repairs --------
    try:
        a1_serial = om._cert_serial_hex(CA_DIR / "pki" / "issued" / "a1.crt")
        (CA_DIR / "pki" / "issued" / "a1.crt").unlink()
        r = om.revoke_user("a1")
        crl_ok = crl_has_serial(SRV_DIR / "crl.pem", a1_serial or "")
        st = {u["name"]: u["status"] for u in om.list_users()}.get("a1")
        cell("L4-3a revoke repairs missing-cert user (repaired=True, CRL has serial)",
             r.get("repaired") is True and crl_ok and st == "revoked",
             "repaired=%s crl=%s status=%s" % (r.get("repaired"), crl_ok, st))
        ovpn = om.create_user("a1")
        st2 = {u["name"]: u["status"] for u in om.list_users()}.get("a1")
        cell("L4-3a2 re-create after repair works",
             st2 == "valid" and "-----BEGIN CERTIFICATE-----" in ovpn,
             "status=%s" % st2)
    except Exception as exc:  # noqa: BLE001
        cell("L4-3a revoke repairs missing-cert user (repaired=True, CRL has serial)", False,
             "%s: %s" % (type(exc).__name__, exc))

    # ---- L4-3b: stray cert, duplicate serial ----------------------
    try:
        a2_serial = om._cert_serial_hex(CA_DIR / "pki" / "issued" / "a2.crt")
        shutil.copy(CA_DIR / "pki" / "issued" / "a2.crt",
                    CA_DIR / "pki" / "issued" / "ghost.crt")
        ovpn = om.create_user("ghost")
        users = {u["name"]: u["status"] for u in om.list_users()}
        # The stray copy must not hijack the serial map: creating
        # "ghost" must NOT revoke the donor (the legacy migration
        # used to see a phantom valid "ghost" and revoke a2's cert).
        donor_crl = crl_has_serial(SRV_DIR / "crl.pem", a2_serial or "")
        cell("L4-3b stray duplicate-serial cert: create succeeds, donor intact",
             users.get("ghost") == "valid" and users.get("a2") == "valid"
             and not donor_crl and "-----BEGIN CERTIFICATE-----" in ovpn,
             "ghost=%s a2=%s donor_on_crl=%s"
             % (users.get("ghost"), users.get("a2"), donor_crl))
    except Exception as exc:  # noqa: BLE001
        cell("L4-3b stray duplicate-serial cert: create succeeds, donor intact", False,
             "%s: %s" % (type(exc).__name__, exc))

    # ---- L4-3b3: donor file gone, only the stray copy remains -----
    try:
        shutil.copy(CA_DIR / "pki" / "issued" / "a2.crt",
                    CA_DIR / "pki" / "issued" / "ghostx.crt")
        (CA_DIR / "pki" / "issued" / "a2.crt").unlink()
        a2_serial = om._cert_serial_hex(CA_DIR / "pki" / "issued" / "ghostx.crt")
        ovpn = om.create_user("ghostx")
        users = {u["name"]: u["status"] for u in om.list_users()}
        donor_crl = crl_has_serial(SRV_DIR / "crl.pem", a2_serial or "")
        cell("L4-3b3 donor file gone, only stray copy left: create succeeds, donor NOT revoked",
             users.get("ghostx") == "valid" and users.get("a2") == "valid"
             and not donor_crl and "-----BEGIN CERTIFICATE-----" in ovpn,
             "ghostx=%s a2=%s donor_on_crl=%s"
             % (users.get("ghostx"), users.get("a2"), donor_crl))
        # a2 is now in the missing-cert wedge (a); the repair path
        # still un-wedges it.
        r = om.revoke_user("a2")
        cell("L4-3b4 wedged donor still revocable by the repair path",
             r.get("repaired") is True,
             "repaired=%s" % r.get("repaired"))
        om.create_user("a2")
    except Exception as exc:  # noqa: BLE001
        cell("L4-3b3 donor file gone, only stray copy left: create succeeds, donor NOT revoked", False,
             "%s: %s" % (type(exc).__name__, exc))

    # ---- L4-3b2: stray cert, unique serial -> CRL -----------------
    try:
        om.create_user("orphan")
        orphan_serial = om._cert_serial_hex(CA_DIR / "pki" / "issued" / "orphan.crt")
        idx = CA_DIR / "pki" / "index.txt"
        kept = [ln for ln in idx.read_text().splitlines()
                if not (ln.startswith("V\t") and "/CN=orphan" in ln)]
        idx.write_text("\n".join(kept) + "\n")
        assert om._user_status("orphan", CA_DIR) is None, "orphan still indexed"
        ovpn = om.create_user("orphan")
        st = {u["name"]: u["status"] for u in om.list_users()}.get("orphan")
        crl_ok = crl_has_serial(SRV_DIR / "crl.pem", orphan_serial or "")
        cell("L4-3b2 stray unique-serial cert: create succeeds, old serial on CRL",
             st == "valid" and crl_ok and "-----BEGIN CERTIFICATE-----" in ovpn,
             "status=%s crl_has_old_serial=%s" % (st, crl_ok))
    except Exception as exc:  # noqa: BLE001
        cell("L4-3b2 stray unique-serial cert: create succeeds, old serial on CRL", False,
             "%s: %s" % (type(exc).__name__, exc))

    # ---- L4-3c: repair_pki repairs both shapes, idempotent --------
    try:
        (CA_DIR / "pki" / "issued" / "a3.crt").unlink()
        shutil.copy(CA_DIR / "pki" / "issued" / "a2.crt",
                    CA_DIR / "pki" / "issued" / "stray2.crt")
        report = om.repair_pki()
        kinds = {(r["name"], r["kind"]) for r in report.get("repaired", [])}
        second = om.repair_pki()
        cell("L4-3c repair_pki fixes both wedges, second call repairs nothing",
             kinds == {("a3", "missing-cert"), ("stray2", "stray-cert")}
             and second.get("repaired") == [],
             "first=%s second=%s" % (report.get("repaired"), second.get("repaired")))
        # a3 is revoked by the repair; re-create works.
        st = {u["name"]: u["status"] for u in om.list_users()}.get("a3")
        cell("L4-3c2 repaired user re-creates cleanly",
             st == "revoked" and "-----BEGIN CERTIFICATE-----" in om.create_user("a3"),
             "a3=%s" % st)
    except Exception as exc:  # noqa: BLE001
        cell("L4-3c repair_pki fixes both wedges, second call repairs nothing", False,
             "%s: %s" % (type(exc).__name__, exc))

    # ---- L4-4b: expired server cert -------------------------------
    try:
        mini = SCRATCH / "mini-ca"
        mini.mkdir(parents=True, exist_ok=True)
        sh(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(mini / "ca.key"), "-out", str(mini / "ca.crt"),
            "-subj", "/CN=mini-ca", "-days", "3650"])
        sh(["openssl", "req", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(mini / "server.key"), "-out", str(mini / "server.csr"),
            "-subj", "/CN=server"])
        (mini / "index.txt").write_text("")
        (mini / "serial").write_text("1000\n")
        (mini / "newcerts").mkdir(exist_ok=True)
        (mini / "ca.cnf").write_text(
            "[ ca ]\ndefault_ca = mini\n[ mini ]\ndatabase = %s\n"
            "new_certs_dir = %s\nserial = %s\nprivate_key = %s\n"
            "certificate = %s\ndefault_md = sha256\npolicy = pol\n"
            "[ pol ]\ncommonName = supplied\n" % (
                mini / "index.txt", mini / "newcerts", mini / "serial",
                mini / "ca.key", mini / "ca.crt"))
        p = sh(["openssl", "ca", "-config", str(mini / "ca.cnf"),
                "-in", str(mini / "server.csr"), "-out", str(mini / "server.crt"),
                "-startdate", "20200101000000Z", "-enddate", "20210101000000Z",
                "-batch", "-notext"])
        assert p.returncode == 0, p.stderr[-300:]
        (SRV_DIR / "server.crt").write_bytes((mini / "server.crt").read_bytes())
        info = om.server_cert_info()
        cell("L4-4b expired server cert: expired + warning",
             info.get("expired") is True and info.get("warning") is True
             and (info.get("days_left") or 0) < 0,
             str(info))
        # restore the real server cert for the panel cells below
        (SRV_DIR / "server.crt").write_bytes(
            (CA_DIR / "pki" / "issued" / "server.crt").read_bytes())
        info2 = om.server_cert_info()
        cell("L4-4b2 real server cert restored after the expiry cell",
             info2.get("expired") is False, str(info2))
    except Exception as exc:  # noqa: BLE001
        cell("L4-4b expired server cert: expired + warning", False,
             "%s: %s" % (type(exc).__name__, exc))

    # ---- L4-2: non-UTF-8 status log must not raise ---------------
    try:
        status_path = Path("/var/log/openvpn/openvpn-status.log")
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_bytes(b"CLIENT_LIST,alice,\xff\xfe,10.8.0.2,,1,2,2026-11-12\n")
        proc2 = subprocess.Popen([str(SCRATCH / "fakebin" / "openvpn"), "3600"],
                                 executable="/bin/sleep")
        DAEMONS.append(proc2.pid)
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(proc2.pid))
        try:
            st = om.server_status()
            cell("L4-2 non-UTF8 status file: no raise, running=True, clients=[], note set",
                 st.get("running") is True and st.get("clients") == []
                 and bool(st.get("status_error")),
                 "running=%s clients=%s status_error=%s"
                 % (st.get("running"), st.get("clients"), st.get("status_error")))
        except om.OpenVPNError as exc:
            cell("L4-2 non-UTF8 status file: no raise, running=True, clients=[], note set",
                 False, "raised OpenVPNError: %s" % exc)
        finally:
            status_path.unlink(missing_ok=True)
            PID_FILE.unlink(missing_ok=True)
            try:
                os.kill(proc2.pid, signal.SIGTERM)
            except OSError:
                pass
            DAEMONS.remove(proc2.pid)
    except Exception as exc:  # noqa: BLE001
        cell("L4-2 non-UTF8 status file: no raise, running=True, clients=[], note set", False,
             "%s: %s" % (type(exc).__name__, exc))

    # ---- L4-1: stop kills a direct-fallback daemon ----------------
    os.environ["PATH"] = "%s:%s:%s" % (SCRATCH / "fakebin", SCRATCH / "bin", ORIG_PATH)
    try:
        if PID_FILE.parent.exists():
            shutil.rmtree(PID_FILE.parent)
        om.render_server_conf(proto="udp", port=1194, server_dir=SRV_DIR, ca_dir=CA_DIR)
        st = om.start_server(SRV_DIR)
        daemon_pid = int(PID_FILE.read_text().strip())
        DAEMONS.append(daemon_pid)
        alive = True
        try:
            os.kill(daemon_pid, 0)
        except OSError:
            alive = False
        cell("L4-1a direct fallback starts daemon (setup)",
             st.get("running") is True and alive and st.get("pid") == daemon_pid,
             "pid=%s running=%s" % (daemon_pid, st.get("running")))
        os.environ.update({"FAKECTL_ISACTIVE_RC": "1", "FAKECTL_STOP_RC": "0",
                           "FAKECTL_START_RC": "1", "FAKECTL_RESTART_RC": "1",
                           "FAKECTL_MAINPID": "0"})
        st = om.stop_server(SRV_DIR)
        still_alive = True
        try:
            os.kill(daemon_pid, 0)
        except OSError:
            still_alive = False
        cell("L4-1 stop_server kills direct-fallback daemon (systemctl stop rc=0)",
             not still_alive and st.get("running") is False,
             "after stop: daemon_alive=%s returned running=%s"
             % (still_alive, st.get("running")))
        if still_alive:
            os.kill(daemon_pid, signal.SIGTERM)
            DAEMONS.remove(daemon_pid)
        else:
            DAEMONS.remove(daemon_pid)
    except Exception as exc:  # noqa: BLE001
        cell("L4-1a direct fallback starts daemon (setup)", False,
             "%s: %s" % (type(exc).__name__, exc))
    os.environ["PATH"] = "%s:%s" % (SCRATCH / "bin", ORIG_PATH)
    for k in ("FAKECTL_ISACTIVE_RC", "FAKECTL_STOP_RC", "FAKECTL_START_RC",
              "FAKECTL_RESTART_RC", "FAKECTL_MAINPID"):
        os.environ.pop(k, None)

    # ---- panel cells (subprocess helpers) -------------------------
    r = run_panel_helper("status")
    ovpn = r.get("openvpn", {}) if isinstance(r, dict) else {}
    sc = ovpn.get("server_cert") or {}
    cell("L4-4c /api/status carries server_cert expiry",
         r.get("status") == 200 and sc.get("exists") is True
         and sc.get("expired") is False and sc.get("warning") is False
         and isinstance(sc.get("days_left"), int) and 800 <= sc["days_left"] <= 825,
         "err=%s cert=%s" % (r.get("helper_error", ""), sc))

    r = run_panel_helper("renew")
    cell("L4-4d POST /api/openvpn/renew-server-cert renews the cert",
         r.get("status") == 200 and r.get("serial_before") and r.get("serial_after")
         and r["serial_before"] != r["serial_after"]
         and (r.get("body") or {}).get("restarted") is False,
         "err=%s body=%s serial %s -> %s"
         % (r.get("helper_error", ""), r.get("body"),
            r.get("serial_before"), r.get("serial_after")))

    r = run_panel_helper("repair")
    rep = (r.get("report") or {}).get("repaired", []) if isinstance(r, dict) else []
    cell("L4-3d POST /api/openvpn/pki/repair fixes the wedge + audits it",
         r.get("status") == 200
         and any(x.get("name") == "pw1" and x.get("kind") == "missing-cert" for x in rep)
         and any(u.get("status") == "revoked" for u in r.get("pw1", []))
         and r.get("audit_has_repair") is True,
         "err=%s report=%s pw1=%s audit=%s"
         % (r.get("helper_error", ""), rep, r.get("pw1"), r.get("audit_has_repair")))

    r = run_panel_helper("create_stray")
    cell("L4-3e panel create with a stray cert succeeds + audits the repair",
         r.get("status") == 200
         and any(u.get("status") == "valid" for u in r.get("ghost9", []))
         and r.get("audit_has_repair") is True,
         "err=%s body=%s ghost9=%s audit=%s"
         % (r.get("helper_error", ""), r.get("body"), r.get("ghost9"),
            r.get("audit_has_repair")))

    # ---- L3-2: agent revoke on a stopped server -------------------
    r = run_agent_helper()
    cell("L3-2 agent revoke on stopped server does NOT restart it",
         r.get("before_running") is False
         and r.get("restart_called") is False
         and r.get("after_running") is False
         and r.get("restarted") is False,
         "before=%s restart_called=%s after=%s err=%s"
         % (r.get("before_running"), r.get("restart_called"),
            r.get("after_running"), r.get("helper_error", "")))

    return 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        kill_daemons()
    failed = [c for c in CELLS if not c[1]]
    print("TOTAL %d/%d passed; %d failed" % (len(CELLS) - len(failed), len(CELLS), len(failed)))
    sys.exit(1 if failed else 0)

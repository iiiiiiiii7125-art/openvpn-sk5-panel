#!/usr/bin/env python3
"""R44-L5 state-machine census probe (AUDIT-R44, ledger+contract derivation).

Enumerates the product's state machines by code search and drives every
transition BY BEHAVIOR on baseline 46a78e8. A cell asserts the CORRECT
transition; a FAIL on the baseline is a finding (mechanism + behavior
proof in the report).

Sections:
  S1 SK5 chain (egress/sk5_manager, direct API, no TUN needed):
     partial merge, enable/disable flips, udp_over_tcp no-op + wedge,
     check_health verdicts, corrupt-config behavior.
  S2 OpenVPN service + users (core, real easy-rsa 3.1.7):
     lifecycle, stop idempotence, stale-PID false-positive + innocent
     kill, revoke-on-stopped-server starts the daemon (fake openvpn
     daemon models "daemon starts OK" only -- the transition under
     test is the panel's decision to call restart, not TUN).
  S3 queue (panel Flask test_client): dispatch/report/requeue,
     malformed/corrupt handling, double poll, wrong-node/unknown-cmd,
     heartbeat snapshot, node delete + re-register stale .ovpn.
  S4 nodes: rotate kills the old token; snapshot merge (HOLD re-run
     of the F4 age probes is done separately in the report).

Run as ROOT from the repo root: python3 tests/r44_l5_state.py
Exit code = FAIL count. Needs the Flask venv (default /tmp/r41-l5-venv)
and the pinned toolchain (tests/r41_fix_a_pki.py bootstrap).
Host hygiene: all state lives under mkdtemp scratch dirs; the probe
checks /etc/openvpn-sk5-panel is absent/empty at the end.
"""
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TREE / "tests"))
sys.path.insert(0, str(TREE / "core"))
sys.path.insert(0, str(TREE / "agent"))
sys.path.insert(0, str(TREE / "egress"))

import r41_fix_a_pki as A  # noqa: E402  (toolchain bootstrap, pinned pins)

WORK = Path(tempfile.mkdtemp(prefix="r44l5-"))
RESULTS = []
SKIPS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name
          + ((" | " + str(detail)[:400]) if detail else ""), flush=True)


def skip(name, why):
    SKIPS.append(name)
    print("SKIP " + name + " | " + why, flush=True)


def run(cmd, timeout=120, **kw):
    return A.run(cmd, timeout=timeout, **kw)


def read_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_raw(p, text):
    Path(p).write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- S1: SK5 chain
def section_s1():
    print("== S1 SK5 chain ==", flush=True)
    import sk5_manager as sm  # noqa: E402
    cfgdir = WORK / "sk5cfg"
    cfgdir.mkdir()
    os.environ["OVPN_SK5_CONFIG_DIR"] = str(cfgdir)
    # Re-point the module at the scratch dir (import-time constants).
    sm.CONFIG_DIR = cfgdir
    sm.CONFIG_FILE = cfgdir / "sk5.json"
    sm.RENDERED_CONFIG = cfgdir / "sing-box.json"
    sm.LOG_FILE = cfgdir / "sing-box.log"
    sm.PID_FILE = cfgdir / "sing-box.pid"
    sm.HEALTH_FILE = cfgdir / "health.json"
    sm.SINGBOX_BIN = "/nonexistent/sing-box"  # no binary: every start fails

    # S1a partial merge: toggle-only save keeps host/port/password.
    sm.set_sk5(host="127.0.0.1", port=11080, username="u1",
               password="pw-secret", enabled=False)
    st = sm.get_status(probe_egress=False)
    cell("S1a-1 set_sk5 stores host/port/user, password hidden",
         st.get("host") == "127.0.0.1" and st.get("port") == 11080
         and st.get("username") == "u1" and "pw-secret" not in json.dumps(st),
         f"st={st}")
    sm.set_sk5(enabled=False)  # toggle-only: no host/port/password sent
    cfg = sm._load_config()
    cell("S1a-2 toggle-only save keeps host/port/password",
         cfg.get("host") == "127.0.0.1" and cfg.get("port") == 11080
         and cfg.get("password") == "pw-secret", f"cfg={cfg}")
    sm.set_sk5(host="127.0.0.1", port=11080, password="")  # blank keeps
    cfg = sm._load_config()
    cell("S1a-3 blank password keeps stored password",
         cfg.get("password") == "pw-secret", f"pw={cfg.get('password')!r}")
    sm.set_sk5(host="127.0.0.1", port=11080, clear_password=True)
    cfg = sm._load_config()
    cell("S1a-4 clear_password wipes the stored password",
         cfg.get("password") == "", f"pw={cfg.get('password')!r}")

    # S1b flip disabled->enabled with a failing enable: disk stays False.
    sm.set_sk5(host="127.0.0.1", port=11080, password="pw2", enabled=False)
    try:
        sm.set_sk5(enabled=True)
        raised = None
    except Exception as exc:  # noqa: BLE001
        raised = str(exc)
    cfg = sm._load_config()
    cell("S1b failed enable flip leaves disk enabled=false",
         raised is not None and cfg.get("enabled") is False,
         f"raised={raised} enabled={cfg.get('enabled')}")

    # S1c/d udp_over_tcp: no-op short-circuit + the wedge.
    # Fabricate an enabled chain on disk (as if enabled earlier on a
    # real machine): the transition under test is the toggle logic.
    cfg = sm._load_config()
    cfg.update({"host": "127.0.0.1", "port": 11080, "username": "u1",
                "password": "pw2", "enabled": True, "fail_open": False,
                "udp_over_tcp": False})
    sm._save_config(cfg)
    try:
        r = sm.set_udp_over_tcp(False)  # same value, daemon down
        noop_ok = True
    except Exception as exc:  # noqa: BLE001
        noop_ok = False
        r = {"error": str(exc)}
    cell("S1c no-op same-value uot returns without touching the daemon",
         noop_ok and not sm._singbox_running(),
         f"noop_ok={noop_ok} running={sm._singbox_running()}")
    try:
        sm.set_udp_over_tcp(True)
        flip_raised = None
    except Exception as exc:  # noqa: BLE001
        flip_raised = str(exc)
    cfg = sm._load_config()
    cell("S1d-1 uot flip with failing restart raises, disk value flipped",
         flip_raised is not None and cfg.get("udp_over_tcp") is True,
         f"raised={flip_raised} uot={cfg.get('udp_over_tcp')}")
    try:
        r2 = sm.set_udp_over_tcp(True)  # retry the SAME value
        retry_raised = None
    except Exception as exc:  # noqa: BLE001
        retry_raised = str(exc)
        r2 = None
    cell("S1d-2 retry of the same uot value re-attempts or raises, "
         "never silent 200 with the daemon down",
         retry_raised is not None or sm._singbox_running(),
         f"retry_raised={retry_raised} running={sm._singbox_running()} "
         f"stored_uot={sm._load_config().get('udp_over_tcp')}")

    # S1e/f/g check_health verdicts.
    sm._save_config({**sm._default_config(), "host": "127.0.0.1",
                     "port": 11080, "enabled": False})
    h = sm.check_health()
    cell("S1e check_health on a disabled chain is chain_disabled/healthy",
         h.get("healthy") is True and h.get("action") == "chain_disabled",
         f"h={h}")
    sm._save_config({**sm._default_config(), "host": "127.0.0.1",
                     "port": 11080, "enabled": True, "fail_open": True})
    h = sm.check_health()
    cfg = sm._load_config()
    cell("S1f fail_open + dead chain fails over, disk enabled=false",
         h.get("action") == "failed_over_to_direct"
         and cfg.get("enabled") is False, f"h={h} enabled={cfg.get('enabled')}")
    sm._save_config({**sm._default_config(), "host": "127.0.0.1",
                     "port": 11080, "enabled": True, "fail_open": False})
    h = sm.check_health()
    cfg = sm._load_config()
    # Sandbox cannot write policy routing (ip rule add -> EPERM), so
    # the self-heal repair cannot run here: the documented verdict
    # for a failed repair is policy_missing with the traffic state
    # named honestly ("egresses direct"). The blackholed_kill_switch
    # verdict itself is only reachable where policy writes work --
    # recorded as needs-live, not faked here.
    cell("S1g fail_closed + dead chain + repair impossible (sandbox "
         "EPERM) -> policy_missing, traffic state named, disk stays "
         "enabled=true",
         h.get("action") == "policy_missing"
         and "egresses direct" in (h.get("detail") or "")
         and cfg.get("enabled") is True, f"h={h} enabled={cfg.get('enabled')}")

    # S1h corrupt config: check_health must not die without a verdict.
    write_raw(sm.CONFIG_FILE, "{not json")
    try:
        h = sm.check_health()
        raised = None
    except Exception as exc:  # noqa: BLE001
        h, raised = None, "%s: %s" % (type(exc).__name__, exc)
    cell("S1h check_health with a corrupt sk5.json returns a verdict, "
         "never raises out of the 60 s timer",
         raised is None and isinstance(h, dict),
         f"raised={raised} h={h}")
    st = sm.get_status(probe_egress=False)
    cell("S1i get_status with a corrupt config degrades to config_error",
         st.get("config_error") is not None, f"st={st}")

    # S1j/k disable/enable on a fresh box.
    sm._save_config(sm._default_config())
    try:
        d = sm.disable()
        dis_ok = (d.get("enabled") is False)
        dis_detail = d
    except Exception as exc:  # noqa: BLE001
        dis_ok, dis_detail = False, str(exc)
    cell("S1j disable() on a disabled chain is honest, enabled=false",
         dis_ok, f"d={dis_detail}")
    try:
        sm.enable()
        en_raised = None
    except Exception as exc:  # noqa: BLE001
        en_raised = str(exc)
    cell("S1k enable() with no SK5 configured raises",
         en_raised is not None and "no SK5 configured" in (en_raised or ""),
         f"raised={en_raised}")
    # Host hygiene: the repair paths above attempted policy writes
    # (all EPERM in the sandbox); make sure no host rule survived.
    try:
        sm._remove_policy()
    except Exception:  # noqa: BLE001
        pass
    rules = run(["ip", "rule", "show"]).stdout or ""
    cell("S1-clean host policy table unchanged (no 10.8.0.0/24 rule)",
         "10.8.0.0" not in rules, f"rules={rules}")
    return sm


# ---------------------------------------------------------------- S2: core
def make_fake_openvpn(bin_dir):
    """Fake openvpn daemon: models 'daemon starts OK' ONLY.

    Accepts --config/--daemon/--writepid/--log-append, spawns a sleep,
    writes its pid, exits 0. The transition under test is the panel's
    decision to call restart, not TUN behavior.
    """
    bin_dir = Path(bin_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "openvpn"
    script.write_text(
        '#!/bin/sh\n'
        'pidfile=""; logfile=""\n'
        'while [ $# -gt 0 ]; do case "$1" in\n'
        '  --writepid) pidfile="$2"; shift 2;;\n'
        '  --log-append) logfile="$2"; shift 2;;\n'
        '  --daemon) shift;;\n'
        '  --config) shift 2;;\n'
        '  *) shift;;\n'
        'esac; done\n'
        '[ -n "$logfile" ] && mkdir -p "$(dirname "$logfile")" '
        '&& touch "$logfile"\n'
        'sleep 3600 </dev/null >/dev/null 2>&1 &\n'
        'echo $! > "$pidfile"\n'
        'exit 0\n')
    script.chmod(0o755)
    return script


def section_s2(TC):
    print("== S2 core ==", flush=True)
    # easyrsa.sh's build-server step requires an openvpn binary on
    # PATH (it dies "openvpn binary not found" at the end otherwise).
    os.environ.update(A.ovpn_env(TC, "2.6.14"))
    # The panel routes rely on openvpn_manager's module-level
    # DEFAULT_CA_DIR/DEFAULT_SERVER_DIR, bound at import time --
    # set them BEFORE the import below (the ca/srv dirs are created
    # just after; the paths are deterministic).
    os.environ["OPENVPN_CA_DIR"] = str(WORK / "ca")
    os.environ["OPENVPN_SERVER_DIR"] = str(WORK / "srv")
    # PID_FILE is bound at import time: the env must be set BEFORE the
    # import, not after (a probe bug in the first draft did it backwards).
    os.environ["OPENVPN_PID_FILE"] = str(WORK / "ovpn.pid")
    import openvpn_manager as om  # noqa: E402
    ca = WORK / "ca"
    srv = WORK / "srv"
    ca.mkdir()
    srv.mkdir()
    with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
        om.init_pki(ca)
        om.build_server_cert(ca, srv)
    cell("S2-0 fixture CA + server cert built (real easy-rsa 3.1.7)",
         (ca / "pki" / "ca.crt").exists()
         and (srv / "server.crt").exists())

    # S2a user lifecycle.
    with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
        om.create_user("alice", ca, srv)
    u = {x["name"]: x for x in om.list_users(ca)}
    cell("S2a-1 create alice -> valid",
         u.get("alice", {}).get("status") == "valid",
         f"alice={u.get('alice')}")
    with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
        om.revoke_user("alice", ca, srv)
    u = {x["name"]: x for x in om.list_users(ca)}
    tomb = read_json(ca / "pki" / ".revoked-tombstones.json") \
        if (ca / "pki" / ".revoked-tombstones.json").exists() else {}
    cell("S2a-2 revoke alice -> revoked, tombstone recorded",
         u.get("alice", {}).get("status") == "revoked"
         and "alice" in tomb,
         f"alice={u.get('alice')} tomb={tomb}")
    try:
        with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
            om.revoke_user("alice", ca, srv)
        second = "no error"
    except Exception as exc:  # noqa: BLE001
        second = "%s: %s" % (type(exc).__name__, exc)
    cell("S2a-3 second revoke refuses (AlreadyRevokedError)",
         "AlreadyRevoked" in second, f"second={second}")
    with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
        om.create_user("alice", ca, srv)
    u = {x["name"]: x for x in om.list_users(ca)}
    cell("S2a-4 re-create after revoke -> valid, tombstone cleared",
         u.get("alice", {}).get("status") == "valid"
         and not u.get("alice", {}).get("revoked"),
         f"alice={u.get('alice')}")

    # S2b stop idempotence on a stopped server.
    pidfile = WORK / "ovpn.pid"
    if pidfile.exists():
        pidfile.unlink()
    st = om.server_status()
    cell("S2b-1 server_status with no pid file: running=false",
         st.get("running") is False, f"st={st}")
    try:
        om.stop_server()
        stop_ok = True
    except Exception as exc:  # noqa: BLE001
        stop_ok, stop_err = False, str(exc)
    cell("S2b-2 stop_server on a stopped server does not raise",
         stop_ok, f"stop_ok={stop_ok}")

    # S2c stale PID file: a pid reused by an innocent process.
    victim = subprocess.Popen(["sleep", "600"])
    try:
        pidfile.write_text(str(victim.pid) + "\n")
        st = om.server_status()
        cell("S2c-1 server_status with a PID file pointing at an "
             "innocent process reports running=false",
             st.get("running") is False,
             f"st={st} victim_pid={victim.pid}")
        try:
            om.stop_server()
            stop_raised = None
        except Exception as exc:  # noqa: BLE001
            stop_raised = str(exc)
        alive = victim.poll() is None
        cell("S2c-2 stop_server on a stale PID file leaves the "
             "innocent process alive",
             alive, f"alive={alive} stop_raised={stop_raised}")
    finally:
        if victim.poll() is None:
            victim.terminate()
            try:
                victim.wait(timeout=5)
            except subprocess.TimeoutExpired:
                victim.kill()
        if pidfile.exists():
            pidfile.unlink()

    # S2e init_pki twice / force.
    try:
        with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
            om.init_pki(ca)
        twice = "no error"
    except Exception as exc:  # noqa: BLE001
        twice = "%s: %s" % (type(exc).__name__, exc)
    cell("S2e init_pki on an existing PKI refuses without force",
         "already exists" in twice, f"twice={twice}")
    return om, ca, srv


def section_s2d_panel(om, ca, srv, TC):
    """S2d: panel DELETE revoke on a STOPPED server must not start it."""
    print("== S2d panel revoke on a stopped server ==", flush=True)
    # Render server.conf with the REAL openvpn 2.6.14 (version probe).
    # render_server_conf takes keyword dirs, NOT (ca, srv) positionally.
    env = A.ovpn_env(TC, "2.6.14")
    os.environ.update(env)
    os.environ["EASYRSA_BIN"] = A.easyrsa_bin(TC, "3.1.7")
    with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
        om.render_server_conf(server_dir=srv, ca_dir=ca)
    cell("S2d-0 server.conf rendered",
         (srv / "server.conf").exists())

    # Now swap in the fake daemon (first on PATH) for the revoke call.
    fake_dir = WORK / "fakebin"
    make_fake_openvpn(fake_dir)
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = str(fake_dir) + os.pathsep + old_path
    os.environ["OPENVPN_PID_FILE"] = str(WORK / "ovpn.pid")
    if (WORK / "ovpn.pid").exists():
        (WORK / "ovpn.pid").unlink()

    client, pw = flask_client(ca, srv)
    r = client.post("/api/openvpn/users", json={"name": "bob"})
    cell("S2d-1 create bob via panel -> 200",
         r.status_code == 200, f"status={r.status_code} body={r.get_json()}")
    st = om.server_status()
    cell("S2d-2 server is stopped before the revoke",
         st.get("running") is False, f"st={st}")
    r = client.delete("/api/openvpn/users/bob")
    d = r.get_json() or {}
    daemon_pid = None
    pidfile = WORK / "ovpn.pid"
    if pidfile.exists():
        try:
            daemon_pid = int(pidfile.read_text().strip())
        except ValueError:
            daemon_pid = None
    daemon_alive = False
    if daemon_pid:
        try:
            os.kill(daemon_pid, 0)
            daemon_alive = True
        except OSError:
            daemon_alive = False
    cell("S2d-3 DELETE revoke on a stopped server leaves it stopped",
         not daemon_alive,
         f"status={r.status_code} body={d} daemon_pid={daemon_pid} "
         f"alive={daemon_alive}")
    # Cleanup: kill the fake daemon by exact pid (never pkill by name).
    if daemon_pid and daemon_alive:
        os.kill(daemon_pid, signal.SIGTERM)
        time.sleep(0.3)
    os.environ["PATH"] = old_path
    return client


def flask_client(ca, srv):
    """Boot the panel Flask app in-process (J2/Fix-I pattern)."""
    venv = Path(os.environ.get("R44L5_VENV", "/tmp/r41-l5-venv"))
    site = venv / "lib" / "python3.12" / "site-packages"
    if not (site / "flask").exists():
        raise RuntimeError("no Flask venv at %s" % venv)
    data = Path(tempfile.mkdtemp(prefix="r44l5-data-"))
    sk5cfg = Path(tempfile.mkdtemp(prefix="r44l5-sk5-"))
    os.environ["OVPN_PANEL_DATA_DIR"] = str(data)
    os.environ["OVPN_PANEL_SECRET_PATH"] = str(data / "secret.key")
    os.environ["OVPN_SK5_CONFIG_DIR"] = str(sk5cfg)
    os.environ["OPENVPN_CA_DIR"] = str(ca)
    os.environ["OPENVPN_SERVER_DIR"] = str(srv)
    sys.path.insert(0, str(site))
    sys.path.insert(0, str(TREE / "panel"))
    import app as panel  # noqa: E402
    panel.ADMIN_PASS_PATH = str(data / "admin.pass")
    pw = panel._ensure_admin_password()
    if pw is None:
        pw = (data / "admin.pass").read_text().strip()
    client = panel.app.test_client()
    r = client.post("/api/login", json={"password": pw})
    assert r.status_code == 200, "login failed: %s" % r.status_code
    return client, pw


# ---------------------------------------------------------------- S3/S4: panel queue + nodes
def section_s3_s4(client):
    print("== S3 queue / S4 nodes ==", flush=True)
    import app as panel  # noqa: E402  (already imported by flask_client)

    def register(name="n1"):
        r = client.post("/api/nodes", json={"name": name})
        d = r.get_json() or {}
        assert r.status_code == 201, "register %s: %s" % (name, d)
        return d["token"]

    def poll(token, status=None, cmds=None):
        # _agent_auth takes Authorization: Bearer <token> (or
        # body.node_token) -- a body "token" field is ignored (401).
        body = {}
        if status is not None:
            body["status"] = status
        if cmds is not None:
            body["cmds"] = cmds
        return client.post("/api/agent/poll", json=body,
                           headers={"Authorization": "Bearer " + token})

    def report(token, cmd_id, result=None, error=None, ok=True):
        body = {"cmd_id": cmd_id, "ok": ok}
        if result is not None:
            body["result"] = result
        if error is not None:
            body["error"] = error
        return client.post("/api/agent/report", json=body,
                           headers={"Authorization": "Bearer " + token})

    def cmd_get(cid):
        return client.get("/api/cmd/%s" % cid)

    tok = register("n1")

    # S3a dispatch -> report -> done; second report 409.
    r = client.post("/api/cmd", json={"node": "n1", "action": "create_user",
                                      "params": {"name": "alice"}})
    d = r.get_json() or {}
    cid = d.get("cmd_id")
    cell("S3a-1 enqueue create_user -> 202 queued",
         r.status_code == 202 and d.get("status") == "queued",
         f"status={r.status_code} d={d}")
    p = poll(tok)
    pd = p.get_json() or {}
    cell("S3a-2 first poll dispatches the queued command",
         p.status_code == 200 and len(pd.get("commands", [])) == 1
         and pd["commands"][0].get("id") == cid,
         f"status={p.status_code} pd={pd}")
    p2 = poll(tok)
    pd2 = p2.get_json() or {}
    cell("S3a-3 second poll dispatches nothing (no double dispatch)",
         p2.status_code == 200 and pd2.get("commands") == [],
         f"pd2={pd2}")
    rr = report(tok, cid, result={"ok": True})
    cell("S3a-4 report done -> 200 done",
         rr.status_code == 200
         and (rr.get_json() or {}).get("status") == "done",
         f"status={rr.status_code} body={rr.get_json()}")
    rr2 = report(tok, cid, result={"ok": True})
    cell("S3a-5 second report for a done command -> 409",
         rr2.status_code == 409, f"status={rr2.status_code}")

    # S3b report for a queued (never sent) command -> 409.
    r = client.post("/api/cmd", json={"node": "n1", "action": "revoke_user",
                                      "params": {"name": "alice"}})
    cid_q = (r.get_json() or {}).get("cmd_id")
    rr = report(tok, cid_q, result={"ok": True})
    cell("S3b report for a queued command -> 409",
         rr.status_code == 409, f"status={rr.status_code}")

    # S3c stale sent -> requeue (retries climb), then failed at the cap.
    p = poll(tok)
    assert len((p.get_json() or {}).get("commands", [])) == 1
    qpath = Path(os.environ["OVPN_PANEL_DATA_DIR"]) / "agent_queue.json"
    for i in (1, 2, 3):
        st = read_json(qpath)
        cmd = st["cmds"][cid_q]
        cmd["sent_at"] = "2020-01-01T00:00:00+00:00"  # 6 years stale
        qpath.write_text(json.dumps(st, indent=2))
        p = poll(tok)
        pd = p.get_json() or {}
        st2 = read_json(qpath)
        c2 = st2["cmds"][cid_q]
        # The poll requeues AND re-dispatches: after the poll the
        # command is sent again (retries=i), not left queued.
        cell("S3c-%d stale sent requeues, retries=%d, re-dispatched" % (i, i),
             p.status_code == 200 and len(pd.get("commands", [])) == 1
             and c2.get("status") == "sent"
             and c2.get("retries") == i,
             f"pd={pd} c2={c2}")
    st = read_json(qpath)
    st["cmds"][cid_q]["sent_at"] = "2020-01-01T00:00:00+00:00"
    qpath.write_text(json.dumps(st, indent=2))
    p = poll(tok)
    st2 = read_json(qpath)
    c2 = st2["cmds"][cid_q]
    cell("S3c-4 fourth stale requeue marks the command failed "
         "(retries cap 3)",
         p.status_code == 200 and (p.get_json() or {}).get("commands") == []
         and c2.get("status") == "failed",
         f"c2={c2}")

    # S3d malformed commands are quarantined to failed, poll stays 200.
    st = read_json(qpath)
    st["cmds"]["bad1"] = {"id": "bad1", "node": "n1"}  # no action
    st["cmds"]["bad2"] = "not-a-dict"
    st["cmds"]["bad3"] = {"id": "bad3", "node": "n1", "action": "create_user",
                          "params": "wrong-type"}
    qpath.write_text(json.dumps(st, indent=2))
    p = poll(tok)
    st2 = read_json(qpath)
    cell("S3d malformed entries fail + audit, poll still 200",
         p.status_code == 200
         and st2["cmds"].get("bad1", {}).get("status") == "failed"
         and "bad2" not in st2["cmds"]
         and st2["cmds"].get("bad3", {}).get("status") == "failed",
         f"st2={st2.get('cmds')}")

    # S3e node delete: queued/sent commands fail, queue popped.
    r = client.post("/api/cmd", json={"node": "n1", "action": "create_user",
                                      "params": {"name": "carol"}})
    cid_d = (r.get_json() or {}).get("cmd_id")
    r = client.delete("/api/nodes/n1")
    d = r.get_json() or {}
    st = read_json(qpath)
    cell("S3e node delete fails queued commands and pops the queue",
         r.status_code == 200 and d.get("ok") is True
         and st.get("queues", {}).get("n1") in (None, [])
         and st["cmds"].get(cid_d, {}).get("status") == "failed",
         f"status={r.status_code} d={d} cmd={st['cmds'].get(cid_d)}")

    # S3f/g wrong-node / unknown-cmd / heartbeat snapshot.
    r = client.post("/api/cmd", json={"node": "n1",
                                      "action": "create_user",
                                      "params": {"name": "x"}})
    cell("S3f enqueue for a deleted node -> 404",
         r.status_code == 404, f"status={r.status_code}")
    tok_live = register("n1b")
    rr = report(tok_live, "no-such-cmd", result={"ok": True})
    cell("S3g report for an unknown cmd (live token) -> 404",
         rr.status_code == 404, f"status={rr.status_code}")
    rr = report(tok, cid, result={"ok": True})
    cell("S3g-2 report with a revoked node token -> 401/403",
         rr.status_code in (401, 403), f"status={rr.status_code}")

    # S4a rotate kills the old token.
    tok2 = register("n2")
    r = client.post("/api/nodes/n2/rotate")
    d = r.get_json() or {}
    tok3 = d.get("token")
    p_old = poll(tok2)
    p_new = poll(tok3)
    cell("S4a rotate: old token rejected, new token accepted",
         p_old.status_code in (401, 403) and p_new.status_code == 200,
         f"old={p_old.status_code} new={p_new.status_code}")

    # S4b heartbeat-only report merges, does not clobber the snapshot.
    p = poll(tok3, status={"version": "1.0.2", "openvpn_running": False})
    cell("S4b-1 heartbeat poll -> 200",
         p.status_code == 200, f"status={p.status_code}")
    rr = client.post("/api/agent/report", json={},
                       headers={"Authorization": "Bearer " + tok3})
    cell("S4b-2 heartbeat-only report -> 200 heartbeat",
         rr.status_code == 200
         and (rr.get_json() or {}).get("heartbeat") is True,
         f"status={rr.status_code} body={rr.get_json()}")

    # S4c stale .ovpn receipt after node delete + re-register (S4b code
    # read: nodes_revoke pops the queue and fails cmds but does not
    # clean state["ovpn"] receipts).
    tok4 = register("n3")
    r = client.post("/api/cmd", json={"node": "n3", "action": "create_user",
                                      "params": {"name": "dave"}})
    cid4 = (r.get_json() or {}).get("cmd_id")
    p = poll(tok4)
    assert len((p.get_json() or {}).get("commands", [])) == 1
    rr = report(tok4, cid4, result={"ovpn": "FAKE-OVPN-CONTENT"})
    cell("S4c-1 report with an ovpn payload -> 200 done",
         rr.status_code == 200, f"status={rr.status_code}")
    r = client.delete("/api/nodes/n3")
    tok5 = register("n3")  # same name, fresh token, no users yet
    r = client.get("/api/nodes/n3/users/dave/ovpn")
    body = r.get_data(as_text=True) if r.status_code == 200 else ""
    cell("S4c-2 re-registered node serves NO stale .ovpn for a "
         "user it never had",
         r.status_code == 404 and "FAKE-OVPN" not in body,
         f"status={r.status_code} body={body[:200]}")


# ---------------------------------------------------------------- main
def main():
    print("work dir: %s" % WORK, flush=True)
    TC = A.bootstrap_toolchain()  # dict (or None) -- NOT a path
    if TC is None:
        print("SKIP: toolchain unavailable", flush=True)
        return 0
    section_s1()
    om, ca, srv = section_s2(TC)
    client = section_s2d_panel(om, ca, srv, TC)
    section_s3_s4(client)
    fails = [n for n, ok in RESULTS if not ok]
    print("\nTOTAL %d cells, FAIL %d, SKIP %d"
          % (len(RESULTS), len(fails), len(SKIPS)), flush=True)
    for n in fails:
        print("  FAILED: %s" % n, flush=True)
    host_etc = Path("/etc/openvpn-sk5-panel")
    if host_etc.exists():
        print("HOST /etc/openvpn-sk5-panel EXISTS: %s"
              % sorted(str(p) for p in host_etc.iterdir()), flush=True)
    else:
        print("HOST /etc/openvpn-sk5-panel absent", flush=True)
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())

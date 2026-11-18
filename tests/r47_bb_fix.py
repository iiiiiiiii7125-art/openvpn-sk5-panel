#!/usr/bin/env python3
"""R47 Fix-BB proof probe — asserts the FIXED behavior (BH-03(c)).

The AUDIT-R47 L5 probe pins the defects (its A3-A6/B1-B2/C2/C4/C5/D1
cells PASS on the 1.0.3 baseline because the defects reproduce); this
probe asserts the fixed behavior on the same setups, and FAILS on the
baseline. L2-1/L2-2/L3-1 are proved by the unchanged audit probes
(r47_l2_panel_ux.py P1/Q2, r47_l3_fix_miss_b.py F1a/F1b), which FAIL
on the baseline and PASS here.

Sections (all against a /tmp COPY of the fixed tree):
- Q: real panel server + fake slow agent + fake UI poller. A 130 s
  command must NEVER be re-queued while the agent executes (status
  reads don't sweep), its late report is accepted (200, not 409),
  and the next poll does not re-deliver it. Retry exhaustion still
  works, but only via agent poll: retries climb 1,2,3 on polls and
  the 4th poll marks the command failed.
- J: real Agent + fake panel. A re-delivered command id is replayed
  from the executed-command journal (create_user runs once), and a
  NEW command id for the same user recovers the existing .ovpn
  instead of 409ing the name; revoke/init_pki re-delivery reports
  success for an effect that already landed.
- D: agent poll against a 401 panel raises with the panel's reason
  ("token 与节点名不匹配"), not the bare code.

Run as nobody with:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    R47BB_TREE=<tree> OVPN_PANEL_DATA_DIR=<fresh data> \\
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OVPN_PANEL_ADMIN_PASS_PATH=<data>/admin.pass \\
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \\
    OVPN_SK5_CONFIG_DIR=<fresh sk5cfg> \\
    EASYRSA_BIN=<toolchain>/EasyRSA-3.1.7/easyrsa \\
    python3 <tree>/tests/r47_bb_fix.py
"""
import http.cookiejar
import http.server
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

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
    import subprocess
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


TREE = os.environ.get("R47BB_TREE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..")
for _p in (os.path.join(TREE, "panel"), os.path.join(TREE, "core"),
           os.path.join(TREE, "egress")):
    assert os.path.isdir(_p), "tree missing: %s" % _p
    sys.path.insert(0, _p)
sys.path.insert(0, os.path.join(TREE, "agent"))
TMP = tempfile.mkdtemp(prefix="r47bb-")
DATA = os.environ["OVPN_PANEL_DATA_DIR"]
QUEUE_FILE = os.path.join(DATA, "agent_queue.json")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# =======================================================================
# Section Q: panel queue — status reads never sweep; poll does
# =======================================================================
import app as panel  # noqa: E402  (fixed tree)

PW = panel._ensure_admin_password()
PORT = free_port()
BASE = "http://127.0.0.1:%d" % PORT


def serve_panel():
    panel.app.run(host="127.0.0.1", port=PORT, threaded=True,
                  use_reloader=False)


threading.Thread(target=serve_panel, daemon=True).start()
for _ in range(50):
    try:
        urllib.request.urlopen(BASE + "/api/me", timeout=2)
        break
    except Exception:
        time.sleep(0.2)

CJ = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(CJ))


def http_admin(method, path, payload=None, expect=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=body, method=method,
        headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            code = resp.status
    except urllib.error.HTTPError as exc:
        data = json.loads(exc.read().decode())
        code = exc.code
    if expect is not None:
        assert code == expect, (method, path, code, data)
    return code, data


def http_agent(method, path, payload, token=None):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=body, method=method,
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"_raw": raw}


code, _ = http_admin("POST", "/api/login", {"password": PW}, expect=200)
check("Q0 panel login 200", code == 200)
code, reg = http_admin("POST", "/api/nodes",
                       {"name": "r47bb", "panel_url": BASE}, expect=201)
TOKEN = reg["token"]
check("Q0 node registered", code == 201 and bool(TOKEN))

# --- Q1: slow command, UI polling the whole time ------------------------
code, cmd = http_admin("POST", "/api/cmd",
                       {"node": "r47bb", "action": "install_prereqs",
                        "params": {}}, expect=202)
CMD1 = cmd["cmd_id"]
check("Q1 cmd enqueued", code == 202 and CMD1)

seen_statuses = []
stop_poll = threading.Event()


def ui_poller(cmd_id):
    while not stop_poll.is_set():
        c, d = http_admin("GET", "/api/cmd/" + cmd_id)
        seen_statuses.append((d.get("status"), d.get("retries")))
        time.sleep(2)


threading.Thread(target=ui_poller, args=(CMD1,), daemon=True).start()
code, pol = http_agent("POST", "/api/agent/poll",
                       {"node_token": TOKEN, "node_name": "r47bb",
                        "panel_url": BASE, "status": {}}, token=TOKEN)
assert code == 200, (code, pol)
check("Q1 agent poll delivers install_prereqs",
      CMD1 in [c["id"] for c in pol.get("commands", [])])
# fake agent executes for 130 s (past the 120 s timeout) while the
# UI polls /api/cmd/<id> every 2 s exactly like waitCmd().
time.sleep(130)
code, rep = http_agent("POST", "/api/agent/report",
                       {"node_token": TOKEN, "node_name": "r47bb",
                        "panel_url": BASE, "id": CMD1, "ok": True,
                        "result": {"openvpn": True}, "error": None},
                       token=TOKEN)
stop_poll.set()
# A flip is a re-queue the sweep caused: status queued with retries
# spent, or failed. The pre-delivery ('queued', 0) readings are
# normal (the command has not been picked up yet).
flips = [s for s in seen_statuses
         if (s[0] == "queued" and s[1]) or s[0] == "failed"]
check("Q1 no re-queue while the agent executes (UI polls see only "
      "sent/retries=0)",
      not flips, "polls=%d flips=%s" % (len(seen_statuses), flips[:3]))
check("Q1 late report of an executed command is accepted (200)",
      code == 200 and rep.get("status") == "done",
      "report -> %s %s" % (code, rep))
code, pol2 = http_agent("POST", "/api/agent/poll",
                        {"node_token": TOKEN, "node_name": "r47bb",
                         "panel_url": BASE, "status": {}}, token=TOKEN)
check("Q1 next poll does NOT re-deliver the finished command",
      CMD1 not in [c["id"] for c in pol2.get("commands", [])],
      str(pol2.get("commands", [])))

# --- Q2: retry exhaustion still works, but only via poll --------------
code, cmd = http_admin("POST", "/api/cmd",
                       {"node": "r47bb", "action": "get_status",
                        "params": {}}, expect=202)
CMD2 = cmd["cmd_id"]
code, pol = http_agent("POST", "/api/agent/poll",
                       {"node_token": TOKEN, "node_name": "r47bb",
                        "panel_url": BASE, "status": {}}, token=TOKEN)
assert CMD2 in [c["id"] for c in pol.get("commands", [])]
get_reads = []
poll_delivered = []
for _ in range(4):
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        st = json.load(f)
    c = st["cmds"][CMD2]
    assert c["status"] == "sent", c
    sent = datetime.fromisoformat(c["sent_at"])
    c["sent_at"] = (sent - timedelta(seconds=200)).isoformat()
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f)
    # a status read must NOT change anything (read doesn't sweep)
    _c, d = http_admin("GET", "/api/cmd/" + CMD2)
    get_reads.append((d.get("status"), d.get("retries")))
    if d.get("status") == "failed":
        break
    code, pol = http_agent("POST", "/api/agent/poll",
                           {"node_token": TOKEN, "node_name": "r47bb",
                            "panel_url": BASE, "status": {}}, token=TOKEN)
    poll_delivered.append(CMD2 in [c["id"] for c in pol.get("commands", [])])
_c, final = http_admin("GET", "/api/cmd/" + CMD2)
check("Q2 status reads never move retries (GETs show the state the "
      "previous poll left)",
      [r[1] for r in get_reads] == [0, 1, 2, 3],
      str(get_reads))
check("Q2 polls re-deliver until the 3rd retry, then the command "
      "fails honestly",
      poll_delivered == [True, True, True, False]
      and final.get("status") == "failed"
      and "重投 3 次" in str(final.get("error")),
      "delivered=%s final=%s" % (poll_delivered, final))

# =======================================================================
# Section J: agent journal + action-level idempotency
# =======================================================================
import agent as agent_mod  # noqa: E402  (fixed tree)
import openvpn_manager  # noqa: E402  (fixed tree)

# stub the public-IP probe: deterministic, no network in the request path
_orig_detect = openvpn_manager.detect_public_ip
openvpn_manager.detect_public_ip = lambda: "203.0.113.7"  # noqa: E731

# --- J1: journal replays a re-delivered command id ----------------------
FIX_CA = os.path.join(TMP, "j-ca")
FIX_SRV = os.path.join(TMP, "j-srv")
shutil.copytree(os.environ["OPENVPN_CA_DIR"], FIX_CA)
shutil.copytree(os.environ["OPENVPN_SERVER_DIR"], FIX_SRV)
os.chmod(FIX_CA, 0o755)
for _root, _dirs, _files in os.walk(FIX_CA):
    for _d in _dirs:
        os.chmod(os.path.join(_root, _d), 0o755)
    for _f in _files:
        os.chmod(os.path.join(_root, _f), 0o644)
os.environ["OPENVPN_CA_DIR"] = FIX_CA
os.environ["OPENVPN_SERVER_DIR"] = FIX_SRV

create_count = {"n": 0}
_orig_create = openvpn_manager.create_user


def counting_create(*a, **kw):
    create_count["n"] += 1
    return _orig_create(*a, **kw)


openvpn_manager.create_user = counting_create

JCMD = {"id": "jcmd-1", "action": "create_user",
        "params": {"name": "juser"}}
reports = []
polls = {"n": 0}


class _FakePanel(http.server.BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        ln = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(ln).decode() or "{}")
        if self.path == "/api/agent/poll":
            polls["n"] += 1
            cmds = [JCMD] if polls["n"] <= 2 else []
            self._json({"ok": True, "node": "j", "commands": cmds})
        elif self.path == "/api/agent/report":
            reports.append(payload)
            self._json({"ok": True, "cmd_id": payload.get("id"),
                        "status": "done"})
        else:
            self._json({"ok": False, "error": "unknown"}, 404)

    def log_message(self, *a):
        pass


fsrv = http.server.HTTPServer(("127.0.0.1", 0), _FakePanel)
threading.Thread(target=fsrv.serve_forever, daemon=True).start()
fport = fsrv.server_address[1]
jcfgdir = os.path.join(TMP, "j-agent")
os.makedirs(jcfgdir, exist_ok=True)
jcfg = {"panel_url": "http://127.0.0.1:%d" % fport,
        "node_token": "tok", "node_name": "j",
        "config_path": os.path.join(jcfgdir, "config.json"),
        "ca_cert": None, "insecure": False}
ag = agent_mod.Agent(jcfg, agent_mod._make_ssl_context(jcfg))
n1 = ag.run_once()
count_after_first = create_count["n"]
check("J1 first run_once executes the command once",
      n1 == 1 and count_after_first == 1,
      "run_once=%s create_count=%s" % (n1, count_after_first))
n2 = ag.run_once()
check("J1 second run_once replays the journal (no 2nd execution)",
      n2 == 1 and create_count["n"] == 1
      and len(reports) == 2
      and reports[0].get("ok") is True
      and reports[1].get("ok") is True
      and reports[0].get("result") == reports[1].get("result")
      and "BEGIN CERTIFICATE" in str(reports[1].get("result", {})),
      "reports=%d ok=%s" % (len(reports),
                            [r.get("ok") for r in reports]))
journal_path = os.path.join(jcfgdir, "executed.json")
check("J1 journal file holds the command id (0600)",
      os.path.isfile(journal_path)
      and "jcmd-1" in open(journal_path, encoding="utf-8").read()
      and (os.stat(journal_path).st_mode & 0o777) == 0o600)

# --- J2: a NEW command id for the same user recovers the .ovpn --------
ok, result, error = agent_mod.execute_command(
    {"id": "jcmd-2", "action": "create_user",
     "params": {"name": "juser"}})
check("J2 new-id create of an existing user returns the existing "
      ".ovpn (no poisoned name, no re-issue)",
      ok is True and isinstance(result, dict)
      and "BEGIN CERTIFICATE" in result.get("ovpn", "")
      and result.get("ovpn") == reports[0].get("result", {}).get("ovpn"),
      "ok=%s error=%s same-ovpn=%s" % (
          ok, error,
          result.get("ovpn") == reports[0].get("result", {}).get("ovpn")
          if isinstance(result, dict) else False))

# --- J3: revoke twice ----------------------------------------------------
_orig_restart = openvpn_manager.restart_server
_orig_status = openvpn_manager.server_status
openvpn_manager.restart_server = lambda *a, **k: {"running": True}  # noqa: E731
openvpn_manager.server_status = lambda *a, **k: {"running": True}  # noqa: E731
ok1, res1, err1 = agent_mod.execute_command(
    {"id": "jcmd-3", "action": "revoke_user", "params": {"name": "juser"}})
ok2, res2, err2 = agent_mod.execute_command(
    {"id": "jcmd-4", "action": "revoke_user", "params": {"name": "juser"}})
check("J3 first revoke succeeds", ok1 is True, "err=%s" % err1)
check("J3 re-delivered revoke reports success (already revoked, "
      "not a failure)",
      ok2 is True and isinstance(res2, dict)
      and res2.get("revoked", {}).get("already_revoked") is True,
      "ok=%s res=%s err=%s" % (ok2, res2, err2))
openvpn_manager.restart_server = _orig_restart
openvpn_manager.server_status = _orig_status

# --- J4: init_pki twice ---------------------------------------------------
ASM_CA = os.path.join(TMP, "asm-ca")
ASM_SRV = os.path.join(TMP, "asm-srv")
os.makedirs(os.path.join(ASM_CA, "pki", "issued"), exist_ok=True)
os.makedirs(os.path.join(ASM_CA, "pki", "private"), exist_ok=True)
os.makedirs(ASM_SRV, exist_ok=True)
shutil.copy(os.path.join(FIX_CA, "pki", "ca.crt"),
            os.path.join(ASM_CA, "pki", "ca.crt"))
shutil.copy(os.path.join(FIX_CA, "pki", "issued", "server.crt"),
            os.path.join(ASM_CA, "pki", "issued", "server.crt"))
shutil.copy(os.path.join(FIX_CA, "pki", "private", "server.key"),
            os.path.join(ASM_CA, "pki", "private", "server.key"))
shutil.copy(os.path.join(FIX_CA, "pki", "ta.key"),
            os.path.join(ASM_CA, "pki", "ta.key"))
open(os.path.join(ASM_CA, "pki", "dh.pem"), "w").write("fake dh\n")
open(os.path.join(ASM_CA, "pki", "crl.pem"), "w").write("fake crl\n")
os.environ["OPENVPN_CA_DIR"] = ASM_CA
os.environ["OPENVPN_SERVER_DIR"] = ASM_SRV
ok, result, error = agent_mod.execute_command(
    {"id": "jcmd-5", "action": "init_pki", "params": {}})
check("J4 re-delivered init_pki (CA exists) succeeds",
      ok is True and isinstance(result, dict)
      and "ca_dir" in result and "server_files" in result,
      "ok=%s error=%s" % (ok, error))
os.environ["OPENVPN_CA_DIR"] = FIX_CA
os.environ["OPENVPN_SERVER_DIR"] = FIX_SRV

# =======================================================================
# Section D: agent surfaces the panel's 401 reason
# =======================================================================
openvpn_manager.detect_public_ip = _orig_detect


class _Fake401(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.dumps({"ok": False,
                           "error": "token 与节点名不匹配"}).encode()
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv401 = http.server.HTTPServer(("127.0.0.1", 0), _Fake401)
threading.Thread(target=srv401.serve_forever, daemon=True).start()
p401 = srv401.server_address[1]
cfg401 = {"panel_url": "http://127.0.0.1:%d" % p401,
          "node_token": "tok", "node_name": "r47bb",
          "config_path": "/nonexistent", "ca_cert": None,
          "insecure": False}
ag401 = agent_mod.Agent(cfg401, agent_mod._make_ssl_context(cfg401))
try:
    ag401.poll_once()
    err401 = ""
except Exception as exc:  # noqa: BLE001
    err401 = str(exc)
check("D1 agent poll against a 401 panel surfaces the panel's "
      "reason in the error",
      "401" in err401 and "节点名不匹配" in err401, err401[:200])
srv401.shutdown()
fsrv.shutdown()

print("\nTOTAL: PASS=%d FAIL=%d" % (CHECKS[0] - len(FAILURES), len(FAILURES)))
if FAILURES:
    print("FAILURES: %s" % ", ".join(FAILURES))
    sys.exit(1)

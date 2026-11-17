#!/usr/bin/env python3
"""R45-L7 live-server probe: restart persistence + concurrency (Flask).

Two modes:
  --serve --port N   run the real panel on 127.0.0.1:N (as nobody).
  (default)          driver: spawn the server as a subprocess, drive it
                     over HTTP, SIGTERM it, respawn on the SAME data dir,
                     and verify state survives; then concurrency cells.

Cells:
  R1-R11  restart persistence: node, session cookie, queued cmd, login
          lockout, audit rows all survive a SIGTERM + respawn.
  C1      10 concurrent /api/cmd enqueues -> 10 distinct ids, all queued.
  C2      two concurrent agent polls -> each queued cmd delivered exactly
          once (3 rounds x 5 cmds).
  C3      two panels (separate data dirs / ports) do not see each other's
          nodes or commands.

Run the driver as nobody with:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    R45L7_TREE=<tree> OVPN_PANEL_DATA_DIR=<fresh-data> \\
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \\
    OVPN_SK5_CONFIG_DIR=<fresh-sk5cfg> \\
    python3 <tree>/tests/r45_l7_live_server.py
"""
import http.client
import json
import os
import subprocess
import sys
import threading
import time

TREE = os.environ.get("R45L7_TREE", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.environ["OVPN_PANEL_DATA_DIR"]
VENV_PY = "/tmp/r41-l5-venv/bin/python3"
PORT = 18447
PORT2 = 18448
RESULTS = []


def cell(name, ok, evidence=""):
    RESULTS.append((name, bool(ok)))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" | " + str(evidence)[:240]) if evidence else ""),
          flush=True)


def serve(port):
    sys.path.insert(0, os.path.join(TREE, "panel"))
    import app as panel  # noqa: E402
    panel._ensure_admin_password()
    panel.app.run(host="127.0.0.1", port=port, threaded=True)


class C:
    def __init__(self, port, source_ip=None):
        self.port = port
        self.source_ip = source_ip
        self.cookie = None

    def req(self, method, path, body=None, headers=None):
        h = {"Content-Type": "application/json"}
        if self.cookie:
            h["Cookie"] = self.cookie
        if headers:
            h.update(headers)
        kw = {}
        if self.source_ip:
            kw["source_address"] = (self.source_ip, 0)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15, **kw)
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        sc = r.getheader("Set-Cookie")
        if sc:
            # Flask sets "session=..."; the Worker sets "panel_session=...".
            # Keep the first cookie either face sets.
            self.cookie = sc.split(";")[0]
        try:
            j = json.loads(raw)
        except Exception:
            j = None
        return r.status, j, raw


def wait_up(port, timeout=15):
    c = C(port)
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            s, _, _ = c.req("GET", "/api/me")
            if s in (200, 401):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def start_server(port, data_dir, sk5_dir):
    env = dict(os.environ)
    env["OVPN_PANEL_DATA_DIR"] = data_dir
    env["OVPN_PANEL_SECRET_PATH"] = os.path.join(data_dir, "secret.key")
    env["OVPN_SK5_CONFIG_DIR"] = sk5_dir
    env["PYTHONPATH"] = "/tmp/r41-l5-venv/lib/python3.12/site-packages"
    p = subprocess.Popen(
        [VENV_PY, os.path.join(TREE, "tests", "r45_l7_live_server.py"),
         "--serve", "--port", str(port)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p


def main():
    sk5 = os.environ["OVPN_SK5_CONFIG_DIR"]
    pw = open(os.path.join(DATA, "admin.pass")).read().strip() \
        if os.path.exists(os.path.join(DATA, "admin.pass")) else None

    srv = start_server(PORT, DATA, sk5)
    try:
        cell("R00 server up", wait_up(PORT), "port %d" % PORT)
        if pw is None:
            pw = open(os.path.join(DATA, "admin.pass")).read().strip()
        c = C(PORT)
        s, j, _ = c.req("POST", "/api/login", {"password": pw})
        cell("R01 login -> 200", s == 200, s)
        old_cookie = c.cookie
        s, j, _ = c.req("POST", "/api/nodes", {"name": "n1", "panel_url": "https://127.0.0.1:18447"})
        cell("R02 register n1 -> 201", s == 201, s)
        token = j["token"]
        s, j, _ = c.req("POST", "/api/cmd", {"node": "n1", "action": "get_status", "params": {}})
        cell("R03 enqueue cmd -> 202", s == 202, s)
        cmd_id = j["cmd_id"]
        # Lock 127.0.0.2 with 5 bad logins (source_address trick).
        c2 = C(PORT, source_ip="127.0.0.2")
        for _ in range(5):
            s, _, _ = c2.req("POST", "/api/login", {"password": "wrong-password"})
        s, _, _ = c2.req("POST", "/api/login", {"password": "wrong-password"})
        cell("R04 lock 127.0.0.2 -> 6th 429", s == 429, s)
        s, j, _ = c.req("GET", "/api/audit?limit=100")
        audit_before = len((j or {}).get("rows", []) or (j or {}).get("audit", []) or [])
        # --- restart: SIGTERM + respawn on the SAME data dir ---
        srv.terminate()
        srv.wait(timeout=10)
        srv = start_server(PORT, DATA, sk5)
        cell("R05 server back up after SIGTERM", wait_up(PORT))
        c3 = C(PORT)
        c3.cookie = old_cookie
        s, j, _ = c3.req("GET", "/api/me")
        cell("R06 old session cookie still valid after restart",
             s == 200 and (j or {}).get("admin") is True, s)
        s, j, _ = c3.req("GET", "/api/nodes")
        names = [n["name"] for n in (j or {}).get("nodes", [])]
        cell("R07 node n1 survives restart", "n1" in names, names)
        s, j, _ = c3.req("GET", "/api/cmd/%s" % cmd_id)
        cell("R08 queued cmd survives restart",
             s == 200 and (j or {}).get("status") == "queued", (s, (j or {}).get("status")))
        s, _, _ = c2.req("POST", "/api/login", {"password": pw})
        cell("R09 lock survives restart (correct pw still 429)", s == 429, s)
        s, j, _ = c3.req("GET", "/api/audit?limit=100")
        rows = (j or {}).get("rows", []) or (j or {}).get("audit", []) or []
        cell("R10 audit rows survive restart",
             len(rows) >= audit_before and audit_before > 0,
             "%d -> %d" % (audit_before, len(rows)))
        s, _, _ = c.req("POST", "/api/login", {"password": pw})
        cell("R11 server healthy after restart (login 200)", s == 200, s)

        # --- concurrency ---
        c4 = C(PORT)
        c4.req("POST", "/api/login", {"password": pw})
        ids = []
        errs = []

        def enq(i):
            try:
                s, j, _ = c4.req("POST", "/api/cmd",
                                {"node": "n1", "action": "get_status", "params": {}})
                ids.append((s, (j or {}).get("cmd_id")))
            except Exception as e:
                errs.append(repr(e))

        threads = [threading.Thread(target=enq, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        got = [cid for s, cid in ids if s == 202 and cid]
        cell("C01 10 concurrent enqueues -> 10 distinct ids",
             len(got) == 10 and len(set(got)) == 10, "%d ids, %d unique, errs=%s" % (len(got), len(set(got)), errs))

        # C2: two concurrent polls, 3 rounds x 5 cmds.
        ac = C(PORT)
        # Drain the C01 leftovers first so each C2 round's batch IS the
        # whole queue; otherwise the comparison counts stale cmds as bad.
        s, j, _ = ac.req("POST", "/api/agent/poll",
                        {"node_token": token, "node_name": "n1"})
        for cc in (j or {}).get("commands", []):
            ac.req("POST", "/api/agent/report",
                   {"node_token": token, "cmd_id": cc["id"], "ok": True, "result": {}})
        dup = 0
        rounds = 0
        for rnd in range(3):
            batch = []
            for _ in range(5):
                s, j, _ = c4.req("POST", "/api/cmd",
                                {"node": "n1", "action": "get_status", "params": {}})
                batch.append(j["cmd_id"])
            outs = []

            def poll(out):
                try:
                    s, j, _ = ac.req("POST", "/api/agent/poll",
                                     {"node_token": token, "node_name": "n1"})
                    out.extend([(cc["id"]) for cc in (j or {}).get("commands", [])])
                except Exception as e:
                    out.append("ERR:%r" % e)

            o1, o2 = [], []
            t1 = threading.Thread(target=poll, args=(o1,))
            t2 = threading.Thread(target=poll, args=(o2,))
            t1.start()
            t2.start()
            t1.join()
            t2.join()
            all_ids = o1 + o2
            rounds += 1
            if sorted(all_ids) != sorted(batch) or len(set(all_ids)) != len(all_ids):
                dup += 1
                print("  BAD ROUND %d batch=%s o1=%s o2=%s" % (rnd, batch, o1, o2), flush=True)
            # report them done so the next round is clean
            for cid in batch:
                ac.req("POST", "/api/agent/report",
                       {"node_token": token, "cmd_id": cid, "ok": True, "result": {}})
        cell("C02 two concurrent polls: each cmd once, none lost (3 rounds)",
             dup == 0, "bad-rounds=%d/3" % dup)

        # C3: second panel, separate data dir + port.
        data2 = DATA + "2"
        sk52 = sk5 + "2"
        os.makedirs(data2, exist_ok=True)
        os.makedirs(sk52, exist_ok=True)
        srv2 = start_server(PORT2, data2, sk52)
        try:
            cell("C03 second panel up", wait_up(PORT2))
            c5 = C(PORT2)
            pw2 = None
            for _ in range(30):
                if os.path.exists(os.path.join(data2, "admin.pass")):
                    pw2 = open(os.path.join(data2, "admin.pass")).read().strip()
                    break
                time.sleep(0.3)
            s, j, _ = c5.req("POST", "/api/login", {"password": pw2})
            cell("C04 second panel login ok", s == 200, s)
            s, j, _ = c5.req("POST", "/api/nodes", {"name": "n1", "panel_url": "https://127.0.0.1:18448"})
            cell("C05 same node name registers on panel 2", s == 201, s)
            tok2 = j["token"]
            s, j, _ = c5.req("GET", "/api/nodes")
            cell("C06 panel 2 sees only its own node",
                 [n["name"] for n in j.get("nodes", [])] == ["n1"], j)
            s, j, _ = c5.req("POST", "/api/agent/poll",
                            {"node_token": tok2, "node_name": "n1"})
            cell("C07 panel-2 poll gets no panel-1 commands",
                 (j or {}).get("commands") == [], (j or {}).get("commands"))
            s, j, _ = c.req("GET", "/api/nodes")
            cell("C08 panel 1 unaffected by panel 2",
                 [n["name"] for n in j.get("nodes", [])] == ["n1"], j)
        finally:
            srv2.terminate()
            srv2.wait(timeout=10)
    finally:
        try:
            srv.terminate()
            srv.wait(timeout=10)
        except Exception:
            pass

    fails = [n for n, ok in RESULTS if not ok]
    print("TOTAL %d cells, FAIL %d: %s" % (len(RESULTS), len(fails), fails))
    return len(fails)


if __name__ == "__main__":
    if "--serve" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
        serve(port)
    else:
        sys.exit(main())

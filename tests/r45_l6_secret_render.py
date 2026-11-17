#!/usr/bin/env python3
"""R45-L6 fresh-eyes probe, ADOPTED by Fix-Y with BH-03(c) flips.

BH-03(c) DISCLOSURE: this probe was written by the R45-L6 audit lane
to PIN the defective behavior (every finding cell PASSED on the
16f06c9 baseline by asserting the defect). Fix-Y flips the finding
cells below to assert the FIXED behavior; each flipped cell is
marked "FIXED:" in its comment. Controls are unchanged. The probe
FAILS on the 16f06c9 baseline (negative control) and PASSES on the
fixed tree.

Sections (each cell PASS = the claimed behavior holds):
 A  secret.key length validation (FIXED: empty/short keys are
    regenerated loudly at import; login works, old-key forgery
    fails, the file on disk is 32 bytes afterwards)
 B  SK5 render builds JSON structurally (FIXED: hostile values are
    literal strings; no render failure, no outbound flip)
 D  _curl_via_sk5 decodes defensively (FIXED: a non-UTF-8 200 body
    returns a verdict instead of raising UnicodeDecodeError)

Run as nobody (fresh scratch per run):
  runuser -u nobody -- env PYTHONPATH=/tmp/r41-l5-venv/lib/python3.12/site-packages \\
    R45L6_TREE=<tree-copy> python3 <tree-copy>/tests/r45_l6_secret_render.py
Section A spawns one inner process per secret case (--inner):
app.secret_key is module-level, so each secret needs its own
process. The inner process prints exactly one "RESULT: {...}" line.
"""
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading

TREE = os.environ.get("R45L6_TREE", "")
SCRATCH = "/tmp/r45l6-probe"
PASS = 0
FAIL = 0
FAILED = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s" % name)
    else:
        FAIL += 1
        FAILED.append(name)
        print("FAIL %s %s" % (name, detail))


# ---------------------------------------------------------------- inner (A)
def _forge_serializer(key):
    from itsdangerous import URLSafeTimedSerializer
    import app as panel_app
    iface = panel_app.app.session_interface
    return URLSafeTimedSerializer(
        key, salt="cookie-session", serializer=iface.serializer,
        signer_kwargs={"key_derivation": "hmac",
                       "digest_method": iface.digest_method})


def inner():
    sys.path.insert(0, os.path.join(TREE, "panel"))
    import app as panel_app
    client = panel_app.app.test_client()
    r0 = client.get("/api/status")
    out = {"no_cookie_status": r0.status_code}
    key_hex = os.environ.get("R45L6_FORGE_KEY_HEX", "")
    key = bytes.fromhex(key_hex) if key_hex else b""
    cookie = _forge_serializer(key).dumps({"admin": True, "v": 1})
    client.set_cookie("session", cookie)
    r1 = client.get("/api/status")
    out["forged_status"] = r1.status_code
    r2 = client.get("/api/me")
    try:
        out["forged_me_admin"] = bool(r2.get_json().get("admin"))
    except Exception:
        out["forged_me_admin"] = None
    key2_hex = os.environ.get("R45L6_FORGE_KEY_HEX2")
    if key2_hex is not None:
        key2 = bytes.fromhex(key2_hex)
        cookie2 = _forge_serializer(key2).dumps({"admin": True, "v": 1})
        c2 = panel_app.app.test_client()
        c2.set_cookie("session", cookie2)
        out["forged2_status"] = c2.get("/api/status").status_code
    # Login flow (R45L6_LOGIN_PW set): create an admin row, log in with
    # the correct password, report whether a session sticks.
    pw = os.environ.get("R45L6_LOGIN_PW")
    if pw:
        conn = panel_app._db()
        conn.execute("INSERT INTO admin (id, password_hash) VALUES (1, ?)",
                     (panel_app._hash_password(pw),))
        conn.commit()
        conn.close()
        c3 = panel_app.app.test_client()
        r3 = c3.post("/api/login", json={"password": pw})
        out["login_status"] = r3.status_code
        out["login_set_cookie"] = bool(r3.headers.get("Set-Cookie"))
        r4 = c3.get("/api/me")
        try:
            out["me_after_login_admin"] = bool(r4.get_json().get("admin"))
        except Exception:
            out["me_after_login_admin"] = None
        out["status_after_login"] = c3.get("/api/status").status_code
    print("RESULT: " + json.dumps(out))
    return 0


def run_inner_case(case, secret_bytes, forge_hex, forge2_hex=None,
                     login_pw=None):
    """One inner process per secret case.
    Returns (result dict, raw lines, rc, post_len, post_sha) where
    post_* describe the secret file AFTER the inner process exits
    (Fix-Y: the fix regenerates a short key at import, so the
    post-run file proves the rotation)."""
    data = os.path.join(SCRATCH, "a-%s-data" % case)
    sk5d = os.path.join(SCRATCH, "a-%s-sk5" % case)
    secret_path = os.path.join(SCRATCH, "a-%s-secret.key" % case)
    # Fresh data dir per case: the inner INSERTs admin id=1, so a
    # stale dir from an earlier run would UNIQUE-fail and the inner
    # would die before printing RESULT (probe bug, not product).
    shutil.rmtree(data, ignore_errors=True)
    for d in (data, sk5d):
        os.makedirs(d, exist_ok=True)
    with open(secret_path, "wb") as f:
        f.write(secret_bytes)
    env = dict(os.environ)
    env["PYTHONPATH"] = "/tmp/r41-l5-venv/lib/python3.12/site-packages"
    env["R45L6_TREE"] = TREE
    env["OVPN_PANEL_DATA_DIR"] = data
    env["OVPN_PANEL_SECRET_PATH"] = secret_path
    env["OPENVPN_CA_DIR"] = "/tmp/r17/fixture-ca"
    env["OPENVPN_SERVER_DIR"] = "/tmp/r17/fixture-server"
    env["OVPN_SK5_CONFIG_DIR"] = sk5d
    env["R45L6_FORGE_KEY_HEX"] = forge_hex
    if forge2_hex is not None:
        env["R45L6_FORGE_KEY_HEX2"] = forge2_hex
    if login_pw is not None:
        env["R45L6_LOGIN_PW"] = login_pw
    proc = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--inner"],
        capture_output=True, text=True, timeout=60, env=env)
    result = None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("RESULT: "):
            result = json.loads(line[len("RESULT: "):])
    post_len, post_sha = -1, ""
    try:
        with open(secret_path, "rb") as f:
            post = f.read()
        post_len, post_sha = len(post), hashlib.sha256(post).hexdigest()
    except OSError:
        pass
    return result, (proc.stdout or "").splitlines(), proc.returncode, post_len, post_sha


def section_a():
    print("== A. secret.key length validation ==")
    # FIXED (BH-03(c)): an empty secret is regenerated loudly at
    # import -- login now works, the session sticks, the file on
    # disk is 32 bytes afterwards, and the WARNING names the file.
    res, lines, rc, post_len, _sha = run_inner_case(
        "empty", b"", "", login_pw="Admin12345678")
    check("A1-empty-secret-login-works",
          res is not None and res.get("login_status") == 200,
          "res=%s rc=%s" % (res, rc))
    check("A1b-empty-secret-session-sticks",
          res is not None and res.get("me_after_login_admin") is True
          and res.get("status_after_login") == 200,
          "res=%s" % (res,))
    check("A1c-no-cookie-still-401",
          res is not None and res.get("no_cookie_status") == 401,
          "res=%s" % (res,))
    check("A1d-empty-secret-regenerated-to-32-bytes",
          post_len == 32, "post_len=%s" % (post_len,))
    # A4 FIXED: a warning about the empty secret IS printed, naming
    # the secret file.
    other = [ln for ln in lines if not ln.startswith("RESULT: ")]
    check("A4-empty-secret-warning-names-file",
          any("secret" in ln.lower() for ln in other),
          "lines=%s" % (other,))
    # A2: random 32-byte secret. Login works and the session sticks;
    # empty-key forgery fails (positive/negative controls). FIXED
    # addition: the valid key is left byte-identical (no rotation).
    import secrets
    good = secrets.token_bytes(32)
    res, _lines, rc, post_len, post_sha = run_inner_case(
        "rand32", good, "", good.hex(), login_pw="Admin12345678")
    check("A2a-random32-login-works",
          res is not None and res.get("login_status") == 200
          and res.get("me_after_login_admin") is True
          and res.get("status_after_login") == 200,
          "res=%s" % (res,))
    check("A2b-random32-empty-key-forgery-fails",
          res is not None and res.get("forged_status") == 401,
          "res=%s" % (res,))
    check("A2c-random32-correct-key-forgery-works",
          res is not None and res.get("forged2_status") == 200,
          "res=%s" % (res,))
    check("A2d-random32-key-left-untouched",
          post_len == 32
          and post_sha == hashlib.sha256(good).hexdigest(),
          "post_len=%s" % (post_len,))
    # A3 FIXED: a 5-byte secret is regenerated at import -- login
    # works, but a forgery with the KNOWN short key now fails (the
    # weak key is gone) and the file on disk is 32 bytes.
    res, _lines, rc, post_len, _sha = run_inner_case(
        "short5", b"abcde", b"abcde".hex(), login_pw="Admin12345678")
    check("A3-short-secret-login-works",
          res is not None and res.get("login_status") == 200,
          "res=%s" % (res,))
    check("A3b-short-secret-old-key-forgery-fails",
          res is not None and res.get("forged_status") == 401,
          "res=%s" % (res,))
    check("A3c-short-secret-regenerated-to-32-bytes",
          post_len == 32, "post_len=%s" % (post_len,))


# ---------------------------------------------------------------- B (render)
def section_b():
    print("== B. SK5 render: structural JSON ==")
    sys.path.insert(0, os.path.join(TREE, "egress"))
    sk5d = os.path.join(SCRATCH, "b-sk5")
    os.makedirs(sk5d, exist_ok=True)
    os.environ["OVPN_SK5_CONFIG_DIR"] = sk5d
    import sk5_manager

    def save(host, port, username, password):
        return sk5_manager.set_sk5(host=host, port=port, username=username,
                                   password=password, enabled=False)

    def render():
        return sk5_manager._render_singbox_config(
            sk5_manager._load_config())

    def outbound_of(path):
        with open(path, encoding="utf-8") as f:
            rendered = json.load(f)
        for o in rendered.get("outbounds", []):
            if o.get("tag") == "bought-sk5":
                return o, rendered
        return None, rendered

    # B4 first: normal values render fine (control).
    save("proxy.example.net", 1080, "u1", "p1")
    try:
        path = render()
        ob, _r = outbound_of(path)
        check("B4-normal-values-render-ok",
              ob is not None and ob.get("type") == "socks"
              and ob.get("server") == "proxy.example.net"
              and ob.get("server_port") == 1080,
              "ob=%s" % (ob,))
    except Exception as exc:
        check("B4-normal-values-render-ok", False, "raised %r" % (exc,))

    # B1 FIXED (BH-03(c)): a password with a double quote is now a
    # literal JSON string -- rendering succeeds and the outbound
    # carries the exact password.
    save("proxy.example.net", 1080, "u1", 'p"ass')
    try:
        path = render()
        ob, _r = outbound_of(path)
        check("B1-password-with-quote-renders",
              ob is not None and ob.get("password") == 'p"ass'
              and ob.get("type") == "socks",
              "ob=%s" % (ob,))
    except Exception as exc:
        check("B1-password-with-quote-renders", False,
              "raised %r" % (exc,))
    try:
        sk5_manager.enable()
        check("B1b-enable-with-quote-password-passes-render", False,
              "enable unexpectedly succeeded (no sing-box in sandbox)")
    except Exception as exc:
        # No sing-box binary in the sandbox, so enable must fail at
        # the daemon start -- the point is it gets PAST the render
        # (no JSON error), which is what the defect blocked.
        check("B1b-enable-with-quote-password-passes-render",
              "sing-box" in str(exc)
              and "Expecting" not in str(exc)
              and "delimiter" not in str(exc),
              "raised %r" % (exc,))

    # B2 FIXED: a username with a backslash renders as a literal.
    save("proxy.example.net", 1080, "u\\ser", "p1")
    try:
        path = render()
        ob, _r = outbound_of(path)
        check("B2-username-with-backslash-renders",
              ob is not None and ob.get("username") == "u\\ser"
              and ob.get("type") == "socks",
              "ob=%s" % (ob,))
    except Exception as exc:
        check("B2-username-with-backslash-renders", False,
              "raised %r" % (exc,))

    # B3b FIXED: a host pasted with quotes renders as a literal.
    save('"proxy.example.net"', 1080, "u1", "p1")
    try:
        path = render()
        ob, _r = outbound_of(path)
        check("B3b-quoted-host-renders",
              ob is not None and ob.get("server") == '"proxy.example.net"'
              and ob.get("type") == "socks",
              "ob=%s" % (ob,))
    except Exception as exc:
        check("B3b-quoted-host-renders", False,
              "raised %r" % (exc,))

    # B3 FIXED: the crafted host is a literal string -- the outbound
    # stays a socks outbound to that (invalid) server, route.final
    # still points at bought-sk5. No silent flip to direct.
    save('x", "type": "direct", "tag": "bought-sk5', 1080, "u1", "p1")
    try:
        path = render()
        ob, rendered = outbound_of(path)
        check("B3-host-injection-is-literal-string",
              ob is not None and ob.get("type") == "socks"
              and ob.get("server") == 'x", "type": "direct", "tag": "bought-sk5'
              and rendered.get("route", {}).get("final") == "bought-sk5",
              "ob=%s final=%s" % (ob, rendered.get("route", {}).get("final")))
    except Exception as exc:
        check("B3-host-injection-is-literal-string", False,
              "render raised %r" % (exc,))

    # Leave the scratch config sane again.
    save("proxy.example.net", 1080, "u1", "p1")


# ---------------------------------------------------------------- D (decode)
class _HTTPHandler:
    def __init__(self, body):
        self.body = body

    def __call__(self, request, client_address, server):
        from http.server import BaseHTTPRequestHandler

        body = self.body

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        return H(request, client_address, server)


def _serve_http(body):
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _HTTPHandler(body))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class _SocksStub:
    """Minimal SOCKS5 stub: greeting + CONNECT, then relay to a target
    (host, port) held in self.target so the probe can flip it."""

    def __init__(self):
        self.target = ("127.0.0.1", 1)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,),
                             daemon=True).start()

    def _handle(self, conn):
        try:
            hdr = conn.recv(2)
            if len(hdr) != 2:
                return
            conn.recv(hdr[1])
            conn.sendall(b"\x05\x00")
            req = conn.recv(4)
            if len(req) != 4:
                return
            atyp = req[3]
            if atyp == 0x01:
                conn.recv(6)
            elif atyp == 0x03:
                n = conn.recv(1)[0]
                conn.recv(n + 2)
            elif atyp == 0x04:
                conn.recv(18)
            else:
                return
            upstream = socket.create_connection(self.target, timeout=5)
            conn.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x50")
            self._relay(conn, upstream)
        except (OSError, ValueError, IndexError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    @staticmethod
    def _relay(a, b):
        import select
        socks = [a, b]
        try:
            while True:
                r, _w, _x = select.select(socks, [], [], 10)
                if not r:
                    return
                for s in r:
                    data = s.recv(65536)
                    if not data:
                        return
                    (b if s is a else a).sendall(data)
        except (OSError, ValueError):
            pass
        finally:
            for s in socks:
                try:
                    s.close()
                except OSError:
                    pass


def section_d():
    print("== D. _curl_via_sk5: decode guard (FIXED) ==")
    sys.path.insert(0, os.path.join(TREE, "egress"))
    # NOTE: sk5_manager was already imported by section B, so its
    # module-level CONFIG_DIR is fixed to the B dir -- reuse it here
    # (an env change now would be silently ignored).
    sk5d = os.path.join(SCRATCH, "b-sk5")
    os.makedirs(sk5d, exist_ok=True)
    import sk5_manager

    gbk_srv = _serve_http(b"\xc4\xe3\xba\xc3\xca\xc0\xbd\xe7")  # GBK bytes
    ascii_srv = _serve_http(b"1.2.3.4\n")
    stub = _SocksStub()
    stub.target = ("127.0.0.1", gbk_srv.server_address[1])
    cfg = {"host": "127.0.0.1", "port": stub.port,
           "username": "", "password": ""}

    # D1 FIXED (BH-03(c)): the probe returns a verdict instead of
    # raising on a non-UTF-8 body.
    try:
        res = sk5_manager._curl_via_sk5(cfg, "http://ifconfig.me")
        check("D1-curl-via-sk5-returns-on-gbk-body",
              isinstance(res, tuple) and len(res) == 3,
              "res=%r" % (res,))
    except Exception as exc:
        check("D1-curl-via-sk5-returns-on-gbk-body", False,
              "raised %r" % (exc,))

    # D2/D3/D4 need a stored enabled config pointing at the stub.
    import json as _json
    stored = {"host": "127.0.0.1", "port": stub.port, "username": "",
              "password": "", "enabled": True, "fail_open": False,
              "udp_over_tcp": False, "uot_restart_failed": False}
    with open(os.path.join(sk5d, "sk5.json"), "w", encoding="utf-8") as f:
        _json.dump(stored, f)
    try:
        res = sk5_manager.test_sk5()
        check("D2-test-sk5-returns-on-gbk-body",
              isinstance(res, dict) and "tcp_ok" in res,
              "res=%r" % (res,))
    except Exception as exc:
        check("D2-test-sk5-returns-on-gbk-body", False,
              "raised %r" % (exc,))
    try:
        res = sk5_manager.get_status(probe_egress=True)
        check("D3-get-status-returns-on-gbk-body",
              isinstance(res, dict), "res=%r" % (res,))
    except Exception as exc:
        check("D3-get-status-returns-on-gbk-body", False,
              "raised %r" % (exc,))
    sk5_manager._policy_active = lambda cfg: True
    sk5_manager._singbox_running = lambda: True
    try:
        res = sk5_manager.check_health()
        check("D4-check-health-returns-on-gbk-body",
              isinstance(res, dict) and "healthy" in res,
              "res=%r" % (res,))
    except Exception as exc:
        check("D4-check-health-returns-on-gbk-body", False,
              "raised %r" % (exc,))

    # D5: ASCII body is the control -- the probe works normally.
    stub.target = ("127.0.0.1", ascii_srv.server_address[1])
    try:
        ok, ip, _ms = sk5_manager._curl_via_sk5(cfg, "http://ifconfig.me")
        check("D5-ascii-body-probe-works",
              ok is True and ip == "1.2.3.4", "ok=%s ip=%s" % (ok, ip))
    except Exception as exc:
        check("D5-ascii-body-probe-works", False, "raised %r" % (exc,))
    gbk_srv.shutdown()
    ascii_srv.shutdown()

def main():
    global PASS, FAIL
    if len(sys.argv) > 1 and sys.argv[1] == "--inner":
        return inner()
    os.makedirs(SCRATCH, exist_ok=True)
    section_a()
    section_b()
    section_d()
    print("TOTAL %d cells, FAIL %d: %s" % (PASS + FAIL, FAIL, FAILED))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""R27 probe (r27_verify_forced_divergence.py) -- verify.sh forced-path
file/live divergence, laundered into a healthy verdict by check_health.

MECHANISM UNDER TEST (code-derived, this probe proves it behaviorally):
  1. verify.sh's SK5 toggle test (forced: VERIFY_ALLOW_OVERWRITE_SK5=1)
     drives the chain through the API: enable with a stub SK5, then
     disable. disable() renders the DIRECT sing-box config, restarts
     sing-box on it, flushes the policy, and saves enabled=false.
  2. verify.sh cleanup() (FIXED, R27-P1-1) restores the RUNNING
     chain, not just the files: while the disk still says
     enabled=false it re-enables via the API -- POST /api/sk5 with
     the backed-up host/port and enabled=true, no password (the
     panel keeps the stored merchant password, P0-4) -- so set_sk5
     takes the disabled->enabled flip and runs the full enable()
     (re-render + sing-box restart + policy). Only then are the
     backed-up sk5.json and sing-box.json copied back over the
     identical state enable() just persisted. The OLD cleanup
     copied the files only: the RUNNING sing-box stayed direct
     while the disk said SK5, and the next healthcheck tick
     whitewashed it healthy (step 3 of the old mechanism).
  3. ORDER TRAP (why the API call must come BEFORE the file
     restore): restoring the files first and then posting the same
     values takes set_sk5's still-enabled branch, whose repair --
     when the daemon is alive -- only re-applies the policy and
     never restarts the daemon. The daemon would stay direct and
     the divergence would survive. D3b pins this: a file-first
     same-values save leaves the loaded config direct while the
     policy comes back.
  4. The next 60 s healthcheck tick now finds a genuinely restored
     chain: policy already applied, test_sk5() tcp_ok through the
     merchant SOCKS -- healthy=true, action="none" (no repair
     needed), and the running config is the SK5 one, so VPN
     traffic genuinely egresses via SK5. The panel surface
     (enabled + policy_routing_active + merchant egress IP) is
     honest because the ground truth behind it is true.

WHAT THIS PROBE PROVES (and what it does not):
  * REAL sk5_manager functions throughout: set_sk5/enable/disable/
    get_status/check_health/current_egress_ip, with a stub `sing-box`
    binary that records which config it was started with (the
    "loaded config" -- the observable that distinguishes direct-mode
    from SK5-mode in the running process).
  * REAL policy-routing.sh (repair/disable verbs) run under
    `unshare -rm` against the BM probe's stateful mock `ip`
    (same pattern as tests/bm_blackhole_selfheal.py part 2).
  * REAL test_sk5() TCP leg: real curl --socks5-hostname through a
    real in-process SOCKS5 stub to a local HTTP server. The UDP leg
    runs the real code too (stub relay forwards to 1.1.1.1:53 when
    the sandbox allows it, else synthesises a matching DNS answer
    and logs it -- the verdict under test needs only tcp_ok, and
    udp_ok is reported, never asserted).
  * It does NOT prove real-kernel forwarding (no TUN in the
    sandbox): the "traffic fate" is derived from the two facts the
    verdict itself relies on (rule + tun1 route present) PLUS the
    stub's loaded-config record (direct). The control cell (D5)
    shows the verdict is IDENTICAL when the loaded config is the
    SK5 one -- i.e. check_health cannot discriminate the two
    states at all.

CELLS:
  D1 genuine chain up: enable() loads the SK5 config, policy active.
  D2 verify.sh disable step: running config becomes direct, enabled=false.
  D3 FIXED cleanup: API re-enable (flip branch -> full enable())
     BEFORE the file restore; running config is SK5 again and the
     restored files are byte-identical to the backups.
  D4 next healthcheck tick: healthy + action "none" (no repair
     needed) with the running config genuinely SK5, fate via-sk5.
  D3b ORDER TRAP: file restore FIRST, then the same-values API
     save, leaves the loaded config direct (the still-enabled
     repair only re-applies the policy) -- the divergence the
     old cleanup produced, pinned so the order is never flipped.
  D5 control: same tick on a flushed genuine chain gives
     healthy + policy_repaired, fate via-sk5 -- healthy in both
     D4 and D5, genuinely true in both.
  D6 panel surface: in the restored state get_status() reports
     enabled=true + policy_routing_active=true and
     current_egress_ip() returns the merchant IP -- and the loaded
     config behind them is the SK5 one, so the surface is honest.

Run: python3 tests/r27_verify_forced_divergence.py
Exit code = number of FAILs. Requires: unshare, curl, python3.
"""
import json
import os
import shutil
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TREE / "egress"))

RESULTS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + detail) if detail else ""))


def run(cmd, timeout=120, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)


# ---------------------------------------------------------------- stub sing-box
# Records which config it was started with: the "loaded config".
# `check` only parses JSON; `run` records route.final + outbound tags
# + config sha, marks tun1 live in the mock-ip state, then sleeps.
STUB_SINGBOX = r"""#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("check", "run"):
        sys.exit(2)
    cfg_path = sys.argv[sys.argv.index("-c") + 1]
    try:
        cfg = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
    except Exception:
        sys.exit(1)
    if sys.argv[1] == "check":
        sys.exit(0)
    loaded = Path(os.environ["STUB_SINGBOX_LOADED"])
    rec = {
        "route_final": (cfg.get("route") or {}).get("final"),
        "outbounds": [o.get("tag") for o in cfg.get("outbounds", [])],
        "sha": __import__("hashlib").sha256(
            Path(cfg_path).read_bytes()).hexdigest()[:12],
        "started_at": time.time(),
    }
    loaded.write_text(json.dumps(rec), encoding="utf-8")
    state = Path(os.environ["MOCK_IP_STATE"])
    (state / "tun1").write_text("live", encoding="utf-8")
    while True:
        time.sleep(3600)
if __name__ == "__main__":
    main()
"""

# ---------------------------------------------------------------- mock ip/sysctl/iptables
# Same surface as tests/bm_blackhole_selfheal.py part 2, plus a
# "route del" case (do_enable's stale-route cleanup when tun1 is
# not live). Kernel semantics are NOT modeled here -- they are
# proven by BM part 1 (real ip in a private netns); this mock only
# proves what the script issues and what sk5_manager reads back.
MOCK_IP = r"""#!/bin/sh
S="${MOCK_IP_STATE:?}"
mkdir -p "$S"
echo "ip $*" >> "$S/log"
case "$1 $2" in
  "rule show") cat "$S/rules" 2>/dev/null; exit 0;;
  "rule add")
    grep -qx "100: from 10.8.0.0/24 lookup 100" "$S/rules" 2>/dev/null \
      || echo "100: from 10.8.0.0/24 lookup 100" >> "$S/rules"
    exit 0;;
  "rule del")
    if [ -f "$S/rules" ]; then
      grep -vx "100: from 10.8.0.0/24 lookup 100" "$S/rules" > "$S/rules.tmp" || true
      mv "$S/rules.tmp" "$S/rules"
    fi
    exit 0;;
  "route show") cat "$S/routes" 2>/dev/null; exit 0;;
  "route replace")
    if [ "$3" = "blackhole" ]; then
      grep -v "^blackhole default" "$S/routes" 2>/dev/null > "$S/routes.tmp" || true
      mv "$S/routes.tmp" "$S/routes" 2>/dev/null || true
      echo "blackhole default metric 200" >> "$S/routes"
    else
      grep -v "^default via" "$S/routes" 2>/dev/null > "$S/routes.tmp" || true
      mv "$S/routes.tmp" "$S/routes" 2>/dev/null || true
      echo "default via 10.9.0.1 dev tun1" >> "$S/routes"
    fi
    exit 0;;
  "route del")
    if [ -f "$S/routes" ]; then
      grep -v "^default via" "$S/routes" > "$S/routes.tmp" || true
      mv "$S/routes.tmp" "$S/routes"
    fi
    exit 0;;
  "route flush") : > "$S/routes"; exit 0;;
  "link show")
    if [ -f "$S/tun1" ]; then
      if [ "$(cat "$S/tun1")" = live ]; then
        echo "2: tun1: <POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP> mtu 1400 qdisc fq_codel state UNKNOWN mode DEFAULT group default qlen 500"
      else
        echo "2: tun1: <NO-CARRIER,POINTOPOINT,MULTICAST,NOARP,UP> mtu 1400 qdisc fq_codel state DOWN mode DEFAULT group default qlen 500"
      fi
      exit 0
    fi
    exit 1;;
  "tuntap add") touch "$S/tun1"; exit 0;;
  "addr add") exit 0;;
  "addr show")
    [ -f "$S/tun1" ] && echo "inet 10.9.0.1/30"
    exit 0;;
  "link set") exit 0;;
  *) exit 0;;
esac
"""
MOCK_SYSCTL = "#!/bin/sh\nexit 0\n"
MOCK_IPTABLES = """#!/bin/sh
echo "iptables $*" >> "${MOCK_IP_STATE:?}/log"
if [ "$1" = "-C" ]; then exit 1; fi
exit 0
"""


# ---------------------------------------------------------------- stub SOCKS5 + HTTP
class SocksHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.request.settimeout(10)
            head = self.request.recv(2)
            if len(head) != 2 or head[0] != 0x05:
                return
            nmethods = head[1]
            self.request.recv(nmethods)
            auth = 0x02 if self.server.want_auth else 0x00
            self.request.sendall(bytes([0x05, auth]))
            if auth == 0x02:
                h = self.request.recv(2)
                ulen = h[1]
                u = self.request.recv(ulen)
                plen = self.request.recv(1)[0]
                p = self.request.recv(plen)
                self.request.sendall(b"\x01\x00")
            req = self.request.recv(4)
            if len(req) < 4:
                return
            cmd, atyp = req[1], req[3]
            if atyp == 0x01:
                addr = socket.inet_ntoa(self.request.recv(4))
            elif atyp == 0x03:
                n = self.request.recv(1)[0]
                addr = self.request.recv(n).decode()
            elif atyp == 0x04:
                addr = socket.inet_ntop(socket.AF_INET6, self.request.recv(16))
            else:
                return
            port = struct.unpack(">H", self.request.recv(2))[0]
            if cmd == 0x03:  # UDP ASSOCIATE
                udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                udp.bind(("127.0.0.1", 0))
                uport = udp.getsockname()[1]
                self.server.udp_sock = udp
                self.request.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01"
                                     + struct.pack(">H", uport))
                threading.Thread(target=self.server.relay_udp,
                                 args=(udp,), daemon=True).start()
                while True:
                    try:
                        if not self.request.recv(1):
                            break
                    except OSError:
                        break
                return
            if cmd != 0x01:  # only CONNECT otherwise
                self.request.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
                return
            try:
                peer = socket.create_connection((addr, port), timeout=10)
            except OSError:
                self.request.sendall(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")
                return
            self.request.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
            self._relay(self.request, peer)
        except (OSError, IndexError, struct.error):
            return

    def _relay(self, a, b):
        def pump(src, dst):
            try:
                while True:
                    d = src.recv(65535)
                    if not d:
                        break
                    dst.sendall(d)
            except OSError:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
        t = threading.Thread(target=pump, args=(b, a), daemon=True)
        t.start()
        pump(a, b)


class SocksServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    want_auth = True

    def relay_udp(self, udp):
        udp.settimeout(12)
        while True:
            try:
                data, src = udp.recvfrom(2048)
            except (OSError, socket.timeout):
                return
            if len(data) < 10 or data[2] != 0x00:
                continue
            atyp = data[3]
            off = 4
            if atyp == 0x01:
                dst = (socket.inet_ntoa(data[4:8]),
                       struct.unpack(">H", data[8:10])[0])
                off = 10
            elif atyp == 0x03:
                n = data[4]
                dst = (data[5:5 + n].decode(),
                       struct.unpack(">H", data[5 + n:7 + n])[0])
                off = 7 + n
            elif atyp == 0x04:
                dst = (socket.inet_ntop(socket.AF_INET6, data[4:20]),
                       struct.unpack(">H", data[20:22])[0])
                off = 22
            else:
                continue
            payload = data[off:]
            resp = self.dns_answer(payload, dst)
            if resp is None:
                continue
            hdr = b"\x00\x00\x00\x01" + socket.inet_aton(dst[0]) \
                + struct.pack(">H", dst[1])
            try:
                udp.sendto(hdr + resp, src)
            except OSError:
                return

    def dns_answer(self, query, dst):
        # Try the real resolver first; the sandbox may block UDP
        # egress, in which case synthesise a matching DNS answer
        # (txid copied, ancount=1) and LOG it -- the verdict under
        # test needs only tcp_ok; udp_ok is reported, never asserted.
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(3)
            s.sendto(query, ("1.1.1.1", 53))
            data, _ = s.recvfrom(2048)
            s.close()
            self.dns_path = "forwarded to 1.1.1.1:53"
            return data
        except OSError:
            pass
        if len(query) < 12:
            return None
        txid = query[:2]
        self.dns_path = "synthesised (sandbox UDP egress blocked)"
        q = query[4:]
        ans = (txid + b"\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00"
               + q
               + b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04"
               + socket.inet_aton("93.184.216.34"))
        return ans


class HttpHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.request.settimeout(5)
            self.request.recv(65535)
            body = b"203.0.113.7\n"
            self.request.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n"
                b"Content-Type: text/plain\r\n\r\n" % len(body) + body)
        except OSError:
            pass


def main():
    tmp = Path(tempfile.mkdtemp(prefix="r27-div-"))
    cfgdir = tmp / "cfg"
    cfgdir.mkdir()
    ipstate = tmp / "ipstate"
    ipstate.mkdir()
    (tmp / "sysctld").mkdir()
    (tmp / "rundir").mkdir()
    mockbin = tmp / "mockbin"
    mockbin.mkdir()
    (mockbin / "ip").write_text(MOCK_IP, encoding="utf-8")
    (mockbin / "sysctl").write_text(MOCK_SYSCTL, encoding="utf-8")
    (mockbin / "iptables").write_text(MOCK_IPTABLES, encoding="utf-8")
    for f in ("ip", "sysctl", "iptables"):
        (mockbin / f).chmod(0o755)
    stubbin = tmp / "stubbin"
    stubbin.mkdir()
    (stubbin / "sing-box").write_text(STUB_SINGBOX, encoding="utf-8")
    (stubbin / "sing-box").chmod(0o755)
    loaded = tmp / "loaded.json"

    # --- stub SOCKS5 + local HTTP (the "merchant" + the "internet")
    socks = SocksServer(("127.0.0.1", 0), SocksHandler)
    socks.dns_path = "not run yet"
    threading.Thread(target=socks.serve_forever, daemon=True).start()
    stub_port = socks.server_address[1]
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), HttpHandler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    http_port = httpd.server_address[1]

    env = dict(os.environ)
    env["PATH"] = str(stubbin) + ":" + env["PATH"]
    env["OVPN_SK5_CONFIG_DIR"] = str(cfgdir)
    env["MOCK_IP_STATE"] = str(ipstate)
    env["STUB_SINGBOX_LOADED"] = str(loaded)
    os.environ.update(env)

    import sk5_manager as m

    orig_run = m._run

    def run_script(verb):
        inner = (
            "mkdir -p /etc/sysctl.d /run/openvpn-sk5-panel && "
            "mount --bind \"$1/sysctld\" /etc/sysctl.d && "
            "mount --bind \"$1/rundir\" /run/openvpn-sk5-panel && "
            "export PATH=\"$1/mockbin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\" && "
            "export MOCK_IP_STATE=\"$1/ipstate\" && "
            "bash \"" + str(TREE / "egress" / "policy-routing.sh") + "\" "
            + verb + "; echo \"rc=$?\""
        )
        r = subprocess.run(["unshare", "-rm", "bash", "-c", inner, "x", str(tmp)],
                           capture_output=True, text=True, timeout=120, env=env)
        return r.stdout + r.stderr

    def model_run(cmd, timeout=30):
        if not cmd:
            return orig_run(cmd, timeout=timeout)
        if cmd[0] == "systemctl":
            return subprocess.CompletedProcess(cmd, 1, "", "unit absent")
        if cmd[0] == "bash" and any("policy-routing.sh" in a for a in cmd):
            verb = cmd[-1]
            out = run_script(verb)
            rc = 0 if "rc=0" in out else 1
            return subprocess.CompletedProcess(cmd, rc, out, "")
        if cmd[0] == "ip":
            if cmd[1:3] == ["rule", "show"]:
                rules = (ipstate / "rules").read_text(
                    encoding="utf-8") if (ipstate / "rules").exists() else ""
                return subprocess.CompletedProcess(cmd, 0, rules, "")
            if cmd[1:3] == ["route", "show"]:
                routes = (ipstate / "routes").read_text(
                    encoding="utf-8") if (ipstate / "routes").exists() else ""
                return subprocess.CompletedProcess(cmd, 0, routes, "")
            if cmd[1:3] == ["link", "show"]:
                if (ipstate / "tun1").exists() \
                        and (ipstate / "tun1").read_text() == "live":
                    return subprocess.CompletedProcess(
                        cmd, 0,
                        "2: tun1: <POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP> "
                        "mtu 1400 state UNKNOWN", "")
                return subprocess.CompletedProcess(cmd, 1, "", "no such device")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return orig_run(cmd, timeout=timeout)

    m._run = model_run
    m.EGRESS_CHECK_URL = "http://127.0.0.1:%d/" % http_port

    def loaded_config():
        if not loaded.exists():
            return {}
        return json.loads(loaded.read_text(encoding="utf-8"))

    def state():
        rules = (ipstate / "rules").read_text(
            encoding="utf-8") if (ipstate / "rules").exists() else ""
        routes = (ipstate / "routes").read_text(
            encoding="utf-8") if (ipstate / "routes").exists() else ""
        return rules, routes

    def traffic_fate():
        """What happens to a VPN packet: enters table 100 (rule+tun1
        route present) and is forwarded by the RUNNING sing-box per
        its loaded config -- direct when route.final == 'direct',
        via SK5 when route.final == 'bought-sk5'."""
        rules, routes = state()
        if "lookup 100" not in rules or "dev tun1" not in routes:
            return "no-policy"
        lc = loaded_config()
        return "direct" if lc.get("route_final") == "direct" \
            else "via-sk5" if lc.get("route_final") == "bought-sk5" \
            else "unknown"

    try:
        # --- D1: genuine chain up (the merchant state verify.sh backs up)
        st = m.set_sk5(host="127.0.0.1", port=stub_port,
                       username="session-test", password="pw",
                       enabled=True)
        cell("D1 enable() loads SK5 config + policy active",
             loaded_config().get("route_final") == "bought-sk5"
             and "bought-sk5" in loaded_config().get("outbounds", [])
             and m._policy_active(m._load_config()) is True
             and st.get("enabled") is True,
             "loaded=%s policy=%s" % (loaded_config().get("route_final"),
                                       m._policy_active(m._load_config())))
        # Backups, exactly as verify.sh takes them before the toggle.
        sk5_bak = (cfgdir / "sk5.json").read_bytes()
        sb_bak = (cfgdir / "sing-box.json").read_bytes()

        # --- D2: the toggle test's disable step (verify.sh §9-11)
        st = m.disable()
        cell("D2 disable() switches running sing-box to direct",
             loaded_config().get("route_final") == "direct"
             and m._load_config().get("enabled") is False,
             "loaded=%s enabled=%s" % (loaded_config().get("route_final"),
                                        m._load_config().get("enabled")))

        # --- D3: FIXED verify.sh cleanup() -- API re-enable FIRST
        # (while the disk still says enabled=false, so set_sk5
        # takes the disabled->enabled flip and runs the full
        # enable()), then the file restore. This models POST
        # /api/sk5 {host, port, username, enabled=true} with the
        # password omitted (the panel keeps it stored, P0-4) --
        # the direct m.set_sk5(password=None) call is the same
        # function the panel handler invokes.
        st = m.set_sk5(host="127.0.0.1", port=stub_port,
                       username="session-test", password=None,
                       enabled=True)
        (cfgdir / "sk5.json").write_bytes(sk5_bak)
        (cfgdir / "sing-box.json").write_bytes(sb_bak)
        gs = m.get_status()
        cell("D3 fixed cleanup: API re-enable then file restore -- "
             "running config SK5 again, files byte-identical to backups",
             st.get("enabled") is True
             and loaded_config().get("route_final") == "bought-sk5"
             and gs.get("enabled") is True
             and gs.get("policy_routing_active") is True
             and (cfgdir / "sk5.json").read_bytes() == sk5_bak
             and (cfgdir / "sing-box.json").read_bytes() == sb_bak,
             "loaded=%s enabled=%s policy=%s sk5_bak_match=%s sb_bak_match=%s" % (
                 loaded_config().get("route_final"), gs.get("enabled"),
                 gs.get("policy_routing_active"),
                 (cfgdir / "sk5.json").read_bytes() == sk5_bak,
                 (cfgdir / "sing-box.json").read_bytes() == sb_bak))

        # --- D4: the next healthcheck tick on the restored chain
        h = m.check_health()
        gs = m.get_status()
        cell("D4 health tick on restored chain: healthy + action "
             "none (no repair needed), running config genuinely SK5",
             h.get("healthy") is True
             and h.get("action") == "none"
             and loaded_config().get("route_final") == "bought-sk5"
             and traffic_fate() == "via-sk5",
             "healthy=%s action=%s loaded=%s fate=%s detail=%s" % (
                 h.get("healthy"), h.get("action"),
                 loaded_config().get("route_final"), traffic_fate(),
                 h.get("detail", "")[:120]))
        cell("D6 panel surface in restored state: enabled + policy "
             "active + merchant egress IP -- and the loaded config "
             "behind them is SK5, so the surface is honest",
             gs.get("enabled") is True
             and gs.get("policy_routing_active") is True
             and m.current_egress_ip() == "203.0.113.7"
             and loaded_config().get("route_final") == "bought-sk5",
             "enabled=%s policy=%s egress=%s loaded=%s" % (
                 gs.get("enabled"), gs.get("policy_routing_active"),
                 m.current_egress_ip(),
                 loaded_config().get("route_final")))

        # --- D3b: ORDER TRAP -- file restore FIRST, then the
        # same-values API save. This is what restoring the files
        # before the API call would do: set_sk5 takes the
        # still-enabled branch, whose repair only re-applies the
        # policy when the daemon is alive and never restarts it --
        # the daemon stays direct. Pinned so the order in
        # cleanup() is never flipped back.
        m.disable()
        (cfgdir / "sk5.json").write_bytes(sk5_bak)
        (cfgdir / "sing-box.json").write_bytes(sb_bak)
        st = m.set_sk5(host="127.0.0.1", port=stub_port,
                       username="session-test", password=None,
                       enabled=True)
        cell("D3b order trap: file-first + same-values API save "
             "does NOT restart the daemon (loaded stays direct)",
             loaded_config().get("route_final") == "direct"
             and m._policy_active(m._load_config()) is True
             and st.get("repaired") is True,
             "loaded=%s policy=%s repaired=%s" % (
                 loaded_config().get("route_final"),
                 m._policy_active(m._load_config()),
                 st.get("repaired")))

        # --- D5: control -- same tick, genuine SK5-loaded sing-box
        # Re-enable genuinely (renders SK5 config, restarts stub on
        # it), flush the policy by the script alone (no sing-box
        # touch), then run the same tick.
        m.enable()
        out = run_script("disable")
        cell("D5 setup: policy flushed, stub still SK5-loaded",
             loaded_config().get("route_final") == "bought-sk5"
             and m._policy_active(m._load_config()) is False,
             "loaded=%s policy=%s" % (loaded_config().get("route_final"),
                                       m._policy_active(m._load_config())))
        h2 = m.check_health()
        cell("D5 control tick on flushed genuine chain: healthy + "
             "policy_repaired, fate via-sk5 (same healthy verdict "
             "as D4, genuinely true in both -- D4 needed no repair, "
             "so its action is none, D5's is policy_repaired)",
             h2.get("healthy") is True
             and h2.get("action") == "policy_repaired"
             and h2.get("healthy") == h.get("healthy")
             and traffic_fate() == "via-sk5",
             "healthy=%s action=%s fate=%s (D4 was healthy=%s action=%s)" % (
                 h2.get("healthy"), h2.get("action"), traffic_fate(),
                 h.get("healthy"), h.get("action")))
    finally:
        try:
            m._stop_singbox()
        except Exception:
            pass
        try:
            socks.shutdown()
        except Exception:
            pass
        try:
            httpd.shutdown()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    fails = sum(1 for _, ok in RESULTS if not ok)
    print("r27_verify_forced_divergence: %d/%d PASS"
          % (len(RESULTS) - fails, len(RESULTS)))
    sys.exit(fails)


if __name__ == "__main__":
    main()

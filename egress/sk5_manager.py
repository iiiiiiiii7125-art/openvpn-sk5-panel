#!/usr/bin/env python3
"""SK5 egress manager for the OpenVPN transit server.

OpenVPN users live on 10.8.0.0/24 (tun0). Their traffic is policy-routed
(from 10.8.0.0/24 -> table 100 -> tun1 10.9.0.1) into sing-box's tun
inbound, and sing-box forwards it through the purchased SOCKS5
(tag ``bought-sk5``). This module is the control plane for that chain:

  * stores the SK5 credential (0600, never logged),
  * renders egress/sing-box.json.template -> sing-box config,
  * runs ``sing-box check`` before (re)starting sing-box,
  * applies / removes policy routing via egress/policy-routing.sh,
  * probes the chain for real: TCP via curl --socks5-hostname,
    UDP via a real SOCKS5 UDP ASSOCIATE + DNS query (never TCP
    success masquerading as UDP success).

Only the standard library + subprocess is used. No password is ever
written to stdout, logs or exceptions.

Files (all under /etc/openvpn-sk5-panel/, created on first use;
set OVPN_SK5_CONFIG_DIR to redirect them -- the integration gate
runs the panel as nobody, which cannot write /etc, so it points
the panel at a scratch dir instead; production leaves it unset):
  sk5.json          SK5 config + switches (0600)
  sing-box.json     rendered sing-box config (0600)
  sing-box.log      sing-box stdout/stderr when started by this module

Systemd unit expected by enable(): openvpn-sk5-singbox.service with
  ExecStart=/usr/local/bin/sing-box run -c /etc/openvpn-sk5-panel/sing-box.json
If the unit does not exist, enable() falls back to starting sing-box
directly in the background (nohup, PID in sing-box.pid) so the chain
still works on a plain Debian/Ubuntu box.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("OVPN_SK5_CONFIG_DIR")
                   or "/etc/openvpn-sk5-panel")
CONFIG_FILE = CONFIG_DIR / "sk5.json"
RENDERED_CONFIG = CONFIG_DIR / "sing-box.json"
LOG_FILE = CONFIG_DIR / "sing-box.log"
PID_FILE = CONFIG_DIR / "sing-box.pid"
HEALTH_FILE = CONFIG_DIR / "health.json"  # last check_health() result (0600)
TEMPLATE = Path(__file__).resolve().parent / "sing-box.json.template"
POLICY_SCRIPT = Path(__file__).resolve().parent / "policy-routing.sh"

SINGBOX_BIN = shutil.which("sing-box") or "/usr/local/bin/sing-box"
SYSTEMD_UNIT = "openvpn-sk5-singbox.service"

VPN_NET = "10.8.0.0/24"
DNS_SERVER = "1.1.1.1"          # UDP probe target (port 53)
DNS_QUERY_NAME = "example.com"  # A query sent through the UDP relay
# R27-P2-1 depth retry: a second query name + a second resolver, so
# one resolver's empty answer database (live-18: 1.1.1.1 answered
# example.com with ancount=0 while the relay demonstrably worked)
# or one lost packet cannot condemn UDP. Attempt 2 only runs when
# attempt 1 produced no txid-matching reply.
DNS_SERVER2 = "8.8.8.8"
DNS_QUERY_NAME2 = "cloudflare.com"
EGRESS_CHECK_URL = "http://ifconfig.me"
TIMEOUT = 10                    # seconds, per probe
# NOTE: the UoT probe used to listen on a fixed 127.0.0.1:18080; it now
# picks a free loopback port per probe (see _udp_probe_via_uot_singbox).


# ---------------------------------------------------------------- config I/O

def _default_config() -> dict:
    return {
        "host": "",
        "port": 1080,
        "username": "",
        "password": "",
        "enabled": False,
        # False = kill-switch (default): while enabled, if the SK5 /
        # sing-box dies, VPN user traffic must never silently fall
        # back to direct egress on its own. The kill-switch is the
        # device-independent `blackhole default metric 200` route
        # that enable() installs in table 100 alongside the tun1
        # route (R13-BUG-1): the tun1 route is device-bound and the
        # kernel deletes it when tun1 dies, which used to leave an
        # EMPTY table 100 -- and an empty table falls through to
        # the main table, i.e. silent direct (the old model, "the
        # dead tun1 route blackholes traffic", was wrong; the dead
        # route is gone, not blackholing). With the fallback
        # blackhole, lookups fall to it and traffic is dropped.
        # True = fail-open: a health check that finds the chain
        # dead removes table 100, restoring direct egress (see
        # check_health()).
        "fail_open": False,
        # False = native SOCKS5 UDP ASSOCIATE (needs merchant UDP).
        # True  = udp_over_tcp: sing-box wraps UDP in TCP to the SK5.
        "udp_over_tcp": False,
    }


def _exists(path: Path) -> bool:
    """exists() that never raises: Path.exists() lets PermissionError
    through (proven live: a non-root agent against a root-only 0700
    /etc/openvpn-sk5-panel gets EACCES from stat). Read paths must
    treat "inaccessible" as "absent", never crash the status poll."""
    try:
        return path.exists()
    except OSError:
        return False


def _validate_stored(cfg: dict) -> None:
    """Strict shape check on the merged stored config (R20-P2-1).

    Single choke point: every consumer (render, probes, set_sk5,
    enable, test_sk5, get_status) loads through _load_config, so a
    bad stored shape is rejected here, once, before any consumer
    can launder it. Before this, the six read points did
    ``int(cfg["port"])`` BEFORE _validate's isinstance check ran,
    so a stored ``"port": true`` became server_port 1 and
    ``1194.5`` became 1194 in the LIVE sing-box config. The
    isinstance check in _validate was dead by construction.
    The six ``int(cfg["port"])`` read points are deliberately left
    alone: past this gate they only ever see a validated int.

    Digit strings are REJECTED here (``"1194"`` is not accepted),
    unlike agent ``_as_int`` on the action-param path, which
    tolerates them: the panel (``_valid_port``) and the agent
    (``_as_int``) both deliver real ints, and _save_config only
    ever writes ints, so any string in the stored file is a
    hand-edit / corruption signal, not a legitimate wire shape.
    Same for the three bool switches: ``bool("false") == True``
    (R12-P2-1's exact mechanism, on the stored face this time) --
    only real bools, plus int 0/1 (the R12-pinned panel tolerance,
    normalized to bool), are accepted; anything else is rejected.

    Swept and deliberately NOT checked here: host/username/
    password -- no conversion precedes their checks, and a wrong
    type fails loudly instead of laundering (render raises
    TypeError on a non-str host; a garbage host makes the curl
    probe fail honestly). The set_sk5 param intake
    (``cfg["port"] = int(port)``) is likewise left alone: its only
    callers are panel ``_valid_port`` and agent ``_as_int``, which
    already reject bool/float before it runs.
    """
    port = cfg.get("port")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError(
            "bad stored %s: port must be an integer 1-65535, got %s %s"
            % (CONFIG_FILE, type(port).__name__, repr(port)[:64]))
    for key in ("enabled", "fail_open", "udp_over_tcp"):
        v = cfg.get(key)
        if type(v) is bool:
            continue
        if type(v) is int and v in (0, 1):
            cfg[key] = bool(v)  # normalize the R12-pinned 0/1 form
            continue
        raise ValueError(
            "bad stored %s: %s must be a boolean (0/1 accepted), got %s"
            % (CONFIG_FILE, key, type(v).__name__))


def _load_config() -> dict:
    cfg = _default_config()
    if _exists(CONFIG_FILE):
        try:
            stored = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except PermissionError as exc:
            # A permission problem is not a parse problem: say so, and
            # say how to fix it. (Seen live: a root-owned 0600
            # sk5.json makes a non-root agent fail every call with a
            # misleading "cannot parse" -- the agent normally runs as
            # root, but the integration test runs it as nobody.)
            raise RuntimeError(
                "cannot read %s: permission denied -- run as root (the "
                "agent normally runs as root) or fix the file's "
                "ownership/permissions" % CONFIG_FILE
            ) from exc
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"cannot parse {CONFIG_FILE}: {exc}") from exc
        if not isinstance(stored, dict):
            raise RuntimeError(f"{CONFIG_FILE} is not a JSON object")
        cfg.update({k: v for k, v in stored.items() if k in cfg})
        _validate_stored(cfg)  # R20-P2-1: reject bad shapes, never launder
    return cfg


def _atomic_write_json(path: Path, payload: str) -> None:
    """Atomically write *payload* (JSON text) to *path*.

    AJ (R7-BUG-3 family): the four write sites in this module used
    to share one FIXED temp name (``path.with_suffix(".json.tmp")``).
    Panel and agent are two processes; when both saved at once, one
    os.replace() moved the tmp away and the other's os.replace()
    died FileNotFoundError (``'sk5.json.tmp' -> 'sk5.json'``) -- an
    occasional 500 on a plain save. Each writer now gets a UNIQUE
    temp name (pid + random token) in the same directory, so
    os.replace stays on one filesystem and writers never step on
    each other. On any failure the writer removes its own temp file
    (no garbage left) and raises a RuntimeError naming the target
    path and the underlying error, so the failure is diagnosable
    instead of a bare FileNotFoundError.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (
        "%s.tmp.%d.%x" % (path.name, os.getpid(), random.randrange(1 << 62)))
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError(
            "cannot write %s (via temp %s): %s" % (path, tmp.name, exc)
        ) from exc


def _save_config(cfg: dict) -> None:
    _atomic_write_json(CONFIG_FILE, json.dumps(cfg, indent=2) + "\n")


def _redact(cfg: dict) -> dict:
    """Public view of the config: host/port/switches, never the secret."""
    return {
        "host": cfg.get("host", ""),
        "port": cfg.get("port", 1080),
        "username": cfg.get("username", ""),
        "has_password": bool(cfg.get("password")),
        "enabled": bool(cfg.get("enabled")),
        "fail_open": bool(cfg.get("fail_open")),
        "udp_over_tcp": bool(cfg.get("udp_over_tcp")),
    }


def _validate(host: str, port: int) -> None:
    if not host or not isinstance(host, str) or len(host) > 253:
        raise ValueError("host must be a non-empty hostname or IP")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer 1-65535")


def _run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------- sing-box

def _render_singbox_config(cfg: dict) -> Path:
    """Render the template with the stored SK5 credential.

    Placeholders __SK5_HOST__ / __SK5_PORT__ / __SK5_USER__ /
    __SK5_PASS__ are replaced; the udp_over_tcp line is set from the
    stored switch. Empty username/password keys are dropped entirely
    (some merchants run auth-free SOCKS5; sing-box rejects empty
    strings there). Lines starting with '#' in the template are
    comments and are stripped before writing.
    """
    if not TEMPLATE.exists():
        raise RuntimeError(f"template not found: {TEMPLATE}")
    text = TEMPLATE.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    text = "\n".join(lines) + "\n"
    text = text.replace("__SK5_HOST__", cfg["host"])
    text = text.replace("__SK5_PORT__", str(int(cfg["port"])))
    text = text.replace("__SK5_USER__", cfg.get("username", ""))
    text = text.replace("__SK5_PASS__", cfg.get("password", ""))
    text = text.replace(
        '"udp_over_tcp": false',
        '"udp_over_tcp": %s' % ("true" if cfg.get("udp_over_tcp") else "false"),
    )
    rendered = json.loads(text)  # fail fast on bad JSON, before check
    # Drop empty auth keys so auth-free merchants validate cleanly.
    for outbound in rendered.get("outbounds", []):
        if outbound.get("tag") == "bought-sk5":
            if not cfg.get("username"):
                outbound.pop("username", None)
            if not cfg.get("password"):
                outbound.pop("password", None)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(RENDERED_CONFIG, json.dumps(rendered, indent=2) + "\n")
    return RENDERED_CONFIG


def _render_direct_config() -> Path:
    """Render the direct-mode sing-box config (no SK5 outbound).

    Same shape as the install.sh starter config: tun1 up, DNS
    direct, route.final = "direct". Derived from the SK5 template
    (drop the bought-sk5 outbound, flip route.final) instead of a
    second hand-written copy, so the two cannot drift apart.
    R3-BUG-1: disable() restarts sing-box in this mode -- the
    installer establishes "sing-box always up" as an invariant, and
    a disable that only stops it leaves direct mode with no tun1
    and no panel path to bring sing-box back.
    """
    if not TEMPLATE.exists():
        raise RuntimeError(f"template not found: {TEMPLATE}")
    text = TEMPLATE.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    text = "\n".join(lines) + "\n"
    # Placeholders are never used in direct mode (the outbound is
    # dropped below); substitute inert values so json.loads works.
    text = text.replace("__SK5_HOST__", "127.0.0.1")
    text = text.replace("__SK5_PORT__", "1")
    text = text.replace("__SK5_USER__", "")
    text = text.replace("__SK5_PASS__", "")
    rendered = json.loads(text)  # fail fast on bad JSON, before check
    rendered["outbounds"] = [
        o for o in rendered.get("outbounds", []) if o.get("tag") != "bought-sk5"
    ]
    rendered.setdefault("route", {})["final"] = "direct"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(RENDERED_CONFIG, json.dumps(rendered, indent=2) + "\n")
    return RENDERED_CONFIG


def _singbox_check() -> None:
    """Run `sing-box check -c <rendered>`; raise on failure."""
    if not os.path.exists(SINGBOX_BIN):
        raise RuntimeError(
            f"sing-box not found at {SINGBOX_BIN}: install sing-box 1.11+ first "
            "(see egress/README.md)"
        )
    proc = _run([SINGBOX_BIN, "check", "-c", str(RENDERED_CONFIG)], timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(
            "sing-box check failed: " + (proc.stderr or proc.stdout or "").strip()[-500:]
        )


def _singbox_running() -> bool:
    # Either control path counts: systemd unit OR the direct PID file.
    # (A stale PID file must not mask a running systemd unit.)
    try:
        proc = _run(["systemctl", "is-active", "--quiet", SYSTEMD_UNIT], timeout=10)
        if proc.returncode == 0:
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    if _exists(PID_FILE):
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return True
        except (ValueError, OSError):
            return False
    return False


def _start_singbox() -> None:
    _singbox_check()
    # Preferred: systemd unit, if the installer created it.
    proc = _run(["systemctl", "is-enabled", "--quiet", SYSTEMD_UNIT], timeout=10)
    if proc.returncode == 0:
        # R4-BUG-1: the unit carries StartLimitBurst=5/120s (BUG-3
        # guard). Six operator toggles in a row wedge it in failed
        # state (start-limit-hit) and every later start is refused
        # until somebody runs reset-failed by hand. Clear the
        # start-rate accounting first -- the field-proven recovery
        # (live-R4: reset-failed && start, then two more starts in
        # the same window succeeded). Best-effort: a failure here
        # must not block the restart attempt itself. The crash-loop
        # guard still bounds systemd's OWN automatic restarts
        # (Restart=on-failure) to 5 per episode, and sing-box check
        # above gates a bad config before any restart happens.
        try:
            _run(["systemctl", "reset-failed", SYSTEMD_UNIT], timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
        proc = _run(["systemctl", "restart", SYSTEMD_UNIT], timeout=30)
        if proc.returncode != 0:
            raise RuntimeError(
                "systemctl restart %s failed: %s"
                % (SYSTEMD_UNIT, (proc.stderr or proc.stdout or "").strip()[-300:])
            )
        return
    # Fallback: direct background process (plain box, no unit installed).
    _stop_singbox_direct()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "ab") as log:
        proc = subprocess.Popen(
            [SINGBOX_BIN, "run", "-c", str(RENDERED_CONFIG)],
            stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True,
        )
    PID_FILE.write_text(str(proc.pid) + "\n", encoding="utf-8")
    time.sleep(1)
    if proc.poll() is not None:
        raise RuntimeError(
            f"sing-box exited immediately (rc={proc.returncode}); see {LOG_FILE}"
        )


def _stop_singbox_direct() -> None:
    if _exists(PID_FILE):
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 15)
            for _ in range(20):
                time.sleep(0.25)
                try:
                    os.kill(pid, 0)
                except OSError:
                    break
            else:
                os.kill(pid, 9)
        except (ValueError, OSError):
            pass
        try:
            PID_FILE.unlink()
        except OSError:
            pass


def _stop_singbox() -> None:
    proc = _run(["systemctl", "is-enabled", "--quiet", SYSTEMD_UNIT], timeout=10)
    if proc.returncode == 0:
        _run(["systemctl", "stop", SYSTEMD_UNIT], timeout=30)
    _stop_singbox_direct()


def _apply_policy(verb: str = "repair") -> None:
    """Run policy-routing.sh <verb> (R14-BUG-1: repair is a separate
    verb -- it must never create tun1, see the script header).

    The default is "repair" (R24-P2-1 / BT): since the BT fix the
    panel enable / set_sk5 paths also run repair semantics -- the
    old "enable" verb's placeholder fallback (ensure_tun1) is
    deleted from the script, and both verbs now install only the
    blackhole + rule plus the tun1 route when tun1 is LIVE
    (LOWER_UP, i.e. sing-box holds it). The health-check self-heal
    uses "repair" explicitly; enable() passes it explicitly too.
    The script keeps an "enable" entry point for compatibility, but
    it behaves identically to "repair" now."""
    if not POLICY_SCRIPT.exists():
        raise RuntimeError(f"policy script not found: {POLICY_SCRIPT}")
    proc = _run(["bash", str(POLICY_SCRIPT), verb], timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(
            "policy-routing.sh %s failed: " % verb
            + (proc.stderr or proc.stdout or "").strip()[-500:]
        )


def _remove_policy() -> None:
    if POLICY_SCRIPT.exists():
        _run(["bash", str(POLICY_SCRIPT), "disable"], timeout=30)


# ---------------------------------------------------------------- probes

def _curl_via_sk5(cfg: dict, url: str, timeout: int = TIMEOUT) -> tuple[bool, str | None, float]:
    """TCP probe: real HTTP GET through the SOCKS5. Returns (ok, ip, ms)."""
    cmd = [
        "curl", "-sS", "--max-time", str(timeout),
        "--socks5-hostname", f"{cfg['host']}:{int(cfg['port'])}",
    ]
    if cfg.get("username"):
        cmd += ["--proxy-user", f"{cfg.get('username')}:{cfg.get('password', '')}"]
    cmd += [url]
    start = time.monotonic()
    proc = _run(cmd, timeout=timeout + 5)
    elapsed_ms = (time.monotonic() - start) * 1000.0
    if proc.returncode != 0:
        return False, None, elapsed_ms
    lines = (proc.stdout or "").strip().splitlines()
    ip = lines[0].strip() if lines else ""
    return (bool(ip), ip or None, elapsed_ms)


def _build_dns_query(name: str, txid: int) -> bytes:
    header = struct.pack(">HHHHHH", txid, 0x0100, 1, 0, 0, 0)
    qname = b"".join(bytes([len(part)]) + part.encode() for part in name.split("."))
    return header + qname + b"\x00" + struct.pack(">HH", 1, 1)  # A, IN


def _strip_socks_udp_header(data: bytes) -> bytes | None:
    """SOCKS UDP reply -> inner payload, or None if the datagram is
    not a well-formed SOCKS UDP reply (too short, unknown ATYP).
    Shared by the verdict parser and the reply-note helper so the
    header walk lives in exactly one place."""
    if len(data) < 14:
        return None
    off = 3  # skip RSV(2) + FRAG(1), data[3] is ATYP
    atyp = data[off]
    if atyp == 0x01:
        off += 1 + 4 + 2
    elif atyp == 0x03:
        if off + 1 >= len(data):
            return None
        off += 1 + 1 + data[off + 1] + 2
    elif atyp == 0x04:
        off += 1 + 16 + 2
    else:
        return None
    return data[off:]


_DNS_RCODES = {0: "NOERROR", 1: "FORMERR", 2: "SERVFAIL", 3: "NXDOMAIN",
               4: "NOTIMP", 5: "REFUSED"}


def _parse_socks_udp_dns_reply(data: bytes, txid: int) -> bool:
    """Pure parser: SOCKS UDP reply -> does it carry a legitimate DNS
    response with the expected transaction ID?

    Round-trip proof, NOT answer proof (R27-P2-1): a txid-matching
    DNS response proves the relay carried a packet both ways, whatever
    the resolver's answer database says about the queried name -- an
    empty NOERROR (ancount=0; live-18: upstream 1.1.1.1 answered
    example.com with zero answers while the relay demonstrably worked,
    39-byte query out, 29-byte reply back, txid matched) is a PASS.
    Answer content (ancount, rcode) is the resolver's business, never
    the relay's verdict; it is recorded in the probe note instead
    (see _dns_reply_note).

    "Legitimate" means: a well-formed DNS header (12 bytes) with the
    QR bit set (it IS a response, not a stray query) and the expected
    transaction ID. Any rcode passes, including NXDOMAIN and SERVFAIL
    -- the resolver answered, so the relay worked.

    Split out of _socks5_udp_associate_dns so the logic is unit-
    testable without any socket (the sandbox blocks UDP sendto, so
    live UDP tests can only run on a real machine -- see README).
    """
    dns = _strip_socks_udp_header(data)
    if dns is None or len(dns) < 12:
        return False
    resp_txid, flags, _qd, _an = struct.unpack(">HHHH", dns[:8])
    return resp_txid == txid and bool(flags & 0x8000)


def _dns_reply_note(data: bytes, txid: int) -> str:
    """One-line summary of a txid-matching DNS reply for the probe
    note (R27-P2-1): answer content is recorded HERE, never in the
    verdict. E.g. "reply NOERROR an=0" / "reply NXDOMAIN an=0".
    Returns "" when the packet is not a matching DNS response."""
    dns = _strip_socks_udp_header(data)
    if dns is None or len(dns) < 12:
        return ""
    resp_txid, flags, _qd, ancount = struct.unpack(">HHHH", dns[:8])
    if resp_txid != txid or not (flags & 0x8000):
        return ""
    rcode = flags & 0x000F
    return "reply %s an=%d" % (_DNS_RCODES.get(rcode, "rcode=%d" % rcode),
                               ancount)


def _socks5_udp_associate_dns(
    proxy_host: str, proxy_port: int, username: str, password: str,
    timeout: int = TIMEOUT,
) -> tuple[bool, float, str]:
    """Real UDP probe: SOCKS5 UDP ASSOCIATE + DNS query via the relay.

    1. TCP handshake to the SOCKS5 (auth 0x00, or 0x02 user/pass).
    2. CMD 0x03 UDP ASSOCIATE -> relay IP:port from the server.
    3. Send a DNS A query through the relay (SOCKS UDP header + DNS
       payload), wait for a DNS response with the same transaction ID.
    Returns (udp_ok, latency_ms, note). No TCP result is ever reported
    here.

    Verdict (R27-P2-1): udp_ok is ROUND-TRIP proof -- any txid-matching
    legitimate DNS response passes, even an empty NOERROR (ancount=0)
    or NXDOMAIN; the answer content is recorded in the note, never in
    the verdict. Depth: two attempts -- (example.com, 1.1.1.1) then
    (cloudflare.com, 8.8.8.8) -- so one resolver's empty answer
    database or one lost packet cannot condemn UDP; a timeout or a
    non-matching reply falls through to the next attempt.
    """
    start = time.monotonic()
    tcp = None
    udp = None
    try:
        # Inside try on purpose: an unreachable/refused proxy must
        # return (False, ms, note), never raise into the caller.
        tcp = socket.create_connection((proxy_host, int(proxy_port)), timeout=timeout)
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tcp.settimeout(timeout)
        udp.settimeout(timeout)
        methods = b"\x02" if username else b"\x00"
        tcp.sendall(b"\x05\x01" + methods)
        resp = tcp.recv(2)
        if len(resp) != 2 or resp[0] != 0x05 or resp[1] not in (0x00, 0x02):
            return False, (time.monotonic() - start) * 1000.0, \
                "UDP ASSOCIATE handshake rejected"
        if resp[1] == 0x02:
            u, p = username.encode(), password.encode()
            tcp.sendall(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
            auth = tcp.recv(2)
            if len(auth) != 2 or auth[1] != 0x00:
                return False, (time.monotonic() - start) * 1000.0, \
                    "UDP ASSOCIATE auth failed"
        tcp.sendall(b"\x05\x03\x00\x01\x00\x00\x00\x00\x00\x00")
        reply = tcp.recv(64)
        if len(reply) < 10 or reply[1] != 0x00:
            return False, (time.monotonic() - start) * 1000.0, \
                "UDP ASSOCIATE refused"
        atyp = reply[3]
        if atyp == 0x01:
            relay = (socket.inet_ntoa(reply[4:8]), struct.unpack(">H", reply[8:10])[0])
        elif atyp == 0x03:
            n = reply[4]
            relay = (reply[5:5 + n].decode(), struct.unpack(">H", reply[5 + n:7 + n])[0])
        elif atyp == 0x04:
            relay = (socket.inet_ntop(socket.AF_INET6, reply[4:20]),
                     struct.unpack(">H", reply[20:22])[0])
        else:
            return False, (time.monotonic() - start) * 1000.0, \
                "UDP ASSOCIATE returned unknown ATYP"
        # Two attempts, one sendto/recvfrom call site each inside the
        # loop: (example.com, 1.1.1.1) then the depth retry
        # (cloudflare.com, 8.8.8.8). A timeout or a non-matching reply
        # falls through to the next attempt instead of condemning UDP.
        attempts = [(DNS_QUERY_NAME, DNS_SERVER),
                    (DNS_QUERY_NAME2, DNS_SERVER2)]
        for name, server in attempts:
            txid = random.randint(0, 0xFFFF)
            query = _build_dns_query(name, txid)
            # SOCKS UDP header: RSV(2) FRAG(1) ATYP(1) DST(4) PORT(2) + DNS.
            packet = b"\x00\x00\x00\x01" + socket.inet_aton(server) \
                + struct.pack(">H", 53) + query
            try:
                udp.sendto(packet, relay)
                data, _ = udp.recvfrom(2048)
            except (OSError, socket.timeout):
                continue
            if _parse_socks_udp_dns_reply(data, txid):
                return True, (time.monotonic() - start) * 1000.0, \
                    "native UDP ASSOCIATE + DNS to %s:53 (%s, %s)" % (
                        server, name, _dns_reply_note(data, txid))
        return False, (time.monotonic() - start) * 1000.0, \
            "native UDP ASSOCIATE + DNS: no txid-matching reply from " \
            "1.1.1.1:53 (example.com) or 8.8.8.8:53 (cloudflare.com)"
    except (OSError, socket.timeout, struct.error, ValueError, IndexError):
        return False, (time.monotonic() - start) * 1000.0, \
            "UDP ASSOCIATE raised (network unreachable?)"
    finally:
        for sock in (tcp, udp):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass


def _udp_probe_via_uot_singbox(cfg: dict) -> tuple[bool, float, str]:
    """UDP probe for udp_over_tcp=true: spin a throwaway sing-box.

    The temp sing-box listens on a per-probe 127.0.0.1 port (socks
    inbound) and forwards to bought-sk5 with udp_over_tcp=true. The
    same UDP ASSOCIATE + DNS probe is then run against the *local*
    inbound, so a pass proves the whole UoT path (sing-box wraps UDP
    in TCP to the merchant), not just native UDP ASSOCIATE.

    P1-12 / P2-11: the throwaway config carries the SK5 password, so
    it lives in a unique mkdtemp dir (0700, config file 0600 -- never
    umask-dependent, never a fixed /tmp path two concurrent probes
    can step on), and the whole dir is removed afterwards.
    """
    if not os.path.exists(SINGBOX_BIN):
        return False, 0.0, "sing-box binary missing, cannot probe UoT path"
    tmpdir = Path(tempfile.mkdtemp(prefix="ovpn-sk5-uot-probe-"))
    os.chmod(tmpdir, 0o700)
    # Free loopback port per probe (the old fixed 18080 collided
    # between concurrent probes the same way the fixed path did).
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        probe_port = s.getsockname()[1]
    tmpcfg = tmpdir / "sing-box.json"
    outbound: dict = {
        "type": "socks", "tag": "bought-sk5",
        "server": cfg["host"], "server_port": int(cfg["port"]),
        "version": "5", "udp_over_tcp": True,
    }
    if cfg.get("username"):
        outbound["username"] = cfg["username"]
        outbound["password"] = cfg.get("password", "")
    payload = json.dumps({
        "log": {"level": "error"},
        "inbounds": [{"type": "socks", "tag": "probe-in",
                      "listen": "127.0.0.1", "listen_port": probe_port}],
        "outbounds": [outbound, {"type": "direct", "tag": "direct"}],
        "route": {"final": "bought-sk5"},
    }, indent=2)
    fd = os.open(tmpcfg, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise
    proc = subprocess.Popen(
        [SINGBOX_BIN, "run", "-c", str(tmpcfg)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True,
    )
    try:
        # Wait for the local listener to accept.
        for _ in range(20):
            time.sleep(0.25)
            try:
                with socket.create_connection(("127.0.0.1", probe_port), timeout=1):
                    break
            except OSError:
                continue
        else:
            return False, 0.0, "temp sing-box did not listen in time"
        ok, ms, inner_note = _socks5_udp_associate_dns("127.0.0.1", probe_port, "", "")
        return ok, ms, "udp_over_tcp via temp sing-box (127.0.0.1:%d) (%s)" % (
            probe_port, inner_note)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------- public API

def set_sk5(host: str | None = None, port: int | None = None,
            username: str | None = None, password: str | None = None,
            enabled: bool | None = None, fail_open: bool | None = None,
            udp_over_tcp: bool | None = None,
            clear_password: bool = False) -> dict:
    """Store SK5 fields and (if enabled) apply them immediately.

    Partial-merge semantics -- this is the contract the panel and the
    Cloudflare Worker rely on (P0-2 / P0-4): any field passed as None
    keeps its stored value, so a single-field toggle (``fail_open`` /
    ``udp_over_tcp``) works without resending host+port. The password
    is special: None *or* an empty string keeps the stored password
    (a frontend that leaves the password box blank must never wipe
    the credential); only a non-empty password overwrites it. To
    switch to an auth-free merchant deliberately, pass
    ``clear_password=True``. With enabled=False the credential is
    stored but the chain stays off.

    Mode changes only (R4-P1-1): enable()/disable() run ONLY when the
    enabled flag actually flips. A save on an already-disabled chain
    is a pure config write -- it must not touch the daemon, because
    on a host where sing-box cannot (re)start (no TUN, broken
    binary) the save would 500 even though the credential was
    already stored. A save on an already-enabled chain re-renders
    and restarts only when a chain-affecting field (host/port/
    username/password/udp_over_tcp) changed; a fail_open-only change
    needs no restart. Returns the redacted public status (never
    the password).

    R4-BUG-1: two more rules on top of the mode-change rule.
    (a) Save-after-success on the enable flip: the old code saved
    enabled=true BEFORE calling enable(), so a failed enable left
    the disk claiming the chain was on while nothing was running
    (500 + enabled=true). Now the flip saves the fields with
    enabled still False and lets enable() persist enabled=true
    only after the daemon is up and the policy is applied. The
    disable side keeps O's "save first, restart best-effort"
    rule (disable is a downgrade: the write itself takes effect).
    (b) Repair, never a bare short-circuit, on re-enable: when the
    chain is already enabled and nothing chain-affecting changed,
    the save first checks the chain is actually effective
    (daemon running AND policy applied). If it is not -- start-
    limit wedge aftermath, manual policy deletion -- the call
    repairs instead of returning a bare 200 (a bare 200 there
    left traffic silently direct while the panel claimed SK5 on).
    The repair re-applies just the policy when the daemon is
    alive, or runs the full enable() when it is dead, and reports
    what it fixed (repaired=true + repair_detail). A repair that
    still fails raises honestly instead of reporting success.
    """
    cfg = _load_config()
    was_enabled = bool(cfg.get("enabled"))
    old_chain = {k: cfg.get(k) for k in
                 ("host", "port", "username", "password", "udp_over_tcp")}
    if host is not None and str(host) != "":
        cfg["host"] = str(host)
    if port is not None:
        cfg["port"] = int(port)
    if username is not None:
        cfg["username"] = str(username) or ""
    if clear_password:
        cfg["password"] = ""
    elif password:
        cfg["password"] = str(password)
    if enabled is not None:
        cfg["enabled"] = bool(enabled)
    if fail_open is not None:
        cfg["fail_open"] = bool(fail_open)
    if udp_over_tcp is not None:
        cfg["udp_over_tcp"] = bool(udp_over_tcp)
    if not cfg.get("host"):
        raise ValueError(
            "host is required: no SK5 stored yet, pass host+port")
    _validate(cfg["host"], int(cfg["port"]))
    now_enabled = bool(cfg["enabled"])
    if now_enabled and not was_enabled:
        # Flip disabled -> enabled: save the fields WITHOUT flipping
        # enabled on disk yet, then enable() (which persists
        # enabled=true only after the daemon is up and the policy
        # is applied). A failed enable leaves the disk at False --
        # no "enabled=true but nothing running" lie. enable()
        # raises honestly (panel: 500) on failure.
        cfg["enabled"] = False
        _save_config(cfg)
        return enable()
    _save_config(cfg)
    if not now_enabled and was_enabled:
        # Flip enabled -> disabled: O's rule -- save first (the
        # write itself takes effect), disable() is best-effort and
        # reports a restart failure honestly instead of raising.
        # Return disable()'s status directly so its honest fields
        # (policy_removed / singbox_restart_error) survive instead
        # of being discarded by a fresh get_status().
        return disable()
    if now_enabled and any(
            cfg.get(k) != old_chain[k] for k in
            ("host", "port", "username", "password", "udp_over_tcp")):
        # Still enabled, chain-affecting field changed: re-render +
        # restart so the running chain picks the new credential.
        # The chain was already enabled, so enabled=true on disk
        # stays correct-as-intent even if the restart fails (the
        # failure raises, and singbox_running / policy flags in the
        # next status report the broken effective state honestly).
        return enable()
    if now_enabled:
        # Still enabled, no chain-affecting change: normally a pure
        # save (fail_open-only change needs no restart). First check
        # the chain is actually effective -- R4-BUG-1.
        effective, problems = _chain_effective(cfg)
        if effective:
            return get_status()
        repaired: list[str] = []
        if not _singbox_running():
            # Daemon dead: full enable() (render + reset-failed /
            # start + policy). Restarts feed the start-limit
            # counter, so this runs only when the daemon is really
            # down -- never on a healthy no-op save.
            status = enable()
            repaired.append("sing-box restarted")
        else:
            # Daemon alive, policy missing: re-applying the policy
            # is enough; do NOT restart the daemon for it. Repair
            # semantics (R24-P2-1): never a placeholder -- if tun1
            # is gone the repair installs blackhole-only and the
            # _chain_effective check below raises honestly.
            _apply_policy(verb="repair")
            status = get_status()
            repaired.append("policy routing re-applied")
        # Verify the repair actually landed; a repair that still
        # fails raises honestly instead of reporting success.
        effective_after, problems_after = _chain_effective(_load_config())
        if not effective_after:
            raise RuntimeError(
                "SK5 repair failed: " + "; ".join(problems_after))
        status["repaired"] = True
        status["repair_detail"] = repaired
        return status
    # Still disabled: pure save, the daemon is not touched.
    return get_status()


def test_sk5() -> dict:
    """Real dial test against the stored SK5. TCP and UDP separately.

    Returns {"tcp_ok","udp_ok","egress_ip","latency_ms",
             "udp_mode","udp_note","host","port"}.
    tcp_ok: curl --socks5-hostname fetched ifconfig.me through the SK5.
    udp_ok: SOCKS5 UDP ASSOCIATE + DNS query through the relay returned
    a txid-matching DNS response (R27-P2-1: any rcode, even an empty
    NOERROR -- the answer content is the resolver's business, recorded
    in udp_note, never the verdict; on no reply it retries once with a
    second name + second resolver). If udp_over_tcp is on,
    the UDP probe runs through a throwaway sing-box so it exercises
    the UoT encapsulation. A TCP pass never sets udp_ok.
    """
    cfg = _load_config()
    if not cfg.get("host"):
        return {"tcp_ok": False, "udp_ok": False, "egress_ip": None,
                "latency_ms": None, "udp_mode": "native",
                "udp_note": "no SK5 configured", "host": "", "port": 0}
    tcp_ok, egress_ip, tcp_ms = _curl_via_sk5(cfg, EGRESS_CHECK_URL)
    latency_ms = round(tcp_ms, 1) if tcp_ok else None
    if cfg.get("udp_over_tcp"):
        udp_ok, _udp_ms, note = _udp_probe_via_uot_singbox(cfg)
        udp_mode = "udp_over_tcp"
    else:
        try:
            udp_ok, _udp_ms, note = _socks5_udp_associate_dns(
                cfg["host"], int(cfg["port"]),
                cfg.get("username", ""), cfg.get("password", ""))
        except (OSError, socket.timeout, ValueError):
            udp_ok, note = False, "UDP ASSOCIATE raised (network unreachable?)"
        udp_mode = "native"
    return {
        "tcp_ok": tcp_ok, "udp_ok": udp_ok, "egress_ip": egress_ip,
        "latency_ms": latency_ms, "udp_mode": udp_mode, "udp_note": note,
        "host": cfg["host"], "port": int(cfg["port"]),
    }


def current_egress_ip() -> str | None:
    """Egress IP as the world sees it: via SK5 if enabled, else direct."""
    try:
        cfg = _load_config()
    except (RuntimeError, ValueError, OSError):
        return None  # unreadable config: no egress claim to make
    if cfg.get("enabled") and cfg.get("host"):
        ok, ip, _ms = _curl_via_sk5(cfg, EGRESS_CHECK_URL)
        return ip if ok else None
    try:
        proc = _run(["curl", "-sS", "--max-time", str(TIMEOUT), EGRESS_CHECK_URL],
                    timeout=TIMEOUT + 5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    lines = (proc.stdout or "").strip().splitlines()
    return lines[0].strip() if lines else None


def _rule_present() -> bool:
    """Is the from-VPN-net policy rule in place? (R4-P2-1: the rule
    alone is not enough -- _policy_active() also requires the tun1
    route -- but the rule alone decides whether VPN traffic even
    ENTERS table 100: without it, traffic goes direct no matter
    what table 100 holds, blackhole included.)"""
    try:
        proc = _run(["ip", "rule", "show"], timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return (VPN_NET in (proc.stdout or "")
            and "lookup 100" in (proc.stdout or ""))


def _blackhole_active() -> bool:
    """Does table 100 hold the device-independent fallback blackhole
    route (R13-BUG-1 layer 1)? This is NOT chain health -- a
    blackhole-only table means the chain is down -- it only answers
    what happens to VPN traffic while the policy is missing: with
    the rule present and the blackhole present, traffic is dropped;
    without either one, it egresses direct. Used only to make
    check_health()'s policy_missing detail tell the truth."""
    try:
        proc = _run(["ip", "route", "show", "table", "100"],
                    timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if parts and parts[0] == "blackhole" and "default" in parts:
            return True
    return False


def _tun1_link_text() -> str | None:
    """`ip link show dev tun1` output, or None when the device is
    absent (or `ip` itself fails). The None-vs-empty distinction
    matters: rc != 0 means "no such device"; rc == 0 with output
    means the device exists and its flags can be judged."""
    try:
        proc = _run(["ip", "link", "show", "dev", "tun1"], timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout or ""


def _tun1_live() -> bool:
    """Is tun1 a LIVE sing-box-owned device? Live means LOWER_UP:
    sing-box holds the fd open and brings the link up, so a device
    it owns always shows UP,LOWER_UP. Mere existence is NOT live --
    a dead placeholder exists too (UP, NO-CARRIER, state DOWN)."""
    text = _tun1_link_text()
    return text is not None and "LOWER_UP" in text


def _tun1_dead_placeholder() -> bool:
    """Is tun1 a dead placeholder (R24-P2-1)? Triple check: the
    device exists, shows NO-CARRIER, and has no LOWER_UP -- the
    exact shape ensure_tun1 used to write, and a shape a live
    sing-box-owned device never has (sing-box holds the fd and
    brings the link up, so a live tun1 always shows LOWER_UP).
    A route via such a device installs as linkdown: it carries
    nothing while shadowing the blackhole at lookup level."""
    text = _tun1_link_text()
    return (text is not None and "NO-CARRIER" in text
            and "LOWER_UP" not in text)


def _remove_dead_tun1_placeholder() -> bool:
    """Delete a dead tun1 placeholder, if one is present (R24-P2-1).

    BO rejected deleting the device from the repair path for the
    "delete a live device" race; this helper answers that race
    head-on, and deletes only when ALL of these hold:
      1. the device passes the triple dead check
         (_tun1_dead_placeholder: exists + NO-CARRIER + no
         LOWER_UP) -- a sing-box-held device that is up always
         carries LOWER_UP and never shows NO-CARRIER;
      2. sing-box is NOT running (_singbox_running() is False) --
         so no holder can be mid-flight creating or bringing the
         device up. The only remaining window is a systemd
         auto-restart spawning sing-box between this check and the
         delete: then the racing sing-box either creates tun1
         after the delete (clean start) or created it just before
         the delete but has not brought it up yet (its start fails
         and systemd retries it; the next enable / health tick
         succeeds). Either way the outcome is a transient failed
         start, never a wedge -- unlike the placeholder itself,
         which wedged every later start with TUNSETIFF "Device or
         resource busy" until a human deleted it.
    Returns True if a placeholder was deleted. Never raises: a
    failed delete just leaves the old state, and the caller's loud
    failure / next tick reports it.
    """
    if not _tun1_dead_placeholder():
        return False
    if _singbox_running():
        return False
    try:
        proc = _run(["ip", "link", "del", "dev", "tun1"], timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _repair_policy() -> tuple[bool, str]:
    """One self-heal attempt for a missing policy (R13-BUG-1 layer 2).

    Runs policy-routing.sh repair, NOT enable (R14-BUG-1): the
    repair verb never creates tun1 -- sing-box owns the device,
    and a repair-created placeholder blocks the daemon's own
    restart (TUNSETIFF "Device or resource busy") and burns all
    5 systemd restarts. If sing-box has not recreated tun1 yet,
    the script installs only the blackhole + rule and exits 0;
    the caller re-checks the repair verb's own contract
    (_repair_holding(): rule + blackhole in place), NOT
    _policy_active() -- that needs the tun1 route, which cannot
    exist until sing-box recreates the device, so judging the
    repair by it mislabels a successful repair as failed
    (R15-BUG-1: "did not stick"). The next 60 s tick completes
    the repair once sing-box is up. Returns (ok, note): ok means
    the script exited 0 -- the caller still re-checks the
    repair's own contract, since a script can exit 0 while a
    route fails to stick. Never raises: a repair failure is
    reported in the note, never thrown into check_health() (which
    must never raise on probe error).

    R24-P2-1 (BT): before re-applying, clear a dead placeholder
    left by a pre-fix enable (_remove_dead_tun1_placeholder):
    without it the wedge survives the repair -- the linkdown route
    is deleted but the device stays, and sing-box can still never
    restart. The delete runs only on a triple-checked dead device
    with no sing-box holder (see that helper for the race
    analysis), so a live device is never touched.
    """
    _remove_dead_tun1_placeholder()
    try:
        _apply_policy(verb="repair")
    except (RuntimeError, OSError) as exc:
        return False, "policy re-apply failed: %s" % exc
    return True, "policy re-applied by health check"


def _repair_holding() -> bool:
    """Did the repair verb's own contract hold? The repair verb
    (R14-BUG-1) installs only the blackhole + rule while sing-box
    is dead -- it never creates tun1, so the tun1 route cannot
    exist until the daemon recreates the device. Judging the
    repair by _policy_active() (which needs that route) mislabels
    a successful repair as failed (R15-BUG-1: "did not stick" for
    a repair that did everything it was designed to do). This
    predicate is the repair verb's own self-check caliber: rule
    present AND blackhole present. It does NOT mean the chain can
    carry traffic -- _policy_active() is still the only test for
    that, and stays the gate for policy_repaired / healthy."""
    return _rule_present() and _blackhole_active()


def _policy_active(cfg: dict) -> bool:
    """Is policy routing EFFECTIVE for an enabled chain? All three
    must hold (R4-P2-1): the chain is enabled, the from-VPN-net rule
    is in place, AND table 100 actually carries a default route via
    tun1. A bare rule with an empty table 100 (SK5 off) used to
    report "active" while no traffic was policy-routed at all;
    with SK5 off this is always false. The fallback blackhole route
    (R13-BUG-1) deliberately does NOT count here: a blackhole-only
    table means traffic is safely dropped, but the chain is down --
    reporting "active" would hide that and suppress the repair.
    A linkdown route does NOT count either (R24-P2-1): a route via
    a dead tun1 (UP, NO-CARRIER) carries nothing -- the kernel
    marks it linkdown -- but the old matcher accepted any
    `default ... dev tun1` line, so an enable-path placeholder
    made this predicate report True while VPN traffic was entirely
    dropped, and check_health never repaired (the placeholder also
    blocked sing-box's restart). The route line must contain no
    `linkdown` token to count."""
    if not cfg.get("enabled"):
        return False
    try:
        rule_ok = _rule_present()
        route_ok = False
        if rule_ok:
            rproc = _run(["ip", "route", "show", "table", "100"],
                         timeout=10)
            for line in (rproc.stdout or "").splitlines():
                parts = line.split()
                if (parts and parts[0] == "default"
                        and "dev" in parts and "tun1" in parts
                        and "linkdown" not in parts):
                    route_ok = True
                    break
        return rule_ok and route_ok
    except (OSError, subprocess.TimeoutExpired):
        return False


def _chain_effective(cfg: dict) -> tuple[bool, list[str]]:
    """Is an enabled chain actually live (no network probe)? The
    daemon must be running AND policy routing must be applied.
    Returns (ok, problems). Used by set_sk5() before it takes the
    no-op short-circuit: after a start-limit wedge, or a manual
    policy deletion, the disk can say enabled=true while the chain
    is dead -- a bare 200 there would leave VPN traffic silently
    direct (R4-BUG-1 second stage)."""
    problems: list[str] = []
    if not _singbox_running():
        problems.append("sing-box not running")
    if not _policy_active(cfg):
        problems.append("policy routing not applied")
    return (not problems, problems)


def get_status() -> dict:
    """Public status: config (redacted) + live chain state.

    Read-only: an unreadable config file must not make status fail
    hard (a non-root agent against a root-owned 0600 sk5.json used to
    raise out of every status poll). Report defaults plus a
    ``config_error`` field instead, so the panel can show the problem
    rather than a 500. Write paths (set_sk5/enable) still raise.
    """
    config_error = None
    try:
        cfg = _load_config()
    except (RuntimeError, ValueError) as exc:
        # ValueError is _load_config's strict stored-shape rejection
        # (R20-P2-1); a bad stored port/switch degrades to
        # config_error here exactly like an unreadable file, never a
        # 500 -- write paths (set_sk5/enable) still raise.
        cfg = _default_config()
        config_error = str(exc)
    status = _redact(cfg)
    if config_error:
        status["config_error"] = config_error
    status["singbox_running"] = _singbox_running()
    status["singbox_config"] = str(RENDERED_CONFIG) if _exists(RENDERED_CONFIG) else None
    status["policy_script"] = str(POLICY_SCRIPT)
    # Policy routing EFFECTIVE? See _policy_active() (R4-P2-1).
    status["policy_routing_active"] = _policy_active(cfg)
    status["vpn_net"] = VPN_NET
    status["egress_ip"] = current_egress_ip() if cfg.get("enabled") else None
    status["last_health"] = last_health()
    return status


def enable() -> dict:
    """Enable the SK5 chain for the stored config (raises if none).

    All-or-nothing (R24-P2-1 / BT): either the daemon is up, tun1
    is LIVE, and the policy is applied -- and only then is
    enabled=true persisted -- or the call raises loudly and changes
    no policy state. The old code waited ~5 s for tun1 to merely
    EXIST, then let policy-routing.sh build a dead placeholder
    (UP, NO-CARRIER) and install a linkdown route that carried
    nothing while _policy_active() reported True -- one slow or
    failed sing-box start plus one enable click wedged the chain
    until a human ran `ip link del tun1`. That writer is deleted:
    no path in this module or in policy-routing.sh creates tun1
    any more; sing-box alone owns the device.
      * a dead placeholder left by a pre-fix enable is cleared
        BEFORE starting the daemon (_remove_dead_tun1_placeholder:
        triple dead check + no sing-box holder), so one enable
        click recovers a wedged chain instead of needing manual
        deletion;
      * after starting sing-box, the wait is for a LIVE tun1
        (LOWER_UP), not mere existence. If none appears within
        5 s the call raises: no placeholder, no policy change,
        enabled stays False on disk -- the operator sees the 500
        and retries, instead of a fake 200 on a dead chain;
      * the policy is applied with the repair verb (blackhole +
        rule, tun1 route only when live), and the result is
        verified with _policy_active() before anything is
        persisted. If tun1 dies between the wait and the apply,
        the table is left blackhole-only (fail-closed) and the
        call still raises -- a half-enabled chain is never
        reported as success.
    """
    cfg = _load_config()
    if not cfg.get("host"):
        raise RuntimeError("no SK5 configured: call set_sk5() first")
    _validate(cfg["host"], int(cfg["port"]))
    _render_singbox_config(cfg)
    _remove_dead_tun1_placeholder()
    _start_singbox()
    # sing-box owns tun1; give it a moment to create the interface
    # AND bring it up (LOWER_UP). Mere existence is not enough: a
    # dead placeholder exists too, and routing via it installs a
    # linkdown route that carries nothing (R24-P2-1).
    # R32-P2-1: deadline loop, not `for _ in range(10)` with
    # check-then-sleep -- the old shape checked liveness only at
    # 0.0..4.5 s and raised at 5.0 s without ever checking at 5.0 s,
    # so a tun1 going live at 4.6..5.0 s was missed. This loop
    # checks at 0.0, 0.5, ..., 5.0 s (11 checks); the 5 s hard
    # cutoff is unchanged (DELIVERY.md:131, O-R25-2).
    deadline = time.monotonic() + 5.0
    while True:
        if _tun1_live():
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "sing-box did not create a live tun1 within 5 s "
                "(no placeholder was created; check that sing-box is "
                "running and its tun inbound is configured -- see "
                "sing-box.log); enable aborted, no policy state changed")
        time.sleep(0.5)
    _apply_policy(verb="repair")
    if not _policy_active({**cfg, "enabled": True}):
        raise RuntimeError(
            "policy routing did not come up after enable (tun1 route "
            "missing from table 100); table 100 is left on the "
            "fallback blackhole so VPN traffic is dropped, not "
            "leaked -- re-enable via the panel once sing-box is up")
    cfg["enabled"] = True
    _save_config(cfg)
    return get_status()


def disable() -> dict:
    """Explicitly turn the chain off: remove policy routing, then
    bring sing-box back up in direct mode.

    This is an operator decision, so VPN users fall back to direct
    egress from the transit server (main-table default route).
    The kill-switch is different: it applies to *unplanned* failure
    while enabled -- if sing-box / the SK5 dies, the fallback
    `blackhole default metric 200` route in table 100 (installed by
    enable(), R13-BUG-1) holds VPN traffic instead of letting it
    silently egress direct. The old wording here ("table 100 still
    points at the dead tun1") was the wrong model: the kernel
    deletes the device-bound tun1 route when tun1 dies, so without
    the blackhole an empty table would fall through to the main
    table. See check_health().

    R3-BUG-1: the old code stopped sing-box here and never started
    it again -- _start_singbox() was only called by enable(), so one
    "disable SK5" click left sing-box dead in direct mode with no
    panel path to revive it (and /api/status reported
    singbox_running=false). The installer invariant is "sing-box
    always up": disable re-renders the direct-mode config and
    restarts it, so tun1 stays up and VPN traffic egresses direct.
    (check_health()'s fail-open path calls disable() too, so a
    fail-over now also leaves a live direct-mode sing-box.)

    R4-P1-1: the restart is best-effort, never fatal. By the time
    _start_singbox() runs, policy routing is already removed and
    enabled=False is already on disk -- a daemon that cannot
    restart (no TUN, broken binary) must not turn a successful
    disable into a 500. The failure is reported honestly in the
    returned status instead (singbox_restart_error +
    singbox_restarted=false); get_status()'s singbox_running
    reflects the real (dead) state.
    """
    cfg = _load_config()
    # Render before stopping: if the template is missing we fail
    # before any state changes, instead of stopping sing-box and
    # then dying with no running process.
    _render_direct_config()
    _remove_policy()
    _stop_singbox()
    cfg["enabled"] = False
    _save_config(cfg)
    restart_error = None
    try:
        _start_singbox()
    except (RuntimeError, OSError) as exc:
        restart_error = str(exc)
    status = get_status()
    status["policy_removed"] = True
    status["config_saved"] = True
    if restart_error is not None:
        status["singbox_restart_error"] = restart_error
        status["singbox_restarted"] = False
    else:
        status["singbox_restarted"] = True
    return status


def _record_health(result: dict) -> None:
    """Persist the latest health result for get_status()/agent polls.

    Best-effort only (0600, atomic replace): a failure to write the
    history file must never break the health check itself.
    """
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        entry = dict(result)
        entry["checked_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _atomic_write_json(HEALTH_FILE, json.dumps(entry, indent=2) + "\n")
    except (OSError, RuntimeError):
        # Best-effort: _atomic_write_json raises RuntimeError (see
        # its docstring), which must be swallowed here like any
        # other write failure -- a broken history file must never
        # break the health check itself.
        pass


def last_health() -> dict | None:
    """Last recorded check_health() result, or None if never checked."""
    try:
        data = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def check_health() -> dict:
    """Health gate, driven by the systemd timer (60s, see
    systemd/openvpn-sk5-healthcheck.timer).

    Only meaningful while enabled. Healthy requires ALL of: the
    daemon is running, policy routing is actually applied, AND the
    TCP probe through the SK5 succeeds. (R6-P1-1: the old code only
    looked at the TCP probe, which dials the SOCKS directly and
    never traverses the policy route -- a missing policy still
    reported healthy=true, action=none, so the timer never failed
    over and never warned.) If unhealthy:
      * fail_open=True  -> disable() (restore direct egress). The
        recorded action matches what REALLY happened: disable()
        completed -> "failed_over_to_direct"; disable() raised
        before any state changed (template missing, config
        unwritable) -> "failover_failed" (R6-P2-1: the old code
        recorded failed_over_to_direct either way, while the
        policy was still in place and the disk still said
        enabled=true). A completed disable whose sing-box restart
        failed is still a real fail-over (policy gone, disk
        flipped) -- the restart failure stays in the detail.
      * fail_open=False -> policy applied: leave table 100 in
        place (the fallback blackhole route is the kill-switch),
        action="blackholed_kill_switch". Policy MISSING: this
        check first attempts ONE self-heal (_repair_policy(),
        R13-BUG-1 layer 2) and re-probes; a repaired chain is
        re-verdicted by the probe (healthy -> "policy_repaired",
        still dead -> "blackholed_kill_switch"). Only a failed
        repair lands "policy_missing", and its detail states
        exactly what VPN traffic is doing: with the rule present
        and the fallback blackhole in place, traffic is dropped
        (not leaked); if the rule itself is gone or the blackhole
        was never installed, traffic egresses direct.
        (R15-BUG-1: "repaired" is judged by the repair verb's
        own contract -- blackhole + rule in place
        (_repair_holding()) -- not by _policy_active(), which
        needs the tun1 route that only a live sing-box can
        provide. A blackhole-only table after a successful
        repair is still blackholed_kill_switch; _policy_active()
        stays the test for whether the chain can carry traffic.)
    Repair attempts are bounded by the timer itself (one per 60s
    tick, idempotent script, flock-serialized), so a permanently
    broken policy cannot turn into a repair storm; a crashing
    sing-box is separately start-limited by its unit (5 starts in
    120s, then failed). The repair deliberately lives here, not
    in an ExecStartPost on the sing-box unit: that unit also
    serves direct mode, where policy must NOT be installed.
    Every outcome is recorded to health.json so the panel / agent
    can show the last check without re-probing. Returns
    {"healthy","action","detail"}; never raises on probe error.
    """
    cfg = _load_config()
    if not cfg.get("enabled"):
        result = {"healthy": True, "action": "chain_disabled",
                  "detail": "not enabled"}
        _record_health(result)
        return result
    policy_ok = _policy_active(cfg)
    repaired = False
    repair_note = ""
    if not policy_ok:
        # R13-BUG-1 layer 2 (self-heal): a missing policy used to be
        # reported forever while VPN traffic silently egressed
        # direct (sing-box death deletes the device-bound tun1
        # route; the empty table falls through to main). Re-apply
        # once per check and re-verify -- _repair_policy() is
        # idempotent, and the 60s timer bounds the attempt rate.
        repaired, repair_note = _repair_policy()
        if repaired:
            policy_ok = _policy_active(cfg)
            if policy_ok:
                repair_note = "policy re-applied by health check"
            elif _repair_holding():
                # R15-BUG-1: the repair verb installs only the
                # blackhole + rule while sing-box is dead
                # (R14-BUG-1: it must never create tun1, so the
                # tun1 route cannot exist until the daemon
                # recreates the device). _policy_active() needs
                # that route, so it cannot turn true here --
                # judging the repair by it mislabels a
                # successful repair as failed ("did not stick").
                # The repair did everything its own contract
                # promises; keep repaired=True so the verdict
                # below lands blackholed_kill_switch, not
                # policy_missing. policy_ok stays False: the
                # chain still cannot carry traffic until
                # sing-box is back.
                repair_note = ("policy re-applied by health check "
                               "(blackhole + rule in place; tun1 "
                               "route waits for sing-box)")
            else:
                repaired = False
                repair_note = ("policy script exited 0 but the policy "
                               "still did not stick")
    if not _singbox_running():
        detail = "sing-box not running"
        healthy = False
    elif not policy_ok:
        # R6-P1-1: the chain cannot carry traffic without the
        # policy, whatever the SOCKS probe would say (it bypasses
        # the policy). Do not run test_sk5() here -- its tcp_ok
        # would only muddy a verdict that is already decided.
        detail = "policy routing not applied"
        healthy = False
    else:
        result = test_sk5()
        healthy = bool(result["tcp_ok"])
        detail = "tcp_ok=%s udp_ok=%s egress=%s" % (
            result["tcp_ok"], result["udp_ok"], result["egress_ip"])
        if repaired:
            detail += "; policy was missing, auto-repaired by this check"
    if healthy:
        result = {"healthy": True,
                  "action": "policy_repaired" if repaired else "none",
                  "detail": detail}
    elif cfg.get("fail_open"):
        # R4-P1-1: disable() must never make the timer come home
        # empty-handed. It reports a restart failure honestly
        # instead of raising -- but an earlier failure (template
        # missing, config unwritable) can still raise, and then
        # nothing was actually failed over (R6-P2-1).
        failover_ok = False
        failover_error = None
        try:
            dis = disable()
            if isinstance(dis, dict):
                failover_error = dis.get("singbox_restart_error")
            failover_ok = True
        except Exception as exc:  # noqa: BLE001
            failover_error = str(exc)
        if failover_ok:
            if failover_error:
                detail = (detail + "; fail-over restart failed: "
                          + failover_error)
            result = {"healthy": False, "action": "failed_over_to_direct",
                      "detail": detail}
        else:
            result = {"healthy": False, "action": "failover_failed",
                      "detail": detail + "; fail-over did not run: "
                      + str(failover_error)}
    elif not policy_ok:
        # R13-BUG-1: say exactly what VPN traffic is doing while the
        # policy is missing. The repair above was already attempted;
        # repair_note names its outcome. With the rule present and
        # the fallback blackhole in place, traffic is dropped --
        # held, not leaked. Without the rule, or without the
        # blackhole (pre-fix tree, flushed table), traffic
        # egresses direct: keep the dire wording for that case.
        holding = _repair_holding()
        if holding:
            traffic = ("VPN traffic is held by the fallback blackhole "
                       "route in table 100 (not egressing direct)")
        else:
            traffic = "VPN traffic egresses direct (not blackholed)"
        if repaired and holding:
            # R15-BUG-1: the repair succeeded -- blackhole + rule
            # are in place, measured just now -- but the chain is
            # still dead because sing-box is down (the tun1 route
            # waits for the daemon). Per the docstring that is
            # blackholed_kill_switch: the kill-switch is holding
            # traffic. policy_missing is reserved for a repair
            # that actually failed (script error, or blackhole /
            # rule missing at re-check) or a table with no
            # kill-switch at all.
            result = {"healthy": False, "action": "blackholed_kill_switch",
                      "detail": detail + "; policy routing is not applied, "
                      + traffic + "; auto-repair: " + repair_note}
        else:
            result = {"healthy": False, "action": "policy_missing",
                      "detail": detail + "; policy routing is not applied, "
                      + traffic + "; auto-repair: " + repair_note
                      + " (re-enable via the panel if this persists)"}
    else:
        result = {"healthy": False, "action": "blackholed_kill_switch",
                  "detail": detail}
    _record_health(result)
    return result


def set_fail_open(fail_open: bool) -> dict:
    """Switch kill-switch (False, default) <-> fail-open (True)."""
    cfg = _load_config()
    cfg["fail_open"] = bool(fail_open)
    _save_config(cfg)
    return get_status()


def set_udp_over_tcp(enabled: bool) -> dict:
    """Switch native UDP ASSOCIATE <-> udp_over_tcp encapsulation.

    Takes effect on the next enable()/set_sk5() (config re-render).
    R6-P2-2: a save that does not change the value must NOT restart
    the daemon -- the old code called enable() unconditionally
    whenever the chain was enabled, so every full-field save that
    merely carried udp_over_tcp (e.g. the panel's sk5_save, which
    always passes it through) cost one full restart on a healthy
    chain. A real value change still re-renders + restarts so the
    running chain picks the new encapsulation up.
    """
    cfg = _load_config()
    new_value = bool(enabled)
    if cfg.get("udp_over_tcp") == new_value:
        return get_status()
    cfg["udp_over_tcp"] = new_value
    _save_config(cfg)
    if cfg.get("enabled"):
        enable()
    return get_status()


# ---------------------------------------------------------------- CLI (for the panel backend / manual checks)

def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: sk5_manager.py {status|test|enable|disable|egress-ip|health}",
              file=sys.stderr)
        return 2
    cmd = argv[1]
    try:
        if cmd == "status":
            print(json.dumps(get_status(), indent=2, ensure_ascii=False))
        elif cmd == "test":
            print(json.dumps(test_sk5(), indent=2, ensure_ascii=False))
        elif cmd == "enable":
            print(json.dumps(enable(), indent=2, ensure_ascii=False))
        elif cmd == "disable":
            print(json.dumps(disable(), indent=2, ensure_ascii=False))
        elif cmd == "egress-ip":
            print(current_egress_ip() or "")
        elif cmd == "health":
            print(json.dumps(check_health(), indent=2, ensure_ascii=False))
        else:
            print(f"unknown command: {cmd}", file=sys.stderr)
            return 2
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))

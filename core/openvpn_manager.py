"""Lightweight OpenVPN manager (Pritunl-style model, no MongoDB).

Model: one CA (Easy-RSA) + one OpenVPN server daemon + one cert per
user. The manager shells out to ``easyrsa.sh`` (same directory) for all
PKI operations and to ``systemctl openvpn-server@server`` (with a direct
``openvpn --config`` fallback) for the daemon.

Only the standard library + ``subprocess`` is used. Target platform:
Debian 12 / Ubuntu 22.04 / 24.04, OpenVPN 2.6, Python 3.10+.

Layout (defaults, overridable with env vars)::

    /etc/openvpn/server/               OPENVPN_SERVER_DIR
        server.conf                    rendered from server.conf.template
        ca.crt  server.crt  server.key
        dh.pem  ta.key  crl.pem
        easy-rsa/                      OPENVPN_CA_DIR
            pki/
                ca.crt  dh.pem  ta.key  crl.pem  index.txt
                issued/<name>.crt  private/<name>.key

Module-level functions are the public API; :class:`OpenVPNManager`
exists for callers that want an instance with explicit paths.
"""

from __future__ import annotations

import base64
import fcntl
import ipaddress
import os
import re
import socket
import subprocess
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from string import Template

MODULE_DIR = Path(__file__).resolve().parent
EASYRSA_SH = MODULE_DIR / "easyrsa.sh"
SERVER_CONF_TEMPLATE = MODULE_DIR / "server.conf.template"
CLIENT_OVPN_TEMPLATE = MODULE_DIR / "client.ovpn.template"

DEFAULT_CA_DIR = Path(os.environ.get("OPENVPN_CA_DIR", "/etc/openvpn/server/easy-rsa"))
DEFAULT_SERVER_DIR = Path(os.environ.get("OPENVPN_SERVER_DIR", "/etc/openvpn/server"))
SERVER_UNIT = "openvpn-server@server"
SERVER_CONF_NAME = "server.conf"
PID_FILE = Path(os.environ.get("OPENVPN_PID_FILE", "/run/openvpn-server/server.pid"))
STATUS_LOG_CANDIDATES = (
    Path("/var/log/openvpn/openvpn-status.log"),
    Path("/run/openvpn-server/status-server.log"),
    Path("/run/openvpn-server/openvpn-status.log"),
    Path("/var/log/openvpn-status.log"),
)

# Names that may never be a username: they collide with the CA cert
# ("OpenVPN-CA", the CA's CN) or the server cert ("server"). A user
# called "server" would share issued/server.crt with the daemon, and
# one called "OpenVPN-CA" would be indistinguishable from the CA in
# index.txt (BUG-7). "ca" is reserved too: the CA cert file is
# pki/ca.crt, and filename-stem identification (R2-P1-3) would map a
# user called "ca" onto it. Enforced in validate_username() and in
# the index.txt filter below (defence in depth for pre-existing PKIs).
RESERVED_NAMES = frozenset({"server", "openvpn-ca", "ca"})

USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
DEFAULT_PROTO = os.environ.get("OPENVPN_PROTO", "udp")
DEFAULT_PORT = int(os.environ.get("OPENVPN_PORT", "1194"))
DEFAULT_DNS = os.environ.get("OVPN_DNS", "1.1.1.1")


class OpenVPNError(RuntimeError):
    """Raised for any expected OpenVPN/PKI failure (bad input, missing files,
    failing subprocess). Carries the failing command's output when known."""


class UserAlreadyExistsError(OpenVPNError):
    """create_user: *name* already holds a valid (non-legacy) cert.

    Subclassed (not a message match) so the panel can map this
    predictable client error to 409 instead of 500; the message text
    is unchanged, so agent-side generic handling is unaffected."""


class UserNotFoundError(OpenVPNError):
    """revoke_user: *name* holds no certificate at all (panel maps to 404)."""


class UserAlreadyRevokedError(OpenVPNError):
    """revoke_user: *name*'s certificate is already revoked (panel maps
    to 409 -- the resource exists but is in a state that forbids the
    operation)."""


def validate_username(name: str) -> str:
    """Validate a username. Returns the name unchanged.

    Rule: ``[a-zA-Z0-9_-]{1,32}``. Anything else is rejected because the
    name becomes a file name (``issued/<name>.crt``), a certificate CN and
    a status-log key -- path traversal / shell metacharacters must be
    impossible. ``server`` and ``OpenVPN-CA`` are reserved (BUG-7):
    they collide with the server cert and the CA cert.
    """
    if not isinstance(name, str) or not USERNAME_RE.match(name):
        raise OpenVPNError(
            "invalid username %r: must match [a-zA-Z0-9_-]{1,32}" % (name,)
        )
    if name.lower() in RESERVED_NAMES:
        raise OpenVPNError(
            "invalid username %r: %r is reserved (collides with the "
            "server/CA certificate)" % (name, name)
        )
    return name


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """Run *cmd*, raising :class:`OpenVPNError` (with stderr) on failure."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OpenVPNError("failed to run %s: %s" % (" ".join(cmd), exc)) from exc
    if proc.returncode != 0:
        raise OpenVPNError(
            "command failed (%s): %s" % (" ".join(cmd), (proc.stderr or proc.stdout or "").strip())
        )
    return proc


def _run_easyrsa(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    """Run ``easyrsa.sh <args>``. The script locates the easy-rsa binary."""
    if not EASYRSA_SH.is_file():
        raise OpenVPNError("easyrsa.sh not found at %s" % EASYRSA_SH)
    return _run(["bash", str(EASYRSA_SH), *args], timeout=timeout)


def _resolve_ca_dir(ca_dir: str | Path | None) -> Path:
    return Path(ca_dir) if ca_dir else DEFAULT_CA_DIR


def _resolve_server_dir(server_dir: str | Path | None) -> Path:
    return Path(server_dir) if server_dir else DEFAULT_SERVER_DIR


def _pki_dir(ca_dir: str | Path | None) -> Path:
    return _resolve_ca_dir(ca_dir) / "pki"


def _read_if_exists(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _exists(path: Path) -> bool:
    """OSError-tolerant existence check (same rule as egress
    ``_exists()`` in egress/sk5_manager.py -- re-implemented here
    rather than imported, so core stays standalone): ``Path.exists()``
    swallows only FileNotFoundError, so on an unreadable parent dir
    it raises PermissionError. A status call must never die on that
    (R5-P2-3) -- treat it as 'not there'."""
    try:
        return path.exists()
    except OSError:
        return False


# ---------------------------------------------------------------------------
# PKI
# ---------------------------------------------------------------------------

def init_pki(ca_dir: str | Path | None = None, force: bool = False) -> Path:
    """Initialise a fresh PKI and build the CA (``init-pki`` + ``build-ca nopass``).

    Returns the CA directory. Refuses to overwrite an existing CA unless
    ``force=True`` -- wiping a CA invalidates every issued client cert.
    With ``force=True`` the wipe is passed through to ``easyrsa.sh init
    --force`` (which removes the pki dir before re-running init-pki);
    without it the script still refuses when ca.crt exists.
    """
    ca_dir = _resolve_ca_dir(ca_dir)
    ca_crt = ca_dir / "pki" / "ca.crt"
    if ca_crt.exists() and not force:
        raise OpenVPNError(
            "CA already exists at %s (pass force=True to wipe it)" % ca_crt
        )
    args = ["init", str(ca_dir)]
    if force:
        args.append("--force")
    _run_easyrsa(*args)
    if not ca_crt.exists():
        raise OpenVPNError("init-pki/build-ca did not produce %s" % ca_crt)
    return ca_dir


def build_server_cert(
    ca_dir: str | Path | None = None,
    server_dir: str | Path | None = None,
) -> dict[str, str]:
    """Build the server cert/key, DH params and tls-auth key, then copy the
    server-side files into *server_dir*.

    Runs ``easyrsa.sh build-server`` (gen-req server, sign-req server,
    gen-dh, ta.key) and copies ``ca.crt / server.crt / server.key /
    dh.pem / ta.key`` plus ``crl.pem`` (empty CRL) into the server dir.
    Returns a dict of the installed paths.

    Idempotent (P1-10): when the full artifact set already exists the
    Easy-RSA run is skipped entirely -- re-running ``gen-req server``
    over an existing key is refused, and ``gen-dh`` would burn minutes
    for nothing. Only the CRL is refreshed in that case. A *partial*
    set (e.g. an interrupted first run left req/key but no issued
    cert) is cleared first, mirroring install.sh's stale cleanup, so
    build-server can run cleanly.
    """
    ca_dir = _resolve_ca_dir(ca_dir)
    server_dir = _resolve_server_dir(server_dir)
    pki = _pki_dir(ca_dir)
    artifacts = {
        "ca.crt": pki / "ca.crt",
        "server.crt": pki / "issued" / "server.crt",
        "server.key": pki / "private" / "server.key",
        "dh.pem": pki / "dh.pem",
        "ta.key": pki / "ta.key",
    }
    if all(p.exists() for p in artifacts.values()):
        if not (pki / "crl.pem").exists():
            _run_easyrsa("gen-crl", str(ca_dir))
    else:
        # Partial set blocks gen-req: drop the server pair (issued
        # cert / req / key) so build-server starts clean. A complete
        # set never reaches this branch and is never touched.
        for stale in (
            pki / "issued" / "server.crt",
            pki / "reqs" / "server.req",
            pki / "private" / "server.key",
        ):
            try:
                stale.unlink()
            except OSError:
                pass
        _run_easyrsa("build-server", str(ca_dir))
    server_dir.mkdir(parents=True, exist_ok=True)

    copies = {
        "ca.crt": pki / "ca.crt",
        "server.crt": pki / "issued" / "server.crt",
        "server.key": pki / "private" / "server.key",
        "dh.pem": pki / "dh.pem",
        "ta.key": pki / "ta.key",
        "crl.pem": pki / "crl.pem",
    }
    installed: dict[str, str] = {}
    for name, src in copies.items():
        if not src.exists():
            raise OpenVPNError("build-server did not produce %s" % src)
        dest = server_dir / name
        dest.write_bytes(src.read_bytes())
        dest.chmod(0o600 if name.endswith((".key", "ta.key")) else 0o644)
        installed[name] = str(dest)
    return installed


def _cert_serial_hex(cert_path: Path) -> str | None:
    """Serial number of a PEM certificate as uppercase hex (no ``0x``).

    Pure-stdlib DER read: Certificate ::= SEQUENCE { TBSCertificate,
    ... }, TBSCertificate ::= SEQUENCE { [0] version OPTIONAL,
    INTEGER serial, ... }. Returns None when the file is not a
    parseable certificate (stub/fake PKI, missing file, ...).
    """
    try:
        text = cert_path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return None
    b64 = "".join(
        ln.strip() for ln in text.splitlines()
        if ln.strip() and not ln.startswith("-----")
    )
    try:
        der = base64.b64decode(b64)
    except Exception:
        return None

    def _read_tlv(buf: bytes, pos: int) -> tuple[int, int, int]:
        tag = buf[pos]
        pos += 1
        length = buf[pos]
        pos += 1
        if length & 0x80:
            n = length & 0x7F
            length = int.from_bytes(buf[pos:pos + n], "big")
            pos += n
        return tag, length, pos

    try:
        tag, _length, pos = _read_tlv(der, 0)
        if tag != 0x30:
            return None
        tag, _length, pos = _read_tlv(der, pos)  # TBSCertificate
        if tag != 0x30:
            return None
        tag, length, pos = _read_tlv(der, pos)  # [0] version, or serial
        if tag == 0xA0:
            # v3 cert: skip the whole [0] element (it wraps the
            # version INTEGER); the serial is the NEXT TLV. Reading
            # a TLV *inside* the wrapper would return the version
            # number (2) as the serial.
            pos += length
            tag, length, pos = _read_tlv(der, pos)
        if tag != 0x02:
            return None
        serial = int.from_bytes(der[pos:pos + length], "big")
    except (IndexError, ValueError):
        return None
    hexs = format(serial, "X")
    if len(hexs) % 2:
        hexs = "0" + hexs
    return hexs


def _serial_to_name(pki: Path) -> dict[str, str]:
    """Serial (uppercase hex) -> username stem, from ``pki/issued/*.crt``.

    Ground truth for legacy certs: real ``openssl ca`` (what Easy-RSA
    uses to sign) writes the filename column of index.txt as the
    literal word ``unknown`` for every entry, so the filename cannot
    identify a user. The serial number can: each issued cert file
    carries the serial recorded in index.txt.
    """
    mapping: dict[str, str] = {}
    issued = pki / "issued"
    try:
        certs = sorted(issued.glob("*.crt"))
    except OSError:
        return mapping
    for cert in certs:
        stem = cert.stem
        if stem.lower() in RESERVED_NAMES:
            continue
        serial = _cert_serial_hex(cert)
        if serial:
            mapping[serial.upper()] = stem
    return mapping


def _index_expiry_is_past(expiry: str) -> bool:
    """True when an index.txt expiry (``YYMMDDHHMMSSZ``) is in the past.

    R9-P1-2: ``openssl ca`` only flips an expired ``V`` row to ``E``
    the next time it loads index.txt, which can be months after the
    certificate actually expired. Until then the row still says ``V``
    while OpenVPN already refuses the certificate, so the flag alone
    lies. The expiry is UTC (``Z``) and is compared against UTC now.
    A malformed or empty expiry returns False -- the flag stands and
    nothing raises.
    """
    expiry = (expiry or "").strip()
    if not expiry:
        return False
    try:
        when = datetime.strptime(expiry, "%y%m%d%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return False
    return when <= datetime.now(timezone.utc)


def _parse_index_txt(index_path: Path) -> list[dict]:
    """Parse Easy-RSA ``pki/index.txt``.

    Each line is TAB separated: ``status, expiry, revocation-date,
    serial, filename, subject-DN`` where the DN contains ``CN=<name>``.
    Status ``V`` = valid, ``R`` = revoked, ``E`` = expired.

    Returns one dict per user (CA/server entries filtered out):
    ``{name, status, expires, serial, cn, legacy}`` where ``cn`` is
    the subject CN and ``legacy`` is True when the cert's CN differs
    from the username (pre-BUG-7 certs, all signed with CN=OpenVPN-CA).

    Identity rules (R2-P1-3), in priority order: the name comes from
    the certificate filename when index.txt records a real one; from
    the serial number (matched against ``pki/issued/*.crt``) when the
    filename column is the literal ``unknown`` that real
    ``openssl ca`` writes for every entry; from the subject CN only
    as a last resort. Pre-BUG-7 certs all carry CN=OpenVPN-CA, so CN
    alone cannot identify them -- their entry is recognised by serial
    and flagged ``legacy``.

    BUG-4: the CA cert itself is an index.txt entry (``/CN=OpenVPN-CA``)
    and so is the server cert -- neither is a user. Both are skipped
    here, plus the ``unknown`` fallback name (a line with no CN at all
    would otherwise surface as a phantom user called "unknown").

    index.txt is append-only: when a name is re-issued after a revoke,
    both the old revoked entry and the new valid one are present; the
    LAST entry for a name wins (a stale revoked entry must not mask
    the live one).

    R9-P1-2: the reported ``status`` is the *effective* status, not
    the raw flag. A ``V`` row whose ``expires`` is already past is
    reported as ``expired`` -- ``openssl ca`` only flips such a row to
    ``E`` the next time it loads index.txt, so until then the raw flag
    would claim a dead certificate is valid (and ``create_user`` would
    409 on re-create). An ``E`` row already reports ``expired``; an
    ``R`` row is untouched by this rule.
    """
    users: list[dict] = []
    text = _read_if_exists(index_path)
    if text is None:
        return users
    serial_map = _serial_to_name(index_path.parent)
    by_name: dict[str, dict] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        status, expiry, _revoked, serial, filename, subject = parts[:6]
        match = re.search(r"CN=([^,/]+)", subject)
        cn = match.group(1) if match else None
        stem = ""
        if filename and filename != "unknown":
            stem = filename.rsplit("/", 1)[-1]
            if stem.endswith(".crt"):
                stem = stem[:-4]
        name = ""
        if stem and stem.lower() not in RESERVED_NAMES:
            name = stem
        elif serial.strip().upper() in serial_map:
            name = serial_map[serial.strip().upper()]
        elif cn and cn.lower() not in RESERVED_NAMES:
            name = cn
        if not name or name.lower() in RESERVED_NAMES or name == "unknown":
            continue  # CA cert / server cert / CN-less line: not a user
        flag = {"V": "valid", "R": "revoked", "E": "expired"}.get(
            status, status
        )
        # R9-P1-2: a V row whose expiry is past is effectively expired
        # even though openssl has not flipped the flag yet.
        if flag == "valid" and _index_expiry_is_past(expiry):
            flag = "expired"
        by_name[name] = {
            "name": name,
            "status": flag,
            "expires": expiry.strip(),
            "serial": serial.strip(),
            "cn": cn,
            "legacy": bool(cn) and cn != name,
        }
    users = sorted(by_name.values(), key=lambda u: u["name"])
    return users


def list_users(ca_dir: str | Path | None = None) -> list[dict]:
    """List all client certificates from ``pki/index.txt``.

    Returns ``[{name, status, expires, serial, cn, legacy}]`` sorted
    by name. ``status`` is one of ``valid`` / ``revoked`` /
    ``expired`` -- the *effective* status (R9-P1-2: a ``V`` row whose
    expiry is past reports ``expired``); ``legacy`` is True for
    pre-BUG-7 certs whose CN is ``OpenVPN-CA`` instead of the username
    (identified by serial). Returns ``[]`` when no PKI exists yet.
    """
    users = _parse_index_txt(_pki_dir(ca_dir) / "index.txt")
    return sorted(users, key=lambda u: u["name"])


def _user_entry(name: str, ca_dir: str | Path | None) -> dict | None:
    """The (single, latest) index.txt entry for *name*, or None."""
    for user in list_users(ca_dir):
        if user["name"] == name:
            return user
    return None


def _user_status(name: str, ca_dir: str | Path | None) -> str | None:
    """Current status of *name* in index.txt, or None if never issued.

    Uses the latest entry per name: after a revoke + re-create the
    index holds both an old revoked entry and a new valid one, and
    the first match would wrongly report the user as revoked.
    """
    entry = _user_entry(name, ca_dir)
    return entry["status"] if entry else None


# ---------------------------------------------------------------------------
# Client configs
# ---------------------------------------------------------------------------

PUBLIC_IP_SERVICES = (
    "https://api.ipify.org",
    "https://ifconfig.me",
)


def detect_public_ip(timeout: int = 5) -> str | None:
    """Ask an external service what IP the world sees for this host.

    Returns a public IPv4 address, or None when unreachable / the
    answer is not a public IP. Pure stdlib; each service gets one
    short attempt so a dead network fails fast instead of hanging a
    client-config render.
    """
    for url in PUBLIC_IP_SERVICES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ovpn/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                candidate = resp.read().decode("utf-8", "replace").strip()
            ip = ipaddress.ip_address(candidate)
            if isinstance(ip, ipaddress.IPv4Address) and not ip.is_private:
                return str(ip)
        except (ValueError, OSError, urllib.error.URLError):
            continue
    return None


def ip_is_private(ip: str | None) -> bool:
    """True when *ip* is a private / loopback / link-local address
    (i.e. useless as a ``remote`` for an off-site client)."""
    if not ip:
        return True
    try:
        addr = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return True  # unparsable: treat as unusable, caller warns
    return bool(
        addr.is_private or addr.is_loopback or addr.is_link_local
        or addr.is_reserved or addr.is_multicast
    )


def server_endpoint_info(
    server_dir: str | Path | None = None,
    server_ip: str | None = None,
    proto: str | None = None,
    port: int | None = None,
) -> dict:
    """Like :func:`_server_endpoint` but also reports where the IP came
    from: ``{ip, proto, port, ip_source, is_private}``. ``ip_source``
    is ``explicit`` / ``env`` / ``public-detect`` / ``lan-fallback`` /
    ``loopback``; callers show a warning when ``is_private`` is True
    (观察-1: a LAN remote makes the .ovpn unusable off-site)."""
    ip, proto, port = _server_endpoint(server_dir, server_ip, proto, port)
    if server_ip:
        source = "explicit"
    elif os.environ.get("OPENVPN_SERVER_IP"):
        source = "env"
    elif ip == "127.0.0.1":
        source = "loopback"
    else:
        source = "public-detect" if not ip_is_private(ip) else "lan-fallback"
    return {"ip": ip, "proto": proto, "port": port,
            "ip_source": source, "is_private": ip_is_private(ip)}


def _server_endpoint(
    server_dir: str | Path | None,
    server_ip: str | None,
    proto: str | None,
    port: int | None,
) -> tuple[str, str, int]:
    """Resolve (server_ip, proto, port) for a client config.

    proto/port are read from the rendered ``server.conf`` when present,
    otherwise from ``OPENVPN_PROTO`` / ``OPENVPN_PORT`` env or the
    ``udp/1194`` defaults. server_ip comes from the argument, the
    ``OPENVPN_SERVER_IP`` env var, a public-IP lookup, or -- last --
    the host's outward-facing address (UDP connect to 8.8.8.8 sends no
    traffic, it only picks a source IP). 观察-1: the old order put the
    LAN address first, so a NAT/cloud host rendered an unreachable
    ``remote <lan-ip>`` into every .ovpn; the public lookup now runs
    before the LAN fallback.
    """
    server_dir = _resolve_server_dir(server_dir)
    conf_proto, conf_port = None, None
    conf = _read_if_exists(server_dir / SERVER_CONF_NAME)
    if conf:
        for line in conf.splitlines():
            line = line.strip()
            if line.startswith("proto "):
                conf_proto = line.split(None, 1)[1].strip()
            elif line.startswith("port "):
                try:
                    conf_port = int(line.split(None, 1)[1].strip())
                except ValueError:
                    pass
    # R13-P2-2: resolve fallbacks with explicit None checks, not ``or``.
    # ``proto or conf_proto`` / ``port or conf_port`` silently replaced
    # an explicitly-passed falsy value ("" / 0 / False) with the conf or
    # default value before the strict guards below ever saw it. None
    # still means "unset" and falls through the chain.
    if proto is None:
        proto = conf_proto if conf_proto is not None else DEFAULT_PROTO
    # R12-P1-2: strict types before any coercion -- ``True`` is an
    # ``int`` subclass (``1 <= True <= 65535`` holds) and ``.lower()``
    # on a non-string raises AttributeError; both used to slip through
    # and poison the rendered ``.ovpn`` with a literal ``True`` port.
    if not isinstance(proto, str):
        raise OpenVPNError("proto must be 'udp' or 'tcp', got %r" % (proto,))
    proto = proto.lower()
    if proto not in ("udp", "tcp"):
        raise OpenVPNError("proto must be 'udp' or 'tcp', got %r" % proto)
    if port is None:
        port = conf_port if conf_port is not None else DEFAULT_PORT
    if type(port) is not int or not 1 <= port <= 65535:
        raise OpenVPNError("port must be an integer 1-65535, got %r" % (port,))

    ip = server_ip or os.environ.get("OPENVPN_SERVER_IP")
    if not ip:
        ip = detect_public_ip()
    if not ip:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.connect(("8.8.8.8", 80))
                ip = sock.getsockname()[0]
            finally:
                sock.close()
        except OSError:
            ip = "127.0.0.1"
    return ip, proto, port


def build_client_config(
    name: str,
    ca: str,
    cert: str,
    key: str,
    ta_key: str,
    server_ip: str,
    proto: str = "udp",
    port: int = 1194,
) -> str:
    """Render a client ``.ovpn`` from *client.ovpn.template* with the CA,
    cert, key and tls-auth key inlined. Pure function -- no disk/PKI use,
    so it is unit-testable with fixture PEM blocks.
    """
    validate_username(name)
    if proto not in ("udp", "tcp"):
        raise OpenVPNError("proto must be 'udp' or 'tcp', got %r" % proto)
    # R12-P1-2: ``port`` lands verbatim in the ``.ovpn`` template -- a
    # bool/float would render as a literal ``True``/``1194.0`` remote
    # port. ``type(port) is int`` excludes bool and every other type.
    if type(port) is not int or not 1 <= port <= 65535:
        raise OpenVPNError("port must be an integer 1-65535, got %r" % (port,))
    for label, blob in (("ca", ca), ("cert", cert), ("key", key), ("ta_key", ta_key)):
        if not blob or "-----BEGIN" not in blob:
            raise OpenVPNError("missing/invalid PEM block for %s" % label)
    template = CLIENT_OVPN_TEMPLATE.read_text(encoding="utf-8")
    return Template(template).substitute(
        SERVER_IP=server_ip,
        PROTO=proto,
        PORT=port,
        CA=ca.strip(),
        CERT=cert.strip(),
        KEY=key.strip(),
        TA=ta_key.strip(),
    )


@contextmanager
def _create_user_lock(pki: Path):
    """Exclusive advisory lock for :func:`create_user`'s check-then-build.

    R8-P2-3: two concurrent creates for one name both passed the
    duplicate check (``_user_status``) before either ran
    ``easyrsa build-client``, so both got 200 and index.txt kept two
    ``V`` records for one CN. The lock makes the whole sequence --
    sweep, duplicate check, stale-file cleanup, build -- one atomic
    step.

    Why flock in core and not a threading.Lock in the panel: the agent
    executes the same function from a *different process* (it polls
    the command queue and runs core directly), and a panel-side lock
    cannot serialise across processes. An flock on a file inside the
    PKI dir covers panel threads, the agent process, and any future
    caller. The lock file (``.create_user.lock``, 0600, created on
    demand) is inert: nothing enumerates the PKI root, and
    ``_serial_to_name`` only globs ``issued/*.crt``. The lock is
    released on process death (fd close), so a crashed holder cannot
    wedge creation forever. Blocking acquire is deliberate: a build
    takes seconds at most, and the waiter then re-checks against the
    finished state instead of racing it.
    """
    lock_path = pki / ".create_user.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _index_line_name(parts: list[str], serial_map: dict[str, str]) -> str:
    """Resolve one raw index.txt line to a user name, or "" if not a user.

    Mirrors the identity rules of :func:`_parse_index_txt` (filename
    stem, then serial -> issued cert stem, then subject CN) so the
    orphan sweep groups lines exactly the way the list/revoke paths
    see them. CA/server lines and malformed lines resolve to "" and
    are never touched.
    """
    if len(parts) < 6:
        return ""
    serial = parts[3].strip()
    filename = parts[4].strip()
    subject = parts[5]
    match = re.search(r"CN=([^,/]+)", subject)
    cn = match.group(1) if match else None
    stem = ""
    if filename and filename != "unknown":
        stem = filename.rsplit("/", 1)[-1]
        if stem.endswith(".crt"):
            stem = stem[:-4]
    name = ""
    if stem and stem.lower() not in RESERVED_NAMES:
        name = stem
    elif serial.upper() in serial_map:
        name = serial_map[serial.upper()]
    elif cn and cn.lower() not in RESERVED_NAMES:
        name = cn
    if not name or name.lower() in RESERVED_NAMES or name == "unknown":
        return ""
    return name


def _sweep_orphan_index_entries(pki: Path) -> int:
    """Delete dangling ``V`` records left by a raced duplicate create.

    R8-P2-3: when two creates for one name raced, the loser's
    certificate was overwritten by the winner's, but index.txt kept
    the loser's ``V`` line -- a serial with no key, no cert file, and
    no deliverable credential. Only a name with *more than one* ``V``
    entry is swept (a lone ``V`` line is never touched, whatever its
    state). Of the duplicates, the entry whose serial matches the
    serial inside ``issued/<name>.crt`` is kept; the rest are deleted.
    When the issued file is absent, every ``V`` entry for that name
    is an orphan and all are deleted, so the name can be re-created.
    When the issued file is present but unparsable, the name is left
    alone -- deleting on a guess could destroy the only record of a
    live credential.

    Why delete (not revoke, not report-only): the ghost serial never
    corresponded to a deliverable credential -- its cert/key files
    were overwritten before any ``.ovpn`` was rendered from them
    (the panel renders downloads from the on-disk files), so there is
    nothing to revoke: ``openssl ca -revoke`` needs the cert file,
    and hand-marking the line ``R`` would fabricate revocation state
    for a cert that never existed as a deliverable. Deleting removes
    invisible residue with zero security effect (the CRL only ever
    lists ``R`` entries, and a deleted ghost serial cannot be
    presented because no cert/key exists for it). ``R``/``E`` entries
    are never touched, and lines the parser skips (CA/server,
    malformed) are preserved byte-for-byte. The file is rewritten
    atomically (temp file + ``os.replace``, original mode preserved)
    and only when something actually changed.

    Returns the number of lines deleted. Callers must hold
    :func:`_create_user_lock` -- the sweep reads the same index.txt
    the duplicate check reads.
    """
    index = pki / "index.txt"
    try:
        raw = index.read_text(encoding="utf-8")
    except OSError:
        return 0
    lines = raw.splitlines()
    serial_map = _serial_to_name(pki)
    # group V entries by resolved user name
    groups: dict[str, list[int]] = {}
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        parts = line.split("\t")
        if not parts or parts[0] != "V":
            continue
        name = _index_line_name(parts, serial_map)
        if name:
            groups.setdefault(name, []).append(i)
    doomed: set[int] = set()
    for name, idxs in groups.items():
        if len(idxs) < 2:
            continue
        issued = pki / "issued" / ("%s.crt" % name)
        if not issued.is_file():
            # No credential file at all: every V line is an orphan.
            doomed.update(idxs)
            continue
        keeper = _cert_serial_hex(issued)
        if keeper is None:
            continue  # unparsable cert: leave the name alone
        keeper_norm = format(int(keeper, 16), "X")
        for i in idxs:
            serial = lines[i].split("\t")[3].strip()
            try:
                serial_norm = format(int(serial, 16), "X")
            except ValueError:
                continue  # unparsable serial: keep the line
            if serial_norm != keeper_norm:
                doomed.add(i)
    if not doomed:
        return 0
    kept = [ln for i, ln in enumerate(lines) if i not in doomed]
    tmp = index.with_name("index.txt.tmp")
    tmp.write_text("\n".join(kept) + ("\n" if kept else ""),
                   encoding="utf-8")
    try:
        os.chmod(tmp, index.stat().st_mode)
    except OSError:
        pass
    os.replace(tmp, index)
    return len(doomed)


def create_user(
    name: str,
    ca_dir: str | Path | None = None,
    server_dir: str | Path | None = None,
    server_ip: str | None = None,
    proto: str | None = None,
    port: int | None = None,
) -> str:
    """Create a client certificate for *name* and return the ``.ovpn`` text.

    Raises :class:`OpenVPNError` on an invalid name, a duplicate valid
    cert, or a missing CA. A previously *revoked* or *expired* name
    may be re-created: its stale issued/req/private files are removed
    first so Easy-RSA can re-issue. (R9-P1-2: "expired" includes a
    ``V`` row whose expiry is already past -- see
    :func:`_parse_index_txt`.)

    R2-P1-3 migration: a *valid* pre-BUG-7 cert (CN=OpenVPN-CA, flagged
    ``legacy``) is revoked first and then re-issued with the correct CN
    -- the user keeps the name and gets a fresh .ovpn; the old cert
    stops working for new connections after ``restart_server()``.

    R8-P2-3: the duplicate check and the build are serialised by an
    exclusive flock on the PKI dir (see :func:`_create_user_lock`),
    so two concurrent creates for one name cannot both succeed; a
    sweep inside the lock deletes dangling ``V`` records left by an
    earlier race (see :func:`_sweep_orphan_index_entries`).
    """
    validate_username(name)
    ca_dir = _resolve_ca_dir(ca_dir)
    server_dir = _resolve_server_dir(server_dir)
    pki = _pki_dir(ca_dir)
    if not (pki / "ca.crt").exists():
        raise OpenVPNError("no CA at %s -- run init_pki() first" % pki)

    # R8-P2-3: sweep + duplicate check + stale cleanup + build must be
    # one atomic step under _create_user_lock. The post-build file
    # reads and the .ovpn render stay outside the lock: after the
    # build, this name's V line exists, so a later create for the
    # same name hits 409 before touching any file, and the render
    # only reads this name's own files.
    pki.mkdir(parents=True, exist_ok=True)
    with _create_user_lock(pki):
        _sweep_orphan_index_entries(pki)
        status = _user_status(name, ca_dir)
        if status == "valid":
            entry = _user_entry(name, ca_dir)
            if entry is not None and entry.get("legacy"):
                _revoke_cert(name, ca_dir, server_dir)
                status = "revoked"
            else:
                raise UserAlreadyExistsError(
                    "user %r already exists (valid cert)" % name
                )
        if status in ("revoked", "expired"):
            for stale in (
                pki / "issued" / ("%s.crt" % name),
                pki / "reqs" / ("%s.req" % name),
                pki / "private" / ("%s.key" % name),
            ):
                try:
                    stale.unlink()
                except OSError:
                    pass

        _run_easyrsa("build-client", str(ca_dir), name)

    ca = _read_if_exists(pki / "ca.crt")
    cert = _read_if_exists(pki / "issued" / ("%s.crt" % name))
    key = _read_if_exists(pki / "private" / ("%s.key" % name))
    ta_key = _read_if_exists(server_dir / "ta.key") or _read_if_exists(pki / "ta.key")
    if not (ca and cert and key and ta_key):
        raise OpenVPNError("create-user did not produce all files for %r" % name)
    ip, resolved_proto, resolved_port = _server_endpoint(server_dir, server_ip, proto, port)
    return build_client_config(name, ca, cert, key, ta_key, ip, resolved_proto, resolved_port)


def _revoke_cert(
    name: str,
    ca_dir: str | Path,
    server_dir: str | Path,
) -> dict:
    """Run ``easyrsa.sh revoke`` (revoke + gen-crl) and sync the CRL to
    the server dir. Shared core for :func:`revoke_user` and the
    legacy-CN migration in :func:`create_user` (a pre-BUG-7 cert is
    revoked before it is re-issued with a correct CN). Returns
    ``{name, status, crl}``."""
    pki = _pki_dir(ca_dir)
    _run_easyrsa("revoke", str(ca_dir), name)
    crl_src = pki / "crl.pem"
    if not crl_src.exists():
        raise OpenVPNError("revoke did not produce %s" % crl_src)
    dest = Path(server_dir) / "crl.pem"
    dest.write_bytes(crl_src.read_bytes())
    dest.chmod(0o644)
    return {"name": name, "status": "revoked", "crl": str(dest)}


def revoke_user(
    name: str,
    ca_dir: str | Path | None = None,
    server_dir: str | Path | None = None,
) -> dict:
    """Revoke *name*'s certificate and regenerate the CRL.

    Runs ``easyrsa.sh revoke`` (revoke + gen-crl) and copies the new
    ``crl.pem`` into the server dir. Returns ``{name, status, crl}``.

    NOTE: OpenVPN reads the CRL at daemon start, so the revocation only
    takes effect for *new* connections after ``restart_server()`` (an
    already-connected client is not kicked by a CRL refresh alone).

    R9-P1-2: an *expired* certificate can still be revoked through
    this path -- real ``openssl ca -revoke`` accepts an already-expired
    cert (verified against OpenSSL 3.0.13, rc=0), so no special case
    is needed; the CRL entry is harmless and OpenVPN already rejects
    the cert on expiry alone.
    """
    validate_username(name)
    ca_dir = _resolve_ca_dir(ca_dir)
    server_dir = _resolve_server_dir(server_dir)
    status = _user_status(name, ca_dir)
    if status is None:
        raise UserNotFoundError("user %r does not exist" % name)
    if status == "revoked":
        raise UserAlreadyRevokedError("user %r is already revoked" % name)
    return _revoke_cert(name, ca_dir, server_dir)


# ---------------------------------------------------------------------------
# Server config + daemon
# ---------------------------------------------------------------------------

def _validate_dns(dns: str | None) -> str:
    """Validate the pushed DNS server (P2-6): a bare IP/hostname, no
    whitespace or shell metacharacters (it lands verbatim in server.conf).

    R12-P1-2 (core side): a non-string value must not be silently
    coerced -- ``str(True)`` would push the literal hostname ``True``.
    Only real strings (or None for "use the default") are accepted.
    """
    if dns is not None and not isinstance(dns, str):
        raise OpenVPNError("invalid DNS server %r" % (dns,))
    dns = str(dns or "").strip()
    if not dns or any(c in dns for c in " \t\"';&|<>$`\\"):
        raise OpenVPNError("invalid DNS server %r" % dns)
    return dns


def _port_occupant(proto: str, port: int) -> str | None:
    """Name the holder of ``proto``/``port``, or None if the port is free.

    Detection is a plain ``bind()`` (no SO_REUSEADDR): it fails exactly
    when something already listens. ``ss`` output is only used to name
    the occupant for the error message; a missing ``ss`` still detects
    occupancy, it just cannot name the holder.
    """
    kind = socket.SOCK_STREAM if proto == "tcp" else socket.SOCK_DGRAM
    try:
        sock = socket.socket(socket.AF_INET, kind)
        try:
            sock.bind(("0.0.0.0", port))
        finally:
            sock.close()
    except OSError:
        holder = None
        try:
            flag = "-tlnp" if proto == "tcp" else "-ulnp"
            proc = subprocess.run(
                ["ss", flag], capture_output=True, text=True, timeout=10
            )
            for line in (proc.stdout or "").splitlines():
                if (":%d" % port) in line:
                    holder = line.strip()
                    break
        except (OSError, subprocess.TimeoutExpired):
            holder = None
        return holder or "another process (ss unavailable, cannot name it)"
    return None


def _parse_existing_server_conf(text: str) -> tuple[str | None, int | None, str | None]:
    """Parse proto/port out of an existing server.conf.

    Returns ``(proto, port, damage)`` where ``damage`` is None when the
    conf parsed cleanly, else a human-readable reason: an unparseable
    ``proto``/``port`` value, or a missing ``proto``/``port`` line in a
    non-empty conf. R12-P1-2: the old code swallowed the ``int()``
    ValueError and left ``old_port`` as None, so ``(udp, None) !=
    (udp, 1194)`` froze every later render -- one poisoned conf locked
    the entry port forever. Callers must treat a damaged conf as
    damaged (explicit error + recovery), never as "old port None".
    """
    old_proto, old_port, damage = None, None, None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("proto "):
            raw = line.split(None, 1)[1].strip().lower()
            if raw in ("udp", "tcp"):
                old_proto = raw
            elif damage is None:
                damage = "unparseable proto value %r" % raw
        elif line.startswith("port "):
            raw = line.split(None, 1)[1].strip()
            try:
                old_port = int(raw)
            except ValueError:
                if damage is None:
                    damage = "unparseable port value %r" % raw
    if damage is None:
        missing = [f for f, v in (("proto", old_proto), ("port", old_port))
                   if v is None]
        if missing:
            damage = "missing %s line(s)" % " and ".join(missing)
    return old_proto, old_port, damage


def render_server_conf(
    proto: str = "udp",
    port: int | None = None,
    server_dir: str | Path | None = None,
    ca_dir: str | Path | None = None,
    dns: str | None = None,
    allow_port_change: bool = False,
) -> Path:
    """Render ``server.conf.template`` to ``<server_dir>/server.conf``.

    ``proto`` is ``udp`` (port 1194) or ``tcp`` (port 443 by default);
    ``dns`` is the pushed DNS server (default: ``$OVPN_DNS`` or
    ``1.1.1.1``). Returns the written path.

    P1-11 (FLMX P01): the entry port is checked against live occupancy
    *before* rendering, and once a server.conf exists its proto/port
    are fixed -- a different proto/port is refused unless
    ``allow_port_change`` is explicitly passed (deleting server.conf
    and re-creating is the deliberate way to move the entry port).
    Re-rendering the *same* proto/port skips the occupancy check: the
    port is ours (the running daemon holds it).
    """
    # R12-P1-2: strict types before any coercion. ``bool`` is an
    # ``int`` subclass, so ``port=True`` used to pass ``1 <= True <=
    # 65535`` and ``Template.substitute(PORT=True)`` wrote the literal
    # line ``port True`` into server.conf; a float/string port slipped
    # through the same way (or raised a bare TypeError). Only real
    # ints 1-65535 are accepted; ``allow_port_change`` must be a real
    # bool -- a truthy string must never silently authorise a move.
    if type(allow_port_change) is not bool:
        raise OpenVPNError(
            "allow_port_change must be a boolean, got %r" % (allow_port_change,))
    if not isinstance(proto, str):
        raise OpenVPNError("proto must be 'udp' or 'tcp', got %r" % (proto,))
    proto = proto.lower()
    if proto not in ("udp", "tcp"):
        raise OpenVPNError("proto must be 'udp' or 'tcp', got %r" % proto)
    # R13-P2-2: resolve the default with an explicit None check, not
    # ``port or default``. The ``or`` merge ran before the strict type
    # guard below, so falsy values (0, False) were silently replaced
    # with the default port and rendered as if nothing was wrong.
    # None still means "unset" and takes the default.
    if port is None:
        port = 1194 if proto == "udp" else 443
    if type(port) is not int or not 1 <= port <= 65535:
        raise OpenVPNError("port must be an integer 1-65535, got %r" % (port,))
    # R14-P2-2: resolve the default with an explicit None check, not
    # ``dns or default``. The ``or`` merge ran before the strict guard
    # in _validate_dns, so falsy values (False, 0, "") were silently
    # replaced with the default DNS and rendered as if nothing was
    # wrong. None still means "unset" and takes $OVPN_DNS / default;
    # an empty $OVPN_DNS likewise means "not configured".
    if dns is None:
        dns = os.environ.get("OVPN_DNS") or DEFAULT_DNS
    dns = _validate_dns(dns)
    server_dir = _resolve_server_dir(server_dir)
    _resolve_ca_dir(ca_dir)  # validated for symmetry; paths in conf are absolute
    conf_path = server_dir / SERVER_CONF_NAME
    existing = _read_if_exists(conf_path)
    if existing:
        old_proto, old_port, damage = _parse_existing_server_conf(existing)
        if damage is not None:
            # R12-P1-2: the old conf is damaged -- the entry-port freeze
            # cannot be evaluated (the old port is unknown, not
            # None-as-a-port). Say so explicitly and name the recovery:
            # delete the file and re-create, or re-render with
            # allow_port_change=True (occupancy is still checked).
            # Never fall through to the P01 comparison: (udp, None)
            # != (udp, 1194) would freeze every later render.
            if not allow_port_change:
                raise OpenVPNError(
                    "existing server.conf is damaged (%s) in %s: entry-port "
                    "check cannot be evaluated -- delete %s and re-create, "
                    "or re-render with allow_port_change=True"
                    % (damage, conf_path, conf_path)
                )
            occupant = _port_occupant(proto, port)
            if occupant is not None:
                raise OpenVPNError(
                    "cannot move entry port to %s/%d: already in use by %s"
                    % (proto, port, occupant)
                )
        elif (old_proto, old_port) != (proto, port):
            if not allow_port_change:
                raise OpenVPNError(
                    "entry port is fixed at creation (FLMX P01): server.conf "
                    "already uses %s/%s, refusing to change to %s/%s "
                    "(delete %s and re-create to move the entry port, "
                    "or pass allow_port_change=True)"
                    % (old_proto, old_port, proto, port, conf_path)
                )
            occupant = _port_occupant(proto, port)
            if occupant is not None:
                raise OpenVPNError(
                    "cannot move entry port to %s/%d: already in use by %s"
                    % (proto, port, occupant)
                )
    else:
        occupant = _port_occupant(proto, port)
        if occupant is not None:
            raise OpenVPNError(
                "port %d/%s is already in use by: %s "
                "(pick a free port; the entry port is fixed once created)"
                % (port, proto, occupant)
            )
    template = SERVER_CONF_TEMPLATE.read_text(encoding="utf-8")
    rendered = Template(template).substitute(
        PROTO=proto, PORT=port, SERVER_DIR=str(server_dir), DNS=dns
    )
    server_dir.mkdir(parents=True, exist_ok=True)
    conf_path.write_text(rendered, encoding="utf-8")
    conf_path.chmod(0o644)
    return conf_path


def _v2_client_row(parts: list[str], col: dict[str, int] | None) -> dict | None:
    """Map one v2 ``CLIENT_LIST`` row to a client dict.

    Separator-agnostic: ``parts`` may come from a TAB-separated row
    (management-interface shape) or a comma-separated row (status
    file -- the deployed shape, R2-BUG-13). With a ``HEADER
    CLIENT_LIST`` line seen, columns are mapped by field name, so a
    missing or extra column cannot shift the fields. Without a
    header, positional fallback: 13 parts = 12 fields (incl. the
    empty Virtual IPv6 Address column), 12 parts = the pre-IPv6
    11-field shape. Returns None for an unrecognisable row.
    """
    if col is not None:
        def get(name: str) -> str:
            idx = col.get(name)
            return parts[idx] if idx is not None and idx < len(parts) else ""
        row = {
            "name": get("Common Name"),
            "real_address": get("Real Address"),
            "virtual_address": get("Virtual Address"),
            "bytes_received": get("Bytes Received"),
            "bytes_sent": get("Bytes Sent"),
            "connected_since": get("Connected Since"),
        }
    elif len(parts) >= 13:
        row = {
            "name": parts[1],
            "real_address": parts[2],
            "virtual_address": parts[3],
            "bytes_received": parts[5],
            "bytes_sent": parts[6],
            "connected_since": parts[7],
        }
    elif len(parts) == 12:
        row = {
            "name": parts[1],
            "real_address": parts[2],
            "virtual_address": parts[3],
            "bytes_received": parts[4],
            "bytes_sent": parts[5],
            "connected_since": parts[6],
        }
    else:
        return None
    return row if row["name"] else None


def _parse_status_log(log_path: Path) -> list[dict]:
    """Parse an OpenVPN status log into connected clients.

    FIXTURE RULE (R2-BUG-13, third BUG-9 fix -- do not re-break it):
    an OpenVPN *status file* is ALWAYS comma-separated. v1 and v2
    differ in columns and section headers, NOT in separator. TAB
    separation exists only in management-interface output, never in
    a status file. Two audit rounds and two fix rounds all modelled
    v2 as TAB; the deployed Debian unit passes ``--status-version 2``
    while the config's ``status`` line still sets the path, so the
    file the panel actually reads is comma-separated v2 -- and the
    old parser dropped every one of its 13-field rows, leaving
    ``online_users`` at 0 with a client connected. Regression
    fixtures must use the verbatim deployed lines (see
    ``core/tests/test_status_log.py``), never a re-typed shape.

    Accepted shapes (all four must keep passing):
    * comma v2 (deployed): ``HEADER,CLIENT_LIST,...`` declares the
      columns; ``CLIENT_LIST,<12 fields>`` rows (incl. an empty
      Virtual IPv6 Address column); ``ROUTING_TABLE,<vaddr>,<CN>,...``.
    * bare v1: ``OpenVPN CLIENT LIST`` section with bare 5-field
      rows (``Common Name,Real Address,Bytes Received,Bytes Sent,
      Connected Since`` -- NO virtual-address column); the virtual
      address is backfilled from the ``ROUTING TABLE`` section,
      keyed by CN.
    * TAB v2 (management-interface shape): ``HEADER\tCLIENT_LIST``
      + ``CLIENT_LIST\t`` rows, same column mapping.
    * prefixed 7-field form: ``CLIENT_LIST,CN,real,virtual,rx,tx,
      since`` (6 fields after the prefix) and a 6-field v1 row
      carrying a virtual address.

    Returns ``[{name, real_address, virtual_address, bytes_received,
    bytes_sent, connected_since}]``; ``virtual_address`` is ``""``
    when the log carries no routing row for the client.
    """
    clients: list[dict] = []
    routing: dict[str, str] = {}
    text = _read_if_exists(log_path)
    if text is None:
        return clients
    col: dict[str, int] | None = None  # v2 field name -> data-row index
    section: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if line.startswith("HEADER\t") or line.startswith("HEADER,"):
            parts = line.split("\t") if "\t" in line else line.split(",")
            if len(parts) >= 3 and parts[1] == "CLIENT_LIST":
                # Header index i (>= 2) is data-row index i - 1.
                col = {name: i - 1 for i, name in enumerate(parts) if i >= 2}
            continue
        if line.startswith("CLIENT_LIST\t") or line.startswith("CLIENT_LIST,"):
            parts = line.split("\t") if "\t" in line else line.split(",")
            if len(parts) == 7:
                clients.append(
                    {
                        "name": parts[1],
                        "real_address": parts[2],
                        "virtual_address": parts[3],
                        "bytes_received": parts[4],
                        "bytes_sent": parts[5],
                        "connected_since": parts[6],
                    }
                )
            elif col is not None or len(parts) >= 12:
                row = _v2_client_row(parts, col)
                if row is not None:
                    clients.append(row)
            continue
        if line.startswith("ROUTING_TABLE\t") or line.startswith("ROUTING_TABLE,"):
            parts = line.split("\t") if "\t" in line else line.split(",")
            if len(parts) >= 3 and parts[1]:
                routing[parts[2]] = parts[1]
            continue
        if line == "OpenVPN CLIENT LIST":
            section = "clients"
            continue
        if line == "ROUTING TABLE":
            section = "routing"
            continue
        if line == "END" or line.startswith("GLOBAL STATS"):
            section = None
            continue
        if "," in line and section in ("clients", "routing"):
            parts = line.split(",")
            if section == "clients":
                if parts[0] in ("Common Name", "Updated"):
                    continue
                if len(parts) == 5:
                    clients.append(
                        {
                            "name": parts[0],
                            "real_address": parts[1],
                            "virtual_address": "",
                            "bytes_received": parts[2],
                            "bytes_sent": parts[3],
                            "connected_since": parts[4],
                        }
                    )
                elif len(parts) == 6:
                    # Tolerant variant: some builds include the
                    # virtual address column in v1 rows.
                    clients.append(
                        {
                            "name": parts[0],
                            "real_address": parts[1],
                            "virtual_address": parts[2],
                            "bytes_received": parts[3],
                            "bytes_sent": parts[4],
                            "connected_since": parts[5],
                        }
                    )
            else:
                if parts[0] == "Virtual Address":
                    continue
                if len(parts) >= 2 and parts[1]:
                    routing[parts[1]] = parts[0]
            continue
    for client in clients:
        if not client["virtual_address"]:
            client["virtual_address"] = routing.get(client["name"], "")
    return clients


def server_status(server_dir: str | Path | None = None) -> dict:
    """Report the server daemon state.

    Returns ``{running, unit_active, pid, clients, status_log}``.
    ``running`` is True when ``systemctl is-active`` succeeds, or -- when
    systemd is unavailable -- when the PID file points at a live process.
    Never raises for a stopped/missing daemon; the ``error`` key carries
    the reason instead.
    """
    server_dir = _resolve_server_dir(server_dir)
    result: dict = {
        "running": False,
        "unit_active": False,
        "pid": None,
        "clients": [],
        "status_log": None,
        "error": None,
    }
    # P1-13: systemctl must never raise out of a status call (no
    # binary on a container host) and must never hang it either.
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", "--quiet", SERVER_UNIT],
            capture_output=True, timeout=10,
        )
        result["unit_active"] = proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        result["unit_active"] = False

    pid = None
    # R5-P2-3: bare Path.exists() raises PermissionError on an unreadable
    # parent dir (Python 3.12 swallows only FileNotFoundError) -- use the
    # OSError-tolerant check so server_status() never raises here.
    if _exists(PID_FILE):
        try:
            pid = int(PID_FILE.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)  # raises ProcessLookupError if dead
            result["pid"] = pid
        except (ValueError, OSError):
            pid = None
    if pid is None and result["unit_active"]:
        # 观察-2: the Debian openvpn-server@ unit runs Type=notify and
        # writes no PID file, so pid was null even while running. Ask
        # systemd for the unit's MainPID instead.
        try:
            proc = subprocess.run(
                ["systemctl", "show", "-p", "MainPID", "--value", SERVER_UNIT],
                capture_output=True, text=True, timeout=10,
            )
            main_pid = int((proc.stdout or "").strip())
            if main_pid > 0:
                os.kill(main_pid, 0)
                result["pid"] = main_pid
                pid = main_pid
        except (ValueError, OSError, subprocess.TimeoutExpired):
            pass
    result["running"] = bool(result["unit_active"] or pid is not None)
    if not result["running"]:
        result["error"] = "openvpn-server@server is not running"
        return result

    for candidate in STATUS_LOG_CANDIDATES:
        # R5-P2-3: same bare-exists() trap as the PID file above.
        if _exists(candidate):
            result["status_log"] = str(candidate)
            result["clients"] = _parse_status_log(candidate)
            break
    return result


def _systemctl(action: str) -> bool:
    """Run ``systemctl <action> openvpn-server@server``; False if systemd
    is missing, hangs, or the command fails (caller falls back to
    direct mode). Never raises (P1-13)."""
    try:
        proc = subprocess.run(
            ["systemctl", action, SERVER_UNIT],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def start_server(server_dir: str | Path | None = None) -> dict:
    """Start the daemon. Prefers systemd; falls back to a direct
    ``openvpn --config ... --daemon`` launch when systemd is unavailable.
    Raises :class:`OpenVPNError` if no ``server.conf`` exists or the
    daemon fails to come up. Returns :func:`server_status`.
    """
    server_dir = _resolve_server_dir(server_dir)
    conf = server_dir / SERVER_CONF_NAME
    if not conf.exists():
        raise OpenVPNError(
            "no %s -- run render_server_conf() and build_server_cert() first" % conf
        )
    if _systemctl("start"):
        status = server_status(server_dir)
        if status["running"]:
            return status
    # Direct fallback (containers / no systemd): daemonise openvpn itself.
    log = Path("/var/log/openvpn/openvpn.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "openvpn",
            "--config", str(conf),
            "--daemon",
            "--writepid", str(PID_FILE),
            "--log-append", str(log),
        ],
        timeout=60,
    )
    status = server_status(server_dir)
    if not status["running"]:
        raise OpenVPNError("openvpn daemon failed to start; see %s" % log)
    return status


def stop_server(server_dir: str | Path | None = None) -> dict:
    """Stop the daemon (systemd, else SIGTERM to the PID file). Idempotent:
    stopping an already-stopped server succeeds. Returns server_status()."""
    server_dir = _resolve_server_dir(server_dir)
    if _systemctl("stop"):
        return server_status(server_dir)
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text(encoding="utf-8").strip())
            os.kill(pid, 15)
        except (ValueError, ProcessLookupError, OSError):
            pass
        try:
            PID_FILE.unlink()
        except OSError:
            pass
    return server_status(server_dir)


def restart_server(server_dir: str | Path | None = None) -> dict:
    """Restart the daemon. Required after revoking a user (CRL reload) and
    after changing server.conf. Returns server_status()."""
    server_dir = _resolve_server_dir(server_dir)
    if _systemctl("restart"):
        status = server_status(server_dir)
        if status["running"]:
            return status
    stop_server(server_dir)
    return start_server(server_dir)


@dataclass
class OpenVPNManager:
    """Instance wrapper around the module functions for callers that want
    explicit paths instead of env-var defaults."""

    ca_dir: Path = DEFAULT_CA_DIR
    server_dir: Path = DEFAULT_SERVER_DIR

    def init_pki(self, force: bool = False) -> Path:
        return init_pki(self.ca_dir, force=force)

    def build_server_cert(self) -> dict[str, str]:
        return build_server_cert(self.ca_dir, self.server_dir)

    def render_server_conf(
        self, proto: str = "udp", port: int | None = None,
        dns: str | None = None, allow_port_change: bool = False,
    ) -> Path:
        return render_server_conf(
            proto, port, self.server_dir, self.ca_dir,
            dns=dns, allow_port_change=allow_port_change)

    def create_user(self, name: str, **kwargs) -> str:
        return create_user(name, self.ca_dir, self.server_dir, **kwargs)

    def server_endpoint_info(self, **kwargs) -> dict:
        return server_endpoint_info(self.server_dir, **kwargs)

    def revoke_user(self, name: str) -> dict:
        return revoke_user(name, self.ca_dir, self.server_dir)

    def list_users(self) -> list[dict]:
        return list_users(self.ca_dir)

    def server_status(self) -> dict:
        return server_status(self.server_dir)

    def start_server(self) -> dict:
        return start_server(self.server_dir)

    def stop_server(self) -> dict:
        return stop_server(self.server_dir)

    def restart_server(self) -> dict:
        return restart_server(self.server_dir)


if __name__ == "__main__":
    import json
    import sys

    # Tiny CLI for smoke tests: python3 -m core.openvpn_manager <cmd> [args]
    #   status | list | create <name> | revoke <name> | start | stop | restart
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    mgr = OpenVPNManager()
    if cmd == "status":
        print(json.dumps(mgr.server_status(), indent=2, ensure_ascii=False))
    elif cmd == "list":
        print(json.dumps(mgr.list_users(), indent=2, ensure_ascii=False))
    elif cmd == "create" and len(sys.argv) > 2:
        print(mgr.create_user(sys.argv[2]))
    elif cmd == "revoke" and len(sys.argv) > 2:
        print(json.dumps(mgr.revoke_user(sys.argv[2]), indent=2, ensure_ascii=False))
    elif cmd == "start":
        print(json.dumps(mgr.start_server(), indent=2, ensure_ascii=False))
    elif cmd == "stop":
        print(json.dumps(mgr.stop_server(), indent=2, ensure_ascii=False))
    elif cmd == "restart":
        print(json.dumps(mgr.restart_server(), indent=2, ensure_ascii=False))
    else:
        raise SystemExit("usage: openvpn_manager.py status|list|create <name>|revoke <name>|start|stop|restart")

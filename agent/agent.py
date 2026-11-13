#!/usr/bin/env python3
"""ovpn-agent -- the on-host agent for openvpn-sk5-panel (FLMX-agent model).

The panel is the control plane (Cloudflare Worker or a server); this
agent runs on the transit host and does the real work. It ONLY talks
outbound: every 5 s it POSTs to the panel's /api/agent/poll, executes
any queued commands through core/openvpn_manager.py and
egress/sk5_manager.py (imported, never reimplemented), then POSTs the
result to /api/agent/report. The transit host needs NO inbound port,
so it works behind NAT / a firewall.

    poll   POST {panel_url}/api/agent/poll
           {"node_token": "...", "node_name": "...",
            "status": {"version": ..., "openvpn_running": bool,
                       "sk5_enabled": bool, "hostname": ...}}
           -> {"commands": [{"id": "...", "action": "...", "params": {...}}]}

    report POST {panel_url}/api/agent/report
           {"node_token": "...", "node_name": "...", "id": "...",
            "ok": bool, "result": {...} | null, "error": str | null}

Config: /etc/ovpn-agent/config.json (0600)
    {"panel_url": "https://panel.example.com",   # no trailing slash
     "node_token": "<secret issued by the panel>",
     "node_name": "transit-01"}

Standard library only -- no pip dependencies, so the agent runs on a
bare Debian 12 / Ubuntu 22.04 / 24.04 host. Python 3.10+.

Security: the node token and any SK5 password are never written to
logs (only action/id/ok are logged). Command params are validated
against a whitelist before dispatch; unknown actions are rejected
and reported as errors, never executed. The panel URL must be https
(http allowed only for 127.0.0.1/localhost smoke tests); https->http
redirects are refused so the token can never be downgraded to
plaintext. The config file is forced to mode 0600 on every load.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import signal
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

VERSION = "0.1.0"
AGENT_NAME = "ovpn-agent"

DEFAULT_CONFIG_PATH = Path(
    os.environ.get("OVPN_AGENT_CONFIG", "/etc/ovpn-agent/config.json")
)
POLL_INTERVAL = 5          # seconds between polls
POLL_TIMEOUT = 10          # seconds per HTTP request
MAX_BACKOFF = 60           # seconds, on repeated panel-unreachable

# Layout: installed as /opt/ovpn-agent/agent/agent.py with core/ and
# egress/ as siblings of agent/; a repo checkout has the same shape.
AGENT_DIR = Path(__file__).resolve().parent
INSTALL_ROOT = AGENT_DIR.parent
for _candidate in (INSTALL_ROOT, AGENT_DIR.parent.parent):
    if (_candidate / "core" / "openvpn_manager.py").is_file() and (
        _candidate / "egress" / "sk5_manager.py"
    ).is_file():
        INSTALL_ROOT = _candidate
        break
if str(INSTALL_ROOT) not in sys.path:
    sys.path.insert(0, str(INSTALL_ROOT))

# core/egress live under INSTALL_ROOT/{core,egress} and are imported as
# top-level modules, so their directories must be on sys.path BEFORE
# the imports below (importing first, then adding the path, fails).
for _sub in ("core", "egress"):
    _p = str(INSTALL_ROOT / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import openvpn_manager  # noqa: E402  (path set up above)
import sk5_manager      # noqa: E402

log = logging.getLogger(AGENT_NAME)

# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

SINGBOX_VERSION = "1.11.15"  # pinned, same as install.sh -- do not float
SINGBOX_BASE = (
    "https://github.com/SagerNet/sing-box/releases/download/v%s"
    % SINGBOX_VERSION
)
TUN2SOCKS_VERSION = "2.7.0"  # pinned, same as install.sh -- do not float
TUN2SOCKS_BASE = (
    "https://github.com/xjasonlyu/tun2socks/releases/download/v%s"
    % TUN2SOCKS_VERSION
)

# Pinned sha256 of the release assets above (BUG-2): the upstream releases
# publish NO sha256 manifest (live-verify §9), so without these the agent
# could never install on a fresh node -- the manifest step alone always
# fails. Values are double-anchor verified against the real binaries and
# their self-reported versions (2026-11-12, same values as install.sh).
# Priority: env/param override > pinned hash below > upstream manifest.
# A pinned hash must be refreshed together with the version above.
SINGBOX_SHA256_AMD64 = (
    "950af37eb2d7e55dddae34a18411cd617303fd99d2dc75bc76b6dd9fcd97d9c5"
)
SINGBOX_SHA256_ARM64 = (
    "20a6a9cd259a95411599f811a5066513a98db63705a51121252ad27daf96c029"
)
TUN2SOCKS_SHA256_AMD64 = (
    "a612baa287a3b6de6221f74fd02b442a50888508227ecf51e1288a5ccbb77381"
)
TUN2SOCKS_SHA256_ARM64 = (
    "3931476c9cfa8fa236d23aeaf36767df0eb27cc11ecaab699faba57744450f49"
)

_PINNED_SHA256 = {
    ("sing-box", "amd64"): SINGBOX_SHA256_AMD64,
    ("sing-box", "arm64"): SINGBOX_SHA256_ARM64,
    ("tun2socks", "amd64"): TUN2SOCKS_SHA256_AMD64,
    ("tun2socks", "arm64"): TUN2SOCKS_SHA256_ARM64,
}


def _pinned_sha256(binary: str, arch: str) -> str:
    """Pinned sha256 for a (binary, arch) pair, or "" when unpinned."""
    return _PINNED_SHA256.get((binary, arch), "")

# Params that must never appear in logs (values are redacted wholesale).
SECRET_KEYS = {"node_token", "token", "password"}


def _redact(obj: Any) -> Any:
    """Deep-copy *obj* with secret values replaced (for logging only)."""
    if isinstance(obj, dict):
        return {
            k: ("***" if k in SECRET_KEYS else _redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


def _validate_panel_url(panel_url: str) -> None:
    """面板 URL 必须走 HTTPS；仅本地回环 http 例外（本机假面板冒烟用）。

    token 与 .ovpn（含用户私钥）都走 poll/report，生产部署走明文
    http 会直接泄露它们，所以这里硬拒绝，不只告警。
    """
    parsed = urllib.parse.urlparse(panel_url)
    if parsed.scheme == "https" and parsed.hostname:
        return
    if parsed.scheme == "http" and parsed.hostname in (
            "127.0.0.1", "localhost", "::1"):
        return
    raise RuntimeError(
        "panel_url must use https:// "
        "(http allowed only for 127.0.0.1/localhost): %s" % panel_url
    )


def load_config(path: Path | None = None) -> dict:
    """Load the agent config; raises a clear error when unusable."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not path.is_file():
        raise RuntimeError(
            "agent config not found at %s -- run install-agent.sh "
            "(--panel-url ... --token ...) first" % path
        )
    # token 配置文件强制 0600：装机脚本已写 0600，这里每次加载再核一次，
    # 权限被改宽（比如误 cp 过来）时当场收紧，改不动则告警不断行。
    try:
        if stat.S_IMODE(os.stat(path).st_mode) != 0o600:
            os.chmod(path, 0o600)
    except OSError as exc:
        log.warning("cannot chmod agent config %s to 0600: %s", path, exc)
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("cannot parse agent config %s: %s" % (path, exc)) from exc
    if not isinstance(cfg, dict):
        raise RuntimeError("agent config %s is not a JSON object" % path)
    panel_url = str(cfg.get("panel_url", "")).rstrip("/")
    token = str(cfg.get("node_token", ""))
    _validate_panel_url(panel_url)
    if not token:
        raise RuntimeError("node_token missing in %s" % path)
    # BUG-5: how the agent trusts the panel's TLS certificate.
    # "ca_cert": path to a PEM file with the panel's (self-signed)
    # certificate -- install-agent.sh fetches it from the panel on
    # first install (TOFU) and writes it here. "insecure": skip
    # verification entirely -- only ever set explicitly, never the
    # default; the panel UI / installer warn loudly when it is on.
    ca_cert = str(cfg.get("ca_cert") or "").strip() or None
    insecure = bool(cfg.get("insecure", False))
    return {
        "panel_url": panel_url,
        "node_token": token,
        "node_name": str(cfg.get("node_name", "") or platform.node()),
        "config_path": str(path),
        "ca_cert": ca_cert,
        "insecure": insecure,
    }


# ---------------------------------------------------------------------------
# HTTP (stdlib only)
# ---------------------------------------------------------------------------

class _NoDowngradeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """拒绝 https -> http 的重定向：Authorization 里的 token 绝不能
    被一次重定向带到明文地址上。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old_scheme = urllib.parse.urlparse(req.full_url).scheme
        new_scheme = urllib.parse.urlparse(newurl).scheme
        if old_scheme == "https" and new_scheme != "https":
            raise urllib.error.URLError(
                "refusing https->http redirect to %s" % newurl
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _make_ssl_context(cfg: dict) -> ssl.SSLContext:
    """Build the TLS context the agent uses to talk to the panel.

    BUG-5: the panel serves a self-signed certificate and the agent
    used to verify against the system store only, so poll failed
    forever with CERTIFICATE_VERIFY_FAILED. Resolution order:
    insecure=True -> unverified context (explicit opt-in only, warns);
    ca_cert set -> system store + that PEM as an extra trust anchor;
    otherwise the default system store (public-CA panels, e.g. a
    Cloudflare front, need nothing extra).
    """
    if cfg.get("insecure"):
        log.warning(
            "TLS verification DISABLED for the panel (insecure=true): "
            "the node token and .ovpn contents can be intercepted -- "
            "use ca_cert instead whenever possible")
        return ssl._create_unverified_context()
    ca_cert = cfg.get("ca_cert")
    if ca_cert:
        path = Path(ca_cert)
        if not path.is_file():
            raise RuntimeError(
                "ca_cert %s does not exist -- re-run install-agent.sh "
                "to re-fetch the panel certificate" % path
            )
        ctx = ssl.create_default_context(cafile=str(path))
        log.info("trusting panel certificate from %s", path)
        return ctx
    return ssl.create_default_context()


def _post_json(
    url: str, payload: dict, token: str,
    ssl_context: ssl.SSLContext | None = None,
) -> dict:
    """POST JSON, return the decoded JSON object. Raises on any failure."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % token,
            "User-Agent": "%s/%s" % (AGENT_NAME, VERSION),
        },
        method="POST",
    )
    # stdlib 默认校验 HTTPS 证书；另禁 https->http 降级重定向。
    # BUG-5: the context carries the panel's pinned self-signed cert
    # when one is configured (ca_cert), else the system store.
    handlers = [_NoDowngradeRedirectHandler()]
    if ssl_context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=ssl_context))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=POLL_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError("panel HTTP %s on %s" % (exc.code, url)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("cannot reach panel %s: %s" % (url, exc)) from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError("panel returned non-JSON on %s" % url) from exc
    if not isinstance(data, dict):
        raise RuntimeError("panel returned non-object JSON on %s" % url)
    return data


# ---------------------------------------------------------------------------
# heartbeat (cheap: no network probes -- a curl per poll would be wasteful)
# ---------------------------------------------------------------------------

def heartbeat_status() -> dict:
    """Small status block sent with every poll."""
    try:
        running = bool(openvpn_manager.server_status().get("running"))
    except Exception:  # noqa: BLE001 -- heartbeat must never kill the loop
        running = False
    sk5_enabled = False
    try:
        sk5_cfg = Path("/etc/openvpn-sk5-panel/sk5.json")
        if sk5_cfg.is_file():
            # R20-P2-2: parsed JSON may be a list/string/number -- calling
            # .get() on it raises AttributeError, which (OSError, ValueError)
            # never caught, so every poll died before sending any request
            # and the node went permanently silent. Same dict-shape check
            # as load_config (:197) and the poll response (:305); a
            # non-object JSON is treated as "no usable config" (False),
            # exactly like a missing file. The except clause is deliberately
            # left narrow: with the isinstance check, .get() is only ever
            # called on a dict, so AttributeError is unreachable here.
            parsed = json.loads(sk5_cfg.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                sk5_enabled = bool(parsed.get("enabled"))
    except (OSError, ValueError):
        sk5_enabled = False
    return {
        "version": VERSION,
        "hostname": platform.node(),
        "openvpn_running": running,
        "sk5_enabled": sk5_enabled,
    }


# ---------------------------------------------------------------------------
# param validation (whitelist -- anything else is rejected, never run)
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")


def _need_params(params: dict, *keys: str) -> None:
    for key in keys:
        if key not in params or params[key] in (None, ""):
            raise ValueError("missing required param: %s" % key)


def _as_int(value: Any, name: str, lo: int = 1, hi: int = 65535) -> int:
    # R13-P2-5: reject bool (and float) before any coercion. ``int()``
    # silently changed semantics: ``int(True) == 1`` rendered a bogus
    # ``port 1`` server.conf, and ``int(1194.5) == 1194`` truncated.
    # A digit string stays accepted (R13 probe N15 pins "1194" -> 1194):
    # that coercion is lossless and unambiguous, unlike bool/float.
    if isinstance(value, bool):
        raise ValueError("param %s must be an integer, got bool" % name)
    if isinstance(value, int):
        num = value
    elif isinstance(value, str):
        text = value.strip()
        if not text or not text.lstrip("-").isdigit():
            raise ValueError("param %s must be an integer" % name)
        num = int(text)
    else:
        raise ValueError("param %s must be an integer" % name)
    if not lo <= num <= hi:
        raise ValueError("param %s out of range %d-%d" % (name, lo, hi))
    return num


def _as_bool(value: Any, name: str, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValueError("param %s must be a boolean" % name)


def _as_proto(value: Any) -> str:
    proto = str(value or "udp").lower()
    if proto not in ("udp", "tcp"):
        raise ValueError("proto must be 'udp' or 'tcp', got %r" % value)
    return proto


# ---------------------------------------------------------------------------
# actions -- thin dispatch into core/egress; no logic is reimplemented here
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            "command failed (%s): %s"
            % (" ".join(cmd), (proc.stderr or proc.stdout or "").strip()[:500])
        )
    return proc


def _arch() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    raise RuntimeError(
        "unsupported architecture: %s "
        "(only amd64/arm64 have pinned release assets)" % machine
    )


def _download(url: str, dest: Path, timeout: int = 300) -> None:
    req = urllib.request.Request(
        url, headers={"User-Agent": "%s/%s" % (AGENT_NAME, VERSION)}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, \
                open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("download failed: %s (%s)" % (url, exc)) from exc


def _download_text(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "%s/%s" % (AGENT_NAME, VERSION)}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("download failed: %s (%s)" % (url, exc)) from exc


def _expected_sha256(
    asset: str,
    base_url: str,
    override: str | None,
    env_name: str,
    pinned: str = "",
) -> str:
    """Fail-closed hash resolution (FLMX §1-15 pattern, same as install.sh):
    1. operator-supplied hash (command param, else $SINGBOX_SHA256 /
       $TUN2SOCKS_SHA256 env), if set -- strict;
    2. the pinned hash for this version+arch (BUG-2: the upstream releases
       publish no sha256 manifest, so without this step a fresh install
       can never verify -- this is the step that makes it work);
    3. otherwise the release's own published manifest (checksums.txt,
       then SHA256SUMS.txt) fetched over the same HTTPS connection;
    4. none available -> raise: never install an unverified binary.
    A hash value is never invented, and a missing hash is never a
    warning -- the install stops here."""
    if override:
        want = str(override).strip().lower()
        if len(want) != 64 or any(c not in "0123456789abcdef" for c in want):
            raise RuntimeError("%s is not a 64-hex sha256" % env_name)
        return want
    if pinned:
        want = str(pinned).strip().lower()
        if len(want) != 64 or any(c not in "0123456789abcdef" for c in want):
            raise RuntimeError("pinned sha256 for %s is not 64-hex" % asset)
        log.info("using pinned sha256 for %s", asset)
        return want
    tried: list[str] = []
    for manifest_name in ("checksums.txt", "SHA256SUMS.txt", "sha256sums.txt"):
        try:
            text = _download_text("%s/%s" % (base_url, manifest_name))
        except RuntimeError:
            continue
        tried.append(manifest_name)
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].lstrip("*") == asset:
                return parts[0].lower()
        # P2-11: this manifest exists but has no entry for the asset --
        # try the next manifest name instead of refusing outright.
    if tried:
        raise RuntimeError(
            "manifest(s) %s have no entry for %s -- refusing to install "
            "unverified binary" % (", ".join(tried), asset)
        )
    raise RuntimeError(
        "no sha256 manifest published for this release and no %s "
        "override set -- download the asset yourself, run "
        "'sha256sum %s', then re-run with %s=<hash>"
        % (env_name, asset, env_name)
    )


def _verify_file(path: Path, want: str, asset: str) -> None:
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != want:
        raise RuntimeError(
            "%s sha256 mismatch (expected %s, got %s) -- refusing to install"
            % (asset, want, actual)
        )
    log.info("sha256 OK: %s", asset)


def _install_singbox(params: dict) -> str:
    """Download + verify + install the pinned sing-box binary (fail-closed)."""
    singbox = Path("/usr/local/bin/sing-box")
    if singbox.is_file():
        # P2-2: an installed sing-box is only accepted when it reports
        # the pinned version (same rule tun2socks already had). An old
        # 1.8.0 would otherwise pass here and only fail later at
        # `sing-box check` with a confusing 1.11-field error.
        proc = _run([str(singbox), "version"], timeout=30)
        if SINGBOX_VERSION in (proc.stdout or ""):
            return str(singbox)
        log.info("installed sing-box is not %s, replacing", SINGBOX_VERSION)
    arch = _arch()
    asset = "sing-box-%s-linux-%s.tar.gz" % (SINGBOX_VERSION, arch)
    url = "%s/%s" % (SINGBOX_BASE, asset)
    override = (params.get("singbox_sha256")
                or os.environ.get("SINGBOX_SHA256") or "")
    with tempfile.TemporaryDirectory(prefix="ovpn-agent-singbox-") as tmp:
        archive = Path(tmp) / "sing-box.tar.gz"
        log.info("downloading sing-box %s (%s)", SINGBOX_VERSION, asset)
        _download(url, archive)
        _verify_file(
            archive,
            _expected_sha256(
                asset, SINGBOX_BASE, override, "SINGBOX_SHA256",
                _pinned_sha256("sing-box", arch),
            ),
            asset,
        )
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(path=tmp, filter="data")
        binary = next(Path(tmp).rglob("sing-box"), None)
        if binary is None or not binary.is_file():
            raise RuntimeError("sing-box binary not found in %s" % url)
        singbox.write_bytes(binary.read_bytes())
        singbox.chmod(0o755)
    _run([str(singbox), "version"], timeout=30)
    return str(singbox)


def _install_tun2socks(params: dict) -> str:
    """Download + verify + install the pinned tun2socks binary (fail-closed).
    Standby path for the egress chain (sing-box tun is primary)."""
    tun2socks = Path("/usr/local/bin/tun2socks")
    if tun2socks.is_file():
        proc = _run([str(tun2socks), "--version"], timeout=30)
        if TUN2SOCKS_VERSION in (proc.stdout or ""):
            return str(tun2socks)
        log.info("installed tun2socks is not %s, replacing", TUN2SOCKS_VERSION)
    arch = _arch()
    asset = "tun2socks-linux-%s.zip" % arch
    url = "%s/%s" % (TUN2SOCKS_BASE, asset)
    override = (params.get("tun2socks_sha256")
                or os.environ.get("TUN2SOCKS_SHA256") or "")
    with tempfile.TemporaryDirectory(prefix="ovpn-agent-tun2socks-") as tmp:
        archive = Path(tmp) / "tun2socks.zip"
        log.info("downloading tun2socks %s (%s)", TUN2SOCKS_VERSION, asset)
        _download(url, archive)
        _verify_file(
            archive,
            _expected_sha256(
                asset, TUN2SOCKS_BASE, override, "TUN2SOCKS_SHA256",
                _pinned_sha256("tun2socks", arch),
            ),
            asset,
        )
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(path=tmp)
        binary = next(Path(tmp).rglob("tun2socks"), None)
        if binary is None or not binary.is_file():
            raise RuntimeError("tun2socks binary not found in %s" % url)
        tun2socks.write_bytes(binary.read_bytes())
        tun2socks.chmod(0o755)
    proc = _run([str(tun2socks), "--version"], timeout=30)
    if TUN2SOCKS_VERSION not in (proc.stdout or ""):
        raise RuntimeError(
            "installed tun2socks does not report %s" % TUN2SOCKS_VERSION)
    return str(tun2socks)


def action_install_prereqs(params: dict) -> dict:
    """apt-install openvpn/easy-rsa + sing-box + tun2socks (pinned versions,
    sha256 fail-closed -- see _expected_sha256)."""
    _run(["apt-get", "update"], timeout=300)
    _run(
        [
            "apt-get", "install", "-y", "--no-install-recommends",
            "openvpn", "easy-rsa", "curl", "ca-certificates",
            "iproute2", "iptables", "python3",
        ],
        timeout=900,
    )
    singbox = _install_singbox(params)
    tun2socks = _install_tun2socks(params)
    return {
        "openvpn": True,
        "singbox": singbox,
        "singbox_version": SINGBOX_VERSION,
        "tun2socks": tun2socks,
        "tun2socks_version": TUN2SOCKS_VERSION,
    }


def action_init_pki(params: dict) -> dict:
    force = _as_bool(params.get("force"), "force", False)
    # P2-9: force=true wipes the CA and invalidates every issued client
    # certificate. A single remote command must never do that by
    # accident (or via a stolen session): it needs an explicit
    # confirm=true alongside force.
    if force and params.get("confirm") is not True:
        raise ValueError(
            "init_pki force=true wipes the CA and invalidates every "
            "issued client certificate: resend with confirm=true to proceed"
        )
    ca_dir = openvpn_manager.init_pki(force=force)
    installed = openvpn_manager.build_server_cert()
    return {"ca_dir": str(ca_dir), "server_files": installed}


def action_create_server(params: dict) -> dict:
    proto = _as_proto(params.get("proto", "udp"))
    port = _as_int(params.get("port", 1194 if proto == "udp" else 443), "port")
    ca_crt = Path(
        os.environ.get(
            "OPENVPN_CA_DIR", "/etc/openvpn/server/easy-rsa"
        )
    ) / "pki" / "ca.crt"
    if not ca_crt.exists():
        openvpn_manager.init_pki()
    # P1-10: build_server_cert() is idempotent now (a complete set is
    # reused, a stale partial pair is cleared first), so re-running
    # create_server to change DNS -- or with allow_port_change to move
    # the entry port -- no longer dies in Easy-RSA.
    installed = openvpn_manager.build_server_cert()
    conf = openvpn_manager.render_server_conf(
        proto=proto, port=port,
        dns=(str(params["dns"]) if params.get("dns") else None),
        allow_port_change=_as_bool(
            params.get("allow_port_change"), "allow_port_change", False),
    )
    return {"proto": proto, "port": port, "conf": str(conf), "server_files": installed}


def action_start_openvpn(_params: dict) -> dict:
    return openvpn_manager.start_server()


def action_stop_openvpn(_params: dict) -> dict:
    return openvpn_manager.stop_server()


def action_restart_openvpn(_params: dict) -> dict:
    return openvpn_manager.restart_server()


def action_create_user(params: dict) -> dict:
    _need_params(params, "name")
    name = str(params["name"])
    if not _NAME_RE.match(name):
        raise ValueError("invalid username: must match [A-Za-z0-9_-]{1,32}")
    ovpn = openvpn_manager.create_user(
        name,
        server_ip=params.get("server_ip") or None,
        proto=_as_proto(params["proto"]) if params.get("proto") else None,
        port=_as_int(params["port"], "port") if params.get("port") else None,
    )
    # The .ovpn embeds the user's private key: it travels only over the
    # HTTPS report channel to the panel, which must deliver it to the
    # requesting admin -- never log it (see _redact / logging below).
    return {"name": name, "ovpn": ovpn}


def action_revoke_user(params: dict) -> dict:
    _need_params(params, "name")
    name = str(params["name"])
    if not _NAME_RE.match(name):
        raise ValueError("invalid username: must match [A-Za-z0-9_-]{1,32}")
    revoked = openvpn_manager.revoke_user(name)
    # CRL is only read at daemon start -- restart so the revocation
    # takes effect for new connections immediately.
    status = openvpn_manager.restart_server()
    return {"revoked": revoked, "server": status}


def action_set_sk5(params: dict) -> dict:
    # P0-2 / P0-4: set_sk5 is partial-merge -- absent fields keep their
    # stored values, an empty password keeps the stored password. So a
    # single-field toggle ({"fail_open": true} / {"udp_over_tcp": true})
    # works without resending host+port, and saving the panel form
    # with the password box left blank can no longer wipe the
    # credential. Only an explicitly non-empty password overwrites it
    # (clear_password=True switches to an auth-free merchant).
    host = params.get("host")
    if host is not None:
        host = str(host)
        if not _HOST_RE.match(host):
            raise ValueError("invalid SK5 host %r" % host)
    port = _as_int(params["port"], "port") if params.get("port") is not None else None
    return sk5_manager.set_sk5(
        host,
        port,
        username=(str(params["username"])
                  if params.get("username") is not None else None),
        password=(str(params["password"])
                  if params.get("password") else None),
        enabled=(_as_bool(params["enabled"], "enabled")
                 if params.get("enabled") is not None else None),
        fail_open=(_as_bool(params["fail_open"], "fail_open")
                   if params.get("fail_open") is not None else None),
        udp_over_tcp=(_as_bool(params["udp_over_tcp"], "udp_over_tcp")
                      if params.get("udp_over_tcp") is not None else None),
        clear_password=bool(params.get("clear_password", False)),
    )


def action_test_sk5(_params: dict) -> dict:
    return sk5_manager.test_sk5()


def action_enable_sk5(_params: dict) -> dict:
    return sk5_manager.enable()


def action_disable_sk5(_params: dict) -> dict:
    return sk5_manager.disable()


def action_get_status(_params: dict) -> dict:
    return {
        "openvpn": openvpn_manager.server_status(),
        "users": openvpn_manager.list_users(),
        "sk5": sk5_manager.get_status(),
        "egress_ip": sk5_manager.current_egress_ip(),
        # P1-8: last timer-driven health check (None until the first
        # check_health run); the panel snapshot reads this instead of
        # re-probing on every status poll.
        "health": sk5_manager.last_health(),
    }


ACTIONS = {
    "install_prereqs": action_install_prereqs,
    "init_pki": action_init_pki,
    "create_server": action_create_server,
    "start_openvpn": action_start_openvpn,
    "stop_openvpn": action_stop_openvpn,
    "restart_openvpn": action_restart_openvpn,
    "create_user": action_create_user,
    "revoke_user": action_revoke_user,
    "set_sk5": action_set_sk5,
    "test_sk5": action_test_sk5,
    "enable_sk5": action_enable_sk5,
    "disable_sk5": action_disable_sk5,
    "get_status": action_get_status,
}


def execute_command(cmd: dict) -> tuple[bool, Any, str | None]:
    """Run one panel command. Returns (ok, result, error). Never raises."""
    cmd_id = str(cmd.get("id", ""))
    action = str(cmd.get("action", ""))
    params = cmd.get("params") or {}
    if not isinstance(params, dict):
        return False, None, "params must be an object"
    fn = ACTIONS.get(action)
    if fn is None:
        return False, None, "unknown action: %s" % action
    # 纵深防御：面板只许发白名单 action + 当 action 的参数；任何
    # 想借 params 夹带 shell 命令的键一律在分派前拒绝——agent 全程
    # 不接受面板下发的任意 shell 命令（执行层只用 subprocess 列表参数）。
    bad = {"command", "shell", "cmd", "exec", "script", "argv"} & {
        str(k).lower() for k in params
    }
    if bad:
        return False, None, "forbidden param: %s" % sorted(bad)[0]
    log.info("cmd %s action=%s params=%s", cmd_id, action, _redact(params))
    try:
        return True, fn(params), None
    except Exception as exc:  # noqa: BLE001 -- every failure is reported
        log.warning("cmd %s action=%s failed: %s", cmd_id, action, exc)
        return False, None, "%s: %s" % (type(exc).__name__, exc)


# ---------------------------------------------------------------------------
# poll loop
# ---------------------------------------------------------------------------

class Agent:
    def __init__(self, cfg: dict, ssl_context: ssl.SSLContext | None = None):
        self.cfg = cfg
        self.ssl_context = ssl_context or _make_ssl_context(cfg)
        self.backoff = POLL_INTERVAL

    def poll_once(self) -> list[dict]:
        payload = {
            "node_token": self.cfg["node_token"],
            "node_name": self.cfg["node_name"],
            # panel_url 一并上报：面板用它做认领守卫——注册时绑定的
            # panel_url 与 agent 配置里的必须逐字相等，否则 403。
            "panel_url": self.cfg["panel_url"],
            "status": heartbeat_status(),
        }
        data = _post_json(
            self.cfg["panel_url"] + "/api/agent/poll",
            payload,
            self.cfg["node_token"],
            self.ssl_context,
        )
        commands = data.get("commands", [])
        if not isinstance(commands, list):
            raise RuntimeError("panel poll returned non-list commands")
        return commands

    def report(self, cmd_id: str, ok: bool, result: Any, error: str | None) -> None:
        payload = {
            "node_token": self.cfg["node_token"],
            "node_name": self.cfg["node_name"],
            "panel_url": self.cfg["panel_url"],
            "id": cmd_id,
            "ok": ok,
            "result": result,
            "error": error,
        }
        _post_json(
            self.cfg["panel_url"] + "/api/agent/report",
            payload,
            self.cfg["node_token"],
            self.ssl_context,
        )

    def run_once(self) -> int:
        """One poll cycle. Returns the number of commands executed, or
        -1 when the poll itself failed (panel unreachable)."""
        try:
            commands = self.poll_once()
        except Exception as exc:  # noqa: BLE001 -- back off, keep running
            log.warning("poll failed: %s (retry in %ss)", exc, self.backoff)
            return -1
        self.backoff = POLL_INTERVAL
        for cmd in commands:
            if not isinstance(cmd, dict) or "id" not in cmd:
                log.warning("skipping malformed command: %s", _redact(cmd))
                continue
            ok, result, error = execute_command(cmd)
            log.info("cmd %s done ok=%s", cmd.get("id"), ok)
            try:
                self.report(str(cmd["id"]), ok, result, error)
            except Exception as exc:  # noqa: BLE001 -- report loss is logged
                log.warning("report for cmd %s failed: %s", cmd.get("id"), exc)
        return len(commands)

    def run_forever(self, interval: int = POLL_INTERVAL) -> None:
        log.info(
            "%s %s started: panel=%s node=%s (poll every %ss, outbound only)",
            AGENT_NAME, VERSION, self.cfg["panel_url"], self.cfg["node_name"],
            interval,
        )
        while True:
            done = self.run_once()
            if done < 0:
                # Poll failed (panel unreachable): grow the wait, capped.
                # A healthy-but-idle panel returns 0 commands and resets
                # the backoff in run_once(), so idle nodes keep polling
                # every `interval` seconds.
                self.backoff = min(max(self.backoff * 2, POLL_INTERVAL), MAX_BACKOFF)
                time.sleep(self.backoff)
            else:
                time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ovpn-agent (polls the panel)")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--once", action="store_true",
                        help="run a single poll cycle, then exit")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL)
    # BUG-5: trust overrides for this run only (the config file's
    # ca_cert/insecure still apply when neither flag is given).
    parser.add_argument("--ca-cert", default=None,
                        help="PEM file with the panel's certificate "
                             "(self-signed panel); overrides config")
    parser.add_argument("--insecure", action="store_true",
                        help="skip TLS verification for the panel "
                             "(explicit opt-in only; the token and .ovpn "
                             "contents can then be intercepted)")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        cfg = load_config(Path(args.config))
        if args.ca_cert:
            cfg["ca_cert"] = args.ca_cert
            cfg["insecure"] = False
        if args.insecure:
            cfg["insecure"] = True
            cfg["ca_cert"] = None
        ctx = _make_ssl_context(cfg)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 2
    agent = Agent(cfg, ctx)

    def _stop(_signum: int, _frame: Any) -> None:
        log.info("stopping on signal")
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    if args.once:
        # P2-3: --once is used by smoke/health scripts, so a failed
        # poll must exit non-zero (run_once returns -1 then).
        return 0 if agent.run_once() >= 0 else 1
    agent.run_forever(interval=args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

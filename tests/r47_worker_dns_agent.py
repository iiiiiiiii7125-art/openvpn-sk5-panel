#!/usr/bin/env python3
"""R47 Worker-face LIVE-R47-1 proof probe (agent + core).

The agent's get_status snapshot must carry the DNS the server actually
pushes (core server_dns(), read from server.conf), and create_server
must return it, so the Worker (and Flask remote) status stops reporting
the hardcoded 1.1.1.1 after a DNS change. Every cell asserts the FIXED
behavior, so the defect cells FAIL on the 1.0.3 baseline (core has no
server_dns there; the snapshot carries no dns; create_server returns
no dns) and PASS on the fixed tree.

Cells (all against a /tmp COPY of the fixed tree, own scratch dirs --
never the shared /tmp/r17 fixture):
- A1-A6 core server_dns() matrix on temp server dirs: 8.8.8.8, bare
  hostname, first of two push lines wins, missing conf -> None,
  non-UTF8 conf -> None without raising, no DNS push line -> None.
- A7  action_get_status snapshot openvpn.dns == 8.8.8.8 (conf pushes it).
- A8  action_get_status with missing conf -> no "dns" key in the
  snapshot openvpn (downstream falls back; never a crash).
- A9  action_create_server dns=8.8.8.8 (fresh PKI, real EasyRSA 3.1.7)
  -> result["dns"] == 8.8.8.8 and server.conf pushes it.
- A10 action_create_server without dns -> result["dns"] == effective
  default ($OVPN_DNS or 1.1.1.1).

Run as nobody with:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    R47WD_TREE=<tree> OVPN_PANEL_DATA_DIR=<fresh data> \\
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OVPN_PANEL_ADMIN_PASS_PATH=<data>/admin.pass \\
    OPENVPN_CA_DIR=<fixture-ca copy> OPENVPN_SERVER_DIR=<temp srv> \\
    OVPN_SK5_CONFIG_DIR=<fresh sk5cfg> OPENVPN_PID_FILE=<temp pid> \\
    EASYRSA_BIN=<toolchain copy>/EasyRSA-3.1.7/easyrsa \\
    python3 <tree>/tests/r47_worker_dns_agent.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

TREE = Path(os.environ.get("R47WD_TREE") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(TREE / "core"))
sys.path.insert(0, str(TREE))
# agent.py lives at <tree>/agent/agent.py: its own directory must
# precede <tree> on sys.path, or `import agent` resolves to the
# agent/ directory as a namespace package (no attributes).
sys.path.insert(0, str(TREE / "agent"))

# Env must be set before importing agent/core (module-level defaults).
SCRATCH = Path(tempfile.mkdtemp(prefix="r47wd-agent-"))
SERVER_DIR = SCRATCH / "srv"
CA_DIR = SCRATCH / "ca"
SK5_DIR = SCRATCH / "sk5"
for d in (SERVER_DIR, CA_DIR, SK5_DIR):
    d.mkdir(parents=True)
os.environ["OPENVPN_SERVER_DIR"] = str(SERVER_DIR)
os.environ["OPENVPN_CA_DIR"] = str(CA_DIR)
os.environ["OVPN_SK5_CONFIG_DIR"] = str(SK5_DIR)
os.environ["OPENVPN_PID_FILE"] = str(SCRATCH / "server.pid")

import openvpn_manager  # noqa: E402
import agent as agent_mod  # noqa: E402

CELLS = []
FAILURES = []


def cell(name, ok, evidence=""):
    CELLS.append(name)
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" | " + str(evidence)[:200]) if evidence else ""),
          flush=True)
    if not ok:
        FAILURES.append(name)


def _server_dns():
    """core.server_dns() when present; a marker when the tree predates it
    (so the matrix cells FAIL instead of crashing on the baseline)."""
    fn = getattr(openvpn_manager, "server_dns", None)
    if fn is None:
        return "<no server_dns>"
    return fn()


def write_conf(text_or_bytes, name="server.conf"):
    p = SERVER_DIR / name
    if isinstance(text_or_bytes, bytes):
        p.write_bytes(text_or_bytes)
    else:
        p.write_text(text_or_bytes, encoding="utf-8")
    return p


BASE_CONF = (
    "port 1194\nproto udp\ndev tun\n"
    "push \"dhcp-option DNS %s\"\n"
)

# A1-A6: core server_dns() matrix.
write_conf(BASE_CONF % "8.8.8.8")
cell("A1 server_dns reads pushed 8.8.8.8",
     _server_dns() == "8.8.8.8",
     _server_dns())
write_conf(BASE_CONF % "dns.example")
cell("A2 server_dns passes a bare hostname through",
     _server_dns() == "dns.example",
     _server_dns())
write_conf("port 1194\nproto udp\ndev tun\n"
           "push \"dhcp-option DNS 8.8.8.8\"\n"
           "push \"dhcp-option DNS 9.9.9.9\"\n")
cell("A3 server_dns takes the first push line",
     _server_dns() == "8.8.8.8",
     _server_dns())
(SERVER_DIR / "server.conf").unlink()
cell("A4 server_dns missing conf -> None",
     _server_dns() is None)
write_conf(b"port 1194\npush \"dhcp-option DNS 8.8.8.8\"\n\xff\xfe bad bytes\n")
try:
    got = _server_dns()
    cell("A5 server_dns non-UTF8 conf -> None, no raise", got is None, got)
except Exception as exc:  # noqa: BLE001 -- the point is "never raises"
    cell("A5 server_dns non-UTF8 conf -> None, no raise", False, repr(exc))
write_conf("port 1194\nproto udp\ndev tun\n")
cell("A6 server_dns no DNS push line -> None",
     _server_dns() is None)

# A7/A8: action_get_status snapshot. list_users() needs a CA dir with
# an index.txt; copy the shared R17 fixture CA (read-only use).
FIXTURE_CA = Path(os.environ.get("R47WD_FIXTURE_CA", "/tmp/r17/fixture-ca"))
if FIXTURE_CA.is_dir():
    shutil.copytree(FIXTURE_CA, CA_DIR, dirs_exist_ok=True)
    os.environ["OPENVPN_CA_DIR"] = str(CA_DIR)
write_conf(BASE_CONF % "8.8.8.8")
try:
    snap = agent_mod.action_get_status({})
    ovpn = snap.get("openvpn") or {}
    cell("A7 get_status snapshot carries dns 8.8.8.8",
         ovpn.get("dns") == "8.8.8.8", ovpn.get("dns"))
except Exception as exc:  # noqa: BLE001 -- report, don't crash the probe
    cell("A7 get_status snapshot carries dns 8.8.8.8", False, repr(exc))
(SERVER_DIR / "server.conf").unlink()
try:
    snap = agent_mod.action_get_status({})
    ovpn = snap.get("openvpn") or {}
    cell("A8 get_status without conf has no dns key",
         "dns" not in ovpn, sorted(ovpn.keys()))
except Exception as exc:  # noqa: BLE001
    cell("A8 get_status without conf has no dns key", False, repr(exc))

# A9/A10: action_create_server returns the pushed dns (fresh PKI, real
# EasyRSA). Needs EASYRSA_BIN pointing at a 3.1.7 easyrsa.
EASYRSA_BIN = os.environ.get("EASYRSA_BIN", "")
if EASYRSA_BIN and Path(EASYRSA_BIN).is_file():
    try:
        res = agent_mod.action_create_server(
            {"proto": "udp", "port": 1194, "dns": "8.8.8.8"})
        pushed = (SERVER_DIR / "server.conf").read_text(
            encoding="utf-8")
        cell("A9 create_server dns=8.8.8.8 returns dns 8.8.8.8",
             res.get("dns") == "8.8.8.8", res.get("dns"))
        cell("A9b server.conf pushes 8.8.8.8 after create_server",
             'push "dhcp-option DNS 8.8.8.8"' in pushed)
    except Exception as exc:  # noqa: BLE001
        cell("A9 create_server dns=8.8.8.8 returns dns 8.8.8.8", False, repr(exc))
        cell("A9b server.conf pushes 8.8.8.8 after create_server", False, repr(exc))
    try:
        res = agent_mod.action_create_server({"proto": "udp", "port": 1194})
        want = os.environ.get("OVPN_DNS") or "1.1.1.1"
        cell("A10 create_server without dns returns default %s" % want,
             res.get("dns") == want, res.get("dns"))
    except Exception as exc:  # noqa: BLE001
        cell("A10 create_server without dns returns default", False, repr(exc))
else:
    for name in ("A9 create_server dns=8.8.8.8 returns dns 8.8.8.8",
                 "A9b server.conf pushes 8.8.8.8 after create_server",
                 "A10 create_server without dns returns default"):
        cell(name, False, "EASYRSA_BIN not set to a real easyrsa binary")

print("\n%d/%d PASS" % (len(CELLS) - len(FAILURES), len(CELLS)))
if FAILURES:
    print("FAILURES: " + ", ".join(FAILURES))
    sys.exit(1)

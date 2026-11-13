#!/usr/bin/env python3
"""AUDIT-R17 core probe (r17_core.py) — render guards, own enumeration.

Drives core/openvpn_manager.py directly (real code paths). Env:
  OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server>
Cells C1..C2x; exit code = FAIL count.
"""
import os
import sys
from pathlib import Path

TREE = Path(os.environ.get("R17_TREE", "/tmp/r17/ptree"))
sys.path.insert(0, str(TREE / "core"))

from openvpn_manager import (  # noqa: E402
    OpenVPNError, _validate_dns, build_client_config, list_users,
    render_server_conf, validate_username)

PEM_CA = "-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----"
PEM_CERT = "-----BEGIN CERTIFICATE-----\nFAKE\n-----END CERTIFICATE-----"
PEM_KEY = "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----"
PEM_TA = "-----BEGIN OpenVPN Static key V1-----\nFAKE\n-----END OpenVPN Static key V1-----"

RESULTS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""))


def raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except Exception as e:  # noqa: BLE001
        return e


def main():
    srv = Path(os.environ["OPENVPN_SERVER_DIR"])
    # ---------- C1 render_server_conf guards ----------
    for val, label in [(True, "bool True"), (False, "bool False"), (0, "0"),
                       (1194.5, "float"), ("1194", "digit str"), (-1, "-1"),
                       (65536, "65536"), ([1194], "list")]:
        e = raises(render_server_conf, "udp", val, server_dir=srv)
        cell(f"C1-01 render port={label} raises", e is not None,
             f"{type(e).__name__}: {str(e)[:60]}" if e else "no raise")
    e = raises(render_server_conf, "udp", 1194, server_dir=srv)
    cell("C1-02 render port=1194 ok", e is None, str(e)[:80] if e else "")
    e = raises(render_server_conf, "udp", None, server_dir=srv)
    cell("C1-03 render port=None defaults ok", e is None, str(e)[:80] if e else "")
    for val, label in [(False, "False"), (0, "0"), ("", "empty str")]:
        e = raises(render_server_conf, "udp", 1194, server_dir=srv, dns=val)
        cell(f"C1-04 render dns={label} raises (R14-P2-2)", e is not None,
             f"{type(e).__name__}: {str(e)[:60]}" if e else "no raise")
    e = raises(render_server_conf, "udp", 1194, server_dir=srv, dns=None)
    cell("C1-05 render dns=None defaults to 1.1.1.1", e is None, str(e)[:80] if e else "")
    conf = srv / "server.conf"
    cell("C1-06 rendered conf has port 1194 + dns 1.1.1.1",
         conf.exists() and "port 1194" in conf.read_text()
         and "1.1.1.1" in conf.read_text(), "")
    e = raises(render_server_conf, "udp", 1194, server_dir=srv, dns="bad dns")
    cell("C1-07 render dns='bad dns' raises", e is not None, str(e)[:60] if e else "")
    e = raises(render_server_conf, "udp", 1194, server_dir=srv, dns="999.1.1.1")
    # OBSERVED (not filed): _validate_dns is charset-only by design
    # (docstring: bare IP/hostname, no whitespace/shell metachars) --
    # "999.1.1.1" is accepted verbatim and would break client DNS at
    # runtime. Panel surface never accepts dns (fixed 1.1.1.1); only
    # OVPN_DNS env / agent params reach it, and the failure is loud.
    cell("C1-08 OBSERVED: render dns='999.1.1.1' accepted (charset-only)",
         e is None, str(e)[:60] if e else "")
    e = raises(render_server_conf, "udp", 1194, server_dir=srv, allow_port_change="false")
    cell("C1-09 render allow_port_change str raises", e is not None, str(e)[:60] if e else "")
    e = raises(render_server_conf, "sctp", 1194, server_dir=srv)
    cell("C1-10 render proto sctp raises", e is not None, str(e)[:60] if e else "")
    e = raises(render_server_conf, 123, 1194, server_dir=srv)
    cell("C1-11 render proto non-string raises", e is not None, str(e)[:60] if e else "")
    # P01 port freeze: existing conf port 1194, re-render port 443 without flag -> 500-ish raise
    e = raises(render_server_conf, "udp", 51194, server_dir=srv, allow_port_change=False)
    cell("C1-12 render port change without allow_port_change raises (P01)",
         e is not None, str(e)[:80] if e else "no raise")
    e = raises(render_server_conf, "udp", 51194, server_dir=srv, allow_port_change=True)
    cell("C1-13 render port change WITH allow_port_change ok", e is None,
         str(e)[:80] if e else "")
    conf_text = conf.read_text()
    cell("C1-14 conf now port 51194", "port 51194" in conf_text, "")

    # ---------- C2 dns validation + username + users ----------
    for val, label, want_raise in [("1.1.1.1", "valid", False), ("8.8.8.8", "valid2", False),
                                   ("bad dns", "space", True), ("", "empty", True),
                                   (None, "None", True)]:
        e = raises(_validate_dns, val)
        cell(f"C2-01 _validate_dns {label} {'raises' if want_raise else 'ok'}",
             (e is not None) == want_raise, str(e)[:60] if e else "")
    # charset-only design: non-IP hostnames / bad octets accepted verbatim
    for val, label in [("999.1.1.1", "octet>255"), ("1.1.1", "short")]:
        e = raises(_validate_dns, val)
        cell(f"C2-01 OBSERVED: _validate_dns {label} accepted (charset-only)",
             e is None, str(e)[:60] if e else "")
    for name, label, want in [("alice", "ok", True), ("../evil", "traversal", False),
                              ("a" * 33, "too long", False), ("bad name", "space", False),
                              ("server", "reserved", False), ("OpenVPN-CA", "reserved2", False),
                              ("ca", "reserved ca", False), ("a-b_c9", "ok2", True)]:
        try:
            validate_username(name)
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
        cell(f"C2-02 validate_username {label} {'ok' if want else 'raises'}", ok == want, name)
    users = {u["name"]: u for u in list_users()}
    cell("C2-03 list_users sees fixture 5 users", len(users) == 5, str(sorted(users)))
    cell("C2-04 bob status revoked", users.get("bob", {}).get("status") == "revoked",
         str(users.get("bob")))
    cell("C2-05 erin V-but-past-expiry reported expired (R9-P1-2)",
         users.get("erin", {}).get("status") == "expired", str(users.get("erin")))
    cell("C2-06 carol status expired", users.get("carol", {}).get("status") == "expired",
         str(users.get("carol")))
    cell("C2-07 alice status valid", users.get("alice", {}).get("status") == "valid",
         str(users.get("alice")))
    e = raises(build_client_config, "alice", PEM_CA, PEM_CERT, PEM_KEY, PEM_TA,
               "1.2.3.4", proto="sctp", port=1194)
    cell("C2-08 build_client_config proto sctp raises", e is not None, str(e)[:60] if e else "")
    e = raises(build_client_config, "alice", PEM_CA, PEM_CERT, PEM_KEY, PEM_TA,
               "1.2.3.4", proto="udp", port=True)
    cell("C2-09 build_client_config port=True raises", e is not None, str(e)[:60] if e else "")
    out = build_client_config("alice", PEM_CA, PEM_CERT, PEM_KEY, PEM_TA, "1.2.3.4",
                              proto="udp", port=1194)
    cell("C2-10 build_client_config ok embeds all blobs",
         all(x in out for x in ("FAKE", "1.2.3.4", "1194")), "")

    # Fixture hygiene (R21): C1-13 deliberately leaves the shared fixture
    # server.conf at port 51194 (C1-14 asserts it). Without a reset the
    # NEXT run fails C1-02/03/05/08/12 (existing-conf port is no longer
    # 1194) — the suite was single-shot per fixture. Restore port 1194
    # here so re-runs are green; the restore itself is not a cell.
    try:
        render_server_conf("udp", 1194, server_dir=srv, allow_port_change=True)
    except Exception as exc:  # noqa: BLE001 - fixture reset must not mask results
        print(f"WARNING: fixture server.conf reset failed: {exc}")

    fails = [n for n, ok, _ in RESULTS if not ok]
    print(f"\nTOTAL {len(RESULTS)} cells, FAIL {len(fails)}: {fails}")
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())

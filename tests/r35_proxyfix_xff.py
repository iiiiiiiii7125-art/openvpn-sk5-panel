#!/usr/bin/env python3
"""AUDIT-R35 ProxyFix / X-Forwarded-For probe (r35_proxyfix_xff.py).

Drives panel/app.py through Flask test_client (real code paths, no
monkeypatch except env isolation). Verifies the security.md "域名反代"
row invariants:
  - OVPN_TRUSTED_PROXY=0 (default): X-Forwarded-For is ignored; the
    login rate limit keys on the connection IP only.
  - OVPN_TRUSTED_PROXY=1: ProxyFix(x_for=1) takes the LAST XFF value;
    the rate limit keys on that value -- so a forged XFF rotates the
    lockout bucket (documented residual, see security.md).
  - OVPN_PANEL_HTTPS=1: session cookie carries the Secure flag.

Run as nobody with PYTHONPATH=venv site-packages, one mode per run:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \
    R35_TREE=<ptree> OVPN_PANEL_DATA_DIR=<data> \
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \
    OVPN_SK5_CONFIG_DIR=<sk5cfg> \
    R35_TRUSTED_PROXY=0 R35_PANEL_HTTPS=0 \
    python3 <ptree>/tests/r35_proxyfix_xff.py
R35_TRUSTED_PROXY=1 + R35_PANEL_HTTPS=1 for the second run.
Each run needs a FRESH data dir (lockout rows persist in SQLite).
Exit code = number of FAILs (0 = all green).
"""
import os
import sys
from pathlib import Path

TREE = Path(os.environ.get("R35_TREE", "/tmp/r35/ptree"))
sys.path.insert(0, str(TREE / "panel"))
sys.path.insert(0, str(TREE / "core"))
sys.path.insert(0, str(TREE / "egress"))

# R36: bridge the R35_* selector vars into the OVPN_* vars the app
# actually reads at import (app.py:182/190 reads os.environ
# OVPN_TRUSTED_PROXY / OVPN_PANEL_HTTPS; in production systemd feeds
# them via EnvironmentFile=panel.env, which the probe has no copy of).
# Without this bridge the documented header invocation runs the trust
# cells against an app with ProxyFix off + Secure off (R36 re-run:
# T1-03/05/06/08 fail 4/8) -- a harness gap, not a product defect.
os.environ["OVPN_TRUSTED_PROXY"] = os.environ.get("R35_TRUSTED_PROXY", "0")
os.environ["OVPN_PANEL_HTTPS"] = os.environ.get("R35_PANEL_HTTPS", "0")

import app as panel  # noqa: E402

TRUSTED = os.environ.get("R35_TRUSTED_PROXY", "0") == "1"
HTTPS = os.environ.get("R35_PANEL_HTTPS", "0") == "1"
RESULTS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""))


def P(c, ip, xff=None, password="wrong-password"):
    headers = {"X-Forwarded-For": xff} if xff else {}
    return c.post("/api/login", json={"password": password},
                  environ_base={"REMOTE_ADDR": ip}, headers=headers)


def main():
    pw = panel._ensure_admin_password()
    assert pw, "admin password not generated"
    c = panel.app.test_client()

    if not TRUSTED:
        # --- default: XFF ignored, lock keys on the connection IP ---
        for _ in range(5):
            r = P(c, "127.0.0.1", xff="1.2.3.4")
        cell("T0-01 5 wrong logins with forged XFF -> 5th still 401",
             r.status_code == 401, str(r.status_code))
        r = P(c, "127.0.0.1", xff="9.9.9.9")
        cell("T0-02 6th wrong login (different forged XFF) -> 429: XFF ignored, lock is on 127.0.0.1",
             r.status_code == 429 and "Retry-After" in r.headers,
             f"{r.status_code} {r.headers.get('Retry-After')}")
        r = P(c, "10.9.9.9", password=pw)
        cell("T0-03 correct login from another connection IP -> 200",
             r.status_code == 200, str(r.status_code))
        secure = "Secure" in (r.headers.get("Set-Cookie") or "")
        cell("T0-04 OVPN_PANEL_HTTPS=0 -> session cookie has NO Secure flag",
             not secure, r.headers.get("Set-Cookie") or "")
    else:
        # --- trusted proxy: ProxyFix takes the LAST XFF value ---
        for _ in range(5):
            r = P(c, "127.0.0.1", xff="1.2.3.4")
        cell("T1-01 5 wrong logins with XFF 1.2.3.4 -> 5th still 401",
             r.status_code == 401, str(r.status_code))
        r = P(c, "127.0.0.1", xff="1.2.3.4")
        cell("T1-02 6th wrong login, same XFF -> 429: lock follows the forged IP",
             r.status_code == 429 and "Retry-After" in r.headers,
             f"{r.status_code} {r.headers.get('Retry-After')}")
        r = P(c, "127.0.0.1", xff="5.6.7.8")
        cell("T1-03 wrong login with a ROTATED forged XFF -> 401 (lock evaded: bypass)",
             r.status_code == 401, str(r.status_code))
        for _ in range(4):
            r = P(c, "127.0.0.1", xff="5.6.7.8")
        r = P(c, "127.0.0.1", xff="5.6.7.8")
        cell("T1-04 6th wrong login under the rotated XFF -> 429 (counting is per forged IP)",
             r.status_code == 429, str(r.status_code))
        r = P(c, "127.0.0.1", xff="1.2.3.4, 9.9.9.9")
        cell("T1-05 XFF '1.2.3.4, 9.9.9.9' while 1.2.3.4 is locked -> 401 (last hop wins, 9.9.9.9 is the counted IP)",
             r.status_code == 401, str(r.status_code))
        r = P(c, "127.0.0.1", xff="9.9.9.9")
        cell("T1-06 2nd wrong login under 9.9.9.9 -> 401 (it counted exactly once from T1-05)",
             r.status_code == 401, str(r.status_code))
        r = P(c, "10.9.9.9", password=pw)
        cell("T1-07 correct login from another connection IP -> 200",
             r.status_code == 200, str(r.status_code))
        secure = "Secure" in (r.headers.get("Set-Cookie") or "")
        cell("T1-08 OVPN_PANEL_HTTPS=1 -> session cookie HAS Secure flag",
             secure, r.headers.get("Set-Cookie") or "")

    fails = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"R35 ProxyFix/XFF: {len(RESULTS) - fails} passed, {fails} failed "
          f"(TRUSTED_PROXY={'1' if TRUSTED else '0'}, PANEL_HTTPS={'1' if HTTPS else '0'})")
    return fails


if __name__ == "__main__":
    sys.exit(main())

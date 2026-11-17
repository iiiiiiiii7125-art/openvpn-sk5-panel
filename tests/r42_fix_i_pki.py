#!/usr/bin/env python3
"""R42 Fix-I probe — PKI family fixes (AUDIT-R42-F1 findings).

Drives the product code against REAL toolchains (easy-rsa 3.1.7,
OpenVPN 2.4.12 / 2.6.14, real openssl) in scratch dirs. Reuses the
Fix-A probe's toolchain bootstrap (tests/r41_fix_a_pki.py, same
sha256 pins, cached in /tmp/r41a/toolchain).

Cells assert the FIXED behavior, so every I-cell FAILS on the
baseline 88b5891 and PASSES on the Fix-I tip (negative control):
  I1  legacy revoke: user stays in list_users as revoked (tombstone)
  I2  second revoke of a tombstoned legacy user: AlreadyRevoked (409)
  I3  re-create after revoke: valid, non-legacy; tombstone cleared
  I4  revoke_user blocks while the create flock is held (F1-6)
  I5  build_server_cert regenerates an EXPIRED server cert (F1-3)
  I6  renew_server_cert forces regeneration, CA + clients untouched
  I7  init_pki on a junk dir: junk survives in a sibling backup (F1-5)
  I7b easyrsa.sh init directly on a junk dir: same (shell safety net)
  I8  shipped .ovpn has no data-ciphers; parses under 2.4.12 (F1-2)
  I9  panel DELETE revoke endpoint restarts the daemon (F1-1)
  I10 panel DELETE revoke endpoint: restart failure is a loud 500
  I11 build_server_cert stays idempotent on a VALID cert (regression)
  I12 non-legacy revoke still lists revoked; second revoke 409

Run from the repo root: python3 tests/r42_fix_i_pki.py
Exit code = FAIL count. The Flask cells (I9/I10) need a venv with
Flask+bcrypt: pass R42FIXI_VENV=/path/to/venv (default
/tmp/r41-l5-venv); if the venv is missing the cells SKIP. The panel
env dirs come from R42FIXI_DATA / R42FIXI_SK5 (fresh temp dirs by
default) -- the probe sets OPENVPN_CA_DIR/OPENVPN_SERVER_DIR to its
own fixture dirs before importing the panel app.
"""
import fcntl
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TREE / "tests"))
sys.path.insert(0, str(TREE / "core"))
sys.path.insert(0, str(TREE / "agent"))
sys.path.insert(0, str(TREE / "egress"))

import r41_fix_a_pki as A  # noqa: E402  (toolchain bootstrap, pinned pins)

WORK = Path(tempfile.mkdtemp(prefix="r42fixi-"))
RESULTS = []
SKIPS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name
          + (" | " + str(detail)[:400] if detail else ""), flush=True)


def skip(name, why):
    SKIPS.append(name)
    print("SKIP " + name + " | " + why, flush=True)


def run(cmd, timeout=120, **kw):
    return A.run(cmd, timeout=timeout, **kw)


def sha256_file(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_legacy_user(ca, name):
    """Sign a client cert with CN=OpenVPN-CA (pre-BUG-7 shape)."""
    run([A.easyrsa_bin(TC, "3.1.7"), "--batch", "gen-req", name, "nopass"],
        timeout=120, stdin=subprocess.DEVNULL,
        env={**os.environ, "EASYRSA_PKI": str(ca / "pki"),
             "EASYRSA_BATCH": "1", "EASYRSA_REQ_CN": "OpenVPN-CA"})
    run([A.easyrsa_bin(TC, "3.1.7"), "--batch", "sign-req", "client", name],
        timeout=120, stdin=subprocess.DEVNULL,
        env={**os.environ, "EASYRSA_PKI": str(ca / "pki"),
             "EASYRSA_BATCH": "1"})


TC = None


def main():
    global TC
    _dn = open(os.devnull, "rb")
    os.dup2(_dn.fileno(), 0)
    TC = A.bootstrap_toolchain()
    if TC is None:
        print("SKIP: toolchain unavailable")
        return 0
    os.environ["PATH"] = (str(TC["ovpn2614"] / "usr/sbin") + ":"
                          + os.environ.get("PATH", ""))
    os.environ["LD_LIBRARY_PATH"] = A.ovpn_env(TC, "2.6.14")["LD_LIBRARY_PATH"]
    os.environ["EASYRSA_BIN"] = A.easyrsa_bin(TC, "3.1.7")

    # openvpn_manager captures OPENVPN_CA_DIR/OPENVPN_SERVER_DIR into
    # DEFAULT_* at import time, so the endpoint fixture dirs must be
    # on the environment BEFORE importing it. All other om calls in
    # this probe pass explicit dirs; only the panel endpoint (which
    # calls revoke_user(name) with no dirs) uses the default.
    os.environ["OPENVPN_CA_DIR"] = str(WORK / "ca9")
    os.environ["OPENVPN_SERVER_DIR"] = str(WORK / "srv9")

    import openvpn_manager as om  # noqa: E402

    print(f"work dir: {WORK}", flush=True)

    # ---- fixture PKI 1: full set + users + legacy carol ----
    ca1 = WORK / "ca1"
    srv1 = WORK / "srv1"
    with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
        om.init_pki(ca1)
        om.build_server_cert(ca1, srv1)
        om.create_user("alice", ca1, srv1, server_ip="203.0.113.7")
        om.create_user("bob", ca1, srv1, server_ip="203.0.113.7")
        make_legacy_user(ca1, "carol")
    users1 = {u["name"]: u for u in om.list_users(ca1)}
    cell("I0 fixture: legacy carol visible pre-revoke",
         users1.get("carol", {}).get("status") == "valid"
         and users1.get("carol", {}).get("legacy") is True,
         f"carol={users1.get('carol')} users={sorted(users1)}")

    # ---- I1/I2/I3: tombstone ----
    with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
        rev = om.revoke_user("carol", ca1, srv1)
    users_after = {u["name"]: u for u in om.list_users(ca1)}
    carol = users_after.get("carol", {})
    cell("I1 legacy revoke: user STAYS listed as revoked (tombstone)",
         carol.get("status") == "revoked" and carol.get("legacy") is True
         and rev.get("status") == "revoked",
         f"revoke={rev} carol={carol} users={sorted(users_after)}")
    try:
        om.revoke_user("carol", ca1, srv1)
        second = "no-raise"
    except Exception as e:  # noqa: BLE001
        second = f"{type(e).__name__}: {e}"
    cell("I2 second revoke of tombstoned legacy: 409 AlreadyRevoked",
         "UserAlreadyRevokedError" in second, f"second-revoke={second}")
    try:
        with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
            om.create_user("carol", ca1, srv1, server_ip="203.0.113.7")
        carol2 = {u["name"]: u for u in om.list_users(ca1)}.get("carol", {})
        recreated = (carol2.get("status") == "valid"
                     and carol2.get("legacy") is False)
        recreate_err = ""
    except Exception as e:  # noqa: BLE001
        recreated = False
        recreate_err = f"{type(e).__name__}: {e}"
    cell("I3 re-create of tombstoned legacy works; tombstone cleared",
         recreated, f"carol2={carol2} err={recreate_err}")

    # ---- I12: non-legacy revoke (tombstone redundant but harmless) ----
    with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
        om.revoke_user("alice", ca1, srv1)
    alice = {u["name"]: u for u in om.list_users(ca1)}.get("alice", {})
    try:
        om.revoke_user("alice", ca1, srv1)
        second_a = "no-raise"
    except Exception as e:  # noqa: BLE001
        second_a = f"{type(e).__name__}: {e}"
    cell("I12 non-legacy revoke lists revoked; second revoke 409",
         alice.get("status") == "revoked"
         and "UserAlreadyRevokedError" in second_a,
         f"alice={alice} second={second_a}")

    # ---- I4: revoke blocks on the create flock ----
    lock_holder = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl, time, sys; fd = open(sys.argv[1], 'w'); "
         "fcntl.flock(fd, fcntl.LOCK_EX); time.sleep(4)",
         str(ca1 / "pki" / ".create_user.lock")])
    time.sleep(1.0)  # let the holder acquire
    t0 = time.time()
    try:
        with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
            om.revoke_user("bob", ca1, srv1)
        revoke_dt = time.time() - t0
        revoke_ok = True
        revoke_err = ""
    except Exception as e:  # noqa: BLE001
        revoke_dt = time.time() - t0
        revoke_ok = False
        revoke_err = f"{type(e).__name__}: {e}"
    lock_holder.wait()
    cell("I4 revoke_user WAITS for the create flock (mutual exclusion)",
         revoke_ok and revoke_dt >= 2.5,
         f"ok={revoke_ok} dt={revoke_dt:.1f}s err={revoke_err}")

    # ---- I5: expired server cert is regenerated ----
    ca3 = WORK / "ca3"
    srv3 = WORK / "srv3"
    with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
        om.init_pki(ca3)
        om.build_server_cert(ca3, srv3)
    key3 = ca3 / "pki" / "private" / "server.key"
    csr3 = WORK / "server3.csr"
    crt3 = ca3 / "pki" / "issued" / "server.crt"
    run(["openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key3), "-out", str(csr3), "-subj", "/CN=server"],
        timeout=60)
    q = run(["openssl", "x509", "-req", "-in", str(csr3),
             "-CA", str(ca3 / "pki" / "ca.crt"),
             "-CAkey", str(ca3 / "pki" / "private" / "ca.key"),
             "-CAcreateserial", "-out", str(crt3), "-days", "0"],
            timeout=60)
    time.sleep(2)  # let a -days 0 cert cross into expired
    chk = run(["openssl", "x509", "-noout", "-checkend", "0", "-in", str(crt3)],
              timeout=30)
    expired_hash = sha256_file(crt3)
    if q.returncode == 0 and chk.returncode != 0:
        try:
            with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
                out = om.build_server_cert(ca3, srv3)
        except Exception as e:  # noqa: BLE001
            cell("I5 expired server cert is REGENERATED (backup + new cert)",
                 False, f"build_server_cert raised: {type(e).__name__}: {str(e)[:300]}")
            out = None
        if out is not None:
            after = sha256_file(crt3)
            bk = Path(out.get("backup_dir", "")) if out.get("backup_dir") else None
            bk_ok = (bk is not None and (bk / "server.crt").exists()
                     and sha256_file(bk / "server.crt") == expired_hash)
            chk2 = run(["openssl", "x509", "-noout", "-checkend", "0",
                        "-in", str(crt3)], timeout=30)
            ver = run(["openssl", "verify", "-CAfile",
                       str(ca3 / "pki" / "ca.crt"), str(crt3)], timeout=30)
            cell("I5 expired server cert is REGENERATED (backup + new cert)",
                 after != expired_hash and out.get("renewed_expired") == "true"
                 and bk_ok and chk2.returncode == 0 and ver.returncode == 0,
                 f"hash-changed={after != expired_hash} marker={out.get('renewed_expired')} "
                 f"backup-ok={bk_ok} checkend-rc={chk2.returncode} verify-rc={ver.returncode}")
    else:
        skip("I5 expired server cert is regenerated",
             f"could not craft expired cert: x509-rc={q.returncode} checkend-rc={chk.returncode}")

    # ---- I11: idempotent on a VALID cert (regression guard) ----
    h_before = sha256_file(ca3 / "pki" / "issued" / "server.crt")
    with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
        out11 = om.build_server_cert(ca3, srv3)
    h_after = sha256_file(ca3 / "pki" / "issued" / "server.crt")
    cell("I11 build_server_cert stays idempotent on a VALID cert",
         h_before == h_after and "backup_dir" not in out11
         and "renewed_expired" not in out11,
         f"hash-same={h_before == h_after} keys={sorted(out11)}")

    # ---- I6: renew_server_cert forces regeneration, CA untouched ----
    ca6 = WORK / "ca6"
    srv6 = WORK / "srv6"
    with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
        om.init_pki(ca6)
        om.build_server_cert(ca6, srv6)
        om.create_user("alice", ca6, srv6, server_ip="203.0.113.7")
    ca_hash_before = sha256_file(ca6 / "pki" / "ca.crt")
    srv_hash_before = sha256_file(ca6 / "pki" / "issued" / "server.crt")
    try:
        with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
            out6 = om.renew_server_cert(ca6, srv6)
        renew_err = ""
    except Exception as e:  # noqa: BLE001
        out6 = {}
        renew_err = f"{type(e).__name__}: {str(e)[:200]}"
    srv_hash_after = sha256_file(ca6 / "pki" / "issued" / "server.crt")
    alice6 = {u["name"]: u for u in om.list_users(ca6)}.get("alice", {})
    cell("I6 renew_server_cert regenerates server pair; CA + clients kept",
         not renew_err and srv_hash_after != srv_hash_before
         and sha256_file(ca6 / "pki" / "ca.crt") == ca_hash_before
         and alice6.get("status") == "valid"
         and Path(out6.get("backup_dir", "")).exists(),
         f"srv-changed={srv_hash_after != srv_hash_before} "
         f"ca-same={sha256_file(ca6 / 'pki' / 'ca.crt') == ca_hash_before} "
         f"alice={alice6.get('status')} backup={out6.get('backup_dir')} "
         f"err={renew_err}")

    # ---- I7/I7b: init on a junk dir moves it aside ----
    ca7 = WORK / "ca7"
    (ca7 / "pki").mkdir(parents=True)
    (ca7 / "pki" / "junk.txt").write_text("operator leftovers\n")
    (ca7 / "pki" / "stray-dir").mkdir()
    try:
        with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
            om.init_pki(ca7)
        junk_bks = [d for d in ca7.iterdir()
                    if d.name.startswith(".pki-backup-")
                    and (d / "junk.txt").exists()]
        i7_ok = bool(junk_bks) and (ca7 / "pki" / "ca.crt").exists() \
            and not (ca7 / "pki" / "junk.txt").exists()
        i7_detail = f"backups={[d.name for d in junk_bks]}"
    except Exception as e:  # noqa: BLE001
        i7_ok = False
        i7_detail = f"{type(e).__name__}: {str(e)[:240]}"
    cell("I7 init_pki on junk dir: junk survives in a sibling backup",
         i7_ok, i7_detail)
    ca8 = WORK / "ca8"
    (ca8 / "pki").mkdir(parents=True)
    (ca8 / "pki" / "junk2.txt").write_text("direct-call leftovers\n")
    q8 = run(["bash", str(TREE / "core" / "easyrsa.sh"), "init", str(ca8)],
             timeout=180,
             env={**os.environ, "EASYRSA_BIN": A.easyrsa_bin(TC, "3.1.7")})
    junk_bks8 = [d for d in ca8.iterdir()
                 if d.name.startswith(".pki-backup-")
                 and (d / "junk2.txt").exists()]
    cell("I7b easyrsa.sh init directly on junk dir: same safety net",
         q8.returncode == 0 and bool(junk_bks8)
         and (ca8 / "pki" / "ca.crt").exists(),
         f"rc={q8.returncode} backups={[d.name for d in junk_bks8]} "
         f"err={(q8.stderr or '')[:200]}")

    # ---- I8: client template has no data-ciphers ----
    with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
        ovpn_i8 = om.create_user("i8user", ca1, srv1, server_ip="203.0.113.7")
    f_i8 = WORK / "i8.ovpn"
    f_i8.write_text(ovpn_i8)

    def ovpn_parse(binary_path, cfg):
        ver = "2.4.12" if "ovpn2412" in str(binary_path) else "2.6.14"
        env = {**os.environ, **A.ovpn_env(TC, ver)}
        try:
            p = subprocess.run([str(binary_path), "--config", str(cfg)],
                               capture_output=True, text=True, timeout=15,
                               env=env, stdin=subprocess.DEVNULL)
            out = p.stdout + p.stderr
        except subprocess.TimeoutExpired as e:
            def _dec(x):
                if x is None:
                    return ""
                if isinstance(x, bytes):
                    return x.decode("utf-8", "replace")
                return x
            out = _dec(e.stdout) + _dec(e.stderr)
        return out

    has_dc = any(ln.startswith("data-ciphers") for ln in ovpn_i8.splitlines())
    out2412 = ovpn_parse(TC["ovpn2412"] / "usr/sbin" / "openvpn", f_i8)
    out2614 = ovpn_parse(TC["ovpn2614"] / "usr/sbin" / "openvpn", f_i8)
    cell("I8 shipped .ovpn has no data-ciphers; parses under 2.4.12",
         not has_dc and "Unrecognized option" not in out2412,
         f"has-data-ciphers={has_dc} out2412={out2412.strip()[:200]!r}")
    cell("I8b same .ovpn parses under 2.6.14 (control)",
         "Unrecognized option" not in out2614,
         f"out2614={out2614.strip()[:200]!r}")

    # ---- I9/I10: panel DELETE revoke endpoint restarts the daemon ----
    venv = Path(os.environ.get("R42FIXI_VENV", "/tmp/r41-l5-venv"))
    site = venv / "lib" / "python3.12" / "site-packages"
    if not (site / "flask").exists():
        skip("I9 panel DELETE revoke restarts the daemon", "no Flask venv")
        skip("I10 panel DELETE revoke: restart failure is a loud 500",
             "no Flask venv")
    else:
        sys.path.insert(0, str(TREE / "panel"))
        data = Path(os.environ.get("R42FIXI_DATA",
                                   tempfile.mkdtemp(prefix="r42fixi-data-")))
        sk5cfg = Path(os.environ.get(
            "R42FIXI_SK5", tempfile.mkdtemp(prefix="r42fixi-sk5-")))
        data.mkdir(parents=True, exist_ok=True)
        sk5cfg.mkdir(parents=True, exist_ok=True)
        os.environ["OVPN_PANEL_DATA_DIR"] = str(data)
        os.environ["OVPN_PANEL_SECRET_PATH"] = str(data / "secret.key")
        os.environ["OVPN_SK5_CONFIG_DIR"] = str(sk5cfg)
        # Fixture PKI for the endpoint: fresh CA + one normal user.
        ca9 = WORK / "ca9"
        srv9 = WORK / "srv9"
        with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
            om.init_pki(ca9)
            om.build_server_cert(ca9, srv9)
            om.create_user("dave", ca9, srv9, server_ip="203.0.113.7")
        os.environ["OPENVPN_CA_DIR"] = str(ca9)
        os.environ["OPENVPN_SERVER_DIR"] = str(srv9)
        sys.path.insert(0, str(site))
        import app as panel  # noqa: E402
        # Keep the generated admin password inside the scratch data
        # dir: _ensure_admin_password() otherwise writes the hardcoded
        # /etc/openvpn-sk5-panel/admin.pass (sandbox /etc is not
        # reliably shared across exec calls, so a later check cannot
        # prove where it landed).
        panel.ADMIN_PASS_PATH = str(data / "admin.pass")
        pw = panel._ensure_admin_password()
        if pw is None:
            pw = (data / "admin.pass").read_text().strip()
        client = panel.app.test_client()
        r = client.post("/api/login", json={"password": pw})
        logged_in = r.status_code == 200
        cell("I9a panel login works (harness)", logged_in,
             f"login={r.status_code}")
        if logged_in:
            calls = []
            real_restart = panel.restart_server
            real_status = panel.server_status

            def _stub_restart():
                calls.append("restart")
                return {"running": True}

            # R44-L5-F4: the endpoint now checks server_status()
            # first and skips the restart when the daemon is
            # stopped. These cells assert the running-daemon case,
            # so stub the status to running alongside the restart;
            # the stopped case is covered with a real fake daemon
            # by tests/r44_l5_state.py (S2d-3).
            panel.restart_server = _stub_restart
            panel.server_status = lambda: {"running": True}
            try:
                r = client.delete("/api/openvpn/users/dave")
                d = r.get_json() or {}
            finally:
                panel.restart_server = real_restart
                panel.server_status = real_status
            cell("I9 panel DELETE revoke restarts the daemon",
                 r.status_code == 200 and calls == ["restart"]
                 and d.get("needs_restart") is False
                 and d.get("restarted") is True,
                 f"status={r.status_code} calls={calls} body={d}")
            r = client.delete("/api/openvpn/users/dave")
            d = r.get_json() or {}
            cell("I9b second DELETE via panel is 409 (tombstone)",
                 r.status_code == 409, f"status={r.status_code} body={d}")

            def _boom_restart():
                raise om.OpenVPNError("systemctl restart failed (stub)")

            panel.restart_server = _boom_restart
            panel.server_status = lambda: {"running": True}
            try:
                # Re-create dave so there is something to revoke.
                try:
                    with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
                        om.create_user("dave", ca9, srv9,
                                       server_ip="203.0.113.7")
                    recreate_err = ""
                except Exception as e:  # noqa: BLE001
                    recreate_err = f"{type(e).__name__}: {str(e)[:200]}"
                r = client.delete("/api/openvpn/users/dave")
                d = r.get_json() or {}
            finally:
                panel.restart_server = real_restart
                panel.server_status = real_status
            cell("I10 panel DELETE revoke: restart failure is a loud 500",
                 not recreate_err and r.status_code == 500
                 and d.get("needs_restart") is True
                 and "重启" in (d.get("error") or ""),
                 f"status={r.status_code} body={d} recreate_err={recreate_err}")

    fails = [n for n, ok, _ in RESULTS if not ok]
    print(f"\nTOTAL {len(RESULTS)} cells, FAIL {len(fails)}: {fails}"
          + (f" | SKIP {SKIPS}" if SKIPS else ""))
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())

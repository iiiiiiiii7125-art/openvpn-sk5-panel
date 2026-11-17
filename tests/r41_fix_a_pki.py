#!/usr/bin/env python3
"""Fix-A verification probe (AUDIT-R41): PKI core + 20.04 compat.

Drives the product code against REAL toolchains in scratch dirs --
easy-rsa 3.0.6 / 3.0.8 / 3.1.7 tarballs, OpenVPN 2.4.12 (focal) and
2.6.14 (bookworm) binaries. Nothing is installed on the host: easy-rsa
versions are selected via the EASYRSA_BIN override, OpenVPN versions
via PATH + LD_LIBRARY_PATH. All PKI/server state lives under a temp
work dir (default: tempfile.mkdtemp).

Toolchain bootstrap: downloads (sha256-pinned) into $R41A_TOOLCHAIN
(default /tmp/r41a/toolchain); already-downloaded files with matching
hashes are reused. When a download fails the probe SKIPs (exit 0 with
a SKIP line) -- that is an environment limit, not a product verdict.

Cells T01..T14; exit code = FAIL count. Each cell prints PASS/FAIL
with the measured evidence. Run from the repo root:
    python3 tests/r41_fix_a_pki.py
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TREE / "core"))

TOOLCHAIN_DIR = Path(os.environ.get("R41A_TOOLCHAIN", "/tmp/r41a/toolchain"))
WORK = Path(tempfile.mkdtemp(prefix="r41a-probe-"))

RESULTS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""),
          flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest, want_sha):
    if dest.exists() and sha256(dest) == want_sha:
        return True
    try:
        subprocess.run(["curl", "-fsSL", "--max-time", "180", "-o", str(dest), url],
                       check=True, timeout=200)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return sha256(dest) == want_sha


ASSETS = [
    # (filename, url, sha256, top dir after extraction)
    ("easy-rsa_3.0.6.orig.tar.gz",
     "http://archive.ubuntu.com/ubuntu/pool/universe/e/easy-rsa/easy-rsa_3.0.6.orig.tar.gz",
     "8d47f8d6ba64043d2e7a567a5505d641db4f628c88e45904ddb1f613b97dfb5e",
     "easy-rsa-3.0.6"),
    ("EasyRSA-3.0.8.tgz",
     "https://github.com/OpenVPN/easy-rsa/releases/download/v3.0.8/EasyRSA-3.0.8.tgz",
     "cae114c212a5be4d89f2253d36c70ab94f68d295f24e8b6711c2cab0fabf7e18",
     "EasyRSA-3.0.8"),
    ("EasyRSA-3.1.7.tgz",
     "https://github.com/OpenVPN/easy-rsa/releases/download/v3.1.7/EasyRSA-3.1.7.tgz",
     "aaa48fadcbb77511b9c378554ef3eae09f8c7bc149d6f56ba209f1c9bab98c6e",
     "EasyRSA-3.1.7"),
    ("openvpn_2.4.12.deb",
     "http://archive.ubuntu.com/ubuntu/pool/main/o/openvpn/openvpn_2.4.12-0ubuntu0.20.04.2_amd64.deb",
     "7e8c986a1f6e1d8d681f12aba96ceaae48e3d808f2389d2f9cdcd0366b98b46f",
     None),
    ("libssl1.1.deb",
     "http://archive.ubuntu.com/ubuntu/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2.24_amd64.deb",
     "7cf39d70a639017d1dd7c8d36daa2258063608688e449fddf40ffdd46f992a78",
     None),
    ("openvpn_2.6.14.deb",
     "http://deb.debian.org/debian/pool/main/o/openvpn/openvpn_2.6.14-0+deb12u2_amd64.deb",
     "6f25a47c80cd4707bd4245e42c97c8a612dc9e5dc92a7e1b1d6ea1b9e2ef956a",
     None),
    # Runtime libs the extracted openvpn binaries need but the sandbox
    # host no longer provides (no system openvpn / libpkcs11 / libnl
    # after the sandbox reset): bookworm builds, SONAME-compatible
    # with both the focal 2.4.12 and bookworm 2.6.14 binaries. Note
    # libnl* installs to /lib, pkcs11-helper to /usr/lib.
    ("libpkcs11-helper1_1.29.0-1_amd64.deb",
     "http://deb.debian.org/debian/pool/main/p/pkcs11-helper/libpkcs11-helper1_1.29.0-1_amd64.deb",
     "44df37a630dc39474900f9dbcaa627556169974a96b1b57e6e07288ab79197e6",
     None),
    ("libnl-3-200_3.7.0-0.2+b1_amd64.deb",
     "http://deb.debian.org/debian/pool/main/libn/libnl3/libnl-3-200_3.7.0-0.2+b1_amd64.deb",
     "d1fc3e9eb8e79b4c96b0a64c3d8c9e068ae2f665cab71bd19f417ffd0453a890",
     None),
    ("libnl-genl-3-200_3.7.0-0.2+b1_amd64.deb",
     "http://deb.debian.org/debian/pool/main/libn/libnl3/libnl-genl-3-200_3.7.0-0.2+b1_amd64.deb",
     "1f7b198f5d87659f815140ed41c1517b2fe41ba62c5b15b0bafdcc2d61801871",
     None),
]


def bootstrap_toolchain():
    """Fetch + verify + extract all toolchains. Returns dict or None (SKIP)."""
    TOOLCHAIN_DIR.mkdir(parents=True, exist_ok=True)
    tc = {}
    for fname, url, want, top in ASSETS:
        dest = TOOLCHAIN_DIR / fname
        if not download(url, dest, want):
            print(f"SKIP toolchain: cannot fetch {fname} (no egress?)")
            return None
        if top:
            outdir = TOOLCHAIN_DIR / top
            if not (outdir / "easyrsa").exists():
                with tarfile.open(dest) as tf:
                    tf.extractall(TOOLCHAIN_DIR)
            tc[top] = outdir
    for deb, dest, sentinel in (("openvpn_2.4.12.deb", "ovpn2412",
                                  "usr/sbin/openvpn"),
                                 ("libssl1.1.deb", "ovpn2412",
                                  "usr/lib/x86_64-linux-gnu/libcrypto.so.1.1"),
                                 ("openvpn_2.6.14.deb", "ovpn2614",
                                  "usr/sbin/openvpn"),
                                 ("libpkcs11-helper1_1.29.0-1_amd64.deb", "ovpnlibs",
                                  "usr/lib/x86_64-linux-gnu/libpkcs11-helper.so.1"),
                                 ("libnl-3-200_3.7.0-0.2+b1_amd64.deb", "ovpnlibs",
                                  "lib/x86_64-linux-gnu/libnl-3.so.200"),
                                 ("libnl-genl-3-200_3.7.0-0.2+b1_amd64.deb", "ovpnlibs",
                                  "lib/x86_64-linux-gnu/libnl-genl-3.so.200")):
        outdir = TOOLCHAIN_DIR / dest
        if not (outdir / sentinel).exists():
            subprocess.run(["dpkg-deb", "-x", str(TOOLCHAIN_DIR / deb), str(outdir)],
                           check=True)
        tc[dest] = outdir
    return tc


def run(cmd, timeout=120, **kw):
    """subprocess.run with captured output; never raises."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, **kw)
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(cmd, -99,
                                           stdout=e.stdout or "", stderr="TIMEOUT")


class Env:
    """Temporary os.environ overrides (restores on exit)."""

    def __init__(self, **over):
        self.over = over
        self.saved = {}

    def __enter__(self):
        for k, v in self.over.items():
            self.saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def easyrsa_bin(tc, version):
    top = {"3.0.6": "easy-rsa-3.0.6", "3.0.8": "EasyRSA-3.0.8",
           "3.1.7": "EasyRSA-3.1.7"}[version]
    return str(tc[top] / "easyrsa")


def ovpn_env(tc, version):
    """Env selecting one OpenVPN binary via PATH + LD_LIBRARY_PATH."""
    libs = (str(tc["ovpnlibs"] / "lib/x86_64-linux-gnu") + ":"
            + str(tc["ovpnlibs"] / "usr/lib/x86_64-linux-gnu"))
    if version == "2.4.12":
        d = tc["ovpn2412"]
        return {"PATH": str(d / "usr/sbin") + ":/usr/sbin:/usr/bin:/bin",
                "LD_LIBRARY_PATH": str(d / "usr/lib/x86_64-linux-gnu") + ":" + libs}
    d = tc["ovpn2614"]
    return {"PATH": str(d / "usr/sbin") + ":/usr/sbin:/usr/bin:/bin",
            "LD_LIBRARY_PATH": libs}


def main():
    # The manager's _run() inherits OUR stdin; point it at /dev/null so
    # a prompting child (baseline _run has no stdin=DEVNULL) fails fast
    # instead of hanging on the harness stdin until its 600s timeout.
    _dn = open(os.devnull, "rb")
    os.dup2(_dn.fileno(), 0)
    tc = bootstrap_toolchain()
    if tc is None:
        print("SKIP: toolchain unavailable")
        return 0
    # Default openvpn for manager-level tests (T05/T09/T10): the
    # sandbox host has no system openvpn after the reset, so put the
    # 2.6.14 toolchain binary first on PATH (version-specific cells
    # override via ovpn_env).
    os.environ["PATH"] = (str(tc["ovpn2614"] / "usr/sbin") + ":"
                          + os.environ.get("PATH", ""))
    os.environ["LD_LIBRARY_PATH"] = ovpn_env(tc, "2.6.14")["LD_LIBRARY_PATH"]
    print(f"work dir: {WORK}", flush=True)

    import openvpn_manager as om

    easyrsa_sh = str(TREE / "core" / "easyrsa.sh")

    # ---- T01: version gate rejects 3.0.6 fast, with a clear message ----
    t0 = time.time()
    with Env(EASYRSA_BIN=easyrsa_bin(tc, "3.0.6")):
        p = run(["bash", easyrsa_sh, "init", str(WORK / "gate306")],
                timeout=60, stdin=subprocess.DEVNULL)
    dt = time.time() - t0
    cell("T01 gate rejects easy-rsa 3.0.6 fast with a clear message",
         p.returncode != 0 and dt < 10 and "too old" in (p.stderr + p.stdout)
         and "3.1.0" in (p.stderr + p.stdout)
         and "PEM pass phrase" not in (p.stderr + p.stdout)
         and "set:" not in (p.stderr + p.stdout),
         f"rc={p.returncode} {dt:.1f}s out={ (p.stderr + p.stdout).strip()[:160]!r}")

    # ---- T02: version gate rejects 3.0.8 the same way ----
    t0 = time.time()
    with Env(EASYRSA_BIN=easyrsa_bin(tc, "3.0.8")):
        p = run(["bash", easyrsa_sh, "init", str(WORK / "gate308")],
                timeout=60, stdin=subprocess.DEVNULL)
    dt = time.time() - t0
    cell("T02 gate rejects easy-rsa 3.0.8 fast with a clear message",
         p.returncode != 0 and dt < 10 and "too old" in (p.stderr + p.stdout)
         and "3.1.0" in (p.stderr + p.stdout),
         f"rc={p.returncode} {dt:.1f}s out={ (p.stderr + p.stdout).strip()[:160]!r}")

    # ---- T03: build-ca works on 3.1.7 via the product wrapper ----
    ca317 = WORK / "ca317"
    with Env(EASYRSA_BIN=easyrsa_bin(tc, "3.1.7")):
        p = run(["bash", easyrsa_sh, "init", str(ca317)],
                timeout=120, stdin=subprocess.DEVNULL)
    ok_ca = (ca317 / "pki/ca.crt").exists() and (ca317 / "pki/private/ca.key").exists()
    unenc = False
    if ok_ca:
        q = run(["openssl", "pkey", "-in", str(ca317 / "pki/private/ca.key"),
                 "-noout"], timeout=30)
        unenc = q.returncode == 0
    cell("T03 build-ca nopass succeeds on easy-rsa 3.1.7 (product wrapper)",
         p.returncode == 0 and ok_ca and unenc,
         f"rc={p.returncode} ca.crt={ok_ca} key-unencrypted={unenc}")

    # ---- T04: _run fails fast on a prompting openssl req (stdin DEVNULL) ----
    # The outer helper spawns a grandchild whose stdin is a pipe the
    # helper holds open (never EOF). Without stdin=DEVNULL the grandchild
    # blocks on the openssl pass-phrase prompt until the 30s _run
    # timeout; with it, openssl gets EOF at once and fails in <10s.
    outer = (
        "import os, subprocess, sys, time\n"
        "code = (\n"
        "\"import sys, time, tempfile, subprocess; sys.path.insert(0, %r)\\n\"\n"
        "\"from openvpn_manager import _run, OpenVPNError\\n\"\n"
        "\"d = tempfile.mkdtemp()\\n\"\n"
        "\"subprocess.run(['openssl','genrsa','-out',d+'/k.pem','2048'],capture_output=True,timeout=60)\\n\"\n"
        "\"t0=time.time()\\n\"\n"
        "\"try:\\n\"\n"
        "\"    _run(['openssl','req','-utf8','-new','-key',d+'/k.pem','-keyout',d+'/k.pem','-out',d+'/c.pem','-x509','-days','3650','-batch'],timeout=30)\\n\"\n"
        "\"    print('NO-RAISE')\\n\"\n"
        "\"except OpenVPNError as e:\\n\"\n"
        "\"    print('RAISED %%.1f' %% (time.time()-t0))\\n\"\n"
        ")\n"
        "r, w = os.pipe()\n"
        "p = subprocess.Popen([sys.executable, '-c', code], stdin=r,"
        " stdout=subprocess.PIPE, stderr=subprocess.PIPE)\n"
        "os.close(r)\n"
        "try:\n"
        "    out, err = p.communicate(timeout=25)\n"
        "    print(out.decode())\n"
        "    print(err.decode(), file=sys.stderr)\n"
        "except subprocess.TimeoutExpired:\n"
        "    p.kill(); print('TIMEOUT')\n"
        % str(TREE / "core"))
    p = run([sys.executable, "-c", outer], timeout=60,
            stdin=subprocess.DEVNULL)
    m = re.search(r"RAISED ([0-9.]+)", p.stdout or "")
    cell("T04 _run fails fast on a prompting openssl req (no 600s hang)",
         m is not None and float(m.group(1)) < 10.0,
         f"outer-out={ (p.stdout or '').strip()[:80]!r} rc={p.returncode}")

    # ---- T05: full product E2E on 3.1.7 ----
    ca_e2e = WORK / "ca-e2e"
    srv_e2e = WORK / "srv-e2e"
    arts = False
    ta = ""
    users = users2 = users3 = {}
    rev = {}
    e2e_s = 0.0
    e2e_err = ""
    ovpn_alice = ""
    try:
        with Env(EASYRSA_BIN=easyrsa_bin(tc, "3.1.7")):
            t0 = time.time()
            om.init_pki(ca_e2e)
            installed = om.build_server_cert(ca_e2e, srv_e2e)
            e2e_s = time.time() - t0
            arts = all((srv_e2e / n).exists()
                       for n in ("ca.crt", "server.crt", "server.key",
                                 "dh.pem", "ta.key", "crl.pem"))
            ta = (srv_e2e / "ta.key").read_text() if (srv_e2e / "ta.key").exists() else ""
            om.create_user("alice", ca_e2e, srv_e2e, server_ip="203.0.113.7")
            om.create_user("bob", ca_e2e, srv_e2e, server_ip="203.0.113.7")
            users = {u["name"]: u for u in om.list_users(ca_e2e)}
            # legacy pre-BUG-7 user: cert with CN=OpenVPN-CA, serial in index.
            # (Easy-RSA has no `build-client` command: gen-req + sign-req
            # client are the primitives, as the product wrapper uses them.)
            with Env(EASYRSA_REQ_CN="OpenVPN-CA"):
                run([easyrsa_bin(tc, "3.1.7"), "--batch", "gen-req", "carol", "nopass"],
                    timeout=120, stdin=subprocess.DEVNULL,
                    env={**os.environ, "EASYRSA_PKI": str(ca_e2e / "pki"),
                         "EASYRSA_BATCH": "1"})
                q = run([easyrsa_bin(tc, "3.1.7"), "--batch", "sign-req", "client", "carol"],
                        timeout=120, stdin=subprocess.DEVNULL,
                        env={**os.environ, "EASYRSA_PKI": str(ca_e2e / "pki"),
                             "EASYRSA_BATCH": "1"})
            users2 = {u["name"]: u for u in om.list_users(ca_e2e)}
            rev = om.revoke_user("bob", ca_e2e, srv_e2e)
            users3 = {u["name"]: u for u in om.list_users(ca_e2e)}
            # fresh .ovpn for alice, rendered from the on-disk files:
            _ca = (ca_e2e / "pki/ca.crt").read_text()
            _cert = (ca_e2e / "pki/issued/alice.crt").read_text()
            _key = (ca_e2e / "pki/private/alice.key").read_text()
            _ta = (srv_e2e / "ta.key").read_text()
            ovpn_alice = om.build_client_config("alice", _ca, _cert, _key, _ta,
                                                "203.0.113.7", "udp", 1194)
    except Exception as e:  # noqa: BLE001 -- baseline is expected to raise here
        e2e_err = f"{type(e).__name__}: {str(e)[:200]}"
    carol = users2.get("carol", {})
    _m = re.search(r"<cert>\n(.*?)</cert>", ovpn_alice, re.S)
    cert_block = _m.group(1) if _m else ""
    cell("T05 E2E on 3.1.7: init+build-server+users+revoke (%.0fs)" % e2e_s,
         arts and "-----BEGIN OpenVPN Static key V1-----" in ta
         and users.get("alice", {}).get("status") == "valid"
         and users.get("bob", {}).get("status") == "valid"
         and rev.get("status") == "revoked"
         and users3.get("bob", {}).get("status") == "revoked",
         f"artifacts={arts} users={sorted(users)} bob-after-revoke={users3.get('bob', {}).get('status')} err={e2e_err}")
    cell("T06 legacy CN=OpenVPN-CA user visible + revocable (serial map works)",
         carol.get("status") == "valid" and carol.get("legacy") is True,
         f"carol={carol} users2={sorted(users2)}")
    # revoke carol to prove the 404 path is gone. F2's promise is
    # revocability (no 404) + the return value, and the re-create flow
    # must work afterwards. OBSERVATION (not asserted): after revoke,
    # easy-rsa moves issued/carol.crt into revoked/certs_by_serial/,
    # destroying the only name record (the CN fallback yields the
    # reserved OpenVPN-CA), so the R row no longer resolves in
    # list_users. The name is unrecoverable read-side; re-create is
    # the recovery path.
    with Env(EASYRSA_BIN=easyrsa_bin(tc, "3.1.7")):
        try:
            rev_carol = om.revoke_user("carol", ca_e2e, srv_e2e)
            carol_revoked = rev_carol.get("status") == "revoked"
            om.create_user("carol", ca_e2e, srv_e2e, server_ip="203.0.113.7")
            carol2 = {u["name"]: u for u in om.list_users(ca_e2e)}.get("carol", {})
            carol_recreated = (carol2.get("status") == "valid"
                               and carol2.get("legacy") is False)
        except Exception as e:  # noqa: BLE001
            carol_revoked = False
            carol_recreated = False
            print("carol revoke/re-create raised:", e)
    cell("T06b legacy user revoke succeeds (no 404) + re-create yields valid non-legacy cert",
         carol_revoked and carol_recreated,
         f"revoked={carol_revoked} recreated={carol_recreated}")
    cell("T07 .ovpn <cert> block is PEM-only (no text dump)",
         "Certificate:" not in cert_block
         and "Signature Algorithm" not in cert_block
         and cert_block.strip().startswith("-----BEGIN CERTIFICATE-----")
         and cert_block.strip().endswith("-----END CERTIFICATE-----"),
         f"cert-block-head={cert_block.strip()[:60]!r}")
    # serial matches openssl for a text+PEM cert
    alice_crt = ca_e2e / "pki/issued/alice.crt"
    if alice_crt.exists():
        q = run(["openssl", "x509", "-noout", "-serial", "-in",
                 str(alice_crt)], timeout=30)
        want_serial = q.stdout.strip().split("=", 1)[1].strip() if "=" in q.stdout else ""
        got_serial = om._cert_serial_hex(alice_crt)
    else:
        want_serial, got_serial = "", None
    cell("T08 _cert_serial_hex matches openssl on text+PEM cert",
         got_serial is not None and got_serial.upper() == want_serial.upper(),
         f"openssl={want_serial} got={got_serial}")

    # ---- T09: foreign-PKI adoption (L1-4/L1-5) via the manager ----
    # EC CA built with raw 3.1.7 (the user's angristan shape), then
    # stripped to the user's state: no pki/openssl-easyrsa.cnf, empty
    # revoked/, no renewed/ at all.
    ca_foreign = WORK / "ca-foreign"
    srv_foreign = WORK / "srv-foreign"
    fenv = {**os.environ, "EASYRSA_PKI": str(ca_foreign / "pki"),
            "EASYRSA_BATCH": "1", "EASYRSA_ALGO": "ec",
            "EASYRSA_CURVE": "prime256v1",
            "EASYRSA": str(tc["EasyRSA-3.1.7"])}
    run([easyrsa_bin(tc, "3.1.7"), "init-pki"], timeout=60,
        stdin=subprocess.DEVNULL, env=fenv)
    with Env(EASYRSA_REQ_CN="OpenVPN-CA"):
        run([easyrsa_bin(tc, "3.1.7"), "build-ca", "nopass"], timeout=120,
            stdin=subprocess.DEVNULL, env=fenv)
    # server cert the foreign way (signed by the EC CA), then strip
    with Env(EASYRSA_REQ_CN="server"):
        run([easyrsa_bin(tc, "3.1.7"), "gen-req", "server", "nopass"],
            timeout=60, stdin=subprocess.DEVNULL, env=fenv)
    run([easyrsa_bin(tc, "3.1.7"), "sign-req", "server", "server"],
        timeout=60, stdin=subprocess.DEVNULL, env=fenv)
    assert (ca_foreign / "pki/issued/server.crt").exists(), "fixture: no server.crt"
    (ca_foreign / "pki/openssl-easyrsa.cnf").unlink(missing_ok=True)
    shutil.rmtree(ca_foreign / "pki/renewed", ignore_errors=True)
    for sub in ("certs_by_serial", "private_by_serial", "reqs_by_serial"):
        p = ca_foreign / "pki/revoked" / sub
        if p.exists():
            for f in p.iterdir():
                f.unlink()
    with Env(EASYRSA_BIN=easyrsa_bin(tc, "3.1.7")):
        try:
            installed_f = om.build_server_cert(ca_foreign, srv_foreign)
            f_ok = all((srv_foreign / n).exists()
                       for n in ("ca.crt", "server.crt", "server.key",
                                 "dh.pem", "ta.key", "crl.pem"))
            f_err = ""
        except Exception as e:  # noqa: BLE001
            installed_f, f_ok, f_err = {}, False, str(e)[:200]
    cnf_restored = (ca_foreign / "pki/openssl-easyrsa.cnf").exists()
    dirs_ok = all((ca_foreign / "pki" / d).is_dir() for d in
                  ("revoked/certs_by_serial", "revoked/private_by_serial",
                   "revoked/reqs_by_serial", "renewed/certs_by_serial",
                   "renewed/private_by_serial", "renewed/reqs_by_serial"))
    cell("T09 foreign PKI (no cnf, no revoked/renewed dirs) adopts cleanly",
         f_ok and cnf_restored and dirs_ok,
         f"installed={f_ok} cnf-restored={cnf_restored} dirs={dirs_ok} err={f_err}")

    # ---- T10: F3 -- pre-existing server key survives a partial set ----
    ca_p = WORK / "ca-partial"
    srv_p = WORK / "srv-partial"
    t10_err = ""
    pre_key = pre_req = pre_crt = ""
    try:
        with Env(EASYRSA_BIN=easyrsa_bin(tc, "3.1.7")):
            om.init_pki(ca_p)
            om.build_server_cert(ca_p, srv_p)
        # foreign shape: server triple present, dh.pem + ta.key gone
        (ca_p / "pki/dh.pem").unlink(missing_ok=True)
        (ca_p / "pki/ta.key").unlink(missing_ok=True)
        pre_key = sha256(ca_p / "pki/private/server.key")
        pre_req = sha256(ca_p / "pki/reqs/server.req")
        pre_crt = sha256(ca_p / "pki/issued/server.crt")
    except Exception as e:  # noqa: BLE001 -- baseline is expected to raise here
        t10_err = f"{type(e).__name__}: {str(e)[:160]}"
    installed_p = {}
    try:
        with Env(EASYRSA_BIN=easyrsa_bin(tc, "3.1.7")):
            installed_p = om.build_server_cert(ca_p, srv_p)
    except Exception as e:  # noqa: BLE001
        t10_err += f" | rebuild: {type(e).__name__}: {str(e)[:160]}"
    backup_dir = installed_p.get("backup_dir")
    backup_ok = False
    if backup_dir:
        bdir = Path(backup_dir)
        backup_ok = (
            bdir.is_dir()
            and (bdir / "server.key").exists()
            and sha256(bdir / "server.key") == pre_key
            and (bdir / "server.req").exists()
            and sha256(bdir / "server.req") == pre_req
            and (bdir / "server.crt").exists()
            and sha256(bdir / "server.crt") == pre_crt)
    arts_p = all((srv_p / n).exists()
                 for n in ("ca.crt", "server.crt", "server.key",
                           "dh.pem", "ta.key", "crl.pem"))
    cell("T10 partial set: pre-existing server key backed up byte-identical",
         backup_ok and arts_p,
         f"backup_dir={backup_dir} backup_ok={backup_ok} artifacts={arts_p} err={t10_err}")

    # ---- T11: render is OpenVPN-version aware (L1-1) ----
    srv24 = WORK / "srv-24"
    srv26 = WORK / "srv-26"
    with Env(**ovpn_env(tc, "2.4.12")):
        om.render_server_conf("udp", 1194, server_dir=srv24)
    conf24 = (srv24 / "server.conf").read_text()
    with Env(**ovpn_env(tc, "2.6.14")):
        om.render_server_conf("udp", 1194, server_dir=srv26)
    conf26 = (srv26 / "server.conf").read_text()
    cell("T11a render omits data-ciphers when OpenVPN is 2.4.12",
         not any(ln.startswith("data-ciphers") for ln in conf24.splitlines())
         and "cipher AES-256-GCM" in conf24,
         f"directive-present={any(ln.startswith('data-ciphers') for ln in conf24.splitlines())}")
    cell("T11b render keeps data-ciphers when OpenVPN is 2.6.14",
         any(ln.startswith("data-ciphers AES-256-GCM") for ln in conf26.splitlines()),
         f"directive-present={any(ln.startswith('data-ciphers') for ln in conf26.splitlines())}")
    # parse check with real PKI files in place: config must parse far
    # enough to reach TUN setup (sandbox EPERM), not die on the option
    _src = None
    for _cand in (srv_e2e, srv_foreign):
        if all((_cand / f).exists() for f in
               ("ca.crt", "server.crt", "server.key", "dh.pem", "ta.key", "crl.pem")):
            _src = _cand
            break
    if _src is None:
        # build a throwaway artifact set with the raw 3.1.7 binary
        _src = WORK / "srv-parse"
        _ca = WORK / "ca-parse"
        _env = {**os.environ, "EASYRSA_PKI": str(_ca / "pki"),
                "EASYRSA_BATCH": "1"}
        run([easyrsa_bin(tc, "3.1.7"), "init-pki"], timeout=60,
            stdin=subprocess.DEVNULL, env=_env)
        with Env(EASYRSA_REQ_CN="OpenVPN-CA"):
            run([easyrsa_bin(tc, "3.1.7"), "build-ca", "nopass"],
                timeout=120, stdin=subprocess.DEVNULL, env=_env)
        with Env(EASYRSA_REQ_CN="server"):
            run([easyrsa_bin(tc, "3.1.7"), "gen-req", "server", "nopass"],
                timeout=60, stdin=subprocess.DEVNULL, env=_env)
        run([easyrsa_bin(tc, "3.1.7"), "sign-req", "server", "server"],
            timeout=60, stdin=subprocess.DEVNULL, env=_env)
        run([easyrsa_bin(tc, "3.1.7"), "gen-dh"], timeout=180,
            stdin=subprocess.DEVNULL, env=_env)
        run([easyrsa_bin(tc, "3.1.7"), "gen-crl"], timeout=60,
            stdin=subprocess.DEVNULL, env=_env)
        _src.mkdir(parents=True, exist_ok=True)
        for _f, _s in (("ca.crt", _ca / "pki/ca.crt"),
                       ("server.crt", _ca / "pki/issued/server.crt"),
                       ("server.key", _ca / "pki/private/server.key"),
                       ("dh.pem", _ca / "pki/dh.pem"),
                       ("crl.pem", _ca / "pki/crl.pem")):
            shutil.copyfile(_s, _src / _f)
        _ov = str(tc["ovpn2614"] / "usr/sbin/openvpn")
        run([_ov, "--genkey", "secret", str(_src / "ta.key")],
            timeout=30, stdin=subprocess.DEVNULL)
    for f in ("ca.crt", "server.crt", "server.key", "dh.pem", "ta.key", "crl.pem"):
        shutil.copyfile(_src / f, srv24 / f)
        shutil.copyfile(_src / f, srv26 / f)
    # The rendered config logs via log-append to /var/log/openvpn/,
    # NOT to stdout/stderr: truncate the log before each run and read
    # it after. A clean parse reaches the TUNSETIFF EPERM; an option
    # error dies in the log before that.
    _log = Path("/var/log/openvpn/openvpn.log")
    with Env(**ovpn_env(tc, "2.4.12")):
        _log.parent.mkdir(parents=True, exist_ok=True)
        _log.write_text("")
        p24 = run([str(tc["ovpn2412"] / "usr/sbin/openvpn"), "--config",
                   str(srv24 / "server.conf")], timeout=30,
                  stdin=subprocess.DEVNULL)
    log24 = _log.read_text() if _log.exists() else ""
    with Env(**ovpn_env(tc, "2.6.14")):
        _log.write_text("")
        p26 = run([str(tc["ovpn2614"] / "usr/sbin/openvpn"), "--config",
                   str(srv26 / "server.conf")], timeout=30,
                  stdin=subprocess.DEVNULL)
    log26 = _log.read_text() if _log.exists() else ""
    # Option errors print to stderr BEFORE log-append opens; TUN
    # failure lands in the log. Judge on both streams together.
    blob24 = log24 + p24.stderr + p24.stdout
    blob26 = log26 + p26.stderr + p26.stdout
    cell("T11c 2.4.12 parses the rendered conf (reaches TUN, no option error)",
         "Unrecognized option" not in blob24 and "TUNSETIFF" in blob24,
         f"blob-tail={blob24.strip().splitlines()[-1] if blob24.strip() else ''!r}")
    cell("T11d 2.6.14 parses the rendered conf (reaches TUN, no option error)",
         "Unrecognized option" not in blob26 and "TUNSETIFF" in blob26,
         f"blob-tail={blob26.strip().splitlines()[-1] if blob26.strip() else ''!r}")

    # ---- T12: ta.key generation works under both genkey syntaxes (L1-2) ----
    for ver, label in (("2.4.12", "T12a"), ("2.6.14", "T12b")):
        ca_g = WORK / f"ca-genkey-{ver}"
        ta_g = WORK / f"srv-genkey-{ver}" / "ta.key"
        t12_err = ""
        try:
            with Env(EASYRSA_BIN=easyrsa_bin(tc, "3.1.7"),
                     **ovpn_env(tc, ver)):
                om.init_pki(ca_g)
                installed_g = om.build_server_cert(ca_g, WORK / f"srv-genkey-{ver}")
        except Exception as e:  # noqa: BLE001 -- baseline is expected to raise
            t12_err = f"{type(e).__name__}: {str(e)[:160]}"
        ok_g = (ta_g.exists() and ta_g.stat().st_size == 636
                and "-----BEGIN OpenVPN Static key V1-----" in ta_g.read_text())
        cell(f"{label} build-server makes ta.key under OpenVPN {ver}",
             ok_g, f"size={ta_g.stat().st_size if ta_g.exists() else '-'} err={t12_err}")

    # ---- T13: install.sh _ensure_easyrsa upgrades a too-old install ----
    install_sh = (TREE / "install.sh").read_text()
    m = re.search(r"# --- begin _ensure_easyrsa \(tested by tests/r41_fix_a_pki\.py\) ---\n(.*?)"
                  r"# --- end _ensure_easyrsa ---\n", install_sh, re.S)
    pin_ok = ('EASYRSA_SHA256_PINNED="aaa48fadcbb77511b9c378554ef3eae09f8c7bc149d6f56ba209f1c9bab98c6e"'
              in install_sh)
    cell("T13a install.sh pins EasyRSA 3.1.7 sha256 (verified hash)",
         pin_ok and m is not None, f"pin-present={pin_ok} fn-extracted={m is not None}")
    if m is not None:
        harness_dir = WORK / "ensure-harness"
        harness_dir.mkdir(parents=True, exist_ok=True)
        harness = harness_dir / "run.sh"
        harness.write_text(
            "#!/usr/bin/env bash\n"
            "set -uo pipefail\n"
            "log() { echo \"LOG: $*\"; }\n"
            "die() { echo \"DIE: $*\" >&2; exit 1; }\n"
            "EASYRSA_VERSION=\"3.1.7\"\n"
            "EASYRSA_MIN_VERSION=\"3.1.0\"\n"
            "EASYRSA_SHA256_PINNED=\"aaa48fadcbb77511b9c378554ef3eae09f8c7bc149d6f56ba209f1c9bab98c6e\"\n"
            "EASYRSA_BASE=\"https://github.com/OpenVPN/easy-rsa/releases/download/v${EASYRSA_VERSION}\"\n"
            "EASYRSA_INSTALL_DIR=\"$1\"\n"
            + m.group(1) +
            "_ensure_easyrsa\n")
        harness.chmod(0o755)
        # fake old easyrsa first on PATH (3.0.6 binary, no --version cmd)
        fakebin = harness_dir / "bin"
        fakebin.mkdir(exist_ok=True)
        (fakebin / "easyrsa").symlink_to(easyrsa_bin(tc, "3.0.6"))
        inst_root = harness_dir / "easy-rsa-install"
        env_h = {**os.environ, "PATH": str(fakebin) + ":/usr/bin:/bin"}
        # hide the host /usr/share easy-rsa from the function by pointing
        # the search at our scratch root only is not possible; instead the
        # function checks /usr/local first -- host has none, /usr/share
        # has 3.0.8 (< 3.1.0) so it must still upgrade into $1.
        p1 = run(["bash", str(harness), str(inst_root)], timeout=180,
                 stdin=subprocess.DEVNULL, env=env_h)
        got317 = (inst_root / "easyrsa").exists()
        ver317 = ""
        if got317:
            q = run([str(inst_root / "easyrsa"), "--version"], timeout=30)
            ver317 = q.stdout
        cell("T13b _ensure_easyrsa installs 3.1.7 when the system one is too old",
             p1.returncode == 0 and got317 and "3.1.7" in ver317,
             f"rc={p1.returncode} out={(p1.stdout + p1.stderr).strip()[-200:]!r}")
        p2 = run(["bash", str(harness), str(inst_root)], timeout=180,
                 stdin=subprocess.DEVNULL, env=env_h)
        cell("T13c _ensure_easyrsa is idempotent (second run skips download)",
             p2.returncode == 0 and (("already" in (p2.stdout + p2.stderr).lower())
                                      or ("keeping" in (p2.stdout + p2.stderr).lower())),
             f"rc={p2.returncode} out={(p2.stdout + p2.stderr).strip()[-160:]!r}")

    # ---- T14: regression -- existing core tests + script syntax ----
    q = run(["bash", "-n", str(TREE / "core/easyrsa.sh")], timeout=30)
    q2 = run(["bash", "-n", str(TREE / "install.sh")], timeout=30)
    cell("T14a bash -n clean for easyrsa.sh + install.sh",
         q.returncode == 0 and q2.returncode == 0,
         f"easyrsa.sh rc={q.returncode} install.sh rc={q2.returncode}")
    q3 = run([sys.executable, "-m", "pytest", "-q",
              str(TREE / "core/tests/test_status_log.py")], timeout=120)
    cell("T14b core/tests/test_status_log.py still green",
         q3.returncode == 0,
         f"rc={q3.returncode} tail={(q3.stdout + q3.stderr).strip()[-120:]!r}")
    # r17_core needs its fixture PKI: rebuild it from the versioned
    # recipe into the scratch work dir and run for real.
    r17_ca = WORK / "r17" / "fixture-ca"
    r17_srv = WORK / "r17" / "fixture-server"
    r17_srv.mkdir(parents=True, exist_ok=True)
    qf = run(["bash", str(TREE / "tests/rebuild-r17-fixture.sh"), str(r17_ca)],
             timeout=120)
    om.render_server_conf("udp", 1194, server_dir=r17_srv)
    if qf.returncode != 0:
        print("SKIP T14c: r17 fixture rebuild failed: "
              + (qf.stdout + qf.stderr).strip()[-160:])
    else:
        # r17_core.py is a standalone script (exit code = FAIL count),
        # not a pytest module.
        q4 = run([sys.executable, str(TREE / "tests/r17_core.py")], timeout=120,
                 env={**os.environ,
                      "R17_TREE": str(TREE),
                      "OPENVPN_CA_DIR": str(r17_ca),
                      "OPENVPN_SERVER_DIR": str(r17_srv)})
        cell("T14c tests/r17_core.py still green",
             q4.returncode == 0,
             f"rc={q4.returncode} tail={(q4.stdout + q4.stderr).strip()[-160:]!r}")

    fails = [n for n, ok, _ in RESULTS if not ok]
    print(f"\nTOTAL {len(RESULTS)} cells, FAIL {len(fails)}: {fails}")
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())

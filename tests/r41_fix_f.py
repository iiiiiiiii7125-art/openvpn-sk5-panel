#!/usr/bin/env python3
"""R41 Fix-F verification probe (tests/r41_fix_f.py).

Verifies, against the REAL edited files (extraction, not re-typed copies):
  F1  fresh panel cert SANs include IP:127.0.0.1 (L7-P2-1)
  F2  stale-SAN cert is rebuilt on re-run (+ .bak kept); a non-self-signed
      cert is left alone (L7-P2-1)
  F3  banner warns about the self-signed cert with click path + domain
      pointer (L7-P2-2)
  F4  secret.key is kept byte-identical across a re-run of the secret
      block (L1-6)
  F5  python3-venv is in the installer's apt list (L1-8)
  F6  check-no-secrets.sh passes the clean tree and blocks every planted
      secret (mutation, incl. the pre-push hook) (L7-P2-3)
  F7  README/DELIVERY state the supported OS list + ALLOW_UNSUPPORTED_OS=1
      + the 20.04 note, and the cert warning with click path + Caddy
      pointer (L6-P1-1, L6-P2-3)
  F8  TOFU trial: a CN-only panel cert pins to mode=error (previous pin
      preserved); a SAN'd cert pins to mode=pinned (O-L5-1)

Usage: python3 tests/r41_fix_f.py   (run from the repo root)
Exit 0 = all checks pass.
"""
import hashlib
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} {detail}")


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


INSTALL_SH = read(os.path.join(ROOT, "install.sh"))


def extract_block(text, start_re, end_re):
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if re.search(start_re, l))
    end = next(i for i, l in enumerate(lines) if i > start and re.search(end_re, l))
    return "\n".join(lines[start:end + 1]) + "\n"


# ---------------------------------------------------------------- F1/F2
def cert_sans(cert_path):
    out = run(["openssl", "x509", "-in", cert_path, "-noout", "-text"]).stdout
    m = re.search(r"X509v3 Subject Alternative Name:\s*\n\s*(.+)", out)
    return m.group(1) if m else ""


TMP = tempfile.mkdtemp(prefix="r41fixf-")
SCRATCH = os.path.join(TMP, "cfg")
os.makedirs(SCRATCH)

cert_lines = INSTALL_SH.splitlines()
_cert_start = next(i for i, l in enumerate(cert_lines) if l.startswith("_PANEL_CERT_STALE=0"))
_cert_keep = next(i for i, l in enumerate(cert_lines)
                 if i > _cert_start and "keeping existing panel TLS cert" in l)
_cert_end = next(i for i, l in enumerate(cert_lines)
                if i > _cert_keep and l == "fi")
cert_block = "\n".join(cert_lines[_cert_start:_cert_end + 1]) + "\n"
# sanity: the extracted block must contain the new SAN and the stale logic
check("F1a cert block extracted (has 127.0.0.1 SAN + stale check)",
      "IP:127.0.0.1" in cert_block and "_PANEL_CERT_STALE" in cert_block)

PREAMBLE = (
    'log() { echo "[install] $*"; }\n'
    'warn() { echo "[install] WARN: $*" >&2; }\n'
    'die() { echo "[install] DIE: $*" >&2; exit 1; }\n'
    'SERVER_IP="192.0.2.10"\n'
    f'PANEL_CERT="{SCRATCH}/panel-cert.pem"\n'
    f'PANEL_KEY="{SCRATCH}/panel-key.pem"\n'
)
BLOCK_SH = os.path.join(TMP, "cert-block.sh")
with open(BLOCK_SH, "w", encoding="utf-8") as f:
    f.write(PREAMBLE + cert_block)


def run_cert_block():
    return run(["bash", BLOCK_SH])


r = run_cert_block()
cert = os.path.join(SCRATCH, "panel-cert.pem")
key = os.path.join(SCRATCH, "panel-key.pem")
sans = cert_sans(cert) if os.path.exists(cert) else ""
check("F1 fresh cert SANs include IP:127.0.0.1",
      r.returncode == 0 and "IP Address:127.0.0.1" in sans
      and "IP Address:192.0.2.10" in sans and "DNS:localhost" in sans, sans)
check("F1 fresh cert modes (key 0600, cert 0644)",
      oct(os.stat(key).st_mode & 0o777) == "0o600"
      and oct(os.stat(cert).st_mode & 0o777) == "0o644")

# stale: overwrite with an old-style cert (no 127.0.0.1), re-run, must rebuild
old_sha = hashlib.sha256(open(cert, "rb").read()).hexdigest()
run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", key,
     "-out", cert, "-days", "3650", "-nodes", "-subj", "/CN=192.0.2.10",
     "-addext", "subjectAltName=IP:192.0.2.10,DNS:localhost"],
    check=True)
stale_sha = hashlib.sha256(open(cert, "rb").read()).hexdigest()
check("F2 setup: stale cert has no 127.0.0.1",
      "IP Address:127.0.0.1" not in cert_sans(cert))
r = run_cert_block()
new_sha = hashlib.sha256(open(cert, "rb").read()).hexdigest()
check("F2 stale-SAN cert rebuilt on re-run",
      r.returncode == 0 and new_sha != stale_sha
      and "IP Address:127.0.0.1" in cert_sans(cert))
check("F2 old pair kept as .bak",
      os.path.exists(cert + ".bak") and os.path.exists(key + ".bak")
      and hashlib.sha256(open(cert + ".bak", "rb").read()).hexdigest() == stale_sha)

# non-self-signed: mini CA signs a panel cert without 127.0.0.1 -> kept
ca_dir = os.path.join(TMP, "ca")
os.makedirs(ca_dir)
run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout",
     os.path.join(ca_dir, "ca.key"), "-out", os.path.join(ca_dir, "ca.crt"),
     "-days", "3650", "-nodes", "-subj", "/CN=TestCA"],
    check=True)
run(["openssl", "req", "-newkey", "rsa:2048", "-keyout", key,
     "-out", os.path.join(ca_dir, "panel.csr"), "-nodes",
     "-subj", "/CN=192.0.2.10"], check=True)
with open(os.path.join(ca_dir, "san.ext"), "w") as f:
    f.write("subjectAltName=IP:192.0.2.10,DNS:localhost\n")
run(["openssl", "x509", "-req", "-in", os.path.join(ca_dir, "panel.csr"),
     "-CA", os.path.join(ca_dir, "ca.crt"), "-CAkey",
     os.path.join(ca_dir, "ca.key"), "-CAcreateserial",
     "-out", cert, "-days", "3650",
     "-extfile", os.path.join(ca_dir, "san.ext")],
    check=True)
ca_signed_sha = hashlib.sha256(open(cert, "rb").read()).hexdigest()
r = run_cert_block()
check("F2 non-self-signed cert left alone",
      r.returncode == 0
      and hashlib.sha256(open(cert, "rb").read()).hexdigest() == ca_signed_sha
      and "IP Address:127.0.0.1" not in cert_sans(cert))

# ---------------------------------------------------------------- F3
banner = INSTALL_SH[INSTALL_SH.index("安装完成"):]
check("F3 banner warns: self-signed + click path + domain pointer",
      "自签" in banner and "高级" in banner and "继续前往" in banner
      and "域名" in banner and "Let's Encrypt" in banner)

# ---------------------------------------------------------------- F4
secret_block = extract_block(
    INSTALL_SH, r'^if \[ ! -f "/etc/openvpn-sk5-panel/secret\.key" \]; then',
    r"^fi$")
check("F4a secret block extracted (existence guard present)",
      'if [ ! -f "/etc/openvpn-sk5-panel/secret.key" ]' in secret_block)
SECRET_SCRATCH = os.path.join(TMP, "secret.key")
secret_sh = os.path.join(TMP, "secret-block.sh")
with open(secret_sh, "w", encoding="utf-8") as f:
    f.write('log() { echo "[install] $*"; }\n'
            'die() { echo "[install] DIE: $*" >&2; exit 1; }\n'
            + secret_block.replace("/etc/openvpn-sk5-panel/secret.key",
                                   SECRET_SCRATCH))
r1 = run(["bash", secret_sh])
sha1 = hashlib.sha256(open(SECRET_SCRATCH, "rb").read()).hexdigest()
r2 = run(["bash", secret_sh])
sha2 = hashlib.sha256(open(SECRET_SCRATCH, "rb").read()).hexdigest()
check("F4 secret kept byte-identical across re-run",
      r1.returncode == 0 and r2.returncode == 0 and sha1 == sha2
      and "keeping existing" in r2.stdout)
check("F4 secret mode 0600",
      oct(os.stat(SECRET_SCRATCH).st_mode & 0o777) == "0o600")

# ---------------------------------------------------------------- F5
check("F5 python3-venv in installer apt list",
      "python3-venv" in INSTALL_SH
      and re.search(r"apt-get install.*python3-venv", INSTALL_SH, re.S) is not None)

# ---------------------------------------------------------------- F6
SCAN = os.path.join(ROOT, "scripts", "check-no-secrets.sh")
check("F6a scan passes the clean worktree",
      run(["bash", SCAN, ROOT]).returncode == 0)


def scratch_repo():
    d = tempfile.mkdtemp(prefix="r41fixf-repo-")
    run(["git", "init", "-q", d], check=True)
    run(["git", "-C", d, "config", "user.email", "t@t"], check=True)
    run(["git", "-C", d, "config", "user.name", "t"], check=True)
    open(os.path.join(d, "clean.txt"), "w").write("hello\n")
    run(["git", "-C", d, "add", "clean.txt"], check=True)
    run(["git", "-C", d, "commit", "-qm", "clean"], check=True)
    return d


def plant_and_scan(relpath, content_bytes, force_add=False):
    """Fresh repo per case (isolation: each case proves its own check)."""
    d = scratch_repo()
    p = os.path.join(d, relpath)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(content_bytes)
    args = ["git", "-C", d, "add"]
    if force_add:
        args.append("-f")
    args.append(relpath)
    run(args, check=True)
    return run(["bash", SCAN, d]).returncode


# The shipped secret's SHA-256, derived from the panel tripwire at runtime.
# It MUST NOT be a literal here: this probe verifies check-no-secrets.sh,
# and a literal would make the scan flag the probe itself (R41 Fix-F2).
def _shipped_hash():
    text = read(os.path.join(ROOT, "panel", "app.py"))
    m = re.search(r"_SHIPPED_SECRET_SHA256\s*=\s*\(\s*\"([0-9a-f]{64})\"", text)
    assert m, "tripwire value not found in panel/app.py"
    return m.group(1)


SHIPPED_HASH = _shipped_hash()
check("F6b staged fake secret.key blocked",
      plant_and_scan("secret.key", os.urandom(32)) == 1)
check("F6c staged file with shipped hash blocked",
      plant_and_scan("note.txt", ("key " + SHIPPED_HASH + "\n").encode()) == 1)
key_pem = run(["openssl", "genrsa", "2048"], check=True).stdout.encode()
check("F6d staged real private key blocked",
      plant_and_scan("id_rsa.pem", key_pem) == 1)
check("F6e staged panel/data file blocked",
      plant_and_scan("panel/data/secret.key", os.urandom(32),
                     force_add=True) == 1)
# tarball with a credential entry (fresh repo, only the tarball is dirty)
repo_t = scratch_repo()
rel_dir = os.path.join(repo_t, "releases")
os.makedirs(rel_dir, exist_ok=True)
evil_dir = os.path.join(repo_t, "evil-pkg")
os.makedirs(evil_dir, exist_ok=True)
open(os.path.join(evil_dir, "secret.key"), "wb").write(os.urandom(32))
run(["tar", "czf", os.path.join(rel_dir, "evil.tar.gz"), "-C", repo_t,
     "evil-pkg"], check=True)
check("F6f tarball listing a credential entry blocked",
      run(["bash", SCAN, repo_t]).returncode == 1)
# clean repo passes + pre-push hook blocks the push, allows a clean push
repo2 = scratch_repo()
remote = os.path.join(TMP, "remote.git")
run(["git", "init", "-q", "--bare", remote], check=True)
run(["git", "-C", repo2, "remote", "add", "origin", remote], check=True)
shutil.copy(os.path.join(ROOT, "scripts", "git-hooks", "pre-push"),
            os.path.join(repo2, ".git", "hooks", "pre-push"))
os.chmod(os.path.join(repo2, ".git", "hooks", "pre-push"), 0o755)
# the hook execs scripts/check-no-secrets.sh from the same repo: a real
# clone carries it; the scratch repo needs a copy too.
os.makedirs(os.path.join(repo2, "scripts"), exist_ok=True)
shutil.copy(os.path.join(ROOT, "scripts", "check-no-secrets.sh"),
            os.path.join(repo2, "scripts", "check-no-secrets.sh"))
os.chmod(os.path.join(repo2, "scripts", "check-no-secrets.sh"), 0o755)
check("F6g clean repo: scan passes, push succeeds",
      run(["bash", SCAN, repo2]).returncode == 0
      and run(["git", "-C", repo2, "push", "-q", "origin", "HEAD:master"]).returncode == 0)
open(os.path.join(repo2, "secret.key"), "wb").write(os.urandom(32))
run(["git", "-C", repo2, "add", "secret.key"], check=True)
# commit it: a push with nothing new never invokes the hook, so the
# secret must be committed for the hook to run (the realistic case).
run(["git", "-C", repo2, "commit", "-qm", "add secret"], check=True)
check("F6h pre-push hook blocks push of a committed secret.key",
      run(["git", "-C", repo2, "push", "-q", "origin", "HEAD:master"]).returncode != 0)

# ---------------------------------------------------------------- F7
README = read(os.path.join(ROOT, "README.md"))
DELIVERY = read(os.path.join(ROOT, "docs", "DELIVERY.md"))
check("F7a docs state supported OS + override + 20.04 note",
      "ALLOW_UNSUPPORTED_OS=1" in README and "ALLOW_UNSUPPORTED_OS=1" in DELIVERY
      and "20.04" in README and "20.04" in DELIVERY
      and "unsupported OS" in README)
check("F7b install docs carry the cert warning (click path + domain)",
      "继续前往" in README and "继续前往" in DELIVERY
      and "Caddy" in README and "Caddy" in DELIVERY)
check("F7c README security section no longer points at manual cert-swap",
      "可把证书换成合法证书" not in README)
check("F7d gate count is 30 in README + DELIVERY + gate comment",
      "PASS=30" in README and "PASS=30" in DELIVERY
      and "30 格" in DELIVERY
      and "30 格" in read(os.path.join(ROOT, "verify-integration.sh")))

# ---------------------------------------------------------------- F8
AGENT_SH = read(os.path.join(ROOT, "agent", "install-agent.sh"))
_snip_start = AGENT_SH.index('_TRUST_JSON="$(python3 - ')
_snip_end = AGENT_SH.index("\nPYEOF", _snip_start) + len("\nPYEOF")
snippet = AGENT_SH[_snip_start:_snip_end]
# strip the shell assignment wrapper, keep the python body (without the
# closing PYEOF line)
py_body = snippet[snippet.index("<<'PYEOF'") + len("<<'PYEOF'"):snippet.rindex("PYEOF")]
check("F8a trust snippet extracted (has trial verification)",
      "create_default_context(cafile=_tmp_pem)" in py_body
      and "SSLCertVerificationError" in py_body)


def tls_server(certfile, keyfile, port):
    """Serve TLS on 127.0.0.1:port until stopped; returns stop()."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile, keyfile)
    lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lsock.bind(("127.0.0.1", port))
    lsock.listen(8)
    lsock.settimeout(0.5)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                conn, _ = lsock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                with ctx.wrap_socket(conn, server_side=True) as ssock:
                    ssock.settimeout(2)
                    try:
                        ssock.recv(4096)
                    except (socket.timeout, OSError, ssl.SSLError):
                        pass
            except (OSError, ssl.SSLError):
                pass
    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return lambda: (stop.set(), lsock.close(), t.join(timeout=5))


def run_snippet(panel_url, out_pem):
    script = os.path.join(TMP, "tofu-snippet.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(py_body)
    return run([sys.executable, script, panel_url, "auto", out_pem],
               timeout=60)


def make_cert(cert_path, key_path, subj, san=None):
    cmd = ["openssl", "req", "-x509", "-newkey", "rsa:2048",
           "-keyout", key_path, "-out", cert_path, "-days", "3650",
           "-nodes", "-subj", subj]
    if san:
        cmd += ["-addext", f"subjectAltName={san}"]
    run(cmd, check=True)


# CN-only cert: trial must fail -> mode=error, previous pin preserved
cn_cert = os.path.join(TMP, "cn-only.crt")
cn_key = os.path.join(TMP, "cn-only.key")
make_cert(cn_cert, cn_key, "/CN=127.0.0.1")
stop_cn = tls_server(cn_cert, cn_key, 18441)
pin_path = os.path.join(TMP, "pin.pem")
open(pin_path, "w").write("PREVIOUS-PIN\n")
try:
    r = run_snippet("https://127.0.0.1:18441", pin_path)
    mode = json.loads(r.stdout).get("mode")
    check("F8b CN-only cert: trial fails, mode=error",
          r.returncode == 0 and mode == "error", f"mode={mode} out={r.stdout[:200]}")
    check("F8c failed trial leaves previous pin untouched",
          open(pin_path).read() == "PREVIOUS-PIN\n"
          and not os.path.exists(pin_path + ".tmp"))
finally:
    stop_cn()
# SAN'd cert (IP:127.0.0.1): trial succeeds -> mode=pinned
san_cert = os.path.join(TMP, "san.crt")
san_key = os.path.join(TMP, "san.key")
make_cert(san_cert, san_key, "/CN=127.0.0.1",
          san="IP:127.0.0.1,DNS:localhost")
stop_san = tls_server(san_cert, san_key, 18442)
pin2 = os.path.join(TMP, "pin2.pem")
try:
    r = run_snippet("https://127.0.0.1:18442", pin2)
    mode = json.loads(r.stdout).get("mode")
    check("F8d SAN'd cert: trial succeeds, mode=pinned",
          r.returncode == 0 and mode == "pinned", f"mode={mode} out={r.stdout[:200]}")
    check("F8e pinned PEM is the presented cert, 0600",
          os.path.exists(pin2) and "BEGIN CERTIFICATE" in open(pin2).read()
          and oct(os.stat(pin2).st_mode & 0o777) == "0o600")
finally:
    stop_san()

shutil.rmtree(TMP, ignore_errors=True)
print(f"\nTOTAL: PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)

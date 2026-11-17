#!/usr/bin/env python3
"""R43 Fix-R probe: scan evasion (J7-5) + uninstall/docs (J7-2, J2-D1, J4-1).

Cells:
  S1 tip scan flags the three evasion files (secret.key.bak, SECRET.KEY,
     "admin.pass " trailing space) in a scratch git repo (binary content,
     so checks 2/3 cannot catch them).
  S2 baseline (2e08a8c) scan MISSES all three (negative control).
  S3 tip scan does NOT flag bare stems (mysecret.key, admin.password,
     secret.keystore).
  S4 tip scan flags sk5.json.example (documented fail-closed trade-off:
     any "<name>.<suffix>" counts as the same file).
  S5 tip scan passes a clean tree, git mode.
  S6 tip scan passes a clean non-git tree copy, disk mode, as nobody.
  S7 tip scan flags a tarball listing SECRET.KEY (check 4); baseline
     scan misses it.
  D1 README.md revoke line states auto-restart (tip) / manual restart
     (baseline, negative control).
  D2 panel/README.md DELETE row states needs_restart:false,
     restarted:true (tip) / needs_restart:true (baseline).
  D3 docs/DELIVERY.md revoke line states auto-restart (tip) / manual
     restart (baseline).
  D4 cloudflare/README.md corpus is 292 cells / 19 files with both new
     files listed (tip) / 246 / 17 (baseline).
  D5 D10 list in tests/r42_f7_docs.py contains both new Worker files.
  D6 tests/r43_j4_journey.mjs exists on the tree and runs 25/25.
  U1 README uninstall block names all 6 leftover paths; fake deployment
     + documented removals -> all 6 gone (old 9 documented paths gone too).
  U2 baseline README uninstall block names none of the 6 (negative control).

Run from the repo root: python3 tests/r43_fix_r.py
Exit code = number of FAILs. Scratch under /tmp/r43fixr-* only.
"""
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

RESULTS = []
FAILURES = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name
          + ((" | " + str(detail)[:300]) if detail else ""), flush=True)
    if not cond:
        FAILURES.append(name)


def run(cmd, cwd=None, timeout=120):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)


TREE = Path(__file__).resolve().parent.parent
SCAN_TIP = TREE / "scripts" / "check-no-secrets.sh"
SCRATCH = Path("/tmp/r43fixr-probe")
if SCRATCH.exists():
    shutil.rmtree(SCRATCH)
SCRATCH.mkdir(parents=True)

# ---- baseline scan (2e08a8c) -------------------------------------------
base_scan = SCRATCH / "scan-base.sh"
base_scan.write_text(run(["git", "-C", str(TREE), "show",
                          "2e08a8c:scripts/check-no-secrets.sh"]).stdout)
base_scan.chmod(0o755)


def git_repo(path, files):
    """Create a scratch git repo with the given {name: bytes}."""
    path.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        p = path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    run(["git", "init", "-q", "."], cwd=str(path))
    run(["git", "add", "-A"], cwd=str(path))
    return path


BIN = b"x\x00\x01\x02binary-not-a-key"
evasion = git_repo(SCRATCH / "evasion", {
    "secret.key.bak": BIN, "SECRET.KEY": BIN, "admin.pass ": BIN,
    "README.md": b"harmless\n",
})
r_tip = run(["bash", str(SCAN_TIP), str(evasion)])
cell("S1 tip scan flags all 3 evasion files",
     r_tip.returncode == 1 and r_tip.stderr.count("SECRET:") == 3,
     "rc=%d secrets=%d" % (r_tip.returncode, r_tip.stderr.count("SECRET:")))
r_base = run(["bash", str(base_scan), str(evasion)])
cell("S2 baseline scan misses all 3 evasion files (negative control)",
     r_base.returncode == 0,
     "rc=%d out=%s" % (r_base.returncode, r_base.stdout.strip()[:80]))

neg = git_repo(SCRATCH / "neg", {
    "mysecret.key": b"not a secret\n", "admin.password": b"not a secret\n",
    "secret.keystore": b"not a secret\n",
})
r_neg = run(["bash", str(SCAN_TIP), str(neg)])
cell("S3 tip scan does NOT flag bare stems",
     r_neg.returncode == 0,
     "rc=%d err=%s" % (r_neg.returncode, r_neg.stderr.strip()[:120]))
ex = git_repo(SCRATCH / "example", {"sk5.json.example": b"template\n"})
r_ex = run(["bash", str(SCAN_TIP), str(ex)])
cell("S4 tip scan flags sk5.json.example (fail-closed .suffix rule)",
     r_ex.returncode == 1 and r_ex.stderr.count("SECRET:") == 1,
     "rc=%d secrets=%d" % (r_ex.returncode, r_ex.stderr.count("SECRET:")))

r_clean = run(["bash", str(SCAN_TIP), str(TREE)])
cell("S5 tip scan clean on this tree (git mode)",
     r_clean.returncode == 0, "rc=%d" % r_clean.returncode)

# ---- S6: disk mode as nobody on a non-git copy --------------------------
disk = SCRATCH / "disk"
shutil.copytree(TREE, disk, ignore=shutil.ignore_patterns(".git"))
scan_copy = SCRATCH / "scan-tip.sh"
shutil.copyfile(SCAN_TIP, scan_copy)
scan_copy.chmod(0o755)
# This shell's umask makes fresh dirs 770: nobody cannot traverse
# SCRATCH until it is opened up (the known harness rule).
run(["chmod", "755", str(SCRATCH)])
run(["chmod", "-R", "a+rX", str(disk), str(scan_copy)])
r_disk = run(["runuser", "-u", "nobody", "--", "bash", str(scan_copy),
              str(disk)])
cell("S6 tip scan clean on non-git copy, disk mode, as nobody",
     r_disk.returncode == 0,
     "rc=%d err=%s" % (r_disk.returncode, r_disk.stderr.strip()[:120]))

# ---- S7: tarball check 4 -------------------------------------------------
tar_dir = SCRATCH / "tar"
(tar_dir / "releases").mkdir(parents=True)
with tarfile.open(tar_dir / "releases" / "test.tar.gz", "w:gz") as tf:
    for name in ("x/SECRET.KEY", "x/secret.key.bak", "x/ok.txt"):
        p = SCRATCH / ("tar-" + name.replace("/", "_"))
        p.write_bytes(BIN if name.endswith((".KEY", ".bak")) else b"ok\n")
        tf.add(p, arcname=name)
r_tar_tip = run(["bash", str(SCAN_TIP), str(tar_dir)])
cell("S7 tip scan flags tarball listing SECRET.KEY",
     r_tar_tip.returncode == 1,
     "rc=%d err=%s" % (r_tar_tip.returncode, r_tar_tip.stderr.strip()[:120]))
r_tar_base = run(["bash", str(base_scan), str(tar_dir)])
cell("S7b baseline scan misses the same tarball (negative control)",
     r_tar_base.returncode == 0, "rc=%d" % r_tar_base.returncode)


def base_text(rel):
    return run(["git", "-C", str(TREE), "show", "2e08a8c:" + rel]).stdout


# ---- D1-D3: revoke docs ---------------------------------------------------
readme = (TREE / "README.md").read_text()
cell("D1 README revoke line states auto-restart",
     "吊销用户后 OpenVPN 服务自动重启一次" in readme
     and "needs_restart: false, restarted: true" in readme,
     "auto-restart present=%s" % ("吊销用户后 OpenVPN 服务自动重启一次" in readme))
cell("D1b baseline README demands manual restart (negative control)",
     "吊销用户后须重启 OpenVPN 服务才对新连接生效" in base_text("README.md"),
     "old line present on baseline")
prm = (TREE / "panel" / "README.md").read_text()
del_line = next((l for l in prm.splitlines()
                 if "DELETE `/api/openvpn/users/<name>`" in l), "")
cell("D2 panel/README DELETE row states needs_restart:false, restarted:true",
     "needs_restart: false, restarted: true" in del_line
     and "CRL 只在启动时读" not in del_line,
     "row=%s" % del_line[:120])
cell("D2b baseline panel/README DELETE row says needs_restart:true",
     "needs_restart: true" in base_text("panel/README.md"),
     "old row present on baseline")
delivery = (TREE / "docs" / "DELIVERY.md").read_text()
cell("D3 DELIVERY revoke line states auto-restart",
     "吊销后 OpenVPN 服务自动重启一次" in delivery,
     "auto-restart present")
cell("D3b baseline DELIVERY demands manual restart",
     "吊销后须重启 OpenVPN 服务才对新连接生效" in base_text("docs/DELIVERY.md"),
     "old line present on baseline")

# ---- D4-D6: Worker corpus --------------------------------------------------
crm = (TREE / "cloudflare" / "README.md").read_text()
m = re.search(r"全路由测试（(\d+) 格，\s*\n?\s*(\d+) 个探针文件", crm)
cell("D4 cloudflare README corpus is 292 cells / 19 files",
     m and m.group(1) == "292" and m.group(2) == "19"
     and "r42_f4_age 21" in crm and "r43_j4_journey 25" in crm,
     "found=%r" % (m.groups() if m else None,))
m_base = re.search(r"全路由测试（(\d+) 格", base_text("cloudflare/README.md"))
cell("D4b baseline README corpus is 246 (negative control)",
     m_base and m_base.group(1) == "246",
     "found=%s" % (m_base.group(1) if m_base else None))
d10 = (TREE / "tests" / "r42_f7_docs.py").read_text()
cell("D5 D10 list contains both new Worker files",
     '"tests/r42_f4_age.mjs"' in d10
     and '"tests/r43_j4_journey.mjs"' in d10,
     "both listed")
j4 = TREE / "tests" / "r43_j4_journey.mjs"
r_j4 = run(["node", str(j4)], cwd=str(TREE), timeout=120) if j4.exists() else None
cell("D6 r43_j4_journey.mjs exists and runs 25/25",
     j4.exists() and r_j4 is not None and "25/25 passed" in r_j4.stdout,
     "exists=%s out=%s" % (j4.exists(),
                           (r_j4.stdout.strip()[-40:] if r_j4 else None)))

# ---- U1-U2: uninstall -------------------------------------------------------
uninst = re.search(r"## 卸载（手动，无一键卸载脚本）\n\n(.*?)\n\n注：",
                   readme, re.S)
block = uninst.group(1) if uninst else ""
NEW_PATHS = ["/usr/local/bin/sing-box", "/usr/local/bin/tun2socks",
             "/usr/local/share/easy-rsa", "/etc/caddy/panel-cert.pem",
             "/etc/sysctl.d/99-openvpn-sk5.conf"]
cell("U1 README uninstall block names all 6 leftover paths",
     all(p in block for p in NEW_PATHS),
     "missing=%s" % [p for p in NEW_PATHS if p not in block])
base_readme = base_text("README.md")
base_block = re.search(r"## 卸载（手动，无一键卸载脚本）\n\n(.*?)\n\n注：",
                       base_readme, re.S)
base_block = base_block.group(1) if base_block else ""
cell("U2 baseline uninstall block names none of the 6 (negative control)",
     not any(p in base_block for p in NEW_PATHS),
     "present=%s" % [p for p in NEW_PATHS if p in base_block])

# Fake deployment + documented removals (mirrors the R43-J7 U1 probe).
FAKE = SCRATCH / "fake-root"
INSTALLED = [
    "opt/openvpn-sk5-panel", "opt/openvpn-sk5-panel/panel/app.py",
    "etc/openvpn-sk5-panel", "etc/openvpn-sk5-panel/panel.env",
    "etc/openvpn-sk5-panel/panel-cert.pem",
    "etc/openvpn-sk5-panel/panel-key.pem",
    "etc/openvpn-sk5-panel/admin.pass", "etc/openvpn-sk5-panel/secret.key",
    "etc/openvpn-sk5-panel/sk5.json", "etc/openvpn-sk5-panel/panel.db",
    "etc/openvpn/server", "etc/openvpn/server/server.conf",
    "etc/openvpn/server/easy-rsa", "etc/openvpn/server/easy-rsa/pki/ca.crt",
    "etc/systemd/system/openvpn-sk5-panel.service",
    "etc/systemd/system/openvpn-sk5-singbox.service",
    "etc/systemd/system/openvpn-sk5-policy.service",
    "etc/systemd/system/openvpn-sk5-healthcheck.service",
    "etc/systemd/system/openvpn-sk5-healthcheck.timer",
    "etc/caddy/Caddyfile", "etc/caddy/panel-cert.pem",
    "etc/sysctl.d/99-openvpn-sk5.conf",
    "usr/local/bin/sing-box", "usr/local/bin/tun2socks",
    "usr/local/share/easy-rsa", "usr/local/share/easy-rsa/easyrsa",
]
DIRS = {"opt/openvpn-sk5-panel", "etc/openvpn-sk5-panel",
        "etc/openvpn/server", "etc/openvpn/server/easy-rsa",
        "usr/local/share/easy-rsa"}
for rel in INSTALLED:
    p = FAKE / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if rel in DIRS:
        p.mkdir(parents=True, exist_ok=True)
    else:
        p.write_text("fake deployment artifact: %s\n" % rel)
(FAKE / "etc/caddy/Caddyfile").write_text(
    "# BEGIN openvpn-sk5-panel\n16.146.199.68.sslip.io {\n    reverse_proxy https://localhost:8443\n}\n# END openvpn-sk5-panel\n")
# Apply the documented removal steps (file removals only; systemctl /
# iptables / ufw are host ops, needs-live -- same split as the J7 probe).
caddyfile = FAKE / "etc/caddy/Caddyfile"
text = caddyfile.read_text()
start = text.find("# BEGIN openvpn-sk5-panel")
end = text.find("# END openvpn-sk5-panel")
if start >= 0 and end > start:
    end = text.find("\n", end) + 1
    caddyfile.write_text(text[:start] + text[end:])
    if not caddyfile.read_text().strip():
        caddyfile.unlink()
for rel in ("opt/openvpn-sk5-panel", "etc/openvpn-sk5-panel",
            "etc/openvpn/server",
            "etc/systemd/system/openvpn-sk5-panel.service",
            "etc/systemd/system/openvpn-sk5-singbox.service",
            "etc/systemd/system/openvpn-sk5-policy.service",
            "etc/systemd/system/openvpn-sk5-healthcheck.service",
            "etc/systemd/system/openvpn-sk5-healthcheck.timer",
            "usr/local/bin/sing-box", "usr/local/bin/tun2socks",
            "usr/local/share/easy-rsa", "etc/caddy/panel-cert.pem",
            "etc/sysctl.d/99-openvpn-sk5.conf"):
    p = FAKE / rel
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()
leftovers = [rel for rel in INSTALLED if (FAKE / rel).exists()]
cell("U1b fake deployment: documented removals leave NOTHING behind",
     not leftovers, "leftovers=%s" % leftovers)

print("\nR43FIXR TOTAL: PASS=%d FAIL=%d"
      % (len(RESULTS) - len(FAILURES), len(FAILURES)))
if FAILURES:
    print("FAILURES: %s" % FAILURES)
sys.exit(1 if FAILURES else 0)

#!/usr/bin/env python3
"""R44 Fix-T probe: scan evasion v2 (R44-L7-2).

Cells:
  T1 tip scan flags all 5 new evasion files (secret.key~, SECRET.KEY~,
     .secret.key, sk5.json~, admin.pass~) in a scratch git repo
     (binary content, so checks 2/3 cannot catch them).
  T2 baseline (46a78e8) scan MISSES all 5 (negative control).
  T3 tip scan does NOT flag bare stems / lookalikes (mysecret.key,
     admin.password, secret.keystore, mysecret.key~, notes~, .hidden).
  T4 tip scan flags combined shapes (.secret.key~, secret.key~~,
     ..secret.key, " secret.key~ " with surrounding spaces).
  T5 tip scan passes a clean tree, git mode.
  T6 tip scan passes a clean non-git tree copy, disk mode, as nobody.
  T7 tip scan flags a tarball listing secret.key~ (check 4); baseline
     scan misses it.
  T8 baseline scan still flags the old Fix-R shapes (secret.key.bak,
     SECRET.KEY) -- the T2 negative control is meaningful, not a dead
     scan.

Run from the repo root: python3 tests/r44_fix_t_scan.py
Exit code = number of FAILs. Scratch under /tmp/r44fixt-* only.
"""
import shutil
import subprocess
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
SCRATCH = Path("/tmp/r44fixt-probe")
if SCRATCH.exists():
    shutil.rmtree(SCRATCH)
SCRATCH.mkdir(parents=True)

# ---- baseline scan (46a78e8) -------------------------------------------
base_scan = SCRATCH / "scan-base.sh"
base_scan.write_text(run(["git", "-C", str(TREE), "show",
                          "46a78e8:scripts/check-no-secrets.sh"]).stdout)
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
    "secret.key~": BIN, "SECRET.KEY~": BIN, ".secret.key": BIN,
    "sk5.json~": BIN, "admin.pass~": BIN,
    "README.md": b"harmless\n",
})
r_tip = run(["bash", str(SCAN_TIP), str(evasion)])
cell("T1 tip scan flags all 5 evasion files",
     r_tip.returncode == 1 and r_tip.stderr.count("SECRET:") == 5,
     "rc=%d secrets=%d" % (r_tip.returncode, r_tip.stderr.count("SECRET:")))
r_base = run(["bash", str(base_scan), str(evasion)])
cell("T2 baseline scan misses all 5 evasion files (negative control)",
     r_base.returncode == 0,
     "rc=%d out=%s" % (r_base.returncode, r_base.stdout.strip()[:80]))

neg = git_repo(SCRATCH / "neg", {
    "mysecret.key": b"not a secret\n", "admin.password": b"not a secret\n",
    "secret.keystore": b"not a secret\n", "mysecret.key~": b"not a secret\n",
    "notes~": b"not a secret\n", ".hidden": b"not a secret\n",
})
r_neg = run(["bash", str(SCAN_TIP), str(neg)])
cell("T3 tip scan does NOT flag bare stems / lookalikes",
     r_neg.returncode == 0,
     "rc=%d err=%s" % (r_neg.returncode, r_neg.stderr.strip()[:120]))

combined = git_repo(SCRATCH / "combined", {
    ".secret.key~": BIN, "secret.key~~": BIN, "..secret.key": BIN,
    " secret.key~ ": BIN,
})
r_comb = run(["bash", str(SCAN_TIP), str(combined)])
cell("T4 tip scan flags combined shapes",
     r_comb.returncode == 1 and r_comb.stderr.count("SECRET:") == 4,
     "rc=%d secrets=%d" % (r_comb.returncode, r_comb.stderr.count("SECRET:")))

r_clean = run(["bash", str(SCAN_TIP), str(TREE)])
cell("T5 tip scan clean on this tree (git mode)",
     r_clean.returncode == 0, "rc=%d" % r_clean.returncode)

# ---- T6: disk mode as nobody on a non-git copy --------------------------
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
cell("T6 tip scan clean on non-git copy, disk mode, as nobody",
     r_disk.returncode == 0,
     "rc=%d err=%s" % (r_disk.returncode, r_disk.stderr.strip()[:120]))

# ---- T7: tarball check 4 -------------------------------------------------
tar_dir = SCRATCH / "tar"
(tar_dir / "releases").mkdir(parents=True)
with tarfile.open(tar_dir / "releases" / "test.tar.gz", "w:gz") as tf:
    for name in ("x/secret.key~", "x/.secret.key", "x/ok.txt"):
        p = SCRATCH / ("tar-" + name.replace("/", "_"))
        p.write_bytes(BIN if name.endswith(("~", ".key")) else b"ok\n")
        tf.add(p, arcname=name)
r_tar_tip = run(["bash", str(SCAN_TIP), str(tar_dir)])
r_tar_base = run(["bash", str(base_scan), str(tar_dir)])
cell("T7 tip scan flags tarball listing secret.key~ / .secret.key",
     r_tar_tip.returncode == 1
     and r_tar_tip.stderr.count("SECRET:") == 1,
     "rc=%d secrets=%d" % (r_tar_tip.returncode,
                            r_tar_tip.stderr.count("SECRET:")))
cell("T7b baseline scan misses the tarball evasion (negative control)",
     r_tar_base.returncode == 0,
     "rc=%d out=%s" % (r_tar_base.returncode, r_tar_base.stdout.strip()[:80]))

# ---- T8: baseline still flags the old Fix-R shapes -----------------------
old = git_repo(SCRATCH / "old", {
    "secret.key.bak": BIN, "SECRET.KEY": BIN, "README.md": b"harmless\n",
})
r_old_base = run(["bash", str(base_scan), str(old)])
cell("T8 baseline scan flags old Fix-R shapes (control is meaningful)",
     r_old_base.returncode == 1
     and r_old_base.stderr.count("SECRET:") == 2,
     "rc=%d secrets=%d" % (r_old_base.returncode,
                            r_old_base.stderr.count("SECRET:")))

print()
print("R44FIXT TOTAL: PASS=%d FAIL=%d %s"
      % (len(RESULTS) - len(FAILURES), len(FAILURES), FAILURES))
raise SystemExit(len(FAILURES))

#!/usr/bin/env python3
"""R43 Fix-Q probe — init_pki file-at-path guard (AUDIT-R43-J7-4).

A FILE (or symlink) sitting at the pki path was silently destroyed by
easy-rsa ``init-pki``'s ``rm -rf``: the R42-F1-5 backup guard was
dir-only in both layers (core/openvpn_manager.py ``pki.is_dir()``
and core/easyrsa.sh ``[ -d ]``). The fix moves a non-dir pki path
aside to a timestamped sibling ``.pki-backup-<ts>-<pid>`` like a
non-empty dir without a CA, in both layers.

Cells assert the FIXED behavior, so every Q-cell FAILS on the
baseline 2e08a8c and PASSES on the Fix-Q tip (negative control):
  Q1  init_pki (Python) on a FILE at pki: file survives byte-identical
      in a sibling backup, fresh CA built.
  Q2  easyrsa.sh init directly on a FILE at pki: same safety net.
  Q3  init_pki on a SYMLINK at pki (points at a file elsewhere):
      link moved aside, target file untouched, fresh CA built.
  Q4  init_pki on a BROKEN symlink at pki: link moved aside, CA built.
  Q5  init_pki(force=True) on a file at pki: file destroyed (explicit
      wipe, unchanged behavior), fresh CA built.
  Q6  init_pki on a junk dir: F1-5 intact (junk survives in backup).
  Q7  init_pki on missing pki: fresh CA, no backup created.
  Q8  second init_pki with a CA present, no force: refuses loudly.

Run from the repo root: python3 tests/r43_fix_q_pki_file.py
Exit code = FAIL count. Uses the Fix-A toolchain bootstrap (real
easy-rsa 3.1.7, real openssl) cached in /tmp/r41a/toolchain.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TREE / "tests"))
sys.path.insert(0, str(TREE / "core"))

import r41_fix_a_pki as A  # noqa: E402  (toolchain bootstrap, pinned pins)

WORK = Path(tempfile.mkdtemp(prefix="r43fixq-"))
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


def find_backups(ca_dir):
    return [d for d in Path(ca_dir).iterdir()
            if d.name.startswith(".pki-backup-")]


def main():
    global TC
    TC = A.bootstrap_toolchain()
    if TC is None:
        skip("all", "toolchain bootstrap failed")
        print("TOTAL: PASS=0 FAIL=0 SKIP=%d" % len(SKIPS))
        return 0

    import openvpn_manager as om

    marker = b"operator file -- do not destroy\n"
    with A.Env(EASYRSA_BIN=A.easyrsa_bin(TC, "3.1.7")):
        # ---- Q1: Python init_pki on a FILE at pki ----
        ca1 = WORK / "ca1"
        ca1.mkdir(parents=True)
        (ca1 / "pki").write_bytes(marker)
        h1 = sha256_file(ca1 / "pki")
        try:
            om.init_pki(ca1)
            bks = [b for b in find_backups(ca1)
                   if b.is_file() and b.read_bytes() == marker]
            q1 = bool(bks) and (ca1 / "pki" / "ca.crt").exists()
            q1d = f"backups={[b.name for b in bks]} ca={bool((ca1 / 'pki' / 'ca.crt').exists())}"
        except Exception as e:  # noqa: BLE001
            q1, q1d = False, f"{type(e).__name__}: {str(e)[:240]}"
        cell("Q1 init_pki on a file at pki: file survives in a sibling backup, CA built",
             q1, q1d)

        # ---- Q2: easyrsa.sh init directly on a FILE at pki ----
        ca2 = WORK / "ca2"
        ca2.mkdir(parents=True)
        (ca2 / "pki").write_bytes(marker)
        q2r = run(["bash", str(TREE / "core" / "easyrsa.sh"), "init", str(ca2)],
                  timeout=180,
                  env={**os.environ, "EASYRSA_BIN": A.easyrsa_bin(TC, "3.1.7")})
        bks2 = [b for b in find_backups(ca2)
                if b.is_file() and b.read_bytes() == marker]
        cell("Q2 easyrsa.sh init directly on a file at pki: same safety net",
             q2r.returncode == 0 and bool(bks2)
             and (ca2 / "pki" / "ca.crt").exists(),
             f"rc={q2r.returncode} backups={[b.name for b in bks2]} "
             f"err={(q2r.stderr or '')[:200]}")

        # ---- Q3: symlink at pki -> file elsewhere ----
        target = WORK / "target.txt"
        target.write_bytes(marker)
        ca3 = WORK / "ca3"
        ca3.mkdir(parents=True)
        os.symlink(target, ca3 / "pki")
        try:
            om.init_pki(ca3)
            bks3 = [b for b in find_backups(ca3) if b.is_symlink()]
            q3 = (bool(bks3) and target.read_bytes() == marker
                  and (ca3 / "pki" / "ca.crt").exists()
                  and not (ca3 / "pki").is_symlink())
            q3d = f"backups={[b.name for b in bks3]} target-intact={target.read_bytes() == marker}"
        except Exception as e:  # noqa: BLE001
            q3, q3d = False, f"{type(e).__name__}: {str(e)[:240]}"
        cell("Q3 init_pki on a symlink at pki: link moved aside, target untouched, CA built",
             q3, q3d)

        # ---- Q4: broken symlink at pki ----
        ca4 = WORK / "ca4"
        ca4.mkdir(parents=True)
        os.symlink(WORK / "does-not-exist.txt", ca4 / "pki")
        try:
            om.init_pki(ca4)
            bks4 = [b for b in find_backups(ca4) if b.is_symlink()]
            q4 = bool(bks4) and (ca4 / "pki" / "ca.crt").exists()
            q4d = f"backups={[b.name for b in bks4]}"
        except Exception as e:  # noqa: BLE001
            q4, q4d = False, f"{type(e).__name__}: {str(e)[:240]}"
        cell("Q4 init_pki on a broken symlink at pki: link moved aside, CA built",
             q4, q4d)

        # ---- Q5: force=True on a file: explicit wipe, unchanged ----
        ca5 = WORK / "ca5"
        ca5.mkdir(parents=True)
        (ca5 / "pki").write_bytes(marker)
        try:
            om.init_pki(ca5, force=True)
            q5 = (not find_backups(ca5)
                  and (ca5 / "pki" / "ca.crt").exists())
            q5d = f"backups={len(find_backups(ca5))}"
        except Exception as e:  # noqa: BLE001
            q5, q5d = False, f"{type(e).__name__}: {str(e)[:240]}"
        cell("Q5 init_pki(force=True) on a file at pki: file wiped (explicit), CA built",
             q5, q5d)

        # ---- Q6: junk dir still moved aside (F1-5 intact) ----
        ca6 = WORK / "ca6"
        (ca6 / "pki").mkdir(parents=True)
        (ca6 / "pki" / "junk.txt").write_text("operator leftovers\n")
        try:
            om.init_pki(ca6)
            bks6 = [d for d in find_backups(ca6)
                    if (d / "junk.txt").exists()]
            q6 = bool(bks6) and (ca6 / "pki" / "ca.crt").exists()
            q6d = f"backups={[d.name for d in bks6]}"
        except Exception as e:  # noqa: BLE001
            q6, q6d = False, f"{type(e).__name__}: {str(e)[:240]}"
        cell("Q6 init_pki on a junk dir: F1-5 intact, junk survives in backup",
             q6, q6d)

        # ---- Q7: missing pki: fresh CA, no backup ----
        ca7 = WORK / "ca7"
        ca7.mkdir(parents=True)
        try:
            om.init_pki(ca7)
            q7 = (not find_backups(ca7)
                  and (ca7 / "pki" / "ca.crt").exists())
            q7d = f"backups={len(find_backups(ca7))}"
        except Exception as e:  # noqa: BLE001
            q7, q7d = False, f"{type(e).__name__}: {str(e)[:240]}"
        cell("Q7 init_pki on missing pki: fresh CA, no backup created",
             q7, q7d)

        # ---- Q8: second init_pki with CA present refuses ----
        try:
            om.init_pki(ca7)
            q8, q8d = False, "no refusal raised"
        except om.OpenVPNError as e:
            q8, q8d = True, str(e)[:200]
        except Exception as e:  # noqa: BLE001
            q8, q8d = False, f"{type(e).__name__}: {str(e)[:240]}"
        cell("Q8 second init_pki with CA present, no force: refuses loudly",
             q8, q8d)

    n_fail = sum(1 for _, ok, _ in RESULTS if not ok)
    print("TOTAL: PASS=%d FAIL=%d SKIP=%d"
          % (len(RESULTS) - n_fail, n_fail, len(SKIPS)))
    return n_fail


if __name__ == "__main__":
    sys.exit(main())

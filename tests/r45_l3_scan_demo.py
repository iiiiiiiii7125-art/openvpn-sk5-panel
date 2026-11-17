#!/usr/bin/env python3
"""R45-L3 scan-probe-gap demonstrations (R45-L3-3, R45-L3-4).

The F6 probe (tests/r42_fix_l.py) S2 and S5 never isolate the check
they claim to guard, because the planted fixture also trips check 1:
- S2 plants the OpenVPN static-key block in a file NAMED ta.key, so
  check 1 flags it by filename alone -- removing check 3's static-key
  grep leaves S2 green.
- S5 builds a tarball listing ta.key from a pkg/ dir that ALSO holds
  the loose file pkg/ta.key, so check 1 flags the loose file --
  removing check 4 leaves S5 green.

This script proves each pattern/loop is genuinely unguarded by
planting WITHOUT any check-1 trigger: the static-key block in a
benign-named notes.txt, and a tarball listing ta.key with no loose
sensitive file in the scan target. Baseline scan must flag both
(rc=1); the mutant scans (from the s-check3 / s-check4 mutant copies,
rebuilt here by the same edits) must pass both clean (rc=0).
Run: python3 tests/r45_l3_scan_demo.py
Exit 0 = both gaps demonstrated.
"""
import os
import shutil
import subprocess
import sys
import tempfile

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_SCAN = os.path.join(TREE, "scripts", "check-no-secrets.sh")

TA = (b"-----BEGIN " + b"OpenVPN Static key V1-----\n"
      + b"0123456789abcdef" * 4 + b"\n"
      + b"-----END " + b"OpenVPN Static key V1-----\n")


def scan(script, target):
    r = subprocess.run(["bash", script, target],
                       capture_output=True, text=True)
    return r.returncode


def mutant_scan(name, edit):
    """Copy the scan script, apply edit, return its path."""
    d = tempfile.mkdtemp(prefix="r45l3-scanmut-")
    dst = os.path.join(d, "check-no-secrets.sh")
    shutil.copy(BASE_SCAN, dst)
    text = open(dst, encoding="utf-8").read()
    text = edit(text)
    open(dst, "w", encoding="utf-8").write(text)
    return dst


def no_static_key(text):
    # s-check3: drop the ENCRYPTED alternative and the static-key grep.
    # Line-based (the grep pattern's backslashes make a literal
    # whole-string replace fragile): rewrite the single check-3
    # invocation line that references $_TA_BEGIN.
    lines = text.splitlines(keepends=True)
    n = 0
    out = []
    for ln in lines:
        if "_TA_BEGIN" in ln and ln.strip().startswith("$(_grep '-----BEGIN"):
            out.append("$(_grep '-----BEGIN \\(RSA \\|EC \\|OPENSSH \\|DSA \\)\\?PRIVATE KEY-----')\n")
            n += 1
        else:
            out.append(ln)
    assert n == 1, "check-3 invocation line not found"
    return "".join(out)


def no_check4(text):
    # s-check4: drop the whole check-4 tarball loop.
    start = text.index("# --- 4. release tarballs")
    end = text.index('if [ "$FAIL" -eq 0 ]; then')
    return text[:start] + text[end:]


def main():
    ok = True
    # R45-L3-3: static key in a benign-named file.
    d = tempfile.mkdtemp(prefix="r45l3-demo3-")
    open(os.path.join(d, "notes.txt"), "wb").write(TA)
    m3 = mutant_scan("s-check3", no_static_key)
    base, mut = scan(BASE_SCAN, d), scan(m3, d)
    print("DEMO3 static-key-in-notes.txt baseline rc=%s mutant rc=%s"
          % (base, mut))
    ok = ok and base == 1 and mut == 0
    shutil.rmtree(d, ignore_errors=True)
    # R45-L3-4: tarball listing ta.key, no loose sensitive file.
    d = tempfile.mkdtemp(prefix="r45l3-demo4-")
    src = tempfile.mkdtemp(prefix="r45l3-demo4src-")
    open(os.path.join(src, "ta.key"), "wb").write(TA)
    open(os.path.join(src, "README.md"), "wb").write(b"docs\n")
    os.makedirs(os.path.join(d, "releases"))
    subprocess.run(["tar", "czf",
                    os.path.join(d, "releases", "ovpn-release-test.tar.gz"),
                    "-C", src, "."], check=True)
    shutil.rmtree(src, ignore_errors=True)
    m4 = mutant_scan("s-check4", no_check4)
    base, mut = scan(BASE_SCAN, d), scan(m4, d)
    print("DEMO4 tarball-only baseline rc=%s mutant rc=%s" % (base, mut))
    ok = ok and base == 1 and mut == 0
    shutil.rmtree(d, ignore_errors=True)
    print("SCAN-DEMO:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

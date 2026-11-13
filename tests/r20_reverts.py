#!/usr/bin/env python3
"""AUDIT-R20 revert mutants for BJ's two fixes in cloudflare/src/index.js.

m-kvarray: kvArray helper reverted to identity (return value as-is) —
restores pre-BJ behavior at all 11 queue/sent read points.
m-dlguard: the snapshot-users guard in handleCompatOvpnDownload removed —
restores pre-BJ download behavior (revoked/expired still 200).

Usage: python3 tests/r20_reverts.py  (builds /tmp/r20/mutants/<name>)
"""
import re
import shutil
import sys
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
OUT = Path("/tmp/r20/mutants")
SRC = TREE / "cloudflare/src/index.js"


def build(name, transform):
    dst = OUT / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(TREE, dst, ignore=shutil.ignore_patterns(
        "__pycache__", ".git", "panel/data"))
    p = dst / "cloudflare/src/index.js"
    s = p.read_text()
    s2 = transform(s)
    assert s2 != s, f"{name}: transform did not change the file"
    p.write_text(s2)
    print(f"built {dst}")


def t_kvarray(s):
    # Faithful single-layer revert: restore exactly the pre-BJ inline
    # semantics `(await kvGetJson(...)) || []` — null/undefined fall back
    # to [], non-array truthy values pass through (and later .push/.filter
    # throw). A plain identity revert would ALSO break the null case the
    # original code already handled, and is not a faithful revert.
    old = """function kvArray(value, key) {
  if (Array.isArray(value)) return value;
  if (value === null || value === undefined) return [];
  console.warn(`kv container ${key} is not an array (${typeof value}); treating as empty`);
  return [];
}"""
    assert old in s, "kvArray definition not found"
    return s.replace(old, """function kvArray(value, key) {
  if (value === null || value === undefined) return [];
  return value;
}""", 1)


def t_dlguard(s):
    # Remove the snapshot guard block in handleCompatOvpnDownload, from the
    # R19-P2-2 comment through the expired-check closing brace.
    start = s.index("  // R19-P2-2")
    end = s.index("  return new Response(rec.ovpn,", start)
    block = s[start:end]
    assert "revoked" in block and "expired" in block, "guard block mismatch"
    return s[:start] + s[end:]


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    build("m-kvarray", t_kvarray)
    build("m-dlguard", t_dlguard)
    print("done")

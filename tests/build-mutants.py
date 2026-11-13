#!/usr/bin/env python3
"""AUDIT-R17 gate mutant builder (rebuilt from mechanism, independent of R16/BE builders).

Builds mutant trees from a clean tree copy, each mutating exactly one
predicate point of verify-integration.sh §7 (two-layer hash pin check):
  layer 1: 4 named constants install.sh <-> agent.py, key-by-key, non-empty
  layer 2: _PINNED_SHA256 dict binding (binary,arch) -> CONSTANT name,
           value == install.sh assignment, exactly 4 entries.

Usage: python3 build-mutants.py <clean-tree-dir> <out-dir>
Mutants:
  m-dict-sb      dict sing-box amd64/arm64 values swapped (constants untouched)
  m-dict-ts      dict tun2socks amd64/arm64 values swapped
  m-dict-x-amd   dict sing-box amd64 <-> tun2socks amd64 (same arch, cross-binary)
  m-dict-x-arm   dict sing-box arm64 <-> tun2socks arm64 (same arch, cross-binary)
  m-dict-x-a     dict sing-box amd64 <-> tun2socks arm64 (cross-binary, cross-arch)
  m-dict-x-b     dict sing-box arm64 <-> tun2socks amd64 (cross-binary, cross-arch)
  m-dict-missing dict loses one entry (3 items)
  m-dict-extra   dict gains a bogus 5th entry ("sing-box","arm")
  m-const-sb     agent.py sing-box constant VALUES swapped
  m-install-sb   install.sh sing-box assignment VALUES swapped
  m-char         one hex char changed in agent.py SINGBOX_SHA256_AMD64
The four m-dict-x-* mutants complete the C(4,2)=6 pairwise dict swaps
(R24): layer 2 computes the expected constant name from BOTH the
binary and the arch, so a same-arch cross-binary swap must also go
red -- it only exercises the binary half of the name check.
Each mutant asserts exactly one edit site (unique hit) before writing.
"""
import re
import shutil
import sys
from pathlib import Path

SB_AMD64 = "950af37eb2d7e55dddae34a18411cd617303fd99d2dc75bc76b6dd9fcd97d9c5"
SB_ARM64 = "20a6a9cd259a95411599f811a5066513a98db63705a51121252ad27daf96c029"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    assert n == 1, f"{label}: expected 1 hit, got {n}"
    return text.replace(old, new, 1)


def main() -> None:
    src = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2]).resolve()
    agent = src / "agent" / "agent.py"
    agent_text = agent.read_text()
    install = src / "install.sh"
    install_text = install.read_text()
    # sanity: constants and dict entries present exactly as expected
    assert SB_AMD64 in agent_text and SB_ARM64 in agent_text
    dict_sb = (
        '    ("sing-box", "amd64"): SINGBOX_SHA256_AMD64,\n'
        '    ("sing-box", "arm64"): SINGBOX_SHA256_ARM64,'
    )
    dict_ts = (
        '    ("tun2socks", "amd64"): TUN2SOCKS_SHA256_AMD64,\n'
        '    ("tun2socks", "arm64"): TUN2SOCKS_SHA256_ARM64,'
    )
    assert agent_text.count(dict_sb) == 1 and agent_text.count(dict_ts) == 1

    def fresh(name: str) -> Path:
        d = out / name
        if d.exists():
            shutil.rmtree(d)
        shutil.copytree(src, d, ignore=shutil.ignore_patterns("__pycache__"))
        return d

    # m-dict-sb: swap dict values only
    d = fresh("m-dict-sb")
    p = d / "agent" / "agent.py"
    p.write_text(replace_once(p.read_text(), dict_sb,
        '    ("sing-box", "amd64"): SINGBOX_SHA256_ARM64,\n'
        '    ("sing-box", "arm64"): SINGBOX_SHA256_AMD64,', "m-dict-sb"))
    # m-dict-ts
    d = fresh("m-dict-ts")
    p = d / "agent" / "agent.py"
    p.write_text(replace_once(p.read_text(), dict_ts,
        '    ("tun2socks", "amd64"): TUN2SOCKS_SHA256_ARM64,\n'
        '    ("tun2socks", "arm64"): TUN2SOCKS_SHA256_AMD64,', "m-dict-ts"))
    # m-dict-x-*: cross-binary pairwise swaps (R24: completes C(4,2)=6).
    # Each swaps the CONSTANT names bound to two keys; constants untouched.
    # The two keys are not adjacent in the file, so each mutant replaces
    # the whole four-line dict block.
    dict_all = dict_sb + "\n" + dict_ts
    d = fresh("m-dict-x-amd")
    p = d / "agent" / "agent.py"
    p.write_text(replace_once(p.read_text(), dict_all,
        '    ("sing-box", "amd64"): TUN2SOCKS_SHA256_AMD64,\n'
        '    ("sing-box", "arm64"): SINGBOX_SHA256_ARM64,\n'
        '    ("tun2socks", "amd64"): SINGBOX_SHA256_AMD64,\n'
        '    ("tun2socks", "arm64"): TUN2SOCKS_SHA256_ARM64,', "m-dict-x-amd"))
    d = fresh("m-dict-x-arm")
    p = d / "agent" / "agent.py"
    p.write_text(replace_once(p.read_text(), dict_all,
        '    ("sing-box", "amd64"): SINGBOX_SHA256_AMD64,\n'
        '    ("sing-box", "arm64"): TUN2SOCKS_SHA256_ARM64,\n'
        '    ("tun2socks", "amd64"): TUN2SOCKS_SHA256_AMD64,\n'
        '    ("tun2socks", "arm64"): SINGBOX_SHA256_ARM64,', "m-dict-x-arm"))
    d = fresh("m-dict-x-a")
    p = d / "agent" / "agent.py"
    p.write_text(replace_once(p.read_text(), dict_all,
        '    ("sing-box", "amd64"): TUN2SOCKS_SHA256_ARM64,\n'
        '    ("sing-box", "arm64"): SINGBOX_SHA256_ARM64,\n'
        '    ("tun2socks", "amd64"): TUN2SOCKS_SHA256_AMD64,\n'
        '    ("tun2socks", "arm64"): SINGBOX_SHA256_AMD64,', "m-dict-x-a"))
    d = fresh("m-dict-x-b")
    p = d / "agent" / "agent.py"
    p.write_text(replace_once(p.read_text(), dict_all,
        '    ("sing-box", "amd64"): SINGBOX_SHA256_AMD64,\n'
        '    ("sing-box", "arm64"): TUN2SOCKS_SHA256_AMD64,\n'
        '    ("tun2socks", "amd64"): SINGBOX_SHA256_ARM64,\n'
        '    ("tun2socks", "arm64"): TUN2SOCKS_SHA256_ARM64,', "m-dict-x-b"))
    # m-dict-missing: drop tun2socks arm64 entry
    d = fresh("m-dict-missing")
    p = d / "agent" / "agent.py"
    p.write_text(replace_once(p.read_text(),
        '    ("tun2socks", "arm64"): TUN2SOCKS_SHA256_ARM64,\n', "", "m-dict-missing"))
    # m-dict-extra: bogus 5th entry
    d = fresh("m-dict-extra")
    p = d / "agent" / "agent.py"
    p.write_text(replace_once(p.read_text(), dict_ts,
        dict_ts + '\n    ("sing-box", "arm"): SINGBOX_SHA256_AMD64,', "m-dict-extra"))
    # m-const-sb: swap constant VALUES (dict untouched)
    d = fresh("m-const-sb")
    p = d / "agent" / "agent.py"
    t = p.read_text()
    t = replace_once(t, f'SINGBOX_SHA256_AMD64 = (\n    "{SB_AMD64}"',
                     f'SINGBOX_SHA256_AMD64 = (\n    "{SB_ARM64}"', "m-const-sb/1")
    t = replace_once(t, f'SINGBOX_SHA256_ARM64 = (\n    "{SB_ARM64}"',
                     f'SINGBOX_SHA256_ARM64 = (\n    "{SB_AMD64}"', "m-const-sb/2")
    p.write_text(t)
    # m-install-sb: swap install.sh assignment VALUES
    d = fresh("m-install-sb")
    p = d / "install.sh"
    t = p.read_text()
    t = replace_once(t, f'SINGBOX_SHA256_AMD64="{SB_AMD64}"',
                     f'SINGBOX_SHA256_AMD64="{SB_ARM64}"', "m-install-sb/1")
    t = replace_once(t, f'SINGBOX_SHA256_ARM64="{SB_ARM64}"',
                     f'SINGBOX_SHA256_ARM64="{SB_AMD64}"', "m-install-sb/2")
    p.write_text(t)
    # m-char: one hex char in agent.py amd64 constant
    d = fresh("m-char")
    p = d / "agent" / "agent.py"
    t = p.read_text()
    assert SB_AMD64 in t
    p.write_text(t.replace(SB_AMD64, "8" + SB_AMD64[1:], 1))
    print("built 11 mutants in", out)


if __name__ == "__main__":
    main()

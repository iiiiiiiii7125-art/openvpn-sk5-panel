#!/usr/bin/env python3
"""AUDIT-R21 revert mutants for BK / BL / BM fixes.

m-validate:  delete the `_validate_stored(cfg)` call in _load_config —
             restores pre-BK behavior (stored port bool/float laundered).
m-heartbeat: drop the isinstance guard in heartbeat_status — restores
             pre-BL behavior (list-shaped sk5.json raises AttributeError).
m-blackhole: delete the fallback-blackhole install block in
             policy-routing.sh enable — restores pre-BM empty-table
             fall-through (R13-BUG-1 layer 1).
m-repair:    replace the _repair_policy() call in check_health with a
             forced failure — restores pre-BM report-only behavior
             (R13-BUG-1 layer 2).

Usage: python3 tests/r21_reverts.py  (builds /tmp/r21/mutants/<name>)
"""
import shutil
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
OUT = Path("/tmp/r21/mutants")


def build(name, relpath, transform):
    dst = OUT / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(TREE, dst, ignore=shutil.ignore_patterns(
        "__pycache__", ".git", "panel/data"))
    p = dst / relpath
    s = p.read_text()
    s2 = transform(s)
    assert s2 != s, f"{name}: transform did not change the file"
    p.write_text(s2)
    print(f"built {dst}")


def t_validate(s):
    old = "        _validate_stored(cfg)  # R20-P2-1: reject bad shapes, never launder\n"
    assert old in s, "_validate_stored call not found"
    return s.replace(old, "", 1)


def t_heartbeat(s):
    old = """            parsed = json.loads(sk5_cfg.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                sk5_enabled = bool(parsed.get("enabled"))"""
    assert old in s, "heartbeat isinstance guard not found"
    return s.replace(old, """            parsed = json.loads(sk5_cfg.read_text(encoding="utf-8"))
            sk5_enabled = bool(parsed.get("enabled"))""", 1)


def t_blackhole(s):
    # Faithful single-layer revert (mirrors the controller's BM check):
    # remove BOTH the blackhole install block and the blackhole self-check
    # block, restoring the pre-BM enable path exactly. Removing only the
    # install would make enable die loudly at the self-check instead of
    # silently shipping a chain with no fallback — a different mechanism.
    start = s.index('    if ! _bh_err="$(ip route replace blackhole default metric 200')
    end = s.index("    fi\n", start) + len("    fi\n")
    block = s[start:end]
    assert "die \"cannot install table" in block, "blackhole block mismatch"
    s = s[:start] + s[end:]
    start2 = s.index('    if ! ip route show table "$TABLE" 2>/dev/null | grep "^blackhole default"')
    end2 = s.index("    fi\n", start2) + len("    fi\n")
    block2 = s[start2:end2]
    assert "fallback blackhole route did not stick" in block2, "self-check block mismatch"
    return s[:start2] + s[end2:]


def t_repair(s):
    old = "        repaired, repair_note = _repair_policy()\n"
    assert old in s, "_repair_policy call not found"
    return s.replace(old, "        repaired, repair_note = False, \"repair disabled (mutant)\"\n", 1)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    build("m-validate", "egress/sk5_manager.py", t_validate)
    build("m-heartbeat", "agent/agent.py", t_heartbeat)
    build("m-blackhole", "egress/policy-routing.sh", t_blackhole)
    build("m-repair", "egress/sk5_manager.py", t_repair)
    print("done")

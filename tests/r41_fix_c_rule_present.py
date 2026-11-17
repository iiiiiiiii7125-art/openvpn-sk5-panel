#!/usr/bin/env python3
"""R41 Fix-C probe: _rule_present() must match ONE `ip rule` line.

Reproduces R41-L4-P2-1 (E2 N7): with rules
  `from 10.8.0.0/24 lookup 200` + `from 192.168.0.0/24 lookup 100`
the old whole-output substring check returned True while VPN traffic
went direct. The fix mirrors rule_exists() in policy-routing.sh:
priority 100, our selector, table 100 -- on a single line.

Usage: python3 tests/r41_fix_c_rule_present.py [path/to/sk5_manager.py]
Exit 0 iff every case matches its expectation.
"""

import importlib.util
import subprocess
import sys

MODULE = sys.argv[1] if len(sys.argv) > 1 else "egress/sk5_manager.py"


def load(path):
    spec = importlib.util.spec_from_file_location("sm_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# (name, canned `ip rule show` stdout, expected _rule_present())
CASES = [
    # L4 E2 N7 verbatim: halves on different rules -> False.
    ("n7-cross-line", "0:\tfrom all lookup local\n"
     "200:\tfrom 10.8.0.0/24 lookup 200\n"
     "150:\tfrom 192.168.0.0/24 lookup 100\n"
     "32766:\tfrom all lookup main\n", False),
    # The product's own rule -> True.
    ("own-rule", "0:\tfrom all lookup local\n"
     "100:\tfrom 10.8.0.0/24 lookup 100\n"
     "32766:\tfrom all lookup main\n", True),
    # Same selector at another priority is a duplicate, not our rule
    # (rule_exists() in policy-routing.sh treats it the same way).
    ("same-selector-other-prio", "200:\tfrom 10.8.0.0/24 lookup 100\n", False),
    # Same rule with trailing fields -> True.
    ("trailing-fields", "100:\tfrom 10.8.0.0/24 lookup 100 proto static\n", True),
    # lookup 1000 must not match as lookup 100.
    ("lookup-1000", "100:\tfrom 10.8.0.0/24 lookup 1000\n", False),
    # No rules at all -> False.
    ("empty", "", False),
    # Selector present but no table-100 lookup anywhere -> False.
    ("selector-only", "200:\tfrom 10.8.0.0/24 lookup 200\n", False),
]


def main():
    sm = load(MODULE)
    fails = 0
    for name, stdout, expected in CASES:
        sm._run = lambda cmd, timeout=30, _out=stdout: subprocess.CompletedProcess(
            cmd, 0, stdout=_out, stderr="")
        got = sm._rule_present()
        status = "PASS" if got == expected else "FAIL"
        if got != expected:
            fails += 1
        print(f"{status}: {name}: _rule_present()={got} expected={expected}")
    print(f"result: {len(CASES) - fails}/{len(CASES)} pass")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

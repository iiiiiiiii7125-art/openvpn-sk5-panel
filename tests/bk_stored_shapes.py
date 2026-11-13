#!/usr/bin/env python3
"""BK fix probe (bk_stored_shapes.py) — stored sk5.json shape checks added
by the R20-P2-1 fix in egress/sk5_manager.py::_validate_stored.

Covers what the R20 probe does not:
  B1: stored port as a digit string ("1194") -> ValueError (rejected;
      the stored file is machine-written with ints only -- panel
      _valid_port and agent _as_int both deliver ints; _as_int's
      digit-string tolerance exists only on the wire param path).
  B2: stored "enabled": "false" (string) -> ValueError (bool("false")
      == True would otherwise silently enable the chain -- R12-P2-1's
      mechanism on the stored face).
  B3: stored "udp_over_tcp": "false" (string) -> ValueError (same).
  B4: stored 0/1 ints for the bool switches are accepted and normalized
      to real bools (R12-pinned panel tolerance).
  B5: get_status() degrades with config_error (not a 500) on a bad
      stored port -- its documented "rather than a 500" contract.
  B6: current_egress_ip() returns None on a bad stored port -- its
      "unreadable config: no egress claim" contract.
  B7: stored port 0 / 70000 -> ValueError (range part of the check).

Run: python3 tests/bk_stored_shapes.py
Exit code = number of FAILs.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TREE / "egress"))

RESULTS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + detail) if detail else ""))


BASE = {"host": "127.0.0.1", "port": 1194, "username": "",
        "password": "", "enabled": False, "fail_open": False,
        "udp_over_tcp": False}


def fresh_import(d):
    os.environ["OVPN_SK5_CONFIG_DIR"] = d
    for m in [m for m in list(sys.modules) if m == "sk5_manager"]:
        del sys.modules[m]
    import sk5_manager
    return sk5_manager


def main():
    # B1: digit-string port rejected.
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "sk5.json").write_text(
            json.dumps({**BASE, "port": "1194"}), encoding="utf-8")
        m = fresh_import(d)
        try:
            m.set_sk5()
            cell("B1 digit-string port rejected", False, "no error raised")
        except ValueError as exc:
            cell("B1 digit-string port rejected", True, str(exc)[:80])

    # B2/B3: string bools rejected.
    for key in ("enabled", "udp_over_tcp"):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "sk5.json").write_text(
                json.dumps({**BASE, key: "false"}), encoding="utf-8")
            m = fresh_import(d)
            try:
                m.set_sk5()
                cell(f"B2/3 stored {key}='false' rejected", False,
                     "no error raised")
            except ValueError as exc:
                cell(f"B2/3 stored {key}='false' rejected", True,
                     str(exc)[:80])

    # B4: 0/1 ints accepted and normalized to bool.
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "sk5.json").write_text(
            json.dumps({**BASE, "enabled": 1, "fail_open": 0,
                        "udp_over_tcp": 1}), encoding="utf-8")
        m = fresh_import(d)
        try:
            cfg = m._load_config()
            cell("B4 stored 0/1 bools normalized",
                 cfg["enabled"] is True and cfg["fail_open"] is False
                 and cfg["udp_over_tcp"] is True,
                 f"enabled={cfg['enabled']!r} fail_open={cfg['fail_open']!r}")
        except Exception as exc:
            cell("B4 stored 0/1 bools normalized", False, str(exc))

    # B5: get_status degrades with config_error on bad stored port.
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "sk5.json").write_text(
            json.dumps({**BASE, "port": True}), encoding="utf-8")
        m = fresh_import(d)
        try:
            st = m.get_status()
            cell("B5 get_status degrades with config_error",
                 "config_error" in st and "port" in st["config_error"],
                 f"config_error={st.get('config_error')!r}"[:100])
        except Exception as exc:
            cell("B5 get_status degrades with config_error", False,
                 f"raised {type(exc).__name__}: {exc}")

    # B6: current_egress_ip returns None on bad stored port.
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "sk5.json").write_text(
            json.dumps({**BASE, "port": 1194.5}), encoding="utf-8")
        m = fresh_import(d)
        try:
            ip = m.current_egress_ip()
            cell("B6 current_egress_ip None on bad port", ip is None,
                 f"ip={ip!r}")
        except Exception as exc:
            cell("B6 current_egress_ip None on bad port", False,
                 f"raised {type(exc).__name__}: {exc}")

    # B7: out-of-range ports rejected.
    for bad in (0, 70000):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "sk5.json").write_text(
                json.dumps({**BASE, "port": bad}), encoding="utf-8")
            m = fresh_import(d)
            try:
                m.set_sk5()
                cell(f"B7 stored port={bad} rejected", False,
                     "no error raised")
            except ValueError:
                cell(f"B7 stored port={bad} rejected", True)

    fails = sum(1 for _, ok in RESULTS if not ok)
    print(f"\nTOTAL {len(RESULTS)} cells, FAIL {fails}: "
          f"{[n for n, ok in RESULTS if not ok]}")
    return fails


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""AUDIT-R17 agent probe (r17_agent.py) — _as_int, pin binding, whitelist.

Drives agent/agent.py directly (real code paths, no panel needed).
Cells A1..A2x; exit code = FAIL count.
"""
import os
import sys
from pathlib import Path

TREE = Path(os.environ.get("R17_TREE", "/tmp/r17/ptree"))
sys.path.insert(0, str(TREE / "agent"))

import agent  # noqa: E402

RESULTS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (" | " + detail if detail else ""))


def raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except Exception as e:  # noqa: BLE001
        return e


def main():
    # ---------- A1 _as_int (R13-P2-5) ----------
    for val, label, want in [(1194, "int", 1194), ("1194", "digit str", 1194),
                             (True, "bool True", None), (False, "bool False", None),
                             (1194.5, "float", None), ("12x", "bad str", None),
                             (None, "None", None), ([1194], "list", None),
                             (0, "0 out of range", None), (65536, "65536 out of range", None)]:
        e = raises(agent._as_int, val, "port")
        if want is None:
            cell(f"A1-01 _as_int {label} raises", e is not None, str(e)[:60] if e else "no raise")
        else:
            try:
                got = agent._as_int(val, "port")
                cell(f"A1-01 _as_int {label} == {want}", got == want, str(got))
            except Exception as exc:  # noqa: BLE001
                cell(f"A1-01 _as_int {label} == {want}", False, f"raised {exc}")
    e = raises(agent._as_bool, "false", "enabled")
    cell("A1-02 _as_bool str 'false' raises", e is not None, str(e)[:60] if e else "no raise")
    e = raises(agent._as_bool, 1, "enabled")
    cell("A1-03 _as_bool int 1 raises", e is not None, str(e)[:60] if e else "no raise")
    # ---------- A2 pin binding ----------
    cell("A2-01 _pinned_sha256(sing-box,amd64) == 950af37e…",
         agent._pinned_sha256("sing-box", "amd64").startswith("950af37e"), "")
    cell("A2-02 _pinned_sha256(sing-box,arm64) == 20a6a9cd…",
         agent._pinned_sha256("sing-box", "arm64").startswith("20a6a9cd"), "")
    cell("A2-03 _pinned_sha256(tun2socks,amd64) == a612baa2…",
         agent._pinned_sha256("tun2socks", "amd64").startswith("a612baa2"), "")
    cell("A2-04 _pinned_sha256(tun2socks,arm64) == 3931476c…",
         agent._pinned_sha256("tun2socks", "arm64").startswith("3931476c"), "")
    cell("A2-05 _pinned_sha256 unknown pair empty",
         agent._pinned_sha256("gost", "amd64") == "", "")
    d = agent._PINNED_SHA256
    cell("A2-06 dict has exactly 4 entries", len(d) == 4, str(len(d)))
    cell("A2-07 dict keys match constant names",
         d[("sing-box", "amd64")] is agent.SINGBOX_SHA256_AMD64
         and d[("sing-box", "arm64")] is agent.SINGBOX_SHA256_ARM64
         and d[("tun2socks", "amd64")] is agent.TUN2SOCKS_SHA256_AMD64
         and d[("tun2socks", "arm64")] is agent.TUN2SOCKS_SHA256_ARM64, "")
    # ---------- A3 whitelist / shell-key rejection ----------
    cell("A3-01 ACTIONS == 13", len(agent.ACTIONS) == 13, str(sorted(agent.ACTIONS)))
    cell("A3-02 ACTIONS matches panel AGENT_ACTIONS",
         set(agent.ACTIONS) == {"install_prereqs", "init_pki", "create_server",
                                "start_openvpn", "stop_openvpn", "restart_openvpn",
                                "create_user", "revoke_user", "set_sk5", "test_sk5",
                                "enable_sk5", "disable_sk5", "get_status"}, "")
    for key in ("command", "shell", "cmd", "exec", "script", "argv"):
        ok, _res, err = agent.execute_command(
            {"id": "t", "action": "create_user", "params": {key: "id", "name": "alice"}})
        cell(f"A3-03 shell key '{key}' rejected", ok is False and "forbidden param" in (err or ""),
             str(err)[:60])
    ok, _res, err = agent.execute_command({"id": "t", "action": "rm_rf", "params": {}})
    cell("A3-04 unknown action rejected", ok is False and "unknown action" in (err or ""),
         str(err)[:60])
    ok, _res, err = agent.execute_command(
        {"id": "t", "action": "create_user", "params": {"name": "../evil"}})
    cell("A3-05 create_user bad username rejected", ok is False, str(err)[:60])
    ok, _res, err = agent.execute_command(
        {"id": "t", "action": "create_user", "params": {"name": "alice"}})
    cell("A3-06 create_user no-CA fails honestly (not crash)",
         ok is False and err is not None, str(err)[:80])
    ok, _res, err = agent.execute_command(
        {"id": "t", "action": "set_sk5", "params": {"port": True}})
    cell("A3-07 set_sk5 port=True rejected", ok is False and "bool" in (err or ""),
         str(err)[:80])
    ok, _res, err = agent.execute_command(
        {"id": "t", "action": "get_status", "params": "not-a-dict"})
    cell("A3-08 non-dict params rejected", ok is False, str(err)[:60])
    # load_config with no config file must error, never silently default
    e = raises(agent.load_config)
    cell("A3-08 load_config with no config errors", e is not None, str(e)[:60] if e else "no raise")

    fails = [n for n, ok, _ in RESULTS if not ok]
    print(f"\nTOTAL {len(RESULTS)} cells, FAIL {len(fails)}: {fails}")
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())

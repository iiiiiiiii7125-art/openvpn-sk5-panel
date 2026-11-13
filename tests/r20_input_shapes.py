#!/usr/bin/env python3
"""AUDIT-R20 input-shape probe (r20_input_shapes.py) — stored-config and
agent-heartbeat input shapes not covered by earlier suites.

S1/S2: stored sk5.json with a bool/float port reaches egress set_sk5()
  with port=None (toggle-only save / enable flip keeps the stored value).
  set_sk5() does int(cfg["port"]) BEFORE _validate (so the isinstance
  check is dead against both), and _render_singbox_config() does
  str(int(cfg["port"])) with no guard of its own — the bool is laundered
  to port 1 and the float is truncated in the LIVE sing-box config
  (same root cause as R13-P2-5, which only closed the action-param
  path via agent _as_int; the stored-config path was never closed).
  The saved file itself keeps the original shape (int() is never
  assigned back), so the assertion is on the rendered config.
S3/S4/S5: controls (bad string port -> ValueError; int port kept; list
  config -> RuntimeError).
S6: agent heartbeat_status() reads /etc/openvpn-sk5-panel/sk5.json and
  calls .get("enabled") on the parsed value; a JSON list makes .get raise
  AttributeError, which the (OSError, ValueError) handler does not catch,
  so every poll_once() raises before any network call and the node goes
  silently stale (run_once catches it per cycle and backs off). Runs in a
  private mount namespace with a bind mount over /etc/openvpn-sk5-panel.
S7: OPENVPN_PORT="abc" makes `int(os.environ.get("OPENVPN_PORT", "1194"))`
  raise ValueError at core import time (module level, core:72) — loud
  startup failure, operator-only; recorded as an observation, not a defect.
  (Note: the variable is OPENVPN_PORT, not OVPN_PORT — an earlier draft
  tested the wrong name and got a false negative.)

Run as root (needs the unshare cell):  python3 tests/r20_input_shapes.py
Exit code = number of FAILs. FAIL = the defect signature reproduced.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TREE / "egress"))

RESULTS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + detail) if detail else ""))


def write_sk5(d, payload):
    p = Path(d) / "sk5.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def fresh_env(d):
    os.environ["OVPN_SK5_CONFIG_DIR"] = d


def fresh_import():
    for m in [m for m in list(sys.modules) if m == "sk5_manager"]:
        del sys.modules[m]
    import sk5_manager
    return sk5_manager


BASE = {"host": "127.0.0.1", "port": 1194, "username": "",
        "password": "", "enabled": False, "fail_open": False,
        "udp_over_tcp": False}


def main():
    import sk5_manager as _sm  # noqa: F401  (import once for path sanity)

    # S1: stored port=true, toggle-only set_sk5() keeps stored value;
    # the laundering lands in the RENDERED sing-box config (port 1).
    with tempfile.TemporaryDirectory() as d:
        fresh_env(d)
        write_sk5(d, {**BASE, "port": True})
        m = fresh_import()
        try:
            m.set_sk5()
            rendered = json.loads(m._render_singbox_config(
                m._load_config()).read_text())
            port = next(o["server_port"] for o in rendered["outbounds"]
                        if o.get("tag") == "bought-sk5")
            cell("S1 stored port=true renders as server_port 1 (defect)",
                 port == 1 and type(port) is int,
                 f"rendered server_port={port!r}")
        except ValueError as exc:
            cell("S1 stored port=true renders as server_port 1 (defect)",
                 False, f"honest ValueError instead: {exc}")

    # S2: stored port=1194.5 truncated in the rendered config.
    with tempfile.TemporaryDirectory() as d:
        fresh_env(d)
        write_sk5(d, {**BASE, "port": 1194.5})
        m = fresh_import()
        try:
            m.set_sk5()
            rendered = json.loads(m._render_singbox_config(
                m._load_config()).read_text())
            port = next(o["server_port"] for o in rendered["outbounds"]
                        if o.get("tag") == "bought-sk5")
            cell("S2 stored port=1194.5 renders as server_port 1194 (defect)",
                 port == 1194 and type(port) is int,
                 f"rendered server_port={port!r}")
        except ValueError as exc:
            cell("S2 stored port=1194.5 renders as server_port 1194 (defect)",
                 False, f"honest ValueError instead: {exc}")

    # S3 control: stored port="abc" -> ValueError (honest).
    with tempfile.TemporaryDirectory() as d:
        fresh_env(d)
        write_sk5(d, {**BASE, "port": "abc"})
        m = fresh_import()
        try:
            m.set_sk5()
            cell("S3 stored port='abc' raises ValueError (control)",
                 False, "no error raised")
        except ValueError:
            cell("S3 stored port='abc' raises ValueError (control)", True)

    # S4 control: stored port=1194 kept.
    with tempfile.TemporaryDirectory() as d:
        fresh_env(d)
        write_sk5(d, {**BASE, "port": 1194})
        m = fresh_import()
        try:
            m.set_sk5()
            saved = json.loads((Path(d) / "sk5.json").read_text())
            cell("S4 stored port=1194 kept (control)",
                 saved.get("port") == 1194, f"saved port={saved.get('port')!r}")
        except Exception as exc:
            cell("S4 stored port=1194 kept (control)", False, str(exc))

    # S5 control: stored config as a JSON list -> RuntimeError.
    with tempfile.TemporaryDirectory() as d:
        fresh_env(d)
        write_sk5(d, [1, 2, 3])
        m = fresh_import()
        try:
            m.set_sk5()
            cell("S5 stored config list raises RuntimeError (control)",
                 False, "no error raised")
        except RuntimeError:
            cell("S5 stored config list raises RuntimeError (control)", True)

    # S6: agent heartbeat with list-shaped sk5.json (private mount ns).
    s6 = run_heartbeat_list_probe()
    if s6[0] is None:
        # 探针自身起不来（import 失败等）时不得把“缺陷未复现”当成修复成立。
        print("S6 PROBE SETUP FAILURE:", s6[1])
        return 99
    cell("S6 heartbeat list-shaped sk5.json raises AttributeError (defect)",
         s6[0], s6[1])

    # S7: OPENVPN_PORT="abc" breaks core import (observation).
    r = subprocess.run(
        [sys.executable, "-c",
         "import os; os.environ['OPENVPN_PORT']='abc'; "
         "import sys; sys.path.insert(0, %r); import openvpn_manager"
         % str(TREE / "core")],
        capture_output=True, text=True, timeout=60)
    cell("S7 OPENVPN_PORT='abc' breaks core import (observation)",
         r.returncode != 0 and "ValueError" in r.stderr,
         f"rc={r.returncode} " + (r.stderr.strip().splitlines()[-1]
                                  if r.stderr.strip() else ""))

    fails = sum(1 for _, ok in RESULTS if not ok)
    print(f"\nTOTAL {len(RESULTS)} cells, FAIL {fails}: "
          f"{[n for n, ok in RESULTS if not ok]}")
    return fails


def run_heartbeat_list_probe():
    """Return (defect_reproduced, detail). Runs the agent's real
    heartbeat_status() in a private mount namespace with a list-shaped
    /etc/openvpn-sk5-panel/sk5.json bind-mounted in."""
    ptree = Path("/tmp/r20/ptree")
    # S6 曾踩的过期树陷阱（R20/BK/BL 三路都踩过）：ptree 是活树的副本，
    # 不刷新就跑会测旧代码。每次先把活树的 agent/＋core/＋egress/ 同步
    # 进来（agent.py 运行时从自身所在树找 openvpn_manager 与
    # sk5_manager；只同步 agent/＋core/ 会致 ModuleNotFoundError，
    # 其输出既无 HB-ATTR 又无 HB-OK，会被误读为“缺陷未复现”），再跑。
    import shutil
    for sub in ("agent", "core", "egress"):
        shutil.copytree(TREE / sub, ptree / sub, dirs_exist_ok=True)
    if not ptree.is_dir():
        return (False, "no /tmp/r20/ptree copy (run setup first)")
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "sk5.json").write_text("[1, 2, 3]", encoding="utf-8")
        runner = (
            "import sys\n"
            "sys.path.insert(0, %r)\n"
            "sys.path.insert(0, %r)\n"
            "import agent\n"
            "try:\n"
            "    print('HB-OK', agent.heartbeat_status())\n"
            "except AttributeError as e:\n"
            "    print('HB-ATTR', type(e).__name__, e)\n"
            "except Exception as e:\n"
            "    print('HB-OTHER', type(e).__name__, e)\n"
            % (str(ptree / "agent"), str(ptree))
        )
        script = Path(d) / "run_hb.py"
        script.write_text(runner, encoding="utf-8")
        cmd = ("mkdir -p /etc/openvpn-sk5-panel && "
               "mount --bind %(d)s /etc/openvpn-sk5-panel && "
               "python3 %(s)s" % {"d": d, "s": str(script)})
        r = subprocess.run(["unshare", "-rm", "bash", "-c", cmd],
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip().replace("\n", " ")
        if "HB-ATTR" in out:
            return (True, out[:200])
        if "HB-OK" in out:
            return (False, out[:200])
        # 既无 HB-ATTR 又无 HB-OK：探针自身失败（import 崩等），不是修复成立。
        return (None, out[:200] or f"rc={r.returncode}")


if __name__ == "__main__":
    sys.exit(main())

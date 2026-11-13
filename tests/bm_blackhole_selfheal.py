#!/usr/bin/env python3
"""BM fix probe (bm_blackhole_selfheal.py) -- R13-BUG-1:
sing-box death silently fell back to direct egress.

The bug (live-13 §11, twice reproduced on the machine): table 100's
only route was device-bound (`default via 10.9.0.1 dev tun1`); when
sing-box died, tun1 vanished, the kernel DELETED the route, table 100
went empty, and `from 10.8.0.0/24 lookup 100` fell through to the main
table -- VPN traffic silently egressed direct. Restarting sing-box
did not restore the route: permanent silent direct, no self-heal.

The fix has two layers, each proven by a different part of this probe:
  Layer 1 (fail-closed): enable() installs a device-independent
    `blackhole default metric 200` in table 100. tun1's metric-0
    route wins while tun1 is up; tun1's death drops lookups onto
    the blackhole instead of the main table. disable() flushes
    table 100, which removes the blackhole too (direct mode stays
    direct).
  Layer 2 (self-heal): check_health() re-applies the policy once
    per 60s timer tick when it finds policy missing (fail-open
    mode still fails over to direct afterwards if the chain stays
    dead); a repaired chain is re-probed and reported
    action="policy_repaired".

What each part proves -- and what it deliberately does NOT:
  Part 1 (K1-K5): REAL kernel behavior, real `ip`, private netns
    (`unshare -rn`). lo stands in for tun1 (the sandbox cannot
    create tun/dummy devices); the main-table default via lo
    stands in for the host's default via ens5. This proves the
    mechanism: empty table falls through, blackhole drops,
    tun1 route wins, tun1-route deletion falls back to blackhole,
    flush restores direct. It does NOT prove the script issues
    those commands -- that is part 2.
  Part 2 (S1-S7): the REAL policy-routing.sh, run as root in a
    private mount ns (bind-mounted /etc/sysctl.d + lock dir, so
    the host is untouched), against a STATEFUL MOCK `ip` (plus
    mock sysctl/iptables). The mock models only the command
    surface the script uses; kernel semantics are NOT modeled
    here (see part 1). This proves the script installs the
    blackhole, self-checks it, stays idempotent, and flushes it
    on disable.
  Part 3 (H1-H10): the REAL sk5_manager.check_health() against a
    scratch OVPN_SK5_CONFIG_DIR, with _run() answered by an
    in-process model of `ip`/`systemctl`/policy-routing.sh and
    test_sk5() stubbed (the probe function, not the product --
    its real TCP/UDP probing is covered by the R17 suites and the
    live rounds). This proves the repair decision logic: repair
    once, re-probe, honest action/detail, no repair when disabled
    or already healthy, fail-open still fails over. It does NOT
    prove the script works on a real host -- that is live-14
    (kill sing-box, watch traffic blackhole, watch it self-heal).

Run: python3 tests/bm_blackhole_selfheal.py
Exit code = number of FAILs. Requires: unshare, ip, python3.
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


def run(cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------- part 1
# Real kernel, real ip, private netns. lo = stand-in for tun1 (the
# sandbox cannot create tun/dummy devices); main default via lo =
# stand-in for the host's default via ens5. 10.8.0.1 must be a LOCAL
# address for `ip route get ... from 10.8.0.1` to work (R7-BUG-4).
NETNS_SCRIPT = r"""
ip link set lo up
ip addr add 10.8.0.1/24 dev lo
ip route add default dev lo table main
ip rule add from 10.8.0.0/24 lookup 100 priority 100
echo "@@K1@@"
ip route get 1.1.1.1 from 10.8.0.1 2>&1; echo "rc=$?"
echo "@@K2@@"
ip route add blackhole default metric 200 table 100
ip route get 1.1.1.1 from 10.8.0.1 2>&1; echo "rc=$?"
echo "@@K3@@"
ip route add default via 10.9.0.1 dev lo table 100
ip route get 1.1.1.1 from 10.8.0.1 2>&1; echo "rc=$?"
echo "@@K4@@"
ip route del default via 10.9.0.1 dev lo table 100
ip route get 1.1.1.1 from 10.8.0.1 2>&1; echo "rc=$?"
ip route show table 100
echo "@@K5@@"
ip route flush table 100
ip route show table 100; echo "(table-empty-above)"
ip route get 1.1.1.1 from 10.8.0.1 2>&1; echo "rc=$?"
"""


def part1_kernel():
    r = run(["unshare", "-rn", "bash", "-c", NETNS_SCRIPT])
    out = r.stdout + r.stderr
    if r.returncode != 0:
        cell("K0 netns harness runs", False, f"rc={r.returncode} {out[:200]}")
        return
    cell("K0 netns harness runs", True)
    secs = {}
    cur = None
    for line in out.splitlines():
        if line.startswith("@@") and line.endswith("@@"):
            cur = line.strip("@")
            secs[cur] = []
        elif cur:
            secs[cur].append(line)
    sec = {k: "\n".join(v) for k, v in secs.items()}
    k1 = sec.get("K1", "")
    cell("K1 empty table 100 falls through to main (the bug)",
         "rc=0" in k1 and "dev lo" in k1 and "table 100" not in k1,
         k1.replace("\n", " ")[:120])
    k2 = sec.get("K2", "")
    cell("K2 blackhole drops the lookup (EINVAL, not direct)",
         "rc=2" in k2 and "Invalid argument" in k2, k2.replace("\n", " ")[:120])
    k3 = sec.get("K3", "")
    cell("K3 tun1 route (metric 0) wins over blackhole (metric 200)",
         "rc=0" in k3 and "table 100" in k3 and "via 10.9.0.1" in k3
         and "Invalid argument" not in k3, k3.replace("\n", " ")[:120])
    k4 = sec.get("K4", "")
    cell("K4 tun1-route deletion falls back to the blackhole",
         "rc=2" in k4 and "Invalid argument" in k4
         and "blackhole default metric 200" in k4,
         k4.replace("\n", " ")[:160])
    k5 = sec.get("K5", "")
    cell("K5 flush restores direct (disable path)",
         "rc=0" in k5 and "dev lo" in k5 and "table 100" not in k5
         and "blackhole" not in k5, k5.replace("\n", " ")[:120])


# ---------------------------------------------------------------- part 2
# Real policy-routing.sh against a stateful mock `ip`.
MOCK_IP = r"""#!/bin/sh
# Stateful mock ip for the BM probe: models ONLY the command surface
# policy-routing.sh uses. Kernel semantics are NOT modeled here --
# they are proven by part 1 (real ip in a private netns).
S="${MOCK_IP_STATE:?}"
mkdir -p "$S"
echo "ip $*" >> "$S/log"
case "$1 $2" in
  "rule show") cat "$S/rules" 2>/dev/null; exit 0;;
  "rule add")
    grep -qx "100: from 10.8.0.0/24 lookup 100" "$S/rules" 2>/dev/null \
      || echo "100: from 10.8.0.0/24 lookup 100" >> "$S/rules"
    exit 0;;
  "rule del")
    if [ -f "$S/rules" ]; then
      grep -vx "100: from 10.8.0.0/24 lookup 100" "$S/rules" > "$S/rules.tmp" || true
      mv "$S/rules.tmp" "$S/rules"
    fi
    exit 0;;
  "route show") cat "$S/routes" 2>/dev/null; exit 0;;
  "route replace")
    if [ "$3" = "blackhole" ]; then
      # S7 variant: silently swallow the blackhole install.
      if [ -n "${MOCK_IP_NO_BLACKHOLE:-}" ]; then exit 0; fi
      grep -v "^blackhole default" "$S/routes" 2>/dev/null > "$S/routes.tmp" || true
      mv "$S/routes.tmp" "$S/routes" 2>/dev/null || true
      echo "blackhole default metric 200" >> "$S/routes"
    else
      grep -v "^default via" "$S/routes" 2>/dev/null > "$S/routes.tmp" || true
      mv "$S/routes.tmp" "$S/routes" 2>/dev/null || true
      echo "default via 10.9.0.1 dev tun1" >> "$S/routes"
    fi
    exit 0;;
  "route flush") : > "$S/routes"; exit 0;;
  "link show")
    # R24-P2-1 (BT): model device liveness like the BO mock --
    # $S/tun1 holds "live" (sing-box holds it: UP,LOWER_UP) or
    # "dead" (placeholder: NO-CARRIER, state DOWN, no LOWER_UP);
    # absent -> no such device. The script gates the tun1 route
    # on tun1_live(), so the mock must answer it faithfully.
    if [ -f "$S/tun1" ]; then
      if [ "$(cat "$S/tun1")" = live ]; then
        echo "2: tun1: <POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP> mtu 1400 qdisc fq_codel state UNKNOWN mode DEFAULT group default qlen 500"
      else
        echo "2: tun1: <NO-CARRIER,POINTOPOINT,MULTICAST,NOARP,UP> mtu 1400 qdisc fq_codel state DOWN mode DEFAULT group default qlen 500"
      fi
      exit 0
    fi
    exit 1;;
  "tuntap add") touch "$S/tun1"; exit 0;;
  "addr add") exit 0;;
  "addr show")
    [ -f "$S/tun1" ] && echo "inet 10.9.0.1/30"
    exit 0;;
  "link set") exit 0;;
  *) exit 0;;
esac
"""

MOCK_SYSCTL = "#!/bin/sh\nexit 0\n"
MOCK_IPTABLES = """#!/bin/sh
# -C -> 1 (absent, so -A runs); -A/-D -> 0.
echo "iptables $*" >> "${MOCK_IP_STATE:?}/log"
if [ "$1" = "-C" ]; then exit 1; fi
exit 0
"""


def run_script(tmp, *args, extra_env=None):
    """Run the REAL policy-routing.sh in a private mount ns with
    bind-mounted /etc/sysctl.d + lock dir (host untouched)."""
    env = dict(os.environ)
    env["MOCK_IP_STATE"] = str(tmp / "ipstate")
    if extra_env:
        env.update(extra_env)
    inner = (
        "mkdir -p /etc/sysctl.d /run/openvpn-sk5-panel && "
        "mount --bind \"$1/sysctld\" /etc/sysctl.d && "
        "mount --bind \"$1/rundir\" /run/openvpn-sk5-panel && "
        "export PATH=\"$1/mockbin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\" && "
        "export MOCK_IP_STATE=\"$1/ipstate\" && "
        + (f"export MOCK_IP_NO_BLACKHOLE=1 && " if extra_env and extra_env.get("MOCK_IP_NO_BLACKHOLE") else "")
        + "bash \"" + str(TREE / "egress" / "policy-routing.sh") + "\" "
        + " ".join(args) + "; echo \"rc=$?\""
    )
    r = subprocess.run(["unshare", "-rm", "bash", "-c", inner, "x", str(tmp)],
                       capture_output=True, text=True, timeout=120, env=env)
    return r.stdout + r.stderr


def part2_script():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (tmp / "sysctld").mkdir()
        (tmp / "rundir").mkdir()
        (tmp / "ipstate").mkdir()
        mockbin = tmp / "mockbin"
        mockbin.mkdir()
        (mockbin / "ip").write_text(MOCK_IP, encoding="utf-8")
        (mockbin / "sysctl").write_text(MOCK_SYSCTL, encoding="utf-8")
        (mockbin / "iptables").write_text(MOCK_IPTABLES, encoding="utf-8")
        for f in ("ip", "sysctl", "iptables"):
            (mockbin / f).chmod(0o755)

        def state():
            rules = (tmp / "ipstate" / "rules").read_text(
                encoding="utf-8") if (tmp / "ipstate" / "rules").exists() else ""
            routes = (tmp / "ipstate" / "routes").read_text(
                encoding="utf-8") if (tmp / "ipstate" / "routes").exists() else ""
            log = (tmp / "ipstate" / "log").read_text(
                encoding="utf-8") if (tmp / "ipstate" / "log").exists() else ""
            return rules, routes, log

        # S1: enable installs rule + tun1 route + blackhole.
        # (Precondition: tun1 is LIVE -- sing-box holds it. Since
        # BT the script never creates the device, so a route can
        # only land when the daemon already holds tun1; the
        # no-device case is S5.)
        (tmp / "ipstate" / "tun1").write_text("live", encoding="utf-8")
        out = run_script(tmp, "enable")
        rules, routes, log = state()
        cell("S1 enable installs blackhole alongside tun1 route",
             "rc=0" in out
             and "100: from 10.8.0.0/24 lookup 100" in rules
             and "default via 10.9.0.1 dev tun1" in routes
             and "blackhole default metric 200" in routes
             and "ip route replace blackhole default metric 200 table 100" in log,
             (out.strip().splitlines() or [""])[-1] + " | routes=" + routes.replace("\n", ","))
        # S2: enable again is idempotent (no duplicate lines).
        out = run_script(tmp, "enable")
        rules, routes, _ = state()
        cell("S2 re-enable is idempotent (no duplicate rule/routes)",
             "rc=0" in out
             and rules.count("lookup 100") == 1
             and routes.count("default via 10.9.0.1 dev tun1") == 1
             and routes.count("blackhole default metric 200") == 1,
             f"rules={rules.count('lookup 100')} tun1={routes.count('default via')} bh={routes.count('blackhole')}")
        # S3: disable removes the rule AND the blackhole.
        out = run_script(tmp, "disable")
        rules, routes, _ = state()
        cell("S3 disable removes rule and blackhole (direct stays direct)",
             "rc=0" in out and "lookup 100" not in rules
             and "blackhole" not in routes and routes.strip() == "",
             f"rules={rules!r} routes={routes!r}")
        # S4: disable when already disabled is a clean no-op.
        out = run_script(tmp, "disable")
        cell("S4 double disable exits 0", "rc=0" in out,
             (out.strip().splitlines() or [""])[-1])
        # S5: enable with tun1 absent creates NO device -- it
        # installs blackhole + rule only (blackhole-only table),
        # and installs NO tun1 route. (R24-P2-1 / BT: this cell
        # used to assert the placeholder was created -- that
        # pinned the defective behavior itself, same legitimate
        # correction family as BH-03(c) / BN-Q5 / BR-W2. The
        # blackhole layer this cell guards is unchanged.)
        (tmp / "ipstate" / "tun1").unlink(missing_ok=True)
        out = run_script(tmp, "enable")
        rules, routes, log = state()
        cell("S5 enable with tun1 absent creates NO device, blackhole-only table",
             "rc=0" in out and "ip tuntap add mode tun dev tun1" not in log
             and "blackhole default metric 200" in routes
             and "100: from 10.8.0.0/24 lookup 100" in rules
             and "default via 10.9.0.1 dev tun1" not in routes,
             (out.strip().splitlines() or [""])[-1])
        # S6: disable again leaves a clean slate for S7.
        run_script(tmp, "disable")
        # S7: blackhole that cannot stick must fail LOUDLY (and the
        # rule is rolled back); a chain without a kill-switch must
        # never silently ship. No tun1 route is installed either:
        # tun1 is absent here, so the route was never attempted
        # (since BT the route lands only via a live device).
        out = run_script(tmp, "enable", extra_env={"MOCK_IP_NO_BLACKHOLE": "1"})
        rules, routes, _ = state()
        cell("S7 blackhole-not-sticking fails loudly + rolls back rule",
             "rc=0" not in out
             and "fallback blackhole route did not stick" in out
             and "lookup 100" not in rules
             and "default via 10.9.0.1 dev tun1" not in routes,
             (out.strip().splitlines() or [""])[-1][:160])


# ---------------------------------------------------------------- part 3
# Real sk5_manager.check_health() against a scratch config dir; _run()
# answered by an in-process model of ip/systemctl/policy-routing.sh,
# test_sk5() stubbed (probe function, not product).
BASE_CFG = {"host": "127.0.0.1", "port": 11080, "username": "",
            "password": "", "enabled": True, "fail_open": False,
            "udp_over_tcp": False}


class Model:
    """In-process stand-in for `ip`/`systemctl`/policy-routing.sh."""

    def __init__(self, rule=False, tun1=False, blackhole=False,
                 singbox=True, apply_fail=False, tun1_device=None):
        self.rule = rule
        self.tun1 = tun1
        self.blackhole = blackhole
        self.singbox = singbox
        self.apply_fail = apply_fail
        # Device-level state, distinct from the route: tun1_device
        # says whether sing-box currently holds the tun1 device
        # (LOWER_UP). Default follows singbox (the daemon creates
        # the device at startup and it vanishes when it dies).
        # R14-BUG-1 (BO): repair installs the tun1 route only when
        # the device is live, never a dead placeholder.
        self.tun1_device = singbox if tun1_device is None else tun1_device
        self.apply_calls = 0
        self.verbs = []  # policy-routing.sh verbs actually invoked

    def _cp(self, rc, out="", err=""):
        return subprocess.CompletedProcess(args=[], returncode=rc,
                                          stdout=out, stderr=err)

    def run(self, cmd, timeout=30):
        if cmd[:2] == ["systemctl", "is-active"]:
            return self._cp(0 if self.singbox else 3)
        if cmd[:2] == ["systemctl", "is-enabled"]:
            return self._cp(1)  # no unit in the sandbox
        if cmd[:2] == ["systemctl", "reset-failed"]:
            return self._cp(0)
        if cmd[:2] == ["systemctl", "restart"]:
            return self._cp(0)
        if cmd[:2] == ["systemctl", "stop"]:
            return self._cp(0)
        if cmd[:2] == ["ip", "rule"]:
            if cmd[2:3] == ["show"]:
                return self._cp(0, "100: from 10.8.0.0/24 lookup 100\n"
                                if self.rule else "")
            return self._cp(0)
        if cmd[:3] == ["ip", "route", "show"]:
            lines = []
            if self.tun1:
                # R24-P2-1 (BT): a route via a device sing-box does
                # NOT hold is linkdown in the real kernel -- the
                # route line carries the token, and _policy_active()
                # must reject it. A route via a live device has no
                # such token. Model the token from device state, not
                # from the route flag alone.
                suffix = "" if self.tun1_device else " linkdown"
                lines.append("default via 10.9.0.1 dev tun1 proto static"
                             + suffix)
            if self.blackhole:
                lines.append("blackhole default metric 200 proto static")
            return self._cp(0, "\n".join(lines) + ("\n" if lines else ""))
        if cmd[:1] == ["bash"] and cmd[-1:] == ["enable"]:
            self.verbs.append("enable")
            self.apply_calls += 1
            if self.apply_fail:
                return self._cp(1, "", "mock policy script failed")
            self.rule = self.tun1 = self.blackhole = True
            return self._cp(0)
        if cmd[:1] == ["bash"] and cmd[-1:] == ["repair"]:
            # R14-BUG-1 (BO): repair never creates tun1. It
            # re-installs the blackhole + rule, and the tun1 route
            # only once sing-box has recreated the device.
            self.verbs.append("repair")
            self.apply_calls += 1
            if self.apply_fail:
                return self._cp(1, "", "mock policy script failed")
            self.rule = self.blackhole = True
            if self.tun1_device:
                self.tun1 = True
            else:
                # R15-BUG-1 (BS): the real script drops a stale
                # linkdown tun1 route when the device is not live
                # (BO R3) -- a route via a dead device would
                # otherwise fool _policy_active() at lookup level.
                self.tun1 = False
            return self._cp(0)
        if cmd[:1] == ["bash"] and cmd[-1:] == ["disable"]:
            self.rule = self.tun1 = self.blackhole = False
            return self._cp(0)
        return self._cp(0)


def fresh_import(d):
    os.environ["OVPN_SK5_CONFIG_DIR"] = d
    for m in [m for m in list(sys.modules) if m == "sk5_manager"]:
        del sys.modules[m]
    import sk5_manager
    return sk5_manager


def health_case(cfg_extra, model, tcp_ok):
    """Run one check_health() cell; returns (module, model, result)."""
    d = tempfile.mkdtemp()
    cfg = {**BASE_CFG, **cfg_extra}
    (Path(d) / "sk5.json").write_text(json.dumps(cfg), encoding="utf-8")
    m = fresh_import(d)
    m._run = model.run
    m.test_sk5 = lambda: {"tcp_ok": tcp_ok, "udp_ok": tcp_ok,
                          "egress_ip": "203.0.113.7" if tcp_ok else None}
    result = m.check_health()
    return m, model, result, Path(d)


def part3_health():
    # H1: R13-BUG-1 state (rule + blackhole, tun1 route gone),
    # sing-box up, probe passes -> repaired, healthy.
    m, model, r, d = health_case({}, Model(rule=True, tun1=False,
                                           blackhole=True, singbox=True), True)
    hj = json.loads((d / "health.json").read_text(encoding="utf-8"))
    cell("H1 missing tun1 route auto-repairs to healthy",
         r["healthy"] is True and r["action"] == "policy_repaired"
         and model.apply_calls == 1 and hj["action"] == "policy_repaired",
         f"action={r['action']} apply_calls={model.apply_calls}")
    # H2: same state, probe fails -> blackholed, not policy_missing.
    m, model, r, d = health_case({}, Model(rule=True, tun1=False,
                                           blackhole=True, singbox=True), False)
    cell("H2 repaired-but-dead chain is blackholed_kill_switch",
         r["healthy"] is False and r["action"] == "blackholed_kill_switch"
         and model.apply_calls == 1, f"action={r['action']}")
    # H3: pre-fix state (no blackhole), repair fails -> policy_missing
    # with the DIRE wording: traffic really is direct here.
    m, model, r, d = health_case({}, Model(rule=True, tun1=False,
                                           blackhole=False, singbox=True,
                                           apply_fail=True), False)
    cell("H3 no-blackhole + repair fails -> policy_missing, direct",
         r["healthy"] is False and r["action"] == "policy_missing"
         and "egresses direct" in r["detail"]
         and "auto-repair: policy re-apply failed" in r["detail"]
         and model.apply_calls == 1, r["detail"][:160])
    # H4: blackhole present, repair fails -> policy_missing, but the
    # detail must say HELD, never "egresses direct".
    m, model, r, d = health_case({}, Model(rule=True, tun1=False,
                                           blackhole=True, singbox=True,
                                           apply_fail=True), False)
    cell("H4 blackhole present + repair fails -> held, not direct",
         r["healthy"] is False and r["action"] == "policy_missing"
         and "held by the fallback blackhole" in r["detail"]
         and "egresses direct" not in r["detail"],
         r["detail"][:160])
    # H5: rule itself gone, repair fails -> direct (the blackhole
    # cannot help without the rule steering traffic into table 100).
    m, model, r, d = health_case({}, Model(rule=False, tun1=False,
                                           blackhole=True, singbox=True,
                                           apply_fail=True), False)
    cell("H5 rule gone + repair fails -> policy_missing, direct",
         r["healthy"] is False and r["action"] == "policy_missing"
         and "egresses direct" in r["detail"], r["detail"][:160])
    # H6: fail-open still fails over after a repair that cannot make
    # the chain live (repair runs, probe fails, disable flips disk).
    m, model, r, d = health_case(
        {"fail_open": True},
        Model(rule=True, tun1=False, blackhole=True, singbox=True), False)
    saved = json.loads((d / "sk5.json").read_text(encoding="utf-8"))
    cell("H6 fail-open: repair tried, then fails over to direct",
         r["healthy"] is False and r["action"] == "failed_over_to_direct"
         and model.apply_calls == 1 and saved["enabled"] is False,
         f"action={r['action']} enabled={saved['enabled']}")
    # H7: idempotent -- second check after a repair does NOT repair
    # again (policy is in place now).
    d = tempfile.mkdtemp()
    (Path(d) / "sk5.json").write_text(json.dumps(BASE_CFG), encoding="utf-8")
    m = fresh_import(d)
    model = Model(rule=True, tun1=False, blackhole=True, singbox=True)
    m._run = model.run
    m.test_sk5 = lambda: {"tcp_ok": True, "udp_ok": True,
                          "egress_ip": "203.0.113.7"}
    r1 = m.check_health()
    r2 = m.check_health()
    cell("H7 second check does not re-repair (idempotent)",
         r1["action"] == "policy_repaired" and r2["action"] == "none"
         and model.apply_calls == 1,
         f"r1={r1['action']} r2={r2['action']} calls={model.apply_calls}")
    # H8: disabled chain -> no repair attempt at all.
    m, model, r, d = health_case({"enabled": False},
                                 Model(rule=False, tun1=False,
                                       blackhole=False, singbox=True), False)
    cell("H8 disabled chain never repairs",
         r["healthy"] is True and r["action"] == "chain_disabled"
         and model.apply_calls == 0, f"action={r['action']}")
    # H9: healthy chain -> no repair attempt at all.
    m, model, r, d = health_case({}, Model(rule=True, tun1=True,
                                           blackhole=True, singbox=True), True)
    cell("H9 healthy chain never repairs",
         r["healthy"] is True and r["action"] == "none"
         and model.apply_calls == 0, f"action={r['action']}")
    # H10: _blackhole_active() unit shape (blackhole line only).
    d = tempfile.mkdtemp()
    (Path(d) / "sk5.json").write_text(json.dumps(BASE_CFG), encoding="utf-8")
    m = fresh_import(d)
    model = Model(rule=True, tun1=True, blackhole=False, singbox=True)
    m._run = model.run
    before = m._blackhole_active()
    model.blackhole = True
    after = m._blackhole_active()
    cell("H10 _blackhole_active false without blackhole, true with",
         before is False and after is True,
         f"before={before} after={after}")


def main():
    part1_kernel()
    part2_script()
    part3_health()
    fails = sum(1 for _, ok in RESULTS if not ok)
    print(f"\nTOTAL {len(RESULTS)} cells, FAIL {fails}: "
          f"{[n for n, ok in RESULTS if not ok]}")
    return fails


if __name__ == "__main__":
    sys.exit(main())

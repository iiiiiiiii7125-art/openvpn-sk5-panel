#!/usr/bin/env python3
"""BS fix probe (bs_verdict.py) -- R15-BUG-1 (P2):
while sing-box is dead, check_health() reported policy_missing
and called a successful repair "did not stick".

The bug (live-15 §10): BO's repair verb installs only the
blackhole + rule while sing-box is dead -- it never creates tun1,
so the tun1 route cannot exist until the daemon recreates the
device. check_health() re-verified the repair with
_policy_active(), which needs that tun1 route, so the re-check
always failed while sing-box was down: repaired=False, note
"policy script exited 0 but the policy still did not stick",
action policy_missing. That violated check_health()'s own
docstring (a repaired chain that is still dead ->
blackholed_kill_switch; only a failed repair lands
policy_missing) and disagreed with live-14, which observed
blackholed_kill_switch for the same state (there the pre-BO
repair recreated the dead tun1 + route, so _policy_active()
happened to turn true -- an artifact of the old repair, not
correct verdict logic).

The fix (option (a)): "repaired" is judged by the repair
verb's own contract -- blackhole + rule in place
(_repair_holding()) -- not by _policy_active(), which stays
the test for whether the chain can carry traffic. A repair
that succeeds (script exit 0 and blackhole + rule in place)
while the chain is still dead lands blackholed_kill_switch;
policy_missing is reserved for a repair that actually failed
(script error, or blackhole / rule missing at re-check) or a
table with no kill-switch at all. Docstrings of check_health()
and _repair_policy() now say so; _policy_active() is untouched.

What this probe proves: the REAL sk5_manager.check_health()
against the BM probe's Model (which models the `repair` verb
and device-level tun1 state). It does NOT prove the script
works on a real host -- that is live-16.

Note: the "did not stick" note is kept as defense-in-depth
for a post-script flush race (script exit 0, blackhole / rule
gone by re-check time); no Model state constructs that race,
so no cell covers it -- the branch is not dead code, just
unreachable in this model.

Run: python3 tests/bs_verdict.py
Exit code = number of FAILs. Requires: python3.
"""
import json
import sys
import tempfile
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TREE / "egress"))
sys.path.insert(0, str(TREE / "tests"))
import bm_blackhole_selfheal as bm

RESULTS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + detail) if detail else ""))


def main():
    # V1: THE BUG (live-15 §10 state) -- sing-box dead, device
    # absent, rule + blackhole present, tun1 route gone. Repair
    # succeeds (blackhole + rule in place); the chain is still
    # dead only because the daemon is down -> blackholed, not
    # policy_missing, and no "did not stick" mislabel.
    m, model, r, d = bm.health_case(
        {}, bm.Model(rule=True, tun1=False, blackhole=True,
                     singbox=False, tun1_device=False), False)
    hj = json.loads((d / "health.json").read_text(encoding="utf-8"))
    cell("V1 dead sing-box + successful repair -> blackholed_kill_switch",
         r["healthy"] is False and r["action"] == "blackholed_kill_switch"
         and hj["action"] == "blackholed_kill_switch"
         and model.verbs == ["repair"] and model.apply_calls == 1
         and model.tun1_device is False and model.tun1 is False
         and "held by the fallback blackhole" in r["detail"]
         and "egresses direct" not in r["detail"]
         and "did not stick" not in r["detail"]
         and "policy re-applied by health check" in r["detail"],
         f"action={r['action']} verbs={model.verbs} | {r['detail'][:180]}")
    # V2: repair FAILS (script error), dead sing-box, blackhole
    # present -> policy_missing, but the detail still says HELD.
    # The failure -- not the dead chain -- is what earns
    # policy_missing.
    m, model, r, d = bm.health_case(
        {}, bm.Model(rule=True, tun1=False, blackhole=True,
                     singbox=False, tun1_device=False,
                     apply_fail=True), False)
    cell("V2 repair failure + dead sing-box -> policy_missing, held",
         r["healthy"] is False and r["action"] == "policy_missing"
         and model.verbs == ["repair"]
         and "auto-repair: policy re-apply failed" in r["detail"]
         and "held by the fallback blackhole" in r["detail"]
         and "egresses direct" not in r["detail"],
         r["detail"][:180])
    # V3: repair fails AND no blackhole -> policy_missing with the
    # DIRE wording: traffic really is direct here.
    m, model, r, d = bm.health_case(
        {}, bm.Model(rule=True, tun1=False, blackhole=False,
                     singbox=False, tun1_device=False,
                     apply_fail=True), False)
    cell("V3 repair failure + no blackhole -> policy_missing, direct",
         r["healthy"] is False and r["action"] == "policy_missing"
         and "egresses direct" in r["detail"],
         r["detail"][:180])
    # V4: rule itself gone, repair fails -> direct (the blackhole
    # cannot help without the rule steering traffic into table 100).
    m, model, r, d = bm.health_case(
        {}, bm.Model(rule=False, tun1=False, blackhole=True,
                     singbox=False, tun1_device=False,
                     apply_fail=True), False)
    cell("V4 rule gone + repair fails -> policy_missing, direct",
         r["healthy"] is False and r["action"] == "policy_missing"
         and "egresses direct" in r["detail"],
         r["detail"][:180])
    # V5: control -- sing-box alive, device live, route missing,
    # probe passes -> repaired, healthy (BM H1 via the repair verb).
    m, model, r, d = bm.health_case(
        {}, bm.Model(rule=True, tun1=False, blackhole=True,
                     singbox=True), True)
    cell("V5 live device + missing route repairs to healthy",
         r["healthy"] is True and r["action"] == "policy_repaired"
         and model.verbs == ["repair"] and model.apply_calls == 1,
         f"action={r['action']}")
    # V6: control -- same state, probe fails -> blackholed (BM H2
    # via the repair verb): route lands, chain still dead.
    m, model, r, d = bm.health_case(
        {}, bm.Model(rule=True, tun1=False, blackhole=True,
                     singbox=True), False)
    cell("V6 live device + missing route, probe fails -> blackholed",
         r["healthy"] is False and r["action"] == "blackholed_kill_switch"
         and model.apply_calls == 1,
         f"action={r['action']}")
    # V7: two ticks -- tick 1 dead (repair, blackholed); sing-box
    # comes back (device live); tick 2 completes the repair ->
    # policy_repaired, healthy.
    d = tempfile.mkdtemp()
    (Path(d) / "sk5.json").write_text(json.dumps(bm.BASE_CFG), encoding="utf-8")
    m = bm.fresh_import(d)
    model = bm.Model(rule=True, tun1=False, blackhole=True,
                     singbox=False, tun1_device=False)
    m._run = model.run
    m.test_sk5 = lambda: {"tcp_ok": True, "udp_ok": True,
                          "egress_ip": "203.0.113.7"}
    r1 = m.check_health()
    model.singbox = True
    model.tun1_device = True  # sing-box recreated the device
    r2 = m.check_health()
    cell("V7 two ticks: blackholed (dead) -> sing-box back -> policy_repaired",
         r1["healthy"] is False and r1["action"] == "blackholed_kill_switch"
         and r2["healthy"] is True and r2["action"] == "policy_repaired"
         and model.verbs == ["repair", "repair"]
         and model.apply_calls == 2 and model.tun1 is True,
         f"r1={r1['action']} r2={r2['action']} verbs={model.verbs}")
    # V8: a STALE linkdown tun1 route (pre-BO repair leftover, or
    # an enable-path placeholder) plus a MISSING rule, sing-box
    # dead. The missing rule triggers a repair, which must drop
    # the stale route (BO R3, now modeled) -- a route via a dead
    # device would otherwise fool _policy_active() at lookup
    # level. Verdict is still blackholed: the repair held.
    # (Note, updated BT: since the BT fix a stale route ALONE no
    # longer fools _policy_active() either -- the predicate
    # rejects linkdown lines, so a repair would run even with the
    # rule in place. The Model now emits the linkdown token on a
    # route whose device is dead; V8's rule-missing trigger is
    # unchanged.)
    m, model, r, d = bm.health_case(
        {}, bm.Model(rule=False, tun1=True, blackhole=True,
                     singbox=False, tun1_device=False), False)
    cell("V8 stale linkdown route dropped by repair, still blackholed",
         r["healthy"] is False and r["action"] == "blackholed_kill_switch"
         and model.tun1 is False
         and "held by the fallback blackhole" in r["detail"],
         f"action={r['action']} tun1={model.tun1}")
    # V9: control -- fail-open still fails over even when the
    # repair succeeds: the fail-over branch precedes the
    # policy_missing / blackholed split.
    m, model, r, d = bm.health_case(
        {"fail_open": True},
        bm.Model(rule=True, tun1=False, blackhole=True,
                 singbox=False, tun1_device=False), False)
    saved = json.loads((d / "sk5.json").read_text(encoding="utf-8"))
    cell("V9 fail-open: repair tried, then fails over to direct",
         r["healthy"] is False and r["action"] == "failed_over_to_direct"
         and model.apply_calls == 1 and saved["enabled"] is False,
         f"action={r['action']} enabled={saved['enabled']}")

    fails = sum(1 for _, ok in RESULTS if not ok)
    print(f"\nTOTAL {len(RESULTS)} cells, FAIL {fails}: "
          f"{[n for n, ok in RESULTS if not ok]}")
    return fails


if __name__ == "__main__":
    sys.exit(main())

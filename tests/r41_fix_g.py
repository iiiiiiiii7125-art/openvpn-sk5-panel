#!/usr/bin/env python3
"""R41 Fix-G verification — LIVE-R41-1 panel restart after cert regen.

Proves the fix by driving the REAL `_restart_panel_if_needed`
function extracted from install.sh (not a copy) through a stub
`systemctl`, across the scenario matrix:

  G1  LIVE-R41-1: stale cert + domain unchanged + panel was running
      -> exactly one restart (domain call), service call is a no-op.
  G2  No domain: stale cert + panel was running -> service fallback
      restarts once (domain section never runs).
  G3  Cert current + domain unchanged -> no restart.
  G4  Fresh install (fresh cert, panel never ran) -> no restart,
      even with a new domain.
  G5  Stale cert but panel was not running -> no restart (enable
      --now starts it fresh with the new cert).
  G6  Domain changed, cert current -> one restart (pre-existing
      behaviour preserved).
  G7  Domain changed + stale cert -> exactly one restart (the two
      call sites never restart twice).
  G8  Panel died mid-run (was active, now inactive) -> no restart.
  G9  Restart fails at the domain call -> flag stays 0 and the
      service fallback retries (two attempts, warn emitted).
  G10 Caddy down: stale cert + panel was running -> service fallback
      restarts once (domain section skipped).
  G11 _PANEL_WAS_ACTIVE capture lines behave (active -> 1, else 0).

Static checks:
  S1  function defined exactly once; S2 domain call site present;
  S3  service call site present; S4 old inline restart gone;
  S5  domain health-check warning names the stale-cert cause and
      the restart action (no bare "Caddy retries automatically");
  S6  bash -n install.sh clean; S7 DNS warnings (967/969) keep
      their (true) issuance-retry wording -- deliberately untouched.

Usage: python3 tests/r41_fix_g.py [tree]   (default: this tree)
Baseline (integrated tip c5bbd61) fails the function/static cells:
the function does not exist there, so nothing restarts.
"""
import os
import re
import subprocess
import sys
import tempfile

TREE = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else
                       os.path.join(os.path.dirname(__file__), ".."))
INSTALL = os.path.join(TREE, "install.sh")

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s %s" % (name, detail))
    else:
        FAIL += 1
        print("FAIL %s %s" % (name, detail))


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def extract_function(src):
    """Return the _restart_panel_if_needed definition, or None."""
    lines = src.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.startswith("_restart_panel_if_needed() {")), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines))
                if lines[i] == "}"), None)
    if end is None:
        return None
    return "\n".join(lines[start:end + 1])


def extract_capture(src):
    """Return the _PANEL_WAS_ACTIVE capture lines, or None."""
    lines = src.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if l.startswith("_PANEL_WAS_ACTIVE=0")), None)
    if start is None:
        return None
    return "\n".join(lines[start:start + 2])


STUB_SYSTEMCTL = """#!/usr/bin/env bash
# Stub systemctl: is-active answers from env, restart is logged.
if [ "$1" = "is-active" ]; then
    _unit="${@: -1}"
    case "$_unit" in
        openvpn-sk5-panel) [ "${STUB_PANEL_ACTIVE:-0}" = "1" ] && exit 0 || exit 3 ;;
        caddy) [ "${STUB_CADDY_ACTIVE:-0}" = "1" ] && exit 0 || exit 3 ;;
        *) exit 3 ;;
    esac
fi
if [ "$1" = "restart" ]; then
    echo "restart $2" >> "$STUB_LOG"
    [ "${STUB_RESTART_FAIL:-0}" = "1" ] && exit 1 || exit 0
fi
exit 0
"""


def run_scenario(fn_text, *, stale, was, active, domain, prev,
                 domain_call, restart_fail=False):
    """Run the extracted function as the two call sites would.

    Returns (restart_attempts, flag, log_text)."""
    d = tempfile.mkdtemp(prefix="r41fixg-")
    stubdir = os.path.join(d, "bin")
    os.makedirs(stubdir)
    stub = os.path.join(stubdir, "systemctl")
    with open(stub, "w") as f:
        f.write(STUB_SYSTEMCTL)
    os.chmod(stub, 0o755)
    stub_log = os.path.join(d, "stub.log")
    harness_log = os.path.join(d, "harness.log")
    open(stub_log, "w").close()
    open(harness_log, "w").close()
    domain_changed = "1" if domain != prev else "0"
    harness = """set -eu
export PATH="%s:$PATH"
export STUB_LOG="%s" HARNESS_LOG="%s"
export STUB_PANEL_ACTIVE="%s" STUB_RESTART_FAIL="%s"
log() { echo "[install] $*" >> "$HARNESS_LOG"; }
warn() { echo "[install] WARN: $*" >> "$HARNESS_LOG"; }
die() { echo "[install] ERROR: $*" >> "$HARNESS_LOG"; exit 1; }
_PANEL_CERT_STALE=%s
_PANEL_WAS_ACTIVE=%s
_PANEL_RESTARTED=0
_PANEL_DOMAIN="%s"
_PREV_PANEL_DOMAIN="%s"
%s
%s
_restart_panel_if_needed 0
echo "RESTARTS=$(grep -c '^restart ' "$STUB_LOG" || true)"
echo "FLAG=$_PANEL_RESTARTED"
""" % (stubdir, stub_log, harness_log, "1" if active else "0",
       "1" if restart_fail else "0", stale, was, domain, prev,
       fn_text,
       ('_DOMAIN_CHANGED=%s\n_restart_panel_if_needed "$_DOMAIN_CHANGED"'
        % domain_changed) if domain_call else "# domain section skipped")
    script = os.path.join(d, "harness.sh")
    with open(script, "w") as f:
        f.write(harness)
    r = run(["bash", script])
    out = r.stdout + r.stderr
    m_restarts = re.search(r"^RESTARTS=(\d+)$", out, re.M)
    m_flag = re.search(r"^FLAG=(\d+)$", out, re.M)
    log_text = open(harness_log).read()
    return ((int(m_restarts.group(1)) if m_restarts else -1),
            (int(m_flag.group(1)) if m_flag else -1), log_text,
            r.returncode, out)


def main():
    src = open(INSTALL).read()

    # --- static checks -------------------------------------------
    fn_text = extract_function(src)
    check("S1 function defined exactly once",
          src.count("_restart_panel_if_needed() {") == 1)
    check("S2 domain call site present",
          '_restart_panel_if_needed "$_DOMAIN_CHANGED"' in src)
    check("S3 service call site present",
          re.search(r"^_restart_panel_if_needed 0$", src, re.M) is not None)
    check("S4 old inline restart gone",
          "restarting openvpn-sk5-panel to apply the proxy env vars" not in src)
    warn_line = next((l for l in src.splitlines()
                      if "panel does not answer yet at" in l), "")
    check("S5 warning names stale-cert cause + restart action",
          "stale TLS cert" in warn_line
          and "systemctl restart openvpn-sk5-panel" in warn_line,
          "| " + warn_line[:80])
    check("S5b no bare 'Caddy retries automatically' left",
          "Caddy retries automatically" not in src)
    check("S6 bash -n clean", run(["bash", "-n", INSTALL]).returncode == 0)
    check("S7 DNS warnings keep issuance-retry wording",
          src.count("Caddy will keep retrying automatically") == 2)
    cap_text = extract_capture(src)
    check("S8 _PANEL_WAS_ACTIVE capture present", cap_text is not None)

    if fn_text is None:
        # Baseline: nothing else can run; the scenario cells fail.
        for name in ("G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8",
                     "G9", "G10", "G11"):
            check(name + " (function missing on this tree)", False)
        print("\nTOTAL: PASS=%d FAIL=%d" % (PASS, FAIL))
        return 1

    def scenario(name, expect_restarts, expect_flag, **kw):
        restarts, flag, log_text, rc, out = run_scenario(fn_text, **kw)
        check(name, rc == 0 and restarts == expect_restarts
              and flag == expect_flag,
              "| restarts=%s flag=%s (want %s/%s) rc=%s"
              % (restarts, flag, expect_restarts, expect_flag, rc))
        return restarts, flag, log_text

    # G1: the LIVE-R41-1 case itself.
    scenario("G1 stale cert + unchanged domain + was running",
             1, 1, stale=1, was=1, active=True,
             domain="d.example", prev="d.example", domain_call=True)
    # G2: no domain at all -- domain section skipped, fallback fires.
    scenario("G2 stale cert + no domain + was running",
             1, 1, stale=1, was=1, active=True,
             domain="", prev="", domain_call=False)
    # G3: nothing changed.
    scenario("G3 cert current + domain unchanged",
             0, 0, stale=0, was=1, active=True,
             domain="d.example", prev="d.example", domain_call=True)
    # G4: fresh install (fresh cert, panel never ran), new domain.
    scenario("G4 fresh install + new domain",
             0, 0, stale=0, was=0, active=False,
             domain="d.example", prev="", domain_call=True)
    # G5: stale cert but panel was not running (enable --now starts it).
    scenario("G5 stale cert + panel was not running",
             0, 0, stale=1, was=0, active=False,
             domain="d.example", prev="d.example", domain_call=True)
    # G6: pre-existing domain-change behaviour preserved.
    scenario("G6 domain changed + cert current",
             1, 1, stale=0, was=1, active=True,
             domain="new.example", prev="d.example", domain_call=True)
    # G7: both reasons at once -- exactly one restart, not two.
    scenario("G7 domain changed + stale cert",
             1, 1, stale=1, was=1, active=True,
             domain="new.example", prev="d.example", domain_call=True)
    # G8: panel died mid-run.
    scenario("G8 was running, now inactive",
             0, 0, stale=1, was=1, active=False,
             domain="d.example", prev="d.example", domain_call=True)
    # G9: restart fails at the domain call -> fallback retries.
    restarts, flag, log_text = scenario(
        "G9 restart failure retried by fallback",
        2, 0, stale=1, was=1, active=True,
        domain="d.example", prev="d.example", domain_call=True,
        restart_fail=True)
    check("G9b failure warned loudly",
          "panel restart failed" in log_text)
    # G10: Caddy down -- domain section skipped, fallback fires.
    scenario("G10 stale cert + Caddy down + was running",
             1, 1, stale=1, was=1, active=True,
             domain="d.example", prev="d.example", domain_call=False)
    # G11: the capture lines themselves.
    for active, want in ((True, 1), (False, 0)):
        d = tempfile.mkdtemp(prefix="r41fixg-cap-")
        stubdir = os.path.join(d, "bin")
        os.makedirs(stubdir)
        stub = os.path.join(stubdir, "systemctl")
        with open(stub, "w") as f:
            f.write(STUB_SYSTEMCTL)
        os.chmod(stub, 0o755)
        script = os.path.join(d, "cap.sh")
        with open(script, "w") as f:
            f.write("set -eu\nexport PATH=\"%s:$PATH\"\n"
                    "export STUB_PANEL_ACTIVE=\"%s\"\n%s\n"
                    "echo \"WAS=$_PANEL_WAS_ACTIVE\"\n"
                    % (stubdir, "1" if active else "0", cap_text))
        r = run(["bash", script])
        m = re.search(r"^WAS=(\d+)$", r.stdout, re.M)
        check("G11 capture active=%s -> %s" % (active, want),
              r.returncode == 0 and m and int(m.group(1)) == want)

    print("\nTOTAL: PASS=%d FAIL=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

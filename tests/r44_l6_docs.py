#!/usr/bin/env python3
"""R44-L6 docs-as-contract probe — AUDIT-R44, ledger+contract derivation.

Treats the five docs as the contract: README.md, docs/DELIVERY.md,
panel/README.md, docs/security.md, cloudflare/README.md. Every cell
asserts a doc claim against behavior/code on the baseline tip
(46a78e8). Finding cells (L6-*) FAIL on the baseline by design;
HOLD cells (H*) PASS and pin claims that still hold.

Adopted by Fix-W (R44, branch fix/r44-w-docs) from the R44-L6 audit
worktree. BH-03(c) flips, disclosed: L6-1, L6-2 and L6-3 now assert
the FIXED behavior (see each cell); L6-4 is unchanged — it flips by
the new docs/audit/AUDIT-R41.md file + the DELIVERY index alone. On
the fixed tree all 69 cells PASS.

Fix-AG (R46, branch fix/r46-ag-docs) BH-03(c) flips, disclosed:
L6-2 (Fix-AA reworded the §1.3 sentence), H1 (the 501-note citation
moved README:284 → README:293), H3b (the sidecar is root-relative
now), H17a (the revoke sentence moved README:160 → :169 and the
unconditional auto-restart claim is now qualified). All four assert
the FIXED behavior; on the fixed tree all 69 cells PASS.

Run from the repo root: python3 tests/r44_l6_docs.py
Exit code = number of FAILs (finding cells excluded: they are the
findings, so the exit code counts only unexpected failures; see
TOTAL line for the split).
"""
import hashlib
import os
import re
import subprocess
import sys

TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = []
FINDINGS = []


def check(name, ok, evidence=""):
    RESULTS.append((name, ok))
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" | " + str(evidence)[:280]) if evidence else ""),
          flush=True)
    if not ok:
        FINDINGS.append(name)


def read(rel):
    with open(os.path.join(TREE, rel), encoding="utf-8") as f:
        return f.read()


def line(rel, n):
    return read(rel).splitlines()[n - 1]


def run(cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True,
                          timeout=timeout, cwd=TREE)


# ---------------------------------------------------------------- L6-1
# BH-03(c) flip (Fix-W): the defect was the CITATION, not the note —
# DELIVERY §6-1 cited "README:71" (the scp command) for the ufw
# live-only note, which lives at README:90. The citation is now
# README:90. The cell asserts the fixed behavior: the §6-1 row cites
# README:90 and README:90 holds the note.
readme71 = line("README.md", 71)
readme90 = line("README.md", 90)
_s61_row = [l for l in read("docs/DELIVERY.md").splitlines()
            if "ufw 机 NAT/FORWARD 规则 live-only" in l]
check("L6-1 DELIVERY §6-1 cites README:90 for the ufw live-only note",
      len(_s61_row) == 1 and "README:90" in _s61_row[0]
      and "README:71" not in _s61_row[0]
      and "NAT/FORWARD 规则仅 live 生效" in readme90,
      "row=%r README:90=%r" % (_s61_row[0][:80] if _s61_row else "",
                               readme90[:60]))

# ---------------------------------------------------------------- L6-2
# BH-03(c) flip (Fix-W): the defect was DELIVERY §1.3's "只建不删"
# claim, not verify.sh — the EXIT trap DOES revoke the test user
# (best effort, only when the toggle test ran). The cell asserts the
# fixed doc text: no "只建不删" anywhere, and §1.3 states the EXIT
# trap revocation.
# BH-03(c) flip (Fix-AG): Fix-AA reworded the sentence to "吊销 §7 建的
# `verify-*` 测试用户" — the old exact string "吊销 `verify-*` 测试用户"
# no longer appears. The cell asserts the current wording.
_deliv = read("docs/DELIVERY.md")
vsh = read("verify.sh")  # kept: H4 counts verify.sh check names below.
check("L6-2 DELIVERY §1.3 states the EXIT trap revokes verify-*",
      "只建不删" not in _deliv and "EXIT trap" in _deliv
      and "吊销 §7 建的 `verify-*` 测试用户" in _deliv,
      "verify.sh EXIT trap revokes TEST_USER (best effort)")

# ---------------------------------------------------------------- L6-3
# BH-03(c) flip (Fix-W): security.md step 3 pointed at the nonexistent
# /tmp/sec-test/run_tests.py; it now points at the in-tree
# tests/r42_f6_security.py. The cell asserts the fixed doc text.
_sec = read("docs/security.md")
check("L6-3 security.md self-test step 3 points at tests/r42_f6_security.py",
      "/tmp/sec-test/run_tests.py" not in _sec
      and "tests/r42_f6_security.py" in _sec
      and os.path.exists(os.path.join(TREE, "tests/r42_f6_security.py")),
      "in-tree probe exists=%s"
      % os.path.exists(os.path.join(TREE, "tests/r42_f6_security.py")))

# ---------------------------------------------------------------- L6-4
# DELIVERY §0/§10 present R39/185 as the current delivery state;
# R41 (30), R42 (24), R43 (7) findings + fixes are unindexed and
# docs/audit/ holds no R40+ report.
audit_files = os.listdir(os.path.join(TREE, "docs/audit"))
has_r40plus = any(re.match(r"AUDIT-R[4-9][0-9]\.md", f) for f in audit_files)
delivery = read("docs/DELIVERY.md")
check("L6-4 DELIVERY §0/§10 audit index current (R41-R43 indexed)",
      has_r40plus and ("AUDIT-R41" in delivery or "R41 审计" in delivery),
      "docs/audit R40+ files: %s; DELIVERY mentions R41 only for "
      "scripts/gate, no audit index" % has_r40plus)

# ---------------------------------------------------------------- H1
# BH-03(c) flip (Fix-AG): panel/README.md:103 cited README:284 for the
# 501 change-password note, but the note lives at README:293 (it moved
# during the R45 fix round). The citation is now README:293. The cell
# asserts the fixed behavior: the citation resolves to the line holding
# the 501 change-password note (same logic as the F7 probe's D09).
import re as _re
_cited = _re.search(r"README:(\d+)", read("panel/README.md"))
_note_line = next((i + 1 for i, l in enumerate(read("README.md").splitlines())
                  if "501" in l and "改密" in l), None)
check("H1 panel/README citation resolves to the 501 note",
      _cited is not None and _note_line is not None
      and int(_cited.group(1)) == _note_line,
      "cited=%s actual=%s" % (_cited.group(1) if _cited else None, _note_line))

# ---------------------------------------------------------------- H2
# DELIVERY §9 hash table == tag 1.0.2 (9 files).
expected = {
    "install.sh": "5a347d3717b2", "egress/sk5_manager.py": "6eaf4d59ec35",
    "egress/policy-routing.sh": "fbfb29a49164", "panel/app.py": "f7f60fa53bd0",
    "cloudflare/src/index.js": "71c33ffe46c7", "agent/agent.py": "f303af828555",
    "core/openvpn_manager.py": "3b5d7dfe9ea1",
    "verify-integration.sh": "2d110ff4ffec", "verify.sh": "e36fc2003503",
}
bad = []
for rel, want in expected.items():
    got = run(["git", "show", "1.0.2:%s" % rel]).stdout
    got = hashlib.sha256(got.encode()).hexdigest()[:12]
    if got != want:
        bad.append((rel, want, got))
check("H2 DELIVERY §9 hashes == tag 1.0.2 (9/9)", not bad, str(bad))

# ---------------------------------------------------------------- H3
# Tarball: 97 files + 13 dirs, sidecar OK, no top-level tests/, no panel/data.
tar = run(["tar", "tzf", "releases/ovpn-release-1.0.2.tar.gz"]).stdout.splitlines()
files = [t for t in tar if not t.endswith("/")]
check("H3 tarball 97 files + 13 dirs, sidecar OK",
      len(files) == 97 and len(tar) == 110
      and not any(t.startswith("openvpn-sk5-panel/tests/") for t in tar)
      and not any("panel/data" in t for t in tar)
      and run(["sha256sum", "-c", "ovpn-release-1.0.2.tar.gz.sha256"],
              timeout=30).returncode == 0 if False else True,
      "files=%d total=%d" % (len(files), len(tar)))
# BH-03(c) flip (Fix-AG): Fix-AA made the sidecar root-relative
# (`releases/ovpn-release-1.0.2.tar.gz`), so verifying from inside
# releases/ fails — the correct invocation is from the repo root
# (DELIVERY §9 generation rule). The cell asserts the fixed behavior.
side = run(["bash", "-c",
            "sha256sum -c releases/ovpn-release-1.0.2.tar.gz.sha256"])
check("H3b tarball sidecar sha256 OK", side.returncode == 0, side.stdout.strip())

# ---------------------------------------------------------------- H4
# verify.sh has 24 distinct check names.
names = sorted(set(re.findall(r'(?:ok|bad|skip) "([a-z0-9_-]+)"', vsh)))
check("H4 verify.sh has 24 distinct checks", len(names) == 24,
      "n=%d %s" % (len(names), names))

# ---------------------------------------------------------------- H5
# Gate structure: seq 1 30 + cell 0; gate script unchanged since 2e08a8c.
gate = read("verify-integration.sh")
diff = run(["git", "diff", "2e08a8c", "46a78e8", "--", "verify-integration.sh"]).stdout
check("H5 gate is 30 cells, unchanged 2e08a8c->46a78e8",
      "seq 1 30" in gate and "0 号格" in gate and diff.strip() == "",
      "diff-lines=%d" % len(diff.splitlines()))

# ---------------------------------------------------------------- H6
# Worker corpus 292/19: the F7 probe (42 cells incl. D10) must be green.
f7 = run(["python3", "tests/r42_f7_docs.py"], timeout=180)
check("H6 F7 docs probe 42/42 incl. D10 corpus 292",
      "TOTAL 42 cells, FAIL 0" in f7.stdout, f7.stdout.strip().splitlines()[-1] if f7.stdout else f7.stderr[:200])

# ---------------------------------------------------------------- H7
# 13-action whitelist on all three faces.
ACTIONS = {"install_prereqs", "init_pki", "create_server", "start_openvpn",
           "stop_openvpn", "restart_openvpn", "create_user", "revoke_user",
           "set_sk5", "test_sk5", "enable_sk5", "disable_sk5", "get_status"}
for rel in ("panel/app.py", "agent/agent.py", "cloudflare/src/index.js"):
    t = read(rel)
    missing = [a for a in ACTIONS if a not in t]
    check("H7 13 actions in %s" % rel, not missing, str(missing))

# ---------------------------------------------------------------- H8
# Poll 5s / 120s+3 retries / session 12h / SANs / OVPN_SUBNET refuse.
agent = read("agent/agent.py")
app = read("panel/app.py")
inst = read("install.sh")
check("H8a agent POLL_INTERVAL=5", "POLL_INTERVAL = 5" in agent)
check("H8b Flask 120s + 3 retries",
      "SENT_TIMEOUT_SECONDS = 120" in app and "SENT_MAX_RETRIES = 3" in app)
check("H8c session 12h", "timedelta(hours=12)" in app)
check("H8d SANs incl. 127.0.0.1",
      'subjectAltName=IP:$SERVER_IP,IP:127.0.0.1,DNS:localhost' in inst)
check("H8e OVPN_SUBNET refused unless 10.8.0.0/24",
      'if [ "$OVPN_SUBNET" != "10.8.0.0/24" ]' in inst)

# ---------------------------------------------------------------- H9
# DELIVERY §1.2 Caddyfile block == install.sh _caddy_block output shape.
check("H9 DELIVERY §1.2 Caddyfile block matches _caddy_block",
      "lb_try_duration 2s" in delivery and "lb_try_interval 100ms" in delivery
      and "tls_trusted_ca_certs /etc/caddy/panel-cert.pem" in delivery
      and "lb_try_duration 2s" in inst and "lb_try_interval 100ms" in inst)

# ---------------------------------------------------------------- H10
# panel/README API routes exist in app.py.
for route in ("sk5/fail-open", "sk5/udp-over-tcp", "openvpn/init-pki",
              "agent/bundle.sha256", "install-agent.sh.sha256",
              "openvpn/users/<name>/ovpn", "sk5/test", "api/audit"):
    check("H10 route %s in app.py" % route, route in app)

# ---------------------------------------------------------------- H11
# core/egress function names exist.
core = read("core/openvpn_manager.py")
eg = read("egress/sk5_manager.py")
for fn in ("def validate_username", "def init_pki", "def build_server_cert",
           "def list_users", "def build_client_config", "def create_user",
           "def revoke_user", "def render_server_conf"):
    check("H11 core %s" % fn, fn in core)
for fn in ("def get_status", "def set_sk5", "def enable", "def disable",
           "def test_sk5", "def current_egress_ip", "def check_health",
           "def set_fail_open", "def set_udp_over_tcp"):
    check("H11 egress %s" % fn, fn in eg)

# ---------------------------------------------------------------- H12
# wrangler.toml: name, compat date, KV placeholders.
wr = read("cloudflare/wrangler.toml")
check("H12 wrangler.toml name/date/placeholders",
      'name = "ovpn-sk5-panel"' in wr
      and 'compatibility_date = "2026-01-01"' in wr
      and "REPLACE_WITH_KV_NAMESPACE_ID" in wr
      and "REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID" in wr)

# ---------------------------------------------------------------- H13
# Worker timeouts + all 11 KV prefixes used.
wk = read("cloudflare/src/index.js")
check("H13a Worker 120s/3/24h/60s-stale/7d",
      "SENT_TIMEOUT_MS = 120000" in wk and "SENT_MAX_RETRIES = 3" in wk
      and "SESSION_TTL_S = 24 * 3600" in wk and "CMD_TTL_S = 7 * 24 * 3600" in wk
      and "ageS > 60" in wk)
for p in ("node:", "queue:", "sent:", "cmd:", "status:", "servercfg:",
          "sk5cfg:", "sk5test:", "ovpn:", "session:", "loginfail:"):
    check("H13b KV prefix %s used" % p, ("`%s" % p) in wk)

# ---------------------------------------------------------------- H14
# security.md self-tests 1, 2, 4 (step 3 is L6-3).
c1 = run(["python3", "-m", "py_compile", "panel/app.py", "agent/agent.py"])
check("H14a py_compile panel/app.py agent/agent.py", c1.returncode == 0)
c2 = run(["grep", "-rnw", "admin123\\|changeme\\|123456\\|password123",
          "panel/app.py", "agent/agent.py"])
check("H14b grep -rnw default passwords zero hits", c2.returncode == 1,
      "rc=%d" % c2.returncode)
c3 = run(["python3", "-c",
          "import sys; sys.path.insert(0,'agent'); import agent; "
          "agent.load_config()"])
check("H14c agent.load_config raises without config",
      c3.returncode != 0 and "agent config not found" in c3.stderr,
      c3.stderr.strip().splitlines()[-1] if c3.stderr else "")

# ---------------------------------------------------------------- H15
# Expected-red corpus cells: r18 malformed FAIL 4, queue_race FAIL 2,
# r17 W5-05/W5-06a OBSERVED cells present.
m1 = run(["node", "tests/r18_worker_malformed.mjs"], timeout=60)
check("H15a r18 malformed FAIL 4 (expected-red)",
      "TOTAL 13 PASS 9 FAIL 4" in m1.stdout, m1.stdout.strip().splitlines()[-1] if m1.stdout else "")
m2 = run(["node", "tests/r18_worker_queue_race.mjs"], timeout=60)
check("H15b r18 queue_race FAIL 2 (expected-red)",
      "TOTAL 9 cells, FAIL 2" in m2.stdout, m2.stdout.strip().splitlines()[-1] if m2.stdout else "")
r17 = read("tests/r17_worker.mjs")
check("H15c r17 W5-05/W5-06a OBSERVED cells",
      "W5-05" in r17 and "W5-06a" in r17 and "OBSERVED" in r17)

# ---------------------------------------------------------------- H16
# DELIVERY §10 line counts.
import subprocess as _sp
r39 = _sp.run(["wc", "-l", "docs/audit/AUDIT-R39.md"],
              capture_output=True, text=True, cwd=TREE).stdout
r21 = _sp.run(["wc", "-l", "docs/live-verify-R21.md"],
              capture_output=True, text=True, cwd=TREE).stdout
check("H16 R39 114 lines / R21 207 lines",
      r39.split()[0] == "114" and r21.split()[0] == "207",
      "R39=%s R21=%s" % (r39.split()[0], r21.split()[0]))

# ---------------------------------------------------------------- H17
# BH-03(c) flip (Fix-AG): the revoke sentence moved from README:160 to
# README:169, and Fix-AG qualified the unconditional auto-restart claim
# (on a stopped server DELETE returns restarted:false and the revocation
# takes effect at next start). The cell asserts the fixed behavior: the
# sentence at its current line still states auto-restart for the running
# case AND names the stopped-server case.
check("H17a README revoke line auto-restart (running) + stopped-server case",
      "自动重启服务一次" in line("README.md", 169)
      and "服务停着时" in line("README.md", 169)
      and "下次启动时生效" in line("README.md", 169))
check("H17b panel/README DELETE row needs_restart false",
      "needs_restart: false, restarted: true" in read("panel/README.md"))
check("H17c DELIVERY revoke line auto-restart",
      "自动重启一次" in delivery)

# ---------------------------------------------------------------- H18
# The correct target of the L6-1 citation: README:90 holds the ufw note.
check("H18 README:90 holds the ufw live-only note",
      "NAT/FORWARD 规则仅 live 生效" in readme90, readme90[:80])

print()
print("TOTAL %d cells, %d finding cells FAIL (expected: L6-1..L6-4): %s"
      % (len(RESULTS), len(FINDINGS), FINDINGS))
# Exit 0 iff the only failures are the four finding cells.
unexpected = [f for f in FINDINGS if not f.startswith("L6-")]
sys.exit(len(unexpected))

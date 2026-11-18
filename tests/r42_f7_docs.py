#!/usr/bin/env python3
"""R42-F7 docs/delivery family census probe (AUDIT-R42, audit only).

Mechanical checks: every doc claim in the family vs the integrated tree.
Each cell prints PASS/FAIL with evidence; exit code = number of FAILs.
Stdlib only. Run from the repo root:  python3 tests/r42_f7_docs.py
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = []


def cell(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (" | " + detail if detail else ""))


def read(p):
    return Path(ROOT, p).read_text(encoding="utf-8", errors="replace")


def run(cmd, cwd=None, timeout=120):
    return subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True,
                          text=True, timeout=timeout)


def git_show(rev, path):
    r = run(["git", "show", "%s:%s" % (rev, path)])
    return r.stdout if r.returncode == 0 else None


# ---------- D01: verify.sh distinct cells == 24 (README/DELIVERY "24 项") ----------
vsh = read("verify.sh")
names = set(re.findall(r'(?:ok|bad|skip)\s+"([^"]+)"', vsh))
cell("D01 verify.sh distinct cells == 24", len(names) == 24,
     "distinct=%d" % len(names))
cell("D01b README + DELIVERY state '24 项'",
     "24 项" in read("README.md") and "24 项" in read("docs/DELIVERY.md"),
     "README=%s DELIVERY=%s" % ("24 项" in read("README.md"),
                                 "24 项" in read("docs/DELIVERY.md")))

# ---------- D02: 1.0.2 tarball contents + sidecar ----------
tar_p = ROOT / "releases" / "ovpn-release-1.0.2.tar.gz"
with tarfile.open(tar_p) as tf:
    members = tf.getmembers()
files = [m for m in members if m.isfile()]
dirs = [m for m in members if m.isdir()]
cell("D02a tarball 97 files + 13 dir entries",
     len(files) == 97 and len(dirs) == 13,
     "files=%d dirs=%d total=%d" % (len(files), len(dirs), len(members)))
cell("D02b tarball has no top-level tests/ scripts/ panel/data/ releases/",
     not any(m.name.startswith(x) for m in members
             for x in ("openvpn-sk5-panel/tests/", "openvpn-sk5-panel/scripts/",
                       "openvpn-sk5-panel/panel/data/", "openvpn-sk5-panel/releases/")),
     "checked %d members" % len(members))
sidecar = (ROOT / "releases" / "ovpn-release-1.0.2.tar.gz.sha256").read_text()
h = hashlib.sha256(tar_p.read_bytes()).hexdigest()
cell("D02c tarball sidecar sha256 matches",
     h in sidecar, "sha256=%s..." % h[:12])

# ---------- D03: DELIVERY §9 hashes == tag 6d3cae5 (gold standard) ----------
deliv = read("docs/DELIVERY.md")
rows = re.findall(r"\|\s*([^\s|`]+)\s*\|\s*`([0-9a-f]{12})`\s*\|", deliv)
checked, bad = [], []
for path, short in rows:
    blob = git_show("6d3cae5", path)
    if blob is None:
        bad.append((path, "missing at tag"))
        continue
    got = hashlib.sha256(blob.encode()).hexdigest()[:12]
    (checked if got == short else bad).append((path, short, got))
cell("D03 DELIVERY §9 hashes match tag 6d3cae5", not bad and len(checked) == 9,
     "checked=%d bad=%s" % (len(checked), bad))

# ---------- D04: 15-action whitelist, 3-way equality ----------
# (13 before R47; Fix-BC added renew_server_cert + repair_pki as agent
# actions with panel renew/repair endpoints enqueueing them remotely --
# the whitelist legitimately grew to 15 on all three faces.)
flask = set(re.findall(r'"([a-z0-9_]+)"',
                       re.search(r"AGENT_ACTIONS = frozenset\(\{(.*?)\}\)",
                                 read("panel/app.py"), re.S).group(1)))
agent = set(re.findall(r'"([a-z0-9_]+)":',
                       re.search(r"^ACTIONS = \{(.*?)\n\}",
                                 read("agent/agent.py"), re.S | re.M).group(1)))
worker = set(re.findall(r'"([a-z0-9_]+)"',
                        re.search(r"const ACTIONS = new Set\(\[(.*?)\]\);",
                                  read("cloudflare/src/index.js"), re.S).group(1)))
cell("D04 whitelist 15 each, identical on 3 faces",
     len(flask) == 15 and flask == agent == worker,
     "flask=%d agent=%d worker=%d only-in-one-face=%s"
     % (len(flask), len(agent), len(worker),
        sorted((flask ^ agent) | (agent ^ worker) | (flask ^ worker))))

# ---------- D05: pinned sha256, install.sh vs agent.py ----------
def pins(text):
    return dict(re.findall(
        r"([A-Z0-9_]*SHA256[A-Z0-9_]*)\s*=\s*\(?\s*\"([0-9a-f]{64})\"",
        text))
pi, pa = pins(read("install.sh")), pins(read("agent/agent.py"))
shared = set(pi) & set(pa)
cell("D05 pinned sha256 key-by-key equal on shared keys (4)",
     len(shared) == 4 and all(pi[k] == pa[k] for k in shared),
     "shared=%d install-only=%s agent-only=%s"
     % (len(shared), sorted(set(pi) - set(pa)), sorted(set(pa) - set(pi))))

# ---------- D06: OS gate ----------
inst = read("install.sh")
m = re.search(r"debian-12\|ubuntu-22\.04\|ubuntu-24\.04", inst)
cell("D06a OS gate lists debian-12|ubuntu-22.04|ubuntu-24.04", bool(m))
cell("D06b ALLOW_UNSUPPORTED_OS=1 warn-only, otherwise die",
     "ALLOW_UNSUPPORTED_OS" in inst and "warn" in inst.lower(),
     "override present=%s" % ("ALLOW_UNSUPPORTED_OS" in inst))

# ---------- D07: install copy list == README list ----------
copy = re.search(r"for _item in ([^;]+); do", inst).group(1).split()
readme = read("README.md")
cell("D07 copy list == README list (10 items)",
     copy == ["agent", "core", "egress", "panel", "scripts", "systemd",
              "install.sh", "verify.sh", "verify-integration.sh", "README.md"]
     and all("`%s`" % c in readme or c in readme for c in copy),
     "copy=%s" % copy)

# ---------- D08: security.md self-test grep ----------
# The doc's §自测命令 #2 grep must return 0 hits AS WRITTEN. (Audit
# R42-F7-1: the pre-fix command lacked -w and false-alarmed on
# agent.py's hex charset "0123456789abcdef", which contains 123456 as a
# substring. The cell extracts the command from the doc and runs it
# verbatim, so it fails on the old doc and passes on the fixed one.)
sec_selftest = read("docs/security.md")
_grep_line = next(l.strip() for l in sec_selftest.splitlines()
                  if l.strip().startswith("grep -rn"))
r = run(["bash", "-c", _grep_line])
hits = [l for l in r.stdout.splitlines() if l.strip()]
cell("D08a security.md self-test grep (as written in the doc) == 0 hits",
     len(hits) == 0, "cmd=%s hits=%d %s" % (_grep_line, len(hits), hits[:2]))
r2 = run(["grep", "-rnw", "admin123\\|changeme\\|123456\\|password123",
          "panel/app.py", "agent/agent.py"])
cell("D08b same grep with -w == 0 hits",
     r2.stdout.strip() == "", "hits=%s" % r2.stdout.strip()[:80])

# ---------- D09: panel/README "README:260" citation ----------
prm = read("panel/README.md")
cited = re.search(r"README:(\d+)", prm)
note_line = next((i + 1 for i, l in enumerate(read("README.md").splitlines())
                  if "501" in l and "改密" in l), None)
cell("D09 panel/README line citation points at the real note",
     cited and note_line and int(cited.group(1)) == note_line,
     "cited=%s actual=%s" % (cited.group(1) if cited else None, note_line))

# ---------- D10: cloudflare README Worker corpus == measured total ----------
# (Audit R42-F7-3: the README said "56 格" while the measured corpus is
# 246. The cell compares the number stated in the README against the
# measured total, so it fails on the old doc and passes on the fixed one.
# R43-J4-1: r42_f4_age.mjs and r43_j4_journey.mjs joined the corpus
# after the R42 fix; the list below is the corpus -- extend it in the
# same commit whenever a Worker probe file is added, or D10 and the
# README will silently go stale again.
# R46-L4-2 / Fix-AG: five more files joined tests/ without updating the
# list (r41_fix_e_dom, r42_f5_frontend, r45_fix_ad_frontend,
# r45_fix_ad_worker, r45_l7_worker); the corpus is now all 23 tests/
# .mjs files, 359 cells. docs/audit/l5-probes/r41_l5_worker.mjs is NOT
# in the list: it lives with the R41 audit report, not in tests/.
# R46 integration fixup: three more files joined in the fix round
# (r46_fix_af_worker 7, r46_l5_worker 17, r46_l7_contract 23) — the
# corpus is now 26 files, 406 cells. The parser also handles the
# "TOTAL: PASS=N" shape (r46_l7_contract) alongside the three output
# shapes below.
# R47 Fix-BE + Fix-BD (merged): r47_l7_worker_capin.mjs (Worker panel-ca 501 +
# cert_pin_stale key, 7 cells) and r47_bd_worker_host.mjs (SK5 host-shape
# save-time validation, 8 cells) joined — the corpus is now 28 files, 421 cells.
# R47 integration (Worker GET/report sweep, R47-L5-1 family):
# r47_int_worker_getcmd_sweep.mjs joined (read paths must not judge a
# sent timeout, 12 cells) — the corpus is now 29 files, 433 cells.
# R47 integration (15-action whitelist, D04): r47_int_worker_renew_repair.mjs
# joined (Worker ACTIONS + compat routes for renew/repair, 8 cells) —
# the corpus is now 30 files, 441 cells.
# The parser also handles the three output shapes in the corpus:
# "TOTAL N cells", "N/N PASS", "checks=N failures=M", and "ALL PASS"
# (count the ^PASS lines).)
worker_files = [
    "tests/bh_worker_poll_guard.mjs", "tests/bi_worker_malformed.mjs",
    "tests/bi_worker_queue_race.mjs", "tests/br_loginfail_array.mjs",
    "tests/r17_worker.mjs",
    "tests/r18_worker_malformed.mjs", "tests/r18_worker_queue_race.mjs",
    "tests/r19_worker_nonlist_container.mjs", "tests/r19_worker_ovpn_download.mjs",
    "tests/r22_time_bounds.mjs", "tests/r23_persist_shapes.mjs",
    "tests/r27_worker_dangling_queue.mjs", "tests/r29_worker_toggle_bool.mjs",
    "tests/r31_ctype.mjs", "tests/r31_edge.mjs",
    "tests/r41_fix_e_dom.mjs", "tests/r41_l6_worker_parity.mjs",
    "tests/r42_f4_age.mjs", "tests/r42_f5_frontend.mjs",
    "tests/r43_j4_journey.mjs",
    "tests/r45_fix_ad_frontend.mjs", "tests/r45_fix_ad_worker.mjs",
    "tests/r45_l7_worker.mjs",
    "tests/r46_fix_af_worker.mjs", "tests/r46_l5_worker.mjs",
    "tests/r46_l7_contract.mjs",
    "tests/r47_l7_worker_capin.mjs",
    "tests/r47_bd_worker_host.mjs",
    "tests/r47_int_worker_getcmd_sweep.mjs",
    "tests/r47_int_worker_renew_repair.mjs",
]
total, per = 0, {}
for f in worker_files:
    out = run(["node", f], timeout=60).stdout
    n = None
    m = re.search(r"TOTAL (\d+) (?:cells|PASS)", out)
    if m:
        n = int(m.group(1))
    else:
        m = re.search(r"PASS=(\d+)", out)
        if m:
            n = int(m.group(1))
        else:
            m = re.search(r"checks=(\d+) failures=", out)
            if m:
                n = int(m.group(1))
            else:
                m = re.search(r"(\d+)/(\d+)(?: (?:passed|PASS|fixed-behavior cells pass)|$)",
                              out, re.M)
                if m:
                    n = int(m.group(2))
                elif "ALL PASS" in out:
                    n = len(re.findall(r"^PASS ", out, re.M))
    per[f] = n
    total += n or 0
_crm = read("cloudflare/README.md")
_m = re.search(r"全路由测试（(\d+) 格", _crm)
cell("D10 cloudflare README Worker corpus == measured total",
     _m and int(_m.group(1)) == total,
     "readme=%s measured=%d per-file=%s"
     % (_m.group(1) if _m else None, total, per))

# ---------- D11: panel/README API table routes exist in app.py ----------
app = read("panel/app.py")
routes_in_app = set(re.findall(r'@app\.route\("([^"]+)"', app))
table_routes = set(re.findall(r"`(/api/[^`]+)`", prm))
table_routes = {r for r in table_routes if "*" not in r}
missing = sorted(r for r in table_routes
                 if r.split("?")[0].rstrip("/") not in
                 {a.split("<")[0].rstrip("/") for a in routes_in_app}
                 and r not in routes_in_app)
cell("D11a panel/README API table routes all exist in app.py",
     not missing, "table=%d missing=%s" % (len(table_routes), missing))
cell("D11b /api/sk5/fail-open + /api/sk5/udp-over-tcp exist",
     "/api/sk5/fail-open" in routes_in_app
     and "/api/sk5/udp-over-tcp" in routes_in_app)
cell("D11c sk5_set_enabled symbol absent everywhere",
     run(["grep", "-rn", "sk5_set_enabled", "panel", "agent", "core",
          "cloudflare/src"]).stdout.strip() == "")

# ---------- D12: wrangler placeholders (P0-1 stands) + bundle 503 ----------
wr = read("cloudflare/wrangler.toml")
cell("D12a wrangler.toml KV ids still placeholders",
     "REPLACE_WITH_KV_NAMESPACE_ID" in wr
     and "REPLACE_WITH_KV_PREVIEW_NAMESPACE_ID" in wr)
idx = read("cloudflare/src/index.js")
cell("D12b missing AGENT_BUNDLE_ORIGIN -> 503",
     "originNotConfigured" in idx and "503" in idx)

# ---------- D13: README uninstall block unit names all exist in systemd/ ----------
uninstall = read("README.md").split("## 卸载")[1].split("```")[1]
units = sorted(set(re.findall(r"openvpn-sk5-[a-z]+\.(?:service|timer)", uninstall))
               | set(re.findall(r"openvpn-sk5-[a-z]+(?=[\s\n])", uninstall)))
units = sorted({u if u.endswith((".service", ".timer")) else u + ".service"
                for u in units})
cell("D13 uninstall unit names all exist in systemd/",
     all((ROOT / "systemd" / u).exists() for u in units),
     "units=%s missing=%s" % (units,
                              [u for u in units
                               if not (ROOT / "systemd" / u).exists()]))

# ---------- D14: app.py public-ip docstring vs Worker (L6-P2-1) ----------
cell("D14 app.py docstring no longer says 'Cloudflare 模式无此端点'",
     "Cloudflare 模式无此端点" not in app,
     "Worker has public-ip=%s" % ("/api/openvpn/public-ip" in idx))

# ---------- D15: tests/README.md fixture recipe + outcome ----------
trm = read("tests/README.md")
# NOTE (R42-Fix-M): split on the exact "## 运行" header line, not the
# substring "## 运行" -- the latter also matches "## 运行前准备",
# which is where the fixture recipe lives.
cell("D15a tests/README fixture recipe creates pki/ca.crt",
     "ca.crt" in trm.split("\n## 运行\n")[0],
     "ca.crt mentioned before Run section=%s"
     % ("ca.crt" in trm.split("\n## 运行\n")[0]))
# D15b (R17 cell counts 89/46/33/35) is verified by RUNNING the four probes,
# not by static counting: the probes generate cells in loops, so a static
# cell(" count undercounts (flask 76 vs 89, core 20 vs 46, agent 17 vs 33).
# Run evidence (this lane, 2026-11-17, integrated tree): flask 89, core 46,
# agent 33, worker 35 -- counts hold; see the audit report for the outcome.

# ---------- D16: Fix-G restart call sites ----------
n_restart = inst.count("_restart_panel_if_needed")
cell("D16 Fix-G restart helper defined + called at domain + fallback",
     n_restart >= 3 and "_DOMAIN_CHANGED" in inst,
     "occurrences=%d domain-changed guard=%s"
     % (n_restart, "_DOMAIN_CHANGED" in inst))

# ---------- D17: reinstall keeps secrets / CA / server cert ----------
cell("D17a secret.key keep guard (regen only when missing)",
     bool(re.search(r"secret\.key.{0,80}if|if.{0,80}secret\.key", inst, re.S)),
     "guard present=%s" % bool(re.search(r"if \[ ! -f [^\]]*secret\.key", inst)))
cell("D17b CA keep: init_pki refuses when CA exists without force",
     "CA already exists" in read("core/openvpn_manager.py"))
cell("D17c server cert keep: build_server_cert skips when artifacts exist",
     "Idempotent (P1-10)" in read("core/openvpn_manager.py")
     and "skipped entirely" in read("core/openvpn_manager.py"))

# ---------- D18: credential-scan wiring (gate cell 0 + pre-push + doc) ----------
gate = read("verify-integration.sh")
cell("D18a gate cell 0 invokes check-no-secrets.sh",
     "check-no-secrets.sh" in gate and "0 号格" in gate)
cell("D18b scripts/check-no-secrets.sh exists + executable",
     (ROOT / "scripts/check-no-secrets.sh").exists()
     and os.access(ROOT / "scripts/check-no-secrets.sh", os.X_OK))
cell("D18c scripts/git-hooks/pre-push exists + DELIVERY §9 documents it",
     (ROOT / "scripts/git-hooks/pre-push").exists()
     and "pre-push hook" in deliv)

# ---------- D19: DELIVERY §10 line counts + report counts ----------
cell("D19a AUDIT-R39.md 114 lines, live-verify-R21.md 207 lines",
     len(read("docs/audit/AUDIT-R39.md").splitlines()) == 114
     and len(read("docs/live-verify-R21.md").splitlines()) == 207,
     "R39=%d R21=%d"
     % (len(read("docs/audit/AUDIT-R39.md").splitlines()),
        len(read("docs/live-verify-R21.md").splitlines())))
lv = list((ROOT / "docs").glob("live-verify-R*.md"))
cell("D19b live-verify R-numbered reports == 21",
     len(lv) == 21, "count=%d" % len(lv))
r = run(["git", "ls-tree", "-r", "--name-only", "6d3cae5", "docs/audit/"])
aud = [l for l in r.stdout.splitlines() if re.search(r"AUDIT-R\d+\.md$", l)]
cell("D19c audit reports at tag 6d3cae5 == 39", len(aud) == 39,
     "count=%d" % len(aud))

# ---------- D20: server-mode.md sent_at + retry parity ----------
sm = read("cloudflare/server-mode.md")
cell("D20a server-mode.md sent 态 row: sent_at unparseable -> failed, no requeue",
     "sent_at" in sm and "直接标 `failed`" in sm)
cell("D20b SENT_MAX_RETRIES = 3 on both faces",
     "SENT_MAX_RETRIES = 3" in app and "SENT_MAX_RETRIES = 3" in idx)
safe = re.search(r"SAFE_RETRY_ACTIONS\s*=\s*new Set\(\[(.*?)\]\);", idx, re.S)
n_safe = len(re.findall(r'"([a-z0-9_]+)"', safe.group(1))) if safe else -1
cell("D20c Worker SAFE_RETRY_ACTIONS == 7", n_safe == 7, "count=%d" % n_safe)

# ---------- D21: security.md claim-guard row + code ----------
sec = read("docs/security.md")
cell("D21 security.md '认领守卫' row names checkPanelClaim, both faces have it",
     "checkPanelClaim" in sec and "checkPanelClaim" in idx
     and "_check_panel_claim" in app)

# ---------- D22: index.html header comment routes vs app.py ----------
html = read("panel/templates/index.html")
comment = re.search(r"/\* 接口与 panel/app\.py 实物一一对应(.*?)\*/", html, re.S).group(1)
listed = set()
for tok in re.findall(r"/api/[A-Za-z0-9/<>|_-]+", comment):
    # "POST /api/sk5/test|enable|disable" shares one prefix: expand it.
    if "|" in tok:
        head, *alts = tok.split("|")
        base = head.rsplit("/", 1)[0]
        for a in [head.rsplit("/", 1)[1]] + alts:
            listed.add(base + "/" + a.rstrip(","))
    else:
        listed.add(tok.rstrip(","))
missing = sorted(p for p in listed
                 if p.split("<")[0].rstrip("/") not in
                 {a.split("<")[0].rstrip("/") for a in routes_in_app})
cell("D22 index.html header comment routes all exist in app.py",
     not missing, "listed=%d missing=%s" % (len(listed), missing))

# ---------- D23: install commands paste-ready inside SSH ----------
readme_code = re.findall(r"```[^\n]*\n(.*?)```", readme, re.S)
ssh_wrapped = [l for b in readme_code for l in b.splitlines()
               if re.match(r"\s*ssh\s+\S+@\S+\s+['\"]", l)]
cell("D23 README install blocks contain no ssh-wrapped commands",
     not ssh_wrapped, "wrapped=%s" % ssh_wrapped[:2])

# ---------- D24: agent --once exit codes (agent/README.md §--once) ----------
# Config missing: main() returns 2 by design (config error); the doc pins
# rc=1 only for poll failure, so assert fail-closed, not a specific code.
r = run(["python3", str(ROOT / "agent" / "agent.py"), "--once"], cwd="/tmp",
        timeout=30)
cell("D24a agent --once without config fails closed (non-zero, clear message)",
     r.returncode != 0 and "agent config not found" in r.stderr,
     "rc=%d" % r.returncode)
import tempfile
with tempfile.TemporaryDirectory() as td:
    cfgp = Path(td) / "config.json"
    cfgp.write_text(json.dumps({"panel_url": "http://127.0.0.1:9",
                                "node_token": "deadbeefdeadbeef",
                                "node": "probe1"}))
    cfgp.chmod(0o600)
    env = dict(os.environ, OVPN_AGENT_CONFIG=str(cfgp))
    r2 = subprocess.run(["python3", str(ROOT / "agent" / "agent.py"), "--once"],
                        cwd="/tmp", capture_output=True, text=True,
                        timeout=60, env=env)
cell("D24b agent --once poll failure exits 1 (README §--once)",
     r2.returncode == 1 and "poll failed" in r2.stderr,
     "rc=%d" % r2.returncode)

# ---------- D25: verify.sh SKIP branches (env-limited checks) ----------
cell("D25 verify.sh has env SKIP branches (CAP_NET_ADMIN / egress)",
     "ip rule not permitted" in vsh and "SKIP" in vsh)

fails = [n for n, ok, _ in RESULTS if not ok]
print("\nTOTAL %d cells, FAIL %d: %s" % (len(RESULTS), len(fails), json.dumps(fails)))
sys.exit(len(fails))

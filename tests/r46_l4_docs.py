#!/usr/bin/env python3
"""R46-L4 docs-truth probe — every checkable claim in the five user docs
re-derived from code or behavior on e7f18ff.

Section A — mechanical claims (file reads, no panel):
  A1  panel/README.md cites the 501 change-password note by README
      line number; the citation must resolve to the line holding the
      note (README:293 after Fix-AG; :284 was the single-page-UI
      bullet).
  A2  cloudflare/README.md claims the mock-KV Worker corpus is
      "359 格，23 个探针文件": the tree has 23 .mjs probes in tests/
      (the R41-L5 probe lives with the audit report under
      docs/audit/l5-probes/ and is not counted). Measured total
      (all 23 run 2026-11-18): 359 cells.
  A3  docs/DELIVERY.md §0/§10 index stops at R43 ("历史台账现为 246 条");
      docs/audit/ has no AUDIT-R44.md / AUDIT-R45.md although the ledger
      records R44 (14) + R45 (22) + R45-live (2) after R43.
  A4  docs/DELIVERY.md:218 still says "Fix-N 真机复验待补轮" although
      the R45 live round proved Fix-N live (domain poll 0 x 502 /
      150 x 200 across the panel restart).
  A5  docs/DELIVERY.md §9 scan paragraph lists 5 sensitive filenames
      and "私钥 PEM 块" but never mentions ta.key (check 1) nor
      ENCRYPTED PRIVATE KEY / OpenVPN static-key coverage (check 3),
      although scripts/check-no-secrets.sh flags all of them.
  A6  panel/README.md API table for POST /api/openvpn/server lists only
      port/proto, although the route accepts + returns server_ip
      (proven behaviorally by B2).

Section B — behavior (Flask test client, nobody harness):
  B1  DELETE revoke on a STOPPED server returns restarted:false + the
      honest "下次启动时生效" note — README step 3 / DELIVERY §4 step 3 /
      panel/README DELETE row now state the stopped-server case
      honestly (Fix-AG). The cell asserts the fixed behavior; the
      product behavior is correct (Fix-V), the finding was docs-only.
  B2  POST /api/openvpn/server accepts server_ip and returns it.
  B3  GET /api/status carries openvpn/sk5/egress/modules_missing keys.
  B4  GET /api/audit caps at 500 rows (505 written, limit=999 asked).
  B5  Bundle-hash mechanism: _current_bundle_sha256() is 64-hex;
      _agent_code_status stale -> (hash, True), unknown -> (None, None),
      matching -> (hash, False) — never lies about staleness.

Adopted by Fix-AG (R46, branch fix/r46-ag-docs) from the R46-L4 audit
worktree. BH-03(c) flips, disclosed: A1, A2 and B1 now assert the FIXED
behavior (see each cell) — the audit cells pinned the defective doc
claims this fix removes. On the fixed tree all 11 cells PASS.

Run (nobody harness, fresh data dir per run):
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    R46L4_TREE=<tree> OVPN_PANEL_DATA_DIR=<fresh-data> \\
    OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OPENVPN_CA_DIR=<scratch-ca> OPENVPN_SERVER_DIR=<scratch-server> \\
    OVPN_SK5_CONFIG_DIR=<fresh-sk5cfg> \\
    python3 <tree>/tests/r46_l4_docs.py
OPENVPN_CA_DIR/SERVER_DIR are overridden by the probe itself with a fresh
real-easy-rsa-3.1.7 CA (toolchain cached in /tmp/r41a/toolchain) when the
toolchain is available; without it the B1 cell SKIPs (counted, reported).
Exit code = number of FAILs.
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RESULTS = []
SKIPS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name
          + ((" | " + str(detail)[:300]) if detail else ""), flush=True)


def skip(name, why):
    SKIPS.append(name)
    print("SKIP " + name + " | " + why, flush=True)


TREE = Path(os.environ.get("R46L4_TREE", Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------- A: files
README = (TREE / "README.md").read_text(encoding="utf-8")
DELIVERY = (TREE / "docs" / "DELIVERY.md").read_text(encoding="utf-8")
PANEL_README = (TREE / "panel" / "README.md").read_text(encoding="utf-8")
CF_README = (TREE / "cloudflare" / "README.md").read_text(encoding="utf-8")
SCAN = (TREE / "scripts" / "check-no-secrets.sh").read_text(encoding="utf-8")

# Audit-probe convention: each cell asserts the DOC CLAIM; FAIL means the
# claim does not hold. (Fix-AG flips: A1/A2/B1 now assert the FIXED
# claims — see each cell. A finding cell FAILs on the unfixed tree by
# design; on the fixed tree all 11 cells PASS.)

# A1: README citation resolves to the 501 note
# BH-03(c) flip (Fix-AG): the defect was the CITATION, not the note —
# panel/README.md:103 cited README:284 (the single-page-UI bullet) for
# the 501 change-password note, which lives at README:293. The cell now
# asserts the fixed behavior: the citation in panel/README.md resolves
# to the line holding the 501 change-password note.
readme_lines = README.splitlines()
_cited = re.search(r"README:(\d+)", PANEL_README)
_note_line = next((i + 1 for i, l in enumerate(readme_lines)
                  if "501" in l and "改密" in l), None)
check("A1-readme-citation-resolves",
      _cited and _note_line and int(_cited.group(1)) == _note_line,
      "cited=%s actual=%s" % (_cited.group(1) if _cited else None, _note_line))

# A2: Worker corpus count
mjs_files = sorted(p.name for p in (TREE / "tests").glob("*.mjs"))
doc_m = re.search(r"（(\d+) 格，\n?\s*(\d+) 个探针文件", CF_README)
# the corpus list lives in the "未解决的风险" section; extract its names
# (only up to the "；其中 8 格" sentence — the red-cell sentence reuses
# shortened names like r18_malformed that are not file names).
# BH-03(c) flip (Fix-AG): the corpus grew from 19 files / 292 cells to
# 23 files / 359 cells, so the anchor can no longer be the literal
# "19 个探针文件" — find the count by regex instead.
_m_files = re.search(r"(\d+) 个探针文件", CF_README)
corpus_sec = CF_README[_m_files.start():]
corpus_sec = corpus_sec[:corpus_sec.index("；其中")]
listed = set(re.findall(r"\b([a-z][a-z0-9_]+) \d+", corpus_sec))
missing_from_doc = [f[:-4] for f in mjs_files if f[:-4] not in listed]
check("A2-corpus-count",
      doc_m and int(doc_m.group(2)) == len(mjs_files)
      and all((TREE / "tests" / (n + ".mjs")).exists() for n in listed)
      and not missing_from_doc,
      "doc claims %s files / %s cells; tree has %d .mjs; listed-but-absent=%s; "
      "tree-not-listed=%s" % (doc_m.group(2) if doc_m else "?",
                              doc_m.group(1) if doc_m else "?",
                              len(mjs_files),
                              sorted(n for n in listed
                                     if not (TREE / "tests" / (n + ".mjs")).exists()),
                              missing_from_doc))

# A3: DELIVERY ledger/index stops at R43
check("A3-delivery-index-current",
      (TREE / "docs" / "audit" / "AUDIT-R44.md").exists()
      and (TREE / "docs" / "audit" / "AUDIT-R45.md").exists()
      and "历史台账现为 246 条" not in DELIVERY,
      "no AUDIT-R44/R45 index; DELIVERY still says 246 (R44 14 + R45 22 "
      "+ live 2 unindexed)")

# A4: Fix-N live re-proof listed as pending
check("A4-fixn-live-proof-not-pending",
      "Fix-N 真机复验待补轮" not in DELIVERY,
      "DELIVERY:218 still says 待补轮; R45 live round proved 0x502/150x200")

# A5: scan paragraph understates the scan
scan_para = DELIVERY[DELIVERY.index("凭据扫描（R41-L7-P2-3"):][:900]
check("A5-scan-paragraph-complete",
      "ta.key" in scan_para and "ENCRYPTED" in scan_para,
      "DELIVERY names 5 filenames; script also flags ta.key + "
      "ENCRYPTED/static-key blocks")

# A6: panel/README server_ip omission (behavioral proof is B2)
srv_row = [l for l in PANEL_README.splitlines()
           if "POST `/api/openvpn/server`" in l]
check("A6-panel-readme-server-row-lists-server_ip",
      bool(srv_row) and "server_ip" in srv_row[0],
      srv_row[0][:120] if srv_row else "row missing")

# ---------------------------------------------------------------- B: Flask
DATA = Path(os.environ.get("OVPN_PANEL_DATA_DIR", ""))
SK5CFG = Path(os.environ.get("OVPN_SK5_CONFIG_DIR", ""))
SECRET = os.environ.get("OVPN_PANEL_SECRET_PATH", "")
if not DATA or not SK5CFG or not SECRET:
    for n in ("B1-delete-stopped-server-note",
              "B2-server-ip-accepted-and-returned",
              "B3-status-shape", "B4-audit-cap-500",
              "B5-bundle-hash-mechanism"):
        skip(n, "no Flask harness env (OVPN_PANEL_DATA_DIR etc.)")
    print("TOTAL %d cells, FAIL %d, SKIP %d: %s"
          % (len(RESULTS), sum(1 for _, ok in RESULTS if not ok),
             len(SKIPS), [n for n, ok in RESULTS if not ok]))
    sys.exit(sum(1 for _, ok in RESULTS if not ok))

sys.path.insert(0, str(TREE / "panel"))
sys.path.insert(0, str(TREE / "core"))
sys.path.insert(0, str(TREE / "egress"))
sys.path.insert(0, str(TREE / "tests"))

# Fresh real CA via the pinned toolchain (same bootstrap as Fix-A/Fix-I).
# The /tmp toolchain cache is wiped repeatedly (tmpfs pressure), so this
# probe prefers the persistent rebuild at ~/.scratch-r46l4/toolchain and
# only falls back to the /tmp default when the persistent one is absent.
_PERSIST_TC = Path.home() / "workspace" / ".scratch-r46l4" / "toolchain"
if (_PERSIST_TC / "EasyRSA-3.1.7" / "easyrsa").exists():
    os.environ["R41A_TOOLCHAIN"] = str(_PERSIST_TC)
TC = None
CA_DIR = SERVER_DIR = None
try:
    import r41_fix_a_pki as _A
    TC = _A.bootstrap_toolchain()
except Exception as exc:  # noqa: BLE001 - toolchain unavailable -> SKIP B1
    TC = None
    print("toolchain bootstrap failed: %r" % (exc,), flush=True)

if TC is not None:
    # Set the panel/core dir env BEFORE importing openvpn_manager:
    # core reads OPENVPN_CA_DIR/OPENVPN_SERVER_DIR at import time into
    # DEFAULT_CA_DIR/DEFAULT_SERVER_DIR, and the panel calls
    # revoke_user(name) with no dir args, so a late override would leave
    # core pointed at the harness fixture dirs (and the test user would
    # land in the SHARED /tmp/r17 fixture instead of the scratch CA).
    _work = Path(tempfile.mkdtemp(prefix="r46l4-ca-"))
    CA_DIR = _work / "ca"
    SERVER_DIR = _work / "server"
    CA_DIR.mkdir(parents=True)
    SERVER_DIR.mkdir(parents=True)
    os.environ["OPENVPN_CA_DIR"] = str(CA_DIR)
    os.environ["OPENVPN_SERVER_DIR"] = str(SERVER_DIR)
    import openvpn_manager as om
    os.environ["EASYRSA_BIN"] = _A.easyrsa_bin(TC, "3.1.7")
    # easyrsa.sh needs a real `openvpn` binary for ta.key generation
    # (openvpn --genkey secret); the 2.6.14 toolchain binary provides it.
    _ovpn_env = _A.ovpn_env(TC, "2.6.14")
    os.environ["PATH"] = _ovpn_env["PATH"]
    os.environ["LD_LIBRARY_PATH"] = _ovpn_env["LD_LIBRARY_PATH"]
    om.init_pki(ca_dir=CA_DIR)
    om.build_server_cert(ca_dir=CA_DIR, server_dir=SERVER_DIR)
    om.render_server_conf(proto="udp", port=1194, server_dir=SERVER_DIR,
                          ca_dir=CA_DIR)
    os.environ["OPENVPN_CA_DIR"] = str(CA_DIR)
    os.environ["OPENVPN_SERVER_DIR"] = str(SERVER_DIR)

import app as panel_app  # noqa: E402

c = panel_app.app.test_client()
_pw = panel_app._ensure_admin_password()
assert _pw, "no admin password generated"
assert c.post("/api/login", json={"password": _pw}).status_code == 200

# B1: DELETE on a stopped server (no unit, no PID file in the sandbox).
if TC is None:
    skip("B1-delete-stopped-server-note", "no real easy-rsa toolchain")
else:
    r = c.post("/api/openvpn/users", json={"name": "l4alice"})
    created = r.status_code == 200
    if not created:
        check("B1-delete-stopped-server-note", False,
              "create user failed: %s %s" % (r.status_code, r.get_data(as_text=True)[:200]))
    else:
        r = c.delete("/api/openvpn/users/l4alice")
        d = r.get_json(silent=True) or {}
        # BH-03(c) flip (Fix-AG): the audit cell pinned the defective
        # doc claim (revoke ALWAYS restarts the daemon). The docs now
        # state the stopped-server case honestly (README step 3 /
        # DELIVERY §4-3 / panel/README DELETE row), and the cell
        # asserts the fixed behavior: on a stopped server the product
        # returns restarted:false with the honest "下次启动时生效"
        # note (Fix-V).
        check("B1-delete-stopped-server-note",
              r.status_code == 200 and d.get("restarted") is False
              and "下次启动时生效" in (d.get("note") or ""),
              "status=%s body=%s" % (r.status_code, str(d)[:300]))

# B2: server_ip accepted + returned (panel/README table omits it).
r = c.post("/api/openvpn/server",
           json={"port": 1194, "proto": "udp", "server_ip": "203.0.113.9"})
d = r.get_json(silent=True) or {}
srv = d.get("server", {}) if isinstance(d, dict) else {}
check("B2-server-ip-accepted-and-returned",
      r.status_code == 200 and srv.get("server_ip") == "203.0.113.9",
      "status=%s server=%s" % (r.status_code, str(srv)[:200]))

# B3: /api/status shape.
r = c.get("/api/status")
d = r.get_json(silent=True) or {}
check("B3-status-shape",
      r.status_code == 200 and all(k in d for k in
                                   ("openvpn", "sk5", "egress", "modules_missing")),
      "keys=%s" % sorted(d.keys()))

# B4: audit cap 500.
for _ in range(505):
    panel_app._audit("l4-cap-probe", detail="x")
r = c.get("/api/audit?limit=999")
d = r.get_json(silent=True) or {}
rows = d.get("rows", d.get("audit", [])) if isinstance(d, dict) else []
check("B4-audit-cap-500", len(rows) == 500, "rows=%d" % len(rows))

# B5: bundle-hash mechanism never lies about staleness.
cur = panel_app._current_bundle_sha256()
ok_hex = isinstance(cur, str) and len(cur) == 64 and all(
    ch in "0123456789abcdef" for ch in cur)
inst, out = panel_app._agent_code_status({"bundle_sha256": "0" * 64})
stale_ok = inst == "0" * 64 and out is True
inst2, out2 = panel_app._agent_code_status({})
unk_ok = inst2 is None and out2 is None
inst3, out3 = panel_app._agent_code_status({"bundle_sha256": cur}) if cur else (None, None)
match_ok = inst3 == cur and out3 is False
check("B5-bundle-hash-mechanism",
      ok_hex and stale_ok and unk_ok and match_ok,
      "current=%s stale=%s unknown=%s match=%s"
      % (str(cur)[:12], stale_ok, unk_ok, match_ok))

fails = [n for n, ok in RESULTS if not ok]
print("TOTAL %d cells, FAIL %d, SKIP %d: %s"
      % (len(RESULTS), len(fails), len(SKIPS), fails))
sys.exit(len(fails))

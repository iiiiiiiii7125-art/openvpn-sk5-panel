# AUDIT-R46 — round index (2026-11-18)

Baseline: e7f18ff (R45 live-fix integrated tip). Derivation (sixth):
behavioral diff + new-code hostile + operator journey + docs-truth +
state-machine v2 + gate/probe mutation v2 + cross-face contract v2 —
(1) does the candidate behave differently from 1.0.2 where it should
not, (2) do the new Fix-AC/AD code paths hold under hostile inputs,
(3) does the operator journey (fresh install, upgrade with stock
data, agent update, uninstall, daily use) still work end to end,
(4) is every doc claim true on the tree, (5) does the
bundle-hash / PID-parent state machine tell the truth in every
state, (6) is every gate/probe that claims to guard it actually
alive — does it FAIL on a mutant, (7) do the Flask and Worker faces
agree on every contract field. 7 parallel lanes, audit only. This
file is the round index; the full per-lane reports live in the audit
worktrees (branch `audit/r46-<lane>`, report commit per lane below).

## Totals (pre-fix)

- P0: 0, P1: 1 candidate (LIVE-R45-3, carried in from the R45 live
  re-check), P2: 17 (per-lane count; L2-2 duplicates L5-1 — one fix
  covers both).

## Per-lane findings

| Lane | Report commit | Findings |
|---|---|---|
| L1 behavioral diff | — (no commit; finding verified by coordinator direct grep) | 1 P2 (docs) |
| L2 new-code hostile | 9725051 | 2 P2 |
| L3 operator journey | 63bc9c6 | 0 |
| L4 docs-truth | 5dba89f | 7 P2 (docs) |
| L5 state-machine v2 | be04fe4 | 1 P2 |
| L6 gate/probe mutation v2 | c3e22a0 | 5 P2 (probe/docs) |
| L7 cross-face contract v2 | 44d522a | 1 P2 |

Findings: L7-1 — Worker `handleAgentPoll` drops a null/non-string
`bundle_sha256` from heartbeats (cloudflare/src/index.js:1147
typeof-string guard), so the staleness verdict freezes on the old
hash (trigger is real: install-agent.sh local-checkout branch deletes
the bundle.sha256 record); L5-1 — Worker `originBundleSha256()`
KV-caches the origin hash 1h and returns it fresh without
revalidating (index.js:1908-1920): after an upgrade a current agent
reads outdated=True (false stale) and a stale agent reads
outdated=False (false fresh — the dangerous direction, exactly what
Fix-AD was meant to kill); /api/nodes follows; self-heals ≤1h; Flask
face immediately correct; L2-1 — Flask `_current_bundle_sha256()`
memoizes the bundle hash in `_BUNDLE_SHA256_CACHE`
(panel/app.py:3231) with the false docstring "面板每次升级都重启服务"
— install.sh `_restart_panel_if_needed` restarts only on cert regen /
domain change; proven by behavior (H7c/H7d): bundle hash changed
under a live panel process, old-hash node reports outdated False
(must be True), new-hash node reports True (must be False); same
family as LIVE-R45-4; L2-2 — Worker originBundleSha256 KV 1h cache
— SAME finding as L5-1 (one fix covers both); L4-1 — README:284
cites the 501 note at README:293; L4-2 — cloudflare/README corpus
"292 格，19 文件" stale (23 .mjs files, 359 cells); L4-3 — DELIVERY
§0/§10 index stops at R43, AUDIT-R44.md/AUDIT-R45.md don't exist;
L4-4 — DELIVERY:218 still says "Fix-N 真机复验待补轮" (live proved
0×502/150×200); L4-5 — DELIVERY §9 scan paragraph omits ta.key +
ENCRYPTED/static-key blocks; L4-6 — panel/README server row omits
server_ip; L4-7 — README:169/DELIVERY:138/panel/README:41 claim
unconditional auto-restart on revoke — on a stopped server DELETE
returns restarted:false + "下次启动时生效" (product correct, docs
wrong); L1-1 — panel/README.md:103 cites "见 README:284" for the 501
note; the note is at README.md:293 (moved during the R45 fix round;
same stale-citation family as L4-1 — fix both together); L6-1 —
tests/r45_fix_ac_pidparent.py A2b can never fail —
core/openvpn_manager.py:139 `_run` echoes the full command line
(containing `--writepid`) into every failure message; L6-2 —
scripts/check-no-secrets.sh in git mode is blind to untracked files
(untracked literal PRIVATE KEY block → rc=0; after git add → rc=1);
the "gate counts only post-commit" rule is written nowhere; L6-3 —
AD Worker probe lacks cells for (a) non-string bundle_sha256
heartbeat and (b) origin-hash change inside the 1h KV TTL (product
defects are sibling lanes' findings — this is only the probe half);
L6-4 — same citation as L1-1; L6-5 — three L6-docs-probe cells fail
on a correct tree after the R45 fix round invalidated their pins
(L6-2, H17a, H3b; H6 fails transitively on D09).

## Fix round (all coordinator-verified by probe re-run)

- Fix-AE 655da7c — Flask staleness + panel restart on code change
  (L2-1, LIVE-R45-4): `_current_bundle_sha256()` recomputes every
  call; install.sh `_panel_code_hash()` restarts the panel when panel
  code changed, no-op on same-content re-run. Probe 23/23.
- Fix-AF 01a55ab — Worker staleness (L7-1, L5-1/L2-2):
  `handleAgentPoll` writes null for non-string bundle_sha256;
  `originBundleSha256()` re-fetches whenever reachable, KV 1h cache
  only as fallback. Own probe 7/7, L7 contract 23/23, L5 Worker 17/17.
- Fix-AG d314e0f — docs (L4-1..L4-7, L1-1, L6-2, L6-5): both
  284/293 citations, corpus 359/23, DELIVERY index through R45 +
  AUDIT-R44.md/AUDIT-R45.md, Fix-N line, §9 scan paragraph +
  post-commit rule in scan header, server_ip row, revoke
  stopped-server wording. L4 docs probe 11/11, F7 42/42, L6 69/69.
- Fix-AH 667b0ab + a63041e + 5242489 — LIVE-R45-3 (P1 candidate): CA
  pin, not dual-trust — agent pins the panel CA via new public
  `GET /api/agent/panel-ca` (404 falls back to leaf pin on pre-fix
  panels); existing self-signed leaf adopted as the CA verbatim;
  fresh-CA nodes flagged `cert_pin_stale` in /api/nodes + /api/status
  with a UI badge + re-pin button; panel records rotations at first
  start serving the new CA. Probe 41/41 (baseline 15/41).
- Fix-AI 6ec1885 — AC probe dead cell (L6-1): A2b asserts on the
  stderr phrase "--writepid fails" instead of the bare substring.
  Probe 8/8.
- Fix-AJ 4495b04 — LIVE-R46-1 (found in the R46 live re-check, see
  below): admin password path honours `OVPN_PANEL_ADMIN_PASS_PATH`
  (default /etc/openvpn-sk5-panel/admin.pass, production behaviour
  unchanged). Probe 7/7.
- Integrated tip 92c33d3 (merges 487ca02, b00ca3c, 748929e, e5954e8,
  b7ffade, 92c33d3); one real conflict (panel/app.py: AH's branch
  still carried the pre-AE `_BUNDLE_SHA256_CACHE` line — dropped,
  AE's recomputing function kept); integration drift fixup bf2eacd
  (501 citation 293→295, Worker corpus 359/23→406/26);
  verify-integration.sh PASS=30 FAIL=0 SKIP=0; difference set
  rescan: EMPTY.

## Live round (candidate bf2eacd, Lightsail)

Upgrade 5242489→bf2eacd with stock data, LIVE-R45-4 both directions
(panel restarts on code-only upgrade, PID 386553→393741; same-content
re-run: no restart), LIVE-R45-3 leaf-rotation re-proof (new leaf,
agent keeps polling, 0 CERTIFICATE_VERIFY_FAILED; AH files diff
vs 5242489 = 0 lines, so the AH live brick proof stands — no repeat
brick cycle), Fix-AC PID-parent proof (real binary, pid 343225 =
ps pid, ppid 1), UDP 1194 data plane (real client, bidirectional
bytes), AH 41/41 + AE 23/23 on the installed tree — 6/6 cells PASS.
One new finding: LIVE-R46-1 (P2) — probes run as root on the
machine overwrote the live /etc/openvpn-sk5-panel/admin.pass
(`_ensure_admin_password()` wrote to the hardcoded /etc path even
when OVPN_PANEL_DATA_DIR was redirected); login went 401, recovered
from backup; fixed by Fix-AJ 4495b04 (see above), live proof:
admin.pass sha256 + mtime identical before/after, login 200.

## Fresh-install test (candidate 92c33d3, Lightsail)

Uninstall, fresh install from the release tarball
(/root/ovpn-r46-final.tar.gz, OVPN_PANEL_DOMAIN=
16.146.199.68.sslip.io), agent from scratch, user journey, end state
— 6/6 cells PASS. Install log: "panel health gate passed (login +
/api/status 200)", "panel answers via domain", "forwarding gate
passed", "安装完成"; zero error/fail lines in 96 lines. New leaf
AF:38:E5:63…, new CA B6:DA:02:23… (nothing carried over); agent
pinned to the new CA with no manual --force re-pin; user fialice
.ovpn 200/5279B; real client Initialization Sequence Completed,
tun2 10.8.0.2/24, bidirectional bytes over 60 s. `cert_pin_stale`
None — correct by design (no rotation record → unknown, never lies).

## Carried forward

None — difference set EMPTY. Standing unverified items (not
blockers, carried from earlier rounds): Cloudflare Worker real
deployment (P0-1), arm64 install on a real machine, SK5 port 1001
vs 9000 unconfirmed.

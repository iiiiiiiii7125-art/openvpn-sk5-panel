# AUDIT-R44 — round index (2026-11-17)

Baseline: 46a78e8 (R43 integrated tip). Derivation: ledger + contract —
re-execute the whole audit ledger behaviorally (R1–R43), plus a
cross-face contract census and a state-machine census. 7 parallel lanes,
audit only. This file is the round index; the full per-lane reports live
in the audit worktrees (branch `audit/r44-<lane>`, report commit per
lane below).

## Totals (pre-fix)

- P0: 0, P1: 0, P2: 14 (10 product + 4 docs).

## Per-lane findings

| Lane | Report commit | Findings |
|---|---|---|
| L1 ledger A (R1–R15) | ddc6b7b | 0 |
| L2 ledger B (R16–R30) | 62bf7d2 | 0 |
| L3 ledger C (R31–R43) | f98b300 | 0 |
| L4 cross-face contract | 737e821 | 3 P2 |
| L5 state machine | 9de17f2 | 5 P2 |
| L6 docs-as-contract | 9ce3b8c | 4 P2 (docs) |
| L7 hostile v2 | b31e274 | 2 P2 |

Findings: L4-F1 — Worker `POST /api/openvpn/server` with bad proto
`sctp` / port `70000` → 202 queued, Flask 400s; L4-F2 — Worker
`POST /api/openvpn/users {"name": 123}` → 202 queued, Flask 400s
(the Fix-O hole left open on the Worker side); L4-F3 — Worker
fail-open/udp-over-tcp toggle-only update with no stored SK5 config
→ 400, Flask local 200 / remote 202; L5-F1 — `set_udp_over_tcp`
no-op wedge (same-value retry after a failed restart returns silent
200 while the daemon is down); L5-F2 — `check_health()` raises on
corrupt sk5.json, every 60 s timer tick dies; L5-F3 — stale openvpn
PID file: `server_status` reports `running=True` for an innocent
process, `stop_server` SIGTERMs it; L5-F4 — panel DELETE revoke
starts a stopped server; L5-F5 — node DELETE leaves `.ovpn` receipts,
re-registering the same node name serves the old user's credential;
L6-1 — DELIVERY §6-1 cites "README:71" for the ufw NAT/FORWARD
live-only note (the note is at README:90); L6-2 — DELIVERY §1.3 says
verify.sh "只建不删" the `verify-*` test user, but the EXIT trap
revokes it; L6-3 — docs/security.md self-test step 3 references the
nonexistent `/tmp/sec-test/run_tests.py`; L6-4 — DELIVERY §0/§10
present R39/185 as current delivery state, R41–R43 unindexed;
L7-1 — `str()` coercion defeats the isinstance guards on two more
paths (agent `action_create_server` dns, Flask `POST /api/openvpn/server`
server_ip); L7-2 — credential scan still evaded by `secret.key~`,
`.secret.key`, tarball `secret.key~`, `SECRET.KEY~`.

Ledger re-execution: L1 re-ran 122 findings (120 HOLD + 2
partial-by-design), L2 re-ran 24 (24 HOLD), L3 re-verified every
R41/R42/R43 fix by behavior (all HOLD) — 0 regressions, 0 new
findings from the ledger lanes.

## Fix round (all coordinator-verified by probe re-run)

- Fix-S ebf0b62 — entry validation (L7-1, L4-F1, L4-F2, L4-F3)
- Fix-T 91904f6 — scan evasion (L7-2)
- Fix-U 821f9af — manager-layer state honesty (L5-F1, L5-F2, L5-F3)
- Fix-V 32bf649 — panel DELETE semantics (L5-F4, L5-F5)
- Fix-W c87915c — docs (L6-1..L6-4) + round indexes AUDIT-R41/42/43
- Integrated tip 16f06c9; verify-integration.sh PASS=30 FAIL=0 SKIP=0;
  difference set rescan: 14/14 fixed, EMPTY.

## Carried forward

Harness note (not a product finding): the Fix-B driver harness
bind-mounts only /etc/hosts + /etc/openvpn-sk5-panel and leaks
`/etc/sysctl.d/99-openvpn-sk5.conf` + `/run/openvpn-sk5-panel/policy-routing.lock`
onto the host — it should bind-cover all three paths.

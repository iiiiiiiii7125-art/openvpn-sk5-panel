# AUDIT-R42 — round index (2026-11-17)

Baseline: 88b5891 (R41 integrated tip). Derivation: mechanism-family
census — each lane enumerates its family's FULL set across the whole
tree by code search, re-verifies every R41 fix in that family BY
BEHAVIOR, and hunts same-family recurrence. 7 parallel lanes, audit
only. This file is the round index; the full per-lane reports live in
the audit worktrees (branch `audit/r42-<lane>`, report commit per lane
below).

## Totals (pre-fix)

- P0: 0, P1: 3, P2: 21 — total 24, plus one transient residual (F1-7,
  not counted: Fix-G ordering leaves a ~1 s 502 window during install,
  closed by Fix-L dual-trust rotation).

## Per-lane findings

| Lane | Report commit | Findings |
|---|---|---|
| F1 PKI | 4ee2105 | 1 P1 + 5 P2 (+ F1-7 transient) |
| F2 install | ae13717 | 1 P2 |
| F3 egress | 3414f47 | 2 P1 + 3 P2 |
| F4 Worker | b8363ef | 1 P2 |
| F5 frontend | c792c9f | 4 P2 |
| F6 security | e03b475 | 2 P2 |
| F7 docs | 5e77a4d | 5 P2 (docs-only, non-blocking) |

Headline findings: F1-1 (P1) — panel-local DELETE revoke does not
restart the daemon, so a revoked cert stays valid for new connections
until a manual restart; F3-1 (P1) — agent double probe stalls the
poll loop 10–20 s; F3-2 (P1) — uncached `_outward_ip()` runs 2×5 s
HTTPS on every `/api/status` and every `.ovpn` render on fresh
installs.

## Fix round (all coordinator-verified by probe re-run)

- Fix-H c923385 — probe budget (F3-1/2/5)
- Fix-I b02f7e1 — PKI (F1-1..6, incl. revoke tombstones and expired
  server-cert renewal)
- Fix-J 000ff5d — frontend (F5-1..4)
- Fix-K 8d25dac — Worker age semantics (F4-1)
- Fix-L 301621c — scan + pid + test script + cert-regen + ordering
  (F6-1/2, F3-3/4, F2-1, F1-7 dual-trust)
- Fix-M 8128ad6 — docs + runbook (F7-1..5)
- Fix-N 6f81374 — LIVE-R42-1: one transient 502 across the panel
  restart during upgrade (Caddy `lb_try_duration 2s` retry)
- Integrated tip 9331daf, Fix-N merged to 2e08a8c;
  verify-integration.sh PASS=30 FAIL=0 SKIP=0; difference set rescan:
  24/24 fixed, EMPTY.

## Live round (candidate 9331daf, Lightsail, follow-up)

Gate on the live box 29/30 (the one FAIL is the known sandbox-premise
cell), fresh install PASS, upgrade with stock data PASS, Fix-G live
PASS, TCP 443 client PASS, status-file cross-check PASS, Fix-I F1-1
live PASS (revoked cert rejected server-side, second DELETE 409).
New finding LIVE-R42-1 (transient 502, fixed by Fix-N above). Fix-N
live proof (real upgrade, zero 502s across the restart) is still
outstanding. Browser typing test closed separately with local
Playwright against the live panel (6/6 PASS).

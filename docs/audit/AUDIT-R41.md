# AUDIT-R41 — round index (2026-11-17)

Baseline: tag 1.0.2 (commit 6d3cae5). Derivation: functional area
(install / panel / OpenVPN core / egress / agent / Worker+docs /
security), 7 parallel lanes, audit only. This file is the round index;
the full per-lane reports live in the audit worktrees
(branch `audit/r41-<lane>`, report commit per lane below).

## Totals (pre-fix)

- P0: 1, P1: 9, P2: 20 — total 30.

## Per-lane findings

| Lane | Report commit | Findings |
|---|---|---|
| L1 install | 92ac47b | 5 P1 + 3 P2 |
| L2 panel | 9dd70e1 | 2 P2 |
| L3 OpenVPN core | 4ea3a6e | 1 P0 + 2 P1 |
| L4 egress & SK5 | 9c79920 | 1 P1 + 5 P2 |
| L5 agent & queue | ac940b3 | 3 P2 |
| L6 Worker face + docs | eb98c02 | 1 P1 + 4 P2 |
| L7 security & secrets | 3c4f148 | 3 P2 |

Headline finding: L3-F1 (P0) — fresh install cannot create a CA on
easy-rsa 3.0.x (`build-ca nopass` prompts for a PEM pass phrase and
hangs up to 600 s). Scope correction: Debian 12 ships easy-rsa
3.1.0-1 and is NOT affected; affected are Ubuntu 22.04 and 20.04
(3.0.6).

## Fix round (all coordinator-verified by probe re-run)

- Fix-A 16c5db6 — PKI core + 20.04 compat (L3-F1/F2/F3, L1-1/2/4/5)
- Fix-B 501af7d — probe budget (L4-P1-1, L4-P2-5, L1-7)
- Fix-C 56f24f2 — policy routing + test script (L4-P2-1..4)
- Fix-D 8731279 — Worker parity (L5-P2-1..3, L6-P2-1/2)
- Fix-E f48639c — panel frontend (L2-P2-1/2, L6-P2-4)
- Fix-F 5afac6e — install polish + trust + docs (L7-P2-1/2/3,
  L6-P2-3, L1-6/8, L6-P1-1; incl. the Fix-F2 scan-literal follow-up)
- Fix-G 8254365 — LIVE-R41-1: upgrade breaks domain access until a
  manual panel restart (panel keeps serving the old cert after
  regeneration; Caddy trusts only the new one)
- Integrated tip 88b5891; verify-integration.sh PASS=30 FAIL=0 SKIP=0;
  difference set rescan: 30/30 fixed, EMPTY.

## Live round (candidate c5bbd61, Lightsail)

Upgrade 1.0.2 → candidate PASS, UDP data plane PASS, Fix-B live PASS.
The round stopped early when the Tailscale tunnel died mid-round;
gate-on-live-box, fresh install, TCP 443 client, status cross-check
and the live-browser typing test were NOT run in that round (closed
by the R42 follow-up live round except Fix-N live proof, still
outstanding — see AUDIT-R42.md).

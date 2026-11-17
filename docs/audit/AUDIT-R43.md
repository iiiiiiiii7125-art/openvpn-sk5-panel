# AUDIT-R43 — round index (2026-11-17)

Baseline: 2e08a8c (R42 integrated tip incl. Fix-N). Derivation: user
journey + adversarial — 6 lanes each walk one real user journey end
to end against the docs, 1 lane injects hostile inputs/failures; every
lane also re-verifies the R41/R42 fixes in its path BY BEHAVIOR.
7 parallel lanes, audit only. This file is the round index; the full
per-lane reports live in the audit worktrees (branch `audit/r43-<lane>`,
report commit per lane below).

## Totals (pre-fix)

- P0: 0, P1: 0, P2: 7 (4 product + 3 docs).

## Per-lane findings

| Lane | Report commit | Findings |
|---|---|---|
| J1 install | 3c7fb53 | 0 |
| J2 daily use | dec9b55 | 1 P2 (docs) |
| J3 SK5 / egress | 6acb3eb | 0 |
| J4 Worker / agent | 6acafd0 | 1 P2 (docs) |
| J5 frontend | d28de42 | 0 |
| J6 security | 3117741 | 0 |
| J7 hostile / failure | 9663155 | 4 P2 product + 1 P2 docs |

Findings: J2-D1 — revoke docs still demand a manual restart the
panel no longer needs (README.md:160, panel/README.md:41,
docs/DELIVERY.md:135); J4-1 — Worker corpus count 246/17, actually
292/19; J7-1 — `str()` coercion of non-string names (int/null/bool
become "123"/"None"/"True"); J7-2 — documented uninstall leaves 6
artifacts; J7-3 — non-UTF8 bytes in `agent_queue.json` raise an
uncaught `UnicodeDecodeError`, every queue op 500s until manual
deletion; J7-4 — `init_pki` silently destroys a FILE at the pki path;
J7-5 — credential-scan check 1 is exact-match only
(`secret.key.bak`, `SECRET.KEY`, trailing-space names evade it).

## Fix round (all coordinator-verified by probe re-run)

- Fix-O 7bcdf4a — strict type validation (J7-1; census of every
  `str(data.get(...))` name/username site, incl. SK5 host/password
  and the agent face)
- Fix-P 43f1bc4 — queue decode quarantine (J7-3)
- Fix-Q 48d2447 — init_pki file-at-path guard (J7-4, both layers)
- Fix-R f3f9d35 — scan evasion + docs (J7-5, J7-2, J2-D1, J4-1)
- Integrated tip 46a78e8; verify-integration.sh PASS=30 FAIL=0 SKIP=0;
  difference set rescan: 7/7 fixed, EMPTY.

## Carried forward

Fix-O observation (unproven at the time, for the next round to
verify/file): `agent/agent.py:651` `action_create_server` does
`str(params["dns"])` — a list-typed `dns` would coerce to
`"['8.8.8.8']"` into server.conf. Filed by AUDIT-R44-L7 as L7-1
(proven: dns `[8]` / `123` / `["8.8.8.8"]` land verbatim in
server.conf).

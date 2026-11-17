# AUDIT-R45 — round index (2026-11-17)

Baseline: 16f06c9 (R44 integrated tip). Derivation: invariant +
mutation — (1) does every invariant the product PROMISES (docs, code
comments, design) actually hold by behavior? (2) is every gate/probe
that claims to guard it actually alive — does it FAIL on a mutant?
7 parallel lanes, audit only. This file is the round index; the full
per-lane reports live in the audit worktrees (branch `audit/r45-<lane>`,
report commit per lane below).

## Totals (pre-fix)

- P0: 0, P1: 1 candidate, P2: 21.

## Per-lane findings

| Lane | Report commit | Findings |
|---|---|---|
| L1 docs-promised invariants | 7f09d4a | 0 |
| L2 behavior invariants | 5e0f43f | 0 |
| L3 gate/probe mutation | 20b0d95 | 5 P2 (dead cells) |
| L4 install/packaging/upgrade | e51fc42 | 3 P2 |
| L5 fresh-eyes core | 41245b4 | 8 P2 |
| L6 fresh-eyes egress/panel | cff6bbb | 1 P1 candidate + 3 P2 |
| L7 Worker/frontend/docs | c276bb6 | 2 P2 |

Findings: L3-1 — gate UI inbound-card cell greps bare "入站卡"
instead of the marker it names; L3-2 — gate agent-config cell is an
unconditional ok() that never asserts the 0600 it claims; L3-3 — F6
probe S2 never isolates check-3's static-key pattern; L3-4 — F6
probe S5 never isolates check-4; L3-5 — gate token-leak cell only
greps the failed receipt, never the succeeded one; L4-1 — 1.0.2
sidecar's bare filename breaks the DELIVERY §9 verification command
run from the repo root; L4-2 — verify.sh cleanup revokes the
`verify-*` test user only when the SK5 chain is left enabled at exit,
orphaning one live VPN credential per self-check run in the common
case; L4-3 — install.sh forwarding gate reads an unreadable sk5.json
as direct mode and dies on a healthy SK5 chain; L5-1 — `^...$`
accepts a trailing newline in usernames; L5-2 — `_validate_dns`
forbids metachars but not `\n`/`\r` (directive injection into
server.conf); L5-3 — server_ip never validated in core, `1.2.3.4\nproto
tcp` injects a line into the .ovpn; L5-4 — non-UTF8 index.txt /
tombstone / server.conf / status log lets raw `UnicodeDecodeError`
escape; L5-5 — agent `action_create_server` validates dns AFTER
`init_pki()` + `build_server_cert()`; L5-6 — `_make_ssl_context` with
a corrupt ca_cert raises raw `ssl.SSLError` instead of a clean
RuntimeError; L5-7 — `_port_occupant` names the holder by substring
(`:1194` matches 11940); L5-8 — revoke/gen-crl partial-failure wedge
(revoked cert keeps working, retry 409s, no in-product CRL repair);
L6-1 (P1 candidate) — empty/short secret.key accepted with no
validation or warning (silent self-lockout: correct-password login
500s, no session ever sticks); L6-2 — SK5 render does raw string
substitution into JSON (a `"` in the password breaks the chain, a
crafted host flips an outbound to direct); L6-3 —
policy-routing.sh `rule_exists()` unanchored grep matches
`lookup 1000`; L6-4 — `_curl_via_sk5` text=True with no decode guard
(GBK body raises UnicodeDecodeError out of test_sk5 / get_status /
check_health); L7-1 — Worker `/api/status` never surfaces
`ovpn.remote_ip` / `ovpn.remote_warning`; L7-2 — Worker-mode 对外地址
field is dead but the UI reports success.

## Fix round (all coordinator-verified by probe re-run)

- Fix-X f6ab848 — core validation + robustness (L5-1..L5-8)
- Fix-Y 32cd301 — panel/egress robustness (L6-1, L6-2, L6-4, L4-3)
- Fix-Z cd845b4 — dead gates/probes + shell rule (L3-1..L3-5, L6-3)
- Fix-AA d51fff5 — verify.sh cleanup + sidecar (L4-2, L4-1)
- Fix-AB 686cd69 — Worker remote fields (L7-1, L7-2)
- Fix-X2 0d3ad3c — panel `$` regex follow-up (L5-1 same-family
  recurrence found by Fix-X: `_NODE_NAME_RE` / `_HOST_RE`)
- Integrated tip 6eac5af; verify-integration.sh PASS=30 FAIL=0 SKIP=0;
  difference set rescan: 22/22 fixed, EMPTY.

## Live round (candidate 6eac5af, Lightsail)

Fix-N live proof: domain poll 0 × 502 / 150 × 200 across the panel
restart. Upgrade with stock data, fresh install, TCP 443, status-file
cross-check, expired server-cert renewal (Fix-I F1-3) all PASS.
Two new findings: LIVE-R45-1 (P2) — `start_server` direct fallback
dies on a missing PID parent; LIVE-R45-2 (P1 candidate) — the
R45-L6-3 fix never reached the RUNNING agent
(`/opt/ovpn-agent/egress/policy-routing.sh` is the Nov 13 copy;
install.sh never touches /opt/ovpn-agent). Fixed by Fix-AC ae98924
and Fix-AD 5db48f0 (staleness signal + `--force` update command, no
agent self-update), integrated tip e7f18ff, live re-check PASS.

## Carried forward

The R45 live re-check (candidate e7f18ff) found 2 more items, both
open at the time of this index: LIVE-R45-3 (P1 candidate) — panel
cert rotation silently bricks deployed agents' TOFU pin (agent black
~10 hours until a `--force` update re-pinned it; the panel shows
nothing except a stale last_seen); LIVE-R45-4 (P2) — pure-code
upgrades don't restart the panel (old code keeps serving
indefinitely). Both ride the R46 fix round.

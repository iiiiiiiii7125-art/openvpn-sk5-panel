# AUDIT-R47 — round index (2026-11-18)

Baseline: tag 1.0.3 (commit eedeb2b). Derivation: shipped-package-first
+ user journey + mechanism-family census of all R41–R46 fixes — (1)
does the shipped 1.0.3 package behave as its docs claim, (2) does the
operator journey (install, upgrade, daily use, uninstall) work end to
end from the user's perspective, (3) did any R41–R46 fix miss a sibling
of the same mechanism (fix-A-miss-B is the headline risk for this
round, per the 2026-11-18 00:26 order). 7 parallel lanes, audit only,
sandbox-only (test machine untouched). This file is the round index;
the full per-lane reports live in the audit worktrees (branch
`audit/r47-<lane>`, report commit per lane below).

## Totals (pre-fix, deduplicated)

- P0: 0, P1: 1 (L5-1, agent queue re-execution), P2: 30 (L3-4 duplicates
  L1-1; L3-5 local face duplicates L6-3, Worker face new).

## Per-lane findings

| Lane | Report commit | Findings |
|---|---|---|
| L1 install | 76e5c49 | 4 P2 |
| L2 panel UX | db1e035 | 2 P2 |
| L3 fix-A-miss-B census | 5dc019a | 5 P2 filed, 3 new (2 duplicates) |
| L4 OpenVPN core | 24f940b | 4 P2 |
| L5 agent + CA pin | eaddaf8 | 1 P1 + 4 P2 |
| L6 egress | 1690401 | 4 P2 |
| L7 Worker + docs + gates | 5e7f845 | 9 P2 (2 code, 7 docs) |

Findings: L1-1 — `_panel_code_hash` covers only run-panel-tls.py +
panel/, but app.py imports openvpn_manager + sk5_manager at module
level, so core/egress-only upgrades never restart the panel; L1-2 —
DNS-only server.conf re-render never takes effect (install.sh had ZERO
`systemctl restart openvpn-server` calls; the banner printed the new
DNS anyway); L1-3 — `wait_steady_active` dies on a stale NRestarts
(counter persists after a recovered auto-restart; install.sh never ran
reset-failed; the die message never named the remedy); L1-4 —
uninstall leaves the same-machine agent running (polls a dead panel
every 5 s; agent/README had NO uninstall section), NAT delete a
comment line, FORWARD deletes carried a literal `<网卡>` placeholder,
`disable --now caddy` unconditional, /var/log/openvpn + Caddy apt
source/keyring left behind; L2-1 — create-user stalls synchronously
on `detect_public_ip()` in the request path (probe: 5.5 s create);
L2-2 — auto-downloaded .ovpn can carry a LAN remote on a cold cache
(proven: download gave `remote 198.19.0.2 1194` while the public IP
was instantly reachable); L3-1 — change_password str-coerces
non-string passwords before validation (`["abcdefghij", 1]` stored as
its repr, login with the repr works); L3-2 — agent revoke restarts a
stopped server (Flask face has the was_running guard, agent face
didn't); L3-3 — Worker create_user/revoke don't validate the username
pattern (Flask 400s, Worker 202s bad names); L3-4 = duplicate of
L1-1; L3-5 = partial duplicate of L6-3 + new Worker face; L4-1 —
stop_server trusts systemctl stop rc=0 with no verification (a
direct-fallback daemon keeps running while the panel returns
running=True); L4-2 — non-UTF-8 status log makes server_status()
raise (against its "Never raises" docstring); panel then reports the
server as down; L4-3 — index/file disagreement wedges a user with no
in-product repair (revoke needs the cert file, build-client refuses
if it exists); L4-4 — server-cert expiry has no panel surface
(renew_server_cert existed CLI-only; at 825 days handshakes fail,
panel shows running=True, 0 users, no explanation); L5-1 (P1) — slow
commands get re-queued, their reports 409'd, and re-executed; after 3
retries the panel marks them failed while the agent actually ran them
(`SENT_TIMEOUT_SECONDS=120` < install_prereqs' own budget: apt
timeout=300 plus 900 s + downloads; the re-queue sweep ran on every
GET /api/cmd/<id>, which the UI's waitCmd polls every 2 s — the UI's
own waiting loop was the trigger; proven end to end: flip sent→queued
at 120.5 s mid-execution, late report → 409, re-delivery executes
twice, then "已重投 3 次，放弃"; create_user re-delivery poisons the
name — first .ovpn never stored); L5-2 — agent swallows the panel's
401 reason (bare `panel HTTP 401`; the commonest install mistake —
wrong --node-name — was undiagnosable); L5-3 — user-supplied CA-issued
panel cert: the promised leaf-pin fallback cannot work (no panel CA;
a CA-issued leaf can't anchor itself); L5-4 — no agent uninstall
path; L5-5 — `_make_ssl_context` docstring false (ca_cert REPLACES
the system store); L6-1 — unterminated `table 100` matcher in
install.sh/verify.sh/test-egress.sh (foreign `lookup 1000` →
false-PASS in SK5 mode, false-FAIL in direct mode); L6-2 —
`uot_restart_failed` marker bypassed via set_sk5 (enable() raise path
never set it) → later same-value set_udp_over_tcp returns 200
silently on a dead chain; L6-3 — SK5 host-shape validation missing on
the local save path ("not a host!!!" stored verbatim;
"proxy.iproyal.net:1080" passes both faces → enabled-but-dead chain
reported as success); L6-4 — UDP probe uses AF_INET unconditionally
→ EAFNOSUPPORT for an IPv6 relay; L7-1 — Worker has NO GET
/api/agent/panel-ca (installer 404s and leaf-pins the Cloudflare edge
cert — same brick mechanism as LIVE-R45-3); L7-2 — Worker never emits
cert_pin_stale (badge + "更新 agent" button dead in Worker mode);
L7-3..L7-9 — docs-truth items (CA-pin flow presented as universal
though server-mode-only; DELIVERY §0/§6-3 fail-closed wording reads
as its opposite; §9 header stale + manifest "21 份" vs actual 22
live-verify files; stale line cites README:198→233 and
agent.py:122-132→123-134; panel/README API table omits
/api/agent/panel-ca + nodes/cmd/audit; panel/README "只监听 8443
明文端口" wrong for production; core/README "OpenVPN 2.6" though
Ubuntu 22.04 ships 2.5.1).

## Fix round (all coordinator-verified by probe re-run)

- Fix-BA 8131e29 — install (L1-1..L1-4): hash now covers core/ +
  egress/ + unit file; DNS re-render restarts openvpn-server@server
  on actual conf change; reset-failed before the zero-restart gate +
  remedy named in the die message; new agent/uninstall-agent.sh +
  agent/README 卸载 section + paste-ready README uninstall block
  (real `ip route show default` lookup, no `<网卡>` placeholders,
  conditional caddy handling via installer-written caddy-installed
  marker). Probe tests/r47_ba_install.py 24/24 (baseline 18/23 FAIL).
- Fix-BB 46bc37c — panel/API + agent queue, the P1 (L5-1, L2-1,
  L2-2, L3-1, L5-2): GET /api/cmd/<id> no longer runs
  `_requeue_stale_sent` (reads must not mutate the queue; a sent
  command >120 s only gets a `timeout_hint`); the sweep runs only on
  the agent-poll path. Agent executed-command journal (lookup before
  execute, replays stored outcome instead of re-executing) +
  per-action idempotency (init_pki "already exists" → success;
  create_user UserAlreadyExistsError → new core `get_user_ovpn()`
  rebuilds the .ovpn; revoke_user UserAlreadyRevokedError → success
  with already_revoked). The 409 stays only for genuinely non-sent
  reports (R17-P1-1 ruling preserved). L2-1: create passes the cached
  outward IP. L2-2: download uses `_outward_ip_wait(timeout=12.0)`.
  L3-1: `_strict_str` in change_password → 400 on non-string. L5-2:
  401 reason carried into the agent exception. Probe
  tests/r47_bb_fix.py 17/17 (baseline 6/11). Lane self-caught and
  fixed an `ovpn_public_ip` bug (assigned the detector function
  instead of calling it, E5 500→200). docs/security.md updated.
- Fix-BC 37fc572 — core (L4-1..L4-4, L3-2): stop_server verifies the
  daemon actually died (SIGTERM→poll→SIGKILL); corrupt status file →
  clients=[] + status_error note, never raises; `repair_pki()` +
  `pki_disagreements()` + POST /api/openvpn/pki/repair with audit
  entry; `server_cert_info()` + /api/status carries server_cert +
  POST /api/openvpn/renew-server-cert + UI buttons; agent revoke
  was_running guard. NEW FIND fixed in the same commit (same L4-3
  family): a stray copy of another user's cert hijacked the serial
  map → create_user's legacy migration revoked the donor (proven on
  baseline); fixed three ways + cells L4-3b3/L4-3b4. Probe
  tests/r47_bc_core.py 20/20 (baseline 3/17).
- Fix-BD 840ce5f — egress (L6-1..L6-4, L3-5): table-100 matcher
  terminated in all 10 sites; set_sk5 sets uot_restart_failed before
  re-raise; shared `valid_sk5_host()` enforced on _validate, agent,
  panel local+remote (400), and Worker (`isValidSk5Host`, 400); UDP
  probe socket family from the relay via getaddrinfo. Probes:
  table100 9/9, uot 10/10, host-shape 32/32, udp-ipv6 3/3,
  worker-host 8/8.
- Fix-BE 28f24a8 — Worker + docs (L7-1..L7-9, L5-3, L5-5): Worker GET
  /api/agent/panel-ca returns **501** (not 404); installer
  distinguishes it — fails loud naming Cloudflare Worker mode + the
  CA-store remedy, never leaf-pins the edge cert (pre-fix 404 → leaf
  pin preserved for legacy panels). Worker emits `cert_pin_stale:
  null` (never lies; badge fires only on true). All L7-3..L7-9 doc
  lines fixed and re-verified; L5-3 docs + installer message now
  state the CA-issued-cert limitation honestly; L5-5 docstring
  corrected. Census: cloudflare/README 26→27 files, 406→413 cells.
- Integrated tip 6776b4a (merges e9b73f1, e88aa8e, 3162bde, e2634c8,
  f94c82a; fixups cde1f97 — Worker read-path sweep, the Flask L5-1
  defect reproduced for orphaned sent commands on the Worker face,
  probe 12/12; 6776b4a — Worker username validation, R47-L3-3, which
  the fix-brief grouping missed and the integration lane caught via
  the audit probe, probe 16/16, census 31 files / 457 cells).
  verify-integration.sh PASS=30 FAIL=0 SKIP=0; F7 corpus FAIL 1 =
  D03 only (release-lane item, §9 gold standard predates the 1.0.3
  §9 refresh — fixed at 1.0.4 packaging); difference set rescan:
  EMPTY except D03 and the standing needs-live list below.

## Live round (candidate 6776b4a, Lightsail)

In-place upgrade 1.0.3 → 6776b4a with stock data (login 200, domain
200, secret.key unchanged, agent last_seen advancing, UDP 1194, all
5 units active; /api/status carries server_cert, expires 2029-02-20,
days_left 824), L5-1 live (install_prereqs ~8 s wall time, exactly
ONE execution, retries 0 — the >120 s trip cannot be forced live:
apt warm ~3 s; the >120 s mechanism is sandbox-proven only, 130 s
command, 65 UI polls, 0 flips, late report 200), L1-2 DNS restart
(OVPN_DNS=8.8.8.8: restart logged, server.conf pushes 8.8.8.8, fresh
client PUSH_REPLY shows 8.8.8.8), L1-3 stale-NRestarts gate (SIGKILL
→ NRestarts=1 → install re-run completes, restarts=0, same pid, no
spurious restart), L1-4 agent uninstall → re-install (unit inactive,
dirs gone, last_seen frozen; re-install ACTIVE, last_seen advancing,
cert_pin_stale null), L4-1 masked-unit direct-start stop (panel
stop kills the direct daemon, running=false, port free), L4-4
renew-server-cert live (serial rotated, expiry 2029-02-20, client
reconnects), L5-2 wrong --node-name 401 reason in journalctl, L2-1
cold-cache create 920 ms, L2-2 cold-cache download 712 ms with
`remote 16.146.199.68 1194` (public, not LAN fallback), L6 live cells
(kill-switch fail-closed, fail-open, repair verb, toggle storm ×5),
CA rotation → stale badge → --force re-pin (leaf regen does not
brick; real CA rotation bricks with cert_pin_stale=true; --force
re-pin restores, pinned CA matches). All 8 sections PASS except
L5-1 marked PARTIAL-honest (see above). One new finding: LIVE-R47-1
(P2) — /api/status still reports hardcoded "dns":"1.1.1.1" (panel
FIXED_DNS static, not read from server.conf) after a DNS change
takes effect; a fix-A-miss-B sibling of L1-2, fixed both faces
(Flask 0bf1109: `_parse_server_dns()` reads server.conf, probe 9/9,
gate 30/30; Worker 9f1268b: agent get_status snapshot carries the
pushed DNS, Worker mergeServerCfg prefers it, probes Worker 9/9 +
agent 11/11, gate 30/30; merged 11e2f68 + 3de00e2, gate re-run
PASS=30 on the merged tree, both DNS probes re-run green).

## Carried forward

Difference set EMPTY except the standing needs-live list (all
sandbox-proven, live unproven by environment, never asked of the
user): merchant UDP round-trip / UoT / IPv6 relay (no SK5 credential
on the test panel), L6-2 uot marker live, L5-1 >120 s live trip,
SK5-mode false-PASS half of L6-1. Standing unverified items (not
blockers, carried from earlier rounds): Cloudflare Worker real
deployment (P0-1), arm64 install on a real machine, SK5 port 1001
vs 9000 unconfirmed. The 1.0.4 fresh-install leg runs against the
final release package before tagging (user's 2026-11-18 rule); the
1.0.3 fresh-install 6/6 (candidate 92c33d3) is not inherited as 1.0.4
evidence.

"""Regression tests for openvpn_manager._parse_status_log (BUG-9 / R2-BUG-13).

FIXTURE RULE: an OpenVPN *status file* is ALWAYS comma-separated.
v1 and v2 differ in columns and section headers, NOT in separator.
TAB separation exists only in management-interface output, never in
a status file. Two audit rounds and two fix rounds all modelled v2
as TAB and the deployed comma-v2 rows were dropped three times in a
row -- the fixtures below are the verbatim lines captured on the
Lightsail test machine (live-verify.md / live-verify-R2.md), never
re-typed shapes. The only non-verbatim row is the second client in
the comma-v2 fixture, which repeats the exact 13-field layout of
the captured alice row with different per-client values.

Run:  python3 core/tests/test_status_log.py   (no pytest needed)
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openvpn_manager import _parse_status_log  # noqa: E402

# Route A -- deployed comma-separated v2 (live-verify-R2.md SS4, verbatim).
# Debian unit passes --status-version 2; the config `status` line sets
# the path. This is the shape the panel actually reads on a live box.
COMMA_V2 = """\
OpenVPN STATISTICS
Updated,Wed Nov 12 02:06:46 2026
HEADER,CLIENT_LIST,Common Name,Real Address,Virtual Address,Virtual IPv6 Address,Bytes Received,Bytes Sent,Connected Since,Connected Since (time_t),Username,Client ID,Peer ID,Data Channel Cipher
CLIENT_LIST,alice,10.200.0.2:51829,10.8.0.2,,5457,5121,2026-11-12 02:05:09,1794449109,UNDEF,0,0,AES-256-GCM
CLIENT_LIST,bob,10.200.0.3:51200,10.8.0.3,,900,800,2026-11-12 02:06:01,1794449161,UNDEF,0,0,AES-256-GCM
ROUTING_TABLE,10.8.0.2,alice,10.200.0.2:51829,2026-11-12 02:05:09
ROUTING_TABLE,10.8.0.3,bob,10.200.0.3:51200,2026-11-12 02:06:01
GLOBAL STATS
Max bcast/mcast queue length,0
END
"""

# Route B -- real v1, bare 5-field rows under section headers
# (live-verify.md SS5: alice,10.200.0.2:43223,5011,4020,Thu Nov 12 00:32:42 2026).
BARE_V1 = """\
OpenVPN CLIENT LIST
Updated,Thu Nov 12 00:33:38 2026
Common Name,Real Address,Bytes Received,Bytes Sent,Connected Since
alice,10.200.0.2:43223,5011,4020,Thu Nov 12 00:32:42 2026
ROUTING TABLE
Virtual Address,Common Name,Real Address,Last Ref
10.8.0.2,alice,10.200.0.2:43223,Thu Nov 12 00:32:42 2026
GLOBAL STATS
Max bcast/mcast queue length,0
END
"""

# Route C -- TAB-separated v2 (management-interface shape, kept for
# tolerance; this is NOT a status-file shape).
TAB_V2 = (
    "OpenVPN STATISTICS\n"
    "Updated,Thu Nov 12 00:33:38 2026\n"
    "HEADER\tCLIENT_LIST\tCommon Name\tReal Address\tVirtual Address\t"
    "Virtual IPv6 Address\tBytes Received\tBytes Sent\tConnected Since\t"
    "Connected Since (time_t)\tUsername\tClient ID\tPeer ID\t"
    "Data Channel Cipher\n"
    "CLIENT_LIST\talice\t10.200.0.2:43223\t10.8.0.2\t\t5011\t4020\t"
    "Thu Nov 12 00:32:42 2026\t1762907562\talice\t0\t0\tAES-256-GCM\n"
    "CLIENT_LIST\tbob\t10.200.0.3:51200\t10.8.0.3\t\t900\t800\t"
    "Thu Nov 12 00:33:01 2026\t1762907581\tbob\t1\t0\tAES-256-GCM\n"
    "END\n"
)

# Route D -- prefixed 7-field form (tolerated legacy shape).
PREFIXED_7 = """\
CLIENT_LIST,carol,10.200.0.4:40000,10.8.0.4,111,222,Thu Nov 12 00:34:00 2026
"""


def _parse(text: str) -> list[dict]:
    with tempfile.NamedTemporaryFile(
        "w", suffix=".log", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(text)
        path = Path(fh.name)
    try:
        return _parse_status_log(path)
    finally:
        path.unlink(missing_ok=True)


def _check(client: dict, expected: dict) -> None:
    for key, value in expected.items():
        assert client[key] == value, (
            f"{key}: got {client[key]!r}, expected {value!r} "
            f"(client={client!r})"
        )


def test_comma_v2_deployed() -> None:
    clients = _parse(COMMA_V2)
    assert len(clients) == 2, f"comma v2: got {len(clients)} clients, want 2"
    _check(clients[0], {
        "name": "alice",
        "real_address": "10.200.0.2:51829",
        "virtual_address": "10.8.0.2",
        "bytes_received": "5457",
        "bytes_sent": "5121",
        "connected_since": "2026-11-12 02:05:09",
    })
    _check(clients[1], {
        "name": "bob",
        "real_address": "10.200.0.3:51200",
        "virtual_address": "10.8.0.3",
        "bytes_received": "900",
        "bytes_sent": "800",
        "connected_since": "2026-11-12 02:06:01",
    })


def test_bare_v1() -> None:
    clients = _parse(BARE_V1)
    assert len(clients) == 1, f"bare v1: got {len(clients)} clients, want 1"
    _check(clients[0], {
        "name": "alice",
        "real_address": "10.200.0.2:43223",
        # No virtual-address column in v1: backfilled from ROUTING TABLE.
        "virtual_address": "10.8.0.2",
        "bytes_received": "5011",
        "bytes_sent": "4020",
        "connected_since": "Thu Nov 12 00:32:42 2026",
    })


def test_tab_v2() -> None:
    clients = _parse(TAB_V2)
    assert len(clients) == 2, f"TAB v2: got {len(clients)} clients, want 2"
    _check(clients[0], {
        "name": "alice",
        "real_address": "10.200.0.2:43223",
        "virtual_address": "10.8.0.2",
        "bytes_received": "5011",
        "bytes_sent": "4020",
        "connected_since": "Thu Nov 12 00:32:42 2026",
    })
    _check(clients[1], {
        "name": "bob",
        "real_address": "10.200.0.3:51200",
        "virtual_address": "10.8.0.3",
        "bytes_received": "900",
        "bytes_sent": "800",
        "connected_since": "Thu Nov 12 00:33:01 2026",
    })


def test_prefixed_7() -> None:
    clients = _parse(PREFIXED_7)
    assert len(clients) == 1, f"7-field: got {len(clients)} clients, want 1"
    _check(clients[0], {
        "name": "carol",
        "real_address": "10.200.0.4:40000",
        "virtual_address": "10.8.0.4",
        "bytes_received": "111",
        "bytes_sent": "222",
        "connected_since": "Thu Nov 12 00:34:00 2026",
    })


def test_empty_and_missing() -> None:
    assert _parse("") == []
    assert _parse("OpenVPN STATISTICS\nEND\n") == []


TESTS = [
    test_comma_v2_deployed,
    test_bare_v1,
    test_tab_v2,
    test_prefixed_7,
    test_empty_and_missing,
]


if __name__ == "__main__":
    failed = 0
    for test in TESTS:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)

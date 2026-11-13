#!/usr/bin/env python3
"""R27 probe (r27_udp_probe_verdict.py) -- O-R18-1: /api/sk5/test's UDP
leg reported false when the upstream resolver returned an empty NOERROR
for the one fixed query name.

live-18 §4 (O-R18-1) evidence: the UDP relay worked end to end
(txid-matching 39-byte query out, 29-byte reply back, dante logs
confirm), but the reply carried ancount=0 for example.com -- while
the same resolver answered cloudflare.com (an=2) and google.com
(an=6), and 8.8.8.8 answered example.com (an=2). The probe's verdict
was `ancount >= 1` on a single fixed name via a single fixed resolver.

FIXED (R27-P2-1): the verdict is round-trip proof -- any txid-matching
legitimate DNS response (any rcode, including ancount=0 NOERROR)
passes; answer content is recorded in the probe note, never in the
verdict. Depth: on no reply / non-matching reply the probe retries
once with a second name + second resolver (cloudflare.com, 8.8.8.8).

This probe proves the verdict criterion at the pure-function level
(no sockets -- the sandbox blocks UDP sendto to ephemeral ports):
  U1 a txid-matching DNS response with ancount=0 -> verdict True
     (FLIPPED per BH-03(c): the old False pinned the defective
     behavior -- the live-18 shape: relay worked, verdict said no).
  U2 the same response with ancount=1 -> verdict True.
  U3 retry shape: two attempts (second name + second resolver),
     one sendto / one recvfrom call site inside the loop.
  U4 a txid-MISMATCH response -> verdict False (still discriminates).
  U5 a query-shaped packet (QR bit clear) -> verdict False.
  U6 the reply note records answer content ("reply NOERROR an=0").
Run: python3 tests/r27_udp_probe_verdict.py
Exit code = number of FAILs.
"""
import struct
import sys
from pathlib import Path

TREE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TREE / "egress"))

import sk5_manager as m

RESULTS = []


def cell(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + detail) if detail else ""))


def socks_udp_packet(dns_payload):
    # RSV(2) FRAG(1) ATYP(1)=ipv4 DST(4) PORT(2) + DNS.
    return (b"\x00\x00\x00\x01" + b"\x01\x01\x01\x01"
            + struct.pack(">H", 53) + dns_payload)


def dns_response(txid, ancount, name=b"example.com", flags=0x8180):
    qname = b"".join(bytes([len(p)]) + p for p in name.split(b".")) + b"\x00"
    header = struct.pack(">HHHHHH", txid, flags, 1, ancount, 0, 0)
    question = qname + struct.pack(">HH", 1, 1)
    answers = b""
    for _ in range(ancount):
        answers += (b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04"
                    + b"\x5d\xb8\xd8\x22")
    return header + question + answers


def main():
    txid = 0x1234
    # U1: the live-18 shape -- matching txid, rcode 0, ancount 0.
    # FIXED: round-trip proof, an empty NOERROR now passes.
    pkt0 = socks_udp_packet(dns_response(txid, 0))
    cell("U1 txid-matching NOERROR with ancount=0 -> verdict True "
         "(live-18 shape: relay worked, probe now agrees)",
         m._parse_socks_udp_dns_reply(pkt0, txid) is True)
    # U2: same packet with one answer -> True.
    pkt1 = socks_udp_packet(dns_response(txid, 1))
    cell("U2 txid-matching response with ancount=1 -> verdict True",
         m._parse_socks_udp_dns_reply(pkt1, txid) is True)
    # U3: retry shape, by source inspection of the probe function:
    # two attempts (second name + second resolver), exactly one
    # sendto / one recvfrom call site inside the loop.
    src = (TREE / "egress" / "sk5_manager.py").read_text(encoding="utf-8")
    body = src.split("def _socks5_udp_associate_dns(")[1].split(
        "def _udp_probe_via_uot_singbox")[0]
    cell("U3 retry shape: two attempts (second name + resolver), "
         "one sendto + one recvfrom call site",
         "attempts = [" in body
         and src.count("DNS_QUERY_NAME2 =") == 1
         and src.count("DNS_SERVER2 =") == 1
         and body.count("sendto(") == 1
         and body.count("recvfrom(") == 1,
         "sendto=%d recvfrom=%d names2=%d resolvers2=%d" % (
             body.count("sendto("), body.count("recvfrom("),
             src.count("DNS_QUERY_NAME2 ="), src.count("DNS_SERVER2 =")))
    # U4: txid mismatch still fails -- the verdict discriminates.
    pkt_bad_txid = socks_udp_packet(dns_response(0x5678, 1))
    cell("U4 txid-mismatch response -> verdict False",
         m._parse_socks_udp_dns_reply(pkt_bad_txid, txid) is False)
    # U5: a query-shaped packet (QR bit clear) is not a response.
    pkt_query = socks_udp_packet(dns_response(txid, 0, flags=0x0100))
    cell("U5 query-shaped packet (QR clear) -> verdict False",
         m._parse_socks_udp_dns_reply(pkt_query, txid) is False)
    # U6: answer content is recorded in the note, not the verdict.
    cell("U6 reply note records answer content",
         m._dns_reply_note(pkt0, txid) == "reply NOERROR an=0"
         and m._dns_reply_note(pkt1, txid) == "reply NOERROR an=1"
         and m._dns_reply_note(pkt_bad_txid, txid) == "",
         repr(m._dns_reply_note(pkt0, txid)))
    fails = sum(1 for _, ok in RESULTS if not ok)
    print("r27_udp_probe_verdict: %d/%d PASS" % (len(RESULTS) - fails, len(RESULTS)))
    sys.exit(fails)


if __name__ == "__main__":
    main()

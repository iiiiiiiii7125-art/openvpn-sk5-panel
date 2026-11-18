#!/usr/bin/env python3
"""R47-BD probe 4: UDP probe with an IPv6 relay (R47-L6-4) -- fixed
behavior. _socks5_udp_associate_dns() must create its UDP socket
with the RELAY's address family: an AF_INET socket can never sendto
an IPv6 relay (EAFNOSUPPORT before any packet exists).

Method: a fake SOCKS5 on 127.0.0.1 that completes the greeting and
returns an ASSOCIATE reply with ATYP=0x04, relay ::1:53. The
sandbox blocks ALL UDP sendto with EPERM, so no reply can arrive
either way -- but the FAILURE MODE is the discriminator, recorded
by wrapping socket.socket.sendto:
  - IPv4 relay control: sendto raises EPERM (errno 1) -- the syscall
    ran, the sandbox blocked it; on a real machine the packet goes out.
  - IPv6 relay, fixed: sendto also raises EPERM -- the socket is
    AF_INET6 now and the syscall ran. On the baseline it raised
    EAFNOSUPPORT (errno -9): the address family rejected it before
    any packet existed.
Exit 0 iff both relays reach the syscall (all sendto errnos EPERM).
"""
import socket
import struct
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "egress"))
import sk5_manager as m  # noqa: E402

PASS = 0
FAIL = 0


def ok(msg):
    global PASS
    PASS += 1
    print("PASS: " + msg)


def bad(msg):
    global FAIL
    FAIL += 1
    print("FAIL: " + msg)


def fake_socks5(atyp, relay_host, relay_port):
    """One-shot fake SOCKS5: greeting, no-auth, ASSOCIATE -> relay."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        try:
            conn, _ = srv.accept()
            conn.settimeout(5)
            conn.recv(3)  # greeting
            conn.sendall(b"\x05\x00")
            conn.recv(10)  # UDP ASSOCIATE request
            if atyp == 0x01:
                body = b"\x05\x00\x00\x01" + socket.inet_aton(relay_host) \
                    + struct.pack(">H", relay_port)
            else:  # 0x04 IPv6
                body = b"\x05\x00\x00\x04" \
                    + socket.inet_pton(socket.AF_INET6, relay_host) \
                    + struct.pack(">H", relay_port)
            conn.sendall(body)
            import time
            time.sleep(2)
            conn.close()
        except OSError:
            pass
        finally:
            srv.close()

    threading.Thread(target=serve, daemon=True).start()
    return port


def probe_with_recorder(atyp, relay_host):
    calls = {"errnos": []}
    orig_sendto = socket.socket.sendto

    def recording_sendto(self, data, addr):
        try:
            return orig_sendto(self, data, addr)
        except OSError as exc:
            calls["errnos"].append(exc.errno)
            raise

    socket.socket.sendto = recording_sendto
    try:
        port = fake_socks5(atyp, relay_host, 53)
        ok_flag, _ms, note = m._socks5_udp_associate_dns(
            "127.0.0.1", port, "", "", timeout=5)
        return ok_flag, note, list(calls["errnos"])
    finally:
        socket.socket.sendto = orig_sendto


def main():
    # IPv4 relay control: sendto must reach the syscall (EPERM).
    ok4, note4, err4 = probe_with_recorder(0x01, "127.0.0.1")
    print("IPv4 relay: udp_ok=%s note=%r sendto_errnos=%s" % (ok4, note4, err4))
    if err4 and all(e == 1 for e in err4):
        ok("IPv4 relay: sendto reached the syscall (EPERM x%d)" % len(err4))
    else:
        bad("IPv4 relay: unexpected sendto errnos %s" % err4)

    # IPv6 relay: the fix -- sendto must reach the syscall too.
    ok6, note6, err6 = probe_with_recorder(0x04, "::1")
    print("IPv6 relay: udp_ok=%s note=%r sendto_errnos=%s" % (ok6, note6, err6))
    if err6 and all(e == 1 for e in err6):
        ok("IPv6 relay: sendto reached the syscall (EPERM x%d -- AF_INET6 "
           "socket, no EAFNOSUPPORT)" % len(err6))
    else:
        bad("IPv6 relay: sendto errnos %s (EAFNOSUPPORT -9 means the "
            "socket is still AF_INET)" % err6)
    if not ok6 and "no txid-matching reply" in note6:
        ok("IPv6 relay: udp_ok=False with 'no txid-matching reply' "
           "(sandbox blocks the packet, same as the IPv4 control)")
    else:
        bad("IPv6 relay: unexpected verdict ok=%s note=%r" % (ok6, note6))

    print("result: PASS=%d FAIL=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

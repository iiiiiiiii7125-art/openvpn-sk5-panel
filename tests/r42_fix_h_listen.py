#!/usr/bin/env python3
"""R42-FIX-H blackhole hold listener (AUDIT-R42, lane F3).

Binds 127.0.0.3:80, :443 and :1080 and accepts connections but never
replies, so any client with a socket timeout hangs for the full
budget -- the same shape as a dead merchant / dead DNS path, without
relying on the sandbox EPERM artifact. /etc/hosts (bind-mounted by
the driver) maps api.ipify.org and ifconfig.me to 127.0.0.3, so the
panel's detect_public_ip() HTTPS probes and the egress curl probes
all land here and hang.

Usage (inside the netns, started by tests/r42_f3_inner.sh):
  python3 tests/r42_f3_listen.py
"""
import socket
import threading

ADDRS = [("127.0.0.3", 80), ("127.0.0.3", 443), ("127.0.0.3", 1080)]


def hold(addr):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(64)
    while True:
        try:
            conn, _ = s.accept()
        except OSError:
            return
        # Never reply, never close: the peer hangs until its own
        # timeout fires. Hold the socket open in a daemon thread so
        # the accept loop keeps serving.
        threading.Thread(target=lambda c=conn: c.recv(65536),
                         daemon=True).start()


def main():
    threads = []
    for addr in ADDRS:
        t = threading.Thread(target=hold, args=(addr,), daemon=True)
        t.start()
        threads.append(t)
    print("R42FIXH listen: holding %s" % (ADDRS,), flush=True)
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()

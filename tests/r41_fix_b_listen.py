#!/usr/bin/env python3
"""Fix-B netns listener (AUDIT-R41).

Runs INSIDE the probe netns (see tests/r41_fix_b_driver.sh):

- fast: a stub HTTP server on 127.0.0.1:80 answering "203.0.113.7\\n"
  to every request (ifconfig.me resolves to 127.0.0.1 via the
  bind-mounted /etc/hosts). Models a healthy ifconfig.me.
- blackhole: hold listeners on 127.0.0.3:80 and 127.0.0.3:1080 that
  accept and never reply (ifconfig.me resolves to 127.0.0.3). This is
  L1's method (R41-L1-G): curl then times out on its --max-time
  exactly like the user's box (exit 28, ~10 s). A DNS-forwarder
  blackhole does NOT reproduce it (glibc TCP-DNS reads ignore the
  timeout and hang 180 s+).

Runs in the foreground; the driver kills it when the cell is done.
"""
import argparse
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Stub(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"203.0.113.7\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _hold(port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.3", port))
    srv.listen(64)
    while True:
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        # Hold the connection open forever; never reply, never close.
        threading.Thread(target=_keep, args=(conn,), daemon=True).start()


def _keep(conn):
    try:
        while True:
            time.sleep(3600)
    finally:
        try:
            conn.close()
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["fast", "blackhole"])
    args = ap.parse_args()
    if args.mode == "fast":
        ThreadingHTTPServer(("127.0.0.1", 80), _Stub).serve_forever()
    threads = [threading.Thread(target=_hold, args=(p,), daemon=True)
               for p in (80, 1080)]
    for t in threads:
        t.start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()

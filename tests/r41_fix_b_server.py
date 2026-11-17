#!/usr/bin/env python3
"""Tiny TLS runner for the Fix-B live gate replay (e2e only).

Serves the real Flask panel from $R41B_TREE on a scratch port with a
self-signed cert, so the driver can replay the install gate's exact
curl (https://127.0.0.1:<port>/api/status) with real curl.
"""
import os
import sys

TREE = os.environ["R41B_TREE"]
for _sub in ("panel", "core", "egress"):
    sys.path.insert(0, os.path.join(TREE, _sub))

import app as panel  # noqa: E402

if __name__ == "__main__":
    panel._ensure_admin_password()
    panel.app.run(host="127.0.0.1", port=int(sys.argv[1]),
                  ssl_context=(sys.argv[2], sys.argv[3]))

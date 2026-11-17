#!/usr/bin/env python3
"""R41 Fix-E verification — Flask-side probe for the fixed index.html.

Drives the real Flask panel (test_client, in-process) against a fresh
data dir + the R17-style fixture PKI, and checks the frontend/backend
route contract mechanically:

  F1  POST /api/nodes/<name>/install is absent from url_map and 404s
      (Flask never had the route; the fix is client-side, the frontend
      no longer calls it).
  F2  Header-comment parity, enumerated both ways:
      (a) every route the comment lists exists in Flask url_map;
      (b) every /api literal the frontend actually calls exists in
          Flask url_map (dynamic .../<name>/... forms normalized);
      (c) the comment lists every frontend-called route.
  F3  No api()/apiWait() call in the shipped script references /install.
  F4  GET / serves the fixed template (Worker-only note present, dead
      call string absent).

Run as nobody (the panel's test identity) with:
  runuser -u nobody -- env PYTHONPATH=<venv>/lib/python3.12/site-packages \\
    OVPN_PANEL_DATA_DIR=<data> OVPN_PANEL_SECRET_PATH=<data>/secret.key \\
    OPENVPN_CA_DIR=<fixture-ca> OPENVPN_SERVER_DIR=<fixture-server> \\
    OVPN_SK5_CONFIG_DIR=<sk5cfg> \\
    python3 <tree>/tests/r41_fix_e_flask.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "panel"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "core"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "egress"))

import app as panel  # noqa: E402

FAILURES = []


def check(name, ok, evidence=""):
    print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                       (" | " + str(evidence)[:300]) if evidence else ""),
          flush=True)
    if not ok:
        FAILURES.append(name)


DATA = os.environ["OVPN_PANEL_DATA_DIR"]
TREE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(os.path.join(TREE, "panel/templates/index.html"),
            encoding="utf-8").read()
JS = HTML.split("<script>", 1)[1].split("</script>", 1)[0]

pw = panel._ensure_admin_password()
if pw is None:
    pw = open(os.path.join(DATA, "admin.pass")).read().strip()
client = panel.app.test_client()
r = client.post("/api/login", json={"password": pw})
check("F0 login works", r.status_code == 200, r.status_code)

# --- F1: no /install route on Flask -------------------------------
# Flask names the cmd parameter <cmd_id>, the comment/frontend <id>:
# compare route shapes with parameter names normalized away.
def norm(path):
    return re.sub(r"<[^>]+>", "<>", path)


rules = set()
for rule in panel.app.url_map.iter_rules():
    for method in rule.methods - {"HEAD", "OPTIONS"}:
        rules.add((method, norm(str(rule.rule))))
check("F1a /install absent from url_map",
      not any(p.endswith("/install") for _, p in rules),
      [p for _, p in rules if "install" in p])
r = client.post("/api/nodes/node1/install", json={})
check("F1b POST /api/nodes/node1/install -> 404", r.status_code == 404,
      r.status_code)
# register a node first, then the same call must still 404 (not 200)
r = client.post("/api/nodes", json={"name": "node1",
                                    "panel_url": "https://panel.example:8443"})
check("F1c node register 201", r.status_code == 201, r.status_code)
r = client.post("/api/nodes/node1/install", json={})
check("F1d POST /install on a real node still 404", r.status_code == 404,
      r.status_code)

# --- comment parsing ----------------------------------------------
comment = re.search(r"/\* 接口与 panel/app\.py([\s\S]*?)\*/", HTML).group(0)
list_part = comment.split("注意：")[0]


def expand_comment(text):
    """Expand the comment's compact route list into (method, template)."""
    out = set()
    for m in re.finditer(r"((?:GET|POST|DELETE)(?:/(?:GET|POST|DELETE))*)\s+"
                         r"(/api/[^\s,;]+)", text):
        methods = m.group(1).split("/")
        paths = m.group(2)
        for path in paths.split(","):
            path = path.strip()
            if not path:
                continue
            # alternatives: /api/openvpn/start|stop|restart
            if "|" in path:
                head, alts = path.rsplit("/", 1)
                for alt in alts.split("|"):
                    out.update((meth, norm(head + "/" + alt)) for meth in methods)
            else:
                out.update((meth, norm(path)) for meth in methods)
    return out


comment_routes = expand_comment(list_part)
missing = sorted(m for m in comment_routes if m not in rules)
check("F2a every comment-listed route exists in Flask",
      not missing, "missing=%s" % missing)
check("F2b comment is non-trivial", len(comment_routes) >= 20,
      "routes=%d" % len(comment_routes))


def frontend_calls(js):
    """All /api calls the frontend makes, normalized to (method, template).

    Static literals come straight from the call; dynamic forms
    ("/api/nodes/" + encodeURIComponent(n.name) + "/rotate") are joined
    with <name> (or <id> for /api/cmd/) as the placeholder.
    """
    out = set()
    for line in js.splitlines():
        m = re.search(r"(?:api|apiWait|fetch)\(\s*\"([^\"]*)\"", line)
        if not m:
            m = re.search(r"href\s*=\s*withNode\(\s*\"([^\"]*)\"", line)
            if not m:
                continue
        first = m.group(1)
        rest = line[m.end():]
        suffixes = re.findall(r"\+\s*\"([^\"]*)\"", rest)
        method_m = re.search(r",\s*\"(GET|POST|DELETE|PUT|PATCH)\"", line)
        method = method_m.group(1) if method_m else "GET"
        dynamic = bool(re.search(r"\+\s*encodeURIComponent", rest))
        if first.startswith("/api/") and not dynamic:
            out.add((method, norm(first)))
        elif first.startswith("/api/"):
            out.add((method, norm(first + "<>" + "".join(suffixes))))
    return out


called = frontend_calls(JS)
check("F2c frontend call census non-trivial", len(called) >= 15,
      "calls=%d: %s" % (len(called), sorted(called)))
not_in_flask = sorted(c for c in called if c not in rules)
check("F2d every frontend-called route exists in Flask",
      not not_in_flask, "missing=%s" % not_in_flask)
not_in_comment = sorted(c for c in called if c not in comment_routes)
check("F2e comment lists every frontend-called route",
      not not_in_comment, "unlisted=%s" % not_in_comment)

# --- F3: no /install call left ------------------------------------
# The only "/install*" literal allowed is "/install-agent.sh(.sha256)"
# inside buildInstallCommand; a quoted "/install" path must be gone.
check("F3 no quoted \"/install\" path literal left in the script",
      not re.search(r"\"/install\"", JS), "")

# --- F4: served template is the fixed one -------------------------
r = client.get("/")
body = r.get_data(as_text=True)
check("F4a GET / serves index.html", r.status_code == 200, r.status_code)
check("F4b served page carries the Worker-only note",
      "仅 Cloudflare Worker 实现" in body, "")
check("F4c served page has no dead /install call string",
      '"/install", "POST"' not in body and
      '+ "/install"' not in body, "")
check("F4d served page has the P2-2 dirty guard",
      "portDirty" in body and "protoDirty" in body, "")

print("ALL PASS" if not FAILURES else "%d FAILURES: %s"
      % (len(FAILURES), FAILURES))
sys.exit(0 if not FAILURES else 1)

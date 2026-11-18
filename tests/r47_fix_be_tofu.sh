#!/usr/bin/env bash
# R47 Fix-BE: behavioral proof of the installer trust decision after
# the L7-1 / L5-3 fixes. Extracts the REAL trust-decision python from
# THIS TREE's agent/install-agent.sh (lines between <<'PYEOF' and
# PYEOF) and runs it against four local TLS servers:
#   W   ("worker"): self-signed leaf + /api/agent/panel-ca -> 501
#       (what the Worker serves after R47-L7-1). Expectation:
#       mode=error naming Cloudflare Worker mode -- NO leaf pin.
#   A404 ("pre-fix"): self-signed leaf + panel-ca -> 404. Expectation:
#       mode=pinned pin=leaf (old behavior preserved).
#   B   ("flask-ca", control): CA-signed leaf + panel-ca -> 200 with
#       the CA PEM. Expectation: mode=pinned pin=ca.
#   C   ("ca-issued leaf", R47-L5-3): CA-issued leaf (no CA:TRUE) +
#       panel-ca -> 404. Expectation: mode=error naming --ca-cert --
#       the leaf cannot anchor itself, so the promised leaf-pin
#       fallback is dead for exactly this case and the failure must
#       stay loud and recoverable.
# Plus two cells for R47-L5-5: the _make_ssl_context docstring must
# say ca_cert REPLACES the system store (not "an extra trust anchor"),
# and the real function must behave that way (wrong CA rejects).
# Usage: bash tests/r47_fix_be_tofu.sh (exit = FAIL count)
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d /tmp/r47be-tofu.XXXXXX)"
trap 'kill ${SRV_W:-} ${SRV_A:-} ${SRV_B:-} ${SRV_C:-} 2>/dev/null; rm -rf "$WORK"' EXIT
FAIL=0
cell() { if [ "$2" = 0 ]; then echo "PASS $1"; else echo "FAIL $1"; FAIL=$((FAIL+1)); fi; }

# --- extract the trust block from this tree's install-agent.sh ---
IA="$ROOT/agent/install-agent.sh"
START="$(grep -n "<<'PYEOF'" "$IA" | head -1 | cut -d: -f1)"
END="$(grep -n "^PYEOF$" "$IA" | head -1 | cut -d: -f1)"
[ -n "$START" ] && [ -n "$END" ] && [ "$END" -gt "$START" ] || { echo "FAIL trust-block extraction"; exit 1; }
sed -n "$((START+1)),$((END-1))p" "$IA" > "$WORK/trust.py"
python3 -m py_compile "$WORK/trust.py" && echo "PASS trust-block extracts + compiles"

# --- certs: standalone self-signed leaf (W, A404) and CA + leaf (B, C) ---
openssl req -x509 -newkey rsa:2048 -keyout "$WORK/a-key.pem" -out "$WORK/a-leaf.pem" \
  -days 2 -nodes -subj "/CN=127.0.0.1" -addext "subjectAltName=IP:127.0.0.1" 2>/dev/null
openssl req -x509 -newkey rsa:2048 -keyout "$WORK/ca-key.pem" -out "$WORK/ca.pem" \
  -days 2 -nodes -subj "/CN=r47be-test-ca" 2>/dev/null
openssl req -newkey rsa:2048 -keyout "$WORK/b-key.pem" -out "$WORK/b.csr" \
  -nodes -subj "/CN=127.0.0.1" 2>/dev/null
openssl x509 -req -in "$WORK/b.csr" -CA "$WORK/ca.pem" -CAkey "$WORK/ca-key.pem" \
  -CAcreateserial -out "$WORK/b-leaf.pem" -days 2 \
  -extfile <(printf "subjectAltName=IP:127.0.0.1") 2>/dev/null
# second CA (the "wrong CA" for the L5-5 behavior cell)
openssl req -x509 -newkey rsa:2048 -keyout "$WORK/ca2-key.pem" -out "$WORK/ca2.pem" \
  -days 2 -nodes -subj "/CN=r47be-wrong-ca" 2>/dev/null

# --- tiny TLS servers: W=501, A404=404, B=200 CA PEM, C=404 (CA leaf) ---
cat > "$WORK/serve.py" <<'PYEOF'
import http.server, ssl, sys
mode, cert, key, ca_pem, port = sys.argv[1:6]
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/agent/panel-ca":
            if mode == "B":
                body = open(ca_pem, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "application/x-pem-file")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body); return
            if mode == "W":
                body = b'{"ok":false,"error":"Cloudflare mode: no panel CA"}'
                self.send_response(501)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body); return
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            body = b'{"ok":false,"error":"unknown agent interface"}'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); return
        self.send_response(200); self.send_header("Content-Length", "2")
        self.end_headers(); self.wfile.write(b"{}")
    def log_message(self, *a): pass
srv = http.server.HTTPServer(("127.0.0.1", int(port)), H)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(cert, key)
srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
srv.serve_forever()
PYEOF
python3 "$WORK/serve.py" W "$WORK/a-leaf.pem" "$WORK/a-key.pem" "$WORK/ca.pem" 18453 &
SRV_W=$!
python3 "$WORK/serve.py" A "$WORK/a-leaf.pem" "$WORK/a-key.pem" "$WORK/ca.pem" 18454 &
SRV_A=$!
python3 "$WORK/serve.py" B "$WORK/b-leaf.pem" "$WORK/b-key.pem" "$WORK/ca.pem" 18455 &
SRV_B=$!
python3 "$WORK/serve.py" C "$WORK/b-leaf.pem" "$WORK/b-key.pem" "$WORK/ca.pem" 18456 &
SRV_C=$!
sleep 1

# --- run the real trust decision against each server ---
run_trust() {
  python3 "$WORK/trust.py" "https://127.0.0.1:$1" auto "$WORK/pin-$1.pem" 2>/dev/null
}
_jget() { printf '%s' "$1" | python3 -c "import json,sys; print(json.load(sys.stdin).get('$2') or '')"; }

W_JSON="$(run_trust 18453)"; echo "mode W: $W_JSON"
[ "$(_jget "$W_JSON" mode)" = "error" ] && case "$W_JSON" in *"Cloudflare Worker mode"*) true;; *) false;; esac
cell "T1 Worker 501: trust decision fails loud, no leaf pin" $?
[ "$(_jget "$W_JSON" pin)" = "" ]; cell "T1b Worker 501: no pin written" $?

A_JSON="$(run_trust 18454)"; echo "mode A404: $A_JSON"
[ "$(_jget "$A_JSON" mode)" = "pinned" ] && [ "$(_jget "$A_JSON" pin)" = "leaf" ]
cell "T2 pre-fix 404: trust decision leaf-pins (old behavior kept)" $?

B_JSON="$(run_trust 18455)"; echo "mode B: $B_JSON"
[ "$(_jget "$B_JSON" mode)" = "pinned" ] && [ "$(_jget "$B_JSON" pin)" = "ca" ]
cell "T3 control: trust decision CA-pins" $?

C_JSON="$(run_trust 18456)"; echo "mode C: $C_JSON"
[ "$(_jget "$C_JSON" mode)" = "error" ] && case "$C_JSON" in *"--ca-cert"*) true;; *) false;; esac
cell "T4 CA-issued leaf + 404: install dies naming --ca-cert (L5-3)" $?

# --- R47-L5-5: docstring text + matching behavior ---
python3 - "$ROOT/agent/agent.py" <<'PYEOF'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
i = src.index("def _make_ssl_context")
doc = src[i:src.index('"""', src.index('"""', i) + 3) + 3]
ok = ("REPLACES the system store" in doc
      and "extra trust anchor" not in doc)
print("docstring ok" if ok else "docstring WRONG:\n" + doc)
sys.exit(0 if ok else 1)
PYEOF
cell "T5 _make_ssl_context docstring says REPLACES, not extra anchor" $?

# Behavior: real agent._make_ssl_context(ca_cert=wrong-CA) must reject
# the B/C leaf served on 18455 (system store is never consulted).
python3 - "$ROOT/agent" "$WORK/ca2.pem" 18455 <<'PYEOF'
import socket, ssl, sys
sys.path.insert(0, sys.argv[1])
import agent as agent_mod
ctx = agent_mod._make_ssl_context({"ca_cert": sys.argv[2],
                                   "panel_url": "https://127.0.0.1",
                                   "node_token": "t", "node_name": "n"})
try:
    with socket.create_connection(("127.0.0.1", int(sys.argv[3])), timeout=5) as s:
        with ctx.wrap_socket(s, server_hostname="127.0.0.1"):
            pass
    print("UNEXPECTED: wrong-CA context verified the leaf")
    sys.exit(1)
except ssl.SSLCertVerificationError:
    print("wrong-CA context rejects the leaf (store replaced, as documented)")
    sys.exit(0)
PYEOF
cell "T6 behavior: wrong-CA context rejects the leaf (L5-5)" $?

echo "TOTAL FAIL=$FAIL"
exit "$FAIL"

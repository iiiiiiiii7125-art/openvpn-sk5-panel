#!/usr/bin/env python3
"""R42 Fix-L consolidated probe — scan + pid + test script + regen + ordering.

Covers all six Fix-L findings on the REAL code (no copies of product
logic), negative-controlled against baseline 88b5891 (every defect
cell FAILs there, every guard cell passes there):

  S1  scan flags ENCRYPTED PRIVATE KEY (F6-1; via tests/r42_f6_security.py)
  S2  scan flags OpenVPN static key in a benign-named file (F6-1,
      check 3 -- R45-L3-3: planted in notes.txt so ONLY check 3 can
      flag it; the old ta.key name let check 1 flag it by filename)
  S2b scan flags ta.key by filename alone (check 1 -- keeps the
      filename half now that S2 no longer plants that name)
  S3  scan passes a clean non-git tree in disk mode (F6-2; same)
  S4  scan flags plain RSA private key (control; same)
  S5  scan flags a release tarball listing ta.key (F6-1, check 4 --
      R45-L3-4: tarball source lives OUTSIDE the scan target, so only
      the tarball entry can trigger; the old in-target pkg/ta.key let
      check 1 flag the loose file instead)
  S6  scan passes a release tarball with only benign entries (control)
  P1  _pid_is_singbox rejects a sleep with argv[0]="sing-box"
      (F3-3; via tests/r42_f3_pid.py -- that probe exits 0 iff the
      defect reproduces, so this cell wants rc != 0 + NOT-CONFIRMED)
  P2  _pid_is_singbox accepts the Fix-C fake-script daemon (guard:
      its exe is /bin/sh, its argv path element names sing-box)
  P3  _pid_is_singbox rejects a plain sleep pid reuser (guard)
  R1  test-egress.sh §1 FAILs on a lookup-1000 rule (F3-4, netns)
  R2  test-egress.sh §1 PASSes on a lookup-100 rule (control, netns)
  C1..C7  cert-regen restart matrix (F2-1; via
      tests/r42_f2_cert_regen_restart.py, 9/9)
  O1  bundle construction precedes the first Caddy reload (F1-7, static)
  O2  prune reload follows the panel restart call (F1-7, static)
  O3  behavioral dual-trust sequence (F1-7): stub systemctl records
      the CA-copy cert count at each reload/restart while driving the
      REAL domain section -- reload#1 sees the bundle (2 certs),
      restart sees the bundle, prune reload sees new-only (1 cert).
  O4  same harness with regen=0 (control): single cert throughout,
      exactly one reload, no prune reload.

F1-7 NOTE (adjudication, read before "fixing" O1/O2): a plain
reorder -- restart the panel BEFORE Caddy reloads -- does NOT remove
the ~1 s window, it only moves it. Caddy holds its trusted CA pool
in memory until a reload, so after a restart-first the panel serves
the NEW cert while Caddy still trusts only the OLD one: same 502,
other phase. Dual-trust (old+new through the transition, prune
after the restart) is the only ordering that closes it, and it
REQUIRES the first reload to precede the restart (to load the
bundle). So the F1 probe's H7 cell -- which pins "reload precedes
restart ⇒ window remains" -- is superseded: its line-order fact
still holds, its conclusion does not. H7 must be flipped BH-03(c)
to assert the bundle mechanism (O1-O3 here), not the line order.

Run: python3 tests/r42_fix_l.py [tree]   (default: this tree)
Exit code = number of FAILs. Needs: openssl CLI, unshare (userns),
bash. The F6-probe Flask cell needs R42F1_VENV-style env: pass
R42FIXL_VENV=/path/to/venv (default /tmp/r41-l5-venv) and fixture
dirs R42FIXL_CA / R42FIXL_SERVER (defaults /tmp/r17/fixture-ca and
/tmp/r17/fixture-server); if the venv is missing that cell SKIPs.
Host /etc: the netns cells pre-create /etc/openvpn-sk5-panel as a
mountpoint and remove it afterwards; the O3 harness uses the real
/etc/caddy and removes it afterwards. Both are verified empty/absent
at the end of the run.
"""
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name
          + ((" | " + str(detail)[:300]) if detail else ""), flush=True)


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def openssl(*args, check=True):
    return run(["openssl"] + list(args), check=check)


# ---------------------------------------------------------------- scan --
SCAN = str(ROOT / "scripts" / "check-no-secrets.sh")


def scratch_repo():
    d = tempfile.mkdtemp(prefix="r42fixl-repo-")
    run(["git", "init", "-q", d], check=True)
    run(["git", "-C", d, "config", "user.email", "t@t"], check=True)
    run(["git", "-C", d, "config", "user.name", "t"], check=True)
    open(os.path.join(d, "clean.txt"), "w").write("hello\n")
    run(["git", "-C", d, "add", "clean.txt"], check=True)
    run(["git", "-C", d, "commit", "-qm", "clean"], check=True)
    return d


def plant_and_scan(relpath, content_bytes):
    d = scratch_repo()
    p = os.path.join(d, relpath)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(content_bytes)
    run(["git", "-C", d, "add", relpath], check=True)
    return run(["bash", SCAN, d]).returncode


def scan_cells():
    # Real key fixtures (openssl CLI; shapes, not secrets). The
    # static-key header is built by concatenation, never written as
    # one literal -- a check-3 that matches it must not flag this
    # probe itself (Fix-F2 lesson).
    tmp = tempfile.mkdtemp(prefix="r42fixl-keys-")
    run(["openssl", "genrsa", "-out", os.path.join(tmp, "plain.pem"),
         "2048"], check=True)
    run(["openssl", "pkcs8", "-topk8", "-inform", "PEM", "-outform",
         "PEM", "-in", os.path.join(tmp, "plain.pem"),
         "-out", os.path.join(tmp, "enc.pem"), "-passout", "pass:testpass"],
        check=True)
    plain_pem = open(os.path.join(tmp, "plain.pem"), "rb").read()
    enc_pem = open(os.path.join(tmp, "enc.pem"), "rb").read()
    assert b"BEGIN ENCRYPTED PRIVATE KEY" in enc_pem
    ta_key = (b"-----BEGIN " + b"OpenVPN Static key V1-----\n"
              + b"0123456789abcdef" * 4 + b"\n"
              + b"-----END " + b"OpenVPN Static key V1-----\n")
    check("S1 scan flags ENCRYPTED PRIVATE KEY (F6-1)",
          plant_and_scan("enc.pem", enc_pem) == 1)
    # R45-L3-3: S2 must isolate check 3's static-key pattern -- the
    # block is planted in a benign-named file, so ONLY check 3 can
    # flag it (the old ta.key name let check 1 flag it by filename
    # alone, and the cell stayed green with check 3 removed).
    check("S2 scan flags OpenVPN static key in benign-named file (F6-1, check 3)",
          plant_and_scan("notes.txt", ta_key) == 1)
    # S2b keeps the check-1 half: a ta.key file with benign content
    # is flagged by filename alone -- this is what guards check 1's
    # ta.key entry now that S2 no longer plants that name.
    check("S2b scan flags ta.key by filename alone (check 1)",
          plant_and_scan("ta.key", b"nothing secret here\n") == 1)
    check("S4 scan flags plain RSA private key (control)",
          plant_and_scan("id_rsa.pem", plain_pem) == 1)
    # S3: disk-mode parity -- a plain copy (no .git at all) must scan
    # clean. Copies THIS tree, so it also proves the probe itself
    # and the fixed test helpers carry no flaggable literal.
    copy = tempfile.mkdtemp(prefix="r42fixl-copy-")
    shutil.copytree(ROOT, copy, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__"))
    r = run(["bash", SCAN, copy])
    check("S3 scan passes a clean non-git tree (disk mode, F6-2)",
          r.returncode == 0,
          r.stderr.strip().splitlines()[-1] if r.stderr else "")
    # S5/S6: check 4 -- release tarballs listing a sensitive entry.
    # R45-L3-4: the tarball source dir lives OUTSIDE the scan target,
    # so only the tarball entry itself can trigger check 4 (the old
    # layout kept the loose pkg/ta.key inside the target, and check 1
    # flagged it -- S5 stayed green with check 4 removed).
    for name, entries, want_rc, label in (
            ("S5 scan flags tarball listing ta.key (F6-1, check 4)",
             {"ta.key": ta_key, "README.md": b"docs\n"}, 1, "ta.key"),
            ("S6 scan passes tarball with only benign entries",
             {"README.md": b"docs\n", "app.py": b"print(1)\n"}, 0,
             "benign")):
        t = tempfile.mkdtemp(prefix="r42fixl-tar-")
        rel = os.path.join(t, "releases")
        os.makedirs(rel)
        src = tempfile.mkdtemp(prefix="r42fixl-tarsrc-")
        for fn, content in entries.items():
            with open(os.path.join(src, fn), "wb") as f:
                f.write(content)
        tar = os.path.join(rel, "ovpn-release-test.tar.gz")
        run(["tar", "czf", tar, "-C", src, "."] , check=True)
        shutil.rmtree(src, ignore_errors=True)
        r = run(["bash", SCAN, t])
        check(name, r.returncode == want_rc,
              "rc=%s (%s)" % (r.returncode, label))


# ----------------------------------------------------------------- pid --
def load_sm():
    spec = importlib.util.spec_from_file_location(
        "sm_under_test", str(ROOT / "egress" / "sk5_manager.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pid_cells():
    tmp = Path(tempfile.mkdtemp(prefix="r42fixl-pid-"))
    os.environ["OVPN_SK5_CONFIG_DIR"] = str(tmp)
    sm = load_sm()
    assert str(sm.PID_FILE).startswith(str(tmp)), sm.PID_FILE

    # P1: F3 victim -- sleep with argv[0]="sing-box" (bare claim, no
    # slash). Must NOT be judged the daemon, must survive the stop.
    victim = subprocess.Popen(["sing-box", "3600"], executable="/bin/sleep")
    try:
        time.sleep(0.2)
        sm.PID_FILE.write_text("%d\n" % victim.pid)
        is_sb = sm._pid_is_singbox(victim.pid)
        running = sm._singbox_running()
        sm._stop_singbox_direct()
        time.sleep(0.3)
        check("P1 fake argv[0] is not sing-box, survives stop (F3-3)",
              is_sb is False and running is False
              and victim.poll() is None,
              "is_sb=%s running=%s rc=%s" % (is_sb, running, victim.poll()))
    finally:
        if victim.poll() is None:
            victim.kill()
        victim.wait()
        try:
            sm.PID_FILE.unlink()
        except OSError:
            pass

    # P2: Fix-C fake-script daemon -- exe is /bin/sh, but an argv
    # element is the script PATH naming sing-box. Must still count
    # (guard: the exe-only rule would break the Fix-C probe).
    fake = tmp / "sing-box"
    fake.write_text("#!/bin/sh\n# passes `check`, stays alive on `run` until SIGTERM\n"
                    "if [ \"$1\" = check ]; then exit 0; fi\n"
                    "trap 'exit 0' TERM\nsleep 30\n", encoding="utf-8")
    fake.chmod(0o755)
    real_run = sm._run

    def fake_run(cmd, timeout=30):
        if cmd and cmd[0] == "systemctl":
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        return real_run(cmd, timeout=timeout)

    sm._run = fake_run
    sm.CONFIG_DIR = tmp
    sm.PID_FILE = tmp / "sing-box.pid"
    sm.LOG_FILE = tmp / "sing-box.log"
    sm.RENDERED_CONFIG = tmp / "sing-box.json"
    sm.RENDERED_CONFIG.write_text("{}\n", encoding="utf-8")
    sm.SINGBOX_BIN = str(fake)
    try:
        sm._start_singbox()
        live_pid = int(sm.PID_FILE.read_text().strip())
        is_sb = sm._pid_is_singbox(live_pid)
        running = sm._singbox_running()
        sm._stop_singbox_direct()
        time.sleep(0.5)
        alive = False
        try:
            alive = os.kill(live_pid, 0) is None
        except OSError:
            alive = False
        # A reaped zombie still answers kill(pid, 0); check /proc stat.
        try:
            with open("/proc/%d/stat" % live_pid, "rb") as f:
                alive = f.read().rsplit(b")", 1)[1].split()[0] != b"Z"
        except OSError:
            alive = False
        check("P2 script-path daemon still counts + stop kills it (guard)",
              is_sb is True and running is True and not alive
              and not sm.PID_FILE.exists(),
              "is_sb=%s running=%s alive=%s" % (is_sb, running, alive))
    except RuntimeError as e:
        check("P2 script-path daemon still counts + stop kills it (guard)",
              False, "start raised: %s" % str(e)[:100])
    finally:
        sm._run = real_run

    # P3: plain sleep pid reuser (guard).
    victim3 = subprocess.Popen(["sleep", "300"])
    try:
        time.sleep(0.2)
        sm.PID_FILE.write_text(str(victim3.pid) + "\n", encoding="utf-8")
        check("P3 plain sleep reuser is not sing-box (guard)",
              sm._pid_is_singbox(victim3.pid) is False
              and sm._singbox_running() is False)
    finally:
        victim3.terminate()
        victim3.wait()
        try:
            sm.PID_FILE.unlink()
        except OSError:
            pass

# ---------------------------------------------------------------- rule --
RULE_DRIVER = r"""#!/usr/bin/env bash
# Parameterized §1 netns driver (adapted from tests/r42_f3_rule1000.sh):
# installs a lookup-<TABLE> rule + a live table-100 route, runs the real
# test-egress.sh, prints the §1 line and _rule_present(). Always exits 0.
set -u
TABLE="__TABLE__"
EGRESS_SH="__EGRESS_SH__"
MOD="__MOD__"
if [ -z "${IN_NS:-}" ]; then
    mkdir -p /etc/openvpn-sk5-panel
    unshare --user --map-root-user --net --mount env IN_NS=1 "$0"
    RC=$?
    rmdir /etc/openvpn-sk5-panel 2>/dev/null || true
    exit "$RC"
fi
S="$(mktemp -d /tmp/r42fixl-ns-XXXXXX)"
mkdir -p "$S/bin" "$S/cfg" "$S/mod"
cp "$MOD" "$S/mod/sk5_manager.py"
cat > "$S/bin/curl" <<'EOF'
#!/bin/sh
for a in "$@"; do
  if [ "$a" = "--socks5-hostname" ]; then
    if [ -n "${STUB_SK5:-}" ]; then printf '%s\n' "$STUB_SK5"; exit 0; else exit 7; fi
  fi
done
if [ -n "${STUB_DIRECT:-}" ]; then printf '%s\n' "$STUB_DIRECT"; exit 0; else exit 7; fi
EOF
chmod +x "$S/bin/curl"
export PATH="$S/bin:$PATH"
printf '%s\n' '{"host": "proxy.example.net", "port": 1001, "username": "", "password": ""}' > "$S/cfg/sk5.json"
mount --bind "$S/cfg" /etc/openvpn-sk5-panel
ip link set lo up
ip link add eth0 type veth peer name eth0p
ip link set eth0 up; ip link set eth0p up
ip addr add 192.168.0.2/24 dev eth0
ip route add default via 192.168.0.1 dev eth0
ip link add tun0 type veth peer name tun0p
ip link set tun0 up; ip link set tun0p up
ip addr add 10.8.0.1/24 dev tun0
ip link add tun1 type veth peer name tun1p
ip link set tun1 up; ip link set tun1p up
ip addr add 10.9.0.1/30 dev tun1
ip rule add from 10.8.0.0/24 lookup "$TABLE" prio 100
ip route add default via 10.9.0.1 dev tun1 table 100
GOT="$(PYTHONPATH="$S/mod" python3 -c "import sk5_manager as sm; print('rule_present=%s' % sm._rule_present())")"
echo "RULE_PRESENT=$GOT"
STUB_DIRECT="198.51.100.1" STUB_SK5="203.0.113.7" bash "$EGRESS_SH" >"$S/out" 2>&1
S1="$(grep -E '^(PASS|FAIL):' "$S/out" | sed -n '1p')"
echo "S1_LINE=$S1"
rm -rf "$S"
exit 0
"""


def rule_cells():
    tmp = Path(tempfile.mkdtemp(prefix="r42fixl-rule-"))
    driver = tmp / "driver.sh"
    for table, want_pass, label in (
            ("1000", False, "R1 §1 FAILs on a lookup-1000 rule (F3-4)"),
            ("100", True, "R2 §1 PASSes on a lookup-100 rule (control)")):
        driver.write_text(RULE_DRIVER.replace("__TABLE__", table)
                          .replace("__EGRESS_SH__",
                                   str(ROOT / "egress" / "test-egress.sh"))
                          .replace("__MOD__",
                                   str(ROOT / "egress" / "sk5_manager.py")),
                          encoding="utf-8")
        driver.chmod(0o755)
        r = run(["bash", str(driver)])
        s1 = next((ln.split("=", 1)[1] for ln in r.stdout.splitlines()
                   if ln.startswith("S1_LINE=")), "")
        rp = next((ln.split("=", 1)[1] for ln in r.stdout.splitlines()
                   if ln.startswith("RULE_PRESENT=")), "")
        is_pass = s1.startswith("PASS:")
        check(label, is_pass == want_pass
              and ("rule_present=%s" % str(want_pass).lower()) in rp
              .replace("True", "true").replace("False", "false"),
              "%s | %s" % (s1, rp))


# ------------------------------------------------- subprocessed probes --
def subprocess_cells():
    # F2: regen matrix (9/9). Runs against THIS tree.
    f2 = ROOT / "tests" / "r42_f2_cert_regen_restart.py"
    r = run([sys.executable, str(f2), str(ROOT)])
    check("C1-C7 cert-regen restart matrix 9/9 (F2-1)",
          r.returncode == 0 and "PASS=9" in r.stdout,
          r.stdout.strip().splitlines()[-1] if r.stdout else "")
    # F3 pid probe: exits 0 iff the defect reproduces, so the FIXED
    # tree wants rc != 0 + NOT-CONFIRMED (flip documented, defect gone).
    f3 = ROOT / "tests" / "r42_f3_pid.py"
    r = run([sys.executable, str(f3), str(ROOT / "egress" / "sk5_manager.py")])
    check("P1 F3 pid probe NOT-CONFIRMED (defect gone, F3-3)",
          r.returncode != 0 and "NOT-CONFIRMED" in r.stdout,
          r.stdout.strip().splitlines()[-1] if r.stdout else "")
    # F6: scan probe, run from a /tmp copy of THIS tree (ROOT is
    # derived from __file__), with the Flask harness env when the
    # venv + fixtures exist. Exit 0 = 6/6 (S5 skipped if no env).
    # Runs as nobody (the documented harness): as root, the S5 cell's
    # _ensure_admin_password() would write /etc/openvpn-sk5-panel/
    # admin.pass on the host (panel/app.py:129 hardcodes that path);
    # as nobody the write fails and it falls back to the fresh data
    # dir. The copy and the data dirs are made world-usable first.
    f6 = ROOT / "tests" / "r42_f6_security.py"
    copy = tempfile.mkdtemp(prefix="r42fixl-f6-")
    shutil.copytree(ROOT, copy, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__"))
    run(["chmod", "-R", "a+rX", copy], check=True)
    env = dict(os.environ)
    venv = os.environ.get("R42FIXL_VENV", "/tmp/r41-l5-venv")
    ca = os.environ.get("R42FIXL_CA", "/tmp/r17/fixture-ca")
    srv = os.environ.get("R42FIXL_SERVER", "/tmp/r17/fixture-server")
    data = tempfile.mkdtemp(prefix="r42fixl-f6-data-")
    sk5cfg = tempfile.mkdtemp(prefix="r42fixl-f6-sk5-")
    run(["chmod", "0777", data, sk5cfg], check=True)
    if os.path.isdir(venv) and os.path.isdir(ca) and os.path.isdir(srv):
        site = subprocess.run(
            ["bash", "-c", "ls -d %s/lib/python*/site-packages" % venv],
            capture_output=True, text=True).stdout.strip()
        env["PYTHONPATH"] = site
        env["OVPN_PANEL_DATA_DIR"] = data
        env["OVPN_PANEL_SECRET_PATH"] = os.path.join(data, "secret.key")
        env["OPENVPN_CA_DIR"] = ca
        env["OPENVPN_SERVER_DIR"] = srv
        env["OVPN_SK5_CONFIG_DIR"] = sk5cfg
    cmd = ["runuser", "-u", "nobody", "--", "env"]
    for k in ("PYTHONPATH", "OVPN_PANEL_DATA_DIR",
              "OVPN_PANEL_SECRET_PATH", "OPENVPN_CA_DIR",
              "OPENVPN_SERVER_DIR", "OVPN_SK5_CONFIG_DIR"):
        if k in env:
            cmd.append("%s=%s" % (k, env[k]))
    cmd += [sys.executable,
            os.path.join(copy, "tests", "r42_f6_security.py")]
    r = run(cmd)
    check("S1-S4 F6 scan probe 6/6 on a tree copy (F6-1/F6-2)",
          r.returncode == 0,
          (r.stdout.strip().splitlines()[-1] if r.stdout else "")
          + ((" | " + r.stderr.strip().splitlines()[-1])
             if r.returncode != 0 and r.stderr else ""))


# -------------------------------------------------------------- bundle --
def bundle_static_cells():
    lines = (ROOT / "install.sh").read_text().splitlines()
    idx = {}
    for i, ln in enumerate(lines):
        if 'cat "$_OLD_COPY_TMP" >> "$_CADDY_PANEL_CERT"' in ln:
            idx.setdefault("bundle_build", i)
        if "systemctl reload caddy" in ln:
            idx.setdefault("reloads", []).append(i)
        if '_restart_panel_if_needed "$_DOMAIN_CHANGED"' in ln:
            idx.setdefault("restart_call", i)
    reloads = idx.get("reloads", [])
    check("O1 bundle built before the first Caddy reload (F1-7)",
          "bundle_build" in idx and len(reloads) >= 1
          and idx["bundle_build"] < reloads[0],
          "bundle@%s reload#1@%s"
          % (idx.get("bundle_build"), reloads[0] if reloads else None))
    check("O2 prune reload follows the panel restart call (F1-7)",
          len(reloads) == 2 and "restart_call" in idx
          and reloads[0] < idx["restart_call"] < reloads[1],
          "reload#1@%s restart@%s prune-reload@%s"
          % (reloads[0] if reloads else None, idx.get("restart_call"),
             reloads[1] if len(reloads) > 1 else None))


def _bundle_harness(regen):
    """Drive the REAL domain section (fragment B) with stubbed
    externals; the stub systemctl logs the CA-copy cert count at
    each reload/restart. Returns (log_lines, final_copy_certs,
    final_copy_first_fp, new_fp, run_log)."""
    td = Path(tempfile.mkdtemp(prefix="r42fixl-o3-"))
    stubbin = td / "stubbin"
    stubbin.mkdir()
    cfg = td / "config"
    cfg.mkdir()
    (cfg / "panel.env").write_text("", encoding="utf-8")
    # Real old + new certs (distinct keys/subjects).
    old_key, old_crt = td / "old-key.pem", td / "old-cert.pem"
    new_key, new_crt = td / "new-key.pem", td / "new-cert.pem"
    openssl("req", "-x509", "-newkey", "rsa:2048", "-keyout", str(old_key),
            "-out", str(old_crt), "-days", "365", "-nodes",
            "-subj", "/CN=old.example.com")
    openssl("req", "-x509", "-newkey", "rsa:2048", "-keyout", str(new_key),
            "-out", str(new_crt), "-days", "365", "-nodes",
            "-subj", "/CN=new.example.com")
    shutil.copy(new_crt, cfg / "panel-cert.pem")
    shutil.copy(new_key, cfg / "panel-key.pem")
    new_fp = openssl("x509", "-in", str(new_crt), "-noout",
                     "-fingerprint", "-sha256").stdout.strip()
    # Pre-seed the Caddy copy with the OLD cert (the state a regen
    # run finds). /etc/caddy does not exist on this host; the
    # harness creates it and removes it afterwards.
    os.makedirs("/etc/caddy", exist_ok=True)
    shutil.copy(old_crt, "/etc/caddy/panel-cert.pem")
    log_path = td / "calls.log"
    log_path.write_text("", encoding="utf-8")
    (stubbin / "caddy").write_text(
        "#!/usr/bin/env bash\necho \"caddy $*\" >> \"%s\"\nexit 0\n"
        % (td / "caddy-calls.log"), encoding="utf-8")
    (stubbin / "getent").write_text(
        "#!/usr/bin/env bash\necho \"203.0.113.7 new.example.com\"\n",
        encoding="utf-8")
    (stubbin / "systemctl").write_text(
        "#!/usr/bin/env bash\n"
        "{\n"
        "  echo -n \"systemctl $*\"\n"
        "  case \"$1\" in\n"
        "    reload|restart)\n"
        "      if [ -f /etc/caddy/panel-cert.pem ]; then\n"
        "        echo -n \" certs=$(grep -c 'BEGIN CERTIFICATE' /etc/caddy/panel-cert.pem)\"\n"
        "      fi\n"
        "      ;;\n"
        "  esac\n"
        "  echo\n"
        "} >> \"%s\"\n"
        "if [ \"${1:-}\" = \"is-active\" ]; then exit 0; fi\n"
        "exit 0\n" % log_path, encoding="utf-8")
    (stubbin / "runuser").write_text("#!/usr/bin/env bash\nexit 1\n",
                                     encoding="utf-8")
    (stubbin / "id").write_text("#!/usr/bin/env bash\nexit 1\n",
                                encoding="utf-8")
    for p in stubbin.iterdir():
        p.chmod(0o755)
    # Extract the shipped fragments verbatim (same ranges as the
    # R35/R37 probes, plus the _restart_panel_if_needed function,
    # which lives outside both and the prune depends on).
    inst = str(ROOT / "install.sh")
    frag_a = td / "fragment-a.sh"
    frag_b = td / "fragment-b.sh"
    frag_r = td / "fragment-restart.sh"
    frag_h = td / "helpers.sh"
    run(["bash", "-c",
         "sed -n '/^# R35: remember a previously configured panel domain/,"
         "/^chmod 600 \"\\$CONFIG_DIR\\/panel.env\"/p' %s > %s"
         % (inst, frag_a)], check=True)
    run(["bash", "-c",
         "sed -n '/panel domain + reverse proxy (Caddy)/,/sing-box config/p' "
         "%s | sed '$d' > %s" % (inst, frag_b)], check=True)
    run(["bash", "-c",
         "sed -n '/^_restart_panel_if_needed() {/,/^}/p' %s > %s"
         % (inst, frag_r)], check=True)
    run(["bash", "-c",
         "sed -n '/^# R35-HELPERS-BEGIN/,/^# R35-HELPERS-END/p' %s > %s"
         % (inst, frag_h)], check=True)
    harness = td / "harness.sh"
    harness.write_text(
        "#!/usr/bin/env bash\n"
        "set -uo pipefail\n"
        "export PATH=\"%s:$PATH\"\n"
        "export CONFIG_DIR=\"%s\" SERVER_IP=203.0.113.7 PANEL_PORT=8443\n"
        "export _PUBLIC_IP=203.0.113.7\n"
        "PANEL_CERT=\"%s\"; PANEL_KEY=\"%s\"\n"
        "CA_DIR=/etc/openvpn/server/easy-rsa; SERVER_DIR=/etc/openvpn/server\n"
        "OVPN_PROTO=udp; OVPN_PORT=1194; INSTALL_ROOT=%s\n"
        "export OVPN_PANEL_DOMAIN=\"new.example.com\"\n"
        "_SERVER_IP_LINE=\"OPENVPN_SERVER_IP=203.0.113.7\"\n"
        "_PANEL_CERT_STALE=%d\n"
        "_PANEL_CERT_REGEN=%d\n"
        "_PANEL_WAS_ACTIVE=1\n"
        "_PANEL_RESTARTED=0\n"
        "log()  { echo \"LOG: $*\" >&2; }\n"
        "warn() { echo \"WARN: $*\" >&2; }\n"
        "die()  { echo \"DIE: $*\" >&2; exit 1; }\n"
        "source \"%s\"\n"
        "source \"%s\"\n"
        "source \"%s\"\n"
        "(\n"
        "    umask 077\n"
        "    source \"%s\"\n"
        "    source \"%s\"\n"
        ") </dev/null\n"
        % (stubbin, cfg, cfg / "panel-cert.pem", cfg / "panel-key.pem",
           td / "install-root", 1 if regen else 0, 1 if regen else 0,
           frag_h, frag_r, frag_a, frag_a, frag_b),
        encoding="utf-8")
    harness.chmod(0o755)
    r = run(["bash", str(harness)])
    log_lines = [ln for ln in log_path.read_text().splitlines() if ln]
    final_certs = 0
    final_fp = ""
    if os.path.exists("/etc/caddy/panel-cert.pem"):
        final_certs = int(run(["bash", "-c",
                               "grep -c 'BEGIN CERTIFICATE' "
                               "/etc/caddy/panel-cert.pem"]).stdout.strip())
        # Fingerprint of the FIRST cert in the copy.
        first = run(["bash", "-c",
                     "awk '/BEGIN CERTIFICATE/{c++} c==1' "
                     "/etc/caddy/panel-cert.pem | "
                     "openssl x509 -noout -fingerprint -sha256"])
        final_fp = first.stdout.strip()
    shutil.rmtree("/etc/caddy", ignore_errors=True)
    return log_lines, final_certs, final_fp, new_fp, r.stderr


def bundle_behavior_cells():
    log, final_certs, final_fp, new_fp, _err = _bundle_harness(regen=True)
    seq = [re.sub(r" certs=.*", "", ln) for ln in log]
    counts = [re.search(r"certs=(\d+)", ln) for ln in log]
    counts = [int(m.group(1)) for m in counts if m]
    check("O3 reload#1 loads the bundle, restart on bundle, prune to new-only (F1-7)",
          seq == ["systemctl is-active --quiet caddy",
                  "systemctl reload caddy",
                  "systemctl is-active --quiet caddy",
                  "systemctl is-active --quiet openvpn-sk5-panel",
                  "systemctl restart openvpn-sk5-panel",
                  "systemctl reload caddy"]
          and counts == [2, 2, 1]
          and final_certs == 1 and final_fp == new_fp
          and not any("restart caddy" in ln for ln in log),
          "seq=%s counts=%s final=%d fp-match=%s"
          % (seq, counts, final_certs, final_fp == new_fp))
    log0, final0, fp0, new0, _e0 = _bundle_harness(regen=False)
    seq0 = [re.sub(r" certs=.*", "", ln) for ln in log0]
    counts0 = [int(m.group(1)) for m in
               (re.search(r"certs=(\d+)", ln) for ln in log0) if m]
    check("O4 regen=0: single cert throughout, one reload, no prune (control)",
          seq0 == ["systemctl is-active --quiet caddy",
                   "systemctl reload caddy",
                   "systemctl is-active --quiet caddy",
                   "systemctl is-active --quiet openvpn-sk5-panel",
                   "systemctl restart openvpn-sk5-panel"]
          and counts0 == [1, 1]
          and final0 == 1 and fp0 == new0,
          "seq=%s counts=%s final=%d" % (seq0, counts0, final0))


# ------------------------------------------------------------------ main --
def main():
    scan_cells()
    pid_cells()
    rule_cells()
    subprocess_cells()
    bundle_static_cells()
    bundle_behavior_cells()
    fails = sum(1 for _, ok in RESULTS if not ok)
    print("\nTOTAL: PASS=%d FAIL=%d" % (len(RESULTS) - fails, fails))
    # Host hygiene: the netns driver and the bundle harness both
    # create and remove their /etc mountpoints; verify nothing leaked.
    leaked = [p for p in ("/etc/openvpn-sk5-panel", "/etc/caddy")
              if os.path.exists(p)]
    if leaked:
        print("HOST LEAK: %s still exist" % leaked)
        fails += 1
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
